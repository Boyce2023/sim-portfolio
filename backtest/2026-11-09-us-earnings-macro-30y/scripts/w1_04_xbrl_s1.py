#!/usr/bin/env python3
"""
W1_04: SEC XBRL Point-in-Time (PIT) Quarterly Financials & Trajectory Panel Extractor (Shard 1)
---------------------------------------------------------------------------------------------
Shard: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/shards/xbrl_shard_1.json
Output: /tmp/us_earn_macro_bt_20261109/sec_xbrl_shards/xbrl_pit_shard_1.parquet

Core Invariants:
1. 100% Zero Future Information / Zero Leakage (PIT).
2. Form in {'10-Q', '10-K', '10-Q/A', '10-K/A'}.
3. 0 < (filed - end).days <= 130 filter. No comparative periods or restatements filed years later.
4. For same period/duration, sort by (tag_priority, filed_date asc) -> earliest filing date & original value.
5. Q4 single-quarter derivation: FY - (Q1 + Q2 + Q3) when direct 10-K single quarter missing.
6. Cash flows: OCF & Capex single-quarter via contemporaneous YTD differencing.
7. Derived TTM, single quarter margins, capital return, YoY changes, and multi-quarter trajectory features.
"""

import os
import sys
import json
import time
import zipfile
import datetime
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# ---------------------------------------------------------------------------
# Path Configuration
# ---------------------------------------------------------------------------
PROJECT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
SHARD_FILE = os.path.join(PROJECT_DIR, "shards", "xbrl_shard_1.json")
OUTPUT_DIR = "/tmp/us_earn_macro_bt_20261109/sec_xbrl_shards"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "xbrl_pit_shard_1.parquet")

CANDIDATE_ZIPS = [
    "/tmp/us_earn_macro_bt_20261109/companyfacts.zip",
    "/tmp/us_xuangu_20261109/w1_a3/companyfacts.zip",
]

# ---------------------------------------------------------------------------
# Tag Definitions in Priority Order
# ---------------------------------------------------------------------------
TAGS_REV = [
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

TAGS_GP = ["GrossProfit"]

TAGS_COR = [
    "CostOfGoodsAndServicesSold",
    "CostOfRevenue",
    "CostOfGoodsSold",
    "CostOfServices"
]

TAGS_OPINC = [
    "OperatingIncomeLoss",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"
]

TAGS_NI = [
    "NetIncomeLoss",
    "ProfitLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic"
]

TAGS_RD = [
    "ResearchAndDevelopmentExpense",
    "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"
]

TAGS_SGA_DIRECT = [
    "SellingGeneralAndAdministrativeExpense",
    "GeneralAndAdministrativeExpense"
]

TAGS_SBC = [
    "ShareBasedCompensation",
    "AllocatedShareBasedCompensationExpense"
]

TAGS_OCF = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"
]

TAGS_CAPEX = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets"
]

# Balance sheet instant tags
TAGS_ASSETS = ["Assets"]

TAGS_CASH = [
    "CashCashEquivalentsAndShortTermInvestments",
    "CashAndCashEquivalentsAtCarryingValue"
]

TAGS_EQUITY = [
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
]

TAGS_DEBT_LT = [
    "LongTermDebtNoncurrent",
    "LongTermDebt",
    "LongTermDebtAndCapitalLeaseObligations"
]

TAGS_DEBT_ST = [
    "ShortTermBorrowings",
    "LongTermDebtCurrent",
    "DebtCurrent"
]

TAGS_SHARES_DILUTED = ["WeightedAverageNumberOfDilutedSharesOutstanding"]
TAGS_SHARES_BASIC = ["WeightedAverageNumberOfSharesOutstandingBasic"]
TAGS_SHARES_COMMON = ["CommonStockSharesOutstanding"]
TAGS_SHARES_DEI = ["EntityCommonStockSharesOutstanding"]

VALID_FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}


def parse_date(s):
    """Fast parse YYYY-MM-DD into datetime.date."""
    try:
        return datetime.date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except Exception:
        return None


def get_available_zip():
    """Find valid and ready companyfacts.zip."""
    for p in CANDIDATE_ZIPS:
        if os.path.exists(p) and os.path.getsize(p) > 100_000_000:
            try:
                with zipfile.ZipFile(p, "r") as zf:
                    # Test reading central directory
                    _ = zf.namelist()[:5]
                return p
            except Exception:
                pass
    return None


def wait_for_zip():
    """Wait if zip is actively being downloaded."""
    print("Waiting for companyfacts.zip to be fully available and valid...")
    for _ in range(60):
        zp = get_available_zip()
        if zp:
            # Check if file size is still changing
            sz1 = os.path.getsize(zp)
            time.sleep(2)
            sz2 = os.path.getsize(zp)
            if sz1 == sz2 and sz2 > 1_000_000_000:
                print(f"Verified ready zip: {zp} ({sz2 / (1024*1024):.1f} MB)")
                return zp
            else:
                print(f"Zip downloading: {sz2 / (1024*1024):.1f} MB...")
        else:
            time.sleep(3)
    raise RuntimeError("Timed out waiting for companyfacts.zip!")


