"""Near-miss detection — learning feedback without relaxing gates (FR-4.4)."""

from __future__ import annotations

from dataclasses import dataclass

from cryptobot.costs.model import CostModel


@dataclass(frozen=True)
class NearMiss:
    rejection_code: str
    summary: str
    actual: float
    required: float
    gap: float


def required_edge(costs: CostModel) -> float:
    return costs.round_trip_fraction + costs.safety_margin


def near_miss_cost_gate(
    edge: float,
    costs: CostModel,
    margin: float,
) -> NearMiss | None:
    """True when edge fell short of the cost gate by at most `margin` (fraction)."""
    req = required_edge(costs)
    gap = req - edge
    if gap <= 0 or gap > margin:
        return None
    return NearMiss(
        rejection_code="NEAR_MISS_COST_GATE",
        summary=(
            f"Expected edge {edge:.4%} was {gap:.4%} below the required "
            f"{req:.4%} (costs + safety margin)."
        ),
        actual=edge,
        required=req,
        gap=gap,
    )


def near_miss_confidence(
    confidence: float,
    min_confidence: float,
    margin: float,
) -> NearMiss | None:
    gap = min_confidence - confidence
    if gap <= 0 or gap > margin:
        return None
    return NearMiss(
        rejection_code="NEAR_MISS_CONFIDENCE",
        summary=(
            f"Confidence {confidence:.2f} was {gap:.2f} below the required "
            f"{min_confidence:.2f}."
        ),
        actual=confidence,
        required=min_confidence,
        gap=gap,
    )
