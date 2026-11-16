import os
import json
import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from .cache_manager import save_json_gz, load_json_gz, SUB_CACHE
from .rate_limiter import fetch_sec_json

SUBMISSIONS_ZIP = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_fundamentals_30y_permanent/bulk_zip/submissions.zip"
OUT_PARQUET = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_fundamentals_30y_permanent/pre2009/sec_filings_1995_2009_pit.parquet"

def parse_session_timing(adt_str):
    if not adt_str or len(str(adt_str)) < 10:
        return 'DATE_ONLY'
    try:
        s = str(adt_str).strip().replace('.000Z', 'Z').replace('Z', '+00:00')
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo('UTC'))
        dt_et = dt.astimezone(ZoneInfo('America/New_York'))
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
    return bool(item_set & {'2.02', '12', '1.03', '2.01'})

def run_step_a(universe):
    """
    Step A: Harvests 1995-2009 filings (10-K, 10-K405, 10-Q, 10-Q405, and select 8-K)
    for all companies in universe. Caches in raw_sec_cache/submissions/ as .json.gz.
    Saves sec_filings_1995_2009_pit.parquet.
    """
    if os.path.exists(OUT_PARQUET) and os.path.getsize(OUT_PARQUET) > 100000:
        df_cached = pd.read_parquet(OUT_PARQUET)
        if len(df_cached) >= 50000:
            print(f"=== [Step A] Loaded {len(df_cached):,} filings from cache {OUT_PARQUET} ===")
            filings_index = {}
            for r in df_cached.to_dict('records'):
                t = r['ticker']
                if t not in filings_index:
                    filings_index[t] = []
                filings_index[t].append(r)
            return df_cached, filings_index

    print(f"\n=== [Step A] Harvesting SEC Filings (1995-2009) for {len(universe)} Companies ===")
    
    zip_obj = None
    zip_names = set()
    if os.path.exists(SUBMISSIONS_ZIP):
        zip_obj = zipfile.ZipFile(SUBMISSIONS_ZIP, 'r')
        zip_names = set(zip_obj.namelist())
        print(f"Loaded bulk submissions.zip ({len(zip_names):,} files)")

    all_rows = []
    filings_index = {}  # ticker -> list of row dicts

    for idx, comp in enumerate(universe):
        ticker = comp['ticker']
        cik = int(comp['cik'])
        comp_name = comp.get('name', '')

        if (idx + 1) % 100 == 0 or idx == 0:
            print(f"[{idx+1}/{len(universe)}] Processing submissions for {ticker} (CIK {cik:010d})...")

        main_fname = f"CIK{cik:010d}.json"
        main_cache_path = os.path.join(SUB_CACHE, f"CIK{cik:010d}.json.gz")
        data = load_json_gz(main_cache_path)

        if data is None:
            if zip_obj and main_fname in zip_names:
                try:
                    data = json.loads(zip_obj.read(main_fname))
                    save_json_gz(main_cache_path, data)
                except Exception:
                    data = None
            if data is None:
                url = f"https://data.sec.gov/submissions/{main_fname}"
                data = fetch_sec_json(url, cache_path=main_cache_path)

        if not data or not isinstance(data, dict):
            continue

        actual_name = data.get('name', comp_name)
        comp_records = []
        recent = data.get('filings', {}).get('recent', {})
        if recent and 'form' in recent:
            comp_records.append(recent)

        # Historical files
        hist_files = data.get('filings', {}).get('files', [])
        for hf in hist_files:
            fname = hf.get('name')
            if not fname:
                continue
            h_cache_path = os.path.join(SUB_CACHE, f"{fname}.gz")
            h_data = load_json_gz(h_cache_path)
            if h_data is None:
                if zip_obj and fname in zip_names:
                    try:
                        h_data = json.loads(zip_obj.read(fname))
                        save_json_gz(h_cache_path, h_data)
                    except Exception:
                        h_data = None
                if h_data is None:
                    h_url = f"https://data.sec.gov/submissions/{fname}"
                    h_data = fetch_sec_json(h_url, cache_path=h_cache_path)
            if h_data and isinstance(h_data, dict) and 'form' in h_data:
                comp_records.append(h_data)

        seen_accns = set()
        ticker_filings = []

        for rec in comp_records:
            forms = rec.get('form', [])
            fdates = rec.get('filingDate', [])
            rdates = rec.get('reportDate', [])
            adts = rec.get('acceptanceDateTime', [])
            items_list = rec.get('items', [])
            accns = rec.get('accessionNumber', [])
            pdocs = rec.get('primaryDocument', [])

            for i in range(len(forms)):
                fdate = fdates[i] if i < len(fdates) else ''
                # Filter 1995 to 2010 to allow late 2008 filings
                if not fdate or not ('1995-01-01' <= fdate <= '2010-04-30'):
                    continue

                form = forms[i] if i < len(forms) else ''
                accn = accns[i] if i < len(accns) else ''
                if accn in seen_accns:
                    continue

                raw_items = items_list[i] if i < len(items_list) else ''
                is_periodic = form in {'10-K', '10-K405', '10-Q', '10-Q405'}
                is_8k_match = form.startswith('8-K') and check_8k_items(raw_items)

                if not (is_periodic or is_8k_match):
                    continue

                seen_accns.add(accn)
                rdate = rdates[i] if i < len(rdates) else ''
                adt = adts[i] if i < len(adts) else ''
                pdoc = pdocs[i] if i < len(pdocs) else ''
                timing = parse_session_timing(adt)

                items_str = ""
                if isinstance(raw_items, list):
                    items_str = ",".join(str(x) for x in raw_items)
                elif raw_items:
                    items_str = str(raw_items).strip()

                row = {
                    'ticker': ticker,
                    'cik': cik,
                    'entity_name': actual_name,
                    'form': form,
                    'filingDate': fdate,
                    'reportDate': rdate,
                    'acceptanceDateTime': adt,
                    'session_timing': timing,
                    'items': items_str,
                    'accessionNumber': accn,
                    'primaryDocument': pdoc,
                    '_primaryDocument': pdoc
                }
                all_rows.append(row)
                ticker_filings.append(row)

        filings_index[ticker] = ticker_filings

    if zip_obj:
        zip_obj.close()

    df_filings = pd.DataFrame(all_rows)
    print(f"Step A extracted {len(df_filings):,} filing records across {len(filings_index)} companies.")

    if not df_filings.empty:
        df_save = df_filings.drop(columns=['_primaryDocument'], errors='ignore')
        os.makedirs(os.path.dirname(OUT_PARQUET), exist_ok=True)
        df_save.to_parquet(OUT_PARQUET, index=False)
        print(f"Saved Step A filings to {OUT_PARQUET} ({os.path.getsize(OUT_PARQUET):,} bytes)")

    return df_filings, filings_index
