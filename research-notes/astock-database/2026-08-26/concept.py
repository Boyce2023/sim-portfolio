import akshare as ak
import pandas as pd
import sys, time

try:
    t0=time.time()
    df = ak.stock_board_concept_name_em()
    print(f"list elapsed={time.time()-t0:.1f}s rows={len(df)}")
    df.to_csv("concept_board_list.csv", index=False, encoding="utf-8-sig")
except Exception as e:
    print("ERROR list:", type(e).__name__, e, file=sys.stderr)

try:
    t0=time.time()
    info = ak.stock_individual_info_em(symbol="600212")
    print(info.to_string())
    info.to_csv("individual_info_600212.csv", index=False, encoding="utf-8-sig")
except Exception as e:
    print("ERROR info:", type(e).__name__, e, file=sys.stderr)
