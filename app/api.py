"""REST API: authentication, doctor/patient management, scores and messaging.

Routes are grouped under ``/api``. The data store is read from
``request.app.state.store`` so the app (and tests) can inject a fresh one.
:class:`app.store.StoreError` subclasses are mapped to HTTP status codes by an
exception handler registered in :func:`app.server.create_app`.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.models import ADMIN_ROLES, Role, User
from app.store import Store

# --- request bodies ------------------------------------------------------- #


class RegisterIn(BaseModel):
    username: str
    password: str = Field(min_length=4)
    display_name: str = ""
    role: Role


class LoginIn(BaseModel):
    username: str
    password: str


class LinkPatientIn(BaseModel):
    patient_username: str


class AssignmentIn(BaseModel):
    patient_id: int
    exercise: str
    target_sets: int = Field(ge=1)
    target_reps: int = Field(ge=1)
    notes: str = ""


class MessageIn(BaseModel):
    recipient_id: int
    body: str = Field(min_length=1)


class BootstrapAdminIn(BaseModel):
    username: str
    password: str = Field(min_length=4)
    display_name: str = ""


class CreateAdminIn(BootstrapAdminIn):
    tier: Literal["basic", "super"] = "basic"


# --- dependencies --------------------------------------------------------- #


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_current_user(
    request: Request, authorization: Optional[str] = Header(default=None)
) -> User:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    user = get_store(request).user_for_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


def require_doctor(user: User = Depends(get_current_user)) -> User:
    if user.role is not Role.DOCTOR:
        raise HTTPException(status_code=403, detail="doctors only")
    return user


def require_patient(user: User = Depends(get_current_user)) -> User:
    if user.role is not Role.PATIENT:
        raise HTTPException(status_code=403, detail="patients only")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Any admin tier (basic or super)."""
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="admins only")
    return user


def require_super_admin(user: User = Depends(get_current_user)) -> User:
    """Full-access admin only — required for medical-record data."""
    if user.role is not Role.ADMIN_SUPER:
        raise HTTPException(status_code=403, detail="full-access admin only")
    return user


# --- router --------------------------------------------------------------- #


