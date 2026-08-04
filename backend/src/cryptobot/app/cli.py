"""CLI entry points: `cryptobot collect` (market data), `cryptobot check` (connectivity)."""

from __future__ import annotations

import argparse
import asyncio
import sys

from cryptobot.config import get_settings
from cryptobot.core.logging import get_logger, setup_logging
from cryptobot.security.redaction import install_redaction

logger = get_logger(__name__)


def _bootstrap() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    install_redaction(settings.api_key, settings.api_secret, settings.api_secret_key)


async def _make_adapter() -> object:
    from cryptobot.exchange.binance.adapter import BinanceSpotAdapter
    from cryptobot.exchange.binance.client import BinanceRestClient
    from cryptobot.exchange.time_sync import TimeSync

    settings = get_settings()
    client = BinanceRestClient(
        base_url=settings.rest_base_url,
        api_key=settings.api_key,
        api_secret=settings.api_secret,
        time_sync=TimeSync(max_drift_ms=settings.max_clock_drift_ms),
    )
    return BinanceSpotAdapter(client, settings.ws_base_url)


async def _collect() -> None:
    from cryptobot.db.session import create_engine, create_session_factory
    from cryptobot.exchange.binance.adapter import BinanceSpotAdapter
    from cryptobot.market_data.service import MarketDataService, watch_staleness
    from cryptobot.market_data.staleness import StalenessMonitor

    settings = get_settings()
    adapter = await _make_adapter()
    assert isinstance(adapter, BinanceSpotAdapter)
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    monitor = StalenessMonitor(settings.market_data_stale_after_s)
    service = MarketDataService(
        adapter, sessions, settings.trading_pairs, settings.candle_intervals, monitor
    )
    watcher = asyncio.create_task(watch_staleness(monitor, settings.trading_pairs))
    try:
        await service.run()
    finally:
        watcher.cancel()
        await adapter.close()
        await engine.dispose()


async def _check() -> None:
    from cryptobot.exchange.binance.adapter import BinanceSpotAdapter

    settings = get_settings()
    logger.info("connectivity_check", mode=settings.mode.value, rest=settings.rest_base_url)
    adapter = await _make_adapter()
    assert isinstance(adapter, BinanceSpotAdapter)
    try:
        await adapter.verify_connectivity()
        rules = await adapter.get_exchange_rules()
        for symbol in settings.trading_pairs:
            r = rules.symbols.get(symbol)
            if r is None:
                logger.error("symbol_missing", symbol=symbol)
            else:
                logger.info(
                    "symbol_ok",
                    symbol=symbol,
                    status=r.status,
                    tick_size=str(r.tick_size),
                    step_size=str(r.step_size),
                    min_notional=str(r.min_notional),
                )
        logger.info("connectivity_check_passed")
    finally:
        await adapter.close()


async def _import_history(symbol: str, interval: str, days: int) -> None:
    from datetime import UTC, datetime, timedelta

    from pydantic import SecretStr

    from cryptobot.db.session import create_engine, create_session_factory
    from cryptobot.exchange.binance.adapter import BinanceSpotAdapter
    from cryptobot.exchange.binance.client import BinanceRestClient
    from cryptobot.importer.service import HistoricalImporter

    settings = get_settings()
    # Historical klines come from the LIVE public market-data API: the
    # testnet resets ~monthly and holds only weeks of history, which is
    # useless for backtesting. This is public read-only data — no API key
    # is sent or required, and trading still happens only on testnet/paper.
    client = BinanceRestClient(
        base_url=settings.endpoints.live_rest,
        api_key=SecretStr(""),
        api_secret=SecretStr(""),
    )
    adapter = BinanceSpotAdapter(client, settings.endpoints.live_ws)
    logger.info("importing_from_live_public_data", note="testnet history is too short")
    engine = create_engine(settings.database_url)
    try:
        importer = HistoricalImporter(adapter, create_session_factory(engine))
        count, issues = await importer.import_range(
            symbol, interval, start=datetime.now(UTC) - timedelta(days=days)
        )
        logger.info("import_done", symbol=symbol, interval=interval,
                    candles=count, issues=issues.summary(), critical=issues.critical)
    finally:
        await adapter.close()
        await engine.dispose()


