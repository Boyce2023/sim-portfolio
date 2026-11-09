#!/usr/bin/env python3
"""
W1_06: SEC XBRL 100% Point-in-Time (PIT) Quarterly Financial & Trajectory Feature Panel
Shard 3 Extractor.

Features extracted strictly 100% Point-in-Time:
1. Forms: 10-Q, 10-K, 10-Q/A, 10-K/A
2. Lag condition: 0 < (filed - end).days <= 130
3. Deduplication: Earliest filed date and original first disclosure value
4. Imputation: Q4 = FY - (Q1+Q2+Q3); Cash flow YTD differencing (prior filed <= current filed)
5. Multi-quarter features: TTMs, Margins, ROIC, YoY, Acceleration, Streaks, Lags
"""

import os
import sys
import json
import time
import zipfile
import warnings
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

warnings.filterwarnings("ignore")

SHARD_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/shards/xbrl_shard_3.json"
OUT_DIR = "/tmp/us_earn_macro_bt_20261109/sec_xbrl_shards"
OUT_PARQUET = os.path.join(OUT_DIR, "xbrl_pit_shard_3.parquet")

ZIP_CANDIDATES = [
    "/tmp/us_earn_macro_bt_20261109/companyfacts.zip",
    "/tmp/us_xuangu_20261109/w1_a3/companyfacts.zip",
]

# Subject tags according to prompt specifications
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

OPINC_PRIMARY = ["OperatingIncomeLoss"]
OPINC_FALLBACK = ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"]

NI_TAGS = [
    "NetIncomeLoss",
    "ProfitLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic"
]

RD_TAGS = [
    "ResearchAndDevelopmentExpense",
    "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"
]

SGA_TAGS = [
    "SellingGeneralAndAdministrativeExpense",
    "GeneralAndAdministrativeExpense"
]
SGA_SM = ["SellingAndMarketingExpense"]
SGA_GA = ["GeneralAndAdministrativeExpense"]

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

ASSETS_TAGS = ["Assets"]
CASH_TAGS = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
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
    "DebtCurrent",
    "LongTermDebtCurrent",
    "ShortTermBorrowings"
]

SHARES_DILUTED = ["WeightedAverageNumberOfDilutedSharesOutstanding"]
SHARES_BASIC = ["WeightedAverageNumberOfSharesOutstandingBasic"]
SHARES_COMMON = ["CommonStockSharesOutstanding"]
SHARES_DEI = ["EntityCommonStockSharesOutstanding"]

VALID_FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}

def parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def get_valid_zip_path():
    for zp in ZIP_CANDIDATES:
        if os.path.exists(zp):
            try:
                # Test opening zip
                with zipfile.ZipFile(zp, "r") as zf:
                    if len(zf.namelist()) > 1000:
                        return zp
            except Exception:
                pass
    return None

def extract_flow_metric_records(us_gaap, tag_list):
    """
    Extract flow records for a list of prioritized tags.
    Returns: dict mapping (end_date, dur_type) -> (filed_date, val, tag_idx, form)
    where dur_type is:
      1: 1Q (68-112d)
      2: 6M YTD (165-200d)
      3: 9M YTD (255-295d)
      4: FY (345-385d)
    Strict PIT rule: earliest filed date and first original disclosure value.
    """
    records_by_key = {} # (end_date, dur_type) -> list of (filed_date, val, tag_idx, form)
    for tag_idx, tag in enumerate(tag_list):
        node = us_gaap.get(tag)
        if not node:
            continue
        items = node.get("units", {}).get("USD", [])
        for item in items:
            form = item.get("form")
            if form not in VALID_FORMS:
                continue
            start_s = item.get("start")
            end_s = item.get("end")
            filed_s = item.get("filed")
            val = item.get("val")
            if not (start_s and end_s and filed_s and val is not None):
                continue
            try:
                start_dt = parse_date(start_s)
                end_dt = parse_date(end_s)
                filed_dt = parse_date(filed_s)
            except Exception:
                continue
            if not (start_dt and end_dt and filed_dt):
                continue
            
            # Physical PIT filter: 0 < (filed - end).days <= 130
            lag = (filed_dt - end_dt).days
            if not (0 < lag <= 130):
                continue
            
            dur = (end_dt - start_dt).days
            if 68 <= dur <= 112:
                dt = 1
            elif 165 <= dur <= 200:
                dt = 2
            elif 255 <= dur <= 295:
                dt = 3
            elif 345 <= dur <= 385:
                dt = 4
            else:
                continue

            k = (end_dt, dt)
            records_by_key.setdefault(k, []).append((filed_dt, float(val), tag_idx, form))

    # Deduplicate: Earliest filed date first! Break tie by lowest tag_idx, then prefer non-amended form
    best_map = {}
    for k, lst in records_by_key.items():
        # Sort by filed_dt asc, tag_idx asc, form not-A first
        lst.sort(key=lambda x: (x[0], x[2], 1 if "/A" in x[3] else 0))
        best_map[k] = lst[0]
    return best_map

