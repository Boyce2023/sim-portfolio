# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40", "akshare>=1.12.0", "requests>=2.31"]
# ///
"""
maintain_truth.py — Nexus Truth Store 日常维护
在 daily_run.sh 中于 update_prices 之后、decision_engine 之前调用。

5个任务:
1. refresh_macro()    — yf拉宏观指标 → indicators.json
2. update_regime()    — 规则判定regime → regime.json
3. expire_signals()   — 过期信号 pending/ → processed/
4. rebuild_index()    — 扫companies/实际文件 → _index.json
5. sync_positions()   — portfolio_state.json → truth/portfolio/positions.json
"""

import json
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
NEXUS_DIR = Path.home() / ".claude" / "nexus"
TRUTH_DIR = NEXUS_DIR / "truth"
SIGNALS_DIR = NEXUS_DIR / "signals"

BJT = timezone(timedelta(hours=8))
NOW = datetime.now(BJT)
TODAY_STR = NOW.strftime("%Y-%m-%d")

# US/global macro tickers — fetched via yfinance (correct source for US data)
MACRO_TICKERS = {
    "macro-01": {"entity": "VIX", "ticker": "^VIX", "unit": "points"},
    "macro-02": {"entity": "DXY", "ticker": "DX-Y.NYB", "unit": "index"},
    "macro-03": {"entity": "US10Y", "ticker": "^TNX", "unit": "%"},
    "macro-04": {"entity": "US2Y", "ticker": "2YY=F", "unit": "%"},
    "macro-05": {"entity": "SPX", "ticker": "^GSPC", "unit": "points"},
    "macro-06": {"entity": "IXIC", "ticker": "^IXIC", "unit": "points"},
    "macro-07": {"entity": "BTC-USD", "ticker": "BTC-USD", "unit": "USD"},
    "macro-08": {"entity": "GC=F", "ticker": "GC=F", "unit": "USD/oz"},
    "macro-09": {"entity": "CL=F", "ticker": "CL=F", "unit": "USD/bbl"},
    "macro-10": {"entity": "NG=F", "ticker": "NG=F", "unit": "USD/MMBtu"},
    "macro-11": {"entity": "HG=F", "ticker": "HG=F", "unit": "USD/lb"},
    "macro-12": {"entity": "UX-SPOT", "ticker": "SRUUF", "unit": "CAD/unit"},
    "macro-13": {"entity": "URA", "ticker": "URA", "unit": "USD"},
    "macro-14": {"entity": "CCJ", "ticker": "CCJ", "unit": "USD"},
    "macro-15": {"entity": "SRUUF", "ticker": "SRUUF", "unit": "USD"},
}

# A-stock macro indicators — fetched via akshare (A-stock preferred source; yfinance deprecated)
ASTOCK_MACRO = {
    "macro-a01": {"entity": "CSI300", "symbol": "000300", "unit": "points"},
}


def atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(path)


def fetch_price(ticker: str) -> float | None:
    """Fetch price via yfinance. For US/global instruments only."""
    try:
        t = yf.Ticker(ticker)
        price = t.fast_info.get("lastPrice")
        if price and price > 0:
            return round(float(price), 4)
        hist = t.history(period="2d")
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 4)
    except Exception:
        pass
    return None


