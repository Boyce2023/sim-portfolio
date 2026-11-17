#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
p1_task1_entry_exit_duel.py: 任务一：真假撬板买法与短平快卖法正面对决
严格遵守 D12、D15、零未来函数与反幸存者偏差铁律。
"""
import os
import sys
import json
import time
import pickle
import numpy as np
import pandas as pd

WORK_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p4_pry_board"
MAT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
if WORK_DIR not in sys.path:
    sys.path.insert(0, WORK_DIR)

from p1_sim_engine import (
    precompute_all_entries_and_exits,
    build_trades_dataframe,
    eval_d15_all,
    CSI_BENCHMARKS,
    FEE_RATE,
)


def run_task1():
    t0 = time.time()
    print("[+] Loading cand_pry_limitdown.parquet & code_bars_5y.pkl...")
    df = pd.read_parquet(f"{MAT_DIR}/cand_pry_limitdown.parquet")
    with open(f"{MAT_DIR}/code_bars_5y.pkl", "rb") as f:
        cb = pickle.load(f)["code_bars"]

    # 1. 反幸存者偏差与退市/仙股过滤
    delist_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
    df_d = pd.read_parquet(delist_path)
    delist_tickers = set(df_d["ticker"].str[:6].unique())

    open_raw = np.zeros(len(df), dtype=float)
    codes = df["code"].values
    buy_dates = df["buy_date"].values
    for i in range(len(df)):
        c = codes[i]
        bd = buy_dates[i]
        b = cb[c]
        pos = b["date_to_pos"][bd]
        open_raw[i] = float(b["open"][pos])
    df["open_px_raw"] = open_raw

    is_st_name = df["name"].str.contains("ST|退", na=False).values
    is_penny = df["open_px_raw"].values < 2.0
    is_in_delist_db = df["code"].isin(delist_tickers).values

    print(f"Total rows in cand_pry_limitdown: {len(df)}")
    print(f"ST / 退 names: {is_st_name.sum()}")
    print(f"Open price < 2.0: {is_penny.sum()}")
    print(f"In delisted db: {is_in_delist_db.sum()} (non-ST delisted: {(is_in_delist_db & (~is_st_name)).sum()})")

    # 基础候选池（剔除ST/退市名/开盘低于2元）
    base_mask = (~is_st_name) & (~is_penny)
    print(f"Base pool valid candidates: {base_mask.sum()} / {len(df)}")

    # 2. 预计算买卖矩阵
    print("[+] Precomputing B1~B5 x E1~E6 entry-exit outcome matrix...")
    pre = precompute_all_entries_and_exits(df, cb)

    BUY_MODES = ["B1_auc_deep_open", "B2_pry_2tick", "B3_pry_lift_15pct", "B4_pry_lift_25pct", "B5_open_or_lift15"]
    EXIT_MODES = ["E1_next_open", "E2_tp5_h2", "E3_tp7_h2", "E4_tp7_h3", "E5_tp7_h5", "E6_cut_reseal_tp7_h3"]

    results_matrix = {}
    prio_deep10 = -df["ret_pre10"].values.astype(float)

    for bm in BUY_MODES:
        results_matrix[bm] = {}
        for em in EXIT_MODES:
            tdf = build_trades_dataframe(df, pre, base_mask, bm, em, prio_deep10)
            ev = eval_d15_all(tdf)
            results_matrix[bm][em] = ev

    # 3. 核验 B6: 5m 真实切片核验
    print("[+] Evaluating B6: 5m Verified Subset on B3/B4 real intraday slippage & re-seal...")
    p5m_3 = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cand_5m_bars_v15_complete.parquet"
    df_v15 = pd.read_parquet(p5m_3)

    b6_results = []
    # Merge 5m with base candidates
    df_base = df[base_mask].copy()
    overlap_keys = set(zip(df_base["code"], df_base["buy_date"]))

    v15_grouped = df_v15.groupby(["c6", "date"])
    for (c, bd), group in v15_grouped:
        if (c, bd) not in overlap_keys:
            continue
        b = cb[c]
        pos = b["date_to_pos"][bd]
        dt_px = float(b["dt_px"][pos])
        op = float(b["open"][pos])
        cl = float(b["close"][pos])
        hi = float(b["high"][pos])

        if op > dt_px + 0.011:
            continue  # Not opened at limit down

        trig15 = round(dt_px * 1.015, 2)
        trig25 = round(dt_px * 1.025, 2)

        # 扫描 48 根 5m bar
        b3_hit_time, b3_exec_px = None, None
        b4_hit_time, b4_exec_px = None, None

        bars = group.sort_values("time")
        for idx_b, bar in bars.iterrows():
            b_hi = float(bar["high"])
            b_op = float(bar["open"])
            b_t = str(bar["time"])

            if b3_hit_time is None and b_hi >= trig15:
                b3_hit_time = b_t
                b3_exec_px = max(trig15, b_op)

            if b4_hit_time is None and b_hi >= trig25:
                b4_hit_time = b_t
                b4_exec_px = max(trig25, b_op)

        day0_reseal = bool(cl <= dt_px + 0.011 or cl < trig15 * 0.985)
        day0_ret_b3 = float(cl / trig15 - 1.0) if b3_hit_time else None

        b6_results.append({
            "code": c,
            "buy_date": bd,
            "dt_px": dt_px,
            "day_high": hi,
            "day_close": cl,
            "b3_triggered": b3_hit_time is not None,
            "b3_hit_time": b3_hit_time,
            "b3_slip_pct": round((b3_exec_px / trig15 - 1.0) * 100, 3) if b3_exec_px else None,
            "b4_triggered": b4_hit_time is not None,
            "b4_hit_time": b4_hit_time,
            "b4_slip_pct": round((b4_exec_px / trig25 - 1.0) * 100, 3) if b4_exec_px else None,
            "day0_reseal": day0_reseal,
            "day0_ret_b3": day0_ret_b3,
        })

    df_b6 = pd.DataFrame(b6_results)
    b6_summary = {
        "total_5m_limitdown_overlap": len(df_b6),
        "b3_trigger_count": int(df_b6["b3_triggered"].sum()) if len(df_b6) else 0,
        "b3_trigger_rate_pct": round(float(df_b6["b3_triggered"].mean() * 100), 2) if len(df_b6) else 0.0,
        "b3_avg_slip_pct": round(float(df_b6["b3_slip_pct"].dropna().mean()), 3) if len(df_b6) and df_b6["b3_slip_pct"].notna().sum() else 0.0,
        "b4_trigger_count": int(df_b6["b4_triggered"].sum()) if len(df_b6) else 0,
        "b4_trigger_rate_pct": round(float(df_b6["b4_triggered"].mean() * 100), 2) if len(df_b6) else 0.0,
        "b4_avg_slip_pct": round(float(df_b6["b4_slip_pct"].dropna().mean()), 3) if len(df_b6) and df_b6["b4_slip_pct"].notna().sum() else 0.0,
        "b3_day0_reseal_count": int(df_b6[df_b6["b3_triggered"]]["day0_reseal"].sum()) if len(df_b6) else 0,
        "b3_day0_reseal_rate_pct": round(float(df_b6[df_b6["b3_triggered"]]["day0_reseal"].mean() * 100), 2) if len(df_b6) and df_b6["b3_triggered"].sum() else 0.0,
    }
    print(f"B6 5m Audit Summary: {b6_summary}")

    # 4. 汇总对照表并保存
    summary_rows = []
    for bm in BUY_MODES:
        for em in EXIT_MODES:
            ev = results_matrix[bm][em]
            f5 = ev.get("full_5y", {})
            is_m = ev.get("is_2022_2024", {})
            oos_m = ev.get("oos_2025_2026", {})
            h2 = ev.get("half2_5y", {})

            summary_rows.append({
                "buy_mode": bm,
                "exit_mode": em,
                # 5Y 全景
                "5y_raw_n": f5.get("raw_n", 0),
                "5y_single_n": f5.get("single_n", 0),
                "5y_single_wr": f5.get("wr", 0.0),
                "5y_single_payoff": f5.get("payoff", 0.0),
                "5y_single_nav": f5.get("single_nav", 1.0),
                "5y_single_mdd": f5.get("single_mdd_pct", 0.0),
                "5y_trimmed3_nav": f5.get("trimmed3_nav", 1.0),
                "5y_half2_nav": h2.get("nav", 1.0),
                "5y_half2_mdd": h2.get("mdd_pct", 0.0),
                "5y_eq_nav": f5.get("eq_nav", 1.0),
                "5y_single_excess": f5.get("single_excess_pct", 0.0),
                # IS 2022-2024
                "is_single_n": is_m.get("single_n", 0),
                "is_single_wr": is_m.get("wr", 0.0),
                "is_single_payoff": is_m.get("payoff", 0.0),
                "is_single_nav": is_m.get("single_nav", 1.0),
                "is_single_mdd": is_m.get("single_mdd_pct", 0.0),
                "is_single_excess": is_m.get("single_excess_pct", 0.0),
                # OOS 2025-2026
                "oos_single_n": oos_m.get("single_n", 0),
                "oos_single_wr": oos_m.get("wr", 0.0),
                "oos_single_payoff": oos_m.get("payoff", 0.0),
                "oos_single_nav": oos_m.get("single_nav", 1.0),
                "oos_single_mdd": oos_m.get("single_mdd_pct", 0.0),
                "oos_single_excess": oos_m.get("single_excess_pct", 0.0),
            })

    df_summary = pd.DataFrame(summary_rows)
    out_csv = f"{WORK_DIR}/p1_task1_duel_matrix.csv"
    df_summary.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"[+] Task 1 Duel Matrix saved to: {out_csv}")

    out_json = f"{WORK_DIR}/p1_task1_summary.json"
    task1_data = {
        "b6_5m_summary": b6_summary,
        "results_matrix": results_matrix,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(task1_data, f, indent=2, ensure_ascii=False)
    print(f"[+] Task 1 JSON saved to: {out_json} (Elapsed: {time.time()-t0:.1f}s)")


if __name__ == "__main__":
    run_task1()
