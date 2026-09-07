#!/opt/homebrew/bin/python3
"""打板市值研究 v2 — 胜率+赔率+首板后涨幅分布+连板数, 按月。数据源 /tmp/grid_v3.json"""
import json,statistics as st,collections
rows=json.load(open('/tmp/grid_v3.json'))
fb=[r for r in rows if r['first']]
MS=sorted({r['m'] for r in rows})
CSS=open('/Users/huaichuaibeimeng/.claude/standards/buwen.css').read()
MB=[(0,30),(30,60),(60,90),(90,120),(120,150),(150,200),(200,300),(300,99999)]
ML=['&lt;30亿','30-60亿','60-90亿','90-120亿','120-150亿','150-200亿','200-300亿','300亿以上']
def m(s,k='prem'): return st.mean([r[k] for r in s]) if s else 0
def wr(s): return sum(1 for r in s if r['prem']>0)/len(s)*100 if s else 0
def odds(s):
    p=[r['prem'] for r in s]; w=[x for x in p if x>0]; l=[x for x in p if x<=0]
    return (st.mean(w)/abs(st.mean(l))) if (w and l) else 0

def bar_dual(data,title,sub):
    """双条: 上条胜率, 下条期望值"""
    items=[]
    for (lo,hi),lab in zip(MB,ML):
        g=[r for r in data if lo<=r['mcap']<hi]
        if len(g)<50: continue
        items.append((lab,len(g),wr(g),odds(g),m(g),
                      st.mean([x['prem'] for x in g if x['prem']>0]),
                      abs(st.mean([x['prem'] for x in g if x['prem']<=0]))))
    h=f'<h3>{title}</h3><div class="doc-sub">{sub}</div><div class="chart">'
    mx=max(x[4] for x in items)
    for lab,n,w,od,ev,aw,al in items:
        pw=max(2,min(100,(w-50)/25*100))
        pe=max(2,min(100,ev/mx*100))
        cw='#2E7D46' if w>=65 else ('#C0392B' if w<60 else '#4E7CA0')
        h+=(f'<div class="grp"><div class="lab">{lab}</div><div class="bars">'
            f'<div class="b"><div class="t"><div class="f" style="width:{pw}%;background:{cw}"></div></div>'
            f'<span class="v">胜率 <b>{w:.0f}%</b></span></div>'
            f'<div class="b"><div class="t"><div class="f" style="width:{pe}%;background:#1B3A5B"></div></div>'
            f'<span class="v">期望 <b>{ev:+.2f}%</b></span></div></div>'
            f'<div class="meta">赔率 <b>{od:.2f}</b><br><span class="n">盈{aw:+.2f} 亏-{al:.2f} · {n}笔</span></div></div>')
    return h+'</div>'

def updist(data,title,sub):
    """首板后10日最大涨幅分布 堆叠条"""
    UB=[(-999,0,'涨不动','#C0392B'),(0,10,'0-10%','#E8C9A0'),(10,20,'10-20%','#A8C4A2'),
        (20,30,'20-30%','#6E9E77'),(30,50,'30-50%','#41764F'),(50,9999,'50%以上','#1F4A2C')]
    h=f'<h3>{title}</h3><div class="doc-sub">{sub}</div><div class="chart">'
    for (lo,hi),lab in zip(MB,ML):
        g=[r for r in data if lo<=r['mcap']<hi]
        if len(g)<50: continue
        h+=f'<div class="row"><div class="lab">{lab}</div><div class="stack">'
        for a,b,nm,col in UB:
            c=[r for r in g if (r['maxup10']<=0 if b==0 else a<r['maxup10']<=b)]
            p=len(c)/len(g)*100
            if p<1.2: continue
            h+=f'<div style="width:{p}%;background:{col}" title="{nm}: {p:.1f}%">{nm.replace("%","") if p>8 else ""}</div>'
        med=st.median([r['maxup10'] for r in g])
        h+=f'</div><div class="meta">中位 <b>{med:+.1f}%</b><span class="n">{len(g)}笔</span></div></div>'
    h+='<div class="legend">'+''.join(f'<span><i style="background:{c}"></i>{n}</span>' for _,_,n,c in UB)+'</div>'
    return h+'</div>'

