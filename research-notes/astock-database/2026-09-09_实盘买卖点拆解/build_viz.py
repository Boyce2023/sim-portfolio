# -*- coding: utf-8 -*-
import pandas as pd,numpy as np,json,sqlite3,html
D=pd.read_pickle('/tmp/dhbr/diag_rt.pkl'); O=pd.read_pickle('/tmp/dhbr/diag_open.pkl'); T=json.load(open('/tmp/dhbr/buwen_trades_all.json'))
con=sqlite3.connect('/tmp/dhbr/exit_bars.db'); K=pd.read_sql("select code,date,open,high,low,close from k",con); K['date']=pd.to_datetime(K['date']); K=K.sort_values(['code','date'])
bars={c:g.reset_index(drop=True) for c,g in K.groupby('code')}
FB,FS=0.00036,0.00086
def f(x,d=1):
    try:
        if x!=x: return ''
    except: return ''
    return ('−' if x<0 else '')+f"{abs(x):,.{d}f}"
def bar(c,d):
    g=bars[c]; x=g[g.date==d]; return x.iloc[0] if len(x) else None
def closeN(c,d,n):
    g=bars[c]; x=g[g.date>d].head(n); return x.close.iloc[-1] if len(x)>=n else None
def maxN(c,d,n):
    g=bars[c]; x=g[g.date>d].head(n); return x.high.max() if len(x) else None
# ── 精确分解(恒等式): q(sp−bp)−fee = q[(C5−C0)+(C0−bp)+(sp−Cs)+(Cs−C5)] − fee
rows=[]
for _,r in D.iterrows():
    b=bar(r.code,r.bd); s=bar(r.code,r.sd); c5=closeN(r.code,r.bd,5)
    if b is None or s is None: continue
    if c5 is None: c5=bars[r.code].close.iloc[-1]
    fee=r.bp*r.q*FB+r.sp*r.q*FS
    rows.append(dict(name=r['name'],code=r.code,bd=r.bd,sd=r.sd,q=r.q,cap=r.cap,ret=r.ret,pnl=r.pnl,hold=r.hold,prev=r.prev,after5=r.after5,auction=r.auction_sell,
        pick=r.q*(c5-b.close), entry=r.q*(b.close-r.bp), exit_intra=r.q*(r.sp-s.close), holdterm=r.q*(s.close-c5), fee=-fee,
        max5=(maxN(r.code,r.bd,5)/r.bp-1)*100 if maxN(r.code,r.bd,5) else np.nan))
