"""Supervised Generation 1 staging, submission, and fill synchronization.

This command is intentionally separate from the public web process. Staging is
offline and immutable. Submission requires the exact paper-only confirmation
token and rechecks every broker/ledger gate immediately before POSTing.
"""

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

from alpaca_readonly import PaperReader, load_credentials, sync_fill_activities
from alpaca_submit import PaperSubmitter, submit_reserved_order
from bots import BOTS
from generation_one import BOT_RULES, COMMON_RULES, GENERATION
from ledger import Ledger, LedgerError


def _utc(value, field):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise LedgerError(f"{field} must be ISO 8601") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LedgerError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_contract(contract, captured_at):
    required = ("symbol", "expiration", "bid_cents", "ask_cents", "open_interest", "volume")
    if not isinstance(contract, dict) or any(key not in contract for key in required):
        raise LedgerError("candidate contract metadata is incomplete")
    bid, ask = contract["bid_cents"], contract["ask_cents"]
    values = (bid, ask, contract["open_interest"], contract["volume"])
    if not all(isinstance(value, int) and value >= 0 for value in values) or ask <= 0 or bid >= ask:
        raise LedgerError("candidate contract quote or activity is invalid")
    try:
        days = (date.fromisoformat(contract["expiration"]) - captured_at.date()).days
    except (TypeError, ValueError):
        raise LedgerError("candidate expiration must be an ISO date") from None
    limits = COMMON_RULES["days_to_expiry"]
    if not limits["minimum"] <= days <= limits["maximum"]:
        raise LedgerError("candidate contract is outside the expiry window")
    if contract["open_interest"] < COMMON_RULES["minimum_open_interest"]:
        raise LedgerError("candidate contract has insufficient open interest")
    if contract["volume"] < COMMON_RULES["minimum_contract_volume"]:
        raise LedgerError("candidate contract has insufficient volume")
    if (ask - bid) / ask > COMMON_RULES["maximum_bid_ask_spread_fraction"]:
        raise LedgerError("candidate contract spread is too wide")
    if ask * 100 > COMMON_RULES["max_position_premium_cents"]:
        raise LedgerError("candidate contract exceeds the premium cap")


def stage_plan(ledger, plan):
    """Freeze one shared snapshot, five decisions, and at most one opening order."""
    if plan.get("generation") != GENERATION:
        raise LedgerError("plan generation does not match frozen rules")
    captured = _utc(plan.get("captured_at"), "captured_at")
    cutoff = _utc(plan.get("data_cutoff_at"), "data_cutoff_at")
    if cutoff > captured:
        raise LedgerError("data cutoff cannot follow capture time")
    market = plan.get("market")
    if not isinstance(market, dict) or not isinstance(market.get("contracts"), list):
        raise LedgerError("plan requires a shared market snapshot")
    contracts = {row.get("symbol"): row for row in market["contracts"] if isinstance(row, dict)}
    if len(contracts) != len(market["contracts"]) or None in contracts:
        raise LedgerError("candidate contracts require unique symbols")
    for contract in contracts.values():
        _validate_contract(contract, captured)

    decisions = plan.get("decisions")
    expected = {bot.slug for bot in BOTS}
    if not isinstance(decisions, list) or {row.get("bot_id") for row in decisions} != expected or len(decisions) != len(expected):
        raise LedgerError("plan must contain exactly one decision for every contender")
    buys = [row for row in decisions if row.get("action") == "buy"]
    if len(buys) > 1:
        raise LedgerError("supervised launch cycle permits at most one order")
    if any(row.get("action") not in ("buy", "decline") for row in decisions):
        raise LedgerError("unsupported decision action")
    if next(row for row in decisions if row["bot_id"] == "cash").get("action") != "decline":
        raise LedgerError("cash benchmark must decline")

    opportunity_id = plan.get("opportunity_id")
    ledger.record_opportunity(opportunity_id, plan["captured_at"], plan["data_cutoff_at"], market)
    reserved = None
    for row in decisions:
        bot_id = row["bot_id"]
        action = row["action"]
        symbol, quantity, limit_cents = row.get("option_symbol"), row.get("quantity"), row.get("limit_cents")
        if action == "buy":
            if symbol not in contracts or quantity != 1:
                raise LedgerError("buy must use one snapshotted contract")
            if limit_cents != contracts[symbol]["ask_cents"]:
                raise LedgerError("launch limit must equal the frozen ask")
        decision_id = f"{opportunity_id}-{bot_id}"
        ledger.record_decision(
            decision_id, opportunity_id, bot_id, BOT_RULES[bot_id]["version_id"], action,
            row.get("public_rationale", ""), plan["captured_at"],
            option_symbol=symbol, quantity=quantity, limit_cents=limit_cents,
        )
        if action == "buy":
            client_id = f"dm-g{GENERATION}-{bot_id}-{opportunity_id[-8:]}"
            ledger.reserve_order(client_id, bot_id, symbol, "buy", quantity, limit_cents,
                                 decision_id=decision_id)
            reserved = client_id
    return {"opportunity_id": opportunity_id, "reserved_order": reserved, "buy_count": len(buys)}


def submit(ledger, env_file, client_order_id, confirmation):
    credentials = load_credentials(env_file)
    broker_id = submit_reserved_order(
        ledger, PaperReader(credentials), PaperSubmitter(credentials, confirmation), client_order_id
    )
    return {"client_order_id": client_order_id, "accepted": bool(broker_id)}


def sync(ledger, env_file):
    baseline = ledger.db.execute(
        "SELECT captured_at FROM launch_baselines WHERE generation=?", (GENERATION,)
    ).fetchone()
    if not baseline:
        raise LedgerError("generation has no launch baseline")
    return sync_fill_activities(
        ledger, PaperReader(load_credentials(env_file)), baseline["captured_at"]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default="/var/lib/ai-options-deathmatch/ledger.sqlite3")
    parser.add_argument("--env-file", default="/etc/ai-options-deathmatch/alpaca.env")
    commands = parser.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("stage")
    stage.add_argument("plan", type=Path)
    send = commands.add_parser("submit")
    send.add_argument("client_order_id")
    send.add_argument("--confirm", required=True)
    commands.add_parser("sync")
    args = parser.parse_args()

    ledger = Ledger(args.ledger)
    try:
        if args.command == "stage":
            result = stage_plan(ledger, json.loads(args.plan.read_text()))
        elif args.command == "submit":
            result = submit(ledger, args.env_file, args.client_order_id, args.confirm)
        else:
            result = sync(ledger, args.env_file)
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        ledger.close()


if __name__ == "__main__":
    main()
