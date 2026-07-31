# Performance Evidence Requirements — Phase 6

> Evidence must exist BEFORE live trading is even considered. Passing every
> requirement does not guarantee future profitability — it only demonstrates
> the system behaved acceptably on data it has seen.

## 1. Required evidence (maps to graduation criteria, prd.md §3)

| GC | Evidence | Source | Requirement |
|----|----------|--------|-------------|
| GC-1 | Backtest span per pair | `cryptobot backtest` reports | ≥ 2 years, 1h bars, per traded pair |
| GC-1 | Regime coverage | report "performance by regime" | trades observed in trend-up, trend-down, range |
| GC-2 | Paper duration | `equity_snapshots` (automated) | ≥ 90 consecutive days |
| GC-3 | Closed paper trades | `positions` table (automated) | ≥ 100 |
| GC-4 | Net expectancy after costs | paper PnL + walk-forward reports | > 0 in both |
| GC-5 | Paper max drawdown | equity snapshots (automated) | ≤ 15% |
| GC-6 | Stability | 30-day window analysis | ≥ 2 of 3 consecutive windows positive |
| — | Cost sensitivity | `backtest --sensitivity` | edge survives 1.5× fees and 2× slippage |
| — | Baseline comparison | backtest reports | strategy justified vs buy-and-hold AND no-trade |

## 2. Archive format

For each claim, archive under `docs/live-readiness/evidence/`:
report output (text/JSON), the config version hash, git commit, data range,
and the seed. Every number must be reproducible from a clean checkout.

## 3. Honest-reporting rules

- Losing periods are reported, never smoothed or excluded.
- Win rate is never cited without expectancy and drawdown beside it.
- Any parameter changed after seeing test-period results invalidates that
  test period as evidence; re-run on fresh data.
- If evidence is mixed, the default decision is: stay in paper.

## 4. Known limitations (state in the decision package)

- Backtests simulate market-at-next-open fills; resting limit-order queue
  dynamics are not modeled (taker costs assumed — conservative).
- Paper fills use a cost model, not a real order book; live slippage can be
  worse in fast markets.
- Testnet liquidity is unrealistic; testnet validates integration only.
- Regime detection is rule-based and lags regime changes by design.
- VaR is historical and understates tail risk.
- The strategy set is long-only spot; prolonged bear markets are expected to
  produce long flat (no-trade) stretches — that is correct behavior, not a bug.

## 5. Unresolved risks (accepted, documented)

- Exchange counterparty risk (Binance outage/insolvency) — mitigated only by
  small capital allocation.
- Regulatory changes in the owner's jurisdiction — owner's responsibility to
  monitor (see disclaimer).
- Model drift faster than the monitoring window — mitigated by PSI alerts +
  demotion to rule-based baselines, not eliminated.
- Single-operator, single-region deployment — no HA; an outage means the bot
  is down (positions are protected by stops resting in state, but a crashed
  bot cannot manage exits until restarted; keep allocations sized for this).
