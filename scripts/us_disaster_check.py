#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""美股灾难线检查器 (2026-09-08 建)

⛔为什么会有这个文件: 灾难线-12% 是 08-27 纠偏后**美股唯一保留的价格规则**
(memory/feedback_us_value_only.md 第32行; 项目CLAUDE.md:123 有完整口径),
但代码库里只有 auto_stop_check.py 且它写死读 accounts["a_share"], 美股16只
一直靠人手算。规则写在纸上、机制不存在——与 .dxy_count.json 同族。

⛔美股口径与A股不同(CLAUDE.md:123): 触发 = **当日减半 + thesis三问强制复核**,
**连续2个交易日收盘仍在线下才清余仓**。不是A股那套直接清仓。
理由: 采纳A股B1回测"完全不设止损更差" + C2"触发即全卖仅36%卖对率"——价值在触发不在执行。

⛔2026-09-29 起加 --enqueue: 击穿时自动挂 pending_order, 由同一轮 daily_run 的 Step 4b2 执行。
  为什么: 原设计"只告警不下单, 执行是人的动作"。09-24、09-25 RTX 连续两日收盘在线下,
  本脚本两天都报了击穿, 但 us session 离线, 清余仓晚了一天半。告警写进 inbox 没人读 = 规则没执行。
  授权: 模拟盘一切买卖自主执行(memory feedback_monitor_autonomous_exec, 09-08 用户原话
  "你检测有问题就执行……如果你真的会忘为什么不代码化")。
  口径: 当天收盘首次在线下 → 挂减半; 前一交易日收盘也在线下 → 挂清余仓。
  幂等: .disaster_state.json 记每只票最后一次动作对应的收盘日, 同一收盘日不重复挂单;
  上一轮遗留未清的本脚本挂单在新一轮开头先撤掉, 防 Step 4b2 清单失败时第二天重复减半。
