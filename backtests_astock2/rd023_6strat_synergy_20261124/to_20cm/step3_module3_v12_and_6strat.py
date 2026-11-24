#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD023 Module 3: V1.2 Candidate Gate Audit (R_sen20_lt40 vs V1.1) + 6-Strategy Pure Single-Slot Priority Audit."""
import json, os, pickle, sys, time
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
P2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
PC_DIR = f"{BASE}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
OUT_DIR = f"{BASE}/backtests_astock2/rd023_6strat_synergy_20261124/to_20cm"
sys.path.insert(0, P2_DIR); sys.path.insert(0, OUT_DIR)

from backtest_utils import bench_return, _sim_k_slots
from rd023_eval_lib import V11_EXIT_CFG, compute_scorecard_v11, cscv_pbo, eval_splits, sim_v11_exit_ext


def run_1slot_chrono(pool_df: pd.DataFrame) -> pd.DataFrame:
    """Exact chronological single-slot execution (same as V19.1 run_1slot_sim)."""
    df_s = pool_df.sort_values(
        ["buy_date", "priority", "score", "buy_hhmm", "code"],
        ascending=[True, True, False, True, True],
    ).reset_index(drop=True)
    picked, cur_ed, cur_eh = [], "", 0
    for r in df_s.itertuples(index=False):
        if (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and int(r.buy_hhmm) > cur_eh):
            picked.append(r._asdict())
            cur_ed = r.exit_date
            cur_eh = int(r.buy_hhmm) if False else int(r.exit_hhmm)
    return pd.DataFrame(picked)


def run_strict_empty_preserve(v191_df: pd.DataFrame, s20_df: pd.DataFrame) -> pd.DataFrame:
    """Oracle empty-slot fill preserving 228/228 V19.1 trades (matches v11_audits.py Scheme 2)."""
    cols_k = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "priority", "score", "net_ret"]
    occ = [((r.buy_date, int(r.buy_hhmm)), (r.exit_date, int(r.exit_hhmm))) for r in v191_df.itertuples(index=False)]
    s20_ord = s20_df[cols_k].sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).reset_index(drop=True)
    acc = []
    for r in s20_ord.itertuples(index=False):
        st_i, en_i = (r.buy_date, int(r.buy_hhmm)), (r.exit_date, int(r.exit_hhmm))
        if all((en_i < os_) or (st_i > oe_) for os_, oe_ in occ):
            acc.append(r._asdict()); occ.append((st_i, en_i))
    return pd.concat([v191_df[cols_k], pd.DataFrame(acc, columns=cols_k)], ignore_index=True).sort_values(["buy_date", "buy_hhmm", "exit_date"]).reset_index(drop=True)


def assert_clean_slot(df: pd.DataFrame):
    assert (df["exit_date"] > df["buy_date"]).all(), "T+0 violation"
    for i in range(1, len(df)):
        p, c = df.iloc[i - 1], df.iloc[i]
        assert (c["buy_date"], int(c["buy_hhmm"])) > (p["exit_date"], int(p["exit_hhmm"])), f"Overlap at {i}"


def calc_window_stats(df: pd.DataFrame, sh300: dict, sdt: str, edt: str, yrs: float) -> dict:
    sub = df[(df["buy_date"] >= sdt) & (df["buy_date"] <= edt)]
    hs = bench_return(sh300, sdt, edt)
    if sub.empty:
        return {"n": 0, "wr": 0.0, "po": 0.0, "nav": 1.0, "ex5": 1.0, "mdd": 0.0, "calmar": 0.0, "hs300_ret": round(hs * 100, 2), "ex_hs300_pp": round(-hs * 100, 2)}
    r = sub["net_ret"].to_numpy(dtype=float)
    cum = np.cumprod(1.0 + r)
    pk = np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]
    mdd = float(np.max((pk - cum) / pk))
    nav = float(cum[-1])
    w, l = r[r > 0], r[r <= 0]
    po = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else 99.0
    ex5 = float(np.prod(1.0 + np.sort(r)[:-5])) if len(r) > 5 else 1.0
    cagr = (nav ** (1.0 / yrs) - 1.0) * 100.0 if nav > 0 else -100.0
    calmar = round(cagr / (mdd * 100.0), 2) if mdd > 1e-6 else 99.0
    return {
        "n": int(len(r)), "wr": round(float((r > 0).mean() * 100), 2), "po": round(po, 2),
        "mean_pct": round(float(r.mean() * 100), 2), "nav": round(nav, 2), "ex5": round(ex5, 2),
        "mdd": round(mdd * 100, 2), "calmar": calmar,
        "hs300_ret": round(hs * 100, 2), "ex_hs300_pp": round((nav - 1.0 - hs) * 100, 1),
    }


