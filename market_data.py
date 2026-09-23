"""Paper-credentialed, GET-only Alpaca data with Yahoo liquidity augmentation.

This module never submits an order and never contacts the trading endpoint;
it only reads public market data (bars, latest trade, options snapshots)
using the same paper account key/secret already used for trading. It fails
closed: any missing, incomplete, or malformed field is treated as unusable
data rather than a fabricated value, so a market-data outage or an
unavailable data entitlement causes callers to abstain instead of guessing.
"""

import json
import math
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ledger import LedgerError


DATA_URL = "https://data.alpaca.markets"


class MarketDataReader:
    """Read-only wrapper around Alpaca's market data API.

    Only ``/v2/`` and ``/v1beta1/`` GET endpoints are reachable, and the host
    is hard-coded to ``DATA_URL``; there is no method here that can place,
    modify, or cancel an order at any endpoint, paper or live.
    """

    def __init__(self, credentials, opener=urlopen, yahoo=None):
        if not credentials.get("APCA_API_KEY_ID") or not credentials.get("APCA_API_SECRET_KEY"):
            raise LedgerError("paper key and secret are required")
        self.credentials = credentials
        self.opener = opener
        self.yahoo = yahoo if yahoo is not None else YahooLiquidityReader()

    def _get(self, path, params=None):
        if not (path.startswith("/v2/") or path.startswith("/v1beta1/")) or "?" in path or "//" in path:
            raise LedgerError("invalid market data API path")
        url = DATA_URL + path + ("?" + urlencode(params) if params else "")
        request = Request(url, headers={
            "APCA-API-KEY-ID": self.credentials["APCA_API_KEY_ID"],
            "APCA-API-SECRET-KEY": self.credentials["APCA_API_SECRET_KEY"],
            "Accept": "application/json",
        }, method="GET")
        with self.opener(request, timeout=12) as response:
            return json.load(response)

    def daily_bars(self, symbol, limit=30):
        """Return up to ``limit`` most recent complete daily bars, oldest first."""
        if not isinstance(limit, int) or not 1 <= limit <= 200:
            raise LedgerError("bar limit outside 1..200")
        payload = self._get(f"/v2/stocks/{symbol}/bars", {
            "timeframe": "1Day", "limit": limit, "adjustment": "raw", "feed": "iex",
        })
        bars = payload.get("bars")
        if not isinstance(bars, list) or not bars:
            raise LedgerError("no daily bars available")
        parsed = []
        for bar in bars:
            try:
                parsed.append({
                    "t": bar["t"],
                    "o": _decimal_cents(bar["o"]),
                    "h": _decimal_cents(bar["h"]),
                    "l": _decimal_cents(bar["l"]),
                    "c": _decimal_cents(bar["c"]),
                    "v": int(bar["v"]),
                })
            except (KeyError, TypeError, ValueError, InvalidOperation):
                raise LedgerError("malformed daily bar") from None
        return parsed

    def latest_trade_price_cents(self, symbol):
        payload = self._get(f"/v2/stocks/{symbol}/trades/latest")
        trade = payload.get("trade")
        if not isinstance(trade, dict) or trade.get("p") is None:
            raise LedgerError("no latest trade available")
        return _decimal_cents(trade["p"])

    def option_chain(self, underlying, expiration_gte, expiration_lte, max_pages=100, page_size=100):
        """Join current Alpaca quotes to Yahoo OI by exact OCC symbol."""
        if not isinstance(max_pages, int) or not 1 <= max_pages <= 100:
            raise LedgerError("page bound outside 1..100")
        contracts = []
        self.last_diagnostics = {"alpaca_contracts": 0, "yahoo_matched": 0, "combined": 0}
        page_token = None
        seen_tokens = set()
        for _ in range(max_pages):
            params = {
                "expiration_date_gte": expiration_gte, "expiration_date_lte": expiration_lte,
                "limit": page_size,
            }
            if page_token:
                params["page_token"] = page_token
            payload = self._get(f"/v1beta1/options/snapshots/{underlying}", params)
            snapshots = payload.get("snapshots")
            if not isinstance(snapshots, dict):
                raise LedgerError("options snapshot page is not a mapping")
            for option_symbol, snapshot in snapshots.items():
                contract = _normalize_contract(option_symbol, snapshot)
                if contract is not None:
                    contracts.append(contract)
            page_token = payload.get("next_page_token")
            if not page_token:
                break
            if page_token in seen_tokens:
                raise LedgerError("options snapshot pagination repeated a token")
            seen_tokens.add(page_token)
        else:
            raise LedgerError("options snapshot pagination exceeded safety bound")
        if not contracts:
            return []
        self.last_diagnostics["alpaca_contracts"] = len(contracts)
        try:
            liquidity = self.yahoo.chain(underlying, {c["expiration"] for c in contracts})
        except (LedgerError, OSError, ValueError, TypeError, KeyError):
            return []
        if not isinstance(liquidity, Mapping):
            return []
        self.last_diagnostics["yahoo_matched"] = sum(c["symbol"] in liquidity for c in contracts)
        combined = []
        observed_at = datetime.now(timezone.utc).isoformat()
        for contract in contracts:
            row = liquidity.get(contract["symbol"])
            if not isinstance(row, Mapping):
                continue
            oi = _nonnegative_integer(row.get("open_interest"))
            volume = _nonnegative_integer(row.get("volume"))
            volume_source = "yahoo_delayed"
            if volume is None:
                volume = contract.pop("alpaca_volume", None)
                volume_source = "alpaca"
            if oi is None or volume is None:
                continue
            contract.update(open_interest=oi, volume=volume,
                            quote_source="alpaca", open_interest_source="yahoo_delayed",
                            volume_source=volume_source, liquidity_observed_at=observed_at)
            contract.pop("alpaca_volume", None)
            combined.append(contract)
        self.last_diagnostics["combined"] = len(combined)
        return combined


