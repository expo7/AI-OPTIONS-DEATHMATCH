"""Supervised Generation 1 staging, submission, and fill synchronization.

This command is intentionally separate from the public web process. Staging is
offline and immutable. Submission requires the exact paper-only confirmation
token and rechecks every broker/ledger gate immediately before POSTing.
"""

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

from alpaca_readonly import PaperReader, load_credentials, premium_cents, sync_fill_activities
from alpaca_submit import EXECUTION_ENABLE_TOKEN, PaperSubmitter, submit_reserved_exit, submit_reserved_order
from bots import BOTS
from generation_one import BOT_RULES, COMMON_RULES, GENERATION
from ledger import OPEN_STATUSES, Ledger, LedgerError
from lifecycle_policy import POLICY_ID, exit_signals
from public_data import write_public_results


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
    if not all(type(value) is int and value >= 0 for value in values) or bid <= 0 or ask <= 0 or bid >= ask:
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


def validate_plan(plan):
    """Validate a complete Generation 1 plan without changing the ledger."""
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

    for row in decisions:
        action = row["action"]
        symbol, quantity, limit_cents = row.get("option_symbol"), row.get("quantity"), row.get("limit_cents")
        rationale = row.get("public_rationale")
        if not isinstance(rationale, str) or not 1 <= len(rationale) <= 500:
            raise LedgerError("every decision requires a concise public rationale")
        if action == "decline" and any(value is not None for value in (symbol, quantity, limit_cents)):
            raise LedgerError("decline cannot specify an order")
        if action == "buy":
            if symbol not in contracts or quantity != 1:
                raise LedgerError("buy must use one snapshotted contract")
            if limit_cents != contracts[symbol]["ask_cents"]:
                raise LedgerError("launch limit must equal the frozen ask")
    if not plan.get("opportunity_id"):
        raise LedgerError("plan requires an opportunity ID")
    return contracts


def stage_plan(ledger, plan):
    """Freeze one shared snapshot, five decisions, and at most one opening order."""
    contracts = validate_plan(plan)

    opportunity_id = plan.get("opportunity_id")
    ledger.record_opportunity(
        opportunity_id, plan["captured_at"], plan["data_cutoff_at"], plan["market"]
    )
    reserved = None
    for row in plan["decisions"]:
        bot_id = row["bot_id"]
        action = row["action"]
        symbol, quantity, limit_cents = row.get("option_symbol"), row.get("quantity"), row.get("limit_cents")
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
    return {"opportunity_id": opportunity_id, "reserved_order": reserved,
            "buy_count": sum(row["action"] == "buy" for row in plan["decisions"])}


def submit(ledger, env_file, client_order_id, confirmation):
    credentials = load_credentials(env_file)
    broker_id = submit_reserved_order(
        ledger, PaperReader(credentials), PaperSubmitter(credentials, confirmation), client_order_id
    )
    return {"client_order_id": client_order_id, "accepted": bool(broker_id)}


def stage_exit(ledger, bot_id, symbol, quantity, limit_cents, reason, rationale, decided_at=None):
    """Migrate exit tables and freeze one supervised closing reservation."""
    if bot_id not in BOT_RULES:
        raise LedgerError("unknown contender")
    ledger.initialize()
    timestamp = decided_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    token = timestamp.replace("-", "").replace(":", "").replace(".", "").replace("+", "")[-14:]
    decision_id = f"exit-g{GENERATION}-{bot_id}-{token}"
    client_id = f"dm-g{GENERATION}-exit-{bot_id}-{token}"
    ledger.record_exit_decision(
        decision_id, bot_id, BOT_RULES[bot_id]["version_id"], symbol, quantity,
        limit_cents, reason, rationale, timestamp,
    )
    ledger.reserve_exit_order(client_id, decision_id)
    return {"exit_decision_id": decision_id, "reserved_order": client_id,
            "symbol": symbol, "quantity": quantity, "limit_cents": limit_cents}