def extract_instant_metric_records(us_gaap, tag_list):
    """
    Extract instant (balance sheet) records for prioritized tags.
    Returns: dict mapping end_date -> (filed_date, val, tag_idx, form)
    Strict PIT rule: earliest filed date and first original disclosure value.
    """
    records_by_end = {}
    for tag_idx, tag in enumerate(tag_list):
        node = us_gaap.get(tag)
        if not node:
            continue
        items = node.get("units", {}).get("USD", [])
        for item in items:
            form = item.get("form")
            if form not in VALID_FORMS:
                continue
            end_s = item.get("end")
            filed_s = item.get("filed")
            val = item.get("val")
            if not (end_s and filed_s and val is not None):
                continue
            try:
                end_dt = parse_date(end_s)
                filed_dt = parse_date(filed_s)
            except Exception:
                continue
            if not (end_dt and filed_dt):
                continue
            
            # Physical PIT filter: 0 < (filed - end).days <= 130
            lag = (filed_dt - end_dt).days
            if not (0 < lag <= 130):
                continue

            records_by_end.setdefault(end_dt, []).append((filed_dt, float(val), tag_idx, form))

    best_map = {}
    for k, lst in records_by_end.items():
        lst.sort(key=lambda x: (x[0], x[2], 1 if "/A" in x[3] else 0))
        best_map[k] = lst[0]
    return best_map

def extract_shares_records(us_gaap, dei):
    """
    Extract shares records with priority:
    1. WeightedAverageNumberOfDilutedSharesOutstanding (1Q or FY flow)
    2. WeightedAverageNumberOfSharesOutstandingBasic (1Q or FY flow)
    3. CommonStockSharesOutstanding (instant)
    4. EntityCommonStockSharesOutstanding (instant dei)
    Returns: dict mapping end_date -> (filed_date, val, prio, form)
    """
    records_by_end = {}
    
    # Priority 0: Diluted
    # Priority 1: Basic
    for prio, tag in enumerate(SHARES_DILUTED + SHARES_BASIC):
        node = us_gaap.get(tag)
        if not node:
            continue
        items = node.get("units", {}).get("shares", [])
        for item in items:
            form = item.get("form")
            if form not in VALID_FORMS:
                continue
            end_s = item.get("end")
            filed_s = item.get("filed")
            val = item.get("val")
            if not (end_s and filed_s and val is not None and val > 0):
                continue
            end_dt = parse_date(end_s)
            filed_dt = parse_date(filed_s)
            if not (end_dt and filed_dt):
                continue
            lag = (filed_dt - end_dt).days
            if not (0 < lag <= 130):
                continue
            
            # If duration present, check duration
            start_s = item.get("start")
            dur_penalty = 0
            if start_s:
                start_dt = parse_date(start_s)
                if start_dt:
                    dur = (end_dt - start_dt).days
                    if 68 <= dur <= 112:
                        dur_penalty = 0 # best
                    elif 345 <= dur <= 385:
                        dur_penalty = 1 # annual
                    else:
                        continue
            records_by_end.setdefault(end_dt, []).append((filed_dt, float(val), prio * 2 + dur_penalty, form))

    # Priority 2: CommonStockSharesOutstanding
    if "CommonStockSharesOutstanding" in us_gaap:
        items = us_gaap["CommonStockSharesOutstanding"].get("units", {}).get("shares", [])
        for item in items:
            form = item.get("form")
            if form not in VALID_FORMS:
                continue
            end_s = item.get("end")
            filed_s = item.get("filed")
            val = item.get("val")
            if not (end_s and filed_s and val is not None and val > 0):
                continue
            end_dt = parse_date(end_s)
            filed_dt = parse_date(filed_s)
            if not (end_dt and filed_dt):
                continue
            lag = (filed_dt - end_dt).days
            if not (0 < lag <= 130):
                continue
            records_by_end.setdefault(end_dt, []).append((filed_dt, float(val), 6, form))

    # Priority 3: EntityCommonStockSharesOutstanding
    if "EntityCommonStockSharesOutstanding" in dei:
        items = dei["EntityCommonStockSharesOutstanding"].get("units", {}).get("shares", [])
        for item in items:
            form = item.get("form")
            if form not in VALID_FORMS:
                continue
            end_s = item.get("end")
            filed_s = item.get("filed")
            val = item.get("val")
            if not (end_s and filed_s and val is not None and val > 0):
                continue
            end_dt = parse_date(end_s)
            filed_dt = parse_date(filed_s)
            if not (end_dt and filed_dt):
                continue
            lag = (filed_dt - end_dt).days
            if not (0 < lag <= 130):
                continue
            records_by_end.setdefault(end_dt, []).append((filed_dt, float(val), 8, form))

    best_map = {}
    for k, lst in records_by_end.items():
        lst.sort(key=lambda x: (x[0], x[2]))
        best_map[k] = lst[0]
    return best_map

