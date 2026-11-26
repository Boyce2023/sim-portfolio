#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD042 Step 0: Fetch & Cache Full BSE (北交所 30cm) Daily History (2021-11-15 .. 2026-11-25).
Uses BSE official stock list + Sina daily bars (`ak.stock_zh_a_daily`, trust_env=False).
Zero yfinance (D12). Internal threads <= 2. Cross-checks against local `bj_daily.parquet`.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

# Bypass broken local macOS proxy 127.0.0.1:1082 cleanly
_orig_session_init = requests.Session.__init__


def _no_env_init(self, *args, **kwargs):
    _orig_session_init(self, *args, **kwargs)
    self.trust_env = False


requests.Session.__init__ = _no_env_init

import akshare as ak  # noqa: E402

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd042_bse30cm_subnew_20261126"
LOCAL_BJ_PQ = f"{ROOT}/sim-portfolio/data/cn_hk_price_db/bj_daily.parquet"
CACHE_PQ = f"{OUT_DIR}/bse_30cm_daily_cache.parquet"
AUDIT_JSON = f"{OUT_DIR}/bse_cache_audit.json"
os.makedirs(OUT_DIR, exist_ok=True)


def fetch_bse_official_universe() -> pd.DataFrame:
    """Fetch official current BSE stock list from www.bse.cn (357 stocks)."""
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "Referer": "https://www.bse.cn/"})
    r0 = s.post("https://www.bse.cn/nqxxController/nqxxCnzq.do", data={"page": "0", "typejb": "T", "xxfcbj[]": "2"}, timeout=12)
    j0 = json.loads(r0.text[5:-1] if r0.text.startswith("null(") else r0.text)[0]
    total_pages = int(j0["totalPages"])
    rows = list(j0["content"])
    for p in range(1, total_pages):
        for att in range(5):
            try:
                time.sleep(0.18)
                rp = s.post("https://www.bse.cn/nqxxController/nqxxCnzq.do", data={"page": str(p), "typejb": "T", "xxfcbj[]": "2"}, timeout=12)
                jp = json.loads(rp.text[5:-1] if rp.text.startswith("null(") else rp.text)[0]
                rows.extend(jp["content"])
                break
            except Exception:
                time.sleep(0.8 * (att + 1))
        else:
            raise RuntimeError(f"Failed fetching BSE universe page {p}")
    df = pd.DataFrame(rows)
    df["c6"] = df["xxzqdm"].astype(str).str.zfill(6)
    df["name"] = df["xxzqjc"].astype(str).str.strip()
    df["list_date"] = pd.to_datetime(df["fxssrq"].astype(str), errors="coerce").dt.strftime("%Y-%m-%d")
    df["industry_bse"] = df.get("xxhyzl", pd.Series("", index=df.index)).astype(str).str.strip()
    return df[["c6", "name", "list_date", "industry_bse"]].drop_duplicates("c6").sort_values("c6").reset_index(drop=True)


def _fetch_one_stock(row_dict: dict) -> tuple[str, pd.DataFrame | None, str | None]:
    c6 = row_dict["c6"]
    sym = f"bj{c6}"
    for att in range(3):
        try:
            df = ak.stock_zh_a_daily(symbol=sym, start_date="20211115", end_date="20261125", adjust="")
            if df is None or df.empty:
                return c6, None, "empty_bars"
            df = df.copy()
            df["dt"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df[(df["dt"] >= "2021-11-15") & (df["dt"] <= "2026-11-25")].copy()
            if df.empty:
                return c6, None, "empty_in_range"
            try:
                qf = ak.stock_zh_a_daily(symbol=sym, adjust="qfq-factor")
                qf["dt"] = pd.to_datetime(qf["date"]).dt.strftime("%Y-%m-%d")
                qf["qfq_factor"] = pd.to_numeric(qf["qfq_factor"], errors="coerce")
                qf = qf[["dt", "qfq_factor"]].dropna().drop_duplicates("dt").sort_values("dt")
                df = df.sort_values("dt")
                df = pd.merge_asof(df, qf, on="dt", direction="forward", allow_exact_matches=True)
                # Note: Sina qfq_factor table stores factor for dates <= ex_date (or >= ex_date? Let's verify! Wait: in stock_zh_a_daily it uses outer merge + ffill!)
            except Exception:
                df["qfq_factor"] = 1.0
            return c6, df, None
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:80]}"
            time.sleep(0.5 * (att + 1))
    return c6, None, err


