"""Restore paper runtime state from PostgreSQL on startup (FR-8.1, NFR-5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import desc, func, select

from cryptobot.db.models import EquitySnapshot, PositionRow
from cryptobot.db.session import SessionFactory
from cryptobot.paper.account import PaperAccount
from cryptobot.runtime.engine import OpenPosition

D = Decimal


@dataclass
class RestoreReport:
    restored: bool
    equity: float
    open_positions: int
    cash: float
    detail: str = ""


async def restore_paper_state(
    sessions: SessionFactory,
    account_id: object,
    quote_asset: str,
    default_equity: float,
) -> tuple[PaperAccount, list[OpenPosition], float, RestoreReport, list[PositionRow], float | None]:
    """Rebuild in-memory account + open positions from the latest DB snapshots."""
    async with sessions() as session:
        latest = (await session.execute(
            select(EquitySnapshot)
            .where(EquitySnapshot.account_id == account_id)
            .order_by(desc(EquitySnapshot.taken_at))
            .limit(1)
        )).scalars().first()

        open_rows = (await session.execute(
            select(PositionRow).where(
                PositionRow.account_id == account_id,
                PositionRow.status == "open",
            )
        )).scalars().all()

        today = datetime.now(UTC).date()
        day_start = datetime(today.year, today.month, today.day, tzinfo=UTC)
        closed_today = (await session.execute(
            select(PositionRow).where(
                PositionRow.account_id == account_id,
                PositionRow.status == "closed",
                PositionRow.closed_at >= day_start,
            )
        )).scalars().all()

        peak_equity = (await session.execute(
            select(func.max(EquitySnapshot.equity)).where(
                EquitySnapshot.account_id == account_id,
            )
        )).scalar()

    if latest is None and not open_rows:
        account = PaperAccount.with_starting_balance(quote_asset, D(str(default_equity)))
        return account, [], float(default_equity), RestoreReport(
            restored=False, equity=float(default_equity), open_positions=0,
            cash=float(default_equity), detail="no prior state — fresh account",
        ), closed_today, None

    if latest is None and open_rows:
        locked = sum(float(r.qty * r.avg_entry_price) for r in open_rows)
        cash = max(0.0, float(default_equity) - locked)
        equity = cash + locked
    else:
        cash = float(latest.cash) if latest else float(default_equity)
        equity = float(latest.equity) if latest else cash

    account = PaperAccount(quote_asset=quote_asset, balances={quote_asset: D(str(cash))})

    default_holding = timedelta(hours=48)
    positions: list[OpenPosition] = []
    for row in open_rows:
        base = row.symbol.removesuffix(quote_asset)
        account.balances[base] = account.balance(base) + row.qty
        max_until = row.max_holding_until
        if max_until is None:
            max_until = row.opened_at + default_holding
        positions.append(OpenPosition(
            position_id=str(row.id),
            symbol=row.symbol,
            qty=row.qty,
            entry_price=row.avg_entry_price,
            stop_price=row.stop_price or row.avg_entry_price * D("0.95"),
            take_profit=row.take_profit_price,
            strategy=row.strategy,
            opened_at=row.opened_at,
            max_holding_until=max_until,
            fees_paid=row.fees_paid,
        ))

    hwm = float(peak_equity) if peak_equity is not None else equity
    hwm = max(hwm, equity)
    detail = f"equity={equity:.2f} cash={cash:.2f} positions={len(positions)}"
    return account, positions, equity, RestoreReport(
        restored=True, equity=equity, open_positions=len(positions), cash=cash, detail=detail,
    ), closed_today, hwm


def restore_risk_counters(closed_today: list[PositionRow], risk_state: object) -> None:
    """Replay today's closed trades into RiskState."""
    from cryptobot.risk.engine import RiskState

    if not isinstance(risk_state, RiskState):
        return
    risk_state.roll_day(datetime.now(UTC).date())
    risk_state.trades_today = len(closed_today)
    risk_state.daily_realized_pnl = sum(float(p.realized_pnl) for p in closed_today)
    streak = 0
    for row in sorted(closed_today, key=lambda p: p.closed_at or datetime.min.replace(tzinfo=UTC),
                      reverse=True):
        pnl = float(row.realized_pnl)
        if pnl <= 0:
            streak += 1
        else:
            break
    risk_state.consecutive_losses = streak


def apply_high_water_mark(risk_state: object, equity: float, hwm: float | None) -> None:
    from cryptobot.risk.engine import RiskState

    if not isinstance(risk_state, RiskState):
        return
    risk_state.equity = equity
    risk_state.high_water_mark = max(hwm or equity, equity)


async def load_risk_state_for_review(
    sessions: SessionFactory,
    account_id: object,
    quote_asset: str,
    default_equity: float,
) -> object:
    """Rebuild RiskState from DB for API halt-clear validation."""
    from cryptobot.risk.engine import RiskState

    _, positions, equity, _, closed_today, hwm = await restore_paper_state(
        sessions, account_id, quote_asset, default_equity,
    )
    state = RiskState(open_positions=len(positions))
    apply_high_water_mark(state, equity, hwm)
    restore_risk_counters(closed_today, state)
    return state
