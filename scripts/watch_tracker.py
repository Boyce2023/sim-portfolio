#!/usr/bin/env python3
"""
watch_tracker.py v2 — T16 watch失效期跟踪器 + 对称退出机制(2026-08-14重建)

背景(B3任务): watch原设计"进去就出不来"——义翘神州(301047)07-30挂watch"等66-67元
缩量企稳",回踩从未到位,股价随后暴涨,全程无人行动,踏空成本约¥45.6万。同类:博腾股份
+42.7%/翰宇药业+33.3%/诺唯赞+44.7%。诊断: 112次watch平均后续+7.24%,61.6%上涨,
只挡住1次>10%的跌,却错过18次>20%的涨——"等时机"本身是负expectancy。

v2核心变化(相对v1的3点修正):
  1. 【路径回溯,不只看今天】v1只拉当天tencent实时价,若当天没人跑工具=永久错过。
     v2从watch日起用新浪历史K线逐日回放,今天补一条tencent实时tick,任何一天首次
     触发都能被追溯找到(哪怕晚10天跑,也能报"08-04那天已经触发,你错过了")。
  2. 【趋势确认=新增的向上退出,不再只有"回踩到位"这一个出口】
     旧breakout(前高)常常离现价太远/被单日暴力跳空瞬间越过就没了意义(义翘07-30挂
     watch时前高77.48,08-04直接跳空到83.58,一天内"回踩"和"突破"同时作废)。
     新增fast_track: 单日涨≥8%或3日累计≥15% → 立即判"趋势确认",这组阈值直接复用
     T11(持仓端"单日涨>8%或2-3日累计>15%=止盈窗口打开")——同一套动量语言双向使用:
     T11对持仓喊"该减了",fast_track对watch喊"该追了"，对称。
  3. 【失效到期不再默认放弃,按现价vs watch时基准价给方向性默认】
     v1到期文案"按趋势追或明确放弃"模棱两可,实践中112次里绝大多数默认走向沉默放弃。
     v2到期时: 现价≥watch时收盘 → 默认"按probe追(未转弱,不放弃)"；
              现价<watch时收盘 → 默认"放弃(走弱确认,thesis需重新过审)"。

数据流(只读裁决账本,不回写):
  读  scan_history.jsonl      — 每ticker取最新一条裁决,筛 decision=='watch'
  读  portfolio_state.json    — 已建仓的watch自动标"已建仓"不再提示
  拉  新浪历史K线(money.finance.sina.com.cn) — watch日至今逐日回放(D12允许:A股价格
                                  用新浪/腾讯,禁yfinance)
  拉  qt.gtimg.cn 腾讯实时价  — 今天这一条(盘中未收盘,新浪日K线还没有today)
  写  (仅--signal时) ~/.claude/nexus/signals/pending/ 新格式信号

判定(按事件在历史K线上首次出现的日期排序,取最早者为准):
  🟢回踩到位   某日最低价触及回踩区间上沿(旧"买点到位"改名,逻辑不变)
  🟡趋势确认   某日单日涨≥8% 或 3日累计涨≥15%(新增,T11镜像阈值)
  🟢突破前高   某日收盘价≥旧breakout(前高)位(保留作慢涨型的兜底,常年被①③抢跑)
  ⚠️失效到期   watch日+N交易日≤今天且以上均未触发 → 按现价vs watch基准给方向性默认
  ⏳临近失效   剩余≤1交易日
  ❓历史数据缺失 新浪K线拉取失败,不可下结论(不用残缺数据判定)
  ✍️需人工补   回踩区/突破位均解析不出(不影响趋势确认监测,fast_track独立于此)

08-06批次注记: 2026-08-13已有一条 watch_pool_deprecation 记录作废该批次"回踩位等待"
逻辑(32只中经复核的24只回踩位比现价低6%~34%全部踏空,R5"位置不否决买入"生效后位置门
本身作废)。v2对08-06日期的watch记录: 回踩到位仅作提示不再建议据此单独建仓,趋势确认/
突破前高不受影响仍正常触发(那是向上确认,不是位置门问题)。

CLI:
  python3 scripts/watch_tracker.py                       # 默认只报"需行动"的
  python3 scripts/watch_tracker.py --all                 # 显示全部watch池
  python3 scripts/watch_tracker.py --signal               # 需行动项发信号
  python3 scripts/watch_tracker.py --tickers 301047,300363 --events  # 指定ticker+完整事件链(回溯验证用)

注: 交易日按周一至周五近似,忽略法定节假日(误差≤2日,失效判定偏保守可接受)。
"""
import os
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

