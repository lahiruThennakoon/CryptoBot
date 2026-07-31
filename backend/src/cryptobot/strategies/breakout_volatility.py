"""Breakout with volatility filter.

Entry: close breaks above the prior N-bar high while volatility is NOT in
its top decile (breakouts during volatility spikes are disproportionately
false). Exit: close back below the breakout level. Stop: breakout level − 1×ATR.
TP: entry + 2×ATR. Regimes: trend_up or range (breakout from consolidation).
"""

from __future__ import annotations

from collections.abc import Sequence

from cryptobot.features.indicators import atr, percentile_rank, rolling_max
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


class BreakoutVolatilityStrategy(Strategy):
    def __init__(
        self,
        channel_n: int = 20,
        atr_n: int = 14,
        vol_lookback: int = 200,
        max_vol_rank: float = 0.90,
    ) -> None:
        self._channel_n, self._atr_n = channel_n, atr_n
        self._vol_lookback, self._max_vol_rank = vol_lookback, max_vol_rank
        self.spec = StrategySpec(
            name="breakout_volatility",
            timeframe="1h",
            warmup_bars=max(channel_n, atr_n) + 2,
            max_holding_bars=24 * 7,
            cooldown_bars=10,
            allowed_regimes=frozenset({Regime.TREND_UP, Regime.RANGE}),
            required_conditions="Break of N-bar high outside volatility spikes",
            invalid_when="ATR in top decile; no prior consolidation",
            params={"channel_n": channel_n, "max_vol_rank": max_vol_rank},
        )
        self._hh: list[float | None] = []
        self._atr: list[float | None] = []
        self._atr_norm: list[float | None] = []
        self._breakout_level: float | None = None

    def prepare(self, bars: Sequence[BarLike]) -> None:
        c = closes(bars)
        h = highs(bars)
        self._hh = rolling_max(h, self._channel_n)
        self._atr = atr(h, lows(bars), c, self._atr_n)
        self._atr_norm = [
            (a / c[i]) if a is not None and c[i] > 0 else None for i, a in enumerate(self._atr)
        ]
        self._breakout_level = None

    def on_bar(self, bars: Sequence[BarLike], i: int) -> Signal:
        if i < self.spec.warmup_bars:
            return HOLD
        prior_high, a = self._hh[i - 1], self._atr[i]
        if prior_high is None or a is None:
            return HOLD
        price = float(bars[i].close)  # type: ignore[arg-type]

        if self._breakout_level is not None and price < self._breakout_level:
            self._breakout_level = None
            return Signal(Intent.EXIT, confidence=1.0, reason="fell back through breakout level")

        if price > prior_high:
            vol_rank = percentile_rank(self._atr_norm, i, self._vol_lookback)
            if vol_rank is not None and vol_rank > self._max_vol_rank:
                return HOLD  # volatility spike — structurally invalid breakout
            margin = (price - prior_high) / prior_high
            self._breakout_level = prior_high
            return Signal(
                Intent.ENTER_LONG,
                confidence=min(1.0, 0.6 + margin * 60),
                stop_price=prior_high - 1.0 * a,
                take_profit=price + 2.0 * a,
                reason=f"broke {self._channel_n}-bar high at {prior_high:.2f}",
            )
        return HOLD
