#!/usr/bin/env python3
"""Step 1 for Gem 4: Fetch real CFFEX IF0 continuous + individual contract OHLCV
and sh000300 spot via Sina/AKShare (NO yfinance, strict D12).
Computes exact rollover-free same-contract returns & daily spot-futures basis.
"""
import os
for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[k] = "1"

import json
import time
import urllib.request
from pathlib import Path
import numpy as np
import pandas as pd
import akshare as ak

BASE = Path("/Users/huaichuaibeimeng/claude-projects")
OUT_DIR = BASE / "sim-portfolio/backtests_astock2/rd048_4small_gems_polish_integration_20261126/wave1b_gem2_gem4"
V3_RAW_PQ = BASE / "output/china_policy_macro_rd027_20261125/rd029_daybyday_etf/cache/v3_raw_panel_2016_20261125.parquet"
CORE4_ETF_PQ = BASE / "output/china_policy_macro_rd027_20261125/rd029_daybyday_etf/cache/core4_etfs_to_20261125.parquet"


def gen_if_contract_symbols(y_start=2020, y_end=2027):
    syms = []
    for y in range(y_start, y_end + 1):
        for m in range(1, 13):
            syms.append(f"IF{y % 100:02d}{m:02d}")
    return syms


def fetch_sina_hq_today():
    """Optionally check live/post-close Sina quote for CFF_RE_IF0 and sh000300."""
    url = "https://hq.sinajs.cn/list=CFF_RE_IF0,sh000300"
    req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            txt = resp.read().decode("gbk", errors="ignore")
    except Exception as e:
        return {"error": str(e)}
    out = {}
    for line in txt.strip().splitlines():
        if '="' not in line:
            continue
        k = line.split('="')[0].split("hq_str_")[-1]
        v = line.split('="')[1].rstrip('";').split(",")
        out[k] = v
    parsed = {}
    if "CFF_RE_IF0" in out and len(out["CFF_RE_IF0"]) >= 50:
        v = out["CFF_RE_IF0"]
        date_cand = next((x for x in v if len(x) == 10 and x.startswith("2026-")), None)
        parsed["IF0"] = {
            "date": date_cand,
            "open": float(v[0]),
            "high": float(v[1]),
            "low": float(v[2]),
            "close": float(v[3]),
            "volume": float(v[4]),
            "open_interest": float(v[6]) if len(v) > 6 and v[6] else np.nan,
        }
    if "sh000300" in out and len(out["sh000300"]) >= 32:
        v = out["sh000300"]
        date_cand = next((x for x in v if len(x) == 10 and x.startswith("2026-")), None)
        parsed["sh000300"] = {
            "date": date_cand,
            "open": float(v[1]),
            "prev_close": float(v[2]),
            "close": float(v[3]),
            "high": float(v[4]),
            "low": float(v[5]),
        }
    return parsed


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Fetch IF0 continuous via AKShare Sina
    df_if0 = ak.futures_main_sina(symbol="IF0")
    df_if0 = df_if0.rename(columns={
        "日期": "date",
        "开盘价": "open",
        "最高价": "high",
        "最低价": "low",
        "收盘价": "close",
        "成交量": "volume",
        "持仓量": "open_interest",
        "动态结算价": "settle",
    })
    df_if0["date"] = pd.to_datetime(df_if0["date"]).dt.strftime("%Y-%m-%d")
    for c in ["open", "high", "low", "close", "volume", "open_interest", "settle"]:
        df_if0[c] = pd.to_numeric(df_if0[c], errors="coerce")
    df_if0 = df_if0.sort_values("date").drop_duplicates("date").reset_index(drop=True)

    hq = fetch_sina_hq_today()

    # 2. Fetch sh000300 spot via AKShare Sina
    df_spot = ak.stock_zh_index_daily(symbol="sh000300")
    df_spot["date"] = pd.to_datetime(df_spot["date"]).dt.strftime("%Y-%m-%d")
    df_spot = df_spot.rename(columns={
        "open": "spot_open",
        "high": "spot_high",
        "low": "spot_low",
        "close": "spot_close",
        "volume": "spot_volume",
    })
    df_spot = df_spot.sort_values("date").drop_duplicates("date").reset_index(drop=True)

    # 3. Cross-check against v3_raw_panel_2016_20261125.parquet
    v3_raw = pd.read_parquet(V3_RAW_PQ, columns=["date", "c300_open", "c300_high", "c300_low", "c300_close", "IF0_close", "IF0_vol"])
    v3_raw["date"] = pd.to_datetime(v3_raw["date"]).dt.strftime("%Y-%m-%d")
    chk = df_if0.merge(v3_raw, on="date", how="inner").merge(df_spot, on="date", how="inner")
    if0_diff = (chk["close"] - chk["IF0_close"]).abs()
    c300_diff = (chk["spot_close"] - chk["c300_close"]).abs()

    # 4. Fetch individual IF contracts for 2020-10 .. 2027-03 to detect exact rollovers & rollover-free returns
    contracts = {}
    fetch_ok, fetch_err = [], []
    for sym in gen_if_contract_symbols(2020, 2027):
        try:
            dc = ak.futures_zh_daily_sina(symbol=sym)
            if dc is not None and len(dc) > 0:
                dc["date"] = pd.to_datetime(dc["date"]).dt.strftime("%Y-%m-%d")
                for col in ["open", "high", "low", "close", "volume", "hold"]:
                    dc[col] = pd.to_numeric(dc[col], errors="coerce")
                dc = dc.sort_values("date").drop_duplicates("date").reset_index(drop=True)
                contracts[sym] = dc.set_index("date")
                fetch_ok.append(sym)
        except Exception as e:
            fetch_err.append((sym, str(e)[:60]))

    dom_contract = {}
    for i, dt in enumerate(df_if0["date"]):
        if dt < "2020-11-01":
            dom_contract[dt] = None
            continue
        if0_c = df_if0.loc[i, "close"]
        if0_v = df_if0.loc[i, "volume"]
        if0_h = df_if0.loc[i, "open_interest"]
        best_sym = None
        best_err = 1e18
        for sym, cdf in contracts.items():
            if dt in cdf.index:
                r = cdf.loc[dt]
                err = abs(float(r["close"]) - float(if0_c)) * 1000.0 + abs(float(r["volume"]) - float(if0_v)) * 0.01 + abs(float(r["hold"]) - float(if0_h)) * 0.001
                if err < best_err:
                    best_err = err
                    best_sym = sym
        if best_sym is not None and abs(float(contracts[best_sym].loc[dt, "close"]) - float(if0_c)) <= 1.0:
            dom_contract[dt] = best_sym
        else:
            dom_contract[dt] = None

    df_if0["dom_contract"] = df_if0["date"].map(dom_contract)
    prev_dom = df_if0["dom_contract"].shift(1)
    df_if0["is_roll_day"] = (df_if0["dom_contract"].notna()) & (prev_dom.notna()) & (df_if0["dom_contract"] != prev_dom)

    true_prev_c = []
    old_t_open, old_t_high, old_t_low, old_t_close = [], [], [], []
    roll_jump_pts = []
    for i in range(len(df_if0)):
        dt = df_if0.loc[i, "date"]
        cur = df_if0.loc[i, "dom_contract"]
        prv = df_if0.loc[i - 1, "dom_contract"] if i > 0 else None
        p_dt = df_if0.loc[i - 1, "date"] if i > 0 else None
        p_c = np.nan
        oo, oh, ol, oc = np.nan, np.nan, np.nan, np.nan
        rjp = 0.0
        if i > 0 and cur is not None and cur in contracts and p_dt in contracts[cur].index:
            p_c = float(contracts[cur].loc[p_dt, "close"])
            if prv is not None and prv != cur and prv in contracts:
                old_prev_c = float(df_if0.loc[i - 1, "close"])
                rjp = p_c - old_prev_c
                if dt in contracts[prv].index:
                    r_old = contracts[prv].loc[dt]
                    oo = float(r_old["open"])
                    oh = float(r_old["high"])
                    ol = float(r_old["low"])
                    oc = float(r_old["close"])
        else:
            p_c = float(df_if0.loc[i - 1, "close"]) if i > 0 else np.nan
        true_prev_c.append(p_c)
        old_t_open.append(oo)
        old_t_high.append(oh)
        old_t_low.append(ol)
        old_t_close.append(oc)
        roll_jump_pts.append(rjp)

    df_if0["same_contract_prev_close"] = true_prev_c
    df_if0["old_contract_open"] = old_t_open
    df_if0["old_contract_high"] = old_t_high
    df_if0["old_contract_low"] = old_t_low
    df_if0["old_contract_close"] = old_t_close
    df_if0["roll_jump_pts"] = roll_jump_pts
    df_if0["roll_jump_pct"] = df_if0["roll_jump_pts"] / df_if0["close"].shift(1) * 100.0

    df_if0["naive_cc_ret"] = df_if0["close"] / df_if0["close"].shift(1) - 1.0
    df_if0["true_cc_ret"] = df_if0["close"] / df_if0["same_contract_prev_close"] - 1.0
    df_if0["true_oc_ret"] = df_if0["close"] / df_if0["open"] - 1.0
    df_if0["true_co_ret"] = df_if0["open"] / df_if0["same_contract_prev_close"] - 1.0
    df_if0["true_low_ret_from_prev_c"] = df_if0["low"] / df_if0["same_contract_prev_close"] - 1.0
    df_if0["true_low_ret_from_open"] = df_if0["low"] / df_if0["open"] - 1.0
    df_if0["true_high_ret_from_prev_c"] = df_if0["high"] / df_if0["same_contract_prev_close"] - 1.0

    df = df_if0.merge(df_spot, on="date", how="left")
    df["spot_cc_ret"] = df["spot_close"] / df["spot_close"].shift(1) - 1.0
    df["spot_oc_ret"] = df["spot_close"] / df["spot_open"] - 1.0
    df["spot_low_ret_from_prev_c"] = df["spot_low"] / df["spot_close"].shift(1) - 1.0
    df["basis_pts"] = df["close"] - df["spot_close"]
    df["basis_pct"] = (df["close"] / df["spot_close"] - 1.0) * 100.0

    etf = pd.read_parquet(CORE4_ETF_PQ)
    etf300 = etf[etf["code"] == "510300"][["date", "open", "high", "low", "close", "open_hfq", "high_hfq", "low_hfq", "close_hfq"]].copy()
    etf300["date"] = pd.to_datetime(etf300["date"]).dt.strftime("%Y-%m-%d")
    etf300 = etf300.rename(columns={c: f"etf_510300_{c}" for c in etf300.columns if c != "date"})
    df = df.merge(etf300, on="date", how="left")

    cache_pq = OUT_DIR / "if_continuous_daily_cache.parquet"
    df.to_parquet(cache_pq, index=False)

    sub21 = df[(df["date"] >= "2021-01-04") & (df["date"] <= "2026-11-25")].copy()
    rolls = sub21[sub21["is_roll_day"]].copy()
    rolls["abs_roll_jump_pct"] = rolls["roll_jump_pct"].abs()
    top_rolls = rolls.sort_values("abs_roll_jump_pct", ascending=False).head(10)[
        ["date", "dom_contract", "close", "same_contract_prev_close", "roll_jump_pts", "roll_jump_pct", "naive_cc_ret", "true_cc_ret"]
    ].to_dict(orient="records")

    audit = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "d12_yfinance_imported": False,
        "source": "akshare.futures_main_sina('IF0') + akshare.futures_zh_daily_sina('IFYYMM') + akshare.stock_zh_index_daily('sh000300')",
        "if0_full_rows": int(len(df)),
        "if0_date_range": [str(df["date"].min()), str(df["date"].max())],
        "individual_contracts_fetched": len(fetch_ok),
        "individual_contracts_failed_sample": fetch_err[:5],
        "sub_2021_2026_rows": int(len(sub21)),
        "sub_2021_2026_unmatched_contract_days": int(sub21["dom_contract"].isna().sum()),
        "parity_vs_v3_raw_panel": {
            "overlap_rows": int(len(chk)),
            "if0_close_max_abs_diff": float(if0_diff.max()),
            "spot_c300_close_max_abs_diff": float(c300_diff.max()),
        },
        "basis_2021_2026": {
            "mean_pts": round(float(sub21["basis_pts"].mean()), 3),
            "median_pts": round(float(sub21["basis_pts"].median()), 3),
            "mean_pct": round(float(sub21["basis_pct"].mean()), 4),
            "min_pct": round(float(sub21["basis_pct"].min()), 4),
            "max_pct": round(float(sub21["basis_pct"].max()), 4),
            "discount_days_pct": round(float((sub21["basis_pts"] < 0).mean() * 100.0), 2),
        },
        "rollover_2021_2026": {
            "roll_count": int(len(rolls)),
            "mean_roll_jump_pts": round(float(rolls["roll_jump_pts"].mean()), 3),
            "mean_abs_roll_jump_pct": round(float(rolls["abs_roll_jump_pct"].mean()), 4),
            "max_abs_roll_jump_pct": round(float(rolls["abs_roll_jump_pct"].max()), 4),
            "note": "Rollover days switch IF0 to next contract; naive IF0[t]/IF0[t-1]-1 mixes two contracts by roll_jump_pct. Backtest uses rollover-free true_cc_ret / true_low_ret_from_prev_c plus explicit roll slippage when holding across a rollover.",
            "top10_roll_jumps": top_rolls,
        },
        "sina_hq_20261126_snapshot": hq,
        "cache_parquet": str(cache_pq),
    }
    audit_path = OUT_DIR / "if_data_audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    print("DONE step1_build_if_cache in", audit["elapsed_sec"], "s")
    print("IF0 range:", audit["if0_date_range"], "unmatched:", audit["sub_2021_2026_unmatched_contract_days"])
    print("Parity IF0 diff:", audit["parity_vs_v3_raw_panel"]["if0_close_max_abs_diff"], "c300 diff:", audit["parity_vs_v3_raw_panel"]["spot_c300_close_max_abs_diff"])
    print("Basis 2021-2026:", audit["basis_2021_2026"])
    print("Rollovers:", audit["rollover_2021_2026"]["roll_count"], "max abs jump pct:", audit["rollover_2021_2026"]["max_abs_roll_jump_pct"])


if __name__ == "__main__":
    main()
