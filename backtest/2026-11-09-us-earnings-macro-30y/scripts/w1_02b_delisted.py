"""
W1_02B: Survivor Bias Patching and Delisted / M&A Terminal Value Builder (Shard 1)
Author: W1_02B Subagent
Date: 2026-11-09
"""

import os
import sys
import json
import time
import subprocess
import datetime
import numpy as np
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor

SHARD_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/shards/delisted_shard_1.json"
PIT_PATH = "/tmp/pit_panel_enriched_20261106.parquet"

OUTPUT_DIR = "/tmp/us_earn_macro_bt_20261109/delisted_prices"
OUTPUT_PRICES_PATH = os.path.join(OUTPUT_DIR, "delisted_prices_1.parquet")
OUTPUT_META_PATH = os.path.join(OUTPUT_DIR, "delisted_meta_1.parquet")
OUTPUT_HC_META_PATH = os.path.join(OUTPUT_DIR, "hc_delisted_61_meta.parquet")
SEC_CACHE_PATH = os.path.join(OUTPUT_DIR, "sec_cache.json")

SEC_USER_AGENT = "OHIM Research buwen@ohim.com"

# Known M&A acquisitions from historical record
KNOWN_MA = {
    'ABI', 'ABX', 'ACV', 'ALTR', 'AMCC', 'ANDW', 'APOL', 'ARG', 'ASC', 'AT', 'BAY', 'BBI',
    'BDK', 'BEV', 'BFI', 'BGEN', 'BHGE', 'BLL', 'BLY', 'BMET', 'BMS', 'BNL', 'BOL', 'BSC',
    'BXLT', 'CBB', 'CBH', 'CBSS', 'CCE', 'CEPH', 'CFC', 'CFN', 'CIN', 'CMB', 'CMVT', 'CNG',
    'CNXT', 'COG', 'COMS', 'CPGX', 'CPQ', 'CRR', 'CTB', 'CTLT', 'CTX', 'CVC', 'CVH', 'CYM',
    'DI', 'DISCA', 'DISH', 'DNR', 'DTV', 'DWDP', 'ECO', 'EOP', 'ESV', 'FBF', 'FDC', 'FG',
    'FPC', 'FRX', 'FSL', 'FTR', 'GDT', 'GENZ', 'GGP', 'GMCR', 'GP', 'GPU', 'GRA', 'GTW',
    'GX', 'HCR', 'HES', 'HFC', 'HI', 'HMA', 'HPC', 'HRS', 'HSP', 'IAC', 'IKN', 'INCLF',
    'JOY', 'KATE', 'KMG', 'KRB', 'KRI', 'KSU', 'LDG', 'LLL', 'LLX', 'LO', 'LXK', 'MDR',
    'MEDI', 'MEL', 'MERQ', 'MHS', 'MII', 'MKG', 'MMI', 'MNR', 'MOLX', 'MRO', 'MTL', 'MWV',
    'MYL', 'NAE', 'NBL', 'NCC', 'NCR', 'NFX', 'NLC', 'NLSN', 'NMK', 'NSM', 'NXTL', 'NYX',
    'OM', 'PBG', 'PCS', 'PET', 'PGL', 'PHA', 'PKI', 'PMCS', 'PNU', 'PTV', 'PVT', 'QEP',
    'RAI', 'RDC', 'RLM', 'RNB', 'RRD', 'RTN', 'RYC', 'SAF', 'SAPE', 'SBL', 'SCG', 'SEBL',
    'SFS', 'SGID', 'SIAL', 'SLR', 'SMS', 'SOTR', 'SRR', 'STJ', 'STR', 'SVU', 'SWY',
    'SYMC', 'TCOMA', 'TEG', 'TEN', 'THY', 'TIF', 'TLAB', 'TNB', 'TOY', 'TRW', 'TSS',
    'TWC', 'TWX', 'UCL', 'UMG', 'USBC', 'USHC', 'UST', 'UTX', 'VAR', 'VIAB', 'VMW',
    'VRTS', 'VTSS', 'WCG', 'WFM', 'WIN', 'WLL', 'WLTW', 'WPX', 'WWY', 'WYND', 'XEC',
    'XLNX', 'YNR'
}

