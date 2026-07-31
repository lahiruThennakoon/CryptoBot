"""Dashboard-facing API routes (Phase 4).

High-risk controls use the two-step arm/confirm flow: the client first calls
POST /controls/arm, then passes the returned one-time token to the
destructive endpoint. Every control action is written to the audit trail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import desc, select

from cryptobot.api.auth import require_auth
from cryptobot.config import get_settings
from cryptobot.db.models import (
    AuditEvent,
    DailyReportRow,
    EquitySnapshot,
    FillRow,
    OrderRow,
    PositionRow,
    RiskEventRow,
    SignalRow,
)
from cryptobot.risk.engine import RiskConfig
from cryptobot.runtime.controls import ControlService

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_auth)])


def _sessions(request: Request):  # noqa: ANN202
    return request.app.state.sessions


def _controls(request: Request) -> ControlService:
    return request.app.state.controls


class ConfirmedAction(BaseModel):
    confirm_token: str


# ── read endpoints ────────────────────────────────────────────────────
@router.get("/overview")
async def overview(request: Request) -> dict[str, Any]:
    settings = get_settings()
    controls = await _controls(request).state()
    async with _sessions(request)() as session:
        latest_equity = (await session.execute(
            select(EquitySnapshot).order_by(desc(EquitySnapshot.taken_at)).limit(1)
        )).scalars().first()
        open_positions = (await session.execute(
            select(PositionRow).where(PositionRow.status == "open")
        )).scalars().all()
        last_risk_event = (await session.execute(
            select(RiskEventRow).order_by(desc(RiskEventRow.occurred_at)).limit(1)
        )).scalars().first()
    cfg = RiskConfig()
    equity = float(latest_equity.equity) if latest_equity else None
    return {
        "mode": settings.mode.value,
        "execution_mode": settings.execution_mode,   # analysis | paper | testnet
        "live_trading": "disabled",
        "paused": controls.paused,
        "emergency_stop": controls.emergency_stop,
        "equity": equity,
        "cash": float(latest_equity.cash) if latest_equity else None,
        "exposure": float(latest_equity.exposure) if latest_equity else None,
        "open_positions": len(open_positions),
        "risk_limits": {
            "max_daily_loss_pct": cfg.max_daily_loss_pct,
            "max_drawdown_pct": cfg.max_drawdown_pct,
            "max_positions": cfg.max_positions,
            "max_exposure_pct": cfg.max_exposure_pct,
            "max_trades_per_day": cfg.max_trades_per_day,
        },
        "last_risk_event": {
            "type": last_risk_event.event_type,
            "detail": last_risk_event.detail,
            "at": last_risk_event.occurred_at.isoformat(),
        } if last_risk_event else None,
        "disclaimer": "Trading is risky. No profit is guaranteed. Losses are possible.",
    }


@router.get("/equity")
async def equity_curve(request: Request, hours: int = 168) -> list[dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    async with _sessions(request)() as session:
        rows = (await session.execute(
            select(EquitySnapshot).where(EquitySnapshot.taken_at >= since)
            .order_by(EquitySnapshot.taken_at)
        )).scalars().all()
    return [{"t": r.taken_at.isoformat(), "equity": float(r.equity),
             "exposure": float(r.exposure)} for r in rows]


@router.get("/positions")
async def positions(request: Request, status: str = "open") -> list[dict[str, Any]]:
    async with _sessions(request)() as session:
        rows = (await session.execute(
            select(PositionRow).where(PositionRow.status == status)
            .order_by(desc(PositionRow.opened_at)).limit(100)
        )).scalars().all()
    return [{
        "symbol": r.symbol, "qty": str(r.qty), "entry": str(r.avg_entry_price),
        "stop": str(r.stop_price) if r.stop_price else None,
        "take_profit": str(r.take_profit_price) if r.take_profit_price else None,
        "strategy": r.strategy, "opened_at": r.opened_at.isoformat(),
        "realized_pnl": str(r.realized_pnl), "exit_reason": r.exit_reason,
        "closed_at": r.closed_at.isoformat() if r.closed_at else None,
    } for r in rows]


@router.get("/fills")
async def fills(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    async with _sessions(request)() as session:
        rows = (await session.execute(
            select(FillRow, OrderRow).join(OrderRow, FillRow.order_id == OrderRow.id)
            .order_by(desc(FillRow.filled_at)).limit(min(limit, 200))
        )).all()
    return [{
        "symbol": order.symbol, "side": order.side, "role": order.role,
        "price": str(fill.price), "qty": str(fill.qty), "fee": str(fill.fee_amount),
        "at": fill.filled_at.isoformat(),
    } for fill, order in rows]


@router.get("/signals")
async def signals(request: Request, limit: int = 100) -> list[dict[str, Any]]:
    async with _sessions(request)() as session:
        rows = (await session.execute(
            select(SignalRow).order_by(desc(SignalRow.created_at)).limit(min(limit, 500))
        )).scalars().all()
    return [{
        "symbol": r.symbol, "strategy": r.strategy, "side": r.side,
        "confidence": float(r.confidence), "regime": r.regime, "outcome": r.outcome,
        "rejection_code": r.rejection_code, "detail": r.detail,
        "at": r.created_at.isoformat(),
    } for r in rows]


@router.get("/risk/events")
async def risk_events(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    async with _sessions(request)() as session:
        rows = (await session.execute(
            select(RiskEventRow).order_by(desc(RiskEventRow.occurred_at)).limit(limit)
        )).scalars().all()
    return [{"type": r.event_type, "limit": r.limit_name, "detail": r.detail,
             "at": r.occurred_at.isoformat(), "acknowledged_by": r.acknowledged_by}
            for r in rows]


@router.get("/reports/daily")
async def daily_reports(request: Request, limit: int = 30) -> list[dict[str, Any]]:
    async with _sessions(request)() as session:
        rows = (await session.execute(
            select(DailyReportRow).order_by(desc(DailyReportRow.report_date)).limit(limit)
        )).scalars().all()
    return [{"date": r.report_date, "content": r.content} for r in rows]


@router.post("/graduation/drills/{name}")
async def acknowledge_drill(request: Request, name: str, body: dict[str, Any]) -> dict[str, Any]:
    """Record (or withdraw) the operator's claim that a drill was run and passed.

    This is an integrity-critical record, not a preference: it is attributed,
    timestamped, and every change is written to the permanent audit trail.
    """
    from cryptobot.db.models import AuditEvent, DrillAckRow, utcnow
    from cryptobot.readiness.checks import DRILLS
    from cryptobot.readiness.drills import DRILL_SPECS

    if name not in (*DRILLS, "owner_signoff"):
        raise HTTPException(404, f"unknown drill '{name}'")
    acknowledged = bool(body.get("acknowledged", True))
    notes = str(body.get("notes", ""))[:2000]
    if acknowledged and len(notes.strip()) < 10:
        raise HTTPException(
            422,
            "Please record what you observed (at least a sentence). An unexplained "
            "tick is not evidence, and this record is what a future you will rely on.",
        )

    async with _sessions(request)() as session:
        row = await session.get(DrillAckRow, name)
        if row is None:
            row = DrillAckRow(drill_name=name)
            session.add(row)
        row.acknowledged = acknowledged
        row.notes = notes
        row.acknowledged_by = "operator"
        row.acknowledged_at = utcnow() if acknowledged else None
        row.updated_at = utcnow()
        session.add(AuditEvent(
            category="manual_action", actor="operator",
            payload={"action": "drill_acknowledged" if acknowledged else "drill_withdrawn",
                     "drill": name, "notes": notes,
                     "pass_criteria": DRILL_SPECS[name].pass_criteria
                     if name in DRILL_SPECS else "owner sign-off"},
        ))
        await session.commit()
    return {"drill": name, "acknowledged": acknowledged,
            "note": "Recorded and audited. Withdraw it any time if you later find the "
                    "drill did not truly pass."}


# ── small-account awareness suite ─────────────────────────────────────
async def _latest_equity(request: Request) -> float:
    from cryptobot.db.models import EquitySnapshot

    async with _sessions(request)() as session:
        snap = (await session.execute(
            select(EquitySnapshot).order_by(desc(EquitySnapshot.taken_at)).limit(1)
        )).scalars().first()
    return float(snap.equity) if snap else 0.0


@router.get("/awareness/costs")
async def awareness_costs(
    request: Request, symbol: str = "BTCUSDT", equity: float = 0.0,
    position_pct: float = 0.05, trades_per_day: float = 3.0, bnb_discount: float = 0.0,
) -> dict[str, Any]:
    """Cost microscope: what trading actually costs at YOUR account size."""
    from cryptobot.analytics.cost_microscope import CostInputs, analyse_costs
    from cryptobot.db.models import Instrument

    if equity <= 0:
        equity = await _latest_equity(request) or float(
            get_settings().paper_starting_balance_quote)
    listings = await _catalog(request).list_pairs(_sessions(request), search=symbol)
    match = next((p for p in listings if p.symbol == symbol.upper()), None)
    price = float(match.stats.last_price) if match else 0.0
    spread = float(match.stats.spread_fraction) if match else 0.0006
    if price <= 0:
        raise HTTPException(409, f"no live price for {symbol}")

    async with _sessions(request)() as session:
        instrument = (await session.execute(
            select(Instrument).where(Instrument.symbol == symbol.upper())
        )).scalars().first()
    min_notional = float(instrument.min_notional) if instrument else 5.0
    step_size = float(instrument.step_size) if instrument else 1e-5

    report = analyse_costs(CostInputs(
        equity=equity, price=price, spread_fraction=max(spread, 0.0001),
        min_notional=min_notional or 5.0, step_size=step_size or 1e-5,
        position_pct=position_pct, trades_per_day=trades_per_day,
        bnb_discount=bnb_discount,
    ))
    return {"symbol": symbol.upper(), "equity": equity, "price": price,
            **report.__dict__}


@router.post("/awareness/sizing")
async def awareness_sizing(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Sizing reality check — catches settings that make trading impossible."""
    from cryptobot.analytics.cost_microscope import SizingInputs, check_sizing
    from cryptobot.db.models import Instrument
    from cryptobot.risk.engine import RiskConfig

    symbol = str(body.get("symbol", "BTCUSDT")).upper()
    equity = float(body.get("equity") or 0) or await _latest_equity(request) or float(
        get_settings().paper_starting_balance_quote)
    defaults = RiskConfig()
    listings = await _catalog(request).list_pairs(_sessions(request), search=symbol)
    match = next((p for p in listings if p.symbol == symbol), None)
    price = float(match.stats.last_price) if match else 0.0
    if price <= 0:
        raise HTTPException(409, f"no live price for {symbol}")
    async with _sessions(request)() as session:
        instrument = (await session.execute(
            select(Instrument).where(Instrument.symbol == symbol)
        )).scalars().first()

    report = check_sizing(SizingInputs(
        equity=equity, price=price,
        risk_per_trade=float(body.get("risk_per_trade") or defaults.risk_per_trade),
        stop_distance_pct=float(body.get("stop_distance_pct") or 0.03),
        max_position_pct=float(body.get("max_position_pct") or defaults.max_position_pct),
        min_notional=float(instrument.min_notional) if instrument else 5.0,
        min_qty=float(instrument.min_qty) if instrument else 1e-5,
        step_size=float(instrument.step_size) if instrument else 1e-5,
    ))
    return {"symbol": symbol, "equity": equity, "price": price, **report.__dict__}


