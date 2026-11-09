#!/usr/bin/env python3
"""
W1_08: 1995-2026 SEC 全历史财报精确时间戳与 Pre-2009 面板提取器 (分片B)
Part B: pre2009_shard_0..3 全部 851 家去重升序排序后取 [1::3] (共 284 家)

Outputs:
1. /tmp/us_earn_macro_bt_20261109/pre2009_shards/sec_filings_1995_2026_partB.parquet
2. /tmp/us_earn_macro_bt_20261109/pre2009_shards/pre2009_comp_anchored_partB.parquet
"""

import os
import sys
import json
import time
import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import pandas as pd
import numpy as np
from bs4 import BeautifulSoup

# Config
BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
SHARDS_DIR = os.path.join(BASE_DIR, "shards")
TMP_OUTPUT_DIR = "/tmp/us_earn_macro_bt_20261109/pre2009_shards"
CACHE_DIR = "/tmp/us_earn_macro_bt_20261109/pre2009_cache_b"

USER_AGENT = "OHIM Research buwen@ohim.com"
MAX_REQ_PER_SEC = 1.35  # Strictly <= 1.5 req/sec

os.makedirs(TMP_OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.join(CACHE_DIR, "submissions"), exist_ok=True)
os.makedirs(os.path.join(CACHE_DIR, "companyfacts"), exist_ok=True)
os.makedirs(os.path.join(CACHE_DIR, "docs"), exist_ok=True)

class RateLimiter:
    def __init__(self, max_per_sec=1.35):
        self.min_interval = 1.0 / max_per_sec
        self.last_req_time = 0.0

    def wait(self):
        now = time.time()
        elapsed = now - self.last_req_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_req_time = time.time()

rate_limiter = RateLimiter(max_per_sec=MAX_REQ_PER_SEC)

session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    max_retries=requests.adapters.Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
)
session.mount("https://", adapter)
session.mount("http://", adapter)
session.headers.update({"User-Agent": USER_AGENT})

def fetch_url(url, cache_path=None, as_json=True, text_only=False):
    if cache_path and os.path.exists(cache_path):
        if os.path.getsize(cache_path) > 0:
            try:
                with open(cache_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    if content == "__404__":
                        return None
                    if as_json:
                        return json.loads(content)
                    return content
            except Exception as e:
                pass

    rate_limiter.wait()
    try:
        r = session.get(url, timeout=20)
        if r.status_code == 404:
            if cache_path:
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write("__404__")
            return None
        r.raise_for_status()
        content = r.text
        if cache_path:
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(content)
        if as_json:
            return r.json()
        return content
    except requests.exceptions.HTTPError as e:
        if r.status_code == 429:
            print(f"[RateLimit 429] Sleeping 15s...")
            time.sleep(15)
            return fetch_url(url, cache_path, as_json, text_only)
        print(f"HTTPError for {url}: {e}")
        return None
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def parse_session_timing(adt_str):
    if not adt_str or len(str(adt_str)) < 10:
        return 'DATE_ONLY'
    try:
        s = str(adt_str).strip()
        clean_str = s.replace('.000Z', 'Z').replace('Z', '+00:00')
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo('UTC'))
        dt_et = dt.astimezone(ZoneInfo('America/New_York'))
        # If midnight ET (00:00:00), SEC had date only
        if dt_et.hour == 0 and dt_et.minute == 0 and dt_et.second == 0:
            return 'DATE_ONLY'
        t = dt_et.time()
        t_0930 = datetime.strptime('09:30:00', '%H:%M:%S').time()
        t_1600 = datetime.strptime('16:00:00', '%H:%M:%S').time()
        if t < t_0930:
            return 'BMO_pre0930ET'
        elif t < t_1600:
            return 'INTRADAY'
        else:
            return 'AMC_post1600ET'
    except Exception:
        return 'DATE_ONLY'

