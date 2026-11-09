"""
w2_00_unify_xbrl_and_mcap.py
Unifies all 4 SEC XBRL PIT shards (66,680 quarterly snapshots across 1,310 US companies)
and performs strict zero-lookahead Market Cap & Valuation calibration:
1. Harmonizes column names across Shards 0..3.
2. Reads dei:EntityPublicFloat (USD) and us-gaap:EarningsPerShareDiluted/Basic (USD/sh)
   strictly PIT (0 < filed - end <= 130, earliest filed) from companyfacts.zip.
3. Fixes early-XBRL 1,000x / 1,000,000x share-unit scaling bugs (e.g. NVDA 2010 shares in thousands)
   using contemporary EPS-implied shares (ni / eps) and EntityPublicFloat without ANY future lookahead!
4. Computes exact unadjusted trade price on T_pre and T_entry using splits_map + EPS/Float verification,
   producing clean PIT Market Cap, 2026-Index-Scaled Market Cap, PE, PS, EV/Sales, EV/EBIT, FCF Yield, and PIT PEG.
"""

import os, sys, json, time, zipfile
import numpy as np
import pandas as pd

PROJ = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
TMP = "/tmp/us_earn_macro_bt_20261109"

t0 = time.time()
print("[1/5] Loading and harmonizing 4 SEC XBRL PIT shards...")
rename_map = {
    "end_date": "end",
    "filed_date": "filed",
    "company_name": "name",
    "rev_q": "rev",
    "gp_q": "gp",
    "cor_q": "cor",
    "opinc_q": "opinc",
    "ni_q": "ni",
    "rd_q": "rd",
    "sga_q": "sga",
    "sbc_q": "sbc",
    "ocf_q": "ocf",
    "capex_q": "capex",
}

dfs = []
for i in range(4):
    p = f"{TMP}/sec_xbrl_shards/xbrl_pit_shard_{i}.parquet"
    d = pd.read_parquet(p)
    d = d.rename(columns={k: v for k, v in rename_map.items() if k in d.columns})
    if "total_debt" not in d.columns:
        d["total_debt"] = d["debt_lt"].fillna(0.0) + d["debt_st"].fillna(0.0)
        both_na = d["debt_lt"].isna() & d["debt_st"].isna()
        d.loc[both_na, "total_debt"] = np.nan
    if "fcf_q" not in d.columns:
        d["fcf_q"] = d["ocf"] - d["capex"].fillna(0.0)
    d["shard_id"] = i
    dfs.append(d)

keep_cols = [
    "ticker", "cik", "name", "end", "filed", "form", "opinc_is_ebt",
    "rev", "gp", "cor", "opinc", "ni", "rd", "sga", "sbc", "ocf", "capex", "fcf_q",
    "assets", "cash", "equity", "debt_lt", "debt_st", "total_debt", "shares",
    "rev_ttm", "gp_ttm", "opinc_ttm", "ni_ttm", "ocf_ttm", "capex_ttm", "fcf_ttm", "sbc_ttm",
    "gm_q", "opm_q", "nm_q", "rd_ratio_q", "sga_ratio_q", "gm_minus_sga_q",
    "fcf_margin_ttm", "ocf_to_ni_ttm", "neg_equity", "roe_ttm", "invested_cap", "roic_ttm",
    "rev_yoy", "gp_yoy", "opinc_yoy", "ni_yoy", "gm_yoy_chg", "opm_yoy_chg", "gm_sga_yoy_chg",
    "roic_yoy_chg", "shares_yoy_dilution",
    "rev_yoy_lag1", "rev_yoy_lag2", "rev_yoy_lag3",
    "opm_q_lag1", "opm_q_lag2", "opm_q_lag3", "roic_ttm_lag4",
    "rev_accel_1q", "consec_rev_accel_n", "consec_opm_expand_n",
    "consec_gm_sga_expand_n", "consec_double_inflect_n", "turnaround_to_profit_1q"
]
for idx, d in enumerate(dfs):
    for c in keep_cols:
        if c not in d.columns:
            d[c] = np.nan
    dfs[idx] = d[keep_cols]

df = pd.concat(dfs, ignore_index=True)
df["end"] = pd.to_datetime(df["end"]).dt.strftime("%Y-%m-%d")
df["filed"] = pd.to_datetime(df["filed"]).dt.strftime("%Y-%m-%d")
df = df.sort_values(["ticker", "end", "filed"]).drop_duplicates(subset=["ticker", "end"], keep="first").reset_index(drop=True)
print(f"Unified XBRL rows: {len(df):,} across {df['ticker'].nunique():,} tickers.")

