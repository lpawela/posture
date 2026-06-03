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
    #: landmarks that must be visible for analysis to run
    required_landmarks: Tuple[int, ...] = ()
    #: cues shown live while descending / ascending
    down_cue: str = ""
    up_cue: str = ""
    #: rules used to score each completed rep (see :mod:`app.scoring`)
    scoring_rules: Tuple[ScoringRule, ...] = ()
    #: per-frame "in bounds" ranges driving the live out-of-bounds tint
    live_bounds: Tuple[LiveBound, ...] = ()

    def __init__(self) -> None:
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
        if not self.required_landmarks:
            return True
        return frame.min_visibility(self.required_landmarks) >= MIN_VISIBILITY

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

        metrics = self.compute_metrics(frame)
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
            feedback=self._feedback(issues, completed),
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

    def _feedback(self, issues: List[FormIssue], completed: bool) -> str:
        if issues:
            return issues[0].message
        if completed:
            return f"Rep {self._rep_count} ✓ nice work!"
        if self._state is RepState.DOWN:
            return self.down_cue
        return self.up_cue