def extract_flow_facts(us_gaap, tag_list):
    """
    Extract flow facts for a given list of synonymous tags.
    Returns dict: (end_dt, dur_type) -> (val, filed_dt, tag, prio, form, start_dt)
    dur_type: 1 (70-110d 1Q), 2 (165-200d 2Q/6M), 3 (255-295d 3Q/9M), 4 (345-385d FY)
    """
    records = []
    for prio, tag in enumerate(tag_list):
        node = us_gaap.get(tag)
        if not node:
            continue
        arr = node.get("units", {}).get("USD", [])
        if not arr:
            continue
        for item in arr:
            form = item.get("form")
            if form not in VALID_FORMS:
                continue
            s_str = item.get("start")
            e_str = item.get("end")
            f_str = item.get("filed")
            val = item.get("val")
            if not (s_str and e_str and f_str and val is not None):
                continue
            
            s_dt = parse_date(s_str)
            e_dt = parse_date(e_str)
            f_dt = parse_date(f_str)
            if not (s_dt and e_dt and f_dt):
                continue

            # Core PIT filter: 0 < (filed - end).days <= 130
            lag = (f_dt - e_dt).days
            if lag <= 0 or lag > 130:
                continue

            dur = (e_dt - s_dt).days
            if 70 <= dur <= 110:
                dt = 1
            elif 165 <= dur <= 200:
                dt = 2
            elif 255 <= dur <= 295:
                dt = 3
            elif 345 <= dur <= 385:
                dt = 4
            else:
                continue

            records.append((e_dt, dt, prio, f_dt, float(val), tag, form, s_dt))

    if not records:
        return {}

    # Sort by (end_dt, dt, prio, f_dt): lowest tag priority, earliest filed
    records.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

    best = {}
    for e_dt, dt, prio, f_dt, val, tag, form, s_dt in records:
        key = (e_dt, dt)
        if key not in best:
            best[key] = (val, f_dt, tag, prio, form, s_dt)

    return best


def extract_sga_facts(us_gaap):
    """
    Extract SGA:
    Priority 1: SellingGeneralAndAdministrativeExpense
    Priority 2: GeneralAndAdministrativeExpense
    Fallback: SellingAndMarketingExpense + GeneralAndAdministrativeExpense
    """
    direct = extract_flow_facts(us_gaap, TAGS_SGA_DIRECT)
    
    # Check fallback SM + GA if direct is missing for certain quarters
    sm_facts = extract_flow_facts(us_gaap, ["SellingAndMarketingExpense", "MarketingAndAdvertisingExpense"])
    ga_facts = extract_flow_facts(us_gaap, ["GeneralAndAdministrativeExpense"])

    combined = dict(direct)
    all_keys = set(list(sm_facts.keys()) + list(ga_facts.keys()))
    for key in all_keys:
        if key not in combined:
            if key in sm_facts and key in ga_facts:
                v_sm, f_sm, t_sm, p_sm, form_sm, s_sm = sm_facts[key]
                v_ga, f_ga, t_ga, p_ga, form_ga, s_ga = ga_facts[key]
                combined[key] = (v_sm + v_ga, max(f_sm, f_ga), "SM+GA", 99, form_sm, s_sm)
            elif key in ga_facts:
                combined[key] = ga_facts[key]

    return combined


def build_single_quarter_series(flow_dict):
    """
    From flow_dict: (end_dt, dur_type) -> (val, f_dt, tag, prio, form, s_dt),
    derive single-quarter map: end_dt -> (val, f_dt, tag, form, s_dt).
    Imputes Q4 = FY - (Q1 + Q2 + Q3) if direct Q4 is missing.
    """
    q_map = {}
    # 1. Direct 1Q
    for (e_dt, dt), item in flow_dict.items():
        if dt == 1:
            val, f_dt, tag, prio, form, s_dt = item
            q_map[e_dt] = (val, f_dt, tag, form, s_dt)

    # 2. Q4 derivation from FY (dt=4)
    fy_items = [(e_dt, item) for (e_dt, dt), item in flow_dict.items() if dt == 4]
    fy_items.sort(key=lambda x: x[0])

    for e_fy, (fy_val, fy_f_dt, fy_tag, fy_prio, fy_form, fy_s_dt) in fy_items:
        if e_fy in q_map:
            continue
        # Find Q1, Q2, Q3: end dates in (e_fy - 310d, e_fy - 60d) and filed <= fy_f_dt
        cands = [
            (e_q, q_map[e_q]) for e_q in q_map 
            if (e_fy - datetime.timedelta(days=310)) <= e_q <= (e_fy - datetime.timedelta(days=60))
            and q_map[e_q][1] <= fy_f_dt
        ]
        cands.sort(key=lambda x: x[0])
        if len(cands) >= 3:
            # Pick 3 non-overlapping quarters spaced ~90 days apart
            selected = [cands[-1]]
            for prev_e, prev_item in reversed(cands[:-1]):
                gap = (selected[-1][0] - prev_e).days
                if 70 <= gap <= 115:
                    selected.append((prev_e, prev_item))
                    if len(selected) == 3:
                        break
            if len(selected) == 3:
                selected.reverse()
                q1_3_sum = sum(item[1][0] for item in selected)
                q4_val = fy_val - q1_3_sum
                # Q4 filed date = FY filed date
                q_map[e_fy] = (q4_val, fy_f_dt, f"{fy_tag}_imputed_Q4", "10-K", selected[-1][0])

    return q_map


