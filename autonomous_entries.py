"""Root-only, autonomous Generation 1 entry-decision generator.

This script is the missing half of the automation loop: ``scheduled_update.py``
already runs every five minutes to sync fills, mark equity, and auto-manage
exits. This script runs on its own, longer cadence (default 30 minutes) to
fetch a shared market snapshot, let every Generation 1 competitor
independently evaluate it, and stage (and, if a buy is chosen, submit) at
most one paper order per cycle through the existing, unchanged
``stage_plan``/``submit`` gates.

Cadence rationale: fetching daily bars and a full options chain for every
underlying in the universe is several GET requests per symbol, versus the
existing five-minute cycle's constant handful of trading-API reads. A
30-minute cadence keeps this well under Alpaca's market-data rate limits and
avoids an "order storm" while remaining decoupled from -- and much more
frequent than -- fully manual curation.

Idempotency: the opportunity ID is time-bucketed to the cadence window
(``opp-auto-g{GENERATION}-{YYYYMMDD-HHMM}`` floored to the interval). Before
fetching any market data, this script checks whether decisions already exist
for the current bucket and skips the entire cycle if so, so a duplicate timer
firing (or a restart) cannot re-fetch data or record a second, conflicting
opportunity snapshot under the same ID.

Fairness: if more than one bot proposes a genuine buy in the same cycle, the
existing ``validate_plan`` launch-cycle rule (at most one buy per plan) is
preserved by picking exactly one via a deterministic rotation over prior
auto-generated cycles, rather than by strategy quality or bot identity. Every
other bot that wanted to buy is downgraded to an honest decline that
distinguishes "another contender was selected this cycle" from a genuine
strategy abstention.
"""

import argparse
import fcntl
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import json

from alpaca_readonly import PaperReader, load_credentials
from alpaca_submit import EXECUTION_ENABLE_TOKEN, PaperSubmitter
from bots import BOTS
from competition_operator import stage_plan, submit
from generation_one import COMMON_RULES, GENERATION
from ledger import Ledger, LedgerError
from market_data import MarketDataReader
from strategies import STRATEGIES

CADENCE_MINUTES = 30
UNIVERSE = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA")


