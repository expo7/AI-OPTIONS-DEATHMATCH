import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from autonomous_entries import build_plan, run_entries, _opportunity_id
from bots import BOTS
from generation_one import BOT_RULES, frozen_rules
from ledger import Ledger

WHEN = "2026-09-21T16:45:30Z"
NOW = datetime(2026, 9, 21, 16, 30, tzinfo=timezone.utc)


def bars(closes):
    return [{"o": c, "h": c, "l": c, "c": c, "v": 1000} for c in closes]


def call_contract(symbol="SPY261101C00500000", strike=50000):
    return {"symbol": symbol, "option_type": "call", "strike_cents": strike,
            "expiration": "2026-11-01", "bid_cents": 100, "ask_cents": 110,
            "open_interest": 1000, "volume": 500}


class FakeMarketReader:
    """Uptrend bars + one liquid call for every underlying, so every
    directional bot proposes the same buy and the rotation tie-break is
    exercised deterministically."""

    def daily_bars(self, underlying, limit=30):
        return bars([100] * 15 + [101, 102, 103, 110, 112])

    def latest_trade_price_cents(self, underlying):
        return 50000

    def option_chain(self, underlying, expiration_gte, expiration_lte, max_pages=20, page_size=100):
        return [call_contract(f"{underlying}261101C00500000")]


class FlatMarketReader(FakeMarketReader):
    def daily_bars(self, underlying, limit=30):
        return bars([100] * 25)


class PartialOutageReader(FakeMarketReader):
    def option_chain(self, underlying, *args, **kwargs):
        if underlying == "SPY":
            raise OSError("provider unavailable")
        return super().option_chain(underlying, *args, **kwargs)


class BuildPlanTest(unittest.TestCase):
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

    def test_at_most_one_buy_survives_rotation(self):
        plan = build_plan(self.db, FakeMarketReader(), NOW)
        buys = [d for d in plan["decisions"] if d["action"] == "buy"]
        self.assertEqual(len(buys), 1)
        cash_decision = next(d for d in plan["decisions"] if d["bot_id"] == "cash")
        self.assertEqual(cash_decision["action"], "decline")

    def test_downgraded_buyers_get_honest_rationale(self):
        plan = build_plan(self.db, FakeMarketReader(), NOW)
        downgraded = [d for d in plan["decisions"]
                      if d["action"] == "decline" and d["bot_id"] in ("trend", "reversal", "breakout")]
        self.assertTrue(any("selected for this cycle" in d["public_rationale"] for d in downgraded))

    def test_flat_market_produces_all_declines(self):
        plan = build_plan(self.db, FlatMarketReader(), NOW)
        self.assertTrue(all(d["action"] == "decline" for d in plan["decisions"]))

    def test_one_ticker_outage_does_not_crash_other_candidates(self):
        plan = build_plan(self.db, PartialOutageReader(), NOW)
        self.assertTrue(plan["market"]["contracts"])
        self.assertTrue(all(c["underlying"] != "SPY" for c in plan["market"]["contracts"] if "underlying" in c))

    def test_position_limit_forces_decline(self):
        with patch("autonomous_entries._open_position_count", return_value=3):
            plan = build_plan(self.db, FakeMarketReader(), NOW)
        self.assertTrue(all(d["action"] == "decline" for d in plan["decisions"]))
        trend_decision = next(d for d in plan["decisions"] if d["bot_id"] == "trend")
        self.assertIn("Position limit", trend_decision["public_rationale"])


class RunEntriesIdempotencyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger_path = Path(self.tmp.name) / "ledger.sqlite3"
        db = Ledger(self.ledger_path)
        db.initialize()
        for bot in BOTS:
            db.add_bot(bot.slug, 1_000_000)
            db.record_bot_version(BOT_RULES[bot.slug]["version_id"], bot.slug, 1,
                                  frozen_rules(bot.slug), WHEN)
        db.record_launch_baseline(1, WHEN, "ACTIVE", 0, 0)
        db.close()

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, market_reader=FakeMarketReader):
        lock = Path(self.tmp.name) / "lock" / "entries.lock"
        with patch("autonomous_entries.load_credentials", return_value={
            "APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret",
        }), patch("autonomous_entries.PaperReader") as reader_cls, \
                patch("autonomous_entries.MarketDataReader", return_value=market_reader()), \
                patch("autonomous_entries.submit", return_value={"client_order_id": "x", "accepted": True}), \
                patch("autonomous_entries.datetime") as datetime_cls:
            reader_cls.return_value.clock.return_value = {"is_open": True}
            datetime_cls.now.return_value = NOW
            return run_entries(str(self.ledger_path), "unused", str(lock))

    def test_market_closed_skips(self):
        lock = Path(self.tmp.name) / "lock" / "entries.lock"
        with patch("autonomous_entries.load_credentials", return_value={
            "APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret",
        }), patch("autonomous_entries.PaperReader") as reader_cls:
            reader_cls.return_value.clock.return_value = {"is_open": False}
            result = run_entries(str(self.ledger_path), "unused", str(lock))
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "market is closed")

    def test_completes_and_second_run_in_same_window_is_skipped(self):
        first = self._run()
        self.assertEqual(first["status"], "completed")
        buys = [d for d in first["decisions"] if d["action"] == "buy"]
        self.assertEqual(len(buys), 1)

        second = self._run()
        self.assertEqual(second["status"], "skipped")
        self.assertEqual(second["reason"], "already decided this cadence window")

    def test_opportunity_id_is_floored_to_cadence_bucket(self):
        early = datetime(2026, 9, 21, 16, 31, tzinfo=timezone.utc)
        late = datetime(2026, 9, 21, 16, 59, tzinfo=timezone.utc)
        self.assertEqual(_opportunity_id(early), _opportunity_id(late))

        next_window = datetime(2026, 9, 21, 17, 0, tzinfo=timezone.utc)
        self.assertNotEqual(_opportunity_id(late), _opportunity_id(next_window))


if __name__ == "__main__":
    unittest.main()