def process_company_pit(cik, ticker, company_name, zip_path):
    """
    Extract PIT quarterly time series and compute multi-quarter features for a company.
    """
    fname = f"CIK{cik:010d}.json"
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            if fname not in zf.namelist():
                return []
            content = zf.read(fname)
        data = json.loads(content)
    except Exception:
        return []

    facts = data.get("facts", {})
    us_gaap = facts.get("us-gaap", {})
    dei = facts.get("dei", {})
    if not us_gaap:
        return []

    # 1. Extract raw concept records
    m_rev = extract_flow_metric_records(us_gaap, REV_TAGS)
    m_gp = extract_flow_metric_records(us_gaap, GP_TAGS)
    m_cor = extract_flow_metric_records(us_gaap, COR_TAGS)
    
    m_op_pri = extract_flow_metric_records(us_gaap, OPINC_PRIMARY)
    m_op_fb = extract_flow_metric_records(us_gaap, OPINC_FALLBACK)
    
    m_ni = extract_flow_metric_records(us_gaap, NI_TAGS)
    m_rd = extract_flow_metric_records(us_gaap, RD_TAGS)
    
    m_sga = extract_flow_metric_records(us_gaap, SGA_TAGS)
    m_sm = extract_flow_metric_records(us_gaap, SGA_SM)
    m_ga = extract_flow_metric_records(us_gaap, SGA_GA)
    
    m_sbc = extract_flow_metric_records(us_gaap, SBC_TAGS)
    m_ocf = extract_flow_metric_records(us_gaap, OCF_TAGS)
    m_capex = extract_flow_metric_records(us_gaap, CAPEX_TAGS)

    s_assets = extract_instant_metric_records(us_gaap, ASSETS_TAGS)
    s_cash = extract_instant_metric_records(us_gaap, CASH_TAGS)
    s_equity = extract_instant_metric_records(us_gaap, EQUITY_TAGS)
    s_debt_lt = extract_instant_metric_records(us_gaap, DEBT_LT_TAGS)
    s_debt_st = extract_instant_metric_records(us_gaap, DEBT_ST_TAGS)
    s_shares = extract_shares_records(us_gaap, dei)

    # 2. Collect all distinct period end dates from 10-Q / 10-K filings
    # A valid quarter end must have a filing date and revenue or net income or assets
    all_ends = set()
    for (e_dt, _) in m_rev.keys():
        all_ends.add(e_dt)
    for (e_dt, _) in m_ni.keys():
        all_ends.add(e_dt)
    for e_dt in s_assets.keys():
        all_ends.add(e_dt)

    sorted_ends = sorted(all_ends)
    if not sorted_ends:
        return []

    # Clean calendar: merge ends within 25 days (52/53 week accounting adjustments)
    clean_ends = []
    for e_dt in sorted_ends:
        if clean_ends and (e_dt - clean_ends[-1]).days < 35:
            continue
        clean_ends.append(e_dt)

    # 3. For each end date, determine the primary filing date and form
    quarter_events = []
    for e_dt in clean_ends:
        # Check all records for this end_dt to determine earliest filing date
        cands = []
        for d_type in (1, 4, 2, 3):
            if (e_dt, d_type) in m_rev:
                cands.append(m_rev[(e_dt, d_type)])
            if (e_dt, d_type) in m_ni:
                cands.append(m_ni[(e_dt, d_type)])
        if e_dt in s_assets:
            cands.append(s_assets[e_dt])
        if e_dt in s_equity:
            cands.append(s_equity[e_dt])
        if not cands:
            continue
        cands.sort(key=lambda x: x[0])
        earliest_filed = cands[0][0]
        # Form: prefer 10-K if FY present or form is 10-K, else 10-Q
        form = "10-Q"
        for item in cands:
            if "10-K" in item[3]:
                form = "10-K"
                break
        quarter_events.append((e_dt, earliest_filed, form))

    # Helper function to get single quarter flow for a metric map with Q4 & YTD imputation
    # We will build single-quarter maps: q_map[end_dt] = (val, filed_dt)
    def build_single_quarter_flow(metric_map, is_cash_flow=False):
        q_map = {} # end_dt -> (val, filed_dt)
        # Direct 1Q
        for (e_dt, dt), (f_dt, val, _, form) in metric_map.items():
            if dt == 1:
                q_map[e_dt] = (val, f_dt)

        # For cash flows, handle 6M and 9M YTD differencing
        if is_cash_flow:
            # Sort ends
            for e_dt, f_dt, form in quarter_events:
                if e_dt in q_map:
                    continue
                # Try 6M YTD (dt=2)
                if (e_dt, 2) in metric_map:
                    ytd6_f, ytd6_v, _, _ = metric_map[(e_dt, 2)]
                    # Look for Q1 ending ~91 days prior
                    q1_cands = [k for k in q_map if 70 <= (e_dt - k).days <= 112]
                    if len(q1_cands) == 1:
                        q1_k = q1_cands[0]
                        q1_v, q1_f = q_map[q1_k]
                        if q1_f <= ytd6_f:
                            q_map[e_dt] = (ytd6_v - q1_v, ytd6_f)
                # Try 9M YTD (dt=3)
                elif (e_dt, 3) in metric_map:
                    ytd9_f, ytd9_v, _, _ = metric_map[(e_dt, 3)]
                    # Look for 6M YTD ~91 days prior
                    prior_6m = [k for (k, dt2) in metric_map if dt2 == 2 and 70 <= (e_dt - k).days <= 112]
                    if prior_6m:
                        p6_k = prior_6m[0]
                        p6_f, p6_v, _, _ = metric_map[(p6_k, 2)]
                        if p6_f <= ytd9_f:
                            q_map[e_dt] = (ytd9_v - p6_v, ytd9_f)
                    else:
                        # Check if Q1 and Q2 exist
                        prior_qs = sorted([k for k in q_map if 70 <= (e_dt - k).days <= 210])
                        if len(prior_qs) >= 2 and 70 <= (prior_qs[-1] - prior_qs[-2]).days <= 115:
                            q1_k, q2_k = prior_qs[-2], prior_qs[-1]
                            if q_map[q1_k][1] <= ytd9_f and q_map[q2_k][1] <= ytd9_f:
                                q_map[e_dt] = (ytd9_v - (q_map[q1_k][0] + q_map[q2_k][0]), ytd9_f)

        # Rule 4: Q4 single quarter deduction from FY (dt=4)
        for e_dt, f_dt, form in quarter_events:
            if e_dt in q_map:
                continue
            if (e_dt, 4) in metric_map:
                fy_f, fy_v, _, _ = metric_map[(e_dt, 4)]
                # Look for Q1, Q2, Q3 in (e_dt - 310d, e_dt - 60d) with filed <= fy_f
                prior_qs = sorted([k for k in q_map if 60 <= (e_dt - k).days <= 310 and q_map[k][1] <= fy_f])
                # Filter to 3 non-overlapping quarters spaced ~91 days apart
                if len(prior_qs) >= 3:
                    selected = [prior_qs[-1]]
                    for cand_k in reversed(prior_qs[:-1]):
                        if 70 <= (selected[-1] - cand_k).days <= 115:
                            selected.append(cand_k)
                            if len(selected) == 3:
                                break
                    if len(selected) == 3:
                        sum_3q = sum(q_map[k][0] for k in selected)
                        q_map[e_dt] = (fy_v - sum_3q, fy_f)

        return q_map

    # Build flow single-quarter maps
    q_rev = build_single_quarter_flow(m_rev)
    q_gp = build_single_quarter_flow(m_gp)
    q_cor = build_single_quarter_flow(m_cor)
    q_op_pri = build_single_quarter_flow(m_op_pri)
    q_op_fb = build_single_quarter_flow(m_op_fb)
    q_ni = build_single_quarter_flow(m_ni)
    q_rd = build_single_quarter_flow(m_rd)
    q_sga = build_single_quarter_flow(m_sga)
    q_sm = build_single_quarter_flow(m_sm)
    q_ga = build_single_quarter_flow(m_ga)
    q_sbc = build_single_quarter_flow(m_sbc)
    q_ocf = build_single_quarter_flow(m_ocf, is_cash_flow=True)
    q_capex = build_single_quarter_flow(m_capex, is_cash_flow=True)

    # 4. Assemble basic panel records
    quarter_records = []
    for e_dt, f_dt, form in quarter_events:
        # Revenue
        rev_val = q_rev.get(e_dt, (np.nan, None))[0]
        # Gross profit & COR
        gp_val = q_gp.get(e_dt, (np.nan, None))[0]
        cor_val = q_cor.get(e_dt, (np.nan, None))[0]
        if np.isnan(gp_val) and not np.isnan(rev_val) and not np.isnan(cor_val):
            gp_val = rev_val - cor_val

        # Operating income
        opinc_is_ebt = False
        if e_dt in q_op_pri:
            opinc_val = q_op_pri[e_dt][0]
        elif e_dt in q_op_fb:
            opinc_val = q_op_fb[e_dt][0]
            opinc_is_ebt = True
        else:
            opinc_val = np.nan

        # Net income
        ni_val = q_ni.get(e_dt, (np.nan, None))[0]
        # RD
        rd_val = q_rd.get(e_dt, (np.nan, None))[0]

        # SGA
        sga_val = q_sga.get(e_dt, (np.nan, None))[0]
        if np.isnan(sga_val):
            sm_v = q_sm.get(e_dt, (np.nan, None))[0]
            ga_v = q_ga.get(e_dt, (np.nan, None))[0]
            if not np.isnan(sm_v) and not np.isnan(ga_v):
                sga_val = sm_v + ga_v
            elif not np.isnan(ga_v):
                sga_val = ga_v

        # SBC
        sbc_val = q_sbc.get(e_dt, (np.nan, None))[0]

        # Cash flows
        ocf_val = q_ocf.get(e_dt, (np.nan, None))[0]
        capex_raw = q_capex.get(e_dt, (np.nan, None))[0]
        capex_val = abs(capex_raw) if not np.isnan(capex_raw) else np.nan

        # Balance sheet items
        assets_val = s_assets.get(e_dt, (None, np.nan))[1]
        cash_val = s_cash.get(e_dt, (None, np.nan))[1]
        equity_val = s_equity.get(e_dt, (None, np.nan))[1]
        debt_lt_val = s_debt_lt.get(e_dt, (None, np.nan))[1]
        debt_st_val = s_debt_st.get(e_dt, (None, np.nan))[1]
        shares_val = s_shares.get(e_dt, (None, np.nan))[1]

        # Determine filing date for this quarter (earliest of the components reported)
        f_dates = [f_dt]
        if e_dt in q_rev and q_rev[e_dt][1] is not None:
            f_dates.append(q_rev[e_dt][1])
        if e_dt in q_ni and q_ni[e_dt][1] is not None:
            f_dates.append(q_ni[e_dt][1])
        if e_dt in s_assets and s_assets[e_dt][0] is not None:
            f_dates.append(s_assets[e_dt][0])
        actual_filed = min(f_dates)

        # Skip rows that have neither rev nor ni nor assets
        if np.isnan(rev_val) and np.isnan(ni_val) and np.isnan(assets_val):
            continue

        quarter_records.append({
            "ticker": ticker,
            "cik": int(cik),
            "company_name": company_name,
            "end_date": e_dt.isoformat(),
            "filed_date": actual_filed.isoformat(),
            "form": form,
            "end_dt_obj": e_dt,
            "filed_dt_obj": actual_filed,
            "rev": rev_val,
            "gp": gp_val,
            "cor": cor_val,
            "opinc": opinc_val,
            "opinc_is_ebt": bool(opinc_is_ebt),
            "ni": ni_val,
            "rd": rd_val,
            "sga": sga_val,
            "sbc": sbc_val,
            "ocf": ocf_val,
            "capex": capex_val,
            "assets": assets_val,
            "cash": cash_val,
            "equity": equity_val,
            "debt_lt": debt_lt_val,
            "debt_st": debt_st_val,
            "shares": shares_val,
        })

    if not quarter_records:
        return []

    # Sort strictly chronologically by end_dt_obj
    quarter_records.sort(key=lambda x: x["end_dt_obj"])
    df = pd.DataFrame(quarter_records)
    n = len(df)

    # 5. Compute TTM, Margins, ROE/ROIC, YoY, and Multi-Quarter Trajectories
    rev_ttm = np.full(n, np.nan)
    gp_ttm = np.full(n, np.nan)
    opinc_ttm = np.full(n, np.nan)
    ni_ttm = np.full(n, np.nan)
    ocf_ttm = np.full(n, np.nan)
    capex_ttm = np.full(n, np.nan)
    fcf_ttm = np.full(n, np.nan)
    sbc_ttm = np.full(n, np.nan)

    gm_q = np.full(n, np.nan)
    opm_q = np.full(n, np.nan)
    nm_q = np.full(n, np.nan)
    rd_ratio_q = np.full(n, np.nan)
    sga_ratio_q = np.full(n, np.nan)
    gm_minus_sga_q = np.full(n, np.nan)
    fcf_margin_ttm = np.full(n, np.nan)
    ocf_to_ni_ttm = np.full(n, np.nan)

    neg_equity = np.full(n, False, dtype=bool)
    roe_ttm = np.full(n, np.nan)
    invested_cap = np.full(n, np.nan)
    roic_ttm = np.full(n, np.nan)

    rev_yoy = np.full(n, np.nan)
    gp_yoy = np.full(n, np.nan)
    opinc_yoy = np.full(n, np.nan)
    ni_yoy = np.full(n, np.nan)
    gm_yoy_chg = np.full(n, np.nan)
    opm_yoy_chg = np.full(n, np.nan)
    gm_sga_yoy_chg = np.full(n, np.nan)
    roic_yoy_chg = np.full(n, np.nan)
    shares_yoy_dilution = np.full(n, np.nan)

    # Quarterly margins first
    for i in range(n):
        r = df.loc[i, "rev"]
        g = df.loc[i, "gp"]
        op = df.loc[i, "opinc"]
        ni = df.loc[i, "ni"]
        rd = df.loc[i, "rd"]
        sga = df.loc[i, "sga"]
        
        if pd.notna(r) and r > 0:
            if pd.notna(g):
                gm_q[i] = g / r
            if pd.notna(op):
                opm_q[i] = op / r
            if pd.notna(ni):
                nm_q[i] = ni / r
            if pd.notna(rd):
                rd_ratio_q[i] = rd / r
            if pd.notna(sga):
                sga_ratio_q[i] = sga / r
            if pd.notna(gm_q[i]) and pd.notna(sga_ratio_q[i]):
                gm_minus_sga_q[i] = gm_q[i] - sga_ratio_q[i]

    # Helper to check if indices form consecutive 4 quarters
    for i in range(n):
        # TTM requires 4 consecutive quarters ending at i
        # Look backwards for 3 preceding quarters spaced ~91 days apart
        ttm_indices = [i]
        curr_e = df.loc[i, "end_dt_obj"]
        for k in range(i - 1, -1, -1):
            prior_e = df.loc[k, "end_dt_obj"]
            expected_lag = 91.3 * len(ttm_indices)
            diff = (curr_e - prior_e).days
            if abs(diff - expected_lag) <= 25:
                ttm_indices.append(k)
                if len(ttm_indices) == 4:
                    break

        if len(ttm_indices) == 4:
            # Check PIT filing condition: all prior filings <= current filing
            curr_f = df.loc[i, "filed_dt_obj"]
            all_pit_ok = all(df.loc[k, "filed_dt_obj"] <= curr_f for k in ttm_indices)
            if all_pit_ok:
                revs = [df.loc[k, "rev"] for k in ttm_indices]
                gps = [df.loc[k, "gp"] for k in ttm_indices]
                ops = [df.loc[k, "opinc"] for k in ttm_indices]
                nis = [df.loc[k, "ni"] for k in ttm_indices]
                ocfs = [df.loc[k, "ocf"] for k in ttm_indices]
                caps = [df.loc[k, "capex"] for k in ttm_indices]
                sbcs = [df.loc[k, "sbc"] for k in ttm_indices]

                if not any(pd.isna(x) for x in revs):
                    rev_ttm[i] = sum(revs)
                if not any(pd.isna(x) for x in gps):
                    gp_ttm[i] = sum(gps)
                if not any(pd.isna(x) for x in ops):
                    opinc_ttm[i] = sum(ops)
                if not any(pd.isna(x) for x in nis):
                    ni_ttm[i] = sum(nis)
                if not any(pd.isna(x) for x in ocfs):
                    ocf_ttm[i] = sum(ocfs)
                if not any(pd.isna(x) for x in caps):
                    capex_ttm[i] = sum(caps)
                if pd.notna(ocf_ttm[i]) and pd.notna(capex_ttm[i]):
                    fcf_ttm[i] = ocf_ttm[i] - capex_ttm[i]
                if not any(pd.isna(x) for x in sbcs):
                    sbc_ttm[i] = sum(sbcs)
                elif any(pd.notna(x) for x in sbcs):
                    sbc_ttm[i] = sum(x for x in sbcs if pd.notna(x))

                if pd.notna(fcf_ttm[i]) and pd.notna(rev_ttm[i]) and rev_ttm[i] > 0:
                    fcf_margin_ttm[i] = fcf_ttm[i] / rev_ttm[i]
                if pd.notna(ocf_ttm[i]) and pd.notna(ni_ttm[i]) and ni_ttm[i] != 0:
                    ocf_to_ni_ttm[i] = ocf_ttm[i] / ni_ttm[i]

        # Balance sheet ratios: neg_equity, ROE, Invested Capital, ROIC
        eq = df.loc[i, "equity"]
        ast = df.loc[i, "assets"]
        csh = df.loc[i, "cash"]
        d_lt = df.loc[i, "debt_lt"]
        d_st = df.loc[i, "debt_st"]

        is_neg = bool(pd.isna(eq) or pd.isna(ast) or eq <= 0.05 * ast or eq <= 0)
        neg_equity[i] = is_neg

        if not is_neg and pd.notna(ni_ttm[i]):
            roe_ttm[i] = ni_ttm[i] / eq

        # Invested capital = Equity + Total Debt - Cash
        tot_d = (d_lt if pd.notna(d_lt) else 0.0) + (d_st if pd.notna(d_st) else 0.0)
        csh_c = csh if pd.notna(csh) else 0.0
        eq_c = eq if (pd.notna(eq) and eq > 0) else 0.0
        inv_cap = eq_c + tot_d - csh_c
        invested_cap[i] = inv_cap

        floor_ic = 0.15 * ast if (pd.notna(ast) and ast > 0) else 0.0
        denom_roic = max(inv_cap, floor_ic)
        if denom_roic > 0 and pd.notna(opinc_ttm[i]):
            # NOPAT = opinc_ttm * (1 - 0.21)
            roic_ttm[i] = (opinc_ttm[i] * 0.79) / denom_roic

        # YoY comparisons (~365±25 days prior and prior.filed < curr.filed)
        curr_e = df.loc[i, "end_dt_obj"]
        curr_f = df.loc[i, "filed_dt_obj"]
        prior_yoy_idx = None
        for k in range(i - 1, -1, -1):
            pe = df.loc[k, "end_dt_obj"]
            pf = df.loc[k, "filed_dt_obj"]
            days_diff = (curr_e - pe).days
            if 340 <= days_diff <= 390 and pf < curr_f:
                prior_yoy_idx = k
                break

        if prior_yoy_idx is not None:
            k = prior_yoy_idx
            # rev_yoy
            r_c, r_p = df.loc[i, "rev"], df.loc[k, "rev"]
            if pd.notna(r_c) and pd.notna(r_p) and r_p > 0:
                rev_yoy[i] = (r_c - r_p) / r_p

            # gp_yoy
            g_c, g_p = df.loc[i, "gp"], df.loc[k, "gp"]
            if pd.notna(g_c) and pd.notna(g_p) and g_p != 0:
                gp_yoy[i] = (g_c - g_p) / abs(g_p)

            # opinc_yoy
            op_c, op_p = df.loc[i, "opinc"], df.loc[k, "opinc"]
            if pd.notna(op_c) and pd.notna(op_p) and op_p != 0:
                opinc_yoy[i] = (op_c - op_p) / abs(op_p)

            # ni_yoy
            ni_c, ni_p = df.loc[i, "ni"], df.loc[k, "ni"]
            if pd.notna(ni_c) and pd.notna(ni_p) and ni_p != 0:
                ni_yoy[i] = (ni_c - ni_p) / abs(ni_p)

            # Margin changes
            if pd.notna(gm_q[i]) and pd.notna(gm_q[k]):
                gm_yoy_chg[i] = gm_q[i] - gm_q[k]
            if pd.notna(opm_q[i]) and pd.notna(opm_q[k]):
                opm_yoy_chg[i] = opm_q[i] - opm_q[k]
            if pd.notna(gm_minus_sga_q[i]) and pd.notna(gm_minus_sga_q[k]):
                gm_sga_yoy_chg[i] = gm_minus_sga_q[i] - gm_minus_sga_q[k]
            if pd.notna(roic_ttm[i]) and pd.notna(roic_ttm[k]):
                roic_yoy_chg[i] = roic_ttm[i] - roic_ttm[k]

            # shares dilution
            sh_c, sh_p = df.loc[i, "shares"], df.loc[k, "shares"]
            if pd.notna(sh_c) and pd.notna(sh_p) and sh_p > 0:
                shares_yoy_dilution[i] = (sh_c - sh_p) / sh_p

    # Assign intermediate features to DataFrame
    df["rev_ttm"] = rev_ttm
    df["gp_ttm"] = gp_ttm
    df["opinc_ttm"] = opinc_ttm
    df["ni_ttm"] = ni_ttm
    df["ocf_ttm"] = ocf_ttm
    df["capex_ttm"] = capex_ttm
    df["fcf_ttm"] = fcf_ttm
    df["sbc_ttm"] = sbc_ttm

    df["gm_q"] = gm_q
    df["opm_q"] = opm_q
    df["nm_q"] = nm_q
    df["rd_ratio_q"] = rd_ratio_q
    df["sga_ratio_q"] = sga_ratio_q
    df["gm_minus_sga_q"] = gm_minus_sga_q
    df["fcf_margin_ttm"] = fcf_margin_ttm
    df["ocf_to_ni_ttm"] = ocf_to_ni_ttm

    df["neg_equity"] = neg_equity
    df["roe_ttm"] = roe_ttm
    df["invested_cap"] = invested_cap
    df["roic_ttm"] = roic_ttm

    df["rev_yoy"] = rev_yoy
    df["gp_yoy"] = gp_yoy
    df["opinc_yoy"] = opinc_yoy
    df["ni_yoy"] = ni_yoy
    df["gm_yoy_chg"] = gm_yoy_chg
    df["opm_yoy_chg"] = opm_yoy_chg
    df["gm_sga_yoy_chg"] = gm_sga_yoy_chg
    df["roic_yoy_chg"] = roic_yoy_chg
    df["shares_yoy_dilution"] = shares_yoy_dilution

    # 6. Multi-quarter Trajectory & Lags
    rev_accel_1q = np.full(n, np.nan)
    consec_rev_accel_n = np.zeros(n, dtype=int)
    consec_opm_expand_n = np.zeros(n, dtype=int)
    consec_gm_sga_expand_n = np.zeros(n, dtype=int)
    consec_double_inflect_n = np.zeros(n, dtype=int)
    turnaround_to_profit_1q = np.zeros(n, dtype=bool)

    rev_yoy_lag1 = np.full(n, np.nan)
    rev_yoy_lag2 = np.full(n, np.nan)
    rev_yoy_lag3 = np.full(n, np.nan)
    opm_q_lag1 = np.full(n, np.nan)
    opm_q_lag2 = np.full(n, np.nan)
    opm_q_lag3 = np.full(n, np.nan)
    roic_ttm_lag4 = np.full(n, np.nan)

    for i in range(n):
        # Lags: 1Q, 2Q, 3Q prior (checking ~91*k days continuity)
        curr_e = df.loc[i, "end_dt_obj"]
        
        # lag 1
        idx_1 = None
        for k in range(i - 1, -1, -1):
            if 70 <= (curr_e - df.loc[k, "end_dt_obj"]).days <= 115:
                idx_1 = k
                break
        if idx_1 is not None:
            rev_yoy_lag1[i] = df.loc[idx_1, "rev_yoy"]
            opm_q_lag1[i] = df.loc[idx_1, "opm_q"]
            if pd.notna(df.loc[i, "rev_yoy"]) and pd.notna(df.loc[idx_1, "rev_yoy"]):
                rev_accel_1q[i] = df.loc[i, "rev_yoy"] - df.loc[idx_1, "rev_yoy"]
            # Turnaround to profit
            p_op = df.loc[idx_1, "opinc"]
            p_ni = df.loc[idx_1, "ni"]
            c_op = df.loc[i, "opinc"]
            c_ni = df.loc[i, "ni"]
            if ((pd.notna(p_op) and p_op <= 0) or (pd.notna(p_ni) and p_ni <= 0)) and \
               ((pd.notna(c_op) and c_op > 0) and (pd.notna(c_ni) and c_ni > 0)):
                turnaround_to_profit_1q[i] = True

            # lag 2
            idx_2 = None
            for k in range(idx_1 - 1, -1, -1):
                if 70 <= (df.loc[idx_1, "end_dt_obj"] - df.loc[k, "end_dt_obj"]).days <= 115:
                    idx_2 = k
                    break
            if idx_2 is not None:
                rev_yoy_lag2[i] = df.loc[idx_2, "rev_yoy"]
                opm_q_lag2[i] = df.loc[idx_2, "opm_q"]

                # lag 3
                idx_3 = None
                for k in range(idx_2 - 1, -1, -1):
                    if 70 <= (df.loc[idx_2, "end_dt_obj"] - df.loc[k, "end_dt_obj"]).days <= 115:
                        idx_3 = k
                        break
                if idx_3 is not None:
                    rev_yoy_lag3[i] = df.loc[idx_3, "rev_yoy"]
                    opm_q_lag3[i] = df.loc[idx_3, "opm_q"]

        # roic_ttm_lag4 (~365d prior)
        for k in range(i - 1, -1, -1):
            if 340 <= (curr_e - df.loc[k, "end_dt_obj"]).days <= 390:
                roic_ttm_lag4[i] = df.loc[k, "roic_ttm"]
                break

        # Consecutive streaks
        # consec_rev_accel_n: count backwards consecutive quarters where rev_accel > 0
        c_accel = 0
        curr_step = i
        while True:
            # find immediate prior step
            p_step = None
            for k in range(curr_step - 1, -1, -1):
                if 70 <= (df.loc[curr_step, "end_dt_obj"] - df.loc[k, "end_dt_obj"]).days <= 115:
                    p_step = k
                    break
            if p_step is None:
                break
            yoy_curr = df.loc[curr_step, "rev_yoy"]
            yoy_prev = df.loc[p_step, "rev_yoy"]
            if pd.notna(yoy_curr) and pd.notna(yoy_prev) and yoy_curr > yoy_prev:
                c_accel += 1
                curr_step = p_step
            else:
                break
        consec_rev_accel_n[i] = c_accel

        # consec_opm_expand_n
        c_opm = 0
        curr_step = i
        while True:
            p_step = None
            for k in range(curr_step - 1, -1, -1):
                if 70 <= (df.loc[curr_step, "end_dt_obj"] - df.loc[k, "end_dt_obj"]).days <= 115:
                    p_step = k
                    break
            if p_step is None:
                break
            opm_curr = df.loc[curr_step, "opm_q"]
            opm_prev = df.loc[p_step, "opm_q"]
            if pd.notna(opm_curr) and pd.notna(opm_prev) and opm_curr > opm_prev:
                c_opm += 1
                curr_step = p_step
            else:
                break
        consec_opm_expand_n[i] = c_opm

        # consec_gm_sga_expand_n
        c_gmsga = 0
        curr_step = i
        while True:
            p_step = None
            for k in range(curr_step - 1, -1, -1):
                if 70 <= (df.loc[curr_step, "end_dt_obj"] - df.loc[k, "end_dt_obj"]).days <= 115:
                    p_step = k
                    break
            if p_step is None:
                break
            v_curr = df.loc[curr_step, "gm_minus_sga_q"]
            v_prev = df.loc[p_step, "gm_minus_sga_q"]
            if pd.notna(v_curr) and pd.notna(v_prev) and v_curr > v_prev:
                c_gmsga += 1
                curr_step = p_step
            else:
                break
        consec_gm_sga_expand_n[i] = c_gmsga

        # consec_double_inflect_n: BOTH rev_accel > 0 and opm_expand > 0
        c_double = 0
        curr_step = i
        while True:
            p_step = None
            for k in range(curr_step - 1, -1, -1):
                if 70 <= (df.loc[curr_step, "end_dt_obj"] - df.loc[k, "end_dt_obj"]).days <= 115:
                    p_step = k
                    break
            if p_step is None:
                break
            yoy_curr = df.loc[curr_step, "rev_yoy"]
            yoy_prev = df.loc[p_step, "rev_yoy"]
            opm_curr = df.loc[curr_step, "opm_q"]
            opm_prev = df.loc[p_step, "opm_q"]
            if pd.notna(yoy_curr) and pd.notna(yoy_prev) and yoy_curr > yoy_prev and \
               pd.notna(opm_curr) and pd.notna(opm_prev) and opm_curr > opm_prev:
                c_double += 1
                curr_step = p_step
            else:
                break
        consec_double_inflect_n[i] = c_double

    df["rev_accel_1q"] = rev_accel_1q
    df["consec_rev_accel_n"] = consec_rev_accel_n
    df["consec_opm_expand_n"] = consec_opm_expand_n
    df["consec_gm_sga_expand_n"] = consec_gm_sga_expand_n
    df["consec_double_inflect_n"] = consec_double_inflect_n
    df["turnaround_to_profit_1q"] = turnaround_to_profit_1q

    df["rev_yoy_lag1"] = rev_yoy_lag1
    df["rev_yoy_lag2"] = rev_yoy_lag2
    df["rev_yoy_lag3"] = rev_yoy_lag3
    df["opm_q_lag1"] = opm_q_lag1
    df["opm_q_lag2"] = opm_q_lag2
    df["opm_q_lag3"] = opm_q_lag3
    df["roic_ttm_lag4"] = roic_ttm_lag4

    # Drop temporary datetime helper columns
    df = df.drop(columns=["end_dt_obj", "filed_dt_obj"])
    return df.to_dict(orient="records")

