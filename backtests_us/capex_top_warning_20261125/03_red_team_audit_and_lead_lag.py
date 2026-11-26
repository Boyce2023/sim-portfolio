#!/usr/bin/env python3
"""
Step 3: Independent Red-Team Audit (Q8 Gate 2) on the 4-Factor CapEx Top-Warning PIT Backtest.
Audits:
1. Strict PIT / Lookahead zero-violation check (entry_dt > filed_dt on 100% rows).
2. Why F2 (Peer DD>=40%) acted as a contrarian BOTTOM signal + Peer Divergence test (peers down >=40% while target only down -10% to -35%).
3. Decompose F1 & F3 by sub16 sector inside U2_StrongCapEx_Live4 + print top-5 crashes & top-5 false-alarm winners.
4. D15 Mandatory Calendar-Quarter EW + Single-Slot 1Y Sequential Rotation (Baseline vs F1&F3 vs F4b).
5. Factor 4 (RPO) Lead-vs-Lag Physics: How much had stock ALREADY dropped before first RPO QoQ<=0 / 2Q Stagnant filing, and how much FURTHER did it fall?
6. Historical Major-Top Case Audit (2000-02 Fiber, 2007-08 EME GFC + 2008-09 +86% dead-cat trap, 2014-15 PWR/PRIM/MDR, 2018 WFE) + exact price-adjusted Live 2026-11-24 Dashboard.
"""
import warnings
import json
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

OUT_DIR = "sim-portfolio/backtests_us/capex_top_warning_20261125"
panel = pd.read_parquet(f"{OUT_DIR}/pit_panel_1996_2026_capex_top.parquet")
panel = panel[panel["entry_yr"] >= 2000].copy()

# 1. ZERO-LOOKAHEAD PIT INTEGRITY ASSERTION
n_leak = int((panel["entry_dt"] <= panel["filed_dt"]).sum())
print(f"=== AUDIT 1: STRICT PIT INTEGRITY ===")
print(f"Rows with entry_dt <= filed_dt (lookahead leak): {n_leak} / {len(panel)} (MUST BE 0)")
assert n_leak == 0, f"LOOKAHEAD LEAK DETECTED: {n_leak}"
print(f"Min lag (entry_dt - filed_dt): {(panel['entry_dt'] - panel['filed_dt']).dt.days.min()} days | Median: {(panel['entry_dt'] - panel['filed_dt']).dt.days.median():.0f} days")

# Recompute factor flags
panel["F1"] = (panel["opm_10y_pct_pit"] >= 0.85) & (panel["pe_vs_5y_med"] < 1.0)
panel["F2_40_50"] = panel["peer_dd40_share"] >= 0.50
panel["F2_30_50"] = panel["peer_dd30_share"] >= 0.50
panel["F3"] = (panel["months_since_52w_high"] >= 5.0) & (panel["below_ma200"] == 1.0)
panel["F1_and_F3"] = panel["F1"] & panel["F3"]
# Peer Divergence hypothesis: >=30% or >=40% of peers already down >=40%, WHILE target itself is only down 0% to -35% (resilient leader crack!)
panel["F2_div_30"] = (panel["peer_dd40_share"] >= 0.30) & (panel["dd_52w"] > -0.35)
panel["F2_div_40"] = (panel["peer_dd40_share"] >= 0.40) & (panel["dd_52w"] > -0.35)
panel["F2_div_med30"] = (panel["peer_dd30_share"] >= 0.50) & (panel["dd_52w"] > -0.35)

# 2. WHY DID F2 ACT AS A CONTRARIAN BOTTOM SIGNAL? + TEST PEER DIVERGENCE!
print("\n=== AUDIT 2: F2 DATES & PEER DIVERGENCE HYPOTHESIS ===")
u1 = panel[panel["pool_strong_capex"] & (panel["mcap_2026_eq_b"] >= 25.0)].dropna(subset=["alpha_1y"]).copy()
u2 = u1[u1["hit_any_live4"]].copy()

