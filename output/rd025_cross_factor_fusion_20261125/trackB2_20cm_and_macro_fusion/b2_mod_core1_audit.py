#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Track B2 Core 1 Part B: S82 Enhancement Matrix, A76-81 Rescue Audit, CSCV PBO, 7-Spotlight Tests."""
import itertools, sys
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
from b2_mod_eval import WINDOWS_20CM, bh_fdr, build_20cm_slot1_mtm, cscv_pbo_matrix, eval_all_windows, paired_daily_pval


def build_core1_rules(df: pd.DataFrame) -> list[tuple[str, str, str, np.ndarray, str]]:
    """Build strictly IS-quantiled or native-threshold rules across all 11 modules + oversold pry DNA.
    Returns list of (rule_id, module, mode ['FILT_S82'|'SC_ADD'], vec_bool_or_delta, desc).
    """
    is_m = df["buy_date"].to_numpy() <= "2024-06-30"
    rules = []

    def q_is(col, q):
        v = pd.to_numeric(df.loc[is_m, col], errors="coerce").dropna()
        return float(np.quantile(v, q)) if len(v) else 0.0

    # Native / explicit prompt mechanism rules (tested cleanly in both skip & scorecard where relevant)
    nat_pairs = [
        ("R_M1_ixic15_skip", "M1_美股隔夜", "FILT_S82", ~(df["us_ixic_ret"] <= -0.015).to_numpy(), "纳指<=-1.5%过滤"),
        ("R_M1_ixic15_sc_pen", "M1_美股隔夜", "SC_ADD", np.where(df["us_ixic_ret"] <= -0.015, -6.0, 0.0), "纳指<=-1.5%扣6分"),
        ("R_M1_ixic15_sc_add", "M1_美股隔夜", "SC_ADD", np.where(df["us_ixic_ret"] <= -0.015, 5.0, 0.0), "纳指<=-1.5%加5分(错杀)"),
        ("R_M1_ixic_panic_skip", "M1_美股隔夜", "FILT_S82", ~(df["us_ixic_drop15_panic_open"] == 1).to_numpy(), "纳指<=-1.5%叠深低开过滤"),
        ("R_M1_ixic_panic_add", "M1_美股隔夜", "SC_ADD", np.where(df["us_ixic_drop15_panic_open"] == 1, 5.0, 0.0), "纳指<=-1.5%叠深低开加5分"),
        ("R_M1_ixic10_panic_add", "M1_美股隔夜", "SC_ADD", np.where(df["us_ixic_drop10_panic_open"] == 1, 5.0, 0.0), "纳指<=-1.0%叠深低开加5分"),
        ("R_M2_nt_ge40_add", "M2_国家队V3", "SC_ADD", np.where(df["score_eod_d1"].fillna(20) >= 40, 5.0, 0.0), "国家队V3>=40加5分"),
        ("R_M2_nt_ge40_skip", "M2_国家队V3", "FILT_S82", ~(df["score_eod_d1"].fillna(20) >= 40).to_numpy(), "国家队V3>=40过滤(虹吸)"),
        ("R_M2_nt_fake_skip", "M2_国家队V3", "FILT_S82", ~(df["fake_supp_d1"].fillna(0) == 1).to_numpy(), "国家队假护盘过滤"),
        ("R_M2_nt_fake_pen", "M2_国家队V3", "SC_ADD", np.where(df["fake_supp_d1"].fillna(0) == 1, -6.0, 0.0), "国家队假护盘扣6分"),
        ("R_M2_nt_redemp_skip", "M2_国家队V3", "FILT_S82", ~(df["redemp_press_d1"].fillna(0) == 1).to_numpy(), "国家队赎回压力过滤"),
        ("R_M2_nt_redemp_pen", "M2_国家队V3", "SC_ADD", np.where(df["redemp_press_d1"].fillna(0) == 1, -5.0, 0.0), "国家队赎回压力扣5分"),
        ("R_M3_pol_neg20_skip", "M3_证监会22核", "FILT_S82", ~(df["pol_22_neg_20d"].fillna(0) >= 2).to_numpy(), "20日正面缺失/负面政策>=2过滤"),
        ("R_M3_pol_exch_skip", "M3_证监会22核", "FILT_S82", ~(df["pol_exch_surv_5d"].fillna(0) >= 1).to_numpy(), "交易所点名后5日过滤"),
        ("R_M5_sell_lasa_skip", "M5_游资贝叶斯", "FILT_S82", ~(df["lhb_sell_lasa_net_sell"].fillna(0) > 100.0).to_numpy(), "卖榜纯拉萨净卖出>100万过滤"),
        ("R_M5_sell_lasa_add", "M5_游资贝叶斯", "SC_ADD", np.where(df["lhb_sell_lasa_net_sell"].fillna(0) > 100.0, 5.0, 0.0), "卖榜纯拉萨净卖出>100万加5分"),
        ("R_M5_buy_lasa15_skip", "M5_游资贝叶斯", "FILT_S82", ~(df["lhb_buy_lasa_share"].fillna(0) >= 0.15).to_numpy(), "买榜拉萨占比>=15%过滤"),
        ("R_M5_surf_skip", "M5_游资贝叶斯", "FILT_S82", ~(df["lhb_surf_flag"].fillna(0) == 1).to_numpy(), "一日游席位过滤"),
        ("R_M5_bayes_pos_add", "M5_游资贝叶斯", "SC_ADD", np.where(df["yz_bayes_t2"].fillna(0) > 0.002, 5.0, 0.0), "游资贝叶斯T+2>0.2%加5分"),
        ("R_M5_bayes_neg_skip", "M5_游资贝叶斯", "FILT_S82", ~(df["yz_bayes_t2"].fillna(0) < -0.002).to_numpy(), "游资贝叶斯T+2<-0.2%过滤"),
        ("R_M6_abn_lt40_skip", "M6_异动与公告", "FILT_S82", ~(df["abn_tight_headroom"].fillna(1.0) < 0.45).to_numpy(), "异动紧余量<45%过滤"),
        ("R_M6_ir_unpop_add", "M6_异动与公告", "SC_ADD", np.where(df["cninfo_ir_unpop90"].fillna(0) == 1, 4.0, 0.0), "90日冷门零调研加4分"),
        ("R_M6_pos_notice_add", "M6_异动与公告", "SC_ADD", np.where(df["cninfo_pos_45d"].fillna(0) >= 1, 4.0, 0.0), "45日正面公告加4分"),
        ("R_M6_reg_neg_skip", "M6_异动与公告", "FILT_S82", ~(df["cninfo_reg_neg_30d"].fillna(0) >= 1).to_numpy(), "30日负面/问询公告过滤"),
        ("R_M7_shrink_bank_skip", "M7_RD012防御", "FILT_S82", ~(df["rd012_shrink_bank_fake_d1"].fillna(0) == 1).to_numpy(), "缩量银行假护盘过滤"),
        ("R_M7_shrink_bank_pen", "M7_RD012防御", "SC_ADD", np.where(df["rd012_shrink_bank_fake_d1"].fillna(0) == 1, -5.0, 0.0), "缩量银行假护盘扣5分"),
        ("R_M7_tech_retr_skip", "M7_RD012防御", "FILT_S82", ~(df["rd012_tech_retreat_d1"].fillna(0) == 1).to_numpy(), "科技大退潮日过滤"),
        ("M08_brk_r10_hot_add", "M8_断板反包", "SC_ADD", np.where(df["brk_r10_d1"].fillna(0) >= q_is("brk_r10_d1", 0.70), 5.0, 0.0), "断板反包率IS前30%加5分"),
        ("M08_brk_r10_cold_skip", "M8_断板反包", "FILT_S82", ~(df["brk_r10_d1"].fillna(1) <= q_is("brk_r10_d1", 0.30)).to_numpy(), "断板反包率IS后30%过滤"),
        ("M08_brk_r10_cold_pen", "M8_断板反包", "SC_ADD", np.where(df["brk_r10_d1"].fillna(1) <= q_is("brk_r10_d1", 0.30), -5.0, 0.0), "断板反包率IS后30%扣5分"),
        ("R_M9_gap_defA_skip", "M9_连板断层", "FILT_S82", ~(df["gap_void_defA_d1"].fillna(0) == 1).to_numpy(), "连板断层定义A过滤"),
        ("R_M9_gap_defA_add", "M9_连板断层", "SC_ADD", np.where(df["gap_void_defA_d1"].fillna(0) == 1, 5.0, 0.0), "连板断层定义A加5分"),
        ("R_M9_gap_defB_skip", "M9_连板断层", "FILT_S82", ~(df["gap_ice_defB_d1"].fillna(0) == 1).to_numpy(), "连板绝对冰点B过滤"),
        ("R_M9_old_drag_skip", "M9_连板断层", "FILT_S82", ~(df["old_dragon_brk_1_2d_d1"].fillna(0) == 1).to_numpy(), "老妖断板1至2日过滤"),
        ("R_M10_kpl_1020_add", "M10_题材微观", "SC_ADD", np.where(df["kpl_10_20_zt"].fillna(0) >= 3, 4.0, 0.0), "10+20cm同题材共振>=3加4分"),
        ("R_M10_zt_obc0_add", "M10_题材微观", "SC_ADD", np.where(df["zt_obc"].fillna(1) == 0, 4.0, 0.0), "T0零开板紧封加4分"),
        ("R_M10_rfm_pct40_add", "M10_题材微观", "SC_ADD", np.where(df["rfm_pct_all20"].fillna(1) <= 0.40, 4.0, 0.0), "20cm自由流值分位<=40%加4分"),
        ("R_M11_dt_ge20_skip", "M11_商品与撬板", "FILT_S82", ~(df["mkt_all_nonst_dt_d1"].fillna(0) >= 20).to_numpy(), "买前跌停>=20家过滤"),
        ("R_M11_dt_ge20_add", "M11_商品与撬板", "SC_ADD", np.where(df["mkt_all_nonst_dt_d1"].fillna(0) >= 20, 5.0, 0.0), "买前跌停>=20家加5分"),
        ("M11_dt_lt5_add", "M11_商品与撬板", "SC_ADD", np.where(df["mkt_all_nonst_dt_d1"].fillna(99) < 5, 4.0, 0.0), "买前跌停<5家加4分"),
        ("R_M11_0925_zt_lt5_skip", "M11_商品与撬板", "FILT_S82", ~(df["mkt_all_nonst_0925_zt"].fillna(99) < 5).to_numpy(), "0925竞价涨停<5家过滤"),
        ("R_M11_prev_bias20_add", "M11_商品与撬板", "SC_ADD", np.where(df["prev_bias20"].fillna(0) <= -0.08, 4.0, 0.0), "首板前20日超跌<=-8%加4分"),
        ("R_M11_down_streak2_add", "M11_商品与撬板", "SC_ADD", np.where(df["pry_down_streak_pre"].fillna(0) >= 2, 4.0, 0.0), "首板前连跌>=2天加4分"),
        ("R_M11_vol_r5_hi_skip", "M11_商品与撬板", "FILT_S82", ~(df["vol_ratio5"].fillna(0) >= 3.5).to_numpy(), "首板放量>=3.5倍过滤"),
        ("R_M4_smb_lo_skip", "M4_15年风格", "FILT_S82", ~(df["st15_small_minus_big_5d_d1"].fillna(0) <= q_is("st15_small_minus_big_5d_d1", 0.30)).to_numpy(), "近5日小微跑输茅指数IS后30%过滤"),
        ("R_M4_ice_hi_add", "M4_15年风格", "SC_ADD", np.where(df["st15_ice_5d_d1"].fillna(0) >= q_is("st15_ice_5d_d1", 0.70), 4.0, 0.0), "游资周期冰点IS前30%加4分"),
        ("R_M4_erp_hi_add", "M4_15年风格", "SC_ADD", np.where(df["macro15_erp_20d_d1"].fillna(0) >= q_is("macro15_erp_20d_d1", 0.70), 4.0, 0.0), "股债ERP策略IS前30%加4分"),
        ("R_M11_comm_gc_up_skip", "M11_商品与撬板", "FILT_S82", ~(df["comm_gc_ret"].fillna(0) >= q_is("comm_gc_ret", 0.70)).to_numpy(), "隔夜黄金大涨IS前30%(避险)过滤"),
        ("R_M7_bank_tech_hi_skip", "M7_RD012防御", "FILT_S82", ~(df["rd012_bank_minus_tech_d1"].fillna(0) >= q_is("rd012_bank_minus_tech_d1", 0.70)).to_numpy(), "银行减科技差IS前30%过滤"),
        ("R_M7_bank_tech_hi_pen", "M7_RD012防御", "SC_ADD", np.where(df["rd012_bank_minus_tech_d1"].fillna(0) >= q_is("rd012_bank_minus_tech_d1", 0.70), -6.0, 0.0), "银行减科技差IS前30%扣6分"),
        ("R_M7_bank_tech_lo_add", "M7_RD012防御", "SC_ADD", np.where(df["rd012_bank_minus_tech_d1"].fillna(0) <= q_is("rd012_bank_minus_tech_d1", 0.30), 4.0, 0.0), "科技强于银行IS前30%加4分"),
        ("R_M10_zt_mins_hi_add", "M10_题材微观", "SC_ADD", np.where(df["zt_mins"].fillna(0) >= q_is("zt_mins", 0.70), 4.0, 0.0), "首板封板耗时IS后30%(充分换手)加4分"),
        ("R_M6_abn_hi_add", "M6_异动与公告", "SC_ADD", np.where(df["abn_tight_headroom"].fillna(0) >= q_is("abn_tight_headroom", 0.70), 4.0, 0.0), "异动紧余量IS前30%加4分"),
        ("R_M1_vix_hi_add", "M1_美股隔夜", "SC_ADD", np.where(df["us_vix_level"].fillna(20) >= q_is("us_vix_level", 0.70), 4.0, 0.0), "隔夜VIX高位IS前30%加4分"),
        ("R_M2_nt_sync_neg_skip", "M2_国家队V3", "FILT_S82", ~(df["t1_t2_sync_d1"].fillna(0) == 1).to_numpy(), "一二队大蓝筹同步救市过滤"),
    ]
    rules.extend(nat_pairs)
    return rules


