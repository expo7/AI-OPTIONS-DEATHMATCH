"""Initialize the append-only Generation 1 ledger without contacting a broker."""

import argparse
import sqlite3

from bots import BOTS, STARTING_CASH_CENTS
from generation_one import BOT_RULES, GENERATION, frozen_rules
from ledger import Ledger


def initialize_generation(path, created_at):
    ledger = Ledger(path)
    try:
        ledger.initialize()
        for bot in BOTS:
            try:
                ledger.add_bot(bot.slug, STARTING_CASH_CENTS)
            except sqlite3.IntegrityError:
                existing = ledger.db.execute(
                    "SELECT starting_cash_cents FROM bots WHERE id=?", (bot.slug,)
                ).fetchone()
                if not existing or existing["starting_cash_cents"] != STARTING_CASH_CENTS:
                    raise
            ledger.record_bot_version(
                BOT_RULES[bot.slug]["version_id"], bot.slug, GENERATION,
                frozen_rules(bot.slug), created_at,
            )
        return len(BOTS)
    finally:
        ledger.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", help="SQLite ledger path")
    parser.add_argument("--created-at", required=True, help="Frozen configuration time in ISO 8601 UTC")
    arguments = parser.parse_args()
    count = initialize_generation(arguments.database, arguments.created_at)
    print(f"initialized Generation 1 with {count} frozen contenders")
