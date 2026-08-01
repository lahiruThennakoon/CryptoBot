"""Cost microscope — makes small-account arithmetic visible (pure).

For a small account, transaction costs and exchange minimums decide the
outcome more than any signal does. This module turns abstract fee rates into
the numbers that actually matter: dollars per round trip, the price move
required to break even, how much a given trade frequency costs per day and
per month, and what maker orders would save.

Nothing here is a projection or a promise. Every figure is arithmetic on
current costs and the user's own account size.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CostInputs:
    equity: float
    price: float
    taker_fee: float = 0.001
    maker_fee: float = 0.001
    spread_fraction: float = 0.0003     # observed half-spread ×2 at entry+exit
    slippage_fraction: float = 0.0005
    min_notional: float = 5.0
    step_size: float = 1e-5
    position_pct: float = 0.05          # notional as fraction of equity
    trades_per_day: float = 3.0
    bnb_discount: float = 0.0           # 0.25 when paying fees in BNB


@dataclass
class CostReport:
    position_notional: float
    round_trip_cost_usd: float
    round_trip_cost_pct_of_position: float
    round_trip_cost_pct_of_equity: float
    breakeven_move_pct: float           # price move needed just to cover costs
    daily_cost_usd: float
    daily_cost_pct_of_equity: float
    monthly_cost_pct_of_equity: float
    trades_until_10pct_of_equity_spent: float
    smallest_valid_notional: float
    smallest_trade_cost_pct: float      # cost of the minimum trade vs equity
    maker_round_trip_cost_usd: float
    maker_saving_usd_per_trade: float
    maker_saving_pct_per_month: float
    warnings: list[str] = field(default_factory=list)
    plain_summary: str = ""


def _round_down(value: float, step: float) -> float:
    if step <= 0:
        return value
    return value - (value % step)


def analyse_costs(inputs: CostInputs) -> CostReport:
    i = inputs
    taker = i.taker_fee * (1 - i.bnb_discount)
    maker = i.maker_fee * (1 - i.bnb_discount)

    notional = max(0.0, i.equity * i.position_pct)
    qty = _round_down(notional / i.price, i.step_size) if i.price > 0 else 0.0
    notional = qty * i.price

    # taker round trip: fees both sides + full spread + slippage both sides
    taker_fraction = 2 * taker + i.spread_fraction + 2 * i.slippage_fraction
    # maker round trip: maker fees, no spread crossing, no slippage on fills
    maker_fraction = 2 * maker

    cost = notional * taker_fraction
    maker_cost = notional * maker_fraction
    daily = cost * i.trades_per_day

    report = CostReport(
        position_notional=round(notional, 2),
        round_trip_cost_usd=round(cost, 4),
        round_trip_cost_pct_of_position=round(taker_fraction * 100, 4),
        round_trip_cost_pct_of_equity=round(
            (cost / i.equity * 100) if i.equity > 0 else 0.0, 4),
        breakeven_move_pct=round(taker_fraction * 100, 4),
        daily_cost_usd=round(daily, 4),
        daily_cost_pct_of_equity=round((daily / i.equity * 100) if i.equity > 0 else 0.0, 3),
        monthly_cost_pct_of_equity=round(
            (daily * 30 / i.equity * 100) if i.equity > 0 else 0.0, 2),
        trades_until_10pct_of_equity_spent=round(
            (i.equity * 0.10 / cost) if cost > 0 else 0.0, 1),
        smallest_valid_notional=round(i.min_notional, 2),
        smallest_trade_cost_pct=round(
            (i.min_notional * taker_fraction / i.equity * 100) if i.equity > 0 else 0.0, 4),
        maker_round_trip_cost_usd=round(maker_cost, 4),
        maker_saving_usd_per_trade=round(cost - maker_cost, 4),
        maker_saving_pct_per_month=round(
            ((cost - maker_cost) * i.trades_per_day * 30 / i.equity * 100)
            if i.equity > 0 else 0.0, 2),
    )

    if notional < i.min_notional:
        report.warnings.append(
            f"At {i.position_pct:.1%} of a ${i.equity:,.0f} account, a position is "
            f"${notional:,.2f} — below the exchange minimum of ${i.min_notional:,.2f}. "
            "The bot cannot place this trade at all."
        )
    if report.monthly_cost_pct_of_equity >= 5:
        report.warnings.append(
            f"At {i.trades_per_day:g} trades/day these costs alone consume "
            f"{report.monthly_cost_pct_of_equity:.0f}% of your account per month. "
            "Very few strategies out-earn that; fewer trades is usually better."
        )
    elif i.trades_per_day >= 8:
        report.warnings.append(
            f"At {i.trades_per_day:g} trades/day, fees and spreads add up to roughly "
            f"{report.monthly_cost_pct_of_equity:.1f}% of your account per month. "
            "Fewer, higher-conviction trades usually survive costs better."
        )
    if report.breakeven_move_pct >= 0.5:
        report.warnings.append(
            f"Each trade must move {report.breakeven_move_pct:.2f}% in your favour "
            "just to break even — before any profit."
        )
    if i.equity < 500:
        report.warnings.append(
            "Small accounts are hit hardest: exchange minimums force larger "
            "relative position sizes, and fixed costs are a bigger share of equity. "
            "Treat this as a learning laboratory before risking money you need."
        )

    report.plain_summary = (
        f"On a ${i.equity:,.0f} account, one round trip of ${notional:,.2f} costs about "
        f"${cost:,.2f} ({report.round_trip_cost_pct_of_equity:.2f}% of your equity). "
        f"The price must move {report.breakeven_move_pct:.2f}% in your favour before you "
        f"make anything. At {i.trades_per_day:g} trades a day that is "
        f"${daily:,.2f}/day, roughly {report.monthly_cost_pct_of_equity:.1f}% of the "
        f"account per month in costs. Using resting limit (maker) orders instead of "
        f"market orders would save about ${report.maker_saving_usd_per_trade:,.2f} per "
        f"trade — {report.maker_saving_pct_per_month:.1f}% of the account per month."
    )
    return report


# ── sizing feasibility ────────────────────────────────────────────────
@dataclass(frozen=True)
class SizingInputs:
    equity: float
    price: float
    risk_per_trade: float = 0.005       # fraction of equity risked to the stop
    stop_distance_pct: float = 0.03     # stop distance as fraction of price
    max_position_pct: float = 0.05
    min_notional: float = 5.0
    min_qty: float = 1e-5
    step_size: float = 1e-5


@dataclass
class SizingReport:
    quantity: float
    notional: float
    risk_amount_usd: float
    feasible: bool
    blocking_reason: str = ""
    min_equity_for_current_settings: float | None = None
    workable_risk_per_trade: float | None = None
    max_simultaneous_positions: int = 0
    notes: list[str] = field(default_factory=list)


def check_sizing(inputs: SizingInputs) -> SizingReport:
    """Detects the silent failure mode: settings so conservative that no
    valid order can ever be placed, so the bot never trades and never says why."""
    s = inputs
    if s.price <= 0 or s.equity <= 0 or s.stop_distance_pct <= 0:
        return SizingReport(0, 0, 0, False, "equity, price and stop distance must be positive")

    risk_amount = s.equity * s.risk_per_trade
    stop_distance_price = s.price * s.stop_distance_pct
    qty = risk_amount / stop_distance_price
    qty = min(qty, s.equity * s.max_position_pct / s.price)   # position cap
    qty = _round_down(qty, s.step_size)
    notional = qty * s.price

    # how many positions of this size the account can actually fund
    fundable = int(s.equity // notional) if notional > 0 else 0
    report = SizingReport(
        quantity=qty, notional=round(notional, 2),
        risk_amount_usd=round(risk_amount, 2), feasible=True,
        max_simultaneous_positions=fundable,
    )

    # equity needed so that the risk-based size clears min notional
    risk_based_notional_per_dollar = s.risk_per_trade / s.stop_distance_pct
    if risk_based_notional_per_dollar > 0:
        report.min_equity_for_current_settings = round(
            s.min_notional / risk_based_notional_per_dollar, 2)
    if s.equity > 0:
        needed = s.min_notional * s.stop_distance_pct / s.equity
        report.workable_risk_per_trade = round(min(0.02, max(needed, 0.0)), 5)

    if qty < s.min_qty or qty <= 0:
        report.feasible = False
        report.blocking_reason = (
            f"Position size rounds to {qty:g} — below the exchange minimum quantity."
        )
    elif notional < s.min_notional:
        report.feasible = False
        report.blocking_reason = (
            f"Position would be ${notional:,.2f}, under the exchange minimum of "
            f"${s.min_notional:,.2f}. With these settings the bot can never trade "
            f"this pair: you would need about ${report.min_equity_for_current_settings:,.0f} "
            f"equity, or a risk-per-trade of about "
            f"{(report.workable_risk_per_trade or 0)*100:.2f}%."
        )

    if report.feasible:
        report.notes.append(
            f"Risking ${risk_amount:,.2f} ({s.risk_per_trade:.2%}) with a "
            f"{s.stop_distance_pct:.1%} stop gives a ${notional:,.2f} position."
        )
        if notional / s.equity > s.max_position_pct + 1e-9:
            report.notes.append("Position capped by your max-position limit.")
    return report
