#!/usr/bin/env python3
"""
有机体决策核心 · 2026-07-10
把一个标的的5维状态向量 → 买/卖/持/加/减 一次称重坍缩。无中心:5维同级、thesis有对机械信号的否决权。
"油滑不死板"落地: 深研仓给空间(thesis否决机械线) + 追高仓守铁律(机械止损硬执行)。
持有性质(hold_nature)是那个开关。

5维状态向量 state_vector = {
  fundamental: {sabct:'A+/A/A-/B+/B', edge_real:bool, tree_node:str, peg_margin:'有/薄/无',
                thesis_3q:{supply:'intact/broken', beta:'intact/broken', catalyst:'intact/broken'}},
  trend: <timing_signals.trend_signals输出>,   # ②机械读数
  hold_nature: '深研埋伏仓/趋势追高仓/短线probe仓',
  position: {cur_pct:float, room_to_cap:float, concentration:float},
  regime: {water_level:'普涨/缩圈/普跌', sector_resonance:bool},
}
"""

CONV_CAP={'A+':0.30,'A':0.25,'A-':0.18,'B+':0.10,'B':0.0}
REGIME_MULT={'普涨':1.0,'缩圈':0.5,'普跌':0.3}   # regime=连续旋钮不是0/1闸门

def _thesis_broken(f):
    q=(f or {}).get('thesis_3q',{})
    return any(str(q.get(k,'intact')).startswith('broken') for k in ('supply','beta','catalyst'))

def decide_holding(sv):
    """已持仓的守/减/加/清。深研仓:thesis否决机械信号;追高仓:机械止损硬执行。"""
    f=sv.get('fundamental',{}); tr=sv.get('trend',{}) or {}; nat=sv.get('hold_nature','')
    pos=sv.get('position',{}); reg=sv.get('regime',{})
    thesis_broken=_thesis_broken(f)
    reasons=[]

    # ===== 深研埋伏仓: thesis管,机械信号降级为提示 =====
    if nat=='深研埋伏仓':
        if thesis_broken:
            return dict(action='清', stop_type='基本面证伪', reason='thesis三问证伪(供给/beta/催化有变坏)→深研仓唯一合法卖出理由')
        # thesis完好: 机械线不自动执行(油滑,不死板/不误杀)
        g=tr.get('浮盈%')
        if tr.get('round-trip触发(曾+15%吐回成本)') and g is not None and g>-3:
            # round-trip只在"还在成本附近/尚有浮盈"时减=锁利;已深亏再减=锁亏,不做
            return dict(action='减', stop_type='基本面证伪', reason='round-trip:曾+15%吐回到成本附近→减半锁利(thesis还在,不清);⛔这门本该更早在成本附近就响')
        if tr.get('round-trip触发(曾+15%吐回成本)') and g is not None and g<=-3:
            reasons.append(f'round-trip窗口已错过(现浮盈{g}%,减=锁亏):不减,守;教训=该门本应在成本附近响')
        if tr.get('量价结构')=='放量滞涨' and (tr.get('峰值浮盈%') or 0)>15:
            return dict(action='减', stop_type='基本面证伪', reason='末段放量滞涨+高浮盈→T11b减2/3锁利,thesis在保留底仓')
        # 主升中+仓位有空间+regime允许 → 可加
        if tr.get('量价结构')=='放量上涨' and tr.get('是否突破前高') and pos.get('room_to_cap',0)>0.05 and reg.get('water_level')!='普跌':
            return dict(action='加', stop_type='基本面证伪', reason='thesis完好+放量上涨突破+仓位有空间→让利润跑并加')
        return dict(action='守', stop_type='基本面证伪', reason='thesis完好,趋势未给减/加信号→持有(价格跌≠卖出理由)')

    # ===== 追高/动量/短线probe仓: 机械止损硬执行(不放松) =====
    if tr.get('灾难线触发(-12%,仅追高仓硬底)'):
        return dict(action='清', stop_type='技术止损', reason='追高仓触及灾难线-12%硬底→无条件清(无alpha仓守铁律)')
    if tr.get('是否破前低'):
        return dict(action='清', stop_type='技术止损', reason='追高仓破前10日低→趋势止损硬执行')
    if tr.get('round-trip触发(曾+15%吐回成本)'):
        return dict(action='减', stop_type='技术止损', reason='追高仓round-trip→减仓锁利')
    if thesis_broken:
        return dict(action='清', stop_type='技术止损', reason='thesis证伪+追高仓→清')
    return dict(action='守', stop_type='技术止损', reason='追高仓趋势未破→持有(动量在)')

