"""SQLAlchemy-backed store — a persistent drop-in for :class:`app.store.Store`.

Implements the exact same method surface and raises the same exceptions, so the
API, analyzers and tests are unchanged. ORM rows (:mod:`app.db_models`) are
converted to the domain dataclasses (:mod:`app.models`) on the way out, keeping
the rest of the app storage-agnostic. Works with SQLite (default) and Postgres.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Dict, List, Optional

from sqlalchemy import create_engine, func, or_, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password, new_token, verify_password
from app.catalog import CatalogExercise, distinct_filters, filter_and_paginate
from app.db_models import (
    AssignmentRow,
    Base,
    CatalogExerciseRow,
    LinkRow,
    MessageRow,
    TokenRow,
    UserRow,
    WorkoutRow,
)
from app.exercises.registry import available_exercises
from app.models import ADMIN_ROLES, Assignment, Message, Role, User, WorkoutRecord
from app.store import Conflict, NotFound, PermissionDenied, StoreError
from app.workout import WorkoutSummary

# --- ORM row -> domain dataclass converters ------------------------------- #


def _user(row: Optional[UserRow]) -> Optional[User]:
    if row is None:
        return None
    return User(
        id=row.id,
        username=row.username,
        display_name=row.display_name,
        role=Role(row.role),
        password_hash=row.password_hash,
        salt=row.salt,
    )


def _assignment(row: AssignmentRow) -> Assignment:
    return Assignment(
        id=row.id,
        doctor_id=row.doctor_id,
        patient_id=row.patient_id,
        exercise=row.exercise,
        target_sets=row.target_sets,
        target_reps=row.target_reps,
        notes=row.notes,
        created_at=row.created_at,
    )


def _workout(row: WorkoutRow) -> WorkoutRecord:
    return WorkoutRecord(
        id=row.id,
        patient_id=row.patient_id,
        assignment_id=row.assignment_id,
        exercise=row.exercise,
        total_sets=row.total_sets,
        total_reps=row.total_reps,
        set_scores=list(row.set_scores or []),
        form_score=row.form_score,
        completion_ratio=row.completion_ratio,
        overall_score=row.overall_score,
        created_at=row.created_at,
    )


def _message(row: MessageRow) -> Message:
    return Message(
        id=row.id,
        sender_id=row.sender_id,
        recipient_id=row.recipient_id,
        body=row.body,
        created_at=row.created_at,
        read=row.read,
    )


def _catalog(row: CatalogExerciseRow) -> CatalogExercise:
    return CatalogExercise(
        id=row.id,
        source=row.source,
        source_id=row.source_id,
        name=row.name,
        slug=row.slug,
        category=row.category,
        difficulty=row.difficulty,
        force=row.force,
        grips=row.grips,
        primary_muscles=list(row.primary_muscles or []),
        secondary_muscles=list(row.secondary_muscles or []),
        steps=list(row.steps or []),
        details=row.details or "",
        aka=row.aka,
        video_urls=list(row.video_urls or []),
        youtube_url=row.youtube_url,
    )


class SqlStore:
    """Persistent store backed by a SQLAlchemy engine."""

    def __init__(
        self,
        url: str = "sqlite:///posture.db",
        create_all: bool = False,
        clock=time.time,
    ) -> None:
        kwargs: dict = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            # An in-memory SQLite DB only survives if every session shares one
            # connection — otherwise each session sees an empty database.
            if ":memory:" in url or url == "sqlite://":
                kwargs["poolclass"] = StaticPool
        self._engine = create_engine(url, **kwargs)
        if create_all:
            Base.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine)
        self._clock = clock

    # ----- users & auth --------------------------------------------------- #

    def create_user(self, username: str, password: str, display_name: str, role: Role) -> User:
        username = username.strip().lower()
        if not username or not password:
            raise StoreError("username and password are required")
        salt, pw_hash = hash_password(password)
        with self._Session() as s:
            if s.scalar(select(UserRow.id).where(UserRow.username == username)):
                raise Conflict(f"username '{username}' is taken")
            row = UserRow(
                username=username,
                display_name=display_name or username,
                role=Role(role).value,
                password_hash=pw_hash,
                salt=salt,
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return _user(row)

    def get_user(self, user_id: int) -> User:
        with self._Session() as s:
            row = s.get(UserRow, user_id)
            if row is None:
                raise NotFound(f"no user {user_id}")
            return _user(row)

    def get_user_by_username(self, username: str) -> Optional[User]:
        with self._Session() as s:
            return _user(
                s.scalar(select(UserRow).where(UserRow.username == username.strip().lower()))
            )

    def authenticate(self, username: str, password: str) -> Optional[User]:
        user = self.get_user_by_username(username)
        if user and verify_password(password, user.salt, user.password_hash):
            return user
        return None

    def issue_token(self, user: User) -> str:
        token = new_token()
        with self._Session() as s:
            s.add(TokenRow(token=token, user_id=user.id))
            s.commit()
        return token

    def user_for_token(self, token: Optional[str]) -> Optional[User]:
        if not token:
            return None
        with self._Session() as s:
            tok = s.get(TokenRow, token)
            return _user(s.get(UserRow, tok.user_id)) if tok else None

    def revoke_token(self, token: str) -> None:
        with self._Session() as s:
            tok = s.get(TokenRow, token)
            if tok:
                s.delete(tok)
                s.commit()

    # ----- admin / directory views --------------------------------------- #

    def all_users(self) -> List[User]:
        with self._Session() as s:
            return [_user(r) for r in s.scalars(select(UserRow).order_by(UserRow.id))]

    def has_admin(self) -> bool:
        with self._Session() as s:
            return s.scalar(
                select(UserRow.id).where(UserRow.role.in_([r.value for r in ADMIN_ROLES])).limit(1)
            ) is not None

    def role_counts(self) -> Dict[str, int]:
        with self._Session() as s:
            return dict(Counter(s.scalars(select(UserRow.role)).all()))

    # ----- doctor <-> patient links -------------------------------------- #

    def link(self, doctor_id: int, patient_id: int) -> None:
        doctor = self.get_user(doctor_id)
        patient = self.get_user(patient_id)
        if doctor.role is not Role.DOCTOR:
            raise StoreError("first user must be a doctor")
        if patient.role is not Role.PATIENT:
            raise StoreError("second user must be a patient")
        with self._Session() as s:
            if s.get(LinkRow, (doctor_id, patient_id)) is None:
                s.add(LinkRow(doctor_id=doctor_id, patient_id=patient_id))
                s.commit()

    def is_linked(self, doctor_id: int, patient_id: int) -> bool:
        with self._Session() as s:
            return s.get(LinkRow, (doctor_id, patient_id)) is not None

    def patients_of(self, doctor_id: int) -> List[User]:
        with self._Session() as s:
            ids = s.scalars(
                select(LinkRow.patient_id).where(LinkRow.doctor_id == doctor_id).order_by(LinkRow.patient_id)
            ).all()
            return [_user(s.get(UserRow, pid)) for pid in ids]

    def doctors_of(self, patient_id: int) -> List[User]:
        with self._Session() as s:
            ids = s.scalars(
                select(LinkRow.doctor_id).where(LinkRow.patient_id == patient_id).order_by(LinkRow.doctor_id)
            ).all()
            return [_user(s.get(UserRow, did)) for did in ids]

    def can_communicate(self, a_id: int, b_id: int) -> bool:
        return self.is_linked(a_id, b_id) or self.is_linked(b_id, a_id)

    # ----- assignments ---------------------------------------------------- #

    def create_assignment(
        self,
        doctor_id: int,
        patient_id: int,
        exercise: str,
        target_sets: int,
        target_reps: int,
        notes: str = "",
    ) -> Assignment:
        if not self.is_linked(doctor_id, patient_id):
            raise PermissionDenied("doctor is not linked to this patient")
        if exercise not in available_exercises():
            raise StoreError(f"unknown exercise '{exercise}'")
        if target_sets < 1 or target_reps < 1:
            raise StoreError("target_sets and target_reps must be >= 1")
        with self._Session() as s:
            row = AssignmentRow(
                doctor_id=doctor_id,
                patient_id=patient_id,
                exercise=exercise,
                target_sets=target_sets,
                target_reps=target_reps,
                notes=notes,
                created_at=self._clock(),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return _assignment(row)

    def get_assignment(self, assignment_id: int) -> Assignment:
        with self._Session() as s:
            row = s.get(AssignmentRow, assignment_id)
            if row is None:
                raise NotFound(f"no assignment {assignment_id}")
            return _assignment(row)

    def assignments_for_patient(self, patient_id: int) -> List[Assignment]:
        with self._Session() as s:
            return [
                _assignment(r)
                for r in s.scalars(
                    select(AssignmentRow).where(AssignmentRow.patient_id == patient_id).order_by(AssignmentRow.id)
                )
            ]

    def assignments_by_doctor(self, doctor_id: int) -> List[Assignment]:
        with self._Session() as s:
            return [
                _assignment(r)
                for r in s.scalars(
                    select(AssignmentRow).where(AssignmentRow.doctor_id == doctor_id).order_by(AssignmentRow.id)
                )
            ]

    def assignments_involving(self, user_id: int) -> List[Assignment]:
        with self._Session() as s:
            return [
                _assignment(r)
                for r in s.scalars(
                    select(AssignmentRow)
                    .where(or_(AssignmentRow.patient_id == user_id, AssignmentRow.doctor_id == user_id))
                    .order_by(AssignmentRow.id)
                )
            ]

    # ----- workout records ------------------------------------------------ #

    def record_workout(
        self, patient_id: int, summary: WorkoutSummary, assignment_id: Optional[int] = None
    ) -> WorkoutRecord:
        self.get_user(patient_id)  # validate existence
        with self._Session() as s:
            row = WorkoutRow(
                patient_id=patient_id,
                assignment_id=assignment_id,
                exercise=summary.exercise,
                total_sets=summary.total_sets,
                total_reps=summary.total_reps,
                set_scores=list(summary.set_scores),
                form_score=summary.form_score,
                completion_ratio=summary.completion_ratio,
                overall_score=summary.overall_score,
                created_at=self._clock(),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return _workout(row)

    def workouts_for_patient(self, patient_id: int) -> List[WorkoutRecord]:
        with self._Session() as s:
            return [
                _workout(r)
                for r in s.scalars(
                    select(WorkoutRow).where(WorkoutRow.patient_id == patient_id).order_by(WorkoutRow.id)
                )
            ]

    def get_workout(self, workout_id: int) -> WorkoutRecord:
        with self._Session() as s:
            row = s.get(WorkoutRow, workout_id)
            if row is None:
                raise NotFound(f"no workout {workout_id}")
            return _workout(row)

    def all_workouts(self) -> List[WorkoutRecord]:
        with self._Session() as s:
            return [_workout(r) for r in s.scalars(select(WorkoutRow).order_by(WorkoutRow.id))]

    # ----- messaging ------------------------------------------------------ #

    def add_message(self, sender_id: int, recipient_id: int, body: str) -> Message:
        self.get_user(sender_id)
        self.get_user(recipient_id)
        if not body.strip():
            raise StoreError("message body is empty")
        if not self.can_communicate(sender_id, recipient_id):
            raise PermissionDenied("messaging is only allowed between linked users")
        with self._Session() as s:
            row = MessageRow(
                sender_id=sender_id,
                recipient_id=recipient_id,
                body=body,
                created_at=self._clock(),
                read=False,
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return _message(row)

    def conversation(self, a_id: int, b_id: int) -> List[Message]:
        with self._Session() as s:
            rows = s.scalars(
                select(MessageRow)
                .where(
                    or_(
                        (MessageRow.sender_id == a_id) & (MessageRow.recipient_id == b_id),
                        (MessageRow.sender_id == b_id) & (MessageRow.recipient_id == a_id),
                    )
                )
                .order_by(MessageRow.id)
            )
            return [_message(r) for r in rows]

    def mark_read(self, recipient_id: int, other_id: int) -> int:
        with self._Session() as s:
            rows = s.scalars(
                select(MessageRow).where(
                    MessageRow.sender_id == other_id,
                    MessageRow.recipient_id == recipient_id,
                    MessageRow.read.is_(False),
                )
            ).all()
            for row in rows:
                row.read = True
            s.commit()
            return len(rows)

    def messages_involving(self, user_id: int) -> List[Message]:
        with self._Session() as s:
            return [
                _message(r)
                for r in s.scalars(
                    select(MessageRow)
                    .where(or_(MessageRow.sender_id == user_id, MessageRow.recipient_id == user_id))
                    .order_by(MessageRow.id)
                )
            ]

    # ----- exercise catalog ---------------------------------------------- #

    def upsert_catalog_exercises(self, exercises: List[CatalogExercise]) -> int:
        with self._Session() as s:
            for ex in exercises:
                row = s.scalar(
                    select(CatalogExerciseRow).where(
                        CatalogExerciseRow.source == ex.source,
                        CatalogExerciseRow.source_id == ex.source_id,
                    )
                )
                if row is None:
                    row = CatalogExerciseRow(source=ex.source, source_id=ex.source_id)
                    s.add(row)
                row.name = ex.name
                row.slug = ex.slug
                row.category = ex.category
                row.difficulty = ex.difficulty
                row.force = ex.force
                row.grips = ex.grips
                row.primary_muscles = list(ex.primary_muscles)
                row.secondary_muscles = list(ex.secondary_muscles)
                row.steps = list(ex.steps)
                row.details = ex.details
                row.aka = ex.aka
                row.video_urls = list(ex.video_urls)
                row.youtube_url = ex.youtube_url
            s.commit()
        return len(exercises)

    def _all_catalog(self) -> List[CatalogExercise]:
        with self._Session() as s:
            return [_catalog(r) for r in s.scalars(select(CatalogExerciseRow))]

    def catalog_count(self) -> int:
        with self._Session() as s:
            return s.scalar(select(func.count()).select_from(CatalogExerciseRow)) or 0

    def list_catalog_exercises(self, **filters):
        return filter_and_paginate(self._all_catalog(), **filters)

    def get_catalog_exercise(self, key) -> CatalogExercise:
        with self._Session() as s:
            row = None
            if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
                row = s.get(CatalogExerciseRow, int(key))
            if row is None and isinstance(key, str):
                row = s.scalar(select(CatalogExerciseRow).where(CatalogExerciseRow.slug == key))
            if row is None:
                raise NotFound(f"no catalog exercise '{key}'")
            return _catalog(row)

    def catalog_filters(self) -> dict:
        return distinct_filters(self._all_catalog())
