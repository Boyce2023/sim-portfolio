#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD027 Wave 2B Tool 1: China Policy Waterpool Regime & True/False Bottom Dashboard (0-100 V1.0).
Strictly D12 compliant (zero yfinance), strict PIT alignment, weekly Friday -> Monday open
execution with 0.30% two-way transaction cost (0.15% per side on equity turnover).
All rules & thresholds strictly locked on IS (2005-2020) and blind-tested on OOS (2021-2026.11).
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
from pit_utils import pit_asof_join

ROOT = cm.ROOT
PILLAR_DIR = cm.OUT_PILLAR_DIR
OUT_DIR = os.path.join(ROOT, "output/china_policy_macro_rd027_20261125/wave2_practical")
os.makedirs(OUT_DIR, exist_ok=True)
OUT_JSON = os.path.join(OUT_DIR, "tool1_waterpool_regime_audit.json")

ONE_WAY_COST = 0.0015  # 0.15% one-way -> 0.30% round-trip


def _regime_label(score: int) -> str:
    if score >= 70:
        return "TRUE_BOTTOM_STRONG_TAILWIND"
    if score >= 50:
        return "MILD_WARM_STANDARD"
    if score >= 30:
        return "CHOP_TRAP_DEFENSE"
    return "TIGHTENING_DRAIN_KILL"


