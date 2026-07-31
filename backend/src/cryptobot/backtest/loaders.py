"""Candle loaders for backtesting: database and CSV."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from cryptobot.db.models import CandleRow
from cryptobot.db.session import SessionFactory


@dataclass(frozen=True)
class Bar:
    """Lightweight float bar for simulation (BarLike-compatible)."""

    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def load_csv(path: str | Path) -> list[Bar]:
    """CSV columns: open_time (ISO8601 or epoch ms), open, high, low, close, volume."""
    bars: list[Bar] = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            raw = row["open_time"].strip()
            if raw.isdigit():
                ts = datetime.fromtimestamp(int(raw) / 1000, tz=UTC)
            else:
                ts = datetime.fromisoformat(raw)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
            bars.append(Bar(
                open_time=ts, open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]), volume=float(row["volume"]),
            ))
    bars.sort(key=lambda b: b.open_time)
    return bars


async def load_db(
    sessions: SessionFactory,
    symbol: str,
    interval: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Bar]:
    async with sessions() as session:
        stmt = (
            select(CandleRow)
            .where(CandleRow.symbol == symbol, CandleRow.interval == interval)
            .order_by(CandleRow.open_time)
        )
        if start:
            stmt = stmt.where(CandleRow.open_time >= start)
        if end:
            stmt = stmt.where(CandleRow.open_time <= end)
        rows = (await session.execute(stmt)).scalars().all()
    return [
        Bar(
            open_time=r.open_time, open=float(r.open), high=float(r.high),
            low=float(r.low), close=float(r.close), volume=float(r.volume),
        )
        for r in rows
    ]