import argparse
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

BASE = os.path.expanduser('~/claude-projects/sim-portfolio')
SCAN_HISTORY = os.path.join(BASE, 'scan_history.jsonl')
PORTFOLIO = os.path.join(BASE, 'portfolio_state.json')
SIGNAL_DIR = os.path.expanduser('~/.claude/nexus/signals/pending')

DEFAULT_EXPIRY_DAYS = 6   # T16建议5-8交易日,未标注时默认6
TIMEOUT = 8
KLINE_TIMEOUT = 6
KLINE_LOOKBACK_DAYS = 90  # 新浪datalen上限,足够覆盖当前所有watch(最老07-29)

# T11镜像阈值(2026-08-14 B3重建新增): 持仓端暴涨用它喊"该减了",watch端用它喊"该追了"
FAST_1D_PCT = 0.08
FAST_3D_PCT = 0.15

# 08-06批次: 2026-08-13 watch_pool_deprecation 已作废该日期批次的"回踩位等待"逻辑
DEPRECATED_ZONE_DATES = {'2026-08-06'}

# ---------------------------------------------------------------- 数据读取

def load_latest_watches():
    """每ticker取最新一条(文件按时间append,后写覆盖先写),筛decision=='watch'"""
    latest = {}
    if not os.path.exists(SCAN_HISTORY):
        print(f'⚠️ {SCAN_HISTORY} 不存在, watch池视为空', file=sys.stderr)
        return {}
    with open(SCAN_HISTORY, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get('ticker'):
                latest[r['ticker']] = r
    return {t: r for t, r in latest.items() if r.get('decision') == 'watch'}


def load_portfolio_tickers():
    try:
        with open(PORTFOLIO, encoding='utf-8') as f:
            state = json.load(f)
        pos = state.get('accounts', {}).get('a_share', {}).get('positions', [])
        return {p['ticker'] for p in pos}
    except Exception as e:
        print(f'⚠️ portfolio_state.json读取失败({e}),跳过已建仓过滤', file=sys.stderr)
        return set()

# ---------------------------------------------------------------- 计划解析

NUM = r'(\d+(?:\.\d+)?)'

def parse_plan(rec):
    """从 watch_expiry(优先) + one_line 解析: 回踩区间/突破位/失效交易日数"""
    text = (rec.get('watch_expiry') or '') + ' ' + (rec.get('one_line') or '')
    plan = {'zone_lo': None, 'zone_hi': None, 'breakout': None,
            'days': None, 'needs_manual': False, 'note': ''}

    # ⭐结构化字段优先(2026-07-30修): 新记录直接给数值,不走正则猜。
    _num = lambda v: float(v) if isinstance(v, (int, float)) else None
    s_lo, s_hi = _num(rec.get('zone_lo')), _num(rec.get('zone_hi'))
    s_bo, s_days = _num(rec.get('breakout')), rec.get('expiry_days')
    if s_lo or s_hi or s_bo:
        plan['zone_lo'] = s_lo if s_lo else s_hi
        plan['zone_hi'] = s_hi if s_hi else s_lo
        plan['breakout'] = s_bo
        plan['days'] = int(s_days) if isinstance(s_days, (int, float)) and 1 <= s_days <= 30 else DEFAULT_EXPIRY_DAYS
        if not isinstance(s_days, (int, float)):
            plan['note'] = f'失效期未标注,按默认{DEFAULT_EXPIRY_DAYS}交易日'
        if plan['zone_hi'] is None and plan['breakout'] is None:
            plan['needs_manual'] = True
        return plan

    # 回踩区间: "回踩95-105" / "回踩50-51再进" / "缩量回45再进" / "回调至30"
    _NOT_MA = r'(?![\d日周天])'
    m = re.search(r'回[踩调落至]?\D{0,6}?' + NUM + _NOT_MA
                  + r'(?:\s*[-–~至]\s*' + NUM + _NOT_MA + r')?', text)
    if m:
        lo = float(m.group(1))
        hi = float(m.group(2)) if m.group(2) else lo
        if hi < lo:
            plan['note'] = f'疑似截断"回踩{m.group(1)}-{m.group(2)}",区间不可信'
        else:
            plan['zone_lo'], plan['zone_hi'] = lo, hi

    m = re.search(r'突破\s*' + NUM + _NOT_MA, text)
    if m:
        plan['breakout'] = float(m.group(1))

    m = re.search(r'(\d+)\s*(?:个)?交易日', text)
    if m and 1 <= int(m.group(1)) <= 30:
        plan['days'] = int(m.group(1))
    else:
        plan['days'] = DEFAULT_EXPIRY_DAYS
        plan['note'] = (plan['note'] + ' ' if plan['note'] else '') + f'失效期未标注,按默认{DEFAULT_EXPIRY_DAYS}交易日'

    if plan['zone_hi'] is None and plan['breakout'] is None:
        plan['needs_manual'] = True
    return plan

# ---------------------------------------------------------------- 交易日

def add_trading_days(d, n):
    cur, added = d, 0
    while added < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur


def trading_days_between(a, b):
    """a到b(含b)剩余交易日数; b<=a返回0"""
    if b <= a:
        return 0
    n, cur = 0, a
    while cur < b:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n

# ---------------------------------------------------------------- 行情: 实时(今天这一条)

def tencent_prefix(ticker):
    """⚠️2026-08-14修复: 920xxx(北交所2023新编号)原被误判sz→行情拉取100%失败
    (贝特瑞920185/锦波生物920982实测: sz前缀返回'v_pv_none_match=1'空响应)。"""
    if ticker.startswith('6'):
        return 'sh'
    if ticker.startswith('92') or ticker[0] in '48':
        return 'bj'
    if ticker[0] in '03':
        return 'sz'
    return 'sz'


def fetch_prices(tickers):
    """腾讯qt.gtimg.cn批量实时价 → {ticker: {cur, prev, pct, high, low}}"""
    out = {}
    tickers = list(tickers)
    for i in range(0, len(tickers), 50):
        batch = tickers[i:i + 50]
        q = ','.join(tencent_prefix(t) + t for t in batch)
        url = f'http://qt.gtimg.cn/q={q}'
        try:
            raw = urllib.request.urlopen(url, timeout=TIMEOUT).read().decode('gbk', 'ignore')
        except Exception as e:
            print(f'⚠️ 行情批次获取失败: {e}', file=sys.stderr)
            continue
        for seg in raw.strip().split(';'):
            if '=' not in seg or '~' not in seg:
                continue
            f = seg.split('~')
            if len(f) < 35:
                continue
            try:
                cur, low = float(f[3]), float(f[34])
                if cur <= 0 or low <= 0:
                    continue
                out[f[2]] = {'cur': cur, 'prev': float(f[4]),
                             'pct': float(f[32]), 'high': float(f[33]), 'low': low}
            except (ValueError, IndexError):
                continue
    return out

# ---------------------------------------------------------------- 行情: 历史K线(路径回放)

def _sina_prefix(ticker):
    if ticker.startswith('6'):
        return 'sh'
    if ticker.startswith('92') or ticker[0] in '48':
        return 'bj'
    return 'sz'


def fetch_kline_since(ticker, since_date_str, today_tick=None):
    """新浪历史日K线,从since_date_str(含)到今天,升序返回[{day,open,high,low,close,volume}]。
    D12允许源:新浪/腾讯,禁yfinance。今天若盘中未收盘(新浪日K还没有today这一条),
    用today_tick(来自fetch_prices的实时tick)补一条合成行,保证"今天"也能参与判定。
    失败返回None(调用方须显式处理,不可当空历史用,防止残缺数据被误判"未触发")。
    """
    prefix = _sina_prefix(ticker)
    url = (f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
           f'CN_MarketData.getKLineData?symbol={prefix}{ticker}&scale=240&ma=no'
           f'&datalen={KLINE_LOOKBACK_DAYS}')
    try:
        req = urllib.request.Request(url, headers={'Referer': 'http://finance.sina.com.cn'})
        raw = urllib.request.urlopen(req, timeout=KLINE_TIMEOUT).read().decode('utf-8', 'ignore')
        data = json.loads(raw) if raw.strip() else None
    except Exception as e:
        print(f'⚠️ {ticker} 新浪K线拉取失败: {e}', file=sys.stderr)
        return None
    if not data:
        return None
    rows = [r for r in data if r.get('day', '') >= since_date_str]
    if not rows:
        return None
    today_str = date.today().isoformat()
    if today_tick and (not rows or rows[-1]['day'] != today_str):
        rows.append({
            'day': today_str,
            'open': str(today_tick.get('prev', today_tick['cur'])),
            'high': str(today_tick['high']),
            'low': str(today_tick['low']),
            'close': str(today_tick['cur']),
            'volume': '0',
        })
    return rows

# ---------------------------------------------------------------- 事件回放(核心新增)

def scan_path(klines, anchor_date_str, zone_hi, breakout):
    """从anchor_date_str(watch裁决日)之后逐日回放klines,找出所有历史上首次出现的
    退出事件,按日期升序返回全部(不只是最早一个,供--events完整展示回溯链):
      [{'date','type','price','detail'}, ...]
    type: 'zone_touch'(回踩到位) / 'fast_1d' / 'fast_3d'(合并显示为'趋势确认')
          / 'breakout'(突破前高)
    anchor(watch日)当天本身不计入判定(裁决就是基于那天的收盘做出的,不能自己触发自己)。
    """
    if not klines:
        return None  # 区别于[](无事件): None=数据缺失不可下结论
    rows = klines
    anchor_idx = None
    for i, r in enumerate(rows):
        if r['day'] >= anchor_date_str:
            anchor_idx = i
            break
    if anchor_idx is None:
        return None

    def _f(r, k):
        try:
            return float(r[k])
        except (TypeError, ValueError):
            return None

    anchor_close = _f(rows[anchor_idx], 'close')
    if anchor_close is None:
        return None

    events = []
    prev_close = anchor_close
    close_hist = [anchor_close]
    for r in rows[anchor_idx + 1:]:
        d = r['day']
        hi, lo, c = _f(r, 'high'), _f(r, 'low'), _f(r, 'close')
        if c is None or lo is None:
            continue
        if zone_hi is not None and lo <= zone_hi:
            events.append({'date': d, 'type': 'zone_touch', 'price': lo,
                            'detail': f'当日低{lo:g}触及回踩区上沿{zone_hi:g}'})
        if prev_close and prev_close > 0:
            chg1 = (c - prev_close) / prev_close
            if chg1 >= FAST_1D_PCT:
                events.append({'date': d, 'type': 'fast_1d', 'price': c,
                                'detail': f'单日{chg1*100:+.1f}%(前收{prev_close:g}→收{c:g})'})
        if breakout is not None and c >= breakout:
            events.append({'date': d, 'type': 'breakout', 'price': c,
                            'detail': f'收盘{c:g}≥突破前高{breakout:g}'})
        close_hist.append(c)
        if len(close_hist) >= 4:
            base = close_hist[-4]
            if base and base > 0:
                chg3 = (c - base) / base
                if chg3 >= FAST_3D_PCT:
                    events.append({'date': d, 'type': 'fast_3d', 'price': c,
                                    'detail': f'3交易日{chg3*100:+.1f}%(3日前收{base:g}→收{c:g})'})
        prev_close = c
    events.sort(key=lambda e: e['date'])
    return events


TYPE_LABEL = {
    'zone_touch': '🟢回踩到位',
    'fast_1d': '🟡趋势确认(单日)',
    'fast_3d': '🟡趋势确认(3日)',
    'breakout': '🟢突破前高',
}

# ---------------------------------------------------------------- 判定(v2)

def evaluate_v2(rec, plan, anchor_close, events, held, today):
    """返回 dict: status, advice, remaining_days, events(全部,供--events展示)"""
    try:
        watch_date = datetime.strptime(rec.get('date', ''), '%Y-%m-%d').date()
    except ValueError:
        return {'status': '✍️需人工补',
                'advice': f"date字段缺失/格式错({rec.get('date')!r}), 修scan_history该记录",
                'remaining': 0, 'events': []}
    expiry_date = add_trading_days(watch_date, plan['days'])
    remaining = trading_days_between(today, expiry_date)
    deprecated_zone = rec.get('date') in DEPRECATED_ZONE_DATES

    if held:
        return {'status': '💼已建仓', 'advice': '已在持仓,watch关闭',
                'remaining': remaining, 'events': events or []}

    if events is None:
        return {'status': '❓历史数据缺失', 'advice': '新浪K线拉取失败,不可下结论(禁用残缺数据判定),重跑',
                'remaining': remaining, 'events': []}

    if events:
        first = events[0]
        label = TYPE_LABEL[first['type']]
        is_today = first['date'] == today.isoformat()
        when = '今日' if is_today else f"{first['date']}(回溯,非今日)"
        dep_note = ''
        if first['type'] == 'zone_touch' and deprecated_zone:
            dep_note = ' | ⚠️08-06批次回踩位机制08-13已作废,不据此单独建仓,需SABCT复核后按现价定'
        n_more = len(events) - 1
        more_note = f' (其后另有{n_more}次触发,--events查全部)' if n_more else ''
        advice = f"{when}触发: {first['detail']} → 按probe评估{'/追' if 'fast' in first['type'] or first['type']=='breakout' else ''}{dep_note}{more_note}"
        return {'status': label, 'advice': advice, 'remaining': remaining, 'events': events}

    if today >= expiry_date:
        # v2核心修正: 不再模糊"按趋势追或明确放弃",按现价vs watch时基准给方向性默认
        # (现价需要今天的tick,这里用anchor_close比较——调用方在main()里传入的anchor_close
        #  已是watch日收盘,真正"现价"由main()在advice里用当日tencent tick二次校正)
        return {'status': '⚠️失效到期',
                'advice': f'{plan["days"]}交易日内无任何触发(回踩/趋势确认/突破前高均未出现)',
                'remaining': 0, 'events': [], 'anchor_close': anchor_close}
    if remaining <= 1:
        return {'status': '⏳临近失效', 'advice': f'剩{remaining}交易日,明日仍无触发即按到期规则处理',
                'remaining': remaining, 'events': [], 'anchor_close': anchor_close}
    return {'status': '⌛等待中', 'advice': '', 'remaining': remaining, 'events': [], 'anchor_close': anchor_close}

# ---------------------------------------------------------------- 信号

EVENT_MAP = {
    '🟢回踩到位': ('entry_hit', 'high'),
    '🟡趋势确认(单日)': ('trend_confirm', 'high'),
    '🟡趋势确认(3日)': ('trend_confirm', 'high'),
    '🟢突破前高': ('breakout', 'high'),
    '⚠️失效到期': ('expired', 'high'),
    '⏳临近失效': ('expiring', 'medium'),
}


def emit_signal(row):
    event, priority = EVENT_MAP[row['status']]
    ticker = row['ticker']
    os.makedirs(SIGNAL_DIR, exist_ok=True)
    for fn in os.listdir(SIGNAL_DIR):
        if f'watch_tracker-{event}-{ticker}' in fn:
            return None
    now = datetime.now(timezone.utc)
    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    sig_id = f'sig-{ts}-watch_tracker-{event}-{ticker}'
    sig = {
        'id': sig_id,
        'from': 'watch_tracker',
        'to': ['trading_astock'],
        'priority': priority,
        'type': 'position_change',
        'title': f'{row["status"]} | {row["name"]}({ticker}) | {row["advice"][:40]}',
        'content': (f'watch日: {row["date"]}  回踩区: {row["zone"]}  突破位: {row["bo"]}\n'
                    f'现价: {row["cur"]}  剩余交易日: {row["remain"]}\n'
                    f'裁决原文: {row["one_line"]}'),
        'action_required': row['advice'],
        'source_context': 'auto-detect:T16+watch_v2_fast_track',
        'created_at': now.isoformat(),
        'expires_at': (now + timedelta(days=3)).isoformat(),
        'lifecycle': 'pending',
        'read_by': [],
        'acted_on': False,
    }
    path = os.path.join(SIGNAL_DIR, sig_id + '.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(sig, f, ensure_ascii=False, indent=2)
    return path

# ---------------------------------------------------------------- 输出

def fmt_row(r):
    return (f"{r['ticker']:<7} {r['name']:　<5} {r['date'][5:]:<6} "
            f"{r['zone']:>9} {r['bo']:>6} {r['cur']:>8} {r['dist']:>8} "
            f"{str(r['remain']):>3}  {r['status']:<10} {r['advice']}")


HEADER = (f"{'代码':<7} {'名称':　<5} {'watch':<6} "
          f"{'回踩区':>8} {'突破位':>5} {'现价':>7} {'距买点':>6} "
          f"{'剩':>2}  {'状态':<9} 建议")


def main():
    ap = argparse.ArgumentParser(description='T16 watch失效期跟踪器 v2(对称退出:回踩到位+趋势确认+到期方向性默认)')
    ap.add_argument('--all', action='store_true', help='显示全部watch池(默认只报需行动)')
    ap.add_argument('--signal', action='store_true', help='需行动项发信号到signals/pending/')
    ap.add_argument('--tickers', type=str, default=None, help='逗号分隔,只看指定ticker(回溯验证用)')
    ap.add_argument('--events', action='store_true', help='展示每只标的完整历史触发事件链,不只是最早一条')
    args = ap.parse_args()

    today = date.today()
    watches = load_latest_watches()
    if args.tickers:
        wanted = set(args.tickers.split(','))
        watches = {t: r for t, r in watches.items() if t in wanted}
    if not watches:
        print('watch池为空')
        return
    held = load_portfolio_tickers()
    non_held = [t for t in watches if t not in held]
    prices = fetch_prices(watches.keys())

    print(f'⏳ 拉取{len(non_held)}只新浪历史K线(路径回放)...', file=sys.stderr)
    klines = {}
    for t in non_held:
        watch_date = watches[t].get('date', '')
        since = add_trading_days(datetime.strptime(watch_date, '%Y-%m-%d').date(), -3).isoformat() \
            if re.match(r'^\d{4}-\d{2}-\d{2}$', watch_date) else watch_date
        klines[t] = fetch_kline_since(t, since, today_tick=prices.get(t))

    rows = []
    for ticker, rec in sorted(watches.items(), key=lambda kv: kv[1].get('date', ''), reverse=True):
        plan = parse_plan(rec)
        px = prices.get(ticker)
        kl = klines.get(ticker)
        anchor_close = None
        events = None
        if kl:
            watch_date_str = rec.get('date', '')
            events = scan_path(kl, watch_date_str, plan['zone_hi'], plan['breakout'])
            for r in kl:
                if r['day'] >= watch_date_str:
                    try:
                        anchor_close = float(r['close'])
                    except (TypeError, ValueError):
                        pass
                    break
        result = evaluate_v2(rec, plan, anchor_close, events, ticker in held, today)
        status, advice, remaining = result['status'], result['advice'], result['remaining']

        if status == '⚠️失效到期' and anchor_close is not None and px is not None:
            drift = (px['cur'] - anchor_close) / anchor_close if anchor_close else 0
            if drift >= 0:
                advice += f' → 现价{px["cur"]:g}仍≥watch时{anchor_close:g}(+{drift*100:.1f}%),默认按probe追,不放弃'
            else:
                advice += f' → 现价{px["cur"]:g}已<watch时{anchor_close:g}({drift*100:.1f}%),默认放弃,thesis需重新过审'

        if plan['note'] and status not in ('💼已建仓',):
            advice = (advice + ' | ' if advice else '') + plan['note']
        if plan['needs_manual'] and status in ('⌛等待中', '⏳临近失效'):
            advice = (advice + ' | ' if advice else '') + '回踩区/突破位缺失(不影响趋势确认监测继续跑)'

        zone = ('-' if plan['zone_hi'] is None else
                (f"{plan['zone_lo']:g}-{plan['zone_hi']:g}" if plan['zone_lo'] != plan['zone_hi']
                 else f"{plan['zone_hi']:g}"))
        dist = '-'
        if px and plan['zone_hi']:
            dist = f"{(px['cur'] - plan['zone_hi']) / plan['zone_hi'] * 100:+.1f}%"
        rows.append({
            'ticker': ticker, 'name': rec.get('name', '?'), 'date': rec.get('date', '?????'),
            'zone': zone, 'bo': f"{plan['breakout']:g}" if plan['breakout'] else '-',
            'cur': f"{px['cur']:g}" if px else '-', 'dist': dist,
            'remain': remaining, 'status': status, 'advice': advice,
            'one_line': rec.get('one_line', ''), 'events': result.get('events') or [],
        })

    actionable = [r for r in rows if r['status'] in EVENT_MAP]
    manual = [r for r in rows if r['status'] == '✍️需人工补']
    missing = [r for r in rows if r['status'] == '❓历史数据缺失']
    waiting = [r for r in rows if r['status'] not in EVENT_MAP and r['status'] not in ('✍️需人工补', '❓历史数据缺失')]

    print(f'📋 watch池巡检(v2) {today} | 共{len(rows)}只: '
          f'需行动{len(actionable)} / 数据缺失{len(missing)} / 需人工补{len(manual)} / 等待或已建仓{len(waiting)}')
    print('=' * 120)

    if actionable:
        print('\n🔔 需行动 (回踩到位=买点触发 / 趋势确认+突破前高=向上确认追进 / 失效到期=方向性默认)')
        print(HEADER)
        for r in actionable:
            print(fmt_row(r))
            if args.events and len(r['events']) > 1:
                for e in r['events']:
                    print(f"      · {e['date']} {TYPE_LABEL[e['type']]}: {e['detail']}")
    else:
        print('\n✅ 今日无回踩触发/无趋势确认/无失效到期')

    if missing:
        print(f'\n❓ 历史数据缺失,不可下结论 ({len(missing)}只)')
        print(HEADER)
        for r in missing:
            print(fmt_row(r))

    if manual:
        print(f'\n✍️ 需人工补挂单计划 ({len(manual)}只)')
        print(HEADER)
        for r in manual:
            print(fmt_row(r))

    if args.all and waiting:
        print(f'\n⌛ 等待中/已建仓 ({len(waiting)}只)')
        print(HEADER)
        for r in waiting:
            print(fmt_row(r))
    elif waiting and not args.all:
        print(f'\n(另有{len(waiting)}只等待中/已建仓, --all查看)')

    if args.signal and actionable:
        print('\n📡 发信号:')
        for r in actionable:
            path = emit_signal(r)
            print(f'  {"→ " + path if path else "  跳过(pending已有同类信号): " + r["ticker"]}')


if __name__ == '__main__':
    main()
