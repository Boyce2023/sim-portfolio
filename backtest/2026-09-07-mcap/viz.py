#!/opt/homebrew/bin/python3
"""可读版: 用图不用数字矩阵。数据源 /tmp/grid_v2.json (grid_v2.py生成, 含累计涨幅与板性)"""
import json,statistics as st,collections
rows=json.load(open('/tmp/grid_v2.json'))
MS=sorted({r['m'] for r in rows})
CSS=open('/Users/huaichuaibeimeng/.claude/standards/buwen.css').read()
def wr(s): return sum(1 for r in s if r['prem']>0)/len(s)*100 if s else 0
def md(s): return st.median([r['prem'] for r in s]) if s else 0

def bars(data,bins,labels,title,sub,key='mcap'):
    """横向条形图: 每档一行, 条长=胜率, 右侧标中位溢价与样本数"""
    items=[]
    for (lo,hi),lab in zip(bins,labels):
        g=[r for r in data if lo<=r[key]<hi]
        if len(g)<20: continue
        items.append((lab,len(g),wr(g),md(g)))
    if not items: return ''
    base=wr(data)
    h=f'<h3>{title}</h3><div class="doc-sub">{sub} · 基线胜率 {base:.0f}%(虚线) · 共{len(data)}笔</div><div class="chart">'
    for lab,n,w,m in items:
        pct=(w-45)/35*100   # 45%到80%映射到0-100%
        pct=max(2,min(100,pct))
        bl=(base-45)/35*100
        col='#2E7D46' if w>=base+4 else ('#C0392B' if w<=base-4 else '#4E7CA0')
        h+=(f'<div class="row"><div class="lab">{lab}</div>'
            f'<div class="track"><div class="fill" style="width:{pct}%;background:{col}"></div>'
            f'<div class="baseline" style="left:{bl}%"></div>'
            f'<span class="val">{w:.0f}%</span></div>'
            f'<div class="meta">中位 <b>{m:+.2f}%</b><span class="n">{n}笔</span></div></div>')
    return h+'</div>'

def heat(data,title,sub):
    """月×市值热力图: 只用颜色不写数字, 鼠标悬停出数"""
    B=[(0,30),(30,60),(60,90),(90,150),(150,300),(300,99999)]
    L=['&lt;30亿','30-60','60-90','90-150','150-300','300亿+']
    h=f'<h3>{title}</h3><div class="doc-sub">{sub} · 颜色=胜率, 悬停看具体数字</div>'
    h+='<div style="overflow-x:auto"><table class="hm"><tr><th></th>'+''.join(f'<th>{x}</th>' for x in L)+'<th>月合计</th></tr>'
    for m in MS:
        g=[r for r in data if r['m']==m]
        h+=f'<tr><td class="mo">{m[2:]}</td>'
        for lo,hi in B:
            c=[r for r in g if lo<=r['mcap']<hi]
            if len(c)<5: h+='<td class="na"></td>'; continue
            w=wr(c); t=(w-45)/35
            t=max(0,min(1,t))
            if w>=68: bg=f'rgba(46,125,70,{0.25+t*0.55:.2f})'
            elif w<=57: bg=f'rgba(192,57,43,{0.25+(1-t)*0.5:.2f})'
            else: bg='#F2F4F6'
            h+=f'<td style="background:{bg}" title="{m} {lo}-{hi}亿: 胜率{w:.0f}% 中位{md(c):+.2f}% n={len(c)}"></td>'
        w=wr(g)
        h+=f'<td class="tot">{w:.0f}%</td></tr>'
    h+='</table></div>'
    return h

lb=[r for r in rows if r['cum']>=12]      # 累计涨幅≥12% = 至少走出一个板以上的行情
fb=[r for r in rows if r['cum']<12]       # 首板
MB=[(0,30),(30,60),(60,90),(90,120),(120,150),(150,200),(200,300),(300,99999)]
ML=['&lt;30亿','30-60亿','60-90亿','90-120亿','120-150亿','150-200亿','200-300亿','300亿以上']
CB=[(0,12),(12,25),(25,40),(40,60),(60,90),(90,150),(150,9999)]
CL=['&lt;12% 首板','12-25%','25-40%','40-60%','60-90%','90-150%','150%以上']