def check_8k_items(items_val):
    if not items_val:
        return False
    if isinstance(items_val, list):
        item_set = {str(x).strip() for x in items_val}
    else:
        item_set = {x.strip() for x in str(items_val).replace(';', ',').split(',') if x.strip()}
    target = {'2.02', '12', '1.03', '2.01'}
    return bool(item_set & target)

def load_part_b_companies():
    all_items = []
    for i in range(4):
        p = os.path.join(SHARDS_DIR, f"pre2009_shard_{i}.json")
        with open(p, "r", encoding="utf-8") as f:
            all_items.extend(json.load(f))
    unique = {item['ticker']: item for item in all_items}
    sorted_items = sorted(unique.values(), key=lambda x: x['ticker'])
    part_b = sorted_items[1::3]
    return part_b

def run_part_1(companies):
    print(f"=== [Step 1] Fetching SEC Filings (1995-2026) for {len(companies)} Part B Companies ===")
    all_records = []
    # Index for fast lookup in Part 2: (ticker, reportDate) and (ticker, fiscal_year, form)
    filings_index = {}

    for idx, comp in enumerate(companies):
        ticker = comp['ticker']
        cik = int(comp['cik'])
        entity_name = comp.get('name', '')

        if (idx + 1) % 25 == 0 or idx == 0:
            print(f"[{idx+1}/{len(companies)}] Fetching filings for {ticker} (CIK {cik:010d})...")

        sub_cache = os.path.join(CACHE_DIR, "submissions", f"CIK{cik:010d}.json")
        sub_url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
        data = fetch_url(sub_url, cache_path=sub_cache, as_json=True)

        if not data:
            print(f"  Warning: No submission data for {ticker} (CIK {cik})")
            continue

        actual_name = data.get('name', entity_name)
        comp_records = []

        # 1. Recent filings
        recent = data.get('filings', {}).get('recent', {})
        if recent and 'form' in recent:
            comp_records.append(recent)

        # 2. Historical submission files
        hist_files = data.get('filings', {}).get('files', [])
        for hf in hist_files:
            fname = hf.get('name')
            if not fname:
                continue
            h_cache = os.path.join(CACHE_DIR, "submissions", fname)
            h_url = f"https://data.sec.gov/submissions/{fname}"
            h_data = fetch_url(h_url, cache_path=h_cache, as_json=True)
            if h_data and 'form' in h_data:
                comp_records.append(h_data)

        # Parse rows
        seen_accessions = set()
        ticker_filings = []

        for rec in comp_records:
            forms = rec.get('form', [])
            f_dates = rec.get('filingDate', [])
            r_dates = rec.get('reportDate', [])
            adts = rec.get('acceptanceDateTime', [])
            items_list = rec.get('items', [])
            accns = rec.get('accessionNumber', [])
            pdocs = rec.get('primaryDocument', [])

            n_rows = len(forms)
            for i in range(n_rows):
                f_date = f_dates[i] if i < len(f_dates) else ''
                if not f_date or not ('1995-01-01' <= f_date <= '2026-11-09'):
                    continue

                form = forms[i] if i < len(forms) else ''
                accn = accns[i] if i < len(accns) else ''
                if accn in seen_accessions:
                    continue

                r_date = r_dates[i] if i < len(r_dates) else ''
                adt = adts[i] if i < len(adts) else ''
                raw_items = items_list[i] if i < len(items_list) else ''
                pdoc = pdocs[i] if i < len(pdocs) else ''

                # Filter condition:
                # 10-Q, 10-K, 10-Q405, 10-K405
                # OR 8-K with items in {'2.02', '12', '1.03', '2.01'}
                is_periodic = form in {'10-Q', '10-K', '10-Q405', '10-K405'}
                is_8k_match = (form.startswith('8-K') and check_8k_items(raw_items))

                if not (is_periodic or is_8k_match):
                    continue

                seen_accessions.add(accn)
                timing = parse_session_timing(adt)

                items_str = ""
                if isinstance(raw_items, list):
                    items_str = ",".join(str(x) for x in raw_items)
                elif raw_items:
                    items_str = str(raw_items).strip()

                row_dict = {
                    'ticker': ticker,
                    'cik': cik,
                    'entity_name': actual_name,
                    'form': form,
                    'filingDate': f_date,
                    'reportDate': r_date if r_date else '',
                    'acceptanceDateTime': adt if adt else None,
                    'items': items_str,
                    'accessionNumber': accn,
                    'session_timing': timing,
                    '_primaryDocument': pdoc
                }
                all_records.append(row_dict)
                ticker_filings.append(row_dict)

        filings_index[ticker] = ticker_filings

    df_filings = pd.DataFrame(all_records)
    print(f"Total extracted filings rows before save: {len(df_filings)}")
    if not df_filings.empty:
        # Drop temporary doc column before parquet save
        df_save = df_filings.drop(columns=['_primaryDocument'], errors='ignore')
        out_path = os.path.join(TMP_OUTPUT_DIR, "sec_filings_1995_2026_partB.parquet")
        df_save.to_parquet(out_path, index=False)
        print(f"Saved Part 1 filings to {out_path} ({os.path.getsize(out_path):,} bytes)")

    return df_filings, filings_index

