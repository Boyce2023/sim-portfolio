#!/usr/bin/env python3
"""两条铁律的可执行实现 (Buwen 2026-08-26定)

铁律1: 财报出了股价跌 = 不及预期。不管公告数字多好看。
铁律2: 长期下跌 = 基本面有问题(除非极端情绪冲击),但这不等于不能买。

⛔为什么单独成模块而不是埋进某个Gate:
   ①买入(execute_trade买入gate)/卖出(portfolio_trend_check)/扫描(workflow深扫)三处都要用
   ②必须可被单独测试——我今年多次出现"规则写了但没接上"(plan_consistency_check零调用/
     D6死代码静默失败3个月/位置门在prompt里复活),独立模块+调用点计数是防这个的唯一办法
"""
from __future__ import annotations
import json, urllib.request, datetime

TENCENT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={m}{c},day,{a},{b},60,qfq"


def _kline(code: str, start: str, end: str):
    c = str(code).zfill(6)
    m = 'sh' if c[0] in '65' else ('bj' if c.startswith(('4', '8', '92')) else 'sz')
    try:
        d = json.load(urllib.request.urlopen(
            TENCENT.format(m=m, c=c, a=start, b=end), timeout=8))['data'][f'{m}{c}']
        return d.get('qfqday') or d.get('day') or []
    except Exception:
        return []


def rule1_earnings_reaction(code: str, disclose_date: str, as_of: str | None = None):
    """铁律1: 财报披露后股价累计跌 = 不及预期。

    返回 dict:
      verdict: 'MISS'(不及预期) / 'BEAT'(超预期) / 'UNKNOWN'(数据不足)
      chg_1d / chg_3d / chg_5d / chg_todate: 披露日收盘价起算的累计涨跌%
    ⛔判定只看价格,不看财报数字——这正是铁律1的全部意义。
    """
    as_of = as_of or datetime.date.today().isoformat()
    start = (datetime.date.fromisoformat(disclose_date) - datetime.timedelta(days=10)).isoformat()
    rows = _kline(code, start, as_of)
    if not rows:
        return {'verdict': 'UNKNOWN', 'why': '取不到K线'}
    base = next((r for r in rows if r[0] == disclose_date), None)
    if base is None:
        return {'verdict': 'UNKNOWN', 'why': f'披露日{disclose_date}非交易日或无数据'}
    i = rows.index(base)
    b = float(base[2])
    out = {'base_close': b, 'disclose_date': disclose_date}
    for n, k in ((1, 'chg_1d'), (3, 'chg_3d'), (5, 'chg_5d')):
        out[k] = round((float(rows[i + n][2]) / b - 1) * 100, 2) if i + n < len(rows) else None
    out['chg_todate'] = round((float(rows[-1][2]) / b - 1) * 100, 2)
    # 判定: 优先用5日,不足则用现有最长窗口
    ref = next((out[k] for k in ('chg_5d', 'chg_3d', 'chg_1d') if out.get(k) is not None),
               out['chg_todate'])
    out['verdict'] = 'MISS' if ref < 0 else 'BEAT'
    out['ref_used'] = ref
    return out


def rule2_long_decline(code: str, as_of: str | None = None, window: int = 40, thresh: float = -15.0):
    """铁律2: 长期下跌 = 基本面有问题(但不等于不能买)。

    返回 dict:
      declining: bool  近window个交易日累计跌幅是否超过thresh
      msg: 给决策者看的提示 —— ⛔不给"买/不买"结论,只强制承认"有我没看懂的东西"
    """
    as_of = as_of or datetime.date.today().isoformat()
    start = (datetime.date.fromisoformat(as_of) - datetime.timedelta(days=window * 2 + 30)).isoformat()
    rows = _kline(code, start, as_of)
    if len(rows) < window + 1:
        return {'declining': None, 'why': '数据不足'}
    chg = (float(rows[-1][2]) / float(rows[-1 - window][2]) - 1) * 100
    out = {'chg_window': round(chg, 2), 'window': window, 'declining': chg <= thresh}
    if out['declining']:
        out['msg'] = (
            f"近{window}个交易日累计{chg:+.1f}%。铁律2: 长跌一定对应某个基本面问题——\n"
            f"  ⛔不许说'基本面很好只是被误杀'(那是死扛的根源)\n"
            f"  ⛔也不许因为它跌就拒绝配置(那会永远踏空回撤中的好公司,如英伟达)\n"
            f"  ✅正确姿态: 承认下跌指向了我还没看懂的东西, 说清楚那是什么, 再决定买/不买。")
    return out


def check_all(code: str, disclose_date: str | None = None, as_of: str | None = None):
    """两条铁律一起跑,供买入gate/卖出检查/扫描调用"""
    res = {'ticker': code}
    if disclose_date:
        res['rule1'] = rule1_earnings_reaction(code, disclose_date, as_of)
    res['rule2'] = rule2_long_decline(code, as_of)
    return res


if __name__ == '__main__':
    import sys
    for tk, dd in [('600549', '2026-08-21'), ('688627', '2026-08-19'), ('603259', '2026-08-04')]:
        r = check_all(tk, dd)
        r1 = r.get('rule1', {})
        print(f"{tk}: 铁律1={r1.get('verdict')} (披露后{r1.get('ref_used')}%) | "
              f"铁律2 近40日{r.get('rule2', {}).get('chg_window')}% declining={r.get('rule2', {}).get('declining')}")
