import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scheduled_update import run_update


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
