#!/usr/bin/env python3
"""成交流水 vs 裁决记录 的反向差集 — 拿体系外部的事件源核对体系内部的记录

⛔ 为什么需要(2026-09-17 全组夜间对账, interview 提出 us 实证):
   所有治理机制(needs_buwen 检查/stale 列/格式校验/点名)管的都是**已经进了台账的条目**。
   一件事如果从未被记录, 它对整套体系不可见 —— 那不是绿灯, 是不在名单上。
   补法只有一个: 用**独立于台账的事件源**做反向核对。本域的事件源 = 成交流水。

⛔ 两条量尺纪律(踩过才写下来的):
   1. **按 (日期, 标的, 动作) 三元组比, 不按日期比**。日期粒度太粗: 某天既有成交又恰好有
      别的记录时, 日期能对上而漏记的成交照样查不出来。(us 2026-09-17 第一版就是这么漏的)
   2. **先验事件源本身的覆盖率**。对着一个盲源做反向核对只会得到"无异常"的自我安慰。
      (interview 2026-09-17 实证: 它的日历源对 Teams 邀约结构性失明, 两次面试一条没有)

⛔ 两类缺口, 危险程度不同:
   A. 有成交无裁决 -> 漏记, 事后补
   B. 有裁决无成交 -> **该执行没执行**, 这类更危险, 且只有到期日过了才看得出来
"""
import json
import os

_LEDGER_EPOCH = '1900-01-01'
import sys
from datetime import date

ROOT = os.path.expanduser('~/claude-projects/sim-portfolio')
LEDGER = os.path.expanduser('~/.claude/nexus/tasks/astock.jsonl')
SINCE = '2026-09-01'


def _cn_trades():
    st = json.load(open(f'{ROOT}/portfolio_state.json'))
    out = []
    for t in st.get('trade_log') or []:
        if str(t.get('account') or '') != 'a_share':
            continue
        d = str(t.get('date') or t.get('timestamp') or '')[:10]
        if d >= SINCE:
            out.append((d, str(t.get('ticker') or '').split('.')[0],
                        str(t.get('action') or '').lower(), t))
    return sorted(out)


def _verdicts():
    d = json.load(open(f'{ROOT}/data/pending_verdicts.json'))
    return d['items'] if isinstance(d, dict) else d


def _ledger_rows():
    return [json.loads(l) for l in open(LEDGER, encoding='utf-8') if l.strip()]


