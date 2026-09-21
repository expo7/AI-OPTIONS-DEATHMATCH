"""Per-bot accounting for a shared options paper account.

This module never contacts a broker or submits an order. Monetary inputs are
integer cents; a standard listed option has a 100-share multiplier.
"""

import hashlib
import json
import sqlite3
from collections import defaultdict


MULTIPLIER = 100
OPEN_STATUSES = ("reserved", "accepted", "partial")


class LedgerError(ValueError):
    pass


class Ledger:
    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=10000")

    def close(self):
        self.db.close()

    def initialize(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS bots (
                id TEXT PRIMARY KEY,
                starting_cash_cents INTEGER NOT NULL CHECK(starting_cash_cents > 0)
            );
            CREATE TABLE IF NOT EXISTS orders (
                client_order_id TEXT PRIMARY KEY,
                bot_id TEXT NOT NULL REFERENCES bots(id),
                symbol TEXT NOT NULL,
                side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                limit_cents INTEGER NOT NULL CHECK(limit_cents > 0),
                status TEXT NOT NULL CHECK(status IN ('reserved','accepted','partial','filled','canceled','rejected')),
                broker_order_id TEXT UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_orders_symbol_status ON orders(symbol, status);
            CREATE TABLE IF NOT EXISTS fills (
                broker_fill_id TEXT PRIMARY KEY,
                client_order_id TEXT NOT NULL REFERENCES orders(client_order_id),
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                price_cents INTEGER NOT NULL CHECK(price_cents > 0),
                fee_cents INTEGER NOT NULL DEFAULT 0 CHECK(fee_cents >= 0),
                occurred_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS equity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id TEXT NOT NULL REFERENCES bots(id),
                equity_cents INTEGER NOT NULL CHECK(equity_cents >= 0),
                cash_cents INTEGER NOT NULL,
                occurred_at TEXT NOT NULL,
                UNIQUE(bot_id, occurred_at)
            );
            CREATE INDEX IF NOT EXISTS idx_equity_bot_time
                ON equity_snapshots(bot_id, occurred_at DESC);
            CREATE TABLE IF NOT EXISTS bot_versions (
                id TEXT PRIMARY KEY,
                bot_id TEXT NOT NULL REFERENCES bots(id),
                generation INTEGER NOT NULL CHECK(generation > 0),
                rules_json TEXT NOT NULL,
                rules_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(bot_id, generation),
                UNIQUE(rules_sha256)
            );
            CREATE TABLE IF NOT EXISTS opportunity_snapshots (
                id TEXT PRIMARY KEY,
                captured_at TEXT NOT NULL,
                data_cutoff_at TEXT NOT NULL,
                market_json TEXT NOT NULL,
                market_sha256 TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS decisions (
                id TEXT PRIMARY KEY,
                opportunity_id TEXT NOT NULL REFERENCES opportunity_snapshots(id),
                bot_id TEXT NOT NULL REFERENCES bots(id),
                bot_version_id TEXT NOT NULL REFERENCES bot_versions(id),
                action TEXT NOT NULL CHECK(action IN ('buy','decline')),
                option_symbol TEXT,
                quantity INTEGER,
                limit_cents INTEGER,
                public_rationale TEXT NOT NULL CHECK(length(public_rationale) BETWEEN 1 AND 500),
                decided_at TEXT NOT NULL,
                CHECK(
                    (action='decline' AND option_symbol IS NULL AND quantity IS NULL AND limit_cents IS NULL)
                    OR
                    (action='buy' AND option_symbol IS NOT NULL AND quantity > 0 AND limit_cents > 0)
                ),
                UNIQUE(opportunity_id, bot_id)
            );
            CREATE TABLE IF NOT EXISTS decision_orders (
                decision_id TEXT PRIMARY KEY REFERENCES decisions(id),
                client_order_id TEXT NOT NULL UNIQUE REFERENCES orders(client_order_id)
            );
            CREATE INDEX IF NOT EXISTS idx_decisions_bot_time
                ON decisions(bot_id, decided_at DESC);
            CREATE TRIGGER IF NOT EXISTS immutable_bot_versions_update
                BEFORE UPDATE ON bot_versions BEGIN SELECT RAISE(ABORT, 'bot versions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_bot_versions_delete
                BEFORE DELETE ON bot_versions BEGIN SELECT RAISE(ABORT, 'bot versions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_opportunities_update
                BEFORE UPDATE ON opportunity_snapshots BEGIN SELECT RAISE(ABORT, 'opportunities are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_opportunities_delete
                BEFORE DELETE ON opportunity_snapshots BEGIN SELECT RAISE(ABORT, 'opportunities are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_decisions_update
                BEFORE UPDATE ON decisions BEGIN SELECT RAISE(ABORT, 'decisions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_decisions_delete
                BEFORE DELETE ON decisions BEGIN SELECT RAISE(ABORT, 'decisions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_decision_orders_update
                BEFORE UPDATE ON decision_orders BEGIN SELECT RAISE(ABORT, 'decision order links are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_decision_orders_delete
                BEFORE DELETE ON decision_orders BEGIN SELECT RAISE(ABORT, 'decision order links are immutable'); END;
        """)

    def add_bot(self, bot_id, starting_cash_cents):
        if not bot_id or not isinstance(starting_cash_cents, int) or starting_cash_cents <= 0:
            raise LedgerError("bot ID and positive integer starting cash required")
        self.db.execute("INSERT INTO bots(id,starting_cash_cents) VALUES (?,?)", (bot_id, starting_cash_cents))

    def position(self, bot_id, symbol):
        row = self.db.execute("""
            SELECT COALESCE(SUM(CASE WHEN o.side='buy' THEN f.quantity ELSE -f.quantity END),0) AS quantity
            FROM fills f JOIN orders o ON o.client_order_id=f.client_order_id
            WHERE o.bot_id=? AND o.symbol=?
        """, (bot_id, symbol)).fetchone()
        return row["quantity"]

    def cash_cents(self, bot_id):
        row = self.db.execute("""
            SELECT b.starting_cash_cents + COALESCE(SUM(
                CASE WHEN o.side='buy' THEN -f.quantity*f.price_cents*100-f.fee_cents
                     ELSE f.quantity*f.price_cents*100-f.fee_cents END),0) AS cash
            FROM bots b LEFT JOIN orders o ON o.bot_id=b.id
            LEFT JOIN fills f ON f.client_order_id=o.client_order_id
            WHERE b.id=? GROUP BY b.id
        """, (bot_id,)).fetchone()
        if row is None:
            raise LedgerError("unknown bot")
        return row["cash"]

    def reserve_order(self, client_order_id, bot_id, symbol, side, quantity, limit_cents, decision_id=None):
        if not client_order_id or not symbol or side not in ("buy", "sell") or \
           not isinstance(quantity, int) or quantity <= 0 or \
           not isinstance(limit_cents, int) or limit_cents <= 0:
            raise LedgerError("invalid order")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.db.execute("SELECT * FROM orders WHERE client_order_id=?", (client_order_id,)).fetchone()
            if existing is not None:
                if (existing["bot_id"], existing["symbol"], existing["side"], existing["quantity"], existing["limit_cents"]) != \
                   (bot_id, symbol, side, quantity, limit_cents):
                    raise LedgerError("client order ID reused for different intent")
                if decision_id:
                    link = self.db.execute("SELECT decision_id FROM decision_orders WHERE client_order_id=?", (client_order_id,)).fetchone()
                    if not link or link["decision_id"] != decision_id:
                        raise LedgerError("client order ID has different decision attribution")
                self.db.execute("COMMIT")
                return False
            if decision_id:
                decision = self.db.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
                if not decision or (
                    decision["bot_id"], decision["action"], decision["option_symbol"],
                    decision["quantity"], decision["limit_cents"]
                ) != (bot_id, "buy", symbol, quantity, limit_cents):
                    raise LedgerError("order does not exactly match its immutable decision")
            conflict = self.db.execute("SELECT 1 FROM orders WHERE symbol=? AND status IN ('reserved','accepted','partial') LIMIT 1", (symbol,)).fetchone()
            if conflict:
                raise LedgerError("another order for this exact contract is unresolved")
            if side == "buy" and self.cash_cents(bot_id) < quantity * limit_cents * MULTIPLIER:
                raise LedgerError("insufficient bot cash")
            if side == "sell" and self.position(bot_id, symbol) < quantity:
                raise LedgerError("bot does not own enough contracts")
            self.db.execute("""INSERT INTO orders(client_order_id,bot_id,symbol,side,quantity,limit_cents,status)
                VALUES (?,?,?,?,?,?,'reserved')""", (client_order_id, bot_id, symbol, side, quantity, limit_cents))
            if decision_id:
                self.db.execute("INSERT INTO decision_orders VALUES (?,?)", (decision_id, client_order_id))
            self.db.execute("COMMIT")
            return True
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def accept_order(self, client_order_id, broker_order_id):
        if not broker_order_id:
            raise LedgerError("broker order ID required")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            order = self.db.execute("SELECT * FROM orders WHERE client_order_id=?", (client_order_id,)).fetchone()
            if not order or order["status"] not in ("reserved", "accepted"):
                raise LedgerError("order is not awaiting broker acceptance")
            if order["broker_order_id"] and order["broker_order_id"] != broker_order_id:
                raise LedgerError("broker order ID changed")
            self.db.execute("UPDATE orders SET status='accepted',broker_order_id=? WHERE client_order_id=?", (broker_order_id, client_order_id))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def record_fill(self, broker_fill_id, client_order_id, quantity, price_cents, occurred_at, fee_cents=0):
        if not broker_fill_id or not occurred_at or not isinstance(quantity, int) or quantity <= 0 or \
           not isinstance(price_cents, int) or price_cents <= 0 or \
           not isinstance(fee_cents, int) or fee_cents < 0:
            raise LedgerError("invalid fill")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.db.execute("SELECT * FROM fills WHERE broker_fill_id=?", (broker_fill_id,)).fetchone()
            if existing:
                if (existing["client_order_id"], existing["quantity"], existing["price_cents"], existing["occurred_at"], existing["fee_cents"]) != \
                   (client_order_id, quantity, price_cents, occurred_at, fee_cents):
                    raise LedgerError("broker fill ID reused with different data")
                self.db.execute("COMMIT")
                return False
            order = self.db.execute("SELECT * FROM orders WHERE client_order_id=?", (client_order_id,)).fetchone()
            if not order or not order["broker_order_id"] or order["status"] not in ("accepted", "partial"):
                raise LedgerError("fill has no accepted open order")
            filled = self.db.execute("SELECT COALESCE(SUM(quantity),0) FROM fills WHERE client_order_id=?", (client_order_id,)).fetchone()[0]
            if filled + quantity > order["quantity"]:
                raise LedgerError("fill exceeds order quantity")
            if order["side"] == "sell" and self.position(order["bot_id"], order["symbol"]) < quantity:
                raise LedgerError("fill exceeds bot holdings")
            # Broker fills are authoritative even if a fee or unexpected price
            # pushes virtual cash below zero. Record the event, then flag the
            # negative balance for operator review instead of losing the fill.
            self.db.execute("INSERT INTO fills VALUES (?,?,?,?,?,?)", (broker_fill_id, client_order_id, quantity, price_cents, fee_cents, occurred_at))
            self.db.execute("UPDATE orders SET status=? WHERE client_order_id=?", ("filled" if filled + quantity == order["quantity"] else "partial", client_order_id))
            self.db.execute("COMMIT")
            return True
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def close_order(self, client_order_id, status):
        if status not in ("canceled", "rejected"):
            raise LedgerError("unsupported terminal status")
        self.db.execute("UPDATE orders SET status=? WHERE client_order_id=? AND status IN ('reserved','accepted','partial')", (status, client_order_id))
        if not self.db.execute("SELECT changes()").fetchone()[0]:
            raise LedgerError("no open order to close")

    def reconcile(self, broker_positions):
        """Return mismatches in contract units; pass Alpaca's complete positions mapping."""
        attributed = defaultdict(int)
        for row in self.db.execute("""SELECT o.symbol, SUM(CASE WHEN o.side='buy' THEN f.quantity ELSE -f.quantity END) AS quantity
            FROM fills f JOIN orders o ON o.client_order_id=f.client_order_id GROUP BY o.symbol"""):
            attributed[row["symbol"]] = row["quantity"]
        return {symbol: {"bots": attributed[symbol], "broker": broker_positions.get(symbol, 0)}
                for symbol in attributed.keys() | broker_positions.keys()
                if attributed[symbol] != broker_positions.get(symbol, 0)}

    def negative_cash_bots(self):
        return {row["id"]: self.cash_cents(row["id"])
                for row in self.db.execute("SELECT id FROM bots")
                if self.cash_cents(row["id"]) < 0}

    def record_equity_snapshot(self, bot_id, equity_cents, occurred_at):
        """Record immutable mark-to-market equity for public performance."""
        if not occurred_at or not isinstance(equity_cents, int) or equity_cents < 0:
            raise LedgerError("valid timestamp and non-negative integer equity required")
        cash = self.cash_cents(bot_id)
        try:
            self.db.execute(
                "INSERT INTO equity_snapshots(bot_id,equity_cents,cash_cents,occurred_at) VALUES (?,?,?,?)",
                (bot_id, equity_cents, cash, occurred_at),
            )
            return True
        except sqlite3.IntegrityError as error:
            existing = self.db.execute(
                "SELECT equity_cents,cash_cents FROM equity_snapshots WHERE bot_id=? AND occurred_at=?",
                (bot_id, occurred_at),
            ).fetchone()
            if existing and (existing["equity_cents"], existing["cash_cents"]) == (equity_cents, cash):
                return False
            raise LedgerError("equity snapshot timestamp reused with different data") from error

    @staticmethod
    def _canonical_json(value):
        try:
            encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as error:
            raise LedgerError("value must be valid JSON") from error
        return encoded, hashlib.sha256(encoded.encode()).hexdigest()

    def record_bot_version(self, version_id, bot_id, generation, rules, created_at):
        if not version_id or not created_at or not isinstance(generation, int) or generation <= 0:
            raise LedgerError("valid bot version metadata required")
        rules_json, digest = self._canonical_json(rules)
        try:
            self.db.execute(
                "INSERT INTO bot_versions VALUES (?,?,?,?,?,?)",
                (version_id, bot_id, generation, rules_json, digest, created_at),
            )
            return True
        except sqlite3.IntegrityError as error:
            existing = self.db.execute("SELECT * FROM bot_versions WHERE id=?", (version_id,)).fetchone()
            if existing and (existing["bot_id"], existing["generation"], existing["rules_json"], existing["created_at"]) == (bot_id, generation, rules_json, created_at):
                return False
            raise LedgerError("bot version conflicts with frozen configuration") from error

    def record_opportunity(self, opportunity_id, captured_at, data_cutoff_at, market):
        if not opportunity_id or not captured_at or not data_cutoff_at:
            raise LedgerError("valid opportunity metadata required")
        market_json, digest = self._canonical_json(market)
        try:
            self.db.execute(
                "INSERT INTO opportunity_snapshots(id,captured_at,data_cutoff_at,market_json,market_sha256) VALUES (?,?,?,?,?)",
                (opportunity_id, captured_at, data_cutoff_at, market_json, digest),
            )
            return True
        except sqlite3.IntegrityError as error:
            existing = self.db.execute("SELECT * FROM opportunity_snapshots WHERE id=?", (opportunity_id,)).fetchone()
            if existing and (existing["captured_at"], existing["data_cutoff_at"], existing["market_json"]) == (captured_at, data_cutoff_at, market_json):
                return False
            raise LedgerError("opportunity conflicts with immutable snapshot") from error

    def record_decision(self, decision_id, opportunity_id, bot_id, bot_version_id, action,
                        public_rationale, decided_at, option_symbol=None, quantity=None,
                        limit_cents=None):
        if not decision_id or action not in ("buy", "decline") or not decided_at or \
           not isinstance(public_rationale, str) or not 1 <= len(public_rationale) <= 500:
            raise LedgerError("invalid public decision")
        if action == "decline" and any(value is not None for value in (option_symbol, quantity, limit_cents)):
            raise LedgerError("decline cannot specify an order")
        if action == "buy" and (not option_symbol or not isinstance(quantity, int) or quantity <= 0 or
                                not isinstance(limit_cents, int) or limit_cents <= 0):
            raise LedgerError("buy decision requires a valid proposed order")
        version = self.db.execute("SELECT bot_id FROM bot_versions WHERE id=?", (bot_version_id,)).fetchone()
        if not version or version["bot_id"] != bot_id:
            raise LedgerError("decision bot does not match frozen bot version")
        try:
            self.db.execute(
                """INSERT INTO decisions(id,opportunity_id,bot_id,bot_version_id,action,option_symbol,
                   quantity,limit_cents,public_rationale,decided_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (decision_id, opportunity_id, bot_id, bot_version_id, action, option_symbol,
                 quantity, limit_cents, public_rationale, decided_at),
            )
            return True
        except sqlite3.IntegrityError as error:
            existing = self.db.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
            expected = (opportunity_id, bot_id, bot_version_id, action, option_symbol, quantity,
                        limit_cents, public_rationale, decided_at)
            if existing and tuple(existing[key] for key in (
                "opportunity_id", "bot_id", "bot_version_id", "action", "option_symbol",
                "quantity", "limit_cents", "public_rationale", "decided_at")) == expected:
                return False
            raise LedgerError("decision conflicts with immutable record") from error
