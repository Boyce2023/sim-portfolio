#!/usr/bin/env python3
"""
harvest_13f_2009_2016.py
SEC EDGAR 13F-HR Institutional Holdings 2009-2016 Historical Backfiller
Author: Delisted-Prices-And-13F-Permanent-Backfiller
Complies strictly with SEC Rate Limiting (<= 1.5 req/sec, User-Agent: OHIM Research buwen@ohim.com)
"""

import os
import sys
import re
import json
import time
import gzip
import xml.etree.ElementTree as ET
import pandas as pd
import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_fundamentals_30y_permanent"
RAW_13F_DIR = os.path.join(BASE_DIR, "raw_sec_cache", "13f")
CHECKPOINT_PARQUET = os.path.join(BASE_DIR, "sec_13f_2009_2016_checkpoint.parquet")
OUT_PERMANENT_PARQUET = os.path.join(BASE_DIR, "sec_13f_2009_2026_permanent.parquet")
CACHE_10Y_PARQUET = "/Users/huaichuaibeimeng/claude-projects/output/pick_30y_overhaul_20261111/sec_13f_10y_holdings_cache.parquet"
XBRL_MASTER_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/data/xbrl_master_pit_2009_2026.parquet"

os.makedirs(RAW_13F_DIR, exist_ok=True)

USER_AGENT = "OHIM Research buwen@ohim.com"

# Setup resilient HTTP session
session = requests.Session()
adapter = HTTPAdapter(
    max_retries=Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
)
session.mount("https://", adapter)
session.mount("http://", adapter)
session.headers.update({"User-Agent": USER_AGENT})

class RateLimiter:
    def __init__(self, max_per_sec=1.2):
        self.interval = 1.0 / max_per_sec
        self.last_req_time = 0.0

    def wait(self):
        now = time.time()
        elapsed = now - self.last_req_time
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self.last_req_time = time.time()

rate_limiter = RateLimiter(max_per_sec=1.2)