def _bucket(now):
    floored_minute = (now.minute // CADENCE_MINUTES) * CADENCE_MINUTES
    bucket = now.replace(minute=floored_minute, second=0, microsecond=0)
    return bucket.strftime("%Y%m%d-%H%M")


def _opportunity_id(now):
    return f"opp-auto-g{GENERATION}-{_bucket(now)}"


def _already_decided(ledger, opportunity_id):
    return ledger.db.execute(
        "SELECT 1 FROM opportunity_snapshots WHERE id=? LIMIT 1", (opportunity_id,)
    ).fetchone() is not None


def _open_position_count(ledger, bot_id):
    rows = ledger.db.execute(
        """SELECT o.symbol, SUM(CASE WHEN o.side='buy' THEN f.quantity ELSE -f.quantity END) AS net_quantity
           FROM fills f JOIN orders o ON o.client_order_id=f.client_order_id
           WHERE o.bot_id=? GROUP BY o.symbol HAVING net_quantity > 0""", (bot_id,),
    ).fetchall()
    return len(rows)


def _rotation_index(ledger):
    total = ledger.db.execute(
        "SELECT COUNT(*) FROM opportunity_snapshots WHERE id LIKE ?", (f"opp-auto-g{GENERATION}-%",)
    ).fetchone()[0]
    return total % len(BOTS)


def _fetch_market(reader, underlying, captured_at):
    bars = reader.daily_bars(underlying, limit=30)
    price_cents = reader.latest_trade_price_cents(underlying)
    expiration_gte = captured_at.date().isoformat()
    expiration_lte = (captured_at + timedelta(days=COMMON_RULES["days_to_expiry"]["maximum"])).date().isoformat()
    contracts = reader.option_chain(underlying, expiration_gte, expiration_lte)
    return bars, price_cents, contracts


def _valid_contract(contract, captured_at):
    from competition_operator import _validate_contract
    try:
        _validate_contract(contract, captured_at)
        return True
    except LedgerError:
        return False


def build_plan(ledger, market_reader, now):
    opportunity_id = _opportunity_id(now)
    captured_at = now.isoformat().replace("+00:00", "Z")
    all_contracts = []
    proposals = {}
    per_underlying = {}
    for underlying in UNIVERSE:
        try:
            bars, price_cents, contracts = _fetch_market(market_reader, underlying, now)
        except (LedgerError, OSError, ValueError, KeyError, TypeError):
            continue
        valid_contracts = [c for c in contracts if _valid_contract(c, now)]
        all_contracts.extend(valid_contracts)
        per_underlying[underlying] = (bars, valid_contracts, price_cents)

    for bot in BOTS:
        strategy = STRATEGIES[bot.slug]
        decision = None
        at_position_limit = _open_position_count(ledger, bot.slug) >= COMMON_RULES["max_open_positions"]
        if not at_position_limit:
            for underlying in UNIVERSE:
                if underlying not in per_underlying:
                    continue
                bars, valid_contracts, price_cents = per_underlying[underlying]
                candidate = strategy(underlying, bars, valid_contracts, price_cents)
                if candidate["action"] == "buy":
                    decision = candidate
                    break
        if decision is None:
            rationale = ("Position limit reached; abstaining this cycle." if at_position_limit
                         else "No qualifying setup found across the universe this cycle.")
            decision = {"bot_id": bot.slug, "action": "decline", "option_symbol": None,
                        "quantity": None, "limit_cents": None, "public_rationale": rationale}
        proposals[bot.slug] = decision

    buyers = [slug for slug, row in proposals.items() if row["action"] == "buy"]
    if len(buyers) > 1:
        winner = buyers[_rotation_index(ledger) % len(buyers)]
        for slug in buyers:
            if slug != winner:
                proposals[slug] = {
                    "bot_id": slug, "action": "decline", "option_symbol": None,
                    "quantity": None, "limit_cents": None,
                    "public_rationale": "Another contender was selected for this cycle's shared opportunity.",
                }

    decisions = [proposals[bot.slug] for bot in BOTS]
    plan = {
        "generation": GENERATION,
        "opportunity_id": opportunity_id,
        "captured_at": captured_at,
        "data_cutoff_at": captured_at,
        "market": {"contracts": all_contracts},
        "decisions": decisions,
    }
    return plan


def run_entries(ledger_path, env_file, lock_path):
    Path(lock_path).parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "skipped", "reason": "another entry cycle is running"}
        try:
            credentials = load_credentials(env_file)
            reader = PaperReader(credentials)
            if reader.clock().get("is_open") is not True:
                return {"status": "skipped", "reason": "market is closed"}
            now = datetime.now(timezone.utc)
            opportunity_id = _opportunity_id(now)
            ledger = Ledger(ledger_path)
            try:
                if _already_decided(ledger, opportunity_id):
                    return {"status": "skipped", "reason": "already decided this cadence window",
                            "opportunity_id": opportunity_id}
                market_reader = MarketDataReader(credentials)
                plan = build_plan(ledger, market_reader, now)
                staged = stage_plan(ledger, plan)
                submitted = None
                if staged["reserved_order"]:
                    try:
                        submitted = submit(ledger, env_file, staged["reserved_order"], EXECUTION_ENABLE_TOKEN)
                    except LedgerError as error:
                        submitted = {"client_order_id": staged["reserved_order"], "accepted": False,
                                     "reason": str(error)}
                return {"status": "completed", "opportunity_id": opportunity_id,
                        "decisions": plan["decisions"], "staged": staged, "submitted": submitted}
            finally:
                ledger.close()
        except (LedgerError, OSError, ValueError) as error:
            return {"status": "error", "error": type(error).__name__, "message": str(error)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default="/var/lib/ai-options-deathmatch/ledger.sqlite3")
    parser.add_argument("--env-file", default="/etc/ai-options-deathmatch/alpaca.env")
    parser.add_argument("--lock", default="/run/lock/ai-options-deathmatch-entries.lock")
    args = parser.parse_args()
    result = run_entries(args.ledger, args.env_file, args.lock)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
