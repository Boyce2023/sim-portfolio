#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Step 8a: DeepOpen V1.1 (10-item orthogonal) LOO ablation (IS & OOS), exit tree comparison (+0.30% buf), and Beta +0.30% buf stress."""
import os, pickle, sys
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
from step7_is_refine_card_and_pbo import build_refined_cards
from step3_diagnose_pbo_and_prune import cscv_detail, build_daily_mat


def sim_beta_strict_buf(paths: dict, c6: str, t0_gidx: int, rule: str, fee_rt: float = 0.0030, tp_buf: float = 0.0030):
    """Exact Beta exit engine with strict +tp_buf intraday TP penetration!"""
    st = paths.get(c6)
    if st is None: return None
    buy_pos = st["gidx_pos"].get(t0_gidx + 1)
    n_len = len(st["dt"])
    if buy_pos is None or st["vol"][buy_pos] <= 0 or st["op"][buy_pos] >= st["zt_px"][buy_pos] - 0.011:
        return None
    buy_px, buy_dt, first_sell = st["ao"][buy_pos], st["dt"][buy_pos], buy_pos + 1
    if buy_px <= 0 or np.isnan(buy_px) or first_sell >= n_len:
        return None

    def mk(j, px, why):
        return buy_dt, float(buy_px), st["dt"][j], float(px), float((px / buy_px) * (1.0 - fee_rt) - 1.0), why, int(st["gidx"][j] - (t0_gidx + 1))

    def dclose(sj, tag):
        for j in range(sj, n_len):
            if st["vol"][j] > 0 and (not st["is_dt"][j]):
                return mk(j, st["ac"][j], tag if j == sj else f"{tag}_DEF")
        return None

    if rule.startswith("FIX_T"):
        tk = int(rule.split("T")[1])
        for j in range(first_sell, n_len):
            if st["gidx"][j] >= t0_gidx + tk: return dclose(j, rule)
        return None

    d1_ao, d1_ac = st["ao"][buy_pos], st["ac"][buy_pos]
    d1_clv = (d1_ac - st["al"][buy_pos]) / max(st["ah"][buy_pos] - st["al"][buy_pos], 1e-6)
    d1_strong = (d1_ac / d1_ao - 1.0 >= 0.04 and d1_clv >= 0.65)
    zt_riding = bool(st["is_zt"][buy_pos])
    if rule == "DYN_YANG_TP15_T5":
        tp_pct, sl_pct, max_k = (0.15 if d1_strong else 0.10), 0.07, 5
    elif rule == "GRID_TP10_SL07_T3":
        tp_pct, sl_pct, max_k = 0.10, 0.07, 3
    else:
        raise ValueError(rule)

    for j in range(first_sell, n_len):
        gk = int(st["gidx"][j] - t0_gidx)
        if st["vol"][j] <= 0: continue
        o_p, h_p, l_p, c_p = st["ao"][j], st["ah"][j], st["al"][j], st["ac"][j]
        zt_adj, dt_adj = st["zt_px"][j] * st["adjf"][j], st["dt_px"][j] * st["adjf"][j]
        can_op, can_cl = st["op"][j] > st["dt_px"][j] + 0.011, (not st["is_dt"][j])
        sl_px = buy_px * (1.0 - sl_pct)
        tp_px = buy_px * (1.0 + tp_pct)
        if o_p <= sl_px and can_op: return mk(j, o_p, f"SL_OPEN_T{gk}")
        if (not zt_riding) and o_p >= tp_px and can_op: return mk(j, o_p, f"TP_OPEN_T{gk}")
        if l_p <= sl_px and sl_px >= dt_adj - 1e-4 and can_cl: return mk(j, sl_px, f"SL_HIT_T{gk}")
        if l_p <= sl_px and not can_cl: return dclose(j, f"SL_DTDEF_T{gk}")
        need_h = min(tp_px * (1.0 + tp_buf), zt_adj + 1e-4)
        if (not zt_riding) and h_p >= need_h and tp_px <= zt_adj + 1e-4: return mk(j, tp_px, f"TP_HIT_T{gk}")
        if zt_riding:
            if st["is_zt"][j]: continue
            return dclose(j, f"ZT_BREAK_T{gk}")
        if gk >= max_k: return dclose(j, f"TIME_T{gk}")
    return None


