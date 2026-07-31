from decimal import Decimal

from cryptobot.pairs.catalog import PairStats, evaluate_pair, parse_24h_ticker

D = Decimal


def stats(**kw) -> PairStats:
    base = dict(symbol="BTCUSDT", last_price=D("60000"), quote_volume_24h=D("2000000000"),
                high_24h=D("61000"), low_24h=D("59000"),
                best_bid=D("59999"), best_ask=D("60001"))
    base.update(kw)
    return PairStats(**base)


def listing(**kw):
    args = dict(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
                status="TRADING", stats=stats())
    args.update(kw)
    return evaluate_pair(**args)


class TestSelectability:
    def test_healthy_pair_selectable_no_warnings(self):
        p = listing()
        assert p.selectable and not p.warnings

    def test_non_trading_status_blocked(self):
        p = listing(status="BREAK")
        assert not p.selectable and "not TRADING" in p.not_selectable_reason

    def test_unsupported_quote_blocked(self):
        p = listing(symbol="BTCEUR", quote_asset="EUR")
        assert not p.selectable and "EUR" in p.not_selectable_reason

    def test_spot_not_allowed_blocked(self):
        p = listing(is_spot_allowed=False)
        assert not p.selectable


class TestWarnings:
    def test_low_liquidity_warns(self):
        p = listing(stats=stats(quote_volume_24h=D("5000000")))
        assert any("liquidity" in w.lower() for w in p.warnings)

    def test_wide_spread_warns(self):
        p = listing(stats=stats(best_bid=D("59900"), best_ask=D("60100")))
        assert any("spread" in w.lower() for w in p.warnings)

    def test_high_volatility_warns(self):
        p = listing(stats=stats(high_24h=D("66000"), low_24h=D("54000")))
        assert any("volatility" in w.lower() for w in p.warnings)

    def test_unselectable_pairs_skip_warning_analysis(self):
        p = listing(status="HALT", stats=stats(quote_volume_24h=D("1")))
        assert not p.warnings   # blocked pairs don't need warnings


class TestTickerParsing:
    def test_official_field_names(self):
        s = parse_24h_ticker({
            "symbol": "ETHUSDT", "lastPrice": "3400.5", "priceChangePercent": "-1.2",
            "quoteVolume": "900000000", "highPrice": "3500", "lowPrice": "3300",
            "bidPrice": "3400", "askPrice": "3401",
        })
        assert s.last_price == D("3400.5")
        assert s.spread_fraction > 0
        assert s.volatility_24h > 0