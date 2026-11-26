#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD045 Step 4: Consolidate rd045_grid.csv & rd045_audit.json + Generate 2 high-res Chinese PNG charts."""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"
import json, resource, sys, time
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
RD042_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd042_bse30cm_subnew_20261126"
RD045_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd045_abn_v2_bse_v2_refinement_20261126"


def _setup_font():
    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang SC", "STHeiti", "Heiti TC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def build_charts(t1_df: pd.DataFrame, t2_df: pd.DataFrame, fk: dict) -> tuple[str, str]:
    _setup_font()

    # --- Chart 1: Track 1 (卡异动 V2) Theme Continuation + Red-Team Waterfall ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.4, 6.4), dpi=180)
    fig.patch.set_facecolor("white")

    # Left: Buwen's Theme Continuation 4-group + No-MA5 contrast
    t_items = [
        ("OpenQual_G1_ThmUp", "二波题材升温且守5日线 (39/42笔)"),
        ("OpenQual_G2_ThmHighHold", "题材高位延续 (>=80%, 87/91笔)"),
        ("OpenQual_G3_ThmFade", "题材明显退潮 (<50%, 43笔)"),
        ("OpenQual_G4_LoneZhuang", "无主线助攻独苗庄股 (44笔)"),
        ("OpenAll_G1_ThmUp_NoMA5", "题材升温但未卡5日线 (67/70笔)"),
    ]
    y1 = np.arange(len(t_items))
    v_s7, v_s1 = [], []
    for k, _ in t_items:
        r7 = t1_df[(t1_df["track"] == k) & (t1_df["exit_rule"] == "S7_lianban")]
        r1 = t1_df[(t1_df["track"] == k) & (t1_df["exit_rule"] == "S1_hold1c")]
        v_s7.append(float(r7["nav_30"].iloc[0]) if not r7.empty else 0.0)
        v_s1.append(float(r1["nav_30"].iloc[0]) if not r1.empty else 0.0)

    h = 0.36
    ax1.barh(y1 - h / 2, v_s7, height=h, color="#0284c7", alpha=0.92, label="涨停持有至断板 (5年单仓)")
    ax1.barh(y1 + h / 2, v_s1, height=h, color="#64748b", alpha=0.85, label="次日收盘卖出 (5年单仓)")
    ax1.axvline(1.0, color="#dc2626", linestyle="--", linewidth=1.3, label="保本线 (1.00倍)")
    for i in range(len(t_items)):
        ax1.text(v_s7[i] + 0.14, y1[i] - h / 2, f"{v_s7[i]:.2f}x", va="center", ha="left", fontsize=8.4, fontweight="bold", color="#0c4a6e")
        ax1.text(v_s1[i] + 0.14, y1[i] + h / 2, f"{v_s1[i]:.2f}x", va="center", ha="left", fontsize=8.4, fontweight="bold", color="#334155")
    ax1.set_yticks(y1)
    ax1.set_yticklabels([lbl for _, lbl in t_items], fontsize=8.8, fontweight="bold")
    ax1.set_xlabel("五年单仓复利净值（倍，双边扣千分之三）", fontsize=9.4, fontweight="bold")
    ax1.set_title("赛道一：题材升温延续显著拉正方向，但仍须守死5日线", fontsize=10.8, fontweight="bold", pad=12)
    ax1.set_xlim(0, 8.6)
    ax1.legend(loc="upper right", fontsize=8.2, frameon=True)
    ax1.grid(axis="x", linestyle="--", alpha=0.35)

    # Right: Red-team audit across V2_A, V2_B, V2_C & OpenQual_G1_ThmUp
    r_vq = t1_df[(t1_df["track"] == "OpenQual_G1_ThmUp") & (t1_df["exit_rule"] == "S7_lianban")].iloc[0]
    r_va = t1_df[(t1_df["track"] == "V2_A_ThmUp_MA5_OpenM5P3") & (t1_df["exit_rule"] == "S2_hold2c")].iloc[0]
    r_vb = t1_df[(t1_df["track"] == "V2_B_Hug94_Stk3_Amt3_MA5") & (t1_df["exit_rule"] == "S7_lianban")].iloc[0]
    r_wf = t1_df[(t1_df["track"] == "WF_V2C_No100_Low_S1_abs_70") & (t1_df["exit_rule"] == "S1_hold1c")].iloc[0]
    oq_wf_s1 = [x for x in fk["t1"]["openqual_wf"] if x["exit"] == "S1_hold1c" and x["thr"] == "top20"][0]

    steps = [
        ("题材升温精选\n五年账面(断板)", float(r_vq["nav_30"]), "#16a34a"),
        ("题材升温精选\n去前五极值(5年)", float(r_vq["ex5_30"]), "#dc2626"),
        ("优质池内前视\n打分前20%(次收)", float(oq_wf_s1["nav_wf"]), "#b91c1c"),
        ("精确解禁开盘\n去前五极值(2日)", float(r_va["ex5_30"]), "#ef4444"),
        ("前一日尾盘贴线\n五年净值(仅8笔)", float(r_vb["nav_30"]), "#f59e0b"),
        ("强行并入现役\n总仓净值乘数", float(r_vq["v20_delta_ratio"]), "#991b1b"),
    ]
    x2 = np.arange(len(steps))
    vals2, cols2 = [s[1] for s in steps], [s[2] for s in steps]
    bars2 = ax2.bar(x2, vals2, width=0.55, color=cols2, alpha=0.92, edgecolor="white")
    ax2.axhline(1.0, color="#0f172a", linestyle="--", linewidth=1.2, label="过关生死线 (1.00倍)")
    for b, v in zip(bars2, vals2):
        if 0.45 <= v <= 1.05:
            ax2.text(b.get_x() + b.get_width() / 2, v * 0.5, f"{v:.2f}x", ha="center", va="center", fontsize=8.6, fontweight="bold", color="white")
        else:
            ax2.text(b.get_x() + b.get_width() / 2, v + 0.14, f"{v:.2f}x", ha="center", va="bottom", fontsize=8.6, fontweight="bold", color="#0f172a")
    ax2.set_xticks(x2)
    ax2.set_xticklabels([s[0] for s in steps], fontsize=8.0, fontweight="bold")
    ax2.set_ylabel("净值或对现役总仓乘数（倍）", fontsize=9.4, fontweight="bold")
    ax2.set_title("红队死刑解剖：去前五极值全跌破1倍，内嵌打分失灵且撞毁现役", fontsize=10.6, fontweight="bold", pad=12)
    ax2.set_ylim(0, 8.2)
    ax2.legend(loc="upper right", fontsize=8.2)
    ax2.grid(axis="y", linestyle="--", alpha=0.35)

    plt.tight_layout(pad=2.0)
    c1 = f"{RD045_DIR}/rd045_chart1_abn_v2_theme_and_redteam.png"
    fig.savefig(c1, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # --- Chart 2: Track 2 (北交所 30cm V2) Post-924 vs Ex-Oct24 & Liquidity Cliff ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.4, 6.4), dpi=180)
    fig.patch.set_facecolor("white")

    b_items = [
        ("B2_A2_Yang12_brk_1yi", "S3_hold3c", "跷跷板大阳突破\n(超1亿 3日卖)"),
        ("B2_A2_Yang12_brk_1yi", "S4_hold5c", "跷跷板大阳突破\n(超1亿 5日卖)"),
        ("B2_B2_Surge15_div63_5kw", "S3_hold3c", "15%大阳分歧低吸\n(5千万 3日卖)"),
        ("B2_B3_MA5_pullback_5kw", "S3_hold3c", "回踩5日线低吸\n(5千万 3日卖)"),
        ("B2_C_WF_5kw_top10", "S3_hold3c", "五因子前视打分\n(5千万 前10%)"),
        ("B2_C_ZeroFit_5kw", "S3_hold3c", "零拟合动量轮动\n(5千万 3日卖)"),
    ]
    x_b = np.arange(len(b_items))
    v_p9, v_eo, v_ex5 = [], [], []
    for tk, ex, _ in b_items:
        row = t2_df[(t2_df["track"] == tk) & (t2_df["exit_rule"] == ex)].iloc[0]
        v_p9.append(float(row["nav_p924"]))
        v_eo.append(float(row["nav_exoct"]))
        v_ex5.append(float(row["ex5_exoct"]))

    w = 0.27
    ax1.bar(x_b - w, v_p9, width=w, color="#0284c7", alpha=0.88, label="924全活水期 (含2024年10月)")
    ax1.bar(x_b, v_eo, width=w, color="#f59e0b", alpha=0.92, label="砍掉10月狂潮后常态期")
    ax1.bar(x_b + w, v_ex5, width=w, color="#dc2626", alpha=0.92, label="常态期再去前五极值")
    ax1.axhline(1.0, color="#0f172a", linestyle="--", linewidth=1.2, label="保本线 (1.00倍)")
    for i in range(len(b_items)):
        ax1.text(x_b[i] - w, v_p9[i] + 0.05, f"{v_p9[i]:.2f}", ha="center", va="bottom", fontsize=7.6, fontweight="bold", color="#0c4a6e")
        ax1.text(x_b[i], v_eo[i] + 0.05, f"{v_eo[i]:.2f}", ha="center", va="bottom", fontsize=7.6, fontweight="bold", color="#92400e")
        ax1.text(x_b[i] + w, v_ex5[i] + 0.05, f"{v_ex5[i]:.2f}", ha="center", va="bottom", fontsize=7.6, fontweight="bold", color="#991b1b")
    ax1.set_xticks(x_b)
    ax1.set_xticklabels([x[2] for x in b_items], fontsize=7.8, fontweight="bold")
    ax1.set_ylabel("单仓复利净值（倍，扣千分之三）", fontsize=9.4, fontweight="bold")
    ax1.set_title("赛道二：北交所砍掉2024年10月狂潮或去前五极值后全线跌破1倍", fontsize=10.6, fontweight="bold", pad=12)
    ax1.set_ylim(0, 3.65)
    ax1.legend(loc="upper right", fontsize=8.0, frameon=True)
    ax1.grid(axis="y", linestyle="--", alpha=0.35)

    # Right: Monthly BSE median turnover decay + staggered EW baseline (2024.09 ~ 2026.11)
    bse = pd.read_parquet(f"{RD042_DIR}/bse_30cm_daily_cache.parquet")
    bse["dt"] = bse["dt"].astype(str).str[:10]
    post = bse[bse["dt"] >= "2024-09-24"].copy()
    post["ym"] = post["dt"].str[:7]
    m_agg = post.groupby("ym", as_index=False).agg(med_wan=("amount_yi", lambda s: float(s.median() * 10000.0)))
    xm = np.arange(len(m_agg))
    ax2.plot(xm, m_agg["med_wan"], marker="o", color="#0284c7", linewidth=2.2, label="北交所全市场单股日成交中位数（万元）")
    ax2.fill_between(xm, 0, m_agg["med_wan"], color="#0284c7", alpha=0.14)
    ax2.axhline(5000.0, color="#dc2626", linestyle="--", linewidth=1.2, label="5000万元流动性门槛线")
    ax2.set_xticks(xm[::3])
    ax2.set_xticklabels([m_agg["ym"].iloc[i].replace("-", ".") for i in range(0, len(m_agg), 3)], fontsize=8.2, fontweight="bold")
    ax2.set_ylabel("单股日成交额中位数（万元）", fontsize=9.4, fontweight="bold")
    ax2.set_ylim(0, 12500)
    ax2.set_title("活水退潮物理根因：成交中位从1.07亿跌至0.13亿，高额门槛变成接盘信号", fontsize=10.3, fontweight="bold", pad=12)
    b2c = fk["t2"]["b2c_contrarian_and_stagger"]
    ew_5k = [x for x in b2c if x["liq"] == "5kw" and x["exit"] == "S3_hold3c"][0]["all_liq_ew_phase_mean"]
    ew_1y = [x for x in b2c if x["liq"] == "1yi" and x["exit"] == "S3_hold3c"][0]["all_liq_ew_phase_mean"]
    ax2.text(0.52, 0.72, f"常态期(2024.11至2026.11)全相位轮动3天基准:\n"
                         f"  5000万以上全池等权: {ew_5k:.2f}x\n"
                         f"  1亿以上全池等权: {ew_1y:.2f}x\n"
                         f"  逆势低吸反转前3名: 0.14x 至 0.20x",
             transform=ax2.transAxes, fontsize=8.6, fontweight="bold",
             bbox=dict(boxstyle="round,pad=0.45", facecolor="#fef2f2", edgecolor="#ef4444", alpha=0.95))
    ax2.legend(loc="upper left", fontsize=8.2, frameon=True)
    ax2.grid(True, linestyle="--", alpha=0.35)

    plt.tight_layout(pad=2.0)
    c2 = f"{RD045_DIR}/rd045_chart2_bse_v2_post924_falsified.png"
    fig.savefig(c2, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return c1, c2


def main():
    t0 = time.time()
    t1_df = pd.read_csv(f"{RD045_DIR}/rd045_track1_abn_grid.csv")
    t2_df = pd.read_csv(f"{RD045_DIR}/rd045_track2_bse_grid.csv")
    t1_bu = json.load(open(f"{RD045_DIR}/_t1_build_audit.json", encoding="utf-8"))
    fk = json.load(open(f"{RD045_DIR}/rd045_forensics.json", encoding="utf-8"))

    # Combine unified rd045_grid.csv
    comb = pd.concat([t1_df.assign(domain="TRACK1_ABN_V2"), t2_df.assign(domain="TRACK2_BSE_V2")], ignore_index=True, sort=False)
    comb.to_csv(f"{RD045_DIR}/rd045_grid.csv", index=False, encoding="utf-8-sig")

    c1, c2 = build_charts(t1_df, t2_df, fk)

    # Check Red-Team Pass Counts strictly across both tracks
    t1_pass = t1_df[
        (t1_df["n_trades"] >= 20) & (t1_df["nav_30"] >= 1.5) & (t1_df["ex5_30"] >= 1.15)
        & (t1_df["nav_wf"] >= 1.5) & (t1_df["ex5_wf"] >= 1.15) & (t1_df["nav_2023"] >= 1.0)
        & (t1_df["nav_2526"] >= 1.05) & (t1_df["perm_any_p"] < 0.05)
        & (t1_df["v20_delta_ratio"].fillna(0) >= 1.0)
    ]
    t2_pass = t2_df[
        (t2_df["n_exoct"] >= 15) & (t2_df["nav_exoct"] >= 1.3) & (t2_df["ex5_exoct"] >= 1.1)
        & (t2_df["nav_2526"] >= 1.05) & (t2_df["perm_any_p"] < 0.05)
        & (t2_df["v20_delta_ratio"].fillna(0) >= 1.0)
    ]

    audit = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "verdict": "BOTH_FALSIFIED_FOR_LIVE_WITH_TRACK1_THEME_DISCOVERY",
        "track1_redteam_pass_cnt": int(len(t1_pass)),
        "track2_redteam_pass_cnt": int(len(t2_pass)),
        "track1_build": t1_bu,
        "track1_max_mtm_diff": float(t1_df["mtm_diff"].abs().max()),
        "track2_max_mtm_diff": float(t2_df["mtm_diff"].abs().max()),
        "track1_trunc_all_pass": bool(t1_df["trunc_20241231_pass"].dropna().all()),
        "track2_trunc_all_pass": bool(t2_df["trunc_20251231_pass"].dropna().all()),
        "track1_theme_exp": t1_df[t1_df["section"] == "THEME_EXP"].to_dict("records"),
        "track1_top_by_ex5wf": t1_df.sort_values("ex5_wf", ascending=False).head(10).to_dict("records"),
        "track2_top_by_ex5exoct": t2_df.sort_values("ex5_exoct", ascending=False).head(10).to_dict("records"),
        "forensics": fk,
        "charts": [c1, c2],
    }
    with open(f"{RD045_DIR}/rd045_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(f"[Step4 DONE] grid={len(comb)} rows | t1_pass={len(t1_pass)}, t2_pass={len(t2_pass)} | charts={c1}, {c2}")


if __name__ == "__main__":
    main()