# Known Chapter 11 / Liquidations
KNOWN_BK = {
    'AAMRQ', 'BTUUQ', 'CITGQ', 'DALRQ', 'DCNAQ', 'DPHIQ', 'EKDKQ', 'FLMIQ', 'FLTWQ', 'GAPTQ',
    'LEHMQ', 'MIR', 'NRTLQ', 'OWENQ', 'UAWGQ', 'WAMUQ', 'WNDXQ', 'CHK', 'ENE', 'JCP',
    'SAVE', 'SHLD', 'SIVB', 'WCOM'
}


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def extract_hc_61_meta():
    print(f"Extracting 61 HC delisted meta from {PIT_PATH}...")
    if not os.path.exists(PIT_PATH):
        print(f"Warning: PIT path {PIT_PATH} does not exist.")
        return
    df_pit = pd.read_parquet(PIT_PATH)
    delisted = df_pit[df_pit['is_delisted'] == True]
    cols = ['ticker', 'cik', 'name', 'delist_dt', 'is_delisted']
    avail_cols = [c for c in cols if c in delisted.columns]
    hc_meta = delisted[avail_cols].drop_duplicates(subset=['ticker']).copy()
    hc_meta.sort_values('ticker', inplace=True)
    hc_meta.reset_index(drop=True, inplace=True)
    hc_meta.to_parquet(OUTPUT_HC_META_PATH, index=False)
    print(f"Saved {len(hc_meta)} HC delisted meta records to {OUTPUT_HC_META_PATH}")


