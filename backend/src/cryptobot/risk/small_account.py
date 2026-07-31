"""Small-account guardrail mode + deterministic market-wisdom rules (pure).

This is where crypto trading knowledge lives in a form that CANNOT
hallucinate: hard-coded, testable rules derived from well-established market
facts. No language model participates in these decisions.

Each rule states the principle it encodes, so the reasoning is auditable
rather than folklore.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from cryptobot.risk.engine import RiskConfig


# ── 4. small-account guardrail mode ───────────────────────────────────
@dataclass(frozen=True)
class GuardrailResult:
    config: RiskConfig
    min_expected_edge: float          # required edge before costs are cleared
    max_trades_per_day: int
    adjustments: tuple[str, ...] = ()
    rationale: str = ""


def apply_small_account_guardrails(
    base: RiskConfig,
    equity: float,
    round_trip_cost_fraction: float,
    min_notional: float = 5.0,
) -> GuardrailResult:
    """Tighten requirements when costs are large relative to the account.

    Principle: cost drag scales with trade frequency, not account size, so a
    small account must demand a proportionally larger edge and trade less.
    """
    adjustments: list[str] = []
    config = base
    min_edge = round_trip_cost_fraction * 1.5      # 50% margin over costs
    max_trades = base.max_trades_per_day

    if equity < 1000:
        min_edge = round_trip_cost_fraction * 2.5
        max_trades = min(max_trades, 4)
        config = replace(config, max_positions=min(base.max_positions, 2),
                         max_trades_per_day=max_trades)
        adjustments.append(
            "Account under $1,000: required edge raised to 2.5× round-trip costs, "
            "max 4 trades/day, max 2 concurrent positions.")
    elif equity < 5000:
        min_edge = round_trip_cost_fraction * 2.0
        max_trades = min(max_trades, 8)
        config = replace(config, max_trades_per_day=max_trades)
        adjustments.append(
            "Account under $5,000: required edge raised to 2× round-trip costs, "
            "max 8 trades/day.")

    # A position must be large enough to be legal AND small enough to be safe.
    min_position_pct = (min_notional / equity) if equity > 0 else 1.0
    if min_position_pct > base.max_position_pct:
        config = replace(config, max_position_pct=min(0.25, min_position_pct * 1.1))
        adjustments.append(
            f"Max position raised to {config.max_position_pct:.1%} because the exchange "
            f"minimum (${min_notional:,.2f}) exceeds your configured cap — otherwise no "
            "trade could ever be placed. Consider a larger account instead of larger risk.")

    return GuardrailResult(
        config=config, min_expected_edge=round(min_edge, 6),
        max_trades_per_day=max_trades, adjustments=tuple(adjustments),
        rationale=(
            "Costs are fixed percentages; edges are not. The smaller the account, the "
            "higher the bar a trade must clear to be worth taking."
        ),
    )


# ── market-wisdom rules (deterministic, engine-enforced) ──────────────
@dataclass(frozen=True)
class WisdomCheck:
    code: str
    principle: str          # the established market fact being encoded
    passed: bool
    detail: str


@dataclass
class WisdomReport:
    checks: list[WisdomCheck] = field(default_factory=list)

    @property
    def blocking(self) -> list[WisdomCheck]:
        return [c for c in self.checks if not c.passed]

    @property
    def all_passed(self) -> bool:
        return not self.blocking


def evaluate_wisdom_rules(
    *,
    expected_net_return: float | None,
    round_trip_cost_fraction: float,
    stop_distance_pct: float | None,
    take_profit_pct: float | None,
    spread_fraction: float | None,
    quote_volume_24h: float | None,
    hours_since_last_loss_on_pair: float | None,
    position_count: int,
    correlated_position_exists: bool,
    is_averaging_down: bool,
    equity_fraction_at_risk: float,
) -> WisdomReport:
    """Encode durable trading principles as pass/fail gates.

    These complement (never replace) the risk engine. Every rule cites the
    principle it comes from so a user can learn from the rejection.
    """
    report = WisdomReport()
    add = report.checks.append

    add(WisdomCheck(
        "COSTS_FIRST",
        "Transaction costs are certain; profits are not. An edge smaller than costs "
        "is a guaranteed loss repeated many times.",
        expected_net_return is not None and expected_net_return > 0,
        f"expected net {expected_net_return if expected_net_return is not None else 'unknown'} "
        f"vs costs {round_trip_cost_fraction:.4f}",
    ))

    add(WisdomCheck(
        "ASYMMETRIC_PAYOFF",
        "Survivable strategies need reward at least comparable to risk; risking 3 to "
        "make 1 requires a win rate almost no one sustains.",
        stop_distance_pct is None or take_profit_pct is None
        or take_profit_pct >= stop_distance_pct * 0.8,
        f"target {take_profit_pct} vs stop {stop_distance_pct}",
    ))

    add(WisdomCheck(
        "NEVER_AVERAGE_DOWN",
        "Adding to a losing position converts a small planned loss into an unplanned "
        "large one; it is how accounts die even with high win rates.",
        not is_averaging_down,
        "averaging down attempted" if is_averaging_down else "no averaging down",
    ))

    add(WisdomCheck(
        "LIQUIDITY_MATTERS",
        "In thin markets your own order moves the price; illiquidity silently converts "
        "modelled profits into real losses.",
        quote_volume_24h is None or quote_volume_24h >= 10_000_000,
        f"24h quote volume {quote_volume_24h}",
    ))

    add(WisdomCheck(
        "SPREAD_DISCIPLINE",
        "You pay the spread on entry and exit; a wide spread means starting each trade "
        "meaningfully behind.",
        spread_fraction is None or spread_fraction <= 0.002,
        f"spread {spread_fraction}",
    ))

    add(WisdomCheck(
        "COOLDOWN_AFTER_LOSS",
        "Immediately re-entering a pair after a loss is the mechanical signature of "
        "revenge trading, which reliably compounds losses.",
        hours_since_last_loss_on_pair is None or hours_since_last_loss_on_pair >= 1.0,
        f"{hours_since_last_loss_on_pair}h since last loss on this pair",
    ))

    add(WisdomCheck(
        "CORRELATION_IS_CONCENTRATION",
        "Crypto assets are highly correlated with BTC; several 'diversified' positions "
        "are usually one large bet wearing a disguise.",
        not correlated_position_exists,
        "correlated position already open" if correlated_position_exists
        else "no correlated exposure",
    ))

    add(WisdomCheck(
        "SURVIVE_FIRST",
        "Risk of ruin rises non-linearly with position size; risking more than ~2% of "
        "capital per trade makes a normal losing streak fatal.",
        equity_fraction_at_risk <= 0.02,
        f"{equity_fraction_at_risk:.2%} of equity at risk",
    ))

    add(WisdomCheck(
        "POSITION_LIMIT",
        "Every extra simultaneous position multiplies exposure to a single market-wide "
        "shock, which is the dominant risk in crypto.",
        position_count <= 3,
        f"{position_count} open positions",
    ))
    return report
