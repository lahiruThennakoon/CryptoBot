"""Paper account — in-memory balances with strict invariants.

Phase 2 scope: balance accounting only. The fill simulator with the full
cost model (spread/slippage/partial fills) arrives in Phase 3/4 and will
apply fills through this account.

Invariants enforced:
- Balances can never go negative (sell ≤ available, spend ≤ available).
- Every mutation records the fee paid.
- All arithmetic in Decimal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from cryptobot.exchange.models import Side


class InsufficientBalanceError(Exception):
    pass


@dataclass
class PaperFill:
    symbol: str
    side: Side
    price: Decimal
    qty: Decimal
    fee_amount: Decimal
    fee_asset: str


@dataclass
class PaperAccount:
    quote_asset: str = "USDT"
    balances: dict[str, Decimal] = field(default_factory=dict)
    fees_paid: dict[str, Decimal] = field(default_factory=dict)

    @classmethod
    def with_starting_balance(cls, quote_asset: str, amount: Decimal) -> PaperAccount:
        return cls(quote_asset=quote_asset, balances={quote_asset: amount})

    def balance(self, asset: str) -> Decimal:
        return self.balances.get(asset, Decimal(0))

    def apply_fill(self, fill: PaperFill, base_asset: str, quote_asset: str) -> None:
        """Apply a simulated fill atomically; raises before mutating on any violation."""
        if fill.qty <= 0 or fill.price <= 0:
            raise ValueError("Fill qty and price must be positive")
        cost = fill.qty * fill.price

        if fill.side is Side.BUY:
            required_quote = cost + (fill.fee_amount if fill.fee_asset == quote_asset else Decimal(0))
            if self.balance(quote_asset) < required_quote:
                raise InsufficientBalanceError(
                    f"Need {required_quote} {quote_asset}, have {self.balance(quote_asset)}"
                )
            gained_base = fill.qty - (fill.fee_amount if fill.fee_asset == base_asset else Decimal(0))
            self.balances[quote_asset] = self.balance(quote_asset) - required_quote
            self.balances[base_asset] = self.balance(base_asset) + gained_base
        else:
            if self.balance(base_asset) < fill.qty:
                raise InsufficientBalanceError(
                    f"Need {fill.qty} {base_asset}, have {self.balance(base_asset)}"
                )
            gained_quote = cost - (fill.fee_amount if fill.fee_asset == quote_asset else Decimal(0))
            self.balances[base_asset] = self.balance(base_asset) - fill.qty
            self.balances[quote_asset] = self.balance(quote_asset) + gained_quote

        self.fees_paid[fill.fee_asset] = (
            self.fees_paid.get(fill.fee_asset, Decimal(0)) + fill.fee_amount
        )
        assert all(v >= 0 for v in self.balances.values()), "negative balance invariant violated"

    def equity_in_quote(self, prices: dict[str, Decimal]) -> Decimal:
        """Total equity valued in the quote asset. prices: base asset → quote price."""
        total = self.balance(self.quote_asset)
        for asset, amount in self.balances.items():
            if asset == self.quote_asset or amount == 0:
                continue
            price = prices.get(asset)
            if price is None:
                raise ValueError(f"No price provided for {asset}")
            total += amount * price
        return total
