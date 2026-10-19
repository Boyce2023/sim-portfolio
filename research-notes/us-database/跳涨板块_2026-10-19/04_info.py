"""yfinance info: 行业/简介/PE_TTM/营收同比, 存 info.json (可断点续)"""
import json, os, yfinance as yf, concurrent.futures as cf, time, warnings
warnings.filterwarnings('ignore')
uni=[u['t'] for u in json.load(open('universe.json'))]
out=json.load(open('info.json')) if os.path.exists('info.json') else {}
need=[t for t in uni if t not in out]
K=['shortName','longName','sector','industry','longBusinessSummary','trailingPE','forwardPE','revenueGrowth','earningsGrowth','marketCap','profitMargins','totalRevenue','quoteType']
def one(t):
    for a in range(3):
        try:
            i=yf.Ticker(t).info
            return t,{k:i.get(k) for k in K}
        except Exception as e:
            time.sleep(3*(a+1))
    return t,None
n=0
with cf.ThreadPoolExecutor(3) as ex:
    for t,d in ex.map(one,need):
        if d: out[t]=d
        n+=1
        if n%200==0:
            json.dump(out,open('info.json','w')); print(n,'/',len(need),flush=True)
json.dump(out,open('info.json','w')); print('完成',len(out),'/',len(uni))
