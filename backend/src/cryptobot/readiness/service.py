"""Fact gathering for the readiness checker (I/O lives here, logic in checks.py)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from cryptobot.config import Settings
from cryptobot.readiness.checks import Facts


def gather_static_facts(settings: Settings, repo_root: Path) -> Facts:
    facts = Facts(mode=settings.mode.value)
    facts.api_secret_is_default = settings.api_secret_key.get_secret_value() in (
        "", "dev-only-not-secret",
    )
    facts.testnet_keys_configured = bool(settings.binance_testnet_api_key.get_secret_value())
    facts.live_keys_configured = bool(settings.binance_live_api_key.get_secret_value())
    facts.confirm_phrase_set = bool(settings.confirm_live_trading)

    gitignore = repo_root / ".gitignore"
    facts.gitignore_covers_env = gitignore.exists() and ".env" in gitignore.read_text()

    env_example = repo_root / ".env.example"
    if env_example.exists():
        facts.env_example_has_secrets = _looks_secret(env_example.read_text())
    return facts


def _looks_secret(text: str) -> bool:
    """Heuristic: any assignment whose value looks like a real credential."""
    placeholders = ("your_", "change_me", "generate_", "same_value", "placeholder", "")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        value = line.split("=", 1)[1].strip()
        if value.lower().startswith(placeholders) or len(value) < 20:
            continue
        if any(c.isalnum() for c in value) and not value.lower().startswith("postgresql"):
            return True
    return False


async def gather_db_facts(facts: Facts, sessions: object, redis_url: str) -> Facts:
    from cryptobot.db.models import DrillAckRow, EquitySnapshot, PositionRow

    try:
        async with sessions() as session:  # type: ignore[operator]
            first_snap = (await session.execute(
                select(func.min(EquitySnapshot.taken_at))
            )).scalar_one_or_none()
            if first_snap is not None:
                facts.paper_trading_days = (datetime.now(UTC) - first_snap).days
            facts.closed_paper_trades = (await session.execute(
                select(func.count()).select_from(PositionRow)
                .where(PositionRow.status == "closed")
            )).scalar_one()
            pnl = (await session.execute(
                select(func.sum(PositionRow.realized_pnl))
                .where(PositionRow.status == "closed")
            )).scalar_one_or_none()
            facts.paper_net_pnl = float(pnl) if pnl is not None else None

            rows = (await session.execute(
                select(EquitySnapshot.equity).order_by(EquitySnapshot.taken_at)
            )).scalars().all()
            if rows:
                peak, max_dd = float(rows[0]), 0.0
                for r in rows:
                    v = float(r)
                    peak = max(peak, v)
                    if peak > 0:
                        max_dd = max(max_dd, (peak - v) / peak * 100)
                facts.max_drawdown_pct = max_dd

            # operator drill acknowledgements (recorded in the dashboard)
            try:
                acks = (await session.execute(select(DrillAckRow))).scalars().all()
                facts.manual_drills = {
                    r.drill_name: bool(r.acknowledged) for r in acks
                }
            except Exception:  # noqa: BLE001 — table may predate this feature
                facts.manual_drills = {}
        facts.db_reachable = True
    except Exception:  # noqa: BLE001
        facts.db_reachable = False

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(redis_url)
        await client.ping()
        await client.aclose()
        facts.redis_reachable = True
    except Exception:  # noqa: BLE001
        facts.redis_reachable = False
    return facts


def format_results(results: list[object]) -> str:
    from cryptobot.readiness.checks import CheckResult

    lines = ["=" * 72, " Live-readiness review — automated checks", "=" * 72]
    category = None
    for r in results:
        assert isinstance(r, CheckResult)
        if r.category != category:
            category = r.category
            lines.append(f"\n [{category.upper()}]")
        lines.append(f"   {r.status.value:<7} {r.name}" + (f" — {r.detail}" if r.detail else ""))
    lines.append("=" * 72)
    return "\n".join(lines)