doc=f'''<!doctype html><html><head><meta charset="utf-8"><title>打板市值研究</title><style>{CSS}
.chart{{margin:10px 0 18px}}
.row{{display:flex;align-items:center;margin:3px 0}}
.lab{{width:96px;font-size:10px;text-align:right;padding-right:9px;color:#444;flex-shrink:0}}
.track{{position:relative;flex:1;height:19px;background:#F2F4F6;border-radius:2px}}
.fill{{height:100%;border-radius:2px}}
.baseline{{position:absolute;top:-2px;bottom:-2px;width:0;border-left:1.5px dashed #8A857C}}
.val{{position:absolute;right:6px;top:2px;font-size:10px;font-weight:700;color:#1F1F1C}}
.meta{{width:130px;font-size:9.5px;padding-left:9px;color:#444;flex-shrink:0}}
.meta .n{{color:#9a958c;margin-left:6px;font-size:8.5px}}
table.hm{{border-collapse:collapse}} .hm th{{background:#1B3A5B;color:#fff;font-size:9px;padding:3px 6px;white-space:nowrap}}
.hm td{{border:1px solid #fff;width:34px;height:17px;padding:0}}
.hm .mo{{background:#F5F8FB;font-size:9px;text-align:right;padding-right:5px;width:auto;color:#444}}
.hm .tot{{background:#EAF0F5;font-size:9px;text-align:center;width:auto;padding:0 5px;font-weight:700}}
.hm .na{{background:#FCFCFC}}
.box{{background:#F5F8FB;border-left:3px solid #1B3A5B;padding:9px 13px;margin:11px 0;font-size:10.5px}}
.warn{{background:#FDF2F2;border-left:3px solid #C0392B;padding:9px 13px;margin:11px 0;font-size:10.5px}}
</style></head><body><div class="container">
<h1>打板策略 · 市值与涨幅研究</h1>
<div class="doc-sub">{MS[0]} 至 {MS[-1]} · 共{len(rows)}个涨停样本 · 溢价 = 涨停当日收盘买入、次日开盘卖出的收益率 · Claude分析意见</div><hr class="rule-navy">

<div class="box"><b>三句话结论</b><br>
一、<b>首板买大不买小</b>。30亿以下是全场最差, 150亿以上最好。<br>
二、<b>已有涨幅的票, 甜区在累计涨25%到40%</b>, 胜率71%。<br>
三、<b>累计涨幅超150%是负期望区</b>, 胜率只有25%, 中位亏5%。这是全研究里唯一的负值区。</div>

<h2>一 首板 · 市值决定胜率</h2>
{bars(fb,MB,ML,"首板(累计涨幅<12%)按流通市值","市值越大胜率越高, 单调无例外")}

<h2>二 已启动的票 · 累计涨幅比板数更重要</h2>
<div class="warn"><b>为什么不用"连板数"</b>: 主板涨停10%、创业板科创板20%。同样叫"3板", 主板累计涨33%, 创业板涨73%, <b>差2.2倍</b>。
把它们放进同一格统计没有意义。改用<b>累计涨幅</b>作为可比单位。</div>
{bars(rows,CB,CL,"全样本按累计涨幅","25-40%是甜区; 150%以上是断崖", key='cum')}

<h2>三 已启动的票 · 市值</h2>
{bars(lb,MB,ML,"累计涨幅≥12%的票按流通市值","90亿是台阶: 以下63-66%, 以上70%+")}

<h2>四 逐月热力图</h2>
{heat(lb,"已启动的票 · 月份 × 市值","悬停单元格看胜率与样本数")}
{heat(fb,"首板 · 月份 × 市值","")}

<h2>五 要注意的两件事</h2>
<p><b>笔数最多的档不是最赚的档。</b>30到60亿这一段占了三分之一的连板股, 是盘面上看起来最热闹的, 但胜率只在中等偏下。</p>
<p><b>市值在漂移。</b>连板股的中位市值从2025年1月的39亿涨到2026年6月的118亿, 翻了三倍。同一个市值档在不同时期含义不同, 固定金额的门槛需要每季度复检。</p>
</div></body></html>'''
open('output/表2_打板市值研究.html','w').write(doc)
print(f'ok {MS[0]}~{MS[-1]}')
