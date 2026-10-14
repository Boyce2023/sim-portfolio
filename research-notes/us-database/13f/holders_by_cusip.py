"""按 CUSIP 反查 13F 持有人, 逐季对比新建仓/加仓/减仓/清仓。
数据: SEC EDGAR 全文检索(efts) 找含该 CUSIP 的 13F-HR 信息表, 下载 XML 逐行解析。
用法: python3 holders_by_cusip.py 26603R106 DUOL
输出: 同目录 <TICKER>_13f_raw.json(逐份申报逐行) 与 <TICKER>_13f_panel.csv(机构×季度股数)
"""
import json, sys, time, re, os, csv, urllib.request, urllib.parse
import xml.etree.ElementTree as ET

CUSIP, TICK = sys.argv[1].upper(), sys.argv[2].upper()
D = os.path.dirname(os.path.abspath(__file__))
UA = {'User-Agent': 'Buwen Deng research buwendeng@gmail.com'}
# 按申报日期窗口取四个报告期: 申报截止为期末后45天, 早报的会落在期末后第一个月
WINDOWS = [('2026-01-01', '2026-03-31', '2025-12-31'), ('2026-04-01', '2026-06-30', '2026-03-31'),
           ('2026-07-01', '2026-09-30', '2026-06-30'), ('2026-10-01', '2026-12-31', '2026-09-30')]


def get(url, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:
            err = e
            time.sleep(2 * (k + 1))
    raise err


def search(start, end):
    hits, frm = [], 0
    while True:
        q = urllib.parse.urlencode({'q': f'"{CUSIP}"', 'forms': '13F-HR', 'dateRange': 'custom',
                                    'startdt': start, 'enddt': end, 'from': frm})
        d = json.loads(get('https://efts.sec.gov/LATEST/search-index?' + q))
        h = d['hits']['hits']
        hits += h
        tot = d['hits']['total']['value']
        frm += len(h)
        if not h or frm >= tot:
            return hits, tot
        time.sleep(0.15)


def parse(xml_bytes):
    """按本地标签名解析, 不依赖命名空间前缀(各家申报的前缀写法不一)。"""
    root = ET.fromstring(xml_bytes)
    ln = lambda e: e.tag.rsplit('}', 1)[-1]
    def find(e, name):
        for c in e.iter():
            if ln(c) == name:
                return (c.text or '').strip()
        return ''
    rows, total = [], 0.0
    for it in root.iter():
        if ln(it) != 'infoTable':
            continue
        try: total += float(find(it, 'value') or 0)
        except ValueError: pass
        if find(it, 'cusip').upper() != CUSIP:
            continue
        rows.append({'value': float(find(it, 'value') or 0), 'shares': float(find(it, 'sshPrnamt') or 0),
                     'type': find(it, 'sshPrnamtType'), 'putcall': find(it, 'putCall'),
                     'discretion': find(it, 'investmentDiscretion')})
    return rows, total


raw_path = os.path.join(D, f'{TICK}_13f_raw.json')
raw = json.load(open(raw_path)) if os.path.exists(raw_path) else {}
for start, end, period in WINDOWS:
    hits, tot = search(start, end)
    print(f'{period}: 检索命中 {tot} 份 (申报日 {start} 至 {end})', flush=True)
    import concurrent.futures as cf, threading
    lock = threading.Lock()
    todo = [h for h in hits if h['_id'].split(':', 1)[0] not in raw or 'total' not in raw[h['_id'].split(':', 1)[0]]]
    def one(h):
        acc, fn = h['_id'].split(':', 1)
        s_ = h['_source']
        cik = (s_.get('ciks') or [''])[0].lstrip('0')
        url = f'https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace("-", "")}/{fn}'
        try:
            rows, total = parse(get(url)); ok = True
        except Exception as e:
            rows, total, ok = [], None, type(e).__name__
        return acc, {'cik': cik, 'name': (s_.get('display_names') or [''])[0], 'file_date': s_.get('file_date'),
                     'period': s_.get('period_ending') or period, 'url': url, 'ok': ok, 'rows': rows, 'total': total}
    n = 0
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for acc, rec in ex.map(one, todo):
            raw[acc] = rec; n += 1
            if n % 100 == 0:
                with lock: json.dump(raw, open(raw_path, 'w'), ensure_ascii=False)
                print(f'  {n}/{len(todo)}', flush=True)
    json.dump(raw, open(raw_path, 'w'), ensure_ascii=False)

# 机构×季度面板: 只算普通股(不含期权), 同一报告期多份取最新申报
panel = {}
for acc, r in raw.items():
    sh = sum(x['shares'] for x in r['rows'] if not x['putcall'])
    val = sum(x['value'] for x in r['rows'] if not x['putcall'])
    opt = ';'.join(f"{x['putcall']}:{int(x['shares'])}" for x in r['rows'] if x['putcall'])
    k = (r['cik'], r['period'])
    if k not in panel or r['file_date'] > panel[k]['file_date']:
        panel[k] = dict(name=r['name'], file_date=r['file_date'], shares=sh, value=val, options=opt, ok=r['ok'],
                        total=r.get('total'), weight=(val / r['total'] * 100 if r.get('total') else None))
with open(os.path.join(D, f'{TICK}_13f_panel.csv'), 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['cik', 'name', 'period', 'file_date', 'shares', 'value', 'options', 'parse_ok', 'portfolio_total', 'weight_pct'])
    for (cik, per), v in sorted(panel.items()):
        w.writerow([cik, v['name'], per, v['file_date'], int(v['shares']), v['value'], v['options'], v['ok'], v['total'], v['weight']])
bad = sum(1 for r in raw.values() if r['ok'] is not True)
print(f'完成: {len(raw)} 份申报, 解析失败 {bad} 份, 面板 {len(panel)} 行')
