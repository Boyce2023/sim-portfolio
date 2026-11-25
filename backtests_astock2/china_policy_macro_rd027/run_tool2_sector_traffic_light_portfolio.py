#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD027 Wave 2B Tool 2: Ministerial Sector Traffic-Light Portfolio Backtest (2008-2026.11).
Strictly D12 compliant (zero yfinance), strict T+1 open execution, 0.30% two-way cost.
Tests:
  1. Green Subsidy Mainline Pool (GREEN_SUBSIDY_PLAN I>=2, 120d vs 250d)
  2. Red Light Exclusion Rule (RED_CRACKDOWN_BAN or I==3 RED_PRICE_CAP_TAX excluded 120d)
  3. Composite Green + Red Exclusion + Tool 1 Macro-Style Overlay
"""
import json
import os
import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
import rd027_common as cm
from build_pillar3_sector_traffic_lights import SECTOR_COL_MAP
import run_tool1_waterpool_regime_dashboard as t1

ROOT = cm.ROOT
OUT_DIR = os.path.join(ROOT, "output/china_policy_macro_rd027_20261125/wave2_practical")
os.makedirs(OUT_DIR, exist_ok=True)
OUT_JSON = os.path.join(OUT_DIR, "tool2_sector_traffic_light_audit.json")

ONE_WAY_COST = 0.0015
SECTORS = sorted(SECTOR_COL_MAP.keys())
GROWTH_SECTORS = {"NEW_ENERGY", "SEMI_HARDTECH", "TMT_AI_MEDIA", "DEFENSE_AERO", "BROKERAGE", "EDU_INTERNET"}
DEFENSIVE_SECTORS = {"CENTRAL_SOE_DIV", "BANK", "PHARMA", "SUPPLY_CYCLICAL", "CONSUMPTION_BAIJIU"}


def _sector_col_at_day(panel: pd.DataFrame, i: int, sec: str) -> str:
    """Strictly causal sector index column available at day i open/close."""
    p_col, fb1, fb2 = SECTOR_COL_MAP[sec]
    for col in [p_col, fb1, fb2, "bench"]:
        oc = f"{col}_open"
        cc = f"{col}_close"
        if oc in panel.columns and cc in panel.columns:
            if pd.notna(panel.at[i, oc]) and pd.notna(panel.at[i, cc]) and panel.at[i, oc] > 0 and panel.at[i, cc] > 0:
                return col
    return "bench"


def _compute_sector_daily_returns(panel: pd.DataFrame, start_idx: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Precompute exact day-t close-to-close and open-to-close return matrices for 14 sectors + CSI300."""
    n = len(panel)
    cc_ret = {}
    oc_ret = {}
    co_ret = {}
    for sec in SECTORS:
        cc_arr = np.zeros(n)
        oc_arr = np.zeros(n)
        co_arr = np.zeros(n)
        for i in range(max(1, start_idx), n):
            col = _sector_col_at_day(panel, i - 1, sec)
            # Ensure col also valid at i
            if pd.isna(panel.at[i, f"{col}_close"]) or pd.isna(panel.at[i, f"{col}_open"]):
                col = _sector_col_at_day(panel, i, sec)
            c_prev = panel.at[i - 1, f"{col}_close"]
            o_cur = panel.at[i, f"{col}_open"]
            c_cur = panel.at[i, f"{col}_close"]
            if pd.notna(c_prev) and pd.notna(o_cur) and pd.notna(c_cur) and c_prev > 0 and o_cur > 0:
                cc_arr[i] = c_cur / c_prev - 1.0
                oc_arr[i] = c_cur / o_cur - 1.0
                co_arr[i] = o_cur / c_prev - 1.0
        cc_ret[sec] = cc_arr
        oc_ret[sec] = oc_arr
        co_ret[sec] = co_arr
    return pd.DataFrame(cc_ret), pd.DataFrame(oc_ret), pd.DataFrame(co_ret)


