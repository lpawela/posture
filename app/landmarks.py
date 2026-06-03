"""BlazePose landmark model.

MediaPipe's Pose Landmarker emits 33 body landmarks per frame. This module
provides a typed view over those landmarks so the rest of the codebase can
refer to joints by name (``PoseLandmark.LEFT_KNEE``) instead of magic indices,
and can build a frame straight from the JSON the browser sends.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable, Sequence

NUM_LANDMARKS = 33


class PoseLandmark(IntEnum):
    """Index of each BlazePose landmark (matches MediaPipe ordering)."""

    NOSE = 0
    LEFT_EYE_INNER = 1
    LEFT_EYE = 2
    LEFT_EYE_OUTER = 3
    RIGHT_EYE_INNER = 4
    RIGHT_EYE = 5
    RIGHT_EYE_OUTER = 6
    LEFT_EAR = 7
    RIGHT_EAR = 8
    MOUTH_LEFT = 9
    MOUTH_RIGHT = 10
    LEFT_SHOULDER = 11
    RIGHT_SHOULDER = 12
    LEFT_ELBOW = 13
    RIGHT_ELBOW = 14
    LEFT_WRIST = 15
    RIGHT_WRIST = 16
    LEFT_PINKY = 17
    RIGHT_PINKY = 18
    LEFT_INDEX = 19
    RIGHT_INDEX = 20
    LEFT_THUMB = 21
    RIGHT_THUMB = 22
    LEFT_HIP = 23
    RIGHT_HIP = 24
    LEFT_KNEE = 25
    RIGHT_KNEE = 26
    LEFT_ANKLE = 27
    RIGHT_ANKLE = 28
    LEFT_HEEL = 29
    RIGHT_HEEL = 30
    LEFT_FOOT_INDEX = 31
    RIGHT_FOOT_INDEX = 32


@dataclass(frozen=True)
class Landmark:
    """A single normalised landmark.

    ``x``/``y`` are in ``[0, 1]`` image space, ``z`` is depth relative to the
    hips (smaller = closer to camera), and ``visibility`` is MediaPipe's
    confidence that the point is present and not occluded.
    """

    x: float
    y: float
    z: float = 0.0
    visibility: float = 1.0


class PoseFrame:
    """An immutable snapshot of all 33 landmarks for one video frame."""

    __slots__ = ("_landmarks",)

    def __init__(self, landmarks: Sequence[Landmark]):
        if len(landmarks) != NUM_LANDMARKS:
            raise ValueError(
                f"expected {NUM_LANDMARKS} landmarks, got {len(landmarks)}"
            )
        self._landmarks = tuple(landmarks)

    def __getitem__(self, key) -> Landmark:
        # Accept PoseLandmark members or raw ints interchangeably.
        return self._landmarks[int(key)]

    def __len__(self) -> int:
        return len(self._landmarks)

    def __iter__(self):
        return iter(self._landmarks)

    def min_visibility(self, indices: Iterable[int]) -> float:
        """Lowest visibility among the given landmark indices."""
        return min(self._landmarks[int(i)].visibility for i in indices)

    @classmethod
    def from_list(cls, data: Iterable) -> "PoseFrame":
        """Build a frame from the browser payload.

        Accepts an iterable of either mappings (``{"x":.., "y":.., "z":..,
        "visibility":..}``) or sequences (``[x, y, z, visibility]``). Missing
        ``z`` defaults to ``0`` and missing ``visibility`` to ``1``.
        """
        landmarks: list[Landmark] = []
        for item in data:
            if isinstance(item, dict):
                landmarks.append(
                    Landmark(
                        x=float(item.get("x", 0.0)),
                        y=float(item.get("y", 0.0)),
                        z=float(item.get("z", 0.0)),
                        visibility=float(
                            item.get("visibility", item.get("score", 1.0))
                        ),
                    )
                )
            else:
                seq = list(item)
                landmarks.append(
                    Landmark(
                        x=float(seq[0]),
                        y=float(seq[1]),
                        z=float(seq[2]) if len(seq) > 2 else 0.0,
                        visibility=float(seq[3]) if len(seq) > 3 else 1.0,
                    )
                )
        return cls(landmarks)
