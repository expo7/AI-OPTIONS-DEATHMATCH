import tempfile
import unittest
from pathlib import Path

from init_generation import initialize_generation
from launch_readiness import check_launch_readiness
from ledger import Ledger


WHEN = "2026-09-21T14:00:00Z"


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


class LaunchReadinessTest(unittest.TestCase):
    def test_flat_account_without_ledger_is_safe_only_to_initialize(self):
        report = check_launch_readiness(FakeReader())
        self.assertTrue(report["safe_to_initialize"])
        self.assertFalse(report["safe_to_record_baseline"])
        self.assertFalse(report["execution_ready"])
        self.assertFalse(report["gates"]["generation_initialized"])

    def test_legacy_positions_or_orders_block_initialization(self):
        for reader in (
            FakeReader(positions=[{"symbol": "LEGACY", "qty": "1"}]),
            FakeReader(orders=[{"id": "legacy-order"}]),
            FakeReader(account={"status": "ACTIVE", "trading_blocked": True}),
        ):
            report = check_launch_readiness(reader)
            self.assertFalse(report["safe_to_initialize"])
            self.assertFalse(report["execution_ready"])

    def test_initialized_flat_ledger_is_ready_for_baseline_then_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            initialize_generation(path, WHEN)
            ledger = Ledger(path)
            try:
                before = check_launch_readiness(FakeReader(), ledger)
                self.assertTrue(before["safe_to_record_baseline"])
                self.assertFalse(before["execution_ready"])
                self.assertFalse(before["gates"]["launch_baseline_recorded"])

                ledger.record_launch_baseline(1, WHEN, "ACTIVE", 0, 0)
                after = check_launch_readiness(FakeReader(), ledger)
                self.assertTrue(after["execution_ready"])
                self.assertTrue(all(after["gates"].values()))
            finally:
                ledger.close()

    def test_readonly_ledger_cannot_be_mutated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            initialize_generation(path, WHEN)
            ledger = Ledger(path, readonly=True)
            try:
                with self.assertRaises(Exception):
                    ledger.add_bot("intruder", 1_000_000)
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
