"""Squat analyzer.

Rep counting is driven by the **knee angle** (hip-knee-ankle), averaged across
both legs. Form checks (first-pass heuristics, tuned against side-on framing):

* ``insufficient_depth`` -- the lifter never broke roughly parallel.
* ``excessive_forward_lean`` -- the torso pitched too far from vertical.
"""

from __future__ import annotations

from typing import Dict, List

from app.exercises.base import ExerciseAnalyzer, FormIssue, Severity
from app.geometry import angle_with_vertical
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
    # Both knees must be this visible (a margin above MIN_VISIBILITY) before we
    # judge wobble, so a far leg hovering at the gate can't flicker the metric.
    WOBBLE_MIN_VIS = 0.6

    down_cue = "Sit back and down — keep your chest up and knees tracking out."
    up_cue = "Stand tall and squeeze your glutes to finish the rep."

    # One full leg+torso chain per side; analysis runs as long as either side
    # is visible (so a side-on view, which occludes the far side, still works).
    required_sides = (
        (L.LEFT_SHOULDER, L.LEFT_HIP, L.LEFT_KNEE, L.LEFT_ANKLE),
        (L.RIGHT_SHOULDER, L.RIGHT_HIP, L.RIGHT_KNEE, L.RIGHT_ANKLE),
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

    # Live tint:
    #  * torso_lean -- clear through a normal squat's incline (~35°), ramping to
    #    fully red by ~65° (just past the excessive-lean fault at 55°). The old
    #    good=45/limit=80 band stayed clear through almost the whole movement and
    #    could never reach red (lean tops out at 90°).
    #  * knee_asymmetry -- only emitted when both legs are visible (a front-on
    #    view); flags side-to-side wobble / one knee caving relative to the other.
    live_bounds = (
        LiveBound(metric="torso_lean", good=35.0, limit=65.0, direction=HIGHER_IS_WORSE),
        LiveBound(metric="knee_asymmetry", good=18.0, limit=45.0, direction=HIGHER_IS_WORSE),
    )

    def compute_metrics(self, frame: PoseFrame) -> Dict[str, float]:
        # Pick the usable side(s) once so knee, hip and torso all describe the
        # same leg (never a blend of left + right on a borderline frame).
        sides = self.frame_sides(frame)
        knee, both, knee_asym = self._bilateral_angle(
            frame,
            (L.LEFT_HIP, L.LEFT_KNEE, L.LEFT_ANKLE),
            (L.RIGHT_HIP, L.RIGHT_KNEE, L.RIGHT_ANKLE),
            sides,
        )
        hip, _, _ = self._bilateral_angle(
            frame,
            (L.LEFT_SHOULDER, L.LEFT_HIP, L.LEFT_KNEE),
            (L.RIGHT_SHOULDER, L.RIGHT_HIP, L.RIGHT_KNEE),
            sides,
        )
        hip_pt, shoulder_pt = self._bilateral_segment(
            frame, (L.LEFT_HIP, L.LEFT_SHOULDER), (L.RIGHT_HIP, L.RIGHT_SHOULDER), sides
        )
        torso_lean = angle_with_vertical(hip_pt, shoulder_pt)
        metrics = {"knee_angle": knee, "hip_angle": hip, "torso_lean": torso_lean}
        # Wobble (side-to-side knee asymmetry) is only meaningful when both legs
        # are clearly visible (a front-on view). `both` guarantees knee_asym is a
        # real |left - right| (not the single-side 0.0 sentinel); the >= 0.6
        # margin (stricter than `both`'s 0.5 visibility floor) then keeps a far
        # leg hovering at the gate from flickering the metric on/off. The margin
        # is what actually gates here; `both` documents the real precondition.
        left_chain, right_chain = self.required_sides
        if both and min(
            frame.min_visibility(left_chain), frame.min_visibility(right_chain)
        ) >= self.WOBBLE_MIN_VIS:
            metrics["knee_asymmetry"] = knee_asym
        return metrics

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
