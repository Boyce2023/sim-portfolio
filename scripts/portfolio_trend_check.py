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
# 2026中报实际披露日(供铁律1判定"财报后跌=不及预期")。新增持仓需补进来,
# 或改为运行时调 ak.stock_report_disclosure —— 此处硬编码是为避免每次跑都打接口。
_DISCLOSE={'603259':'2026-08-04','688627':'2026-08-19','600111':'2026-08-20',
           '600312':'2026-08-20','600549':'2026-08-21','000155':'2026-08-25'}
# 2026-08-24 B2实证: round-trip口径由'峰值+15%吐回成本'改为'从持有期峰值回撤10%'(与成本无关)
RT_DRAWDOWN=0.10

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

def _live_price(t):
    """⛔2026-08-26修: 日K源(ak kline)在收盘后有延迟,盘中/刚收盘时返回的是昨日收盘价。
    实测: 精智达实际收盘464.45,而日K源给448.61(昨收) —— 差3.5%,足以让灾难线判断完全反向
    (448.61在灾难线449.06之下=触发清仓, 464.45在其上=不触发)。
    修法: 历史结构仍用日K,但"当前价"强制用实时源(腾讯/astock_data_layer)覆盖。"""
    try:
        import sys as _s
        _s.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts')
        from astock_data_layer import get_batch_prices
        v=(get_batch_prices([t]) or {}).get(t) or {}
        px=v.get('price')
        return float(px) if px and float(px)>0 else None
    except Exception:
        return None

