#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD040 Step 3: Deep Red-Team Forensics on E1a_NoHit100_LowOpen & full E1a anatomy."""
import json
import resource
import sys
import time
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd040_abn_unlock_wave2_20261126"
WAVE1_BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
for p in (OUT_DIR, WAVE1_BASE):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm
import _rd040_eval as rd_ev
import _rd040_wf_runner as rd_wf

WINDOWS_5Y = [
    ("FULL_5Y", "2021-01-04", "2026-11-25"),
    ("WF_2326", "2023-01-03", "2026-11-16"),
    ("Y2021", "2021-01-04", "2021-12-31"),
    ("Y2022", "2022-01-01", "2022-12-31"),
    ("Y2023", "2023-01-01", "2023-12-31"),
    ("Y2024", "2024-01-01", "2024-12-31"),
    ("Y2025", "2025-01-01", "2025-12-31"),
    ("Y2025_2026", "2025-01-01", "2026-11-16"),
    ("Y2026", "2026-01-01", "2026-11-25"),
    ("Y2026_H2", "2026-07-01", "2026-11-25"),
]


def _eval_slice(df: pd.DataFrame, ent: str, ex: str, msk: np.ndarray, bench_df: pd.DataFrame, all_idx_dts: list[str],
                v20_ctx: dict, fee_rt: float = 0.0030, perm_n: int = 1000) -> tuple[dict, pd.DataFrame]:
    view = rd_ev.make_clean_view(df, ent, ex, extra_mask=msk, fee_rt=fee_rt)
    if view.empty:
        return {"n_cands": 0, "n_slot": 0}, view
    _, slot = wfm.select_single_slot_trades(view.assign(wf_score=100.0), score_col="wf_score", threshold=None, wf_only=False)
    # Candidate pool for perm test = all E1a candidates (to test timing+pick alpha!)
    all_e1a = rd_ev.make_clean_view(df, "E1a", ex, extra_mask=None, fee_rt=fee_rt)
    ev = rd_ev.eval_windows_exact(slot, view, all_e1a, bench_df, all_idx_dts, "mtm_json_use", fee_rt, "2021-01-04", "2026-11-25", WINDOWS_5Y, perm_n=perm_n)
    corr = rd_ev.compute_v20_corr_exact(slot, v20_ctx, all_idx_dts, "mtm_json_use", fee_rt, "2023-01-03", "2026-11-16")
    return {"n_cands": int(len(view)), "n_slot": int(len(slot)), "ev": ev, "corr_v20": corr}, slot


