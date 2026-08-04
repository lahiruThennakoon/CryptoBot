"""Startup reconciliation — compare local state vs exchange before trading (FR-2.8)."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select

from cryptobot.core.logging import get_logger
from cryptobot.db.models import OrderRow, PositionRow
from cryptobot.db.session import SessionFactory
from cryptobot.exchange.adapter import ExchangeAdapter

logger = get_logger(__name__)


@dataclass
class ReconcileReport:
    ok: bool
    mode: str
    checks: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)


async def reconcile_on_startup(
    sessions: SessionFactory,
    account_id: object,
    quote_asset: str,
    execution_mode: str,
    adapter: ExchangeAdapter | None,
    memory_open_symbols: set[str],
) -> ReconcileReport:
    """Reconcile DB + in-memory state; testnet also checks exchange balances."""
    report = ReconcileReport(ok=True, mode=execution_mode)

    async with sessions() as session:
        db_open = (await session.execute(
            select(PositionRow).where(
                PositionRow.account_id == account_id,
                PositionRow.status == "open",
            )
        )).scalars().all()
        db_symbols = {p.symbol for p in db_open}
        open_orders = (await session.execute(
            select(OrderRow).where(
                OrderRow.account_id == account_id,
                OrderRow.status.notin_(("filled", "canceled", "rejected", "expired")),
            )
        )).scalars().all()

    if db_symbols != memory_open_symbols:
        msg = f"position mismatch: db={sorted(db_symbols)} memory={sorted(memory_open_symbols)}"
        report.mismatches.append(msg)
        report.ok = False
    else:
        report.checks.append(f"positions aligned ({len(db_symbols)} open)")

    if open_orders and execution_mode == "testnet":
        report.mismatches.append(
            f"{len(open_orders)} local open orders — verify on exchange manually"
        )
        report.ok = False

    if execution_mode == "testnet" and adapter is not None:
        try:
            account = await adapter.get_account()
            exchange_bases = {
                asset: float(bal.free) + float(bal.locked)
                for asset, bal in account.balances.items()
                if asset != quote_asset and (float(bal.free) + float(bal.locked)) > 0
            }
            for sym in memory_open_symbols:
                base = sym.removesuffix(quote_asset)
                db_qty = next((float(p.qty) for p in db_open if p.symbol == sym), 0.0)
                ex_qty = exchange_bases.get(base, 0.0)
                if abs(db_qty - ex_qty) > max(db_qty, ex_qty, 1e-8) * 0.01:
                    report.mismatches.append(
                        f"{sym}: db qty {db_qty:.8f} vs exchange {ex_qty:.8f}"
                    )
                    report.ok = False
                else:
                    report.checks.append(f"{sym} balance aligned")
            orders = await adapter.get_open_orders()
            if orders:
                report.mismatches.append(f"{len(orders)} open orders on exchange")
                report.ok = False
            else:
                report.checks.append("no open exchange orders")
        except Exception as exc:  # noqa: BLE001
            report.mismatches.append(f"exchange reconcile failed: {type(exc).__name__}: {exc}")
            report.ok = False
    elif execution_mode == "paper":
        report.checks.append("paper mode — DB/memory position check only")

    logger.info(
        "reconciliation_complete",
        ok=report.ok,
        mode=execution_mode,
        checks=report.checks,
        mismatches=report.mismatches,
    )
    return report
