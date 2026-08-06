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
# ⛔ regime乘数已废除(2026-08-06 回测证伪, 全部改为1.0)
# 证据(142日全市场面板 + 291日第二样本, 循环移位随机化检验):
#   ①当日涨家占比1日自相关=-0.09(负!) → 是噪音不是状态变量; 现行判定每1.5天翻转一次,142天里64段单日噪音
#   ②预测力两样本符号相反: 普涨-普跌未来20日价差 S1 +0.48pp / S2 -0.17pp; 11个breadth指标×2样本×3窗口无一 p<0.10
#   ③循环移位检验(141种错位,精确p值): 当日涨家占比 p=0.184 / 1周累计 p=0.057 / 10日均+3日确认 p=0.766(比随机还差)
#      错位对照夏普区间[-0.11,0.89]=噪音带宽, A~D所有sizing方案(0.28~0.98)全落在里面 → 跟随机分仓统计上无区别
#   ④降仓信号反向: 用它降仓后指数未来10日-0.08%, 而全期任意日之后-0.77%(降仓后反而涨得更好)
#   ⑤盘中vs收盘一致率仅49.3%, 22.5%的交易日会出3.3倍系数错配(2026-08-06实盘踩中)
# 风险控制改由两件被验证有效的事承担: -12%止损(回撤-36.6% vs 无止损-42.8%) + 信心等级仓位上限
# ⚠️新旋钮要动钱必须先过三道门: ①1日自相关≥0.9 ②≥2独立样本IC同号 ③循环移位检验p<0.05
REGIME_MULT={'普涨':1.0,'缩圈':1.0,'普跌':1.0}   # 全1.0=乘数已停用; 保留dict仅为向后兼容,regime标签只作叙事不接仓位

