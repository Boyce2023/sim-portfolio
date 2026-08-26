import akshare as ak
import pandas as pd
import time, sys

boards = ['充电桩','无线充电','储能概念','熔盐储能','固态电池','虚拟电厂','光伏概念','锂电池概念','换电概念']
found = []
for b in boards:
    for attempt in range(3):
        try:
            df = ak.stock_board_concept_cons_em(symbol=b)
            df.to_csv(f'concept_cons_{b}.csv', index=False, encoding='utf-8-sig')
            hit = df[df['代码'].astype(str).str.zfill(6) == '600212']
            print(f"{b}: rows={len(df)} 600212_in={'YES' if len(hit) else 'no'}")
            if len(hit):
                found.append(b)
            break
        except Exception as e:
            print(f"{b} attempt{attempt} ERR {type(e).__name__} {e}")
            time.sleep(1)
print("FOUND_IN:", found)
