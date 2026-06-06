import pytest

from app.exercises.deadlift import DeadliftAnalyzer
from app.landmarks import Landmark, PoseFrame, PoseLandmark as L
from pose_factory import deadlift_pose


def codes(result):
    return {issue.code for issue in result.form_issues}


RIGHT_SIDE = (L.RIGHT_SHOULDER, L.RIGHT_HIP, L.RIGHT_KNEE, L.RIGHT_ANKLE)


def _collapse_side(frame, indices, visibility=0.1):
    """Occlude one side: collapse its landmarks onto a single low-confidence
    point (so ``angle()`` on that side would raise)."""
    lms = list(frame)
    for i in indices:
        lms[int(i)] = Landmark(0.9, 0.1, 0.0, visibility)
    return PoseFrame(lms)


def test_side_on_with_collapsed_far_side_still_analyses():
    a = DeadliftAnalyzer()
    frame = _collapse_side(deadlift_pose(hip_angle=120, torso_lean=45), RIGHT_SIDE)
    res = a.update(frame)
    assert res.pose_visible
    assert res.metrics["hip_angle"] == pytest.approx(120, abs=3)


def run(analyzer, *frames):
    result = None
    for frame in frames:
        result = analyzer.update(frame)
    return result


def test_standing_metrics_are_near_straight():
    a = DeadliftAnalyzer()
    res = a.update(deadlift_pose(hip_angle=178, torso_lean=5))
    assert res.pose_visible
    assert res.metrics["hip_angle"] == pytest.approx(178, abs=1)
    assert res.state == "up"


def test_counts_one_clean_rep():
    a = DeadliftAnalyzer()
    res = run(
        a,
        deadlift_pose(hip_angle=178, torso_lean=5),
        deadlift_pose(hip_angle=70, torso_lean=45),   # hinge, safe back angle
        deadlift_pose(hip_angle=172, torso_lean=5),   # full lockout
    )
    assert res.rep_count == 1
    assert res.state == "up"
    assert codes(res) == set()


def test_bottom_sets_down_state():
    a = DeadliftAnalyzer()
    a.update(deadlift_pose(hip_angle=178))
    res = a.update(deadlift_pose(hip_angle=70))
    assert res.state == "down"
    assert res.rep_count == 0


def test_flags_incomplete_lockout():
    a = DeadliftAnalyzer()
    res = run(
        a,
        deadlift_pose(hip_angle=178),
        deadlift_pose(hip_angle=70, torso_lean=45),
        deadlift_pose(hip_angle=162, torso_lean=5),  # completes (>=160) but short of 168
    )
    assert res.rep_count == 1
    assert "incomplete_lockout" in codes(res)


def test_flags_back_too_horizontal():
    a = DeadliftAnalyzer()
    res = run(
        a,
        deadlift_pose(hip_angle=178, torso_lean=5),
        deadlift_pose(hip_angle=70, torso_lean=82),  # back nearly horizontal
        deadlift_pose(hip_angle=172, torso_lean=5),
    )
    assert res.rep_count == 1
    assert "back_too_horizontal" in codes(res)
    assert "incomplete_lockout" not in codes(res)


def test_pose_not_visible_pauses_analysis():
    a = DeadliftAnalyzer()
    res = a.update(deadlift_pose(hip_angle=70, visibility=0.1))
    assert res.pose_visible is False
    assert res.rep_count == 0


def test_live_deviation_clear_for_normal_hinge():
    a = DeadliftAnalyzer()
    # A legitimately inclined torso at the bottom should not warn.
    assert a.update(deadlift_pose(hip_angle=110, torso_lean=60)).deviation == 0.0


def test_live_deviation_rises_when_back_too_horizontal():
    a = DeadliftAnalyzer()
    assert a.update(deadlift_pose(hip_angle=110, torso_lean=85)).deviation > 0.0


def test_reset_clears_count():
    a = DeadliftAnalyzer()
    run(a, deadlift_pose(178), deadlift_pose(70), deadlift_pose(172))
    assert a._rep_count == 1
    a.reset()
    assert a._rep_count == 0
