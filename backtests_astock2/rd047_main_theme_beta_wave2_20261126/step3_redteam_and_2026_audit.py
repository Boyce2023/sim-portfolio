#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD047 Step 3: 2026 Four-Wave Forensic Audit + 4-Gate Trend Anti-Overfit & Truncation Verification.
Outputs:
  - rd047_2026_theme_timeline.csv
  - rd047_2026_trades_detail.csv
  - rd047_audit.json
Zero yfinance (D12). Peak RAM < 1.5 GB.
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation!"
sys.dont_write_bytecode = True

RD047_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd047_main_theme_beta_wave2_20261126"
if RD047_DIR not in sys.path:
    sys.path.insert(0, RD047_DIR)

import _rd047_common as cm
import step2_simulate_tracks as s2


def build_2026_theme_timeline(ctx: dict, ts_npz) -> pd.DataFrame:
    dts = ctx["cal_dts"]
    th_names = ctx["all_theme_names"]
    th_act = ts_npz["th_active"]
    tot = ts_npz["total_score"]
    s_fl = ts_npz["s_flow"]
    s_tr = ts_npz["s_trend"]
    s_se = ts_npz["s_sent"]
    s_lf = ts_npz["s_life"]
    s_ct = ts_npz["s_cat"]
    ex20 = ts_npz["th_ex20"]
    abs20 = ts_npz["th_abs20"]
    th_n = ts_npz["th_n"]

    rows = []
    for i, d in enumerate(dts):
        if not ("2026-01-01" <= d <= cm.EVAL_END):
            continue
        act_ids = np.flatnonzero(th_act[i])
        if len(act_ids) == 0:
            continue
        order = act_ids[np.argsort(-tot[i, act_ids])]
        rec = {"trade_date": d}
        for rk in range(1, 4):
            if rk - 1 < len(order):
                ti = int(order[rk - 1])
                rec[f"top{rk}_theme"] = th_names[ti]
                rec[f"top{rk}_score"] = round(float(tot[i, ti]), 2)
                rec[f"top{rk}_flow"] = round(float(s_fl[i, ti]), 1)
                rec[f"top{rk}_trend"] = round(float(s_tr[i, ti]), 1)
                rec[f"top{rk}_sent"] = round(float(s_se[i, ti]), 1)
                rec[f"top{rk}_life"] = round(float(s_lf[i, ti]), 1)
                rec[f"top{rk}_cat"] = round(float(s_ct[i, ti]), 1)
                rec[f"top{rk}_abs20_pct"] = round(float(abs20[i, ti] * 100.0), 1)
                rec[f"top{rk}_n"] = int(th_n[i, ti])
            else:
                rec[f"top{rk}_theme"] = ""
                rec[f"top{rk}_score"] = 0.0
        rows.append(rec)
    df = pd.DataFrame(rows)
    df.to_csv(f"{cm.RD047_DIR}/rd047_2026_theme_timeline.csv", index=False)
    return df