def build_cash_flow_single_quarters(cf_flow_dict, is_capex=False):
    """
    Reconstruct single-quarter cash flows (OCF and Capex).
    In 10-Q, cash flows are typically reported cumulative YTD:
    Q1: dt=1
    Q2: dt=2 (6M YTD)
    Q3: dt=3 (9M YTD)
    Q4/FY: dt=4 (12M FY)
    Deduce:
    Q2 = YTD_6M - Q1
    Q3 = YTD_9M - YTD_6M (or YTD_9M - Q1 - Q2)
    Q4 = FY - YTD_9M (or FY - Q1 - Q2 - Q3)
    Strictly using filed <= curr.filed!
    """
    q_map = {}
    # Direct 1Q
    for (e_dt, dt), item in cf_flow_dict.items():
        if dt == 1:
            val, f_dt, tag, prio, form, s_dt = item
            v = abs(val) if is_capex else val
            q_map[e_dt] = (v, f_dt, tag, form, s_dt)

    # All YTD items sorted
    ytd_items = sorted(
        [(e_dt, dt, item) for (e_dt, dt), item in cf_flow_dict.items() if dt in (2, 3, 4)],
        key=lambda x: (x[0], x[1])
    )

    for e_dt, dt, (val, f_dt, tag, prio, form, s_dt) in ytd_items:
        v_ytd = abs(val) if is_capex else val
        if e_dt in q_map:
            continue

        if dt == 2:
            # Look for Q1 ending ~91 days earlier (65-115d) with same start (within 10 days) and filed <= f_dt
            q1_cands = [
                (k, v) for k, v in q_map.items() 
                if 65 <= (e_dt - k).days <= 115 and v[1] <= f_dt
            ]
            if len(q1_cands) == 1:
                q_map[e_dt] = (v_ytd - q1_cands[0][1][0], f_dt, f"{tag}_from_6M", form, q1_cands[0][0])

        elif dt == 3:
            # Look for 6M YTD with filed <= f_dt
            m6_cands = [
                (e2, item2) for (e2, dt2, item2) in ytd_items 
                if dt2 == 2 and 65 <= (e_dt - e2).days <= 115 and item2[1] <= f_dt
            ]
            if m6_cands:
                v6 = abs(m6_cands[0][1][0]) if is_capex else m6_cands[0][1][0]
                q_map[e_dt] = (v_ytd - v6, f_dt, f"{tag}_from_9M_sub_6M", form, m6_cands[0][0])
            else:
                # Look for Q1 and Q2 in q_map
                qs = [
                    (k, v) for k, v in q_map.items() 
                    if (e_dt - datetime.timedelta(days=220)) <= k <= (e_dt - datetime.timedelta(days=65))
                    and v[1] <= f_dt
                ]
                qs.sort(key=lambda x: x[0])
                if len(qs) == 2 and 70 <= (qs[1][0] - qs[0][0]).days <= 115:
                    q_map[e_dt] = (v_ytd - (qs[0][1][0] + qs[1][1][0]), f_dt, f"{tag}_from_9M_sub_Q1_Q2", form, qs[1][0])

        elif dt == 4:
            # Look for 9M YTD with filed <= f_dt
            m9_cands = [
                (e3, item3) for (e3, dt3, item3) in ytd_items 
                if dt3 == 3 and 65 <= (e_dt - e3).days <= 115 and item3[1] <= f_dt
            ]
            if m9_cands:
                v9 = abs(m9_cands[0][1][0]) if is_capex else m9_cands[0][1][0]
                q_map[e_dt] = (v_ytd - v9, f_dt, f"{tag}_from_FY_sub_9M", form, m9_cands[0][0])
            else:
                qs = [
                    (k, v) for k, v in q_map.items() 
                    if (e_dt - datetime.timedelta(days=310)) <= k <= (e_dt - datetime.timedelta(days=65))
                    and v[1] <= f_dt
                ]
                qs.sort(key=lambda x: x[0])
                if len(qs) >= 3:
                    selected = [qs[-1]]
                    for prev_k, prev_v in reversed(qs[:-1]):
                        if 70 <= (selected[-1][0] - prev_k).days <= 115:
                            selected.append((prev_k, prev_v))
                            if len(selected) == 3:
                                break
                    if len(selected) == 3:
                        sum3 = sum(x[1][0] for x in selected)
                        q_map[e_dt] = (v_ytd - sum3, f_dt, f"{tag}_from_FY_sub_3Q", form, selected[-1][0])

    return q_map


def extract_instant_facts(us_gaap, tag_list):
    """
    Extract instant (balance sheet) items.
    Returns dict: end_dt -> (val, filed_dt, tag, prio, form)
    Sorted by tag priority, then earliest filed_dt.
    """
    records = []
    for prio, tag in enumerate(tag_list):
        node = us_gaap.get(tag)
        if not node:
            continue
        arr = node.get("units", {}).get("USD", [])
        if not arr:
            continue
        for item in arr:
            form = item.get("form")
            if form not in VALID_FORMS:
                continue
            e_str = item.get("end")
            f_str = item.get("filed")
            val = item.get("val")
            if not (e_str and f_str and val is not None):
                continue
            e_dt = parse_date(e_str)
            f_dt = parse_date(f_str)
            if not (e_dt and f_dt):
                continue
            lag = (f_dt - e_dt).days
            if lag <= 0 or lag > 130:
                continue
            records.append((e_dt, prio, f_dt, float(val), tag, form))

    if not records:
        return {}

    records.sort(key=lambda x: (x[0], x[1], x[2]))
    best = {}
    for e_dt, prio, f_dt, val, tag, form in records:
        if e_dt not in best:
            best[e_dt] = (val, f_dt, tag, prio, form)
    return best


