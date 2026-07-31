"""Exchange-agnostic domain models. All money/qty values are Decimal."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(StrEnum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class OrderStatus(StrEnum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"  # client could not confirm state → reconcile before retry

    @property
    def is_terminal(self) -> bool:
        return self in {
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }


class Candle(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    interval: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    trade_count: int
    is_closed: bool = True


class BookLevel(BaseModel):
    model_config = ConfigDict(frozen=True)
    price: Decimal
    qty: Decimal


class OrderBook(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: str
    bids: list[BookLevel]
    asks: list[BookLevel]
    fetched_at: datetime

    @property
    def best_bid(self) -> BookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> BookLevel | None:
        return self.asks[0] if self.asks else None

    @property
    def spread(self) -> Decimal | None:
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return None

    @property
    def mid(self) -> Decimal | None:
        if self.best_bid and self.best_ask:
            return (self.best_ask.price + self.best_bid.price) / 2
        return None


class SymbolRules(BaseModel):
    """Trading rules for one symbol, parsed from exchangeInfo filters."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    base_asset: str
    quote_asset: str
    status: str
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    max_qty: Decimal
    min_notional: Decimal
    raw_filters: tuple[dict[str, str], ...] = ()

    @property
    def is_trading(self) -> bool:
        return self.status == "TRADING"


class ExchangeRules(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbols: dict[str, SymbolRules]
    fetched_at: datetime


class Balance(BaseModel):
    model_config = ConfigDict(frozen=True)
    asset: str
    free: Decimal
    locked: Decimal

    @property
    def total(self) -> Decimal:
        return self.free + self.locked


class AccountState(BaseModel):
    model_config = ConfigDict(frozen=True)
    balances: dict[str, Balance]
    can_trade: bool
    can_withdraw: bool  # MUST be False for any key this system uses
    fetched_at: datetime


class OrderRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    side: Side
    type: OrderType
    quantity: Decimal
    client_order_id: str = Field(min_length=8, max_length=36)  # idempotency key
    price: Decimal | None = None
    time_in_force: TimeInForce | None = None


class Fill(BaseModel):
    model_config = ConfigDict(frozen=True)
    trade_id: str
    price: Decimal
    qty: Decimal
    fee_amount: Decimal
    fee_asset: str
    is_maker: bool = False


class OrderState(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    client_order_id: str
    exchange_order_id: str | None
    status: OrderStatus
    side: Side
    type: OrderType
    orig_qty: Decimal
    executed_qty: Decimal
    cumulative_quote_qty: Decimal
    price: Decimal | None
    fills: tuple[Fill, ...] = ()
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def avg_fill_price(self) -> Decimal | None:
        if self.executed_qty > 0:
            return self.cumulative_quote_qty / self.executed_qty
        return None


class MarketEventType(StrEnum):
    KLINE = "kline"
    TRADE = "trade"


class MarketEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: MarketEventType
    symbol: str
    received_at: datetime
    candle: Candle | None = None
    payload: dict[str, object] = Field(default_factory=dict)