def run_loto_and_loyo(tdf: pd.DataFrame, base_dr: np.ndarray, cal_dts: list[str], end_idx: int) -> dict:
    """
    Leave-One-Year-Out (LOYO) on daily returns + Leave-One-Theme-Out (LOTO) on closed trades.
    """
    if tdf.empty:
        return {"loyo": {}, "loto": {}}

    # LOYO on daily returns (2021..2026)
    loyo = {}
    dts_eval = np.array(cal_dts[:end_idx + 1])
    dr_eval = base_dr[:end_idx + 1]
    start_m = dts_eval >= "2021-04-06"
    for yr in ("2021", "2022", "2023", "2024", "2025", "2026"):
        m = start_m & (~np.char.startswith(dts_eval, yr))
        r = dr_eval[m]
        nav = float(np.prod(1.0 + r))
        cagr = (nav ** (cm.TRD_DAYS_YEAR / max(1, len(r))) - 1.0) * 100.0
        loyo[f"ex_{yr}"] = {"nav": round(nav, 4), "cagr_pct": round(cagr, 2)}

    # LOTO on closed trades: find top-contributing (most profitable) and largest-count themes
    grp = tdf.groupby("entry_theme")["net_ret"].agg(["count", "sum", "mean"]).sort_values("sum", ascending=False)
    best_th = str(grp.index[0]) if len(grp) else "NONE"
    most_freq_th = str(grp.sort_values("count", ascending=False).index[0]) if len(grp) else "NONE"
    loto = {
        "best_profit_theme": best_th,
        "best_profit_theme_n": int(grp.loc[best_th, "count"]) if best_th in grp.index else 0,
        "best_profit_theme_sum_ret": round(float(grp.loc[best_th, "sum"] * 100.0), 2) if best_th in grp.index else 0.0,
        "most_freq_theme": most_freq_th,
    }
    for tag_k, excl_th in [("ex_best_theme", best_th), ("ex_most_freq_theme", most_freq_th)]:
        sub = tdf[tdf["entry_theme"] != excl_th]
        rets = sub["net_ret"].to_numpy(float)
        n_s = float(sub["slots_cap"].iloc[0]) if (not sub.empty and "slots_cap" in sub.columns) else 5.0
        nav_approx = float(np.prod(1.0 + rets / max(1.0, n_s))) if len(rets) else 1.0
        loto[tag_k] = {
            "excluded_theme": excl_th,
            "n_trades": int(len(rets)),
            "wr_pct": round(float((rets > 0).mean() * 100.0), 2) if len(rets) else 0.0,
            "mean_pct": round(float(rets.mean() * 100.0), 2) if len(rets) else 0.0,
            "approx_nav": round(nav_approx, 4),
        }
    return {"loyo": loyo, "loto": loto}


