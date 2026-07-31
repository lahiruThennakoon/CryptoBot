import pytest

from cryptobot.ml.splits import chronological_split, walk_forward_splits


class TestChronologicalSplit:
    def test_segments_are_ordered_and_disjoint(self):
        s = chronological_split(1000, embargo=24)
        assert s.train.stop <= s.validation.start
        assert s.validation.stop <= s.test.start
        assert set(s.train).isdisjoint(s.validation)
        assert set(s.validation).isdisjoint(s.test)

    def test_embargo_gap_exists(self):
        s = chronological_split(1000, embargo=24)
        assert s.validation.start - s.train.stop >= 24
        assert s.test.start - s.validation.stop >= 24

    def test_test_segment_reaches_end(self):
        s = chronological_split(1000)
        assert s.test.stop == 1000

    def test_too_few_rows_raises(self):
        with pytest.raises(ValueError):
            chronological_split(50, embargo=30)

    def test_bad_fractions_raise(self):
        with pytest.raises(ValueError):
            chronological_split(1000, train_frac=0.8, val_frac=0.3)


class TestWalkForward:
    def test_windows_disjoint_with_embargo(self):
        windows = walk_forward_splits(2000, train_size=500, test_size=200, embargo=24)
        assert windows
        for w in windows:
            assert w.test.start - w.train.stop >= 24
        for a, b in zip(windows, windows[1:], strict=False):
            assert b.train.start == a.train.start + 200  # steps by test size

    def test_never_exceeds_bounds(self):
        for w in walk_forward_splits(1234, 400, 150, 24):
            assert w.test.stop <= 1234