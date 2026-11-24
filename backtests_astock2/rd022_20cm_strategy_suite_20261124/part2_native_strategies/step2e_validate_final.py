#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 2e: Full blind OOS/2026/D15 validation, yearly breakdown, and monkey-draw p-value for P1, P2, P3."""
import json, pickle, time
import numpy as np
import pandas as pd
from backtest_utils import calc_d15_suite, _sim_k_slots
from step2d_scorers import score_p1_s1, score_p2_s3, score_p3_s4, sim_exit_v2

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"


def monkey_pvalue(sub_tr: pd.DataFrame, bg_rets: np.ndarray, n_pick: int, obs_nav: float, n_sim: int = 5000) -> float:
    rng = np.random.default_rng(42)
    if n_pick <= 0 or len(bg_rets) == 0:
        return 1.0
    wins = 0
    for _ in range(n_sim):
        draw = rng.choice(bg_rets, size=n_pick, replace=True)
        if np.prod(1.0 + draw) >= obs_nav:
            wins += 1
    return round(wins / n_sim, 4)


def yearly_table(trades: pd.DataFrame) -> dict:
    out = {}
    if trades.empty:
        return out
    for yr in ["2021", "2022", "2023", "2024", "2025", "2026"]:
        sub = trades[trades["buy_date"].str.startswith(yr)]
        if sub.empty:
            out[yr] = {"n_1s": 0, "nav_1s": 1.0, "ew_nav": 1.0}
            continue
        t1, nav1, mdd1 = _sim_k_slots(sub, 1)
        t3, nav3, _ = _sim_k_slots(sub, 3)
        ew = float(np.prod(1.0 + sub.groupby("buy_date")["net_ret"].mean().to_numpy()))
        r1 = t1["net_ret_eval"].to_numpy()
        out[yr] = {
            "raw_n": int(len(sub)), "n_1s": int(len(t1)),
            "wr_1s": round(float((r1 > 0).mean() * 100), 1),
            "nav_1s": round(nav1, 3), "mdd_1s": round(mdd1 * 100, 1),
            "nav_3s": round(nav3, 3), "ew_nav": round(ew, 3),
        }
    return out


def main():
    t0 = time.time()
    df = pd.read_parquet(f"{OUT_DIR}/cache_20cm_panel.parquet")
    g = df.groupby("c6", sort=False)
    df["prev_zt_obc"] = g["zt_obc"].shift(1).fillna(-1).astype(int)
    aux = pickle.load(open(f"{OUT_DIR}/cache_20cm_aux.pkl", "rb"))
    sh300, ew20 = aux["sh300"], aux["ew20_daily"]

    configs = [
        ("P1_S1_DeepOpen", score_p1_s1, [70.0, 75.0, 80.0], ["T2_close", "T2_zt_tp10"]),
        ("P2_S3_BrokenYang", score_p2_s3, [70.0, 78.0, 84.0], ["T2_zt_ride", "T2_close"]),
        ("P3_S4_ZhabanAntiNuke", score_p3_s4, [70.0, 75.0, 80.0], ["T2_gap_cut_only", "T2_close"]),
    ]

    summary = {}
    chosen_ledgers = {}

    for pname, scorer, ths, exits in configs:
        skel, sc = scorer(df)
        df_pool = df[skel].copy()
        df_pool["score"] = sc[skel].values
        print(f"\n==================== {pname} (Skeleton N={len(df_pool)}) ====================")
        # Baseline background returns for monkey p-value
        tr_bg = sim_exit_v2(df_pool, exits[0])
        bg_rets = tr_bg["net_ret"].to_numpy()

        best_key = None
        best_res = None
        best_tr = None
        all_grid = {}
        for th in ths:
            sub_p = df_pool[df_pool["score"] >= th]
            for ex in exits:
                tr = sim_exit_v2(sub_p, ex)
                m = calc_d15_suite(tr, sh300, ew20)
                key = f"th{int(th)}_{ex}"
                all_grid[key] = m
                IS, OOS, Y26, FULL = m["IS"], m["OOS"], m["2026"], m["FULL"]
                print(f"  {key:24s} | IS: N={IS.get('n_1s',0):3d} WR={IS.get('wr_1s',0):4.1f}% 1s={IS.get('nav_1s',1):5.2f}x 3s={IS.get('nav_3s',1):5.2f}x ew={IS.get('ew_nav',1):5.2f}x | "
                      f"OOS: N={OOS.get('n_1s',0):3d} WR={OOS.get('wr_1s',0):4.1f}% 1s={OOS.get('nav_1s',1):5.2f}x 3s={OOS.get('nav_3s',1):5.2f}x ew={OOS.get('ew_nav',1):5.2f}x | "
                      f"26:1s={Y26.get('nav_1s',1):4.2f}x 3s={Y26.get('nav_3s',1):4.2f}x | FULL:1s={FULL.get('nav_1s',1):6.2f}x ex5={FULL.get('ex5_1s',1):5.2f}x f50={FULL.get('fee50_1s',1):5.2f}x")
                # Pick standard IS-calibrated rule (avoid over-filtering N_IS < 40)
                if th == ths[1] and ex == exits[0]:
                    best_key, best_res, best_tr = key, m, tr

        # Also save strict tier if ths[2] has N_IS >= 35
        yr_tbl = yearly_table(best_tr)
        t1_full, nav1_full, _ = _sim_k_slots(best_tr, 1)
        p_val = monkey_pvalue(best_tr, bg_rets, len(t1_full), nav1_full)
        print(f"  -> SELECTED [{best_key}] Monkey p={p_val:.4f} | Yearly: " +
              " | ".join(f"{y}:{v['nav_1s']}x(N={v['n_1s']})" for y, v in yr_tbl.items()))
        summary[pname] = {
            "selected": best_key, "metrics": best_res, "yearly": yr_tbl,
            "monkey_p": p_val, "all_grid": all_grid,
        }
        best_tr.to_csv(f"{OUT_DIR}/ledger_{pname.lower()}.csv", index=False)

    with open(f"{OUT_DIR}/part2_final_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n[DONE] Saved part2_final_summary.json & 3 strategy ledgers in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
