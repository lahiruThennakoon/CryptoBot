"""Momentum with volume confirmation.

Entry: N-bar return above threshold AND current volume above k× its SMA.
Exit: momentum fades below zero. Stop: entry − 2×ATR. TP: entry + 3×ATR.
Regimes: trend_up. Invalid: weak volume, negative momentum, volatile regime.
"""

from __future__ import annotations

from collections.abc import Sequence

from cryptobot.features.indicators import atr, returns, sma
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
    volumes,
)


class MomentumVolumeStrategy(Strategy):
    def __init__(
        self,
        lookback: int = 12,
        min_return: float = 0.02,
        volume_mult: float = 1.5,
        volume_sma_n: int = 20,
        atr_n: int = 14,
    ) -> None:
        self._lookback, self._min_return = lookback, min_return
        self._volume_mult, self._volume_sma_n, self._atr_n = volume_mult, volume_sma_n, atr_n
        self.spec = StrategySpec(
            name="momentum_volume",
            timeframe="1h",
            warmup_bars=max(lookback, volume_sma_n, atr_n) + 2,
            max_holding_bars=24 * 5,
            cooldown_bars=8,
            allowed_regimes=frozenset({Regime.TREND_UP}),
            required_conditions="Strong recent return with above-average volume",
            invalid_when="Volume below average; momentum negative; volatile regime",
            params={"lookback": lookback, "min_return": min_return, "volume_mult": volume_mult},
        )
        self._ret: list[float | None] = []
        self._vol_sma: list[float | None] = []
        self._atr: list[float | None] = []
        self._vols: list[float] = []

    def prepare(self, bars: Sequence[BarLike]) -> None:
        c = closes(bars)
        self._vols = volumes(bars)
        self._ret = returns(c, self._lookback)
        self._vol_sma = sma(self._vols, self._volume_sma_n)
        self._atr = atr(highs(bars), lows(bars), c, self._atr_n)

    def on_bar(self, bars: Sequence[BarLike], i: int) -> Signal:
        if i < self.spec.warmup_bars:
            return HOLD
        r, v_avg, a = self._ret[i], self._vol_sma[i], self._atr[i]
        if r is None or v_avg is None or a is None:
            return HOLD
        price = float(bars[i].close)  # type: ignore[arg-type]

        if r < 0:
            return Signal(Intent.EXIT, confidence=1.0, reason="momentum turned negative")
        if r >= self._min_return and v_avg > 0 and self._vols[i] >= self._volume_mult * v_avg:
            strength = min(1.0, r / (self._min_return * 3))
            vol_boost = min(1.0, self._vols[i] / (self._volume_mult * v_avg) - 1.0)
            return Signal(
                Intent.ENTER_LONG,
                confidence=min(1.0, 0.55 + 0.3 * strength + 0.15 * vol_boost),
                stop_price=price - 2.0 * a,
                take_profit=price + 3.0 * a,
                reason=f"{self._lookback}-bar return {r:.2%} with volume confirmation",
            )
        return HOLD
