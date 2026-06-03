"""Synthetic pose builders for deterministic analyzer tests.

We construct sagittal-plane (side-on) poses where the joint angle that drives a
given analyzer is realised *exactly*, so tests can assert on rep counting and
form thresholds without depending on a real camera.
"""

import math

from app.landmarks import Landmark, PoseFrame, PoseLandmark as L, NUM_LANDMARKS

L_THIGH = 0.18
L_SHANK = 0.18
L_TORSO = 0.25
_HALF_WIDTH = 0.03  # left/right x-offset (a pure translation per leg → angle preserved)


def _down_dir(angle_deg):
    """Unit vector at `angle_deg` from the downward axis (0, 1), tilting +x.

    At 180° it points straight up (0, -1); at 90° straight forward (1, 0).
    """
    a = math.radians(angle_deg)
    return (math.sin(a), math.cos(a))


def _rotate(v, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def _torso_dir(lean_deg):
    """hip -> shoulder direction for a torso leaning `lean_deg` from vertical."""
    return (math.sin(math.radians(lean_deg)), -math.cos(math.radians(lean_deg)))


def _build(shoulder, hip, knee, ankle, visibility):
    landmarks = [Landmark(0.5, 0.5, 0.0, visibility) for _ in range(NUM_LANDMARKS)]
    joints = (
        (L.LEFT_SHOULDER, shoulder), (L.RIGHT_SHOULDER, shoulder),
        (L.LEFT_HIP, hip), (L.RIGHT_HIP, hip),
        (L.LEFT_KNEE, knee), (L.RIGHT_KNEE, knee),
        (L.LEFT_ANKLE, ankle), (L.RIGHT_ANKLE, ankle),
    )
    for idx, (x, y) in joints:
        sign = -1 if "LEFT" in idx.name else 1
        landmarks[int(idx)] = Landmark(x + sign * _HALF_WIDTH, y, 0.0, visibility)
    return PoseFrame(landmarks)


def squat_pose(knee_angle=178.0, torso_lean=8.0, visibility=1.0):
    """Pose with an exact knee angle (hip-knee-ankle) and torso lean."""
    ankle = (0.5, 0.90)
    knee = (ankle[0], ankle[1] - L_SHANK)                 # shank vertical
    hd = _down_dir(knee_angle)                            # knee -> hip
    hip = (knee[0] + L_THIGH * hd[0], knee[1] + L_THIGH * hd[1])
    td = _torso_dir(torso_lean)
    shoulder = (hip[0] + L_TORSO * td[0], hip[1] + L_TORSO * td[1])
    return _build(shoulder, hip, knee, ankle, visibility)


def deadlift_pose(hip_angle=178.0, torso_lean=8.0, visibility=1.0):
    """Pose with an exact hip angle (shoulder-hip-knee) and torso lean."""
    hip = (0.5, 0.55)
    td = _torso_dir(torso_lean)                           # hip -> shoulder
    shoulder = (hip[0] + L_TORSO * td[0], hip[1] + L_TORSO * td[1])
    # hip -> knee makes `hip_angle` with hip -> shoulder; take the downward one.
    cand1, cand2 = _rotate(td, hip_angle), _rotate(td, -hip_angle)
    kd = cand1 if cand1[1] > cand2[1] else cand2          # larger y = downward
    knee = (hip[0] + L_THIGH * kd[0], hip[1] + L_THIGH * kd[1])
    ankle = (knee[0], knee[1] + L_SHANK)                  # shank straight down
    return _build(shoulder, hip, knee, ankle, visibility)


def to_landmark_dicts(frame):
    """Serialise a frame to the JSON shape the browser sends."""
    return [
        {"x": lm.x, "y": lm.y, "z": lm.z, "visibility": lm.visibility}
        for lm in frame
    ]
