#!/usr/bin/env python3
"""每交易日15:30留存东财涨停池快照(含首次封板时间/炸板次数/封板资金/换手), 供B策略逐笔验成交(东财仅保留约1个月历史)。
输出: data/zt_pool/YYYYMMDD.json  (2026-09-02建)"""
import json,sys,datetime,os,time
import akshare as ak
D=sys.argv[1] if len(sys.argv)>1 else datetime.date.today().strftime('%Y%m%d')
if datetime.datetime.strptime(D,'%Y%m%d').weekday()>4: print('weekend skip'); sys.exit(0)
out=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'data','zt_pool',f'{D}.json')
for a in range(3):
    try:
        df=ak.stock_zt_pool_em(date=D)
        if df is None or not len(df): raise RuntimeError('empty')
        json.dump(df.to_dict('records'),open(out,'w'),ensure_ascii=False,default=str)
        print(f'zt_pool {D}: {len(df)}板 → {out}'); sys.exit(0)
    except Exception as e:
        err=e; time.sleep(5)
print(f'zt_pool {D} FAIL: {err}'); sys.exit(1)
