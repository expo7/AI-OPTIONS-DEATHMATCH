import tempfile
import unittest
from pathlib import Path

from ledger import Ledger, LedgerError


SYMBOL = "SPY261218C00600000"
WHEN = "2026-09-21T14:35:00Z"


class SharedAccountLedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.tmp.name) / "ledger.sqlite3")
        self.ledger.initialize()
        self.ledger.add_bot("alpha", 2_500_000)
        self.ledger.add_bot("beta", 2_500_000)

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def buy(self, bot, client_id, broker_id, fill_id, price=200):
        self.assertTrue(self.ledger.reserve_order(client_id, bot, SYMBOL, "buy", 1, 250))
        self.ledger.accept_order(client_id, broker_id)
        self.assertTrue(self.ledger.record_fill(fill_id, client_id, 1, price, WHEN))

    def test_two_bots_same_contract_one_exits(self):
        self.buy("alpha", "alpha-buy", "broker-1", "fill-1")
        self.buy("beta", "beta-buy", "broker-2", "fill-2", 210)
        self.assertEqual(self.ledger.reconcile({SYMBOL: 2}), {})
        self.assertTrue(self.ledger.reserve_order("alpha-sell", "alpha", SYMBOL, "sell", 1, 150))
        self.ledger.accept_order("alpha-sell", "broker-3")
        self.ledger.record_fill("fill-3", "alpha-sell", 1, 230, WHEN)
        self.assertEqual(self.ledger.position("alpha", SYMBOL), 0)
        self.assertEqual(self.ledger.position("beta", SYMBOL), 1)
        self.assertEqual(self.ledger.cash_cents("alpha"), 2_503_000)
        self.assertEqual(self.ledger.cash_cents("beta"), 2_479_000)
        self.assertEqual(self.ledger.reconcile({SYMBOL: 1}), {})
        self.assertEqual(self.ledger.reconcile({}), {SYMBOL: {"bots": 1, "broker": 0}})

    def test_partial_fill_idempotency_and_conflict(self):
        self.ledger.reserve_order("a", "alpha", SYMBOL, "buy", 2, 300)
        self.assertFalse(self.ledger.reserve_order("a", "alpha", SYMBOL, "buy", 2, 300))
        with self.assertRaises(LedgerError):
            self.ledger.reserve_order("b", "beta", SYMBOL, "buy", 1, 300)
        self.ledger.accept_order("a", "broker-a")
        self.ledger.record_fill("fill-a", "a", 1, 280, WHEN)
        self.assertFalse(self.ledger.record_fill("fill-a", "a", 1, 280, WHEN))
        with self.assertRaises(LedgerError):
            self.ledger.record_fill("fill-a", "a", 1, 281, WHEN)
        with self.assertRaises(LedgerError):
            self.ledger.reserve_order("b", "beta", SYMBOL, "buy", 1, 300)
        self.ledger.close_order("a", "canceled")
        self.assertEqual(self.ledger.position("alpha", SYMBOL), 1)
        self.assertTrue(self.ledger.reserve_order("b", "beta", SYMBOL, "buy", 1, 300))

    def test_bot_cannot_sell_others_holding_or_spend_others_cash(self):
        self.buy("alpha", "a", "broker-a", "fill-a")
        with self.assertRaises(LedgerError):
            self.ledger.reserve_order("b", "beta", SYMBOL, "sell", 1, 150)
        with self.assertRaises(LedgerError):
            self.ledger.reserve_order("c", "beta", SYMBOL, "buy", 200, 300)
        self.assertEqual(self.ledger.reconcile({SYMBOL: 1, "OTHER": 1})["OTHER"], {"bots": 0, "broker": 1})

    def test_unexpected_broker_fill_is_preserved_for_review(self):
        self.ledger.reserve_order("a", "alpha", SYMBOL, "buy", 1, 24_000)
        self.ledger.accept_order("a", "broker-a")
        self.ledger.record_fill("fill-a", "a", 1, 26_000, WHEN)
        self.assertEqual(self.ledger.cash_cents("alpha"), -100_000)
        self.assertEqual(self.ledger.negative_cash_bots(), {"alpha": -100_000})
        self.assertEqual(self.ledger.reconcile({SYMBOL: 1}), {})

    def test_equity_snapshots_are_immutable_and_idempotent(self):
        self.assertTrue(self.ledger.record_equity_snapshot("alpha", 2_500_000, WHEN))
        self.assertFalse(self.ledger.record_equity_snapshot("alpha", 2_500_000, WHEN))
        with self.assertRaises(LedgerError):
            self.ledger.record_equity_snapshot("alpha", 2_400_000, WHEN)
        with self.assertRaises(LedgerError):
            self.ledger.record_equity_snapshot("alpha", -1, "later")

    def test_frozen_opportunity_and_bot_decisions(self):
        rules = {"strategy": "trend", "risk": {"max_contracts": 1}}
        market = {"underlying": "SPY", "price": 600.25, "contracts": [SYMBOL]}
        self.assertTrue(self.ledger.record_bot_version("alpha-g1", "alpha", 1, rules, WHEN))
        self.assertFalse(self.ledger.record_bot_version("alpha-g1", "alpha", 1, rules, WHEN))
        self.assertTrue(self.ledger.record_opportunity("opp-1", WHEN, WHEN, market))
        self.assertFalse(self.ledger.record_opportunity("opp-1", WHEN, WHEN, market))
        self.assertTrue(self.ledger.record_decision(
            "decision-1", "opp-1", "alpha", "alpha-g1", "buy",
            "Trend remained aligned and the contract passed liquidity limits.", WHEN,
            option_symbol=SYMBOL, quantity=1, limit_cents=250,
        ))
        self.assertFalse(self.ledger.record_decision(
            "decision-1", "opp-1", "alpha", "alpha-g1", "buy",
            "Trend remained aligned and the contract passed liquidity limits.", WHEN,
            option_symbol=SYMBOL, quantity=1, limit_cents=250,
        ))
        with self.assertRaises(LedgerError):
            self.ledger.record_decision(
                "decision-2", "opp-1", "beta", "alpha-g1", "decline", "No setup.", WHEN,
            )
        with self.assertRaises(LedgerError):
            self.ledger.record_decision(
                "decision-3", "opp-1", "beta", "missing", "decline", "No setup.", WHEN,
            )

    def test_decisions_and_inputs_cannot_be_rewritten_or_deleted(self):
        self.ledger.record_bot_version("alpha-g1", "alpha", 1, {"strategy": "trend"}, WHEN)
        self.ledger.record_opportunity("opp-1", WHEN, WHEN, {"underlying": "SPY"})
        self.ledger.record_decision(
            "decision-1", "opp-1", "alpha", "alpha-g1", "decline", "No qualified contract.", WHEN,
        )
        for statement in (
            "UPDATE bot_versions SET generation=2 WHERE id='alpha-g1'",
            "DELETE FROM opportunity_snapshots WHERE id='opp-1'",
            "UPDATE decisions SET public_rationale='changed' WHERE id='decision-1'",
        ):
            with self.assertRaises(Exception):
                self.ledger.db.execute(statement)

    def test_decision_validation_rejects_hidden_or_malformed_orders(self):
        self.ledger.record_bot_version("alpha-g1", "alpha", 1, {"strategy": "trend"}, WHEN)
        self.ledger.record_opportunity("opp-1", WHEN, WHEN, {"underlying": "SPY"})
        with self.assertRaises(LedgerError):
            self.ledger.record_decision(
                "bad-1", "opp-1", "alpha", "alpha-g1", "decline", "No trade.", WHEN,
                option_symbol=SYMBOL,
            )
        with self.assertRaises(LedgerError):
            self.ledger.record_decision(
                "bad-2", "opp-1", "alpha", "alpha-g1", "buy", "Trade.", WHEN,
                option_symbol=SYMBOL, quantity=0, limit_cents=250,
            )


if __name__ == "__main__":
    unittest.main()
