#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD041 Step 4:
1. Merge red-team forensics + instant-seal exclusion audit into rd041_audit.json (Verdict -> FALSIFIED).
2. Generate 2 crisp pure-Chinese visual charts.
3. Build strict V19.1 pure-Chinese Feishu payload, run local audit (--dry-run),
   or publish/verify online under 证伪回测与避坑墓碑 (QiDewdTkJiquokkbbo6cWr3Fn6f)
   and incrementally update Hub (ZTaudjSqtoaj71xTPSLciMcdnLb) + manifest.

Zero yfinance (D12). Zero edits to production/V20 docs.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import argparse
import fcntl
import json
import sqlite3
import sys
import time
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
DATA_DIR = f"{ROOT}/sim-portfolio/data"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd041_day0_firstboard_sweep_20261126"
CACHE_DIR = f"{OUT_DIR}/_cache"

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import wf_scorecard_engine as wf
import rd041_step3_wf_scorecard_and_stress as s3
import _rd041_feishu_helpers as h

DOC_TITLE = "第零天首板扫板实证"
MANIFEST_KEY = "rd041_day0_firstboard_sweep"
CHART1_PATH = f"{OUT_DIR}/chart1_rd041_trap_and_tracks.png"
CHART2_PATH = f"{OUT_DIR}/chart2_rd041_stress_and_v20.png"

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Hiragino Sans GB", "STHeiti", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def compute_instant_seal_audit() -> dict:
    """Compute exact impact of excluding unfillable <=09:31 / <=09:35 zero-open instant seals."""
    cache_p = f"{CACHE_DIR}/rd041_instant_seal_audit.json"
    if os.path.exists(cache_p):
        with open(cache_p, "r", encoding="utf-8") as f:
            return json.load(f)

    v20_ctx = wf.load_v20_reference_context(BASE_DIR)
    df = pd.read_parquet(f"{CACHE_DIR}/rd041_fb_master_pit.parquet")
    con = sqlite3.connect(f"file:{DATA_DIR}/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    zt_nm = pd.read_sql("SELECT DISTINCT trade_date, sec_code, sec_name FROM zt_micro_tape", con)
    con.close()
    nm_map = {(str(d)[:10], str(c).zfill(6)): str(n) for d, c, n in zip(zt_nm["trade_date"], zt_nm["sec_code"], zt_nm["sec_name"])}
    seal_map = {(str(d)[:10], str(c).zfill(6)): (int(hh), int(ob)) for d, c, hh, ob in zip(df["buy_date"], df["code"], df["audit_only_seal_hhmm"], df["audit_only_open_cnt"])}

    out = {}
    specs = [
        ("A1_PreCat_All_T1O", "any_pre_cat", 50, 35, ("top5", 75)),
        ("A4_FN_PrePos_T1O", "fn_pre_pos", 40, 30, (70, 75, "top5")),
    ]
    for name, mask_col, mw, mwr, ths in specs:
        sub = df[(df["buy_date"] <= "2026-11-11") & (df[mask_col] == 1)].copy()
        fcols = [c for c in s3.CAUSAL_FEATURES if c in sub.columns]
        sub["exit_date"] = sub["E1_T1Open_exit_date"].astype(str).str[:10]
        sub["exit_hhmm"] = sub["E1_T1Open_exit_hhmm"].astype(int)
        sub["gross_ret"] = sub["E1_T1Open_gross_ret"].astype(float)
        sub["buy_hhmm"] = 935
        sub["can_buy"] = sub["gross_ret"].notna() & (sub["exit_date"] > sub["buy_date"]) & (sub["exit_date"] <= "2026-11-16")
        sub["is_yizi"] = False
        sub = sub[sub["can_buy"]].copy().reset_index(drop=True)
        res = wf.run_wf_scorecard_new_strategy(
            sub, feature_cols=fcols, v20_ctx=v20_ctx, wf_start_date="2023-01-03", end_date="2026-11-11",
            min_warmup_trades=mw, min_warmup_trades_rare=mwr, min_warmup_months=18,
            recalc_freq="daily", top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0,
            shrink_tau=20.0, fee_rt=0.0030, gross_ret_col="gross_ret",
            thresholds=ths, eval_v20_patch=False, perm_n=0,
        )
        out[name] = {}
        for th_raw in ths:
            th = f"abs_{th_raw}" if isinstance(th_raw, int) else th_raw
            sl = res["threshold_results"][th]["slot_df"].copy()
            d_col = "buy_date" if "buy_date" in sl.columns else "entry_date"
            sl["nm"] = [nm_map.get((str(d)[:10], str(c)), "") for d, c in zip(sl[d_col], sl["code"])]
            sl["shhmm"] = [seal_map.get((str(d)[:10], str(c)), (-1, -1))[0] for d, c in zip(sl[d_col], sl["code"])]
            sl["obcnt"] = [seal_map.get((str(d)[:10], str(c)), (-1, -1))[1] for d, c in zip(sl[d_col], sl["code"])]
            m931 = (sl["is_zt"] == 1) & (sl["shhmm"] <= 931) & (sl["obcnt"] == 0)
            m935 = (sl["is_zt"] == 1) & (sl["shhmm"] <= 935) & (sl["obcnt"] == 0)
            sl_931, sl_935 = sl[~m931], sl[~m935]
            out[name][th] = {
                "n_all": int(len(sl)),
                "n_brk": int((sl["is_zt"] == 0).sum()),
                "n_st_pit": int(sl["nm"].str.contains("ST|退", regex=True).sum()),
                "n_seal_le0931_ob0": int(m931.sum()),
                "n_seal_le0935_ob0": int(m935.sum()),
                "drop931_n": int(len(sl_931)),
                "drop931_nav_30bp": round(float(np.prod(1.0 + sl_931["net_ret"])), 4),
                "drop931_nav_80bp": round(float(np.prod(1.0 + sl_931["net_ret"] - 0.005)), 4),
                "drop935_n": int(len(sl_935)),
                "drop935_wr_pct": round(float((sl_935["net_ret"] > 0).mean() * 100.0), 1),
                "drop935_mean_pct": round(float(sl_935["net_ret"].mean() * 100.0), 2),
                "drop935_nav_30bp": round(float(np.prod(1.0 + sl_935["net_ret"])), 4),
                "drop935_nav_80bp": round(float(np.prod(1.0 + sl_935["net_ret"] - 0.005)), 4),
            }
    with open(cache_p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return out


def update_audit_with_redteam() -> tuple[dict, dict, pd.DataFrame]:
    """Consolidate redteam forensics + instant-seal audit into rd041_audit.json."""
    audit_path = f"{OUT_DIR}/rd041_audit.json"
    with open(audit_path, "r", encoding="utf-8") as f:
        audit = json.load(f)
    with open(f"{CACHE_DIR}/rd041_redteam_forensics.json", "r", encoding="utf-8") as f:
        fore = json.load(f)
    inst = compute_instant_seal_audit()
    grid = pd.read_csv(f"{OUT_DIR}/rd041_grid.csv")

    audit["redteam_forensics_summary"] = {
        "A4_abs70": fore["A4_FN_PrePos_T1O"]["abs_70"],
        "A1_top5": fore["A1_PreCat_All_T1O"]["top5"],
        "A6_abs75": fore["A6_Day0Theme_Gap2_T1O"]["abs_75"],
    }
    audit["instant_seal_exclusion_audit"] = inst
    audit["passing_strict_before_redteam"] = audit.get("passing_strict_tracks", [])
    audit["passing_strict_count"] = 0
    audit["passing_strict_tracks"] = []
    audit["verdict"] = "FALSIFIED"
    audit["redteam_disqualification_reasons"] = [
        "All 13 Track B variations (10cm/20cm/Gap2-8/W2S, T1O/T1C/T2C/StreakHold) fail 50% adverse selection (med NAV <= 0.66x) and hurt V20.",
        "Track A intraday flash news suffers 52.73% reverse causality (published after first seal time).",
        "A4_FN_PrePos_T1O (abs_70): 17/62 trades (27.4%) seal <=09:35 with 0 opens; dropping those collapses NAV from 2.416x to 1.030x (30bp) and 0.822x (80bp); DSR(147)=0.850 < 0.95; hurts V20 by -11.1% (delta=0.8891).",
        "A1_PreCat_All_T1O (top5): 17/40 trades (42.5%) seal <=09:35 with 0 opens; dropping those collapses NAV from 2.169x to 1.062x (30bp) and 0.947x (80bp); DSR(147)=0.857 < 0.95; V20 empty-slot only 13 trades in 4 years.",
        "A6_Day0Theme_Gap2_T1O (abs_75): AS50_30=1.000x, AS50_80=0.752x, liquid filter n=44 -> 0.986x, DSR(147)=0.549.",
    ]

    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(s3.sanitize_json(audit), f, ensure_ascii=False, indent=2, allow_nan=False)
    return audit, fore, grid


def generate_charts(audit: dict, fore: dict, grid: pd.DataFrame):
    step2 = audit["step2_baseline_and_trap_diag"]
    trap = step2["micro_tape_trap_audit"]
    inst = audit["instant_seal_exclusion_audit"]

    # --- Chart 1: Micro-Tape Survivorship Trap & 5-Track WF vs AS50 Collapse ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.4), dpi=160)
    fig.patch.set_facecolor("#FFFFFF")

    cats = ["主板09点45前封死", "主板10点前零开板", "20cm09点45前封死", "20cm10点前零开板"]
    fake_vals = [
        trap["10cm"]["Seal<=0945"]["fake_sealed_only_T1O"]["mean_pct"],
        trap["10cm"]["Seal<=1000_ZeroOpen"]["fake_sealed_only_T1O"]["mean_pct"],
        trap["20cm"]["Seal<=0945"]["fake_sealed_only_T1O"]["mean_pct"],
        trap["20cm"]["Seal<=1000_ZeroOpen"]["fake_sealed_only_T1O"]["mean_pct"],
    ]
    real_full = [
        trap["10cm"]["Seal<=0945"]["imputed_stress"]["T1O_brk32_fill100"]["net30_pct"],
        trap["10cm"]["Seal<=1000_ZeroOpen"]["imputed_stress"]["T1O_brk32_fill100"]["net30_pct"],
        trap["20cm"]["Seal<=0945"]["imputed_stress"]["T1O_brk32_fill100"]["net30_pct"],
        trap["20cm"]["Seal<=1000_ZeroOpen"]["imputed_stress"]["T1O_brk32_fill100"]["net30_pct"],
    ]
    real_adv70 = [
        trap["10cm"]["Seal<=0945"]["imputed_stress"]["T1O_brk32_fill70"]["net30_pct"],
        trap["10cm"]["Seal<=1000_ZeroOpen"]["imputed_stress"]["T1O_brk32_fill70"]["net30_pct"],
        trap["20cm"]["Seal<=0945"]["imputed_stress"]["T1O_brk32_fill70"]["net30_pct"],
        trap["20cm"]["Seal<=1000_ZeroOpen"]["imputed_stress"]["T1O_brk32_fill70"]["net30_pct"],
    ]
    real_adv50_80 = [
        trap["10cm"]["Seal<=0945"]["imputed_stress"]["T1O_brk32_fill50"]["net80_pct"],
        trap["10cm"]["Seal<=1000_ZeroOpen"]["imputed_stress"]["T1O_brk32_fill50"]["net80_pct"],
        trap["20cm"]["Seal<=0945"]["imputed_stress"]["T1O_brk32_fill50"]["net80_pct"],
        trap["20cm"]["Seal<=1000_ZeroOpen"]["imputed_stress"]["T1O_brk32_fill50"]["net80_pct"],
    ]

    x = np.arange(len(cats))
    w = 0.20
    b1 = ax1.bar(x - 1.5 * w, fake_vals, width=w, color="#94A3B8", label="只看封死库（零炸板幻觉）")
    ax1.bar(x - 0.5 * w, real_full, width=w, color="#3B82F6", label="补回32.5%炸板全成交")
    ax1.bar(x + 0.5 * w, real_adv70, width=w, color="#F59E0B", label="好板70%成交+烂板必买")
    b4 = ax1.bar(x + 1.5 * w, real_adv50_80, width=w, color="#DC2626", label="好板50%成交+千八滑点")
    ax1.axhline(0.0, color="#111827", linewidth=1.0)
    ax1.set_xticks(x)
    ax1.set_xticklabels(cats, fontsize=9)
    ax1.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax1.set_ylabel("次日开盘卖单笔平均净回报 (%)", fontsize=10)
    ax1.set_title("一、早盘扫板漏掉炸板分母的虚高与逆向排板崩塌", fontsize=11, fontweight="bold", pad=10)
    ax1.set_ylim(-2.9, 4.6)
    ax1.legend(loc="upper left", fontsize=8, frameon=True)
    ax1.grid(axis="y", linestyle="--", alpha=0.35)
    for bars in (b1, b4):
        for bar in bars:
            yv = bar.get_height()
            va = "bottom" if yv >= 0 else "top"
            off = 0.08 if yv >= 0 else -0.10
            ax1.text(bar.get_x() + bar.get_width() / 2, yv + off, f"{yv:+.2f}%", ha="center", va=va, fontsize=8, fontweight="bold")

    best_by_tid = {r["track_id"]: r for r in audit["best_summary_sorted"]}
    r_tracks = [
        ("主板连板B4", "B4_10cm_All_Stk"),
        ("20cm连板B7", "B7_20cm_All_Stk"),
        ("新题材A6", "A6_Day0Theme_Gap2_T1O"),
        ("正快讯A4", "A4_FN_PrePos_T1O"),
        ("全催化A1", "A1_PreCat_All_T1O"),
    ]
    r_labels = [x[0] for x in r_tracks]
    nav_100 = [best_by_tid[x[1]]["nav_wf"] for x in r_tracks]
    nav_as50 = [best_by_tid[x[1]]["as50_fb_med_nav"] for x in r_tracks]
    nav_as50_80 = [
        audit["adverse_selection_mc500"]["B4_10cm_All_Stk"]["best_50_with_fb_80bp"]["med_nav"],
        audit["adverse_selection_mc500"]["B7_20cm_All_Stk"]["best_50_with_fb_80bp"]["med_nav"],
        fore["A6_Day0Theme_Gap2_T1O"]["abs_75"]["as50_80"]["med_nav"],
        fore["A4_FN_PrePos_T1O"]["abs_70"]["as50_80"]["med_nav"],
        fore["A1_PreCat_All_T1O"]["top5"]["as50_80"]["med_nav"],
    ]
    x2 = np.arange(len(r_labels))
    w2 = 0.25
    c1 = ax2.bar(x2 - w2, nav_100, width=w2, color="#64748B", label="理想全成交（含秒封）")
    ax2.bar(x2, nav_as50, width=w2, color="#F59E0B", label="好板50%成交（千三费）")
    c3 = ax2.bar(x2 + w2, nav_as50_80, width=w2, color="#DC2626", label="好板50%成交+千八滑点")
    ax2.axhline(1.0, color="#111827", linestyle="--", linewidth=1.1, label="盈亏平衡线 (1.0倍)")
    ax2.set_xticks(x2)
    ax2.set_xticklabels(r_labels, fontsize=9)
    ax2.set_yscale("log")
    ax2.set_yticks([0.03, 0.1, 0.5, 1.0, 5.0, 20.0])
    ax2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.2g}倍" if v < 1 else f"{v:.0f}倍"))
    ax2.minorticks_off()
    ax2.set_ylabel("四年样本外净值倍数（对数坐标）", fontsize=10)
    ax2.set_ylim(0.02, 32.0)
    ax2.set_title("二、多因子打分五路在好板半成交与滑点下的衰减", fontsize=11, fontweight="bold", pad=10)
    ax2.legend(loc="upper right", fontsize=8, frameon=True)
    ax2.grid(axis="y", linestyle="--", alpha=0.35)
    for bar in c1:
        yv = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width() / 2, yv * 1.12, f"{yv:.2f}倍", ha="center", va="bottom", fontsize=8, fontweight="bold")
    for bar in c3:
        yv = bar.get_height()
        if 0.50 <= yv <= 0.99:
            ax2.text(bar.get_x() + bar.get_width() / 2, yv * 0.72, f"{yv:.2f}倍", ha="center", va="top", fontsize=7.5, fontweight="bold", color="#FFFFFF")
        else:
            ax2.text(bar.get_x() + bar.get_width() / 2, yv * 1.14, f"{yv:.2f}倍", ha="center", va="bottom", fontsize=8, fontweight="bold")

    plt.tight_layout()
    plt.savefig(CHART1_PATH, dpi=160, facecolor="#FFFFFF")
    plt.close(fig)

    # --- Chart 2: A4 / A1 Peel-Off & V20 Empty-Slot Impact ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.4), dpi=160)
    fig.patch.set_facecolor("#FFFFFF")

    stages = ["纸面全成交\n(千三费)", "好板七成买到\n(千八滑点)", "好板五成买到\n(千八滑点)", "去09:31秒封\n(千八滑点)", "去09:35秒封\n(千八滑点)"]
    a4_vals = [
        best_by_tid["A4_FN_PrePos_T1O"]["nav_wf"],
        fore["A4_FN_PrePos_T1O"]["abs_70"]["as70_80"]["med_nav"],
        fore["A4_FN_PrePos_T1O"]["abs_70"]["as50_80"]["med_nav"],
        inst["A4_FN_PrePos_T1O"]["abs_70"]["drop931_nav_80bp"],
        inst["A4_FN_PrePos_T1O"]["abs_70"]["drop935_nav_80bp"],
    ]
    a1_vals = [
        best_by_tid["A1_PreCat_All_T1O"]["nav_wf"],
        fore["A1_PreCat_All_T1O"]["top5"]["as70_80"]["med_nav"],
        fore["A1_PreCat_All_T1O"]["top5"]["as50_80"]["med_nav"],
        inst["A1_PreCat_All_T1O"]["top5"]["drop931_nav_80bp"],
        inst["A1_PreCat_All_T1O"]["top5"]["drop935_nav_80bp"],
    ]
    xs = np.arange(len(stages))
    ws = 0.34
    ba4 = ax1.bar(xs - ws / 2, a4_vals, width=ws, color="#2563EB", label="盘前正快讯70分 (62笔)")
    ba1 = ax1.bar(xs + ws / 2, a1_vals, width=ws, color="#0D9488", label="盘前全催化前五 (40笔)")
    ax1.axhline(1.0, color="#DC2626", linestyle="--", linewidth=1.2, label="盈亏平衡线 (1.0倍)")
    ax1.set_xticks(xs)
    ax1.set_xticklabels(stages, fontsize=8.5)
    ax1.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.1f}"))
    ax1.set_ylabel("四年样本外净值倍数", fontsize=10)
    ax1.set_ylim(0.0, 2.85)
    ax1.set_title("三、盘前催化两路剥除难成交秒封与滑点后归零", fontsize=11, fontweight="bold", pad=10)
    ax1.legend(loc="upper right", fontsize=8.5, frameon=True)
    ax1.grid(axis="y", linestyle="--", alpha=0.35)
    for bars in (ba4, ba1):
        for bar in bars:
            yv = bar.get_height()
            if yv < 0.99:
                ax1.text(bar.get_x() + bar.get_width() / 2, yv - 0.08, f"{yv:.2f}", ha="center", va="top", fontsize=8.5, fontweight="bold", color="#FFFFFF")
            else:
                ax1.text(bar.get_x() + bar.get_width() / 2, yv + 0.05, f"{yv:.2f}", ha="center", va="bottom", fontsize=8.5, fontweight="bold")

    v_labels = ["10cm全池\n连板持股", "10cm全池\n次日开盘", "10cm强切\n弱转强次开", "盘前正快讯\n70分次开", "盘前全催化\n前五次开"]
    v_tids = ["B4_10cm_All_Stk", "B1_10cm_All_T1O", "B12_10cm_W2S_T1O", "A4_FN_PrePos_T1O", "A1_PreCat_All_T1O"]
    v_delta = [best_by_tid[t]["patch_delta_nav_ratio"] for t in v_tids]
    colors = ["#DC2626" if v < 0.99 else "#64748B" for v in v_delta]
    xv = np.arange(len(v_labels))
    bv = ax2.bar(xv, v_delta, width=0.52, color=colors)
    ax2.axhline(1.0, color="#111827", linestyle="--", linewidth=1.2, label="原版 V20.0 基准线 (1.000倍)")
    ax2.set_xticks(xv)
    ax2.set_xticklabels(v_labels, fontsize=9)
    ax2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.1f}"))
    ax2.set_ylabel("加入 V20 空仓位后的联合净值倍率", fontsize=10)
    ax2.set_ylim(0.0, 1.25)
    ax2.set_title("四、空仓补位不仅不加分反而挤占 V20 核心大肉单", fontsize=11, fontweight="bold", pad=10)
    ax2.legend(loc="upper left", fontsize=8.5, frameon=True)
    ax2.grid(axis="y", linestyle="--", alpha=0.35)
    for bar in bv:
        yv = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width() / 2, yv + 0.025, f"{yv:.3f}倍", ha="center", va="bottom", fontsize=9, fontweight="bold")

    plt.tight_layout()
    plt.savefig(CHART2_PATH, dpi=160, facecolor="#FFFFFF")
    plt.close(fig)


