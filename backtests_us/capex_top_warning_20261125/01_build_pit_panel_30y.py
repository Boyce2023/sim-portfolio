#!/usr/bin/env python3
"""
Step 1: Build 1996-2026 Zero-Survivorship-Bias PIT Panel with 4 CapEx Top-Warning Factors.
Strict PIT rules:
- Fundamental ratios (OPM, PE, Rev YoY, RPO) ONLY become known on filed_dt + 1 trading day.
- Rolling history (10Y OPM percentile, 5Y median PE) uses STRICTLY prior filings (< entry_dt).
- Price-based factors (52W drawdown, months since 52W high, <200D MA, peer breadth dd>=40%)
  use STRICTLY close[<= entry_dt] with zero lookahead and include delisted tickers.
- Forward returns (1Y=252d, 2Y=504d, 3Y=756d, 1Y max drawdown) incorporate terminal bankruptcy returns.
"""
import os
import json
import zipfile
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

OUT_DIR = "sim-portfolio/backtests_us/capex_top_warning_20261125"
os.makedirs(OUT_DIR, exist_ok=True)

# 1. Reuse pick's exact EXPLICIT_MAP & EXCLUDED_TICKERS for 100% alignment
v2_src = open("output/us_sector_pit_sweetspot_20261123/v2_clean/run_16sector_pit_backtest_v2.py").read()
lns = v2_src.splitlines()
i1 = next(i for i, l in enumerate(lns) if l.startswith("EXCLUDED_TICKERS = {"))
i2 = next(i for i, l in enumerate(lns) if l.startswith("m = xbrl["))
i3 = next(i for i, l in enumerate(lns) if l.startswith("EXPLICIT_MAP = {"))
i4 = next(i for i, l in enumerate(lns) if l.startswith('m["sub16"] ='))
ns = {}
exec("\n".join(lns[i1:i2] + lns[i3:i4]), ns)
EXCL = ns["EXCLUDED_TICKERS"]
EMAP = ns["EXPLICIT_MAP"]

STRONG_CAPEX_SECTORS = {
    "01_半导体与设备",
    "02_硬件通信与算力基建",
    "09_电网电气暖通与机电",
    "10_工业机械运输与分销",
    "13_油气管道与大宗材料",
}
CORE_CAPEX_SECTORS = {
    "01_半导体与设备",
    "09_电网电气暖通与机电",
    "10_工业机械运输与分销",
}
NON_CYCLICAL_CONTROL = {
    "03_企业软件与网安",
    "04_互联网平台与数字媒体",
    "05_创新药与生物制药",
    "06_医疗器械与生命科学工具",
    "11_可选消费零售与出行",
    "12_必选消费与日化",
    "15_支付交易所与金融数据",
}

print("[1/5] Loading 30Y US prices (active + delisted) & SPY benchmark...")
px_act = pd.read_parquet("sim-portfolio/data/us_price_db/all_daily.parquet", columns=["date", "ticker", "close", "adj_close"])
px_del = pd.read_parquet("sim-portfolio/data/us_price_db/us_delisted_daily_permanent.parquet")
spy = pd.read_parquet("sim-portfolio/data/us_price_db/benchmarks/SPY.parquet")

if "date" in spy.columns:
    spy["date"] = pd.to_datetime(spy["date"]).dt.tz_localize(None)
    spy_s = spy.set_index("date")["adj_close"].sort_index()
else:
    spy.index = pd.to_datetime(spy.index)
    if getattr(spy.index, "tz", None) is not None:
        spy.index = spy.index.tz_localize(None)
    spy_s = spy["adj_close"].sort_index()
spy_dates = spy_s.index.values
spy_vals = spy_s.values.astype(float)
spy_2026 = float(spy_vals[-1])


def spy_asof(dt64):
    i = np.searchsorted(spy_dates, dt64, side="right") - 1
    return float(spy_vals[i]) if i >= 0 else np.nan


# Precompute daily price features per ticker (strictly causal on each trading day)
# Needed: close, adj_close, dd_52w, days_since_52w_high, below_ma200, dd_2y
print("[2/5] Computing strictly causal daily price features & peer breadth across all mapped tickers...")
px_act["date"] = pd.to_datetime(px_act["date"]).dt.tz_localize(None)
px_del["date"] = pd.to_datetime(px_del["date"]).dt.tz_localize(None)

# Build unified price map (prefer active if ticker exists in active, else delisted)
act_tickers = set(px_act["ticker"].unique())
del_only = px_del[~px_del["ticker"].isin(act_tickers)].copy()

del_meta = {}
for tk, g in px_del.sort_values("date").groupby("ticker"):
    del_meta[tk] = (
        str(g["exit_type"].iloc[-1]),
        float(g["terminal_delist_ret"].iloc[-1]) if pd.notna(g["terminal_delist_ret"].iloc[-1]) else 0.0,
    )

