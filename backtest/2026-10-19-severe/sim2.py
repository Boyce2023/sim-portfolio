"""单仓逐日模拟 + 换仓规则. 第1天=五板次日.
买点: B2 = 第1天开盘涨跌在[-5%,+5%)才开盘买; B9 = B2, 否则第1天盘中碰跌停按跌停价买
换仓(新五板的第1天开盘时, 现有持仓已过T+1可卖):
  S0 不换 / S1 只要新票满足开盘买条件就换 / S2 现持仓第1天盘中最高没过+8%(弱)才换 / S3 现持仓前一日收盘浮亏才换
  换仓=现持仓按新票第1天的开盘价卖出(同一天开盘), 新票开盘买. 跌停价买入的新票不参与换仓(盘中才知道)."""
import pandas as pd, numpy as np
src=open('sim.py').read().split("out=[]; keep={}")[0]; ns={}; exec(src,ns)
P=ns['P']; F0=ns['F'].copy(); trig_price=ns['trig_price']; series=ns['series']
F0['cap']=[P[c].close[P[c].date==d].iloc[0]*P[c].oshare[P[c].date==d].iloc[0] for c,d in zip(F0.code,F0.d5)]
def entry(code,d5,rule):
    d,O,H,Lo,C,ZT,DT=series(code); i=int(d.index[d.date==d5][0]); b=i+1
    if b>=len(d): return None
    yz=Lo[b]>=ZT[b]*0.998; gap=O[b]/C[i]-1
    if not yz and -0.05<=gap<0.05: return (b,O[b],'开盘')
    if rule=='B9' and Lo[b]<=DT[b]*1.002 and not yz: return (b,DT[b],'跌停接')
    return None
def run(rule,sw,L,maxday,F):
    trades=[]; pos=None   # pos: dict(code,b,buy,i5)
    days=sorted(set(F.d5))
    # 逐个五板日处理; 在两个五板日之间, 持仓按卖出规则自然了结
    def settle(pos,until_date):
        """持仓按规则走到 until_date(不含)之前是否已卖; 返回(已卖?, 卖出下标, 卖价)"""
        code=pos['code']; d,O,H,Lo,C,ZT,DT=series(code)
        t,sell,why=ns['exit_'](code,pos['b'],pos['buy'],L,pos['i5']+maxday-pos['b']+1)
        return t,sell,why
    for d5 in days:
        g=F[F.d5==d5].sort_values('turn')
        for _,e in g.iterrows():
            d=P[e.code]; i5=int(d.index[d.date==d5][0]); en=entry(e.code,d5,rule)
            if en is None: continue
            b,buy,how=en; bd=d.date[b]
            if pos is not None:
                t,sell,why=settle(pos,bd); pd_=P[pos['code']]
                if pd_.date[t]<bd:          # 已经自然卖出
                    trades.append(dict(pos['meta'],卖出日=pd_.date[t].date(),收益=sell/pos['buy']-1,卖因=why)); pos=None
                else:
                    # 仍持有: 判断是否换仓
                    if how!='开盘' or pd_.date[pos['b']]>=bd: continue      # 跌停接的新票不换; 当天买的不能卖
                    dd,O,H,Lo,C,ZT,DT=series(pos['code'])
                    k=int(dd.index[dd.date==bd][0]) if (dd.date==bd).any() else None
                    if k is None: continue
                    weak=H[pos['b']]/C[pos['i5']]-1<0.08
                    losing=C[k-1]/pos['buy']-1<0
                    ok={'S0':False,'S1':True,'S2':weak,'S3':losing}[sw]
                    if not ok: continue
                    trades.append(dict(pos['meta'],卖出日=bd.date(),收益=O[k]/pos['buy']-1,卖因='换仓开盘卖')); pos=None
            pos={'code':e.code,'b':b,'buy':buy,'i5':i5,'meta':{'五板日':d5.date(),'name':e['name'],'买入日':bd.date(),'买法':how}}
            break
    if pos is not None:
        t,sell,why=settle(pos,None); trades.append(dict(pos['meta'],卖出日=P[pos['code']].date[t].date(),收益=sell/pos['buy']-1,卖因=why))
    return pd.DataFrame(trades)
res=[]; keep={}
for rule in ('B2','B9'):
    for sw in ('S0','S1','S2','S3'):
        for L,md in ((1.0,4),(1.0,5),(0.95,4),(0.95,5)):
            vals=[]
            for start in ['2026-07-06','2026-07-20','2026-08-03','2026-08-17']:
                for order in ('turn','turn_desc','cap'):
                    F=F0[F0.d5>=start].copy()
                    if order=='turn_desc': F['turn']=-F.turn
                    if order=='cap': F['turn']=-F.cap
                    X=run(rule,sw,L,md,F)
                    vals.append(np.prod(1+X.收益)-1 if len(X) else 0)
                    if start=='2026-07-06' and order=='turn': keep[(rule,sw,L,md)]=X
            v=np.array(vals); X=keep[(rule,sw,L,md)]
            res.append({'买点':rule,'换仓':sw,'线':f'{int(L*100)}%','最晚':f'第{md}天','笔数(基准路径)':len(X),'胜率':round((X.收益>0).mean()*100),'基准路径复利':round((np.prod(1+X.收益)-1)*100),'12路径中位':round(np.median(v)*100),'最差':round(v.min()*100),'最好':round(v.max()*100)})
R=pd.DataFrame(res); R.to_pickle('sim2_summary.pkl'); pd.to_pickle(keep,'sim2_trades.pkl')
pd.set_option('display.width',200); print(R.to_string(index=False))
