#!/usr/bin/env python3
"""
机械信号层 (有机体②趋势维 + 风控维的确定性计算) · 2026-07-10
纯脚本、可回测、无歧义。agent只在此之上做整合判断,不再肉眼估量比。
参数来自PIT回测锁定+审判修正: 突破25/前低10/灾难-12%/round-trip峰值+15%吐回成本(提前到成本附近就响)
数据: 腾讯/新浪 不复权(match成本口径), 禁yfinance/东财_em
用法: python3 timing_signals.py 603505 [成本] [买入日YYYY-MM-DD]
      或 import: from timing_signals import trend_signals
"""
import json, subprocess, sys
AK="/Users/huaichuaibeimeng/.claude/skills/akshare-china/scripts/ak"

BREAKOUT_N=25   # 前高突破窗
PREVLOW_N=10    # 前低止损窗
DISASTER=0.12   # 灾难线(仅追高仓硬底;深研仓由thesis管)
RT_PEAK=0.15    # round-trip: 曾达此浮盈
RT_GIVE=0.03    # 吐回到+3%(成本附近)就响——提前锁利,不拖到-12%

def _kline(t, n=40):
    out=subprocess.run([AK,"kline",t,str(n),"--json"],capture_output=True,text=True,timeout=60).stdout
    d=json.loads(out); rows=d if isinstance(d,list) else (d.get('data') or d.get('kline') or [])
    bars=[]
    for r in rows:
        try:
            bars.append({'d':str(r.get('date') or r.get('day') or r.get('日期'))[:10],
                         'c':float(r.get('close') or r.get('收盘') or r.get('c')),
                         'h':float(r.get('high') or r.get('最高') or r.get('h')),
                         'l':float(r.get('low') or r.get('最低') or r.get('l')),
                         'v':float(r.get('volume') or r.get('成交量') or r.get('v') or 0)})
        except: continue
    bars.sort(key=lambda x:x['d']); return bars

def trend_signals(bars, cost=None, entry_date=None):
    """返回②趋势维+风控维的机械读数(纯客观,不含判断)。判断留给整合层。"""
    if len(bars)<BREAKOUT_N+2: return None
    cur=bars[-1]['c']; prev=bars[-2]['c']
    hi_n=max(b['h'] for b in bars[-BREAKOUT_N-1:-1])   # 前25日高(不含今)
    lo_n=min(b['l'] for b in bars[-PREVLOW_N-1:-1])     # 前10日低(不含今)
    vols=[b['v'] for b in bars[-6:-1] if b['v']>0]
    vol_ratio=(bars[-1]['v']/(sum(vols)/len(vols))) if vols and bars[-1]['v']>0 else None
    chg=cur/prev-1 if prev else 0
    # 量价结构(客观分类,不判好坏)
    vp="未知"
    if vol_ratio is not None:
        if vol_ratio>=1.5 and chg>0.03: vp="放量上涨"
        elif vol_ratio>=2.0 and chg<0.015: vp="放量滞涨"
        elif vol_ratio<0.7: vp="缩量"
        else: vp="普通"
    r={
      "现价":round(cur,2),
      "距前高突破%":round((cur/hi_n-1)*100,1),   # >0=已突破且高出多少
      "是否突破前高":cur>hi_n,
      "距前低%":round((cur/lo_n-1)*100,1),        # <0=已破前低
      "是否破前低":cur<lo_n,
      "量比":round(vol_ratio,2) if vol_ratio else None,
      "今日涨跌%":round(chg*100,1),
      "量价结构":vp,
      "前25高":round(hi_n,2), "前10低":round(lo_n,2),
    }
    # 持仓相关(有成本才算)
    if cost:
        gain=cur/cost-1
        # 持有期峰值(entry_date后的最高)
        seg=[b for b in bars if (not entry_date or b['d']>=entry_date)]
        peak=(max(b['h'] for b in seg)/cost-1) if seg else gain
        r.update({
          "浮盈%":round(gain*100,1),
          "峰值浮盈%":round(peak*100,1),
          "灾难线触发(-12%,仅追高仓硬底)":gain<=-DISASTER,
          "round-trip触发(曾+15%吐回成本)":peak>=RT_PEAK and gain<=RT_GIVE,
          "持有天数":len(seg)-1 if seg else 0,
        })
    return r

if __name__=="__main__":
    t=sys.argv[1] if len(sys.argv)>1 else "603505"
    cost=float(sys.argv[2]) if len(sys.argv)>2 else None
    ed=sys.argv[3] if len(sys.argv)>3 else None
    bars=_kline(t,40)
    sig=trend_signals(bars,cost,ed)
    print(f"=== {t} 机械信号(②趋势维+风控维) ===")
    print(json.dumps(sig,ensure_ascii=False,indent=2))
