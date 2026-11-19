#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step3_deep_audit.py — 深度核查所有双段同向/疑似候选特征：
1. 打印完整 IS/OOS 分组明细 (N, WR%, Mean%, 方向单调性)
2. 检验剔除 IS 最差组后单策略 5Y / Near3Y / OOS / 2026 净值、胜率、盈亏比、回撤变化
3. 正交性回归检验：控制 [pos20, dd20, dd60, score] 后，特征残差与 net_ret 在 IS/OOS 是否仍显著同向
4. 检验四大策略 1-slot 合体组合净值/回撤增益 (D15)
"""
import os, json
import numpy as np
import pandas as pd
from scipy import stats

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/continuous_curve_explore_20261119/part2_existing4_curve_audit"
FEAT_CSV = os.path.join(OUT_DIR, "all_trades_curve_features_pit.csv")
DETAILS_JSON = os.path.join(OUT_DIR, "audit_details.json")
CSI_JSON = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_rebacktest_20261116/csi300_canonical_20261116.json"

PRIORITY = {"3to4": 1, "high": 2, "2to3": 3, "1to2": 4}


def run_1slot(pool: pd.DataFrame) -> pd.DataFrame:
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


def win_metrics(sub: pd.DataFrame, start_dt: str) -> dict:
    s = sub[sub["buy_date"] >= start_dt]
    if s.empty:
        return {"n": 0, "wr": 0.0, "mean": 0.0, "plr": 0.0, "nav": 1.0, "mdd": 0.0}
    r = s.sort_values(["buy_date", "buy_hhmm"])["net_ret"].to_numpy(dtype=float)
    wins, losses = r[r > 0], r[r <= 0]
    wr = float(len(wins) / len(r) * 100.0)
    plr = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else 99.9
    cum = np.cumprod(1.0 + r)
    peaks = np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]
    mdd = float(np.max((peaks - cum) / peaks) * 100.0)
    return {"n": len(r), "wr": round(wr, 2), "mean": round(float(r.mean() * 100), 2), "plr": round(plr, 2), "nav": round(float(cum[-1]), 2), "mdd": round(mdd, 2)}


def residualize_ols(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    Xc = np.column_stack([np.ones(len(X)), X])
    beta, _, _, _ = np.linalg.lstsq(Xc, y, rcond=None)
    return y - Xc @ beta


def main():
    df = pd.read_csv(FEAT_CSV)
    with open(DETAILS_JSON, "r", encoding="utf-8") as f:
        det = json.load(f)

    # 1. Inspect ALL D0 candidates that had same_dir_mean==1 in g3 or g2, OR |rho|>=0.08 same dir
    print("=== DETAILED INSPECTION OF ALL D0 CANDIDATES (same-dir in g3 or g2) ===")
    candidates = []
    for item in det["d0"]:
        g3 = item["g3"]
        g2 = item["g2"]
        g3_ok = bool(g3 and g3["same_dir_mean"] == 1 and g3["filt_oos_d_mean"] > 0)
        g2_ok = bool(g2 and g2["same_dir_mean"] == 1 and g2["filt_oos_d_mean"] > 0)
        if not (g3_ok or g2_ok):
            continue

        strat = item["strategy"]
        feat = item["feature"]
        df_s = df[df["strategy"] == strat].copy()
        is_df = df_s[df_s["is_oos"] == 0]
        oos_df = df_s[df_s["is_oos"] == 1]

        # Residualize feature on [pos20, dd20, dd60, score] fitted strictly on IS!
        ctrl_cols = ["pos20", "dd20", "dd60", "score"]
        X_is = is_df[ctrl_cols].to_numpy(dtype=float)
        Xc_is = np.column_stack([np.ones(len(X_is)), X_is])
        beta, _, _, _ = np.linalg.lstsq(Xc_is, is_df[feat].to_numpy(dtype=float), rcond=None)

        X_all = df_s[ctrl_cols].to_numpy(dtype=float)
        Xc_all = np.column_stack([np.ones(len(X_all)), X_all])
        df_s["_f_resid"] = df_s[feat].to_numpy(dtype=float) - Xc_all @ beta

        is_res = df_s[df_s["is_oos"] == 0]
        oos_res = df_s[df_s["is_oos"] == 1]
        r_res_is, p_res_is = stats.spearmanr(is_res["_f_resid"], is_res["net_ret"])
        r_res_oos, p_res_oos = stats.spearmanr(oos_res["_f_resid"], oos_res["net_ret"])

        # Check monotonicity across g3 (Q1 vs Q2 vs Q3)
        print(f"\n--- [{strat}] {feat} | verdict={item['verdict']} | cuts=({item['cuts']}) ---")
        print(f"  Corrs w/ refs: {item['ref_corrs']} | Resid Spearman: IS={r_res_is:+.3f}(p={p_res_is:.3f}), OOS={r_res_oos:+.3f}(p={p_res_oos:.3f})")
        for tag, res in [("G3", g3), ("G2", g2)]:
            if not res:
                continue
            b = item["base"]
            f5, f3, fo, f26 = res["filt_5y"], res["filt_3y"], res["filt_oos"], res["filt_2026"]
            print(f"  {tag} worst={res['worst_g']} best={res['best_g']} | IS_bins={res['is_grp_detail']} | OOS_bins={res['oos_grp_detail']}")
            print(f"     Drop {res['worst_g']}: 5Y N {b['5y']['n']}->{f5['n']} WR {b['5y']['wr']}->{f5['wr']} NAV {b['5y']['nav']}->{f5['nav']} MDD {b['5y']['mdd']}->{f5['mdd']}"
                  f" | OOS WR {b['oos']['wr']}->{fo['wr']} Mean {b['oos']['mean']}->{fo['mean']} NAV {b['oos']['nav']}->{fo['nav']} MDD {b['oos']['mdd']}->{fo['mdd']}"
                  f" | 2026 N {b['2026']['n']}->{f26['n']} WR {b['2026']['wr']}->{f26['wr']} NAV {b['2026']['nav']}->{f26['nav']}")

        candidates.append((strat, feat, item, r_res_is, r_res_oos))

    # 2. Also check D_sig candidates where D0 didn't appear or had notable signal (e.g. high F4/F7, 1to2 F4)
    print("\n=== CHECK NOTABLE D_sig CANDIDATES (excluding high-collinearity dd20/dd60/pos20) ===")
    for item in det["sig"]:
        if "已吸收" in item["verdict"] or "失效" in item["verdict"] or "无显著" in item["verdict"]:
            continue
        g3, g2 = item["g3"], item["g2"]
        if not ((g3 and g3["filt_oos_d_mean"] > 1.0) or (g2 and g2["filt_oos_d_mean"] > 1.0)):
            continue
        print(f"  [sig] {item['strategy']} | {item['feature']} | refs={item['ref_corrs']} | "
              f"G3(worst={g3['worst_g']}, IS_d={g3['is_spread_mean_pp']}, OOS_d={g3['oos_spread_mean_pp']}, OOS_gain={g3['filt_oos_d_mean']}) | "
              f"G2(worst={g2['worst_g']}, IS_d={g2['is_spread_mean_pp']}, OOS_d={g2['oos_spread_mean_pp']}, OOS_gain={g2['filt_oos_d_mean']})")

    # 3. Check 4-strategy 1-slot combined baseline
    base_slot = run_1slot(df)
    print("\n=== BASELINE 4-STRATEGY 1-SLOT PORTFOLIO ===")
    for lbl, d0 in [("5Y(2021-11+)", "2021-11-15"), ("Near3Y(2023-11-16+)", "2023-11-16"), ("OOS(2024+)", "2024-01-01"), ("2026", "2026-01-01")]:
        print(f"  {lbl:18s}: {win_metrics(base_slot, d0)}")
    print("  Strategy share in 1-slot:", base_slot["strategy"].value_counts().to_dict())


if __name__ == "__main__":
    main()
