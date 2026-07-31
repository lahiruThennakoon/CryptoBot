"""Pair screener: which pairs THIS account can actually trade, ranked by suitability.

What this does and does not claim
--------------------------------
It CANNOT rank pairs by future profit — nothing can. What it ranks is
*suitability*, which is knowable today:

  1. Affordability — can this equity place a valid, safely-sized order at all?
  2. Tradability   — is the pair's typical move large relative to what it costs
                     to trade? (the single most decisive ratio for small accounts)
  3. Liquidity     — can the book absorb our size without eating the edge?
  4. Spread        — how far behind does every round trip start?
  5. Evidence      — does a backtest on THIS pair show positive expectancy
                     after costs? (absent evidence scores neutral, never good)
  6. Diversification — does it add exposure, or duplicate a correlated bet?

Every score component is arithmetic on observable data, and every exclusion
carries a plain-language reason. The AI assistant may explain this ranking;
it never produces or alters it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Weights sum to 1.0. Tradability and evidence dominate because they are the
# two factors that actually decide whether trading a pair can work.
W_TRADABILITY = 0.30
W_EVIDENCE = 0.25
W_LIQUIDITY = 0.20
W_DIVERSIFICATION = 0.15
W_SPREAD = 0.10

# A pair's typical bar move should be several multiples of the round-trip cost
# before trading it is even arithmetically sensible.
TARGET_MOVE_TO_COST_RATIO = 4.0


@dataclass
class ScreenInput:
    symbol: str
    base_asset: str
    quote_asset: str
    selectable: bool                       # from the catalog (status/quote checks)
    not_selectable_reason: str = ""
    price: float = 0.0
    atr_pct: float | None = None           # typical bar move as % of price
    quote_volume_24h: float = 0.0
    spread_fraction: float = 0.0
    round_trip_cost_fraction: float = 0.004
    min_notional: float = 5.0
    step_size: float = 1e-5
    # affordability inputs
    equity: float = 0.0
    risk_per_trade: float = 0.005
    stop_distance_pct: float = 0.03
    max_position_pct: float = 0.05
    # evidence + portfolio context
    backtest_expectancy_pct: float | None = None    # per-trade, after costs
    backtest_trades: int = 0
    max_correlation_with_enabled: float | None = None
    candles_available: int = 0
    candles_required: int = 500
    already_enabled: bool = False


@dataclass
class ScreenResult:
    symbol: str
    suitable: bool
    score: float
    affordable: bool
    components: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    position_notional: float = 0.0
    move_to_cost_ratio: float | None = None
    already_enabled: bool = False

    @property
    def headline(self) -> str:
        if not self.suitable:
            return self.blockers[0] if self.blockers else "not suitable"
        band = ("strong fit" if self.score >= 0.7 else
                "workable" if self.score >= 0.5 else "marginal")
        return f"{band} (score {self.score:.2f})"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def screen_pair(data: ScreenInput) -> ScreenResult:
    result = ScreenResult(symbol=data.symbol, suitable=True, score=0.0,
                          affordable=True, already_enabled=data.already_enabled)

    # ── hard gates ───────────────────────────────────────────────────
    if not data.selectable:
        result.suitable = False
        result.blockers.append(data.not_selectable_reason or "not tradable on this venue")
        return result
    if data.price <= 0 or data.equity <= 0:
        result.suitable = False
        result.blockers.append("no live price or account equity available")
        return result

    # affordability: risk-based size must clear the exchange minimum
    risk_amount = data.equity * data.risk_per_trade
    qty = risk_amount / (data.price * data.stop_distance_pct)
    qty = min(qty, data.equity * data.max_position_pct / data.price)
    if data.step_size > 0:
        qty -= qty % data.step_size
    notional = qty * data.price
    result.position_notional = round(notional, 2)
    if notional < data.min_notional:
        result.suitable = False
        result.affordable = False
        result.blockers.append(
            f"unaffordable: a safely-sized position is ${notional:,.2f}, below the "
            f"${data.min_notional:,.2f} exchange minimum for {data.symbol}. Your equity "
            "would have to take more risk than allowed to trade this pair."
        )
        return result

    if data.candles_available < data.candles_required:
        result.suitable = False
        result.blockers.append(
            f"insufficient history: {data.candles_available} candles stored, "
            f"{data.candles_required} needed before any strategy can be evaluated. "
            f"Run: cryptobot import-history --symbol {data.symbol}"
        )
        return result

    # ── scored components ────────────────────────────────────────────
    cost = max(data.round_trip_cost_fraction, 1e-9)

    if data.atr_pct is not None and data.atr_pct > 0:
        ratio = (data.atr_pct / 100) / cost
        result.move_to_cost_ratio = round(ratio, 2)
        tradability = _clamp(ratio / TARGET_MOVE_TO_COST_RATIO)
        if ratio < 1.5:
            result.blockers.append(
                f"typical move ({data.atr_pct:.2f}%) is only {ratio:.1f}x the round-trip "
                f"cost ({cost*100:.2f}%) — the price barely moves enough to pay for the trade"
            )
            result.suitable = False
        elif ratio < TARGET_MOVE_TO_COST_RATIO:
            result.reasons.append(
                f"moves {ratio:.1f}x its trading cost — thin margin; prefer pairs above "
                f"{TARGET_MOVE_TO_COST_RATIO:.0f}x")
        else:
            result.reasons.append(
                f"typical move is {ratio:.1f}x the cost of trading it — healthy headroom")
    else:
        tradability = 0.4
        result.reasons.append("volatility unknown — scored neutrally, not favourably")
    result.components["tradability"] = round(tradability, 3)

    liquidity = _clamp(data.quote_volume_24h / 500_000_000)
    result.components["liquidity"] = round(liquidity, 3)
    if data.quote_volume_24h < 50_000_000:
        result.reasons.append(
            f"low liquidity (${data.quote_volume_24h/1e6:.0f}M/24h) — expect worse fills")
    else:
        result.reasons.append(f"liquid (${data.quote_volume_24h/1e6:.0f}M/24h)")

    spread_score = _clamp(1 - (data.spread_fraction / 0.002))
    result.components["spread"] = round(spread_score, 3)

    if data.backtest_trades >= 20 and data.backtest_expectancy_pct is not None:
        evidence = _clamp(0.5 + data.backtest_expectancy_pct * 25)
        verdict = ("positive" if data.backtest_expectancy_pct > 0 else "negative")
        result.reasons.append(
            f"backtest evidence: {verdict} expectancy "
            f"({data.backtest_expectancy_pct:+.3f}%/trade over {data.backtest_trades} trades)")
        if data.backtest_expectancy_pct <= 0:
            result.reasons.append(
                "on this evidence the strategies lose money here after costs")
    else:
        evidence = 0.5
        result.reasons.append(
            f"no backtest evidence yet ({data.backtest_trades} trades) — scored neutral. "
            "Test it in the Strategy lab before trusting it.")
    result.components["evidence"] = round(evidence, 3)

    if data.max_correlation_with_enabled is None:
        diversification = 0.7
    else:
        diversification = _clamp(1 - data.max_correlation_with_enabled)
        if data.max_correlation_with_enabled > 0.8:
            result.reasons.append(
                f"moves almost identically to a pair you already trade "
                f"(correlation {data.max_correlation_with_enabled:.2f}) — adding it doubles "
                "the same bet rather than diversifying")
    result.components["diversification"] = round(diversification, 3)

    result.score = round(
        tradability * W_TRADABILITY
        + evidence * W_EVIDENCE
        + liquidity * W_LIQUIDITY
        + diversification * W_DIVERSIFICATION
        + spread_score * W_SPREAD,
        4,
    )
    if not result.suitable:
        result.score = 0.0
    return result


def rank_pairs(inputs: list[ScreenInput], top_n: int = 10) -> list[ScreenResult]:
    """Deterministic ranking: score desc, then symbol for stable ties."""
    results = [screen_pair(i) for i in inputs]
    suitable = [r for r in results if r.suitable]
    unsuitable = [r for r in results if not r.suitable]
    suitable.sort(key=lambda r: (-r.score, r.symbol))
    unsuitable.sort(key=lambda r: r.symbol)
    return suitable[:top_n] + unsuitable[: max(0, top_n - len(suitable))]


def portfolio_advice(results: list[ScreenResult], equity: float,
                     max_pairs: int) -> str:
    """One honest paragraph about what this account should realistically trade."""
    suitable = [r for r in results if r.suitable]
    if not suitable:
        return (
            "No pair currently passes screening for this account. That is a real "
            "answer, not a failure: with this equity, exchange minimums and trading "
            "costs, there is no pair where a safely-sized trade has room to pay for "
            "itself. Growing the account or waiting for higher volatility changes "
            "this; taking more risk does not."
        )
    best = suitable[0]
    count = min(max_pairs, len(suitable))
    return (
        f"{len(suitable)} pair(s) pass screening. On ${equity:,.0f} the arithmetic "
        f"favours concentrating on {count} at most — every extra pair splits attention "
        f"and adds correlated exposure without adding edge. Highest-suitability today: "
        f"{best.symbol} ({best.headline}). Suitability means 'can be traded sensibly', "
        f"NOT 'will be profitable' — that is decided by evidence in the Strategy lab and "
        f"90 days of paper trading, never by a screener."
    )
