# Active paper — 30-day operator checklist

Use with `EXECUTION_MODE=paper` and `CRYPTOBOT_ACTIVE_PAPER=true`.
Simulated fees/spread apply; PnL is more meaningful than testnet (zero fees).

## EC2 `.env` (copy these lines)

```env
CRYPTOBOT_MODE=paper
EXECUTION_MODE=paper
CRYPTOBOT_LEARNING_MODE=false
CRYPTOBOT_ACTIVE_PAPER=true
TRADING_PAIRS=BTCUSDT,ETHUSDT
ENTRY_ORDER_STYLE=market
SMALL_ACCOUNT_GUARDRAILS=false
FIXED_ENTRY_NOTIONAL_USD=10
PAPER_STARTING_BALANCE_QUOTE=200
# Comment out DATABASE_URL and REDIS_URL — Docker Compose sets them on EC2
```

Deploy:

```bash
cd ~/CryptoBot && git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build trader collector api
docker compose logs trader --tail=15 | grep -E "ACTIVE_PAPER|paper_trading_started"
```

---

## Week 1 — Pipeline + rhythm

| Day | Check | Pass? |
|-----|-------|-------|
| 1 | Log shows `ACTIVE_PAPER_MODE` and `execution_routing mode=paper` | |
| 1 | Dashboard fills show **non-zero fees** (e.g. `0.01` not `0E-18`) | |
| 1 | At least 1 trade or near-miss in Signal log | |
| 2–7 | EOD Telegram report received ≥ 5 days | |
| 7 | `decisions` table has mix of scores; not all stuck negative | |
| 7 | No unexplained `HALTED` in daily report | |

## Week 2 — Discipline + costs

| Day | Check | Pass? |
|-----|-------|-------|
| 14 | ≥ 15 closed paper trades total | |
| 14 | Every fill has simulated fee > 0 in dashboard | |
| 14 | Max drawdown ≤ 10% of starting $200 (halt should fire near 15%) | |
| 14 | Review near-misses: mostly cost/confidence, not `PAIR_DISABLED` | |

## Week 3 — Edge signal (not proof yet)

| Day | Check | Pass? |
|-----|-------|-------|
| 21 | Run Strategy Lab backtest on BTC+ETH (2y if available) | |
| 21 | Walk-forward or 1.5× fee stress: strategy not only profitable at 1× | |
| 21 | Paper net PnL documented (win or loss — honesty matters) | |

## Week 4 — Graduation prep (GC-4 direction)

| Day | Check | Pass? |
|-----|-------|-------|
| 30 | ≥ 40 closed paper trades (path to GC-3’s 100) | |
| 30 | Net expectancy **after fees** positive in **backtest** (GC-4) | |
| 30 | Paper equity ≥ $170 (−15% floor, SM-L4) **or** stop with written learnings | |
| 30 | Ops drills: restart trader, confirm reconcile OK, test estop once | |

---

## What this phase proves vs does not

**Proves:** strategy signals under real market data, cost-aware paper PnL, risk halts, ops.

**Does not prove:** live profitability, testnet PnL, or `learning_pulse` results.

**Next step after 30 days:** extend paper to 90 days / 100 trades (GC-3) only if backtest GC-4 looks plausible; then consider live with $10 cap and restricted API key.
