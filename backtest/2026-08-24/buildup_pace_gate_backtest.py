#!/usr/bin/env python3
"""
Backtest: 建仓节奏gate (单日净建仓<=NAV X% / 近5日<=NAV Y%) 反事实检验

背景: strategy_astock.md 2026-08-24加的时间集中度上限
      单日 <=10% NAV / 连续5日 <=25% NAV
实测:  8月全部建仓额98%压在08-06~08-17共9个交易日,单日最高到NAV的63%(08-06买5866430/
       前收9973979/... 注: 用当日NAV算=58.8%,用前一日NAV算更高)

方法:  FIFO队列反事实 -- 超过daily_cap或rolling5_cap的买入单,顺延到下一交易日执行,
       价格改用次日open或次日close(两种都跑,做敏感性)。捕不到的(队列排到窗口结束
       还没执行)记为"未成交"。

核心假设(必须显式声明,不满足会导致结论无效):
  A1. NAV分母用**实际历史NAV**(前一交易日收盘a_share_nav),不重新模拟"如果建仓变慢NAV会怎样"
      的路径 -- 因为完整重建两个月组合需要对所有后续决策做反事实,超出可行范围。
      这意味着本回测只回答"同样的买入决策集合,只改变执行时点/价格,对最终收益的影响"，
      不回答"如果gate生效,交易员会不会干脆做不同的决策"。
  A2. 每笔延迟买入,买入金额(¥)在延迟后近似不变(即维持原定"配置X元到这只票"的决策),
      执行价变了导致买到的股数变了。这比"股数不变、金额变"更贴近真实决策流程(sizing按
      %NAV目标定,不是按股数)。
  A3. 延迟顺序=FIFO(先被挤掉的先排到队列最前面);同一天内新到的单子按trade_log原始id顺序。
  A4. 评估窗口终点价 = 各标的在缓存中的最后可得收盘价(most = 2026-08-21,08-24交易的
      用trade_log自己的成交价代替终点价，因为08-24是"今天"无法再往后)。
  A5. 数据源: 本地 data/kline_cache.db (baostock,2371只A股,2025-03-25~2026-08-21日线,
      已用08-06五笔实际trade_log成交价 vs 当日open/close 交叉核对,价差在合理盘中区间)。
      未额外用akshare/腾讯是因为该缓存已覆盖全部57只标的且抽查通过,重新拉取只会增加
      超时风险(D12只禁yfinance,baostock非yfinance)。

窗口: 2026-06-24 ~ 2026-08-24 (单一regime,结论不外推)
"""
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio")
OUT_DIR = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24")

WINDOW_START = "2026-06-24"
WINDOW_END = "2026-08-24"

# ---------- load trade log ----------
d = json.load(open(REPO / "portfolio_state.json"))
trades = [
    t for t in d["trade_log"]
    if t["account"] == "a_share" and t["action"] == "buy"
    and WINDOW_START <= t["date"] <= WINDOW_END
]
trades.sort(key=lambda t: (t["date"], t["id"]))
print(f"[load] {len(trades)} a_share buy trades in window")

# ---------- NAV series (actual historical, per A1) ----------
snaps = d["performance"]["daily_snapshots"]
nav_by_date = {}
for s in snaps:
    if s.get("a_share_nav"):
        nav_by_date[s["date"]] = s["a_share_nav"]

# ---------- trading calendar ----------
conn = sqlite3.connect(str(REPO / "data" / "kline_cache.db"))
cur = conn.cursor()
cur.execute(
    "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date",
    (WINDOW_START, "2026-08-21"),
)
calendar = [r[0] for r in cur.fetchall()]
if WINDOW_END not in calendar:
    calendar.append(WINDOW_END)
calendar = sorted(set(calendar))
print(f"[calendar] {len(calendar)} trading days: {calendar[0]}..{calendar[-1]}")


def prior_trading_day(date_str):
    idx = calendar.index(date_str)
    return calendar[idx - 1] if idx > 0 else None


def nav_asof(date_str):
    """NAV as of the prior trading day close (gate check happens pre-open)."""
    pd = prior_trading_day(date_str)
    if pd and pd in nav_by_date:
        return nav_by_date[pd]
    # fallback: same day, then nearest available
    if date_str in nav_by_date:
        return nav_by_date[date_str]
    # nearest prior available
    keys = sorted(k for k in nav_by_date if k <= date_str)
    return nav_by_date[keys[-1]] if keys else None


# ---------- price lookup ----------
price_cache = {}
cur.execute("SELECT code, date, open, close FROM daily_kline WHERE date>=? AND date<=?",
            (WINDOW_START, "2026-08-21"))
for code, date, o, c in cur.fetchall():
    price_cache[(code, date)] = (o, c)

# supplement 2026-08-24 execution prices with actual trade_log fills (today, no later data exists)
today_fill_price = {}
for t in trades:
    if t["date"] == WINDOW_END:
        today_fill_price[t["ticker"]] = t["price"]


def get_price(ticker, date, mode):
    """mode: 'open' or 'close'. Falls back across sources; returns None if unavailable."""
    if date == WINDOW_END:
        return today_fill_price.get(ticker)
    row = price_cache.get((ticker, date))
    if row is None:
        return None
    o, c = row
    return o if mode == "open" else c