# ⛔ 量比的两个用法(2026-08-06回测重定义, 7075条股票日观测/50只票/2026-01~08):
#   实测量比对未来收益几乎无预测力: N=5基准 H5 r=0.0005 / H10 r=0.0288 / H20 r=0.0013(解释力<0.1%方差)
#   分位数无梯度(Q1缩量0.76% vs Q5放量0.85%), 科技股甚至反向(Q1 1.44% > Q5 1.09%)
#   现行阈值6组检验只1组勉强显著; 阈值1.5全市场通过率仅11.0% → 结构性关死门, 这是反复打补丁的根源
#   ⭐唯一显著的是负向: 量比>3.0与未来收益显著负相关(t=-2.27~-2.88, 胜率从50%掉到33-45%) = 天量派发
# 结论: 量比不再是"能不能买"的门, 只做两件事——
#   VOL_BLOWOFF: 硬否决(天量见顶, 这是有统计支撑的)
#   VOL_OK:      仅用于分档(有量给大力/无量给半档), 不用于否决。1.05=不缩量即可, 取值宽松因其本身无预测力
VOL_BLOWOFF = 3.0
VOL_OK = 1.05

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

    # ══════════════════════════════════════════════════════════════════
    # ② 现在买(量价轴) —— 2026-08-06 第1轮规则迭代重写
    # ⛔ 旧逻辑的两个方向性错误(回测证伪,3618信号点/30只科技股/2026-01~08):
    #   错误1「位置门当单调关系」: 旧规则设-8%下限,以为"距高越远越差"。实测是非单调:
    #     区间        20日均值  20日胜率  平均MAE(回撤)
    #     A[-3,+8]    +8.93%   61.8%    -12.02%   ←旧主力区
    #     B[-8,-3]    +8.28%   58.6%    -11.38%
    #     C[-15,-8]   +4.77%   51.6%    -11.88%   ←★六区最差,真死区
    #     D[-25,-15]  +12.43%  67.3%    -10.20%   ←★最优(旧规则禁买)
    #     E[-40,-25]  +13.92%  65.3%    -10.10%   ←★次优(旧规则禁买)
    #     C vs D: t=-4.45 p<0.0001 | C vs E: t=-4.01 p=0.0001 (高度显著)
    #     → 旧-8%下限恰好挡掉期望最高的D/E,却因巧合挡住了最差的C(做对结果,错的理由)
    #     → 新形状=双峰型: 允许[-40%,+8%], 挖掉[-15%,-8%]死区
    #   错误2「量比门当硬闸门」: 实测量比对未来收益无预测力——
    #     N=5基准相关系数 H5 r=0.0005 / H10 r=0.0288 / H20 r=0.0013 (解释力<0.1%方差)
    #     分位数无梯度: Q1缩量0.76% vs Q5放量0.85%; 科技股更反直觉 Q1(1.44%)>Q5(1.09%)
    #     现行阈值6组检验只1组勉强显著; 阈值1.5通过率仅11.0%(结构性排除89%交易日→反复打补丁的根源)
    #     ⭐但极端量比>3.0显著负相关(t=-2.27~-2.88)=天量见顶派发信号
    #     → 量比降级: 不再作买入必要条件, 只用于①排除天量见顶 ②区分档位(有量给大力,无量给小仓)
    # ⚠️局限: 样本为2026年单一市场形态(缩圈年,个股中位数-13.8%), F区(<-40%)n=24来自2只票的
    #   对立事件(中微黄金坑+72% vs 天孚接飞刀-40%)不可用, 故F区维持不放行。第2轮需跨周期验证。
    # ══════════════════════════════════════════════════════════════════
    a_level = sabct in ('A+','A')
    limit_up = (tr.get('今日涨跌%') or 0) >= 9.8
    brk = (tr.get('距前高突破%') if tr.get('距前高突破%') is not None else -99)
    vr = tr.get('量比') or 0
    vp = tr.get('量价结构')
    up_today = (tr.get('今日涨跌%') or 0) > 0

    DEAD_LO, DEAD_HI = -15.0, -8.0      # ★C死区(实测六区最差,胜率51.6%)
    DEEP_LO = -40.0                      # ★D/E下沿(E区-40~-25仍显著优于C)
    in_dead = DEAD_LO <= brk < DEAD_HI
    in_deep = DEEP_LO <= brk < DEAD_LO   # D+E区: 旧规则禁买,实测期望最高
    in_near = DEAD_HI <= brk < -3.0      # B区
    in_break = -3.0 <= brk <= 8.0        # A区

    is_top = vp == '放量滞涨'
    blow_off = vr >= 3.0                 # ★天量见顶(实测显著负相关),唯一保留的量能否决
    has_vol = vp == '放量上涨' or vr >= VOL_OK   # 有量=给大力档; 无量但位置好=小仓档
    ext = brk > 8.0                       # 冲太高

    mult = REGIME_MULT.get(reg.get('water_level', '普涨'), 1.0)   # 已全1.0,乘数停用
    cap = CONV_CAP.get(sabct, 0.10)
    stop = '基本面证伪' if nat == '深研埋伏仓' else '技术止损'

    if limit_up:
        return dict(action='打板/次日回踩', reason='涨停封板→现价追=接盘(实盘教训);次日回踩不破前低/突破点才是建仓点,挂条件单')
    if blow_off:
        return dict(action='watch', reason=f'⛔天量见顶(量比{vr:.1f}≥3.0):实测量比>3.0与未来收益显著负相关(t=-2.27~-2.88),是派发不是突破→等量能回落')
    if is_top:
        return dict(action='watch', reason='基本面好但末段放量滞涨→等回踩(必设失效期,链重启/放量新高则转追,别死等)')
    if in_dead:
        return dict(action='watch', reason=f'⛔C死区(距前高{brk:.1f}%∈[-15,-8)):实测六区最差(20日+4.77%/胜率51.6%,显著劣于D区+12.43%/67.3%,p<0.0001)→跌了但没跌透,等跌进-15%以下或收复-8%以上')
    if not a_level and ext:
        return dict(action='watch', reason='B+级且距突破>8%冲太高→等回踩(A级豁免此cap,此非A级)')

    # ── 三条并行入场通道(实测期望值排序: 深跌反转 ≈ 突破 > 近突破) ──
    if in_deep:
        # ★通道3 深跌价值(窄门)。⛔这里的扳机绝不能用"单日放量反弹"——那个版本已被回测证伪:
        #   deep_rebound(4997只/6167信号): "60日高回撤>25%+量比>1.5+涨>3%" 相对CSI300超额20日 -2.94%
        #   /中位-5.80%/胜率34.2%, 且越跌越买越亏单调恶化(-2.84/-3.19/-7.06%), 叠加市值+PE质量过滤后仍-3.17%。
        #   pos_gate(位置期望值高) 与 deep_rebound(策略负超额) 的矛盾解法 = 位置对但扳机错:
        #   位置门放行深跌区, 但入场必须靠"结构企稳"+"估值安全", 不靠价格行为。
        # 四道硬约束(缺一不可, 每条都有独立证据):
        #   ①估值: 0<PE<=30。pe_valuation深跌后1个月 PE<15胜率62.2%(n=135)/15-30组57.6%(n=177)
        #          vs PE>100组40.9%(n=296)/亏损组41.2%(n=284), 62.2%vs40.9%约4个标准差。
        #          且astock_buy_signal_review实盘14笔 corr(entryPE,收益)=-0.55(最强预测变量, 量比只有+0.047)。
        #          ⛔PE未知 → 不猜, 降级watch。
        #   ②信心: SABCT>=A(比其他通道高一档)。deep_rebound: 开放深跌买入的门槛应比技术双确认更严不是更松。
        #   ③扳机: 连续站上5日线>=3日 或 20日未创新低(结构企稳), 不是单日放量。
        #   ④仓位: 半档且硬顶8%; 止损只用-12%灾难线无豁免(deep_rebound: 34.9%的深跌信号20日内触及-12%)。
        # ⚠️本通道整体证据等级=中(pos_gate样本可能有幸存者偏差:30只科技股是"今天的眼光"选的;
        #   扳机③从未回测过, 是草案提议)。第2轮红队正在专项证伪(survivorship/deep_trigger), 未定版前按窄门执行。
        pe = tr.get('PE') if tr.get('PE') is not None else sv.get('pe')
        stable = (tr.get('连续站上5日线天数') or 0) >= 3 or tr.get('20日未创新低')
        if pe is None:
            return dict(action='watch', reason=f'深跌区(距前高{brk:.1f}%)候选,但PE未知→本通道硬要求0<PE<=30(深跌后PE<15胜率62.2% vs PE>100仅40.9%),不猜估值,补PE后再判')
        if not (0 < pe <= 30):
            return dict(action='watch', reason=f'⛔深跌区但PE={pe:.0f}超出[0,30](深跌后高PE/亏损组胜率仅40.9%/41.2%,vs低PE 57.6-62.2%)→深跌抄底的分水岭是估值不是跌幅,不建仓')
        if not a_level:
            return dict(action='watch', reason=f'深跌区要求SABCT>=A(比突破通道高一档,因深跌买入必须靠基本面不靠价格行为),当前{sabct}→观察')
        if not stable:
            return dict(action='watch', reason=f'深跌区+估值安全(PE={pe:.0f})+{sabct},但结构未企稳(连续站上5日线{tr.get("连续站上5日线天数",0)}日<3且仍在创20日新低)→⛔单日放量反弹当扳机已被回测证伪(超额-2.94%/胜率34.2%),等结构企稳')
        size = round(min(cap * mult * 0.5, 0.08), 3)
        return dict(action='probe/买-深跌价值', size_pct=size, tier='深跌半档', stop_type='技术止损',
                    reason=f'⭐通道3深跌价值:距前高{brk:.1f}%∈[-40,-15)×PE={pe:.0f}(<=30)×{sabct}(>=A)×结构企稳(站上5日线{tr.get("连续站上5日线天数",0)}日/20日未创新低{tr.get("20日未创新低")})→半档{size*100:.1f}%(硬顶8%);⛔止损只用-12%灾难线无thesis豁免(34.9%的深跌信号20日内触及);需10-20日兑现不看5日')
    if in_break:  # 突破通道(旧主力区,实测仍有效但不再独占)
        size = round(cap * mult * (1.0 if has_vol else 0.5), 3)
        t = '大力' if has_vol else '小仓'
        return dict(action=f'probe/买-{t}', size_pct=size, tier=t, stop_type=stop,
                    reason=f'突破档:值得买(SABCT {sabct})×距前高{brk:.1f}%∈[-3,+8](20日+8.93%/胜率61.8%)×{"有量" if has_vol else "无量(半档)"}(量比{vr:.1f})→{size*100:.0f}%;止损={stop}')
    if in_near:   # 近突破通道(B区,实测略弱于A/D/E但仍正期望)
        size = round(cap * mult * 0.5, 3)
        return dict(action='probe/买-小仓', size_pct=size, tier='小仓', stop_type=stop,
                    reason=f'近突破档:值得买(SABCT {sabct})×距前高{brk:.1f}%∈[-8,-3)(20日+8.28%/胜率58.6%,略弱于A/D/E)→半档{size*100:.0f}%;突破或跌进深跌区可加档;止损={stop}')
    return dict(action='watch', reason=f'距前高{brk:.1f}%超出可建仓区间[-40%,+8%](F区<-40%样本仅24条来自2只票的对立事件,证据不足不放行)→等回到区间内')

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