def extract_shares_facts(us_gaap, dei):
    """
    Extract shares in priority order:
    1. WeightedAverageNumberOfDilutedSharesOutstanding (us-gaap)
    2. WeightedAverageNumberOfSharesOutstandingBasic (us-gaap)
    3. CommonStockSharesOutstanding (us-gaap)
    4. EntityCommonStockSharesOutstanding (dei)
    Returns dict: end_dt -> (val, filed_dt, tag, prio, form)
    """
    records = []
    
    # Priority 0: Diluted
    for tag, prio in [
        ("WeightedAverageNumberOfDilutedSharesOutstanding", 0),
        ("WeightedAverageNumberOfSharesOutstandingBasic", 1),
        ("CommonStockSharesOutstanding", 2)
    ]:
        node = us_gaap.get(tag)
        if not node:
            continue
        for unit_name, arr in node.get("units", {}).items():
            if unit_name not in ("shares", "pure"):
                continue
            for item in arr:
                form = item.get("form")
                if form not in VALID_FORMS:
                    continue
                e_str = item.get("end")
                f_str = item.get("filed")
                val = item.get("val")
                if not (e_str and f_str and val is not None and float(val) > 0):
                    continue
                e_dt = parse_date(e_str)
                f_dt = parse_date(f_str)
                if not (e_dt and f_dt):
                    continue
                lag = (f_dt - e_dt).days
                if lag <= 0 or lag > 130:
                    continue
                # If duration exists, prefer ~1Q or FY
                s_str = item.get("start")
                if s_str:
                    s_dt = parse_date(s_str)
                    if s_dt:
                        dur = (e_dt - s_dt).days
                        if not (65 <= dur <= 120 or 340 <= dur <= 390):
                            continue
                records.append((e_dt, prio, f_dt, float(val), tag, form))

    # Priority 3: dei EntityCommonStockSharesOutstanding
    if "EntityCommonStockSharesOutstanding" in dei:
        arr = dei["EntityCommonStockSharesOutstanding"].get("units", {}).get("shares", [])
        for item in arr:
            form = item.get("form")
            if form not in VALID_FORMS:
                continue
            e_str = item.get("end")
            f_str = item.get("filed")
            val = item.get("val")
            if not (e_str and f_str and val is not None and float(val) > 0):
                continue
            e_dt = parse_date(e_str)
            f_dt = parse_date(f_str)
            if not (e_dt and f_dt):
                continue
            lag = (f_dt - e_dt).days
            if lag <= 0 or lag > 130:
                continue
            records.append((e_dt, 3, f_dt, float(val), "dei_shares", form))

    if not records:
        return {}

    records.sort(key=lambda x: (x[0], x[1], x[2]))
    best = {}
    for e_dt, prio, f_dt, val, tag, form in records:
        if e_dt not in best:
            best[e_dt] = (val, f_dt, tag, prio, form)
    return best