def build_feishu_payload(audit: dict, fore: dict) -> dict:
    s1 = audit["step1_pool_and_news_audit"]
    trap = audit["step2_baseline_and_trap_diag"]["micro_tape_trap_audit"]
    inst = audit["instant_seal_exclusion_audit"]
    best_by_tid = {r["track_id"]: r for r in audit["best_summary_sorted"]}

    n_10 = s1["pool_audit"]["non_yizi_10cm"]
    n_10_brk = s1["pool_audit"]["non_yizi_10cm_broken"]
    n_20 = s1["pool_audit"]["non_yizi_20cm"]
    n_20_brk = s1["pool_audit"]["non_yizi_20cm_broken"]
    rev_cnt = s1["news_audit"]["intraday_news_causality_audit_on_sealed"]["news_after_seal_reverse_causality"]
    rev_tot = s1["news_audit"]["intraday_news_causality_audit_on_sealed"]["n_sealed_with_intra_news"]

    a4_70 = fore["A4_FN_PrePos_T1O"]["abs_70"]
    a4_b = best_by_tid["A4_FN_PrePos_T1O"]
    a4_inst = inst["A4_FN_PrePos_T1O"]["abs_70"]

    a1_5 = fore["A1_PreCat_All_T1O"]["top5"]
    a1_b = best_by_tid["A1_PreCat_All_T1O"]
    a1_inst = inst["A1_PreCat_All_T1O"]["top5"]

    b4_b = best_by_tid["B4_10cm_All_Stk"]
    b4_80 = audit["adverse_selection_mc500"]["B4_10cm_All_Stk"]["best_50_with_fb_80bp"]["med_nav"]
    b7_b = best_by_tid["B7_20cm_All_Stk"]
    b7_80 = audit["adverse_selection_mc500"]["B7_20cm_All_Stk"]["best_50_with_fb_80bp"]["med_nav"]
    a6_75 = fore["A6_Day0Theme_Gap2_T1O"]["abs_75"]
    a6_b = best_by_tid["A6_Day0Theme_Gap2_T1O"]

    blocks = [
        h.T("第零天首板扫板实盘买不进也赚不到钱，所有做法全部没用。", bold=True, hl=True),
        h.T("六年全市场共出现89288次非一字首板摸板，计入炸板分母后全线失血。盘前快讯精选靠开盘五分钟内无开板秒封撑账，剔除后即归零。加进现役空仓还会撞掉大肉单，整体收益不升反降。"),
        h.T("下文先揭穿盘口库缺失炸板与盘中快讯倒果为因两大假象。再展示五路多因子在好板半成交与空仓碰撞下的实证真相。"),
        h.BL(),
        h.T("一、先纠两大致命数据幻觉", bold=True),
        h.B(f"全市场共{n_10}次主板摸板含{n_10_brk}次炸板，占比32.4%。创业科创板共{n_20}次首板摸板，含{n_20_brk}次炸板。"),
        h.B("微观盘口库只抓收盘封死涨停股，完全漏掉炸板失败样本。若照此回测会把纸面单笔收益抬成天价幻觉。"),
        h.B(f"主板早盘九点四五前封死只看封死库看似每笔高达2.19%。补齐炸板再按半成交加滑点变为回吐{abs(trap['10cm']['Seal<=0945']['imputed_stress']['T1O_brk32_fill50']['net80_pct']):.2f}%。"),
        h.B(f"盘中快讯同样存在严重倒果为因，不能当作买前依据。封死首板配对的{rev_tot}条盘中消息里{rev_cnt}条发在封板后。"),
        h.BL(),
        h.T("二、纯盘口与题材扫板全军覆没", bold=True),
        h.B("全量非一字主板次日开盘盲打每笔平均回吐0.52%。若遇好板半成交叠万分之八十滑点每笔回吐2.04%。"),
        h.B(f"纯盘口打分纸面最高的连板持股前五看似达到{b4_b['nav_wf']:.2f}倍。剔除前五只暴利黑马股后四年仅剩{b4_b['ex5_wf']:.2f}倍。"),
        h.B(f"模拟好板五成买进且烂板全买，净值缩水至{b4_b['as50_fb_med_nav']:.2f}倍。叠加滑点后连板持股直接萎缩至{b4_80:.2f}倍。"),
        h.B("创业科创板与弱转强等十三条纯盘口分支全部阵亡。好板半成交下净值全部跌破本金1.0倍。"),
        h.B(f"新题材前排龙头七十五分纸面看似有{a6_b['nav_wf']:.2f}倍。半成交加滑点跌回{a6_75['as50_80']['med_nav']:.2f}倍，带量过滤也仅0.99倍。"),
        h.BL(),
        h.T("三、盘前快讯精选拆穿秒封与碰撞真相", bold=True),
        h.B(f"盘前正快讯七十分四年合计只有{a4_b['n_trades_wf']}笔交易，样本偏小。纸面净值{a4_b['nav_wf']:.2f}倍，半成交加滑点勉强剩{a4_70['as50_80']['med_nav']:.2f}倍。"),
        h.B(f"模型实际专挑高开贴近涨停股票，实盘极难排进。这批赢家中有{a4_inst['n_seal_le0935_ob0']}笔开盘五分内秒封且全天零开板。"),
        h.B(f"保留全部炸板并剔除极速秒封，千三净值落至{a4_inst['drop935_nav_30bp']:.2f}倍。按实盘千八滑点口径算直接归落至{a4_inst['drop935_nav_80bp']:.2f}倍。"),
        h.B(f"盘前全催化前五名四年才{a1_b['n_trades_wf']}笔，其中{a1_inst['n_seal_le0935_ob0']}笔属秒封。剔除这批秒封并加滑点后净值破位至{a1_inst['drop935_nav_80bp']:.2f}倍。"),
        h.B("把盘前正快讯补进V20.0空仓会撞掉六笔核心连板。结果不仅未添收益反而拖累总净值逾一成一。"),
        h.BL(),
        h.T("四、明确结论与实战处置", bold=True),
        h.B("第零天首板扫板无论纯盘口还是盘前快讯均彻底淘汰。既不替代现役六策略也不作空仓日补位使用。"),
        h.B("现役V20.0继续只等次日分歧转一致的一进二买点。把九点半最拥挤的高炸板成本留给市场对手盘。"),
        h.BL(),
        h.BL(),
        h.BL(),
    ]

    t1_title = "表一 早盘盘口库漏掉炸板分母前后对比"
    t1_rows = [
        [h.C("早盘封板口径", True), h.C("只看封死库", True), h.C("补炸板半成交", True), h.C("半成交加滑点", True)],
        [h.C("主板九点四五前封死"), h.C("2.19%"), h.C("回吐1.19%"), h.C("回吐1.69%")],
        [h.C("主板十点前零开板"), h.C("2.84%"), h.C("回吐0.86%"), h.C("回吐1.36%")],
        [h.C("20cm九点四五前封死"), h.C("2.81%"), h.C("回吐1.78%"), h.C("回吐2.27%")],
        [h.C("20cm十点前零开板"), h.C("3.84%"), h.C("回吐1.26%"), h.C("回吐1.75%")],
    ]

    t2_title = "表二 五路第零天多因子样本外全套压力测试"
    t2_rows = [
        [h.C("策略分支", True), h.C("纸面全成交", True), h.C("半成交加滑点", True), h.C("加V20净值倍率", True)],
        [h.C("主板连板持股B4"), h.C(f"{b4_b['nav_wf']:.2f}倍"), h.C(f"{b4_80:.2f}倍"), h.C(f"{b4_b['patch_delta_nav_ratio']:.3f}倍")],
        [h.C("20cm连板持股B7"), h.C(f"{b7_b['nav_wf']:.2f}倍"), h.C(f"{b7_80:.2f}倍"), h.C(f"{b7_b['patch_delta_nav_ratio']:.3f}倍")],
        [h.C("新题材前排龙头A6"), h.C(f"{a6_b['nav_wf']:.2f}倍"), h.C(f"{a6_75['as50_80']['med_nav']:.2f}倍"), h.C(f"{a6_b['patch_delta_nav_ratio']:.3f}倍")],
        [h.C("盘前正快讯A4"), h.C(f"{a4_b['nav_wf']:.2f}倍"), h.C(f"{a4_70['as50_80']['med_nav']:.2f}倍"), h.C(f"{a4_b['patch_delta_nav_ratio']:.3f}倍")],
        [h.C("盘前全催化A1"), h.C(f"{a1_b['nav_wf']:.2f}倍"), h.C(f"{a1_5['as50_80']['med_nav']:.2f}倍"), h.C(f"{a1_b['patch_delta_nav_ratio']:.3f}倍")],
    ]

    t3_title = "表三 盘前催化两路剔除难成交秒封与多重校正"
    t3_rows = [
        [h.C("检验维度", True), h.C("盘前正快讯70分", True), h.C("盘前全催化前五", True), h.C("淘汰判定", True)],
        [h.C("四年样本数与炸板"), h.C(f"{a4_b['n_trades_wf']}笔/8炸板"), h.C(f"{a1_b['n_trades_wf']}笔/4炸板"), h.C("样本偏稀")],
        [h.C("五分内零开板秒封"), h.C(f"{a4_inst['n_seal_le0935_ob0']}笔"), h.C(f"{a1_inst['n_seal_le0935_ob0']}笔"), h.C("极难排队买到")],
        [h.C("剔秒封千三净值"), h.C(f"{a4_inst['drop935_nav_30bp']:.2f}倍"), h.C(f"{a1_inst['drop935_nav_30bp']:.2f}倍"), h.C("近似原地踏步")],
        [h.C("剔秒封千八净值"), h.C(f"{a4_inst['drop935_nav_80bp']:.2f}倍"), h.C(f"{a1_inst['drop935_nav_80bp']:.2f}倍"), h.C("实盘预期负收益")],
        [h.C("百四七路紧缩保真"), h.C(f"{a4_70['dsr']['dsr']*100:.1f}%"), h.C(f"{a1_5['dsr']['dsr']*100:.1f}%"), h.C("未过九十五门槛")],
    ]

    payload = {
        "title": DOC_TITLE,
        "img_path": CHART1_PATH,
        "blocks": blocks,
        "tables": [(t1_title, t1_rows), (t2_title, t2_rows), (t3_title, t3_rows)],
        "sections_tables": [
            (t1_title, t1_rows, CHART1_PATH),
            (t2_title, t2_rows, None),
            (t3_title, t3_rows, CHART2_PATH),
        ],
    }
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Build audit/charts and run strict Feishu payload validation without uploading.")
    parser.add_argument("--publish", action="store_true", help="Publish to Feishu Invalid Hub & update manifest.")
    args = parser.parse_args()
    if not args.dry_run and not args.publish:
        args.dry_run = True

    audit, fore, grid = update_audit_with_redteam()
    print(f"[Audit] Verdict={audit['verdict']} | trunc_all_pass={audit['truncation_20241231_all_pass']} | peak_rss={audit['peak_rss_mb']} MB")

    generate_charts(audit, fore, grid)
    assert os.path.exists(CHART1_PATH) and os.path.exists(CHART2_PATH), "Charts missing!"
    print(f"[Charts] Saved {CHART1_PATH} & {CHART2_PATH}")

    payload = build_feishu_payload(audit, fore)
    h.audit_payload_strict(payload, require_img=True)
    print("[Feishu Audit] Local strict V19.1 + plain-Chinese audit PASSED (0 errors)!")

    if args.dry_run and not args.publish:
        return

    with open(h.s6.LOCK_PATH, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        doc_id, node_token = h.s9.find_or_create_child_node(h.INVALID_PARENT_NODE, DOC_TITLE)
        print(f"[Feishu] node={node_token} doc={doc_id}")
        done, fail = h.write_doc_with_interleaved_charts(doc_id, payload["blocks"], payload["sections_tables"])
        if fail > 0:
            raise RuntimeError(f"Feishu block write had {fail} failures!")
        time.sleep(0.8)
        ver = h.s9.verify_document_v191(doc_id, DOC_TITLE, expected_tables_count=len(payload["tables"]), has_img=True)
        raw_res = h.s6.api(f"{h.s6.BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET")
        raw_txt = raw_res.get("data", {}).get("content", "")
        h.audit_online_raw_text(raw_txt)
        print(f"[Feishu Online Verify] PASSED! raw_chars={len(raw_txt)} | tables={ver['tables_count']} | images={ver['images_count']}")

        b4_80 = audit["adverse_selection_mc500"]["B4_10cm_All_Stk"]["best_50_with_fb_80bp"]["med_nav"]
        a4_drop935_80 = audit["instant_seal_exclusion_audit"]["A4_FN_PrePos_T1O"]["abs_70"]["drop935_nav_80bp"]
        hub_row = [
            DOC_TITLE,
            "6年89288笔首板全样本",
            f"全池与盘口半成交崩至{b4_80:.2f}倍；盘前快讯去秒封滑点剩{a4_drop935_80:.2f}倍且撞毁V20",
            "永久禁做第零天扫板与补位",
        ]
        hub_res = h.update_hub_incremental(h.INVALID_HUB_DOC, "证伪回测与避坑墓碑", hub_row)
        print(f"[Feishu Hub] Updated {h.INVALID_HUB_DOC} -> total_rows={hub_res['total_rows']} | row={hub_res['added_row']}")

        wiki_url = f"https://my.feishu.cn/wiki/{node_token}"
        pub_res = {
            "title": DOC_TITLE,
            "verdict": audit["verdict"],
            "parent_node_token": h.INVALID_PARENT_NODE,
            "hub_doc_id": h.INVALID_HUB_DOC,
            "node_token": node_token,
            "doc_id": doc_id,
            "wiki_url": wiki_url,
            "hub_total_rows": hub_res["total_rows"],
            "online_raw_chars": len(raw_txt),
            "published_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(f"{OUT_DIR}/feishu_publish_result.json", "w", encoding="utf-8") as f:
            json.dump(pub_res, f, ensure_ascii=False, indent=2)

        with open(h.s6.MANIFEST_PATH, "r", encoding="utf-8") as f:
            man = json.load(f)
        man.setdefault("sub_reports", {})[MANIFEST_KEY] = {
            "title": DOC_TITLE,
            "node_token": node_token,
            "obj_token": doc_id,
            "parent_node_token": h.INVALID_PARENT_NODE,
            "wiki_url": wiki_url,
            "published_at": pub_res["published_at"],
        }
        with open(h.s6.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(man, f, ensure_ascii=False, indent=2)
        fcntl.flock(lf, fcntl.LOCK_UN)
    print(f"[DONE] Published {wiki_url}")


if __name__ == "__main__":
    main()