def fetch_astock_index_price(symbol: str) -> tuple[float | None, str]:
    """
    Fetch A-stock index price via akshare (preferred source for A-stock data).
    Falls back to push2delay Eastmoney if akshare fails.
    Returns (price, source_name).
    yfinance is NOT used for A-stock indices.
    """
    from datetime import date, timedelta

    # Primary: akshare
    try:
        import akshare as ak
        today = date.today()
        start = (today - timedelta(days=7)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")
        df = ak.index_zh_a_hist(symbol=symbol, period="daily", start_date=start, end_date=end)
        if df is not None and not df.empty:
            price = round(float(df["收盘"].iloc[-1]), 2)
            print(f"  [A股宏观] {symbol} akshare primary OK: {price}")
            return price, "akshare"
    except Exception as e:
        print(f"  [A股宏观] {symbol} akshare failed: {e}, trying Eastmoney fallback...")

    # Fallback: push2delay Eastmoney
    try:
        import requests
        secid = f"1.{symbol}" if symbol.startswith("6") else f"0.{symbol}"
        url = (
            "https://push2delay.eastmoney.com/api/qt/ulist.np/get"
            "?ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2"
            f"&fields=f2,f3,f12,f18&secids={secid}"
        )
        resp = requests.get(url, timeout=8)
        data = resp.json()
        if data.get("rc") == 0 and data.get("data", {}).get("diff"):
            item = data["data"]["diff"][0]
            raw = item.get("f2")
            if raw and raw != "-":
                price = round(float(raw), 2)
                print(f"  [A股宏观] {symbol} Eastmoney fallback OK: {price}")
                return price, "eastmoney_fallback"
    except Exception as e:
        print(f"  [A股宏观] {symbol} Eastmoney fallback failed: {e}")

    return None, "failed"


# ─── Task 1: Refresh Macro Indicators ───────────────────────────────────────

def refresh_macro() -> dict:
    indicators_path = TRUTH_DIR / "macro" / "indicators.json"
    try:
        existing = json.loads(indicators_path.read_text())
    except Exception:
        existing = {"metadata": {}, "indicators": []}

    updated_count = 0
    indicators = []

    # US/global indicators via yfinance
    for macro_id, info in MACRO_TICKERS.items():
        price = fetch_price(info["ticker"])
        entry = {
            "id": macro_id,
            "entity": info["entity"],
            "value": price,
            "unit": info["unit"],
            "source": "yfinance",
            "source_date": TODAY_STR,
            "confidence": "high" if price else "low",
        }
        if price:
            updated_count += 1
        indicators.append(entry)
        print(f"  [macro] {info['entity']} (yfinance): {price or 'FAILED'}")

    # A-stock indicators via akshare (yfinance deprecated for A-shares)
    for macro_id, info in ASTOCK_MACRO.items():
        price, source = fetch_astock_index_price(info["symbol"])
        entry = {
            "id": macro_id,
            "entity": info["entity"],
            "value": price,
            "unit": info["unit"],
            "source": source,
            "source_date": TODAY_STR,
            "confidence": "high" if price else "low",
        }
        if price:
            updated_count += 1
        indicators.append(entry)

    total = len(MACRO_TICKERS) + len(ASTOCK_MACRO)
    result = {
        "metadata": {
            "description": "宏观指标 Truth Store",
            "last_updated": NOW.isoformat(),
            "update_source": "maintain_truth.py",
            "indicators_refreshed": updated_count,
            "indicators_total": total,
            "source_note": "US/global via yfinance; A-stock indices via akshare→Eastmoney fallback",
        },
        "indicators": indicators,
    }

    indicators_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(indicators_path, result)
    print(f"[macro] {updated_count}/{total} indicators refreshed")
    return result


# ─── Task 2: Update Regime ──────────────────────────────────────────────────

def update_regime(indicators: dict) -> None:
    regime_path = TRUTH_DIR / "macro" / "regime.json"

    idx = {i["entity"]: i["value"] for i in indicators.get("indicators", []) if i["value"]}

    vix = idx.get("VIX")
    us10y = idx.get("US10Y")
    us2y = idx.get("US2Y")
    dxy = idx.get("DXY")

    spread = (us10y - us2y) if (us10y and us2y) else None

    # Rule-based regime detection
    if vix and vix > 30:
        regime = "bear"
        reasoning = f"VIX={vix:.1f} > 30 触发Bear"
    elif spread is not None and spread < -0.5:
        regime = "bear"
        reasoning = f"10Y-2Y spread={spread:.3f}% 深度倒挂"
    elif vix and vix < 20 and spread is not None and spread > 0:
        regime = "bull"
        reasoning = f"VIX={vix:.1f}<20 且 spread={spread:.3f}%>0"
    else:
        regime = "sideways"
        parts = []
        if vix:
            parts.append(f"VIX={vix:.1f}")
        if spread is not None:
            parts.append(f"spread={spread:.3f}%")
        if dxy:
            parts.append(f"DXY={dxy:.1f}")
        reasoning = f"综合判定Sideways ({', '.join(parts)})"

    confidence = 0.8 if (vix and spread is not None) else 0.5

    result = {
        "metadata": {
            "description": "市场Regime Detection — 规则层(VIX+Spread+DXY)",
            "schema_version": "2.0",
            "last_updated": NOW.isoformat(),
            "update_source": "maintain_truth.py",
        },
        "regime_definition": {
            "bull": {"equity_pct_range": [0.85, 1.30], "cash_pct_range": [0, 0.15]},
            "sideways": {"equity_pct_range": [0.70, 1.00], "cash_pct_range": [0, 0.30]},
            "bear": {"equity_pct_range": [0.40, 0.70], "cash_pct_range": [0.30, 0.60]},
        },
        "current_regime": {
            "regime": regime,
            "confidence": confidence,
            "since_date": TODAY_STR,
            "source": "maintain_truth.py v2.0 — rule_layer_only",
            "reasoning": reasoning,
        },
        "signals_snapshot": {
            "vix": {"value": vix, "signal": "normal" if (vix and vix < 20) else "elevated" if (vix and vix < 30) else "extreme" if vix else "unavailable", "as_of": TODAY_STR},
            "spread_10y2y": {"value": spread, "signal": "bull" if (spread and spread > 0) else "bear" if (spread and spread < -0.5) else "neutral" if spread is not None else "unavailable", "as_of": TODAY_STR},
            "dxy": {"value": dxy, "signal": "strong" if (dxy and dxy > 105) else "weak" if (dxy and dxy < 95) else "neutral" if dxy else "unavailable", "as_of": TODAY_STR},
        },
        "stale_after_days": 3,
    }

    atomic_write_json(regime_path, result)
    print(f"[regime] {regime} (confidence={confidence}, {reasoning})")


# ─── Task 3: Expire Signals ─────────────────────────────────────────────────

def expire_signals() -> None:
    pending_dir = SIGNALS_DIR / "pending"
    processed_dir = SIGNALS_DIR / "processed"

    if not pending_dir.exists():
        return

    processed_dir.mkdir(parents=True, exist_ok=True)
    expired_count = 0

    for f in pending_dir.glob("sig-*.json"):
        try:
            sig = json.loads(f.read_text())
            expires_str = sig.get("expires_at", "")
            if not expires_str:
                continue
            expires = datetime.fromisoformat(expires_str)
            if NOW > expires:
                sig["_expired_at"] = NOW.isoformat()
                sig["_status"] = "expired"
                dest = processed_dir / f.name
                dest.write_text(json.dumps(sig, indent=2, ensure_ascii=False))
                f.unlink()
                expired_count += 1
        except Exception as e:
            print(f"  [warn] 处理 {f.name} 出错: {e}")

    print(f"[signals] {expired_count} expired signals moved to processed/")


# ─── Task 4: Rebuild Index ──────────────────────────────────────────────────

def rebuild_index() -> None:
    index_path = TRUTH_DIR / "_index.json"
    companies_dir = TRUTH_DIR / "companies"

    files = []
    total_facts = 0
    verified_count = 0
    high_confidence_count = 0

    # Scan companies/
    if companies_dir.exists():
        for f in sorted(companies_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                facts = data.get("facts", [])
                n_facts = len(facts)
                n_verified = sum(1 for fact in facts if fact.get("verified"))
                n_high = sum(1 for fact in facts if fact.get("confidence") == "high")
                files.append({
                    "path": f"companies/{f.name}",
                    "fact_count": n_facts,
                    "verified": n_verified,
                    "high_confidence": n_high,
                })
                total_facts += n_facts
                verified_count += n_verified
                high_confidence_count += n_high
            except Exception:
                files.append({"path": f"companies/{f.name}", "fact_count": 0, "verified": 0, "high_confidence": 0})

    # Scan other truth files
    for subdir in ["macro", "portfolio", "personal"]:
        sub_path = TRUTH_DIR / subdir
        if sub_path.exists():
            for f in sorted(sub_path.glob("*.json")):
                try:
                    data = json.loads(f.read_text())
                    if "indicators" in data:
                        n = len(data["indicators"])
                    elif "facts" in data:
                        n = len(data["facts"])
                    elif "positions" in data:
                        n = len(data.get("positions", []))
                    else:
                        n = len([k for k in data.keys() if not k.startswith("_") and k != "metadata"])
                    files.append({"path": f"{subdir}/{f.name}", "fact_count": n})
                    total_facts += n
                except Exception:
                    pass

    result = {
        "generated_at": NOW.isoformat(),
        "generated_by": "maintain_truth.py",
        "total_facts": total_facts,
        "verified_count": verified_count,
        "high_confidence_count": high_confidence_count,
        "files": files,
    }

    atomic_write_json(index_path, result)
    print(f"[index] rebuilt: {len(files)} files, {total_facts} facts")


# ─── Task 5: Sync Positions ─────────────────────────────────────────────────

def sync_positions() -> None:
    state_path = REPO_ROOT / "portfolio_state.json"
    positions_path = TRUTH_DIR / "portfolio" / "positions.json"

    if not state_path.exists():
        print("[positions] portfolio_state.json not found, skipping")
        return

    try:
        state = json.loads(state_path.read_text())
    except Exception as e:
        print(f"[positions] failed to read portfolio_state.json: {e}")
        return

    positions = []
    for acct_key in ("a_share", "us"):
        acct = state.get("accounts", {}).get(acct_key, {})
        for pos in acct.get("positions", []):
            positions.append({
                "ticker": pos.get("ticker"),
                "name": pos.get("name"),
                "account": acct_key,
                "shares": pos.get("shares"),
                "avg_cost": pos.get("avg_cost"),
                "current_price": pos.get("current_price"),
                "market_value": pos.get("market_value"),
                "unrealized_pnl_pct": pos.get("unrealized_pnl_pct"),
                "conviction_level": pos.get("conviction_level"),
                "stop_loss": pos.get("stop_loss"),
                "entry_date": pos.get("entry_date"),
            })

    result = {
        "metadata": {
            "description": "持仓快照 — 从portfolio_state.json同步",
            "last_synced": NOW.isoformat(),
            "source": "sim-portfolio/portfolio_state.json",
            "sync_by": "maintain_truth.py",
            "ssot_note": "此文件为只读参考层，SSOT是portfolio_state.json",
        },
        "summary": {
            "a_share": {
                "cash": state.get("accounts", {}).get("a_share", {}).get("cash"),
                "total_assets": state.get("accounts", {}).get("a_share", {}).get("total_assets"),
                "position_count": len([p for p in positions if p["account"] == "a_share"]),
            },
            "us": {
                "cash": state.get("accounts", {}).get("us", {}).get("cash"),
                "total_assets": state.get("accounts", {}).get("us", {}).get("total_assets"),
                "position_count": len([p for p in positions if p["account"] == "us"]),
            },
        },
        "positions": positions,
    }

    positions_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(positions_path, result)
    print(f"[positions] synced {len(positions)} positions from portfolio_state.json")


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    print(f"=== maintain_truth.py === {NOW.strftime('%Y-%m-%d %H:%M %Z')}")

    # 1. Refresh macro
    try:
        indicators = refresh_macro()
    except Exception as e:
        print(f"[ERROR] refresh_macro failed: {e}")
        indicators = {"indicators": []}

    # 2. Update regime
    try:
        update_regime(indicators)
    except Exception as e:
        print(f"[ERROR] update_regime failed: {e}")

    # 3. Expire signals
    try:
        expire_signals()
    except Exception as e:
        print(f"[ERROR] expire_signals failed: {e}")

    # 4. Rebuild index
    try:
        rebuild_index()
    except Exception as e:
        print(f"[ERROR] rebuild_index failed: {e}")

    # 5. Sync positions
    try:
        sync_positions()
    except Exception as e:
        print(f"[ERROR] sync_positions failed: {e}")

    print("=== maintain_truth.py done ===")


if __name__ == "__main__":
    main()
