"""Per-bot accounting for a shared options paper account.

This module never contacts a broker or submits an order. Monetary inputs are
integer cents; a standard listed option has a 100-share multiplier.
"""

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

    def reserve_order(self, client_order_id, bot_id, symbol, side, quantity, limit_cents):
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
                self.db.execute("COMMIT")
                return False
            conflict = self.db.execute("SELECT 1 FROM orders WHERE symbol=? AND status IN ('reserved','accepted','partial') LIMIT 1", (symbol,)).fetchone()
            if conflict:
                raise LedgerError("another order for this exact contract is unresolved")
            if side == "buy" and self.cash_cents(bot_id) < quantity * limit_cents * MULTIPLIER:
                raise LedgerError("insufficient bot cash")
            if side == "sell" and self.position(bot_id, symbol) < quantity:
                raise LedgerError("bot does not own enough contracts")
            self.db.execute("""INSERT INTO orders(client_order_id,bot_id,symbol,side,quantity,limit_cents,status)
                VALUES (?,?,?,?,?,?,'reserved')""", (client_order_id, bot_id, symbol, side, quantity, limit_cents))
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
