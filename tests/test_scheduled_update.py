import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ledger import LedgerError
from scheduled_update import main, run_update


class ScheduledUpdateTest(unittest.TestCase):
    def test_closed_market_skips_without_opening_ledger(self):
        class Reader:
            def clock(self):
                return {"is_open": False}

        with tempfile.TemporaryDirectory() as directory, \
             patch("scheduled_update.load_credentials", return_value={}), \
             patch("scheduled_update.PaperReader", return_value=Reader()), \
             patch("scheduled_update.Ledger") as ledger:
            result = run_update("missing.sqlite3", "unused.env", "results.json",
                                Path(directory) / "update.lock")
        self.assertEqual(result, {"status": "skipped", "reason": "market is closed"})
        ledger.assert_not_called()

    def test_open_market_syncs_before_common_mark(self):
        class Reader:
            def clock(self):
                return {"is_open": True}

        fake_ledger = Mock()
        with tempfile.TemporaryDirectory() as directory, \
             patch("scheduled_update.load_credentials", return_value={}), \
             patch("scheduled_update.PaperReader", return_value=Reader()), \
             patch("scheduled_update.Ledger", return_value=fake_ledger), \
             patch("scheduled_update.sync", return_value={"seen": 1, "inserted": 0}) as syncing, \
             patch("scheduled_update.mark", return_value={"published": 5}) as marking:
            result = run_update("ledger.sqlite3", "paper.env", "results.json",
                                Path(directory) / "update.lock")
        syncing.assert_called_once_with(fake_ledger, "paper.env")
        marking.assert_called_once_with(fake_ledger, "paper.env", "results.json")
        self.assertEqual(result["status"], "updated")

    def test_broker_error_returns_structured_result_instead_of_raising(self):
        class Reader:
            def clock(self):
                return {"is_open": True}

        fake_ledger = Mock()
        with tempfile.TemporaryDirectory() as directory, \
             patch("scheduled_update.load_credentials", return_value={}), \
             patch("scheduled_update.PaperReader", return_value=Reader()), \
             patch("scheduled_update.Ledger", return_value=fake_ledger), \
             patch("scheduled_update.sync", side_effect=LedgerError("broker positions do not reconcile")):
            result = run_update("ledger.sqlite3", "paper.env", "results.json",
                                Path(directory) / "update.lock")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "LedgerError")
        self.assertIn("reconcile", result["message"])
        fake_ledger.close.assert_called_once()

    def test_main_exits_nonzero_on_error_status(self):
        with patch("scheduled_update.run_update", return_value={"status": "error", "error": "LedgerError", "message": "boom"}), \
             patch("sys.argv", ["scheduled_update.py"]):
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 1)

    def test_main_does_not_exit_on_updated_status(self):
        with patch("scheduled_update.run_update", return_value={"status": "updated"}), \
             patch("sys.argv", ["scheduled_update.py"]):
            main()
