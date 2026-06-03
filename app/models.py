"""Domain models for users, assignments, workout records and messages.

Plain dataclasses with ``to_dict`` helpers; persistence lives in
:mod:`app.store`. Passwords are never returned by ``public()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Role(str, Enum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    # Two admin tiers. Basic admins see only general account data; super
    # admins additionally see medical records (assignments, scores, messages).
    ADMIN_BASIC = "admin_basic"
    ADMIN_SUPER = "admin_super"


#: Roles that self-registration must never grant (created via admin flows only).
ADMIN_ROLES = (Role.ADMIN_BASIC, Role.ADMIN_SUPER)


@dataclass
class User:
    id: int
    username: str
    display_name: str
    role: Role
    password_hash: str
    salt: str

    def public(self) -> dict:
        """User info safe to expose over the API (no credentials)."""
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role.value,
        }


@dataclass
class Assignment:
    """An exercise prescription a doctor gives a patient."""

    id: int
    doctor_id: int
    patient_id: int
    exercise: str
    target_sets: int
    target_reps: int
    notes: str
    created_at: float

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "doctor_id": self.doctor_id,
            "patient_id": self.patient_id,
            "exercise": self.exercise,
            "target_sets": self.target_sets,
            "target_reps": self.target_reps,
            "notes": self.notes,
            "created_at": self.created_at,
        }


@dataclass
class WorkoutRecord:
    """The stored result of a monitored workout (sets, reps, scores)."""

    id: int
    patient_id: int
    assignment_id: Optional[int]
    exercise: str
    total_sets: int
    total_reps: int
    set_scores: List[float]
    form_score: float
    completion_ratio: Optional[float]
    overall_score: float
    created_at: float

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "assignment_id": self.assignment_id,
            "exercise": self.exercise,
            "total_sets": self.total_sets,
            "total_reps": self.total_reps,
            "set_scores": self.set_scores,
            "form_score": self.form_score,
            "completion_ratio": self.completion_ratio,
            "overall_score": self.overall_score,
            "created_at": self.created_at,
        }


@dataclass
class Message:
    """A direct message between a linked doctor and patient."""

    id: int
    sender_id: int
    recipient_id: int
    body: str
    created_at: float
    read: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "body": self.body,
            "created_at": self.created_at,
            "read": self.read,
        }
