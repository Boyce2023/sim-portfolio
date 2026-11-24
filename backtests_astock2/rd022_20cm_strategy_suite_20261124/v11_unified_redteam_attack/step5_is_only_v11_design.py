#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Step 5: Strict IS-ONLY (<=2024-08-31) V1.1 Factor Selection, Balanced Integer Weights, Internal IS-CSCV PBO, & Exit Tree Check (+0.30% buffer)."""
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


def is_cscv_pbo(tr_all: pd.DataFrame, th_list: list, is_dts: list, ng: int = 8) -> dict:
    day_idx = {d: i for i, d in enumerate(is_dts)}
    cols = []
    for th in th_list:
        s1, _, _ = _sim_k_slots(tr_all[tr_all["score"] >= th], 1)
        arr = np.zeros(len(is_dts), dtype=float)
        for r in s1.itertuples(index=False):
            i = day_idx.get(str(r.exit_date))
            if i is not None: arr[i] += float(r.net_ret_eval)
        cols.append(arr)
    R = np.column_stack(cols)
    gs = len(R) // ng
    gidx = [list(range(i * gs, (i + 1) * gs if i < ng - 1 else len(R))) for i in range(ng)]
    omegas = []
    for te in itertools.combinations(range(ng), ng // 2):
        trg = [k for k in range(ng) if k not in te]
        tri = [x for k in trg for x in gidx[k]]
        tei = [x for k in te for x in gidx[k]]
        rt, re_ = R[tri], R[tei]
        sd_t, sd_e = rt.std(0, ddof=1), re_.std(0, ddof=1)
        st = np.divide(rt.mean(0), sd_t, out=np.zeros_like(sd_t), where=sd_t > 1e-12)
        se = np.divide(re_.mean(0), sd_e, out=np.zeros_like(sd_e), where=sd_e > 1e-12)
        b = int(np.argmax(st))
        omegas.append(float(np.mean(se > se[b])))
    return {"pbo": round(float(np.mean(np.array(omegas) > 0.50) * 100), 1), "omega": round(float(np.mean(omegas)), 3)}


def build_candidate_cards(d: pd.DataFrame) -> dict[str, tuple[np.ndarray, pd.DataFrame]]:
    """
    Construct multiple clean, drift-free 8-11 item integer scorecards (Base=70).
    All factors are pure price/volume/LHB/market-breadth/calendar (NO scraper drift, NO KPL Elo drift, NO static mcap>40B penalty).
    """
    cards = {}
    # Card A: 9-item Balanced Core (weights +-4 to +-10; NO extreme spikes)
    fA = pd.DataFrame(index=d.index)
    fA["F01_open_gap"] = np.where(d["f1_o_pct"] < -0.080, -10, np.where(d["f1_o_pct"].between(-0.070, -0.030), 4, 0))
    fA["F02_bias20_le20"] = np.where(d["bias20"].fillna(1.0) <= 0.20, 4, 0)
    fA["F03_dist3d30_ge10"] = np.where(d["dist_3d30"].fillna(0.0) >= 0.10, 4, 0)
    fA["F04_zt60d_ge2"] = np.where(d["zt_cnt_60d"].fillna(0) >= 2, 5, 0)
    fA["F05_seal_ratio_ge10_pen"] = np.where(d["zt_seal_ratio"].fillna(0.0) >= 0.10, -5, 0)
    fA["F06_inst_net_pos"] = np.where(d["lhb_inst_net"].fillna(0.0) > 0.0, 5, 0)
    fA["F07_mkt10_zt_gt55"] = np.where(d["mkt10_zt_cnt"].fillna(0) > 70, 7, np.where(d["mkt10_zt_cnt"].fillna(0) > 55, 4, 0))
    fA["F08_yizi20_siphon_pen"] = np.where(d["f1_mkt20_0925_zt"].fillna(0) >= 1, -5, 0)
    fA["F09_monday_pen"] = np.where(d["f1_weekday"] == 0, -8, 0)
    cards["CardA_9_Bal"] = (70.0 + fA.sum(axis=1).to_numpy(), fA)

    # Card B: 10-item (+zt_hhmm_late>=1400 vs <=945, or +rfm<=20B only no >40B pen)
    fB = fA.copy()
    fB["F10_rfm_le20_pos"] = np.where(d["real_free_mcap"].fillna(999.0) <= 20.0, 4, 0)
    cards["CardB_10_rfm20"] = (70.0 + fB.sum(axis=1).to_numpy(), fB)

    # Card C: 10-item (+zt_hhmm >= 14:00 divergence strength +5, keep bias20<=20)
    fC = fA.copy()
    fC["F10_zt_late_ge1400"] = np.where((d["zt_hhmm"] >= 1400) & (d["zt_hhmm"] < 9999), 5, 0)
    cards["CardC_10_late"] = (70.0 + fC.sum(axis=1).to_numpy(), fC)

    # Card D: 10-item (+rfm<=20B & +quant_noinst_pen -4)
    fD = fA.copy()
    fD["F10_rfm_le20_pos"] = np.where(d["real_free_mcap"].fillna(999.0) <= 20.0, 3, 0)
    fD["F11_quant_noinst_pen"] = np.where((d["lhb_quant"].fillna(0) >= 1) & (d["lhb_inst_net"].fillna(0.0) <= 0.0), -4, 0)
    cards["CardD_11_quant"] = (70.0 + fD.sum(axis=1).to_numpy(), fD)

    # Card E: Ultra-simple 8-item (no bias20, just pure physical & capital & sentiment & calendar)
    fE = fA.drop(columns=["F02_bias20_le20"]).copy()
    cards["CardE_8_Ultra"] = (70.0 + fE.sum(axis=1).to_numpy(), fE)

    return cards


def main():
    aux = pickle.load(open(f"{PART2_DIR}/cache_20cm_aux.pkl", "rb"))
    is_dts = [d for d in sorted(aux["all_dts"]) if "2021-01-04" <= d <= "2024-08-31"]
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")
    is_pool = df[(df["f1_dt"] <= "2024-08-31") & df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)

    # Pre-simulate exit returns on IS pool with STRICT +0.30% TP buffer
    tr_base = sim_deepopen_strict_exec(is_pool, FINAL_EXIT_CFG, fee=0.0030, tp_buf=0.0030)
    tr_nod3 = sim_deepopen_strict_exec(is_pool, {**FINAL_EXIT_CFG, "b2_mode": "d2_tp"}, fee=0.0030, tp_buf=0.0030)
    tr_pt2 = sim_deepopen_strict_exec(is_pool, {"b3_tp_mode": "none", "b2_mode": "d2_close", "zt_imm": False, "risk_mode": "none"}, fee=0.0030, tp_buf=0.0030)

    cards = build_candidate_cards(is_pool)
    th_lad = [68, 70, 72, 74, 76, 78, 80, 82]

    print("=== STRICT IS-ONLY EVALUATION (2021-01-04 ~ 2024-08-31, +0.30% TP BUFFER) ===")
    for cname, (sc, fm) in cards.items():
        sc_map = dict(zip(zip(is_pool["dt"], is_pool["c6"]), sc))
        tr_c = tr_base.copy()
        tr_c["score"] = [sc_map[(r.sig_date, r.c6)] for r in tr_c.itertuples(index=False)]
        pbo_is = is_cscv_pbo(tr_c, th_lad, is_dts, ng=8)
        print(f"\n--- {cname} ({fm.shape[1]} items) | IS-only CSCV(S8, 68..82) PBO={pbo_is['pbo']}% omega={pbo_is['omega']} ---")
        for th in [70, 72, 74, 75, 76, 78, 80, 82, 84]:
            s1, nv, mdd = _sim_k_slots(tr_c[tr_c["score"] >= th], 1)
            r = s1["net_ret_eval"].to_numpy()
            yrs = {y: round(float(_sim_k_slots(tr_c[(tr_c["score"] >= th) & (tr_c["buy_date"].str[:4] == y)], 1)[1]), 2) for y in ["2021", "2022", "2023", "2024"]}
            wr = round(float((r > 0).mean() * 100), 1) if len(r) else 0.0
            print(f"  th>={th:2d} | N={len(s1):3d} WR={wr:4.1f}% IS={nv:6.2f}x MDD={mdd*100:4.1f}% | yrs={yrs}")

    # Also test IS Exit Tree comparison on CardA_9_Bal th>=74 and th>=76 (+0.30% buf)
    print("\n=== IS EXIT TREE COMPARISON ON CardA_9_Bal (th>=74 & th>=76, +0.30% buf) ===")
    scA, _ = cards["CardA_9_Bal"]
    for th in [74, 76]:
        print(f"  [th >= {th}]")
        for ename, tr_e in [("V1_Tree_buf0.30", tr_base), ("NoB2D3_buf0.30", tr_nod3), ("PureT2_Close", tr_pt2)]:
            sc_mapA = dict(zip(zip(is_pool["dt"], is_pool["c6"]), scA))
            t_sub = tr_e.copy()
            t_sub["score"] = [sc_mapA[(r.sig_date, r.c6)] for r in t_sub.itertuples(index=False)]
            s1, nv, mdd = _sim_k_slots(t_sub[t_sub["score"] >= th], 1)
            print(f"    {ename:16s} | N={len(s1):3d} WR={(s1['net_ret_eval']>0).mean()*100:4.1f}% IS={nv:6.2f}x MDD={mdd*100:4.1f}%")


if __name__ == "__main__":
    main()