def build_api_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["api"])

    # ----- auth ----------------------------------------------------------- #

    @router.post("/auth/register")
    def register(body: RegisterIn, store: Store = Depends(get_store)) -> dict:
        if body.role in ADMIN_ROLES:
            # Admin accounts are created via /admin/bootstrap or by a super
            # admin, never through open self-registration.
            raise HTTPException(
                status_code=403, detail="admin accounts cannot be self-registered"
            )
        user = store.create_user(
            body.username, body.password, body.display_name, body.role
        )
        token = store.issue_token(user)
        return {"user": user.public(), "token": token}

    @router.post("/auth/login")
    def login(body: LoginIn, store: Store = Depends(get_store)) -> dict:
        user = store.authenticate(body.username, body.password)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid credentials")
        return {"user": user.public(), "token": store.issue_token(user)}

    @router.get("/auth/me")
    def me(user: User = Depends(get_current_user)) -> dict:
        return user.public()

    # ----- doctor: patients, assignments, scores -------------------------- #

    @router.post("/doctor/patients")
    def add_patient(
        body: LinkPatientIn,
        store: Store = Depends(get_store),
        doctor: User = Depends(require_doctor),
    ) -> dict:
        patient = store.get_user_by_username(body.patient_username)
        if patient is None or patient.role is not Role.PATIENT:
            raise HTTPException(status_code=404, detail="patient not found")
        store.link(doctor.id, patient.id)
        return patient.public()

    @router.get("/doctor/patients")
    def list_patients(
        store: Store = Depends(get_store), doctor: User = Depends(require_doctor)
    ) -> dict:
        return {"patients": [p.public() for p in store.patients_of(doctor.id)]}

    @router.post("/assignments")
    def create_assignment(
        body: AssignmentIn,
        store: Store = Depends(get_store),
        doctor: User = Depends(require_doctor),
    ) -> dict:
        assignment = store.create_assignment(
            doctor.id,
            body.patient_id,
            body.exercise,
            body.target_sets,
            body.target_reps,
            body.notes,
        )
        return assignment.to_dict()

    @router.get("/doctor/patients/{patient_id}/workouts")
    def patient_workouts(
        patient_id: int,
        store: Store = Depends(get_store),
        doctor: User = Depends(require_doctor),
    ) -> dict:
        if not store.is_linked(doctor.id, patient_id):
            raise HTTPException(status_code=403, detail="not your patient")
        return {
            "workouts": [w.to_dict() for w in store.workouts_for_patient(patient_id)]
        }

    @router.get("/doctor/patients/{patient_id}/assignments")
    def patient_assignments_for_doctor(
        patient_id: int,
        store: Store = Depends(get_store),
        doctor: User = Depends(require_doctor),
    ) -> dict:
        if not store.is_linked(doctor.id, patient_id):
            raise HTTPException(status_code=403, detail="not your patient")
        return {
            "assignments": [
                a.to_dict() for a in store.assignments_for_patient(patient_id)
            ]
        }

    # ----- patient: my assignments, my scores, my doctors ----------------- #

    @router.get("/me/assignments")
    def my_assignments(
        store: Store = Depends(get_store), patient: User = Depends(require_patient)
    ) -> dict:
        return {
            "assignments": [
                a.to_dict() for a in store.assignments_for_patient(patient.id)
            ]
        }

    @router.get("/me/workouts")
    def my_workouts(
        store: Store = Depends(get_store), patient: User = Depends(require_patient)
    ) -> dict:
        return {"workouts": [w.to_dict() for w in store.workouts_for_patient(patient.id)]}

    @router.get("/me/doctors")
    def my_doctors(
        store: Store = Depends(get_store), patient: User = Depends(require_patient)
    ) -> dict:
        return {"doctors": [d.public() for d in store.doctors_of(patient.id)]}

    # ----- messaging ------------------------------------------------------ #

    @router.get("/contacts")
    def contacts(
        store: Store = Depends(get_store), user: User = Depends(get_current_user)
    ) -> dict:
        if user.role is Role.DOCTOR:
            people = store.patients_of(user.id)
        else:
            people = store.doctors_of(user.id)
        return {"contacts": [p.public() for p in people]}

    @router.post("/messages")
    def send_message(
        body: MessageIn,
        store: Store = Depends(get_store),
        user: User = Depends(get_current_user),
    ) -> dict:
        message = store.add_message(user.id, body.recipient_id, body.body)
        return message.to_dict()

    @router.get("/messages/{other_id}")
    def conversation(
        other_id: int,
        store: Store = Depends(get_store),
        user: User = Depends(get_current_user),
    ) -> dict:
        store.mark_read(user.id, other_id)
        return {
            "messages": [m.to_dict() for m in store.conversation(user.id, other_id)]
        }

    # ----- exercise catalog (public reference data) ---------------------- #

    @router.get("/catalog")
    def catalog_list(
        store: Store = Depends(get_store),
        muscle: Optional[str] = None,
        category: Optional[str] = None,
        difficulty: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        items, total = store.list_catalog_exercises(
            muscle=muscle, category=category, difficulty=difficulty, q=q, limit=limit, offset=offset
        )
        return {
            "total": total,
            "count": len(items),
            "limit": limit,
            "offset": offset,
            "items": [e.to_dict() for e in items],
        }

    @router.get("/catalog/filters")
    def catalog_filters(store: Store = Depends(get_store)) -> dict:
        return store.catalog_filters()

    @router.get("/catalog/{key}")
    def catalog_get(key: str, store: Store = Depends(get_store)) -> dict:
        # `key` is a slug or a numeric id; NotFound -> 404 via the exception handler.
        return store.get_catalog_exercise(key).to_dict()

    # ----- admin: account creation --------------------------------------- #

    @router.post("/admin/bootstrap")
    def bootstrap_admin(body: BootstrapAdminIn, store: Store = Depends(get_store)) -> dict:
        """Create the first super admin. Disabled once any admin exists."""
        if store.has_admin():
            raise HTTPException(
                status_code=403,
                detail="an admin already exists; ask a full-access admin to add more",
            )
        user = store.create_user(
            body.username, body.password, body.display_name, Role.ADMIN_SUPER
        )
        return {"user": user.public(), "token": store.issue_token(user)}

    @router.post("/admin/admins")
    def create_admin(
        body: CreateAdminIn,
        store: Store = Depends(get_store),
        admin: User = Depends(require_super_admin),
    ) -> dict:
        role = Role.ADMIN_SUPER if body.tier == "super" else Role.ADMIN_BASIC
        user = store.create_user(body.username, body.password, body.display_name, role)
        return user.public()

    # ----- admin: GENERAL user data (both tiers) -------------------------- #

    @router.get("/admin/users")
    def admin_users(
        store: Store = Depends(get_store), admin: User = Depends(require_admin)
    ) -> dict:
        # public() exposes general account fields only — no medical data.
        return {"users": [u.public() for u in store.all_users()]}

    @router.get("/admin/stats")
    def admin_stats(
        store: Store = Depends(get_store), admin: User = Depends(require_admin)
    ) -> dict:
        users = store.all_users()
        return {"total_users": len(users), "by_role": store.role_counts()}

    @router.get("/admin/users/{user_id}")
    def admin_user(
        user_id: int,
        store: Store = Depends(get_store),
        admin: User = Depends(require_admin),
    ) -> dict:
        return store.get_user(user_id).public()

    # ----- admin: MEDICAL records (super admin only) ---------------------- #

    @router.get("/admin/users/{user_id}/medical")
    def admin_user_medical(
        user_id: int,
        store: Store = Depends(get_store),
        admin: User = Depends(require_super_admin),
    ) -> dict:
        store.get_user(user_id)  # 404 if the user doesn't exist
        return {
            "links": {
                "doctors": [d.public() for d in store.doctors_of(user_id)],
                "patients": [p.public() for p in store.patients_of(user_id)],
            },
            "assignments": [a.to_dict() for a in store.assignments_involving(user_id)],
            "workouts": [w.to_dict() for w in store.workouts_for_patient(user_id)],
            "messages": [m.to_dict() for m in store.messages_involving(user_id)],
        }

    @router.get("/admin/workouts")
    def admin_all_workouts(
        store: Store = Depends(get_store),
        admin: User = Depends(require_super_admin),
    ) -> dict:
        return {"workouts": [w.to_dict() for w in store.all_workouts()]}

    return router
