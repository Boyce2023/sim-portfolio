#!/usr/bin/env python3
"""
w1_01_macro.py
30-Year Zero-Future-Function Macro & Market State Engine (1990-01-02 to 2026-11-09).

Key Methodologies:
1. Strict Point-in-Time (PIT):
   - Market series: forward-fill trading holidays, never backfill.
   - Weekly financial conditions (NFCI, STLFSI4): +6 calendar days buffer before effective.
   - Monthly/Quarterly economic data: ALFRED initial release vintages (min realtime_start)
     with physical publication lag fallback when archival started later.
   - Same-vintage YoY calculations to prevent index rebasing distortions (e.g. 1990 INDPRO).
2. Regimes & Classifications:
   - Rate level, 6M direction, Fed cycle.
   - Yield curve regime (including Bear/Bull Uninverting high-risk window).
   - Credit regime, VIX regime.
   - Growth regime (INDPRO YoY & 3M acceleration).
   - Macro quadrants (Q1 Goldilocks, Q2 Reflation, Q3 Stagflation/Tightening, Q4 Recession/CreditStress).
   - 9 Era slices (1990 to 2026).
3. Benchmarks & Sectors:
   - Continuous S&P 500 Total Return index normalized to 1000.0 on 2026-11-06.
   - Market cap scaler to 2026 level.
   - Key sector ETFs (XLK, XLV, XLF, XLI, XLY, XLP, XLE, XLU, XLB, XLRE, XLC) & benchmarks (QQQ, IWM, DXY).

Outputs:
- Parquet: sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/data/macro_pit_daily_1990_2026.parquet
- Audit: sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/data/macro_pit_audit.json
"""

import os
import json
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd

# Paths
BASE_DIR = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio")
TARGET_DIR = BASE_DIR / "backtest/2026-11-09-us-earnings-macro-30y"
DATA_DIR = TARGET_DIR / "data"
SCRIPTS_DIR = TARGET_DIR / "scripts"

DATA_DIR.mkdir(parents=True, exist_ok=True)
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_PARQUET = DATA_DIR / "macro_pit_daily_1990_2026.parquet"
OUTPUT_AUDIT = DATA_DIR / "macro_pit_audit.json"

ENV_PATH = BASE_DIR / ".env"
FRED_API_KEY = None
if ENV_PATH.exists():
    with open(ENV_PATH) as f:
        for line in f:
            if line.startswith("FRED_API_KEY="):
                FRED_API_KEY = line.strip().split("=", 1)[1].strip("'\"")

if not FRED_API_KEY:
    raise ValueError("FRED_API_KEY not found in .env!")


def fetch_fred_daily_weekly(series_id, obs_start="1989-01-01"):
    """Fetch observations for a series using curl with retry."""
    url = (
        f"https://api.stlouisfed.org/fred/series/observations?"
        f"series_id={series_id}&observation_start={obs_start}&"
        f"api_key={FRED_API_KEY}&file_type=json"
    )
    cmd = ["curl", "-sL", "--retry", "3", url]
    res = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(res.stdout)
    except Exception as e:
        print(f"Error parsing json for {series_id}: {e}")
        return pd.Series(dtype=float)
    
    obs = data.get("observations", [])
    if not obs:
        return pd.Series(dtype=float)
    
    df = pd.DataFrame(obs)
    df = df[df["value"] != "."].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return df.set_index("date")["value"]


def load_daily_series(series_id):
    """Load from local parquet, then supplement with FRED API if available."""
    local_p = BASE_DIR / f"data/us_price_db/macro/{series_id}.parquet"
    local_s = pd.Series(dtype=float)
    if local_p.exists():
        ldf = pd.read_parquet(local_p)
        ldf.index = pd.to_datetime(ldf.index).tz_localize(None).normalize()
        local_s = ldf["value"].copy()
    
    # Check if local reaches near 2026-11-06
    if local_s.empty or local_s.index.max() < pd.Timestamp("2026-11-05"):
        print(f"Fetching online update for {series_id}...")
        online_s = fetch_fred_daily_weekly(series_id, obs_start="1989-01-01")
        combined = pd.concat([local_s, online_s])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        return combined
    return local_s


