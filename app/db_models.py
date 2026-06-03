"""SQLAlchemy ORM models — the persistent schema behind :class:`app.sql_store.SqlStore`.

These rows are an implementation detail of the SQL store; the rest of the app
only ever sees the domain dataclasses in :mod:`app.models`. ``SqlStore``
converts between the two, so the API/analyzers/tests stay storage-agnostic.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    salt: Mapped[str] = mapped_column(String(64), nullable=False)


class TokenRow(Base):
    __tablename__ = "tokens"

    token: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)


class LinkRow(Base):
    """A doctor↔patient care relationship (composite primary key)."""

    __tablename__ = "links"

    doctor_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), primary_key=True)
    patient_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), primary_key=True)


class AssignmentRow(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doctor_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    patient_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    exercise: Mapped[str] = mapped_column(String(50), nullable=False)
    target_sets: Mapped[int] = mapped_column(Integer, nullable=False)
    target_reps: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class WorkoutRow(Base):
    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    assignment_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("assignments.id"), nullable=True)
    exercise: Mapped[str] = mapped_column(String(50), nullable=False)
    total_sets: Mapped[int] = mapped_column(Integer, nullable=False)
    total_reps: Mapped[int] = mapped_column(Integer, nullable=False)
    set_scores: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    form_score: Mapped[float] = mapped_column(Float, nullable=False)
    completion_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class MessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sender_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    recipient_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CatalogExerciseRow(Base):
    """An exercise from the reference catalog (e.g. imported from MuscleWiki)."""

    __tablename__ = "catalog_exercises"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_catalog_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(220), nullable=False, unique=True, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    difficulty: Mapped[str | None] = mapped_column(String(30), nullable=True)
    force: Mapped[str | None] = mapped_column(String(30), nullable=True)
    grips: Mapped[str | None] = mapped_column(String(50), nullable=True)
    primary_muscles: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    secondary_muscles: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    aka: Mapped[str | None] = mapped_column(String(200), nullable=True)
    video_urls: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    youtube_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
