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
    rows=[]
    try:   # ak对北交所返回空输出→json.loads崩,包起来让下方兜底能接手(2026-07-30修)
        out=subprocess.run([AK,"kline",t,str(n),"--json"],capture_output=True,text=True,timeout=60).stdout
        d=json.loads(out); rows=d if isinstance(d,list) else (d.get('data') or d.get('kline') or [])
    except Exception:
        rows=[]
    bars=[]
    for r in rows:
        try:
            bars.append({'d':str(r.get('date') or r.get('day') or r.get('日期'))[:10],
                         'c':float(r.get('close') or r.get('收盘') or r.get('c')),
                         'h':float(r.get('high') or r.get('最高') or r.get('h')),
                         'l':float(r.get('low') or r.get('最低') or r.get('l')),
                         'v':float(r.get('volume') or r.get('成交量') or r.get('v') or 0)})
        except: continue
    bars.sort(key=lambda x:x['d'])
    # ⭐北交所兜底(2026-07-30修): ak按沪深规则推前缀(6→sh/其他→sz),北交所(92/83/87开头)取不到→空bars
    # 病根实证: 920982锦波生物(北交所)昨日扫描"数据不足不给裁决"。改用ifind .BJ 补。
    if not bars and str(t)[:2] in ('92','83','87','43'):
        try:
            import ifind_data_layer as _ifd
            from datetime import date, timedelta
            _e = date.today(); _s = _e - timedelta(days=n*2+30)
            _h = _ifd.history(f"{t}.BJ", _s.isoformat(), _e.isoformat(), "close,high,low,volume")
            _tb = (_h.get('tables') or [{}])[0]
            _tm = _tb.get('time') or []; _d = _tb.get('table') or {}
            for _i, _dt in enumerate(_tm):
                try:
                    bars.append({'d': str(_dt)[:10], 'c': float(_d['close'][_i]), 'h': float(_d['high'][_i]),
                                 'l': float(_d['low'][_i]), 'v': float(_d.get('volume', [0]*len(_tm))[_i] or 0)})
                except Exception: continue
            bars.sort(key=lambda x: x['d'])
        except Exception: pass
    return bars

# ⭐量比阈值按regime自适应(2026-08-03回测定版)
# 病根: 固定1.5是拿牛市尺子量熊市。缩圈市场整体缩量,23个A-候选无一到1.5(最高1.49),门=永久关死。
# 回测(07-24+07-29共23个A-候选→08-03): 1.5建0只 | 1.2建2只+1.9%胜率2/2 | 1.0建4只+2.3%胜率4/4 | 全建+1.1%胜率15/23
# 结论: 降到1.0(=不缩量)反而跑赢"全建"一倍,筛选力来自位置门+SABCT,不来自量能门。
VOL_GATE = {'普涨': 1.5, '缩圈': 1.0, '普跌': 1.0}

def trend_signals(bars, cost=None, entry_date=None, regime=None):
    """返回②趋势维+风控维的机械读数(纯客观,不含判断)。判断留给整合层。
    regime: 普涨/缩圈/普跌 → 决定"放量"阈值(缺省1.5=普涨标准,向后兼容)"""
    if len(bars)<BREAKOUT_N+2: return None
    _vg = VOL_GATE.get(regime, 1.5)
    cur=bars[-1]['c']; prev=bars[-2]['c']
    hi_n=max(b['h'] for b in bars[-BREAKOUT_N-1:-1])   # 前25日高(不含今)
    lo_n=min(b['l'] for b in bars[-PREVLOW_N-1:-1])     # 前10日低(不含今)
    vols=[b['v'] for b in bars[-6:-1] if b['v']>0]
    vol_ratio=(bars[-1]['v']/(sum(vols)/len(vols))) if vols and bars[-1]['v']>0 else None
    chg=cur/prev-1 if prev else 0
    # 量价结构(客观分类,不判好坏)
    vp="未知"
    if vol_ratio is not None:
        if vol_ratio>=_vg and (chg>0.03 or (cur>hi_n and chg>0) or (_vg<1.5 and chg>0)): vp="放量上涨"  # 阈值按regime(08-03);大盘股修正(07-29):破25日新高+放量+收阳=突破,不必单日>3%;缩圈/普跌下不缩量+收阳即可(市场整体缩量,不强求3%)
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