def _calc_daily_score_row(r, i: int, idx_sets: dict, tm_s: pd.DataFrame) -> dict:
    """Compute pure integer 0-100 Waterpool Regime Score strictly from PIT state at row i."""
    idx_g1, idx_g2, idx_g3, idx_tight = idx_sets["g1"], idx_sets["g2"], idx_sets["g3"], idx_sets["tight"]

    # 1. Pillar A: Physical Four Gates & Hard Rescue Actions (0-25)
    eqs = r["eq_supply_pct_mcap"]
    mcrash = pd.notna(r["margin_chg_20d_pct"]) and r["margin_chg_20d_pct"] < -0.08
    if mcrash:
        g1 = 0
    else:
        g1 = 4 if (pd.notna(eqs) and eqs <= 0.20) else (2 if (pd.notna(eqs) and eqs <= 0.35) else 0)
        if np.any((idx_g1 >= i - 59) & (idx_g1 <= i)) or (pd.notna(r["ipo_raised_yi"]) and r["ipo_raised_yi"] <= 40.0):
            g1 += 3

    g2 = 5 if np.any((idx_g2 >= i - 39) & (idx_g2 <= i)) else 0
    rc = r["rate_chg_120d"]
    if pd.notna(rc) and rc < -0.05:
        g2 += 3
    elif pd.notna(rc) and rc > 0.05:
        g2 -= 2
    if pd.notna(r["v3_max_10d"]) and r["v3_max_10d"] >= 60:
        g2 += 2
    elif pd.notna(r["etf_flow_20d"]) and r["etf_flow_20d"] > 100.0:
        g2 += 2
    g2 = int(np.clip(g2, 0, 10))

    g3 = 5 if np.any((idx_g3 >= i - 59) & (idx_g3 <= i)) else 1
    if np.any((idx_g3 >= i - 19) & (idx_g3 <= i)):
        g3 += 3
    elif int(np.sum((idx_tight >= i - 19) & (idx_tight <= i))) >= 2:
        g3 = max(0, g3 - 1)
    g3 = int(np.clip(g3, 0, 8))
    s_a = int(np.clip(g1 + g2 + g3, 0, 25))

    # 2. Pillar B: Waterpool Ledger - Net Flows & Equity Supply Drain (0-20)
    pct_wp = r["net_waterpool_trading_pct_mcap_pct_5y"]
    nw = r["net_waterpool_trading_pct_mcap"]
    if pd.notna(pct_wp):
        b1 = 8 if pct_wp >= 0.70 else (6 if pct_wp >= 0.45 else (3 if pct_wp >= 0.25 else 0))
    else:
        b1 = 7 if (pd.notna(nw) and nw >= -0.08) else (4 if (pd.notna(nw) and nw >= -0.25) else 1)
    nid = r["net_waterpool_incl_div_pct_mcap"]
    b2 = 6 if (pd.notna(nid) and nid >= 0.10) else (4 if (pd.notna(nid) and nid >= -0.10) else 0)
    b3 = 6 if (pd.notna(eqs) and eqs <= 0.15) else (4 if (pd.notna(eqs) and eqs <= 0.25) else (2 if (pd.notna(eqs) and eqs <= 0.40) else 0))
    s_b = int(b1 + b2 + b3)

    # 3. Pillar C: Market Breadth Clearance & ERP Valuation Cushion (0-25)
    e300 = r["erp_csi300_pct"]
    ea = r["erp_all_a_median_pct"]
    c1 = 8 if (pd.notna(e300) and e300 >= 5.5) else (6 if (pd.notna(e300) and e300 >= 4.0) else (4 if (pd.notna(e300) and e300 >= 2.5) else (2 if (pd.notna(e300) and e300 >= 1.0) else 0)))
    c2 = 8 if (pd.notna(ea) and ea >= 0.0) else (6 if (pd.notna(ea) and ea >= -0.6) else (4 if (pd.notna(ea) and ea >= -1.2) else (2 if (pd.notna(ea) and ea >= -1.6) else 0)))
    ma2 = r["pct_above_ma200"]
    ab60 = int(r["bench_above_ma60"])
    if pd.isna(ma2):
        c3 = 4
    elif (pd.notna(ea) and ea < -1.5) and ma2 >= 0.85:
        c3 = 0
    elif ma2 < 0.20:
        c3 = 9 if (g2 >= 5 and g3 >= 5) else (5 if ab60 == 1 else 1)
    elif ab60 == 1 and 0.35 <= ma2 <= 0.90:
        c3 = 9
    elif ab60 == 1:
        c3 = 6
    else:
        c3 = 3
    s_c = int(c1 + c2 + c3)

    # 4. Pillar D: Top-Level Economic Meetings Stance & 1st-Diff (0-15)
    tm_past = tm_s[tm_s["tm_obs"] <= i]
    if tm_past.empty:
        s_d = 5
        lt_meta = {"meeting": None, "macro_stance": None, "delta_macro_stance": None}
    else:
        lt = tm_past.iloc[-1]
        ms = int(lt["macro_stance_score"])
        d1 = 9 if ms >= 5 else (7 if ms >= 3 else (5 if ms >= 1 else (3 if ms >= -1 else 0)))
        age = i - int(lt["tm_obs"])
        dms = int(lt["delta_macro_stance"])
        deq = int(lt["delta_equity"])
        if age <= 90 and (dms >= 2 or int(lt["surprise_direction"]) > 0):
            d2 = 6
        elif age <= 90 and (dms >= 1 or deq >= 1):
            d2 = 4
        elif dms <= -2 or int(lt["tone_deleveraging"]) <= -2:
            d2 = 0
        elif ms >= 4:
            d2 = 4
        else:
            d2 = 2
        s_d = int(d1 + d2)
        lt_meta = {"meeting": f"{lt['event_date']} {lt['meeting_type']}", "macro_stance": ms, "delta_macro_stance": dms}

    # 5. Pillar E: Macro Pain Threshold & CN-US Spread/FX Constraint (0-15)
    m12 = r["cn_m1_m2_diff"]
    m12_m = r["cn_m1_m2_diff_mom"]
    e1 = 4 if (pd.notna(m12_m) and m12_m > 0) else (2 if (pd.notna(m12) and m12 <= -5.5) else 1)
    pmi = r["cn_pmi_mfg"]
    e2 = 4 if (pd.notna(rc) and rc < -0.05) else (0 if (pd.notna(rc) and rc > 0.05) else (3 if (pd.notna(pmi) and pmi >= 50.5) else 2))
    sp = r["cn_us_10y_spread_bp"]
    e3 = 4 if (pd.notna(sp) and sp >= 80) else (3 if (pd.notna(sp) and sp >= 0) else (1 if (pd.notna(sp) and sp >= -150) else 0))
    fx = r["usdcny_chg_60d"]
    e4 = 3 if (pd.notna(fx) and fx <= -0.02) else (2 if (pd.notna(fx) and fx <= 0.04) else 0)
    s_e = int(e1 + e2 + e3 + e4)

    tot = int(np.clip(s_a + s_b + s_c + s_d + s_e, 0, 100))
    g4_freeze = int((pd.notna(ma2) and ma2 < 0.20) or (pd.notna(r["bench_dd_60d"]) and r["bench_dd_60d"] <= -0.15) or (pd.notna(r["amount_pct_250d"]) and r["amount_pct_250d"] <= 0.25))
    return {
        "gate_score": s_a,
        "gate1_bleed": int(g1),
        "gate2_balance_sheet": int(g2),
        "gate3_top_level": int(g3),
        "gate4_freeze_flag": g4_freeze,
        "waterpool_score": s_b,
        "breadth_erp_score": s_c,
        "meeting_diff_score": s_d,
        "macro_constraint_score": s_e,
        "waterpool_regime_score": tot,
        "regime_label": _regime_label(tot),
        "latest_meeting": lt_meta["meeting"],
    }