def _eval_daily_nav(nav_arr: np.ndarray, dates: list[str], eq_w: np.ndarray, turn_ow: np.ndarray, bench_nav: np.ndarray = None) -> dict:
    rets = nav_arr[1:] / nav_arr[:-1] - 1.0
    yrs = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days / 365.25
    cum = (nav_arr[-1] / nav_arr[0] - 1.0) * 100.0
    ann = ((nav_arr[-1] / nav_arr[0]) ** (1.0 / max(yrs, 0.1)) - 1.0) * 100.0
    vol = float(np.std(rets, ddof=1) * np.sqrt(242.0)) * 100.0
    pk = np.maximum.accumulate(nav_arr)
    mdd = float(np.min(nav_arr / pk - 1.0)) * 100.0
    sharpe = float(np.mean(rets) / (np.std(rets, ddof=1) + 1e-12) * np.sqrt(242.0))
    calmar = ann / abs(mdd) if abs(mdd) > 1e-6 else 0.0
    ex_ann = None
    if bench_nav is not None:
        b_ann = ((bench_nav[-1] / bench_nav[0]) ** (1.0 / max(yrs, 0.1)) - 1.0) * 100.0
        ex_ann = round(ann - b_ann, 2)
    return {
        "n_days": int(len(rets)),
        "cum_ret_pct": round(cum, 2),
        "ann_ret_pct": round(ann, 2),
        "ann_vol_pct": round(vol, 2),
        "mdd_pct": round(mdd, 2),
        "sharpe": round(sharpe, 2),
        "calmar": round(calmar, 2),
        "avg_eq_weight_pct": round(float(np.mean(eq_w)) * 100.0, 1),
        "annual_turnover_pct": round(float(np.sum(turn_ow) / max(yrs, 0.1)) * 100.0, 1),
        "excess_ann_vs_csi300_pp": ex_ann,
    }


