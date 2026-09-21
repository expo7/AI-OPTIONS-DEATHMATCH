import tempfile
import unittest
from pathlib import Path

from bots import BOTS
from competition_operator import stage_plan
from generation_one import BOT_RULES, frozen_rules
from ledger import Ledger, LedgerError


WHEN = "2026-09-21T16:45:30Z"


class CompetitionOperatorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Ledger(Path(self.tmp.name) / "ledger.sqlite3")
        self.db.initialize()
        for bot in BOTS:
            self.db.add_bot(bot.slug, 1_000_000)
            self.db.record_bot_version(BOT_RULES[bot.slug]["version_id"], bot.slug, 1,
                                       frozen_rules(bot.slug), WHEN)
        self.db.record_launch_baseline(1, WHEN, "ACTIVE", 0, 0)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def plan(self):
        decisions = [{"bot_id": bot.slug, "action": "decline",
                      "public_rationale": "The setup did not match this strategy's entry rules."}
                     for bot in BOTS]
        decisions[0] = {"bot_id": "trend", "action": "buy",
                        "option_symbol": "QQQ261009C00745000", "quantity": 1,
                        "limit_cents": 890,
                        "public_rationale": "QQQ sustained a liquid upside breakout with aligned momentum."}
        return {
            "generation": 1, "opportunity_id": "opp-20260921-164530",
            "captured_at": WHEN, "data_cutoff_at": WHEN,
            "market": {"underlying": "QQQ", "contracts": [{
                "symbol": "QQQ261009C00745000", "expiration": "2026-10-09",
                "bid_cents": 874, "ask_cents": 890, "open_interest": 1292, "volume": 1033,
            }]}, "decisions": decisions,
        }

    def test_stages_exactly_attributed_launch_order(self):
        result = stage_plan(self.db, self.plan())
        self.assertEqual(result["buy_count"], 1)
        order = self.db.db.execute("SELECT * FROM orders").fetchone()
        self.assertEqual((order["bot_id"], order["symbol"], order["limit_cents"]),
                         ("trend", "QQQ261009C00745000", 890))
        self.assertEqual(self.db.db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0], 5)

    def test_rejects_liquidity_risk_and_multiple_buys(self):
        for key, value in (("open_interest", 499), ("volume", 99), ("ask_cents", 1001)):
            plan = self.plan()
            plan["market"]["contracts"][0][key] = value
            with self.assertRaises(LedgerError):
                stage_plan(self.db, plan)
        plan = self.plan()
        plan["decisions"][1] = {**plan["decisions"][0], "bot_id": "reversal"}
        with self.assertRaises(LedgerError):
            stage_plan(self.db, plan)


if __name__ == "__main__":
    unittest.main()
