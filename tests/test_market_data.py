import json
import unittest
from io import BytesIO

from ledger import LedgerError
from market_data import MarketDataReader, parse_occ_symbol


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return BytesIO(json.dumps(self._payload).encode())

    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, pages):
        self.pages = list(pages)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        return FakeResponse(self.pages.pop(0))


CREDS = {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"}


class MarketDataReaderTest(unittest.TestCase):
    def test_requires_credentials(self):
        with self.assertRaises(LedgerError):
            MarketDataReader({})

    def test_daily_bars_parses_and_fails_closed_on_malformed_bar(self):
        good = MarketDataReader(CREDS, opener=FakeOpener([{"bars": [
            {"t": "2026-01-01", "o": "1.00", "h": "1.10", "l": "0.90", "c": "1.05", "v": 100},
        ]}]))
        bars = good.daily_bars("SPY", limit=1)
        self.assertEqual(bars[0]["c"], 105)

        bad = MarketDataReader(CREDS, opener=FakeOpener([{"bars": [{"t": "x"}]}]))
        with self.assertRaises(LedgerError):
            bad.daily_bars("SPY")

        empty = MarketDataReader(CREDS, opener=FakeOpener([{"bars": []}]))
        with self.assertRaises(LedgerError):
            empty.daily_bars("SPY")

    def test_daily_bars_rejects_bad_limit(self):
        reader = MarketDataReader(CREDS, opener=FakeOpener([{}]))
        with self.assertRaises(LedgerError):
            reader.daily_bars("SPY", limit=0)

    def test_latest_trade_price_cents(self):
        reader = MarketDataReader(CREDS, opener=FakeOpener([{"trade": {"p": "123.45"}}]))
        self.assertEqual(reader.latest_trade_price_cents("SPY"), 12345)

        missing = MarketDataReader(CREDS, opener=FakeOpener([{"trade": {}}]))
        with self.assertRaises(LedgerError):
            missing.latest_trade_price_cents("SPY")

    def test_option_chain_excludes_incomplete_contracts_without_fabricating(self):
        snapshots = {
            "SPY261009C00500000": {
                "latestQuote": {"bp": "1.00", "ap": "1.20"},
                "dailyBar": {"v": 500},
                "openInterest": 1000,
            },
            "SPY261009P00500000": {
                "latestQuote": {"bp": "1.00", "ap": "1.20"},
                "dailyBar": {"v": 500},
                # openInterest missing entirely -- must be excluded, not defaulted.
            },
        }
        reader = MarketDataReader(CREDS, opener=FakeOpener([
            {"snapshots": snapshots, "next_page_token": None},
        ]))
        contracts = reader.option_chain("SPY", "2026-10-01", "2026-11-01")
        self.assertEqual(len(contracts), 1)
        self.assertEqual(contracts[0]["symbol"], "SPY261009C00500000")
        self.assertEqual(contracts[0]["option_type"], "call")

    def test_option_chain_pagination_bound_and_repeat_token_detection(self):
        page = {"snapshots": {}, "next_page_token": "same"}
        reader = MarketDataReader(CREDS, opener=FakeOpener([page, page]))
        with self.assertRaises(LedgerError):
            reader.option_chain("SPY", "2026-10-01", "2026-11-01", max_pages=5)

    def test_option_chain_rejects_bad_page_bound(self):
        reader = MarketDataReader(CREDS, opener=FakeOpener([{}]))
        with self.assertRaises(LedgerError):
            reader.option_chain("SPY", "2026-10-01", "2026-11-01", max_pages=0)

    def test_get_rejects_paths_outside_allowed_prefixes(self):
        reader = MarketDataReader(CREDS, opener=FakeOpener([{}]))
        with self.assertRaises(LedgerError):
            reader._get("/v1/account")


class ParseOccSymbolTest(unittest.TestCase):
    def test_parses_call_and_put(self):
        underlying, expiration, option_type, strike_cents = parse_occ_symbol("SPY261009C00500000")
        self.assertEqual((underlying, expiration.isoformat(), option_type, strike_cents),
                         ("SPY", "2026-10-09", "call", 50000))

    def test_rejects_malformed_symbol(self):
        with self.assertRaises(LedgerError):
            parse_occ_symbol("short")


if __name__ == "__main__":
    unittest.main()
