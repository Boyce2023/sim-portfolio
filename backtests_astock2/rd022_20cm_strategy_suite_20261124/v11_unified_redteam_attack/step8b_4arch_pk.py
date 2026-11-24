#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Step 8b: Head-to-head PK of 4 Unified V1.1 Architectures across 1-slot, 2-slot, 3-slot, and 1M->10M Cap (+0.30% TP buffer)."""
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

from step3_oos_and_tables import FINAL_EXIT_CFG
from step2_audit_exits_and_beta import sim_deepopen_strict_exec
from step7_is_refine_card_and_pbo import build_refined_cards
from step8a_deepopen_v11_exit_and_loo import sim_beta_strict_buf


def sim_portfolio_k_slots(trades: pd.DataFrame, k_slots: int, priority_deep: bool = True, empty_only_beta: bool = False) -> dict:
    """
    Exact k-slot simulation across combined DeepOpen + Beta streams.
    Each trade has: buy_date, exit_date, track ('DEEP' or 'BETA'), score, c6, net_ret.
    If empty_only_beta=True: Beta trades are ONLY entered when ALL k_slots are idle AND no DEEP signal on that buy_date.
    """
    if trades.empty:
        return {"n": 0, "nav": 1.0, "mdd": 0.0, "calmar": 0.0, "cap10m": 1.0, "wr": 0.0}
    srt = trades.copy()
    srt["trk_pri"] = np.where(srt["track"] == "DEEP", 0, 1) if priority_deep else 0
    srt = srt.sort_values(["buy_date", "trk_pri", "score", "c6"], ascending=[True, True, False, True]).reset_index(drop=True)

    free_dts = [""] * k_slots
    slot_eq = [1.0 / k_slots] * k_slots
    slot_cap = [100.0 / k_slots] * k_slots  # 100w total -> 1000w cap
    taken = []
    # Build daily mark-on-exit equity curve
    for bdt, grp in srt.groupby("buy_date", sort=True):
        avail = [i for i in range(k_slots) if free_dts[i] == "" or bdt > free_dts[i]]
        if not avail:
            continue
        has_deep_today = bool((grp["track"] == "DEEP").any())
        for _, row in grp.iterrows():
            if not avail:
                break
            if empty_only_beta and row["track"] == "BETA":
                # Only enter Beta if ALL k_slots are free AND no DeepOpen today
                if len(avail) < k_slots or has_deep_today:
                    continue
            si = avail.pop(0)
            r = float(row["net_ret"])
            slot_eq[si] *= (1.0 + r)
            bet = min(slot_cap[si], 1000.0 / k_slots)
            slot_cap[si] += bet * r
            free_dts[si] = str(row["exit_date"])
            d = row.to_dict()
            d["slot_id"] = si
            taken.append(d)

    if not taken:
        return {"n": 0, "nav": 1.0, "mdd": 0.0, "calmar": 0.0, "cap10m": 1.0, "wr": 0.0}
    tdf = pd.DataFrame(taken).sort_values(["exit_date", "buy_date"]).reset_index(drop=True)
    # Exact realized portfolio curve on exit dates
    s_cur = [1.0 / k_slots] * k_slots
    nav_arr = [1.0]
    for r_row in tdf.itertuples(index=False):
        s_cur[int(r_row.slot_id)] *= (1.0 + float(r_row.net_ret))
        nav_arr.append(sum(s_cur))
    arr = np.array(nav_arr, dtype=float)
    nav = float(arr[-1])
    pk = np.maximum.accumulate(arr)
    mdd = float(np.max((pk - arr) / pk) * 100.0)
    years = 5.88
    cagr = (nav ** (1.0 / years) - 1.0) * 100.0 if nav > 0 else -100.0
    calmar = cagr / mdd if mdd > 0.1 else 99.0
    cap10m = sum(slot_cap) / 100.0
    r_all = tdf["net_ret"].to_numpy()
    return {
        "n": int(len(tdf)), "n_deep": int((tdf["track"] == "DEEP").sum()), "n_beta": int((tdf["track"] == "BETA").sum()),
        "wr": round(float((r_all > 0).mean() * 100), 1),
        "nav": round(nav, 2), "mdd": round(mdd, 1), "calmar": round(calmar, 2), "cap10m": round(cap10m, 2), "tdf": tdf,
    }


