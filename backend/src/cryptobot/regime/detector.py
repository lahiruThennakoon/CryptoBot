"""Market-regime detection (Phase 3: transparent rule-based classifier).

Regimes: trend_up · trend_down · range · volatile. Strategies declare the
regimes they may operate in; everything else is a structural "no trade".
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum

from cryptobot.features.indicators import atr, percentile_rank, sma


class Regime(str, Enum):
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


class RegimeDetector:
    """Classifies each bar using only past data (causal)."""

    def __init__(
        self,
        trend_window: int = 50,
        slope_window: int = 10,
        slope_threshold: float = 0.005,   # |SMA50 change over 10 bars| / price
        # 0.005 calibrated for 1h crypto bars (~28% trend-up on 2y BTC-like
        # data); the previous 0.015 suited daily bars and classified <3% of
        # hourly bars as trending, starving trend strategies of any regime.
        vol_lookback: int = 200,
        vol_percentile_cutoff: float = 0.90,
        atr_window: int = 14,
    ) -> None:
        self._trend_window = trend_window
        self._slope_window = slope_window
        self._slope_threshold = slope_threshold
        self._vol_lookback = vol_lookback
        self._vol_cutoff = vol_percentile_cutoff
        self._atr_window = atr_window

    def classify_series(
        self,
        highs: Sequence[float],
        lows: Sequence[float],
        closes: Sequence[float],
    ) -> list[Regime]:
        n = len(closes)
        trend_ma = sma(closes, self._trend_window)
        atr_vals = atr(highs, lows, closes, self._atr_window)
        atr_norm: list[float | None] = [
            (a / closes[i]) if a is not None and closes[i] > 0 else None
            for i, a in enumerate(atr_vals)
        ]
        out: list[Regime] = []
        for i in range(n):
            ma_now = trend_ma[i]
            ma_then = trend_ma[i - self._slope_window] if i >= self._slope_window else None
            if ma_now is None or ma_then is None or closes[i] <= 0:
                out.append(Regime.UNKNOWN)
                continue
            vol_rank = percentile_rank(atr_norm, i, self._vol_lookback)
            if vol_rank is not None and vol_rank >= self._vol_cutoff:
                out.append(Regime.VOLATILE)
                continue
            slope = (ma_now - ma_then) / closes[i]
            if slope > self._slope_threshold:
                out.append(Regime.TREND_UP)
            elif slope < -self._slope_threshold:
                out.append(Regime.TREND_DOWN)
            else:
                out.append(Regime.RANGE)
        return out
