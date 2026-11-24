#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Step 11: Full Red-Team Stress Battle across 4 Clean V1.1 Finalists (+0.30% TP buffer, ex5/ex10, 0.5/0.8% fee, amt>=2e8/3e8, cap10m, PBO, MC, V19.1)."""
import os, pickle, sys
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
V1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
PART2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
V191_PATH = f"{BASE}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_combined_5strat_v191_slot1_clean.csv"
sys.path.insert(0, V1_DIR); sys.path.insert(0, PART2_DIR); sys.path.insert(0, OUT_DIR)

from backtest_utils import _sim_k_slots
from step3_oos_and_tables import FINAL_EXIT_CFG, calc_cap10m_nav
from step2_audit_exits_and_beta import sim_deepopen_strict_exec
from step10b_solve_pbo_spike import full_cscv_suite


def main():
    aux = pickle.load(open(f"{PART2_DIR}/cache_20cm_aux.pkl", "rb"))
    all_dts = aux["all_dts"]
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")
    pool = df[df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    deep_cfg = {**FINAL_EXIT_CFG, "zt_imm": False}
    tr030 = sim_deepopen_strict_exec(pool, deep_cfg, fee=0.0030, tp_buf=0.0030)
    tr050 = sim_deepopen_strict_exec(pool, deep_cfg, fee=0.0050, tp_buf=0.0030)
    tr080 = sim_deepopen_strict_exec(pool, deep_cfg, fee=0.0080, tp_buf=0.0030)

    def base8():
        f = pd.DataFrame(index=pool.index)
        f["F01_open_gap"] = np.where(pool["f1_o_pct"] < -0.080, -10, np.where(pool["f1_o_pct"].between(-0.070, -0.030), 4, 0))
        f["F02_dist3d30_ge10"] = np.where(pool["dist_3d30"].fillna(0.0) >= 0.10, 4, 0)
        f["F03_zt60d_ge2"] = np.where(pool["zt_cnt_60d"].fillna(0) >= 2, 5, 0)
        f["F04_seal_ratio_ge10_pen"] = np.where(pool["zt_seal_ratio"].fillna(0.0) >= 0.10, -5, 0)
        f["F05_inst_net_pos"] = np.where(pool["lhb_inst_net"].fillna(0.0) > 0.0, 5, 0)
        f["F06_mkt10_zt_gt55"] = np.where(pool["mkt10_zt_cnt"].fillna(0) > 70, 7, np.where(pool["mkt10_zt_cnt"].fillna(0) > 55, 4, 0))
        f["F07_yizi20_siphon_pen"] = np.where(pool["f1_mkt20_0925_zt"].fillna(0) >= 1, -5, 0)
        f["F08_monday_pen"] = np.where(pool["f1_weekday"] == 0, -8, 0)
        return f

    f1 = base8(); f1["F09_zt_late"] = np.where((pool["zt_hhmm"] >= 1400) & (pool["zt_hhmm"] < 9999), 4, 0)
    f2 = f1.copy(); f2["F10_bias20_le20"] = np.where(pool["bias20"].fillna(1.0) <= 0.20, 4, 0)
    f4 = base8(); f4["F09_rfm_le20"] = np.where(pool["real_free_mcap"].fillna(999.0) <= 20.0, 4, 0)
    f6 = base8(); f6["F09_rfm_le25"] = np.where(pool["real_free_mcap"].fillna(999.0) <= 25.0, 3, 0); f6["F10_bias20_le20"] = np.where(pool["bias20"].fillna(1.0) <= 0.20, 3, 0)

    v191 = pd.read_csv(V191_PATH)
    v191["code"] = v191["code"].astype(str).str.zfill(6)
    v191_ints = [((r.buy_date, int(r.buy_hhmm)), (r.exit_date, int(r.exit_hhmm))) for r in v191.itertuples(index=False)]
    v191_cols = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "priority", "score", "net_ret"]
    rng = np.random.default_rng(20261124)

    for cnm, fm, thr in [
        ("Cand1_Pure9_NoMcap_76", f1, 76),
        ("Cand2_10_Bias20_76", f2, 76),
        ("Cand4_9_Rfm20_76", f4, 76),
        ("Cand6_10_Rfm25Bias_76", f6, 76),
        ("Cand6_10_Rfm25Bias_78", f6, 78),
    ]:
        sc = 70.0 + fm.sum(axis=1).to_numpy()
        sc_map = dict(zip(zip(pool["dt"], pool["c6"]), sc))
        t030 = tr030.copy(); t030["score"] = [sc_map[(r.sig_date, r.c6)] for r in t030.itertuples(index=False)]
        t050 = tr050.copy(); t050["score"] = [sc_map[(r.sig_date, r.c6)] for r in t050.itertuples(index=False)]
        t080 = tr080.copy(); t080["score"] = [sc_map[(r.sig_date, r.c6)] for r in t080.itertuples(index=False)]

        sub = t030[t030["score"] >= thr]
        s1, nv_f, mdd_f = _sim_k_slots(sub, 1)
        _, nv_3, mdd_3 = _sim_k_slots(sub, 3)
        _, nv_is, _ = _sim_k_slots(sub[sub["buy_date"] <= "2024-08-31"], 1)
        _, nv_oo, mdd_oo = _sim_k_slots(sub[sub["buy_date"] >= "2024-09-01"], 1)
        s25, nv_25, _ = _sim_k_slots(sub[sub["buy_date"].str[:4] == "2025"], 1)
        s26, nv_26, _ = _sim_k_slots(sub[sub["buy_date"].str[:4] == "2026"], 1)
        r1 = s1["net_ret_eval"].to_numpy()
        ex5 = float(np.prod(1.0 + np.sort(r1)[:-5])) if len(r1) > 5 else 1.0
        ex10 = float(np.prod(1.0 + np.sort(r1)[:-10])) if len(r1) > 10 else 1.0
        cap10m = calc_cap10m_nav(r1)
        _, nv_f50, _ = _sim_k_slots(t050[t050["score"] >= thr], 1)
        _, nv_f80, _ = _sim_k_slots(t080[t080["score"] >= thr], 1)
        _, nv_a2, _ = _sim_k_slots(sub[sub["amount"] >= 2e8], 1)
        _, nv_a3, mdd_a3 = _sim_k_slots(sub[sub["amount"] >= 3e8], 1)
        _, nv_a3_oo, _ = _sim_k_slots(sub[(sub["amount"] >= 3e8) & (sub["buy_date"] >= "2024-09-01")], 1)
        pb = full_cscv_suite(t030, thr, all_dts)

        # Weight MC 100x
        fm_arr = np.column_stack([[fm[c].to_numpy()[pool.index[pool["dt"].eq(r.sig_date) & pool["c6"].eq(r.c6)][0]] for r in t030.itertuples(index=False)] for c in fm.columns])
        mc_o, mc_f = [], []
        for _ in range(100):
            scp = 70.0 + fm_arr @ rng.uniform(0.80, 1.20, size=fm.shape[1])
            sp = t030[scp >= thr]
            mc_f.append(_sim_k_slots(sp, 1)[1])
            mc_o.append(_sim_k_slots(sp[sp["buy_date"] >= "2024-09-01"], 1)[1])

        # V19.1 strict228 empty-slot test
        s20 = sub[(sub["buy_date"] >= "2021-11-15") & (sub["buy_date"] <= "2026-11-16")].copy()
        s20["code"] = s20["c6"].astype(str).str.zfill(6)
        s20["buy_hhmm"] = 925
        s20["exit_hhmm"] = np.where(s20["exit_reason"].str.contains("open|gap|tp"), 1030, 1500)
        s20["strategy"] = "20cm_V11"; s20["priority"] = 6; s20["name"] = s20["code"]
        s20 = s20.sort_values(["buy_date", "score", "code"], ascending=[True, False, True])
        acc, occ = [], list(v191_ints)
        for rw in s20[v191_cols].itertuples(index=False):
            st_i, en_i = (rw.buy_date, int(rw.buy_hhmm)), (rw.exit_date, int(rw.exit_hhmm))
            if all((en_i < os_) or (st_i > oe_) for os_, oe_ in occ):
                acc.append(rw._asdict()); occ.append((st_i, en_i))
        cmb = pd.concat([v191[v191_cols], pd.DataFrame(acc, columns=v191_cols)], ignore_index=True).sort_values(["buy_date", "buy_hhmm", "exit_date"])
        cap_v191_base = calc_cap10m_nav(v191["net_ret"].to_numpy())
        cap_v191_cmb = calc_cap10m_nav(cmb["net_ret"].to_numpy())
        r_acc = np.array([x["net_ret"] for x in acc]) if acc else np.array([])

        print(f"\n=== {cnm} ===")
        print(f"  1s: N={len(s1):3d} WR={(r1>0).mean()*100:4.1f}% FULL={nv_f:6.1f}x MDD={mdd_f*100:4.1f}% cap10m={cap10m:5.1f}x | 3s={nv_3:5.1f}x(MDD={mdd_3*100:4.1f}%)")
        print(f"  IS={nv_is:5.1f}x | OOS={nv_oo:5.2f}x(MDD={mdd_oo*100:4.1f}%) | 25(n={len(s25):2d})={nv_25:4.2f}x | 26(n={len(s26):2d})={nv_26:4.2f}x")
        print(f"  Stress: ex5={ex5:5.1f}x ex10={ex10:5.1f}x | f50={nv_f50:5.1f}x f80={nv_f80:5.1f}x | amt>=2e8={nv_a2:5.1f}x amt>=3e8={nv_a3:5.1f}x(m={mdd_a3*100:4.1f}%,OOS={nv_a3_oo:4.2f}x)")
        print(f"  PBO: w8/10={pb['wide_S8']:4.1f}/{pb['wide_S10']:4.1f}% loc={pb['loc_S8']:4.1f}/{pb['loc_S10']:4.1f}% q14={pb['q14_S8']:4.1f}/{pb['q14_S10']:4.1f}% | MC_P10: full={np.percentile(mc_f,10):5.1f}x oos={np.percentile(mc_o,10):4.2f}x")
        print(f"  V19.1(strict228): +{len(acc)} trades (WR={(r_acc>0).mean()*100 if len(r_acc) else 0:.1f}%, mn={r_acc.mean()*100 if len(r_acc) else 0:+.2f}%) | cap10m: {cap_v191_base:.2f}x -> {cap_v191_cmb:.2f}x")


if __name__ == "__main__":
    main()
