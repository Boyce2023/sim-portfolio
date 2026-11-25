#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Build Pillar 4 dataset: pillar4_macro_pain_daily_pit.parquet (2005-01-04 ~ 2026-11-24).
Strictly aligned to official China/US release dates (available_date <= date),
with per-series raw values, MoM/YoY/20d/60d/250d changes, and 3Y/5Y causal percentiles.
"""
import os
import numpy as np
import pandas as pd

from pit_utils import (
    build_pit_mapper,
    causal_rolling_pct,
    parse_quarter_end_ym,
    parse_ym_str,
    pit_asof_join,
)

ROOT = "/Users/huaichuaibeimeng/claude-projects"
DMP_PATH = os.path.join(ROOT, "output/csrc_policy_100factors_20261114/policy_polymarket_v1/daily_market_panel_v2_20261124.parquet")
US_PIT_PATH = os.path.join(ROOT, "sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/data/macro_pit_daily_1990_2026.parquet")
FRED_DIR = os.path.join(ROOT, "sim-portfolio/data/us_price_db/macro")


def _load_fred_series(series_id: str) -> pd.DataFrame:
    p = os.path.join(FRED_DIR, f"{series_id}.parquet")
    if not os.path.exists(p):
        return pd.DataFrame(columns=["obs_date", "value"])
    d = pd.read_parquet(p).reset_index()
    d.columns = ["obs_date", "value"]
    d["obs_date"] = pd.to_datetime(d["obs_date"])
    d["value"] = pd.to_numeric(d["value"], errors="coerce")
    return d.dropna().sort_values("obs_date").reset_index(drop=True)


def _prep_monthly_frame(df: pd.DataFrame, ym_col: str, val_map: dict[str, str], avail_fn) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    d["ym"] = d[ym_col].map(parse_ym_str)
    d = d.dropna(subset=["ym"]).sort_values("ym").drop_duplicates("ym", keep="last").reset_index(drop=True)
    out = pd.DataFrame({"ym": d["ym"]})
    for src_col, dst_col in val_map.items():
        out[dst_col] = pd.to_numeric(d[src_col], errors="coerce") if src_col in d.columns else np.nan
    out["available_date"] = out["ym"].map(avail_fn)
    return out


def _build_china_monthly_macro(raw: dict, ym_day_available, pmi_available) -> dict[str, pd.DataFrame]:
    """Prepare each China monthly/quarterly macro block with exact PIT available_date."""
    blocks = {}

    # 1. M0/M1/M2 (1978~2026.10 from supply_of_money + fill from money_supply)
    som = _prep_monthly_frame(
        raw.get("macro_china_supply_of_money"),
        "统计时间",
        {
            "货币和准货币（广义货币M2）同比增长": "cn_m2_yoy",
            "货币(狭义货币M1)同比增长": "cn_m1_yoy",
            "流通中现金(M0)同比增长": "cn_m0_yoy",
        },
        lambda ym: ym_day_available(ym, 16),
    )
    ms = _prep_monthly_frame(
        raw.get("macro_china_money_supply"),
        "月份",
        {
            "货币和准货币(M2)-同比增长": "cn_m2_yoy",
            "货币(M1)-同比增长": "cn_m1_yoy",
            "流通中的现金(M0)-同比增长": "cn_m0_yoy",
        },
        lambda ym: ym_day_available(ym, 16),
    )
    if not som.empty or not ms.empty:
        if not som.empty:
            som["_prio"] = 0
        if not ms.empty:
            ms["_prio"] = 1
        m12 = (
            pd.concat([som, ms], ignore_index=True)
            .sort_values(["ym", "_prio"], kind="mergesort")
            .groupby("ym", as_index=False)
            .agg({
                "cn_m2_yoy": "last",
                "cn_m1_yoy": "last",
                "cn_m0_yoy": "last",
                "available_date": "last",
            })
            .sort_values("ym")
            .reset_index(drop=True)
        )
        m12["cn_m1_m2_diff"] = m12["cn_m1_yoy"] - m12["cn_m2_yoy"]
        m12["cn_m1_m2_diff_mom"] = m12["cn_m1_m2_diff"] - m12["cn_m1_m2_diff"].shift(1)
        m12["cn_m1_yoy_mom"] = m12["cn_m1_yoy"] - m12["cn_m1_yoy"].shift(1)
        m12["cn_m2_yoy_mom"] = m12["cn_m2_yoy"] - m12["cn_m2_yoy"].shift(1)
        blocks["m12"] = (m12, ["cn_m2_yoy", "cn_m1_yoy", "cn_m0_yoy", "cn_m1_m2_diff", "cn_m1_m2_diff_mom", "cn_m1_yoy_mom", "cn_m2_yoy_mom"], 50)

    # 2. New RMB Loan (2008-01 ~ 2026-10)
    cr = _prep_monthly_frame(
        raw.get("macro_china_new_financial_credit"),
        "月份",
        {"当月": "cn_new_loan_yi", "当月-同比增长": "cn_new_loan_yoy"},
        lambda ym: ym_day_available(ym, 16),
    )
    if not cr.empty:
        cr["cn_new_loan_12m_yi"] = cr["cn_new_loan_yi"].rolling(12, min_periods=6).sum()
        blocks["credit"] = (cr, ["cn_new_loan_yi", "cn_new_loan_yoy", "cn_new_loan_12m_yi"], 50)

    # 3. Total Social Financing (TSF, 2015-01 ~ 2026-04 -> stale cutoff 50d)
    tsf = _prep_monthly_frame(
        raw.get("macro_china_shrzgm"),
        "月份",
        {"社会融资规模增量": "cn_tsf_yi"},
        lambda ym: ym_day_available(ym, 16),
    )
    if not tsf.empty:
        tsf["cn_tsf_yoy_diff"] = tsf["cn_tsf_yi"] - tsf["cn_tsf_yi"].shift(12)
        tsf["cn_tsf_12m_yi"] = tsf["cn_tsf_yi"].rolling(12, min_periods=6).sum()
        blocks["tsf"] = (tsf, ["cn_tsf_yi", "cn_tsf_yoy_diff", "cn_tsf_12m_yi"], 50)

    # 4. PBOC Balance Sheet (1993.3 ~ 2026.10)
    pboc = _prep_monthly_frame(
        raw.get("macro_china_central_bank_balance"),
        "统计时间",
        {"总资产": "cn_pboc_assets_yi", "外汇": "cn_pboc_fx_yi"},
        lambda ym: ym_day_available(ym, 16),
    )
    if not pboc.empty:
        pboc["cn_pboc_assets_yoy"] = (pboc["cn_pboc_assets_yi"] / pboc["cn_pboc_assets_yi"].shift(12) - 1.0) * 100.0
        blocks["pboc"] = (pboc, ["cn_pboc_assets_yi", "cn_pboc_fx_yi", "cn_pboc_assets_yoy"], 50)

    # 5. Official PMI (2005-01 ~ 2026-10)
    pmi_y = raw.get("macro_china_pmi_yearly", pd.DataFrame()).copy()
    pmi_pre = pd.DataFrame()
    if not pmi_y.empty:
        pmi_y["dt"] = pd.to_datetime(pmi_y["日期"], errors="coerce")
        pmi_y["val"] = pd.to_numeric(pmi_y["今值"], errors="coerce")
        pmi_y = pmi_y.dropna(subset=["dt", "val"])
        pmi_y["ym"] = np.where(
            pmi_y["dt"].dt.day <= 5,
            (pmi_y["dt"] - pd.Timedelta(days=10)).dt.strftime("%Y-%m"),
            pmi_y["dt"].dt.strftime("%Y-%m"),
        )
        pmi_pre = pd.DataFrame({"ym": pmi_y["ym"], "cn_pmi_mfg": pmi_y["val"]}).drop_duplicates("ym", keep="last")
        pmi_pre["cn_pmi_non_mfg"] = np.nan
        pmi_pre["available_date"] = pmi_pre["ym"].map(pmi_available)
        pmi_pre["_prio"] = 0

    nm_y = raw.get("macro_china_non_man_pmi", pd.DataFrame()).copy()
    nm_pre = pd.DataFrame()
    if not nm_y.empty:
        nm_y["dt"] = pd.to_datetime(nm_y["日期"], errors="coerce")
        nm_y["val"] = pd.to_numeric(nm_y["今值"], errors="coerce")
        nm_y = nm_y.dropna(subset=["dt", "val"])
        nm_y["ym"] = np.where(
            nm_y["dt"].dt.day <= 5,
            (nm_y["dt"] - pd.Timedelta(days=10)).dt.strftime("%Y-%m"),
            nm_y["dt"].dt.strftime("%Y-%m"),
        )
        nm_pre = pd.DataFrame({"ym": nm_y["ym"], "cn_pmi_non_mfg_backfill": nm_y["val"]}).drop_duplicates("ym", keep="last")

    pmi_m = _prep_monthly_frame(
        raw.get("macro_china_pmi"),
        "月份",
        {"制造业-指数": "cn_pmi_mfg", "非制造业-指数": "cn_pmi_non_mfg"},
        pmi_available,
    )
    if not pmi_m.empty:
        pmi_m["_prio"] = 1
    if not pmi_pre.empty or not pmi_m.empty:
        pmi = (
            pd.concat([pmi_pre, pmi_m], ignore_index=True)
            .sort_values(["ym", "_prio"], kind="mergesort")
            .groupby("ym", as_index=False)
            .agg({
                "cn_pmi_mfg": "last",
                "cn_pmi_non_mfg": "last",
                "available_date": "last",
            })
            .sort_values("ym")
            .reset_index(drop=True)
        )
        if not nm_pre.empty:
            pmi = pmi.merge(nm_pre, on="ym", how="left")
            pmi["cn_pmi_non_mfg"] = pmi["cn_pmi_non_mfg"].fillna(pmi["cn_pmi_non_mfg_backfill"])
            pmi = pmi.drop(columns=["cn_pmi_non_mfg_backfill"])
        pmi["cn_pmi_mfg_mom"] = pmi["cn_pmi_mfg"] - pmi["cn_pmi_mfg"].shift(1)
        pmi["cn_pmi_mfg_yoy"] = pmi["cn_pmi_mfg"] - pmi["cn_pmi_mfg"].shift(12)
        blocks["pmi"] = (pmi, ["cn_pmi_mfg", "cn_pmi_non_mfg", "cn_pmi_mfg_mom", "cn_pmi_mfg_yoy"], 50)

    # 6. CPI & PPI (1996/2000 ~ 2026-10)
    def _parse_jin10_prev_month(df_raw: pd.DataFrame, col_name: str) -> pd.DataFrame:
        if df_raw is None or df_raw.empty:
            return pd.DataFrame()
        d = df_raw.copy()
        d["dt"] = pd.to_datetime(d["日期"], errors="coerce")
        d[col_name] = pd.to_numeric(d["今值"], errors="coerce")
        d = d.dropna(subset=["dt", col_name])
        d["ym"] = (d["dt"].dt.to_period("M") - 1).astype(str)
        out = d[["ym", col_name]].drop_duplicates("ym", keep="last").copy()
        out["available_date"] = out["ym"].map(lambda ym: ym_day_available(ym, 12))
        out["_prio"] = 0
        return out

    cpi_pre = _parse_jin10_prev_month(raw.get("macro_china_cpi_yearly"), "cn_cpi_yoy")
    cpi_m = _prep_monthly_frame(raw.get("macro_china_cpi"), "月份", {"全国-同比增长": "cn_cpi_yoy"}, lambda ym: ym_day_available(ym, 12))
    if not cpi_m.empty:
        cpi_m["_prio"] = 1
    cpi = pd.concat([cpi_pre, cpi_m], ignore_index=True).sort_values(["ym", "_prio"], kind="mergesort").groupby("ym", as_index=False).agg({"cn_cpi_yoy": "last", "available_date": "last"}).sort_values("ym").reset_index(drop=True)
    cpi["cn_cpi_yoy_mom"] = cpi["cn_cpi_yoy"] - cpi["cn_cpi_yoy"].shift(1)

    ppi_pre = _parse_jin10_prev_month(raw.get("macro_china_ppi_yearly"), "cn_ppi_yoy")
    ppi_m = _prep_monthly_frame(raw.get("macro_china_ppi"), "月份", {"当月同比增长": "cn_ppi_yoy"}, lambda ym: ym_day_available(ym, 12))
    if not ppi_m.empty:
        ppi_m["_prio"] = 1
    ppi = pd.concat([ppi_pre, ppi_m], ignore_index=True).sort_values(["ym", "_prio"], kind="mergesort").groupby("ym", as_index=False).agg({"cn_ppi_yoy": "last", "available_date": "last"}).sort_values("ym").reset_index(drop=True)
    ppi["cn_ppi_yoy_mom"] = ppi["cn_ppi_yoy"] - ppi["cn_ppi_yoy"].shift(1)

    inf = cpi.merge(ppi[["ym", "cn_ppi_yoy", "cn_ppi_yoy_mom"]], on="ym", how="outer").sort_values("ym").reset_index(drop=True)
    inf["available_date"] = inf["ym"].map(lambda ym: ym_day_available(ym, 12))
    inf["cn_ppi_minus_cpi"] = inf["cn_ppi_yoy"] - inf["cn_cpi_yoy"]
    blocks["inflation"] = (inf, ["cn_cpi_yoy", "cn_cpi_yoy_mom", "cn_ppi_yoy", "cn_ppi_yoy_mom", "cn_ppi_minus_cpi"], 50)

    # 7. Trade & FX Reserves (2008-01 ~ 2026-10)
    trd = _prep_monthly_frame(
        raw.get("macro_china_hgjck"),
        "月份",
        {"当月出口额-同比增长": "cn_exports_yoy", "当月进口额-同比增长": "cn_imports_yoy"},
        lambda ym: ym_day_available(ym, 12),
    )
    if not trd.empty:
        blocks["trade"] = (trd, ["cn_exports_yoy", "cn_imports_yoy"], 50)

    fxr = _prep_monthly_frame(
        raw.get("macro_china_fx_gold"),
        "月份",
        {"国家外汇储备-数值": "cn_fx_reserves_100m_usd", "国家外汇储备-同比": "cn_fx_reserves_yoy"},
        lambda ym: ym_day_available(ym, 12),
    )
    if not fxr.empty:
        blocks["fx_res"] = (fxr, ["cn_fx_reserves_100m_usd", "cn_fx_reserves_yoy"], 50)

    # 8. Fiscal revenue (2008-01 ~ 2026-10)
    fisc = _prep_monthly_frame(
        raw.get("macro_china_czsr"),
        "月份",
        {"当月-同比增长": "cn_fiscal_rev_yoy"},
        lambda ym: ym_day_available(ym, 16),
    )
    if not fisc.empty:
        blocks["fiscal"] = (fisc, ["cn_fiscal_rev_yoy"], 50)

    # 9. Industrial Production, Retail Sales, FAI, Real Estate Climate, Consumer Confidence
    ip_pre = _parse_jin10_prev_month(raw.get("macro_china_industrial_production_yoy"), "cn_ind_prod_yoy")
    ip_m_raw = raw.get("macro_china_gyzjz", pd.DataFrame()).copy()
    ip_m = pd.DataFrame()
    if not ip_m_raw.empty:
        ip_m_raw["ym"] = ip_m_raw["月份"].map(parse_ym_str)
        ip_m_raw = ip_m_raw.dropna(subset=["ym"]).sort_values("ym").drop_duplicates("ym", keep="last")
        yoy = pd.to_numeric(ip_m_raw["同比增长"], errors="coerce")
        ytd = pd.to_numeric(ip_m_raw["累计增长"], errors="coerce")
        ip_m = pd.DataFrame({
            "ym": ip_m_raw["ym"],
            "cn_ind_prod_yoy": yoy.fillna(ytd),
            "available_date": ip_m_raw["ym"].map(lambda ym: ym_day_available(ym, 19)),
        })
    if not ip_m.empty:
        ip_m["_prio"] = 1
    ip = pd.concat([ip_pre, ip_m], ignore_index=True).sort_values(["ym", "_prio"], kind="mergesort").groupby("ym", as_index=False).agg({"cn_ind_prod_yoy": "last", "available_date": "last"}).sort_values("ym").reset_index(drop=True)
    if not ip.empty:
        # Feb NBS print combines Jan+Feb, so tolerate up to 75 days across Jan-Feb holiday gap
        blocks["ind_prod"] = (ip, ["cn_ind_prod_yoy"], 75)

    ret_raw = raw.get("macro_china_consumer_goods_retail")
    if ret_raw is not None and not ret_raw.empty:
        ret = _prep_monthly_frame(
            ret_raw,
            "月份",
            {"同比增长": "cn_retail_sales_yoy", "累计-同比增长": "cn_retail_ytd_yoy"},
            lambda ym: ym_day_available(ym, 19),
        )
        ret["cn_retail_sales_yoy"] = ret["cn_retail_sales_yoy"].fillna(ret["cn_retail_ytd_yoy"])
        blocks["retail"] = (ret, ["cn_retail_sales_yoy"], 75)

    fai_raw = raw.get("macro_china_gdzctz", pd.DataFrame()).copy()
    if not fai_raw.empty:
        fai = _prep_monthly_frame(
            fai_raw, "月份", {"同比增长": "cn_fai_yoy", "自年初累计": "cn_fai_ytd_val"}, lambda ym: ym_day_available(ym, 19)
        )
        # Fill YoY from YTD cumulative YoY when monthly YoY is missing (e.g., Feb combined print)
        fai_ytd_map = fai.set_index("ym")["cn_fai_ytd_val"].to_dict()
        calc_ytd_yoy = []
        for _, r in fai.iterrows():
            ym_prev = str(pd.Period(r["ym"], freq="M") - 12)
            v_cur, v_prv = r["cn_fai_ytd_val"], fai_ytd_map.get(ym_prev, np.nan)
            calc_ytd_yoy.append((v_cur / v_prv - 1.0) * 100.0 if pd.notna(v_cur) and pd.notna(v_prv) and v_prv > 0 else np.nan)
        fai["cn_fai_ytd_yoy"] = calc_ytd_yoy
        fai["cn_fai_yoy"] = fai["cn_fai_yoy"].fillna(fai["cn_fai_ytd_yoy"])
        blocks["fai"] = (fai, ["cn_fai_yoy", "cn_fai_ytd_yoy"], 75)

    re_raw = raw.get("macro_china_real_estate", pd.DataFrame()).copy()
    if not re_raw.empty:
        re_df = _prep_monthly_frame(
            re_raw, "日期", {"最新值": "cn_real_estate_climate", "近1年涨跌幅": "cn_real_estate_yoy"}, lambda ym: ym_day_available(ym, 19)
        )
        blocks["real_estate"] = (re_df, ["cn_real_estate_climate", "cn_real_estate_yoy"], 50)

    cc_raw = raw.get("macro_china_xfzxx", pd.DataFrame()).copy()
    if not cc_raw.empty:
        cc_df = _prep_monthly_frame(
            cc_raw, "月份", {"消费者信心指数-指数值": "cn_consumer_conf"}, lambda ym: ym_day_available(ym, 19)
        )
        blocks["cons_conf"] = (cc_df, ["cn_consumer_conf"], 80)

    # 10. GDP Quarterly (2006 Q1 ~ 2026 Q3)
    gdp_raw = raw.get("macro_china_gdp", pd.DataFrame()).copy()
    if not gdp_raw.empty:
        gdp_raw["ym"] = gdp_raw["季度"].map(parse_quarter_end_ym)
        gdp_raw["cn_gdp_yoy"] = pd.to_numeric(gdp_raw["国内生产总值-同比增长"], errors="coerce")
        gdp = gdp_raw.dropna(subset=["ym", "cn_gdp_yoy"]).sort_values("ym").drop_duplicates("ym", keep="last").reset_index(drop=True)
        gdp["available_date"] = gdp["ym"].map(lambda ym: ym_day_available(ym, 20))
        gdp["cn_gdp_yoy_qoq"] = gdp["cn_gdp_yoy"] - gdp["cn_gdp_yoy"].shift(1)
        blocks["gdp"] = (gdp, ["cn_gdp_yoy", "cn_gdp_yoy_qoq"], 110)

    return blocks


def build_macro_pain(raw: dict) -> pd.DataFrame:
    """Build daily PIT macro pain & US-China constraints table (2005-01-04 ~ 2026-11-24)."""
    dmp = pd.read_parquet(DMP_PATH, columns=["date"]).sort_values("date").drop_duplicates("date")
    dmp["date"] = pd.to_datetime(dmp["date"])
    dmp = dmp[dmp["date"] <= pd.Timestamp("2026-11-24")].reset_index(drop=True)
    on_or_after, strictly_after, ym_day_available, pmi_available = build_pit_mapper(dmp["date"])

    panel = dmp.copy()

    # 1. China Monthly/Quarterly PIT merges
    print("  Aligning China monthly/quarterly macro to strict PIT available_date...")
    ch_blocks = _build_china_monthly_macro(raw, ym_day_available, pmi_available)
    for _, (bdf, cols, staleness) in ch_blocks.items():
        merged = pit_asof_join(panel[["date"]], bdf, "available_date", cols, max_staleness_days=staleness)
        for c in cols:
            panel[c] = merged[c].values

    # 2. LPR & PBOC 1Y benchmark loan rate (strictly T+1)
    lpr = raw.get("macro_china_lpr", pd.DataFrame()).copy()
    if not lpr.empty:
        lpr["obs_date"] = pd.to_datetime(lpr["TRADE_DATE"])
        lpr["cn_lpr_1y"] = pd.to_numeric(lpr["LPR1Y"], errors="coerce")
        lpr["cn_lpr_5y"] = pd.to_numeric(lpr["LPR5Y"], errors="coerce")
        lpr["cn_pboc_loan_1y"] = pd.to_numeric(lpr["RATE_1"], errors="coerce")
        lpr["cn_policy_rate_1y"] = lpr["cn_lpr_1y"].fillna(lpr["cn_pboc_loan_1y"])
        lpr["available_date"] = lpr["obs_date"].map(strictly_after)
        m_lpr = pit_asof_join(panel[["date"]], lpr, "available_date", ["cn_lpr_1y", "cn_lpr_5y", "cn_pboc_loan_1y", "cn_policy_rate_1y"])
        for c in ["cn_lpr_1y", "cn_lpr_5y", "cn_pboc_loan_1y", "cn_policy_rate_1y"]:
            panel[c] = m_lpr[c].values

    # 3. China & US Sovereign Bond Yields (bond_zh_us_rate, strictly T+1)
    bond = raw.get("bond_zh_us_rate", pd.DataFrame()).copy()
    if not bond.empty:
        bond["obs_date"] = pd.to_datetime(bond["日期"])
        bond["cn_bond_2y"] = pd.to_numeric(bond["中国国债收益率2年"], errors="coerce")
        bond["cn_bond_10y"] = pd.to_numeric(bond["中国国债收益率10年"], errors="coerce")
        bond["cn_bond_30y"] = pd.to_numeric(bond["中国国债收益率30年"], errors="coerce")
        bond["cn_10y_2y_spread"] = bond["cn_bond_10y"] - bond["cn_bond_2y"]
        bond["available_date"] = bond["obs_date"].map(strictly_after)
        b_cols = ["cn_bond_2y", "cn_bond_10y", "cn_bond_30y", "cn_10y_2y_spread"]
        m_b = pit_asof_join(panel[["date"]], bond, "available_date", b_cols, max_staleness_days=15)
        for c in b_cols:
            panel[c] = m_b[c].values

    # 4. USDCNY Exchange Rate (currency_boc_safe + FRED DEXCHUS, strictly T+1)
    boc = raw.get("currency_boc_safe", pd.DataFrame()).copy()
    fx_parts = []
    if not boc.empty:
        boc["obs_date"] = pd.to_datetime(boc["日期"])
        boc["usdcny"] = pd.to_numeric(boc["美元"], errors="coerce") / 100.0
        fx_parts.append(boc[["obs_date", "usdcny"]].dropna())
    dex = _load_fred_series("DEXCHUS").rename(columns={"value": "usdcny"})
    if not dex.empty:
        # BOC safe takes precedence where present; fill missing with FRED DEXCHUS
        fx = pd.concat([dex, fx_parts[0]] if fx_parts else [dex], ignore_index=True)
        fx = fx.sort_values("obs_date").drop_duplicates("obs_date", keep="last")
    else:
        fx = fx_parts[0] if fx_parts else pd.DataFrame(columns=["obs_date", "usdcny"])
    if not fx.empty:
        fx["available_date"] = fx["obs_date"].map(strictly_after)
        m_fx = pit_asof_join(panel[["date"]], fx, "available_date", ["usdcny"], max_staleness_days=15)
        panel["usdcny"] = m_fx["usdcny"].values

    # 5. US PIT Macro & Global Financial Constraints (ALFRED macro_pit_daily_1990_2026 + FRED parquet up to 2026-11-23)
    print("  Merging US ALFRED PIT & FRED constraints (strictly T+1)...")
    us_pit = pd.read_parquet(US_PIT_PATH)
    us_pit["obs_date"] = pd.to_datetime(us_pit["date"])
    us_pit["available_date"] = us_pit["obs_date"].map(strictly_after)

    # Stitch daily US series from FRED directory to reach 2026-11-23 (ALFRED table ends 2026-11-09)
    def _stitch_us_daily(pit_col: str, fred_id: str, out_col: str, staleness: int = 15):
        p1 = us_pit[["obs_date", pit_col]].rename(columns={pit_col: out_col}).dropna()
        p2 = _load_fred_series(fred_id).rename(columns={"value": out_col})
        comb = pd.concat([p1, p2], ignore_index=True).sort_values("obs_date").drop_duplicates("obs_date", keep="last")
        comb["available_date"] = comb["obs_date"].map(strictly_after)
        m = pit_asof_join(panel[["date"]], comb, "available_date", [out_col], max_staleness_days=staleness)
        panel[out_col] = m[out_col].values

    _stitch_us_daily("dgs10", "DGS10", "us_dgs10")
    _stitch_us_daily("dgs2", "DGS2", "us_dgs2")
    _stitch_us_daily("dff", "DFF", "us_dff")
    _stitch_us_daily("dfii10", "DFII10", "us_dfii10")
    _stitch_us_daily("baa10y", "BAA10Y", "us_baa10y")
    _stitch_us_daily("vix", "VIXCLS", "us_vix")
    _stitch_us_daily("hy_oas", "BAMLH0A0HYM2", "us_hy_oas")
    panel["us_t10y2y"] = panel["us_dgs10"] - panel["us_dgs2"]

    # Broad DXY (DTWEXBGS 2006-01 ~ 2026-11-20) + ICE DXY (close_dxy 1990 ~ 2026-11-09)
    dtwex = _load_fred_series("DTWEXBGS").rename(columns={"value": "us_dxy_broad"})
    if not dtwex.empty:
        dtwex["available_date"] = dtwex["obs_date"].map(strictly_after)
        panel["us_dxy_broad"] = pit_asof_join(panel[["date"]], dtwex, "available_date", ["us_dxy_broad"], max_staleness_days=15)["us_dxy_broad"].values
    ice_dxy = us_pit[["obs_date", "close_dxy"]].rename(columns={"close_dxy": "us_dxy_ice"}).dropna()
    ice_dxy["available_date"] = ice_dxy["obs_date"].map(strictly_after)
    panel["us_dxy_ice"] = pit_asof_join(panel[["date"]], ice_dxy, "available_date", ["us_dxy_ice"], max_staleness_days=25)["us_dxy_ice"].values

    # NFCI (ALFRED up to 2026-11-09 + FRED NFCI up to 2026-11-13 with +5d lag)
    nfci1 = us_pit[["obs_date", "nfci_pit"]].rename(columns={"nfci_pit": "us_nfci"}).dropna()
    nfci1["available_date"] = nfci1["obs_date"].map(strictly_after)
    nfci2 = _load_fred_series("NFCI").rename(columns={"value": "us_nfci"})
    nfci2 = nfci2[nfci2["obs_date"] > nfci1["obs_date"].max()].copy()
    nfci2["available_date"] = (nfci2["obs_date"] + pd.Timedelta(days=5)).map(on_or_after)
    nfci_all = pd.concat([nfci1[["available_date", "us_nfci"]], nfci2[["available_date", "us_nfci"]]], ignore_index=True)
    panel["us_nfci"] = pit_asof_join(panel[["date"]], nfci_all, "available_date", ["us_nfci"], max_staleness_days=25)["us_nfci"].values

    # Fed Balance Sheet & Net Liquidity (WALCL million -> billion, WTREGEN million -> billion, RRPONTSYD billion)
    walcl = _load_fred_series("WALCL").rename(columns={"value": "walcl_m"})
    tga = _load_fred_series("WTREGEN").rename(columns={"value": "tga_m"})
    rrp = _load_fred_series("RRPONTSYD").rename(columns={"value": "rrp_b"})
    if not walcl.empty:
        walcl["us_fed_assets_bn"] = walcl["walcl_m"] / 1000.0
        walcl["us_fed_assets_yoy"] = (walcl["us_fed_assets_bn"] / walcl["us_fed_assets_bn"].shift(52) - 1.0) * 100.0
        walcl["available_date"] = (walcl["obs_date"] + pd.Timedelta(days=2)).map(on_or_after)
        m_w = pit_asof_join(panel[["date"]], walcl, "available_date", ["us_fed_assets_bn", "us_fed_assets_yoy"], max_staleness_days=20)
        panel["us_fed_assets_bn"] = m_w["us_fed_assets_bn"].values
        panel["us_fed_assets_yoy"] = m_w["us_fed_assets_yoy"].values
    if not tga.empty:
        tga["us_tga_bn"] = tga["tga_m"] / 1000.0
        tga["available_date"] = (tga["obs_date"] + pd.Timedelta(days=2)).map(on_or_after)
        panel["us_tga_bn"] = pit_asof_join(panel[["date"]], tga, "available_date", ["us_tga_bn"], max_staleness_days=20)["us_tga_bn"].values
    if not rrp.empty:
        rrp["us_rrp_bn"] = rrp["rrp_b"]
        rrp["available_date"] = rrp["obs_date"].map(strictly_after)
        rrp_daily = rrp[rrp["obs_date"] >= pd.Timestamp("2013-09-23")].copy()
        panel["us_rrp_bn"] = pit_asof_join(panel[["date"]], rrp_daily, "available_date", ["us_rrp_bn"], max_staleness_days=15)["us_rrp_bn"].values
    if {"us_fed_assets_bn", "us_tga_bn", "us_rrp_bn"}.issubset(panel.columns):
        panel["us_net_liquidity_bn"] = panel["us_fed_assets_bn"] - panel["us_tga_bn"] - panel["us_rrp_bn"].fillna(0.0)

    # US M2 YoY (ALFRED up to 2026-11-09, M2SL monthly PIT)
    us_m2 = us_pit[["obs_date", "m2_yoy_pit"]].rename(columns={"m2_yoy_pit": "us_m2_yoy"}).dropna()
    us_m2["available_date"] = us_m2["obs_date"].map(strictly_after)
    panel["us_m2_yoy"] = pit_asof_join(panel[["date"]], us_m2, "available_date", ["us_m2_yoy"], max_staleness_days=30)["us_m2_yoy"].values

    # 6. Cross-Border Constraints & Pain Spreads
    panel["cn_us_10y_spread_bp"] = (panel["cn_bond_10y"] - panel["us_dgs10"]) * 100.0
    panel["cn_us_2y_spread_bp"] = (panel["cn_bond_2y"] - panel["us_dgs2"]) * 100.0
    panel["cn_real_rate_cpi"] = panel["cn_bond_10y"] - panel["cn_cpi_yoy"]
    panel["cn_corp_real_rate_ppi"] = panel["cn_policy_rate_1y"] - panel["cn_ppi_yoy"]

    # 7. Daily changes (20d/60d/250d) & Causal 3Y/5Y Rolling Percentiles (using 2000-2004 warmup!)
    daily_chg_cols = [
        "cn_bond_10y", "cn_bond_2y", "us_dgs10", "us_dgs2", "usdcny",
        "cn_us_10y_spread_bp", "cn_us_2y_spread_bp", "us_dxy_broad", "us_vix", "us_baa10y",
    ]
    for c in daily_chg_cols:
        if c in panel.columns:
            panel[f"{c}_chg_20d"] = panel[c] - panel[c].shift(20)
            panel[f"{c}_chg_60d"] = panel[c] - panel[c].shift(60)
            panel[f"{c}_chg_250d"] = panel[c] - panel[c].shift(250)

    pct_cols = [
        "cn_m1_yoy", "cn_m2_yoy", "cn_m1_m2_diff", "cn_new_loan_yoy", "cn_tsf_yi",
        "cn_pmi_mfg", "cn_cpi_yoy", "cn_ppi_yoy", "cn_ppi_minus_cpi",
        "cn_ind_prod_yoy", "cn_retail_sales_yoy", "cn_fai_yoy", "cn_real_estate_climate",
        "cn_exports_yoy", "cn_fiscal_rev_yoy", "cn_bond_10y", "cn_bond_2y",
        "cn_us_10y_spread_bp", "cn_us_2y_spread_bp", "cn_real_rate_cpi", "cn_corp_real_rate_ppi",
        "usdcny", "us_dgs10", "us_dff", "us_dfii10", "us_dxy_broad", "us_baa10y", "us_vix", "us_nfci", "us_net_liquidity_bn",
    ]
    print("  Computing 3Y/5Y causal rolling percentiles...")
    for c in pct_cols:
        if c in panel.columns:
            panel[f"{c}_pct_3y"] = causal_rolling_pct(panel[c], window=726, min_periods=242)
            panel[f"{c}_pct_5y"] = causal_rolling_pct(panel[c], window=1210, min_periods=242)

    out = panel[panel["date"] >= pd.Timestamp("2005-01-01")].sort_values("date").reset_index(drop=True)
    return out
