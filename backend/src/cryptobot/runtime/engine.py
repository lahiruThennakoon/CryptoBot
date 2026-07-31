"""Real-time paper-trading runtime.

Pipeline per closed strategy-timeframe candle (docs/prd.md FR-11):
controls → staleness → regime → strategy signal → cost gate → risk veto →
paper execution → persistence → notifications. Position protection (stops,
take-profit, max holding) is evaluated on every closed 1m candle.

The runtime is adapter-agnostic (BarLike stream) so tests drive it with a
fake adapter; production wires BinanceSpotAdapter market streams in.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cryptobot.backtest.loaders import Bar
from cryptobot.core.logging import get_logger
from cryptobot.costs.model import CostModel
from cryptobot.exchange.models import Candle, Side
from cryptobot.notifications.service import Notifier, Severity
from cryptobot.paper.broker import PaperBroker
from cryptobot.regime.detector import Regime, RegimeDetector
from cryptobot.risk.engine import BasicRiskEngine, RiskState
from cryptobot.strategies.base import Intent, Strategy

logger = get_logger(__name__)

D = Decimal
MAX_HISTORY = 2_000


@dataclass
class PendingMakerOrder:
    """A resting limit entry awaiting a fill (or expiry)."""

    symbol: str
    limit_price: Decimal
    qty: Decimal
    stop_price: Decimal
    take_profit: Decimal | None
    strategy: str
    bars_remaining: int
    max_holding_bars: int


@dataclass
class OpenPosition:
    position_id: str
    symbol: str
    qty: Decimal
    entry_price: Decimal
    stop_price: Decimal
    take_profit: Decimal | None
    strategy: str
    opened_at: datetime
    max_holding_until: datetime
    fees_paid: Decimal = D("0")


@dataclass
class RuntimeEvents:
    """Persistence callbacks — the runtime stays storage-agnostic.
    Production wiring persists to PostgreSQL; tests capture in memory."""

    on_signal: object = None       # (symbol, strategy, side, confidence, regime, outcome, code, detail)
    on_execution: object = None    # (PaperExecution, role, position_id)
    on_position_open: object = None
    on_position_close: object = None
    on_risk_event: object = None   # (event_type, limit_name, detail)
    on_equity: object = None       # (equity, cash, exposure)
    on_decision: object = None     # (DecisionRecord)

    def emit(self, hook: str, *args: object) -> None:
        fn = getattr(self, hook)
        if fn is not None:
            fn(*args)  # type: ignore[operator]


@dataclass
class TradingRuntime:
    broker: PaperBroker                        # or TestnetBroker (same call shape)
    strategies: list[Strategy]
    risk: BasicRiskEngine
    costs: CostModel
    quote_asset: str = "USDT"
    stale_after_s: float = 60.0
    events: RuntimeEvents = field(default_factory=RuntimeEvents)
    notifier: Notifier | None = None
    controls_state: object | None = None      # duck-typed ControlState provider
    # v2: user pair selection, sessions, decisions, execution mode
    enabled_pairs: object | None = None       # async callable → set[str]; None = all
    session_config: object | None = None      # SessionConfig; None = always open
    session_state: object | None = None       # SessionState (day equity/pnl)
    decision_scorer: object | None = None     # DecisionScorer; records per-pair decisions
    analysis_only: bool = False               # True → decisions only, NEVER orders
    execution_policy: object | None = None    # ExecutionPolicy; None = market orders
    loss_cooldown_hours: float = 1.0          # pause per strategy+pair after a loss
    live_costs: object | None = None          # async (symbol, notional) → LiveCostBasis

    _history: dict[tuple[str, str], list[Bar]] = field(default_factory=lambda: defaultdict(list))
    _positions: dict[str, OpenPosition] = field(default_factory=dict)
    _risk_state: RiskState = field(default_factory=RiskState)
    _cooldown_until: dict[str, datetime] = field(default_factory=dict)
    _last_event_at: datetime | None = None
    _regime_detector: RegimeDetector = field(default_factory=RegimeDetector)
    _last_prices: dict[str, Decimal] = field(default_factory=dict)
    _pending_makers: dict[str, PendingMakerOrder] = field(default_factory=dict)

    def seed_history(self, symbol: str, interval: str, bars: list[Bar]) -> None:
        self._history[(symbol, interval)] = list(bars)[-MAX_HISTORY:]

    def seed_equity(self, equity: float) -> None:
        self._risk_state.update_equity(equity)

    # ── event entrypoint ─────────────────────────────────────────────
    async def on_closed_candle(self, candle: Candle) -> None:
        """Feed every CLOSED candle here (all intervals)."""
        self._last_event_at = datetime.now(UTC)
        bar = Bar(
            open_time=candle.open_time, open=float(candle.open), high=float(candle.high),
            low=float(candle.low), close=float(candle.close), volume=float(candle.volume),
        )
        key = (candle.symbol, candle.interval)
        history = self._history[key]
        if history and history[-1].open_time >= bar.open_time:
            return  # duplicate/replayed event — idempotent by design
        history.append(bar)
        del history[:-MAX_HISTORY]
        self._last_prices[candle.symbol] = candle.close

        self._mark_to_market()
        await self._resolve_pending_maker(candle)
        await self._protect_positions(candle)

        # ── v2 boundary: the bot NEVER trades a pair the user hasn't enabled ──
        if self.enabled_pairs is not None:
            allowed = await self.enabled_pairs()  # type: ignore[operator]
            if candle.symbol not in allowed:
                if any(s.spec.timeframe == candle.interval for s in self.strategies):
                    self._signal(candle.symbol, "runtime", "no_trade", 0, "unknown",
                                 "rejected_validation", "PAIR_DISABLED", "")
                return

        strategy_timeframe_closed = any(
            s.spec.timeframe == candle.interval for s in self.strategies
        )
        if strategy_timeframe_closed:
            await self._record_decision(candle.symbol, candle.interval)

        for strategy in self.strategies:
            if strategy.spec.timeframe == candle.interval and self._pair_allowed(strategy, candle.symbol):
                await self._run_strategy(strategy, candle.symbol, candle.interval)

    async def _record_decision(self, symbol: str, interval: str) -> None:
        """Produce and persist the per-pair decision record (docs/spec-v2 §6)."""
        if self.decision_scorer is None:
            return
        bars = self._history[(symbol, interval)]
        if len(bars) < 60:
            return
        from cryptobot.decision.scoring import MarketContext

        context = MarketContext(
            data_fresh=not self._stale(),
            has_open_position=symbol in self._positions,
        )
        record = self.decision_scorer.decide(  # type: ignore[attr-defined]
            symbol, bars, self._regime(bars), context
        )
        self.events.emit("on_decision", record)
        if record.status.value == "strong_buy" and self.notifier is not None:
            await self._notify(
                f"opportunity:{symbol}",
                f"Strong opportunity detected on {symbol} (score {record.score:+.2f}). "
                "This is decision support, not a guarantee of profit.",
            )

    # ── maker-order lifecycle (fill only on a genuine touch) ─────────
    async def _resolve_pending_maker(self, candle: Candle) -> None:
        pending = self._pending_makers.get(candle.symbol)
        if pending is None:
            return
        if candle.low <= pending.limit_price:          # market traded through the bid
            del self._pending_makers[candle.symbol]
            await self._fill_maker(pending)
            return
        pending.bars_remaining -= 1
        if pending.bars_remaining <= 0:
            del self._pending_makers[candle.symbol]
            self._signal(candle.symbol, pending.strategy, "no_trade", 0, "unknown",
                         "no_trade", "MAKER_ORDER_EXPIRED",
                         f"resting limit at {pending.limit_price} never filled — "
                         "no trade, no fees paid (opportunity cost accepted)")

    async def _fill_maker(self, pending: PendingMakerOrder) -> None:
        execution = self.broker.execute_maker_limit(   # type: ignore[attr-defined]
            symbol=pending.symbol, side=Side.BUY, qty=pending.qty,
            limit_price=pending.limit_price,
            base_asset=pending.symbol.removesuffix(self.quote_asset),
            quote_asset=self.quote_asset,
        )
        import inspect

        if inspect.isawaitable(execution):
            execution = await execution
        position = OpenPosition(
            position_id=uuid.uuid4().hex, symbol=pending.symbol, qty=execution.qty,
            entry_price=execution.fill_price, stop_price=pending.stop_price,
            take_profit=pending.take_profit, strategy=pending.strategy,
            opened_at=execution.executed_at,
            max_holding_until=execution.executed_at
            + timedelta(hours=pending.max_holding_bars),
            fees_paid=execution.fee,
        )
        self._positions[pending.symbol] = position
        self._risk_state.open_positions = len(self._positions)
        self._risk_state.trades_today += 1
        self.events.emit("on_execution", execution, "entry", position.position_id)
        self.events.emit("on_position_open", position)
        await self._notify(
            f"entry:{pending.symbol}",
            f"Maker entry filled on {pending.symbol}: {execution.qty} @ "
            f"{execution.fill_price} (maker fee only, no spread crossed)",
        )

    # ── position protection (every closed candle of any interval) ────
    async def _protect_positions(self, candle: Candle) -> None:
        position = self._positions.get(candle.symbol)
        if position is None:
            return
        low, close = D(str(candle.low)), candle.close
        now = candle.open_time
        reason: str | None = None
        exit_ref: Decimal | None = None
        if low <= position.stop_price:
            reason, exit_ref = "stop_loss", min(position.stop_price, close)
        elif position.take_profit is not None and candle.high >= position.take_profit:
            reason, exit_ref = "take_profit", position.take_profit
        elif now >= position.max_holding_until:
            reason, exit_ref = "max_holding_period", close
        if reason and exit_ref:
            await self._close_position(position, exit_ref, reason)

    # ── strategy pipeline ────────────────────────────────────────────
    async def _run_strategy(self, strategy: Strategy, symbol: str, interval: str) -> None:
        name = strategy.spec.name
        bars = self._history[(symbol, interval)]
        if len(bars) < strategy.spec.warmup_bars + 1:
            return

        if not await self._trading_allowed():
            return
        if self._stale():
            self._signal(symbol, name, "no_trade", 0, "unknown", "rejected_validation",
                         "STALE_DATA", "")
            return

        strategy.prepare(bars)          # causal; recomputed on the rolling window
        i = len(bars) - 1
        signal = strategy.on_bar(bars, i)
        regime = self._regime(bars)

        if signal.intent is Intent.HOLD:
            return
        if signal.intent is Intent.EXIT:
            position = self._positions.get(symbol)
            if position is not None and position.strategy == name:
                await self._close_position(position, self._last_prices[symbol], "strategy_exit")
            return

        # ── ENTER_LONG ───────────────────────────────────────────────
        price = self._last_prices[symbol]
        if symbol in self._positions:
            return

        # v2: session policy (times, days, profit-target protection)
        size_factor = 1.0
        min_confidence_override: float | None = None
        if self.session_config is not None and self.session_state is not None:
            from cryptobot.session.policy import evaluate_entry_policy

            policy = evaluate_entry_policy(
                self.session_config, self.session_state, datetime.now(UTC)  # type: ignore[arg-type]
            )
            if not policy.allowed:
                self._signal(symbol, name, "buy", signal.confidence, regime.value,
                             "rejected_risk", policy.reason_code, policy.detail)
                if policy.reason_code == "PROFIT_TARGET_REACHED" and not getattr(
                    self.session_state, "target_reached_notified", True
                ):
                    self.session_state.target_reached_notified = True  # type: ignore[attr-defined]
                    await self._notify("profit_target", policy.detail, Severity.INFO)
                return
            size_factor = policy.size_factor
            min_confidence_override = policy.min_confidence_override

        if min_confidence_override is not None and signal.confidence < min_confidence_override:
            self._signal(symbol, name, "buy", signal.confidence, regime.value,
                         "rejected_risk", "PROFIT_TARGET_RAISED_BAR",
                         f"needs ≥{min_confidence_override:.2f} after daily target")
            return

        # v2: analysis-only mode records the decision but never orders
        if self.analysis_only:
            self._signal(symbol, name, "buy", signal.confidence, regime.value,
                         "no_trade", "ANALYSIS_MODE", "analysis-only mode: no orders")
            return
        cooldown = self._cooldown_until.get(f"{name}:{symbol}")
        if cooldown and bars[i].open_time < cooldown:
            self._signal(symbol, name, "buy", signal.confidence, regime.value,
                         "rejected_risk", "COOLDOWN", "")
            return
        if regime not in strategy.spec.allowed_regimes:
            self._signal(symbol, name, "buy", signal.confidence, regime.value,
                         "rejected_validation", "REGIME_EXCLUDED", regime.value)
            return
        if signal.stop_price is None:
            self._signal(symbol, name, "buy", signal.confidence, regime.value,
                         "rejected_risk", "NO_STOP", "")
            return
        edge = (
            (signal.take_profit / float(price) - 1)
            if signal.take_profit
            else (float(price) - signal.stop_price) / float(price)
        )

        # ── real costs from the exchange, not assumptions ────────────
        costs = self.costs
        cost_note = ""
        if self.live_costs is not None:
            intended_notional = float(self._risk_state.equity) * self.risk.config.max_position_pct
            try:
                basis = await self.live_costs(symbol, intended_notional)  # type: ignore[operator]
                costs = basis.model
                cost_note = basis.summary()
                if not basis.all_live:
                    cost_note += " [some inputs assumed]"
            except Exception as exc:  # noqa: BLE001 — never block trading on a lookup
                logger.warning("live_cost_lookup_failed", symbol=symbol,
                               error=type(exc).__name__)
                cost_note = "live cost lookup failed — conservative defaults used"

        if not costs.passes_cost_gate(edge):
            self._signal(symbol, name, "buy", signal.confidence, regime.value,
                         "rejected_cost", "COST_GATE",
                         f"edge={edge:.4f} vs costs={costs.round_trip_fraction:.4f} "
                         f"+margin; {cost_note}")
            return

        decision = self.risk.evaluate_entry(
            self._risk_state, confidence=signal.confidence,
            price=float(price), stop_price=signal.stop_price,
        )
        if not decision.approved:
            self._signal(symbol, name, "buy", signal.confidence, regime.value,
                         "rejected_risk", decision.reason_code, decision.detail)
            if decision.reason_code in ("DAILY_LOSS_LIMIT", "MAX_DRAWDOWN", "CONSECUTIVE_LOSSES"):
                self.events.emit("on_risk_event", "halt", decision.reason_code, decision.detail)
                await self._notify("halt", f"Trading halted: {decision.reason_code}",
                                   Severity.CRITICAL)
            return

        final_qty = (D(str(decision.qty)) * D(str(size_factor))).quantize(D("0.00000001"))

        # ── maker policy: rest a limit order instead of crossing the spread ──
        if self.execution_policy is not None and getattr(
            self.execution_policy, "uses_maker_entries", False
        ):
            from cryptobot.execution.policy import limit_price_for_entry

            limit = D(str(limit_price_for_entry(float(price), self.execution_policy)))
            self._pending_makers[symbol] = PendingMakerOrder(
                symbol=symbol, limit_price=limit.quantize(D("0.00000001")),
                qty=final_qty, stop_price=D(str(signal.stop_price)),
                take_profit=D(str(signal.take_profit)) if signal.take_profit else None,
                strategy=name,
                bars_remaining=int(getattr(self.execution_policy, "ttl_bars", 3)),
                max_holding_bars=strategy.spec.max_holding_bars,
            )
            self._signal(symbol, name, "buy", signal.confidence, regime.value,
                         "executed", None,
                         f"maker limit resting at {limit:.2f} (cheaper than market; "
                         "may not fill)")
            return

        execution = self.broker.execute_market(
            symbol=symbol, side=Side.BUY, qty=final_qty,
            reference_price=price, base_asset=symbol.removesuffix(self.quote_asset),
            quote_asset=self.quote_asset,
        )
        import inspect

        if inspect.isawaitable(execution):   # TestnetBroker is async; PaperBroker is sync
            execution = await execution
        position = OpenPosition(
            position_id=uuid.uuid4().hex, symbol=symbol, qty=execution.qty,
            entry_price=execution.fill_price, stop_price=D(str(signal.stop_price)),
            take_profit=D(str(signal.take_profit)) if signal.take_profit else None,
            strategy=name, opened_at=execution.executed_at,
            max_holding_until=execution.executed_at
            + timedelta(hours=strategy.spec.max_holding_bars),
            fees_paid=execution.fee,
        )
        self._positions[symbol] = position
        self._risk_state.open_positions = len(self._positions)
        self._risk_state.trades_today += 1
        self._signal(symbol, name, "buy", signal.confidence, regime.value, "executed", None,
                     signal.reason)
        self.events.emit("on_execution", execution, "entry", position.position_id)
        self.events.emit("on_position_open", position)
        await self._notify(f"entry:{symbol}",
                           f"Opened {symbol} qty={execution.qty} @ {execution.fill_price}")

    async def _close_position(self, position: OpenPosition, reference: Decimal, reason: str) -> None:
        import inspect

        execution = self.broker.execute_market(
            symbol=position.symbol, side=Side.SELL, qty=position.qty,
            reference_price=reference,
            base_asset=position.symbol.removesuffix(self.quote_asset),
            quote_asset=self.quote_asset,
        )
        if inspect.isawaitable(execution):
            execution = await execution
        pnl = (execution.fill_price - position.entry_price) * position.qty \
            - execution.fee - position.fees_paid
        del self._positions[position.symbol]
        self._risk_state.open_positions = len(self._positions)
        self._risk_state.record_close(float(pnl))
        self._cooldown_until[f"{position.strategy}:{position.symbol}"] = (
            datetime.now(UTC) + timedelta(hours=self.loss_cooldown_hours)
            if float(pnl) <= 0 else datetime.now(UTC)
        )
        self.events.emit("on_execution", execution, "exit", position.position_id)
        self.events.emit("on_position_close", position, execution, str(pnl), reason)
        severity = Severity.WARNING if float(pnl) < 0 else Severity.INFO
        await self._notify(f"exit:{position.symbol}",
                           f"Closed {position.symbol} ({reason}) pnl={pnl:.2f}", severity)

    # ── emergency stop ───────────────────────────────────────────────
    async def execute_emergency_stop(self) -> int:
        """Close every open position immediately at last price. Returns count."""
        count = 0
        for position in list(self._positions.values()):
            await self._close_position(
                position, self._last_prices.get(position.symbol, position.entry_price),
                "emergency_stop",
            )
            count += 1
        self.events.emit("on_risk_event", "emergency_stop", "", f"closed {count} positions")
        await self._notify("estop", f"EMERGENCY STOP — closed {count} positions",
                           Severity.CRITICAL)
        return count

    # ── helpers ──────────────────────────────────────────────────────
    def _pair_allowed(self, strategy: Strategy, symbol: str) -> bool:
        return not strategy.spec.pairs or symbol in strategy.spec.pairs

    async def _trading_allowed(self) -> bool:
        if self.controls_state is None:
            return True
        state = await self.controls_state()  # type: ignore[operator]
        if state.emergency_stop and self._positions:
            await self.execute_emergency_stop()
        return state.trading_allowed

    def _stale(self) -> bool:
        return (
            self._last_event_at is not None
            and (datetime.now(UTC) - self._last_event_at).total_seconds() > self.stale_after_s
        )

    def _regime(self, bars: list[Bar]) -> Regime:
        return self._regime_detector.classify_series(
            [b.high for b in bars], [b.low for b in bars], [b.close for b in bars]
        )[-1]

    def _mark_to_market(self) -> None:
        exposure = sum(
            float(p.qty * self._last_prices.get(p.symbol, p.entry_price))
            for p in self._positions.values()
        )
        cash = float(self.broker.account.balance(self.quote_asset))
        equity = cash + exposure
        self._risk_state.update_equity(equity)
        self._risk_state.exposure_notional = exposure
        self.events.emit("on_equity", equity, cash, exposure)

    def _signal(self, symbol: str, strategy: str, side: str, confidence: float,
                regime: str, outcome: str, code: str | None, detail: str) -> None:
        logger.info("signal", symbol=symbol, strategy=strategy, outcome=outcome,
                    code=code or "", detail=detail)
        self.events.emit("on_signal", symbol, strategy, side, confidence, regime,
                         outcome, code, detail)

    async def _notify(self, key: str, message: str, severity: Severity = Severity.INFO) -> None:
        if self.notifier is not None:
            await self.notifier.send(key, message, severity)

    # ── daily report ─────────────────────────────────────────────────
    def snapshot(self) -> dict[str, object]:
        return {
            "equity": self._risk_state.equity,
            "cash": float(self.broker.account.balance(self.quote_asset)),
            "open_positions": len(self._positions),
            "positions": [
                {"symbol": p.symbol, "qty": str(p.qty), "entry": str(p.entry_price),
                 "stop": str(p.stop_price), "strategy": p.strategy}
                for p in self._positions.values()
            ],
            "trades_today": self._risk_state.trades_today,
            "daily_realized_pnl": self._risk_state.daily_realized_pnl,
            "consecutive_losses": self._risk_state.consecutive_losses,
            "halted": self._risk_state.halted,
            "halt_reason": self._risk_state.halt_reason,
        }
