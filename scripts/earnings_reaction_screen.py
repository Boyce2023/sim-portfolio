#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""财报反应筛 — 治"财报当日跌、之后接着跌"这类被我漏掉一个月的预警

⛔缘起(2026-08-24复盘发现): 我16只持仓里,HUBB和HWM是唯二"财报当日跌+之后继续跌"的,
   而它们正是我浮亏最大的两只(-12.0K/-7.3K)。这个信号在我8/14建HUBB仓的一个月前就存在,
   我没跑这个筛所以没看见。这与30agent自审的结论同源: 规则写在纸上,系统里没有会响的铃。

⛔口径(2026-08-24 Buwen定): 不看卖方consensus surprise。"涨了就是超预期"——
   价格本身是唯一的surprise,不需要卖方那个数字当中介。故本筛只用价格,不用EPS超预期。

判定:
  双负 = 反应日跌 且 之后继续跌  → ⛔最强预警(实证: 我两只最大浮亏都是这个形态)
  高开低走 = 反应日涨 但 之后回吐  → ⚠️利好兑现
  双正 = 反应日涨 且 之后续涨      → ★真强(实证: HALO/ABNB是这个形态)
  低开高走 = 反应日跌 但 之后反弹  → 市场消化完毕

用法:
  python3 scripts/earnings_reaction_screen.py                # 扫当前美股持仓
  python3 scripts/earnings_reaction_screen.py --tickers A,B  # 扫指定标的
  python3 scripts/earnings_reaction_screen.py --signal       # 双负的发nexus信号
"""
import argparse, json, os, sys, warnings, datetime
warnings.filterwarnings('ignore')
import yfinance as yf
import pandas as pd

STATE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json"
SIGDIR = os.path.expanduser("~/.claude/nexus/signals/pending")

def holdings():
    st = json.load(open(STATE))['accounts']['us']
    pos = st['positions']
    items = list(pos.values()) if isinstance(pos, dict) else pos
    return [p['ticker'] for p in items], st

def probe(t, lookback_days=120):
    """找最近一次财报, 算反应日涨跌 + 反应日至今涨跌"""
    tk = yf.Ticker(t)
    try:
        df = tk.earnings_dates
    except Exception:
        return None
    if df is None or df.empty:
        return None
    now = pd.Timestamp.now(tz=df.index.tz) if df.index.tz else pd.Timestamp.now()
    past = df[df.index <= now]
    if past.empty:
        return None
    ts = past.index[0]                      # earnings_dates 按时间倒序, 第一条=最近一次已发生
    if (now - ts).days > lookback_days:
        return None
    h = tk.history(period='6mo')
    if h.empty:
        return None
    s = h['Close']
    idx = [x.date() for x in s.index]
    edate = ts.date()
    amc = ts.hour >= 12                     # >=12点ET视为盘后, 反应日=次一交易日
    pos = next((k for k, d in enumerate(idx) if d >= edate), None)
    if pos is None:
        return None
    rpos = pos + 1 if amc else pos
    if rpos >= len(s) or rpos < 1:
        return None
    react = (s.iloc[rpos] / s.iloc[rpos - 1] - 1) * 100
    since = (s.iloc[-1] / s.iloc[rpos] - 1) * 100
    if react < 0 and since < 0:   verdict, flag = "双负", "⛔"
    elif react > 0 and since < -3: verdict, flag = "高开低走", "⚠️"
    elif react > 0 and since > 0:  verdict, flag = "双正", "★"
    else:                          verdict, flag = "低开高走", ""
    return dict(t=t, date=str(edate), when='盘后' if amc else '盘前',
                react=round(float(react), 2), since=round(float(since), 2),
                total=round(float(react + since), 2), px=round(float(s.iloc[-1]), 2),
                verdict=verdict, flag=flag, days_since=(now.date() - edate).days)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tickers', help='逗号分隔; 缺省=当前美股持仓')
    ap.add_argument('--lookback', type=int, default=120, help='只看N天内的财报')
    ap.add_argument('--signal', action='store_true', help='双负标的发nexus信号')
    a = ap.parse_args()

    if a.tickers:
        tk = [x.strip().upper() for x in a.tickers.split(',') if x.strip()]
        st = None
    else:
        tk, st = holdings()

    print("=" * 96)
    print("财报反应筛 · 只看价格不看卖方超预期(2026-08-24 Buwen口径: 涨了就是超预期)")
    print("=" * 96)
    rows = []
    for t in tk:
        r = probe(t, a.lookback)
        if r: rows.append(r)
    rows.sort(key=lambda x: x['total'])
    print(f"{'股':6}{'财报日':>12}{'时点':>6}{'当日%':>9}{'之后%':>9}{'合计%':>9}  {'判定':10}{'距今':>5}")
    for r in rows:
        print(f"{r['t']:6}{r['date']:>12}{r['when']:>6}{r['react']:+9.2f}{r['since']:+9.2f}{r['total']:+9.2f}  {r['flag']}{r['verdict']:9}{r['days_since']:4}天")
    bad = [r for r in rows if r['verdict'] == '双负']
    miss = [t for t in tk if t not in {r['t'] for r in rows}]
    print("-" * 96)
    if bad:
        print(f"⛔ 双负 {len(bad)} 只: {', '.join(r['t'] for r in bad)}")
        print("   ⛔本筛无前瞻预测力(2026-08-31 以535只中报样本证伪):")
        print("      财报当日跌幅 vs 之后走势 相关仅 -0.100(轻微均值回归); 双负组全程中位-7.48%是同义反复。")
        print("      旧依据'HUBB/HWM两只双负=浮亏最大'仅2个案例, 大样本不支持。")
        print("   动作: 只作thesis三问复核提示。⛔读到⛔不得当作卖出理由; 去留由三问+综合分排名定。")
    else:
        print("✓ 无双负标的")
    if miss:
        print(f"({len(miss)}只窗口内无财报或数据不足: {', '.join(miss)})")

    if a.signal and bad:
        os.makedirs(SIGDIR, exist_ok=True)
        ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        exp = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
        fn = os.path.join(SIGDIR, f"sig-{ts}-earnings_screen-double_negative.json")
        json.dump(dict(created=datetime.datetime.now().isoformat(), **{'from': 'earnings_reaction_screen'},
                       priority='high', expires=exp, market='us',
                       title=f"财报反应双负 {len(bad)}只: " + ','.join(r['t'] for r in bad),
                       detail=bad,
                       action="进thesis三问复核队列(仅复核提示, ⛔非看空信号)",
                       empirical_note=("⛔2026-08-31 以535只中报样本检验本筛: 双负是**事后分类**不是前瞻信号。"
                                       "财报当日跌幅与之后走势相关仅 -0.100(轻微均值回归); 双负组全程中位-7.48% "
                                       "属同义反复(定义上两段都跌)。本筛唯一作用是提示thesis三问复核, "
                                       "读到⛔不得当作卖出理由。原始依据仅HUBB/HWM两个案例, 已被大样本证伪。")),
                  open(fn, 'w'), ensure_ascii=False, indent=1)
        print(f"[SIGNAL] 已写入 {fn}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
