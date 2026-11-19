#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Camp A: Macro Cycle & Liquidity 4-Theory Empirical Backtest (2011-01-01 to 2026-11-18).
Strictly PIT (merge_asof backward on pit_date + signal.shift(1)) and 0.15% one-way cost.
Zero yfinance usage (D12). Uses unified tei_metrics (D15).
"""
import json
import os
import sys
import numpy as np
import pandas as pd

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/theory_backtest_15y_20261119"
DATA_DIR = os.path.join(BASE_DIR, "data_cache")
sys.path.insert(0, BASE_DIR)
import tei_metrics  # noqa: E402

START_DATE = "2011-01-01"
END_DATE = "2026-11-18"
ONE_WAY_COST = 0.0015


def rolling_percentile_strict(series: pd.Series, window: int = 1210, min_periods: int = 242) -> pd.Series:
    """Strictly backward-only rolling percentile rank within [t-window+1, t]."""
    arr = series.to_numpy(dtype=float)
    out = np.full(len(arr), np.nan)
    for i in range(len(arr)):
        val = arr[i]
        if np.isnan(val):
            continue
        w = arr[max(0, i - window + 1):i + 1]
        w = w[~np.isnan(w)]
        if len(w) >= min_periods:
            out[i] = float(np.mean(w <= val))
    return pd.Series(out, index=series.index)


def load_and_build_pit_table():
    """Load clean datasets and merge macro indicators strictly on pit_date."""
    bi = pd.read_parquet(os.path.join(DATA_DIR, "broad_indices_15y.parquet"))
    hs = bi[bi["symbol"] == "sh000300"].sort_values("date").reset_index(drop=True)
    hs["ret"] = hs["close"].pct_change()

    sec_cw = pd.read_parquet(os.path.join(DATA_DIR, "sector_ret_cw_15y.parquet")).sort_index()
    regime_df = pd.read_parquet(os.path.join(DATA_DIR, "regime_daily_15y.parquet")).sort_index()
    bond = pd.read_parquet(os.path.join(DATA_DIR, "macro_bond10y.parquet")).sort_values("date")

    ppi = pd.read_parquet(os.path.join(DATA_DIR, "macro_ppi_full.parquet")).sort_values("pit_date").copy()
    pmi = pd.read_parquet(os.path.join(DATA_DIR, "macro_pmi_full.parquet")).sort_values("pit_date").copy()
    cpi = pd.read_parquet(os.path.join(DATA_DIR, "macro_cpi_full.parquet")).sort_values("pit_date").copy()
    m12 = pd.read_parquet(os.path.join(DATA_DIR, "macro_m1m2.parquet")).sort_values("pit_date").copy()
    pe = pd.read_parquet(os.path.join(DATA_DIR, "csi300_pe_lg.parquet")).copy()
    pe["pe_date"] = pd.to_datetime(pe["日期"])
    pe = pe.sort_values("pe_date")

    # Compute macro momentums on monthly series BEFORE daily merge_asof
    ppi["ppi_m3"] = ppi["val"] - ppi["val"].shift(3)
    pmi["pmi_m3"] = pmi["val"] - pmi["val"].shift(3)
    pmi["pmi_yoy"] = pmi["val"] - pmi["val"].shift(12)
    cpi["cpi_m3"] = cpi["val"] - cpi["val"].shift(3)
    m12["diff_m3"] = m12["m1_m2_diff"] - m12["m1_m2_diff"].shift(3)
    m12["m1_m3"] = m12["m1_yoy"] - m12["m1_yoy"].shift(3)
    m12["liq_ok"] = (m12["diff_m3"] > 0) | (m12["m1_m3"] > 0)
    m12["liq_ok_lag3"] = m12["liq_ok"].shift(3).eq(True)

    df = hs[["date", "close", "ret"]].copy()
    merges = [
        (ppi[["pit_date", "val", "ppi_m3"]].rename(columns={"val": "ppi"}), "pit_date"),
        (pmi[["pit_date", "val", "pmi_m3", "pmi_yoy"]].rename(columns={"val": "pmi"}), "pit_date"),
        (cpi[["pit_date", "val", "cpi_m3"]].rename(columns={"val": "cpi"}), "pit_date"),
        (m12[["pit_date", "m1_yoy", "m2_yoy", "m1_m2_diff", "diff_m3", "m1_m3", "liq_ok", "liq_ok_lag3"]], "pit_date"),
        (bond[["date", "cn10y"]].rename(columns={"date": "bond_date"}), "bond_date"),
        (pe[["pe_date", "指数", "滚动市盈率"]].rename(columns={"指数": "pe_idx", "滚动市盈率": "pe_ttm"}), "pe_date"),
    ]
    for right_df, rcol in merges:
        df = pd.merge_asof(df, right_df, left_on="date", right_on=rcol, direction="backward")
        if rcol != "date":
            df = df.drop(columns=[rcol])

    df = df.set_index("date")
    df["pe_daily"] = df["pe_ttm"] * (df["close"] / df["pe_idx"])
    df["erp_daily"] = 100.0 / df["pe_daily"] - df["cn10y"]
    df["erp_step"] = 100.0 / df["pe_ttm"] - df["cn10y"]
    df["erp_pct_daily"] = rolling_percentile_strict(df["erp_daily"], window=1210, min_periods=242)
    df["erp_pct_step"] = rolling_percentile_strict(df["erp_step"], window=1210, min_periods=242)
    df["cash_bond_ret"] = (df["cn10y"].shift(1) / 100.0 / 242.0).fillna(0.0)
    return df, sec_cw, regime_df


def simulate_single(w_signal: pd.Series, asset_ret: pd.Series, cash_ret: pd.Series = None):
    """Apply shift(1) to signal formed at t-1 close, deduct 0.15% one-way cost on turnover."""
    w_exec = w_signal.shift(1).loc[START_DATE:END_DATE].astype(float)
    r_a = asset_ret.loc[START_DATE:END_DATE].astype(float)
    r_c = cash_ret.loc[START_DATE:END_DATE].astype(float) if cash_ret is not None else 0.0
    to = w_exec.diff().abs()
    to.iloc[0] = abs(w_exec.iloc[0])
    cost = to * ONE_WAY_COST
    strat_ret = w_exec * r_a + (1.0 - w_exec) * r_c - cost
    stats = {
        "n_rebalances": int((to > 1e-9).sum()),
        "total_turnover": round(float(to.sum()), 3),
        "ann_turnover": round(float(to.sum() / (len(w_exec) / 242.0)), 3),
        "cum_cost_pct": round(float(cost.sum() * 100.0), 2),
        "avg_weight_pct": round(float(w_exec.mean() * 100.0), 1),
    }
    return strat_ret, w_exec, stats


def simulate_multi(W_signal: pd.DataFrame, ret_df: pd.DataFrame, cash_ret: pd.Series = None):
    """Multi-asset rotation with shift(1) and 0.15% per one-way leg turnover."""
    W_exec = W_signal.shift(1).loc[START_DATE:END_DATE].astype(float)
    R = ret_df.loc[START_DATE:END_DATE, W_exec.columns].astype(float)
    r_c = cash_ret.loc[START_DATE:END_DATE].astype(float) if cash_ret is not None else 0.0
    to_df = W_exec.diff().abs()
    to_df.iloc[0] = W_exec.iloc[0].abs()
    to = to_df.sum(axis=1)
    cost = to * ONE_WAY_COST
    w_sum = W_exec.sum(axis=1)
    strat_ret = (W_exec * R).sum(axis=1) + (1.0 - w_sum) * r_c - cost
    stats = {
        "n_rebalances": int((to > 1e-9).sum()),
        "total_turnover": round(float(to.sum()), 3),
        "ann_turnover": round(float(to.sum() / (len(W_exec) / 242.0)), 3),
        "cum_cost_pct": round(float(cost.sum() * 100.0), 2),
        "avg_weight_pct": round(float(w_sum.mean() * 100.0), 1),
    }
    return strat_ret, w_sum, stats


def eval_industry_matrix(w_signal: pd.Series, sec_cw: pd.DataFrame):
    """Apply timing signal across all 10 sectors vs each sector's own buy-and-hold."""
    out = {}
    for col in sec_cw.columns:
        b = sec_cw.loc[START_DATE:END_DATE, col]
        s, w_exec, _ = simulate_single(w_signal, sec_cw[col])
        m15 = tei_metrics.compute_period_metrics(s, b, w_exec)
        m10 = tei_metrics.compute_period_metrics(s.loc["2016-11-19":], b.loc["2016-11-19":], w_exec.loc["2016-11-19":])
        m3 = tei_metrics.compute_period_metrics(s.loc["2023-11-19":], b.loc["2023-11-19":], w_exec.loc["2023-11-19":])
        dd_abs_red = round(abs(m15["bench_mdd"]) - abs(m15["mdd"]), 2)
        dd_rel_red = round((abs(m15["bench_mdd"]) - abs(m15["mdd"])) / abs(m15["bench_mdd"]) * 100.0, 1) if abs(m15["bench_mdd"]) > 0 else 0.0
        out[col] = {
            "tei": m15["tei"],
            "last_10y_tei": m10["tei"],
            "last_3y_tei": m3["tei"],
            "ann_ret": m15["ann_ret"],
            "bench_ann_ret": m15["bench_ann_ret"],
            "excess_ann": m15["excess_ann"],
            "last_10y_excess": m10["excess_ann"],
            "last_3y_excess": m3["excess_ann"],
            "mdd": m15["mdd"],
            "bench_mdd": m15["bench_mdd"],
            "mdd_reduction_pp": dd_abs_red,
            "mdd_reduction_rel_pct": dd_rel_red,
            "ir": m15["ir"],
            "sharpe": m15["sharpe"],
        }
    return out


