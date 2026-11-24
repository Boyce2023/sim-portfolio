#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Step 6: Blind OOS, 2025/2026, Full CSCV PBO (S=8/10), & Exit Tree Check (+0.30% TP buffer) on IS-locked V1.1 cards."""
import itertools, os, pickle, sys
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
V1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
PART2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
sys.path.insert(0, V1_DIR)
sys.path.insert(0, PART2_DIR)
sys.path.insert(0, OUT_DIR)

from backtest_utils import _sim_k_slots
from step3_oos_and_tables import FINAL_EXIT_CFG
from step2_audit_exits_and_beta import sim_deepopen_strict_exec
from step3_diagnose_pbo_and_prune import cscv_detail, build_daily_mat
from step5_is_only_v11_design import build_candidate_cards


def main():
    aux = pickle.load(open(f"{PART2_DIR}/cache_20cm_aux.pkl", "rb"))
    all_dts = aux["all_dts"]
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")
    pool = df[df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)

    tr_base = sim_deepopen_strict_exec(pool, FINAL_EXIT_CFG, fee=0.0030, tp_buf=0.0030)
    tr_nod3 = sim_deepopen_strict_exec(pool, {**FINAL_EXIT_CFG, "b2_mode": "d2_tp"}, fee=0.0030, tp_buf=0.0030)
    tr_pt2 = sim_deepopen_strict_exec(pool, {"b3_tp_mode": "none", "b2_mode": "d2_close", "zt_imm": False, "risk_mode": "none"}, fee=0.0030, tp_buf=0.0030)

    cards = build_candidate_cards(pool)
    th_lad = [68, 70, 72, 74, 76, 78, 80, 82, 84]

    print("=== BLIND OOS & FULL CSCV PBO AUDIT (+0.30% TP BUFFER) ===")
    for cname, (sc, fm) in cards.items():
        sc_map = dict(zip(zip(pool["dt"], pool["c6"]), sc))
        tr_c = tr_base.copy()
        tr_c["score"] = [sc_map[(r.sig_date, r.c6)] for r in tr_c.itertuples(index=False)]
        R_full = build_daily_mat(tr_c, th_lad, all_dts)
        p8 = cscv_detail(R_full, th_lad, 8)
        p10 = cscv_detail(R_full, th_lad, 10)
        print(f"\n================ {cname} ({fm.shape[1]} items) ================")
        print(f"  Full CSCV(68..84) S8: PBO={p8['pbo_pct']}% omega={p8['mean_omega']} win={p8['winners']}")
        print(f"  Full CSCV(68..84) S10: PBO={p10['pbo_pct']}% omega={p10['mean_omega']} win={p10['winners']}")
        for th in [72, 74, 75, 76, 78, 80, 82]:
            sf, nvf, mddf = _sim_k_slots(tr_c[tr_c["score"] >= th], 1)
            si, nvi, _ = _sim_k_slots(tr_c[(tr_c["score"] >= th) & (tr_c["buy_date"] <= "2024-08-31")], 1)
            so, nvo, mddo = _sim_k_slots(tr_c[(tr_c["score"] >= th) & (tr_c["buy_date"] >= "2024-09-01")], 1)
            s25, nv25, _ = _sim_k_slots(tr_c[(tr_c["score"] >= th) & (tr_c["buy_date"].str[:4] == "2025")], 1)
            s26, nv26, _ = _sim_k_slots(tr_c[(tr_c["score"] >= th) & (tr_c["buy_date"].str[:4] == "2026")], 1)
            # Check NoB2D3 & PureT2 at same threshold
            tn3 = tr_nod3.copy(); tn3["score"] = tr_c["score"].values
            tpt = tr_pt2.copy(); tpt["score"] = tr_c["score"].values
            _, nvo_nd3, _ = _sim_k_slots(tn3[(tn3["score"] >= th) & (tn3["buy_date"] >= "2024-09-01")], 1)
            _, nvf_nd3, _ = _sim_k_slots(tn3[tn3["score"] >= th], 1)
            _, nvo_pt2, _ = _sim_k_slots(tpt[(tpt["score"] >= th) & (tpt["buy_date"] >= "2024-09-01")], 1)
            _, nvf_pt2, _ = _sim_k_slots(tpt[tpt["score"] >= th], 1)
            print(f"  th>={th:2d} | N={len(sf):3d}(IS={len(si):3d},OOS={len(so):2d},25={len(s25):2d},26={len(s26):2d}) | "
                  f"FULL={nvf:6.2f}x MDD={mddf*100:4.1f}% | IS={nvi:6.2f}x | OOS={nvo:5.2f}x(mdd={mddo*100:4.1f}%) | "
                  f"25={nv25:4.2f}x 26={nv26:4.2f}x || NoD3:F={nvf_nd3:5.1f}x/O={nvo_nd3:4.2f}x | PT2:F={nvf_pt2:5.1f}x/O={nvo_pt2:4.2f}x")


if __name__ == "__main__":
    main()