def streakdist(data,title,sub):
    h=f'<h3>{title}</h3><div class="doc-sub">{sub}</div><div class="chart">'
    SB=[(1,1,'只1板','#D8DEE6'),(2,2,'2板','#A8C4D8'),(3,3,'3板','#6E9AC0'),(4,4,'4板','#3F6E9E'),(5,99,'5板以上','#C0392B')]
    for (lo,hi),lab in zip(MB,ML):
        g=[r for r in data if lo<=r['mcap']<hi]
        if len(g)<50: continue
        h+=f'<div class="row"><div class="lab">{lab}</div><div class="stack">'
        for a,b,nm,col in SB:
            c=[r for r in g if a<=r['final']<=b]
            p=len(c)/len(g)*100
            if p<0.8: continue
            fc='#fff' if nm in('4板','5板以上') else '#333'
            h+=f'<div style="width:{p}%;background:{col};color:{fc}" title="{nm}: {p:.1f}%">{nm if p>7 else ""}</div>'
        h+=f'</div><div class="meta">平均 <b>{st.mean([r["final"] for r in g]):.2f}</b>板<span class="n">5板+占{sum(1 for r in g if r["final"]>=5)/len(g)*100:.1f}%</span></div></div>'
    return h+'</div>'

def monthly(data,metric,title,sub):
    """按月 × 市值 的指标热力"""
    h=f'<h3>{title}</h3><div class="doc-sub">{sub}</div><div style="overflow-x:auto"><table class="hm"><tr><th></th>'
    h+=''.join(f'<th>{x}</th>' for x in ML)+'<th>月合计</th></tr>'
    for mo in MS:
        g=[r for r in data if r['m']==mo]
        if len(g)<20: continue
        h+=f'<tr><td class="mo">{mo[2:]}</td>'
        for lo,hi in MB:
            c=[r for r in g if lo<=r['mcap']<hi]
            if len(c)<8: h+='<td class="na"></td>'; continue
            v=metric(c)
            if metric==wr: t=(v-50)/25; lo_,hi_=57,68; unit='%'
            else: t=(v-0)/3.5; lo_,hi_=1.0,2.2; unit='%'
            t=max(0,min(1,t))
            bg=f'rgba(46,125,70,{0.15+t*0.6:.2f})' if v>=hi_ else (f'rgba(192,57,43,{0.15+(1-t)*0.5:.2f})' if v<=lo_ else '#F4F6F7')
            fmt=(f'{v:.0f}' if metric==wr else f'{v:.2f}')
            h+=f'<td style="background:{bg}" title="{mo} {lo}-{hi}亿: {v:.2f}{unit} n={len(c)}">{fmt}</td>'
        gt=metric(g); h+=(f'<td class="tot">{gt:.0f}</td></tr>' if metric==wr else f'<td class="tot">{gt:.2f}</td></tr>')
    return h+'</table></div>'