f2_hits = u1[u1["F2_40_50"]]
print("Top calendar quarters where F2_40_50 fired in Strong CapEx (U1):")
q_tbl = (
    f2_hits.groupby("entry_yq")
    .agg(n=("ticker", "count"), self_dd_med=("dd_52w", lambda s: round(s.median() * 100, 1)),
         exc1_med=("alpha_1y", lambda s: round(s.median() * 100, 1)),
         dk_pct=("alpha_1y", lambda s: round((s <= -0.20).mean() * 100, 1)))
    .sort_values("n", ascending=False)
    .head(12)
)
print(q_tbl.to_string())

print("\nPeer Divergence test (Peers already crashed while target itself still dd > -35%):")
for uname, df_u in [("U1_StrongCapEx_All", u1), ("U2_StrongCapEx_Live4", u2)]:
    for col, lbl in [
        ("F2_40_50", "Raw F2 (Peer DD40>=50%, any self DD)"),
        ("F2_div_40", "Div40 (Peer DD40>=40% & Self DD>-35%)"),
        ("F2_div_30", "Div30 (Peer DD40>=30% & Self DD>-35%)"),
        ("F2_div_med30", "Div30_50 (Peer DD30>=50% & Self DD>-35%)"),
    ]:
        blk = df_u[df_u[col].fillna(False)]
        pas = df_u[~df_u[col].fillna(False)]
        if len(blk) == 0:
            continue
        print(
            f"  {uname:20s} | {lbl:40s} | N_blk={len(blk):3d} ({len(blk)/len(df_u)*100:4.1f}%) | "
            f"SelfDD={blk['dd_52w'].median()*100:+5.1f}% | PassExc={pas['alpha_1y'].median()*100:+5.1f}% "
            f"BlkExc={blk['alpha_1y'].median()*100:+5.1f}% | PassDK={((pas['alpha_1y']<=-0.2).mean()*100):4.1f}% "
            f"BlkDK={((blk['alpha_1y']<=-0.2).mean()*100):4.1f}% | Blk3Y={blk['alpha_3y'].median()*100 if blk['alpha_3y'].notna().any() else np.nan:+5.1f}%"
        )

# 3. DECOMPOSE F1 & F3 BY SUB-SECTOR INSIDE U2 + INSPECT ALL 39 BLOCKED TRADES
print("\n=== AUDIT 3: F1 & F3 SUB-SECTOR DECOMPOSITION INSIDE U2_StrongCapEx_Live4 ===")
for sec, g in u2.groupby("sub16"):
    blk = g[g["F1_and_F3"]]
    pas = g[~g["F1_and_F3"]]
    b1 = blk["alpha_1y"].median() * 100 if len(blk) else np.nan
    b3 = blk["alpha_3y"].median() * 100 if blk["alpha_3y"].notna().any() else np.nan
    bdk = (blk["alpha_1y"] <= -0.20).mean() * 100 if len(blk) else np.nan
    p1 = pas["alpha_1y"].median() * 100 if len(pas) else np.nan
    p3 = pas["alpha_3y"].median() * 100 if pas["alpha_3y"].notna().any() else np.nan
    pdk = (pas["alpha_1y"] <= -0.20).mean() * 100 if len(pas) else np.nan
    print(f"  {sec:20s} | N={len(g):3d} N_blk={len(blk):2d} | Pass1Y={p1:+5.1f}% Blk1Y={b1:+5.1f}% | PassDK={pdk:4.1f}% BlkDK={bdk:4.1f}% | Pass3Y={p3:+5.1f}% Blk3Y={b3:+5.1f}%")