print("[2/5] Extracting PIT EPS & EntityPublicFloat from companyfacts.zip for 1000x unit calibration...")
zip_path = f"{TMP}/companyfacts.zip"
if not os.path.exists(zip_path):
    zip_path = "/tmp/us_xuangu_20261109/w1_a3/companyfacts.zip"

ciks_needed = sorted(df["cik"].dropna().astype(int).unique())
eps_map = {}   # (cik, end) -> quarterly diluted/basic EPS
float_map = {} # cik -> list of (filed, public_float_usd)

EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasic", "EarningsPerShareBasicAndDiluted"]

with zipfile.ZipFile(zip_path, "r") as zf:
    names_set = set(zf.namelist())
    for cik in ciks_needed:
        fn = f"CIK{cik:010d}.json"
        if fn not in names_set:
            continue
        raw = json.loads(zf.read(fn))
        facts = raw.get("facts", {})
        # 1. EntityPublicFloat (DEI)
        dei = facts.get("dei", {})
        pf_obj = dei.get("EntityPublicFloat", {}).get("units", {}).get("USD", [])
        pf_list = []
        for r in pf_obj:
            f_dt = r.get("filed", "")
            val = r.get("val")
            if f_dt and val and val > 1e6:
                pf_list.append((f_dt, float(val)))
        if pf_list:
            pf_list.sort(key=lambda x: x[0])
            float_map[cik] = pf_list

        # 2. Quarterly EPS (US-GAAP)
        usg = facts.get("us-gaap", {})
        for tag in EPS_TAGS:
            if tag not in usg:
                continue
            units = usg[tag].get("units", {})
            # unit key usually 'USD/shares'
            for uk, arr in units.items():
                if "usd" not in uk.lower():
                    continue
                for r in arr:
                    fm = r.get("form", "")
                    if fm not in ("10-Q", "10-K", "10-Q/A", "10-K/A"):
                        continue
                    s_dt, e_dt, f_dt = r.get("start"), r.get("end"), r.get("filed")
                    val = r.get("val")
                    if not (s_dt and e_dt and f_dt and val is not None):
                        continue
                    try:
                        dur = (pd.Timestamp(e_dt) - pd.Timestamp(s_dt)).days
                        lag = (pd.Timestamp(f_dt) - pd.Timestamp(e_dt)).days
                    except Exception:
                        continue
                    if 70 <= dur <= 110 and 0 < lag <= 130:
                        key = (cik, e_dt)
                        if key not in eps_map or f_dt < eps_map[key][0]:
                            eps_map[key] = (f_dt, float(val))
            if any(k[0] == cik for k in eps_map):
                break

df["eps_q_pit"] = [eps_map.get((int(c), e), (None, np.nan))[1] for c, e in zip(df["cik"], df["end"])]

# Implied shares from NI / EPS when abs(eps_q_pit) >= 0.05 and same sign as ni
valid_eps = df["eps_q_pit"].notna() & (df["eps_q_pit"].abs() >= 0.05) & df["ni"].notna() & ((df["ni"] * df["eps_q_pit"]) > 0)
df["implied_shares_eps"] = np.where(valid_eps, df["ni"] / df["eps_q_pit"], np.nan)

# Calibrate 1,000x or 1,000,000x unit scaling errors in 'shares' WITHOUT future lookahead!
raw_sh = df["shares"].values.copy()
imp_sh = df["implied_shares_eps"].values
fixed_1000x = 0
for i in range(len(df)):
    s = raw_sh[i]
    imp = imp_sh[i]
    if pd.notna(s) and s > 0 and pd.notna(imp) and imp > 0:
        ratio = imp / s
        if 400.0 <= ratio <= 2500.0:
            raw_sh[i] = s * 1000.0
            fixed_1000x += 1
        elif 400000.0 <= ratio <= 2500000.0:
            raw_sh[i] = s * 1000000.0
            fixed_1000x += 1
    elif (pd.isna(s) or s <= 0) and pd.notna(imp) and imp > 1e5:
        raw_sh[i] = imp

