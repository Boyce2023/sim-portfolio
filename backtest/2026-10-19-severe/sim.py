"""五板策略 7月起逐日模拟(一次只拿一只, 满仓复利). 天数口径: 五板次日=第1天.
事件: 7月起价格口径纯连续第5个涨停(2026-10-19-5ban-day23/events.pkl).
同日多只五板: 按五板当天换手低者优先(当时可知); 一只买不到(一字/没触发买点)就试下一只.
持仓期间出现的新五板一律放弃. 卖出当天不能再买(新票第1天必须晚于卖出日).
卖出统一: 盘中到异动线价位即按线价卖(前一日收盘已过线则开盘卖), 到不了就第4天或第5天收盘卖.
买点(都在第1天, 第1天=五板次日):
  B1 开盘买
  B2 开盘缺口在 -5% 到 +5% 之间才开盘买, 否则当天不买
  B3 开盘买; 若开盘缺口 >=5%(高开太多)改为盘中回落到+5%才买, 回不来就不买
  B4 只在盘中碰跌停时按跌停价买
  B5 混合: 开盘缺口<+5% 开盘买; 高开>=5% 则等碰跌停(按跌停价)否则不买
  B6 只在盘中触涨停时按涨停价买(打六板, 一字不算)
  B7 收盘买
  B8 混合: 第1天开盘缺口<+5% 开盘买; 否则若第1天碰跌停按跌停价买; 否则若第1天收涨停, 第2天开盘买(非一字)
"""
import pandas as pd, numpy as np, sys
A=pd.read_pickle('/private/tmp/claude-501/-Users-huaichuaibeimeng-claude-projects/0271364f-8cab-4319-af5d-5048f0719e12/scratchpad/devpanel.pkl')
P={c:d.reset_index(drop=True) for c,d in A.groupby('code')}
T=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','turn'],filters=[('date','>=',pd.Timestamp('2026-06-25'))]); T['code']=T.ticker.str[:6]; TURN=T.set_index(['code','date']).turn
F=pd.read_pickle('../2026-10-19-5ban-day23/events.pkl')[['code','name','d5']].copy()
F['d5']=pd.to_datetime(F.d5); F['turn']=[TURN.get((c,d),np.nan) for c,d in zip(F.code,F.d5)]
LAST=A.date.max()
def trig_price(d,t,L):
    best=np.inf
    for j in range(1,11):
        if t-j<0: break
        best=min(best,d.adj_close[t-j]*(1+L+(d.ilvl[t]/d.ilvl[t-j]-1)))
    return best
def series(code):
    d=P[code]; af=d.adj_close/d.close
    return d, d.open*af, d.high*af, d.low*af, d.adj_close, d.adj_close.shift(1)*(1+d.lim), d.adj_close.shift(1)*(1-d.lim)
def entry(code,d5,rule):
    """返回 (买入下标, 买价) 或 None"""
    d,O,H,Lo,C,ZT,DT=series(code); i=int(d.index[d.date==d5][0]); b=i+1
    if b>=len(d): return None
    yz=Lo[b]>=ZT[b]*0.998; gap=O[b]/C[i]-1
    touch_dt=Lo[b]<=DT[b]*1.002; touch_zt=H[b]>=ZT[b]*0.998
    if rule=='B1': return None if yz else (b,O[b])
    if rule=='B2': return (b,O[b]) if (not yz and -0.05<=gap<0.05) else None
    if rule=='B3':
        if yz: return None
        if gap<0.05: return (b,O[b])
        return (b,C[i]*1.05) if Lo[b]<=C[i]*1.05 else None
    if rule=='B4': return (b,DT[b]) if touch_dt else None
    if rule=='B5':
        if yz: return None
        if gap<0.05: return (b,O[b])
        return (b,DT[b]) if touch_dt else None
    if rule=='B6': return (b,ZT[b]) if (touch_zt and not yz) else None
    if rule=='B7': return None if yz else (b,C[b])
    if rule=='B8':
        if not yz and gap<0.05: return (b,O[b])
        if not yz and touch_dt: return (b,DT[b])
        if d.zt[b] and b+1<len(d) and not (Lo[b+1]>=ZT[b+1]*0.998): return (b+1,O[b+1])
        return None
def exit_(code,t0,buy,L,maxday):
    """t0=买入下标(第1天或第2天); 第maxday天收盘为最晚卖点, 天数从五板次日算起由调用方折算"""
    d,O,H,Lo,C,ZT,DT=series(code)
    for t in range(t0+1,min(t0+maxday,len(d))):
        pL=trig_price(d,t,L)
        if d.m10[t-1]>=L: return t,O[t],'过线次日开盘'
        if O[t]>=pL: return t,O[t],'开盘即过线'
        if H[t]>=pL and pL<=ZT[t]*1.0001: return t,pL,'盘中到线'
    t=t0+maxday-1
    if t>=len(d): return len(d)-1,C[len(d)-1],'未平(按最新收盘计)'
    return t,C[t],f'第{maxday}天收盘'
def run(rule,L,maxday):
    trades=[]; free_after=pd.Timestamp('1900-01-01')
    for d5,g in F.sort_values(['d5','turn']).groupby('d5',sort=True):
        for _,e in g.iterrows():
            d=P[e.code]
            en=entry(e.code,d5,rule)
            if en is None: continue
            b,buy=en
            if d.date[b]<=free_after: continue
            # 第1天=五板次日, maxday按五板次日算 -> 若在第2天买入, 最晚卖点仍是五板次日起第maxday天
            i5=int(d.index[d.date==d5][0]); last_idx=i5+maxday
            t,sell,why=exit_(e.code,b,buy,L,last_idx-b+1)
            trades.append({'五板日':d5.date(),'name':e['name'],'买入日':d.date[b].date(),'买价相对五板收':buy/d.adj_close[i5]-1,'卖出日':d.date[t].date(),'持有天':t-b,'收益':sell/buy-1,'卖因':why})
            free_after=d.date[t]
            break
    return pd.DataFrame(trades)
out=[]; keep={}
for rule in ['B1','B2','B3','B4','B5','B6','B7','B8']:
    for L in (0.95,1.0):
        for md in (4,5):
            X=run(rule,L,md)
            if not len(X): continue
            eq=np.cumprod(1+X.收益.values); dd=(eq/np.maximum.accumulate(eq)-1).min()
            out.append({'买点':rule,'线':f'{int(L*100)}%','最晚':f'第{md}天','笔数':len(X),'胜率':(X.收益>0).mean(),'平均':X.收益.mean(),'复利':eq[-1]-1,'最大回撤':dd,'平均持有天':X.持有天.mean()})
            keep[(rule,L,md)]=X
S=pd.DataFrame(out); S.to_pickle('sim_summary.pkl'); pd.to_pickle(keep,'sim_trades.pkl')
pd.set_option('display.width',200)
print('数据截至',LAST.date())
print(S.assign(胜率=lambda z:(z.胜率*100).round(0),平均=lambda z:(z.平均*100).round(1),复利=lambda z:(z.复利*100).round(0),最大回撤=lambda z:(z.最大回撤*100).round(0),平均持有天=lambda z:z.平均持有天.round(1)).to_string(index=False))
