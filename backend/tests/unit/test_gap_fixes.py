"""Tests for gap fixes: controls, state restore, reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryptobot.paper.account import PaperAccount
from cryptobot.risk.engine import RiskState
from cryptobot.runtime.controls import ControlService, ControlState
from cryptobot.runtime.engine import OpenPosition
from cryptobot.runtime.state_restore import restore_risk_counters


def test_control_state_blocks_on_risk_halt() -> None:
    state = ControlState(risk_halted=True, risk_halt_reason="daily loss")
    assert state.trading_allowed is False


def test_risk_state_clear_halt() -> None:
    state = RiskState(halted=True, halt_reason="max drawdown")
    state.clear_halt()
    assert state.halted is False
    assert state.halt_reason == ""


def test_restore_risk_counters_from_closed_today() -> None:
    from cryptobot.db.models import PositionRow

    row = PositionRow(
        symbol="BTCUSDT", status="closed", qty=Decimal("0.1"),
        avg_entry_price=Decimal("50000"), realized_pnl=Decimal("-10"),
        closed_at=datetime.now(UTC),
    )
    risk = RiskState()
    restore_risk_counters([row], risk)
    assert risk.trades_today == 1
    assert risk.daily_realized_pnl == -10.0
    assert risk.consecutive_losses == 1


def test_engine_restore_positions() -> None:
    from cryptobot.runtime.engine import TradingRuntime
    from cryptobot.paper.broker import PaperBroker
    from cryptobot.risk.engine import BasicRiskEngine
    from cryptobot.costs.model import CostModel

    account = PaperAccount.with_starting_balance("USDT", Decimal("1000"))
    runtime = TradingRuntime(
        broker=PaperBroker(account, CostModel()),
        strategies=[], risk=BasicRiskEngine(), costs=CostModel(),
    )
    pos = OpenPosition(
        position_id="abc", symbol="BTCUSDT", qty=Decimal("0.01"),
        entry_price=Decimal("50000"), stop_price=Decimal("49000"),
        take_profit=None, strategy="ranked_batch",
        opened_at=datetime.now(UTC), max_holding_until=datetime.now(UTC),
    )
    runtime.restore_positions([pos])
    assert "BTCUSDT" in runtime._positions
    assert runtime._risk_state.open_positions == 1


@pytest.mark.asyncio
async def test_resume_clears_estop(monkeypatch: pytest.MonkeyPatch) -> None:
    """resume() must clear both pause and emergency stop keys."""
    calls: list[str] = []

    class FakeRedis:
        async def mget(self, *keys: str) -> list:
            return ["0", "0", "0", ""]

        async def delete(self, *keys: str) -> None:
            calls.extend(keys)

        async def aclose(self) -> None:
            pass

    svc = ControlService.__new__(ControlService)
    svc._redis = FakeRedis()
    await svc.resume()
    assert "cryptobot:control:paused" in calls
    assert "cryptobot:control:emergency_stop" in calls
