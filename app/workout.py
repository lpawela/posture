"""Whole-workout monitoring: group reps into sets and roll up scores.

A :class:`WorkoutSession` consumes per-rep form scores (produced by the
analyzers) and tracks how many sets and reps were performed, the score of each
set, and an overall session score. When a prescription is known (e.g. "3 sets
of 12"), sets auto-close at the target rep count and a *completion ratio*
factors missing volume into the overall score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


@dataclass
class WorkoutSummary:
    exercise: str
    total_sets: int
    total_reps: int
    set_scores: List[float]
    form_score: float                 # mean rep score (pure form fidelity)
    completion_ratio: Optional[float]  # reps done / prescribed, capped at 1.0
    overall_score: float               # form_score scaled by completion

    def to_dict(self) -> dict:
        return {
            "exercise": self.exercise,
            "total_sets": self.total_sets,
            "total_reps": self.total_reps,
            "set_scores": self.set_scores,
            "form_score": self.form_score,
            "completion_ratio": self.completion_ratio,
            "overall_score": self.overall_score,
        }


class WorkoutSession:
    """Aggregates reps into sets and computes scores for a whole workout."""

    def __init__(
        self,
        exercise: str,
        target_sets: Optional[int] = None,
        target_reps: Optional[int] = None,
    ) -> None:
        self.exercise = exercise
        self.target_sets = target_sets
        self.target_reps = target_reps
        self._sets: List[List[float]] = []   # closed sets (lists of rep scores)
        self._current: List[float] = []      # the in-progress set

    # ----- recording ----------------------------------------------------- #

    def record_rep(self, score: float) -> None:
        """Add a completed rep's form score to the current set.

        If a per-set target is known and reached, the set auto-closes.
        """
        self._current.append(float(score))
        if self.target_reps and len(self._current) >= self.target_reps:
            self.end_set()

    def end_set(self) -> None:
        """Close the current set (no-op if it's empty)."""
        if self._current:
            self._sets.append(self._current)
            self._current = []

    # ----- live counters -------------------------------------------------- #

    @property
    def completed_sets(self) -> int:
        return len(self._sets)

    @property
    def current_set_reps(self) -> int:
        return len(self._current)

    @property
    def total_reps(self) -> int:
        return sum(len(s) for s in self._sets) + len(self._current)

    # ----- finishing ------------------------------------------------------ #

    def finish(self) -> WorkoutSummary:
        """Close any open set and return the final summary."""
        self.end_set()
        all_scores = [score for s in self._sets for score in s]
        total_reps = len(all_scores)
        total_sets = len(self._sets)
        set_scores = [round(_mean(s), 1) for s in self._sets]
        form_score = round(_mean(all_scores), 1)

        completion: Optional[float] = None
        if self.target_sets and self.target_reps:
            prescribed = self.target_sets * self.target_reps
            completion = round(min(1.0, total_reps / prescribed), 3) if prescribed else None

        if completion is not None:
            overall = round(form_score * (0.5 + 0.5 * completion), 1)
        else:
            overall = form_score

        return WorkoutSummary(
            exercise=self.exercise,
            total_sets=total_sets,
            total_reps=total_reps,
            set_scores=set_scores,
            form_score=form_score,
            completion_ratio=completion,
            overall_score=overall,
        )
