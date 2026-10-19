"""偏离值面板: 个股日涨跌幅(前复权) - 基准指数日涨跌幅; 10日/30日滚动累计; 3日累计(异常波动)。供 q1/q2/q3 共用。"""
import json,re,urllib.request, pandas as pd, numpy as np, functools
H={'Referer':'https://finance.sina.com.cn','User-Agent':'Mozilla/5.0'}
@functools.lru_cache(None)
def idx(sym):
    u=f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20x=/CN_MarketDataService.getKLineData?symbol={sym}&scale=240&ma=no&datalen=400"
    raw=urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=15).read().decode()
    B=json.loads(re.search(r"x=\((\[.*\])\)",raw,re.S).group(1))
    return pd.Series({pd.Timestamp(b['day']):float(b['close']) for b in B}).sort_index().pct_change()
def panel(bench, start='2025-08-01'):
    A=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','open','high','low','close','adj_close','oshare'],filters=[('date','>=',pd.Timestamp(start))])
    A=A[A.ticker.str.endswith(('.SH','.SZ'))].copy(); A['code']=A.ticker.str[:6]
    A=A.sort_values(['code','date']).reset_index(drop=True); g=A.groupby('code')
    A['ret']=A.adj_close/g.adj_close.shift(1)-1
    A['board']=np.where(A.code.str[:3].isin(['688','689']),'kcb',np.where(A.code.str[:3].isin(['300','301']),'cyb',np.where(A.code.str[0]=='6','sh','sz')))
    A['iret']=np.nan
    for b,sym in bench.items():
        m=A.board==b; A.loc[m,'iret']=A.loc[m,'date'].map(idx(sym)).values
    A['dev']=(A.ret-A.iret).fillna(0)
    g=A.groupby('code')
    for n in (3,10,30): A[f'c{n}']=g.dev.transform(lambda x:x.rolling(n,min_periods=n).sum())
    return A
BENCH={'A':{'sh':'sh000001','sz':'sz399001','cyb':'sz399006','kcb':'sh000688'},
       'B':{'sh':'sh000001','sz':'sz399106','cyb':'sz399102','kcb':'sh000680'}}

def add_compound(A):
    """复利口径: 区间涨幅(收盘/区间前收盘-1) 减 基准同区间涨幅. 10-19 用开盘啦触发记录校准, 交易所口径是这个而不是日偏离相加"""
    g=A.groupby('code')
    A['ilvl']=(1+A.iret.fillna(0)).groupby(A.code).cumprod()
    for n in (3,10,30):
        A[f'k{n}']=(A.adj_close/g.adj_close.shift(n)-1)-(A.ilvl/A.groupby('code').ilvl.shift(n)-1)
    return A

def add_window_max(A, n=10, col='m10'):
    """窗口内任一起点到今天的复利偏离取最大(连续n个交易日"内"累计达到)"""
    g=A.groupby('code'); best=None
    for j in range(1,n+1):
        v=(A.adj_close/g.adj_close.shift(j)-1)-(A.ilvl/A.groupby('code').ilvl.shift(j)-1)
        best=v if best is None else np.fmax(best,v)
    A[col]=best
    return A
