"""FastAPI application — Phase 2: health/status endpoints only.

Dashboard-facing trading endpoints arrive in Phase 4 with auth and
server-side confirmation tokens for high-risk controls.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, AsyncIterator

from fastapi import FastAPI, Response
from sqlalchemy import text

from cryptobot import __version__
from cryptobot.config import get_settings
from cryptobot.core.logging import get_logger, setup_logging
from cryptobot.db.session import create_engine, create_session_factory
from cryptobot.security.redaction import install_redaction

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from sqlalchemy import select

    from cryptobot.db.models import Account
    from cryptobot.runtime.controls import ControlService

    settings = get_settings()
    setup_logging(settings.log_level)
    install_redaction(settings.api_key, settings.api_secret, settings.api_secret_key)
    app.state.engine = create_engine(settings.database_url)
    app.state.sessions = create_session_factory(app.state.engine)
    app.state.controls = ControlService(settings.redis_url)
    app.state.started_at = datetime.now(UTC)

    async with app.state.sessions() as session:
        account = (await session.execute(
            select(Account).where(Account.mode == settings.mode.value)
        )).scalars().first()
        if account is None:
            account = Account(mode=settings.mode.value)
            session.add(account)
            await session.commit()
        app.state.account_id = account.id

    from pydantic import SecretStr

    from cryptobot.exchange.binance.client import BinanceRestClient
    from cryptobot.pairs.service import PairCatalogService, ensure_default_pairs

    venue_client = BinanceRestClient(
        base_url=settings.rest_base_url, api_key=settings.api_key,
        api_secret=settings.api_secret,
    )
    stats_client = BinanceRestClient(   # live PUBLIC market stats; no key used
        base_url=settings.endpoints.live_rest,
        api_key=SecretStr(""), api_secret=SecretStr(""),
    )
    app.state.pair_catalog = PairCatalogService(venue_client, stats_client)
    await ensure_default_pairs(app.state.sessions, settings.trading_pairs)

    # AI assistant — strictly optional; absent key just disables the panel
    app.state.chat_service = None
    if settings.anthropic_api_key.get_secret_value():
        from pathlib import Path

        from cryptobot.ai.budget import BudgetConfig
        from cryptobot.ai.knowledge import KnowledgeBase
        from cryptobot.ai.provider import AnthropicProvider, ModelPrice
        from cryptobot.ai.routing import RoutingConfig
        from cryptobot.ai.service import ChatService
        from cryptobot.ai.tools import build_registry

        install_redaction(settings.anthropic_api_key)
        kb = KnowledgeBase(docs_dir=Path("../docs") if Path("../docs").exists() else None)
        kb.load()
        prices = {   # USD per Mtok, verified 2026-08 (update via config on change)
            settings.ai_low_cost_model: ModelPrice(1.0, 5.0, 0.10),
            settings.ai_advanced_model: ModelPrice(2.0, 10.0, 0.20),
        }
        app.state.chat_service = ChatService(
            provider=AnthropicProvider(
                settings.anthropic_api_key.get_secret_value(), prices),
            registry=build_registry(app.state.sessions, app.state.pair_catalog, kb),
            routing=RoutingConfig(low_cost_model=settings.ai_low_cost_model,
                                  advanced_model=settings.ai_advanced_model),
            budget=BudgetConfig(max_cost_per_user_day_usd=settings.ai_daily_budget_usd,
                                monthly_budget_usd=settings.ai_monthly_budget_usd),
            operating_mode=f"{settings.mode.value}/{settings.execution_mode}",
        )
        logger.info("ai_assistant_enabled", low=settings.ai_low_cost_model,
                    advanced=settings.ai_advanced_model)

    logger.info("api_started", mode=settings.mode.value,
                execution_mode=settings.execution_mode, version=__version__)
    from cryptobot.config.versioning import record_config_change, settings_snapshot

    await record_config_change(
        app.state.sessions, "app", settings_snapshot(settings),
        change_note="api startup snapshot",
    )
    yield
    await venue_client.close()
    await stats_client.close()
    await app.state.controls.close()
    await app.state.engine.dispose()


app = FastAPI(title="CryptoBot", version=__version__, lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from cryptobot.api.routes import router as api_router  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    # Any localhost/127.0.0.1 origin on any port — the dashboard dev server
    # may not always get port 3000. The API itself binds to localhost only,
    # so this stays a single-operator, same-machine surface.
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics (FR-12.3)."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/v1/health")
async def health() -> dict[str, Any]:
    """Liveness + dependency checks. Never leaks configuration secrets."""
    checks: dict[str, str] = {}
    healthy = True

    try:
        async with app.state.sessions() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {type(exc).__name__}"
        healthy = False

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(get_settings().redis_url)
        await client.ping()
        await client.aclose()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {type(exc).__name__}"
        healthy = False

    return {"status": "ok" if healthy else "degraded", "checks": checks}


@app.get("/api/v1/status")
async def status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "mode": settings.mode.value,          # live is structurally gated
        "version": __version__,
        "started_at": app.state.started_at.isoformat(),
        "trading_pairs": settings.trading_pairs,
        "live_trading": "disabled",           # Phase 2: hard-coded truth
    }