blk39 = u2[u2["F1_and_F3"]].sort_values("alpha_1y")
print("\nTop-7 WORST 1Y crashes caught by F1&F3 in U2:")
for _, r in blk39.head(7).iterrows():
    print(f"  {r['entry_dt'].strftime('%Y-%m-%d')} {r['ticker']:5s} ({r['sub16'][:8]}) DD52={r['dd_52w']*100:+5.1f}% mOff={r['months_since_52w_high']:4.1f} OPMp={r['opm_10y_pct_pit']*100:3.0f}% PE/5m={r['pe_vs_5y_med']:.2f} -> 1Y={r['fwd_1y']*100:+5.1f}% Exc1={r['alpha_1y']*100:+5.1f}% Exc3={r['alpha_3y']*100 if pd.notna(r['alpha_3y']) else np.nan:+6.1f}%")

print("\nTop-7 BIGGEST FALSE-ALARM WINNERS mistakenly blocked by F1&F3 in U2:")
for _, r in blk39.tail(7).iloc[::-1].iterrows():
    print(f"  {r['entry_dt'].strftime('%Y-%m-%d')} {r['ticker']:5s} ({r['sub16'][:8]}) DD52={r['dd_52w']*100:+5.1f}% mOff={r['months_since_52w_high']:4.1f} OPMp={r['opm_10y_pct_pit']*100:3.0f}% PE/5m={r['pe_vs_5y_med']:.2f} -> 1Y={r['fwd_1y']*100:+5.1f}% Exc1={r['alpha_1y']*100:+5.1f}% Exc3={r['alpha_3y']*100 if pd.notna(r['alpha_3y']) else np.nan:+6.1f}%")

# 4. D15 MANDATORY CALENDAR-QUARTER EW & SINGLE-SLOT 1Y SEQUENTIAL ROTATION
print("\n=== AUDIT 4: D15 CALENDAR-EW & SINGLE-SLOT SEQUENTIAL PORTFOLIO ===")


def d15_eval(df_in, name, exc_col="alpha_1y", ret_col="fwd_1y", dt_col="entry_dt", yq_col="entry_yq", scale=100.0):
    s = df_in.dropna(subset=[exc_col, ret_col]).sort_values(dt_col).copy()
    if len(s) == 0:
        return
    q_ew = s.groupby(yq_col)[exc_col].mean()
    # Single-slot 1Y non-overlapping rotation
    slots = []
    nxt = pd.Timestamp("1900-01-01")
    for _, r in s.iterrows():
        if r[dt_col] >= nxt:
            slots.append(r)
            nxt = r[dt_col] + pd.Timedelta(days=365)
    sdf = pd.DataFrame(slots)
    w = s.loc[s[exc_col] > 0, exc_col]
    l = s.loc[s[exc_col] <= 0, exc_col]
    pay = w.mean() / abs(l.mean()) if (len(w) and len(l) and l.mean() != 0) else np.nan
    print(
        f"  {name:38s} | N={len(s):3d} | RawMed={s[exc_col].median()*scale:+5.1f}% Beat={(s[exc_col]>0).mean()*100:4.1f}% "
        f"DK={(s[exc_col]<=-20/scale).mean()*100:4.1f}% Pay={pay:.2f} | "
        f"QtrEW_Mean={q_ew.mean()*scale:+5.1f}% QtrEW_Med={q_ew.median()*scale:+5.1f}% (Nq={len(q_ew)}) | "
        f"1Slot(N={len(sdf):2d}) Med={sdf[exc_col].median()*scale:+5.1f}% Mean={sdf[exc_col].mean()*scale:+5.1f}% Beat={(sdf[exc_col]>0).mean()*100:4.1f}%"
    )


d15_eval(u2, "U2 Live4 StrongCapEx BASE")
d15_eval(u2[~u2["F1_and_F3"]], "U2 Live4 Drop F1&F3")
d15_eval(u2[~(u2["F1_and_F3"] & (u2["sub16"] != "01_半导体与设备"))], "U2 Live4 Drop F1&F3 (Ex-Semi)")

