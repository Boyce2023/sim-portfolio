#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEC XBRL Zero Lookahead (Point-in-Time) Quarterly Financials & Trajectory Panel Extractor
Shard 2 (w1_05)
Author: W1_05 Subagent
Date: 2026-11-09
"""

import os
import sys
import json
import time
import zipfile
import math
import warnings
from datetime import datetime, date, timedelta

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

warnings.filterwarnings("ignore")

SHARD_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/shards/xbrl_shard_2.json"
ZIP_CANDIDATES = [
    "/tmp/us_earn_macro_bt_20261109/companyfacts.zip",
    "/tmp/us_xuangu_20261109/w1_a3/companyfacts.zip"
]
OUT_DIR = "/tmp/us_earn_macro_bt_20261109/sec_xbrl_shards"
OUT_PARQUET = os.path.join(OUT_DIR, "xbrl_pit_shard_2.parquet")

VALID_FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}

# XBRL Tag Taxonomy
FLOW_TAGS = {
    "rev": [
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
    ],
    "gp": ["GrossProfit"],
    "cor": [
        "CostOfGoodsAndServicesSold",
        "CostOfRevenue",
        "CostOfGoodsSold",
        "CostOfServices"
    ],
    "opinc": [
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"
    ],
    "ni": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic"
    ],
    "rd": [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"
    ],
    "sga": [
        "SellingGeneralAndAdministrativeExpense",
        "GeneralAndAdministrativeExpense"
    ],
    "sm": ["SellingAndMarketingExpense"],
    "ga": ["GeneralAndAdministrativeExpense"],
    "sbc": [
        "ShareBasedCompensation",
        "AllocatedShareBasedCompensationExpense"
    ],
    "ocf": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets"
    ]
}

STOCK_TAGS = {
    "assets": ["Assets"],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
    ],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
    ],
    "debt_lt": [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations"
    ],
    "debt_st": [
        "DebtCurrent",
        "LongTermDebtCurrent",
        "ShortTermBorrowings"
    ]
}

SHARE_FLOW_TAGS = [
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic"
]

SHARE_INSTANT_TAGS = [
    "CommonStockSharesOutstanding"
]


def parse_date(d_str):
    try:
        return datetime.strptime(d_str, "%Y-%m-%d").date()
    except Exception:
        return None


def wait_and_open_zip():
    print("Locating valid companyfacts.zip...")
    for attempt in range(120):
        for z_path in ZIP_CANDIDATES:
            if os.path.exists(z_path) and os.path.getsize(z_path) >= 1400000000:
                try:
                    zf = zipfile.ZipFile(z_path, "r")
                    names = zf.namelist()
                    if len(names) > 10000:
                        print(f"Found complete zip: {z_path} ({os.path.getsize(z_path)/1e6:.1f} MB, {len(names)} files)")
                        return zf, z_path
                except Exception:
                    pass
        if attempt % 5 == 0:
            print(f"  Waiting for companyfacts.zip to complete download (attempt {attempt}/120)...")
        time.sleep(3)
    raise FileNotFoundError("Could not find a complete companyfacts.zip after waiting.")


def extract_raw_flow_records(gaap, tag_list, unit="USD"):
    # Output: list of records:
    # (end_date, filed_date, start_date, dur_days, lag_days, val, tag_prio, form, fy, fp)
    recs = []
    for prio, tag in enumerate(tag_list):
        node = gaap.get(tag)
        if not node:
            continue
        units = node.get("units", {})
        arr = units.get(unit)
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
            s_d = parse_date(s_str)
            e_d = parse_date(e_str)
            f_d = parse_date(f_str)
            if not (s_d and e_d and f_d):
                continue
            lag = (f_d - e_d).days
            # Mandatory physical filter: 0 < (filed - end).days <= 130
            if not (0 < lag <= 130):
                continue
            dur = (e_d - s_d).days
            recs.append({
                "end": e_d,
                "end_str": e_str,
                "filed": f_d,
                "filed_str": f_str,
                "start": s_d,
                "start_str": s_str,
                "dur": dur,
                "lag": lag,
                "val": float(val),
                "prio": prio,
                "tag": tag,
                "form": form,
                "fy": item.get("fy"),
                "fp": item.get("fp")
            })
    return recs


def extract_raw_instant_records(gaap, tag_list, unit="USD"):
    # Output: list of records:
    # (end_date, filed_date, lag_days, val, tag_prio, form, fy, fp)
    recs = []
    for prio, tag in enumerate(tag_list):
        node = gaap.get(tag)
        if not node:
            continue
        units = node.get("units", {})
        arr = units.get(unit)
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
            e_d = parse_date(e_str)
            f_d = parse_date(f_str)
            if not (e_d and f_d):
                continue
            lag = (f_d - e_d).days
            # Mandatory physical filter: 0 < (filed - end).days <= 130
            if not (0 < lag <= 130):
                continue
            recs.append({
                "end": e_d,
                "end_str": e_str,
                "filed": f_d,
                "filed_str": f_str,
                "lag": lag,
                "val": float(val),
                "prio": prio,
                "tag": tag,
                "form": form,
                "fy": item.get("fy"),
                "fp": item.get("fp")
            })
    return recs


def extract_shares_records(gaap, dei):
    # Combines flow shares (Diluted / Basic) and instant shares (CommonStockSharesOutstanding, EntityCommonStockSharesOutstanding)
    recs = []
    # 1. Flow shares (Diluted prio 0, Basic prio 1)
    for prio, tag in enumerate(SHARE_FLOW_TAGS):
        node = gaap.get(tag)
        if not node:
            continue
        arr = node.get("units", {}).get("shares", [])
        for item in arr:
            form = item.get("form")
            if form not in VALID_FORMS:
                continue
            e_str = item.get("end")
            f_str = item.get("filed")
            val = item.get("val")
            if not (e_str and f_str and val and float(val) > 0):
                continue
            e_d = parse_date(e_str)
            f_d = parse_date(f_str)
            if not (e_d and f_d):
                continue
            lag = (f_d - e_d).days
            if not (0 < lag <= 130):
                continue
            s_str = item.get("start")
            dur = (e_d - parse_date(s_str)).days if s_str else None
            # Only single quarter or FY
            if dur is not None and not ((70 <= dur <= 110) or (345 <= dur <= 385)):
                continue
            recs.append({
                "end": e_d,
                "end_str": e_str,
                "filed": f_d,
                "filed_str": f_str,
                "val": float(val),
                "prio": prio,
                "dur": dur,
                "source": "flow"
            })

    # 2. Instant shares: CommonStockSharesOutstanding (prio 2)
    node_c = gaap.get("CommonStockSharesOutstanding")
    if node_c:
        arr = node_c.get("units", {}).get("shares", [])
        for item in arr:
            form = item.get("form")
            if form not in VALID_FORMS:
                continue
            e_str = item.get("end")
            f_str = item.get("filed")
            val = item.get("val")
            if not (e_str and f_str and val and float(val) > 0):
                continue
            e_d = parse_date(e_str)
            f_d = parse_date(f_str)
            if not (e_d and f_d):
                continue
            lag = (f_d - e_d).days
            if not (0 < lag <= 130):
                continue
            recs.append({
                "end": e_d,
                "end_str": e_str,
                "filed": f_d,
                "filed_str": f_str,
                "val": float(val),
                "prio": 2,
                "dur": None,
                "source": "instant"
            })

    # 3. DEI EntityCommonStockSharesOutstanding (prio 3)
    node_dei = dei.get("EntityCommonStockSharesOutstanding")
    if node_dei:
        arr = node_dei.get("units", {}).get("shares", [])
        for item in arr:
            form = item.get("form")
            if form not in VALID_FORMS:
                continue
            e_str = item.get("end")
            f_str = item.get("filed")
            val = item.get("val")
            if not (e_str and f_str and val and float(val) > 0):
                continue
            e_d = parse_date(e_str)
            f_d = parse_date(f_str)
            if not (e_d and f_d):
                continue
            lag = (f_d - e_d).days
            if not (0 < lag <= 130):
                continue
            recs.append({
                "end": e_d,
                "end_str": e_str,
                "filed": f_d,
                "filed_str": f_str,
                "val": float(val),
                "prio": 3,
                "dur": None,
                "source": "dei"
            })

    return recs


def process_single_company(ticker, cik, name, facts):
    us_gaap = facts.get("us-gaap", {})
    dei = facts.get("dei", {})
    if not us_gaap:
        return []

    # 1. Extract raw flow records
    flows = {}
    for metric, tags in FLOW_TAGS.items():
        flows[metric] = extract_raw_flow_records(us_gaap, tags)

    # 2. Extract raw instant records
    instants = {}
    for metric, tags in STOCK_TAGS.items():
        instants[metric] = extract_raw_instant_records(us_gaap, tags)

    shares_raw = extract_shares_records(us_gaap, dei)

    # Check if there is enough data
    if not flows["rev"] and not flows["ni"]:
        return []

    # Helper: deduplicate records for a given metric and duration category
    # Period types:
    # 1: 1Q (70 <= dur <= 110)
    # 2: 2Q (160 <= dur <= 205)
    # 3: 3Q (250 <= dur <= 300)
    # 4: FY (345 <= dur <= 385)
    def categorize_flow(records):
        # returns dict: (end_date, period_type) -> best record
        # rule: sort by filed ascending (earliest filed date and original first-disclosed value!), then tag prio ascending
        by_key = {}
        for r in records:
            dur = r["dur"]
            pt = None
            if 70 <= dur <= 110:
                pt = 1
            elif 160 <= dur <= 205:
                pt = 2
            elif 250 <= dur <= 300:
                pt = 3
            elif 345 <= dur <= 385:
                pt = 4
            if pt is None:
                continue
            key = (r["end"], pt)
            cand = (r["filed"], r["prio"], r)
            if key not in by_key or cand[:2] < by_key[key][:2]:
                by_key[key] = cand
        return {k: v[2] for k, v in by_key.items()}

    cat_flows = {m: categorize_flow(flows[m]) for m in flows}

    # Helper for instant records:
    # (end_date) -> best record (earliest filed, tag prio ascending)
    def categorize_instant(records):
        by_end = {}
        for r in records:
            cand = (r["filed"], r["prio"], r)
            if r["end"] not in by_end or cand[:2] < by_end[r["end"]][:2]:
                by_end[r["end"]] = cand
        return {k: v[2] for k, v in by_end.items()}

    cat_instants = {m: categorize_instant(instants[m]) for m in instants}

    # Best shares by end_date:
    by_end_shares = {}
    for r in shares_raw:
        # Prioritize 1Q flow shares, then prio, then earliest filed
        flow_bonus = 0 if r["dur"] and 70 <= r["dur"] <= 110 else 1
        cand = (r["prio"], flow_bonus, r["filed"], r)
        if r["end"] not in by_end_shares or cand[:3] < by_end_shares[r["end"]][:3]:
            by_end_shares[r["end"]] = cand
    cat_shares = {k: v[3] for k, v in by_end_shares.items()}

    # Identify all candidate quarterly end dates
    # A quarter end date is recognized if it has 1Q or FY filing in rev, ni, opinc, or assets
    all_quarter_ends = set()
    for m in ["rev", "ni", "opinc"]:
        for (e_d, pt) in cat_flows[m]:
            if pt in (1, 4):
                all_quarter_ends.add(e_d)
    for e_d in cat_instants["assets"]:
        all_quarter_ends.add(e_d)

    sorted_ends = sorted(all_quarter_ends)
    if not sorted_ends:
        return []

    # Deduplicate end dates within 45 days of each other (keep the one with standard spacing)
    clean_ends = []
    for e_d in sorted_ends:
        if clean_ends and (e_d - clean_ends[-1]).days < 45:
            # Overlapping/duplicate period end, skip
            continue
        clean_ends.append(e_d)

    # Reconstruct single-quarter flows for all clean_ends
    # For each clean_end:
    # 1. Filing date filed_d: earliest filed date across 1Q/FY filings for this end
    quarter_records = []
    for e_d in clean_ends:
        # Determine filing date and form
        filing_candidates = []
        for m in ["rev", "ni", "opinc", "ocf", "capex"]:
            rec1 = cat_flows[m].get((e_d, 1))
            if rec1:
                filing_candidates.append(rec1)
            rec4 = cat_flows[m].get((e_d, 4))
            if rec4:
                filing_candidates.append(rec4)
        for m in ["assets", "equity", "cash"]:
            rec_inst = cat_instants[m].get(e_d)
            if rec_inst:
                filing_candidates.append(rec_inst)

        if not filing_candidates:
            continue

        filing_candidates.sort(key=lambda x: x["filed"])
        primary_rec = filing_candidates[0]
        f_d = primary_rec["filed"]
        f_str = primary_rec["filed_str"]
        e_str = primary_rec["end_str"]
        form = primary_rec.get("form", "10-Q")
        fy = primary_rec.get("fy")
        fp = primary_rec.get("fp")

        quarter_records.append({
            "end_d": e_d,
            "end_str": e_str,
            "filed_d": f_d,
            "filed_str": f_str,
            "form": form,
            "fy": fy,
            "fp": fp
        })

    # Build single-quarter dictionary for each flow metric
    # q_flows[metric][end_d] = {"val": val, "filed_d": filed_d, ...}
    q_flows = {m: {} for m in FLOW_TAGS}

    # Pass 1: Direct 1Q
    for m in FLOW_TAGS:
        for (e_d, pt), rec in cat_flows[m].items():
            if pt == 1:
                q_flows[m][e_d] = rec["val"]

    # Pass 2: Cash flow YTD Differencing (OCF and Capex)
    for m in ["ocf", "capex"]:
        # Sort YTD 2Q, 3Q, 4Q by end_date
        # Differencing strictly requires preceding quarter filed <= current filed
        for pt in [2, 3, 4]:
            for (e_d, p_type), rec in sorted(cat_flows[m].items(), key=lambda x: x[0][0]):
                if p_type != pt:
                    continue
                if e_d in q_flows[m]:
                    continue  # already has direct 1Q
                val_ytd = rec["val"]
                f_curr = rec["filed"]

                if pt == 2:
                    # 6M YTD: look for Q1 ~91 days prior
                    prev_cands = [k for k in q_flows[m] if 70 <= (e_d - k).days <= 115]
                    if len(prev_cands) == 1:
                        prev_k = prev_cands[0]
                        prev_rec = cat_flows[m].get((prev_k, 1))
                        if prev_rec and prev_rec["filed"] <= f_curr:
                            q_flows[m][e_d] = val_ytd - q_flows[m][prev_k]

                elif pt == 3:
                    # 9M YTD: look for 2Q YTD ~91 days prior
                    prev_2q = [k for (k, p), r in cat_flows[m].items() if p == 2 and 70 <= (e_d - k).days <= 115 and r["filed"] <= f_curr]
                    if len(prev_2q) == 1:
                        q_flows[m][e_d] = val_ytd - cat_flows[m][(prev_2q[0], 2)]["val"]
                    else:
                        # Fallback: sum of Q1 and Q2
                        q_prevs = [k for k in q_flows[m] if 70 <= (e_d - k).days <= 210]
                        if len(q_prevs) == 2:
                            q_flows[m][e_d] = val_ytd - sum(q_flows[m][k] for k in q_prevs)

                elif pt == 4:
                    # 12M FY: look for 3Q YTD ~91 days prior
                    prev_3q = [k for (k, p), r in cat_flows[m].items() if p == 3 and 70 <= (e_d - k).days <= 115 and r["filed"] <= f_curr]
                    if len(prev_3q) == 1:
                        q_flows[m][e_d] = val_ytd - cat_flows[m][(prev_3q[0], 3)]["val"]
                    else:
                        # Fallback: sum of Q1, Q2, Q3
                        q_prevs = sorted([k for k in q_flows[m] if 70 <= (e_d - k).days <= 310])
                        if len(q_prevs) == 3:
                            q_flows[m][e_d] = val_ytd - sum(q_flows[m][k] for k in q_prevs)

    # Pass 3: Rule 4 - Q4 Single Quarter Strict Imputation for Income Statement items
    # If 10-K has FY (pt=4) and direct 1Q is missing: FY - (Q1 + Q2 + Q3)
    # where Q1, Q2, Q3 fall in (end_fy - 310d, end_fy - 60d) and filed <= FY.filed
    for m in ["rev", "gp", "cor", "opinc", "ni", "rd", "sga", "sbc"]:
        for (e_d, pt), rec in sorted(cat_flows[m].items(), key=lambda x: x[0][0]):
            if pt != 4:
                continue
            if e_d in q_flows[m]:
                continue
            fy_val = rec["val"]
            f_fy = rec["filed"]

            # Look for 3 non-overlapping quarters in (e_d - 310d, e_d - 60d)
            cands = sorted([k for k in q_flows[m] if 60 <= (e_d - k).days <= 310])
            if len(cands) >= 3:
                # Select 3 quarters ~91 days apart
                selected = [cands[-1]]
                for cand_k in reversed(cands[:-1]):
                    if 70 <= (selected[-1] - cand_k).days <= 115:
                        selected.append(cand_k)
                        if len(selected) == 3:
                            break
                if len(selected) == 3:
                    # Check filing date condition: all selected quarters filed <= FY.filed
                    valid_pit = True
                    for sk in selected:
                        rec_k = cat_flows[m].get((sk, 1))
                        if rec_k and rec_k["filed"] > f_fy:
                            valid_pit = False
                            break
                    if valid_pit:
                        q_flows[m][e_d] = fy_val - sum(q_flows[m][sk] for sk in selected)

    # Fallback for Gross Profit (gp = rev - cor)
    for e_d in clean_ends:
        if e_d not in q_flows["gp"] or np.isnan(q_flows["gp"][e_d]):
            if e_d in q_flows["rev"] and e_d in q_flows["cor"]:
                r_v = q_flows["rev"][e_d]
                c_v = q_flows["cor"][e_d]
                if pd.notna(r_v) and pd.notna(c_v):
                    q_flows["gp"][e_d] = r_v - c_v

    # Fallback for SGA (sga = sm + ga)
    for e_d in clean_ends:
        if e_d not in q_flows["sga"] or np.isnan(q_flows["sga"][e_d]):
            if e_d in q_flows["sm"] and e_d in q_flows["ga"]:
                sm_v = q_flows["sm"][e_d]
                ga_v = q_flows["ga"][e_d]
                if pd.notna(sm_v) and pd.notna(ga_v):
                    q_flows["sga"][e_d] = sm_v + ga_v

    # Build primary quarterly panel rows
    panel_rows = []
    for q_rec in quarter_records:
        e_d = q_rec["end_d"]
        f_d = q_rec["filed_d"]

        # Raw quarterly flow values
        rev = q_flows["rev"].get(e_d, np.nan)
        gp = q_flows["gp"].get(e_d, np.nan)
        cor = q_flows["cor"].get(e_d, np.nan)
        opinc = q_flows["opinc"].get(e_d, np.nan)
        ni = q_flows["ni"].get(e_d, np.nan)
        rd = q_flows["rd"].get(e_d, np.nan)
        sga = q_flows["sga"].get(e_d, np.nan)
        sbc = q_flows["sbc"].get(e_d, np.nan)
        ocf = q_flows["ocf"].get(e_d, np.nan)
        capex_raw = q_flows["capex"].get(e_d, np.nan)
        capex = abs(capex_raw) if pd.notna(capex_raw) else np.nan

        # If revenue and net income are both missing, this is not a viable quarterly record
        if np.isnan(rev) and np.isnan(ni):
            continue

        # opinc_is_ebt flag
        opinc_is_ebt = 0
        rec_op = cat_flows["opinc"].get((e_d, 1)) or cat_flows["opinc"].get((e_d, 4))
        if rec_op and rec_op["tag"] == "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
            opinc_is_ebt = 1

        # Instant items
        assets = cat_instants["assets"].get(e_d, {}).get("val", np.nan)
        cash = cat_instants["cash"].get(e_d, {}).get("val", np.nan)
        equity = cat_instants["equity"].get(e_d, {}).get("val", np.nan)
        debt_lt = cat_instants["debt_lt"].get(e_d, {}).get("val", np.nan)
        debt_st = cat_instants["debt_st"].get(e_d, {}).get("val", np.nan)

        shares = cat_shares.get(e_d, {}).get("val", np.nan)

        panel_rows.append({
            "ticker": ticker,
            "cik": cik,
            "company_name": name,
            "end_date": q_rec["end_str"],
            "end_d": e_d,
            "filed": q_rec["filed_str"],
            "filed_d": f_d,
            "form": q_rec["form"],
            "fiscal_year": q_rec["fy"],
            "fiscal_period": q_rec["fp"],
            "opinc_is_ebt": opinc_is_ebt,
            "rev": rev,
            "gp": gp,
            "cor": cor,
            "opinc": opinc,
            "ni": ni,
            "rd": rd,
            "sga": sga,
            "sbc": sbc,
            "ocf": ocf,
            "capex": capex,
            "assets": assets,
            "cash": cash,
            "equity": equity,
            "debt_lt": debt_lt,
            "debt_st": debt_st,
            "shares": shares
        })

    if not panel_rows:
        return []

    # Sort chronologically by end date
    panel_rows.sort(key=lambda x: x["end_d"])

    # Compute TTM, Ratios, YoY, and Trajectory Features strictly using prior records
    n_q = len(panel_rows)
    for i in range(n_q):
        curr = panel_rows[i]
        curr_e = curr["end_d"]
        curr_f = curr["filed_d"]

        # Helper to find prior quarter k steps back (~91 * k days)
        def find_prior_quarter(n_quarters):
            target_days = int(round(91.31 * n_quarters))
            tol = 22 if n_quarters <= 4 else 30
            best_idx = None
            best_diff = 999
            for j in range(i - 1, -1, -1):
                lag_d = (curr_e - panel_rows[j]["end_d"]).days
                diff = abs(lag_d - target_days)
                if diff <= tol and diff < best_diff:
                    # Strict PIT condition: prior filing date must be < current filing date
                    if panel_rows[j]["filed_d"] < curr_f:
                        best_diff = diff
                        best_idx = j
            return panel_rows[best_idx] if best_idx is not None else None

        q_lag1 = find_prior_quarter(1)
        q_lag2 = find_prior_quarter(2)
        q_lag3 = find_prior_quarter(3)
        q_lag4 = find_prior_quarter(4)

        # 1. TTM Sums
        def compute_ttm(metric_name):
            v0 = curr[metric_name]
            v1 = q_lag1[metric_name] if q_lag1 else np.nan
            v2 = q_lag2[metric_name] if q_lag2 else np.nan
            v3 = q_lag3[metric_name] if q_lag3 else np.nan
            vals = [v0, v1, v2, v3]
            if any(pd.isna(x) for x in vals):
                return np.nan
            return float(sum(vals))

        curr["rev_ttm"] = compute_ttm("rev")
        curr["gp_ttm"] = compute_ttm("gp")
        curr["opinc_ttm"] = compute_ttm("opinc")
        curr["ni_ttm"] = compute_ttm("ni")
        curr["ocf_ttm"] = compute_ttm("ocf")
        curr["capex_ttm"] = compute_ttm("capex")
        curr["sbc_ttm"] = compute_ttm("sbc")

        # FCF TTM
        if pd.notna(curr["ocf_ttm"]) and pd.notna(curr["capex_ttm"]):
            curr["fcf_ttm"] = curr["ocf_ttm"] - curr["capex_ttm"]
        else:
            curr["fcf_ttm"] = np.nan

        # 2. Quarterly Ratios
        rev_0 = curr["rev"]
        curr["gm_q"] = (curr["gp"] / rev_0) if (pd.notna(curr["gp"]) and pd.notna(rev_0) and rev_0 > 0) else np.nan
        curr["opm_q"] = (curr["opinc"] / rev_0) if (pd.notna(curr["opinc"]) and pd.notna(rev_0) and rev_0 > 0) else np.nan
        curr["nm_q"] = (curr["ni"] / rev_0) if (pd.notna(curr["ni"]) and pd.notna(rev_0) and rev_0 > 0) else np.nan
        curr["rd_ratio_q"] = (curr["rd"] / rev_0) if (pd.notna(curr["rd"]) and pd.notna(rev_0) and rev_0 > 0) else np.nan
        curr["sga_ratio_q"] = (curr["sga"] / rev_0) if (pd.notna(curr["sga"]) and pd.notna(rev_0) and rev_0 > 0) else np.nan
        curr["gm_minus_sga_q"] = (curr["gm_q"] - curr["sga_ratio_q"]) if (pd.notna(curr["gm_q"]) and pd.notna(curr["sga_ratio_q"])) else np.nan

        curr["fcf_margin_ttm"] = (curr["fcf_ttm"] / curr["rev_ttm"]) if (pd.notna(curr["fcf_ttm"]) and pd.notna(curr["rev_ttm"]) and curr["rev_ttm"] > 0) else np.nan
        curr["ocf_to_ni_ttm"] = (curr["ocf_ttm"] / curr["ni_ttm"]) if (pd.notna(curr["ocf_ttm"]) and pd.notna(curr["ni_ttm"]) and abs(curr["ni_ttm"]) > 1e-5) else np.nan

        # 3. ROE, Neg Equity, Invested Capital, ROIC TTM
        equity = curr["equity"]
        assets = curr["assets"]
        neg_equity = 0
        if pd.notna(equity):
            if equity <= 0:
                neg_equity = 1
            elif pd.notna(assets) and assets > 0 and equity <= 0.05 * assets:
                neg_equity = 1
        curr["neg_equity"] = neg_equity

        if neg_equity == 1 or pd.isna(equity) or equity <= 0 or pd.isna(curr["ni_ttm"]):
            curr["roe_ttm"] = np.nan
        else:
            curr["roe_ttm"] = curr["ni_ttm"] / equity

        tot_debt = (0.0 if pd.isna(curr["debt_lt"]) else curr["debt_lt"]) + (0.0 if pd.isna(curr["debt_st"]) else curr["debt_st"])
        cash_clean = 0.0 if pd.isna(curr["cash"]) else curr["cash"]
        invested_cap = (equity if pd.notna(equity) else 0.0) + tot_debt - cash_clean
        curr["invested_cap"] = invested_cap

        floor_ic = 0.15 * assets if (pd.notna(assets) and assets > 0) else 0.0
        denom_roic = max(invested_cap, floor_ic)
        if denom_roic > 0 and pd.notna(curr["opinc_ttm"]):
            curr["roic_ttm"] = (curr["opinc_ttm"] * 0.78) / denom_roic
        else:
            curr["roic_ttm"] = np.nan

        # 4. YoY comparisons (vs Lag 4Q, i.e. 365±25d prior, filed < curr.filed)
        if q_lag4:
            # rev_yoy
            r4 = q_lag4["rev"]
            curr["rev_yoy"] = (rev_0 / r4 - 1.0) if (pd.notna(rev_0) and pd.notna(r4) and r4 > 0) else np.nan

            # gp_yoy
            gp4 = q_lag4["gp"]
            curr["gp_yoy"] = (curr["gp"] / gp4 - 1.0) if (pd.notna(curr["gp"]) and pd.notna(gp4) and gp4 > 0) else np.nan

            # opinc_yoy: (curr - prev) / abs(prev)
            op0 = curr["opinc"]
            op4 = q_lag4["opinc"]
            curr["opinc_yoy"] = ((op0 - op4) / abs(op4)) if (pd.notna(op0) and pd.notna(op4) and abs(op4) > 1e-5) else np.nan

            # ni_yoy: (curr - prev) / abs(prev)
            ni0 = curr["ni"]
            ni4 = q_lag4["ni"]
            curr["ni_yoy"] = ((ni0 - ni4) / abs(ni4)) if (pd.notna(ni0) and pd.notna(ni4) and abs(ni4) > 1e-5) else np.nan

            # Margin changes
            curr["gm_yoy_chg"] = (curr["gm_q"] - q_lag4["gm_q"]) if (pd.notna(curr["gm_q"]) and pd.notna(q_lag4["gm_q"])) else np.nan
            curr["opm_yoy_chg"] = (curr["opm_q"] - q_lag4["opm_q"]) if (pd.notna(curr["opm_q"]) and pd.notna(q_lag4["opm_q"])) else np.nan
            curr["gm_sga_yoy_chg"] = (curr["gm_minus_sga_q"] - q_lag4["gm_minus_sga_q"]) if (pd.notna(curr["gm_minus_sga_q"]) and pd.notna(q_lag4["gm_minus_sga_q"])) else np.nan
            curr["roic_yoy_chg"] = (curr["roic_ttm"] - q_lag4["roic_ttm"]) if (pd.notna(curr["roic_ttm"]) and pd.notna(q_lag4["roic_ttm"])) else np.nan

            # Dilution rate
            sh0 = curr["shares"]
            sh4 = q_lag4["shares"]
            curr["shares_yoy_dilution"] = (sh0 / sh4 - 1.0) if (pd.notna(sh0) and pd.notna(sh4) and sh4 > 0) else np.nan

            # Turnaround to profit
            turnaround = 0
            if pd.notna(op4) and pd.notna(ni4) and pd.notna(op0) and pd.notna(ni0):
                if (op4 <= 0 or ni4 <= 0) and (op0 > 0 and ni0 > 0):
                    turnaround = 1
            curr["turnaround_to_profit_1q"] = turnaround
            curr["roic_ttm_lag4"] = q_lag4["roic_ttm"]
        else:
            curr["rev_yoy"] = np.nan
            curr["gp_yoy"] = np.nan
            curr["opinc_yoy"] = np.nan
            curr["ni_yoy"] = np.nan
            curr["gm_yoy_chg"] = np.nan
            curr["opm_yoy_chg"] = np.nan
            curr["gm_sga_yoy_chg"] = np.nan
            curr["roic_yoy_chg"] = np.nan
            curr["shares_yoy_dilution"] = np.nan
            curr["turnaround_to_profit_1q"] = 0
            curr["roic_ttm_lag4"] = np.nan

        # 5. Trajectory & Acceleration Features
        if q_lag1 and pd.notna(curr["rev_yoy"]) and pd.notna(q_lag1.get("rev_yoy")):
            curr["rev_accel_1q"] = curr["rev_yoy"] - q_lag1["rev_yoy"]
        else:
            curr["rev_accel_1q"] = np.nan

        curr["rev_yoy_lag1"] = q_lag1.get("rev_yoy", np.nan) if q_lag1 else np.nan
        curr["rev_yoy_lag2"] = q_lag2.get("rev_yoy", np.nan) if q_lag2 else np.nan
        curr["rev_yoy_lag3"] = q_lag3.get("rev_yoy", np.nan) if q_lag3 else np.nan

        curr["opm_q_lag1"] = q_lag1.get("opm_q", np.nan) if q_lag1 else np.nan
        curr["opm_q_lag2"] = q_lag2.get("opm_q", np.nan) if q_lag2 else np.nan
        curr["opm_q_lag3"] = q_lag3.get("opm_q", np.nan) if q_lag3 else np.nan

        # Consecutive run counts (walk back through history)
        # consec_rev_accel_n
        accel_cnt = 0
        idx_step = i
        while idx_step >= 0:
            row_step = panel_rows[idx_step]
            acc = row_step.get("rev_accel_1q")
            if pd.notna(acc) and acc > 0:
                accel_cnt += 1
                idx_step -= 1
            else:
                break
        curr["consec_rev_accel_n"] = accel_cnt

        # consec_opm_expand_n
        opm_exp_cnt = 0
        idx_step = i
        while idx_step >= 0:
            row_step = panel_rows[idx_step]
            opm_chg = row_step.get("opm_yoy_chg")
            if pd.notna(opm_chg) and opm_chg > 0:
                opm_exp_cnt += 1
                idx_step -= 1
            else:
                break
        curr["consec_opm_expand_n"] = opm_exp_cnt

        # consec_gm_sga_expand_n
        gm_sga_cnt = 0
        idx_step = i
        while idx_step >= 0:
            row_step = panel_rows[idx_step]
            chg = row_step.get("gm_sga_yoy_chg")
            if pd.notna(chg) and chg > 0:
                gm_sga_cnt += 1
                idx_step -= 1
            else:
                break
        curr["consec_gm_sga_expand_n"] = gm_sga_cnt

        # consec_double_inflect_n: BOTH rev accelerating AND margin expanding
        dbl_cnt = 0
        idx_step = i
        while idx_step >= 0:
            row_step = panel_rows[idx_step]
            acc = row_step.get("rev_accel_1q")
            opm_chg = row_step.get("opm_yoy_chg")
            gm_chg = row_step.get("gm_sga_yoy_chg")
            m_exp = (pd.notna(opm_chg) and opm_chg > 0) or (pd.notna(gm_chg) and gm_chg > 0)
            if pd.notna(acc) and acc > 0 and m_exp:
                dbl_cnt += 1
                idx_step -= 1
            else:
                break
        curr["consec_double_inflect_n"] = dbl_cnt

    # Remove temporary helper keys
    for r in panel_rows:
        r.pop("end_d", None)
        r.pop("filed_d", None)

    return panel_rows


def main():
    t_start = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"Loading shard list from: {SHARD_PATH}")
    with open(SHARD_PATH, "r") as f:
        shard_items = json.load(f)
    print(f"Total companies in Shard 2: {len(shard_items)}")

    zf, zip_path = wait_and_open_zip()
    zip_set = set(zf.namelist())

    all_records = []
    n_processed = 0
    n_with_data = 0

    for item in shard_items:
        ticker = item["ticker"]
        cik = int(item["cik"])
        name = item.get("name", "")
        cik_fname = f"CIK{cik:010d}.json"

        n_processed += 1
        if cik_fname not in zip_set:
            continue

        try:
            raw_data = json.loads(zf.read(cik_fname))
            facts = raw_data.get("facts", {})
            rows = process_single_company(ticker, cik, name, facts)
            if rows:
                all_records.extend(rows)
                n_with_data += 1
        except Exception as e:
            print(f"Error processing {ticker} (CIK {cik}): {e}")

        if n_processed % 50 == 0:
            print(f"  Processed {n_processed}/{len(shard_items)} tickers | Rows extracted: {len(all_records):,} ({time.time()-t_start:.1f}s)")

    print(f"\nFinished extracting. Total companies with valid PIT data: {n_with_data}/{len(shard_items)}")
    print(f"Total panel rows: {len(all_records):,}")

    if not all_records:
        raise RuntimeError("No records were extracted! Please verify inputs.")

    df = pd.DataFrame(all_records)

    # Sort final table by ticker and end_date
    df = df.sort_values(["ticker", "end_date"]).reset_index(drop=True)

    # Verify zero lookahead
    # Check 1: filed > end_date
    lags = (pd.to_datetime(df["filed"]) - pd.to_datetime(df["end_date"])).dt.days
    invalid_lookahead = (lags <= 0) | (lags > 130)
    n_invalid = invalid_lookahead.sum()
    print(f"\nZero-lookahead validation:")
    print(f"  Min filing lag (days): {lags.min()}")
    print(f"  Max filing lag (days): {lags.max()}")
    print(f"  Violations (lag <= 0 or lag > 130): {n_invalid}")
    if n_invalid > 0:
        raise ValueError(f"Found {n_invalid} lookahead violations!")

    # Check dates range
    print(f"  Earliest filed date: {df['filed'].min()}")
    print(f"  Latest filed date:   {df['filed'].max()}")
    print(f"  Earliest end date:   {df['end_date'].min()}")
    print(f"  Latest end date:     {df['end_date'].max()}")
    print(f"  Unique tickers:      {df['ticker'].nunique()}")

    # Save to parquet
    print(f"\nWriting to Parquet: {OUT_PARQUET}...")
    df.to_parquet(OUT_PARQUET, index=False, engine="pyarrow", compression="snappy")
    file_size_mb = os.path.getsize(OUT_PARQUET) / 1e6
    print(f"SUCCESS! Output saved: {OUT_PARQUET} ({file_size_mb:.2f} MB, {len(df):,} rows)")
    print(f"Elapsed time: {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
