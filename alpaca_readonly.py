"""Paper-only, GET-only Alpaca adapter. No order submission functions exist here."""

import argparse
import json
import os
import stat
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ledger import LedgerError


PAPER_URL = "https://paper-api.alpaca.markets"


def load_credentials(path):
    path = Path(path)
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise LedgerError("credential file must not be accessible by group or others")
    entries = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key in entries:
            raise LedgerError("invalid credential file")
        entries[key] = value
    if entries.get("APCA_API_BASE_URL") != PAPER_URL:
        raise LedgerError("only the exact Alpaca paper endpoint is permitted")
    if not entries.get("APCA_API_KEY_ID") or not entries.get("APCA_API_SECRET_KEY"):
        raise LedgerError("paper key and secret are required")
    return entries


class PaperReader:
    def __init__(self, credentials, opener=urlopen):
        if credentials.get("APCA_API_BASE_URL") != PAPER_URL:
            raise LedgerError("live endpoint is prohibited")
        self.credentials = credentials
        self.opener = opener

    def get(self, path, params=None):
        if not path.startswith("/v2/") or "?" in path or "//" in path:
            raise LedgerError("invalid paper API path")
        url = PAPER_URL + path + ("?" + urlencode(params) if params else "")
        request = Request(url, headers={
            "APCA-API-KEY-ID": self.credentials["APCA_API_KEY_ID"],
            "APCA-API-SECRET-KEY": self.credentials["APCA_API_SECRET_KEY"],
            "Accept": "application/json",
        }, method="GET")
        with self.opener(request, timeout=12) as response:
            return json.load(response)

    def account(self):
        return self.get("/v2/account")

    def positions(self):
        return self.get("/v2/positions")

    def open_orders(self):
        # Alpaca caps a page at 500; fail closed if more may exist.
        orders = self.get("/v2/orders", {"status": "open", "limit": 500})
        if not isinstance(orders, list) or len(orders) == 500:
            raise LedgerError("open order inventory may be incomplete")
        return orders

    def recent_fills(self, page_size=100):
        if not isinstance(page_size, int) or not 1 <= page_size <= 100:
            raise LedgerError("page size outside 1..100")
        return self.get("/v2/account/activities/FILL", {"page_size": page_size, "direction": "desc"})


def whole_number(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise LedgerError("invalid broker quantity") from None
    if not number.is_finite() or number != number.to_integral_value():
        raise LedgerError("fractional option contracts are not supported")
    return int(number)


def premium_cents(value):
    try:
        cents = Decimal(str(value)) * 100
    except (InvalidOperation, TypeError):
        raise LedgerError("invalid broker premium") from None
    if not cents.is_finite() or cents != cents.to_integral_value() or cents <= 0:
        raise LedgerError("unsupported subcent or invalid broker premium")
    return int(cents)


def apply_trade_activity(ledger, activity):
    """Attribute a broker FILL to an already accepted, uniquely tagged order.

    Any unknown or inconsistent activity stops ingestion for manual review.
    """
    if activity.get("activity_type") != "FILL" or activity.get("type") not in ("fill", "partial_fill"):
        raise LedgerError("not a trade fill activity")
    order = ledger.db.execute("SELECT * FROM orders WHERE broker_order_id=?", (activity.get("order_id"),)).fetchone()
    if not order or order["symbol"] != activity.get("symbol") or order["side"] != activity.get("side"):
        raise LedgerError("unattributed or inconsistent broker fill")
    return ledger.record_fill(
        activity["id"], order["client_order_id"], whole_number(activity["qty"]),
        premium_cents(activity["price"]), activity["transaction_time"])


def main():
    parser = argparse.ArgumentParser(description="Read-only Alpaca paper account diagnostic")
    parser.add_argument("--env-file", default="/etc/ai-options-deathmatch/alpaca.env")
    args = parser.parse_args()
    reader = PaperReader(load_credentials(args.env_file))
    account = reader.account()
    positions = reader.positions()
    open_orders = reader.open_orders()
    fills = reader.recent_fills()
    # Deliberately print no keys, account identifier, order IDs, or individual trades.
    print(json.dumps({
        "paper_endpoint": PAPER_URL,
        "account_status": account.get("status"),
        "options_trading_level": account.get("options_trading_level"),
        "open_positions": len(positions),
        "open_orders": len(open_orders),
        "recent_fill_activities": len(fills),
        "note": "A count of 100 fills may mean more history exists; no orders were placed.",
    }, indent=2))


if __name__ == "__main__":
    main()
