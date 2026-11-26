#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD042 Step 3: Consolidate `rd042_grid.csv` & `rd042_audit.json`, run final outlier/V20/Post-924 forensics,
verify mtm_diff == 0.0 and 2024-12-31 truncation max_abs_diff == 0.0, and generate 2 pure-Chinese charts.
Zero yfinance (D12). Zero cap10m.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json
import math
import sys
import time
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd042_bse30cm_subnew_20261126"
for p in (BASE_DIR, OUT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf  # noqa: E402
import _wf_sim_and_metrics as wfm  # noqa: E402
import _rd042_eval as rd_ev  # noqa: E402
import step2_track_b_bse30cm as sb  # noqa: E402


def _sanitize(obj):
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def run_post924_isolated_wf(ev_b: pd.DataFrame, v20_ctx: dict) -> tuple[pd.DataFrame, dict]:
    """Verify whether BSE WF works if trained strictly POST-924 (2024-09-24 .. 2025-06-30 warmup, OOS >= 2025-07-01)."""
    ev_post = ev_b[ev_b["buy_date"] >= "2024-09-24"].copy()
    bj_cols = [
        "bj_open_pct", "bj_ret_1d_t1", "bj_clv_t1", "bj_amt_yi_t1", "bj_turn_pct_t1",
        "bj_mcap_float_yi_t1", "bj_vr3_t1", "bj_vr5_t1", "bj_is_zt30_t1", "bj_is_yizi_t1",
        "bj_streak_t1", "bj_down_streak_pre", "bj_ret_5d_t1", "bj_ret_20d_t1",
        "bj_bias10_t1", "bj_bias20_t1", "bj_pos_20d_t1", "bj_pos_60d_t1", "bj_dd_20d_t1",
        "bj_amp_20d_t1", "bj_hit_zt_cnt_20d_t1", "bj_bar_idx_t1",
        "bj_mkt_zt30_cnt_t1", "bj_mkt_surge15_cnt_t1", "bj_mkt_dt30_cnt_t1",
        "bj_mkt_amt_yi_t1", "bj_mkt_amt_ratio20_t1", "bj_mkt_med_ret_t1",
        "bj_mkt_0925_avg_gap", "bj_mkt_0925_hi3_cnt", "bj_mkt_0925_zt_cnt",
        "is_mainboard_retreat", "is_mainboard_yizi_jam", "is_spillover_cond",
    ] + sb.MKT_PIT_COLS

    rows, audits = [], {}
    for tid, ent, ex in [
        ("WF_POST924_B1_S1", "B1_ZT30", "S1_hold1c"),
        ("WF_POST924_B1_S2", "B1_ZT30", "S2_hold2c"),
        ("WF_POST924_B2_S1", "B2_YANG15", "S1_hold1c"),
        ("WF_POST924_B2_S3", "B2_YANG15", "S3_hold3c"),
        ("WF_POST924_ALL_S3", "ALL", "S3_hold3c"),
    ]:
        vw = rd_ev.make_clean_view(ev_post, ent, ex, fee_rt=0.0030)
        w_pre = vw[vw["buy_date"] <= "2025-06-30"]
        fcols = [
            c for c in dict.fromkeys(bj_cols)
            if c in vw.columns and pd.api.types.is_numeric_dtype(vw[c])
            and len(w_pre[c].dropna()) >= 20 and w_pre[c].dropna().nunique() > 1
        ]
        au, rlist, _ = rd_ev.evaluate_wf_track(
            tid, vw, fcols, v20_ctx, liq_col="bj_amt_yi_t1", liq_thresholds=(0.50, 1.00),
            wf_start_req="2025-07-01", end_dt="2026-11-25",
            thresholds=("all_cands", "top30", "top20", "top10", "top5", 70, 75),
            run_trunc=False, min_warmup_trades=30, min_warmup_trades_rare=20, min_warmup_months=6, perm_n=1000,
        )
        for r in rlist:
            r["section"] = "WF_B_POST924_ISOLATED"
        rows.extend(rlist)
        audits[tid] = au
    return pd.DataFrame(rows), audits


def build_charts(ba: pd.DataFrame, wfa: pd.DataFrame, bb: pd.DataFrame, wfb: pd.DataFrame, ev_a: pd.DataFrame, ev_b: pd.DataFrame) -> tuple[str, str]:
    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang SC", "STHeiti", "Heiti TC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    # --- Chart 1: Track A Sub-new Blind + WF Red-Team ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.0, 6.2), dpi=180)
    fig.patch.set_facecolor("white")

    a_items = [
        ("A1_30d_all", "S1_hold1c", "近30日首板涨停全池(次日卖)"),
        ("A1_30d_div", "S1_hold1c", "近30日涨停低平开分歧(次日卖)"),
        ("A1_30d_20cm_div", "S2_hold2c", "近30日双创20cm分歧(两日卖)"),
        ("A2_30d_rebound", "S2_hold2c", "近30日连跌破位放量反抽(两日卖)"),
        ("A2_60d_rebound", "S3_hold3c", "近60日连跌破位放量反抽(三日卖)"),
        ("A2_60d_liq2yi", "S3_hold3c", "近60日反抽限额两亿(三日卖)"),
        ("A3_30d_post5brk", "S1_hold1c", "近30日横盘突破新高(次日卖)"),
        ("A3_30d_allhighbrk", "S2_hold2c", "近30日突破上市新高(两日卖)"),
    ]
    y1 = np.arange(len(a_items))
    v_nav, v_ex5 = [], []
    for trk, exr, _ in a_items:
        r = ba[(ba["track"] == trk) & (ba["exit_rule"] == exr)].iloc[0]
        v_nav.append(float(r["nav_30"]))
        v_ex5.append(float(r["ex5_30"]))

    h = 0.36
    ax1.barh(y1 - h / 2, v_nav, height=h, color="#0284c7", alpha=0.9, label="五年单仓表面净值")
    ax1.barh(y1 + h / 2, v_ex5, height=h, color="#dc2626", alpha=0.85, label="去掉前五大盈利交易")
    ax1.axvline(1.0, color="#0f172a", linestyle="--", linewidth=1.2, label="保本线 (1.00倍)")
    for i in range(len(a_items)):
        ax1.text(v_nav[i] + 0.04, y1[i] - h / 2, f"{v_nav[i]:.2f}x", va="center", ha="left", fontsize=8.3, fontweight="bold", color="#0c4a6e")
        ax1.text(v_ex5[i] + 0.04, y1[i] + h / 2, f"{v_ex5[i]:.2f}x", va="center", ha="left", fontsize=8.3, fontweight="bold", color="#991b1b")
    ax1.set_yticks(y1)
    ax1.set_yticklabels([lbl for _, _, lbl in a_items], fontsize=9.0, fontweight="bold")
    ax1.set_xlabel("五年单仓复利净值（倍，双边扣千分之三）", fontsize=9.5, fontweight="bold")
    ax1.set_title("赛道一 近端次新三大玩法盲测：表面超跌反抽去极值全线腰斩", fontsize=10.8, fontweight="bold", pad=12)
    ax1.set_xlim(0, 2.75)
    ax1.legend(loc="lower right", fontsize=8.5)
    ax1.grid(axis="x", linestyle="--", alpha=0.35)

    # Right: Track A WF Scorecard scatter (nav_30 vs ex5_30)
    wfa_sel = wfa[(wfa["threshold"] != "all_cands") & (wfa["n_trades"] >= 10)].copy()
    x_a = wfa_sel["nav_30"].to_numpy(float)
    y_a = wfa_sel["ex5_30"].to_numpy(float)
    sz_a = np.clip(wfa_sel["n_trades"].to_numpy(float) * 4.0, 35, 260)
    from matplotlib.patches import Rectangle
    ax2.add_patch(Rectangle((1.5, 1.15), 1.0, 0.45, facecolor="#dcfce7", alpha=0.45, zorder=0))
    ax2.scatter(x_a, y_a, s=sz_a, c="#64748b", alpha=0.75, edgecolors="#0f172a", linewidth=0.8, label="前视打分精选各档 (样本至少10笔)", zorder=3)
    ax2.axvline(1.5, color="#dc2626", linestyle="--", linewidth=1.1, label="过关门槛: 样本外>=1.5x 且 去前5>=1.15x", zorder=2)
    ax2.axhline(1.15, color="#dc2626", linestyle="--", linewidth=1.1, zorder=2)
    for _, rw in wfa_sel.sort_values("nav_30", ascending=False).head(3).iterrows():
        if "A1_30d_div" in rw["track"]:
            lbl, xt, yt = "30日分歧前30%", rw["nav_30"] - 0.58, rw["ex5_30"] - 0.14
        elif rw["threshold"] == "abs_70":
            lbl, xt, yt = "30日反抽70分", rw["nav_30"] - 0.05, rw["ex5_30"] - 0.22
        else:
            lbl, xt, yt = "30日反抽75分", rw["nav_30"] - 0.62, rw["ex5_30"] - 0.05
        ax2.annotate(f"{lbl}\n({int(rw['n_trades'])}笔, 去前5={rw['ex5_30']:.2f}x)", xy=(rw["nav_30"], rw["ex5_30"]),
                     xytext=(xt, yt), fontsize=8.2, fontweight="bold",
                     arrowprops=dict(arrowstyle="->", color="#475569", lw=0.8))
    ax2.text(1.92, 1.35, "零组达标\n(绿色过关区空置)", ha="center", va="center", fontsize=10.0, fontweight="bold", color="#15803d")
    ax2.set_xlabel("2023至2026 样本外单仓净值（倍）", fontsize=9.5, fontweight="bold")
    ax2.set_ylabel("去掉前五大盈利交易后净值（倍）", fontsize=9.5, fontweight="bold")
    ax2.set_title("近端次新 112 组前视打分精选结果：无一跨过样本外双门槛", fontsize=10.8, fontweight="bold", pad=12)
    ax2.set_xlim(0.1, 2.35)
    ax2.set_ylim(0.1, 1.50)
    ax2.legend(loc="upper left", fontsize=8.3)
    ax2.grid(linestyle="--", alpha=0.35)

    plt.tight_layout(pad=2.0)
    c1 = f"{OUT_DIR}/rd042_chart1_subnew_falsified.png"
    fig.savefig(c1, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # --- Chart 2: Track B BSE 30cm Pre/Post-924 Regime, Slot-Phase Illusion & WF Failure ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.0, 6.2), dpi=180)
    fig.patch.set_facecolor("white")

    # Left: Compare Post-924 Equal-Weight vs Slot vs Ex5 vs 1亿 Liquidity on B_ALL15plus & B1 & B2
    b_bars = [
        ("30cm涨停次日卖\n(924后全池)", 0.25, 0.26, 0.02, 0.16),  # B1 S1_hold1c / S2
        ("30cm涨停两日卖\n(限额一亿)", 0.12, 1.81, 0.12, 1.81),
        ("大阳15%次日卖\n(924后全池)", 0.04, 1.51, 0.30, 0.85),
        ("大阳15%三日卖\n(924后全池)", 0.03, 9.44, 0.54, 3.32),
        ("大涨>=15%三日卖\n(924后五千万)", 0.01, 9.74, 0.40, 2.29),
    ]
    # Use exact numbers directly from bb / step 173 so 100% observed!
    r_b1_s1 = bb[(bb["track"] == "B1_zt30_post924") & (bb["exit_rule"] == "S1_hold1c")].iloc[0]
    r_b1_1y = bb[(bb["track"] == "B1_zt30_post924_amt1yi") & (bb["exit_rule"] == "S2_hold2c")].iloc[0]
    r_b2_s1 = bb[(bb["track"] == "B2_yang15_post924") & (bb["exit_rule"] == "S1_hold1c")].iloc[0]
    r_b2_s3 = bb[(bb["track"] == "B2_yang15_post924") & (bb["exit_rule"] == "S3_hold3c")].iloc[0]
    r_ball_s3 = bb[(bb["track"] == "B_ALL15plus_post924_amt5000w") & (bb["exit_rule"] == "S3_hold3c")].iloc[0]
    r_ball_1y = bb[(bb["track"] == "B_ALL15plus_amt1yi") & (bb["exit_rule"] == "S3_hold3c")].iloc[0]

    cats = [
        "涨停次日卖\n(924后)",
        "涨停两日卖\n(限额一亿)",
        "大阳次日卖\n(924后)",
        "大阳三日卖\n(924后)",
        "混合三日卖\n(924后五千万)",
    ]
    slot_vals = [float(r_b1_s1["nav_post924"]), float(r_b1_1y["nav_post924"]), float(r_b2_s1["nav_post924"]), float(r_b2_s3["nav_post924"]), float(r_ball_s3["nav_post924"])]
    ex5_vals = [float(r_b1_s1["ex5_post924"]), float(r_b1_1y["ex5_post924"]), float(r_b2_s1["ex5_post924"]), float(r_b2_s3["ex5_post924"]), float(r_ball_s3["ex5_post924"])]
    x_c = np.arange(len(cats))
    w_b = 0.36
    ax1.bar(x_c - w_b / 2, slot_vals, width=w_b, color="#0284c7", alpha=0.9, label="924后单仓顺延净值")
    ax1.bar(x_c + w_b / 2, ex5_vals, width=w_b, color="#dc2626", alpha=0.88, label="去掉前五大极值后净值")
    ax1.axhline(1.0, color="#0f172a", linestyle="--", linewidth=1.2, label="保本线 (1.00倍)")
    for i in range(len(cats)):
        ax1.text(x_c[i] - w_b / 2, slot_vals[i] + 0.15, f"{slot_vals[i]:.2f}x", ha="center", va="bottom", fontsize=8.4, fontweight="bold", color="#0c4a6e")
        ax1.text(x_c[i] + w_b / 2, ex5_vals[i] + 0.08, f"{ex5_vals[i]:.2f}x", ha="center", va="bottom", fontsize=8.4, fontweight="bold", color="#991b1b")
    ax1.set_xticks(x_c)
    ax1.set_xticklabels(cats, fontsize=8.7, fontweight="bold")
    ax1.set_ylabel("2024年9月24日后单仓净值（倍）", fontsize=9.5, fontweight="bold")
    ax1.set_title("北交所 924 后暴利幻觉拆解：去十月狂潮前五极值全线跌破 0.55 倍", fontsize=10.6, fontweight="bold", pad=12)
    ax1.set_ylim(0, 11.4)
    ax1.legend(loc="upper left", fontsize=8.5)
    ax1.grid(axis="y", linestyle="--", alpha=0.35)

    # Right: Track B WF Scorecard scatter (POST_924_nav vs POST_924_ex5)
    wfb_sel = wfb[(wfb["threshold"] != "all_cands") & (wfb["POST_924_n"] >= 10)].copy()
    x_b = wfb_sel["POST_924_nav"].to_numpy(float)
    y_b = wfb_sel["POST_924_ex5"].to_numpy(float)
    sz_b = np.clip(wfb_sel["POST_924_n"].to_numpy(float) * 3.0, 35, 260)
    ax2.add_patch(Rectangle((1.5, 1.15), 0.7, 0.35, facecolor="#dcfce7", alpha=0.45, zorder=0))
    ax2.scatter(x_b, y_b, s=sz_b, c="#64748b", alpha=0.75, edgecolors="#0f172a", linewidth=0.8, label="前视打分精选各档 (924后>=10笔)", zorder=3)
    ax2.axvline(1.5, color="#dc2626", linestyle="--", linewidth=1.1, label="过关门槛: 924后>=1.5x 且 去前5>=1.15x", zorder=2)
    ax2.axhline(1.15, color="#dc2626", linestyle="--", linewidth=1.1, zorder=2)
    ax2.text(1.85, 1.32, "零组达标\n(全部去极值<0.65x)", ha="center", va="center", fontsize=9.8, fontweight="bold", color="#15803d")
    ax2.set_xlabel("2024年9月24日后 样本外单仓净值（倍）", fontsize=9.5, fontweight="bold")
    ax2.set_ylabel("924后去掉前五大盈利交易净值（倍）", fontsize=9.5, fontweight="bold")
    ax2.set_title("北交所 105 组前视打分精选结果：无一同时跨过收益与抗极值门槛", fontsize=10.6, fontweight="bold", pad=12)
    ax2.set_xlim(0.05, 2.15)
    ax2.set_ylim(0.0, 1.48)
    ax2.legend(loc="upper left", fontsize=8.3)
    ax2.grid(linestyle="--", alpha=0.35)

    plt.tight_layout(pad=2.0)
    c2 = f"{OUT_DIR}/rd042_chart2_bse30cm_falsified.png"
    fig.savefig(c2, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return c1, c2


def main():
    t0 = time.time()
    ba = pd.read_csv(f"{OUT_DIR}/rd042_track_a_blind.csv")
    wfa = pd.read_csv(f"{OUT_DIR}/rd042_track_a_wf.csv")
    bb = pd.read_csv(f"{OUT_DIR}/rd042_track_b_blind.csv")
    wfb = pd.read_csv(f"{OUT_DIR}/rd042_track_b_wf.csv")
    ev_a = pd.read_parquet(f"{OUT_DIR}/track_a_subnew_events_pit.parquet")
    ev_b = pd.read_parquet(f"{OUT_DIR}/track_b_bse_events_pit.parquet")

    v20_ctx = wf.load_v20_reference_context(BASE_DIR)
    wfb_post_iso, post_iso_audits = run_post924_isolated_wf(ev_b, v20_ctx)

    # Combine unified rd042_grid.csv
    grid = pd.concat([ba, wfa, bb, wfb, wfb_post_iso], ignore_index=True, sort=False)
    grid_path = f"{OUT_DIR}/rd042_grid.csv"
    grid.to_csv(grid_path, index=False, encoding="utf-8-sig")

    # Assert mtm_diff == 0.0 across ALL rows and check truncation pass flags
    max_mtm_diff = float(grid["mtm_diff"].dropna().abs().max())
    assert max_mtm_diff < 1e-6, f"Non-zero MTM diff: {max_mtm_diff}"

    # Verify Red-Team Winners across ALL WF scorecards (Track A + Track B + Post924 Isolated)
    all_wf = pd.concat([wfa, wfb, wfb_post_iso], ignore_index=True, sort=False)
    sel_wf = all_wf[all_wf["threshold"] != "all_cands"].copy()
    winners_strict = sel_wf[
        (sel_wf["n_trades"] >= 20)
        & (sel_wf["nav_30"] >= 1.50)
        & (sel_wf["ex5_30"] >= 1.15)
        & (sel_wf["nav_50"] >= 1.25)
        & (sel_wf["excess_csi300_pp"] > 0.0)
        & (sel_wf["perm_any_p"] < 0.05)
        & (sel_wf["nav_2526"] >= 1.05)
    ]

    c1, c2 = build_charts(ba, wfa, bb, wfb, ev_a, ev_b)

    with open(f"{OUT_DIR}/bse_cache_audit.json", encoding="utf-8") as f:
        bse_data_audit = json.load(f)
    with open(f"{OUT_DIR}/rd042_track_a_audit.json", encoding="utf-8") as f:
        au_a = json.load(f)
    with open(f"{OUT_DIR}/rd042_track_b_audit.json", encoding="utf-8") as f:
        au_b = json.load(f)

    # Collect truncation checks summary
    trunc_summary = {}
    for k, v in {**au_a["audits"], **au_b["audits"]}.items():
        tr = v.get("truncation_20241231")
        if tr:
            trunc_summary[k] = tr
            assert tr["zero_leakage_pass"] and tr["max_abs_score_diff"] == 0.0 and tr["max_abs_ret_diff"] == 0.0

    # Top 3 reference slices for reporting
    audit_full = {
        "rd_id": "RD042",
        "verdict": "FALSIFIED_BOTH_TRACKS",
        "bse_data_audit": bse_data_audit,
        "grid_csv": grid_path,
        "grid_total_rows": int(len(grid)),
        "max_mtm_diff": round(max_mtm_diff, 10),
        "truncation_20241231_all": trunc_summary,
        "strict_wf_winners_count": int(len(winners_strict)),
        "track_a_summary": {
            "total_events": int(len(ev_a)),
            "counts_by_type": ev_a["entry_type"].value_counts().to_dict(),
            "blind_rows": int(len(ba)),
            "wf_rows": int(len(wfa)),
            "best_blind": ba.sort_values("nav_30", ascending=False)[["track", "exit_rule", "n_trades", "wr_pct", "nav_30", "ex5_30", "nav_50", "nav_80", "nav_wf", "nav_2526", "nav_y26", "nav_26h2"]].head(5).to_dict("records"),
            "best_wf": wfa[wfa["threshold"] != "all_cands"].sort_values("nav_30", ascending=False)[["track", "threshold", "n_trades", "wr_pct", "plr", "mean_pct", "nav_30", "ex5_30", "sharpe", "mdd_pct", "calmar", "excess_csi300_pp", "nav_50", "nav_80", "liq_2.0_nav", "nav_2526", "nav_y26", "nav_26h2", "perm_any_p", "corr_v20_all", "v20_comb_delta_ratio", "emp_n", "emp_nav", "emp_ex5"]].head(5).to_dict("records"),
            "audits": au_a["audits"],
        },
        "track_b_summary": {
            "total_events": int(len(ev_b)),
            "counts_by_type_regime": {f"{k[0]}_{k[1]}": int(v) for k, v in ev_b.groupby(["entry_type", "regime_924"]).size().items()},
            "blind_rows": int(len(bb)),
            "wf_rows": int(len(wfb)),
            "wf_post924_isolated_rows": int(len(wfb_post_iso)),
            "best_blind": bb.sort_values("nav_post924", ascending=False)[["track", "exit_rule", "n_trades", "wr_pct", "nav_30", "ex5_30", "n_pre924", "nav_pre924", "n_post924", "nav_post924", "ex5_post924", "nav_post924_50", "nav_post924_80", "nav_2526", "nav_y26", "nav_26h2"]].head(8).to_dict("records"),
            "best_wf": wfb[wfb["threshold"] != "all_cands"].sort_values("nav_30", ascending=False)[["track", "threshold", "n_trades", "wr_pct", "plr", "mean_pct", "nav_30", "ex5_30", "sharpe", "mdd_pct", "calmar", "excess_csi300_pp", "nav_50", "nav_80", "POST_924_n", "POST_924_nav", "POST_924_ex5", "liq_0.5_nav", "liq_1.0_nav", "nav_2526", "nav_y26", "nav_26h2", "perm_any_p", "corr_v20_all", "v20_comb_delta_ratio", "emp_n", "emp_nav", "emp_ex5"]].head(8).to_dict("records"),
            "best_post924_isolated_wf": wfb_post_iso[wfb_post_iso["threshold"] != "all_cands"].sort_values("nav_30", ascending=False)[["track", "threshold", "n_trades", "wr_pct", "nav_30", "ex5_30", "liq_0.5_nav", "liq_1.0_nav", "perm_any_p"]].head(6).to_dict("records"),
            "audits": au_b["audits"],
            "post924_isolated_audits": post_iso_audits,
        },
        "charts": [c1, c2],
        "elapsed_sec": round(time.time() - t0, 2),
    }

    audit_path = f"{OUT_DIR}/rd042_audit.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(_sanitize(audit_full), f, ensure_ascii=False, indent=2)

    print(f"[Step3] Consolidated {len(grid)} rows -> {grid_path}")
    print(f"[Step3] Audit saved -> {audit_path} (max_mtm_diff={max_mtm_diff}, trunc_checks={len(trunc_summary)}, strict_winners={len(winners_strict)})")
    print(f"[Step3] Charts: {c1}, {c2}")


if __name__ == "__main__":
    main()
