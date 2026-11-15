#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
tune_lora_26q4.py
================================================================================
多方案网格测试：寻找既在 2026 全年/7月后/10月后大幅提振，又在近三年与全五年保全基本盘的最优 LoRA 微调包
================================================================================
"""

import sys
import pickle
import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/special_26q4/1to2_26q4")
from test_26q4_candidates import (
    hist_fb, all_dts, dt_to_idx, price_lookup, bars_5m_map,
    run_simulation, make_trade_engine
)

# 基础特征提取
seal_time = hist_fb["first_seal_time"].fillna("99:99:99")
open_cnt = hist_fb["open_board_count"].fillna(0)
dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
clean_brk60 = hist_fb["clean_brk60"].values == 1

is_granularity = hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
bonus_spear = np.where(is_granularity, 15.0, 0.0) + np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))

common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
pass_l1 = ~hist_fb["is_event_basket"]
pass_l3 = (hist_fb["plate_fb_cnt"] <= 1) | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2)))
pass_ac = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
wk_mask = hist_fb["gap_days"] >= 3

f3_bonus = np.where(hist_fb["notice_bad"], -35.0, 0.0)
s_prior_wk = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus

m_t2_base = common_ok & (hist_fb["p_sz"] == 1) & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"]) & hist_fb["d2_o_pct"].between(0.035, 0.078) & (hist_fb["buyable_mkt_open_rk"] <= 3) & (hist_fb["d1_seal_tightness"] >= 15.0) & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))

in_std_buy_win = common_ok & (
    (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
    | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
)
is_front_lock = hist_fb["d2_is_yizi"] | ((~wk_mask) & (hist_fb["d2_o_pct"] > 0.078)) | (wk_mask & (hist_fb["d2_o_pct"] > 0.088))
hist_fb["_is_front_lock"] = is_front_lock.astype(int)
front_lock_cnt = hist_fb.groupby(["d2_dt", "plate"])["_is_front_lock"].transform("sum").values
mkt_yizi_cnt = hist_fb.groupby("d2_dt")["d2_is_yizi"].transform("sum").fillna(0).astype(int).values

hist_fb["_true_buy_o"] = np.where(in_std_buy_win, hist_fb["d2_o_pct"], -9.99)
true_buy_rk = hist_fb.groupby(["d2_dt", "plate"])["_true_buy_o"].rank(ascending=False, method="min").values

has_distinct_sub = (hist_fb["p_sz"] >= 8) & (hist_fb["r_short"] != hist_fb["plate"]) & (hist_fb["r_short"] != "其他") & (hist_fb["r_short"] != "")
orig_rk_bonus = np.where(
    hist_fb["buyable_plate_rk"] == 1, 35.0,
    np.where(has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0,
             np.where(hist_fb["buyable_plate_rk"] == 2, 8.0, -25.0))
)
true_rk_bonus = np.where(
    true_buy_rk == 1, 35.0,
    np.where(has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0,
             np.where(true_buy_rk == 2, 8.0, -25.0))
)
rk_fix_delta = true_rk_bonus - orig_rk_bonus

pass_nd_true = (~((hist_fb["p_sz"] >= 2) & (true_buy_rk >= 3))) & (
    ~((hist_fb["plate_d2_yizi_cnt"] >= 1) & (hist_fb["d1_seal_tightness"] < 15.0))
)

csrc_sec = [str(c)[:3] if str(c) else "UNK" for c in hist_fb["csrc_ind"]]
CSRC_PURE_OUTSIDER = {
    "A01","A02","A03","A04","A05",
    "D44","D45","D46",
    "E47","E48","E49","E50",
    "F51","F52",
    "G53","G54","G55","G56","G58","G59",
    "H61","H62",
    "K70",
    "L72","N77","N78",
    "C13","C14","C15","C17","C18","C19","C20","C21","C22"
}
is_hard_tech = hist_fb["plate"].astype(str).str.contains(r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)", regex=True).values
has_ma_hard = (hist_fb["notice_hard"] | hist_fb["is_ma"]).values
is_pure_outsider = np.array([ht and (cs in CSRC_PURE_OUTSIDER) and (not hm) for ht, cs, hm in zip(is_hard_tech, csrc_sec, has_ma_hard)], dtype=bool)
name_sub20 = np.where(is_pure_outsider, -20.0, 0.0)

is_super_wave = (hist_fb["rk_theme"] == 1) & (hist_fb["p_sz"] >= 8) & (true_buy_rk == 1)

def get_yizi_gran_v17():
    return np.select(
        [
            (front_lock_cnt == 1) & (true_buy_rk == 1) & np.isin(mkt_yizi_cnt, [1, 2]),
            (front_lock_cnt == 1) & (true_buy_rk == 1),
            (front_lock_cnt == 1) & (true_buy_rk >= 2),
            (front_lock_cnt >= 2) & is_super_wave,
            (front_lock_cnt == 2) & (~is_super_wave),
            (front_lock_cnt >= 3) & (~is_super_wave),
            (front_lock_cnt == 0) & (mkt_yizi_cnt == 0) & (~has_ma_hard),
        ],
        [8.0, 0.0, 0.0, 5.0, -15.0, -22.0, -5.0],
        default=0.0,
    )

y_v17 = get_yizi_gran_v17()

daily_records = []
for d, grp in hist_fb.groupby("d2_dt"):
    buyable = grp[grp["is_buyable_open"] & (~grp["nuclear_halt"]) & (~grp["promo_freeze"])]
    ho = buyable[buyable["d2_o_pct"] >= 0.055]
    n_ho = len(ho)
    rate_ho_zt = (ho["d2_is_zt"].sum() / n_ho) if n_ho > 0 else np.nan
    daily_records.append({"date": d, "rate_ho_zt": rate_ho_zt})
df_daily_s = pd.DataFrame(daily_records).sort_values("date").reset_index(drop=True)
df_daily_s["roll20_ho_zt"] = df_daily_s["rate_ho_zt"].shift(1).rolling(20, min_periods=5).mean().fillna(0.45)
sensors_map = df_daily_s.set_index("date").to_dict(orient="index")

pen_thr_vec = np.zeros(len(hist_fb))
pen_val_vec = np.zeros(len(hist_fb))
for d, s in sensors_map.items():
    ho_rate = s.get("roll20_ho_zt", 0.45)
    if ho_rate < 0.45:
        p_val, p_thr = 25.0, 0.035
    else:
        p_val, p_thr = 15.0, 0.031
    idx_d = (hist_fb["d2_dt"] == d).values
    pen_thr_vec[idx_d] = p_thr
    pen_val_vec[idx_d] = p_val
q_pen = - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < pen_thr_vec), pen_val_vec, 0.0)

d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)
is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (hist_fb["d1_seal_tightness"] >= 38.0)
bon_tape = np.where(is_ht, 5.0, 0.0) + np.where(hist_fb["has_ir_pit"], 5.0, 0.0)

valid_plate = hist_fb[(hist_fb["plate"] != "其他") & (~hist_fb["is_event_basket"])].copy()
pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(p_sz_max=("p_sz", "max"), p_theme_med=("s_prior_dual", "median"))
pg_m = pg[pg["p_sz_max"] >= 2].copy()
pg_m["rk_theme"] = pg_m.groupby("d2_dt")["p_theme_med"].rank(ascending=False, method="min")

daily_t1 = pg_m[pg_m["rk_theme"] == 1].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
daily_t2 = pg_m[pg_m["rk_theme"] == 2].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
daily_t3 = pg_m[pg_m["rk_theme"] == 3].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")

sc_climax_pen = np.where(hist_fb["mkt_zt_cnt"] >= 100, -15.0, np.where(hist_fb["mkt_zt_cnt"] >= 95, -10.0, 0.0))
sc_seal_pen = np.where(hist_fb["mkt_seal_rate"] >= 0.80, -10.0, 0.0)
sc_cap_pen = np.where((hist_fb["plate_d2_yizi_cnt"] >= 1) & (hist_fb["mcap"] > 90.0), -25.0, 0.0)

t1_med_map = daily_t1["p_theme_med"].to_dict()
t3_med_map = daily_t3["p_theme_med"].to_dict()
_t1m = hist_fb["d2_dt"].map(t1_med_map).fillna(0.0).values
_t3m = hist_fb["d2_dt"].map(t3_med_map).fillna(0.0).values
v18_dom_t3 = (_t1m >= 65.0) & (_t1m - _t3m >= 35.0) & (_t3m < 42.0)
sc_t3_pen = np.where(v18_dom_t3 & (hist_fb["rk_theme"].values >= 3), -15.0, 0.0)

v18_pen = sc_climax_pen + sc_seal_pen + sc_cap_pen + sc_t3_pen

sp_v = s_prior_wk + name_sub20 + y_v17 * 0.5
sq_v = hist_fb["s_quant_dual"].values + q_pen + d_ov + bon_tape + rk_fix_delta + y_v17 * 0.5

p_tight = (hist_fb["d1_seal_tightness"] >= 37.0).values
open_in_win = (
    (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
    | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
).values

# 题材结构判定
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

    diff_1_2 = t1_med - t2_med
    ratio_sz = t1_sz / max(1, t2_sz)
    is_dominant = (diff_1_2 >= 20.0) or ((t1_sz >= 6) and (ratio_sz >= 2.0))
    if is_dominant:
        dom_no_dragon.add(d) # will be updated after candidate filtering

    if t1_row is not None and t2_row is not None and t3_row is not None:
        t3_med = float(t3_row["p_theme_med"])
        range_top3 = t1_med - t3_med
        sz_max = max(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
        sz_min = min(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
        if range_top3 <= 15.0 and sz_max <= 5 and sz_min >= 2:
            melee_days.add(d)

def evaluate_candidate_pack(
    allow_dying_pulse_in_t1=True, # 放行 Theme 1 的二波龙
    dying_pulse_tax=-15.0,        # 放行 dying_pulse 需扣 15 分门票
    thr_jump_val=15.0,            # 封板率>75%高潮门槛跳升 +15 分 (319.8)
    bon_ma=10.0,                  # 并购重组/硬公告 +10 分
    bon_open_sweet=8.0,           # 竞价开盘 4.5%~7.8% 甜区 +8 分
    bon_brk60=10.0,               # 60日平台突破 +10 分
    pen_yizi_crowd=-10.0,         # 伴生一字分歧防炸板 -10 分
    pen_heavy_cap=0.0,            # 大盘巨型股惩罚 (0 或 -15)
    bon_t1=0.0,                   # 题材龙一额外加分 (0 或 +10)
    pen_t3=0.0,                   # 题材龙三额外扣分 (0 或 -15)
):
    # 门控
    if allow_dying_pulse_in_t1:
        pass_l2 = (~hist_fb["is_dying_pulse"]) | (hist_fb["rk_theme"] == 1) | hist_fb["notice_hard"] | hist_fb["is_ma"]
    else:
        pass_l2 = ~hist_fb["is_dying_pulse"]

    thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + thr_jump_val, 304.8)

    # 打分调整
    lora = np.zeros(len(hist_fb))
    if dying_pulse_tax != 0:
        lora += np.where(hist_fb["is_dying_pulse"], dying_pulse_tax, 0.0)
    if bon_ma != 0:
        lora += np.where(hist_fb["notice_hard"] | hist_fb["is_ma"], bon_ma, 0.0)
    if bon_open_sweet != 0:
        lora += np.where(hist_fb["d2_o_pct"].between(0.045, 0.078), bon_open_sweet, 0.0)
    if bon_brk60 != 0:
        lora += np.where(clean_brk60, bon_brk60, 0.0)
    if pen_yizi_crowd != 0:
        lora += np.where(hist_fb["plate_d2_yizi_cnt"] >= 1, pen_yizi_crowd, 0.0)
    if pen_heavy_cap != 0:
        lora += np.where(hist_fb["mcap"] > 120.0, pen_heavy_cap, 0.0)
    if bon_t1 != 0:
        lora += np.where(hist_fb["rk_theme"] == 1, bon_t1, 0.0)
    if pen_t3 != 0:
        lora += np.where(hist_fb["rk_theme"] >= 3, pen_t3, 0.0)

    sc_v = sp_v + sq_v + v18_pen + lora
    m_t1 = common_ok & open_in_win & (sp_v >= 45.0) & (sc_v >= thr_vec)
    mm = ((m_t1 & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac) | (m_t2_base & pass_l2)) & p_tight

    mmon = (
        common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090)
        & (sp_v >= 38.0) & (sc_v >= thr_vec)
        & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac & p_tight
    )
    tot_cand = (mm | (mmon & (~mm))).copy()

    # 动态龙一判定
    real_dom_no_dragon = set()
    for d in sorted(daily_t1.index):
        t1_row = daily_t1.loc[d]
        t2_row = daily_t2.loc[d] if d in daily_t2.index else None
        t1_med = float(t1_row["p_theme_med"])
        t2_med = float(t2_row["p_theme_med"]) if t2_row is not None else 0.0
        t1_sz = int(t1_row["p_sz_max"])
        t2_sz = int(t2_row["p_sz_max"]) if t2_row is not None else 1
        is_dominant = ((t1_med - t2_med) >= 20.0) or ((t1_sz >= 6) and (t1_sz / max(1, t2_sz) >= 2.0))
        if is_dominant:
            sub_d = hist_fb[hist_fb["d2_dt"] == d]
            sub_d_passed = sub_d[tot_cand[sub_d.index]]
            t1_has_passed = (sub_d_passed["plate"] == t1_row["plate"]).any() if len(sub_d_passed) > 0 else False
            if not t1_has_passed:
                real_dom_no_dragon.add(d)

    sv = np.where(mm, sc_v + 1000.0, sc_v)
    sub_tot = hist_fb[tot_cand].copy()
    sub_tot["_sv_tmp"] = sv[tot_cand]
    bad_dts = set()
    for d, grp in sub_tot.groupby("d2_dt"):
        if (grp["rk_theme"] == 1).any():
            top_rk = grp.sort_values("_sv_tmp", ascending=False).iloc[0]["rk_theme"]
            if pd.notna(top_rk) and top_rk >= 4:
                bad_dts.add(d)
    tot = tot_cand & (~hist_fb["d2_dt"].isin(bad_dts)).values

    is_blocked_alpha = np.zeros(len(hist_fb), dtype=bool)
    for idx, (d, rk) in enumerate(zip(hist_fb["d2_dt"], hist_fb["rk_theme"])):
        if d in real_dom_no_dragon and rk == 3:
            is_blocked_alpha[idx] = True
    tot = tot & (~is_blocked_alpha)

    is_blocked_beta = np.zeros(len(hist_fb), dtype=bool)
    for idx, (d, mrk, nh, hm) in enumerate(zip(
        hist_fb["d2_dt"], hist_fb["buyable_mkt_open_rk"], hist_fb["notice_hard"], hist_fb["is_ma"]
    )):
        if d in melee_days:
            is_breakout = (mrk <= 2) or bool(nh) or bool(hm)
            if not is_breakout:
                is_blocked_beta[idx] = True
    tot = tot & (~is_blocked_beta)

    df_eval = hist_fb.copy()
    df_eval["_sv_eval"] = sv
    return df_eval, tot

# 网格搜索 candidate packs
print("开始网格搜索最优微调参数...")
configs = [
    # cfg 0: V18 原版基准
    {"name": "V18_Baseline", "allow_dying": False, "dying_tax": 0.0, "thr_jump": 25.0, "bon_ma": 0.0, "bon_open": 0.0, "bon_brk": 0.0, "pen_yizi": 0.0, "pen_cap": 0.0, "bon_t1": 0.0, "pen_t3": 0.0},
    
    # cfg 1: 极简放行二波龙 + 高潮微调
    {"name": "Cfg1_DyingT1_Thr15", "allow_dying": True, "dying_tax": -15.0, "thr_jump": 15.0, "bon_ma": 10.0, "bon_open": 5.0, "bon_brk": 5.0, "pen_yizi": -10.0, "pen_cap": 0.0, "bon_t1": 0.0, "pen_t3": 0.0},
    
    # cfg 2: 适度加强重组催化与平台突破
    {"name": "Cfg2_Balanced", "allow_dying": True, "dying_tax": -15.0, "thr_jump": 15.0, "bon_ma": 15.0, "bon_open": 8.0, "bon_brk": 10.0, "pen_yizi": -10.0, "pen_cap": 0.0, "bon_t1": 0.0, "pen_t3": 0.0},

    # cfg 3: 加题材龙一加分
    {"name": "Cfg3_ThemeT1", "allow_dying": True, "dying_tax": -15.0, "thr_jump": 15.0, "bon_ma": 15.0, "bon_open": 8.0, "bon_brk": 10.0, "pen_yizi": -10.0, "pen_cap": 0.0, "bon_t1": 5.0, "pen_t3": -10.0},

    # cfg 4: dying_pulse_tax 提高到 -20 (高门票，只给最硬二波龙过)
    {"name": "Cfg4_StrictDyingTax", "allow_dying": True, "dying_tax": -20.0, "thr_jump": 15.0, "bon_ma": 15.0, "bon_open": 8.0, "bon_brk": 10.0, "pen_yizi": -10.0, "pen_cap": 0.0, "bon_t1": 0.0, "pen_t3": 0.0},
]

rows = []
for c in configs:
    df_e, tot_m = evaluate_candidate_pack(
        allow_dying_pulse_in_t1=c["allow_dying"],
        dying_pulse_tax=c["dying_tax"],
        thr_jump_val=c["thr_jump"],
        bon_ma=c["bon_ma"],
        bon_open_sweet=c["bon_open"],
        bon_brk60=c["bon_brk"],
        pen_yizi_crowd=c["pen_yizi"],
        pen_heavy_cap=c["pen_cap"],
        bon_t1=c["bon_t1"],
        pen_t3=c["pen_t3"],
    )
    
    # 算各期
    r_q4 = run_simulation(df_e, "_sv_eval", tot_m, start_dt="2026-10-01", end_dt="2026-11-13")
    r_jul = run_simulation(df_e, "_sv_eval", tot_m, start_dt="2026-07-01", end_dt="2026-11-13")
    r_26 = run_simulation(df_e, "_sv_eval", tot_m, start_dt="2026-01-01", end_dt="2026-11-13")
    r_3y = run_simulation(df_e, "_sv_eval", tot_m, start_dt="2023-11-10", end_dt="2026-11-13")
    r_5y = run_simulation(df_e, "_sv_eval", tot_m, start_dt="2021-11-01", end_dt="2026-11-13")

    rows.append({
        "Config": c["name"],
        "26Q4_N": r_q4["trades_count"], "26Q4_WR%": r_q4["win_rate"], "26Q4_Nav": r_q4["nav_1s"],
        "Jul_N": r_jul["trades_count"], "Jul_WR%": r_jul["win_rate"], "Jul_Nav": r_jul["nav_1s"],
        "26All_N": r_26["trades_count"], "26All_WR%": r_26["win_rate"], "26All_Nav": r_26["nav_1s"],
        "3Y_N": r_3y["trades_count"], "3Y_WR%": r_3y["win_rate"], "3Y_Nav": r_3y["nav_1s"],
        "5Y_N": r_5y["trades_count"], "5Y_WR%": r_5y["win_rate"], "5Y_Nav": r_5y["nav_1s"],
    })

res_grid = pd.DataFrame(rows)
print("\n" + "=" * 90)
print("【网格搜索方案全景对比】")
print("=" * 90)
print(res_grid.to_string(index=False))
