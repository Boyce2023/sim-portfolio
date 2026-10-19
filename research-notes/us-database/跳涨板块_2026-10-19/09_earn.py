"""财报事件 → 反应日与涨跌。8-K 2.02 为主; 外国发行人与无8-K者用 NASDAQ 日历日。窗口内事件(反应日 08-24~10-16)。存 earn_events.pkl"""
import json, pandas as pd, numpy as np
px=pd.read_pickle('px.pkl'); days=px.index
uni={u['t']:u for u in json.load(open('universe.json'))}
k8=json.load(open('earn_8k.json')); cal=json.load(open('earn_cal.json'))
W0,W1=pd.Timestamp('2026-08-24'),pd.Timestamp('2026-10-16')
def nxt(d,inclusive=True):
    d=pd.Timestamp(d); i=days.searchsorted(d) if inclusive else days.searchsorted(d,side='right')
    return days[i] if i<len(days) else None
ev=[]
acc=json.load(open('earn_8k_acc.json'))
for t,v in acc.items():
    seen=set()
    for e in v:
        # ⛔ acceptanceDateTime 是 UTC, 已转美东: 美东16:00前申报=当日反应(多为盘前发稿、盘中补8-K), 16:00及以后=次一交易日
        same=e['time_et']<'16:00'
        rd=nxt(e['date_et'],inclusive=True) if same else nxt(e['date_et'],inclusive=False)
        if rd is None or rd in seen: continue
        seen.add(rd)
        ev.append(dict(t=t,edate=e['date_et'],rday=rd,session='盘前' if e['time_et']<'09:30' else ('盘中' if same else '盘后'),src='8-K',acc=e['time_et']))
has8k={x['t'] for x in ev}
cal_by={}
for r in cal: cal_by.setdefault(r['symbol'].replace('.','-'),[]).append(r['_date'])
for t,ds in cal_by.items():
    if t not in uni or t in has8k: continue
    for d in sorted(set(ds)):
        rd=nxt(d)
        ev.append(dict(t=t,edate=d,rday=rd,session='未披露',src='NASDAQ日历',acc=''))
ev=pd.DataFrame(ev); ev=ev[(ev.rday>=W0)&(ev.rday<=W1)&ev.t.isin(px.columns)&ev.t.isin(list(uni))].copy()
def row(r):
    s=px[r.t]; i=days.get_loc(r.rday)
    pc,c=s.iloc[i-1],s.iloc[i]
    return pd.Series(dict(pc=pc,c=c,pct=c/pc-1,now=s.iloc[-1],since=s.iloc[-1]/c-1,hi52=s.iloc[-253:].max(),
                          d5=(s.iloc[min(i+5,len(s)-1)]/c-1) if i+5<len(s) else np.nan))
ev=pd.concat([ev.reset_index(drop=True),ev.apply(row,axis=1).reset_index(drop=True)],axis=1).dropna(subset=['pct'])
# 交叉核: 8-K 日与 NASDAQ 日历日相差>3天的标出
def gap(r):
    ds=cal_by.get(r.t,[]); 
    if r.src!='8-K' or not ds: return ''
    g=min(abs((pd.Timestamp(d)-pd.Timestamp(r.edate)).days) for d in ds)
    return '日历差%d天'%g if g>3 else ''
ev['chk']=ev.apply(gap,axis=1)
ev.to_pickle('earn_events.pkl')
print('事件',len(ev),'公司',ev.t.nunique(),'来源',ev.src.value_counts().to_dict(),'时点',ev.session.value_counts().to_dict(),'日历差',int((ev.chk!='').sum()))
print(ev.sort_values('pct',ascending=False)[['t','edate','rday','session','pct','since']].head(12).to_string())
