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

⛔本脚本只告警不下单。执行永远是人的动作(T0)。
"""
import json, os, sys, datetime, argparse

R = os.path.expanduser('~/claude-projects/sim-portfolio')
PORTFOLIO = f'{R}/portfolio_state.json'
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


def fetch_prices(tickers):
    """返回 {ticker: price}。取不到的不放进字典, 由调用方判完整性。"""
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
    return out


def run(verbose=True, notify=False):
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
    prices = fetch_prices(tickers)

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
        print("🚨  ⛔本脚本只告警不下单, 执行是人的动作(T0)")
        print("🚨"*36)
    elif near:
        print(f"\n⚠️  无击穿, 但 {len(near)} 只逼近灾难线 3% 以内:")
        for t, px, ln, d in near: print(f"     {t}: ${px:.2f} 距灾难线 {d:+.2f}%")
    elif not skipped:
        print(f"\n✅  {len(rows)}/{len(positions)} 只全部检查完毕, 无击穿, 最深 {min(r[4] for r in rows):+.2f}%")

    if notify and (breaches or skipped):
        rec = dict(ts=datetime.datetime.now().isoformat(timespec='seconds'),
                   **{'from': 'us-disaster-check'}, kind='alert',
                   level='crit' if breaches else 'warn',
                   text=(f"美股灾难线: 击穿{len(breaches)}只 漏检{len(skipped)}只" if breaches
                         else f"美股灾难线检查不完整: {len(skipped)}只未判定"))
        try:
            with open(INBOX, 'a') as f: f.write(json.dumps(rec, ensure_ascii=False)+'\n')
        except Exception as e:
            print(f"⛔ 写inbox失败: {e}", file=sys.stderr)
    print(f"\n{'='*72}\n")
    # ⛔退出码语义: 0=全部检查完且无击穿 / 1=有击穿 / 2=无法判断(结构坏/读不到)
    # 3=检查不完整(有漏检)。⛔漏检不能返回0, 否则调度器按退出码判会当成"跑成功了"。
    if breaches: return 1
    if skipped:  return 3
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--notify', action='store_true', help='击穿或漏检时写 us inbox')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    sys.exit(run(verbose=not a.quiet, notify=a.notify))
