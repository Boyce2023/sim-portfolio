#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Generate 2 pure-Chinese charts for RD040 Feishu report."""
import json
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd040_abn_unlock_wave2_20261126"


def _setup_font():
    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang SC", "STHeiti", "Heiti TC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def build_chart1() -> str:
    _setup_font()
    bm = pd.read_csv(f"{OUT_DIR}/rd040_blind_matrix.csv")
    an = pd.read_csv(f"{OUT_DIR}/rd040_e1a_anatomy.csv")
    fk = json.load(open(f"{OUT_DIR}/rd040_e1a_forensics.json", encoding="utf-8"))
    wf_ex = pd.read_csv(f"{OUT_DIR}/rd040_e1a_wf_extra.csv")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.0, 6.2), dpi=180)
    fig.patch.set_facecolor("white")

    # Left: 5Y Single-Slot NAV across blind entry slices (S7_lianban & S1_hold1c)
    items = [
        ("E1a", "预解禁早盘全池 (401笔)"),
        ("E1b", "收盘解禁次早 (473笔)"),
        ("E2", "缩量低平开承接 (262笔)"),
        ("E3", "放量阳线次早 (190笔)"),
        ("E_ALL_Cleared", "两步排雷净池 (208笔)"),
        ("E_ALL_NoHit100", "未破百%全池 (584笔)"),
        ("E1a_NoHit100_LowOpen", "预解禁未破百+低平开 (134笔)"),
    ]
    y = np.arange(len(items))
    v_s7, v_s1 = [], []
    for k, _ in items:
        r7 = bm[(bm["slice"] == k) & (bm["exit_rule"] == "S7_lianban")]
        r1 = bm[(bm["slice"] == k) & (bm["exit_rule"] == "S1_hold1c")]
        v_s7.append(float(r7["nav_5y_30"].iloc[0]) if not r7.empty else 0.0)
        v_s1.append(float(r1["nav_5y_30"].iloc[0]) if not r1.empty else 0.0)

    h = 0.36
    b7 = ax1.barh(y - h / 2, v_s7, height=h, color="#0284c7", alpha=0.9, label="涨停持有至断板")
    b1 = ax1.barh(y + h / 2, v_s1, height=h, color="#64748b", alpha=0.85, label="次日收盘卖出")
    ax1.axvline(1.0, color="#dc2626", linestyle="--", linewidth=1.3, label="保本线 (1.00倍)")
    for idx in range(len(items)):
        ax1.text(v_s7[idx] + 0.18, y[idx] - h / 2, f"{v_s7[idx]:.2f}x", va="center", ha="left", fontsize=8.3, color="#0c4a6e", fontweight="bold" if v_s7[idx] > 1 else "normal")
        ax1.text(v_s1[idx] + 0.18, y[idx] + h / 2, f"{v_s1[idx]:.2f}x", va="center", ha="left", fontsize=8.3, color="#334155", fontweight="bold" if v_s1[idx] > 1 else "normal")
    ax1.set_yticks(y)
    ax1.set_yticklabels([lbl for _, lbl in items], fontsize=9.2, fontweight="bold")
    ax1.set_xlabel("五年单仓复利净值（倍，双边扣千分之三）", fontsize=9.5, fontweight="bold")
    ax1.set_title("全市场盲测对比：五大常规买点全部亏损，仅低平开现表面火花", fontsize=11.0, fontweight="bold", pad=12)
    ax1.set_xlim(0, 14.5)
    ax1.legend(loc="lower right", fontsize=8.5, frameon=True)
    ax1.grid(axis="x", linestyle="--", alpha=0.35)

    # Right: Red-team waterfall dissecting E1a_NoHit100_LowOpen (S7_lianban)
    row6 = an[(an["slice"] == "6_E1a_NoHit100_LowOpen_[-4.5,2.5]") & (an["exit"] == "S7_lianban")].iloc[0]
    wf_t30 = wf_ex[(wf_ex["track"] == "WF_E1a_NoHit100_LowOpen_S7") & (wf_ex["threshold"] == "top30")].iloc[0]
    p_dir = fk["v20_patch_direct"]["S7_lianban"]

    steps = [
        ("2023至2026\n全样本账面", float(row6["nav_wf"]), "#16a34a"),
        ("去掉前五极值\n(含海能达+111%)", float(row6["ex5_wf"]), "#f59e0b"),
        ("2023年单年\n实战表现", 0.626, "#ef4444"),
        ("叠加多因子打分\n前30%精选档", float(wf_t30["nav_30"]), "#dc2626"),
        ("V20空仓日独立\n去前五极值", float(p_dir["m2_emp_fw"]["ex_top5_nav"]), "#b91c1c"),
        ("强行并入V20\n总仓净值乘数", float(p_dir["m1_delta_ratio"]), "#991b1b"),
    ]
    x2 = np.arange(len(steps))
    vals2 = [s[1] for s in steps]
    cols2 = [s[2] for s in steps]
    bars2 = ax2.bar(x2, vals2, width=0.55, color=cols2, alpha=0.92, edgecolor="white")
    ax2.axhline(1.0, color="#0f172a", linestyle="--", linewidth=1.2, label="生死线 (1.00倍)")
    for b, v in zip(bars2, vals2):
        ax2.text(b.get_x() + b.get_width() / 2, v + 0.10, f"{v:.2f}x", ha="center", va="bottom", fontsize=8.8, fontweight="bold", color="#0f172a")
    ax2.set_xticks(x2)
    ax2.set_xticklabels([s[0] for s in steps], fontsize=8.4, fontweight="bold")
    ax2.set_ylabel("净值或对V20总仓乘数（倍）", fontsize=9.5, fontweight="bold")
    ax2.set_title("唯一表面火花红队拆解：去极值跌破1倍，打分反亏，补位撞毁V20", fontsize=11.0, fontweight="bold", pad=12)
    ax2.set_ylim(0, 5.8)
    ax2.grid(axis="y", linestyle="--", alpha=0.35)
    ax2.legend(loc="upper right", fontsize=8.5)

    plt.tight_layout(pad=2.0)
    out1 = f"{OUT_DIR}/rd040_chart1_blind_and_e1a_anatomy.png"
    fig.savefig(out1, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out1


def build_chart2() -> str:
    _setup_font()
    pl = pd.read_csv(f"{OUT_DIR}/rd040_e1a_plateau.csv")
    wf_all = pd.read_csv(f"{OUT_DIR}/rd040_wf_scorecard_grid.csv")
    wf_ex = pd.read_csv(f"{OUT_DIR}/rd040_e1a_wf_extra.csv")
    wf_comb = pd.concat([wf_all, wf_ex], ignore_index=True)
    wf_sel = wf_comb[(wf_comb["threshold"] != "all_cands") & (wf_comb["n_trades"] >= 10)].copy()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.0, 6.2), dpi=180)
    fig.patch.set_facecolor("white")

    # Left: Heatmap of S7_lianban ex5_wf across open_lo x open_hi
    p7 = pl[pl["exit"] == "S7_lianban"]
    piv = p7.pivot(index="open_lo", columns="open_hi", values="ex5_wf")
    im = ax1.imshow(piv.values, cmap="RdYlGn", vmin=0.5, vmax=1.25, aspect="auto")
    ax1.set_xticks(np.arange(len(piv.columns)))
    ax1.set_xticklabels([f"+{c:.1f}%" for c in piv.columns], fontsize=9.0, fontweight="bold")
    ax1.set_yticks(np.arange(len(piv.index)))
    ax1.set_yticklabels([f"{r:.1f}%" for r in piv.index], fontsize=9.0, fontweight="bold")
    ax1.set_xlabel("早盘竞价涨幅上限", fontsize=9.5, fontweight="bold")
    ax1.set_ylabel("早盘竞价涨幅下限", fontsize=9.5, fontweight="bold")
    ax1.set_title("预解禁低平开 2023至2026 去前五极值净值矩阵（多数低于1.1倍）", fontsize=10.6, fontweight="bold", pad=12)
    for r_i in range(piv.shape[0]):
        for c_i in range(piv.shape[1]):
            v = piv.values[r_i, c_i]
            if np.isfinite(v):
                ax1.text(c_i, r_i, f"{v:.2f}x", ha="center", va="center", fontsize=8.5, fontweight="bold", color="#0f172a")
    fig.colorbar(im, ax=ax1, fraction=0.046, pad=0.04, label="近四年去前五极值净值（倍）")

    # Right: Scatter of all >=10-trade WF scorecard thresholds (nav_30 vs ex5_30)
    x_n = wf_sel["nav_30"].to_numpy(float)
    y_e = wf_sel["ex5_30"].to_numpy(float)
    sz = np.clip(wf_sel["n_trades"].to_numpy(float) * 3.0, 30, 320)
    x_max = max(2.8, float(np.max(x_n)) + 0.35)
    y_max = max(1.5, float(np.max(y_e)) + 0.25)
    from matplotlib.patches import Rectangle
    ax2.add_patch(Rectangle((1.5, 1.15), x_max - 1.5, y_max - 1.15, facecolor="#dcfce7", alpha=0.42, zorder=0))
    ax2.scatter(x_n, y_e, s=sz, c="#64748b", alpha=0.72, edgecolors="#0f172a", linewidth=0.8, label="前视多因子精选各档 (样本>=10笔)", zorder=3)
    ax2.axvline(1.5, color="#dc2626", linestyle="--", linewidth=1.1, label="过关门槛: 样本外>=1.5x 且 去前五>=1.15x", zorder=2)
    ax2.axhline(1.15, color="#dc2626", linestyle="--", linewidth=1.1, zorder=2)
    name_lu = {
        "WF_E1a_NoHit100_LowOpen_S1": "预解禁未破百低平开(次收)",
        "WF_E1a_NoHit100_S1": "预解禁未破百全池(次收)",
        "WF_E_ALL_S2": "全样本合池(两日收盘)",
    }
    top2 = wf_sel.sort_values("nav_30", ascending=False).head(3)
    for r in top2.itertuples(index=False):
        cn_lbl = name_lu.get(r.track, "其它精选档")
        th_lbl = {"top30": "前30%", "top20": "前20%", "top10": "前10%"}.get(str(r.threshold), str(r.threshold))
        dx = -0.58 if r.nav_30 > 2.0 else 0.06
        dy = -0.10 if r.nav_30 > 2.0 else -0.06
        ax2.annotate(f"{cn_lbl}\n{th_lbl} ({r.n_trades}笔)", xy=(r.nav_30, r.ex5_30),
                     xytext=(r.nav_30 + dx, r.ex5_30 + dy), fontsize=7.8, color="#0f172a")
    ax2.set_xlabel("2023至2026样本外单仓净值（倍）", fontsize=9.5, fontweight="bold")
    ax2.set_ylabel("去掉前五极值后单仓净值（倍）", fontsize=9.5, fontweight="bold")
    ax2.set_title("20套前视多因子打分全部落榜图：无任何组稳过红队极值检验", fontsize=10.8, fontweight="bold", pad=12)
    ax2.set_xlim(0, x_max)
    ax2.set_ylim(0, y_max)
    ax2.grid(True, linestyle="--", alpha=0.35)
    ax2.legend(loc="lower right", fontsize=8.2)

    plt.tight_layout(pad=2.0)
    out2 = f"{OUT_DIR}/rd040_chart2_open_plateau_and_wf_collapse.png"
    fig.savefig(out2, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out2


def main():
    c1 = build_chart1()
    c2 = build_chart2()
    print("Generated charts:", c1, c2)


if __name__ == "__main__":
    main()
