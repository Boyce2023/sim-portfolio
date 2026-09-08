#!/opt/homebrew/bin/python3
"""A股交易规则 · 单一来源(SSOT)
⛔2026-09-08 Buwen令"完整学习A股所有交易规则"后建。起因: 我今天连续踩规则常识的坑
   (涨停板买不进/T+1/竞价撮合时点/涨跌幅分板块), 每一个都是撞出来才知道的。
⛔本模块的意义不是"文档", 是**所有脚本的规则判断必须从这里出**。
   此前同一规则在不同脚本里有不同实现(astock_data_layer硬编码9.9/19.9不认ST和北交所,
   auction_surge自己写一套, b_watch_build又写一套) —— 那才是今天出错的结构性原因。

⚠️ 未逐条核对交易所条款号的项已标注 UNVERIFIED, 不得当作已核实事实硬编码进强约束。
"""
import datetime

# ══════════════════ 一、板块判定 ══════════════════
# 依据: 上交所《证券交易业务指南第4号—证券代码段分配指南(2023年第6次修订)》官方原文
#       深市号段为多源交叉印证(未取得深交所官方总表, UNVERIFIED)
#       北交所 920 号段 2024-04-22 启用, 2025-10-09 存量248家全面切换完成(83/87→920)
def board(code):
    """板块判定。⛔必须先判板块再判交易所——我第一版反过来写, 把 900xxx(沪市B股)判成了北交所。
    ⛔09-03另一次: 'sh' if c[0] in '653' 把 3xxxxx 创业板当沪市, 腾讯kline不报错只返回过期bar,
      静默污染三处产出。代码段判断错误的失败形态永远是静默的, 所以本函数必须有回归测试。"""
    c=str(code)[-6:]
    if c.startswith(('688','689')): return 'star'
    if c.startswith(('300','301')): return 'chinext'
    if c.startswith(('600','601','603','605')): return 'main_sh'
    if c.startswith(('000','001','002','003','004')): return 'main_sz'
    if c.startswith(('900','901')): return 'b_sh'
    if c.startswith('200'): return 'b_sz'
    if c.startswith('920'): return 'bse'
    if c[:2]=='43': return 'neeq'
    if c[:2] in ('83','87','88'): return 'bse'
    if c.startswith(('110','111','113','118','123','127','128')): return 'cb'
    if c.startswith(('204','131')): return 'repo'
    if c[0]=='5' or c[:2] in ('15','16','18'): return 'fund'
    return 'unknown'

_EX={'main_sh':'sh','star':'sh','b_sh':'sh','main_sz':'sz','chinext':'sz','b_sz':'sz',
     'bse':'bj','neeq':'bj'}
def exchange(code):
    """交易所, 由 board() 派生。独立判断正是我第一版出错的原因。"""
    b=board(code); c=str(code)[-6:]
    if b in _EX: return _EX[b]
    if b=='cb':   return 'sh' if c.startswith(('110','111','113','118')) else 'sz'
    if b=='repo': return 'sh' if c.startswith('204') else 'sz'
    if b=='fund': return 'sh' if c[0]=='5' else 'sz'
    return 'sz'

# ══════════════════ 二、涨跌幅 ══════════════════
# ⛔2026-07-06 沪深主板 ST/*ST 涨跌幅由 5% 上调至 10%, 异常波动阈值由12%上调至20%
#   (2026-04-24发布/2026-07-06施行)。跨此日期的回测必须分段, 否则涨停判定系统性错误。
ST_LIMIT_CHANGE_DATE=datetime.date(2026,7,6)

def price_limit_pct(code, is_st=False, on_date=None, is_new_first5=False):
    """涨跌幅限制(小数)。新股上市前5个交易日: 主板/创业板/科创板/北交所首日均不设限"""
    if is_new_first5: return None                      # None = 无涨跌幅限制
    b=board(code); d=on_date or datetime.date.today()
    if b=='bse': return 0.30
    if b in ('star','chinext'): return 0.20            # ST在这两个板也是20%, 不区分
    if b in ('b_sh','b_sz'): return 0.10               # B股10%(ST B股是否随2026-07-06调整 UNVERIFIED)
    if b=='cb': return 0.20                            # 可转债次日起±20%, 另有20%/30%临停
    if b in ('fund','repo'): return 0.10               # ⚠️ETF随跟踪标的板块变, 此为保守默认
    if b=='neeq': return None                          # 老三板另有规则
    if b in ('main_sh','main_sz'):
        if is_st: return 0.10 if d>=ST_LIMIT_CHANGE_DATE else 0.05
        return 0.10
    return 0.10

