"""Server-time synchronization. Signed requests fail closed on excess drift."""

from __future__ import annotations

import time
from dataclasses import dataclass

from cryptobot.exchange.errors import ClockDriftError


@dataclass
class TimeSync:
    max_drift_ms: int = 1000
    _offset_ms: float = 0.0
    _last_sync_monotonic: float | None = None
    resync_interval_s: float = 300.0

    def update(self, server_time_ms: int, rtt_ms: float = 0.0) -> None:
        """Record offset = server − local, compensating half the round-trip."""
        local_ms = time.time() * 1000
        self._offset_ms = server_time_ms + rtt_ms / 2 - local_ms
        self._last_sync_monotonic = time.monotonic()

    @property
    def offset_ms(self) -> float:
        return self._offset_ms

    @property
    def is_synced(self) -> bool:
        return (
            self._last_sync_monotonic is not None
            and time.monotonic() - self._last_sync_monotonic < self.resync_interval_s
        )

    def timestamp_ms(self) -> int:
        """Timestamp for signed requests. Raises if drift exceeds threshold."""
        if self._last_sync_monotonic is None:
            raise ClockDriftError("Server time never synchronized")
        if abs(self._offset_ms) > self.max_drift_ms:
            raise ClockDriftError(
                f"Clock drift {self._offset_ms:.0f}ms exceeds {self.max_drift_ms}ms — "
                "signed requests blocked (fail closed)"
            )
        return int(time.time() * 1000 + self._offset_ms)
