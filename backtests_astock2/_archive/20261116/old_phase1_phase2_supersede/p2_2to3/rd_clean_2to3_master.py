#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RD 终审定版：二进三 42 因子修正检验 (lock_top10百分制 + dd60比值制) + 零穿越时序引擎 + 纯整数打分卡审计"""
import os, sys, json, pickle
import numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
AST2 = f"{ROOT}/sim-portfolio/backtests_astock2"
sys.path.insert(0, AST2)
from core_3to4_5m_engine import _slice_metrics_chrono, csi300_ret

OUT_DIR = f"{AST2}/p2_2to3"

def build_clean_score_2to3(df):
    sc = np.zeros(len(df), dtype=int)
    veto = (
        (df["prev_is_yizi"] == True) |
        (df["to_ratio_d2_d1"] < 0.55) |
        (df["open_pct"] < -0.015) | (df["open_pct"] >= 0.070) |
        (df["has_tox_notice"] == True) | (df["has_stock_reg"] == True) | (df["has_ex_reg"] == True) |
        (df["first_seal_time"].astype(str) <= "09:33:00") |
        (df["first_seal_time"].astype(str) >= "14:15:00") |
        (df["px_d2"] >= 28.0) |
        (df["prev_break_dt_rate_10d"] > 0.30)
    )
    # 100% 双期同向物理因子（彻底剔除 2024-2026 翻负的 is_mkt_highest_2b！）
    sc += np.where(df["lock_top10"] >= 55.0, 18, np.where(df["lock_top10"] >= 48.0, 10, np.where(df["lock_top10"] < 32.0, -10, 0)))
    sc += np.where(df["dd60"] <= 0.80, 18, np.where(df["dd60"] <= 0.88, 10, 0))
    sc += np.where(df["open_board_count"] >= 1, 14, -8)
    sc += np.where(df["prev_real_to"].between(15.0, 48.0), 12, np.where(df["prev_real_to"] > 58.0, -8, 0))
    sc += np.where(df["to_ratio_d2_d1"].between(0.80, 1.65), 10, 0)
    sc += np.where(df["first_seal_time"].astype(str).between("09:36:00", "10:30:00"), 10, 0)
    sc += np.where(df["open_pct"].between(0.025, 0.062), 14, np.where(df["open_pct"].between(0.005, 0.025), 6, 0))
    sc += np.where(df["is_top1_2b_open"] == True, 14, 0)
    sc += np.where(df["is_plate_top1_2b"] == True, 8, -8)
    sc += np.where(df["plate_fresh01_hi_cnt"] >= 1, 12, 0)
    sc += np.where(df["s_elo"] >= 100.0, 8, -8)
    sc += np.where(df["csi300_ret20"] >= -0.02, 10, -6)
    sc += np.where(df["mkt_seal_rate_prev"] >= 0.65, 8, 0)
    sc += np.where(df["prev_3b_dt_cnt"] == 0, 8, -6)
    sc += np.where(df["surf_yz_buy"] >= 1, -14, 0)
    sc += np.where(df["top_yz_buy"] >= 1, -10, 0)
    sc += np.where(df["lhasa_seats_prev"] == 0, 6, -6)
    return np.where(veto, -999, sc)

def strict_top1_eval(df, traj, sc, thr):
    c = df[sc >= thr].assign(sc=sc[sc >= thr], idx=np.where(sc >= thr)[0])
    top_rows = []
    for bd, g in c.groupby("buy_date", sort=True):
        g_s = g.sort_values(["sc", "open_pct", "lock_top10"], ascending=[False, False, False])
        i0 = int(g_s["idx"].iloc[0])
        if traj[i0] is not None:
            top_rows.append(dict(traj[i0], priority_score=float(g_s["sc"].iloc[0]), score=int(g_s["sc"].iloc[0])))
    tdf = pd.DataFrame(top_rows)
    all_rows = [dict(traj[i], priority_score=float(sc[i]), score=int(sc[i])) for i in np.where(sc >= thr)[0] if traj[i] is not None]
    tdf_all = pd.DataFrame(all_rows)
    return tdf, tdf_all

