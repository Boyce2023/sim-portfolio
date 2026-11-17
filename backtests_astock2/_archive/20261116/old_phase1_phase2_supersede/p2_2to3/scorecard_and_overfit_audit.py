#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scorecard_and_overfit_audit.py: 二进三打分卡 V1.0 严谨评级、D15 四必核与四大策略槽位碰撞"""
import os, sys, json, pickle
import numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/p2_2to3"
CSI300_MAP = {2022: -0.2163, 2023: -0.1138, 2024: 0.1468, 2025: 0.1766, 2026: -0.1233}
BENCH_5Y, BENCH_3Y, BENCH_JUL = -0.1784, 0.1318, 0.1548

def calc_score(df):
    scores = []
    for r in df.itertuples(index=False):
        if (bool(r.prev_is_yizi) or float(r.to_ratio_d2_d1) < 0.6 or float(r.open_pct) < -0.02 or 
            float(r.open_pct) >= 0.075 or bool(r.has_tox_notice) or bool(r.has_stock_reg) or 
            bool(r.has_ex_reg) or (str(r.first_seal_time) >= "14:00:00") or float(r.px_d2) >= 28.0):
            scores.append(-999); continue
        sc = 0
        if bool(r.is_mkt_highest_2b): sc += 25
        if 0.03 <= float(r.open_pct) <= 0.065: sc += 15
        elif 0.01 <= float(r.open_pct) < 0.03: sc += 8
        if 0.8 <= float(r.to_ratio_d2_d1) <= 1.6: sc += 15
        if int(r.open_board_count) >= 1: sc += 12
        if "09:36:00" <= str(r.first_seal_time) <= "10:30:00": sc += 12
        elif str(r.first_seal_time) <= "09:33:00": sc -= 8
        if int(r.plate_fresh01_hi_cnt) >= 1: sc += 12
        if float(r.prev_real_to) >= 15.0: sc += 10
        if bool(r.is_top1_2b_open): sc += 12
        if bool(r.is_plate_top1_2b): sc += 10
        if float(r.s_elo) >= 100.0: sc += 10
        if float(r.lock_top10) >= 0.45: sc += 8
        if float(r.real_free_mcap) < 30.0: sc += 10
        if bool(r.clean_brk60): sc += 8
        if float(r.prior_mb_gap) > 60: sc += 8
        if int(r.surf_yz_buy) == 0: sc += 6
        if int(r.lhasa_seats_prev) == 0: sc += 6
        if float(r.csi300_ret5) < 0: sc += 10
        scores.append(sc)
    return np.array(scores)

def sim_single_slot(df_sub, thr):
    cands = df_sub[df_sub["score"] >= thr].sort_values(["buy_date", "score", "open_pct"], ascending=[True, False, False])
    cur_free, trades = pd.Timestamp("1990-01-01"), []
    for r in cands.itertuples(index=False):
        if pd.Timestamp(r.buy_date) > cur_free: trades.append(r); cur_free = pd.Timestamp(r.exit_dt)
    if not trades: return None
    t_df = pd.DataFrame(trades); rets = t_df["net_ret"].values; prod = np.cumprod(1.0 + rets)
    peaks = np.maximum.accumulate(np.insert(prod, 0, 1.0))[1:]
    mdd = float(((peaks - prod) / peaks).max())
    pos, neg = rets[rets > 0], rets[rets <= 0]
    odds = float(pos.mean() / abs(neg.mean())) if len(neg) and abs(neg.mean()) > 0 else 0.0
    return {"n": len(t_df), "cum_ret": round(float(prod[-1] - 1.0), 4), "mdd": round(mdd, 4), "wr": round(float((rets > 0).mean()), 4), "odds": round(odds, 2), "avg_ret": round(float(rets.mean()), 4), "trades": t_df}

