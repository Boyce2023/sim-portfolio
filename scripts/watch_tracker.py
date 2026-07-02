#!/usr/bin/env python3
"""
watch_tracker.py — T16 watch失效期跟踪器（不许挂空等回调）

背景: T16教训(江丰等回调踏空+77.7%) — watch裁决必须带 ①回踩买点 ②失效期N交易日
③到期动作(趋势重启→按趋势追 / 趋势走坏→明确放弃)。本脚本每日巡检watch池,逼出决断。

数据流(只读裁决账本,不回写):
  读  scan_history.jsonl      — 每ticker取最新一条裁决,筛 decision=='watch'
                                 新记录若带 watch_expiry 字段优先解析;老记录从 one_line
                                 正则抓"回踩XX-XX/突破XX/N交易日",抓不到标 needs_manual
  读  portfolio_state.json    — 已建仓的watch自动标"已建仓"不再提示
  拉  qt.gtimg.cn 腾讯实时价  — NO_PROXY直连, timeout=8 (D12: 禁yfinance/禁东财)
  写  (仅--signal时) ~/.claude/nexus/signals/pending/ 新格式信号,复用signal_consumer.py消费

判定:
  🟢 买点到位   当日最低价触及回踩区间上沿 → 按probe评估建仓
  🟢 突破触发   现价≥突破位 → 趋势重启,按趋势追(T16豁免等回调)
  ⚠️ 失效到期   watch日+N交易日≤今天 → 按趋势追或明确放弃,不许继续挂
  ⏳ 临近失效   剩余≤1交易日 → 预警
  ✍️ 需人工补   解析不出买点/失效期 = 挂空,本身违反T16,常显催补

CLI:
  python3 scripts/watch_tracker.py            # 默认只报"需行动"的
  python3 scripts/watch_tracker.py --all      # 显示全部watch池(含等待中/已建仓)
  python3 scripts/watch_tracker.py --signal   # 需行动项发信号到 signals/pending/

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

    # 回踩区间: "回踩95-105" / "回踩50-51再进" / "缩量回45再进" / "回调至30"
    # ⚠️(?![\d日周天])防"回踩10日线/20日均线"把均线天数误当价格(也防NUM回溯截半个数字)
    _NOT_MA = r'(?![\d日周天])'
    m = re.search(r'回[踩调落至]?\D{0,6}?' + NUM + _NOT_MA
                  + r'(?:\s*[-–~至]\s*' + NUM + _NOT_MA + r')?', text)
    if m:
        lo = float(m.group(1))
        hi = float(m.group(2)) if m.group(2) else lo
        if hi < lo:
            # 如"回踩72-7" = one_line被截断,区间不可信
            plan['note'] = f'疑似截断"回踩{m.group(1)}-{m.group(2)}",区间不可信'
        else:
            plan['zone_lo'], plan['zone_hi'] = lo, hi

    # 突破位: "放量突破54" (同样排除"突破5日线"类均线表述)
    m = re.search(r'突破\s*' + NUM + _NOT_MA, text)
    if m:
        plan['breakout'] = float(m.group(1))

    # 失效期: "6交易日" / "5个交易日"
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

# ---------------------------------------------------------------- 行情

def tencent_prefix(ticker):
    if ticker.startswith('6'):
        return 'sh'
    if ticker[0] in '03':
        return 'sz'
    if ticker[0] in '48':
        return 'bj'
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
                out[f[2]] = {'cur': float(f[3]), 'prev': float(f[4]),
                             'pct': float(f[32]), 'high': float(f[33]), 'low': float(f[34])}
            except (ValueError, IndexError):
                continue
    return out

# ---------------------------------------------------------------- 判定

def evaluate(rec, plan, px, held, today):
    """返回 (status, advice, remaining_days)"""
    watch_date = datetime.strptime(rec['date'], '%Y-%m-%d').date()
    expiry_date = add_trading_days(watch_date, plan['days'])
    remaining = trading_days_between(today, expiry_date)

    if held:
        return '💼已建仓', '已在持仓,watch关闭', remaining
    if plan['needs_manual']:
        return '✍️需人工补', '无买点/失效期=挂空,违反T16 → 人工补回踩位/失效期或重判', remaining
    if px is None:
        return '❓无行情', '行情获取失败,重跑或查代码', remaining

    zone_touched = plan['zone_hi'] is not None and px['low'] <= plan['zone_hi']
    breakout_hit = plan['breakout'] is not None and px['cur'] >= plan['breakout']

    if zone_touched:
        z = f"{plan['zone_lo']:g}-{plan['zone_hi']:g}" if plan['zone_lo'] != plan['zone_hi'] else f"{plan['zone_hi']:g}"
        return '🟢买点到位', f'当日最低{px["low"]:g}触及回踩区{z},按probe评估建仓', remaining
    if breakout_hit:
        return '🟢突破触发', f'现价{px["cur"]:g}≥突破位{plan["breakout"]:g},趋势重启按趋势追(T16豁免)', remaining
    if today >= expiry_date:
        return '⚠️失效到期', f'{plan["days"]}交易日未回踩 → 按趋势追或明确放弃,不许继续挂(T16)', 0
    if remaining <= 1:
        return '⏳临近失效', f'剩{remaining}交易日,明日仍未回踩即决断', remaining
    return '⌛等待中', '', remaining

# ---------------------------------------------------------------- 信号

EVENT_MAP = {
    '🟢买点到位': ('entry_hit', 'high'),
    '🟢突破触发': ('breakout', 'high'),
    '⚠️失效到期': ('expired', 'high'),
    '⏳临近失效': ('expiring', 'medium'),
}


def emit_signal(row):
    event, priority = EVENT_MAP[row['status']]
    ticker = row['ticker']
    # 去重: pending里已有同事件同ticker的watch_tracker信号则跳过
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
        'source_context': 'auto-detect:T16',
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
            f"{str(r['remain']):>3}  {r['status']:<6} {r['advice']}")


HEADER = (f"{'代码':<7} {'名称':　<5} {'watch':<6} "
          f"{'回踩区':>8} {'突破位':>5} {'现价':>7} {'距买点':>6} "
          f"{'剩':>2}  {'状态':<5} 建议")


def main():
    ap = argparse.ArgumentParser(description='T16 watch失效期跟踪器')
    ap.add_argument('--all', action='store_true', help='显示全部watch池(默认只报需行动)')
    ap.add_argument('--signal', action='store_true', help='需行动项发信号到signals/pending/')
    args = ap.parse_args()

    today = date.today()
    watches = load_latest_watches()
    if not watches:
        print('watch池为空')
        return
    held = load_portfolio_tickers()
    prices = fetch_prices(watches.keys())

    rows = []
    for ticker, rec in sorted(watches.items(), key=lambda kv: kv[1]['date'], reverse=True):
        plan = parse_plan(rec)
        px = prices.get(ticker)
        status, advice, remaining = evaluate(rec, plan, px, ticker in held, today)
        if plan['note'] and status not in ('💼已建仓',):
            advice = (advice + ' | ' if advice else '') + plan['note']
        zone = ('-' if plan['zone_hi'] is None else
                (f"{plan['zone_lo']:g}-{plan['zone_hi']:g}" if plan['zone_lo'] != plan['zone_hi']
                 else f"{plan['zone_hi']:g}"))
        dist = '-'
        if px and plan['zone_hi']:
            dist = f"{(px['cur'] - plan['zone_hi']) / plan['zone_hi'] * 100:+.1f}%"
        rows.append({
            'ticker': ticker, 'name': rec.get('name', '?'), 'date': rec['date'],
            'zone': zone, 'bo': f"{plan['breakout']:g}" if plan['breakout'] else '-',
            'cur': f"{px['cur']:g}" if px else '-', 'dist': dist,
            'remain': remaining, 'status': status, 'advice': advice,
            'one_line': rec.get('one_line', ''),
        })

    actionable = [r for r in rows if r['status'] in EVENT_MAP]
    manual = [r for r in rows if r['status'] == '✍️需人工补']
    waiting = [r for r in rows if r['status'] not in EVENT_MAP and r['status'] != '✍️需人工补']

    print(f'📋 watch池巡检 {today} | 共{len(rows)}只: '
          f'需行动{len(actionable)} / 需人工补{len(manual)} / 等待或已建仓{len(waiting)}')
    print('=' * 110)

    if actionable:
        print('\n🔔 需行动 (T16: 到点必须决断,不许继续挂)')
        print(HEADER)
        for r in actionable:
            print(fmt_row(r))
    else:
        print('\n✅ 今日无回踩触发/无失效到期')

    if manual:
        print(f'\n✍️ 需人工补挂单计划 ({len(manual)}只, watch无买点=挂空,违反T16精神)')
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