def window_summary(tr_all: pd.DataFrame, k_slots: int, priority_deep: bool, empty_only_beta: bool) -> dict:
    # Note: to avoid compounding truncation bias, run continuous full simulation, then also standalone window sims
    full = sim_portfolio_k_slots(tr_all, k_slots, priority_deep, empty_only_beta)
    is_ = sim_portfolio_k_slots(tr_all[tr_all["buy_date"] <= "2024-08-31"], k_slots, priority_deep, empty_only_beta)
    oos = sim_portfolio_k_slots(tr_all[tr_all["buy_date"] >= "2024-09-01"], k_slots, priority_deep, empty_only_beta)
    oox = sim_portfolio_k_slots(tr_all[(tr_all["buy_date"] >= "2024-09-01") & (~tr_all["sig_date"].between("2024-09-24", "2024-10-08"))], k_slots, priority_deep, empty_only_beta)
    y25 = sim_portfolio_k_slots(tr_all[tr_all["buy_date"].str[:4] == "2025"], k_slots, priority_deep, empty_only_beta)
    y26 = sim_portfolio_k_slots(tr_all[tr_all["buy_date"].str[:4] == "2026"], k_slots, priority_deep, empty_only_beta)
    return {"FULL": full, "IS": is_, "OOS": oos, "OOSx": oox, "Y25": y25, "Y26": y26}


def build_beta_df(b_sig: pd.DataFrame, paths: dict, dt_to_gidx: dict, ex_rule: str) -> pd.DataFrame:
    rows = []
    for r in b_sig.itertuples(index=False):
        res = sim_beta_strict_buf(paths, r.c6, dt_to_gidx[r.dt], ex_rule, fee_rt=0.0030, tp_buf=0.0030)
        if res:
            rows.append({
                "sig_date": r.dt, "buy_date": res[0], "exit_date": res[2],
                "c6": r.c6, "score": float(r.score_v1), "net_ret": res[4], "track": "BETA",
            })
    return pd.DataFrame(rows)


