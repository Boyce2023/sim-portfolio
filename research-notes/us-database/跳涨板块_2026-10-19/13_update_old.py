"""更新 Track/1_活表/1选股_基金加仓追踪.xlsx (只改值不改样式; 改前整本复制进 _归档_底稿与旧版 带时间戳)
Sheet1: 补'这家做什么'空白与占位, 补 此前1月%/此后1月% 空白, 刷 现价$/市值$B, 口径行窗口改到最新
Sheet2: 按 2026Q2 对 Q1 重算(市值口径, 校正拆股与CUSIP变更, 补 Baron/Viking/Janus/Pershing/ValueAct/Greenhaven)
Sheet3: 用本地日线刷 现价/各期涨幅/超额/命中"""
import json, sys, os, glob, shutil, datetime, pandas as pd, numpy as np, openpyxl
from openpyxl.styles import Font, Alignment
SRC=sorted(glob.glob(os.path.expanduser('~/Desktop/Track/*/*基金加仓追踪*.xlsx'))); assert len(SRC)==1,SRC; SRC=SRC[0]
OUT=sys.argv[1] if len(sys.argv)>1 else SRC
px=pd.read_pickle('px.pkl'); uni={u['t']:u for u in json.load(open('universe.json'))}; info=json.load(open('info.json'))
tags=json.load(open('tags.json')); cache=json.load(open('desc_cache.json'))
extra=json.load(open('tags_extra.json')) if os.path.exists('tags_extra.json') else {}
st=pd.read_pickle('stock_stats.pkl').set_index('t')
LAST=px.index[-1]; FONT='等线'
FMT={'1dp':'_(* #,##0.0_);_(* \\(#,##0.0\\);_(* "-"??_);_(@_)','pct1':'0.0%','usd':'_("$"* #,##0.00_);_("$"* \\(#,##0.00\\);_("$"* "-"??_);_(@_)','text':'@','int':'_(* #,##0_);_(* \\(#,##0\\);_(* "-"??_);_(@_)'}
def put(ws,r,c,v,key='text'):
    x=ws.cell(r,c,v); x.font=Font(name=FONT,size=11); x.number_format=FMT[key]
    x.alignment=Alignment(horizontal="right" if key!='text' else "left",vertical="top")
def what(t): return (tags.get(t) or extra.get(t) or {}).get('what') or (cache.get(t) or {}).get('what')
wb=openpyxl.load_workbook(SRC)
H1=['跳涨日','代码','公司','板块','前日收盘$','跳涨日收盘$','当日涨跌%','现价$','市值$B','此前1月%','此后1月%','这家做什么']
ws=wb['1_跳涨10%以上']; assert [ws.cell(4,c).value for c in range(1,13)]==H1
n=dict(desc=0,pre=0,post=0,px=0)
for r in range(5,ws.max_row+1):
    d,t=ws.cell(r,1).value,ws.cell(r,2).value
    if not d or not t: continue
    t=str(t).replace('.','-'); L=ws.cell(r,12).value
    if (not L or '待写' in str(L)) and what(t): put(ws,r,12,what(t)); n['desc']+=1
    if t in px.columns:
        s=px[t].dropna(); dd=pd.Timestamp(str(d)[:10])
        if dd in s.index:
            i=s.index.get_loc(dd)
            if ws.cell(r,10).value is None and i>=22: put(ws,r,10,float(s.iloc[i-1]/s.iloc[i-22]-1),'pct1'); n['pre']+=1
            if ws.cell(r,11).value is None and i+21<len(s): put(ws,r,11,float(s.iloc[i+21]/s.iloc[i]-1),'pct1'); n['post']+=1
        put(ws,r,8,round(float(s.iloc[-1]),2),'usd'); n['px']+=1
        if t in uni: put(ws,r,9,round(uni[t]['mc_b'],1),'1dp')
