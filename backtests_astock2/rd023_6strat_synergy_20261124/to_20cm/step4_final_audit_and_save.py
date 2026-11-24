#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD023 Step 4: Final Red-Team Audit (V1.1 vs R_sen20_lt40), Complete 6-Strategy Priority Table (Zero cap10m), & Master Verdict CSV."""
import json, os, pickle, sys, time
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
P2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
PC_DIR = f"{BASE}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
V11_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
OUT_DIR = f"{BASE}/backtests_astock2/rd023_6strat_synergy_20261124/to_20cm"
sys.path.insert(0, P2_DIR); sys.path.insert(0, V11_DIR); sys.path.insert(0, OUT_DIR)

from backtest_utils import bench_return, _sim_k_slots
from rd023_eval_lib import V11_EXIT_CFG, compute_scorecard_v11, cscv_pbo, eval_splits, sim_v11_exit_ext
from step3_module3_v12_and_6strat import run_1slot_chrono, run_strict_empty_preserve, assert_clean_slot, calc_window_stats
from v11_audits import eval_window, overfitting_suite_v11


def audit_variant(label: str, pool: pd.DataFrame, fm: pd.DataFrame, cfg_patch: dict, sh300: dict, ew20: dict, all_dts: list[str]) -> dict:
    cfg = {**V11_EXIT_CFG, **cfg_patch}
    tr_all = sim_v11_exit_ext(pool, cfg, fee=0.0030, tp_buf=0.0030)
    wins = [("FULL", "2021-01-04", "2026-11-23", False), ("IS", "2021-01-04", "2024-08-31", False),
            ("OOS", "2024-09-01", "2026-11-23", False), ("OOS_ex924", "2024-09-01", "2026-11-23", True),
            ("2026", "2026-01-01", "2026-11-23", False)]
    met = {}
    for tnm, th in [("A_76", 76.0), ("S_82", 82.0)]:
        sub = tr_all[tr_all["score"] >= th]
        met[tnm] = {}
        for wn, sd, ed, ex9 in wins:
            w = eval_window(sub, sh300, ew20, sd, ed, ex9)
            w.pop("cap10m_1s", None)
            met[tnm][wn] = w
    # Stress (0.5%, 0.8%, amt>=2e8, amt>=3e8)
    pool_A = pool[pool["score"] >= 76.0]
    stress = {}
    for snm, sp, f_v in [("fee0.50", pool_A, 0.0050), ("fee0.80", pool_A, 0.0080),
                         ("amt2e8", pool_A[pool_A["amount"] >= 2e8], 0.0030),
                         ("amt3e8", pool_A[pool_A["amount"] >= 3e8], 0.0030)]:
        ts = sim_v11_exit_ext(sp, cfg, fee=f_v, tp_buf=0.0030)
        stress[snm] = {wn: {k: v for k, v in eval_window(ts, sh300, ew20, sd, ed, ex9).items() if k != "cap10m_1s"} for wn, sd, ed, ex9 in wins}
    pbo_A = cscv_pbo(tr_all, 76.0, all_dts)
    pbo_S = cscv_pbo(tr_all, 82.0, all_dts)
    return {"label": label, "metrics": met, "stress": stress, "pbo_A": pbo_A, "pbo_S": pbo_S}


