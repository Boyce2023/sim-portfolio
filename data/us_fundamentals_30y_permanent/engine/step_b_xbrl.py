import os
import json
import zipfile
from datetime import datetime
import numpy as np
import pandas as pd
from .cache_manager import save_json_gz, load_json_gz, FACTS_CACHE
from .rate_limiter import fetch_sec_json

COMPANYFACTS_ZIP = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_fundamentals_30y_permanent/bulk_zip/companyfacts.zip"
XBRL_CHECKPOINT_PARQUET = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_fundamentals_30y_permanent/pre2009/step_b_xbrl_2005_2008.parquet"

TAG_MAP = {
    'rev': [
        'Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'SalesRevenueNet',
        'SalesRevenueGoodsNet', 'RevenuesNetOfInterestExpense', 'InterestAndDividendIncomeOperating',
        'TotalRevenuesAndOtherIncome', 'SalesRevenueServicesNet', 'HealthCareOrganizationRevenue',
        'RealEstateRevenueNet', 'ElectricUtilityRevenue', 'RegulatedAndUnregulatedOperatingRevenue'
    ],
    'gp': ['GrossProfit', 'GrossProfitLoss'],
    'cor': ['CostOfGoodsAndServicesSold', 'CostOfRevenue', 'CostOfGoodsSold'],
    'opinc': [
        'OperatingIncomeLoss', 'OperatingProfitLoss',
        'IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments'
    ],
    'ni': ['NetIncomeLoss', 'ProfitLoss', 'NetIncomeLossAvailableToCommonStockholdersBasic'],
    'ocf': ['NetCashProvidedByUsedInOperatingActivities', 'NetCashProvidedByUsedInOperatingActivitiesContinuingOperations'],
    'capex': [
        'PaymentsToAcquirePropertyPlantAndEquipment', 'PaymentsToAcquireProductiveAssets',
        'PaymentsForCapitalImprovements', 'PaymentsToAcquireOilAndGasPropertyAndEquipment'
    ],
    'rd': ['ResearchAndDevelopmentExpense', 'ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost'],
    'sbc': ['ShareBasedCompensation', 'AllocatedShareBasedCompensationExpense'],
    'assets': ['Assets'],
    'cash': ['CashAndCashEquivalentsAtCarryingValue', 'CashCashEquivalentsAndShortTermInvestments', 'CashAndCashEquivalentsAtFairValue', 'Cash'],
    'debt_lt': ['LongTermDebtNoncurrent', 'LongTermDebtAndCapitalLeaseObligations', 'LongTermDebt'],
    'debt_st': ['DebtCurrent', 'ShortTermBorrowings', 'CommercialPaper'],
    'equity': ['StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest', 'CommonStockholdersEquity'],
    'shares': ['CommonStockSharesOutstanding', 'EntityCommonStockSharesOutstanding', 'WeightedAverageNumberOfDilutedSharesOutstanding', 'WeightedAverageNumberOfSharesOutstandingBasic'],
    'buyback': ['PaymentsForRepurchaseOfCommonStock', 'PaymentsForRepurchaseOfEquity'],
    'div': ['PaymentsOfDividends', 'PaymentsOfDividendsCommonStock', 'PaymentsOfOrdinaryDividends'],
    'inventory': ['InventoryNet', 'InventoryGross'],
    'ar': ['AccountsReceivableNetCurrent', 'ReceivablesNetCurrent', 'AccountsAndNotesReceivableNet']
}

