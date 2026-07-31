# Security & Reliability Checklists — Phase 6

> Part of the live-readiness **decision package**. Completing these lists is
> necessary but NOT sufficient for live trading; final approval is the
> owner's manual decision in `approval.md`. Run `cryptobot readiness` for the
> automated subset.

## 1. Security checklist

| # | Item | How to verify | Result / date |
|---|------|---------------|---------------|
| S1 | No hard-coded secrets anywhere | `gitleaks detect` clean on full history | ☐ |
| S2 | `.env` gitignored; never committed | `git log --all --full-history -- .env` empty | ☐ |
| S3 | Live API key has withdrawals DISABLED | Binance key settings screenshot archived | ☐ |
| S4 | Live key least-privilege (spot trade + read only) | Binance key settings | ☐ |
| S5 | IP allowlisting enabled on live key | Binance key settings; verify from non-allowed IP fails | ☐ |
| S6 | Testnet and live credentials fully separated | distinct env vars; never both loaded (settings.py) | ☐ |
| S7 | Secret redaction proven | `pytest tests/unit/test_redaction.py`; grep logs for keys | ☐ |
| S8 | Key-rotation runbook executed end-to-end once | new key → deploy → verify → revoke old | ☐ |
| S9 | Fail-closed on invalid credentials | start with wrong key → bot refuses to trade | ☐ |
| S10 | Dashboard bound to localhost/VPN; token auth verified | curl without token → 401; default key → 503 | ☐ |
| S11 | Arm/confirm flow enforced on emergency stop & resume | attempt without token → 403 | ☐ |
| S12 | Dependency & container vulnerability scans clean | `pip-audit`; image scan | ☐ |
| S13 | Backups contain no secrets | inspect `pg_dump` output | ☐ |

## 2. Reliability checklist (drills — record evidence for each)

| # | Drill | Procedure | Pass criteria | Result / date |
|---|-------|-----------|---------------|---------------|
| R1 | Restart + reconciliation | kill trader mid-position; restart | positions/balances reconciled, no duplicate orders | ☐ |
| R2 | API disconnection | drop network 5 min during paper run | reconnects, backfills gap, no crash, staleness halt engaged | ☐ |
| R3 | Duplicate-order prevention | replay candle events; resubmit same clientOrderId on testnet | exactly one order exists | ☐ |
| R4 | Emergency stop | trigger from dashboard with open position | all orders cancelled, position closed, audit + alert written | ☐ |
| R5 | Stale-data halt | freeze market stream | new entries blocked within threshold | ☐ |
| R6 | Daily-loss halt + review flow | force loss beyond limit in paper | halt engaged; resume requires arm/confirm | ☐ |
| R7 | Backup & restore | `pg_dump` → restore to fresh DB → run readiness | evidence numbers identical | ☐ |
| R8 | Testnet reset survival | after monthly testnet reset | bot reconciles cleanly, no phantom state | ☐ |
| R9 | Clock-drift fail-close | skew system clock > 1s | signed calls blocked | ☐ |
| R10 | 72h unattended soak | collector + trader, no intervention | no gaps, no crashes, memory stable | ☐ |

## 3. Automated subset

`cryptobot readiness` checks: mode gating, gate factors absent, API secret
configured, `.gitignore` coverage, `.env.example` cleanliness, DB/Redis
reachability, paper evidence (days, trades, PnL, drawdown) against the
graduation criteria in `docs/prd.md §3`. Exit code 0 = ready for owner
review; 1 = not ready.
