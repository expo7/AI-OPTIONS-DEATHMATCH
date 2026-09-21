import io
import json
import tempfile
import unittest
from pathlib import Path

from alpaca_readonly import PAPER_URL
from alpaca_submit import EXECUTION_ENABLE_TOKEN, PaperSubmitter, submit_reserved_exit, submit_reserved_order
from ledger import Ledger, LedgerError


SYMBOL = "SPY261218C00600000"
WHEN = "2026-09-21T14:00:00Z"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeReader:
    def __init__(self, positions=None, orders=None, account=None):
        self._positions = positions or []
        self._orders = orders or []
        self._account = account or {"status": "ACTIVE", "trading_blocked": False}

    def account(self):
        return self._account

    def positions(self):
        return self._positions

    def open_orders(self):
        return self._orders


class GuardedPaperSubmitterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.sqlite3"
        self.ledger = Ledger(self.path)
        self.ledger.initialize()
        self.ledger.add_bot("trend", 1_000_000)
        self.ledger.record_bot_version("g1-trend-v1", "trend", 1, {"strategy": "trend"}, WHEN)
        self.ledger.record_opportunity("opp-1", WHEN, WHEN, {"underlying": "SPY"})
        self.ledger.record_decision(
            "decision-1", "opp-1", "trend", "g1-trend-v1", "buy",
            "Trend and liquidity qualified.", WHEN,
            option_symbol=SYMBOL, quantity=1, limit_cents=250,
        )
        self.ledger.reserve_order(
            "dm-g1-trend-0001", "trend", SYMBOL, "buy", 1, 250,
            decision_id="decision-1",
        )
        self.credentials = {
            "APCA_API_BASE_URL": PAPER_URL,
            "APCA_API_KEY_ID": "paper-id",
            "APCA_API_SECRET_KEY": "paper-secret",
        }

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def submitter(self, calls):
        response = {
            "id": "broker-1", "client_order_id": "dm-g1-trend-0001", "type": "limit",
            "status": "accepted", "symbol": SYMBOL, "side": "buy", "qty": "1",
            "limit_price": "2.50",
        }

        def opener(request, timeout):
            calls.append({
                "url": request.full_url, "method": request.get_method(), "timeout": timeout,
                "headers": dict(request.header_items()), "payload": json.loads(request.data),
            })
            return FakeResponse(json.dumps(response).encode())

        return PaperSubmitter(self.credentials, EXECUTION_ENABLE_TOKEN, opener=opener)

    def test_constructor_requires_exact_paper_endpoint_and_enable_token(self):
        with self.assertRaises(LedgerError):
            PaperSubmitter(self.credentials, "true")
        with self.assertRaises(LedgerError):
            PaperSubmitter({**self.credentials, "APCA_API_BASE_URL": "https://api.alpaca.markets"}, EXECUTION_ENABLE_TOKEN)

    def test_success_requires_baseline_and_posts_exact_reserved_terms(self):
        calls = []
        submitter = self.submitter(calls)
        with self.assertRaises(LedgerError):
            submit_reserved_order(self.ledger, FakeReader(), submitter, "dm-g1-trend-0001")
        self.assertEqual(calls, [])

        self.ledger.record_launch_baseline(1, WHEN, "ACTIVE", 0, 0)
        broker_id = submit_reserved_order(self.ledger, FakeReader(), submitter, "dm-g1-trend-0001")
        self.assertEqual(broker_id, "broker-1")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["url"], PAPER_URL + "/v2/orders")
        self.assertEqual(calls[0]["method"], "POST")
        self.assertEqual(calls[0]["payload"], {
            "symbol": SYMBOL, "qty": 1, "side": "buy", "type": "limit",
            "time_in_force": "day", "limit_price": "2.50",
            "client_order_id": "dm-g1-trend-0001",
        })
        order = self.ledger.db.execute("SELECT * FROM orders WHERE client_order_id='dm-g1-trend-0001'").fetchone()
        self.assertEqual((order["status"], order["broker_order_id"]), ("accepted", "broker-1"))

    def test_reconciliation_and_open_order_gates_block_before_post(self):
        self.ledger.record_launch_baseline(1, WHEN, "ACTIVE", 0, 0)
        calls = []
        submitter = self.submitter(calls)
        with self.assertRaises(LedgerError):
            submit_reserved_order(
                self.ledger, FakeReader(positions=[{"symbol": SYMBOL, "qty": "1"}]),
                submitter, "dm-g1-trend-0001",
            )
        with self.assertRaises(LedgerError):
            submit_reserved_order(
                self.ledger, FakeReader(orders=[{"id": "legacy-order"}]),
                submitter, "dm-g1-trend-0001",
            )
        with self.assertRaises(LedgerError):
            submit_reserved_order(
                self.ledger, FakeReader(account={"status": "ACTIVE", "trading_blocked": True}),
                submitter, "dm-g1-trend-0001",
            )
        self.assertEqual(calls, [])

    def test_baseline_rejects_nonflat_or_unversioned_account(self):
        second = Ledger(Path(self.tmp.name) / "empty.sqlite3")
        try:
            second.initialize()
            second.add_bot("trend", 1_000_000)
            with self.assertRaises(LedgerError):
                second.record_launch_baseline(1, WHEN, "ACTIVE", 0, 0)
        finally:
            second.close()
        with self.assertRaises(LedgerError):
            self.ledger.record_launch_baseline(1, WHEN, "ACTIVE", 1, 0)
        with self.assertRaises(LedgerError):
            self.ledger.record_launch_baseline(1, WHEN, "SUSPENDED", 0, 0)

    def test_attributed_exit_posts_only_owned_sell(self):
        self.ledger.record_launch_baseline(1, WHEN, "ACTIVE", 0, 0)
        self.ledger.accept_order("dm-g1-trend-0001", "broker-buy")
        self.ledger.record_fill("fill-buy", "dm-g1-trend-0001", 1, 200, WHEN)
        self.ledger.record_exit_decision(
            "exit-1", "trend", "g1-trend-v1", SYMBOL, 1, 225, "operator",
            "Supervised closing order.", WHEN,
        )
        self.ledger.reserve_exit_order("dm-g1-exit-trend-0001", "exit-1")
        calls = []
        response = {"id": "broker-sell", "client_order_id": "dm-g1-exit-trend-0001",
                    "type": "limit", "status": "new", "symbol": SYMBOL, "side": "sell",
                    "qty": "1", "limit_price": "2.25"}
        def opener(request, timeout):
            calls.append(json.loads(request.data))
            return FakeResponse(json.dumps(response).encode())
        broker_id = submit_reserved_exit(
            self.ledger, FakeReader(positions=[{"symbol": SYMBOL, "qty": "1"}]),
            PaperSubmitter(self.credentials, EXECUTION_ENABLE_TOKEN, opener=opener),
            "dm-g1-exit-trend-0001",
        )
        self.assertEqual(broker_id, "broker-sell")
        self.assertEqual(calls[0]["side"], "sell")
        self.assertEqual(calls[0]["limit_price"], "2.25")


if __name__ == "__main__":
    unittest.main()
