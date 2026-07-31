"""Moving-average trend following.

Entry: fast SMA crosses above slow SMA with both rising.
Exit: fast crosses back below slow.
Stop: entry − 2×ATR. Take-profit: none (trend-following rides the trend).
Regimes: trend_up only. Invalid: flat/declining slow MA, ATR unavailable.
"""

from __future__ import annotations

from collections.abc import Sequence

from cryptobot.features.indicators import atr, sma
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


class MaTrendStrategy(Strategy):
    def __init__(self, fast: int = 20, slow: int = 50, atr_n: int = 14, atr_mult: float = 2.0) -> None:
        self._fast_n, self._slow_n, self._atr_n, self._atr_mult = fast, slow, atr_n, atr_mult
        self.spec = StrategySpec(
            name="ma_trend",
            timeframe="1h",
            warmup_bars=slow + 11,
            max_holding_bars=24 * 14,          # 14 days on 1h bars
            cooldown_bars=6,
            allowed_regimes=frozenset({Regime.TREND_UP}),
            required_conditions="Established uptrend; fast/slow SMA both rising",
            invalid_when="Slow MA flat or falling; ATR unavailable; volatile regime",
            params={"fast": fast, "slow": slow, "atr_mult": atr_mult},
        )
        self._fast: list[float | None] = []
        self._slow: list[float | None] = []
        self._atr: list[float | None] = []

    def prepare(self, bars: Sequence[BarLike]) -> None:
        c = closes(bars)
        self._fast = sma(c, self._fast_n)
        self._slow = sma(c, self._slow_n)
        self._atr = atr(highs(bars), lows(bars), c, self._atr_n)

    def on_bar(self, bars: Sequence[BarLike], i: int) -> Signal:
        if i < self.spec.warmup_bars:
            return HOLD
        f_now, f_prev = self._fast[i], self._fast[i - 1]
        s_now, s_prev = self._slow[i], self._slow[i - 1]
        s_back = self._slow[i - 10]
        a = self._atr[i]
        if None in (f_now, f_prev, s_now, s_prev, s_back, a):
            return HOLD
        assert f_now and f_prev and s_now and s_prev and s_back and a
        price = float(bars[i].close)  # type: ignore[arg-type]

        crossed_up = f_prev <= s_prev and f_now > s_now
        crossed_down = f_prev >= s_prev and f_now < s_now
        slow_rising = s_now > s_back

        if crossed_down:
            return Signal(Intent.EXIT, confidence=1.0, reason="fast SMA crossed below slow")
        if crossed_up and slow_rising:
            separation = (f_now - s_now) / price
            confidence = min(1.0, 0.6 + separation * 40)
            return Signal(
                Intent.ENTER_LONG,
                confidence=confidence,
                stop_price=price - self._atr_mult * a,
                take_profit=None,
                reason=f"SMA{self._fast_n}x{self._slow_n} bullish cross, slow rising",
            )
        return HOLD
