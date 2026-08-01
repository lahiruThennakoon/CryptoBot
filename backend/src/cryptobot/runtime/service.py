"""Production wiring: TradingRuntime + Binance stream + PostgreSQL persistence.

Run via: `cryptobot trade` (paper mode).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from cryptobot.backtest.loaders import load_db
from cryptobot.config import Settings
from cryptobot.core.logging import get_logger
from cryptobot.costs.model import CostModel
from cryptobot.db.models import (
    DailyReportRow,
    EquitySnapshot,
    FillRow,
    OrderRow,
    PositionRow,
    RiskEventRow,
    SignalRow,
)
from cryptobot.db.session import SessionFactory
from cryptobot.exchange.binance.adapter import BinanceSpotAdapter
from cryptobot.exchange.models import MarketEventType
from cryptobot.notifications.service import Notifier
from cryptobot.paper.account import PaperAccount
from cryptobot.paper.broker import PaperBroker
from cryptobot.risk.engine import BasicRiskEngine
from cryptobot.runtime.controls import ControlService
from cryptobot.runtime.engine import RuntimeEvents, TradingRuntime
from cryptobot.strategies import STRATEGY_REGISTRY

logger = get_logger(__name__)


class PaperTradingService:
    def __init__(
        self,
        settings: Settings,
        adapter: BinanceSpotAdapter,
        sessions: SessionFactory,
        account_id: object,
        enabled_strategies: list[str] | None = None,
        demo_mode: bool = False,
    ) -> None:
        self._settings = settings
        self._adapter = adapter
        self._sessions = sessions
        self._account_id = account_id
        self._controls = ControlService(settings.redis_url)
        self._pending: list[object] = []

        account = PaperAccount.with_starting_balance(
            settings.paper_quote_asset, settings.paper_starting_balance_quote
        )
        if demo_mode:
            from cryptobot.strategies.demo_pulse import DEMO_STRATEGIES

            strategy_names = list(DEMO_STRATEGIES)
            strategies: list = [cls() for cls in DEMO_STRATEGIES.values()]
            logger.warning(
                "DEMO_MODE_ACTIVE",
                detail="demo_pulse trades eagerly on 1m candles through the full "
                       "pipeline. It has NO edge and will slowly lose simulated "
                       "money to costs. Never use its results as evidence.",
            )
        else:
            strategy_names = enabled_strategies or list(STRATEGY_REGISTRY)
            strategies = [STRATEGY_REGISTRY[name]() for name in strategy_names]

        # Execution policy + cost model reflecting it (maker entries are cheaper)
        from cryptobot.decision.scoring import DecisionScorer, Gates
        from cryptobot.execution.policy import (
            ExecutionPolicy,
            OrderStyle,
            effective_costs,
        )
        from cryptobot.pairs.service import enabled_symbols
        from cryptobot.risk.engine import RiskConfig

        if demo_mode:
            policy = ExecutionPolicy(entry_style=OrderStyle.MARKET)
            demo_gates = Gates(buy_threshold=0.2, strong_buy_threshold=0.45)
            risk = BasicRiskEngine(RiskConfig(min_confidence=0.4))
        else:
            policy = ExecutionPolicy(
                entry_style=OrderStyle.MAKER_LIMIT
                if settings.entry_order_style == "maker_limit" else OrderStyle.MARKET,
                limit_offset_bps=settings.maker_limit_offset_bps,
                ttl_bars=settings.maker_ttl_bars,
                bnb_discount=settings.bnb_fee_discount,
            )
            demo_gates = None
            risk = BasicRiskEngine()

        costs = effective_costs(CostModel(), policy)

        # Decision scorer gets its OWN strategy instances (stateful strategies
        # must not share state between scoring and trading paths).
        if demo_mode:
            from cryptobot.strategies.demo_pulse import DEMO_STRATEGIES as _DS

            scorer = DecisionScorer(
                [cls() for cls in _DS.values()], costs=costs, gates=demo_gates,
            )
        else:
            scorer = DecisionScorer(
                [STRATEGY_REGISTRY[n]() for n in strategy_names], costs=costs,
            )

        # Live cost discovery: real commission rates + real spread + depth-based
        # slippage, refreshed per request with caching. Falls back conservatively.
        from cryptobot.costs.live import FeeService, build_live_cost_model

        self._fee_service = FeeService(adapter._client)  # noqa: SLF001 — same package boundary

        async def _live_costs(symbol: str, intended_notional: float) -> object:
            fees = await self._fee_service.get(symbol)
            book = None
            try:
                book = await adapter.get_order_book(symbol, limit=20)
            except Exception:  # noqa: BLE001 — spread/slippage fall back to assumptions
                pass
            return build_live_cost_model(
                symbol, fees, book, intended_notional,
                base=effective_costs(CostModel(), policy),
            )

        self._live_costs = _live_costs

        async def _enabled() -> set[str]:
            return await enabled_symbols(sessions)

        from cryptobot.ml.inference import DeployedModelPredictor
        from cryptobot.runtime.market_context import build_market_context

        ml = DeployedModelPredictor(settings.model_registry_dir)
        strategy_interval = strategies[0].spec.timeframe if strategies else "1h"

        self.runtime = TradingRuntime(
            broker=PaperBroker(account, costs),  # swapped for TestnetBroker in run()
            strategies=strategies,
            risk=risk,
            costs=costs,
            execution_policy=policy,
            live_costs=_live_costs,
            quote_asset=settings.paper_quote_asset,
            events=self._make_events(),
            notifier=Notifier(),  # channels configured via env in _bootstrap
            controls_state=self._controls.state,
            controls=self._controls,
            enabled_pairs=_enabled,
            decision_scorer=scorer,
            analysis_only=settings.execution_mode == "analysis",
            loss_cooldown_hours=0.03 if demo_mode else 1.0,   # ~2 min in demo
            stale_after_s=settings.market_data_stale_after_s,
        )

        async def _market_context(symbol: str, bars: list) -> object:
            rt = self.runtime
            equity = rt._risk_state.equity or float(settings.paper_starting_balance_quote)
            intended_notional = equity * rt.risk.config.max_position_pct
            btc_history = rt._history.get(("BTCUSDT", strategy_interval), [])
            return await build_market_context(
                symbol,
                bars,
                has_open_position=symbol in rt._positions,
                data_fresh=not rt._stale(),
                intended_notional=intended_notional,
                live_costs=_live_costs,
                ml_predictor=ml.probability_up,
                btc_bars=btc_history if symbol != "BTCUSDT" else None,
            )

        self.runtime.market_context_builder = _market_context
        self._current_day: str | None = None

    # ── persistence hooks (buffered; flushed on a timer) ─────────────
    def _make_events(self) -> RuntimeEvents:
        events = RuntimeEvents()
        events.on_signal = lambda *a: self._pending.append(("signal", a))
        events.on_execution = lambda *a: self._pending.append(("execution", a))
        events.on_position_open = lambda *a: self._pending.append(("pos_open", a))
        events.on_position_close = lambda *a: self._pending.append(("pos_close", a))
        events.on_risk_event = lambda *a: self._pending.append(("risk", a))
        events.on_equity = lambda *a: self._pending.append(("equity", a))
        events.on_decision = lambda *a: self._pending.append(("decision", a))
        return events

    async def _flush(self) -> None:
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        async with self._sessions() as session:
            for kind, args in batch:
                if kind == "signal":
                    symbol, strategy, side, conf, regime, outcome, code, detail = args
                    session.add(SignalRow(
                        account_id=self._account_id, symbol=symbol, strategy=strategy,
                        side=side, confidence=Decimal(str(conf)), regime=regime,
                        outcome=outcome, rejection_code=code, detail=str(detail)[:2000],
                    ))
                elif kind == "execution":
                    ex, role, position_id = args
                    order = OrderRow(
                        account_id=self._account_id, symbol=ex.symbol,
                        client_order_id=ex.client_order_id, exchange_order_id=ex.order_id,
                        side=ex.side.value, type="MARKET", qty=ex.qty, status="filled",
                        role=role, submitted_at=ex.executed_at,
                        last_exchange_sync_at=ex.executed_at,
                    )
                    session.add(order)
                    await session.flush()
                    session.add(FillRow(
                        order_id=order.id, exchange_trade_id=ex.order_id,
                        price=ex.fill_price, qty=ex.qty, fee_amount=ex.fee,
                        fee_asset=self._settings.paper_quote_asset,
                        filled_at=ex.executed_at,
                    ))
                elif kind == "pos_open":
                    (p,) = args
                    session.add(PositionRow(
                        account_id=self._account_id, symbol=p.symbol, status="open",
                        qty=p.qty, avg_entry_price=p.entry_price, stop_price=p.stop_price,
                        take_profit_price=p.take_profit, strategy=p.strategy,
                        fees_paid=p.fees_paid, max_holding_until=p.max_holding_until,
                        opened_at=p.opened_at,
                    ))
                elif kind == "pos_close":
                    p, ex, pnl, reason = args
                    from sqlalchemy import select

                    row = (await session.execute(
                        select(PositionRow).where(
                            PositionRow.account_id == self._account_id,
                            PositionRow.symbol == p.symbol,
                            PositionRow.status == "open",
                        )
                    )).scalars().first()
                    if row:
                        row.status = "closed"
                        row.realized_pnl = Decimal(pnl)
                        row.fees_paid = p.fees_paid + ex.fee
                        row.closed_at = ex.executed_at
                        row.exit_reason = reason
                elif kind == "risk":
                    event_type, limit_name, detail = args
                    session.add(RiskEventRow(
                        account_id=self._account_id, event_type=event_type,
                        limit_name=limit_name, detail=str(detail)[:2000],
                    ))
                elif kind == "equity":
                    equity, cash, exposure = args
                    session.add(EquitySnapshot(
                        account_id=self._account_id, equity=Decimal(str(equity)),
                        cash=Decimal(str(cash)), exposure=Decimal(str(exposure)),
                    ))
                elif kind == "decision":
                    (d,) = args
                    from cryptobot.db.models import DecisionRow

                    session.add(DecisionRow(
                        account_id=self._account_id, symbol=d.symbol,
                        decision=d.action.value, status=d.status.value,
                        confidence=Decimal(str(d.confidence)), score=Decimal(str(d.score)),
                        supporting=d.supporting, conflicting=d.conflicting,
                        entry_estimate=Decimal(str(d.entry_estimate)) if d.entry_estimate else None,
                        stop_price=Decimal(str(d.stop_price)) if d.stop_price else None,
                        take_profit=Decimal(str(d.take_profit)) if d.take_profit else None,
                        expected_holding_bars=d.expected_holding_bars,
                        est_fees=Decimal(str(d.est_fees)),
                        est_spread=Decimal(str(d.est_spread)),
                        est_slippage=Decimal(str(d.est_slippage)),
                        expected_gross_return=Decimal(str(d.expected_gross_return))
                        if d.expected_gross_return is not None else None,
                        expected_net_return=Decimal(str(d.expected_net_return))
                        if d.expected_net_return is not None else None,
                        reasons={"list": d.reasons},
                    ))
            await session.commit()

    # ── daily report ─────────────────────────────────────────────────
    async def _maybe_daily_report(self) -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if self._current_day is None:
            self._current_day = today
            return
        if today != self._current_day:
            report = dict(self.runtime.snapshot())
            report["report_for"] = self._current_day
            async with self._sessions() as session:
                session.add(DailyReportRow(
                    account_id=self._account_id, report_date=self._current_day,
                    content=report,
                ))
                await session.commit()
            logger.info("daily_report_written", date=self._current_day)
            self._current_day = today

    # ── main loop ────────────────────────────────────────────────────
    async def run(self) -> None:
        settings = self._settings

        # v2: session config from DB
        from sqlalchemy import select as _select

        from cryptobot.db.models import SessionConfigRow
        from cryptobot.session.policy import (
            OvernightPolicy,
            SessionConfig,
            SessionState,
            TargetProtection,
        )

        async with self._sessions() as session:
            row = (await session.execute(
                _select(SessionConfigRow).where(
                    SessionConfigRow.account_id == self._account_id)
            )).scalars().first()
        if row is not None:
            self.runtime.session_config = SessionConfig(
                session_start_utc=row.session_start_utc,
                session_end_utc=row.session_end_utc,
                trading_days=tuple(row.trading_days.get("days", range(7))),
                overnight_policy=OvernightPolicy(row.overnight_policy),
                daily_profit_target_pct=float(row.daily_profit_target_pct)
                if row.daily_profit_target_pct else None,
                target_protection=TargetProtection(row.target_protection),
            )
        # Restore persisted state (FR-8.1) and route execution
        from cryptobot.runtime.state_restore import (
            apply_high_water_mark,
            restore_paper_state,
            restore_risk_counters,
        )

        account, positions, equity, restore_report, closed_today, hwm = await restore_paper_state(
            self._sessions, self._account_id, settings.paper_quote_asset,
            float(settings.paper_starting_balance_quote),
        )
        self.runtime.restore_positions(positions)
        apply_high_water_mark(self.runtime._risk_state, equity, hwm)
        restore_risk_counters(closed_today, self.runtime._risk_state)
        halt = self.runtime.risk.check_halts(self.runtime._risk_state)
        if halt is not None:
            await self._controls.set_risk_halted(halt.reason_code)
            self.runtime._risk_state.halted = True
            self.runtime._risk_state.halt_reason = halt.detail
        self.runtime.session_state = SessionState(day_start_equity=equity)
        logger.info("state_restored", **restore_report.__dict__)

        if settings.execution_mode == "testnet":
            from cryptobot.exchange.testnet_broker import TestnetBroker
            from cryptobot.execution.policy import ExecutionPolicy, OrderStyle

            rules = await self._adapter.get_exchange_rules()
            self.runtime.broker = TestnetBroker(  # type: ignore[assignment]
                self._adapter, rules.symbols,
                account=account, quote_asset=settings.paper_quote_asset,
            )
            # Testnet broker is market-only; maker limits are paper-only.
            self.runtime.execution_policy = ExecutionPolicy(entry_style=OrderStyle.MARKET)
            logger.info("execution_routing", mode="testnet",
                        note="orders go to Binance Spot Testnet after all checks")
        else:
            self.runtime.broker.account = account  # type: ignore[attr-defined]
            logger.info("execution_routing", mode=settings.execution_mode)

        await self.runtime.sync_controls_halt()

        from cryptobot.runtime.reconciliation import reconcile_on_startup

        reconcile = await reconcile_on_startup(
            self._sessions, self._account_id, settings.paper_quote_asset,
            settings.execution_mode,
            self._adapter if settings.execution_mode == "testnet" else None,
            set(self.runtime._positions.keys()),
        )
        if not reconcile.ok:
            await self._controls.set_risk_halted("reconciliation_mismatch")
            self.runtime._risk_state.halted = True
            self.runtime._risk_state.halt_reason = "reconciliation_mismatch"
            logger.warning("reconciliation_halt", mismatches=reconcile.mismatches)
            if self.runtime.notifier is not None:
                from cryptobot.notifications.service import Severity

                await self.runtime.notifier.send(
                    "reconciliation_halt",
                    "STARTUP RECONCILIATION FAILED — trading halted until operator review. "
                    f"Mismatches: {'; '.join(reconcile.mismatches[:3])}",
                    Severity.CRITICAL,
                )

        from cryptobot.config.versioning import record_config_change, settings_snapshot

        await record_config_change(
            self._sessions, "app", settings_snapshot(settings),
            change_note="trader startup snapshot",
        )

        # Distributed lock — only one trader instance (NFR-4)
        lock_key = "cryptobot:trader:lock"
        import redis.asyncio as aioredis

        lock_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        acquired = await lock_redis.set(
            lock_key, "1", nx=True, ex=settings.trader_lock_ttl_s,
        )
        if not acquired:
            await lock_redis.aclose()
            raise RuntimeError(
                "Another trader instance holds the lock — refusing to start"
            )

        async def _renew_lock() -> None:
            while True:
                await asyncio.sleep(max(5, settings.trader_lock_ttl_s // 3))
                await lock_redis.expire(lock_key, settings.trader_lock_ttl_s)

        lock_task = asyncio.create_task(_renew_lock())

        from cryptobot.runtime.tick_cache import TickCache

        tick_cache = TickCache(settings.redis_url)

        # Seed history so strategies have warmup immediately
        for symbol in settings.trading_pairs:
            for interval in settings.candle_intervals:
                bars = await load_db(self._sessions, symbol, interval)
                if bars:
                    self.runtime.seed_history(symbol, interval, bars)
        logger.info("paper_trading_started", pairs=settings.trading_pairs,
                    strategies=[s.spec.name for s in self.runtime.strategies])

        async def _refresh_exchange_rules() -> None:
            while True:
                await asyncio.sleep(settings.exchange_info_refresh_s)
                try:
                    rules = await self._adapter.get_exchange_rules()
                    broker = self.runtime.broker
                    if hasattr(broker, "_rules"):
                        broker._rules = rules.symbols  # noqa: SLF001
                except Exception as exc:  # noqa: BLE001
                    logger.warning("exchange_info_refresh_failed", error=type(exc).__name__)

        rules_task = asyncio.create_task(_refresh_exchange_rules())

        async def _estop_poller() -> None:
            while True:
                await asyncio.sleep(2)
                try:
                    ctrl = await self._controls.state()
                    if ctrl.emergency_stop and self.runtime._positions:
                        await self.runtime.execute_emergency_stop()
                except Exception as exc:  # noqa: BLE001
                    logger.error("estop_poller_failed", error=type(exc).__name__)

        estop_task = asyncio.create_task(_estop_poller())
        flusher = asyncio.create_task(self._flush_loop())
        try:
            async for event in self._adapter.market_stream(
                settings.trading_pairs, settings.candle_intervals,
                include_trades=settings.ws_include_trades,
                include_depth=settings.ws_include_depth,
            ):
                self._last_ws_at = event.received_at
                if event.type is MarketEventType.TRADE:
                    payload = event.payload
                    await tick_cache.set_trade(
                        event.symbol, str(payload.get("price", "")),
                        str(payload.get("qty", "")),
                    )
                    continue
                if event.type is MarketEventType.DEPTH:
                    continue
                if (
                    event.type is MarketEventType.KLINE
                    and event.candle is not None
                    and event.candle.is_closed
                ):
                    await self.runtime.on_closed_candle(event.candle)
                    await self._maybe_daily_report()
        finally:
            flusher.cancel()
            rules_task.cancel()
            estop_task.cancel()
            lock_task.cancel()
            await lock_redis.delete(lock_key)
            await lock_redis.aclose()
            await tick_cache.close()
            await self._flush()
            await self._controls.close()

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            try:
                await self._flush()
            except Exception as exc:  # noqa: BLE001 — persistence must not kill trading
                logger.error("flush_failed", error=type(exc).__name__)
