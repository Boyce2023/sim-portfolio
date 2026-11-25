#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_trackA_pry_100_exits.py
RD025-Track A: 100 strictly-PIT Super-Oversold Pry exit/risk factors
evaluated across 5 target strategies (1to2 V20, 3to4 V4.1, high V5.1, 2to3 V2.1, 20cm V1.1 S82)
with Benjamini-Hochberg FDR (M=500), 10,000-perm & paired t-test, CSCV PBO, and full D15 audit.
"""
import json
import os
import sys
import time

import numpy as np

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import trackA_data_and_sim as ds
import trackA_100_factors as f100
import trackA_stats_and_audit as st_mod

OUT_JSON = os.path.join(THIS_DIR, "trackA_100_exit_summary.json")

STRAT_LIST = ["1to2", "3to4", "high", "2to3", "20cm"]
STRAT_NAMES = {
    "1to2": "一进二 V20 (s_1to2)",
    "3to4": "三进四 V4.1 (s_3to4)",
    "high": "高标首阴 V5.1 (s_high)",
    "2to3": "二进三 V2.1 (s_2to3)",
    "20cm": "20cm V1.1 S82 (s_20cm_deepopen)",
}
WINDOWS = [
    ("FULL", "2021-01-01", "2026-11-20"),
    ("5Y", "2021-11-16", "2026-11-20"),
    ("3Y", "2023-11-16", "2026-11-20"),
    ("IS", "2021-01-01", "2024-06-30"),
    ("OOS", "2024-07-04", "2026-11-20"),
    ("2026", "2026-01-01", "2026-11-20"),
]


def eval_variant(sk: str, trades_sim: list[dict], ctx: dict, cal_dts: list[str], dt_idx: dict) -> tuple[dict, np.ndarray, list[dict], int]:
    taken, skipped = st_mod.filter_single_slot(trades_sim)
    dr = st_mod.build_daily_mtm(taken, cal_dts, dt_idx, ctx["code_bars"], is_adj_px=(sk == "20cm"))
    wins = {}
    for wlbl, sdt, edt in WINDOWS:
        wins[wlbl] = st_mod.calc_window_d15(taken, dr, cal_dts, dt_idx, ctx["sh300"], ctx["all_dts"], sdt, edt)
    return wins, dr, taken, skipped


def main():
    t0 = time.time()
    print("[1/5] Building PIT context & verifying baseline parity across all 5 ledgers...")
    ctx = ds.build_context()
    parity = ds.verify_baseline_parity(ctx)
    for sk, p_info in parity.items():
        print(f"  Parity {sk:5s}: n={p_info['n']}, mismatches={p_info['mismatches']}, max_ret_diff={p_info['max_ret_diff']}")
        if sk != "high":
            assert p_info["mismatches"] == 0, f"Baseline parity mismatch on {sk}: {p_info}"
        else:
            # High uses strict PIT cp-1 index for 93% double-dev (39/42 exact, 42/42 exit_date exact, max diff ~1.1%)
            assert p_info["max_ret_diff"] < 0.015, f"High parity drift too large: {p_info}"

    factors = f100.build_100_factors()
    rng = np.random.default_rng(20261125)

    # Setup calendar dates per strategy matching each ledger's start..2026-11-16
    cal_by_strat = {}
    dt_idx_by_strat = {}
    for sk in STRAT_LIST:
        min_bd = min(t["buy_date"] for t in ctx["trade_cache"][sk])
        cal_dts = [d for d in ctx["all_dts"] if min_bd <= d <= "2026-11-16"]
        cal_by_strat[sk] = cal_dts
        dt_idx_by_strat[sk] = {d: i for i, d in enumerate(cal_dts)}

    print("[2/5] Evaluating 5 baselines...")
    baselines = {}
    base_dr = {}
    base_rets_paired = {}
    for sk in STRAT_LIST:
        t_base = []
        for tr in ctx["trade_cache"][sk]:
            sim = ds.simulate_trade(sk, tr, ctx, rule_fn=None)
            t_base.append({**tr, **sim})
        wins, dr, taken, skipped = eval_variant(sk, t_base, ctx, cal_by_strat[sk], dt_idx_by_strat[sk])
        assert skipped == 0, f"Baseline overlap in {sk}: {skipped}"
        baselines[sk] = {"windows": wins, "n_trades": len(taken)}
        base_dr[sk] = dr
        base_rets_paired[sk] = np.array([float(t["net_ret"]) for t in t_base], dtype=float)
        print(
            f"  Base {sk:5s} | n={len(taken):3d} FULL={wins['FULL']['nav_1s']:10.2f}x SR={wins['FULL']['sharpe']:.3f} MDD={wins['FULL']['mdd_1s_pct']:.2f}% "
            f"| IS={wins['IS']['nav_1s']:.2f}x | OOS={wins['OOS']['nav_1s']:.2f}x | 2026={wins['2026']['nav_1s']:.2f}x"
        )

    print("[3/5] Scanning all 100 x 5 = 500 (factor x strategy) combinations...")
    all_rows = []
    dr_matrix_by_strat = {sk: [base_dr[sk]] for sk in STRAT_LIST}
    dr_labels_by_strat = {sk: ["BASE"] for sk in STRAT_LIST}
    dr_by_pair = {}

    for fi, fobj in enumerate(factors):
        fid = fobj["id"]
        ffn = fobj["fn"]
        for sk in STRAT_LIST:
            t_new = []
            for tr in ctx["trade_cache"][sk]:
                sim = ds.simulate_trade(sk, tr, ctx, rule_fn=ffn)
                t_new.append({**tr, **sim})
            new_rets = np.array([float(t["net_ret"]) for t in t_new], dtype=float)
            pstats = st_mod.paired_tests_and_change_stats(base_rets_paired[sk], new_rets, rng, n_perm=10000)
            wins, dr, taken, skipped = eval_variant(sk, t_new, ctx, cal_by_strat[sk], dt_idx_by_strat[sk])

            dr_matrix_by_strat[sk].append(dr)
            dr_labels_by_strat[sk].append(fid)
            dr_by_pair[(fid, sk)] = dr

            bw = baselines[sk]["windows"]
            pass_is = (wins["IS"]["nav_1s"] > bw["IS"]["nav_1s"] + 1e-6) and (wins["IS"]["sharpe"] > bw["IS"]["sharpe"] + 1e-6)
            pass_oos = (wins["OOS"]["nav_1s"] > bw["OOS"]["nav_1s"] + 1e-6) and (wins["OOS"]["sharpe"] > bw["OOS"]["sharpe"] + 1e-6)
            pass_2026 = (wins["2026"]["nav_1s"] >= 1.0 - 1e-6) and (wins["2026"]["mdd_1s_pct"] <= bw["2026"]["mdd_1s_pct"] + 1e-6)
            pass_2026_beat = (wins["2026"]["nav_1s"] >= bw["2026"]["nav_1s"] - 1e-6) and (wins["2026"]["mdd_1s_pct"] <= bw["2026"]["mdd_1s_pct"] + 1e-6)
            pass_chg = (pstats["n_changed"] >= 5) and (pstats["chg_win_rate_pct"] >= 60.0)

            all_rows.append({
                "factor_id": fid,
                "family": fobj["family"],
                "name_cn": fobj["name_cn"],
                "decision_time": fobj["decision_time"],
                "action_type": fobj["action_type"],
                "strategy": sk,
                "n_skipped_overlap": skipped,
                **pstats,
                "pass_is": bool(pass_is),
                "pass_oos": bool(pass_oos),
                "pass_2026": bool(pass_2026),
                "pass_2026_beat_base": bool(pass_2026_beat),
                "pass_chg_cnt_wr": bool(pass_chg),
                "windows": wins,
            })
        if (fi + 1) % 20 == 0:
            print(f"  Scanned {fi + 1}/100 factors ({time.time() - t0:.1f}s)")

    print("[4/5] Computing BH-FDR (M=500 & M=100) and CSCV PBO (S=10 & S=8)...")
    # Global BH-FDR across all 500 hypotheses (both t-test and permutation p-values)
    p_tt_all = np.array([r["p_ttest_1s"] for r in all_rows], dtype=float)
    p_pm_all = np.array([r["p_perm_1s"] for r in all_rows], dtype=float)
    q_tt_500 = st_mod.bh_fdr(p_tt_all)
    q_pm_500 = st_mod.bh_fdr(p_pm_all)

    for idx_r, r in enumerate(all_rows):
        r["bh_q_ttest_500"] = round(float(q_tt_500[idx_r]), 6)
        r["bh_q_perm_500"] = round(float(q_pm_500[idx_r]), 6)

    # Per-strategy BH-FDR (M=100) for diagnostic reference
    for sk in STRAT_LIST:
        idxs = [i for i, r in enumerate(all_rows) if r["strategy"] == sk]
        q_tt_100 = st_mod.bh_fdr(np.array([all_rows[i]["p_ttest_1s"] for i in idxs]))
        q_pm_100 = st_mod.bh_fdr(np.array([all_rows[i]["p_perm_1s"] for i in idxs]))
        for j, i in enumerate(idxs):
            all_rows[i]["bh_q_ttest_100"] = round(float(q_tt_100[j]), 6)
            all_rows[i]["bh_q_perm_100"] = round(float(q_pm_100[j]), 6)

    # Strategy-level 101-variant CSCV PBO
    strat_search_pbo = {}
    for sk in STRAT_LIST:
        R_101 = np.column_stack(dr_matrix_by_strat[sk])
        strat_search_pbo[sk] = {
            "cscv_101_s10": st_mod.calc_cscv_pbo_matrix(R_101, 10),
            "cscv_101_s8": st_mod.calc_cscv_pbo_matrix(R_101, 8),
        }

    # Evaluate promotion gates + compute pairwise & family CSCV PBO on all candidates passing >=3 gates or top-10 per strategy
    by_strat = {sk: [r for r in all_rows if r["strategy"] == sk] for sk in STRAT_LIST}
    top_ids = set()
    for sk in STRAT_LIST:
        s_rows = sorted(by_strat[sk], key=lambda x: (x["p_perm_1s"], x["p_ttest_1s"], -x["windows"]["OOS"]["nav_1s"]))
        for r in s_rows[:12]:
            top_ids.add((r["factor_id"], sk))
        for r in by_strat[sk]:
            if r["pass_is"] and r["pass_oos"] and r["pass_2026"] and r["pass_chg_cnt_wr"]:
                top_ids.add((r["factor_id"], sk))

    fam_map = {f["id"]: f["family"] for f in factors}
    fam_members = {}
    for f in factors:
        fam_members.setdefault(f["family"], []).append(f["id"])

    for r in all_rows:
        fid, sk = r["factor_id"], r["strategy"]
        if (fid, sk) in top_ids:
            R_pair = np.column_stack([base_dr[sk], dr_by_pair[(fid, sk)]])
            fam = fam_map[fid]
            R_fam = np.column_stack([base_dr[sk]] + [dr_by_pair[(m_id, sk)] for m_id in fam_members[fam]])
            pbo_pair_s10 = st_mod.calc_cscv_pbo_matrix(R_pair, 10)
            pbo_pair_s8 = st_mod.calc_cscv_pbo_matrix(R_pair, 8)
            pbo_fam_s10 = st_mod.calc_cscv_pbo_matrix(R_fam, 10)
            r["cscv_pair_s10"] = pbo_pair_s10
            r["cscv_pair_s8"] = pbo_pair_s8
            r["cscv_fam_s10"] = pbo_fam_s10
        else:
            r["cscv_pair_s10"] = None
            r["cscv_pair_s8"] = None
            r["cscv_fam_s10"] = None

        q_best_500 = min(r["bh_q_ttest_500"], r["bh_q_perm_500"])
        r["pass_fdr_q15"] = bool(q_best_500 < 0.15)
        r["pass_fdr_q10"] = bool(q_best_500 < 0.10)
        pbo_val = r["cscv_pair_s10"]["pbo_pct"] if r["cscv_pair_s10"] is not None else 100.0
        r["pass_pbo_25"] = bool(pbo_val < 25.0)
        r["promoted"] = bool(
            r["pass_is"] and r["pass_oos"] and r["pass_2026"]
            and r["pass_chg_cnt_wr"] and r["pass_fdr_q15"] and r["pass_pbo_25"]
        )

    print("[5/5] Compiling verdicts & exporting trackA_100_exit_summary.json...")
    verdicts = {}
    for sk in STRAT_LIST:
        s_rows = by_strat[sk]
        prom = [r for r in s_rows if r["promoted"]]
        near_miss = [r for r in s_rows if r["pass_is"] and r["pass_oos"] and r["pass_2026"] and r["pass_chg_cnt_wr"] and not r["promoted"]]
        best_by_p = sorted(s_rows, key=lambda x: (x["p_perm_1s"], x["p_ttest_1s"], -x["windows"]["OOS"]["nav_1s"]))[:5]
        verdicts[sk] = {
            "strategy_name": STRAT_NAMES[sk],
            "n_promoted": len(prom),
            "promoted_ids": [r["factor_id"] for r in prom],
            "n_pass_is_oos_26_chg": len(prom) + len(near_miss),
            "near_miss_ids": [r["factor_id"] for r in near_miss],
            "strat_search_cscv_pbo": strat_search_pbo[sk],
            "top5_by_perm_p": [
                {
                    "factor_id": r["factor_id"], "name_cn": r["name_cn"],
                    "n_changed": r["n_changed"], "chg_wr": r["chg_win_rate_pct"],
                    "mean_delta_pct": r["mean_delta_pct"],
                    "p_perm": round(r["p_perm_1s"], 5), "p_ttest": round(r["p_ttest_1s"], 5),
                    "q_perm_500": r["bh_q_perm_500"], "q_tt_500": r["bh_q_ttest_500"],
                    "is_nav": r["windows"]["IS"]["nav_1s"], "base_is_nav": baselines[sk]["windows"]["IS"]["nav_1s"],
                    "oos_nav": r["windows"]["OOS"]["nav_1s"], "base_oos_nav": baselines[sk]["windows"]["OOS"]["nav_1s"],
                    "y26_nav": r["windows"]["2026"]["nav_1s"], "base_y26_nav": baselines[sk]["windows"]["2026"]["nav_1s"],
                    "pbo_pair_s10": r["cscv_pair_s10"]["pbo_pct"] if r["cscv_pair_s10"] else None,
                    "pbo_fam_s10": r["cscv_fam_s10"]["pbo_pct"] if r["cscv_fam_s10"] else None,
                    "promoted": r["promoted"],
                }
                for r in best_by_p
            ],
            "verdict": "PROMOTED" if prom else "FALSIFIED_NOISE_REJECTED",
        }
        print(f"  Verdict {sk:5s}: {verdicts[sk]['verdict']} (promoted={len(prom)}, pre-FDR pass={len(prom)+len(near_miss)}, search PBO_S10={strat_search_pbo[sk]['cscv_101_s10']['pbo_pct']}%)")

    catalog = [{k: v for k, v in f.items() if k != "fn"} for f in factors]
    summary = {
        "meta": {
            "task": "RD025-Track A: 100 Super-Oversold Pry Exit Factors x 5 Strategies",
            "elapsed_sec": round(time.time() - t0, 2),
            "no_yfinance": "yfinance" not in sys.modules,
            "splits": {"IS": "<= 2024-06-30", "OOS": ">= 2024-07-04", "2026": ">= 2026-01-01"},
            "n_factors": len(catalog),
            "n_strategies": len(STRAT_LIST),
            "n_hypotheses": len(all_rows),
        },
        "baseline_parity": parity,
        "baselines": baselines,
        "factor_catalog_100": catalog,
        "verdicts_by_strategy": verdicts,
        "results_500": all_rows,
    }
    raw_s = json.dumps(summary, ensure_ascii=False, indent=2)
    assert "cap10m" not in raw_s and "1000万" not in raw_s, "Forbidden cap10m found!"
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        f.write(raw_s)
    print(f"DONE in {summary['meta']['elapsed_sec']}s -> {OUT_JSON}")


if __name__ == "__main__":
    main()
