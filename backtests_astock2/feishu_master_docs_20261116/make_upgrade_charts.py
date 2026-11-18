#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""生成一进二 V19 / 三进四 V4.0 / 二进三 V2.0 飞书净值与水下回撤图（基于真实交易台账）"""
import os
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "STHeiti", "Arial Unicode MS", "PingFang HK"]
plt.rcParams["axes.unicode_minus"] = False

LEDGER_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
IDX_JSON = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"


def load_csi300_series(start_dt="2021-11-15", end_dt="2026-11-16"):
    raw = json.load(open(IDX_JSON, "r", encoding="utf-8"))["sh000300"]
    dts = sorted(d for d in raw.keys() if start_dt <= d <= end_dt)
    base = float(raw[dts[0]])
    vals = [float(raw[d]) / base for d in dts]
    return pd.to_datetime(dts), np.array(vals, dtype=float), dts


def build_daily_curve(ledger_csv, dts_str, mode="1s"):
    df = pd.read_csv(ledger_csv)
    df = df.sort_values(["exit_date", "buy_date"]).reset_index(drop=True)
    events = {}
    nav = 1.0
    cap = 100.0
    for r in df.itertuples(index=False):
        ret = float(r.net_ret)
        ed = str(r.exit_date)
        nav *= (1.0 + ret)
        cap += min(cap, 1000.0) * ret
        events[ed] = nav if mode == "1s" else (cap / 100.0)

    series = []
    cur = 1.0
    for d in dts_str:
        if d in events:
            cur = events[d]
        series.append(cur)
    arr = np.array(series, dtype=float)
    pk = np.maximum.accumulate(arr)
    dd = (arr - pk) / pk * 100.0
    return arr, dd


def draw_strategy_chart(
    out_path,
    title,
    primary_csv,
    primary_label,
    cap_label,
    mdd_label,
    y_ticks,
    y_lim,
    dd_ticks,
    dd_lim,
    extra_csv=None,
    extra_label=None,
    anno_lines=None,
):
    dts_dt, csi_nav, dts_str = load_csi300_series("2021-11-15", "2026-11-16")
    nav_1s, dd_1s = build_daily_curve(primary_csv, dts_str, mode="1s")
    nav_cap, _ = build_daily_curve(primary_csv, dts_str, mode="cap1m")

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(12.0, 7.6), gridspec_kw={"height_ratios": [3.0, 1.05]}, sharex=True
    )
    fig.patch.set_facecolor("#FFFFFF")

    ax1.set_yscale("log")
    ax1.plot(dts_dt, nav_1s, color="#D62728", lw=2.6, label=primary_label, zorder=4)
    ax1.plot(dts_dt, nav_cap, color="#1B8A5A", lw=2.0, label=cap_label, zorder=3)
    if extra_csv and extra_label:
        nav_ex, _ = build_daily_curve(extra_csv, dts_str, mode="1s")
        ax1.plot(dts_dt, nav_ex, color="#2B6CB0", lw=1.9, ls="--", label=extra_label, zorder=3)
    ax1.plot(dts_dt, csi_nav, color="#6B7280", lw=1.5, ls=":", label="沪深300指数基准（终点 0.82 倍，跌 18.49%）", zorder=2)

    ax1.scatter([dts_dt[-1]], [nav_1s[-1]], color="#D62728", s=55, zorder=5)
    ax1.set_ylim(*y_lim)
    ax1.set_yticks(y_ticks)
    ax1.set_yticklabels([f"{v:g}倍" for v in y_ticks], fontsize=10)
    ax1.set_ylabel("累计净值倍数（对数坐标，双边千二摩擦）", fontsize=11)
    ax1.set_title(title, fontsize=14, fontweight="bold", pad=12)
    ax1.grid(True, which="major", ls="--", alpha=0.35, color="#CBD5E1")
    ax1.legend(loc="upper left", frameon=True, facecolor="#F8FAFC", edgecolor="#CBD5E1", fontsize=9.8)

    if anno_lines:
        txt = "\n".join(anno_lines)
        ax1.text(
            0.985, 0.14, txt, transform=ax1.transAxes,
            ha="right", va="bottom", fontsize=10.5, color="#B91C1C",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#FEF2F2", edgecolor="#FECACA", alpha=0.92),
        )

    ax2.fill_between(dts_dt, dd_1s, 0.0, color="#EF4444", alpha=0.28)
    ax2.plot(dts_dt, dd_1s, color="#DC2626", lw=1.2, label=mdd_label)
    mdd_min = float(np.min(dd_1s))
    ax2.axhline(mdd_min, color="#B91C1C", lw=1.1, ls="--")
    ax2.set_ylim(*dd_lim)
    ax2.set_yticks(dd_ticks)
    ax2.set_yticklabels(["0%" if v == 0 else f"跌{abs(v):g}%" for v in dd_ticks], fontsize=9.5)
    ax2.set_ylabel("水下回撤", fontsize=11)
    ax2.grid(True, ls="--", alpha=0.35, color="#CBD5E1")
    ax2.legend(loc="lower left", frameon=True, facecolor="#FFFFFF", edgecolor="#CBD5E1", fontsize=9.8)

    ax2.xaxis.set_major_locator(mdates.YearLocator())
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y年"))
    plt.xticks(fontsize=10)
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close(fig)
    print(f"[+] 生成图表完成: {out_path} (nav_1s={nav_1s[-1]:.2f}x, nav_cap={nav_cap[-1]:.2f}x, mdd={abs(mdd_min):.2f}%)")