def parse_selected_financials_doc(html_text, target_year):
    """
    Parses Selected Financial Data from 10-K document (HTML table or ASCII table)
    for target_year. Returns dict with revenue, op_income, net_income, total_assets,
    stockholders_equity, shares. If not found, returns NaNs.
    """
    empty_res = {
        'revenue': np.nan, 'op_income': np.nan, 'net_income': np.nan,
        'total_assets': np.nan, 'stockholders_equity': np.nan, 'shares': np.nan
    }
    if not html_text:
        return empty_res

    target_str = str(target_year)
    m = re.search(r'ITEM\s+6\.?\s+SELECTED\s+FINANCIAL\s+DATA', html_text, re.IGNORECASE)
    if not m:
        m = re.search(r'SELECTED\s+FINANCIAL\s+DATA', html_text, re.IGNORECASE)
    if not m:
        return empty_res

    # Look in the 35KB after Item 6
    chunk = html_text[m.start():m.start()+35000]

    def parse_num(s):
        s = s.replace('$', '').replace(',', '').strip()
        if s.startswith('(') and s.endswith(')'):
            try: return -float(s[1:-1])
            except: return None
        try: return float(s)
        except: return None

    # 1. Try HTML Table parse
    if '<table' in chunk.lower():
        try:
            soup = BeautifulSoup(chunk, 'html.parser')
            tables = soup.find_all('table')
            for table in tables:
                rows = table.find_all('tr')
                years = []
                header_row_idx = -1
                for r_idx, row in enumerate(rows):
                    row_txt = row.get_text(" ", strip=True)
                    found_years = re.findall(r'\b(199\d|200\d|201\d)\b', row_txt)
                    if len(found_years) >= 2 and target_str in found_years:
                        years = found_years
                        header_row_idx = r_idx
                        break
                        
                if years and target_str in years:
                    year_pos = years.index(target_str)
                    res = dict(empty_res)
                    for row in rows[header_row_idx+1:]:
                        row_txt = row.get_text(" ", strip=True)
                        row_lower = row_txt.lower()
                        metric = None
                        if ('sales' in row_lower or 'revenue' in row_lower) and np.isnan(res['revenue']):
                            metric = 'revenue'
                        elif ('operating income' in row_lower or 'operating profit' in row_lower) and np.isnan(res['op_income']):
                            metric = 'op_income'
                        elif ('net income' in row_lower or 'net loss' in row_lower) and np.isnan(res['net_income']):
                            metric = 'net_income'
                        elif 'total assets' in row_lower and np.isnan(res['total_assets']):
                            metric = 'total_assets'
                        elif ('equity' in row_lower or 'shareholders' in row_lower or 'stockholders' in row_lower) and np.isnan(res['stockholders_equity']):
                            metric = 'stockholders_equity'
                        elif 'shares' in row_lower and np.isnan(res['shares']):
                            metric = 'shares'

                        if metric:
                            raw_nums = re.findall(r'[\(\$]?\s*[\d,]+(?:\.\d+)?\s*[\)]?', row_txt)
                            parsed_nums = []
                            for n in raw_nums:
                                val = parse_num(n)
                                if val is not None and int(val) not in range(1990, 2026):
                                    parsed_nums.append(val)
                            if len(parsed_nums) == len(years) or len(parsed_nums) > year_pos:
                                res[metric] = parsed_nums[year_pos]

                    if not np.isnan(res['revenue']) or not np.isnan(res['net_income']):
                        return res
        except Exception:
            pass

    # 2. Try ASCII table parse
    lines = chunk.split('\n')
    years = []
    header_line_idx = -1
    for idx, l in enumerate(lines):
        found = re.findall(r'\b(199\d|200\d|201\d)\b', l)
        if len(found) >= 2 and target_str in found:
            years = found
            header_line_idx = idx
            break

    if years and target_str in years:
        year_pos = years.index(target_str)
        res = dict(empty_res)
        for l in lines[header_line_idx+1:]:
            l_lower = l.lower()
            if 'item 7' in l_lower or '</table' in l_lower:
                break
            metric = None
            if ('sales' in l_lower or 'revenue' in l_lower) and np.isnan(res['revenue']):
                metric = 'revenue'
            elif ('operating income' in l_lower or 'operating profit' in l_lower) and np.isnan(res['op_income']):
                metric = 'op_income'
            elif ('net income' in l_lower or 'net loss' in l_lower) and np.isnan(res['net_income']):
                metric = 'net_income'
            elif 'total assets' in l_lower and np.isnan(res['total_assets']):
                metric = 'total_assets'
            elif ('equity' in l_lower or 'shareholders' in l_lower or 'stockholders' in l_lower) and np.isnan(res['stockholders_equity']):
                metric = 'stockholders_equity'
            elif 'shares' in l_lower and np.isnan(res['shares']):
                metric = 'shares'

            if metric:
                raw_nums = re.findall(r'[\(\$]?\s*[\d,]+(?:\.\d+)?\s*[\)]?', l)
                parsed_nums = []
                for n in raw_nums:
                    val = parse_num(n)
                    if val is not None and int(val) not in range(1990, 2026):
                        parsed_nums.append(val)
                if len(parsed_nums) == len(years) or len(parsed_nums) > year_pos:
                    res[metric] = parsed_nums[year_pos]

        if not np.isnan(res['revenue']) or not np.isnan(res['net_income']):
            return res

    return empty_res

