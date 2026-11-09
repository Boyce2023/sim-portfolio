"""
W1_03 SEC XBRL Point-in-Time (PIT) Panel Extractor - Shard 0
Author: OHIM Research (W1_03 Subagent)
Date: 2026-11-09

Core Guarantees:
1. 100% Zero Lookahead Bias (Strict Point-in-Time):
   - Only reads form in {'10-Q', '10-K', '10-Q/A', '10-K/A'}
   - Enforces 0 < (filed - end).days <= 130 on every single source filing record.
   - For identical period (end, dur_type), takes strictly the earliest filed date and first reported value.
2. Full Tag Coverage with Synonym Cascades:
   - rev, gp (with rev - cor fallback), cor, opinc (with EBT fallback & flag), ni, rd, sga, sbc, ocf, capex
   - Balance sheet: assets, cash, equity, debt_lt, debt_st, total_debt, shares
3. Q4 Imputation:
   - FY - (Q1 + Q2 + Q3) with filed = FY.filed, 100% PIT compliant.
4. Trajectory and Inflection Metrics:
   - TTM sums (rev, gp, opinc, ni, ocf, capex, fcf, sbc)
   - Margins: gm_q, opm_q, nm_q, rd_ratio_q, sga_ratio_q, gm_minus_sga_q (NTRA commercialization metric), fcf_margin_ttm, ocf_to_ni_ttm
   - Capital returns: neg_equity, roe_ttm, invested_cap, roic_ttm
   - YoY growth & changes: rev_yoy, gp_yoy, opinc_yoy, ni_yoy, gm_yoy_chg, opm_yoy_chg, gm_sga_yoy_chg, roic_yoy_chg, shares_yoy_dilution
   - Inflection counters: rev_accel_1q, consec_rev_accel_n, consec_opm_expand_n, consec_gm_sga_expand_n, consec_double_inflect_n, turnaround_to_profit_1q
"""

import os
import sys
import json
import time
import zipfile
from datetime import datetime
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Paths
SHARD_FILE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/shards/xbrl_shard_0.json"
ZIP_CANDIDATES = [
    "/tmp/us_xuangu_20261109/w1_a3/companyfacts.zip",
    "/tmp/us_earn_macro_bt_20261109/companyfacts.zip"
]
OUT_DIR = "/tmp/us_earn_macro_bt_20261109/sec_xbrl_shards"
OUT_PARQUET = os.path.join(OUT_DIR, "xbrl_pit_shard_0.parquet")

VALID_FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}

# Flow Tag Dictionaries (in strict priority order)
REV_TAGS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "RevenuesNetOfInterestExpense",
    "InterestAndDividendIncomeOperating",
    "TotalRevenuesAndOtherIncome",
    "HealthCareOrganizationRevenue",
    "RealEstateRevenueNet",
    "ElectricUtilityRevenue",
    "RegulatedAndUnregulatedOperatingRevenue"
]

GP_TAGS = ["GrossProfit"]

COR_TAGS = [
    "CostOfGoodsAndServicesSold",
    "CostOfRevenue",
    "CostOfGoodsSold",
    "CostOfServices"
]

OPINC_PRIMARY_TAGS = ["OperatingIncomeLoss"]
OPINC_SECONDARY_TAGS = [
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"
]

NI_TAGS = [
    "NetIncomeLoss",
    "ProfitLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic"
]

RD_TAGS = [
    "ResearchAndDevelopmentExpense",
    "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"
]

SGA_MAIN_TAGS = ["SellingGeneralAndAdministrativeExpense"]
SGA_GA_TAGS = ["GeneralAndAdministrativeExpense"]
SGA_SM_TAGS = [
    "SellingAndMarketingExpense",
    "MarketingAndAdvertisingExpense",
    "SellingExpense"
]

SBC_TAGS = [
    "ShareBasedCompensation",
    "AllocatedShareBasedCompensationExpense"
]

OCF_TAGS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"
]

CAPEX_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets"
]

# Stock / Balance Sheet Tags (instant)
ASSETS_TAGS = ["Assets"]
CASH_TAGS = [
    "CashCashEquivalentsAndShortTermInvestments",
    "CashAndCashEquivalentsAtCarryingValue"
]
EQUITY_TAGS = [
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
]
DEBT_LT_TAGS = [
    "LongTermDebtNoncurrent",
    "LongTermDebt",
    "LongTermDebtAndCapitalLeaseObligations"
]
DEBT_ST_TAGS = [
    "ShortTermBorrowings",
    "LongTermDebtCurrent",
    "DebtCurrent"
]

SHARES_DUR_TAGS = [
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic"
]
SHARES_INST_USGAAP = ["CommonStockSharesOutstanding"]
SHARES_INST_DEI = ["EntityCommonStockSharesOutstanding"]


def parse_date(s):
    if not s or len(s) < 10:
        return None
    try:
        return datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except Exception:
        return None


def get_dur_type(dur_days):
    """
    Returns duration type:
    1: Single Quarter (68 to 112 days)
    2: 6-Month YTD (165 to 200 days)
    3: 9-Month YTD (255 to 295 days)
    4: Full Year (345 to 385 days)
    None: Non-standard
    """
    if 68 <= dur_days <= 112:
        return 1
    elif 165 <= dur_days <= 200:
        return 2
    elif 255 <= dur_days <= 295:
        return 3
    elif 345 <= dur_days <= 385:
        return 4
    return None


