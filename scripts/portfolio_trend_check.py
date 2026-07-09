#!/usr/bin/env python3
"""
持仓趋势监控 · 整合退出规则(2026-07-09 P1回测锁定参数)
机械信号(客观,禁单日噪音): 前低止损N=10 / 灾难线-12% / round-trip(峰值+15%吐回成本)
输出每只: 多窗口趋势结构 + 触发的出场门 + 守/减/清
基本面(thesis/信心)作为SECONDARY note分层显示,不覆盖机械信号的灾难线+破位(防死扛)
数据: 腾讯/新浪 不复权(match成本口径), 禁yfinance/东财_em
"""
import json, subprocess, sys
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

def check(t, cps):
    bars=kline(t,30)
    if len(bars)<EXIT_N+2: return None
    cur=bars[-1]['c']; g=cur/cps-1
    peak=max(b['h'] for b in bars)/cps-1   # 30日内峰值(近似持有期峰值)
    low10=min(b['l'] for b in bars[-EXIT_N-1:-1])   # 前10日最低(不含今日)
    hi30=max(b['h'] for b in bars); lo30=min(b['l'] for b in bars)
    tail=[b['c'] for b in bars[-6:]]
    # 出场门(优先级)
    door=None
    if g<=-DISASTER: door=f"灾难线-{int(DISASTER*100)}%(现{g*100:+.1f}%)"
    elif peak>=RT_PEAK and g<=RT_GIVE: door=f"round-trip(峰值+{peak*100:.0f}%吐回{g*100:+.1f}%)"
    elif cur<low10: door=f"破前{EXIT_N}日低{low10:.2f}(现{cur:.2f})"
    verdict="清/减" if door else "守"
    return dict(cur=cur,g=g,peak=peak,low10=low10,hi30=hi30,lo30=lo30,tail=tail,door=door,verdict=verdict)

def main():
    st=json.load(open(STATE))
    print("="*96)
    print(f"持仓趋势监控 · 整合退出规则(前低N={EXIT_N}/灾难-{int(DISASTER*100)}%/round-trip+{int(RT_PEAK*100)}%)")
    print("="*96)
    for p in st['accounts']['a_share']['positions']:
        t=p['ticker']; sh=p['shares']; cps=p['cost_basis']/sh
        conv,thesis=CONV.get(t,("?",""))
        r=check(t,cps)
        if not r: print(f"\n{p['name']}({t}) 数据不足/停牌"); continue
        struct=f"30日高{r['hi30']:.2f}/低{r['lo30']:.2f} 距高{(r['cur']/r['hi30']-1)*100:+.0f}% 近6收{'/'.join(f'{x:.1f}' for x in r['tail'])}"
        print(f"\n{p['name']}({t}) [{conv}] 成本{cps:.2f} 现{r['cur']:.2f} ({r['g']*100:+.1f}%)")
        print(f"  趋势结构: {struct}")
        print(f"  机械信号: 前{EXIT_N}日低={r['low10']:.2f} | 峰值+{r['peak']*100:.0f}% | → 【{r['verdict']}】 {r['door'] or '趋势未破,持有'}")
        print(f"  基本面(secondary): {conv} {thesis}")
    print("\n" + "-"*96)
    print("规则: 灾难线+破位是硬信号(thesis不能override,防死扛); 基本面只决定'给多宽空间'不决定'破了还留'")

if __name__=="__main__": main()
