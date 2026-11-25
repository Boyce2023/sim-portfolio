#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Build Pillar 1 datasets:
1. pillar1_market_breadth_daily.parquet (2005-01-04 ~ 2026-11-24)
2. pillar1_waterpool_monthly.parquet (2005-01 ~ 2026-11)
Strictly D12-compliant, survivorship-free (a_daily + a_delisted + bj_daily), zero lookahead.
"""
import os
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from pit_utils import (
    build_pit_mapper,
    causal_rolling_pct,
    pit_asof_join,
    stamp_tax_rate_series,
)

ROOT = "/Users/huaichuaibeimeng/claude-projects"
DMP_PATH = os.path.join(ROOT, "output/csrc_policy_100factors_20261114/policy_polymarket_v1/daily_market_panel_v2_20261124.parquet")
CN_DB_DIR = os.path.join(ROOT, "sim-portfolio/data/cn_hk_price_db")


def _load_all_stocks_daily(min_date: str = "2002-01-01") -> pd.DataFrame:
    """Load survivorship-free A-share + delisted + BSE daily bars from local parquet."""
    cols = ["date", "ticker", "close", "adj_close", "amount", "oshare", "turn"]
    parts = []
    for fn in ["a_daily.parquet", "a_delisted_daily.parquet", "bj_daily.parquet"]:
        p = os.path.join(CN_DB_DIR, fn)
        if os.path.exists(p):
            tbl = pq.read_table(
                p,
                columns=cols,
                filters=[("date", ">=", pd.Timestamp(min_date)), ("date", "<=", pd.Timestamp("2026-11-24"))],
            ).to_pandas()
            parts.append(tbl)
    stk = pd.concat(parts, ignore_index=True)
    stk["date"] = pd.to_datetime(stk["date"])
    stk = stk.drop_duplicates(["date", "ticker"]).sort_values(["ticker", "date"]).reset_index(drop=True)
    stk = stk[(stk["close"] > 0) & (stk["adj_close"] > 0) & (stk["amount"] > 0)].copy()
    stk["code6"] = stk["ticker"].astype(str).str.split(".").str[0].str.zfill(6)
    return stk


def _build_daily_margin(raw: dict) -> pd.DataFrame:
    """Stitch SH+SZ margin (2010-03-31+) with CSIDC stock_margin_account_info (2012-09-27 ~ 2026-11-24)."""
    cs = raw.get("stock_margin_account_info", pd.DataFrame()).copy()
    sh = raw.get("macro_china_market_margin_sh", pd.DataFrame()).copy()
    sz = raw.get("macro_china_market_margin_sz", pd.DataFrame()).copy()

    ex_df = pd.DataFrame(columns=["obs_date", "margin_balance_yi"])
    if not sh.empty and not sz.empty:
        sh["obs_date"] = pd.to_datetime(sh["日期"])
        sz["obs_date"] = pd.to_datetime(sz["日期"])
        sh["rz_sh"] = pd.to_numeric(sh["融资余额"], errors="coerce")
        sz["rz_sz"] = pd.to_numeric(sz["融资余额"], errors="coerce")
        m_ex = sh[["obs_date", "rz_sh"]].merge(sz[["obs_date", "rz_sz"]], on="obs_date", how="inner")
        m_ex["margin_balance_yi"] = (m_ex["rz_sh"] + m_ex["rz_sz"]) / 1e8
        ex_df = m_ex[["obs_date", "margin_balance_yi"]].dropna()

    cs_df = pd.DataFrame(columns=["obs_date", "margin_balance_yi"])
    if not cs.empty:
        cs["obs_date"] = pd.to_datetime(cs["日期"])
        cs["margin_balance_yi"] = pd.to_numeric(cs["融资余额"], errors="coerce")
        cs_df = cs[["obs_date", "margin_balance_yi"]].dropna()

    if cs_df.empty:
        return ex_df.sort_values("obs_date")
    first_cs = cs_df["obs_date"].min()
    pre = ex_df[ex_df["obs_date"] < first_cs]
    out = pd.concat([pre, cs_df], ignore_index=True).drop_duplicates("obs_date").sort_values("obs_date")
    return out.reset_index(drop=True)


def build_breadth_and_waterpool(raw: dict):
    """Build Pillar 1 daily breadth and monthly waterpool tables, plus anomaly log."""
    dmp = pd.read_parquet(DMP_PATH)
    dmp["date"] = pd.to_datetime(dmp["date"])
    dmp = dmp[dmp["date"] <= pd.Timestamp("2026-11-24")].sort_values("date").reset_index(drop=True)
    on_or_after, strictly_after, _, _ = build_pit_mapper(dmp["date"])

    print("  Loading survivorship-free stock daily DB (2002-2026)...")
    stk = _load_all_stocks_daily(min_date="2002-01-01")

    # Per-stock causal technical & breadth indicators
    g_tk = stk.groupby("ticker", sort=False)
    stk["ma20"] = g_tk["adj_close"].transform(lambda s: s.rolling(20, min_periods=15).mean())
    stk["ma60"] = g_tk["adj_close"].transform(lambda s: s.rolling(60, min_periods=45).mean())
    stk["ma200"] = g_tk["adj_close"].transform(lambda s: s.rolling(200, min_periods=150).mean())
    stk["prev_low250"] = g_tk["adj_close"].transform(lambda s: s.shift(1).rolling(250, min_periods=120).min())
    stk["prev_high250"] = g_tk["adj_close"].transform(lambda s: s.shift(1).rolling(250, min_periods=120).max())
    stk["prev_adj"] = g_tk["adj_close"].shift(1)
    stk["cc_ret"] = (stk["adj_close"] / stk["prev_adj"] - 1.0).clip(-0.35, 0.35)
    stk["float_mcap_yi"] = np.where(stk["oshare"] > 0, stk["close"] * stk["oshare"] / 1e8, np.nan)
    stk["prev_mcap_yi"] = g_tk["float_mcap_yi"].shift(1)
    stk["w_ret"] = stk["prev_mcap_yi"] * stk["cc_ret"]

    stk["above_ma20"] = np.where(stk["ma20"].notna(), (stk["adj_close"] > stk["ma20"]).astype(float), np.nan)
    stk["above_ma60"] = np.where(stk["ma60"].notna(), (stk["adj_close"] > stk["ma60"]).astype(float), np.nan)
    stk["above_ma200"] = np.where(stk["ma200"].notna(), (stk["adj_close"] > stk["ma200"]).astype(float), np.nan)
    stk["new_low_250"] = np.where(stk["prev_low250"].notna(), (stk["adj_close"] < stk["prev_low250"]).astype(float), np.nan)
    stk["new_high_250"] = np.where(stk["prev_high250"].notna(), (stk["adj_close"] > stk["prev_high250"]).astype(float), np.nan)
    stk["is_lt3"] = (stk["close"] < 3.0).astype(float)
    stk["is_lt5"] = (stk["close"] < 5.0).astype(float)
    stk["turn_clean"] = pd.to_numeric(stk["turn"], errors="coerce")
    stk["turn_clean"] = stk["turn_clean"].where((stk["turn_clean"] >= 0.0) & (stk["turn_clean"] <= 1.0))

    print("  Aggregating daily market breadth...")
    gd = stk.groupby("date", sort=True)
    agg_d = pd.DataFrame({
        "stk_n_active": gd["ticker"].count(),
        "total_amount_stk_yi": gd["amount"].sum() / 1e8,
        "total_float_mcap_yi": gd["float_mcap_yi"].sum(),
        "median_float_mcap_yi": gd["float_mcap_yi"].median(),
        "pct_above_ma20": gd["above_ma20"].mean(),
        "pct_above_ma60": gd["above_ma60"].mean(),
        "pct_above_ma200": gd["above_ma200"].mean(),
        "pct_new_low_250d": gd["new_low_250"].mean(),
        "pct_new_high_250d": gd["new_high_250"].mean(),
        "pct_low_price_lt3": gd["is_lt3"].mean(),
        "pct_low_price_lt5": gd["is_lt5"].mean(),
        "turn_ew_mean": gd["turn_clean"].mean(),
        "turn_median": gd["turn_clean"].median(),
        "sum_w_ret": gd["w_ret"].sum(),
        "sum_prev_mcap": gd["prev_mcap_yi"].sum(),
    }).reset_index()
    agg_d["cw_cc_ret"] = np.where(agg_d["sum_prev_mcap"] > 0, agg_d["sum_w_ret"] / agg_d["sum_prev_mcap"], np.nan)
    agg_d["turn_mkt_weighted"] = np.where(agg_d["total_float_mcap_yi"] > 0, agg_d["total_amount_stk_yi"] / agg_d["total_float_mcap_yi"], np.nan)
    agg_d = agg_d.drop(columns=["sum_w_ret", "sum_prev_mcap"])

    # Merge DMP columns (compute clean big4_bank_cc_ret directly from stk)
    dmp_keep = [
        "date", "sh_comp_close", "csi300_close", "csi500_close", "csi1000_close", "chinext_close",
        "sse50_close", "n_stocks", "total_amount_yi", "ew_cc_ret", "up_ratio", "zt_cnt", "dt_cnt",
        "broken_rate", "micro30_cc_ret", "large10_cc_ret", "bench_cc_ret",
        "etf_net_flow_yi", "etf_nt_weighted_flow_yi", "etf22_flow_yi", "etf22_wflow_yi", "etf510300_net_flow_yi",
    ]
    big4 = stk[stk["code6"].isin(["601398", "601939", "601288", "601988"])].groupby("date", as_index=False)["cc_ret"].mean().rename(columns={"cc_ret": "big4_bank_cc_ret"})
    bd = dmp[dmp_keep].merge(agg_d, on="date", how="left").merge(big4, on="date", how="left").sort_values("date").reset_index(drop=True)
    bd["available_date"] = bd["date"].map(strictly_after)
    bd["dt_ratio"] = np.where(bd["n_stocks"] > 0, bd["dt_cnt"] / bd["n_stocks"], np.nan)
    bd["zt_ratio"] = np.where(bd["n_stocks"] > 0, bd["zt_cnt"] / bd["n_stocks"], np.nan)

    # Cumulative EW, CW, and Large-vs-Micro style index (normalized at 2005-01-04 later or full)
    bd["ew_idx_level"] = (1.0 + bd["ew_cc_ret"].fillna(0.0)).cumprod()
    bd["cw_idx_level"] = (1.0 + bd["cw_cc_ret"].fillna(0.0)).cumprod()
    large_lvl = (1.0 + bd["large10_cc_ret"].fillna(0.0)).cumprod()
    micro_lvl = (1.0 + bd["micro30_cc_ret"].fillna(0.0)).cumprod()
    bd["size_ratio_large_vs_micro"] = large_lvl / micro_lvl.replace(0, np.nan)
    bd["large10_minus_micro30_ret_20d"] = (
        large_lvl / large_lvl.shift(20) - 1.0
    ) - (micro_lvl / micro_lvl.shift(20) - 1.0)

    # Volatility & causal percentiles (computed on 2000-2026 history before slicing >= 2005!)
    bd["ew_vol_20d"] = bd["ew_cc_ret"].rolling(20, min_periods=10).std() * np.sqrt(242.0)
    bd["bench_vol_20d"] = bd["bench_cc_ret"].rolling(20, min_periods=10).std() * np.sqrt(242.0)
    bd["amount_ratio_20d"] = bd["total_amount_yi"] / bd["total_amount_yi"].rolling(20, min_periods=5).mean()
    bd["amount_pct_250d"] = causal_rolling_pct(bd["total_amount_yi"], window=250, min_periods=60)
    bd["amount_pct_3y"] = causal_rolling_pct(bd["total_amount_yi"], window=726, min_periods=120)
    bd["turn_pct_250d"] = causal_rolling_pct(bd["turn_mkt_weighted"], window=250, min_periods=60)
    bd["turn_pct_3y"] = causal_rolling_pct(bd["turn_mkt_weighted"], window=726, min_periods=120)

    # Stamp tax daily
    bd["stamp_tax_rate"] = stamp_tax_rate_series(bd["date"])
    bd["stamp_tax_daily_yi"] = bd["total_amount_yi"] * bd["stamp_tax_rate"]

    # Join daily margin, northbound, CN10Y, and PE/PB/ERP strictly on obs_date <= date (same-day close / latest available)
    margin_d = _build_daily_margin(raw)
    if not margin_d.empty:
        bd = pd.merge_asof(
            bd.sort_values("date"),
            margin_d.rename(columns={"obs_date": "m_dt"}).sort_values("m_dt"),
            left_on="date", right_on="m_dt", direction="backward", tolerance=pd.Timedelta(days=10),
        ).drop(columns=["m_dt"])
    else:
        bd["margin_balance_yi"] = np.nan
    bd["margin_to_float_mcap_pct"] = np.where(
        bd["total_float_mcap_yi"] > 0, bd["margin_balance_yi"] / bd["total_float_mcap_yi"] * 100.0, np.nan
    )

    hsgt = raw.get("stock_hsgt_hist_em", pd.DataFrame()).copy()
    if not hsgt.empty:
        hsgt["date"] = pd.to_datetime(hsgt["日期"])
        hsgt["northbound_net_buy_yi"] = pd.to_numeric(hsgt["当日成交净买额"], errors="coerce")
        hsgt = hsgt[["date", "northbound_net_buy_yi"]].dropna().drop_duplicates("date")
        bd = bd.merge(hsgt, on="date", how="left")
    else:
        bd["northbound_net_buy_yi"] = np.nan

    # CN10Y from bond_zh_us_rate for daily ERP
    bond = raw.get("bond_zh_us_rate", pd.DataFrame()).copy()
    if not bond.empty:
        bond["b_dt"] = pd.to_datetime(bond["日期"])
        bond["cn10y_eod"] = pd.to_numeric(bond["中国国债收益率10年"], errors="coerce")
        bond = bond[["b_dt", "cn10y_eod"]].dropna().sort_values("b_dt")
        bd = pd.merge_asof(bd, bond, left_on="date", right_on="b_dt", direction="backward", tolerance=pd.Timedelta(days=10)).drop(columns=["b_dt"])
    else:
        bd["cn10y_eod"] = np.nan

    # PE / PB / ERP (stock_index_pe_lg monthly CSI300 + daily price adjustment; stock_a_ttm_lyr / stock_a_all_pb)
    pe300 = raw.get("stock_index_pe_lg", pd.DataFrame()).copy()
    if not pe300.empty:
        pe300["pe_dt"] = pd.to_datetime(pe300["日期"])
        pe300["pe300_idx"] = pd.to_numeric(pe300["指数"], errors="coerce")
        pe300["pe300_ttm"] = pd.to_numeric(pe300["滚动市盈率"], errors="coerce")
        pe300 = pe300[["pe_dt", "pe300_idx", "pe300_ttm"]].dropna().sort_values("pe_dt")
        bd = pd.merge_asof(bd, pe300, left_on="date", right_on="pe_dt", direction="backward").drop(columns=["pe_dt"])
        bd["csi300_pe_ttm_daily"] = np.where(
            bd["pe300_idx"] > 0, bd["pe300_ttm"] * (bd["csi300_close"] / bd["pe300_idx"]), np.nan
        )
        bd = bd.drop(columns=["pe300_idx", "pe300_ttm"])
    else:
        bd["csi300_pe_ttm_daily"] = np.nan

    pea = raw.get("stock_a_ttm_lyr", pd.DataFrame()).copy()
    if not pea.empty:
        pea["pa_dt"] = pd.to_datetime(pea["date"])
        pea["all_a_median_pe_ttm"] = pd.to_numeric(pea["middlePETTM"], errors="coerce")
        pea["all_a_avg_pe_ttm"] = pd.to_numeric(pea["averagePETTM"], errors="coerce")
        pea = pea[["pa_dt", "all_a_median_pe_ttm", "all_a_avg_pe_ttm"]].dropna().sort_values("pa_dt")
        bd = pd.merge_asof(bd, pea, left_on="date", right_on="pa_dt", direction="backward").drop(columns=["pa_dt"])
    else:
        bd["all_a_median_pe_ttm"] = np.nan
        bd["all_a_avg_pe_ttm"] = np.nan

    pba = raw.get("stock_a_all_pb", pd.DataFrame()).copy()
    if not pba.empty:
        pba["pb_dt"] = pd.to_datetime(pba["date"])
        pba["all_a_median_pb"] = pd.to_numeric(pba["middlePB"], errors="coerce")
        pba["all_a_ew_pb"] = pd.to_numeric(pba["equalWeightAveragePB"], errors="coerce")
        pba = pba[["pb_dt", "all_a_median_pb", "all_a_ew_pb"]].dropna().sort_values("pb_dt")
        bd = pd.merge_asof(bd, pba, left_on="date", right_on="pb_dt", direction="backward").drop(columns=["pb_dt"])
    else:
        bd["all_a_median_pb"] = np.nan
        bd["all_a_ew_pb"] = np.nan

    bd["erp_csi300_pct"] = 100.0 / bd["csi300_pe_ttm_daily"] - bd["cn10y_eod"]
    bd["erp_all_a_median_pct"] = 100.0 / bd["all_a_median_pe_ttm"] - bd["cn10y_eod"]
    bd["erp_csi300_pct_3y"] = causal_rolling_pct(bd["erp_csi300_pct"], window=726, min_periods=242)
    bd["erp_csi300_pct_5y"] = causal_rolling_pct(bd["erp_csi300_pct"], window=1210, min_periods=242)
    bd["erp_all_a_pct_3y"] = causal_rolling_pct(bd["erp_all_a_median_pct"], window=726, min_periods=242)
    bd["erp_all_a_pct_5y"] = causal_rolling_pct(bd["erp_all_a_median_pct"], window=1210, min_periods=242)

    breadth_daily = bd[bd["date"] >= pd.Timestamp("2005-01-01")].sort_values("date").reset_index(drop=True)

    # =========================================================================
    # Monthly Waterpool Ledger (2005-01 ~ 2026-11)
    # =========================================================================
    print("  Building Pillar 1 Monthly Waterpool Ledger (2005-01 ~ 2026-11)...")
    bd05 = breadth_daily.copy()
    bd05["month"] = bd05["date"].dt.strftime("%Y-%m")
    # Also compute daily margin balance change BEFORE monthly sum/diff
    m_base = bd05.groupby("month", sort=True).agg(
        n_trade_days=("date", "count"),
        month_end_date=("date", "max"),
        total_amount_yi=("total_amount_yi", "sum"),
        avg_daily_amount_yi=("total_amount_yi", "mean"),
        avg_float_mcap_yi=("total_float_mcap_yi", "mean"),
        eom_float_mcap_yi=("total_float_mcap_yi", "last"),
        stamp_tax_yi=("stamp_tax_daily_yi", "sum"),
        margin_balance_eom_yi=("margin_balance_yi", "last"),
        nt_etf_net_flow_yi=("etf_net_flow_yi", "sum"),
        nt_etf_weighted_flow_yi=("etf_nt_weighted_flow_yi", "sum"),
        nt_etf22_flow_yi=("etf22_flow_yi", "sum"),
        nt_etf22_wflow_yi=("etf22_wflow_yi", "sum"),
        northbound_net_buy_yi=("northbound_net_buy_yi", lambda s: s.sum() if s.notna().any() else np.nan),
        northbound_valid_days=("northbound_net_buy_yi", lambda s: int(s.notna().sum())),
    ).reset_index()

    m_base["available_date"] = pd.to_datetime(m_base["month_end_date"].map(strictly_after))
    m_base.loc[m_base["month"] == "2026-11", "available_date"] = pd.Timestamp("2026-11-25")
    m_base["commission_est_yi"] = m_base["total_amount_yi"] * 0.0005
    m_base["mkt_turn_monthly_pct"] = np.where(
        m_base["avg_float_mcap_yi"] > 0, m_base["total_amount_yi"] / m_base["avg_float_mcap_yi"] * 100.0, np.nan
    )
    # Fix ETF 2005-2009 to NaN (ETF share data starts 2010-01) and etf22 pre-2016 to NaN
    m_base.loc[m_base["month"] < "2010-01", ["nt_etf_net_flow_yi", "nt_etf_weighted_flow_yi"]] = np.nan
    m_base.loc[m_base["month"] < "2016-01", ["nt_etf22_flow_yi", "nt_etf22_wflow_yi"]] = np.nan
    m_base["margin_net_chg_yi"] = m_base["margin_balance_eom_yi"] - m_base["margin_balance_eom_yi"].shift(1)
    # First month margin started 2010-03-31 -> net_chg valid starting 2010-04
    m_base.loc[m_base["month"] <= "2010-03", "margin_net_chg_yi"] = np.nan

    anomalies = {}

    # 1) IPO (2005-2009 from cninfo + 2010-2026 from xgsglb)
    ipo_parts = []
    xg = raw.get("stock_xgsglb_em", pd.DataFrame()).copy()
    if not xg.empty:
        xg["list_dt"] = pd.to_datetime(xg["上市日期"], errors="coerce")
        xg = xg[(xg["list_dt"] >= "2010-01-01") & (xg["list_dt"] <= "2026-11-24")].copy()
        xg["code6"] = xg["股票代码"].astype(str).str.zfill(6)
        xg["raised_yi"] = pd.to_numeric(xg["发行总数"], errors="coerce") * pd.to_numeric(xg["发行价格"], errors="coerce") / 1e4
        xg["month"] = xg["list_dt"].dt.strftime("%Y-%m")
        ipo_parts.append(xg[["code6", "month", "raised_yi"]])

    ci = raw.get("ipo_2005_2009_cninfo", pd.DataFrame()).copy()
    if not ci.empty:
        ci["list_dt"] = pd.to_datetime(ci["上市日期"], errors="coerce")
        ci = ci[(ci["list_dt"] >= "2005-01-01") & (ci["list_dt"] <= "2009-12-31")].copy()
        ci["code6"] = ci["股票代码"].astype(str).str.zfill(6)
        net_yi = pd.to_numeric(ci["募集资金净额"], errors="coerce") / 1e4
        gross_yi = pd.to_numeric(ci["总发行数量"], errors="coerce") * pd.to_numeric(ci["发行价格"], errors="coerce") / 1e4
        ci["raised_yi"] = net_yi.fillna(gross_yi)
        ci["month"] = ci["list_dt"].dt.strftime("%Y-%m")
        ipo_parts.append(ci[["code6", "month", "raised_yi"]])

    if ipo_parts:
        ipo_all = pd.concat(ipo_parts, ignore_index=True).drop_duplicates("code6")
        ipo_m = ipo_all.groupby("month", as_index=False).agg(
            ipo_count=("code6", "count"),
            ipo_raised_yi=("raised_yi", "sum"),
        )
        m_base = m_base.merge(ipo_m, on="month", how="left")
        m_base["ipo_count"] = m_base["ipo_count"].fillna(0).astype(int)
        m_base["ipo_raised_yi"] = m_base["ipo_raised_yi"].fillna(0.0)
    else:
        m_base["ipo_count"] = np.nan
        m_base["ipo_raised_yi"] = np.nan

    # 2) Refinancing / SEO (stock_qbzf_em, 2011-01+)
    qz = raw.get("stock_qbzf_em", pd.DataFrame()).copy()
    if not qz.empty:
        qz["ev_dt"] = pd.to_datetime(qz["增发上市日期"], errors="coerce").fillna(pd.to_datetime(qz["发行日期"], errors="coerce"))
        qz = qz[(qz["ev_dt"] >= "2011-01-01") & (qz["ev_dt"] <= "2026-11-24")].copy()
        qz["amt_yi"] = pd.to_numeric(qz["发行总数"], errors="coerce") * pd.to_numeric(qz["发行价格"], errors="coerce") / 1e8
        qz["month"] = qz["ev_dt"].dt.strftime("%Y-%m")
        qz["is_pub"] = qz["发行方式"].astype(str).str.contains("公开")
        qz_m = qz.groupby("month", as_index=False).agg(
            refinance_count=("amt_yi", "count"),
            refinance_yi=("amt_yi", "sum"),
            refinance_public_yi=("amt_yi", lambda s: s[qz.loc[s.index, "is_pub"]].sum()),
            refinance_private_yi=("amt_yi", lambda s: s[~qz.loc[s.index, "is_pub"]].sum()),
        )
        m_base = m_base.merge(qz_m, on="month", how="left")
        mask_qz = m_base["month"] >= "2011-01"
        m_base.loc[mask_qz, "refinance_count"] = m_base.loc[mask_qz, "refinance_count"].fillna(0)
        for c in ["refinance_yi", "refinance_public_yi", "refinance_private_yi"]:
            m_base.loc[mask_qz, c] = m_base.loc[mask_qz, c].fillna(0.0)
    else:
        for c in ["refinance_count", "refinance_yi", "refinance_public_yi", "refinance_private_yi"]:
            m_base[c] = np.nan

    # 3) Insider reduction / addition (stock_ggcg_em joined with historical close price!)
    gg = raw.get("stock_ggcg_em", pd.DataFrame()).copy()
    if not gg.empty:
        gg["code6"] = gg["代码"].astype(str).str.zfill(6)
        gg["ann_dt"] = pd.to_datetime(gg["公告日"], errors="coerce")
        gg["trade_dt"] = pd.to_datetime(gg["变动截止日"], errors="coerce").fillna(gg["ann_dt"])
        gg = gg[(gg["ann_dt"] >= "2005-01-01") & (gg["ann_dt"] <= "2026-11-24")].copy()
        gg["chg_wan"] = pd.to_numeric(gg["持股变动信息-变动数量"], errors="coerce").abs()
        gg["pct_tot"] = pd.to_numeric(gg["持股变动信息-占总股本比例"], errors="coerce").abs()
        gg["dir"] = gg["持股变动信息-增减"].astype(str)

        # Historical price join strictly at trade_dt (fallback backward)
        px_ref = stk[["code6", "date", "close", "oshare"]].sort_values("date").copy()
        gg = gg.sort_values("trade_dt")
        gg = pd.merge_asof(
            gg, px_ref, left_on="trade_dt", right_on="date", by="code6",
            direction="backward", tolerance=pd.Timedelta(days=60),
        )
        # Unit check: Eastmoney sometimes encodes shares instead of 万股 if pct_tot > 100 or implied mcap absurd
        gg["amt_yi"] = gg["chg_wan"] * gg["close"] / 1e4
        # Flag obvious raw glitches (e.g. single shareholder trade > 500亿元 or pct_tot > 60%)
        glitch_msk = (gg["amt_yi"] > 500.0) | (gg["pct_tot"] > 60.0)
        anomalies["ggcg_flagged_outliers"] = int(glitch_msk.sum())
        anomalies["ggcg_total_rows_2005_2026"] = int(len(gg))
        gg_clean = gg[~glitch_msk & gg["amt_yi"].notna()].copy()
        gg_clean["month"] = gg_clean["ann_dt"].dt.strftime("%Y-%m")
        gg_clean["is_red"] = gg_clean["dir"].str.contains("减")
        gg_clean["is_add"] = gg_clean["dir"].str.contains("增")
        gg_m = gg_clean.groupby("month", as_index=False).agg(
            insider_reduce_yi=("amt_yi", lambda s: s[gg_clean.loc[s.index, "is_red"]].sum()),
            insider_add_yi=("amt_yi", lambda s: s[gg_clean.loc[s.index, "is_add"]].sum()),
        )
        gg_m["insider_net_reduce_yi"] = gg_m["insider_reduce_yi"] - gg_m["insider_add_yi"]
        m_base = m_base.merge(gg_m, on="month", how="left")
        for c in ["insider_reduce_yi", "insider_add_yi", "insider_net_reduce_yi"]:
            m_base[c] = m_base[c].fillna(0.0)
    else:
        for c in ["insider_reduce_yi", "insider_add_yi", "insider_net_reduce_yi"]:
            m_base[c] = np.nan

    # 4) Block trades (stock_dzjy_sctj, 2000-08 ~ 2026-11)
    dz = raw.get("stock_dzjy_sctj", pd.DataFrame()).copy()
    if not dz.empty:
        dz["dt"] = pd.to_datetime(dz["交易日期"], errors="coerce")
        dz = dz[(dz["dt"] >= "2005-01-01") & (dz["dt"] <= "2026-11-24")].copy()
        dz["month"] = dz["dt"].dt.strftime("%Y-%m")
        dz["tot_yi"] = pd.to_numeric(dz["大宗交易成交总额"], errors="coerce") / 1e8
        dz["disc_yi"] = pd.to_numeric(dz["折价成交总额"], errors="coerce") / 1e8
        dz_m = dz.groupby("month", as_index=False).agg(
            block_trade_yi=("tot_yi", "sum"),
            block_trade_discount_yi=("disc_yi", "sum"),
        )
        m_base = m_base.merge(dz_m, on="month", how="left")
        m_base["block_trade_yi"] = m_base["block_trade_yi"].fillna(0.0)
        m_base["block_trade_discount_yi"] = m_base["block_trade_discount_yi"].fillna(0.0)
    else:
        m_base["block_trade_yi"] = np.nan
        m_base["block_trade_discount_yi"] = np.nan

    # 5) Buybacks (stock_repurchase_em, 2005-06+)
    rp = raw.get("stock_repurchase_em", pd.DataFrame()).copy()
    if not rp.empty:
        rp["ann_dt"] = pd.to_datetime(rp["最新公告日期"], errors="coerce")
        rp = rp[(rp["ann_dt"] >= "2005-01-01") & (rp["ann_dt"] <= "2026-11-24")].copy()
        rp["buyback_yi"] = pd.to_numeric(rp["已回购金额"], errors="coerce") / 1e8
        rp = rp[rp["buyback_yi"] > 0].copy()
        rp["month"] = rp["ann_dt"].dt.strftime("%Y-%m")
        rp_m = rp.groupby("month", as_index=False).agg(buyback_yi=("buyback_yi", "sum"))
        m_base = m_base.merge(rp_m, on="month", how="left")
        m_base.loc[m_base["month"] >= "2005-06", "buyback_yi"] = m_base.loc[m_base["month"] >= "2005-06", "buyback_yi"].fillna(0.0)
    else:
        m_base["buyback_yi"] = np.nan

    # 6) Cash dividends (stock_fhps_em_all, 2005-01+)
    fh = raw.get("stock_fhps_em_all", pd.DataFrame()).copy()
    if not fh.empty:
        fh["ex_dt"] = pd.to_datetime(fh["除权除息日"], errors="coerce")
        fh = fh[(fh["ex_dt"] >= "2005-01-01") & (fh["ex_dt"] <= "2026-11-24")].copy()
        fh["code6"] = fh["代码"].astype(str).str.zfill(6)
        fh = fh.drop_duplicates(["code6", "report_period", "ex_dt"])
        fh["div_per_10"] = pd.to_numeric(fh["现金分红-现金分红比例"], errors="coerce")
        fh["tot_shares"] = pd.to_numeric(fh["总股本"], errors="coerce")
        fh["div_yi"] = fh["tot_shares"] * fh["div_per_10"] / 10.0 / 1e8
        fh = fh[(fh["div_yi"] > 0) & (fh["div_yi"] < 3000.0)].copy()
        fh["month"] = fh["ex_dt"].dt.strftime("%Y-%m")
        fh_m = fh.groupby("month", as_index=False).agg(cash_dividend_yi=("div_yi", "sum"))
        m_base = m_base.merge(fh_m, on="month", how="left")
        m_base["cash_dividend_yi"] = m_base["cash_dividend_yi"].fillna(0.0)
    else:
        m_base["cash_dividend_yi"] = np.nan

    # Synthetic Waterpool Net Balance Columns
    m_base["drain_equity_supply_yi"] = (
        m_base["ipo_raised_yi"].fillna(0.0)
        + m_base["refinance_yi"].fillna(0.0)
        + m_base["insider_net_reduce_yi"].fillna(0.0).clip(lower=0.0)
    )
    m_base["drain_total_yi"] = m_base["drain_equity_supply_yi"] + m_base["stamp_tax_yi"].fillna(0.0)
    m_base["inject_trading_yi"] = (
        m_base["margin_net_chg_yi"].fillna(0.0)
        + m_base["nt_etf_weighted_flow_yi"].fillna(0.0)
        + m_base["northbound_net_buy_yi"].fillna(0.0)
        + m_base["buyback_yi"].fillna(0.0)
    )
    m_base["inject_total_incl_div_yi"] = m_base["inject_trading_yi"] + m_base["cash_dividend_yi"].fillna(0.0)
    m_base["net_waterpool_trading_yi"] = m_base["inject_trading_yi"] - m_base["drain_total_yi"]
    m_base["net_waterpool_incl_div_yi"] = m_base["inject_total_incl_div_yi"] - m_base["drain_total_yi"]

    for col, norm_col in [
        ("drain_total_yi", "drain_total_pct_mcap"),
        ("inject_trading_yi", "inject_trading_pct_mcap"),
        ("net_waterpool_trading_yi", "net_waterpool_trading_pct_mcap"),
        ("net_waterpool_incl_div_yi", "net_waterpool_incl_div_pct_mcap"),
    ]:
        m_base[norm_col] = np.where(
            m_base["eom_float_mcap_yi"] > 0, m_base[col] / m_base["eom_float_mcap_yi"] * 100.0, np.nan
        )

    for col in ["ipo_raised_yi", "drain_total_yi", "inject_trading_yi", "net_waterpool_trading_yi", "cash_dividend_yi"]:
        m_base[f"{col}_3m_sum"] = m_base[col].rolling(3, min_periods=1).sum()
        m_base[f"{col}_12m_sum"] = m_base[col].rolling(12, min_periods=3).sum()

    for col in ["drain_total_pct_mcap", "net_waterpool_trading_pct_mcap", "net_waterpool_incl_div_pct_mcap"]:
        m_base[f"{col}_pct_3y"] = causal_rolling_pct(m_base[col], window=36, min_periods=12)
        m_base[f"{col}_pct_5y"] = causal_rolling_pct(m_base[col], window=60, min_periods=12)

    return breadth_daily, m_base, anomalies
