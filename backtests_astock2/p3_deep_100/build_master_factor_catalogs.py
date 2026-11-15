#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
build_master_factor_catalogs.py
将 Wave 1 全部 10+2 张因子回测表统一标准化、去重归类、核验数字，
生成两份高颗粒度全因子回测总表（CSV）与结构化摘要（JSON）：
  - master_4to5_all_factors_audit.csv
  - master_2to3_all_factors_audit.csv
  - master_catalogs_summary.json
"""
import json
import math
import os
import pandas as pd

ROOT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p3_deep_100"

STD_COLS = [
    "source_group",
    "factor_code",
    "factor_name",
    "buy_mode",
    "n_raw",
    "wr_pct",
    "payoff",
    "avg_net_ret_pct",
    "delta_vs_base_pct",
    "early_22_23_pct",
    "recent_24_26_pct",
    "dual_period_consistent",
    "ss_n",
    "ss_nav",
    "ss_ex_top3_nav",
    "verdict",
]

# 已知跨板位先验方向映射（用于精确标注「原板位正向/负向 -> 迁移后符号反转」）
HIGHDRAGON_PRIOR_DIR = {
    "F45_max_s_1y_ge5": "pos",
    "F45_max_s_3y_ge5": "pos",
    "F45_max_s_1y_ge4": "pos",
    "F45_pure_new_face_no4b": "neg",
    "F46_is_new_face": "neg",
    "F46_old_native_theme": "pos",
    "F46_old_fake_new_concept": "neg",
    "F47_reb_zt_r10_ge20": "pos",
    "F47_reb_zt_r10_ge15": "pos",
    "F47_reb_zt_r10_eq0": "neg",
    "F47_env_brk_dt_r10_ge20": "pos",
    "F47_env_brk_dt_r10_ge15": "pos",
    "F47_env_brk_dt_r10_eq0": "neg",
    "F48_mkt_zt_lt70": "pos",
    "F48_mkt_zt_30_65": "pos",
    "F48_mkt_zt_ge95": "neg",
    "F49_lock50_rfmcap_12_35": "pos",
    "F49_not_lock50_rfmcap_12_35": "neg",
    "F49_v51_lock45_or_rfmcap45": "pos",
    "F49_v51_fail": "neg",
    "F50_d2d3_top_yz_locked_d4": "pos",
    "F50_d4_top_yz_new_buy": "pos",
    "F50_top_yz_dump_d4": "neg",
    "F51_lhb_lh_cnt_eq0": "pos",
    "F51_lhb_lh_cnt_eq2": "neg",
    "F51_lhb_lh_cnt_ge3": "neg",
    "F51_lhb_lh_share_ge20": "neg",
    "F51_lhb_lh_cnt2_share20": "neg",
    "F52_d4_inst_buy_ge1": "pos",
    "F52_d4_inst_sell_ge1": "neg",
    "F_quant_buy_low_lh": "pos",
    "F_quant_sell_ge1": "neg",
    "F_d4_lhb_net_pos": "pos",
    "F_d4_lhb_net_le0": "neg",
    "F_d4_day_surf_buy": "neg",
    "F53_tech_hotword": "pos",
    "F53_non_tech": "neg",
    "F54_ex_reg5_ge2": "neg",
    "F54_ex_reg5_ge1": "neg",
    "F54_ex_reg5_eq0": "pos",
    "F_s_reg_10d": "neg",
    "F_tox_90d": "neg",
    "F_clean_no_reg_no_tox": "pos",
    "F55_fst_le_0935": "neg",
    "F55_fst_0936_1045": "pos",
    "F55_obc0_tight_ge35": "neg",
    "F56_csi_r5_lt_m25": "neg",
    "F65_green_dip_4d": "pos",
    "F65_greenhouse_all_red": "neg",
}

V18_1TO2_PRIOR_DIR = {
    "G1_01_is_plate_space_dragon": "pos",
    "G1_02_has_plate_3b_plus_bro": "neg",
    "G1_03_has_plate_4b_plus_bro": "neg",
    "G1_04_is_sole_plate_space_dragon": "pos",
    "G1_05_is_mkt_highest_2b": "pos",
    "G2_06_d2_rk_c_eq1": "pos",
    "G2_07_d2_rk_c_eq2": "pos",
    "G2_09_d2_rk_c_ge4_cold": "neg",
    "G2_10_d2_gap_c_ge20": "pos",
    "G2_14_d2_p_sz_8_to_15_wave": "pos",
    "G2_15_d2_p_sz_gt15": "neg",
    "G2_16_d2_p_sz_gt35_chaotic": "neg",
    "G2_17_d2_p_elo_ge105": "pos",
    "G2_18_d2_p_elo_ge110": "pos",
    "G2_19_d2_p_elo_ge115": "pos",
    "G2_20_d2_p_elo_le95_weak": "neg",
    "G2_21_d2_s_elo_ge105": "pos",
    "G2_22_d2_s_elo_le95_weak": "neg",
    "G2_23_d2_has_new_term": "pos",
    "G2_24_d2_own_new_term": "pos",
    "G2_25_d2_is_pioneer_word": "pos",
    "G2_26_d2_spark_bonus": "pos",
    "G2_27_d2_sub_cluster_ge2": "pos",
    "G2_28_d2_is_granularity": "pos",
    "G2_29_d2_is_tech_c": "pos",
    "G2_30_d2_is_ma": "pos",
    "G2_32_notice_hard": "pos",
    "G2_33_notice_ma": "pos",
    "G2_34_notice_bad": "neg",
    "G2_35_has_ir_8d": "pos",
    "G2_36_same_plate_d1_d2": "pos",
    "G3_38_is_event_basket": "neg",
    "G3_39_is_broad_ind": "neg",
    "G3_40_is_pure_outsider": "neg",
    "G3_41_is_dying_pulse_d1": "neg",
    "G3_42_is_dying_pulse_d2": "neg",
    "G3_43_dying_pulse_no_4b_escort": "neg",
    "G3_44_theme_age_1_2d_start": "pos",
    "G3_46_theme_age_5_8d_exhaust": "neg",
    "G4_47_rk_theme_le2_main": "pos",
    "G4_48_rk_theme_ge4_cold": "neg",
    "G4_49_Rule_alpha_blocked": "neg",
    "G4_50_Rule_beta_blocked": "neg",
    "G4_51_V18_Rule_3_penalized": "neg",
    "G4_52_Rule_gamma_cold": "neg",
    "G4_53_m_t2_channel": "pos",
}

B1_CN_NAMES = {
    "G1_01_is_plate_space_dragon": "题材内最高身位空间龙",
    "G1_02_has_plate_3b_plus_bro": "同题材有>=3板压制兄弟",
    "G1_03_has_plate_4b_plus_bro": "同题材有>=4板压制兄弟",
    "G1_04_is_sole_plate_space_dragon": "题材内唯一最高身位龙",
    "G1_05_is_mkt_highest_2b": "全场最高身位二板(无>=3板)",
    "G2_06_d2_rk_c_eq1": "Day2题材热度排名第1",
    "G2_07_d2_rk_c_eq2": "Day2题材热度排名第2",
    "G2_08_d2_rk_c_eq3": "Day2题材热度排名第3",
    "G2_09_d2_rk_c_ge4_cold": "Day2题材热度排名>=4(冷门)",
    "G2_10_d2_gap_c_ge20": "Day2题材热度断层领先>=20",
    "G2_11_d2_p_sz_eq1_lone": "Day2题材尺寸==1(独苗)",
    "G2_12_d2_p_sz_2_to_3": "Day2题材尺寸2~3家",
    "G2_13_d2_p_sz_4_to_7": "Day2题材尺寸4~7家",
    "G2_14_d2_p_sz_8_to_15_wave": "Day2题材尺寸8~15家(主升浪)",
    "G2_15_d2_p_sz_gt15": "Day2题材尺寸>15家(过热普涨)",
    "G2_16_d2_p_sz_gt35_chaotic": "Day2题材尺寸>35家(极度混沌)",
    "G2_17_d2_p_elo_ge105": "Day2主题材Elo>=105",
    "G2_18_d2_p_elo_ge110": "Day2主题材Elo>=110",
    "G2_19_d2_p_elo_ge115": "Day2主题材Elo>=115",
    "G2_20_d2_p_elo_le95_weak": "Day2主题材Elo<=95(弱势题材)",
    "G2_21_d2_s_elo_ge105": "Day2细分子题材Elo>=105",
    "G2_22_d2_s_elo_le95_weak": "Day2细分子题材Elo<=95(弱势)",
    "G2_23_d2_has_new_term": "Day2题材含新词发酵",
    "G2_24_d2_own_new_term": "Day2个股自带新词标签",
    "G2_25_d2_is_pioneer_word": "Day2新词先锋首创股",
    "G2_26_d2_spark_bonus": "Day2题材首次点火加分",
    "G2_27_d2_sub_cluster_ge2": "Day2细分分支聚集>=2家",
    "G2_28_d2_is_granularity": "Day2高颗粒度精准题材",
    "G2_29_d2_is_tech_c": "Day2科技成长主线题材",
    "G2_30_d2_is_ma": "Day2并购重组题材",
    "G2_31_d2_is_earn": "Day2业绩预增题材",
    "G2_32_notice_hard": "硬核重大资产/股权公告",
    "G2_33_notice_ma": "并购重组公告",
    "G2_34_notice_bad": "利空减持问询公告",
    "G2_35_has_ir_8d": "近8日机构调研IR",
    "G2_36_same_plate_d1_d2": "首板与二板同属一个题材",
    "G2_37_diff_plate_d1_d2_switch": "首板到二板题材切换",
    "G3_38_is_event_basket": "事件大杂烩篮子(伪题材)",
    "G3_39_is_broad_ind": "宽泛大行业(伪题材)",
    "G3_40_is_pure_outsider": "纯无题材散兵游勇",
    "G3_41_is_dying_pulse_d1": "首板老题材脉冲回光返照",
    "G3_42_is_dying_pulse_d2": "二板老题材脉冲回光返照",
    "G3_43_dying_pulse_no_4b_escort": "脉冲题材且无4板护盘",
    "G3_44_theme_age_1_2d_start": "题材发酵年龄1~2天(启动期)",
    "G3_45_theme_age_3_4d_mid": "题材发酵年龄3~4天(中继期)",
    "G3_46_theme_age_5_8d_exhaust": "题材发酵年龄5~8天(退潮期)",
    "G4_47_rk_theme_le2_main": "V18主线前2题材",
    "G4_48_rk_theme_ge4_cold": "V18排名>=4冷门题材",
    "G4_49_Rule_alpha_blocked": "被V18规则Alpha拦截(非前排弱势)",
    "G4_50_Rule_beta_blocked": "被V18规则Beta拦截(混战非前2)",
    "G4_51_V18_Rule_3_penalized": "被V18规则3惩罚(大题材后排)",
    "G4_52_Rule_gamma_cold": "被V18规则Gamma拦截(无主线冷门)",
    "G4_53_m_t2_channel": "V18独占M-T2独苗先锋通道",
}


def _clean_float(val, ndigits=2):
    if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
        return None
    if pd.isna(val):
        return None
    return round(float(val), ndigits)


def _clean_int(val):
    if val is None or pd.isna(val):
        return None
    return int(round(float(val)))


def classify_verdict(dual_ok: bool, delta_pct: float, n_raw: int, ss_nav, ss_ex_top3_nav) -> str:
    if not dual_ok:
        return "跨周期失效或反转"
    if delta_pct is None or delta_pct < 0:
        return "双期负向排雷"
    nav = 0.0 if ss_nav is None or pd.isna(ss_nav) else float(ss_nav)
    ex3 = 0.0 if ss_ex_top3_nav is None or pd.isna(ss_ex_top3_nav) else float(ss_ex_top3_nav)
    if n_raw >= 15 and (delta_pct >= 1.50 or (nav >= 1.00 and delta_pct >= 0.80) or (ex3 >= 0.50 and delta_pct >= 0.80)):
        return "双期正向王牌"
    return "双期正向辅助"


def sanitize_for_json(obj):
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj


def build_4to5_catalog():
    rows = []
    prior_map = {}  # factor_code -> (prior_stage, expected_dir, desc)

    # 1. a2_4to5_all_3to4_factors.csv -> 三进四V3.4迁移
    a2 = pd.read_csv(f"{ROOT_DIR}/a2_4to5_all_3to4_factors.csv")
    a2 = a2[a2["group"] != "00_BASE"].copy()
    for r in a2.itertuples(index=False):
        b_dual = bool(r.B_dual_same_sign)
        a_dual = bool(r.A_dual_same_sign)
        use_a = (not b_dual) and a_dual and int(r.A_n_raw) >= 10
        pfx = "A" if use_a else "B"
        buy_mode = "touch65_1130" if use_a else "open_925"
        n_raw = _clean_int(getattr(r, f"{pfx}_n_raw"))
        wr = _clean_float(getattr(r, f"{pfx}_wr_raw"))
        po = _clean_float(getattr(r, f"{pfx}_payoff_raw"))
        avg = _clean_float(getattr(r, f"{pfx}_avg_ret"))
        delta = _clean_float(getattr(r, f"{pfx}_delta_vs_base"))
        e_avg = _clean_float(getattr(r, f"{pfx}_early_22_23_avg"))
        r_avg = _clean_float(getattr(r, f"{pfx}_recent_24_26_avg"))
        dual = bool(getattr(r, f"{pfx}_dual_same_sign"))
        ss_n = _clean_int(getattr(r, f"{pfx}_ss_n"))
        ss_nav = _clean_float(getattr(r, f"{pfx}_ss_nav"), 3)
        ss_ex3 = _clean_float(getattr(r, f"{pfx}_ss_ex_top3_nav"), 3)
        fcode = f"A2_{r.factor_name.split(' ')[0]}"
        prior_map[fcode] = ("三进四V3.4", str(r.expected_dir), str(r.factor_name))
        rows.append({
            "source_group": "三进四V3.4迁移",
            "factor_code": fcode,
            "factor_name": str(r.factor_name),
            "buy_mode": buy_mode,
            "n_raw": n_raw,
            "wr_pct": wr,
            "payoff": po,
            "avg_net_ret_pct": avg,
            "delta_vs_base_pct": delta,
            "early_22_23_pct": e_avg,
            "recent_24_26_pct": r_avg,
            "dual_period_consistent": dual,
            "ss_n": ss_n,
            "ss_nav": ss_nav,
            "ss_ex_top3_nav": ss_ex3,
            "verdict": classify_verdict(dual, delta, n_raw, ss_nav, ss_ex3),
        })

    # 2. a3_4to5_all_highdragon_factors.csv -> 高标V5.1迁移
    a3 = pd.read_csv(f"{ROOT_DIR}/a3_4to5_all_highdragon_factors.csv")
    a3 = a3[a3["factor_group"] != "00_BASELINE"].copy()
    regime_order = ["open_all", "open_le5", "right_all", "right_le5"]
    regime_mode_label = {
        "open_all": "open_925_all",
        "open_le5": "open_925_le5",
        "right_all": "touch65_1130_all",
        "right_le5": "touch65_1130_le5",
    }
    for fname, grp in a3.groupby("factor_name", sort=False):
        by_reg = {row["regime"]: row for _, row in grp.iterrows()}
        chosen_reg = None
        for reg in regime_order:
            if reg in by_reg and bool(by_reg[reg]["dual_same_sign"]) and int(by_reg[reg]["n_raw"]) >= 10:
                chosen_reg = reg
                break
        if chosen_reg is None:
            chosen_reg = "open_all" if "open_all" in by_reg else list(by_reg.keys())[0]
        r = by_reg[chosen_reg]
        n_raw = _clean_int(r["n_raw"])
        delta = _clean_float(r["delta_vs_base"])
        dual = bool(r["dual_same_sign"])
        ss_nav = _clean_float(r["ss_nav"], 3)
        ss_ex3 = _clean_float(r["ss_ex_top3_nav"], 3)
        fcode = f"A3_{fname}"
        if fname in HIGHDRAGON_PRIOR_DIR:
            prior_map[fcode] = ("高标首阴V5.1", HIGHDRAGON_PRIOR_DIR[fname], f"{fname} ({r['factor_desc']})")
        rows.append({
            "source_group": "高标V5.1迁移",
            "factor_code": fcode,
            "factor_name": f"{fname}: {r['factor_desc']}",
            "buy_mode": regime_mode_label.get(chosen_reg, chosen_reg),
            "n_raw": n_raw,
            "wr_pct": _clean_float(r["wr_raw"]),
            "payoff": _clean_float(r["payoff_raw"]),
            "avg_net_ret_pct": _clean_float(r["avg_ret"]),
            "delta_vs_base_pct": delta,
            "early_22_23_pct": _clean_float(r["early_22_23_avg"]),
            "recent_24_26_pct": _clean_float(r["recent_24_26_avg"]),
            "dual_period_consistent": dual,
            "ss_n": _clean_int(r["ss_n"]),
            "ss_nav": ss_nav,
            "ss_ex_top3_nav": ss_ex3,
            "verdict": classify_verdict(dual, delta, n_raw, ss_nav, ss_ex3),
        })

    # 3. a4_4to5_left_leakage_F35_F44.csv -> PM衔接F35_F68
    a4 = pd.read_csv(f"{ROOT_DIR}/a4_4to5_left_leakage_F35_F44.csv")
    a4 = a4[a4["slice_name"] != "基准全池"].copy()
    for idx, ((fid, sname), grp) in enumerate(a4.groupby(["factor_id", "slice_name"], sort=False), 1):
        by_mode = {row["buy_mode"]: row for _, row in grp.iterrows()}
        if "open_925" in by_mode and bool(by_mode["open_925"]["dual_same_sign"]) and int(by_mode["open_925"]["n_raw"]) >= 10:
            chosen = by_mode["open_925"]
        elif "touch65_1130" in by_mode and bool(by_mode["touch65_1130"]["dual_same_sign"]) and int(by_mode["touch65_1130"]["n_raw"]) >= 10:
            chosen = by_mode["touch65_1130"]
        else:
            chosen = by_mode.get("open_925", list(by_mode.values())[0])
        n_raw = _clean_int(chosen["n_raw"])
        delta = _clean_float(chosen["delta_vs_base"])
        dual = bool(chosen["dual_same_sign"])
        ss_nav = _clean_float(chosen["ss_nav"], 3)
        ss_ex3 = _clean_float(chosen["ss_ex_top3_nav"], 3)
        fcode = f"A4_{fid}_{idx:02d}"
        rows.append({
            "source_group": "PM衔接F35_F68",
            "factor_code": fcode,
            "factor_name": f"{chosen['factor_name']} | {sname}",
            "buy_mode": str(chosen["buy_mode"]),
            "n_raw": n_raw,
            "wr_pct": _clean_float(chosen["wr_raw"]),
            "payoff": _clean_float(chosen["payoff_raw"]),
            "avg_net_ret_pct": _clean_float(chosen["avg_ret"]),
            "delta_vs_base_pct": delta,
            "early_22_23_pct": _clean_float(chosen["early_22_23_avg"]),
            "recent_24_26_pct": _clean_float(chosen["recent_24_26_avg"]),
            "dual_period_consistent": dual,
            "ss_n": _clean_int(chosen["ss_n"]),
            "ss_nav": ss_nav,
            "ss_ex_top3_nav": ss_ex3,
            "verdict": classify_verdict(dual, delta, n_raw, ss_nav, ss_ex3),
        })

    # 4. a1_4to5_exec_and_interlock_F57_F68.csv -> PM衔接F35_F68 (剔除与EXEC_MATRIX完全重复的12条冗余行)
    a1 = pd.read_csv(f"{ROOT_DIR}/a1_4to5_exec_and_interlock_F57_F68.csv")
    a1_dup_ids = {
        "F59_B1_open_all",
        "F60_B2_underwater_dip",
        "F59_B3_pm_f59_1030",
        "F59_B4_pm_wide_1130",
        "F59_B5_3to4_touch65_1130",
        "F59_B6_auc_sweet_2_7",
        "F61_E1_cutweak_all",
        "F61_E4_handoff_all",
        "F62_E1_3to4_std",
        "F62_E2_dev93_always",
        "F62_E3_staged_dev93",
        "F68_all_universe",
    }
    a1 = a1[~a1["factor_id"].isin(a1_dup_ids)].copy()
    for r in a1.itertuples(index=False):
        fid = str(r.factor_id)
        if fid.startswith("MATRIX_"):
            bmode = fid.replace("MATRIX_", "")
        elif r.category in ("F57_HEADROOM_10D", "F58_DOUBLE_HEADROOM"):
            bmode = "B3_pm1030_" + ("E3_staged" if fid.endswith("E3_staged") else "E1_std")
        else:
            bmode = "B3_pm1030_E3_staged"
        n_raw = _clean_int(r.n_raw)
        delta = _clean_float(r.delta_vs_base)
        dual = bool(r.dual_same_sign)
        ss_nav = _clean_float(r.ss_nav, 3)
        ss_ex3 = _clean_float(r.ss_ex_top3_nav, 3)
        rows.append({
            "source_group": "PM衔接F35_F68",
            "factor_code": f"A1_{fid}",
            "factor_name": str(r.factor_desc),
            "buy_mode": bmode,
            "n_raw": n_raw,
            "wr_pct": _clean_float(r.wr_raw),
            "payoff": _clean_float(r.payoff_raw),
            "avg_net_ret_pct": _clean_float(r.avg_ret),
            "delta_vs_base_pct": delta,
            "early_22_23_pct": _clean_float(r.early_22_23_avg),
            "recent_24_26_pct": _clean_float(r.recent_24_26_avg),
            "dual_period_consistent": dual,
            "ss_n": _clean_int(r.ss_n),
            "ss_nav": ss_nav,
            "ss_ex_top3_nav": ss_ex3,
            "verdict": classify_verdict(dual, delta, n_raw, ss_nav, ss_ex3),
        })

    # 5. a5_4to5_all125_quantiles.csv -> 全列分位与二维交互
    with open(f"{ROOT_DIR}/a5_summary.json", encoding="utf-8") as fp:
        a5_sum = json.load(fp)
    base_open_45 = float(a5_sum["baseline_ret_open_v34"]["all"]["avg_ret"])
    base_t65_45 = float(a5_sum["baseline_ret_t65_v34"]["all"]["avg_ret"])

    a5q = pd.read_csv(f"{ROOT_DIR}/a5_4to5_all125_quantiles.csv")
    for feat, grp in a5q.groupby("feature", sort=False):
        by_m = {row["mode"]: row for _, row in grp.iterrows()}
        if "ret_open_v34" in by_m and bool(by_m["ret_open_v34"]["dual_same_sign"]):
            chosen = by_m["ret_open_v34"]
        elif "ret_t65_v34" in by_m and bool(by_m["ret_t65_v34"]["dual_same_sign"]):
            chosen = by_m["ret_t65_v34"]
        else:
            chosen = by_m.get("ret_open_v34", list(by_m.values())[0])
        mode_k = str(chosen["mode"])
        base_m = base_open_45 if mode_k == "ret_open_v34" else base_t65_45
        bside = str(chosen["best_side"])
        if bside in ("Q1", "False"):
            best_avg = float(chosen["avg_q1_or_false"])
            e_sp = -float(chosen["spread_22_23"])
            r_sp = -float(chosen["spread_24_26"])
        else:
            best_avg = float(chosen["avg_q5_or_true"])
            e_sp = float(chosen["spread_22_23"])
            r_sp = float(chosen["spread_24_26"])
        delta = round(best_avg - base_m, 2)
        n_raw = _clean_int(chosen["best_n_raw"])
        dual = bool(chosen["dual_same_sign"])
        ss_nav = _clean_float(chosen["best_ss_nav"], 3)
        ss_ex3 = _clean_float(chosen["best_ss_ex_top3_nav"], 3)
        rows.append({
            "source_group": "全列分位与二维交互",
            "factor_code": f"A5Q_{feat}",
            "factor_name": f"单调分位 {feat} [优势端:{bside}]",
            "buy_mode": "open_925" if mode_k == "ret_open_v34" else "touch65_1130",
            "n_raw": n_raw,
            "wr_pct": _clean_float(chosen["best_wr_raw"]),
            "payoff": _clean_float(chosen["best_payoff_raw"]),
            "avg_net_ret_pct": _clean_float(best_avg),
            "delta_vs_base_pct": delta,
            "early_22_23_pct": _clean_float(e_sp),
            "recent_24_26_pct": _clean_float(r_sp),
            "dual_period_consistent": dual,
            "ss_n": _clean_int(chosen["best_ss_n"]),
            "ss_nav": ss_nav,
            "ss_ex_top3_nav": ss_ex3,
            "verdict": classify_verdict(dual, delta, n_raw, ss_nav, ss_ex3),
        })

    # 6. a5_4to5_2way_interactions.csv -> 全列分位与二维交互
    base_e_open = float(a5_sum["baseline_ret_open_v34"]["early"]["ss_nav"])
    base_r_open = float(a5_sum["baseline_ret_open_v34"]["recent"]["ss_nav"])
    base_e_t65 = float(a5_sum["baseline_ret_t65_v34"]["early"]["ss_nav"])
    base_r_t65 = float(a5_sum["baseline_ret_t65_v34"]["recent"]["ss_nav"])

    a5i = pd.read_csv(f"{ROOT_DIR}/a5_4to5_2way_interactions.csv")
    for iid, grp in a5i.groupby("interaction_id", sort=False):
        by_m = {row["mode"]: row for _, row in grp.iterrows()}
        def _i_dual(row, mk):
            be = base_e_open if mk == "ret_open_v34" else base_e_t65
            br = base_r_open if mk == "ret_open_v34" else base_r_t65
            d = float(row["delta_vs_base"])
            en = float(row["e_ss_nav"])
            rn = float(row["r_ss_nav"])
            if d > 0:
                return bool(en > be and rn > br and int(row["e_n_raw"]) >= 3 and int(row["r_n_raw"]) >= 3)
            return bool(en < be and rn < br and int(row["e_n_raw"]) >= 3 and int(row["r_n_raw"]) >= 3)

        if "ret_open_v34" in by_m and (_i_dual(by_m["ret_open_v34"], "ret_open_v34") and float(by_m["ret_open_v34"]["ss_ex_top3_nav"]) >= float(by_m.get("ret_t65_v34", by_m["ret_open_v34"])["ss_ex_top3_nav"])):
            chosen = by_m["ret_open_v34"]
        elif "ret_t65_v34" in by_m and float(by_m["ret_t65_v34"]["ss_nav"]) > float(by_m["ret_open_v34"]["ss_nav"]) and _i_dual(by_m["ret_t65_v34"], "ret_t65_v34"):
            chosen = by_m["ret_t65_v34"]
        else:
            chosen = by_m.get("ret_open_v34", list(by_m.values())[0])
        mk = str(chosen["mode"])
        dual = _i_dual(chosen, mk)
        n_raw = _clean_int(chosen["n_raw"])
        delta = _clean_float(chosen["delta_vs_base"])
        ss_nav = _clean_float(chosen["ss_nav"], 3)
        ss_ex3 = _clean_float(chosen["ss_ex_top3_nav"], 3)
        rows.append({
            "source_group": "全列分位与二维交互",
            "factor_code": f"A5I_{iid}",
            "factor_name": f"二维交互 {chosen['desc']}",
            "buy_mode": "open_925" if mk == "ret_open_v34" else "touch65_1130",
            "n_raw": n_raw,
            "wr_pct": _clean_float(chosen["wr_raw"]),
            "payoff": _clean_float(chosen["payoff_raw"]),
            "avg_net_ret_pct": _clean_float(chosen["avg_ret"]),
            "delta_vs_base_pct": delta,
            "early_22_23_pct": None,
            "recent_24_26_pct": None,
            "dual_period_consistent": dual,
            "ss_n": _clean_int(chosen["ss_n"]),
            "ss_nav": ss_nav,
            "ss_ex_top3_nav": ss_ex3,
            "verdict": classify_verdict(dual, delta, n_raw, ss_nav, ss_ex3),
        })

    df_out = pd.DataFrame(rows, columns=STD_COLS)
    return df_out, prior_map


def build_2to3_catalog():
    rows = []
    prior_map = {}

    # 1. b1_2to3_v18_theme_core_factors.csv + b1_summary.json -> 一进二V18题材核心
    b1_df = pd.read_csv(f"{ROOT_DIR}/b1_2to3_v18_theme_core_factors.csv")
    with open(f"{ROOT_DIR}/b1_summary.json", encoding="utf-8") as fp:
        b1_json = json.load(fp)["factors"]
    traj_order = [
        ("traj2_raw", "open_925_full"),
        ("traj2_skel", "open_925_skel"),
        ("traj1_raw", "touch65_1130_full"),
        ("traj1_skel", "touch65_1130_skel"),
    ]
    for fac in b1_df["factor"]:
        fdata = b1_json[fac]
        chosen_k, chosen_label = None, None
        for tk, tlab in traj_order:
            d_tk = fdata[tk]
            if bool(d_tk["dual_same_sign"]) and int(d_tk["n_raw"]) >= 10:
                chosen_k, chosen_label = tk, tlab
                break
        if chosen_k is None:
            chosen_k, chosen_label = "traj2_raw", "open_925_full"
        m = fdata[chosen_k]
        n_raw = _clean_int(m["n_raw"])
        delta = _clean_float(m["delta_vs_base"])
        dual = bool(m["dual_same_sign"])
        ss_nav = _clean_float(m["ss_nav"], 3)
        ss_ex3 = _clean_float(m["ss_ex_top3_nav"], 3)
        fcode = f"B1_{fac}"
        cn = B1_CN_NAMES.get(fac, fac)
        if fac in V18_1TO2_PRIOR_DIR:
            prior_map[fcode] = ("一进二V18题材核心", V18_1TO2_PRIOR_DIR[fac], f"{fac} ({cn})")
        rows.append({
            "source_group": "一进二V18题材核心",
            "factor_code": fcode,
            "factor_name": f"{fac}: {cn}",
            "buy_mode": chosen_label,
            "n_raw": n_raw,
            "wr_pct": _clean_float(m["wr_raw"]),
            "payoff": _clean_float(m["payoff_raw"]),
            "avg_net_ret_pct": _clean_float(m["avg_ret"]),
            "delta_vs_base_pct": delta,
            "early_22_23_pct": _clean_float(m["early_22_23_avg"]),
            "recent_24_26_pct": _clean_float(m["recent_24_26_avg"]),
            "dual_period_consistent": dual,
            "ss_n": _clean_int(m["ss_n"]),
            "ss_nav": ss_nav,
            "ss_ex_top3_nav": ss_ex3,
            "verdict": classify_verdict(dual, delta, n_raw, ss_nav, ss_ex3),
        })

    # 2. b2_2to3_rank_yizi_chip_factors.csv -> 一进二V18排名与筹码
    b2 = pd.read_csv(f"{ROOT_DIR}/b2_2to3_rank_yizi_chip_factors.csv")
    b2_modes = [
        ("B_full", "open_925_full"),
        ("B_rk1", "open_925_rk1_skel"),
        ("A_full", "dyn65_12_full"),
        ("A_rk1", "dyn65_12_rk1_skel"),
    ]
    for idx, r in enumerate(b2.itertuples(index=False), 1):
        chosen_pfx, chosen_label = None, None
        for pfx, mlab in b2_modes:
            if bool(getattr(r, f"{pfx}_dual_same_sign")) and int(getattr(r, f"{pfx}_n_raw")) >= 10:
                chosen_pfx, chosen_label = pfx, mlab
                break
        if chosen_pfx is None:
            chosen_pfx, chosen_label = "B_full", "open_925_full"
        n_raw = _clean_int(getattr(r, f"{chosen_pfx}_n_raw"))
        delta = _clean_float(getattr(r, f"{chosen_pfx}_delta_vs_base"))
        dual = bool(getattr(r, f"{chosen_pfx}_dual_same_sign"))
        ss_nav = _clean_float(getattr(r, f"{chosen_pfx}_ss_nav"), 3)
        ss_ex3 = _clean_float(getattr(r, f"{chosen_pfx}_ss_ex_top3_nav"), 3)
        fcode = f"B2_{str(r.factor).split('_')[0]}_{idx:02d}"
        rows.append({
            "source_group": "一进二V18排名与筹码",
            "factor_code": fcode,
            "factor_name": str(r.factor),
            "buy_mode": chosen_label,
            "n_raw": n_raw,
            "wr_pct": _clean_float(getattr(r, f"{chosen_pfx}_wr_raw")),
            "payoff": _clean_float(getattr(r, f"{chosen_pfx}_payoff_raw")),
            "avg_net_ret_pct": _clean_float(getattr(r, f"{chosen_pfx}_avg_ret")),
            "delta_vs_base_pct": delta,
            "early_22_23_pct": _clean_float(getattr(r, f"{chosen_pfx}_early_22_23_avg")),
            "recent_24_26_pct": _clean_float(getattr(r, f"{chosen_pfx}_recent_24_26_avg")),
            "dual_period_consistent": dual,
            "ss_n": _clean_int(getattr(r, f"{chosen_pfx}_ss_n")),
            "ss_nav": ss_nav,
            "ss_ex_top3_nav": ss_ex3,
            "verdict": classify_verdict(dual, delta, n_raw, ss_nav, ss_ex3),
        })

    # 3. b3_2to3_left_leakage_and_knives_F01_F18.csv -> PM左端漏网与避飞刀F01_F18
    b3 = pd.read_csv(f"{ROOT_DIR}/b3_2to3_left_leakage_and_knives_F01_F18.csv")
    b3 = b3[~b3["factor_id"].isin(["BASE_Touch65", "F01_all"])].copy()
    for fid, grp in b3.groupby("factor_id", sort=False):
        by_m = {row["buy_mode"]: row for _, row in grp.iterrows()}
        if "open0925_pm1345_yang" in by_m and bool(by_m["open0925_pm1345_yang"]["dual_same_sign"]) and int(by_m["open0925_pm1345_yang"]["n_raw"]) >= 10:
            chosen = by_m["open0925_pm1345_yang"]
        elif "touch65_1130_pm1345_yang" in by_m and bool(by_m["touch65_1130_pm1345_yang"]["dual_same_sign"]) and int(by_m["touch65_1130_pm1345_yang"]["n_raw"]) >= 10:
            chosen = by_m["touch65_1130_pm1345_yang"]
        else:
            chosen = by_m.get("open0925_pm1345_yang", list(by_m.values())[0])
        n_raw = _clean_int(chosen["n_raw"])
        delta = _clean_float(chosen["delta_vs_base"])
        dual = bool(chosen["dual_same_sign"])
        ss_nav = _clean_float(chosen["ss_nav"], 3)
        ss_ex3 = _clean_float(chosen["ss_ex_top3_nav"], 3)
        rows.append({
            "source_group": "PM左端漏网与避飞刀F01_F18",
            "factor_code": f"B3_{fid}",
            "factor_name": str(chosen["factor_name"]),
            "buy_mode": str(chosen["buy_mode"]),
            "n_raw": n_raw,
            "wr_pct": _clean_float(chosen["wr_raw"]),
            "payoff": _clean_float(chosen["payoff_raw"]),
            "avg_net_ret_pct": _clean_float(chosen["avg_ret"]),
            "delta_vs_base_pct": delta,
            "early_22_23_pct": _clean_float(chosen["early_22_23_avg"]),
            "recent_24_26_pct": _clean_float(chosen["recent_24_26_avg"]),
            "dual_period_consistent": dual,
            "ss_n": _clean_int(chosen["ss_n"]),
            "ss_nav": ss_nav,
            "ss_ex_top3_nav": ss_ex3,
            "verdict": classify_verdict(dual, delta, n_raw, ss_nav, ss_ex3),
        })

    # 4. b4_2to3_right_genes_and_handoff_F19_F34.csv -> PM右端基因与交接F19_F34
    b4 = pd.read_csv(f"{ROOT_DIR}/b4_2to3_right_genes_and_handoff_F19_F34.csv")
    b4 = b4[b4["factor_id"] != "BASE"].copy()
    # 剔除与 F29 B1_open 完全重复的 F30 C1_f30_pm (sc>=100/108) 与 F31 0_全量二进三 (sc>=100/108)
    dup_mask = (
        ((b4["factor_id"] == "F30") & (b4["slice"] == "C1_f30_pm") & (b4["factor_name"].str.contains("sc>=")))
        | ((b4["factor_id"] == "F31") & (b4["slice"] == "0_全量二进三(不设空仓门)"))
    )
    b4 = b4[~dup_mask].copy()
    for idx, r in enumerate(b4.itertuples(index=False), 1):
        n_raw = _clean_int(r.n_raw)
        delta = _clean_float(r.delta_vs_base)
        dual = bool(r.dual_same_sign)
        ss_nav = _clean_float(r.ss_nav, 3)
        ss_ex3 = _clean_float(r.ss_ex_top3_nav, 3)
        bmode = str(r.slice) if r.factor_id == "F29" else (f"open0925+{r.slice}" if r.factor_id == "F30" else "open0925_f30")
        rows.append({
            "source_group": "PM右端基因与交接F19_F34",
            "factor_code": f"B4_{r.factor_id}_{idx:02d}",
            "factor_name": f"{r.factor_name} | {r.slice}",
            "buy_mode": bmode,
            "n_raw": n_raw,
            "wr_pct": _clean_float(r.wr_raw),
            "payoff": _clean_float(r.payoff_raw),
            "avg_net_ret_pct": _clean_float(r.avg_ret),
            "delta_vs_base_pct": delta,
            "early_22_23_pct": _clean_float(r.early_22_23_avg),
            "recent_24_26_pct": _clean_float(r.recent_24_26_avg),
            "dual_period_consistent": dual,
            "ss_n": _clean_int(r.ss_n),
            "ss_nav": ss_nav,
            "ss_ex_top3_nav": ss_ex3,
            "verdict": classify_verdict(dual, delta, n_raw, ss_nav, ss_ex3),
        })

    # 5. b5_2to3_all_cols_quantiles.csv -> 全列分位与龙头二维交互
    with open(f"{ROOT_DIR}/b5_summary.json", encoding="utf-8") as fp:
        b5_sum = json.load(fp)
    base_auc_23 = float(b5_sum["baselines"]["ret_auc_f30"]["avg_ret"])
    base_ign_23 = float(b5_sum["baselines"]["ret_ign_f30"]["avg_ret"])

    b5q = pd.read_csv(f"{ROOT_DIR}/b5_2to3_all_cols_quantiles.csv")
    b5q = b5q[b5q["bin_type"] != "constant"].copy()
    for r in b5q.itertuples(index=False):
        auc_dual = bool(r.auc_dual_same_sign)
        ign_dual = bool(r.ign_dual_same_sign)
        use_ign = (not auc_dual) and ign_dual
        pfx = "ign" if use_ign else "auc"
        base_m = base_ign_23 if use_ign else base_auc_23
        q1_pct = float(getattr(r, f"{pfx}_q1_pct"))
        q5_pct = float(getattr(r, f"{pfx}_q5_pct"))
        q1_n = int(getattr(r, f"{pfx}_q1_n"))
        q5_n = int(getattr(r, f"{pfx}_q5_n"))
        e_diff = getattr(r, f"{pfx}_early_22_23_diff_pct")
        r_diff = getattr(r, f"{pfx}_recent_24_26_diff_pct")
        if q5_pct >= q1_pct:
            side_desc = f"Q5={r.q5_range}"
            n_raw = q5_n
            best_avg = q5_pct
            e_sp = _clean_float(e_diff)
            r_sp = _clean_float(r_diff)
        else:
            side_desc = f"Q1={r.q1_range}"
            n_raw = q1_n
            best_avg = q1_pct
            e_sp = _clean_float(-e_diff) if pd.notna(e_diff) else None
            r_sp = _clean_float(-r_diff) if pd.notna(r_diff) else None
        delta = round(best_avg - base_m, 2)
        dual = bool(getattr(r, f"{pfx}_dual_same_sign"))
        rows.append({
            "source_group": "全列分位与龙头二维交互",
            "factor_code": f"B5Q_{r.feature}",
            "factor_name": f"单调分位 {r.feature} [优势端:{side_desc}]",
            "buy_mode": "dyn65_12_f30" if use_ign else "open_925_f30",
            "n_raw": n_raw,
            "wr_pct": None,
            "payoff": None,
            "avg_net_ret_pct": _clean_float(best_avg),
            "delta_vs_base_pct": delta,
            "early_22_23_pct": e_sp,
            "recent_24_26_pct": r_sp,
            "dual_period_consistent": dual,
            "ss_n": None,
            "ss_nav": None,
            "ss_ex_top3_nav": None,
            "verdict": classify_verdict(dual, delta, n_raw, None, None),
        })

    # 6. b5_2to3_dragon_interactions.csv -> 全列分位与龙头二维交互
    b5i = pd.read_csv(f"{ROOT_DIR}/b5_2to3_dragon_interactions.csv")
    for idx, r in enumerate(b5i.itertuples(index=False), 1):
        auc_dual = bool(r.auc_dual_same_sign)
        ign_dual = bool(r.ign_dual_same_sign)
        use_ign = (not auc_dual) and ign_dual
        pfx = "ign" if use_ign else "auc"
        n_raw = _clean_int(getattr(r, f"{pfx}_n_raw"))
        delta = _clean_float(getattr(r, f"{pfx}_delta_vs_base"))
        dual = bool(getattr(r, f"{pfx}_dual_same_sign"))
        ss_nav = _clean_float(getattr(r, f"{pfx}_ss_nav"), 3)
        ss_ex3 = _clean_float(getattr(r, f"{pfx}_ss_ex_top3_nav"), 3)
        icode = str(r.interaction_name).split("_")[0]
        rows.append({
            "source_group": "全列分位与龙头二维交互",
            "factor_code": f"B5I_{icode}_{idx:02d}",
            "factor_name": f"龙头交互 {r.interaction_name}",
            "buy_mode": "dyn65_12_f30" if use_ign else "open_925_f30",
            "n_raw": n_raw,
            "wr_pct": _clean_float(getattr(r, f"{pfx}_wr_raw")),
            "payoff": _clean_float(getattr(r, f"{pfx}_payoff_raw")),
            "avg_net_ret_pct": _clean_float(getattr(r, f"{pfx}_avg_ret")),
            "delta_vs_base_pct": delta,
            "early_22_23_pct": _clean_float(getattr(r, f"{pfx}_early_22_23_avg")),
            "recent_24_26_pct": _clean_float(getattr(r, f"{pfx}_recent_24_26_avg")),
            "dual_period_consistent": dual,
            "ss_n": _clean_int(getattr(r, f"{pfx}_ss_n")),
            "ss_nav": ss_nav,
            "ss_ex_top3_nav": ss_ex3,
            "verdict": classify_verdict(dual, delta, n_raw, ss_nav, ss_ex3),
        })

    df_out = pd.DataFrame(rows, columns=STD_COLS)
    return df_out, prior_map


def summarize_4to5(df45: pd.DataFrame, prior_map: dict) -> dict:
    vc = df45["verdict"].value_counts().to_dict()
    sg_vc = df45.groupby("source_group")["verdict"].value_counts().unstack(fill_value=0).to_dict(orient="index")

    # 跨板位迁移对比 (三进四V3.4 + 高标V5.1 -> 四进五)
    mig_df = df45[df45["factor_code"].isin(prior_map.keys())].copy()
    rev_cases = []
    cross_stage_invalid_or_rev_cnt = 0
    for r in mig_df.itertuples(index=False):
        stage, exp_dir, desc = prior_map[r.factor_code]
        if exp_dir not in ("pos", "neg"):
            continue
        delta = float(r.delta_vs_base_pct)
        dual = bool(r.dual_period_consistent)
        is_sign_rev = (exp_dir == "pos" and delta < 0) or (exp_dir == "neg" and delta > 0)
        if is_sign_rev or (not dual):
            cross_stage_invalid_or_rev_cnt += 1
        if is_sign_rev and dual:
            rev_cases.append({
                "factor_code": r.factor_code,
                "factor_name": r.factor_name,
                "origin_stage": stage,
                "origin_expected_dir": "正向增强" if exp_dir == "pos" else "负向排雷",
                "new_stage_dir": "正向" if delta > 0 else "负向",
                "buy_mode": r.buy_mode,
                "n_raw": int(r.n_raw),
                "delta_vs_base_pct": float(r.delta_vs_base_pct),
                "early_22_23_pct": r.early_22_23_pct,
                "recent_24_26_pct": r.recent_24_26_pct,
                "ss_nav": r.ss_nav,
            })

    rev_cases.sort(key=lambda x: abs(x["delta_vs_base_pct"]), reverse=True)

    pos_pool = df45[(df45["dual_period_consistent"]) & (df45["delta_vs_base_pct"] > 0) & (df45["n_raw"] >= 15)].copy()
    pos_pool = pos_pool.sort_values(["delta_vs_base_pct", "ss_nav"], ascending=[False, False])
    neg_pool = df45[(df45["dual_period_consistent"]) & (df45["delta_vs_base_pct"] < 0) & (df45["n_raw"] >= 15)].copy()
    neg_pool = neg_pool.sort_values(["delta_vs_base_pct", "wr_pct"], ascending=[True, True])

    cols_brief = [
        "source_group", "factor_code", "factor_name", "buy_mode", "n_raw", "wr_pct",
        "avg_net_ret_pct", "delta_vs_base_pct", "early_22_23_pct", "recent_24_26_pct",
        "ss_nav", "ss_ex_top3_nav", "verdict",
    ]
    return {
        "total_factors_audited": int(len(df45)),
        "verdict_counts": {
            "双期正向王牌": int(vc.get("双期正向王牌", 0)),
            "双期正向辅助": int(vc.get("双期正向辅助", 0)),
            "双期负向排雷": int(vc.get("双期负向排雷", 0)),
            "跨周期失效或反转": int(vc.get("跨周期失效或反转", 0)),
        },
        "dual_positive_total": int(vc.get("双期正向王牌", 0) + vc.get("双期正向辅助", 0)),
        "dual_negative_veto_total": int(vc.get("双期负向排雷", 0)),
        "cross_period_unstable_total": int(vc.get("跨周期失效或反转", 0)),
        "migrated_from_3to4_and_highdragon_tested_with_prior": int(sum(1 for fc in mig_df["factor_code"] if prior_map[fc][1] in ("pos", "neg"))),
        "migrated_invalid_or_reversed_count": int(cross_stage_invalid_or_rev_cnt),
        "migrated_dual_consistent_sign_reversal_count": int(len(rev_cases)),
        "source_group_breakdown": sg_vc,
        "top10_positive": pos_pool.head(10)[cols_brief].to_dict(orient="records"),
        "top10_negative_veto": neg_pool.head(10)[cols_brief].to_dict(orient="records"),
        "top8_cross_stage_reversals": rev_cases[:8],
    }


def summarize_2to3(df23: pd.DataFrame, prior_map: dict) -> dict:
    vc = df23["verdict"].value_counts().to_dict()
    sg_vc = df23.groupby("source_group")["verdict"].value_counts().unstack(fill_value=0).to_dict(orient="index")

    # 一进二V18题材因子 (B1 53个核心题材/规则因子 + B2 85个排名/一字/筹码切片)
    b1_sub = df23[df23["source_group"] == "一进二V18题材核心"]
    b1_b2_sub = df23[df23["source_group"].isin(["一进二V18题材核心", "一进二V18排名与筹码"])]
    b1_effective_dual_pos = int(((b1_sub["dual_period_consistent"]) & (b1_sub["delta_vs_base_pct"] > 0)).sum())
    b1_effective_dual_neg_veto = int(((b1_sub["dual_period_consistent"]) & (b1_sub["delta_vs_base_pct"] < 0)).sum())
    b1_b2_effective_dual_pos = int(((b1_b2_sub["dual_period_consistent"]) & (b1_b2_sub["delta_vs_base_pct"] > 0)).sum())
    b1_b2_effective_dual_neg = int(((b1_b2_sub["dual_period_consistent"]) & (b1_b2_sub["delta_vs_base_pct"] < 0)).sum())

    mig_df = df23[df23["factor_code"].isin(prior_map.keys())].copy()
    rev_cases = []
    invalid_or_rev_cnt = 0
    for r in mig_df.itertuples(index=False):
        stage, exp_dir, desc = prior_map[r.factor_code]
        delta = float(r.delta_vs_base_pct)
        dual = bool(r.dual_period_consistent)
        is_sign_rev = (exp_dir == "pos" and delta < 0) or (exp_dir == "neg" and delta > 0)
        if is_sign_rev or (not dual):
            invalid_or_rev_cnt += 1
        if is_sign_rev and dual:
            rev_cases.append({
                "factor_code": r.factor_code,
                "factor_name": r.factor_name,
                "origin_stage": stage,
                "origin_expected_dir": "正向加分/主线" if exp_dir == "pos" else "负向避坑/伪题材",
                "new_stage_dir": "正向" if delta > 0 else "负向",
                "buy_mode": r.buy_mode,
                "n_raw": int(r.n_raw),
                "delta_vs_base_pct": float(r.delta_vs_base_pct),
                "early_22_23_pct": r.early_22_23_pct,
                "recent_24_26_pct": r.recent_24_26_pct,
                "ss_nav": r.ss_nav,
            })

    rev_cases.sort(key=lambda x: abs(x["delta_vs_base_pct"]), reverse=True)

    pos_pool = df23[(df23["dual_period_consistent"]) & (df23["delta_vs_base_pct"] > 0) & (df23["n_raw"] >= 15)].copy()
    pos_pool = pos_pool.sort_values(["delta_vs_base_pct", "ss_nav"], ascending=[False, False], na_position="last")
    neg_pool = df23[(df23["dual_period_consistent"]) & (df23["delta_vs_base_pct"] < 0) & (df23["n_raw"] >= 15)].copy()
    neg_pool = neg_pool.sort_values(["delta_vs_base_pct", "wr_pct"], ascending=[True, True], na_position="last")

    cols_brief = [
        "source_group", "factor_code", "factor_name", "buy_mode", "n_raw", "wr_pct",
        "avg_net_ret_pct", "delta_vs_base_pct", "early_22_23_pct", "recent_24_26_pct",
        "ss_nav", "ss_ex_top3_nav", "verdict",
    ]
    return {
        "total_factors_audited": int(len(df23)),
        "verdict_counts": {
            "双期正向王牌": int(vc.get("双期正向王牌", 0)),
            "双期正向辅助": int(vc.get("双期正向辅助", 0)),
            "双期负向排雷": int(vc.get("双期负向排雷", 0)),
            "跨周期失效或反转": int(vc.get("跨周期失效或反转", 0)),
        },
        "dual_positive_total": int(vc.get("双期正向王牌", 0) + vc.get("双期正向辅助", 0)),
        "dual_negative_veto_total": int(vc.get("双期负向排雷", 0)),
        "cross_period_unstable_total": int(vc.get("跨周期失效或反转", 0)),
        "v18_theme_53_effective_dual_positive": b1_effective_dual_pos,
        "v18_theme_53_effective_dual_negative_veto": b1_effective_dual_neg_veto,
        "v18_theme_plus_rank_138_effective_dual_positive": b1_b2_effective_dual_pos,
        "v18_theme_plus_rank_138_effective_dual_negative_veto": b1_b2_effective_dual_neg,
        "v18_theme_with_prior_count": int(len(mig_df)),
        "v18_to_2to3_invalid_or_reversed_count": int(invalid_or_rev_cnt),
        "v18_to_2to3_dual_consistent_sign_reversal_count": int(len(rev_cases)),
        "source_group_breakdown": sg_vc,
        "top12_positive": pos_pool.head(12)[cols_brief].to_dict(orient="records"),
        "top10_negative_veto": neg_pool.head(10)[cols_brief].to_dict(orient="records"),
        "top8_1to2_to_2to3_reversals": rev_cases[:8],
    }


def main():
    df45, prior45 = build_4to5_catalog()
    df23, prior23 = build_2to3_catalog()

    # 检查 factor_code 唯一性与核心字符串列零缺失
    assert df45["factor_code"].is_unique, "4to5 factor_code duplicate detected!"
    assert df23["factor_code"].is_unique, "2to3 factor_code duplicate detected!"
    for col in ["source_group", "factor_code", "factor_name", "buy_mode", "n_raw", "avg_net_ret_pct", "delta_vs_base_pct", "dual_period_consistent", "verdict"]:
        assert df45[col].isna().sum() == 0, f"4to5 col {col} has NaN!"
        assert df23[col].isna().sum() == 0, f"2to3 col {col} has NaN!"

    # 使用可空整数保证 ss_n / n_raw 在 CSV 中不变成 138.0
    for df in (df45, df23):
        df["n_raw"] = df["n_raw"].astype("Int64")
        df["ss_n"] = df["ss_n"].astype("Int64")

    out45_csv = f"{ROOT_DIR}/master_4to5_all_factors_audit.csv"
    out23_csv = f"{ROOT_DIR}/master_2to3_all_factors_audit.csv"
    out_json = f"{ROOT_DIR}/master_catalogs_summary.json"

    df45.to_csv(out45_csv, index=False, encoding="utf-8-sig")
    df23.to_csv(out23_csv, index=False, encoding="utf-8-sig")

    summary = {
        "generated_at": "2026-11-14",
        "data_completeness_notes": {
            "4to5_a5_2way_interactions": "a5_4to5_2way_interactions.csv 原始表未输出 early_22_23_avg 与 recent_24_26_avg 均值，因此这 30 行这两列留空（JSON 为 null），其双期一致性基于原始 e_ss_nav 与 r_ss_nav 相对基线判定。",
            "2to3_b5_quantiles": "b5_2to3_all_cols_quantiles.csv 原始表为单调分位均值差扫描，未输出胜率/赔率/单仓净值，因此这 86 行 wr_pct/payoff/ss_n/ss_nav/ss_ex_top3_nav 留空（JSON 为 null）；另有 3 个稀疏布尔因子(notice_hard/has_stock_reg/has_tox_notice)22-23样本不足致 early_22_23_pct 为空。",
            "pit_and_coverage_caveats": "b3 中 F10_vwap_trap (n=31) 依赖 Day3 盘中 5m 均价线且 Day3 5m 样本仅覆盖 49 笔，在 09:25 竞价买模式下属盘后状态而非开盘前已知特征，实盘不可用于 09:25 竞价过滤；b5_summary 亦标注 headroom_100 含 Day3 指数收盘比值。",
        },
        "4to5_master_audit": summarize_4to5(df45, prior45),
        "2to3_master_audit": summarize_2to3(df23, prior23),
    }
    summary = sanitize_for_json(summary)
    with open(out_json, "w", encoding="utf-8") as fp:
        json.dump(summary, fp, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"[+] 4to5 saved: {out45_csv} (rows={len(df45)})")
    print("    4to5 verdicts:", summary["4to5_master_audit"]["verdict_counts"])
    print(f"    4to5 migrated prior={summary['4to5_master_audit']['migrated_from_3to4_and_highdragon_tested_with_prior']}, invalid_or_rev={summary['4to5_master_audit']['migrated_invalid_or_reversed_count']}, dual_sign_rev={summary['4to5_master_audit']['migrated_dual_consistent_sign_reversal_count']}")
    print(f"[+] 2to3 saved: {out23_csv} (rows={len(df23)})")
    print("    2to3 verdicts:", summary["2to3_master_audit"]["verdict_counts"])
    print(f"    2to3 V18_53 dual_pos={summary['2to3_master_audit']['v18_theme_53_effective_dual_positive']}, dual_neg={summary['2to3_master_audit']['v18_theme_53_effective_dual_negative_veto']}, dual_sign_rev={summary['2to3_master_audit']['v18_to_2to3_dual_consistent_sign_reversal_count']}")
    print(f"[+] Summary JSON saved: {out_json}")


if __name__ == "__main__":
    main()
