import akshare as ak
import time

t0 = time.time()
try:
    df = ak.stock_board_industry_name_em()
    print("SUCCESS em industry list, shape:", df.shape)
    print(df.columns.tolist())
    print(df.head(20))
except Exception as e:
    print("ERROR em:", repr(e))
print("elapsed:", time.time()-t0)
