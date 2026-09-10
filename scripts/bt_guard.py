#!/opt/homebrew/bin/python3
"""回测口径自检 — 2026-09-10 建, 起因: 一天内三次栽在口径上。

① 用 t1(次日开盘买→当日收盘卖) 评估 B策略(当日涨停买→次日开盘卖), 结论完全反向, 差点删掉有效的换手门。
② 算"距25日高"时把当日算进滚动窗口, 导致 brk 恒非正, 突破档全空。
③ 第三次靠临时加的一行自检才拦住。

用法(每个回测脚本开头调一次):
    from bt_guard import assert_metric, assert_ratio, assert_baseline
"""
import sys


def assert_metric(name, buy_desc, sell_desc, strategy_buy, strategy_sell):
    """收益字段的买卖点必须与策略的买卖点逐字对齐, 否则拒绝继续。"""
    ok = (buy_desc == strategy_buy) and (sell_desc == strategy_sell)
    print(f"[口径] {name}: 买={buy_desc} 卖={sell_desc} | 策略: 买={strategy_buy} 卖={strategy_sell} "
          f"→ {'✅一致' if ok else '⛔不一致'}", file=sys.stderr)
    if not ok:
        raise SystemExit(f"⛔口径不一致, 拒绝出结论。字段的买卖点与策略必须逐字相同。")


def assert_ratio(name, value, lo, hi, why):
    """比例类自检: 落在合理区间外即停(如 brk>0 占比应 5%~25%, 全空或全正都是口径错)。"""
    ok = lo < value < hi
    print(f"[口径] {name}={value:.1f}% 期望({lo},{hi}) → {'✅' if ok else '⛔'} {why}", file=sys.stderr)
    if not ok:
        raise SystemExit(f"⛔{name} 落在合理区间外, 多半是口径错而非市场异常。{why}")


def assert_baseline(name, mine, known, tol_ratio=3.0):
    """新算的基线必须能对上既有研究的基线, 差一个数量级就是口径不匹配的警报。"""
    if known == 0:
        return
    r = abs(mine / known) if known else 99
    ok = (1 / tol_ratio) <= r <= tol_ratio
    print(f"[口径] {name}: 本次基线 {mine:+.2f} vs 既有 {known:+.2f} (倍数{r:.1f}) "
          f"→ {'✅' if ok else '⛔'}", file=sys.stderr)
    if not ok:
        raise SystemExit(f"⛔基线对不上既有研究({mine:+.2f} vs {known:+.2f}), 先查口径再出结论。")
