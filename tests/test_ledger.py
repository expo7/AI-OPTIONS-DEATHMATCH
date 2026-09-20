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


if __name__ == "__main__":
    unittest.main()
