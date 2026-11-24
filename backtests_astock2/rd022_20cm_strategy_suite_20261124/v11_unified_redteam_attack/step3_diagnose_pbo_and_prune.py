#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Step 3: Diagnose CSCV PBO root cause on DeepOpen V1.0, test pruned 9-10 item DeepOpen V1.1 (IS-calibrated), and test pruned Beta V1.1."""
import itertools, os, pickle, sys
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
V1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
B1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_beta_scorecard_exit"
PART2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
sys.path.insert(0, V1_DIR)
sys.path.insert(0, B1_DIR)
sys.path.insert(0, PART2_DIR)
sys.path.insert(0, OUT_DIR)

from backtest_utils import _sim_k_slots
from step3_oos_and_tables import FINAL_EXIT_CFG
from step2_audit_exits_and_beta import sim_deepopen_strict_exec
from v1_exit_engine import simulate_exit_v1, _sim_k_slots_v1


def cscv_detail(R: np.ndarray, labels: list, ng: int = 8) -> dict:
    gs = len(R) // ng
    gidx = [list(range(i * gs, (i + 1) * gs if i < ng - 1 else len(R))) for i in range(ng)]
    omegas, winners, ranks = [], [], []
    for te in itertools.combinations(range(ng), ng // 2):
        trg = [k for k in range(ng) if k not in te]
        tri = [x for k in trg for x in gidx[k]]
        tei = [x for k in te for x in gidx[k]]
        rt, re_ = R[tri], R[tei]
        sd_t, sd_e = rt.std(0, ddof=1), re_.std(0, ddof=1)
        st = np.divide(rt.mean(0), sd_t, out=np.zeros_like(sd_t), where=sd_t > 1e-12)
        se = np.divide(re_.mean(0), sd_e, out=np.zeros_like(sd_e), where=sd_e > 1e-12)
        b = int(np.argmax(st))
        winners.append(labels[b])
        omegas.append(float(np.mean(se > se[b])))
        ranks.append(float(np.mean(se <= se[b])))
    vc = pd.Series(winners).value_counts().to_dict()
    return {"pbo_pct": round(float(np.mean(np.array(omegas) > 0.50) * 100.0), 2), "mean_omega": round(float(np.mean(omegas)), 4), "winners": vc}


def build_daily_mat(df_sig: pd.DataFrame, th_list: list, all_dts: list) -> np.ndarray:
    t_days = [d for d in sorted(all_dts) if "2021-01-04" <= d <= "2026-11-23"]
    day_idx = {d: i for i, d in enumerate(t_days)}
    cols = []
    for th in th_list:
        s1, _, _ = _sim_k_slots(df_sig[df_sig["score"] >= th], 1)
        arr = np.zeros(len(t_days), dtype=float)
        for r in s1.itertuples(index=False):
            i = day_idx.get(str(r.exit_date))
            if i is not None: arr[i] += float(r.net_ret_eval)
        cols.append(arr)
    return np.column_stack(cols)


def compute_deepopen_v11(d: pd.DataFrame, include_rfm_small: bool = False, include_bias20: bool = True) -> tuple[np.ndarray, pd.DataFrame]:
    """Pruned 9-10 orthogonal physics factors (Base = 70). Zero scraper/Elo drift, zero small-N noise."""
    f = pd.DataFrame(index=d.index)
    # 1. Open Gap Zone (Micro-structure at 09:25)
    f["F01_open_gap_zone"] = np.where(d["f1_o_pct"] < -0.080, -12, np.where(d["f1_o_pct"].between(-0.065, -0.030), 5, 0))
    # 2. Low Position (20d bias <= 12%)
    if include_bias20:
        f["F02_bias20_le12"] = np.where(d["bias20"].fillna(1.0) <= 0.12, 8, 0)
    # 3. Regulatory Headroom (dist_3d30 >= 10%)
    f["F03_dist3d30_ge10"] = np.where(d["dist_3d30"].fillna(0.0) >= 0.10, 5, 0)
    # 4. Active Stock Memory (zt_cnt_60d >= 2)
    f["F04_zt60d_ge2"] = np.where(d["zt_cnt_60d"].fillna(0) >= 2, 6, 0)
    # 5. Fake Consensus Big Seal Low-Open Trap (seal_ratio >= 10%)
    f["F05_seal_ratio_ge10_pen"] = np.where(d["zt_seal_ratio"].fillna(0.0) >= 0.10, -7, 0)
    # 6. Institutional Net Buy on T0 LHB
    f["F06_inst_net_pos"] = np.where(d["lhb_inst_net"].fillna(0.0) > 0.0, 8, 0)
    # 7. Mainboard 10cm Risk-On Spillover (mkt10_zt > 70)
    f["F07_mkt10_zt_gt70"] = np.where(d["mkt10_zt_cnt"].fillna(0) > 70, 9, 0)
    # 8. 20cm Yizi Dragon Siphon at 09:25
    f["F08_yizi20_siphon_pen"] = np.where(d["f1_mkt20_0925_zt"].fillna(0) >= 1, -6, 0)
    # 9. Monday Opening Pressure
    f["F09_monday_pen"] = np.where(d["f1_weekday"] == 0, -10, 0)
    # Optional 10: Small free float <= 20B bonus ONLY (NO >40B penalty!)
    if include_rfm_small:
        f["F10_rfm_le20_pos"] = np.where(d["real_free_mcap"].fillna(999.0) <= 20.0, 4, 0)
    sc = 70.0 + f.sum(axis=1).to_numpy()
    return sc, f


def main():
    aux = pickle.load(open(f"{PART2_DIR}/cache_20cm_aux.pkl", "rb"))
    all_dts = aux["all_dts"]
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")
    pool = df[df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)

    # 1. Diagnose V1.0 PBO
    v1_sig = pd.read_csv(f"{V1_DIR}/all_scored_signals_v1.csv")
    v1_sig["c6"] = v1_sig["c6"].astype(str).str.zfill(6)
    th_lad = [70, 72, 74, 76, 78, 80, 82, 84, 86, 88]
    R_v1 = build_daily_mat(v1_sig, th_lad, all_dts)
    print("=== V1.0 CSCV DIAGNOSIS (18 items, th 70..88) ===")
    print("  S8 :", cscv_detail(R_v1, th_lad, 8))
    print("  S10:", cscv_detail(R_v1, th_lad, 10))
    for i, th in enumerate(th_lad):
        col = R_v1[:, i]
        sd = col.std(ddof=1)
        print(f"    th>={th}: sr_d={col.mean()/sd if sd>0 else 0:.4f}, nz_days={(col!=0).sum():3d}, nav={np.prod(1+col):.2f}x")

    # 2. Evaluate DeepOpen V1.1 pruned cards with STRICT +0.30% TP buffer!
    # Also compare Exit Tree with B2_d3_hold vs B2_d2_tp (no D3) vs PureT2
    for lbl, inc_rfm, inc_b20 in [("V11_9item", False, True), ("V11_10item_rfm20", True, True), ("V11_8item_nobias", False, False)]:
        sc, fm = compute_deepopen_v11(pool, include_rfm_small=inc_rfm, include_bias20=inc_b20)
        pool["score"] = sc
        tr_buf = sim_deepopen_strict_exec(pool, FINAL_EXIT_CFG, fee=0.0030, tp_buf=0.0030)
        tr_nod3 = sim_deepopen_strict_exec(pool, {**FINAL_EXIT_CFG, "b2_mode": "d2_tp"}, fee=0.0030, tp_buf=0.0030)
        print(f"\n=== [{lbl}] STRICT +0.30% TP BUFFER (Threshold Sweep) ===")
        for th in [70, 72, 74, 75, 76, 78, 80, 82, 85]:
            s_f, nv_f, mdd_f = _sim_k_slots(tr_buf[tr_buf["score"] >= th], 1)
            s_is, nv_is, _ = _sim_k_slots(tr_buf[(tr_buf["score"] >= th) & (tr_buf["buy_date"] <= "2024-08-31")], 1)
            s_oo, nv_oo, _ = _sim_k_slots(tr_buf[(tr_buf["score"] >= th) & (tr_buf["buy_date"] >= "2024-09-01")], 1)
            s_25, nv_25, _ = _sim_k_slots(tr_buf[(tr_buf["score"] >= th) & (tr_buf["buy_date"].str[:4] == "2025")], 1)
            s_26, nv_26, _ = _sim_k_slots(tr_buf[(tr_buf["score"] >= th) & (tr_buf["buy_date"].str[:4] == "2026")], 1)
            _, nv_nd3_oo, _ = _sim_k_slots(tr_nod3[(tr_nod3["score"] >= th) & (tr_nod3["buy_date"] >= "2024-09-01")], 1)
            print(f"  th>={th:2d} | N={len(s_f):3d}(IS={len(s_is):3d},OOS={len(s_oo):2d},25={len(s_25):2d},26={len(s_26):2d}) | "
                  f"FULL={nv_f:6.2f}x MDD={mdd_f*100:4.1f}% | IS={nv_is:6.2f}x | OOS={nv_oo:5.2f}x(noD3={nv_nd3_oo:5.2f}x) | 25={nv_25:4.2f}x | 26={nv_26:4.2f}x")
        R_11 = build_daily_mat(tr_buf, th_lad, all_dts)
        print("  CSCV S8 :", cscv_detail(R_11, th_lad, 8))
        print("  CSCV S10:", cscv_detail(R_11, th_lad, 10))


if __name__ == "__main__":
    main()
