import pytest

# The web layer is optional for the core engine; skip cleanly if FastAPI/httpx
# aren't installed (e.g. running just the pure-Python tests).
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.server import create_app  # noqa: E402
from pose_factory import squat_pose, to_landmark_dicts  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(create_app())


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_api_exercises(client):
    res = client.get("/api/exercises")
    assert res.status_code == 200
    names = {e["name"] for e in res.json()["exercises"]}
    assert names == {"squat", "deadlift"}


def test_static_index_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Posture" in res.text


def test_websocket_counts_rep(client):
    frames = [
        squat_pose(knee_angle=178),
        squat_pose(knee_angle=85),
        squat_pose(knee_angle=178),
    ]
    with client.websocket_connect("/ws/analyze?exercise=squat") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert ready["exercise"] == "squat"

        last = None
        for frame in frames:
            ws.send_json({"landmarks": to_landmark_dicts(frame)})
            last = ws.receive_json()
            assert last["type"] == "analysis"
        assert last["rep_count"] == 1


def test_websocket_reset(client):
    with client.websocket_connect("/ws/analyze?exercise=squat") as ws:
        ws.receive_json()  # ready
        ws.send_json({"type": "reset"})
        assert ws.receive_json() == {"type": "reset_ok", "rep_count": 0}


def test_websocket_unknown_exercise(client):
    with client.websocket_connect("/ws/analyze?exercise=zumba") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
