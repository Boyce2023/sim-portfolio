#!/opt/homebrew/bin/python3
"""打板首板后 · 纯数字表 (市值做行, 每10亿一档不合并)
2026-09-07 Buwen: 全表连续着色, 无白格; 样本数与平均连板数同样着色
"""
import json,statistics as st
R=json.load(open('/tmp/grid_v4.json'))
MS=sorted({r['m'] for r in R})
MSL=[m[2:4]+'/'+m[5:7] for m in MS]   # 2025-01 → 25/01, 收窄列宽
CSS=open('/Users/huaichuaibeimeng/.claude/standards/buwen.css').read()
M10=[(i,i+10) for i in range(10,300,10)]
ROWS=[(f"{a}-{b}",[r for r in R if a<=r['mcap']<b]) for a,b in M10]
ROWS=[(l,g) for l,g in ROWS if g]
UB=[(-1e9,0,'≤0'),*[(i,i+10,f'{i}-{i+10}') for i in range(0,100,10)],(100,1e9,'100+')]
def inb(v,a,b): return v<=0 if b==0 else a<v<=b

def scale_of(vals,bases):
    """列内校准: 取相对偏离绝对值的P85做满色刻度, 让每列都用满渐变"""
    d=sorted(abs((v-b)/b) for v,b in zip(vals,bases) if b)
    return d[int(len(d)*0.85)] if d and d[int(len(d)*0.85)]>1e-6 else 1.0
def cell(v,base,sc):
    """连续着色: 偏离0=极淡, 越偏越深。⛔无死区无白格(2026-09-07)"""
    if not base: return '#fff'
    r=(v-base)/base
    a=0.035+min(1.0,abs(r)/sc)**0.72*0.455
    return (f'rgba(46,125,70,{a:.3f})' if r>=0 else f'rgba(192,57,43,{a:.3f})')
def wrap(head,body,narrow=False):
    def _th(h):
        if narrow and '/' in str(h): return f'<th class="mth">{h}</th>'
        if str(h).startswith('≤0'): return f'<th style="background:#8E2B22">{h}</th>'
        return f'<th>{h}</th>'
    th=''.join(_th(h) for h in head)
    return '<div style="overflow-x:auto"><table><tr>'+th+'</tr>'+body+'</table></div>'

BASE={l:sum(1 for r in R if inb(r['hi10'],a,b))/len(R)*100 for a,b,l in UB}
ALLF=st.mean([r['final'] for r in R])

# ── 表一 市值 × 涨幅区间 ──────────────────────────────────
def t1():
    N=[len(g) for _,g in ROWS];  Nb=st.median(N);  Ns=scale_of(N,[Nb]*len(N))
    F=[st.mean([r['final'] for r in g]) for _,g in ROWS]; Fs=scale_of(F,[ALLF]*len(F))
    P={}
    for a,b,l in UB:
        col=[sum(1 for r in g if inb(r['hi10'],a,b))/len(g)*100 for _,g in ROWS]
        P[l]=(col,scale_of(col,[BASE[l]]*len(col)))
    h=''
    for i,(lab,g) in enumerate(ROWS):
        h+=(f'<tr><td class="mo">{lab}亿</td>'
            f'<td style="background:{cell(N[i],Nb,Ns)}">{N[i]}</td>')
        for a,b,l in UB:
            p=P[l][0][i]; c=round(p*len(g)/100)
            if l=='≤0':                      # ⛔负收益列不上红绿底色, 只把数字标红(Buwen 09-07)
                h+=f'<td class="neg" title="{c}笔 全样本{BASE[l]:.1f}%">{p:.1f}</td>'
            else:
                h+=f'<td style="background:{cell(p,BASE[l],P[l][1])}" title="{c}笔 全样本{BASE[l]:.1f}%">{p:.1f}</td>'
        h+=f'<td style="background:{cell(F[i],ALLF,Fs)}"><b>{F[i]:.2f}</b></td></tr>'
    h+=f'<tr class="sum"><td class="mo"><b>全样本</b></td><td>{len(R)}</td>'
    for a,b,l in UB:
        h+=f'<td class="neg">{BASE[l]:.1f}</td>' if l=='≤0' else f'<td>{BASE[l]:.1f}</td>'
    return h+f'<td>{ALLF:.2f}</td></tr>'

# ── 表二 市值 × 月份 首板数 ───────────────────────────────
def t2():
    MT={mo:len([r for r in R if r['m']==mo]) for mo in MS}
    V=[[sum(1 for r in g if r['m']==mo) for mo in MS] for _,g in ROWS]
    E=[[len(g)*MT[mo]/len(R) for mo in MS] for _,g in ROWS]     # 期望值=行合计×列合计/总数
    sc=scale_of([v for rw in V for v in rw],[e for rw in E for e in rw])
    T=[len(g) for _,g in ROWS]; Tb=st.median(T); Ts=scale_of(T,[Tb]*len(T))
    h=''
    for i,(lab,g) in enumerate(ROWS):
        h+=f'<tr><td class="mo">{lab}亿</td>'
        for j,mo in enumerate(MS):
            h+=f'<td class="mth" style="background:{cell(V[i][j],E[i][j],sc)}" title="{mo} 期望{E[i][j]:.0f}只">{V[i][j]}</td>'
        h+=f'<td style="background:{cell(T[i],Tb,Ts)}"><b>{T[i]}</b></td></tr>'
    h+='<tr class="sum"><td class="mo"><b>月合计</b></td>'
    for mo in MS: h+=f'<td class="mth">{MT[mo]}</td>'
    return h+f'<td>{len(R)}</td></tr>'

