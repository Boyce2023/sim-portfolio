"""
审判: -12%灾难线(成本止损) vs 破20日均线(结构止损) vs 破前10日低 vs 不设止损持有到今天
样本: sim-portfolio a_share account, 2026-06-24起平仓的全部交易 (n=60, FIFO聚合)
数据源: akshare stock_zh_a_daily(sina) 2026-04-01~08-21 + 腾讯qt.gtimg今日(08-24)盘中快照 (D12合规,禁yfinance)

方法论(4条规则独立重放,互不依赖实际卖出原因/日期):
  R1 -12%灾难线: stop = entry_cost * 0.88。触发日=LOW首次<=stop的交易日,假设按stop价成交(不含滑点,已知比实际略乐观)
  R2 破20日均线: MA20=当日收盘含当日的过去20个交易日均值。触发日=close首次<MA20,假设按当日收盘价成交
  R3 破前10日低: 触发日=当日LOW首次<过去10个交易日(不含当日)的最低LOW,假设按当日收盘价成交
  R4 不止损持有到今天: 无触发,直接按08-24盘中快照价(11:xx,午休)计价,不构成"卖出"故无误杀概念

误杀定义: 触发退出后,未来N=5个交易日内(含触发当日起算,数据不足5日的样本单独剔除计误杀分母)
  最高价(HIGH)反弹超过卖出价 = 计1次误杀

⛔本回测样本量n=60,单一regime(2026-06-24~08-24两个月),结论仅对该窗口负责,外推需谨慎。
"""
import json
import statistics as st

SCRATCH = "/private/tmp/claude-501/-Users-huaichuaibeimeng-claude-projects/0271364f-8cab-4319-af5d-5048f0719e12/scratchpad"
REBOUND_N = 5

agg = json.load(open(f"{SCRATCH}/agg_closed_trades.json"))
price_data = json.load(open(f"{SCRATCH}/price_data.json"))
today_quotes = json.load(open(f"{SCRATCH}/today_quotes.json"))

def build_series(ticker):
    rows = price_data.get(ticker, [])
    series = [{"date": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]} for r in rows]
    tq = today_quotes.get(ticker)
    if tq:
        date, open_, current, high, low, _ = tq
        series.append({"date": date, "open": open_, "high": high, "low": low, "close": current, "volume": None,
                        "note": "08-24盘中快照(午休时点),非官方收盘价"})
    series.sort(key=lambda x: x["date"])
    return series

def simulate(trade, series, rule):
    entry_date = trade["entry_date_anchor"]
    entry_price = trade["avg_entry_price"]
    shares = trade["shares"]
    idx_after_entry = None
    for i, bar in enumerate(series):
        if bar["date"] > entry_date:
            idx_after_entry = i
            break
    if idx_after_entry is None:
        return {"triggered": False, "reason": "no_data_after_entry"}

    if rule == "R4":
        last = series[-1]
        exit_price = last["close"]
        pnl = (exit_price - entry_price) * shares
        return {"triggered": False, "exit_date": last["date"], "exit_price": exit_price,
                "pnl": pnl, "pnl_pct": (exit_price - entry_price) / entry_price * 100,
                "note": "held_to_today"}

    if rule == "R1":
        stop = entry_price * 0.88
        for i in range(idx_after_entry, len(series)):
            bar = series[i]
            if bar["low"] <= stop:
                exit_price = stop
                pnl = (exit_price - entry_price) * shares
                return {"triggered": True, "exit_date": bar["date"], "exit_idx": i, "exit_price": exit_price,
                        "pnl": pnl, "pnl_pct": (exit_price - entry_price) / entry_price * 100}
        last = series[-1]
        exit_price = last["close"]
        return {"triggered": False, "exit_date": last["date"], "exit_price": exit_price,
                "pnl": (exit_price - entry_price) * shares,
                "pnl_pct": (exit_price - entry_price) / entry_price * 100, "note": "never_triggered_marked_today"}

    if rule == "R2":
        for i in range(idx_after_entry, len(series)):
            if i < 19:
                continue
            trailing = [series[j]["close"] for j in range(i - 19, i + 1)]
            ma20 = sum(trailing) / 20.0
            bar = series[i]
            if bar["close"] < ma20:
                exit_price = bar["close"]
                pnl = (exit_price - entry_price) * shares
                return {"triggered": True, "exit_date": bar["date"], "exit_idx": i, "exit_price": exit_price,
                        "pnl": pnl, "pnl_pct": (exit_price - entry_price) / entry_price * 100, "ma20_at_trigger": ma20}
        last = series[-1]
        exit_price = last["close"]
        return {"triggered": False, "exit_date": last["date"], "exit_price": exit_price,
                "pnl": (exit_price - entry_price) * shares,
                "pnl_pct": (exit_price - entry_price) / entry_price * 100, "note": "never_triggered_marked_today"}

    if rule == "R3":
        for i in range(idx_after_entry, len(series)):
            if i < 10:
                continue
            prior10_low = min(series[j]["low"] for j in range(i - 10, i))
            bar = series[i]
            if bar["low"] < prior10_low:
                exit_price = bar["close"]
                pnl = (exit_price - entry_price) * shares
                return {"triggered": True, "exit_date": bar["date"], "exit_idx": i, "exit_price": exit_price,
                        "pnl": pnl, "pnl_pct": (exit_price - entry_price) / entry_price * 100, "prior10_low": prior10_low}
        last = series[-1]
        exit_price = last["close"]
        return {"triggered": False, "exit_date": last["date"], "exit_price": exit_price,
                "pnl": (exit_price - entry_price) * shares,
                "pnl_pct": (exit_price - entry_price) / entry_price * 100, "note": "never_triggered_marked_today"}

