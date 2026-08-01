"""Tests for FR-4.4 near-miss detection."""

from cryptobot.costs.model import CostModel
from cryptobot.risk.near_miss import near_miss_confidence, near_miss_cost_gate


class TestNearMissCostGate:
    def test_detects_when_edge_slightly_short(self):
        costs = CostModel(maker_fee=0.001, taker_fee=0.001, safety_margin=0.001)
        req = costs.round_trip_fraction + costs.safety_margin
        edge = req - 0.0005
        nm = near_miss_cost_gate(edge, costs, margin=0.001)
        assert nm is not None
        assert nm.rejection_code == "NEAR_MISS_COST_GATE"

    def test_none_when_far_short(self):
        costs = CostModel()
        req = costs.round_trip_fraction + costs.safety_margin
        assert near_miss_cost_gate(req - 0.01, costs, margin=0.001) is None

    def test_none_when_passes(self):
        costs = CostModel()
        req = costs.round_trip_fraction + costs.safety_margin
        assert near_miss_cost_gate(req + 0.001, costs, margin=0.001) is None


class TestNearMissConfidence:
    def test_detects_close_confidence(self):
        nm = near_miss_confidence(0.58, 0.60, margin=0.05)
        assert nm is not None
        assert nm.rejection_code == "NEAR_MISS_CONFIDENCE"

    def test_none_when_too_low(self):
        assert near_miss_confidence(0.40, 0.60, margin=0.05) is None
