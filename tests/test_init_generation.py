import tempfile
import unittest
from pathlib import Path

from bots import BOTS, STARTING_CASH_CENTS
from generation_one import BOT_RULES
from init_generation import initialize_generation
from ledger import Ledger


class InitializeGenerationTest(unittest.TestCase):
    def test_initialization_is_complete_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            self.assertEqual(initialize_generation(path, "2026-09-21T17:00:00Z"), 5)
            self.assertEqual(initialize_generation(path, "2026-09-21T17:00:00Z"), 5)
            ledger = Ledger(path)
            try:
                bots = ledger.db.execute("SELECT id,starting_cash_cents FROM bots ORDER BY id").fetchall()
                versions = ledger.db.execute("SELECT id,bot_id,generation FROM bot_versions ORDER BY bot_id").fetchall()
                self.assertEqual({row["id"] for row in bots}, {bot.slug for bot in BOTS})
                self.assertTrue(all(row["starting_cash_cents"] == STARTING_CASH_CENTS for row in bots))
                self.assertEqual({row["id"] for row in versions}, {value["version_id"] for value in BOT_RULES.values()})
                self.assertTrue(all(row["generation"] == 1 for row in versions))
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
