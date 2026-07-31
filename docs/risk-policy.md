# Risk Policy — CryptoBot

> Draft v1.0 · 2026-08-01
> **The risk engine has absolute veto authority over every signal.** Defaults below are conservative *engineering defaults*, not optimal values — all are configurable and versioned.

## 1. Per-trade limits

| Limit | Default | Notes |
|-------|---------|-------|
| Max capital at risk per trade | 0.5% of equity | risk = qty × stop distance |
| Max position size | 5% of equity per position | notional |
| Min expected net return | > estimated total costs + 0.10% safety margin | cost gate (§6) |
| Min signal confidence / ensemble score | 0.6 (scale 0–1) | strategy-configurable |
| Max spread at entry | 0.15% of mid | else reject |
| Max estimated slippage | 0.10% | from live depth |
| Min liquidity | order ≤ 5% of top-10-level depth on relevant side | thin-book protection |

## 2. Portfolio limits

| Limit | Default |
|-------|---------|
| Max total market exposure | 25% of equity |
| Max simultaneous positions | 3 |
| Max portfolio drawdown (from high-water mark) | 15% → **halt + review** |

## 3. Frequency & loss limits

| Limit | Default | Breach action |
|-------|---------|---------------|
| Max trades per hour | 4 | reject new entries this hour |
| Max trades per day | 12 | halt new entries today |
| Max daily realized loss | 2% of starting-day equity | **halt + review** |
| Max daily total loss (realized + unrealized) | 3% | **halt + review** |
| Max consecutive losses | 5 | halt new entries + review |
| Strategy cooldown after loss | 60 min per strategy | configurable per strategy |
| Pair cooldown after loss | 30 min per pair | configurable per pair |

**Halt + review** = no new entries; open positions still managed (stops/exits active); resumption requires explicit operator acknowledgment via dashboard/CLI, recorded in the audit log.

## 4. Infrastructure & market-condition protections

- **Stale market data**: no fresh tick within N seconds (default 10s for 1m-driven strategies) → pair blocked; global staleness → halt.
- **API health**: repeated errors / rate-limit saturation → halt new entries until healthy.
- **Exchange status**: symbol not `TRADING` in exchangeInfo, or system maintenance → block affected pairs.
- **Abnormal volatility**: realized vol > k× rolling baseline (default k=4) → block entries on that pair.
- **Clock drift** beyond threshold → block signed operations (fail closed).
- **Account state unconfirmable** (reconciliation failure) → halt everything.

## 5. Prohibited behaviors (hard bans, not configurable)

- Martingale or any doubling-after-loss sizing.
- Unlimited averaging down.
- Revenge trading (cooldowns enforce this mechanically).
- Unbounded grid strategies.
- Hidden leverage of any kind (spot only, no borrowing).
- Any strategy premised on eventually recovering every loss.
- Trading without a stop-loss defined at entry.
- Retrying an order without first querying its state on the exchange.

## 6. Cost gate

Every candidate trade must satisfy:

```
conservative_expected_return > maker/taker fees (both sides)
                              + observed spread
                              + slippage estimate (depth-based, conservative)
                              + market-impact allowance
                              + safety margin (default 0.10%)
```

Costs modeled everywhere (backtest, paper, live): maker/taker fees, bid-ask spread, slippage, partial fills, book depth, market impact, latency price drift, unfilled limit orders (opportunity cost), stablecoin conversion, min-order rules, rounding losses. The displayed price is never assumed to be the executed price. Infrastructure/data costs and tax/record-keeping are tracked at the reporting level.

## 7. Position exit rules

Every position carries from entry: stop-loss price, take-profit target (or trailing rule), and max holding period. Expiry of holding period → managed exit. Emergency stop → cancel all open orders, disable new orders immediately.

## 8. Risk-limit precedence

1. Emergency stop (manual or automatic)
2. Infrastructure protections (§4)
3. Loss/drawdown halts (§3, §2)
4. Frequency limits
5. Per-trade validation (§1)

A lower rule can never override a higher one.

## 9. Live-trading gate (all required, in order)

1. All graduation criteria GC-1…GC-10 (`prd.md` §3) satisfied and recorded in DB.
2. Security + reliability checklists (`threat-model.md`, Phase 6) passed.
3. Separate live configuration file created (never derived from paper config).
4. Separate live API credentials (withdrawals disabled, least privilege, IP allowlisted).
5. `CONFIRM_LIVE_TRADING=I_UNDERSTAND_THE_RISKS` environment variable set.
6. Interactive CLI confirmation at startup naming the capital allocation.
7. Capital allocation ≤ configured small cap (default suggestion: an amount the owner can afford to lose entirely).
8. Live-specific limits active: max daily loss, max order value, global kill switch, continuous reconciliation, auto-shutdown on stale data or unconfirmable account state.

Missing any element → system runs in paper mode. The system never requests or requires withdrawal permission.