def quadrant_stats(quad_signal: pd.Series, strat_ret: pd.Series, bench_ret: pd.Series):
    """Evaluate realized performance inside each signal quadrant (shifted to executed day)."""
    q_exec = quad_signal.shift(1).loc[START_DATE:END_DATE]
    res = {}
    total_n = len(q_exec)
    for label, idx in q_exec.groupby(q_exec).groups.items():
        if len(idx) < 5:
            continue
        m = tei_metrics.compute_period_metrics(strat_ret.loc[idx], bench_ret.loc[idx])
        res[str(label)] = {
            "n_days": int(len(idx)),
            "time_share_pct": round(len(idx) / total_n * 100.0, 1),
            "ann_ret": m["ann_ret"],
            "bench_ann_ret": m["bench_ann_ret"],
            "excess_ann": m["excess_ann"],
            "ir": m["ir"],
        }
    return res


def extreme_year_audit(profile: dict, df15: pd.DataFrame, w_exec: pd.Series):
    """Audit best, worst, and iconic shock years (2015, 2018, 2020, 2022, 2024, 2026)."""
    by_y = profile["by_year"]
    sorted_y = sorted(by_y.items(), key=lambda kv: kv[1]["excess_ann"])
    pick_years = sorted({sorted_y[0][0], sorted_y[-1][0], "2015", "2018", "2020", "2022", "2024", "2026"} & set(by_y.keys()))
    audit = {}
    for yr in pick_years:
        mask = df15.index.year == int(yr)
        sub = df15.loc[mask]
        w_sub = w_exec.loc[mask]
        audit[yr] = {
            "ann_ret": by_y[yr]["ann_ret"],
            "excess_ann": by_y[yr]["excess_ann"],
            "mdd": by_y[yr]["mdd"],
            "tei": by_y[yr]["tei"],
            "avg_weight_pct": round(float(w_sub.mean() * 100.0), 1),
            "pmi_m3_mean": round(float(sub["pmi_m3"].mean()), 2),
            "ppi_m3_mean": round(float(sub["ppi_m3"].mean()), 2),
            "cpi_m3_mean": round(float(sub["cpi_m3"].mean()), 2),
            "m1_m2_diff_mean": round(float(sub["m1_m2_diff"].mean()), 2),
            "erp_pct_mean": round(float(sub["erp_pct_daily"].mean() * 100.0), 1),
        }
    return audit


