import pytest

from app.landmarks import Landmark, NUM_LANDMARKS, PoseFrame, PoseLandmark


def _dicts(n=NUM_LANDMARKS):
    return [{"x": i / 100, "y": i / 50, "z": 0.0, "visibility": 1.0} for i in range(n)]


def test_pose_landmark_indices():
    assert PoseLandmark.NOSE == 0
    assert PoseLandmark.LEFT_KNEE == 25
    assert PoseLandmark.RIGHT_FOOT_INDEX == 32
    assert len(PoseLandmark) == NUM_LANDMARKS


def test_from_list_with_dicts_indexes_by_name():
    frame = PoseFrame.from_list(_dicts())
    assert len(frame) == NUM_LANDMARKS
    knee = frame[PoseLandmark.LEFT_KNEE]
    assert knee.x == pytest.approx(25 / 100)
    assert knee.visibility == 1.0


def test_from_list_with_sequences_and_defaults():
    data = [[i / 100, i / 50] for i in range(NUM_LANDMARKS)]
    frame = PoseFrame.from_list(data)
    assert frame[PoseLandmark.NOSE].z == 0.0
    assert frame[PoseLandmark.NOSE].visibility == 1.0


def test_from_list_reads_score_alias():
    data = _dicts()
    data[0] = {"x": 0.1, "y": 0.2, "score": 0.3}
    frame = PoseFrame.from_list(data)
    assert frame[PoseLandmark.NOSE].visibility == pytest.approx(0.3)


def test_wrong_length_raises():
    with pytest.raises(ValueError):
        PoseFrame([Landmark(0, 0)])
    with pytest.raises(ValueError):
        PoseFrame.from_list(_dicts(10))


def test_min_visibility():
    data = _dicts()
    data[PoseLandmark.LEFT_KNEE] = {"x": 0, "y": 0, "visibility": 0.2}
    frame = PoseFrame.from_list(data)
    assert frame.min_visibility([PoseLandmark.LEFT_KNEE, PoseLandmark.NOSE]) == pytest.approx(0.2)
