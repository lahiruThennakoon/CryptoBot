from decimal import Decimal

import pytest

from cryptobot.exchange.models import Side
from cryptobot.paper.account import InsufficientBalanceError, PaperAccount, PaperFill

D = Decimal


def _account(usdt: str = "10000") -> PaperAccount:
    return PaperAccount.with_starting_balance("USDT", D(usdt))


def _buy(qty: str, price: str, fee: str = "0") -> PaperFill:
    return PaperFill(symbol="BTCUSDT", side=Side.BUY, price=D(price), qty=D(qty),
                     fee_amount=D(fee), fee_asset="USDT")


class TestPaperAccount:
    def test_buy_moves_quote_to_base(self):
        acct = _account()
        acct.apply_fill(_buy("0.1", "50000"), "BTC", "USDT")
        assert acct.balance("USDT") == D("5000")
        assert acct.balance("BTC") == D("0.1")

    def test_buy_records_fee(self):
        acct = _account()
        acct.apply_fill(_buy("0.1", "50000", fee="5"), "BTC", "USDT")
        assert acct.balance("USDT") == D("4995")
        assert acct.fees_paid["USDT"] == D("5")

    def test_cannot_overspend(self):
        acct = _account("100")
        with pytest.raises(InsufficientBalanceError):
            acct.apply_fill(_buy("1", "50000"), "BTC", "USDT")
        assert acct.balance("USDT") == D("100")  # unchanged after rejection

    def test_cannot_oversell(self):
        acct = _account()
        sell = PaperFill(symbol="BTCUSDT", side=Side.SELL, price=D("50000"),
                         qty=D("1"), fee_amount=D("0"), fee_asset="USDT")
        with pytest.raises(InsufficientBalanceError):
            acct.apply_fill(sell, "BTC", "USDT")

    def test_round_trip_with_fees_loses_money(self):
        """Sanity: fees make a flat round trip negative — no free profits."""
        acct = _account()
        acct.apply_fill(_buy("0.1", "50000", fee="5"), "BTC", "USDT")
        sell = PaperFill(symbol="BTCUSDT", side=Side.SELL, price=D("50000"),
                         qty=D("0.1"), fee_amount=D("5"), fee_asset="USDT")
        acct.apply_fill(sell, "BTC", "USDT")
        assert acct.balance("USDT") == D("9990")
        assert acct.balance("BTC") == D("0")

    def test_equity_valuation(self):
        acct = _account()
        acct.apply_fill(_buy("0.1", "50000"), "BTC", "USDT")
        equity = acct.equity_in_quote({"BTC": D("52000")})
        assert equity == D("5000") + D("0.1") * D("52000")

    def test_equity_requires_price_for_held_assets(self):
        acct = _account()
        acct.apply_fill(_buy("0.1", "50000"), "BTC", "USDT")
        with pytest.raises(ValueError, match="No price"):
            acct.equity_in_quote({})
