#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Run Final V1.1 Production Pipeline & Complete 8-Test Red-Team Validation Suite."""
import json, os, pickle, sys, time, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
V1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
PART2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
sys.path.insert(0, V1_DIR); sys.path.insert(0, PART2_DIR); sys.path.insert(0, OUT_DIR)

from backtest_utils import _sim_k_slots
from v11_core import V11_EXIT_CFG, V11_FACTOR_META, compute_scorecard_v11, sim_v11_exit, truncation_20250101_v11
from v11_audits import eval_window, overfitting_suite_v11, kline_exdiv_dt_audit, v191_empty_slot_v11


def main():
    t0 = time.time()
    aux = pickle.load(open(f"{PART2_DIR}/cache_20cm_aux.pkl", "rb"))
    sh300, ew20, all_dts = aux["sh300"], aux["ew20_daily"], aux["all_dts"]
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")

    # Verify total 37 delisted 20cm stocks in raw delisted db
    dl_raw = pd.read_parquet(f"{BASE}/data/cn_hk_price_db/a_delisted_daily.parquet", columns=["ticker"])
    dl_20_tickers = sorted({t[:6] for t in dl_raw["ticker"].astype(str) if t[:6].startswith(("30", "688", "689"))})

    pool = df[df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    sc, fm = compute_scorecard_v11(pool)
    pool["score"] = sc.values

    # Primary execution uses strict +0.30% TP penetration buffer & 0.30% round-trip fee!
    tr_all = sim_v11_exit(pool, V11_EXIT_CFG, fee=0.0030, tp_buf=0.0030).drop(columns=["score"])
    pool_meta = pool[["dt", "c6", "score", "f1_body", "f1_clv", "f1_zt", "f1_is_dt"]].rename(columns={"dt": "sig_date"})
    all_sig = tr_all.merge(pool_meta, on=["sig_date", "c6"], how="left")
    all_sig = all_sig.merge(pd.concat([pool[["dt", "c6"]].rename(columns={"dt": "sig_date"}), fm], axis=1), on=["sig_date", "c6"], how="left")
    all_sig["d1_branch"] = np.where(all_sig["f1_zt"], "B1_D1_ZT",
                           np.where((all_sig["f1_body"] <= -0.05) | all_sig["f1_is_dt"], "B4_D1_DeepYin",
                           np.where((all_sig["f1_body"] >= 0.06) & (all_sig["f1_clv"] >= 0.65), "B2_D1_StrongYang", "B3_D1_Mild")))
    all_sig.to_csv(f"{OUT_DIR}/final_v11_all_scored_signals.csv", index=False, encoding="utf-8-sig")

    tr_A = all_sig[all_sig["score"] >= 76.0].copy()
    tr_S = all_sig[all_sig["score"] >= 82.0].copy()
    slot_A, _, _ = _sim_k_slots(tr_A, 1)
    slot_S, _, _ = _sim_k_slots(tr_S, 1)
    slot_A["buy_hhmm"] = 925; slot_A["exit_hhmm"] = np.where(slot_A["exit_reason"].str.contains("open|gap|tp"), 1030, 1500)
    slot_S["buy_hhmm"] = 925; slot_S["exit_hhmm"] = np.where(slot_S["exit_reason"].str.contains("open|gap|tp"), 1030, 1500)
    slot_A.to_csv(f"{OUT_DIR}/final_v11_ledger.csv", index=False, encoding="utf-8-sig")
    slot_S.to_csv(f"{OUT_DIR}/final_v11_ledger_S82.csv", index=False, encoding="utf-8-sig")

    # Export final_v11_scorecard.csv (with IS/OOS marginal stats & 2021~2026 yearly coverage!)
    all_sig["yr"] = all_sig["buy_date"].str[:4]
    b_is = all_sig.loc[all_sig["buy_date"] <= "2024-08-31", "net_ret"].mean() * 100
    b_oos = all_sig.loc[all_sig["buy_date"] >= "2024-09-01", "net_ret"].mean() * 100
    sc_rows = []
    for fid, dim, desc, w_str, phys in V11_FACTOR_META:
        m_is = (all_sig["buy_date"] <= "2024-08-31").to_numpy() & (all_sig[fid].to_numpy() != 0)
        m_oos = (all_sig["buy_date"] >= "2024-09-01").to_numpy() & (all_sig[fid].to_numpy() != 0)
        r_is, r_oos = all_sig.loc[m_is, "net_ret"].to_numpy(), all_sig.loc[m_oos, "net_ret"].to_numpy()
        yr_cov = {f"cov_{y}_pct": round(float((all_sig.loc[all_sig["yr"] == y, fid] != 0).mean() * 100), 1) for y in ["2021", "2022", "2023", "2024", "2025", "2026"]}
        sc_rows.append({
            "factor_id": fid, "dimension": dim, "definition": desc, "weight": w_str, "physics": phys,
            "IS_hits": int(len(r_is)), "IS_WR": round(float((r_is > 0).mean() * 100), 2), "IS_delta_pct": round(float(r_is.mean() * 100 - b_is), 2),
            "OOS_hits": int(len(r_oos)), "OOS_WR": round(float((r_oos > 0).mean() * 100), 2), "OOS_delta_pct": round(float(r_oos.mean() * 100 - b_oos), 2),
            **yr_cov,
        })
    pd.DataFrame(sc_rows).to_csv(f"{OUT_DIR}/final_v11_scorecard.csv", index=False, encoding="utf-8-sig")

    # Windows & Yearly tables
    wins = [("FULL", "2021-01-04", "2026-11-23", False), ("IS", "2021-01-04", "2024-08-31", False),
            ("OOS", "2024-09-01", "2026-11-23", False), ("OOS_ex924", "2024-09-01", "2026-11-23", True), ("2026", "2026-01-01", "2026-11-23", False)]
    metrics = {}
    for tnm, tdf in [("A_76", tr_A), ("S_82", tr_S)]:
        metrics[tnm] = {wn: eval_window(tdf, sh300, ew20, sdt, edt, ex9) for wn, sdt, edt, ex9 in wins}
    yearly = {}
    for tnm, tdf in [("A_76", tr_A), ("S_82", tr_S)]:
        yearly[tnm] = {y: eval_window(tdf, sh300, ew20, f"{y}-01-01", f"{y}-12-31" if y != "2026" else "2026-11-23", False) for y in ["2021", "2022", "2023", "2024", "2025", "2026"]}

    # Friction & Capacity Stress (0.3/0.5/0.8% fee, amt>=2e8/3e8, buf=0 vs buf=0.30% vs PureT2)
    pool_A = pool[pool["score"] >= 76.0].copy()
    stress = {}
    for snm, sub_p, cfg_s, f_s, b_s in [
        ("A76_buf0.30_fee0.30_base", pool_A, V11_EXIT_CFG, 0.0030, 0.0030),
        ("A76_buf0.00_fee0.30_nobuf", pool_A, V11_EXIT_CFG, 0.0030, 0.0000),
        ("A76_buf0.30_fee0.50", pool_A, V11_EXIT_CFG, 0.0050, 0.0030),
        ("A76_buf0.30_fee0.80", pool_A, V11_EXIT_CFG, 0.0080, 0.0030),
        ("A76_buf0.30_amt2e8", pool_A[pool_A["amount"] >= 2e8], V11_EXIT_CFG, 0.0030, 0.0030),
        ("A76_buf0.30_amt3e8", pool_A[pool_A["amount"] >= 3e8], V11_EXIT_CFG, 0.0030, 0.0030),
        ("A76_PureT2_Close", pool_A, {"b3_tp_mode": "none", "b2_mode": "d2_close", "zt_imm": False, "risk_mode": "none"}, 0.0030, 0.0030),
    ]:
        ts = sim_v11_exit(sub_p, cfg_s, fee=f_s, tp_buf=b_s)
        stress[snm] = {wn: eval_window(ts, sh300, ew20, sdt, edt, ex9) for wn, sdt, edt, ex9 in wins}

    # 8-Test Suite, Truncation, Kline/Ex-Div/DT, Delisted, V19.1
    ov_A = overfitting_suite_v11("A_76", pool, fm, 76.0, all_sig, sh300, all_dts)
    ov_S = overfitting_suite_v11("S_82", pool, fm, 82.0, all_sig, sh300, all_dts)
    trunc = truncation_20250101_v11(slot_A, slot_S)
    k_int = kline_exdiv_dt_audit(slot_A, slot_S, all_sig)
    v191 = v191_empty_slot_v11(all_sig, sh300)

    delisted_audit = {
        "raw_delisted_20cm_universe_cnt": len(dl_20_tickers),
        "raw_delisted_20cm_tickers": dl_20_tickers,
        "clean_pool_delisted_rows": int((df["dl"] == 1).sum()),
        "clean_pool_delisted_tickers": sorted(df[df["dl"] == 1]["c6"].unique().tolist()),
        "skeleton_pool_hits": all_sig[all_sig["dl"] == 1][["sig_date", "buy_date", "exit_date", "c6", "name", "score", "net_ret", "exit_reason"]].to_dict("records"),
        "slot_A76_hits": slot_A[slot_A["dl"] == 1][["buy_date", "exit_date", "c6", "name", "score", "net_ret_eval", "exit_reason"]].to_dict("records"),
        "slot_S82_hits": slot_S[slot_S["dl"] == 1][["buy_date", "exit_date", "c6", "name", "score", "net_ret_eval", "exit_reason"]].to_dict("records"),
    }

    audit = {
        "strategy_name": "20cm_首板深水错杀反抽_V1.1",
        "architecture_decision": "Arch1_Pure_DeepOpen_V1.1 (淘汰普涨Beta轨：样本外ex924及2026年实盘全线亏损挤占深水机会)",
        "execution_standard": "09:25买入 + 盘中限价止盈须打穿+0.30%缓冲(high>=target*1.003) + 0.30%双边滑点",
        "thresholds": {"A_tier": 76, "S_tier": 82},
        "exit_cfg": V11_EXIT_CFG,
        "metrics": metrics, "yearly": yearly, "stress_tests": stress,
        "overfitting_audit": {"A_76": ov_A, "S_82": ov_S},
        "delisted_audit": delisted_audit, "truncation_20250101": trunc,
        "kline_exdiv_dt_integrity": k_int, "v191_empty_slot_test": v191,
        "elapsed_sec": round(time.time() - t0, 2),
    }
    with open(f"{OUT_DIR}/final_v11_redteam_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print(f"[DONE in {audit['elapsed_sec']}s]")
    print("  A_76 FULL:", metrics["A_76"]["FULL"])
    print("  A_76 OOS :", metrics["A_76"]["OOS"])
    print("  A_76 2026:", metrics["A_76"]["2026"])
    print("  S_82 FULL:", metrics["S_82"]["FULL"])
    print("  S_82 2025:", yearly["S_82"]["2025"])
    print("  TRUNC    :", trunc)
    print("  KLINE/INT:", k_int["kline_matched_all"], k_int["kline_err_all"], k_int["integrity"], "exdiv=", len(k_int["exdiv_hold_trades"]), "dt_def=", len(k_int["dt_deferral_trades"]))
    print("  V19.1    :", json.dumps(v191, ensure_ascii=False))


if __name__ == "__main__":
    main()