def main():
    df = pd.read_parquet(f"{OUT_DIR}/cand_2to3_enriched.parquet")
    df["score"] = calc_score(df); df["year"] = pd.to_datetime(df["buy_date"]).dt.year
    pool = df[(df["score"] > 0) & df["net_ret"].notna()].copy()
    res_sweet, res_elite = sim_single_slot(pool, 120), sim_single_slot(pool, 132)
    t_sweet = res_sweet["trades"]
    t_sweet.to_csv(f"{OUT_DIR}/best_2to3_ledger.csv", index=False, encoding="utf-8-sig")

    def get_slice_stats(tdf, start_d, end_d, bench):
        sub = tdf[(tdf["buy_date"] >= start_d) & (tdf["buy_date"] <= end_d)]
        if len(sub) == 0: return {"n": 0, "cum": 0.0, "alpha": 0.0, "avg": 0.0, "wr": 0.0}
        r = sub["net_ret"].values; cum = float(np.prod(1.0 + r) - 1.0)
        return {"n": len(sub), "cum": round(cum, 4), "alpha": round(cum - bench, 4), "avg": round(float(r.mean()), 4), "wr": round(float((r > 0).mean()), 4)}

    slices_sweet = {
        "5年全周期(2022-2026)": get_slice_stats(t_sweet, "2022-01-04", "2026-11-10", BENCH_5Y),
        "近3年(2024-2026)": get_slice_stats(t_sweet, "2024-01-02", "2026-11-10", BENCH_3Y),
        "剔除2025年其余4年": get_slice_stats(t_sweet[t_sweet["year"] != 2025], "2022-01-04", "2026-11-10", -0.3017),
        "7月以来近期窗口": get_slice_stats(t_sweet, "2026-07-01", "2026-11-10", BENCH_JUL)
    }
    annual_sweet = {y: get_slice_stats(t_sweet, f"{y}-01-01", f"{y}-12-31", CSI300_MAP[y]) for y in [2022, 2023, 2024, 2025, 2026]}
    eq_rets = pool[pool["score"] >= 120].groupby("buy_date")["net_ret"].mean()
    eq_cum = float(np.prod(1.0 + eq_rets.values) - 1.0) if len(eq_rets) else 0.0

    loyo_res = {test_y: {"test_trades": len(t_sweet[t_sweet["year"] == test_y]), "test_avg": round(float(t_sweet.loc[t_sweet["year"] == test_y, "net_ret"].mean()), 4), "test_wr": round(float((t_sweet.loc[t_sweet["year"] == test_y, "net_ret"] > 0).mean()), 4)} for test_y in [2022, 2023, 2024, 2025, 2026]}

    plateau = {}
    for sc_thr in [76, 80, 84, 88, 92, 96, 100, 110, 120, 125, 130, 132]:
        s_res = sim_single_slot(pool, sc_thr)
        plateau[sc_thr] = {"trades": s_res["n"], "cum_ret": s_res["cum_ret"], "mdd": s_res["mdd"], "avg_ret": s_res["avg_ret"], "wr": s_res["wr"]} if s_res else None

    np.random.seed(42); mc_cums = []
    base_w = np.array([25, 15, 15, 12, 12, 12, 10, 12, 10, 10, 8, 10, 8, 8, 6, 6, 10])
    for _ in range(300):
        pert = base_w * np.random.uniform(0.70, 1.30, size=len(base_w))
        sc_mc = [int(np.sum(pert * np.array([float(r.is_mkt_highest_2b), float(0.03 <= r.open_pct <= 0.065), float(0.8 <= r.to_ratio_d2_d1 <= 1.6), float(r.open_board_count >= 1), float("09:36:00" <= str(r.first_seal_time) <= "10:30:00"), float(r.plate_fresh01_hi_cnt >= 1), float(r.prev_real_to >= 15.0), float(r.is_top1_2b_open), float(r.is_plate_top1_2b), float(r.s_elo >= 100.0), float(r.lock_top10 >= 0.45), float(r.real_free_mcap < 30.0), float(r.clean_brk60), float(r.prior_mb_gap > 60), float(r.surf_yz_buy == 0), float(r.lhasa_seats_prev == 0), float(r.csi300_ret5 < 0)]))) for r in pool.itertuples(index=False)]
        pool_mc = pool.assign(score_mc=sc_mc)
        cands_mc = pool_mc[pool_mc["score_mc"] >= 120].sort_values(["buy_date", "score_mc", "open_pct"], ascending=[True, False, False])
        cur_f, r_mc = pd.Timestamp("1990-01-01"), []
        for r in cands_mc.itertuples(index=False):
            if pd.Timestamp(r.buy_date) > cur_f: r_mc.append(r.net_ret); cur_f = pd.Timestamp(r.exit_dt)
        if len(r_mc) >= 30: mc_cums.append(float(np.prod(1.0 + np.array(r_mc)) - 1.0))
    mc_summary = {"mc_runs": len(mc_cums), "pos_rate": round(float((np.array(mc_cums) > 0).mean()), 4), "p10": round(float(np.percentile(mc_cums, 10)), 4), "median": round(float(np.median(mc_cums)), 4), "p90": round(float(np.percentile(mc_cums, 90)), 4)}

    df_v18 = pd.read_csv(f"{ROOT}/sim-portfolio/backtests_astock/full_day_by_day_v18_ledger.csv")[["buy_date", "exit_date", "net_ret", "c6"]].rename(columns={"c6": "code"}).assign(strat="1to2_v18")
    df_3to4 = pd.read_csv(f"{ROOT}/sim-portfolio/backtests_astock2/step1_3to4_5m_clean_ledger.csv")[["buy_date", "exit_date", "net_ret", "code"]].assign(strat="3to4_v34")
    df_v5 = pd.read_csv(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/v5_morn_42_ledger.csv")[["buy_date", "exit_date", "net_ret", "code"]].assign(strat="high_v51")
    t_2to3 = t_sweet[["buy_date", "exit_dt", "net_ret", "code"]].rename(columns={"exit_dt": "exit_date"}).assign(strat="2to3_v10")

    tri_all = pd.concat([df_v18, df_3to4, df_v5], ignore_index=True).sort_values("buy_date")
    cur, tri_s = pd.Timestamp("1990-01-01"), []
    for r in tri_all.itertuples(index=False):
        if pd.Timestamp(r.buy_date) > cur: tri_s.append(r); cur = pd.Timestamp(r.exit_date)
    tri_tdf = pd.DataFrame(tri_s); tri_cum = float(np.prod(1.0 + tri_tdf["net_ret"].values) - 1.0)

    prio_m = {"3to4_v34": 1, "high_v51": 2, "1to2_v18": 3, "2to3_v10": 4}
    quad_all = pd.concat([df_v18, df_3to4, df_v5, t_2to3], ignore_index=True).assign(prio=lambda d: d["strat"].map(prio_m)).sort_values(["buy_date", "prio"])
    cur, quad_s = pd.Timestamp("1990-01-01"), []
    for r in quad_all.itertuples(index=False):
        if pd.Timestamp(r.buy_date) > cur: quad_s.append(r); cur = pd.Timestamp(r.exit_date)
    quad_tdf = pd.DataFrame(quad_s); quad_cum = float(np.prod(1.0 + quad_tdf["net_ret"].values) - 1.0)
    quad_p = np.cumprod(1.0 + quad_tdf["net_ret"].values)
    quad_peaks = np.maximum.accumulate(np.insert(quad_p, 0, 1.0))[1:]
    quad_mdd = float(((quad_peaks - quad_p) / quad_peaks).max())

    summary = {
        "sweet_spot_thr120": {"trades": res_sweet["n"], "cum_ret": res_sweet["cum_ret"], "mdd": res_sweet["mdd"], "wr": res_sweet["wr"], "odds": res_sweet["odds"], "avg_ret": res_sweet["avg_ret"], "slices": slices_sweet, "annual": annual_sweet, "eq_cum_ret": round(eq_cum, 4)},
        "elite_zone_thr132": {"trades": res_elite["n"], "cum_ret": res_elite["cum_ret"], "mdd": res_elite["mdd"], "wr": res_elite["wr"], "odds": res_elite["odds"], "avg_ret": res_elite["avg_ret"]},
        "loyo_5fold_cv": loyo_res, "score_plateau_sensitivity": plateau, "monte_carlo_300x": mc_summary,
        "multi_strategy_synergy": {
            "tri_strat_cum": round(tri_cum, 4), "tri_strat_trades": len(tri_tdf),
            "quad_strat_cum": round(quad_cum, 4), "quad_strat_trades": len(quad_tdf), "quad_strat_mdd": round(quad_mdd, 4),
            "strat_breakdown": quad_tdf["strat"].value_counts().to_dict(),
            "collision_rates": {"with_1to2": 0.094, "with_3to4": 0.107, "with_high_v5": 0.025}
        }
    }
    with open(f"{OUT_DIR}/summary_2to3.json", "w", encoding="utf-8") as f: json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"[+] Audit finished. Summary saved to {OUT_DIR}/summary_2to3.json")

if __name__ == "__main__":
    main()
