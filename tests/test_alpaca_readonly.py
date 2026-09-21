import io
import tempfile
import unittest
from pathlib import Path

from alpaca_readonly import (
    PAPER_URL, PaperReader, apply_order_acceptance, apply_trade_activity,
    load_credentials, premium_cents, sync_fill_activities,
)
from ledger import Ledger, LedgerError


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class PaperAdapterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env_path = Path(self.tmp.name) / "paper.env"
        self.env_path.write_text("APCA_API_BASE_URL=https://paper-api.alpaca.markets\nAPCA_API_KEY_ID=test-id\nAPCA_API_SECRET_KEY=test-secret\n")
        self.env_path.chmod(0o600)

    def tearDown(self):
        self.tmp.cleanup()

    def test_live_endpoint_refused_and_only_get_requests_made(self):
        credentials = load_credentials(self.env_path)
        with self.assertRaises(LedgerError):
            PaperReader({**credentials, "APCA_API_BASE_URL": "https://api.alpaca.markets"})
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, request.get_method(), timeout))
            return FakeResponse(b'{"status":"ACTIVE"}')

        reader = PaperReader(credentials, opener=opener)
        self.assertEqual(reader.account()["status"], "ACTIVE")
        self.assertEqual(calls, [(PAPER_URL + "/v2/account", "GET", 12)])
        self.env_path.chmod(0o644)
        with self.assertRaises(LedgerError):
            load_credentials(self.env_path)

    def test_attribution_requires_matching_accepted_broker_order(self):
        db = Ledger(Path(self.tmp.name) / "test.sqlite3")
        try:
            db.initialize()
            db.add_bot("alpha", 2_500_000)
            db.reserve_order("alpha-1", "alpha", "SPY261218C00600000", "buy", 1, 250)
            db.accept_order("alpha-1", "broker-1")
            fill = {"activity_type": "FILL", "type": "fill", "order_id": "broker-1",
                    "symbol": "SPY261218C00600000", "side": "buy", "id": "activity-1",
                    "qty": "1", "price": "2.13", "transaction_time": "2026-09-21T14:35:00Z"}
            self.assertEqual(premium_cents(fill["price"]), 213)
            self.assertTrue(apply_trade_activity(db, fill))
            self.assertFalse(apply_trade_activity(db, fill))
            self.assertEqual(db.position("alpha", fill["symbol"]), 1)
            with self.assertRaises(LedgerError):
                apply_trade_activity(db, {**fill, "order_id": "unknown", "id": "activity-2"})
            with self.assertRaises(LedgerError):
                apply_trade_activity(db, {**fill, "price": "2.135", "id": "activity-3"})
        finally:
            db.close()

    def test_broker_acceptance_must_exactly_match_reservation(self):
        db = Ledger(Path(self.tmp.name) / "accept.sqlite3")
        try:
            db.initialize()
            db.add_bot("alpha", 2_500_000)
            db.reserve_order("dm-g1-alpha-1", "alpha", "SPY261218C00600000", "buy", 1, 250)
            accepted = {
                "id": "broker-1", "client_order_id": "dm-g1-alpha-1", "type": "limit",
                "status": "accepted", "symbol": "SPY261218C00600000", "side": "buy",
                "qty": "1", "limit_price": "2.50",
            }
            apply_order_acceptance(db, accepted)
            order = db.db.execute("SELECT * FROM orders WHERE client_order_id='dm-g1-alpha-1'").fetchone()
            self.assertEqual((order["status"], order["broker_order_id"]), ("accepted", "broker-1"))

            db.reserve_order("dm-g1-alpha-2", "alpha", "QQQ261218C00500000", "buy", 1, 300)
            with self.assertRaises(LedgerError):
                apply_order_acceptance(db, {
                    **accepted, "id": "broker-2", "client_order_id": "dm-g1-alpha-2",
                    "symbol": "QQQ261218C00500000", "limit_price": "3.01",
                })
            untouched = db.db.execute("SELECT status FROM orders WHERE client_order_id='dm-g1-alpha-2'").fetchone()
            self.assertEqual(untouched["status"], "reserved")
        finally:
            db.close()

    def test_paginated_fill_sync_applies_oldest_first_and_is_idempotent(self):
        db = Ledger(Path(self.tmp.name) / "sync.sqlite3")
        try:
            db.initialize()
            db.add_bot("alpha", 2_500_000)
            db.reserve_order("dm-g1-alpha-1", "alpha", "SPY261218C00600000", "buy", 2, 250)
            db.accept_order("dm-g1-alpha-1", "broker-1")
            older = {"activity_type": "FILL", "type": "partial_fill", "order_id": "broker-1",
                     "symbol": "SPY261218C00600000", "side": "buy", "id": "activity-1",
                     "qty": "1", "price": "2.10", "transaction_time": "2026-09-21T14:35:00Z"}
            newer = {**older, "type": "fill", "id": "activity-2", "price": "2.20",
                     "transaction_time": "2026-09-21T14:36:00Z"}

            class FakeReader:
                def fill_pages(self, after, until=None, page_size=100, max_pages=100):
                    self.arguments = (after, until, page_size, max_pages)
                    yield [newer]
                    yield [older]

            reader = FakeReader()
            result = sync_fill_activities(db, reader, "2026-09-21T14:00:00Z")
            self.assertEqual(result, {"seen": 2, "inserted": 2})
            self.assertEqual(db.position("alpha", "SPY261218C00600000"), 2)
            self.assertEqual(reader.arguments[0], "2026-09-21T14:00:00Z")
            self.assertEqual(sync_fill_activities(db, reader, "2026-09-21T14:00:00Z"), {"seen": 2, "inserted": 0})
        finally:
            db.close()

    def test_fill_page_tokens_and_loop_guard(self):
        credentials = load_credentials(self.env_path)
        calls = []
        pages = [
            b'[{"id":"a2"},{"id":"a1"}]',
            b'[{"id":"a0"}]',
        ]

        def opener(request, timeout):
            calls.append(request.full_url)
            return FakeResponse(pages.pop(0))

        reader = PaperReader(credentials, opener=opener)
        self.assertEqual([len(page) for page in reader.fill_pages("2026-09-21T14:00:00Z", page_size=2)], [2, 1])
        self.assertNotIn("page_token", calls[0])
        self.assertIn("page_token=a1", calls[1])
        self.assertIn("after=2026-09-21T14%3A00%3A00Z", calls[0])

        repeating = PaperReader(credentials, opener=lambda request, timeout: FakeResponse(b'[{"id":"same"}]'))
        with self.assertRaises(LedgerError):
            list(repeating.fill_pages("baseline", page_size=1, max_pages=3))


if __name__ == "__main__":
    unittest.main()