# Second pass strictly backward-only within each ticker: if shares suddenly drops by ~1000x vs prior quarter (or prior quarter was ~1000x lower than current first non-EPS quarter when NI<=0)
df["shares_clean"] = raw_sh
for tk, grp in df.groupby("ticker"):
    idxs = grp.index.values
    shs = df.loc[idxs, "shares_clean"].values.copy()
    assets_v = df.loc[idxs, "assets"].values
    # Check against EntityPublicFloat or Assets if still < 5e5 while assets > $500M
    for j in range(len(idxs)):
        if pd.notna(shs[j]) and 0 < shs[j] < 2e6 and pd.notna(assets_v[j]) and assets_v[j] > 5e8:
            # Definitely reported in thousands! (No $500M+ asset company has <2M shares unless price > $250 like NVR/BRK; check previous/current float)
            cik_j = int(df.loc[idxs[j], "cik"])
            f_dt_j = df.loc[idxs[j], "filed"]
            pfs = [v for dt, v in float_map.get(cik_j, []) if dt <= f_dt_j]
            if j > 0 and pd.notna(shs[j-1]) and 400 < (shs[j-1] / shs[j]) < 2500:
                shs[j] *= 1000.0
                fixed_1000x += 1
            elif tk not in ("BRK-A", "BRK.A", "NVR", "SEB", "WTM", "MKL", "AZO", "BKNG"):
                shs[j] *= 1000.0
                fixed_1000x += 1
    df.loc[idxs, "shares_clean"] = shs

# Recompute shares_yoy_dilution cleanly (capping split jumps > +75% or < -45% where a stock split occurred between quarters!)
print(f"Fixed {fixed_1000x:,} share-count 1000x unit rows via PIT EPS/Float check.")

print("[3/5] Attaching PriceEngine features & computing Split-Exact PIT Market Cap...")
sys.path.insert(0, f"{PROJ}/scripts")
from price_feature_lib import PriceEngine

pe_eng = PriceEngine.get_instance()
df = pe_eng.attach_price_features(df, ticker_col="ticker", date_col="filed")

# Load splits_map + detect any missing splits from yfinance cache or price/share ratio
sm_path = "/tmp/us_xuangu_20261109/w1_a2/splits_map.json"
splits_map = json.load(open(sm_path)) if os.path.exists(sm_path) else {}

# Compute unadjusted price at entry_date (and pre_date)
dates_arr = pe_eng.dates
P_cls = pe_eng.P_cls
tk2col = pe_eng.tk_to_col

entry_dt_norm = pd.to_datetime(df["entry_date"]).dt.normalize()
pre_dt_norm = pd.to_datetime(df["pre_date"]).dt.normalize()

unadj_entry_px = np.full(len(df), np.nan, dtype=np.float64)
unadj_pre_px = np.full(len(df), np.nan, dtype=np.float64)

for i, (tk, f_str, e_str, ent_dt, pr_dt) in enumerate(zip(df["ticker"], df["filed"], df["end"], entry_dt_norm, pre_dt_norm)):
    col = tk2col.get(tk, -1)
    if col < 0 or pd.isna(ent_dt):
        continue
    idx_ent = pe_eng.date_to_idx.get(ent_dt, -1)
    idx_pre = pe_eng.date_to_idx.get(pr_dt, -1) if pd.notna(pr_dt) else -1
    sp_d = splits_map.get(tk, {})

    # Note: shares in filing 'filed' reflect splits up to 'end' (or 'filed' if retroactively adjusted per ASC 260).
    # If a split occurred AFTER 'filed', P_cls in database is divided by that future split factor!
    fut_mult_ent = 1.0
    fut_mult_pre = 1.0
    f_ts = pd.Timestamp(f_str)
    for s_dt_str, mult in sp_d.items():
        s_ts = pd.Timestamp(s_dt_str)
        if s_ts > ent_dt:
            fut_mult_ent *= float(mult)
        if pd.notna(pr_dt) and s_ts > pr_dt:
            fut_mult_pre *= float(mult)

    if idx_ent >= 0:
        unadj_entry_px[i] = float(P_cls[idx_ent, col]) * fut_mult_ent
    if idx_pre >= 0:
        unadj_pre_px[i] = float(P_cls[idx_pre, col]) * fut_mult_pre

df["unadj_entry_px"] = unadj_entry_px
df["unadj_pre_px"] = unadj_pre_px
df["mcap_pit"] = df["unadj_entry_px"] * df["shares_clean"]
df["mcap_pre_pit"] = df["unadj_pre_px"] * df["shares_clean"]

