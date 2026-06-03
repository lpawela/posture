import pytest

from app.models import Role
from app.store import Conflict, PermissionDenied, Store, StoreError
from app.workout import WorkoutSession


@pytest.fixture(params=["memory", "sql"])
def store(request):
    """Run the whole store contract against both backends."""
    if request.param == "sql":
        from app.sql_store import SqlStore

        return SqlStore("sqlite://", create_all=True)
    return Store()


def doctor(store, username="dr"):
    return store.create_user(username, "pwpw", "Doctor", Role.DOCTOR)


def patient(store, username="pat"):
    return store.create_user(username, "pwpw", "Patient", Role.PATIENT)


def test_create_and_authenticate(store):
    u = patient(store)
    assert store.authenticate("pat", "pwpw").id == u.id
    assert store.authenticate("pat", "nope") is None
    assert store.get_user_by_username("PAT").id == u.id  # case-insensitive


def test_duplicate_username_conflict(store):
    patient(store)
    with pytest.raises(Conflict):
        patient(store)


def test_token_roundtrip(store):
    u = patient(store)
    token = store.issue_token(u)
    assert store.user_for_token(token).id == u.id
    assert store.user_for_token("bogus") is None
    assert store.user_for_token(None) is None
    store.revoke_token(token)
    assert store.user_for_token(token) is None


def test_linking_and_lookups(store):
    d, p = doctor(store), patient(store)
    store.link(d.id, p.id)
    assert store.is_linked(d.id, p.id)
    assert [u.id for u in store.patients_of(d.id)] == [p.id]
    assert [u.id for u in store.doctors_of(p.id)] == [d.id]
    assert store.can_communicate(p.id, d.id)  # symmetric


def test_link_role_validation(store):
    d, p = doctor(store), patient(store)
    with pytest.raises(StoreError):
        store.link(p.id, d.id)  # patient cannot be the "doctor" side


def test_assignment_requires_link(store):
    d, p = doctor(store), patient(store)
    with pytest.raises(PermissionDenied):
        store.create_assignment(d.id, p.id, "squat", 3, 12)
    store.link(d.id, p.id)
    a = store.create_assignment(d.id, p.id, "squat", 3, 12, "go deep")
    assert a.exercise == "squat" and a.target_sets == 3 and a.notes == "go deep"
    assert [x.id for x in store.assignments_for_patient(p.id)] == [a.id]
    assert [x.id for x in store.assignments_by_doctor(d.id)] == [a.id]


def test_assignment_unknown_exercise(store):
    d, p = doctor(store), patient(store)
    store.link(d.id, p.id)
    with pytest.raises(StoreError):
        store.create_assignment(d.id, p.id, "yoga", 3, 12)


def test_assignment_invalid_targets(store):
    d, p = doctor(store), patient(store)
    store.link(d.id, p.id)
    with pytest.raises(StoreError):
        store.create_assignment(d.id, p.id, "squat", 0, 12)


def test_record_and_read_workout(store):
    p = patient(store)
    s = WorkoutSession("squat", 1, 2)
    s.record_rep(100)
    s.record_rep(80)
    record = store.record_workout(p.id, s.finish())
    assert record.total_reps == 2
    assert [w.id for w in store.workouts_for_patient(p.id)] == [record.id]


def test_messaging_requires_link(store):
    d, p = doctor(store), patient(store)
    with pytest.raises(PermissionDenied):
        store.add_message(d.id, p.id, "hello")
    store.link(d.id, p.id)
    m1 = store.add_message(d.id, p.id, "How's the knee?")
    m2 = store.add_message(p.id, d.id, "Much better!")
    convo = store.conversation(p.id, d.id)
    assert [m.id for m in convo] == [m1.id, m2.id]


def test_mark_read(store):
    d, p = doctor(store), patient(store)
    store.link(d.id, p.id)
    store.add_message(d.id, p.id, "hi")  # from doctor to patient, unread
    assert store.mark_read(p.id, d.id) == 1
    assert store.mark_read(p.id, d.id) == 0  # already read


def test_admin_directory_views(store):
    d, p = doctor(store), patient(store)
    assert store.has_admin() is False
    admin = store.create_user("root", "pwpw", "Root", Role.ADMIN_SUPER)
    assert store.has_admin() is True
    assert {u.id for u in store.all_users()} == {d.id, p.id, admin.id}
    counts = store.role_counts()
    assert counts == {"doctor": 1, "patient": 1, "admin_super": 1}


def test_assignments_and_messages_involving(store):
    d, p = doctor(store), patient(store)
    store.link(d.id, p.id)
    a = store.create_assignment(d.id, p.id, "squat", 3, 12)
    store.add_message(d.id, p.id, "hello")
    # The assignment involves both the doctor and the patient.
    assert [x.id for x in store.assignments_involving(d.id)] == [a.id]
    assert [x.id for x in store.assignments_involving(p.id)] == [a.id]
    assert len(store.messages_involving(p.id)) == 1
    assert len(store.messages_involving(d.id)) == 1


def test_all_workouts(store):
    p = patient(store)
    s = WorkoutSession("squat", 1, 1)
    s.record_rep(100)
    store.record_workout(p.id, s.finish())
    assert len(store.all_workouts()) == 1
