#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Finalize RD037 Audit JSON:
1. Verify BLIND_PK exact daily MTM reconciliation on trades exiting <= 2026-11-16 (expect max_diff < 1e-12).
2. Summarize 483-config WF multiple-testing pass rates.
3. Run Red-Team 50bps fee stress + neighborhood plateau checks (with exact daily MTM & V20 collision)
   on the top 4 WF specs (`Peer1B_OldYouziSM_T0_Open_H1`, `Peer2_RecActive_T1_Open_H1`,
   `Peer3_InstBig_T1_Open_H3`, `AllPeers_T1_Open_H1_Ge305`) + top `Missed_YiziOver` cells.
4. Persist complete `red_team_audit` & `summary_tables` into `rd037_audit.json` (Peak RSS < 2.0 GB).
"""
import gc
import json
import math
import os
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd
import pyarrow as pa

warnings.filterwarnings("ignore")

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
pa.set_cpu_count(1)
pa.set_io_thread_count(1)

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd037_1to2_peer_leaders_20261126"
CACHE_DIR = f"{OUT_DIR}/_cache"

for p in (BASE_DIR, OUT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm
import _wf_v20_patch as wfp
from rd037_step2_blind_pk_and_wf import _sanitize, eval_custom_windows


def verify_blind_mtm_completed(v20_ctx: dict) -> dict:
    bench_df = v20_ctx["bench"]
    cal_5y_bench = bench_df[bench_df["trade_date"].between("2021-11-16", "2026-11-16")].sort_values("trade_date").reset_index(drop=True)
    cal_dts_5y = cal_5y_bench["trade_date"].tolist()
    dt_idx_5y = {d: i for i, d in enumerate(cal_dts_5y)}

    raw_idx = json.load(open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))
    all_cal = sorted(raw_idx["sh000300"].keys())
    cal_5y_all = [d for d in all_cal if "2021-01-04" <= d <= "2026-11-25"]
    g_to_local_5y = {gi: dt_idx_5y[d] for gi, d in enumerate(cal_5y_all) if d in dt_idx_5y}

    max_diff_top1 = 0.0
    max_diff_top3 = 0.0
    n_checked_top1 = 0
    n_checked_top3 = 0

    for ap in ("Anchor_Live92", "Anchor_Wide_P1_Ge305", "Anchor_Missed_YiziOver", "Anchor_Missed_Untrig"):
        pk_p = pd.read_parquet(f"{CACHE_DIR}/anchor_peer_1to1_all.parquet", filters=[("anchor_pool", "==", ap)])
        for (pc, am, em, hh), grp in pk_p.groupby(["peer_class", "agg_mode", "entry_mode", "hold_h"], sort=False):
            if am not in ("Top1_Cascade", "Top3_EW"):
                continue
            sub = grp[(grp["can_buy"] == 1) & (grp["exit_date"].astype(str) <= "2026-11-16")].copy()
            if sub.empty:
                continue
            fee_rt = 0.0030
            sub["net_ret"] = (1.0 + sub["gross_ret"].astype(float)) * (1.0 - fee_rt) - 1.0
            sub["can_buy_hygiene"] = True
            mtm_list = []
            for s_json in sub["mtm_segs_json"]:
                arr = json.loads(s_json)
                loc = []
                for idx_k, (g_di, mult) in enumerate(arr):
                    li = g_to_local_5y.get(int(g_di))
                    m_val = float(mult) * (1.0 - fee_rt) if idx_k == 0 else float(mult)
                    if li is not None:
                        loc.append((li, m_val))
                mtm_list.append(tuple(loc))
            sub["mtm_pairs"] = mtm_list
            _, slot_df = wfm.select_single_slot_trades(sub, score_col="anchor_score", threshold=None, wf_only=False)
            _, mtm_diff = wfm.build_daily_mtm_returns(slot_df, cal_dts_5y, mtm_col="mtm_pairs")
            if am == "Top1_Cascade":
                max_diff_top1 = max(max_diff_top1, float(mtm_diff))
                n_checked_top1 += 1
            else:
                max_diff_top3 = max(max_diff_top3, float(mtm_diff))
                n_checked_top3 += 1
        del pk_p
        gc.collect()

    return {
        "n_checked_top1_cascade": n_checked_top1,
        "max_mtm_diff_top1_cascade_le_20261116": max_diff_top1,
        "n_checked_top3_ew": n_checked_top3,
        "max_mtm_diff_top3_ew_le_20261116": max_diff_top3,
        "pass": (max_diff_top1 < 1e-9 and max_diff_top3 < 1e-9),
    }


def eval_wf_top4_red_team(v20_ctx: dict) -> dict:
    bench_df = v20_ctx["bench"]
    wf_raw = pd.read_parquet(f"{CACHE_DIR}/wf_peer_candidates_all.parquet")

    feats_0925 = [
        "peer_ret_1d_t1", "peer_ret_5d_t1", "peer_ret_20d_t1",
        "peer_pos_20d_t1", "peer_pos_60d_t1", "peer_pos_250d_t1",
        "peer_dd_20d_t1", "peer_bias10_t1", "peer_bias20_t1", "peer_overhang_t1",
        "peer_zt20_t1", "peer_zt60_t1", "peer_cool_days_zt",
        "peer_open_pct_t0", "peer_open_minus_anc",
        "anchor_score", "anchor_s_prior", "anchor_s_quant", "anchor_open_pct",
        "anchor_p_sz", "anchor_rk_theme", "anchor_d1_tight", "anchor_front_lock", "anchor_yizi_cnt",
        "peer_kpl_on_t1", "peer_kpl_60", "peer_kpl_1y", "peer_kpl_3y",
        "peer_ind_ex5_t1", "peer_ind_ex20_t1", "peer_ind_rk20_t1", "peer_ind_zt_sh5_t1",
        "peer_free_mcap_log", "peer_amt20_log", "peer_vol_ratio5_t1", "peer_turn_5_20_t1",
        "peer_real_turn_t1", "peer_amp_20d_t1", "peer_zt_3y_t1", "peer_waves_3y_t1",
        "peer_yz3y_t1", "peer_yz1y_t1", "peer_comm_pct", "peer_xq_pct",
        "peer_lhb_bayes_t1", "peer_lhb_inst_t1", "peer_lhb_goodyz_t1",
        "is_20cm", "role_oldyz", "role_oldyz_sm", "role_recact", "role_inst", "role_ind1",
        "mkt_zt_cnt_t1", "mkt_zb_rate_t1", "mkt_zt_prem_t1", "mkt_amt_ratio20_t1",
        "mkt_ew_bias20_t1", "mkt_abv_ma20_t1", "mkt_0925_gap", "us_ixic_1d_on", "nt_v3_eod_t1",
    ]
    feats_t0_close = feats_0925 + ["anchor_zt_t0", "anchor_ret_t0", "peer_ret_1d_t0"]
    feats_t1_open = feats_t0_close + ["entry_open_pct"]

    raw_idx = json.load(open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))
    all_cal = sorted(raw_idx["sh000300"].keys())
    cal_5y_all = [d for d in all_cal if "2021-01-04" <= d <= "2026-11-25"]

    target_specs = [
        ("Peer1B_OldYouziSM_T0_Open_H1", "all_ge275", "role_oldyz_sm", "T0_Open", 1),
        ("Peer2_RecActive_T1_Open_H1", "all_ge275", "role_recact", "T1_Open", 1),
        ("Peer3_InstBig_T1_Open_H3", "all_ge275", "role_inst", "T1_Open", 3),
        ("AllPeers_T1_Open_H1_Ge305", "hf_ge305", None, "T1_Open", 1),
    ]
    thrs = ("top30", "top20", "top10", "top5", 65, 68, 70, 72, 75, 78, 80)

    out = {}
    for sp_name, anc_flt, role_col, em, h in target_specs:
        sub = wf_raw[wf_raw["entry_mode"] == em].copy()
        if anc_flt == "hf_ge305":
            sub = sub[sub["in_hf_ge305"] == 1]
        if role_col is not None:
            sub = sub[sub[role_col] == 1]
        sub["exit_date"] = sub[f"exit_date_H{h}"]
        sub["gross_ret"] = sub[f"gross_ret_H{h}"]
        sub = sub[sub["exit_date"].notna() & sub["gross_ret"].notna()].copy().reset_index(drop=True)

        fcols = feats_0925 if em == "T0_Open" else (feats_t0_close if em == "T0_Close" else feats_t1_open)
        if role_col is not None:
            fcols = [c for c in fcols if not c.startswith("role_")]
        rec_freq = "daily" if (role_col is None or h in (1, 2)) else "monthly"

        spec_res = {}
        for fee_bps in (30, 50):
            fee_rt = fee_bps / 10000.0
            res = wf.run_wf_scorecard_new_strategy(
                sub,
                feature_cols=fcols,
                v20_ctx=v20_ctx,
                wf_start_date="2023-01-03",
                end_date="2026-11-16",
                min_warmup_trades=80,
                min_warmup_trades_rare=60,
                min_warmup_months=18,
                recalc_freq=rec_freq,
                top_k=10,
                min_k=5,
                max_corr=0.65,
                min_t_stat=1.0,
                shrink_tau=20.0,
                fee_rt=fee_rt,
                gross_ret_col="gross_ret",
                tie_col="anchor_score",
                mtm_col=None,
                thresholds=thrs,
                eval_v20_patch=False,
                perm_n=500 if fee_bps == 30 else 0,
                seed=20261126,
            )
            actual_wf_start = res["meta"].get("wf_actual_start") or "2023-01-03"
            cal_act = bench_df[bench_df["trade_date"].between(actual_wf_start, "2026-11-16")].sort_values("trade_date").reset_index(drop=True)
            cal_dts_act = cal_act["trade_date"].tolist()
            dt_idx_act = {d: i for i, d in enumerate(cal_dts_act)}
            g_to_act = {gi: dt_idx_act[d] for gi, d in enumerate(cal_5y_all) if d in dt_idx_act}
            wins_act = [
                ("FULL_WF", actual_wf_start, "2026-11-16"),
                ("Y2025_2026", "2025-01-01", "2026-11-16"),
                ("Y2026", "2026-01-01", "2026-11-16"),
                ("Y2026_H2", "2026-07-01", "2026-11-16"),
            ]

            rows = []
            for th_key, tr in res["threshold_results"].items():
                slot_df = tr["slot_df"].copy()
                pass_df = tr["pass_df"].copy()
                if not slot_df.empty:
                    slot_df["mtm_pairs_act"] = [
                        tuple((g_to_act[int(g_di)], float(mult) * (1.0 - fee_rt) if ik == 0 else float(mult))
                              for ik, (g_di, mult) in enumerate(json.loads(s_json)) if int(g_di) in g_to_act)
                        for s_json in slot_df[f"mtm_segs_H{h}"]
                    ]
                else:
                    slot_df["mtm_pairs_act"] = []

                ev_exact = eval_custom_windows(
                    slot_df, pass_df, sub[sub["buy_date"] >= actual_wf_start],
                    bench_df, wins_act, mtm_col="mtm_pairs_act", perm_n=0
                )
                fw = ev_exact["windows"].get("FULL_WF", {})
                y26 = ev_exact["windows"].get("Y2026", {})
                h2 = ev_exact["windows"].get("Y2026_H2", {})

                vp_ratio = None
                vp_emp_nav = None
                if not pass_df.empty:
                    pass_df["mtm_pairs_act"] = [
                        tuple((g_to_act[int(g_di)], float(mult) * (1.0 - fee_rt) if ik == 0 else float(mult))
                              for ik, (g_di, mult) in enumerate(json.loads(s_json)) if int(g_di) in g_to_act)
                        for s_json in pass_df[f"mtm_segs_H{h}"]
                    ]
                    vp = wfp.simulate_v20_empty_slot_patch(
                        pass_df, v20_ctx=v20_ctx, wf_start_dt=actual_wf_start, end_dt="2026-11-16",
                        score_col="wf_score", patch_mtm_col="mtm_pairs_act",
                    )
                    vp_ratio = vp["mode1_strict_combined_no_peek"]["delta_nav_ratio_full_wf"]
                    vp_emp_nav = vp["mode2_empty_slot_standalone"]["windows"]["FULL_WF"].get("nav")

                rows.append({
                    "threshold": th_key,
                    "n_slot": fw.get("n", 0),
                    "wr_wf": fw.get("wr_pct", 0.0),
                    "plr_wf": fw.get("plr", 0.0),
                    "mean_wf": fw.get("mean_pct", 0.0),
                    "nav_wf": fw.get("nav", 1.0),
                    "ex5_wf": fw.get("ex_top5_nav", 1.0),
                    "mdd_wf": fw.get("daily_mdd_pct", 0.0),
                    "sharpe_wf": fw.get("daily_sharpe", 0.0),
                    "nav_2026": y26.get("nav", 1.0),
                    "nav_26h2": h2.get("nav", 1.0),
                    "perm_sd_p": tr["metrics"]["permutation_1000"].get("same_day_p_nav") if fee_bps == 30 else None,
                    "v20_comb_ratio": vp_ratio,
                    "v20_emp_nav": vp_emp_nav,
                    "mtm_diff": ev_exact["mtm_reconciliation_diff"],
                })
            spec_res[f"fee_{fee_bps}bps"] = rows
        out[sp_name] = spec_res

    del wf_raw
    gc.collect()
    return out


def eval_missed_yiziover_detail(v20_ctx: dict) -> dict:
    bench_df = v20_ctx["bench"]
    cal_5y_bench = bench_df[bench_df["trade_date"].between("2021-11-16", "2026-11-16")].sort_values("trade_date").reset_index(drop=True)
    cal_dts_5y = cal_5y_bench["trade_date"].tolist()
    dt_idx_5y = {d: i for i, d in enumerate(cal_dts_5y)}

    raw_idx = json.load(open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))
    all_cal = sorted(raw_idx["sh000300"].keys())
    cal_5y_all = [d for d in all_cal if "2021-01-04" <= d <= "2026-11-25"]
    g_to_local_5y = {gi: dt_idx_5y[d] for gi, d in enumerate(cal_5y_all) if d in dt_idx_5y}

    wins_5y = [
        ("FULL_5Y", "2021-11-16", "2026-11-16"),
        ("WF_2326", "2023-01-03", "2026-11-16"),
        ("Y2025_2026", "2025-01-01", "2026-11-16"),
        ("Y2026", "2026-01-01", "2026-11-16"),
        ("Y2026_H2", "2026-07-01", "2026-11-16"),
    ]

    pk_p = pd.read_parquet(f"{CACHE_DIR}/anchor_peer_1to1_all.parquet", filters=[("anchor_pool", "==", "Anchor_Missed_YiziOver")])
    out = {}
    for pc, em, hh in [
        ("Peer4_IndLeader1", "T0_Open", 1),
        ("Peer1C_OldYouzi_CSRC", "T1_Open", 3),
        ("Peer1A_OldYouzi_KPL", "T0_Open", 1),
        ("Peer3A_InstBigCap_KPL100", "T0_Open", 1),
    ]:
        grp = pk_p[(pk_p["peer_class"] == pc) & (pk_p["agg_mode"] == "Top1_Cascade") &
                   (pk_p["entry_mode"] == em) & (pk_p["hold_h"] == hh) & (pk_p["can_buy"] == 1)].copy()
        if grp.empty:
            continue
        cell_res = {}
        for fee_bps in (30, 50):
            fee_rt = fee_bps / 10000.0
            sub = grp.copy()
            sub["net_ret"] = (1.0 + sub["gross_ret"].astype(float)) * (1.0 - fee_rt) - 1.0
            sub["can_buy_hygiene"] = True
            sub["wf_score"] = sub["anchor_score"]
            sub["mtm_pairs"] = [
                tuple((g_to_local_5y[int(g_di)], float(mult) * (1.0 - fee_rt) if ik == 0 else float(mult))
                      for ik, (g_di, mult) in enumerate(json.loads(s_json)) if int(g_di) in g_to_local_5y)
                for s_json in sub["mtm_segs_json"]
            ]
            _, slot_df = wfm.select_single_slot_trades(sub, score_col="anchor_score", threshold=None, wf_only=False)
            ev = eval_custom_windows(slot_df, sub, sub, cal_5y_bench, wins_5y, mtm_col="mtm_pairs", perm_n=0)

            # Empty-slot WF 2023-2026 with exact MTM pairs
            cal_wf = bench_df[bench_df["trade_date"].between("2023-01-03", "2026-11-16")].sort_values("trade_date").reset_index(drop=True)
            cal_dts_wf = cal_wf["trade_date"].tolist()
            dt_idx_wf = {d: i for i, d in enumerate(cal_dts_wf)}
            g_to_wf = {gi: dt_idx_wf[d] for gi, d in enumerate(cal_5y_all) if d in dt_idx_wf}
            sub["mtm_pairs_wf"] = [
                tuple((g_to_wf[int(g_di)], float(mult) * (1.0 - fee_rt) if ik == 0 else float(mult))
                      for ik, (g_di, mult) in enumerate(json.loads(s_json)) if int(g_di) in g_to_wf)
                for s_json in sub["mtm_segs_json"]
            ]
            vp = wfp.simulate_v20_empty_slot_patch(
                sub, v20_ctx=v20_ctx, wf_start_dt="2023-01-03", end_dt="2026-11-16",
                respect_stier_waits=True, score_col="wf_score", patch_mtm_col="mtm_pairs_wf",
            )
            cell_res[f"fee_{fee_bps}bps"] = {
                "windows": ev["windows"],
                "v20_empty_wf": {
                    "n_patch_added": vp["mode1_strict_combined_no_peek"]["n_patch_added"],
                    "n_v20_skipped": vp["mode1_strict_combined_no_peek"]["n_v20_skipped_by_collision"],
                    "delta_nav_ratio_wf": vp["mode1_strict_combined_no_peek"]["delta_nav_ratio_full_wf"],
                    "emp_n": vp["mode2_empty_slot_standalone"]["n_standalone_empty_trades"],
                    "emp_wf": vp["mode2_empty_slot_standalone"]["windows"]["FULL_WF"],
                },
            }
        out[f"{pc}__{em}_H{hh}"] = cell_res
    del pk_p
    gc.collect()
    return out


def main():
    t0 = time.time()
    v20_ctx = wfp.load_v20_reference_context(BASE_DIR)
    df = pd.read_csv(f"{OUT_DIR}/rd037_peer_matrix.csv")
    audit = json.load(open(f"{OUT_DIR}/rd037_audit.json", encoding="utf-8"))

    # 1. Multiple testing breakdown across all 483 WF filtered configs
    wf = df[(df["track_type"] == "WF_SCORECARD") & (df["threshold"] != "all_cands")].copy()
    mt_483 = {
        "n_total_filtered_configs": int(len(wf)),
        "n_specs": int(wf["spec_name"].nunique()),
        "nav_wf_gt_1_5": int((wf["nav_wf"] > 1.5).sum()),
        "nav_wf_gt_2_0": int((wf["nav_wf"] > 2.0).sum()),
        "ex5_wf_gt_1_0": int((wf["ex5_wf"] > 1.0).sum()),
        "ex5_wf_gt_1_2": int((wf["ex5_wf"] > 1.2).sum()),
        "perm_sd_p_lt_0_05": int((wf["perm_sd_p"] < 0.05).sum()),
        "strict_pass_ex5gt1_2_and_perm005_and_v20gt1": int(
            ((wf["ex5_wf"] > 1.2) & (wf["perm_sd_p"] < 0.05) & (wf["v20_comb_ratio"] > 1.0)).sum()
        ),
        "strict_pass_ex5gt1_0_and_perm005_and_v20gt1": int(
            ((wf["ex5_wf"] > 1.0) & (wf["perm_sd_p"] < 0.05) & (wf["v20_comb_ratio"] > 1.0)).sum()
        ),
    }

    # 2. MTM verification on completed BLIND_PK trades
    mtm_verif = verify_blind_mtm_completed(v20_ctx)

    # 3. Top-4 WF Red-Team 50bps + neighborhood
    wf_red_team = eval_wf_top4_red_team(v20_ctx)

    # 4. Missed YiziOver exact detail
    missed_yizi_detail = eval_missed_yiziover_detail(v20_ctx)

    audit["red_team_audit"] = {
        "finalized_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "multiple_testing_483": mt_483,
        "blind_pk_mtm_completed_verif": mtm_verif,
        "top4_wf_neighborhood_and_50bps": wf_red_team,
        "missed_yiziover_30_vs_50bps": missed_yizi_detail,
    }
    rss_gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9
    audit["meta"]["finalize_peak_rss_gb"] = round(rss_gb, 3)

    with open(f"{OUT_DIR}/rd037_audit.json", "w", encoding="utf-8") as f:
        json.dump(_sanitize(audit), f, ensure_ascii=False, indent=2)

    print(f"[FINALIZED AUDIT] mtm_pass={mtm_verif['pass']} | top1_diff={mtm_verif['max_mtm_diff_top1_cascade_le_20261116']:.2e} | top3_diff={mtm_verif['max_mtm_diff_top3_ew_le_20261116']:.2e}")
    print(f"[MULTIPLE TESTING 483] {mt_483}")
    for sp, sd in wf_red_team.items():
        r30 = [r for r in sd["fee_30bps"] if r["threshold"] in ("top10", "top20", "70", 70, "75", 75)]
        r50 = {r["threshold"]: r for r in sd["fee_50bps"]}
        print(f"  [{sp}]")
        for r in r30:
            th = r["threshold"]
            r_s = r50.get(th, {})
            print(f"    thr={th}: 30bps nav={r['nav_wf']} ex5={r['ex5_wf']} mdd={r['mdd_wf']} p={r['perm_sd_p']} v20r={r['v20_comb_ratio']} -> 50bps nav={r_s.get('nav_wf')} ex5={r_s.get('ex5_wf')} v20r={r_s.get('v20_comb_ratio')}")
    print(f"Elapsed={time.time()-t0:.1f}s | Peak RSS={rss_gb:.3f} GB")
    assert rss_gb < 2.0, f"Peak RSS {rss_gb:.3f} GB >= 2.0 GB!"


if __name__ == "__main__":
    main()
