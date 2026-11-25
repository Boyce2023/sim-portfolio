#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD027 Wave 2A: Multi-Process Systematic 1,097-Factor Scan (Newey-West HAC + BH-FDR + IS/OOS + 3-Era),
8 Falsifiable China Hypotheses (CH1 ~ CH8), and Jorda Local Projections (T+20/60/120/250).
Outputs:
  - output/china_policy_macro_rd027_20261125/wave2_factors/wave2a_1000factor_audit.json
  - output/china_policy_macro_rd027_20261125/wave2_factors/surviving_factors_top100.csv
"""
from concurrent.futures import ProcessPoolExecutor
import json
import math
import os
import sys
import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
import rd027_common as cm
from wave2a_stats_and_hypotheses import (
    benjamini_hochberg,
    nw_ols_uni,
    run_ch1_to_ch8_tests,
    run_jorda_local_projections,
)

WAVE2_DIR = os.path.join(cm.ROOT, "output/china_policy_macro_rd027_20261125/wave2_factors")
MASTER_PQ = os.path.join(WAVE2_DIR, "master_weekly_1000factors_pit.parquet")
CATALOG_JSON = os.path.join(WAVE2_DIR, "factor_catalog.json")
OUT_AUDIT = os.path.join(WAVE2_DIR, "wave2a_1000factor_audit.json")
OUT_TOP100 = os.path.join(WAVE2_DIR, "surviving_factors_top100.csv")

TARGET_SPECS = [
    ("tgt_csi300_fwd_60d", 60, "大盘60日收益"),
    ("tgt_csi300_fwd_120d", 120, "大盘120日收益"),
    ("tgt_csi300_fwd_250d", 250, "大盘250日收益"),
    ("tgt_ew_all_fwd_120d", 120, "全A等权120日收益"),
    ("tgt_csi300_fwd_60d_mdd", 60, "大盘60日最大回撤风险"),
    ("tgt_micro30_minus_300_120d", 120, "微盘vs沪深300(120日剪刀差)"),
    ("tgt_div_minus_chinext_120d", 120, "红利vs创业板(120日剪刀差)"),
    ("tgt_tech_minus_300_120d", 120, "硬科技vs沪深300(120日剪刀差)"),
]


def _scan_one_target(args: tuple) -> tuple[str, list[dict]]:
    """Worker function scanning all factors against one target with Newey-West HAC + era splits."""
    tgt_col, horizon, tgt_desc, y_arr, X_mat, factor_names, dates_arr = args
    maxlags = int(math.ceil(horizon / 5.0))
    ti = np.arange(len(y_arr), dtype=int)

    is_m = dates_arr <= "2020-12-31"
    oos_m = dates_arr >= "2021-01-01"
    e1_m = dates_arr <= "2014-12-31"
    e2_m = (dates_arr >= "2015-01-01") & (dates_arr <= "2020-12-31")
    e3_m = dates_arr >= "2021-01-01"
    e3b_m = dates_arr >= "2024-01-01"

    rows = []
    for j, fn in enumerate(factor_names):
        x = X_mat[:, j]
        b, b1, se, t, p, r2, n = nw_ols_uni(x, y_arr, ti, maxlags, min_n=40)
        b_is, _, _, t_is, _, _, n_is = nw_ols_uni(x[is_m], y_arr[is_m], ti[is_m], maxlags, min_n=30)
        b_oos, _, _, t_oos, _, _, n_oos = nw_ols_uni(x[oos_m], y_arr[oos_m], ti[oos_m], maxlags, min_n=30)
        b_e1, _, _, t_e1, _, _, n_e1 = nw_ols_uni(x[e1_m], y_arr[e1_m], ti[e1_m], maxlags, min_n=30)
        b_e2, _, _, t_e2, _, _, n_e2 = nw_ols_uni(x[e2_m], y_arr[e2_m], ti[e2_m], maxlags, min_n=30)
        b_e3, _, _, t_e3, _, _, n_e3 = nw_ols_uni(x[e3_m], y_arr[e3_m], ti[e3_m], maxlags, min_n=30)
        b_e3b, _, _, t_e3b, _, _, n_e3b = nw_ols_uni(x[e3b_m], y_arr[e3b_m], ti[e3b_m], maxlags, min_n=15)

        def _sgn(val):
            if not np.isfinite(val) or abs(val) < 1e-12:
                return 0
            return 1 if val > 0 else -1

        rows.append({
            "target": tgt_col,
            "target_desc": tgt_desc,
            "horizon": horizon,
            "maxlags": maxlags,
            "factor": fn,
            "n_full": n,
            "beta": b,
            "beta_1sd_pct": b1 * 100.0 if np.isfinite(b1) else np.nan,
            "t_hac": t,
            "abs_t_hac": abs(t) if np.isfinite(t) else np.nan,
            "p_val": p,
            "r2_pct": r2 * 100.0 if np.isfinite(r2) else np.nan,
            "sign_full": _sgn(b),
            "n_is": n_is,
            "t_is": t_is,
            "sign_is": _sgn(b_is),
            "n_oos": n_oos,
            "t_oos": t_oos,
            "sign_oos": _sgn(b_oos),
            "sign_e1": _sgn(b_e1),
            "t_e1": t_e1,
            "sign_e2": _sgn(b_e2),
            "t_e2": t_e2,
            "sign_e3": _sgn(b_e3),
            "t_e3": t_e3,
            "sign_e3b": _sgn(b_e3b),
            "t_e3b": t_e3b,
            "n_e3b": n_e3b,
        })

    pvals = np.array([r["p_val"] for r in rows], dtype=float)
    qvals = benjamini_hochberg(pvals)
    for r, q in zip(rows, qvals):
        r["q_val"] = float(q) if np.isfinite(q) else np.nan
        sf = r["sign_full"]
        sis = r["sign_is"]
        soos = r["sign_oos"]
        se1, se2, se3 = r["sign_e1"], r["sign_e2"], r["sign_e3"]

        is_oos_match = (sf != 0) and (sis == sf) and (soos == sf)
        three_era_match = (sf != 0) and (se1 == sf) and (se2 == sf) and (se3 == sf)
        two_era_oos_match = (sf != 0) and (se3 == sf) and ((se1 == sf) or (se2 == sf))
        oos_flipped = (sf != 0) and ((soos != sf) or (sis != sf))

        q_ok_05 = np.isfinite(q) and q < 0.05
        q_ok_10 = np.isfinite(q) and q < 0.10
        hlz_ok = np.isfinite(r["abs_t_hac"]) and r["abs_t_hac"] >= 3.0

        if q_ok_05 and hlz_ok and is_oos_match and three_era_match:
            tier = "S级铁律真因子"
        elif q_ok_05 and hlz_ok and is_oos_match and two_era_oos_match:
            tier = "A级体制真因子"
        elif q_ok_05 and is_oos_match and two_era_oos_match:
            tier = "A2级有效因子(q<0.05,|t|<3)"
        elif q_ok_10 and is_oos_match and two_era_oos_match:
            tier = "B级候选真因子(q<0.10)"
        elif q_ok_05 and oos_flipped:
            tier = "已证伪/体制断裂"
        elif q_ok_10 and oos_flipped:
            tier = "体制断裂候选"
        else:
            tier = "过拟合淘汰"

        r["is_oos_match"] = bool(is_oos_match)
        r["three_era_match"] = bool(three_era_match)
        r["two_era_oos_match"] = bool(two_era_oos_match)
        r["era3b_2426_match"] = bool((sf != 0) and (r["sign_e3b"] == sf))
        r["tier"] = tier

    return tgt_col, rows


def main():
    print("[Wave2A-Scan] Loading master weekly PIT table & catalog...")
    df = pd.read_parquet(MASTER_PQ)
    with open(CATALOG_JSON, encoding="utf-8") as f:
        cat = json.load(f)

    p2_raw = pd.read_parquet(os.path.join(cm.OUT_PILLAR_DIR, "pillar2_top_meetings_diff.parquet"))
    p3_raw = pd.read_parquet(os.path.join(cm.OUT_PILLAR_DIR, "pillar3_sector_traffic_lights.parquet"))

    factor_names = list(cat["factors"].keys())
    X_mat = df[factor_names].to_numpy(dtype=float)
    dates_arr = df["date_str"].to_numpy(dtype=str)

    # Latest 2026-11-24 causal percentile & value map
    latest_vals = {}
    latest_pct = {}
    for j, fn in enumerate(factor_names):
        col = X_mat[:, j]
        lv = col[-1]
        latest_vals[fn] = None if np.isnan(lv) else round(float(lv), 4)
        valid = col[np.isfinite(col)]
        if len(valid) > 10 and np.isfinite(lv):
            latest_pct[fn] = round(float(np.mean(valid <= lv) * 100.0), 1)
        else:
            latest_pct[fn] = None

    print(f"[Wave2A-Scan] Scanning {len(factor_names)} factors x {len(TARGET_SPECS)} targets in parallel...")
    tasks = []
    for tgt_col, horizon, tgt_desc in TARGET_SPECS:
        y_arr = df[tgt_col].to_numpy(dtype=float)
        tasks.append((tgt_col, horizon, tgt_desc, y_arr, X_mat, factor_names, dates_arr))

    all_rows = []
    n_workers = min(8, os.cpu_count() or 4)
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        for tgt_col, rows in ex.map(_scan_one_target, tasks):
            all_rows.extend(rows)

    res_df = pd.DataFrame(all_rows)
    res_df["family"] = res_df["factor"].map(lambda fn: cat["factors"][fn]["family"])
    res_df["formula"] = res_df["factor"].map(lambda fn: cat["factors"][fn]["formula"])
    res_df["effective_start"] = res_df["factor"].map(lambda fn: cat["factors"][fn]["effective_start_date"])
    res_df["latest_20261124"] = res_df["factor"].map(latest_vals)
    res_df["latest_pct_rank"] = res_df["factor"].map(latest_pct)

    # Summary statistics across all targets & per target
    tier_counts_all = res_df["tier"].value_counts().to_dict()
    per_target_summary = {}
    top15_by_target = {}

    for tgt_col, horizon, tgt_desc in TARGET_SPECS:
        sub = res_df[res_df["target"] == tgt_col].copy()
        n_tot = len(sub)
        n_q05 = int((sub["q_val"] < 0.05).sum())
        n_q10 = int((sub["q_val"] < 0.10).sum())
        n_hlz = int((sub["abs_t_hac"] >= 3.0).sum())
        n_s = int((sub["tier"] == "S级铁律真因子").sum())
        n_a = int((sub["tier"] == "A级体制真因子").sum())
        n_a2 = int((sub["tier"] == "A2级有效因子(q<0.05,|t|<3)").sum())
        n_b = int((sub["tier"] == "B级候选真因子(q<0.10)").sum())
        n_brk = int(sub["tier"].isin(["已证伪/体制断裂", "体制断裂候选"]).sum())
        per_target_summary[tgt_col] = {
            "desc": tgt_desc,
            "horizon_days": horizon,
            "maxlags_weeks": int(math.ceil(horizon / 5.0)),
            "n_tested": n_tot,
            "q_lt_005": n_q05,
            "q_lt_010": n_q10,
            "abs_t_ge_3": n_hlz,
            "S_tier_3era_hlz": n_s,
            "A_tier_2era_hlz": n_a,
            "A2_tier_q05_lt3": n_a2,
            "B_tier_q10_cand": n_b,
            "robust_SA_total": n_s + n_a,
            "robust_SA_pct": round((n_s + n_a) / n_tot * 100.0, 2),
            "broken_or_falsified": n_brk,
            "eliminated": int((sub["tier"] == "过拟合淘汰").sum()),
        }

        # Top 15 surviving factors for this target (prioritize S -> A -> A2 -> B -> others sorted by |t_HAC|)
        tier_rank = {
            "S级铁律真因子": 0, "A级体制真因子": 1, "A2级有效因子(q<0.05,|t|<3)": 2,
            "B级候选真因子(q<0.10)": 3, "已证伪/体制断裂": 4, "体制断裂候选": 5, "过拟合淘汰": 6,
        }
        sub["trank"] = sub["tier"].map(tier_rank)
        top15 = sub.sort_values(["trank", "abs_t_hac"], ascending=[True, False]).head(15)
        t15_list = []
        for _, r in top15.iterrows():
            t15_list.append({
                "factor": r["factor"],
                "family": r["family"],
                "tier": r["tier"],
                "t_hac": round(float(r["t_hac"]), 3),
                "q_val": float(f"{r['q_val']:.3e}"),
                "beta_1sd_pct": round(float(r["beta_1sd_pct"]), 2),
                "r2_pct": round(float(r["r2_pct"]), 2),
                "signs_IS_OOS_E1_E2_E3_E3b": f"{r['sign_is']:+d}/{r['sign_oos']:+d}|{r['sign_e1']:+d}/{r['sign_e2']:+d}/{r['sign_e3']:+d}/{r['sign_e3b']:+d}",
                "t_IS_OOS": f"{round(float(r['t_is']),2) if pd.notna(r['t_is']) else None}/{round(float(r['t_oos']),2) if pd.notna(r['t_oos']) else None}",
                "latest_20261124": r["latest_20261124"],
                "latest_pct_rank": r["latest_pct_rank"],
            })
        top15_by_target[tgt_col] = t15_list

    # Unique surviving factors count across targets
    surv_sa = res_df[res_df["tier"].isin(["S级铁律真因子", "A级体制真因子"])]
    surv_all = res_df[res_df["tier"].isin(["S级铁律真因子", "A级体制真因子", "A2级有效因子(q<0.05,|t|<3)"])]
    surv_cand = res_df[res_df["tier"].isin(["S级铁律真因子", "A级体制真因子", "A2级有效因子(q<0.05,|t|<3)", "B级候选真因子(q<0.10)"])]

    # Save Top 100 surviving factor-target pairs (ranked by tier then |t_HAC|)
    tier_rank = {
        "S级铁律真因子": 0, "A级体制真因子": 1, "A2级有效因子(q<0.05,|t|<3)": 2,
        "B级候选真因子(q<0.10)": 3, "已证伪/体制断裂": 4, "体制断裂候选": 5, "过拟合淘汰": 6,
    }
    res_df["trank"] = res_df["tier"].map(tier_rank)
    surv_pool = res_df[res_df["trank"] <= 3].sort_values(["trank", "abs_t_hac"], ascending=[True, False])
    if len(surv_pool) < 100:
        surv_pool = res_df.sort_values(["trank", "abs_t_hac"], ascending=[True, False])
    top100 = surv_pool.head(100).drop(columns=["trank"])
    top100.to_csv(OUT_TOP100, index=False, encoding="utf-8-sig")

    print("[Wave2A-Scan] Running CH1~CH8 hypothesis falsification & Jorda Local Projections...")
    ch_results = run_ch1_to_ch8_tests(df, p3_raw, p2_raw)
    jorda_results = run_jorda_local_projections(df)

    audit = {
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "n_weeks": int(len(df)),
        "date_range": [str(df["date_str"].iloc[0]), str(df["date_str"].iloc[-1])],
        "n_factors": len(factor_names),
        "n_targets": len(TARGET_SPECS),
        "total_tests": int(len(res_df)),
        "family_counts": cat["family_counts"],
        "global_summary": {
            "unique_factors_SA_hlz": int(surv_sa["factor"].nunique()),
            "unique_factors_SA_pct": round(surv_sa["factor"].nunique() / len(factor_names) * 100.0, 2),
            "unique_factors_S_only": int(res_df[res_df["tier"] == "S级铁律真因子"]["factor"].nunique()),
            "unique_factors_q05_is_oos_all": int(surv_all["factor"].nunique()),
            "unique_factors_q10_cand_all": int(surv_cand["factor"].nunique()),
            "pair_tier_counts": tier_counts_all,
        },
        "per_target_summary": per_target_summary,
        "top15_by_target": top15_by_target,
        "ch1_to_ch8_hypotheses": ch_results,
        "jorda_local_projections": jorda_results,
    }
    with open(OUT_AUDIT, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print(f"[Wave2A-Scan] Saved {OUT_AUDIT}")
    print(f"[Wave2A-Scan] Saved {OUT_TOP100} ({len(top100)} rows)")
    print(f"[Wave2A-Scan] Unique S+A factors (|t|>=3, q<0.05, IS+OOS): {audit['global_summary']['unique_factors_SA_hlz']}/{len(factor_names)} ({audit['global_summary']['unique_factors_SA_pct']}%)")
    print(f"[Wave2A-Scan] Unique S-tier only: {audit['global_summary']['unique_factors_S_only']}")


if __name__ == "__main__":
    main()
