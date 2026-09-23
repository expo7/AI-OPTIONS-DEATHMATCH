"""Generation 1 per-competitor entry strategies.

Each function below is independent, deterministic, and reasons only from the
shared market snapshot handed to every bot (daily bars and a normalized
option chain for one underlying). No function fabricates news, sentiment, or
any data source that is not actually wired into ``market_data.py``. A bot
that cannot find a genuine, rule-satisfying setup returns a decline with an
honest rationale rather than being forced to trade.

Strategy summary (kept faithful to ``generation_one.BOT_RULES`` text):
  * trend    - buys with a confirmed short/long moving-average trend.
  * reversal - buys the opposing side after an unusually extended short move.
  * breakout - buys after price closes outside a recent trading range.
  * catalyst - always declines: no dated public catalyst feed is wired into
               this system, and inventing one would violate the "no
               fabricated data" rule. This is an honest capability gap, not a
               bug.
  * cash     - always declines (benchmark).
"""

from generation_one import COMMON_RULES


def _closes(bars):
    return [bar["c"] for bar in bars]


def _sma(values, window):
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def select_contract(contracts, option_type, underlying_price_cents, common_rules=COMMON_RULES):
    """Return the contract closest to at-the-money for ``option_type``, or None.

    Only contracts already present in the normalized chain are considered;
    liquidity/expiry/spread/premium filtering happens later in
    ``competition_operator._validate_contract`` against the same
    ``common_rules``, so this only narrows by option type and moneyness to
    avoid re-implementing (and risking drift from) those existing gates.
    """
    candidates = [c for c in contracts if c.get("option_type") == option_type]
    if not candidates:
        return None
    candidates.sort(key=lambda c: abs(c["strike_cents"] - underlying_price_cents))
    return candidates[0]


def _decline(bot_id, rationale):
    return {"bot_id": bot_id, "action": "decline", "option_symbol": None,
            "quantity": None, "limit_cents": None, "public_rationale": rationale}


def _buy(bot_id, contract, rationale):
    return {"bot_id": bot_id, "action": "buy", "option_symbol": contract["symbol"],
            "quantity": 1, "limit_cents": contract["ask_cents"], "public_rationale": rationale}


def trend(underlying, bars, contracts, underlying_price_cents):
    closes = _closes(bars)
    short = _sma(closes, 5)
    long = _sma(closes, 20)
    if short is None or long is None:
        return _decline("trend", f"Insufficient {underlying} history for a confirmed trend read.")
    if short > long * 1.01:
        option_type = "call"
    elif short < long * 0.99:
        option_type = "put"
    else:
        return _decline("trend", f"{underlying} short/long averages are not separated enough to confirm a trend.")
    contract = select_contract(contracts, option_type, underlying_price_cents)
    if contract is None:
        return _decline("trend", f"No tradable {option_type} contract available for {underlying}.")
    return _buy("trend", contract,
                f"{underlying} 5-day average {'above' if option_type == 'call' else 'below'} "
                f"20-day average confirms a {option_type} trend continuation.")


def reversal(underlying, bars, contracts, underlying_price_cents):
    closes = _closes(bars)
    if len(closes) < 4:
        return _decline("reversal", f"Insufficient {underlying} history to measure an extended move.")
    move = (closes[-1] - closes[-4]) / closes[-4]
    if move >= 0.05:
        option_type = "put"
    elif move <= -0.05:
        option_type = "call"
    else:
        return _decline("reversal", f"{underlying}'s recent 3-day move is not extended enough to fade.")
    contract = select_contract(contracts, option_type, underlying_price_cents)
    if contract is None:
        return _decline("reversal", f"No tradable {option_type} contract available for {underlying}.")
    return _buy("reversal", contract,
                f"{underlying} moved {move:+.1%} over 3 days; fading the extension with a {option_type}.")


def breakout(underlying, bars, contracts, underlying_price_cents):
    if len(bars) < 11:
        return _decline("breakout", f"Insufficient {underlying} history to define a prior range.")
    prior = bars[-11:-1]
    high = max(bar["h"] for bar in prior)
    low = min(bar["l"] for bar in prior)
    last_close = bars[-1]["c"]
    if last_close > high:
        option_type = "call"
    elif last_close < low:
        option_type = "put"
    else:
        return _decline("breakout", f"{underlying} is still inside its prior 10-day range.")
    contract = select_contract(contracts, option_type, underlying_price_cents)
    if contract is None:
        return _decline("breakout", f"No tradable {option_type} contract available for {underlying}.")
    return _buy("breakout", contract,
                f"{underlying} closed outside its prior 10-day range, confirming a breakout {option_type}.")


def catalyst(underlying, bars, contracts, underlying_price_cents):
    return _decline("catalyst",
                     "No reliable dated public catalyst data source is wired into this system; "
                     "declining rather than fabricating a news signal.")


def cash(underlying, bars, contracts, underlying_price_cents):
    return _decline("cash", "Cash benchmark never enters a position.")


STRATEGIES = {
    "trend": trend,
    "reversal": reversal,
    "breakout": breakout,
    "catalyst": catalyst,
    "cash": cash,
}
