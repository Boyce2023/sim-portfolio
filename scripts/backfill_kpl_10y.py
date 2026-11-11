#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
开盘啦历史题材与涨停库补齐脚本 (2018-04 至 2021-10-18)
写入独立增量文件: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_2016_2021.jsonl
"""
import os
import sys
import time
import json
import datetime
import importlib.util

OUTPUT_FILE = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_2016_2021.jsonl'
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

kpl_path = os.path.expanduser('~/claude-projects/sim-portfolio/scripts/kpl_archive.py')
spec = importlib.util.spec_from_file_location('kpl_archive', kpl_path)
kpl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kpl)
kpl.alert = lambda m: None

done_dates = set()
if os.path.exists(OUTPUT_FILE):
    with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    obj = json.loads(line)
                    done_dates.add(obj.get('date'))
                except Exception:
                    pass

print(f'已完成天数: {len(done_dates)}')

start_date = datetime.date(2018, 4, 1)
end_date = datetime.date(2021, 10, 18)
cur = start_date
dates_to_pull = []
while cur <= end_date:
    if cur.weekday() < 5:
        ds = cur.strftime('%Y-%m-%d')
        if ds not in done_dates:
            dates_to_pull.append(ds)
    cur += datetime.timedelta(days=1)

print(f'待拉取工作日数: {len(dates_to_pull)}')

def day_plates(date_str):
    plates, idx, seen = [], 0, set()
    while idx < 90:
        d = kpl.get('apphis', {'c': 'HisLimitResumption', 'a': 'GetPlateInfo_w38', 'Date': date_str, 'Index': idx})
        L = (d.get('list') if isinstance(d, dict) else None) or []
        if not L:
            break
        for p in L:
            zs_name = p.get('ZSName', '')
            if zs_name in seen:
                continue
            seen.add(zs_name)
            stock_list = []
            for s in p.get('StockList', []):
                sym = s[0] if len(s) > 0 else ''
                name = s[1] if len(s) > 1 else ''
                r1 = (s[16] if len(s) > 16 else '') or ''
                r2 = ((s[17] if len(s) > 17 else '') or '').split('；')[0][:60]
                stock_list.append([sym, name, r1, r2])
            plates.append({'plate': zs_name, 'stocks': stock_list})
        idx += 3
        time.sleep(0.35)
    return plates

success_count = 0
empty_count = 0
with open(OUTPUT_FILE, 'a', encoding='utf-8') as out_f:
    for i, ds in enumerate(dates_to_pull):
        try:
            pls = day_plates(ds)
            if pls:
                rec = {'date': ds, 'plates': pls}
                out_f.write(json.dumps(rec, ensure_ascii=False) + '\n')
                out_f.flush()
                success_count += 1
                if success_count % 5 == 0:
                    print(f'[{datetime.datetime.now().strftime("%H:%M:%S")}] 成功拉取 {ds}, 板块数={len(pls)}, 累计成功={success_count}/{len(dates_to_pull)}')
            else:
                empty_count += 1
        except Exception as e:
            print(f'拉取 {ds} 异常: {e}')
        time.sleep(0.3)

print(f'全部结束! 成功={success_count}, 空={empty_count}')
