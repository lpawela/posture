"""Seed the configured store with one user per role plus sample clinical data.

Idempotent: re-running is a no-op once the sample patient exists. Run against
the configured database with ``python -m app.seed`` (honours
``POSTURE_DATABASE_URL``), or call :func:`seed` with any store in tests.
"""

from __future__ import annotations

from app.models import Role
from app.workout import WorkoutSession

SEED_PASSWORD = "password123"

#: One account per role. (username, display name, role)
SEED_USERS = [
    ("root", "Root Admin", Role.ADMIN_SUPER),
    ("frontdesk", "Front Desk", Role.ADMIN_BASIC),
    ("dr.house", "Dr. Gregory House", Role.DOCTOR),
    ("jdoe", "John Doe", Role.PATIENT),
]


def seed(store) -> dict:
    """Create the seed users and sample data. No-op if already seeded."""
    if store.get_user_by_username("jdoe"):
        return {"created": False, "reason": "already seeded"}

    users = {
        username: store.create_user(username, SEED_PASSWORD, display, role)
        for username, display, role in SEED_USERS
    }
    doctor, patient = users["dr.house"], users["jdoe"]

    store.link(doctor.id, patient.id)

    squat = store.create_assignment(
        doctor.id, patient.id, "squat", 3, 12, "Keep your chest up; reach parallel."
    )
    store.create_assignment(
        doctor.id, patient.id, "deadlift", 3, 8, "Neutral spine; brace your core."
    )

    # A sample completed workout: 3 sets of 12 squats at solid (92) form.
    session = WorkoutSession("squat", target_sets=3, target_reps=12)
    for _ in range(3 * 12):
        session.record_rep(92.0)
    store.record_workout(patient.id, session.finish(), squat.id)

    store.add_message(
        doctor.id, patient.id, "Welcome! Start with the squat assignment and send me your scores."
    )
    store.add_message(patient.id, doctor.id, "Thanks, Dr. House — will do today.")

    return {
        "created": True,
        "users": {u.username: u.role.value for u in users.values()},
        "password": SEED_PASSWORD,
    }


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from app.server import build_default_store

    store = build_default_store()
    result = seed(store)
    if result["created"]:
        print(f"Seeded users (password = '{SEED_PASSWORD}'):")
        for username, role in result["users"].items():
            print(f"  - {username:12s} {role}")
    else:
        print("Seed skipped:", result["reason"])

    # Load the local MuscleWiki exercise catalog (idempotent).
    try:
        from app.catalog_import import import_catalog

        n = import_catalog(store)
        print(f"Catalog: {n} exercises upserted ({store.catalog_count()} total).")
    except FileNotFoundError:
        print("Catalog data file not found; skipping catalog import.")


if __name__ == "__main__":
    main()