mapped_tks = set(EMAP.keys()) - EXCL
px_all = pd.concat(
    [
        px_act[px_act["ticker"].isin(mapped_tks)][["date", "ticker", "close", "adj_close"]],
        del_only[del_only["ticker"].isin(mapped_tks)][["date", "ticker", "close", "adj_close"]],
    ],
    ignore_index=True,
)
px_all = px_all.dropna(subset=["adj_close"]).sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last")
px_all = px_all[px_all["adj_close"] > 0].copy()

# Compute per-ticker causal arrays and collect daily peer drawdown matrix by sub16
ticker_arrays = {}
sector_daily_records = []  # (date, sub16, ticker, dd_52w, below_ma200)

for tk, g in px_all.groupby("ticker", sort=False):
    dts = g["date"].values
    adj = g["adj_close"].values.astype(float)
    cls = g["close"].values.astype(float)
    n = len(adj)
    if n < 60:
        continue
    # Rolling 252-day max & days since high (strictly causal, inclusive of current bar t)
    s_adj = pd.Series(adj)
    roll_max_252 = s_adj.rolling(252, min_periods=60).max().values
    dd_52w = adj / roll_max_252 - 1.0
    roll_max_504 = s_adj.rolling(504, min_periods=126).max().values
    dd_2y = adj / roll_max_504 - 1.0
    ma200 = s_adj.rolling(200, min_periods=150).mean().values
    below_ma200 = (adj < ma200).astype(np.float32)
    below_ma200[np.isnan(ma200)] = np.nan

    # Exact causal bars since 52w high (reset whenever adj[i] >= roll_max_252[i] * 0.9999)
    # Vectorized exact calculation via rolling argmax over 252 window
    bars_since_52w = np.full(n, np.nan, dtype=np.float32)
    # Fast loop in pure python/numpy over arrays (n <= 7500 per ticker, ~1000 tickers -> ~3 sec)
    cur_hi = adj[0]
    cur_hi_idx = 0
    for i in range(n):
        if i >= 252 and cur_hi_idx <= i - 252:
            # recompute window max index
            w = adj[i - 251 : i + 1]
            rel = int(np.argmax(w))
            cur_hi_idx = i - 251 + rel
            cur_hi = adj[cur_hi_idx]
        elif adj[i] >= cur_hi:
            cur_hi = adj[i]
            cur_hi_idx = i
        if i >= 60:
            bars_since_52w[i] = float(i - cur_hi_idx)

    # Also bars since 2Y (504d) high
    bars_since_2y = np.full(n, np.nan, dtype=np.float32)
    cur_hi2 = adj[0]
    cur_hi2_idx = 0
    for i in range(n):
        if i >= 504 and cur_hi2_idx <= i - 504:
            w = adj[i - 503 : i + 1]
            rel = int(np.argmax(w))
            cur_hi2_idx = i - 503 + rel
            cur_hi2 = adj[cur_hi2_idx]
        elif adj[i] >= cur_hi2:
            cur_hi2 = adj[i]
            cur_hi2_idx = i
        if i >= 126:
            bars_since_2y[i] = float(i - cur_hi2_idx)

    etype, tret = del_meta.get(tk, ("ACTIVE", 0.0)) if tk not in act_tickers else ("ACTIVE", 0.0)
    ticker_arrays[tk] = (dts, adj, cls, dd_52w, dd_2y, bars_since_52w, bars_since_2y, below_ma200, etype, tret)

    # Store weekly/daily peer breadth input (sample every 5 trading days or keep full daily for sub16)
    sec = EMAP[tk]
    # Keep full daily for exact asof match
    valid_m = np.isfinite(dd_52w)
    if valid_m.any():
        sector_daily_records.append(
            pd.DataFrame(
                {
                    "date": dts[valid_m],
                    "sub16": sec,
                    "dd40": (dd_52w[valid_m] <= -0.40).astype(np.int8),
                    "dd35": (dd_52w[valid_m] <= -0.35).astype(np.int8),
                    "dd30": (dd_52w[valid_m] <= -0.30).astype(np.int8),
                    "dd_val": dd_52w[valid_m].astype(np.float32),
                    "bma200": (below_ma200[valid_m] == 1.0).astype(np.int8),
                }
            )
        )