def run_core1_suite(df20: pd.DataFrame, v11_fcols: list[str], sim_k_slots_fn, tpe_mod, bar_lu, cal_dts, dt_idx, sh300, all_sh_dts) -> dict:
    def _eval_subset(sub_raw: pd.DataFrame):
        if sub_raw.empty:
            dr = np.zeros(len(cal_dts), dtype=float)
            return pd.DataFrame(), dr, eval_all_windows(pd.DataFrame(), pd.DataFrame(), dr, cal_dts, dt_idx, sh300, all_sh_dts, WINDOWS_20CM)
        s1, _, _ = sim_k_slots_fn(sub_raw, 1)
        dr = build_20cm_slot1_mtm(s1, cal_dts, dt_idx, bar_lu, tpe_mod)
        return s1, dr, eval_all_windows(s1, sub_raw, dr, cal_dts, dt_idx, sh300, all_sh_dts, WINDOWS_20CM)

    base_all_s1, base_all_dr, base_all_w = _eval_subset(df20)
    s82_raw = df20[df20["score_base_v11"] >= 82.0].copy()
    base_s82_s1, base_s82_dr, base_s82_w = _eval_subset(s82_raw)
    a76_all_s1, a76_all_dr, a76_all_w = _eval_subset(df20[df20["score_base_v11"] >= 76.0])
    a7681_raw = df20[df20["score_base_v11"].between(76.0, 81.9)].copy()
    base_7681_s1, base_7681_dr, base_7681_w = _eval_subset(a7681_raw)

    base_s82_keys = set(zip(s82_raw["sig_date"], s82_raw["c6"]))
    base_s82_s1_keys = set(zip(base_s82_s1["sig_date"], base_s82_s1["c6"]))
    rules = build_core1_rules(df20)
    s82_results, dr_mat_s82, pvals_s82 = [], [base_s82_dr], []
    for rid, mod, rmode, vec, desc in rules:
        if rmode == "FILT_S82":
            sub = df20[(df20["score_base_v11"] >= 82.0) & vec].copy()
        else:
            d_sc = df20["score_base_v11"].to_numpy(float) + vec
            sub = df20[d_sc >= 82.0].copy()
            sub["score"] = d_sc[d_sc >= 82.0]
        s1, dr, w = _eval_subset(sub)
        cur_raw_k = set(zip(sub["sig_date"], sub["c6"]))
        cur_s1_k = set(zip(s1["sig_date"], s1["c6"])) if not s1.empty else set()
        mod_raw = len(base_s82_keys ^ cur_raw_k)
        mod_s1 = len(base_s82_s1_keys ^ cur_s1_k)
        pv = paired_daily_pval(dr, base_s82_dr)
        pvals_s82.append(pv)
        dr_mat_s82.append(dr)
        d_is = round(w["IS"]["nav"] - base_s82_w["IS"]["nav"], 3)
        d_oob = round(w["OOS_BLIND"]["nav"] - base_s82_w["OOS_BLIND"]["nav"], 3)
        d_oort = round(w["OOS_RT"]["nav"] - base_s82_w["OOS_RT"]["nav"], 3)
        d_y26 = round(w["Y26"]["nav"] - base_s82_w["Y26"]["nav"], 3)
        s82_results.append({
            "rule_id": rid, "module": mod, "mode": rmode, "desc": desc,
            "mod_raw_n": int(mod_raw), "mod_slot1_n": int(mod_s1),
            "p_daily": round(pv, 5),
            "d_IS_nav": d_is, "d_OOS_BLIND_nav": d_oob, "d_OOS_RT_nav": d_oort, "d_Y26_nav": d_y26,
            "d_IS_sharpe": round(w["IS"]["daily_sharpe"] - base_s82_w["IS"]["daily_sharpe"], 3),
            "d_OOS_sharpe": round(w["OOS_BLIND"]["daily_sharpe"] - base_s82_w["OOS_BLIND"]["daily_sharpe"], 3),
            "windows": w,
        })
    qs_s82 = bh_fdr(pvals_s82)
    finalists_pbo = {}
    for i, r in enumerate(s82_results):
        r["q_bh"] = qs_s82[i]
        w = r["windows"]
        y26_ok = (w["Y26"]["mean_pct"] >= 0.0) and (w["Y26"]["daily_mdd_pct"] <= base_s82_w["Y26"]["daily_mdd_pct"] + 0.5)
        pass_pre = (r["d_IS_nav"] > 0) and (r["d_OOS_BLIND_nav"] > 0) and y26_ok and (r["mod_slot1_n"] >= 5)
        r["pass_is_oos_y26_n"] = bool(pass_pre)
        r["promoted"] = False
        if pass_pre or (r["d_OOS_BLIND_nav"] > 0.5 and r["d_IS_nav"] > 0):
            # CSCV PBO on threshold ladder [76,78,80,82,84,86]
            vec = next(v for rid0, _, rm0, v, _ in rules if rid0 == r["rule_id"])
            rm0 = r["mode"]
            cols_th = []
            for th in [76.0, 78.0, 80.0, 82.0, 84.0, 86.0]:
                if rm0 == "FILT_S82":
                    sub_t = df20[(df20["score_base_v11"] >= th) & vec].copy()
                else:
                    dsc = df20["score_base_v11"].to_numpy(float) + vec
                    sub_t = df20[dsc >= th].copy(); sub_t["score"] = dsc[dsc >= th]
                cols_th.append(_eval_subset(sub_t)[1])
            pbo_r = cscv_pbo_matrix(np.column_stack(cols_th))
            r["cscv_pbo_ladder"] = pbo_r
            finalists_pbo[r["rule_id"]] = pbo_r
            if pass_pre and r["q_bh"] < 0.10 and (pbo_r["S8"]["pbo_pct"] or 99) < 25.0:
                r["promoted"] = True

    pool_pbo_s82 = cscv_pbo_matrix(np.column_stack(dr_mat_s82))

    # A76-81 Rescue Audit: test keeping OR dropping top/bottom half/threshold of EVERY atomic feature inside A76-81!
    a7681_tests, dr_mat_7681, pvals_7681 = [], [base_7681_dr], []
    for rid, mod, rmode, vec, desc in rules:
        if rmode == "FILT_S82":
            masks = [(f"A7681_{rid}_keep", vec, desc), (f"A7681_{rid}_inv", ~vec, f"反向:{desc}")]
        else:
            masks = [(f"A7681_{rid}_hit", vec > 0 if vec.max() > 0 else vec < 0, desc)]
        for tid, mvec, tdesc in masks:
            sub = df20[df20["score_base_v11"].between(76.0, 81.9) & mvec].copy()
            if len(sub) < 10:
                continue
            s1, dr, w = _eval_subset(sub)
            pv = paired_daily_pval(dr, base_7681_dr)
            pvals_7681.append(pv); dr_mat_7681.append(dr)
            rescued = (w["IS"]["nav"] > 1.05) and (w["OOS_BLIND"]["nav"] > 1.05) and (w["Y26"]["nav"] >= 1.00) and (w["IS"]["n"] >= 5) and (w["OOS_BLIND"]["n"] >= 5)
            a7681_tests.append({
                "test_id": tid, "module": mod, "desc": tdesc, "raw_n": int(len(sub)), "n_1s": w["FULL"]["n"],
                "IS_n": w["IS"]["n"], "IS_nav": w["IS"]["nav"], "OOS_BLIND_n": w["OOS_BLIND"]["n"], "OOS_BLIND_nav": w["OOS_BLIND"]["nav"],
                "OOS_RT_nav": w["OOS_RT"]["nav"], "Y26_nav": w["Y26"]["nav"], "FULL_nav": w["FULL"]["nav"],
                "FULL_mdd": w["FULL"]["trade_mdd_pct"], "p_daily": round(pv, 5), "rescued_pre_fdr": bool(rescued),
            })
    q76 = bh_fdr(pvals_7681)
    for i, r in enumerate(a7681_tests):
        r["q_bh"] = q76[i]
    # Also test top IS 2-factor AND combinations inside A76-81
    top_is_a = sorted([r for r in a7681_tests if r["IS_n"] >= 10], key=lambda x: x["IS_nav"], reverse=True)[:5]
    mask_lu = {}
    for rid, mod, rmode, vec, desc in rules:
        if rmode == "FILT_S82":
            mask_lu[f"A7681_{rid}_keep"] = vec
            mask_lu[f"A7681_{rid}_inv"] = ~vec
        else:
            mask_lu[f"A7681_{rid}_hit"] = (vec > 0 if vec.max() > 0 else vec < 0)
    combo_2f = []
    top_ids = [x["test_id"] for x in top_is_a]
    for a_id, b_id in itertools.combinations(top_ids, 2):
        sub_c = df20[df20["score_base_v11"].between(76.0, 81.9) & mask_lu[a_id] & mask_lu[b_id]].copy()
        if len(sub_c) >= 5:
            _, dr_c, w_c = _eval_subset(sub_c)
            combo_2f.append({
                "combo": f"{a_id} & {b_id}", "raw_n": int(len(sub_c)), "n_1s": w_c["FULL"]["n"],
                "IS_n": w_c["IS"]["n"], "IS_nav": w_c["IS"]["nav"], "OOB_n": w_c["OOS_BLIND"]["n"],
                "OOB_nav": w_c["OOS_BLIND"]["nav"], "Y26_nav": w_c["Y26"]["nav"], "FULL_nav": w_c["FULL"]["nav"],
            })
    pbo_7681 = cscv_pbo_matrix(np.column_stack(dr_mat_7681)) if len(dr_mat_7681) >= 3 else {}

    return {
        "baselines": {"ALL_809": base_all_w, "S82": base_s82_w, "A76_all": a76_all_w, "A76_81_only": base_7681_w},
        "s82_enhancement_tests": s82_results,
        "s82_pool_cscv_pbo": pool_pbo_s82,
        "s82_finalists_pbo": finalists_pbo,
        "a76_81_rescue_audit": {"n_tested": len(a7681_tests), "pool_cscv_pbo": pbo_7681, "top_by_IS": top_is_a, "top_is_2f_combos": combo_2f, "rescued_all": [r for r in a7681_tests if r["rescued_pre_fdr"]], "all_tests": a7681_tests},
    }
