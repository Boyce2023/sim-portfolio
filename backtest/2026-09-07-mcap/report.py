#!/opt/homebrew/bin/python3
"""打板市值研究 · 合并版 (2026-09-07)
取各版之长: 月×市值矩阵 + 完整不压缩分档 + 红绿双向配色 + 胜率与赔率并列
去掉: 条形图/堆叠条/自作主张的合并分档/单色热力
"""
import json,statistics as st
R=json.load(open('/tmp/grid_v3.json'))
FB=[r for r in R if r['first']]
MS=sorted({r['m'] for r in R})
CSS=open('/Users/huaichuaibeimeng/.claude/standards/buwen.css').read()
M10=[(i,i+10) for i in range(10,300,10)]          # 市值10亿一档
M10L=[f"{i}-{i+10}" for i in range(10,300,10)]
MCOL=[(0,30),(30,60),(60,90),(90,120),(120,150),(150,200),(200,300),(300,99999)]
MCOLL=['&lt;30','30-60','60-90','90-120','120-150','150-200','200-300','300+']
UB=[(-999,0,'≤0')]+[(i,i+10,f'{i}-{i+10}') for i in range(0,100,10)]+[(100,99999,'100+')]

def wr(s): return sum(1 for r in s if r['prem']>0)/len(s)*100 if s else 0
def ev(s): return st.mean([r['prem'] for r in s]) if s else 0
def odd(s):
    p=[r['prem'] for r in s]; w=[x for x in p if x>0]; l=[x for x in p if x<=0]
    return st.mean(w)/abs(st.mean(l)) if (w and l) else 0
def col(v,lo,hi,mid=None):
    """红绿双向: v<=lo 红, v>=hi 绿, 中间灰"""
    if v>=hi: t=min(1,(v-hi)/(hi-(mid or (lo+hi)/2)+1e-9)); return f'rgba(46,125,70,{0.18+t*0.5:.2f})'
    if v<=lo: t=min(1,(lo-v)/((mid or (lo+hi)/2)-lo+1e-9)); return f'rgba(192,57,43,{0.18+t*0.45:.2f})'
    return '#F4F6F7'

def tbl(head,rows_html,note=''):
    return (f'<div style="overflow-x:auto"><table><tr>'+''.join(f'<th>{h}</th>' for h in head)+'</tr>'
            +rows_html+'</table></div>'+(f'<div class="lg">{note}</div>' if note else ''))

# 表一 市值×(胜率 赔率 期望 后续涨幅)  10亿一档不压缩
def t1():
    h=''
    base_w=wr(FB); base_e=ev(FB)
    for (lo,hi),lab in zip(M10,M10L):
        g=[r for r in FB if lo<=r['mcap']<hi]
        if not g: continue
        w,e,o=wr(g),ev(g),odd(g)
        u=[r['maxup10'] for r in g]
        dead=sum(1 for r in g if r['maxup10']<=0)/len(g)*100
        big=sum(1 for r in g if r['maxup10']>30)/len(g)*100
        s5=sum(1 for r in g if r['final']>=5)/len(g)*100
        h+=(f'<tr><td class="mo">{lab}亿</td>'
            f'<td class="n">{len(g)}</td>'
            f'<td style="background:{col(w,59,64)}">{w:.0f}</td>'
            f'<td style="background:{col(e,1.5,1.9)}">{e:+.2f}</td>'
            f'<td style="background:{col(o,2.15,2.35)}">{o:.2f}</td>'
            f'<td style="background:{col(-dead,-6.5,-4.5)}">{dead:.1f}</td>'
            f'<td style="background:{col(st.median(u),10.2,11.5)}">{st.median(u):+.1f}</td>'
            f'<td style="background:{col(big,11,15)}">{big:.1f}</td>'
            f'<td style="background:{col(s5,0.6,1.4)}">{s5:.1f}</td></tr>')
    g=FB; u=[r['maxup10'] for r in g]
    h+=(f'<tr class="sum"><td class="mo"><b>全样本</b></td><td>{len(g)}</td><td>{wr(g):.0f}</td>'
        f'<td>{ev(g):+.2f}</td><td>{odd(g):.2f}</td>'
        f'<td>{sum(1 for r in g if r["maxup10"]<=0)/len(g)*100:.1f}</td>'
        f'<td>{st.median(u):+.1f}</td><td>{sum(1 for r in g if r["maxup10"]>30)/len(g)*100:.1f}</td>'
        f'<td>{sum(1 for r in g if r["final"]>=5)/len(g)*100:.1f}</td></tr>')
    return h

