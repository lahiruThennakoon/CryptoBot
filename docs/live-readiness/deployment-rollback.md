# Deployment & Rollback Procedures — Phase 6

## 1. Deployment procedure (paper/testnet — the only supported modes today)

1. `git pull` the tagged release; verify `git describe` matches the approved tag.
2. `docker compose build` — images build clean.
3. `docker compose run --rm api alembic upgrade head` — migrations applied.
4. `cryptobot check` — connectivity, time sync, permissions, symbol rules OK.
5. `cryptobot readiness` — exit code 0.
6. `docker compose up -d` — api, collector, trader, dashboard.
7. Verify `/api/v1/health` is `ok` and the dashboard shows the correct mode badge.
8. Record: release tag, config version hash, operator, timestamp → audit log.

## 2. Live deployment (ONLY after approval.md is fully signed)

Everything above, plus, in order:
1. Create the live API key (withdrawals disabled, least privilege, IP allowlist).
2. Set live credentials in the production `.env` only (never in the repo).
3. Set `CRYPTOBOT_MODE=live` and `CONFIRM_LIVE_TRADING=I_UNDERSTAND_THE_RISKS`.
4. Set the small capital allocation and live loss limits in the live config.
5. Start; complete the interactive CLI confirmation naming the allocation.
6. First 48h: heightened monitoring; operator reachable; kill switch tested
   once with a real (tiny) order at start of window.

Missing any step → the system runs in paper mode by construction.

## 3. Rollback procedure

**Code rollback**
1. `docker compose down trader` (stops new orders; open stops remain in state).
2. `git checkout <previous-approved-tag>` → rebuild → `alembic downgrade` if
   the release added migrations (each migration ships a tested downgrade).
3. `cryptobot check && cryptobot readiness` → `docker compose up -d`.
4. Reconciliation runs automatically at startup; verify no mismatches in logs.

**Emergency rollback (something is actively wrong)**
1. Dashboard → Emergency stop (arm + confirm), or `POST /controls/emergency-stop`.
2. Verify on the exchange (testnet/live UI) that no orders remain open.
3. `docker compose down trader`.
4. Investigate with the audit trail before any restart; resuming after a halt
   requires the review acknowledgment flow.

**Data rollback**
Restore latest `pg_dump` backup → replay reconciliation against the exchange
→ readiness check → restart. Never trade against a database whose state has
not been reconciled with the exchange.

## 4. Configuration changes in production

Config is versioned (`config_versions`). Any risk-limit change requires: a
change note, the new version hash recorded, and appears in the audit trail.
Loosening a risk limit requires the same review rigor as a code deployment.