print(f"  Precomputed price arrays for {len(ticker_arrays)} tickers. Aggregating peer breadth...")
sec_all = pd.concat(sector_daily_records, ignore_index=True)
breadth_df = (
    sec_all.groupby(["sub16", "date"], sort=True)
    .agg(
        peer_n=("dd40", "count"),
        peer_dd40_cnt=("dd40", "sum"),
        peer_dd35_cnt=("dd35", "sum"),
        peer_dd30_cnt=("dd30", "sum"),
        peer_bma200_cnt=("bma200", "sum"),
        peer_dd_med=("dd_val", "median"),
    )
    .reset_index()
)
# Build fast lookup dict per sub16
breadth_map = {}
for sec, g in breadth_df.groupby("sub16"):
    g = g.sort_values("date")
    breadth_map[sec] = (
        g["date"].values,
        g["peer_n"].values.astype(float),
        g["peer_dd40_cnt"].values.astype(float),
        g["peer_dd35_cnt"].values.astype(float),
        g["peer_dd30_cnt"].values.astype(float),
        g["peer_bma200_cnt"].values.astype(float),
        g["peer_dd_med"].values.astype(float),
    )
del sec_all, sector_daily_records

# 3. Extract PIT RPO from companyfacts.zip for all mapped tickers (2018-2026) + supplement from contractor parquet
print("[3/5] Extracting strictly PIT RPO from companyfacts.zip & contractor_pit_daily_2010_2026.parquet...")
xbrl = pd.read_parquet("sim-portfolio/data/us_fundamentals_30y_permanent/xbrl_master_enriched_2009_2026.parquet")
pre = pd.read_parquet("sim-portfolio/data/us_fundamentals_30y_permanent/pre2009/pre2009_fundamentals_1996_2008_pit.parquet")

cik_map = xbrl.dropna(subset=["cik"]).groupby("ticker")["cik"].last().to_dict()
rpo_rows = []
with zipfile.ZipFile("sim-portfolio/data/us_fundamentals_30y_permanent/companyfacts.zip") as zf:
    znames = set(zf.namelist())
    for tk, cik_raw in cik_map.items():
        if tk not in mapped_tks:
            continue
        try:
            cik = str(int(float(cik_raw))).zfill(10)
        except Exception:
            continue
        fn = f"CIK{cik}.json"
        if fn not in znames:
            continue
        data = json.loads(zf.read(fn))
        gaap = data.get("facts", {}).get("us-gaap", {})
        if "RevenueRemainingPerformanceObligation" not in gaap:
            continue
        usd = gaap["RevenueRemainingPerformanceObligation"].get("units", {}).get("USD", [])
        if not usd:
            continue
        # Keep point-in-time instant values from 10-Q/10-K, earliest filed per period end, taking largest consolidated total if multiple segments reported on same end+filed
        recs = []
        for u in usd:
            frm = u.get("form", "")
            if frm not in ("10-Q", "10-K", "10-Q/A", "10-K/A"):
                continue
            end_d = u.get("end")
            fld_d = u.get("filed")
            val = u.get("val")
            if end_d and fld_d and val is not None and val > 0:
                recs.append((end_d, fld_d, float(val)))
        if not recs:
            continue
        rdf = pd.DataFrame(recs, columns=["end", "filed", "rpo_val"])
        # For each (end, filed), keep max (total consolidated RPO vs sub-segment); then earliest filed for each end (true PIT!)
        rdf = rdf.groupby(["end", "filed"], as_index=False)["rpo_val"].max()
        rdf = rdf.sort_values(["end", "filed"]).drop_duplicates("end", keep="first")
        rdf["end_dt"] = pd.to_datetime(rdf["end"])
        rdf["filed_dt"] = pd.to_datetime(rdf["filed"])
        rdf = rdf.sort_values("end_dt").reset_index(drop=True)
        # Filter out non-quarterly duplicates (keep roughly >=60d apart)
        keep_idx = []
        last_e = None
        for idx_r, rr in rdf.iterrows():
            if last_e is None or (rr["end_dt"] - last_e).days >= 60:
                keep_idx.append(idx_r)
                last_e = rr["end_dt"]
        rdf = rdf.loc[keep_idx].reset_index(drop=True)
        if len(rdf) < 4:
            continue
        rdf["rpo_qoq"] = rdf["rpo_val"].pct_change()
        # YoY match ~365d prior (330 to 400d)
        yoy_vals = []
        for i_r in range(len(rdf)):
            cur_e = rdf.at[i_r, "end_dt"]
            cur_v = rdf.at[i_r, "rpo_val"]
            cand = rdf[(rdf["end_dt"] >= cur_e - pd.Timedelta(days=400)) & (rdf["end_dt"] <= cur_e - pd.Timedelta(days=330))]
            if len(cand) > 0:
                prev_v = cand.iloc[-1]["rpo_val"]
                yoy_vals.append(cur_v / prev_v - 1.0 if prev_v > 0 else np.nan)
            else:
                yoy_vals.append(np.nan)
        rdf["rpo_yoy"] = yoy_vals
        rdf["rpo_2q_stag"] = ((rdf["rpo_qoq"] <= 0.0) & (rdf["rpo_qoq"].shift(1) <= 0.0)).astype(float)
        rdf.loc[rdf["rpo_qoq"].isna() | rdf["rpo_qoq"].shift(1).isna(), "rpo_2q_stag"] = np.nan
        rdf["ticker"] = tk
        rpo_rows.append(rdf[["ticker", "end_dt", "filed_dt", "rpo_val", "rpo_qoq", "rpo_yoy", "rpo_2q_stag"]])