def compute_waterpool_regime_panel(include_nov2026_mtd: bool = False) -> pd.DataFrame:
    """Build daily panel (2005-01-04 ~ 2026-11-24) with strictly PIT Waterpool Regime Scores."""
    wp = pd.read_parquet(os.path.join(PILLAR_DIR, "pillar1_waterpool_monthly.parquet"))
    bd = pd.read_parquet(os.path.join(PILLAR_DIR, "pillar1_market_breadth_daily.parquet"))
    mp4 = pd.read_parquet(os.path.join(PILLAR_DIR, "pillar4_macro_pain_daily_pit.parquet"))
    tm = pd.read_parquet(os.path.join(PILLAR_DIR, "pillar2_top_meetings_diff.parquet"))
    ev = pd.read_parquet(os.path.join(ROOT, "output/csrc_policy_100factors_20261114/policy_polymarket_v1/master_events_v2_20261125.parquet"))
    panel, _, _ = cm.load_market_panel()

    p = panel[panel["date"] >= "2005-01-04"].copy().reset_index(drop=True)
    p["dt"] = pd.to_datetime(p["date"])
    bd["date_str"] = bd["date"].dt.strftime("%Y-%m-%d")
    mp4["date_str"] = mp4["date"].dt.strftime("%Y-%m-%d")

    wp = wp.copy()
    wp["eq_supply_pct_mcap"] = (
        wp["ipo_raised_yi"].fillna(0.0)
        + wp["refinance_yi"].fillna(0.0)
        + wp["insider_net_reduce_yi"].fillna(0.0).clip(lower=0.0)
    ) / wp["eom_float_mcap_yi"] * 100.0
    if include_nov2026_mtd:
        wp.loc[wp["month"] == "2026-11", "available_date"] = pd.Timestamp("2026-11-24")

    wp_cols = [
        "month", "ipo_raised_yi", "drain_total_pct_mcap", "drain_total_pct_mcap_pct_5y",
        "net_waterpool_trading_pct_mcap", "net_waterpool_trading_pct_mcap_pct_5y",
        "net_waterpool_incl_div_pct_mcap", "eq_supply_pct_mcap", "buyback_yi", "nt_etf_weighted_flow_yi",
    ]
    wp_j = pit_asof_join(p[["dt"]].rename(columns={"dt": "date"}), wp, "available_date", wp_cols, max_staleness_days=60)
    for c in wp_cols:
        p[c] = wp_j[c].values

    p = p.merge(
        bd[["date_str", "pct_above_ma20", "pct_above_ma60", "pct_above_ma200", "pct_new_low_250d",
            "erp_csi300_pct", "erp_all_a_median_pct", "erp_csi300_pct_5y", "erp_all_a_pct_5y",
            "amount_pct_250d", "etf_nt_weighted_flow_yi", "margin_balance_yi"]],
        left_on="date", right_on="date_str", how="left", suffixes=("", "_bd"),
    )
    p = p.merge(
        mp4[["date_str", "cn_m1_m2_diff", "cn_m1_m2_diff_mom", "cn_m1_yoy_mom", "cn_pmi_mfg",
             "cn_policy_rate_1y", "cn_bond_10y", "us_dgs10", "cn_us_10y_spread_bp", "usdcny", "usdcny_chg_60d"]],
        left_on="date", right_on="date_str", how="left", suffixes=("", "_mp4"),
    )

    p_dates = p["date"].tolist()
    p_d2i = {d: i for i, d in enumerate(p_dates)}
    t_arr = np.array(p_dates)
    ev = ev.copy()
    ev["p_obs"] = [
        p_d2i[str(r["event_date"])[:10]] + (0 if str(r.get("release_slot", "AMC")).upper() in ("BMO", "INTRADAY") else 1)
        if str(r["event_date"])[:10] in p_d2i
        else int(np.searchsorted(t_arr, str(r["event_date"])[:10], side="left"))
        for _, r in ev.iterrows()
    ]

    m_g1 = (ev["ipo_supply_tightening"] >= 1) | (ev["share_reduction_crackdown"] >= 1) | ev["hard_levers_joined"].fillna("").str.contains("IPO_PAUSE", regex=True)
    m_g2 = (ev["action_verb_stage"] == "HARD_ACTION_NOW") & (
        ev["authority_level"].isin(["PBOC_HARD_TOOL", "HUIJIN_NATIONAL_TEAM", "FISCAL_SASAC", "STATE_COUNCIL_EXEC", "FSDC_VICE_PREMIER", "JOINT_MINISTRY_SCIO"])
        | ev["hard_levers_joined"].fillna("").str.contains("PBOC_SFISF|HUIJIN_BUY|FISCAL_CAPITAL_INJECT", regex=True)
    ) & (ev["market_rescue_signal"] >= 1)
    m_g3 = ev["authority_level"].isin(["POLITBURO", "CENTRAL_ECON_CONF", "CENTRAL_FIN_CONF", "STATE_COUNCIL_EXEC", "STATE_COUNCIL_NINE_ARTICLES", "FSDC_VICE_PREMIER"]) & (
        (ev["market_rescue_signal"] >= 1) | (ev["liquidity_long_term_capital"] >= 1)
    )
    m_tight = (ev["market_rescue_signal"] <= -1) | (ev["speculation_fraud_crackdown"] >= 1)
    idx_sets = {
        "g1": ev.loc[m_g1, "p_obs"].to_numpy(),
        "g2": ev.loc[m_g2, "p_obs"].to_numpy(),
        "g3": ev.loc[m_g3, "p_obs"].to_numpy(),
        "tight": ev.loc[m_tight, "p_obs"].to_numpy(),
    }

    tm_s = tm.sort_values("tradable_date").copy()
    tm_s["tm_obs"] = [int(np.searchsorted(t_arr, str(d)[:10], side="left")) for d in tm_s["tradable_date"]]

    p["etf_flow_20d"] = p["etf_nt_weighted_flow_yi"].rolling(20, min_periods=1).sum()
    p["v3_max_10d"] = np.maximum(p["v3_score_live"].fillna(-1), p["v3_score_eod"].fillna(-1)).rolling(10, min_periods=1).max()
    p["rate_chg_120d"] = p["cn_policy_rate_1y"] - p["cn_policy_rate_1y"].shift(120)
    p["margin_chg_20d_pct"] = p["margin_balance_yi"] / p["margin_balance_yi"].shift(20) - 1.0
    p["bench_ma60"] = p["bench_level"].rolling(60, min_periods=20).mean()
    p["bench_above_ma60"] = (p["bench_level"] > p["bench_ma60"]).astype(int)

    # Causal style sleeve open/close series (zero lookahead pre-inception splicing)
    # Growth sleeve = 50% csi1000 (else csi500 else ew) + 50% tech_board (else ew)
    # Defensive sleeve = csi_div (else sse50)
    # Track cumulative level curves of daily open-to-open returns from spliced daily cc/gap
    sc_rows = [_calc_daily_score_row(p.iloc[i], i, idx_sets, tm_s) for i in range(len(p))]
    sc_df = pd.DataFrame(sc_rows)
    out = pd.concat([p, sc_df], axis=1)
    return out


