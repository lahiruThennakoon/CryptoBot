"""Operational drill definitions: what each drill proves, and how to run it.

These are the rehearsals that must happen BEFORE real money is involved.
Each one targets a specific way trading systems lose money that has nothing
to do with strategy quality: state corruption, blind trading, duplicate
orders, an unusable kill switch, unrecoverable data, or a leaked key.

Acknowledging a drill is a factual claim that you ran it and it passed.
Ticking a box without running it defeats the entire purpose of the gate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DrillSpec:
    name: str
    title: str
    why: str
    how: tuple[str, ...]
    pass_criteria: str


DRILL_SPECS: dict[str, DrillSpec] = {
    "restart_and_reconciliation": DrillSpec(
        name="restart_and_reconciliation",
        title="Restart and reconciliation",
        why="A crash mid-position must never leave the bot guessing what it owns. "
            "Trading on imagined state is how small bugs become large losses.",
        how=(
            "Start the paper trader and wait until at least one position is open.",
            "Kill the trader window abruptly (close it, do not use Ctrl+C).",
            "Restart it: cryptobot trade",
            "Watch the startup logs for the reconciliation step.",
        ),
        pass_criteria="Positions, balances and orders after restart match what the "
                      "exchange/paper account actually holds; no duplicate positions "
                      "appear and no phantom position is invented.",
    ),
    "api_disconnection": DrillSpec(
        name="api_disconnection",
        title="API disconnection",
        why="When market data stops arriving, prices in memory are fiction. The bot "
            "must refuse to trade rather than act on stale numbers.",
        how=(
            "With the trader running, disable your network adapter (or turn off Wi-Fi) "
            "for about 3 minutes.",
            "Watch the trader window for ws_disconnected and market_data_stale entries.",
            "Re-enable the network and watch it reconnect and backfill.",
        ),
        pass_criteria="Entries are blocked while data is stale (STALE_DATA in the "
                      "signal log), the WebSocket reconnects with backoff, gaps are "
                      "backfilled, and the process never crashes.",
    ),
    "duplicate_order_prevention": DrillSpec(
        name="duplicate_order_prevention",
        title="Duplicate order prevention",
        why="Retries after a timeout are the classic way to accidentally buy twice. "
            "Idempotency must be enforced, not hoped for.",
        how=(
            "Run the opt-in testnet suite, which submits the same clientOrderId twice:",
            "cd backend; pytest -m testnet -k duplicate",
            "Alternatively: replay candles into the runtime and confirm one fill only.",
        ),
        pass_criteria="The second submission is rejected by the exchange and by the "
                      "database's unique client_order_id constraint; exactly one order "
                      "exists.",
    ),
    "emergency_stop": DrillSpec(
        name="emergency_stop",
        title="Emergency stop",
        why="A kill switch that has never been tested is a kill switch you do not have.",
        how=(
            "Start demo mode so a position opens quickly: .\\demo.ps1",
            "Once a position is open, press Emergency stop on the dashboard.",
            "Confirm in the dialog (this uses a one-time server token).",
        ),
        pass_criteria="All open positions close immediately with reason "
                      "emergency_stop, new entries are blocked until you resume, and "
                      "the action appears in the audit trail and risk events.",
    ),
    "backup_restore": DrillSpec(
        name="backup_restore",
        title="Backup and restore",
        why="Your trade history is your tax record and your only performance evidence. "
            "An untested backup is not a backup.",
        how=(
            "Dump: docker compose exec postgres pg_dump -U cryptobot cryptobot > backup.sql",
            "Create a scratch database and restore the dump into it.",
            "Point DATABASE_URL at the restored copy and run: cryptobot doctor",
        ),
        pass_criteria="The restored database passes doctor with the same candle counts, "
                      "trades and equity history as the original.",
    ),
    "key_rotation": DrillSpec(
        name="key_rotation",
        title="API key rotation",
        why="If a key leaks you must be able to replace it in minutes, without "
            "downtime or a half-configured state.",
        how=(
            "Create a second Testnet API key at https://testnet.binance.vision",
            "Put the new key in .env, restart the API and trader.",
            "Verify with: cryptobot check",
            "Delete the old key on Binance and confirm nothing breaks.",
        ),
        pass_criteria="The bot operates normally on the new key, the old key is "
                      "revoked, and no secret ever appeared in logs.",
    ),
}


def spec(name: str) -> DrillSpec | None:
    return DRILL_SPECS.get(name)
