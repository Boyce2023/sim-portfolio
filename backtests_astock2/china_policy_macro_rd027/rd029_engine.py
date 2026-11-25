#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD029 Pure Causal Day-by-Day ETF Simulation Engine (2000-01-04 ~ 2026-11-25).
Strictly D12 compliant (NO yfinance). Zero cap10m. Zero shift(-1) / full-sample peeking.
"""
import os
import sys
import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
from pit_utils import build_pit_mapper, causal_rolling_pct, pit_asof_join
from build_pillar3_sector_traffic_lights import SECTOR_COL_MAP

assert "yfinance" not in sys.modules, "D12 violation"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
CACHE_DIR = os.path.join(ROOT, "output/china_policy_macro_rd027_20261125/rd029_daybyday_etf/cache")
PILLAR_DIR = os.path.join(ROOT, "output/china_policy_macro_rd027_20261125/data_pillars")
POLY_DIR = os.path.join(ROOT, "output/csrc_policy_100factors_20261114/policy_polymarket_v1")
NT_DIR = os.path.join(ROOT, "output/csrc_policy_100factors_20261114/national_team")

SECTORS = sorted(SECTOR_COL_MAP.keys())


def _map_event_obs_idx(event_dates: pd.Series, cal_dates: list[str], cal_arr: np.ndarray, d2i: dict[str, int]) -> np.ndarray:
    """
    Strictly causal observation index on trading calendar:
      - If event_date is a trading day -> obs_idx = d2i[event_date] (known by end of day, trades at obs_idx+1 open).
      - If weekend/holiday -> obs_idx = first trading day > event_date (NEVER leaks back to prior Friday!).
    """
    n = len(cal_dates)
    out = np.full(len(event_dates), n + 999, dtype=int)
    for k, raw_d in enumerate(event_dates):
        dt = str(raw_d)[:10]
        if dt in d2i:
            out[k] = d2i[dt]
        else:
            pos = int(np.searchsorted(cal_arr, dt, side="right"))
            if pos < n:
                out[k] = pos
    return out


def score_v3_causal(v3_raw: pd.DataFrame, nt_ev: pd.DataFrame, cutoff_date: str | None = None) -> pd.DataFrame:
    """Compute strictly causal V3.0 National Team live & EOD scores without shift(-1) or future data."""
    d = v3_raw.copy()
    if cutoff_date is not None:
        d = d[d["date"] <= cutoff_date].copy()
    d = d.sort_values("date").reset_index(drop=True)
    if d.empty:
        return pd.DataFrame(columns=["date", "v3_score_live", "v3_score_eod"])

    d["c300_prev_close"] = d["c300_close"].shift(1)
    d["c300_ret"] = d["c300_close"] / d["c300_prev_close"] - 1.0
    d["c300_pullup"] = (d["c300_close"] - d["c300_low"]) / d["c300_prev_close"]
    d["c1000_ret"] = d["c1000_close"] / d["c1000_close"].shift(1) - 1.0
    d["c300_ma20"] = d["c300_close"].rolling(20, min_periods=20).mean()
    d["c300_dd60"] = d["c300_close"] / d["c300_close"].rolling(60, min_periods=10).max() - 1.0
    d["c300_ret20"] = d["c300_close"] / d["c300_close"].shift(20) - 1.0

    d["etf22_amt_spike"] = d["etf22_amt_yi"] / d["etf22_amt_yi"].rolling(20, min_periods=10).median().shift(1)
    d["core10_amt_spike"] = d["core10_amt_yi"] / d["core10_amt_yi"].rolling(20, min_periods=10).median().shift(1)
    d["etf22_wflow_5d"] = d["etf22_wflow_yi"].rolling(5, min_periods=1).sum()
    d["wflow_pct_aum"] = d["etf22_wflow_yi"] / d["etf22_aum_yi"].shift(1).replace(0, np.nan) * 100.0

    consec, c_run = [], 0
    for v, nsh in zip(d["etf22_wflow_yi"].fillna(0.0), d["etf22_n_sh"].fillna(0)):
        c_run = c_run + 1 if (nsh > 0 and v >= 30.0) else 0
        consec.append(c_run)
    d["nt_tapering_stop"] = (
        (pd.Series(consec).shift(1).fillna(0) >= 3)
        & (d["etf22_wflow_5d"].shift(1).fillna(0) >= 220.0)
        & (d["etf22_wflow_yi"].fillna(0.0) <= 0.0)
    ).astype(int)

    d["if0_spike"] = d["IF0_vol"] / d["IF0_vol"].rolling(20, min_periods=10).median().shift(1)
    d["if0_basis_pct"] = (d["IF0_close"] / d["c300_close"] - 1.0) * 100.0
    d["if0_basis_chg1"] = d["if0_basis_pct"] - d["if0_basis_pct"].shift(1)

    dt_s = pd.to_datetime(d["date"])
    d["ym"] = dt_s.dt.strftime("%Y-%m")
    # Causal monthly 3rd-Friday delivery day check (pure calendar rule, no future date peeking!)
    is_deliv = np.zeros(len(d), dtype=bool)
    seen_deliv_ym = set()
    for idx_r, ts in enumerate(dt_s):
        ym_val = ts.strftime("%Y-%m")
        if ym_val in seen_deliv_ym:
            continue
        fd = pd.Timestamp(year=ts.year, month=ts.month, day=1)
        ff = 1 + (4 - fd.weekday()) % 7
        tf = pd.Timestamp(year=ts.year, month=ts.month, day=ff + 14)
        if ts >= tf:
            is_deliv[idx_r] = True
            seen_deliv_ym.add(ym_val)
    d["is_deliv"] = is_deliv

    d["sec9_flow_5d_yi"] = d["sec9_flow_1d_yi"].rolling(5, min_periods=1).sum()
    d["lhb_5d_net_yi"] = d["lhb_net_yi"].fillna(0.0).rolling(5, min_periods=1).sum()
    d["lag1_wflow_5d"] = d["etf22_wflow_5d"].shift(1)
    d["lag1_sec9_5d"] = d["sec9_flow_5d_yi"].shift(1)
    d["lag1_lhb_5d"] = d["lhb_5d_net_yi"].shift(1)

    dates_list = d["date"].tolist()
    d2i = {dt: i for i, dt in enumerate(dates_list)}
    arr_d = np.array(dates_list)
    ev_nt = nt_ev[nt_ev["cat"] == "NT_OFFICIAL_ENTRY"].copy()
    if cutoff_date is not None:
        ev_nt = ev_nt[ev_nt["event_date"].astype(str).str[:10] <= cutoff_date].copy()
    obs_nt = _map_event_obs_idx(ev_nt["event_date"], dates_list, arr_d, d2i)
    off_5d = np.zeros(len(d), dtype=int)
    for oi in obs_nt:
        if 0 <= oi < len(d):
            off_5d[oi : min(len(d), oi + 5)] = 1
    d["official_nt_5d"] = off_5d

    live_scores, eod_scores = [], []
    for _, r in d.iterrows():
        s_live, s_eod = 20, 20
        is_weak = (pd.notna(r["c300_ma20"]) and r["c300_close"] < r["c300_ma20"]) or (pd.notna(r["c300_dd60"]) and r["c300_dd60"] <= -0.06)
        is_deep = pd.notna(r["c300_dd60"]) and r["c300_dd60"] <= -0.08
        is_high = (pd.notna(r["c300_ma20"]) and r["c300_close"] > r["c300_ma20"]) and (pd.notna(r["c300_ret20"]) and r["c300_ret20"] >= 0.05)
        is_bubble = (pd.notna(r["c300_ma20"]) and r["c300_close"] > r["c300_ma20"]) and (pd.notna(r["c300_ret20"]) and r["c300_ret20"] >= 0.15)

        if is_high:
            s_live -= 18
            s_eod -= 18
            if is_bubble:
                s_live -= 6
                s_eod -= 6
        else:
            if is_weak:
                s_live += 6
                s_eod += 6
            if is_deep:
                s_live += 4
                s_eod += 4

        if int(r["official_nt_5d"]) == 1:
            s_live += 12
            s_eod += 12

        c10_spk = float(r["core10_amt_spike"]) if pd.notna(r["core10_amt_spike"]) else 0.0
        e22_spk = float(r["etf22_amt_spike"]) if pd.notna(r["etf22_amt_spike"]) else 0.0
        spk = max(c10_spk, e22_spk)
        pullup = float(r["c300_pullup"]) if pd.notna(r["c300_pullup"]) else 0.0
        t1_c = int(r["core10_t1_cnt16"]) if pd.notna(r["core10_t1_cnt16"]) else 0
        t2_c = int(r["core10_t2_cnt16"]) if pd.notna(r["core10_t2_cnt16"]) else 0

        if spk >= 2.0:
            s_live += 16
            s_eod += 12
        elif spk >= 1.5:
            s_live += 10
            s_eod += 7
        elif spk >= 1.2 and pullup >= 0.008:
            s_live += 4
            s_eod += 3

        if spk >= 1.5 and pullup >= 0.008:
            s_live += 4
            s_eod += 3

        if t1_c >= 2 and t2_c >= 2:
            s_live += 8
        elif (t1_c + t2_c) >= 5:
            s_live += 6
        elif t1_c >= 2 and t2_c == 0:
            s_live -= 4

        l5 = float(r["lag1_wflow_5d"]) if pd.notna(r["lag1_wflow_5d"]) else 0.0
        if l5 >= 150.0:
            s_live += 4

        wf = float(r["etf22_wflow_yi"]) if pd.notna(r["etf22_wflow_yi"]) else 0.0
        wpct = float(r["wflow_pct_aum"]) if pd.notna(r["wflow_pct_aum"]) else 0.0
        wf5 = float(r["etf22_wflow_5d"]) if pd.notna(r["etf22_wflow_5d"]) else 0.0
        t1f = float(r["t1_flow_yi"]) if pd.notna(r["t1_flow_yi"]) else 0.0
        t2f = float(r["t2_flow_yi"]) if pd.notna(r["t2_flow_yi"]) else 0.0
        if wf >= 90.0 or wpct >= 1.5:
            s_eod += 12
        elif wf >= 40.0 or wpct >= 0.7:
            s_eod += 7
        if wf5 >= 150.0:
            s_eod += 4
        if t1f >= 50.0 and t2f >= 25.0:
            s_eod += 6
        elif t1f >= 75.0 and t2f < 15.0:
            s_eod -= 5

        hw_cnt = int(r["hw16_sync_cnt"]) if pd.notna(r["hw16_sync_cnt"]) else 0
        sq_cnt = int(r["sq_active_cnt"]) if pd.notna(r["sq_active_cnt"]) else 0
        b4o = float(r["big4_oil_ret"]) if pd.notna(r["big4_oil_ret"]) else 0.0
        c1k = float(r["c1000_ret"]) if pd.notna(r["c1000_ret"]) else 0.0
        if spk >= 1.5 and hw_cnt >= 4:
            pts_hw = 10 + (4 if (hw_cnt >= 8 and sq_cnt >= 3) else 0)
            s_live += pts_hw
            s_eod += pts_hw
        elif spk < 1.3 and (((b4o - c1k) >= 0.020) or (b4o >= 0.008 and c1k <= -0.008)):
            s_live -= 10
            s_eod -= 10

        if_spk = float(r["if0_spike"]) if pd.notna(r["if0_spike"]) else 0.0
        if_bas = float(r["if0_basis_pct"]) if pd.notna(r["if0_basis_pct"]) else 0.0
        bas_c1 = float(r["if0_basis_chg1"]) if pd.notna(r["if0_basis_chg1"]) else 0.0
        is_del = bool(r["is_deliv"])
        if spk >= 1.8 and if_spk >= 1.5 and (not is_del):
            s_live -= 10
            s_eod -= 10
        elif spk >= 1.8 and if_spk < 1.5 and (not is_del):
            s_live += 6
            s_eod += 6
        if spk >= 1.5 and if_bas <= -0.5:
            s_live += 5
            s_eod += 5
        if spk >= 1.5 and if_bas <= -0.1 and bas_c1 >= 0.25:
            s_live += 3
            s_eod += 3
        if (is_weak and if_bas >= 0.0) or (if_bas >= 0.30):
            s_live -= 5
            s_eod -= 5

        f8_dump = int(r["fund8_dump_cnt"]) if pd.notna(r["fund8_dump_cnt"]) else 0
        if f8_dump >= 3:
            s_live -= 6
            s_eod -= 6
        s9_lag = float(r["lag1_sec9_5d"]) if pd.notna(r["lag1_sec9_5d"]) else 0.0
        lhb_lag = float(r["lag1_lhb_5d"]) if pd.notna(r["lag1_lhb_5d"]) else 0.0
        if s9_lag <= -35.0 or lhb_lag <= -40.0:
            s_live -= 4
        s9_cur = float(r["sec9_flow_5d_yi"]) if pd.notna(r["sec9_flow_5d_yi"]) else 0.0
        lhb_cur = float(r["lhb_5d_net_yi"]) if pd.notna(r["lhb_5d_net_yi"]) else 0.0
        if s9_cur <= -35.0:
            s_eod -= 4
        if lhb_cur <= -40.0:
            s_eod -= 4
        if wf <= -80.0:
            s_eod -= 12
        elif int(r["nt_tapering_stop"]) == 1:
            s_eod -= 5
        if wf5 <= -250.0:
            s_eod -= 8

        live_scores.append(int(np.clip(s_live, 0, 100)))
        eod_scores.append(int(np.clip(s_eod, 0, 100)))

    d["v3_score_live"] = live_scores
    d["v3_score_eod"] = eod_scores
    return d[["date", "v3_score_live", "v3_score_eod", "etf22_amt_spike", "core10_amt_spike", "etf22_wflow_yi"]]


def build_causal_state(cutoff_date: str | None = None, wp_lag_mode: str = "after_16") -> dict:
    """
    Build 100% zero-lookahead daily market + ETF + policy state up to cutoff_date.
    wp_lag_mode:
      - 'after_16': month M available strictly after M+1 day 16 (e.g., Oct -> >= Nov 17)
      - 'full_1m':  month M available on M+2 day 1 (e.g., Oct -> >= Dec 1)
    """
    mp = pd.read_parquet(os.path.join(CACHE_DIR, "daily_market_panel_2000_20261125.parquet"))
    etf = pd.read_parquet(os.path.join(CACHE_DIR, "core4_etfs_to_20261125.parquet"))
    v3_raw = pd.read_parquet(os.path.join(CACHE_DIR, "v3_raw_panel_2016_20261125.parquet"))
    bd = pd.read_parquet(os.path.join(CACHE_DIR, "breadth_daily_2005_20261125.parquet"))
    m4 = pd.read_parquet(os.path.join(CACHE_DIR, "macro_pain_daily_2005_20261125.parquet"))
    wp = pd.read_parquet(os.path.join(PILLAR_DIR, "pillar1_waterpool_monthly.parquet"))
    tm = pd.read_parquet(os.path.join(PILLAR_DIR, "pillar2_top_meetings_diff.parquet"))
    tl = pd.read_parquet(os.path.join(PILLAR_DIR, "pillar3_sector_traffic_lights.parquet"))
    ev = pd.read_parquet(os.path.join(POLY_DIR, "master_events_v2_20261125.parquet"))
    nt_ev = pd.read_json(os.path.join(NT_DIR, "nt_official_events.json"))

    # Truncate ALL tables strictly at cutoff_date BEFORE any rolling/joining
    mp = mp.sort_values("date").reset_index(drop=True)
    if cutoff_date is not None:
        mp = mp[mp["date"] <= cutoff_date].copy().reset_index(drop=True)
        etf = etf[etf["date"] <= cutoff_date].copy()
        v3_raw = v3_raw[v3_raw["date"] <= cutoff_date].copy()
        bd = bd[bd["date_str"] <= cutoff_date].copy()
        m4 = m4[m4["date_str"] <= cutoff_date].copy()
        tm = tm[tm["event_date"].astype(str).str[:10] <= cutoff_date].copy()
        tl = tl[tl["event_date"].astype(str).str[:10] <= cutoff_date].copy()
        ev = ev[ev["event_date"].astype(str).str[:10] <= cutoff_date].copy()
        nt_ev = nt_ev[nt_ev["event_date"].astype(str).str[:10] <= cutoff_date].copy()

    # Drop all forward-looking columns from ev so they physically cannot leak
    keep_ev_cols = [c for c in ev.columns if not c.startswith(("ret_", "fwd")) and c not in ("n_subseq_policies", "min_policy_lead_days", "has_policy_within_15d", "has_policy_within_30d", "has_policy_within_60d", "has_policy_within_90d")]
    ev = ev[keep_ev_cols].copy()

    dates = mp["date"].tolist()
    cal_arr = np.array(dates)
    d2i = {d: i for i, d in enumerate(dates)}
    n = len(dates)

    # Recompute causal rolling features on mp strictly after truncation
    mp["bench_cc_ret"] = mp["csi300_cc_ret"].fillna(mp["large10_cc_ret"]).fillna(mp["sh_comp_cc_ret"])
    mp["bench_oc_ret"] = mp["csi300_oc_ret"].fillna(mp["large10_oc_ret"]).fillna(mp["sh_comp_oc_ret"])
    mp["bench_gap_ret"] = mp["csi300_gap_ret"].fillna(mp["large10_gap_ret"]).fillna(mp["sh_comp_gap_ret"])

    # Reconstruct open/close levels for synthetic portfolio indices (ew, micro30, large10, tech_board, bench)
    for ps in ["ew", "micro30", "large10", "tech_board", "bench"]:
        cc_col = f"{ps}_cc_ret"
        gap_col = f"{ps}_gap_ret"
        if cc_col not in mp.columns:
            continue
        valid = mp[cc_col].notna()
        cl = (1.0 + mp[cc_col].fillna(0.0)).cumprod()
        prev_cl = cl.shift(1).fillna(1.0)
        op = prev_cl * (1.0 + mp[gap_col].fillna(0.0))
        if valid.any():
            first_idx = int(valid.idxmax())
            if first_idx > 1:
                cl.iloc[: first_idx - 1] = np.nan
                op.iloc[:first_idx] = np.nan
            # Keep trailing NaN rows (e.g. 2026-11-25 where stock-level DB is not yet updated) NaN so fallback index is used!
            cl = cl.where(valid, np.nan)
            op = op.where(valid, np.nan)
        mp[f"{ps}_open"] = op
        mp[f"{ps}_close"] = cl
    mp["bench_level"] = (1.0 + mp["bench_cc_ret"].fillna(0.0)).cumprod()
    mp["bench_ma20"] = mp["bench_level"].rolling(20, min_periods=20).mean()
    mp["bench_ma60"] = mp["bench_level"].rolling(60, min_periods=20).mean()
    mp["bench_ret_20d"] = mp["bench_level"] / mp["bench_level"].shift(20) - 1.0
    mp["bench_ret_60d"] = mp["bench_level"] / mp["bench_level"].shift(60) - 1.0
    mp["bench_dd_60d"] = mp["bench_level"] / mp["bench_level"].rolling(60, min_periods=10).max() - 1.0
    mp["bench_dd_250d"] = mp["bench_level"] / mp["bench_level"].rolling(250, min_periods=30).max() - 1.0
    mp["bench_vol_20d"] = mp["bench_cc_ret"].rolling(20, min_periods=10).std() * np.sqrt(242.0)
    mp["bench_vol_60d"] = mp["bench_cc_ret"].rolling(60, min_periods=20).std() * np.sqrt(242.0)
    mp["mkt_amt_spike_20d"] = mp["total_amount_yi"] / mp["total_amount_yi"].rolling(20, min_periods=10).median().shift(1)
    mp["amount_pct_250d"] = causal_rolling_pct(mp["total_amount_yi"], window=250, min_periods=30)

    # Align 4 Core ETFs onto master calendar with causal spike and tradable flags
    etf_panels = {}
    for code in ["510050", "510300", "510500", "512100"]:
        sub = etf[etf["code"] == code].sort_values("date").copy()
        sub["amt_spike"] = sub["amount"] / sub["amount"].rolling(20, min_periods=10).median().shift(1)
        m = pd.DataFrame({"date": dates}).merge(
            sub[["date", "open", "close", "open_hfq", "close_hfq", "amount", "amt_spike"]],
            on="date", how="left"
        )
        m["tradable"] = m["open_hfq"].notna() & m["close_hfq"].notna() & (m["open_hfq"] > 0)
        # Forward-fill last MTM close during rare 1-2d split suspensions after first listing day
        first_valid = m["tradable"].idxmax() if m["tradable"].any() else n
        m["mtm_close_hfq"] = m["close_hfq"]
        if first_valid < n:
            m.loc[first_valid:, "mtm_close_hfq"] = m.loc[first_valid:, "close_hfq"].ffill()
        etf_panels[code] = m

    # Build continuous ETF_CHAIN_2000_2026:
    #   2000-01-04 ~ 2005-02-22: sh_comp (spot proxy)
    #   2005-02-23 ~ 2012-05-27: 510050 HFQ
    #   2012-05-28 ~ 2026-11-25: 510300 HFQ
    chain_asset = np.where(
        cal_arr < "2005-02-23", "sh_comp",
        np.where(cal_arr < "2012-05-28", "510050", "510300")
    )

    # Precompute daily per-asset open/close/tradable arrays for fast daily loop
    asset_data = {
        "sh_comp": {
            "open": mp["sh_comp_open"].to_numpy(float),
            "close": mp["sh_comp_close"].to_numpy(float),
            "raw_open": mp["sh_comp_open"].to_numpy(float),
            "raw_close": mp["sh_comp_close"].to_numpy(float),
            "tradable": mp["sh_comp_open"].notna().to_numpy(bool),
        }
    }
    for code in ["510050", "510300", "510500", "512100"]:
        ep = etf_panels[code]
        asset_data[code] = {
            "open": ep["open_hfq"].to_numpy(float),
            "close": ep["mtm_close_hfq"].to_numpy(float),
            "raw_open": ep["open"].to_numpy(float),
            "raw_close": ep["close"].to_numpy(float),
            "tradable": ep["tradable"].to_numpy(bool),
        }

    # Causal 20d/60d realized vol on ETF_CHAIN_2000_2026 returns
    chain_ret = np.zeros(n, dtype=float)
    for i in range(1, n):
        a = chain_asset[i]
        # On switch day, use same-day asset oc/cc or prev asset close if continuous; use same asset close/prev_close when valid
        if chain_asset[i] == chain_asset[i - 1]:
            c1, c0 = asset_data[a]["close"][i], asset_data[a]["close"][i - 1]
            chain_ret[i] = (c1 / c0 - 1.0) if (np.isfinite(c1) and np.isfinite(c0) and c0 > 0) else 0.0
        else:
            o1, c1 = asset_data[a]["open"][i], asset_data[a]["close"][i]
            chain_ret[i] = (c1 / o1 - 1.0) if (np.isfinite(c1) and np.isfinite(o1) and o1 > 0) else 0.0
    chain_s = pd.Series(chain_ret)
    mp["chain_vol_20d"] = chain_s.rolling(20, min_periods=10).std().to_numpy(float) * np.sqrt(242.0)
    mp["chain_vol_60d"] = chain_s.rolling(60, min_periods=20).std().to_numpy(float) * np.sqrt(242.0)
    mp["chain_ma20"] = pd.Series((1.0 + chain_s).cumprod()).rolling(20, min_periods=20).mean().to_numpy(float)

    # Causal V3 scores (2016+) - drop any pre-existing non-causal V3 columns first
    v3_sc = score_v3_causal(v3_raw, nt_ev, cutoff_date=cutoff_date)
    drop_v3_cols = [c for c in v3_sc.columns if c != "date" and c in mp.columns]
    if drop_v3_cols:
        mp = mp.drop(columns=drop_v3_cols)
    mp = mp.merge(v3_sc, on="date", how="left")
    mp["e50_amt_spike"] = etf_panels["510050"]["amt_spike"].to_numpy(float)
    mp["e300_amt_spike"] = etf_panels["510300"]["amt_spike"].to_numpy(float)

    # Strict PIT Waterpool Monthly join (fixes Wave 3 Critic days 1~9 leak!)
    _, strictly_after, _, _ = build_pit_mapper(pd.to_datetime(dates))
    wp = wp.sort_values("month").copy().reset_index(drop=True)
    wp["eq_supply_pct_mcap"] = (
        wp["ipo_raised_yi"].fillna(0.0)
        + wp["refinance_yi"].fillna(0.0)
        + wp["insider_net_reduce_yi"].fillna(0.0).clip(lower=0.0)
    ) / wp["eom_float_mcap_yi"].replace(0, np.nan) * 100.0
    if wp_lag_mode == "full_1m":
        wp["avail_strict"] = [
            pd.Timestamp(year=(pd.Period(m, "M") + 2).year, month=(pd.Period(m, "M") + 2).month, day=1)
            for m in wp["month"]
        ]
    else:
        # Strictly AFTER M+1 day 16 (i.e. >= 17th of next month, first trading day > 16th)
        wp["avail_strict"] = [
            strictly_after(pd.Timestamp(year=(pd.Period(m, "M") + 1).year, month=(pd.Period(m, "M") + 1).month, day=16))
            for m in wp["month"]
        ]
    wp = wp.dropna(subset=["avail_strict"]).copy()
    if cutoff_date is not None:
        wp = wp[wp["avail_strict"] <= pd.Timestamp(cutoff_date)].copy()
    wp = wp.sort_values("month").reset_index(drop=True)
    wp["wp_drain_pct_5y"] = causal_rolling_pct(wp["drain_total_pct_mcap"], window=60, min_periods=12)
    wp["wp_net_pct_5y"] = causal_rolling_pct(wp["net_waterpool_trading_pct_mcap"], window=60, min_periods=12)

    base_dt_df = pd.DataFrame({"date": pd.to_datetime(dates)})
    wp_cols = ["ipo_raised_yi", "eq_supply_pct_mcap", "drain_total_pct_mcap", "wp_drain_pct_5y", "wp_net_pct_5y"]
    wp_j = pit_asof_join(base_dt_df, wp, "avail_strict", wp_cols, max_staleness_days=95)
    for c in wp_cols:
        mp[c] = wp_j[c].to_numpy(float)

    # Breadth & Macro Pain (strictly <= cutoff_date)
    mp = mp.merge(
        bd[["date_str", "pct_above_ma200", "erp_csi300_pct", "margin_balance_yi"]].rename(columns={"date_str": "date"}),
        on="date", how="left",
    )
    mp["margin_chg_20d_pct"] = mp["margin_balance_yi"] / mp["margin_balance_yi"].shift(20) - 1.0
    mp = mp.merge(
        m4[["date_str", "cn_bond_10y", "cn_policy_rate_1y"]].rename(columns={"date_str": "date"}),
        on="date", how="left",
    )
    mp["rate_cut_flag"] = (mp["cn_policy_rate_1y"] < mp["cn_policy_rate_1y"].shift(1)).fillna(False)

    # Map all policy events to strictly causal obs_idx
    ev_obs = _map_event_obs_idx(ev["event_date"], dates, cal_arr, d2i)
    ev["obs_idx"] = ev_obs
    ev_valid = ev[ev["obs_idx"] < n].copy()

    # S1 pre-2016 hard stabilizing tool (PBOC / Huijin / Ministries)
    m_s1_hard = (
        (ev_valid["action_verb_stage"] == "HARD_ACTION_NOW")
        & (ev_valid["market_rescue_signal"] >= 1)
        & (ev_valid["authority_level"].isin([
            "PBOC_HARD_TOOL", "HUIJIN_NATIONAL_TEAM", "FISCAL_SASAC",
            "STATE_COUNCIL_EXEC", "FSDC_VICE_PREMIER", "JOINT_MINISTRY_SCIO",
            "CSRC_OFFICIAL", "CSRC_CHAIR"
        ]))
    )
    # Four-Gate masks
    m_g1 = (ev_valid["ipo_supply_tightening"] >= 1) | (ev_valid["share_reduction_crackdown"] >= 1) | ev_valid["hard_levers_joined"].fillna("").str.contains("IPO_PAUSE", regex=True)
    m_g2 = (
        (ev_valid["action_verb_stage"] == "HARD_ACTION_NOW")
        & (
            ev_valid["authority_level"].isin(["PBOC_HARD_TOOL", "HUIJIN_NATIONAL_TEAM", "FISCAL_SASAC", "STATE_COUNCIL_EXEC", "FSDC_VICE_PREMIER", "JOINT_MINISTRY_SCIO"])
            | ev_valid["hard_levers_joined"].fillna("").str.contains("PBOC_SFISF|HUIJIN_BUY|FISCAL_CAPITAL_INJECT", regex=True)
        )
        & (ev_valid["market_rescue_signal"] >= 1)
    )
    m_g3 = ev_valid["authority_level"].isin([
        "POLITBURO", "CENTRAL_ECON_CONF", "CENTRAL_FIN_CONF",
        "STATE_COUNCIL_EXEC", "STATE_COUNCIL_NINE_ARTICLES", "FSDC_VICE_PREMIER"
    ]) & ((ev_valid["market_rescue_signal"] >= 1) | (ev_valid["liquidity_long_term_capital"] >= 1))
    m_tight = (ev_valid["market_rescue_signal"] <= -1) | (ev_valid["speculation_fraud_crackdown"] >= 2)

    nt_ev_obs = _map_event_obs_idx(nt_ev["event_date"], dates, cal_arr, d2i)
    nt_entry_idx = [int(oi) for oi, cat in zip(nt_ev_obs, nt_ev["cat"]) if cat == "NT_OFFICIAL_ENTRY" and oi < n]

    tm_obs = _map_event_obs_idx(tm["event_date"], dates, cal_arr, d2i)
    tm["obs_idx"] = tm_obs
    tm_v = tm[tm["obs_idx"] < n].copy()
    tm_up_idx = tm_v.loc[(tm_v["delta_macro_stance"] >= 1) | (tm_v["delta_equity"] >= 1) | (tm_v["surprise_direction"] > 0), "obs_idx"].to_numpy(int)
    tm_tight_idx = tm_v.loc[(tm_v["delta_macro_stance"] <= -2) | (tm_v["tone_deleveraging"] <= -2), "obs_idx"].to_numpy(int)

    # Precompute daily boolean signal arrays strictly using [<= t]
    def _window_active(obs_indices: np.ndarray, lookback_td: int) -> np.ndarray:
        arr = np.zeros(n, dtype=bool)
        for oi in obs_indices:
            if 0 <= oi < n:
                arr[oi : min(n, oi + lookback_td)] = True
        return arr

    s1_hard_5d = _window_active(np.concatenate([ev_valid.loc[m_s1_hard, "obs_idx"].to_numpy(int), np.array(nt_entry_idx, dtype=int)]), 5)
    g1_ev_60d = _window_active(ev_valid.loc[m_g1, "obs_idx"].to_numpy(int), 60)
    g2_ev_22d = _window_active(np.concatenate([ev_valid.loc[m_g2, "obs_idx"].to_numpy(int), np.array(nt_entry_idx, dtype=int)]), 22)
    rate_cut_22d = _window_active(np.where(mp["rate_cut_flag"].to_numpy(bool))[0], 22)
    g3_ev_22d = _window_active(np.concatenate([ev_valid.loc[m_g3, "obs_idx"].to_numpy(int), tm_up_idx]), 22)
    tight_20d = _window_active(np.concatenate([ev_valid.loc[m_tight, "obs_idx"].to_numpy(int), tm_tight_idx]), 20)
    tight_5d = _window_active(np.concatenate([ev_valid.loc[m_tight, "obs_idx"].to_numpy(int), tm_tight_idx]), 5)

    # Causal S1 Signals (Pre-2016 vs 2016+ V3)
    weak_mkt = (mp["bench_level"] < mp["bench_ma20"]) | (mp["bench_dd_60d"] <= -0.06)
    etf_or_mkt_spk = np.nanmax(
        np.vstack([
            mp["e300_amt_spike"].fillna(0.0).to_numpy(float),
            mp["e50_amt_spike"].fillna(0.0).to_numpy(float),
            np.where(cal_arr < "2005-03-25", mp["mkt_amt_spike_20d"].fillna(0.0).to_numpy(float), 0.0),
        ]),
        axis=0,
    )
    s1_pre2016 = (cal_arr < "2016-02-01") & weak_mkt.to_numpy(bool) & (etf_or_mkt_spk >= 2.0) & s1_hard_5d
    v3_live = mp["v3_score_live"].fillna(0.0).to_numpy(float)
    v3_eod = mp["v3_score_eod"].fillna(0.0).to_numpy(float)

    s1_live_60 = s1_pre2016 | ((cal_arr >= "2016-02-01") & (v3_live >= 60))
    s1_live_75 = s1_pre2016 | ((cal_arr >= "2016-02-01") & (v3_live >= 75))
    s1_eod_60 = s1_pre2016 | ((cal_arr >= "2016-02-01") & (v3_eod >= 60))
    s1_eod_75 = s1_pre2016 | ((cal_arr >= "2016-02-01") & (v3_eod >= 75))

    # Causal S2 Four-Gate Bottom Signals (ZERO casebook peeking!)
    mcrash = (mp["margin_chg_20d_pct"] < -0.08).fillna(False).to_numpy(bool)
    wp_low_supply = ((mp["eq_supply_pct_mcap"] <= 0.25) | (mp["ipo_raised_yi"] <= 40.0)).fillna(False).to_numpy(bool)
    g1_gate = (~mcrash) & (g1_ev_60d | wp_low_supply)
    v3_75_22d = _window_active(np.where(v3_live >= 75)[0], 22)
    g2_gate = g2_ev_22d | rate_cut_22d | v3_75_22d
    g3_gate = g3_ev_22d
    g4_gate = (
        (mp["pct_above_ma200"] < 0.20).fillna(False).to_numpy(bool)
        | (mp["bench_dd_60d"] <= -0.15).fillna(False).to_numpy(bool)
        | (mp["bench_dd_250d"] <= -0.25).fillna(False).to_numpy(bool)
        | (mp["amount_pct_250d"] <= 0.25).fillna(False).to_numpy(bool)
    )
    gate_cnt = g1_gate.astype(int) + g2_gate.astype(int) + g3_gate.astype(int) + g4_gate.astype(int)
    s2_four_gate = (gate_cnt >= 3) & g2_gate

    # Causal S3 Overheat + Tightening / Drain Spike Regime
    overheat = (
        (mp["bench_level"] > mp["bench_ma60"]).fillna(False).to_numpy(bool)
        & (
            (mp["bench_ret_60d"] >= 0.25).fillna(False).to_numpy(bool)
            | (mp["amount_pct_250d"] >= 0.85).fillna(False).to_numpy(bool)
            | (mp["pct_above_ma200"] >= 0.80).fillna(False).to_numpy(bool)
        )
    )
    drain_spike = ((mp["wp_drain_pct_5y"] >= 0.85) & (mp["eq_supply_pct_mcap"] >= 0.40)).fillna(False).to_numpy(bool)
    s3_escape = overheat & (tight_20d | drain_spike)
    s3_recover = (
        (mp["bench_level"] > mp["bench_ma60"]).fillna(False).to_numpy(bool)
        & (mp["bench_ma20"] > mp["bench_ma60"]).fillna(False).to_numpy(bool)
        & (~s3_escape)
    )

    # Sector 14 daily open/close/tradable for S4 (2008-08-28+)
    tl_obs = _map_event_obs_idx(tl["event_date"], dates, cal_arr, d2i)
    tl["obs_idx"] = tl_obs
    tl_v = tl[tl["obs_idx"] < n].copy()

    def _build_sector_window(mask_series: pd.Series, horizon_td: int) -> list[set[str]]:
        res = [set() for _ in range(n)]
        for _, r in tl_v[mask_series].iterrows():
            oi = int(r["obs_idx"])
            sc = str(r["sector_code"])
            for j in range(oi, min(n, oi + horizon_td)):
                res[j].add(sc)
        return res

    sec_green250 = _build_sector_window((tl_v["signal_type"] == "GREEN_SUBSIDY_PLAN") & (tl_v["intensity"] >= 2), 250)
    sec_red120 = _build_sector_window(
        (tl_v["signal_type"] == "RED_CRACKDOWN_BAN") | ((tl_v["signal_type"] == "RED_PRICE_CAP_TAX") & (tl_v["intensity"] == 3)),
        120,
    )

    # Causal sector index mapping for each day i (chosen from col valid at i-1 and i)
    for sec in SECTORS:
        op_arr = np.full(n, np.nan)
        cl_arr = np.full(n, np.nan)
        tr_arr = np.zeros(n, dtype=bool)
        p_col, fb1, fb2 = SECTOR_COL_MAP[sec]
        cands = [p_col, fb1, fb2, "bench"]
        chosen_col = None
        for i in range(n):
            col_use = None
            for col in cands:
                oc, cc = f"{col}_open", f"{col}_close"
                if oc in mp.columns and cc in mp.columns:
                    v_o, v_c = mp.at[i, oc], mp.at[i, cc]
                    if pd.notna(v_o) and pd.notna(v_c) and v_o > 0 and v_c > 0:
                        col_use = col
                        break
            if col_use is not None:
                op_arr[i] = float(mp.at[i, f"{col_use}_open"])
                cl_arr[i] = float(mp.at[i, f"{col_use}_close"])
                # Note: only smoothly link returns when same col on i-1 & i; handle switch cleanly in asset_data
                tr_arr[i] = True
                chosen_col = col_use
        asset_data[f"SEC_{sec}"] = {"open": op_arr, "close": cl_arr, "tradable": tr_arr}

    # Exact sector column per day so switch between proxy & primary never creates price jump
    sec_col_by_day = {}
    for sec in SECTORS:
        p_col, fb1, fb2 = SECTOR_COL_MAP[sec]
        cands = [p_col, fb1, fb2, "bench"]
        cols_i = []
        for i in range(n):
            cu = "bench"
            for col in cands:
                oc, cc = f"{col}_open", f"{col}_close"
                if oc in mp.columns and cc in mp.columns:
                    v_o, v_c = mp.at[i, oc], mp.at[i, cc]
                    if pd.notna(v_o) and pd.notna(v_c) and v_o > 0 and v_c > 0:
                        cu = col
                        break
            cols_i.append(cu)
        sec_col_by_day[sec] = cols_i

    return {
        "dates": dates,
        "cal_arr": cal_arr,
        "mp": mp,
        "asset_data": asset_data,
        "chain_asset": chain_asset,
        "sec_col_by_day": sec_col_by_day,
        "signals": {
            "s1_live_60": s1_live_60,
            "s1_live_75": s1_live_75,
            "s1_eod_60": s1_eod_60,
            "s1_eod_75": s1_eod_75,
            "s2_four_gate": s2_four_gate,
            "g1_gate": g1_gate,
            "g2_gate": g2_gate,
            "g3_gate": g3_gate,
            "g4_gate": g4_gate,
            "s3_escape": s3_escape,
            "s3_recover": s3_recover,
            "tight_5d": tight_5d,
            "tight_20d": tight_20d,
            "overheat": overheat,
            "sec_green250": sec_green250,
            "sec_red120": sec_red120,
        },
    }


def run_daily_portfolio_sim(
    state: dict,
    target_fn,
    start_date: str = "2000-01-04",
    fee_one_way: float = 0.0005,
    cash_mode: str = "0pct",
    track_single_trades: bool = False,
    strat_name: str = "",
) -> dict:
    """
    Strictly causal day-by-day simulation loop:
      - At close of day t: strategy evaluates target_fn(t, cur_state) -> target weights for t+1 open.
      - At open of day t+1: executes target weights against actual tradable opens, paying fee_one_way * turnover.
    Supports seamless asset chain switches (e.g., sh_comp -> 510050 -> 510300) and sector proxy transitions.
    """
    dates = state["dates"]
    mp = state["mp"]
    ad = state["asset_data"]
    sec_cols = state["sec_col_by_day"]

    start_idx = next((i for i, d in enumerate(dates) if d >= start_date), 0)
    n = len(dates)
    m = n - start_idx

    cgb10 = mp["cn_bond_10y"].to_numpy(float)
    ts_dates = pd.to_datetime(dates)

    nav = np.ones(m, dtype=float)
    eq_w = np.zeros(m, dtype=float)
    turn_arr = np.zeros(m, dtype=float)
    cur_weights: dict[str, float] = {}  # asset_key -> weight
    pending_target: dict[str, float] = {}

    # Optional trade ledger tracking (for single-asset timing strategies S1 & S2)
    trades = []
    open_trade = None

    def _get_ret_co(ak: str, i: int) -> float:
        if ak.startswith("SEC_"):
            sec = ak[4:]
            col = sec_cols[sec][i - 1]
            c_prev = mp.at[i - 1, f"{col}_close"]
            o_cur = mp.at[i, f"{col}_open"]
            if pd.isna(c_prev) or pd.isna(o_cur) or c_prev <= 0:
                col = sec_cols[sec][i]
                c_prev = mp.at[i - 1, f"{col}_close"]
                o_cur = mp.at[i, f"{col}_open"]
            return float(o_cur / c_prev - 1.0) if (pd.notna(c_prev) and pd.notna(o_cur) and c_prev > 0) else 0.0
        if not ad[ak]["tradable"][i]:
            return 0.0
        c_prev = ad[ak]["close"][i - 1]
        o_cur = ad[ak]["open"][i]
        return float(o_cur / c_prev - 1.0) if (np.isfinite(c_prev) and np.isfinite(o_cur) and c_prev > 0) else 0.0

    def _get_ret_oc(ak: str, i: int) -> float:
        if ak.startswith("SEC_"):
            sec = ak[4:]
            col = sec_cols[sec][i]
            o_cur = mp.at[i, f"{col}_open"]
            c_cur = mp.at[i, f"{col}_close"]
            return float(c_cur / o_cur - 1.0) if (pd.notna(o_cur) and pd.notna(c_cur) and o_cur > 0) else 0.0
        if not ad[ak]["tradable"][i]:
            return 0.0
        o_cur = ad[ak]["open"][i]
        c_cur = ad[ak]["close"][i]
        return float(c_cur / o_cur - 1.0) if (np.isfinite(o_cur) and np.isfinite(c_cur) and o_cur > 0) else 0.0

    def _get_ret_cc(ak: str, i: int) -> float:
        if ak.startswith("SEC_"):
            sec = ak[4:]
            col = sec_cols[sec][i - 1]
            col2 = sec_cols[sec][i]
            if col != col2:
                c_prev = mp.at[i - 1, f"{col}_close"]
                o_cur = mp.at[i, f"{col}_open"]
                o2, c2 = mp.at[i, f"{col2}_open"], mp.at[i, f"{col2}_close"]
                if pd.notna(c_prev) and pd.notna(o_cur) and pd.notna(o2) and pd.notna(c2) and c_prev > 0 and o2 > 0:
                    return float((o_cur / c_prev) * (c2 / o2) - 1.0)
                col = col2
            c_prev = mp.at[i - 1, f"{col}_close"]
            c_cur = mp.at[i, f"{col}_close"]
            return float(c_cur / c_prev - 1.0) if (pd.notna(c_prev) and pd.notna(c_cur) and c_prev > 0) else 0.0
        if not ad[ak]["tradable"][i]:
            return 0.0
        c_prev = ad[ak]["close"][i - 1]
        c_cur = ad[ak]["close"][i]
        return float(c_cur / c_prev - 1.0) if (np.isfinite(c_prev) and np.isfinite(c_cur) and c_prev > 0) else 0.0

    def _is_tradable(ak: str, i: int) -> bool:
        if ak.startswith("SEC_"):
            return True
        return bool(ad[ak]["tradable"][i])

    # Day 0 at start_idx: start in 100% cash, evaluate close signal for start_idx + 1 open
    strat_ctx = {"days_held": 0, "hold_rem": 0, "in_pos": False, "escaped": False, "entry_nav": 1.0, "entry_reason": ""}
    pending_target, reason0 = target_fn(start_idx, strat_ctx)
    if pending_target:
        strat_ctx["pending_reason"] = reason0

    for pos in range(1, m):
        i = start_idx + pos
        dt_days = (ts_dates[i] - ts_dates[i - 1]).days
        if cash_mode == "0pct":
            r_rf = 0.0
        elif cash_mode == "2pct":
            r_rf = 0.02 * (dt_days / 365.0)
        else:
            y_ann = float(cgb10[i - 1]) / 100.0 if np.isfinite(cgb10[i - 1]) else 0.025
            r_rf = max(0.0, y_ann) * (dt_days / 365.0)

        w_sum_prev = float(sum(cur_weights.values()))
        all_keys = set(cur_weights.keys()) | set(pending_target.keys())
        blocked = any(not _is_tradable(ak, i) for ak in all_keys)
        new_weights = dict(cur_weights) if blocked else {k: v for k, v in pending_target.items() if v > 1e-6}
        dw = sum(abs(new_weights.get(k, 0.0) - cur_weights.get(k, 0.0)) for k in (set(new_weights.keys()) | set(cur_weights.keys())))

        r_on = sum(w * _get_ret_co(ak, i) for ak, w in cur_weights.items()) + max(0.0, 1.0 - w_sum_prev) * r_rf
        cost = fee_one_way * dw if dw > 1e-6 else 0.0

        # Track single-asset trade ledger cleanly (even across 2005/2012 chain rollovers)
        if track_single_trades:
            prev_main = max(cur_weights, key=cur_weights.get) if cur_weights else None
            new_main = max(new_weights, key=new_weights.get) if new_weights else None
            if prev_main is None and new_main is not None:
                open_trade = {
                    "strategy": strat_name,
                    "signal_date": dates[i - 1],
                    "buy_date": dates[i],
                    "buy_idx": i,
                    "etf_code": new_main,
                    "buy_open_hfq": float(ad[new_main]["open"][i]),
                    "buy_open_raw": float(ad[new_main]["raw_open"][i]),
                    "cur_leg_open": float(ad[new_main]["open"][i]),
                    "cum_gross_mult": 1.0,
                    "trigger_reason": strat_ctx.get("pending_reason", ""),
                }
            elif prev_main is not None and new_main is None and open_trade is not None:
                sell_hfq = float(ad[prev_main]["open"][i])
                sell_raw = float(ad[prev_main]["raw_open"][i])
                open_trade["cum_gross_mult"] *= (sell_hfq / open_trade["cur_leg_open"])
                gross_r = open_trade["cum_gross_mult"] - 1.0
                net_r = (1.0 + gross_r) * (1.0 - 2.0 * fee_one_way) - 1.0
                c300_buy = float(mp.at[open_trade["buy_idx"], "csi300_open"]) if pd.notna(mp.at[open_trade["buy_idx"], "csi300_open"]) else float(mp.at[open_trade["buy_idx"], "sh_comp_open"])
                c300_sell = float(mp.at[i, "csi300_open"]) if pd.notna(mp.at[i, "csi300_open"]) else float(mp.at[i, "sh_comp_open"])
                bench_r = c300_sell / c300_buy - 1.0 if c300_buy > 0 else 0.0
                trades.append({
                    "strategy": strat_name,
                    "trade_id": len(trades) + 1,
                    "signal_date": open_trade["signal_date"],
                    "buy_date": open_trade["buy_date"],
                    "sell_date": dates[i],
                    "etf_code": open_trade["etf_code"],
                    "buy_open_hfq": round(open_trade["buy_open_hfq"], 4),
                    "sell_open_hfq": round(sell_hfq, 4),
                    "buy_open_raw": round(open_trade["buy_open_raw"], 4),
                    "sell_open_raw": round(sell_raw, 4),
                    "hold_days": int(i - open_trade["buy_idx"]),
                    "gross_ret_pct": round(gross_r * 100.0, 2),
                    "net_ret_pct": round(net_r * 100.0, 2),
                    "bench_same_window_pct": round(bench_r * 100.0, 2),
                    "excess_vs_bench_pct": round((net_r - bench_r) * 100.0, 2),
                    "trigger_reason": open_trade["trigger_reason"],
                    "is_open_mtm": False,
                })
                open_trade = None
            elif prev_main is not None and new_main is not None and prev_main != new_main and open_trade is not None:
                sell_hfq = float(ad[prev_main]["open"][i])
                open_trade["cum_gross_mult"] *= (sell_hfq / open_trade["cur_leg_open"])
                open_trade["cur_leg_open"] = float(ad[new_main]["open"][i])
                open_trade["etf_code"] = f"{open_trade['etf_code']}->{new_main}"

        cur_weights = new_weights
        w_sum_cur = float(sum(cur_weights.values()))
        if dw > 1e-6:
            turn_arr[pos] = dw
            r_oc = sum(w * _get_ret_oc(ak, i) for ak, w in cur_weights.items())
            day_ret = (1.0 + r_on) * (1.0 - cost) * (1.0 + r_oc) - 1.0
        else:
            day_ret = sum(w * _get_ret_cc(ak, i) for ak, w in cur_weights.items()) + max(0.0, 1.0 - w_sum_cur) * r_rf

        nav[pos] = nav[pos - 1] * (1.0 + day_ret)
        eq_w[pos] = w_sum_cur

        # Update context for close-of-day i signal evaluation
        strat_ctx["cur_nav"] = nav[pos]
        strat_ctx["in_pos"] = w_sum_cur > 1e-6
        if strat_ctx["in_pos"]:
            if not strat_ctx.get("was_in_pos", False):
                strat_ctx["days_held"] = 1
                strat_ctx["entry_nav"] = nav[pos - 1] * (1.0 + r_on) * (1.0 - cost)
            else:
                strat_ctx["days_held"] = strat_ctx.get("days_held", 0) + 1
        else:
            strat_ctx["days_held"] = 0
        strat_ctx["was_in_pos"] = strat_ctx["in_pos"]
        strat_ctx["cur_trade_ret"] = (nav[pos] / strat_ctx["entry_nav"] - 1.0) if strat_ctx["in_pos"] and strat_ctx.get("entry_nav", 0) > 0 else 0.0

        pending_target, rsn = target_fn(i, strat_ctx)
        if rsn:
            strat_ctx["pending_reason"] = rsn

    # Record open MTM position at final close if still holding
    if track_single_trades and open_trade is not None:
        i_end = n - 1
        cur_ak = max(cur_weights, key=cur_weights.get) if cur_weights else open_trade["etf_code"].split("->")[-1]
        sell_hfq = float(ad[cur_ak]["close"][i_end])
        sell_raw = float(ad[cur_ak]["raw_close"][i_end])
        open_trade["cum_gross_mult"] *= (sell_hfq / open_trade["cur_leg_open"])
        gross_r = open_trade["cum_gross_mult"] - 1.0
        net_r = (1.0 + gross_r) * (1.0 - fee_one_way) - 1.0
        c300_buy = float(mp.at[open_trade["buy_idx"], "csi300_open"]) if pd.notna(mp.at[open_trade["buy_idx"], "csi300_open"]) else float(mp.at[open_trade["buy_idx"], "sh_comp_open"])
        c300_sell = float(mp.at[i_end, "csi300_close"]) if pd.notna(mp.at[i_end, "csi300_close"]) else float(mp.at[i_end, "sh_comp_close"])
        bench_r = c300_sell / c300_buy - 1.0 if c300_buy > 0 else 0.0
        trades.append({
            "strategy": strat_name,
            "trade_id": len(trades) + 1,
            "signal_date": open_trade["signal_date"],
            "buy_date": open_trade["buy_date"],
            "sell_date": f"{dates[i_end]} (OPEN_MTM)",
            "etf_code": cur_ak,
            "buy_open_hfq": round(open_trade["buy_open_hfq"], 4),
            "sell_open_hfq": round(sell_hfq, 4),
            "buy_open_raw": round(open_trade["buy_open_raw"], 4),
            "sell_open_raw": round(sell_raw, 4),
            "hold_days": int(i_end - open_trade["buy_idx"] + 1),
            "gross_ret_pct": round(gross_r * 100.0, 2),
            "net_ret_pct": round(net_r * 100.0, 2),
            "bench_same_window_pct": round(bench_r * 100.0, 2),
            "excess_vs_bench_pct": round((net_r - bench_r) * 100.0, 2),
            "trigger_reason": open_trade["trigger_reason"],
            "is_open_mtm": True,
        })

    return {
        "dates": dates[start_idx:],
        "nav": nav,
        "eq_w": eq_w,
        "turnover": turn_arr,
        "trades": trades,
    }


def compute_window_metrics(
    nav: np.ndarray,
    eq_w: np.ndarray,
    turnover: np.ndarray,
    dates: list[str],
    bench_nav: np.ndarray,
    trades: list[dict] | None = None,
    d0: str | None = None,
    d1: str | None = None,
) -> dict:
    """Compute exact CAGR, total mult, MDD, Sharpe, Calmar, avg weight, turnover, and trade win/payoff."""
    arr_d = np.array(dates)
    mask = np.ones(len(dates), dtype=bool)
    if d0 is not None:
        mask &= (arr_d >= d0)
    if d1 is not None:
        mask &= (arr_d <= d1)
    if mask.sum() < 10:
        return {}

    sub_nav = nav[mask] / nav[mask][0]
    sub_b = bench_nav[mask] / bench_nav[mask][0]
    sub_w = eq_w[mask]
    sub_t = turnover[mask]
    sub_d = arr_d[mask]

    rets = sub_nav[1:] / sub_nav[:-1] - 1.0
    yrs = (pd.Timestamp(str(sub_d[-1])) - pd.Timestamp(str(sub_d[0]))).days / 365.25
    tot_mult = float(sub_nav[-1])
    cum_pct = (tot_mult - 1.0) * 100.0
    ann_pct = (tot_mult ** (1.0 / max(yrs, 0.1)) - 1.0) * 100.0
    b_mult = float(sub_b[-1])
    b_ann_pct = (b_mult ** (1.0 / max(yrs, 0.1)) - 1.0) * 100.0

    std_d = float(np.std(rets, ddof=1)) if len(rets) > 2 else 0.0
    ann_vol = std_d * np.sqrt(242.0) * 100.0
    sharpe = (float(np.mean(rets)) / std_d * np.sqrt(242.0)) if std_d > 1e-12 else 0.0
    pk = np.maximum.accumulate(sub_nav)
    mdd_pct = float(np.min(sub_nav / pk - 1.0)) * 100.0
    calmar = ann_pct / abs(mdd_pct) if abs(mdd_pct) > 1e-6 else 0.0
    avg_w_pct = float(np.mean(sub_w)) * 100.0
    ann_turn_pct = float(np.sum(sub_t) / max(yrs, 0.1)) * 100.0

    out = {
        "start_date": str(sub_d[0]),
        "end_date": str(sub_d[-1]),
        "years": round(yrs, 2),
        "n_days": int(len(sub_d)),
        "total_mult": round(tot_mult, 3),
        "cum_ret_pct": round(cum_pct, 2),
        "ann_ret_pct": round(ann_pct, 2),
        "ann_vol_pct": round(ann_vol, 2),
        "mdd_pct": round(mdd_pct, 2),
        "sharpe": round(sharpe, 2),
        "calmar": round(calmar, 2),
        "avg_weight_pct": round(avg_w_pct, 1),
        "annual_turnover_pct": round(ann_turn_pct, 1),
        "excess_ann_vs_bh_pp": round(ann_pct - b_ann_pct, 2),
        "excess_cum_vs_bh_pct": round(cum_pct - (b_mult - 1.0) * 100.0, 2),
    }

    if trades is not None:
        w_tr = [t for t in trades if (d0 is None or t["buy_date"] >= d0) and (d1 is None or t["buy_date"] <= d1)]
        n_tr = len(w_tr)
        if n_tr > 0:
            r_tr = np.array([t["net_ret_pct"] for t in w_tr], dtype=float)
            wins = r_tr[r_tr > 0]
            losses = -r_tr[r_tr < 0]
            wr = float(np.mean(r_tr > 0)) * 100.0
            pl = float(np.mean(wins) / np.mean(losses)) if (len(wins) > 0 and len(losses) > 0) else (9.99 if len(wins) > 0 else 0.0)
            out.update({
                "n_trades": int(n_tr),
                "trade_win_rate_pct": round(wr, 1),
                "trade_payoff_ratio": round(pl, 2),
                "trade_mean_ret_pct": round(float(np.mean(r_tr)), 2),
            })
        else:
            out.update({"n_trades": 0, "trade_win_rate_pct": None, "trade_payoff_ratio": None, "trade_mean_ret_pct": None})

    return out


def solve_vol_scalar_for_target(inv_vol: np.ndarray, target_w_bar: float) -> float:
    lo, hi = 0.0, 10.0
    valid = np.where(np.isfinite(inv_vol), inv_vol, 0.0)
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if float(np.mean(np.clip(mid * valid, 0.0, 1.0))) < target_w_bar:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
