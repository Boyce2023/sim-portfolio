"""日线: 宇宙个股+主题ETF, 2025-09-01 起(够算52周高), Close=拆股调整未除息(与旧表同口径)。存 px.pkl / vol.pkl"""
import json, pandas as pd, yfinance as yf, time, warnings
warnings.filterwarnings('ignore')
uni=[u['t'] for u in json.load(open('universe.json'))]
ETF=json.load(open('etfs.json'))
tk=uni+[e[0] for e in ETF if e[0] not in uni]
C,V=[],[]
for i in range(0,len(tk),150):
    b=tk[i:i+150]
    for a in range(3):
        try:
            d=yf.download(b,start='2025-09-01',end='2026-10-18',auto_adjust=False,progress=False,threads=True,group_by='column')
            C.append(d['Close']); V.append(d['Volume']); break
        except Exception as e:
            print('retry',i,e); time.sleep(10)
    print(i+len(b),'/',len(tk),flush=True)
px=pd.concat(C,axis=1); vol=pd.concat(V,axis=1)
px=px.loc[:,~px.columns.duplicated()]; vol=vol.loc[:,~vol.columns.duplicated()]
px.to_pickle('px.pkl'); vol.to_pickle('vol.pkl')
print('shape',px.shape,'最后日',px.index[-1].date(),'最后日缺失',int(px.iloc[-1].isna().sum()))
