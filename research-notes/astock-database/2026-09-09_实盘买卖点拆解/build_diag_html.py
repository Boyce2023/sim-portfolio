# -*- coding: utf-8 -*-
import pandas as pd,numpy as np,json,sqlite3,html
D=pd.read_pickle('/tmp/dhbr/diag_rt.pkl'); O=pd.read_pickle('/tmp/dhbr/diag_open.pkl'); X=pd.read_pickle('/tmp/dhbr/diag_stock.pkl'); W=pd.read_pickle('/tmp/dhbr/diag_whipsaw.pkl')
T=json.load(open('/tmp/dhbr/buwen_trades_all.json'))
con=sqlite3.connect('/tmp/dhbr/exit_bars.db'); K=pd.read_sql("select code,date,open,high,low,close from k",con); K['date']=pd.to_datetime(K['date']); K=K.sort_values(['code','date'])
bars={c:g.reset_index(drop=True) for c,g in K.groupby('code')}
def f(x,d=1):
    try:
        if x!=x: return ''
    except: return ''
    return ('−' if x<0 else '')+f"{abs(x):,.{d}f}"
def dt(d): return pd.Timestamp(d).strftime('%m/%d')
css=open('/Users/huaichuaibeimeng/.claude/standards/buwen.css').read()
OV="body{font-size:10px!important}h1{font-size:17px!important}h2{font-size:14px!important}h3,h4{font-size:12px!important}p,li{font-size:10px!important}table,th,td,.cap{font-size:9px!important}td.num,th.num{text-align:right}.neg{color:#2E7D46;font-weight:700}.pos{color:#C0392B;font-weight:700}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}svg text{font-family:-apple-system,'PingFang SC',Arial,sans-serif}details summary{cursor:pointer;color:#1B3A5B;font-weight:700}"
H=[];A=H.append
A(f'<title>买卖点拆解</title><style>{css}\n{OV}</style><div class="container doc-numbered"><h1>8月到9月实盘：买卖点与亏损拆解</h1><div class="doc-sub">中金财富账户成交 2026/08/03 到 09/08 · 259笔 · 54只 · 170个配对回合 · 日线为新浪前复权 · 费用按买入3.6bp卖出8.6bp计 · 2026/09/09</div><hr class="rule-navy">')
real=D.pnl.sum(); flo=O.pnl.sum(); fees=(D.cap*0.00036+D.sp*D.q*0.00086).sum()
a=D[D.auction_sell]; auc_alt=((a.sp/(1+a.exit_vs_close/100))*(1-0.00086)*a.q-a.bp*(1+0.00036)*a.q).sum()
one=D[D.same_or_next_day]; multi=D[~D.same_or_next_day]
whip=W[W['回买贵%']>0]['损失元'].sum()
h5=D.hold5.dropna(); h5_yuan=(D.cap*(D.hold5.fillna(D.ret))/100).sum()
A('<div class="box-navy"><span class="box-h">结论</span><ul>'
 f'<li><span class="lead-in">总账：</span>窗口内可配对的170个回合已实现<span class="kw">{f(real,0)}元</span>，3个未平仓lot浮动{f(flo,0)}元，合计{f(real+flo,0)}元；周转320万，费用{f(fees,0)}元。8月前建仓、窗口内卖出的6只（红利ETF、行云科技、牧原、海尔、药明、宁波银行，卖出额64万）成本不在成交记录里，不计入。</li>'
 f'<li><span class="lead-in">"股在涨"只对了一半：</span>49只里到09/08仍高于你首买日收盘的只有20只，中位<span class="kw">−1.6%</span>；但期内最高点中位<span class="kw">+8.3%</span>。它们是一周内的脉冲，不是趋势。你的持有期均1.4个交易日，和脉冲对不上。</li>'
 f'<li><span class="lead-in">选股不是亏损来源：</span>同样的买点持有5个交易日，等权<span class="kw">+{f(h5.mean(),2)}%</span>；按你的实际仓位折算约<span class="kw">{f(h5_yuan,0)}元</span>。你实际做到+0.17%。</li>'
 f'<li><span class="lead-in">钱丢在四个执行动作上：</span>①09:25集合竞价卖出13笔{f(a.pnl.sum(),0)}元，改当日收盘卖是{f(auc_alt,0)}元，差<span class="kw">{f(a.pnl.sum()-auc_alt,0)}元</span>；②一天内进出134笔{f(one.pnl.sum(),0)}元，持有超过一天的36笔{f(multi.pnl.sum(),0)}元；③卖了又买回、买回更贵18次，多付<span class="kw">{f(whip,0)}元</span>；④单票超过15万的3笔{f(D[D.cap>150000].pnl.sum(),0)}元，仓位最大的地方亏得最多。</li>'
 '<li><span class="lead-in">最反直觉的一条：</span>你追涨的单子在赚钱，低吸的单子在亏钱。买入前一日涨超5%的32笔+24,043元（等权+2.38%），前一日涨停的11笔+23,521元；买入前一日下跌的70笔<span class="kw">−37,751元</span>（−1.39%）。你的优势在动量入场，漏在"跌了去接"。</li></ul></div>')
