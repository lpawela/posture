"""The REST API runs unchanged on the SQL store (not just the in-memory one)."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from app.server import create_app  # noqa: E402
from app.sql_store import SqlStore  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(create_app(SqlStore("sqlite://", create_all=True)))


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_full_flow_persists_through_api(client):
    doc = client.post("/api/auth/register", json={"username": "doc", "password": "secret", "role": "doctor"})
    assert doc.status_code == 200
    token = doc.json()["token"]
    pat = client.post("/api/auth/register", json={"username": "pat", "password": "secret", "role": "patient"})
    assert pat.status_code == 200

    assert client.post("/api/doctor/patients", headers=auth(token), json={"patient_username": "pat"}).status_code == 200
    created = client.post(
        "/api/assignments",
        headers=auth(token),
        json={"patient_id": pat.json()["user"]["id"], "exercise": "squat", "target_sets": 3, "target_reps": 12},
    )
    assert created.status_code == 200

    # Re-fetch via a fresh login token to confirm it came from the database.
    pat_token = client.post("/api/auth/login", json={"username": "pat", "password": "secret"}).json()["token"]
    mine = client.get("/api/me/assignments", headers=auth(pat_token)).json()["assignments"]
    assert len(mine) == 1 and mine[0]["exercise"] == "squat"
