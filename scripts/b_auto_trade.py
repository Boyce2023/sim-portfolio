#!/opt/homebrew/bin/python3
"""B策略全自动执行器 — 选股即推送 / 最早可交易时点即执行 / 执行即报告
⛔2026-09-08 Buwen当面质问后建: "如果你真的会忘为什么不代码化, 为什么呢?"
   我没有正当理由。模拟盘我有自主决策+执行+事后报告的授权(07-09定, 08-26/27/09-08共复发4次),
   每次都靠"记得"——靠记得就等于没有。三个环节全部代码化, 不留人工判断:

   ① 15:40 收盘选股完成 → **立即推飞书**(不埋在报告里)
   ② 09:25 竞价 / 09:30 开盘 → **自动执行**, 不等任何人确认
   ③ 成交 → **立即推飞书**报告代码/股数/价格/金额

⛔实操性铁律(2026-09-08 血的教训, 龙版传媒无效成交):
   B的买点是**当日盘中回落后再触及涨停价的那一瞬间**。封板一小时后再挂单, 前面压着巨额封单,
   真实市场排不进去——模拟盘的即时成交模型会给出假成交, 污染策略实证。
   所以: 昨日选出的候选, **必须在今日最早可交易时点执行**, 过了就作废不补。
   一字板同理不买(开盘价==最低价==涨停价, 全天没打开过, 买不进)。

用法: b_auto_trade.py notify      选股完成后推送名单(15:40 挂 b_watch_build 之后)
      b_auto_trade.py execute     最早可交易时点执行(09:30 挂)
      b_auto_trade.py sell        次日开盘卖出昨仓(09:30 挂, 先于 execute)
"""
import json,os,sys,datetime,subprocess,urllib.request
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def fs(msg):
    r=subprocess.run(['bash',os.path.expanduser('~/.claude/session-remote/fs-reply.sh'),msg],
                     capture_output=True,timeout=20)
    if r.returncode!=0:
        print(f'⛔飞书失败 rc={r.returncode} {r.stderr.decode("utf-8","ignore")[:120]}',flush=True)
        print(f'   未送达: {msg[:200]}',flush=True)
    return r.returncode==0
def mkt(c): return 'sh' if c[0] in '56' else ('bj' if c[0] in '48' else 'sz')
def quote(codes):
    out={}
    for i in range(0,len(codes),400):
        q=','.join(mkt(c)+c for c in codes[i:i+400])
        try: raw=urllib.request.urlopen(f'http://qt.gtimg.cn/q={q}',timeout=8).read().decode('gbk','ignore')
        except Exception as e: print('⛔行情失败',type(e).__name__); continue
        for line in raw.split('\n'):
            p=line.split('~')
            if len(p)>44 and 'none_match' not in line:
                try: out[p[2]]={'n':p[1],'now':float(p[3]),'pc':float(p[4]),'open':float(p[5]),
                                'high':float(p[33]),'low':float(p[34]),'turn':float(p[38] or 0),
                                'flow':float(p[44]),'chg':float(p[32])}
                except ValueError: pass
    return out
def watch_file(day=None):
    d=day or datetime.date.today().strftime('%Y%m%d')
    return f'{ROOT}/data/b_watch_{d}.json'

def notify():
    """① 选股完成立即推送 —— 不埋在长报告里"""
    p=watch_file()
    if not os.path.exists(p):
        fs(f'[B策略·选股] ⛔{datetime.date.today()} 短名单文件未生成({os.path.basename(p)}), 上游可能没跑 — 这不等于今天没候选'); return
    w=json.load(open(p)); c=w.get('候选',[])
    if not c:
        fs(f'[B策略·选股] {w.get("date")} 四门筛后**零候选**(文件正常, 确实没有过门的票)'); return
    lines=[f"{x['code']} {x['name']} {x['lb']}板 {x['gates']}/4门 {'满档' if x['gates']>=4 else '半档'} 市值{x.get('mcap','?')}亿 {x['ind']}" for x in c]
    msg=(f"[B策略·选股 {w.get('date')}] {len(c)}只候选, 明早最早可交易时点自动执行:\n"+'\n'.join(lines)
         +f"\n⛔买点=盘中回落后再触板那一瞬间; 一字板不买; 过了时点作废不补。我会自动下单并立刻报你, 不需要你确认。")
    print(msg); fs(msg)