def fetch_sec_submission(cik):
    """
    Fetch SEC submission JSON via curl with rate limit compliance.
    """
    url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    cmd = [
        "curl", "-sL", "--retry", "3",
        "-H", f"User-Agent: {SEC_USER_AGENT}",
        url
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if res.returncode == 0 and res.stdout.startswith('{'):
            return json.loads(res.stdout)
    except Exception as e:
        print(f"Error fetching CIK {cik}: {e}")
    return None


def parse_sec_submission(data):
    """
    Analyze SEC submission records for exit event.
    """
    if not data:
        return None, None, None, None, "UNRESOLVED_HISTORICAL", ""

    name = data.get('name', '')
    recent = data.get('filings', {}).get('recent', {})
    forms = recent.get('form', [])
    dates = recent.get('filingDate', [])
    items = recent.get('items', [])

    last_filing_date = dates[0] if dates else None
    last_form = forms[0] if forms else None

    # Check for active ongoing reporting in 2026
    is_active_2026 = False
    for f, d in zip(forms[:15], dates[:15]):
        if d and d >= '2026-01-01' and f in ['10-K', '10-Q', '10-K/A', '10-Q/A', '8-K', '4', 'SC 13G', 'SC 13G/A']:
            is_active_2026 = True
            break

    # Look for bankruptcy 8-K item 1.03
    for f, d, it in zip(forms[:60], dates[:60], items[:60]):
        it_str = str(it) if it is not None else ""
        if '1.03' in it_str:
            return name, last_filing_date, last_form, d, "BANKRUPTCY_OR_LIQUIDATION", f"SEC 8-K Item 1.03 Bankruptcy on {d}"

    # Look for acquisition 8-K item 2.01
    for f, d, it in zip(forms[:60], dates[:60], items[:60]):
        it_str = str(it) if it is not None else ""
        if '2.01' in it_str:
            return name, last_filing_date, last_form, d, "MA_ACQUISITION", f"SEC 8-K Item 2.01 Acquisition on {d}"

    # Look for deregistration 25-NSE or 15-12G / 15-12B
    for f, d in zip(forms[:40], dates[:40]):
        if f in ['25-NSE', '25', '15-12G', '15-12B', '15-15D']:
            return name, last_filing_date, last_form, d, "MA_ACQUISITION", f"SEC Form {f} Deregistration on {d}"

    if is_active_2026:
        return name, last_filing_date, last_form, last_filing_date, "DEMOTED_STILL_TRADING", "Active SEC filer in 2026"

    return name, last_filing_date, last_form, None, "UNRESOLVED_HISTORICAL", "No definitive SEC event found"


def fetch_and_validate_price(item):
    """
    Fetch daily price via yfinance and validate against anti-pollution criteria.
    """
    ticker = item['ticker']
    sp_start = item['sp_start']
    sp_end = item['sp_end']

    t_clean = ticker.replace('.', '-')
    df = None
    used_ticker = t_clean

    # 1. Try clean ticker
    try:
        df = yf.download(t_clean, start="1995-01-01", end="2026-11-09", auto_adjust=False, progress=False)
    except Exception:
        pass

    # 2. Try + 'Q' if empty and ticker does not end in Q
    if (df is None or df.empty) and not t_clean.endswith('Q'):
        try:
            df = yf.download(t_clean + "Q", start="1995-01-01", end="2026-11-09", auto_adjust=False, progress=False)
            if df is not None and not df.empty:
                used_ticker = t_clean + "Q"
        except Exception:
            pass

    if df is None or df.empty:
        return ticker, False, None, None, None, None, "NO_PRICE_DATA"

    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0].lower() for col in df.columns]
    else:
        df.columns = [col.lower() for col in df.columns]

    # Required columns check
    req_cols = ['open', 'high', 'low', 'close', 'adj close', 'volume']
    if 'adj close' in df.columns:
        df.rename(columns={'adj close': 'adj_close'}, inplace=True)

    p_first = df.index[0].strftime('%Y-%m-%d')
    p_last = df.index[-1].strftime('%Y-%m-%d')
    last_close = float(df['close'].iloc[-1])

    s_start = pd.to_datetime(sp_start) if pd.notnull(sp_start) and str(sp_start).lower() != 'nan' else pd.to_datetime('1996-01-01')
    s_end = pd.to_datetime(sp_end) if pd.notnull(sp_end) and str(sp_end).lower() != 'nan' else pd.to_datetime('2026-11-09')

    overlap_mask = (df.index >= s_start) & (df.index <= s_end)
    overlap_days = int(overlap_mask.sum())

    sp_trading_days = max(5, int((s_end - s_start).days * 5 / 7))
    min_overlap = min(60, sp_trading_days)

    # Validation Rule 1: price_first <= sp_end and overlap >= min_overlap
    if p_first > s_end.strftime('%Y-%m-%d'):
        return ticker, False, p_first, p_last, last_close, None, f"TICKER_REUSED_REJECTED (price_first {p_first} > sp_end {s_end.strftime('%Y-%m-%d')})"

    if overlap_days < min_overlap:
        return ticker, False, p_first, p_last, last_close, None, f"TICKER_REUSED_REJECTED (overlap {overlap_days} < min_overlap {min_overlap})"

    # Validation Rule 2: If sp_end < 2026-01-01 and price_last in late 2026
    if s_end < pd.to_datetime('2026-01-01') and p_last >= '2026-10-01':
        # Check start date not excessively late (> 5 years after sp_start)
        if pd.to_datetime(p_first) > s_start + pd.Timedelta(days=5*365):
            return ticker, False, p_first, p_last, last_close, None, f"TICKER_REUSED_REJECTED (price_first {p_first} > sp_start + 5y)"

    # Format price dataframe for export
    clean_df = df[['open', 'high', 'low', 'close', 'adj_close', 'volume']].copy()
    clean_df.reset_index(inplace=True)
    if 'Date' in clean_df.columns:
        clean_df.rename(columns={'Date': 'date'}, inplace=True)
    elif 'index' in clean_df.columns:
        clean_df.rename(columns={'index': 'date'}, inplace=True)
    clean_df['ticker'] = ticker

    # Reorder columns
    clean_df = clean_df[['date', 'ticker', 'open', 'high', 'low', 'close', 'adj_close', 'volume']]

    return ticker, True, p_first, p_last, last_close, clean_df, f"VALID_PRICE ({len(df)} rows, overlap {overlap_days}d)"


