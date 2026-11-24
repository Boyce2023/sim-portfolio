#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""生成 V20.0 六大实盘策略纯单仓净值与回撤图表（永久零千万封顶口径）"""
import os, json
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
OUT_DIR = f"{SIM}/backtests_astock2/feishu_master_docs_20261116"
PARTC = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
S2_STRICT96 = f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/ledger_opt_t2_strict96.csv"
V20_1TO2 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades/ledger_1to2_v20_cand.csv"
V11_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"


def load_csi(start_dt, end_dt):
    raw = json.load(open(IDX_JSON, "r", encoding="utf-8"))["sh000300"]
    dts = sorted(d for d in raw.keys() if start_dt <= d <= end_dt)
    base = float(raw[dts[0]])
    return pd.to_datetime(dts), np.array([float(raw[d]) / base for d in dts], dtype=float), dts


def curve_from_df(df, dts_str, start_dt):
    df = df[df["buy_date"] >= start_dt].sort_values(["exit_date", "buy_date"]).reset_index(drop=True)
    events, nav = {}, 1.0
    for r in df.itertuples(index=False):
        nav *= (1.0 + float(r.net_ret))
        events[str(r.exit_date)[:10]] = nav
    series, cur = [], 1.0
    for d in dts_str:
        if d in events:
            cur = events[d]
        series.append(cur)
    arr = np.array(series, dtype=float)
    pk = np.maximum.accumulate(arr)
    return arr, (arr - pk) / pk * 100.0


def draw_chart(out_path, title, primary_df, primary_label, mdd_label, y_ticks, y_lim, dd_ticks, dd_lim,
               start_dt="2021-11-15", end_dt="2026-11-16", extra_df=None, extra_label=None,
               anno_lines=None, log_scale=True, anno_x=0.985, anno_y=0.14, anno_ha="right"):
    dts_dt, csi_nav, dts_str = load_csi(start_dt, end_dt)
    nav_1s, dd_1s = curve_from_df(primary_df, dts_str, start_dt)
    csi_ret = (csi_nav[-1] - 1.0) * 100.0
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12.0, 7.6), gridspec_kw={"height_ratios": [3.0, 1.05]}, sharex=True)
    fig.patch.set_facecolor("#FFFFFF")
    if log_scale:
        ax1.set_yscale("log")
    ax1.plot(dts_dt, nav_1s, color="#D62728", lw=2.6, label=primary_label, zorder=4)
    if extra_df is not None and extra_label:
        nav_ex, _ = curve_from_df(extra_df, dts_str, start_dt)
        ax1.plot(dts_dt, nav_ex, color="#2B6CB0", lw=1.9, ls="--", label=extra_label, zorder=3)
    ax1.plot(dts_dt, csi_nav, color="#6B7280", lw=1.5, ls=":",
             label=f"沪深300指数基准（终点 {csi_nav[-1]:.2f} 倍，{csi_ret:+.2f}%）", zorder=2)
    ax1.scatter([dts_dt[-1]], [nav_1s[-1]], color="#D62728", s=55, zorder=5)
    ax1.set_ylim(*y_lim)
    ax1.set_yticks(y_ticks)
    ax1.set_yticklabels([f"{v:g}倍" for v in y_ticks], fontsize=10)
    ax1.set_ylabel(f"累计净值倍数（{'对数坐标' if log_scale else '线性坐标'}，纯单仓复利）", fontsize=11)
    ax1.set_title(title, fontsize=14, fontweight="bold", pad=12)
    ax1.grid(True, which="major", ls="--", alpha=0.35, color="#CBD5E1")
    ax1.legend(loc="upper left", frameon=True, facecolor="#F8FAFC", edgecolor="#CBD5E1", fontsize=9.6)
    if anno_lines:
        ax1.text(anno_x, anno_y, "\n".join(anno_lines), transform=ax1.transAxes, ha=anno_ha, va="bottom",
                 fontsize=10.5, color="#B91C1C",
                 bbox=dict(boxstyle="round,pad=0.4", facecolor="#FEF2F2", edgecolor="#FECACA", alpha=0.92))
    ax2.fill_between(dts_dt, dd_1s, 0.0, color="#EF4444", alpha=0.28)
    ax2.plot(dts_dt, dd_1s, color="#DC2626", lw=1.2, label=mdd_label)
    ax2.axhline(float(np.min(dd_1s)), color="#B91C1C", lw=1.1, ls="--")
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
    print(f"[+] 生成图表: {os.path.basename(out_path)} | nav={nav_1s[-1]:.2f}x mdd={abs(float(np.min(dd_1s))):.2f}%")


