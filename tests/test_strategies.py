import unittest

from strategies import STRATEGIES, select_contract


def bars_from_closes(closes, high_pad=0, low_pad=0):
    return [{"o": c, "h": c + high_pad, "l": c - low_pad, "c": c, "v": 1000} for c in closes]


def contract(symbol, option_type, strike_cents, bid=100, ask=110, oi=1000, volume=500):
    return {"symbol": symbol, "option_type": option_type, "strike_cents": strike_cents,
            "expiration": "2026-11-01", "bid_cents": bid, "ask_cents": ask,
            "open_interest": oi, "volume": volume}


CONTRACTS = [
    contract("SPY261101C00500000", "call", 50000),
    contract("SPY261101P00500000", "put", 50000),
]


class SelectContractTest(unittest.TestCase):
    def test_returns_closest_strike_for_side(self):
        contracts = CONTRACTS + [contract("SPY261101C00600000", "call", 60000)]
        chosen = select_contract(contracts, "call", 50100)
        self.assertEqual(chosen["symbol"], "SPY261101C00500000")

    def test_returns_none_when_no_contract_of_that_type(self):
        self.assertIsNone(select_contract([CONTRACTS[0]], "put", 50000))


class TrendStrategyTest(unittest.TestCase):
    def test_buys_call_on_confirmed_uptrend(self):
        closes = [100] * 15 + [101, 102, 103, 110, 112]
        result = STRATEGIES["trend"]("SPY", bars_from_closes(closes), CONTRACTS, 50000)
        self.assertEqual(result["action"], "buy")
        self.assertEqual(result["option_symbol"], "SPY261101C00500000")

    def test_declines_without_enough_history(self):
        result = STRATEGIES["trend"]("SPY", bars_from_closes([100, 101]), CONTRACTS, 50000)
        self.assertEqual(result["action"], "decline")
        self.assertIsNone(result["option_symbol"])

    def test_declines_on_flat_market(self):
        closes = [100] * 25
        result = STRATEGIES["trend"]("SPY", bars_from_closes(closes), CONTRACTS, 50000)
        self.assertEqual(result["action"], "decline")

    def test_declines_when_no_tradable_contract(self):
        closes = [100] * 15 + [101, 102, 103, 110, 112]
        result = STRATEGIES["trend"]("SPY", bars_from_closes(closes), [CONTRACTS[1]], 50000)
        self.assertEqual(result["action"], "decline")


class ReversalStrategyTest(unittest.TestCase):
    def test_fades_extended_up_move_with_a_put(self):
        closes = [100, 100, 100, 106]
        result = STRATEGIES["reversal"]("SPY", bars_from_closes(closes), CONTRACTS, 50000)
        self.assertEqual(result["action"], "buy")
        self.assertEqual(result["option_symbol"], "SPY261101P00500000")

    def test_declines_on_modest_move(self):
        closes = [100, 100, 100, 101]
        result = STRATEGIES["reversal"]("SPY", bars_from_closes(closes), CONTRACTS, 50000)
        self.assertEqual(result["action"], "decline")


class BreakoutStrategyTest(unittest.TestCase):
    def test_buys_call_on_range_breakout(self):
        prior = [100] * 10
        bars = bars_from_closes(prior, high_pad=1, low_pad=1) + bars_from_closes([105])
        result = STRATEGIES["breakout"]("SPY", bars, CONTRACTS, 50000)
        self.assertEqual(result["action"], "buy")
        self.assertEqual(result["option_symbol"], "SPY261101C00500000")

    def test_declines_inside_range(self):
        prior = [100] * 10
        bars = bars_from_closes(prior, high_pad=5, low_pad=5) + bars_from_closes([100])
        result = STRATEGIES["breakout"]("SPY", bars, CONTRACTS, 50000)
        self.assertEqual(result["action"], "decline")


class AlwaysDeclineStrategyTest(unittest.TestCase):
    def test_catalyst_always_declines(self):
        result = STRATEGIES["catalyst"]("SPY", bars_from_closes([100] * 30), CONTRACTS, 50000)
        self.assertEqual(result["action"], "decline")

    def test_cash_always_declines(self):
        result = STRATEGIES["cash"]("SPY", bars_from_closes([100] * 30), CONTRACTS, 50000)
        self.assertEqual(result["action"], "decline")


if __name__ == "__main__":
    unittest.main()
