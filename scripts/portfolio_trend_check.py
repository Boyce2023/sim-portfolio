#!/usr/bin/env python3
"""
持仓趋势监控 · 整合退出规则(2026-07-09 P1回测锁定参数)
机械信号(客观,禁单日噪音): 前低止损N=10 / 灾难线-12% / round-trip(峰值+15%吐回成本)
输出每只: 多窗口趋势结构 + 触发的出场门 + 守/减/清
基本面(thesis/信心)作为SECONDARY note分层显示,不覆盖机械信号的灾难线+破位(防死扛)
数据: A股用腾讯/新浪不复权(match成本口径,禁yfinance/东财_em); 美股用yfinance
⛔2026-08-14修复: 原版第62行硬编码 accounts['a_share'],美股持仓从未被检查过——
   此前每日报告的"T18五门全静默"是人工算的,不是本脚本在跑(30agent自审发现)。
用法: python3 portfolio_trend_check.py --market cn|us
"""
import argparse, json, subprocess, sys
AK="/Users/huaichuaibeimeng/.claude/skills/akshare-china/scripts/ak"
STATE="/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json"

# 锁定参数(P1 2026-07-09)
EXIT_N=10; DISASTER=0.12; RT_PEAK=0.15; RT_GIVE=0.0

# 信心+thesis(SECONDARY,人工判断层;宽止损overlay未独立回测,仅作note)
CONV={
 "688072":("A","半导体设备PECVD/ALD龙头,+42%最大赢家(停牌)"),
 "002049":("A","特种FPGA垄断,军工链龙头"),
 "000049":("A-","快充/SIP,博Q1三引擎拐点"),
 "603505":("A-","萤石命门矿,四树共享战略矿"),
 "603662":("B+","六维力龙头但scout仓PE117"),
 "605020":("A-","制冷剂配额,氟链下游"),
 "600160":("A+","制冷剂龙头,但旺季catalyst已price in在回落"),
 "002025":("A-","弹载连接器90%垄断"),
}

def kline(t, n=30):
    out=subprocess.run([AK,"kline",t,str(n),"--json"],capture_output=True,text=True,timeout=60).stdout
    d=json.loads(out); rows=d if isinstance(d,list) else (d.get('data') or d.get('kline') or [])
    bars=[]
    for r in rows:
        try:
            bars.append({'d':str(r.get('date') or r.get('day') or r.get('日期'))[:10],
                         'c':float(r.get('close') or r.get('收盘') or r.get('c')),
                         'h':float(r.get('high') or r.get('最高') or r.get('h')),
                         'l':float(r.get('low') or r.get('最低') or r.get('l'))})
        except: continue
    bars.sort(key=lambda x:x['d']); return bars

def kline_us(t, n=30):
    """美股用yfinance,收盘口径(与A股不复权口径的可比性: 美股复权差异主要来自分红,大盘股影响<1%)"""
    import yfinance as yf
    h=yf.Ticker(t).history(period=f"{max(n+15,60)}d")
    if h.empty: return []
    bars=[{'d':str(i.date()),'c':float(r['Close']),'h':float(r['High']),'l':float(r['Low'])}
          for i,r in h.iterrows()]
    return bars[-n:]

def check(t, cps, market='cn', entry_date=None):
    bars=kline_us(t,30) if market=='us' else kline(t,30)
    if len(bars)<EXIT_N+2: return None
    cur=bars[-1]['c']; g=cur/cps-1
    # 2026-08-17 修bug: 原为 max(全部30根K线的high)，对持有仅2-4天的新仓会把"建仓前的高点"
    # 当成持有期峰值，凭空制造 round-trip 信号(实测16只持仓中7只受影响)。
    # round-trip 的语义是"我赚到过的利润又吐回去了"，只能从建仓日之后算起。
    hold_bars=[b for b in bars if entry_date and b['d']>=entry_date] or bars[-1:]
    peak=max(b['h'] for b in hold_bars)/cps-1
    peak_days=len(hold_bars)
    low10=min(b['l'] for b in bars[-EXIT_N-1:-1])   # 前10日最低(不含今日)
    hi30=max(b['h'] for b in bars); lo30=min(b['l'] for b in bars)
    tail=[b['c'] for b in bars[-6:]]
    # 出场门(优先级)
    door=None
    if g<=-DISASTER: door=f"灾难线-{int(DISASTER*100)}%(现{g*100:+.1f}%)"
    elif peak>=RT_PEAK and g<=RT_GIVE: door=f"round-trip(峰值+{peak*100:.0f}%吐回{g*100:+.1f}%)"
    elif cur<low10: door=f"破前{EXIT_N}日低{low10:.2f}(现{cur:.2f})"
    verdict="清/减" if door else "守"
    return dict(cur=cur,g=g,peak=peak,peak_days=peak_days,low10=low10,hi30=hi30,lo30=lo30,
                tail=tail,door=door,verdict=verdict)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--market', choices=['cn','us'], default='cn',
                    help='⛔必须显式指定(市场隔离铁律)。cn=A股 us=美股')
    a=ap.parse_args()
    key='a_share' if a.market=='cn' else 'us'
    st=json.load(open(STATE))
    print("="*96)
    print(f"持仓趋势监控[{a.market.upper()}] · 整合退出规则(前低N={EXIT_N}/灾难-{int(DISASTER*100)}%/round-trip+{int(RT_PEAK*100)}%)")
    print("="*96)
    pos=st['accounts'][key]['positions']
    items=list(pos.values()) if isinstance(pos,dict) else pos
    if isinstance(pos,dict):
        for k,v in pos.items(): v.setdefault('ticker',k)
    for p in items:
        t=p['ticker']; sh=p['shares']
        cps=p.get('cost_basis',0)/sh if p.get('cost_basis') else (p.get('avg_cost') or p.get('cost') or 0)
        conv,thesis=CONV.get(t,("?",""))
        ed=str(p.get('entry_date') or '')[:10] or None
        r=check(t,cps,a.market,entry_date=ed)
        if not r: print(f"\n{p.get('name',t)}({t}) 数据不足/停牌"); continue
        struct=f"30日高{r['hi30']:.2f}/低{r['lo30']:.2f} 距高{(r['cur']/r['hi30']-1)*100:+.0f}% 近6收{'/'.join(f'{x:.1f}' for x in r['tail'])}"
        print(f"\n{p.get('name',t)}({t}) [{conv}] 成本{cps:.2f} 现{r['cur']:.2f} ({r['g']*100:+.1f}%)")
        print(f"  趋势结构: {struct}")
        print(f"  机械信号: 前{EXIT_N}日低={r['low10']:.2f} | 持有期峰值+{r['peak']*100:.0f}%(建仓{ed or '?'}起{r['peak_days']}根K) | → 【{r['verdict']}】 {r['door'] or '趋势未破,持有'}")
        print(f"  基本面(secondary): {conv} {thesis}")
    print("\n" + "-"*96)
    print("规则: 灾难线+破位是硬信号(thesis不能override,防死扛); 基本面只决定'给多宽空间'不决定'破了还留'")

if __name__=="__main__": main()