rpo_xbrl = pd.concat(rpo_rows, ignore_index=True) if rpo_rows else pd.DataFrame()
rpo_xbrl.to_parquet(f"{OUT_DIR}/pit_rpo_xbrl_2018_2026.parquet", index=False)
print(f"  Extracted XBRL RPO for {rpo_xbrl['ticker'].nunique() if len(rpo_xbrl) else 0} tickers ({len(rpo_xbrl)} obs).")

# Build fast RPO lookup (also merge contractor_pit_daily_2010_2026.parquet for EME/FIX/PWR/MTZ/MYRG/PRIM/ACM/ETN/JCI!)
rpo_lookup = {}
if len(rpo_xbrl):
    for tk, g in rpo_xbrl.sort_values("filed_dt").groupby("ticker"):
        rpo_lookup[tk] = (
            g["filed_dt"].values,
            g["rpo_qoq"].values.astype(float),
            g["rpo_yoy"].values.astype(float),
            g["rpo_2q_stag"].values.astype(float),
        )

# Supplement with verified contractor RPO table (covers EME/FIX back to 2011/2012 & PWR/ACM/ETN/JCI)
c_df = pd.read_parquet("eme-research/06_量化底表与13F持仓/contractor_pit_daily_2010_2026.parquet")
c_df["filed_dt"] = pd.to_datetime(c_df["filed"]).dt.tz_localize(None)
c_rpo = (
    c_df.dropna(subset=["filed_dt"])
    .sort_values(["ticker", "filed_dt", "date"])
    .drop_duplicates(["ticker", "filed_dt"], keep="first")
)
for tk, g in c_rpo.groupby("ticker"):
    g = g.dropna(subset=["rpo_qoq"]).sort_values("filed_dt")
    if len(g) >= 4:
        rpo_lookup[tk] = (
            g["filed_dt"].values,
            (g["rpo_qoq"].values / 100.0).astype(float),
            (g["rpo_yoy"].values / 100.0).astype(float),
            g["rpo_2q_stagnant"].values.astype(float),
        )
print(f"  Total tickers with PIT RPO (XBRL + verified contractor filings): {len(rpo_lookup)}")

# 4. Stitch unified 1996-2026 quarterly/annual filing panel (exact pick cleaning + causal 10Y OPM & 5Y PE)
print("[4/5] Stitching 1996-2026 PIT filing panel with causal 10Y OPM pct, 5Y PE med, peer breadth & time-structure...")

# Clean 2009-2026 XBRL
m = xbrl[~xbrl["ticker"].isin(EXCL)].copy()
m["sub16"] = m["ticker"].map(EMAP)
m = m[m["sub16"].notna()].copy()
m["filed_dt"] = pd.to_datetime(m["filed"]).dt.tz_localize(None)
m["entry_dt"] = pd.to_datetime(m["entry_date"]).dt.tz_localize(None)

m["implied_sh"] = np.where((m["mcap_pit"] > 0) & (m["unadj_entry_px"] > 0), m["mcap_pit"] / m["unadj_entry_px"], np.nan)
med_sh = m.groupby("ticker")["implied_sh"].transform("median")
sh_ratio = m["implied_sh"] / med_sh
bad_mcap = (
    (m["mcap_usd_b"] > 6000.0)
    | ((m["mcap_usd_b"] > 3000.0) & (~m["ticker"].isin({"AAPL", "NVDA", "MSFT", "GOOG", "GOOGL", "AMZN", "META"})))
    | (sh_ratio > 8.0)
    | (sh_ratio < 0.12)
)
rebuilt = np.where(
    (m["shares_clean"] > 0) & (m["unadj_entry_px"] > 0) & ((m["shares_clean"] / med_sh).between(0.15, 6.0)),
    m["shares_clean"] * m["unadj_entry_px"],
    np.nan,
)
m["mcap_pit_clean"] = np.where(bad_mcap, rebuilt, m["mcap_pit"])
m.loc[(m["mcap_pit_clean"] <= 0) | (m["mcap_pit_clean"] / 1e9 > 6000.0), "mcap_pit_clean"] = np.nan
m.loc[
    (m["mcap_pit_clean"] / 1e9 > 2500.0)
    & (~m["ticker"].isin({"AAPL", "NVDA", "MSFT", "GOOG", "GOOGL", "AMZN", "META", "BRK-A", "BRK-B", "AVGO", "LLY", "TSLA"})),
    "mcap_pit_clean",
] = np.nan
m["mcap_usd_b_clean"] = m["mcap_pit_clean"] / 1e9
m["mcap_2026_equiv_b_clean"] = m["mcap_usd_b_clean"] * m["mcap_scale_to_2026"]