def extract_flow_metric_records(us_gaap, tag_list):
    """
    Extracts flow records for a metric.
    Enforces form validity and 0 < lag <= 130.
    Returns dict: (end_str, dur_type) -> (d_filed, is_amend, tag_prio, val, filed_str, form_str, fy, fp)
    Picks earliest filed date, breaking ties with non-amended and highest tag priority.
    """
    best = {}
    for prio, tag in enumerate(tag_list):
        node = us_gaap.get(tag)
        if not node:
            continue
        arr = node.get("units", {}).get("USD", [])
        if not arr:
            continue
        for it in arr:
            form = it.get("form", "")
            if form not in VALID_FORMS:
                continue
            s_str = it.get("start")
            e_str = it.get("end")
            f_str = it.get("filed")
            val = it.get("val")
            if not (s_str and e_str and f_str and val is not None):
                continue
            d_s = parse_date(s_str)
            d_e = parse_date(e_str)
            d_f = parse_date(f_str)
            if not (d_s and d_e and d_f):
                continue
            
            # Anti-lookahead PIT filter: 0 < lag <= 130
            lag = (d_f - d_e).days
            if not (0 < lag <= 130):
                continue
            
            dur = (d_e - d_s).days
            dtype = get_dur_type(dur)
            if dtype is None:
                continue
            
            is_amend = 1 if "/A" in form else 0
            key = (e_str, dtype)
            # Candidate: (d_filed, is_amend, prio) -> lowest wins
            cand_sort_key = (d_f, is_amend, prio)
            cand_val = (d_f, is_amend, prio, float(val), f_str, form, it.get("fy"), it.get("fp"))
            
            if key not in best:
                best[key] = (cand_sort_key, cand_val)
            else:
                if cand_sort_key < best[key][0]:
                    best[key] = (cand_sort_key, cand_val)
                    
    # Return mapping: (end_str, dur_type) -> (val, filed_str, form_str, fy, fp, d_f)
    result = {}
    for k, (_, v) in best.items():
        result[k] = (v[3], v[4], v[5], v[6], v[7], v[0])
    return result


def extract_instant_metric_records(facts, tag_list, source="us-gaap", unit="USD"):
    """
    Extracts instant (balance sheet / stock) records.
    Returns dict: end_str -> (val, filed_str, form_str, d_f)
    """
    container = facts.get(source, {})
    best = {}
    for prio, tag in enumerate(tag_list):
        node = container.get(tag)
        if not node:
            continue
        arr = node.get("units", {}).get(unit, [])
        if not arr:
            continue
        for it in arr:
            form = it.get("form", "")
            if form not in VALID_FORMS:
                continue
            e_str = it.get("end")
            f_str = it.get("filed")
            val = it.get("val")
            if not (e_str and f_str and val is not None):
                continue
            d_e = parse_date(e_str)
            d_f = parse_date(f_str)
            if not (d_e and d_f):
                continue
            
            lag = (d_f - d_e).days
            if not (0 < lag <= 130):
                continue
            
            is_amend = 1 if "/A" in form else 0
            cand_sort_key = (d_f, is_amend, prio)
            cand_val = (float(val), f_str, form, d_f)
            
            if e_str not in best:
                best[e_str] = (cand_sort_key, cand_val)
            else:
                if cand_sort_key < best[e_str][0]:
                    best[e_str] = (cand_sort_key, cand_val)
                    
    result = {}
    for k, (_, v) in best.items():
        result[k] = v
    return result


def extract_shares_records(facts):
    """
    Extracts share count records with priority:
    1. Duration-matched diluted shares (dur_type 1 or 4)
    2. Duration-matched basic shares (dur_type 1 or 4)
    3. Instant CommonStockSharesOutstanding (us-gaap)
    4. Instant EntityCommonStockSharesOutstanding (dei)
    Returns:
      dur_shares: dict (end_str, dur_type) -> (shares, filed_str, form_str, d_f)
      inst_shares: dict end_str -> (shares, filed_str, form_str, d_f)
    """
    us_gaap = facts.get("us-gaap", {})
    dei = facts.get("dei", {})
    
    dur_shares = {}
    for prio, tag in enumerate(SHARES_DUR_TAGS):
        node = us_gaap.get(tag)
        if not node:
            continue
        arr = node.get("units", {}).get("shares", [])
        for it in arr:
            form = it.get("form", "")
            if form not in VALID_FORMS:
                continue
            s_str = it.get("start")
            e_str = it.get("end")
            f_str = it.get("filed")
            val = it.get("val")
            if not (s_str and e_str and f_str and val and float(val) > 0):
                continue
            d_s = parse_date(s_str)
            d_e = parse_date(e_str)
            d_f = parse_date(f_str)
            if not (d_s and d_e and d_f):
                continue
            lag = (d_f - d_e).days
            if not (0 < lag <= 130):
                continue
            dur = (d_e - d_s).days
            dtype = get_dur_type(dur)
            if dtype is None:
                continue
            is_amend = 1 if "/A" in form else 0
            cand_key = (d_f, is_amend, prio)
            cand_val = (float(val), f_str, form, d_f)
            key = (e_str, dtype)
            if key not in dur_shares or cand_key < dur_shares[key][0]:
                dur_shares[key] = (cand_key, cand_val)
                
    dur_res = {k: v[1] for k, v in dur_shares.items()}
    
    # Instant shares
    inst_res = extract_instant_metric_records(facts, SHARES_INST_USGAAP, source="us-gaap", unit="shares")
    dei_res = extract_instant_metric_records(facts, SHARES_INST_DEI, source="dei", unit="shares")
    # Merge DEI where us-gaap is missing
    for e_str, v in dei_res.items():
        if e_str not in inst_res:
            inst_res[e_str] = v
            
    return dur_res, inst_res