def parse_company(cik, ticker, name, zf):
    """
    Extract PIT quarterly series and trajectory features for one company.
    Returns list of record dictionaries.
    """
    fname = f"CIK{cik:010d}.json"
    try:
        raw_bytes = zf.read(fname)
        data = json.loads(raw_bytes)
    except Exception:
        return []

    facts = data.get("facts", {})
    us_gaap = facts.get("us-gaap", {})
    dei = facts.get("dei", {})
    if not us_gaap:
        return []

    # 1. Extract raw flow facts
    f_rev = extract_flow_facts(us_gaap, TAGS_REV)
    if not f_rev:
        return []

    f_gp = extract_flow_facts(us_gaap, TAGS_GP)
    f_cor = extract_flow_facts(us_gaap, TAGS_COR)
    f_opinc = extract_flow_facts(us_gaap, TAGS_OPINC)
    f_ni = extract_flow_facts(us_gaap, TAGS_NI)
    f_rd = extract_flow_facts(us_gaap, TAGS_RD)
    f_sga = extract_sga_facts(us_gaap)
    f_sbc = extract_flow_facts(us_gaap, TAGS_SBC)
    f_ocf = extract_flow_facts(us_gaap, TAGS_OCF)
    f_capex = extract_flow_facts(us_gaap, TAGS_CAPEX)

    # 2. Derive single quarter flow series
    q_rev = build_single_quarter_series(f_rev)
    if not q_rev:
        return []

    q_gp = build_single_quarter_series(f_gp)
    q_cor = build_single_quarter_series(f_cor)
    q_opinc = build_single_quarter_series(f_opinc)
    q_ni = build_single_quarter_series(f_ni)
    q_rd = build_single_quarter_series(f_rd)
    q_sga = build_single_quarter_series(f_sga)
    q_sbc = build_single_quarter_series(f_sbc)
    q_ocf = build_cash_flow_single_quarters(f_ocf, is_capex=False)
    q_capex = build_cash_flow_single_quarters(f_capex, is_capex=True)

    # 3. Balance sheet & instant facts
    inst_assets = extract_instant_facts(us_gaap, TAGS_ASSETS)
    inst_cash = extract_instant_facts(us_gaap, TAGS_CASH)
    inst_equity = extract_instant_facts(us_gaap, TAGS_EQUITY)
    inst_debt_lt = extract_instant_facts(us_gaap, TAGS_DEBT_LT)
    inst_debt_st = extract_instant_facts(us_gaap, TAGS_DEBT_ST)
    inst_shares = extract_shares_facts(us_gaap, dei)

    # 4. Form chronological quarterly events
    # An event is anchored at each quarter end date where revenue is known
    sorted_ends = sorted(q_rev.keys())
    clean_ends = []
    for e_dt in sorted_ends:
        if clean_ends and (e_dt - clean_ends[-1]).days < 45:
            # Minor shift (e.g. 52/53-week), keep earlier
            continue
        clean_ends.append(e_dt)

    # Pre-build quarterly structures for fast lookup
    # dict: end_dt -> dict of single-quarter values
    quarter_data = {}
    for e_dt in clean_ends:
        rev_val, rev_f_dt, rev_tag, rev_form, _ = q_rev[e_dt]

        # Gross profit fallback: rev - cor
        if e_dt in q_gp:
            gp_val = q_gp[e_dt][0]
        elif e_dt in q_cor and rev_val is not None:
            gp_val = rev_val - q_cor[e_dt][0]
        else:
            gp_val = np.nan

        cor_val = q_cor[e_dt][0] if e_dt in q_cor else np.nan

        # OpInc and flag
        if e_dt in q_opinc:
            opinc_val = q_opinc[e_dt][0]
            opinc_tag = q_opinc[e_dt][2]
            opinc_is_ebt = bool("ContinuingOperations" in opinc_tag)
        else:
            opinc_val = np.nan
            opinc_is_ebt = False

        ni_val = q_ni[e_dt][0] if e_dt in q_ni else np.nan
        rd_val = q_rd[e_dt][0] if e_dt in q_rd else np.nan
        sga_val = q_sga[e_dt][0] if e_dt in q_sga else np.nan
        sbc_val = q_sbc[e_dt][0] if e_dt in q_sbc else np.nan
        ocf_val = q_ocf[e_dt][0] if e_dt in q_ocf else np.nan
        capex_val = q_capex[e_dt][0] if e_dt in q_capex else np.nan

        # Balance sheet instants matching e_dt (or within 15 days)
        def get_instant(inst_dict):
            if e_dt in inst_dict:
                return inst_dict[e_dt][0]
            for d in range(-15, 16):
                cand = e_dt + datetime.timedelta(days=d)
                if cand in inst_dict:
                    return inst_dict[cand][0]
            return np.nan

        assets_val = get_instant(inst_assets)
        cash_val = get_instant(inst_cash)
        equity_val = get_instant(inst_equity)
        debt_lt_val = get_instant(inst_debt_lt)
        debt_st_val = get_instant(inst_debt_st)
        shares_val = get_instant(inst_shares)

        quarter_data[e_dt] = {
            "filed_date": rev_f_dt,
            "form": rev_form,
            "rev_q": rev_val,
            "gp_q": gp_val,
            "cor_q": cor_val,
            "opinc_q": opinc_val,
            "opinc_is_ebt": opinc_is_ebt,
            "ni_q": ni_val,
            "rd_q": rd_val,
            "sga_q": sga_val,
            "sbc_q": sbc_val,
            "ocf_q": ocf_val,
            "capex_q": capex_val,
            "assets": assets_val,
            "cash": cash_val,
            "equity": equity_val,
            "debt_lt": debt_lt_val,
            "debt_st": debt_st_val,
            "shares": shares_val,
        }

    # 5. Build full PIT panel with derived and trajectory features
    rows = []
    for i, e_dt in enumerate(clean_ends):
        qd = quarter_data[e_dt]
        f_dt = qd["filed_date"]

        # Find historical quarters available at this filing point:
        # Strictly: past_end < e_dt AND past_filed <= f_dt
        avail_past = [
            (prev_e, quarter_data[prev_e]) for prev_e in clean_ends[:i]
            if quarter_data[prev_e]["filed_date"] <= f_dt
        ]

        # Helper to find a quarter roughly k quarters prior (~91*k days)
        def find_prior_quarter(n_q):
            target_days = int(round(91.31 * n_q))
            tol = 18 if n_q <= 4 else 28
            best_diff = 999
            best_item = None
            for prev_e, p_qd in avail_past:
                d = abs((e_dt - prev_e).days - target_days)
                if d <= tol and d < best_diff:
                    best_diff = d
                    best_item = (prev_e, p_qd)
            return best_item

        q_minus1 = find_prior_quarter(1)
        q_minus2 = find_prior_quarter(2)
        q_minus3 = find_prior_quarter(3)
        q_minus4 = find_prior_quarter(4)

        # Single-quarter flow items
        r0 = qd["rev_q"]
        gp0 = qd["gp_q"]
        op0 = qd["opinc_q"]
        ni0 = qd["ni_q"]
        rd0 = qd["rd_q"]
        sga0 = qd["sga_q"]
        sbc0 = qd["sbc_q"]
        ocf0 = qd["ocf_q"]
        cap0 = qd["capex_q"]

        # Margins & ratios for current quarter
        gm_q = (gp0 / r0) if (pd.notna(gp0) and pd.notna(r0) and r0 > 0) else np.nan
        opm_q = (op0 / r0) if (pd.notna(op0) and pd.notna(r0) and r0 > 0) else np.nan
        nm_q = (ni0 / r0) if (pd.notna(ni0) and pd.notna(r0) and r0 > 0) else np.nan
        rd_ratio_q = (rd0 / r0) if (pd.notna(rd0) and pd.notna(r0) and r0 > 0) else np.nan
        sga_ratio_q = (sga0 / r0) if (pd.notna(sga0) and pd.notna(r0) and r0 > 0) else np.nan
        gm_minus_sga_q = (gm_q - sga_ratio_q) if (pd.notna(gm_q) and pd.notna(sga_ratio_q)) else np.nan

        # TTM Sums (requires Q0, Q-1, Q-2, Q-3)
        has_ttm = (q_minus1 is not None and q_minus2 is not None and q_minus3 is not None)
        if has_ttm:
            rev_ttm = r0 + q_minus1[1]["rev_q"] + q_minus2[1]["rev_q"] + q_minus3[1]["rev_q"]
            
            def ttm_sum(field):
                vals = [qd[field], q_minus1[1][field], q_minus2[1][field], q_minus3[1][field]]
                if any(pd.isna(x) for x in vals):
                    return np.nan
                return sum(vals)

            gp_ttm = ttm_sum("gp_q")
            opinc_ttm = ttm_sum("opinc_q")
            ni_ttm = ttm_sum("ni_q")
            ocf_ttm = ttm_sum("ocf_q")
            capex_ttm = ttm_sum("capex_q")
            fcf_ttm = (ocf_ttm - capex_ttm) if (pd.notna(ocf_ttm) and pd.notna(capex_ttm)) else np.nan
            sbc_ttm = ttm_sum("sbc_q")
        else:
            rev_ttm = gp_ttm = opinc_ttm = ni_ttm = ocf_ttm = capex_ttm = fcf_ttm = sbc_ttm = np.nan

        fcf_margin_ttm = (fcf_ttm / rev_ttm) if (pd.notna(fcf_ttm) and pd.notna(rev_ttm) and rev_ttm > 0) else np.nan
        ocf_to_ni_ttm = (ocf_ttm / ni_ttm) if (pd.notna(ocf_ttm) and pd.notna(ni_ttm) and abs(ni_ttm) > 1e-4) else np.nan

        # Balance sheet & Capital metrics
        assets = qd["assets"]
        cash = qd["cash"] if pd.notna(qd["cash"]) else 0.0
        equity = qd["equity"]
        debt_lt = qd["debt_lt"] if pd.notna(qd["debt_lt"]) else 0.0
        debt_st = qd["debt_st"] if pd.notna(qd["debt_st"]) else 0.0
        tot_debt = debt_lt + debt_st
        shares = qd["shares"]

        neg_equity = bool(pd.isna(equity) or equity <= 0 or (pd.notna(assets) and assets > 0 and equity < 0.05 * assets))

        roe_ttm = np.nan
        if pd.notna(ni_ttm) and pd.notna(equity) and not neg_equity:
            roe_ttm = ni_ttm / equity

        # Invested capital: equity + debt - cash, floor at 10% assets
        invested_cap = np.nan
        roic_ttm = np.nan
        if pd.notna(equity):
            raw_ic = equity + tot_debt - cash
            floor_ic = 0.10 * assets if (pd.notna(assets) and assets > 0) else 0.0
            invested_cap = max(raw_ic, floor_ic)
            if invested_cap > 0 and pd.notna(opinc_ttm):
                roic_ttm = (opinc_ttm * 0.79) / invested_cap

        # YoY Comparisons (vs Q-4)
        if q_minus4 is not None:
            q4_d = q_minus4[1]
            r4 = q4_d["rev_q"]
            gp4 = q4_d["gp_q"]
            op4 = q4_d["opinc_q"]
            ni4 = q4_d["ni_q"]
            sh4 = q4_d["shares"]

            rev_yoy = (r0 / r4 - 1.0) if (pd.notna(r0) and pd.notna(r4) and r4 > 0) else np.nan
            gp_yoy = (gp0 / gp4 - 1.0) if (pd.notna(gp0) and pd.notna(gp4) and gp4 > 0) else np.nan

            def calc_profit_yoy(curr, prev):
                if pd.isna(curr) or pd.isna(prev):
                    return np.nan
                if prev > 0:
                    return curr / prev - 1.0
                elif abs(prev) > 1e-4:
                    return (curr - prev) / abs(prev)
                return np.nan

            opinc_yoy = calc_profit_yoy(op0, op4)
            ni_yoy = calc_profit_yoy(ni0, ni4)

            # Prior Q-4 margins
            gm4 = (gp4 / r4) if (pd.notna(gp4) and pd.notna(r4) and r4 > 0) else np.nan
            opm4 = (op4 / r4) if (pd.notna(op4) and pd.notna(r4) and r4 > 0) else np.nan
            sga_ratio4 = (q4_d["sga_q"] / r4) if (pd.notna(q4_d["sga_q"]) and pd.notna(r4) and r4 > 0) else np.nan
            gm_minus_sga4 = (gm4 - sga_ratio4) if (pd.notna(gm4) and pd.notna(sga_ratio4)) else np.nan

            gm_yoy_chg = (gm_q - gm4) if (pd.notna(gm_q) and pd.notna(gm4)) else np.nan
            opm_yoy_chg = (opm_q - opm4) if (pd.notna(opm_q) and pd.notna(opm4)) else np.nan
            gm_sga_yoy_chg = (gm_minus_sga_q - gm_minus_sga4) if (pd.notna(gm_minus_sga_q) and pd.notna(gm_minus_sga4)) else np.nan

            shares_yoy_dilution = (shares / sh4 - 1.0) if (pd.notna(shares) and pd.notna(sh4) and sh4 > 0) else np.nan
            turnaround_to_profit_1q = bool(pd.notna(op0) and op0 > 0 and pd.notna(op4) and op4 <= 0)
        else:
            rev_yoy = gp_yoy = opinc_yoy = ni_yoy = np.nan
            gm_yoy_chg = opm_yoy_chg = gm_sga_yoy_chg = shares_yoy_dilution = np.nan
            turnaround_to_profit_1q = False

        # Lags of YoY and Margins
        # Helper to compute YoY for an earlier quarter
        def get_prior_yoy(pq_tuple):
            if pq_tuple is None:
                return np.nan
            p_e, p_qd = pq_tuple
            p_target = p_e - datetime.timedelta(days=365)
            # Find in clean_ends prior to p_e
            match_yoy = None
            for cand_e in clean_ends:
                if cand_e < p_e and abs((p_e - cand_e).days - 365) <= 25:
                    c_r = quarter_data[cand_e]["rev_q"]
                    if pd.notna(c_r) and c_r > 0 and pd.notna(p_qd["rev_q"]):
                        match_yoy = p_qd["rev_q"] / c_r - 1.0
                    break
            return match_yoy if match_yoy is not None else np.nan

        rev_yoy_lag1 = get_prior_yoy(q_minus1)
        rev_yoy_lag2 = get_prior_yoy(q_minus2)
        rev_yoy_lag3 = get_prior_yoy(q_minus3)

        opm_q_lag1 = (q_minus1[1]["opinc_q"] / q_minus1[1]["rev_q"]) if (q_minus1 and q_minus1[1]["rev_q"] > 0) else np.nan
        opm_q_lag2 = (q_minus2[1]["opinc_q"] / q_minus2[1]["rev_q"]) if (q_minus2 and q_minus2[1]["rev_q"] > 0) else np.nan
        opm_q_lag3 = (q_minus3[1]["opinc_q"] / q_minus3[1]["rev_q"]) if (q_minus3 and q_minus3[1]["rev_q"] > 0) else np.nan

        rev_accel_1q = (rev_yoy - rev_yoy_lag1) if (pd.notna(rev_yoy) and pd.notna(rev_yoy_lag1)) else np.nan

        # Consecutive Acceleration and Expansion Counts
        # Consec Rev Accel
        consec_rev_accel_n = 0
        if pd.notna(rev_yoy) and pd.notna(rev_yoy_lag1) and rev_yoy > rev_yoy_lag1:
            consec_rev_accel_n = 1
            if pd.notna(rev_yoy_lag2) and rev_yoy_lag1 > rev_yoy_lag2:
                consec_rev_accel_n = 2
                if pd.notna(rev_yoy_lag3) and rev_yoy_lag2 > rev_yoy_lag3:
                    consec_rev_accel_n = 3

        # Consec OPM Expand
        consec_opm_expand_n = 0
        if pd.notna(opm_q) and pd.notna(opm_q_lag1) and opm_q > opm_q_lag1:
            consec_opm_expand_n = 1
            if pd.notna(opm_q_lag2) and opm_q_lag1 > opm_q_lag2:
                consec_opm_expand_n = 2
                if pd.notna(opm_q_lag3) and opm_q_lag2 > opm_q_lag3:
                    consec_opm_expand_n = 3

        # Consec GM - SGA Expand
        def get_gm_sga(pq_tuple):
            if pq_tuple is None:
                return np.nan
            d = pq_tuple[1]
            r = d["rev_q"]
            if pd.isna(r) or r <= 0:
                return np.nan
            g = d["gp_q"] / r if pd.notna(d["gp_q"]) else np.nan
            s = d["sga_q"] / r if pd.notna(d["sga_q"]) else np.nan
            return (g - s) if (pd.notna(g) and pd.notna(s)) else np.nan

        gms0 = gm_minus_sga_q
        gms1 = get_gm_sga(q_minus1)
        gms2 = get_gm_sga(q_minus2)
        gms3 = get_gm_sga(q_minus3)

        consec_gm_sga_expand_n = 0
        if pd.notna(gms0) and pd.notna(gms1) and gms0 > gms1:
            consec_gm_sga_expand_n = 1
            if pd.notna(gms2) and gms1 > gms2:
                consec_gm_sga_expand_n = 2
                if pd.notna(gms3) and gms2 > gms3:
                    consec_gm_sga_expand_n = 3

        # Double Inflection: BOTH rev_accel AND opm_expand
        consec_double_inflect_n = 0
        if consec_rev_accel_n >= 1 and consec_opm_expand_n >= 1:
            consec_double_inflect_n = min(consec_rev_accel_n, consec_opm_expand_n)

        # ROIC Lag 4 and change
        # Compute ROIC for Q-4
        roic_ttm_lag4 = np.nan
        if q_minus4 is not None:
            # Check if Q-4 had TTM
            e4 = q_minus4[0]
            # Look at prior 3 quarters before e4
            prior3_for_e4 = [cand_e for cand_e in clean_ends if cand_e < e4 and (e4 - cand_e).days <= 300]
            if len(prior3_for_e4) >= 3:
                p_op_ttm = sum(quarter_data[k]["opinc_q"] for k in [e4] + prior3_for_e4[-3:])
                p_eq = q_minus4[1]["equity"]
                p_d = (q_minus4[1]["debt_lt"] or 0) + (q_minus4[1]["debt_st"] or 0)
                p_c = q_minus4[1]["cash"] or 0
                if pd.notna(p_eq) and p_eq > 0 and pd.notna(p_op_ttm):
                    ic4 = max(p_eq + p_d - p_c, 0.10 * (q_minus4[1]["assets"] or 0))
                    if ic4 > 0:
                        roic_ttm_lag4 = (p_op_ttm * 0.79) / ic4

        roic_yoy_chg = (roic_ttm - roic_ttm_lag4) if (pd.notna(roic_ttm) and pd.notna(roic_ttm_lag4)) else np.nan

        rows.append({
            "ticker": ticker,
            "cik": int(cik),
            "name": name,
            "end_date": str(e_dt),
            "filed_date": str(f_dt),
            "form": qd["form"],
            "fiscal_year": int(e_dt.year),
            "rev_q": r0,
            "gp_q": gp0,
            "cor_q": qd["cor_q"],
            "opinc_q": op0,
            "opinc_is_ebt": qd["opinc_is_ebt"],
            "ni_q": ni0,
            "rd_q": rd0,
            "sga_q": sga0,
            "sbc_q": sbc0,
            "ocf_q": ocf0,
            "capex_q": cap0,
            "assets": assets,
            "cash": cash,
            "equity": equity,
            "debt_lt": debt_lt,
            "debt_st": debt_st,
            "shares": shares,
            # Derived TTM
            "rev_ttm": rev_ttm,
            "gp_ttm": gp_ttm,
            "opinc_ttm": opinc_ttm,
            "ni_ttm": ni_ttm,
            "ocf_ttm": ocf_ttm,
            "capex_ttm": capex_ttm,
            "fcf_ttm": fcf_ttm,
            "sbc_ttm": sbc_ttm,
            # Margins & Ratios
            "gm_q": gm_q,
            "opm_q": opm_q,
            "nm_q": nm_q,
            "rd_ratio_q": rd_ratio_q,
            "sga_ratio_q": sga_ratio_q,
            "gm_minus_sga_q": gm_minus_sga_q,
            "fcf_margin_ttm": fcf_margin_ttm,
            "ocf_to_ni_ttm": ocf_to_ni_ttm,
            # Capital & Returns
            "neg_equity": neg_equity,
            "roe_ttm": roe_ttm,
            "invested_cap": invested_cap,
            "roic_ttm": roic_ttm,
            # YoY Changes
            "rev_yoy": rev_yoy,
            "gp_yoy": gp_yoy,
            "opinc_yoy": opinc_yoy,
            "ni_yoy": ni_yoy,
            "gm_yoy_chg": gm_yoy_chg,
            "opm_yoy_chg": opm_yoy_chg,
            "gm_sga_yoy_chg": gm_sga_yoy_chg,
            "roic_yoy_chg": roic_yoy_chg,
            "shares_yoy_dilution": shares_yoy_dilution,
            # Trajectory & Acceleration
            "rev_accel_1q": rev_accel_1q,
            "consec_rev_accel_n": int(consec_rev_accel_n),
            "consec_opm_expand_n": int(consec_opm_expand_n),
            "consec_gm_sga_expand_n": int(consec_gm_sga_expand_n),
            "consec_double_inflect_n": int(consec_double_inflect_n),
            "turnaround_to_profit_1q": turnaround_to_profit_1q,
            "rev_yoy_lag1": rev_yoy_lag1,
            "rev_yoy_lag2": rev_yoy_lag2,
            "rev_yoy_lag3": rev_yoy_lag3,
            "opm_q_lag1": opm_q_lag1,
            "opm_q_lag2": opm_q_lag2,
            "opm_q_lag3": opm_q_lag3,
            "roic_ttm_lag4": roic_ttm_lag4
        })

    return rows


