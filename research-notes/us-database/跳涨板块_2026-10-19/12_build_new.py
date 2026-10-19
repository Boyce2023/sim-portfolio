"""新表: Track/1_活表/1选股_跳涨板块追踪.xlsx (封面 + 4 张)。⛔文字列断言: 主业<=10字, AI增速<=20字, 备注<=20字"""
import json, sys, os, shutil, datetime, pandas as pd, numpy as np, openpyxl
from xl import put, sheet, scale, notes, YEL
OUT=sys.argv[1] if len(sys.argv)>1 else '/Users/huaichuaibeimeng/Desktop/Track/1_活表/1选股_跳涨板块追踪.xlsx'
uni={u['t']:u for u in json.load(open('universe.json'))}; info=json.load(open('info.json'))
tags=json.load(open('tags.json')); growth=json.load(open('growth.json')); fc=json.load(open('fund_counts.json'))
ORD={'AI核心':0,'AI受益':1,'AI应用':2,'科技':3,'非科技':4}
import re
_SUF=re.compile(r'(,?\s+(Inc\.?|Incorporated|Corporation|Corp\.?|Company|Co\.|Holdings?|Ltd\.?|Limited|plc|PLC|N\.V\.|S\.A\.(B\. de C\.V\.)?|SE|AG|L\.P\.|LP|Group|Common Stock|Ordinary Shares|American Depositary Shares.*|Class [A-C].*))+$')
def nm(t):
    i=info.get(t) or {}; n=i.get('longName') or i.get('shortName') or uni.get(t,{}).get('name') or t
    n=_SUF.sub('',n.strip()).strip(' ,'); return n[:26]
def ind(t): return (info.get(t) or {}).get('industry') or uni.get(t,{}).get('industry') or ''
def mc(t): return round(uni[t]['mc_b']*10) if t in uni else None
def pe(t):
    v=(info.get(t) or {}).get('trailingPE'); return round(v,1) if isinstance(v,(int,float)) and 0<v<1000 else None
def rg(t):
    v=(info.get(t) or {}).get('revenueGrowth'); return v if isinstance(v,(int,float)) else None
def tg(t): return tags.get(t,{})
def zy(t):
    z=tg(t).get('zhuye',''); assert len(z)<=10, (t,z); return z
def ag(t):
    g=growth.get(t,{}).get('ai_growth','') if tg(t).get('tier') in ('AI核心','AI受益','AI应用') else ''
    assert len(g)<=20,(t,g); return g
def tier(t): return tg(t).get('tier','')
def fn(t): return fc.get(t,0) or None
def memo(s): assert len(s)<=20,s; return s
wb=openpyxl.Workbook(); wb.remove(wb.active)
# ── 封面 ──
cv=wb.create_sheet('封面'); cv.sheet_view.showGridLines=False
cv.column_dimensions['A'].width=1.83; cv.column_dimensions['B'].width=14; cv.column_dimensions['C'].width=90
put(cv,1,2,'美股跳涨与板块追踪',bold=True)
for k,(a,b) in enumerate([('类型','选股 · 活表'),('市场','美股'),('窗口','2026-08-24 至 2026-10-16, 基准为 08-21 收盘'),('负责','us'),
    ('内容','1_财报日涨跌; 2_跳涨10%以上; 3_板块持续上涨; 4_持续上涨个股'),('最后更新',str(datetime.date.today()))]):
    put(cv,3+k,2,a); put(cv,3+k,3,b)
# ── 1 财报日涨跌 ──
ev=pd.read_pickle('earn_events.pkl')
ev['o']=ev.t.map(lambda t:ORD.get(tier(t),5)); ev=ev.sort_values(['o','pct'],ascending=[True,False])
C1=[('代码',8),('公司',22),('板块',26),('主业',14),('AI关联',8),('AI带来的增速',24),('财报日',11),('时点',7),('反应日',11),('前日收盘$',10),('反应日收盘$',11),
    ('当日涨跌%',9),('现价$',9),('反应日至今%',11),('结局',13),('距52周高%',10),('总市值亿美元',12),('PE_TTM',8),('营收同比%',9),('基金加仓数',10),('备注',22)]