@router.get("/awareness/summary")
async def awareness_summary(request: Request) -> dict[str, Any]:
    """Recovery math, growth range, execution divergence, behaviour flags,
    and the small-account guardrails currently in force."""
    from cryptobot.analytics.awareness import (
        behaviour_flags,
        execution_divergence,
        growth_outlook,
        recovery_math,
    )
    from cryptobot.costs.model import CostModel
    from cryptobot.db.models import AuditEvent, EquitySnapshot, FillRow, PositionRow
    from cryptobot.risk.engine import RiskConfig
    from cryptobot.risk.small_account import apply_small_account_guardrails

    async with _sessions(request)() as session:
        equity_rows = (await session.execute(
            select(EquitySnapshot).order_by(EquitySnapshot.taken_at)
        )).scalars().all()
        closed = (await session.execute(
            select(PositionRow).where(PositionRow.status == "closed")
            .order_by(PositionRow.closed_at)
        )).scalars().all()
        fills = (await session.execute(select(FillRow))).scalars().all()
        changes = (await session.execute(
            select(AuditEvent).where(AuditEvent.category == "manual_action")
            .order_by(desc(AuditEvent.occurred_at)).limit(50)
        )).scalars().all()

    equity = float(equity_rows[-1].equity) if equity_rows else float(
        get_settings().paper_starting_balance_quote)
    peak = max((float(r.equity) for r in equity_rows), default=equity)

    trade_returns = []
    for p in closed:
        notional = float(p.avg_entry_price) * float(p.qty)
        if notional > 0:
            trade_returns.append(float(p.realized_pnl) / notional * 100)
    expectancy = (sum(trade_returns) / len(trade_returns) / 100) if trade_returns else None

    observed = []
    for f in fills:
        notional = float(f.price) * float(f.qty)
        if notional > 0:
            observed.append(float(f.fee_amount) / notional)
    costs = CostModel()
    guardrails = apply_small_account_guardrails(
        RiskConfig(), equity, costs.round_trip_fraction)

    config_changes = [
        (c.occurred_at, str(c.payload.get("action", "")),
         "loosened" if "risk" in str(c.payload.get("action", "")).lower() else "other")
        for c in changes
    ]
    return {
        "equity": equity, "peak_equity": peak,
        "recovery": recovery_math(peak, equity, expectancy).__dict__,
        "growth": growth_outlook(trade_returns, equity).__dict__,
        "divergence": execution_divergence(costs.round_trip_fraction, observed).__dict__,
        "behaviour": [f.__dict__ for f in behaviour_flags(config_changes)],
        "guardrails": {
            "min_expected_edge_pct": round(guardrails.min_expected_edge * 100, 4),
            "max_trades_per_day": guardrails.max_trades_per_day,
            "max_positions": guardrails.config.max_positions,
            "adjustments": list(guardrails.adjustments),
            "rationale": guardrails.rationale,
        },
        "disclaimer": "Arithmetic and ranges from your own results — never a forecast "
                      "or a promise of profit.",
    }


