#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD040 Step 2: 28+ Blind Matrix (4 entries x 7 exits) + WF 0..100 Scorecards + Red-Team Audit."""
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

EXITS = ["S1_hold1c", "S2_hold2c", "S3_hold3c", "S4_hold5c", "S5_ma5_stop", "S6_abn95_tp", "S7_lianban"]
WINDOWS_5Y = [
    ("FULL_5Y", "2021-01-04", "2026-11-25"),
    ("WF_2326", "2023-01-03", "2026-11-16"),
    ("Y2025_2026", "2025-01-01", "2026-11-16"),
    ("Y2026", "2026-01-01", "2026-11-25"),
    ("Y2026_H2", "2026-07-01", "2026-11-25"),
]


def _sanitize(obj):
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (np.isnan(v) or np.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def run_blind_matrix(df: pd.DataFrame, bench_df: pd.DataFrame, all_idx_dts: list[str]) -> tuple[pd.DataFrame, dict]:
    """Module 2: Blind test across entries x exits + physical splits (nohit100 vs hit100, cleared vs mine)."""
    slices = [
        ("E1a", "E1a", None),
        ("E1b", "E1b", None),
        ("E2", "E2", None),
        ("E3", "E3", None),
        ("E_ALL", "E_ALL", None),
        ("E_ALL_NoHit100", "E_ALL", df["abn_was_hit_100"].to_numpy() == 0),
        ("E_ALL_Hit100", "E_ALL", df["abn_was_hit_100"].to_numpy() == 1),
        ("E_ALL_Cleared", "E_ALL", df["is_mine_cleared"].to_numpy() == 1),
        ("E_ALL_Mine", "E_ALL", df["is_mine_cleared"].to_numpy() == 0),
        ("E1a_NoHit100_LowOpen", "E1a", (df["abn_was_hit_100"].to_numpy() == 0) & df["abn_open_pct"].between(-4.5, 2.5).to_numpy()),
        ("E3_NoHit100_CtrlOpen", "E3", (df["abn_was_hit_100"].to_numpy() == 0) & (df["abn_open_pct"].to_numpy() <= 6.5)),
    ]
    rows, raw_stats = [], {}
    for s_name, ent, msk in slices:
        for ex in EXITS:
            view = rd_ev.make_clean_view(df, ent, ex, extra_mask=msk, fee_rt=0.0030)
            if view.empty:
                continue
            _, slot = wfm.select_single_slot_trades(view.assign(wf_score=100.0), score_col="wf_score", threshold=None, wf_only=False)
            ev30 = rd_ev.eval_windows_exact(slot, view, view, bench_df, all_idx_dts, "mtm_json_use", 0.0030, "2021-01-04", "2026-11-25", WINDOWS_5Y, perm_n=100)
            # Also 50bps & 80bps on FULL_5Y & WF_2326
            slot50 = slot.assign(net_ret=(1.0 + slot["gross_ret"]) * (1.0 - 0.0050) - 1.0)
            view50 = view.assign(net_ret=(1.0 + view["gross_ret"]) * (1.0 - 0.0050) - 1.0)
            ev50 = rd_ev.eval_windows_exact(slot50, view50, view50, bench_df, all_idx_dts, "mtm_json_use", 0.0050, "2021-01-04", "2026-11-25", WINDOWS_5Y[:2], perm_n=20)
            slot80 = slot.assign(net_ret=(1.0 + slot["gross_ret"]) * (1.0 - 0.0080) - 1.0)
            view80 = view.assign(net_ret=(1.0 + view["gross_ret"]) * (1.0 - 0.0080) - 1.0)
            ev80 = rd_ev.eval_windows_exact(slot80, view80, view80, bench_df, all_idx_dts, "mtm_json_use", 0.0080, "2021-01-04", "2026-11-25", WINDOWS_5Y[:2], perm_n=20)

            f5 = ev30["windows"].get("FULL_5Y", {})
            wf23 = ev30["windows"].get("WF_2326", {})
            y2526 = ev30["windows"].get("Y2025_2026", {})
            y26 = ev30["windows"].get("Y2026", {})
            y26h2 = ev30["windows"].get("Y2026_H2", {})
            rows.append({
                "grid_type": "BLIND_MATRIX", "slice": s_name, "exit_rule": ex,
                "n_cands_5y": int(len(view)), "raw_wr_5y_pct": round(float((view["net_ret"] > 0).mean() * 100), 2),
                "raw_mean_5y_pct": round(float(view["net_ret"].mean() * 100), 2),
                "n_slot_5y": f5.get("n", 0), "wr_5y_pct": f5.get("wr_pct", 0.0), "plr_5y": f5.get("plr", 0.0),
                "nav_5y_30": f5.get("nav", 1.0), "ex5_5y_30": f5.get("ex_top5_nav", 1.0),
                "mdd_5y_pct": f5.get("daily_mdd_pct", 0.0), "sharpe_5y": f5.get("daily_sharpe", 0.0), "calmar_5y": f5.get("daily_calmar", 0.0),
                "excess_csi300_5y_pp": f5.get("excess_csi300_pp", 0.0), "mtm_diff": ev30["mtm_reconciliation_diff"],
                "nav_5y_50": ev50["windows"].get("FULL_5Y", {}).get("nav", 1.0),
                "nav_5y_80": ev80["windows"].get("FULL_5Y", {}).get("nav", 1.0),
                "n_wf": wf23.get("n", 0), "nav_wf_30": wf23.get("nav", 1.0), "ex5_wf_30": wf23.get("ex_top5_nav", 1.0),
                "sharpe_wf": wf23.get("daily_sharpe", 0.0), "excess_csi_wf_pp": wf23.get("excess_csi300_pp", 0.0),
                "nav_2526": y2526.get("nav", 1.0), "nav_y26": y26.get("nav", 1.0), "nav_26h2": y26h2.get("nav", 1.0),
            })
            if s_name in ("E_ALL", "E_ALL_Cleared") and ex == "S2_hold2c":
                raw_stats[s_name] = ev30
    return pd.DataFrame(rows), raw_stats


def main():
    t0 = time.time()
    df = pd.read_parquet(f"{OUT_DIR}/rd040_events_pit.parquet")
    idx_js = json.load(open(f"{OUT_DIR}/index_klines_cache.json", encoding="utf-8"))
    all_idx_dts = sorted(idx_js["sh000002"].keys())
    v20_ctx = wf.load_v20_reference_context(WAVE1_BASE)

    # Bench up to 2026-11-25 exists in v20_ctx["bench"] (1428 rows!)
    bench_df = v20_ctx["bench"]
    blind_df, blind_highlights = run_blind_matrix(df, bench_df, all_idx_dts)

    # Module 3: WF 0..100 Scorecards across key entry x exit tracks (including 两步排雷寻龙分家!)
    mine_excl = ("mine_tox_reg", "mine_prev_dt", "mine_hit_100", "mine_lhasa_heavy", "mine_deep_break",
                 "mine_nuclear_open", "mine_any_cnt", "is_mine_cleared", "abn_was_hit_100", "tox_reg_30d_pre")
    wf_specs = [
        ("WF_E_ALL_S1", "E_ALL", "S1_hold1c", None, ()),
        ("WF_E_ALL_S2", "E_ALL", "S2_hold2c", None, ()),
        ("WF_E_ALL_S3", "E_ALL", "S3_hold3c", None, ()),
        ("WF_E_ALL_S6_95tp", "E_ALL", "S6_abn95_tp", None, ()),
        ("WF_E_ALL_S7_lb", "E_ALL", "S7_lianban", None, ()),
        ("WF_E_ALL_Cleared_S1", "E_ALL", "S1_hold1c", df["is_mine_cleared"].to_numpy() == 1, mine_excl),
        ("WF_E_ALL_Cleared_S2", "E_ALL", "S2_hold2c", df["is_mine_cleared"].to_numpy() == 1, mine_excl),
        ("WF_E_ALL_Cleared_S3", "E_ALL", "S3_hold3c", df["is_mine_cleared"].to_numpy() == 1, mine_excl),
        ("WF_E_ALL_Cleared_S6_95tp", "E_ALL", "S6_abn95_tp", df["is_mine_cleared"].to_numpy() == 1, mine_excl),
        ("WF_E_ALL_Cleared_S7_lb", "E_ALL", "S7_lianban", df["is_mine_cleared"].to_numpy() == 1, mine_excl),
        ("WF_E1a_S2", "E1a", "S2_hold2c", None, ()),
        ("WF_E1a_S6_95tp", "E1a", "S6_abn95_tp", None, ()),
        ("WF_E1b_S2", "E1b", "S2_hold2c", None, ()),
        ("WF_E2_S2", "E2", "S2_hold2c", None, ()),
        ("WF_E3_S2", "E3", "S2_hold2c", None, ()),
        ("WF_E3_S7_lb", "E3", "S7_lianban", None, ()),
    ]
    wf_rows, wf_audits, res_map = [], {}, {}
    for idx_s, (tid, ent, ex, msk, excl) in enumerate(wf_specs):
        view = rd_ev.make_clean_view(df, ent, ex, extra_mask=msk, fee_rt=0.0030)
        if len(view) < 90:
            print(f"[Skip {tid}] len={len(view)}")
            continue
        fcols = rd_wf.get_causal_feature_list(view, [], exclude_cols=excl)
        run_tr = tid in ("WF_E_ALL_S2", "WF_E_ALL_Cleared_S2", "WF_E1a_S2", "WF_E_ALL_S6_95tp")
        au, rows, res_obj = rd_wf.evaluate_wf_track(tid, view, fcols, v20_ctx, all_idx_dts, run_trunc=run_tr)
        wf_audits[tid] = au
        wf_rows.extend(rows)
        res_map[tid] = (res_obj, rows)
        print(f"  -> {tid} done (n={len(view)}, F={len(fcols)}, {au['elapsed_sec']}s)")

    wf_df = pd.DataFrame(wf_rows)
    # Combine blind & WF summary tables for comprehensive CSV export
    blind_df.to_csv(f"{OUT_DIR}/rd040_blind_matrix.csv", index=False, encoding="utf-8-sig")
    wf_df.to_csv(f"{OUT_DIR}/rd040_wf_scorecard_grid.csv", index=False, encoding="utf-8-sig")
    comb_df = pd.concat([blind_df.assign(section="BLIND"), wf_df.assign(section="WF_SCORECARD")], ignore_index=True, sort=False)
    comb_df.to_csv(f"{OUT_DIR}/rd040_events_and_grid.csv", index=False, encoding="utf-8-sig")

    # Check genuine WF winners under Red-Team gates
    sc_only = wf_df[wf_df["threshold"] != "all_cands"].copy()
    winners = sc_only[
        (sc_only["n_trades"] >= 20) & (sc_only["nav_30"] >= 1.5) & (sc_only["ex5_30"] >= 1.15)
        & (sc_only["ex5_50"] >= 1.05) & (sc_only["excess_csi300_pp"] > 0.0) & (sc_only["perm_any_p"] < 0.05)
        & (sc_only["nav_2526"] >= 1.05) & (sc_only["liq2yi_ex5"] >= 1.0)
    ].sort_values(["sharpe", "nav_30"], ascending=False)

    patch_winners = sc_only[
        (sc_only["v20_comb_delta_ratio"].fillna(0.0) > 1.05) & (sc_only["v20_comb_delta_sharpe"].fillna(-9.0) > 0.0)
        & (sc_only["emp_nav"].fillna(0.0) > 1.05) & (sc_only["emp_ex5"].fillna(0.0) > 1.0)
    ].sort_values(["v20_comb_delta_sharpe", "v20_comb_delta_ratio"], ascending=False)

    # Benchmark examples inspection (九阳股份 002242, 海洋王 002724, 慈文传媒 002343, 大业股份 603278 in 2026-10)
    ex_cases = df[df["code"].isin(["002242", "002724", "002343", "603278"]) & (df["buy_date"] >= "2026-10-01")][
        ["code", "entry_type", "sig_date", "buy_date", "abn_peak_dev10", "abn_was_hit_100", "abn_proj_flat_b",
         "abn_rel_proj_pp", "abn_open_pct", "is_mine_cleared", "S1_hold1c_gross_ret", "S2_hold2c_gross_ret", "S6_abn95_tp_gross_ret"]
    ].to_dict("records")

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1)
    step1_au = json.load(open(f"{OUT_DIR}/_step1_audit.json", encoding="utf-8"))
    final_audit = _sanitize({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": rss_mb, "d12_yfinance_imported": "yfinance" in sys.modules,
        "step1_summary": step1_au,
        "benchmark_cases_202610": ex_cases,
        "blind_matrix_top10_wf": blind_df.sort_values("nav_wf_30", ascending=False).head(10).to_dict("records"),
        "wf_top10_nav30": sc_only.sort_values("nav_30", ascending=False).head(10).to_dict("records"),
        "genuine_standalone_winners_cnt": int(len(winners)),
        "genuine_standalone_winners": winners.to_dict("records"),
        "genuine_patch_winners_cnt": int(len(patch_winners)),
        "genuine_patch_winners": patch_winners.to_dict("records"),
        "wf_tracks": wf_audits,
    })
    with open(f"{OUT_DIR}/rd040_audit.json", "w", encoding="utf-8") as f:
        json.dump(final_audit, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"[Step2 DONE in {final_audit['elapsed_sec']}s | RSS={rss_mb}MB] winners={len(winners)} | patch_winners={len(patch_winners)}")
    assert rss_mb < 2000.0, f"Peak RSS >= 2GB: {rss_mb}"


if __name__ == "__main__":
    main()
