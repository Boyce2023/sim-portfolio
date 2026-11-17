#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_partD_rebacktest.py
================================================================================
Wave 2 · Part D: 26Q4 专供版三大核心策略独立及纯单仓合体真账重跑引擎
================================================================================
"""

import os
import sys
import json
import pickle
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
PART_D_DIR = f"{ROOT}/sim-portfolio/backtests_astock/clean_rebacktest_20261116/partD_26q4_and_combined"
os.makedirs(PART_D_DIR, exist_ok=True)

START_DATE = "2021-11-15"
END_DATE = "2026-11-16"

# 1. 载入基准指数
with open(f"{ROOT}/sim-portfolio/backtests_astock/clean_rebacktest_20261116/csi300_canonical_20261116.json", "r", encoding="utf-8") as f:
    CSI300_BENCHMARK = json.load(f)

# 2. 载入 100% 补齐的底层数据
TOP10_PATH = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"
with open(TOP10_PATH, "r", encoding="utf-8") as f:
    holders_pit = json.load(f)

def pit_lock_lookup(c6: str, dt_str: str) -> float:
    valid = [r for r in holders_pit.get(c6, []) if r[0] < dt_str]
    if not valid:
        return 38.0
    b = max(valid, key=lambda x: x[1])
    return float(b[2])

# ==============================================================================
# 模块 1: 第 1 顺位 · 高标首阴 26Q4专供版 (门槛 96 分)
# ==============================================================================
print(">>> [1/4] 运行 第1顺位 · 高标首阴 26Q4 专供版 (门槛 96 分)...")
SRC_HIGH = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
GOLDEN_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/golden_regime_20261113"

(all_dts_h, dt_to_idx_h, by_dt_h, code_bars_h, env_stats_h, _, t_lookup_h, _, _, _, stock_reg_h, ex_reg_h, tox_dates_h, CSI_MAP_h, SH_MAP_h, SZ_MAP_h) = pickle.load(open(f"{SRC_HIGH}/part1_cache.pkl", "rb"))
dfr_h = pd.read_pickle(f"{SRC_HIGH}/v5_enriched_119.pkl")
bars_5m_h = pickle.load(open(f"{SRC_HIGH}/sub2_5m_bars_cache.pkl", "rb"))
idx_5m_h = {(k[0], k[2]): v for k, v in bars_5m_h.items()}

# 补齐真实 100% 锁仓
for idx, r in dfr_h.iterrows():
    c6 = str(r["code"]).zfill(6)
    dfr_h.at[idx, "lock"] = pit_lock_lookup(c6, r["buy_date"])

src_h = "\n".join(open(f"{GOLDEN_DIR}/sub2_03_golden_relaxation_backtest.py").read().splitlines()[:192])
src_h = src_h.replace('r["d1_to"] > 38.0', 'r["d1_to"] > 35.0')
G_h = {"__name__": "eng"}
exec(src_h, G_h)
get_double_dev_px = G_h["get_double_dev_px"]
get_df_k = G_h["get_df_k"]
FEE = 0.0030

def sim_trade_high(r):
    c6 = str(r.code).zfill(6)
    bars = code_bars_h[c6]
    d2p = bars["p"][r.buy_date]
    b_op = float(bars["open"][d2p])
    zt_px = float(bars["zt_px"][d2p])
    df_k = get_df_k(c6, r.buy_date)
    imap = SH_MAP_h if r.ex == "SH" else SZ_MAP_h
    buy_hhmm = 925
    if r.op2 >= 0.0:
        if r.op2 > 0.045 or b_op >= zt_px - 0.011: return None
        buy_px, is_auc = b_op, True
        buy_hhmm = 925
    else:
        ipx = round(b_op * 1.015, 2)
        if ipx >= zt_px - 0.011: return None
        sub_m = df_k[(df_k["date"] == r.buy_date) & (df_k["hhmm"] <= "11:30")] if not df_k.empty else pd.DataFrame()
        if sub_m.empty or sub_m["high"].max() < ipx: return None
        hit_rows = sub_m[sub_m["high"] >= ipx]
        first_hit = hit_rows.iloc[0]
        buy_px = float(first_hit["open"]) if float(first_hit["open"]) >= ipx else ipx
        buy_hhmm = int(str(first_hit["hhmm"]).replace(":", ""))
        is_auc = False

    n = len(bars["dts"])
    ep, epx, eo = None, None, False
    exit_hhmm = 1500
    def run_zt_loop(start_p, max_steps=8):
        imm = False
        for step in range(1, max_steps):
            p = start_p + step
            if p >= n: break
            pl = get_double_dev_px(bars, p, imap, 0.07)
            if bars["open"][p] >= pl: return p, float(bars["open"][p]), True, 925
            if bars["high"][p] >= pl: return p, float(pl), False, 1030
            if not bars["is_zt"][p]:
                if (not imm) and (bars["close"][p] > bars["open"][p]):
                    imm = True; continue
                while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
                return p, float(bars["close"][p]), False, 1500
        p_end = min(start_p + 5, n - 1)
        return p_end, float(bars["close"][p_end]), False, 1500

    if bars["is_zt"][d2p]: ep, epx, eo, exit_hhmm = run_zt_loop(d2p)
    else:
        p = min(d2p + 1, n - 1)
        while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
        if bars["is_zt"][p]: ep, epx, eo, exit_hhmm = run_zt_loop(p)
        else: ep, epx, eo, exit_hhmm = p, float(bars["close"][p]), False, 1500

    ret = (epx * bars["adjf"][ep]) / (buy_px * bars["adjf"][d2p]) * (1.0 - FEE) - 1.0
    return {
        "strategy": "高标首阴 26Q4",
        "priority": 1,
        "code": c6, "name": r.name,
        "buy_date": r.buy_date, "buy_hhmm": buy_hhmm, "buy_px": buy_px,
        "exit_date": bars["dts"][ep], "exit_hhmm": exit_hhmm, "exit_px": epx,
        "net_ret": float(ret), "b_open_h": is_auc, "eo": eo,
        "score": float(r.sc_26q4), "priority_score": float(r.sc_26q4) * 10.0,
        "zt_price": zt_px
    }

def score_high_26q4(r):
    if r["s_reg"] or r["tox"] or r["ex_reg5"] >= 2 or r["d1_to"] > 35.0 or r["lh1"] >= 3 or r["op2"] > 0.045 or r["op2"] < -0.065:
        return -999
    sc = 60
    sc += 12 if r["brk_r10"] >= 0.20 else -8
    if r["n_zt"] < 70: sc += 10
    elif r["n_zt"] >= 95: sc -= 10
    if r["csi5"] >= -0.005: sc += 8
    if r["d1_op"] < 0.0: sc += 8
    if r["op2"] < 0.0: sc += 8
    elif 0.0 <= r["op2"] <= 0.025: sc += 6
    if r["obc"] >= 1: sc += 6
    if r["d0_tight"] < 25.0: sc -= 10
    if r["pelo"] < 135.0 or r["dom"]: sc += 6
    if r["lh1"] == 0: sc += 6
    elif r["lh1"] == 2: sc -= 10
    if r["in1"] >= 1: sc -= 6
    if r["low_price_le20"]: sc += 5
    elif r["high_price_gt35"]: sc -= 10
    if r["turn_boards_ge4"]: sc += 5
    elif r["turn_boards_cnt"] <= 2: sc -= 5
    if r["d1_deep_dip_le6"]: sc += 10
    if (r["lock"] >= 45.0) or (r["fmcap"] >= 45.0): sc += 6
    else: sc -= 6
    if r["qu1"] >= 1 and r["lh1"] <= 1: sc += 4
    if r["kpl_hist_1y_has_ge5"]: sc += 6
    elif r["kpl_hist_3y_has_ge5"]: sc += 3
    if r["kpl_old_stock_old_theme"]: sc += 3
    elif r["kpl_old_stock_new_theme"]: sc -= 5
    if r["lhb_d0_top_locked"]: sc += 5
    if r["lhb_d1_lhasa_heavy"]: sc -= 10
    if r["lhb_d1_net_positive"]: sc -= 5
    if r["lhb_d0_day_surf_buy"]: sc -= 6
    if r["kpl_d0_seal_early_0935"]: sc -= 5
    if r["kpl_reason_tech"]: sc -= 4
    if 25.0 <= r["d1_to"] <= 35.0: sc += 5
    return sc

dfr_h["sc_26q4"] = [score_high_26q4(r) for _, r in dfr_h.iterrows()]

cands_high = []
for r in dfr_h[(dfr_h["sc_26q4"] >= 96) & (dfr_h["buy_date"] >= START_DATE) & (dfr_h["buy_date"] <= END_DATE)].itertuples():
    tr = sim_trade_high(r)
    if tr is not None:
        cands_high.append(tr)

# 独立单仓回测: 熔断机制 + 单仓
def run_standalone_high(cands):
    tdf = pd.DataFrame(cands).sort_values(["buy_date", "score"], ascending=[True, False])
    taken, fd, peo, cl, sk = [], "", False, 0, False
    for r in tdf.itertuples(index=False):
        if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not r.b_open_h)):
            if sk:
                fd, peo = r.exit_date, r.eo
                if r.net_ret > 0: sk, cl = False, 0
                continue
            taken.append(r); fd, peo = r.exit_date, r.eo
            if r.net_ret < -0.02:
                cl += 1
                if cl >= 2: sk = True
            elif r.net_ret > 0: cl = 0
    return pd.DataFrame(taken)

df_led_high = run_standalone_high(cands_high)
df_led_high.to_csv(f"{PART_D_DIR}/ledger_26q4_high.csv", index=False, encoding="utf-8-sig")
print(f"  -> 高标首阴 26Q4 独立完成: {len(df_led_high)} 笔交易，累计单仓净值 {np.prod(1.0 + df_led_high['net_ret']):.2f}x")

# ==============================================================================
# 模块 2: 第 2 顺位 · 三进四 26Q4专供版 (门槛 94 分)
# ==============================================================================
print(">>> [2/4] 运行 第2顺位 · 三进四 26Q4 专供版 (门槛 94 分)...")
CACHE_34 = f"{ROOT}/sim-portfolio/backtests_astock/special_26q4/3to4_26q4/cache_d_and_p.pkl"
BTEST2_DIR = f"{ROOT}/sim-portfolio/backtests_astock2"
sys.path.insert(0, BTEST2_DIR)
from core_3to4_5m_engine import _sim_single_slot_chrono

with open(CACHE_34, "rb") as f:
    pkg_34 = pickle.load(f)

d_34 = pkg_34["df"].copy()
p_34 = pkg_34["p_v32"]
sc_v34 = pkg_34["sc_v34"]

# 补齐 100% 锁仓
for idx, r in d_34.iterrows():
    c6 = str(r["code"]).zfill(6)
    d_34.at[idx, "lock_top10"] = pit_lock_lookup(c6, r["buy_date"])

core_34 = (d_34.is_10cm_non_st & (~d_34.prev_is_yizi) & d_34.buyable_open & (~d_34.has_tox_notice) & (~d_34.has_stock_reg))
obc_34 = d_34.open_board_count >= 1
op_ok_34 = d_34.open_pct.between(0.030, 0.092)
mask_A_34 = core_34 & obc_34 & op_ok_34
top1_34 = d_34.is_top1_3b_open.astype(bool)
lock_34 = (d_34.lock_top10 >= 45.0) | (d_34.real_free_mcap >= 45.0)

delta_34 = (
    np.where(d_34.px_d3 > 32.0, 5, 0)
    + np.where(d_34.open_pct.between(0.030, 0.058), 4, 0)
    + np.where(d_34.open_pct >= 0.065, -3, 0)
    + np.where(d_34.is_post_holiday_or_mon.astype(bool), 3, 0)
    + np.where(d_34.mkt_max_board_prev <= 4, 2, 0)
    + np.where(d_34.plate_fb_yz_cnt >= 1, 4, 0)
    + np.where(~lock_34, 5, 0)
)
sc_34 = np.where(mask_A_34, sc_v34 + delta_34, -999.0)

cands_3to4 = []
for i in np.where(sc_34 >= 94)[0]:
    b_dt = str(d_34["buy_date"].iloc[i])
    if b_dt < START_DATE or b_dt > END_DATE:
        continue
    if p_34[i] is not None:
        rec = dict(p_34[i])
        rec["strategy"] = "三进四 26Q4"
        rec["priority"] = 2
        rec["code"] = str(rec["code"]).zfill(6)
        rec["score"] = int(sc_34[i])
        rec["priority_score"] = float(sc_34[i]) * 10.0 + float(d_34["prio_3to4"].iloc[i]) * 0.1
        rec["buy_px"] = float(rec["buy_price"])
        rec["exit_px"] = float(rec["exit_price"])
        rec["buy_hhmm"] = int(rec["buy_hhmm"])
        rec["exit_hhmm"] = int(rec["exit_hhmm"])
        rec["zt_price"] = float(d_34["px_d3"].iloc[i]) * 1.10
        cands_3to4.append(rec)

tdf_34 = pd.DataFrame(cands_3to4)
taken_34, nav_34, mdd_34, _ = _sim_single_slot_chrono(tdf_34)
df_led_34 = pd.DataFrame([x._asdict() for x in taken_34])
df_led_34.to_csv(f"{PART_D_DIR}/ledger_26q4_3to4.csv", index=False, encoding="utf-8-sig")
print(f"  -> 三进四 26Q4 独立完成: {len(df_led_34)} 笔交易，累计单仓净值 {nav_34:.2f}x")

# ==============================================================================
# 模块 3: 第 3 顺位 · 一进二 26Q4专供版 (304.8/319.8 分)
# ==============================================================================
print(">>> [3/4] 运行 第3顺位 · 一进二 26Q4 专供版 (304.8/319.8 分)...")
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

sys.path.insert(0, f"{ROOT}/sim-portfolio/backtests_astock/special_26q4/1to2_26q4")
from run_master_26q4 import build_model, make_trade_engine

df_26q4_12, tot_26q4_12 = build_model(hist_fb_12.copy(), is_26q4=True)
fn_trade_12 = make_trade_engine(fee=0.003)

# 仅选取区间内符合条件的每日头名候选，保证与 master 一致
sub_12 = df_26q4_12[tot_26q4_12 & (df_26q4_12["d2_dt"] >= START_DATE) & (df_26q4_12["d2_dt"] <= END_DATE)].copy()
sub_12.sort_values(["d2_dt", "_sv_eval"], ascending=[True, False], inplace=True)

cands_1to2 = []
for d2, grp in sub_12.groupby("d2_dt", sort=True):
    # 当日头名
    top_r = grp.iloc[0]
    tr = fn_trade_12(top_r)
    if tr is not None:
        rec = dict(tr)
        rec["strategy"] = "一进二 26Q4"
        rec["priority"] = 3
        rec["code"] = str(rec["c6"]).zfill(6)
        rec["score"] = float(top_r["score_active"])
        rec["priority_score"] = float(top_r["_sv_eval"])
        rec["buy_px"] = float(rec["buy_price"])
        rec["exit_px"] = float(rec["exit_price"])
        
        is_monday = top_r.get("gap_days", 1) >= 3
        cand_score = top_r.get("score_active", top_r.get("score_0", 0.0))
        cand_lead = top_r.get("buy_open_lead", 0.0)
        do_direct = is_monday and (cand_score >= 310.0) and (cand_lead >= 0.025)
        if do_direct:
            rec["buy_hhmm"] = 925
        else:
            trig_p = float(top_r["trig_p"])
            arr2 = bars_5m_map_12.get((top_r["c6"], top_r["d2_dt"]))
            ign_hhmm = 935
            if arr2 is not None and len(arr2) > 0:
                for bi in range(len(arr2)):
                    if arr2[bi, 2] >= trig_p - 1e-4:
                        ign_hhmm = int(arr2[bi, 0])
                        break
            rec["buy_hhmm"] = ign_hhmm

        if rec.get("exit_at_open", False):
            rec["exit_hhmm"] = 925
        elif rec.get("tag") == "5m_1030_weak_cut":
            rec["exit_hhmm"] = 1035
        elif rec.get("tag") == "5m_1430_rush":
            rec["exit_hhmm"] = 1435
        else:
            rec["exit_hhmm"] = 1500
        rec["zt_price"] = float(top_r["trig_p"]) * 1.05
        cands_1to2.append(rec)

# 独立单仓回测: 1to2
def run_standalone_1to2(cands):
    tdf = pd.DataFrame(cands).sort_values(["buy_date", "priority_score"], ascending=[True, False])
    taken, fd, feo = [], "", False
    for r in tdf.itertuples(index=False):
        if fd == "" or r.buy_date > fd or (r.buy_date == fd and feo):
            taken.append(r)
            fd = r.exit_date
            feo = bool(r.exit_hhmm <= 925)
    return pd.DataFrame(taken)

df_led_12 = run_standalone_1to2(cands_1to2)
df_led_12.to_csv(f"{PART_D_DIR}/ledger_26q4_1to2.csv", index=False, encoding="utf-8-sig")
print(f"  -> 一进二 26Q4 独立完成: {len(df_led_12)} 笔交易，累计单仓净值 {np.prod(1.0 + df_led_12['net_ret']):.2f}x")

# ==============================================================================
# 模块 4: 严格纯单仓合体实盘回测 (三大核心策略: 高标 > 三进四 > 一进二)
# ==============================================================================
print(">>> [4/4] 运行 严格纯单仓合体实盘回测 (高标 > 三进四 > 一进二)...")

# 汇聚全量候选
all_cands = []
for c in cands_high:
    all_cands.append(c)
for c in cands_3to4:
    all_cands.append(c)
for c in cands_1to2:
    all_cands.append(c)

df_all_cands = pd.DataFrame(all_cands)
print(f"  全量合体候选信号数: {len(df_all_cands)} (高标: {len(cands_high)}, 三进四: {len(cands_3to4)}, 一进二: {len(cands_1to2)})")

all_dates = sorted(df_all_cands["buy_date"].unique())

taken_combined = []
free_date = ""
free_hhmm = 0

for d in all_dates:
    day_cands = df_all_cands[df_all_cands["buy_date"] == d].copy()
    if day_cands.empty:
        continue

    # 1. 判断今日是否有仓位冲突
    if free_date != "" and d < free_date:
        # 旧仓未卖出，严格跳过一切新信号
        continue

    # 2. 判断是否同日接力
    if free_date != "" and d == free_date:
        # 仅当前一笔是 09:25 竞价卖出 (free_hhmm <= 925)，且新信号是 09:30 以后条件单成交 (buy_hhmm >= 931)
        if free_hhmm > 925:
            # 盘中或尾盘卖出，当天绝不开任何早盘新仓
            continue
        # 过滤今日仅保留 buy_hhmm >= 931 的候选信号
        day_cands = day_cands[day_cands["buy_hhmm"] >= 931]
        if day_cands.empty:
            continue

    # 3. 按严格顺位选取唯一首选策略头名 (高标 > 三进四 > 一进二)
    cands_p1 = day_cands[day_cands["priority"] == 1]
    if not cands_p1.empty:
        best_cand = cands_p1.sort_values("priority_score", ascending=False).iloc[0].to_dict()
    else:
        cands_p2 = day_cands[day_cands["priority"] == 2]
        if not cands_p2.empty:
            best_cand = cands_p2.sort_values("priority_score", ascending=False).iloc[0].to_dict()
        else:
            cands_p3 = day_cands[day_cands["priority"] == 3]
            if not cands_p3.empty:
                best_cand = cands_p3.sort_values("priority_score", ascending=False).iloc[0].to_dict()
            else:
                continue

    # 4. 执行开仓并更新持仓空闲时间
    taken_combined.append(best_cand)
    free_date = str(best_cand["exit_date"])
    free_hhmm = int(best_cand["exit_hhmm"])

df_combined = pd.DataFrame(taken_combined)
df_combined.to_csv(f"{PART_D_DIR}/ledger_26q4_combined_3main.csv", index=False, encoding="utf-8-sig")
print(f"  合体回测执行完成: 共成交 {len(df_combined)} 笔交易!")

# ==============================================================================
# 模块 5: D15 多窗口全口径指标与实盘资金容量封顶模型测算
# ==============================================================================
print(">>> 计算五大标准窗口与实盘资金容量封顶模型...")

CAP_AMOUNT = 10000000.0  # 1000 万元
SLIPPAGE = 0.0020        # 20 bps

def evaluate_window(trades_df, s_dt, e_dt, csi_ret):
    sub = trades_df[(trades_df["buy_date"] >= s_dt) & (trades_df["buy_date"] <= e_dt)].copy()
    if sub.empty:
        return {
            "n_trades": 0, "strategy_counts": {"高标首阴 26Q4": 0, "三进四 26Q4": 0, "一进二 26Q4": 0},
            "wr_pct": 0.0, "payoff": 0.0,
            "single_nav": 1.0, "single_ret_pct": 0.0,
            "daily_eq_nav": 1.0, "daily_eq_ret_pct": 0.0,
            "mdd_pct": 0.0, "trimmed_top3_nav": 1.0, "trimmed_top5_nav": 1.0,
            "csi300_ret_pct": round(csi_ret, 2), "excess_ret_pct": round(-csi_ret, 2),
            "capped_net_profit_wan": 0.0, "capped_annualized_ret_pct": 0.0,
        }

    rets = sub["net_ret"].to_numpy()
    n = len(rets)
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    wr = float(len(wins) / n * 100.0)
    w_avg = float(np.mean(wins)) if len(wins) > 0 else 0.0
    l_avg = float(np.abs(np.mean(losses))) if len(losses) > 0 else 0.0
    payoff = float(w_avg / l_avg) if l_avg > 0 else 99.0

    single_nav = float(np.prod(1.0 + rets))
    single_ret_pct = float((single_nav - 1.0) * 100.0)

    daily_eq_rets = sub.groupby("buy_date")["net_ret"].mean().to_numpy()
    daily_eq_nav = float(np.prod(1.0 + daily_eq_rets))
    daily_eq_ret_pct = float((daily_eq_nav - 1.0) * 100.0)

    pk, cur, mdd = 1.0, 1.0, 0.0
    for x in rets:
        cur *= (1.0 + x)
        pk = max(pk, cur)
        mdd = max(mdd, (pk - cur) / pk)
    mdd_pct = float(mdd * 100.0)

    sorted_rets = np.sort(rets)
    t3_nav = float(np.prod(1.0 + sorted_rets[:-3])) if len(sorted_rets) > 3 else single_nav
    t5_nav = float(np.prod(1.0 + sorted_rets[:-5])) if len(sorted_rets) > 5 else single_nav

    sc_counts = sub["strategy"].value_counts().to_dict()
    strat_counts = {
        "高标首阴 26Q4": int(sc_counts.get("高标首阴 26Q4", 0)),
        "三进四 26Q4": int(sc_counts.get("三进四 26Q4", 0)),
        "一进二 26Q4": int(sc_counts.get("一进二 26Q4", 0)),
    }

    # 实盘容量封顶模型 (初始 1000 万，单笔上限 1000 万，超出转现金不复利，真实滑点 20 bps)
    cur_equity = CAP_AMOUNT
    total_net_pnl = 0.0
    for r_val in rets:
        invest = min(cur_equity, CAP_AMOUNT)
        real_ret = r_val - SLIPPAGE
        pnl = invest * real_ret
        total_net_pnl += pnl
        cur_equity += pnl

    capped_net_profit_wan = round(float(total_net_pnl / 10000.0), 2)
    days_span = max(1, (pd.to_datetime(e_dt) - pd.to_datetime(s_dt)).days)
    years = days_span / 365.25
    ann_ret = float(((cur_equity / CAP_AMOUNT) ** (1.0 / years) - 1.0) * 100.0) if years > 0 and cur_equity > 0 else 0.0

    excess_ret_pct = float(single_ret_pct - csi_ret)

    return {
        "n_trades": n,
        "strategy_counts": strat_counts,
        "wr_pct": round(wr, 1),
        "payoff": round(payoff, 2),
        "single_nav": round(single_nav, 2),
        "single_ret_pct": round(single_ret_pct, 1),
        "daily_eq_nav": round(daily_eq_nav, 2),
        "daily_eq_ret_pct": round(daily_eq_ret_pct, 1),
        "mdd_pct": round(mdd_pct, 1),
        "trimmed_top3_nav": round(t3_nav, 2),
        "trimmed_top5_nav": round(t5_nav, 2),
        "csi300_ret_pct": round(csi_ret, 2),
        "excess_ret_pct": round(excess_ret_pct, 1),
        "capped_net_profit_wan": capped_net_profit_wan,
        "capped_annualized_ret_pct": round(ann_ret, 1),
    }

WINDOWS = [
    ("2026年10月以来", "2026-10-01", "2026-11-16", CSI300_BENCHMARK["2026年10月以来"][0]),
    ("2026年7月以来",  "2026-07-01", "2026-11-16", CSI300_BENCHMARK["2026年7月以来"][0]),
    ("2026全年",      "2026-01-01", "2026-11-16", CSI300_BENCHMARK["2026全年"][0]),
    ("近三年",        "2023-11-15", "2026-11-16", CSI300_BENCHMARK["近三年(2023-11-16起)"][0]),
    ("全五年",        "2021-11-15", "2026-11-16", CSI300_BENCHMARK["全五年(2021-11-16起)"][0]),
]

summary_combined = {
    "generated_at": "2026-11-16 18:45:00",
    "version": "26Q4 专供版三大核心策略纯单仓合体真账重跑",
    "priority_rule": "第1顺位 高标首阴 26Q4 (96分) > 第2顺位 三进四 26Q4 (94分) > 第3顺位 一进二 26Q4 (304.8/319.8分)",
    "timing_constraints": "零时间穿越：旧仓未卖出严格跳过；同日仅当09:25竞价卖出且新信号09:30以后突破才允许接力；盘中/尾盘卖出当天绝不开早盘新仓",
    "capacity_model": "初始1000万，单笔上限1000万，超出转现金不复利，真实滑点20bps",
    "windows_summary": {}
}

for name, s_dt, e_dt, csi_ret in WINDOWS:
    res = evaluate_window(df_combined, s_dt, e_dt, csi_ret)
    summary_combined["windows_summary"][name] = res

with open(f"{PART_D_DIR}/summary_26q4_combined_3main.json", "w", encoding="utf-8") as f:
    json.dump(summary_combined, f, indent=2, ensure_ascii=False)
print("  -> 汇总 JSON summary_26q4_combined_3main.json 保存成功!")

# ==============================================================================
# 模块 6: 严密防伪与硬约束核验 (T+0, 资金穿越, 一字买入)
# ==============================================================================
print(">>> 执行防伪核验三铁律...")
# 1. T+0 检查: 买入日期必须严格小于卖出日期 (T+1 规则)
t0_count = sum(df_combined["buy_date"] == df_combined["exit_date"])
print(f"  [核验 1] T+0 违规买卖笔数: {t0_count} (必须为 0)")

# 2. 同日资金穿越检查
crossover_count = 0
for i in range(1, len(df_combined)):
    prev = df_combined.iloc[i-1]
    curr = df_combined.iloc[i]
    if curr["buy_date"] < prev["exit_date"]:
        crossover_count += 1
    elif curr["buy_date"] == prev["exit_date"]:
        if prev["exit_hhmm"] > 925 or curr["buy_hhmm"] < 931:
            crossover_count += 1
print(f"  [核验 2] 同日资金穿越与早盘秒级换仓违规笔数: {crossover_count} (必须为 0)")

# 3. 一字板顶死买入检查 (集合竞价买入且开盘即涨停顶死)
yizi_buy_count = 0
for _, r in df_combined.iterrows():
    if r["buy_hhmm"] == 925 and r["buy_px"] >= r.get("zt_price", 99999.0) - 0.005:
        yizi_buy_count += 1
print(f"  [核验 3] 一字板顶死买入违规笔数: {yizi_buy_count} (必须为 0)")

print("\n=== 全量重跑完成！===")