# ── 1 五方面
A('<h2>从五个方面看错在哪一步</h2>')
A('<table><thead><tr><th>方面</th><th>数据</th><th>判定</th></tr></thead><tbody>'
 f'<tr><td>选股</td><td>买入后持5日等权+{f(h5.mean(),2)}%，持有窗口内股票自身+{f(D.stock_c2c.mean(),2)}%；但拿到09/08为{f(D.to_now.mean(),2)}%（胜率{(D.to_now>0).mean()*100:.0f}%）</td><td>一周内有肉，两三周没有。选的是脉冲股，不是趋势股，本身没错，但决定了持有期必须短而不是极短</td></tr>'
 f'<tr><td>入场时点</td><td>买价相对当日收盘{f(D.entry_vs_close.mean(),2)}%，买在当日振幅的{D.entry_pos.mean():.0f}分位；10点档买入14笔{f(D[D.hour=="10"].pnl.sum(),0)}元（−2.81%），09点档24笔+1.63%</td><td>日内位置中性；问题在"哪种日子买"：跌后接的亏、涨后追的赚</td></tr>'
 f'<tr><td>出场时点</td><td>卖价相对当日收盘{f(D.exit_vs_close.mean(),2)}%；卖出后5日股价均值{f(D.after5.mean(),2)}%，亏损单卖出后反弹{f(D[D.ret<0].after5.mean(),2)}%；卖飞（卖后5日涨超5%）47笔 vs 卖对43笔；集合竞价卖出13笔{f(a.pnl.sum(),0)}元</td><td><span class="kw-red">主要亏损点</span>。卖在低点，尤其是隔夜跌了往09:25竞价里砸</td></tr>'
 f'<tr><td>持有期</td><td>均1.4个交易日；≤1日134笔{f(one.pnl.sum(),0)}元，&gt;1日36笔{f(multi.pnl.sum(),0)}元；5日规则+{f(h5.mean(),2)}%</td><td><span class="kw-red">主要亏损点</span>。一日游把脉冲切在启动那一段</td></tr>'
 f'<tr><td>仓位</td><td>&lt;3万107笔{f(D[D.cap<=30000].pnl.sum(),0)}元；3到8万53笔{f(D[(D.cap>30000)&(D.cap<=80000)].pnl.sum(),0)}元；&gt;15万3笔{f(D[D.cap>150000].pnl.sum(),0)}元</td><td><span class="kw-red">主要亏损点</span>。重仓的三笔全是隔天割的：佳禾、海南橡胶、云南旅游</td></tr>'
 f'<tr><td>频率与成本</td><td>25个交易日259笔，费用{f(fees,0)}元；回买更贵18次多付{f(whip,0)}元</td><td>两项合计约两万，超过总亏损本身</td></tr></tbody></table>')
