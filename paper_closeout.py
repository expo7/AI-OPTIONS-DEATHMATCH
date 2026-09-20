"""One-time, paper-only closeout of legacy positions before Generation 1.

Run only on the Deathmatch VPS as root. The default is a read-only preview.
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from alpaca_readonly import PAPER_URL, PaperReader, load_credentials
from ledger import LedgerError


def snapshot(account, positions, path):
    """Write a private pre-closeout record outside the Git checkout."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "account": {key: account.get(key) for key in ("status", "equity", "cash", "portfolio_value")},
        "positions": [
            {key: p.get(key) for key in ("symbol", "asset_class", "qty", "side", "market_value")}
            for p in positions
        ],
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def inspect_closeout(reader):
    positions = reader.positions()
    orders = reader.open_orders()
    return {
        "positions": [
            {key: p.get(key) for key in ("symbol", "asset_class", "qty", "side")}
            for p in positions
        ],
        "open_orders": [
            {key: o.get(key) for key in ("symbol", "status", "side", "qty", "type")}
            for o in orders
        ],
    }


def close_legacy_positions(reader, execute, snapshot_path, opener=urlopen):
    account = reader.account()
    positions = reader.positions()
    orders = reader.open_orders()
    if account.get("status") != "ACTIVE":
        raise LedgerError("paper account is not active")
    if orders:
        raise LedgerError("open orders exist; resolve them before closeout")
    if not isinstance(positions, list):
        raise LedgerError("invalid position inventory")
    result = {"paper_endpoint": PAPER_URL, "positions_before": len(positions), "open_orders_before": 0}
    if not execute or not positions:
        result["action"] = "preview" if not execute else "already_flat"
        return result
    snapshot(account, positions, snapshot_path)
    request = Request(
        PAPER_URL + "/v2/positions?cancel_orders=true",
        headers={
            "APCA-API-KEY-ID": reader.credentials["APCA_API_KEY_ID"],
            "APCA-API-SECRET-KEY": reader.credentials["APCA_API_SECRET_KEY"],
            "Accept": "application/json",
        },
        method="DELETE",
    )
    try:
        with opener(request, timeout=30) as response:
            status = response.status
            body = json.load(response)
    except HTTPError as error:
        raise LedgerError(f"paper closeout request failed with HTTP {error.code}; check Alpaca and the snapshot") from None
    if status != 207 or not isinstance(body, list):
        raise LedgerError(f"unexpected paper closeout response HTTP {status}; inspect broker state")
    result["action"] = "liquidation_requested"
    result["response_statuses"] = [entry.get("status") for entry in body]
    result["positions_after_request"] = len(reader.positions())
    result["open_orders_after_request"] = len(reader.open_orders())
    result["note"] = "Orders may remain pending. Verify both counts reach zero before Generation 1."
    return result


def main():
    parser = argparse.ArgumentParser(description="Preview or liquidate legacy Deathmatch paper positions")
    parser.add_argument("--env-file", default="/etc/ai-options-deathmatch/alpaca.env")
    parser.add_argument("--execute", action="store_true", help="Send one paper-only liquidation request")
    parser.add_argument("--details", action="store_true", help="Read-only list of positions and pending order statuses")
    parser.add_argument("--snapshot", default="/var/lib/ai-options-deathmatch/legacy-closeout.json")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("run as root on the Deathmatch VPS")
    reader = PaperReader(load_credentials(args.env_file))
    if args.details and args.execute:
        parser.error("--details cannot be combined with --execute")
    result = inspect_closeout(reader) if args.details else close_legacy_positions(reader, args.execute, args.snapshot)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