def process_company_xbrl(cik, ticker, company_name, facts_json_bytes):
    """
    Parses a single company XBRL JSON facts, extracts Point-in-Time financial panel,
    and returns list of enriched quarterly dict rows.
    """
    try:
        data = json.loads(facts_json_bytes.decode("utf-8", errors="ignore"))
    except Exception:
        return []
    
    facts = data.get("facts", {})
    us_gaap = facts.get("us-gaap", {})
    if not us_gaap:
        return []
    
    # Extract flow metrics: (end_str, dur_type) -> (val, filed_str, form_str, fy, fp, d_f)
    rev_raw = extract_flow_metric_records(us_gaap, REV_TAGS)
    gp_raw = extract_flow_metric_records(us_gaap, GP_TAGS)
    cor_raw = extract_flow_metric_records(us_gaap, COR_TAGS)
    opinc_p_raw = extract_flow_metric_records(us_gaap, OPINC_PRIMARY_TAGS)
    opinc_s_raw = extract_flow_metric_records(us_gaap, OPINC_SECONDARY_TAGS)
    ni_raw = extract_flow_metric_records(us_gaap, NI_TAGS)
    rd_raw = extract_flow_metric_records(us_gaap, RD_TAGS)
    sga_m_raw = extract_flow_metric_records(us_gaap, SGA_MAIN_TAGS)
    sga_ga_raw = extract_flow_metric_records(us_gaap, SGA_GA_TAGS)
    sga_sm_raw = extract_flow_metric_records(us_gaap, SGA_SM_TAGS)
    sbc_raw = extract_flow_metric_records(us_gaap, SBC_TAGS)
    ocf_raw = extract_flow_metric_records(us_gaap, OCF_TAGS)
    capex_raw = extract_flow_metric_records(us_gaap, CAPEX_TAGS)
    
    # Balance sheet metrics: end_str -> (val, filed_str, form_str, d_f)
    assets_raw = extract_instant_metric_records(facts, ASSETS_TAGS)
    cash_raw = extract_instant_metric_records(facts, CASH_TAGS)
    equity_raw = extract_instant_metric_records(facts, EQUITY_TAGS)
    debt_lt_raw = extract_instant_metric_records(facts, DEBT_LT_TAGS)
    debt_st_raw = extract_instant_metric_records(facts, DEBT_ST_TAGS)
    dur_shares, inst_shares = extract_shares_records(facts)
    
    # Determine all candidate period ends
    # A quarter can come from 1Q flow record, or FY flow record, or balance sheet record
    all_q_ends = set()
    for (e_str, dtype) in rev_raw.keys():
        if dtype in (1, 4):
            all_q_ends.add(e_str)
    for (e_str, dtype) in ni_raw.keys():
        if dtype in (1, 4):
            all_q_ends.add(e_str)
    for (e_str, dtype) in ocf_raw.keys():
        if dtype in (1, 4):
            all_q_ends.add(e_str)
    for e_str in assets_raw.keys():
        all_q_ends.add(e_str)
        
    if not all_q_ends:
        return []
        
    sorted_q_ends = sorted(all_q_ends)
    
    # Pre-assemble 1Q values for all periods
    # For each metric, map end_str -> (val, filed_str, d_f)
    def build_metric_1q_map(raw_dict):
        m = {}
        for (e_str, dtype), v in raw_dict.items():
            if dtype == 1:
                m[e_str] = (v[0], v[1], v[5])
        return m
        
    rev_1q = build_metric_1q_map(rev_raw)
    gp_1q = build_metric_1q_map(gp_raw)
    cor_1q = build_metric_1q_map(cor_raw)
    ni_1q = build_metric_1q_map(ni_raw)
    rd_1q = build_metric_1q_map(rd_raw)
    sbc_1q = build_metric_1q_map(sbc_raw)
    
    # Opinc 1Q map: (val, filed_str, d_f, is_ebt)
    opinc_1q = {}
    for (e_str, dtype), v in opinc_p_raw.items():
        if dtype == 1:
            opinc_1q[e_str] = (v[0], v[1], v[5], False)
    for (e_str, dtype), v in opinc_s_raw.items():
        if dtype == 1 and e_str not in opinc_1q:
            opinc_1q[e_str] = (v[0], v[1], v[5], True)
            
    # SGA 1Q map
    sga_1q = {}
    for (e_str, dtype), v in sga_m_raw.items():
        if dtype == 1:
            sga_1q[e_str] = (v[0], v[1], v[5])
    for (e_str, dtype), v in sga_ga_raw.items():
        if dtype == 1 and e_str not in sga_1q:
            sm_val = sga_sm_raw.get((e_str, 1), (0.0,))[0]
            sga_1q[e_str] = (v[0] + sm_val, v[1], v[5])
            
    # Cash flows: OCF & CAPEX
    # Check if direct 1Q exists; otherwise derive from YTD differences
    def resolve_cash_flow_1q(cf_raw):
        cf_1q = {}
        # 1. Direct 1Q
        for (e_str, dtype), v in cf_raw.items():
            if dtype == 1:
                cf_1q[e_str] = (v[0], v[1], v[5])
                
        # 2. Derive Q2 from YTD 6M (dtype=2) minus Q1 (dtype=1)
        for (e_str, dtype), v2 in cf_raw.items():
            if dtype == 2 and e_str not in cf_1q:
                d_e2 = parse_date(e_str)
                f_date2 = v2[5]
                # Look for Q1 ending ~90 days earlier
                for q1_e, q1_val in cf_1q.items():
                    d_q1 = parse_date(q1_e)
                    if 70 <= (d_e2 - d_q1).days <= 115 and q1_val[2] <= f_date2:
                        cf_1q[e_str] = (v2[0] - q1_val[0], v2[1], f_date2)
                        break
                        
        # 3. Derive Q3 from YTD 9M (dtype=3) minus YTD 6M (dtype=2)
        for (e_str, dtype), v3 in cf_raw.items():
            if dtype == 3 and e_str not in cf_1q:
                d_e3 = parse_date(e_str)
                f_date3 = v3[5]
                # Look for 6M YTD
                found = False
                for (e2, dt2), v2 in cf_raw.items():
                    if dt2 == 2:
                        d_e2 = parse_date(e2)
                        if 70 <= (d_e3 - d_e2).days <= 115 and v2[5] <= f_date3:
                            cf_1q[e_str] = (v3[0] - v2[0], v3[1], f_date3)
                            found = True
                            break
                if not found:
                    # Look for Q1 and Q2
                    prev_qs = [k for k in cf_1q if 60 <= (d_e3 - parse_date(k)).days <= 210 and cf_1q[k][2] <= f_date3]
                    if len(prev_qs) >= 2:
                        sorted_prev = sorted(prev_qs, key=lambda x: parse_date(x))
                        if 70 <= (parse_date(sorted_prev[-1]) - parse_date(sorted_prev[-2])).days <= 115:
                            sum_prev = cf_1q[sorted_prev[-1]][0] + cf_1q[sorted_prev[-2]][0]
                            cf_1q[e_str] = (v3[0] - sum_prev, v3[1], f_date3)
        return cf_1q
        
    ocf_1q = resolve_cash_flow_1q(ocf_raw)
    capex_1q = resolve_cash_flow_1q(capex_raw)
    
    # Step 3: Now iterate over each unique quarter end_str and construct full record
    # Including Q4 derivation from FY - (Q1 + Q2 + Q3)
    quarter_records = []
    
    for e_str in sorted_q_ends:
        d_e = parse_date(e_str)
        
        # Determine filing date and form for this quarter
        # Prioritize 10-Q filing for Q1-Q3 or 10-K filing for Q4
        filing_info = None
        for raw in (rev_raw, ni_raw, ocf_raw, opinc_p_raw):
            if (e_str, 1) in raw:
                r = raw[(e_str, 1)]
                filing_info = (r[1], r[2], r[3], r[4], r[5])
                break
        if not filing_info:
            for raw in (rev_raw, ni_raw, ocf_raw, opinc_p_raw):
                if (e_str, 4) in raw:
                    r = raw[(e_str, 4)]
                    filing_info = (r[1], r[2], r[3], "Q4", r[5])
                    break
        if not filing_info and e_str in assets_raw:
            a = assets_raw[e_str]
            filing_info = (a[1], a[2], None, None, a[3])
            
        if not filing_info:
            continue
            
        filed_str, form_str, fy_val, fp_val, d_filed = filing_info
        days_to_file = (d_filed - d_e).days
        if not (0 < days_to_file <= 130):
            continue
            
        # Extract or impute flow metrics
        def get_or_impute_flow(metric_1q, metric_raw):
            # 1. Direct 1Q
            if e_str in metric_1q:
                return metric_1q[e_str][0]
            # 2. FY - (Q1 + Q2 + Q3)
            if (e_str, 4) in metric_raw:
                fy_entry = metric_raw[(e_str, 4)]
                fy_val_amt = fy_entry[0]
                fy_f_date = fy_entry[5]
                # Look for 3 prior single quarters inside [d_e - 310, d_e - 60]
                prev_q_keys = [
                    k for k in metric_1q 
                    if 60 <= (d_e - parse_date(k)).days <= 310 
                    and metric_1q[k][2] <= fy_f_date
                ]
                if len(prev_q_keys) >= 3:
                    sorted_p = sorted(prev_q_keys, key=lambda x: parse_date(x))
                    # Pick last 3 non-overlapping quarters
                    sel = [sorted_p[-1]]
                    for cand in reversed(sorted_p[:-1]):
                        if 70 <= (parse_date(sel[-1]) - parse_date(cand)).days <= 115:
                            sel.append(cand)
                            if len(sel) == 3:
                                break
                    if len(sel) == 3:
                        sum_3q = sum(metric_1q[k][0] for k in sel)
                        return fy_val_amt - sum_3q
            return None
            
        rev_val = get_or_impute_flow(rev_1q, rev_raw)
        gp_val = get_or_impute_flow(gp_1q, gp_raw)
        cor_val = get_or_impute_flow(cor_1q, cor_raw)
        if gp_val is None and rev_val is not None and cor_val is not None:
            if cor_val < rev_val * 2.0:
                gp_val = rev_val - cor_val
                
        # Opinc
        opinc_val = None
        opinc_is_ebt = False
        if e_str in opinc_1q:
            opinc_val = opinc_1q[e_str][0]
            opinc_is_ebt = opinc_1q[e_str][3]
        else:
            p_val = get_or_impute_flow(build_metric_1q_map(opinc_p_raw), opinc_p_raw)
            if p_val is not None:
                opinc_val = p_val
                opinc_is_ebt = False
            else:
                s_val = get_or_impute_flow(build_metric_1q_map(opinc_s_raw), opinc_s_raw)
                if s_val is not None:
                    opinc_val = s_val
                    opinc_is_ebt = True
                    
        ni_val = get_or_impute_flow(ni_1q, ni_raw)
        rd_val = get_or_impute_flow(rd_1q, rd_raw)
        
        # SGA
        sga_val = None
        if e_str in sga_1q:
            sga_val = sga_1q[e_str][0]
        else:
            sga_m_val = get_or_impute_flow(build_metric_1q_map(sga_m_raw), sga_m_raw)
            if sga_m_val is not None:
                sga_val = sga_m_val
            else:
                sga_ga_val = get_or_impute_flow(build_metric_1q_map(sga_ga_raw), sga_ga_raw)
                if sga_ga_val is not None:
                    sga_sm_val = get_or_impute_flow(build_metric_1q_map(sga_sm_raw), sga_sm_raw) or 0.0
                    sga_val = sga_ga_val + sga_sm_val
                    
        sbc_val = get_or_impute_flow(sbc_1q, sbc_raw)
        
        # Cash flow: OCF and CAPEX
        def get_or_impute_cf(cf_1q, cf_raw):
            if e_str in cf_1q:
                return cf_1q[e_str][0]
            # Try 10-K FY minus 9M or minus 3 quarters
            if (e_str, 4) in cf_raw:
                fy_val_amt = cf_raw[(e_str, 4)][0]
                fy_f_date = cf_raw[(e_str, 4)][5]
                # Check 9M YTD
                for (e3, dt3), v3 in cf_raw.items():
                    if dt3 == 3 and v3[5] <= fy_f_date:
                        d_e3 = parse_date(e3)
                        if 70 <= (d_e - d_e3).days <= 115:
                            return fy_val_amt - v3[0]
                # Check 3 quarters
                prev_q_keys = [
                    k for k in cf_1q 
                    if 60 <= (d_e - parse_date(k)).days <= 310 
                    and cf_1q[k][2] <= fy_f_date
                ]
                if len(prev_q_keys) >= 3:
                    sorted_p = sorted(prev_q_keys, key=lambda x: parse_date(x))
                    sel = [sorted_p[-1]]
                    for cand in reversed(sorted_p[:-1]):
                        if 70 <= (parse_date(sel[-1]) - parse_date(cand)).days <= 115:
                            sel.append(cand)
                            if len(sel) == 3:
                                break
                    if len(sel) == 3:
                        sum_3q = sum(cf_1q[k][0] for k in sel)
                        return fy_val_amt - sum_3q
            return None
            
        ocf_val = get_or_impute_cf(ocf_1q, ocf_raw)
        capex_val = get_or_impute_cf(capex_1q, capex_raw)
        fcf_q_val = (ocf_val - capex_val) if (ocf_val is not None and capex_val is not None) else None
        
        # Balance sheet instant items
        assets_val = assets_raw.get(e_str, (None,))[0]
        cash_val = cash_raw.get(e_str, (None,))[0]
        equity_val = equity_raw.get(e_str, (None,))[0]
        debt_lt_val = debt_lt_raw.get(e_str, (None,))[0]
        debt_st_val = debt_st_raw.get(e_str, (None,))[0]
        
        total_debt_val = None
        if debt_lt_val is not None or debt_st_val is not None:
            total_debt_val = (debt_lt_val or 0.0) + (debt_st_val or 0.0)
            
        # Shares
        shares_val = None
        if (e_str, 1) in dur_shares:
            shares_val = dur_shares[(e_str, 1)][0]
        elif (e_str, 4) in dur_shares:
            shares_val = dur_shares[(e_str, 4)][0]
        elif e_str in inst_shares:
            shares_val = inst_shares[e_str][0]
            
        shares_anomaly = bool(shares_val is not None and shares_val < 100_000)
        
        quarter_records.append({
            "ticker": ticker,
            "cik": cik,
            "name": company_name,
            "end": e_str,
            "d_end": d_e,
            "filed": filed_str,
            "d_filed": d_filed,
            "form": form_str,
            "fp": fp_val or ("FY" if "10-K" in form_str else "1Q"),
            "fiscal_year": int(fy_val) if fy_val is not None else d_e.year,
            "days_to_file": days_to_file,
            "rev": rev_val,
            "gp": gp_val,
            "cor": cor_val,
            "opinc": opinc_val,
            "opinc_is_ebt": opinc_is_ebt,
            "ni": ni_val,
            "rd": rd_val,
            "sga": sga_val,
            "sbc": sbc_val,
            "ocf": ocf_val,
            "capex": capex_val,
            "fcf_q": fcf_q_val,
            "assets": assets_val,
            "cash": cash_val,
            "equity": equity_val,
            "debt_lt": debt_lt_val,
            "debt_st": debt_st_val,
            "total_debt": total_debt_val,
            "shares": shares_val,
            "shares_anomaly": shares_anomaly
        })
        
    if not quarter_records:
        return []
        
    # Sort strictly by end date ascending
    quarter_records.sort(key=lambda x: x["d_end"])
    
    # Filter out redundant records with identical end_date (keep earliest filed)
    deduped = []
    seen_ends = set()
    for r in quarter_records:
        if r["end"] not in seen_ends:
            seen_ends.add(r["end"])
            deduped.append(r)
    quarter_records = deduped
    
    # Step 4: Compute Trajectory, TTM, Margins, Returns, YoY, and Inflection metrics
    # Strictly zero lookahead: all lag comparisons enforce filed_prior < filed_current
    n_q = len(quarter_records)
    
    for i in range(n_q):
        cur = quarter_records[i]
        d_end_i = cur["d_end"]
        d_filed_i = cur["d_filed"]
        
        # 1. TTM calculations: requires 4 consecutive quarters spanning 340~390 days
        rev_ttm = np.nan
        gp_ttm = np.nan
        opinc_ttm = np.nan
        ni_ttm = np.nan
        ocf_ttm = np.nan
        capex_ttm = np.nan
        fcf_ttm = np.nan
        sbc_ttm = np.nan
        
        if i >= 3:
            q_window = [quarter_records[i - 3], quarter_records[i - 2], quarter_records[i - 1], cur]
            # Check PIT and continuity
            all_pit_valid = all(q["d_filed"] <= d_filed_i for q in q_window)
            span_days = (d_end_i - q_window[0]["d_end"]).days
            step_valid = (
                70 <= (q_window[1]["d_end"] - q_window[0]["d_end"]).days <= 115 and
                70 <= (q_window[2]["d_end"] - q_window[1]["d_end"]).days <= 115 and
                70 <= (q_window[3]["d_end"] - q_window[2]["d_end"]).days <= 115
            )
            # 4 consecutive quarters have 3 steps between ends (approx 3 * 91 = 273 days; full year span ~365d)
            if all_pit_valid and step_valid and (250 <= span_days <= 305):
                def sum_window(key):
                    vals = [q[key] for q in q_window]
                    if any(v is None or np.isnan(v) for v in vals):
                        return np.nan
                    return float(sum(vals))
                rev_ttm = sum_window("rev")
                gp_ttm = sum_window("gp")
                opinc_ttm = sum_window("opinc")
                ni_ttm = sum_window("ni")
                ocf_ttm = sum_window("ocf")
                capex_ttm = sum_window("capex")
                sbc_ttm = sum_window("sbc")
                if not np.isnan(ocf_ttm) and not np.isnan(capex_ttm):
                    fcf_ttm = ocf_ttm - capex_ttm
                    
        cur["rev_ttm"] = rev_ttm
        cur["gp_ttm"] = gp_ttm
        cur["opinc_ttm"] = opinc_ttm
        cur["ni_ttm"] = ni_ttm
        cur["ocf_ttm"] = ocf_ttm
        cur["capex_ttm"] = capex_ttm
        cur["fcf_ttm"] = fcf_ttm
        cur["sbc_ttm"] = sbc_ttm
        
        # 2. Quarterly Margins & Commercialization
        rev_val = cur["rev"]
        gp_val = cur["gp"]
        opinc_val = cur["opinc"]
        ni_val = cur["ni"]
        rd_val = cur["rd"]
        sga_val = cur["sga"]
        
        cur["gm_q"] = (gp_val / rev_val) if (gp_val is not None and rev_val and rev_val > 0) else np.nan
        cur["opm_q"] = (opinc_val / rev_val) if (opinc_val is not None and rev_val and rev_val > 0) else np.nan
        cur["nm_q"] = (ni_val / rev_val) if (ni_val is not None and rev_val and rev_val > 0) else np.nan
        cur["rd_ratio_q"] = (rd_val / rev_val) if (rd_val is not None and rev_val and rev_val > 0) else np.nan
        cur["sga_ratio_q"] = (sga_val / rev_val) if (sga_val is not None and rev_val and rev_val > 0) else np.nan
        
        if gp_val is not None and sga_val is not None and rev_val and rev_val > 0:
            cur["gm_minus_sga_q"] = (gp_val - sga_val) / rev_val
        else:
            cur["gm_minus_sga_q"] = np.nan
            
        cur["fcf_margin_ttm"] = (fcf_ttm / rev_ttm) if (not np.isnan(fcf_ttm) and not np.isnan(rev_ttm) and rev_ttm > 0) else np.nan
        cur["ocf_to_ni_ttm"] = (ocf_ttm / ni_ttm) if (not np.isnan(ocf_ttm) and not np.isnan(ni_ttm) and ni_ttm != 0) else np.nan
        
        # 3. Capital Return (ROE and ROIC)
        assets_val = cur["assets"]
        equity_val = cur["equity"]
        cash_val = cur["cash"] or 0.0
        total_debt_val = cur["total_debt"] or 0.0
        
        neg_equity = bool(
            equity_val is None or 
            equity_val <= 0 or 
            (assets_val is not None and equity_val <= 0.05 * assets_val)
        )
        cur["neg_equity"] = neg_equity
        
        if not neg_equity and equity_val and not np.isnan(ni_ttm):
            cur["roe_ttm"] = ni_ttm / equity_val
        else:
            cur["roe_ttm"] = np.nan
            
        min_invested = (0.05 * assets_val) if (assets_val is not None and assets_val > 0) else 1e5
        eq_base = equity_val if (equity_val is not None and equity_val > 0) else 0.0
        invested_cap = max(eq_base + total_debt_val - cash_val, min_invested)
        cur["invested_cap"] = invested_cap
        
        if not np.isnan(opinc_ttm) and invested_cap > 0:
            cur["roic_ttm"] = (opinc_ttm * 0.79) / invested_cap
        else:
            cur["roic_ttm"] = np.nan
            
        # 4. YoY Growth & Comparison with ~365±25 days prior quarter
        q_yoy_prior = None
        for j in range(i - 1, -1, -1):
            cand_q = quarter_records[j]
            span = (d_end_i - cand_q["d_end"]).days
            if 340 <= span <= 390:
                if cand_q["d_filed"] < d_filed_i:
                    q_yoy_prior = cand_q
                    break
                    
        rev_yoy = np.nan
        gp_yoy = np.nan
        opinc_yoy = np.nan
        ni_yoy = np.nan
        gm_yoy_chg = np.nan
        opm_yoy_chg = np.nan
        gm_sga_yoy_chg = np.nan
        roic_yoy_chg = np.nan
        shares_yoy_dilution = np.nan
        
        if q_yoy_prior:
            p_rev = q_yoy_prior["rev"]
            p_gp = q_yoy_prior["gp"]
            p_op = q_yoy_prior["opinc"]
            p_ni = q_yoy_prior["ni"]
            p_gm = q_yoy_prior.get("gm_q", np.nan)
            p_opm = q_yoy_prior.get("opm_q", np.nan)
            p_gmsga = q_yoy_prior.get("gm_minus_sga_q", np.nan)
            p_roic = q_yoy_prior.get("roic_ttm", np.nan)
            p_shares = q_yoy_prior.get("shares")
            
            if rev_val is not None and p_rev and p_rev > 0:
                rev_yoy = (rev_val / p_rev) - 1.0
            if gp_val is not None and p_gp and p_gp > 0:
                gp_yoy = (gp_val / p_gp) - 1.0
            if opinc_val is not None and p_op and p_op != 0:
                opinc_yoy = (opinc_val - p_op) / abs(p_op)
            if ni_val is not None and p_ni and p_ni != 0:
                ni_yoy = (ni_val - p_ni) / abs(p_ni)
            if not np.isnan(cur["gm_q"]) and not np.isnan(p_gm):
                gm_yoy_chg = cur["gm_q"] - p_gm
            if not np.isnan(cur["opm_q"]) and not np.isnan(p_opm):
                opm_yoy_chg = cur["opm_q"] - p_opm
            if not np.isnan(cur["gm_minus_sga_q"]) and not np.isnan(p_gmsga):
                gm_sga_yoy_chg = cur["gm_minus_sga_q"] - p_gmsga
            if not np.isnan(cur["roic_ttm"]) and not np.isnan(p_roic):
                roic_yoy_chg = cur["roic_ttm"] - p_roic
            if cur["shares"] and p_shares and p_shares > 0:
                shares_yoy_dilution = (cur["shares"] / p_shares) - 1.0
                
        cur["rev_yoy"] = rev_yoy
        cur["gp_yoy"] = gp_yoy
        cur["opinc_yoy"] = opinc_yoy
        cur["ni_yoy"] = ni_yoy
        cur["gm_yoy_chg"] = gm_yoy_chg
        cur["opm_yoy_chg"] = opm_yoy_chg
        cur["gm_sga_yoy_chg"] = gm_sga_yoy_chg
        cur["roic_yoy_chg"] = roic_yoy_chg
        cur["shares_yoy_dilution"] = shares_yoy_dilution
        
        # 5. Lags & Inflection Acceleration
        def get_lag_q(lag_steps):
            idx = i - lag_steps
            if idx >= 0:
                lq = quarter_records[idx]
                if lq["d_filed"] < d_filed_i:
                    return lq
            return None
            
        q_lag1 = get_lag_q(1)
        q_lag2 = get_lag_q(2)
        q_lag3 = get_lag_q(3)
        q_lag4 = get_lag_q(4)
        
        cur["rev_yoy_lag1"] = q_lag1.get("rev_yoy", np.nan) if q_lag1 else np.nan
        cur["rev_yoy_lag2"] = q_lag2.get("rev_yoy", np.nan) if q_lag2 else np.nan
        cur["rev_yoy_lag3"] = q_lag3.get("rev_yoy", np.nan) if q_lag3 else np.nan
        cur["opm_q_lag1"] = q_lag1.get("opm_q", np.nan) if q_lag1 else np.nan
        cur["opm_q_lag2"] = q_lag2.get("opm_q", np.nan) if q_lag2 else np.nan
        cur["opm_q_lag3"] = q_lag3.get("opm_q", np.nan) if q_lag3 else np.nan
        cur["roic_ttm_lag4"] = q_yoy_prior.get("roic_ttm", np.nan) if q_yoy_prior else (q_lag4.get("roic_ttm", np.nan) if q_lag4 else np.nan)
        
        # Acceleration
        if not np.isnan(rev_yoy) and not np.isnan(cur["rev_yoy_lag1"]):
            cur["rev_accel_1q"] = rev_yoy - cur["rev_yoy_lag1"]
        else:
            cur["rev_accel_1q"] = np.nan
            
        # Consecutive counters (0, 1, 2, 3, 4+)
        prev_accel_cnt = q_lag1.get("consec_rev_accel_n", 0) if q_lag1 else 0
        if not np.isnan(cur["rev_accel_1q"]) and cur["rev_accel_1q"] > 0:
            cur["consec_rev_accel_n"] = min(prev_accel_cnt + 1, 5)
        else:
            cur["consec_rev_accel_n"] = 0
            
        prev_opm_cnt = q_lag1.get("consec_opm_expand_n", 0) if q_lag1 else 0
        if not np.isnan(opm_yoy_chg) and opm_yoy_chg > 0:
            cur["consec_opm_expand_n"] = min(prev_opm_cnt + 1, 5)
        else:
            cur["consec_opm_expand_n"] = 0
            
        prev_gmsga_cnt = q_lag1.get("consec_gm_sga_expand_n", 0) if q_lag1 else 0
        if not np.isnan(gm_sga_yoy_chg) and gm_sga_yoy_chg > 0:
            cur["consec_gm_sga_expand_n"] = min(prev_gmsga_cnt + 1, 5)
        else:
            cur["consec_gm_sga_expand_n"] = 0
            
        prev_dbl_cnt = q_lag1.get("consec_double_inflect_n", 0) if q_lag1 else 0
        is_double_inflect = (
            (not np.isnan(rev_yoy) and rev_yoy >= 0.10 or (not np.isnan(cur["rev_accel_1q"]) and cur["rev_accel_1q"] > 0)) and
            (not np.isnan(opm_yoy_chg) and opm_yoy_chg > 0)
        )
        if is_double_inflect:
            cur["consec_double_inflect_n"] = min(prev_dbl_cnt + 1, 5)
        else:
            cur["consec_double_inflect_n"] = 0
            
        # Turnaround to profit
        # ni > 0 and (count(ni <= 0 in past 4 quarters) >= 2 or (ni_ttm > 0 and ni_ttm_lag1 <= 0))
        turnaround = False
        if ni_val is not None and ni_val > 0:
            past_ni = []
            for lag_s in (1, 2, 3, 4):
                lq = get_lag_q(lag_s)
                if lq and lq.get("ni") is not None:
                    past_ni.append(lq["ni"])
            if len(past_ni) >= 2 and sum(1 for v in past_ni if v <= 0) >= 2:
                turnaround = True
            elif not np.isnan(ni_ttm) and ni_ttm > 0:
                prev_ni_ttm = q_lag1.get("ni_ttm", np.nan) if q_lag1 else np.nan
                if not np.isnan(prev_ni_ttm) and prev_ni_ttm <= 0:
                    turnaround = True
        cur["turnaround_to_profit_1q"] = turnaround

    # Clean up non-serializable datetime objects
    output_rows = []
    for r in quarter_records:
        r_clean = dict(r)
        del r_clean["d_end"]
        del r_clean["d_filed"]
        output_rows.append(r_clean)
        
    return output_rows


