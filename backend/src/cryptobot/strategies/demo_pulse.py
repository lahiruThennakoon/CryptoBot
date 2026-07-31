"""DEMO strategy — exists ONLY to make the machinery visible, fast.

Enters whenever flat (1-minute candles), exits via stop / take-profit /
short max-hold. It has NO edge by design and will slowly lose simulated
money to fees and spread — which is itself the honest lesson it teaches.

It is deliberately NOT in STRATEGY_REGISTRY: it can never run unless the
operator explicitly starts `cryptobot trade --demo`, and it only ever
touches the paper account.
"""

from __future__ import annotations

from collections.abc import Sequence

from cryptobot.features.indicators import atr
from cryptobot.regime.detector import Regime
from cryptobot.strategies.base import (
    HOLD,
    BarLike,
    Intent,
    Signal,
    Strategy,
    StrategySpec,
    closes,
    highs,
    lows,
)


class DemoPulseStrategy(Strategy):
    def __init__(self, atr_n: int = 14) -> None:
        self._atr_n = atr_n
        self.spec = StrategySpec(
            name="demo_pulse",
            timeframe="1m",
            warmup_bars=atr_n + 6,
            max_holding_bars=6,            # forced exit ~6 minutes after entry
            cooldown_bars=2,
            allowed_regimes=frozenset(Regime),   # demo ignores regime selectivity
            required_conditions="NONE — demo mode enters whenever flat",
            invalid_when="never (that is the point of the demo)",
            params={"demo": 1.0},
        )
        self._atr: list[float | None] = []

    def prepare(self, bars: Sequence[BarLike]) -> None:
        c = closes(bars)
        self._atr = atr(highs(bars), lows(bars), c, self._atr_n)

    def on_bar(self, bars: Sequence[BarLike], i: int) -> Signal:
        if i < self.spec.warmup_bars:
            return HOLD
        a = self._atr[i]
        if a is None:
            return HOLD
        price = float(bars[i].close)  # type: ignore[arg-type]
        # Stop wide enough to satisfy the risk engine's minimum distance,
        # take-profit far enough to clear the cost gate (~0.8% > round-trip
        # costs + margin) — it will rarely hit; max-hold does the exiting.
        stop = price - max(2.0 * a, price * 0.004)
        take_profit = price * 1.008
        return Signal(
            Intent.ENTER_LONG,
            confidence=0.9,
            stop_price=stop,
            take_profit=take_profit,
            reason="DEMO: scripted entry to exercise the pipeline — no edge claimed",
        )


DEMO_STRATEGIES: dict[str, type[Strategy]] = {"demo_pulse": DemoPulseStrategy}
