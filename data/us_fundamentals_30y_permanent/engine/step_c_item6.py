import os
import re
from datetime import datetime
from bs4 import BeautifulSoup
import numpy as np
import pandas as pd
from .cache_manager import save_text_gz, load_text_gz, DOCS_CACHE
from .rate_limiter import fetch_sec_text

def clean_num(s):
    if not s:
        return np.nan
    s = s.replace('$', '').replace(',', '').strip()
    if s.startswith('(') and s.endswith(')'):
        try:
            return -float(s[1:-1].strip())
        except Exception:
            return np.nan
    try:
        return float(s)
    except Exception:
        return np.nan

def parse_item6_table(text):
    """
    Parses Item 6 Selected Financial Data from 10-K text (HTML or ASCII).
    Returns dict: {year_int: {metric: float_raw}}, unit_hint_str
    """
    if not text:
        return {}, "unknown"

    clean_text = text.replace('&nbsp;', ' ').replace('&#160;', ' ')
    
    # Tolerant regex that allows HTML tags between 'Item 6' and 'Selected Financial Data'
    pattern = r'item\s*6(?:\s*<[^>]+>|[^\w\n]){0,150}selected\s+financial\s+data'
    matches = list(re.finditer(pattern, clean_text, re.I))
    if not matches:
        matches = list(re.finditer(r'selected\s+financial\s+data', clean_text, re.I))
    if not matches:
        return {}, "unknown"

    for m in matches:
        chunk = clean_text[m.start():m.start() + 45000]
        chunk_lower = chunk.lower()
        
        unit_hint = "unknown"
        if 'in millions' in chunk_lower or 'millions of dollars' in chunk_lower or '($ in millions)' in chunk_lower:
            unit_hint = "millions"
        elif 'in thousands' in chunk_lower or 'thousands of dollars' in chunk_lower or '($ in thousands)' in chunk_lower:
            unit_hint = "thousands"

        results_by_year = {}

        # 1. HTML / SGML Table Parsing
        if '<table' in chunk_lower:
            try:
                soup = BeautifulSoup(chunk, 'html.parser')
                for table in soup.find_all('table')[:6]:
                    rows = table.find_all('tr')
                    years = []

                    for r in rows[:8]:
                        cells = [c.get_text(" ", strip=True) for c in r.find_all(['td', 'th'])]
                        row_txt = " ".join(cells)
                        found_years = re.findall(r'\b(199\d|200\d)\b', row_txt)
                        if len(found_years) >= 3:
                            years = [int(y) for y in found_years]
                            break

                    if not years:
                        continue

                    for r in rows:
                        cells = [c.get_text(" ", strip=True) for c in r.find_all(['td', 'th']) if c.get_text(" ", strip=True)]
                        if not cells:
                            continue
                        lbl = cells[0].lower()
                        metric = None
                        if ('revenue' in lbl or 'net sales' in lbl or 'total sales' in lbl) and 'per share' not in lbl:
                            metric = 'rev'
                        elif ('operating income' in lbl or 'operating profit' in lbl or 'income from operations' in lbl) and 'per share' not in lbl:
                            metric = 'opinc'
                        elif ('net income' in lbl or 'net loss' in lbl or 'net earnings' in lbl) and 'per share' not in lbl:
                            metric = 'ni'
                        elif 'total assets' in lbl:
                            metric = 'assets'
                        elif 'shareholders' in lbl or 'stockholders' in lbl or 'total equity' in lbl:
                            metric = 'equity'
                        elif 'long-term debt' in lbl or 'long term debt' in lbl or 'long-term obligations' in lbl:
                            metric = 'total_debt'
                        elif ('shares' in lbl or 'common stock' in lbl) and ('weighted' in lbl or 'outstanding' in lbl):
                            metric = 'shares'

                        if metric:
                            cell_strs = " ".join(cells[1:])
                            cell_strs = re.sub(r'\(\s*([\d,\.]+)\s*\)', r'(-\1)', cell_strs)
                            num_tokens = re.findall(r'[\(\$]?\s*[\d,]+(?:\.\d+)?\s*[\)]?', cell_strs)
                            raw_nums = []
                            for tok in num_tokens:
                                v = clean_num(tok)
                                if not np.isnan(v) and int(abs(v)) not in range(1990, 2026):
                                    raw_nums.append(v)

                            if len(raw_nums) >= len(years):
                                for y_idx, y_val in enumerate(years):
                                    if y_val not in results_by_year:
                                        results_by_year[y_val] = {}
                                    if metric not in results_by_year[y_val]:
                                        results_by_year[y_val][metric] = raw_nums[y_idx]

                    if results_by_year and len(results_by_year) >= 3:
                        return results_by_year, unit_hint
            except Exception:
                pass

        # 2. Plain ASCII text table parsing
        lines = chunk.split('\n')
        years = []
        header_idx = -1

        for l_idx, line in enumerate(lines[:35]):
            found_years = re.findall(r'\b(199\d|200\d)\b', line)
            if len(found_years) >= 3:
                years = [int(y) for y in found_years]
                header_idx = l_idx
                break

        if years and header_idx >= 0:
            for line in lines[header_idx + 1:]:
                line_clean = line.strip()
                if not line_clean or line_clean.startswith('</TABLE') or 'item 7' in line_clean.lower():
                    break
                lbl = line_clean.lower()
                metric = None
                if ('revenue' in lbl or 'net sales' in lbl or 'total sales' in lbl) and 'per share' not in lbl:
                    metric = 'rev'
                elif ('operating income' in lbl or 'operating profit' in lbl or 'income from operations' in lbl) and 'per share' not in lbl:
                    metric = 'opinc'
                elif ('net income' in lbl or 'net loss' in lbl or 'net earnings' in lbl) and 'per share' not in lbl:
                    metric = 'ni'
                elif 'total assets' in lbl:
                    metric = 'assets'
                elif 'shareholders' in lbl or 'stockholders' in lbl or 'total equity' in lbl:
                    metric = 'equity'
                elif 'long-term debt' in lbl or 'long term debt' in lbl or 'long-term obligations' in lbl:
                    metric = 'total_debt'
                elif ('shares' in lbl or 'common stock' in lbl) and ('weighted' in lbl or 'outstanding' in lbl):
                    metric = 'shares'

                if metric:
                    fixed_line = re.sub(r'\(\s*([\d,\.]+)\s*\)', r'(-\1)', line_clean)
                    num_tokens = re.findall(r'[\(\$]?\s*[\d,]+(?:\.\d+)?\s*[\)]?', fixed_line)
                    raw_nums = []
                    for tok in num_tokens:
                        v = clean_num(tok)
                        if not np.isnan(v) and int(abs(v)) not in range(1990, 2026):
                            raw_nums.append(v)
                    if len(raw_nums) >= len(years):
                        for y_idx, y_val in enumerate(years):
                            if y_val not in results_by_year:
                                results_by_year[y_val] = {}
                            if metric not in results_by_year[y_val]:
                                results_by_year[y_val][metric] = raw_nums[y_idx]

            if results_by_year and len(results_by_year) >= 3:
                return results_by_year, unit_hint

    return {}, "unknown"

