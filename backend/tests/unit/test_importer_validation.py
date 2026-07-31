from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cryptobot.exchange.models import Candle
from cryptobot.importer.service import validate_candles

D = Decimal
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def candle(i: int, **overrides) -> Candle:
    fields = dict(
        symbol="BTCUSDT", interval="1h", open_time=T0 + timedelta(hours=i),
        open=D("100"), high=D("101"), low=D("99"), close=D("100"),
        volume=D("10"), quote_volume=D("1000"), trade_count=5,
    )
    fields.update(overrides)
    return Candle(**fields)


class TestValidation:
    def test_clean_series_has_no_issues(self):
        issues = validate_candles([candle(i) for i in range(48)], "1h")
        assert not issues.critical

    def test_detects_gap(self):
        candles = [candle(i) for i in [0, 1, 2, 5, 6]]  # missing 3, 4
        issues = validate_candles(candles, "1h")
        assert len(issues.gaps) == 1
        gap_start, gap_end = issues.gaps[0]
        assert gap_start == T0 + timedelta(hours=3)

    def test_detects_duplicates(self):
        issues = validate_candles([candle(0), candle(1), candle(1)], "1h")
        assert issues.duplicates == 1

    def test_detects_out_of_order(self):
        issues = validate_candles([candle(2), candle(1)], "1h")
        assert issues.out_of_order == 1

    def test_detects_impossible_ohlc(self):
        bad = candle(0, high=D("98"))  # high < low
        issues = validate_candles([bad], "1h")
        assert issues.bad_values == 1

    def test_detects_nonpositive_price(self):
        # pydantic allows it structurally; validation must flag it
        bad = candle(0, open=D("0"), low=D("0"))
        issues = validate_candles([bad], "1h")
        assert issues.bad_values == 1