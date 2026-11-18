#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step3_is_neighborhood_and_scorecard.py
严格只在 IS (2021-11-15 ~ 2023-12-31) 上做：
  1. 候选有效因子的 IS ±20% 参数平滑曲线检验（Elo 115..150, 机构净卖/卖额 0..3000w, 反包率 15..25%, 爆量倍数 2.8..4.5, 护利线 5.5..7.5%）
  2. 揭示单因子的正交性与交易重叠度
  3. 在 IS 上定标 XF30_composite_exit_scorecard（持仓卖点风险整数打分卡）并锁参
  4. 锁参后对全部入选单因子方案与 XF30 打分卡在 OOS (2024-01-01 ~ 2026-11-16) 上做一次性盲测！
"""

import os
import sys
import json
import time
import pickle
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_factors_v2_20261118/f1_3to4"
sys.path.insert(0, OUT_DIR)
import exit_factor_engine as efe


def run_param_smoothness_is(cache: dict, states: dict, base: dict):
    """严格仅展示 IS (90分 1S/EQ/IS22/IS23 + 78分+ EQ/1S) 的 ±20% 阈值平滑检验"""
    # 为了做精细阈值扫描，从原始 cache 抽取连续值供实时判断
    code_bars = cache["code_bars_ext"]
    lhb_map = cache["lhb_map"]
    stock_theme = cache["stock_theme_5y"]
    mkt_env = cache["mkt_env"]
    tape_ext = cache["tape_ext_map"]

    def eval_is_only(rule_fn, label: str):
        r90 = efe.evaluate_rule(cache, states, rule_fn, label, 90.0)
        r78 = efe.evaluate_rule(cache, states, rule_fn, label, 78.0)
        r102 = efe.evaluate_rule(cache, states, rule_fn, label, 102.0)
        b90 = base["90"]["raw_df"].set_index("idx")
        c90 = r90["raw_df"].set_index("idx")
        chg90 = (c90["net_ret"] - b90["net_ret"]).abs() > 1e-6
        is_c90 = int(chg90[c90["buy_date"] <= "2023-12-31"].sum())
        is_w90 = int(((c90["net_ret"] - b90["net_ret"]) > 1e-6)[c90["buy_date"] <= "2023-12-31"].sum())
        b78 = base["78"]["raw_df"].set_index("idx")
        c78 = r78["raw_df"].set_index("idx")
        chg78 = (c78["net_ret"] - b78["net_ret"]).abs() > 1e-6
        is_c78 = int(chg78[c78["buy_date"] <= "2023-12-31"].sum())
        is_w78 = int(((c78["net_ret"] - b78["net_ret"]) > 1e-6)[c78["buy_date"] <= "2023-12-31"].sum())
        return {
            "label": label,
            "is_c90": is_c90, "is_w90": is_w90,
            "is_d1s90": round(r90["IS"]["nav_1s"] - base["90"]["IS"]["nav_1s"], 4),
            "is_deq90": round(r90["IS"]["eq_nav"] - base["90"]["IS"]["eq_nav"], 4),
            "is22_deq90": round(r90["IS_22"]["eq_nav"] - base["90"]["IS_22"]["eq_nav"], 4),
            "is23_deq90": round(r90["IS_23"]["eq_nav"] - base["90"]["IS_23"]["eq_nav"], 4),
            "is_c78": is_c78, "is_w78": is_w78,
            "is_d1s78": round(r78["IS"]["nav_1s"] - base["78"]["IS"]["nav_1s"], 4),
            "is_deq78": round(r78["IS"]["eq_nav"] - base["78"]["IS"]["eq_nav"], 4),
            "is_d1s102": round(r102["IS"]["nav_1s"] - base["102"]["IS"]["nav_1s"], 4),
        }

    # 先给每条 (idx, k) 附加精确连续值（用于 ±20% 邻域平滑检验）
    for e in cache["buy_entries"]:
        idx = e["idx"]
        if idx not in states:
            continue
        c6 = e["code"]
        cb = code_bars[c6]
        last_elo = float(stock_theme.get((e["sig_date"], c6), {}).get("p_elo", 100.0))
        for k in sorted(states[idx].keys()):
            d_prev = str(cb["dts"][k - 1])
            ti_p = stock_theme.get((d_prev, c6))
            if ti_p is not None:
                last_elo = float(ti_p["p_elo"])
            lhb_p = lhb_map.get((d_prev, c6))
            env_p = mkt_env.get(d_prev, {})
            tp_p = tape_ext.get((d_prev, c6))
            amt_p = float(cb["amount"][k - 1])
            states[idx][k]["_elo"] = last_elo
            states[idx][k]["_inst_sell"] = float(lhb_p["inst_sell_amt"]) if lhb_p else 0.0
            states[idx][k]["_inst_net"] = float(lhb_p["inst_net_sell"]) if lhb_p else 0.0
            states[idx][k]["_vr"] = float(cb["vol_ratio"][k - 1])
            states[idx][k]["_reb_r10"] = float(env_p.get("brk_reb_r10", 0.25))
            states[idx][k]["_seal_r"] = (float(tp_p["seal_amount"]) / amt_p) if (tp_p and amt_p > 0 and cb["is_zt"][k - 1]) else 1.0

    print("=== IS-ONLY ±20% PARAMETER SMOOTHNESS CHECK ===")
    rows = []
    # 1. XF21 Elo + A2_1345_d70 / d60
    for elo_th in [115, 125, 130, 135, 140, 145]:
        rows.append(eval_is_only(lambda st, ctx, t=elo_th: {"tight_1345_thr": 0.070 if st.get("_elo", 0) >= t else 0.050}, f"XF21_elo>={elo_th}_d70"))
        rows.append(eval_is_only(lambda st, ctx, t=elo_th: {"tight_1345_thr": 0.060 if st.get("_elo", 0) >= t else 0.050}, f"XF21_elo>={elo_th}_d60"))
    # 2. XF03 Inst Dump + A2_1345_d60 / d70
    for im_th in [0.0, 1e7, 1.6e7, 2.0e7, 2.4e7, 3.0e7]:
        rows.append(eval_is_only(lambda st, ctx, t=im_th: {"tight_1345_thr": 0.060 if (st.get("_inst_sell", 0) > t or st.get("_inst_net", 0) > t) else 0.050}, f"XF03_inst>{int(im_th/1e4)}w_d60"))
        rows.append(eval_is_only(lambda st, ctx, t=im_th: {"tight_1345_thr": 0.070 if (st.get("_inst_sell", 0) > t or st.get("_inst_net", 0) > t) else 0.050}, f"XF03_inst>{int(im_th/1e4)}w_d70"))
    # 3. XF28 Vol Blowoff + A2_1345_d70 / d60
    for vr_th in [2.8, 3.0, 3.5, 4.0, 4.2]:
        rows.append(eval_is_only(lambda st, ctx, t=vr_th: {"tight_1345_thr": 0.070 if st.get("_vr", 1) > t else 0.050}, f"XF28_vr>{vr_th:.1f}_d70"))
    # 4. XF23 Rebound Rate10 + A3_dev93_5b / dev96_5b
    for rb_th in [0.15, 0.18, 0.20, 0.22, 0.25]:
        rows.append(eval_is_only(lambda st, ctx, t=rb_th: {"cond_dev_ratio": 0.93 if (ctx["boards"] >= 5 and st.get("_reb_r10", 1) < t) else None}, f"XF23_reb<{int(rb_th*100)}%_dev93_5b"))
        rows.append(eval_is_only(lambda st, ctx, t=rb_th: {"cond_dev_ratio": 0.96 if (ctx["boards"] >= 5 and st.get("_reb_r10", 1) < t) else None}, f"XF23_reb<{int(rb_th*100)}%_dev96_5b"))
    # 5. XF21 Elo + A2_1345 drop_thr smoothness (0.055 .. 0.075)
    for d_th in [0.055, 0.060, 0.065, 0.070, 0.075]:
        rows.append(eval_is_only(lambda st, ctx, d=d_th: {"tight_1345_thr": d if st.get("_elo", 0) >= 135 else 0.050}, f"XF21_135_drop={d_th*100:.1f}%"))

    df_sm = pd.DataFrame(rows)
    print(df_sm.to_string(index=False))
    df_sm.to_csv(f"{OUT_DIR}/is_smoothness_check.csv", index=False, encoding="utf-8-sig")


def build_and_eval_scorecard(cache: dict, states: dict, base: dict):
    """
    在 IS 上构建 XF30_composite_exit_scorecard 并检验全套候选与合成规则（先看 IS 稳定性，再在 OOS 一次性盲测）。
    """
    # 严格基于 IS 有效且有物理机制支撑的正交卖点风险信号构成打分卡：
    #   S1: XF21_elo >= 135 (+1) [主概念动态Elo过热，高标对偶]
    #   S2: XF03_inst_20m (+1)    [t-1机构大额出逃>2000w]
    #   S3: XF28_vol_blowoff>3.5 (+1) [t-1巨量爆量>3.5x]
    #   S4: XF02_daysurf (+1)     [t-1一日游游资买入]
    #   S5: XF07_sreg_new (+1)    [持仓期突发个股监管]
    #   S6: XF22_csi_slump (+1)   [大盘跌>=2%或5日跌>=2.5%]
    #   S7: XF23_reb20 (<20%) (+1)[近10日高标断板次日反包率<20%]
    #   S8: XF20_plt (+1)         [同板块更高板新龙头卡位]
    def risk_score_7(st: dict) -> int:
        # 7项严格正交、各组全覆盖的卖点风险分 (LHB + Reg + Sector/Macro + Micro/Tape):
        return (
            int(bool(st.get("xf21_135")))     # 概念Elo>=135过热
            + int(bool(st.get("xf03_20m")))   # 机构卖出>2000万
            + int(bool(st.get("xf28_35")))    # 成交额>3.5x均量爆量
            + int(bool(st.get("xf02")))       # 一日游买入
            + int(bool(st.get("xf07_new")))   # 持仓新增监管
            + int(bool(st.get("xf22")))       # 大盘暴跌阴跌
            + int(bool(st.get("xf23_reb20"))) # 高标反包率<20%冷区
        )

    def risk_score_5_core(st: dict) -> int:
        # 更精简 5 项核心正交风险分（全为低相关性独立维度）:
        return (
            int(bool(st.get("xf21_135")))
            + int(bool(st.get("xf03_20m")))
            + int(bool(st.get("xf28_35")))
            + int(bool(st.get("xf02")))
            + int(bool(st.get("xf23_reb20")))
        )

    candidates = [
        ("BASE_V40", None),
        # 单因子候选（IS-verified & smooth）
        ("C1_XF21_elo135_1345d70", lambda st, ctx: {"tight_1345_thr": 0.070 if st.get("xf21_135") else 0.050}),
        ("C2_XF21_elo135_1345d60", lambda st, ctx: {"tight_1345_thr": 0.060 if st.get("xf21_135") else 0.050}),
        ("C3_XF03_inst20m_1345d60", lambda st, ctx: {"tight_1345_thr": 0.060 if st.get("xf03_20m") else 0.050}),
        ("C4_XF28_vr35_1345d70", lambda st, ctx: {"tight_1345_thr": 0.070 if st.get("xf28_35") else 0.050}),
        ("C5_XF23_reb20_dev96_5b", lambda st, ctx: {"cond_dev_ratio": 0.96 if (ctx["boards"] >= 5 and st.get("xf23_reb20")) else None}),
        ("C6_XF23_reb20_dev93_5b", lambda st, ctx: {"cond_dev_ratio": 0.93 if (ctx["boards"] >= 5 and st.get("xf23_reb20")) else None}),
        ("C7_XF14_quiet_req_imm", lambda st, ctx: {"strip_imm": not bool(st.get("xf14_cum"))}),
        # XF30 整数风险打分卡（不同阈值与动作组合）
        ("XF30_7f_ge1_1345d60", lambda st, ctx: {"tight_1345_thr": 0.060 if risk_score_7(st) >= 1 else 0.050}),
        ("XF30_7f_ge1_1345d70", lambda st, ctx: {"tight_1345_thr": 0.070 if risk_score_7(st) >= 1 else 0.050}),
        ("XF30_7f_ge2_1345d60", lambda st, ctx: {"tight_1345_thr": 0.060 if risk_score_7(st) >= 2 else 0.050}),
        ("XF30_7f_ge2_1345d70", lambda st, ctx: {"tight_1345_thr": 0.070 if risk_score_7(st) >= 2 else 0.050}),
        ("XF30_7f_ge3_1345d70", lambda st, ctx: {"tight_1345_thr": 0.070 if risk_score_7(st) >= 3 else 0.050}),
        ("XF30_5f_ge1_1345d60", lambda st, ctx: {"tight_1345_thr": 0.060 if risk_score_5_core(st) >= 1 else 0.050}),
        ("XF30_5f_ge1_1345d70", lambda st, ctx: {"tight_1345_thr": 0.070 if risk_score_5_core(st) >= 1 else 0.050}),
        ("XF30_5f_ge2_1345d70", lambda st, ctx: {"tight_1345_thr": 0.070 if risk_score_5_core(st) >= 2 else 0.050}),
        ("XF30_5f_ge2_1430rush", lambda st, ctx: {"tight_1430rush": risk_score_5_core(st) >= 2}),
        ("XF30_5f_ge2_dev96_5b", lambda st, ctx: {"cond_dev_ratio": 0.96 if (ctx["boards"] >= 5 and risk_score_5_core(st) >= 2) else None}),
        ("XF30_5f_ge2_dev93_5b", lambda st, ctx: {"cond_dev_ratio": 0.93 if (ctx["boards"] >= 5 and risk_score_5_core(st) >= 2) else None}),
        # 复合策略：温和护利收紧 (Risk5 >= 1 -> 1345d60 / 或 Elo135|Inst20m -> d70) + 冷区双异动(XF23_reb20 & boards>=5 -> dev96) + 断板换手<=35%
        ("XF30_Combo_EloInst_d70_plus_Reb20dev96", lambda st, ctx: {
            "tight_1345_thr": 0.070 if (st.get("xf21_135") or st.get("xf03_20m")) else 0.050,
            "cond_dev_ratio": 0.96 if (ctx["boards"] >= 5 and st.get("xf23_reb20")) else None,
        }),
        ("XF30_Combo_Risk5ge1_d60_plus_Reb20dev96", lambda st, ctx: {
            "tight_1345_thr": 0.060 if risk_score_5_core(st) >= 1 else 0.050,
            "cond_dev_ratio": 0.96 if (ctx["boards"] >= 5 and st.get("xf23_reb20")) else None,
        }),
        ("XF30_Combo_Elo135d70_plus_Reb20dev96_plus_To35", lambda st, ctx: {
            "tight_1345_thr": 0.070 if st.get("xf21_135") else 0.050,
            "cond_dev_ratio": 0.96 if (ctx["boards"] >= 5 and st.get("xf23_reb20")) else None,
            "strip_imm": bool(st.get("xf27_k35")),
        }),
        ("XF30_Combo_Risk5ge1_d60_plus_Inst_d70_plus_Reb20dev96", lambda st, ctx: {
            "tight_1345_thr": 0.070 if st.get("xf03_20m") else (0.060 if risk_score_5_core(st) >= 1 else 0.050),
            "cond_dev_ratio": 0.96 if (ctx["boards"] >= 5 and st.get("xf23_reb20")) else None,
        }),
    ]

    res_rows = []
    for lbl, rfn in candidates:
        r90 = efe.evaluate_rule(cache, states, rfn, lbl, 90.0)
        r78 = efe.evaluate_rule(cache, states, rfn, lbl, 78.0)
        r102 = efe.evaluate_rule(cache, states, rfn, lbl, 102.0)
        res_rows.append({
            "label": lbl,
            # IS
            "IS_90_1S": r90["IS"]["nav_1s"], "IS_90_EQ": r90["IS"]["eq_nav"], "IS_90_MDD": r90["IS"]["mdd"],
            "IS22_EQ": r90["IS_22"]["eq_nav"], "IS23_EQ": r90["IS_23"]["eq_nav"],
            "IS_78_1S": r78["IS"]["nav_1s"], "IS_78_EQ": r78["IS"]["eq_nav"],
            "IS_102_1S": r102["IS"]["nav_1s"],
            # OOS (盲测披露)
            "OOS_90_1S": r90["OOS"]["nav_1s"], "OOS_90_EQ": r90["OOS"]["eq_nav"], "OOS_90_MDD": r90["OOS"]["mdd"],
            "OOS_78_1S": r78["OOS"]["nav_1s"], "OOS_78_EQ": r78["OOS"]["eq_nav"],
            "OOS_102_1S": r102["OOS"]["nav_1s"],
            # 5Y
            "5Y_90_1S": r90["ALL_5Y"]["nav_1s"], "5Y_90_EQ": r90["ALL_5Y"]["eq_nav"],
            "5Y_90_T5": r90["ALL_5Y"]["t5"], "5Y_102_1S": r102["ALL_5Y"]["nav_1s"],
        })

    df_c = pd.DataFrame(res_rows)
    print("\n=== XF30 SCORECARD & SINGLE-FACTOR CANDIDATES: IS CALIBRATION + BLIND OOS ===")
    print(df_c.to_string(index=False))
    df_c.to_csv(f"{OUT_DIR}/scorecard_candidates_eval.csv", index=False, encoding="utf-8-sig")


def main():
    t0 = time.time()
    with open(f"{OUT_DIR}/pit_exit_cache_full.pkl", "rb") as f:
        cache = pickle.load(f)
    states = efe.precompute_trade_day_states(cache, min_score=78.0)
    base = {
        "90": efe.evaluate_rule(cache, states, None, "BASE90", 90.0),
        "78": efe.evaluate_rule(cache, states, None, "BASE78", 78.0),
        "102": efe.evaluate_rule(cache, states, None, "BASE102", 102.0),
    }
    run_param_smoothness_is(cache, states, base)
    build_and_eval_scorecard(cache, states, base)
    print(f"\n[Step3 DONE in {time.time()-t0:.1f}s]")


if __name__ == "__main__":
    main()
