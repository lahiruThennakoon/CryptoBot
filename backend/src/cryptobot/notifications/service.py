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

from typing import Any

from cryptobot.config.settings import Settings
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


def notifier_from_settings(settings: Settings) -> Notifier:
    return Notifier(
        telegram_bot_token=settings.telegram_bot_token.get_secret_value(),
        telegram_chat_id=settings.telegram_chat_id,
        webhook_url=settings.alert_webhook_url,
    )


def format_daily_report(report: dict[str, Any]) -> str:
    """Plain-text EOD summary for Telegram/webhook (no secrets)."""
    report_for = report.get("report_for", "?")
    equity = report.get("equity", 0)
    cash = report.get("cash", 0)
    pnl = report.get("daily_realized_pnl", 0)
    trades = report.get("trades_today", 0)
    open_pos = report.get("open_positions", 0)
    near = report.get("near_misses") or []
    halted = report.get("halted", False)
    halt_reason = report.get("halt_reason") or ""

    lines = [
        f"Daily report — {report_for} (UTC)",
        "",
        f"Equity: ${float(equity):,.2f}",
        f"Cash: ${float(cash):,.2f}",
        f"Daily PnL: ${float(pnl):+,.2f}",
        f"Trades today: {trades}",
        f"Open positions: {open_pos}",
        f"Near-misses: {len(near)}",
    ]
    if halted:
        lines.append(f"Status: HALTED ({halt_reason or 'unknown'})")
    else:
        lines.append("Status: OK")
    if near:
        lines.append("")
        lines.append("Recent near-misses:")
        for nm in near[:5]:
            sym = nm.get("symbol", "?")
            code = nm.get("code", "?")
            conf = nm.get("confidence", 0)
            lines.append(f"  • {sym} — {code} (conf {float(conf):.2f})")
    return "\n".join(lines)