def limit_up_price(prev_close, code, is_st=False, on_date=None):
    """涨停价。⚠️UNVERIFIED: 取整方式(四舍五入到分)未取得交易所条款号原文,
    待 agent② 的价格规则确认后校正。"""
    p=price_limit_pct(code,is_st,on_date)
    if p is None: return None
    return round(prev_close*(1+p),2)

def is_limit_up(price, prev_close, code, is_st=False, on_date=None, tol=0.005):
    lp=limit_up_price(prev_close,code,is_st,on_date)
    return lp is not None and abs(price-lp)<=tol

# ══════════════════ 三、交易费用 ══════════════════
# 来源: 财政部税务总局公告2023年第39号(印花税0.1%→0.05%, 2023-08-28施行)
#       中国结算过户费下调50%(2022-04-29起 0.02‰→0.01‰)
#       交易经手费 0.0341‰ 双向 / 证管费 0.002% 双向
STAMP_CHANGE_DATE=datetime.date(2023,8,28)
TRANSFER_FEE_CHANGE_DATE=datetime.date(2022,4,29)

def fees(amount, side, on_date=None, commission_rate=0.0003, min_commission=5.0):
    """返回费用明细。⛔卖出成本≈万分之5.64, 买入≈万分之0.64 —— 印花税单边收。
    ⚠️min_commission=5元是市场惯例, UNVERIFIED是否为法定统一标准, 故设为可配置参数。"""
    d=on_date or datetime.date.today()
    stamp = amount*(0.0005 if d>=STAMP_CHANGE_DATE else 0.001) if side=='sell' else 0.0
    transfer = amount*(0.00001 if d>=TRANSFER_FEE_CHANGE_DATE else 0.00002)
    exch = amount*0.0000341
    reg  = amount*0.00002
    comm = max(amount*commission_rate, min_commission)
    total=stamp+transfer+exch+reg+comm
    return {'stamp':round(stamp,2),'transfer':round(transfer,2),'exchange':round(exch,2),
            'regulatory':round(reg,2),'commission':round(comm,2),'total':round(total,2),
            'bps':round(total/amount*10000,2) if amount else 0}

def roundtrip_cost_bps(amount, on_date=None, commission_rate=0.0003):
    """一买一卖的双边总成本(基点)。B策略日内买次日卖, 这个数直接吃掉溢价。"""
    b=fees(amount,'buy',on_date,commission_rate); s=fees(amount,'sell',on_date,commission_rate)
    return round((b['total']+s['total'])/amount*10000,2) if amount else 0

# ══════════════════ 四、T+1 ══════════════════
T0_KINDS={'convertible_bond','bond','bond_etf','money_etf','gold_etf','qdii_etf','reverse_repo'}
def is_t0(kind):
    """⛔普通股票型ETF是T+1不是T+0, 这条最易错。可转债/债券/债券ETF/货币ETF/
    黄金ETF/跨境ETF/国债逆回购才是T+0。"""
    return kind in T0_KINDS

def can_sell_today(buy_date, today=None, kind='stock'):
    if is_t0(kind): return True
    return (today or datetime.date.today()) > buy_date

if __name__=='__main__':
    print('=== 自检 ===')
    for c,n in [('600111','北方稀土'),('300788','中信出版'),('688206','概伦电子'),
                ('002436','兴森科技'),('430047','北交所样例'),('920289','华汇智能')]:
        print(f'  {c} {n:<10} {exchange(c)}/{board(c):<9} 涨跌幅{price_limit_pct(c)*100:.0f}%')
    print(f"\n  ST主板 2026-07-05: {price_limit_pct('600001',is_st=True,on_date=datetime.date(2026,7,5))*100:.0f}%")
    print(f"  ST主板 2026-07-06: {price_limit_pct('600001',is_st=True,on_date=datetime.date(2026,7,6))*100:.0f}%  ← 新规")
    print(f"\n  涨停价 昨收58.04 主板 → {limit_up_price(58.04,'603823')}  (实测百合花涨停63.84)")
    print(f"  涨停价 昨收26.46 创业板 → {limit_up_price(26.46,'300788')}")
    a=910888
    print(f"\n  买入{a:,}元 费用: {fees(a,'buy')}")
    print(f"  卖出{a:,}元 费用: {fees(a,'sell')}")
    print(f"  ⛔一买一卖双边成本 {roundtrip_cost_bps(a)} 基点 = {roundtrip_cost_bps(a)/100:.2f}%")

