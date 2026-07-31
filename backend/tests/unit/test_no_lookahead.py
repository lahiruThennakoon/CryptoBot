"""No-look-ahead proof for every registered strategy.

Method: run each strategy over a series, then corrupt all bars AFTER index i
with absurd values and verify the signal at i is unchanged. If a strategy
peeked at the future, corruption would alter its output.
"""

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from cryptobot.strategies import STRATEGY_REGISTRY


@dataclass(frozen=True)
class Bar:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def make_bars(n: int = 600, seed: int = 3) -> list[Bar]:
    rng = random.Random(seed)
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    price, bars = 100.0, []
    for i in range(n):
        drift = rng.gauss(0.0005, 0.01)
        o = price
        c = max(0.01, price * (1 + drift))
        hi = max(o, c) * (1 + abs(rng.gauss(0, 0.003)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, 0.003)))
        bars.append(Bar(t0 + timedelta(hours=i), o, hi, lo, c, abs(rng.gauss(100, 40)) + 1))
        price = c
    return bars


def corrupt_future(bars: list[Bar], keep: int) -> list[Bar]:
    corrupted = list(bars[: keep + 1])
    t = bars[keep].open_time
    for j in range(keep + 1, len(bars)):
        v = 1e9 if j % 2 else 1e-3
        corrupted.append(Bar(t + timedelta(hours=j), v, v * 1.1, v * 0.9, v, 1e9))
    return corrupted


def replay(strategy, bars, upto: int):
    """Sequential replay — strategies may carry internal state across bars."""
    strategy.prepare(bars)
    signals = []
    for i in range(upto + 1):
        signals.append(strategy.on_bar(bars, i))
    return signals


@pytest.mark.parametrize("name", sorted(STRATEGY_REGISTRY))
def test_strategy_never_uses_future_data(name):
    bars = make_bars()
    checkpoints = [150, 300, 450, 550]

    for i in checkpoints:
        signals_full = replay(STRATEGY_REGISTRY[name](), bars, i)
        signals_corrupted = replay(STRATEGY_REGISTRY[name](), corrupt_future(bars, i), i)
        full, sig = signals_full[i], signals_corrupted[i]
        assert sig.intent == full.intent, f"{name}: intent changed by future data at bar {i}"
        if full.stop_price is not None and sig.stop_price is not None:
            assert math.isclose(sig.stop_price, full.stop_price, rel_tol=1e-9), (
                f"{name}: stop changed by future data at bar {i}"
            )
        assert math.isclose(sig.confidence, full.confidence, rel_tol=1e-9), (
            f"{name}: confidence changed by future data at bar {i}"
        )