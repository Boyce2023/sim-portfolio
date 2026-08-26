import akshare as ak
import pandas as pd
import time, sys, json
from concurrent.futures import ThreadPoolExecutor, as_completed

t0 = time.time()
names_df = ak.stock_board_industry_name_em()
print(f"行业板块数={len(names_df)} elapsed={time.time()-t0:.1f}s", file=sys.stderr)
names_df.to_csv('industry_board_names.csv', index=False, encoding='utf-8-sig')
industries = names_df['板块名称'].tolist()

mapping = {}  # code(6digit) -> industry name
errors = []

def fetch_one(ind):
    try:
        df = ak.stock_board_industry_cons_em(symbol=ind)
        return ind, df['代码'].tolist(), None
    except Exception as e:
        return ind, [], str(e)

results = {}
with ThreadPoolExecutor(max_workers=4) as ex:
    futs = {ex.submit(fetch_one, ind): ind for ind in industries}
    done_n = 0
    for fut in as_completed(futs):
        ind, codes, err = fut.result()
        done_n += 1
        if err:
            errors.append({'industry': ind, 'error': err})
            print(f"[{done_n}/{len(industries)}] {ind} ERROR: {err}", file=sys.stderr)
        else:
            for c in codes:
                mapping[c] = ind
            print(f"[{done_n}/{len(industries)}] {ind}: {len(codes)}只", file=sys.stderr)

print(f"总耗时{time.time()-t0:.1f}s 覆盖股票数={len(mapping)} 失败行业数={len(errors)}", file=sys.stderr)
json.dump(mapping, open('code_industry_map.json', 'w'), ensure_ascii=False, indent=0)
json.dump(errors, open('industry_fetch_errors.json', 'w'), ensure_ascii=False, indent=2)
