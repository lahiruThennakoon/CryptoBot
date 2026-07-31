"""SQLAlchemy models (Phase 2 subset of docs/database-schema.md).

Money/qty: NUMERIC(38,18). Timestamps: timestamptz UTC. Append-only tables
(fills, audit_events, balance_snapshots) are never updated or deleted by the
application.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

MONEY = Numeric(38, 18)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {
        Decimal: MONEY,
        datetime: DateTime(timezone=True),
        dict: JSON,
    }


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    base_asset: Mapped[str] = mapped_column(String(16))
    quote_asset: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    tick_size: Mapped[Decimal]
    step_size: Mapped[Decimal]
    min_qty: Mapped[Decimal]
    max_qty: Mapped[Decimal]
    min_notional: Mapped[Decimal]
    filters_raw: Mapped[dict] = mapped_column(JSON, default=dict)
    filters_updated_at: Mapped[datetime] = mapped_column(default=utcnow)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class CandleRow(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "interval", "open_time", name="uq_candle"),
        Index("ix_candles_lookup", "symbol", "interval", "open_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32))
    interval: Mapped[str] = mapped_column(String(8))
    open_time: Mapped[datetime]
    open: Mapped[Decimal]
    high: Mapped[Decimal]
    low: Mapped[Decimal]
    close: Mapped[Decimal]
    volume: Mapped[Decimal]
    quote_volume: Mapped[Decimal]
    trade_count: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16), default="ws")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    mode: Mapped[str] = mapped_column(String(16))  # paper | testnet | live
    label: Mapped[str] = mapped_column(String(64), default="default")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (UniqueConstraint("mode", "label", name="uq_account_mode_label"),)


class BalanceSnapshot(Base):
    __tablename__ = "balance_snapshots"  # append-only

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    asset: Mapped[str] = mapped_column(String(16))
    free: Mapped[Decimal]
    locked: Mapped[Decimal]
    taken_at: Mapped[datetime] = mapped_column(default=utcnow)
    reason: Mapped[str] = mapped_column(String(32), default="schedule")


class OrderRow(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True)  # idempotency backstop
    exchange_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    side: Mapped[str] = mapped_column(String(8))
    type: Mapped[str] = mapped_column(String(16))
    time_in_force: Mapped[str | None] = mapped_column(String(8), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    qty: Mapped[Decimal]
    status: Mapped[str] = mapped_column(String(24), default="new", index=True)
    role: Mapped[str] = mapped_column(String(16), default="entry")
    submitted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_exchange_sync_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class FillRow(Base):
    __tablename__ = "fills"  # append-only
    __table_args__ = (
        UniqueConstraint("order_id", "exchange_trade_id", name="uq_fill_dedupe"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"))
    exchange_trade_id: Mapped[str] = mapped_column(String(64))
    price: Mapped[Decimal]
    qty: Mapped[Decimal]
    fee_amount: Mapped[Decimal]
    fee_asset: Mapped[str] = mapped_column(String(16))
    is_maker: Mapped[bool] = mapped_column(Boolean, default=False)
    filled_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"  # append-only
    __table_args__ = (Index("ix_audit_category_time", "category", "occurred_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(32), default="system")
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # redacted upstream
    occurred_at: Mapped[datetime] = mapped_column(default=utcnow)


class SignalRow(Base):
    __tablename__ = "signals"  # append-only; includes NO_TRADE and rejections
    __table_args__ = (Index("ix_signals_time", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    symbol: Mapped[str] = mapped_column(String(32))
    strategy: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(16))       # buy | sell | no_trade
    confidence: Mapped[Decimal] = mapped_column(MONEY, default=0)
    regime: Mapped[str] = mapped_column(String(16), default="unknown")
    outcome: Mapped[str] = mapped_column(String(32))    # executed | rejected_* | no_trade
    rejection_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PositionRow(Base):
    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    qty: Mapped[Decimal]
    avg_entry_price: Mapped[Decimal]
    stop_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    take_profit_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    strategy: Mapped[str] = mapped_column(String(64), default="")
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, default=0)
    fees_paid: Mapped[Decimal] = mapped_column(MONEY, default=0)
    max_holding_until: Mapped[datetime | None] = mapped_column(nullable=True)
    opened_at: Mapped[datetime] = mapped_column(default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    exit_reason: Mapped[str] = mapped_column(String(32), default="")


class RiskEventRow(Base):
    __tablename__ = "risk_events"  # append-only

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    event_type: Mapped[str] = mapped_column(String(32))  # halt | resume | emergency_stop | ...
    limit_name: Mapped[str] = mapped_column(String(48), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime] = mapped_column(default=utcnow)
    acknowledged_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class DailyReportRow(Base):
    __tablename__ = "daily_reports"
    __table_args__ = (UniqueConstraint("account_id", "report_date", name="uq_daily_report"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    report_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    content: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"  # append-only; feeds dashboard equity curve
    __table_args__ = (Index("ix_equity_time", "account_id", "taken_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    equity: Mapped[Decimal]
    cash: Mapped[Decimal]
    exposure: Mapped[Decimal] = mapped_column(MONEY, default=0)
    taken_at: Mapped[datetime] = mapped_column(default=utcnow)


class PairSettingRow(Base):
    __tablename__ = "pair_settings"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # bot NEVER trades when False
    risk_per_trade: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    max_position_pct: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    min_confidence: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    allowed_strategies: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"names": [...]}
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(64), default="operator")


class SessionConfigRow(Base):
    __tablename__ = "session_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), unique=True)
    session_start_utc: Mapped[str] = mapped_column(String(5), default="00:00")
    session_end_utc: Mapped[str] = mapped_column(String(5), default="23:59")
    trading_days: Mapped[dict] = mapped_column(JSON, default=lambda: {"days": [0, 1, 2, 3, 4, 5, 6]})
    overnight_policy: Mapped[str] = mapped_column(String(24), default="hold")
    daily_profit_target_pct: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    target_protection: Mapped[str] = mapped_column(String(24), default="stop_trading")
    max_capital: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class DecisionRow(Base):
    __tablename__ = "decisions"  # append-only
    __table_args__ = (Index("ix_decisions_symbol_time", "symbol", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    symbol: Mapped[str] = mapped_column(String(32))
    decision: Mapped[str] = mapped_column(String(16))   # buy|sell|hold|close|no_trade
    status: Mapped[str] = mapped_column(String(24))     # strong_buy..data_unavailable
    confidence: Mapped[Decimal] = mapped_column(MONEY, default=0)
    score: Mapped[Decimal] = mapped_column(MONEY, default=0)
    supporting: Mapped[dict] = mapped_column(JSON, default=dict)
    conflicting: Mapped[dict] = mapped_column(JSON, default=dict)
    entry_estimate: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    expected_holding_bars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    est_fees: Mapped[Decimal] = mapped_column(MONEY, default=0)
    est_spread: Mapped[Decimal] = mapped_column(MONEY, default=0)
    est_slippage: Mapped[Decimal] = mapped_column(MONEY, default=0)
    expected_gross_return: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    expected_net_return: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    reasons: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AiConversationRow(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    title: Mapped[str] = mapped_column(String(120), default="Conversation")
    explanation_mode: Mapped[str] = mapped_column(String(16), default="simple")
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    cleared_at: Mapped[datetime | None] = mapped_column(nullable=True)


class AiMessageRow(Base):
    __tablename__ = "ai_messages"  # append-only
    __table_args__ = (Index("ix_ai_messages_conv", "conversation_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_conversations.id"))
    role: Mapped[str] = mapped_column(String(12))          # user | assistant
    content: Mapped[str] = mapped_column(Text)             # redacted upstream
    tools_used: Mapped[dict] = mapped_column(JSON, default=dict)
    data_timestamps: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AiUsageRow(Base):
    __tablename__ = "ai_usage"  # append-only
    __table_args__ = (Index("ix_ai_usage_time", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    model: Mapped[str] = mapped_column(String(64))
    route_reason: Mapped[str] = mapped_column(Text, default="")
    prompt_version: Mapped[str] = mapped_column(String(16), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(MONEY, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class DrillAckRow(Base):
    """Operator's record that a readiness drill was run and passed.

    One row per drill (latest state). Every change is ALSO written to
    audit_events, so the history of who claimed what, and when, is permanent.
    """

    __tablename__ = "drill_acknowledgements"

    drill_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by: Mapped[str] = mapped_column(String(64), default="operator")
    notes: Mapped[str] = mapped_column(Text, default="")
    acknowledged_at: Mapped[datetime | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class ConfigVersion(Base):
    __tablename__ = "config_versions"  # append-only; secrets NEVER stored here

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    scope: Mapped[str] = mapped_column(String(32), default="app")
    content: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    change_note: Mapped[str] = mapped_column(Text, default="")