ws=sheet(wb,'1_财报日涨跌','美股财报日涨跌 · 2026-08-24 至 10-16 出财报 · 市值20亿美元以上',
         f'财报日取 SEC 8-K 第2.02项申报, 美东中午前申报当日反应、之后次日反应; 外国发行人用 NASDAQ 日历; 收盘价 yfinance, 现价 10-16; 共 {len(ev)} 次财报 {ev.t.nunique()} 家',
         [(c,0) for c,_ in C1],[w for _,w in C1])
put(ws,2,17,'跌幅标准'); put(ws,2,18,-0.03,'pct',fill=YEL); put(ws,2,19,'涨幅标准'); put(ws,2,20,0.03,'pct',fill=YEL)
r=5
for x in ev.itertuples():
    t=x.t; rd=str(x.rday.date())
    vals=[t,nm(t),ind(t),zy(t),tier(t),ag(t),x.edate,x.session,rd]
    for j,v in enumerate(vals): put(ws,r,2+j,v)
    put(ws,r,11,round(x.pc,2),'px'); put(ws,r,12,round(x.c,2),'px'); put(ws,r,13,f'=L{r}/K{r}-1','pct')
    put(ws,r,14,round(x.now,2),'px'); put(ws,r,15,f'=N{r}/L{r}-1','pct')
    put(ws,r,16,f'=IF(J{r}>="2026-10-15","待观察",IF(AND(O{r}>$T$2,M{r}>$R$2),"守住，续涨",IF(AND(O{r}<$R$2,M{r}>$T$2),"当日上涨，回吐",IF(AND(O{r}>$T$2,M{r}<$R$2),"当日下跌，反涨",IF(O{r}<$R$2,"下跌","持平")))))')
    put(ws,r,17,f'=N{r}/{round(x.hi52,2)}-1','pct'); put(ws,r,18,mc(t),'int'); put(ws,r,19,pe(t),'pe'); put(ws,r,20,rg(t),'pct'); put(ws,r,21,fn(t),'int')
    m=[]; 
    if x.chk: m.append(x.chk)
    if growth.get(t,{}).get('confidence')=='low' and ag(t) and ag(t)!='未拆分': m.append('AI增速未核到一手')
    put(ws,r,22,memo('; '.join(m)),gray=True); r+=1
for c in (13,15,17,20): scale(ws,c,5,r-1)
ws.auto_filter.ref=f'B4:V{r-1}'; R1=r
g=ev.assign(ai=ev.t.map(lambda t:tier(t).startswith('AI')))
A,N=g[g.ai],g[~g.ai]
fade=[t for t in A[(A.pct>0.03)&(A.since<-0.03)].sort_values('mc' if 'mc' in A else 'pct',ascending=False).t]
hold=[t for t in A[(A.pct>0.03)&(A.since>0.03)&(A.rday<'2026-10-15')].sort_values('pct',ascending=False).t]
notes(ws,r+1,['Claude分析意见',
 f'AI相关 {len(A)} 次财报当日中位 {A.pct.median():+.1%}, 上涨占比 {(A.pct>0).mean():.0%}; 非AI {len(N)} 次中位 {N.pct.median():+.1%}; 反应日至今 AI 中位 {A.since.median():+.1%}, 财报日的超额没有延续。',
 f'AI 当日涨3%以上随后回吐3%以上的: {", ".join(fade[:10])}; 当日涨后守住并续涨的: {", ".join(hold[:10]) or "无"}。',
 '方法: 反应日由 8-K 第2.02项申报的美东时间推得, 稿件盘前发而 8-K 盘中补交的按当日; 外国发行人无 8-K, 按 NASDAQ 日历当日, 可能差一天。',
 '拐点观察: 下一批 AI 硬件财报若当日上涨且一周内不回吐, 才说明硬件端的卖压出清。'])