def determine_period(it):
    end = it.get('end', '')
    if not end or not ('2005-01-01' <= end <= '2008-12-31'):
        return None, None, None

    start = it.get('start')
    form = it.get('form', '')
    fp_raw = it.get('fp', '')

    dur = None
    if start:
        try:
            d_start = datetime.strptime(start, '%Y-%m-%d')
            d_end = datetime.strptime(end, '%Y-%m-%d')
            dur = (d_end - d_start).days
        except Exception:
            dur = None

    fy = int(end[:4])

    if dur is not None:
        if 320 <= dur <= 385:
            fp = 'FY'
        elif 70 <= dur <= 115:
            m = int(end[5:7])
            if m in (3, 4): fp = 'Q1'
            elif m in (6, 7): fp = 'Q2'
            elif m in (9, 10): fp = 'Q3'
            else: fp = 'Q4'
        else:
            return None, None, None
    else:
        if '10-K' in form or fp_raw == 'FY':
            fp = 'FY'
        else:
            m = int(end[5:7])
            if m in (3, 4): fp = 'Q1'
            elif m in (6, 7): fp = 'Q2'
            elif m in (9, 10): fp = 'Q3'
            else: fp = 'FY'

    return fy, fp, end

def run_step_b(universe, filings_index):
    """
    Step B: Extract 2005-2008 comparative XBRL facts, anchored to contemporaneous
    filingDate from Step A submissions.
    """
    if os.path.exists(XBRL_CHECKPOINT_PARQUET) and os.path.getsize(XBRL_CHECKPOINT_PARQUET) > 10000:
        df_cached = pd.read_parquet(XBRL_CHECKPOINT_PARQUET)
        if len(df_cached) >= 2000:
            print(f"=== [Step B] Loaded {len(df_cached):,} comparative XBRL rows from checkpoint {XBRL_CHECKPOINT_PARQUET} ===")
            return df_cached

    print(f"\n=== [Step B] Extracting 2005-2008 Comparative XBRL Facts for {len(universe)} Companies ===")

    zip_obj = None
    zip_names = set()
    if os.path.exists(COMPANYFACTS_ZIP):
        zip_obj = zipfile.ZipFile(COMPANYFACTS_ZIP, 'r')
        zip_names = set(zip_obj.namelist())
        print(f"Loaded bulk companyfacts.zip ({len(zip_names):,} files)")

    anchored_rows = []

    for idx, comp in enumerate(universe):
        ticker = comp['ticker']
        cik = int(comp['cik'])
        entity_name = comp.get('name', '')
        comp_filings = filings_index.get(ticker, [])

        if (idx + 1) % 100 == 0 or idx == 0:
            print(f"[{idx+1}/{len(universe)}] Extracting XBRL facts for {ticker} (CIK {cik:010d})...")

        fname = f"CIK{cik:010d}.json"
        cache_path = os.path.join(FACTS_CACHE, f"CIK{cik:010d}.json.gz")
        cf_data = load_json_gz(cache_path)

        if cf_data is None:
            if zip_obj and fname in zip_names:
                try:
                    cf_data = json.loads(zip_obj.read(fname))
                    save_json_gz(cache_path, cf_data)
                except Exception:
                    cf_data = None
            if cf_data is None:
                url = f"https://data.sec.gov/api/xbrl/companyfacts/{fname}"
                cf_data = fetch_sec_json(url, cache_path=cache_path)

        if not cf_data or not isinstance(cf_data, dict) or 'facts' not in cf_data:
            continue

        us_gaap = cf_data.get('facts', {}).get('us-gaap', {})
        dei = cf_data.get('facts', {}).get('dei', {})

        period_data = {}  # key: (fy, fp, end) -> {'filed': str, 'form': str, 'metrics': {}}

        def scan_concepts(field, concept_list, source):
            for concept in concept_list:
                if concept not in source:
                    continue
                units = source[concept].get('units', {})
                for u_key, items in units.items():
                    for it in items:
                        val = it.get('val')
                        if val is None:
                            continue
                        fy, fp, p_end = determine_period(it)
                        if fy is None:
                            continue
                        key = (fy, fp, p_end)
                        if key not in period_data:
                            period_data[key] = {
                                'filed': it.get('filed', ''),
                                'form': it.get('form', '10-K' if fp == 'FY' else '10-Q'),
                                'metrics': {}
                            }
                        if field not in period_data[key]['metrics']:
                            period_data[key]['metrics'][field] = float(val)

        for field, clist in TAG_MAP.items():
            scan_concepts(field, clist, us_gaap)
            if field == 'shares':
                scan_concepts(field, clist, dei)

        for (fy, fp, p_end), p_info in sorted(period_data.items()):
            metrics = p_info['metrics']
            if not metrics:
                continue

            # Fallback gp = rev - cor
            if 'gp' not in metrics and 'rev' in metrics and 'cor' in metrics:
                metrics['gp'] = metrics['rev'] - metrics['cor']

            # Total debt = debt_lt + debt_st
            lt = metrics.get('debt_lt', 0.0) or 0.0
            st = metrics.get('debt_st', 0.0) or 0.0
            total_debt = (lt + st) if ('debt_lt' in metrics or 'debt_st' in metrics) else np.nan

            target_form_family = {'10-K', '10-K405'} if fp == 'FY' else {'10-Q', '10-Q405'}
            matched = None

            # Priority 1: exact reportDate
            if p_end:
                for f in comp_filings:
                    if f['form'] in target_form_family and f['reportDate'] == p_end and f['filingDate'] >= p_end:
                        matched = f
                        break

            # Priority 2: reportDate within 45 days
            if not matched and p_end:
                try:
                    p_dt = datetime.strptime(p_end, '%Y-%m-%d')
                    for f in comp_filings:
                        if f['form'] in target_form_family and f['reportDate'] and f['filingDate'] >= p_end:
                            try:
                                f_dt = datetime.strptime(f['reportDate'], '%Y-%m-%d')
                                if abs((f_dt - p_dt).days) <= 45:
                                    matched = f
                                    break
                            except Exception:
                                pass
                except Exception:
                    pass

            # Priority 3: filingDate in fy / fy+1 (strictly >= p_end)
            if not matched:
                for f in comp_filings:
                    if f['form'] in target_form_family and f['filingDate'] and f['filingDate'] >= p_end:
                        f_year = int(f['filingDate'][:4])
                        if fp == 'FY' and (f_year == fy or (f_year == fy + 1 and int(f['filingDate'][5:7]) <= 4)):
                            matched = f
                            break

            if matched:
                filing_date = matched['filingDate']
                adt = matched['acceptanceDateTime']
                timing = matched['session_timing']
                source_tier = 'EARLY_XBRL_ANCHORED'
            else:
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
                'rev': metrics.get('rev', np.nan),
                'gp': metrics.get('gp', np.nan),
                'opinc': metrics.get('opinc', np.nan),
                'ni': metrics.get('ni', np.nan),
                'ocf': metrics.get('ocf', np.nan),
                'capex': metrics.get('capex', np.nan),
                'rd': metrics.get('rd', np.nan),
                'sbc': metrics.get('sbc', np.nan),
                'assets': metrics.get('assets', np.nan),
                'cash': metrics.get('cash', np.nan),
                'total_debt': total_debt,
                'equity': metrics.get('equity', np.nan),
                'shares': metrics.get('shares', np.nan),
                'buyback': metrics.get('buyback', np.nan),
                'div': metrics.get('div', np.nan),
                'inventory': metrics.get('inventory', np.nan),
                'ar': metrics.get('ar', np.nan),
                'source_tier': source_tier
            })

    if zip_obj:
        zip_obj.close()

    df_xbrl = pd.DataFrame(anchored_rows)
    print(f"Step B extracted {len(df_xbrl):,} comparative XBRL rows.")
    if not df_xbrl.empty:
        os.makedirs(os.path.dirname(XBRL_CHECKPOINT_PARQUET), exist_ok=True)
        df_xbrl.to_parquet(XBRL_CHECKPOINT_PARQUET, index=False)
        print(f"Saved Step B checkpoint to {XBRL_CHECKPOINT_PARQUET} ({os.path.getsize(XBRL_CHECKPOINT_PARQUET):,} bytes)")
    return df_xbrl
