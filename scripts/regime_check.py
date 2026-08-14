#!/usr/bin/env python3
"""
月度 Regime 判定层 — 每日扫描前先跑这个,回答"这个月的钱在从哪流向哪"

缺口来源(2026-08-14 Buwen指出): 70领域扫描是横截面,只答"今天谁涨跌",
不答"本月什么风格在赚钱"。结果是仓位停在七月的供给侧稀缺主线,
八月的降息+超跌反转主线完全没吃到(VST/TRGP/CB 是8月最差三仓)。

三个轴,全部用价格数据定性,不用叙事:
  1. 风格轴: 成长vs价值 / 大盘vs小盘
  2. 久期轴: 长端方向 + 久期敏感资产相对强度 → 降息交易 or 通胀交易
  3. 动量轴: 上月最弱N个板块在本月表现 → 趋势延续 or 均值回归

用法:
  python3 regime_check.py                # 当月 vs 上月
  python3 regime_check.py --months 3     # 回看3个月
"""
import argparse
import sys
from datetime import date

import yfinance as yf

SECTORS = {
    "XLK": "科技", "XLF": "金融", "XLE": "能源", "XLV": "医疗", "XLU": "公用",
    "XLRE": "REITs", "XLI": "工业", "XLP": "必需消费", "XLY": "可选消费",
    "XLB": "材料", "XLC": "通信", "SMH": "半导体", "IGV": "软件",
    "XBI": "生物科技", "ITA": "国防", "XME": "金属矿业", "KRE": "区域银行",
    "ICLN": "清洁能源", "GLD": "黄金", "TLT": "长债",
}
STYLE = {"QQQ": "成长", "RSP": "等权重", "IWM": "小盘", "SPY": "大盘", "IWD": "价值", "IWF": "成长风格"}
DURATION = {"TLT": "20年+国债", "XLRE": "REITs", "XLU": "公用", "^TNX": "10年期收益率"}


def month_bounds(y, m):
    from calendar import monthrange
    return f"{y}-{m:02d}-01", f"{y}-{m:02d}-{monthrange(y, m)[1]:02d}"


