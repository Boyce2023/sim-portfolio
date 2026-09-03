#!/opt/homebrew/bin/python3
"""四档规模指数标准化图. 用法: size_index_chart.py START END 输出html [标题]. 数据源腾讯行情(直连,勿走代理)."""
import sys, os, requests
for k in ('HTTPS_PROXY','HTTP_PROXY','https_proxy','http_proxy','ALL_PROXY'): os.environ.pop(k,None)
START,END,OUT=sys.argv[1],sys.argv[2],sys.argv[3]; TITLE=sys.argv[4] if len(sys.argv)>4 else 'A股大中小微盘标准化走势'
CSS=open('/Users/huaichuaibeimeng/.claude/standards/buwen.css').read()
idx=[('沪深300 (大盘)','sh000300','#12233D',''),('中证500 (中盘)','sh000905','#1B3A5B','6,3'),('中证1000 (小盘)','sh000852','#4E7CA0',''),('国证2000 (微盘)','sz399303','#9DB4C8','')]
series=[]
for n,c,col,dash in idx:
    rows=requests.get(f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={c},day,{START},{END},120,",timeout=10).json()['data'][c]['day']
    cl=[(r[0],float(r[2])) for r in rows if START<=r[0]<=END]; base=cl[0][1]
    series.append((n,col,dash,[(d,v/base*100) for d,v in cl]))
dates=[d for d,_ in series[0][3]]
W,H,L,R,T,B=1000,420,52,40,20,44
allv=[v for s in series for _,v in s[3]]; ymin=int(min(allv)//2*2)-2; ymax=int(max(allv)//2*2)+4
x=lambda i: L+(W-L-R)*i/(len(dates)-1); y=lambda v: T+(H-T-B)*(ymax-v)/(ymax-ymin)
g=[f'<svg viewBox="0 0 {W} {H}" width="100%" style="font-family:Arial,\'Microsoft YaHei\',sans-serif;background:#fff">']
for gv in range(ymin,ymax+1,2):
    g.append(f'<line x1="{L}" y1="{y(gv):.1f}" x2="{W-R}" y2="{y(gv):.1f}" stroke="{"#1B3A5B" if gv==100 else "#E6E9ED"}" stroke-width="{1.2 if gv==100 else .8}"/><text x="{L-6}" y="{y(gv)+3.5:.1f}" font-size="9.5" fill="#8A857C" text-anchor="end">{gv}</text>')
step=max(1,len(dates)//10)
for i,d in enumerate(dates):
    if i%step==0 or i==len(dates)-1:
        g.append(f'<line x1="{x(i):.1f}" y1="{T}" x2="{x(i):.1f}" y2="{H-B}" stroke="#E6E9ED" stroke-width=".8"/><text x="{x(i):.1f}" y="{H-B+14}" font-size="9.5" fill="#8A857C" text-anchor="middle">{d[5:]}</text>')
for n,col,dash,pts in series:
    path=' '.join(f'{"M" if i==0 else "L"}{x(i):.1f},{y(v):.1f}' for i,(_,v) in enumerate(pts))
    g.append(f'<path d="{path}" fill="none" stroke="{col}" stroke-width="2"{" stroke-dasharray="+chr(34)+dash+chr(34) if dash else ""}/>')
# 图例(左上)
g.append('<rect x="64" y="26" width="210" height="72" fill="#fff" stroke="#D8DEE6"/>')
for i,(n,col,dash,pts) in enumerate(series):
    yy=40+i*16; g.append(f'<line x1="72" y1="{yy}" x2="96" y2="{yy}" stroke="{col}" stroke-width="2"{" stroke-dasharray="+chr(34)+dash+chr(34) if dash else ""}/><text x="102" y="{yy+3.5}" font-size="10" font-weight="700" fill="{col}">{n} {pts[-1][1]-100:+.1f}%</text>')
g.append('</svg>')
f=lambda v: f'<span style="color:{"#C0392B" if v<0 else "#2E7D46"}">{v:+.1%}</span>'
tr=''.join(f'<tr><td><b>{n}</b></td><td>{f(pts[-1][1]/100-1)}</td><td>{max(pts,key=lambda p:p[1])[1]-100:+.1f}% ({max(pts,key=lambda p:p[1])[0][5:]})</td><td>{min(pts,key=lambda p:p[1])[1]-100:+.1f}% ({min(pts,key=lambda p:p[1])[0][5:]})</td><td>{pts[-1][1]/max(p[1] for p in pts)-1:+.1%}</td></tr>' for n,_,_,pts in series)
doc=f'''<!doctype html><html><head><meta charset="utf-8"><title>{TITLE}</title><style>{CSS}</style></head><body><div class="container">
<h1>{TITLE}</h1><div class="doc-sub">{START} = 100 · 收盘价 · 数据源: 腾讯行情(web.ifzq.gtimg.cn) · 生成 {END} · Claude分析意见</div><hr class="rule-navy">
<h2>图 四档规模指数标准化({START[5:]}=100)</h2>{''.join(g)}
<h2>表 区间统计</h2><table><tr><th>指数</th><th>区间累计</th><th>区间最高(日期)</th><th>区间最低(日期)</th><th>现距区间高点</th></tr>{tr}</table>
</div></body></html>'''
open(OUT,'w').write(doc); print('ok',OUT,len(dates),'days')
