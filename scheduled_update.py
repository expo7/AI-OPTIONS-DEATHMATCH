"""Root-only, non-trading competition fill and mark updater."""

import argparse
import fcntl
import json
import sys
from pathlib import Path

from alpaca_readonly import PaperReader, load_credentials
from competition_operator import auto_manage_exits, mark, sync
from ledger import Ledger, LedgerError


def run_update(ledger_path, env_file, public_results, lock_path):
    Path(lock_path).parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "skipped", "reason": "another update is running"}
        try:
            credentials = load_credentials(env_file)
            if PaperReader(credentials).clock().get("is_open") is not True:
                return {"status": "skipped", "reason": "market is closed"}
            ledger = Ledger(ledger_path)
            try:
                fills = sync(ledger, env_file)
                result = mark(ledger, env_file, public_results)
                exits = auto_manage_exits(ledger, env_file, result["positions"])
                return {"status": "updated", "fills": fills, "mark": result, "exits": exits}
            finally:
                ledger.close()
        except (LedgerError, OSError, ValueError) as error:
            # This runs unattended every five minutes as a root timer. A raw
            # traceback here is invisible to anything monitoring the script's
            # normal JSON output. Surface a structured, still fail-closed
            # result instead of silently swallowing or retrying the error.
            return {"status": "error", "error": type(error).__name__, "message": str(error)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default="/var/lib/ai-options-deathmatch/ledger.sqlite3")
    parser.add_argument("--env-file", default="/etc/ai-options-deathmatch/alpaca.env")
    parser.add_argument("--public-results", default="/var/lib/ai-options-deathmatch-public/results.json")
    parser.add_argument("--lock", default="/run/lock/ai-options-deathmatch-update.lock")
    args = parser.parse_args()
    result = run_update(args.ledger, args.env_file, args.public_results, args.lock)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
