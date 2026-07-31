import logging

from cryptobot.security.redaction import (
    RedactionFilter,
    redact,
    register_secret,
)


class TestRedact:
    def test_signature_scrubbed(self):
        url = "/api/v3/order?symbol=BTCUSDT&signature=abcdef0123456789abcdef0123456789"
        assert "abcdef0123456789" not in redact(url)
        assert "signature=***REDACTED***" in redact(url)

    def test_api_key_header_scrubbed(self):
        text = 'X-MBX-APIKEY: "AbCdEfGh1234567890AbCdEfGh1234567890"'
        assert "AbCdEfGh1234567890" not in redact(text)

    def test_registered_secret_scrubbed_anywhere(self):
        register_secret("super-secret-value-42")
        assert "super-secret-value-42" not in redact("error dumping: super-secret-value-42 in body")

    def test_symbol_names_untouched(self):
        assert redact("BTCUSDT kline received") == "BTCUSDT kline received"


class TestRedactionFilter:
    def test_filter_scrubs_log_records(self, caplog):
        register_secret("filter-test-secret-99")
        logger = logging.getLogger("redaction-test")
        logger.addFilter(RedactionFilter())
        with caplog.at_level(logging.INFO, logger="redaction-test"):
            logger.info("payload contains filter-test-secret-99 here")
        assert "filter-test-secret-99" not in caplog.text
        assert "***REDACTED***" in caplog.text

    def test_filter_scrubs_args(self, caplog):
        register_secret("args-secret-12345")
        logger = logging.getLogger("redaction-test-2")
        logger.addFilter(RedactionFilter())
        with caplog.at_level(logging.INFO, logger="redaction-test-2"):
            logger.info("value: %s", "args-secret-12345")
        assert "args-secret-12345" not in caplog.text
