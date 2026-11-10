import os, glob, json
from datetime import datetime
from collections import defaultdict

WORK_DIR = '/tmp/w1_a5_sec_work'

REV_TAGS_TOTAL = [
    'RevenueFromContractWithCustomerExcludingAssessedTax',
    'RevenueFromContractWithCustomerIncludingAssessedTax',
    'Revenues',
    'SalesRevenueNet',
    'HealthCareOrganizationRevenue',
]
REV_TAGS_PRODUCT = [
    'SalesRevenueGoodsNet',
    'SalesRevenueServicesNet',
]
GP_TAGS = ['GrossProfit']
COR_TAGS = ['CostOfGoodsAndServicesSold', 'CostOfRevenue', 'CostOfGoodsSold', 'CostOfServices']

def parse_days(start_s, end_s):
    try:
        d1 = datetime.strptime(start_s, '%Y-%m-%d')
        d2 = datetime.strptime(end_s, '%Y-%m-%d')
        return (d2 - d1).days
    except Exception:
        return -1

def extract_duration_series(us_gaap, tags):
    """Returns dict of annual {(end_date): (val, accn, filed, form, tag)} and quarterly {(end_date): (val, accn, filed, form, tag)}"""
    ann = {}
    qtr = {}
    for tag in tags:
        if tag not in us_gaap:
            continue
        units = us_gaap[tag].get('units', {})
        usd_list = units.get('USD', [])
        for it in usd_list:
            st, en = it.get('start'), it.get('end')
            if not st or not en:
                continue
            days = parse_days(st, en)
            val = float(it.get('val') or 0)
            accn = it.get('accn', '')
            filed = it.get('filed', '')
            form = it.get('form', '')
            if 345 <= days <= 380:
                # Prefer 10-K over 10-Q, and larger/more complete total tag or earlier tag priority
                prev = ann.get(en)
                if prev is None or (prev[4] not in tags[:3] and tag in tags[:3]) or (prev[4] == tag and val > prev[0]):
                    ann[en] = (val, accn, filed, form, tag)
            elif 75 <= days <= 105:
                prev = qtr.get(en)
                if prev is None or (prev[4] not in tags[:3] and tag in tags[:3]) or (prev[4] == tag and val > prev[0]):
                    qtr[en] = (val, accn, filed, form, tag)
    return ann, qtr

def extract_instant_series(facts_root, ns, tag, unit_name):
    res = {}
    ns_obj = facts_root.get(ns, {})
    if tag not in ns_obj:
        return res
    items = ns_obj[tag].get('units', {}).get(unit_name, [])
    for it in items:
        en = it.get('end')
        if not en:
            continue
        val = float(it.get('val') or 0)
        if val <= 0:
            continue
        prev = res.get(en)
        # Keep earliest filing after end date (point-in-time un-restated shares!)
        filed = it.get('filed', '9999-99-99')
        if prev is None or filed < prev[2]:
            res[en] = (val, it.get('accn', ''), filed, it.get('form', ''))
    return res

