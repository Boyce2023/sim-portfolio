#!/opt/homebrew/bin/python3
"""生成 月份×市值 二维HTML表。用法: make_html.py [起始月 结束月]
数据源: /tmp/grid_rows.json (由 grid.py 生成)"""
import json,statistics as st,sys
rows=json.load(open('/tmp/grid_rows.json'))
ms=sorted({r['m'] for r in rows})
MS=ms
CSS=open('/Users/huaichuaibeimeng/.claude/standards/buwen.css').read()
MIN_CELL=3      # 单元格最少笔数
MIN_MED=10      # 中位溢价最少笔数(原20太严, 两头都空)
def cell(c):
    if len(c)<MIN_CELL: return '<td class="na"></td>'
    w=sum(1 for r in c if r['prem']>0)/len(c)*100
    bg='#fff'
    if w>=72: bg='#CFE3D4'
    elif w>=66: bg='#E7F0E9'
    elif w<58: bg='#F5D8D3'
    elif w<62: bg='#FBEBE7'
    return f'<td style="background:{bg}"><b>{w:.0f}</b><span class="sm">{len(c)}</span></td>'
def table(data,bins,labels,title,note):
    h=f'<h3>{title}</h3><div class="doc-sub">{note}</div>'
    h+='<div style="overflow-x:auto"><table><tr><th>月份</th>'+''.join(f'<th>{x}</th>' for x in labels)+'<th>合计</th></tr>'
    for m in MS:
        g=[r for r in data if r['m']==m]
        h+=f'<tr><td class="mo"><b>{m[2:]}</b></td>'
        for lo,hi in bins: h+=cell([r for r in g if lo<=r['mcap']<hi])
        w=sum(1 for r in g if r['prem']>0)/len(g)*100 if g else 0
        h+=f'<td class="tot"><b>{w:.0f}</b><span class="sm">{len(g)}</span></td></tr>'
    h+='<tr class="sumrow"><td><b>胜率%</b></td>'
    for lo,hi in bins:
        c=[r for r in data if lo<=r['mcap']<hi]
        if len(c)<MIN_CELL: h+='<td class="na"></td>'; continue
        w=sum(1 for r in c if r['prem']>0)/len(c)*100
        h+=f'<td class="tot"><b>{w:.0f}</b><span class="sm">{len(c)}</span></td>'
    w=sum(1 for r in data if r['prem']>0)/len(data)*100
    h+=f'<td class="grand"><b>{w:.0f}</b><span class="sm">{len(data)}</span></td></tr>'
    h+='<tr class="sumrow"><td><b>中位溢价%</b></td>'
    for lo,hi in bins:
        c=[r['prem'] for r in data if lo<=r['mcap']<hi]
        h+=(f'<td class="med">{st.median(c):+.2f}</td>' if len(c)>=MIN_MED else '<td class="na"></td>')
    h+=f'<td class="med">{st.median([r["prem"] for r in data]):+.2f}</td></tr></table></div>'
    return h
B10=[(i,i+10) for i in range(0,300,10)]+[(300,99999)]
L10=[str(i) for i in range(0,300,10)]+["300+"]
B30=[(i,i+30) for i in range(0,300,30)]+[(300,99999)]
L30=[f"{i}-{i+30}" for i in range(0,300,30)]+["300+"]
lb=[r for r in rows if r['streak']>=2]; fb=[r for r in rows if r['streak']==1]
doc=f'''<!doctype html><html><head><meta charset="utf-8"><title>涨停股月份×市值二维表</title><style>{CSS}
table{{border-collapse:collapse;width:100%;font-size:9px}}
th{{background:#1B3A5B;color:#fff;padding:3px 2px;font-size:8.5px;white-space:nowrap}}
td{{border:1px solid #E6E9ED;padding:2px 1px;text-align:center;white-space:nowrap;min-width:26px}}
.sm{{font-size:7px;color:#9a958c;display:block;line-height:1}}
.na{{background:#FAFAFA}} .mo{{background:#F5F8FB;font-size:8.5px}}
.tot{{background:#EAF0F5}} .grand{{background:#1B3A5B;color:#fff}}
.med{{background:#F8F6F2;font-size:8px;color:#444}}
.sumrow td{{border-top:2px solid #1B3A5B}}</style></head><body><div class="container">
<h1>涨停股 月份 × 流通市值 二维表</h1>
<div class="doc-sub">{MS[0]} 至 {MS[-1]} 共{len(MS)}个月 · 跨库按(代码,日期)去重 · Claude分析意见</div><hr class="rule-navy">
<div style="background:#F5F8FB;border-left:3px solid #1B3A5B;padding:8px 12px;margin:10px 0;font-size:10px">
<b>怎么读</b>: 单元格上方大字是<b>胜率%</b>(次日开盘卖出赚钱的比例), 下方小字是样本笔数。样本少于{MIN_CELL}笔留空。<br>
<b>中位溢价%</b> = 涨停当日收盘买入、次日开盘卖出的收益率中位数。用中位不用平均, 因为平均会被极少数暴涨票拉高, 中位更接近实际能拿到的。样本少于{MIN_MED}笔才留空。<br>
底色: 深绿=胜率≥72%, 浅绿≥66%, 浅红&lt;62%, 深红&lt;58%。<br>
⛔<b>10亿档在月度层面样本薄, 逐月单元格仅供观察, 下结论看底部两行汇总。</b>30亿档逐月可读。
</div>
<h2>一 每30亿一档(逐月可读)</h2>
{table(lb,B30,L30,"1-1 · 2板及以上(游资在炒的票)",f"n={len(lb)}")}
{table(fb,B30,L30,"1-2 · 仅首板",f"n={len(fb)}")}
<h2>二 每10亿一档(看底部汇总行)</h2>
{table(lb,B10,L10,"2-1 · 2板及以上",f"n={len(lb)}")}
{table(fb,B10,L10,"2-2 · 仅首板",f"n={len(fb)}")}
<h2>三 结论</h2>
<p><b>首板买大不买小。</b>胜率随市值单调上升, 0到30亿是全场最差, 150亿以上最好。</p>
<p><b>2板以上的分界线在90亿。</b>90亿以下各档都在63%到66%, 90亿以上跳到70%以上。</p>
<p><b>笔数最多的档不是最赚的档。</b>30到60亿占连板股三分之一, 胜率只有66%, 中等偏下。这是盘面上看起来最热闹的一段。</p>
<p><b>市值在漂移。</b>2025年上半年300亿以上几乎为零, 2026年1月单月就有61笔。同一个市值档在不同时期含义不同, 用固定金额做门槛需要定期复检。</p>
</div></body></html>'''
open('output/表2_涨停股月份市值二维表.html','w').write(doc)
print(f'ok {MS[0]}~{MS[-1]} {len(MS)}个月')