def simulate_strategies(panel: pd.DataFrame, tl: pd.DataFrame, regime_df: pd.DataFrame) -> dict:
    # Align events to panel indices (strictly t_entry_idx = T+1 open)
    dates = panel["date"].tolist()
    d2i = {d: i for i, d in enumerate(dates)}
    start_idx = int(tl["t_entry_idx"].min())  # 2008-08-28
    end_idx = len(panel) - 1

    # Map cn_bond_10y & Waterpool Regime Score (available strictly as of day i-1 close before day i open)
    reg_map = regime_df.set_index("date")["waterpool_regime_score"].to_dict()
    cgb_map = regime_df.set_index("date")["cn_bond_10y"].to_dict()

    cc_df, oc_df, co_df = _compute_sector_daily_returns(panel, start_idx)
    c300_cc = panel["csi300_close"].pct_change().fillna(0.0).to_numpy()
    c300_oc = (panel["csi300_close"] / panel["csi300_open"] - 1.0).fillna(0.0).to_numpy()
    c300_co = (panel["csi300_open"] / panel["csi300_close"].shift(1) - 1.0).fillna(0.0).to_numpy()

    # Pre-build active sector timers by day i (entry at open[t_entry], active for t in [t_entry, t_entry + H))
    ev_list = tl[tl["t_entry_idx"] >= 0].copy()

    def build_active_mask(filter_fn, horizon: int) -> dict[int, set[str]]:
        act = {i: set() for i in range(start_idx, end_idx + 1)}
        for _, r in ev_list[filter_fn(ev_list)].iterrows():
            te = int(r["t_entry_idx"])
            sec = str(r["sector_code"])
            for j in range(max(start_idx, te), min(end_idx + 1, te + horizon)):
                act[j].add(sec)
        return act

    m_green_sub_i2 = lambda d: (d["signal_type"] == "GREEN_SUBSIDY_PLAN") & (d["intensity"] >= 2)
    m_green_dereg_i3 = lambda d: (d["signal_type"] == "GREEN_DEREG_MA") & (d["intensity"] >= 3)
    m_red = lambda d: (d["signal_type"] == "RED_CRACKDOWN_BAN") | ((d["signal_type"] == "RED_PRICE_CAP_TAX") & (d["intensity"] == 3))

    g120 = build_active_mask(m_green_sub_i2, 120)
    g250 = build_active_mask(m_green_sub_i2, 250)
    gdereg60 = build_active_mask(m_green_dereg_i3, 60)
    red120 = build_active_mask(m_red, 120)

    # Target weights generator per strategy at open of day i (using only info known by i-1 close / morning open)
    def run_sim(weight_fn) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        nav = np.ones(end_idx - start_idx + 1)
        eq_w = np.zeros(end_idx - start_idx + 1)
        turn_ow = np.zeros(end_idx - start_idx + 1)
        cur_w = np.zeros(len(SECTORS) + 1)  # last slot is CSI300 fallback if used

        for idx_pos, i in enumerate(range(start_idx, end_idx + 1)):
            prev_d = dates[i - 1]
            rf_ann = float(cgb_map.get(prev_d, 3.0)) if pd.notna(cgb_map.get(prev_d, np.nan)) else 3.0
            dt_days = (pd.Timestamp(dates[i]) - pd.Timestamp(prev_d)).days
            r_rf = rf_ann / 100.0 * (dt_days / 365.0)

            tgt_w = weight_fn(i, prev_d)
            # Only rebalance when target weights differ materially (> 1e-4) to avoid drift churn
            if np.sum(np.abs(tgt_w - cur_w)) > 1e-4:
                # Overnight return on cur_w from close[i-1] to open[i]
                r_co_vec = np.append(co_df.iloc[i].to_numpy(), c300_co[i])
                w_eq_prev = float(np.sum(cur_w))
                r_overnight = float(np.dot(cur_w, r_co_vec)) + (1.0 - w_eq_prev) * r_rf
                # Rebalance at open[i] paying 0.15% one-way on equity turnover
                dw = float(np.sum(np.abs(tgt_w - cur_w)))
                cost = ONE_WAY_COST * dw
                turn_ow[idx_pos] = dw
                cur_w = tgt_w.copy()
                # Intraday open[i] to close[i] on new weights
                r_oc_vec = np.append(oc_df.iloc[i].to_numpy(), c300_oc[i])
                r_intraday = float(np.dot(cur_w, r_oc_vec))
                day_ret = (1.0 + r_overnight) * (1.0 - cost) * (1.0 + r_intraday) - 1.0
            else:
                r_cc_vec = np.append(cc_df.iloc[i].to_numpy(), c300_cc[i])
                w_eq_cur = float(np.sum(cur_w))
                day_ret = float(np.dot(cur_w, r_cc_vec)) + (1.0 - w_eq_cur) * r_rf

            eq_w[idx_pos] = float(np.sum(cur_w))
            if idx_pos > 0:
                nav[idx_pos] = nav[idx_pos - 1] * (1.0 + day_ret)
            else:
                nav[0] = 1.0 * (1.0 + day_ret)
        return nav, eq_w, turn_ow

    sec_to_idx = {s: k for k, s in enumerate(SECTORS)}

    def vec_from_set(sec_set: set[str], total_eq_w: float = 1.0, fallback_300: bool = False, weights_dict: dict = None) -> np.ndarray:
        v = np.zeros(len(SECTORS) + 1)
        if not sec_set:
            if fallback_300:
                v[-1] = total_eq_w
            return v
        if weights_dict is None:
            w = total_eq_w / len(sec_set)
            for s in sec_set:
                v[sec_to_idx[s]] = w
        else:
            tot_raw = sum(weights_dict.get(s, 1.0) for s in sec_set)
            for s in sec_set:
                v[sec_to_idx[s]] = total_eq_w * weights_dict.get(s, 1.0) / tot_raw
        return v

    # Define 8 clean strategies covering Rules 1, 2, 3 and benchmarks
    strats = {
        "CSI300_BH": lambda i, pd_: vec_from_set(set(), 1.0, fallback_300=True),
        "All_14_Sectors_EW": lambda i, pd_: vec_from_set(set(SECTORS), 1.0),
        "Rule1_GreenSub120d_300FB": lambda i, pd_: vec_from_set(g120[i] - red120[i], 1.0, fallback_300=True),
        "Rule1_GreenSub250d_300FB": lambda i, pd_: vec_from_set(g250[i] - red120[i], 1.0, fallback_300=True),
        "Rule1_GreenSub250d_CashFB": lambda i, pd_: vec_from_set(g250[i] - red120[i], 1.0, fallback_300=False),
        "Rule2_AllSectors_ExclRed120d": lambda i, pd_: vec_from_set(set(SECTORS) - red120[i], 1.0),
        "Rule2_Red120d_ExcludedBasket": lambda i, pd_: vec_from_set(red120[i], 1.0, fallback_300=False),
    }

    def rule3_fn(i: int, prev_d: str) -> np.ndarray:
        score = int(reg_map.get(prev_d, 50))
        reds = red120[i]
        greens = (g250[i] | gdereg60[i]) - reds
        non_red = set(SECTORS) - reds
        if score >= 50:
            pool = greens if greens else non_red
            w_dict = {s: (1.5 if s in GROWTH_SECTORS else 1.0) for s in pool}
            return vec_from_set(pool, 1.0, weights_dict=w_dict)
        if score >= 30:
            def_pool = (greens & DEFENSIVE_SECTORS) or (non_red & DEFENSIVE_SECTORS) or non_red
            return vec_from_set(def_pool, 0.50)
        def_pool = (non_red & DEFENSIVE_SECTORS) or non_red
        return vec_from_set(def_pool, 0.20)

    strats["Rule3_Composite_Green_ExclRed_Macro"] = rule3_fn

    sim_res = {name: run_sim(fn) for name, fn in strats.items()}
    sim_dates = dates[start_idx:end_idx + 1]

    windows = {
        "FULL_2008_2026": ("2008-08-28", "2026-11-24"),
        "IS_2008_2020": ("2008-08-28", "2020-12-31"),
        "OOS_2021_2026": ("2021-01-01", "2026-11-24"),
        "OOS_3Y_2024_2026": ("2024-01-01", "2026-11-24"),
    }
    out_win = {}
    sim_arr_dates = np.array(sim_dates)
    for wname, (d_lo, d_hi) in windows.items():
        mask = (sim_arr_dates >= d_lo) & (sim_arr_dates <= d_hi)
        if not np.any(mask):
            continue
        sub_dates = sim_arr_dates[mask].tolist()
        b_nav = sim_res["CSI300_BH"][0][mask]
        ew_nav = sim_res["All_14_Sectors_EW"][0][mask]
        ew_m = _eval_daily_nav(ew_nav, sub_dates, sim_res["All_14_Sectors_EW"][1][mask], sim_res["All_14_Sectors_EW"][2][mask], b_nav)
        w_dict = {}
        for sname, (nv, eqw, tow) in sim_res.items():
            m = _eval_daily_nav(nv[mask], sub_dates, eqw[mask], tow[mask], b_nav)
            m["excess_ann_vs_all14ew_pp"] = round(m["ann_ret_pct"] - ew_m["ann_ret_pct"], 2)
            w_dict[sname] = m
        out_win[wname] = w_dict

    # Extract 2026-11-25 active Green & Red sector lists (as of end_idx = 2026-11-24)
    active_green_250 = []
    active_red_120 = []
    for _, r in ev_list.sort_values("event_date", ascending=False).iterrows():
        te = int(r["t_entry_idx"])
        elapsed = end_idx - te + 1
        if elapsed < 0:
            continue
        if r["signal_type"].startswith("GREEN") and elapsed <= 250:
            active_green_250.append({
                "event_id": r["event_id"],
                "sector_code": r["sector_code"],
                "signal_type": r["signal_type"],
                "intensity": int(r["intensity"]),
                "event_date": r["event_date"],
                "tradable_date": r["tradable_date"],
                "days_elapsed_td": int(elapsed),
                "within_120d": bool(elapsed <= 120),
                "days_left_250d": int(250 - elapsed),
                "ministry": r["ministry"],
                "doc_title": r["doc_title"],
            })
        if (r["signal_type"] == "RED_CRACKDOWN_BAN" or (r["signal_type"] == "RED_PRICE_CAP_TAX" and int(r["intensity"]) == 3)) and elapsed <= 250:
            active_red_120.append({
                "event_id": r["event_id"],
                "sector_code": r["sector_code"],
                "signal_type": r["signal_type"],
                "intensity": int(r["intensity"]),
                "event_date": r["event_date"],
                "tradable_date": r["tradable_date"],
                "days_elapsed_td": int(elapsed),
                "active_120d_ban": bool(elapsed <= 120),
                "days_left_120d": max(0, int(120 - elapsed)),
                "ministry": r["ministry"],
                "doc_title": r["doc_title"],
            })

    return {
        "backtest_windows": out_win,
        "live_2026_11_25_traffic_lights": {
            "as_of_date": "2026-11-25",
            "active_green_sectors_250td": active_green_250,
            "active_green_sector_codes_250td": sorted(list({x["sector_code"] for x in active_green_250})),
            "active_green_subsidy_codes_250td": sorted(list({x["sector_code"] for x in active_green_250 if x["signal_type"] == "GREEN_SUBSIDY_PLAN" and x["intensity"] >= 2})),
            "active_red_events_250td": active_red_120,
            "active_red_excluded_codes_120td": sorted(list({x["sector_code"] for x in active_red_120 if x["active_120d_ban"]})),
        },
    }


