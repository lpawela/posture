"""Form scoring: how far a rep is from the ideal execution.

Scoring idea
------------
Each exercise declares a few :class:`ScoringRule` s over the metric *extremes*
captured during a rep (e.g. the *minimum* knee angle = squat depth, the
*maximum* torso lean = how far they folded over). A rep starts at **100** and
loses points the further a metric drifts, in the *bad* direction, past a
tolerance band around its ideal:

    deviation beyond tolerance  ->  penalty = deviation * per_unit_penalty
                                    (clamped to the rule's max_penalty)

The rep score is ``100 - sum(penalties)`` clamped to ``[0, 100]``. Set and
session scores then aggregate rep scores (see :mod:`app.workout`). This makes
"how good was that rep / set / workout" an interpretable distance-from-ideal,
and keeps the whole thing a pure, deterministic function that's easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

HIGHER_IS_WORSE = "higher_is_worse"
LOWER_IS_WORSE = "lower_is_worse"


@dataclass(frozen=True)
class ScoringRule:
    metric: str          # key into the metric extremes, e.g. "knee_angle"
    aggregate: str       # "min" or "max" -- which extreme of the rep to judge
    ideal: float         # the ideal value for that extreme
    direction: str       # HIGHER_IS_WORSE or LOWER_IS_WORSE relative to ideal
    tolerance: float     # free band past `ideal` before any penalty
    per_unit_penalty: float
    max_penalty: float
    label: str = ""


def _bad_amount(value: float, rule: ScoringRule) -> float:
    """How far ``value`` is in the *penalised* direction, past tolerance."""
    deviation = value - rule.ideal
    if rule.direction == HIGHER_IS_WORSE:
        return max(0.0, deviation - rule.tolerance)
    return max(0.0, -deviation - rule.tolerance)


def score_extremes(
    rules: List[ScoringRule], extremes: Dict[str, Dict[str, float]]
) -> Tuple[float, List[dict]]:
    """Score one rep from its metric extremes.

    Returns ``(score, breakdown)`` where ``score`` is in ``[0, 100]`` and
    ``breakdown`` lists each rule's observed value and penalty.
    """
    score = 100.0
    breakdown: List[dict] = []
    for rule in rules:
        slot = extremes.get(rule.metric)
        if not slot or rule.aggregate not in slot:
            continue
        value = slot[rule.aggregate]
        penalty = min(rule.max_penalty, _bad_amount(value, rule) * rule.per_unit_penalty)
        score -= penalty
        breakdown.append(
            {
                "metric": rule.metric,
                "label": rule.label or rule.metric,
                "value": round(value, 1),
                "penalty": round(penalty, 1),
            }
        )
    return max(0.0, min(100.0, score)), breakdown


@dataclass(frozen=True)
class LiveBound:
    """A per-frame "in bounds" range for live form feedback.

    ``good`` is the edge of acceptable form (no warning); ``limit`` is where the
    fault is fully developed (max severity). ``direction`` says which way is bad.
    """

    metric: str
    good: float
    limit: float
    direction: str  # HIGHER_IS_WORSE or LOWER_IS_WORSE


def live_deviation(bounds: List[LiveBound], metrics: Dict[str, float]) -> float:
    """How far out of bounds the *current* frame is, in ``[0, 1]``.

    ``0`` = within ``good`` on every bound; ``1`` = at/beyond ``limit`` on the
    worst bound. Drives the yellow→red video tint.
    """
    worst = 0.0
    for b in bounds:
        value = metrics.get(b.metric)
        if value is None:
            continue
        if b.direction == HIGHER_IS_WORSE:
            excess, span = value - b.good, b.limit - b.good
        else:
            excess, span = b.good - value, b.good - b.limit
        if excess <= 0 or span <= 0:
            continue
        worst = max(worst, min(1.0, excess / span))
    return worst