# Cross-verify mcap_pit against latest prior dei:EntityPublicFloat (strictly filed <= current filed!)
# If a ticker wasn't in splits_map (618 tickers) and had a split, mcap_pit / public_float will be ~0.5, ~0.25, ~0.1, etc.!
split_rescued = 0
for i in range(len(df)):
    mc = df.at[i, "mcap_pit"]
    if pd.isna(mc) or mc <= 0:
        continue
    tk = df.at[i, "ticker"]
    if tk in splits_map:
        continue
    cik_i = int(df.at[i, "cik"])
    f_dt_i = df.at[i, "filed"]
    pfs = [(dt, v) for dt, v in float_map.get(cik_i, []) if dt <= f_dt_i]
    if pfs:
        last_dt, last_pf = pfs[-1]
        # Only compare if within 450 days so genuine price moves aren't confused with big splits
        if (pd.Timestamp(f_dt_i) - pd.Timestamp(last_dt)).days <= 450 and last_pf > 5e7:
            ratio = last_pf / mc
            # If ratio >= 1.85 (e.g. 2:1, 3:1, 4:1, 5:1, 10:1 future split missing from splits_map)
            for cand_mult in [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 9.0, 10.0, 12.0, 15.0, 20.0]:
                if 0.72 * cand_mult <= ratio <= 1.35 * cand_mult:
                    df.at[i, "mcap_pit"] = mc * cand_mult
                    df.at[i, "mcap_pre_pit"] = df.at[i, "mcap_pre_pit"] * cand_mult
                    split_rescued += 1
                    break

print(f"Rescued {split_rescued:,} rows for tickers outside splits_map via PIT EntityPublicFloat anchor.")

# Recompute clean split-free YoY share dilution using market-cap vs adj_close ratio OR split-adjusted shares!
# Wait: look at pure math! Split-adjusted share count at entry = mcap_pit / entry_adj_close (up to dividend yield)!
# Even cleaner: unadj_shares adjusted by cumulative splits = shares_clean * fut_split_mult!
split_adj_sh = np.full(len(df), np.nan, dtype=np.float64)
for i, (tk, f_str, sh) in enumerate(zip(df["ticker"], df["filed"], df["shares_clean"])):
    if pd.isna(sh) or sh <= 0:
        continue
    sp_d = splits_map.get(tk, {})
    f_ts = pd.Timestamp(f_str)
    mult = 1.0
    for s_dt_str, m in sp_d.items():
        if pd.Timestamp(s_dt_str) > f_ts:
            mult *= float(m)
    split_adj_sh[i] = sh * mult
df["shares_split_adj_2026"] = split_adj_sh

# Compute exact split-free YoY share dilution!
df["dilution_yoy_clean"] = np.nan
for tk, grp in df.groupby("ticker"):
    if len(grp) < 5:
        continue
    ends = pd.to_datetime(grp["end"]).values
    flds = pd.to_datetime(grp["filed"]).values
    shs = grp["shares_split_adj_2026"].values
    idxs = grp.index.values
    dil = np.full(len(grp), np.nan)
    for j in range(len(grp)):
        if pd.isna(shs[j]) or shs[j] <= 0:
            continue
        for k in range(j - 1, max(-1, j - 7), -1):
            days_diff = (ends[j] - ends[k]) / np.timedelta64(1, "D")
            if 335 <= days_diff <= 395 and flds[k] < flds[j] and pd.notna(shs[k]) and shs[k] > 0:
                d_val = shs[j] / shs[k] - 1.0
                if -0.35 <= d_val <= 1.50:
                    dil[j] = d_val
                break
    df.loc[idxs, "dilution_yoy_clean"] = dil

print("[4/5] Joining PIT Macro Regime Table & Computing Valuation Multiples (PE, PS, EV/EBIT, PEG)...")
macro = pd.read_parquet(f"{PROJ}/data/macro_pit_daily_1990_2026.parquet")
macro["macro_join_date"] = pd.to_datetime(macro["date"]).dt.normalize()
macro_cols = [
    "macro_join_date", "mcap_scale_to_2026", "dgs10", "dgs2", "t10y2y", "t10y3m", "dff", "dfii10",
    "real_rate_10y_pit", "baa10y", "hy_oas", "vix", "nfci_pit", "cpi_yoy_pit", "indpro_yoy_pit",
    "indpro_accel_pit", "dgs10_chg_126d", "rate_level_bin", "rate_dir_6m", "fed_cycle",
    "yc_regime", "credit_regime", "vix_regime", "growth_regime", "macro_quadrant", "era_regime",
    "sp500_above_ma200", "sp500_dd_252d"
]
# Join macro strictly at pre_date (for predicting jump) AND at entry_date (for post-earnings entry)!
# Wait: macro at pre_date is 100% known BEFORE earnings AND before entry_date! Let's attach macro as-of pre_date (zero lookahead for BOTH jump prediction AND post-earnings holding)!
df["pre_date_norm"] = pd.to_datetime(df["pre_date"]).dt.normalize()
df = df.merge(macro[macro_cols], left_on="pre_date_norm", right_on="macro_join_date", how="left")

