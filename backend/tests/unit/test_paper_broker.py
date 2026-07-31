from decimal import Decimal

import pytest

from cryptobot.costs.model import CostModel
from cryptobot.exchange.models import Side
from cryptobot.paper.account import InsufficientBalanceError, PaperAccount
from cryptobot.paper.broker import PaperBroker

D = Decimal


def broker(usdt: str = "10000") -> PaperBroker:
    return PaperBroker(
        PaperAccount.with_starting_balance("USDT", D(usdt)),
        CostModel(taker_fee=0.001, half_spread=0.0003, slippage=0.0005, latency_drift=0.0002),
    )


class TestPaperBroker:
    def test_buy_fill_is_worse_than_reference(self):
        b = broker()
        ex = b.execute_market("BTCUSDT", Side.BUY, D("0.01"), D("50000"), "BTC", "USDT")
        assert ex.fill_price > D("50000")
        assert ex.fee > 0
        assert ex.slippage_cost > 0

    def test_sell_fill_is_worse_than_reference(self):
        b = broker()
        b.execute_market("BTCUSDT", Side.BUY, D("0.01"), D("50000"), "BTC", "USDT")
        ex = b.execute_market("BTCUSDT", Side.SELL, D("0.01"), D("50000"), "BTC", "USDT")
        assert ex.fill_price < D("50000")

    def test_round_trip_at_same_price_loses_money(self):
        b = broker()
        b.execute_market("BTCUSDT", Side.BUY, D("0.01"), D("50000"), "BTC", "USDT")
        b.execute_market("BTCUSDT", Side.SELL, D("0.01"), D("50000"), "BTC", "USDT")
        assert b.account.balance("USDT") < D("10000")
        assert b.account.balance("BTC") == 0

    def test_cannot_buy_beyond_balance(self):
        b = broker("100")
        with pytest.raises(InsufficientBalanceError):
            b.execute_market("BTCUSDT", Side.BUY, D("1"), D("50000"), "BTC", "USDT")
        assert b.account.balance("USDT") == D("100")

    def test_cannot_sell_what_you_do_not_hold(self):
        b = broker()
        with pytest.raises(InsufficientBalanceError):
            b.execute_market("BTCUSDT", Side.SELL, D("1"), D("50000"), "BTC", "USDT")

    def test_rejects_nonpositive_inputs(self):
        b = broker()
        with pytest.raises(ValueError):
            b.execute_market("BTCUSDT", Side.BUY, D("0"), D("50000"), "BTC", "USDT")
        with pytest.raises(ValueError):
            b.execute_market("BTCUSDT", Side.BUY, D("1"), D("0"), "BTC", "USDT")

    def test_unique_client_order_ids(self):
        b = broker()
        a = b.execute_market("BTCUSDT", Side.BUY, D("0.001"), D("50000"), "BTC", "USDT")
        c = b.execute_market("BTCUSDT", Side.BUY, D("0.001"), D("50000"), "BTC", "USDT")
        assert a.client_order_id != c.client_order_id