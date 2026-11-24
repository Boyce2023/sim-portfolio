#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Step 10: Inspect 47.5% MDD cause in A>=76 vs 29.2% in A>=80, and check flat-weight V11 variants for <15% PBO & <32% MDD."""
import os, pickle, sys
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
V1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
PART2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
sys.path.insert(0, V1_DIR); sys.path.insert(0, PART2_DIR); sys.path.insert(0, OUT_DIR)

from backtest_utils import _sim_k_slots
from step3_oos_and_tables import FINAL_EXIT_CFG
from step2_audit_exits_and_beta import sim_deepopen_strict_exec
from step7_is_refine_card_and_pbo import build_refined_cards
from step3_diagnose_pbo_and_prune import cscv_detail, build_daily_mat


def inspect_mdd_period(tr_c: pd.DataFrame, th: float):
    s1, nav, mdd = _sim_k_slots(tr_c[tr_c["score"] >= th], 1)
    r = s1["net_ret_eval"].to_numpy()
    cum = np.cumprod(1.0 + r)
    pk = np.maximum.accumulate(cum)
    dd = (pk - cum) / pk
    i_end = int(np.argmax(dd))
    i_start = int(np.argmax(cum[:i_end + 1]))
    print(f"  [th>={th}] MaxDD={mdd*100:.1f}% from {s1.iloc[i_start]['buy_date']} (nav={cum[i_start]:.2f}) to {s1.iloc[i_end]['exit_date']} (nav={cum[i_end]:.2f}), trades in DD={i_end-i_start}")
    print(s1.iloc[i_start+1:min(i_end+1, i_start+10)][["buy_date", "exit_date", "c6", "score", "net_ret_eval", "exit_reason"]].to_string(index=False))


def main():
    aux = pickle.load(open(f"{PART2_DIR}/cache_20cm_aux.pkl", "rb"))
    all_dts = aux["all_dts"]
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")
    pool = df[df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    deep_cfg = {**FINAL_EXIT_CFG, "zt_imm": False}
    tr_base = sim_deepopen_strict_exec(pool, deep_cfg, fee=0.0030, tp_buf=0.0030)

    cards = build_refined_cards(pool)
    sc, fm = cards["V11_10_late_rfm"]
    sc_map = dict(zip(zip(pool["dt"], pool["c6"]), sc))
    tr_c = tr_base.copy()
    tr_c["score"] = [sc_map[(r.sig_date, r.c6)] for r in tr_c.itertuples(index=False)]

    print("=== MDD ANATOMY IN V11_10_late_rfm ===")
    inspect_mdd_period(tr_c, 76)
    inspect_mdd_period(tr_c, 78)
    inspect_mdd_period(tr_c, 80)

    # What if we add a small +3/-3 or clean integer adjustment on IS? Wait: check q14 CSCV on A=76, 78, 80!
    print("\n=== q14 & 6-th CSCV FOR V11_10_late_rfm ===")
    t_days = [d for d in sorted(all_dts) if "2021-01-04" <= d <= "2026-11-23"]
    day_idx = {d: i for i, d in enumerate(t_days)}
    for thr in [76, 78, 80]:
        sc_sub = tr_c[tr_c["score"] >= thr]["score"]
        cols = []
        q_lbls = ["base"] + [f"q{v}" for v in range(1, 14)]
        for v in range(14):
            qv = thr if v == 0 else float(np.quantile(sc_sub, 0.05 + (v / 14.0) * 0.40))
            s1, _, _ = _sim_k_slots(tr_c[tr_c["score"] >= qv], 1)
            arr = np.zeros(len(t_days))
            for r in s1.itertuples(index=False):
                i = day_idx.get(str(r.exit_date))
                if i is not None: arr[i] += float(r.net_ret_eval)
            cols.append(arr)
        Rq = np.column_stack(cols)
        print(f"  A>={thr} q14 S8={cscv_detail(Rq, q_lbls, 8)['pbo_pct']}% | S10={cscv_detail(Rq, q_lbls, 10)['pbo_pct']}%")

    # Also test what happens if we soften F11_zt_late/F04_zt60d by 1pt or check 2-factor cap, or check clean 10-item Card where F10_rfm<=20 is +3 and F08_yizi20 is -6 (so max spike >=82 doesn't overfit IS!)
    # Check strictly on IS first!
    f = fm.copy()
    f["F08_yizi20_siphon_pen"] = np.where(pool["f1_mkt20_0925_zt"].fillna(0) >= 1, -6, 0)
    f["F10_rfm_le20_pos"] = np.where(pool["real_free_mcap"].fillna(999.0) <= 20.0, 3, 0)
    f["F11_zt_late_ge1400"] = np.where((pool["zt_hhmm"] >= 1400) & (pool["zt_hhmm"] < 9999), 3, 0)
    sc2 = 70.0 + f.sum(axis=1).to_numpy()
    sc_map2 = dict(zip(zip(pool["dt"], pool["c6"]), sc2))
    tr2 = tr_base.copy()
    tr2["score"] = [sc_map2[(r.sig_date, r.c6)] for r in tr2.itertuples(index=False)]
    print("\n=== TEST GENTLER WEIGHTS (rfm+3, late+3, yizi-6) ===")
    for thr in [75, 76, 77, 78, 79, 80]:
        sf, nf, mf = _sim_k_slots(tr2[tr2["score"] >= thr], 1)
        _, ni, mi = _sim_k_slots(tr2[(tr2["score"] >= thr) & (tr2["buy_date"] <= "2024-08-31")], 1)
        _, no, mo = _sim_k_slots(tr2[(tr2["score"] >= thr) & (tr2["buy_date"] >= "2024-09-01")], 1)
        _, n25, _ = _sim_k_slots(tr2[(tr2["score"] >= thr) & (tr2["buy_date"].str[:4] == "2025")], 1)
        _, n26, _ = _sim_k_slots(tr2[(tr2["score"] >= thr) & (tr2["buy_date"].str[:4] == "2026")], 1)
        print(f"  th>={thr} | N={len(sf):3d} FULL={nf:6.2f}x MDD={mf*100:4.1f}% | IS={ni:5.2f}x(mdd={mi*100:4.1f}%) | OOS={no:5.2f}x(mdd={mo*100:4.1f}%) | 25={n25:4.2f}x 26={n26:4.2f}x")
    R2_w = build_daily_mat(tr2, [72, 74, 76, 78, 80, 82], all_dts)
    R2_l = build_daily_mat(tr2, [74, 75, 76, 77, 78, 79, 80, 81, 82], all_dts)
    print("  CSCV(72..82) S8/S10:", cscv_detail(R2_w, [72,74,76,78,80,82], 8)["pbo_pct"], cscv_detail(R2_w, [72,74,76,78,80,82], 10)["pbo_pct"])
    print("  CSCV(74..82) S8/S10:", cscv_detail(R2_l, list(range(74,83)), 8)["pbo_pct"], cscv_detail(R2_l, list(range(74,83)), 10)["pbo_pct"])


if __name__ == "__main__":
    main()
