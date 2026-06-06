"""Deadlift analyzer.

Rep counting is driven by the **hip angle** (shoulder-hip-knee): the lifter
hinges down (small hip angle) and drives up to a tall lockout (large hip
angle). Form checks (first-pass heuristics, tuned against side-on framing):

* ``incomplete_lockout`` -- hips never fully extended at the top.
* ``back_too_horizontal`` -- torso pitched dangerously flat at the bottom,
  the classic "stripper / good-morning" deadlift fault.
"""

from __future__ import annotations

from typing import Dict, List

from app.exercises.base import ExerciseAnalyzer, FormIssue, Severity
from app.geometry import angle_with_vertical
from app.landmarks import PoseFrame, PoseLandmark as L
from app.scoring import HIGHER_IS_WORSE, LOWER_IS_WORSE, LiveBound, ScoringRule


class DeadliftAnalyzer(ExerciseAnalyzer):
    name = "deadlift"
    display_name = "Deadlift"
    primary_metric = "hip_angle"

    # Hysteresis band on the hip angle: hinge below 120 to "arm" a rep,
    # extend back above 160 to complete it.
    down_enter = 120.0
    up_enter = 160.0

    # Coaching thresholds.
    lockout_target = 168.0    # hip angle that counts as a full lockout
    max_bottom_lean = 75.0    # torso deviation from vertical at the bottom

    down_cue = "Hinge at the hips, flat back, and keep the bar close to your shins."
    up_cue = "Drive through the floor and stand tall — lock out hips and knees."

    # One full leg+torso chain per side; analysis runs as long as either side
    # is visible (so a side-on view, which occludes the far side, still works).
    required_sides = (
        (L.LEFT_SHOULDER, L.LEFT_HIP, L.LEFT_KNEE, L.LEFT_ANKLE),
        (L.RIGHT_SHOULDER, L.RIGHT_HIP, L.RIGHT_KNEE, L.RIGHT_ANKLE),
    )

    # Reward a full lockout (high max hip angle) without an unsafe, overly
    # horizontal back at the bottom (high max lean).
    scoring_rules = (
        ScoringRule(
            metric="hip_angle", aggregate="max", ideal=178.0,
            direction=LOWER_IS_WORSE, tolerance=10.0,
            per_unit_penalty=1.5, max_penalty=45.0, label="lockout",
        ),
        ScoringRule(
            metric="torso_lean", aggregate="max", ideal=45.0,
            direction=HIGHER_IS_WORSE, tolerance=30.0,
            per_unit_penalty=1.0, max_penalty=35.0, label="back safety",
        ),
    )

    # A deadlift torso is legitimately inclined; only warn as the back approaches
    # horizontal — clear up to ~72°, fully red by ~88°.
    live_bounds = (
        LiveBound(metric="torso_lean", good=72.0, limit=88.0, direction=HIGHER_IS_WORSE),
    )

    def compute_metrics(self, frame: PoseFrame) -> Dict[str, float]:
        # Pick the usable side(s) once so hip, knee and torso all describe the
        # same side (never a blend of left + right on a borderline frame). The
        # bilateral wobble/asymmetry output is intentionally unused here: a
        # front-on knee asymmetry isn't a primary deadlift fault (unlike squat).
        sides = self.frame_sides(frame)
        hip, _, _ = self._bilateral_angle(
            frame,
            (L.LEFT_SHOULDER, L.LEFT_HIP, L.LEFT_KNEE),
            (L.RIGHT_SHOULDER, L.RIGHT_HIP, L.RIGHT_KNEE),
            sides,
        )
        knee, _, _ = self._bilateral_angle(
            frame,
            (L.LEFT_HIP, L.LEFT_KNEE, L.LEFT_ANKLE),
            (L.RIGHT_HIP, L.RIGHT_KNEE, L.RIGHT_ANKLE),
            sides,
        )
        hip_pt, shoulder_pt = self._bilateral_segment(
            frame, (L.LEFT_HIP, L.LEFT_SHOULDER), (L.RIGHT_HIP, L.RIGHT_SHOULDER), sides
        )
        torso_lean = angle_with_vertical(hip_pt, shoulder_pt)
        return {"hip_angle": hip, "knee_angle": knee, "torso_lean": torso_lean}

    def evaluate_form(self, metrics, extremes) -> List[FormIssue]:
        issues: List[FormIssue] = []

        max_hip = extremes.get("hip_angle", {}).get("max", metrics["hip_angle"])
        if max_hip < self.lockout_target:
            issues.append(
                FormIssue(
                    "incomplete_lockout",
                    f"Finish taller — fully extend your hips at the top "
                    f"(reached {max_hip:.0f}°, target ≥ {self.lockout_target:.0f}°).",
                    Severity.WARNING,
                )
            )

        max_lean = extremes.get("torso_lean", {}).get("max", metrics["torso_lean"])
        if max_lean > self.max_bottom_lean:
            issues.append(
                FormIssue(
                    "back_too_horizontal",
                    f"Your back went too horizontal ({max_lean:.0f}°). "
                    "Keep hips lower and chest up to protect your spine.",
                    Severity.WARNING,
                )
            )

        return issues
