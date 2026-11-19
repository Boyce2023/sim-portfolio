#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step2_audit_curve_factors.py — C8 四大主战策略 × 8连续曲线特征 单因子双段(IS/OOS) + 共线性 + 组合增益审计
严格零前视偏差：分位数切分点与剔除方向均严格由 IS (2021-2023) 锁定，原样外推至 OOS (2024-2026)。
"""
import os, json
import numpy as np
import pandas as pd
from scipy import stats

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/continuous_curve_explore_20261119/part2_existing4_curve_audit"
FEAT_CSV = os.path.join(OUT_DIR, "all_trades_curve_features_pit.csv")

CORE_FEATURES = [
    ("F1_ER10", "cont"),
    ("F1_ER10_SIGNED", "cont"),
    ("F2_VCP", "cont"),
    ("F3_MA_SCORE", "disc_score"),
    ("F3_MA20_SLOPE", "cont"),
    ("F4_VOL_BUILD", "cont"),
    ("F4_VOL_BUILD15", "cont"),
    ("F5_N_WAVE", "bin"),
    ("F6_MA5_HUG", "cont_int"),
    ("F7_YANG_RATIO", "cont_int"),
    ("F8_DIST_HI120", "cont"),
]

BASE_REFS = ["pos20", "dd20", "dd60", "score"]
STRAT_ORDER = ["3to4", "high", "2to3", "1to2"]
PRIORITY = {"3to4": 1, "high": 2, "2to3": 3, "1to2": 4}


def calc_slot_stats(sub: pd.DataFrame) -> dict:
    if sub.empty:
        return {"n": 0, "wr": 0.0, "mean": 0.0, "plr": 0.0, "nav": 1.0, "mdd": 0.0}
    r = sub.sort_values(["buy_date", "buy_hhmm"])["net_ret"].to_numpy(dtype=float)
    wins = r[r > 0]
    losses = r[r <= 0]
    wr = float(len(wins) / len(r) * 100.0)
    mean_r = float(np.mean(r) * 100.0)
    plr = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else (99.9 if len(wins) > 0 else 0.0)
    cum = np.cumprod(1.0 + r)
    peaks = np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]
    mdd = float(np.max((peaks - cum) / peaks) * 100.0)
    return {"n": int(len(r)), "wr": round(wr, 2), "mean": round(mean_r, 2), "plr": round(plr, 2), "nav": round(float(cum[-1]), 3), "mdd": round(mdd, 2)}


def run_1slot_4strat(pool: pd.DataFrame) -> pd.DataFrame:
    df_s = pool.copy()
    df_s["priority"] = df_s["strategy"].map(PRIORITY)
    df_s = df_s.sort_values(["buy_date", "priority", "score", "buy_hhmm"], ascending=[True, True, False, True]).reset_index(drop=True)
    picked = []
    cur_ed, cur_eh = "", 0
    for row in df_s.itertuples(index=False):
        if not cur_ed or row.buy_date > cur_ed or (row.buy_date == cur_ed and row.buy_hhmm > cur_eh):
            picked.append(row._asdict())
            cur_ed = row.exit_date
            cur_eh = row.exit_hhmm
    return pd.DataFrame(picked)


def assign_groups_is_locked(is_vals: np.ndarray, all_vals: np.ndarray, kind: str):
    """Build 3-group (tertile) and 2-group (median) labels using strictly IS thresholds."""
    if kind == "bin":
        g3 = np.where(all_vals >= 0.5, "G1_yes", "G0_no")
        g2 = g3.copy()
        return g3, g2, "0 vs 1"

    if kind == "disc_score":
        # 0-1 vs 2 vs 3
        g3 = np.where(all_vals <= 1, "Q1_low(0-1)", np.where(all_vals == 2, "Q2_mid(2)", "Q3_high(3)"))
        med = float(np.median(is_vals))
        g2 = np.where(all_vals <= 1, "B1_low(<=1)", "B2_high(2-3)")
        return g3, g2, f"0-1/2/3 (IS_med={med:.1f})"

    # Continuous or integer discrete: compute IS quantiles
    q33, q67 = np.quantile(is_vals, [1 / 3, 2 / 3])
    med = float(np.median(is_vals))
    if q33 == q67:
        # Fallback if too many ties at boundary
        q33 = float(np.quantile(is_vals, 0.25))
        q67 = float(np.quantile(is_vals, 0.75))

    if q33 < q67:
        g3 = np.where(all_vals <= q33, "Q1_low", np.where(all_vals <= q67, "Q2_mid", "Q3_high"))
    else:
        g3 = np.where(all_vals <= med, "Q1_low", "Q3_high")

    if np.sum(is_vals <= med) == len(is_vals) or np.sum(is_vals > med) == 0:
        g2 = np.where(all_vals < med, "B1_low", "B2_high")
        cut_str = f"q33={q33:.3f}, q67={q67:.3f}, lt_med={med:.3f}"
    else:
        g2 = np.where(all_vals <= med, "B1_low", "B2_high")
        cut_str = f"q33={q33:.3f}, q67={q67:.3f}, med={med:.3f}"
    return g3, g2, cut_str


def eval_split(df_s: pd.DataFrame, grp_col: str):
    is_df = df_s[df_s["is_oos"] == 0]
    oos_df = df_s[df_s["is_oos"] == 1]

    is_grp = is_df.groupby(grp_col)["net_ret"].agg(n="count", mean="mean", wr=lambda x: (x > 0).mean())
    oos_grp = oos_df.groupby(grp_col)["net_ret"].agg(n="count", mean="mean", wr=lambda x: (x > 0).mean())

    # Identify worst and best groups strictly on IS mean return
    if len(is_grp) < 2:
        return None
    worst_g = str(is_grp["mean"].idxmin())
    best_g = str(is_grp["mean"].idxmax())
    # Compare best_g vs worst_g in both IS and OOS
    if worst_g not in oos_grp.index or best_g not in oos_grp.index:
        return None

    is_diff_mean = float((is_grp.loc[best_g, "mean"] - is_grp.loc[worst_g, "mean"]) * 100.0)
    is_diff_wr = float((is_grp.loc[best_g, "wr"] - is_grp.loc[worst_g, "wr"]) * 100.0)
    oos_diff_mean = float((oos_grp.loc[best_g, "mean"] - oos_grp.loc[worst_g, "mean"]) * 100.0)
    oos_diff_wr = float((oos_grp.loc[best_g, "wr"] - oos_grp.loc[worst_g, "wr"]) * 100.0)

    # Filter performance: keep everything except IS-worst group
    keep_df = df_s[df_s[grp_col] != worst_g]
    keep_is = keep_df[keep_df["is_oos"] == 0]
    keep_oos = keep_df[keep_df["is_oos"] == 1]

    base_is_s = calc_slot_stats(is_df)
    base_oos_s = calc_slot_stats(oos_df)
    keep_is_s = calc_slot_stats(keep_is)
    keep_oos_s = calc_slot_stats(keep_oos)

    return {
        "worst_g": worst_g,
        "best_g": best_g,
        "is_spread_mean_pp": round(is_diff_mean, 2),
        "is_spread_wr_pp": round(is_diff_wr, 2),
        "oos_spread_mean_pp": round(oos_diff_mean, 2),
        "oos_spread_wr_pp": round(oos_diff_wr, 2),
        "same_dir_mean": int(is_diff_mean > 0 and oos_diff_mean > 0),
        "same_dir_wr": int(is_diff_wr > 0 and oos_diff_wr > 0),
        "is_grp_detail": {k: {"n": int(v["n"]), "wr": round(v["wr"] * 100, 1), "mean": round(v["mean"] * 100, 2)} for k, v in is_grp.to_dict("index").items()},
        "oos_grp_detail": {k: {"n": int(v["n"]), "wr": round(v["wr"] * 100, 1), "mean": round(v["mean"] * 100, 2)} for k, v in oos_grp.to_dict("index").items()},
        "filt_is_d_mean": round(keep_is_s["mean"] - base_is_s["mean"], 2),
        "filt_is_d_wr": round(keep_is_s["wr"] - base_is_s["wr"], 2),
        "filt_oos_d_mean": round(keep_oos_s["mean"] - base_oos_s["mean"], 2),
        "filt_oos_d_wr": round(keep_oos_s["wr"] - base_oos_s["wr"], 2),
        "filt_5y": calc_slot_stats(keep_df),
        "filt_3y": calc_slot_stats(keep_df[keep_df["buy_date"] >= "2023-11-16"]),
        "filt_2026": calc_slot_stats(keep_df[keep_df["buy_date"] >= "2026-01-01"]),
        "filt_oos": keep_oos_s,
    }


def audit_anchor(df: pd.DataFrame, prefix: str = "") -> tuple[pd.DataFrame, list[dict]]:
    records = []
    details = []
    for strat in STRAT_ORDER:
        df_s = df[df["strategy"] == strat].copy()
        is_df = df_s[df_s["is_oos"] == 0]
        oos_df = df_s[df_s["is_oos"] == 1]

        base_5y = calc_slot_stats(df_s)
        base_3y = calc_slot_stats(df_s[df_s["buy_date"] >= "2023-11-16"])
        base_oos = calc_slot_stats(oos_df)
        base_26 = calc_slot_stats(df_s[df_s["buy_date"] >= "2026-01-01"])

        for fname, fkind in CORE_FEATURES:
            col = f"{prefix}{fname}"
            is_vals = is_df[col].to_numpy(dtype=float)
            all_vals = df_s[col].to_numpy(dtype=float)

            rho_is, p_is = stats.spearmanr(is_vals, is_df["net_ret"].to_numpy(dtype=float))
            rho_oos, p_oos = stats.spearmanr(oos_df[col].to_numpy(dtype=float), oos_df["net_ret"].to_numpy(dtype=float))
            rho_is = 0.0 if np.isnan(rho_is) else float(rho_is)
            rho_oos = 0.0 if np.isnan(rho_oos) else float(rho_oos)

            # Collinearity with pos20, dd20, dd60, score
            ref_corrs = {}
            for rc in BASE_REFS:
                rcol = f"{prefix}{rc}" if rc != "score" else "score"
                rr, _ = stats.spearmanr(all_vals, df_s[rcol].to_numpy(dtype=float))
                ref_corrs[rc] = round(0.0 if np.isnan(rr) else float(rr), 3)
            max_ref_name = max(ref_corrs, key=lambda k: abs(ref_corrs[k]))
            max_ref_val = ref_corrs[max_ref_name]

            g3, g2, cut_str = assign_groups_is_locked(is_vals, all_vals, fkind)
            df_s["_g3"] = g3
            df_s["_g2"] = g2
            res3 = eval_split(df_s, "_g3")
            res2 = eval_split(df_s, "_g2")

            # Determine classification label
            same_rho = (rho_is * rho_oos > 0) and (abs(rho_is) >= 0.08 and abs(rho_oos) >= 0.08)
            g3_pass = bool(res3 and res3["same_dir_mean"] == 1 and res3["filt_oos_d_mean"] > 0.3)
            g2_pass = bool(res2 and res2["same_dir_mean"] == 1 and res2["filt_oos_d_mean"] > 0.3)
            collinear = abs(max_ref_val) >= 0.50

            if (g3_pass or g2_pass) and collinear:
                verdict = f"疑似已吸收({max_ref_name}={max_ref_val:+.2f})"
            elif g3_pass and g2_pass and same_rho:
                verdict = "双段强同向候选"
            elif g3_pass or g2_pass:
                verdict = "双段弱同向(待复核)"
            elif (res3 and res3["same_dir_mean"] == 0) or (rho_is * rho_oos < 0):
                verdict = "异号失效"
            else:
                verdict = "无显著增量"

            row_rec = {
                "anchor": prefix or "D0",
                "strategy": strat,
                "feature": fname,
                "rho_is": round(rho_is, 3),
                "rho_oos": round(rho_oos, 3),
                "max_ref": f"{max_ref_name}:{max_ref_val:+.2f}",
                "g3_worst": res3["worst_g"] if res3 else "-",
                "g3_is_diff": res3["is_spread_mean_pp"] if res3 else 0.0,
                "g3_oos_diff": res3["oos_spread_mean_pp"] if res3 else 0.0,
                "g3_oos_d_mean": res3["filt_oos_d_mean"] if res3 else 0.0,
                "g3_oos_d_wr": res3["filt_oos_d_wr"] if res3 else 0.0,
                "g2_worst": res2["worst_g"] if res2 else "-",
                "g2_is_diff": res2["is_spread_mean_pp"] if res2 else 0.0,
                "g2_oos_diff": res2["oos_spread_mean_pp"] if res2 else 0.0,
                "g2_oos_d_mean": res2["filt_oos_d_mean"] if res2 else 0.0,
                "g2_oos_d_wr": res2["filt_oos_d_wr"] if res2 else 0.0,
                "verdict": verdict,
            }
            records.append(row_rec)
            details.append({
                "anchor": prefix or "D0",
                "strategy": strat,
                "feature": fname,
                "cuts": cut_str,
                "rho_is": round(rho_is, 4),
                "p_is": round(float(p_is), 4) if not np.isnan(p_is) else 1.0,
                "rho_oos": round(rho_oos, 4),
                "p_oos": round(float(p_oos), 4) if not np.isnan(p_oos) else 1.0,
                "ref_corrs": ref_corrs,
                "base": {"5y": base_5y, "3y": base_3y, "oos": base_oos, "2026": base_26},
                "g3": res3,
                "g2": res2,
                "verdict": verdict,
            })
    return pd.DataFrame(records), details


def main():
    df = pd.read_csv(FEAT_CSV)
    tab_d0, det_d0 = audit_anchor(df, prefix="")
    tab_sig, det_sig = audit_anchor(df, prefix="sig_")

    tab_all = pd.concat([tab_d0, tab_sig], ignore_index=True)
    tab_all.to_csv(os.path.join(OUT_DIR, "audit_summary_matrix.csv"), index=False)
    with open(os.path.join(OUT_DIR, "audit_details.json"), "w", encoding="utf-8") as f:
        json.dump({"d0": det_d0, "sig": det_sig}, f, ensure_ascii=False, indent=2)

    # Print compact D0 matrix first
    print("=== D0 (Pre-Launch) 4-Strategy x Curve Features Summary ===")
    cols_show = ["strategy", "feature", "rho_is", "rho_oos", "max_ref", "g3_is_diff", "g3_oos_diff", "g3_oos_d_mean", "g2_is_diff", "g2_oos_diff", "g2_oos_d_mean", "verdict"]
    print(tab_d0[cols_show].to_string(index=False))

    print("\n=== Candidates in D_sig (signal_date) with same-dir signal ===")
    c_sig = tab_sig[tab_sig["verdict"].str.contains("候选|同向|已吸收")]
    print(c_sig[cols_show].to_string(index=False))


if __name__ == "__main__":
    main()
