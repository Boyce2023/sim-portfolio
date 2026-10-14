#!/opt/homebrew/bin/python3.13
"""同高度连板竞争回测(2026-07-01 至 10-12 决策日, 结局看下一交易日是否继续涨停).
组 = 同一天、同一连板高度(连续N天N板, N=2/3/4)的全部个股, 含创业板科创板. 另做'同高度且同题材'子组.
特征均为 T 日收盘可得: 流通市值、换手、首封时间、炸板次数、封单/流通、封单/成交额(封成比)、板型(一字/T字/换手)、回封、20cm、股价、题材当日涨停数."""
import json,glob,os,sys,itertools,contextlib,io,pandas as pd,numpy as np
sys.path.insert(0,'../2026-10-09-theme')
with contextlib.redirect_stdout(io.StringIO()):
    _c=os.getcwd(); os.chdir('../2026-10-09-theme'); from theme import themes; os.chdir(_c)
rows=[]
for f in sorted(glob.glob('../2026-10-09-theme/ths/2026*.json')):
    d=f.split('/')[-1][:8]
    if d<'20260625': continue
    for r in json.load(open(f)):
        v=int(r.get('high_days_value') or 65537); cap=float(r.get('currency_value') or 0)/1e8; turn=float(r.get('turnover_rate') or 0)
        amt=cap*turn/100
        rows.append(dict(date=pd.Timestamp(d),code=r['code'],name=r['name'],lb=v>>16,days=v&0xFFFF,cap=cap,turn=turn,
            first=pd.Timestamp(int(r.get('first_limit_up_time') or 0),unit='s',tz='UTC').tz_convert('Asia/Shanghai').strftime('%H%M'),
            open_num=int(r.get('open_num') or 0),seal=float(r.get('order_amount') or 0)/1e8,amt=amt,typ=r.get('limit_up_type') or '',
            again=int(r.get('is_again_limit') or 0),is20=r['code'][:3] in('300','301','688','689'),price=float(r.get('latest') or 0),
            ths=sorted(themes(r.get('reason_type')))))
Z=pd.DataFrame(rows); Z['first']=Z['first'].astype(int)
Z['封单占流通']=Z.seal/Z.cap; Z['封成比']=Z.seal/Z.amt.replace(0,np.nan); Z['一字']=(Z.typ=='一字板').astype(int)
cal=sorted(Z.date.unique()); nxt={cal[i]:cal[i+1] for i in range(len(cal)-1)}
zt={(d,c) for d,c in zip(Z.date,Z.code)}
tc=Z.explode('ths').groupby(['date','ths']).code.nunique()
Z['题材涨停数']=[max([tc.get((d,t),0) for t in ts] or [0]) for d,ts in zip(Z.date,Z.ths)]
Z['晋级']=[((nxt[d],c) in zt) if d in nxt else np.nan for d,c in zip(Z.date,Z.code)]
H=Z[(Z.date>=pd.Timestamp('2026-07-01'))&(Z.lb.between(2,4))&(Z.lb==Z.days)&Z.晋级.notna()].copy()
H['晋级']=H.晋级.astype(float); H['段']=np.where(H.date<pd.Timestamp('2026-09-01'),'7-8月','9-10月')
H.to_pickle('H.pkl')
FEAT=[('流通市值最大','cap',1),('流通市值最小','cap',-1),('换手最低','turn',-1),('换手最高','turn',1),('封板最早','first',-1),('封板最晚','first',1),
      ('炸板最少','open_num',-1),('封单占流通最高','封单占流通',1),('封成比最高','封成比',1),('一字板','一字',1),('股价最低','price',-1),('股价最高','price',1),
      ('题材涨停最多','题材涨停数',1),('20cm','is20',1)]
def evaluate(groups,label):
    out=[]
    for nm,col,sg in FEAT:
        rec={'挑法':nm}
        for seg in ('全部','7-8月','9-10月'):
            sel=[];base=[];win=n=0
            for g in groups:
                if seg!='全部' and g.段.iloc[0]!=seg: continue
                v=g[col]*sg
                if v.isna().any(): continue
                top=v==v.max()
                if top.all() or top.sum()>1 and col not in('一字','is20'): continue   # 并列不挑(一字/20cm是二元, 取整组里属于该类的)
                s=g[top]; o=g[~top]
                sel.append(s.晋级.mean()); base.append(g.晋级.mean())
                if s.晋级.mean()!=o.晋级.mean(): n+=1; win+=s.晋级.mean()>o.晋级.mean()
            rec[f'{seg}组数']=len(sel); rec[f'{seg}挑中晋级']=round(np.mean(sel)*100) if sel else np.nan
            rec[f'{seg}组均晋级']=round(np.mean(base)*100) if base else np.nan; rec[f'{seg}分化占优']=f'{win}/{n}'
        out.append(rec)
    T=pd.DataFrame(out); print(f'\n===== {label} ====='); print(T.to_string(index=False)); return T
res={}
for lb in (2,3,4):
    G=[g for _,g in H[H.lb==lb].groupby('date') if len(g)>=2]
    print(f'\n{lb}板: 组 {len(G)} 个, 只次 {sum(len(g) for g in G)}, 组均人数 {np.mean([len(g) for g in G]):.1f}, 整体晋级率 {H[H.lb==lb].晋级.mean():.0%}')
    res[lb]=evaluate(G,f'{lb}板 同高度全市场')
G=[g for _,g in H.groupby(['date','lb']) if len(g)>=2]
res['all']=evaluate(G,'2到4板合并 同高度全市场')
# 同高度且同题材
E=H.explode('ths'); E=E[E.ths.notna()]
GT=[g.drop_duplicates('code') for _,g in E.groupby(['date','lb','ths']) if g.code.nunique()>=2]
print(f'\n同高度同题材组 {len(GT)} 个'); res['theme']=evaluate(GT,'2到4板 同高度且同题材')
pd.concat({str(k):v for k,v in res.items()}).to_csv('race_result.csv',encoding='utf-8-sig')