def main():
    t0 = time.time()
    df = pd.read_parquet(f"{OUT_DIR}/rd040_events_pit.parquet")
    idx_js = json.load(open(f"{OUT_DIR}/index_klines_cache.json", encoding="utf-8"))
    all_idx_dts = sorted(idx_js["sh000002"].keys())
    v20_ctx = wf.load_v20_reference_context(WAVE1_BASE)
    bench_df = v20_ctx["bench"]

    e1a_all = df[df["entry_type"] == "E1a"].copy()
    nohit = (df["abn_was_hit_100"].to_numpy() == 0)
    op = df["abn_open_pct"].to_numpy()
    amt2 = df["abn_sig_amt_yi"].to_numpy() >= 2.0

    # 1. Anatomy of E1a: why did E1a_NoHit100_LowOpen separate from the rest of E1a?
    anatomy_specs = [
        ("1_E1a_ALL", np.ones(len(df), dtype=bool)),
        ("2_E1a_Hit100_only", ~nohit),
        ("3_E1a_NoHit100_ALL_Open", nohit),
        ("4_E1a_NoHit100_Open_gt_25", nohit & (op > 2.5)),
        ("5_E1a_NoHit100_Open_lt_m45", nohit & (op < -4.5)),
        ("6_E1a_NoHit100_LowOpen_[-4.5,2.5]", nohit & (op >= -4.5) & (op <= 2.5)),
        ("7_E1a_LowOpen_incl_Hit100", (op >= -4.5) & (op <= 2.5)),
    ]
    anatomy_rows = []
    for ex in ("S1_hold1c", "S7_lianban"):
        for nm, msk in anatomy_specs:
            r30, sl = _eval_slice(df, "E1a", ex, msk, bench_df, all_idx_dts, v20_ctx, 0.0030, perm_n=1000 if nm.startswith("6_") else 100)
            r50, _ = _eval_slice(df, "E1a", ex, msk, bench_df, all_idx_dts, v20_ctx, 0.0050, perm_n=20)
            r80, _ = _eval_slice(df, "E1a", ex, msk, bench_df, all_idx_dts, v20_ctx, 0.0080, perm_n=20)
            rliq, _ = _eval_slice(df, "E1a", ex, msk & amt2, bench_df, all_idx_dts, v20_ctx, 0.0030, perm_n=20)
            w5 = r30.get("ev", {}).get("windows", {}).get("FULL_5Y", {})
            wwf = r30.get("ev", {}).get("windows", {}).get("WF_2326", {})
            w25 = r30.get("ev", {}).get("windows", {}).get("Y2025_2026", {})
            w26 = r30.get("ev", {}).get("windows", {}).get("Y2026", {})
            w26h2 = r30.get("ev", {}).get("windows", {}).get("Y2026_H2", {})
            perm = r30.get("ev", {}).get("permutation_1000", {})
            anatomy_rows.append({
                "exit": ex, "slice": nm, "n_cands": r30["n_cands"], "n_slot": r30["n_slot"],
                "wr_5y": w5.get("wr_pct"), "plr_5y": w5.get("plr"), "mean_5y": w5.get("mean_pct"),
                "nav_5y_30": w5.get("nav"), "ex3_5y": w5.get("ex_top3_nav"), "ex5_5y": w5.get("ex_top5_nav"),
                "mdd_5y": w5.get("daily_mdd_pct"), "sharpe_5y": w5.get("daily_sharpe"), "calmar_5y": w5.get("daily_calmar"),
                "excess_csi300_5y": w5.get("excess_csi300_pp"),
                "nav_5y_50": r50.get("ev", {}).get("windows", {}).get("FULL_5Y", {}).get("nav"),
                "ex5_5y_50": r50.get("ev", {}).get("windows", {}).get("FULL_5Y", {}).get("ex_top5_nav"),
                "nav_5y_80": r80.get("ev", {}).get("windows", {}).get("FULL_5Y", {}).get("nav"),
                "ex5_5y_80": r80.get("ev", {}).get("windows", {}).get("FULL_5Y", {}).get("ex_top5_nav"),
                "liq2yi_n": rliq.get("n_slot"), "liq2yi_nav": rliq.get("ev", {}).get("windows", {}).get("FULL_5Y", {}).get("nav"),
                "liq2yi_ex5": rliq.get("ev", {}).get("windows", {}).get("FULL_5Y", {}).get("ex_top5_nav"),
                "nav_wf": wwf.get("nav"), "ex5_wf": wwf.get("ex_top5_nav"), "nav_2526": w25.get("nav"),
                "nav_y26": w26.get("nav"), "nav_26h2": w26h2.get("nav"),
                "perm_sd_p": perm.get("same_day_p_nav"), "perm_any_p": perm.get("any_cand_day_p_nav"),
                "corr_v20": r30.get("corr_v20", {}).get("corr_all_days"),
            })
            if nm.startswith("6_"):
                # Print top-5 winners & bottom-5 losers, plus year-by-year breakdown
                print(f"\n=== DETAIL {ex} | {nm} ===")
                for yr in ("Y2021", "Y2022", "Y2023", "Y2024", "Y2025", "Y2026", "Y2026_H2"):
                    yv = r30["ev"]["windows"].get(yr, {})
                    print(f"  {yr:8s}: n={yv.get('n',0):2d} wr={yv.get('wr_pct',0):5.1f}% nav={yv.get('nav',1):6.3f} ex5={yv.get('ex_top5_nav',1):6.3f} mdd={yv.get('daily_mdd_pct',0):5.1f}% csi={yv.get('csi300_pct',0):+6.1f}%")
                top5 = sl.sort_values("net_ret", ascending=False).head(7)[["buy_date", "exit_date", "code", "abn_open_pct", "abn_peak_dev10", "abn_sig_amt_yi", "net_ret"]]
                bot5 = sl.sort_values("net_ret", ascending=True).head(5)[["buy_date", "exit_date", "code", "abn_open_pct", "abn_peak_dev10", "abn_sig_amt_yi", "net_ret"]]
                print("  TOP7:", top5.to_dict("records"))
                print("  BOT5:", bot5.to_dict("records"))

    # 2. Neighbor plateau grid on Open bounds & Peak bounds (S7_lianban & S1_hold1c)
    plateau_rows = []
    for lo_o in (-6.0, -5.0, -4.5, -4.0, -3.5, -3.0):
        for hi_o in (1.0, 2.0, 2.5, 3.0, 4.0, 5.0):
            if hi_o <= lo_o + 2.0:
                continue
            msk = nohit & (op >= lo_o) & (op <= hi_o)
            for ex in ("S7_lianban", "S1_hold1c"):
                r30, _ = _eval_slice(df, "E1a", ex, msk, bench_df, all_idx_dts, v20_ctx, 0.0030, perm_n=50)
                r80, _ = _eval_slice(df, "E1a", ex, msk, bench_df, all_idx_dts, v20_ctx, 0.0080, perm_n=20)
                w5 = r30["ev"]["windows"]["FULL_5Y"]
                wwf = r30["ev"]["windows"]["WF_2326"]
                w25 = r30["ev"]["windows"]["Y2025_2026"]
                w26 = r30["ev"]["windows"]["Y2026"]
                plateau_rows.append({
                    "exit": ex, "open_lo": lo_o, "open_hi": hi_o, "n_cands": r30["n_cands"], "n_slot": r30["n_slot"],
                    "wr_5y": w5["wr_pct"], "nav_5y_30": w5["nav"], "ex5_5y": w5["ex_top5_nav"],
                    "nav_5y_80": r80["ev"]["windows"]["FULL_5Y"]["nav"], "ex5_80": r80["ev"]["windows"]["FULL_5Y"]["ex_top5_nav"],
                    "nav_wf": wwf["nav"], "ex5_wf": wwf["ex_top5_nav"], "nav_2526": w25["nav"], "nav_y26": w26["nav"],
                })

    # 3. Walk-Forward 0..100 Scorecard + V20 empty-slot patch specifically on E1a_NoHit100 & E1a_NoHit100_LowOpen!
    wf_extra_rows = []
    for tid, msk in [("WF_E1a_NoHit100_S7", nohit), ("WF_E1a_NoHit100_LowOpen_S7", nohit & (op >= -4.5) & (op <= 2.5)),
                     ("WF_E1a_NoHit100_S1", nohit), ("WF_E1a_NoHit100_LowOpen_S1", nohit & (op >= -4.5) & (op <= 2.5))]:
        ex = "S7_lianban" if tid.endswith("S7") else "S1_hold1c"
        view = rd_ev.make_clean_view(df, "E1a", ex, extra_mask=msk, fee_rt=0.0030)
        fcols = rd_wf.get_causal_feature_list(view, [])
        au, rows, _ = rd_wf.evaluate_wf_track(
            tid, view, fcols, v20_ctx, all_idx_dts,
            thresholds=("all_cands", "top30", "top20", "top10", 70, 75),
            run_trunc=True, min_warmup_trades=30, min_warmup_trades_rare=25,
        )
        wf_extra_rows.extend(rows)

    # 4. Also test V20 empty-slot patch directly on blind E1a_NoHit100_LowOpen (2023-01-03 ~ 2026-11-16)
    cal_df = v20_ctx["calendar_5y"]
    patch_cal_dts = cal_df[cal_df["trade_date"].between("2023-01-03", "2026-11-16")].sort_values("trade_date")["trade_date"].tolist()
    v20_patch_direct = {}
    for ex in ("S7_lianban", "S1_hold1c"):
        vw = rd_ev.make_clean_view(df, "E1a", ex, extra_mask=(nohit & (op >= -4.5) & (op <= 2.5)), fee_rt=0.0030)
        vw_m = rd_ev.attach_exact_mtm_col(vw, "mtm_json_use", patch_cal_dts, all_idx_dts, 0.0030, out_col="mtm_patch_exact")
        vw_m["wf_score"] = 100.0
        pr = wf.simulate_v20_empty_slot_patch(vw_m, v20_ctx=v20_ctx, wf_start_dt="2023-01-03", end_dt="2026-11-16", score_col="wf_score", patch_mtm_col="mtm_patch_exact")
        v20_patch_direct[ex] = {
            "m1_v20_base": pr["mode1_strict_combined_no_peek"]["v20_baseline"]["FULL_WF"],
            "m1_combined": pr["mode1_strict_combined_no_peek"]["combined_with_patch"]["FULL_WF"],
            "m1_delta_ratio": pr["mode1_strict_combined_no_peek"]["delta_nav_ratio_full_wf"],
            "m1_delta_sharpe": pr["mode1_strict_combined_no_peek"]["delta_sharpe_full_wf"],
            "m1_n_added": pr["mode1_strict_combined_no_peek"]["n_patch_added"],
            "m1_n_skipped_v20": pr["mode1_strict_combined_no_peek"]["n_v20_skipped_by_collision"],
            "m1_skipped_prod": pr["mode1_strict_combined_no_peek"]["skipped_v20_net_ret_prod"],
            "m2_emp_fw": pr["mode2_empty_slot_standalone"]["windows"]["FULL_WF"],
            "m2_emp_2526": pr["mode2_empty_slot_standalone"]["windows"].get("Y2025_2026"),
            "m2_collision_pct": pr["mode2_empty_slot_standalone"]["collision_rate_pct"],
        }

    pd.DataFrame(anatomy_rows).to_csv(f"{OUT_DIR}/rd040_e1a_anatomy.csv", index=False)
    pd.DataFrame(plateau_rows).to_csv(f"{OUT_DIR}/rd040_e1a_plateau.csv", index=False)
    pd.DataFrame(wf_extra_rows).to_csv(f"{OUT_DIR}/rd040_e1a_wf_extra.csv", index=False)
    with open(f"{OUT_DIR}/rd040_e1a_forensics.json", "w", encoding="utf-8") as f:
        json.dump({"v20_patch_direct": v20_patch_direct, "anatomy": anatomy_rows, "wf_extra": wf_extra_rows}, f, ensure_ascii=False, indent=2)

    print("\n=== ANATOMY SUMMARY ===")
    print(pd.DataFrame(anatomy_rows)[["exit","slice","n_cands","n_slot","wr_5y","nav_5y_30","ex5_5y","nav_5y_80","liq2yi_nav","liq2yi_ex5","nav_wf","ex5_wf","nav_2526","nav_y26","perm_any_p"]].to_string(index=False))
    print("\n=== PLATEAU SUMMARY (S7_lianban) ===")
    print(pd.DataFrame(plateau_rows).query("exit=='S7_lianban'")[["open_lo","open_hi","n_slot","wr_5y","nav_5y_30","ex5_5y","nav_5y_80","ex5_80","nav_wf","ex5_wf","nav_2526","nav_y26"]].to_string(index=False))
    print("\n=== WF EXTRA SUMMARY ===")
    print(pd.DataFrame(wf_extra_rows)[["track","threshold","n_trades","wr_pct","nav_30","ex5_30","nav_80","liq2yi_nav","nav_2526","nav_y26","perm_any_p","emp_nav","v20_comb_delta_ratio","trunc_pass"]].to_string(index=False))
    print("\n=== V20 DIRECT EMPTY SLOT PATCH ===")
    print(json.dumps(v20_patch_direct, ensure_ascii=False, indent=2))
    print(f"\n[Step3 DONE in {time.time()-t0:.1f}s]")


if __name__ == "__main__":
    main()
