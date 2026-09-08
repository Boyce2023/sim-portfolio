#!/opt/homebrew/bin/python3
"""竞价"冲天阳量"形态 — 每日提取 + 收盘回填
形态(Buwen 提出, 截图万向德农600371; 2026-09-08 用中信出版300788 校正定义):
  ①末段增量 > 此前所有时刻增量最大值 × RATIO_MIN(量突然冲天)
  ②末段价格 > 上一时刻价格(那一刻向上跳)
  ③竞价涨幅 ≥ CHG_MIN(已有明显涨幅=资金在抢, 不是小票微动)
  ④剔一字板/竞价涨停(那不是"最后一刻"形态)

⛔我第一版把形态做错了, 记下来别再犯: Buwen 原话"9:24是阴量, 9:25忽然冲天阳量",
  我把"阴/阳"理解成**价格低于/高于昨收**并写成硬条件(9:24前阴占比≥60%)。
  实际那是**量柱相对上一刻的涨跌着色**。中信出版竞价全程 +5~6% 从没跌破昨收,
  被我那条件直接排除——而它才是当日最典型的一只(4.0x, 开盘+12.96%, 盘中涨停+19.99%)。
  旧定义筛出的9只竞价涨幅全在+0.22%~+1.44%(小票微动), 开→收中位约0;
  新定义筛出的9只开→现中位+2.04%/开→最高中位+3.68%, 6涨3跌。**核心是量突变+价上跳, 与昨收无关。**

⛔口径要点(2026-09-08 实测, 踩过才知道):
· 竞价段腾讯 volume 字段**恒为0**, 累计匹配量在 bid1量/ask1量 上
· bidsz1 是**累计**量单调递增, 图上那根冲天柱是**增量**, 必须逐时刻差分
· 终值取 **09:25:03**(撮合完成)。⛔09:25:06 已开盘, bid1 含义变回真实盘口挂单量,
  用它会算出负增量(实测中信银行 -1082)
· 样本从 2026-09-08 起逐日累积; 之前的竞价历史因 iFinD 高频额度耗尽已永久滑走

用法: auction_surge.py scan [日期]     提取当日形态股, 写 data/auction_surge.jsonl
      auction_surge.py fill [日期]     回填当日表现(开盘→收盘/最高/最低)
      auction_surge.py stat            汇总已积累样本
"""
import sqlite3,collections,json,os,sys,datetime,urllib.request
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB=f'{ROOT}/data/auction/auction.db'; OUT=f'{ROOT}/data/auction_surge.jsonl'
MIN_LOT=200; RATIO_MIN=2.0; CHG_MIN=3.0; END_TS='09:25:03'   # 门槛暂定, 待样本积累后校准
def mkt(c): return 'sh' if c[0] in '56' else ('bj' if c[0] in '48' else 'sz')

