import pytest

from app.exercises.squat import SquatAnalyzer
from pose_factory import squat_pose


def codes(result):
    return {issue.code for issue in result.form_issues}


def run(analyzer, *frames):
    result = None
    for frame in frames:
        result = analyzer.update(frame)
    return result


def test_standing_metrics_are_near_straight():
    a = SquatAnalyzer()
    res = a.update(squat_pose(knee_angle=178, torso_lean=5))
    assert res.pose_visible
    assert res.metrics["knee_angle"] == pytest.approx(178, abs=1)
    assert res.metrics["torso_lean"] == pytest.approx(5, abs=1)
    assert res.state == "up"
    assert res.rep_count == 0


def test_counts_one_clean_rep():
    a = SquatAnalyzer()
    res = run(
        a,
        squat_pose(knee_angle=178, torso_lean=10),
        squat_pose(knee_angle=85, torso_lean=30),   # deep, acceptable lean
        squat_pose(knee_angle=178, torso_lean=10),
    )
    assert res.rep_count == 1
    assert res.state == "up"
    assert codes(res) == set()  # clean rep → no faults


def test_bottom_sets_down_state():
    a = SquatAnalyzer()
    a.update(squat_pose(knee_angle=178))
    res = a.update(squat_pose(knee_angle=85))
    assert res.state == "down"
    assert res.rep_count == 0  # not counted until standing again


def test_flags_insufficient_depth():
    a = SquatAnalyzer()
    res = run(
        a,
        squat_pose(knee_angle=178),
        squat_pose(knee_angle=112),  # armed (<=120) but above depth target (100)
        squat_pose(knee_angle=178),
    )
    assert res.rep_count == 1
    assert "insufficient_depth" in codes(res)


def test_flags_excessive_forward_lean():
    a = SquatAnalyzer()
    res = run(
        a,
        squat_pose(knee_angle=178, torso_lean=8),
        squat_pose(knee_angle=85, torso_lean=70),  # deep but folded over
        squat_pose(knee_angle=178, torso_lean=8),
    )
    assert res.rep_count == 1
    assert "excessive_forward_lean" in codes(res)
    assert "insufficient_depth" not in codes(res)


def test_counts_multiple_reps():
    a = SquatAnalyzer()
    for _ in range(3):
        run(
            a,
            squat_pose(knee_angle=178),
            squat_pose(knee_angle=85),
            squat_pose(knee_angle=178),
        )
    assert a._rep_count == 3


def test_pose_not_visible_pauses_analysis():
    a = SquatAnalyzer()
    res = a.update(squat_pose(knee_angle=85, visibility=0.1))
    assert res.pose_visible is False
    assert res.rep_count == 0
    assert "visible" in res.feedback.lower()


def test_live_deviation_clear_when_upright():
    a = SquatAnalyzer()
    res = a.update(squat_pose(knee_angle=110, torso_lean=15))
    assert res.deviation == 0.0


def test_live_deviation_rises_with_forward_lean():
    a = SquatAnalyzer()
    mild = a.update(squat_pose(knee_angle=100, torso_lean=55)).deviation
    severe = a.update(squat_pose(knee_angle=100, torso_lean=78)).deviation
    assert 0.0 < mild < severe <= 1.0


def test_reset_clears_count():
    a = SquatAnalyzer()
    run(a, squat_pose(178), squat_pose(85), squat_pose(178))
    assert a._rep_count == 1
    a.reset()
    assert a._rep_count == 0
    assert a.update(squat_pose(178)).rep_count == 0
