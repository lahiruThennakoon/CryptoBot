"""Application settings with fail-closed live-trading gate.

Secrets are read from environment variables only (or a `.env` file that is
never committed). Nothing here is ever persisted to the database.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

LIVE_CONFIRMATION_PHRASE = "I_UNDERSTAND_THE_RISKS"


class Mode(StrEnum):
    PAPER = "paper"
    TESTNET = "testnet"
    BACKTEST = "backtest"
    LIVE = "live"


class BinanceEndpoints(BaseSettings):
    """Official endpoints — verified against binance/binance-spot-api-docs."""

    testnet_rest: str = "https://testnet.binance.vision/api"
    testnet_ws: str = "wss://stream.testnet.binance.vision"
    live_rest: str = "https://api.binance.com/api"
    live_ws: str = "wss://stream.binance.com:9443"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Search the repo root as well as the CWD, so running from backend/
        # still finds CryptoBot/.env. Later entries take precedence.
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mode: Mode = Field(default=Mode.PAPER, alias="CRYPTOBOT_MODE")

    # Execution routing: analysis (no orders) | paper (simulated) | testnet
    # (real testnet orders). There is no 'live' value by design.
    execution_mode: str = Field(default="paper", alias="EXECUTION_MODE")

    # --- Binance credentials (testnet and live are strictly separate) ---
    binance_testnet_api_key: SecretStr = Field(default=SecretStr(""), alias="BINANCE_TESTNET_API_KEY")
    binance_testnet_api_secret: SecretStr = Field(default=SecretStr(""), alias="BINANCE_TESTNET_API_SECRET")
    binance_live_api_key: SecretStr = Field(default=SecretStr(""), alias="BINANCE_LIVE_API_KEY")
    binance_live_api_secret: SecretStr = Field(default=SecretStr(""), alias="BINANCE_LIVE_API_SECRET")
    confirm_live_trading: str = Field(default="", alias="CONFIRM_LIVE_TRADING")

    # --- Infrastructure ---
    database_url: str = Field(
        default="postgresql+asyncpg://cryptobot:change_me@localhost:5432/cryptobot",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    api_secret_key: SecretStr = Field(default=SecretStr("dev-only-not-secret"), alias="API_SECRET_KEY")
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- Notifications (optional; best-effort, never blocks trading) ---
    telegram_bot_token: SecretStr = Field(default=SecretStr(""), alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    alert_webhook_url: str = Field(default="", alias="ALERT_WEBHOOK_URL")

    # --- Trading scope ---
    trading_pairs: list[str] = Field(default=["BTCUSDT", "ETHUSDT"])
    candle_intervals: list[str] = Field(default=["1m", "5m", "15m", "1h", "4h"])

    # --- Safety thresholds (engineering defaults; see docs/risk-policy.md) ---
    max_clock_drift_ms: int = 1000
    market_data_stale_after_s: float = 10.0
    exchange_info_refresh_s: int = 3600
    ws_include_trades: bool = Field(default=True, alias="CRYPTOBOT_WS_INCLUDE_TRADES")
    ws_include_depth: bool = Field(default=True, alias="CRYPTOBOT_WS_INCLUDE_DEPTH")
    trader_lock_ttl_s: int = Field(default=30, alias="CRYPTOBOT_TRADER_LOCK_TTL_S")

    # Paper account
    paper_starting_balance_quote: Decimal = Decimal("10000")
    paper_quote_asset: str = "USDT"

    # ── execution policy (cost control) ─────────────────────────────
    # market = certain fills, pays spread+slippage; maker_limit = cheaper
    # (maker fee only) but may not fill. Exits always use market orders.
    entry_order_style: str = Field(default="maker_limit", alias="ENTRY_ORDER_STYLE")
    maker_limit_offset_bps: float = Field(default=2.0, alias="MAKER_LIMIT_OFFSET_BPS")
    maker_ttl_bars: int = Field(default=3, alias="MAKER_TTL_BARS")
    bnb_fee_discount: float = Field(default=0.0, alias="BNB_FEE_DISCOUNT")
    small_account_guardrails: bool = Field(default=True, alias="SMALL_ACCOUNT_GUARDRAILS")
    fixed_entry_notional_usd: Decimal = Field(default=Decimal("0"), alias="FIXED_ENTRY_NOTIONAL_USD")
    near_miss_confidence_margin: float = Field(default=0.05, alias="NEAR_MISS_CONFIDENCE_MARGIN")
    near_miss_edge_margin: float = Field(default=0.001, alias="NEAR_MISS_EDGE_MARGIN")
    model_registry_dir: str = Field(default="./model_registry", alias="MODEL_REGISTRY_DIR")

    # ── AI assistant (optional; trading never depends on it) ────────
    anthropic_api_key: SecretStr = Field(default=SecretStr(""), alias="ANTHROPIC_API_KEY")
    ai_low_cost_model: str = Field(default="claude-haiku-4-5-20251001", alias="AI_LOW_COST_MODEL")
    ai_advanced_model: str = Field(default="claude-sonnet-5", alias="AI_ADVANCED_MODEL")
    ai_daily_budget_usd: float = Field(default=2.0, alias="AI_DAILY_BUDGET_USD")
    ai_monthly_budget_usd: float = Field(default=30.0, alias="AI_MONTHLY_BUDGET_USD")

    endpoints: BinanceEndpoints = Field(default_factory=BinanceEndpoints)

    @model_validator(mode="after")
    def _validate_execution_mode(self) -> Settings:
        if self.execution_mode not in ("analysis", "paper", "testnet"):
            logger.critical("invalid EXECUTION_MODE %r — failing closed to 'analysis'",
                            self.execution_mode)
            object.__setattr__(self, "execution_mode", "analysis")
        return self

    @model_validator(mode="after")
    def _enforce_live_gate(self) -> Settings:
        """Fail closed: live mode requires every gate factor; otherwise paper.

        Full gate (docs/risk-policy.md §9) also requires a graduation-criteria
        record in the DB and interactive CLI confirmation — enforced at startup
        in the app layer. This validator enforces the config-level factors.
        """
        if self.mode is Mode.LIVE:
            missing: list[str] = []
            if self.confirm_live_trading != LIVE_CONFIRMATION_PHRASE:
                missing.append("CONFIRM_LIVE_TRADING confirmation phrase")
            if not self.binance_live_api_key.get_secret_value():
                missing.append("BINANCE_LIVE_API_KEY")
            if not self.binance_live_api_secret.get_secret_value():
                missing.append("BINANCE_LIVE_API_SECRET")
            if missing:
                logger.critical(
                    "LIVE mode requested but gate factors missing (%s). "
                    "Failing closed: running in PAPER mode.",
                    ", ".join(missing),
                )
                object.__setattr__(self, "mode", Mode.PAPER)
        return self

    @property
    def rest_base_url(self) -> str:
        if self.mode is Mode.LIVE:
            return self.endpoints.live_rest
        return self.endpoints.testnet_rest

    @property
    def ws_base_url(self) -> str:
        if self.mode is Mode.LIVE:
            return self.endpoints.live_ws
        return self.endpoints.testnet_ws

    @property
    def api_key(self) -> SecretStr:
        if self.mode is Mode.LIVE:
            return self.binance_live_api_key
        return self.binance_testnet_api_key

    @property
    def api_secret(self) -> SecretStr:
        if self.mode is Mode.LIVE:
            return self.binance_live_api_secret
        return self.binance_testnet_api_secret


@lru_cache
def get_settings() -> Settings:
    return Settings()
