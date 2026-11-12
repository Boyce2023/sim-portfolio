#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import sys, sqlite3, json
import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock")
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean")
from master_5y_zero_lookahead_walkforward import (
    load_all_data, create_master_trade_engine, evaluate_strategy_master, FEE_RATE, FEE_RATE_DISCOUNT
)

hist_fb, price_lookup, all_dts, dt_to_idx = load_all_data()
hist_fb = hist_fb.reset_index(drop=True)

# Load 5Y zt_micro_tape for D1 exact first_seal_time, open_board_count, seal_amount!
zt_map = {}
conn = sqlite3.connect("file:sim-portfolio/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
for td, code, fst, obc, samt in conn.execute("SELECT trade_date, sec_code, first_seal_time, open_board_count, seal_amount FROM zt_micro_tape WHERE board_count = 1"):
    c6 = str(code)[:6].zfill(6)
    zt_map[(str(td), c6)] = (str(fst or ""), int(obc or 0), float(samt or 0.0))
conn.close()
print("Loaded D1 micro-tape first-board rows:", len(zt_map))

# Attach D1 micro-tape features strictly from D1 (dt_str)!
fst_sec, obc_arr, samt_arr = [], [], []
for d1, c6 in zip(hist_fb["dt_str"], hist_fb["c6"]):
    v = zt_map.get((d1, c6))
    if v is None:
        fst_sec.append(np.nan); obc_arr.append(-1); samt_arr.append(np.nan)
    else:
        ts_str, obc, sa = v
        parts = ts_str.split(":")
        sec = int(parts[0])*3600 + int(parts[1])*60 + int(parts[2]) if len(parts) == 3 else np.nan
        fst_sec.append(sec); obc_arr.append(obc); samt_arr.append(sa)
hist_fb["d1_fst_sec"] = fst_sec
hist_fb["d1_obc"] = obc_arr
hist_fb["d1_seal_amt"] = samt_arr
hist_fb["d1_seal_to_mcap"] = hist_fb["d1_seal_amt"] / (hist_fb["mcap"] * 1e8 + 1e-6)

# Reconstruct 90.98x baseline
dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
clean_brk60 = hist_fb["clean_brk60"].values == 1
is_granularity = hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
bonus_spear = np.where(is_granularity, 15.0, 0.0) + np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))
common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
pass_l1 = (~hist_fb["is_event_basket"]) & (~(hist_fb["is_broad_ind"] & (hist_fb["sub_cluster_cnt"] < 2)))
pass_l2 = (~hist_fb["is_dying_pulse"])
pass_l3 = (hist_fb["plate_fb_cnt"] <= 1) | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2)))
pass_nd = (~((hist_fb["p_sz"] >= 2) & (hist_fb["buyable_plate_rk"] >= 3))) & (~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0))))
pass_ac = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
wk_mask = hist_fb["gap_days"] >= 3
f3_bonus = np.where(hist_fb["notice_hard"], 8.0, 0.0) + np.where(hist_fb["notice_bad"], -35.0, 0.0)
thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)

q_pen15 = - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < 0.031), 15.0, 0.0)
d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)
hist_fb["s_prior_wk"] = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
hist_fb["sq_91"] = hist_fb["s_quant_dual"] + q_pen15 + d_ov
hist_fb["sc_91"] = hist_fb["s_prior_wk"] + hist_fb["sq_91"]
hist_fb["score_active"] = hist_fb["sc_91"]

m_t2 = common_ok & (hist_fb["p_sz"] == 1) & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"]) & hist_fb["d2_o_pct"].between(0.035, 0.078) & (hist_fb["buyable_mkt_open_rk"] <= 3) & (hist_fb["d1_seal_tightness"] >= 15.0) & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))
mt1_91 = common_ok & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))) & (hist_fb["s_prior_wk"] >= 45.0) & (hist_fb["sq_91"] >= 150.0) & (hist_fb["sc_91"] >= thr_vec)
mm_91 = (mt1_91 & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac) | (m_t2 & pass_l2)
mmon_91 = common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090) & (hist_fb["s_prior_wk"] >= 38.0) & (hist_fb["sq_91"] >= 145.0) & (hist_fb["sc_91"] >= thr_vec) & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac
hist_fb["msk_91"] = mm_91 | (mmon_91 & (~mm_91))
hist_fb["_s_91"] = np.where(mm_91, hist_fb["sc_91"] + 1000.0, hist_fb["sc_91"])