q1_c = pd.read_csv(f"{OUT_DIR}/contractor_q1_signals_with_4factors.csv", parse_dates=["date"])
q1_c["yq"] = q1_c["date"].dt.to_period("Q").astype(str)
d15_eval(q1_c, "Contractor Q1 Daily BASE", exc_col="exc_1y", ret_col="ret_1y", dt_col="date", yq_col="yq", scale=1.0)
d15_eval(q1_c[~q1_c["F4_2q"].fillna(False)], "Contractor Q1 Drop F4b (2Q RPO Stag)", exc_col="exc_1y", ret_col="ret_1y", dt_col="date", yq_col="yq", scale=1.0)
d15_eval(q1_c[~q1_c["F3"].fillna(False)], "Contractor Q1 Drop F3 (>=5m&<MA200)", exc_col="exc_1y", ret_col="ret_1y", dt_col="date", yq_col="yq", scale=1.0)

# 5. FACTOR 4 (RPO) LEAD-VS-LAG PHYSICS ON EVERY >=30% CONTRACTOR CRASH (2012-2026)!
print("\n=== AUDIT 5: FACTOR 4 (RPO) LEAD-VS-LAG PHYSICS ON EVERY >=30% CONTRACTOR CRASH ===")
c_df = pd.read_parquet("eme-research/06_量化底表与13F持仓/contractor_pit_daily_2010_2026.parquet")
c_df["date"] = pd.to_datetime(c_df["date"]).dt.tz_localize(None)
c_df = c_df.sort_values(["ticker", "date"]).reset_index(drop=True)

crash_episodes = []
for tk, g in c_df.groupby("ticker"):
    g = g.reset_index(drop=True)
    # Find major peak-to-trough drawdowns >= 35% where RPO data exists around the episode
    px = g["close_sa"].values
    dts = g["date"].values
    i = 0
    n = len(g)
    while i < n - 60:
        # Check if i is a local 252d peak
        lo = max(0, i - 126)
        hi = min(n, i + 126)
        if px[i] == np.max(px[lo:hi]):
            # Look forward up to 378 trading days (1.5Y) for trough
            fut = px[i : min(n, i + 378)]
            t_rel = int(np.argmin(fut))
            t_idx = i + t_rel
            mdd = px[t_idx] / px[i] - 1.0
            if mdd <= -0.35 and t_rel >= 30:
                ep = g.iloc[i : t_idx + 1]
                # Check if RPO data existed during this episode
                if ep["rpo_qoq"].notna().any():
                    # Find FIRST day in episode where rpo_qoq <= 0 and FIRST day where rpo_2q_stagnant == 1
                    f4a_days = ep[ep["rpo_qoq"] <= 0]
                    f4b_days = ep[ep["rpo_2q_stagnant"] == 1]
                    dd_at_f4a = (f4a_days.iloc[0]["close_sa"] / px[i] - 1.0) * 100 if len(f4a_days) else np.nan
                    rem_after_f4a = (px[t_idx] / f4a_days.iloc[0]["close_sa"] - 1.0) * 100 if len(f4a_days) else np.nan
                    dt_f4a = f4a_days.iloc[0]["date"].strftime("%Y-%m-%d") if len(f4a_days) else "NEVER"

                    dd_at_f4b = (f4b_days.iloc[0]["close_sa"] / px[i] - 1.0) * 100 if len(f4b_days) else np.nan
                    rem_after_f4b = (px[t_idx] / f4b_days.iloc[0]["close_sa"] - 1.0) * 100 if len(f4b_days) else np.nan
                    dt_f4b = f4b_days.iloc[0]["date"].strftime("%Y-%m-%d") if len(f4b_days) else "NEVER"

                    crash_episodes.append({
                        "ticker": tk, "peak_dt": pd.Timestamp(dts[i]).strftime("%Y-%m-%d"),
                        "trough_dt": pd.Timestamp(dts[t_idx]).strftime("%Y-%m-%d"),
                        "total_mdd%": round(mdd * 100, 1),
                        "f4a_dt": dt_f4a, "dd_at_f4a%": round(dd_at_f4a, 1) if pd.notna(dd_at_f4a) else np.nan,
                        "rem_after_f4a%": round(rem_after_f4a, 1) if pd.notna(rem_after_f4a) else np.nan,
                        "f4b_dt": dt_f4b, "dd_at_f4b%": round(dd_at_f4b, 1) if pd.notna(dd_at_f4b) else np.nan,
                        "rem_after_f4b%": round(rem_after_f4b, 1) if pd.notna(rem_after_f4b) else np.nan,
                    })
                i = t_idx + 60
                continue
        i += 1