def worker_task(batch_items, zip_path):
    results = []
    for item in batch_items:
        cik = item["cik"]
        ticker = item["ticker"]
        name = item.get("name", ticker)
        records = process_company_pit(cik, ticker, name, zip_path)
        if records:
            results.extend(records)
    return results

def main():
    print(f"[{datetime.now().isoformat()}] W1_06 Shard 3 PIT Panel Extractor Starting...")
    os.makedirs(OUT_DIR, exist_ok=True)

    # 1. Wait for companyfacts.zip to be fully available
    zip_path = None
    for attempt in range(60):
        zp = get_valid_zip_path()
        if zp:
            # Also check if curl is actively writing to it
            try:
                with zipfile.ZipFile(zp, "r") as zf:
                    n_files = len(zf.namelist())
                    if n_files > 15000:
                        zip_path = zp
                        print(f"Valid zip archive verified at {zip_path} with {n_files} files.")
                        break
            except Exception:
                pass
        print(f"Waiting for companyfacts.zip to finish downloading/ready (attempt {attempt+1}/60)...")
        time.sleep(5)

    if not zip_path:
        print("ERROR: companyfacts.zip could not be found or opened after timeout.")
        sys.exit(1)

    # 2. Load Shard 3 companies
    with open(SHARD_PATH, "r") as f:
        shard_data = json.load(f)
    print(f"Loaded {len(shard_data)} companies from {SHARD_PATH}.")

    # 3. Parallel extraction across batches
    n_workers = min(8, os.cpu_count() or 4)
    batch_size = max(1, len(shard_data) // (n_workers * 2))
    batches = [shard_data[i:i + batch_size] for i in range(0, len(shard_data), batch_size)]
    print(f"Dispatched {len(batches)} batches across {n_workers} worker processes...")

    all_records = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = {executor.submit(worker_task, b, zip_path): idx for idx, b in enumerate(batches)}
        completed = 0
        for fut in as_completed(futures):
            res = fut.result()
            all_records.extend(res)
            completed += 1
            if completed % 5 == 0 or completed == len(batches):
                print(f"Completed {completed}/{len(batches)} batches ({len(all_records):,} rows extracted so far)...")

    elapsed = time.time() - t0
    print(f"Extraction completed in {elapsed:.1f}s. Total rows: {len(all_records):,}")

    if not all_records:
        print("ERROR: No records were extracted!")
        sys.exit(1)

    # 4. Create and write final parquet
    df_final = pd.DataFrame(all_records)

    # Verification checks
    n_tickers = df_final["ticker"].nunique()
    earliest_filed = df_final["filed_date"].min()
    latest_filed = df_final["filed_date"].max()
    print("\n--- FINAL VERIFICATION ---")
    print(f"Total Rows: {len(df_final):,}")
    print(f"Unique Tickers: {n_tickers} / {len(shard_data)}")
    print(f"Earliest Filed Date: {earliest_filed}")
    print(f"Latest Filed Date: {latest_filed}")

    # Lookahead bias verification: verify filed_date >= end_date strictly
    df_final["_end_dt"] = pd.to_datetime(df_final["end_date"])
    df_final["_filed_dt"] = pd.to_datetime(df_final["filed_date"])
    lookahead_violations = (df_final["_filed_dt"] < df_final["_end_dt"]).sum()
    lag_violations = ((df_final["_filed_dt"] - df_final["_end_dt"]).dt.days > 130).sum()
    df_final = df_final.drop(columns=["_end_dt", "_filed_dt"])

    print(f"Lookahead violations (filed < end): {lookahead_violations} (MUST BE 0)")
    print(f"Lag violations (lag > 130 days): {lag_violations} (MUST BE 0)")

    if lookahead_violations > 0 or lag_violations > 0:
        print("ERROR: Integrity verification failed!")
        sys.exit(1)

    # Write parquet
    table = pa.Table.from_pandas(df_final)
    pq.write_table(table, OUT_PARQUET, compression="snappy")
    print(f"Successfully saved output to: {OUT_PARQUET}")
    print(f"Output file size: {os.path.getsize(OUT_PARQUET) / (1024*1024):.2f} MB")

if __name__ == "__main__":
    main()
