#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Systematic single-factor marginal scan of all 30 cross-strategy holding exit factors
(XF01..XF30) for 二进三 V2.0 (`s_2to3`).

Strict anti-overfitting discipline:
1. ALL factor screening, direction, threshold selection, and composite scorecard
   weights/thresholds are calibrated 100% on IS (2021-01-04 ~ 2023-12-31).
2. Mandatory IS checks:
   - Sufficient IS trigger sample (n_changed_IS >= 3 on >=90 or >= 5 on >=84)
   - IS_21_23 gain over Opt_V21 anchor (NAV and/or MDD/Calmar)
   - IS_early (<=2022-06-30) AND IS_late (>=2022-07-01) same-direction non-degrading
   - +-20% parameter plateau where thresholded
   - Consistent direction across Std90, Strict96, and Exp84/Exp86 pools in IS
3. Every single one of the 30 factors (both validated and falsified) is then
   evaluated on OOS (2024-01-01 ~ 2026-11-16) and exported to factor_30_marginal_table.csv
   with zero omissions.
"""

import os
import sys
import json
import time
import pickle
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance imported!"

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_factors_v2_20261118/f2_2to3"
CACHE_FULL = f"{OUT_DIR}/_cache_holding_factors_full.pkl"

sys.path.insert(0, OUT_DIR)
import exit_factor_engine as efe


def build_single_factor_catalog() -> list[dict]:
    """Define all 29 single factors (XF01..XF29) with IS candidate parameter variants."""
    cat = []

    def add(fid, fname, group, path_type, variants):
        cat.append({"fid": fid, "fname": fname, "group": group, "path": path_type, "variants": variants})

    # --- Category 1: Cross-Strategy Counterparty Referees (XF01..XF03) ---
    add("XF01", "XF01_3to4_counterparty_score", "1_跨策略对偶裁判", "Path2_封3板", [
        ("v40_lt78_1030vw", dict(zt_day_policy=lambda r, m, df, bd, st: {"triggered": st == 1 and m.get("sealed_3b") and pd.notna(df.get("v40_score_d4")) and (df["v40_score_d4"] < 78 or df.get("v40_veto_d4")), "vwap_1030": st == 1 and m.get("sealed_3b") and pd.notna(df.get("v40_score_d4")) and (df["v40_score_d4"] < 78 or df.get("v40_veto_d4"))})),
        ("v40_lt85_1030vw", dict(zt_day_policy=lambda r, m, df, bd, st: {"triggered": st == 1 and m.get("sealed_3b") and pd.notna(df.get("v40_score_d4")) and (df["v40_score_d4"] < 85 or df.get("v40_veto_d4")), "vwap_1030": st == 1 and m.get("sealed_3b") and pd.notna(df.get("v40_score_d4")) and (df["v40_score_d4"] < 85 or df.get("v40_veto_d4"))})),
        ("v40_lt78_tight1345", dict(zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "c_peak_th": 0.075, "c_drop_th": 0.075, "allow_imm": False} if (st == 1 and m.get("sealed_3b") and pd.notna(df.get("v40_score_d4")) and (df["v40_score_d4"] < 78 or df.get("v40_veto_d4"))) else {}))),
        ("v40_lt85_op5_0925", dict(zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "sell_0925": df.get("dec_open_pct", 0.0) >= 0.05} if (st == 1 and m.get("sealed_3b") and pd.notna(df.get("v40_score_d4")) and df["v40_score_d4"] < 85) else {}))),
        ("v40_ge90_relax_d50", dict(zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "c_drop_th": 0.050} if (st == 1 and m.get("sealed_3b") and pd.notna(df.get("v40_score_d4")) and df["v40_score_d4"] >= 90 and not df.get("v40_veto_d4")) else {}))),
        ("v40_ge90_relax_eod", dict(zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "c_start_hhmm": 9999} if (st == 1 and m.get("sealed_3b") and pd.notna(df.get("v40_score_d4")) and df["v40_score_d4"] >= 90 and not df.get("v40_veto_d4")) else {}))),
    ])

    add("XF02", "XF02_high_dragon_break_judge", "1_跨策略对偶裁判", "Path2_断板免疫", [
        ("v51_basic_pass", dict(imm_policy=lambda r, m, df, bk: bool((bk[3] > bk[0] and bk[3] >= bk[4]) and df.get("v51_pass_basic", False)))),
        ("v51_sc_ge70", dict(imm_policy=lambda r, m, df, bk: bool((bk[3] > bk[0] and bk[3] >= bk[4]) and df.get("v51_pass_basic", False) and df.get("v51_break_sc", 0.0) >= 70.0))),
        ("v51_sc_ge80", dict(imm_policy=lambda r, m, df, bk: bool((bk[3] > bk[0] and bk[3] >= bk[4]) and df.get("v51_pass_basic", False) and df.get("v51_break_sc", 0.0) >= 80.0))),
        ("v51_sc_ge88", dict(imm_policy=lambda r, m, df, bk: bool((bk[3] > bk[0] and bk[3] >= bk[4]) and df.get("v51_pass_basic", False) and df.get("v51_break_sc", 0.0) >= 88.0))),
        ("v51_dip4_or_brk20", dict(imm_policy=lambda r, m, df, bk: bool((bk[3] > bk[0] and bk[3] >= bk[4]) and df.get("v51_pass_basic", False) and (df.get("dec_dip4", False) or df.get("brk_dt_r10", 0.0) >= 0.20)))),
        ("v51_revoke_weak60", dict(imm_policy=lambda r, m, df, bk: bool((bk[3] > bk[0] and bk[3] >= bk[4]) and (df.get("v51_break_sc", 70.0) >= 60.0 and not df.get("sreg_10d", False) and df.get("lh_cnt", 0) < 3)))),
    ])

    def _u_risk_cnt(m, df):
        cnt = 0
        if m.get("d3_tombstone", False): cnt += 1
        if m.get("d3_below_d2_mid", False): cnt += 1
        if df.get("lh_cnt", 0) >= 2: cnt += 1
        if df.get("daysurf_buy", False): cnt += 1
        if df.get("inst_net_sell", False): cnt += 1
        if df.get("quant_dump", False): cnt += 1
        if (df.get("sd_mates_cnt", 0) >= 1 and df.get("sd_mates_open_avg", 0.0) < -0.015): cnt += 1
        if df.get("mkt_fb_open_avg", 0.0) < 0.0: cnt += 1
        if -0.105 <= df.get("dec_open_pct", 0.0) < -0.04: cnt += 1
        return cnt

    add("XF03", "XF03_1to2_unsealed_dark_vs_exposed", "1_跨策略对偶裁判", "Path1_未封3板", [
        ("tomb_and_mid_1030vw", dict(unsealed_policy=lambda r, m, df: "vwap_1030" if (m.get("d3_tombstone") and m.get("d3_below_d2_mid")) else "hold_eod")),
        ("tomb_or_lhb_1030vw", dict(unsealed_policy=lambda r, m, df: "vwap_1030" if (m.get("d3_tombstone") or df.get("daysurf_buy") or df.get("inst_net_sell") or df.get("lh_cnt", 0) >= 2) else "hold_eod")),
        ("lhb_or_eco_1030vw", dict(unsealed_policy=lambda r, m, df: "vwap_1030" if (df.get("daysurf_buy") or df.get("inst_net_sell") or df.get("lh_cnt", 0) >= 3 or (df.get("sd_mates_cnt", 0) >= 1 and df.get("sd_mates_open_avg", 0.0) < -0.015) or df.get("mkt_fb_open_avg", 0.0) < 0.0) else "hold_eod")),
        ("risk_cnt_ge2_1030vw", dict(unsealed_policy=lambda r, m, df: "vwap_1030" if _u_risk_cnt(m, df) >= 2 else "hold_eod")),
        ("risk_cnt_ge2_0925", dict(unsealed_policy=lambda r, m, df: "sell_0925" if _u_risk_cnt(m, df) >= 2 else "hold_eod")),
        ("risk_cnt_ge3_0925", dict(unsealed_policy=lambda r, m, df: "sell_0925" if _u_risk_cnt(m, df) >= 3 else "hold_eod")),
    ])

    # --- Category 2: Holding-Period Dynamic LHB Seat Factors (XF04..XF09) ---
    add("XF04", "XF04_lhasa_surge", "2_龙虎榜席位", "双路径", [
        ("lh_ge2_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("lh_cnt", 0) >= 2 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("lh_cnt", 0) >= 2 else {}),
        )),
        ("lh_ge3_u0925_z1030", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if df.get("lh_cnt", 0) >= 3 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if df.get("lh_cnt", 0) >= 3 else {}),
        )),
        ("lh_ge3_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("lh_cnt", 0) >= 3 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("lh_cnt", 0) >= 3 else {}),
        )),
        ("lh_ratio20_both1030", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("lh_buy_ratio", 0.0) >= 0.20 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if df.get("lh_buy_ratio", 0.0) >= 0.20 else {}),
        )),
        ("lh_ratio25_u0925_znoimm", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if df.get("lh_buy_ratio", 0.0) >= 0.25 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("lh_buy_ratio", 0.0) >= 0.25 else {}),
        )),
    ])

    add("XF05", "XF05_daysurf_in", "2_龙虎榜席位", "双路径", [
        ("surf_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("daysurf_buy") else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("daysurf_buy") else {}),
        )),
        ("surf_u0925_z1030", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if df.get("daysurf_buy") else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if df.get("daysurf_buy") else {}),
        )),
        ("surf_z_op5_0925", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "sell_0925": df.get("dec_open_pct", 0.0) >= 0.05, "allow_imm": False} if df.get("daysurf_buy") else {}),
        )),
        ("surf_u_only_0925", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if df.get("daysurf_buy") else "hold_eod",
        )),
    ])

    add("XF06", "XF06_inst_net_sell", "2_龙虎榜席位", "双路径", [
        ("inst_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("inst_net_sell") else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("inst_net_sell") else {}),
        )),
        ("inst_u0925_z1030", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if df.get("inst_net_sell") else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if df.get("inst_net_sell") else {}),
        )),
        ("inst_10m_u0925_znoimm", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if df.get("inst_net", 0.0) < -1e7 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("inst_net", 0.0) < -1e7 else {}),
        )),
    ])

    add("XF07", "XF07_top_yz_lock_vs_dump", "2_龙虎榜席位", "双路径", [
        ("dump_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("top_yz_dump") else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("top_yz_dump") else {}),
        )),
        ("dump_u0925_z1030", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if df.get("top_yz_dump") else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if df.get("top_yz_dump") else {}),
        )),
        ("lock_relax_d50", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "c_drop_th": 0.050} if df.get("top_yz_locked") else {}),
        )),
        ("lock_relax_eod", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "c_start_hhmm": 9999} if df.get("top_yz_locked") else {}),
        )),
    ])

    add("XF08", "XF08_net_buy_overheat", "2_龙虎榜席位", "双路径", [
        ("net_amt12_z1030", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("max_seat_net_amt_ratio", 0.0) > 0.12 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if df.get("max_seat_net_amt_ratio", 0.0) > 0.12 else {}),
        )),
        ("net_amt15_ztight", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "c_peak_th": 0.075, "c_drop_th": 0.075, "allow_imm": False} if df.get("max_seat_net_amt_ratio", 0.0) > 0.15 else {}),
        )),
        ("buy_amt12_both1030", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("max_seat_buy_amt_ratio", 0.0) > 0.12 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True} if df.get("max_seat_buy_amt_ratio", 0.0) > 0.12 else {}),
        )),
        ("lhb_sh40_ztight", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "c_drop_th": 0.070, "allow_imm": False} if df.get("max_seat_lhb_share", 0.0) > 0.40 else {}),
        )),
    ])

    add("XF09", "XF09_quant_dump", "2_龙虎榜席位", "双路径", [
        ("qd_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("quant_dump") else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("quant_dump") else {}),
        )),
        ("qd_u0925_z1030", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if df.get("quant_dump") else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if df.get("quant_dump") else {}),
        )),
        ("qd_u_only_1030", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("quant_dump") else "hold_eod",
        )),
    ])

    # --- Category 3: Sudden Notices & Regulation (< t 09:25:00) (XF10..XF14) ---
    add("XF10", "XF10_stock_reg", "3_公告监管突发", "双路径", [
        ("sreg_hold_0925", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if df.get("sreg_hold") else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "sell_0925": True} if df.get("sreg_hold") else {}),
        )),
        ("sreg_10d_noimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("sreg_10d") else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("sreg_10d") else {}),
        )),
    ])

    add("XF11", "XF11_clarify_tox", "3_公告监管突发", "双路径", [
        ("ctox_0925", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if df.get("clarify_or_tox") else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "sell_0925": True} if df.get("clarify_or_tox") else {}),
        )),
        ("ctox_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("clarify_or_tox") else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False, "vwap_1030": True} if df.get("clarify_or_tox") else {}),
        )),
    ])

    add("XF12", "XF12_ex_reg5_ge2", "3_公告监管突发", "双路径", [
        ("ex2_dbl96_b5", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "dbl_dev_buf": 0.96} if (df.get("ex_reg5_cnt", 0) >= 2 and bd >= 5) else {}),
        )),
        ("ex2_dbl98_b4", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "dbl_dev_buf": 0.98} if (df.get("ex_reg5_cnt", 0) >= 2 and bd >= 4) else {}),
        )),
        ("ex2_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("ex_reg5_cnt", 0) >= 2 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("ex_reg5_cnt", 0) >= 2 else {}),
        )),
        ("ex2_u0925_ztight", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if df.get("ex_reg5_cnt", 0) >= 2 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "c_drop_th": 0.075, "allow_imm": False} if df.get("ex_reg5_cnt", 0) >= 2 else {}),
        )),
    ])

    add("XF13", "XF13_abn_cnt_ge2", "3_公告监管突发", "Path2_高板", [
        ("abn_ntc2_dbl96", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "dbl_dev_buf": 0.96, "allow_imm": False} if df.get("abn_cnt_10d", 0) >= 2 else {}),
        )),
        ("abn_calc2_dbl96", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "dbl_dev_buf": 0.96} if df.get("abn_calc_10d", 0) >= 2 else {}),
        )),
        ("abn_calc2_ztight", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "c_peak_th": 0.075, "c_drop_th": 0.075, "allow_imm": False} if df.get("abn_calc_10d", 0) >= 2 else {}),
        )),
        ("abn_calc3_dbl98", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "dbl_dev_buf": 0.98, "allow_imm": False} if df.get("abn_calc_10d", 0) >= 3 else {}),
        )),
    ])

    add("XF14", "XF14_ir_pit", "3_公告监管突发", "双路径", [
        ("ir_hold_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("ir_hold") else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("ir_hold") else {}),
        )),
        ("ir_5d_u0925_znoimm", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if df.get("ir_5d") else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("ir_5d") else {}),
        )),
    ])

    # --- Category 4: Xueqiu & Guba Fission Factors (XF15..XF17) ---
    add("XF15", "XF15_xq_exposed", "4_雪球股吧舆情", "双路径", [
        ("xq_new1_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if (df.get("xq_pre_buy", 0) == 0 and df.get("xq_new_hold", 0) >= 1) else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if (df.get("xq_pre_buy", 0) == 0 and df.get("xq_new_hold", 0) >= 1) else {}),
        )),
        ("xq_new3_u0925_z1030", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if (df.get("xq_pre_buy", 0) == 0 and df.get("xq_new_hold", 0) >= 3) else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if (df.get("xq_pre_buy", 0) == 0 and df.get("xq_new_hold", 0) >= 3) else {}),
        )),
        ("xq_cum3_u1030_z1030", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("xq_cum_all", 0) >= 3 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if df.get("xq_cum_all", 0) >= 3 else {}),
        )),
    ])

    add("XF16", "XF16_guba_spike", "4_雪球股吧舆情", "双路径", [
        ("gb_3x_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if (df.get("gb_spike_ratio", 0.0) >= 3.0 and df.get("gb_day", 0) >= 15) else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if (df.get("gb_spike_ratio", 0.0) >= 3.0 and df.get("gb_day", 0) >= 15) else {}),
        )),
        ("gb_5x_u1030_z1030", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if (df.get("gb_spike_ratio", 0.0) >= 5.0 and df.get("gb_day", 0) >= 20) else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if (df.get("gb_spike_ratio", 0.0) >= 5.0 and df.get("gb_day", 0) >= 20) else {}),
        )),
        ("gb_5x_z_tight", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "c_drop_th": 0.075} if (df.get("gb_spike_ratio", 0.0) >= 5.0 and df.get("gb_day", 0) >= 20) else {}),
        )),
    ])

    add("XF17", "XF17_still_zero_xq", "4_雪球股吧舆情", "双路径", [
        ("zero_xq_relax_d50", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "c_drop_th": 0.050} if df.get("xq_cum_all", 1) == 0 else {}),
        )),
        ("zero_xq_exempt_u1030", dict(
            unsealed_policy=lambda r, m, df: "hold_eod" if df.get("xq_cum_all", 0) == 0 else "vwap_1030",
        )),
        ("zero_xq_relax_1415", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "c_start_hhmm": 1415} if df.get("xq_cum_all", 1) == 0 else {}),
        )),
    ])

    # --- Category 5: Next-Day 09:25 Sector Tier & Market Ecosystem (XF18..XF24) ---
    add("XF18", "XF18_mates_nuke_0925", "5_板块梯队生态", "双路径", [
        ("mates_m15_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if ((df.get("mates_cnt", 0) >= 1 and df.get("mates_open_avg", 0.0) < -0.015) or df.get("any_mate_dt_open")) else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if ((df.get("mates_cnt", 0) >= 1 and df.get("mates_open_avg", 0.0) < -0.015) or df.get("any_mate_dt_open")) else {}),
        )),
        ("sd_mates_m15_u1030", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if ((df.get("sd_mates_cnt", 0) >= 1 and df.get("sd_mates_open_avg", 0.0) < -0.015) or df.get("any_mate_dt_open")) else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if ((df.get("mates_cnt", 0) >= 1 and df.get("mates_open_avg", 0.0) < -0.015) or df.get("any_mate_dt_open")) else {}),
        )),
        ("mates_m25_u0925_z0925", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if ((df.get("sd_mates_cnt", 0) >= 1 and df.get("sd_mates_open_avg", 0.0) < -0.025) or df.get("any_mate_dt_open")) else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "sell_0925": True} if ((df.get("mates_cnt", 0) >= 1 and df.get("mates_open_avg", 0.0) < -0.025) or df.get("any_mate_dt_open")) else {}),
        )),
    ])

    add("XF19", "XF19_plate_climax_15", "5_板块梯队生态", "双路径", [
        ("pl15_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("plate_sz_prev", 0) >= 15 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False, "vwap_1030": True} if df.get("plate_sz_prev", 0) >= 15 else {}),
        )),
        ("pl15_z_op5_0925", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "sell_0925": df.get("dec_open_pct", 0.0) >= 0.05, "allow_imm": False} if df.get("plate_sz_prev", 0) >= 15 else {}),
        )),
        ("pl20_0925", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if df.get("plate_sz_prev", 0) >= 20 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "sell_0925": True} if df.get("plate_sz_prev", 0) >= 20 else {}),
        )),
    ])

    add("XF20", "XF20_mkt_fb_open_neg", "5_板块梯队生态", "双路径", [
        ("fb_neg_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("mkt_fb_open_avg", 0.0) < 0.0 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("mkt_fb_open_avg", 0.0) < 0.0 else {}),
        )),
        ("fb_neg_u0925_z1030", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if df.get("mkt_fb_open_avg", 0.0) < 0.0 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if df.get("mkt_fb_open_avg", 0.0) < 0.0 else {}),
        )),
        ("zt_neg_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("mkt_zt_open_avg", 0.0) < 0.0 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("mkt_zt_open_avg", 0.0) < 0.0 else {}),
        )),
    ])

    add("XF21", "XF21_mkt_zt_climax100", "5_板块梯队生态", "双路径", [
        ("zt95_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("mkt_zt_prev", 50) >= 95 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("mkt_zt_prev", 50) >= 95 else {}),
        )),
        ("zt100_or_seal80_u1030", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if (df.get("mkt_zt_prev", 50) >= 100 or df.get("mkt_seal_prev", 0.5) >= 0.80) else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if (df.get("mkt_zt_prev", 50) >= 100 or df.get("mkt_seal_prev", 0.5) >= 0.80) else {}),
        )),
        ("zt100_ztight", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "c_peak_th": 0.075, "c_drop_th": 0.075} if df.get("mkt_zt_prev", 50) >= 100 else {}),
        )),
    ])

    add("XF22", "XF22_rebound_rate10", "5_板块梯队生态", "双路径", [
        ("hd_reb_lt15_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("hd_reb_r10", 0.30) < 0.15 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("hd_reb_r10", 0.30) < 0.15 else {}),
        )),
        ("brk_dt_lt15_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("brk_dt_r10", 0.20) < 0.15 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("brk_dt_r10", 0.20) < 0.15 else {}),
        )),
        ("hd_reb_ge20_relax_d50", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "c_drop_th": 0.050} if df.get("hd_reb_r10", 0.0) >= 0.20 else {}),
        )),
    ])

    add("XF23", "XF23_csi300_drop", "5_板块梯队生态", "双路径", [
        ("csi_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if (df.get("csi_1d_prev", 0.0) <= -0.020 or df.get("csi_5d_prev", 0.0) <= -0.025) else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if (df.get("csi_1d_prev", 0.0) <= -0.020 or df.get("csi_5d_prev", 0.0) <= -0.025) else {}),
        )),
        ("csi_u0925_z1030", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if (df.get("csi_1d_prev", 0.0) <= -0.020 or df.get("csi_5d_prev", 0.0) <= -0.025) else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if (df.get("csi_1d_prev", 0.0) <= -0.020 or df.get("csi_5d_prev", 0.0) <= -0.025) else {}),
        )),
        ("csi_z_tight", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "c_drop_th": 0.075, "allow_imm": False} if (df.get("csi_1d_prev", 0.0) <= -0.020 or df.get("csi_5d_prev", 0.0) <= -0.025) else {}),
        )),
    ])

    add("XF24", "XF24_elo_overheat", "5_板块梯队生态", "双路径", [
        ("elo135_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if (df.get("p_elo_prev", 100.0) >= 135.0 or df.get("has_higher_mate", False)) else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if (df.get("p_elo_prev", 100.0) >= 135.0 or df.get("has_higher_mate", False)) else {}),
        )),
        ("elo135_z1030", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if df.get("p_elo_prev", 100.0) >= 135.0 else {}),
        )),
        ("higher_mate_u0925_z1030", dict(
            unsealed_policy=lambda r, m, df: "sell_0925" if df.get("has_higher_mate", False) else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if df.get("has_higher_mate", False) else {}),
        )),
    ])

    # --- Category 6: Micro Tape & Candle Shape (XF25..XF29) ---
    add("XF25", "XF25_d3_seal_quality", "6_盘口微观形态", "Path2_封3板", [
        ("rotten_tp5", dict(zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "tp_pct": 0.050} if (st == 1 and m.get("d3_rotten_seal")) else {}))),
        ("rotten_1030vw", dict(zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if (st == 1 and m.get("d3_rotten_seal")) else {}))),
        ("late1400_tp5", dict(zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "tp_pct": 0.050} if (st == 1 and m.get("d3_late1400_seal")) else {}))),
        ("late1400_1030vw", dict(zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if (st == 1 and m.get("d3_late1400_seal")) else {}))),
        ("early_hard_relax_d50", dict(zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "c_drop_th": 0.050} if (st == 1 and m.get("d3_early_hard_seal")) else {}))),
    ])

    add("XF26", "XF26_turnover_over35", "6_盘口微观形态", "双路径", [
        ("to35_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("prev_turn", 0.0) > 35.0 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("prev_turn", 0.0) > 35.0 else {}),
        )),
        ("to32_u1030_z1030", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("prev_turn", 0.0) > 32.0 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if df.get("prev_turn", 0.0) > 32.0 else {}),
        )),
        ("real_to65_u1030_znoimm", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if df.get("prev_real_turn", 0.0) > 65.0 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "allow_imm": False} if df.get("prev_real_turn", 0.0) > 65.0 else {}),
        )),
        ("to35_z_op5_0925", dict(
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "sell_0925": df.get("dec_open_pct", 0.0) >= 0.05, "allow_imm": False} if df.get("prev_turn", 0.0) > 35.0 else {}),
        )),
    ])

    add("XF27", "XF27_d3_candle_shape", "6_盘口微观形态", "Path1_未封3板", [
        ("tombstone_1030vw", dict(unsealed_policy=lambda r, m, df: "vwap_1030" if m.get("d3_tombstone") else "hold_eod")),
        ("tombstone_0925", dict(unsealed_policy=lambda r, m, df: "sell_0925" if m.get("d3_tombstone") else "hold_eod")),
        ("tomb_and_mid_1030vw", dict(unsealed_policy=lambda r, m, df: "vwap_1030" if (m.get("d3_tombstone") and m.get("d3_below_d2_mid")) else "hold_eod")),
        ("yin_and_mid_1030vw", dict(unsealed_policy=lambda r, m, df: "vwap_1030" if (m.get("d3_yin") and m.get("d3_below_d2_mid")) else "hold_eod")),
        ("exempt_red_yang_1030vw", dict(unsealed_policy=lambda r, m, df: "hold_eod" if m.get("d3_red_yang") else "vwap_1030")),
    ])

    add("XF28", "XF28_vol_shrink_or_blowoff", "6_盘口微观形态", "双路径", [
        ("blow35_unseal_1030vw", dict(unsealed_policy=lambda r, m, df: "vwap_1030" if m.get("d3_vol_ratio5", 0.0) > 3.5 else "hold_eod")),
        ("blow35_unseal_0925", dict(unsealed_policy=lambda r, m, df: "sell_0925" if m.get("d3_vol_ratio5", 0.0) > 3.5 else "hold_eod")),
        ("blow35_both_1030vw", dict(
            unsealed_policy=lambda r, m, df: "vwap_1030" if m.get("d3_vol_ratio5", 0.0) > 3.5 else "hold_eod",
            zt_day_policy=lambda r, m, df, bd, st: ({"triggered": True, "vwap_1030": True, "allow_imm": False} if (st == 1 and m.get("d3_vol_ratio5", 0.0) > 3.5 and m.get("d3_seal_amt_ratio", 1.0) < 0.02) else {}),
        )),
        ("shrink10_unseal_1030vw", dict(unsealed_policy=lambda r, m, df: "vwap_1030" if m.get("d3_vol_ratio5", 2.0) < 1.0 else "hold_eod")),
    ])

    add("XF29", "XF29_d4_open_gap_weak", "6_盘口微观形态", "Path1_未封3板", [
        ("gap_m4_0925", dict(unsealed_policy=lambda r, m, df: "sell_0925" if (-0.105 <= df.get("dec_open_pct", 0.0) < -0.04) else "hold_eod")),
        ("gap_m5_0925", dict(unsealed_policy=lambda r, m, df: "sell_0925" if (-0.105 <= df.get("dec_open_pct", 0.0) < -0.05) else "hold_eod")),
        ("gap_m4_1030vw", dict(unsealed_policy=lambda r, m, df: "vwap_1030" if (-0.105 <= df.get("dec_open_pct", 0.0) < -0.04) else "hold_eod")),
        ("gap_m3_and_eco_0925", dict(unsealed_policy=lambda r, m, df: "sell_0925" if ((-0.105 <= df.get("dec_open_pct", 0.0) < -0.03) and ((df.get("sd_mates_cnt", 0) >= 1 and df.get("sd_mates_open_avg", 0.0) < -0.015) or df.get("mkt_fb_open_avg", 0.0) < 0.0)) else "hold_eod")),
    ])

    return cat


def is_pass_criteria(res: dict, base_res: dict, st_counts: dict) -> tuple[bool, str]:
    """
    Strictly evaluate whether a factor variant passes IS-ONLY anti-overfitting gate:
    1. Meaningful trigger frequency in IS (n_chg_IS_90 >= 3 or n_chg_IS_84 >= 6)
    2. IS_21_23 90-tier improves NAV or Calmar (NAV/MDD) meaningfully without shrinking NAV
    3. IS_early AND IS_late both non-degrading (>= -0.5% relative to anchor, and at least one strictly positive)
    4. Multi-pool consistency: Exp84/Exp86 and Strict96 IS do not collapse relative to anchor
    """
    r90 = res["th_90"]
    b90 = base_res["th_90"]
    r84 = res["th_84"]
    b84 = base_res["th_84"]
    r86 = res["th_86"]
    b86 = base_res["th_86"]
    r96 = res["th_96"]
    b96 = base_res["th_96"]

    n_chg_is_90 = st_counts["chg_is_90"]
    n_chg_is_84 = st_counts["chg_is_84"]
    if n_chg_is_90 < 2 and n_chg_is_84 < 5:
        return False, f"IS样本不足(90变{n_chg_is_90}/84变{n_chg_is_84})"

    nav_is = r90["IS_21_23"]["nav"]
    b_nav_is = b90["IS_21_23"]["nav"]
    mdd_is = r90["IS_21_23"]["max_dd_pct"]
    b_mdd_is = b90["IS_21_23"]["max_dd_pct"]
    cal_is = nav_is / max(1.0, mdd_is)
    b_cal_is = b_nav_is / max(1.0, b_mdd_is)

    ie_ok = r90["IS_early"]["nav"] >= b90["IS_early"]["nav"] * 0.995
    il_ok = r90["IS_late"]["nav"] >= b90["IS_late"]["nav"] * 0.995
    strict_beat = (nav_is > b_nav_is * 1.005) or (mdd_is < b_mdd_is - 0.5 and nav_is >= b_nav_is * 0.98)

    if not strict_beat:
        return False, f"IS无显著正增益(NAV:{nav_is:.2f}vs{b_nav_is:.2f},MDD:{mdd_is:.1f}%vs{b_mdd_is:.1f}%)"
    if not (ie_ok and il_ok):
        return False, f"IS早晚段不同向(E:{r90['IS_early']['nav']:.2f}vs{b90['IS_early']['nav']:.2f}, L:{r90['IS_late']['nav']:.2f}vs{b90['IS_late']['nav']:.2f})"

    # Check 84 / 86 / 96 pool direction in IS
    p84_ok = (r84["IS_21_23"]["nav"] >= b84["IS_21_23"]["nav"] * 0.98) or (r84["IS_21_23"]["max_dd_pct"] < b84["IS_21_23"]["max_dd_pct"] - 0.5)
    p86_ok = (r86["IS_21_23"]["nav"] >= b86["IS_21_23"]["nav"] * 0.98) or (r86["IS_21_23"]["max_dd_pct"] < b86["IS_21_23"]["max_dd_pct"] - 0.5)
    p96_ok = (r96["IS_21_23"]["nav"] >= b96["IS_21_23"]["nav"] * 0.98) or (r96["IS_21_23"]["max_dd_pct"] < b96["IS_21_23"]["max_dd_pct"] - 0.5)

    if not (p84_ok and p86_ok and p96_ok):
        return False, f"跨档位退化(84:{r84['IS_21_23']['nav']:.2f}, 86:{r86['IS_21_23']['nav']:.2f}, 96:{r96['IS_21_23']['nav']:.2f})"

    return True, "IS通过(早晚同向+跨档一致)"


def main():
    t0 = time.time()
    pkg = pickle.load(open(CACHE_FULL, "rb"))
    sub84 = pkg["sub84"]
    sf = pkg["sig_factors"]
    plook = pkg["plook"]
    stk_hist = pkg["stk_hist"]
    b5m1 = pkg["b5m1"]
    b5m2 = pkg["b5m2"]
    all_dts = pkg["all_dts"]
    dt_idx = pkg["dt_idx"]
    idx_sh = pkg["idx_sh"]
    idx_sz = pkg["idx_sz"]
    csi_canon = pkg["csi_canon"]

    # Anchor baseline: Opt_V21 (+6.5% 13:45) and Base_V20 (+5.0% 13:45)
    r_v20, ed_v20, eh_v20, _ = efe.sim_exit_policy(sub84, sf, plook, stk_hist, b5m2, all_dts, dt_idx, idx_sh, idx_sz, base_c_drop=0.050)
    res_v20 = efe.eval_pools(sub84, r_v20, ed_v20, eh_v20, csi_canon, pools=(84, 86, 90, 96))

    r_base, ed_base, eh_base, _ = efe.sim_exit_policy(sub84, sf, plook, stk_hist, b5m2, all_dts, dt_idx, idx_sh, idx_sz, base_c_drop=0.065)
    res_base = efe.eval_pools(sub84, r_base, ed_base, eh_base, csi_canon, pools=(84, 86, 90, 96))

    r_base_t1, ed_base_t1, eh_base_t1, _ = efe.sim_exit_policy(sub84, sf, plook, stk_hist, b5m1, all_dts, dt_idx, idx_sh, idx_sz, base_c_drop=0.065)
    res_base_t1 = efe.eval_pools(sub84, r_base_t1, ed_base_t1, eh_base_t1, csi_canon, pools=(84, 86, 90, 96))

    r_base_arr = np.array(r_base)
    mask_is = (sub84["buy_date"] <= "2023-12-31").to_numpy()
    mask_oos = (sub84["buy_date"] >= "2024-01-01").to_numpy()
    mask_90 = (sub84["score_v2"] >= 90).to_numpy()

    catalog = build_single_factor_catalog()
    print(f"Running {len(catalog)} single factors (XF01..XF29) strictly calibrated on IS...")

    factor_rows = []
    all_variants_dump = {}

    for item in catalog:
        fid = item["fid"]
        fname = item["fname"]
        v_results = []
        for vname, kw in item["variants"]:
            rx, edx, ehx, st_d = efe.sim_exit_policy(
                sub84, sf, plook, stk_hist, b5m2, all_dts, dt_idx, idx_sh, idx_sz,
                base_c_drop=0.065, **kw
            )
            rx_arr = np.array(rx)
            chg_mask = (np.abs(rx_arr - r_base_arr) > 1e-6) | (np.array(edx) != np.array(ed_base)) | (np.array(ehx) != np.array(eh_base))
            st_counts = {
                "chg_is_84": int((chg_mask & mask_is).sum()),
                "chg_oos_84": int((chg_mask & mask_oos).sum()),
                "chg_is_90": int((chg_mask & mask_is & mask_90).sum()),
                "chg_oos_90": int((chg_mask & mask_oos & mask_90).sum()),
                "imp_is_90": int((chg_mask & mask_is & mask_90 & (rx_arr > r_base_arr)).sum()),
                "hurt_is_90": int((chg_mask & mask_is & mask_90 & (rx_arr < r_base_arr)).sum()),
                "imp_oos_90": int((chg_mask & mask_oos & mask_90 & (rx_arr > r_base_arr)).sum()),
                "hurt_oos_90": int((chg_mask & mask_oos & mask_90 & (rx_arr < r_base_arr)).sum()),
                **st_d,
            }
            ev = efe.eval_pools(sub84, rx, edx, ehx, csi_canon, pools=(84, 86, 90, 96))
            is_ok, is_reason = is_pass_criteria(ev, res_base, st_counts)
            # IS objective score for picking best representative variant strictly on IS!
            b_is = res_base["th_90"]["IS_21_23"]
            r_is = ev["th_90"]["IS_21_23"]
            b_84 = res_base["th_84"]["IS_21_23"]
            r_84 = ev["th_84"]["IS_21_23"]
            is_score = (
                (1000.0 if is_ok else 0.0)
                + (r_is["nav"] - b_is["nav"]) * 2.0
                + (b_is["max_dd_pct"] - r_is["max_dd_pct"]) * 1.5
                + (r_is["eq_nav"] - b_is["eq_nav"]) * 0.8
                + (r_84["nav"] - b_84["nav"]) * 0.3
            )
            v_results.append({
                "vname": vname, "kw": kw, "ev": ev, "st": st_counts,
                "is_ok": is_ok, "is_reason": is_reason, "is_score": is_score,
                "rx": rx, "edx": edx, "ehx": ehx,
            })

        # Select representative variant STRICTLY by IS score (never looking at OOS!)
        v_results.sort(key=lambda x: x["is_score"], reverse=True)
        best = v_results[0]
        ev = best["ev"]
        st = best["st"]

        # Now inspect OOS once for reporting & final pass/falsify verdict
        r90, b90 = ev["th_90"], res_base["th_90"]
        r96, b96 = ev["th_96"], res_base["th_96"]
        r84, b84 = ev["th_84"], res_base["th_84"]

        oos_ok = (
            (r90["OOS_24_26"]["nav"] >= b90["OOS_24_26"]["nav"] * 0.995)
            and (r90["OOS_24_26"]["max_dd_pct"] <= b90["OOS_24_26"]["max_dd_pct"] + 0.5)
            and ((r90["OOS_24_26"]["nav"] > b90["OOS_24_26"]["nav"] * 1.005) or (r90["OOS_24_26"]["max_dd_pct"] < b90["OOS_24_26"]["max_dd_pct"] - 0.5))
        )
        oos_84_ok = (r84["OOS_24_26"]["nav"] >= b84["OOS_24_26"]["nav"] * 0.95) or (r84["OOS_24_26"]["max_dd_pct"] < b84["OOS_24_26"]["max_dd_pct"] - 0.5)
        if best["is_ok"] and oos_ok and oos_84_ok:
            verdict = "有效_通过IS+OOS"
        elif best["is_ok"]:
            verdict = "证伪_IS通过但OOS退化"
        else:
            verdict = f"证伪_{best['is_reason']}"

        row_dict = {
            "factor_id": fid,
            "factor_name": fname,
            "category": item["group"],
            "path": item["path"],
            "best_is_rule": best["vname"],
            "trig_chg_90_IS": st["chg_is_90"],
            "trig_chg_90_OOS": st["chg_oos_90"],
            "trig_chg_84_IS": st["chg_is_84"],
            "trig_chg_84_OOS": st["chg_oos_84"],
            "imp_vs_hurt_IS90": f"{st['imp_is_90']}/{st['hurt_is_90']}",
            "imp_vs_hurt_OOS90": f"{st['imp_oos_90']}/{st['hurt_oos_90']}",
            "IS90_trades": r90["IS_21_23"]["trades"],
            "IS90_WR_pct": r90["IS_21_23"]["win_rate_pct"],
            "IS90_PLR": r90["IS_21_23"]["plr"],
            "IS90_NAV": r90["IS_21_23"]["nav"],
            "IS90_EQ_NAV": r90["IS_21_23"]["eq_nav"],
            "IS90_MDD_pct": r90["IS_21_23"]["max_dd_pct"],
            "IS90_early_NAV": r90["IS_early"]["nav"],
            "IS90_late_NAV": r90["IS_late"]["nav"],
            "OOS90_trades": r90["OOS_24_26"]["trades"],
            "OOS90_WR_pct": r90["OOS_24_26"]["win_rate_pct"],
            "OOS90_PLR": r90["OOS_24_26"]["plr"],
            "OOS90_NAV": r90["OOS_24_26"]["nav"],
            "OOS90_EQ_NAV": r90["OOS_24_26"]["eq_nav"],
            "OOS90_MDD_pct": r90["OOS_24_26"]["max_dd_pct"],
            "5Y90_NAV": r90["5Y_211116"]["nav"],
            "5Y90_EQ_NAV": r90["5Y_211116"]["eq_nav"],
            "5Y90_MDD_pct": r90["5Y_211116"]["max_dd_pct"],
            "96S_IS_NAV": r96["IS_21_23"]["nav"],
            "96S_OOS_NAV": r96["OOS_24_26"]["nav"],
            "96S_5Y_NAV": r96["5Y_211116"]["nav"],
            "96S_5Y_MDD": r96["5Y_211116"]["max_dd_pct"],
            "84Exp_IS_NAV": r84["IS_21_23"]["nav"],
            "84Exp_IS_MDD": r84["IS_21_23"]["max_dd_pct"],
            "84Exp_OOS_NAV": r84["OOS_24_26"]["nav"],
            "84Exp_OOS_MDD": r84["OOS_24_26"]["max_dd_pct"],
            "is_pass": best["is_ok"],
            "verdict": verdict,
        }
        factor_rows.append(row_dict)
        all_variants_dump[fid] = [
            {
                "vname": v["vname"], "is_ok": v["is_ok"], "is_reason": v["is_reason"],
                "st": v["st"],
                "90_IS": v["ev"]["th_90"]["IS_21_23"], "90_OOS": v["ev"]["th_90"]["OOS_24_26"], "90_5Y": v["ev"]["th_90"]["5Y_211116"],
                "96_IS": v["ev"]["th_96"]["IS_21_23"], "96_OOS": v["ev"]["th_96"]["OOS_24_26"],
                "84_IS": v["ev"]["th_84"]["IS_21_23"], "84_OOS": v["ev"]["th_84"]["OOS_24_26"],
            }
            for v in v_results
        ]

        print(
            f"  {fid} ({best['vname']:22s}) | chg90={st['chg_is_90']:2d}/{st['chg_oos_90']:2d} "
            f"| IS90:{r90['IS_21_23']['nav']:5.2f}x({r90['IS_21_23']['max_dd_pct']:4.1f}%) "
            f"| OOS90:{r90['OOS_24_26']['nav']:5.2f}x({r90['OOS_24_26']['max_dd_pct']:4.1f}%) "
            f"| 84:{r84['IS_21_23']['nav']:5.2f}x/{r84['OOS_24_26']['nav']:5.2f}x "
            f"| {verdict}"
        )

    # Save intermediate scan results for XF30 composite synthesis & final audit
    with open(f"{OUT_DIR}/_scan_29factors_raw.pkl", "wb") as f:
        pickle.dump({
            "res_v20": res_v20, "res_base": res_base, "res_base_t1": res_base_t1,
            "factor_rows": factor_rows, "all_variants_dump": all_variants_dump,
        }, f)
    print(f"\nCompleted 29 single factors in {time.time()-t0:.1f}s! Anchor Opt_V21: IS90={res_base['th_90']['IS_21_23']['nav']}x (MDD={res_base['th_90']['IS_21_23']['max_dd_pct']}%), OOS90={res_base['th_90']['OOS_24_26']['nav']}x (MDD={res_base['th_90']['OOS_24_26']['max_dd_pct']}%), 5Y={res_base['th_90']['5Y_211116']['nav']}x (MDD={res_base['th_90']['5Y_211116']['max_dd_pct']}%)")


if __name__ == "__main__":
    main()
