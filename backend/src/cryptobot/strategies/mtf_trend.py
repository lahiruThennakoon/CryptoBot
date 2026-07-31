"""Multi-timeframe trend confirmation.

Approximates a higher timeframe by aggregating every `htf_factor` bars
(e.g. 4h from 1h). Entry: higher-TF trend up (EMA fast > slow) AND lower-TF
pullback resumes (close crosses back above fast EMA). Exit: higher-TF trend
flips. Stop: entry − 2×ATR. Regimes: trend_up.
"""

from __future__ import annotations

from collections.abc import Sequence

from cryptobot.features.indicators import atr, ema
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


class MultiTimeframeTrendStrategy(Strategy):
    def __init__(
        self,
        htf_factor: int = 4,
        htf_fast: int = 10,
        htf_slow: int = 30,
        ltf_fast: int = 20,
        atr_n: int = 14,
    ) -> None:
        self._factor, self._htf_fast_n, self._htf_slow_n = htf_factor, htf_fast, htf_slow
        self._ltf_fast_n, self._atr_n = ltf_fast, atr_n
        self.spec = StrategySpec(
            name="mtf_trend",
            timeframe="1h",
            warmup_bars=htf_factor * (htf_slow + 2),
            max_holding_bars=24 * 10,
            cooldown_bars=6,
            allowed_regimes=frozenset({Regime.TREND_UP}),
            required_conditions="Higher-TF uptrend with lower-TF pullback resumption",
            invalid_when="Timeframes disagree; higher-TF trend flat or down",
            params={"htf_factor": htf_factor, "htf_fast": htf_fast, "htf_slow": htf_slow},
        )
        self._ltf_ema: list[float | None] = []
        self._atr: list[float | None] = []
        self._htf_up: list[bool | None] = []

    def prepare(self, bars: Sequence[BarLike]) -> None:
        c = closes(bars)
        self._ltf_ema = ema(c, self._ltf_fast_n)
        self._atr = atr(highs(bars), lows(bars), c, self._atr_n)

        # Aggregate closed higher-TF candles causally: HTF close at index i uses
        # only fully completed groups of `factor` bars ending at or before i.
        htf_closes: list[float] = []
        htf_index_at: list[int] = []  # last LTF index covered by each HTF bar
        for end in range(self._factor - 1, len(c), self._factor):
            htf_closes.append(c[end])
            htf_index_at.append(end)
        f = ema(htf_closes, self._htf_fast_n)
        s = ema(htf_closes, self._htf_slow_n)
        up_flags: list[bool | None] = [
            (fv > sv) if fv is not None and sv is not None else None
            for fv, sv in zip(f, s, strict=True)
        ]
        # Map back to LTF index: at bar i, the latest COMPLETED HTF bar applies.
        self._htf_up = [None] * len(c)
        j = 0
        current: bool | None = None
        for i in range(len(c)):
            while j < len(htf_index_at) and htf_index_at[j] <= i:
                current = up_flags[j]
                j += 1
            self._htf_up[i] = current

    def on_bar(self, bars: Sequence[BarLike], i: int) -> Signal:
        if i < self.spec.warmup_bars:
            return HOLD
        htf_up = self._htf_up[i]
        e_now, e_prev, a = self._ltf_ema[i], self._ltf_ema[i - 1], self._atr[i]
        if htf_up is None or e_now is None or e_prev is None or a is None:
            return HOLD
        price = float(bars[i].close)  # type: ignore[arg-type]
        prev_price = float(bars[i - 1].close)  # type: ignore[arg-type]

        if not htf_up:
            return Signal(Intent.EXIT, confidence=1.0, reason="higher-TF trend flipped down")
        crossed_above_fast = prev_price <= e_prev and price > e_now
        if crossed_above_fast:
            return Signal(
                Intent.ENTER_LONG,
                confidence=0.7,
                stop_price=price - 2.0 * a,
                take_profit=None,
                reason="HTF uptrend + LTF pullback resumption",
            )
        return HOLD