def run_part_2(companies, df_filings, filings_index):
    print(f"\n=== [Step 2] Extracting Pre-2009 Anchored Financials (Part B) ===")
    anchored_rows = []

    # 2A. Extract 2007-2009 Early XBRL Facts for all Part B companies
    print("--- [Step 2A] Processing 2007-2009 Early XBRL for 284 companies ---")
    
    # Financial concepts mapped to canonical fields
    CONCEPT_MAP = {
        'revenue': [
            'Revenues', 'SalesRevenueNet', 'RevenueFromContractWithCustomerExcludingAssessedTax',
            'SalesRevenueGoodsNet', 'TotalRevenuesAndOtherIncome', 'SalesRevenueServicesNet'
        ],
        'op_income': [
            'OperatingIncomeLoss',
            'IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments'
        ],
        'net_income': [
            'NetIncomeLoss', 'ProfitLoss'
        ],
        'total_assets': [
            'Assets'
        ],
        'stockholders_equity': [
            'StockholdersEquity',
            'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'
        ],
        'shares': [
            'CommonStockSharesOutstanding',
            'EntityCommonStockSharesOutstanding',
            'WeightedAverageNumberOfDilutedSharesOutstanding',
            'WeightedAverageNumberOfSharesOutstandingBasic'
        ]
    }

    for idx, comp in enumerate(companies):
        ticker = comp['ticker']
        cik = int(comp['cik'])
        entity_name = comp.get('name', '')

        if (idx + 1) % 50 == 0 or idx == 0:
            print(f"[{idx+1}/{len(companies)}] Fetching companyfacts for {ticker} (CIK {cik:010d})...")

        cf_cache = os.path.join(CACHE_DIR, "companyfacts", f"CIK{cik:010d}.json")
        cf_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
        cf_data = fetch_url(cf_url, cache_path=cf_cache, as_json=True)

        if not cf_data or 'facts' not in cf_data:
            continue

        us_gaap = cf_data.get('facts', {}).get('us-gaap', {})
        dei = cf_data.get('facts', {}).get('dei', {})

        # Collect points grouped by (fy, fp)
        period_data = {}  # key: (fy, fp) -> {'end': str, 'filed': str, 'form': str, metrics: {}}

        def scan_concepts(field_name, concept_list, source_dict):
            for concept in concept_list:
                if concept not in source_dict:
                    continue
                units = source_dict[concept].get('units', {})
                for u_key, items in units.items():
                    for item in items:
                        fy = item.get('fy')
                        fp = item.get('fp', 'FY')
                        val = item.get('val')
                        if fy in [2007, 2008, 2009] and fp in ['FY', 'Q1', 'Q2', 'Q3'] and val is not None:
                            key = (int(fy), str(fp).upper())
                            if key not in period_data:
                                period_data[key] = {
                                    'end': item.get('end', ''),
                                    'filed': item.get('filed', ''),
                                    'form': item.get('form', '10-K' if fp == 'FY' else '10-Q'),
                                    'metrics': {}
                                }
                            if field_name not in period_data[key]['metrics']:
                                period_data[key]['metrics'][field_name] = float(val)

        for field, clist in CONCEPT_MAP.items():
            scan_concepts(field, clist, us_gaap)
            if field == 'shares':
                scan_concepts(field, clist, dei)

        # Now match each period to historical filings for this company
        comp_filings = filings_index.get(ticker, [])

        for (fy, fp), p_info in sorted(period_data.items()):
            p_end = p_info['end']
            metrics = p_info['metrics']
            if not metrics:
                continue

            # Target form type
            target_form_family = {'10-K', '10-K405'} if fp == 'FY' else {'10-Q', '10-Q405'}

            # Find matching historical filing
            matched_filing = None

            # 1. First priority: match exact reportDate
            if p_end:
                for f in comp_filings:
                    if f['form'] in target_form_family and f['reportDate'] == p_end:
                        matched_filing = f
                        break

            # 2. Second priority: match fiscal year / reportDate within 60 days
            if not matched_filing:
                for f in comp_filings:
                    if f['form'] in target_form_family and f['reportDate']:
                        try:
                            f_rdate = datetime.strptime(f['reportDate'], '%Y-%m-%d')
                            p_rdate = datetime.strptime(p_end, '%Y-%m-%d')
                            if abs((f_rdate - p_rdate).days) <= 45:
                                matched_filing = f
                                break
                        except Exception:
                            pass

            # 3. Third priority: match by filingDate in fy or fy+1
            if not matched_filing:
                for f in comp_filings:
                    if f['form'] in target_form_family:
                        f_year = int(f['filingDate'][:4])
                        if fp == 'FY' and (f_year == fy or (f_year == fy + 1 and int(f['filingDate'][5:7]) <= 4)):
                            matched_filing = f
                            break

            if matched_filing:
                # Anchored to the true historical filing date
                filing_date = matched_filing['filingDate']
                adt = matched_filing['acceptanceDateTime']
                timing = matched_filing['session_timing']
                source_tier = 'EARLY_XBRL_ANCHORED'
            else:
                # If never filed historically before that year: strictly DO NOT make effective early!
                filing_date = p_info['filed']
                adt = None
                timing = 'DATE_ONLY'
                source_tier = 'EARLY_XBRL_UNANCHORED_RESTATED'

            anchored_rows.append({
                'ticker': ticker,
                'cik': cik,
                'entity_name': entity_name,
                'fiscal_year': fy,
                'fiscal_period': fp,
                'reportDate': p_end,
                'form': '10-K' if fp == 'FY' else '10-Q',
                'filingDate': filing_date,
                'acceptanceDateTime': adt,
                'session_timing': timing,
                'revenue': metrics.get('revenue', np.nan),
                'op_income': metrics.get('op_income', np.nan),
                'net_income': metrics.get('net_income', np.nan),
                'total_assets': metrics.get('total_assets', np.nan),
                'stockholders_equity': metrics.get('stockholders_equity', np.nan),
                'shares': metrics.get('shares', np.nan),
                'source_tier': source_tier
            })

    print(f"Step 2A produced {len(anchored_rows)} early XBRL anchored rows.")

    # 2B. Top 40 Old Representative Companies Item 6 Selected Financial Data
    print("\n--- [Step 2B] Sampling 1998, 2001, 2004, 2007 10-K Item 6 for Top 40 Old Companies ---")
    
    # Identify top 40 old companies with the most historical pre-2005 10-K filings
    company_oldness = []
    for comp in companies:
        ticker = comp['ticker']
        c_filings = filings_index.get(ticker, [])
        old_10ks = [f for f in c_filings if f['form'] in {'10-K', '10-K405'} and f['filingDate'] < '2005-01-01']
        earliest_fdate = min([f['filingDate'] for f in c_filings]) if c_filings else '9999-99-99'
        company_oldness.append((ticker, len(old_10ks), earliest_fdate, comp))

    # Sort by old 10-K count descending, then earliest filing date ascending, then ticker
    company_oldness.sort(key=lambda x: (-x[1], x[2], x[0]))
    top_40 = [x[3] for x in company_oldness[:40]]
    print(f"Top 5 selected old companies: {[c['ticker'] for c in top_40[:5]]}")
    if len(top_40) >= 40:
        print(f"Top 36-40 selected old companies: {[c['ticker'] for c in top_40[35:40]]}")

    target_sample_years = [1998, 2001, 2004, 2007]

    for idx, comp in enumerate(top_40):
        ticker = comp['ticker']
        cik = int(comp['cik'])
        entity_name = comp.get('name', '')
        c_filings = filings_index.get(ticker, [])

        print(f"[{idx+1}/{len(top_40)}] Parsing Item 6 for {ticker} (CIK {cik:010d})...")

        for ty in target_sample_years:
            # Find the 10-K filed for this target year
            matched_10k = None
            for f in c_filings:
                if f['form'] in {'10-K', '10-K405'}:
                    f_year = int(f['filingDate'][:4])
                    f_month = int(f['filingDate'][5:7])
                    r_year = int(f['reportDate'][:4]) if f['reportDate'] else 0
                    if r_year == ty:
                        matched_10k = f
                        break
                    elif f_year == ty and f_month >= 9:
                        matched_10k = f
                        break
                    elif f_year == ty + 1 and f_month <= 4:
                        matched_10k = f
                        break

            if not matched_10k:
                # Not filed in that year
                anchored_rows.append({
                    'ticker': ticker,
                    'cik': cik,
                    'entity_name': entity_name,
                    'fiscal_year': ty,
                    'fiscal_period': 'FY',
                    'reportDate': f"{ty}-12-31",
                    'form': '10-K',
                    'filingDate': f"{ty+1}-03-31",
                    'acceptanceDateTime': None,
                    'session_timing': 'DATE_ONLY',
                    'revenue': np.nan,
                    'op_income': np.nan,
                    'net_income': np.nan,
                    'total_assets': np.nan,
                    'stockholders_equity': np.nan,
                    'shares': np.nan,
                    'source_tier': 'NOT_FILED'
                })
                continue

            # Download document and parse Item 6
            accn = matched_10k['accessionNumber']
            accn_clean = accn.replace('-', '')
            pdoc = matched_10k.get('_primaryDocument', '')
            
            doc_ext = ".htm" if pdoc and pdoc.endswith(('.htm', '.html')) else ".txt"
            doc_cache = os.path.join(CACHE_DIR, "docs", f"{cik}_{accn}{doc_ext}")

            if pdoc and pdoc.endswith(('.htm', '.html')):
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_clean}/{pdoc}"
            else:
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_clean}/{accn}.txt"

            doc_text = fetch_url(doc_url, cache_path=doc_cache, as_json=False, text_only=True)
            metrics = parse_selected_financials_doc(doc_text, ty)

            anchored_rows.append({
                'ticker': ticker,
                'cik': cik,
                'entity_name': entity_name,
                'fiscal_year': ty,
                'fiscal_period': 'FY',
                'reportDate': matched_10k['reportDate'] if matched_10k['reportDate'] else f"{ty}-12-31",
                'form': matched_10k['form'],
                'filingDate': matched_10k['filingDate'],
                'acceptanceDateTime': matched_10k['acceptanceDateTime'],
                'session_timing': matched_10k['session_timing'],
                'revenue': metrics.get('revenue', np.nan),
                'op_income': metrics.get('op_income', np.nan),
                'net_income': metrics.get('net_income', np.nan),
                'total_assets': metrics.get('total_assets', np.nan),
                'stockholders_equity': metrics.get('stockholders_equity', np.nan),
                'shares': metrics.get('shares', np.nan),
                'source_tier': 'HTML_10K_ITEM6'
            })

    df_anchored = pd.DataFrame(anchored_rows)
    # Deduplicate by (ticker, fiscal_year, fiscal_period, source_tier)
    df_anchored = df_anchored.drop_duplicates(subset=['ticker', 'fiscal_year', 'fiscal_period', 'source_tier'], keep='last')
    
    out_anchored_path = os.path.join(TMP_OUTPUT_DIR, "pre2009_comp_anchored_partB.parquet")
    df_anchored.to_parquet(out_anchored_path, index=False)
    print(f"\nSaved Part 2 anchored financials to {out_anchored_path} ({os.path.getsize(out_anchored_path):,} bytes, {len(df_anchored)} rows)")

    return df_anchored