def make_hysteresis_erp(pct_series: pd.Series, buy_th: float = 0.70, sell_th: float = 0.30) -> pd.Series:
    arr = pct_series.to_numpy(dtype=float)
    out = np.zeros(len(arr))
    state, started = 0.0, False
    for i, p in enumerate(arr):
        if np.isnan(p):
            continue
        if not started:
            state = 1.0 if p >= 0.50 else 0.0
            started = True
        elif p >= buy_th:
            state = 1.0
        elif p < sell_th:
            state = 0.0
        out[i] = state
    return pd.Series(out, index=pct_series.index)


def summarize_bond_ref(strat_bond: pd.Series, bench: pd.Series, w_exec: pd.Series):
    m15 = tei_metrics.compute_period_metrics(strat_bond, bench, w_exec)
    m10 = tei_metrics.compute_period_metrics(strat_bond.loc["2016-11-19":], bench.loc["2016-11-19":], w_exec.loc["2016-11-19":])
    m3 = tei_metrics.compute_period_metrics(strat_bond.loc["2023-11-19":], bench.loc["2023-11-19":], w_exec.loc["2023-11-19":])
    return {
        "tei_15y": m15["tei"], "ann_ret_15y": m15["ann_ret"], "excess_15y": m15["excess_ann"], "mdd_15y": m15["mdd"],
        "tei_10y": m10["tei"], "excess_10y": m10["excess_ann"],
        "tei_3y": m3["tei"], "excess_3y": m3["excess_ann"],
    }