def main():
    t0 = time.time()
    pool = pd.read_parquet(f"{OUT_DIR}/rd023_pool_enriched.parquet")
    aux = pickle.load(open(f"{P2_DIR}/cache_20cm_aux.pkl", "rb"))
    sh300, all_dts = aux["sh300"], aux["all_dts"]
    sc, _ = compute_scorecard_v11(pool)
    pool["score"] = sc.values

    # 1. V1.2 Candidate Gate Audit: V1.1 vs V1.1+R_sen20_lt40
    tr_v11 = sim_v11_exit_ext(pool, V11_EXIT_CFG, fee=0.0030, tp_buf=0.0030)
    tr_sen = sim_v11_exit_ext(pool, {**V11_EXIT_CFG, "extra_risk": ["R_sen20_lt40"]}, fee=0.0030, tp_buf=0.0030)
    pbo_v11 = cscv_pbo(tr_v11, 76.0, all_dts)
    pbo_sen = cscv_pbo(tr_sen, 76.0, all_dts)
    ev_v11_A = eval_splits(tr_v11[tr_v11["score"] >= 76.0])
    ev_sen_A = eval_splits(tr_sen[tr_sen["score"] >= 76.0])
    ev_v11_S = eval_splits(tr_v11[tr_v11["score"] >= 82.0])
    ev_sen_S = eval_splits(tr_sen[tr_sen["score"] >= 82.0])
    print("=== V1.1 vs Candidate V1.1+R_sen20_lt40 ===")
    print("  V1.1 A76:", ev_v11_A["IS"]["nav"], ev_v11_A["OOS"]["nav"], ev_v11_A["Y26"]["nav"], ev_v11_A["FULL"]["nav"], "EW:", ev_v11_A["FULL"]["ew_nav"], "PBO:", pbo_v11)
    print("  +sen A76:", ev_sen_A["IS"]["nav"], ev_sen_A["OOS"]["nav"], ev_sen_A["Y26"]["nav"], ev_sen_A["FULL"]["nav"], "EW:", ev_sen_A["FULL"]["ew_nav"], "PBO:", pbo_sen)
    print("  V1.1 S82:", ev_v11_S["IS"]["nav"], ev_v11_S["OOS"]["nav"], ev_v11_S["Y26"]["nav"], ev_v11_S["FULL"]["nav"], "EW:", ev_v11_S["FULL"]["ew_nav"])
    print("  +sen S82:", ev_sen_S["IS"]["nav"], ev_sen_S["OOS"]["nav"], ev_sen_S["Y26"]["nav"], ev_sen_S["FULL"]["nav"], "EW:", ev_sen_S["FULL"]["ew_nav"])

    # 2. Load 5 clean 10cm pools + V19.1 combined ledger (2021-11-15 ~ 2026-11-16)
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

    # Verify V19.1 base reproduction
    base5 = run_1slot_chrono(pd.concat([p34, phd, ppr, p23, p12], ignore_index=True))
    assert len(base5) == len(v191) == 228 and np.max(np.abs(base5["net_ret"].to_numpy() - v191["net_ret"].to_numpy())) < 1e-6

    def prep_20cm(tr_src, min_sc, prio_fn, label="20cm首板深水V1.1"):
        s = tr_src[(tr_src["score"] >= min_sc) & tr_src["buy_date"].between("2021-11-15", "2026-11-16")].copy()
        s["code"] = s["c6"].astype(str).str.zfill(6)
        s["buy_hhmm"] = 925
        s["exit_hhmm"] = np.where(s["exit_reason"].str.contains("open|gap|tp|dev93"), 1030, 1500)
        s["strategy"] = label
        s["priority"] = prio_fn(s)
        return s[cols_k]

    schemes = []
    WINS = [("FULL", "2021-11-15", "2026-11-16", 5.0), ("IS", "2021-11-15", "2024-08-31", 2.79),
            ("OOS", "2024-09-01", "2026-11-16", 2.21), ("Y26", "2026-01-01", "2026-11-16", 0.88)]

    def eval_scheme(name, df_cmb):
        assert_clean_slot(df_cmb)
        row = {"scheme": name, "by_strat": df_cmb["strategy"].value_counts().to_dict(),
               "v191_228_kept": int(sum((df_cmb["strategy"] != "20cm首板深水V1.1") & (df_cmb["strategy"] != "20cm首板深水_Rsen20")))}
        for wn, sd, ed, yrs in WINS:
            st = calc_window_stats(df_cmb, sh300, sd, ed, yrs)
            for k, v in st.items():
                row[f"{wn}_{k}"] = v
        # 20cm solo contribution inside combined
        s20_sub = df_cmb[df_cmb["strategy"].str.startswith("20cm")]
        row["20cm_n"] = int(len(s20_sub))
        row["20cm_wr"] = round(float((s20_sub["net_ret"] > 0).mean() * 100), 2) if len(s20_sub) else 0.0
        row["20cm_mean"] = round(float(s20_sub["net_ret"].mean() * 100), 2) if len(s20_sub) else 0.0
        row["20cm_solo_nav"] = round(float(np.prod(1.0 + s20_sub["net_ret"].to_numpy())), 2) if len(s20_sub) else 1.0
        schemes.append(row)

    # Scheme 1: V19.1 Baseline (228)
    eval_scheme("S1_V19.1_5Strat_Base", base5)
    # Scheme 2A: 20cm A76 at prio 6 (strictly preserve 228/228)
    s20_A6 = prep_20cm(tr_v11, 76.0, lambda x: 6)
    eval_scheme("S2A_20cmA_P6_Preserve228", run_strict_empty_preserve(v191[cols_k], s20_A6))
    # Scheme 2B: 20cm A76 at prio 6 (causal chronological single-slot)
    eval_scheme("S2B_20cmA_P6_Causal", run_1slot_chrono(pd.concat([p34, phd, ppr, p23, p12, s20_A6], ignore_index=True)))
    # Scheme 3_PM: 20cm A76 at prio 5 (ahead of 1to2=6) — PM's urgent test!
    s20_A5 = prep_20cm(tr_v11, 76.0, lambda x: 5)
    p12_6 = p12.assign(priority=6)
    eval_scheme("S3_PM_20cmA_P5_vs_1to2_P6", run_1slot_chrono(pd.concat([p34, phd, ppr, p23, s20_A5, p12_6], ignore_index=True)))
    # Scheme 4: 20cm S82 at prio 5 (ahead of 1to2=6), 20cm A(76~81) at prio 7
    s20_S5_A7 = prep_20cm(tr_v11, 76.0, lambda x: np.where(x["score"] >= 82.0, 5, 7))
    eval_scheme("S4_20cmS_P5_A_P7", run_1slot_chrono(pd.concat([p34, phd, ppr, p23, p12_6, s20_S5_A7], ignore_index=True)))
    # Scheme 5: 20cm S82 at prio 4 (ahead of 2to3=5, 1to2=6), 20cm A(76~81) at prio 7
    s20_S4_A7 = prep_20cm(tr_v11, 76.0, lambda x: np.where(x["score"] >= 82.0, 4, 7))
    p23_5 = p23.assign(priority=5)
    eval_scheme("S5_20cmS_P4_2to3_P5_A_P7", run_1slot_chrono(pd.concat([p34, phd, ppr, s20_S4_A7, p23_5, p12_6], ignore_index=True)))
    # Also test Scheme 3_sen20 (with R_sen20_lt40 exit switch) for comparison!
    s20_sen_A5 = prep_20cm(tr_sen, 76.0, lambda x: 5, label="20cm首板深水_Rsen20")
    eval_scheme("S3_Rsen20_20cmA_P5", run_1slot_chrono(pd.concat([p34, phd, ppr, p23, s20_sen_A5, p12_6], ignore_index=True)))

    df_sch = pd.DataFrame(schemes)
    df_sch.to_csv(f"{OUT_DIR}/module3_6strat_priority_audit.csv", index=False, encoding="utf-8-sig")
    v11_vs_sen = {"V11_A76": ev_v11_A, "V11_pbo": pbo_v11, "Rsen20_A76": ev_sen_A, "Rsen20_pbo": pbo_sen,
                  "V11_S82": ev_v11_S, "Rsen20_S82": ev_sen_S, "schemes": schemes}
    json.dump(v11_vs_sen, open(f"{OUT_DIR}/module3_v12_and_6strat.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    cols_p = ["scheme", "FULL_n", "FULL_wr", "FULL_po", "FULL_nav", "FULL_ex5", "FULL_mdd", "FULL_calmar", "OOS_nav", "OOS_wr", "Y26_nav", "Y26_wr", "20cm_n", "20cm_wr", "20cm_solo_nav"]
    print(f"\n[DONE Module 3 in {time.time()-t0:.2f}s]")
    print(df_sch[cols_p].to_string(index=False))
    for r in schemes:
        print(f"  {r['scheme']}: by_strat={r['by_strat']}")


if __name__ == "__main__":
    main()
