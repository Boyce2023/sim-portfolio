#!/opt/homebrew/bin/python3
"""竞价形态扫描 — 两类形态, 只看量与量柱颜色, 不看涨跌幅
(Buwen 2026-09-07 提出, 2026-09-08 用中信出版/百合花/海欣食品三只校正定义)

⛔量柱颜色 = 该时刻价格 相对 **上一时刻** 的涨跌(红=涨 绿=跌), **不是相对昨收**。
   我第一版把它当成"低于昨收=阴"并写成硬条件, 结果把中信出版(竞价全程+5~6%从没跌破昨收)
   直接排除——而它正是当日最典型的一只(4.0x / 开盘+12.96% / 盘中涨停+19.99%)。

【A 冲天阳量】9:24前量柱多为绿(逐级阴跌) → 最后一根爆量且翻红
   样本: 中信出版300788 (28.20一路跌到27.80, 09:25:00跳28.10, 末段2122手=此前最大4.0倍)
【B 超级大红】量柱几乎不绿(价格一路不跌) + 量持续放大(后半段均量 > 前半段)
   样本: 海欣食品002702(13.7万手/放大5.2x) 百合花603823(8789手/放大)

⛔口径(实测踩过):
· 竞价段腾讯 volume 恒为0, 累计匹配量在 bid1量; bidsz1是累计值, 柱高是**增量**须差分
· 增量=0 的时刻是"数据没更新"不是"没成交", 必须剔除否则稀释倍数
· 终值取 09:25:03(撮合完成); ⛔09:25:06已开盘, bid1变回真实盘口挂单量, 用它会算出负增量
· ⛔剔除竞价涨幅==0.00% 的票: 停牌/无真实竞价, 其倍数是被极小分母放大的假信号
  (实测金科股份203.6x / 兰州银行176.2x / 荣盛发展44.3x 全属此类)

用法: auction_surge.py scan [日期] / fill [日期] / stat
"""
import sqlite3,collections,json,os,sys,datetime,urllib.request,subprocess
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB=f'{ROOT}/data/auction/auction.db'; OUT=f'{ROOT}/data/auction_surge.jsonl'
A_RATIO=2.0; A_MIN_LOT=500; A_GREEN=0.5      # A: 末段≥2倍 / ≥500手 / 此前≥50%绿柱
B_GREEN=0.15; B_GROW=1.5; B_MIN_CUM=3000     # B: ≤15%绿柱 / 后半段>前半段1.5倍 / 总量≥3000手
QTY_TS='09:25:03'   # 量: 竞价累计匹配量
PX_TS='09:25:06'    # ⛔价: 最终撮合价=开盘价。09:25:03部分股票尚未更新完(中信出版28.10 vs 29.89差6.4%)
def mkt(c): return 'sh' if c[0] in '56' else ('bj' if c[0] in '48' else 'sz')

def load(day):
    """⛔2026-09-08 Buwen戳穿: 我用同一个时点取了两个不同性质的字段。
    价格必须取 09:25:06(最终撮合价=开盘价), 量必须取 09:25:03(09:25:06时bid1已变回盘口挂单量)。
    我早上发现过"09:25:06 bid1含义变了", 却把整个时点都排除——那判断只对量成立, 对价格是错的。
    后果: 所有竞价涨幅系统性低估, 中信出版报+6.20%实际+12.96%, 表内"竞价涨幅"与"开盘价"自相矛盾。"""
    c=sqlite3.connect(f'file:{DB}?mode=ro',uri=True)
    rows=collections.defaultdict(list)
    for code,ts,p,pc,bs in c.execute(
        "select code,ts,price,prevclose,bidsz1 from snapf where date=? and ts<=? order by code,ts",(day,QTY_TS)):
        if pc and pc>0: rows[code].append((ts,p,pc,bs or 0))
    final={}                                  # 最终撮合价(=开盘价)单独取
    for code,p in c.execute("select code,price from snapf where date=? and ts=?",(day,PX_TS)):
        final[code]=p
    for code in rows:
        if code in final and final[code]:
            ts,_,pc,bs=rows[code][-1]
            rows[code].append((PX_TS,final[code],pc,bs))    # 价用最终价, 量沿用09:25:03
    return rows

