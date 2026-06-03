import pytest

from app.scoring import (
    HIGHER_IS_WORSE,
    LOWER_IS_WORSE,
    LiveBound,
    ScoringRule,
    live_deviation,
    score_extremes,
)


def test_perfect_rep_scores_100():
    rules = [ScoringRule("knee_angle", "min", 90, HIGHER_IS_WORSE, 15, 1.5, 45, "depth")]
    score, breakdown = score_extremes(rules, {"knee_angle": {"min": 85, "max": 178}})
    assert score == 100.0
    assert breakdown[0]["penalty"] == 0.0
    assert breakdown[0]["label"] == "depth"


def test_higher_is_worse_penalty():
    # min knee 130: deviation 40, minus tolerance 15 = 25, * 1.5 = 37.5 penalty.
    rules = [ScoringRule("knee_angle", "min", 90, HIGHER_IS_WORSE, 15, 1.5, 45)]
    score, _ = score_extremes(rules, {"knee_angle": {"min": 130, "max": 178}})
    assert score == pytest.approx(62.5)


def test_lower_is_worse_penalty():
    # max hip 150: deviation -28, (28 - 10) = 18, * 1.5 = 27 penalty.
    rules = [ScoringRule("hip_angle", "max", 178, LOWER_IS_WORSE, 10, 1.5, 45)]
    score, _ = score_extremes(rules, {"hip_angle": {"max": 150, "min": 60}})
    assert score == pytest.approx(73.0)


def test_within_tolerance_is_not_penalised():
    rules = [ScoringRule("hip_angle", "max", 178, LOWER_IS_WORSE, 10, 1.5, 45)]
    score, _ = score_extremes(rules, {"hip_angle": {"max": 172, "min": 60}})
    assert score == 100.0


def test_penalty_is_capped():
    rules = [ScoringRule("knee_angle", "min", 90, HIGHER_IS_WORSE, 0, 10, 30)]
    score, _ = score_extremes(rules, {"knee_angle": {"min": 200, "max": 200}})
    assert score == 70.0  # raw 1100 penalty capped at 30


def test_score_floored_at_zero():
    rules = [
        ScoringRule("a", "min", 0, HIGHER_IS_WORSE, 0, 1, 200),
        ScoringRule("b", "max", 0, HIGHER_IS_WORSE, 0, 1, 200),
    ]
    score, _ = score_extremes(rules, {"a": {"min": 300}, "b": {"max": 50}})
    assert score == 0.0


def test_missing_metric_is_skipped():
    rules = [ScoringRule("absent", "min", 0, HIGHER_IS_WORSE, 0, 1, 50)]
    score, breakdown = score_extremes(rules, {"knee_angle": {"min": 90}})
    assert score == 100.0
    assert breakdown == []


def test_squat_analyzer_scores_better_rep_higher():
    from app.exercises.squat import SquatAnalyzer

    a = SquatAnalyzer()
    good, _ = a.score_rep({"knee_angle": {"min": 85, "max": 178}, "torso_lean": {"min": 5, "max": 20}})
    bad, _ = a.score_rep({"knee_angle": {"min": 130, "max": 178}, "torso_lean": {"min": 5, "max": 70}})
    assert good == 100.0
    assert bad < good


# ----- live deviation (drives the yellow→red tint) ------------------------ #

BOUNDS = [LiveBound("torso_lean", good=45.0, limit=80.0, direction=HIGHER_IS_WORSE)]


def test_live_deviation_zero_in_bounds():
    assert live_deviation(BOUNDS, {"torso_lean": 20}) == 0.0
    assert live_deviation(BOUNDS, {"torso_lean": 45}) == 0.0  # exactly at good edge


def test_live_deviation_ramps_to_one():
    assert live_deviation(BOUNDS, {"torso_lean": 62.5}) == pytest.approx(0.5)
    assert live_deviation(BOUNDS, {"torso_lean": 80}) == 1.0
    assert live_deviation(BOUNDS, {"torso_lean": 120}) == 1.0  # clamped


def test_live_deviation_lower_is_worse():
    b = [LiveBound("hip_angle", good=170.0, limit=150.0, direction=LOWER_IS_WORSE)]
    assert live_deviation(b, {"hip_angle": 175}) == 0.0
    assert live_deviation(b, {"hip_angle": 160}) == pytest.approx(0.5)
    assert live_deviation(b, {"hip_angle": 140}) == 1.0


def test_live_deviation_missing_metric_is_zero():
    assert live_deviation(BOUNDS, {}) == 0.0


def test_live_deviation_takes_worst_bound():
    bounds = [
        LiveBound("a", good=0.0, limit=10.0, direction=HIGHER_IS_WORSE),
        LiveBound("b", good=0.0, limit=10.0, direction=HIGHER_IS_WORSE),
    ]
    assert live_deviation(bounds, {"a": 2, "b": 8}) == pytest.approx(0.8)