def sec_get(url, is_json=True, tries=4):
    for attempt in range(tries):
        rate_limiter.wait()
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                time.sleep(12 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json() if is_json else r.content
        except Exception as e:
            if attempt == tries - 1:
                return None
            time.sleep(2 * (attempt + 1))
    return None

# The 29 Evergreen Institutional Managers
MANAGERS_CIK = [
    ("Alex Sacerdote", "1387322"),
    ("Andreas Halvorsen", "1103804"),
    ("Bill Ackman", "1336528"),           # Pershing Square pre-2024
    ("Bill Nygren", "813917"),
    ("Boykin Curry", "945631"),
    ("Brad Gerstner", "1541617"),
    ("Carl Icahn", "921669"),
    ("Chase Coleman", "1167483"),
    ("Chris Hohn", "1647251"),
    ("Christopher Davis", "1036325"),
    ("Chuck Akre / John Neff", "1112520"),
    ("Dan Loeb", "1040273"),
    ("David Einhorn", "1079114"),
    ("David Tepper", "1006438"),          # Appaloosa Management LP pre-2016
    ("Dev Kantesaria", "1697868"),
    ("Gavin Baker", "1777813"),
    ("George Soros / Dawn Fitzpatrick", "1029160"),
    ("John Rogers", "936753"),
    ("Julian & Felix Baker", "1263508"),
    ("Lee Ainslie", "934639"),
    ("Mason Hawkins", "807985"),
    ("Nelson Peltz", "1345471"),
    ("Philippe Laffont", "1135730"),
    ("Seth Klarman", "1061768"),
    ("Stanley Druckenmiller", "1536411"),
    ("Stephen Mandel", "1061165"),
    ("Terry Smith", "1569205"),
    ("Tweedy Browne", "732905"),
    ("Warren Buffett", "1067983")
]

# Build CUSIP & Ticker Resolution Indexes
print("[Init] Building Ticker Resolution and CUSIP Dictionaries...")
EXACT_NAME_MAP = {
    "ALPHA METALLURGICAL": "AMR", "ALPHA METALLURGICAL RESOURCES": "AMR",
    "META PLATFORMS": "META", "FACEBOOK": "META", "ALPHABET": "GOOGL", "GOOGLE": "GOOGL",
    "NATERA": "NTRA", "VERTIV": "VRT", "GE VERNOVA": "GEV", "AMPHENOL": "APH",
    "ARISTA NETWORKS": "ANET", "BROADCOM": "AVGO", "APPLOVIN": "APP", "FAIR ISAAC": "FICO",
    "VISTRA": "VST", "CHENIERE": "LNG", "HOWMET": "HWM", "COMFORT SYSTEMS": "FIX",
    "BERKSHIRE": "BRK-B", "BERKSHIRE HATHAWAY": "BRK-B", "MICROSOFT": "MSFT", "APPLE": "AAPL",
    "NVIDIA": "NVDA", "AMAZON": "AMZN", "TESLA": "TSLA", "TAIWAN SEMICONDUCTOR": "TSM",
    "ASML": "ASML", "ELI LILLY": "LLY", "UNITEDHEALTH": "UNH", "VISA": "V", "MASTERCARD": "MA",
    "JPMORGAN": "JPM", "EXXON": "XOM", "CHEVRON": "CVX", "COSTCO": "COST", "WALMART": "WMT",
    "PROCTER & GAMBLE": "PG", "JOHNSON & JOHNSON": "JNJ", "ABBVIE": "ABBV", "ORACLE": "ORCL",
    "SALESFORCE": "CRM", "NETFLIX": "NFLX", "ADOBE": "ADBE", "CISCO": "CSCO", "INTEL": "INTC",
    "QUALCOMM": "QCOM", "TEXAS INSTRUMENTS": "TXN", "INTUIT": "INTU", "SERVICENOW": "NOW",
    "IBM": "IBM", "CONOCOPHILLIPS": "COP", "THERMO FISHER": "TMO", "ABBOTT": "ABT",
    "ACCENTURE": "ACN", "DISNEY": "DIS", "COCA COLA": "KO", "PEPSICO": "PEP",
    "MCDONALDS": "MCD", "LINDE": "LIN", "MEDTRONIC": "MDT", "PFIZER": "PFE",
    "GENERAL ELECTRIC": "GE", "CATERPILLAR": "CAT", "BOEING": "BA", "HONEYWELL": "HON",
    "UNION PACIFIC": "UNP", "LOWES": "LOW", "STARBUCKS": "SBUX", "AMGEN": "AMGN",
    "APPLIED MATERIALS": "AMAT", "LAM RESEARCH": "LRCX", "KLA": "KLAC", "MICRON": "MU",
    "ANALOG DEVICES": "ADI", "SYNOPSYS": "SNPS", "CADENCE": "CDNS", "PALANTIR": "PLTR",
    "UBER": "UBER", "AIRBNB": "ABNB", "SNOWFLAKE": "SNOW", "CROWDSTRIKE": "CRWD",
    "PALO ALTO NETWORKS": "PANW", "DATADOG": "DDOG", "CLOUDFLARE": "NET", "MONGODB": "MDB",
    "TRADE DESK": "TTD", "DUOLINGO": "DUOL", "CONSTELLATION ENERGY": "CEG",
    "AMERICAN EXPRESS": "AXP", "BANK OF NEW YORK MELLON": "BK", "CVS CAREMARK": "CVS",
    "CVS HEALTH": "CVS", "CITIGROUP": "C", "BANK OF AMERICA": "BAC", "WELLS FARGO": "WFC",
    "GOLDMAN SACHS": "GS", "MORGAN STANLEY": "MS", "BLACKROCK": "BLK", "MOODYS": "MCO",
    "S&P GLOBAL": "SPGI", "MCGRAW HILL": "SPGI", "DIRECTV": "DTV", "TIME WARNER": "TWX",
    "ACTIVISION": "ATVI", "CELGENE": "CELG", "ALEXION": "ALXN", "ALLERGAN": "AGN",
    "TWITTER": "TWTR", "VMWARE": "VMW", "XILINX": "XLNX", "BED BATH & BEYOND": "BBBY",
    "FIRST REPUBLIC": "FRC", "SVB FINANCIAL": "SIVB", "SILICON VALLEY BANK": "SIVB"
}

# Load CUSIP dictionary from existing 10Y cache
CUSIP_MAP = {}
if os.path.exists(CACHE_10Y_PARQUET):
    df_cache = pd.read_parquet(CACHE_10Y_PARQUET)
    val_c = df_cache[df_cache['ticker'].notna() & df_cache['cusip'].notna()]
    for cu, grp in val_c.groupby('cusip'):
        CUSIP_MAP[cu.upper()] = grp['ticker'].iloc[0]

# Add XBRL names
NAME_TO_TICKER = {}
if os.path.exists(XBRL_MASTER_PATH):
    df_xbrl = pd.read_parquet(XBRL_MASTER_PATH)
    if 'name' in df_xbrl.columns:
        for _, r in df_xbrl[['ticker', 'name']].dropna().drop_duplicates().iterrows():
            clean_n = re.sub(r'[^A-Z0-9 ]', ' ', str(r['name']).upper()).strip()
            NAME_TO_TICKER[clean_n] = str(r['ticker']).replace('/', '-')

def resolve_ticker(issuer, cusip=None):
    if cusip and str(cusip).upper() in CUSIP_MAP:
        return CUSIP_MAP[str(cusip).upper()]
    if not issuer or pd.isna(issuer):
        return None
    raw = re.sub(r'[^A-Z0-9 ]', ' ', str(issuer).upper())
    raw = re.sub(r'\s+', ' ', raw).strip()
    
    if "ALPHA METALLURGICAL" in raw:
        return "AMR"
    for k, v in EXACT_NAME_MAP.items():
        if k in raw:
            if k in ["META", "META PLATFORMS"] and "ALPHA" in raw:
                continue
            return v
    if raw in NAME_TO_TICKER:
        return NAME_TO_TICKER[raw]
    words = raw.split()
    if len(words) >= 2:
        w2 = f"{words[0]} {words[1]}"
        if w2 in EXACT_NAME_MAP:
            return EXACT_NAME_MAP[w2]
        if w2 in NAME_TO_TICKER:
            return NAME_TO_TICKER[w2]
    return None

def parse_xml_infotable(xml_bytes):
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return []
    ln = lambda e: e.tag.rsplit('}', 1)[-1]
    rows = []
    for it in root.iter():
        if ln(it) != 'infoTable':
            continue
        g = {ln(c): (c.text or '').strip() for c in it.iter()}
        if g.get('putCall'):
            continue
        if g.get('sshPrnamtType', 'SH').upper() not in ('SH', 'PRN', ''):
            continue
        cu = g.get('cusip', '').upper().replace(' ', '').replace('-', '')
        iss = g.get('nameOfIssuer', '').strip()
        try:
            sh = float(g.get('sshPrnamt') or 0)
        except Exception:
            sh = 0.0
        try:
            val = float(g.get('value') or 0)
        except Exception:
            val = 0.0
        if sh > 0:
            rows.append({
                'cusip': cu,
                'issuer': iss,
                'shares': sh,
                'value': val
            })
    return rows

def parse_ascii_infotable(text):
    rows = []
    lines = text.splitlines()
    cusip_re = re.compile(r'\b([0-9A-Z]{6}[\s\-]?[0-9A-Z]{2}[\s\-]?[0-9A-Z])\b')
    
    prev_lines = []
    for line in lines:
        s_line = line.strip()
        if not s_line:
            continue
        m = cusip_re.search(line)
        if m:
            cu_raw = m.group(1).replace(' ', '').replace('-', '').upper()
            if len(cu_raw) == 9 and sum(c.isdigit() for c in cu_raw) >= 3:
                before = line[:m.start()].strip()
                after = line[m.end():].strip()
                nums = re.findall(r'[\d,]+(?:\.\d+)?', after)
                clean_nums = [float(n.replace(',', '')) for n in nums if n.replace(',', '').replace('.', '').isdigit()]
                if len(clean_nums) >= 2:
                    val = clean_nums[0]
                    shares = clean_nums[1]
                    name_parts = []
                    for pl in prev_lines[-2:]:
                        if not cusip_re.search(pl) and len(pl) > 2 and not any(tag in pl for tag in ['<PAGE>', '<TABLE>', '----']):
                            name_parts.append(pl.strip())
                    name_parts.append(before)
                    full_name = " ".join(name_parts)
                    full_name = re.sub(r'[\.]{2,}', ' ', full_name)
                    full_name = re.sub(r'\b(COM|CL A|CL B|COMMON|SHS|CAP STK|CLASS A|CLASS B|ORD|SPON ADR)\b.*$', '', full_name, flags=re.I).strip()
                    full_name = re.sub(r'\s+', ' ', full_name).strip()
                    if shares > 0:
                        rows.append({
                            'cusip': cu_raw,
                            'issuer': full_name or before,
                            'shares': shares,
                            'value': val
                        })
            prev_lines = []
        else:
            prev_lines.append(s_line)
            if len(prev_lines) > 5:
                prev_lines.pop(0)
    return rows

def harvest_all_managers():
    print("=" * 70)
    print("Starting 13F-HR Harvest (2009-01-01 to 2016-02-09)")
    print("=" * 70)
    
    all_backfilled_rows = []
    
    # Check existing checkpoint
    if os.path.exists(CHECKPOINT_PARQUET):
        try:
            df_ckpt = pd.read_parquet(CHECKPOINT_PARQUET)
            all_backfilled_rows = df_ckpt.to_dict(orient='records')
            print(f"Loaded {len(all_backfilled_rows)} rows from existing checkpoint.")
        except Exception:
            pass

    processed_filings = set()
    for r in all_backfilled_rows:
        processed_filings.add(f"{r['cik']}_{r['report_date']}_{r['filing_date']}")

    for mgr_name, cik_str in MANAGERS_CIK:
        cik = int(cik_str)
        print(f"\n[{mgr_name}] Querying filings for CIK {cik}...")
        sub_url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
        sub_data = sec_get(sub_url, is_json=True)
        if not sub_data:
            print(f"  Warning: could not fetch submissions for CIK {cik}")
            continue

        filings = sub_data.get('filings', {})
        recent = filings.get('recent', {})
        all_forms = list(recent.get('form', []))
        all_dates = list(recent.get('filingDate', []))
        all_accs = list(recent.get('accessionNumber', []))
        all_reports = list(recent.get('reportDate', []))

        # Check older files
        for extra in filings.get('files', []):
            extra_url = f"https://data.sec.gov/submissions/{extra.get('name')}"
            extra_data = sec_get(extra_url, is_json=True)
            if extra_data:
                all_forms.extend(extra_data.get('form', []))
                all_dates.extend(extra_data.get('filingDate', []))
                all_accs.extend(extra_data.get('accessionNumber', []))
                all_reports.extend(extra_data.get('reportDate', []))

        # Filter to 13F-HR filings between 2009-01-01 and 2016-02-09
        target_filings = []
        for fm, f_dt, acc, r_dt in zip(all_forms, all_dates, all_accs, all_reports):
            if '13F-HR' in fm and '2009-01-01' <= f_dt <= '2016-02-09':
                target_filings.append((fm, f_dt, acc, r_dt))

        # Deduplicate by reportDate: prefer latest filingDate (or amendment)
        filings_by_report = {}
        for fm, f_dt, acc, r_dt in target_filings:
            key = r_dt or f_dt
            if key not in filings_by_report or f_dt > filings_by_report[key][1]:
                filings_by_report[key] = (fm, f_dt, acc, r_dt)

        print(f"  Found {len(filings_by_report)} quarterly reports to fetch.")

        for r_dt in sorted(filings_by_report.keys()):
            fm, f_dt, acc, report_d = filings_by_report[r_dt]
            f_key = f"{cik}_{report_d}_{f_dt}"
            if f_key in processed_filings:
                continue

            acc_clean = acc.replace('-', '')
            gz_path = os.path.join(RAW_13F_DIR, f"{cik}_{acc_clean}.gz")
            
            # Fetch directory index to locate tables
            idx_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/index.json"
            idx_data = sec_get(idx_url, is_json=True)
            
            holdings = []
            if idx_data:
                items = [i['name'] for i in idx_data.get('directory', {}).get('item', [])]
                # Check for XML table
                xml_files = [x for x in items if x.lower().endswith('.xml') and 'primary' not in x.lower() and ('table' in x.lower() or '13f' in x.lower())]
                if xml_files:
                    xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{xml_files[0]}"
                    xb = sec_get(xml_url, is_json=False)
                    if xb:
                        holdings = parse_xml_infotable(xb)
                
                # If no XML table, parse text table
                if not holdings:
                    # Find candidate text files
                    txt_files = [x for x in items if x.lower().endswith('.txt') and not x.lower().endswith('headers.html')]
                    # Sort so specific 13f table txt comes first, else {acc}.txt
                    txt_files.sort(key=lambda x: 0 if '13f' in x.lower() else 1)
                    for tf in txt_files:
                        t_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{tf}"
                        tb = sec_get(t_url, is_json=False)
                        if tb:
                            try:
                                text_str = tb.decode('utf-8', errors='ignore')
                                parsed = parse_ascii_infotable(text_str)
                                if parsed and len(parsed) > len(holdings):
                                    holdings = parsed
                            except Exception:
                                pass
                        if holdings:
                            break

            if holdings:
                print(f"    [{report_d} filed {f_dt}] {fm} (acc {acc}): Parsed {len(holdings)} holdings.")
                for h in holdings:
                    cu = h['cusip']
                    iss = h['issuer']
                    sh = h['shares']
                    val = h['value']
                    # Standardize value: in 13F filings, value is reported in thousands ($1,000)
                    # If value < 5e7, it is thousands; multiply by 1000 for standard USD or keep thousands matching cache
                    # In sec_13f_10y_holdings_cache.parquet, values are in thousands (e.g. 160441.0 = $160M)
                    tk = resolve_ticker(iss, cu)
                    all_backfilled_rows.append({
                        'manager': mgr_name,
                        'cik': str(cik),
                        'report_date': str(report_d)[:10],
                        'filing_date': str(f_dt)[:10],
                        'cusip': cu,
                        'issuer': iss,
                        'shares': float(sh),
                        'value': float(val),
                        'ticker': tk
                    })
                processed_filings.add(f_key)
            else:
                print(f"    [{report_d} filed {f_dt}] {fm} (acc {acc}): No table parsed.")

            # Periodic checkpoint save
            if len(all_backfilled_rows) % 100 < len(holdings):
                df_temp = pd.DataFrame(all_backfilled_rows)
                df_temp.to_parquet(CHECKPOINT_PARQUET, index=False)

    # Final save of backfilled table
    df_backfill = pd.DataFrame(all_backfilled_rows)
    df_backfill.to_parquet(CHECKPOINT_PARQUET, index=False)
    print(f"\nBackfill phase complete: {len(df_backfill)} total historical 2009-2016 holding records.")

    # Merge with 2016-2026 cache
    print("\nMerging with 2016-2026 institutional cache...")
    if os.path.exists(CACHE_10Y_PARQUET):
        df_10y = pd.read_parquet(CACHE_10Y_PARQUET)
        print(f"Loaded 2016-2026 cache: {len(df_10y)} rows.")
        # Ensure compatible columns and datatypes
        common_cols = ['manager', 'cik', 'report_date', 'filing_date', 'cusip', 'issuer', 'shares', 'value', 'ticker']
        for c in common_cols:
            if c not in df_backfill.columns: df_backfill[c] = None
            if c not in df_10y.columns: df_10y[c] = None
        
        df_backfill_clean = df_backfill[common_cols].copy()
        df_10y_clean = df_10y[common_cols].copy()
        
        # Standardize CIK as normalized integer string
        df_backfill_clean['cik'] = df_backfill_clean['cik'].astype(str)
        df_10y_clean['cik'] = df_10y_clean['cik'].apply(lambda x: str(int(x)) if str(x).isdigit() else str(x))
        
        df_merged = pd.concat([df_backfill_clean, df_10y_clean], ignore_index=True)
        # Deduplicate
        df_merged = df_merged.drop_duplicates(subset=['cik', 'report_date', 'cusip', 'shares'], keep='last')
        df_merged = df_merged.sort_values(['manager', 'report_date', 'filing_date']).reset_index(drop=True)
        
        df_merged.to_parquet(OUT_PERMANENT_PARQUET, index=False)
        print(f"Successfully saved PERMANENT 2009-2026 13F dataset to {OUT_PERMANENT_PARQUET}")
        print(f"  Total records: {len(df_merged):,}")
        print(f"  Date range: {df_merged['filing_date'].min()} to {df_merged['filing_date'].max()}")
        print(f"  Unique managers: {df_merged['manager'].nunique()}")
        print(f"  Resolved tickers: {df_merged['ticker'].notna().sum()} / {len(df_merged)} ({df_merged['ticker'].notna().mean()*100:.1f}%)")
    else:
        print(f"Error: {CACHE_10Y_PARQUET} not found!")

if __name__ == "__main__":
    harvest_all_managers()