def main():
    t_start = time.time()
    print("=" * 80)
    print("W1_03 SEC XBRL Zero-Lookahead PIT Extractor (Shard 0)")
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    # 1. Locate companyfacts.zip
    zip_path = None
    for cand in ZIP_CANDIDATES:
        if os.path.exists(cand) and os.path.getsize(cand) > 1_000_000_000:
            zip_path = cand
            break
            
    if not zip_path:
        # Check if secondary is still downloading and wait if close
        sec_cand = ZIP_CANDIDATES[1]
        if os.path.exists(sec_cand):
            print(f"Waiting for {sec_cand} download to complete...")
            while True:
                sz = os.path.getsize(sec_cand)
                print(f"   Downloaded {sz / (1024*1024):.1f} MB / 1355.9 MB...")
                if sz >= 1421776943:
                    zip_path = sec_cand
                    break
                time.sleep(3)
        else:
            print("ERROR: companyfacts.zip not found!")
            sys.exit(1)
            
    print(f"Using companyfacts zip: {zip_path} (size: {os.path.getsize(zip_path)/(1024*1024):.1f} MB)")
    
    # 2. Load Shard 0 tickers
    with open(SHARD_FILE, "r") as f:
        shard = json.load(f)
    print(f"Loaded shard 0 with {len(shard)} companies.")
    
    os.makedirs(OUT_DIR, exist_ok=True)
    
    all_rows = []
    companies_processed = 0
    companies_with_data = 0
    
    with zipfile.ZipFile(zip_path, "r") as zf:
        zip_namelist = set(zf.namelist())
        
        for item in shard:
            cik = item["cik"]
            ticker = item["ticker"]
            name = item.get("name", ticker)
            
            fname = f"CIK{cik:010d}.json"
            if fname not in zip_namelist:
                continue
                
            raw_bytes = zf.read(fname)
            rows = process_company_xbrl(cik, ticker, name, raw_bytes)
            
            companies_processed += 1
            if rows:
                companies_with_data += 1
                all_rows.extend(rows)
                
            if companies_processed % 50 == 0 or companies_processed == len(shard):
                elapsed = time.time() - t_start
                print(f"[{companies_processed:3d}/{len(shard)}] Processed: {companies_processed} | Rows: {len(all_rows):,} | Elapsed: {elapsed:.1f}s")
                
    print("-" * 80)
    print(f"Extraction complete! Extracted {len(all_rows):,} rows across {companies_with_data} companies.")
    
    if not all_rows:
        print("ERROR: 0 rows extracted!")
        sys.exit(1)
        
    df = pd.DataFrame(all_rows)
    
    # Validation checks
    print("Performing strict Point-in-Time validation checks...")
    df["d_end"] = pd.to_datetime(df["end"])
    df["d_filed"] = pd.to_datetime(df["filed"])
    df["lag_days"] = (df["d_filed"] - df["d_end"]).dt.days
    
    invalid_lags = df[(df["lag_days"] <= 0) | (df["lag_days"] > 130)]
    print(f"Verification: Records with lag <= 0 or lag > 130: {len(invalid_lags)} (MUST BE 0!)")
    if len(invalid_lags) > 0:
        print("FATAL ERROR: Lookahead bias detected in extracted data!")
        sys.exit(1)
        
    df = df.drop(columns=["d_end", "d_filed", "lag_days"])
    
    # Save to Parquet
    table = pa.Table.from_pandas(df)
    pq.write_table(table, OUT_PARQUET, compression="snappy")
    
    out_sz_mb = os.path.getsize(OUT_PARQUET) / (1024 * 1024)
    elapsed_total = time.time() - t_start
    
    print("=" * 80)
    print(f"SUCCESS! Output saved to: {OUT_PARQUET}")
    print(f"Total Rows: {len(df):,}")
    print(f"Unique Tickers: {df['ticker'].nunique():,}")
    print(f"Earliest Filed: {df['filed'].min()} | Latest Filed: {df['filed'].max()}")
    print(f"Earliest Period End: {df['end'].min()} | Latest Period End: {df['end'].max()}")
    print(f"File Size: {out_sz_mb:.2f} MB")
    print(f"Total Time: {elapsed_total:.1f} seconds")
    print("=" * 80)


if __name__ == "__main__":
    main()
