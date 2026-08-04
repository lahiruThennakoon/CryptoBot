from cryptobot.config.settings import Settings
from cryptobot.notifications.service import format_daily_report, notifier_from_settings


class TestNotifierFromSettings:
    def test_loads_telegram_from_env_fields(self):
        settings = Settings(
            _env_file=None,
            TELEGRAM_BOT_TOKEN="bot-token",
            TELEGRAM_CHAT_ID="12345",
            ALERT_WEBHOOK_URL="https://example.com/hook",
        )
        notifier = notifier_from_settings(settings)
        assert notifier.telegram_bot_token == "bot-token"
        assert notifier.telegram_chat_id == "12345"
        assert notifier.webhook_url == "https://example.com/hook"


class TestFormatDailyReport:
    def test_includes_core_metrics_and_near_misses(self):
        text = format_daily_report({
            "report_for": "2026-08-04",
            "equity": 198.42,
            "cash": 185.0,
            "daily_realized_pnl": -1.23,
            "trades_today": 2,
            "open_positions": 1,
            "halted": False,
            "near_misses": [
                {"symbol": "BTCUSDT", "code": "edge_too_low", "confidence": 0.72},
            ],
        })
        assert "Daily report — 2026-08-04 (UTC)" in text
        assert "Equity: $198.42" in text
        assert "Daily PnL: $-1.23" in text
        assert "Near-misses: 1" in text
        assert "BTCUSDT" in text
        assert "Status: OK" in text

    def test_shows_halt_status(self):
        text = format_daily_report({
            "report_for": "2026-08-04",
            "equity": 100,
            "cash": 100,
            "daily_realized_pnl": 0,
            "trades_today": 0,
            "open_positions": 0,
            "halted": True,
            "halt_reason": "daily_loss_limit",
            "near_misses": [],
        })
        assert "Status: HALTED (daily_loss_limit)" in text