# ── 2 跳涨 ──
jp=pd.read_pickle('jumps.pkl'); jp=jp[~jp.glitch].copy()
er={(e.t,str(e.rday.date())) for e in ev.itertuples()}
jp['earn']=jp.apply(lambda x:'是' if (x.t,x.date) in er else '否',axis=1)
jp['o']=jp.t.map(lambda t:ORD.get(tier(t),5)); jp=jp.sort_values(['o','date','pct'],ascending=[True,False,False])
C2=[('跳涨日',11),('代码',8),('公司',22),('板块',26),('主业',14),('AI关联',8),('AI带来的增速',24),('财报',6),('前日收盘$',10),('跳涨日收盘$',11),('当日涨跌%',9),
    ('量比',7),('此前1月%',9),('跳涨后至今%',11),('现价$',9),('距52周高%',10),('总市值亿美元',12),('PE_TTM',8),('基金加仓数',10),('备注',22)]
ws=sheet(wb,'2_跳涨10%以上','美股跳涨 · 单日收盘涨10%以上 · 2026-08-24 至 10-16 · 市值20亿美元以上',
         f'宇宙 {len(uni)} 只(NASDAQ+NYSE+AMEX, 市值20亿美元以上且股价5美元以上); 收盘对收盘, 已剔除次日全回吐且不放量的数据错; 量比为当日量除以前20日均量; 共 {len(jp)} 次 {jp.t.nunique()} 只',
         [(c,0) for c,_ in C2],[w for _,w in C2])
put(ws,2,20,'跳涨门槛'); put(ws,2,21,0.10,'pct',fill=YEL)
r=5
for x in jp.itertuples():
    t=x.t
    for j,v in enumerate([x.date,t,nm(t),ind(t),zy(t),tier(t),ag(t),x.earn]): put(ws,r,2+j,v)
    put(ws,r,10,round(x.pc,2),'px'); put(ws,r,11,round(x.c,2),'px'); put(ws,r,12,x.pct,'pct'); put(ws,r,13,round(x.vr,1) if x.vr==x.vr else None,'x')
    put(ws,r,14,x.pre1m,'pct'); put(ws,r,15,x.since,'pct'); put(ws,r,16,round(x.now,2),'px'); put(ws,r,17,x.now/x.hi52-1,'pct')
    put(ws,r,18,mc(t),'int'); put(ws,r,19,pe(t),'pe'); put(ws,r,20,fn(t),'int')
    m=[]
    if growth.get(t,{}).get('confidence')=='low' and ag(t) and ag(t)!='未拆分': m.append('AI增速未核到一手')
    put(ws,r,21,memo('; '.join(m)),gray=True); r+=1
for c in (12,14,15,17): scale(ws,c,5,r-1)
ws.auto_filter.ref=f'B4:U{r-1}'; R2=r
j=jp.assign(ai=jp.t.map(lambda t:tier(t).startswith('AI')),mon=jp.date.str[:7])
E,NE=j[j.earn=='是'],j[j.earn=='否']; m9,m10=j[j.mon=='2026-09'],j[j.mon=='2026-10']
notes(ws,r+1,['Claude分析意见',
 f'共 {len(j)} 次跳涨, 至今仍高于跳涨日收盘的只有 {(j.since>0).mean():.0%}, 跳涨后至今中位 {j.since.median():+.1%}; AI 相关 {j.ai.sum()} 次, 留存率 {(j[j.ai].since>0).mean():.0%}。',
 f'财报驱动的 {len(E)} 次留存 {(E.since>0).mean():.0%}、中位 {E.since.median():+.1%}; 非财报的 {len(NE)} 次留存 {(NE.since>0).mean():.0%}、中位 {NE.since.median():+.1%}, 有业绩事件的跳涨更扛得住。',
 f'9 月 {len(m9)} 次跳涨里 AI 占 {m9.ai.mean():.0%}, 10 月降到 {len(m10)} 次且 AI 只占 {m10.ai.mean():.0%}, AI 跳涨潮在退。',
 '方法: 收盘对收盘, 已剔除拆股; 量比低于1.5倍且次日全回吐的视为数据错剔除。',
 '拐点观察: AI 跳涨次数重新回升且留存率回到三成以上, 才算 AI 情绪修复。'])