def main():
    panel, _, _ = cm.load_market_panel()
    tl = pd.read_parquet(os.path.join(cm.OUT_PILLAR_DIR, "pillar3_sector_traffic_lights.parquet"))
    regime_df = t1.compute_waterpool_regime_panel(include_nov2026_mtd=False)

    res = simulate_strategies(panel, tl, regime_df)
    audit = {
        "meta": {
            "tool": "Tool 2: Ministerial Sector Traffic-Light Portfolio Backtest (2008-2026.11)",
            "d12_compliant": True,
            "execution": "Strictly T+1 open execution with 0.30% two-way cost (0.15% one-way on equity turnover)",
            "is_window": "2008-08-28 ~ 2020-12-31",
            "oos_window": "2021-01-01 ~ 2026-11-24",
        },
        **res,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print("=== TOOL 2: SECTOR TRAFFIC LIGHT PORTFOLIO BACKTEST ===")
    for wn in ["IS_2008_2020", "OOS_2021_2026", "OOS_3Y_2024_2026"]:
        wd = res["backtest_windows"][wn]
        print(f"\n[{wn}]")
        for sn, sm in wd.items():
            print(f"  {sn:34s}: Ann={sm['ann_ret_pct']:+6.2f}% MDD={sm['mdd_pct']:7.2f}% Sharpe={sm['sharpe']:5.2f} "
                  f"Calmar={sm['calmar']:5.2f} Ex300={str(sm['excess_ann_vs_csi300_pp']):>6s} ExEW={sm['excess_ann_vs_all14ew_pp']:+6.2f}pp")
    lv = res["live_2026_11_25_traffic_lights"]
    print("\nActive Green (250td):", lv["active_green_sector_codes_250td"])
    print("Active Green Subsidy I>=2 (250td):", lv["active_green_subsidy_codes_250td"])
    print("Active Red Excluded (120td):", lv["active_red_excluded_codes_120td"])
    print(f"\nSaved -> {OUT_JSON}")


if __name__ == "__main__":
    main()
