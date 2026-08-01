"""Versioned, leakage-safe feature pipeline.

Every feature at row i uses only bars[0..i]. Labels use bars[i+1..i+horizon]
and are therefore absent for the final `horizon` bars. The feature version is
a content hash of the feature spec — any change produces a new version, so a
model can never silently run on features it was not trained with.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from cryptobot.features.indicators import (
    atr,
    bollinger,
    macd,
    realized_vol,
    returns,
    rsi,
    sma,
)
from cryptobot.strategies.base import BarLike

RETURN_PERIODS = (1, 3, 6, 12, 24)


@dataclass(frozen=True)
class FeatureSpec:
    return_periods: tuple[int, ...] = RETURN_PERIODS
    sma_fast: int = 20
    sma_slow: int = 50
    rsi_n: int = 14
    atr_n: int = 14
    boll_n: int = 20
    vol_change_n: int = 20
    realized_vol_n: int = 20
    momentum_n: int = 12
    btc_corr_n: int = 48
    include_time_of_day: bool = True

    @property
    def version(self) -> str:
        payload = json.dumps(self.__dict__, sort_keys=True, default=str)
        return "fv1-" + hashlib.sha256(payload.encode()).hexdigest()[:12]


@dataclass
class FeatureMatrix:
    names: list[str]
    rows: list[list[float]]          # aligned with `bar_indices`
    bar_indices: list[int]           # index into the source bars per row
    version: str
    labels: list[int] = field(default_factory=list)  # aligned with rows; may be empty


class FeatureBuilder:
    def __init__(self, spec: FeatureSpec | None = None) -> None:
        self.spec = spec or FeatureSpec()

    def build(
        self,
        bars: Sequence[BarLike],
        btc_closes: Sequence[float] | None = None,
        horizon: int = 6,
        label_cost_threshold: float = 0.004,
    ) -> FeatureMatrix:
        """Build features and binary labels.

        Label = 1 when the forward `horizon`-bar return exceeds
        `label_cost_threshold` (a conservative round-trip cost), else 0.
        Rows without complete features or labels are dropped.

        When horizon=0, labels are omitted and the latest complete feature
        row is retained (for live inference).
        """
        s = self.spec
        closes = [float(b.close) for b in bars]  # type: ignore[arg-type]
        highs = [float(b.high) for b in bars]    # type: ignore[arg-type]
        lows = [float(b.low) for b in bars]      # type: ignore[arg-type]
        volumes = [float(b.volume) for b in bars]  # type: ignore[arg-type]
        n = len(bars)

        columns: dict[str, list[float | None]] = {}
        for p in s.return_periods:
            columns[f"ret_{p}"] = returns(closes, p)
        fast, slow = sma(closes, s.sma_fast), sma(closes, s.sma_slow)
        columns["sma_ratio"] = [
            (f / sl - 1) if f is not None and sl not in (None, 0) else None
            for f, sl in zip(fast, slow, strict=True)
        ]
        columns["rsi"] = [v / 100 if v is not None else None for v in rsi(closes, s.rsi_n)]
        _, _, hist = macd(closes)
        columns["macd_hist"] = [
            (h / closes[i]) if h is not None and closes[i] > 0 else None
            for i, h in enumerate(hist)
        ]
        atr_vals = atr(highs, lows, closes, s.atr_n)
        columns["atr_norm"] = [
            (a / closes[i]) if a is not None and closes[i] > 0 else None
            for i, a in enumerate(atr_vals)
        ]
        _, _, _, pct_b = bollinger(closes, s.boll_n)
        columns["boll_pct_b"] = pct_b
        vol_sma = sma(volumes, s.vol_change_n)
        columns["volume_change"] = [
            (volumes[i] / v - 1) if v not in (None, 0) else None
            for i, v in enumerate(vol_sma)
        ]
        columns["realized_vol"] = realized_vol(closes, s.realized_vol_n)
        columns["momentum"] = returns(closes, s.momentum_n)

        if s.include_time_of_day:
            columns["hour_sin"] = [
                math.sin(2 * math.pi * b.open_time.hour / 24) for b in bars
            ]
            columns["hour_cos"] = [
                math.cos(2 * math.pi * b.open_time.hour / 24) for b in bars
            ]

        if btc_closes is not None and len(btc_closes) == n:
            columns["btc_corr"] = _rolling_corr(
                returns(closes, 1), returns(list(btc_closes), 1), s.btc_corr_n
            )
            btc_trend = sma(list(btc_closes), s.sma_slow)
            columns["btc_direction"] = [
                (1.0 if btc_closes[i] > t else -1.0) if t is not None else None
                for i, t in enumerate(btc_trend)
            ]

        names = sorted(columns)
        labels_all: list[int | None] = [None] * n
        if horizon > 0:
            for i in range(n - horizon):
                if closes[i] > 0:
                    fwd = closes[i + horizon] / closes[i] - 1
                    labels_all[i] = 1 if fwd > label_cost_threshold else 0
        else:
            labels_all = [0] * n

        rows: list[list[float]] = []
        bar_indices: list[int] = []
        labels: list[int] = []
        for i in range(n):
            values = [columns[name][i] for name in names]
            if any(v is None for v in values):
                continue
            if horizon > 0 and labels_all[i] is None:
                continue
            rows.append([float(v) for v in values])  # type: ignore[arg-type]
            bar_indices.append(i)
            if horizon > 0:
                labels.append(int(labels_all[i]))  # type: ignore[arg-type]

        return FeatureMatrix(
            names=names, rows=rows, bar_indices=bar_indices,
            version=self.spec.version, labels=labels,
        )

    def inference_row(
        self,
        bars: Sequence[BarLike],
        btc_closes: Sequence[float] | None = None,
    ) -> list[float] | None:
        """Feature vector for the latest bar (no label required)."""
        matrix = self.build(bars, btc_closes=btc_closes, horizon=0)
        if not matrix.rows:
            return None
        return matrix.rows[-1]


def _rolling_corr(
    a: list[float | None], b: list[float | None], n: int
) -> list[float | None]:
    out: list[float | None] = [None] * len(a)
    for i in range(n, len(a)):
        xs = [a[j] for j in range(i - n + 1, i + 1)]
        ys = [b[j] for j in range(i - n + 1, i + 1)]
        if any(x is None for x in xs) or any(y is None for y in ys):
            continue
        xf = [float(x) for x in xs]   # type: ignore[arg-type]
        yf = [float(y) for y in ys]   # type: ignore[arg-type]
        mx, my = sum(xf) / n, sum(yf) / n
        cov = sum((x - mx) * (y - my) for x, y in zip(xf, yf, strict=True))
        vx = sum((x - mx) ** 2 for x in xf)
        vy = sum((y - my) ** 2 for y in yf)
        if vx > 0 and vy > 0:
            out[i] = cov / math.sqrt(vx * vy)
    return out
