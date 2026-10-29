#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""美股慢账 thesis 盲审复核器 (2026-09-08 建, 2026-10-29 并入原 T9 反处置效应盲审)

核心纪律:
1. 只提示不下单: 美股走基本面慢账, 卖出仅基于基本面论点证伪、催化兑现预期打满或换入更优标的。
2. 反处置效应盲审(原 T9 正式落点): 全程故意隐藏买入成本价(avg_cost)与账面浮盈亏,
   严禁盯着回本线或浮亏幅度做去留判断, 只按权重高低逐只核验慢账三问与前瞻催化剂。
3. 慢账复核三问:
   ① 供给侧物理壁垒(产能/交期/专利/牌照)变了吗?
   ② 核心盈利驱动被客观事实证伪了吗?
   ③ 前瞻催化剂已兑现打满或关键节点大幅推迟了吗?
"""
import argparse
import datetime
import json
import os
import re
import sys

R = os.path.expanduser('~/claude-projects/sim-portfolio')
CFG = f'{R}/config/us_thesis_invalidation.json'
PF = f'{R}/portfolio_state.json'
LOG = f'{R}/data/thesis_review_log.jsonl'
DATE_RE = re.compile(r'(20\d{2}-\d{2}-\d{2})')


def load():
    """三态区分: 文件缺失或结构损坏绝不等同于没有问题。"""
    try:
        with open(CFG, encoding='utf-8') as f:
            cfg = json.load(f)['positions']
    except FileNotFoundError:
        return None, None, f'失效条件文件不存在({CFG}), 无法复核'
    except Exception as e:
        return None, None, f'失效条件文件损坏: {type(e).__name__}'
    try:
        with open(PF, encoding='utf-8') as f:
            pos = json.load(f)['accounts']['us']['positions']
    except Exception as e:
        return None, None, f'读不到美股持仓: {type(e).__name__}'
    return cfg, pos, None


def _upcoming_tag(watch_date_str: str, today: datetime.date, days_ahead: int) -> str:
    """提取 watch_date 中的 YYYY-MM-DD 日期, 标注临近或刚过的催化剂窗口。"""
    m = DATE_RE.search(watch_date_str or '')
    if not m:
        return ''
    try:
        dt = datetime.date.fromisoformat(m.group(1))
    except ValueError:
        return ''
    delta = (dt - today).days
    if 0 <= delta <= days_ahead:
        return f' [催化临近: 剩{delta}天]'
    if -3 <= delta < 0:
        return f' [刚过催化日{-delta}天: 核对财报或事件兑现]'
    return ''


def run(days_ahead=7, verbose=True):
    cfg, pos, err = load()
    if err:
        print(f'⛔ {err}')
        return 2

    held = {p['ticker']: p for p in pos}
    tot = sum(p['market_value'] for p in pos) or 1.0
    today = datetime.date.today()

    uncovered = [t for t in held if t not in cfg]
    stale_cfg = [t for t in cfg if t not in held]
    rows = sorted([t for t in cfg if t in held],
                  key=lambda t: -held[t]['market_value'])

    upcoming_list = []
    for t in rows:
        tag = _upcoming_tag(cfg[t].get('watch_date', ''), today, days_ahead)
        if tag:
            upcoming_list.append(f'{t}{tag}')

    if verbose:
        print(f"\n{'='*76}")
        print(f"  美股慢账论点盲审复核 (原T9反处置效应已并入) | {datetime.datetime.now():%Y-%m-%d %H:%M}")
        print("  盲审铁律: 已隐藏成本价与浮盈亏, 只审基本面论点与前瞻催化剂, 只提示不下单")
        print("  慢账三问: ①供给壁垒变了吗  ②盈利驱动证伪了吗  ③催化已打满或推迟了吗")
        print(f"{'='*76}")

        if uncovered:
            print(f"\n⛔ {len(uncovered)} 只持仓缺失失效条件定义(论点无人看管):")
            for t in uncovered:
                print(f"     {t} (权重{held[t]['market_value']/tot*100:.1f}%)")
            print("   处理: 立即补入 config/us_thesis_invalidation.json")

        if upcoming_list:
            print(f"\n  近期催化窗口({days_ahead}日内): " + " | ".join(upcoming_list))

        print(f"\n{'代码':<7}{'权重':>6}  核心论点与关键证伪红线(按权重降序)")
        for t in rows:
            c = cfg[t]
            w = held[t]['market_value'] / tot * 100
            wd = c.get('watch_date', '')
            tag = _upcoming_tag(wd, today, days_ahead)
            print(f"\n  {t:<7}{w:>5.1f}%  {c['thesis'][:68]}")
            print(f"          观察窗口: {wd[:60]}{tag}")
            hot = [x for x in c.get('invalidate', []) if x.startswith('⛔')]
            for h in (hot or c.get('invalidate', [])[:1] or ['⛔本条缺失效条件字段, 需补']):
                print(f"          {'🔴' if hot else '  '} {h[:72]}")

        print(f"\n{'-'*76}")
        print(f"  覆盖 {len(rows)}/{len(held)} 只 | 失效条件共 {sum(len(cfg[t].get('invalidate', [])) for t in rows)} 条")
        if stale_cfg:
            print(f"  ⚠️ 配置含 {len(stale_cfg)} 只非当前持仓(可移入归档): {stale_cfg}")
        print(f"{'='*76}\n")
    else:
        status = f"覆盖 {len(rows)}/{len(held)} 只"
        if uncovered:
            status += f" | ⛔漏配: {uncovered}"
        if upcoming_list:
            status += f" | 近期催化: {', '.join(upcoming_list)}"
        print(f"[us_thesis_review] {status}")

    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'date': today.isoformat(),
                'covered': len(rows),
                'held': len(held),
                'uncovered': uncovered,
                'upcoming': upcoming_list,
                'blind_cost_review': True,
            }, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f'⛔ 复核留痕失败: {e}', file=sys.stderr)

    # 退出码: 0=全覆盖 / 3=有持仓未定义失效条件 / 2=配置或持仓读取异常
    return 3 if uncovered else 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='美股慢账论点盲审复核器(含原T9反处置效应检查)')
    ap.add_argument('--quiet', action='store_true', help='仅输出单行摘要')
    ap.add_argument('--days-ahead', type=int, default=7, help='前瞻催化剂提醒天数(默认7)')
    a = ap.parse_args()
    sys.exit(run(days_ahead=a.days_ahead, verbose=not a.quiet))
