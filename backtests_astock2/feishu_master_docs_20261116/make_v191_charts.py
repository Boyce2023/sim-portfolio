#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""生成 V19.1 升级后《三进四 V4.1》《二进三 V2.1》《超跌撬板 V2.1》净值与回撤图表"""
import os
import sys
import json
import pickle
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "STHeiti", "Arial Unicode MS", "PingFang HK"]
plt.rcParams["axes.unicode_minus"] = False

SIM = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
F1_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4"
S2_DIR = f"{SIM}/backtests_astock/exit_opt_20261118/s2_2to3_exit"
F3_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f3_pry"
S3_DIR = f"{SIM}/backtests_astock/exit_opt_20261118/s3_pry_exit"


def load_csi300_series(start_dt="2021-11-15", end_dt="2026-11-16"):
    raw = json.load(open(IDX_JSON, "r", encoding="utf-8"))["sh000300"]
    dts = sorted(d for d in raw.keys() if start_dt <= d <= end_dt)
    base = float(raw[dts[0]])
    vals = [float(raw[d]) / base for d in dts]
    return pd.to_datetime(dts), np.array(vals, dtype=float), dts


def build_daily_curve_from_df(df, dts_str, mode="1s", start_dt="2021-11-15"):
    df = df[df["buy_date"] >= start_dt].copy()
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
    primary_df,
    primary_label,
    cap_label,
    mdd_label,
    y_ticks,
    y_lim,
    dd_ticks,
    dd_lim,
    extra_df=None,
    extra_label=None,
    anno_lines=None,
    log_scale=True,
):
    dts_dt, csi_nav, dts_str = load_csi300_series("2021-11-15", "2026-11-16")
    nav_1s, dd_1s = build_daily_curve_from_df(primary_df, dts_str, mode="1s")
    nav_cap, _ = build_daily_curve_from_df(primary_df, dts_str, mode="cap1m")

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(12.0, 7.6), gridspec_kw={"height_ratios": [3.0, 1.05]}, sharex=True
    )
    fig.patch.set_facecolor("#FFFFFF")

    if log_scale:
        ax1.set_yscale("log")
    ax1.plot(dts_dt, nav_1s, color="#D62728", lw=2.6, label=primary_label, zorder=4)
    if cap_label:
        ax1.plot(dts_dt, nav_cap, color="#1B8A5A", lw=2.0, label=cap_label, zorder=3)
    if extra_df is not None and extra_label:
        nav_ex, _ = build_daily_curve_from_df(extra_df, dts_str, mode="1s")
        ax1.plot(dts_dt, nav_ex, color="#2B6CB0", lw=1.9, ls="--", label=extra_label, zorder=3)
    ax1.plot(dts_dt, csi_nav, color="#6B7280", lw=1.5, ls=":", label="沪深300指数基准（终点 0.82 倍，-18.49%）", zorder=2)

    ax1.scatter([dts_dt[-1]], [nav_1s[-1]], color="#D62728", s=55, zorder=5)
    ax1.set_ylim(*y_lim)
    ax1.set_yticks(y_ticks)
    ax1.set_yticklabels([f"{v:g}倍" for v in y_ticks], fontsize=10)
    scale_note = "对数坐标" if log_scale else "线性坐标"
    ax1.set_ylabel(f"累计净值倍数（{scale_note}，双边千二摩擦）", fontsize=11)
    ax1.set_title(title, fontsize=14, fontweight="bold", pad=12)
    ax1.grid(True, which="major", ls="--", alpha=0.35, color="#CBD5E1")
    ax1.legend(loc="upper left", frameon=True, facecolor="#F8FAFC", edgecolor="#CBD5E1", fontsize=9.6)

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
    ax2.set_yticklabels(["0%" if v == 0 else f"-{abs(v):g}%" for v in dd_ticks], fontsize=9.5)
    ax2.set_ylabel("水下回撤", fontsize=11)
    ax2.grid(True, ls="--", alpha=0.35, color="#CBD5E1")
    ax2.legend(loc="lower left", frameon=True, facecolor="#FFFFFF", edgecolor="#CBD5E1", fontsize=9.8)

    ax2.xaxis.set_major_locator(mdates.YearLocator())
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y年"))
    plt.xticks(fontsize=10)
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close(fig)
    print(f"[+] 生成图表完成: {os.path.basename(out_path)} (nav_1s={nav_1s[-1]:.2f}x, nav_cap={nav_cap[-1]:.2f}x, mdd={abs(mdd_min):.2f}%)")


def build_pry_16_dfs():
    s3 = json.load(open(f"{F3_DIR}/summary_pry_exit_factors.json", "r", encoding="utf-8"))
    rows_v21 = []
    rows_v10 = []
    for t in s3["p165_16trades_comparison"]:
        rows_v21.append({"buy_date": t["buy_date"], "exit_date": t["V21_exit"], "net_ret": t["V21_ret"] / 100.0})
        rows_v10.append({"buy_date": t["buy_date"], "exit_date": t["X10_exit"], "net_ret": t["X10_ret"] / 100.0})
    return pd.DataFrame(rows_v21), pd.DataFrame(rows_v10)