def determine_unit_scale(doc_raw_data, xbrl_comp_data, unit_hint):
    """
    Validates unit scale for a specific document against XBRL comparative data.
    """
    for y in [2005, 2006, 2007, 2004, 2008]:
        if y in doc_raw_data and y in xbrl_comp_data:
            r_item6 = doc_raw_data[y].get('rev')
            r_xbrl = xbrl_comp_data[y].get('rev')
            if r_item6 and r_xbrl and abs(r_item6) > 0 and abs(r_xbrl) > 0:
                ratio = abs(r_xbrl / r_item6)
                if 700_000 <= ratio <= 1_300_000:
                    return 1_000_000.0
                elif 700 <= ratio <= 1_300:
                    return 1_000.0
                elif 0.7 <= ratio <= 1.3:
                    return 1.0
                elif 700_000_000 <= ratio <= 1_300_000_000:
                    return 1_000_000_000.0

            ni_item6 = doc_raw_data[y].get('ni')
            ni_xbrl = xbrl_comp_data[y].get('ni')
            if ni_item6 and ni_xbrl and abs(ni_item6) > 0 and abs(ni_xbrl) > 0:
                ratio = abs(ni_xbrl / ni_item6)
                if 700_000 <= ratio <= 1_300_000:
                    return 1_000_000.0
                elif 700 <= ratio <= 1_300:
                    return 1_000.0
                elif 0.7 <= ratio <= 1.3:
                    return 1.0

    if unit_hint == "millions":
        return 1_000_000.0
    elif unit_hint == "thousands":
        return 1_000.0

    return 1_000.0