def submit_exit(ledger, env_file, client_order_id, confirmation):
    credentials = load_credentials(env_file)
    broker_id = submit_reserved_exit(
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


def mark(ledger, env_file, public_results, occurred_at=None):
    """Reconcile broker inventory and record one common mark for every bot."""
    reader = PaperReader(load_credentials(env_file))
    account = reader.account()
    if account.get("status") != "ACTIVE" or account.get("trading_blocked") is True:
        raise LedgerError("paper account is not currently eligible")
    if reader.open_orders():
        raise LedgerError("cannot mark while broker orders are unresolved")
    positions = reader.positions()
    from alpaca_submit import broker_position_map
    if ledger.reconcile(broker_position_map(positions)):
        raise LedgerError("broker positions do not reconcile to bot allocations")
    prices = {}
    for position in positions:
        prices[position["symbol"]] = premium_cents(position.get("current_price"))
    timestamp = occurred_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    equities = {}
    public_positions = {}
    for bot in BOTS:
        equity = ledger.cash_cents(bot.slug)
        holdings = ledger.db.execute(
            """SELECT o.symbol,SUM(CASE WHEN o.side='buy' THEN f.quantity ELSE -f.quantity END) quantity
               FROM fills f JOIN orders o ON o.client_order_id=f.client_order_id
               WHERE o.bot_id=? GROUP BY o.symbol""", (bot.slug,)
        ).fetchall()
        bot_positions = []
        for holding in holdings:
            if holding["quantity"] and holding["symbol"] not in prices:
                raise LedgerError("attributed holding has no broker mark")
            equity += holding["quantity"] * prices.get(holding["symbol"], 0) * 100
            if holding["quantity"]:
                symbol = holding["symbol"]
                cost = open_lot_cost_cents(ledger, bot.slug, symbol)
                value = holding["quantity"] * prices[symbol] * 100
                expiration = option_expiration(symbol)
                days = (expiration - _utc(timestamp, "mark timestamp").date()).days
                position_return = (value - cost) / cost if cost else 0.0
                signals = exit_signals(position_return, days)
                bot_positions.append({
                    "symbol": symbol, "quantity": holding["quantity"],
                    "cost_basis_cents": cost, "market_value_cents": value,
                    "unrealized_pl_cents": value - cost,
                    "return_fraction": position_return,
                    "mark_cents": prices[symbol], "expiration": expiration.isoformat(),
                    "days_to_expiry": days, "exit_policy_id": POLICY_ID,
                    "exit_signals": signals, "exit_due": bool(signals),
                })
        if equity < 0:
            raise LedgerError("negative bot equity cannot be published")
        equities[bot.slug] = equity
        public_positions[bot.slug] = bot_positions
    for bot_id, equity in equities.items():
        ledger.record_equity_snapshot(bot_id, equity, timestamp)
    published = write_public_results(ledger, public_results, timestamp, public_positions)
    exits_due = sum(position["exit_due"] for rows in public_positions.values() for position in rows)
    return {"marked_at": timestamp, "contenders": len(equities), "published": published,
            "open_positions": sum(map(len, public_positions.values())), "expiry_exits_due": exits_due,
            "positions": public_positions}


def auto_manage_exits(ledger, env_file, public_positions):
    """Automatically stage and submit exits for positions with a due signal.

    This only decides *when* to close a position. Every existing safety gate
    in ``stage_exit``/``submit_reserved_exit`` still applies unchanged: exact
    ownership, live broker reconciliation, immutable decision linkage, and one
    unresolved order per exact contract. A symbol already carrying an
    unresolved order (for example a prior automatic exit still awaiting a
    fill) is skipped rather than re-staged, so a duplicate scheduled run or a
    slow fill cannot duplicate an exit order.
    """
    results = []
    for bot_id, positions in public_positions.items():
        for position in positions:
            if not position["exit_due"]:
                continue
            symbol = position["symbol"]
            placeholders = ",".join("?" * len(OPEN_STATUSES))
            pending = ledger.db.execute(
                f"SELECT 1 FROM orders WHERE symbol=? AND status IN ({placeholders}) LIMIT 1",
                (symbol, *OPEN_STATUSES),
            ).fetchone()
            if pending:
                results.append({"bot_id": bot_id, "symbol": symbol, "status": "already_pending"})
                continue
            reason = "expiry_rule" if "expiry_rule" in position["exit_signals"] else position["exit_signals"][0]
            rationale = (f"Automatic exit: {', '.join(position['exit_signals'])} "
                         f"under lifecycle policy {position['exit_policy_id']}.")
            try:
                staged = stage_exit(ledger, bot_id, symbol, position["quantity"],
                                    position["mark_cents"], reason, rationale)
                credentials = load_credentials(env_file)
                broker_id = submit_reserved_exit(
                    ledger, PaperReader(credentials),
                    PaperSubmitter(credentials, EXECUTION_ENABLE_TOKEN),
                    staged["reserved_order"],
                )
                results.append({"bot_id": bot_id, "symbol": symbol, "status": "submitted",
                                "broker_order_id": broker_id})
            except LedgerError as error:
                results.append({"bot_id": bot_id, "symbol": symbol, "status": "not_submitted",
                                "reason": str(error)})
    return results


def option_expiration(symbol):
    """Extract the OCC YYMMDD expiration from an option symbol."""
    if not isinstance(symbol, str) or len(symbol) < 15:
        raise LedgerError("invalid OCC option symbol")
    suffix = symbol[-15:]
    try:
        return datetime.strptime(suffix[:6], "%y%m%d").date()
    except ValueError:
        raise LedgerError("invalid OCC option expiration") from None


def open_lot_cost_cents(ledger, bot_id, symbol):
    """Return remaining FIFO premium cost, including the 100-share multiplier."""
    rows = ledger.db.execute(
        """SELECT o.side,f.quantity,f.price_cents FROM fills f
           JOIN orders o ON o.client_order_id=f.client_order_id
           WHERE o.bot_id=? AND o.symbol=? ORDER BY f.occurred_at,f.broker_fill_id""",
        (bot_id, symbol),
    ).fetchall()
    lots = []
    for row in rows:
        if row["side"] == "buy":
            lots.append([row["quantity"], row["price_cents"]])
            continue
        remaining = row["quantity"]
        while remaining and lots:
            consumed = min(remaining, lots[0][0])
            lots[0][0] -= consumed
            remaining -= consumed
            if lots[0][0] == 0:
                lots.pop(0)
        if remaining:
            raise LedgerError("sell fills exceed FIFO lots")
    return sum(quantity * price * 100 for quantity, price in lots)


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
    exit_stage = commands.add_parser("stage-exit")
    exit_stage.add_argument("--bot", required=True)
    exit_stage.add_argument("--symbol", required=True)
    exit_stage.add_argument("--quantity", required=True, type=int)
    exit_stage.add_argument("--limit-cents", required=True, type=int)
    exit_stage.add_argument("--reason", required=True,
                            choices=("thesis_invalidation", "risk_limit", "target", "expiry_rule", "operator"))
    exit_stage.add_argument("--rationale", required=True)
    exit_send = commands.add_parser("submit-exit")
    exit_send.add_argument("client_order_id")
    exit_send.add_argument("--confirm", required=True)
    commands.add_parser("sync")
    marking = commands.add_parser("mark")
    marking.add_argument("--public-results", default="/var/lib/ai-options-deathmatch-public/results.json")
    args = parser.parse_args()

    ledger = Ledger(args.ledger)
    try:
        if args.command == "stage":
            result = stage_plan(ledger, json.loads(args.plan.read_text()))
        elif args.command == "submit":
            result = submit(ledger, args.env_file, args.client_order_id, args.confirm)
        elif args.command == "stage-exit":
            result = stage_exit(ledger, args.bot, args.symbol, args.quantity, args.limit_cents,
                                args.reason, args.rationale)
        elif args.command == "submit-exit":
            result = submit_exit(ledger, args.env_file, args.client_order_id, args.confirm)
        elif args.command == "sync":
            result = sync(ledger, args.env_file)
        else:
            result = mark(ledger, args.env_file, args.public_results)
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        ledger.close()


if __name__ == "__main__":
    main()