# ── 2 集合竞价
A('<h2>09:25集合竞价卖出13笔</h2><table><thead><tr><th>股票</th><th>日期</th><th class="num">卖价</th><th class="num">当日开</th><th class="num">当日收</th><th class="num">卖价vs收</th><th class="num">次日收</th><th class="num">盈亏</th></tr></thead><tbody>')
for _,r in a.sort_values('pnl').iterrows():
    s=bars[r.code]; sd=s[s.date==r.sd].iloc[0]; nx=s[s.date>r.sd].head(1)
    A(f'<tr><td>{r["name"]}</td><td>{dt(r.sd)}</td><td class="num">{r.sp:.3f}</td><td class="num">{sd.open:.2f}</td><td class="num">{sd.close:.2f}</td><td class="num {"neg" if r.exit_vs_close<0 else ""}">{f(r.exit_vs_close)}%</td><td class="num">{(nx.close.iloc[0] if len(nx) else float("nan")):.2f}</td><td class="num {"neg" if r.pnl<0 else "pos"}">{f(r.pnl,0)}</td></tr>')
A(f'</tbody></table><p>海南橡胶08/26两笔：竞价6.00卖出，当日收6.56，09/08收8.30，从你首买日算+28.8%，你在它身上实现−10,689元。</p>')
# ── 3 追涨vs低吸
A('<h2>追涨与低吸</h2>')
grp=[('前一日涨停(>9.5%)',D.prev>9.5),('前一日涨5%到9.5%',(D.prev>5)&(D.prev<=9.5)),('前一日涨0到5%',(D.prev>0)&(D.prev<=5)),('前一日跌0到3%',(D.prev<=0)&(D.prev>-3)),('前一日跌超3%',D.prev<=-3)]
A('<table style="max-width:640px"><thead><tr><th>买入前一日</th><th class="num">笔数</th><th class="num">盈亏(元)</th><th class="num">等权</th><th class="num">胜率</th></tr></thead><tbody>')
for lab,m in grp:
    q=D[m]; A(f'<tr><td>{lab}</td><td class="num">{len(q)}</td><td class="num {"neg" if q.pnl.sum()<0 else "pos"}">{f(q.pnl.sum(),0)}</td><td class="num">{f(q.ret.mean(),2)}%</td><td class="num">{(q.ret>0).mean()*100:.0f}%</td></tr>')
A('</tbody></table>')
# ── 4 回买
A('<h2>卖了又买回</h2><table><thead><tr><th>股票</th><th>卖日</th><th class="num">卖价</th><th>回买日</th><th class="num">回买价</th><th class="num">回买贵</th><th class="num">量</th><th class="num">多付(元)</th></tr></thead><tbody>')
for _,r in W.sort_values('损失元',ascending=False).iterrows():
    A(f'<tr><td>{r["name"]}</td><td>{r["卖日"][4:6]}/{r["卖日"][6:]}</td><td class="num">{r["卖价"]:.3f}</td><td>{r["回买日"][4:6]}/{r["回买日"][6:]}</td><td class="num">{r["回买价"]:.3f}</td><td class="num">{f(r["回买贵%"])}%</td><td class="num">{int(r["量"])}</td><td class="num">{f(r["损失元"],0)}</td></tr>')
A('</tbody></table>')
# ── 5 分票总表
A('<h2>分票：从首买到09/08的走势与你的结果</h2><table><thead><tr><th>股票</th><th>首买日</th><th class="num">至09/08</th><th class="num">期内最高</th><th class="num">回合</th><th class="num">已实现(元)</th></tr></thead><tbody>')
per=D.groupby('name').size()
for _,r in X.iterrows():
    A(f'<tr><td>{r["name"]}</td><td>{r["首买日"][5:]}</td><td class="num {"pos" if r["至09-08%"]>0 else "neg"}">{f(r["至09-08%"])}%</td><td class="num">+{f(r["期内最高%"])}%</td><td class="num">{per.get(r["name"],0)}</td><td class="num {"neg" if r["你的已实现元"]<0 else "pos"}">{f(r["你的已实现元"],0)}</td></tr>')
