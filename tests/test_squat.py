import pytest

from app.exercises.squat import SquatAnalyzer
from app.landmarks import Landmark, PoseFrame, PoseLandmark as L, NUM_LANDMARKS
from app.scoring import live_deviation
from pose_factory import squat_pose


def codes(result):
    return {issue.code for issue in result.form_issues}


def _dim_side(frame, indices, visibility=0.1):
    """Return a copy of ``frame`` with the given landmarks made low-visibility."""
    lms = list(frame)
    for i in indices:
        p = lms[int(i)]
        lms[int(i)] = Landmark(p.x, p.y, p.z, visibility)
    return PoseFrame(lms)


def _collapse_side(frame, indices, visibility=0.1):
    """Occlude one side the way MediaPipe does: collapse its landmarks onto a
    single low-confidence point (so ``angle()`` on that side would raise)."""
    lms = list(frame)
    for i in indices:
        lms[int(i)] = Landmark(0.9, 0.1, 0.0, visibility)
    return PoseFrame(lms)


RIGHT_LEG = (L.RIGHT_SHOULDER, L.RIGHT_HIP, L.RIGHT_KNEE, L.RIGHT_ANKLE)


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


# ----- side-on visibility (one occluded side) ----------------------------- #


def test_side_on_one_visible_side_still_analyses():
    # Side-on framing occludes the far leg; analysis must still run off the
    # near side instead of gating out with "step back".
    a = SquatAnalyzer()
    frame = _dim_side(squat_pose(knee_angle=100, torso_lean=30), RIGHT_LEG)
    res = a.update(frame)
    assert res.pose_visible
    assert res.metrics["knee_angle"] == pytest.approx(100, abs=1)
    # Wobble can't be judged from one leg, so no asymmetry metric is emitted.
    assert "knee_asymmetry" not in res.metrics


def test_side_on_with_collapsed_far_side_still_analyses():
    # MediaPipe collapses occluded landmarks onto ~one point, so angle() on the
    # far side would raise; the analyzer must carry the frame on the near side
    # instead of discarding it (regression guard for the bilateral helper).
    a = SquatAnalyzer()
    frame = _collapse_side(squat_pose(knee_angle=100, torso_lean=30), RIGHT_LEG)
    res = a.update(frame)
    assert res.pose_visible
    assert res.metrics["knee_angle"] == pytest.approx(100, abs=2)
    # torso_lean uses the near side, so the collapsed far hip/shoulder can't bias it.
    assert res.metrics["torso_lean"] == pytest.approx(30, abs=2)
    assert "knee_asymmetry" not in res.metrics


def test_partial_far_side_occlusion_uses_one_side_consistently():
    # Only the far SHOULDER is occluded (its leg is still visible). The frame
    # must commit to one side for EVERY metric rather than blending (e.g. knee
    # from both legs but hip from one). With a single usable side, no wobble
    # metric is emitted.
    a = SquatAnalyzer()
    frame = _dim_side(squat_pose(knee_angle=100, torso_lean=30), (L.RIGHT_SHOULDER,), visibility=0.3)
    res = a.update(frame)
    assert res.pose_visible
    assert res.metrics["knee_angle"] == pytest.approx(100, abs=2)
    assert "knee_asymmetry" not in res.metrics


def test_partial_rep_jitter_near_bottom_keeps_down_cue():
    # A single jittery frame that rebounds off the bottom but stays below the
    # descent threshold must not flip the live cue to "stand up".
    a = SquatAnalyzer()
    a.update(squat_pose(knee_angle=178))
    a.update(squat_pose(knee_angle=100))         # descend; bottom ~100, state down
    res = a.update(squat_pose(knee_angle=116))   # rebound, but still < down_enter (120)
    assert res.state == "down"
    assert res.feedback == a.down_cue


def test_partial_rep_above_descent_threshold_nudges_up():
    # Risen back past the descent threshold but short of lockout → nudge to finish.
    a = SquatAnalyzer()
    a.update(squat_pose(knee_angle=178))
    a.update(squat_pose(knee_angle=95))          # bottom
    res = a.update(squat_pose(knee_angle=140))   # past down_enter (120), below up_enter (160)
    assert res.state == "down"
    assert res.feedback == a.up_cue


def test_both_sides_occluded_pauses_analysis():
    a = SquatAnalyzer()
    frame = _dim_side(
        squat_pose(knee_angle=100),
        RIGHT_LEG + (L.LEFT_SHOULDER, L.LEFT_HIP, L.LEFT_KNEE, L.LEFT_ANKLE),
    )
    assert a.update(frame).pose_visible is False


# ----- robustness: degenerate frame --------------------------------------- #


def test_misconfigured_required_sides_fails_loudly():
    # frame_sides assumes a left/right pair; a subclass with the wrong arity must
    # fail at construction, not degrade to a permanent "not visible".
    class Bad(SquatAnalyzer):
        required_sides = ((L.LEFT_HIP, L.LEFT_KNEE),)  # only one side

    with pytest.raises(TypeError):
        Bad()


def test_degenerate_frame_does_not_crash():
    # All landmarks coincident but fully visible: angle() would raise. The
    # analyzer must treat it as not-visible rather than propagating the error
    # (which would otherwise tear down the live WebSocket session).
    a = SquatAnalyzer()
    res = a.update(PoseFrame([Landmark(0.5, 0.5, 0.0, 1.0) for _ in range(NUM_LANDMARKS)]))
    assert res.pose_visible is False
    assert res.rep_count == 0


# ----- wobble (knee asymmetry) -------------------------------------------- #


def test_balanced_legs_emit_zero_asymmetry():
    a = SquatAnalyzer()
    res = a.update(squat_pose(knee_angle=100))
    assert res.metrics["knee_asymmetry"] == pytest.approx(0, abs=1)


def test_knee_asymmetry_bound_drives_tint():
    a = SquatAnalyzer()
    bounds = list(a.live_bounds)
    assert live_deviation(bounds, {"torso_lean": 10, "knee_asymmetry": 5}) == 0.0
    assert live_deviation(bounds, {"torso_lean": 10, "knee_asymmetry": 40}) > 0.0


# ----- set boundaries ----------------------------------------------------- #


def test_end_rep_cycle_abandons_partial_rep_keeps_count():
    a = SquatAnalyzer()
    run(a, squat_pose(178), squat_pose(85), squat_pose(178))  # one clean rep
    a.update(squat_pose(85))  # start descending into a new rep
    assert a._state.value == "down"
    a.end_rep_cycle()
    assert a._state.value == "up"
    assert a._rep_count == 1  # count preserved across the boundary
    # Standing back up must NOT complete the abandoned partial rep.
    assert a.update(squat_pose(178)).rep_count == 1
