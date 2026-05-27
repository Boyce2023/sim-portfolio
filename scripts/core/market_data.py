"""
Unified price fetching with file-backed cache.

All scripts should use this instead of calling yfinance directly.

Cache file format:
    {"prices": {"NVDA": 135.5, "002028.SZ": 67.8, ...}, "updated_at": "2026-05-27T10:00:00+08:00"}

A-share tickers are stored in the cache with their yfinance suffix (.SZ/.SS) but
returned to callers in the same form they were requested (bare 6-digit codes or
suffixed, whichever was passed in).
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

TZ_BEIJING = timezone(timedelta(hours=8))
CACHE_FILE = Path(__file__).parent.parent.parent / "latest_prices.json"

# Seconds a cached price is considered fresh (default arg mirrors this)
DEFAULT_MAX_AGE = 300  # 5 minutes

_RETRY_ATTEMPTS = 3
_RETRY_DELAY = 2.0  # seconds

# OTC / special tickers that need remapping for yfinance
_YF_TICKER_MAP: dict[str, str] = {
    "SPUT": "SRUUF",  # Sprott Uranium Trust trades OTC as SRUUF
}


# ─── Ticker helpers ───────────────────────────────────────────────────────────

def cn_to_yf(ticker: str) -> str:
    """Convert A-share ticker for yfinance: 002028 -> 002028.SZ, 600000 -> 600000.SS"""
    t = ticker.strip()
    if "." in t:
        return t  # already suffixed
    if t.startswith("6"):
        return t + ".SS"
    return t + ".SZ"  # 0xxxxx / 3xxxxx → Shenzhen


def yf_to_cn(ticker: str) -> str:
    """Reverse: 002028.SZ -> 002028, 600000.SS -> 600000"""
    return ticker.split(".")[0] if "." in ticker else ticker


def _is_cn_ticker(ticker: str) -> bool:
    """Return True if ticker looks like a bare 6-digit A-share code."""
    bare = yf_to_cn(ticker)
    return bare.isdigit() and len(bare) == 6


def _to_yf_symbol(ticker: str) -> str:
    """Map any ticker to the symbol yfinance expects."""
    if _is_cn_ticker(ticker):
        return cn_to_yf(ticker)
    upper = ticker.upper()
    return _YF_TICKER_MAP.get(upper, upper)


# ─── Cache I/O ────────────────────────────────────────────────────────────────

def _read_cache() -> tuple[dict[str, float], Optional[datetime]]:
    """
    Return (prices_dict, updated_at) from CACHE_FILE.
    prices_dict keys use yfinance symbol format (with suffix for CN tickers).
    updated_at is None when the file doesn't exist or is malformed.
    """
    if not CACHE_FILE.exists():
        return {}, None
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        prices = raw.get("prices", {})
        ts_str = raw.get("updated_at")
        updated_at = datetime.fromisoformat(ts_str) if ts_str else None
        return prices, updated_at
    except Exception as e:
        logger.warning("Failed to read cache file %s: %s", CACHE_FILE, e)
        return {}, None


def _write_cache(prices: dict[str, float]) -> None:
    """Atomically write prices to CACHE_FILE."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    now_str = datetime.now(TZ_BEIJING).isoformat()
    payload = {"prices": prices, "updated_at": now_str}
    fd, tmp = tempfile.mkstemp(dir=CACHE_FILE.parent, prefix=".mdata_tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CACHE_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ─── yfinance fetch ───────────────────────────────────────────────────────────

def _fetch_yf_price(yf_symbol: str) -> Optional[float]:
    """
    Fetch a single price from yfinance with retry + history fallback.
    Returns float price on success, None on failure (logged as warning).
    """
    last_error = ""
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            t = yf.Ticker(yf_symbol)
            info = t.fast_info
            price = info.last_price

            if price is None or (isinstance(price, float) and math.isnan(price)) or price <= 0:
                hist = t.history(period="2d", auto_adjust=True)
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])

            if price is None or (isinstance(price, float) and math.isnan(price)) or price <= 0:
                last_error = "no valid price returned"
                if attempt < _RETRY_ATTEMPTS - 1:
                    time.sleep(_RETRY_DELAY)
                continue

            return round(float(price), 4)

        except Exception as e:
            last_error = str(e)
            if attempt < _RETRY_ATTEMPTS - 1:
                time.sleep(_RETRY_DELAY)

    logger.warning("Could not fetch price for %s after %d attempts: %s",
                   yf_symbol, _RETRY_ATTEMPTS, last_error)
    return None


def _batch_fetch(yf_symbols: list[str]) -> dict[str, float]:
    """
    Fetch prices for a list of yfinance symbols.
    Returns {yf_symbol: price}; missing/failed tickers are omitted.
    """
    results: dict[str, float] = {}
    for sym in yf_symbols:
        price = _fetch_yf_price(sym)
        if price is not None:
            results[sym] = price
        # else: already logged inside _fetch_yf_price
    return results


# ─── Public API ───────────────────────────────────────────────────────────────

def get_prices(tickers: list[str], max_age: int = DEFAULT_MAX_AGE) -> dict[str, float]:
    """Batch fetch prices with file-backed cache.

    Args:
        tickers: list of tickers — bare A-share codes ("002028"), suffixed ("002028.SZ"),
                 or US symbols ("NVDA", "SPUT").
        max_age: cache TTL in seconds. Set to 0 to force a fresh fetch for all tickers.

    Returns:
        {ticker: price} dict keyed by the original ticker form passed in.
        Tickers that could not be fetched are omitted (with a logged warning).

    Cache logic:
        1. Read CACHE_FILE if it exists and its age < max_age.
        2. For tickers not in cache (or when cache is expired / max_age==0), batch-fetch
           via yfinance.
        3. Update cache file with merged prices.
        4. Return results keyed by original ticker form.
    """
    if not tickers:
        return {}

    # Map each original ticker → yfinance symbol
    orig_to_yf = {t: _to_yf_symbol(t) for t in tickers}

    # Read existing cache
    cached_prices, updated_at = _read_cache()

    now = datetime.now(TZ_BEIJING)
    cache_age = (now - updated_at).total_seconds() if updated_at else float("inf")
    cache_fresh = max_age > 0 and cache_age < max_age

    # Decide which yf symbols need a fresh fetch
    if cache_fresh:
        stale_yf = [yf_sym for yf_sym in orig_to_yf.values() if yf_sym not in cached_prices]
    else:
        stale_yf = list(orig_to_yf.values())

    # Fetch missing / stale prices
    if stale_yf:
        fresh = _batch_fetch(stale_yf)
        cached_prices.update(fresh)
        _write_cache(cached_prices)

    # Build result keyed by original ticker form
    result: dict[str, float] = {}
    for orig, yf_sym in orig_to_yf.items():
        if yf_sym in cached_prices:
            result[orig] = cached_prices[yf_sym]
        else:
            logger.warning("No price available for %s (yf: %s)", orig, yf_sym)

    return result


def get_price(ticker: str, max_age: int = DEFAULT_MAX_AGE) -> Optional[float]:
    """Single-ticker convenience wrapper. Returns None if price unavailable."""
    result = get_prices([ticker], max_age=max_age)
    return result.get(ticker)


def refresh_all(tickers: list[str]) -> dict[str, float]:
    """Force-refresh all tickers, ignoring cache. Used by update_prices.py."""
    return get_prices(tickers, max_age=0)
