#!/usr/bin/env python3
"""
generate_w1d_01_sectors.py
Builds w1d_01_official_sector_etf_zero_survivorship_30y.csv
Calculates official SPDR and sub-industry ETF 1998-2026 returns, risk metrics,
crisis drawdowns, and compares directly with naive survivor stock baskets from all_daily.parquet
to quantify survivorship bias inflation (water squeeze).
"""

import os
import json
import numpy as np
import pandas as pd

# Paths
OUTPUT_DIR = "/Users/huaichuaibeimeng/claude-projects/output/us_quant_value_scorecard_30y_20261115/lab_w1d_survivorship_clean_30y"
SECTORS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/sectors"
BENCHMARKS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/benchmarks"
ALL_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/all_daily.parquet"
XBRL_MASTER_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/data/xbrl_master_pit_2009_2026.parquet"
FIN_META_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_jump_tracker_cache/financials_meta.json"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# 1. Load SPY Benchmark
spy_df = pd.read_parquet(os.path.join(BENCHMARKS_DIR, "SPY.parquet"))
if isinstance(spy_df.index, pd.DatetimeIndex):
    spy_df = spy_df.reset_index()
if "date" not in spy_df.columns and "index" in spy_df.columns:
    spy_df.rename(columns={"index": "date"}, inplace=True)
spy_df["date"] = pd.to_datetime(spy_df["date"]).dt.tz_localize(None).dt.normalize()
spy_df = spy_df.sort_values("date").drop_duplicates("date").set_index("date")

# Helper for crisis drawdowns
CRISES = {
    "mdd_2000_dotcom": ("2000-03-24", "2002-10-09"),
    "mdd_2008_gfc": ("2007-10-09", "2009-03-09"),
    "mdd_2020_covid": ("2020-02-19", "2020-03-23"),
    "mdd_2022_hike": ("2022-01-03", "2022-10-12"),
}

def calc_mdd_window(series, start_d, end_d):
    sub = series.loc[start_d:end_d]
    if len(sub) < 5:
        return np.nan
    cum = sub / sub.iloc[0]
    dd = (cum - cum.cummax()) / cum.cummax()
    return float(dd.min())

# List of ETFs to process
ETF_METADATA = [
    # SPDR Sector ETFs
    ("XLK", "Technology Select Sector SPDR", "Sector_SPDR", "Technology"),
    ("XLV", "Health Care Select Sector SPDR", "Sector_SPDR", "Health Care"),
    ("XLF", "Financial Select Sector SPDR", "Sector_SPDR", "Financials"),
    ("XLI", "Industrial Select Sector SPDR", "Sector_SPDR", "Industrials"),
    ("XLY", "Consumer Discretionary Select Sector SPDR", "Sector_SPDR", "Consumer Discretionary"),
    ("XLP", "Consumer Staples Select Sector SPDR", "Sector_SPDR", "Consumer Staples"),
    ("XLE", "Energy Select Sector SPDR", "Sector_SPDR", "Energy"),
    ("XLU", "Utilities Select Sector SPDR", "Sector_SPDR", "Utilities"),
    ("XLB", "Materials Select Sector SPDR", "Sector_SPDR", "Materials"),
    ("XLRE", "Real Estate Select Sector SPDR", "Sector_SPDR", "Real Estate"),
    ("XLC", "Communication Services Select Sector SPDR", "Sector_SPDR", "Communication Services"),
    # Sub-industry / Factor ETFs
    ("SMH", "VanEck Semiconductor ETF", "SubIndustry_Leader", "Technology"),
    ("IGV", "iShares Expanded Tech-Software Sector ETF", "SubIndustry_Leader", "Technology"),
    ("XBI", "SPDR S&P Biotech ETF", "SubIndustry_Leader", "Health Care"),
    ("ITA", "iShares U.S. Aerospace & Defense ETF", "SubIndustry_Leader", "Industrials"),
    ("KBE", "SPDR S&P Bank ETF", "SubIndustry_Leader", "Financials"),
    ("XME", "SPDR S&P Metals & Mining ETF", "SubIndustry_Leader", "Materials"),
    ("XOP", "SPDR S&P Oil & Gas Exploration & Production ETF", "SubIndustry_Leader", "Energy"),
    ("VNQ", "Vanguard Real Estate ETF", "SubIndustry_Leader", "Real Estate"),
    ("IYT", "iShares Transportation Average ETF", "SubIndustry_Leader", "Industrials"),
    ("GDX", "VanEck Gold Miners ETF", "SubIndustry_Leader", "Materials"),
    # Key Benchmarks
    ("SPY", "SPDR S&P 500 ETF Trust", "Benchmark_Market", "Broad Market"),
    ("QQQ", "Invesco QQQ Trust (Nasdaq 100)", "Benchmark_Market", "Large Growth"),
    ("DIA", "SPDR Dow Jones Industrial Average ETF", "Benchmark_Market", "Large Value/Core"),
    ("IWM", "iShares Russell 2000 ETF", "Benchmark_Market", "Small Cap"),
]

