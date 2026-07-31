from cryptobot.strategies.base import Intent, Signal, Strategy, StrategySpec
from cryptobot.strategies.breakout_volatility import BreakoutVolatilityStrategy
from cryptobot.strategies.ma_trend import MaTrendStrategy
from cryptobot.strategies.momentum_volume import MomentumVolumeStrategy
from cryptobot.strategies.mtf_trend import MultiTimeframeTrendStrategy
from cryptobot.strategies.rsi_reversion import RsiReversionStrategy

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "ma_trend": MaTrendStrategy,
    "momentum_volume": MomentumVolumeStrategy,
    "rsi_reversion": RsiReversionStrategy,
    "breakout_volatility": BreakoutVolatilityStrategy,
    "mtf_trend": MultiTimeframeTrendStrategy,
}

__all__ = [
    "STRATEGY_REGISTRY",
    "BreakoutVolatilityStrategy",
    "Intent",
    "MaTrendStrategy",
    "MomentumVolumeStrategy",
    "MultiTimeframeTrendStrategy",
    "RsiReversionStrategy",
    "Signal",
    "Strategy",
    "StrategySpec",
]
