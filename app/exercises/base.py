"""Shared analyzer scaffolding: result types and the rep-counting machine.

An :class:`ExerciseAnalyzer` is fed one :class:`~app.landmarks.PoseFrame` at a
time via :meth:`~ExerciseAnalyzer.update`. It maintains a small hysteresis
state machine on a *primary* joint angle to count reps, tracks the min/max of
every metric across the current rep, and -- on each completed rep -- runs the
exercise-specific form checks.

Subclasses provide the per-frame metrics and the form rules; the rep counting,
visibility gating and feedback wiring live here so squat/deadlift stay tiny.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from app.geometry import angle, midpoint
from app.landmarks import PoseFrame
from app.scoring import LiveBound, ScoringRule, live_deviation, score_extremes

# A landmark is "present" for analysis once MediaPipe is at least this
# confident; below it we tell the user to step into frame rather than emit
# garbage angles.
MIN_VISIBILITY = 0.5


class RepState(str, Enum):
    """Where the lifter is in the rep cycle."""

    UP = "up"      # top / lockout / standing
    DOWN = "down"  # bottom of the movement


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"


@dataclass(frozen=True)
class FormIssue:
    """A single coaching cue raised after a completed rep."""

    code: str
    message: str
    severity: Severity = Severity.WARNING

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
        }


@dataclass
class AnalysisResult:
    """What the analyzer reports for a single frame."""

    exercise: str
    rep_count: int
    state: str
    pose_visible: bool
    metrics: Dict[str, float] = field(default_factory=dict)
    form_issues: List[FormIssue] = field(default_factory=list)
    feedback: str = ""
    # Set only on the frame where a rep completes: the rep's form score
    # (0-100) and a per-rule penalty breakdown. ``None`` otherwise.
    rep_score: Optional[float] = None
    score_breakdown: List[dict] = field(default_factory=list)
    # Live "out of bounds" severity for this frame, 0 (in bounds) .. 1 (far out).
    deviation: float = 0.0

    def to_dict(self) -> dict:
        return {
            "exercise": self.exercise,
            "rep_count": self.rep_count,
            "state": self.state,
            "pose_visible": self.pose_visible,
            "metrics": {k: round(v, 1) for k, v in self.metrics.items()},
            "form_issues": [i.to_dict() for i in self.form_issues],
            "feedback": self.feedback,
            "rep_score": round(self.rep_score, 1) if self.rep_score is not None else None,
            "score_breakdown": self.score_breakdown,
            "deviation": round(self.deviation, 3),
        }


class ExerciseAnalyzer(ABC):
    """Base class for stateful, per-frame exercise analyzers."""

    #: stable identifier used in the API/registry (e.g. ``"squat"``)
    name: str = ""
    #: human-friendly label (e.g. ``"Squat"``)
    display_name: str = ""
    #: which metric drives the rep state machine (key of ``compute_metrics``)
    primary_metric: str = ""
    #: primary angle at/below which we consider the lifter to have descended
    down_enter: float = 0.0
    #: primary angle at/above which a descended lifter has returned to the top
    up_enter: float = 180.0
    #: landmark groups, one per body side (e.g. left chain, right chain). The
    #: pose is "visible" when at least *one* side is fully visible, so a side-on
    #: view -- which occludes the far side -- still analyses cleanly.
    required_sides: Tuple[Tuple[int, ...], ...] = ()
    #: cues shown live while descending / ascending
    down_cue: str = ""
    up_cue: str = ""
    #: rules used to score each completed rep (see :mod:`app.scoring`)
    scoring_rules: Tuple[ScoringRule, ...] = ()
    #: per-frame "in bounds" ranges driving the live out-of-bounds tint
    live_bounds: Tuple[LiveBound, ...] = ()

    def __init__(self) -> None:
        # frame_sides assumes a left/right pair; fail loudly at construction (not
        # silently as a permanent "not visible") if a subclass is misconfigured.
        if self.required_sides and len(self.required_sides) != 2:
            raise TypeError(
                f"{type(self).__name__}.required_sides must have exactly two "
                f"side chains (got {len(self.required_sides)})"
            )
        self.reset()

    def reset(self) -> None:
        """Clear all counting/tracking state (new session)."""
        self._state = RepState.UP
        self._rep_count = 0
        self._extremes: Dict[str, Dict[str, float]] = {}

    # ----- subclass hooks ------------------------------------------------- #

    @abstractmethod
    def compute_metrics(self, frame: PoseFrame) -> Dict[str, float]:
        """Return the joint angles / measurements of interest for ``frame``."""

    @abstractmethod
    def evaluate_form(
        self, metrics: Dict[str, float], extremes: Dict[str, Dict[str, float]]
    ) -> List[FormIssue]:
        """Assess a *just-completed* rep and return any coaching cues.

        ``extremes`` maps each metric to its ``{"min", "max"}`` over the rep.
        """

    # ----- driving the machine ------------------------------------------- #

    def pose_visible(self, frame: PoseFrame) -> bool:
        if not self.required_sides:
            return True
        return any(
            frame.min_visibility(side) >= MIN_VISIBILITY
            for side in self.required_sides
        )

    def frame_sides(self, frame: PoseFrame) -> Tuple[bool, bool]:
        """Decide, once per frame, which body side(s) are usable.

        Uses the *full* per-side chains in :attr:`required_sides` so every metric
        in a frame is taken from the same side — otherwise knee, hip and torso
        could each independently pick a different leg on a borderline frame and
        end up describing different bodies. Returns ``(use_left, use_right)``;
        :meth:`pose_visible` guarantees at least one is ``True``.
        """
        left, right = self.required_sides
        return (
            frame.min_visibility(left) >= MIN_VISIBILITY,
            frame.min_visibility(right) >= MIN_VISIBILITY,
        )

    @staticmethod
    def _bilateral_angle(
        frame: PoseFrame,
        left: Tuple[int, int, int],
        right: Tuple[int, int, int],
        sides: Tuple[bool, bool],
    ) -> Tuple[float, bool, float]:
        """Joint angle from the side(s) selected for this frame, plus a wobble summary.

        ``left``/``right`` are ``(a, vertex, c)`` landmark-index triples and
        ``sides`` is the ``(use_left, use_right)`` decision from
        :meth:`frame_sides`. When both sides are used (a front/back view) the
        result averages them; otherwise it uses the single selected side instead
        of diluting the real near-side angle with a noisy occluded one. Returns
        ``(value, both_used, asymmetry)`` where ``asymmetry`` is
        ``|left - right|`` (and ``0.0`` when only one side is used).

        Crucially, ``angle()`` is computed *only* for a selected side: MediaPipe
        collapses low-confidence occluded landmarks onto a single point, which
        would make ``angle()`` raise on the far side and (via ``update``) discard
        an otherwise-good side-on frame.
        """
        use_left, use_right = sides
        la = angle(frame[left[0]], frame[left[1]], frame[left[2]]) if use_left else None
        ra = angle(frame[right[0]], frame[right[1]], frame[right[2]]) if use_right else None
        if la is not None and ra is not None:
            return 0.5 * (la + ra), True, abs(la - ra)
        # frame_sides/pose_visible guarantee at least one side is used.
        return (la if la is not None else ra), False, 0.0

    @staticmethod
    def _bilateral_segment(
        frame: PoseFrame,
        left: Tuple[int, int],
        right: Tuple[int, int],
        sides: Tuple[bool, bool],
    ):
        """Endpoints of a body segment from the side(s) selected for this frame.

        ``left``/``right`` are ``(lower, upper)`` landmark-index pairs (e.g.
        ``(HIP, SHOULDER)`` for the torso) and ``sides`` is the
        ``(use_left, use_right)`` decision. Returns ``(lower, upper)`` points:
        the midpoints of both sides when both are used, otherwise the selected
        side's two points — so an occluded far-side shoulder/hip doesn't pollute
        a side-on segment (and the metric built from it).
        """
        use_left, use_right = sides
        if use_left and use_right:
            return (
                midpoint(frame[left[0]], frame[right[0]]),
                midpoint(frame[left[1]], frame[right[1]]),
            )
        chosen = left if use_left else right
        return frame[chosen[0]], frame[chosen[1]]

    def update(self, frame: PoseFrame) -> AnalysisResult:
        """Process one frame and return the current analysis."""
        if not self.pose_visible(frame):
            return AnalysisResult(
                exercise=self.name,
                rep_count=self._rep_count,
                state=self._state.value,
                pose_visible=False,
                feedback="Step back so your whole body is visible in frame.",
            )

        try:
            metrics = self.compute_metrics(frame)
        except ValueError:
            # A degenerate frame (e.g. coincident landmarks from a momentary
            # tracking glitch) makes an angle undefined. Skip it rather than
            # letting the exception abort the whole live session.
            return AnalysisResult(
                exercise=self.name,
                rep_count=self._rep_count,
                state=self._state.value,
                pose_visible=False,
                feedback="Hold steady — move so your joints are clearly separated.",
            )
        primary = metrics[self.primary_metric]

        completed = False
        if self._state is RepState.UP and primary <= self.down_enter:
            # Start of a descent: begin tracking this rep fresh.
            self._state = RepState.DOWN
            self._extremes = {}
        elif self._state is RepState.DOWN and primary >= self.up_enter:
            self._state = RepState.UP
            completed = True

        self._accumulate(metrics)

        issues: List[FormIssue] = []
        rep_score: Optional[float] = None
        breakdown: List[dict] = []
        if completed:
            self._rep_count += 1
            issues = self.evaluate_form(metrics, self._extremes)
            rep_score, breakdown = self.score_rep(self._extremes)

        return AnalysisResult(
            exercise=self.name,
            rep_count=self._rep_count,
            state=self._state.value,
            pose_visible=True,
            metrics=metrics,
            form_issues=issues,
            feedback=self._feedback(issues, completed, primary),
            rep_score=rep_score,
            score_breakdown=breakdown,
            deviation=live_deviation(list(self.live_bounds), metrics),
        )

    def score_rep(self, extremes: Dict[str, Dict[str, float]]) -> Tuple[float, List[dict]]:
        """Score a completed rep from its metric extremes (0-100 + breakdown)."""
        return score_extremes(list(self.scoring_rules), extremes)

    # ----- helpers -------------------------------------------------------- #

    def _accumulate(self, metrics: Dict[str, float]) -> None:
        for key, value in metrics.items():
            slot = self._extremes.get(key)
            if slot is None:
                self._extremes[key] = {"min": value, "max": value}
            else:
                if value < slot["min"]:
                    slot["min"] = value
                if value > slot["max"]:
                    slot["max"] = value

    def _feedback(self, issues: List[FormIssue], completed: bool, primary: float) -> str:
        if issues:
            return issues[0].message
        if completed:
            return f"Rep {self._rep_count} ✓ nice work!"
        if self._state is RepState.DOWN:
            # Once they've risen back past the descent threshold (and clearly off
            # the bottom) but haven't crossed up_enter to complete the rep, switch
            # from the "go down" cue to the "stand all the way up" cue so a
            # partial/half rep gets a nudge to finish. Requiring primary past
            # ``down_enter`` keeps a single jittery frame near the bottom from
            # flipping the cue mid-descent.
            bottom = self._extremes.get(self.primary_metric, {}).get("min", primary)
            if primary > self.down_enter and primary > bottom + 15.0:
                return self.up_cue
            return self.down_cue
        return self.up_cue

    def end_rep_cycle(self) -> None:
        """Abandon any in-flight partial rep at a set boundary.

        Resets the rep state machine and per-rep extremes so the next set starts
        clean, **without** touching ``_rep_count`` (so the running total and the
        count echoed to the client are preserved).
        """
        self._state = RepState.UP
        self._extremes = {}
