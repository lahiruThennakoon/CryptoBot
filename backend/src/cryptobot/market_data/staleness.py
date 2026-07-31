"""Staleness monitoring — the risk engine blocks entries on stale pairs."""

from __future__ import annotations

from datetime import UTC, datetime


class StalenessMonitor:
    def __init__(self, stale_after_s: float) -> None:
        self._stale_after_s = stale_after_s
        self._last_seen: dict[str, datetime] = {}

    def touch(self, symbol: str, at: datetime | None = None) -> None:
        self._last_seen[symbol] = at or datetime.now(UTC)

    def age_s(self, symbol: str) -> float | None:
        seen = self._last_seen.get(symbol)
        if seen is None:
            return None
        return (datetime.now(UTC) - seen).total_seconds()

    def is_stale(self, symbol: str) -> bool:
        age = self.age_s(symbol)
        return age is None or age > self._stale_after_s

    def stale_symbols(self, symbols: list[str]) -> list[str]:
        return [s for s in symbols if self.is_stale(s)]

    def all_healthy(self, symbols: list[str]) -> bool:
        return not self.stale_symbols(symbols)
