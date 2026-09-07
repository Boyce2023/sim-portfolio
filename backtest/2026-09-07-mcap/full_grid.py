#!/opt/homebrew/bin/python3
"""首板后10日最大涨幅 完整分布表 — 不压缩不合并, 红绿双向配色
纵: 市值10亿一档 10-20 到 290-300 | 横: 涨幅10%一级 0-10 到 90-100, 另加 ≤0 与 100%+
⭐配色: 相对全样本基准的偏离。绿=该市值档在此涨幅区间比全市场更集中, 红=更稀疏。
"""
import json,statistics as st
rows=[r for r in json.load(open('/tmp/grid_v3.json')) if r['first']]
CSS=open('/Users/huaichuaibeimeng/.claude/standards/buwen.css').read()
MB=[(i,i+10) for i in range(10,300,10)]
UB=[(-999,0,'≤0')]+[(i,i+10,f'{i}-{i+10}') for i in range(0,100,10)]+[(100,99999,'100+')]
def sel(data,a,b): return [r for r in data if (r['maxup10']<=0 if b==0 else a<r['maxup10']<=b)]
COLAVG=[len(sel(rows,a,b))/len(rows)*100 for a,b,_ in UB]

def pct_cell(c,g,base):
    if not g: return '<td class="na"></td>'
    p=len(c)/len(g)*100
    if p<0.05: return '<td class="z"></td>'
    r=(p-base)/base if base else 0
    if r>=0.12:  t=min(1,(r-0.12)/0.55); bg=f'rgba(46,125,70,{0.16+t*0.55:.2f})'
    elif r<=-0.12: t=min(1,(-r-0.12)/0.55); bg=f'rgba(192,57,43,{0.16+t*0.5:.2f})'
    else: bg='#F4F6F7'
    return f'<td style="background:{bg}" title="{len(c)}笔 · 全样本基准{base:.1f}%">{p:.1f}</td>'
def n_cell(c,g,base):
    if not g: return '<td class="na"></td>'
    if not c: return '<td class="z"></td>'
    return f'<td>{len(c)}</td>'

def build(title,sub,fn,legend):
    h=f'<h3>{title}</h3><div class="doc-sub">{sub}</div><div style="overflow-x:auto"><table><tr><th>流通市值</th>'
    h+=''.join(f'<th>{l}</th>' for _,_,l in UB)+'<th>样本</th><th>中位</th><th>均值</th></tr>'
    for lo,hi in MB:
        g=[r for r in rows if lo<=r['mcap']<hi]
        if not g:
            h+=f'<tr><td class="mo">{lo}-{hi}亿</td>'+'<td class="na"></td>'*(len(UB)+3)+'</tr>'; continue
        h+=f'<tr><td class="mo">{lo}-{hi}亿</td>'
        for i,(a,b,_) in enumerate(UB): h+=fn(sel(g,a,b),g,COLAVG[i])
        u=[r['maxup10'] for r in g]
        h+=f'<td class="tot">{len(g)}</td><td class="tot">{st.median(u):+.1f}</td><td class="tot">{st.mean(u):+.1f}</td></tr>'
    h+='<tr class="sum"><td class="mo"><b>全样本</b></td>'
    for i,(a,b,_) in enumerate(UB):
        c=sel(rows,a,b)
        h+=f'<td>{len(c)/len(rows)*100:.1f}</td>' if fn is pct_cell else f'<td>{len(c)}</td>'
    u=[r['maxup10'] for r in rows]
    h+=f'<td>{len(rows)}</td><td>{st.median(u):+.1f}</td><td>{st.mean(u):+.1f}</td></tr>'
    return h+f'</table></div><div class="lg">{legend}</div>'

doc=f'''<!doctype html><html><head><meta charset="utf-8"><title>首板后10日涨幅完整分布</title><style>{CSS}
table{{border-collapse:collapse;font-size:9px}}
th{{background:#1B3A5B;color:#fff;padding:4px 3px;font-size:8.5px;white-space:nowrap}}
td{{border:1px solid #E9ECEF;padding:2px 3px;text-align:center;white-space:nowrap;min-width:34px}}
.mo{{background:#F5F8FB;text-align:right;padding-right:6px;font-weight:600;color:#1B3A5B;min-width:62px}}
.tot{{background:#EFF3F6;color:#444}} .na{{background:#FCFCFC}} .z{{background:#FDFDFD;color:#ddd}}
.sum td{{border-top:2px solid #1B3A5B;background:#E3EBF2;font-weight:700}}
.sum .mo{{background:#1B3A5B;color:#fff}}
.lg{{font-size:9.5px;color:#666;margin:6px 0 22px}}
.box{{background:#F5F8FB;border-left:3px solid #1B3A5B;padding:9px 13px;margin:11px 0;font-size:10.5px}}
</style></head><body><div class="container">
<h1>首板后10个交易日最大涨幅 · 完整分布</h1>
<div class="doc-sub">2025-01 至 2026-09 · 首板样本 {len(rows)} 个 · 涨幅从首板收盘价算起, 取后续10个交易日内的最高价 · Claude分析意见</div><hr class="rule-navy">
<div class="box">纵轴每10亿一档从10亿到300亿, 横轴每10%一级从0到100%, 未做任何合并。<br>
表一格子里是<b>占该市值档的百分比</b>(每行横向加总100)。表二是<b>原始笔数</b>, 用来判断哪些格子样本够不够。</div>
{build("表一 · 占比%","例如'150-160亿'行的'20-30'列 = 该市值档里有百分之多少的首板在后10日最高涨了20%到30%",pct_cell,
 "⭐颜色是<b>相对全样本的偏离</b>: <b style='color:#2E7D46'>绿</b>=该市值档在这个涨幅区间比全市场更集中, <b style='color:#C0392B'>红</b>=更稀疏, 灰=接近平均。悬停看笔数与全样本基准。")}
{build("表二 · 笔数","同样的格子, 显示原始样本数",n_cell,"空白=0笔。200亿以上多数档只剩几十到一百多笔, 那些行的百分比要打折看。")}
</div></body></html>'''
open('output/表3_首板后涨幅完整分布.html','w').write(doc)
print('ok')
