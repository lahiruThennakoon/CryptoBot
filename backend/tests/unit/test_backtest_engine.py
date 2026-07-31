"""Backtest engine behavior tests using a deterministic scripted strategy."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptobot.backtest.engine import BacktestEngine, SimpleRules
from cryptobot.backtest.metrics import compute_report
from cryptobot.costs.model import CostModel
from cryptobot.regime.detector import Regime
from cryptobot.risk.engine import BasicRiskEngine, RiskConfig
from cryptobot.strategies.base import HOLD, Intent, Signal, Strategy, StrategySpec


@dataclass(frozen=True)
class Bar:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def flat_bars(n: int, price: float = 100.0) -> list[Bar]:
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    return [Bar(t0 + timedelta(hours=i), price, price * 1.001, price * 0.999, price, 10.0)
            for i in range(n)]


class ScriptedStrategy(Strategy):
    """Enters at a scripted bar with a scripted stop; exits on script."""

    def __init__(self, enter_at: int, exit_at: int | None = None,
                 stop_pct: float = 0.05, tp_pct: float | None = None):
        self._enter_at, self._exit_at = enter_at, exit_at
        self._stop_pct, self._tp_pct = stop_pct, tp_pct
        self.spec = StrategySpec(
            name="scripted", timeframe="1h", warmup_bars=5, max_holding_bars=10_000,
            cooldown_bars=0, allowed_regimes=frozenset(Regime),
        )

    def on_bar(self, bars, i):
        price = float(bars[i].close)
        if i == self._enter_at:
            return Signal(Intent.ENTER_LONG, confidence=0.9,
                          stop_price=price * (1 - self._stop_pct),
                          take_profit=price * (1 + self._tp_pct) if self._tp_pct else None)
        if self._exit_at is not None and i == self._exit_at:
            return Signal(Intent.EXIT, confidence=1.0, reason="scripted")
        return HOLD


def engine(costs=None, risk_config=None):
    return BacktestEngine(
        costs=costs or CostModel(taker_fee=0.001, half_spread=0.0003, slippage=0.0005,
                                 latency_drift=0.0002, safety_margin=0.0),
        risk=BasicRiskEngine(risk_config or RiskConfig(min_confidence=0.5)),
        rules=SimpleRules(step_size=1e-5, min_qty=1e-5, min_notional=5.0),
        use_regime_filter=False,
    )


class TestExecutionTiming:
    def test_entry_fills_at_next_bar_open_with_costs(self):
        bars = flat_bars(30)
        result = engine().run(bars, ScriptedStrategy(enter_at=10, exit_at=20, tp_pct=None))
        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade.entry_time == bars[11].open_time          # next bar, not same bar
        expected_fill = 100.0 * (1 + 0.0003 + 0.0005 + 0.0002)
        assert math.isclose(trade.entry_price, expected_fill, rel_tol=1e-9)

    def test_flat_market_round_trip_loses_costs(self):
        """No price movement → net PnL must be strictly negative (fees+spread+slippage)."""
        bars = flat_bars(40)
        result = engine().run(bars, ScriptedStrategy(enter_at=10, exit_at=25))
        assert len(result.trades) == 1
        assert result.trades[0].pnl < 0
        assert result.total_fees > 0


class TestProtectiveExits:
    def test_stop_loss_triggers_at_stop_not_low(self):
        bars = flat_bars(30)
        crash = bars[15]
        bars[15] = Bar(crash.open_time, 100.0, 100.1, 80.0, 81.0, 10.0)  # low pierces stop
        result = engine().run(bars, ScriptedStrategy(enter_at=10, stop_pct=0.05))
        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade.exit_reason == "stop_loss"
        assert math.isclose(trade.exit_price,
                            engine()._costs.sell_fill_price(95.0), rel_tol=1e-9)

    def test_gap_through_stop_fills_at_open_not_stop(self):
        bars = flat_bars(30)
        gap = bars[15]
        bars[15] = Bar(gap.open_time, 85.0, 86.0, 84.0, 85.5, 10.0)  # opens below stop 95
        result = engine().run(bars, ScriptedStrategy(enter_at=10, stop_pct=0.05))
        trade = result.trades[0]
        assert trade.exit_reason == "stop_loss_gap"
        assert trade.exit_price < 95.0 * 0.999  # filled near the (worse) open

    def test_stop_beats_take_profit_when_both_touched(self):
        bars = flat_bars(30)
        wild = bars[15]
        bars[15] = Bar(wild.open_time, 100.0, 120.0, 80.0, 100.0, 10.0)
        result = engine().run(bars, ScriptedStrategy(enter_at=10, stop_pct=0.05, tp_pct=0.10))
        assert result.trades[0].exit_reason == "stop_loss"  # conservative ordering


class TestRiskIntegration:
    def test_no_stop_signal_rejected(self):
        class NoStop(ScriptedStrategy):
            def on_bar(self, bars, i):
                if i == 10:
                    return Signal(Intent.ENTER_LONG, confidence=0.9, stop_price=None)
                return HOLD

        result = engine().run(flat_bars(30), NoStop(enter_at=10))
        assert not result.trades
        assert any(r.reason_code == "NO_STOP" for r in result.rejected)

    def test_low_confidence_rejected(self):
        class Timid(ScriptedStrategy):
            def on_bar(self, bars, i):
                if i == 10:
                    return Signal(Intent.ENTER_LONG, confidence=0.1, stop_price=95.0)
                return HOLD

        result = engine().run(flat_bars(30), Timid(enter_at=10))
        assert not result.trades
        assert any(r.reason_code == "LOW_CONFIDENCE" for r in result.rejected)

    def test_sizing_respects_risk_per_trade(self):
        bars = flat_bars(40)
        cfg = RiskConfig(risk_per_trade=0.005, max_position_pct=1.0,
                         max_exposure_pct=1.0, min_confidence=0.5)
        result = engine(risk_config=cfg).run(bars, ScriptedStrategy(enter_at=10, stop_pct=0.05))
        trade = result.trades[0]
        risked = trade.qty * (trade.entry_price / (1 + 0.001) - 95.0)
        assert risked <= 10_000 * 0.005 * 1.05  # within risk budget (+5% tolerance)

    def test_deterministic_reruns(self):
        bars = flat_bars(60)
        r1 = engine().run(bars, ScriptedStrategy(enter_at=10, exit_at=30))
        r2 = engine().run(bars, ScriptedStrategy(enter_at=10, exit_at=30))
        assert r1.equity_curve == r2.equity_curve
        assert [t.pnl for t in r1.trades] == [t.pnl for t in r2.trades]


class TestReport:
    def test_report_consistency(self):
        bars = flat_bars(60)
        result = engine().run(bars, ScriptedStrategy(enter_at=10, exit_at=30))
        report = compute_report(result, "1h")
        assert report.n_trades == 1
        assert report.net_return_pct < 0          # flat market: costs only
        assert report.no_trade_return_pct == 0.0
        assert report.total_fees == result.total_fees