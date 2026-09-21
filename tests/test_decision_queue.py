import tempfile
import unittest
from pathlib import Path

from bots import BOTS
from decision_queue import assemble_plan, enqueue, queue_status, record_queued_decision
from generation_one import BOT_RULES, frozen_rules
from ledger import Ledger, LedgerError


WHEN = "2026-09-21T18:00:00Z"


class DecisionQueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.tmp.name) / "ledger.sqlite3")
        self.ledger.initialize()
        for bot in BOTS:
            self.ledger.add_bot(bot.slug, 1_000_000)
            self.ledger.record_bot_version(BOT_RULES[bot.slug]["version_id"], bot.slug, 1,
                                           frozen_rules(bot.slug), WHEN)
        self.snapshot = {
            "generation": 1, "opportunity_id": "opp-20260921-180000",
            "captured_at": WHEN, "data_cutoff_at": WHEN,
            "market": {"underlying": "SPY", "contracts": [{
                "symbol": "SPY261009C00670000", "expiration": "2026-10-09",
                "bid_cents": 700, "ask_cents": 720, "open_interest": 900, "volume": 400,
            }]},
        }

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_queue_tracks_pending_decisions_and_assembles(self):
        result = enqueue(self.ledger, self.snapshot)
        self.assertTrue(result["created"])
        self.assertEqual(len(queue_status(self.ledger, self.snapshot["opportunity_id"])["pending"]), 5)
        for bot in BOTS:
            decision = {"bot_id": bot.slug, "action": "decline",
                        "public_rationale": "No qualifying setup for this strategy."}
            record_queued_decision(self.ledger, self.snapshot["opportunity_id"], decision)
        status = queue_status(self.ledger, self.snapshot["opportunity_id"])
        self.assertTrue(status["ready"])
        self.assertEqual(len(assemble_plan(self.ledger, self.snapshot["opportunity_id"])["decisions"]), 5)

    def test_buy_must_match_snapshotted_contract_and_single_buy_limit(self):
        enqueue(self.ledger, self.snapshot)
        buy = {"bot_id": "trend", "action": "buy", "option_symbol": "SPY261009C00670000",
               "quantity": 1, "limit_cents": 720, "public_rationale": "Trend setup qualifies."}
        record_queued_decision(self.ledger, self.snapshot["opportunity_id"], buy)
        with self.assertRaises(LedgerError):
            record_queued_decision(self.ledger, self.snapshot["opportunity_id"], {**buy, "bot_id": "reversal"})
        with self.assertRaises(LedgerError):
            record_queued_decision(self.ledger, self.snapshot["opportunity_id"], {
                **buy, "bot_id": "breakout", "limit_cents": 719,
            })

    def test_incomplete_queue_cannot_assemble_or_stage(self):
        enqueue(self.ledger, self.snapshot)
        with self.assertRaises(LedgerError):
            assemble_plan(self.ledger, self.snapshot["opportunity_id"])


if __name__ == "__main__":
    unittest.main()