def main():
    start_time = time.time()
    print("=== Starting W1_08 Pre-2009 Shard B Extractor ===")
    companies = load_part_b_companies()
    print(f"Loaded {len(companies)} Part B companies.")
    print(f"Sample tickers: {[c['ticker'] for c in companies[:10]]}")

    # Step 1: SEC filings 1995-2026
    df_filings, filings_index = run_part_1(companies)

    # Step 2: Anchored financials
    df_anchored = run_part_2(companies, df_filings, filings_index)

    elapsed = time.time() - start_time
    print(f"\n=== W1_08 Finished in {elapsed:.1f} seconds ===")
    print("--- Summary Verification ---")
    print(f"Filings rows: {len(df_filings):,}")
    if not df_filings.empty:
        print(f"Filings date range: {df_filings['filingDate'].min()} to {df_filings['filingDate'].max()}")
        print(f"Filings session timing counts:\n{df_filings['session_timing'].value_counts().to_dict()}")
        print(f"Filings form counts:\n{df_filings['form'].value_counts().head(10).to_dict()}")

    print(f"\nAnchored financial rows: {len(df_anchored):,}")
    if not df_anchored.empty:
        print(f"Source tiers:\n{df_anchored['source_tier'].value_counts().to_dict()}")
        print(f"Non-null counts:\n{df_anchored[['revenue', 'op_income', 'net_income', 'total_assets', 'stockholders_equity', 'shares']].notna().sum().to_dict()}")

if __name__ == "__main__":
    main()