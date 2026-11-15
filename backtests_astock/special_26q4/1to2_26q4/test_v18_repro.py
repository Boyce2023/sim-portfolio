#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
test_v18_repro.py
================================================================================
验证在 /tmp/astock_hist_fb_v17_cache.pkl 上运行原版 V18 规则是否 100% 复现 95 笔台账
================================================================================
"""

import os
import sys
import pickle
import numpy as np
import pandas as pd

SIM_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
BACKTEST_ASTOCK_DIR = f"{SIM_DIR}/backtests_astock"
PARQUET_5M_COMPLETE = f"{SIM_DIR}/data/cand_5m_bars_v15_complete.parquet"
ORIG_LEDGER_CSV = f"{BACKTEST_ASTOCK_DIR}/full_day_by_day_v18_ledger.csv"

# 1. 载入缓存
with open("/tmp/astock_hist_fb_v17_cache.pkl", "rb") as f:
    hist_fb = pickle.load(f)

with open("/tmp/astock_price_lookup.pkl", "rb") as f:
    pl_data = pickle.load(f)
price_lookup = pl_data["price_lookup"]
all_dts = pl_data["all_dts"]
dt_to_idx = {d: i for i, d in enumerate(all_dts)}

# 2. 载入 5m bars
df_5m = pd.read_parquet(PARQUET_5M_COMPLETE)
df_5m["hhmm_int"] = df_5m["hhmm"].astype(int)
df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
bars_5m_map = {}
for (c6, dt), grp in df_5m.groupby(["c6", "date"], sort=False):
    bars_5m_map[(c6, dt)] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy()

print(f"5m bars loaded: {len(bars_5m_map)} bars")

# 3. 运行 V18 原始打分与规则判定
seal_time = hist_fb["first_seal_time"].fillna("99:99:99")
open_cnt = hist_fb["open_board_count"].fillna(0)
dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
clean_brk60 = hist_fb["clean_brk60"].values == 1

is_granularity = hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
bonus_spear = np.where(is_granularity, 15.0, 0.0) + np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))

common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
pass_l1 = ~hist_fb["is_event_basket"]
pass_l2 = ~hist_fb["is_dying_pulse"]
pass_l3 = (hist_fb["plate_fb_cnt"] <= 1) | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2)))
pass_ac = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
wk_mask = hist_fb["gap_days"] >= 3
thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)

f3_bonus = np.where(hist_fb["notice_bad"], -35.0, 0.0)
hist_fb["score_wk"] = hist_fb["score_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
hist_fb["s_prior_wk"] = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus

m_t2_base = common_ok & (hist_fb["p_sz"] == 1) & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"]) & hist_fb["d2_o_pct"].between(0.035, 0.078) & (hist_fb["buyable_mkt_open_rk"] <= 3) & (hist_fb["d1_seal_tightness"] >= 15.0) & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))

in_std_buy_win = common_ok & (
    (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
    | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
)
is_front_lock = hist_fb["d2_is_yizi"] | ((~wk_mask) & (hist_fb["d2_o_pct"] > 0.078)) | (wk_mask & (hist_fb["d2_o_pct"] > 0.088))
hist_fb["_is_front_lock"] = is_front_lock.astype(int)
hist_fb["front_lock_cnt"] = hist_fb.groupby(["d2_dt", "plate"])["_is_front_lock"].transform("sum")
hist_fb["mkt_yizi_cnt"] = hist_fb.groupby("d2_dt")["d2_is_yizi"].transform("sum").fillna(0).astype(int)

hist_fb["_true_buy_o"] = np.where(in_std_buy_win, hist_fb["d2_o_pct"], -9.99)
hist_fb["true_buy_rk"] = hist_fb.groupby(["d2_dt", "plate"])["_true_buy_o"].rank(ascending=False, method="min")

has_distinct_sub = (hist_fb["p_sz"] >= 8) & (hist_fb["r_short"] != hist_fb["plate"]) & (hist_fb["r_short"] != "其他") & (hist_fb["r_short"] != "")
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

pass_nd_true = (~((hist_fb["p_sz"] >= 2) & (hist_fb["true_buy_rk"] >= 3))) & (
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

flc = hist_fb["front_lock_cnt"].values
tbrk = hist_fb["true_buy_rk"].values
myz = hist_fb["mkt_yizi_cnt"].values
is_super_wave = (hist_fb["rk_theme"] == 1) & (hist_fb["p_sz"] >= 8) & (tbrk == 1)

def get_yizi_gran_v17():
    return np.select(
        [
            (flc == 1) & (tbrk == 1) & np.isin(myz, [1, 2]),
            (flc == 1) & (tbrk == 1),
            (flc == 1) & (tbrk >= 2),
            (flc >= 2) & is_super_wave,
            (flc == 2) & (~is_super_wave),
            (flc >= 3) & (~is_super_wave),
            (flc == 0) & (myz == 0) & (~has_ma_hard),
        ],
        [8.0, 0.0, 0.0, 5.0, -15.0, -22.0, -5.0],
        default=0.0,
    )

y_v17 = get_yizi_gran_v17()

# 传感器 roll20_ho_zt
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

sp_v = hist_fb["s_prior_wk"].values + name_sub20 + y_v17 * 0.5
sq_v = hist_fb["s_quant_dual"].values + q_pen + d_ov + bon_tape + rk_fix_delta + y_v17 * 0.5
sc_v = sp_v + sq_v + v18_pen
hist_fb["score_active"] = sc_v

p_tight = (hist_fb["d1_seal_tightness"] >= 37.0).values
open_in_win = (
    (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
    | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
).values

m_t1 = common_ok & open_in_win & (sp_v >= 45.0) & (sc_v >= thr_vec)
mm = ((m_t1 & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac) | (m_t2_base & pass_l2)) & p_tight

mmon = (
    common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090)
    & (sp_v >= 38.0) & (sc_v >= thr_vec)
    & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac & p_tight
)
tot_cand = (mm | (mmon & (~mm))).copy()

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
        t1_plate = t1_row["plate"]
        sub_d = hist_fb[hist_fb["d2_dt"] == d]
        sub_d_passed = sub_d[tot_cand[sub_d.index]]
        t1_has_passed = (sub_d_passed["plate"] == t1_plate).any() if len(sub_d_passed) > 0 else False
        if not t1_has_passed:
            dom_no_dragon.add(d)

    if t1_row is not None and t2_row is not None and t3_row is not None:
        t3_med = float(t3_row["p_theme_med"])
        range_top3 = t1_med - t3_med
        sz_max = max(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
        sz_min = min(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
        if range_top3 <= 15.0 and sz_max <= 5 and sz_min >= 2:
            melee_days.add(d)

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
    if d in dom_no_dragon and rk == 3:
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

hist_fb["_sv_eval"] = sv

# 导入 master walkforward 评估
def make_v17_trade_engine(fee=0.003):
    def sim_trade(row):
        c6, d2 = row["c6"], row["d2_dt"]
        idx2 = dt_to_idx.get(d2, -1)
        if idx2 < 0 or idx2 >= len(all_dts) - 1:
            return None
        d2_bar = price_lookup.get((c6, d2))
        if not d2_bar:
            return None
        o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = d2_bar[:8]
        if o2 >= zt2 - 0.005 or o2 <= 0:
            return None

        is_monday = row.get("gap_days", 1) >= 3
        cand_score = row.get("score_active", row.get("score_0", 0.0))
        cand_lead = row.get("buy_open_lead", 0.0)
        do_direct = is_monday and (cand_score >= 310.0) and (cand_lead >= 0.025)
        trig_p = float(row["trig_p"])
        buy_px = round(float(o2), 2) if do_direct else round(trig_p, 2)
        if not do_direct:
            if h2 < trig_p or trig_p >= zt2 - 0.005:
                return None
            arr2 = bars_5m_map.get((c6, d2))
            if arr2 is not None and len(arr2) > 0:
                ign_hhmm = None
                for bi in range(len(arr2)):
                    if arr2[bi, 2] >= trig_p - 1e-4:
                        ign_hhmm = int(arr2[bi, 0])
                        break
                if ign_hhmm is not None and ign_hhmm > 1130:
                    return None

        prev_c = round(float(c2), 2)
        idx3 = idx2 + 1
        d3 = all_dts[idx3]
        d3_bar = price_lookup.get((c6, d3))
        if not d3_bar:
            net = round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4)
            return {"net_ret": net, "exit_date": d3, "exit_at_open": True, "sealed_2b": int(is_zt2), "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}
        o3, h3, l3, c3, zt3, dt3, is_zt3, is_yz_dt3 = d3_bar[:8]

        if not is_zt2:
            d2_closed_up = (c2 >= float(row["close"]))
            if d2_closed_up and (o3 >= round(c2 * 1.005, 2)) and not is_yz_dt3:
                if is_zt3:
                    curr = idx3 + 1
                    boards_held = 3
                    used_immunity = False
                    prev_c = round(float(c3), 2)
                    while curr < len(all_dts) and (curr - idx2 <= 12):
                        dc = all_dts[curr]
                        b = price_lookup.get((c6, dc))
                        if not b: break
                        oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b[:8]
                        if iyzc:
                            prev_c = round(float(cc), 2); curr += 1; continue

                        arr = bars_5m_map.get((c6, dc))
                        if arr is not None and len(arr) >= 12:
                            idx_1030 = -1
                            cum_v, cum_a = 0.0, 0.0
                            for bi in range(len(arr)):
                                cum_v += arr[bi, 5]; cum_a += arr[bi, 6]
                                if arr[bi, 0] == 1030:
                                    idx_1030 = bi; break
                            if idx_1030 >= 0:
                                bc_1030 = arr[idx_1030, 4]
                                vwap_1030 = cum_a / cum_v if cum_v > 0 else bc_1030
                                if bc_1030 >= ztc - 0.01:
                                    for bi in range(idx_1030 + 1, len(arr) - 1):
                                        if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                            px = round(float(arr[bi + 1, 1]), 2)
                                            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1430_rush"}
                                    if iztc:
                                        prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                                    else:
                                        px = round(float(cc), 2)
                                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_break"}
                                elif bc_1030 < vwap_1030:
                                    px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1030_weak_cut"}
                                else:
                                    if iztc:
                                        prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                                    if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                                        used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                                    px = round(float(cc), 2)
                                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}

                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                        px = round(float(cc), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}
                    return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}
                else:
                    px = round(float(c3), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": d3, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "nshape_d3_close"}

            curr = idx3
            while curr < len(all_dts):
                b = price_lookup.get((c6, all_dts[curr]))
                if not b or not b[7]:
                    px = round(float(b[0]), 2) if b else prev_c
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[curr], "exit_at_open": True, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "fail_open_cut"}
                curr += 1
            return None

        # 分支 2：买入日封死二板
        curr = idx3
        boards_held = 2
        used_immunity = False
        while curr < len(all_dts) and (curr - idx2 <= 12):
            dc = all_dts[curr]
            b = price_lookup.get((c6, dc))
            if not b: break
            oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b[:8]
            if iyzc:
                prev_c = round(float(cc), 2); curr += 1; continue

            arr = bars_5m_map.get((c6, dc))
            if arr is not None and len(arr) >= 12:
                idx_1030 = -1
                cum_v, cum_a = 0.0, 0.0
                for bi in range(len(arr)):
                    cum_v += arr[bi, 5]; cum_a += arr[bi, 6]
                    if arr[bi, 0] == 1030:
                        idx_1030 = bi; break
                if idx_1030 >= 0:
                    bc_1030 = arr[idx_1030, 4]
                    vwap_1030 = cum_a / cum_v if cum_v > 0 else bc_1030
                    if bc_1030 >= ztc - 0.01:
                        for bi in range(idx_1030 + 1, len(arr) - 1):
                            if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                px = round(float(arr[bi + 1, 1]), 2)
                                return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1430_rush"}
                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        else:
                            px = round(float(cc), 2)
                            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_break"}
                    elif bc_1030 < vwap_1030:
                        px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1030_weak_cut"}
                    else:
                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                        px = round(float(cc), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}

            if iztc:
                prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
            if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
            px = round(float(cc), 2)
            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}

        return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}

    return sim_trade
sys.path.insert(0, BACKTEST_ASTOCK_DIR)
from master_5y_zero_lookahead_walkforward import evaluate_strategy_master

fn_trade = make_v17_trade_engine(fee=0.003)

# 评估截至 2026-11-13 的全部交易
res = evaluate_strategy_master(hist_fb, "_sv_eval", tot, fn_trade, end_dt="2026-11-13", desc="Repro_V18")
trades_new = res["trades_list"]
print(f"Total trades under V18 (to 2026-11-13): {len(trades_new)}")

# 与原版 95 笔台账逐笔比对
df_orig = pd.read_csv(ORIG_LEDGER_CSV)
print(f"Original ledger trades: {len(df_orig)}")

set_new = {(r["buy_date"], str(r["c6"]).zfill(6)) for r in trades_new}
set_orig = {(r["buy_date"], str(r["c6"]).zfill(6)) for _, r in df_orig.iterrows()}

diff_drop = set_orig - set_new
diff_add = set_new - set_orig
print(f"Dropped vs orig: {diff_drop}")
print(f"Added vs orig: {diff_add}")

if len(diff_drop) == 0 and len(diff_add) == 0:
    print("🎯【100% 完美复现！】原版 V18 95 笔台账一笔不差完全吻合！")
else:
    print("⚠️ 存在差异，请检查！")