async def _backtest(args: argparse.Namespace) -> None:
    from cryptobot.backtest.engine import BacktestEngine
    from cryptobot.backtest.loaders import load_csv, load_db
    from cryptobot.backtest.metrics import compute_report, format_report
    from cryptobot.backtest.walkforward import sensitivity_analysis, walk_forward
    from cryptobot.costs.model import CostModel
    from cryptobot.strategies import STRATEGY_REGISTRY

    strategy_cls = STRATEGY_REGISTRY.get(args.strategy)
    if strategy_cls is None:
        logger.error("unknown_strategy", requested=args.strategy,
                     available=sorted(STRATEGY_REGISTRY))
        sys.exit(2)

    if args.csv:
        bars = load_csv(args.csv)
    else:
        from cryptobot.db.session import create_engine, create_session_factory

        settings = get_settings()
        engine = create_engine(settings.database_url)
        try:
            bars = await load_db(create_session_factory(engine), args.symbol, args.interval)
        finally:
            await engine.dispose()
    if not bars:
        logger.error("no_candles", symbol=args.symbol, interval=args.interval)
        sys.exit(2)

    costs = CostModel(taker_fee=args.fee, slippage=args.slippage)
    bt = BacktestEngine(costs=costs, initial_equity=args.equity)
    report = compute_report(bt.run(bars, strategy_cls()), args.interval)
    print(format_report(report, f"{args.strategy} · {args.symbol} · {args.interval} · {len(bars)} bars"))  # noqa: T201

    if args.walk_forward:
        wf = walk_forward(bars, strategy_cls, train_bars=args.wf_train, test_bars=args.wf_test,
                          timeframe=args.interval, costs=costs, initial_equity=args.equity)
        print(wf.summary())  # noqa: T201

    if args.sensitivity:
        print("Sensitivity (fee× / slippage× → net %):")  # noqa: T201
        for (fm, sm), rep in sensitivity_analysis(
            bars, strategy_cls, timeframe=args.interval, base_costs=costs,
            initial_equity=args.equity,
        ).items():
            print(f"  {fm:>3.1f}x / {sm:>3.1f}x  →  {rep.net_return_pct:+7.2f}%  "  # noqa: T201
                  f"(trades {rep.n_trades}, dd {rep.max_drawdown_pct:.1f}%)")


async def _trade(enabled: list[str] | None, demo: bool = False) -> None:
    from sqlalchemy import select

    from cryptobot.db.models import Account
    from cryptobot.db.session import create_engine, create_session_factory
    from cryptobot.exchange.binance.adapter import BinanceSpotAdapter
    from cryptobot.runtime.service import PaperTradingService

    settings = get_settings()
    if settings.mode.value == "live":
        logger.critical("live_trading_not_implemented",
                        detail="Phase 6 gate not passed; refusing to start")
        sys.exit(3)
    adapter = await _make_adapter()
    assert isinstance(adapter, BinanceSpotAdapter)
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    async with sessions() as session:
        account = (await session.execute(
            select(Account).where(Account.mode == settings.mode.value)
        )).scalars().first()
        if account is None:
            account = Account(mode=settings.mode.value)
            session.add(account)
            await session.commit()
        account_id = account.id
    if demo:
        print("=" * 66)                                                    # noqa: T201
        print(" DEMO MODE: eager 1-minute trading to demonstrate the pipeline.")  # noqa: T201
        print(" No edge is claimed; expect small simulated losses to costs.")     # noqa: T201
        print(" Demo results are NEVER evidence for the graduation criteria.")    # noqa: T201
        print("=" * 66)                                                    # noqa: T201
    service = PaperTradingService(settings, adapter, sessions, account_id, enabled,
                                  demo_mode=demo)
    try:
        await service.run()
    finally:
        await adapter.close()
        await engine.dispose()


async def _ml_train(args: argparse.Namespace) -> None:
    from cryptobot.backtest.loaders import load_db
    from cryptobot.db.session import create_engine, create_session_factory
    from cryptobot.ml.registry import ModelRegistry
    from cryptobot.ml.training import run_training

    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        sessions = create_session_factory(engine)
        bars = await load_db(sessions, args.symbol, args.interval)
        btc_closes = None
        if args.symbol != "BTCUSDT":
            btc_bars = await load_db(sessions, "BTCUSDT", args.interval)
            if len(btc_bars) == len(bars):
                btc_closes = [b.close for b in btc_bars]
    finally:
        await engine.dispose()
    if not bars:
        logger.error("no_candles", symbol=args.symbol, interval=args.interval)
        sys.exit(2)

    result = run_training(
        bars, ModelRegistry(args.registry), horizon=args.horizon,
        seed=args.seed, btc_closes=btc_closes,
        model_name=f"direction_{args.symbol}_{args.interval}",
    )
    print(f"winner: {result.winner_name}")                                # noqa: T201
    for name, ev in result.validation.items():
        print(f"  {name:<22} val AUC {ev.auc:.4f}  brier {ev.brier:.4f}  "  # noqa: T201
              f"expectancy {ev.expectancy_after_costs}")
    assert result.test is not None
    print(f"test (untouched): AUC {result.test.auc:.4f}  "                # noqa: T201
          f"expectancy {result.test.expectancy_after_costs}  signals {result.test.n_signals}")
    print(result.promotion_summary)                                       # noqa: T201
    print("note: promotion means the model beat predefined gates on historical "  # noqa: T201
          "data — it is not a guarantee of future performance.")