fn20 = create_master_trade_engine(price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.005, lock_high_pct=0.05, direct_scope="monday", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE)
r91 = evaluate_strategy_master(hist_fb, "_s_91", hist_fb["msk_91"], fn20, desc="91x")
picked_set = {(t["c6"], t["buy_date"]) for t in r91["trades_list"]}

# Now inspect ALL non-yizi buyable D2 first-board stocks in 2022-2026 (even mcap < 18亿!) to see:
# 1) How many reached >=4 consecutive boards (4b+), >=5 consecutive boards (5b+), or max 10-day gain >= 45%!
oos_all = hist_fb[(hist_fb["d2_dt"] >= "2022-01-01") & (hist_fb["d2_dt"] <= "2026-11-09") & (hist_fb["d2_open"] > 0) & (hist_fb["d2_open"] < hist_fb["d2_zt_p"] - 0.005)].copy()

max_boards_list = []
max_10d_ret_list = []
for c6, d2, d1_c in zip(oos_all["c6"], oos_all["d2_dt"], oos_all["close"]):
    idx2 = dt_to_idx.get(d2, -1)
    if idx2 < 0:
        max_boards_list.append(1); max_10d_ret_list.append(0.0)
        continue
    b_cnt = 1
    counting = True
    mx_h = d1_c
    for k in range(idx2, min(idx2 + 10, len(all_dts))):
        bar = price_lookup.get((c6, all_dts[k]))
        if not bar: break
        mx_h = max(mx_h, bar[1])
        if counting and bar[6]: # is_zt
            b_cnt += 1
        else:
            counting = False
    max_boards_list.append(b_cnt)
    max_10d_ret_list.append(mx_h / (d1_c + 1e-6) - 1.0)

oos_all["max_boards"] = max_boards_list
oos_all["max_10d_ret"] = max_10d_ret_list
oos_all["in_msk91"] = oos_all["msk_91"]
oos_all["in_picked114"] = [(c, d) in picked_set for c, d in zip(oos_all["c6"], oos_all["d2_dt"])]

b5 = oos_all[oos_all["max_boards"] >= 5]
b4 = oos_all[oos_all["max_boards"] >= 4]
super_bull = oos_all[(oos_all["max_boards"] >= 5) | (oos_all["max_10d_ret"] >= 0.55)]

print(f"\n=== 1. COVERAGE OF 5-BOARD+ & SUPER MONSTER DRAGONS (2022-2026 NON-YIZI D2) ===")
print(f"Total non-yizi D2 first-boards: {len(oos_all)}")
print(f"4-board+ dragons: {len(b4)} | Passed msk_91: {b4['in_msk91'].sum()} | Picked in 114 trades: {b4['in_picked114'].sum()}")
print(f"5-board+ dragons: {len(b5)} | Passed msk_91: {b5['in_msk91'].sum()} | Picked in 114 trades: {b5['in_picked114'].sum()}")
print(f"Super Monsters (5b+ or 10d>=+55%): {len(super_bull)} | Passed msk_91: {super_bull['in_msk91'].sum()} | Picked in 114: {super_bull['in_picked114'].sum()}")

print("\n--- MCAP DISTRIBUTION OF 5-BOARD+ DRAGONS VS OUR 114 PICKED TRADES ---")
for lo, hi, lbl in [(0, 18, "<18亿 (HARD BLOCKED!)"), (18, 35, "18-35亿 (-20pt mcap & -25pt amt PENALTY!)"), (35, 60, "35-60亿 (0~+10pt)"), (60, 155, "60-155亿 (+28pt sweetspot)"), (155, 9999, ">155亿")]:
    n_5b = len(b5[(b5["mcap"] >= lo) & (b5["mcap"] < hi)])
    n_sb = len(super_bull[(super_bull["mcap"] >= lo) & (super_bull["mcap"] < hi)])
    n_pk = len(oos_all[oos_all["in_picked114"] & (oos_all["mcap"] >= lo) & (oos_all["mcap"] < hi)])
    print(f"  {lbl:42s}: 5b+={n_5b:3d} ({n_5b/max(1,len(b5))*100:4.1f}%) | SuperBull={n_sb:3d} ({n_sb/max(1,len(super_bull))*100:4.1f}%) | Picked114={n_pk:3d} ({n_pk/114*100:4.1f}%)")

# Compare SMALL-CAP (<40亿) 5-Board+ Super Monsters vs SMALL-CAP (<40亿) Non-Monsters on D1/D2 early signs!
sm_pool = oos_all[(oos_all["mcap"] >= 12.0) & (oos_all["mcap"] < 40.0) & (~oos_all["notice_bad"]) & (~oos_all["nuclear_halt"]) & (~oos_all["promo_freeze"])].copy()
sm_win = sm_pool[sm_pool["max_boards"] >= 5]
sm_lose = sm_pool[sm_pool["max_boards"] == 1]