def check(verbose=True):
    trades = _cn_trades()
    vs = _verdicts()
    rows = _ledger_rows()
    # ⛔源覆盖率自检: 事件源空或异常少时, 差集结果没有意义, 必须喊而不是报"无异常"
    assert trades, f'⛔成交流水在 {SINCE} 之后一笔都没有 —— 先查事件源本身是不是断了, 不许当成"没有漏记"'
    vtext = json.dumps(vs, ensure_ascii=False)
    ltext = json.dumps(rows, ensure_ascii=False)

    # ⛔制度起始日(2026-09-17 二次修正): 第一版定义为"台账最早提到股票代码的行"= 2026-09-02, **错了**。
    #   实测 21 笔成交里, 09-02~09-07 期间只有 2 笔碰巧有台账命中, 09-09 之后才连续命中(2/2/1/3/1)。
    #   **一次出现和一个习惯, 在"最早出现"这个判据下长得一模一样** —— 它测不出"形成了习惯"。
    #   正确定义: **连续覆盖率首次达标的日期** —— 从该日起, 每笔成交都能在台账里找到对应行。
    _cn = [(str(t.get('date'))[:10], str(t.get('ticker'))) for t in
           (json.load(open(f'{ROOT}/portfolio_state.json'))['trade_log'])
           if str(t.get('account')) == 'a_share']
    _cn.sort()
    _rtxt = [(str(r.get('updated_at') or r.get('ts') or '')[:10],
              json.dumps(r, ensure_ascii=False)) for r in rows]
    _hit = [(d, tk, any(rd == d and tk in txt for rd, txt in _rtxt)) for d, tk in _cn]
    # 从后往前找: 最后一段"连续全命中"的起点
    global _LEDGER_EPOCH
    _LEDGER_EPOCH = '9999-12-31'
    for i in range(len(_hit) - 1, -1, -1):
        if not _hit[i][2]:
            break
        _LEDGER_EPOCH = _hit[i][0]
    if _LEDGER_EPOCH == '9999-12-31':
        _LEDGER_EPOCH = _hit[-1][0] if _hit else '1900-01-01'
    print(f'[制度起始日] {_LEDGER_EPOCH} — 定义=连续覆盖率首次达标之日(非"最早出现过一次"), '
          f'早于此日的成交归入空窗期不计入缺口')

    no_verdict, no_ledger = [], []
    for d, tk, act, t in trades:
        # 裁决系统: 该标的存在覆盖这个日期的已结案动作条目
        hit_v = [v for v in vs if str(v.get('ticker') or v.get('code') or '') == tk
                 and str(v.get('closed') or '')[:10] == d]
        if not hit_v:
            hit_v = [v for v in vs if str(v.get('ticker') or v.get('code') or '') == tk
                     and tk in vtext and str(v.get('due') or '')[:10] == d]
        # ⛔2026-09-17 修假警: pending_verdicts 存的是**带到期日的延后裁决**, 不是每笔成交的决策载体。
        #   真正的载体是 trade_log 每笔自带的 reason(实测09-01起20笔: 零空值, 中位274字, 最长647字)。
        #   首跑报"16笔有成交无裁决"全部是这个口径错造成的假警。
        #   ⛔一个天天报假警的门, 一周内就会被谁绕过去(main 2026-09-17) —— 所以判据必须改对再挂进日常。
        if not hit_v and len(str(t.get('reason') or '').strip()) < 50:
            no_verdict.append((d, tk, act, t.get('shares'), t.get('value')))
        # ⛔2026-09-17 制度生效日分界(main判据, 我引用过却没实现 —— 判据记住了没落到代码上):
        #   取台账里**最早一条提到成交的行**的日期作为制度起始日; 早于它的成交归入"制度空窗期", 不计入缺口。
        #   实证: 首版报14笔"无台账镜像", 全部落在我建立"成交后补台账镜像"这个习惯之前。
        #   ⛔一个天天报14笔历史空窗的门, 一周内就会被我自己无视。
        if d < _LEDGER_EPOCH:
            continue
        # 共享台账: 同日或次日提到该代码
        hit_l = [i for i, r in enumerate(rows, 1)
                 if str(r.get('updated_at') or r.get('ts') or '')[:10] >= d
                 and str(r.get('updated_at') or r.get('ts') or '')[:10] <= d
                 and tk in json.dumps(r, ensure_ascii=False)]
        if not hit_l:
            no_ledger.append((d, tk, act, t.get('shares')))

    # B 类: 有裁决无成交 —— 已过期的"待执行动作"却没有对应成交
    today = date.today().isoformat()
    trade_keys = {(d, tk) for d, tk, _, _ in trades}
    undone = []
    for v in vs:
        cond = str(v.get('condition') or '')
        if '待执行动作' not in cond:
            continue
        due = str(v.get('due') or '')[:10]
        tk = str(v.get('ticker') or v.get('code') or '')
        if due and due <= today and (due, tk) not in trade_keys:
            # ⛔2026-09-17 修假阳性: "到期无成交"要区分两种情况 ——
            #   ①漏做(无任何解释) = 真问题
            #   ②已裁决不执行(裁决原文写明理由, 如被T15门拦下) = 正常, 不该报
            #   实证: #34 金盘清仓单 09-15 被 T15 门当场拦下, verdict 里写清了"未执行"及依据,
            #   而第一版只看"有没有成交", 把一次**正确的不执行**报成了漏做。
            #   ⛔一个天天报假警的门, 一周内就会被谁绕过去(main 2026-09-17)。
            vtxt = str(v.get('verdict') or '')
            explained = (str(v.get('status')) == 'closed'
                         and any(w in vtxt for w in ('未执行', '不执行', '拦下', '拦截', '撤销', '作废', '放弃')))
            if not explained:
                undone.append((due, tk, v.get('id'), str(v.get('status'))))

    if verbose:
        print(f'[源] A股成交 {len(trades)} 笔({SINCE} 起), 裁决 {len(vs)} 条, 台账 {len(rows)} 行')
        for d, tk, act, t in trades:
            print(f'  {d} {tk} {act:5s} {t.get("shares")}')
        print(f'\n[A类 有成交无裁决] {len(no_verdict)} 笔: {no_verdict}')
        print(f'[A类 有成交无台账镜像] {len(no_ledger)} 笔: {no_ledger}')
        print(f'[B类 有裁决无成交(更危险)] {len(undone)} 条: {undone}')

    fails = []
    if no_verdict:
        fails.append(f'有成交但裁决系统无记录 {len(no_verdict)} 笔: {no_verdict}')
    if undone:
        fails.append(f'⛔到期的待执行动作没有对应成交 {len(undone)} 条: {undone}')
    if fails:
        raise AssertionError('⛔成交与决策记录对不上:\n  - ' + '\n  - '.join(fails))
    if verbose:
        print('\n[门] A类裁决覆盖完整, B类无到期未执行')
    return {'no_verdict': no_verdict, 'no_ledger': no_ledger, 'undone': undone}


if __name__ == '__main__':
    try:
        check()
    except AssertionError as e:
        print(e)
        sys.exit(1)