async def _readiness() -> None:
    from pathlib import Path

    from cryptobot.db.session import create_engine, create_session_factory
    from cryptobot.readiness.checks import evaluate, verdict
    from cryptobot.readiness.service import (
        format_results,
        gather_db_facts,
        gather_static_facts,
    )

    settings = get_settings()
    facts = gather_static_facts(settings, Path.cwd().parent
                                if Path.cwd().name == "backend" else Path.cwd())
    engine = create_engine(settings.database_url)
    try:
        facts = await gather_db_facts(facts, create_session_factory(engine), settings.redis_url)
    finally:
        await engine.dispose()

    results = evaluate(facts)
    ready, summary = verdict(results)
    print(format_results(results))   # noqa: T201
    print(f"\n {summary}")           # noqa: T201
    print(" This tool cannot enable live trading. Final approval is a manual, "  # noqa: T201
          "multi-step decision documented in docs/live-readiness/approval.md.")
    sys.exit(0 if ready else 1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="cryptobot")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("collect", help="Run the market-data collector")
    sub.add_parser("check", help="Verify exchange connectivity, time sync and permissions")

    trade = sub.add_parser("trade", help="Run the paper-trading runtime (never live)")
    trade.add_argument("--strategies", nargs="*", default=None,
                       help="Enabled strategies (default: all registered)")
    trade.add_argument("--demo", action="store_true",
                       help="DEMO: trade eagerly on 1m candles to show the pipeline "
                            "working. No edge; slowly loses simulated money to costs. "
                            "Never evidence.")

    sub.add_parser("readiness", help="Run the live-readiness review (never enables live)")
    sub.add_parser("doctor", help="Diagnose why the dashboard looks empty and print fixes")

    ml = sub.add_parser("ml-train", help="Train candidate models with promotion gating")
    ml.add_argument("--symbol", default="BTCUSDT")
    ml.add_argument("--interval", default="1h")
    ml.add_argument("--horizon", type=int, default=6)
    ml.add_argument("--seed", type=int, default=42)
    ml.add_argument("--registry", default="./model_registry")

    imp = sub.add_parser("import-history", help="Import historical klines with validation")
    imp.add_argument("--symbol", default="BTCUSDT")
    imp.add_argument("--interval", default="1h")
    imp.add_argument("--days", type=int, default=730)

    bt = sub.add_parser("backtest", help="Run an event-driven backtest")
    bt.add_argument("--strategy", required=True)
    bt.add_argument("--symbol", default="BTCUSDT")
    bt.add_argument("--interval", default="1h")
    bt.add_argument("--csv", help="Load candles from CSV instead of the database")
    bt.add_argument("--equity", type=float, default=10_000.0)
    bt.add_argument("--fee", type=float, default=0.001)
    bt.add_argument("--slippage", type=float, default=0.0005)
    bt.add_argument("--walk-forward", action="store_true")
    bt.add_argument("--wf-train", type=int, default=2000)
    bt.add_argument("--wf-test", type=int, default=500)
    bt.add_argument("--sensitivity", action="store_true")

    args = parser.parse_args()
    _bootstrap()
    from cryptobot.exchange.errors import ClockDriftError, ExchangeError

    try:
        if args.command == "collect":
            asyncio.run(_collect())
        elif args.command == "check":
            asyncio.run(_check())
        elif args.command == "trade":
            asyncio.run(_trade(args.strategies, demo=getattr(args, "demo", False)))
        elif args.command == "ml-train":
            asyncio.run(_ml_train(args))
        elif args.command == "readiness":
            asyncio.run(_readiness())
        elif args.command == "doctor":
            from cryptobot.app.doctor import run_doctor

            sys.exit(asyncio.run(run_doctor()))
        elif args.command == "import-history":
            asyncio.run(_import_history(args.symbol, args.interval, args.days))
        elif args.command == "backtest":
            asyncio.run(_backtest(args))
    except KeyboardInterrupt:
        logger.info("shutdown_requested")
        sys.exit(0)
    except ClockDriftError as exc:
        print(f"\nCLOCK DRIFT: {exc}")                                     # noqa: T201
        print("Your system clock disagrees with Binance server time. "     # noqa: T201
              "Signed requests are blocked as a safety measure (fail closed).")
        print("Fix on Windows: Settings → Time & language → Date & time "
              "→ 'Sync now', then re-run this command.")
        print("Fix on Linux/EC2: sudo timedatectl set-ntp true && "
              "sudo systemctl restart systemd-timesyncd")
        sys.exit(1)
    except ExchangeError as exc:
        print(f"\nEXCHANGE ERROR: {exc}")                                  # noqa: T201
        print("Check your API keys in .env and your network, then re-run.")  # noqa: T201
        sys.exit(1)


if __name__ == "__main__":
    main()
