"""Chronological data splits with embargo gaps.

The embargo (≥ label horizon) between segments prevents label leakage across
boundaries: a label at the end of train looks `horizon` bars forward, which
would otherwise overlap the start of validation. The test segment is
untouched: it must never be used for any selection decision.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Split:
    train: range
    validation: range
    test: range          # UNTOUCHED — final evaluation only


def chronological_split(
    n_rows: int,
    train_frac: float = 0.6,
    val_frac: float = 0.2,
    embargo: int = 24,
) -> Split:
    if not 0 < train_frac < 1 or not 0 < val_frac < 1 or train_frac + val_frac >= 1:
        raise ValueError("fractions must be in (0,1) and sum below 1")
    train_end = int(n_rows * train_frac)
    val_start = train_end + embargo
    val_end = val_start + int(n_rows * val_frac)
    test_start = val_end + embargo
    if test_start >= n_rows:
        raise ValueError(f"not enough rows ({n_rows}) for split with embargo {embargo}")
    return Split(
        train=range(0, train_end),
        validation=range(val_start, val_end),
        test=range(test_start, n_rows),
    )


@dataclass(frozen=True)
class WalkWindow:
    train: range
    test: range


def walk_forward_splits(
    n_rows: int, train_size: int, test_size: int, embargo: int = 24
) -> list[WalkWindow]:
    windows: list[WalkWindow] = []
    start = 0
    while start + train_size + embargo + test_size <= n_rows:
        train_end = start + train_size
        test_start = train_end + embargo
        windows.append(WalkWindow(
            train=range(start, train_end),
            test=range(test_start, test_start + test_size),
        ))
        start += test_size
    return windows