# Load sector mapping for all_daily survivor comparison
df_xbrl = pd.read_parquet(XBRL_MASTER_PATH, columns=["ticker", "sector"])
sec_map = df_xbrl.dropna(subset=["sector"]).drop_duplicates("ticker").set_index("ticker")["sector"].to_dict()

with open(FIN_META_PATH) as f:
    d_fin = json.load(f)
for k, v in d_fin.items():
    if k not in sec_map and v.get("sector"):
        sec_map[k] = v["sector"]

def norm_to_etf(s):
    if not isinstance(s, str):
        return None
    s = s.lower()
    if any(x in s for x in ["tech", "information", "semiconductor"]):
        return "XLK"
    if any(x in s for x in ["health", "medical", "pharma", "biotech"]):
        return "XLV"
    if any(x in s for x in ["finan", "bank", "insurance"]):
        return "XLF"
    if any(x in s for x in ["industr", "aerospace", "machinery"]):
        return "XLI"
    if any(x in s for x in ["discretionary", "retail", "consumer cycl"]):
        return "XLY"
    if any(x in s for x in ["staple", "food", "beverage"]):
        return "XLP"
    if any(x in s for x in ["energy", "oil", "gas"]):
        return "XLE"
    if "utilit" in s:
        return "XLU"
    if any(x in s for x in ["material", "metal", "chemical"]):
        return "XLB"
    if any(x in s for x in ["real estate", "reit"]):
        return "XLRE"
    if any(x in s for x in ["communication", "telecom", "media"]):
        return "XLC"
    return None

mapped_etf = {k: norm_to_etf(v) for k, v in sec_map.items()}

# Load all_daily for survivor calculations
print("Loading all_daily for survivor stock basket computation...")
df_daily = pd.read_parquet(ALL_DAILY_PATH, columns=["date", "ticker", "adj_close"])
df_daily["date"] = pd.to_datetime(df_daily["date"]).dt.tz_localize(None).dt.normalize()
df_daily["etf"] = df_daily["ticker"].map(mapped_etf)
df_daily = df_daily.sort_values(["ticker", "date"])
df_daily["ret"] = df_daily.groupby("ticker")["adj_close"].pct_change()

# Compute results
results = []
rf_annual = 0.02 # 2% long-term risk free cash benchmark

