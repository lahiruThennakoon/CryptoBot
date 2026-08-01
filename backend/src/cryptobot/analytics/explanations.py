"""Plain-language explanations for every machine reason code.

Written for an operator who is not a trader. Tone rules: explain what the
bot protected them from, never apologize for not trading, never imply a
missed trade was a missed profit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Explanation:
    title: str
    text: str
    is_protective: bool = True   # False → operational/infrastructure cause


EXPLANATIONS: dict[str, Explanation] = {
    "REGIME_EXCLUDED": Explanation(
        "Wrong market conditions",
        "The strategy that spotted this opportunity only works in a specific kind of "
        "market (for example, a steady uptrend). The market wasn't that kind at the "
        "time, and trading a strategy outside its home conditions is how it loses.",
    ),
    "COST_GATE": Explanation(
        "Expected profit too small to cover fees",
        "Every trade pays exchange fees, the bid-ask spread, and slippage. This "
        "signal's expected profit was smaller than those costs plus an extra buffer, "
        "so taking it would most likely have lost money even if the prediction was right.",
    ),
    "LOW_CONFIDENCE": Explanation(
        "Signal too weak",
        "The strategy generated a signal but its own confidence score was below the "
        "minimum bar. Weak signals are statistically closer to coin flips, and coin "
        "flips lose money once you pay fees.",
    ),
    "COOLDOWN": Explanation(
        "Cooling off after a recent loss",
        "This strategy recently closed a losing trade on this pair, so it is required "
        "to wait before trying again. This mechanically prevents revenge-trading — "
        "one of the most common ways trading accounts die.",
    ),
    "NO_STOP": Explanation(
        "No exit plan",
        "The signal did not define a stop-loss price. This system refuses any trade "
        "that doesn't know in advance where it will give up, because unlimited "
        "downside is never acceptable.",
    ),
    "INVALID_STOP": Explanation(
        "Broken exit plan",
        "The signal's stop-loss price was above the entry price, which makes no sense "
        "for a buy. Malformed signals are rejected rather than 'fixed' silently.",
    ),
    "STOP_TOO_TIGHT": Explanation(
        "Stop-loss too close to the price",
        "The stop was so close that normal market noise would trigger it instantly, "
        "guaranteeing a loss plus fees. Rejected.",
    ),
    "MAX_POSITIONS": Explanation(
        "Position limit reached",
        "The bot already holds its maximum number of simultaneous positions. Adding "
        "more would concentrate risk beyond the configured limit.",
    ),
    "MAX_EXPOSURE": Explanation(
        "Too much money already in the market",
        "The configured cap on total market exposure was reached. The remainder of "
        "the account stays in cash by design — cash is a position too.",
    ),
    "MAX_TRADES_PER_DAY": Explanation(
        "Daily trade limit reached",
        "The bot hit its maximum trades for the day. Overtrading multiplies fee costs "
        "and usually signals chasing, so the day is done.",
    ),
    "DAILY_LOSS_LIMIT": Explanation(
        "Daily loss limit hit — trading halted",
        "Losses today reached the configured daily maximum, so the bot stopped "
        "opening positions and will not resume until you review and explicitly "
        "confirm. This is the seatbelt doing its job.",
    ),
    "MAX_DRAWDOWN": Explanation(
        "Account drawdown limit hit — trading halted",
        "The account fell far enough below its high-water mark to hit the drawdown "
        "limit. Trading halted pending your review — protecting what remains matters "
        "more than winning it back quickly.",
    ),
    "CONSECUTIVE_LOSSES": Explanation(
        "Losing streak limit hit — trading halted",
        "Too many losses in a row. Streaks like this usually mean market conditions "
        "have changed; the bot stops and waits for your review instead of doubling down.",
    ),
    "HALTED": Explanation(
        "Trading is halted pending your review",
        "A protective limit was hit earlier and trading stays stopped until you "
        "explicitly resume it from the dashboard. Nothing resumes on its own.",
    ),
    "STALE_DATA": Explanation(
        "Market data too old",
        "Fresh price data stopped arriving (connection hiccup or exchange issue). "
        "Trading on outdated prices is gambling, so entries were blocked until the "
        "feed recovered.",
        is_protective=False,
    ),
    "INSUFFICIENT_CASH": Explanation(
        "Not enough available cash",
        "The account's free cash couldn't cover the trade at the required size. "
        "The bot never borrows and never oversizes to compensate.",
        is_protective=False,
    ),
    "SIZE_BELOW_MIN_QTY": Explanation(
        "Trade would be too small",
        "After applying your risk limits, the resulting order was below the "
        "exchange's minimum size. A safe size that the exchange won't accept means "
        "no trade — the alternative is taking more risk than configured.",
    ),
    "SIZE_BELOW_MIN_NOTIONAL": Explanation(
        "Trade value below the exchange minimum",
        "The safely-sized order was worth less than the exchange's minimum order "
        "value. Same principle: the bot won't increase risk just to satisfy a minimum.",
    ),
}

EXPLANATIONS["OUT_OF_SESSION"] = Explanation(
    "Outside your trading hours",
    "You configured specific days and hours when the bot may trade. This "
    "opportunity appeared outside that window, so it was skipped. Exits and "
    "protective stops stay active around the clock.",
)
EXPLANATIONS["PROFIT_TARGET_REACHED"] = Explanation(
    "Daily profit target reached — protecting the result",
    "Today's realized profit hit your configured target, so per your settings "
    "the bot stopped opening new trades to protect what it made. Giving "
    "profits back by overtrading a good day is a classic mistake this prevents.",
)
EXPLANATIONS["PAIR_DISABLED"] = Explanation(
    "Pair not enabled by you",
    "A signal appeared on a trading pair you have not enabled. The bot never "
    "trades a pair without your explicit permission, no matter how strong the "
    "signal looks.",
)
EXPLANATIONS["WIDE_SPREAD"] = Explanation(
    "Gap between buy and sell price too wide",
    "The difference between the best buying and selling price was unusually "
    "large. Entering would start the trade at an immediate loss bigger than "
    "the configured limit.",
)
EXPLANATIONS["LOW_LIQUIDITY"] = Explanation(
    "Not enough buyers and sellers",
    "The order book was too thin to fill an order of our size without moving "
    "the price against us. Thin markets quietly eat profits through slippage.",
)
EXPLANATIONS["NOT_TOP_RANKED"] = Explanation(
    "Better opportunities were available",
    "Several pairs qualified at the same time and this one ranked below the "
    "best risk-adjusted opportunities, or moved too similarly to one already "
    "taken. Taking every signal at once would concentrate risk.",
)

_UNKNOWN = Explanation(
    "Skipped for a technical reason",
    "The signal was rejected with an internal code that has no plain-language entry "
    "yet. The full detail is in the signal log and audit trail.",
    is_protective=False,
)


def explain(code: str | None) -> Explanation:
    if not code:
        return _UNKNOWN
    return EXPLANATIONS.get(code, _UNKNOWN)


def summarize_no_trades(code_counts: dict[str, int]) -> str:
    """One-paragraph plain-language summary of a period with no/few trades."""
    if not code_counts:
        return (
            "No trade signals were generated in this period. The strategies watched "
            "the market and found no setups worth acting on — staying out of the "
            "market costs nothing, while forced trades pay fees on every attempt."
        )
    total = sum(code_counts.values())
    top = sorted(code_counts.items(), key=lambda kv: -kv[1])[:3]
    parts = [f"{count}× {explain(code).title.lower()}" for code, count in top]
    return (
        f"{total} potential trade(s) were evaluated and skipped: "
        + "; ".join(parts)
        + ". Each rejection protected the account from a trade that failed at least "
        "one safety check. Not trading is a decision, not a malfunction."
    )
