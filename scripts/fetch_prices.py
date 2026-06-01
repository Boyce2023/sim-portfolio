# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40", "requests>=2.31"]
# ///
"""
Fetch latest prices for portfolio holdings.
Used by remote agent and other scripts via import.

Usage:
  uv run --script scripts/fetch_prices.py
  python scripts/fetch_prices.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yfinance as yf

# ─── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PORTFOLIO_PATH = REPO_ROOT / "portfolio_state.json"
PRICES_OUTPUT = REPO_ROOT / "latest_prices.json"

TZ_BEIJING = timezone(timedelta(hours=8))

# ─── Ticker Mappings ──────────────────────────────────────────────────────────
# OTC / special tickers that need remapping for yfinance
YF_TICKER_MAP: dict[str, str] = {
    "SPUT": "SRUUF",    # Sprott Uranium Trust trades OTC as SRUUF
    "BATT": "BATT",     # keep as-is if already correct
}


def normalize_us_ticker(ticker: str) -> str:
    """Apply ticker remapping for yfinance compatibility."""
    return YF_TICKER_MAP.get(ticker.upper(), ticker.upper())


def cn_ticker_to_yf(ticker: str) -> str:
    """Convert 6-digit A-share code to yfinance format."""
    if ticker.startswith("6"):
        return ticker + ".SS"
    return ticker + ".SZ"  # 0xxxx / 3xxxx → Shenzhen


# ─── Price Fetch with Retry ───────────────────────────────────────────────────

def _fetch_single(yf_ticker: str, retries: int = 3, delay: float = 1.5) -> dict:
    """
    Fetch a single ticker from yfinance with retry + history fallback.
    Returns dict with keys: price, prev_close, change_pct, timestamp.
    On failure returns dict with error key and price=None.
    """
    last_error = ""
    for attempt in range(retries):
        try:
            t = yf.Ticker(yf_ticker)
            info = t.fast_info
            last_price = info.last_price
            prev_close = info.previous_close

            # Fallback: use history if fast_info returns None
            if last_price is None or last_price <= 0:
                hist = t.history(period="2d", auto_adjust=True)
                if not hist.empty:
                    last_price = float(hist["Close"].iloc[-1])
                    if len(hist) >= 2:
                        prev_close = float(hist["Close"].iloc[-2])
                    else:
                        prev_close = last_price

            if last_price is None or last_price <= 0:
                last_error = "no valid price returned"
                if attempt < retries - 1:
                    time.sleep(delay)
                continue

            price = round(float(last_price), 4)
            prev = round(float(prev_close), 4) if (prev_close and prev_close > 0) else price
            change_pct = round((price / prev - 1) * 100, 2) if prev > 0 else None

            return {
                "price": price,
                "prev_close": prev,
                "change_pct": change_pct,
                "timestamp": datetime.now(TZ_BEIJING).isoformat(),
            }

        except Exception as e:
            last_error = str(e)
            if attempt < retries - 1:
                time.sleep(delay)

    return {
        "price": None,
        "error": last_error,
        "timestamp": datetime.now(TZ_BEIJING).isoformat(),
    }


# ─── Public API ───────────────────────────────────────────────────────────────

def fetch_us_prices(tickers: list[str]) -> dict[str, dict]:
    """
    Fetch US stock prices via batch download + individual fallback.
    Returns dict keyed by ORIGINAL ticker symbol.
    """
    if not tickers:
        return {}

    ticker_map = {t: normalize_us_ticker(t) for t in tickers}
    yf_syms = list(dict.fromkeys(ticker_map.values()))
    now_ts = datetime.now(TZ_BEIJING).isoformat()

    results: dict[str, dict] = {}
    batch_ok: set[str] = set()

    try:
        df = yf.download(yf_syms, period="2d", group_by="ticker", progress=False, threads=True)
        for orig, yf_sym in ticker_map.items():
            try:
                col = df[yf_sym] if len(yf_syms) > 1 else df
                closes = col["Close"].dropna()
                if len(closes) == 0:
                    continue
                price = round(float(closes.iloc[-1]), 4)
                prev = round(float(closes.iloc[-2]), 4) if len(closes) >= 2 else price
                change_pct = round((price / prev - 1) * 100, 2) if prev > 0 else 0
                entry = {
                    "price": price,
                    "prev_close": prev,
                    "change_pct": change_pct,
                    "timestamp": now_ts,
                }
                if orig != yf_sym:
                    entry["yf_symbol"] = yf_sym
                results[orig] = entry
                batch_ok.add(orig)
            except Exception:
                pass
    except Exception:
        pass

    failed = [t for t in tickers if t not in batch_ok]
    if failed:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _fallback(ticker: str) -> tuple[str, dict]:
            yf_sym = ticker_map[ticker]
            data = _fetch_single(yf_sym)
            if ticker != yf_sym:
                data["yf_symbol"] = yf_sym
            return ticker, data

        with ThreadPoolExecutor(max_workers=min(len(failed), 8)) as pool:
            for fut in as_completed(pool.submit(_fallback, t) for t in failed):
                ticker, data = fut.result()
                results[ticker] = data

    return results


def _cn_secid(ticker: str) -> str:
    """Convert bare A-share code to Eastmoney secid format (1.6xxxxx for SH, 0.others for SZ)."""
    if ticker.startswith("6"):
        return f"1.{ticker}"
    return f"0.{ticker}"


def _fetch_cn_eastmoney(tickers: list[str]) -> dict[str, dict]:
    """
    Fetch A-share prices from Eastmoney push2delay API (primary source).
    Uses push2delay.eastmoney.com HTTPS — works even when VPN blocks push2.eastmoney.com.
    """
    import requests

    secids = ",".join(_cn_secid(t) for t in tickers)
    url = (
        "https://push2delay.eastmoney.com/api/qt/ulist.np/get"
        "?ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2"
        f"&fields=f2,f3,f4,f12,f14,f17,f18&secids={secids}"
    )
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {t: {"price": None, "error": f"eastmoney request failed: {e}"} for t in tickers}

    if data.get("rc") != 0 or not data.get("data", {}).get("diff"):
        return {t: {"price": None, "error": "eastmoney returned empty data"} for t in tickers}

    results: dict[str, dict] = {}
    em_by_code = {}
    for item in data["data"]["diff"]:
        code = str(item.get("f12", ""))
        em_by_code[code] = item

    now_ts = datetime.now(TZ_BEIJING).isoformat()
    for ticker in tickers:
        item = em_by_code.get(ticker)
        if not item or item.get("f2") in (None, "-"):
            results[ticker] = {"price": None, "error": "no data from eastmoney", "timestamp": now_ts}
            continue
        price = float(item["f2"])
        prev_close = float(item["f18"]) if item.get("f18") not in (None, "-") else price
        change_pct = float(item["f3"]) if item.get("f3") not in (None, "-") else 0.0
        results[ticker] = {
            "price": round(price, 4),
            "prev_close": round(prev_close, 4),
            "change_pct": round(change_pct, 2),
            "source": "eastmoney",
            "timestamp": now_ts,
        }
    return results


def fetch_cn_prices(tickers: list[str]) -> dict[str, dict]:
    """
    Fetch A-share prices. Primary: Eastmoney API. Fallback: yfinance.
    Input should be bare 6-digit codes.
    Returns dict keyed by bare code (e.g. "002028", not "002028.SZ").
    """
    results = _fetch_cn_eastmoney(tickers)

    failed = [t for t in tickers if results.get(t, {}).get("price") is None]
    if failed:
        for ticker in failed:
            yf_sym = cn_ticker_to_yf(ticker)
            data = _fetch_single(yf_sym)
            data["yf_symbol"] = yf_sym
            data["source"] = "yfinance_fallback"
            results[ticker] = data

    return results


def fetch_benchmark_prices() -> dict[str, dict]:
    """
    Fetch benchmark prices: CSI 300 from Eastmoney, SPY from yfinance.
    Returns {"csi300": {"close": ..., "prev_close": ...}, "spy": {...}}.
    """
    import requests

    result: dict[str, dict] = {}
    now_ts = datetime.now(TZ_BEIJING).isoformat()

    # CSI 300: Eastmoney primary, yfinance fallback
    try:
        url = (
            "https://push2delay.eastmoney.com/api/qt/ulist.np/get"
            "?ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2"
            "&fields=f2,f3,f4,f12,f14,f17,f18&secids=1.000300"
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("rc") == 0 and data.get("data", {}).get("diff"):
            item = data["data"]["diff"][0]
            close = float(item["f2"])
            prev = float(item["f18"]) if item.get("f18") not in (None, "-") else close
            result["csi300"] = {
                "close": round(close, 2),
                "prev_close": round(prev, 2),
                "change_pct": round(float(item.get("f3", 0)), 2),
                "source": "eastmoney",
                "timestamp": now_ts,
            }
    except Exception:
        pass

    if not result.get("csi300", {}).get("close"):
        csi_data = _fetch_single("000300.SS")
        if csi_data.get("price"):
            result["csi300"] = {
                "close": csi_data["price"],
                "prev_close": csi_data.get("prev_close", csi_data["price"]),
                "change_pct": csi_data.get("change_pct", 0),
                "source": "yfinance_fallback",
                "timestamp": now_ts,
            }

    # SPY via yfinance
    try:
        spy_data = _fetch_single("SPY")
        if spy_data.get("price"):
            result["spy"] = {
                "close": spy_data["price"],
                "prev_close": spy_data.get("prev_close", spy_data["price"]),
                "change_pct": spy_data.get("change_pct", 0),
                "source": "yfinance",
                "timestamp": now_ts,
            }
        else:
            result["spy"] = {"close": None, "error": spy_data.get("error", "no data")}
    except Exception as e:
        result["spy"] = {"close": None, "error": str(e)}

    return result


def fetch_all_from_portfolio(state: dict) -> dict:
    """
    Fetch prices for all positions in portfolio_state dict.
    Returns {"us": {...}, "cn": {...}, "fetched_at": "..."}.
    """
    us_tickers = [
        p["ticker"]
        for p in state["accounts"]["us"]["positions"]
        if p.get("instrument_type") != "call_option"
    ]
    cn_tickers = [
        p["ticker"]
        for p in state["accounts"]["a_share"]["positions"]
    ]

    us_prices = fetch_us_prices(us_tickers)
    cn_prices = fetch_cn_prices(cn_tickers)

    return {
        "us": us_prices,
        "cn": cn_prices,
        "fetched_at": datetime.now(TZ_BEIJING).isoformat(),
    }


# ─── Atomic Save ──────────────────────────────────────────────────────────────

def save_prices_atomic(data: dict, path: Path) -> None:
    """Write prices JSON atomically (tmp → rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".prices_tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> int:
    if not PORTFOLIO_PATH.exists():
        print(f"[ERROR] portfolio_state.json not found at {PORTFOLIO_PATH}", file=sys.stderr)
        return 1

    try:
        with open(PORTFOLIO_PATH, encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to load portfolio_state.json: {e}", file=sys.stderr)
        return 1

    print("=== 获取美股价格 ===")
    us_tickers = [
        p["ticker"]
        for p in state["accounts"]["us"]["positions"]
        if p.get("instrument_type") != "call_option"
    ]
    us_prices = fetch_us_prices(us_tickers)
    for ticker, d in us_prices.items():
        yf_sym = d.get("yf_symbol", ticker)
        sym_info = f" (yf: {yf_sym})" if yf_sym != ticker else ""
        if d.get("price"):
            chg = d.get("change_pct")
            chg_str = f" ({chg:+.2f}%)" if chg is not None else ""
            print(f"  {ticker}{sym_info}: ${d['price']}{chg_str}")
        else:
            print(f"  {ticker}{sym_info}: ERROR — {d.get('error', 'no data')}")

    print("\n=== 获取A股价格 ===")
    cn_tickers = [p["ticker"] for p in state["accounts"]["a_share"]["positions"]]
    cn_prices = fetch_cn_prices(cn_tickers)
    for ticker, d in cn_prices.items():
        if d.get("price"):
            chg = d.get("change_pct")
            chg_str = f" ({chg:+.2f}%)" if chg is not None else ""
            print(f"  {ticker}: ¥{d['price']}{chg_str}")
        else:
            print(f"  {ticker}: ERROR — {d.get('error', 'no data')}")

    # Save output
    all_prices = {
        "us": us_prices,
        "cn": cn_prices,
        "fetched_at": datetime.now(TZ_BEIJING).isoformat(),
    }
    try:
        save_prices_atomic(all_prices, PRICES_OUTPUT)
        print(f"\n[OK] 价格已保存到 {PRICES_OUTPUT}")
    except Exception as e:
        print(f"[ERROR] 保存价格失败: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
