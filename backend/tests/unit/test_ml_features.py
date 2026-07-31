import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptobot.ml.features import FeatureBuilder, FeatureSpec


@dataclass(frozen=True)
class Bar:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def make_bars(n=400, seed=9):
    rng = random.Random(seed)
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    price, out = 100.0, []
    for i in range(n):
        c = max(0.01, price * (1 + rng.gauss(0.0002, 0.01)))
        out.append(Bar(t0 + timedelta(hours=i), price, max(price, c) * 1.002,
                       min(price, c) * 0.998, c, abs(rng.gauss(50, 20)) + 1))
        price = c
    return out


class TestFeatureBuilder:
    def test_versions_change_with_spec(self):
        assert FeatureSpec().version != FeatureSpec(rsi_n=21).version
        assert FeatureSpec().version == FeatureSpec().version

    def test_rows_align_with_labels(self):
        m = FeatureBuilder().build(make_bars(), horizon=6)
        assert len(m.rows) == len(m.labels) == len(m.bar_indices)
        assert all(label in (0, 1) for label in m.labels)
        assert all(len(r) == len(m.names) for r in m.rows)

    def test_last_horizon_bars_have_no_rows(self):
        bars = make_bars()
        m = FeatureBuilder().build(bars, horizon=6)
        assert max(m.bar_indices) <= len(bars) - 6 - 1

    def test_features_are_causal(self):
        """Corrupting the future must not change past feature rows."""
        bars = make_bars()
        m1 = FeatureBuilder().build(bars, horizon=6)
        cutoff = 300
        corrupted = list(bars[:cutoff]) + [
            Bar(b.open_time, 1e6, 1.1e6, 0.9e6, 1e6, 1e9) for b in bars[cutoff:]
        ]
        m2 = FeatureBuilder().build(corrupted, horizon=6)
        common = [k for k, idx in enumerate(m1.bar_indices) if idx < cutoff - 6]
        lookup2 = {idx: k for k, idx in enumerate(m2.bar_indices)}
        checked = 0
        for k in common:
            idx = m1.bar_indices[k]
            if idx in lookup2:
                for v1, v2 in zip(m1.rows[k], m2.rows[lookup2[idx]], strict=True):
                    assert math.isclose(v1, v2, rel_tol=1e-9), f"feature leak at bar {idx}"
                checked += 1
        assert checked > 50

    def test_labels_use_only_future(self):
        """Label at bar i must equal the sign of the forward return, computed independently."""
        bars = make_bars()
        threshold = 0.004
        m = FeatureBuilder().build(bars, horizon=6, label_cost_threshold=threshold)
        closes = [b.close for b in bars]
        for k in range(0, len(m.rows), 25):
            i = m.bar_indices[k]
            fwd = closes[i + 6] / closes[i] - 1
            assert m.labels[k] == (1 if fwd > threshold else 0)

    def test_btc_features_included_when_supplied(self):
        bars = make_bars()
        btc = [b.close * 300 for b in bars]
        m = FeatureBuilder().build(bars, btc_closes=btc, horizon=6)
        assert "btc_corr" in m.names and "btc_direction" in m.names