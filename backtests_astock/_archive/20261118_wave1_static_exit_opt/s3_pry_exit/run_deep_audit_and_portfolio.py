#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_deep_audit_and_portfolio.py
对初选与合成 Top 候选卖点执行：
  1. 全局四策略 / 五策略纯单仓组合碰撞验证 (对齐 synthesize_master_clean_20261116.py 与 audit_5strategies_priority_winrate.py)
  2. ±20% 参数微抖高原测试 (确认非孤立尖峰)
  3. D15 五大窗口 (全五年/IS/OOS/近3年/2026全年) + 沪深300净超额 + 八大防过拟合统计学检验 (HLZ t, DSR, 猴子p值, Bootstrap, CSCV PBO, 去极值, 2x/3x摩擦, 逐年)
  4. 硬断言 (t0_violations==0, overlap_violations==0, 一字跌停零违规, >=2025-01-01数据截断不变性 max_abs_diff==0.0)
  5. >=165 分单仓逐笔对比 + 2026-11-18 实盘持仓 000011 深物业A 执行指令对比
"""
import os, sys, json, math, time, pickle, itertools
from collections import defaultdict
import numpy as np
import pandas as pd
import scipy.stats as stats

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock/exit_opt_20261118/s3_pry_exit"
CLEAN16 = f"{SIM}/backtests_astock/clean_rebacktest_20261116"
OUT23 = f"{SIM}/backtests_astock/clean_2to3_v10_20261117"

for p in (OUT_DIR, CLEAN16):
    if p not in sys.path:
        sys.path.insert(0, p)

import run_exit_scan as base
import run_synthesis_scan as syn_mod
import synthesize_master_clean_20261116 as syn16


def get_hhmm_fn(exit_code_mode, d, p0, buy_px, exit_dt):
    """Determine accurate exit_hhmm for single-slot portfolio chaining."""
    if not exit_dt:
        return 1455
    pos_ex = d["date_to_pos"].get(exit_dt)
    if pos_ex is None or pos_ex == p0:
        return 1455
    # Check if sold at open (day0 reseal cut or open >= tp)
    if pos_ex == p0 + 1 and (d["close"][p0] <= d["dt_px"][p0] + 0.005):
        return 925
    return 1455


def build_candidate_runners(sub, cb, m5_map):
    """Return dictionary of candidate simulation functions with exact exit_hhmm."""
    runners = {}

    def wrap_limit(tp_fn, mh, t1c="none", t2s=None, ztr=True, eztr=True, match="strict_premarket", use_adjf=True):
        def fn(d, p0, bpx, r):
            if match == "phantom_s3_bug":
                rv, ed, hd = base.sim_limit_tp(d, p0, bpx, tp_fn(r)[0] if isinstance(tp_fn(r), list) else tp_fn(r), mh, match_mode="phantom_s3_bug", use_adjf=False)
                return rv, ed, hd, 1455
            rv, ed, hd = syn_mod.sim_synth(
                d, p0, bpx,
                (lambda s: tp_fn(r)[min(s - 1, len(tp_fn(r)) - 1)]) if isinstance(tp_fn(r), list) else (lambda s: tp_fn(r)),
                max_h=mh, t1_cut_mode=t1c, t2_stall_ratio=t2s,
                zt_relay_if_unfilled=ztr, end_zt_relay=eztr
            )
            eh = 925 if (d["close"][p0] <= d["dt_px"][p0] + 0.005) else 1455
            return rv, ed, hd, eh
        return fn

    # 1. Baselines
    runners["B0_X10_phantom_bug"] = wrap_limit(lambda r: float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16)), 4, match="phantom_s3_bug")
    runners["B1_X10_v1_strict"] = wrap_limit(lambda r: float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16)), 4, t1c="none", t2s=None, ztr=False, eztr=False)

    # 2. X7 Family
    def fn_x7(d, p0, bpx, r):
        rv, ed, hd = base.sim_x7_relay(d, p0, bpx)
        eh = 925 if (d["close"][p0] <= d["dt_px"][p0] + 0.005) else 1455
        return rv, ed, hd, eh
    runners["S01_X7_exact_3d"] = fn_x7
    runners["S06_X7_4d"] = wrap_limit(lambda r: [None, None, None, None], 4, t1c="lt_d0_close", t2s=0.985, ztr=True, eztr=True)

    # 3. Family A shortened 2d
    runners["S_X10_2d_ztr"] = wrap_limit(lambda r: float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16)), 2, t1c="none", t2s=None, ztr=True, eztr=True)
    runners["A_mh_x10_2d_strict"] = wrap_limit(lambda r: float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16)), 2, t1c="none", t2s=None, ztr=False, eztr=False)

    # 4. Family C TimeDecay + Hybrids
    runners["C_decay_D_highT1_4d"] = wrap_limit(
        lambda r: [float(np.clip(0.55*abs(r.prev_ret10), 0.08, 0.20)), float(np.clip(0.40*abs(r.prev_ret10), 0.06, 0.14)), 0.05, 0.02],
        4, t1c="none", t2s=None, ztr=True, eztr=True
    )
    runners["S_DecD_t1noTP_2d"] = wrap_limit(
        lambda r: [None, float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16))],
        2, t1c="none", t2s=None, ztr=True, eztr=True
    )
    runners["S_DecD_t1noTP_3d_weakcut"] = wrap_limit(
        lambda r: [None, float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16)), 0.05],
        3, t1c="lt_d0_close", t2s=0.985, ztr=True, eztr=True
    )
    runners["S_DecD_t1noTP_4d_weakcut"] = wrap_limit(
        lambda r: [None, float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16)), 0.05, 0.02],
        4, t1c="lt_d0_close", t2s=0.985, ztr=True, eztr=True
    )
    runners["S_X10_3d_weakcut"] = wrap_limit(
        lambda r: float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16)),
        3, t1c="lt_d0_close", t2s=None, ztr=True, eztr=True
    )
    runners["S_X7_plus_T2TP15"] = wrap_limit(
        lambda r: [None, 0.15, 0.08],
        3, t1c="lt_d0_close", t2s=0.985, ztr=True, eztr=True
    )

    # 5. Family D MA10
    def fn_ma10(d, p0, bpx, r):
        rv, ed, hd = base.sim_ma_regress(d, p0, bpx, ma_len=10, mult=0.95, min_protect=1.05, max_h=4)
        eh = 925 if (d["close"][p0] <= d["dt_px"][p0] + 0.005) else 1455
        return rv, ed, hd, eh
    runners["D_MA10_m95_p105"] = fn_ma10

    # 6. Family B Trail (neutral & pess)
    for bnd in ["neutral", "pess"]:
        runners[f"B_trail_armDyn_pb25_{bnd}"] = (lambda b0: lambda d, p0, bpx, r: (
            *base.sim_trailing_pullback(d, p0, bpx, float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16)), 0.025, 4, bound=b0, m5_map=m5_map, c6=r.c6),
            925 if (d["close"][p0] <= d["dt_px"][p0] + 0.005) else 1455
        ))(bnd)

    return runners


def run_candidate_ledger(sub, cb, fn):
    rows = []
    for r in sub.itertuples(index=False):
        rv, ed, hd, eh = fn(cb[r.c6], r.p0, r.buy_px, r)
        rows.append({
            "buy_date": r.buy_date, "exit_date": ed, "code": r.code, "name": r.name,
            "score": int(r.score), "bias10": float(r.bias10), "o_pct": float(r.o_pct),
            "net_ret": float(rv), "hold_days": int(hd), "buy_hhmm": 925, "exit_hhmm": int(eh),
            "buy_px": float(r.buy_px), "prev_ret10": float(r.prev_ret10),
        })
    return pd.DataFrame(rows)


def sim_1slot_pry(df_sub):
    srt = df_sub.sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True])
    taken, free_after = [], ""
    for r in srt.itertuples(index=False):
        if free_after == "" or r.buy_date > free_after:
            taken.append(r._asdict())
            free_after = r.exit_date
    return pd.DataFrame(taken)


def main():
    t0 = time.time()
    df, cb, v1_ref, s3_ref, csi_canon, sh300, m5_map = base.load_all_data()
    sub = base.build_base_candidates(df, cb)
    runners = build_candidate_runners(sub, cb, m5_map)

    # Load 4 other strategies for portfolio synergy test
    d_hd = syn16.standardize_ledger(f"{CLEAN16}/partA_high_3to4/ledger_base_high_v51.csv", "高标首阴", 1)
    d_34 = syn16.standardize_ledger(f"{CLEAN16}/partA_high_3to4/ledger_base_3to4_v34.csv", "三进四", 2)
    d_12 = syn16.standardize_ledger(f"{CLEAN16}/partB_1to2/ledger_base_1to2_v18.csv", "一进二", 4)
    d_23 = syn16.standardize_ledger(f"{OUT23}/candidates_2to3_v10_all_raw90.csv", "二进三90", 5)

    # Note: verify exact baseline match with ledger_combined_5strat_slot5_canonical.csv!
    print("=== [1] GLOBAL 5-STRATEGY PORTFOLIO COLLISION IMPACT (高标 > 三进四 > 超跌撬板 > 一进二 > 二进三90) ===")
    port_rows = []
    cand_ledgers = {}
    for nm, fn in runners.items():
        ldf = run_candidate_ledger(sub, cb, fn)
        cand_ledgers[nm] = ldf
        p165 = ldf[ldf["score"] >= 165].copy()
        top25 = p165.sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
        top25_std = top25[["buy_date", "exit_date", "code", "name", "net_ret", "score", "buy_hhmm", "exit_hhmm"]].copy()
        top25_std["strategy"] = "超跌撬板"
        top25_std["priority"] = 3

        # 5-strat (pry @ P3 above 1to2, 2to3 @ P5)
        pool5 = pd.concat([
            d_hd.assign(priority=1), d_34.assign(priority=2), top25_std.assign(priority=3),
            d_12.assign(priority=4), d_23.assign(priority=5)
        ], ignore_index=True)
        slot5 = syn16.run_1slot(pool5)
        m5_5y = syn16.calc_metrics(pool5, slot5, "2021-11-16", -18.49)
        m5_3y = syn16.calc_metrics(pool5, slot5, "2023-11-16", 10.33)
        m5_26 = syn16.calc_metrics(pool5, slot5, "2026-01-01", -14.04)
        pry_taken = slot5[(slot5["strategy"] == "超跌撬板") & (slot5["buy_date"] >= "2021-11-16")]
        pry_wr = round(float((pry_taken["net_ret"] > 0).mean() * 100), 1) if len(pry_taken) else 0.0

        # 4-strat (without 2to3: high > 3to4 > pry > 1to2)
        pool4 = pd.concat([
            d_hd.assign(priority=1), d_34.assign(priority=2), top25_std.assign(priority=3), d_12.assign(priority=4)
        ], ignore_index=True)
        slot4 = syn16.run_1slot(pool4)
        m4_5y = syn16.calc_metrics(pool4, slot4, "2021-11-16", -18.49)

        # Standalone P165 single-slot
        ss165 = sim_1slot_pry(p165)
        ss_r = ss165["net_ret"].to_numpy()
        ss_nav = float(np.prod(1.0 + ss_r))
        ss_wr = float((ss_r > 0).mean() * 100.0)
        ss_avg_h = float(ss165["hold_days"].mean())

        port_rows.append({
            "variant": nm,
            "ss_n": len(ss165), "ss_wr": round(ss_wr, 2), "ss_nav": round(ss_nav, 4), "ss_hold": round(ss_avg_h, 2),
            "p4_nav": m4_5y["nav_slot"], "p4_cap10m": m4_5y["cap10m_mult"], "p4_wr": m4_5y["win_rate"], "p4_mdd": m4_5y["max_dd_pct"],
            "p5_n": m5_5y["n_slot"], "p5_pry_n": len(pry_taken), "p5_pry_wr": pry_wr,
            "p5_nav": m5_5y["nav_slot"], "p5_cap10m": m5_5y["cap10m_mult"], "p5_wr": m5_5y["win_rate"], "p5_mdd": m5_5y["max_dd_pct"],
            "p5_3y_nav": m5_3y["nav_slot"], "p5_26_nav": m5_26["nav_slot"],
        })

    pdf = pd.DataFrame(port_rows)
    pdf.to_csv(f"{OUT_DIR}/portfolio_comparison.csv", index=False, encoding="utf-8-sig")
    print(pdf[["variant", "ss_n", "ss_wr", "ss_nav", "ss_hold", "p4_nav", "p4_cap10m", "p5_pry_n", "p5_pry_wr", "p5_nav", "p5_cap10m", "p5_wr", "p5_mdd"]].to_string(index=False))

    # 2. Parameter Plateau Check (±20% perturbations around S_DecD_t1noTP_4d_weakcut, S01_X7_exact_3d, S06_X7_4d, S_X10_2d)
    print("\n=== [2] PARAMETER PLATEAU CHECK (±20% NEIGHBORHOOD) ===")
    plateau_rows = []
    # 2a. X7 neighborhood: T+1 cut threshold & T+2 stall threshold & max_h
    for mh in [2, 3, 4, 5]:
        for t1_th in [0.98, 0.99, 1.00, 1.01]:
            for s2_th in [0.975, 0.985, 0.995]:
                if mh == 2 and s2_th != 0.985:
                    continue
                def fn_x7p(d, p0, bpx, r, m0=mh, c1=t1_th, s2=s2_th):
                    L = len(d["dts"])
                    if p0 + 1 >= L: return np.nan, "", 0
                    if d["is_zt"][p0]: return base.hold_zt_relay(d, p0, p0, bpx)
                    if d["close"][p0] <= d["dt_px"][p0] + 0.005:
                        ps = base.first_sellable_day(d, p0 + 1)
                        return base.ret_from_px(d, p0, ps, d["open"][ps] if d["open"][ps] > d["dt_px"][ps] + 0.005 else d["close"][ps], bpx)
                    end_p = min(L - 1, p0 + m0)
                    for step_i, k in enumerate(range(p0 + 1, end_p + 1), 1):
                        if d["is_yizi_dt"][k]: continue
                        if d["is_zt"][k]: return base.hold_zt_relay(d, p0, k, bpx)
                        if k < end_p:
                            ck = d["close"][k] * d["adjf"][k] / d["adjf"][p0]
                            cp = d["close"][k - 1] * d["adjf"][k - 1] / d["adjf"][p0]
                            if (step_i == 1 and ck < cp * c1) or (step_i >= 2 and ck < cp * s2):
                                return base.ret_from_px(d, p0, k, d["close"][k], bpx)
                    ps = base.first_sellable_day(d, end_p)
                    return base.ret_from_px(d, p0, ps, d["close"][ps], bpx)

                rets, edts, hlds = [], [], []
                for r in sub.itertuples(index=False):
                    rv, ed, hd = fn_x7p(cb[r.c6], r.p0, r.buy_px, r)
                    rets.append(rv); edts.append(ed); hlds.append(hd)
                rets, edts, hlds = np.array(rets), np.array(edts, dtype=object), np.array(hlds)
                e65 = base.eval_variant(sub, rets, edts, hlds, 165)
                e50 = base.eval_variant(sub, rets, edts, hlds, 150)
                e00 = base.eval_variant(sub, rets, edts, hlds, 0)
                plateau_rows.append({
                    "grid": "X7_plateau", "mh": mh, "p1": t1_th, "p2": s2_th,
                    "P165_ss": e65["ALL"]["ss"]["nav"], "P165_IS_d": e65["IS"]["deq"]["nav"], "P165_OOS_d": e65["OOS"]["deq"]["nav"],
                    "P150_IS_d": e50["IS"]["deq"]["nav"], "P150_OOS_d": e50["OOS"]["deq"]["nav"], "P000_ALL_d": e00["ALL"]["deq"]["nav"],
                })

    # 2b. S_DecD_t1noTP_weakcut neighborhood: max_h ∈ {2,3,4}, T2 k ∈ {0.35, 0.45, 0.55}, T1 cut ∈ {0.985, 1.00, 1.01}, T2 stall ∈ {0.98, 0.985, 0.99}
    for mh in [3, 4]:
        for kv in [0.35, 0.45, 0.55]:
            for s2_th in [0.980, 0.985, 0.990]:
                def fn_decp(d, p0, bpx, r, m0=mh, k_v=kv, s2=s2_th):
                    tp2 = float(np.clip(k_v * abs(r.prev_ret10), 0.06, 0.16))
                    sched = [None, tp2, 0.05, 0.02]
                    return syn_mod.sim_synth(d, p0, bpx, lambda s: sched[min(s-1, 3)], max_h=m0, t1_cut_mode="lt_d0_close", t2_stall_ratio=s2, zt_relay_if_unfilled=True, end_zt_relay=True)
                rets, edts, hlds = [], [], []
                for r in sub.itertuples(index=False):
                    rv, ed, hd = fn_decp(cb[r.c6], r.p0, r.buy_px, r)
                    rets.append(rv); edts.append(ed); hlds.append(hd)
                rets, edts, hlds = np.array(rets), np.array(edts, dtype=object), np.array(hlds)
                e65 = base.eval_variant(sub, rets, edts, hlds, 165)
                e50 = base.eval_variant(sub, rets, edts, hlds, 150)
                e00 = base.eval_variant(sub, rets, edts, hlds, 0)
                plateau_rows.append({
                    "grid": "DecD_weakcut_plateau", "mh": mh, "p1": kv, "p2": s2_th,
                    "P165_ss": e65["ALL"]["ss"]["nav"], "P165_IS_d": e65["IS"]["deq"]["nav"], "P165_OOS_d": e65["OOS"]["deq"]["nav"],
                    "P150_IS_d": e50["IS"]["deq"]["nav"], "P150_OOS_d": e50["OOS"]["deq"]["nav"], "P000_ALL_d": e00["ALL"]["deq"]["nav"],
                })

    pl_df = pd.DataFrame(plateau_rows)
    pl_df.to_csv(f"{OUT_DIR}/parameter_plateau.csv", index=False, encoding="utf-8-sig")
    for gname, gdf in pl_df.groupby("grid"):
        print(f"--- {gname} ({len(gdf)} combos) ---")
        print(f"  P165_ss: min={gdf['P165_ss'].min():.4f}, median={gdf['P165_ss'].median():.4f}, max={gdf['P165_ss'].max():.4f}, pct_beat_v1(1.9411)={(gdf['P165_ss']>1.9411).mean()*100:.1f}%")
        print(f"  P150_OOS_d: min={gdf['P150_OOS_d'].min():.4f}, median={gdf['P150_OOS_d'].median():.4f}, max={gdf['P150_OOS_d'].max():.4f}, pct_beat_v1(0.9559)={(gdf['P150_OOS_d']>0.9559).mean()*100:.1f}%")
        print(f"  P000_ALL_d: min={gdf['P000_ALL_d'].min():.4f}, median={gdf['P000_ALL_d'].median():.4f}, max={gdf['P000_ALL_d'].max():.4f}, pct_beat_v1(0.6677)={(gdf['P000_ALL_d']>0.6677).mean()*100:.1f}%")

    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