def end_price(ticker):
    """last available price in window for return-to-end-of-window comparison."""
    if ticker in today_fill_price:
        return today_fill_price[ticker], WINDOW_END
    # walk back from 2026-08-21
    for dt in reversed(calendar):
        if dt == WINDOW_END:
            continue
        row = price_cache.get((ticker, dt))
        if row:
            return row[1], dt
    return None, None


# ---------- pre-group trades by original date ----------
trades_by_date = defaultdict(list)
for t in trades:
    trades_by_date[t["date"]].append(t)

missing_price_tickers = set()


def business_days_between(d1, d2):
    i1, i2 = calendar.index(d1), calendar.index(d2)
    return i2 - i1


def run_scenario(daily_pct, roll5_pct, price_mode, label):
    """FIFO deferral simulation. daily_pct/roll5_pct = None means unlimited."""
    queue = []  # list of dict items waiting
    executed = []  # log of executed (possibly delayed) trades
    daily_exec_total = defaultdict(float)  # date -> executed value that day

    for date in calendar:
        if date < trades[0]["date"]:
            continue
        # today's candidate pool: queue first (FIFO priority), then new arrivals
        new_arrivals = [
            dict(ticker=t["ticker"], name=t["name"], orig_date=t["date"],
                 orig_price=t["price"], value=t["value"], id=t["id"])
            for t in trades_by_date.get(date, [])
        ]
        pool = queue + new_arrivals

        nav = nav_asof(date)
        cap_daily = daily_pct * nav if (daily_pct is not None and nav) else float("inf")
        # rolling 5 trading days INCLUDING today
        idx = calendar.index(date)
        window_days = calendar[max(0, idx - 4): idx]  # prior 4 days (today added as we go)
        prior_sum = sum(daily_exec_total.get(dd, 0.0) for dd in window_days)
        cap_roll5 = roll5_pct * nav if (roll5_pct is not None and nav) else float("inf")
        remaining_roll5 = max(0.0, cap_roll5 - prior_sum) if roll5_pct is not None else float("inf")
        eff_cap_today = min(cap_daily, remaining_roll5)

        running = 0.0
        new_queue = []
        for item in pool:
            is_delayed = item["orig_date"] != date
            price_today = get_price(item["ticker"], date, price_mode) if is_delayed else item["orig_price"]
            if price_today is None:
                missing_price_tickers.add((item["ticker"], date))
                price_today = item["orig_price"]  # fallback, flagged
            v = item["value"]
            if running + v <= eff_cap_today + 1e-6:
                running += v
                daily_exec_total[date] += v
                executed.append(dict(
                    ticker=item["ticker"], name=item["name"],
                    orig_date=item["orig_date"], exec_date=date,
                    orig_price=item["orig_price"], exec_price=price_today,
                    value=v, delay_days=business_days_between(item["orig_date"], date),
                ))
            else:
                new_queue.append(item)
        queue = new_queue

    unexecuted = queue  # leftover at window end
    return dict(label=label, daily_pct=daily_pct, roll5_pct=roll5_pct,
                price_mode=price_mode, executed=executed, unexecuted=unexecuted,
                daily_exec_total=dict(daily_exec_total))


# ---------- run all scenarios ----------
SCENARIOS = [
    (0.05, 0.125, "5%/12.5%"),
    (0.10, 0.25, "10%/25% (实际规则)"),
    (0.15, 0.375, "15%/37.5%"),
    (0.20, 0.50, "20%/50%"),
    (None, None, "无限制(实际历史,基准)"),
]
PRICE_MODES = ["open", "close"]

results = {}
for daily_pct, roll5_pct, label in SCENARIOS:
    for pm in PRICE_MODES:
        key = f"{label}|{pm}"
        results[key] = run_scenario(daily_pct, roll5_pct, pm, label)

print(f"[done] {len(results)} scenario runs, missing price points: {len(missing_price_tickers)}")
if missing_price_tickers:
    print("  missing:", sorted(missing_price_tickers)[:20])

# ---------- compute return-delta metric per executed trade ----------
def compute_metrics(scn):
    rows = []
    for e in scn["executed"]:
        if e["delay_days"] == 0:
            continue  # not deferred, no delay effect to measure
        pend, dt_end = end_price(e["ticker"])
        if pend is None or e["orig_price"] in (None, 0) or e["exec_price"] in (None, 0):
            continue
        ret_orig = pend / e["orig_price"] - 1.0
        ret_delayed = pend / e["exec_price"] - 1.0
        delta = ret_delayed - ret_orig  # >0: delaying was BETTER for return; <0: delaying was WORSE
        entry_price_delta_pct = (e["exec_price"] / e["orig_price"] - 1.0)  # >0: paid more by waiting
        rows.append(dict(
            ticker=e["ticker"], name=e["name"], orig_date=e["orig_date"], exec_date=e["exec_date"],
            delay_days=e["delay_days"], value=e["value"],
            orig_price=e["orig_price"], exec_price=e["exec_price"],
            entry_price_delta_pct=entry_price_delta_pct,
            ret_orig_to_end=ret_orig, ret_delayed_to_end=ret_delayed, delta_return=delta,
        ))
    return rows


