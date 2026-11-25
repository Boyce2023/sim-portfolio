#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Cached, fault-tolerant data fetcher for RD027 (Pillar 1 Waterpool & Pillar 4 Macro Pain).
All downloads are persisted into raw_cache/ with resume support and status logging.
"""
import json
import os
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")
os.environ["NO_PROXY"] = "*"

import akshare as ak
import pandas as pd
import pyarrow.parquet as pq

BASE_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_CACHE_DIR = os.path.join(BASE_SCRIPT_DIR, "raw_cache")
os.makedirs(RAW_CACHE_DIR, exist_ok=True)

ROOT = "/Users/huaichuaibeimeng/claude-projects"
CN_DB_DIR = os.path.join(ROOT, "sim-portfolio/data/cn_hk_price_db")


def _norm_df_for_parquet(df: pd.DataFrame) -> pd.DataFrame:
    """Convert date/object columns cleanly so pyarrow writes reliably."""
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == "object":
            # Keep numeric if possible, else string (preserving NaN/None)
            s_str = out[c].astype(str).where(out[c].notna(), None)
            out[c] = s_str
    return out


def fetch_simple_table(name: str, fn, kwargs: dict, status: dict, refresh: bool = False, retries: int = 3) -> pd.DataFrame:
    """Fetch a single akshare endpoint with disk cache and retry."""
    p = os.path.join(RAW_CACHE_DIR, f"{name}.parquet")
    if os.path.exists(p) and not refresh:
        df = pd.read_parquet(p)
        status[name] = {"ok": True, "cached": True, "rows": int(len(df))}
        return df

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            t0 = time.time()
            df = fn(**kwargs)
            if df is None or len(df) == 0:
                raise ValueError("empty dataframe")
            out = _norm_df_for_parquet(df)
            out.to_parquet(p, index=False)
            status[name] = {"ok": True, "cached": False, "rows": int(len(out)), "sec": round(time.time() - t0, 2)}
            print(f"  [OK] {name}: {len(out)} rows ({status[name]['sec']}s)")
            return out
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:180]}"
            time.sleep(1.0 * attempt)

    status[name] = {"ok": False, "error": last_err, "rows": 0}
    print(f"  [FAIL] {name}: {last_err}")
    return pd.DataFrame()


def fetch_dividends_all(status: dict, refresh: bool = False) -> pd.DataFrame:
    """Fetch semi-annual cash dividend plans 2004-12-31 to 2026-06-30 via stock_fhps_em."""
    p = os.path.join(RAW_CACHE_DIR, "stock_fhps_em_all.parquet")
    if os.path.exists(p) and not refresh:
        df = pd.read_parquet(p)
        status["stock_fhps_em_all"] = {"ok": True, "cached": True, "rows": int(len(df))}
        return df

    periods = ["20041231"]
    for y in range(2005, 2026):
        periods.append(f"{y}0630")
        periods.append(f"{y}1231")
    periods.append("20260630")

    def _one(dt_str: str):
        for attempt in range(1, 4):
            try:
                d = ak.stock_fhps_em(date=dt_str)
                if d is not None and len(d) > 0:
                    d = d.copy()
                    d["report_period"] = dt_str
                    return d, None
                return pd.DataFrame(), None
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:100]}"
                time.sleep(0.5 * attempt)
        return pd.DataFrame(), (dt_str, err)

    t0 = time.time()
    frames, failed = [], []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_one, pdt): pdt for pdt in periods}
        for fut in as_completed(futs):
            d, err = fut.result()
            if not d.empty:
                frames.append(d)
            if err is not None:
                failed.append(err)

    if frames:
        out = _norm_df_for_parquet(pd.concat(frames, ignore_index=True))
        out.to_parquet(p, index=False)
        status["stock_fhps_em_all"] = {
            "ok": True, "cached": False, "rows": int(len(out)),
            "periods_ok": len(frames), "periods_total": len(periods),
            "failed_periods": failed, "sec": round(time.time() - t0, 2),
        }
        print(f"  [OK] stock_fhps_em_all: {len(out)} rows across {len(frames)}/{len(periods)} periods ({status['stock_fhps_em_all']['sec']}s)")
        return out

    status["stock_fhps_em_all"] = {"ok": False, "error": str(failed[:5]), "rows": 0}
    print("  [FAIL] stock_fhps_em_all")
    return pd.DataFrame()


def fetch_ipo_2005_2009_cninfo(xgsglb_df: pd.DataFrame, status: dict, refresh: bool = False) -> pd.DataFrame:
    """Fetch 2005-2009 IPO details via stock_ipo_summary_cninfo for tickers whose first trade date is 2005-2009."""
    p = os.path.join(RAW_CACHE_DIR, "ipo_2005_2009_cninfo.parquet")
    if os.path.exists(p) and not refresh:
        df = pd.read_parquet(p)
        status["ipo_2005_2009_cninfo"] = {"ok": True, "cached": True, "rows": int(len(df))}
        return df

    a1 = pq.read_table(os.path.join(CN_DB_DIR, "a_daily.parquet"), columns=["date", "ticker"]).to_pandas()
    a2 = pq.read_table(os.path.join(CN_DB_DIR, "a_delisted_daily.parquet"), columns=["date", "ticker"]).to_pandas()
    all_dt = pd.concat([a1, a2], ignore_index=True)
    first_dt = all_dt.groupby("ticker")["date"].min()
    cand = first_dt[(first_dt >= pd.Timestamp("2005-01-01")) & (first_dt <= pd.Timestamp("2009-12-31"))].index.tolist()
    existing_codes = set(xgsglb_df["股票代码"].astype(str).str.zfill(6)) if not xgsglb_df.empty else set()
    codes = sorted({t.split(".")[0].zfill(6) for t in cand if t.split(".")[0].zfill(6) not in existing_codes})

    def _one(code: str):
        for attempt in range(1, 3):
            try:
                d = ak.stock_ipo_summary_cninfo(symbol=code)
                if d is not None and len(d) > 0:
                    return d, None
            except Exception as e:
                time.sleep(0.3 * attempt)
        return pd.DataFrame(), code

    t0 = time.time()
    frames, failed = [], []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(_one, c) for c in codes]
        for fut in as_completed(futs):
            d, fail_c = fut.result()
            if not d.empty:
                frames.append(d)
            if fail_c is not None:
                failed.append(fail_c)

    if frames:
        out = _norm_df_for_parquet(pd.concat(frames, ignore_index=True))
        out.to_parquet(p, index=False)
        status["ipo_2005_2009_cninfo"] = {
            "ok": True, "cached": False, "rows": int(len(out)),
            "target_codes": len(codes), "failed_count": len(failed),
            "sec": round(time.time() - t0, 2),
        }
        print(f"  [OK] ipo_2005_2009_cninfo: {len(out)}/{len(codes)} tickers ({status['ipo_2005_2009_cninfo']['sec']}s)")
        return out

    status["ipo_2005_2009_cninfo"] = {"ok": False, "error": "no rows", "rows": 0}
    return pd.DataFrame()


def fetch_all(refresh: bool = False) -> dict:
    """Download and cache all macro and waterpool sources."""
    status = {}
    endpoints = [
        # Pillar 4 China macro
        ("macro_china_supply_of_money", ak.macro_china_supply_of_money, {}),
        ("macro_china_money_supply", ak.macro_china_money_supply, {}),
        ("macro_china_shrzgm", ak.macro_china_shrzgm, {}),
        ("macro_china_new_financial_credit", ak.macro_china_new_financial_credit, {}),
        ("macro_china_pmi_yearly", ak.macro_china_pmi_yearly, {}),
        ("macro_china_pmi", ak.macro_china_pmi, {}),
        ("macro_china_non_man_pmi", ak.macro_china_non_man_pmi, {}),
        ("macro_china_cpi_yearly", ak.macro_china_cpi_yearly, {}),
        ("macro_china_cpi", ak.macro_china_cpi, {}),
        ("macro_china_ppi_yearly", ak.macro_china_ppi_yearly, {}),
        ("macro_china_ppi", ak.macro_china_ppi, {}),
        ("macro_china_lpr", ak.macro_china_lpr, {}),
        ("macro_china_gdp", ak.macro_china_gdp, {}),
        ("macro_china_real_estate", ak.macro_china_real_estate, {}),
        ("macro_china_fx_gold", ak.macro_china_fx_gold, {}),
        ("macro_china_gyzjz", ak.macro_china_gyzjz, {}),
        ("macro_china_industrial_production_yoy", ak.macro_china_industrial_production_yoy, {}),
        ("macro_china_consumer_goods_retail", ak.macro_china_consumer_goods_retail, {}),
        ("macro_china_gdzctz", ak.macro_china_gdzctz, {}),
        ("macro_china_czsr", ak.macro_china_czsr, {}),
        ("macro_china_hgjck", ak.macro_china_hgjck, {}),
        ("macro_china_xfzxx", ak.macro_china_xfzxx, {}),
        ("macro_china_central_bank_balance", ak.macro_china_central_bank_balance, {}),
        ("macro_china_stock_market_cap", ak.macro_china_stock_market_cap, {}),
        ("bond_zh_us_rate", ak.bond_zh_us_rate, {}),
        ("currency_boc_safe", ak.currency_boc_safe, {}),
        # Pillar 1 waterpool & valuation
        ("stock_margin_account_info", ak.stock_margin_account_info, {}),
        ("macro_china_market_margin_sh", ak.macro_china_market_margin_sh, {}),
        ("macro_china_market_margin_sz", ak.macro_china_market_margin_sz, {}),
        ("stock_xgsglb_em", ak.stock_xgsglb_em, {"symbol": "全部股票"}),
        ("stock_qbzf_em", ak.stock_qbzf_em, {}),
        ("stock_repurchase_em", ak.stock_repurchase_em, {}),
        ("stock_dzjy_sctj", ak.stock_dzjy_sctj, {}),
        ("stock_hsgt_hist_em", ak.stock_hsgt_hist_em, {"symbol": "北向资金"}),
        ("stock_a_ttm_lyr", ak.stock_a_ttm_lyr, {}),
        ("stock_a_all_pb", ak.stock_a_all_pb, {}),
        ("stock_index_pe_lg", ak.stock_index_pe_lg, {"symbol": "沪深300"}),
        ("stock_index_pb_lg", ak.stock_index_pb_lg, {"symbol": "沪深300"}),
        ("stock_ggcg_em", ak.stock_ggcg_em, {"symbol": "全部"}),
    ]

    data = {}
    for name, fn, kw in endpoints:
        data[name] = fetch_simple_table(name, fn, kw, status, refresh=refresh)

    data["stock_fhps_em_all"] = fetch_dividends_all(status, refresh=refresh)
    data["ipo_2005_2009_cninfo"] = fetch_ipo_2005_2009_cninfo(data.get("stock_xgsglb_em", pd.DataFrame()), status, refresh=refresh)

    with open(os.path.join(RAW_CACHE_DIR, "fetch_status.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    return data, status


if __name__ == "__main__":
    _, st = fetch_all(refresh=False)
    ok_cnt = sum(1 for v in st.values() if v.get("ok"))
    print(f"Fetch complete: {ok_cnt}/{len(st)} endpoints succeeded.")