E=pd.DataFrame(rows)
chk=(E.pick+E.entry+E.exit_intra+E.holdterm+E.fee).sum(); print(f"分解恒等式校验: 各项和 {chk:,.0f} vs 实际 {E.pnl.sum():,.0f}")
# 逐日累计
T2=pd.DataFrame(T); T2['d']=pd.to_datetime(T2.date.str[:4]+'-'+T2.date.str[4:6]+'-'+T2.date.str[6:])
feeday=T2.groupby('d').apply(lambda g:(g[g.side=='buy'].amount*FB).sum()+(g[g.side=='sell'].amount*FS).sum())
pnlday=E.groupby('sd').pnl.sum()
days=sorted(set(feeday.index)|set(pnlday.index))
cum_p=np.cumsum([pnlday.get(d,0) for d in days]); cum_f=np.cumsum([feeday.get(d,0) for d in days])
css=open('/Users/huaichuaibeimeng/.claude/standards/buwen.css').read()
OV="body{font-size:10px!important}h1{font-size:17px!important}h2{font-size:14px!important}h3,h4{font-size:12px!important}p,li{font-size:10px!important}table,th,td,.cap{font-size:9px!important}td.num,th.num{text-align:right}.neg{color:#2E7D46;font-weight:700}.pos{color:#C0392B;font-weight:700}svg text{font-family:-apple-system,'PingFang SC',Arial,sans-serif}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}"
H=[];A=H.append
A(f'<title>逐笔数据图</title><style>{css}\n{OV}</style><div class="container doc-numbered"><h1>实盘逐笔数据图：08/03 到 09/08</h1><div class="doc-sub">每个点、每根线都是你的一笔成交或一天。170个配对回合 + 3个未平仓lot。红=盈利 绿=亏损（A股习惯）。</div><hr class="rule-navy">')
# helper axes
def axes(W_,H_,x0,x1,y0,y1,xl,yl,xt=None,yt=None):
    s=[f'<line x1="50" y1="{H_-30}" x2="{W_-10}" y2="{H_-30}" stroke="#D8DEE6"/><line x1="50" y1="10" x2="50" y2="{H_-30}" stroke="#D8DEE6"/>']
    sx=lambda v:50+(v-x0)/(x1-x0)*(W_-60); sy=lambda v:10+(y1-v)/(y1-y0)*(H_-40)
    for v in (yt or []): s.append(f'<line x1="50" y1="{sy(v):.1f}" x2="{W_-10}" y2="{sy(v):.1f}" stroke="#EEF1F4"/><text x="46" y="{sy(v)+3:.1f}" font-size="8" fill="#8A857C" text-anchor="end">{v:g}</text>')
    for v,lab in (xt or []): s.append(f'<text x="{sx(v):.1f}" y="{H_-17}" font-size="8" fill="#8A857C" text-anchor="middle">{lab}</text>')
    s.append(f'<text x="{W_-10}" y="{H_-4}" font-size="8.5" fill="#444" text-anchor="end">{xl}</text><text x="52" y="9" font-size="8.5" fill="#444">{yl}</text>')
    return s,sx,sy
def dots(pts,sx,sy,rmin=2.2,rmax=7,cap_scale=True):
    out=[]
    for x,y,c,n,lab in pts:
        r=rmin+ (min(c,250000)/250000)*(rmax-rmin) if cap_scale else 3
        col="#C0392B" if y>0 else "#2E7D46"
        out.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="{r:.1f}" fill="{col}" fill-opacity=".55" stroke="{col}" stroke-width=".6"><title>{html.escape(lab)}</title></circle>')
    return out
# ═══ 1 日内/隔日交易
A('<h2>Day trading：一天内进出的每一笔</h2>')
one=E[E.hold<=1]; multi=E[E.hold>1]
A(f'<p>≤1个交易日进出 <span class="kw">{len(one)}笔</span>：亏损笔数 {int((one.pnl<0).sum())}（<span class="kw">亏损率 {(one.pnl<0).mean()*100:.0f}%</span>），合计 <span class="kw">{f(one.pnl.sum(),0)}元</span>，等权 {f(one.ret.mean(),2)}%。持有超过1天 {len(multi)}笔：亏损率 {(multi.pnl<0).mean()*100:.0f}%，合计 {f(multi.pnl.sum(),0)}元。</p>')
W_,H_=1100,300; d0=min(E.sd); d1=max(E.sd); xd=lambda d:(d-d0).days
s,sx,sy=axes(W_,H_,0,xd(d1)+1,-12,14,'卖出日','单笔收益 %（点大小=金额）',[(xd(d),d.strftime('%m/%d')) for d in pd.date_range(d0,d1,freq='5D')],[-10,-5,0,5,10])
s.append(f'<line x1="50" y1="{sy(0):.1f}" x2="{W_-10}" y2="{sy(0):.1f}" stroke="#444" stroke-width=".8"/>')
s+=dots([(xd(r.sd)+ (0.3 if r.hold<=1 else 0.7),max(-12,min(14,r.ret)),r.cap,r['name'],f"{r['name']} 买{r.bd.strftime('%m/%d')}卖{r.sd.strftime('%m/%d')} {r.ret:+.2f}% {r.pnl:+,.0f}元 金额{r.cap:,.0f}") for _,r in one.iterrows()],sx,sy)
s.append('<text x="60" y="24" font-size="9" fill="#444">只画≤1日的134笔；每个点一笔</text></svg>')
A('<div class="card"><svg viewBox="0 0 1100 300" width="100%">'+"".join(s)+'</div>')
# cumulative pnl day vs multi
s,sx,sy=axes(W_,240,0,xd(d1)+1,min(-15000,(np.cumsum(one.groupby('sd').pnl.sum().reindex(days,fill_value=0).values)).min()-2000),max(15000,np.cumsum(multi.groupby('sd').pnl.sum().reindex(days,fill_value=0).values).max()+2000),'日期','累计盈亏 元',[(xd(d),d.strftime('%m/%d')) for d in pd.date_range(d0,d1,freq='5D')],[-15000,-10000,-5000,0,5000,10000,15000])
for grp,col,lab in [(one,'#2E7D46','≤1日进出 累计'),(multi,'#1B3A5B','持有>1日 累计')]:
    cs=np.cumsum(grp.groupby('sd').pnl.sum().reindex(days,fill_value=0).values)
    s.append(f'<polyline fill="none" stroke="{col}" stroke-width="1.6" points="'+" ".join(f"{sx(xd(d)):.1f},{sy(v):.1f}" for d,v in zip(days,cs))+f'"/><text x="{sx(xd(days[-1]))-4:.0f}" y="{sy(cs[-1])-4:.0f}" font-size="9" fill="{col}" text-anchor="end">{lab} {cs[-1]:+,.0f}</text>')