def check(t, cps, market='cn', entry_date=None):
    bars=kline_us(t,30) if market=='us' else kline(t,30)
    if len(bars)<EXIT_N+2: return None
    cur=bars[-1]['c']
    if market=='cn':
        lp=_live_price(t)
        if lp and abs(lp/cur-1)>0.005:          # 与日K差>0.5%说明日K滞后
            bars[-1]['c']=lp                     # 覆盖最新bar收盘价
            bars[-1]['h']=max(bars[-1]['h'],lp)
            bars[-1]['l']=min(bars[-1]['l'],lp)
            cur=lp
    g=cur/cps-1
    # 2026-08-17 修bug: 原为 max(全部30根K线的high)，对持有仅2-4天的新仓会把"建仓前的高点"
    # 当成持有期峰值，凭空制造 round-trip 信号(实测16只持仓中7只受影响)。
    # round-trip 的语义是"我赚到过的利润又吐回去了"，只能从建仓日之后算起。
    hold_bars=[b for b in bars if entry_date and b['d']>=entry_date] or bars[-1:]
    peak_px=max(b['h'] for b in hold_bars)   # 持有期峰值绝对价(与成本无关,供RT_DRAWDOWN用)
    peak=peak_px/cps-1                       # 相对成本的峰值涨幅(旧口径,仅展示用)
    peak_days=len(hold_bars)
    low10=min(b['l'] for b in bars[-EXIT_N-1:-1])   # 前10日最低(不含今日)
    hi30=max(b['h'] for b in bars); lo30=min(b['l'] for b in bars)
    tail=[b['c'] for b in bars[-6:]]
    # 出场门(优先级)
    door=None
    # ⛔ 2026-08-24 实证大改(15份2个月回测,backtest/2026-08-24/,可复跑):
    # C2实测69笔卖出分类: 判断型(thesis证伪/主beta缺失/换仓)事后卖对率 5日72%/10日88%/20日87%;
    # 机械型(灾难线+破位) 58%/36%/36% —— 机械型20日36%比抛硬币差。所以机械门降级为"复核触发器"不是"执行器"。
    # B1: 不设止损总盈亏也不如设(所以不删灾难线),但破前10日低是四种规则里最差 → 降为仅告警。
    warn10=None
    if g<=-DISASTER:
        door=f"灾难线-{int(DISASTER*100)}%(现{g*100:+.1f}%)"
        # 是否连续2个交易日收在灾难线下(决定减半还是清余仓)
        dis_px=cps*(1-DISASTER)
        prev_below = len(bars)>=2 and bars[-2]['c']<dis_px
        action = "清余仓(连续2日在线下)" if prev_below else "当日减半+强制thesis三问复核"
        door += f" → {action}"
    elif cur <= peak_px*(1-RT_DRAWDOWN):
        # ⛔ 2026-08-24 口径改版(B2自算,45只持仓段, backtest/2026-08-24/b2_roundtrip_self.py):
        # 旧口径"峰值+15%吐回成本"45只里只触发2次=死规则,因为要求峰值先涨过+15%再跌回买入价,
        # 两条同时满足很罕见。且"成本"是我的买入价不是股票属性——同一只票我买贵了就触发、买便宜了不触发,
        # 测的是"我买贵了没"而不是"这只股票怎么了"。与已改掉的灾难线同一类毛病。
        # 实测四种口径(均收益/触发数): 现行-4.60%/2次 | DD10% -3.42%/20次 | DD15% -4.96%/12次
        #                          | DD20% -5.29%/9次 | 不设门 -5.18%
        # → DD10%是唯一明显优于"不设门"的(改善1.76pp),故取10%。
        # ⚠️但DD10%在45只里触发20次(44%),而C2实测机械型卖出20日卖对率仅36%——高触发率+低卖对率
        # 会制造churn(已知最大失血点)。故与灾难线同处理: 做复核触发器,不做自动卖出。
        door=(f"峰值回撤{RT_DRAWDOWN*100:.0f}%(持有期峰值{peak_px:.2f}→现{cur:.2f}) "
              f"→ 强制thesis三问复核, 三问未坏则持有(不自动卖)")
    elif cur<low10:
        door=None   # B5/B1: 破前10日低已降为仅告警,不构成卖出理由
        warn10=f"⚠️告警(不卖): 破前{EXIT_N}日低{low10:.2f}(现{cur:.2f}) — B1实测该规则四种止损里最差,仅提示"
    verdict="清/减" if door else "守"
    return dict(cur=cur,g=g,peak=peak,peak_days=peak_days,low10=low10,hi30=hi30,lo30=lo30,warn10=warn10,
                tail=tail,door=door,verdict=verdict)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--market', choices=['cn','us'], default='cn',
                    help='⛔必须显式指定(市场隔离铁律)。cn=A股 us=美股')
    a=ap.parse_args()
    key='a_share' if a.market=='cn' else 'us'
    st=json.load(open(STATE))
    print("="*96)
    print(f"持仓趋势监控[{a.market.upper()}] · 退出规则2026-08-24实证改版(前低N={EXIT_N}仅告警/灾难-{int(DISASTER*100)}%减半复核/峰值回撤{int(RT_DRAWDOWN*100)}%复核)")
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
        if r.get('warn10'): print(f"  {r['warn10']}")
        # ⛔ 两条铁律(2026-08-26 Buwen定): 财报后跌=不及预期 / 长跌=基本面有问题
        try:
            from iron_rules import check_all
            _dd = _DISCLOSE.get(t)
            _ir = check_all(t, _dd)
            _r1 = _ir.get('rule1') or {}; _r2 = _ir.get('rule2') or {}
            if _r1.get('verdict') == 'MISS':
                print(f"  ⛔铁律1: 中报{_dd}披露后 {_r1.get('ref_used'):+.1f}% = 不及预期"
                      f"(⛔不许用'数字很好/外生宏观/错杀'辩护,市场的反应就是判决)")
            elif _r1.get('verdict') == 'BEAT':
                print(f"  ✓铁律1: 中报{_dd}披露后 {_r1.get('ref_used'):+.1f}% = 超预期")
            if _r2.get('declining'):
                print(f"  ⛔铁律2: 近{_r2.get('window')}日{_r2.get('chg_window'):+.1f}% 长跌"
                      f" → 承认有我没看懂的基本面问题, 但⛔不因此自动放弃标的")
        except Exception as _e:
            pass
        print(f"  基本面(secondary): {conv} {thesis}")
    print("\n" + "-"*96)
    print("规则(2026-08-24实证改版): 灾难线=强制复核触发器(当日减半+thesis三问, 连续2日在线下才清余仓),")
    print("  不再是'无条件出'; 破前10日低=仅告警不卖(B1实测四种止损里最差); 去留主判据是thesis三问")
    print("  (C2实测: 判断型卖出20日卖对率87%, 机械型仅36%——机械型比抛硬币差)。")
    print("  依据脚本可复跑: sim-portfolio/backtest/2026-08-24/")

if __name__=="__main__": main()
