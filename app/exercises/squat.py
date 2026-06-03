"""Squat analyzer.

Rep counting is driven by the **knee angle** (hip-knee-ankle), averaged across
both legs. Form checks (first-pass heuristics, tuned against side-on framing):

* ``insufficient_depth`` -- the lifter never broke roughly parallel.
* ``excessive_forward_lean`` -- the torso pitched too far from vertical.
"""

from __future__ import annotations

from typing import Dict, List

from app.exercises.base import ExerciseAnalyzer, FormIssue, Severity
from app.geometry import angle, angle_with_vertical, midpoint
from app.landmarks import PoseFrame, PoseLandmark as L
from app.scoring import HIGHER_IS_WORSE, LiveBound, ScoringRule


class SquatAnalyzer(ExerciseAnalyzer):
    name = "squat"
    display_name = "Squat"
    primary_metric = "knee_angle"

    # Hysteresis band on the knee angle: descend below 120 to "arm" a rep,
    # rise back above 160 to complete it.
    down_enter = 120.0
    up_enter = 160.0

    # Coaching thresholds.
    depth_target = 100.0      # knee angle at the bottom for ~parallel depth
    max_forward_lean = 55.0   # torso deviation from vertical (degrees)

    down_cue = "Sit back and down — keep your chest up and knees tracking out."
    up_cue = "Stand tall and squeeze your glutes to finish the rep."

    required_landmarks = (
        L.LEFT_SHOULDER, L.RIGHT_SHOULDER,
        L.LEFT_HIP, L.RIGHT_HIP,
        L.LEFT_KNEE, L.RIGHT_KNEE,
        L.LEFT_ANKLE, L.RIGHT_ANKLE,
    )

    # Reward a deep squat (low min knee angle) held upright (low max lean).
    scoring_rules = (
        ScoringRule(
            metric="knee_angle", aggregate="min", ideal=90.0,
            direction=HIGHER_IS_WORSE, tolerance=15.0,
            per_unit_penalty=1.5, max_penalty=45.0, label="depth",
        ),
        ScoringRule(
            metric="torso_lean", aggregate="max", ideal=10.0,
            direction=HIGHER_IS_WORSE, tolerance=35.0,
            per_unit_penalty=1.0, max_penalty=35.0, label="upright torso",
        ),
    )

    # Live tint: clear up to ~45° of forward lean, fully red by ~80°.
    live_bounds = (
        LiveBound(metric="torso_lean", good=45.0, limit=80.0, direction=HIGHER_IS_WORSE),
    )

    def compute_metrics(self, frame: PoseFrame) -> Dict[str, float]:
        knee = 0.5 * (
            angle(frame[L.LEFT_HIP], frame[L.LEFT_KNEE], frame[L.LEFT_ANKLE])
            + angle(frame[L.RIGHT_HIP], frame[L.RIGHT_KNEE], frame[L.RIGHT_ANKLE])
        )
        hip = 0.5 * (
            angle(frame[L.LEFT_SHOULDER], frame[L.LEFT_HIP], frame[L.LEFT_KNEE])
            + angle(frame[L.RIGHT_SHOULDER], frame[L.RIGHT_HIP], frame[L.RIGHT_KNEE])
        )
        shoulder_mid = midpoint(frame[L.LEFT_SHOULDER], frame[L.RIGHT_SHOULDER])
        hip_mid = midpoint(frame[L.LEFT_HIP], frame[L.RIGHT_HIP])
        torso_lean = angle_with_vertical(hip_mid, shoulder_mid)
        return {"knee_angle": knee, "hip_angle": hip, "torso_lean": torso_lean}

    def evaluate_form(self, metrics, extremes) -> List[FormIssue]:
        issues: List[FormIssue] = []

        min_knee = extremes.get("knee_angle", {}).get("min", metrics["knee_angle"])
        if min_knee > self.depth_target:
            issues.append(
                FormIssue(
                    "insufficient_depth",
                    f"Squat deeper — aim for at least parallel "
                    f"(knee bent to {min_knee:.0f}°, target ≤ {self.depth_target:.0f}°).",
                    Severity.WARNING,
                )
            )

        max_lean = extremes.get("torso_lean", {}).get("max", metrics["torso_lean"])
        if max_lean > self.max_forward_lean:
            issues.append(
                FormIssue(
                    "excessive_forward_lean",
                    f"Too much forward lean ({max_lean:.0f}°). "
                    "Keep your chest up and weight over mid-foot.",
                    Severity.WARNING,
                )
            )

        return issues
