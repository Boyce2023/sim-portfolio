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
        # ⛔2026-09-16: 收盘后数小时内 yfinance 给的当日bar是半截的, open/high/low/volume 有值而 close 是 NaN。
        #   不过滤就照样落盘, 还因日期最大成了"末日" —— DIA/IWM/QQQ/SPY 四条核心基准的 09-15 全是这种空行,
        #   而下面的断言只比日期不比值, 于是"SPY 末日 09-15"是假的。SPY 是一切超额计算的分母,
        #   这一行空值会让所有"超额"静默偏掉半个百分点, 且下游取价时只会安静地回退到 09-14。
        s=s[s['close'].notna()]
        if s.empty: fail.append((fn,'过滤空收盘后为空')); continue
        s.index.name='date'; s.to_parquet(os.path.join(B,f'{fn}.parquet'))
        done.append((fn,str(s.index[-1].date()),len(s),float(s['close'].iloc[-1])))
    except Exception as e: fail.append((fn,f'{type(e).__name__}: {str(e)[:60]}'))
if not done: print('⛔ 全部失败'); sys.exit(2)
spy=dict((d[0],d[1]) for d in done).get('SPY')
print(f"刷新 {len(done)}/{len(BM)} 条, SPY 末日 {spy}")
for fn,last,n,px in done:
    gap=(pd.Timestamp(spy)-pd.Timestamp(last)).days
    flag=' ⛔落后' if gap>3 else ''
    # ⛔末日的收盘值也要打出来: 只打日期的话, 一行空收盘的"末日 09-15"和真有价的"末日 09-15"长得一模一样。
    print(f"  {fn:10} 末日 {last} 收盘 {px:.2f} 行数 {n}{flag}")
# ⛔2026-10-20: 本脚本从 09-16 起每天刷数据, 却从没回写 catalog.csv, 于是 catalog 里 13 条基准的 last 一直停在 09-08,
#   10-19 复查时我据此误判'DIA/DJI 增量停了'。数据其实是新的, 坏的是目录。按 refresh_aux 同样的口径回写 last/n/status。
CAT=os.path.join(os.path.dirname(B),'catalog.csv'); cat=pd.read_csv(CAT)
for fn,last,n,px in done:
    m=(cat.category=='benchmark')&(cat.series==fn)
    if m.any(): cat.loc[m,'last']=last; cat.loc[m,'n']=n; cat.loc[m,'status']='ok'
for fn,err in fail:
    cat.loc[(cat.category=='benchmark')&(cat.series==fn),'status']='failed'
cat.to_csv(CAT,index=False); print(f'catalog.csv 已回写 {len(done)} 条基准')
if fail:
    print("⛔ 失败:", fail); sys.exit(1)
sys.exit(0)