def main():
    aux = pickle.load(open(f"{PART2_DIR}/cache_20cm_aux.pkl", "rb"))
    all_dts = aux["all_dts"]
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")
    pool = df[df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    cards = build_refined_cards(pool)
    sc, fm = cards["V11_10_late_rfm"]
    sc_map = dict(zip(zip(pool["dt"], pool["c6"]), sc))

    # 1. Exit Tree variants on V11_10_late_rfm at th>=78 (+0.30% TP buffer)
    print("=== EXIT TREE VARIANTS ON V11_10_late_rfm (th>=78, +0.30% TP BUFFER) ===")
    ex_variants = [
        ("V1_Full_Tree", FINAL_EXIT_CFG),
        ("NoB2D3_OnlyD2TP12", {**FINAL_EXIT_CFG, "b2_mode": "d2_tp"}),
        ("NoRisk_V1Tree", {**FINAL_EXIT_CFG, "risk_mode": "none"}),
        ("NoZTImm_V1Tree", {**FINAL_EXIT_CFG, "zt_imm": False}),
        ("FixedB3TP10_NoB2D3", {**FINAL_EXIT_CFG, "b2_mode": "d2_tp", "b3_tp_mode": "fixed", "b3_tp": 0.10}),
        ("PureT2_Close", {"b3_tp_mode": "none", "b2_mode": "d2_close", "zt_imm": False, "risk_mode": "none"}),
    ]
    for enm, ecfg in ex_variants:
        tr = sim_deepopen_strict_exec(pool, ecfg, fee=0.0030, tp_buf=0.0030)
        tr["score"] = [sc_map[(r.sig_date, r.c6)] for r in tr.itertuples(index=False)]
        sub = tr[tr["score"] >= 78.0]
        sf, nf, mddf = _sim_k_slots(sub, 1)
        _, ni, _ = _sim_k_slots(sub[sub["buy_date"] <= "2024-08-31"], 1)
        _, no, mddo = _sim_k_slots(sub[sub["buy_date"] >= "2024-09-01"], 1)
        _, n25, _ = _sim_k_slots(sub[sub["buy_date"].str[:4] == "2025"], 1)
        _, n26, _ = _sim_k_slots(sub[sub["buy_date"].str[:4] == "2026"], 1)
        print(f"  {enm:20s} | N={len(sf):3d} FULL={nf:6.2f}x MDD={mddf*100:4.1f}% | IS={ni:5.2f}x | OOS={no:5.2f}x(MDD={mddo*100:4.1f}%) | 25={n25:4.2f}x 26={n26:4.2f}x")

    # 2. LOO Ablation on V11_10_late_rfm at th>=78 (IS & OOS & FULL, +0.30% buf)
    tr0 = sim_deepopen_strict_exec(pool, FINAL_EXIT_CFG, fee=0.0030, tp_buf=0.0030)
    tr0["score"] = [sc_map[(r.sig_date, r.c6)] for r in tr0.itertuples(index=False)]
    fm_map = {col: dict(zip(zip(pool["dt"], pool["c6"]), fm[col].to_numpy())) for col in fm.columns}
    _, b_is, _ = _sim_k_slots(tr0[(tr0["score"] >= 78) & (tr0["buy_date"] <= "2024-08-31")], 1)
    _, b_oo, _ = _sim_k_slots(tr0[(tr0["score"] >= 78) & (tr0["buy_date"] >= "2024-09-01")], 1)
    _, b_fl, _ = _sim_k_slots(tr0[tr0["score"] >= 78], 1)
    print(f"\n=== V11_10_late_rfm LOO ABLATION at th>=78 (Base: IS={b_is:.2f}x, OOS={b_oo:.2f}x, FULL={b_fl:.2f}x) ===")
    for col in fm.columns:
        td = tr0.copy()
        td["score"] = td["score"] - np.array([fm_map[col][(r.sig_date, r.c6)] for r in td.itertuples(index=False)])
        _, di, _ = _sim_k_slots(td[(td["score"] >= 78) & (td["buy_date"] <= "2024-08-31")], 1)
        _, do, _ = _sim_k_slots(td[(td["score"] >= 78) & (td["buy_date"] >= "2024-09-01")], 1)
        _, df_, _ = _sim_k_slots(td[td["score"] >= 78], 1)
        print(f"  Keep {col:24s} | d_IS={b_is-di:+6.2f}x | d_OOS={b_oo-do:+5.2f}x | d_FULL={b_fl-df_:+7.2f}x")

    # 3. Beta V1.0 Execution Friction Test (+0.30% TP buffer!)
    b_sig = pd.read_csv(f"{B1_DIR}/all_scored_signals_beta_v1.csv")
    b_sig["c6"] = b_sig["c6"].astype(str).str.zfill(6)
    b_A = b_sig[b_sig["pass_A"]].copy()
    pk = pickle.load(open(f"{B1_DIR}/v1_stock_paths.pkl", "rb"))
    paths, dt_to_gidx = pk["paths"], pk["dt_to_gidx"]
    print("\n=== BETA V1.0 EXECUTION BUFFER STRESS (+0.30% TP BUFFER) ===")
    for ex_r in ["DYN_YANG_TP15_T5", "GRID_TP10_SL07_T3", "FIX_T3", "FIX_T2"]:
        for buf in [0.0, 0.0030]:
            if ex_r.startswith("FIX_") and buf > 0: continue
            trows = []
            for r in b_A.itertuples(index=False):
                res = sim_beta_strict_buf(paths, r.c6, dt_to_gidx[r.dt], ex_r, fee_rt=0.0030, tp_buf=buf)
                if res:
                    trows.append({"signal_dt": r.dt, "buy_dt": res[0], "sell_dt": res[2], "c6": r.c6, "circ_mcap": r.circ_mcap, "score": r.score_v1, "net_ret": res[4]})
            tdf = pd.DataFrame(trows)
            from v1_exit_engine import _sim_k_slots_v1
            _, n1f, m1f, _ = _sim_k_slots_v1(tdf, 1)
            _, n1o, _, _ = _sim_k_slots_v1(tdf[tdf["buy_dt"] >= "2024-09-01"], 1)
            _, n1ox, _, _ = _sim_k_slots_v1(tdf[(tdf["buy_dt"] >= "2024-09-01") & (~tdf["signal_dt"].between("2024-09-24", "2024-10-08"))], 1)
            _, n1_26, _, _ = _sim_k_slots_v1(tdf[tdf["buy_dt"] >= "2026-01-01"], 1)
            _, n3ox, _, _ = _sim_k_slots_v1(tdf[(tdf["buy_dt"] >= "2024-09-01") & (~tdf["signal_dt"].between("2024-09-24", "2024-10-08"))], 3)
            _, n3_26, _, _ = _sim_k_slots_v1(tdf[tdf["buy_dt"] >= "2026-01-01"], 3)
            print(f"  {ex_r:17s} buf={buf*100:.2f}% | 1s: FULL={n1f:.2f}x MDD={m1f*100:5.1f}% OOS={n1o:.2f}x OOSx={n1ox:.2f}x Y26={n1_26:.2f}x | 3s: OOSx={n3ox:.2f}x Y26={n3_26:.2f}x")


if __name__ == "__main__":
    main()
