#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
extract_1to2_broad_candidates.py
从 /tmp/astock_hist_fb_v17_cache.pkl 提取全部通过硬骨架且 score_active >= thr_vec - 18.0 的一进二候选
"""
import pickle, sys, os, time
import pandas as pd, numpy as np

ROOT = "/Users/huaichuaibeimeng/claude-projects"
sys.path.insert(0, f"{ROOT}/sim-portfolio/backtests_astock/special_26q4/1to2_26q4")

# 1. 载入缓存
with open("/tmp/astock_hist_fb_v17_cache.pkl", "rb") as f:
    hist_fb_12 = pickle.load(f)

with open("/tmp/astock_price_lookup.pkl", "rb") as f:
    pl_data_12 = pickle.load(f)
price_lookup_12 = pl_data_12["price_lookup"]
all_dts_12 = pl_data_12["all_dts"]
dt_to_idx_12 = {d: i for i, d in enumerate(all_dts_12)}

df_5m_12 = pd.read_parquet(f"{ROOT}/sim-portfolio/data/cand_5m_bars_v15_complete.parquet")
df_5m_12["hhmm_int"] = df_5m_12["hhmm"].astype(int)
df_5m_12.sort_values(["c6", "date", "hhmm_int"], inplace=True)
bars_5m_map_12 = {}
for (c6, dt), grp in df_5m_12.groupby(["c6", "date"], sort=False):
    bars_5m_map_12[(c6, dt)] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy()

# 2. 从 run_master_26q4 提取核心打分逻辑 (带 thr_offset 参数)
from run_master_26q4 import build_model, make_trade_engine

print("Running build_model...")
df_v18, tot_v18 = build_model(hist_fb_12.copy(), is_26q4=False)

# 重新计算放宽门槛 -18.0 的掩码
wk_mask = df_v18["gap_days"] >= 3
thr_vec = np.where(df_v18["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)
thr_broad = thr_vec - 18.0

sc_v = df_v18["score_active"].values
common_ok = df_v18["is_buyable_open"] & (~df_v18["nuclear_halt"]) & (~df_v18["promo_freeze"])
pass_l1 = ~df_v18["is_event_basket"]
pass_l2 = ~df_v18["is_dying_pulse"]
pass_l3 = (df_v18["plate_fb_cnt"] <= 1) | ((df_v18["plate_peers_open_avg"] >= -0.010) & ((df_v18["plate_d2_open_avg"] >= -0.005) | (df_v18["plate_high_open_cnt"] >= 2)))
pass_ac = ~(df_v18["p_sz"] > 35) & (~df_v18["notice_bad"])
p_tight = (df_v18["d1_seal_tightness"] >= 37.0).values
open_in_win = (
    (wk_mask & df_v18["d2_o_pct"].between(0.020, 0.088))
    | ((~wk_mask) & df_v18["d2_o_pct"].between(0.022, 0.078))
).values

# 放宽条件: sc_v >= thr_broad
sp_v = df_v18["s_prior_dual"].values
m_t1_broad = common_ok & open_in_win & (sp_v >= 45.0) & (sc_v >= thr_broad)

is_front_lock = df_v18["d2_is_yizi"] | ((~wk_mask) & (df_v18["d2_o_pct"] > 0.078)) | (wk_mask & (df_v18["d2_o_pct"] > 0.088))
df_v18["_is_front_lock"] = is_front_lock.astype(int)
in_std_buy_win = common_ok & (
    (wk_mask & df_v18["d2_o_pct"].between(0.020, 0.088))
    | ((~wk_mask) & df_v18["d2_o_pct"].between(0.022, 0.078))
)
df_v18["_true_buy_o"] = np.where(in_std_buy_win, df_v18["d2_o_pct"], -9.99)
true_buy_rk = df_v18.groupby(["d2_dt", "plate"])["_true_buy_o"].rank(ascending=False, method="min").values
pass_nd_true = (~((df_v18["p_sz"] >= 2) & (true_buy_rk >= 3))) & (
    ~((df_v18["plate_d2_yizi_cnt"] >= 1) & (df_v18["d1_seal_tightness"] < 15.0))
)

m_t2_base = common_ok & (df_v18["p_sz"] == 1) & (df_v18["is_pioneer_word"] | df_v18["notice_hard"] | df_v18["is_ma"] | df_v18["has_new_term"] | df_v18["own_new_term"]) & df_v18["d2_o_pct"].between(0.035, 0.078) & (df_v18["buyable_mkt_open_rk"] <= 3) & (df_v18["d1_seal_tightness"] >= 15.0) & ((df_v18["f_dd20_d0"] <= 0.88) | (df_v18["clean_brk60"] == 1))

mm_broad = ((m_t1_broad & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac) | (m_t2_base & pass_l2)) & p_tight
mmon_broad = (
    common_ok & wk_mask & df_v18["d2_o_pct"].between(0.015, 0.090)
    & (sp_v >= 38.0) & (sc_v >= thr_broad)
    & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac & p_tight
)
tot_broad = (mm_broad | (mmon_broad & (~mm_broad))).copy()

print(f"tot_v18 count: {tot_v18.sum()}, tot_broad count: {tot_broad.sum()}")

fn_trade_12 = make_trade_engine(fee=0.0020)

sub_broad = df_v18[tot_broad & (df_v18["d2_dt"] >= "2021-11-15") & (df_v18["d2_dt"] <= "2026-11-16")].copy()
sub_broad.sort_values(["d2_dt", "_sv_eval"], ascending=[True, False], inplace=True)

cands_1to2_broad = []
for d2, grp in sub_broad.groupby("d2_dt", sort=True):
    top_r = grp.iloc[0]
    tr = fn_trade_12(top_r)
    triggered = bool(tr is not None)
    sc = float(top_r["score_active"])
    base_t = float(thr_vec[top_r.name])
    
    op_pct = float(top_r.get("d2_o_pct", 0.0))
    if triggered:
        is_monday = top_r.get("gap_days", 1) >= 3
        cand_score = top_r.get("score_active", top_r.get("score_0", 0.0))
        cand_lead = top_r.get("buy_open_lead", 0.0)
        do_direct = is_monday and (cand_score >= 310.0) and (cand_lead >= 0.025)
        if do_direct:
            b_hhmm = 925
        else:
            trig_p = float(top_r["trig_p"])
            arr2 = bars_5m_map_12.get((top_r["c6"], top_r["d2_dt"]))
            ign_hhmm = 935
            if arr2 is not None and len(arr2) > 0:
                for bi in range(len(arr2)):
                    if arr2[bi, 2] >= trig_p - 1e-4:
                        ign_hhmm = int(arr2[bi, 0])
                        break
            b_hhmm = ign_hhmm
            
        b_px = float(tr.get("buy_price", top_r.get("open", 0.0)))
        ed = str(tr.get("exit_date", d2))
        if tr.get("exit_at_open", False): e_hhmm = 925
        elif tr.get("tag") == "5m_1030_weak_cut": e_hhmm = 1035
        elif tr.get("tag") == "5m_1430_rush": e_hhmm = 1435
        else: e_hhmm = 1500
        epx = float(tr.get("exit_price", b_px))
        r_net = float(tr.get("net_ret", 0.0))
    else:
        b_hhmm, b_px, ed, e_hhmm, epx, r_net = 935, 0.0, str(d2), 1500, 0.0, 0.0

    cands_1to2_broad.append({
        "strategy": "一进二_V18",
        "code": str(top_r["c6"]).zfill(6),
        "name": str(top_r["name"]),
        "buy_date": str(d2),
        "score": round(sc, 1),
        "base_threshold": round(base_t, 1),
        "is_base_passed": bool(sc >= base_t),
        "triggered": triggered,
        "buy_hhmm": b_hhmm,
        "buy_price": round(b_px, 2),
        "exit_date": ed,
        "exit_hhmm": e_hhmm,
        "exit_price": round(epx, 2),
        "net_ret": round(r_net, 6),
        "open_pct": round(op_pct, 4)
    })

print(f"Extracted 1to2 broad candidates: {len(cands_1to2_broad)} rows (triggered: {sum(c['triggered'] for c in cands_1to2_broad)})")
with open("/tmp/cands_1to2_broad.pkl", "wb") as f:
    pickle.dump(cands_1to2_broad, f)
print("Saved to /tmp/cands_1to2_broad.pkl")