def main():
    draw_strategy_chart(
        out_path=f"{OUT_DIR}/chart_1to2_v19.png",
        title="2021年至2026年一进二策略 V19 定版与基准增长轨迹",
        primary_csv=f"{LEDGER_DIR}/ledger_upg_1to2.csv",
        primary_label="一进二 V19 纯单仓定版（97笔，终点 338.37 倍，胜率 68.04%）",
        cap_label="一进二 V19 百万起千万封顶（终点 54.57 倍，净超额 5375.02 百分点）",
        mdd_label="V19 单仓动态水下回撤（历史最大回撤 15.97%）",
        y_ticks=[0.6, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 400.0],
        y_lim=(0.55, 520.0),
        dd_ticks=[0, -5, -10, -15.97, -22],
        dd_lim=(-24, 2),
        anno_lines=["V19 定版单仓 338.37 倍", "五年胜率 68.04%  盈亏比 2.87  回撤 15.97%"],
    )

    draw_strategy_chart(
        out_path=f"{OUT_DIR}/chart_3to4_v40.png",
        title="2022年至2026年三进四策略 V4.0 定版与基准增长轨迹",
        primary_csv=f"{LEDGER_DIR}/ledger_upg_3to4_std.csv",
        primary_label="三进四 V4.0 标准90分单仓（95笔，终点 1799.99 倍，胜率 68.42%）",
        cap_label="三进四 V4.0 百万起千万封顶（终点 75.49 倍，净超额 7467.14 百分点）",
        extra_csv=f"{LEDGER_DIR}/ledger_upg_3to4_strict.csv",
        extra_label="三进四 V4.0 极严102分S档（31笔，终点 16.72 倍，胜率 64.52%）",
        mdd_label="V4.0 标准90分单仓动态水下回撤（历史最大回撤 31.25%）",
        y_ticks=[0.6, 1.0, 2.0, 5.0, 10.0, 30.0, 100.0, 300.0, 1000.0, 2000.0],
        y_lim=(0.55, 2800.0),
        dd_ticks=[0, -10, -20, -31.25, -40],
        dd_lim=(-42, 2),
        anno_lines=["V4.0 标准单仓 1799.99 倍", "五年胜率 68.42%  HLZ t值 4.09  DSR 0.9818"],
    )

    draw_strategy_chart(
        out_path=f"{OUT_DIR}/chart_2to3_v20.png",
        title="2021年至2026年二进三策略 V2.0 定版与基准增长轨迹",
        primary_csv=f"{LEDGER_DIR}/ledger_upg_2to3_std.csv",
        primary_label="二进三 V2.0 标准90分单仓（94笔，终点 144.21 倍，胜率 52.13%）",
        cap_label="二进三 V2.0 百万起千万封顶（终点 41.65 倍，净超额 4083.32 百分点）",
        extra_csv=f"{LEDGER_DIR}/ledger_upg_2to3_strict.csv",
        extra_label="二进三 V2.0 高严96分提醒档（35笔，终点 17.43 倍，胜率 54.29%）",
        mdd_label="V2.0 标准90分单仓动态水下回撤（历史最大回撤 28.68%）",
        y_ticks=[0.6, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0],
        y_lim=(0.55, 260.0),
        dd_ticks=[0, -10, -20, -28.68, -35],
        dd_lim=(-38, 2),
        anno_lines=["V2.0 标准单仓 144.21 倍（盈亏比 4.01）", "96分高严档 17.43 倍（回撤 15.87%，2026胜率 83.33%）"],
    )


if __name__ == "__main__":
    main()