"""
import json, os, sys, datetime, argparse

R = os.path.expanduser('~/claude-projects/sim-portfolio')
PORTFOLIO = f'{R}/portfolio_state.json'
DSTATE = f'{R}/.disaster_state.json'
ORDER_SOURCE = 'us_disaster_check'
INBOX = os.path.expanduser('~/.claude/session-inbox/us.jsonl')
FS = os.path.expanduser('~/.claude/session-remote/fs-reply.sh')
RATIO = 0.88          # 灾难线 = 成本 × 0.88
NEAR = 0.03           # 距灾难线 3% 以内列为逼近


def get_us_positions(pf):
    """⛔三态: 结构坏了 ≠ 没有持仓。返回 (positions, error)。"""
    try:
        acc = pf["accounts"]["us"]
    except (KeyError, TypeError) as e:
        return None, f"portfolio_state.json 结构异常, 读不到 accounts.us ({type(e).__name__})"
    pos = acc.get("positions")
    if pos is None:
        return None, "accounts.us 下没有 positions 字段"
    if not isinstance(pos, list):
        return None, f"positions 不是列表而是 {type(pos).__name__}"
    return pos, None


def last_completed_session():
    """最近一个常规时段已走完的交易日, 从 SPY 5分钟线里读出来。
    ⛔为什么不用 date.today() 或"减一天": 那是猜。休市、半日市、夏令时都会让猜错,
      而猜错的后果是拿旧价当今价, 输出和"一切正常"长得一模一样。
    返回 (date, None) 或 (None, 原因)。"""
    try:
        import yfinance as yf, pandas as pd
        h = yf.Ticker('SPY').history(period='5d', interval='5m')
        if h.empty:
            return None, 'SPY 5分钟线返回空'
        et = h.index.tz_convert('America/New_York')
        f = pd.DataFrame({'d': et.date, 'm': et.hour * 60 + et.minute})
        reg = f[(f.m >= 570) & (f.m <= 960)]          # 09:30~16:00 常规时段
        cnt = reg.groupby('d').size()
        done = cnt[cnt >= 75]                          # 完整一天=78根, 留3根容差
        if done.empty:
            return None, '近5日没有常规时段走完的交易日'
        return max(done.index), None
    except Exception as e:
        return None, f'{type(e).__name__}: {str(e)[:80]}'


def fetch_prices(tickers, target=None):
    """返回 {ticker: (price, date)}。取不到的不放进字典, 由调用方判完整性。
    ⛔ 日线在收盘后数小时内常常还是 NaN。原来的写法 dropna() 后取末根, 会静默退回
      上一个交易日, 并且照常打绿勾——2026-09-09 实测: 9/8 已收盘, 它拿 9/4 的价格报
      "16/16 无击穿"。现在改成: 缺 target 那天的, 用 5分钟线常规时段末根补回真收盘价。
    ⛔ 只取 <=16:00 的常规时段, 不用盘后价——扳机一律收盘价判定。"""
    out = {}
    try:
        import yfinance as yf
        d = yf.download(tickers, period='5d', progress=False, auto_adjust=False)['Close']
        d = d[d.index.dayofweek < 5]
        for t in tickers:
            try:
                s = d[t].dropna()
                if len(s):
                    out[t] = (float(s.iloc[-1]), s.index[-1].date())
            except Exception:
                pass
    except Exception as e:
        print(f"  ⛔ 批量取价整体失败: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)

    if target:
        need = [t for t in tickers if out.get(t, (None, None))[1] != target]
        if need:
            try:
                import yfinance as yf, pandas as pd
                m = yf.download(need, period='2d', interval='5m', progress=False,
                                auto_adjust=False, prepost=False)['Close']
                if not m.empty:
                    et = m.index.tz_convert('America/New_York')
                    keep = (pd.Series(et.date).values == target) & \
                           (pd.Series(et.hour * 60 + et.minute).values <= 960)
                    m = m[keep]
                    for t in need:
                        try:
                            s = (m[t] if len(need) > 1 else m).dropna()
                            if len(s):
                                out[t] = (float(s.iloc[-1]), target)
                        except Exception:
                            pass
            except Exception as e:
                print(f"  ⛔ 分钟线补价失败: {type(e).__name__}: {str(e)[:100]}", file=sys.stderr)
    return out


def prev_close_below(ticker, line, target):
    """target 之前最近一个交易日的收盘是否 <= 灾难线。取不到返回 None(调用方按首日处理)。"""
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period='15d', auto_adjust=False)['Close'].dropna()
        h = h[[d.date() < target for d in h.index]]
        if not len(h):
            return None
        return float(h.iloc[-1]) <= line
    except Exception:
        return None


def plan_orders(positions, breaches, target, prev_below, pending, dstate, trade_log=()):
    """纯函数, 不碰文件, 便于单测。
    返回 (orders, dstate_updates, notes)。
    breaches: [(ticker, cost, px, line, pl)]; prev_below(ticker, line, target) -> True/False/None"""
    held = {p['ticker']: p.get('shares') or 0 for p in positions}
    already = {o.get('ticker') for o in pending if o.get('source') == ORDER_SOURCE}
    orders, upd, notes = [], {}, []
    for t, cost, px, line, pl in breaches:
        sh = int(held.get(t) or 0)
        if sh <= 0:
            continue
        if t in already:
            notes.append(f"{t}: 已有本脚本挂单未执行, 不重复挂"); continue
        if (dstate.get(t) or {}).get('close_date') == str(target):
            notes.append(f"{t}: {target} 收盘已处理过, 不重复挂"); continue
        # 收盘日之后已有该票卖出成交(手工执行过) → 不再挂, 不靠人记得登记 .disaster_state.json
        if any(str(x.get('ticker')) == t and str(x.get('action', '')).lower() == 'sell'
               and str(x.get('date') or '')[:10] > str(target) for x in trade_log):
            notes.append(f"{t}: {target} 收盘后已有卖出成交, 视为已处理, 不重复挂")
            upd[t] = {'close_date': str(target), 'action': 'manual', 'line': line}; continue
        pb = prev_below(t, line, target)
        if pb:
            kind, n = 'clear', None
            why = f"连续第二个交易日收盘在灾难线下({target}收{px:.2f}<={line:.2f}, 前一交易日亦在线下), 清余仓"
        else:
            kind, n = 'halve', sh // 2
            why = (f"{target}收{px:.2f}首次跌破灾难线{line:.2f}(成本{cost:.2f}, {pl:+.1f}%), 当日减半锁风险"
                   + ("; 前一交易日收盘取不到, 按首日处理" if pb is None else ""))
            if n <= 0:
                kind, n = 'clear', None
                why += "; 仅1股无法减半, 改为清仓"
        orders.append({'ticker': t, 'action': 'sell', 'shares': n, 'account': 'us',
                       'source': ORDER_SOURCE, 'kind': kind, 'close_date': str(target),
                       'created_at': datetime.datetime.now().isoformat(timespec='seconds'),
                       'reason': f"灾难线{kind}: {why}。thesis三问复核由us session事后补做"})
        upd[t] = {'close_date': str(target), 'action': kind, 'line': line}
    return orders, upd, notes


def enqueue(positions, breaches, target, dry=False):
    """把 plan_orders 的结果写进 pending_orders(走 portfolio_io, 不直写 state)。返回挂单列表。"""
    try:
        dstate = json.load(open(DSTATE))
    except FileNotFoundError:
        dstate = {}
    except Exception as e:
        print(f"⛔ {DSTATE} 损坏({type(e).__name__}), 无法判断是否已处理过, 本轮不自动挂单")
        return None
    pf = json.load(open(PORTFOLIO))
    pending = pf.get('pending_orders') or []
    # 撤掉上一轮遗留的本脚本挂单(收盘日不是本轮 target 的), 防止第二天重复执行
    stale = [o for o in pending if o.get('source') == ORDER_SOURCE and o.get('close_date') != str(target)]
    keep = [o for o in pending if o not in stale]
    orders, upd, notes = plan_orders(positions, breaches, target, prev_close_below, keep, dstate,
                                     pf.get('trade_log') or [])
    for n in notes:
        print(f"  [自动挂单] {n}")
    for o in stale:
        print(f"  [自动挂单] ⛔ 撤掉遗留挂单 {o['ticker']} {o.get('kind')} (收盘日 {o.get('close_date')}), 上一轮未被执行或未被清除")
    for o in orders:
        print(f"  [自动挂单] {'(dry)' if dry else ''} sell {o['ticker']} {o['shares'] or '全部'}股 [{o['kind']}] {o['reason']}")
    if dry or (not orders and not stale and not upd):
        return orders
    if orders or stale:
        pf['pending_orders'] = keep + orders
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from portfolio_io import save_portfolio
        save_portfolio(pf, reason=f"us_disaster_check: 灾难线自动挂单 {[o['ticker'] for o in orders]}", auto_sync=False)
    dstate.update(upd)
    with open(DSTATE, 'w') as f:
        json.dump(dstate, f, ensure_ascii=False, indent=1)
    return orders


def run(verbose=True, notify=False, do_enqueue=False, dry=False):
    try:
        pf = json.load(open(PORTFOLIO))
    except Exception as e:
        print(f"⛔ 读不到 portfolio_state.json: {type(e).__name__} — 无法判断, 不是'安全'")
        return 2
    positions, err = get_us_positions(pf)
    if err:
        print(f"⛔ {err} — 无法判断灾难线, 需人工检查")
        return 2
    if not positions:
        print("⛔ 美股持仓为空。若确实空仓则正常; 若不该空, 说明state有问题")
        return 0

    tickers = [p['ticker'] for p in positions]
    target, terr = last_completed_session()
    if terr:
        # ⛔判不出目标日 = 新鲜度无法断言 = 给不出安全结论。
        # 不许"打一行警告然后照常打绿勾"——2026-09-09 注入测试当场抓到这个复发。
        print("⛔" * 36)
        print(f"⛔  判不出最近已收盘交易日: {terr}")
        print("⛔  无法确认手上的价是不是最新收盘价, 因此**本次不做安全判定**。")
        print("⛔  下面的表只作参考, 不构成结论。")
        print("⛔" * 36)
    prices = fetch_prices(tickers, target)

    rows, skipped, breaches, near = [], [], [], []
    for p in positions:
        t = p['ticker']
        cost = p.get('avg_cost')
        if not cost or cost <= 0:
            skipped.append((t, '无avg_cost')); continue
        got = prices.get(t)
        if got is None:
            cached = p.get('current_price')
            if cached:
                got = (float(cached), None)
                if verbose: print(f"  [{t}] 实时取价失败, 降级用 state 缓存价 ${cached}")
            else:
                skipped.append((t, '实时+缓存均无价')); continue
        px, pxdate = got
        line = round(cost * RATIO, 4)
        pl = (px / cost - 1) * 100
        dist = (px / line - 1) * 100
        rows.append((t, cost, px, line, pl, dist, pxdate))
        if px <= line: breaches.append((t, cost, px, line, pl))
        elif dist <= NEAR * 100: near.append((t, px, line, dist))

    today = datetime.date.today()
    print(f"\n{'='*72}")
    print(f"  美股灾难线检查 | {datetime.datetime.now():%Y-%m-%d %H:%M} | 阈值 成本×{RATIO}")
    print(f"{'='*72}")
    print(f"  {'代码':<7}{'成本':>10}{'现价':>10}{'灾难线':>10}{'较成本%':>10}{'距灾难线%':>12}  价格日")
    for t, c, px, ln, pl, dist, pd in sorted(rows, key=lambda r: r[5]):
        mark = ' 🚨' if px <= ln else (' ⚠️' if dist <= NEAR*100 else '')
        print(f"  {t:<7}{c:>10.2f}{px:>10.2f}{ln:>10.2f}{pl:>+9.2f}%{dist:>+11.2f}%  {pd or '缓存'}{mark}")

    # ⛔新鲜度优先: 用旧价判灾难线 = 拿上周的体温说人今天没发烧
    stale = [(t, d) for t, c, px, ln, pl, dist, d in rows if target and d != target]
    if stale:
        print("\n" + "⛔" * 36)
        print(f"⛔  价格不新鲜: 最近已收盘交易日是 {target}, 但下列 {len(stale)} 只用的是更早的价")
        for t, d in stale:
            print(f"⛔    {t} — 价格日 {d or '缓存(无日期)'}")
        print("⛔  ⛔本次结果**不构成今日安全结论**, 请补价后重跑")
        print("⛔" * 36)

    # ⛔完整性优先: 检查数 != 持仓数 就不打绿勾
    if skipped:
        print("\n" + "⛔"*36)
        print(f"⛔  检查不完整: {len(positions)} 只持仓中 {len(skipped)} 只未能判定")
        for t, why in skipped: print(f"⛔    {t} — {why}")
        print(f"⛔  已检查 {len(rows)} 只, 这**不构成全仓安全结论**")
        print("⛔"*36)
    if breaches:
        print("\n" + "🚨"*36)
        print("🚨  灾难线击穿 — 美股口径: 当日减半 + thesis三问强制复核")
        print("🚨  ⛔连续2个交易日收盘仍在线下才清余仓, 不是直接清仓(CLAUDE.md:123)")
        for t, c, px, ln, pl in breaches:
            print(f"🚨    {t}: 现价${px:.2f} 跌破灾难线${ln:.2f} (成本${c:.2f}, {pl:+.2f}%)")
        print("🚨"*36)

    queued = []
    if do_enqueue and breaches:
        # ⛔只对价格日==最近已收盘交易日的击穿挂单; 新鲜度判不了就不挂(旧价不能触发真实卖出)
        fresh = {t for t, c, px, ln, pl, dist, d in rows if target and d == target}
        ok = [b for b in breaches if b[0] in fresh]
        if len(ok) < len(breaches):
            print(f"  [自动挂单] ⛔ {len(breaches)-len(ok)} 只击穿的价格不是 {target} 收盘价, 不自动挂单, 需人工确认")
        if ok:
            queued = enqueue(positions, ok, target, dry=dry) or []
    elif near:
        print(f"\n⚠️  无击穿, 但 {len(near)} 只逼近灾难线 3% 以内:")
        for t, px, ln, d in near: print(f"     {t}: ${px:.2f} 距灾难线 {d:+.2f}%")
    elif not skipped and not stale and target:
        print(f"\n✅  {len(rows)}/{len(positions)} 只全部检查完毕 (收盘日 {target}), 无击穿, 最深 {min(r[4] for r in rows):+.2f}%")
    elif not target:
        print(f"\n⛔  {len(rows)} 只已列出但**新鲜度未知**, 不打安全结论。最深读数 {min(r[4] for r in rows):+.2f}% 仅供参考。")

    if notify and (breaches or skipped or stale or not target):
        rec = dict(ts=datetime.datetime.now().isoformat(timespec='seconds'),
                   **{'from': 'us-disaster-check'}, kind='alert',
                   level='crit' if breaches else 'warn',
                   text=(f"美股灾难线: 击穿{len(breaches)}只 漏检{len(skipped)}只"
                         + (f" | 已自动挂单{len(queued)}笔: " + ', '.join(f"{o['ticker']} {o['kind']}" for o in queued)
                            + " (本轮 daily_run Step 4b2 执行), 请补 thesis 三问复核" if queued and not dry else "")
                         if breaches
                         else (f"美股灾难线检查不完整: {len(skipped)}只未判定" if skipped
                               else (f"美股灾难线价格不新鲜: {len(stale)}只非{target}收盘价, 结论不可用" if stale
                                     else "美股灾难线: 判不出最近收盘交易日, 本次未做安全判定"))))
        try:
            with open(INBOX, 'a') as f: f.write(json.dumps(rec, ensure_ascii=False)+'\n')
        except Exception as e:
            print(f"⛔ 写inbox失败: {e}", file=sys.stderr)
    print(f"\n{'='*72}\n")
    # ⛔退出码语义: 0=全部检查完且无击穿 / 1=有击穿 / 2=无法判断(结构坏/读不到)
    # 3=检查不完整(有漏检)。⛔漏检不能返回0, 否则调度器按退出码判会当成"跑成功了"。
    if breaches: return 1
    if not target: return 2      # 新鲜度判不了 = 无法判断, 不是"安全"
    if skipped:  return 3
    if stale:    return 3
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--notify', action='store_true', help='击穿或漏检时写 us inbox')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--enqueue', action='store_true', help='击穿时自动挂 pending_order(减半/清余仓)')
    ap.add_argument('--dry', action='store_true', help='配合 --enqueue: 只打印计划挂单, 不写文件')
    a = ap.parse_args()
    sys.exit(run(verbose=not a.quiet, notify=a.notify, do_enqueue=a.enqueue, dry=a.dry))
