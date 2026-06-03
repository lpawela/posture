import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")

from sqlalchemy import create_engine, inspect  # noqa: E402

from app.migrate import run_migrations  # noqa: E402
from app.models import Role  # noqa: E402
from app.sql_store import SqlStore  # noqa: E402

EXPECTED_TABLES = {
    "users", "tokens", "links", "assignments", "workouts", "messages",
    "catalog_exercises", "alembic_version",
}


def test_migration_builds_expected_schema(tmp_path):
    url = f"sqlite:///{tmp_path / 'posture.db'}"
    run_migrations(url)
    tables = set(inspect(create_engine(url)).get_table_names())
    assert EXPECTED_TABLES <= tables


def test_store_works_on_migrated_db_without_create_all(tmp_path):
    url = f"sqlite:///{tmp_path / 'posture.db'}"
    run_migrations(url)
    # create_all=False -> relies entirely on the migration having built the schema.
    store = SqlStore(url, create_all=False)
    doc = store.create_user("doc", "pwpw", "Doc", Role.DOCTOR)
    pat = store.create_user("pat", "pwpw", "Pat", Role.PATIENT)
    store.link(doc.id, pat.id)
    a = store.create_assignment(doc.id, pat.id, "squat", 3, 12)
    assert store.assignments_for_patient(pat.id)[0].id == a.id


def test_migration_is_idempotent(tmp_path):
    url = f"sqlite:///{tmp_path / 'posture.db'}"
    run_migrations(url)
    run_migrations(url)  # head -> head, no error
    assert "users" in inspect(create_engine(url)).get_table_names()