# 表二 月×市值 (可切换指标)
def t2(metric,lo,hi,fmt,data):
    h=''
    for mo in MS:
        g=[r for r in data if r['m']==mo]
        if len(g)<20: continue
        h+=f'<tr><td class="mo">{mo}</td>'
        for a,b in MCOL:
            c=[r for r in g if a<=r['mcap']<b]
            if len(c)<8: h+='<td class="na"></td>'; continue
            v=metric(c)
            h+=f'<td style="background:{col(v,lo,hi)}" title="{len(c)}笔">{fmt(v)}</td>'
        h+=f'<td class="tot">{fmt(metric(g))}</td><td class="n">{len(g)}</td></tr>'
    h+='<tr class="sum"><td class="mo"><b>全期</b></td>'
    for a,b in MCOL:
        c=[r for r in data if a<=r['mcap']<b]
        h+=f'<td>{fmt(metric(c))}</td>' if c else '<td class="na"></td>'
    h+=f'<td>{fmt(metric(data))}</td><td>{len(data)}</td></tr>'
    return h

# 表三 市值×涨幅区间 完整不压缩
COLAVG=[len([r for r in FB if (r['maxup10']<=0 if b==0 else a<r['maxup10']<=b)])/len(FB)*100 for a,b,_ in UB]
def t3():
    h=''
    for (lo,hi),lab in zip(M10,M10L):
        g=[r for r in FB if lo<=r['mcap']<hi]
        if not g: continue
        h+=f'<tr><td class="mo">{lab}亿</td>'
        for i,(a,b,_) in enumerate(UB):
            c=[r for r in g if (r['maxup10']<=0 if b==0 else a<r['maxup10']<=b)]
            p=len(c)/len(g)*100
            if p<0.05: h+='<td class="z"></td>'; continue
            base=COLAVG[i]; rr=(p-base)/base if base else 0
            if rr>=0.12: t=min(1,(rr-0.12)/0.55); bg=f'rgba(46,125,70,{0.16+t*0.52:.2f})'
            elif rr<=-0.12: t=min(1,(-rr-0.12)/0.55); bg=f'rgba(192,57,43,{0.16+t*0.46:.2f})'
            else: bg='#F4F6F7'
            h+=f'<td style="background:{bg}" title="{len(c)}笔 基准{base:.1f}%">{p:.1f}</td>'
        u=[r['maxup10'] for r in g]
        h+=f'<td class="n">{len(g)}</td><td class="tot">{st.median(u):+.1f}</td></tr>'
    h+='<tr class="sum"><td class="mo"><b>全样本</b></td>'
    for a,b,_ in UB:
        c=[r for r in FB if (r['maxup10']<=0 if b==0 else a<r['maxup10']<=b)]
        h+=f'<td>{len(c)/len(FB)*100:.1f}</td>'
    h+=f'<td>{len(FB)}</td><td>{st.median([r["maxup10"] for r in FB]):+.1f}</td></tr>'
    return h