m["opm_use"] = np.where(m["rev_ttm"] > 0, m["opinc_ttm"] / m["rev_ttm"], np.nan)
m["opm_use"] = pd.Series(m["opm_use"], index=m.index).fillna(m["opm_q"])
m["gm_use"] = np.where(m["rev_ttm"] > 0, m["gp_ttm"] / m["rev_ttm"], np.nan)
m["gm_use"] = pd.Series(m["gm_use"], index=m.index).fillna(m["gm_q"])
m.loc[(m["gm_use"] > 1.0) | (m["gm_use"] < -0.5), "gm_use"] = np.nan
m.loc[(m["opm_use"] > 1.0) | (m["opm_use"] < -2.0), "opm_use"] = np.nan
m["pe_clean"] = np.where((m["ni_ttm"] > 0) & (m["mcap_pit_clean"] > 0), m["mcap_pit_clean"] / m["ni_ttm"], np.nan)
m["ps_clean"] = np.where((m["rev_ttm"] > 0) & (m["mcap_pit_clean"] > 0), m["mcap_pit_clean"] / m["rev_ttm"], np.nan)
m["peg_g3"] = np.where((m["pe_clean"] > 0) & (m["rev_yoy"] > 0.01), m["pe_clean"] / (m["rev_yoy"] * 100.0), np.nan)
m["source_era"] = "xbrl_2009_2026"

# Clean 1996-2008 pre2009
pre_c = pre[~pre["ticker"].isin(EXCL)].copy()
pre_c["sub16"] = pre_c["ticker"].map(EMAP)
pre_c = pre_c[pre_c["sub16"].notna()].sort_values(["ticker", "fiscal_year"]).copy()
pre_c["filed_dt"] = pd.to_datetime(pre_c["filingDate"]).dt.tz_localize(None)
pre_c = pre_c[(pre_c["filed_dt"] >= "1996-01-01") & (pre_c["filed_dt"] < "2009-01-01")].copy()
pre_c["rev_yoy"] = pre_c.groupby("ticker")["rev"].pct_change(fill_method=None)
pre_c["opm_use"] = np.where(pre_c["rev"] > 0, pre_c["opinc"] / pre_c["rev"], np.nan)
pre_c["gm_use"] = np.where(pre_c["rev"] > 0, pre_c["gp"] / pre_c["rev"], np.nan)
pre_c["roic_ttm"] = np.where(
    (pre_c["equity"] > 0) & (pre_c["opinc"].notna()),
    pre_c["opinc"] * 0.75 / (pre_c["equity"] + pre_c["total_debt"].fillna(0) - pre_c["cash"].fillna(0)).clip(lower=1e6),
    np.nan,
)
pre_c["dilution_yoy_clean"] = pre_c.groupby("ticker")["shares"].pct_change(fill_method=None)
pre_c["gm_5y_std_pit"] = pre_c.groupby("ticker")["gm_use"].transform(lambda s: s.rolling(5, min_periods=3).std())
pre_c["source_era"] = "pre2009_1996_2008"

