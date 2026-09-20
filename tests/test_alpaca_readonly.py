import io
import tempfile
import unittest
from pathlib import Path

from alpaca_readonly import PAPER_URL, PaperReader, apply_trade_activity, load_credentials, premium_cents
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


if __name__ == "__main__":
    unittest.main()
