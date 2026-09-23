"""Read-only production proof of paper access and an OCC-matched liquid contract."""

import json
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
    now = datetime.now(timezone.utc)
    start = now.date() + timedelta(days=COMMON_RULES["days_to_expiry"]["minimum"])
    end = now.date() + timedelta(days=COMMON_RULES["days_to_expiry"]["maximum"])
    # Probe an actual monthly or weekly expiration, keeping each Alpaca chain bounded.
    for days in range((end - start).days + 1):
        expiry = start + timedelta(days=days)
        if expiry.weekday() != 4:
            continue
        contracts = reader.option_chain("SPY", expiry.isoformat(), expiry.isoformat())
        for contract in contracts:
            try:
                _validate_contract(contract, now)
            except LedgerError:
                continue
            return {key: contract[key] for key in (
                "symbol", "bid_cents", "ask_cents", "open_interest", "volume",
                "quote_source", "open_interest_source", "volume_source", "liquidity_observed_at")}
    raise LedgerError("no combined SPY contract passed liquidity validation")


if __name__ == "__main__":
    print(json.dumps(check(), sort_keys=True))
