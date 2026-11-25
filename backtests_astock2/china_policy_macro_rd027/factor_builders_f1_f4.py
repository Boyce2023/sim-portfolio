#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD027 Wave 2A Factor Builders: F1 (Waterpool), F2 (Breadth & Valuation),
F3 (China Macro Pain & Credit), F4 (US-China Spread & Overseas Liquidity).
All inputs strictly PIT as of Friday_date (T close -> predicts T+1 open).
"""
import numpy as np
import pandas as pd


def causal_pct_series(s: pd.Series, window: int, min_periods: int = 26) -> pd.Series:
    """Strictly causal rolling percentile rank in [0, 1] over [t-window+1, t]."""
    arr = s.to_numpy(dtype=float)
    n = len(arr)
    out = np.full(n, np.nan, dtype=float)
    for i in range(n):
        v = arr[i]
        if np.isnan(v):
            continue
        w = arr[max(0, i - window + 1) : i + 1]
        w = w[~np.isnan(w)]
        if len(w) >= min_periods:
            out[i] = float(np.mean(w <= v))
    return pd.Series(out, index=s.index)


def causal_zscore(s: pd.Series, window: int = 156, min_periods: int = 26) -> pd.Series:
    """Strictly causal rolling z-score."""
    m = s.rolling(window, min_periods=min_periods).mean()
    sd = s.rolling(window, min_periods=min_periods).std().replace(0.0, np.nan)
    return (s - m) / sd


def _add(cols: dict, meta: list, name: str, ser: pd.Series, family: str, formula: str, source: str):
    cols[name] = ser.astype(float)
    meta.append({"factor": name, "family": family, "formula": formula, "source": source})


def build_f1_waterpool(
    wk_dates: pd.DataFrame,
    wp_raw: pd.DataFrame,
    bd_daily: pd.DataFrame,
    cal_dates: pd.Series,
) -> tuple[pd.DataFrame, list[dict]]:
    """
    F1_水池抽输血 (~160 factors).
    Monthly waterpool lagged strictly to next-month 10th calendar day (first trading day >= 10th)
    so month-end aggregates NEVER peek intra-month or on 2026-11-24.
    Plus daily trading-flow waterpool proxies as of T close.
    """
    cols, meta = {}, []
    fam = "F1_水池抽输血"

    cal = pd.DatetimeIndex(pd.to_datetime(cal_dates)).sort_values().unique()
    cal_ns = cal.asi8

    def on_or_after(ts):
        idx = int(np.searchsorted(cal_ns, pd.Timestamp(ts).normalize().value, side="left"))
        return cal[idx] if idx < len(cal) else pd.NaT

    wp = wp_raw.sort_values("month").reset_index(drop=True).copy()
    lagged_dates = []
    for _, r in wp.iterrows():
        p_next = pd.Period(r["month"], freq="M") + 1
        d10 = pd.Timestamp(year=p_next.year, month=p_next.month, day=10)
        av_orig = pd.Timestamp(r["available_date"]) if pd.notna(r["available_date"]) else d10
        d_eff = max(d10, av_orig)
        mapped = on_or_after(d_eff)
        lagged_dates.append(mapped if pd.notna(mapped) else d_eff)
    wp["wp_pit_avail"] = pd.to_datetime(lagged_dates)

    mcap = wp["eom_float_mcap_yi"].replace(0.0, np.nan)
    flow_items = [
        ("ipo_raised_yi", "IPO融资"),
        ("refinance_yi", "再融资"),
        ("insider_net_reduce_yi", "产业资本净减持"),
        ("insider_reduce_yi", "产业资本减持"),
        ("insider_add_yi", "产业资本增持"),
        ("stamp_tax_yi", "印花税"),
        ("buyback_yi", "回购"),
        ("cash_dividend_yi", "现金分红"),
        ("margin_net_chg_yi", "两融净变化"),
        ("nt_etf_weighted_flow_yi", "国家队ETF权重流"),
        ("block_trade_discount_yi", "折价大宗交易"),
        ("drain_equity_supply_yi", "股权供给抽血合计"),
        ("drain_total_yi", "总抽血"),
        ("inject_trading_yi", "交易型输血合计"),
        ("inject_total_incl_div_yi", "含分红总输血"),
        ("net_waterpool_trading_yi", "交易型净水池"),
        ("net_waterpool_incl_div_yi", "含分红净水池"),
    ]
    wp_feats = {"wp_pit_avail": wp["wp_pit_avail"]}
    wp_meta_tmp = []

    core_pct5_set = {
        "ipo_raised_yi", "refinance_yi", "insider_net_reduce_yi", "stamp_tax_yi",
        "buyback_yi", "cash_dividend_yi", "drain_equity_supply_yi", "drain_total_yi",
        "inject_trading_yi", "net_waterpool_trading_yi", "net_waterpool_incl_div_yi",
    }

    for col, desc in flow_items:
        pm = wp[col] / mcap * 100.0
        s1 = pm
        s3 = wp[col].rolling(3, min_periods=1).sum() / mcap * 100.0
        s6 = wp[col].rolling(6, min_periods=2).sum() / mcap * 100.0
        s12 = wp[col].rolling(12, min_periods=4).sum() / mcap * 100.0
        acc = s3 - s3.shift(3)
        p3y = causal_pct_series(s1, window=36, min_periods=12)
        base_nm = f"wp_{col.replace('_yi','')}_mcap"
        pairs = [
            ("1m", s1, f"{desc}/流通市值(1M,次月10日滞后)"),
            ("3m", s3, f"{desc}3M累计/流通市值"),
            ("6m", s6, f"{desc}6M累计/流通市值"),
            ("12m", s12, f"{desc}12M累计/流通市值"),
            ("3m_accel", acc, f"{desc}3M动量加速"),
            ("pct3y", p3y, f"{desc}占市值3Y因果分位"),
        ]
        if col in core_pct5_set:
            pairs.append(("pct5y", causal_pct_series(s1, window=60, min_periods=12), f"{desc}占市值5Y因果分位"))
        for suf, val, fml in pairs:
            fn = f"{base_nm}_{suf}"
            wp_feats[fn] = val.values
            wp_meta_tmp.append((fn, fml, "pillar1_waterpool_monthly"))

    wp_feats["wp_ipo_count_1m"] = wp["ipo_count"].astype(float)
    wp_feats["wp_ipo_count_3m"] = wp["ipo_count"].rolling(3, min_periods=1).sum()
    wp_feats["wp_ipo_count_12m"] = wp["ipo_count"].rolling(12, min_periods=4).sum()
    wp_feats["wp_refinance_count_3m"] = wp["refinance_count"].rolling(3, min_periods=1).sum()
    wp_feats["wp_mkt_turn_monthly_pct"] = wp["mkt_turn_monthly_pct"].astype(float)
    wp_feats["wp_mkt_turn_3m_avg"] = wp["mkt_turn_monthly_pct"].rolling(3, min_periods=1).mean()
    wp_feats["wp_margin_mcap_pct"] = wp["margin_balance_eom_yi"] / mcap * 100.0
    prev_wp_m = wp["margin_balance_eom_yi"].shift(1)
    wp_feats["wp_margin_mom_pct"] = np.where(
        prev_wp_m >= 50.0, wp["margin_net_chg_yi"] / prev_wp_m * 100.0, np.nan
    )
    wp_feats["wp_buyback_to_drain"] = wp["buyback_yi"] / wp["drain_total_yi"].replace(0, np.nan)
    wp_feats["wp_div_to_drain"] = wp["cash_dividend_yi"] / wp["drain_total_yi"].replace(0, np.nan)
    wp_feats["wp_inject_to_drain"] = wp["inject_trading_yi"] / wp["drain_total_yi"].replace(0, np.nan)
    wp_feats["wp_eq_supply_share_drain"] = wp["drain_equity_supply_yi"] / wp["drain_total_yi"].replace(0, np.nan)
    wp_feats["wp_insider_add_reduce_ratio"] = (wp["insider_add_yi"] + 1.0) / (wp["insider_reduce_yi"] + 1.0)
    wp_feats["wp_nt_etf22_mcap_1m"] = wp["nt_etf22_wflow_yi"] / mcap * 100.0
    wp_feats["wp_nt_etf22_mcap_3m"] = wp["nt_etf22_wflow_yi"].rolling(3, min_periods=1).sum() / mcap * 100.0
    wp_feats["wp_northbound_mcap_3m"] = wp["northbound_net_buy_yi"].rolling(3, min_periods=1).sum() / mcap * 100.0

    nw1 = wp["net_waterpool_trading_yi"]
    nw3 = nw1.rolling(3, min_periods=1).sum()
    nwd1 = wp["net_waterpool_incl_div_yi"]
    dr3y = wp["drain_total_pct_mcap_pct_3y"]
    wp_feats["wp_net_flip_pos_1m"] = ((nw1 > 0) & (nw1.shift(1) <= 0)).astype(float)
    wp_feats["wp_net_flip_pos_3m"] = ((nw3 > 0) & (nw3.shift(1) <= 0)).astype(float)
    wp_feats["wp_net_incl_div_flip_pos_1m"] = ((nwd1 > 0) & (nwd1.shift(1) <= 0)).astype(float)
    wp_feats["wp_net_pos_flag_1m"] = (nw1 > 0).astype(float)
    wp_feats["wp_net_pos_flag_3m"] = (nw3 > 0).astype(float)
    wp_feats["wp_drain_freeze_20pct"] = (dr3y <= 0.20).astype(float)
    wp_feats["wp_drain_freeze_10pct"] = (dr3y <= 0.10).astype(float)
    wp_feats["wp_ipo_freeze_15pct"] = (causal_pct_series(wp["ipo_raised_yi"].rolling(3, min_periods=1).sum() / mcap, 36, 12) <= 0.15).astype(float)
    wp_feats["wp_inject_surge_80pct"] = (causal_pct_series(wp["inject_trading_yi"].rolling(3, min_periods=1).sum() / mcap, 36, 12) >= 0.80).astype(float)
    wp_feats["wp_nt_buy_margin_delev"] = np.where(
        wp["margin_net_chg_yi"].notna() & wp["nt_etf_weighted_flow_yi"].notna(),
        ((wp["margin_net_chg_yi"] < 0) & (wp["nt_etf_weighted_flow_yi"] > 0)).astype(float),
        np.nan,
    )

    extra_descs = {
        "wp_ipo_count_1m": "月度IPO家数", "wp_ipo_count_3m": "3M IPO家数", "wp_ipo_count_12m": "12M IPO家数",
        "wp_refinance_count_3m": "3M再融资家数",
        "wp_mkt_turn_monthly_pct": "全A月换手率%", "wp_mkt_turn_3m_avg": "全A 3M均换手率%",
        "wp_margin_mcap_pct": "期末两融/流通市值%", "wp_margin_mom_pct": "两融月度环比增速%",
        "wp_buyback_to_drain": "回购/总抽血比", "wp_div_to_drain": "分红/总抽血比",
        "wp_inject_to_drain": "输血/总抽血比", "wp_eq_supply_share_drain": "股权供给占总抽血比",
        "wp_insider_add_reduce_ratio": "增持/减持金额比", "wp_nt_etf22_mcap_1m": "22只国家队ETF流/市值(1M)",
        "wp_nt_etf22_mcap_3m": "22只国家队ETF流/市值(3M)", "wp_northbound_mcap_3m": "北向净买/市值(3M)",
        "wp_net_flip_pos_1m": "净水池1M由负转正拐点", "wp_net_flip_pos_3m": "净水池3M由负转正拐点",
        "wp_net_incl_div_flip_pos_1m": "含分红净水池由负转正拐点",
        "wp_net_pos_flag_1m": "1M净水池为正标志", "wp_net_pos_flag_3m": "3M净水池为正标志",
        "wp_drain_freeze_20pct": "抽血阀<=20%分位冻结", "wp_drain_freeze_10pct": "抽血阀<=10%分位死封",
        "wp_ipo_freeze_15pct": "IPO抽血<=15%分位", "wp_inject_surge_80pct": "输血>=80%分位放水",
        "wp_nt_buy_margin_delev": "国家队净买+两融去杠杆月度标志",
    }
    for fn, desc in extra_descs.items():
        wp_meta_tmp.append((fn, desc, "pillar1_waterpool_monthly"))

    wp_feats_df = pd.DataFrame(wp_feats)
    m_wp = pd.merge_asof(
        wk_dates[["date"]].sort_values("date"),
        wp_feats_df.sort_values("wp_pit_avail").drop_duplicates("wp_pit_avail", keep="last"),
        left_on="date",
        right_on="wp_pit_avail",
        direction="backward",
    )
    for fn, fml, src in wp_meta_tmp:
        _add(cols, meta, fn, m_wp[fn], fam, fml, src)

    bd = bd_daily.sort_values("date").reset_index(drop=True).copy()
    dmcap = bd["total_float_mcap_yi"].replace(0.0, np.nan)
    d_derived = pd.DataFrame({"date": bd["date"]})
    for win in [5, 20, 60, 120]:
        nt_s = bd["etf_nt_weighted_flow_yi"].rolling(win, min_periods=max(1, win // 3)).sum()
        etf_s = bd["etf_net_flow_yi"].rolling(win, min_periods=max(1, win // 3)).sum()
        etf22_s = bd["etf22_wflow_yi"].rolling(win, min_periods=max(1, win // 3)).sum()
        stax_s = bd["stamp_tax_daily_yi"].rolling(win, min_periods=max(1, win // 3)).sum()
        prev_m = bd["margin_balance_yi"].shift(win)
        m_chg = bd["margin_balance_yi"] - prev_m
        m_pct = np.where(prev_m >= 50.0, (bd["margin_balance_yi"] / prev_m - 1.0) * 100.0, np.nan)
        proxy_net = ((m_chg.fillna(0.0) + nt_s.fillna(0.0) - stax_s) / dmcap * 100.0).where(m_chg.notna(), np.nan)

        d_derived[f"d_nt_wflow_{win}d_mcap"] = nt_s / dmcap * 100.0
        d_derived[f"d_etf_flow_{win}d_mcap"] = etf_s / dmcap * 100.0
        d_derived[f"d_etf22_wflow_{win}d_mcap"] = etf22_s / dmcap * 100.0
        d_derived[f"d_stamp_tax_{win}d_mcap"] = stax_s / dmcap * 100.0
        d_derived[f"d_margin_chg_{win}d_mcap"] = m_chg / dmcap * 100.0
        d_derived[f"d_margin_chg_{win}d_pct"] = m_pct
        d_derived[f"d_net_flow_proxy_{win}d_mcap"] = proxy_net

    d_derived["d_margin_to_mcap_pct"] = bd["margin_to_float_mcap_pct"]
    d_derived["d_margin_to_mcap_pct3y"] = causal_pct_series(bd["margin_to_float_mcap_pct"], window=726, min_periods=120)
    d_derived["d_nt_buy_days_20d"] = (bd["etf_nt_weighted_flow_yi"] > 0).rolling(20, min_periods=10).sum().where(bd["etf_nt_weighted_flow_yi"].notna(), np.nan)
    d_derived["d_etf510300_20d_mcap"] = bd["etf510300_net_flow_yi"].rolling(20, min_periods=5).sum() / dmcap * 100.0

    w_d = wk_dates[["date"]].merge(d_derived, on="date", how="left")
    for c in d_derived.columns:
        if c != "date":
            _add(cols, meta, c, w_d[c], fam, f"日度交易型水池代理:{c}(截至T日收盘)", "pillar1_market_breadth_daily")

    return pd.DataFrame(cols, index=wk_dates.index), meta


def build_f2_breadth_valuation(
    wk_dates: pd.DataFrame,
    bd_daily: pd.DataFrame,
    dmp_daily: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict]]:
    """F2_市场宽度与估值出清 (~150 factors)."""
    cols, meta = {}, []
    fam = "F2_市场宽度与估值出清"

    bd = bd_daily.sort_values("date").reset_index(drop=True).copy()
    dmp = dmp_daily.sort_values("date").reset_index(drop=True).copy()
    dmp["date"] = pd.to_datetime(dmp["date"])
    df = bd.merge(
        dmp[["date", "csi_div_close", "tech_board_close", "csi500_close", "csi1000_close", "bench_close", "bench_dd_60d", "bench_dd_250d", "micro30_close", "large10_close"]],
        on="date",
        how="left",
        suffixes=("", "_dmp"),
    )
    df["new_high_minus_low"] = df["pct_new_high_250d"] - df["pct_new_low_250d"]
    df["zt_minus_dt_ratio"] = df["zt_ratio"] - df["dt_ratio"]
    df["turn_ew_minus_mkt"] = df["turn_ew_mean"] - df["turn_mkt_weighted"]
    df["ep_csi300"] = 100.0 / df["csi300_pe_ttm_daily"].replace(0, np.nan)
    df["bp_all_a_med"] = 1.0 / df["all_a_median_pb"].replace(0, np.nan)
    df["pe_med_to_300_ratio"] = df["all_a_median_pe_ttm"] / df["csi300_pe_ttm_daily"].replace(0, np.nan)
    df["erp_300_minus_all_a"] = df["erp_csi300_pct"] - df["erp_all_a_median_pct"]
    df["vol_spread_ew_minus_bench"] = df["ew_vol_20d"] - df["bench_vol_20d"]

    asset_map = {
        "csi300": df["csi300_close"],
        "bench": df["bench_close"],
        "ew": df["ew_idx_level"],
        "cw": df["cw_idx_level"],
        "micro30": df["micro30_close"],
        "large10": df["large10_close"],
        "csi_div": df["csi_div_close"],
        "chinext": df["chinext_close"],
        "tech": df["tech_board_close"],
        "csi500": df["csi500_close"],
    }
    for nm, ser in asset_map.items():
        for h in [20, 60, 120, 250]:
            df[f"{nm}_trail_ret_{h}d"] = ser / ser.shift(h) - 1.0

    for h in [20, 60, 120]:
        df[f"trail_micro30_minus_300_{h}d"] = df[f"micro30_trail_ret_{h}d"] - df[f"csi300_trail_ret_{h}d"]
        df[f"trail_div_minus_chinext_{h}d"] = df[f"csi_div_trail_ret_{h}d"] - df[f"chinext_trail_ret_{h}d"]
        df[f"trail_tech_minus_300_{h}d"] = df[f"tech_trail_ret_{h}d"] - df[f"csi300_trail_ret_{h}d"]
        df[f"trail_ew_minus_cw_{h}d"] = df[f"ew_trail_ret_{h}d"] - df[f"cw_trail_ret_{h}d"]

    df["big4_vs_ew_5d"] = (df["big4_bank_cc_ret"] - df["ew_cc_ret"]).rolling(5, min_periods=3).sum()
    df["big4_vs_ew_20d"] = (df["big4_bank_cc_ret"] - df["ew_cc_ret"]).rolling(20, min_periods=10).sum()

    w = wk_dates[["date"]].merge(df, on="date", how="left")

    base_breadth = [
        "pct_above_ma20", "pct_above_ma60", "pct_above_ma200",
        "pct_new_low_250d", "pct_new_high_250d", "new_high_minus_low",
        "pct_low_price_lt3", "pct_low_price_lt5", "up_ratio", "zt_ratio", "dt_ratio",
        "zt_minus_dt_ratio", "broken_rate", "turn_mkt_weighted", "turn_ew_mean",
        "turn_median", "turn_ew_minus_mkt", "amount_ratio_20d", "ew_vol_20d",
        "bench_vol_20d", "vol_spread_ew_minus_bench",
        "csi300_pe_ttm_daily", "all_a_median_pe_ttm", "all_a_median_pb",
        "ep_csi300", "bp_all_a_med", "pe_med_to_300_ratio", "erp_csi300_pct",
        "erp_all_a_median_pct", "erp_300_minus_all_a", "size_ratio_large_vs_micro",
    ]
    for c in base_breadth:
        _add(cols, meta, f"f2_{c}", w[c], fam, f"市场宽度/估值水平:{c}", "pillar1_market_breadth_daily")
        _add(cols, meta, f"f2_{c}_chg4w", w[c] - w[c].shift(4), fam, f"{c}近4周变化", "pillar1_market_breadth_daily")
        _add(cols, meta, f"f2_{c}_chg13w", w[c] - w[c].shift(13), fam, f"{c}近13周变化", "pillar1_market_breadth_daily")
        _add(cols, meta, f"f2_{c}_pct3y", causal_pct_series(w[c], 156, 26), fam, f"{c} 3Y因果分位", "pillar1_market_breadth_daily")

    direct_cols = [
        "amount_pct_250d", "amount_pct_3y", "turn_pct_250d", "turn_pct_3y",
        "erp_csi300_pct_3y", "erp_csi300_pct_5y", "erp_all_a_pct_3y", "erp_all_a_pct_5y",
        "bench_dd_60d", "bench_dd_250d", "big4_vs_ew_5d", "big4_vs_ew_20d",
        "csi300_trail_ret_20d", "csi300_trail_ret_60d", "csi300_trail_ret_120d", "csi300_trail_ret_250d",
        "ew_trail_ret_20d", "ew_trail_ret_60d", "ew_trail_ret_120d", "ew_trail_ret_250d",
        "micro30_trail_ret_60d", "csi_div_trail_ret_60d", "chinext_trail_ret_60d", "tech_trail_ret_60d",
        "trail_micro30_minus_300_20d", "trail_micro30_minus_300_60d", "trail_micro30_minus_300_120d",
        "trail_div_minus_chinext_20d", "trail_div_minus_chinext_60d", "trail_div_minus_chinext_120d",
        "trail_tech_minus_300_20d", "trail_tech_minus_300_60d", "trail_tech_minus_300_120d",
        "trail_ew_minus_cw_60d",
    ]
    for c in direct_cols:
        _add(cols, meta, f"f2_{c}", w[c], fam, f"市场价格/估值分位:{c}", "pillar1_market_breadth_daily")

    return pd.DataFrame(cols, index=wk_dates.index), meta


def build_f3_cn_macro(
    wk_dates: pd.DataFrame,
    mp_daily: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict]]:
    """F3_中国宏观痛阈与信贷 (~180 factors)."""
    cols, meta = {}, []
    fam = "F3_中国宏观痛阈与信贷"

    mp = mp_daily.sort_values("date").reset_index(drop=True).copy()
    for bc in ["cn_bond_2y", "cn_bond_10y", "cn_bond_30y", "cn_10y_2y_spread"]:
        mp[bc] = mp[bc].ffill(limit=5)
    mp["cn_real_rate_cpi"] = mp["cn_bond_10y"] - mp["cn_cpi_yoy"]
    mp["cn_corp_real_rate_ppi"] = mp["cn_policy_rate_1y"] - mp["cn_ppi_yoy"]

    w = wk_dates[["date"]].merge(mp, on="date", how="left")
    w["cn_pmi_spread"] = w["cn_pmi_mfg"] - w["cn_pmi_non_mfg"]
    w["cn_trade_spread"] = w["cn_exports_yoy"] - w["cn_imports_yoy"]
    w["cn_30y_10y_spread"] = w["cn_bond_30y"] - w["cn_bond_10y"]
    w["cn_m1_minus_cpi"] = w["cn_m1_yoy"] - w["cn_cpi_yoy"]
    w["cn_credit_impulse_13w"] = w["cn_new_loan_12m_yi"] - w["cn_new_loan_12m_yi"].shift(13)
    w["cn_credit_impulse_26w"] = w["cn_new_loan_12m_yi"] - w["cn_new_loan_12m_yi"].shift(26)
    w["cn_new_loan_12m_yoy"] = (w["cn_new_loan_12m_yi"] / w["cn_new_loan_12m_yi"].shift(52).replace(0, np.nan) - 1.0) * 100.0
    w["cn_new_loan_yoy_diff"] = w["cn_new_loan_yi"] - w["cn_new_loan_yi"].shift(52)
    w["cn_new_loan_yoy_clip"] = w["cn_new_loan_yoy"].clip(-150.0, 200.0)
    w["cn_tsf_impulse_13w"] = w["cn_tsf_12m_yi"] - w["cn_tsf_12m_yi"].shift(13)
    w["cn_tsf_impulse_26w"] = w["cn_tsf_12m_yi"] - w["cn_tsf_12m_yi"].shift(26)

    core_macro = [
        "cn_m1_yoy", "cn_m2_yoy", "cn_m0_yoy", "cn_m1_m2_diff",
        "cn_new_loan_yi", "cn_new_loan_12m_yoy", "cn_new_loan_12m_yi",
        "cn_tsf_yi", "cn_tsf_yoy_diff", "cn_tsf_12m_yi",
        "cn_pboc_assets_yoy", "cn_pmi_mfg", "cn_pmi_non_mfg", "cn_pmi_spread",
        "cn_cpi_yoy", "cn_ppi_yoy", "cn_ppi_minus_cpi",
        "cn_ind_prod_yoy", "cn_retail_sales_yoy", "cn_fai_yoy",
        "cn_real_estate_climate", "cn_real_estate_yoy", "cn_consumer_conf",
        "cn_exports_yoy", "cn_imports_yoy", "cn_trade_spread",
        "cn_fiscal_rev_yoy", "cn_fx_reserves_yoy", "cn_gdp_yoy",
        "cn_policy_rate_1y", "cn_lpr_1y", "cn_lpr_5y",
        "cn_bond_2y", "cn_bond_10y", "cn_bond_30y",
        "cn_10y_2y_spread", "cn_30y_10y_spread",
        "cn_real_rate_cpi", "cn_corp_real_rate_ppi", "cn_m1_minus_cpi",
    ]
    for c in core_macro:
        _add(cols, meta, f"f3_{c}", w[c], fam, f"中国宏观水平:{c}", "pillar4_macro_pain_daily_pit")
        _add(cols, meta, f"f3_{c}_chg4w", w[c] - w[c].shift(4), fam, f"{c}近4周变化", "pillar4_macro_pain_daily_pit")
        _add(cols, meta, f"f3_{c}_chg13w", w[c] - w[c].shift(13), fam, f"{c}近13周变化", "pillar4_macro_pain_daily_pit")
        _add(cols, meta, f"f3_{c}_pct3y", causal_pct_series(w[c], 156, 26), fam, f"{c} 3Y因果分位", "pillar4_macro_pain_daily_pit")

    mom_cols = [
        "cn_m1_m2_diff_mom", "cn_m1_yoy_mom", "cn_pmi_mfg_mom", "cn_pmi_mfg_yoy",
        "cn_cpi_yoy_mom", "cn_ppi_yoy_mom", "cn_gdp_yoy_qoq",
        "cn_new_loan_yoy_diff", "cn_new_loan_yoy_clip",
        "cn_credit_impulse_13w", "cn_credit_impulse_26w",
        "cn_tsf_impulse_13w", "cn_tsf_impulse_26w",
    ]
    for c in mom_cols:
        _add(cols, meta, f"f3_{c}", w[c], fam, f"中国宏观脉冲:{c}", "pillar4_macro_pain_daily_pit")

    for c in ["cn_m1_m2_diff", "cn_pmi_mfg", "cn_ppi_yoy", "cn_corp_real_rate_ppi", "cn_bond_10y", "cn_10y_2y_spread", "cn_real_estate_climate"]:
        _add(cols, meta, f"f3_{c}_chg26w", w[c] - w[c].shift(26), fam, f"{c}近26周变化", "pillar4_macro_pain_daily_pit")
        _add(cols, meta, f"f3_{c}_pct5y", causal_pct_series(w[c], 260, 26), fam, f"{c} 5Y因果分位", "pillar4_macro_pain_daily_pit")

    _add(cols, meta, "f3_pain_pmi_lt50", (w["cn_pmi_mfg"] < 50.0).astype(float), fam, "PMI制造业<50收缩痛阈", "pillar4_macro_pain_daily_pit")
    _add(cols, meta, "f3_pain_ppi_deflation", (w["cn_ppi_yoy"] < 0.0).astype(float), fam, "PPI通缩痛阈(<0)", "pillar4_macro_pain_daily_pit")
    _add(cols, meta, "f3_pain_m1m2_lt_neg5", (w["cn_m1_m2_diff"] <= -5.0).astype(float), fam, "M1-M2剪刀差<=-5%痛阈", "pillar4_macro_pain_daily_pit")
    _add(cols, meta, "f3_pain_corp_real_rate_gt5", (w["cn_corp_real_rate_ppi"] >= 5.0).astype(float), fam, "企业实际融资利率(利率-PPI)>=5%", "pillar4_macro_pain_daily_pit")
    _add(cols, meta, "f3_pain_re_climate_lt95", (w["cn_real_estate_climate"] < 95.0).astype(float), fam, "国房景气指数<95", "pillar4_macro_pain_daily_pit")
    pain_idx = (
        causal_zscore(w["cn_corp_real_rate_ppi"])
        - causal_zscore(w["cn_pmi_mfg"])
        - causal_zscore(w["cn_m1_m2_diff"])
        - causal_zscore(w["cn_ppi_yoy"])
    ) / 4.0
    _add(cols, meta, "f3_cn_macro_pain_composite", pain_idx, fam, "中国宏观痛苦指数(因果Z组合)", "pillar4_macro_pain_daily_pit")

    return pd.DataFrame(cols, index=wk_dates.index), meta


def build_f4_us_china_constraints(
    wk_dates: pd.DataFrame,
    mp_daily: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict]]:
    """F4_中美利差与海外流动约束 (~120 factors)."""
    cols, meta = {}, []
    fam = "F4_中美利差与海外流动约束"

    mp = mp_daily.sort_values("date").reset_index(drop=True).copy()
    for c in ["cn_bond_10y", "cn_bond_2y", "us_dgs10", "us_dgs2", "us_dff", "us_dfii10", "us_baa10y", "us_vix", "us_dxy_broad", "us_dxy_ice", "usdcny"]:
        mp[c] = mp[c].ffill(limit=5)
    mp["cn_us_10y_spread_bp"] = (mp["cn_bond_10y"] - mp["us_dgs10"]) * 100.0
    mp["cn_us_2y_spread_bp"] = (mp["cn_bond_2y"] - mp["us_dgs2"]) * 100.0
    mp["cn_real_rate_cpi"] = mp["cn_bond_10y"] - mp["cn_cpi_yoy"]

    w = wk_dates[["date"]].merge(mp, on="date", how="left")
    w["us_breakeven_10y"] = w["us_dgs10"] - w["us_dfii10"]
    w["cn_us_real_10y_spread"] = w["cn_real_rate_cpi"] - w["us_dfii10"]
    w["usdcny_ret_13w"] = (w["usdcny"] / w["usdcny"].shift(13) - 1.0) * 100.0
    w["usdcny_ret_26w"] = (w["usdcny"] / w["usdcny"].shift(26) - 1.0) * 100.0
    w["us_net_liq_chg_13w_pct"] = (w["us_net_liquidity_bn"] / w["us_net_liquidity_bn"].shift(13) - 1.0) * 100.0
    w["us_net_liq_chg_52w_pct"] = (w["us_net_liquidity_bn"] / w["us_net_liquidity_bn"].shift(52) - 1.0) * 100.0

    us_series = [
        "cn_us_10y_spread_bp", "cn_us_2y_spread_bp", "cn_us_real_10y_spread",
        "usdcny", "us_dgs10", "us_dgs2", "us_dff", "us_dfii10",
        "us_breakeven_10y", "us_t10y2y", "us_baa10y", "us_vix",
        "us_dxy_broad", "us_dxy_ice", "us_nfci",
        "us_fed_assets_bn", "us_fed_assets_yoy", "us_net_liquidity_bn",
        "us_tga_bn", "us_m2_yoy",
    ]
    for c in us_series:
        _add(cols, meta, f"f4_{c}", w[c], fam, f"海外流动性/中美约束:{c}", "pillar4_macro_pain_daily_pit")
        _add(cols, meta, f"f4_{c}_chg4w", w[c] - w[c].shift(4), fam, f"{c}近4周变化", "pillar4_macro_pain_daily_pit")
        _add(cols, meta, f"f4_{c}_chg13w", w[c] - w[c].shift(13), fam, f"{c}近13周变化", "pillar4_macro_pain_daily_pit")
        _add(cols, meta, f"f4_{c}_chg26w", w[c] - w[c].shift(26), fam, f"{c}近26周变化", "pillar4_macro_pain_daily_pit")
        _add(cols, meta, f"f4_{c}_pct3y", causal_pct_series(w[c], 156, 26), fam, f"{c} 3Y因果分位", "pillar4_macro_pain_daily_pit")

    for c in ["cn_us_10y_spread_bp", "cn_us_2y_spread_bp", "usdcny", "us_dgs10", "us_dfii10", "us_dxy_broad", "us_vix", "us_baa10y", "us_nfci", "us_net_liquidity_bn"]:
        _add(cols, meta, f"f4_{c}_pct5y", causal_pct_series(w[c], 260, 26), fam, f"{c} 5Y因果分位", "pillar4_macro_pain_daily_pit")

    _add(cols, meta, "f4_usdcny_ret_13w", w["usdcny_ret_13w"], fam, "USDCNY近13周贬值%", "pillar4_macro_pain_daily_pit")
    _add(cols, meta, "f4_usdcny_ret_26w", w["usdcny_ret_26w"], fam, "USDCNY近26周贬值%", "pillar4_macro_pain_daily_pit")
    _add(cols, meta, "f4_us_net_liq_chg_13w_pct", w["us_net_liq_chg_13w_pct"], fam, "Fed净流动性13周增速%", "pillar4_macro_pain_daily_pit")
    _add(cols, meta, "f4_us_net_liq_chg_52w_pct", w["us_net_liq_chg_52w_pct"], fam, "Fed净流动性52周增速%", "pillar4_macro_pain_daily_pit")
    _add(cols, meta, "f4_flag_cn_us_10y_inv", (w["cn_us_10y_spread_bp"] < 0.0).astype(float), fam, "中美10Y利差倒挂标志", "pillar4_macro_pain_daily_pit")
    _add(cols, meta, "f4_flag_usdcny_ge7", (w["usdcny"] >= 7.0).astype(float), fam, "汇率破7压力标志", "pillar4_macro_pain_daily_pit")

    return pd.DataFrame(cols, index=wk_dates.index), meta
