"""In-memory data store for users, links, assignments, workouts and messages.

Deliberately simple (a dict-backed singleton) so the skeleton has no database
dependency and tests can spin up a fresh store per case. The public methods are
the seam you'd reimplement against a real DB later. Not thread-safe and not
persistent across restarts.
"""

from __future__ import annotations

import threading
import time
from itertools import count
from typing import Dict, List, Optional, Set, Tuple

from collections import Counter

from app.auth import hash_password, new_token, verify_password
from app.catalog import CatalogExercise, distinct_filters, filter_and_paginate
from app.exercises.registry import available_exercises
from app.models import ADMIN_ROLES, Assignment, Message, Role, User, WorkoutRecord
from app.workout import WorkoutSummary


class StoreError(Exception):
    """Base class for store-level validation errors."""


class NotFound(StoreError):
    pass


class Conflict(StoreError):
    pass


class PermissionDenied(StoreError):
    pass


class Store:
    def __init__(self, clock=time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._ids = count(1)

        self._users: Dict[int, User] = {}
        self._by_username: Dict[str, int] = {}
        self._tokens: Dict[str, int] = {}
        self._links: Set[Tuple[int, int]] = set()  # (doctor_id, patient_id)
        self._assignments: Dict[int, Assignment] = {}
        self._workouts: Dict[int, WorkoutRecord] = {}
        self._messages: List[Message] = []
        # Catalog keyed by (source, source_id); plus slug/id lookup indexes.
        self._catalog: Dict[tuple, CatalogExercise] = {}
        self._catalog_by_slug: Dict[str, tuple] = {}
        self._catalog_by_id: Dict[int, tuple] = {}

    def _next_id(self) -> int:
        return next(self._ids)

    # ----- users & auth --------------------------------------------------- #

    def create_user(
        self, username: str, password: str, display_name: str, role: Role
    ) -> User:
        username = username.strip().lower()
        if not username or not password:
            raise StoreError("username and password are required")
        with self._lock:
            if username in self._by_username:
                raise Conflict(f"username '{username}' is taken")
            salt, pw_hash = hash_password(password)
            user = User(
                id=self._next_id(),
                username=username,
                display_name=display_name or username,
                role=Role(role),
                password_hash=pw_hash,
                salt=salt,
            )
            self._users[user.id] = user
            self._by_username[username] = user.id
            return user

    def get_user(self, user_id: int) -> User:
        try:
            return self._users[user_id]
        except KeyError:
            raise NotFound(f"no user {user_id}") from None

    def get_user_by_username(self, username: str) -> Optional[User]:
        uid = self._by_username.get(username.strip().lower())
        return self._users.get(uid) if uid is not None else None

    # ----- admin / directory views --------------------------------------- #

    def all_users(self) -> List[User]:
        return list(self._users.values())

    def has_admin(self) -> bool:
        return any(u.role in ADMIN_ROLES for u in self._users.values())

    def role_counts(self) -> Dict[str, int]:
        return dict(Counter(u.role.value for u in self._users.values()))

    def all_workouts(self) -> List[WorkoutRecord]:
        return list(self._workouts.values())

    def assignments_involving(self, user_id: int) -> List[Assignment]:
        return [
            a
            for a in self._assignments.values()
            if a.patient_id == user_id or a.doctor_id == user_id
        ]

    def messages_involving(self, user_id: int) -> List[Message]:
        return [
            m
            for m in self._messages
            if m.sender_id == user_id or m.recipient_id == user_id
        ]

    def authenticate(self, username: str, password: str) -> Optional[User]:
        user = self.get_user_by_username(username)
        if user and verify_password(password, user.salt, user.password_hash):
            return user
        return None

    def issue_token(self, user: User) -> str:
        token = new_token()
        self._tokens[token] = user.id
        return token

    def user_for_token(self, token: Optional[str]) -> Optional[User]:
        if not token:
            return None
        uid = self._tokens.get(token)
        return self._users.get(uid) if uid is not None else None

    def revoke_token(self, token: str) -> None:
        self._tokens.pop(token, None)

    # ----- doctor <-> patient links -------------------------------------- #

    def link(self, doctor_id: int, patient_id: int) -> None:
        doctor = self.get_user(doctor_id)
        patient = self.get_user(patient_id)
        if doctor.role is not Role.DOCTOR:
            raise StoreError("first user must be a doctor")
        if patient.role is not Role.PATIENT:
            raise StoreError("second user must be a patient")
        self._links.add((doctor_id, patient_id))

    def is_linked(self, doctor_id: int, patient_id: int) -> bool:
        return (doctor_id, patient_id) in self._links

    def patients_of(self, doctor_id: int) -> List[User]:
        return [
            self._users[p] for (d, p) in self._links if d == doctor_id and p in self._users
        ]

    def doctors_of(self, patient_id: int) -> List[User]:
        return [
            self._users[d] for (d, p) in self._links if p == patient_id and d in self._users
        ]

    def can_communicate(self, a_id: int, b_id: int) -> bool:
        """True if the pair is a linked doctor/patient (either direction)."""
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
        assignment = Assignment(
            id=self._next_id(),
            doctor_id=doctor_id,
            patient_id=patient_id,
            exercise=exercise,
            target_sets=target_sets,
            target_reps=target_reps,
            notes=notes,
            created_at=self._clock(),
        )
        self._assignments[assignment.id] = assignment
        return assignment

    def get_assignment(self, assignment_id: int) -> Assignment:
        try:
            return self._assignments[assignment_id]
        except KeyError:
            raise NotFound(f"no assignment {assignment_id}") from None

    def assignments_for_patient(self, patient_id: int) -> List[Assignment]:
        return [a for a in self._assignments.values() if a.patient_id == patient_id]

    def assignments_by_doctor(self, doctor_id: int) -> List[Assignment]:
        return [a for a in self._assignments.values() if a.doctor_id == doctor_id]

    # ----- workout records ------------------------------------------------ #

    def record_workout(
        self,
        patient_id: int,
        summary: WorkoutSummary,
        assignment_id: Optional[int] = None,
    ) -> WorkoutRecord:
        self.get_user(patient_id)  # validate existence
        record = WorkoutRecord(
            id=self._next_id(),
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
        self._workouts[record.id] = record
        return record

    def workouts_for_patient(self, patient_id: int) -> List[WorkoutRecord]:
        return [w for w in self._workouts.values() if w.patient_id == patient_id]

    def get_workout(self, workout_id: int) -> WorkoutRecord:
        try:
            return self._workouts[workout_id]
        except KeyError:
            raise NotFound(f"no workout {workout_id}") from None

    # ----- messaging ------------------------------------------------------ #

    def add_message(self, sender_id: int, recipient_id: int, body: str) -> Message:
        self.get_user(sender_id)
        self.get_user(recipient_id)
        if not body.strip():
            raise StoreError("message body is empty")
        if not self.can_communicate(sender_id, recipient_id):
            raise PermissionDenied("messaging is only allowed between linked users")
        message = Message(
            id=self._next_id(),
            sender_id=sender_id,
            recipient_id=recipient_id,
            body=body,
            created_at=self._clock(),
        )
        self._messages.append(message)
        return message

    def conversation(self, a_id: int, b_id: int) -> List[Message]:
        """Messages exchanged between two users, oldest first."""
        return [
            m
            for m in self._messages
            if {m.sender_id, m.recipient_id} == {a_id, b_id}
        ]

    def mark_read(self, recipient_id: int, other_id: int) -> int:
        """Mark messages from ``other_id`` to ``recipient_id`` as read."""
        n = 0
        for m in self._messages:
            if m.sender_id == other_id and m.recipient_id == recipient_id and not m.read:
                m.read = True
                n += 1
        return n

    # ----- exercise catalog ---------------------------------------------- #

    def upsert_catalog_exercises(self, exercises: List[CatalogExercise]) -> int:
        """Insert or update catalog exercises (matched on source + source_id)."""
        for ex in exercises:
            key = (ex.source, ex.source_id)
            existing = self._catalog.get(key)
            ex.id = existing.id if existing else self._next_id()
            self._catalog[key] = ex
        self._catalog_by_slug = {e.slug: k for k, e in self._catalog.items()}
        self._catalog_by_id = {e.id: k for k, e in self._catalog.items()}
        return len(exercises)

    def _all_catalog(self) -> List[CatalogExercise]:
        return list(self._catalog.values())

    def catalog_count(self) -> int:
        return len(self._catalog)

    def list_catalog_exercises(self, **filters):
        return filter_and_paginate(self._all_catalog(), **filters)

    def get_catalog_exercise(self, key) -> CatalogExercise:
        ckey = None
        if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
            ckey = self._catalog_by_id.get(int(key))
        if ckey is None and isinstance(key, str):
            ckey = self._catalog_by_slug.get(key)
        if ckey is None:
            raise NotFound(f"no catalog exercise '{key}'")
        return self._catalog[ckey]

    def catalog_filters(self) -> dict:
        return distinct_filters(self._all_catalog())