def main():
    df = pd.read_parquet(f"{OUT_DIR}/cand_2to3_enriched.parquet")
    with open(f"{OUT_DIR}/rd_trajectories_5m.pkl", "rb") as f:
        trajs = pickle.load(f)
    tr_opn = trajs["open_reb2"]
    tr_t65 = trajs["touch65_reb2"]
    df["ret_clean"] = [x["net_ret"] if x else np.nan for x in tr_opn]

    pool = df[(~df["prev_is_yizi"]) & (df["open_pct"] >= -0.04) & df["ret_clean"].notna()].copy()
    pool["yr"] = pd.to_datetime(pool["buy_date"]).dt.year
    b_avg = float(pool["ret_clean"].mean())

    # Check corrected dd60 & lock_top10 first!
    for tag, msk in [
        ("dd60<=0.80 (60日超跌>=20%黄金坑)", pool["dd60"] <= 0.80),
        ("dd60<=0.85 (60日回撤>=15%黄金坑)", pool["dd60"] <= 0.85),
        ("lock_top10>=50% (前十锁仓>=50%)", pool["lock_top10"] >= 50.0),
        ("lock_top10>=55% (前十锁仓>=55%)", pool["lock_top10"] >= 55.0),
        ("lock>=50% & dd60<=0.85 (锁仓黄金坑共振)", (pool["lock_top10"] >= 50.0) & (pool["dd60"] <= 0.85)),
    ]:
        s = pool.loc[msk]
        e_m = s.loc[s["buy_date"] < "2024-01-01", "ret_clean"].mean() * 100
        l_m = s.loc[s["buy_date"] >= "2024-01-01", "ret_clean"].mean() * 100
        print(f"{tag:36s} | n={len(s):4d} WR={(s['ret_clean']>0).mean()*100:4.1f}% avg={s['ret_clean'].mean()*100:+5.2f}% (22-23:{e_m:+5.2f}%, 24-26:{l_m:+5.2f}%)")

    sc = build_clean_score_2to3(df)
    for mode_nm, tr in [("Open+Reb2", tr_opn), ("Touch65+Reb2", tr_t65)]:
        print(f"\n=== 二进三 V1.0 分数线平原 [{mode_nm}] (剔除翻负因子 + 修正锁仓/黄金坑 + 严格单仓) ===")
        for thr in [80, 86, 92, 96, 100, 104, 108, 112]:
            t_top, t_all = strict_top1_eval(df, tr, sc, thr)
            if t_top.empty: continue
            m5 = _slice_metrics_chrono(t_top, "2022-01-04", "2026-11-10")
            m_eq = _slice_metrics_chrono(t_all, "2022-01-04", "2026-11-10")
            m3 = _slice_metrics_chrono(t_top[t_top.buy_date >= "2024-01-02"], "2024-01-02", "2026-11-10")
            mj = _slice_metrics_chrono(t_top[t_top.buy_date >= "2026-07-01"], "2026-07-01", "2026-11-10")
            yrs = [(_slice_metrics_chrono(t_top[t_top.buy_date.str.startswith(str(y))], f"{y}-01-01", f"{y}-12-31")["single_nav"] - 1.0) * 100 for y in [2022,2023,2024,2025,2026]]
            pos_y = sum(1 for x in yrs if x > 0)
            print(f"thr>={thr:3d} | 单仓{m5['single_n']:3d}笔 WR={m5['wr']:4.1f}% PO={m5['payoff']:4.2f} 均={m5['mean_pct']:+5.2f}% NAV={m5['single_nav']:6.2f}x MDD={m5['single_mdd_pct']:4.1f}% 等权={m_eq['eq_nav']:6.2f}x | 近3年={m3['single_nav']:5.2f}x | 7月起={mj['single_n']}笔/{mj['single_nav']:.2f}x | 正年={pos_y}/5 {[round(x,1) for x in yrs]}")

if __name__ == "__main__":
    main()
