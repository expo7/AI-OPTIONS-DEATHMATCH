"""Read-only projection of competition results for the public website."""

import sqlite3
from pathlib import Path


def load_public_standings(path):
    """Return published metrics from an initialized ledger, or an empty mapping.

    The connection is opened in SQLite read-only mode. This module cannot create,
    migrate, or mutate the competition ledger.
    """
    database = Path(path)
    if not database.is_file():
        return {}
    try:
        db = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        bots = db.execute("SELECT id,starting_cash_cents FROM bots ORDER BY id").fetchall()
        standings = {}
        for bot in bots:
            snapshots = db.execute(
                "SELECT equity_cents,occurred_at FROM equity_snapshots WHERE bot_id=? ORDER BY occurred_at",
                (bot["id"],),
            ).fetchall()
            if not snapshots:
                continue
            peak = snapshots[0]["equity_cents"]
            max_drawdown = 0.0
            for snapshot in snapshots:
                equity = snapshot["equity_cents"]
                peak = max(peak, equity)
                if peak:
                    max_drawdown = max(max_drawdown, (peak - equity) / peak)
            latest = snapshots[-1]
            closed_trades = db.execute(
                "SELECT COUNT(*) FROM orders WHERE bot_id=? AND side='sell' AND status='filled'",
                (bot["id"],),
            ).fetchone()[0]
            starting = bot["starting_cash_cents"]
            standings[bot["id"]] = {
                "starting_cash_cents": starting,
                "equity_cents": latest["equity_cents"],
                "return_fraction": (latest["equity_cents"] - starting) / starting,
                "max_drawdown_fraction": max_drawdown,
                "closed_trades": closed_trades,
                "as_of": latest["occurred_at"],
            }
        return standings
    except sqlite3.DatabaseError:
        return {}
    finally:
        if "db" in locals():
            db.close()
