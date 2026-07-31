"""`cryptobot doctor` — diagnose why the dashboard looks empty.

Checks the things that actually break the UI: missing migrations (new tables),
empty candle store, no enabled pairs, unreachable Redis, missing API key.
Prints the exact command to fix each problem.
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from cryptobot.config import get_settings
from cryptobot.db.models import Base
from cryptobot.db.session import create_engine

OK = "  OK   "
BAD = " FAIL  "
WARN = " WARN  "


async def run_doctor() -> int:
    settings = get_settings()
    problems: list[str] = []
    print("=" * 72)                                          # noqa: T201
    print(" cryptobot doctor — why is the dashboard empty?")  # noqa: T201
    print("=" * 72)                                          # noqa: T201

    # ── database ─────────────────────────────────────────────────────
    engine = create_engine(settings.database_url)
    tables: set[str] = set()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            tables = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        print(f"{OK} database reachable")                     # noqa: T201
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD} database unreachable: {type(exc).__name__}")   # noqa: T201
        problems.append("Start the database:  docker compose up -d postgres redis")
        await engine.dispose()
        _summarise(problems)
        return 1

    expected = set(Base.metadata.tables)
    missing = sorted(expected - tables)
    if missing:
        print(f"{BAD} {len(missing)} database table(s) missing: "  # noqa: T201
              f"{', '.join(missing[:6])}{'…' if len(missing) > 6 else ''}")
        problems.append(
            'Create the new tables:\n'
            '     alembic revision --autogenerate -m "v2 v3 tables"\n'
            "     alembic upgrade head\n"
            "     then RESTART the API (uvicorn) so new routes load"
        )
    else:
        print(f"{OK} all {len(expected)} tables present")     # noqa: T201

    # ── data that the UI needs ───────────────────────────────────────
    if "candles" in tables:
        async with engine.connect() as conn:
            rows = (await conn.execute(text(
                "SELECT symbol, interval, count(*) c FROM candles "
                "GROUP BY symbol, interval ORDER BY c DESC LIMIT 5"
            ))).all()
        if rows:
            print(f"{OK} candle store: "                      # noqa: T201
                  + ", ".join(f"{r[0]} {r[1]}={r[2]}" for r in rows))
        else:
            print(f"{WARN} candle store is empty — price charts and the "  # noqa: T201
                  "strategy lab will be blank")
            problems.append(
                "Import history:  cryptobot import-history --symbol BTCUSDT "
                "--interval 1h --days 730")

    if "pair_settings" in tables:
        async with engine.connect() as conn:
            enabled = (await conn.execute(text(
                "SELECT symbol FROM pair_settings WHERE enabled = true"
            ))).all()
        if enabled:
            print(f"{OK} enabled pairs: "                     # noqa: T201
                  + ", ".join(r[0] for r in enabled))
        else:
            print(f"{WARN} no pairs enabled — the bot will not trade anything")  # noqa: T201
            problems.append("Enable pairs in the dashboard's Trading pairs tab "
                            "(defaults seed on first API start)")

    if "equity_snapshots" in tables:
        async with engine.connect() as conn:
            count = (await conn.execute(text("SELECT count(*) FROM equity_snapshots"))).scalar()
        if count:
            print(f"{OK} equity snapshots: {count}")           # noqa: T201
        else:
            print(f"{WARN} no equity snapshots — equity chart stays empty "  # noqa: T201
                  "until the trader runs")
            problems.append("Run the paper trader:  cryptobot trade")

    await engine.dispose()

    # ── redis ────────────────────────────────────────────────────────
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url)
        await client.ping()
        await client.aclose()
        print(f"{OK} redis reachable")                         # noqa: T201
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD} redis unreachable: {type(exc).__name__}")  # noqa: T201
        problems.append("Start redis:  docker compose up -d redis")

    # ── config ───────────────────────────────────────────────────────
    if settings.api_secret_key.get_secret_value() in ("", "dev-only-not-secret"):
        print(f"{BAD} API_SECRET_KEY is unset/default — the API refuses "  # noqa: T201
              "all dashboard calls (503)")
        problems.append("Set API_SECRET_KEY in .env to a long random string, and set "
                        "the SAME value as NEXT_PUBLIC_API_TOKEN in dashboard/.env.local")
    else:
        print(f"{OK} API_SECRET_KEY configured")               # noqa: T201

    if not settings.binance_testnet_api_key.get_secret_value():
        print(f"{WARN} no Binance Testnet key — account calls will fail")  # noqa: T201
    else:
        print(f"{OK} Binance testnet credentials present")     # noqa: T201

    if not settings.anthropic_api_key.get_secret_value():
        print(f"{WARN} no ANTHROPIC_API_KEY — AI assistant panel disabled "  # noqa: T201
              "(everything else works)")
    else:
        print(f"{OK} AI assistant configured")                 # noqa: T201

    print(f"{OK} execution mode: {settings.execution_mode} "   # noqa: T201
          f"(live trading: disabled)")
    _summarise(problems)
    return 1 if problems else 0


def _summarise(problems: list[str]) -> None:
    print("-" * 72)                                            # noqa: T201
    if not problems:
        print(" No problems found. If the dashboard still looks empty, restart "  # noqa: T201
              "uvicorn and hard-refresh the browser (Ctrl+Shift+R).")
        return
    print(f" {len(problems)} thing(s) to fix, in order:\n")     # noqa: T201
    for i, fix in enumerate(problems, start=1):
        print(f"  {i}. {fix}")                                  # noqa: T201
    print("\n Run from the backend/ folder with the venv active.")  # noqa: T201
    print("=" * 72)                                             # noqa: T201
