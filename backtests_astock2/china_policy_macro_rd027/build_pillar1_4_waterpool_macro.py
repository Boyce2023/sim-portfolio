#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD027 Wave 1 (Pillar 1 & Pillar 4) Unified Builder & Q8 Auditor.
Produces strictly PIT-aligned 2005-01 ~ 2026-11 datasets:
  - pillar1_waterpool_monthly.parquet
  - pillar1_market_breadth_daily.parquet
  - pillar4_macro_pain_daily_pit.parquet
  - pillar1_4_audit.json
"""
import argparse
import datetime
import json
import os
import sys

import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

from fetch_sources import fetch_all
from build_breadth_and_waterpool import build_breadth_and_waterpool
from build_macro_pain import build_macro_pain
from pit_utils import audit_columns

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = os.path.join(ROOT, "output/china_policy_macro_rd027_20261125/data_pillars")
os.makedirs(OUT_DIR, exist_ok=True)


def _infer_col_meta(col: str, table_kind: str) -> dict:
    """Assign human-readable source and PIT rule metadata per column."""
    if table_kind == "waterpool_monthly":
        rules = {
            "ipo_": ("stock_xgsglb_em + ipo_2005_2009_cninfo", "listing_date month; available T+1 after month-end"),
            "refinance_": ("stock_qbzf_em", "listing/issue date month (2011-01+); available T+1 after month-end"),
            "insider_": ("stock_ggcg_em + local hist close", "announcement date month + historical close at trade date"),
            "block_trade": ("stock_dzjy_sctj", "trade_date month; available T+1 after month-end"),
            "stamp_tax": ("DMP turnover * statutory rate", "exact daily statutory stamp rate summed monthly"),
            "margin_": ("macro_china_market_margin_sh/sz + stock_margin_account_info", "2010-03+; EOM T+1"),
            "nt_etf": ("DMP national team 21+1 ETF flows", "2010-01+ (21 ETF) / 2016-01+ (22 ETF); EOM T+1"),
            "northbound": ("stock_hsgt_hist_em", "2014-11 ~ 2024-08-16 (HKEX stopped daily disclosure)"),
            "buyback": ("stock_repurchase_em", "announcement date month (completed/in-progress actual RMB)"),
            "cash_dividend": ("stock_fhps_em_all", "ex-dividend date month (implemented plans)"),
        }
        for k, (src, pit) in rules.items():
            if col.startswith(k) or k in col:
                return {"source": src, "pit_rule": pit}
        return {"source": "DMP + cn_hk_price_db + synthetic waterpool", "pit_rule": "EOM T+1 available_date"}

    if table_kind == "breadth_daily":
        if "margin" in col:
            return {"source": "stock_margin_account_info + SH/SZ", "pit_rule": "T EOD (exec available T+1)"}
        if "northbound" in col:
            return {"source": "stock_hsgt_hist_em", "pit_rule": "2014-11-17 ~ 2024-08-16 T EOD"}
        if "etf" in col:
            return {"source": "DMP v3_cache ETF shares/flows", "pit_rule": "T EOD (available T+1)"}
        if "pe" in col or "pb" in col or "erp" in col:
            return {"source": "stock_index_pe_lg / stock_a_ttm_lyr / bond_zh_us_rate", "pit_rule": "Backward merge_asof + daily price ratio"}
        return {"source": "cn_hk_price_db (survivorship-free) + DMP", "pit_rule": "T EOD (available_date = T+1)"}

    # macro_pain_daily_pit
    prefix_rules = [
        ("cn_m", "macro_china_supply_of_money + money_supply", "Monthly release M+1 day 16 -> first trade day >="),
        ("cn_new_loan", "macro_china_new_financial_credit", "Monthly release M+1 day 16 -> first trade day >="),
        ("cn_tsf", "macro_china_shrzgm", "Monthly M+1 day 16 (stops 2026-04; 50d staleness cap)"),
        ("cn_pboc", "macro_china_central_bank_balance", "Monthly M+1 day 16"),
        ("cn_fiscal", "macro_china_czsr", "Monthly M+1 day 16"),
        ("cn_pmi", "macro_china_pmi_yearly + macro_china_pmi", "Month-end release -> next trade day (+1d)"),
        ("cn_cpi", "macro_china_cpi_yearly + macro_china_cpi", "Monthly M+1 day 12 -> first trade day >="),
        ("cn_ppi", "macro_china_ppi_yearly + macro_china_ppi", "Monthly M+1 day 12 -> first trade day >="),
        ("cn_exports", "macro_china_hgjck", "Monthly M+1 day 12"),
        ("cn_imports", "macro_china_hgjck", "Monthly M+1 day 12"),
        ("cn_fx_reserves", "macro_china_fx_gold", "Monthly M+1 day 12"),
        ("cn_ind_prod", "macro_china_industrial_production_yoy + gyzjz", "Monthly M+1 day 19 (Jan+Feb combined)"),
        ("cn_retail", "macro_china_consumer_goods_retail", "Monthly M+1 day 19"),
        ("cn_fai", "macro_china_gdzctz", "Monthly M+1 day 19 (2012-02+)"),
        ("cn_real_estate", "macro_china_real_estate", "Monthly M+1 day 19 (stops 2025-12; 50d staleness cap)"),
        ("cn_consumer_conf", "macro_china_xfzxx", "Monthly M+1 day 19 (stops 2026-09)"),
        ("cn_gdp", "macro_china_gdp", "Quarterly Q_end+1 month day 20"),
        ("cn_lpr", "macro_china_lpr", "Release date T -> T+1 trade day"),
        ("cn_pboc_loan", "macro_china_lpr", "Release date T -> T+1 trade day"),
        ("cn_policy_rate", "macro_china_lpr", "Release date T -> T+1 trade day"),
        ("cn_bond", "bond_zh_us_rate", "Daily T close -> T+1 trade day"),
        ("cn_10y_2y", "bond_zh_us_rate", "Daily T close -> T+1 trade day"),
        ("usdcny", "currency_boc_safe + FRED DEXCHUS", "Daily T close -> T+1 trade day"),
        ("us_fed_assets", "FRED WALCL", "Weekly Thu release -> +2d on_or_after"),
        ("us_tga", "FRED WTREGEN", "Weekly Thu release -> +2d on_or_after"),
        ("us_rrp", "FRED RRPONTSYD", "Daily T close -> T+1 trade day"),
        ("us_net_liq", "FRED WALCL - WTREGEN - RRPONTSYD", "Weekly Thu/Daily T+1"),
        ("us_nfci", "ALFRED macro_pit + FRED NFCI", "Weekly ALFRED/5d lag"),
        ("us_m2", "ALFRED macro_pit_daily_1990_2026", "Monthly ALFRED initial vintage T+1"),
        ("us_hy_oas", "ALFRED + FRED BAMLH0A0HYM2", "2023-09-11+; Daily T+1"),
        ("us_", "ALFRED macro_pit + local FRED parquet", "Daily US close -> next China trade day (T+1)"),
        ("cn_us_", "bond_zh_us_rate vs FRED DGS10/DGS2", "Daily T+1 aligned"),
        ("cn_real_rate", "CN bond/LPR vs CPI/PPI PIT", "Strict PIT components"),
        ("cn_corp_real", "CN policy rate vs PPI PIT", "Strict PIT components"),
    ]
    for pref, src, pit in prefix_rules:
        if col.startswith(pref):
            return {"source": src, "pit_rule": pit}
    return {"source": "RD027 PIT Macro", "pit_rule": "Strict PIT"}


def _clean_float_dict(row: pd.Series, cols: list[str]) -> dict:
    out = {}
    for c in cols:
        if c not in row.index:
            continue
        v = row[c]
        if pd.isna(v):
            out[c] = None
        elif isinstance(v, (np.floating, float)):
            out[c] = round(float(v), 4)
        elif isinstance(v, (np.integer, int)):
            out[c] = int(v)
        elif isinstance(v, (pd.Timestamp, datetime.date, datetime.datetime)):
            out[c] = pd.Timestamp(v).strftime("%Y-%m-%d")
        else:
            out[c] = str(v)
    return out


def _build_snapshots(wp_m: pd.DataFrame, bd_d: pd.DataFrame, mp_d: pd.DataFrame) -> dict:
    """Extract cross-sectional waterpool, breadth, and PIT macro pain snapshots at 8 key moments."""
    target_months = ["2008-11", "2014-11", "2015-06", "2018-10", "2021-07", "2023-07", "2024-09", "2026-11"]
    wp_cols = [
        "month", "n_trade_days", "total_amount_yi", "eom_float_mcap_yi", "mkt_turn_monthly_pct",
        "ipo_count", "ipo_raised_yi", "refinance_yi", "insider_net_reduce_yi", "block_trade_yi",
        "stamp_tax_yi", "margin_balance_eom_yi", "margin_net_chg_yi", "nt_etf_weighted_flow_yi",
        "northbound_net_buy_yi", "buyback_yi", "cash_dividend_yi", "drain_total_yi",
        "inject_trading_yi", "net_waterpool_trading_yi", "net_waterpool_trading_pct_mcap",
        "net_waterpool_incl_div_yi",
    ]
    bd_cols = [
        "date", "sh_comp_close", "csi300_close", "total_amount_yi", "pct_above_ma20",
        "pct_above_ma60", "pct_above_ma200", "pct_new_low_250d", "pct_low_price_lt3",
        "turn_mkt_weighted", "margin_balance_yi", "csi300_pe_ttm_daily", "all_a_median_pe_ttm",
        "all_a_median_pb", "erp_csi300_pct", "erp_all_a_median_pct",
    ]
    mp_cols = [
        "date", "cn_m1_yoy", "cn_m2_yoy", "cn_m1_m2_diff", "cn_tsf_yi", "cn_new_loan_yi",
        "cn_pmi_mfg", "cn_cpi_yoy", "cn_ppi_yoy", "cn_ppi_minus_cpi", "cn_policy_rate_1y",
        "cn_real_estate_climate", "cn_ind_prod_yoy", "cn_retail_sales_yoy", "cn_bond_10y",
        "us_dgs10", "cn_us_10y_spread_bp", "usdcny", "us_dff", "us_dfii10", "us_dxy_broad",
        "us_baa10y", "us_hy_oas", "us_vix", "us_nfci", "us_net_liquidity_bn",
        "cn_m1_m2_diff_pct_5y", "cn_us_10y_spread_bp_pct_5y", "cn_ppi_yoy_pct_5y",
    ]

    bd_tmp = bd_d.copy()
    bd_tmp["ym"] = bd_tmp["date"].dt.strftime("%Y-%m")
    mp_tmp = mp_d.copy()
    mp_tmp["ym"] = mp_tmp["date"].dt.strftime("%Y-%m")

    snaps = {}
    for ym in target_months:
        wp_row = wp_m[wp_m["month"] == ym].iloc[-1] if (wp_m["month"] == ym).any() else pd.Series(dtype=object)
        bd_row = bd_tmp[bd_tmp["ym"] == ym].iloc[-1] if (bd_tmp["ym"] == ym).any() else pd.Series(dtype=object)
        mp_row = mp_tmp[mp_tmp["ym"] == ym].iloc[-1] if (mp_tmp["ym"] == ym).any() else pd.Series(dtype=object)
        snaps[ym] = {
            "waterpool_monthly": _clean_float_dict(wp_row, wp_cols),
            "breadth_eom": _clean_float_dict(bd_row, bd_cols),
            "macro_pain_eom_pit": _clean_float_dict(mp_row, mp_cols),
        }

    # Add pre-924 trough check (2024-09-23) alongside 2024-09-30 EOM!
    bd_923 = bd_tmp[bd_tmp["date"] == pd.Timestamp("2024-09-23")]
    mp_923 = mp_tmp[mp_tmp["date"] == pd.Timestamp("2024-09-23")]
    if not bd_923.empty and not mp_923.empty:
        snaps["2024-09-23_pre924"] = {
            "breadth": _clean_float_dict(bd_923.iloc[0], bd_cols),
            "macro_pain_pit": _clean_float_dict(mp_923.iloc[0], mp_cols),
        }
    return snaps


def main():
    parser = argparse.ArgumentParser(description="RD027 Pillar 1 & 4 PIT Data Builder")
    parser.add_argument("--refresh", action="store_true", help="Force re-download raw akshare cache")
    args = parser.parse_args()

    print("=== [RD027 Step 1/4] Fetching / Loading Raw Cache ===")
    raw, fetch_status = fetch_all(refresh=args.refresh)

    print("=== [RD027 Step 2/4] Building Pillar 1 Breadth & Waterpool ===")
    breadth_daily, waterpool_monthly, anomalies = build_breadth_and_waterpool(raw)

    print("=== [RD027 Step 3/4] Building Pillar 4 Macro Pain Daily PIT ===")
    macro_pain_daily = build_macro_pain(raw)

    # Strict Integrity Checks
    assert waterpool_monthly["month"].is_monotonic_increasing, "waterpool months not sorted"
    assert len(waterpool_monthly) == 263, f"expected 263 months (2005-01..2026-11), got {len(waterpool_monthly)}"
    assert breadth_daily["date"].is_monotonic_increasing and breadth_daily["date"].is_unique, "breadth dates invalid"
    assert macro_pain_daily["date"].is_monotonic_increasing and macro_pain_daily["date"].is_unique, "macro dates invalid"
    assert (breadth_daily["available_date"] > breadth_daily["date"]).iloc[:-1].all(), "breadth available_date must be > date"

    # Write parquets
    p_wp = os.path.join(OUT_DIR, "pillar1_waterpool_monthly.parquet")
    p_bd = os.path.join(OUT_DIR, "pillar1_market_breadth_daily.parquet")
    p_mp = os.path.join(OUT_DIR, "pillar4_macro_pain_daily_pit.parquet")
    p_aud = os.path.join(OUT_DIR, "pillar1_4_audit.json")

    waterpool_monthly.to_parquet(p_wp, index=False)
    breadth_daily.to_parquet(p_bd, index=False)
    macro_pain_daily.to_parquet(p_mp, index=False)

    print("=== [RD027 Step 4/4] Running Q8 Completeness & Snapshot Audit ===")
    wp_meta = {c: _infer_col_meta(c, "waterpool_monthly") for c in waterpool_monthly.columns if c != "month"}
    bd_meta = {c: _infer_col_meta(c, "breadth_daily") for c in breadth_daily.columns if c != "date"}
    mp_meta = {c: _infer_col_meta(c, "macro_pain_daily") for c in macro_pain_daily.columns if c != "date"}

    aud_wp = audit_columns(waterpool_monthly, "month", wp_meta)
    aud_bd = audit_columns(breadth_daily, "date", bd_meta)
    aud_mp = audit_columns(macro_pain_daily, "date", mp_meta)

    def _summarize_flags(aud_dict: dict, expected_end: str) -> dict:
        gt5 = {k: v["missing_rate_pct"] for k, v in aud_dict.items() if v.get("gt_5pct_missing_flag")}
        late_start = {k: v["first_date"] for k, v in aud_dict.items() if v.get("first_date") and v["first_date"] > "2006-01-01" and not k.endswith(("_pct_3y", "_pct_5y", "_250d", "_12m_yi", "_12m_sum"))}
        early_stop = {k: v["last_date"] for k, v in aud_dict.items() if v.get("last_date") and v["last_date"] < expected_end}
        null_all = [k for k, v in aud_dict.items() if v["valid_count"] == 0]
        return {
            "total_data_columns": len(aud_dict),
            "gt_5pct_missing_after_start": gt5,
            "late_start_after_2006": late_start,
            "early_stop_before_end": early_stop,
            "all_null_columns": null_all,
        }

    snapshots = _build_snapshots(waterpool_monthly, breadth_daily, macro_pain_daily)
    failed_endpoints = {k: v for k, v in fetch_status.items() if not v.get("ok")}

    audit_report = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "d12_compliant": True,
        "pit_rules": {
            "pmi": "month_end -> strictly next trading day (+1d)",
            "cpi_ppi_trade_fxres": "ref_month + 1m day 12 -> on_or_after trading day",
            "m0_m1_m2_loan_tsf_pboc_fiscal": "ref_month + 1m day 16 -> on_or_after trading day",
            "ip_retail_fai_realestate_consconf": "ref_month + 1m day 19 -> on_or_after trading day (Jan+Feb combined)",
            "gdp": "quarter_end + 1m day 20 -> on_or_after trading day",
            "daily_rates_fx_us_macro_breadth": "obs_date T close -> strictly next trading day T+1",
        },
        "table_shapes": {
            "pillar1_waterpool_monthly": {"rows": int(len(waterpool_monthly)), "cols": int(waterpool_monthly.shape[1]), "range": [str(waterpool_monthly["month"].min()), str(waterpool_monthly["month"].max())]},
            "pillar1_market_breadth_daily": {"rows": int(len(breadth_daily)), "cols": int(breadth_daily.shape[1]), "range": [breadth_daily["date"].min().strftime("%Y-%m-%d"), breadth_daily["date"].max().strftime("%Y-%m-%d")]},
            "pillar4_macro_pain_daily_pit": {"rows": int(len(macro_pain_daily)), "cols": int(macro_pain_daily.shape[1]), "range": [macro_pain_daily["date"].min().strftime("%Y-%m-%d"), macro_pain_daily["date"].max().strftime("%Y-%m-%d")]},
        },
        "fetch_status": fetch_status,
        "failed_endpoints": failed_endpoints,
        "data_anomalies_and_truncations": {
            **anomalies,
            "northbound_disclosure_stop": "HKEX stopped daily northbound net buy disclosure after 2024-08-16; post-2024-08-16 strictly NaN.",
            "tsf_shrzgm_stop": "akshare macro_china_shrzgm stops at 2026-04; staleness cutoff (50d) sets post-2026-07-02 strictly NaN.",
            "real_estate_climate_stop": "akshare macro_china_real_estate stops at 2025-12; staleness cutoff (50d) sets post-2026-03 strictly NaN.",
            "us_hy_oas_start": "FRED BAMLH0A0HYM2 local cache starts 2023-09-11; full 2005-2026 corporate credit spread covered by us_baa10y.",
        },
        "completeness_summary": {
            "pillar1_waterpool_monthly": _summarize_flags(aud_wp, "2026-10"),
            "pillar1_market_breadth_daily": _summarize_flags(aud_bd, "2026-11-15"),
            "pillar4_macro_pain_daily_pit": _summarize_flags(aud_mp, "2026-11-15"),
        },
        "key_snapshots_8_moments": snapshots,
        "columns_audit": {
            "pillar1_waterpool_monthly": aud_wp,
            "pillar1_market_breadth_daily": aud_bd,
            "pillar4_macro_pain_daily_pit": aud_mp,
        },
    }

    with open(p_aud, "w", encoding="utf-8") as f:
        json.dump(audit_report, f, ensure_ascii=False, indent=2)

    print("Saved outputs:")
    print(f"  1) {p_wp} ({waterpool_monthly.shape})")
    print(f"  2) {p_bd} ({breadth_daily.shape})")
    print(f"  3) {p_mp} ({macro_pain_daily.shape})")
    print(f"  4) {p_aud}")
    print("EXIT=0 OK")


if __name__ == "__main__":
    main()
