"""Structured JSON logging with mandatory secret redaction."""

from __future__ import annotations

import logging
import sys

import structlog

from cryptobot.security.redaction import RedactionFilter, redact


def _redact_event(_: object, __: str, event_dict: dict[str, object]) -> dict[str, object]:
    for key, value in event_dict.items():
        if isinstance(value, str):
            event_dict[key] = redact(value)
    return event_dict


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(message)s", stream=sys.stdout, level=getattr(logging, level.upper(), logging.INFO)
    )
    logging.getLogger().addFilter(RedactionFilter())

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,   # correlation IDs
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_event,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