A('</tbody></table>')
# ── 6 逐票买卖点+走势
A('<h2>每只票的买卖点与走势</h2><p>线为收盘价（07/20 到 09/08），▲买 ▼卖，标签为价格。表为该票全部成交。</p>')
order=X.sort_values('你的已实现元').name.tolist()
name2code={t['name']:t['code'] for t in T}
for nm in order+[n for n in O.name if n not in order]:
    c=name2code[nm]; g=bars.get(c)
    if g is None: continue
    g=g[g.date>=pd.Timestamp('2026-07-20')].reset_index(drop=True)
    tr=[t for t in T if t['code']==c]
    lo,hi=g.low.min(),g.high.max(); pad=(hi-lo)*0.12 or 1; lo-=pad; hi+=pad
    Wd,Ht=560,150; xs=lambda i:40+i/(len(g)-1)*(Wd-60); ys=lambda p:15+(hi-p)/(hi-lo)*(Ht-35)
    pts=" ".join(f"{xs(i):.1f},{ys(p):.1f}" for i,p in enumerate(g.close))
    svg=[f'<svg viewBox="0 0 {Wd} {Ht}" width="100%" style="max-width:{Wd}px"><polyline points="{pts}" fill="none" stroke="#1B3A5B" stroke-width="1.4"/>']
    for k,d in enumerate(g.date):
        if d.day in (1,11,21) or k==0: svg.append(f'<text x="{xs(k):.0f}" y="{Ht-4}" font-size="8" fill="#8A857C" text-anchor="middle">{d.strftime("%m/%d")}</text>')
    svg.append(f'<text x="4" y="18" font-size="8" fill="#8A857C">{hi-pad:.2f}</text><text x="4" y="{Ht-22}" font-size="8" fill="#8A857C">{lo+pad:.2f}</text>')
    didx={d:i for i,d in enumerate(g.date)}
    for t in tr:
        d=pd.Timestamp(f"{t['date'][:4]}-{t['date'][4:6]}-{t['date'][6:]}")
        if d not in didx: continue
        x=xs(didx[d]); y=ys(t['price'])
        if t['side']=='buy': svg.append(f'<polygon points="{x:.1f},{y+7:.1f} {x-4:.1f},{y+14:.1f} {x+4:.1f},{y+14:.1f}" fill="#C0392B"/><text x="{x:.1f}" y="{y+22:.1f}" font-size="7" fill="#C0392B" text-anchor="middle">{t["price"]:.2f}</text>')
        else: svg.append(f'<polygon points="{x:.1f},{y-7:.1f} {x-4:.1f},{y-14:.1f} {x+4:.1f},{y-14:.1f}" fill="#2E7D46"/><text x="{x:.1f}" y="{y-16:.1f}" font-size="7" fill="#2E7D46" text-anchor="middle">{t["price"]:.2f}</text>')
    svg.append('</svg>')
    rec=X[X.name==nm]; s1=f"至09/08 {f(rec['至09-08%'].iloc[0])}% · 期内最高 +{f(rec['期内最高%'].iloc[0])}% · 已实现 {f(rec['你的已实现元'].iloc[0],0)}元" if len(rec) else ""
    A(f'<h3>{nm} {c}</h3><p class="cap">{s1}</p><div class="grid2"><div class="card">'+"".join(svg)+'</div><div><table><thead><tr><th>日期</th><th>时间</th><th>方向</th><th class="num">价</th><th class="num">量</th><th class="num">金额</th></tr></thead><tbody>')
    for t in tr: A(f'<tr><td>{t["date"][4:6]}/{t["date"][6:]}</td><td>{t["time"][:5]}</td><td class="{"pos" if t["side"]=="buy" else "neg"}">{"买" if t["side"]=="buy" else "卖"}</td><td class="num">{t["price"]:.3f}</td><td class="num">{t["qty"]}</td><td class="num">{t["amount"]:,.0f}</td></tr>')
    A('</tbody></table></div></div>')
A('<h2>附：口径与边界</h2><ul><li>成交来自你的中金账户截图（08/03到08/26由research2录入，08/24到09/08由本次十张截图录入，重叠段去重，全部价×量与成交额核对无误）。</li><li>配对按先进先出；只有卖出没有买入的6只（8月前的仓）不计入；未平仓按09/08收盘计浮动。</li><li>"若持5日"为买入后第5个交易日收盘卖出，含费用；"卖后5日"为卖出价到第5个交易日收盘。</li><li>数据与程序：/tmp/dhbr/（buwen_trades_all.json 为合并后的完整成交，可交给research2并入月度复盘）。</li></ul></div>')
out="".join(H); p='/Users/huaichuaibeimeng/claude-projects/trading-journal/output/买卖点拆解.html'
open(p,'w').write(out); print("写入",p,len(out)//1024,"KB")
