import pytest

from app.models import Role
from app.seed import SEED_PASSWORD, seed
from app.store import Store


@pytest.fixture(params=["memory", "sql"])
def store(request):
    if request.param == "sql":
        pytest.importorskip("sqlalchemy")
        from app.sql_store import SqlStore

        return SqlStore("sqlite://", create_all=True)
    return Store()


def test_seed_creates_one_user_per_role(store):
    result = seed(store)
    assert result["created"] is True

    roles = {u.role for u in store.all_users()}
    assert roles == {Role.PATIENT, Role.DOCTOR, Role.ADMIN_BASIC, Role.ADMIN_SUPER}

    # Seed users are usable: each can authenticate with the seed password.
    for user in store.all_users():
        assert store.authenticate(user.username, SEED_PASSWORD) is not None


def test_seed_includes_sample_clinical_data(store):
    seed(store)
    patient = store.get_user_by_username("jdoe")
    doctor = store.get_user_by_username("dr.house")
    assert store.is_linked(doctor.id, patient.id)
    assert len(store.assignments_for_patient(patient.id)) == 2
    workouts = store.workouts_for_patient(patient.id)
    assert len(workouts) == 1 and workouts[0].total_reps == 36
    assert len(store.conversation(patient.id, doctor.id)) == 2


def test_seed_is_idempotent(store):
    assert seed(store)["created"] is True
    assert seed(store)["created"] is False
    assert len(store.all_users()) == 4
