import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bots import BOTS
from competition_operator import auto_manage_exits, mark, open_lot_cost_cents, option_expiration, stage_plan
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

    def test_common_mark_records_and_publishes_every_contender(self):
        plan = self.plan()
        stage_plan(self.db, plan)
        self.db.accept_order("dm-g1-trend-1-164530", "broker-1")
        self.db.record_fill("fill-1", "dm-g1-trend-1-164530", 1, 880, WHEN)

        class Reader:
            def account(self):
                return {"status": "ACTIVE", "trading_blocked": False}
            def open_orders(self):
                return []
            def positions(self):
                return [{"symbol": "QQQ261009C00745000", "qty": "1", "current_price": "9.00"}]

        from unittest.mock import patch
        target = Path(self.tmp.name) / "public" / "results.json"
        with patch("competition_operator.load_credentials", return_value={
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret",
        }), patch("competition_operator.PaperReader", return_value=Reader()):
            result = mark(self.db, "unused", target, "2026-09-21T17:00:00Z")
        self.assertEqual(result["published"], 5)
        self.assertEqual(result["open_positions"], 1)
        self.assertEqual(result["expiry_exits_due"], 0)
        self.assertEqual(self.db.db.execute("SELECT COUNT(*) FROM equity_snapshots").fetchone()[0], 5)
        self.assertIn('"trend"', target.read_text())

    def test_fifo_cost_and_occ_expiration(self):
        plan = self.plan()
        stage_plan(self.db, plan)
        order = "dm-g1-trend-1-164530"
        self.db.accept_order(order, "broker-1")
        self.db.record_fill("fill-1", order, 1, 880, WHEN)
        self.assertEqual(open_lot_cost_cents(self.db, "trend", "QQQ261009C00745000"), 88_000)
        self.assertEqual(option_expiration("QQQ261009C00745000").isoformat(), "2026-10-09")

    def test_auto_manage_exits_submits_due_position_and_skips_pending(self):
        plan = self.plan()
        stage_plan(self.db, plan)
        self.db.accept_order("dm-g1-trend-1-164530", "broker-1")
        self.db.record_fill("fill-1", "dm-g1-trend-1-164530", 1, 880, WHEN)

        positions = {
            "trend": [{
                "symbol": "QQQ261009C00745000", "quantity": 1, "mark_cents": 100,
                "exit_signals": ["risk_limit"], "exit_due": True, "exit_policy_id": "g1-lifecycle-v1",
            }],
            "reversal": [],
        }

        class Reader:
            def account(self):
                return {"status": "ACTIVE", "trading_blocked": False, "account_blocked": False,
                         "trade_suspended_by_user": False}

            def open_orders(self):
                return []

            def positions(self):
                return [{"symbol": "QQQ261009C00745000", "qty": "1"}]

        class Submitter:
            def __init__(self, credentials, token):
                pass

            def post_order(self, payload):
                return {"id": "broker-exit-1", "client_order_id": payload["client_order_id"],
                         "symbol": payload["symbol"], "side": "sell", "qty": payload["qty"],
                         "type": "limit", "limit_price": payload["limit_price"], "status": "accepted"}

        with patch("competition_operator.load_credentials", return_value={
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret",
        }), patch("competition_operator.PaperReader", return_value=Reader()), \
                patch("competition_operator.PaperSubmitter", Submitter):
            results = auto_manage_exits(self.db, "unused", positions)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "submitted")
        order = self.db.db.execute(
            "SELECT * FROM orders WHERE bot_id='trend' AND side='sell'"
        ).fetchone()
        self.assertEqual(order["status"], "accepted")

        # A second call must not duplicate the exit while it is unresolved.
        with patch("competition_operator.load_credentials", return_value={}), \
                patch("competition_operator.PaperReader", return_value=Reader()), \
                patch("competition_operator.PaperSubmitter", Submitter):
            again = auto_manage_exits(self.db, "unused", positions)
        self.assertEqual(again[0]["status"], "already_pending")


if __name__ == "__main__":
    unittest.main()
