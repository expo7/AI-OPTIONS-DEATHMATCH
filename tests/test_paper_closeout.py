import json
import tempfile
import unittest
from pathlib import Path

from paper_closeout import close_legacy_positions, inspect_closeout
from ledger import LedgerError


class Reader:
    credentials = {"APCA_API_KEY_ID": "test", "APCA_API_SECRET_KEY": "test"}
    def __init__(self, orders=None, positions=None):
        self.orders = orders if orders is not None else []
        self.current_positions = positions if positions is not None else [{"symbol": "SPY", "qty": "2", "side": "long", "asset_class": "us_equity"}]
        self.calls = 0

    def account(self):
        return {"status": "ACTIVE", "equity": "1000", "cash": "200"}

    def positions(self):
        self.calls += 1
        return self.current_positions

    def open_orders(self):
        return self.orders


class Response:
    status = 207
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self, *args):
        return b'[{"status": 200}]'


class CloseoutTests(unittest.TestCase):
    def test_preview_never_submits_or_saves_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            result = close_legacy_positions(Reader(), False, path, opener=lambda *args, **kwargs: self.fail("DELETE called"))
            self.assertEqual(result["action"], "preview")
            self.assertFalse(path.exists())

    def test_inspection_is_read_only_and_limits_fields(self):
        reader = Reader(orders=[{"symbol": "SPY", "status": "accepted", "id": "private-id"}])
        result = inspect_closeout(reader)
        self.assertEqual(result["open_orders"], [{"symbol": "SPY", "status": "accepted", "side": None, "qty": None, "type": None}])
        self.assertNotIn("id", result["open_orders"][0])

    def test_open_orders_block_liquidation(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(LedgerError, "open orders"):
                close_legacy_positions(Reader(orders=[{}]), True, Path(directory) / "snapshot", opener=lambda *args, **kwargs: self.fail("DELETE called"))

    def test_execution_targets_only_paper_and_saves_snapshot_first(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            def opener(request, timeout):
                self.assertTrue(path.exists())
                self.assertEqual(request.get_method(), "DELETE")
                self.assertEqual(request.full_url, "https://paper-api.alpaca.markets/v2/positions?cancel_orders=true")
                return Response()
            result = close_legacy_positions(Reader(), True, path, opener=opener)
            self.assertEqual(result["action"], "liquidation_requested")
            self.assertEqual(json.loads(path.read_text())["positions"][0]["symbol"], "SPY")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