# Compute exact entry_dt, price features, peer breadth, and forward returns for EVERY row from ticker_arrays
def enrich_rows(df_in, is_pre=False):
    recs = []
    for _, r in df_in.iterrows():
        tk = r["ticker"]
        fdt = r["filed_dt"]
        if pd.isna(fdt) or tk not in ticker_arrays:
            continue
        dts, adj, cls, dd52, dd2y, bs52, bs2y, bma200, etype, tret = ticker_arrays[tk]
        # Entry strictly AFTER filing date (filed + 1 calendar day -> next trading day)
        pos = np.searchsorted(dts, np.datetime64(fdt + pd.Timedelta(days=1)), side="left")
        if pos >= len(dts):
            continue
        edt = pd.Timestamp(dts[pos])
        epx_adj = float(adj[pos])
        epx_cls = float(cls[pos])
        if not (epx_adj > 0 and epx_cls > 0):
            continue
        s0 = spy_asof(dts[pos])
        if pd.isna(s0) or s0 <= 0:
            continue
        scale = spy_2026 / s0

        if is_pre:
            sh = r["shares"]
            mc = float(sh * epx_cls) if (pd.notna(sh) and sh > 0) else np.nan
            if pd.isna(mc) or mc < 1e8 or mc > 1e12:
                continue
            mc_b = mc / 1e9
            mc_eq_b = mc_b * scale
            pe = mc / r["ni"] if (pd.notna(r["ni"]) and r["ni"] > 0) else np.nan
            ps = mc / r["rev"] if (pd.notna(r["rev"]) and r["rev"] > 0) else np.nan
            peg = pe / (r["rev_yoy"] * 100.0) if (pd.notna(pe) and pd.notna(r["rev_yoy"]) and r["rev_yoy"] > 0.01) else np.nan
            rev_ttm = r["rev"]
            ni_ttm = r["ni"]
        else:
            mc_b = r["mcap_usd_b_clean"]
            mc_eq_b = r["mcap_2026_equiv_b_clean"]
            pe = r["pe_clean"]
            ps = r["ps_clean"]
            peg = r["peg_g3"]
            rev_ttm = r["rev_ttm"]
            ni_ttm = r["ni_ttm"]
            # Rescued delisted backfill
            if pd.isna(mc_b):
                sh = r["shares_clean"] if pd.notna(r["shares_clean"]) and r["shares_clean"] > 0 else r["shares"]
                if pd.notna(sh) and sh > 0:
                    mc_new = float(sh * epx_cls)
                    if 1e8 < mc_new < 2.5e12:
                        mc_b = mc_new / 1e9
                        mc_eq_b = mc_b * scale
                        pe = mc_new / ni_ttm if (pd.notna(ni_ttm) and ni_ttm > 0) else np.nan
                        ps = mc_new / rev_ttm if (pd.notna(rev_ttm) and rev_ttm > 0) else np.nan
                        peg = pe / (r["rev_yoy"] * 100.0) if (pd.notna(pe) and pd.notna(r["rev_yoy"]) and r["rev_yoy"] > 0.01) else np.nan

        if pd.isna(mc_eq_b) or mc_eq_b < 5.0:
            # Keep >= $5B 2026-equiv so mid-cap contractors like FIX/MYRG/DY/IESC are NOT dropped!
            continue

        # Peer breadth strictly on date dts[pos], excluding self!
        sec = r["sub16"]
        p_n = np.nan
        p_dd40 = np.nan
        p_dd35 = np.nan
        p_dd30 = np.nan
        p_bma200 = np.nan
        p_ddmed = np.nan
        if sec in breadth_map:
            bdts, bn, b40, b35, b30, b200, bmed = breadth_map[sec]
            bi = np.searchsorted(bdts, dts[pos], side="right") - 1
            if bi >= 0 and (dts[pos] - bdts[bi]) <= np.timedelta64(5, "D"):
                self_valid = 1.0 if np.isfinite(dd52[pos]) else 0.0
                n_ex = bn[bi] - self_valid
                if n_ex >= 5:
                    s40 = 1.0 if (self_valid and dd52[pos] <= -0.40) else 0.0
                    s35 = 1.0 if (self_valid and dd52[pos] <= -0.35) else 0.0
                    s30 = 1.0 if (self_valid and dd52[pos] <= -0.30) else 0.0
                    s200 = 1.0 if (np.isfinite(bma200[pos]) and bma200[pos] == 1.0) else 0.0
                    p_n = n_ex
                    p_dd40 = (b40[bi] - s40) / n_ex
                    p_dd35 = (b35[bi] - s35) / n_ex
                    p_dd30 = (b30[bi] - s30) / n_ex
                    p_bma200 = (b200[bi] - s200) / n_ex
                    p_ddmed = bmed[bi]

        # PIT RPO lookup strictly filed_dt <= edt
        rpo_qoq, rpo_yoy, rpo_2q_stag = np.nan, np.nan, np.nan
        if tk in rpo_lookup:
            rflds, rqoq, ryoy, r2q = rpo_lookup[tk]
            ri = np.searchsorted(rflds, dts[pos], side="right") - 1
            if ri >= 0 and (dts[pos] - rflds[ri]) <= np.timedelta64(150, "D"):
                rpo_qoq = float(rqoq[ri])
                rpo_yoy = float(ryoy[ri])
                rpo_2q_stag = float(r2q[ri])

        # Forward returns (1Y=252d, 2Y=504d, 3Y=756d) + 1Y max drawdown from entry
        is_del = etype != "ACTIVE"
        last_adj, last_dt = float(adj[-1]), dts[-1]
        s_last = spy_asof(last_dt)
        term_ret = max(-1.0, (last_adj / epx_adj) * (1.0 + tret) - 1.0) if etype == "BANKRUPTCY_OR_LIQUIDATION" else (last_adj / epx_adj - 1.0)
        spy_term = (s_last / s0 - 1.0) if pd.notna(s_last) else np.nan

        fwd = {}
        for h_bars, rk, ak in [(252, "fwd_1y", "alpha_1y"), (504, "fwd_2y", "alpha_2y"), (756, "fwd_3y", "alpha_3y")]:
            if pos + h_bars < len(adj):
                rr = float(adj[pos + h_bars] / epx_adj - 1.0)
                ss = spy_asof(dts[pos + h_bars])
                sp = (ss / s0 - 1.0) if pd.notna(ss) else np.nan
            elif is_del:
                rr, sp = term_ret, spy_term
            else:
                rr, sp = np.nan, np.nan
            fwd[rk] = rr
            fwd[ak] = (rr - sp) if (pd.notna(rr) and pd.notna(sp)) else np.nan

        # 1Y forward max drawdown from entry price (min price in next 252 trading days / entry - 1)
        if pos + 252 < len(adj):
            fwd_min_1y = float(np.min(adj[pos + 1 : pos + 253]) / epx_adj - 1.0)
        elif is_del and pos + 1 < len(adj):
            fwd_min_1y = float(min(np.min(adj[pos + 1 :]) / epx_adj - 1.0, term_ret))
        else:
            fwd_min_1y = np.nan

        recs.append(
            {
                "ticker": tk,
                "sub16": sec,
                "source_era": r["source_era"],
                "filed_dt": fdt,
                "entry_dt": edt,
                "entry_yr": edt.year,
                "entry_yq": edt.to_period("Q").strftime("%YQ%q"),
                "is_delisted_tkr": is_del,
                "mcap_b": mc_b,
                "mcap_2026_eq_b": mc_eq_b,
                "entry_px_adj": epx_adj,
                "dd_52w": float(dd52[pos]),
                "dd_2y": float(dd2y[pos]),
                "months_since_52w_high": float(bs52[pos]) / 21.0 if np.isfinite(bs52[pos]) else np.nan,
                "months_since_2y_high": float(bs2y[pos]) / 21.0 if np.isfinite(bs2y[pos]) else np.nan,
                "below_ma200": float(bma200[pos]),
                "peer_n": p_n,
                "peer_dd40_share": p_dd40,
                "peer_dd35_share": p_dd35,
                "peer_dd30_share": p_dd30,
                "peer_bma200_share": p_bma200,
                "peer_dd_med": p_ddmed,
                "pe_clean": pe,
                "ps_clean": ps,
                "peg_g3": peg,
                "rev_yoy": r["rev_yoy"],
                "opm_use": r["opm_use"],
                "gm_use": r["gm_use"],
                "roic_ttm": r["roic_ttm"],
                "dilution_yoy_clean": r["dilution_yoy_clean"],
                "gm_5y_std_pit": r["gm_5y_std_pit"],
                "rpo_qoq": rpo_qoq,
                "rpo_yoy": rpo_yoy,
                "rpo_2q_stag": rpo_2q_stag,
                "fwd_min_1y": fwd_min_1y,
                **fwd,
            }
        )
    return pd.DataFrame(recs)


