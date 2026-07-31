"""Strategy interface shared by backtest, paper and (eventually) live paths.

Contract:
- `prepare(bars)` is called once; it may precompute CAUSAL indicator series.
- `on_bar(bars, i)` may only use bars[0..i]. The no-look-ahead test in
  tests/unit/test_no_lookahead.py enforces this for every registered strategy.
- Spot only: strategies go long or flat, never short.
- Returning HOLD (or never signaling) is a first-class, valid outcome.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

from cryptobot.regime.detector import Regime


@runtime_checkable
class BarLike(Protocol):
    """Duck-typed candle: works for exchange Candle models and plain test bars."""

    open_time: datetime

    @property
    def open(self) -> object: ...
    @property
    def high(self) -> object: ...
    @property
    def low(self) -> object: ...
    @property
    def close(self) -> object: ...
    @property
    def volume(self) -> object: ...


class Intent(str, Enum):
    ENTER_LONG = "enter_long"
    EXIT = "exit"
    HOLD = "hold"


@dataclass(frozen=True)
class Signal:
    intent: Intent
    confidence: float = 0.0          # 0..1; risk engine enforces a minimum
    stop_price: float | None = None  # REQUIRED for ENTER_LONG (no stop → rejected)
    take_profit: float | None = None
    reason: str = ""

    HOLD_INSTANCE: "Signal | None" = None


HOLD = Signal(intent=Intent.HOLD, reason="no setup")


@dataclass(frozen=True)
class StrategySpec:
    """Everything a strategy must declare about itself (docs/prd.md FR-3.1)."""

    name: str
    timeframe: str                                  # e.g. "1h"
    warmup_bars: int                                # bars needed before first signal
    max_holding_bars: int                           # forced exit after this many bars
    cooldown_bars: int                              # entry cooldown after any exit
    allowed_regimes: frozenset[Regime]              # operates ONLY in these regimes
    pairs: tuple[str, ...] = ()                     # empty = any configured pair
    required_conditions: str = ""                   # human-readable market conditions
    invalid_when: str = ""                          # human-readable invalid-signal conditions
    params: dict[str, float] = field(default_factory=dict)


class Strategy(ABC):
    spec: StrategySpec

    def prepare(self, bars: Sequence[BarLike]) -> None:
        """Precompute causal indicator series over `bars`. Called once per run."""

    @abstractmethod
    def on_bar(self, bars: Sequence[BarLike], i: int) -> Signal:
        """Signal for bar i. MUST use only bars[0..i] (and causal precomputations)."""


def closes(bars: Sequence[BarLike]) -> list[float]:
    return [float(b.close) for b in bars]  # type: ignore[arg-type]


def highs(bars: Sequence[BarLike]) -> list[float]:
    return [float(b.high) for b in bars]  # type: ignore[arg-type]


def lows(bars: Sequence[BarLike]) -> list[float]:
    return [float(b.low) for b in bars]  # type: ignore[arg-type]


def volumes(bars: Sequence[BarLike]) -> list[float]:
    return [float(b.volume) for b in bars]  # type: ignore[arg-type]