# ══════════════════ 五、涨停价精确取整(三层规则) ══════════════════
# 沪3.3.17 / 深3.3.19 原文: 四舍五入到最小变动单位; 若与前收盘价之差<1个tick, 则强制±1个tick;
# 若结果本身<1个tick, 取1个tick。⛔只做四舍五入会让超低价股算出"涨停价==前收盘价"=当天无法交易。
from decimal import Decimal, ROUND_HALF_UP
def tick_size(code):
    b=board(code)
    if b=='fund': return Decimal('0.001')
    if b=='b_sh': return Decimal('0.001')      # 沪B以美元计价
    return Decimal('0.01')

def limit_price(prev_close, code, direction='up', is_st=False, on_date=None):
    """涨/跌停价, 按交易所三层取整规则。返回 Decimal, None=无涨跌幅限制"""
    pct=price_limit_pct(code,is_st,on_date)
    if pct is None: return None
    pc=Decimal(str(prev_close)); t=tick_size(code); p=Decimal(str(pct))
    raw = pc*(1+p) if direction=='up' else pc*(1-p)
    r=(raw/t).quantize(Decimal('1'),rounding=ROUND_HALF_UP)*t
    if abs(r-pc) < t:  r = pc+t if direction=='up' else pc-t   # 第二层
    if r < t: r = t                                             # 第三层
    return r

# ══════════════════ 六、申报数量校验 ══════════════════
# ⛔科创板最小申报200股(不是100), 限价单上限10万股/市价5万股; 创业板限价30万/市价15万
QTY_RULE={'star':(1,200,100_000,50_000),'chinext':(100,100,300_000,150_000),
          'main_sh':(100,100,1_000_000,1_000_000),'main_sz':(100,100,1_000_000,1_000_000),
          'bse':(1,100,1_000_000,1_000_000)}   # 北交所100股起、1股递增(待核实上限)
def check_qty(code, qty, side='buy', order_type='limit', holding=None):
    b=board(code); step,lo,cap_l,cap_m=QTY_RULE.get(b,(100,100,1_000_000,1_000_000))
    cap=cap_l if order_type=='limit' else cap_m
    if side=='sell':
        if holding is not None and qty==holding: return True,''   # 清空持仓含零股恒合法
        if qty%step: return False,f'卖出{qty}股不是{step}股整数倍(零股须一次性全卖)'
        return True,''
    if qty<lo: return False,f'{b}最小申报{lo}股, 实{qty}'
    if qty>cap: return False,f'{b}单笔上限{cap}股, 实{qty}'
    if qty%step: return False,f'{b}申报须{step}股整数倍'
    return True,''

# ══════════════════ 七、涨停板可成交性 ══════════════════
# ⛔这不是交易所规则, 是市场微观结构经验判据。来源: 2026-09-08 规则调研 agent 的启发式,
#   已用我自己的实盘教训校准 —— 09-08 我在龙版传媒封板69分钟后挂涨停价买单, 模拟盘按涨停价
#   记了成交, 现实中排不进封单。那笔是"往训练数据投毒": 一笔不可能成交的成交长得跟正常交易
#   一模一样, 之后所有从流水算出的胜率/净期望全被污染且不可见。
def limit_up_fillability(minutes_since_sealed, has_opened_today, minutes_to_close,
                         seal_volume=None, avg_vol_5d=None):
    """返回 (等级, 原因)。等级: HIGH/MEDIUM/LOW/NEAR_ZERO"""
    if not has_opened_today and minutes_since_sealed is not None and minutes_since_sealed>60:
        return 'NEAR_ZERO', f'一字/未开板且已封{minutes_since_sealed:.0f}分钟, 排不进封单队列'
    if minutes_to_close is not None and minutes_to_close<10 and not has_opened_today:
        return 'NEAR_ZERO','尾盘10分钟内仍封死, 当日无成交希望'
    ratio = (seal_volume/avg_vol_5d) if (seal_volume and avg_vol_5d) else None
    if has_opened_today and ratio is not None and ratio<0.15:
        return 'MEDIUM', f'今日开板过且封单/5日均量={ratio:.2f}'
    if ratio is not None and ratio>0.30:
        return 'LOW', f'封单/5日均量={ratio:.2f}, 供给严重不足'
    if has_opened_today: return 'MEDIUM','今日开板过, 有过真实供给'
    return 'LOW','未开板, 供给不明'