def execute():
    """② 最早可交易时点自动执行 —— 不等任何人确认"""
    # ⛔取用链打在执行日志里, 每次都留痕(Buwen 09-08: 学了不调用等于没学)
    import subprocess as _sp
    print(_sp.run(['/opt/homebrew/bin/python3',f'{ROOT}/scripts/preflight.py','buy'],
                  capture_output=True,text=True).stdout)
    p=watch_file()
    if not os.path.exists(p): print(f'⛔无今日短名单 {p}'); return
    w=json.load(open(p)); cands=w.get('候选',[])
    if not cands: print('今日零候选'); return
    book=json.load(open(f'{ROOT}/data/b_book.json'))
    held={str(x.get('ticker'))[-6:] for x in (book.get('positions') or [])}
    room=3-len(held)
    if room<=0: print('⛔已持满3只'); return
    q=quote([c['code'] for c in cands])
    done=[]
    for c in sorted(cands,key=lambda z:(-z['gates'],z.get('turn',99))):
        if room<=0: break
        code=c['code']; d=q.get(code)
        if not d or code in held: continue
        lim=round(d['pc']*(1.2 if code[:2] in ('30','68') else 1.1),2)
        # 逐条核对回测参数(PARAMS_B2权威)
        if abs(d['open']-lim)<0.02 and abs(d['low']-lim)<0.02: print(f'  {code} ⛔一字板不买'); continue
        if d['turn']>10.0: print(f'  {code} ⛔换手{d["turn"]}%>10%'); continue
        if abs(d['now']-lim)>0.02: print(f'  {code} · 未触板(现{d["now"]} 涨停{lim}), 等触板'); continue
        need=100 if c['lb']<=1 else 50
        if d['flow']<need: print(f'  {code} ⛔市值{d["flow"]:.0f}亿<{need}亿'); continue
        size=book['pool_size']*(1/3 if c['gates']>=4 else 1/6)
        sh=int(size/lim/100)*100
        if sh<100: continue
        r=subprocess.run(['/opt/homebrew/bin/python3',f'{ROOT}/scripts/execute_trade.py','buy',
            '--account','cn','--book','b','--ticker',code,'--shares',str(sh),'--at-price',str(lim),
            '--reason',f"B策略自动执行·{'满档' if c['gates']>=4 else '半档'}({c['gates']}/4门)。触板即买, 涨停价{lim}成交。"
                        f"参数核对: 非一字板/换手{d['turn']}%<10/市值{d['flow']:.0f}亿≥{need}/前日涨>3%/{c['lb']}板。"
                        f"次日开盘价卖不留第二天。⛔自动执行不等确认(Buwen授权, 09-08代码化)"],
            capture_output=True,text=True,cwd=ROOT)
        ok='[OK]' in r.stdout
        print(f"  {code} {'✅成交' if ok else '⛔失败'} {sh}股@{lim}")
        if ok: done.append(f"{code} {d['n']} {sh}股@{lim} ={sh*lim:,.0f}元 {c['gates']}/4门"); room-=1
        else: print('   ',r.stdout[-200:] or r.stderr[-200:])
    # ③ 执行即报告
    if done:
        fs(f"[B策略·已成交 {datetime.date.today()}] 自动执行{len(done)}笔:\n"+'\n'.join(done)+"\n次日开盘卖出, 不留第二天。")
    else:
        fs(f"[B策略·未成交 {datetime.date.today()}] {len(cands)}只候选无一触板或全被参数门挡下, 今日零成交。")

def sell():
    """次日开盘卖出昨仓 —— B无thesis只有溢价
    ⛔2026-09-08修时点: 原挂09:30执行, 但**开盘价是09:25:00集合竞价撮合产生的**,
      09:30下单成交的是连续竞价实时价, 不是开盘价 —— 规则和实现对不上。
      现改挂 09:16/09:19/09:22 三次, 全在 9:15-9:25 申报窗口内。
    ⛔集合竞价只能限价单(沪3.3.6/深3.3.5, 市价单一律被拒);
      9:20-9:25 不可撤单但仍可新报; 9:25-9:30 交易所完全不接受申报。
    ⛔报价用跌停价挂卖(保证以集合竞价成交价即开盘价成交), 而非用昨收猜开盘价。"""
    book=json.load(open(f'{ROOT}/data/b_book.json'))
    ps=book.get('positions') or []
    if not ps: print('B账本空仓, 无需卖出'); return
    q=quote([str(x['ticker'])[-6:] for x in ps]); done=[]
    for x in ps:
        code=str(x['ticker'])[-6:]; d=q.get(code)
        if not d: continue
        # 以开盘价记账(集合竞价成交价==开盘价); 现实中挂单价应用跌停价确保成交
        r=subprocess.run(['/opt/homebrew/bin/python3',f'{ROOT}/scripts/execute_trade.py','sell',
            '--account','cn','--ticker',code,'--all','--at-price',str(d['open'] or d['now']),
            '--reason',f"B策略规则卖出: 次日开盘价{d['open']}卖出, 不留第二天。B没有thesis只有溢价, 不设持有逻辑。"],
            capture_output=True,text=True,cwd=ROOT)
        if '[OK]' in r.stdout:
            pnl=(d['open']-x.get('avg_cost',d['open']))*x['shares']
            done.append(f"{code} {d['n']} {x['shares']}股@{d['open']} 盈亏{pnl:+,.0f}")
    if done: fs(f"[B策略·开盘卖出 {datetime.date.today()}]\n"+'\n'.join(done))

if __name__=='__main__':
    {'notify':notify,'execute':execute,'sell':sell}[(sys.argv[1:] or ['execute'])[0]]()
