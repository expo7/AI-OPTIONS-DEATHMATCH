"""Build complete, reviewable competition plans from one shared market snapshot.

This command only writes immutable opportunity and decision records to the local
ledger. It never contacts Alpaca and never submits an order.
"""

import argparse
import json
from pathlib import Path

from bots import BOTS
from competition_operator import stage_plan, validate_plan
from generation_one import BOT_RULES, GENERATION
from ledger import Ledger, LedgerError


def enqueue(ledger, snapshot):
    plan = {
        "generation": snapshot.get("generation"),
        "opportunity_id": snapshot.get("opportunity_id"),
        "captured_at": snapshot.get("captured_at"),
        "data_cutoff_at": snapshot.get("data_cutoff_at"),
        "market": snapshot.get("market"),
        "decisions": [
            {"bot_id": bot.slug, "action": "decline", "public_rationale": "Pending queue validation."}
            for bot in BOTS
        ],
    }
    # Reuse the production plan validator, but do not persist placeholder decisions.
    validate_plan(plan)
    created = ledger.record_opportunity(
        plan["opportunity_id"], plan["captured_at"], plan["data_cutoff_at"], plan["market"]
    )
    return {"opportunity_id": plan["opportunity_id"], "created": created,
            "pending": [bot.slug for bot in BOTS]}


def record_queued_decision(ledger, opportunity_id, decision):
    opportunity = ledger.db.execute(
        "SELECT * FROM opportunity_snapshots WHERE id=?", (opportunity_id,)
    ).fetchone()
    if not opportunity:
        raise LedgerError("queued opportunity does not exist")
    bot_id = decision.get("bot_id")
    if bot_id not in BOT_RULES:
        raise LedgerError("unknown contender")
    existing = _decisions(ledger, opportunity_id)
    candidate = dict(decision)
    candidate["bot_id"] = bot_id
    decisions = []
    for bot in BOTS:
        if bot.slug == bot_id:
            decisions.append(candidate)
        elif bot.slug in existing:
            decisions.append(existing[bot.slug])
        else:
            decisions.append({"bot_id": bot.slug, "action": "decline",
                              "public_rationale": "Pending queue validation."})
    validate_plan({
        "generation": GENERATION,
        "opportunity_id": opportunity_id,
        "captured_at": opportunity["captured_at"],
        "data_cutoff_at": opportunity["data_cutoff_at"],
        "market": json.loads(opportunity["market_json"]),
        "decisions": decisions,
    })
    decision_id = f"{opportunity_id}-{bot_id}"
    created = ledger.record_decision(
        decision_id, opportunity_id, bot_id, BOT_RULES[bot_id]["version_id"],
        candidate.get("action"), candidate.get("public_rationale", ""),
        opportunity["captured_at"], option_symbol=candidate.get("option_symbol"),
        quantity=candidate.get("quantity"), limit_cents=candidate.get("limit_cents"),
    )
    return {"opportunity_id": opportunity_id, "bot_id": bot_id, "created": created}


def _decisions(ledger, opportunity_id):
    rows = ledger.db.execute(
        "SELECT * FROM decisions WHERE opportunity_id=? ORDER BY bot_id", (opportunity_id,)
    ).fetchall()
    return {row["bot_id"]: {
        "bot_id": row["bot_id"], "action": row["action"],
        "option_symbol": row["option_symbol"], "quantity": row["quantity"],
        "limit_cents": row["limit_cents"], "public_rationale": row["public_rationale"],
    } for row in rows}


def queue_status(ledger, opportunity_id=None):
    where, params = ("WHERE id=?", (opportunity_id,)) if opportunity_id else ("", ())
    opportunities = ledger.db.execute(
        f"SELECT id,captured_at FROM opportunity_snapshots {where} ORDER BY captured_at DESC", params
    ).fetchall()
    output = []
    expected = [bot.slug for bot in BOTS]
    for opportunity in opportunities:
        decisions = _decisions(ledger, opportunity["id"])
        pending = [bot_id for bot_id in expected if bot_id not in decisions]
        buys = [row for row in decisions.values() if row["action"] == "buy"]
        output.append({"opportunity_id": opportunity["id"], "captured_at": opportunity["captured_at"],
                       "ready": not pending, "pending": pending, "buy_count": len(buys)})
    if opportunity_id and not output:
        raise LedgerError("queued opportunity does not exist")
    return output[0] if opportunity_id else output


def assemble_plan(ledger, opportunity_id):
    status = queue_status(ledger, opportunity_id)
    if not status["ready"]:
        raise LedgerError("queued opportunity still has pending decisions")
    opportunity = ledger.db.execute(
        "SELECT * FROM opportunity_snapshots WHERE id=?", (opportunity_id,)
    ).fetchone()
    decisions = _decisions(ledger, opportunity_id)
    plan = {
        "generation": GENERATION, "opportunity_id": opportunity_id,
        "captured_at": opportunity["captured_at"], "data_cutoff_at": opportunity["data_cutoff_at"],
        "market": json.loads(opportunity["market_json"]),
        "decisions": [decisions[bot.slug] for bot in BOTS],
    }
    validate_plan(plan)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default="/var/lib/ai-options-deathmatch/ledger.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("enqueue")
    add.add_argument("snapshot", type=Path)
    decide = commands.add_parser("decide")
    decide.add_argument("opportunity_id")
    decide.add_argument("decision", type=Path)
    status = commands.add_parser("status")
    status.add_argument("opportunity_id", nargs="?")
    assemble = commands.add_parser("assemble")
    assemble.add_argument("opportunity_id")
    stage = commands.add_parser("stage")
    stage.add_argument("opportunity_id")
    args = parser.parse_args()

    ledger = Ledger(args.ledger)
    try:
        if args.command == "enqueue":
            result = enqueue(ledger, json.loads(args.snapshot.read_text()))
        elif args.command == "decide":
            result = record_queued_decision(
                ledger, args.opportunity_id, json.loads(args.decision.read_text())
            )
        elif args.command == "status":
            result = queue_status(ledger, args.opportunity_id)
        elif args.command == "assemble":
            result = assemble_plan(ledger, args.opportunity_id)
        else:
            result = stage_plan(ledger, assemble_plan(ledger, args.opportunity_id))
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        ledger.close()


if __name__ == "__main__":
    main()
