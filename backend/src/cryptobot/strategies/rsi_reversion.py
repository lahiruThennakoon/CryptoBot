"""RSI mean reversion.

Entry: RSI dips below oversold threshold then turns up, in a RANGE regime.
Exit: RSI recovers above the exit level. Stop: entry − 2.5×ATR.
TP: middle Bollinger band. Regimes: range only — mean reversion in a trend
or high-volatility regime is how reversion strategies die.
"""

from __future__ import annotations

from collections.abc import Sequence

from cryptobot.features.indicators import atr, bollinger, rsi
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


class RsiReversionStrategy(Strategy):
    def __init__(
        self,
        rsi_n: int = 14,
        oversold: float = 30.0,
        exit_level: float = 55.0,
        atr_n: int = 14,
        boll_n: int = 20,
    ) -> None:
        self._rsi_n, self._oversold, self._exit_level = rsi_n, oversold, exit_level
        self._atr_n, self._boll_n = atr_n, boll_n
        self.spec = StrategySpec(
            name="rsi_reversion",
            timeframe="1h",
            warmup_bars=max(rsi_n, atr_n, boll_n) + 2,
            max_holding_bars=48,
            cooldown_bars=12,
            allowed_regimes=frozenset({Regime.RANGE}),
            required_conditions="Sideways market; RSI oversold and turning up",
            invalid_when="Trending or volatile regime; RSI still falling",
            params={"rsi_n": rsi_n, "oversold": oversold, "exit_level": exit_level},
        )
        self._rsi: list[float | None] = []
        self._atr: list[float | None] = []
        self._boll_mid: list[float | None] = []

    def prepare(self, bars: Sequence[BarLike]) -> None:
        c = closes(bars)
        self._rsi = rsi(c, self._rsi_n)
        self._atr = atr(highs(bars), lows(bars), c, self._atr_n)
        self._boll_mid, _, _, _ = bollinger(c, self._boll_n)

    def on_bar(self, bars: Sequence[BarLike], i: int) -> Signal:
        if i < self.spec.warmup_bars:
            return HOLD
        r_now, r_prev, a, mid = self._rsi[i], self._rsi[i - 1], self._atr[i], self._boll_mid[i]
        if r_now is None or r_prev is None or a is None or mid is None:
            return HOLD
        price = float(bars[i].close)  # type: ignore[arg-type]

        if r_now >= self._exit_level:
            return Signal(Intent.EXIT, confidence=1.0, reason=f"RSI recovered to {r_now:.0f}")
        if r_prev < self._oversold and r_now > r_prev:
            depth = max(0.0, (self._oversold - r_prev) / self._oversold)
            return Signal(
                Intent.ENTER_LONG,
                confidence=min(1.0, 0.6 + depth),
                stop_price=price - 2.5 * a,
                take_profit=mid if mid > price else None,
                reason=f"RSI {r_prev:.0f}→{r_now:.0f} turning up from oversold",
            )
        return HOLD