s.append('</svg>'); A('<div class="card"><svg viewBox="0 0 1100 240" width="100%">'+"".join(s)+'</div>')
# ═══ 2 手续费
A('<h2>手续费与印花税</h2>')
tf=cum_f[-1]; A(f'<p>259笔合计 <span class="kw">{f(tf,0)}元</span>（买入0.036%，卖出0.086%含印花税）。同期已实现盈亏 {f(E.pnl.sum(),0)}元：<span class="kw">费用是已实现亏损的{tf/abs(E.pnl.sum()):.1f}倍</span>。平均每天 {f(tf/len(days),0)}元，最贵一天 {f(feeday.max(),0)}元（{feeday.idxmax().strftime("%m/%d")}）。</p>')
s,sx,sy=axes(W_,240,0,xd(d1)+1,min(cum_p.min(),-8000)-1000,max(cum_p.max(),8000)+1000,'日期','元',[(xd(d),d.strftime('%m/%d')) for d in pd.date_range(d0,d1,freq='5D')],[-8000,-4000,0,4000,8000])
s.append('<polyline fill="none" stroke="#1B3A5B" stroke-width="1.6" points="'+" ".join(f"{sx(xd(d)):.1f},{sy(v):.1f}" for d,v in zip(days,cum_p))+'"/>')
s.append('<polyline fill="none" stroke="#B7791F" stroke-width="1.6" points="'+" ".join(f"{sx(xd(d)):.1f},{sy(-v):.1f}" for d,v in zip(days,cum_f))+'"/>')
s.append(f'<text x="60" y="24" font-size="9" fill="#1B3A5B">累计已实现盈亏 {cum_p[-1]:+,.0f}</text><text x="60" y="36" font-size="9" fill="#B7791F">累计费用(负向) {-cum_f[-1]:,.0f}</text></svg>')
A('<div class="card"><svg viewBox="0 0 1100 240" width="100%">'+"".join(s)+'</div>')
# 每日费用柱
s,sx,sy=axes(W_,200,0,xd(d1)+1,0,max(feeday.max()*1.1,100),'日期','当日费用 元',[(xd(d),d.strftime('%m/%d')) for d in pd.date_range(d0,d1,freq='5D')],[0,200,400,600,800])
for d,v in feeday.items(): s.append(f'<rect x="{sx(xd(d))-4:.1f}" y="{sy(v):.1f}" width="8" height="{sy(0)-sy(v):.1f}" fill="#B7791F" opacity=".8"><title>{d.strftime("%m/%d")} {v:,.0f}元</title></rect>')
s.append('</svg>'); A('<div class="card"><svg viewBox="0 0 1100 200" width="100%">'+"".join(s)+'</div>')
# ═══ 3 追涨杀跌
A('<h2>追涨杀跌？每一笔的买入前一日涨幅 与 这笔的结果</h2>')
up=E[E.prev>5]; dn=E[E.prev<0]
A(f'<p>横轴是你买入那天的<span class="kw">前一个交易日</span>涨幅，纵轴是这笔最后赚了亏了。前一日涨超5%（追涨）{len(up)}笔：<span class="kw">{f(up.pnl.sum(),0)}元</span>，胜率{(up.pnl>0).mean()*100:.0f}%。前一日下跌（低吸）{len(dn)}笔：<span class="kw">{f(dn.pnl.sum(),0)}元</span>，胜率{(dn.pnl>0).mean()*100:.0f}%。结论：追涨不是错，低吸才是。</p>')
s,sx,sy=axes(W_,320,-12,22,-12,14,'买入前一日涨幅 %','这笔收益 %',[(v,f"{v:+d}") for v in (-10,-5,0,5,10,15,20)],[-10,-5,0,5,10])
s.append(f'<line x1="{sx(0):.1f}" y1="10" x2="{sx(0):.1f}" y2="{320-30}" stroke="#444" stroke-width=".8"/><line x1="50" y1="{sy(0):.1f}" x2="{W_-10}" y2="{sy(0):.1f}" stroke="#444" stroke-width=".8"/>')
s+=dots([(max(-12,min(22,r.prev)),max(-12,min(14,r.ret)),r.cap,r['name'],f"{r['name']} 买{r.bd.strftime('%m/%d')} 前一日{r.prev:+.1f}% 本笔{r.ret:+.2f}% {r.pnl:+,.0f}元") for _,r in E.dropna(subset=['prev']).iterrows()],sx,sy)
s.append(f'<text x="{sx(12):.0f}" y="{sy(12):.0f}" font-size="9" fill="#444">右上：追涨且赚</text><text x="{sx(-11):.0f}" y="{sy(-9):.0f}" font-size="9" fill="#444">左下：低吸且亏</text></svg>')
A('<div class="card"><svg viewBox="0 0 1100 320" width="100%">'+"".join(s)+'</div>')
A('<h3>杀跌？每一笔卖出时的盈亏 与 卖出后5日股价怎么走</h3>')
lo=E[(E.ret<0)&E.after5.notna()]; A(f'<p>横轴是你卖出时这笔的盈亏，纵轴是卖出后5个交易日股价相对你卖价的变化。亏着卖的{len(lo)}笔，卖后5日平均<span class="kw">{f(lo.after5.mean(),2)}%</span>、其中反弹超5%的{int((lo.after5>5).sum())}笔。左上角那堆就是"割在地板上"。</p>')
s,sx,sy=axes(W_,320,-12,14,-15,25,'卖出时本笔盈亏 %','卖后5日股价 %',[(v,f"{v:+d}") for v in (-10,-5,0,5,10)],[-10,0,10,20])
s.append(f'<line x1="{sx(0):.1f}" y1="10" x2="{sx(0):.1f}" y2="{320-30}" stroke="#444" stroke-width=".8"/><line x1="50" y1="{sy(0):.1f}" x2="{W_-10}" y2="{sy(0):.1f}" stroke="#444" stroke-width=".8"/>')
for _,r in E.dropna(subset=['after5']).iterrows():
    col="#C0392B" if r.after5>0 else "#2E7D46"; rr=2.2+min(r.cap,250000)/250000*4.8
    s.append(f'<circle cx="{sx(max(-12,min(14,r.ret))):.1f}" cy="{sy(max(-15,min(25,r.after5))):.1f}" r="{rr:.1f}" fill="{col}" fill-opacity=".55" stroke="{col}" stroke-width=".6"><title>{html.escape(r["name"])} 卖{r.sd.strftime("%m/%d")} 本笔{r.ret:+.2f}% 卖后5日{r.after5:+.1f}%</title></circle>')
