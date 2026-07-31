import json
from decimal import Decimal

from cryptobot.exchange.binance.ws import BinanceMarketStream
from cryptobot.exchange.models import MarketEventType


def _stream() -> BinanceMarketStream:
    return BinanceMarketStream("wss://stream.testnet.binance.vision", ["BTCUSDT"], ["1m"])


KLINE_MSG = {
    "stream": "btcusdt@kline_1m",
    "data": {
        "e": "kline", "E": 1690000000000, "s": "BTCUSDT",
        "k": {
            "t": 1689999960000, "T": 1690000019999, "s": "BTCUSDT", "i": "1m",
            "o": "29000.10", "c": "29010.50", "h": "29011.00", "l": "28999.90",
            "v": "12.5", "q": "362512.5", "n": 250, "x": True,
            "f": 1, "L": 2, "V": "6", "Q": "174000", "B": "0",
        },
    },
}


class TestWsParsing:
    def test_combined_stream_url(self):
        url = _stream()._url()
        assert url.startswith("wss://stream.testnet.binance.vision/stream?streams=")
        assert "btcusdt@kline_1m" in url

    def test_closed_kline_parsed(self):
        event = _stream()._parse(json.dumps(KLINE_MSG))
        assert event is not None
        assert event.type is MarketEventType.KLINE
        assert event.candle is not None
        assert event.candle.close == Decimal("29010.50")
        assert event.candle.is_closed is True
        assert event.candle.open_time.tzinfo is not None  # UTC-aware

    def test_garbage_returns_none(self):
        assert _stream()._parse("not json{") is None
        assert _stream()._parse(json.dumps({"data": {"e": "unknownEvent"}})) is None
