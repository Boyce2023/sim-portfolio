#!/usr/bin/env python3
"""刷新 us_price_db/benchmarks/ 的 13 条基准与宏观锚。
⛔为什么单独有这个脚本: 2026-09-16 发现 prices/ 已到 09-15 而 benchmarks/SPY.parquet 停在 09-08,
  每日增量只更新了个股没更新基准。基准是所有对照与超额计算的分母, 落后会让"超额"静默失真,
  而且我当天正是拿这个过期文件当交易日历, 数出错误的回看天数。
⛔断言: 任一序列末日早于 SPY 末日超过 3 天就报出来(期货与指数是7天日历, 允许小差异)。
退出码 0=全部刷新 / 1=有序列失败 / 2=整体失败"""
import warnings, sys, os; warnings.filterwarnings('ignore')
import yfinance as yf, pandas as pd
B=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'data','us_price_db','benchmarks')
BM={'SPY':'SPY','QQQ':'QQQ','IWM':'IWM','DIA':'DIA','GSPC':'^GSPC','IXIC':'^IXIC','DJI':'^DJI','RUT':'^RUT',
    'VIX':'^VIX','TNX':'^TNX','DX-Y_NYB':'DX-Y.NYB','GC_F':'GC=F','CL_F':'CL=F'}
fail=[]; done=[]
for fn,sym in BM.items():
    try:
        s=yf.Ticker(sym).history(start='1990-01-01',interval='1d')
        if s.empty: fail.append((fn,'空')); continue
        s=s.rename(columns={'Adj Close':'adj_close'}); s.columns=[c.lower().replace(' ','_') for c in s.columns]
        if 'adj_close' not in s.columns: s['adj_close']=s['close']
        s.index.name='date'; s.to_parquet(os.path.join(B,f'{fn}.parquet'))
        done.append((fn,str(s.index[-1].date()),len(s)))
    except Exception as e: fail.append((fn,f'{type(e).__name__}: {str(e)[:60]}'))
if not done: print('⛔ 全部失败'); sys.exit(2)
spy=dict((d[0],d[1]) for d in done).get('SPY')
print(f"刷新 {len(done)}/{len(BM)} 条, SPY 末日 {spy}")
for fn,last,n in done:
    gap=(pd.Timestamp(spy)-pd.Timestamp(last)).days
    flag=' ⛔落后' if gap>3 else ''
    print(f"  {fn:10} 末日 {last} 行数 {n}{flag}")
if fail:
    print("⛔ 失败:", fail); sys.exit(1)
sys.exit(0)
