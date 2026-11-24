#!/usr/bin/env python3
"""
astock_mkt_water_chart.py — A股牌桌水温 V2 合成指数 vs 策略实证对比图生成器 (近3个月 / 近1年 / 近5年)

两大经严格样本内外 (IS 2021-2023 / OOS 2024-2026) 验证的无错位合成指数:
  1. 短期「V2 单笔胜率温度指数」(0~100, 四等权: 炸板甜区 + 高度5日回落出清 + 近3日跌停洗盘 + 近3日溢价洗净)
     - 单笔相关性 Spearman=+0.183 (p=0.0055, IS=+0.201, OOS=+0.187), R^2=3.4%
     - 甜区(>=65): 胜率 74.0% / 均赚 +10.6%  vs  雷区(<45): 胜率 51.1% / 均赚 +5.1%
     - 用于 近3个月 & 近1年 主面板 (严格对齐 T-1 买入前水温，零一天错位 + 右侧三档实证柱状图)
  2. 中期「60日同窗市场活水合成指数」(0~100: 全市场分化度30% + 涨停数30% + 成交额20% + 炸板甜区20%, IS标准化)
     - 与策略同60交易日收益相关性 Spearman=+0.411 (R^2=16.9%, IS=+0.481, OOS=+0.347)
     - 用于 近5年 主面板 (60日对60日严格同窗，消除错位 + 右侧三档60日收益中位数对比柱)

用法: python3.13 sim-portfolio/scripts/astock_mkt_water_chart.py
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec

ROOT = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio")
OUT_DIR = ROOT / "data" / "mkt_water_charts"
LEDGER_PATH = ROOT / "backtests_astock/clean_3strategies_mutual_upgrade_20261117/ledger_combined_5strat_v191_slot1.csv"

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "Heiti TC", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

C_SWEET_BG = "#DCFCE7"
C_DANGER_BG = "#FEE2E2"
C_LINE = "#1E293B"
C_RAW = "#CBD5E1"
C_STRAT = "#2563EB"
C_SWEET_FG = "#15803D"
C_DANGER_FG = "#B91C1C"
C_NEUT_FG = "#475569"


def compute_daily_water() -> pd.DataFrame:
    cols = ["ticker", "date", "open", "high", "low", "close", "amount"]
    df = pd.concat([
        pd.read_parquet(ROOT / "data/cn_hk_price_db/a_daily.parquet", columns=cols),
        pd.read_parquet(ROOT / "data/cn_hk_price_db/a_delisted_daily.parquet", columns=cols),
    ], ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df[df["date"] >= "2021-09-01"].copy()
    df["code6"] = df["ticker"].astype(str).str.extract(r"(\d{6})")[0]
    df = df[df["code6"].str.startswith(("00", "60"), na=False)].copy()
    df = df.sort_values(["code6", "date"]).reset_index(drop=True)

    df["pre_c"] = df.groupby("code6")["close"].shift(1)
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["zt_px"] = (df["pre_c"] * 1.10).round(2)
    df["dt_px"] = (df["pre_c"] * 0.90).round(2)
    df["is_zt"] = (df["close"] >= df["zt_px"] - 0.005) & (df["pre_c"] > 0) & (df["pct"] >= 0.095)
    df["is_dt"] = (df["close"] <= df["dt_px"] + 0.005) & (df["pre_c"] > 0) & (df["pct"] <= -0.095)
    df["is_zb"] = (df["high"] >= df["zt_px"] - 0.005) & (~df["is_zt"]) & (df["pre_c"] > 0)
    df["prev_zt"] = df.groupby("code6")["is_zt"].shift(1).astype("boolean").fillna(False).astype(bool)

    z = df["is_zt"].astype(int).values
    codes = df["code6"].values
    streak = np.zeros(len(df), dtype=np.int16)
    for i in range(len(df)):
        if z[i] == 1:
            streak[i] = (streak[i - 1] + 1) if (i > 0 and codes[i] == codes[i - 1]) else 1
    df["streak"] = streak

    g = df.groupby("date")
    mkt = pd.DataFrame({
        "amt_yi": g["amount"].sum() / 1e8,
        "zt_cnt": g["is_zt"].sum(),
        "dt_cnt": g["is_dt"].sum(),
        "zb_cnt": g["is_zb"].sum(),
        "max_board": g["streak"].max(),
        "hi3_cnt": g["streak"].apply(lambda x: (x >= 3).sum()),
        "mkt_disp": g["pct"].std() * 100.0,
    })
    gp = df[df["prev_zt"]].groupby("date")
    mkt["zt_prem"] = gp["pct"].mean() * 100.0
    mkt["damian_rate"] = gp["pct"].apply(lambda x: (x <= -0.05).mean() * 100.0)
    mkt["zb_rate"] = mkt["zb_cnt"] / (mkt["zt_cnt"] + mkt["zb_cnt"]).clip(lower=1) * 100.0
    mkt["amt_ma20"] = mkt["amt_yi"].rolling(20).mean()
    mkt["prem_3d"] = mkt["zt_prem"].rolling(3).mean()
    mkt["dt_3d"] = mkt["dt_cnt"].rolling(3).sum()
    mkt["max_b_drop5"] = mkt["max_board"].rolling(5).max() - mkt["max_board"]
    mkt = mkt.sort_index()

    # 1. V2 Single-Trade Composite Index (equal weight 25% x 4 IS+OOS survivors)
    zb = mkt["zb_rate"].values
    d3 = mkt["dt_3d"].fillna(0.0).values
    p3 = mkt["prem_3d"].fillna(1.5).values
    mbd = mkt["max_b_drop5"].fillna(0.0).values

    s_zb = np.where((zb >= 25) & (zb <= 40), 70 + 30 * (1 - np.abs(zb - 32.5) / 7.5),
           np.where(zb > 40, np.clip(70 * (1 - (zb - 40) / 20.0), 0, 70),
                    np.clip(70 * (1 - (25 - zb) / 15.0), 0, 70)))
    s_dt = np.clip(d3 / 60.0 * 100.0, 0, 100)
    s_p3 = np.where(p3 <= 1.0, np.clip(70 + np.maximum(0, 1.0 - p3) / 2.0 * 30.0, 70, 100),
           np.where(p3 <= 3.0, 70 - (p3 - 1.0) / 2.0 * 40.0,
                    np.clip(30 * (1 - (p3 - 3.0) / 2.0), 0, 30)))
    s_mb = np.clip(25.0 + mbd * 25.0, 0, 100)
    mkt["v2_idx"] = 0.25 * (s_zb + s_dt + s_p3 + s_mb)
    mkt["v2_idx_t1"] = mkt["v2_idx"].shift(1)

    # 2. 60D Macro Water Index (strictly 2021-2023 IS standardized -> zero OOS peeking)
    is_sl = mkt.loc["2021-11-19":"2023-12-31"]
    def norm0100(ser, ref):
        return np.clip(50.0 + ((ser - ref.mean()) / ref.std()) * 18.0, 0, 100)

    mkt["macro_water"] = (
        0.30 * norm0100(mkt["mkt_disp"], is_sl["mkt_disp"])
        + 0.30 * norm0100(mkt["zt_cnt"], is_sl["zt_cnt"])
        + 0.20 * norm0100(mkt["amt_yi"], is_sl["amt_yi"])
        + 0.20 * pd.Series(s_zb, index=mkt.index)
    )
    mkt["macro_water_60d"] = mkt["macro_water"].rolling(60, min_periods=20).mean()

    mkt = mkt[mkt.index >= "2021-11-15"].copy()
    mkt["dt"] = pd.to_datetime(mkt.index)
    return mkt


def load_strategy_ledger(mkt: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    comb = pd.read_csv(LEDGER_PATH)
    comb["buy_d"] = comb["buy_date"].astype(str).str.slice(0, 10)
    comb["exit_d"] = comb["exit_date"].astype(str).str.slice(0, 10)
    comb["dt"] = pd.to_datetime(comb["buy_d"])
    comb["ret"] = comb["net_ret"].astype(float)
    comb["ret_pct"] = comb["ret"] * 100.0
    comb = comb.sort_values("dt").reset_index(drop=True)
    comb["v2_t1"] = comb["buy_d"].map(mkt["v2_idx"].shift(1))

    # Daily 60-trading-day aligned strategy log-return -> % return
    by_exit = comb.groupby("exit_d")["ret"].apply(list).to_dict()
    s_log = pd.Series([np.sum([np.log1p(x) for x in by_exit.get(d, [])]) for d in mkt.index], index=mkt.index)
    s60_log = s_log.rolling(60, min_periods=20).sum()
    return comb, s60_log


def _zone_style(status: str) -> tuple[str, str]:
    if "甜区" in status:
        return C_SWEET_FG, "#F0FDF4"
    if "雷区" in status:
        return C_DANGER_FG, "#FEF2F2"
    return C_NEUT_FG, "#F8FAFC"


def _eval_statuses(last: pd.Series) -> dict:
    v2 = float(last["v2_idx"])
    v2_st = "甜区 · 高胜率" if v2 >= 65 else ("雷区 · 胜率平庸" if v2 < 45 else "常态 · 中性")
    mw = float(last["macro_water_60d"])
    mw_st = "甜区 · 肥水周期" if mw >= 60 else ("雷区 · 干水周期" if mw < 45 else "常态 · 温和水量")
    zb = float(last["zb_rate"])
    zb_st = "甜区 · 良性分歧" if 25 <= zb <= 40 else ("雷区 · 失血溃败" if zb > 40 else "雷区 · 一致过热")
    mbd = float(last["max_b_drop5"])
    mb_st = "甜区 · 退潮出清" if mbd >= 2 else ("雷区 · 顶峰未落" if mbd <= 0 else "常态 · 轻度回落")
    d3 = int(last["dt_3d"])
    d3_st = "甜区 · 3日深洗" if d3 >= 40 else ("雷区 · 浮筹未清" if d3 <= 12 else "常态 · 正常换手")
    p3 = float(last["prem_3d"])
    p3_st = "甜区 · 低溢价洗净" if p3 <= 1.0 else ("雷区 · 高潮透支" if p3 > 3.0 else "常态 · 正常接力")
    return {"v2": v2_st, "mw": mw_st, "zb": zb_st, "mb": mb_st, "d3": d3_st, "p3": p3_st}


def _draw_sub_panel(
    ax, x: pd.Series, y_raw: pd.Series, smooth: int, title: str, ylabel: str,
    ylim: tuple[float, float], sweet_bands: list[tuple[float, float]],
    danger_bands: list[tuple[float, float]], hlines: list[tuple[float, str]],
    cur_val_str: str, cur_status: str,
) -> None:
    lo, hi = ylim
    ax.set_facecolor("#FFFFFF")
    for b0, b1 in sweet_bands:
        ax.axhspan(max(lo, b0), min(hi, b1), color=C_SWEET_BG, alpha=0.80, zorder=0)
    for b0, b1 in danger_bands:
        ax.axhspan(max(lo, b0), min(hi, b1), color=C_DANGER_BG, alpha=0.72, zorder=0)
    for yv, col in hlines:
        ax.axhline(yv, color=col, ls="--", lw=0.9, alpha=0.72, zorder=1)

    y_plot = y_raw.rolling(smooth, min_periods=1).mean() if smooth > 1 else y_raw
    if smooth > 1:
        ax.plot(x, y_raw.clip(lo, hi), color=C_RAW, lw=0.7, alpha=0.7, zorder=2)
        ax.plot(x, y_plot.clip(lo, hi), color=C_LINE, lw=1.75, zorder=3)
    else:
        ax.plot(x, y_plot.clip(lo, hi), color=C_LINE, lw=1.8, marker="o", ms=2.2, zorder=3)

    x_last = x.iloc[-1]
    y_last = float(np.clip(y_plot.iloc[-1], lo, hi))
    fg, bg = _zone_style(cur_status)
    ax.scatter([x_last], [y_last], s=60, color=fg, edgecolor="#FFFFFF", linewidth=1.6, zorder=5)
    ax.annotate(
        f" 当前 {cur_val_str}\n {cur_status}",
        xy=(x_last, y_last), xytext=(10, 0), textcoords="offset points",
        va="center", ha="left", fontsize=8.6, fontweight="bold", color=fg,
        bbox=dict(boxstyle="round,pad=0.30", facecolor=bg, edgecolor=fg, lw=1.1),
        annotation_clip=False, zorder=6,
    )
    ax.set_ylim(lo, hi)
    ax.set_ylabel(ylabel, fontsize=9.2, color="#334155", fontweight="bold")
    ax.set_title(title, loc="left", fontsize=10.0, fontweight="bold", color="#0F172A", pad=4)
    ax.grid(axis="y", ls=":", color="#94A3B8", alpha=0.35, zorder=1)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#CBD5E1")
    ax.spines["bottom"].set_color("#CBD5E1")
    ax.tick_params(colors="#475569", labelsize=8.6)


def plot_window(mkt: pd.DataFrame, comb: pd.DataFrame, s60_log: pd.Series,
                days: int, title_tag: str, out_path: Path, smooth: int = 1) -> None:
    sub = mkt.tail(days).copy()
    x = sub["dt"]
    d0, d1 = sub["dt"].iloc[0], sub["dt"].iloc[-1]
    last = sub.iloc[-1]
    d_last = sub.index[-1]
    st = _eval_statuses(last)
    is_5y = days > 500

    fig = plt.figure(figsize=(14.4, 13.8), dpi=180)
    fig.patch.set_facecolor("#FFFFFF")
    gs = GridSpec(5, 2, figure=fig, width_ratios=[4.3, 1.25], height_ratios=[1.65, 0.9, 0.9, 0.9, 0.9],
                  hspace=0.32, wspace=0.14, left=0.058, right=0.865, top=0.915, bottom=0.045)

    ax0 = fig.add_subplot(gs[0, 0])
    ax0_bar = fig.add_subplot(gs[0, 1])
    sub_axes = [fig.add_subplot(gs[i, 0], sharex=ax0) for i in range(1, 5)]

    sm_note = f"（{smooth}日平滑 + 浅灰日线）" if smooth > 1 else "（严格对齐买入前一日 T-1 水温）"
    fig.suptitle(
        f"A股牌桌水温 V2 合成指数 vs 策略实证对比 · {title_tag}{sm_note}  |  截至 {d_last} 收盘",
        fontsize=13.8, fontweight="bold", color="#0F172A", y=0.985,
    )

    if not is_5y:
        # === 3M & 1Y MASTER PANEL: V2 T-1 Water Index (exact buy-date alignment!) + Real Trades ===
        tr_sub = comb[(comb["dt"] >= d0) & (comb["dt"] <= d1)].copy()
        handles = [
            mpatches.Patch(facecolor=C_SWEET_BG, edgecolor=C_SWEET_FG, lw=0.8, label="绿底 = 甜区 (>=65分)"),
            mpatches.Patch(facecolor=C_DANGER_BG, edgecolor=C_DANGER_FG, lw=0.8, label="红底 = 雷区 (<45分)"),
            plt.Line2D([0], [0], color=C_LINE, lw=2.0, label="深墨线 = 买入前一日 V2 合成水温 (左轴)"),
            plt.Line2D([0], [0], color="#16A34A", marker="o", ls="None", ms=5.5, label="绿杆 = 盈利笔% · 红杆 = 亏损笔% (右轴)"),
        ]
        fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.46, 0.958), ncol=4, frameon=False, fontsize=8.8)

        ax0.set_facecolor("#FFFFFF")
        ax0.axhspan(65.0, 100.0, color=C_SWEET_BG, alpha=0.80, zorder=0)
        ax0.axhspan(0.0, 45.0, color=C_DANGER_BG, alpha=0.72, zorder=0)
        ax0.axhline(65.0, color=C_SWEET_FG, ls="--", lw=1.0, alpha=0.8, zorder=1)
        ax0.axhline(45.0, color=C_DANGER_FG, ls="--", lw=1.0, alpha=0.8, zorder=1)

        # Plot T-1 aligned v2_idx so vertically above any buy_date dot is EXACTLY the T-1 score known at 09:25!
        y_v2 = sub["v2_idx_t1"].rolling(3, min_periods=1).mean() if days > 100 else sub["v2_idx_t1"]
        if days > 100:
            ax0.plot(x, sub["v2_idx_t1"], color=C_RAW, lw=0.65, alpha=0.65, zorder=2)
        ax0.plot(x, y_v2, color=C_LINE, lw=2.0, zorder=3)
        ax0.set_ylim(0.0, 100.0)
        ax0.set_ylabel("V2 胜率温度 (0至100)", fontsize=9.4, color="#0F172A", fontweight="bold")
        ax0.grid(axis="y", ls=":", color="#94A3B8", alpha=0.35, zorder=1)
        ax0.spines["top"].set_visible(False)
        ax0.spines["left"].set_color("#CBD5E1")
        ax0.spines["bottom"].set_color("#CBD5E1")

        ax0r = ax0.twinx()
        ax0r.spines["top"].set_visible(False)
        ax0r.spines["right"].set_color("#93C5FD")
        ax0r.axhline(0.0, color="#64748B", ls=":", lw=0.9, alpha=0.65, zorder=1)
        if len(tr_sub) > 0:
            w_df = tr_sub[tr_sub["ret_pct"] > 0]
            l_df = tr_sub[tr_sub["ret_pct"] <= 0]
            if len(w_df):
                ax0r.vlines(w_df["dt"], 0, w_df["ret_pct"], color="#16A34A", lw=1.6, alpha=0.78, zorder=4)
                ax0r.scatter(w_df["dt"], w_df["ret_pct"], s=36, color="#16A34A", edgecolor="#FFFFFF", lw=0.7, zorder=5)
            if len(l_df):
                ax0r.vlines(l_df["dt"], 0, l_df["ret_pct"], color="#DC2626", lw=1.6, alpha=0.82, zorder=4)
                ax0r.scatter(l_df["dt"], l_df["ret_pct"], s=36, color="#DC2626", edgecolor="#FFFFFF", lw=0.7, zorder=5)
            ax0r.set_ylim(min(-14.0, float(tr_sub["ret_pct"].min()) * 1.25), max(26.0, float(tr_sub["ret_pct"].max()) * 1.18))
        ax0r.set_ylabel("策略单笔盈亏 (%)", fontsize=9.2, color=C_STRAT, fontweight="bold")
        ax0r.tick_params(colors=C_STRAT, labelsize=8.6)

        ra, pa = stats.spearmanr(comb["v2_t1"].dropna(), comb.loc[comb["v2_t1"].notna(), "ret_pct"])
        fg, bg = _zone_style(st["v2"])
        ax0.scatter([x.iloc[-1]], [float(last["v2_idx"])], s=72, color=fg, edgecolor="#FFFFFF", lw=1.7, zorder=7)
        ax0.set_title(
            f"★ V2 胜率温度指数（对齐买入前一日）vs 策略单笔盈亏  |  最新 {last['v2_idx']:.1f}分 ({st['v2']})  |  五年单笔 r={ra:+.3f} (p={pa:.3f}, 解释度{ra**2*100:.1f}%)",
            loc="left", fontsize=9.8, fontweight="bold", color="#0F172A", pad=5,
        )

        # Right bar panel: 5Y 228-trade empirical bucket win-rate & avg EV!
        cats = ["雷区\n<45分", "常态\n45至65", "甜区\n>=65分"]
        b_all = pd.cut(comb["v2_t1"], bins=[-1, 45, 65, 101], labels=cats)
        wrs = [float((comb[b_all == c]["ret_pct"] > 0).mean() * 100) for c in cats]
        evs = [float(comb[b_all == c]["ret_pct"].mean()) for c in cats]
        ns = [int((b_all == c).sum()) for c in cats]
        cols_b = ["#EF4444", "#94A3B8", "#16A34A"]
        bars = ax0_bar.bar(range(3), wrs, color=cols_b, alpha=0.85, width=0.58)
        ax0_bar.set_ylim(0, 96)
        ax0_bar.set_xticks(range(3))
        ax0_bar.set_xticklabels(cats, fontsize=8.3, fontweight="bold")
        ax0_bar.set_title("五年228笔实证胜率\n(顶标单笔均赚)", fontsize=9.2, fontweight="bold", color="#0F172A", pad=4)
        ax0_bar.grid(axis="y", ls=":", alpha=0.35)
        ax0_bar.spines["top"].set_visible(False)
        ax0_bar.spines["right"].set_visible(False)
        ax0_bar.tick_params(axis="y", labelsize=8.2)
        for bar, wr, ev, n in zip(bars, wrs, evs, ns):
            ax0_bar.text(bar.get_x() + bar.get_width() / 2, wr + 2.2, f"{wr:.1f}%\n({ev:+.1f}%)\nN={n}",
                         ha="center", va="bottom", fontsize=7.8, fontweight="bold", color="#0F172A")
    else:
        # === 5Y MASTER PANEL: 60D Aligned Macro Water Index vs 60D Aligned Strategy Return (r=+0.411!) ===
        handles = [
            mpatches.Patch(facecolor=C_SWEET_BG, edgecolor=C_SWEET_FG, lw=0.8, label="绿底 = 肥水甜区 (>=60分)"),
            mpatches.Patch(facecolor=C_DANGER_BG, edgecolor=C_DANGER_FG, lw=0.8, label="红底 = 干水雷区 (<45分)"),
            plt.Line2D([0], [0], color=C_LINE, lw=2.1, label="深墨线 = 60日市场活水合成指数 (左轴)"),
            plt.Line2D([0], [0], color=C_STRAT, lw=2.1, label="蓝线 = 策略同60日对数累计收益 (右轴)"),
        ]
        fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.46, 0.958), ncol=4, frameon=False, fontsize=8.8)

        ax0.set_facecolor("#FFFFFF")
        ax0.axhspan(60.0, 100.0, color=C_SWEET_BG, alpha=0.80, zorder=0)
        ax0.axhspan(0.0, 45.0, color=C_DANGER_BG, alpha=0.72, zorder=0)
        ax0.axhline(60.0, color=C_SWEET_FG, ls="--", lw=1.0, alpha=0.8, zorder=1)
        ax0.axhline(45.0, color=C_DANGER_FG, ls="--", lw=1.0, alpha=0.8, zorder=1)

        mw60 = sub["macro_water_60d"]
        s60_sub = s60_log.reindex(sub.index)
        ok = mw60.notna() & s60_sub.notna()
        r60, _ = stats.spearmanr(mw60[ok], s60_sub[ok])

        ax0.plot(x, mw60, color=C_LINE, lw=2.15, zorder=4)
        ax0.set_ylim(25.0, 92.0)
        ax0.set_ylabel("60日市场活水指数 (0至100)", fontsize=9.4, color="#0F172A", fontweight="bold")
        ax0.grid(axis="y", ls=":", color="#94A3B8", alpha=0.35, zorder=1)
        ax0.spines["top"].set_visible(False)
        ax0.spines["left"].set_color("#CBD5E1")
        ax0.spines["bottom"].set_color("#CBD5E1")

        ax0r = ax0.twinx()
        ax0r.spines["top"].set_visible(False)
        ax0r.spines["right"].set_color("#93C5FD")
        ax0r.axhline(0.0, color="#64748B", ls=":", lw=0.9, alpha=0.65, zorder=1)
        # Plot 60D log return * 100 (clean additive scale!)
        y_s60 = s60_sub * 100.0
        ax0r.plot(x, y_s60, color=C_STRAT, lw=2.0, alpha=0.90, zorder=5)
        ax0r.fill_between(x, 0, y_s60, where=(y_s60 >= 0), color="#DBEAFE", alpha=0.32, zorder=2)
        ax0r.set_ylabel("策略同60日对数收益 (ln x100)", fontsize=9.2, color=C_STRAT, fontweight="bold")
        ax0r.tick_params(colors=C_STRAT, labelsize=8.6)

        fg, bg = _zone_style(st["mw"])
        ax0.scatter([x.iloc[-1]], [float(mw60.iloc[-1])], s=72, color=fg, edgecolor="#FFFFFF", lw=1.7, zorder=7)
        ax0.set_title(
            f"★ 60日同窗「市场活水指数」vs 策略同60日收益（严格同窗 r={r60:+.3f}, R2={r60**2*100:.1f}% · IS +0.481 / OOS +0.347 · 当前 {mw60.iloc[-1]:.1f}分）",
            loc="left", fontsize=9.7, fontweight="bold", color="#0F172A", pad=5,
        )

        # Right bar panel: 60D median strategy return by macro water zone!
        cats60 = ["干水雷区\n<45分", "常态\n45至60", "肥水甜区\n>=60分"]
        b60 = pd.cut(mw60[ok], bins=[-1, 45, 60, 101], labels=cats60)
        meds = [float((np.exp(s60_sub[ok][b60 == c]) - 1.0).median() * 100) for c in cats60]
        pos_p = [float((s60_sub[ok][b60 == c] > 0).mean() * 100) for c in cats60]
        bars = ax0_bar.bar(range(3), meds, color=["#EF4444", "#94A3B8", "#16A34A"], alpha=0.85, width=0.58)
        ax0_bar.set_ylim(0, max(meds) * 1.32)
        ax0_bar.set_xticks(range(3))
        ax0_bar.set_xticklabels(cats60, fontsize=8.3, fontweight="bold")
        ax0_bar.set_title("同60日策略收益中位数\n(顶标60日正收益概率)", fontsize=9.2, fontweight="bold", color="#0F172A", pad=4)
        ax0_bar.grid(axis="y", ls=":", alpha=0.35)
        ax0_bar.spines["top"].set_visible(False)
        ax0_bar.spines["right"].set_visible(False)
        ax0_bar.tick_params(axis="y", labelsize=8.2)
        for bar, med, pp in zip(bars, meds, pos_p):
            ax0_bar.text(bar.get_x() + bar.get_width() / 2, med + 4.0, f"+{med:.0f}%\n(胜{pp:.0f}%)",
                         ha="center", va="bottom", fontsize=8.0, fontweight="bold", color="#0F172A")

    # ===== Panels 1~4: V2 Four Validated Orthogonal Components (unified minimalist style) =====
    y1_hi = min(75.0, max(55.0, float(sub["zb_rate"].quantile(0.99)) + 6.0))
    _draw_sub_panel(
        sub_axes[0], x, sub["zb_rate"], smooth,
        title="① 炸板率（甜区: 25%至40%良性分歧  |  雷区: >40%失血 或 <25%过热）",
        ylabel="炸板率 (%)", ylim=(0.0, y1_hi),
        sweet_bands=[(25.0, 40.0)], danger_bands=[(0.0, 25.0), (40.0, y1_hi)],
        hlines=[(25.0, C_DANGER_FG), (40.0, C_DANGER_FG)],
        cur_val_str=f"{last['zb_rate']:.1f}%", cur_status=st["zb"],
    )

    y2_hi = max(6.5, float(sub["max_b_drop5"].quantile(0.99)) + 1.0)
    _draw_sub_panel(
        sub_axes[1], x, sub["max_b_drop5"].fillna(0.0), smooth,
        title=f"② 最高连板5日回落幅（新发现单笔冠军 · 甜区: 回落>=2板老周期出清  |  雷区: 0板仍在顶峰  |  现最高{int(last['max_board'])}板）",
        ylabel="高度回落 (板)", ylim=(-0.3, y2_hi),
        sweet_bands=[(2.0, y2_hi)], danger_bands=[(-0.3, 0.4)],
        hlines=[(2.0, C_SWEET_FG), (0.0, C_DANGER_FG)],
        cur_val_str=f"落{int(last['max_b_drop5'])}板", cur_status=st["mb"],
    )

    y3_hi = min(320.0, max(95.0, float(sub["dt_3d"].quantile(0.98)) * 1.15))
    _draw_sub_panel(
        sub_axes[2], x, sub["dt_3d"].fillna(0.0), smooth,
        title=f"③ 近3日累计跌停家数（甜区: >=40家深洗出清  |  雷区: <=12家浮筹未清  |  昨日单日跌停{int(last['dt_cnt'])}家）",
        ylabel="3日跌停数", ylim=(0.0, y3_hi),
        sweet_bands=[(40.0, y3_hi)], danger_bands=[(0.0, 12.0)],
        hlines=[(40.0, C_SWEET_FG), (12.0, C_DANGER_FG)],
        cur_val_str=f"{int(last['dt_3d'])}家", cur_status=st["d3"],
    )

    y4_lo = min(-2.5, float(sub["prem_3d"].min()) - 0.5)
    y4_hi = max(4.8, float(sub["prem_3d"].quantile(0.99)) + 0.6)
    _draw_sub_panel(
        sub_axes[3], x, sub["prem_3d"].fillna(0.0), smooth,
        title="④ 近3日打板平均溢价（甜区: <=+1.0%洗净低溢价  |  雷区: >+3.0%高潮透支）",
        ylabel="3日溢价 (%)", ylim=(y4_lo, y4_hi),
        sweet_bands=[(y4_lo, 1.0)], danger_bands=[(3.0, y4_hi)],
        hlines=[(1.0, C_SWEET_FG), (3.0, C_DANGER_FG), (0.0, "#64748B")],
        cur_val_str=f"{last['prem_3d']:+.2f}%", cur_status=st["p3"],
    )

    ax_b = sub_axes[3]
    if days <= 80:
        ax_b.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        ax_b.xaxis.set_major_locator(mdates.DayLocator(interval=7))
    elif days <= 270:
        ax_b.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
        ax_b.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    else:
        ax_b.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax_b.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    plt.setp(ax_b.get_xticklabels(), rotation=22, ha="right", fontsize=8.6)
    plt.setp(ax0.get_xticklabels(), visible=False)
    for a in sub_axes[:3]:
        plt.setp(a.get_xticklabels(), visible=False)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def main() -> int:
    mkt = compute_daily_water()
    comb, s60_log = load_strategy_ledger(mkt)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plot_window(mkt, comb, s60_log, days=63, title_tag="近3个月", out_path=OUT_DIR / "mkt_water_3m.png", smooth=1)
    plot_window(mkt, comb, s60_log, days=242, title_tag="近1年", out_path=OUT_DIR / "mkt_water_1y.png", smooth=3)
    plot_window(mkt, comb, s60_log, days=len(mkt), title_tag="近5年", out_path=OUT_DIR / "mkt_water_5y.png", smooth=5)

    last = mkt.iloc[-1]
    d_last = mkt.index[-1]
    st = _eval_statuses(last)
    ok = mkt["macro_water_60d"].notna() & s60_log.notna()
    r60 = round(float(stats.spearmanr(mkt["macro_water_60d"][ok], s60_log[ok])[0]), 3)
    ra = round(float(stats.spearmanr(comb["v2_t1"].dropna(), comb.loc[comb["v2_t1"].notna(), "ret_pct"])[0]), 3)
    summary = {
        "as_of_date": d_last,
        "water_idx": round(float(last["v2_idx"]), 1),
        "water_zone": st["v2"],
        "macro_water_60d": round(float(last["macro_water_60d"]), 1),
        "macro_zone": st["mw"],
        "corr_single_trade": ra,
        "corr_60d_aligned": r60,
        "zb_rate": round(float(last["zb_rate"]), 2),
        "zb_zone": st["zb"],
        "max_b_drop5": int(last["max_b_drop5"]),
        "mb_zone": st["mb"],
        "dt_cnt": int(last["dt_cnt"]),
        "dt_3d": int(last["dt_3d"]),
        "wash_zone": st["d3"],
        "damian_rate": round(float(last["damian_rate"]), 2),
        "zt_cnt": int(last["zt_cnt"]),
        "hi3_cnt": int(last["hi3_cnt"]),
        "max_board": int(last["max_board"]),
        "amt_yi": round(float(last["amt_yi"]), 1),
        "amt_ma20_yi": round(float(last["amt_ma20"]), 1),
        "prem_3d": round(float(last["prem_3d"]), 2),
        "prem_zone": st["p3"],
        "charts": {
            "3m": str(OUT_DIR / "mkt_water_3m.png"),
            "1y": str(OUT_DIR / "mkt_water_1y.png"),
            "5y": str(OUT_DIR / "mkt_water_5y.png"),
        },
    }
    (OUT_DIR / "mkt_water_latest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("V2_ALIGNED_CHARTS_OK:", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