def decide_buy(sv):
    """扫描候选的建仓裁决。①值得买(基本面轴)×②现在买(量价轴),AND门;涨跌永不否决基本面。"""
    f=sv.get('fundamental',{}); tr=sv.get('trend',{}) or {}; reg=sv.get('regime',{}); nat=sv.get('hold_nature','趋势追高仓')
    sabct=f.get('sabct','B'); edge=f.get('edge_real',False); peg=f.get('peg_margin','无')

    # ① 值得买(基本面轴,与涨跌无关)
    worth = sabct in ('A+','A','A-') and edge and peg!='无'
    if not worth:
        return dict(action='reject', reason=f'基本面轴不过:SABCT={sabct}/edge={edge}/PEG边际={peg}(概念蹭/无真edge/估值无边际)')

    # ② 现在买(量价轴)。⛔涨停封板不现价追(接盘);真主升=放量上涨突破;普通量价=未确认
    a_level = sabct in ('A+','A')
    limit_up = (tr.get('今日涨跌%') or 0) >= 9.8
    brk = (tr.get('距前高突破%') if tr.get('距前高突破%') is not None else -99)
    is_up = tr.get('量价结构')=='放量上涨' and (tr.get('是否突破前高') or brk>=-3)   # 强: 放量+突破/近突破
    is_near = tr.get('量价结构')=='放量上涨' and -8 <= brk < -3                      # 次一点: 放量但未突破,近突破区
    is_top = tr.get('量价结构')=='放量滞涨'
    ext = (tr.get('距前高突破%') or 0) > 8   # 冲太高

    mult=REGIME_MULT.get(reg.get('water_level','普涨'),1.0)
    cap=CONV_CAP.get(sabct,0.10)
    stop='基本面证伪' if nat=='深研埋伏仓' else '技术止损'

    if limit_up:
        return dict(action='打板/次日回踩', reason='涨停封板→现价追=接盘(实盘教训);次日回踩不破前低/突破点才是建仓点,挂条件单')
    if is_top:
        return dict(action='watch', reason='基本面好但末段放量滞涨→等回踩(必设失效期,链重启/放量新高则转追,别死等)')
    if not a_level and ext:
        return dict(action='watch', reason='B+级且距突破>8%冲太高→等回踩(A级豁免此cap,此非A级)')
    if is_up:   # ⭐大力档: 值得买+放量突破/近突破 → 满档(信心上限×regime)
        size=round(cap*mult,3)
        return dict(action='probe/买-大力', size_pct=size, tier='大力', stop_type=stop,
                    reason=f'大力档:值得买(SABCT {sabct}+真edge)×现在买(放量上涨+突破/近突破距前高{brk:.1f}%)→满档{size*100:.0f}%(上限{cap*100:.0f}%×regime{mult});止损={stop}')
    if is_near:  # ⭐小仓档(2026-07-16用户令): 值得买但timing次一点(放量未突破) → 半档
        size=round(cap*mult*0.5,3)
        return dict(action='probe/买-小仓', size_pct=size, tier='小仓', stop_type=stop,
                    reason=f'小仓档:值得买(SABCT {sabct})但timing次一点(放量上涨但未突破,距前高{brk:.1f}%)→半档{size*100:.0f}%(大力档一半);突破前高则可加至大力档;止损={stop}')
    return dict(action='watch', reason=f'量价未确认主升(非放量上涨/距前高{brk:.1f}%<-8太远)→等放量突破或回踩企稳确认')

if __name__=="__main__":
    # demo: 金石(深研仓,机械信号全触发,但thesis完好→守/减不清)
    jinshi=dict(
      fundamental=dict(sabct='A-',edge_real=True,tree_node='萤石命门矿',peg_margin='薄',
                       thesis_3q=dict(supply='intact',beta='intact',catalyst='intact')),
      trend={'量价结构':'缩量','是否破前低':True,'灾难线触发(-12%,仅追高仓硬底)':True,
             'round-trip触发(曾+15%吐回成本)':True,'峰值浮盈%':20.1,'是否突破前高':False},
      hold_nature='深研埋伏仓', position=dict(cur_pct=0.03,room_to_cap=0.15), regime=dict(water_level='缩圈'))
    print("金石(深研仓,thesis完好):", decide_holding(jinshi))
    jinshi2=dict(jinshi); jinshi2['fundamental']=dict(jinshi['fundamental'],thesis_3q=dict(supply='broken:萤石价崩',beta='intact',catalyst='intact'))
    print("金石(若供给thesis证伪):", decide_holding(jinshi2))
    # demo: 同样信号但是追高仓 → 机械硬清
    momentum=dict(jinshi); momentum['hold_nature']='趋势追高仓'
    print("同信号但追高仓:", decide_holding(momentum))
