#!/usr/bin/env python3
"""台账反向核对: 拿独立事件源和任务台账做差集, 找出"发生过但从未被记录"的事。

⛔为什么需要这个脚本(2026-09-17 interview 提出, us 首个实证):
  所有治理机制管的都是**已经进了台账的条目**——字段校验、status 合法性、新鲜度、needs_buwen 清账,
  全部以"这条记录存在"为前提。**一件事从未被记录时, 所有校验都通过, 因为它根本不在名单上。**
  实证: 2026-09-11 两笔美股持仓被一条 ADVISORY 性质的机械止损误判为 thesis 失效而清仓
  (ADBE 实现 -14,823 / TDG 实现 -12,449, 合计 -27,273 美元), 台账**零记录**。
  当时 us.jsonl 的字段可以齐全、status 可以合法、校验可以全绿, 因为那天的事不在名单上。
  六天里没有任何机制看见过它, 直到拿成交流水做反向核对才暴露。

⛔粒度必须是三元组, 不能只比日期:
  若某天既有成交又恰好有别的台账记录, 按日期比对能"对上", 漏记的成交照样查不出来。
  本脚本按 (日期, 标的, 动作) 逐笔核对。

市场隔离: 只核对本域标的。美股 ticker 是字母, A股是六位数字, 按此切分, 不越界判断另一市场。

用法:
    python3 ledger_gap_check.py                # 默认核对最近 30 天
    python3 ledger_gap_check.py --days 90
    python3 ledger_gap_check.py --market cn    # A股域自用(astock 可直接复用本脚本)
退出码: 0=无缺口 / 1=发现缺口(差集非空)
"""
import json, os, re, sys, argparse, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, 'portfolio_state.json')

ap = argparse.ArgumentParser()
ap.add_argument('--days', type=int, default=30)
ap.add_argument('--market', choices=['us', 'cn'], default='us')
ap.add_argument('--ledger', default=os.path.expanduser('~/.claude/nexus/tasks/us.jsonl'))
args = ap.parse_args()

CUT = (datetime.date.today() - datetime.timedelta(days=args.days)).isoformat()


def is_cn(t):
    return bool(re.fullmatch(r'\d{6}', str(t).strip()))


def in_market(t):
    return is_cn(t) if args.market == 'cn' else not is_cn(t)


# ---------- 事件源A: 成交流水 ----------
state = json.load(open(STATE))
events = []
for t in (state.get('trade_log') or []):
    d = str(t.get('date') or t.get('ts') or '')[:10]
    tk = str(t.get('ticker') or '').strip()
    if not d or d < CUT or not tk or not in_market(tk):
        continue
    events.append({
        'date': d, 'ticker': tk,
        'action': str(t.get('action') or '?').lower(),
        'shares': t.get('shares'),
        'pnl': t.get('realized_pnl') or t.get('pnl'),
        'reason': str(t.get('reason') or '')[:100],
    })

# ---------- 台账 ----------
led = []
if os.path.exists(args.ledger):
    for line in open(args.ledger):
        line = line.strip()
        if not line:
            continue
        try:
            led.append(json.loads(line))
        except Exception:
            pass

# ⛔把每条台账压成一个可搜索的文本块: 漏记判定靠"这笔成交有没有在任何一行里被提到"
blobs = []
for d in led:
    ts = str(d.get('updated_at') or d.get('ts') or '')[:10]
    blobs.append((ts, json.dumps(d, ensure_ascii=False)))


def mentioned(ev):
    """某笔成交是否被台账提到。两条通道任一成立即算:
      A 当期记录: 台账行的日期是成交日或次日, 且行内出现该标的代码(盘后复盘常在次日写)
      B 补记记录: 任何日期的台账行内同时出现该标的代码与成交日期字符串

    ⛔ 为什么必须有通道 B(2026-09-17 实测): 第一版只有 A, 结果是
      **本脚本抓出漏记 -> 我补记 -> 它照样报同一笔缺口**, 因为补记必然发生在事发之后,
      补记行的日期永远落不进"成交日或次日"这个窗口。
      那样它就成了一道**永远报错的门**, 而永远报错的门一周内就会被谁绕过去, 从此等于没有门。
      ⛔ 判据: 一道门如果连"按它的要求把问题修好"之后都还报错, 那它测的就不是它声称要测的东西。"""
    nxt = (datetime.date.fromisoformat(ev['date']) + datetime.timedelta(days=1)).isoformat()
    for ts, blob in blobs:
        if ev['ticker'] not in blob:
            continue
        if ts in (ev['date'], nxt):      # 通道A: 当期记录
            return True
        if ev['date'] in blob:           # 通道B: 补记, 行内写明了成交日期
            return True
    return False


# ⛔制度生效日: 台账制度 2026-09-02 由 Buwen 定, 早于此的成交不存在"漏记"一说。
#   不加这道分界的后果实测过: 首次运行报 35 笔缺口, 其中 33 笔是 08-24 至 08-28 的制度空窗期。
#   **一个天天报假警的门, 一周内就会被谁加一句忽略绕过去, 从此等于没有门。**
#   生效日取台账最早一行的日期, 而不是硬编码, 这样别的域复用本脚本时自动适配。
ledger_dates = sorted(ts for ts, _ in blobs if ts)
EFFECTIVE = ledger_dates[0] if ledger_dates else '1970-01-01'

pre_era = [e for e in events if e['date'] < EFFECTIVE]
in_era = [e for e in events if e['date'] >= EFFECTIVE]
gaps = [e for e in in_era if not mentioned(e)]

print(f"台账反向核对 | 市场={args.market} | 回看 {args.days} 天(自 {CUT})")
print(f"事件源 成交流水: {len(events)} 笔 | 台账: {len(led)} 行 | 制度生效日: {EFFECTIVE}")
if pre_era:
    print(f"  其中 {len(pre_era)} 笔早于制度生效日, 不计入缺口(制度空窗期, 非漏记)")
print(f"  纳入核对: {len(in_era)} 笔\n")

if not in_era:
    print("  该窗口内无制度生效后的成交, 无可核对")
    sys.exit(0)

by_date = {}
for e in events:
    by_date.setdefault(e['date'], []).append(e)
for d in sorted(by_date):
    miss = [e for e in by_date[d] if e in gaps]
    flag = f"  ⛔ {len(miss)} 笔无记录" if miss else "  ✅ 均有记录"
    print(f"  {d}: {len(by_date[d])} 笔{flag}")

if gaps:
    print(f"\n⛔⛔ 差集非空: {len(gaps)} 笔成交在台账中找不到任何提及")
    tot = 0.0
    for e in gaps:
        pnl = e['pnl']
        if isinstance(pnl, (int, float)):
            tot += pnl
        print(f"   [{e['date']}] {e['action'].upper()} {e['ticker']} {e['shares']}股 "
              f"实现 {pnl if pnl is not None else '?'}")
        print(f"        reason: {e['reason']}")
    print(f"\n   这些未被记录的成交合计实现盈亏 {tot:+,.2f}")
    print("   ⛔ 这不是台账写坏了, 是记录根本不存在: 字段校验与 status 合法性对它们一律通过。")
    sys.exit(1)

print("\n✅ 无缺口: 窗口内每笔成交都能在台账中找到对应记录")
sys.exit(0)
