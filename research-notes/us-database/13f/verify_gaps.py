"""核实面板里的"缺季度": 直接从 EDGAR 公司申报列表取该机构 Q1/Q2 的 13F 信息表, 区分"真的没持有"与"检索漏掉"。
用法: python3 -u verify_gaps.py 26603R106 DUOL
"""
import json, sys, csv, collections, concurrent.futures as cf

exec(open('holders_by_cusip.py').read().split("raw_path =")[0])
rows = list(csv.DictReader(open(f'{TICK}_13f_panel.csv')))
by = collections.defaultdict(dict); nm = {}
for r in rows:
    by[r['cik']][r['period']] = r; nm[r['cik']] = r['name']
f = lambda x: float(x) if x not in ('', None, 'None') else 0.0
P = ['2025-12-31', '2026-03-31', '2026-06-30']
chk = set()
for c, d in by.items():
    sh = [f(d[p]['shares']) if p in d else None for p in P]
    if sh[1] is None and ((sh[0] or 0) > 20000 or (sh[2] or 0) > 20000):
        chk.add(c)
    if sh[2] is None and (sh[1] or 0) > 20000:
        chk.add(c)
    if sh[1] == 0 and (sh[2] or 0) > 20000:      # 面板 Q1=0 而 Q2 大量: 疑似 Q1 解析漏
        chk.add(c)
chk = sorted(chk)
print(f'待核 {len(chk)} 家', flush=True)


def periods(cik):
    sub = json.loads(get(f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json'))
    rc = sub['filings']['recent']; out = {}
    for form, acc, fd, rd in zip(rc['form'], rc['accessionNumber'], rc['filingDate'], rc['reportDate']):
        if form != '13F-HR' or rd not in ('2026-03-31', '2026-06-30') or rd in out:
            continue
        base = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace("-", "")}'
        idx = json.loads(get(base + '/index.json'))
        xs = [i['name'] for i in idx['directory']['item']
              if i['name'].lower().endswith('.xml') and 'primary' not in i['name'].lower()]
        got = None
        for x in xs:
            try:
                rws, t = parse(get(f'{base}/{x}'))
                if t > 0:
                    got = (int(sum(r['shares'] for r in rws if not r['putcall'])), round(t / 1e6), fd)
                    break
            except Exception:
                pass
        out[rd] = got if got else ('信息表解析失败', fd)
    for rd in ('2026-03-31', '2026-06-30'):
        out.setdefault(rd, '该期无13F申报')
    return out


res = {}
with cf.ThreadPoolExecutor(max_workers=4) as ex:
    futs = {ex.submit(periods, c): c for c in chk}
    for i, fu in enumerate(cf.as_completed(futs)):
        c = futs[fu]
        try:
            res[c] = fu.result()
        except Exception as e:
            res[c] = type(e).__name__
        print(f'[{i+1}/{len(chk)}] {nm[c][:42]:42s} 面板 Q4/Q1/Q2 = ' +
              ' / '.join(str(int(f(by[c][p]['shares']))) if p in by[c] else '缺' for p in P) + f' | 原件 {res[c]}',
              flush=True)
json.dump(res, open(f'{TICK}_verify_gaps.json', 'w'), ensure_ascii=False, indent=1, default=str)
print('完成', flush=True)
