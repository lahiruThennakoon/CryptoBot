"""Chatbot tool registry: strict allowlist, schema validation, classification.

Every tool is a thin wrapper over existing authenticated services. Tools are
executed ONLY from provider-native tool calls, never parsed from free text.
There is deliberately no place_order tool. High-risk tools return a
confirmation requirement instead of executing directly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from cryptobot.core.logging import get_logger

logger = get_logger(__name__)


class RiskClass(str, Enum):
    READ_ONLY = "read_only"
    LOW_RISK = "low_risk"        # explicit user confirmation
    HIGH_RISK = "high_risk"      # arm/confirm server token


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    risk: RiskClass
    handler: Callable[..., Awaitable[dict[str, Any]]]


class ToolValidationError(Exception):
    pass


@dataclass
class ToolRegistry:
    _tools: dict[str, ToolSpec] = field(default_factory=dict)
    max_calls_per_request: int = 8

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:            # strict allowlist
            raise ToolValidationError(f"tool '{name}' is not on the allowlist")
        return self._tools[name]

    def definitions(self) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in self._tools.values()
        ]

    def validate_arguments(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Minimal JSON-schema validation: required keys, types, enums, no extras."""
        spec = self.get(name)
        schema = spec.input_schema
        props: dict[str, Any] = schema.get("properties", {})
        clean: dict[str, Any] = {}
        for key in schema.get("required", []):
            if key not in arguments:
                raise ToolValidationError(f"{name}: missing required argument '{key}'")
        for key, value in arguments.items():
            if key not in props:
                raise ToolValidationError(f"{name}: unexpected argument '{key}'")
            expected = props[key].get("type")
            type_map = {"string": str, "integer": int, "number": (int, float),
                        "boolean": bool}
            if expected in type_map and not isinstance(value, type_map[expected]):
                raise ToolValidationError(f"{name}: '{key}' must be {expected}")
            if "enum" in props[key] and value not in props[key]["enum"]:
                raise ToolValidationError(f"{name}: '{key}' must be one of {props[key]['enum']}")
            if expected == "string" and len(str(value)) > 200:
                raise ToolValidationError(f"{name}: '{key}' too long")
            clean[key] = value
        return clean

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a validated tool. High-risk tools do NOT execute here —
        they return a confirmation-required envelope for the UI flow."""
        spec = self.get(name)
        clean = self.validate_arguments(name, arguments)
        if spec.risk is RiskClass.HIGH_RISK:
            return {
                "requires_confirmation": True,
                "risk_classification": spec.risk.value,
                "action": name,
                "arguments": clean,
                "message": ("This is a protected action. Review the impact and "
                            "confirm it in the app's confirmation dialog — it was "
                            "NOT executed."),
            }
        result = await spec.handler(**clean)
        result.setdefault("_meta", {})
        result["_meta"].update({
            "tool": name,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "risk_classification": spec.risk.value,
        })
        return result


def _schema(properties: dict[str, Any] | None = None,
            required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties or {},
            "required": required or []}


def build_registry(sessions: Any, catalog: Any, kb: Any) -> ToolRegistry:
    """Wire tools to the existing services. Read-only handlers query the same
    repositories the dashboard API uses; no direct exchange or secret access."""
    from sqlalchemy import desc, select

    registry = ToolRegistry()

    async def get_enabled_trading_pairs() -> dict[str, Any]:
        from cryptobot.pairs.service import enabled_symbols

        return {"enabled_pairs": sorted(await enabled_symbols(sessions))}

    async def get_live_pair_price(symbol: str) -> dict[str, Any]:
        listings = await catalog.list_pairs(sessions, search=symbol)
        match = next((p for p in listings if p.symbol == symbol.upper()), None)
        if match is None:
            return {"error": f"{symbol} not found on the active venue"}
        return {"symbol": match.symbol, "price": float(match.stats.last_price),
                "change_24h_pct": float(match.stats.price_change_pct_24h),
                "spread_pct": float(match.stats.spread_fraction) * 100,
                "source": "binance live public 24h ticker"}

    async def get_pair_signal(symbol: str) -> dict[str, Any]:
        from cryptobot.db.models import DecisionRow

        async with sessions() as session:
            row = (await session.execute(
                select(DecisionRow).where(DecisionRow.symbol == symbol.upper())
                .order_by(desc(DecisionRow.created_at)).limit(1)
            )).scalars().first()
        if row is None:
            return {"error": f"no decision recorded yet for {symbol}",
                    "hint": "the trading runtime records one per closed candle"}
        return {"symbol": row.symbol, "status": row.status, "decision": row.decision,
                "confidence": float(row.confidence), "score": float(row.score),
                "supporting": row.supporting, "conflicting": row.conflicting,
                "reasons": row.reasons, "calculated_at": row.created_at.isoformat(),
                "source": "decision engine (deterministic)"}

    async def get_account_balances() -> dict[str, Any]:
        from cryptobot.db.models import EquitySnapshot

        async with sessions() as session:
            snap = (await session.execute(
                select(EquitySnapshot).order_by(desc(EquitySnapshot.taken_at)).limit(1)
            )).scalars().first()
        if snap is None:
            return {"error": "no equity snapshot yet — is the trading runtime running?"}
        return {"equity": float(snap.equity), "cash": float(snap.cash),
                "exposure": float(snap.exposure), "as_of": snap.taken_at.isoformat(),
                "value_kind": "simulated (paper account)", "source": "equity snapshots db"}

    async def get_open_positions() -> dict[str, Any]:
        from cryptobot.db.models import PositionRow

        async with sessions() as session:
            rows = (await session.execute(
                select(PositionRow).where(PositionRow.status == "open")
            )).scalars().all()
        return {"open_positions": [
            {"symbol": r.symbol, "qty": str(r.qty), "entry": str(r.avg_entry_price),
             "stop": str(r.stop_price), "strategy": r.strategy,
             "opened_at": r.opened_at.isoformat()} for r in rows
        ], "source": "positions db"}

    async def get_daily_performance() -> dict[str, Any]:
        from cryptobot.db.models import FillRow, PositionRow

        today = datetime.now(UTC).date()
        async with sessions() as session:
            closed = (await session.execute(
                select(PositionRow).where(PositionRow.status == "closed")
            )).scalars().all()
            fills = (await session.execute(select(FillRow))).scalars().all()
        closed_today = [p for p in closed if p.closed_at and p.closed_at.date() == today]
        fees_today = sum(float(f.fee_amount) for f in fills
                         if f.filled_at.date() == today)
        realized = sum(float(p.realized_pnl) for p in closed_today)
        return {"date": str(today), "closed_trades": len(closed_today),
                "realized_pnl": realized, "fees_paid": fees_today,
                "net_after_fees_note": "realized_pnl is already net of fees",
                "value_kind": "simulated (paper)", "source": "positions + fills db"}

    async def get_risk_status() -> dict[str, Any]:
        from cryptobot.db.models import RiskEventRow

        async with sessions() as session:
            events = (await session.execute(
                select(RiskEventRow).order_by(desc(RiskEventRow.occurred_at)).limit(5)
            )).scalars().all()
        return {"recent_risk_events": [
            {"type": e.event_type, "limit": e.limit_name, "detail": e.detail,
             "at": e.occurred_at.isoformat()} for e in events
        ], "source": "risk events db"}

    async def get_rejected_signals(hours: int = 24) -> dict[str, Any]:
        from datetime import timedelta

        from cryptobot.analytics.explanations import explain
        from cryptobot.db.models import SignalRow

        since = datetime.now(UTC) - timedelta(hours=min(hours, 168))
        async with sessions() as session:
            rows = (await session.execute(
                select(SignalRow).where(SignalRow.created_at >= since,
                                        SignalRow.outcome != "executed")
            )).scalars().all()
        counts: dict[str, int] = {}
        for r in rows:
            counts[r.rejection_code or "UNKNOWN"] = counts.get(r.rejection_code or "UNKNOWN", 0) + 1
        return {"hours": hours, "rejections": [
            {"code": code, "count": n, "plain_language": explain(code).text}
            for code, n in sorted(counts.items(), key=lambda kv: -kv[1])
        ], "source": "signal log db"}

    async def search_application_help(query: str) -> dict[str, Any]:
        return kb.search(query)

    async def explain_crypto_concept(topic: str) -> dict[str, Any]:
        """Curated crypto education (indicators, costs, risk, market structure).
        Contains no predictions by design."""
        return kb.search(topic, top_k=3)

    async def recommend_trading_pairs(equity: float = 0.0) -> dict[str, Any]:
        """Deterministic suitability ranking (the LLM only explains this)."""
        from cryptobot.costs.model import CostModel
        from cryptobot.db.models import CandleRow, EquitySnapshot, Instrument
        from cryptobot.pairs.screener import ScreenInput, portfolio_advice, rank_pairs
        from cryptobot.risk.engine import RiskConfig

        if equity <= 0:
            async with sessions() as session:
                snap = (await session.execute(
                    select(EquitySnapshot).order_by(desc(EquitySnapshot.taken_at)).limit(1)
                )).scalars().first()
            equity = float(snap.equity) if snap else 0.0
        if equity <= 0:
            return {"error": "no account equity recorded yet — start the paper trader first"}

        listings = [p for p in await catalog.list_pairs(sessions) if p.selectable][:25]
        enabled = {p.symbol for p in listings if p.enabled}
        defaults = RiskConfig()
        cost = CostModel().round_trip_fraction
        async with sessions() as session:
            instruments = {
                i.symbol: i for i in
                (await session.execute(select(Instrument))).scalars().all()
            }
            counts = {}
            for listing in listings:
                counts[listing.symbol] = len((await session.execute(
                    select(CandleRow.id).where(CandleRow.symbol == listing.symbol,
                                               CandleRow.interval == "1h").limit(600)
                )).scalars().all())

        ranked = rank_pairs([
            ScreenInput(
                symbol=p.symbol, base_asset=p.base_asset, quote_asset=p.quote_asset,
                selectable=p.selectable, not_selectable_reason=p.not_selectable_reason,
                price=float(p.stats.last_price),
                quote_volume_24h=float(p.stats.quote_volume_24h),
                spread_fraction=float(p.stats.spread_fraction),
                round_trip_cost_fraction=cost,
                min_notional=float(instruments[p.symbol].min_notional)
                if p.symbol in instruments else 5.0,
                equity=equity, risk_per_trade=defaults.risk_per_trade,
                max_position_pct=defaults.max_position_pct,
                candles_available=counts.get(p.symbol, 0),
                already_enabled=p.symbol in enabled,
            ) for p in listings
        ], top_n=8)
        return {
            "equity": equity,
            "advice": portfolio_advice(ranked, equity, defaults.max_positions),
            "ranking": [
                {"symbol": r.symbol, "suitable": r.suitable, "score": r.score,
                 "headline": r.headline, "reasons": r.reasons, "blockers": r.blockers}
                for r in ranked
            ],
            "source": "deterministic pair screener",
            "caveat": "Suitability, not profit prediction. Enabling a pair is the user's "
                      "decision and requires confirmation.",
        }

    async def get_cost_reality(equity: float = 0.0, symbol: str = "BTCUSDT") -> dict[str, Any]:
        """Deterministic cost arithmetic for this account size."""
        from cryptobot.analytics.cost_microscope import CostInputs, analyse_costs
        from cryptobot.db.models import EquitySnapshot

        if equity <= 0:
            async with sessions() as session:
                snap = (await session.execute(
                    select(EquitySnapshot).order_by(desc(EquitySnapshot.taken_at)).limit(1)
                )).scalars().first()
            equity = float(snap.equity) if snap else 0.0
        if equity <= 0:
            return {"error": "no equity recorded yet — start the paper trader first"}
        price_info = await get_live_pair_price(symbol)
        price = float(price_info.get("price") or 0)
        if price <= 0:
            return {"error": f"no live price available for {symbol}"}
        report = analyse_costs(CostInputs(equity=equity, price=price))
        return {"equity": equity, "symbol": symbol.upper(),
                "round_trip_cost_usd": report.round_trip_cost_usd,
                "breakeven_move_pct": report.breakeven_move_pct,
                "monthly_cost_pct_of_equity": report.monthly_cost_pct_of_equity,
                "maker_saving_usd_per_trade": report.maker_saving_usd_per_trade,
                "warnings": report.warnings, "summary": report.plain_summary,
                "source": "deterministic cost calculator"}

    read_tools: list[tuple[str, str, dict[str, Any], Any]] = [
        ("get_enabled_trading_pairs", "List the trading pairs the user has enabled.",
         _schema(), get_enabled_trading_pairs),
        ("get_live_pair_price", "Live price, 24h change and spread for one pair.",
         _schema({"symbol": {"type": "string"}}, ["symbol"]), get_live_pair_price),
        ("get_pair_signal", "Latest decision-engine signal for a pair with reasons.",
         _schema({"symbol": {"type": "string"}}, ["symbol"]), get_pair_signal),
        ("get_account_balances", "Current (simulated) equity, cash and exposure.",
         _schema(), get_account_balances),
        ("get_open_positions", "Open positions with entries, stops and strategies.",
         _schema(), get_open_positions),
        ("get_daily_performance", "Today's realized PnL, trade count and fees.",
         _schema(), get_daily_performance),
        ("get_risk_status", "Recent risk events (halts, emergency stops).",
         _schema(), get_risk_status),
        ("get_rejected_signals", "Skipped signals with plain-language reasons.",
         _schema({"hours": {"type": "integer"}}), get_rejected_signals),
        ("search_application_help", "Search the app's documentation and FAQ.",
         _schema({"query": {"type": "string"}}, ["query"]), search_application_help),
        ("explain_crypto_concept",
         "Look up curated crypto education: indicators, fees, spread, slippage, "
         "regimes, risk, exchange rules. Use this instead of answering from memory.",
         _schema({"topic": {"type": "string"}}, ["topic"]), explain_crypto_concept),
        ("recommend_trading_pairs",
         "Deterministic suitability ranking of pairs for the user's account size "
         "(affordability, move-vs-cost, liquidity, evidence, diversification). "
         "Explain this ranking — never invent or reorder it, and never claim it "
         "predicts profit.",
         _schema({"equity": {"type": "number"}}), recommend_trading_pairs),
        ("get_cost_reality",
         "Deterministic cost arithmetic for the user's account size: round-trip cost, "
         "break-even move, monthly cost drag, maker savings.",
         _schema({"equity": {"type": "number"}, "symbol": {"type": "string"}}),
         get_cost_reality),
    ]
    for name, description, schema, handler in read_tools:
        registry.register(ToolSpec(name, description, schema, RiskClass.READ_ONLY, handler))

    async def _confirm_stub(**_: Any) -> dict[str, Any]:   # never called (HIGH_RISK short-circuits)
        return {}

    for name, description, schema in [
        ("pause_trading", "Pause opening new positions (exits stay active).", _schema()),
        ("resume_trading", "Resume trading after a pause or halt review.", _schema()),
        ("activate_emergency_stop",
         "Close all positions immediately and block trading.", _schema()),
        ("cancel_open_order", "Cancel one open order.",
         _schema({"client_order_id": {"type": "string"}}, ["client_order_id"])),
        ("update_risk_setting", "Change a risk limit within allowed bounds.",
         _schema({"setting": {"type": "string",
                              "enum": ["risk_per_trade", "max_daily_loss_pct",
                                       "max_positions", "daily_profit_target_pct"]},
                  "value": {"type": "number"}}, ["setting", "value"])),
    ]:
        registry.register(ToolSpec(name, description, schema, RiskClass.HIGH_RISK, _confirm_stub))

    async def enable_pair_handler(symbol: str) -> dict[str, Any]:
        listing = await catalog.set_enabled(sessions, symbol.upper(), True)
        return {"symbol": symbol.upper(), "enabled": True, "warnings": listing.warnings}

    async def disable_pair_handler(symbol: str) -> dict[str, Any]:
        await catalog.set_enabled(sessions, symbol.upper(), False)
        return {"symbol": symbol.upper(), "enabled": False}

    registry.register(ToolSpec(
        "enable_trading_pair",
        "Enable a trading pair (after showing its liquidity/spread warnings).",
        _schema({"symbol": {"type": "string"}}, ["symbol"]),
        RiskClass.LOW_RISK, enable_pair_handler))
    registry.register(ToolSpec(
        "disable_trading_pair", "Disable a trading pair.",
        _schema({"symbol": {"type": "string"}}, ["symbol"]),
        RiskClass.LOW_RISK, disable_pair_handler))
    return registry
