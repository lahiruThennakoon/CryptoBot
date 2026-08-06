import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptobot.decision.ranking import rank_opportunities, returns_correlation
from cryptobot.decision.scoring import (
    AGREEMENT_FLOOR,
    Action,
    DecisionRecord,
    DecisionScorer,
    DecisionStatus,
    Gates,
    MarketContext,
)
from cryptobot.regime.detector import Regime
from cryptobot.strategies.base import HOLD, Intent, Signal, Strategy, StrategySpec


@dataclass(frozen=True)
class Bar:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def trending_bars(n=300, seed=2, drift=0.002):
    rng = random.Random(seed)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    p, out = 100.0, []
    for i in range(n):
        c = max(0.01, p * (1 + rng.gauss(drift, 0.004)))
        out.append(Bar(t0 + timedelta(hours=i), p, max(p, c) * 1.001,
                       min(p, c) * 0.999, c, 100 + i % 40))
        p = c
    return out


class AlwaysEnter(Strategy):
    def __init__(self):
        self.spec = StrategySpec(name="always", timeframe="1h", warmup_bars=5,
                                 max_holding_bars=24, cooldown_bars=0,
                                 allowed_regimes=frozenset(Regime))

    def on_bar(self, bars, i):
        price = float(bars[i].close)
        return Signal(Intent.ENTER_LONG, confidence=0.9,
                      stop_price=price * 0.95, take_profit=price * 1.10)


class NeverEnter(Strategy):
    def __init__(self):
        self.spec = StrategySpec(name="never", timeframe="1h", warmup_bars=5,
                                 max_holding_bars=24, cooldown_bars=0,
                                 allowed_regimes=frozenset(Regime))

    def on_bar(self, bars, i):
        return HOLD


class AlwaysExit(Strategy):
    def __init__(self):
        self.spec = StrategySpec(name="exiter", timeframe="1h", warmup_bars=5,
                                 max_holding_bars=24, cooldown_bars=0,
                                 allowed_regimes=frozenset(Regime))

    def on_bar(self, bars, i):
        return Signal(Intent.EXIT, confidence=1.0, reason="not applicable")


class RegimeEnter(Strategy):
    """Enters at a fixed confidence, restricted to the given regimes."""

    def __init__(self, name, regimes, confidence=0.8):
        self._confidence = confidence
        self.spec = StrategySpec(name=name, timeframe="1h", warmup_bars=5,
                                 max_holding_bars=24, cooldown_bars=0,
                                 allowed_regimes=frozenset(regimes))

    def on_bar(self, bars, i):
        price = float(bars[i].close)
        return Signal(Intent.ENTER_LONG, confidence=self._confidence,
                      stop_price=price * 0.95, take_profit=price * 1.10)


class RegimeHold(Strategy):
    """Never votes, but declares regime preferences the scorer must ignore."""

    def __init__(self, name, regimes):
        self.spec = StrategySpec(name=name, timeframe="1h", warmup_bars=5,
                                 max_holding_bars=24, cooldown_bars=0,
                                 allowed_regimes=frozenset(regimes))

    def on_bar(self, bars, i):
        return HOLD


