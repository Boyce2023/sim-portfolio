#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 3: Final IS-calibrated scoring + dynamic exit validation for P1_S1_DeepOpen & P1B_BigYang_DeepOpen, plus full D15 ledger export."""
import json, pickle, time
import numpy as np
import pandas as pd
from backtest_utils import calc_d15_suite, _sim_k_slots
from step2c_is_exit_probe import sim_dynamic_exit
from step2d_scorers import score_p1_s1, score_p2_s3, score_p3_s4, sim_exit_v2
from step2e_validate_final import monkey_pvalue, yearly_table

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"


def score_p1_s1_final(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Final P1_S1_DeepOpen: T0 non-yizi first 20cm ZT (amount>=1e8), mkt20_zt<16 overheat veto, T+1 open -10% ~ -3.5%."""
    skel, sc = score_p1_s1(df)
    skel_f = skel & (df["mkt20_zt_cnt"] < 16) & (df["amount"] >= 1e8)
    return skel_f, sc


def score_p1b_final(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """IS-calibrated P1B_BigYang_DeepOpen: T0 non-ZT strong yang +12%~+19.4%, to<=30%, mkt20_zt<16, T+1 open -5.0% ~ -3.0%."""
    skel = (
        df["tradable"] & (df["is_st_pit"] == 0) & (df["close"] >= 2.0)
        & (df["tox_90d"] == 0) & (df["reg_10d"] == 0)
        & (~df["is_zt"]) & df["ret"].between(0.12, 0.194) & df["is_true_yang"]
        & (df["to"] <= 30.0) & (df["amount"] >= 1e8) & (df["mkt20_zt_cnt"] < 16)
        & df["f1_buyable"] & df["f1_o_pct"].between(-0.050, -0.030)
    )
    sc = np.full(len(df), 70.0)
    sc += np.where(df["bias20"] <= 0.12, 10.0, 0.0)
    sc += np.where(df["close"] <= 25.0, 8.0, 0.0)
    sc += np.where(df["real_free_mcap"] <= 30.0, 6.0, 0.0)
    sc += np.where(df["real_to"] < 20.0, 6.0, 0.0)
    sc += np.where(df["prev_pos20"] <= 0.50, 4.0, 0.0)
    sc += np.where(df["lhb_inst_net"] > 0, 6.0, 0.0)
    sc += np.where((df["lhb_has"] == 1) & (df["lhb_inst_net"] <= 0), -10.0, 0.0)
    sc += np.where(df["is_tech"] == 1, -4.0, 0.0)
    sc += np.where(df["close"] > 40.0, -6.0, 0.0)
    wd = pd.to_datetime(df["f1_dt"], errors="coerce").dt.dayofweek.fillna(-1)
    sc += np.where(wd == 0, -4.0, 0.0)
    return skel, pd.Series(sc, index=df.index)


def full_report(name: str, tr: pd.DataFrame, bg_rets: np.ndarray, sh300: dict, ew20: dict) -> dict:
    m = calc_d15_suite(tr, sh300, ew20)
    yt = yearly_table(tr)
    t1, nav1, _ = _sim_k_slots(tr, 1)
    pv = monkey_pvalue(tr, bg_rets, len(t1), nav1, n_sim=5000)
    print(f"\n==================== {name} (Monkey p={pv:.4f}) ====================")
    for w in ("FULL", "IS", "OOS", "2026"):
        mw = m[w]
        print(f"  {w:4s} | raw={mw.get('raw_n',0):3d} 1sN={mw.get('n_1s',0):3d} WR={mw.get('wr_1s',0):5.1f}% PO={mw.get('po_1s',0):4.2f} "
              f"1s={mw.get('nav_1s',1):6.2f}x MDD={mw.get('mdd_1s',0):5.1f}% ex5={mw.get('ex5_1s',1):6.2f}x f50={mw.get('fee50_1s',1):6.2f}x | "
              f"3s={mw.get('nav_3s',1):5.2f}x MDD3={mw.get('mdd_3s',0):5.1f}% f50_3s={mw.get('fee50_3s',1):5.2f}x | ew={mw.get('ew_nav',1):6.2f}x | "
              f"exHS300={mw.get('ex_hs300_1s',0):+8.1f}pp ex20EW={mw.get('ex_ew20_1s',0):+8.1f}pp HLZ_t={mw.get('hlz_t',0):5.2f}")
    print("  Yearly:", " | ".join(f"{y}:{v['nav_1s']}x(N={v['n_1s']},WR={v.get('wr_1s',0)}%,3s={v.get('nav_3s',1)}x)" for y, v in yt.items()))
    return {"metrics": m, "yearly": yt, "monkey_p": pv}


def main():
    t0 = time.time()
    df = pd.read_parquet(f"{OUT_DIR}/cache_20cm_panel.parquet")
    g = df.groupby("c6", sort=False)
    df["prev_zt_obc"] = g["zt_obc"].shift(1).fillna(-1).astype(int)
    aux = pickle.load(open(f"{OUT_DIR}/cache_20cm_aux.pkl", "rb"))
    sh300, ew20 = aux["sh300"], aux["ew20_daily"]

    summary = {}

    # 1. P1_S1_DeepOpen_V1 (Selected: th>=75, T2_zt_tp10, plus T2_close robustness)
    sk1, sc1 = score_p1_s1_final(df)
    p1 = df[sk1].copy(); p1["score"] = sc1[sk1].values
    bg1 = sim_exit_v2(p1, "T2_zt_tp10")["net_ret"].to_numpy()
    tr1_tp = sim_exit_v2(p1[p1["score"] >= 75.0], "T2_zt_tp10")
    tr1_cl = sim_exit_v2(p1[p1["score"] >= 75.0], "T2_close")
    summary["P1_S1_DeepOpen_zt_tp10"] = full_report("P1_S1_DeepOpen [th>=75 + mkt20<16 + amt>=1e8 + T2_zt_tp10]", tr1_tp, bg1, sh300, ew20)
    summary["P1_S1_DeepOpen_T2_close"] = full_report("P1_S1_DeepOpen [th>=75 + mkt20<16 + amt>=1e8 + T2_close]", tr1_cl, bg1, sh300, ew20)
    tr1_tp.to_csv(f"{OUT_DIR}/ledger_p1_s1_deepopen.csv", index=False)

    # 2. P1B_BigYang_DeepOpen_V1 (test th>=70, 74, 78 across T2_close & T2_tp10_weakcut)
    sk1b, sc1b = score_p1b_final(df)
    p1b = df[sk1b].copy(); p1b["score"] = sc1b[sk1b].values
    bg1b = sim_dynamic_exit(p1b, "T2_tp10_weakcut")["net_ret"].to_numpy()
    for th in [70.0, 74.0, 78.0]:
        for ex in ["T2_close", "T2_tp10_weakcut", "T2_gap_cut_only"]:
            tr1b = sim_dynamic_exit(p1b[p1b["score"] >= th], ex)
            res1b = full_report(f"P1B_BigYang [th>={int(th)} + {ex}]", tr1b, bg1b, sh300, ew20)
            summary[f"P1B_th{int(th)}_{ex}"] = res1b
            if th == 74.0 and ex == "T2_tp10_weakcut":
                tr1b.to_csv(f"{OUT_DIR}/ledger_p1b_bigyang_deepopen.csv", index=False)

    # 3. Also export P2_S3 & P3_S4 summary cleanly into part2_final_summary.json
    sk2, sc2 = score_p2_s3(df)
    p2 = df[sk2].copy(); p2["score"] = sc2[sk2].values
    tr2 = sim_exit_v2(p2[p2["score"] >= 78.0], "T2_zt_ride")
    summary["P2_S3_BrokenYang_ref"] = full_report("P2_S3_BrokenYang [th>=78, OOS_1s=0.86x -> FALSIFIED]", tr2, tr2["net_ret"].to_numpy(), sh300, ew20)
    tr2.to_csv(f"{OUT_DIR}/ledger_p2_s3_brokenyang.csv", index=False)

    sk3, sc3 = score_p3_s4(df)
    p3 = df[sk3].copy(); p3["score"] = sc3[sk3].values
    tr3 = sim_exit_v2(p3[p3["score"] >= 75.0], "T2_gap_cut_only")
    summary["P3_S4_Zhaban_ref"] = full_report("P3_S4_Zhaban [th>=75, OOS_1s=0.82x -> FALSIFIED]", tr3, tr3["net_ret"].to_numpy(), sh300, ew20)
    tr3.to_csv(f"{OUT_DIR}/ledger_p3_s4_zhaban.csv", index=False)

    with open(f"{OUT_DIR}/part2_final_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n[DONE] Saved final summary & all ledgers in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
