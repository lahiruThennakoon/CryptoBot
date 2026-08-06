"""Persist configuration changes to config_versions (NFR-8)."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import func, select

from cryptobot.db.models import ConfigVersion
from cryptobot.db.session import SessionFactory


def _hash_content(content: dict) -> str:
    payload = json.dumps(content, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


async def record_config_change(
    sessions: SessionFactory,
    scope: str,
    content: dict,
    change_note: str = "",
    created_by: str = "system",
) -> int:
    """Append a config version row; returns the new version number."""
    content_hash = _hash_content(content)
    async with sessions() as session:
        current = (await session.execute(
            select(func.max(ConfigVersion.version))
        )).scalar() or 0
        version = current + 1
        session.add(ConfigVersion(
            version=version,
            scope=scope,
            content=content,
            content_hash=content_hash,
            created_by=created_by,
            change_note=change_note,
        ))
        await session.commit()
    return version


def settings_snapshot(settings: object) -> dict:
    """Non-secret subset of Settings suitable for versioning."""
    from cryptobot.config.settings import Settings

    if not isinstance(settings, Settings):
        return {}
    return {
        "mode": settings.mode.value,
        "execution_mode": settings.execution_mode,
        "trading_pairs": settings.trading_pairs,
        "candle_intervals": settings.candle_intervals,
        "entry_order_style": settings.entry_order_style,
        "fixed_entry_notional_usd": str(settings.fixed_entry_notional_usd),
        "paper_starting_balance_quote": str(settings.paper_starting_balance_quote),
        "market_data_stale_after_s": settings.market_data_stale_after_s,
        "ws_include_trades": settings.ws_include_trades,
        "ws_include_depth": settings.ws_include_depth,
        "small_account_guardrails": settings.small_account_guardrails,
        "learning_mode": settings.learning_mode,
    }
