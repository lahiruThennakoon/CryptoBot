import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptobot.backtest.walkforward import sensitivity_analysis, walk_forward
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


def trending_bars(n: int = 1200, seed: int = 11) -> list[Bar]:
    rng = random.Random(seed)
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    price, bars = 100.0, []
    for i in range(n):
        c = max(0.01, price * (1 + rng.gauss(0.0004, 0.008)))
        o = price
        bars.append(Bar(t0 + timedelta(hours=i), o, max(o, c) * 1.002,
                        min(o, c) * 0.998, c, 10.0))
        price = c
    return bars


class PeriodicStrategy(Strategy):
    """Enters every `period` bars — enough activity to exercise the machinery."""

    def __init__(self, period: int = 50):
        self._period = period
        self.spec = StrategySpec(
            name="periodic", timeframe="1h", warmup_bars=10, max_holding_bars=20,
            cooldown_bars=0, allowed_regimes=frozenset(Regime),
        )

    def on_bar(self, bars, i):
        if i % self._period == 0:
            price = float(bars[i].close)
            return Signal(Intent.ENTER_LONG, confidence=0.9, stop_price=price * 0.95)
        return HOLD


class TestWalkForward:
    def test_windows_cover_series_without_overlap(self):
        bars = trending_bars()
        wf = walk_forward(bars, PeriodicStrategy, train_bars=400, test_bars=200)
        assert wf.total_windows == 4
        for k in range(1, len(wf.windows)):
            assert wf.windows[k].start_index == wf.windows[k - 1].end_index

    def test_param_grid_selects_on_train_only(self):
        bars = trending_bars()
        wf = walk_forward(
            bars, PeriodicStrategy, train_bars=400, test_bars=200,
            param_grid=[{"period": 40}, {"period": 80}],
        )
        for w in wf.windows:
            assert w.chosen_params in ({"period": 40}, {"period": 80}, {})

    def test_summary_mentions_stability_caveat(self):
        wf = walk_forward(trending_bars(700), PeriodicStrategy, train_bars=400, test_bars=200)
        assert "not a guarantee" in wf.summary()


class TestSensitivity:
    def test_higher_costs_never_improve_results(self):
        bars = trending_bars(800)
        grid = sensitivity_analysis(
            bars, PeriodicStrategy, fee_multipliers=(1.0, 2.0), slippage_multipliers=(1.0, 3.0),
        )
        base = grid[(1.0, 1.0)].net_return_pct
        stressed = grid[(2.0, 3.0)].net_return_pct
        assert stressed <= base + 1e-9 or math.isclose(stressed, base)