def summarize_all():
    sub_files = sorted(glob.glob(f'{WORK_DIR}/submissions/*.json'))
    summary = {}
    for sp in sub_files:
        base = os.path.basename(sp).replace('.json', '')
        tk, cik_s = base.split('_')
        with open(sp) as fp:
            sub = json.load(fp)
        fp_fact = f'{WORK_DIR}/facts/{base}.json'
        facts = {}
        if os.path.exists(fp_fact):
            with open(fp_fact) as fp:
                facts = json.load(fp).get('facts', {})

        rec = sub.get('filings', {}).get('recent', {})
        forms = rec.get('form', [])
        fdates = rec.get('filingDate', [])
        accns = rec.get('accessionNumber', [])
        docs = rec.get('primaryDocument', [])
        items_list = rec.get('items', [])

        key_filings = []
        f4_count = 0
        for i, fm in enumerate(forms):
            if fm == '4':
                f4_count += 1
            its = items_list[i] if i < len(items_list) else []
            it_str = ','.join(its) if isinstance(its, list) else str(its)
            if fm in ('25-NSE', '25', '15-12G', '15-12B', 'DEFM14A', 'PREM14A', 'SC 14D9', 'SC 14D9/A', '10-K') or (
                fm == '8-K' and any(k in it_str for k in ('1.01', '1.03', '2.01', '3.01', '5.01'))
            ):
                if fm == 'SC 14D9/A':
                    continue
                key_filings.append({
                    'date': fdates[i],
                    'form': fm,
                    'items': it_str,
                    'accn': accns[i],
                    'doc': docs[i],
                })

        us_gaap = facts.get('us-gaap', {})
        ann_rev, qtr_rev = extract_duration_series(us_gaap, REV_TAGS_TOTAL + REV_TAGS_PRODUCT)
        ann_prod, qtr_prod = extract_duration_series(us_gaap, REV_TAGS_PRODUCT)
        ann_gp, qtr_gp = extract_duration_series(us_gaap, GP_TAGS)
        ann_cor, qtr_cor = extract_duration_series(us_gaap, COR_TAGS)
        shares = extract_instant_series(facts, 'dei', 'EntityCommonStockSharesOutstanding', 'shares')
        pub_flt = extract_instant_series(facts, 'dei', 'EntityPublicFloat', 'USD')

        # Build annual summary table by year
        ann_by_yr = {}
        for en, (val, accn, filed, fm, tag) in sorted(ann_rev.items()):
            yr = int(en[:4])
            if int(en[5:7]) <= 3:
                yr -= 1
            gp_v = ann_gp.get(en, (None,))[0]
            cor_v = ann_cor.get(en, (None,))[0]
            gm = None
            if val > 0:
                if gp_v is not None and -2*val <= gp_v <= val:
                    gm = gp_v / val * 100.0
                elif cor_v is not None and 0 <= cor_v <= 3*val:
                    gm = (val - cor_v) / val * 100.0
            ann_by_yr[yr] = {
                'end': en, 'rev_m': round(val/1e6, 2), 'gm_pct': round(gm, 1) if gm is not None else None,
                'accn': accn, 'filed': filed, 'tag': tag,
                'prod_rev_m': round(ann_prod[en][0]/1e6, 2) if en in ann_prod else None
            }

        summary[tk] = {
            'cik': int(cik_s),
            'name': sub.get('name'),
            'sic': sub.get('sic'),
            'sicDescription': sub.get('sicDescription'),
            'tickers_sec': sub.get('tickers'),
            'f4_recent_count': f4_count,
            'older_files_count': len(sub.get('filings', {}).get('files', [])),
            'key_filings': key_filings[:25],
            'annual_rev': ann_by_yr,
            'public_float': {en: {'flt_b': round(v[0]/1e9, 3), 'filed': v[2], 'accn': v[1]} for en, v in sorted(pub_flt.items())},
            'shares_sample': {en: round(v[0]/1e6, 3) for en, v in sorted(shares.items())[-12:]},
        }

    with open(f'{WORK_DIR}/parsed_summary.json', 'w') as fp:
        json.dump(summary, fp, indent=2)
    print(f"Parsed {len(summary)} companies -> {WORK_DIR}/parsed_summary.json")
    for tk, d in sorted(summary.items()):
        yrs = sorted(d['annual_rev'].keys())
        rev_str = ', '.join(f"{y}:${d['annual_rev'][y]['rev_m']:.0f}M" for y in yrs[-4:])
        kf_top = [(k['date'], k['form'], k['items']) for k in d['key_filings'][:4]]
        print(f"{tk:6s} | SIC={str(d['sic']):4s} | F4={d['f4_recent_count']:3d} | {d['name'][:30]:30s} | Rev: {rev_str} | TopFilings: {kf_top[:2]}")

if __name__ == '__main__':
    summarize_all()