doc=f'''<!doctype html><html><head><meta charset="utf-8"><title>打板市值研究</title><style>{CSS}
.chart{{margin:9px 0 20px}}
.grp{{display:flex;align-items:center;margin:6px 0;border-bottom:1px solid #F0F2F4;padding-bottom:5px}}
.row{{display:flex;align-items:center;margin:4px 0}}
.lab{{width:88px;font-size:10px;text-align:right;padding-right:9px;color:#444;flex-shrink:0}}
.bars{{flex:1}} .b{{display:flex;align-items:center;margin:2px 0}}
.t{{position:relative;flex:1;height:14px;background:#F2F4F6;border-radius:2px}}
.f{{height:100%;border-radius:2px}}
.v{{width:96px;font-size:9.5px;padding-left:8px;color:#444}}
.meta{{width:132px;font-size:9.5px;padding-left:10px;color:#444;flex-shrink:0}}
.meta .n{{color:#9a958c;font-size:8.5px;display:block}}
.stack{{flex:1;display:flex;height:18px;border-radius:2px;overflow:hidden;font-size:8px;line-height:18px;text-align:center}}
.stack div{{overflow:hidden;white-space:nowrap}}
.legend{{margin-top:7px;font-size:9px;color:#666;padding-left:88px}}
.legend span{{margin-right:13px}} .legend i{{display:inline-block;width:9px;height:9px;margin-right:3px;vertical-align:-1px}}
table.hm{{border-collapse:collapse}} .hm th{{background:#1B3A5B;color:#fff;font-size:8.5px;padding:3px 5px;white-space:nowrap}}
.hm td{{border:1px solid #fff;padding:2px 4px;text-align:center;font-size:8.5px;min-width:32px}}
.hm .mo{{background:#F5F8FB;text-align:right;color:#444}} .hm .tot{{background:#EAF0F5;font-weight:700}} .hm .na{{background:#FCFCFC}}
.box{{background:#F5F8FB;border-left:3px solid #1B3A5B;padding:9px 13px;margin:11px 0;font-size:10.5px}}
</style></head><body><div class="container">
<h1>打板策略 · 市值 · 胜率与赔率</h1>
<div class="doc-sub">{MS[0]} 至 {MS[-1]} · {len(rows)}个涨停样本(首板{len(fb)}) · 溢价=涨停收盘买入次日开盘卖出 · Claude分析意见</div><hr class="rule-navy">

<div class="box"><b>四句话结论</b><br>
一、<b>赔率几乎不随市值变化</b>, 全部在2.1到2.5之间。所以市值只影响胜率, 不影响赔率, 大市值更好这个结论没有被赔率抵消。<br>
二、<b>期望值最高的是150到200亿</b>, 每笔+1.99%。30亿以下均盈虽最高(+4.25%)但均亏也最大(-2.01%), 赔率反而全场最低。<br>
三、<b>首板买进去后10天最高能涨10%到12%</b>(中位), 各档差别不大; 但<b>"完全涨不动"的比例</b>从30亿以下的7.4%单调降到300亿以上的3.0%。<br>
四、<b>小市值是彩票, 大市值是稳定收益</b>。30亿以下走出5连板的概率是300亿以上的5.7倍, 但80.8%只走一板就结束。<b>要龙头就去小市值找并接受高失败率, 要稳定就买大市值但别指望连板。</b></div>

<h2>一 首板 · 胜率与赔率</h2>
{bar_dual(fb,"首板按流通市值","上条=胜率, 下条=每笔期望收益; 右侧是赔率(均盈÷均亏)")}

<h2>二 首板之后能涨多少</h2>
{updist(fb,"首板后10个交易日最大涨幅分布","从首板收盘价算起, 后续10日内最高价的涨幅")}

<h2>三 首板最终走几个板</h2>
{streakdist(fb,"首板最终连板数分布","这一波总共封了几个板")}

<h2>四 逐月</h2>
{monthly(fb,wr,"首板胜率 · 月 × 市值","数字是胜率%, 绿=68以上, 红=57以下")}
{monthly(fb,m,"首板期望收益 · 月 × 市值","数字是每笔期望%, 绿=2.2以上, 红=1.0以下")}

<h2>五 怎么用</h2>
<p><b>做B策略(次日开盘卖)</b>: 选150到200亿, 期望值最高。避开30亿以下, 那里赔率最差。</p>
<p><b>想吃连板</b>: 只能去小市值找, 但要接受80%以上只有一个板, 且7.4%买了就涨不动。这是两套完全不同的玩法。</p>
<p><b>市值在漂移</b>: 连板股中位市值从2025年1月的39亿涨到2026年6月的118亿。固定金额门槛需要每季度复检。</p>
</div></body></html>'''
open('output/表2_打板市值研究.html','w').write(doc)
print('ok')
