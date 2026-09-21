import tempfile
import unittest
from pathlib import Path

from ledger import Ledger
from public_data import load_public_standings, write_public_results


class PublicStandingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.sqlite3"
        self.ledger = Ledger(self.path)
        self.ledger.initialize()
        self.ledger.add_bot("trend", 1_000_000)

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_missing_or_unmarked_ledger_publishes_nothing(self):
        self.assertEqual(load_public_standings(Path(self.tmp.name) / "missing.sqlite3"), {})
        self.assertEqual(load_public_standings(self.path), {})

    def test_latest_equity_return_and_drawdown(self):
        self.ledger.record_bot_version("trend-g1", "trend", 1, {"strategy": "trend"}, "2026-09-21T14:00:00Z")
        self.ledger.record_opportunity("opp-1", "2026-09-21T14:15:00Z", "2026-09-21T14:15:00Z", {"symbol": "SPY"})
        self.ledger.record_decision(
            "decision-1", "opp-1", "trend", "trend-g1", "decline",
            "No contract passed the liquidity filter.", "2026-09-21T14:20:00Z",
        )
        self.ledger.record_equity_snapshot("trend", 1_100_000, "2026-09-21T14:30:00Z")
        self.ledger.record_equity_snapshot("trend", 880_000, "2026-09-21T15:30:00Z")
        self.ledger.record_equity_snapshot("trend", 990_000, "2026-09-21T16:30:00Z")
        result = load_public_standings(self.path)["trend"]
        self.assertEqual(result["equity_cents"], 990_000)
        self.assertAlmostEqual(result["return_fraction"], -0.01)
        self.assertAlmostEqual(result["max_drawdown_fraction"], 0.20)
        self.assertEqual(result["closed_trades"], 0)
        self.assertEqual(result["as_of"], "2026-09-21T16:30:00Z")
        self.assertEqual(result["recent_decisions"][0]["action"], "decline")
        self.assertEqual(result["recent_decisions"][0]["public_rationale"], "No contract passed the liquidity filter.")

    def test_sanitized_json_export_round_trip(self):
        self.ledger.record_equity_snapshot("trend", 1_025_000, "2026-09-21T17:00:00Z")
        target = Path(self.tmp.name) / "public" / "results.json"
        positions = {"trend": [{"symbol": "QQQ261009C00745000", "quantity": 1}]}
        self.assertEqual(write_public_results(self.ledger, target, "2026-09-21T17:00:00Z", positions), 1)
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)
        result = load_public_standings(target)
        self.assertEqual(result["trend"]["equity_cents"], 1_025_000)
        self.assertEqual(result["trend"]["open_positions"][0]["quantity"], 1)
        self.assertNotIn("orders", target.read_text())


if __name__ == "__main__":
    unittest.main()
