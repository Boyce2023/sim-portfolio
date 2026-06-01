# /// script
# requires-python = ">=3.11"
# dependencies = ["baostock>=0.8", "pandas>=2.0"]
# ///
"""
Local K-line cache — SQLite storage for A-share daily OHLCV.

First run: bulk loads from baostock (~20s for 40 stocks × 65 days)
Subsequent runs: incremental delta (~1-2s, only new trading days)

Usage:
  from kline_cache import update_cache, get_klines
  update_cache(["002028", "300502", "600160"])  # incremental update
  df = get_klines("002028", days=65)            # instant read
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "kline_cache.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_kline (
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            PRIMARY KEY (code, date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_code ON daily_kline(code)")
    conn.commit()
    return conn


def get_klines(code: str, days: int = 65):
    """Read cached K-lines as DataFrame. Returns None if insufficient data."""
    import pandas as pd

    conn = _connect()
    try:
        df = pd.read_sql_query(
            "SELECT date, open AS Open, high AS High, low AS Low, "
            "close AS Close, volume AS Volume "
            "FROM daily_kline WHERE code = ? ORDER BY date DESC LIMIT ?",
            conn, params=(code, days),
        )
        if df.empty or len(df) < 20:
            return None
        df = df.sort_values("date").reset_index(drop=True)
        for col in ("Open", "High", "Low", "Close", "Volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    finally:
        conn.close()


def _latest_cached(conn: sqlite3.Connection, code: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(date) FROM daily_kline WHERE code = ?", (code,)
    ).fetchone()
    return row[0] if row and row[0] else None


def _bs_code(code: str) -> str:
    return f"sh.{code}" if code.startswith(("6", "9")) else f"sz.{code}"


def _last_trading_day() -> str:
    """Estimate the last trading day (skip weekends, not holidays)."""
    now = datetime.now()
    # Before 15:30, today's data isn't final yet — use previous day
    if now.hour < 16:
        d = now - timedelta(days=1)
    else:
        d = now
    # Skip weekends
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def update_cache(codes: list[str], days: int = 65) -> dict[str, int]:
    """
    Incremental update via single baostock session.
    Skips baostock connection when cache is fresh (within 1 trading day).
    Returns {code: rows_inserted} for monitoring.
    """
    conn = _connect()
    today = datetime.now().strftime("%Y-%m-%d")
    last_td = _last_trading_day()
    default_start = (datetime.now() - timedelta(days=days + 20)).strftime("%Y-%m-%d")

    to_fetch: dict[str, str] = {}
    for code in codes:
        if code.startswith(("8", "4")) or code.startswith("92"):
            continue
        latest = _latest_cached(conn, code)
        if latest:
            if latest >= last_td:
                continue
            start = (datetime.strptime(latest, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            if start <= today:
                to_fetch[code] = start
        else:
            to_fetch[code] = default_start

    if not to_fetch:
        conn.close()
        return {}

    stats: dict[str, int] = {}
    try:
        import baostock as bs
        bs.login()

        for code, start in to_fetch.items():
            try:
                rs = bs.query_history_k_data_plus(
                    _bs_code(code),
                    "date,open,high,low,close,volume",
                    start_date=start, end_date=today,
                    frequency="d", adjustflag="2",
                )
                rows = []
                while rs.error_code == "0" and rs.next():
                    r = rs.get_row_data()
                    try:
                        rows.append((
                            code, r[0],
                            float(r[1]) if r[1] else None,
                            float(r[2]) if r[2] else None,
                            float(r[3]) if r[3] else None,
                            float(r[4]) if r[4] else None,
                            float(r[5]) if r[5] else None,
                        ))
                    except (ValueError, IndexError):
                        pass

                if rows:
                    conn.executemany(
                        "INSERT OR REPLACE INTO daily_kline "
                        "(code, date, open, high, low, close, volume) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        rows,
                    )
                    stats[code] = len(rows)
            except Exception:
                pass

        conn.commit()
        bs.logout()
    except Exception:
        pass
    finally:
        conn.close()

    return stats


def cache_stats() -> dict:
    conn = _connect()
    try:
        stocks = conn.execute("SELECT COUNT(DISTINCT code) FROM daily_kline").fetchone()[0]
        rows = conn.execute("SELECT COUNT(*) FROM daily_kline").fetchone()[0]
        latest = conn.execute("SELECT MAX(date) FROM daily_kline").fetchone()[0]
        size_mb = DB_PATH.stat().st_size / 1024 / 1024 if DB_PATH.exists() else 0
        return {"stocks": stocks, "rows": rows, "latest_date": latest, "size_mb": round(size_mb, 1)}
    finally:
        conn.close()


def prune(keep_days: int = 120) -> int:
    """Remove data older than keep_days."""
    conn = _connect()
    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    cursor = conn.execute("DELETE FROM daily_kline WHERE date < ?", (cutoff,))
    conn.commit()
    deleted = cursor.rowcount
    conn.execute("VACUUM")
    conn.close()
    return deleted


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        s = cache_stats()
        print(f"K-line cache: {s['stocks']} stocks, {s['rows']} rows, "
              f"latest={s['latest_date']}, size={s['size_mb']}MB")
    elif len(sys.argv) > 1 and sys.argv[1] == "prune":
        d = prune()
        print(f"Pruned {d} old rows")
    else:
        print("Usage: kline_cache.py stats|prune")
