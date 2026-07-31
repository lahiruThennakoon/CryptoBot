"""Crypto knowledge corpus for the assistant (education + grounding).

This is what "giving the bot knowledge about crypto" honestly means: a
curated, versioned corpus the assistant can quote and cite, so explanations
are accurate and consistent. It deliberately contains NO price predictions,
no signal folklore, and no claims about what will happen — because no amount
of knowledge makes future prices knowable.

Trading decisions never consult this file; they come from the deterministic
strategy, cost and risk engines (see risk/small_account.py for the rules
version of this knowledge).
"""

from __future__ import annotations

CRYPTO_KB_VERSION = "crypto-kb-v1"

# (topic, title, text)
CRYPTO_KNOWLEDGE: list[tuple[str, str, str]] = [
    # ── market structure ──────────────────────────────────────────────
    ("market-structure", "What a spot order book is",
     "A spot order book lists resting buy orders (bids) and sell orders (asks). The "
     "highest bid and lowest ask define the spread. Market orders consume resting "
     "orders and pay the spread; limit orders join the book and may not fill. Depth "
     "means how much size sits near the top of the book: thin depth means your order "
     "moves the price against you (slippage)."),
    ("market-structure", "Maker vs taker fees",
     "A taker removes liquidity (market order) and pays the taker fee. A maker adds "
     "liquidity (resting limit order) and pays the usually-lower maker fee. On Binance "
     "spot both are commonly 0.1% without discounts; paying fees in BNB typically cuts "
     "them further. Fees apply to BOTH entry and exit, so a round trip costs at least "
     "twice the single-side rate."),
    ("market-structure", "Why 24-hour volume matters",
     "Quote volume approximates how much money changes hands. Low-volume pairs have "
     "wide spreads, sudden gaps and unreliable fills, so modelled profits often fail "
     "to materialise. Preferring high-volume majors is a cost decision, not a taste."),
    ("market-structure", "Exchange minimums and filters",
     "Binance enforces per-symbol rules: tick size (price increments), step size "
     "(quantity increments), minimum quantity and minimum notional (usually about $5). "
     "Orders violating any filter are rejected. On small accounts these minimums, not "
     "strategy, often decide whether a trade is possible at all."),
    ("market-structure", "Stablecoins are not risk-free",
     "USDT/USDC are claims on an issuer, not dollars in a bank. They have historically "
     "traded slightly off $1 under stress. Holding quote currency on an exchange also "
     "carries exchange counterparty risk — 'not your keys, not your coins'."),

    # ── costs and the arithmetic of trading ───────────────────────────
    ("costs", "The full cost of a round trip",
     "Total cost = entry fee + exit fee + spread + slippage + any latency drift. At "
     "0.1% fees and a 0.03% spread, a round trip costs roughly 0.25-0.35%. That is the "
     "minimum favourable move needed before a trade makes a single cent, and it is "
     "charged whether the trade wins or loses."),
    ("costs", "Why frequent trading usually loses",
     "Costs scale linearly with the number of trades; edges do not. Ten trades a day at "
     "0.3% cost each is roughly 3% of capital per day in costs — a bar almost no retail "
     "strategy clears. Reducing trade frequency is one of the few reliable improvements "
     "available to a retail trader."),
    ("costs", "Slippage and market impact",
     "Slippage is the gap between the price you decided on and the price you got. It "
     "grows with order size relative to book depth and with volatility. Backtests that "
     "assume perfect fills at the close systematically overstate results."),
    ("costs", "Compounding cuts both ways",
     "Repeated small gains compound upward; repeated small losses compound downward, "
     "and a -20% drawdown requires +25% to recover. Cost drag compounds too, which is "
     "why cost control matters more than signal cleverness at small size."),

    # ── indicators: what they are and are not ─────────────────────────
    ("indicators", "Moving averages",
     "A moving average smooths price to make trend direction visible. Crossovers "
     "(fast above slow) are trend-following signals: they identify a trend that has "
     "already started, and by construction they lag turns. They are descriptive, not "
     "predictive."),
    ("indicators", "RSI (Relative Strength Index)",
     "RSI compares recent average gains to average losses on a 0-100 scale. Below ~30 "
     "is called oversold and above ~70 overbought. Crucially, in a strong trend RSI can "
     "stay 'overbought' for weeks — buying every oversold reading in a downtrend is a "
     "well-known way to lose money."),
    ("indicators", "MACD",
     "MACD is the difference between two exponential moving averages plus a signal line. "
     "The histogram shows momentum shifting. Like all moving-average tools it lags and "
     "produces frequent false signals in ranging markets."),
    ("indicators", "ATR (Average True Range)",
     "ATR measures typical bar range, i.e. volatility, in price units. It is the sane "
     "basis for stop placement: a stop closer than about 1.5-2 ATR is likely to be hit "
     "by ordinary noise regardless of direction."),
    ("indicators", "Bollinger Bands",
     "Bands plotted a number of standard deviations around a moving average. Price "
     "touching a band is not a signal by itself — bands widen in volatility and price "
     "can ride a band throughout a strong trend."),
    ("indicators", "Why no single indicator works",
     "Indicators are transformations of the same past prices; they cannot add "
     "information that price does not contain. Any simple rule that worked reliably "
     "would be arbitraged away. Combining indicators reduces some noise but never "
     "creates a guarantee, and over-combining invites curve-fitting."),

    # ── strategy and evaluation ───────────────────────────────────────
    ("strategy", "Market regimes",
     "Markets alternate between trending, ranging and high-volatility states. Trend "
     "strategies lose money in ranges (whipsaw), mean-reversion strategies lose money in "
     "trends (fighting momentum). Matching strategy to regime — and refusing to trade "
     "outside it — matters more than parameter tuning."),
    ("strategy", "Expectancy beats win rate",
     "Expectancy = average win x win rate - average loss x loss rate, after costs. A 90% "
     "win rate with occasional huge losses is a losing system; a 35% win rate with large "
     "winners can be excellent. Any system advertised by win rate alone should be "
     "distrusted."),
    ("strategy", "Overfitting and walk-forward testing",
     "Tuning parameters until a backtest looks good fits noise, not signal. Honest "
     "evaluation requires an untouched test period, walk-forward windows, and checking "
     "that the edge survives higher assumed fees and slippage. If results collapse at "
     "1.5x costs, there was no edge."),
    ("strategy", "Beating buy-and-hold is the real bar",
     "In a rising market, doing nothing earns the market return at zero cost and zero "
     "effort. A trading strategy must beat buy-and-hold AND no-trade after costs to "
     "justify its risk and complexity. Most do not."),
    ("strategy", "Prohibited patterns",
     "Martingale (doubling after losses), unlimited averaging down, unbounded grids and "
     "revenge trading all convert small losses into account-ending ones. They can look "
     "profitable for a long time, which is precisely what makes them dangerous."),

    # ── risk management ───────────────────────────────────────────────
    ("risk", "Position sizing and risk of ruin",
     "Position size should follow from the distance to your stop and a fixed small "
     "fraction of equity (commonly 0.5-1%, rarely above 2%). Risk of ruin rises "
     "non-linearly with size: at 10% risk per trade, a normal streak of losses is fatal."),
    ("risk", "Stops are a plan, not a prediction",
     "A stop-loss defines the maximum acceptable loss before entering, when judgement is "
     "clearest. Trading without a pre-committed exit means the size of your loss is "
     "decided by hope. Stops do not guarantee the price: gaps can fill worse."),
    ("risk", "Drawdown and psychology",
     "Drawdown is the fall from peak equity. Deep drawdowns break discipline before they "
     "break arithmetic — most people abandon a system at its worst point. Choosing "
     "limits you can actually tolerate is part of the strategy."),
    ("risk", "Correlation in crypto",
     "Most crypto assets are strongly correlated with Bitcoin, especially in selloffs. "
     "Holding several altcoins is usually one leveraged BTC bet, so position limits "
     "should be judged on correlated exposure, not the number of tickers."),
    ("risk", "Leverage and liquidation",
     "Leverage multiplies both directions and introduces liquidation, where a position "
     "is force-closed at a loss you did not choose. This application is deliberately "
     "spot-only with no borrowing: the worst case is an asset falling, never a forced "
     "liquidation."),

    # ── operational and security realities ────────────────────────────
    ("operations", "API keys and permissions",
     "Trading keys should have withdrawal permission DISABLED and IP allowlisting "
     "enabled. A leaked key with withdrawal rights means total loss; a leaked "
     "trade-only key on an allowlisted IP is far less damaging."),
    ("operations", "Testnet vs live",
     "Binance Spot Testnet uses virtual funds and resets roughly monthly. It validates "
     "integration (orders, filters, reconnects) but NOT strategy performance, because "
     "its liquidity and prices are unrealistic."),
    ("operations", "Paper trading limitations",
     "Paper trading with live prices tests logic and discipline, but simulated fills are "
     "optimistic by nature: no queue position, no partial-fill grind, no exchange "
     "outages. Expect real results to be somewhat worse."),
    ("operations", "Tax and record keeping",
     "In many jurisdictions every disposal is a taxable event, and bots generate many. "
     "Keeping per-fill records with fees is not optional bookkeeping; without it, tax "
     "reporting becomes guesswork."),
    ("operations", "Scams and red flags",
     "Guaranteed returns, 'proprietary AI that never loses', copy-trading with hidden "
     "track records, and signal groups charging for tips are the standard shapes of "
     "crypto fraud. Any system claiming certainty about future prices is either "
     "mistaken or lying — including this one, if it ever does."),
]


def as_chunks() -> list[dict[str, str]]:
    return [
        {"doc": f"crypto-kb/{topic}", "version": CRYPTO_KB_VERSION,
         "title": title, "text": text}
        for topic, title, text in CRYPTO_KNOWLEDGE
    ]
