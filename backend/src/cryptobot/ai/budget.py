"""AI budget guard (pure): per-request, per-user-day, and monthly caps.

When a limit is reached, only optional AI features degrade — the trading
engine never depends on this module.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BudgetConfig:
    max_cost_per_request_usd: float = 0.10
    max_cost_per_user_day_usd: float = 2.00
    monthly_budget_usd: float = 30.00
    max_requests_per_minute: int = 10
    max_conversation_messages: int = 60
    max_tool_calls_per_request: int = 8


@dataclass
class SpendState:
    today_usd: float = 0.0
    month_usd: float = 0.0
    requests_this_minute: int = 0
    conversation_messages: int = 0


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: str = ""
    advanced_allowed: bool = True    # advanced model may be blocked before all AI


def check(config: BudgetConfig, state: SpendState,
          estimated_request_cost_usd: float = 0.05) -> BudgetDecision:
    if state.requests_this_minute >= config.max_requests_per_minute:
        return BudgetDecision(False, "rate limit: too many AI requests this minute")
    if state.conversation_messages >= config.max_conversation_messages:
        return BudgetDecision(
            False, "conversation length limit reached — start a new chat "
                   "(a summary of this one is retained)")
    if estimated_request_cost_usd > config.max_cost_per_request_usd:
        return BudgetDecision(False, "this request would exceed the per-request cost cap")
    if state.month_usd + estimated_request_cost_usd > config.monthly_budget_usd:
        return BudgetDecision(False, "monthly AI budget reached — AI features paused; "
                                     "trading and reports continue normally")
    if state.today_usd + estimated_request_cost_usd > config.max_cost_per_user_day_usd:
        return BudgetDecision(False, "daily AI budget reached — resets tomorrow; "
                                     "trading continues normally")
    # advanced model gets blocked in the last 20% of either budget
    advanced_ok = (
        state.today_usd < config.max_cost_per_user_day_usd * 0.8
        and state.month_usd < config.monthly_budget_usd * 0.8
    )
    return BudgetDecision(True, advanced_allowed=advanced_ok)
