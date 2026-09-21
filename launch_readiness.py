"""Read-only launch-gate report for AI Options Deathmatch."""

import argparse
import json
import sqlite3
from pathlib import Path

from alpaca_readonly import PaperReader, load_credentials
from alpaca_submit import broker_position_map
from bots import BOTS
from ledger import Ledger, LedgerError


def check_launch_readiness(reader, ledger=None, generation=1):
    """Return a sanitized gate report without changing broker or ledger state."""
    account = reader.account()
    positions = reader.positions()
    open_orders = reader.open_orders()
    account_ready = (
        account.get("status") == "ACTIVE"
        and account.get("trading_blocked") is not True
        and account.get("account_blocked") is not True
        and account.get("trade_suspended_by_user") is not True
    )
    broker_flat = len(positions) == 0 and len(open_orders) == 0

    initialized = False
    reconciled = False
    baseline_recorded = False
    no_unresolved_local_orders = False
    if ledger is not None:
        expected = {bot.slug for bot in BOTS}
        actual = {row["id"] for row in ledger.db.execute("SELECT id FROM bots")}
        versioned = {
            row["bot_id"] for row in ledger.db.execute(
                "SELECT bot_id FROM bot_versions WHERE generation=?", (generation,)
            )
        }
        initialized = actual == expected and versioned == expected
        reconciled = not ledger.reconcile(broker_position_map(positions))
        baseline_recorded = ledger.db.execute(
            "SELECT 1 FROM launch_baselines WHERE generation=?", (generation,)
        ).fetchone() is not None
        no_unresolved_local_orders = ledger.db.execute(
            "SELECT 1 FROM orders WHERE status IN ('reserved','accepted','partial') LIMIT 1"
        ).fetchone() is None

    gates = {
        "paper_account_active": account_ready,
        "broker_positions_zero": len(positions) == 0,
        "broker_open_orders_zero": len(open_orders) == 0,
        "generation_initialized": initialized,
        "broker_ledger_reconciled": reconciled,
        "launch_baseline_recorded": baseline_recorded,
        "local_unresolved_orders_zero": no_unresolved_local_orders,
    }
    return {
        "generation": generation,
        "safe_to_initialize": account_ready and broker_flat,
        "safe_to_record_baseline": account_ready and broker_flat and initialized and reconciled,
        "execution_ready": all(gates.values()),
        "gates": gates,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default="/etc/ai-options-deathmatch/alpaca.env")
    parser.add_argument("--ledger", default="/var/lib/ai-options-deathmatch/ledger.sqlite3")
    parser.add_argument("--generation", type=int, default=1)
    arguments = parser.parse_args()

    ledger = None
    try:
        ledger_path = Path(arguments.ledger)
        if ledger_path.is_file():
            ledger = Ledger(ledger_path, readonly=True)
        report = check_launch_readiness(
            PaperReader(load_credentials(arguments.env_file)), ledger, arguments.generation
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["execution_ready"] else 1
    except (LedgerError, OSError, sqlite3.DatabaseError) as error:
        print(json.dumps({"execution_ready": False, "error": str(error)}, indent=2))
        return 2
    finally:
        if ledger is not None:
            ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
