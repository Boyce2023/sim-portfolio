# -*- coding: utf-8 -*-
"""
v16_scoring.py: V16 因子特征与排位打分逻辑
严格零未来函数，100% 对齐 V16 审计标准公式。
"""
import re
import numpy as np
import pandas as pd

CSRC_PURE_OUTSIDER = {
    "A01", "A02", "A03", "A04", "A05", "D44", "D45", "D46",
    "E47", "E48", "E49", "E50", "F51", "F52", "G53", "G54",
    "G55", "G56", "G58", "G59", "H61", "H62", "K70", "L72",
    "N77", "N78", "C13", "C14", "C15", "C17", "C18", "C19",
    "C20", "C21", "C22"
}
HARD_TECH_RE = re.compile(
    r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)"
)

def compute_v16_features_and_scores(hist_fb):
    wk_mask = hist_fb["gap_days"] >= 3
    csrc_sec = [str(c)[:3] if str(c) else "UNK" for c in hist_fb["csrc_ind"]]
    is_hard_tech = hist_fb["plate"].astype(str).str.contains(HARD_TECH_RE).values
    has_ma_hard = (hist_fb["notice_hard"] | hist_fb["is_ma"]).values
    is_pure_outsider = np.array([ht and (cs in CSRC_PURE_OUTSIDER) and (not hm) for ht, cs, hm in zip(is_hard_tech, csrc_sec, has_ma_hard)], dtype=bool)
    name_sub20 = np.where(is_pure_outsider, -20.0, 0.0)
    hist_fb["is_outsider_pen"] = is_pure_outsider
    hist_fb["name_sub20"] = name_sub20

    common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
    in_std_buy_win = common_ok & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078)))
    is_front_lock = hist_fb["d2_is_yizi"] | ((~wk_mask) & (hist_fb["d2_o_pct"] > 0.078)) | (wk_mask & (hist_fb["d2_o_pct"] > 0.088))
    hist_fb["_is_front_lock"] = is_front_lock.astype(int)
    hist_fb["front_lock_cnt"] = hist_fb.groupby(["d2_dt", "plate"])["_is_front_lock"].transform("sum")
    hist_fb["mkt_yizi_cnt"] = hist_fb.groupby("d2_dt")["d2_is_yizi"].transform("sum").fillna(0).astype(int)
    hist_fb["_true_buy_o"] = np.where(in_std_buy_win, hist_fb["d2_o_pct"], -9.99)
    hist_fb["true_buy_rk"] = hist_fb.groupby(["d2_dt", "plate"])["_true_buy_o"].rank(ascending=False, method="min")

    has_distinct_sub = (hist_fb["p_sz"] >= 8) & (hist_fb["r_short"] != hist_fb["plate"]) & (hist_fb["r_short"] != "其他") & (hist_fb["r_short"] != "")
    orig_rk_bonus = np.where(hist_fb["buyable_plate_rk"] == 1, 35.0, np.where(has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0, np.where(hist_fb["buyable_plate_rk"] == 2, 8.0, -25.0)))
    true_rk_bonus = np.where(hist_fb["true_buy_rk"] == 1, 35.0, np.where(has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0, np.where(hist_fb["true_buy_rk"] == 2, 8.0, -25.0)))
    rk_fix_delta = true_rk_bonus - orig_rk_bonus
    hist_fb["rk_fix_delta"] = rk_fix_delta

    flc = hist_fb["front_lock_cnt"].values
    tbrk = hist_fb["true_buy_rk"].values
    myz = hist_fb["mkt_yizi_cnt"].values
    is_super_wave = (hist_fb["rk_theme"] == 1) & (hist_fb["p_sz"] >= 8) & (tbrk == 1)
    y_std = np.select(
        [
            (flc == 1) & (tbrk == 1) & np.isin(myz, [1, 2]),
            (flc >= 2) & is_super_wave,
            (flc == 2) & (~is_super_wave),
            (flc >= 3) & (~is_super_wave),
            (flc == 0) & (myz == 0) & (~has_ma_hard),
        ],
        [8.0, 5.0, -15.0, -22.0, -5.0],
        default=0.0
    )
    hist_fb["y_std"] = y_std

    # 规则 γ: t-1 滚动前20日可买高开(>=5.5%)首板股二板封板率传感器
    daily_s3 = []
    for d, grp in hist_fb.groupby("d2_dt"):
        buyable = grp[grp["is_buyable_open"] & (~grp["nuclear_halt"]) & (~grp["promo_freeze"])]
        ho = buyable[buyable["d2_o_pct"] >= 0.055]
        rate_ho_zt = (ho["d2_is_zt"].sum() / len(ho)) if len(ho) > 0 else np.nan
        daily_s3.append({"date": d, "rate_ho_zt": rate_ho_zt})
    df_s3 = pd.DataFrame(daily_s3).sort_values("date").reset_index(drop=True)
    df_s3["roll20_ho_zt"] = df_s3["rate_ho_zt"].shift(1).rolling(20, min_periods=5).mean().fillna(0.45)
    ho_rate_map = dict(zip(df_s3["date"], df_s3["roll20_ho_zt"]))
    ho_vec = np.array([ho_rate_map.get(d, 0.45) for d in hist_fb["d2_dt"]])
    hist_fb["roll20_ho_zt"] = ho_vec
    hist_fb["weak_open_sensor_cold"] = ho_vec < 0.45

    clean_brk60 = hist_fb["clean_brk60"].values == 1
    dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
    pen_thr_vec = np.where(ho_vec < 0.45, 0.035, 0.031)
    pen_val_vec = np.where(ho_vec < 0.45, 25.0, 15.0)
    q_pen = - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < pen_thr_vec), pen_val_vec, 0.0)
    d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)
    seal_time = hist_fb["first_seal_time"].fillna("99:99:99")
    open_cnt = hist_fb["open_board_count"].fillna(0)
    is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (hist_fb["d1_seal_tightness"] >= 38.0)
    bon_tape = np.where(is_ht, 5.0, 0.0) + np.where(hist_fb["has_ir_pit"], 5.0, 0.0)
    hist_fb["is_hard_turnover"] = is_ht

    is_granularity = hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
    bonus_spear = np.where(is_granularity, 15.0, 0.0) + np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))
    f3_bonus = np.where(hist_fb["notice_bad"], -35.0, 0.0)
    hist_fb["score_wk"] = hist_fb["score_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
    hist_fb["s_prior_wk"] = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus

    sp_v = hist_fb["s_prior_wk"] + name_sub20 + y_std * 0.5
    sq_v = hist_fb["s_quant_dual"] + q_pen + d_ov + bon_tape + rk_fix_delta + y_std * 0.5
    sc_v = hist_fb["score_wk"] + q_pen + d_ov + bon_tape + rk_fix_delta + y_std + name_sub20
    hist_fb["sp_v"] = sp_v
    hist_fb["sq_v"] = sq_v
    hist_fb["sc_v"] = sc_v
    hist_fb["score_active"] = sc_v

    p_tight = hist_fb["d1_seal_tightness"] >= 37.0
    pass_l1 = ~hist_fb["is_event_basket"]
    pass_l2 = ~hist_fb["is_dying_pulse"]
    pass_l3 = (hist_fb["plate_fb_cnt"] <= 1) | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2)))
    pass_nd_true = (~((hist_fb["p_sz"] >= 2) & (hist_fb["true_buy_rk"] >= 3))) & (~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0))))
    pass_ac = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
    thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)

    m_t1 = common_ok & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))) & (sp_v >= 45.0) & (sc_v >= thr_vec)
    m_t2_base = common_ok & (hist_fb["p_sz"] == 1) & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"]) & hist_fb["d2_o_pct"].between(0.035, 0.078) & (hist_fb["buyable_mkt_open_rk"] <= 3) & (hist_fb["d1_seal_tightness"] >= 15.0) & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))

    mm = ((m_t1 & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac) | (m_t2_base & pass_l2)) & p_tight
    mmon = common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090) & (sp_v >= 38.0) & (sc_v >= thr_vec) & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac & p_tight
    tot = (mm | (mmon & (~mm))).copy()
    sv = np.where(mm, sc_v + 1000.0, sc_v)

    sub_tot = hist_fb[tot].copy()
    sub_tot["_sv_tmp"] = sv[tot]
    bad_dts = set()
    for d, grp in sub_tot.groupby("d2_dt"):
        if (grp["rk_theme"] == 1).any():
            top_rk = grp.sort_values("_sv_tmp", ascending=False).iloc[0]["rk_theme"]
            if pd.notna(top_rk) and top_rk >= 4:
                bad_dts.add(d)
    tot = tot & (~hist_fb["d2_dt"].isin(bad_dts))

    # 规则 α 与 规则 β: 题材结构矩阵 (断层主线无过线禁买第三题材 + 三题材混战卡全场前二或硬催化)
    valid_plate = hist_fb[(hist_fb["plate"] != "其他") & (~hist_fb["is_event_basket"])].copy()
    pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(
        p_sz_max=("p_sz", "max"),
        p_theme_med=("s_prior_dual", "median")
    )
    pg_m = pg[pg["p_sz_max"] >= 2].copy()
    pg_m["rk_theme_mat"] = pg_m.groupby("d2_dt")["p_theme_med"].rank(ascending=False, method="min")
    daily_t1 = pg_m[pg_m["rk_theme_mat"] == 1].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
    daily_t2 = pg_m[pg_m["rk_theme_mat"] == 2].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
    daily_t3 = pg_m[pg_m["rk_theme_mat"] == 3].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")

    dom_no_dragon = set()
    melee_days = set()
    for d in sorted(daily_t1.index):
        t1_row = daily_t1.loc[d]
        t2_row = daily_t2.loc[d] if d in daily_t2.index else None
        t3_row = daily_t3.loc[d] if d in daily_t3.index else None
        t1_med = float(t1_row["p_theme_med"])
        t2_med = float(t2_row["p_theme_med"]) if t2_row is not None else 0.0
        t1_sz = int(t1_row["p_sz_max"])
        t2_sz = int(t2_row["p_sz_max"]) if t2_row is not None else 1
        is_dominant = ((t1_med - t2_med) >= 20.0) or ((t1_sz >= 6) and ((t1_sz / max(1, t2_sz)) >= 2.0))
        if is_dominant:
            t1_plate = t1_row["plate"]
            sub_d_passed = hist_fb[(hist_fb["d2_dt"] == d) & tot]
            t1_has_passed = (sub_d_passed["plate"] == t1_plate).any() if len(sub_d_passed) > 0 else False
            if not t1_has_passed:
                dom_no_dragon.add(d)
        if t1_row is not None and t2_row is not None and t3_row is not None:
            t3_med = float(t3_row["p_theme_med"])
            sz_max = max(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
            sz_min = min(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
            if (t1_med - t3_med) <= 15.0 and sz_max <= 5 and sz_min >= 2:
                melee_days.add(d)

    blocked_alpha = hist_fb["d2_dt"].isin(dom_no_dragon) & (hist_fb["rk_theme"] == 3)
    blocked_beta = hist_fb["d2_dt"].isin(melee_days) & (~((hist_fb["buyable_mkt_open_rk"] <= 2) | hist_fb["notice_hard"] | hist_fb["is_ma"]))
    tot = tot & (~blocked_alpha) & (~blocked_beta)
    hist_fb["is_melee_day"] = hist_fb["d2_dt"].isin(melee_days)
    hist_fb["is_dom_no_dragon"] = hist_fb["d2_dt"].isin(dom_no_dragon)

    hist_fb["v16_tot"] = tot
    hist_fb["v16_sv"] = sv
    hist_fb["v16_mm"] = mm

    pure_win = hist_fb["is_buyable_open"] & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078)))
    c_cond_tier1 = tot
    c_cond_tier2 = hist_fb["gate_ok"] & pure_win & (~tot)
    c_cond_tier3 = hist_fb["gate_ok"] & hist_fb["is_buyable_open"] & (~pure_win) & (hist_fb["d2_o_pct"] >= 0.0) & (~tot)
    hist_fb["sys_rank_score"] = np.where(
        c_cond_tier1, 10000.0 + sv,
        np.where(c_cond_tier2, 5000.0 + sc_v, np.where(c_cond_tier3, 2000.0 + sc_v, sc_v))
    )
    return hist_fb
