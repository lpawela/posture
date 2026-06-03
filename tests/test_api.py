import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.server import create_app  # noqa: E402
from app.store import Store  # noqa: E402
from app.workout import WorkoutSession  # noqa: E402


@pytest.fixture()
def store():
    return Store()


@pytest.fixture()
def client(store):
    return TestClient(create_app(store))


def register(client, username, role, password="secret"):
    res = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "display_name": username, "role": role},
    )
    assert res.status_code == 200, res.text
    return res.json()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_register_me_and_login(client):
    reg = register(client, "alice", "patient")
    assert reg["user"]["role"] == "patient"
    me = client.get("/api/auth/me", headers=auth(reg["token"]))
    assert me.status_code == 200 and me.json()["username"] == "alice"

    ok = client.post("/api/auth/login", json={"username": "alice", "password": "secret"})
    assert ok.status_code == 200
    bad = client.post("/api/auth/login", json={"username": "alice", "password": "x"})
    assert bad.status_code == 401


def test_duplicate_register_conflict(client):
    register(client, "bob", "doctor")
    res = client.post(
        "/api/auth/register",
        json={"username": "bob", "password": "secret", "role": "doctor"},
    )
    assert res.status_code == 409


def test_endpoints_require_auth(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/doctor/patients").status_code == 401


def test_role_enforcement(client):
    pat = register(client, "pat", "patient")
    assert client.get("/api/doctor/patients", headers=auth(pat["token"])).status_code == 403


def test_doctor_links_and_assigns_and_patient_sees_it(client):
    doc = register(client, "doc", "doctor")
    register(client, "pat", "patient")

    linked = client.post(
        "/api/doctor/patients", headers=auth(doc["token"]), json={"patient_username": "pat"}
    )
    assert linked.status_code == 200 and linked.json()["username"] == "pat"

    patients = client.get("/api/doctor/patients", headers=auth(doc["token"])).json()["patients"]
    assert len(patients) == 1
    pid = patients[0]["id"]

    created = client.post(
        "/api/assignments",
        headers=auth(doc["token"]),
        json={"patient_id": pid, "exercise": "deadlift", "target_sets": 3, "target_reps": 12, "notes": "flat back"},
    )
    assert created.status_code == 200 and created.json()["exercise"] == "deadlift"

    pat_token = client.post("/api/auth/login", json={"username": "pat", "password": "secret"}).json()["token"]
    mine = client.get("/api/me/assignments", headers=auth(pat_token)).json()["assignments"]
    assert len(mine) == 1 and mine[0]["target_reps"] == 12


def test_assign_without_link_is_forbidden(client):
    doc = register(client, "doc", "doctor")
    pat = register(client, "pat", "patient")
    res = client.post(
        "/api/assignments",
        headers=auth(doc["token"]),
        json={"patient_id": pat["user"]["id"], "exercise": "squat", "target_sets": 3, "target_reps": 10},
    )
    assert res.status_code == 403


def test_assign_unknown_exercise(client):
    doc = register(client, "doc", "doctor")
    register(client, "pat", "patient")
    client.post("/api/doctor/patients", headers=auth(doc["token"]), json={"patient_username": "pat"})
    pid = client.get("/api/doctor/patients", headers=auth(doc["token"])).json()["patients"][0]["id"]
    res = client.post(
        "/api/assignments",
        headers=auth(doc["token"]),
        json={"patient_id": pid, "exercise": "pilates", "target_sets": 3, "target_reps": 10},
    )
    assert res.status_code == 400


def test_messaging_between_linked_users(client):
    doc = register(client, "doc", "doctor")
    pat = register(client, "pat", "patient")
    client.post("/api/doctor/patients", headers=auth(doc["token"]), json={"patient_username": "pat"})
    did, pid = doc["user"]["id"], pat["user"]["id"]

    assert client.post("/api/messages", headers=auth(doc["token"]), json={"recipient_id": pid, "body": "How are you?"}).status_code == 200
    assert client.post("/api/messages", headers=auth(pat["token"]), json={"recipient_id": did, "body": "Good!"}).status_code == 200

    convo = client.get(f"/api/messages/{did}", headers=auth(pat["token"])).json()["messages"]
    assert [m["body"] for m in convo] == ["How are you?", "Good!"]


def test_message_without_link_forbidden(client):
    doc = register(client, "doc", "doctor")
    pat = register(client, "pat", "patient")
    res = client.post(
        "/api/messages", headers=auth(doc["token"]), json={"recipient_id": pat["user"]["id"], "body": "hi"}
    )
    assert res.status_code == 403


def test_doctor_reads_patient_scores(client, store):
    doc = register(client, "doc", "doctor")
    pat = register(client, "pat", "patient")
    client.post("/api/doctor/patients", headers=auth(doc["token"]), json={"patient_username": "pat"})
    pid = pat["user"]["id"]

    s = WorkoutSession("squat", 1, 2)
    s.record_rep(100)
    s.record_rep(90)
    store.record_workout(pid, s.finish())

    res = client.get(f"/api/doctor/patients/{pid}/workouts", headers=auth(doc["token"]))
    assert res.status_code == 200
    workouts = res.json()["workouts"]
    assert len(workouts) == 1 and workouts[0]["total_reps"] == 2

    # A doctor not linked to this patient cannot read the scores.
    other = register(client, "doc2", "doctor")
    assert client.get(f"/api/doctor/patients/{pid}/workouts", headers=auth(other["token"])).status_code == 403


def test_contacts(client):
    doc = register(client, "doc", "doctor")
    pat = register(client, "pat", "patient")
    client.post("/api/doctor/patients", headers=auth(doc["token"]), json={"patient_username": "pat"})
    doc_contacts = client.get("/api/contacts", headers=auth(doc["token"])).json()["contacts"]
    pat_contacts = client.get("/api/contacts", headers=auth(pat["token"])).json()["contacts"]
    assert doc_contacts[0]["username"] == "pat"
    assert pat_contacts[0]["username"] == "doc"
