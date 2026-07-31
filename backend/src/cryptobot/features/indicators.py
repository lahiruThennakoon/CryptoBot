"""Causal technical indicators.

All functions return lists aligned with the input (None during warmup) and
use only data at or before each index — no look-ahead by construction.
Indicator math uses float; money stays Decimal at the accounting boundary.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Series = list[float | None]


def sma(values: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(values)
    acc = 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= n:
            acc -= values[i - n]
        if i >= n - 1:
            out[i] = acc / n
    return out


def ema(values: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(values)
    if len(values) < n:
        return out
    alpha = 2.0 / (n + 1)
    prev = sum(values[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def returns(values: Sequence[float], n: int = 1) -> Series:
    out: Series = [None] * len(values)
    for i in range(n, len(values)):
        if values[i - n] != 0:
            out[i] = values[i] / values[i - n] - 1.0
    return out


def rsi(values: Sequence[float], n: int = 14) -> Series:
    """Wilder's RSI."""
    out: Series = [None] * len(values)
    if len(values) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        delta = values[i] - values[i - 1]
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    avg_gain, avg_loss = gains / n, losses / n
    out[n] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
    for i in range(n + 1, len(values)):
        delta = values[i] - values[i - 1]
        avg_gain = (avg_gain * (n - 1) + max(delta, 0.0)) / n
        avg_loss = (avg_loss * (n - 1) + max(-delta, 0.0)) / n
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
    return out


def macd(
    values: Sequence[float], fast: int = 12, slow: int = 26, signal_n: int = 9
) -> tuple[Series, Series, Series]:
    fast_e, slow_e = ema(values, fast), ema(values, slow)
    line: Series = [
        (f - s) if f is not None and s is not None else None
        for f, s in zip(fast_e, slow_e, strict=True)
    ]
    dense = [v for v in line if v is not None]
    sig_dense = ema(dense, signal_n) if dense else []
    sig: Series = [None] * len(values)
    offset = len(values) - len(dense)
    for j, v in enumerate(sig_dense):
        sig[offset + j] = v
    hist: Series = [
        (m - s) if m is not None and s is not None else None
        for m, s in zip(line, sig, strict=True)
    ]
    return line, sig, hist


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], n: int = 14
) -> Series:
    """Wilder's ATR."""
    length = len(closes)
    out: Series = [None] * length
    if length <= n:
        return out
    trs = [highs[0] - lows[0]]
    for i in range(1, length):
        trs.append(
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        )
    prev = sum(trs[1 : n + 1]) / n
    out[n] = prev
    for i in range(n + 1, length):
        prev = (prev * (n - 1) + trs[i]) / n
        out[i] = prev
    return out


def bollinger(
    values: Sequence[float], n: int = 20, k: float = 2.0
) -> tuple[Series, Series, Series, Series]:
    """Returns (mid, upper, lower, %B)."""
    mid = sma(values, n)
    upper: Series = [None] * len(values)
    lower: Series = [None] * len(values)
    pct_b: Series = [None] * len(values)
    for i in range(n - 1, len(values)):
        m = mid[i]
        assert m is not None
        var = sum((values[j] - m) ** 2 for j in range(i - n + 1, i + 1)) / n
        sd = math.sqrt(var)
        upper[i], lower[i] = m + k * sd, m - k * sd
        band = upper[i] - lower[i]  # type: ignore[operator]
        pct_b[i] = 0.5 if band == 0 else (values[i] - lower[i]) / band  # type: ignore[operator]
    return mid, upper, lower, pct_b


def realized_vol(closes: Sequence[float], n: int = 20) -> Series:
    """Rolling std-dev of 1-bar log returns (per-bar, not annualized)."""
    out: Series = [None] * len(closes)
    logs = [0.0] + [
        math.log(closes[i] / closes[i - 1]) if closes[i - 1] > 0 else 0.0
        for i in range(1, len(closes))
    ]
    for i in range(n, len(closes)):
        window = logs[i - n + 1 : i + 1]
        mean = sum(window) / n
        out[i] = math.sqrt(sum((x - mean) ** 2 for x in window) / n)
    return out


def rolling_max(values: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(values)
    for i in range(n - 1, len(values)):
        out[i] = max(values[i - n + 1 : i + 1])
    return out


def rolling_min(values: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(values)
    for i in range(n - 1, len(values)):
        out[i] = min(values[i - n + 1 : i + 1])
    return out


def percentile_rank(values: Sequence[float | None], i: int, lookback: int) -> float | None:
    """Rank of values[i] within the previous `lookback` non-None values (0..1)."""
    current = values[i]
    if current is None:
        return None
    window = [v for v in values[max(0, i - lookback + 1) : i + 1] if v is not None]
    if len(window) < 2:
        return None
    below = sum(1 for v in window if v <= current)
    return below / len(window)
