"""2D geometric helpers for pose analysis.

All helpers accept *points*: anything exposing ``x``/``y`` attributes (e.g.
:class:`app.landmarks.Landmark`) or a 2+ element sequence ``(x, y, ...)``.
Coordinates are assumed to be in normalised image space where ``y`` grows
*downward*, matching the convention used by MediaPipe pose landmarks.

These functions are pure and dependency-free so they can be unit tested in
isolation from the web stack.
"""

from __future__ import annotations

import math

__all__ = ["xy", "angle", "angle_with_vertical", "midpoint"]


def xy(point) -> tuple[float, float]:
    """Coerce a point into an ``(x, y)`` float tuple."""
    if hasattr(point, "x") and hasattr(point, "y"):
        return float(point.x), float(point.y)
    return float(point[0]), float(point[1])


def angle(a, b, c) -> float:
    """Interior angle at vertex ``b`` of the path ``a -> b -> c``, in degrees.

    The result is in ``[0, 180]``. Raises :class:`ValueError` if ``a`` or ``c``
    coincides with ``b`` (an undefined angle).
    """
    ax, ay = xy(a)
    bx, by = xy(b)
    cx, cy = xy(c)
    v1 = (ax - bx, ay - by)
    v2 = (cx - bx, cy - by)
    m1 = math.hypot(*v1)
    m2 = math.hypot(*v2)
    if m1 == 0.0 or m2 == 0.0:
        raise ValueError("angle() requires three distinct points")
    cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (m1 * m2)
    cos = max(-1.0, min(1.0, cos))  # guard against fp drift outside [-1, 1]
    return math.degrees(math.acos(cos))


def angle_with_vertical(a, b) -> float:
    """Deviation of segment ``a -> b`` from the vertical axis, in degrees.

    ``0`` means perfectly vertical, ``90`` means horizontal. Direction along
    the segment is ignored, so the result is always in ``[0, 90]`` -- handy for
    "forward lean" style checks. Raises :class:`ValueError` for a zero-length
    segment.
    """
    ax, ay = xy(a)
    bx, by = xy(b)
    dx = bx - ax
    dy = by - ay
    length = math.hypot(dx, dy)
    if length == 0.0:
        raise ValueError("angle_with_vertical() requires two distinct points")
    cos = abs(dy) / length  # projection onto the (0, 1) vertical axis
    cos = max(-1.0, min(1.0, cos))
    return math.degrees(math.acos(cos))


def midpoint(a, b) -> tuple[float, float]:
    """Midpoint of two points as an ``(x, y)`` tuple."""
    ax, ay = xy(a)
    bx, by = xy(b)
    return ((ax + bx) / 2.0, (ay + by) / 2.0)