print(f"\n=== 2. EARLY D1/D2 SIGNS OF SMALL-CAP (<40亿) 5-BOARD+ MONSTERS (N={len(sm_win)}) VS FAILED 1-BOARD (N={len(sm_lose)}) ===")
for col, desc in [
    ("mcap", "D1 Float Mcap (亿)"),
    ("to", "D1 Turnover % (高锁仓?)"),
    ("amount", "D1 Amount (元)"),
    ("d1_fst_sec", "D1 First Seal Sec (34200=09:30, 36000=10:00)"),
    ("d1_obc", "D1 Blown Board Count (0=封死)"),
    ("d1_seal_to_mcap", "D1 Seal Amt / Mcap"),
    ("d2_o_pct", "D2 09:25 Open %"),
    ("buyable_plate_rk", "D2 Plate Open Rank"),
    ("buyable_mkt_open_rk", "D2 Market Open Rank"),
    ("p_sz", "D1 Plate ZT Count (梯队共振)"),
    ("s_prior_wk", "Theme Prior Score"),
    ("f_dd20_d0", "20D Drawdown Ratio"),
    ("f_pos20_d0", "20D Position"),
    ("clean_brk60", "60D Clean Breakout"),
]:
    w_v = sm_win[col].dropna()
    l_v = sm_lose[col].dropna()
    print(f"  {desc:44s}: 5B_Monster Med={w_v.median():8.3f} (Mean={w_v.mean():8.3f}) | Fail_1B Med={l_v.median():8.3f} (Mean={l_v.mean():8.3f})")

print("\n--- SPECIFIC RATE COMPARISONS ON SMALL-CAP (<40亿, open 2%~8.5%) ---")
sm_o = sm_pool[sm_pool["d2_o_pct"].between(0.020, 0.085)].copy()
for name, cond in [
    ("Base SmallCap (<40亿, open 2~8.5%)", pd.Series(True, index=sm_o.index)),
    ("D1 Seal <= 10:00 & 0 Blown", (sm_o["d1_fst_sec"] <= 36000) & (sm_o["d1_obc"] == 0)),
    ("D1 Low Turnover 3%~10% (高锁仓!)", sm_o["to"].between(3.0, 10.0)),
    ("Plate_Rk==1 & Plate p_sz>=3 (主线梯队领涨)", (sm_o["buyable_plate_rk"] == 1) & (sm_o["p_sz"] >= 3)),
    ("Mkt_Open_Rk <= 5 (全场竞价前5)", sm_o["buyable_mkt_open_rk"] <= 5),
    ("Combo: LowTO(2.5~11%)+EarlySeal(<=10:00,obc=0)+Rk1+Prior>=45+Open>=3.5%",
     sm_o["to"].between(2.5, 11.0) & (sm_o["d1_fst_sec"] <= 36000) & (sm_o["d1_obc"] == 0) & (sm_o["buyable_plate_rk"] == 1) & (sm_o["s_prior_wk"] >= 45.0) & (sm_o["d2_o_pct"] >= 0.035)),
    ("Combo2: EarlySeal(<=09:45,obc=0)+MktRk<=5+Prior>=45+Open>=4.0%",
     (sm_o["d1_fst_sec"] <= 35100) & (sm_o["d1_obc"] == 0) & (sm_o["buyable_mkt_open_rk"] <= 5) & (sm_o["s_prior_wk"] >= 45.0) & (sm_o["d2_o_pct"] >= 0.040)),
]:
    sub = sm_o[cond]
    if len(sub) >= 10:
        r2b = sub["d2_is_zt"].mean() * 100
        r4b = (sub["max_boards"] >= 4).mean() * 100
        r5b = (sub["max_boards"] >= 5).mean() * 100
        # Also simulate actual fn20 trade return!
        rets = [tr["net_ret"] for r in sub.to_dict("records") if (tr := fn20(r)) is not None]
        s = pd.Series(rets)
        wr = (s > 0).mean() * 100 if len(s) else 0
        pf = (s[s > 0].mean() / abs(s[s <= 0].mean())) if ((s > 0).any() and (s <= 0).any()) else 0
        print(f"  {name:72s}: N={len(s):4d} | 2B={r2b:4.1f}% | 4B+={r4b:4.1f}% | 5B+={r5b:4.1f}% | WR={wr:4.1f}% | PF={pf:4.2f} | Avg={s.mean()*100:+5.2f}%")
