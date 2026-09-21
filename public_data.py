"""Sanitized projection of competition results for the public website."""

import json
import os
import sqlite3
import tempfile
from pathlib import Path


def load_public_standings(path):
    """Return published metrics from an initialized ledger, or an empty mapping.

    The connection is opened in SQLite read-only mode. This module cannot create,
    migrate, or mutate the competition ledger.
    """
    database = Path(path)
    if not database.is_file():
        return {}
    if database.suffix == ".json":
        try:
            payload = json.loads(database.read_text())
            return payload["standings"] if payload.get("generation") == 1 else {}
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
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
                "recent_decisions": _recent_decisions(db, bot["id"]),
            }
        return standings
    except sqlite3.DatabaseError:
        return {}
    finally:
        if "db" in locals():
            db.close()


def build_public_standings(db):
    """Build the public-only projection from an already-open trusted ledger."""
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
        starting = bot["starting_cash_cents"]
        standings[bot["id"]] = {
            "starting_cash_cents": starting,
            "equity_cents": latest["equity_cents"],
            "return_fraction": (latest["equity_cents"] - starting) / starting,
            "max_drawdown_fraction": max_drawdown,
            "closed_trades": db.execute(
                "SELECT COUNT(*) FROM orders WHERE bot_id=? AND side='sell' AND status='filled'",
                (bot["id"],),
            ).fetchone()[0],
            "as_of": latest["occurred_at"],
            "recent_decisions": _recent_decisions(db, bot["id"]),
        }
    return standings


def write_public_results(ledger, path, generated_at):
    """Atomically write a credential-free, world-readable standings document."""
    target = Path(path)
    target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    payload = {"generation": 1, "generated_at": generated_at,
               "standings": build_public_standings(ledger.db)}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(encoded)
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return len(payload["standings"])


def _recent_decisions(db, bot_id, limit=10):
    try:
        rows = db.execute(
            """SELECT action,option_symbol,quantity,limit_cents,public_rationale,decided_at
               FROM decisions WHERE bot_id=? ORDER BY decided_at DESC,id DESC LIMIT ?""",
            (bot_id, limit),
        ).fetchall()
    except sqlite3.DatabaseError:
        return []
    return [dict(row) for row in rows]
