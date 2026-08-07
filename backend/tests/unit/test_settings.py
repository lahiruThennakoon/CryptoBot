from cryptobot.config.settings import Mode, Settings


class TestTradingPairs:
    def test_comma_separated_env(self):
        settings = Settings(_env_file=None, TRADING_PAIRS="btcusdt, ethusdt ,SHIBUSDT")
        assert settings.trading_pairs == ["BTCUSDT", "ETHUSDT", "SHIBUSDT"]


class TestLearningMode:
    def test_learning_mode_env(self):
        settings = Settings(_env_file=None, CRYPTOBOT_LEARNING_MODE="true")
        assert settings.learning_mode is True


class TestActivePaperMode:
    def test_active_paper_env(self):
        settings = Settings(_env_file=None, CRYPTOBOT_ACTIVE_PAPER="true")
        assert settings.active_paper_mode is True


class TestLiveGate:
    def test_default_mode_is_paper(self):
        settings = Settings(_env_file=None)
        assert settings.mode is Mode.PAPER

    def test_live_without_gate_factors_fails_closed_to_paper(self):
        settings = Settings(_env_file=None, CRYPTOBOT_MODE="live")
        assert settings.mode is Mode.PAPER

    def test_live_with_partial_gate_still_paper(self):
        settings = Settings(
            _env_file=None,
            CRYPTOBOT_MODE="live",
            CONFIRM_LIVE_TRADING="I_UNDERSTAND_THE_RISKS",
            # live credentials missing
        )
        assert settings.mode is Mode.PAPER

    def test_live_with_wrong_phrase_still_paper(self):
        settings = Settings(
            _env_file=None,
            CRYPTOBOT_MODE="live",
            CONFIRM_LIVE_TRADING="yes",
            BINANCE_LIVE_API_KEY="k" * 32,
            BINANCE_LIVE_API_SECRET="s" * 32,
        )
        assert settings.mode is Mode.PAPER

    def test_live_with_all_config_factors_allowed(self):
        # Config-level gate only; runtime gate (DB graduation record + CLI
        # confirmation) is enforced at startup in the app layer.
        settings = Settings(
            _env_file=None,
            CRYPTOBOT_MODE="live",
            CONFIRM_LIVE_TRADING="I_UNDERSTAND_THE_RISKS",
            BINANCE_LIVE_API_KEY="k" * 32,
            BINANCE_LIVE_API_SECRET="s" * 32,
        )
        assert settings.mode is Mode.LIVE


class TestCredentialSeparation:
    def test_paper_and_testnet_use_testnet_urls_and_keys(self):
        settings = Settings(
            _env_file=None,
            CRYPTOBOT_MODE="testnet",
            BINANCE_TESTNET_API_KEY="testnet-key-0123456789",
            BINANCE_LIVE_API_KEY="live-key-0123456789012",
        )
        assert "testnet.binance.vision" in settings.rest_base_url
        assert settings.api_key.get_secret_value() == "testnet-key-0123456789"

    def test_secrets_never_appear_in_repr(self):
        settings = Settings(_env_file=None, BINANCE_TESTNET_API_KEY="hidden-key-abcdef123456")
        assert "hidden-key-abcdef123456" not in repr(settings)
        assert "hidden-key-abcdef123456" not in str(settings)
