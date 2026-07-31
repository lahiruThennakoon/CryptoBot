"""Secret redaction for logs and exception traces.

Two layers of defense:
1. Pattern-based scrubbing of known secret shapes (signatures, API-key query
   params and headers) — catches secrets embedded in URLs/messages.
2. Registered-secret scrubbing — exact-match removal of every secret value
   the process has loaded, regardless of context.
"""

from __future__ import annotations

import logging
import re
from typing import Any

_REDACTED = "***REDACTED***"

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(signature=)[0-9a-fA-F]{16,}"),
    re.compile(r"(X-MBX-APIKEY['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9]{16,}"),
    re.compile(r"((?:api[_-]?key|api[_-]?secret|secret[_-]?key|listenKey)['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9\-_]{16,}", re.IGNORECASE),
]

_registered_secrets: set[str] = set()


def register_secret(value: str) -> None:
    """Register a live secret value for exact-match scrubbing."""
    if value and len(value) >= 8:
        _registered_secrets.add(value)


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(rf"\g<1>{_REDACTED}", text)
    for secret in _registered_secrets:
        if secret in text:
            text = text.replace(secret, _REDACTED)
    return text


class RedactionFilter(logging.Filter):
    """Logging filter that scrubs secrets from messages, args and tracebacks."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(
                redact(a) if isinstance(a, str) else a
                for a in (record.args if isinstance(record.args, tuple) else (record.args,))
            )
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def install_redaction(*secrets: Any) -> None:
    """Register secrets and attach the filter to the root logger AND all of
    its handlers.

    Handler-level attachment is essential: records from third-party loggers
    (httpx, websockets, ...) propagate to root handlers WITHOUT passing
    through root-logger filters — only handler filters see them. Without
    this, httpx would log signed request URLs verbatim.
    """
    for s in secrets:
        value = s.get_secret_value() if hasattr(s, "get_secret_value") else str(s)
        register_secret(value)
    root = logging.getLogger()
    redaction = RedactionFilter()
    if not any(isinstance(f, RedactionFilter) for f in root.filters):
        root.addFilter(redaction)
    for handler in root.handlers:
        if not any(isinstance(f, RedactionFilter) for f in handler.filters):
            handler.addFilter(redaction)