import statistics as stats

def summarize(rows, value_weighted=False):
    n = len(rows)
    if n == 0:
        return dict(n=0)
    deltas = [r["delta_return"] for r in rows]
    values = [r["value"] for r in rows]
    mean = stats.mean(deltas)
    median = stats.median(deltas)
    win_rate = sum(1 for x in deltas if x > 0) / n
    sd = stats.pstdev(deltas) if n > 1 else 0.0
    sorted_d = sorted(deltas)
    def pct(p):
        if n == 1:
            return sorted_d[0]
        k = (n - 1) * p
        f = int(k)
        c = min(f + 1, n - 1)
        if f == c:
            return sorted_d[f]
        return sorted_d[f] + (sorted_d[c] - sorted_d[f]) * (k - f)
    vw = sum(r["delta_return"] * r["value"] for r in rows) / sum(values) if sum(values) else None
    return dict(n=n, mean=mean, median=median, win_rate=win_rate, sd=sd,
                p5=pct(0.05), p95=pct(0.95),
                value_weighted_mean=vw, total_value_deferred=sum(values),
                avg_delay_days=stats.mean([r["delay_days"] for r in rows]))


# ---------- segment by up/down sub-period (based on orig_date, per task requirement) ----------
DOWN_SEG = ("2026-06-24", "2026-07-17")   # SSE 4943.02 -> 4528.47, -8.4%
UP_SEG = ("2026-07-17", "2026-08-17")     # SSE 4528.47 -> 4741.10, +4.7%
POST_SEG = ("2026-08-17", "2026-08-24")   # SSE 4741.10 -> 4557.48, -3.9%


def segment_rows(rows, seg):
    lo, hi = seg
    return [r for r in rows if lo <= r["orig_date"] <= hi]


# ---------- output ----------
report = {"generated": "2026-08-24 backtest run", "window": [WINDOW_START, WINDOW_END],
          "n_trades_in_window": len(trades),
          "segments": {"down": DOWN_SEG, "up": UP_SEG, "post": POST_SEG,
                       "sse_down_pct": -8.4, "sse_up_pct": 4.7, "sse_post_pct": -3.9},
          "scenarios": {}}

for key, scn in results.items():
    rows = compute_metrics(scn)
    overall = summarize(rows)
    down = summarize(segment_rows(rows, DOWN_SEG))
    up = summarize(segment_rows(rows, UP_SEG))
    post = summarize(segment_rows(rows, POST_SEG))
    unexecuted_value = sum(it["value"] for it in scn["unexecuted"])
    unexecuted_n = len(scn["unexecuted"])
    max_daily_actual = max(scn["daily_exec_total"].values()) if scn["daily_exec_total"] else 0
    report["scenarios"][key] = dict(
        daily_pct=scn["daily_pct"], roll5_pct=scn["roll5_pct"], price_mode=scn["price_mode"],
        n_deferred=overall["n"],
        overall=overall, down_segment=down, up_segment=up, post_segment=post,
        unexecuted_n=unexecuted_n, unexecuted_value=unexecuted_value,
        max_single_day_executed_value=max_daily_actual,
    )

with open(OUT_DIR / "buildup_pace_gate_result.json", "w") as f:
    json.dump(report, f, ensure_ascii=False, indent=2, default=str)

# ---------- print console summary ----------
print("\n" + "=" * 100)
print(f"{'scenario':<28} {'mode':<6} {'n_def':>6} {'mean_dR':>9} {'med_dR':>9} {'win%':>6} {'p5':>8} {'p95':>8} {'vw_mean':>9} {'unexec_n':>9} {'unexec_¥':>12}")
for key, s in report["scenarios"].items():
    o = s["overall"]
    if o["n"] == 0:
        print(f"{key:<35} n=0 (no deferrals)")
        continue
    print(f"{key:<28} {'':<6} {o['n']:>6} {o['mean']*100:>8.2f}% {o['median']*100:>8.2f}% "
          f"{o['win_rate']*100:>5.1f}% {o['p5']*100:>7.2f}% {o['p95']*100:>7.2f}% "
          f"{(o['value_weighted_mean'] or 0)*100:>8.2f}% {s['unexecuted_n']:>9} {s['unexecuted_value']:>12,.0f}")

print("\n--- 分段 (10%/25%规则, open价) ---")
for seg_name in ["down_segment", "up_segment", "post_segment"]:
    for pm in ["open", "close"]:
        key = f"10%/25% (实际规则)|{pm}"
        s = report["scenarios"][key][seg_name]
        print(f"{seg_name:<14} price={pm:<6} n={s.get('n',0):>4} mean_dR={s.get('mean',0)*100 if s.get('n') else 0:>7.2f}% "
              f"median={s.get('median',0)*100 if s.get('n') else 0:>7.2f}% win%={s.get('win_rate',0)*100 if s.get('n') else 0:>5.1f}%")

print(f"\n[saved] {OUT_DIR / 'buildup_pace_gate_result.json'}")