def _fetch_one_stock_exact_qfq(row_dict: dict) -> tuple[str, pd.DataFrame | None, str | None]:
    """Match ak.stock_zh_a_daily exact outer-merge + ffill qfq_factor logic cleanly without rounding adj_close."""
    c6 = row_dict["c6"]
    sym = f"bj{c6}"
    for att in range(3):
        try:
            df = ak.stock_zh_a_daily(symbol=sym, start_date="20211115", end_date="20261125", adjust="")
            if df is None or df.empty:
                return c6, None, "empty_bars"
            df = df.copy()
            df["dt"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df[(df["dt"] >= "2021-11-15") & (df["dt"] <= "2026-11-25")].drop_duplicates("dt").sort_values("dt").reset_index(drop=True)
            if df.empty:
                return c6, None, "empty_in_range"

            qfq_map_df = None
            try:
                qf = ak.stock_zh_a_daily(symbol=sym, adjust="qfq-factor")
                qf["dt"] = pd.to_datetime(qf["date"]).dt.strftime("%Y-%m-%d")
                qf["qfq_factor"] = pd.to_numeric(qf["qfq_factor"], errors="coerce")
                qfq_map_df = qf[["dt", "qfq_factor"]].dropna().drop_duplicates("dt").sort_values("dt")
            except Exception:
                qfq_map_df = None

            if qfq_map_df is not None and not qfq_map_df.empty:
                # Replicate ak.stock_zh_a_daily exact ffill alignment on full union of dates
                all_d = pd.DataFrame({"dt": sorted(set(df["dt"]) | set(qfq_map_df["dt"]))})
                all_d = all_d.merge(qfq_map_df, on="dt", how="left").sort_values("dt")
                all_d["qfq_factor"] = all_d["qfq_factor"].ffill().bfill().fillna(1.0)
                df = df.merge(all_d, on="dt", how="left")
            else:
                df["qfq_factor"] = 1.0

            df["qfq_factor"] = pd.to_numeric(df["qfq_factor"], errors="coerce").fillna(1.0)
            df["adj_factor"] = (1.0 / df["qfq_factor"].replace(0, 1.0)).astype(np.float64)
            df["adj_close"] = (df["close"].astype(np.float64) * df["adj_factor"]).astype(np.float64)
            df["c6"] = c6
            df["name"] = row_dict["name"]
            df["list_date"] = row_dict["list_date"]
            df["industry_bse"] = row_dict["industry_bse"]
            return c6, df, None
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:100]}"
            time.sleep(0.5 * (att + 1))
    return c6, None, err