def build_alfred_pit_series(series_id, fallback_day, is_quarterly=False, sahm_unrate_map=None):
    """
    Build Point-in-Time published observations and initial YoY from ALFRED raw vintages.
    Uses same-vintage base comparison for YoY to avoid base-year rebasing discontinuities.
    """
    raw_file = DATA_DIR / f"alfred_raw_{series_id}.parquet"
    if not raw_file.exists():
        print(f"Fetching raw ALFRED for {series_id}...")
        url = (
            f"https://api.stlouisfed.org/fred/series/observations?"
            f"series_id={series_id}&realtime_start=1776-07-04&realtime_end=9999-12-31&"
            f"observation_start=1988-01-01&api_key={FRED_API_KEY}&file_type=json"
        )
        cmd = ["curl", "-sL", "--retry", "3", url]
        res = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(res.stdout)
        obs = data.get("observations", [])
        df = pd.DataFrame(obs)
        df = df[df["value"] != "."].copy()
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["value"])
        df.to_parquet(raw_file)
    else:
        df = pd.read_parquet(raw_file)

    df["date"] = pd.to_datetime(df["date"])
    df["realtime_start"] = pd.to_datetime(df["realtime_start"])
    df["realtime_end"] = df["realtime_end"].replace({"9999-12-31": "2099-12-31"})
    df["realtime_end"] = pd.to_datetime(df["realtime_end"])

    # First release records (group by observation date, take min realtime_start)
    first_df = df.sort_values(["date", "realtime_start"]).groupby("date").first().reset_index()
    first_df["lag_days"] = (first_df["realtime_start"] - first_df["date"]).dt.days

    # Pre-index df by date for fast lookup of previous year value in same vintage
    records = []
    for _, row in first_df.iterrows():
        obs_d = row["date"]
        rt = row["realtime_start"]
        initial_val = row["value"]
        lag = row["lag_days"]

        # Publication date determination
        if lag > 45:
            if is_quarterly:
                # Quarter end + 35 days
                q_end = obs_d + pd.offsets.QuarterEnd(startingMonth=obs_d.month)
                pub_d = q_end + pd.Timedelta(days=35)
            elif series_id == "SAHMREALTIME" and sahm_unrate_map is not None:
                pub_d = sahm_unrate_map.get(
                    obs_d,
                    obs_d + pd.DateOffset(months=1) + pd.Timedelta(days=fallback_day - 1)
                )
            else:
                next_m = obs_d + pd.DateOffset(months=1)
                pub_d = pd.Timestamp(year=next_m.year, month=next_m.month, day=fallback_day)
        else:
            pub_d = rt

        # Look up 12 months prior in the same vintage rt
        prev_12_d = obs_d - pd.DateOffset(months=12)
        match_prev = df[
            (df["date"] == prev_12_d) &
            (df["realtime_start"] <= rt) &
            (df["realtime_end"] >= rt)
        ]
        if not match_prev.empty:
            prev_val = match_prev.iloc[0]["value"]
            yoy = (initial_val / prev_val - 1.0) * 100.0 if prev_val != 0 else np.nan
        else:
            yoy = np.nan

        records.append({
            "obs_date": obs_d,
            "pub_date": pub_d,
            "initial_val": initial_val,
            "yoy": yoy
        })

    pub_df = pd.DataFrame(records).sort_values("pub_date").reset_index(drop=True)
    return pub_df