class TestScorer:
    def test_stale_data_wins_over_everything(self):
        scorer = DecisionScorer([AlwaysEnter()])
        record = scorer.decide("BTCUSDT", trending_bars(), Regime.TREND_UP,
                               MarketContext(data_fresh=False))
        assert record.status is DecisionStatus.DATA_UNAVAILABLE
        assert record.action is Action.NO_TRADE

    def test_no_strategy_confirmation_blocks_buy(self):
        """Positive indicator score without a strategy vote must not trade."""
        scorer = DecisionScorer([NeverEnter()])
        record = scorer.decide("BTCUSDT", trending_bars(), Regime.TREND_UP, MarketContext())
        assert record.action is not Action.BUY

    def test_wide_spread_gate_beats_score(self):
        scorer = DecisionScorer([AlwaysEnter()])
        record = scorer.decide("BTCUSDT", trending_bars(), Regime.TREND_UP,
                               MarketContext(spread_fraction=0.01))
        assert record.action is Action.NO_TRADE
        assert any("spread" in r.lower() for r in record.reasons)

    def test_thin_book_gate(self):
        scorer = DecisionScorer([AlwaysEnter()])
        record = scorer.decide("BTCUSDT", trending_bars(), Regime.TREND_UP,
                               MarketContext(liquidity_ok=False))
        assert record.action is Action.NO_TRADE

    def test_decision_record_completeness_on_buy(self):
        scorer = DecisionScorer([AlwaysEnter()])
        record = scorer.decide("BTCUSDT", trending_bars(), Regime.TREND_UP, MarketContext())
        if record.action is Action.BUY:   # gates may legitimately reject
            assert record.entry_estimate and record.stop_price and record.take_profit
            assert record.expected_net_return is not None
            assert record.est_fees > 0 and record.reasons
        assert record.supporting or record.conflicting

    def test_sell_status_only_closes_open_positions(self):
        scorer = DecisionScorer([NeverEnter()])
        bars = trending_bars(drift=-0.004)   # falling market
        no_pos = scorer.decide("X", bars, Regime.TREND_DOWN, MarketContext())
        with_pos = scorer.decide("X", bars, Regime.TREND_DOWN,
                                 MarketContext(has_open_position=True))
        if no_pos.status in (DecisionStatus.SELL, DecisionStatus.STRONG_SELL):
            assert no_pos.action is Action.NO_TRADE       # spot: nothing to sell
            assert with_pos.action is Action.CLOSE


class TestEnsembleVoting:
    def test_exit_vote_abstains_without_open_position(self):
        """A strategy with nothing to exit must not vote the score down."""
        scorer = DecisionScorer([AlwaysExit()])
        bars = trending_bars()
        flat = scorer.decide("X", bars, Regime.RANGE, MarketContext())
        held = scorer.decide("X", bars, Regime.RANGE,
                             MarketContext(has_open_position=True))
        assert "ensemble" not in flat.conflicting
        assert held.conflicting["ensemble"] < 0

    def test_lone_voter_keeps_agreement_floor_of_unanimous(self):
        """One voter among five is worth less than five, but not negligible."""
        bars = trending_bars()
        lone = DecisionScorer(
            [AlwaysEnter()] + [RegimeHold(f"h{i}", Regime) for i in range(4)]
        ).decide("X", bars, Regime.TREND_UP, MarketContext())
        unanimous = DecisionScorer([AlwaysEnter() for _ in range(5)]).decide(
            "X", bars, Regime.TREND_UP, MarketContext())
        ratio = lone.supporting["ensemble"] / unanimous.supporting["ensemble"]
        assert AGREEMENT_FLOOR <= ratio < 1.0

    def test_lone_voter_can_clear_the_buy_threshold(self):
        """Dilution must not put a confident entry structurally out of reach."""
        record = DecisionScorer(
            [AlwaysEnter()] + [RegimeHold(f"h{i}", Regime) for i in range(4)]
        ).decide("X", trending_bars(), Regime.TREND_UP, MarketContext())
        assert record.score >= Gates().buy_threshold

    def test_confidence_is_strategy_conviction_not_score_magnitude(self):
        """min_confidence must gate conviction, not act as a second threshold."""
        record = DecisionScorer([AlwaysEnter()]).decide(
            "X", trending_bars(), Regime.TREND_UP, MarketContext())
        assert record.confidence == 0.9      # AlwaysEnter's own confidence

    def test_confidence_falls_back_to_score_without_votes(self):
        record = DecisionScorer([NeverEnter()]).decide(
            "X", trending_bars(), Regime.TREND_UP, MarketContext())
        assert record.confidence == round(min(1.0, abs(record.score)), 4)

    def test_regime_fit_uses_voters_only(self):
        """Non-voting strategies' regime preferences must not colour the fit."""
        strategies = [RegimeEnter("range_only", {Regime.RANGE})] + [
            RegimeHold(f"trend{i}", {Regime.TREND_UP}) for i in range(4)
        ]
        record = DecisionScorer(strategies).decide(
            "X", trending_bars(), Regime.RANGE, MarketContext())
        assert record.supporting["regime"] > 0

    def test_regime_fit_penalises_voter_out_of_regime(self):
        strategies = [RegimeEnter("range_only", {Regime.RANGE})] + [
            RegimeHold(f"trend{i}", {Regime.TREND_UP}) for i in range(4)
        ]
        record = DecisionScorer(strategies).decide(
            "X", trending_bars(), Regime.TREND_UP, MarketContext())
        assert record.conflicting["regime"] < 0


