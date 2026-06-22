# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40", "requests>=2.31", "akshare>=1.12.0"]
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

    # ⛔修复(06-16): 旧逻辑用 yf.download(period="2d") 批量取价为primary, 但该接口
    #   对部分票返回滞后收盘(NVDA/SOXL/MU/AMDL曾返回6/12 vs 真实6/15), 且"成功"即不
    #   走fast_info兜底 → 静默污染NAV(假跌$129K)。fast_info.last_price才是yf skill用
    #   的正确实时字段。修法: 美股持仓量小, 全部走fast_info(_fetch_single)为primary,
    #   保证取价新鲜; 批量download降级为fast_info失败时的fallback。
    failed = list(tickers)  # 全部走 _fetch_single (fast_info primary)
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


def _fetch_cn_push2delay_single(ticker: str) -> dict:
    """
    Fetch a single A-share price from push2delay.eastmoney.com (fallback source).
    Uses the single-stock endpoint (f43 = current price × 100).
    """
    import requests

    secid = f"1.{ticker}" if ticker.startswith("6") else f"0.{ticker}"
    url = (
        f"https://push2delay.eastmoney.com/api/qt/stock/get"
        f"?secid={secid}&fields=f43,f44,f45,f170"
    )
    now_ts = datetime.now(TZ_BEIJING).isoformat()
    try:
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        d = data.get("data") or {}
        raw_price = d.get("f43")
        raw_prev = d.get("f18") or d.get("f44")  # f18=prev_close in some endpoints; f44=open
        raw_pct = d.get("f170")  # change_pct × 10 in some fields

        if raw_price and raw_price > 0:
            price = round(raw_price / 100, 4)
            prev = round(raw_prev / 100, 4) if (raw_prev and raw_prev > 0) else price
            change_pct = round(raw_pct / 100, 2) if raw_pct is not None else (
                round((price / prev - 1) * 100, 2) if prev > 0 else 0.0
            )
            print(f"    [{ticker}] push2delay单股 OK: ¥{price}")
            return {
                "price": price,
                "prev_close": prev,
                "change_pct": change_pct,
                "source": "push2delay_single",
                "timestamp": now_ts,
            }
    except Exception as e:
        pass

    return {"price": None, "error": "push2delay single fetch failed", "timestamp": now_ts}


def _fetch_cn_tencent_batch(tickers: list[str]) -> dict[str, dict]:
    """A股批量实时价 — 腾讯qt.gtimg(不延迟)。2026-06-22加: push2delay滞后15分钟,
    盘中持仓/X1判断不能用延迟价。腾讯实时, 批量一次取。"""
    import urllib.request
    now_ts = datetime.now(TZ_BEIJING).isoformat()
    out: dict[str, dict] = {}
    try:
        codes = ','.join(('sh' if t.startswith('6') else ('bj' if t.startswith(('4', '8')) else 'sz')) + t for t in tickers)
        raw = urllib.request.urlopen('http://qt.gtimg.cn/q=' + codes, timeout=8).read().decode('gbk')
        for line in raw.strip().split('\n'):
            if '~' not in line:
                continue
            code = line.split('=', 1)[0].strip().replace('v_', '')[2:]
            f = line.split('~')
            if len(f) > 4 and f[3]:
                price = round(float(f[3]), 4)
                prev = round(float(f[4]), 4) if f[4] else None
                out[code] = {'price': price, 'prev_close': prev,
                             'change_pct': round((price / prev - 1) * 100, 2) if prev else 0.0,
                             'source': 'tencent_realtime', 'timestamp': now_ts}
    except Exception:
        pass
    return out


def fetch_cn_prices(tickers: list[str]) -> dict[str, dict]:
    """
    Fetch A-share prices.
    Source chain: 腾讯qt.gtimg实时(primary,不延迟) → Eastmoney push2delay批量 → push2delay单股。
    yfinance is deprecated for A-shares and is NOT used.
    Input should be bare 6-digit codes.
    Returns dict keyed by bare code (e.g. "002028", not "002028.SZ").
    """
    # 0. 腾讯实时 primary (push2delay滞后15分钟, 盘中不能用)
    results = _fetch_cn_tencent_batch(tickers)
    got = sum(1 for v in results.values() if v.get('price'))
    print(f"  [A股] 腾讯实时: {got} / {len(tickers)} 成功")
    failed_t = [t for t in tickers if results.get(t, {}).get('price') is None]
    if failed_t:
        results.update(_fetch_cn_eastmoney(failed_t))
        print(f"  [A股] 腾讯缺{len(failed_t)}只 → Eastmoney批量补")

    failed = [t for t in tickers if results.get(t, {}).get("price") is None]
    if failed:
        print(f"  [A股] Eastmoney批量失败 {len(failed)} 只，尝试push2delay单股...")
        for ticker in failed:
            data = _fetch_cn_push2delay_single(ticker)
            data.setdefault("source", "push2delay_single")
            results[ticker] = data
            if not data.get("price"):
                print(f"    [{ticker}] push2delay也失败: {data.get('error', 'no data')}")

    return results


def fetch_benchmark_prices() -> dict[str, dict]:
    """
    Fetch benchmark prices: CSI 300 via akshare (primary) → Eastmoney push2delay (fallback).
    SPY from yfinance (US benchmark, yfinance is correct source).
    Returns {"csi300": {"close": ..., "prev_close": ...}, "spy": {...}}.

    Source chain for CSI300 (A-stock data source rules):
      1. akshare index_zh_a_hist  — preferred A-stock source
      2. Eastmoney push2delay     — real-time fallback (intraday)
      yfinance is NOT used for CSI300 (deprecated for A-shares).
    """
    import requests

    result: dict[str, dict] = {}
    now_ts = datetime.now(TZ_BEIJING).isoformat()

    # ── CSI 300: akshare primary (A-stock preferred source) ──────────────────
    try:
        import akshare as ak
        from datetime import date

        today = date.today()
        start = (today - timedelta(days=7)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")
        df = ak.index_zh_a_hist(symbol="000300", period="daily", start_date=start, end_date=end)
        if df is not None and not df.empty:
            close = round(float(df["收盘"].iloc[-1]), 2)
            prev = round(float(df["收盘"].iloc[-2]), 2) if len(df) >= 2 else close
            change_pct = round((close / prev - 1) * 100, 2) if prev > 0 else 0.0
            result["csi300"] = {
                "close": close,
                "prev_close": prev,
                "change_pct": change_pct,
                "source": "akshare",
                "timestamp": now_ts,
            }
            print(f"  [CSI300] akshare primary OK: {close}")
    except Exception as e:
        print(f"  [CSI300] akshare primary failed: {e}, trying Eastmoney fallback...")

    # ── CSI 300: Eastmoney push2delay fallback (real-time, intraday) ─────────
    if not result.get("csi300", {}).get("close"):
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
                    "source": "eastmoney_fallback",
                    "timestamp": now_ts,
                }
                print(f"  [CSI300] Eastmoney fallback OK: {close}")
        except Exception as e:
            print(f"  [CSI300] Eastmoney fallback failed: {e}")

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