class YahooLiquidityReader:
    """Read delayed Yahoo option chains via yfinance; never infer missing values."""

    def __init__(self, ticker_factory=None):
        self.ticker_factory = ticker_factory

    def chain(self, underlying, expirations):
        if self.ticker_factory is None:
            try:
                import yfinance
            except ImportError:
                raise LedgerError("yfinance is unavailable") from None
            factory = yfinance.Ticker
        else:
            factory = self.ticker_factory
        try:
            ticker = factory(underlying)
            available = set(ticker.options)
        except Exception as error:
            raise LedgerError("Yahoo expiration lookup failed") from error
        matched = {}
        duplicates = set()
        for expiration in sorted(expirations & available):
            try:
                chain = ticker.option_chain(expiration)
                for option_type, frame in (("call", chain.calls), ("put", chain.puts)):
                    for row in frame.to_dict("records"):
                        symbol = row.get("contractSymbol")
                        try:
                            parsed = parse_occ_symbol(symbol)
                        except LedgerError:
                            continue
                        if parsed[:3] != (underlying, datetime.fromisoformat(expiration).date(), option_type):
                            continue
                        if symbol in matched or symbol in duplicates:
                            matched.pop(symbol, None)
                            duplicates.add(symbol)
                            continue
                        matched[symbol] = {"open_interest": row.get("openInterest"),
                                           "volume": row.get("volume")}
            except Exception:
                # One broken expiry must not prevent the remaining expiries from being assessed.
                continue
        return matched


def _nonnegative_integer(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        return None
    return int(number)


def _decimal_cents(value):
    cents = Decimal(str(value)) * 100
    if not cents.is_finite() or cents <= 0:
        raise LedgerError("invalid or non-positive price")
    return int(cents.quantize(Decimal("1")))


def parse_occ_symbol(symbol):
    """Return (underlying, expiration_date, option_type, strike_cents) from an OCC symbol."""
    if not isinstance(symbol, str) or len(symbol) < 15:
        raise LedgerError("invalid OCC option symbol")
    suffix = symbol[-15:]
    underlying = symbol[:-15]
    try:
        expiration = datetime.strptime(suffix[:6], "%y%m%d").date()
    except ValueError:
        raise LedgerError("invalid OCC option expiration") from None
    option_type = {"C": "call", "P": "put"}.get(suffix[6])
    if option_type is None or not underlying:
        raise LedgerError("invalid OCC option symbol")
    try:
        strike_cents = int(suffix[7:]) // 10
    except ValueError:
        raise LedgerError("invalid OCC option strike") from None
    return underlying, expiration, option_type, strike_cents


def _normalize_contract(option_symbol, snapshot):
    try:
        underlying, expiration, option_type, strike_cents = parse_occ_symbol(option_symbol)
    except LedgerError:
        return None
    if not isinstance(snapshot, dict):
        return None
    quote = snapshot.get("latestQuote")
    if not isinstance(quote, dict):
        return None
    try:
        bid_cents = _decimal_cents(quote["bp"]) if quote.get("bp") else 0
        ask_cents = _decimal_cents(quote["ap"])
        bar = snapshot.get("dailyBar")
        alpaca_volume = _nonnegative_integer(bar.get("v")) if isinstance(bar, dict) else None
    except (KeyError, TypeError, ValueError, InvalidOperation, LedgerError):
        return None
    if bid_cents <= 0 or bid_cents >= ask_cents:
        return None
    return {
        "symbol": option_symbol, "underlying": underlying, "option_type": option_type,
        "strike_cents": strike_cents, "expiration": expiration.isoformat(),
        "bid_cents": bid_cents, "ask_cents": ask_cents,
        "alpaca_volume": alpaca_volume,
    }