def ret(ticker, a, b, hist_cache):
    h = hist_cache.get(ticker)
    if h is None or h.empty:
        return None
    c = h["Close"]
    s = c[(c.index.strftime("%Y-%m-%d") >= a) & (c.index.strftime("%Y-%m-%d") <= b)]
    if len(s) < 2:
        return None
    return (float(s.iloc[-1]) / float(s.iloc[0]) - 1) * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=3, help="回看月数(含当月)")
    ap.add_argument("--today", default=None, help="覆盖今天日期 YYYY-MM-DD(回测用)")
    a = ap.parse_args()

    today = date.fromisoformat(a.today) if a.today else date.today()
    periods = []
    y, m = today.year, today.month
    for i in range(a.months):
        yy, mm = (y, m - i) if m - i > 0 else (y - 1, m - i + 12)
        s, e = month_bounds(yy, mm)
        if i == 0:
            e = today.isoformat()          # 当月只算到今天
        periods.append((f"{yy}-{mm:02d}", s, e))
    periods.reverse()                       # 旧→新

    start = periods[0][1]
    universe = set(SECTORS) | set(STYLE) | {"^TNX"}
    cache = {}
    for t in universe:
        try:
            cache[t] = yf.Ticker(t).history(start=start)
        except Exception:
            cache[t] = None

    print(f"# Regime 判定 · 基准日 {today} · 回看 {a.months} 个月\n")

    # ── 板块表 ──────────────────────────────────────────
    print("## 板块月度收益(%)")
    hdr = "板块      " + "".join(f"{p[0]:>10}" for p in periods)
    print(hdr)
    table = {}
    for t, n in SECTORS.items():
        row = [ret(t, s, e, cache) for _, s, e in periods]
        table[n] = row
        cells = "".join(f"{v:+9.2f} " if v is not None else "      n/a " for v in row)
        print(f"{n:<10}{cells}")

    cur = periods[-1][0]
    valid = {n: r[-1] for n, r in table.items() if r[-1] is not None}
    top = sorted(valid.items(), key=lambda x: -x[1])[:5]
    bot = sorted(valid.items(), key=lambda x: x[1])[:5]
    print(f"\n{cur} 最强5: " + " / ".join(f"{n} {v:+.1f}%" for n, v in top))
    print(f"{cur} 最弱5: " + " / ".join(f"{n} {v:+.1f}%" for n, v in bot))

    # ── 轴1 风格 ────────────────────────────────────────
    print("\n## 轴1 · 风格")
    _, s, e = periods[-1]
    qqq, rsp = ret("QQQ", s, e, cache), ret("RSP", s, e, cache)
    iwm, spy = ret("IWM", s, e, cache), ret("SPY", s, e, cache)
    if None not in (qqq, rsp):
        d = qqq - rsp
        print(f"  成长(QQQ) {qqq:+.2f}% vs 等权重(RSP) {rsp:+.2f}% → 差 {d:+.2f}pp "
              f"[{'成长占优' if d > 0.5 else '价值/均衡占优' if d < -0.5 else '无明显偏好'}]")
    if None not in (iwm, spy):
        d = iwm - spy
        print(f"  小盘(IWM) {iwm:+.2f}% vs 大盘(SPY) {spy:+.2f}% → 差 {d:+.2f}pp "
              f"[{'小盘占优' if d > 0.5 else '大盘占优' if d < -0.5 else '无明显偏好'}]")

    # ── 轴2 久期 ────────────────────────────────────────
    print("\n## 轴2 · 久期(判降息交易 or 通胀交易)")
    tnx_h = cache.get("^TNX")
    if tnx_h is not None and not tnx_h.empty:
        c = tnx_h["Close"]
        sub = c[(c.index.strftime("%Y-%m-%d") >= s) & (c.index.strftime("%Y-%m-%d") <= e)]
        if len(sub) >= 2:
            bp = (float(sub.iloc[-1]) - float(sub.iloc[0])) * 100
            print(f"  10年期收益率 {float(sub.iloc[0]):.3f}% → {float(sub.iloc[-1]):.3f}% "
                  f"({bp:+.0f}bp) [{'下行=利好久期' if bp < 0 else '上行=压制久期'}]")
    for t in ("TLT", "XLRE", "XLU"):
        v = ret(t, s, e, cache)
        if v is not None and spy is not None:
            print(f"  {DURATION.get(t, t):<10} {v:+6.2f}%  相对SPY {v - spy:+6.2f}pp")
    dur = [ret(t, s, e, cache) for t in ("TLT", "XLRE", "XLU")]
    dur = [x for x in dur if x is not None]
    if dur and spy is not None:
        avg = sum(dur) / len(dur)
        print(f"  → 久期篮子均值 {avg:+.2f}% vs SPY {spy:+.2f}% = "
              f"{'降息交易在跑' if avg - spy > 0.5 else '久期在被卖' if avg - spy < -0.5 else '中性'}")

    # ── 轴3 动量 vs 均值回归 ────────────────────────────
    if len(periods) >= 2:
        print("\n## 轴3 · 动量 vs 均值回归")
        _, ps, pe = periods[-2]
        prev = {n: ret(t, ps, pe, cache) for t, n in SECTORS.items()}
        prev = {n: v for n, v in prev.items() if v is not None}
        pw = sorted(prev.items(), key=lambda x: x[1])[:5]
        pb = sorted(prev.items(), key=lambda x: -x[1])[:5]
        w_now = [valid[n] for n, _ in pw if n in valid]
        b_now = [valid[n] for n, _ in pb if n in valid]
        if w_now and b_now:
            wm, bm = sum(w_now) / len(w_now), sum(b_now) / len(b_now)
            print(f"  上月最弱5({', '.join(n for n, _ in pw)}) 本月均值 {wm:+.2f}%")
            print(f"  上月最强5({', '.join(n for n, _ in pb)}) 本月均值 {bm:+.2f}%")
            gap = wm - bm
            verdict = ("均值回归(超跌反转在赚钱)" if gap > 1.5 else
                       "动量延续(强者恒强)" if gap < -1.5 else "无明显模式")
            print(f"  → 弱者-强者 = {gap:+.2f}pp [{verdict}]")

    # ── 一句话 regime ──────────────────────────────────
    print("\n## Regime 一句话")
    bits = []
    if None not in (qqq, rsp):
        bits.append("成长" if qqq - rsp > 0.5 else "价值" if qqq - rsp < -0.5 else "风格中性")
    if dur and spy is not None:
        bits.append("降息交易" if sum(dur) / len(dur) - spy > 0.5 else
                    "久期承压" if sum(dur) / len(dur) - spy < -0.5 else "久期中性")
    if len(periods) >= 2 and w_now and b_now:
        bits.append("超跌反转" if gap > 1.5 else "动量延续" if gap < -1.5 else "无动量模式")
    print("  " + cur + ": " + " + ".join(bits))
    print("\n⛔ 用法提醒: 这是资金流的月度切片,不是产业判断。"
          "产业研究(供给侧/到期日)答'买什么能长期持有',本层答'这个月什么风格在赚钱'。两者不可互相替代。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