ep_df = pd.DataFrame(crash_episodes).sort_values(["peak_dt", "ticker"])
ep_df.to_csv(f"{OUT_DIR}/redteam_rpo_lead_lag_crashes.csv", index=False)
print(f"Found {len(ep_df)} major contractor crashes (>=35% peak-to-trough) with PIT RPO coverage:")
print(ep_df.to_string(index=False))
if len(ep_df):
    fired_a = ep_df["dd_at_f4a%"].notna()
    fired_b = ep_df["dd_at_f4b%"].notna()
    print(f"Summary F4a (RPO QoQ<=0): Fired in {fired_a.sum()}/{len(ep_df)} crashes | Median DD ALREADY suffered at trigger: {ep_df.loc[fired_a, 'dd_at_f4a%'].median():+.1f}% | Median remaining drop AFTER trigger: {ep_df.loc[fired_a, 'rem_after_f4a%'].median():+.1f}%")
    print(f"Summary F4b (2Q RPO Stag): Fired in {fired_b.sum()}/{len(ep_df)} crashes | Median DD ALREADY suffered at trigger: {ep_df.loc[fired_b, 'dd_at_f4b%'].median():+.1f}% | Median remaining drop AFTER trigger: {ep_df.loc[fired_b, 'rem_after_f4b%'].median():+.1f}%")

# 6. HISTORICAL MAJOR TOPS (2000-02, 2007-08 EME + DEAD-CAT RALLY, 2014-15, DELISTED MDR/FWLT) + EXACT PRICE-ADJUSTED LIVE 2026-11-24 DASHBOARD
print("\n=== AUDIT 6: HISTORICAL TOPS (EME 2007-09, PWR 2014-16, LRCX 2018, DELISTED MDR/FWLT) ===")
hist_cases = panel[
    ((panel["ticker"] == "EME") & (panel["entry_yr"].between(2007, 2009)))
    | ((panel["ticker"] == "PWR") & (panel["entry_yr"].between(2014, 2016)))
    | ((panel["ticker"] == "LRCX") & (panel["entry_yr"].between(2017, 2019)))
    | ((panel["ticker"] == "MTZ") & (panel["entry_yr"].between(2021, 2023)))
].sort_values(["ticker", "entry_dt"])
for _, r in hist_cases.iterrows():
    print(
        f"  {r['ticker']:4s} {r['entry_dt'].strftime('%Y-%m-%d')} DD52={r['dd_52w']*100:+5.1f}% mOff={r['months_since_52w_high']:4.1f} b200={int(r['below_ma200']) if pd.notna(r['below_ma200']) else -1} "
        f"OPMp={r['opm_10y_pct_pit']*100 if pd.notna(r['opm_10y_pct_pit']) else np.nan:3.0f}% PE/5m={r['pe_vs_5y_med'] if pd.notna(r['pe_vs_5y_med']) else np.nan:4.2f} "
        f"Peer40={r['peer_dd40_share']*100 if pd.notna(r['peer_dd40_share']) else np.nan:4.1f}% "
        f"F1={int(r['F1'])} F3={int(r['F3'])} -> 1Y={r['fwd_1y']*100 if pd.notna(r['fwd_1y']) else np.nan:+5.1f}% Exc1={r['alpha_1y']*100 if pd.notna(r['alpha_1y']) else np.nan:+5.1f}%"
    )