def main():
    print("=================================================================")
    print("W1_01: Building 30-Year Zero-Future-Function Macro State Engine")
    print("=================================================================")

    # 1. Trading Calendar from GSPC and SPY
    print("\n[Step 1] Constructing US Equity Trading Calendar...")
    gspc_p = BASE_DIR / "data/us_price_db/benchmarks/GSPC.parquet"
    spy_p = BASE_DIR / "data/us_price_db/benchmarks/SPY.parquet"

    gspc_df = pd.read_parquet(gspc_p)
    spy_df = pd.read_parquet(spy_p)

    gspc_df.index = pd.to_datetime(gspc_df.index).tz_localize(None).normalize()
    spy_df.index = pd.to_datetime(spy_df.index).tz_localize(None).normalize()

    all_trading_days = sorted(list(set(gspc_df.index).union(set(spy_df.index))))
    all_trading_days = [
        d for d in all_trading_days
        if d >= pd.Timestamp("1990-01-02") and d <= pd.Timestamp("2026-11-06")
    ]
    # Pad to 2026-11-09
    if pd.Timestamp("2026-11-09") not in all_trading_days:
        all_trading_days.append(pd.Timestamp("2026-11-09"))
    all_trading_days = sorted(all_trading_days)

    cal = pd.DataFrame({"date": all_trading_days})
    print(f"Total trading days: {len(cal)} (Range: {cal['date'].min().date()} to {cal['date'].max().date()})")

    # 2. S&P 500 Benchmarks & Total Return Index
    print("\n[Step 2] Calculating Benchmark Returns & Total Return Index...")
    gspc_s = gspc_df["close"].reindex(all_trading_days).ffill()
    spy_s = spy_df["adj_close"].reindex(all_trading_days).ffill()

    # Calculate seamless daily return
    # Before 1993-01-29: GSPC close return
    # 1993-01-29 to 2026-11-06: SPY adj_close return
    gspc_ret = gspc_s.pct_change().fillna(0.0)
    spy_ret = spy_s.pct_change()

    combined_ret = pd.Series(index=all_trading_days, dtype=float)
    spy_start = pd.Timestamp("1993-01-29")
    for d in all_trading_days:
        if d <= spy_start or pd.isna(spy_ret.get(d)):
            combined_ret[d] = gspc_ret.get(d, 0.0)
        else:
            combined_ret[d] = spy_ret[d]
    
    # 2026-11-09 is Monday before market close, 0% daily return from Friday close
    combined_ret[pd.Timestamp("2026-11-09")] = 0.0

    # Cumulative total return
    cum_tr = (1.0 + combined_ret).cumprod()
    # Normalize to 1000.0 on 2026-11-06
    tr_20261106 = cum_tr.loc[pd.Timestamp("2026-11-06")]
    bench_sp500_tr = (cum_tr / tr_20261106) * 1000.0

    # Market Cap Scaler to 2026
    gspc_20261106 = gspc_s.loc[pd.Timestamp("2026-11-06")]
    mcap_scale_to_2026 = gspc_20261106 / gspc_s

    # S&P 500 Momentum, MA200, DD252
    sp500_ret_126d = bench_sp500_tr / bench_sp500_tr.shift(126) - 1.0
    sp500_ret_252d = bench_sp500_tr / bench_sp500_tr.shift(252) - 1.0
    sp500_ma200 = gspc_s.rolling(200, min_periods=1).mean()
    sp500_above_ma200 = gspc_s > sp500_ma200
    sp500_peak_252 = gspc_s.rolling(252, min_periods=1).max()
    sp500_dd_252d = (gspc_s / sp500_peak_252) - 1.0

    cal["bench_sp500_price"] = cal["date"].map(gspc_s)
    cal["bench_sp500_tr"] = cal["date"].map(bench_sp500_tr)
    cal["mcap_scale_to_2026"] = cal["date"].map(mcap_scale_to_2026)
    cal["sp500_ret_126d"] = cal["date"].map(sp500_ret_126d)
    cal["sp500_ret_252d"] = cal["date"].map(sp500_ret_252d)
    cal["sp500_above_ma200"] = cal["date"].map(sp500_above_ma200).astype(bool)
    cal["sp500_dd_252d"] = cal["date"].map(sp500_dd_252d)

    # Key broader benchmarks: QQQ, IWM, DXY
    for b_ticker, col_b in [("QQQ", "close_qqq"), ("IWM", "close_iwm"), ("DX-Y_NYB", "close_dxy")]:
        bp = BASE_DIR / f"data/us_price_db/benchmarks/{b_ticker}.parquet"
        if bp.exists():
            bdf = pd.read_parquet(bp)
            bdf.index = pd.to_datetime(bdf.index).tz_localize(None).normalize()
            cal[col_b] = cal["date"].map(bdf["close"].reindex(all_trading_days).ffill())

    # Sector ETFs (XLK, XLV, XLF, XLI, XLY, XLP, XLE, XLU, XLB, XLRE, XLC)
    sector_tickers = ["XLK", "XLV", "XLF", "XLI", "XLY", "XLP", "XLE", "XLU", "XLB", "XLRE", "XLC"]
    for sec in sector_tickers:
        sec_p = BASE_DIR / f"data/us_price_db/sectors/{sec}.parquet"
        if sec_p.exists():
            sec_df = pd.read_parquet(sec_p)
            sec_df.index = pd.to_datetime(sec_df.index).tz_localize(None).normalize()
            cal[f"close_{sec.lower()}"] = cal["date"].map(sec_df["close"].reindex(all_trading_days).ffill())

    # 3. Market Rates & Price Series (Daily Forward-Fill)
    print("\n[Step 3] Loading Daily Rates & Spreads (DGS10, DGS2, T10Y2Y, T10Y3M, DFF, DFII10, BAA10Y, AAA10Y, HY_OAS, VIX)...")
    daily_series_names = [
        "DGS10", "DGS2", "T10Y2Y", "T10Y3M", "DFF", "DFII10", "BAA10Y", "AAA10Y", "BAMLH0A0HYM2"
    ]
    daily_data = {}
    for s_name in daily_series_names:
        s = load_daily_series(s_name)
        s_aligned = s.reindex(all_trading_days).ffill()
        daily_data[s_name.lower()] = s_aligned

    # VIX from VIX benchmark or VIXCLS
    vix_p = BASE_DIR / "data/us_price_db/benchmarks/VIX.parquet"
    if vix_p.exists():
        vix_df = pd.read_parquet(vix_p)
        vix_df.index = pd.to_datetime(vix_df.index).tz_localize(None).normalize()
        vix_s = vix_df["close"].reindex(all_trading_days).ffill()
    else:
        vix_s = load_daily_series("VIXCLS").reindex(all_trading_days).ffill()
    daily_data["vix"] = vix_s

    for k, v in daily_data.items():
        col_name = "hy_oas" if k == "bamlh0a0hym2" else k
        cal[col_name] = cal["date"].map(v)

    # Check T10Y2Y fallback
    if cal["t10y2y"].isna().any():
        cal["t10y2y"] = cal["t10y2y"].fillna(cal["dgs10"] - cal["dgs2"])
    if cal["t10y3m"].isna().any():
        cal["t10y3m"] = cal["t10y3m"].ffill()

    # 4. Weekly Conditions (NFCI, STLFSI4) with Strict +6 Days Publication Buffer
    print("\n[Step 4] Aligning Weekly Financial Conditions (NFCI, STLFSI4) with +6 Days Buffer...")
    for w_name in ["NFCI", "STLFSI4"]:
        ws = load_daily_series(w_name)
        w_df = ws.reset_index()
        w_df.columns = ["obs_date", "value"]
        # Publication date = Friday observation date + 6 calendar days
        w_df["pub_date"] = w_df["obs_date"] + pd.Timedelta(days=6)
        w_df = w_df.sort_values("pub_date")

        merged_w = pd.merge_asof(
            cal[["date"]].sort_values("date"),
            w_df[["pub_date", "value"]],
            left_on="date",
            right_on="pub_date",
            direction="backward"
        )
        col_w = f"{w_name.lower()}_pit"
        cal[col_w] = merged_w["value"].values

    # 5. ALFRED Monthly/Quarterly PIT Economic Data
    print("\n[Step 5] Extracting ALFRED Initial Releases (CPIAUCSL, CPILFESL, INDPRO, UNRATE, PAYEMS, M2SL, SAHM, DRTSCILM)...")
    unrate_pit = build_alfred_pit_series("UNRATE", fallback_day=8)
    unrate_map = dict(zip(unrate_pit["obs_date"], unrate_pit["pub_date"]))

    pit_configs = [
        ("CPIAUCSL", 16, False, None, "cpi_pit", "cpi_yoy_pit"),
        ("CPILFESL", 16, False, None, "cpilfesl_pit", "cpilfesl_yoy_pit"),
        ("INDPRO", 18, False, None, "indpro_pit", "indpro_yoy_pit"),
        ("NEWORDER", 18, False, None, "neworder_pit", "neworder_yoy_pit"),
        ("UNRATE", 8, False, None, "unrate_pit", None),
        ("PAYEMS", 8, False, None, "payems_pit", "payems_yoy_pit"),
        ("M2SL", 18, False, None, "m2_pit", "m2_yoy_pit"),
        ("DRTSCILM", 35, True, None, "drtscilm_pit", None),
        ("SAHMREALTIME", 8, False, unrate_map, "unrate_sahm", None),
    ]

    for sid, fb_day, is_q, s_map, val_col, yoy_col in pit_configs:
        pit_table = build_alfred_pit_series(sid, fb_day, is_q, s_map)
        cols_to_merge = ["pub_date", "initial_val"]
        rename_dict = {"initial_val": val_col}
        if yoy_col is not None:
            cols_to_merge.append("yoy")
            rename_dict["yoy"] = yoy_col

        merged_pit = pd.merge_asof(
            cal[["date"]].sort_values("date"),
            pit_table[cols_to_merge].rename(columns=rename_dict),
            left_on="date",
            right_on="pub_date",
            direction="backward"
        )
        cal[val_col] = merged_pit[val_col].values
        if yoy_col is not None:
            cal[yoy_col] = merged_pit[yoy_col].values

    # 6. Interest Rate Features & Inflation Adjustments
    print("\n[Step 6] Engineering Interest Rate, Spread & Real Yield Features...")
    cal["real_rate_10y_derived"] = cal["dgs10"] - cal["cpi_yoy_pit"]
    # 2003 onward優先使用 DFII10 (10Y TIPS real rate), 之前使用 dgs10 - cpi_yoy_pit
    cal["real_rate_10y_pit"] = np.where(
        cal["dfii10"].notna(),
        cal["dfii10"],
        cal["real_rate_10y_derived"]
    )

    # 63d, 126d, 252d changes
    cal["dgs10_chg_63d"] = cal["dgs10"] - cal["dgs10"].shift(63)
    cal["dgs10_chg_126d"] = cal["dgs10"] - cal["dgs10"].shift(126)
    cal["dgs10_chg_252d"] = cal["dgs10"] - cal["dgs10"].shift(252)

    # Rate level bin: <2.5%, 2.5%-4.0%, 4.0%-5.5%, >=5.5%
    cal["rate_level_bin"] = pd.cut(
        cal["dgs10"],
        bins=[-np.inf, 2.5, 4.0, 5.5, np.inf],
        labels=["<2.5%", "2.5%-4.0%", "4.0%-5.5%", ">=5.5%"],
        right=False
    ).astype(str)

    # Rate direction 6M: Falling_35bp+, Stable, Rising_35bp+
    conditions_ratedir = [
        cal["dgs10_chg_126d"] <= -0.35,
        cal["dgs10_chg_126d"] >= 0.35
    ]
    choices_ratedir = ["Falling_35bp+", "Rising_35bp+"]
    cal["rate_dir_6m"] = np.select(conditions_ratedir, choices_ratedir, default="Stable")

    # Fed cycle: based on DFF past 126 trading days change (Cutting <= -0.25, Hiking >= 0.25, OnHold)
    dff_chg_126d = cal["dff"] - cal["dff"].shift(126)
    cal["dff_chg_126d"] = dff_chg_126d
    conditions_fed = [
        dff_chg_126d <= -0.25,
        dff_chg_126d >= 0.25
    ]
    choices_fed = ["Cutting", "Hiking"]
    cal["fed_cycle"] = np.select(conditions_fed, choices_fed, default="OnHold")

    # 7. Yield Curve Regime (with Inverted and Bear_or_Bull_Uninverting High-Risk Window)
    print("\n[Step 7] Classifying Yield Curve Regimes...")
    rolling_min_126_t10y2y = cal["t10y2y"].rolling(126, min_periods=1).min()
    cal["t10y2y_rolling_min_126"] = rolling_min_126_t10y2y

    yc_regime = []
    for idx, row in cal.iterrows():
        y2 = row["t10y2y"]
        rmin = row["t10y2y_rolling_min_126"]
        if y2 < 0.0:
            yc_regime.append("Inverted")
        elif rmin < -0.10:
            yc_regime.append("Bear_or_Bull_Uninverting")
        elif y2 <= 1.20:
            yc_regime.append("Flat_Normal_0_120bp")
        else:
            yc_regime.append("Steep_EarlyCycle_gt120bp")
    cal["yc_regime"] = yc_regime

    # 8. Credit Regime & Volatility Regime
    print("\n[Step 8] Classifying Credit & Volatility Regimes...")
    cal["credit_regime"] = pd.cut(
        cal["baa10y"],
        bins=[-np.inf, 1.8, 2.5, 3.3, np.inf],
        labels=["Benign", "Normal", "Tightening_Stress", "Credit_Crisis"],
        right=False
    ).astype(str)

    cal["vix_regime"] = pd.cut(
        cal["vix"],
        bins=[-np.inf, 16.0, 24.0, 32.0, np.inf],
        labels=["LowVol", "NormalVol", "HighVol", "PanicVol"],
        right=False
    ).astype(str)

    # 9. Real Growth Regime & 3M Acceleration
    print("\n[Step 9] Classifying Real Growth & Macro Quadrants...")
    cal["indpro_accel_pit"] = cal["indpro_yoy_pit"] - cal["indpro_yoy_pit"].shift(63)
    cal["indpro_accel_pit"] = cal["indpro_accel_pit"].fillna(0.0)

    growth_regime = []
    for _, row in cal.iterrows():
        gy = row["indpro_yoy_pit"]
        acc = row["indpro_accel_pit"]
        if gy > 0.0:
            if acc >= 0.0:
                growth_regime.append("Expanding_Accel")
            else:
                growth_regime.append("Expanding_Decel")
        else:
            if acc >= 0.0:
                growth_regime.append("Contracting_Stabilizing")
            else:
                growth_regime.append("Contracting_Worsening")
    cal["growth_regime"] = growth_regime

    # Macro Quadrants:
    macro_quadrant = []
    for _, row in cal.iterrows():
        iy = row["indpro_yoy_pit"]
        chg_10y = row["dgs10_chg_126d"] if not pd.isna(row["dgs10_chg_126d"]) else 0.0
        c_reg = row["credit_regime"]
        baa = row["baa10y"]
        sahm = row["unrate_sahm"]
        cpi = row["cpi_yoy_pit"]
        acc = row["indpro_accel_pit"]

        # Rule 1: Recession / Crisis
        if iy < 0.0 or baa >= 3.0 or sahm >= 0.50 or c_reg == "Credit_Crisis":
            macro_quadrant.append("Q4_Recession_CreditStress")
        # Rule 2: Strong Growth (>= 1.5%)
        elif iy >= 1.5:
            if chg_10y > 0.25:
                macro_quadrant.append("Q2_Reflation_CapexBoom")
            else:
                macro_quadrant.append("Q1_Goldilocks")
        # Rule 3: Moderate / Low Growth (0 <= iy < 1.5)
        else:
            if chg_10y > 0.0 or cpi >= 3.5 or acc < 0.0:
                macro_quadrant.append("Q3_Tightening_Stagflation")
            else:
                macro_quadrant.append("Q1_Goldilocks")

    cal["macro_quadrant"] = macro_quadrant

    # 10. Era Regimes (9 Historical Eras)
    print("\n[Step 10] Assigning 9 Era Regimes...")
    def get_era(d):
        yr = d.year
        if yr < 1996:
            return "1990_1995_Early90s"
        elif 1996 <= yr <= 2000:
            return "1996_2000_DotCom"
        elif 2001 <= yr <= 2002:
            return "2001_2002_TechBust"
        elif 2003 <= yr <= 2007:
            return "2003_2007_CycleBull"
        elif 2008 <= yr <= 2009:
            return "2008_2009_GFC"
        elif 2010 <= yr <= 2019:
            return "2010_2019_LowRateBull"
        elif 2020 <= yr <= 2021:
            return "2020_2021_ZeroRateCovid"
        elif 2022 <= yr <= 2023:
            return "2022_2023_RateHikeReset"
        else:
            return "2024_2026_HighRateAI"

    cal["era_regime"] = cal["date"].apply(get_era)

    # 11. Clean Up Columns & Verification
    print("\n[Step 11] Validating Quality & Column Structure...")
    cal["date_str"] = cal["date"].dt.strftime("%Y-%m-%d")

    crit_cols = [
        "date", "bench_sp500_price", "bench_sp500_tr", "mcap_scale_to_2026",
        "dgs10", "dgs2", "t10y2y", "dff", "cpi_yoy_pit", "real_rate_10y_pit",
        "rate_level_bin", "rate_dir_6m", "fed_cycle", "yc_regime",
        "baa10y", "credit_regime", "vix", "vix_regime",
        "indpro_yoy_pit", "growth_regime", "macro_quadrant", "era_regime"
    ]
    null_counts = cal[crit_cols].isna().sum()
    print("Null counts in critical columns:")
    for c, cnt in null_counts.items():
        if cnt > 0:
            print(f"  {c}: {cnt} nulls")
    if null_counts.max() == 0:
        print("  ALL 22 critical columns have 0 null values!")

    row_count = len(cal)
    print(f"Total Rows: {row_count} (> 9,200: {row_count > 9200})")

    # Print 2026-11-06 macro state slice
    row_20261106 = cal[cal["date_str"] == "2026-11-06"].iloc[0]
    print("\n=======================================================")
    print("Real Macro & Market State Snapshot on 2026-11-06:")
    print("=======================================================")
    key_fields = [
        "date_str", "bench_sp500_price", "bench_sp500_tr", "mcap_scale_to_2026",
        "dgs10", "dgs2", "t10y2y", "dff", "dfii10", "cpi_yoy_pit", "real_rate_10y_pit",
        "dgs10_chg_126d", "rate_level_bin", "rate_dir_6m", "fed_cycle", "yc_regime",
        "baa10y", "hy_oas", "credit_regime", "vix", "vix_regime",
        "indpro_yoy_pit", "indpro_accel_pit", "unrate_pit", "unrate_sahm",
        "growth_regime", "macro_quadrant", "era_regime"
    ]
    snapshot_20261106 = {}
    for f in key_fields:
        val = row_20261106[f]
        snapshot_20261106[f] = float(val) if isinstance(val, (np.floating, float)) else str(val)
        print(f"  {f:24s}: {snapshot_20261106[f]}")

    # Value counts
    print("\nMacro Quadrant Distribution:")
    quad_counts = cal["macro_quadrant"].value_counts().to_dict()
    for q, cnt in quad_counts.items():
        print(f"  {q:30s}: {cnt:5d} days ({cnt/row_count*100:5.1f}%)")

    print("\nEra Regime Distribution:")
    era_counts = cal["era_regime"].value_counts().to_dict()
    for era, cnt in era_counts.items():
        print(f"  {era:30s}: {cnt:5d} days ({cnt/row_count*100:5.1f}%)")

    print("\nYield Curve Regime Distribution:")
    yc_counts = cal["yc_regime"].value_counts().to_dict()
    for yc, cnt in yc_counts.items():
        print(f"  {yc:30s}: {cnt:5d} days ({cnt/row_count*100:5.1f}%)")

    # 12. Save Parquet & Audit JSON
    print(f"\n[Step 12] Saving Parquet to {OUTPUT_PARQUET}...")
    cal.to_parquet(OUTPUT_PARQUET, index=False)
    parquet_size_mb = OUTPUT_PARQUET.stat().st_size / (1024 * 1024)
    print(f"Parquet saved successfully! File size: {parquet_size_mb:.2f} MB")

    audit_summary = {
        "status": "SUCCESS",
        "output_parquet": str(OUTPUT_PARQUET),
        "parquet_size_mb": round(parquet_size_mb, 3),
        "total_trading_days": row_count,
        "date_range": [cal["date_str"].min(), cal["date_str"].max()],
        "sp500_tr_20261106": round(float(row_20261106["bench_sp500_tr"]), 2),
        "snapshot_20261106": snapshot_20261106,
        "macro_quadrant_distribution": quad_counts,
        "era_regime_distribution": era_counts,
        "yc_regime_distribution": yc_counts,
        "credit_regime_distribution": cal["credit_regime"].value_counts().to_dict(),
        "vix_regime_distribution": cal["vix_regime"].value_counts().to_dict(),
        "growth_regime_distribution": cal["growth_regime"].value_counts().to_dict(),
        "columns_included": cal.columns.tolist(),
        "data_sources": {
            "calendar": "GSPC + SPY (1990-01-02 to 2026-11-06, padded to 2026-11-09)",
            "benchmark_tr": "Continuous compounding (GSPC before 1993-01-29, SPY adj_close onward, 2026-11-06=1000.0)",
            "market_rates": "FRED DGS10, DGS2, T10Y2Y, T10Y3M, DFF, DFII10, BAA10Y, AAA10Y, BAMLH0A0HYM2, VIXCLS",
            "weekly_conditions": "FRED NFCI, STLFSI4 with +6 calendar days publication buffer",
            "monthly_alfred_pit": "ALFRED initial releases (CPIAUCSL, CPILFESL, INDPRO, NEWORDER, UNRATE, PAYEMS, M2SL, SAHMREALTIME, DRTSCILM)",
            "sectors_and_benchmarks": "XLK, XLV, XLF, XLI, XLY, XLP, XLE, XLU, XLB, XLRE, XLC, QQQ, IWM, DXY"
        }
    }

    with open(OUTPUT_AUDIT, "w", encoding="utf-8") as f:
        json.dump(audit_summary, f, indent=2, ensure_ascii=False)
    print(f"Audit JSON saved to {OUTPUT_AUDIT}!")


if __name__ == "__main__":
    main()
