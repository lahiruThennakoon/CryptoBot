"""Exchange error hierarchy. Errors carry no secret material."""

from __future__ import annotations


class ExchangeError(Exception):
    """Base for all exchange-layer errors."""


class ExchangeConnectionError(ExchangeError):
    """Network-level failure. Order state may be UNKNOWN — reconcile before retry."""


class RateLimitExceeded(ExchangeError):
    def __init__(self, retry_after_s: float | None = None) -> None:
        self.retry_after_s = retry_after_s
        super().__init__(f"Rate limit exceeded (retry after {retry_after_s}s)")


class IpBanned(ExchangeError):
    """HTTP 418 — client kept sending after 429s. Hard stop."""


class ExchangeApiError(ExchangeError):
    def __init__(self, status_code: int, code: int | None, message: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(f"Binance API error {status_code} (code={code}): {message}")


class OrderRejected(ExchangeApiError):
    pass


class FilterViolation(ExchangeError):
    """Order fails local symbol-filter validation. Never sent to the exchange."""


class ClockDriftError(ExchangeError):
    """Local/server clock drift exceeds threshold. Signed calls blocked (fail closed)."""


class StaleDataError(ExchangeError):
    """Market data older than the staleness threshold."""
