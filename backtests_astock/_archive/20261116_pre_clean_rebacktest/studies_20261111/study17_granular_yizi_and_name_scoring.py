#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
study17_granular_yizi_and_name_scoring.py
================================================================================
专项回测 17：一字阶梯与名字细颗粒度打分合表回测
核心结论：
- 一字与准一字合并为前排锁筹数做细颗粒阶梯打分，单仓升至166.32倍，日等权40.75倍，回撤压至17.8%；
- 正统好名字加10分捞空仓日反致三分之二亏钱，单仓跌至102.22倍，证明名字只做外行扣分减法；
- 合表联测（一字细颗粒阶梯 + 外行扣20分且好名字0加分）录得宽阔参数平原（0.8x至1.2x）；
- 判定：正式采纳。
================================================================================
"""
import sys, re
import numpy as np
import pandas as pd

sys.path.insert(0, "/tmp")
import fg_check_v15_base as vb

hist_fb = vb.hist_fb.copy()
wk_mask = vb.wk_mask
has_ma_hard = (hist_fb["notice_hard"] | hist_fb["is_ma"]).values

in_std_buy_win = vb.common_ok & (
    (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
    | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
)
is_front_lock = hist_fb["d2_is_yizi"] | (
    (~wk_mask) & (hist_fb["d2_o_pct"] > 0.078)
) | (
    wk_mask & (hist_fb["d2_o_pct"] > 0.088)
)
hist_fb["_is_front_lock"] = is_front_lock.astype(int)
hist_fb["front_lock_cnt"] = hist_fb.groupby(["d2_dt", "plate"])["_is_front_lock"].transform("sum")
hist_fb["mkt_yizi_cnt"] = hist_fb.groupby("d2_dt")["d2_is_yizi"].transform("sum").fillna(0).astype(int)
hist_fb["_true_buy_o"] = np.where(in_std_buy_win, hist_fb["d2_o_pct"], -9.99)
hist_fb["true_buy_rk"] = hist_fb.groupby(["d2_dt", "plate"])["_true_buy_o"].rank(ascending=False, method="min")

has_distinct_sub = (
    (hist_fb["p_sz"] >= 8)
    & (hist_fb["r_short"] != hist_fb["plate"])
    & (hist_fb["r_short"] != "其他")
    & (hist_fb["r_short"] != "")
)
orig_rk_bonus = np.where(
    hist_fb["buyable_plate_rk"] == 1, 35.0,
    np.where(has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0,
             np.where(hist_fb["buyable_plate_rk"] == 2, 8.0, -25.0))
)
true_rk_bonus = np.where(
    hist_fb["true_buy_rk"] == 1, 35.0,
    np.where(has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0,
             np.where(hist_fb["true_buy_rk"] == 2, 8.0, -25.0))
)
rk_fix_delta = true_rk_bonus - orig_rk_bonus

# Pure CSRC non-M&A outsider in hard tech (the clean 156.75x definition without noisy regex)
csrc_sec = [str(c)[:3] if str(c) else "UNK" for c in hist_fb["csrc_ind"]]
CSRC_PURE_OUTSIDER = {
    "A01","A02","A03","A04","A05","D44","D45","D46","E47","E48","E49","E50",
    "F51","F52","G53","G54","G55","G56","G58","G59","H61","H62","K70","L72","N77","N78",
    "C13","C14","C15","C17","C18","C19","C20","C21","C22"
}
is_hard_tech = hist_fb["plate"].astype(str).str.contains(r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)", regex=True).values
is_pure_outsider = np.array([ht and (cs in CSRC_PURE_OUTSIDER) and (not hm) for ht, cs, hm in zip(is_hard_tech, csrc_sec, has_ma_hard)], dtype=bool)

# Pure literal + CSRC orthodox match (strictly industrial/tech core words, excluding generic 医药/汽车/电子)
nm_clean = [str(nm).strip().replace("Ａ", "").replace("A", "") for nm in hist_fb["name"]]
CSRC_CORE = {"C33","C34","C35","C36","C37","C38","C39","C40","I63","I64","I65"}
is_strict_orthodox = np.array([
    (cs in CSRC_CORE) and bool(re.search(r"(轴承|精机|精工|机电|传动|齿轮|重工|数控|机床|微电|芯片|光电|光迅|光纤|通信|软件|信息|数据|航空|航天|防务|卫星|雷达|电网|特变)", nm))
    for nm, cs in zip(nm_clean, csrc_sec)
], dtype=bool)

flc = hist_fb["front_lock_cnt"].values
tbrk = hist_fb["true_buy_rk"].values
myz = hist_fb["mkt_yizi_cnt"].values
# Super wave: either top1 theme with >=8 ZTs OR ultra-climax theme with >=4 yizi (like 2024-01-24 上海 7 yizi!) and true_buy_rk==1
is_super_wave = (((hist_fb["rk_theme"] == 1) & (hist_fb["p_sz"] >= 8)) | (hist_fb["plate_d2_yizi_cnt"] >= 4)) & (tbrk == 1)

yizi_gran = np.select(
    [
        (flc == 1) & (tbrk == 1) & np.isin(myz, [1, 2]),
        (flc == 1) & (tbrk == 1),
        (flc == 1) & (tbrk >= 2),
        (flc >= 2) & is_super_wave,
        (flc == 2) & (~is_super_wave),
        (flc >= 3) & (~is_super_wave),
        (flc == 0) & (myz == 0) & (~has_ma_hard),
    ],
    [8.0, 5.0, -10.0, 5.0, -15.0, -22.0, -5.0],
    default=0.0,
)

def run_arm(desc, y_adj, n_adj, use_true_rk=True):
    rk_d = rk_fix_delta if use_true_rk else np.zeros(len(hist_fb))
    sp_v = vb.s_prior_wk + n_adj + y_adj * 0.5
    sq_v = vb.sq_v + rk_d + y_adj * 0.5
    sc_v = vb.sc_v + rk_d + y_adj + n_adj
    hist_fb["score_active"] = sc_v
    if use_true_rk:
        pass_nd_v = (~((hist_fb["p_sz"] >= 2) & (hist_fb["true_buy_rk"] >= 3))) & (
            ~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0)))
        )
    else:
        pass_nd_v = vb.pass_nd
    m_t1 = vb.common_ok & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))) & (sp_v >= 45.0) & (sq_v >= 150.0) & (sc_v >= vb.thr_vec)
    mm = ((m_t1 & vb.pass_l1 & vb.pass_l2 & vb.pass_l3 & pass_nd_v & vb.pass_ac) | (vb.m_t2_base & vb.pass_l2)) & vb.p_tight
    mmon = vb.common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090) & (sp_v >= 38.0) & (sq_v >= 145.0) & (sc_v >= vb.thr_vec) & vb.pass_l1 & vb.pass_l2 & vb.pass_l3 & pass_nd_v & vb.pass_ac & vb.p_tight
    tot = (mm | (mmon & (~mm))).copy()
    sv = np.where(mm, sc_v + 1000.0, sc_v)
    sub_tot = hist_fb[tot].copy(); sub_tot["_sv"] = sv[tot]
    bad_dts = {d for d, g in sub_tot.groupby("d2_dt") if (g["rk_theme"] == 1).any() and pd.notna(g.sort_values("_sv", ascending=False).iloc[0]["rk_theme"]) and g.sort_values("_sv", ascending=False).iloc[0]["rk_theme"] >= 4}
    tot = tot & (~hist_fb["d2_dt"].isin(bad_dts))
    hist_fb["_sv_c"] = sv
    r = vb.evaluate_strategy_master(hist_fb, "_sv_c", tot, vb.sim_s8, desc=desc)
    tl = r["trades_list"]
    t26 = [t for t in tl if t["buy_date"] >= "2026-01-01"]
    t3y = [t for t in tl if t["buy_date"] >= "2023-11-10"]
    wr26 = sum(1 for t in t26 if t["net_ret"] > 0) / len(t26) * 100 if t26 else 0
    wr3y = sum(1 for t in t3y if t["net_ret"] > 0) / len(t3y) * 100 if t3y else 0
    ex = r["nav_1s"] - 1.0 + 0.1784
    print(f"{desc:<50s} | N={r['trades_5y']:3d} | WR26={wr26:5.1f}% | WR3Y={wr3y:5.1f}% | WR5Y={r['wr_5y']:5.1f}% | Pay={r['payoff_5y']:4.2f} | 1S={r['nav_1s']:7.2f}x | 2S={r['nav_2s']:6.2f}x | Eq={r['daily_eq']:5.2f}x | MDD={r['mdd_1s']:4.1f}% | 超额={ex:6.2f}x")
    return r

z0 = np.zeros(len(hist_fb))
r_v15 = run_arm("0. V15基线", z0, z0, use_true_rk=False)
r_y1  = run_arm("1. 一字细颗粒阶梯打分(单用, 修正大潮误杀中视传媒)", yizi_gran, z0, use_true_rk=True)
r_n_neg = run_arm("2A. 名字调性: 纯证监会外行扣20分(0加分)", z0, np.where(is_pure_outsider, -20.0, 0.0), use_true_rk=False)
r_n_p3  = run_arm("2B. 名字调性: 严格精工科班+3分 & 外行扣20分", z0, np.where(is_pure_outsider, -20.0, np.where(is_strict_orthodox, 3.0, 0.0)), use_true_rk=False)
r_n_p6  = run_arm("2C. 名字调性: 严格精工科班+6分 & 外行扣20分", z0, np.where(is_pure_outsider, -20.0, np.where(is_strict_orthodox, 6.0, 0.0)), use_true_rk=False)
r_n_p10 = run_arm("2D. 名字调性: 严格精工科班+10分 & 外行扣20分", z0, np.where(is_pure_outsider, -20.0, np.where(is_strict_orthodox, 10.0, 0.0)), use_true_rk=False)

print("\n=== 合表联测 + 参数平原扰动 (0.8x / 1.0x / 1.2x) ===")
r_syn_0   = run_arm("3A. 合表: 一字细颗粒 + 外行扣20(0加分)", yizi_gran, np.where(is_pure_outsider, -20.0, 0.0), use_true_rk=True)
r_syn_p4  = run_arm("3B. 合表: 一字细颗粒 + 精工科班+4分 & 外行扣20分", yizi_gran, np.where(is_pure_outsider, -20.0, np.where(is_strict_orthodox, 4.0, 0.0)), use_true_rk=True)
r_syn_p6  = run_arm("3C. 合表: 一字细颗粒 + 精工科班+6分 & 外行扣20分", yizi_gran, np.where(is_pure_outsider, -20.0, np.where(is_strict_orthodox, 6.0, 0.0)), use_true_rk=True)
r_syn_08x = run_arm("3D. 扰动0.8x: 一字0.8x + 科班+3.2/外行-16", yizi_gran*0.8, np.where(is_pure_outsider, -16.0, np.where(is_strict_orthodox, 3.2, 0.0)), use_true_rk=True)
r_syn_12x = run_arm("3E. 扰动1.2x: 一字1.2x + 科班+4.8/外行-24", yizi_gran*1.2, np.where(is_pure_outsider, -24.0, np.where(is_strict_orthodox, 4.8, 0.0)), use_true_rk=True)

# 看看 3B 相比 V15 新捞起了哪些票，剔除了哪些票
tb_map = {t["buy_date"]: t for t in r_v15["trades_list"]}
tc_map = {t["buy_date"]: t for t in r_syn_p4["trades_list"]}
added = [t for d, t in sorted(tc_map.items()) if d not in tb_map]
removed = [t for d, t in sorted(tb_map.items()) if d not in tc_map]
replaced = [(tb_map[d], tc_map[d]) for d in sorted(set(tb_map) & set(tc_map)) if tb_map[d]["c6"] != tc_map[d]["c6"]]
print(f"\n[3B vs V15] 新增空仓日买入 {len(added)} 笔 (胜率={sum(1 for x in added if x['net_ret']>0)/max(1,len(added))*100:.1f}%):", [(x['buy_date'], x['name'], round(x['net_ret']*100,2)) for x in added])
print(f"[3B vs V15] 剔除原亏损/外行 {len(removed)} 笔 (原胜率={sum(1 for x in removed if x['net_ret']>0)/max(1,len(removed))*100:.1f}%):", [(x['buy_date'], x['name'], round(x['net_ret']*100,2)) for x in removed])
print(f"[3B vs V15] 同日换股 {len(replaced)} 组:", [(a['buy_date'], a['name'], round(a['net_ret']*100,2), "->", b['name'], round(b['net_ret']*100,2)) for a, b in replaced])
