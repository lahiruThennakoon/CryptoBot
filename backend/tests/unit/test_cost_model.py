import math

from cryptobot.costs.model import CostModel


class TestCostModel:
    def test_buy_fill_always_worse_than_reference(self):
        m = CostModel()
        assert m.buy_fill_price(100.0) > 100.0
        assert m.sell_fill_price(100.0) < 100.0

    def test_round_trip_fraction(self):
        m = CostModel(taker_fee=0.001, half_spread=0.0003, slippage=0.0005, latency_drift=0.0002)
        assert math.isclose(m.round_trip_fraction, 2 * (0.001 + 0.0003 + 0.0005 + 0.0002))

    def test_cost_gate_requires_margin_beyond_costs(self):
        m = CostModel(taker_fee=0.001, half_spread=0.0003, slippage=0.0005,
                      latency_drift=0.0002, safety_margin=0.001)
        assert not m.passes_cost_gate(m.round_trip_fraction)              # costs only → no
        assert not m.passes_cost_gate(m.round_trip_fraction + 0.0009)     # inside margin → no
        assert m.passes_cost_gate(m.round_trip_fraction + 0.0011)         # clears margin → yes

    def test_stressed_scales_costs(self):
        m = CostModel(taker_fee=0.001, slippage=0.0005)
        s = m.stressed(fee_mult=2.0, slippage_mult=3.0)
        assert math.isclose(s.taker_fee, 0.002)
        assert math.isclose(s.slippage, 0.0015)
        assert s.round_trip_fraction > m.round_trip_fraction

    def test_fee_on_notional(self):
        assert math.isclose(CostModel(taker_fee=0.001).fee(10_000.0), 10.0)