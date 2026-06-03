import pytest

from app.exercises.base import ExerciseAnalyzer
from app.exercises.deadlift import DeadliftAnalyzer
from app.exercises.registry import (
    available_exercises,
    exercise_info,
    get_analyzer,
    list_exercises,
)
from app.exercises.squat import SquatAnalyzer


def test_available_exercises():
    assert set(available_exercises()) == {"squat", "deadlift"}


def test_get_analyzer_returns_fresh_instances():
    a = get_analyzer("squat")
    b = get_analyzer("squat")
    assert isinstance(a, SquatAnalyzer)
    assert isinstance(get_analyzer("deadlift"), DeadliftAnalyzer)
    assert a is not b  # independent state per session


def test_get_analyzer_unknown_raises():
    with pytest.raises(ValueError):
        get_analyzer("bench_press")


def test_exercise_info_shape():
    info = exercise_info("squat")
    assert info["name"] == "squat"
    assert info["display_name"] == "Squat"
    assert info["description"]
    assert info["reference_video"]["url"].startswith("https://www.youtube.com/")


def test_list_exercises_has_verified_reference_videos():
    items = {item["name"]: item for item in list_exercises()}
    assert items["squat"]["reference_video"]["video_id"] == "t2b8UdqmlFs"
    assert items["deadlift"]["reference_video"]["video_id"] == "Y1IGeJEXpF4"
    for item in items.values():
        assert isinstance(get_analyzer(item["name"]), ExerciseAnalyzer)