# ── 3 板块 ──
es=pd.read_pickle('etf_stats.pkl'); ins=pd.read_pickle('industry_stats.pkl')
spy=float(es.set_index('t').loc['SPY','win'])
rows=[]
for x in es.itertuples():
    rows.append(dict(typ='主题ETF',name=x.name,code=x.t,n=None,win=x.win,med=None,ex=x.win-spy,m1=x.m1,m3=x.m3,up=None,wk=x.wk_up,dd=x.dd,off=x.off_hi,top=''))
for x in ins.itertuples():
    rows.append(dict(typ='行业',name=x.ind,code='',n=x.n,win=x.win_cw,med=x.win_med,ex=x.win_cw-spy,m1=x.m1_med,m3=x.m3_med,up=x.up,wk=x.wk_up,dd=x.dd,off=x.off_hi,top=x.top))
sd=pd.DataFrame(rows)
sd['hit']=np.where((sd.ex>=0.03)&(sd.wk>=0.625)&(sd.dd>-0.10),'是','否')
sd=sd.sort_values(['hit','win'],ascending=[False,False])
C3=[('类型',8),('板块',36),('代码',7),('家数',6),('窗口涨幅%',10),('个股中位%',10),('超额SPY',9),('近1月%',8),('近3月%',8),('上涨家数占比',12),('周线上涨占比',12),('窗口最大回撤',12),('距窗口高点%',11),('持续上涨',8),('领涨个股',22),('备注',22)]
ws=sheet(wb,'3_板块持续上涨','美股板块持续上涨 · 2026-08-21 收盘至 10-16 · 主题ETF与行业',
         f'行业为宇宙内 yfinance 行业的市值加权组合, 3家以上才列; 周线上涨占比为8个周五中周涨的比例; 持续上涨=超额SPY 3%以上且周涨5周以上且最大回撤小于10%; 同期SPY {spy:.1%}',
         [(c,0) for c,_ in C3],[w for _,w in C3])
r=5
for x in sd.itertuples():
    for j,(v,k) in enumerate([(x.typ,'text'),(x.name,'text'),(x.code,'text'),(x.n,'int'),(x.win,'pct'),(x.med,'pct'),(x.ex,'pct'),(x.m1,'pct'),(x.m3,'pct'),
                              (x.up,'pct'),(x.wk,'pct'),(x.dd,'pct'),(x.off,'pct'),(x.hit,'text'),(x.top,'text')]): put(ws,r,2+j,v,k)
    put(ws,r,17,'',gray=True); r+=1
for c in (6,7,8,9,10,13,14): scale(ws,c,5,r-1)
ws.auto_filter.ref=f'B4:Q{r-1}'; R3=r
stx=pd.read_pickle('stock_stats.pkl'); hit=sd[sd.hit=='是']
smh=es.set_index('t').loc['SMH']
notes(ws,r+1,['Claude分析意见',
 f'同期 SPY {spy:+.1%}, 宇宙个股中位 {stx.win.median():+.1%}, 只有 {(stx.win>0).mean():.0%} 上涨: 窄幅且偏防御的市场。',
 f'持续上涨的 {len(hit)} 个: {"、".join(hit.name.head(12))}; 跌得最深的主题ETF: {"、".join(es.sort_values("win").name.head(8))}。',
 '科技里持续走强的只有软件基础设施与网安, AI 资金在从硬件往软件和安全迁移。',
 '方法: 行业为 yfinance 行业的市值加权组合, 少于3家不列; 主题ETF用其自身净值。',
 f'拐点观察: SMH 距窗口高点 {smh.off_hi:.1%}, 收复高点之前不把半导体当作重新领涨。'])
