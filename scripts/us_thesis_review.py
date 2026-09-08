#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""美股 thesis 复核提示器 (2026-09-08 建)

⛔为什么有这个文件:
2026-09-08 诊断: 美股已实现 -$64,724 而浮盈 +$67,951——**赚的全在没卖的仓位上, 卖出决策整体是亏的**。
T18 回测(2026-08-24, 15份脚本): **判断型卖出20日卖对率87%, 机械型36%**。
而我的自动化全建在机械型上(灾难线/美元/金对簇三条), 判断型只靠"我想起来"。
⛔本文件不是新增扳机。它把 thesis 三问从"靠自觉"变成"每天必然摆到眼前"。

⛔它只提示不下单, 也不给卖出建议。判断结果由我定(06-26授权风控自主, 07-09升级为全部执行自主)。
"""
import json, os, sys, datetime, argparse

R = os.path.expanduser('~/claude-projects/sim-portfolio')
CFG = f'{R}/config/us_thesis_invalidation.json'
PF = f'{R}/portfolio_state.json'
LOG = f'{R}/data/thesis_review_log.jsonl'


def load():
    """⛔三态: 文件缺失/结构坏 ≠ 没有持仓。"""
    try:
        cfg = json.load(open(CFG))['positions']
    except FileNotFoundError:
        return None, None, f'失效条件文件不存在({CFG}) — 无法复核, 这不是"没问题"'
    except Exception as e:
        return None, None, f'失效条件文件损坏: {type(e).__name__}'
    try:
        pos = json.load(open(PF))['accounts']['us']['positions']
    except Exception as e:
        return None, None, f'读不到美股持仓: {type(e).__name__}'
    return cfg, pos, None


def run(days_ahead=7, verbose=True):
    cfg, pos, err = load()
    if err:
        print(f'⛔ {err}')
        return 2

    held = {p['ticker']: p for p in pos}
    tot = sum(p['market_value'] for p in pos)
    today = datetime.date.today()

    # ⛔覆盖率检查: 持仓有而配置没有 = 这只票的thesis没人管
    uncovered = [t for t in held if t not in cfg]
    stale_cfg = [t for t in cfg if t not in held]

    print(f"\n{'='*74}")
    print(f"  美股 thesis 复核提示 | {datetime.datetime.now():%Y-%m-%d %H:%M}")
    print(f"  ⛔只提示不下单; 判断型卖出20日卖对率87% vs 机械型36%(T18回测)")
    print(f"{'='*74}")

    if uncovered:
        print(f"\n⛔ {len(uncovered)} 只持仓没有失效条件定义 — 它们的thesis无人看管:")
        for t in uncovered:
            print(f"     {t} (权重{held[t]['market_value']/tot*100:.1f}%)")
        print(f"   → 处理: 补进 config/us_thesis_invalidation.json")

    # 按权重排, 权重大的先看
    rows = sorted([t for t in cfg if t in held],
                  key=lambda t: -held[t]['market_value'])
    print(f"\n{'代码':<7}{'权重':>6}  thesis 一句话 / ⛔今天该看的")
    for t in rows:
        c = cfg[t]
        w = held[t]['market_value'] / tot * 100
        wd = c.get('watch_date', '')
        urgent = '⛔' in wd or '⛔' in ' '.join(c['invalidate'])
        print(f"\n  {t:<7}{w:>5.1f}%  {c['thesis'][:66]}")
        print(f"          判据日期: {wd[:64]}")
        # 只显示标了⛔的失效条件(最该盯的那条)
        hot = [x for x in c['invalidate'] if x.startswith('⛔')]
        for h in (hot or c['invalidate'][:1]):
            print(f"          {'🔴' if hot else '  '} {h[:72]}")

    print(f"\n{'-'*74}")
    print(f"  覆盖 {len(rows)}/{len(held)} 只 | 失效条件 {sum(len(cfg[t]['invalidate']) for t in rows)} 条")
    if stale_cfg:
        print(f"  ⚠️ 配置里有 {len(stale_cfg)} 只已不在持仓(可清理): {stale_cfg}")
    print(f"{'='*74}\n")

    # 留痕: 证明今天做过, 而不是"我记得看过"
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, 'a') as f:
            f.write(json.dumps({
                'date': today.isoformat(),
                'covered': len(rows), 'held': len(held),
                'uncovered': uncovered,
            }, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f'⛔ 复核留痕失败: {e} — 无法证明今天做过', file=sys.stderr)

    # ⛔退出码: 0=全覆盖 / 3=有持仓未定义失效条件 / 2=无法判断
    return 3 if uncovered else 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    sys.exit(run(verbose=not a.quiet))