def main():
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")
    pool = df[df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    cards = build_refined_cards(pool)
    sc, _ = cards["V11_10_late_rfm"]
    sc_map = dict(zip(zip(pool["dt"], pool["c6"]), sc))
    deep_cfg = {**FINAL_EXIT_CFG, "zt_imm": False}  # pruned redundant zt_imm
    tr_deep_all = sim_deepopen_strict_exec(pool, deep_cfg, fee=0.0030, tp_buf=0.0030)
    tr_deep_all["score"] = [sc_map[(r.sig_date, r.c6)] for r in tr_deep_all.itertuples(index=False)]
    tr_deep_all["track"] = "DEEP"

    b_sig = pd.read_csv(f"{B1_DIR}/all_scored_signals_beta_v1.csv")
    b_sig["c6"] = b_sig["c6"].astype(str).str.zfill(6)
    pk = pickle.load(open(f"{B1_DIR}/v1_stock_paths.pkl", "rb"))
    paths, dt_to_gidx = pk["paths"], pk["dt_to_gidx"]

    b_A_T5 = build_beta_df(b_sig[b_sig["pass_A"]], paths, dt_to_gidx, "DYN_YANG_TP15_T5")
    b_A_T3 = build_beta_df(b_sig[b_sig["pass_A"]], paths, dt_to_gidx, "GRID_TP10_SL07_T3")
    b_A_F3 = build_beta_df(b_sig[b_sig["pass_A"]], paths, dt_to_gidx, "FIX_T3")
    b_A_F2 = build_beta_df(b_sig[b_sig["pass_A"]], paths, dt_to_gidx, "FIX_T2")
    b_S_T5 = build_beta_df(b_sig[b_sig["pass_S"]], paths, dt_to_gidx, "DYN_YANG_TP15_T5")
    b_m_T5 = build_beta_df(b_sig[b_sig["pass_A"] & (b_sig["mkt_prev5d_ew"] >= -0.02)], paths, dt_to_gidx, "DYN_YANG_TP15_T5")

    cols_u = ["sig_date", "buy_date", "exit_date", "c6", "score", "net_ret", "track"]
    for deep_th in [78.0, 80.0]:
        d_sub = tr_deep_all[tr_deep_all["score"] >= deep_th][cols_u].copy()
        archs = [
            (f"Arch1_PureDeep_{int(deep_th)}", d_sub, True, False),
            (f"Arch2_UniFull_T5", pd.concat([d_sub, b_A_T5[cols_u]], ignore_index=True), True, False),
            (f"Arch3a_FastBeta_TP10T3", pd.concat([d_sub, b_A_T3[cols_u]], ignore_index=True), True, False),
            (f"Arch3b_FastBeta_FixT3", pd.concat([d_sub, b_A_F3[cols_u]], ignore_index=True), True, False),
            (f"Arch3c_FastBeta_FixT2", pd.concat([d_sub, b_A_F2[cols_u]], ignore_index=True), True, False),
            (f"Arch4a_PriEmpty_BetaA", pd.concat([d_sub, b_A_T5[cols_u]], ignore_index=True), True, True),
            (f"Arch4b_PriEmpty_BetaS", pd.concat([d_sub, b_S_T5[cols_u]], ignore_index=True), True, True),
            (f"Arch4c_PriEmpty_MktPos", pd.concat([d_sub, b_m_T5[cols_u]], ignore_index=True), True, True),
        ]
        print(f"\n==================== 4-ARCHITECTURE PK (DeepOpen th>={int(deep_th)}, +0.30% TP BUFFER) ====================")
        pk_rows = []
        for k_slots in [1, 2, 3]:
            print(f"\n--- [{k_slots}-SLOT] ---")
            for aname, adf, pri, emp in archs:
                w = window_summary(adf, k_slots, pri, emp)
                f, i, o, ox, y5, y6 = w["FULL"], w["IS"], w["OOS"], w["OOSx"], w["Y25"], w["Y26"]
                print(f"  {aname:23s} | N={f['n']:3d}(D={f['n_deep']:3d},B={f['n_beta']:2d}) WR={f['wr']:4.1f}% | "
                      f"FULL={f['nav']:6.2f}x MDD={f['mdd']:4.1f}% Cal={f['calmar']:4.2f} cap10m={f['cap10m']:5.2f}x | "
                      f"IS={i['nav']:5.2f}x | OOS={o['nav']:5.2f}x OOSx={ox['nav']:5.2f}x | 25={y5['nav']:4.2f}x 26={y6['nav']:4.2f}x")
                pk_rows.append({
                    "deep_th": int(deep_th), "k_slots": k_slots, "arch": aname,
                    "N": f["n"], "N_deep": f["n_deep"], "N_beta": f["n_beta"], "WR": f["wr"],
                    "FULL_nav": f["nav"], "FULL_mdd": f["mdd"], "Calmar": f["calmar"], "cap10m": f["cap10m"],
                    "IS_nav": i["nav"], "OOS_nav": o["nav"], "OOSx924_nav": ox["nav"], "Y25_nav": y5["nav"], "Y26_nav": y6["nav"],
                })
        pd.DataFrame(pk_rows).to_csv(f"{OUT_DIR}/arch_pk_th{int(deep_th)}.csv", index=False)


if __name__ == "__main__":
    main()