# Check delisted EPC bankruptcies in us_delisted_daily_permanent.parquet
px_del = pd.read_parquet("sim-portfolio/data/us_price_db/us_delisted_daily_permanent.parquet")
for dtk in ["MDR", "FWLT", "JEC", "BWC", "SHAW"]:
    sub = px_del[px_del["ticker"] == dtk].sort_values("date")
    if len(sub):
        hi_r = sub.loc[sub["adj_close"].idxmax()]
        lo_r = sub.iloc[-1]
        print(f"  DELISTED {dtk:4s}: rows={len(sub)} span={str(sub['date'].min())[:10]}..{str(sub['date'].max())[:10]} peak={hi_r['adj_close']:.2f} ({str(hi_r['date'])[:10]}) -> last={lo_r['adj_close']:.2f} exit={lo_r['exit_type']} term_ret={lo_r['terminal_delist_ret']}")

# Fix exact LIVE 2026-11-24 price-adjusted PE_vs_5Y_med for the key watchlist
print("\n=== EXACT PRICE-ADJUSTED LIVE 2026-11-24 DASHBOARD (TOP CAPEX + CONTROLS) ===")
px_act = pd.read_parquet("sim-portfolio/data/us_price_db/all_daily.parquet", columns=["date", "ticker", "adj_close"])
px_act["date"] = pd.to_datetime(px_act["date"]).dt.tz_localize(None)
lat_dt = px_act["date"].max()
px_rec = px_act[px_act["date"] >= lat_dt - pd.Timedelta(days=400)].sort_values(["ticker", "date"])
lat_fund = panel.sort_values("entry_dt").groupby("ticker").last().to_dict(orient="index")

key_watch = ["EME", "FIX", "PWR", "MTZ", "DY", "VRT", "ETN", "LRCX", "AMAT", "KLAC", "NVDA", "AVGO", "MU", "AMD", "TER", "TXN", "CAT", "URI", "DELL", "SCCO", "LLY", "NFLX", "SPGI", "MSFT", "AAPL"]
for tk in key_watch:
    g = px_rec[px_rec["ticker"] == tk]
    if len(g) < 200 or tk not in lat_fund:
        continue
    adj = g["adj_close"].values.astype(float)
    w252 = adj[-252:]
    hi_i = int(np.argmax(w252))
    cur = float(w252[-1])
    dd52 = (cur / float(w252[hi_i]) - 1.0) * 100
    m_off = (len(w252) - 1 - hi_i) / 21.0
    b200 = int(cur < float(np.mean(adj[-200:])))
    lf = lat_fund[tk]
    # Exact live price adjustment for PE_vs_5Y_med!
    px_ratio = cur / lf["entry_px_adj"] if (pd.notna(lf.get("entry_px_adj")) and lf["entry_px_adj"] > 0) else 1.0
    live_pe_vs = lf["pe_vs_5y_med"] * px_ratio if pd.notna(lf.get("pe_vs_5y_med")) else np.nan
    opm_p = lf.get("opm_10y_pct_pit", np.nan)
    f1 = int(pd.notna(opm_p) and opm_p >= 0.85 and pd.notna(live_pe_vs) and live_pe_vs < 1.0)
    f3 = int(m_off >= 5.0 and b200 == 1)
    rpo_q = lf.get("rpo_qoq", np.nan)
    rpo_y = lf.get("rpo_yoy", np.nan)
    f4 = int(pd.notna(rpo_q) and rpo_q <= 0.0) if pd.notna(rpo_q) else -1
    print(
        f"  {tk:5s} ({lf['sub16'][:8]}) px={cur:7.2f} DD52={dd52:+5.1f}% mOff={m_off:4.1f} b200={b200} | "
        f"OPMp={opm_p*100 if pd.notna(opm_p) else np.nan:3.0f}% LivePE/5m={live_pe_vs if pd.notna(live_pe_vs) else np.nan:4.2f} | "
        f"F1={f1} F3={f3} F1&F3={int(f1 and f3)} | RPO_QoQ={rpo_q*100 if pd.notna(rpo_q) else np.nan:+5.1f}% RPO_YoY={rpo_y*100 if pd.notna(rpo_y) else np.nan:+5.1f}%"
    )