def _compute_metrics(rets: np.ndarray, eq_weights: np.ndarray, turn_oneway: np.ndarray, years: float, bench_rets: np.ndarray = None) -> dict:
    if len(rets) == 0:
        return {}
    nav = np.cumprod(np.insert(1.0 + rets, 0, 1.0))
    cum = (nav[-1] - 1.0) * 100.0
    ann = (nav[-1] ** (1.0 / max(years, 0.1)) - 1.0) * 100.0
    vol = float(np.std(rets, ddof=1) * np.sqrt(52.0)) * 100.0
    pk = np.maximum.accumulate(nav)
    mdd = float(np.min(nav / pk - 1.0)) * 100.0
    sharpe = float(np.mean(rets) / (np.std(rets, ddof=1) + 1e-12) * np.sqrt(52.0))
    calmar = ann / abs(mdd) if abs(mdd) > 1e-6 else 0.0
    tw_turn_yr = float(np.sum(turn_oneway) / max(years, 0.1)) * 100.0
    ex_ann = None
    if bench_rets is not None:
        b_nav = np.cumprod(np.insert(1.0 + bench_rets, 0, 1.0))
        b_ann = (b_nav[-1] ** (1.0 / max(years, 0.1)) - 1.0) * 100.0
        ex_ann = round(ann - b_ann, 2)
    return {
        "n_weeks": int(len(rets)),
        "cum_ret_pct": round(cum, 2),
        "ann_ret_pct": round(ann, 2),
        "ann_vol_pct": round(vol, 2),
        "mdd_pct": round(mdd, 2),
        "sharpe": round(sharpe, 2),
        "calmar": round(calmar, 2),
        "avg_eq_weight_pct": round(float(np.mean(eq_weights)) * 100.0, 1),
        "annual_turnover_pct": round(tw_turn_yr, 1),
        "excess_ann_vs_csi300_pp": ex_ann,
    }


