"""Notification service — Telegram + webhook channels with dedup/throttling.

Alerts never include secrets; messages pass through the redaction layer.
Failures to notify never crash the trading runtime (alerting is best-effort;
trading safety never depends on it).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

import httpx

from cryptobot.core.logging import get_logger
from cryptobot.security.redaction import redact

logger = get_logger(__name__)


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Notifier:
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    webhook_url: str = ""
    throttle_s: float = 300.0                      # same key at most once/5min
    _last_sent: dict[str, float] = field(default_factory=dict)

    async def send(self, key: str, message: str, severity: Severity = Severity.INFO) -> None:
        now = time.monotonic()
        if severity is not Severity.CRITICAL:      # critical alerts are never throttled
            last = self._last_sent.get(key, 0.0)
            if now - last < self.throttle_s:
                return
        self._last_sent[key] = now

        text = redact(f"[{severity.value.upper()}] CryptoBot: {message}")
        logger.info("notify", key=key, severity=severity.value)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                if self.telegram_bot_token and self.telegram_chat_id:
                    await client.post(
                        f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage",
                        json={"chat_id": self.telegram_chat_id, "text": text},
                    )
                if self.webhook_url:
                    await client.post(self.webhook_url, json={
                        "severity": severity.value, "key": key, "message": text,
                    })
        except httpx.HTTPError as exc:
            logger.warning("notify_failed", key=key, error=type(exc).__name__)
