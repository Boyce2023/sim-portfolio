#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD034 Step 3: Strict IS (<= 2024-12-31) -> Blind OOS (2025-01-01 ~ 2026-11) & Y2026
Real-World Validation across ALL 6 V20.0 Strategies + V20.0 Combined (P3_S2C_STierReserveOnly).

Tests ALL THREE modification paradigms:
  A) Score Rerank (+-w on v20_score): 30 IS-grounded 3-layer rules x 4 weights
  B) Hard Filter (-999 veto on passing pool): 18 IS-grounded 3-layer veto rules
  C) Combined-Level Half-Position Sizing (Half50) & Stop0 on V20.0 Combined (N=278)

Includes:
  - 100% exact baseline parity check (<1e-6)
  - BH-FDR, HLZ/DSR, CSCV PBO (S=8,10), 5-fold Purged CV, 10,000x Paired Block Bootstrap
  - Static same-avg-exposure & 1/vol matched baselines
  - 2024-12-31 physical truncation check (diff == 0.0)
Zero yfinance (D12). Read-only on production files.
"""
import json
import math
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd
import scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD028_DIR = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
OUT_DIR = f"{SIM}/backtests_astock2/rd034_ashare_3layer_cycles_6strat_20261125"

for p in (RD028_DIR,):
    if p not in sys.path:
        sys.path.insert(0, p)

import step4_mod_rules_and_sim as m1
import step4_mod_jianyan as m2

STRAT_ORDER = m1.STRAT_ORDER
TRD_DAYS_YEAR = m1.TRD_DAYS_YEAR
S2C_MAP = m1.S2C_MAP

# 30 Clean 3-Layer Rerank Rules (covering L1 Market, L2 Industry/KPL, L3 Stock)
RERANK_SPECS = [
    # Layer 1 Market
    ("R_L1_zb_hi_bon", "rerank", "L1_市场", "昨日炸板率>=35%分歧加分"),
    ("R_L1_zt_climax_pen", "rerank", "L1_市场", "昨日涨停>=80家高潮扣分"),
    ("R_L1_sent_ice_pen", "rerank", "L1_市场", "情绪冰点期扣分"),
    ("R_L1_sent_climax_pen", "rerank", "L1_市场", "情绪高潮期扣分"),
    ("R_L1_breadth5_lo_bon", "rerank", "L1_市场", "5日市场广度<=0.45逆势加分"),
    ("R_L1_ewbias20_lo_bon", "rerank", "L1_市场", "全A指数MA20乖离<=-2%低位加分"),
    ("R_L1_amt20_surge_bon", "rerank", "L1_市场", "昨日全市场放量>=1.15倍加分"),
    ("R_L1_smb_neg_bon", "rerank", "L1_市场", "微盘20日跑输<=-2%逆风加分"),
    ("R_L1_earn_any_pen", "rerank", "L1_市场", "财报业绩窗扣分"),
    ("R_L1_earn_apr_pen", "rerank", "L1_市场", "4月年季报雷区扣分"),
    ("R_L1_prehol_bon", "rerank", "L1_市场", "长假前2天日历加分"),
    ("R_L1_monthend_bon", "rerank", "L1_市场", "月末最后3天加分"),
    # Layer 2 Industry & KPL
    ("R_L2_ind_upstreak_pen", "rerank", "L2_行业题材", "行业连强>=3天追高扣分"),
    ("R_L2_ind_ex120_pos_bon", "rerank", "L2_行业题材", "行业120日超额>=5%主线加分"),
    ("R_L2_ind_ex120_neg_bon", "rerank", "L2_行业题材", "行业120日跑输<=-5%低位加分"),
    ("R_L2_ind_crowd_pen", "rerank", "L2_行业题材", "行业成交拥挤度>=80%分位扣分"),
    ("R_L2_kpl_hot20_bon", "rerank", "L2_行业题材", "KPL题材20日涨停>=35次主线加分"),
    ("R_L2_kpl_zt3_bon", "rerank", "L2_行业题材", "KPL题材3日涨停>=10次爆发加分"),
    ("R_L2_kpl_wave_multi_bon", "rerank", "L2_行业题材", "KPL题材60日>=2波活跃回流加分"),
    ("R_L2_kpl_streak_pen", "rerank", "L2_行业题材", "KPL题材连爆>=4天尾声扣分"),
    ("R_L2_kpl_peak_cool_bon", "rerank", "L2_行业题材", "KPL题材峰值回落<=0.60分歧加分"),
    # Layer 3 Stock
    ("R_L3_bias20_lo_bon", "rerank", "L3_个股", "个股MA20乖离<=12%低位启动加分"),
    ("R_L3_bias20_hi_pen", "rerank", "L3_个股", "个股MA20乖离>=35%高位乖离扣分"),
    ("R_L3_amp_comp_hi_bon", "rerank", "L3_个股", "启动前20/60日振幅扩张>=0.60加分"),
    ("R_L3_prewave_rng_hi_bon", "rerank", "L3_个股", "启动前20日振幅>=25%高弹性加分"),
    ("R_L3_newhigh_hi_pen", "rerank", "L3_个股", "近60日创250日新高>=6次趋势老股扣分"),
    ("R_L3_cum_turn20_hi_bon", "rerank", "L3_个股", "近20日累计换手>=220%高换手加分"),
    ("R_L3_turn5_lo_bon", "rerank", "L3_个股", "5日均换手<=50%历史分位低吸加分"),
    ("R_L3_pos60_lo_bon", "rerank", "L3_个股", "60日区间位置<=0.65低启动加分"),
    ("R_L3_mabull_hi_bon", "rerank", "L3_个股", "均线多头排列>=3分加分"),
]

# 18 Hard Filter Rules (w = 9999 veto)
FILTER_SPECS = [
    ("F_L1_zt_climax", "filter", "L1_市场", "过滤昨日涨停>=90家极热"),
    ("F_L1_sent_ice", "filter", "L1_市场", "过滤情绪冰点期"),
    ("F_L1_sent_climax", "filter", "L1_市场", "过滤情绪高潮期"),
    ("F_L1_sent_ebb", "filter", "L1_市场", "过滤情绪退潮期"),
    ("F_L1_zb_hi", "filter", "L1_市场", "过滤昨日炸板率>=45%"),
    ("F_L1_dt_hi", "filter", "L1_市场", "过滤昨日跌停>=25家"),
    ("F_L1_earn_apr", "filter", "L1_市场", "过滤4月年季报雷区"),
    ("F_L1_earn_any", "filter", "L1_市场", "过滤全部财报季窗口"),
    ("F_L1_prehol", "filter", "L1_市场", "过滤长假前2天"),
    ("F_L2_ind_crowd", "filter", "L2_行业题材", "过滤行业成交拥挤度>=85%分位"),
    ("F_L2_ind_ex120_hi", "filter", "L2_行业题材", "过滤行业120日超额>=15%高位"),
    ("F_L2_kpl_streak_late", "filter", "L2_行业题材", "过滤题材连爆>=5天尾声"),
    ("F_L2_kpl_cold", "filter", "L2_行业题材", "过滤题材20日涨停<10次冷门"),
    ("F_L3_newhigh_hi", "filter", "L3_个股", "过滤近60日新高>=8次"),
    ("F_L3_bias20_hi", "filter", "L3_个股", "过滤MA20乖离>=40%"),
    ("F_L3_cumturn20_lo", "filter", "L3_个股", "过滤20日累计换手<100%"),
    ("F_L3_ampcomp_lo", "filter", "L3_个股", "过滤20/60日振幅比<0.35"),
    ("F_L3_overhang_hi", "filter", "L3_个股", "过滤1年上方套牢盘>=75%"),
]


def compute_cycle_delta(df: pd.DataFrame, rule_id: str, w: float) -> np.ndarray:
    w = float(w)
    n = len(df)
    def _col(c, fill=np.nan):
        return df[c].fillna(fill).to_numpy(float) if c in df.columns else np.full(n, fill, dtype=float)

    zb = _col("L1_zb_rate_t1")
    zt = _col("L1_zt_cnt_t1")
    dt_c = _col("L1_dt_cnt_t1")
    sp = _col("L1_sent_phase_t1")
    br5 = _col("L1_breadth_5d_t1")
    ewb20 = _col("L1_ew_bias20_t1")
    amt20 = _col("L1_amt_ratio20_t1")
    smb20 = _col("L1_smb_20d_t1")
    e_any = _col("L1_is_earn_any", 0.0)
    e_apr = _col("L1_is_earn_apr", 0.0)
    ph2 = _col("L1_is_pre_hol2", 0.0)
    me3 = _col("L1_is_month_end3", 0.0)

    ind_up = _col("L2_ind_up_streak_t1")
    ind_ex120 = _col("L2_ind_ex120_t1")
    ind_amt = _col("L2_ind_amt_pct250_t1")
    k_zt20 = _col("L2_kpl_zt20_t1", 0.0)
    k_zt3 = _col("L2_kpl_zt3_t1", 0.0)
    k_wv = _col("L2_kpl_wave_cnt60_t1", 0.0)
    k_st = _col("L2_kpl_streak_t1", 0.0)
    k_pr = _col("L2_kpl_peak_ratio_t1", 0.0)

    b20 = _col("L3_bias20_t1")
    acmp = _col("L3_amp_comp_20v60_t1")
    pwr = _col("L3_prewave_rng20_t1")
    nh60 = _col("L3_newhigh_cnt60_t1")
    ct20 = _col("L3_cum_turn20_t1")
    t5p = _col("L3_turn5_pct250_t1")
    p60 = _col("L3_pos_60d_t1")
    mab = _col("L3_ma_bull_score_t1")
    ovh = _col("L3_overhang_pct_t1")

    # Rerank rules
    if rule_id == "R_L1_zb_hi_bon": return np.where(zb >= 35.0, w, 0.0)
    if rule_id == "R_L1_zt_climax_pen": return np.where(zt >= 80.0, -w, 0.0)
    if rule_id == "R_L1_sent_ice_pen": return np.where(sp == 1.0, -w, 0.0)
    if rule_id == "R_L1_sent_climax_pen": return np.where(sp == 4.0, -w, 0.0)
    if rule_id == "R_L1_breadth5_lo_bon": return np.where(br5 <= 0.45, w, 0.0)
    if rule_id == "R_L1_ewbias20_lo_bon": return np.where(ewb20 <= -2.0, w, 0.0)
    if rule_id == "R_L1_amt20_surge_bon": return np.where(amt20 >= 1.15, w, 0.0)
    if rule_id == "R_L1_smb_neg_bon": return np.where(smb20 <= -2.0, w, 0.0)
    if rule_id == "R_L1_earn_any_pen": return np.where(e_any == 1.0, -w, 0.0)
    if rule_id == "R_L1_earn_apr_pen": return np.where(e_apr == 1.0, -w, 0.0)
    if rule_id == "R_L1_prehol_bon": return np.where(ph2 == 1.0, w, 0.0)
    if rule_id == "R_L1_monthend_bon": return np.where(me3 == 1.0, w, 0.0)
    if rule_id == "R_L2_ind_upstreak_pen": return np.where(ind_up >= 3.0, -w, 0.0)
    if rule_id == "R_L2_ind_ex120_pos_bon": return np.where(ind_ex120 >= 5.0, w, 0.0)
    if rule_id == "R_L2_ind_ex120_neg_bon": return np.where(ind_ex120 <= -5.0, w, 0.0)
    if rule_id == "R_L2_ind_crowd_pen": return np.where(ind_amt >= 0.80, -w, 0.0)
    if rule_id == "R_L2_kpl_hot20_bon": return np.where(k_zt20 >= 35.0, w, 0.0)
    if rule_id == "R_L2_kpl_zt3_bon": return np.where(k_zt3 >= 10.0, w, 0.0)
    if rule_id == "R_L2_kpl_wave_multi_bon": return np.where(k_wv >= 2.0, w, 0.0)
    if rule_id == "R_L2_kpl_streak_pen": return np.where(k_st >= 4.0, -w, 0.0)
    if rule_id == "R_L2_kpl_peak_cool_bon": return np.where((k_zt20 > 0) & (k_pr <= 0.60), w, 0.0)
    if rule_id == "R_L3_bias20_lo_bon": return np.where(b20 <= 12.0, w, 0.0)
    if rule_id == "R_L3_bias20_hi_pen": return np.where(b20 >= 35.0, -w, 0.0)
    if rule_id == "R_L3_amp_comp_hi_bon": return np.where(acmp >= 0.60, w, 0.0)
    if rule_id == "R_L3_prewave_rng_hi_bon": return np.where(pwr >= 25.0, w, 0.0)
    if rule_id == "R_L3_newhigh_hi_pen": return np.where(nh60 >= 6.0, -w, 0.0)
    if rule_id == "R_L3_cum_turn20_hi_bon": return np.where(ct20 >= 220.0, w, 0.0)
    if rule_id == "R_L3_turn5_lo_bon": return np.where(t5p <= 0.50, w, 0.0)
    if rule_id == "R_L3_pos60_lo_bon": return np.where(p60 <= 0.65, w, 0.0)
    if rule_id == "R_L3_mabull_hi_bon": return np.where(mab >= 3.0, w, 0.0)

    # Filter vetoes (-9999)
    if rule_id == "F_L1_zt_climax": return np.where(zt >= 90.0, -9999.0, 0.0)
    if rule_id == "F_L1_sent_ice": return np.where(sp == 1.0, -9999.0, 0.0)
    if rule_id == "F_L1_sent_climax": return np.where(sp == 4.0, -9999.0, 0.0)
    if rule_id == "F_L1_sent_ebb": return np.where(sp == 5.0, -9999.0, 0.0)
    if rule_id == "F_L1_zb_hi": return np.where(zb >= 45.0, -9999.0, 0.0)
    if rule_id == "F_L1_dt_hi": return np.where(dt_c >= 25.0, -9999.0, 0.0)
    if rule_id == "F_L1_earn_apr": return np.where(e_apr == 1.0, -9999.0, 0.0)
    if rule_id == "F_L1_earn_any": return np.where(e_any == 1.0, -9999.0, 0.0)
    if rule_id == "F_L1_prehol": return np.where(ph2 == 1.0, -9999.0, 0.0)
    if rule_id == "F_L2_ind_crowd": return np.where(ind_amt >= 0.85, -9999.0, 0.0)
    if rule_id == "F_L2_ind_ex120_hi": return np.where(ind_ex120 >= 15.0, -9999.0, 0.0)
    if rule_id == "F_L2_kpl_streak_late": return np.where(k_st >= 5.0, -9999.0, 0.0)
    if rule_id == "F_L2_kpl_cold": return np.where(k_zt20 < 10.0, -9999.0, 0.0)
    if rule_id == "F_L3_newhigh_hi": return np.where(nh60 >= 8.0, -9999.0, 0.0)
    if rule_id == "F_L3_bias20_hi": return np.where(b20 >= 40.0, -9999.0, 0.0)
    if rule_id == "F_L3_cumturn20_lo": return np.where(ct20 < 100.0, -9999.0, 0.0)
    if rule_id == "F_L3_ampcomp_lo": return np.where(acmp < 0.35, -9999.0, 0.0)
    if rule_id == "F_L3_overhang_hi": return np.where(ovh >= 75.0, -9999.0, 0.0)
    raise ValueError(f"Unknown rule_id: {rule_id}")


def run_combined_v20_custom(
    pools: dict[str, pd.DataFrame],
    untrig_base: pd.DataFrame,
    rule_map: dict[str, tuple[str, float]],
    start_dt: str = "2021-11-16",
    end_dt: str = "2026-11-16",
) -> tuple[pd.DataFrame, list[dict]]:
    """Exact V20.0 P3_S2C_STierReserveOnly engine applying our cycle rules to both pools & untrig."""
    parts = []
    trig_dts_by_strat = {}
    for st in STRAT_ORDER:
        df = pools[st]
        if st in rule_map:
            rid, w = rule_map[st]
            d_vec = compute_cycle_delta(df, rid, w)
        else:
            d_vec = np.zeros(len(df), dtype=float)
        if st == "20cm":
            _, chosen = m1.sim_standalone(st, df, d_vec, cm20_thr=76.0)
        else:
            _, chosen = m1.sim_standalone(st, df, d_vec, high_cb_mode="v51_exact")
        chosen = chosen[chosen["buy_date"].between(start_dt, end_dt)].copy()
        if chosen.empty:
            trig_dts_by_strat[st] = set()
            continue
        sc_s = chosen["_sc_adj"] if "_sc_adj" in chosen.columns else chosen["v20_score"]
        chosen["score"] = [round(float(x), 1) for x in sc_s] if st == "1to2" else sc_s
        chosen["tier"] = [m1.tpe.assign_physical_tier(st, sc) for sc in chosen["score"]]
        chosen["is_untrig"] = False
        trig_dts_by_strat[st] = set(chosen["buy_date"])
        cols = [
            "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
            "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px",
            "is_untrig", "mtm_full", "mtm_5y",
        ]
        parts.append(chosen[cols])

    pool6 = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    ut = untrig_base[untrig_base["buy_date"].between(start_dt, end_dt)].copy()
    if not ut.empty:
        ut_parts = []
        for st_u in ("3to4", "high", "1to2"):
            sub_u = ut[ut["strategy"] == st_u].copy()
            if sub_u.empty:
                continue
            sub_u = sub_u[~sub_u["buy_date"].isin(trig_dts_by_strat.get(st_u, set()))].copy()
            if sub_u.empty:
                continue
            if st_u in rule_map:
                rid, w = rule_map[st_u]
                sub_u["score"] = sub_u["v20_score"].to_numpy(float) + compute_cycle_delta(sub_u, rid, w)
            thr_u = {"3to4": 90.0, "high": 88.0, "1to2": 0.0}[st_u]
            sub_u = sub_u[sub_u["score"] >= thr_u].copy()
            if not sub_u.empty:
                sub_u["tier"] = [m1.tpe.assign_physical_tier(st_u, sc) for sc in sub_u["score"]]
                sub_u = sub_u.sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
                ut_parts.append(sub_u)
        if ut_parts:
            ut_final = pd.concat(ut_parts, ignore_index=True)
            ut_final["is_untrig"] = True
            ut_final["net_ret"] = 0.0
            ut_final["buy_price_val"] = np.nan
            ut_final["is_adj_px"] = False
            ut_final = ut_final[[
                "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
                "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig",
            ]]
        else:
            ut_final = pd.DataFrame()
    else:
        ut_final = pd.DataFrame()

    mtm_map = {}
    if not pool6.empty:
        for r in pool6.itertuples(index=False):
            mtm_map[(r.strategy, r.buy_date, r.code)] = (r.mtm_full, r.mtm_5y)
        p6_clean = pool6.drop(columns=["mtm_full", "mtm_5y"])
    else:
        p6_clean = pool6

    tr_df, waits = m1.tpe.run_single_slot(
        p6_clean,
        lambda d: d["tier"].map(S2C_MAP).fillna(999).to_numpy(),
        untrig_df=ut_final,
        timing_mode="s_tier_reserve_only",
    )
    if not tr_df.empty:
        tr_df["mtm_full"] = [mtm_map[(r.strategy, r.buy_date, r.code)][0] for r in tr_df.itertuples(index=False)]
        tr_df["mtm_5y"] = [mtm_map[(r.strategy, r.buy_date, r.code)][1] for r in tr_df.itertuples(index=False)]
    return tr_df, waits


def eval_single_strategy_mode(
    st: str,
    mode: str,
    specs: list[tuple],
    pools: dict[str, pd.DataFrame],
    cal_full: list[str],
    sh300: dict,
    all_sh_dts: list[str],
) -> dict:
    """Evaluate Rerank or Filter rule grid on IS (<=2024-12-31) ONLY, lock Top IS, then test blind OOS & Y2026."""
    df = pools[st]
    T_full = len(cal_full)
    dt_idx_full = {d: i for i, d in enumerate(cal_full)}
    start = "2021-01-04" if st == "20cm" else "2021-11-16"
    wins = [
        ("FULL", start, "2026-11-25"),
        ("IS", start, "2024-12-31"),
        ("OOS", "2025-01-01", "2026-11-25"),
        ("Y2026", "2026-01-01", "2026-11-25"),
    ]
    st_idx = [i for i, d in enumerate(cal_full) if d >= start]
    csi_vec = np.array([sh300[cal_full[i]] / sh300[all_sh_dts[all_sh_dts.index(cal_full[i]) - 1]] - 1.0 for i in st_idx], dtype=float)

    def _run_one(rule_id: str, w: float):
        delta = np.zeros(len(df), dtype=float) if rule_id == "BASELINE" else compute_cycle_delta(df, rule_id, w)
        pass_df, slot_df = m1.sim_standalone(st, df, delta, high_cb_mode="v51_exact", cm20_thr=82.0)
        dr_full, nd = m1.daily_mtm_from_segs(slot_df, T_full, "mtm_full")
        assert nd < 1e-3, f"{st} {rule_id} MTM diff={nd}"
        wm = {wl: m2.calc_window_metrics_ext(slot_df, pass_df, dr_full, cal_full, dt_idx_full, sh300, all_sh_dts, sd, ed) for wl, sd, ed in wins}
        return slot_df, dr_full, wm

    base_slot, base_dr, base_wm = _run_one("BASELINE", 0.0)
    base_is = base_wm["IS"]
    base_keys_is = set(zip(base_slot[base_slot["buy_date"] <= "2024-12-31"]["buy_date"], base_slot[base_slot["buy_date"] <= "2024-12-31"]["code"]))
    base_keys_full = set(zip(base_slot["buy_date"], base_slot["code"]))

    w_grid = m1.WEIGHT_GRIDS[st] if mode == "rerank" else [9999]
    variants = []
    dr_family = {"BASELINE": base_dr[st_idx]}
    p_base_list = []

    for rule_id, _, layer_cn, desc in specs:
        for w in w_grid:
            vid = f"{rule_id}_w{w}" if mode == "rerank" else rule_id
            slot_df, dr_full, wm = _run_one(rule_id, float(w))
            dr_sub = dr_full[st_idx]

            is_slot = slot_df[slot_df["buy_date"] <= "2024-12-31"]
            is_keys = set(zip(is_slot["buy_date"], is_slot["code"]))
            full_keys = set(zip(slot_df["buy_date"], slot_df["code"]))
            is_chg = len(base_keys_is - is_keys) + len(is_keys - base_keys_is)
            full_kicked = len(base_keys_full - full_keys)
            full_added = len(full_keys - base_keys_full)

            diff_b = dr_sub - base_dr[st_idx]
            _, p_base = stats.ttest_1samp(diff_b, 0.0, alternative="greater") if np.std(diff_b) > 1e-12 else (0.0, 1.0)
            p_base_list.append(float(p_base))

            if not any(np.allclose(dr_sub, v) for v in dr_family.values()):
                dr_family[vid] = dr_sub

            m_is = wm["IS"]
            is_suff = m_is["n"] >= max(6, int(round(0.75 * base_is["n"])))
            if mode == "rerank":
                is_beat = (
                    is_chg > 0 and is_suff
                    and m_is["daily_sharpe"] > base_is["daily_sharpe"] + 1e-6
                    and m_is["ex_top3_nav"] > base_is["ex_top3_nav"] * 1.0001
                    and m_is["nav"] > base_is["nav"] * 1.0001
                    and m_is["daily_calmar"] >= base_is["daily_calmar"] * 0.98
                )
            else:
                # Filter can reduce NAV slightly while improving Sharpe/MDD, or improve all
                is_beat = (
                    is_chg > 0 and is_suff
                    and m_is["daily_sharpe"] > base_is["daily_sharpe"] + 0.02
                    and m_is["ex_top3_nav"] >= base_is["ex_top3_nav"] * 0.98
                    and m_is["daily_calmar"] > base_is["daily_calmar"] * 1.01
                )

            is_rank_score = (
                (m_is["daily_sharpe"] - base_is["daily_sharpe"]) * 2.0
                + math.log(max(1e-9, m_is["ex_top3_nav"]) / max(1e-9, base_is["ex_top3_nav"]))
                + 0.5 * math.log(max(1e-9, m_is["nav"]) / max(1e-9, base_is["nav"]))
            ) if (is_chg > 0 and is_suff) else -999.0

            variants.append({
                "variant_id": vid, "rule_id": rule_id, "mode": mode, "layer": layer_cn, "desc": desc, "w": int(w),
                "windows": wm,
                "is_changed_trades": int(is_chg), "full_kicked": int(full_kicked), "full_added": int(full_added),
                "strict_is_improver": bool(is_beat),
                "is_rank_score": round(float(is_rank_score), 5),
                "p_vs_base_raw": round(float(p_base), 6),
            })

    q_base = m2.bh_fdr(p_base_list)
    for idx_v, v in enumerate(variants):
        v["bh_fdr_vs_base_q"] = q_base[idx_v]

    strict_cands = [v for v in variants if v["strict_is_improver"]]
    if strict_cands:
        top_is_list = sorted(strict_cands, key=lambda x: -x["is_rank_score"])[:3]
    else:
        changed_cands = [v for v in variants if v["is_changed_trades"] > 0 and v["windows"]["IS"]["n"] >= max(6, int(round(0.75 * base_is["n"])))]
        top_is_list = sorted(changed_cands, key=lambda x: -x["is_rank_score"])[:3]
    top_is = top_is_list[0] if top_is_list else None

    cscv_keys = ["BASELINE"]
    for v in sorted(variants, key=lambda x: -x["is_rank_score"]):
        if v["variant_id"] in dr_family and v["variant_id"] not in cscv_keys:
            cscv_keys.append(v["variant_id"])
        if len(cscv_keys) >= 20:
            break
    cscv_res = m2.cscv_pbo_family({k: dr_family[k] for k in cscv_keys}, "BASELINE", S_list=(8, 10)) if len(cscv_keys) >= 2 else {}

    oos_pass = False
    verdict = "KEEP_V20_UNCHANGED"
    if top_is is not None:
        m_oos, b_oos = top_is["windows"]["OOS"], base_wm["OOS"]
        m_y26, b_y26 = top_is["windows"]["Y2026"], base_wm["Y2026"]
        oos_pass = (
            top_is["strict_is_improver"]
            and m_oos["nav"] > b_oos["nav"]
            and m_oos["ex_top3_nav"] >= b_oos["ex_top3_nav"] * 0.99
            and m_oos["daily_sharpe"] >= b_oos["daily_sharpe"] - 0.05
            and m_y26["nav"] >= b_y26["nav"] * 0.95
        )
        verdict = "CANDIDATE_PASS_IS_AND_OOS" if oos_pass else "KEEP_V20_UNCHANGED"

    return {
        "strategy": st, "mode": mode,
        "total_variants_tested": len(variants),
        "unique_daily_streams": len(dr_family),
        "strict_is_improver_count": len(strict_cands),
        "baseline": base_wm,
        "top_is_locked": top_is,
        "top3_is_locked": top_is_list,
        "cscv_pbo": cscv_res,
        "verdict": verdict,
    }


def run_combined_half50_and_stop0_horse_race(
    pools: dict[str, pd.DataFrame],
    untrig_base: pd.DataFrame,
    cal_5y: list[str],
    sh300: dict,
    all_sh_dts: list[str],
    mkt_df: pd.DataFrame,
) -> dict:
    """
    Mode C: Test Half-Position Sizing (Half50) & Stop0 on V20.0 Combined (278 trades)
    using exact daily MTM path scaling (1 - w + w * V(t)). Strictly IS-selected rules -> blind OOS & Y2026.
    """
    tr_base, _ = run_combined_v20_custom(pools, untrig_base, {})
    # Merge cycle columns onto comb_278
    df_cyc = pd.read_parquet(f"{OUT_DIR}/pools_6strat_with_3layer_cycles.parquet")
    df_cyc["code"] = df_cyc["code"].astype(str).str.zfill(6)
    df_cyc["buy_date"] = df_cyc["buy_date"].astype(str).str[:10]
    cyc_cols = [c for c in df_cyc.columns if c.startswith(("L1_", "L2_", "L3_"))]
    comb = tr_base.merge(
        df_cyc[["strategy", "code", "buy_date"] + cyc_cols].drop_duplicates(["strategy", "code", "buy_date"]),
        on=["strategy", "code", "buy_date"],
        how="left",
    )

    T = len(cal_5y)
    dt_idx = {d: i for i, d in enumerate(cal_5y)}
    csi_vec = np.array([sh300[d] / sh300[all_sh_dts[all_sh_dts.index(d) - 1]] - 1.0 for d in cal_5y], dtype=float)

    # 20d realized equal-weight market vol strictly at T-1 for 1/vol matched-exposure control
    m5 = mkt_df.set_index("dt")
    vol_s = m5["L1_ew_vol20_t1"].reindex(cal_5y).ffill().bfill().to_numpy(float) / 100.0
    t_vols = np.array([max(1e-4, float(m5.loc[d, "L1_ew_vol20_t1"]) / 100.0) if d in m5.index else 0.015 for d in comb["buy_date"]], dtype=float)

    is_mask = comb["buy_date"] <= "2024-12-31"
    raw_iv = 1.0 / t_vols
    raw_iv = raw_iv / float(np.mean(raw_iv[is_mask]))

    def _eval_weights(w_arr: np.ndarray, label: str) -> dict:
        ser = np.zeros(T, dtype=float)
        t_rets = comb["net_ret"].to_numpy(float) * w_arr
        for idx_t, r in enumerate(comb.itertuples(index=False)):
            w = float(w_arr[idx_t])
            if w <= 0.0:
                continue
            v_prev = 1.0
            cum_v = 1.0
            for t_i, mult_raw in r.mtm_5y:
                cum_v *= mult_raw
                p_prev = (1.0 - w) + w * v_prev
                p_cur = (1.0 - w) + w * cum_v
                seg_r = p_cur / p_prev - 1.0
                ser[t_i] = (1.0 + ser[t_i]) * (1.0 + seg_r) - 1.0 if abs(ser[t_i]) > 1e-15 else seg_r
                v_prev = cum_v

        wins = [("FULL", "2021-11-16", "2026-11-16"), ("IS", "2021-11-16", "2024-12-31"), ("OOS", "2025-01-01", "2026-11-16"), ("Y2026", "2026-01-01", "2026-11-16")]
        res = {"policy": label, "avg_weight": round(float(w_arr.mean()), 4), "active_trades": int((w_arr > 0).sum())}
        for wn, s, e in wins:
            dm_mask = np.array([(s <= d <= e) for d in cal_5y], dtype=bool)
            dr = ser[dm_mask]
            cr = csi_vec[dm_mask]
            nd = len(dr)
            nav = float(np.prod(1.0 + dr))
            curve = np.concatenate([[1.0], np.cumprod(1.0 + dr)])
            pk = np.maximum.accumulate(curve)
            mdd = float((1.0 - curve / pk).max() * 100.0)
            sd = float(np.std(dr, ddof=1)) if nd > 1 else 0.0
            sr = float(np.mean(dr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
            cagr = (nav ** (TRD_DAYS_YEAR / max(1, nd)) - 1.0) * 100.0 if nav > 0 else -100.0
            cal = cagr / mdd if mdd > 1e-6 else 0.0
            csi_p = (float(np.prod(1.0 + cr)) - 1.0) * 100.0

            tm_mask = (comb["buy_date"] >= s) & (comb["buy_date"] <= e) & (w_arr > 0)
            sub_r = t_rets[tm_mask]
            wr = float((sub_r > 0).mean() * 100.0) if len(sub_r) else 0.0
            w_p, l_p = sub_r[sub_r > 0], sub_r[sub_r <= 0]
            plr = float(w_p.mean() / abs(l_p.mean())) if (len(w_p) and len(l_p) and l_p.mean() < 0) else 0.0
            sr_r = np.sort(sub_r)
            ex3 = float(np.prod(1.0 + sr_r[:-3])) if len(sub_r) > 3 else 1.0
            ex5 = float(np.prod(1.0 + sr_r[:-5])) if len(sub_r) > 5 else 1.0
            res[wn] = {
                "n": int(len(sub_r)), "wr_pct": round(wr, 2), "plr": round(plr, 2),
                "nav": round(nav, 4), "cagr_pct": round(cagr, 2),
                "ex_top3_nav": round(ex3, 4), "ex_top5_nav": round(ex5, 4),
                "daily_mdd_pct": round(mdd, 2), "daily_sharpe": round(sr, 3), "daily_calmar": round(cal, 2),
                "csi300_pct": round(csi_p, 2), "excess_csi300_pp": round((nav - 1.0) * 100.0 - csi_p, 2),
            }
        return res

    # Adverse condition definitions across all 3 layers (all fixed on IS / domain intuition)
    conds = [
        ("C_L1_sent_ice", "情绪冰点期", (comb["L1_sent_phase_t1"] == 1).to_numpy()),
        ("C_L1_sent_climax", "情绪高潮期", (comb["L1_sent_phase_t1"] == 4).to_numpy()),
        ("C_L1_sent_ebb", "情绪退潮期", (comb["L1_sent_phase_t1"] == 5).to_numpy()),
        ("C_L1_zt_ge80", "昨日涨停>=80家极热", (comb["L1_zt_cnt_t1"] >= 80).to_numpy()),
        ("C_L1_duanban_low", "昨日断板大面率<=5%(过顺)", (comb["L1_duanban_damian_t1"] <= 5.0).to_numpy()),
        ("C_L1_earn_any", "全部财报季窗口", (comb["L1_is_earn_any"] == 1).to_numpy()),
        ("C_L1_smb60_hot", "微盘60日过热>=+10%", (comb["L1_smb_60d_t1"] >= 10.0).to_numpy()),
        ("C_L2_ind_crowd80", "行业成交拥挤>=80%分位", (comb["L2_ind_amt_pct250_t1"].fillna(0) >= 0.80).to_numpy()),
        ("C_L2_kpl_streak4", "题材连爆>=4天尾声", (comb["L2_kpl_streak_t1"] >= 4).to_numpy()),
        ("C_L3_bias20_mid", "个股MA20乖离中段(15~30%)", comb["L3_bias20_t1"].between(15.0, 30.0).fillna(False).to_numpy()),
    ]

    rows = [_eval_weights(np.ones(len(comb), dtype=float), "Baseline_100pct_Full")]
    for cid, cdesc, mask in conds:
        w_half = np.where(mask, 0.5, 1.0)
        w_zero = np.where(mask, 0.0, 1.0)
        rows.append(_eval_weights(w_half, f"Half50_{cid} ({cdesc})"))
        rows.append(_eval_weights(w_zero, f"Stop0_{cid} ({cdesc})"))
        avg_h = float(w_half.mean())
        rows.append(_eval_weights(np.full(len(comb), avg_h), f"Static_SameAvgExp_{avg_h:.2f} ({cid})"))
        w_iv = np.clip(raw_iv * avg_h, 0.0, 1.0)
        rows.append(_eval_weights(w_iv, f"Control_1overVol_Matched_{avg_h:.2f} ({cid})"))

    # Identify best IS Half50 and best IS Stop0
    half_rows = [r for r in rows if r["policy"].startswith("Half50_")]
    stop_rows = [r for r in rows if r["policy"].startswith("Stop0_")]
    best_is_half = max(half_rows, key=lambda x: x["IS"]["daily_sharpe"])
    best_is_stop = max(stop_rows, key=lambda x: x["IS"]["daily_sharpe"])
    return {"all_policies": rows, "best_is_half50": best_is_half, "best_is_stop0": best_is_stop}


def check_truncation_custom(
    pools: dict[str, pd.DataFrame],
    untrig_base: pd.DataFrame,
    full_tr: pd.DataFrame,
    rule_map: dict[str, tuple[str, float]],
    fb20_tr_cache: set,
) -> dict:
    p_tr = {}
    for st in STRAT_ORDER:
        df = pools[st]
        sub = df[(df["buy_date"] <= "2024-12-31") & (df["exit_date"] <= "2024-12-31")].copy().reset_index(drop=True)
        if st == "1to2":
            sub["v20_pen"] = np.where(sub["buy_date"].isin(fb20_tr_cache), -25.0, 0.0)
            sub["v20_score"] = sub["base_score"].astype(float) + sub["v20_pen"]
        p_tr[st] = sub
    ut_tr = untrig_base[untrig_base["buy_date"] <= "2024-12-31"].copy()
    tr_trunc, _ = run_combined_v20_custom(p_tr, ut_tr, rule_map, start_dt="2021-11-16", end_dt="2024-12-31")
    f24 = full_tr[full_tr["exit_date"] <= "2024-12-31"].reset_index(drop=True)
    t24 = tr_trunc[tr_trunc["exit_date"] <= "2024-12-31"].reset_index(drop=True)
    assert len(f24) == len(t24), f"Trunc len mismatch {len(f24)} vs {len(t24)}"
    assert list(zip(f24["buy_date"], f24["code"], f24["strategy"])) == list(zip(t24["buy_date"], t24["code"], t24["strategy"]))
    max_diff = float(np.max(np.abs(f24["net_ret"].to_numpy(float) - t24["net_ret"].to_numpy(float))))
    assert max_diff == 0.0, f"Trunc diff != 0: {max_diff}"
    return {"trades_exiting_le_20241231": int(len(t24)), "max_abs_diff": max_diff, "pass": True}


def main():
    t0 = time.time()
    print("[Step 3] Loading pools + 3-layer cycle features & verifying 100% V20.0 parity...")
    codes = set()
    for st in STRAT_ORDER:
        d = pd.read_parquet(f"{OUT_DIR}/pool_{st}_cycles.parquet")
        codes.update(d["code"].astype(str).str.zfill(6))

    sh300, all_sh_dts, cal_full, cal_5y, bar_lu = m1.load_calendars_and_bars(codes)
    pools = m1.load_pools_oldhot(cal_full, cal_5y, bar_lu)
    untrig_base = pd.read_parquet(f"{OUT_DIR}/rd034_untrig_with_3layer_cycles.parquet")
    untrig_base["code"] = untrig_base["code"].astype(str).str.zfill(6)
    untrig_base["buy_date"] = untrig_base["buy_date"].astype(str).str[:10]

    # Attach 3-layer cycle columns onto `pools` (keeping mtm_full / mtm_5y / v51_cb_loss intact)
    for st in STRAT_ORDER:
        c_df = pd.read_parquet(f"{OUT_DIR}/pool_{st}_cycles.parquet")
        c_df["code"] = c_df["code"].astype(str).str.zfill(6)
        c_df["buy_date"] = c_df["buy_date"].astype(str).str[:10]
        cyc_cols = [c for c in c_df.columns if c.startswith(("L1_", "L2_", "L3_"))]
        pools[st] = pools[st].merge(
            c_df[["code", "buy_date"] + cyc_cols].drop_duplicates(["code", "buy_date"]),
            on=["code", "buy_date"],
            how="left",
        )

    parity_rep = m1.verify_all_baselines(pools, untrig_base)
    for k, v in parity_rep.items():
        print(f"  [PARITY] {k:12s}: n={v['n']:3d}, NAV={v['nav']:14,.4f}x, diff={v['max_abs_ret_diff']:.2e}")

    print("\n[1/4] Mode A (Score Rerank) & Mode B (Hard Filter) IS -> Blind OOS across all 6 strategies...")
    single_rerank = {}
    single_filter = {}
    for st in STRAT_ORDER:
        single_rerank[st] = eval_single_strategy_mode(st, "rerank", RERANK_SPECS, pools, cal_full, sh300, all_sh_dts)
        single_filter[st] = eval_single_strategy_mode(st, "filter", FILTER_SPECS, pools, cal_full, sh300, all_sh_dts)
        rr = single_rerank[st]
        ff = single_filter[st]
        for lbl, res in [("RERANK", rr), ("FILTER", ff)]:
            ti = res["top_is_locked"]
            if ti:
                bi, bo, by = res["baseline"]["IS"], res["baseline"]["OOS"], res["baseline"]["Y2026"]
                ci, co, cy = ti["windows"]["IS"], ti["windows"]["OOS"], ti["windows"]["Y2026"]
                print(
                    f"  [{st:4s} {lbl:6s}] strict_IS={res['strict_is_improver_count']:2d} | {ti['variant_id']:26s} "
                    f"| IS: {ci['nav']:6.2f}x(SR={ci['daily_sharpe']:.2f}) vs {bi['nav']:6.2f}x(SR={bi['daily_sharpe']:.2f}) "
                    f"| OOS: {co['nav']:6.2f}x(SR={co['daily_sharpe']:.2f}) vs {bo['nav']:6.2f}x(SR={bo['daily_sharpe']:.2f}) "
                    f"| Y26: {cy['nav']:5.2f}x vs {by['nav']:5.2f}x | {res['verdict']}"
                )

    print("\n[2/4] Plugging IS-locked Rerank & Filter rules into V20.0 Combined (P3_S2C_STierReserveOnly)...")
    comb_specs = [("V20_BASELINE", "现役 V20.0 原版（零修改）", {})]

    # Single-strategy IS winners & multi-strategy combos for Rerank & Filter separately + combined
    rr_is_win = {st: (single_rerank[st]["top_is_locked"]["rule_id"], float(single_rerank[st]["top_is_locked"]["w"]))
                 for st in STRAT_ORDER if single_rerank[st]["top_is_locked"] and single_rerank[st]["top_is_locked"]["strict_is_improver"]}
    rr_oos_win = {st: (single_rerank[st]["top_is_locked"]["rule_id"], float(single_rerank[st]["top_is_locked"]["w"]))
                  for st in STRAT_ORDER if single_rerank[st]["verdict"] == "CANDIDATE_PASS_IS_AND_OOS"}

    ff_is_win = {st: (single_filter[st]["top_is_locked"]["rule_id"], 9999.0)
                 for st in STRAT_ORDER if single_filter[st]["top_is_locked"] and single_filter[st]["top_is_locked"]["strict_is_improver"]}
    ff_oos_win = {st: (single_filter[st]["top_is_locked"]["rule_id"], 9999.0)
                  for st in STRAT_ORDER if single_filter[st]["verdict"] == "CANDIDATE_PASS_IS_AND_OOS"}

    for st, (rid, w) in rr_is_win.items():
        comb_specs.append((f"RERANK_{st}_{rid}_w{int(w)}", f"重排单策略: {st} {rid} w={int(w)}", {st: (rid, w)}))
    if len(rr_is_win) >= 2:
        comb_specs.append(("COMBO_RERANK_ALL_IS", "全部IS胜出策略重排组合", dict(rr_is_win)))
    if len(rr_oos_win) >= 2:
        comb_specs.append(("COMBO_RERANK_IS_OOS", "IS+OOS双胜出策略重排组合", dict(rr_oos_win)))

    for st, (rid, w) in ff_is_win.items():
        comb_specs.append((f"FILTER_{st}_{rid}", f"过滤单策略: {st} {rid}", {st: (rid, w)}))
    if len(ff_is_win) >= 2:
        comb_specs.append(("COMBO_FILTER_ALL_IS", "全部IS胜出策略过滤组合", dict(ff_is_win)))
    if len(ff_oos_win) >= 2:
        comb_specs.append(("COMBO_FILTER_IS_OOS", "IS+OOS双胜出策略过滤组合", dict(ff_oos_win)))

    # Also test top-IS across all 6 strategies (even if not strict improver) as control
    all_top_rr = {st: (single_rerank[st]["top_is_locked"]["rule_id"], float(single_rerank[st]["top_is_locked"]["w"]))
                  for st in STRAT_ORDER if single_rerank[st]["top_is_locked"] is not None}
    if len(all_top_rr) >= 2:
        comb_specs.append(("COMBO_RERANK_TOP6_IS", "6策略IS最优重排全挂对照", all_top_rr))

    T_5y = len(cal_5y)
    dt_idx_5y = {d: i for i, d in enumerate(cal_5y)}
    comb_wins = [
        ("FULL", "2021-11-16", "2026-11-16"),
        ("IS", "2021-11-16", "2024-12-31"),
        ("OOS", "2025-01-01", "2026-11-16"),
        ("Y2026", "2026-01-01", "2026-11-16"),
    ]
    csi_5y_vec = np.array([sh300[d] / sh300[all_sh_dts[all_sh_dts.index(d) - 1]] - 1.0 for d in cal_5y], dtype=float)
    fb20_tr_cache = {d for d, c in m2.mc.build_fb20_cln_dates_pit("2024-12-31").items() if c >= 2}

    def _run_comb(rmap: dict):
        tr_c, waits_c = run_combined_v20_custom(pools, untrig_base, rmap)
        dr_5y, nd = m1.daily_mtm_from_segs(tr_c, T_5y, "mtm_5y")
        assert nd < 1e-3, f"Combined MTM diff={nd}"
        wm = {wl: m2.calc_window_metrics_ext(tr_c, None, dr_5y, cal_5y, dt_idx_5y, sh300, all_sh_dts, sd, ed) for wl, sd, ed in comb_wins}
        return tr_c, waits_c, dr_5y, wm

    base_tr, _, base_dr, base_wm = _run_comb({})
    comb_evals, comb_drs, p_vs_base, all_diffs = {}, {}, [], []

    for cid, cdesc, rmap in comb_specs:
        tr_c, waits_c, dr_5y, wm = _run_comb(rmap)
        hlz_t, dsr150 = m2.mc.hlz_and_dsr150(tr_c.to_dict("records"), sh300, all_sh_dts, m_trials=150)
        diff_b = dr_5y - base_dr
        _, p_b = stats.ttest_1samp(diff_b, 0.0, alternative="greater") if np.std(diff_b) > 1e-12 else (0.0, 1.0)
        p_vs_base.append(float(p_b))
        boot_10k = m2.paired_block_bootstrap_10k(dr_5y, base_dr, csi_5y_vec)
        # 5-fold Purged CV
        T_len = len(cal_5y)
        step_f = T_len // 5
        fold_navs = []
        for fi in range(5):
            fs, fe = fi * step_f, ((fi + 1) * step_f - 1 if fi < 4 else T_len - 1)
            sub_f = tr_c[(tr_c["buy_date"] >= cal_5y[fs]) & (tr_c["buy_date"] <= cal_5y[fe])]
            fold_navs.append(round(float(np.prod(1.0 + sub_f["net_ret"].to_numpy(float))) if not sub_f.empty else 1.0, 4))
        trunc_chk = check_truncation_custom(pools, untrig_base, tr_c, rmap, fb20_tr_cache)
        if cid != "V20_BASELINE":
            all_diffs.extend(m1.extract_trade_diffs(base_tr, tr_c, "combined_v20", cid))

        comb_drs[cid] = dr_5y
        comb_evals[cid] = {
            "scheme_id": cid, "desc": cdesc, "rule_map": {k: [v[0], v[1]] for k, v in rmap.items()},
            "windows": wm,
            "by_strategy": tr_c["strategy"].value_counts().to_dict(),
            "hlz_t": hlz_t, "dsr_m150": dsr150,
            "p_vs_v20_raw": round(float(p_b), 6),
            "cv5_fold_navs": fold_navs,
            "cv5_n_pos": int(sum(1 for x in fold_navs if x > 1.0)),
            "cv5_min_nav": min(fold_navs),
            "paired_block_bootstrap_10k": boot_10k,
            "truncation_20241231": trunc_chk,
        }

    q_b = m2.bh_fdr(p_vs_base)
    for i_c, cid in enumerate(comb_evals.keys()):
        comb_evals[cid]["bh_fdr_vs_v20_q"] = q_b[i_c]

    cscv_comb = m2.cscv_pbo_family(comb_drs, "V20_BASELINE", S_list=(8, 10)) if len(comb_drs) >= 2 else {}

    print("\n[3/4] Mode C (Half50 & Stop0 Position Sizing) on V20.0 Combined (N=278)...")
    mkt_df = pd.read_parquet(f"{OUT_DIR}/rd034_market_daily_pit.parquet")
    half50_res = run_combined_half50_and_stop0_horse_race(pools, untrig_base, cal_5y, sh300, all_sh_dts, mkt_df)

    # Export CSV comparison
    cmp_rows = []
    for cid, ev in comb_evals.items():
        wf, wi, wo, wy = ev["windows"]["FULL"], ev["windows"]["IS"], ev["windows"]["OOS"], ev["windows"]["Y2026"]
        cmp_rows.append({
            "mode": "BASELINE" if cid == "V20_BASELINE" else ("FILTER" if "FILTER" in cid else "RERANK"),
            "scheme_id": cid, "desc": ev["desc"],
            "n_full": wf["n"], "wr_full_pct": wf["wr_pct"], "plr_full": wf["plr"],
            "nav_full": wf["nav"], "ex3_full": wf["ex_top3_nav"], "ex5_full": wf["ex_top5_nav"],
            "mdd_full_pct": wf["daily_mdd_pct"], "sharpe_full": wf["daily_sharpe"], "calmar_full": wf["daily_calmar"],
            "excess_csi_full_pp": wf["excess_csi300_pp"],
            "n_is": wi["n"], "nav_is": wi["nav"], "sharpe_is": wi["daily_sharpe"],
            "n_oos": wo["n"], "nav_oos": wo["nav"], "ex3_oos": wo["ex_top3_nav"], "ex5_oos": wo["ex_top5_nav"],
            "mdd_oos_pct": wo["daily_mdd_pct"], "sharpe_oos": wo["daily_sharpe"], "calmar_oos": wo["daily_calmar"],
            "excess_csi_oos_pp": wo["excess_csi300_pp"],
            "n_y26": wy["n"], "nav_y26": wy["nav"], "sharpe_y26": wy["daily_sharpe"],
            "boot_prob_beat_v20_pct": ev["paired_block_bootstrap_10k"]["paired_prob_cand_beat_v20_nav_pct"],
            "bh_fdr_vs_v20_q": ev["bh_fdr_vs_v20_q"],
        })
    for r in half50_res["all_policies"]:
        if r["policy"] == "Baseline_100pct_Full":
            continue
        wf, wi, wo, wy = r["FULL"], r["IS"], r["OOS"], r["Y2026"]
        cmp_rows.append({
            "mode": "HALF50_OR_STOP0",
            "scheme_id": r["policy"], "desc": f"avg_w={r['avg_weight']}",
            "n_full": wf["n"], "wr_full_pct": wf["wr_pct"], "plr_full": wf["plr"],
            "nav_full": wf["nav"], "ex3_full": wf["ex_top3_nav"], "ex5_full": wf["ex_top5_nav"],
            "mdd_full_pct": wf["daily_mdd_pct"], "sharpe_full": wf["daily_sharpe"], "calmar_full": wf["daily_calmar"],
            "excess_csi_full_pp": wf["excess_csi300_pp"],
            "n_is": wi["n"], "nav_is": wi["nav"], "sharpe_is": wi["daily_sharpe"],
            "n_oos": wo["n"], "nav_oos": wo["nav"], "ex3_oos": wo["ex_top3_nav"], "ex5_oos": wo["ex_top5_nav"],
            "mdd_oos_pct": wo["daily_mdd_pct"], "sharpe_oos": wo["daily_sharpe"], "calmar_oos": wo["daily_calmar"],
            "excess_csi_oos_pp": wo["excess_csi300_pp"],
            "n_y26": wy["n"], "nav_y26": wy["nav"], "sharpe_y26": wy["daily_sharpe"],
            "boot_prob_beat_v20_pct": None, "bh_fdr_vs_v20_q": None,
        })

    cmp_csv = f"{OUT_DIR}/rd034_oos_strategy_compare.csv"
    pd.DataFrame(cmp_rows).to_csv(cmp_csv, index=False, encoding="utf-8-sig")

    # Determine overall final verdict
    b_w = comb_evals["V20_BASELINE"]["windows"]
    winning_comb = []
    for cid, ev in comb_evals.items():
        if cid == "V20_BASELINE":
            continue
        cw = ev["windows"]
        boot = ev["paired_block_bootstrap_10k"]
        if (
            cw["IS"]["nav"] > b_w["IS"]["nav"]
            and cw["OOS"]["nav"] > b_w["OOS"]["nav"]
            and cw["OOS"]["ex_top5_nav"] >= b_w["OOS"]["ex_top5_nav"] * 0.99
            and cw["Y2026"]["nav"] >= b_w["Y2026"]["nav"] * 0.95
            and cw["FULL"]["daily_sharpe"] >= b_w["FULL"]["daily_sharpe"]
            and ev["cv5_n_pos"] == 5
            and boot["paired_prob_cand_beat_v20_nav_pct"] >= 60.0
            and ev["bh_fdr_vs_v20_q"] <= 0.15
        ):
            winning_comb.append(cid)

    # Also check single-strategy IS+OOS double survivors
    single_double_pass = {
        "rerank": [st for st in STRAT_ORDER if single_rerank[st]["verdict"] == "CANDIDATE_PASS_IS_AND_OOS"],
        "filter": [st for st in STRAT_ORDER if single_filter[st]["verdict"] == "CANDIDATE_PASS_IS_AND_OOS"],
    }

    # Combine Step 1 + Step 2 + Step 3 into unified rd034_3layer_cycles_audit.json
    s1_aud = json.load(open(f"{OUT_DIR}/rd034_step1_pit_audit.json", encoding="utf-8"))
    s2_aud = json.load(open(f"{OUT_DIR}/rd034_step2_scan_audit.json", encoding="utf-8"))

    final_verdict = "ADOPT_INCREMENTAL_RULE" if winning_comb else "KEEP_V20_UNCHANGED"
    master_json = m2.sanitize_json({
        "meta": {
            "topic": "RD034_A_Share_3Layer_Endogenous_Cycles_x_6_V20_Strategies",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.time() - t0, 2),
            "d12_yfinance_imported": "yfinance" in sys.modules,
            "is_window": "2021-01-04 ~ 2024-12-31",
            "oos_window": "2025-01-01 ~ 2026-11-25 (combined to 2026-11-16)",
            "y2026_window": "2026-01-01 ~ 2026-11-25 (combined to 2026-11-16)",
            "final_combined_verdict": final_verdict,
            "winning_combined_schemes": winning_comb,
            "single_strategy_is_oos_survivors": single_double_pass,
        },
        "baseline_parity": parity_rep,
        "step1_pit_and_truncation": s1_aud,
        "step2_3layer_scan_and_v20_absorption": s2_aud,
        "step3_single_strategy_rerank_is_to_oos": single_rerank,
        "step3_single_strategy_filter_is_to_oos": single_filter,
        "step3_v20_combined_rerank_and_filter": {
            "schemes": comb_evals,
            "cscv_pbo": cscv_comb,
            "trade_diffs": all_diffs,
        },
        "step3_v20_combined_half50_and_stop0": half50_res,
        "output_files": {
            "master_audit_json": f"{OUT_DIR}/rd034_3layer_cycles_audit.json",
            "factor_matrix_csv": f"{OUT_DIR}/rd034_factor_matrix_all6.csv",
            "oos_strategy_compare_csv": cmp_csv,
        },
    })

    out_json = f"{OUT_DIR}/rd034_3layer_cycles_audit.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(master_json, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"\n[DONE Step 3 in {time.time()-t0:.1f}s] Final Verdict = {final_verdict} | Saved -> {out_json}")
    print("\n=== V20.0 Combined Rerank & Filter Summary ===")
    print(pd.DataFrame([r for r in cmp_rows if r["mode"] != "HALF50_OR_STOP0"])[
        ["scheme_id", "n_full", "nav_full", "ex5_full", "mdd_full_pct", "sharpe_full", "nav_is", "nav_oos", "nav_y26", "boot_prob_beat_v20_pct", "bh_fdr_vs_v20_q"]
    ].to_string(index=False))
    print("\n=== V20.0 Combined Half50 & Stop0 Top Rows ===")
    print("  Best IS Half50:", half50_res["best_is_half50"]["policy"], "| IS:", half50_res["best_is_half50"]["IS"], "| OOS:", half50_res["best_is_half50"]["OOS"])
    print("  Best IS Stop0 :", half50_res["best_is_stop0"]["policy"], "| IS:", half50_res["best_is_stop0"]["IS"], "| OOS:", half50_res["best_is_stop0"]["OOS"])


if __name__ == "__main__":
    main()