def main():
    df, sec_cw, regime_df = load_and_build_pit_table()
    df15 = df.loc[START_DATE:END_DATE]
    bench = df15["ret"]

    # Combine sh000300 and sector returns for multi-asset strategies
    ret_universe = sec_cw.reindex(df.index).copy()
    ret_universe["sh000300"] = df["ret"]

    # --- Build core signals ---
    # 1. 涛动周期论_库存象限
    q_inv = pd.Series(
        np.where(df["pmi_m3"] > 0,
                 np.where(df["ppi_m3"] > 0, "主动补库", "被动去库"),
                 np.where(df["ppi_m3"] > 0, "被动补库", "主动去库")),
        index=df.index,
    )
    w_inv = pd.Series(np.where(df["pmi_m3"] > 0, 1.0, np.where(df["ppi_m3"] > 0, 0.30, 0.0)), index=df.index)

    # 2. 涛动周期论_40月周期律
    anchor = pd.Timestamp("2008-11-01")
    phase = (df.index - anchor).days % 1217
    q_40m = pd.Series(np.where(phase < 608.5, "上半周期做多(0-20月)", "下半周期防御(20-40月)"), index=df.index)
    w_40m = pd.Series(np.where(phase < 608.5, 1.0, 0.0), index=df.index)
    # Sensitivity check with 2008-11-04 exact CSI300 bottom
    phase_04 = (df.index - pd.Timestamp("2008-11-04")).days % 1217
    w_40m_04 = pd.Series(np.where(phase_04 < 608.5, 1.0, 0.0), index=df.index)

    # 3. 美林投资时钟_中国版
    q_ml = pd.Series(
        np.where(df["pmi_m3"] > 0,
                 np.where(df["cpi_m3"] > 0, "过热(增升胀升)", "复苏(增升胀降)"),
                 np.where(df["cpi_m3"] > 0, "滞胀(增降胀升)", "衰退(增降胀降)")),
        index=df.index,
    )
    w_ml_pure = pd.Series(np.where(df["pmi_m3"] > 0, 1.0, np.where(df["cpi_m3"] > 0, 0.0, 0.50)), index=df.index)

    W_ml_rot = pd.DataFrame(0.0, index=df.index, columns=["sh000300", "周期资源", "公用基建交运", "科技电子软件"])
    W_ml_rot.loc[(df["pmi_m3"] > 0) & (df["cpi_m3"] <= 0), "sh000300"] = 1.0
    W_ml_rot.loc[(df["pmi_m3"] > 0) & (df["cpi_m3"] > 0), "周期资源"] = 1.0
    W_ml_rot.loc[(df["pmi_m3"] <= 0) & (df["cpi_m3"] <= 0), "公用基建交运"] = 1.0

    # Variant: Recession 50% utilities, Recovery -> Tech Growth
    W_ml_rot_half_rec = W_ml_rot.copy()
    W_ml_rot_half_rec.loc[(df["pmi_m3"] <= 0) & (df["cpi_m3"] <= 0), "公用基建交运"] = 0.5
    W_ml_rot_tech = W_ml_rot.copy()
    recov_mask = (df["pmi_m3"] > 0) & (df["cpi_m3"] <= 0)
    W_ml_rot_tech.loc[recov_mask, "sh000300"] = 0.0
    W_ml_rot_tech.loc[recov_mask, "科技电子软件"] = 1.0
    w_ml_pure_yoy = pd.Series(np.where(df["pmi_yoy"] > 0, 1.0, np.where(df["cpi_m3"] > 0, 0.0, 0.50)), index=df.index)

    # 4. M1M2剪刀差_流动性择时
    q_m12 = pd.Series(np.where(df["liq_ok"], "流动性改善(M1-M2或M1升)", "流动性双降"), index=df.index)
    w_m12_0 = pd.Series(np.where(df["liq_ok"], 1.0, 0.0), index=df.index)
    w_m12_20 = pd.Series(np.where(df["liq_ok"], 1.0, 0.20), index=df.index)
    q_m12_lag3 = pd.Series(np.where(df["liq_ok_lag3"], "3M前流动性改善", "3M前流动性双降"), index=df.index)
    w_m12_lag3 = pd.Series(np.where(df["liq_ok_lag3"], 1.0, 0.0), index=df.index)

    # 5. 股债性价比ERP择时
    q_erp = pd.Series(
        np.where(df["erp_pct_daily"] >= 0.70, "ERP高分位(>=70%)",
                 np.where(df["erp_pct_daily"] >= 0.30, "ERP中分位(30-70%)", "ERP低分位(<30%)")),
        index=df.index,
    )
    w_erp_3tier = pd.Series(np.where(df["erp_pct_daily"] >= 0.70, 1.0, np.where(df["erp_pct_daily"] >= 0.30, 0.60, 0.20)), index=df.index)
    q_erp_bin50 = pd.Series(np.where(df["erp_pct_daily"] >= 0.50, "ERP>=50%分位(做多)", "ERP<50%分位(空仓)"), index=df.index)
    w_erp_bin50 = pd.Series(np.where(df["erp_pct_daily"] >= 0.50, 1.0, 0.0), index=df.index)
    w_erp_hyst = make_hysteresis_erp(df["erp_pct_daily"], 0.70, 0.30)
    w_erp_step_3tier = pd.Series(np.where(df["erp_pct_step"] >= 0.70, 1.0, np.where(df["erp_pct_step"] >= 0.30, 0.60, 0.20)), index=df.index)

    # Primary & key sub-strategies to evaluate fully
    specs = [
        ("涛动周期论_库存象限", "single", w_inv, w_inv, q_inv),
        ("涛动周期论_40月周期律", "single", w_40m, w_40m, q_40m),
        ("美林投资时钟_行业轮动", "multi", W_ml_rot, w_ml_pure, q_ml),
        ("美林投资时钟_纯择时", "single", w_ml_pure, w_ml_pure, q_ml),
        ("M1M2剪刀差_同步择时", "single", w_m12_0, w_m12_0, q_m12),
        ("M1M2剪刀差_领先3M滞后", "single", w_m12_lag3, w_m12_lag3, q_m12_lag3),
        ("股债ERP_三档择时", "single", w_erp_3tier, w_erp_3tier, q_erp),
        ("股债ERP_二元50分位", "single", w_erp_bin50, w_erp_bin50, q_erp_bin50),
    ]

    results = {}
    daily_rets = {"sh000300_基准": bench}

    for name, mode, sig, ind_sig, q_ser in specs:
        if mode == "single":
            s_cash, w_exec, stats = simulate_single(sig, df["ret"])
            s_bond, _, _ = simulate_single(sig, df["ret"], df["cash_bond_ret"])
        else:
            s_cash, w_exec, stats = simulate_multi(sig, ret_universe)
            s_bond, _, _ = simulate_multi(sig, ret_universe, df["cash_bond_ret"])

        profile = tei_metrics.evaluate_full_profile(name, s_cash, bench, regime_df, w_exec)
        profile["signal_stats"] = stats
        profile["quadrant_breakdown"] = quadrant_stats(q_ser, s_cash, bench)
        profile["bond_cash_ref"] = summarize_bond_ref(s_bond, bench, w_exec)
        profile["industry_tei"] = eval_industry_matrix(ind_sig, sec_cw)
        profile["extreme_year_audit"] = extreme_year_audit(profile, df15, w_exec)
        results[name] = profile
        daily_rets[name] = s_cash

    # Variant checks (stored cleanly under metadata)
    variants = {}
    variant_specs = [
        ("40月周期律_锚点20081104", "single", w_40m_04),
        ("美林_行业轮动_衰退50公用", "multi", W_ml_rot_half_rec),
        ("美林_行业轮动_复苏科技成长", "multi", W_ml_rot_tech),
        ("美林_纯择时_PMI同比口径", "single", w_ml_pure_yoy),
        ("M1M2剪刀差_双降20底仓", "single", w_m12_20),
        ("股债ERP_二元迟滞7030", "single", w_erp_hyst),
        ("股债ERP_月度快照PE", "single", w_erp_step_3tier),
    ]
    for vname, vmode, vsig in variant_specs:
        if vmode == "single":
            sv, wv, vstats = simulate_single(vsig, df["ret"])
        else:
            sv, wv, vstats = simulate_multi(vsig, ret_universe)
        m15 = tei_metrics.compute_period_metrics(sv, bench, wv)
        m10 = tei_metrics.compute_period_metrics(sv.loc["2016-11-19":], bench.loc["2016-11-19":], wv.loc["2016-11-19":])
        m3 = tei_metrics.compute_period_metrics(sv.loc["2023-11-19":], bench.loc["2023-11-19":], wv.loc["2023-11-19":])
        variants[vname] = {
            "overall_15y": m15, "last_10y": m10, "last_3y": m3, "signal_stats": vstats,
        }
        daily_rets[vname] = sv

    # Static blend counterfactual for Merrill Lynch Sector Rotation
    q_ml_exec = q_ml.shift(1).loc[START_DATE:END_DATE]
    shares = q_ml_exec.value_counts(normalize=True).to_dict()
    static_ret = (
        shares.get("复苏(增升胀降)", 0.0) * ret_universe.loc[START_DATE:END_DATE, "sh000300"]
        + shares.get("过热(增升胀升)", 0.0) * ret_universe.loc[START_DATE:END_DATE, "周期资源"]
        + shares.get("衰退(增降胀降)", 0.0) * ret_universe.loc[START_DATE:END_DATE, "公用基建交运"]
    )
    m_static = tei_metrics.compute_period_metrics(static_ret, bench)
    variants["美林_静态时间权重对照"] = {"overall_15y": m_static, "time_shares": {k: round(v, 4) for k, v in shares.items()}}

    # Save parquet & json
    daily_df = pd.DataFrame(daily_rets)
    daily_df.index.name = "date"
    parquet_path = os.path.join(BASE_DIR, "daily_ret_macro.parquet")
    daily_df.to_parquet(parquet_path)

    payload = {
        "meta": {
            "camp": "Camp_A_Macro_Cycle_Liquidity",
            "date_range": f"{START_DATE}..{END_DATE}",
            "n_days": int(len(df15)),
            "benchmark": "sh000300",
            "cash_return": "0%_pure_cash (with cn10y bond_cash_ref recorded)",
            "cost_model": "0.15% one-way turnover",
            "pit_rule": "merge_asof(backward) on pit_date + signal.shift(1)",
        },
        "theories": results,
        "variants": variants,
    }
    json_path = os.path.join(BASE_DIR, "res_macro_4theories.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # Print compact summary (<2KB)
    print(f"Saved: {json_path} & {parquet_path} (shape={daily_df.shape})")
    for k, prof in results.items():
        o15, o10, o3 = prof["overall_15y"], prof["last_10y"], prof["last_3y"]
        best_sec = max(prof["industry_tei"].items(), key=lambda x: x[1]["tei"])
        worst_sec = min(prof["industry_tei"].items(), key=lambda x: x[1]["tei"])
        print(
            f"{k:18s} | 15Y TEI={o15['tei']:4.1f} ex={o15['excess_ann']:+5.2f}% mdd={o15['mdd']:6.2f}% | "
            f"10Y TEI={o10['tei']:4.1f} ex={o10['excess_ann']:+5.2f}% | "
            f"3Y TEI={o3['tei']:4.1f} ex={o3['excess_ann']:+5.2f}% | "
            f"decay={prof['tei_decay_per_decade']:+5.1f} | "
            f"best={best_sec[0]}({best_sec[1]['tei']}/{best_sec[1]['excess_ann']:+.2f}%) "
            f"worst={worst_sec[0]}({worst_sec[1]['tei']}/{worst_sec[1]['excess_ann']:+.2f}%)"
        )
    print("--- Variants ---")
    for vk, vp in variants.items():
        m = vp["overall_15y"]
        print(f"  {vk:26s} | 15Y TEI={m['tei']:4.1f} ann={m['ann_ret']:5.2f}% ex={m['excess_ann']:+5.2f}% mdd={m['mdd']:6.2f}%")


if __name__ == "__main__":
    main()