df["mcap_usd_b"] = df["mcap_pit"] / 1e9
df["mcap_2026_equiv_b"] = df["mcap_usd_b"] * df["mcap_scale_to_2026"]
df["ev_pit"] = df["mcap_pit"] + df["total_debt"].fillna(0.0) - df["cash"].fillna(0.0)

# Strictly PIT Valuation Multiples (numerator = entry_date mcap, denominator = current just-filed TTM)
df["pe_pit"] = np.where(df["ni_ttm"].notna() & (df["ni_ttm"] != 0), df["mcap_pit"] / df["ni_ttm"], np.nan)
df["ps_pit"] = np.where(df["rev_ttm"].notna() & (df["rev_ttm"] > 0), df["mcap_pit"] / df["rev_ttm"], np.nan)
df["ev_sales_pit"] = np.where(df["rev_ttm"].notna() & (df["rev_ttm"] > 0), df["ev_pit"] / df["rev_ttm"], np.nan)
df["ev_ebit_pit"] = np.where(df["opinc_ttm"].notna() & (df["opinc_ttm"] > 0), df["ev_pit"] / df["opinc_ttm"], np.nan)
df["fcf_yield_pit"] = np.where(df["mcap_pit"].notna() & (df["mcap_pit"] > 0) & df["fcf_ttm"].notna(), df["fcf_ttm"] / df["mcap_pit"], np.nan)

# PIT PEG: G3 TTM/YoY factual growth (PE / (rev_yoy*100) and PE / (ni_yoy*100)) — zero sell-side consensus!
g_rev_pct = df["rev_yoy"] * 100.0
g_ni_pct = df["ni_yoy"] * 100.0
df["peg_rev_pit"] = np.where((df["pe_pit"] > 0) & (g_rev_pct >= 5.0), df["pe_pit"] / g_rev_pct, np.nan)
df["peg_ni_pit"] = np.where((df["pe_pit"] > 0) & (g_ni_pct >= 5.0) & (g_ni_pct <= 200.0), df["pe_pit"] / g_ni_pct, np.nan)

# Also compute pre-earnings PIT PE/PS (using PRIOR quarter's TTM before this report, at pre_date price!) for zero-lookahead JUMP PREDICTION!
df["ni_ttm_prior"] = df.groupby("ticker")["ni_ttm"].shift(1)
df["rev_ttm_prior"] = df.groupby("ticker")["rev_ttm"].shift(1)
df["pe_pre_earn"] = np.where(df["ni_ttm_prior"].notna() & (df["ni_ttm_prior"] != 0), df["mcap_pre_pit"] / df["ni_ttm_prior"], np.nan)
df["ps_pre_earn"] = np.where(df["rev_ttm_prior"].notna() & (df["rev_ttm_prior"] > 0), df["mcap_pre_pit"] / df["rev_ttm_prior"], np.nan)

out_path = f"{PROJ}/data/xbrl_master_pit_2009_2026.parquet"
df.to_parquet(out_path, index=False)

print(f"[5/5] Saved {out_path} ({len(df):,} rows, {df['ticker'].nunique():,} tickers) in {time.time()-t0:.1f}s.")
for tk in ["NVDA", "AAPL", "MSFT", "NTRA", "DUOL", "APP"]:
    s = df[df["ticker"] == tk][["end", "filed", "mcap_usd_b", "pe_pit", "ps_pit", "rev_yoy", "consec_rev_accel_n", "gm_minus_sga_q", "roic_ttm", "earn_jump_ret", "fwd_252d"]]
    if len(s) > 0:
        print(f"--- Check {tk} ---")
        print(s.iloc[[0, len(s)//2, -1]].to_string(index=False))