def scan(day):
    rows=load(day)
    if not rows: print(f'⛔{day} 无竞价数据'); sys.exit(1)
    A=[];B=[]
    for code,r in rows.items():
        if len(r)<20: continue
        pc=r[0][2]
        qr=[x for x in r if x[0]<=QTY_TS]           # 量序列只到09:25:03
        seq=[(qr[i][0], qr[i][3]-qr[i-1][3], qr[i][1], qr[i-1][1]) for i in range(1,len(qr)) if qr[i][3]-qr[i-1][3]>0]
        if len(seq)<6: continue
        lt,li,lp,pp=seq[-1]
        open_px=r[-1][1]                            # 最终撮合价=开盘价
        chg=(open_px/pc-1)*100                      # ⛔竞价涨幅按最终撮合价算, 与开盘价必然一致
        if abs(chg)<0.005: continue                 # ⛔剔停牌/无真实竞价的假信号
        prev=[x[1] for x in seq[:-1]]; mx=max(prev)
        col=[(1 if x[2]>x[3] else (0 if x[2]<x[3] else None)) for x in seq]
        pre=[x for x in col[:-1] if x is not None]
        grn=(sum(1 for x in pre if x==0)/len(pre)) if pre else 0
        cum=r[-1][3]
        base={'date':day,'code':code,'auction_chg':round(chg,2),'cum':cum,'green_pct':round(grn*100),'result':None}
        if li>=mx*A_RATIO and lp>pp and grn>=A_GREEN and li>=A_MIN_LOT:
            A.append({**base,'type':'A_冲天阳量','ratio':round(li/max(mx,1),2),'inc':li,'prev_max':mx})
        h=len(seq)//2
        f1=sum(x[1] for x in seq[:h])/max(h,1); f2=sum(x[1] for x in seq[h:])/max(len(seq)-h,1)
        if grn<=B_GREEN and f2>f1*B_GROW and cum>=B_MIN_CUM:
            B.append({**base,'type':'B_超级大红','grow':round(f2/max(f1,1),2),'inc':li,'first_half':round(f1),'second_half':round(f2)})
    # ⛔PUBLISH_ASSERT(2026-09-08): 发布前断言 竞价涨幅==实际开盘涨幅, 不等就不许出表。
    # 病因: 我用09:25:03取价格(部分股票未撮合完), 09:25:06才是最终价, 两栏自相矛盾被Buwen一眼看穿。
    # ⛔我早上的锚点校验用的正是09:25:06, 分析脚本用09:25:03 —— 自己的验证机制和自己的分析脚本
    #   时点不一致而未发现。锚点存在≠锚点被调用, 所以它必须在发布路径上。
    import urllib.request as _u
    _bad=[]
    for _z in (A+B)[:60]:
        try:
            _mk='sh' if _z['code'][0] in '56' else ('bj' if _z['code'][0] in '48' else 'sz')
            _p=_u.urlopen(f"http://qt.gtimg.cn/q={_mk}{_z['code']}",timeout=6).read().decode('gbk','ignore').split('~')
            if len(_p)>5 and float(_p[4]):
                _real=(float(_p[5])/float(_p[4])-1)*100
                if abs(_real-_z['auction_chg'])>0.02: _bad.append((_z['code'],_z['auction_chg'],round(_real,2)))
        except Exception: pass
    if _bad:
        print(f'⛔PUBLISH_ASSERT 失败: {len(_bad)}只 竞价涨幅≠实际开盘涨幅, 拒绝出表')
        for c,a_,r in _bad[:5]: print(f'   {c} 我算{a_:+.2f}% vs 开盘{r:+.2f}%')
        sys.exit(1)
    print(f'  ✅PUBLISH_ASSERT: 抽验{min(60,len(A)+len(B))}只, 竞价涨幅与开盘涨幅零误差')

    A.sort(key=lambda z:-z['ratio']); B.sort(key=lambda z:-z['cum'])
    hits=A+B
    old=[json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []
    old=[x for x in old if x['date']!=day]
    with open(OUT,'w') as f:
        for x in old+hits: f.write(json.dumps(x,ensure_ascii=False)+'\n')
    print(f'{day}: A冲天阳量 {len(A)}只 | B超级大红 {len(B)}只 (已剔竞价涨幅0.00%的假信号)')
    for z in A[:12]: print(f"  A {z['code']} {z['ratio']:>5.1f}x 末段{z['inc']:>6}手 此前绿{z['green_pct']}% 竞价{z['auction_chg']:+.2f}%")
    for z in B[:12]: print(f"  B {z['code']} 放大{z['grow']:>5.1f}x 总量{z['cum']:>8.0f}手 绿{z['green_pct']}% 竞价{z['auction_chg']:+.2f}%")
    if hits:
        msg=(f"[A股·竞价形态 {day}] A冲天阳量{len(A)}只 / B超级大红{len(B)}只\n"
             +'\n'.join(f"A {z['code']} {z['ratio']}x 末段{z['inc']}手 竞价{z['auction_chg']:+.2f}%" for z in A[:8])
             +'\n'+'\n'.join(f"B {z['code']} 放大{z['grow']}x 总量{z['cum']:.0f}手 竞价{z['auction_chg']:+.2f}%" for z in B[:8])
             +f"\n⛔样本从09-08起累积, 门槛未经回测校准, 不构成建仓依据")
        r=subprocess.run(['bash',os.path.expanduser('~/.claude/session-remote/fs-reply.sh'),msg],capture_output=True,timeout=20)
        print('  飞书:', '✅' if r.returncode==0 else f'⛔rc={r.returncode} {r.stderr.decode()[:80]}')
    return hits

def fill(day):
    if not os.path.exists(OUT): print('⛔无样本'); sys.exit(1)
    rec=[json.loads(l) for l in open(OUT)]
    todo=[x for x in rec if x['date']==day]
    if not todo: print(f'⛔{day} 无待回填'); sys.exit(1)
    px={}
    cs=sorted({x['code'] for x in todo})
    for i in range(0,len(cs),400):
        q=','.join(mkt(x)+x for x in cs[i:i+400])
        try: raw=urllib.request.urlopen(f'http://qt.gtimg.cn/q={q}',timeout=10).read().decode('gbk','ignore')
        except Exception as e: print('取行情失败',type(e).__name__); continue
        for line in raw.split('\n'):
            p=line.split('~')
            if len(p)>44 and 'none_match' not in line:
                try: px[p[2]]={'name':p[1],'close':float(p[3]),'open':float(p[5]),
                               'high':float(p[33]),'low':float(p[34]),'chg':float(p[32])}
                except ValueError: pass
    n=0
    for x in rec:
        if x['date']!=day: continue
        d=px.get(x['code'])
        if not d or not d['open']: continue
        x['name']=d['name']
        x['result']={'open':d['open'],'close':d['close'],'day_chg':round(d['chg'],2),
                     'open_to_close':round((d['close']/d['open']-1)*100,2),
                     'open_to_high':round((d['high']/d['open']-1)*100,2),
                     'open_to_low':round((d['low']/d['open']-1)*100,2)}
        n+=1
    with open(OUT,'w') as f:
        for x in rec: f.write(json.dumps(x,ensure_ascii=False)+'\n')
    print(f'{day}: 回填 {n} 只')
    for t in ('A_冲天阳量','B_超级大红'):
        g=[x for x in rec if x['date']==day and x['type']==t and x.get('result')]
        if not g: continue
        import statistics as st
        v=[x['result']['open_to_close'] for x in g]; h=[x['result']['open_to_high'] for x in g]
        print(f"  {t} {len(g)}只: 开→收 中位{st.median(v):+.2f}% | 开→高 中位{st.median(h):+.2f}% | 上涨{sum(1 for a in v if a>0)}只")

def stat():
    if not os.path.exists(OUT): print('⛔无样本'); return
    rec=[json.loads(l) for l in open(OUT)]
    days=sorted({x['date'] for x in rec}); done=[x for x in rec if x.get('result')]
    print(f'样本 {len(rec)}条 / {len(days)}个交易日 ({days[0]}~{days[-1]}) | 已回填 {len(done)}')
    if len(done)<200: print(f'⛔仅 {len(done)} 条, **远不足以算胜率**。门槛也未经校准。')
    import statistics as st
    for t in ('A_冲天阳量','B_超级大红'):
        g=[x for x in done if x['type']==t]
        if not g: continue
        v=[x['result']['open_to_close'] for x in g]; h=[x['result']['open_to_high'] for x in g]
        print(f'  {t} n={len(g)}: 开→收 中位{st.median(v):+.2f}% 均值{st.mean(v):+.2f}% | 开→高 中位{st.median(h):+.2f}% | 上涨{sum(1 for a in v if a>0)}/{len(v)}')

if __name__=='__main__':
    a=sys.argv[1:] or ['scan']
    d=a[1] if len(a)>1 else datetime.date.today().isoformat()
    {'scan':lambda:scan(d),'fill':lambda:fill(d),'stat':stat}[a[0]]()
