import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.models import Role  # noqa: E402
from app.server import create_app  # noqa: E402
from app.store import Store  # noqa: E402
from pose_factory import squat_pose, to_landmark_dicts  # noqa: E402


def rep_frames():
    """Frames for one full squat rep: stand -> bottom -> stand."""
    return [squat_pose(178), squat_pose(85), squat_pose(178)]


def drive_reps(ws, n):
    for _ in range(n):
        for frame in rep_frames():
            ws.send_json({"landmarks": to_landmark_dicts(frame)})
            ws.receive_json()  # analysis


def test_ws_records_assigned_workout_for_patient():
    store = Store()
    doc = store.create_user("doc", "pwpw", "Doc", Role.DOCTOR)
    pat = store.create_user("pat", "pwpw", "Pat", Role.PATIENT)
    store.link(doc.id, pat.id)
    assignment = store.create_assignment(doc.id, pat.id, "squat", 2, 2)
    token = store.issue_token(pat)

    client = TestClient(create_app(store))
    url = f"/ws/analyze?assignment_id={assignment.id}&token={token}"
    with client.websocket_connect(url) as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert ready["exercise"] == "squat"
        assert ready["target_sets"] == 2 and ready["target_reps"] == 2
        assert ready["recording"] is True

        drive_reps(ws, 4)  # 2 sets of 2, auto-closed at the target

        ws.send_json({"type": "finish"})
        summary = ws.receive_json()
        assert summary["type"] == "summary"
        assert summary["total_reps"] == 4
        assert summary["total_sets"] == 2
        assert summary["completion_ratio"] == 1.0
        assert summary["overall_score"] == 100.0
        assert "record_id" in summary

    stored = store.workouts_for_patient(pat.id)
    assert len(stored) == 1
    assert stored[0].assignment_id == assignment.id
    assert stored[0].total_reps == 4


def test_ws_reports_live_session_state():
    store = Store()
    pat = store.create_user("pat", "pwpw", "Pat", Role.PATIENT)
    token = store.issue_token(pat)
    client = TestClient(create_app(store))

    with client.websocket_connect(f"/ws/analyze?exercise=squat&token={token}") as ws:
        ws.receive_json()  # ready
        last = None
        for frame in rep_frames():
            ws.send_json({"landmarks": to_landmark_dicts(frame)})
            last = ws.receive_json()
        assert last["type"] == "analysis"
        assert last["rep_count"] == 1
        assert last["rep_score"] is not None
        assert last["session"]["total_reps"] == 1


def test_ws_reports_live_deviation():
    store = Store()
    pat = store.create_user("pat", "pwpw", "Pat", Role.PATIENT)
    token = store.issue_token(pat)
    client = TestClient(create_app(store))

    with client.websocket_connect(f"/ws/analyze?exercise=squat&token={token}") as ws:
        ws.receive_json()  # ready
        ws.send_json({"landmarks": to_landmark_dicts(squat_pose(knee_angle=120, torso_lean=15))})
        upright = ws.receive_json()
        ws.send_json({"landmarks": to_landmark_dicts(squat_pose(knee_angle=120, torso_lean=78))})
        folded = ws.receive_json()

    assert "deviation" in upright
    assert upright["deviation"] == 0.0
    assert folded["deviation"] > upright["deviation"]


def test_ws_anonymous_does_not_record():
    store = Store()
    client = TestClient(create_app(store))
    with client.websocket_connect("/ws/analyze?exercise=squat") as ws:
        ready = ws.receive_json()
        assert ready["recording"] is False
        drive_reps(ws, 1)
        ws.send_json({"type": "finish"})
        summary = ws.receive_json()
        assert summary["type"] == "summary"
        assert "record_id" not in summary