def scan(day):
    c=sqlite3.connect(f'file:{DB}?mode=ro',uri=True)
    rows=collections.defaultdict(list)
    for code,ts,p,pc,bs in c.execute(
        "select code,ts,price,prevclose,bidsz1 from snapf where date=? and ts<=? order by code,ts",(day,END_TS)):
        if pc and pc>0: rows[code].append((ts,p,pc,bs or 0))
    if not rows: print(f'⛔{day} 无竞价数据, 无法提取'); sys.exit(1)
    hits=[]
    for code,r in rows.items():
        if len(r)<20: continue
        pc=r[0][2]
        # 只取真正有增量的时刻: 增量为0是"数据没更新"不是"没成交", 混进来会稀释倍数
        seq=[]
        for i in range(1,len(r)):
            d=r[i][3]-r[i-1][3]
            if d>0: seq.append((r[i][0],d,r[i][1],r[i-1][1]))
        if len(seq)<5: continue
        last_ts,li,last_p,prev_p=seq[-1]
        prev=[x[1] for x in seq[:-1]]
        if not prev: continue
        mx=max(prev); ratio=li/max(mx,1)
        chg=(last_p/pc-1)*100
        lim=19.9 if code[:2] in ('30','68') else 9.9
        if ratio>=RATIO_MIN and last_p>prev_p and chg>=CHG_MIN and chg<lim-0.2 and li>=MIN_LOT:
            hits.append({'date':day,'code':code,'ratio':round(ratio,2),'inc':li,'prev_max':mx,
                         'auction_chg':round(chg,2),'last_jump':round((last_p/prev_p-1)*100,2),
                         'auction_px':last_p,'prevclose':pc,'cum':r[-1][3],'result':None})
    hits.sort(key=lambda x:-x['ratio'])
    old=[json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []
    old=[x for x in old if x['date']!=day]
    with open(OUT,'w') as f:
        for x in old+hits: f.write(json.dumps(x,ensure_ascii=False)+'\n')
    print(f'{day}: 命中 {len(hits)} 只 (末段量≥{RATIO_MIN}倍此前最大 / 末刻上跳 / 竞价涨幅≥{CHG_MIN}%)')
    for h in hits: print(f"  {h['code']} {h['ratio']:>5.1f}x 增{h['inc']:>6}手 末刻跳{h['last_jump']:>+5.2f}% 竞价{h['auction_chg']:>+6.2f}%")
    if hits:
        import subprocess
        top=[h for h in hits if h['ratio']>=3.0]
        msg=(f"[A股·竞价冲天阳量 {day}] 命中{len(hits)}只(其中≥3倍{len(top)}只):\n"
             + '\n'.join(f"{h['code']} {h['ratio']}x 竞价{h['auction_chg']:+.2f}% 末段{h['inc']}手" for h in hits[:12])
             + f"\n⛔样本仅从09-08起累积, 门槛({RATIO_MIN}倍/{CHG_MIN}%/{MIN_LOT}手)是拍的, 未经回测校准, 不构成建仓依据")
        r=subprocess.run(['bash',os.path.expanduser('~/.claude/session-remote/fs-reply.sh'),msg],
                         capture_output=True,timeout=20)
        print('  飞书推送:', '✅' if r.returncode==0 else f'⛔失败rc={r.returncode}')
    return hits

def fill(day):
    if not os.path.exists(OUT): print('⛔无样本'); sys.exit(1)
    rec=[json.loads(l) for l in open(OUT)]
    todo=[x for x in rec if x['date']==day]
    if not todo: print(f'⛔{day} 无待回填样本'); sys.exit(1)
    q=','.join(mkt(x['code'])+x['code'] for x in todo)
    raw=urllib.request.urlopen(f'http://qt.gtimg.cn/q={q}',timeout=10).read().decode('gbk','ignore')
    px={}
    for line in raw.split('\n'):
        p=line.split('~')
        if len(p)>44 and 'none_match' not in line:
            px[p[2]]={'name':p[1],'close':float(p[3]),'open':float(p[5]),
                      'high':float(p[33]),'low':float(p[34]),'chg':float(p[32])}
    n=0
    for x in rec:
        if x['date']!=day: continue
        d=px.get(x['code'])
        if not d or not d['open']: continue
        x['name']=d['name']
        x['result']={'open':d['open'],'close':d['close'],'high':d['high'],'low':d['low'],
                     'day_chg':round(d['chg'],2),
                     'open_to_close':round((d['close']/d['open']-1)*100,2),
                     'open_to_high':round((d['high']/d['open']-1)*100,2),
                     'open_to_low':round((d['low']/d['open']-1)*100,2)}
        n+=1
    with open(OUT,'w') as f:
        for x in rec: f.write(json.dumps(x,ensure_ascii=False)+'\n')
    print(f'{day}: 回填 {n} 只')
    for x in rec:
        if x['date']==day and x.get('result'):
            r=x['result']
            print(f"  {x['code']} {x.get('name','')[:8]:<9}开{r['open']:>7.2f} 收{r['close']:>7.2f} "
                  f"开→收{r['open_to_close']:>+6.2f}% 开→高{r['open_to_high']:>+6.2f}% 开→低{r['open_to_low']:>+6.2f}%")

def stat():
    if not os.path.exists(OUT): print('⛔无样本'); return
    rec=[json.loads(l) for l in open(OUT)]
    done=[x for x in rec if x.get('result')]
    days=sorted({x['date'] for x in rec})
    print(f'样本: {len(rec)} 条 / {len(days)} 个交易日 ({days[0]}~{days[-1]}) | 已回填 {len(done)}')
    if len(done)<30:
        print(f'⛔样本仅 {len(done)} 条, **不足以算胜率**。至少积累到数百条再谈统计结论。')
    if done:
        import statistics as st
        v=[x['result']['open_to_close'] for x in done]
        h=[x['result']['open_to_high'] for x in done]
        print(f'  开→收: 中位{st.median(v):+.2f}% 均值{st.mean(v):+.2f}% 上涨{sum(1 for a in v if a>0)}/{len(v)}')
        print(f'  开→最高: 中位{st.median(h):+.2f}%')

if __name__=='__main__':
    a=sys.argv[1:] or ['scan']
    d=a[1] if len(a)>1 else datetime.date.today().isoformat()
    {'scan':lambda:scan(d),'fill':lambda:fill(d),'stat':stat}[a[0]]()