@router.get("/export/fills.csv")
async def export_fills_csv(request: Request) -> Response:
    """Tax / record-keeping export: every fill with fees."""
    import csv
    import io

    from cryptobot.db.models import FillRow, OrderRow

    async with _sessions(request)() as session:
        rows = (await session.execute(
            select(FillRow, OrderRow).join(OrderRow, FillRow.order_id == OrderRow.id)
            .order_by(FillRow.filled_at)
        )).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["filled_at_utc", "symbol", "side", "role", "price", "quantity",
                     "notional", "fee", "fee_asset", "client_order_id", "mode"])
    mode = get_settings().execution_mode
    for fill, order in rows:
        writer.writerow([
            fill.filled_at.isoformat(), order.symbol, order.side, order.role,
            str(fill.price), str(fill.qty), str(fill.price * fill.qty),
            str(fill.fee_amount), fill.fee_asset, order.client_order_id, mode,
        ])
    return Response(
        content=buffer.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cryptobot_fills.csv"})


# ── chart data ────────────────────────────────────────────────────────
@router.get("/candles")
async def candles(
    request: Request, symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 200
) -> dict[str, Any]:
    """OHLCV for price charts. Data comes from the app's own candle store,
    collected from Binance streams / historical import (never invented)."""
    from cryptobot.db.models import CandleRow

    async with _sessions(request)() as session:
        rows = (await session.execute(
            select(CandleRow)
            .where(CandleRow.symbol == symbol.upper(), CandleRow.interval == interval)
            .order_by(desc(CandleRow.open_time)).limit(min(limit, 1000))
        )).scalars().all()
    rows = list(reversed(rows))
    return {
        "symbol": symbol.upper(), "interval": interval, "count": len(rows),
        "candles": [
            {"t": r.open_time.isoformat(), "o": float(r.open), "h": float(r.high),
             "l": float(r.low), "c": float(r.close), "v": float(r.volume)}
            for r in rows
        ],
        "source": "cryptobot candle store (binance klines)",
    }


@router.get("/performance/daily")
async def performance_daily(request: Request, days: int = 30) -> dict[str, Any]:
    """Per-day realized PnL and fees for the bar chart. Realized PnL is net of
    fees; gross is shown separately so nothing is double-counted or hidden."""
    from collections import defaultdict

    from cryptobot.db.models import FillRow, PositionRow

    since = datetime.now(UTC) - timedelta(days=min(days, 365))
    async with _sessions(request)() as session:
        closed = (await session.execute(
            select(PositionRow).where(PositionRow.status == "closed",
                                      PositionRow.closed_at >= since)
        )).scalars().all()
        fills = (await session.execute(
            select(FillRow).where(FillRow.filled_at >= since)
        )).scalars().all()

    net_by_day: dict[str, float] = defaultdict(float)
    fees_by_day: dict[str, float] = defaultdict(float)
    trades_by_day: dict[str, int] = defaultdict(int)
    for p in closed:
        if p.closed_at is None:
            continue
        day = p.closed_at.strftime("%Y-%m-%d")
        net_by_day[day] += float(p.realized_pnl)
        trades_by_day[day] += 1
    for f in fills:
        fees_by_day[f.filled_at.strftime("%Y-%m-%d")] += float(f.fee_amount)

    days_sorted = sorted(set(net_by_day) | set(fees_by_day))
    return {
        "days": [
            {"date": d, "net_pnl": round(net_by_day.get(d, 0.0), 4),
             "fees": round(fees_by_day.get(d, 0.0), 4),
             "gross_pnl": round(net_by_day.get(d, 0.0) + fees_by_day.get(d, 0.0), 4),
             "trades": trades_by_day.get(d, 0)}
            for d in days_sorted
        ],
        "value_kind": "simulated (paper trading)",
        "note": "net_pnl is after fees; gross_pnl adds fees back for comparison only.",
    }


# ── trading pairs (v2) ────────────────────────────────────────────────
def _catalog(request: Request):  # noqa: ANN202
    return request.app.state.pair_catalog


@router.get("/pairs")
async def list_pairs(request: Request, search: str = "", limit: int = 100) -> list[dict[str, Any]]:
    listings = await _catalog(request).list_pairs(_sessions(request), search=search)
    return [
        {
            "symbol": p.symbol, "base_asset": p.base_asset, "quote_asset": p.quote_asset,
            "status": p.status, "enabled": p.enabled, "selectable": p.selectable,
            "not_selectable_reason": p.not_selectable_reason, "warnings": p.warnings,
            "last_price": float(p.stats.last_price),
            "price_change_pct_24h": float(p.stats.price_change_pct_24h),
            "quote_volume_24h": float(p.stats.quote_volume_24h),
            "spread_pct": float(p.stats.spread_fraction) * 100,
            "volatility_24h_pct": float(p.stats.volatility_24h) * 100,
        }
        for p in listings[: min(limit, 500)]
    ]


@router.get("/pairs/recommend")
async def recommend_pairs(
    request: Request, equity: float = 0.0, limit: int = 10, top_by_volume: int = 40,
) -> dict[str, Any]:
    """Rank pairs by SUITABILITY for this account — never by predicted profit.

    Suitability = affordable at this equity + typical move large relative to
    trading cost + liquid + evidence + diversification. Every exclusion states
    why. Enabling remains the user's action.
    """
    from cryptobot.costs.model import CostModel
    from cryptobot.db.models import CandleRow, Instrument, PositionRow
    from cryptobot.features.indicators import atr
    from cryptobot.pairs.screener import ScreenInput, portfolio_advice, rank_pairs
    from cryptobot.risk.engine import RiskConfig

    if equity <= 0:
        equity = await _latest_equity(request) or float(
            get_settings().paper_starting_balance_quote)
    listings = await _catalog(request).list_pairs(_sessions(request))
    candidates = [p for p in listings if p.selectable][:max(5, top_by_volume)]
    enabled_now = {p.symbol for p in listings if p.enabled}
    defaults = RiskConfig()
    cost_fraction = CostModel().round_trip_fraction

    async with _sessions(request)() as session:
        instruments = {
            i.symbol: i for i in (await session.execute(select(Instrument))).scalars().all()
        }
        counts: dict[str, int] = {}
        atr_pct: dict[str, float] = {}
        for listing in candidates:
            rows = (await session.execute(
                select(CandleRow).where(CandleRow.symbol == listing.symbol,
                                        CandleRow.interval == "1h")
                .order_by(desc(CandleRow.open_time)).limit(300)
            )).scalars().all()
            counts[listing.symbol] = len(rows)
            if len(rows) >= 30:
                rows = list(reversed(rows))
                values = atr([float(r.high) for r in rows], [float(r.low) for r in rows],
                             [float(r.close) for r in rows], 14)
                last = values[-1]
                close = float(rows[-1].close)
                if last and close > 0:
                    atr_pct[listing.symbol] = last / close * 100
        open_symbols = {
            r.symbol for r in (await session.execute(
                select(PositionRow).where(PositionRow.status == "open")
            )).scalars().all()
        }

    inputs = []
    for listing in candidates:
        instrument = instruments.get(listing.symbol)
        inputs.append(ScreenInput(
            symbol=listing.symbol, base_asset=listing.base_asset,
            quote_asset=listing.quote_asset, selectable=listing.selectable,
            not_selectable_reason=listing.not_selectable_reason,
            price=float(listing.stats.last_price),
            atr_pct=atr_pct.get(listing.symbol),
            quote_volume_24h=float(listing.stats.quote_volume_24h),
            spread_fraction=float(listing.stats.spread_fraction),
            round_trip_cost_fraction=cost_fraction,
            min_notional=float(instrument.min_notional) if instrument else 5.0,
            step_size=float(instrument.step_size) if instrument else 1e-5,
            equity=equity, risk_per_trade=defaults.risk_per_trade,
            max_position_pct=defaults.max_position_pct,
            candles_available=counts.get(listing.symbol, 0),
            already_enabled=listing.symbol in enabled_now,
        ))

    ranked = rank_pairs(inputs, top_n=min(limit, 25))
    return {
        "equity": equity,
        "advice": portfolio_advice(ranked, equity, defaults.max_positions),
        "open_position_symbols": sorted(open_symbols),
        "recommendations": [
            {"symbol": r.symbol, "suitable": r.suitable, "score": r.score,
             "headline": r.headline, "affordable": r.affordable,
             "position_notional": r.position_notional,
             "move_to_cost_ratio": r.move_to_cost_ratio,
             "components": r.components, "reasons": r.reasons,
             "blockers": r.blockers, "already_enabled": r.already_enabled}
            for r in ranked
        ],
        "disclaimer": "Suitability means a pair CAN be traded sensibly at your account "
                      "size — not that it will be profitable. No ranking predicts future "
                      "returns.",
    }


@router.post("/pairs/auto-manage/plan")
async def auto_manage_plan(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Preview what automatic pair selection WOULD do. Executes nothing."""
    from cryptobot.pairs.auto_manage import AutoManageConfig, plan_auto_manage
    from cryptobot.pairs.screener import ScreenInput, rank_pairs  # noqa: F401

    recommendations = await recommend_pairs(request, equity=float(body.get("equity") or 0))
    from cryptobot.pairs.screener import ScreenResult

    ranked = [
        ScreenResult(
            symbol=r["symbol"], suitable=r["suitable"], score=r["score"],
            affordable=r["affordable"], components=r["components"], reasons=r["reasons"],
            blockers=r["blockers"], position_notional=r["position_notional"],
            move_to_cost_ratio=r["move_to_cost_ratio"],
            already_enabled=r["already_enabled"],
        )
        for r in recommendations["recommendations"]
    ]
    config = AutoManageConfig(
        enabled=bool(body.get("enabled", False)),
        consent_phrase=str(body.get("consent_phrase", "")),
        max_active_pairs=int(body.get("max_active_pairs", 3)),
    )
    enabled_now = {r.symbol for r in ranked if r.already_enabled}
    plan = plan_auto_manage(
        config, ranked, enabled_now,
        set(recommendations["open_position_symbols"]),
        evidence_positive={},   # requires Strategy-lab evidence; empty = nothing auto-enabled
    )
    return {
        "authorised": config.authorised,
        "summary": plan.summary(),
        "enable": [{"symbol": s, "reason": r} for s, r in plan.enable],
        "disable": [{"symbol": s, "reason": r} for s, r in plan.disable],
        "unchanged": plan.unchanged,
        "blocked_reason": plan.blocked_reason,
        "note": "This is a preview. Applying it still requires your confirmation, and a "
                "pair is never auto-enabled without positive backtest evidence.",
    }


@router.post("/pairs/{symbol}/enable")
async def enable_pair(request: Request, symbol: str) -> dict[str, Any]:
    try:
        listing = await _catalog(request).set_enabled(_sessions(request), symbol.upper(), True)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from exc
    await _audit(request, "pair_enabled", symbol)
    return {"symbol": symbol.upper(), "enabled": True, "warnings": listing.warnings}


@router.post("/pairs/{symbol}/disable")
async def disable_pair(request: Request, symbol: str) -> dict[str, Any]:
    try:
        await _catalog(request).set_enabled(_sessions(request), symbol.upper(), False)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    await _audit(request, "pair_disabled", symbol)
    return {"symbol": symbol.upper(), "enabled": False}


@router.get("/decisions/current")
async def current_decisions(request: Request) -> list[dict[str, Any]]:
    """Latest decision per symbol — drives the Trading Pairs table."""
    from cryptobot.db.models import DecisionRow

    async with _sessions(request)() as session:
        rows = (await session.execute(
            select(DecisionRow).order_by(desc(DecisionRow.created_at)).limit(500)
        )).scalars().all()
    latest: dict[str, DecisionRow] = {}
    for r in rows:
        latest.setdefault(r.symbol, r)
    return [_decision_json(r) for r in latest.values()]


@router.get("/decisions")
async def decisions(request: Request, symbol: str = "", limit: int = 50) -> list[dict[str, Any]]:
    from cryptobot.db.models import DecisionRow

    async with _sessions(request)() as session:
        stmt = select(DecisionRow).order_by(desc(DecisionRow.created_at)).limit(min(limit, 200))
        if symbol:
            stmt = stmt.where(DecisionRow.symbol == symbol.upper())
        rows = (await session.execute(stmt)).scalars().all()
    return [_decision_json(r) for r in rows]


def _decision_json(r: Any) -> dict[str, Any]:
    return {
        "symbol": r.symbol, "decision": r.decision, "status": r.status,
        "confidence": float(r.confidence), "score": float(r.score),
        "supporting": r.supporting, "conflicting": r.conflicting,
        "entry_estimate": float(r.entry_estimate) if r.entry_estimate else None,
        "stop_price": float(r.stop_price) if r.stop_price else None,
        "take_profit": float(r.take_profit) if r.take_profit else None,
        "expected_holding_bars": r.expected_holding_bars,
        "est_fees": float(r.est_fees), "est_spread": float(r.est_spread),
        "est_slippage": float(r.est_slippage),
        "expected_gross_return": float(r.expected_gross_return) if r.expected_gross_return else None,
        "expected_net_return": float(r.expected_net_return) if r.expected_net_return else None,
        "reasons": r.reasons, "at": r.created_at.isoformat(),
        "advice_disclaimer": "Decision-support status, not financial advice.",
    }


# ── session configuration (v2) ────────────────────────────────────────
@router.get("/session")
async def get_session(request: Request) -> dict[str, Any]:
    from cryptobot.db.models import SessionConfigRow

    async with _sessions(request)() as session:
        row = (await session.execute(
            select(SessionConfigRow).where(
                SessionConfigRow.account_id == request.app.state.account_id)
        )).scalars().first()
    if row is None:
        return {"session_start_utc": "00:00", "session_end_utc": "23:59",
                "trading_days": [0, 1, 2, 3, 4, 5, 6], "overnight_policy": "hold",
                "daily_profit_target_pct": None, "target_protection": "stop_trading"}
    return {
        "session_start_utc": row.session_start_utc, "session_end_utc": row.session_end_utc,
        "trading_days": row.trading_days.get("days", []),
        "overnight_policy": row.overnight_policy,
        "daily_profit_target_pct": float(row.daily_profit_target_pct)
        if row.daily_profit_target_pct else None,
        "target_protection": row.target_protection,
        "max_capital": float(row.max_capital) if row.max_capital else None,
        "version": row.version,
    }


@router.put("/session")
async def put_session(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    from decimal import Decimal as D

    from cryptobot.db.models import SessionConfigRow, utcnow
    from cryptobot.session.policy import (
        OvernightPolicy,
        SessionConfig,
        TargetProtection,
        validate_config,
    )

    try:
        cfg = SessionConfig(
            session_start_utc=str(body.get("session_start_utc", "00:00")),
            session_end_utc=str(body.get("session_end_utc", "23:59")),
            trading_days=tuple(body.get("trading_days", [0, 1, 2, 3, 4, 5, 6])),
            overnight_policy=OvernightPolicy(body.get("overnight_policy", "hold")),
            daily_profit_target_pct=body.get("daily_profit_target_pct"),
            target_protection=TargetProtection(body.get("target_protection", "stop_trading")),
            max_capital=body.get("max_capital"),
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, f"invalid session config: {exc}") from exc

    problems = validate_config(cfg)
    if problems:
        raise HTTPException(422, {"rejected": True, "problems": problems})

    async with _sessions(request)() as session:
        row = (await session.execute(
            select(SessionConfigRow).where(
                SessionConfigRow.account_id == request.app.state.account_id)
        )).scalars().first()
        if row is None:
            row = SessionConfigRow(account_id=request.app.state.account_id)
            session.add(row)
        row.session_start_utc = cfg.session_start_utc
        row.session_end_utc = cfg.session_end_utc
        row.trading_days = {"days": list(cfg.trading_days)}
        row.overnight_policy = cfg.overnight_policy.value
        row.daily_profit_target_pct = (
            D(str(cfg.daily_profit_target_pct)) if cfg.daily_profit_target_pct else None
        )
        row.target_protection = cfg.target_protection.value
        row.max_capital = D(str(cfg.max_capital)) if cfg.max_capital else None
        row.version += 1
        row.updated_at = utcnow()
        await session.commit()
        version = row.version
    await _audit(request, "session_config_updated", f"v{version}")
    return {"saved": True, "version": version}


# ── plain-language: why didn't it trade? ─────────────────────────────
@router.get("/explain/no-trade")
async def explain_no_trade(request: Request, hours: int = 24) -> dict[str, Any]:
    from cryptobot.analytics.explanations import explain, summarize_no_trades

    since = datetime.now(UTC) - timedelta(hours=hours)
    async with _sessions(request)() as session:
        rows = (await session.execute(
            select(SignalRow).where(
                SignalRow.created_at >= since,
                SignalRow.outcome != "executed",
            )
        )).scalars().all()
        executed = (await session.execute(
            select(SignalRow).where(
                SignalRow.created_at >= since, SignalRow.outcome == "executed",
            )
        )).scalars().all()
    counts: dict[str, int] = {}
    for r in rows:
        code = r.rejection_code or "UNKNOWN"
        counts[code] = counts.get(code, 0) + 1
    reasons = [
        {
            "code": code,
            "count": count,
            "title": explain(code).title,
            "explanation": explain(code).text,
            "protective": explain(code).is_protective,
        }
        for code, count in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
    return {
        "hours": hours,
        "trades_executed": len(executed),
        "signals_skipped": len(rows),
        "summary": summarize_no_trades(counts),
        "reasons": reasons,
    }


# ── graduation progress (paper → live evidence) ──────────────────────
@router.get("/graduation")
async def graduation(request: Request) -> dict[str, Any]:
    from cryptobot.readiness.checks import DRILLS, Facts
    from cryptobot.readiness.service import gather_db_facts

    settings = get_settings()
    facts = Facts(mode=settings.mode.value)
    facts = await gather_db_facts(facts, _sessions(request), settings.redis_url)

    def item(name: str, label: str, current: float | int | None, target: float,
             direction: str, unit: str = "") -> dict[str, Any]:
        done = current is not None and (
            current >= target if direction == "gte" else current <= target
        )
        progress = 0.0
        if current is not None and target > 0:
            progress = min(1.0, current / target) if direction == "gte" else (
                1.0 if current <= target else 0.0
            )
        return {"name": name, "label": label, "current": current, "target": target,
                "unit": unit, "done": done, "progress": round(progress, 3)}

    items = [
        item("paper_days", "Days of continuous paper trading",
             facts.paper_trading_days, facts.required_paper_days, "gte", "days"),
        item("trades", "Closed paper trades",
             facts.closed_paper_trades, facts.required_trades, "gte"),
        item("net_pnl", "Net paper profit after costs",
             facts.paper_net_pnl, 0.0000001, "gte", "USDT"),
        item("drawdown", "Max drawdown stays under limit",
             facts.max_drawdown_pct, facts.max_allowed_drawdown_pct, "lte", "%"),
    ]

    from cryptobot.db.models import DrillAckRow
    from cryptobot.readiness.drills import DRILL_SPECS

    async with _sessions(request)() as session:
        acks = {
            r.drill_name: r for r in
            (await session.execute(select(DrillAckRow))).scalars().all()
        }
    manual = []
    for drill in (*DRILLS, "owner_signoff"):
        ack = acks.get(drill)
        spec = DRILL_SPECS.get(drill)
        manual.append({
            "name": drill,
            "label": spec.title if spec else "Owner sign-off (docs/live-readiness/approval.md)",
            "done": bool(ack and ack.acknowledged),
            "manual": True,
            "why": spec.why if spec else
                   "The final human decision: reviewing all evidence and accepting the "
                   "risk in writing. Nothing in the code can grant this.",
            "how": list(spec.how) if spec else
                   ["Read docs/live-readiness/approval.md",
                    "Complete every precondition and attach the evidence",
                    "Sign and date the decision section"],
            "pass_criteria": spec.pass_criteria if spec else
                             "The approval document is complete and signed.",
            "notes": ack.notes if ack else "",
            "acknowledged_by": ack.acknowledged_by if ack and ack.acknowledged else "",
            "acknowledged_at": ack.acknowledged_at.isoformat()
            if ack and ack.acknowledged and ack.acknowledged_at else None,
        })
    automated_done = sum(1 for i in items if i["done"])
    return {
        "items": items,
        "manual_items": manual,
        "manual_complete": sum(1 for m in manual if m["done"]),
        "manual_total": len(manual),
        "automated_complete": automated_done,
        "automated_total": len(items),
        "note": ("Completing every item makes the system ELIGIBLE for the owner's "
                 "live-trading decision. It does not guarantee profitability, and "
                 "live trading stays off until the manual sign-off."),
    }


# ── strategy lab: run/compare backtests from the UI ──────────────────
@router.get("/lab/strategies")
async def lab_strategies() -> list[dict[str, Any]]:
    from cryptobot.strategies import STRATEGY_REGISTRY

    out = []
    for name, cls in STRATEGY_REGISTRY.items():
        spec = cls().spec
        out.append({
            "name": name,
            "timeframe": spec.timeframe,
            "required_conditions": spec.required_conditions,
            "invalid_when": spec.invalid_when,
            "allowed_regimes": sorted(r.value for r in spec.allowed_regimes),
        })
    return out


@router.post("/lab/backtest")
async def lab_backtest(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    import asyncio

    from cryptobot.analytics.verdicts import judge
    from cryptobot.backtest.engine import BacktestEngine
    from cryptobot.backtest.loaders import load_db
    from cryptobot.backtest.metrics import compute_report
    from cryptobot.strategies import STRATEGY_REGISTRY

    strategy_name = str(body.get("strategy", ""))
    symbol = str(body.get("symbol", "BTCUSDT"))
    interval = str(body.get("interval", "1h"))
    if strategy_name not in STRATEGY_REGISTRY:
        raise HTTPException(404, f"unknown strategy {strategy_name}")

    bars = await load_db(_sessions(request), symbol, interval)
    if len(bars) < 200:
        raise HTTPException(
            409, f"only {len(bars)} candles in the database for {symbol} {interval} — "
                 "run: cryptobot import-history",
        )

    def _run() -> Any:
        engine = BacktestEngine()
        return compute_report(engine.run(bars, STRATEGY_REGISTRY[strategy_name]()), interval)

    report = await asyncio.to_thread(_run)
    verdict = judge(report)
    return {
        "strategy": strategy_name,
        "symbol": symbol,
        "interval": interval,
        "bars": len(bars),
        "period": {"from": bars[0].open_time.isoformat(), "to": bars[-1].open_time.isoformat()},
        "verdict": {"grade": verdict.grade, "headline": verdict.headline,
                    "detail": verdict.detail},
        "metrics": {
            "net_return_pct": report.net_return_pct,
            "buy_hold_return_pct": report.buy_hold_return_pct,
            "max_drawdown_pct": report.max_drawdown_pct,
            "n_trades": report.n_trades,
            "win_rate": report.win_rate,
            "expectancy": report.expectancy,
            "total_fees": report.total_fees,
            "sharpe": report.sharpe,
            "exposure_time_pct": report.exposure_time_pct,
        },
        "rejections": report.rejections,
        "regime_distribution": report.regime_distribution,
        "note": "Backtest on historical data — an estimate, never a guarantee.",
    }


# ── AI assistant (v3, optional) ──────────────────────────────────────
@router.post("/ai/chat")
async def ai_chat(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    import time as _time
    import uuid as _uuid

    from cryptobot.ai.budget import SpendState
    from cryptobot.db.models import AiConversationRow, AiMessageRow, AiUsageRow

    chat = getattr(request.app.state, "chat_service", None)
    if chat is None:
        raise HTTPException(503, "AI assistant is not configured (set ANTHROPIC_API_KEY). "
                                 "All trading features work without it.")
    user_message = str(body.get("message", ""))[:4000]
    if not user_message.strip():
        raise HTTPException(422, "empty message")
    conversation_id = body.get("conversation_id")

    async with _sessions(request)() as session:
        conversation = None
        if conversation_id:
            conversation = await session.get(AiConversationRow, _uuid.UUID(str(conversation_id)))
        if conversation is None:
            conversation = AiConversationRow(account_id=request.app.state.account_id,
                                             title=user_message[:60])
            session.add(conversation)
            await session.commit()
        rows = (await session.execute(
            select(AiMessageRow).where(AiMessageRow.conversation_id == conversation.id)
            .order_by(AiMessageRow.created_at).limit(24)
        )).scalars().all()
        history = [{"role": r.role, "content": r.content} for r in rows]
        summary = conversation.summary
        conv_id = conversation.id

        # spend so far (today / this month)
        today = datetime.now(UTC).date()
        usage_rows = (await session.execute(select(AiUsageRow))).scalars().all()
        spend = SpendState(
            today_usd=sum(float(u.cost_usd) for u in usage_rows
                          if u.created_at.date() == today),
            month_usd=sum(float(u.cost_usd) for u in usage_rows
                          if u.created_at.strftime("%Y-%m") == today.strftime("%Y-%m")),
            conversation_messages=len(rows),
        )

    started = _time.monotonic()
    result = await chat.turn(
        user_message, history, spend, conversation_summary=summary,
        explanation_mode="technical" if body.get("explanation_mode") == "technical" else "simple",
    )
    latency_ms = int((_time.monotonic() - started) * 1000)

    async with _sessions(request)() as session:
        session.add(AiMessageRow(conversation_id=conv_id, role="user",
                                 content=user_message))
        session.add(AiMessageRow(conversation_id=conv_id, role="assistant",
                                 content=result.message,
                                 tools_used={"list": result.tools_used},
                                 data_timestamps={"list": result.data_timestamps}))
        session.add(AiUsageRow(conversation_id=conv_id, model=result.model,
                               route_reason=result.route_reason,
                               prompt_version=result.prompt_version,
                               input_tokens=result.input_tokens,
                               output_tokens=result.output_tokens,
                               cache_read_tokens=result.cache_read_tokens,
                               tool_calls=len(result.tools_used),
                               cost_usd=result.cost_usd, latency_ms=latency_ms,
                               error="" if result.response_type != "error" else "provider"))
        await session.commit()

    return {
        "conversation_id": str(conv_id),
        "message": result.message,
        "response_type": result.response_type,
        "tools_used": result.tools_used,
        "data_timestamps": result.data_timestamps,
        "operating_mode": result.operating_mode,
        "warnings": result.warnings,
        "requires_confirmation": result.requires_confirmation,
        "model": result.model,
        "cost_usd": round(result.cost_usd, 5),
        "disclaimer": "AI answers may be imperfect; verify before acting. "
                      "No profit is guaranteed.",
    }


@router.post("/ai/clear")
async def ai_clear(request: Request, body: dict[str, Any]) -> dict[str, str]:
    import uuid as _uuid

    from cryptobot.db.models import AiConversationRow, utcnow

    async with _sessions(request)() as session:
        conversation = await session.get(
            AiConversationRow, _uuid.UUID(str(body.get("conversation_id", "")))
        )
        if conversation and conversation.account_id == request.app.state.account_id:
            conversation.cleared_at = utcnow()
            conversation.summary = ""
            await session.commit()
    return {"status": "cleared"}


# ── controls (high-risk: arm/confirm flow + audit) ────────────────────
async def _audit(request: Request, action: str, detail: str = "") -> None:
    async with _sessions(request)() as session:
        session.add(AuditEvent(category="manual_action", actor="operator",
                               payload={"action": action, "detail": detail}))
        await session.commit()


@router.post("/controls/arm")
async def arm(request: Request) -> dict[str, str]:
    token = await _controls(request).arm()
    await _audit(request, "arm")
    return {"confirm_token": token, "expires_in_s": "60"}


@router.post("/controls/pause")
async def pause(request: Request) -> dict[str, str]:
    await _controls(request).pause()
    await _audit(request, "pause")
    return {"status": "paused"}


@router.post("/controls/resume")
async def resume(request: Request, body: ConfirmedAction) -> dict[str, str]:
    if not await _controls(request).confirm(body.confirm_token):
        raise HTTPException(403, "invalid or expired confirmation token")
    await _controls(request).resume()
    await _audit(request, "resume")
    return {"status": "resumed"}


@router.post("/controls/emergency-stop")
async def emergency_stop(request: Request, body: ConfirmedAction) -> dict[str, str]:
    if not await _controls(request).confirm(body.confirm_token):
        raise HTTPException(403, "invalid or expired confirmation token")
    await _controls(request).emergency_stop()
    await _audit(request, "emergency_stop")
    async with _sessions(request)() as session:
        session.add(RiskEventRow(
            account_id=request.app.state.account_id, event_type="emergency_stop",
            detail="operator emergency stop via API",
        ))
        await session.commit()
    return {"status": "emergency_stop_engaged"}