def run_step_c(universe, filings_index, df_xbrl_step_b):
    """
    Step C: Harvest 1996-2006 annual financials via 2-3 strategic 10-K filings.
    Validates unit scale against Step B's XBRL facts.
    Anchors strictly to contemporaneous 10-K filingDate.
    """
    print(f"\n=== [Step C] Extracting 1996-2006 Annual Financials from Strategic 10-K Filings ===")
    
    xbrl_lookup = {}
    if df_xbrl_step_b is not None and not df_xbrl_step_b.empty:
        df_fy = df_xbrl_step_b[df_xbrl_step_b['fiscal_period'] == 'FY']
        for _, r in df_fy.iterrows():
            t = r['ticker']
            y = int(r['fiscal_year'])
            if t not in xbrl_lookup:
                xbrl_lookup[t] = {}
            xbrl_lookup[t][y] = {
                'rev': r['rev'],
                'ni': r['ni'],
                'assets': r['assets'],
                'shares': r['shares']
            }

    item6_rows = []

    for idx, comp in enumerate(universe):
        ticker = comp['ticker']
        cik = int(comp['cik'])
        entity_name = comp.get('name', '')
        c_filings = filings_index.get(ticker, [])

        if (idx + 1) % 100 == 0 or idx == 0:
            print(f"[{idx+1}/{len(universe)}] Harvesting strategic 10-Ks for {ticker} (CIK {cik:010d})...")

        k_10s = [f for f in c_filings if f['form'] in {'10-K', '10-K405'}]
        if not k_10s:
            continue

        def find_k(min_year, max_year, pref_year):
            candidates = [f for f in k_10s if min_year <= int(f['filingDate'][:4]) <= max_year]
            if not candidates:
                return None
            candidates.sort(key=lambda x: abs(int(x['filingDate'][:4]) - pref_year))
            return candidates[0]

        k_2005 = find_k(2004, 2007, 2005)
        k_2000 = find_k(1998, 2002, 2000)
        # Fallback to ~2008 10-K only if ~2005 10-K is missing
        k_2008 = find_k(2007, 2010, 2008) if k_2005 is None else None

        strategic_filings = [f for f in [k_2005, k_2000, k_2008] if f is not None]
        seen_accns = set()

        comp_scaled_years = {}  # year_int -> dict of scaled metrics

        for f in strategic_filings:
            accn = f['accessionNumber']
            if accn in seen_accns:
                continue
            seen_accns.add(accn)

            accn_clean = accn.replace('-', '')
            pdoc = f.get('primaryDocument', '') or f.get('_primaryDocument', '')
            ext = ".htm" if pdoc and pdoc.endswith(('.htm', '.html')) else ".txt"
            doc_cache = os.path.join(DOCS_CACHE, f"{cik}_{accn}{ext}.gz")

            if pdoc and pdoc.endswith(('.htm', '.html')):
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_clean}/{pdoc}"
            else:
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_clean}/{accn}.txt"

            doc_text = fetch_sec_text(doc_url, cache_path=doc_cache)
            if doc_text:
                doc_raw_years, hint = parse_item6_table(doc_text)
                if doc_raw_years:
                    doc_scale = determine_unit_scale(doc_raw_years, xbrl_lookup.get(ticker, {}), hint)
                    for y_val, m_dict in doc_raw_years.items():
                        if y_val not in comp_scaled_years:
                            # Apply scale
                            scaled_m = {}
                            for m_name in ['rev', 'opinc', 'ni', 'assets', 'equity', 'total_debt']:
                                if m_name in m_dict:
                                    scaled_m[m_name] = m_dict[m_name] * doc_scale
                            if 'shares' in m_dict:
                                raw_sh = m_dict['shares']
                                if raw_sh < 10_000:
                                    scaled_m['shares'] = raw_sh * 1_000_000.0
                                elif raw_sh < 10_000_000:
                                    scaled_m['shares'] = raw_sh * 1_000.0
                                else:
                                    scaled_m['shares'] = raw_sh
                            comp_scaled_years[y_val] = scaled_m

        if not comp_scaled_years:
            continue

        for ty, m_dict in sorted(comp_scaled_years.items()):
            if not (1996 <= ty <= 2008):
                continue

            contemp_filing = None
            for f in k_10s:
                f_year = int(f['filingDate'][:4])
                f_month = int(f['filingDate'][5:7])
                r_year = int(f['reportDate'][:4]) if f['reportDate'] else 0
                if r_year == ty:
                    contemp_filing = f
                    break
                elif f_year == ty and f_month >= 9:
                    contemp_filing = f
                    break
                elif f_year == ty + 1 and f_month <= 6:
                    contemp_filing = f
                    break

            if contemp_filing:
                filing_date = contemp_filing['filingDate']
                adt = contemp_filing['acceptanceDateTime']
                timing = contemp_filing['session_timing']
                rep_date = contemp_filing['reportDate'] if (contemp_filing['reportDate'] and contemp_filing['reportDate'] <= filing_date) else f"{ty}-12-31"
                if rep_date > filing_date:
                    rep_date = f"{ty}-06-30" if f"{ty}-06-30" <= filing_date else filing_date
            else:
                filing_date = f"{ty+1}-03-31"
                adt = None
                timing = 'DATE_ONLY'
                rep_date = f"{ty}-12-31"

            item6_rows.append({
                'ticker': ticker,
                'cik': cik,
                'entity_name': entity_name,
                'fiscal_year': ty,
                'fiscal_period': 'FY',
                'reportDate': rep_date,
                'form': '10-K',
                'filingDate': filing_date,
                'acceptanceDateTime': adt,
                'session_timing': timing,
                'rev': m_dict.get('rev', np.nan),
                'gp': np.nan,
                'opinc': m_dict.get('opinc', np.nan),
                'ni': m_dict.get('ni', np.nan),
                'ocf': np.nan,
                'capex': np.nan,
                'rd': np.nan,
                'sbc': np.nan,
                'assets': m_dict.get('assets', np.nan),
                'cash': np.nan,
                'total_debt': m_dict.get('total_debt', np.nan),
                'equity': m_dict.get('equity', np.nan),
                'shares': m_dict.get('shares', np.nan),
                'buyback': np.nan,
                'div': np.nan,
                'inventory': np.nan,
                'ar': np.nan,
                'source_tier': 'HTML_10K_ITEM6'
            })

    df_item6 = pd.DataFrame(item6_rows)
    print(f"Step C extracted {len(df_item6):,} Item 6 historical rows.")
    return df_item6
