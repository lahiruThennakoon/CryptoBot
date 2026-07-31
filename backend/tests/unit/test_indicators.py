import math

from cryptobot.features.indicators import (
    atr,
    bollinger,
    ema,
    macd,
    returns,
    rolling_max,
    rsi,
    sma,
)


class TestSma:
    def test_values(self):
        assert sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]

    def test_warmup_is_none(self):
        assert sma([1.0] * 10, 5)[:4] == [None] * 4


class TestEma:
    def test_constant_series(self):
        out = ema([5.0] * 20, 10)
        assert out[-1] is not None and math.isclose(out[-1], 5.0)

    def test_reacts_to_change(self):
        out = ema([1.0] * 20 + [10.0] * 5, 10)
        assert out[-1] is not None and 1.0 < out[-1] < 10.0


class TestRsi:
    def test_all_gains_is_100(self):
        out = rsi(list(range(1, 40)), 14)
        assert out[-1] == 100.0

    def test_bounded(self):
        vals = [100 + ((-1) ** i) * (i % 7) for i in range(60)]
        for v in rsi(vals, 14):
            if v is not None:
                assert 0.0 <= v <= 100.0


class TestAtr:
    def test_constant_range(self):
        h, low, c = [101.0] * 40, [99.0] * 40, [100.0] * 40
        out = atr(h, low, c, 14)
        assert out[-1] is not None and math.isclose(out[-1], 2.0, rel_tol=1e-9)


class TestMacdBollinger:
    def test_macd_shapes(self):
        line, sig, hist = macd([float(i) for i in range(1, 100)])
        assert len(line) == len(sig) == len(hist) == 99
        assert line[-1] is not None and sig[-1] is not None

    def test_bollinger_bands_contain_mid(self):
        vals = [100 + (i % 5) for i in range(50)]
        mid, up, lo, pct = bollinger(vals, 20)
        assert up[-1] >= mid[-1] >= lo[-1]
        assert 0.0 <= pct[-1] <= 1.0


class TestMisc:
    def test_returns(self):
        out = returns([100.0, 110.0, 99.0], 1)
        assert out[0] is None and math.isclose(out[1], 0.10)

    def test_rolling_max(self):
        assert rolling_max([1, 5, 3, 2, 8], 3) == [None, None, 5, 5, 8]


class TestCausality:
    """Indicators must not change past values when future data is appended."""

    def test_indicators_are_causal(self):
        base = [100 + math.sin(i / 5) * 10 for i in range(100)]
        extended = base + [1e6] * 20  # absurd future values
        for fn in (lambda v: sma(v, 10), lambda v: ema(v, 10), lambda v: rsi(v, 14)):
            assert fn(base) == fn(extended)[:100]