def main():
    t0 = time.time()
    uni = fetch_bse_official_universe()
    print(f"[Step0] BSE official universe: {len(uni)} stocks (list_date {uni['list_date'].min()} .. {uni['list_date'].max()})", flush=True)

    rows_ok, errs = [], {}
    recs = uni.to_dict("records")
    with ThreadPoolExecutor(max_workers=2) as ex:
        for i, (c6, df_s, err) in enumerate(ex.map(_fetch_one_stock_exact_qfq, recs), 1):
            if df_s is not None and not df_s.empty:
                rows_ok.append(df_s)
            else:
                errs[c6] = err
            if i % 60 == 0 or i == len(recs):
                print(f"   fetched {i}/{len(recs)} ok={len(rows_ok)} err={len(errs)} ({time.time()-t0:.1f}s)", flush=True)

    full = pd.concat(rows_ok, ignore_index=True)
    full = full.rename(columns={"outstanding_share": "oshare", "turnover": "turn"})
    full["amount_yi"] = (full["amount"].astype(np.float64) / 1e8).astype(np.float32)
    full["turn_pct"] = (full["turn"].astype(np.float64) * 100.0).astype(np.float32)
    for c in ("open", "high", "low", "close", "adj_close", "adj_factor", "qfq_factor"):
        full[c] = full[c].astype(np.float64)
    for c in ("volume", "amount", "oshare", "turn"):
        full[c] = full[c].astype(np.float64)
    full = full.sort_values(["c6", "dt"]).drop_duplicates(["c6", "dt"]).reset_index(drop=True)

    # Cross-check overlap against local bj_daily.parquet
    bj_loc = pd.read_parquet(LOCAL_BJ_PQ)
    bj_loc["c6"] = bj_loc["ticker"].astype(str).str[:6]
    bj_loc["dt"] = bj_loc["date"].dt.strftime("%Y-%m-%d")
    bj_loc = bj_loc[bj_loc["dt"] >= "2021-11-15"].copy()
    ov = full.merge(bj_loc[["c6", "dt", "close", "adj_close", "amount"]], on=["c6", "dt"], suffixes=("_new", "_loc"))
    max_close_diff = float(np.max(np.abs(ov["close_new"] - ov["close_loc"]))) if len(ov) else -1.0
    max_amt_rel_diff = float(np.max(np.abs(ov["amount_new"] - ov["amount_loc"]) / np.maximum(1.0, ov["amount_loc"]))) if len(ov) else -1.0
    # Check adj_close ratio stability on 2024..2026
    med_adj_diff = float(np.median(np.abs(ov["adj_close_new"] - ov["adj_close_loc"]))) if len(ov) else -1.0

    keep_cols = [
        "c6", "dt", "name", "list_date", "industry_bse",
        "open", "high", "low", "close", "adj_close", "adj_factor", "qfq_factor",
        "volume", "amount", "amount_yi", "oshare", "turn", "turn_pct",
    ]
    full = full[keep_cols].copy()
    full.to_parquet(CACHE_PQ, index=False, compression="snappy")

    pre_924 = full[full["dt"] < "2024-09-24"]
    post_924 = full[full["dt"] >= "2024-09-24"]
    audit = {
        "cache_file": CACHE_PQ,
        "official_bse_count": int(len(uni)),
        "fetched_tickers": int(full["c6"].nunique()),
        "failed_tickers": errs,
        "missing_delisted_or_transferred_known": [
            {"code": "920680", "name": "广道退", "status": "delisted_fraud_2025_2026"},
            {"code": "920305", "name": "云创退", "status": "delisted_fraud_2026"},
            {"code": "832317", "name": "观典防务", "status": "transferred_to_688287_2022"},
            {"code": "833874", "name": "泰祥股份", "status": "transferred_to_301192_2022"},
            {"code": "833994", "name": "翰博高新", "status": "transferred_to_301321_2022"},
        ],
        "survivor_bias_note": "Upward survivor bias: covers 357/362 (98.6%) BSE tickers; excludes 2 fraud-delisted stocks (920680, 920305) and 3 early 2022 board transfers.",
        "rows_total": int(len(full)),
        "dt_min": str(full["dt"].min()),
        "dt_max": str(full["dt"].max()),
        "overlap_vs_local_bj_rows": int(len(ov)),
        "overlap_max_close_diff": round(max_close_diff, 6),
        "overlap_max_amount_rel_diff": round(max_amt_rel_diff, 6),
        "overlap_med_adj_close_diff": round(med_adj_diff, 6),
        "pre_924_rows": int(len(pre_924)),
        "pre_924_med_amt_wan": round(float(pre_924["amount"].median() / 1e4), 2),
        "post_924_rows": int(len(post_924)),
        "post_924_med_amt_wan": round(float(post_924["amount"].median() / 1e4), 2),
        "elapsed_sec": round(time.time() - t0, 2),
    }
    with open(AUDIT_JSON, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