def main():
    t_start = time.time()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 80)
    print("W1_04: SEC XBRL PIT Panel Extractor (Shard 1)")
    print("=" * 80)

    # 1. Load shard
    print(f"Loading shard 1 from {SHARD_FILE}...")
    with open(SHARD_FILE, "r") as f:
        shard_data = json.load(f)
    print(f"Total companies in shard 1: {len(shard_data)}")

    # 2. Wait for / locate companyfacts.zip
    zip_path = wait_for_zip()

    # 3. Process companies
    print(f"\nProcessing companies from {zip_path}...")
    all_rows = []
    processed_count = 0
    skipped_count = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = set(zf.namelist())
        for idx, item in enumerate(shard_data):
            cik = int(item["cik"])
            ticker = item["ticker"]
            name = item.get("name", ticker)
            fname = f"CIK{cik:010d}.json"

            if fname not in namelist:
                skipped_count += 1
                continue

            try:
                c_rows = parse_company(cik, ticker, name, zf)
                if c_rows:
                    all_rows.extend(c_rows)
                    processed_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                print(f"Warning parsing {ticker} (CIK {cik}): {e}")
                skipped_count += 1

            if (idx + 1) % 50 == 0 or (idx + 1) == len(shard_data):
                elapsed = time.time() - t_start
                print(f"[{idx+1}/{len(shard_data)}] Processed {processed_count} tickers | Total rows: {len(all_rows):,} | Elapsed: {elapsed:.1f}s")

    # 4. Convert to DataFrame and sort
    print(f"\nConstructing DataFrame from {len(all_rows):,} quarterly records...")
    df = pd.DataFrame(all_rows)
    if df.empty:
        raise RuntimeError("No records were extracted! Please check data inputs.")

    df = df.sort_values(["ticker", "end_date", "filed_date"]).reset_index(drop=True)

    # 5. Rigorous Zero-Future-Information and Integrity Audits
    print("\n" + "=" * 80)
    print("RUNNING STRICT PIT ZERO-FUTURE-LEAKAGE INTEGRITY AUDITS")
    print("=" * 80)

    # Audit 1: filed_date > end_date
    df["end_dt_audit"] = pd.to_datetime(df["end_date"])
    df["filed_dt_audit"] = pd.to_datetime(df["filed_date"])
    lag_days = (df["filed_dt_audit"] - df["end_dt_audit"]).dt.days

    violations_future = (lag_days <= 0).sum()
    violations_over130 = (lag_days > 130).sum()
    print(f"Audit 1: filed_date <= end_date violations (future leak): {violations_future} (must be 0)")
    print(f"Audit 2: filed_date > end_date + 130d violations (restatement leak): {violations_over130} (must be 0)")

    if violations_future > 0 or violations_over130 > 0:
        raise ValueError(f"CRITICAL PIT VIOLATION: {violations_future} future dates, {violations_over130} restatement leaks!")

    # Audit 3: Unique (ticker, end_date) pairs
    dups = df.duplicated(subset=["ticker", "end_date"]).sum()
    print(f"Audit 3: Duplicate (ticker, end_date) rows: {dups} (must be 0)")
    if dups > 0:
        print(f"Cleaning {dups} duplicates by taking earliest filed_date...")
        df = df.sort_values(["ticker", "end_date", "filed_date"]).drop_duplicates(subset=["ticker", "end_date"], keep="first").reset_index(drop=True)

    # Clean up temporary audit columns
    df = df.drop(columns=["end_dt_audit", "filed_dt_audit"])

    # 6. Save Parquet
    print(f"\nWriting to {OUTPUT_FILE}...")
    table = pa.Table.from_pandas(df)
    pq.write_table(table, OUTPUT_FILE, compression="zstd")

    file_size_mb = os.path.getsize(OUTPUT_FILE) / (1024 * 1024)
    print(f"Successfully generated {OUTPUT_FILE} ({file_size_mb:.2f} MB)")

    # 7. Print summary statistics
    n_tickers = df["ticker"].nunique()
    earliest_filed = df["filed_date"].min()
    latest_filed = df["filed_date"].max()
    print("\nSummary Statistics:")
    print(f"  Total records: {len(df):,}")
    print(f"  Total unique tickers: {n_tickers}")
    print(f"  Earliest filed date: {earliest_filed}")
    print(f"  Latest filed date: {latest_filed}")
    print(f"  Columns ({len(df.columns)}): {list(df.columns)}")
    print(f"  Execution time: {time.time() - t_start:.1f}s")
    print("=" * 80)


if __name__ == "__main__":
    main()
