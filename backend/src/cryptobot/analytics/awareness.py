"""Awareness analytics (pure): the numbers that keep a small account honest.

Features 5-8 of the small-account plan:
- drawdown recovery asymmetry (-20% needs +25%)
- honest growth expectations as a RANGE with a bad tail, never a projection line
- paper-vs-real execution divergence (is the cost model optimistic?)
- behavioural guardrails (risk-loosening pattern detection)

Nothing here forecasts prices. Every output is arithmetic or a statistical
range derived from the user's own realised results, with uncertainty stated.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime


# ── 5. drawdown recovery math ─────────────────────────────────────────
@dataclass(frozen=True)
class RecoveryMath:
    drawdown_pct: float
    gain_needed_pct: float
    trades_needed_at_expectancy: float | None
    message: str


def recovery_math(peak_equity: float, current_equity: float,
                  expectancy_pct_per_trade: float | None = None) -> RecoveryMath:
    if peak_equity <= 0 or current_equity <= 0 or current_equity >= peak_equity:
        return RecoveryMath(0.0, 0.0, None,
                            "At or above your high-water mark — no recovery needed.")
    dd = (peak_equity - current_equity) / peak_equity
    gain_needed = peak_equity / current_equity - 1
    trades = None
    if expectancy_pct_per_trade and expectancy_pct_per_trade > 0:
        trades = round(math.log(1 + gain_needed) / math.log(1 + expectancy_pct_per_trade), 1)
    message = (
        f"You are {dd*100:.1f}% below your peak, which needs a {gain_needed*100:.1f}% "
        "gain to recover — losses always demand a larger percentage back than they took. "
        "This is why the system protects capital before chasing returns; it is NOT a "
        "reason to increase risk, which is how a drawdown becomes a wipe-out."
    )
    if trades:
        message += f" At your measured expectancy that is roughly {trades:g} winning-average trades."
    return RecoveryMath(round(dd * 100, 2), round(gain_needed * 100, 2), trades, message)


# ── 6. honest growth expectations (range, not a promise) ──────────────
@dataclass
class GrowthOutlook:
    trades_sampled: int
    expectancy_pct: float | None
    win_rate_pct: float | None
    statistically_meaningful: bool
    p10_equity: float | None = None
    p50_equity: float | None = None
    p90_equity: float | None = None
    worst_case_equity: float | None = None
    prob_below_start: float | None = None
    caveats: list[str] = field(default_factory=list)
    message: str = ""


def growth_outlook(
    trade_returns_pct: list[float],
    equity: float,
    horizon_trades: int = 100,
    simulations: int = 2000,
    seed: int = 7,
) -> GrowthOutlook:
    """Bootstrap the user's OWN realised trade returns forward.

    This is a distribution of what past results imply, not a forecast: it
    assumes the future resembles a small sample, which is exactly the
    assumption that breaks in real markets.
    """
    n = len(trade_returns_pct)
    if n == 0:
        return GrowthOutlook(0, None, None, False,
                             caveats=["No closed trades yet — nothing to extrapolate from."],
                             message="No trading history yet. Any projection would be fiction.")
    expectancy = sum(trade_returns_pct) / n
    wins = sum(1 for r in trade_returns_pct if r > 0)
    meaningful = n >= 30

    rng = random.Random(seed)
    finals: list[float] = []
    for _ in range(simulations):
        eq = equity
        for _ in range(horizon_trades):
            eq *= 1 + rng.choice(trade_returns_pct) / 100
            if eq <= 0:
                eq = 0.0
                break
        finals.append(eq)
    finals.sort()

    def pct(p: float) -> float:
        return round(finals[min(len(finals) - 1, int(p * len(finals)))], 2)

    outlook = GrowthOutlook(
        trades_sampled=n,
        expectancy_pct=round(expectancy, 4),
        win_rate_pct=round(100 * wins / n, 1),
        statistically_meaningful=meaningful,
        p10_equity=pct(0.10), p50_equity=pct(0.50), p90_equity=pct(0.90),
        worst_case_equity=round(finals[0], 2),
        prob_below_start=round(100 * sum(1 for f in finals if f < equity) / len(finals), 1),
    )
    if not meaningful:
        outlook.caveats.append(
            f"Only {n} closed trades — far too few to estimate an edge. Luck dominates "
            "this sample; treat the range below as illustration, not evidence.")
    if expectancy <= 0:
        outlook.caveats.append(
            "Measured expectancy is zero or negative: on this evidence the strategy "
            "loses money after costs, and compounding a negative edge destroys capital.")
    outlook.caveats.append(
        "This resamples your own past trades. Real markets change regime; the true "
        "bad tail is worse than any bootstrap suggests.")
    outlook.message = (
        f"Over the next {horizon_trades} trades, resampling your {n} realised trades gives "
        f"a middle outcome around {outlook.p50_equity:,.0f} (from {equity:,.0f}), with "
        f"a poor case near {outlook.p10_equity:,.0f} and a good case near "
        f"{outlook.p90_equity:,.0f}. About {outlook.prob_below_start:.0f}% of simulated "
        "paths finish below where you started. No outcome here is promised."
    )
    return outlook


# ── 7. paper-vs-real execution divergence ─────────────────────────────
@dataclass
class DivergenceReport:
    samples: int
    assumed_cost_pct: float
    observed_cost_pct: float | None
    ratio: float | None
    verdict: str
    message: str


def execution_divergence(
    assumed_round_trip_fraction: float,
    observed_slippage_fractions: list[float],
) -> DivergenceReport:
    """Compare modelled costs against what fills actually cost.

    If reality is materially worse than the model, every backtest and paper
    result is optimistic — and you want to learn that before risking money.
    """
    n = len(observed_slippage_fractions)
    if n < 5:
        return DivergenceReport(
            n, round(assumed_round_trip_fraction * 100, 4), None, None, "insufficient_data",
            f"Only {n} fills recorded — need at least 5 to compare modelled vs actual costs.")
    observed = sum(observed_slippage_fractions) / n
    ratio = observed / assumed_round_trip_fraction if assumed_round_trip_fraction > 0 else None
    if ratio is None:
        verdict, note = "unknown", "No cost assumption to compare against."
    elif ratio <= 1.1:
        verdict = "model_realistic"
        note = "Actual execution costs match the model — backtest and paper results are trustworthy on this axis."
    elif ratio <= 1.5:
        verdict = "model_slightly_optimistic"
        note = "Actual costs run somewhat above the model; shade expectations down accordingly."
    else:
        verdict = "model_optimistic"
        note = ("Actual costs are far above the model. Treat every backtest and paper "
                "result as optimistic until the cost model is raised to match reality.")
    return DivergenceReport(
        n, round(assumed_round_trip_fraction * 100, 4), round(observed * 100, 4),
        round(ratio, 2) if ratio else None, verdict,
        f"Modelled {assumed_round_trip_fraction*100:.3f}% vs observed "
        f"{observed*100:.3f}% per trade over {n} fills. {note}")


# ── 8. behavioural guardrails ─────────────────────────────────────────
@dataclass
class BehaviourFlag:
    code: str
    severity: str          # info | warning
    message: str


def behaviour_flags(
    config_changes: list[tuple[datetime, str, str]],   # (when, setting, direction)
    consecutive_losses: int = 0,
    trades_today: int = 0,
    max_trades_per_day: int = 12,
    changes_window_days: int = 7,
) -> list[BehaviourFlag]:
    """Detect the patterns that precede blown accounts. Advisory only — these
    never change trading behaviour by themselves (the risk engine does that)."""
    flags: list[BehaviourFlag] = []
    loosenings = [c for c in config_changes if c[2] == "loosened"]
    if len(loosenings) >= 3:
        flags.append(BehaviourFlag(
            "FREQUENT_LOOSENING", "warning",
            f"You have loosened risk limits {len(loosenings)} times in the last "
            f"{changes_window_days} days. This pattern — raising risk after "
            "disappointing results — is the most common path to a large loss."))
    if consecutive_losses >= 3 and loosenings:
        flags.append(BehaviourFlag(
            "LOOSENING_AFTER_LOSSES", "warning",
            "Risk limits were loosened during a losing streak. Consider waiting for "
            "the streak to end before changing anything; the system is designed to "
            "survive streaks, not to win them back quickly."))
    if trades_today >= max_trades_per_day * 0.8:
        flags.append(BehaviourFlag(
            "HIGH_ACTIVITY", "info",
            f"{trades_today} trades today, near your {max_trades_per_day} limit. "
            "Each trade pays costs; frequency is rarely where an edge comes from."))
    if not flags:
        flags.append(BehaviourFlag(
            "STEADY", "info",
            "No concerning patterns: settings stable and activity within limits. "
            "Boring is the correct feeling here."))
    return flags
