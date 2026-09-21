"""Heavily guarded Alpaca paper-order submission boundary.

Importing this module performs no network or database work. The public web
process does not import it. Opening and closing boundaries remain separate.
"""

import json
from decimal import Decimal
from urllib.request import Request, urlopen

from alpaca_readonly import PAPER_URL, apply_order_acceptance, whole_number
from ledger import LedgerError


EXECUTION_ENABLE_TOKEN = "ENABLE_DEATHMATCH_PAPER_ORDERS"


class PaperSubmitter:
    def __init__(self, credentials, enable_token, opener=urlopen):
        if credentials.get("APCA_API_BASE_URL") != PAPER_URL:
            raise LedgerError("live endpoint is prohibited")
        if enable_token != EXECUTION_ENABLE_TOKEN:
            raise LedgerError("paper execution is disabled")
        self.credentials = credentials
        self.opener = opener

    def post_order(self, payload):
        data = json.dumps(payload, separators=(",", ":")).encode()
        request = Request(PAPER_URL + "/v2/orders", data=data, headers={
            "APCA-API-KEY-ID": self.credentials["APCA_API_KEY_ID"],
            "APCA-API-SECRET-KEY": self.credentials["APCA_API_SECRET_KEY"],
            "Accept": "application/json",
            "Content-Type": "application/json",
        }, method="POST")
        with self.opener(request, timeout=12) as response:
            return json.load(response)


def broker_position_map(positions):
    if not isinstance(positions, list):
        raise LedgerError("broker positions response is not a list")
    result = {}
    for position in positions:
        symbol = position.get("symbol")
        if not symbol or symbol in result:
            raise LedgerError("broker positions contain a missing or duplicate symbol")
        result[symbol] = whole_number(position.get("qty"))
    return result


def submit_reserved_order(ledger, reader, submitter, client_order_id):
    """Submit one decision-linked long-option reservation after all gates pass."""
    row = ledger.db.execute(
        """SELECT o.*,d.id AS decision_id,bv.generation
           FROM orders o
           JOIN decision_orders link ON link.client_order_id=o.client_order_id
           JOIN decisions d ON d.id=link.decision_id
           JOIN bot_versions bv ON bv.id=d.bot_version_id
           WHERE o.client_order_id=?""",
        (client_order_id,),
    ).fetchone()
    if not row or row["status"] != "reserved":
        raise LedgerError("submission requires a decision-linked reserved order")
    if row["side"] != "buy" or not client_order_id.startswith(f'dm-g{row["generation"]}-'):
        raise LedgerError("V1 submission permits only tagged opening buys")
    baseline = ledger.db.execute(
        "SELECT * FROM launch_baselines WHERE generation=?", (row["generation"],)
    ).fetchone()
    if not baseline:
        raise LedgerError("generation has no flat-account launch baseline")

    account = reader.account()
    if account.get("status") != "ACTIVE" or account.get("trading_blocked") is True or \
       account.get("account_blocked") is True or account.get("trade_suspended_by_user") is True:
        raise LedgerError("paper account is not currently eligible to trade")
    open_orders = reader.open_orders()
    if open_orders:
        raise LedgerError("broker has unresolved open orders")
    mismatches = ledger.reconcile(broker_position_map(reader.positions()))
    if mismatches:
        raise LedgerError("broker positions do not reconcile to bot allocations")

    payload = {
        "symbol": row["symbol"],
        "qty": row["quantity"],
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "limit_price": str((Decimal(row["limit_cents"]) / 100).quantize(Decimal("0.00"))),
        "client_order_id": row["client_order_id"],
    }
    response = submitter.post_order(payload)
    apply_order_acceptance(ledger, response)
    return response.get("id")


def submit_reserved_exit(ledger, reader, submitter, client_order_id):
    """Submit one fully attributed closing limit order after live reconciliation."""
    row = ledger.db.execute(
        """SELECT o.*,x.id AS exit_decision_id,bv.generation
           FROM orders o
           JOIN exit_decision_orders link ON link.client_order_id=o.client_order_id
           JOIN exit_decisions x ON x.id=link.exit_decision_id
           JOIN bot_versions bv ON bv.id=x.bot_version_id
           WHERE o.client_order_id=?""", (client_order_id,),
    ).fetchone()
    if not row or row["status"] != "reserved" or row["side"] != "sell":
        raise LedgerError("exit submission requires an attributed reserved sell")
    if not client_order_id.startswith(f'dm-g{row["generation"]}-exit-'):
        raise LedgerError("exit order does not have the required generation tag")
    if not ledger.db.execute(
        "SELECT 1 FROM launch_baselines WHERE generation=?", (row["generation"],)
    ).fetchone():
        raise LedgerError("generation has no launch baseline")
    account = reader.account()
    if account.get("status") != "ACTIVE" or account.get("trading_blocked") is True or \
       account.get("account_blocked") is True or account.get("trade_suspended_by_user") is True:
        raise LedgerError("paper account is not currently eligible to trade")
    if reader.open_orders():
        raise LedgerError("broker has unresolved open orders")
    if ledger.reconcile(broker_position_map(reader.positions())):
        raise LedgerError("broker positions do not reconcile to bot allocations")
    if ledger.position(row["bot_id"], row["symbol"]) < row["quantity"]:
        raise LedgerError("bot no longer owns the reserved exit quantity")
    response = submitter.post_order({
        "symbol": row["symbol"], "qty": row["quantity"], "side": "sell", "type": "limit",
        "time_in_force": "day",
        "limit_price": str((Decimal(row["limit_cents"]) / 100).quantize(Decimal("0.00"))),
        "client_order_id": row["client_order_id"],
    })
    apply_order_acceptance(ledger, response)
    return response.get("id")
