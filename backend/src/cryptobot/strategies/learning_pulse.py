"""Learning-mode strategy — exercises the pipeline on testnet, not for live.

Fires a long entry on most hourly bars when volatility is not extreme and
price is not in a sharp downtrend. No edge is claimed; the goal is to let
operators see entries, fills, exits, and daily reports on a small account.

Deliberately NOT in STRATEGY_REGISTRY — only loaded when CRYPTOBOT_LEARNING_MODE
is enabled alongside the standard strategies.
"""

from __future__ import annotations

from collections.abc import Sequence

from cryptobot.features.indicators import atr, percentile_rank, sma
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


class LearningPulseStrategy(Strategy):
    """Hourly pulse entry for testnet learning — frequent, low-conviction."""

    def __init__(self, atr_n: int = 14, trend_n: int = 50, vol_lookback: int = 200) -> None:
        self._atr_n = atr_n
        self._trend_n = trend_n
        self._vol_lookback = vol_lookback
        self.spec = StrategySpec(
            name="learning_pulse",
            timeframe="1h",
            warmup_bars=max(atr_n, trend_n) + 5,
            max_holding_bars=12,
            cooldown_bars=2,
            allowed_regimes=frozenset(Regime),
            required_conditions="Learning mode: non-volatile, not sharply down",
            invalid_when="ATR in top decile or price well below trend MA",
            params={"learning": 1.0},
        )
        self._atr: list[float | None] = []
        self._atr_norm: list[float | None] = []
        self._trend: list[float | None] = []

    def prepare(self, bars: Sequence[BarLike]) -> None:
        c = closes(bars)
        h, l = highs(bars), lows(bars)
        self._atr = atr(h, l, c, self._atr_n)
        self._atr_norm = [
            (a / c[i]) if a is not None and c[i] > 0 else None
            for i, a in enumerate(self._atr)
        ]
        self._trend = sma(c, self._trend_n)

    def on_bar(self, bars: Sequence[BarLike], i: int) -> Signal:
        if i < self.spec.warmup_bars:
            return HOLD
        a = self._atr[i]
        trend = self._trend[i]
        if a is None or trend is None:
            return HOLD
        price = float(bars[i].close)  # type: ignore[arg-type]
        if price <= 0 or trend <= 0:
            return HOLD

        vol_rank = percentile_rank(self._atr_norm, i, self._vol_lookback)
        if vol_rank is not None and vol_rank >= 0.92:
            return HOLD
        if price < trend * 0.97:
            return HOLD

        stop = price - max(2.0 * a, price * 0.004)
        take_profit = price * 1.008
        return Signal(
            Intent.ENTER_LONG,
            confidence=0.65,
            stop_price=stop,
            take_profit=take_profit,
            reason="LEARNING: hourly pipeline exercise — no edge claimed",
        )


LEARNING_STRATEGIES: dict[str, type[Strategy]] = {"learning_pulse": LearningPulseStrategy}