def main():
    # 1. 三进四 V4.1
    df_34_std = pd.read_csv(f"{F1_DIR}/ledger_3to4_xf30_std.csv")
    df_34_strict = pd.read_csv(f"{F1_DIR}/ledger_3to4_xf30_strict.csv")
    draw_strategy_chart(
        out_path=f"{OUT_DIR}/chart_3to4_v41.png",
        title="2021年至2026年三进四策略 V4.1 定版与基准增长轨迹",
        primary_df=df_34_std,
        primary_label="三进四 V4.1 标准90分单仓（95笔，终点 2319.09 倍，胜率 68.42%）",
        cap_label="三进四 V4.1 百万起千万封顶（终点 79.02 倍，净超额 7820.51 百分点）",
        extra_df=df_34_strict,
        extra_label="三进四 V4.1 极严102分S档（31笔，终点 17.73 倍，胜率 64.52%）",
        mdd_label="V4.1 标准90分单仓动态水下回撤（历史最大回撤 29.23%，较 V4.0 降 2.02 点）",
        y_ticks=[0.6, 1.0, 2.0, 5.0, 15.0, 50.0, 150.0, 500.0, 1500.0, 2500.0],
        y_lim=(0.55, 3600.0),
        dd_ticks=[0, -10, -20, -29.23, -36],
        dd_lim=(-38, 2),
        anno_lines=["V4.1 标准单仓 2319.09 倍（V4.0 原版 1799.99 倍）", "五年胜率 68.42%  盈亏比 2.19  HLZ t值 4.20  DSR 0.9869"],
        log_scale=True,
    )

    # 2. 二进三 V2.1 (完备5分钟主轨 + 官库5分钟对照说明)
    df_23_std = pd.read_csv(f"{S2_DIR}/ledger_opt_t2_std90.csv")
    df_23_strict = pd.read_csv(f"{S2_DIR}/ledger_opt_t2_strict96.csv")
    draw_strategy_chart(
        out_path=f"{OUT_DIR}/chart_2to3_v21.png",
        title="2021年至2026年二进三策略 V2.1 定版与基准增长轨迹",
        primary_df=df_23_std,
        primary_label="二进三 V2.1 完备5分钟90分单仓（95笔，终点 313.87 倍，官库口径 157.85 倍）",
        cap_label="二进三 V2.1 百万起千万封顶（完备 51.31 倍 / 官库 42.75 倍）",
        extra_df=df_23_strict,
        extra_label="二进三 V2.1 高严96分提醒档（完备 23.36 倍 / 官库 18.54 倍）",
        mdd_label="V2.1 标准90分单仓动态水下回撤（历史最大回撤 28.68%）",
        y_ticks=[0.6, 1.0, 2.0, 5.0, 10.0, 25.0, 60.0, 150.0, 350.0],
        y_lim=(0.55, 480.0),
        dd_ticks=[0, -10, -20, -28.68, -35],
        dd_lim=(-38, 2),
        anno_lines=["13:45 护利由 +5.0% 上调至 +6.5%（变动 17 笔 17 胜 0 负）", "完备库 313.87 倍（DSR 0.9868）| 官库 157.85 倍（DSR 0.9583）"],
        log_scale=True,
    )

    # 3. 超跌撬板 V2.1
    df_pry_v21, df_pry_v10 = build_pry_16_dfs()
    draw_strategy_chart(
        out_path=f"{OUT_DIR}/chart_pry_v21.png",
        title="2021年至2026年超跌撬板策略 V2.1 定版与 V1.0 原版增长轨迹",
        primary_df=df_pry_v21,
        primary_label="超跌撬板 V2.1 四步动态卖法单仓（16笔，终点 2.44 倍，胜率 87.50%）",
        cap_label=None,
        extra_df=df_pry_v10,
        extra_label="超跌撬板 V1.0 旧版死限价单（16笔，终点 1.94 倍，胜率 75.00%）",
        mdd_label="V2.1 单仓动态水下回撤（最大回撤 19.15%，较 V1.0 的 21.42% 下降 2.27 点）",
        y_ticks=[0.7, 1.0, 1.3, 1.6, 1.94, 2.2, 2.44, 2.7],
        y_lim=(0.68, 2.85),
        dd_ticks=[0, -5, -10, -15, -19.15, -24],
        dd_lim=(-26, 2),
        anno_lines=["V2.1 单仓 2.44 倍（V1.0 原版 1.94 倍），25 日等权 3.81 倍", "五年胜率 87.50%  近三年 +49.01%  2026 年胜率 100.0%"],
        log_scale=False,
    )


if __name__ == "__main__":
    main()