def main():
    ensure_dir(OUTPUT_DIR)
    extract_hc_61_meta()

    with open(SHARD_PATH) as f:
        shard = json.load(f)
    print(f"Loaded {len(shard)} items from shard 1.")

    # 1. SEC Submissions Check (using cache if available or querying)
    sec_info = {}
    items_with_cik = [x for x in shard if x.get('cik')]

    if os.path.exists(SEC_CACHE_PATH):
        print(f"Loading SEC metadata from cache: {SEC_CACHE_PATH}")
        with open(SEC_CACHE_PATH) as f:
            cached_data = json.load(f)
        for t, val in cached_data.items():
            # Check for known active / events
            name = val.get('sec_name', '')
            l_form = val.get('last_sec_form', '')
            l_filing = val.get('last_sec_filing', '')
            exit_t = "UNRESOLVED_HISTORICAL"
            note = ""
            if l_form in ['15-12G', '25-NSE', '15-12B']:
                exit_t = "MA_ACQUISITION"
                note = f"SEC Form {l_form} Deregistration on {l_filing}"
            elif l_filing and l_filing >= '2026-01-01':
                exit_t = "DEMOTED_STILL_TRADING"
                note = f"Active SEC filer in 2026 ({l_form})"
            sec_info[t] = {
                'sec_name': name,
                'last_sec_filing': l_filing,
                'last_sec_form': l_form,
                'sec_exit_type': exit_t,
                'sec_note': note
            }
        # Explicit overrides for SEC items verified earlier
        sec_info['ABMD'] = {'sec_name': 'ABIOMED INC', 'last_sec_filing': '2023-01-06', 'last_sec_form': 'SC 13G/A', 'sec_exit_type': 'MA_ACQUISITION', 'sec_note': 'SEC 8-K Item 2.01 Acquisition on 2022-12-22'}
        sec_info['AGN'] = {'sec_name': 'ALLERGAN INC', 'last_sec_filing': '2016-02-10', 'last_sec_form': 'SC 13G/A', 'sec_exit_type': 'MA_ACQUISITION', 'sec_note': 'SEC 8-K Item 2.01 Acquisition on 2015-03-18'}
        sec_info['ANSS'] = {'sec_name': 'ANSYS INC', 'last_sec_filing': '2025-07-30', 'last_sec_form': 'EFFECT', 'sec_exit_type': 'MA_ACQUISITION', 'sec_note': 'SEC 8-K Item 2.01 Acquisition on 2025-07-17'}
        sec_info['ATVI'] = {'sec_name': 'Activision Blizzard, Inc.', 'last_sec_filing': '2024-06-11', 'last_sec_form': 'SC 13G/A', 'sec_exit_type': 'MA_ACQUISITION', 'sec_note': 'Deregistration after Microsoft acquisition'}
        sec_info['CELG'] = {'sec_name': 'CELGENE CORP /DE/', 'last_sec_filing': '2020-07-13', 'last_sec_form': '4', 'sec_exit_type': 'MA_ACQUISITION', 'sec_note': 'SEC 8-K Item 2.01 Acquisition on 2019-11-22'}
        sec_info['DFS'] = {'sec_name': 'Discover Financial Services', 'last_sec_filing': '2025-05-19', 'last_sec_form': '8-K', 'sec_exit_type': 'MA_ACQUISITION', 'sec_note': 'Acquired by Capital One in 2025'}
        sec_info['HZNP'] = {'sec_name': 'Horizon Therapeutics Public Ltd Co', 'last_sec_filing': '2023-10-19', 'last_sec_form': '15-12G', 'sec_exit_type': 'MA_ACQUISITION', 'sec_note': 'Acquired by Amgen in 2023'}
        sec_info['MXIM'] = {'sec_name': 'MAXIM INTEGRATED PRODUCTS INC', 'last_sec_filing': '2021-08-30', 'last_sec_form': '8-K', 'sec_exit_type': 'MA_ACQUISITION', 'sec_note': 'SEC 8-K Item 2.01 Acquisition on 2021-08-30'}
        sec_info['PXD'] = {'sec_name': 'PIONEER NATURAL RESOURCES CO', 'last_sec_filing': '2024-05-08', 'last_sec_form': '8-K', 'sec_exit_type': 'MA_ACQUISITION', 'sec_note': 'SEC 8-K Item 2.01 Acquisition on 2024-05-08'}
        sec_info['SAVE'] = {'sec_name': 'Spirit Aviation Holdings, Inc.', 'last_sec_filing': '2026-11-04', 'last_sec_form': '8-K', 'sec_exit_type': 'BANKRUPTCY_OR_LIQUIDATION', 'sec_note': 'SEC 8-K Item 1.03 Bankruptcy Chapter 11'}
        sec_info['SPLK'] = {'sec_name': 'SPLUNK INC', 'last_sec_filing': '2024-03-28', 'last_sec_form': '15-12G', 'sec_exit_type': 'MA_ACQUISITION', 'sec_note': 'SEC 8-K Item 2.01 Acquisition on 2024-03-18'}
        sec_info['VMW'] = {'sec_name': 'VMWARE, INC.', 'last_sec_filing': '2023-11-22', 'last_sec_form': '15-12B', 'sec_exit_type': 'MA_ACQUISITION', 'sec_note': 'SEC 8-K Item 2.01 Acquisition on 2023-11-22'}
        sec_info['XLNX'] = {'sec_name': 'XILINX INC', 'last_sec_filing': '2022-02-15', 'last_sec_form': '8-K', 'sec_exit_type': 'MA_ACQUISITION', 'sec_note': 'SEC 8-K Item 2.01 Acquisition on 2022-02-14'}
        sec_info['SIVB'] = {'sec_name': 'SVB FINANCIAL GROUP', 'last_sec_filing': '2023-03-17', 'last_sec_form': '8-K', 'sec_exit_type': 'BANKRUPTCY_OR_LIQUIDATION', 'sec_note': 'Chapter 11 Bankruptcy petition on 2023-03-17'}
        sec_info['SHLD'] = {'sec_name': 'SEARS HOLDINGS CORP', 'last_sec_filing': '2019-01-22', 'last_sec_form': '8-K', 'sec_exit_type': 'BANKRUPTCY_OR_LIQUIDATION', 'sec_note': 'Chapter 11 Bankruptcy petition on 2018-10-15'}
        sec_info['WCOM'] = {'sec_name': 'WORLDCOM INC', 'last_sec_filing': '2004-04-20', 'last_sec_form': '8-K', 'sec_exit_type': 'BANKRUPTCY_OR_LIQUIDATION', 'sec_note': 'Chapter 11 Bankruptcy petition on 2002-07-21'}
        sec_info['ENE'] = {'sec_name': 'ENRON CORP', 'last_sec_filing': '2004-11-17', 'last_sec_form': '8-K', 'sec_exit_type': 'BANKRUPTCY_OR_LIQUIDATION', 'sec_note': 'Chapter 11 Bankruptcy petition on 2001-12-02'}
        sec_info['JCP'] = {'sec_name': 'J C PENNEY CO INC', 'last_sec_filing': '2020-05-18', 'last_sec_form': '8-K', 'sec_exit_type': 'BANKRUPTCY_OR_LIQUIDATION', 'sec_note': 'Chapter 11 Bankruptcy petition on 2020-05-15'}
        sec_info['CHK'] = {'sec_name': 'EXPAND ENERGY Corp', 'last_sec_filing': '2026-11-02', 'last_sec_form': '4', 'sec_exit_type': 'BANKRUPTCY_OR_LIQUIDATION', 'sec_note': 'Chesapeake Energy Chapter 11 bankruptcy in 2020'}
    else:
        print(f"Fetching SEC submissions for {len(items_with_cik)} items with CIK...")
        for idx, item in enumerate(items_with_cik, 1):
            cik = item['cik']
            t = item['ticker']
            data = fetch_sec_submission(cik)
            name, last_filing_date, last_form, event_date, exit_type, note = parse_sec_submission(data)
            sec_info[t] = {
                'sec_name': name,
                'last_sec_filing': last_filing_date,
                'last_sec_form': last_form,
                'sec_exit_type': exit_type,
                'sec_note': note
            }
            time.sleep(0.85)

    # 2. Check Prices
    # Load previously verified price parquet if present, else probe
    if os.path.exists(OUTPUT_PRICES_PATH) and os.path.getsize(OUTPUT_PRICES_PATH) > 100000:
        print(f"Loading verified prices from existing {OUTPUT_PRICES_PATH}...")
        df_prices_prev = pd.read_parquet(OUTPUT_PRICES_PATH)
        valid_tickers = set(df_prices_prev['ticker'].unique())
        print(f"Loaded existing prices: {len(df_prices_prev)} rows across {len(valid_tickers)} tickers: {sorted(valid_tickers)}")
        
        # Build price_results
        price_results = {}
        for item in shard:
            t = item['ticker']
            if t in valid_tickers:
                sub = df_prices_prev[df_prices_prev['ticker'] == t]
                price_results[t] = {
                    'has_price': True,
                    'p_first': str(sub['date'].min())[:10],
                    'p_last': str(sub['date'].max())[:10],
                    'last_close': float(sub['close'].iloc[-1]),
                    'price_note': f"VALID_PRICE ({len(sub)} rows)"
                }
            else:
                # check if probe had ticker reuse note
                price_results[t] = {
                    'has_price': False,
                    'p_first': None,
                    'p_last': None,
                    'last_close': None,
                    'price_note': 'NO_VALID_PRICE_OR_REUSED_REJECTED'
                }
    else:
        print("Warmup yfinance and probe prices...")
        yf.Ticker('SPY').history(period='1d')
        price_results = {}
        valid_price_dfs = []
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(fetch_and_validate_price, item): item for item in shard}
            for future in futures:
                ticker, has_price, p_first, p_last, last_close, clean_df, note = future.result()
                price_results[ticker] = {
                    'has_price': has_price,
                    'p_first': p_first,
                    'p_last': p_last,
                    'last_close': last_close,
                    'price_note': note
                }
                if has_price and clean_df is not None:
                    valid_price_dfs.append(clean_df)
        if valid_price_dfs:
            df_prices = pd.concat(valid_price_dfs, ignore_index=True)
            df_prices.to_parquet(OUTPUT_PRICES_PATH, index=False)

    # 3. Assemble Metadata Table
    meta_rows = []
    for item in shard:
        ticker = item['ticker']
        cik = item.get('cik')
        sp_start = str(item.get('sp_start'))
        sp_end = str(item.get('sp_end'))

        p_res = price_results.get(ticker, {})
        has_price = p_res.get('has_price', False)
        p_first = p_res.get('p_first')
        p_last = p_res.get('p_last')
        last_close = p_res.get('last_close')
        price_note = p_res.get('price_note', '')

        s_res = sec_info.get(ticker, {})
        sec_name = s_res.get('sec_name') or ''
        last_sec_filing = s_res.get('last_sec_filing')
        last_sec_form = s_res.get('last_sec_form')
        sec_exit_type = s_res.get('sec_exit_type')
        sec_note = s_res.get('sec_note', '')

        # Classification Hierarchy
        exit_type = "UNRESOLVED_HISTORICAL"
        notes = []

        is_5letter_q = (len(ticker) == 5 and ticker.endswith('Q'))
        is_known_bk = ticker in KNOWN_BK or is_5letter_q

        if is_known_bk:
            exit_type = "BANKRUPTCY_OR_LIQUIDATION"
            notes.append("Bankruptcy Chapter 11 / Q ticker" if is_5letter_q else f"Known Bankruptcy ({ticker})")
        elif sec_exit_type == "BANKRUPTCY_OR_LIQUIDATION":
            exit_type = "BANKRUPTCY_OR_LIQUIDATION"
            notes.append(sec_note)
        elif has_price and p_last and p_last >= '2026-10-01':
            exit_type = "DEMOTED_STILL_TRADING"
            notes.append("Continuous trading to late 2026 (demoted from SP500)")
        elif sec_exit_type == "MA_ACQUISITION":
            exit_type = "MA_ACQUISITION"
            notes.append(sec_note)
        elif ticker in KNOWN_MA:
            exit_type = "MA_ACQUISITION"
            notes.append("Historical M&A / Corporate acquisition")
        elif sec_name and has_price:
            exit_type = "DEMOTED_STILL_TRADING"
            notes.append("Continuous trading on exchange")
        else:
            exit_type = "UNRESOLVED_HISTORICAL"
            notes.append("Historical removal without definitive record")

        # Terminal delist return calculation
        terminal_delist_ret = 0.0
        if exit_type == "BANKRUPTCY_OR_LIQUIDATION":
            if has_price and last_close is not None and last_close < 1.0:
                terminal_delist_ret = -0.50
            else:
                terminal_delist_ret = -0.95
        elif exit_type in ["MA_ACQUISITION", "DEMOTED_STILL_TRADING", "UNRESOLVED_HISTORICAL"]:
            terminal_delist_ret = 0.0

        meta_rows.append({
            'ticker': ticker,
            'cik': int(cik) if cik is not None and str(cik).isdigit() else None,
            'sec_name': sec_name,
            'sp_start': sp_start,
            'sp_end': sp_end,
            'has_price': has_price,
            'price_first': p_first,
            'price_last': p_last,
            'last_sec_filing': last_sec_filing,
            'last_sec_form': last_sec_form,
            'exit_type': exit_type,
            'terminal_delist_ret': float(terminal_delist_ret),
            'notes': "; ".join(notes)
        })

    df_meta = pd.DataFrame(meta_rows)
    df_meta.to_parquet(OUTPUT_META_PATH, index=False)
    print(f"Saved {len(df_meta)} rows to {OUTPUT_META_PATH}")

    # Summary
    print("\n=== SUMMARY STATISTICS ===")
    print("Exit type counts:")
    print(df_meta['exit_type'].value_counts())
    print("\nStocks with clean valid prices:", df_meta['has_price'].sum())
    print("Metadata shape:", df_meta.shape)
    print("==========================")


if __name__ == "__main__":
    main()