def _spliced_period_ret(p: pd.DataFrame, t0: int, t1: int, col_priority: list[str]) -> float:
    for col in col_priority:
        o0 = p.at[t0, f"{col}_open"]
        o1 = p.at[t1, f"{col}_open"]
        if pd.notna(o0) and pd.notna(o1) and o0 > 0 and o1 > 0:
            return float(o1 / o0 - 1.0)
    return float(p.at[t1, "csi300_open"] / p.at[t0, "csi300_open"] - 1.0)


def run_weekly_backtest(p: pd.DataFrame) -> dict:
    """Weekly Friday signal -> next Monday open execution with 0.30% round-trip cost."""
    p = p.copy()
    p["yw"] = p["dt"].dt.strftime("%G-%V")
    wk_idx = p.groupby("yw", sort=False).tail(1).index.tolist()
    p_d2i = {d: i for i, d in enumerate(p["date"].tolist())}

    # Start >= 2005-04-15 (when CSI300 open/close is fully valid)
    wk_dates = [p.at[i, "date"] for i in wk_idx if p.at[i, "date"] >= "2005-04-15"]
    records = []

    prev_w_dyn = 0.0
    prev_style_vec = np.zeros(4)  # [csi300, growth_small, growth_tech, div]

    for k in range(len(wk_dates) - 1):
        d_sig = wk_dates[k]
        d_next = wk_dates[k + 1]
        i0 = p_d2i[d_sig]
        i1 = p_d2i[d_next]
        t_enter = i0 + 1
        t_exit = i1 + 1
        if t_exit >= len(p):
            break

        dt_days = (pd.Timestamp(p.at[t_exit, "date"]) - pd.Timestamp(p.at[t_enter, "date"])).days
        rf_yield = float(p.at[i0, "cn_bond_10y"]) if pd.notna(p.at[i0, "cn_bond_10y"]) else 3.0
        r_rf = rf_yield / 100.0 * (dt_days / 365.0)

        r_300 = float(p.at[t_exit, "csi300_open"] / p.at[t_enter, "csi300_open"] - 1.0)
        r_ew = float(p.at[t_exit, "ew_open"] / p.at[t_enter, "ew_open"] - 1.0)
        r_sm = _spliced_period_ret(p, t_enter, t_exit, ["csi1000", "csi500", "ew"])
        r_tk = _spliced_period_ret(p, t_enter, t_exit, ["tech_board", "ew"])
        r_dv = _spliced_period_ret(p, t_enter, t_exit, ["csi_div", "sse50"])

        tot = int(p.at[i0, "waterpool_regime_score"])
        # Strategy 3: Dynamic CSI300 + 10Y CGB
        w_dyn = 1.0 if tot >= 70 else (0.70 if tot >= 50 else (0.30 if tot >= 30 else 0.0))
        turn_dyn = abs(w_dyn - prev_w_dyn)
        cost_dyn = ONE_WAY_COST * turn_dyn
        prev_w_dyn = w_dyn
        r_dyn = w_dyn * r_300 + (1.0 - w_dyn) * r_rf - cost_dyn

        # Strategy 4: Dynamic Style + 10Y CGB
        if tot >= 70:
            s_vec = np.array([0.0, 0.50, 0.50, 0.0])  # 100% offensive small/tech
        elif tot >= 50:
            s_vec = np.array([0.35, 0.175, 0.175, 0.0])  # 70% balanced CSI300 + growth
        elif tot >= 30:
            s_vec = np.array([0.0, 0.0, 0.0, 0.30])  # 30% high dividend defense
        else:
            s_vec = np.array([0.0, 0.0, 0.0, 0.0])  # 0% equity, 100% 10Y CGB
        turn_style = float(np.sum(np.abs(s_vec - prev_style_vec)))
        cost_style = ONE_WAY_COST * turn_style
        prev_style_vec = s_vec
        w_style = float(np.sum(s_vec))
        r_style = float(np.dot(s_vec, [r_300, r_sm, r_tk, r_dv])) + (1.0 - w_style) * r_rf - cost_style

        records.append({
            "sig_date": d_sig,
            "entry_date": p.at[t_enter, "date"],
            "exit_date": p.at[t_exit, "date"],
            "score": tot,
            "regime": p.at[i0, "regime_label"],
            "r_300": r_300,
            "r_ew": r_ew,
            "r_dyn": r_dyn,
            "w_dyn": w_dyn,
            "turn_dyn": turn_dyn,
            "r_style": r_style,
            "w_style": w_style,
            "turn_style": turn_style,
        })

    bt = pd.DataFrame(records)
    windows = {
        "FULL_2005_2026": ("2005-04-15", "2026-11-24"),
        "IS_2005_2020": ("2005-04-15", "2020-12-31"),
        "OOS_2021_2026": ("2021-01-01", "2026-11-24"),
        "OOS_3Y_2024_2026": ("2024-01-01", "2026-11-24"),
    }
    res = {}
    for wname, (d_lo, d_hi) in windows.items():
        sub = bt[(bt["sig_date"] >= d_lo) & (bt["sig_date"] <= d_hi)]
        if sub.empty:
            continue
        yrs = (pd.Timestamp(sub["exit_date"].iloc[-1]) - pd.Timestamp(sub["entry_date"].iloc[0])).days / 365.25
        b_r = sub["r_300"].to_numpy()
        res[wname] = {
            "CSI300_BH": _compute_metrics(b_r, np.ones(len(sub)), np.zeros(len(sub)), yrs, b_r),
            "AllA_EW_BH": _compute_metrics(sub["r_ew"].to_numpy(), np.ones(len(sub)), np.zeros(len(sub)), yrs, b_r),
            "Waterpool_Dyn_CSI300": _compute_metrics(sub["r_dyn"].to_numpy(), sub["w_dyn"].to_numpy(), sub["turn_dyn"].to_numpy(), yrs, b_r),
            "Waterpool_Dyn_Style": _compute_metrics(sub["r_style"].to_numpy(), sub["w_style"].to_numpy(), sub["turn_style"].to_numpy(), yrs, b_r),
        }

    # Forward bucket returns in IS & OOS
    p["fwd20_300"] = [cm.calc_fwd_return(p, i + 1, 20, "csi300") if i + 20 < len(p) else np.nan for i in range(len(p))]
    p["fwd60_300"] = [cm.calc_fwd_return(p, i + 1, 60, "csi300") if i + 60 < len(p) else np.nan for i in range(len(p))]
    p["fwd20_ew"] = [cm.calc_fwd_return(p, i + 1, 20, "ew") if i + 20 < len(p) else np.nan for i in range(len(p))]
    wk_p = p.loc[[p_d2i[d] for d in wk_dates]].copy()
    wk_p["bucket"] = pd.cut(wk_p["waterpool_regime_score"], bins=[-1, 29, 49, 69, 101], labels=["<30", "30-49", "50-69", ">=70"])

    bucket_stats = {}
    for sp_name, mask in [("IS_2005_2020", wk_p["date"] <= "2020-12-31"), ("OOS_2021_2026", wk_p["date"] >= "2021-01-01")]:
        rows_b = []
        sub_sp = wk_p[mask]
        for b in ["<30", "30-49", "50-69", ">=70"]:
            g = sub_sp[sub_sp["bucket"] == b]
            rows_b.append({
                "bucket": b,
                "n_weeks": int(len(g)),
                "share_pct": round(len(g) / max(len(sub_sp), 1) * 100.0, 1),
                "fwd_20td_csi300_mean_pct": round(float(g["fwd20_300"].mean()) * 100.0, 2) if g["fwd20_300"].notna().any() else None,
                "fwd_60td_csi300_mean_pct": round(float(g["fwd60_300"].mean()) * 100.0, 2) if g["fwd60_300"].notna().any() else None,
                "fwd_20td_ew_mean_pct": round(float(g["fwd20_ew"].mean()) * 100.0, 2) if g["fwd20_ew"].notna().any() else None,
            })
        bucket_stats[sp_name] = rows_b
    return {"backtest_windows": res, "bucket_forward_returns": bucket_stats}