for sym, name, cat, sector_family in ETF_METADATA:
    p = os.path.join(SECTORS_DIR, f"{sym}.parquet")
    if not os.path.exists(p):
        p = os.path.join(BENCHMARKS_DIR, f"{sym}.parquet")
    
    if not os.path.exists(p):
        print(f"Skipping {sym}, not found.")
        continue
    
    df = pd.read_parquet(p)
    if isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
    if "date" not in df.columns and "index" in df.columns:
        df.rename(columns={"index": "date"}, inplace=True)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df.sort_values("date").drop_duplicates("date").set_index("date")
    
    # Align with SPY
    overlap_idx = spy_df.index.intersection(df.index)
    if len(overlap_idx) < 100:
        continue
    
    p_etf = df.loc[overlap_idx, "adj_close"]
    p_spy = spy_df.loc[overlap_idx, "adj_close"]
    
    start_dt = overlap_idx[0].strftime("%Y-%m-%d")
    end_dt = overlap_idx[-1].strftime("%Y-%m-%d")
    n_days = len(overlap_idx)
    years = n_days / 252.0
    
    # Official ETF metrics
    tot_ret = float(p_etf.iloc[-1] / p_etf.iloc[0] - 1.0)
    cagr = float((p_etf.iloc[-1] / p_etf.iloc[0]) ** (1.0 / years) - 1.0)
    
    ret_daily = p_etf.pct_change().dropna()
    vol = float(ret_daily.std() * np.sqrt(252))
    sharpe = float((cagr - rf_annual) / vol) if vol > 0 else np.nan
    
    cum = p_etf / p_etf.iloc[0]
    dd_series = (cum - cum.cummax()) / cum.cummax()
    max_dd = float(dd_series.min())
    calmar = float(cagr / abs(max_dd)) if abs(max_dd) > 0 else np.nan
    
    # SPY over identical period
    spy_cagr = float((p_spy.iloc[-1] / p_spy.iloc[0]) ** (1.0 / years) - 1.0)
    excess_cagr_vs_spy = float(cagr - spy_cagr)
    
    # Crisis drawdowns
    mdd_dotcom = calc_mdd_window(p_etf, CRISES["mdd_2000_dotcom"][0], CRISES["mdd_2000_dotcom"][1])
    mdd_gfc = calc_mdd_window(p_etf, CRISES["mdd_2008_gfc"][0], CRISES["mdd_2008_gfc"][1])
    mdd_covid = calc_mdd_window(p_etf, CRISES["mdd_2020_covid"][0], CRISES["mdd_2020_covid"][1])
    mdd_hike = calc_mdd_window(p_etf, CRISES["mdd_2022_hike"][0], CRISES["mdd_2022_hike"][1])
    
    # SPY crisis drawdowns for reference
    spy_mdd_dotcom = calc_mdd_window(p_spy, CRISES["mdd_2000_dotcom"][0], CRISES["mdd_2000_dotcom"][1])
    spy_mdd_gfc = calc_mdd_window(p_spy, CRISES["mdd_2008_gfc"][0], CRISES["mdd_2008_gfc"][1])
    spy_mdd_covid = calc_mdd_window(p_spy, CRISES["mdd_2020_covid"][0], CRISES["mdd_2020_covid"][1])
    spy_mdd_hike = calc_mdd_window(p_spy, CRISES["mdd_2022_hike"][0], CRISES["mdd_2022_hike"][1])

    # 1998-2008 sub-period analysis (the critical pre-XBRL / lost decade era)
    p_etf_lost_dec = p_etf.loc["1998-12-22":"2008-12-31"] if "1998-12-22" in p_etf.index or len(p_etf.loc[:"2008-12-31"]) > 100 else pd.Series(dtype=float)
    if len(p_etf_lost_dec) > 100:
        etf_lost_dec_cagr = float((p_etf_lost_dec.iloc[-1] / p_etf_lost_dec.iloc[0]) ** (252.0 / len(p_etf_lost_dec)) - 1.0)
    else:
        etf_lost_dec_cagr = np.nan

    # Naive Survivor Comparison
    survivor_cagr_full = np.nan
    survivor_cagr_1998_2008 = np.nan
    survivor_inflation_full_bps = np.nan
    survivor_inflation_1998_2008_bps = np.nan
    survivor_stock_count = 0

    target_etf_code = sym if cat == "Sector_SPDR" else None
    if target_etf_code:
        sub_daily = df_daily[df_daily["etf"] == target_etf_code].dropna(subset=["ret"])
        if len(sub_daily) > 0:
            survivor_stock_count = int(sub_daily["ticker"].nunique())
            
            # Full overlapping period
            sub_overlap = sub_daily[(sub_daily["date"] >= overlap_idx[0]) & (sub_daily["date"] <= overlap_idx[-1])]
            if len(sub_overlap) > 0:
                ew_daily = sub_overlap.groupby("date")["ret"].mean()
                cum_ew = (1.0 + ew_daily).cumprod()
                survivor_cagr_full = float(cum_ew.iloc[-1] ** (252.0 / len(ew_daily)) - 1.0)
                survivor_inflation_full_bps = float((survivor_cagr_full - cagr) * 10000.0)

            # 1998-2008 lost decade period
            sub_lost_dec = sub_daily[(sub_daily["date"] >= "1998-12-22") & (sub_daily["date"] <= "2008-12-31")]
            if len(sub_lost_dec) > 0 and not np.isnan(etf_lost_dec_cagr):
                ew_ld = sub_lost_dec.groupby("date")["ret"].mean()
                cum_ld = (1.0 + ew_ld).cumprod()
                survivor_cagr_1998_2008 = float(cum_ld.iloc[-1] ** (252.0 / len(ew_ld)) - 1.0)
                survivor_inflation_1998_2008_bps = float((survivor_cagr_1998_2008 - etf_lost_dec_cagr) * 10000.0)

    results.append({
        "symbol": sym,
        "name": name,
        "category": cat,
        "sector_family": sector_family,
        "start_date": start_dt,
        "end_date": end_dt,
        "trading_days": n_days,
        "years": round(years, 2),
        "total_return_pct": round(tot_ret * 100.0, 2),
        "cagr_official_pct": round(cagr * 100.0, 2),
        "spy_cagr_overlap_pct": round(spy_cagr * 100.0, 2),
        "excess_vs_spy_cagr_pct": round(excess_cagr_vs_spy * 100.0, 2),
        "volatility_ann_pct": round(vol * 100.0, 2),
        "sharpe_rf2pct": round(sharpe, 2) if not np.isnan(sharpe) else None,
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "calmar_ratio": round(calmar, 2) if not np.isnan(calmar) else None,
        "mdd_2000_dotcom_pct": round(mdd_dotcom * 100.0, 2) if not np.isnan(mdd_dotcom) else None,
        "mdd_2008_gfc_pct": round(mdd_gfc * 100.0, 2) if not np.isnan(mdd_gfc) else None,
        "mdd_2020_covid_pct": round(mdd_covid * 100.0, 2) if not np.isnan(mdd_covid) else None,
        "mdd_2022_hike_pct": round(mdd_hike * 100.0, 2) if not np.isnan(mdd_hike) else None,
        "cagr_1998_2008_official_pct": round(etf_lost_dec_cagr * 100.0, 2) if not np.isnan(etf_lost_dec_cagr) else None,
        "survivor_stock_count_in_all_daily": survivor_stock_count if survivor_stock_count > 0 else None,
        "survivor_cagr_1998_2008_pct": round(survivor_cagr_1998_2008 * 100.0, 2) if not np.isnan(survivor_cagr_1998_2008) else None,
        "survivor_water_squeeze_1998_2008_bps_yr": round(survivor_inflation_1998_2008_bps, 1) if not np.isnan(survivor_inflation_1998_2008_bps) else None,
        "survivor_cagr_full_pct": round(survivor_cagr_full * 100.0, 2) if not np.isnan(survivor_cagr_full) else None,
        "survivor_water_squeeze_full_bps_yr": round(survivor_inflation_full_bps, 1) if not np.isnan(survivor_inflation_full_bps) else None,
    })

res_df = pd.DataFrame(results)
out_csv = os.path.join(OUTPUT_DIR, "w1d_01_official_sector_etf_zero_survivorship_30y.csv")
res_df.to_csv(out_csv, index=False)
print(f"Successfully generated {out_csv} with {len(res_df)} ETF series.")