# ── 4 持续上涨个股 ──
st=pd.read_pickle('stock_stats.pkl'); st=st[st.win>=0.10].copy()
st['o']=st.t.map(lambda t:ORD.get(tier(t),5)); st=st.sort_values(['o','win'],ascending=[True,False])
C4=[('代码',8),('公司',22),('板块',26),('主业',14),('AI关联',8),('AI带来的增速',24),('窗口涨幅%',10),('近1月%',8),('近3月%',8),('周线上涨占比',12),('窗口最大回撤',12),
    ('最大单日涨幅',12),('跳涨天数',8),('距52周高%',10),('现价$',9),('总市值亿美元',12),('PE_TTM',8),('营收同比%',9),('基金加仓数',10),('备注',22)]
ws=sheet(wb,'4_持续上涨个股','美股持续上涨个股 · 2026-08-21 收盘至 10-16 涨10%以上 · 市值20亿美元以上',
         f'窗口涨幅以 08-21 收盘为基准; 跳涨天数为窗口内单日涨10%以上的天数, 0 表示是一路涨上来的; 共 {len(st)} 只, 占宇宙 {len(st)/len(uni):.1%}',
         [(c,0) for c,_ in C4],[w for _,w in C4])
r=5
for x in st.itertuples():
    t=x.t
    for j,v in enumerate([t,nm(t),ind(t),zy(t),tier(t),ag(t)]): put(ws,r,2+j,v)
    for j,(v,k) in enumerate([(x.win,'pct'),(x.m1,'pct'),(x.m3,'pct'),(x.wk_up,'pct'),(x.dd,'pct'),(x.maxday,'pct'),(x.n10,'int'),(x.now/x.hi52-1,'pct'),
                              (round(x.now,2),'px'),(mc(t),'int'),(pe(t),'pe'),(rg(t),'pct'),(fn(t),'int')]): put(ws,r,8+j,v,k)
    m=[]
    if growth.get(t,{}).get('confidence')=='low' and ag(t) and ag(t)!='未拆分': m.append('AI增速未核到一手')
    put(ws,r,21,memo('; '.join(m)),gray=True); r+=1
for c in (8,9,10,12,13,15,19): scale(ws,c,5,r-1)
ws.auto_filter.ref=f'B4:U{r-1}'; R4=r
tc=st.t.map(tier).value_counts()
ai_n=int(sum(tc.get(k,0) for k in ('AI核心','AI受益','AI应用')))
notes(ws,r+1,['Claude分析意见',
 f'{len(st)} 只里非科技 {tc.get("非科技",0)} 只, AI 相关 {ai_n} 只(核心 {tc.get("AI核心",0)}、受益 {tc.get("AI受益",0)}、应用 {tc.get("AI应用",0)}), AI 相关几乎全是软件、安全与平台, 芯片硬件很少。',
 f'{(st.n10==0).mean():.0%} 没有一天涨过10%, 是一路涨上来的, 和跳涨名单重合少: 跳涨追不到这一类。',
 '方法: 周线上涨占比为 8 个周五里周涨的比例; 最大回撤按窗口内收盘计。',
 '拐点观察: 若软件安全这批的周线上涨占比跌破一半, 说明这轮从硬件到软件的迁移也到头了。'])
json.dump(dict(R1=R1,R2=R2,R3=R3,R4=R4),open('build_rows.json','w'))
if os.path.exists(OUT) and datetime.date.fromtimestamp(os.path.getmtime(OUT))<datetime.date.today():   # 当天反复构建不归档, 隔天更新才归档旧版
    ad=os.path.join(os.path.dirname(OUT),'_归档_底稿与旧版'); os.makedirs(ad,exist_ok=True)
    shutil.move(OUT,os.path.join(ad,os.path.basename(OUT).replace('.xlsx',datetime.datetime.now().strftime('_%Y%m%d%H%M.xlsx'))))
wb.save(OUT); print('写入',OUT,dict(R1=R1-5,R2=R2-5,R3=R3-5,R4=R4-5))