def main():
    p_pit = compute_waterpool_regime_panel(include_nov2026_mtd=False)
    p_mtd = compute_waterpool_regime_panel(include_nov2026_mtd=True)

    bt_out = run_weekly_backtest(p_pit)

    # Landmark audit across key historical inflections
    landmarks = [
        ("2007-10-12", "2007.10 6124泡沫估值顶"),
        ("2008-04-25", "2008.04 4·24印花税假底"),
        ("2008-11-14", "2008.11 四万亿真政策底"),
        ("2012-05-25", "2012.05 稳增长口号假底"),
        ("2014-11-28", "2014.11 央行降息+沪港通真底"),
        ("2015-06-12", "2015.06 5178杠杆泡沫顶"),
        ("2015-07-03", "2015.07 股灾救市一浪假底"),
        ("2015-08-28", "2015.08 8·25双降真底"),
        ("2016-01-08", "2016.01 熔断叫停假底"),
        ("2018-10-19", "2018.10 副总理一行两会救市"),
        ("2018-11-02", "2018.11 10·31政治局确认真底"),
        ("2020-03-27", "2020.03 非常规政治局真底"),
        ("2022-03-18", "2022.03 3·16金融委一浪假底"),
        ("2023-07-28", "2023.07 7·24政治局后假底"),
        ("2024-09-20", "2024.09 9·24大招前夜"),
        ("2024-09-27", "2024.09 9·24 SFISF+926政治局真底"),
        ("2025-04-11", "2025.04 汇金类平准抗击关税"),
    ]
    lm_rows = []
    for dt, desc in landmarks:
        sub = p_pit[p_pit["date"] <= dt].tail(1)
        if not sub.empty:
            r = sub.iloc[0]
            lm_rows.append({
                "date": r["date"],
                "landmark": desc,
                "score": int(r["waterpool_regime_score"]),
                "regime": r["regime_label"],
                "A_gates": int(r["gate_score"]),
                "B_waterpool": int(r["waterpool_score"]),
                "C_breadth_erp": int(r["breadth_erp_score"]),
                "D_meetings": int(r["meeting_diff_score"]),
                "E_macro_fx": int(r["macro_constraint_score"]),
            })

    def _extract_snapshot(df_row: pd.Series, wp_tag: str) -> dict:
        return {
            "date": str(df_row["date"]),
            "waterpool_month_used": f"{df_row['month']} ({wp_tag})",
            "total_score": int(df_row["waterpool_regime_score"]),
            "regime_label": str(df_row["regime_label"]),
            "target_equity_weight_pct": 100 if int(df_row["waterpool_regime_score"]) >= 70 else (70 if int(df_row["waterpool_regime_score"]) >= 50 else (30 if int(df_row["waterpool_regime_score"]) >= 30 else 0)),
            "breakdown": {
                "A_physical_gates_25": {
                    "score": int(df_row["gate_score"]),
                    "gate1_bleed_valve_7": int(df_row["gate1_bleed"]),
                    "gate2_balance_sheet_10": int(df_row["gate2_balance_sheet"]),
                    "gate3_top_level_8": int(df_row["gate3_top_level"]),
                    "gate4_freeze_flag": int(df_row["gate4_freeze_flag"]),
                },
                "B_waterpool_ledger_20": int(df_row["waterpool_score"]),
                "C_breadth_erp_25": int(df_row["breadth_erp_score"]),
                "D_top_meetings_diff_15": int(df_row["meeting_diff_score"]),
                "E_macro_pain_cn_us_15": int(df_row["macro_constraint_score"]),
            },
            "raw_diagnostics": {
                "csi300_close": round(float(df_row["csi300_close"]), 2),
                "pct_above_ma200_pct": round(float(df_row["pct_above_ma200"]) * 100.0, 2),
                "erp_csi300_pct": round(float(df_row["erp_csi300_pct"]), 2),
                "erp_all_a_median_pct": round(float(df_row["erp_all_a_median_pct"]), 2),
                "net_waterpool_trading_pct_mcap": round(float(df_row["net_waterpool_trading_pct_mcap"]), 4),
                "eq_supply_pct_mcap": round(float(df_row["eq_supply_pct_mcap"]), 4),
                "cn_m1_m2_diff": round(float(df_row["cn_m1_m2_diff"]), 2),
                "cn_us_10y_spread_bp": round(float(df_row["cn_us_10y_spread_bp"]), 1),
                "usdcny_chg_60d": round(float(df_row["usdcny_chg_60d"]), 4),
                "latest_top_meeting": df_row["latest_meeting"],
                "v3_max_10d": int(df_row["v3_max_10d"]),
            },
        }

    snap_pit = _extract_snapshot(p_pit.iloc[-1], "strict_completed_month_available_le_2026-11-24")
    snap_mtd = _extract_snapshot(p_mtd.iloc[-1], "nov_mtd_available_2026-11-25")

    audit = {
        "meta": {
            "tool": "Tool 1: China Policy Waterpool Regime Dashboard V1.0 (0-100 Integer)",
            "d12_compliant": True,
            "is_window": "2005-04-15 ~ 2020-12-31",
            "oos_window": "2021-01-01 ~ 2026-11-24",
            "execution": "Weekly Friday close signal -> Next Monday open execution, two-way 0.30% equity cost + 10Y CGB yield accrual",
        },
        "current_2026_11_24_pit_completed_month": snap_pit,
        "current_2026_11_25_with_nov_mtd": snap_mtd,
        "backtest_windows": bt_out["backtest_windows"],
        "bucket_forward_returns": bt_out["bucket_forward_returns"],
        "landmark_scores": lm_rows,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print("=== TOOL 1: WATERPOOL REGIME DASHBOARD V1.0 ===")
    print(f"2026-11-24 Strict PIT (2026-10 WP): Score={snap_pit['total_score']} [{snap_pit['regime_label']}] | "
          f"A={snap_pit['breakdown']['A_physical_gates_25']['score']}/25 "
          f"B={snap_pit['breakdown']['B_waterpool_ledger_20']}/20 "
          f"C={snap_pit['breakdown']['C_breadth_erp_25']}/25 "
          f"D={snap_pit['breakdown']['D_top_meetings_diff_15']}/15 "
          f"E={snap_pit['breakdown']['E_macro_pain_cn_us_15']}/15")
    print(f"2026-11-25 With Nov-MTD (2026-11 WP): Score={snap_mtd['total_score']} [{snap_mtd['regime_label']}] | "
          f"B={snap_mtd['breakdown']['B_waterpool_ledger_20']}/20")
    for wn, wd in bt_out["backtest_windows"].items():
        print(f"\n[{wn}]")
        for sn, sm in wd.items():
            print(f"  {sn:22s}: Ann={sm['ann_ret_pct']:+6.2f}% MDD={sm['mdd_pct']:7.2f}% Sharpe={sm['sharpe']:5.2f} "
                  f"Calmar={sm['calmar']:5.2f} Ex300={str(sm['excess_ann_vs_csi300_pp']):>6s}pp Turn={sm['annual_turnover_pct']:5.1f}%")
    print(f"\nSaved -> {OUT_JSON}")


if __name__ == "__main__":
    main()
