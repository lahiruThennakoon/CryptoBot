"""Cost-effective model routing (pure).

Default to the economical model; escalate to the advanced model only when
measured complexity justifies it. Every choice carries a recorded reason.
Model names come from configuration — never hard-coded at call sites.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_COMPLEX_MARKERS = re.compile(
    r"\b(analy[sz]e|compare|multi|all pairs|portfolio risk|walk.?forward|"
    r"conflicting|investigat|incident|unusual|deep|detailed report|"
    r"end.of.day|explain why.*(reject|fail)|correlat)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RoutingConfig:
    low_cost_model: str = "claude-haiku-4-5-20251001"
    advanced_model: str = "claude-sonnet-5"
    fallback_model: str = "claude-haiku-4-5-20251001"
    escalation_threshold: int = 3
    max_input_tokens: int = 30_000
    max_output_tokens: int = 1_500


@dataclass(frozen=True)
class RoutingDecision:
    model: str
    escalated: bool
    score: int
    reasons: tuple[str, ...]


def route(
    message: str,
    config: RoutingConfig,
    expected_tool_count: int = 0,
    data_rows_estimate: int = 0,
    is_action_request: bool = False,
    budget_exhausted_advanced: bool = False,
) -> RoutingDecision:
    score = 0
    reasons: list[str] = []

    if len(message) > 600:
        score += 1
        reasons.append("long message")
    if _COMPLEX_MARKERS.search(message):
        score += 2
        reasons.append("complex-analysis markers")
    if expected_tool_count >= 3:
        score += 2
        reasons.append(f"{expected_tool_count} tools expected")
    elif expected_tool_count == 2:
        score += 1
        reasons.append("two tools expected")
    if data_rows_estimate > 200:
        score += 2
        reasons.append(f"~{data_rows_estimate} data rows to analyse")
    if is_action_request:
        score += 1
        reasons.append("action request (higher care)")

    if budget_exhausted_advanced:
        return RoutingDecision(
            model=config.low_cost_model, escalated=False, score=score,
            reasons=(*reasons, "advanced budget exhausted → economical model enforced"),
        )
    if score >= config.escalation_threshold:
        return RoutingDecision(
            model=config.advanced_model, escalated=True, score=score,
            reasons=(*reasons, "escalated: complexity above threshold"),
        )
    return RoutingDecision(
        model=config.low_cost_model, escalated=False, score=score,
        reasons=(*reasons, "economical model sufficient") if reasons
        else ("simple request → economical model",),
    )