def main():
    t0 = time.time()
    bench_ctx = cm.load_bench_and_v20(end_dt=cm.EVAL_END)
    nm_map = cm.load_stock_names()
    ctx = s2.load_sim_context("full")
    ts_full = np.load(f"{cm.CACHE_DIR}/theme_scores_full.npz")
    pre_a = s2.precompute_track_a_cands(ctx, f"{cm.CACHE_DIR}/kpl_events_full.parquet")
    end_idx = ctx["cal_dts"].index(cm.EVAL_END)
    start_idx = ctx["cal_dts"].index("2021-04-06")
    bond_dr = bench_ctx["bond_511010_dr"]

    # 1. Build 2026 Theme Timeline CSV
    tl_df = build_2026_theme_timeline(ctx, ts_full)
    print(f"[Step3] Saved 2026 theme timeline: {len(tl_df)} days")

    # 2. Run 5 Representative Models & Save 2026 Trade Details CSV
    rep_specs = [
        ("A_Inst_T75_hold20_K5_3y_Bond_30bp", s2.generate_track_a_cands(ctx, pre_a, 75.0, 2, 2, 3.0, "inst_core", False), "hold20", None, None, False, 5, 0.0030, bond_dr),
        ("A_L_T75_ma20_K5_3y_Cash_30bp", s2.generate_track_a_cands(ctx, pre_a, 75.0, 2, 2, 3.0, "leader", False), "ma20", 0.15, 50.0, False, 5, 0.0030, None),
        ("A_StaticSW3_T80_ma20_K5_3y_Cash_30bp", s2.generate_track_a_cands(ctx, pre_a, 80.0, 2, 2, 3.0, "leader", True), "ma20", 0.15, 50.0, True, 5, 0.0030, None),
        ("B_Dyn_T70_ma10_K3_Cash_30bp", s2.generate_track_b_cands(ctx, 70.0, 3.0, "dyn_high"), "ma10", 0.12, None, False, 3, 0.0030, None),
        ("B_SwUp_T75_ma10_K3_Cash_30bp", s2.generate_track_b_cands(ctx, 75.0, 3.0, "dyn_switch_or_up"), "ma10", 0.12, None, False, 3, 0.0030, None),
    ]

    rep_sims = {}
    trade_details_2026 = []
    loto_loyo_res = {}
    v20_res = {}
    mtm_checks = {}

    for nm, cands, ex, tr, fd, f_st, sl, fee, bdr in rep_specs:
        sim = s2.simulate_portfolio(ctx, cands, exit_mode=ex, trail_dd=tr, fade_thr=fd, fade_use_static=f_st, n_slots=sl, fee_rt=fee, bond_dr=bdr, start_eval_idx=start_idx, end_idx=end_idx)
        rep_sims[nm] = sim
        tdf = sim["closed_trades"].copy()
        if not tdf.empty:
            tdf["strategy_id"] = nm
            tdf["name"] = tdf["code"].map(nm_map).fillna("")
            sub26 = tdf[tdf["buy_date"] >= "2026-01-01"].copy()
            trade_details_2026.append(sub26)
        loto_loyo_res[nm] = run_loto_and_loyo(tdf, sim["dr"], ctx["cal_dts"], end_idx)
        v20_res[nm] = cm.compute_v20_corr_and_blend(sim["dr"], bench_ctx, start_dt=cm.WF_START, end_dt=cm.EVAL_END)
        mtm_nav = float(np.prod(1.0 + sim["dr"]))
        mtm_checks[nm] = {"mtm_nav": round(mtm_nav, 6), "n_closed": int(len(tdf)), "n_open_end": int(sim["n_open_end"])}

    tr26_all = pd.concat(trade_details_2026, ignore_index=True) if trade_details_2026 else pd.DataFrame()
    tr26_all.to_csv(f"{cm.RD047_DIR}/rd047_2026_trades_detail.csv", index=False)

    # 3. 2026 Four-Wave Forensic Breakdown
    waves = [
        ("2026_04_06_Tech", "2026-04-01", "2026-06-30", ["KPL:通信", "KPL:芯片", "KPL:算力", "KPL:元器件", "KPL:电阻电容", "KPL:覆铜板", "SW3:印制电路板", "SW3:被动元件", "SW3:通信网络设备及器件"]),
        ("2026_07_08_Pharma", "2026-07-01", "2026-08-31", ["KPL:医药", "SW3:化学制剂", "SW3:医疗研发外包"]),
        ("2026_08_09_Agri", "2026-08-01", "2026-09-30", ["KPL:农业", "SW3:种子", "SW3:生猪养殖"]),
        ("2026_10_11_Robot", "2026-10-01", "2026-11-24", ["KPL:机器人概念", "SW3:机器人", "KPL:家电"]),
    ]
    wave_forensics = {}
    for w_nm, s_d, e_d, watch_ths in waves:
        tl_w = tl_df[tl_df["trade_date"].between(s_d, e_d)]
        th_stats = {}
        for th_n in watch_ths:
            if th_n not in ctx["all_theme_names"]:
                continue
            ti = ctx["all_theme_names"].index(th_n)
            idx_w = [i for i, d in enumerate(ctx["cal_dts"]) if s_d <= d <= e_d and ts_full["th_active"][i, ti]]
            if not idx_w:
                continue
            scs = ts_full["total_score"][idx_w, ti]
            max_i = idx_w[int(np.argmax(scs))]
            th_stats[th_n] = {
                "max_score": round(float(scs.max()), 1),
                "max_date": ctx["cal_dts"][max_i],
                "days_ge_70": int((scs >= 70.0).sum()),
                "days_ge_75": int((scs >= 75.0).sum()),
                "days_ge_80": int((scs >= 80.0).sum()),
            }
        strat_w = {}
        for nm in ("A_Inst_T75_hold20_K5_3y_Bond_30bp", "A_L_T75_ma20_K5_3y_Cash_30bp", "B_Dyn_T70_ma10_K3_Cash_30bp", "B_SwUp_T75_ma10_K3_Cash_30bp"):
            sub = tr26_all[(tr26_all["strategy_id"] == nm) & tr26_all["buy_date"].between(s_d, e_d)]
            if sub.empty:
                strat_w[nm] = {"n": 0, "wr_pct": 0.0, "mean_pct": 0.0, "top_trades": []}
            else:
                top_s = sub.sort_values("net_ret", ascending=False).head(4)[["code", "name", "buy_date", "exit_date", "hold_days", "net_ret", "entry_theme"]]
                strat_w[nm] = {
                    "n": int(len(sub)),
                    "wr_pct": round(float((sub["net_ret"] > 0).mean() * 100.0), 1),
                    "mean_pct": round(float(sub["net_ret"].mean() * 100.0), 2),
                    "top_trades": top_s.to_dict("records"),
                }
        wave_forensics[w_nm] = {
            "window": f"{s_d} ~ {e_d}",
            "n_days": int(len(tl_w)),
            "watch_themes": th_stats,
            "strategy_trades": strat_w,
        }

    # 4. Physical Truncation Check (<= 2024-12-31) on Full Simulation Daily Returns!
    ctx_tr = s2.load_sim_context("trunc24")
    ts_tr = np.load(f"{cm.CACHE_DIR}/theme_scores_trunc24.npz")
    pre_a_tr = s2.precompute_track_a_cands(ctx_tr, f"{cm.CACHE_DIR}/kpl_events_trunc24.parquet")
    end_idx_tr = ctx_tr["cal_dts"].index("2024-12-31")
    start_idx_tr = ctx_tr["cal_dts"].index("2021-04-06")
    bench_tr = cm.load_bench_and_v20(end_dt="2024-12-31")

    c_a_tr = s2.generate_track_a_cands(ctx_tr, pre_a_tr, 75.0, 2, 2, 3.0, "leader", False)
    sim_a_tr = s2.simulate_portfolio(ctx_tr, c_a_tr, "ma20", 0.15, 50.0, False, 5, 0.0030, None, start_idx_tr, end_idx_tr)
    c_i_tr = s2.generate_track_a_cands(ctx_tr, pre_a_tr, 75.0, 2, 2, 3.0, "inst_core", False)
    sim_i_tr = s2.simulate_portfolio(ctx_tr, c_i_tr, "hold20", None, None, False, 5, 0.0030, bench_tr["bond_511010_dr"], start_idx_tr, end_idx_tr)
    c_b_tr = s2.generate_track_b_cands(ctx_tr, 75.0, 3.0, "dyn_switch_or_up")
    sim_b_tr = s2.simulate_portfolio(ctx_tr, c_b_tr, "ma10", 0.12, None, False, 3, 0.0030, None, start_idx_tr, end_idx_tr)

    n_tr = end_idx_tr + 1
    diff_a = float(np.max(np.abs(rep_sims["A_L_T75_ma20_K5_3y_Cash_30bp"]["dr"][:n_tr] - sim_a_tr["dr"][:n_tr])))
    diff_i = float(np.max(np.abs(rep_sims["A_Inst_T75_hold20_K5_3y_Bond_30bp"]["dr"][:n_tr] - sim_i_tr["dr"][:n_tr])))
    diff_b = float(np.max(np.abs(rep_sims["B_SwUp_T75_ma10_K3_Cash_30bp"]["dr"][:n_tr] - sim_b_tr["dr"][:n_tr])))

    tn_f = json.load(open(f"{cm.CACHE_DIR}/theme_names_full.json"))["all_theme_names"]
    tn_t = json.load(open(f"{cm.CACHE_DIR}/theme_names_trunc24.json"))["all_theme_names"]
    f_idx_map = {nm: i for i, nm in enumerate(tn_f)}
    t_cols = [f_idx_map[nm] for nm in tn_t]
    diff_theme_sc = float(np.max(np.abs(ts_full["total_score"][:n_tr, t_cols] - ts_tr["total_score"])))
    si_f = np.searchsorted(ctx["stocks"], ctx_tr["stocks"])
    diff_stk_sc = float(np.max(np.abs(ts_full["stk_dyn_score"][:n_tr, si_f] - ts_tr["stk_dyn_score"])))

    trunc_proof = {
        "cutoff_date": "2024-12-31",
        "n_days": n_tr,
        "theme_score_max_abs_diff": diff_theme_sc,
        "stock_dyn_score_max_abs_diff": diff_stk_sc,
        "track_a_leader_dr_max_abs_diff": diff_a,
        "track_a_inst_bond_dr_max_abs_diff": diff_i,
        "track_b_wave2_dr_max_abs_diff": diff_b,
        "all_zero_diff_passed": (diff_theme_sc == 0.0 and diff_stk_sc == 0.0 and diff_a == 0.0 and diff_i == 0.0 and diff_b == 0.0),
    }

    # 5. Grid Plateau & DSR
    grid_df = pd.read_csv(f"{cm.RD047_DIR}/rd047_grid.csv")
    all_sh = grid_df["WF_OOS_sharpe"].dropna().tolist()
    best_id = str(grid_df.sort_values("FULL_5Y_nav", ascending=False).iloc[0]["strategy_id"])
    dsr_best = cm.deflated_sharpe_ratio(rep_sims["A_Inst_T75_hold20_K5_3y_Bond_30bp"]["dr"], len(grid_df), all_sh)

    # 6. Benchmarks
    csi_bench = cm.evaluate_daily_series(bench_ctx["csi300_dr"][:end_idx + 1], bench_ctx)
    bond_bench = cm.evaluate_daily_series(bench_ctx["bond_511010_dr"][:end_idx + 1], bench_ctx)

    audit = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "verdict": "FALSIFIED_NO_GO",
        "verdict_summary": "0/83 configs beat 1.0x 5Y NAV (max 0.2292x, best Sharpe -0.892). Scoring detects 2026 waves & 002242 dynamic switch, but buying >=70/75/80 themes systematically mean-reverts and loses across all years 2021-2026.",
        "grid_summary": {
            "total_configs": int(len(grid_df)),
            "configs_5y_nav_gt_1": int((grid_df["FULL_5Y_nav"] > 1.0).sum()),
            "configs_wf_nav_gt_1": int((grid_df["WF_OOS_nav"] > 1.0).sum()),
            "best_5y_nav_id": best_id,
            "best_5y_nav": round(float(grid_df["FULL_5Y_nav"].max()), 4),
            "median_5y_nav": round(float(grid_df["FULL_5Y_nav"].median()), 4),
            "best_2022_ret_pct": round(float(grid_df["Y2022_ret_pct"].max()), 2),
        },
        "dsr_best": dsr_best,
        "truncation_proof": trunc_proof,
        "mtm_checks": mtm_checks,
        "benchmarks": {"csi300": csi_bench, "bond_511010": bond_bench},
        "representative_metrics": grid_df[grid_df["strategy_id"].isin([r[0] for r in rep_specs])].to_dict("records"),
        "loto_loyo": loto_loyo_res,
        "v20_corr_and_blends": v20_res,
        "wave_2026_forensics": wave_forensics,
    }
    with open(f"{cm.RD047_DIR}/rd047_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print(f"[Step3 DONE in {time.time()-t0:.1f}s | RSS={cm.rss_mb()}MB]")
    print("Truncation proof:", trunc_proof)
    print("Grid summary:", audit["grid_summary"])
    print("V20 corr (A_Inst_T75_hold20):", v20_res["A_Inst_T75_hold20_K5_3y_Bond_30bp"]["corr_all_days"], v20_res["A_Inst_T75_hold20_K5_3y_Bond_30bp"]["blends"])
    print("LOTO/LOYO (A_Inst_T75_hold20):", loto_loyo_res["A_Inst_T75_hold20_K5_3y_Bond_30bp"])


if __name__ == "__main__":
    main()