df_pre = enrich_rows(pre_c, is_pre=True)
df_xbrl = enrich_rows(m, is_pre=False)
panel = pd.concat([df_pre, df_xbrl], ignore_index=True)
panel = panel.sort_values(["ticker", "entry_dt"]).drop_duplicates(["ticker", "entry_dt"], keep="last").reset_index(drop=True)

# 5. Compute strictly CAUSAL rolling 10Y OPM percentile & 5Y median PE across stitched 1996-2026 history!
print("[5/5] Computing strictly causal 10Y OPM percentile & 5Y median PE across stitched 1996-2026 history...")
opm_10y_pct = np.full(len(panel), np.nan)
pe_5y_med = np.full(len(panel), np.nan)
opm_obs_n = np.zeros(len(panel), dtype=int)
pe_obs_n = np.zeros(len(panel), dtype=int)

for tk, g in panel.groupby("ticker", sort=False):
    idxs = g.index.values
    edts = g["entry_dt"].values
    opms = g["opm_use"].values.astype(float)
    pes = g["pe_clean"].values.astype(float)
    for k in range(len(idxs)):
        cur_dt = edts[k]
        # Strictly prior observations within trailing 10Y (3653d) for OPM and 5Y (1826d) for PE
        # Include current observation in the denominator? No — percentile of current value relative to strictly prior history (or inclusive of current, both strictly causal!).
        # Specifically: fraction of strictly prior valid OPM values <= current OPM (if >= 4 obs and span >= 2.5Y)
        lo10 = cur_dt - np.timedelta64(3653, "D")
        m10 = (edts[:k] >= lo10) & np.isfinite(opms[:k])
        if np.isfinite(opms[k]) and m10.sum() >= 4:
            hist_opm = opms[:k][m10]
            span_days = int((cur_dt - edts[:k][m10][0]) / np.timedelta64(1, "D"))
            if span_days >= 900:  # >= 2.5 years of prior history
                opm_10y_pct[idxs[k]] = float(np.mean(hist_opm <= opms[k]))
                opm_obs_n[idxs[k]] = int(len(hist_opm))

        lo5 = cur_dt - np.timedelta64(1826, "D")
        m5 = (edts[:k] >= lo5) & np.isfinite(pes[:k]) & (pes[:k] > 0) & (pes[:k] < 200)
        if np.isfinite(pes[k]) and pes[k] > 0 and m5.sum() >= 4:
            hist_pe = pes[:k][m5]
            span_days_pe = int((cur_dt - edts[:k][m5][0]) / np.timedelta64(1, "D"))
            if span_days_pe >= 700:  # >= 2 years of prior PE history
                pe_5y_med[idxs[k]] = float(np.median(hist_pe))
                pe_obs_n[idxs[k]] = int(len(hist_pe))