s.append(f'<text x="{sx(-11):.0f}" y="{sy(22):.0f}" font-size="9" fill="#444">左上：亏着卖、卖完就涨（杀跌）</text></svg>')
A('<div class="card"><svg viewBox="0 0 1100 320" width="100%">'+"".join(s)+'</div>')
# ═══ 4 选股成功率
A('<h2>选股成功率（一周脉冲口径）</h2>')
B=E.dropna(subset=['max5']); hit5=(B.max5>=5).mean()*100; hit8=(B.max5>=8).mean()*100; capt=(B.ret>=5).mean()*100
A(f'<p>每笔买入后<span class="kw">5个交易日内的最高价</span>相对你的买价（横轴）与你实际拿到的（纵轴）。买入后一周内曾涨到+5%以上的 <span class="kw">{hit5:.0f}%</span>，曾到+8%以上的 <span class="kw">{hit8:.0f}%</span>；你实际拿到+5%以上的只有 <span class="kw">{capt:.0f}%</span>。对角线下方的距离就是"脉冲来了你没在"。</p>')
s,sx,sy=axes(W_,340,-5,35,-12,20,'买入后5日内最高 %','你实际拿到 %',[(v,f"{v:+d}") for v in (0,5,10,15,20,25,30)],[-10,-5,0,5,10,15])
s.append(f'<line x1="{sx(-5):.1f}" y1="{sy(-5):.1f}" x2="{sx(20):.1f}" y2="{sy(20):.1f}" stroke="#4E7CA0" stroke-dasharray="3 3"/><text x="{sx(19):.0f}" y="{sy(19)-4:.0f}" font-size="8.5" fill="#4E7CA0" text-anchor="end">对角线=全吃到</text><line x1="50" y1="{sy(0):.1f}" x2="{W_-10}" y2="{sy(0):.1f}" stroke="#444" stroke-width=".8"/><line x1="{sx(5):.1f}" y1="10" x2="{sx(5):.1f}" y2="{340-30}" stroke="#B7791F" stroke-dasharray="2 3"/>')
s+=dots([(max(-5,min(35,r.max5)),max(-12,min(20,r.ret)),r.cap,r['name'],f"{r['name']} 买{r.bd.strftime('%m/%d')} 5日内最高{r.max5:+.1f}% 实际{r.ret:+.2f}%") for _,r in B.iterrows()],sx,sy)
s.append('</svg>'); A('<div class="card"><svg viewBox="0 0 1100 340" width="100%">'+"".join(s)+'</div>')
# ═══ 5 归因瀑布
A('<h2>亏损归因：每一分钱归到哪一步</h2>')
parts=[('选股（按当日收盘买、持5日按收盘卖，股票自己给的）',E.pick.sum()),('入场时点（你买价 vs 当日收盘）',E.entry.sum()),('出场时点（你卖价 vs 当日收盘）',E.exit_intra.sum()),('持有期（卖出日收盘 vs 第5日收盘：卖早或卖晚）',E.holdterm.sum()),('费用',E.fee.sum())]
tot=sum(v for _,v in parts)
A(f'<p>恒等式分解，五项之和 = 已实现 {f(tot,0)}元，与流水完全一致。读法：股票本身在你买后5天里给了 <span class="kw">{f(E.pick.sum(),0)}元</span>；你的出场把 <span class="kw">{f(E.exit_intra.sum()+E.holdterm.sum(),0)}元</span> 交了回去；费用再拿走 {f(-E.fee.sum(),0)}元。</p>')
W2,H2=1100,260; vals=[v for _,v in parts]; cum=0; mx=max(abs(sum(vals[:i+1])) for i in range(len(vals)))*1.15
s,sx,sy=axes(W2,H2,0,len(parts)+1,-mx,mx,'','元',None,[-int(mx/2//5000*5000),0,int(mx/2//5000*5000)])
s.append(f'<line x1="50" y1="{sy(0):.1f}" x2="{W2-10}" y2="{sy(0):.1f}" stroke="#444" stroke-width=".8"/>')
for i,(lab,v) in enumerate(parts):
    x=sx(i+0.5); y0=cum; y1=cum+v; col="#C0392B" if v>0 else "#2E7D46"
    s.append(f'<rect x="{x-50:.1f}" y="{min(sy(y0),sy(y1)):.1f}" width="100" height="{abs(sy(y0)-sy(y1)):.1f}" fill="{col}" opacity=".8"/><text x="{x:.1f}" y="{min(sy(y0),sy(y1))-4:.1f}" font-size="9" fill="{col}" text-anchor="middle">{v:+,.0f}</text>')
    for k,seg in enumerate(lab.split('（')): s.append(f'<text x="{x:.1f}" y="{H2-18+k*10}" font-size="8" fill="#444" text-anchor="middle">{("（"+seg) if k else seg}</text>')
    cum=y1
x=sx(len(parts)+0.5); s.append(f'<rect x="{x-50:.1f}" y="{min(sy(0),sy(tot)):.1f}" width="100" height="{abs(sy(0)-sy(tot)):.1f}" fill="#1B3A5B" opacity=".9"/><text x="{x:.1f}" y="{min(sy(0),sy(tot))-4:.1f}" font-size="9" fill="#1B3A5B" text-anchor="middle">已实现 {tot:+,.0f}</text></svg>')
A('<div class="card"><svg viewBox="0 0 1100 260" width="100%">'+"".join(s)+'</div>')
# 每笔的分解 逐票汇总
per=E.groupby('name')[['pick','entry','exit_intra','holdterm','fee','pnl']].sum().sort_values('pnl')
A('<h3>分票归因（元）</h3><table><thead><tr><th>股票</th><th class="num">选股</th><th class="num">入场</th><th class="num">出场</th><th class="num">持有期</th><th class="num">费用</th><th class="num">已实现</th></tr></thead><tbody>')
for n,r in per.iterrows(): A(f'<tr><td>{n}</td>'+"".join(f'<td class="num {"neg" if r[k]<0 else ("pos" if r[k]>0 else "")}">{f(r[k],0)}</td>' for k in ['pick','entry','exit_intra','holdterm','fee','pnl'])+'</tr>')
A('</tbody></table>')
A('<div class="box-red"><span class="box-h">峰值37万到现在：能归因与不能归因的边界</span><p>上面全部数字只覆盖成交记录里的170个回合（已实现）和3个未平仓lot（浮动'+f(O.pnl.sum(),0)+'元）。8月1日之前建的仓——窗口内卖出的红利ETF、行云科技、牧原、海尔智家、药明康德、宁波银行（卖出额64万）和仍在持有的——成本不在截图里，从峰值到现在的其余差额落在这里。补一张8/1前持仓成本或账户资产曲线截图，这一块可以同样逐笔归因。</p></div>')
A('</div>')
out="".join(H); p='/Users/huaichuaibeimeng/claude-projects/trading-journal/output/逐笔数据图.html'; open(p,'w').write(out); print("写入",p,len(out)//1024,"KB")
print(f"日内{len(one)}笔亏损率{(one.pnl<0).mean()*100:.0f}% {one.pnl.sum():+,.0f} | 费用{tf:,.0f} | 追涨{len(up)}笔{up.pnl.sum():+,.0f} 低吸{len(dn)}笔{dn.pnl.sum():+,.0f} | 5日内曾+5%:{hit5:.0f}% +8%:{hit8:.0f}% 实拿+5%:{capt:.0f}%")
print("归因:",[(l.split('（')[0],round(v)) for l,v in parts])
