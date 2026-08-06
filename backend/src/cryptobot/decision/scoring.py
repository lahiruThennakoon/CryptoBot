"""Signal-scoring decision engine (pure logic; docs/spec-v2 §6).

Never a single indicator: the score is a weighted combination of strategy
ensemble, trend, momentum, volume, regime fit, ML confidence, order-book
imbalance, and a volatility penalty. Hard gates (data health, spread,
liquidity, cost gate) override any score — a perfect score with a failed
gate is NO_TRADE. The risk engine downstream retains final veto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from cryptobot.costs.model import CostModel
from cryptobot.features.indicators import atr, macd, percentile_rank, rsi, sma
from cryptobot.regime.detector import Regime
from cryptobot.strategies.base import BarLike, Intent, Strategy


class DecisionStatus(str, Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"
    NO_TRADE = "no_trade"
    RISK_BLOCKED = "risk_blocked"
    DATA_UNAVAILABLE = "data_unavailable"


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE = "close"
    NO_TRADE = "no_trade"


# Share of the ensemble weight a lone voter keeps. The remainder is earned by
# additional strategies agreeing, so breadth still raises the score without a
# single confident entry being diluted into irrelevance.
AGREEMENT_FLOOR = 0.6


@dataclass(frozen=True)
class Weights:
    ensemble: float = 0.35
    trend: float = 0.15
    momentum: float = 0.10
    volume: float = 0.10
    regime: float = 0.10
    ml: float = 0.10
    book_imbalance: float = 0.05
    volatility_penalty: float = 0.05


@dataclass(frozen=True)
class Gates:
    max_spread_fraction: float = 0.0015
    min_liquidity_ok: bool = True          # supplied by caller from depth data
    strong_buy_threshold: float = 0.60
    buy_threshold: float = 0.35
    sell_threshold: float = -0.35
    strong_sell_threshold: float = -0.60
    require_strategy_entry: bool = True    # False only in testnet learning mode
    skip_cost_gate: bool = False           # True only in testnet learning mode


@dataclass
class DecisionRecord:
    symbol: str
    action: Action
    status: DecisionStatus
    score: float = 0.0
    confidence: float = 0.0
    supporting: dict[str, float] = field(default_factory=dict)
    conflicting: dict[str, float] = field(default_factory=dict)
    entry_estimate: float | None = None
    stop_price: float | None = None
    take_profit: float | None = None
    expected_holding_bars: int | None = None
    est_fees: float = 0.0
    est_spread: float = 0.0
    est_slippage: float = 0.0
    expected_gross_return: float | None = None
    expected_net_return: float | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class MarketContext:
    """Everything the scorer needs beyond candles (all optional → degrade gracefully)."""

    spread_fraction: float | None = None
    book_imbalance: float | None = None     # (bidVol−askVol)/(bid+askVol), −1..+1
    liquidity_ok: bool = True
    data_fresh: bool = True
    ml_probability_up: float | None = None  # deployed model only
    has_open_position: bool = False


class DecisionScorer:
    def __init__(
        self,
        strategies: list[Strategy],
        costs: CostModel | None = None,
        weights: Weights | None = None,
        gates: Gates | None = None,
    ) -> None:
        self._strategies = strategies
        self._costs = costs or CostModel()
        self.weights = weights or Weights()
        self.gates = gates or Gates()

    def decide(
        self,
        symbol: str,
        bars: list[BarLike],
        regime: Regime,
        context: MarketContext,
    ) -> DecisionRecord:
        record = DecisionRecord(symbol=symbol, action=Action.NO_TRADE,
                                status=DecisionStatus.NO_TRADE)

        # ── hard gate: data health first ─────────────────────────────
        if not context.data_fresh or len(bars) < 60:
            record.status = DecisionStatus.DATA_UNAVAILABLE
            record.reasons.append("Market data is stale or insufficient — no decision made.")
            return record

        closes = [float(b.close) for b in bars]        # type: ignore[arg-type]
        highs = [float(b.high) for b in bars]          # type: ignore[arg-type]
        lows = [float(b.low) for b in bars]            # type: ignore[arg-type]
        volumes = [float(b.volume) for b in bars]      # type: ignore[arg-type]
        i = len(bars) - 1
        price = closes[i]
        w = self.weights

        components: dict[str, float] = {}

        # ── strategy ensemble ────────────────────────────────────────
        entry_votes: list[float] = []
        entry_strategies: list[Strategy] = []
        exit_votes = 0
        stops: list[float] = []
        tps: list[float] = []
        holding: list[int] = []
        for strategy in self._strategies:
            strategy.prepare(bars)
            signal = strategy.on_bar(bars, i)
            if signal.intent is Intent.ENTER_LONG:
                entry_votes.append(signal.confidence)
                entry_strategies.append(strategy)
                if signal.stop_price:
                    stops.append(signal.stop_price)
                if signal.take_profit:
                    tps.append(signal.take_profit)
                holding.append(strategy.spec.max_holding_bars)
            elif signal.intent is Intent.EXIT:
                exit_votes += 1
        n_strats = max(1, len(self._strategies))
        # Average over the strategies that actually voted, then scale by breadth
        # of agreement. Averaging over the whole roster instead would dilute a
        # lone confident entry below every usable threshold, because the
        # strategies are built for deliberately mutually exclusive regimes and
        # can rarely fire together.
        long_vote = 0.0
        if entry_votes:
            agreement = len(entry_votes) / n_strats
            long_vote = (sum(entry_votes) / len(entry_votes)) * (
                AGREEMENT_FLOOR + (1.0 - AGREEMENT_FLOOR) * agreement
            )
        # An EXIT from a strategy holding nothing is an abstention, not a bearish
        # vote: a flat-market strategy reporting "not applicable" must not veto
        # another strategy's entry.
        exit_vote = (exit_votes / n_strats) if context.has_open_position else 0.0
        components["ensemble"] = w.ensemble * (long_vote - exit_vote)

        # ── trend: SMA slope + MACD histogram sign ───────────────────
        trend_ma = sma(closes, 50)
        macd_hist = macd(closes)[2]
        trend_score = 0.0
        if trend_ma[i] is not None and trend_ma[i - 10] is not None and price > 0:
            slope = (trend_ma[i] - trend_ma[i - 10]) / price  # type: ignore[operator]
            trend_score += max(-1.0, min(1.0, slope / 0.01))
        if macd_hist[i] is not None and price > 0:
            trend_score += max(-1.0, min(1.0, (macd_hist[i] / price) / 0.002))  # type: ignore[operator]
        components["trend"] = w.trend * max(-1.0, min(1.0, trend_score / 2))

        # ── momentum: RSI distance from neutral ──────────────────────
        rsi_now = rsi(closes, 14)[i]
        if rsi_now is not None:
            components["momentum"] = w.momentum * max(-1.0, min(1.0, (rsi_now - 50) / 25))

        # ── volume confirmation ──────────────────────────────────────
        vol_ma = sma(volumes, 20)[i]
        if vol_ma:
            components["volume"] = w.volume * max(0.0, min(1.0, volumes[i] / vol_ma - 1.0))

        # ── regime fit (of the strategies that voted to enter) ───────
        # Scoring the whole roster would only measure how many strategies happen
        # to like the current regime — a constant per regime that says nothing
        # about this signal, and that penalises a valid range entry.
        if entry_strategies:
            fits = [
                1.0 if regime in s.spec.allowed_regimes else -1.0
                for s in entry_strategies
            ]
            components["regime"] = w.regime * (sum(fits) / len(fits))

        # ── ML confidence (deployed model only; absent → 0) ──────────
        if context.ml_probability_up is not None:
            components["ml"] = w.ml * max(-1.0, min(1.0, (context.ml_probability_up - 0.5) * 2))

        # ── order-book imbalance ─────────────────────────────────────
        if context.book_imbalance is not None:
            components["book_imbalance"] = w.book_imbalance * max(-1.0, min(1.0, context.book_imbalance))

        # ── volatility penalty ───────────────────────────────────────
        atr_vals = atr(highs, lows, closes, 14)
        atr_norm = [(a / closes[k]) if a is not None and closes[k] > 0 else None
                    for k, a in enumerate(atr_vals)]
        vol_rank = percentile_rank(atr_norm, i, 200)
        if vol_rank is not None and vol_rank > 0.8:
            components["volatility_penalty"] = -w.volatility_penalty * (vol_rank - 0.8) / 0.2

        score = sum(components.values())
        record.score = round(score, 4)
        # Conviction of the voting strategies — deliberately independent of the
        # score. Deriving it from |score| turned the risk engine's
        # min_confidence into a second, stricter score threshold that silently
        # overrode buy_threshold, so loosening the gates had no effect.
        record.confidence = round(
            (sum(entry_votes) / len(entry_votes)) if entry_votes else min(1.0, abs(score)),
            4,
        )
        record.supporting = {k: round(v, 4) for k, v in components.items() if v > 0}
        record.conflicting = {k: round(v, 4) for k, v in components.items() if v < 0}

        # ── economics of a hypothetical entry ────────────────────────
        atr_now = atr_vals[i]
        stop = (sum(stops) / len(stops)) if stops else (
            price - 2 * atr_now if atr_now else None)
        tp = (sum(tps) / len(tps)) if tps else (
            price + 3 * atr_now if atr_now else None)
        spread = context.spread_fraction if context.spread_fraction is not None else self._costs.half_spread * 2
        record.entry_estimate = self._costs.buy_fill_price(price)
        record.stop_price = stop
        record.take_profit = tp
        record.expected_holding_bars = int(sum(holding) / len(holding)) if holding else None
        record.est_fees = self._costs.taker_fee * 2
        record.est_spread = spread
        record.est_slippage = self._costs.slippage * 2
        if tp and price > 0:
            record.expected_gross_return = tp / price - 1
            record.expected_net_return = record.expected_gross_return - self._costs.round_trip_fraction

        # ── map score → status/action, then apply hard gates ─────────
        g = self.gates
        if score >= g.strong_buy_threshold:
            record.status, record.action = DecisionStatus.STRONG_BUY, Action.BUY
        elif score >= g.buy_threshold:
            record.status, record.action = DecisionStatus.BUY, Action.BUY
        elif score <= g.strong_sell_threshold:
            record.status = DecisionStatus.STRONG_SELL
            record.action = Action.CLOSE if context.has_open_position else Action.NO_TRADE
        elif score <= g.sell_threshold:
            record.status = DecisionStatus.SELL
            record.action = Action.CLOSE if context.has_open_position else Action.NO_TRADE
        else:
            record.status, record.action = DecisionStatus.HOLD, Action.HOLD
            record.reasons.append("Signals are mixed or weak — holding costs nothing.")

        if record.action is Action.BUY:
            record.reasons.append(
                f"{len(entry_votes)} strateg{'ies' if len(entry_votes) != 1 else 'y'} "
                f"support entry; combined score {score:+.2f}."
            )
            if spread is not None and spread > g.max_spread_fraction:
                record.action, record.status = Action.NO_TRADE, DecisionStatus.NO_TRADE
                record.reasons.append(
                    f"Rejected: spread {spread*100:.2f}% exceeds the "
                    f"{g.max_spread_fraction*100:.2f}% limit.")
            elif not context.liquidity_ok:
                record.action, record.status = Action.NO_TRADE, DecisionStatus.NO_TRADE
                record.reasons.append("Rejected: order-book depth too thin for a safe fill.")
            elif (
                not g.skip_cost_gate
                and record.expected_net_return is not None
                and not self._costs.passes_cost_gate(record.expected_gross_return or 0.0)
            ):
                record.action, record.status = Action.NO_TRADE, DecisionStatus.NO_TRADE
                record.reasons.append(
                    "Rejected: expected profit does not clear costs plus the safety margin.")
            elif g.require_strategy_entry and not entry_votes:
                record.action, record.status = Action.NO_TRADE, DecisionStatus.NO_TRADE
                record.reasons.append(
                    "Rejected: score is positive but no strategy independently "
                    "confirms an entry — indicators alone are not a trade.")
        return record