# ── 表三 市值 × 月份 平均连板数 ───────────────────────────
def t3():
    V=[[([r['final'] for r in g if r['m']==mo]) for mo in MS] for _,g in ROWS]
    flat=[st.mean(c) for rw in V for c in rw if len(c)>=5]
    sc=scale_of(flat,[ALLF]*len(flat))
    F=[st.mean([r['final'] for r in g]) for _,g in ROWS]; Fs=scale_of(F,[ALLF]*len(F))
    h=''
    for i,(lab,g) in enumerate(ROWS):
        h+=f'<tr><td class="mo">{lab}亿</td>'
        for j,mo in enumerate(MS):
            c=V[i][j]
            if len(c)<5: h+=f'<td class="z mth" title="{mo} {len(c)}笔 样本不足">·</td>'; continue
            v=st.mean(c)
            h+=f'<td class="mth" style="background:{cell(v,ALLF,sc)}" title="{mo} {len(c)}笔">{v:.2f}</td>'
        h+=f'<td style="background:{cell(F[i],ALLF,Fs)}"><b>{F[i]:.2f}</b></td></tr>'
    h+='<tr class="sum"><td class="mo"><b>全期</b></td>'
    for mo in MS:
        c=[r for r in R if r['m']==mo]; h+=f'<td class="mth">{st.mean([r["final"] for r in c]):.2f}</td>'
    return h+f'<td>{ALLF:.2f}</td></tr>'

doc=f'''<!doctype html><html><head><meta charset="utf-8"><title>打板市值研究</title><style>{CSS}
table{{border-collapse:collapse;font-size:9.5px}}
th{{background:#1B3A5B;color:#fff;padding:4px 5px;font-size:8.5px;white-space:nowrap}}
td{{border:1px solid #E8ECEF;padding:3px 4px;text-align:center;white-space:nowrap;min-width:36px}}
.mo{{background:#F5F8FB;text-align:right;padding-right:7px;font-weight:600;color:#1B3A5B;min-width:64px}}
.z{{background:#FCFCFC;color:#dcdcdc}}
.neg{{background:#fff;color:#C0392B;font-weight:600}}
.sum td.neg{{background:#E3EBF2;color:#C0392B}}
.mth{{min-width:20px;padding:3px 2px;font-size:9px}}
th.mth{{padding:4px 2px}}
.sum td{{border-top:2px solid #1B3A5B;background:#E3EBF2;font-weight:700}}
.sum .mo{{background:#1B3A5B;color:#fff}}
.lg{{font-size:9.5px;color:#777;margin:5px 0 26px}} h2{{margin-top:28px}}
</style></head><body><div class="container">
<h1>打板 · 首板后10日最大涨幅 × 流通市值</h1>
<div class="doc-sub">{MS[0]} 至 {MS[-1]} · 首板样本 {len(R)} 个 · 流通市值取首板当日 · 涨幅=首板收盘价起算, 后10个交易日内摸到的最大涨幅</div>
<div class="doc-sub">配色: 每列独立校准, 绿=高于该列基准, 红=低于, 深浅=偏离幅度(P85满色)。偏离接近0时颜色极淡但不留白。</div><hr class="rule-navy">

<h2>一 市值 × 涨幅区间</h2>
{wrap(['流通市值','样本']+[f'{l}%' for _,_,l in UB]+['平均连板数'],t1())}
<div class="lg">格子=占该市值档的百分比, 每行横向加总100。样本列基准=各档样本数中位, ≤0列不上底色只把数字标红, 其余涨幅区间列基准=最下一行全样本同列, 连板数列基准={ALLF:.2f}。悬停看笔数。</div>

<h2>二 市值 × 月份 首板数</h2>
{wrap(['流通市值']+MSL+['合计'],t2(),True)}
<div class="lg">格子=该市值档当月的首板只数, 基准=期望值(该档全期只数 × 当月全部首板数 ÷ 总数), 绿=比该月大盘节奏应有的多, 红=少。悬停看期望值。</div>

<h2>三 市值 × 月份 平均连板数</h2>
{wrap(['流通市值']+MSL+['全期'],t3(),True)}
<div class="lg">连板数含首板本身, 首板后不再涨停记1。基准={ALLF:.2f}。样本&lt;5的格子留空(悬停看实际笔数)。</div>
</div></body></html>'''
open('output/表2_打板市值研究.html','w').write(doc)
print(f'ok {len(R)}首板 | {len(ROWS)}行 × ({len(UB)}涨幅列 | {len(MS)}月列) | 全表连续着色')
