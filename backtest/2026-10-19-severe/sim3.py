"""单仓逐日: 第1天=五板次日. 买: 开盘缺口[-5%,+5%)开盘买; (可选)高开>=5%且9:45价格<+5%则按9:45价买.
卖: 第2到第4天盘中到100%异动线按线价卖; 到第4天仍未到线: (原)第4天收盘卖 / (新)若第4天开盘仍亏, 挂回本价, 盘中摸到成本就按成本卖, 摸不到收盘卖; 第4天开盘已盈利则收盘卖"""
import pandas as pd, numpy as np, json
src=open('sim.py').read().split("out=[]; keep={}")[0]; ns={}; exec(src,ns)
P=ns['P']; F0=ns['F'].copy(); series=ns['series']; trig_price=ns['trig_price']
F0['cap']=[P[c].close[P[c].date==d].iloc[0]*P[c].oshare[P[c].date==d].iloc[0] for c,d in zip(F0.code,F0.d5)]
M=json.load(open('min945.json'))
def entry(code,d5,use945):
    d,O,H,Lo,C,ZT,DT=series(code); i=int(d.index[d.date==d5][0]); b=i+1
    if b>=len(d) or Lo[b]>=ZT[b]*0.998: return None
    gap=O[b]/C[i]-1
    if -0.05<=gap<0.05: return b,O[b],'开盘'
    if use945 and gap>=0.05:
        m=M.get(f"{code}_{d.date[b].strftime('%Y-%m-%d')}")
        if m and m['price_945'] and m['price_945']/m['c5_raw']-1<0.05:
            af=d.adj_close[b]/d.close[b]; return b,m['price_945']*af,'9:45回落'
    return None
def exit_(code,b,buy,breakeven):
    d,O,H,Lo,C,ZT,DT=series(code)
    for t in range(b+1,min(b+4,len(d))):          # 第2到第4天
        pL=trig_price(d,t,1.0)
        if d.m10[t-1]>=1.0: return t,O[t],'过线次日开盘'
        if O[t]>=pL: return t,O[t],'开盘即过线'
        if H[t]>=pL and pL<=ZT[t]*1.0001: return t,pL,'盘中到线'
        if t==b+3:
            if breakeven and O[t]<buy:
                return (t,buy,'第4天回本卖') if H[t]>=buy else (t,C[t],'第4天没回本收盘卖')
            return t,C[t],'第4天收盘'
    t=len(d)-1; return t,C[t],'未平(按最新收盘)'
def run(F,use945,breakeven):
    tr=[]; free=pd.Timestamp('1900-01-01')
    for d5,g in F.groupby('d5',sort=True):
        for _,e in g.iterrows():
            en=entry(e.code,d5,use945)
            if en is None: continue
            b,buy,how=en; d=P[e.code]
            if d.date[b]<=free: continue
            t,s,why=exit_(e.code,b,buy,breakeven)
            tr.append({'五板日':d5.date(),'name':e['name'],'买法':how,'买入日':d.date[b].date(),'卖出日':d.date[t].date(),'收益':s/buy-1,'卖因':why}); free=d.date[t]; break
    return pd.DataFrame(tr)
res=[]; keep={}
for use945 in (False,True):
    for be in (False,True):
        vals=[]
        for start in ['2026-07-06','2026-07-20','2026-08-03','2026-08-17']:
            for order in ('turn','turn_desc','cap'):
                F=F0[F0.d5>=start].copy(); F['k']={'turn':F.turn,'turn_desc':-F.turn,'cap':-F.cap}[order]; F=F.sort_values(['d5','k'])
                X=run(F,use945,be); vals.append(np.prod(1+X.收益)-1)
                if start=='2026-07-06' and order=='turn': keep[(use945,be)]=X
        v=np.array(vals); X=keep[(use945,be)]
        res.append({'高开9:45回落买':'是' if use945 else '否','第4天回本卖':'是' if be else '否','笔数':len(X),'胜率':round((X.收益>0).mean()*100),'平均':round(X.收益.mean()*100,1),'基准路径复利':round((np.prod(1+X.收益)-1)*100),'12路径中位':round(np.median(v)*100),'最差':round(v.min()*100),'最好':round(v.max()*100)})
pd.to_pickle(keep,'sim3_trades.pkl')
print(pd.DataFrame(res).to_string(index=False))
for k,X in keep.items():
    print('\n',k); X['收益%']=(X.收益*100).round(1); print(X[['五板日','name','买法','买入日','卖出日','收益%','卖因']].to_string(index=False))