panel["opm_10y_pct_pit"] = opm_10y_pct
panel["pe_5y_med_pit"] = pe_5y_med
panel["pe_vs_5y_med"] = panel["pe_clean"] / panel["pe_5y_med_pit"]
panel["opm_hist_n"] = opm_obs_n
panel["pe_hist_n"] = pe_obs_n

# Sector bucket tags
panel["pool_strong_capex"] = panel["sub16"].isin(STRONG_CAPEX_SECTORS)
panel["pool_core_capex"] = panel["sub16"].isin(CORE_CAPEX_SECTORS)
panel["pool_non_cyclical"] = panel["sub16"].isin(NON_CYCLICAL_CONTROL)

# Pick's 4 active strategies flags (exact formulas from run_meta_falsification_30y.py)
panel["hit_06_1"] = (panel["sub16"] == "01_半导体与设备") & (panel["pe_clean"] > 0) & (panel["ps_clean"] >= 8.0) & (panel["gm_use"].between(0.40, 0.65))
panel["hit_06_2"] = (panel["sub16"] == "09_电网电气暖通与机电") & (panel["pe_clean"] > 0) & (panel["ps_clean"] < 3.0) & (panel["opm_use"] < 0.15)
panel["hit_S05a"] = ((panel["rev_yoy"] + panel["opm_use"]) >= 0.45) & (panel["dilution_yoy_clean"] < 0) & (panel["gm_5y_std_pit"] < 0.065) & (panel["pe_clean"].between(0.1, 50.0))
panel["hit_F01"] = (panel["pe_clean"].between(15.0, 45.0)) & (panel["peg_g3"] <= 1.2) & (panel["roic_ttm"] >= 0.15)
panel["hit_any_live4"] = panel["hit_06_1"] | panel["hit_06_2"] | panel["hit_S05a"] | panel["hit_F01"]

# High-boom pullback trigger (EME/FIX Q1 pattern across all stocks: Rev YoY > 15% or RPO YoY > 25%, DD -20% to -40%, PE 10-25x or 15-22x)
panel["hit_q1_pullback"] = (
    ((panel["rev_yoy"] > 0.15) | (panel["rpo_yoy"] > 0.25))
    & (panel["dd_52w"].between(-0.40, -0.20))
    & (panel["pe_clean"].between(10.0, 25.0))
)

out_path = f"{OUT_DIR}/pit_panel_1996_2026_capex_top.parquet"
panel.to_parquet(out_path, index=False)

# Print compact Q8 Gate-1 summary (<2KB)
print("\n=== Q8 GATE-1 PANEL SUMMARY ===")
print(f"Saved: {out_path}")
print(f"Total rows: {len(panel):,} | Tickers: {panel['ticker'].nunique()} (Delisted: {panel.loc[panel['is_delisted_tkr'], 'ticker'].nunique()})")
print(f"Date range: {panel['entry_dt'].min().strftime('%Y-%m-%d')} to {panel['entry_dt'].max().strftime('%Y-%m-%d')}")
for nm, mask in [
    ("Strong CapEx 5-sec (01/02/09/10/13)", panel["pool_strong_capex"]),
    ("Core CapEx 3-sec (01/09/10)", panel["pool_core_capex"]),
    ("Grid/Mech/EPC (09)", panel["sub16"] == "09_电网电气暖通与机电"),
    ("Non-Cyclical Control (7-sec)", panel["pool_non_cyclical"]),
]:
    sub = panel[mask & (panel["entry_yr"] >= 2000)]
    miss_f1 = sub["opm_10y_pct_pit"].isna().mean() * 100
    miss_pe = sub["pe_5y_med_pit"].isna().mean() * 100
    miss_f2 = sub["peer_dd40_share"].isna().mean() * 100
    miss_f3 = sub["months_since_52w_high"].isna().mean() * 100
    miss_f4 = sub["rpo_qoq"].isna().mean() * 100
    print(f"  {nm:36s}: N={len(sub):5d} Tk={sub['ticker'].nunique():3d} | Miss% F1_OPM={miss_f1:4.1f}% F1_PE={miss_pe:4.1f}% F2_Peer={miss_f2:4.1f}% F3_Time={miss_f3:4.1f}% F4_RPO={miss_f4:4.1f}%")