def check_false_positive(series, result, sell_price):
    """After a triggered exit, look forward up to REBOUND_N trading days;
    if HIGH rebounds above sell_price within that window -> false positive (误杀).
    Returns: (eligible: bool, false_positive: bool, days_available: int)"""
    if not result.get("triggered"):
        return False, False, 0
    exit_idx = result["exit_idx"]
    forward = series[exit_idx + 1: exit_idx + 1 + REBOUND_N]
    days_available = len(forward)
    if days_available < REBOUND_N:
        return False, False, days_available
    fp = any(bar["high"] > sell_price for bar in forward)
    return True, fp, days_available

RULES = ["R1", "R2", "R3", "R4"]
results = {r: [] for r in RULES}

missing_data_tickers = set()
for trade in agg:
    ticker = trade["ticker"]
    series = build_series(ticker)
    if not series:
        missing_data_tickers.add(ticker)
        continue
    for rule in RULES:
        r = simulate(trade, series, rule)
        r["ticker"] = ticker
        r["name"] = trade["name"]
        r["entry_date"] = trade["entry_date_anchor"]
        r["entry_price"] = trade["avg_entry_price"]
        r["shares"] = trade["shares"]
        r["actual_exit_date"] = trade["exit_date"]
        r["actual_exit_price"] = trade["exit_price"]
        r["actual_pnl"] = trade["actual_pnl"]
        if rule != "R4":
            elig, fp, days_avail = check_false_positive(series, r, r["exit_price"])
            r["fp_eligible"] = elig
            r["fp_false_positive"] = fp
            r["fp_days_available"] = days_avail
        results[rule].append(r)

print("missing_data_tickers:", missing_data_tickers)

def summarize(rule_results):
    pnls = [r["pnl"] for r in rule_results]
    pnl_pcts = [r["pnl_pct"] for r in rule_results]
    n = len(pnls)
    total = sum(pnls)
    mean = st.mean(pnls)
    median = st.median(pnls)
    sorted_pnls = sorted(pnls)
    def pctile(data, p):
        k = (len(data)-1) * p
        f = int(k)
        c = min(f+1, len(data)-1)
        if f == c:
            return data[f]
        return data[f] + (data[c]-data[f])*(k-f)
    p5 = pctile(sorted_pnls, 0.05)
    p95 = pctile(sorted_pnls, 0.95)
    max_loss = min(pnls)
    max_loss_trade = min(rule_results, key=lambda r: r["pnl"])
    win_count = sum(1 for p in pnls if p > 0)
    triggered = [r for r in rule_results if r.get("triggered")]
    trigger_count = len(triggered)
    eligible = [r for r in rule_results if r.get("fp_eligible")]
    fp_count = sum(1 for r in eligible if r["fp_false_positive"])
    fp_rate = fp_count / len(eligible) if eligible else None
    fp_excluded_insufficient_data = sum(1 for r in triggered if not r.get("fp_eligible") and r.get("fp_days_available", 0) < REBOUND_N)
    return {
        "n": n, "total_pnl": round(total, 2), "mean_pnl": round(mean, 2), "median_pnl": round(median, 2),
        "pnl_p5": round(p5, 2), "pnl_p95": round(p95, 2),
        "max_single_loss": round(max_loss, 2), "max_single_loss_ticker": f"{max_loss_trade['ticker']} {max_loss_trade['name']}",
        "win_rate_pct": round(win_count/n*100, 1),
        "trigger_count": trigger_count, "trigger_rate_pct": round(trigger_count/n*100, 1),
        "false_positive_eligible_n": len(eligible), "false_positive_count": fp_count,
        "false_positive_rate_pct": round(fp_rate*100, 1) if fp_rate is not None else None,
        "false_positive_excluded_insufficient_fwd_data": fp_excluded_insufficient_data,
    }

summary = {rule: summarize(results[rule]) for rule in RULES}
print(json.dumps(summary, ensure_ascii=False, indent=2))

json.dump(results, open(f"{SCRATCH}/backtest_full_results.json", "w"), ensure_ascii=False, indent=2, default=str)
json.dump(summary, open(f"{SCRATCH}/backtest_summary.json", "w"), ensure_ascii=False, indent=2)
print("saved full results + summary")