a=ws.cell(2,1).value or ''
import re
ws.cell(2,1).value=re.sub(r'窗口 [0-9-]+~[0-9-]+',f'窗口 2026-02-02~{LAST.date()}',a)
t1=ws.cell(1,1).value or ''; ws.cell(1,1).value=t1.split('· 更新至')[0].rstrip()+f'· 更新至 {LAST.date()}'
print('sheet1',n)
# ── Sheet2 ──
H2=['代码','公司','板块','现价$','市值$B','近1月%','净利率%','年营收$M','新建仓基金','加仓基金','这家做什么']
ws2=wb['2_基金新建加仓']; assert [ws2.cell(4,c).value for c in range(1,12)]==H2
FR=json.load(open('fund_rows.json')); F=json.load(open('funds_13f_full.json'))
keep=[o for o in FR if o['n']>=2 or o['wmax']>=0.01]
keep.sort(key=lambda o:(-o['n'],-o['wmax']))
if ws2.max_row>=5: ws2.delete_rows(5,ws2.max_row-4)
nf=sum(1 for f in F if f.get('moves'))
ws2.cell(1,1).value=f'Long-only/Long-bias 基金 · 最近一期13F 新建仓与加仓≥20% · 更新至 {datetime.date.today()}'
ws2.cell(2,1).value=(f'{nf}家基金(SEC EDGAR 13F-HR, 2026Q2对Q1; 名单内尚无一家报出Q3, 截止11-14) | 加仓按市值除以季末收盘折股, 已校正拆股与CUSIP变更 | '
                     f'只列被2家以上新建或加仓, 或1家但占其组合1%以上 | Janus 与 Pershing 本期换了申报主体; 分拆新股(FDXF, HONA 等)的新建是被动分得 | 按被提及基金数排序')
for k,o in enumerate(keep):
    r=5+k; t=o['t']; i=info.get(t) or {}; u=uni.get(t,{})
    put(ws2,r,1,t); put(ws2,r,2,(i.get('longName') or i.get('shortName') or u.get('name') or t)[:40]); put(ws2,r,3,i.get('sector') or u.get('sector') or '')
    put(ws2,r,4,round(float(px[t].dropna().iloc[-1]),2) if t in px.columns else None,'usd'); put(ws2,r,5,round(u['mc_b'],1) if u else None,'1dp')
    put(ws2,r,6,float(st.loc[t,'m1']) if t in st.index else None,'pct1')
    pm=i.get('profitMargins'); put(ws2,r,7,pm if isinstance(pm,(int,float)) else None,'pct1')
    tr=i.get('totalRevenue'); put(ws2,r,8,round(tr/1e6,1) if isinstance(tr,(int,float)) else None,'1dp')
    put(ws2,r,9,o['new']); put(ws2,r,10,o['add']); put(ws2,r,11,what(t))
ws2.auto_filter.ref=f'A4:K{4+len(keep)}'
print('sheet2 行',len(keep),'缺介绍',sum(1 for o in keep if not what(o['t'])))
# ── Sheet3 ──
H3=['ETF','板块','现价$','24月%','12月%','3月%','1月%','12月超额pp','24月超额pp','命中','说明']
ws3=wb['3_沉寂后启动板块']; assert [ws3.cell(4,c).value for c in range(1,12)]==H3
etfs=[ws3.cell(r,1).value for r in range(5,ws3.max_row+1) if ws3.cell(r,1).value]
p3=pd.read_pickle('px3y.pkl') if os.path.exists('px3y.pkl') else None
if p3 is not None:
    def rr(s,n): return float(s.iloc[-1]/s.iloc[-n]-1) if len(s)>=n else None
    sp=p3['SPY'].dropna(); s24,s12,s1=rr(sp,505),rr(sp,253),rr(sp,22); hits=0
    for r in range(5,ws3.max_row+1):
        e=ws3.cell(r,1).value
        if not e or e not in p3.columns: continue
        s=p3[e].dropna()
        if len(s)<253: continue
        r24,r12,r3,r1=rr(s,505),rr(s,253),rr(s,64),rr(s,22)
        u12=(r12-s12)*100; u24=(r24-s24)*100 if r24 is not None else None; hit=u12<0 and (r1-s1)*100>5
        put(ws3,r,3,round(float(s.iloc[-1]),2),'usd'); put(ws3,r,4,r24,'pct1'); put(ws3,r,5,r12,'pct1'); put(ws3,r,6,r3,'pct1'); put(ws3,r,7,r1,'pct1')
        put(ws3,r,8,round(u12,1),'1dp'); put(ws3,r,9,round(u24,1) if u24 is not None else None,'1dp'); put(ws3,r,10,'⭐命中' if hit else ''); hits+=hit
    t3=ws3.cell(1,1).value or ''; ws3.cell(1,1).value=t3.split('· 更新至')[0].rstrip()+f'· 更新至 {p3.index[-1].date()}'
    print('sheet3 命中',hits)
if OUT==SRC:
    ad=os.path.join(os.path.dirname(SRC),'_归档_底稿与旧版'); os.makedirs(ad,exist_ok=True)
    shutil.copy2(SRC,os.path.join(ad,os.path.basename(SRC).replace('.xlsx',datetime.datetime.now().strftime('_%Y%m%d%H%M.xlsx'))))
wb.save(OUT); print('写入',OUT)
