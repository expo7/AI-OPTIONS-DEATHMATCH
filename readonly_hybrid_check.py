"""Read-only production proof of paper access and an OCC-matched liquid contract."""

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from alpaca_readonly import PaperReader, load_credentials
from competition_operator import _validate_contract
from generation_one import COMMON_RULES
from ledger import LedgerError
from market_data import MarketDataReader


def check(env_file="/etc/ai-options-deathmatch/alpaca.env"):
    credentials = load_credentials(env_file)
    account = PaperReader(credentials).account()
    if account.get("status") != "ACTIVE" or int(account.get("options_trading_level") or 0) < 1:
        raise LedgerError("paper account is not active for options")
    reader = MarketDataReader(credentials)
    summary = []
    now = datetime.now(timezone.utc)
    start = now.date() + timedelta(days=COMMON_RULES["days_to_expiry"]["minimum"])
    end = now.date() + timedelta(days=COMMON_RULES["days_to_expiry"]["maximum"])
    # Probe every Generation 1 underlying, one expiration at a time.
    for underlying in ("SPY", "QQQ", "AAPL", "MSFT", "NVDA"):
        for days in range((end - start).days + 1):
            expiry = start + timedelta(days=days)
            if expiry.weekday() != 4:
                continue
            contracts = reader.option_chain(underlying, expiry.isoformat(), expiry.isoformat())
            reasons = Counter()
            for contract in contracts:
                try:
                    _validate_contract(contract, now)
                except LedgerError as error:
                    reasons[str(error)] += 1
                    continue
                return {key: contract[key] for key in (
                    "symbol", "bid_cents", "ask_cents", "open_interest", "volume",
                    "quote_source", "open_interest_source", "volume_source", "liquidity_observed_at")}
            summary.append({"underlying": underlying, "expiration": expiry.isoformat(),
                            **reader.last_diagnostics, "max_open_interest": max(
                                (c["open_interest"] for c in contracts), default=None),
                            "max_volume": max((c["volume"] for c in contracts), default=None),
                            "rejections": dict(reasons)})
    print(json.dumps({"paper_account": "ACTIVE", "diagnostics": summary}, sort_keys=True))
    raise LedgerError("no combined contract passed liquidity validation")


if __name__ == "__main__":
    print(json.dumps(check(), sort_keys=True))