def buy_record(symbol: str, net: float, stop_frac: float) -> DecisionRecord:
    return DecisionRecord(
        symbol=symbol, action=Action.BUY, status=DecisionStatus.BUY,
        entry_estimate=100.0, stop_price=100.0 * (1 - stop_frac),
        expected_net_return=net,
    )


class TestRanking:
    def test_ranks_by_risk_adjusted_return(self):
        ranked = rank_opportunities([
            buy_record("AAA", net=0.01, stop_frac=0.05),   # rar 0.2
            buy_record("BBB", net=0.02, stop_frac=0.04),   # rar 0.5 ← best
        ])
        assert ranked[0].record.symbol == "BBB" and ranked[0].selected

    def test_top_n_cap(self):
        records = [buy_record(f"S{i}", net=0.01 + i * 0.001, stop_frac=0.05) for i in range(6)]
        ranked = rank_opportunities(records, max_selected=2)
        assert sum(1 for r in ranked if r.selected) == 2
        assert all("top 2" in r.excluded_reason for r in ranked if not r.selected)

    def test_correlated_pair_excluded(self):
        rng = random.Random(1)
        base = [rng.gauss(0, 0.01) for _ in range(100)]
        returns = {
            "AAA": base,
            "BBB": [x + rng.gauss(0, 0.001) for x in base],   # ~same series
            "CCC": [rng.gauss(0, 0.01) for _ in range(100)],  # independent
        }
        ranked = rank_opportunities(
            [buy_record("AAA", 0.03, 0.05), buy_record("BBB", 0.02, 0.05),
             buy_record("CCC", 0.01, 0.05)],
            returns_by_symbol=returns,
        )
        by_symbol = {r.record.symbol: r for r in ranked}
        assert by_symbol["AAA"].selected
        assert not by_symbol["BBB"].selected and "correlation" in by_symbol["BBB"].excluded_reason
        assert by_symbol["CCC"].selected

    def test_deterministic(self):
        records = [buy_record("AAA", 0.01, 0.05), buy_record("BBB", 0.01, 0.05)]
        a = rank_opportunities(records)
        b = rank_opportunities(records)
        assert [r.record.symbol for r in a] == [r.record.symbol for r in b]

    def test_correlation_math(self):
        xs = [float(i % 7) for i in range(50)]
        assert math.isclose(returns_correlation(xs, xs), 1.0)
        assert math.isclose(returns_correlation(xs, [-x for x in xs]), -1.0)


class TestNoLivePath:
    def test_no_live_execution_router_exists(self):
        """Grep-level guarantee: nothing constructs an execution path against
        the live exchange. Live trading requires Phase-6-gated work that this
        codebase intentionally does not contain."""
        from pathlib import Path

        src = Path(__file__).resolve().parents[2] / "src" / "cryptobot"
        offenders = []
        for path in src.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "live_rest" in text and "place_order" in text:
                offenders.append(path.name)
        assert offenders == [], f"live execution path suspected in: {offenders}"