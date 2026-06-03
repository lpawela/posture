import math

import pytest

from app.geometry import angle, angle_with_vertical, midpoint, xy
from app.landmarks import Landmark


def test_xy_accepts_attributes_and_sequences():
    assert xy(Landmark(0.2, 0.7)) == (0.2, 0.7)
    assert xy((0.2, 0.7)) == (0.2, 0.7)
    assert xy([0.2, 0.7, 0.1]) == (0.2, 0.7)


def test_angle_straight_line_is_180():
    assert angle((0, 0), (1, 0), (2, 0)) == pytest.approx(180.0)


def test_angle_right_angle_is_90():
    assert angle((0, 1), (0, 0), (1, 0)) == pytest.approx(90.0)


def test_angle_45_degrees():
    assert angle((0, 1), (0, 0), (1, 1)) == pytest.approx(45.0)


def test_angle_is_symmetric_in_outer_points():
    a, b, c = (0.3, 0.1), (0.5, 0.5), (0.9, 0.2)
    assert angle(a, b, c) == pytest.approx(angle(c, b, a))


def test_angle_rejects_coincident_points():
    with pytest.raises(ValueError):
        angle((0, 0), (0, 0), (1, 0))


def test_angle_with_vertical():
    assert angle_with_vertical((0.5, 0.1), (0.5, 0.9)) == pytest.approx(0.0)
    assert angle_with_vertical((0.1, 0.5), (0.9, 0.5)) == pytest.approx(90.0)
    assert angle_with_vertical((0.0, 0.0), (1.0, 1.0)) == pytest.approx(45.0)


def test_angle_with_vertical_ignores_direction():
    # Up-going and down-going segments deviate from vertical equally.
    assert angle_with_vertical((0, 0), (1, 1)) == pytest.approx(
        angle_with_vertical((0, 0), (1, -1))
    )


def test_angle_with_vertical_rejects_zero_length():
    with pytest.raises(ValueError):
        angle_with_vertical((0.5, 0.5), (0.5, 0.5))


def test_midpoint():
    assert midpoint((0, 0), (1, 1)) == (0.5, 0.5)
    assert midpoint(Landmark(0.2, 0.4), Landmark(0.6, 0.8)) == pytest.approx((0.4, 0.6))