f0=lambda v:f'{v:.0f}'; f2=lambda v:f'{v:+.2f}'
doc=f'''<!doctype html><html><head><meta charset="utf-8"><title>打板市值研究</title><style>{CSS}
table{{border-collapse:collapse;font-size:9.5px;margin-bottom:4px}}
th{{background:#1B3A5B;color:#fff;padding:4px 5px;font-size:9px;white-space:nowrap}}
td{{border:1px solid #E9ECEF;padding:3px 5px;text-align:center;white-space:nowrap;min-width:38px}}
.mo{{background:#F5F8FB;text-align:right;padding-right:7px;font-weight:600;color:#1B3A5B;min-width:64px}}
.n{{background:#FAFBFC;color:#8A857C;font-size:8.5px}}
.tot{{background:#EFF3F6;color:#333;font-weight:600}} .na{{background:#FCFCFC}} .z{{background:#FDFDFD;color:#e0e0e0}}
.sum td{{border-top:2px solid #1B3A5B;background:#E3EBF2;font-weight:700}}
.sum .mo{{background:#1B3A5B;color:#fff}}
.lg{{font-size:9.5px;color:#666;margin:5px 0 22px}}
.box{{background:#F5F8FB;border-left:3px solid #1B3A5B;padding:10px 14px;margin:12px 0;font-size:10.5px}}
h2{{margin-top:26px}} h3{{margin-top:16px}}
</style></head><body><div class="container">
<h1>打板策略 · 市值研究</h1>
<div class="doc-sub">{MS[0]} 至 {MS[-1]} · 涨停样本 {len(R)} 个(首板 {len(FB)}) · 溢价=涨停收盘买入次日开盘卖出 · 后续涨幅=首板收盘起后10个交易日最高价 · Claude分析意见</div><hr class="rule-navy">

<div class="box"><b>四句话</b><br>
一、<b>赔率不随市值变化</b>(全部2.1到2.5), 所以市值只影响胜率。大市值更好这个结论没有被赔率抵消。<br>
二、<b>期望最高在150到200亿</b>, 每笔+1.99%。30亿以下均盈最高(+4.25%)但均亏也最大(-2.01%), 赔率反而全场最低。<br>
三、<b>首板后10天中位涨10%到12%</b>, 各档差别不大; 但"涨不动"比例从7.4%单调降到3.0%。<br>
四、<b>小市值是彩票, 大市值是稳定收益</b>。30亿以下走出5连板是300亿以上的5.7倍, 但80.8%只走一板。两者不可兼得。</div>

<h2>一 市值分档全指标(每10亿一档, 不合并)</h2>
{tbl(['流通市值','样本','胜率%','期望%','赔率','涨不动%','后10日中位涨幅%','涨超30%占比','走出5板占比'],t1(),
 "红绿是相对全样本基准的偏离。<b>涨不动</b>=首板后10日最高价未超过首板收盘。<b>赔率</b>=平均盈利÷平均亏损。")}

<h2>二 月份 × 市值</h2>
<h3>2-1 胜率%</h3>
{tbl(['月份']+MCOLL+['月合计','样本'],t2(wr,59,64,f0,FB),"绿≥64%, 红≤59%。样本少于8笔的格子留空。")}
<h3>2-2 每笔期望收益%</h3>
{tbl(['月份']+MCOLL+['月合计','样本'],t2(ev,1.5,1.9,f2,FB),"绿≥+1.9%, 红≤+1.5%。")}
<h3>2-3 首板后10日中位涨幅%</h3>
{tbl(['月份']+MCOLL+['月合计','样本'],t2(lambda s:st.median([r['maxup10'] for r in s]),10.2,11.5,lambda v:f'{v:+.1f}',FB),"绿≥+11.5%, 红≤+10.2%。")}

<h2>三 市值 × 首板后涨幅区间(每10%一级, 不合并)</h2>
{tbl(['流通市值']+[l for _,_,l in UB]+['样本','中位'],t3(),
 "格子=占该市值档的百分比, 每行横向加总100。⭐颜色是<b>相对全样本的偏离</b>: <b style='color:#2E7D46'>绿</b>=该档在此涨幅区间比全市场更集中, <b style='color:#C0392B'>红</b>=更稀疏。悬停看笔数与基准。")}

<h2>四 怎么用</h2>
<p><b>做次日开盘卖(B策略)</b>: 选150到200亿, 期望最高。避开30亿以下, 赔率最差。</p>
<p><b>想吃连板</b>: 只能去小市值找, 但要接受80%以上只有一个板。这是两套玩法, 不要混。</p>
<p><b>市值在漂移</b>: 连板股中位市值从2025年1月的39亿涨到2026年6月的118亿。固定金额门槛每季度复检。</p>
<p><b>样本悬崖在200亿</b>: 200亿以下每档一百到两千多笔, 以上多数只剩几十到一百多笔, 那些行的百分比要打折看。</p>
</div></body></html>'''
open('output/表2_打板市值研究.html','w').write(doc)
print('ok')
