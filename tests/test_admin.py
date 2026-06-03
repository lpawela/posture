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


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def register(client, username, role, password="secret"):
    return client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "display_name": username, "role": role},
    )


def login(client, username, password="secret"):
    return client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]


def bootstrap(client, username="root"):
    res = client.post(
        "/api/admin/bootstrap",
        json={"username": username, "password": "secret", "display_name": "Root Admin"},
    )
    assert res.status_code == 200, res.text
    return res.json()


def make_basic_admin(client, root_token, username="ua"):
    res = client.post(
        "/api/admin/admins",
        headers=auth(root_token),
        json={"username": username, "password": "secret", "tier": "basic"},
    )
    assert res.status_code == 200, res.text
    return login(client, username)


# ----- registration / creation rules ------------------------------------- #


def test_admins_cannot_self_register(client):
    assert register(client, "x", "admin_basic").status_code == 403
    assert register(client, "y", "admin_super").status_code == 403


def test_bootstrap_creates_super_admin_then_is_disabled(client):
    out = bootstrap(client)
    assert out["user"]["role"] == "admin_super"
    second = client.post("/api/admin/bootstrap", json={"username": "root2", "password": "secret"})
    assert second.status_code == 403


def test_super_admin_creates_admins_but_basic_cannot(client):
    root = bootstrap(client)
    created = client.post(
        "/api/admin/admins",
        headers=auth(root["token"]),
        json={"username": "ua", "password": "secret", "tier": "basic"},
    )
    assert created.status_code == 200 and created.json()["role"] == "admin_basic"

    ua_token = login(client, "ua")
    blocked = client.post(
        "/api/admin/admins",
        headers=auth(ua_token),
        json={"username": "ub", "password": "secret", "tier": "basic"},
    )
    assert blocked.status_code == 403


# ----- access control ----------------------------------------------------- #


def test_admin_endpoints_reject_non_admins(client):
    register(client, "pat", "patient")
    pat_token = login(client, "pat")
    assert client.get("/api/admin/users").status_code == 401  # unauthenticated
    assert client.get("/api/admin/users", headers=auth(pat_token)).status_code == 403


def test_both_tiers_see_general_user_data_only(client):
    root = bootstrap(client)
    register(client, "pat", "patient")
    register(client, "doc", "doctor")
    ua_token = make_basic_admin(client, root["token"])

    for token in (root["token"], ua_token):
        res = client.get("/api/admin/users", headers=auth(token))
        assert res.status_code == 200
        users = res.json()["users"]
        assert {"pat", "doc", "root", "ua"} <= {u["username"] for u in users}
        # Only general account fields — never medical data.
        for u in users:
            assert set(u.keys()) == {"id", "username", "display_name", "role"}

    # Stats are general data too — both tiers allowed.
    assert client.get("/api/admin/stats", headers=auth(ua_token)).status_code == 200
    stats = client.get("/api/admin/stats", headers=auth(root["token"])).json()
    assert stats["total_users"] == 4
    assert stats["by_role"]["patient"] == 1


def test_user_detail_exposes_no_medical_fields(client):
    root = bootstrap(client)
    pat = register(client, "pat", "patient").json()
    ua_token = make_basic_admin(client, root["token"])
    res = client.get(f"/api/admin/users/{pat['user']['id']}", headers=auth(ua_token))
    assert res.status_code == 200
    assert set(res.json().keys()) == {"id", "username", "display_name", "role"}


# ----- the core tier distinction: medical records ------------------------- #


def _seed_medical(store, client):
    doc = register(client, "doc", "doctor").json()
    pat = register(client, "pat", "patient").json()
    store.link(doc["user"]["id"], pat["user"]["id"])
    assignment = store.create_assignment(doc["user"]["id"], pat["user"]["id"], "squat", 3, 12)
    s = WorkoutSession("squat", 1, 2)
    s.record_rep(100)
    s.record_rep(80)
    store.record_workout(pat["user"]["id"], s.finish(), assignment.id)
    store.add_message(doc["user"]["id"], pat["user"]["id"], "How's the knee?")
    return pat["user"]["id"]


def test_basic_admin_is_denied_medical_records(client, store):
    root = bootstrap(client)
    pid = _seed_medical(store, client)
    ua_token = make_basic_admin(client, root["token"])
    assert client.get(f"/api/admin/users/{pid}/medical", headers=auth(ua_token)).status_code == 403
    assert client.get("/api/admin/workouts", headers=auth(ua_token)).status_code == 403


def test_super_admin_has_complete_access(client, store):
    root = bootstrap(client)
    pid = _seed_medical(store, client)

    med = client.get(f"/api/admin/users/{pid}/medical", headers=auth(root["token"]))
    assert med.status_code == 200
    body = med.json()
    assert len(body["assignments"]) == 1
    assert len(body["workouts"]) == 1
    assert len(body["messages"]) == 1
    assert body["links"]["doctors"][0]["username"] == "doc"

    allw = client.get("/api/admin/workouts", headers=auth(root["token"]))
    assert allw.status_code == 200 and len(allw.json()["workouts"]) == 1
