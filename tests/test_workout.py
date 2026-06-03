import pytest

from app.workout import WorkoutSession


def test_counts_reps_and_sets_with_target():
    s = WorkoutSession("squat", target_sets=3, target_reps=12)
    for _ in range(36):
        s.record_rep(100)
    summary = s.finish()
    assert summary.total_reps == 36
    assert summary.total_sets == 3
    assert summary.set_scores == [100.0, 100.0, 100.0]
    assert summary.completion_ratio == 1.0
    assert summary.overall_score == 100.0


def test_auto_closes_set_at_target_reps():
    s = WorkoutSession("squat", target_sets=2, target_reps=2)
    s.record_rep(100)
    assert s.completed_sets == 0 and s.current_set_reps == 1
    s.record_rep(100)
    assert s.completed_sets == 1 and s.current_set_reps == 0
    s.record_rep(100)
    s.record_rep(100)
    summary = s.finish()
    assert summary.total_sets == 2 and summary.total_reps == 4


def test_manual_set_boundaries_without_target():
    s = WorkoutSession("deadlift")
    s.record_rep(90)
    s.record_rep(80)
    s.end_set()
    s.record_rep(70)
    summary = s.finish()
    assert summary.total_sets == 2
    assert summary.total_reps == 3
    assert summary.set_scores == [85.0, 70.0]
    assert summary.completion_ratio is None
    assert summary.form_score == pytest.approx(80.0, abs=0.05)
    assert summary.overall_score == summary.form_score


def test_incomplete_workout_lowers_overall_score():
    s = WorkoutSession("squat", target_sets=3, target_reps=12)
    for _ in range(18):  # half the prescribed volume, perfect form
        s.record_rep(100)
    summary = s.finish()
    assert summary.total_reps == 18
    assert summary.total_sets == 2  # 12 (auto-closed) + 6
    assert summary.completion_ratio == 0.5
    assert summary.form_score == 100.0
    # overall = form * (0.5 + 0.5 * completion) = 100 * 0.75
    assert summary.overall_score == 75.0


def test_empty_session():
    s = WorkoutSession("squat", target_sets=3, target_reps=12)
    summary = s.finish()
    assert summary.total_reps == 0
    assert summary.total_sets == 0
    assert summary.form_score == 0.0
    assert summary.completion_ratio == 0.0
    assert summary.overall_score == 0.0


def test_end_set_is_noop_when_empty():
    s = WorkoutSession("squat")
    s.end_set()
    s.end_set()
    assert s.completed_sets == 0


def test_summary_to_dict():
    s = WorkoutSession("squat", 1, 2)
    s.record_rep(100)
    s.record_rep(80)
    d = s.finish().to_dict()
    assert d["exercise"] == "squat"
    assert set(d) == {
        "exercise", "total_sets", "total_reps", "set_scores",
        "form_score", "completion_ratio", "overall_score",
    }
