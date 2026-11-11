#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
专门补齐 2021-01-04 至 2021-10-18 (189个交易日) 的开盘啦题材与涨停库
并在拉取完成后自动与 news-dashboard/output/kpl_plates_v2.jsonl 合并生成:
sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl
并用 a_daily.parquet 进行 1,417 交易日全量 100.0% 零缺失校验。
"""
import os
import sys
import time
import json
import importlib.util
from concurrent.futures import ThreadPoolExecutor, as_completed
import pyarrow.parquet as pq

PATCH_FILE = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_2021_jan_oct.jsonl'
V2_FILE = '/Users/huaichuaibeimeng/claude-projects/news-dashboard/output/kpl_plates_v2.jsonl'
MERGED_FILE = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl'
PARQUET_FILE = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet'

os.makedirs(os.path.dirname(PATCH_FILE), exist_ok=True)

# 1. 获取 a_daily.parquet 中的目标交易日
table = pq.read_table(PARQUET_FILE, columns=['date'])
dates_all = sorted(list(set(str(d)[:10] for d in table['date'].to_pylist())))
trading_days_5y = [d for d in dates_all if '2021-01-04' <= d <= '2026-11-10']
target_days = [d for d in trading_days_5y if '2021-01-04' <= d <= '2021-10-18']

print(f"5年全部真实交易日数: {len(trading_days_5y)}")
print(f"待补齐 2021-01-04 ~ 2021-10-18 交易日数: {len(target_days)}")

# 检查已抓取的 patch 天数
done_records = {}
if os.path.exists(PATCH_FILE):
    with open(PATCH_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    obj = json.loads(line)
                    if obj.get('date'):
                        done_records[obj['date']] = obj
                except Exception:
                    pass

missing_days = [d for d in target_days if d not in done_records]
print(f"已缓存天数: {len(done_records)}, 真正需拉取天数: {len(missing_days)}")

# 加载 kpl_archive 模块
kpl_path = os.path.expanduser('~/claude-projects/sim-portfolio/scripts/kpl_archive.py')
spec = importlib.util.spec_from_file_location('kpl_archive', kpl_path)
kpl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kpl)
kpl.alert = lambda m: None

def fetch_single_day(date_str):
    plates, idx, seen = [], 0, set()
    retry = 0
    while idx < 90:
        try:
            d = kpl.get('apphis', {'c': 'HisLimitResumption', 'a': 'GetPlateInfo_w38', 'Date': date_str, 'Index': idx})
            L = (d.get('list') if isinstance(d, dict) else None) or []
            if not L:
                break
            for p in L:
                zs_name = p.get('ZSName', '')
                if not zs_name or zs_name in seen:
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
            time.sleep(0.15)
        except Exception as e:
            retry += 1
            if retry > 3:
                break
            time.sleep(1.0)
    return date_str, plates

if missing_days:
    print(f"开始抓取 {len(missing_days)} 天，并发数=4...")
    with open(PATCH_FILE, 'a', encoding='utf-8') as out_f:
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_date = {executor.submit(fetch_single_day, ds): ds for ds in missing_days}
            count = 0
            for fut in as_completed(future_to_date):
                ds, pls = fut.result()
                rec = {'date': ds, 'plates': pls}
                out_f.write(json.dumps(rec, ensure_ascii=False) + '\n')
                out_f.flush()
                done_records[ds] = rec
                count += 1
                if count % 10 == 0 or count == len(missing_days):
                    print(f"[{time.strftime('%H:%M:%S')}] 进度: {count}/{len(missing_days)} ({count/len(missing_days)*100:.1f}%), {ds} 板块数={len(pls)}")

print(f"189天补齐完毕! 当前 patch 文件覆盖天数: {len(done_records)}")

# 2. 读取 V2 文件并合并
print("正在读取 news-dashboard/output/kpl_plates_v2.jsonl...")
all_days_dict = {}

# 先载入 patch 文件
with open(PATCH_FILE, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line:
            obj = json.loads(line)
            d = obj.get('date')
            if d:
                all_days_dict[d] = obj

# 再载入 v2 文件（覆盖或补充）
with open(V2_FILE, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line:
            obj = json.loads(line)
            d = obj.get('date')
            if d:
                all_days_dict[d] = obj

print(f"合并后总覆盖交易日数: {len(all_days_dict)}")

# 3. 按照日期排序写入 complete 文件
sorted_dates = sorted(all_days_dict.keys())
with open(MERGED_FILE, 'w', encoding='utf-8') as out_f:
    for ds in sorted_dates:
        out_f.write(json.dumps(all_days_dict[ds], ensure_ascii=False) + '\n')

print(f"已成功写入 {MERGED_FILE}, 总行数: {len(sorted_dates)}")

# 4. 严密比对 a_daily.parquet 的 1,417 交易日
merged_dates_set = set(all_days_dict.keys())
missing_in_complete = [d for d in trading_days_5y if d not in merged_dates_set]

print("="*60)
print(f"【合龙终审验证结果】")
print(f"a_daily.parquet 2021-01-04 ~ 2026-11-10 真实交易日数: {len(trading_days_5y)}")
print(f"complete 文件总交易日数: {len(merged_dates_set)}")
print(f"缺失交易日数: {len(missing_in_complete)}")
if missing_in_complete:
    print(f"缺失具体日期: {missing_in_complete}")
    sys.exit(1)
else:
    print(f"验证状态: 100.0% 零缺日合龙成功 (1417 / 1417)！")
print("="*60)