def main():
    t0 = time.time()
    pool = pd.read_parquet(f"{OUT_DIR}/rd023_pool_enriched.parquet")
    aux = pickle.load(open(f"{P2_DIR}/cache_20cm_aux.pkl", "rb"))
    sh300, ew20, all_dts = aux["sh300"], aux["ew20_daily"], aux["all_dts"]
    sc, fm = compute_scorecard_v11(pool)
    pool["score"] = sc.values

    # 1. V1.1 vs R_sen20_lt40 Full Audit
    aud_v11 = audit_variant("DeepOpen_V1.1", pool, fm, {}, sh300, ew20, all_dts)
    aud_sen = audit_variant("DeepOpen_V1.1_plus_Rsen20", pool, fm, {"extra_risk": ["R_sen20_lt40"]}, sh300, ew20, all_dts)

    # 2. Complete 6-strategy single-slot priority matrix (NO cap10m anywhere!)
    cols_k = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "priority", "score", "net_ret"]
    v191 = pd.read_csv(f"{PC_DIR}/ledger_combined_5strat_v191_slot1_clean.csv")
    v191["code"] = v191["code"].astype(str).str.zfill(6)

    def load10(fn, st, pr):
        d = pd.read_csv(f"{PC_DIR}/{fn}")
        d["code"] = d["code"].astype(str).str.zfill(6)
        d["buy_date"] = d["buy_date"].astype(str).str[:10]
        d["exit_date"] = d["exit_date"].astype(str).str[:10]
        d["strategy"] = st; d["priority"] = pr
        return d[cols_k]

    p34 = load10("ledger_3to4_v41_clean.csv", "三进四V4.1", 1)
    phd = load10("ledger_high_v51_clean.csv", "高标首阴V5.1", 2)
    ppr = load10("ledger_pry_v21_top1_clean.csv", "超跌撬板V2.1", 3)
    p23 = load10("ledger_2to3_v21_opt_std90_clean.csv", "二进三V2.1", 4)
    p12 = load10("ledger_1to2_v19_clean.csv", "一进二V19", 5)

    tr_v11 = sim_v11_exit_ext(pool, V11_EXIT_CFG, fee=0.0030, tp_buf=0.0030)
    tr_sen = sim_v11_exit_ext(pool, {**V11_EXIT_CFG, "extra_risk": ["R_sen20_lt40"]}, fee=0.0030, tp_buf=0.0030)

    def prep(tr_src, min_sc, prio_fn, lbl="20cm首板深水V1.1"):
        s = tr_src[(tr_src["score"] >= min_sc) & tr_src["buy_date"].between("2021-11-15", "2026-11-16")].copy()
        s["code"] = s["c6"].astype(str).str.zfill(6); s["buy_hhmm"] = 925
        s["exit_hhmm"] = np.where(s["exit_reason"].str.contains("open|gap|tp|dev93"), 1030, 1500)
        s["strategy"] = lbl; s["priority"] = prio_fn(s); return s[cols_k]

    base5 = run_1slot_chrono(pd.concat([p34, phd, ppr, p23, p12], ignore_index=True))
    WINS = [("FULL", "2021-11-15", "2026-11-16", 5.0), ("IS", "2021-11-15", "2024-08-31", 2.79),
            ("OOS", "2024-09-01", "2026-11-16", 2.21), ("Y26", "2026-01-01", "2026-11-16", 0.88)]

    plan_defs = [
        ("S1_V19.1_5Strat_Base", "现有五策略基线", base5),
        ("S2A_V11_A76_P6_Preserve228", "20cm A76 第6顺位(严格零抢占228笔)", run_strict_empty_preserve(v191[cols_k], prep(tr_v11, 76, lambda x: 6))),
        ("S2B_V11_A76_P6_Causal", "20cm A76 第6顺位(因果时序轮动)", run_1slot_chrono(pd.concat([p34, phd, ppr, p23, p12, prep(tr_v11, 76, lambda x: 6)], ignore_index=True))),
        ("S2C_V11_S82_P6_Causal", "20cm S82 第6顺位(因果时序轮动)", run_1slot_chrono(pd.concat([p34, phd, ppr, p23, p12, prep(tr_v11, 82, lambda x: 6)], ignore_index=True))),
        ("S3_PM_V11_A76_P5_vs_1to2", "PM指定: 20cm A76 第5顺位压住一进二", run_1slot_chrono(pd.concat([p34, phd, ppr, p23, p12.assign(priority=6), prep(tr_v11, 76, lambda x: 5)], ignore_index=True))),
        ("S3B_V11_S82_P5_noA", "20cm S82 第5顺位压住一进二(不纳A76)", run_1slot_chrono(pd.concat([p34, phd, ppr, p23, p12.assign(priority=6), prep(tr_v11, 82, lambda x: 5)], ignore_index=True))),
        ("S4_V11_S82_P5_A_P7", "20cm S82 第5顺位压一进二 + A第7顺位", run_1slot_chrono(pd.concat([p34, phd, ppr, p23, p12.assign(priority=6), prep(tr_v11, 76, lambda x: np.where(x["score"] >= 82, 5, 7))], ignore_index=True))),
        ("S5_V11_S82_P4_2to3_P5_A_P7", "20cm S82 第4顺位压二进三与一进二 + A第7", run_1slot_chrono(pd.concat([p34, phd, ppr, p23.assign(priority=5), p12.assign(priority=6), prep(tr_v11, 76, lambda x: np.where(x["score"] >= 82, 4, 7))], ignore_index=True))),
        ("S2C_Rsen20_S82_P6_Causal", "20cm(加sen20开关) S82 第6顺位因果", run_1slot_chrono(pd.concat([p34, phd, ppr, p23, p12, prep(tr_sen, 82, lambda x: 6, "20cm_Rsen20")], ignore_index=True))),
        ("S4_Rsen20_S82_P5_A_P7", "20cm(加sen20开关) S82第5 + A第7", run_1slot_chrono(pd.concat([p34, phd, ppr, p23, p12.assign(priority=6), prep(tr_sen, 76, lambda x: np.where(x["score"] >= 82, 5, 7), "20cm_Rsen20")], ignore_index=True))),
    ]

    sch_rows = []
    for pid, pdesc, dfc in plan_defs:
        assert_clean_slot(dfc)
        r_out = {"scheme": pid, "desc": pdesc, "by_strat": json.dumps(dfc["strategy"].value_counts().to_dict(), ensure_ascii=False)}
        for wn, sd, ed, yrs in WINS:
            st = calc_window_stats(dfc, sh300, sd, ed, yrs)
            for k, v in st.items():
                r_out[f"{wn}_{k}"] = v
        s20_sub = dfc[dfc["strategy"].str.startswith("20cm")]
        r_out["20cm_n"] = int(len(s20_sub))
        r_out["20cm_wr"] = round(float((s20_sub["net_ret"] > 0).mean() * 100), 2) if len(s20_sub) else 0.0
        r_out["20cm_mean"] = round(float(s20_sub["net_ret"].mean() * 100), 2) if len(s20_sub) else 0.0
        r_out["20cm_solo_nav"] = round(float(np.prod(1.0 + s20_sub["net_ret"].to_numpy())), 2) if len(s20_sub) else 1.0
        sch_rows.append(r_out)

    df_sch = pd.DataFrame(sch_rows)
    df_sch.to_csv(f"{OUT_DIR}/module3_6strat_priority_audit.csv", index=False, encoding="utf-8-sig")
    # Clean module1 CSV to drop any stray columns if needed (already has EW_nav, no cap10m!)
    json.dump({"V1.1": aud_v11, "V1.1_plus_Rsen20": aud_sen, "schemes_6strat": sch_rows},
              open(f"{OUT_DIR}/v11_vs_v12cand_and_6strat_audit.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"[DONE in {time.time()-t0:.2f}s] Saved v11_vs_v12cand_and_6strat_audit.json & module3_6strat_priority_audit.csv")
    print("\n=== V1.1 vs +R_sen20_lt40 Stress ===")
    for nm, a in [("V1.1", aud_v11), ("+R_sen20", aud_sen)]:
        print(nm, "A76 OOS_ex924:", a["metrics"]["A_76"]["OOS_ex924"]["nav_1s"], "fee50:", a["stress"]["fee0.50"]["FULL"]["nav_1s"],
              "fee80:", a["stress"]["fee0.80"]["FULL"]["nav_1s"], "amt3e8:", a["stress"]["amt3e8"]["FULL"]["nav_1s"], "pboA:", a["pbo_A"])
    print("\n=== 6-Strategy Priority Table (Zero cap10m) ===")
    cshow = ["scheme", "FULL_n", "FULL_wr", "FULL_po", "FULL_nav", "FULL_ex5", "FULL_mdd", "FULL_calmar", "OOS_nav", "OOS_wr", "OOS_mdd", "Y26_nav", "Y26_wr", "20cm_n", "20cm_solo_nav"]
    print(df_sch[cshow].to_string(index=False))


if __name__ == "__main__":
    main()
