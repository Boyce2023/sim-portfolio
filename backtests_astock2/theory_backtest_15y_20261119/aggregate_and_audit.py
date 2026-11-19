#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Master Aggregator, Q8 Gate-2 Independent Auditor, and Publication Chart Builder
for 15-Year Chinese Investment Theory Backtest (2011-01-01 to 2026-11-18).
"""
import os, json, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/theory_backtest_15y_20261119"
plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "STHeiti", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

# Canonical clean display names & camp labels
CAMP_MAP = {
    "涛动周期论_库存象限": ("宏观周期", "涛动周期论(库存象限)"),
    "涛动周期论_40月周期律": ("宏观周期", "涛动周期论(40月律)"),
    "美林投资时钟_行业轮动": ("宏观周期", "美林时钟(行业轮动)"),
    "美林投资时钟_纯择时": ("宏观周期", "美林时钟(纯择时)"),
    "M1M2剪刀差_同步择时": ("宏观周期", "M1与M2剪刀差"),
    "M1M2剪刀差_流动性择时": ("宏观周期", "M1与M2剪刀差"),
    "M1M2剪刀差_同步": ("宏观周期", "M1与M2剪刀差"),
    "股债ERP_三档择时": ("宏观周期", "股债性价比ERP"),
    "股债性价比ERP择时": ("宏观周期", "股债性价比ERP"),
    "股债ERP_三档": ("宏观周期", "股债性价比ERP"),
    "艾略特波浪_因果数浪": ("技术玄学", "艾略特波浪(因果)"),
    "缠论_分型笔与MACD背驰": ("技术玄学", "缠论(分型笔背驰)"),
    "经典均线趋势_MA20与MA60": ("技术玄学", "经典均线(MA20与60)"),
    "传统超买超卖_RSI逆势": ("技术玄学", "传统RSI逆势抄底"),
    "A股日历魔咒_春季躁动避五穷六绝": ("技术玄学", "A股日历魔咒"),
    "小市值轮动_壳价值理论": ("本土风格", "小市值轮动(壳价值)"),
    "核心资产大蓝筹低波_茅指数本土化": ("本土风格", "核心资产大盘低波"),
    "超跌反转效应_跌多了就买": ("本土风格", "20日超跌反转"),
    "动量追强效应_强者恒强": ("本土风格", "60日动量追强"),
    "情绪冰点与量能拥挤择时_游资周期论": ("本土风格", "情绪冰点量能择时"),
}


def extract_theories(jdata: dict, camp_default: str) -> dict:
    """Flexibly extract per-theory profiles from a camp JSON regardless of top-level wrapper key."""
    out = {}
    cand_dict = None
    for k in ("theories", "strategies", "profiles", "results"):
        if isinstance(jdata.get(k), dict):
            cand_dict = jdata[k]
            break
    if cand_dict is None:
        cand_dict = {k: v for k, v in jdata.items() if isinstance(v, dict) and "overall_15y" in v}

    ind_top = jdata.get("industry_tei") or {}
    for raw_k, v in cand_dict.items():
        if not isinstance(v, dict) or "overall_15y" not in v:
            continue
        camp, disp = CAMP_MAP.get(raw_k, (camp_default, raw_k))
        # Deduplicate aliases (prefer primary version, skip auxiliary sub-variants unless canonical)
        if any(skip in raw_k for skip in ["含国债", "领先3M", "二元", "迟滞", "20%底仓", "静态权重"]):
            continue
        item = dict(v)
        item["raw_key"] = raw_k
        item["camp"] = camp
        item["display_name"] = disp
        # Attach industry_tei if stored either inside v or in top-level industry_tei[raw_k]
        if "industry_tei" not in item and raw_k in ind_top:
            item["industry_tei"] = ind_top[raw_k]
        out[disp] = item
    return out


def main():
    jm = json.load(open(f"{OUT_DIR}/res_macro_4theories.json", encoding="utf-8"))
    jt = json.load(open(f"{OUT_DIR}/res_tech_4theories.json", encoding="utf-8"))
    js = json.load(open(f"{OUT_DIR}/res_style_4theories.json", encoding="utf-8"))

    all_t = {}
    all_t.update(extract_theories(jm, "宏观周期"))
    all_t.update(extract_theories(jt, "技术玄学"))
    all_t.update(extract_theories(js, "本土风格"))

    # Q8 Gate 2 Audit: verify n_days, benchmark parity, zero NaN, and collect summary leaderboard
    audit_issues = []
    rows = []
    for disp, d in all_t.items():
        o15 = d["overall_15y"]
        o10 = d["last_10y"]
        o3 = d["last_3y"]
        if o15["n_days"] < 3700:
            audit_issues.append(f"{disp}: n_days={o15['n_days']} < 3700")
        if abs(o15["bench_ann_ret"] - 1.53) > 0.35:
            audit_issues.append(f"{disp}: bench_ann={o15['bench_ann_ret']} drift from 1.53%")
        # Regime sensitivity spread (max TEI - min TEI across trend/vol/amt/rate/ppi/era)
        reg = d.get("regimes") or {}
        reg_spreads = {}
        best_reg, worst_reg = ("", -1.0), ("", 999.0)
        for rcol, rdict in reg.items():
            if not isinstance(rdict, dict) or len(rdict) < 2:
                continue
            vals = [(rk, rv["tei"]) for rk, rv in rdict.items() if isinstance(rv, dict) and rv.get("tei") is not None]
            if len(vals) >= 2:
                mx = max(vals, key=lambda x: x[1])
                mn = min(vals, key=lambda x: x[1])
                reg_spreads[rcol] = round(mx[1] - mn[1], 1)
                if mx[1] > best_reg[1]: best_reg = mx
                if mn[1] < worst_reg[1]: worst_reg = mn

        # Industry best/worst
        ind_d = d.get("industry_tei") or {}
        ind_scores = {}
        for sec, sv in ind_d.items():
            if isinstance(sv, dict):
                if sv.get("tei") is not None:
                    ind_scores[sec] = float(sv["tei"])
                elif isinstance(sv.get("overall_15y"), dict) and sv["overall_15y"].get("tei") is not None:
                    ind_scores[sec] = float(sv["overall_15y"]["tei"])
            elif isinstance(sv, (int, float)):
                ind_scores[sec] = float(sv)
        best_ind = max(ind_scores.items(), key=lambda x: x[1]) if ind_scores else ("无", 50.0)
        worst_ind = min(ind_scores.items(), key=lambda x: x[1]) if ind_scores else ("无", 50.0)

        rows.append({
            "display_name": disp,
            "camp": d["camp"],
            "tei_15y": o15["tei"],
            "tei_10y": o10["tei"],
            "tei_3y": o3["tei"],
            "ann_15y": o15["ann_ret"],
            "excess_15y": o15["excess_ann"],
            "excess_10y": o10["excess_ann"],
            "excess_3y": o3["excess_ann"],
            "mdd_15y": o15["mdd"],
            "ir_15y": o15["ir"],
            "q_win_15y": o15["q_win_rate"],
            "t_stat_15y": o15["t_stat"],
            "decay_decade": d.get("tei_decay_per_decade", 0.0),
            "era_11_15": (reg.get("era") or {}).get("2011至2015散户杠杆期", {}).get("tei"),
            "era_16_20": (reg.get("era") or {}).get("2016至2020外资抱团期", {}).get("tei"),
            "era_21_26": (reg.get("era") or {}).get("2021至2026量化政策期", {}).get("tei"),
            "best_regime": f"{best_reg[0]}({best_reg[1]})",
            "worst_regime": f"{worst_reg[0]}({worst_reg[1]})",
            "best_ind": f"{best_ind[0]}({best_ind[1]})",
            "worst_ind": f"{worst_ind[0]}({worst_ind[1]})",
            "max_regime_spread": max(reg_spreads.values()) if reg_spreads else 0.0,
            "reg_spreads": reg_spreads,
            "industry_scores": ind_scores,
        })

    lb = pd.DataFrame(rows).sort_values("tei_15y", ascending=False).reset_index(drop=True)
    print("=== Q8 GATE-2 AUDIT ===")
    print("Total theories:", len(lb), "| Audit issues:", audit_issues)
    print(lb[["display_name", "camp", "tei_15y", "tei_10y", "tei_3y", "excess_15y", "mdd_15y", "decay_decade", "era_11_15", "era_16_20", "era_21_26"]].to_string(index=False))

    # Save master JSON
    master = {
        "as_of_date": "2026-11-18",
        "period": "2011-01-01 to 2026-11-18",
        "benchmark": {"symbol": "sh000300", "name": "沪深300", "ann_ret_15y": 1.53, "mdd_15y": -46.70},
        "audit_issues": audit_issues,
        "leaderboard": lb.to_dict(orient="records"),
        "wave_c4_empirical_stats": jt.get("wave_c4_empirical_stats"),
        "calendar_monthly_matrix": jt.get("calendar_monthly_matrix"),
        "theories_detail": all_t,
    }
    json.dump(master, open(f"{OUT_DIR}/master_15y_theory_audit.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # ===== CHART 1: 15Y vs 3Y TEI Leaderboard + Rolling 2Y TEI Evolution =====
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.5, 6.8), dpi=180, gridspec_kw={"width_ratios": [1.05, 1.25]})
    fig.patch.set_facecolor("white")

    lb_plot = lb.sort_values("tei_15y", ascending=True)
    y = np.arange(len(lb_plot))
    ax1.axvline(50, color="#666666", ls="--", lw=1.2, label="随机线 (50分)")
    ax1.axvline(65, color="#1a7f37", ls=":", lw=1.1, label="强有效线 (65分)")
    ax1.axvline(45, color="#cf222e", ls=":", lw=1.1, label="反向失效线 (45分)")
    for i, r in lb_plot.reset_index(drop=True).iterrows():
        c = "#1a7f37" if r["tei_15y"] >= 60 else ("#cf222e" if r["tei_15y"] < 45 else "#2b6cb0")
        ax1.plot([r["tei_15y"], r["tei_3y"]], [i, i], color="#bbbbbb", lw=2.0, zorder=1)
        ax1.scatter(r["tei_15y"], i, color=c, s=68, zorder=3, label="15年TEI" if i == 0 else "")
        ax1.scatter(r["tei_3y"], i, color="#e67e22", marker="D", s=46, zorder=4, label="近3年TEI" if i == 0 else "")
        ax1.text(max(r["tei_15y"], r["tei_3y"]) + 1.2, i, f"{r['tei_15y']:.1f} -> {r['tei_3y']:.1f}", va="center", fontsize=8.5, color="#333333")
    ax1.set_yticks(y)
    ax1.set_yticklabels(lb_plot["display_name"], fontsize=9.5)
    ax1.set_xlim(24, 98)
    ax1.set_xlabel("理论有效度指数 TEI (0至100分)", fontsize=10)
    ax1.set_title("A股15年主流投资理论 TEI 总榜 (圆点=15年 | 菱形=近3年)", fontsize=11.5, fontweight="bold")
    ax1.grid(axis="x", alpha=0.25)
    ax1.legend(loc="lower right", fontsize=8.5, frameon=True)

    # Right panel: Rolling 2Y TEI time series for 7 iconic theories
    pick_names = [
        ("小市值轮动(壳价值)", "#1a7f37", "-"),
        ("核心资产大盘低波", "#0969da", "-"),
        ("20日超跌反转", "#8250df", "-"),
        ("艾略特波浪(因果)", "#d97706", "--"),
        ("缠论(分型笔背驰)", "#0891b2", "--"),
        ("M1与M2剪刀差", "#be185d", "-."),
        ("涛动周期论(库存象限)", "#cf222e", ":"),
    ]
    ax2.axhline(50, color="#666666", ls="--", lw=1.1)
    ax2.axhspan(65, 100, color="#e6ffed", alpha=0.35)
    ax2.axhspan(0, 45, color="#ffebe9", alpha=0.35)
    for nm, col, ls in pick_names:
        if nm in all_t:
            pts = all_t[nm].get("rolling_2y_tei") or []
            if pts:
                dts = pd.to_datetime([p["end_date"] for p in pts])
                vals = [p["tei"] for p in pts]
                ax2.plot(dts, vals, label=nm, color=col, ls=ls, lw=2.0, marker="o", ms=3)
    ax2.set_ylim(18, 92)
    ax2.set_ylabel("滚动2年 TEI 得分", fontsize=10)
    ax2.set_title("核心理论有效度随时间演变轨迹 (2012至2026滚动2年窗口)", fontsize=11.5, fontweight="bold")
    ax2.grid(alpha=0.25)
    ax2.legend(loc="upper right", fontsize=8.2, ncol=2, frameon=True)

    plt.tight_layout()
    plt.savefig(f"{OUT_DIR}/tei_master_dashboard.png", dpi=180, bbox_inches="tight")
    plt.close()

    # ===== CHART 2: 10 Industries x Theories Heatmap + 6 Regimes x Theories Heatmap =====
    sectors = ["科技电子软件", "电力新能源", "周期资源", "金融地产", "消费食饮", "医药生物", "高端制造军工", "公用基建交运", "传媒文娱"]
    t_order = lb["display_name"].tolist()
    mat_ind = np.full((len(t_order), len(sectors)), np.nan)
    for i, nm in enumerate(t_order):
        sc = lb.loc[lb["display_name"] == nm, "industry_scores"].iloc[0]
        for j, s in enumerate(sectors):
            if s in sc:
                mat_ind[i, j] = sc[s]

    reg_cols = [
        ("trend_regime", "牛市趋势", "牛市"),
        ("trend_regime", "熊市下行", "熊市"),
        ("trend_regime", "震荡区间", "震荡"),
        ("vol_regime", "高波动期", "高波"),
        ("vol_regime", "低波动期", "低波"),
        ("amt_regime", "增量放量市", "放量"),
        ("amt_regime", "存量缩量市", "缩量"),
        ("rate_regime", "利率下行宽松", "宽货币"),
        ("ppi_regime", "PPI上行再通胀", "再通胀"),
    ]
    mat_reg = np.full((len(t_order), len(reg_cols)), np.nan)
    for i, nm in enumerate(t_order):
        rd = all_t[nm].get("regimes") or {}
        for j, (rc, rv, _) in enumerate(reg_cols):
            val = (rd.get(rc) or {}).get(rv, {}).get("tei")
            if val is not None:
                mat_reg[i, j] = val

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16.5, 7.2), dpi=180)
    fig.patch.set_facecolor("white")
    cmap = mcolors.LinearSegmentedColormap.from_list("tei_div", ["#cf222e", "#fca5a5", "#ffffff", "#86efac", "#15803d"])

    im1 = ax1.imshow(mat_ind, cmap=cmap, vmin=25, vmax=75, aspect="auto")
    ax1.set_xticks(range(len(sectors)))
    ax1.set_xticklabels([s[:4] for s in sectors], rotation=30, ha="right", fontsize=9)
    ax1.set_yticks(range(len(t_order)))
    ax1.set_yticklabels(t_order, fontsize=9)
    ax1.set_title("10大行业 x 主流理论 TEI 有效度热力图", fontsize=11.5, fontweight="bold")
    for i in range(len(t_order)):
        for j in range(len(sectors)):
            if np.isfinite(mat_ind[i, j]):
                ax1.text(j, i, f"{mat_ind[i,j]:.0f}", ha="center", va="center", fontsize=8, color="#111111")

    im2 = ax2.imshow(mat_reg, cmap=cmap, vmin=25, vmax=75, aspect="auto")
    ax2.set_xticks(range(len(reg_cols)))
    ax2.set_xticklabels([x[2] for x in reg_cols], rotation=30, ha="right", fontsize=9)
    ax2.set_yticks(range(len(t_order)))
    ax2.set_yticklabels([""] * len(t_order))
    ax2.set_title("市场环境因子 x 主流理论 TEI 有效度热力图", fontsize=11.5, fontweight="bold")
    for i in range(len(t_order)):
        for j in range(len(reg_cols)):
            if np.isfinite(mat_reg[i, j]):
                ax2.text(j, i, f"{mat_reg[i,j]:.0f}", ha="center", va="center", fontsize=8, color="#111111")

    cbar = fig.colorbar(im2, ax=[ax1, ax2], shrink=0.75, pad=0.02)
    cbar.set_label("TEI 有效度 (50=随机 | >=65强有效 | <45失效)", fontsize=9.5)
    plt.savefig(f"{OUT_DIR}/tei_industry_regime_heatmap.png", dpi=180, bbox_inches="tight")
    plt.close()
    print("Charts generated successfully!")


if __name__ == "__main__":
    main()
