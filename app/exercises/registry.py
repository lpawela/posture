"""Registry mapping exercise names to analyzers, metadata and reference videos.

The reference videos were verified live via YouTube's oEmbed endpoint (title +
channel resolved successfully) at build time.
"""

from __future__ import annotations

from typing import Dict, List, Type

from app.exercises.base import ExerciseAnalyzer
from app.exercises.deadlift import DeadliftAnalyzer
from app.exercises.squat import SquatAnalyzer

_ANALYZERS: Dict[str, Type[ExerciseAnalyzer]] = {
    SquatAnalyzer.name: SquatAnalyzer,
    DeadliftAnalyzer.name: DeadliftAnalyzer,
}

DESCRIPTIONS: Dict[str, str] = {
    "squat": (
        "Tracks knee and hip angles to count reps and flag shallow depth or "
        "excessive forward lean."
    ),
    "deadlift": (
        "Tracks the hip hinge to count reps and flag incomplete lockout or an "
        "overly horizontal back at the bottom."
    ),
}

# Verified reference movies (oEmbed-confirmed titles/channels).
REFERENCE_VIDEOS: Dict[str, dict] = {
    "squat": {
        "title": "How To Squat: Layne Norton's Squat Tutorial",
        "channel": "Bodybuilding.com",
        "video_id": "t2b8UdqmlFs",
        "url": "https://www.youtube.com/watch?v=t2b8UdqmlFs",
    },
    "deadlift": {
        "title": '"How To" Deadlift',
        "channel": "Alan Thrall (Untamed Strength)",
        "video_id": "Y1IGeJEXpF4",
        "url": "https://www.youtube.com/watch?v=Y1IGeJEXpF4",
    },
}


def available_exercises() -> List[str]:
    """Names of all registered exercises."""
    return list(_ANALYZERS)


def get_analyzer(name: str) -> ExerciseAnalyzer:
    """Instantiate a fresh analyzer for ``name``.

    Raises :class:`ValueError` for an unknown exercise.
    """
    try:
        return _ANALYZERS[name]()
    except KeyError:
        raise ValueError(
            f"unknown exercise '{name}'; choose one of {available_exercises()}"
        ) from None


def exercise_info(name: str) -> dict:
    """Public metadata for one exercise (name, label, description, video)."""
    if name not in _ANALYZERS:
        raise ValueError(f"unknown exercise '{name}'")
    analyzer = _ANALYZERS[name]
    return {
        "name": name,
        "display_name": analyzer.display_name,
        "description": DESCRIPTIONS.get(name, ""),
        "reference_video": REFERENCE_VIDEOS.get(name),
    }


def list_exercises() -> List[dict]:
    """Metadata for every registered exercise."""
    return [exercise_info(name) for name in _ANALYZERS]
