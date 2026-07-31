"""Live cost discovery tests: fee parsing, slippage from depth, provenance honesty."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cryptobot.costs.live import (
    ASSUMED_TAKER,
    FeeService,
    Provenance,
    build_live_cost_model,
    estimate_slippage,
    parse_account_commission_rates,
    parse_commission_response,
)
from cryptobot.exchange.models import BookLevel, OrderBook

D = Decimal


def book(asks: list[tuple[str, str]], bids: list[tuple[str, str]] | None = None) -> OrderBook:
    return OrderBook(
        symbol="BTCUSDT",
        asks=[BookLevel(price=D(p), qty=D(q)) for p, q in asks],
        bids=[BookLevel(price=D(p), qty=D(q)) for p, q in (bids or [("99.9", "10")])],
        fetched_at=datetime.now(UTC),
    )


class TestCommissionParsing:
    def test_standard_plus_tax_with_bnb_discount(self):
        """Per the official commission FAQ: discount applies to standard only."""
        raw = {
            "symbol": "BTCUSDT",
            "standardCommission": {"maker": "0.001", "taker": "0.001",
                                   "buyer": "0", "seller": "0"},
            "taxCommission": {"maker": "0.0001", "taker": "0.0001",
                              "buyer": "0", "seller": "0"},
            "specialCommission": {"maker": "0", "taker": "0", "buyer": "0", "seller": "0"},
            "discount": {"enabledForAccount": True, "enabledForSymbol": True,
                         "discountAsset": "BNB", "discount": "0.25"},
        }
        schedule = parse_commission_response(raw, "BTCUSDT")
        # 0.001 * 0.75 + 0.0001 = 0.00085
        assert abs(schedule.taker_rate - 0.00085) < 1e-9
        assert schedule.provenance is Provenance.LIVE
        assert schedule.discount_applied == 0.25
        assert "BNB" in schedule.detail

    def test_discount_ignored_when_not_enabled(self):
        raw = {
            "standardCommission": {"maker": "0.001", "taker": "0.001"},
            "discount": {"enabledForAccount": False, "enabledForSymbol": True,
                         "discountAsset": "BNB", "discount": "0.25"},
        }
        schedule = parse_commission_response(raw, "BTCUSDT")
        assert abs(schedule.taker_rate - 0.001) < 1e-9
        assert schedule.discount_applied == 0.0

    def test_special_commission_not_discounted(self):
        raw = {
            "standardCommission": {"taker": "0.001", "maker": "0.001"},
            "specialCommission": {"taker": "0.002", "maker": "0.002"},
            "discount": {"enabledForAccount": True, "enabledForSymbol": True,
                         "discount": "0.25", "discountAsset": "BNB"},
        }
        schedule = parse_commission_response(raw, "BTCUSDT")
        assert abs(schedule.taker_rate - (0.001 * 0.75 + 0.002)) < 1e-9

    def test_account_wide_fallback(self):
        raw = {"commissionRates": {"maker": "0.001", "taker": "0.0015", "buyer": "0",
                                   "seller": "0"}}
        schedule = parse_account_commission_rates(raw, "ETHUSDT")
        assert schedule.taker_rate == 0.0015
        assert schedule.provenance is Provenance.LIVE
        assert "account-wide" in schedule.detail


class TestFeeService:
    class _Client:
        def __init__(self, responses: dict[str, object]):
            self.responses = responses
            self.calls: list[str] = []

        async def request(self, method: str, path: str, **kwargs: object) -> object:
            self.calls.append(path)
            value = self.responses.get(path)
            if isinstance(value, Exception):
                raise value
            if value is None:
                raise RuntimeError(f"no stub for {path}")
            return value

    async def test_prefers_per_symbol_commission(self):
        client = self._Client({"/v3/account/commission": {
            "standardCommission": {"maker": "0.0008", "taker": "0.0009"},
            "discount": {},
        }})
        schedule = await FeeService(client).get("BTCUSDT")
        assert schedule.taker_rate == 0.0009
        assert schedule.provenance is Provenance.LIVE
        assert client.calls == ["/v3/account/commission"]

    async def test_falls_back_to_account_endpoint(self):
        client = self._Client({
            "/v3/account/commission": RuntimeError("not supported here"),
            "/v3/account": {"commissionRates": {"maker": "0.001", "taker": "0.001"}},
        })
        schedule = await FeeService(client).get("BTCUSDT")
        assert schedule.provenance is Provenance.LIVE
        assert "/v3/account" in client.calls

    async def test_falls_back_to_assumption_and_says_so(self):
        client = self._Client({
            "/v3/account/commission": RuntimeError("down"),
            "/v3/account": RuntimeError("down"),
        })
        schedule = await FeeService(client).get("BTCUSDT")
        assert schedule.provenance is Provenance.ASSUMED
        assert schedule.taker_rate == ASSUMED_TAKER
        assert "conservative" in schedule.detail

    async def test_caches_within_window(self):
        client = self._Client({"/v3/account/commission": {
            "standardCommission": {"taker": "0.0009", "maker": "0.0008"}, "discount": {}}})
        service = FeeService(client)
        await service.get("BTCUSDT")
        await service.get("BTCUSDT")
        assert client.calls.count("/v3/account/commission") == 1   # cached

    async def test_force_refresh_bypasses_cache(self):
        client = self._Client({"/v3/account/commission": {
            "standardCommission": {"taker": "0.0009", "maker": "0.0008"}, "discount": {}}})
        service = FeeService(client)
        await service.get("BTCUSDT")
        await service.get("BTCUSDT", force=True)
        assert client.calls.count("/v3/account/commission") == 2


class TestSlippageFromDepth:
    def test_deep_book_gives_small_slippage(self):
        estimate = estimate_slippage(book([("100", "100"), ("100.1", "100")]), 1000)
        assert estimate.depth_sufficient
        assert estimate.fraction < 0.001
        assert estimate.provenance is Provenance.LIVE

    def test_thin_book_gives_larger_slippage(self):
        thin = estimate_slippage(book([("100", "0.5"), ("101", "0.5"), ("103", "5")]), 500)
        deep = estimate_slippage(book([("100", "1000")]), 500)
        assert thin.fraction > deep.fraction

    def test_exhausted_book_is_flagged_and_penalised(self):
        """An order the book cannot absorb must be flagged insufficient — the
        fraction alone is not the protection, depth_sufficient=False is."""
        estimate = estimate_slippage(book([("100", "1")]), 10_000)
        assert not estimate.depth_sufficient
        assert "EXHAUSTED" in estimate.detail
        assert estimate.fraction >= 0.005          # penalty scales with unfilled portion

    def test_penalty_scales_with_unfilled_portion(self):
        mostly_fills = estimate_slippage(book([("100", "95"), ("100.1", "0")]), 10_000)
        barely_fills = estimate_slippage(book([("100", "1")]), 10_000)
        assert barely_fills.fraction > mostly_fills.fraction
        assert not mostly_fills.depth_sufficient

    def test_no_book_falls_back_labelled(self):
        empty = OrderBook(symbol="X", asks=[], bids=[], fetched_at=datetime.now(UTC))
        estimate = estimate_slippage(empty, 1000)
        assert estimate.provenance is Provenance.ASSUMED

    def test_larger_orders_slip_more(self):
        levels = [("100", "1"), ("100.5", "1"), ("101", "1"), ("102", "10")]
        small = estimate_slippage(book(levels), 100)
        large = estimate_slippage(book(levels), 350)
        assert large.fraction > small.fraction


class TestLiveCostModel:
    def test_composes_live_values_and_reports_provenance(self):
        from cryptobot.costs.live import FeeSchedule
        import time

        fees = FeeSchedule("BTCUSDT", 0.0008, 0.0009, provenance=Provenance.LIVE,
                           fetched_at=time.time(), detail="live")
        basis = build_live_cost_model(
            "BTCUSDT", fees, book([("100", "1000")], [("99.98", "1000")]), 1000)
        assert basis.model.taker_fee == 0.0009
        assert basis.all_live
        assert "round trip" in basis.summary()

    def test_missing_book_flags_partial_assumption(self):
        from cryptobot.costs.live import FeeSchedule

        fees = FeeSchedule("BTCUSDT", 0.001, 0.001, provenance=Provenance.ASSUMED)
        basis = build_live_cost_model("BTCUSDT", fees, None, 1000)
        assert not basis.all_live
        assert any("assum" in n.lower() for n in basis.notes)

    def test_real_fees_change_the_cost_gate(self):
        """The whole point: cheaper real fees let marginal trades through, and
        expensive real fees correctly block them."""
        from cryptobot.costs.live import FeeSchedule
        import time

        cheap = build_live_cost_model(
            "BTCUSDT", FeeSchedule("BTCUSDT", 0.0002, 0.0004, provenance=Provenance.LIVE,
                                   fetched_at=time.time()),
            book([("100", "1000")], [("99.99", "1000")]), 1000).model
        pricey = build_live_cost_model(
            "BTCUSDT", FeeSchedule("BTCUSDT", 0.002, 0.003, provenance=Provenance.LIVE,
                                   fetched_at=time.time()),
            book([("100", "1000")], [("99.99", "1000")]), 1000).model
        edge = 0.004
        assert cheap.passes_cost_gate(edge)
        assert not pricey.passes_cost_gate(edge)