def main():
    draw_chart(
        f"{OUT_DIR}/chart_3to4_v41_v20.png", "2021年至2026年三进四策略 V4.1 纯单仓复利轨迹",
        pd.read_csv(f"{PARTC}/ledger_3to4_v41_clean.csv"),
        "三进四 V4.1 标准90分单仓（95笔，终点 616.18 倍，胜率 65.26%）",
        "V4.1 标准90分单仓水下回撤（历史最大回撤 37.00%）",
        [0.6, 1.0, 2.0, 5.0, 15.0, 50.0, 150.0, 300.0, 650.0], (0.55, 950.0), [0, -10, -20, -30, -37.0, -42], (-44, 2),
        extra_df=pd.read_csv(f"{PARTC}/ledger_3to4_v41_strict102_clean_ref.csv"),
        extra_label="三进四 V4.1 极严102分S档（31笔，终点 15.95 倍，胜率 61.29%）",
        anno_lines=["V4.1 纯单仓 616.18 倍（按日等权 1167.33 倍，4F Alpha +337.1%）", "五年胜率 65.26%  盈亏比 1.95  HLZ t值 3.56  容量守卫 3076 万"],
    )
    draw_chart(
        f"{OUT_DIR}/chart_high_v51_v20.png", "2021年至2026年高标首阴策略 V5.1 纯单仓复利轨迹",
        pd.read_csv(f"{PARTC}/ledger_high_v51_clean.csv"),
        "高标首阴 V5.1 纯5分钟单仓（42笔，终点 14.75 倍，胜率 71.43%）",
        "V5.1 纯单仓动态水下回撤（历史最大回撤 15.94%）",
        [0.8, 2.0, 4.0, 6.0, 9.0, 12.0, 15.0], (0.2, 17.5), [0, -5, -10, -15.94, -20], (-22, 2),
        anno_lines=["V5.1 纯单仓 14.75 倍（22至24熊市 2.26 倍，4F Alpha +80.2%）", "五年胜率 71.43%  盈亏比 2.83  HLZ t值 5.40  容量守卫 7568 万"],
        log_scale=False, anno_x=0.36, anno_y=0.45, anno_ha="center",
    )
    draw_chart(
        f"{OUT_DIR}/chart_2to3_v21_v20.png", "2021年至2026年二进三策略 V2.1 纯单仓复利轨迹",
        pd.read_csv(f"{PARTC}/ledger_2to3_v21_opt_std90_clean.csv"),
        "二进三 V2.1 完备5分钟90分单仓（95笔，终点 404.71 倍，胜率 53.68%）",
        "V2.1 标准90分单仓水下回撤（历史最大回撤 28.68%）",
        [0.6, 1.0, 2.0, 5.0, 10.0, 25.0, 60.0, 150.0, 420.0], (0.55, 620.0), [0, -10, -20, -28.68, -35], (-38, 2),
        extra_df=pd.read_csv(S2_STRICT96),
        extra_label="二进三 V2.1 高严96分提醒档（35笔，终点 23.36 倍，胜率 54.29%）",
        anno_lines=["V2.1 纯单仓 404.71 倍（按日等权 319.29 倍，4F Alpha +319.2%）", "五年胜率 53.68%  盈亏比 4.57  HLZ t值 4.39  容量守卫 2417 万"],
    )
    draw_chart(
        f"{OUT_DIR}/chart_1to2_v20.png", "2021年至2026年一进二策略 V20 纯单仓复利轨迹",
        pd.read_csv(V20_1TO2),
        "一进二 V20 跨板抑制定版（92笔，终点 474.35 倍，胜率 71.74%）",
        "V20 单仓动态水下回撤（历史最大回撤 13.31%）",
        [0.6, 1.0, 2.0, 5.0, 15.0, 40.0, 100.0, 250.0, 500.0], (0.55, 680.0), [0, -5, -10, -13.31, -18], (-20, 2),
        extra_df=pd.read_csv(f"{PARTC}/ledger_1to2_v19_clean.csv"),
        extra_label="一进二 V19 旧版参照（97笔，终点 332.72 倍，回撤 15.97%）",
        anno_lines=["V20 纯单仓 474.35 倍（OOS 样本外 63.80 倍，去前五 35.04 倍）", "五年胜率 71.74%  盈亏比 3.21  回撤 13.31%  PBO 1.43%"],
    )
    draw_chart(
        f"{OUT_DIR}/chart_20cm_v11_v20.png", "2021年至2026年 20cm 首板深水错杀 V1.1 纯单仓轨迹",
        pd.read_csv(f"{V11_DIR}/final_v11_ledger_S82.csv"),
        "20cm V1.1 S档满82分单仓（199笔，终点 468.29 倍，胜率 57.79%）",
        "20cm V1.1 S82 单仓水下回撤（历史最大回撤 26.70%）",
        [0.6, 1.0, 2.0, 5.0, 15.0, 40.0, 100.0, 250.0, 500.0], (0.55, 700.0), [0, -10, -20, -26.70, -35], (-38, 2),
        start_dt="2021-01-04", end_dt="2026-11-23",
        extra_df=pd.read_csv(f"{V11_DIR}/final_v11_ledger.csv"),
        extra_label="20cm V1.1 A档76分全池参考（285笔，终点 349.78 倍，仅观察）",
        anno_lines=["S82 全期 468.29 倍（按日等权 1729.70 倍，Calmar 卡尔玛 6.91）", "胜率 57.79%  盈亏比 2.01  回撤 26.70%  容量守卫 1797 万"],
    )


if __name__ == "__main__":
    main()
