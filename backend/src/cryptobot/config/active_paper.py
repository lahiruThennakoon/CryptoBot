"""Active paper profile — frequent real-strategy trades with simulated costs.

Aggressive paper settings so operators see entries and PnL feedback quickly.
Expect more fee drag and drawdowns; not for live trading or graduation evidence
on its own — pair with backtests for GC-4.
"""

from __future__ import annotations

from dataclasses import replace

from cryptobot.costs.model import CostModel
from cryptobot.decision.scoring import Gates
from cryptobot.execution.policy import ExecutionPolicy, OrderStyle
from cryptobot.risk.engine import RiskConfig
from cryptobot.strategies.base import Strategy
from cryptobot.strategies.breakout_volatility import BreakoutVolatilityStrategy
from cryptobot.strategies.ma_trend import MaTrendStrategy
from cryptobot.strategies.momentum_volume import MomentumVolumeStrategy
from cryptobot.strategies.mtf_trend import MultiTimeframeTrendStrategy
from cryptobot.strategies.rsi_reversion import RsiReversionStrategy

ACTIVE_PAPER_GATES = Gates(
    buy_threshold=0.08,
    strong_buy_threshold=0.18,
    max_spread_fraction=0.008,
    require_strategy_entry=True,
    skip_cost_gate=True,
)

ACTIVE_PAPER_POLICY = ExecutionPolicy(entry_style=OrderStyle.MARKET)


def build_active_paper_strategies() -> list[Strategy]:
    """Baseline strategies with aggressive entry thresholds for paper feedback."""
    return [
        MomentumVolumeStrategy(min_return=0.003, volume_mult=1.0),
        RsiReversionStrategy(oversold=42.0, exit_level=55.0),
        BreakoutVolatilityStrategy(max_vol_rank=0.98, channel_n=14),
        MaTrendStrategy(fast=10, slow=30),
        MultiTimeframeTrendStrategy(htf_fast=8, htf_slow=20, ltf_fast=12),
    ]


def apply_active_paper_risk(base: RiskConfig) -> RiskConfig:
    return replace(
        base,
        risk_per_trade=0.01,
        max_position_pct=0.12,
        max_exposure_pct=0.40,
        max_positions=4,
        max_trades_per_day=30,
        min_confidence=0.25,
        max_daily_loss_pct=0.08,
        max_drawdown_pct=0.20,
        max_consecutive_losses=8,
    )


def apply_active_paper_costs(base: CostModel) -> CostModel:
    return replace(base, safety_margin=0.0)
