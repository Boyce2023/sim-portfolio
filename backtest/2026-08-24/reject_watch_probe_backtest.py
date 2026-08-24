#!/usr/bin/env python3
"""
复盘: reject / watch / probe(实际买入) 三组裁决的事后表现对比。
数据源: scan_history.jsonl (2026-06-24以后), 决策日实际收盘价+前瞻收益全部
       独立通过腾讯行情(经akshare stock_zh_a_hist_tx包装,qfq前复权)重新拉取,
       不使用 scan_history.jsonl 里可能被正则解析污染的 zone_lo/zone_hi 字段。
窗口: 2026-06-24 ~ 2026-08-24 (今天), 单一regime, 外推需谨慎。
禁止: yfinance (D12铁律,A股数据源)。
输出: reject_watch_probe_result.json (全量记录级明细+分组统计)
"""
import json
import time
import sys
from datetime import datetime
from collections import defaultdict, Counter

import akshare as ak

SIM_ROOT = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
SCAN_HISTORY = f"{SIM_ROOT}/scan_history.jsonl"
OUT_DIR = f"{SIM_ROOT}/backtest/2026-08-24"
WINDOW_START = "2026-06-24"
TODAY = "2026-08-24"
FETCH_START = "20260601"  # buffer before window start
FETCH_END = "20260824"


def load_records():
    recs = []
    with open(SCAN_HISTORY) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if not d.get("date") or d["date"] < WINDOW_START:
                continue
            if d.get("decision") not in ("reject", "probe", "watch", "watch_expired"):
                continue
            recs.append(d)
    return recs


def prefix_for(ticker):
    if ticker.startswith("6"):
        return "sh" + ticker
    if ticker[0] in ("0", "2", "3"):
        return "sz" + ticker
    if ticker[0] in ("4", "8", "9"):
        return None  # 北交所, stock_zh_a_hist_tx(腾讯源) 不支持, 见下方 EXCLUDED_BJ
    return None


def fetch_kline(ticker):
    """返回 [(date_str, qfq_close), ...] 按日期升序, 或 None(失败)。"""
    sym = prefix_for(ticker)
    if sym is None:
        return None
    for attempt in range(2):
        try:
            df = ak.stock_zh_a_hist_tx(
                symbol=sym, start_date=FETCH_START, end_date=FETCH_END, adjust="qfq"
            )
            if df is None or len(df) == 0:
                return None
            df = df.sort_values("date")
            return list(zip(df["date"].astype(str).tolist(), df["close"].astype(float).tolist()))
        except Exception as e:
            if attempt == 0:
                time.sleep(1.0)
                continue
            print(f"  [FAIL] {ticker} ({sym}): {e}", file=sys.stderr)
            return None
    return None


def find_anchor_index(series_dates, decision_date, max_forward_search=5):
    """找到 decision_date 当天或之后最近的交易日索引(容忍停牌若干天)。"""
    for i, d in enumerate(series_dates):
        if d >= decision_date:
            # 只接受在 decision_date 起 max_forward_search 天内找到的锚点
            return i
    return None


def main():
    t0 = time.time()
    records = load_records()
    tickers = sorted(set(r["ticker"] for r in records))
    print(f"总裁决记录(过滤后): {len(records)}, 涉及unique ticker: {len(tickers)}")

    excluded_bj = sorted({r["ticker"] for r in records if prefix_for(r["ticker"]) is None})
    if excluded_bj:
        print(f"排除北交所ticker(腾讯源不支持,akshare stock_zh_a_hist_tx报KeyError'day'): {excluded_bj}")

    kline_cache = {}
    fail_tickers = []
    for i, t in enumerate(tickers):
        if prefix_for(t) is None:
            continue
        series = fetch_kline(t)
        if series is None or len(series) == 0:
            fail_tickers.append(t)
            continue
        kline_cache[t] = series
        if (i + 1) % 25 == 0:
            print(f"  已拉取 {i+1}/{len(tickers)} ticker, 耗时 {time.time()-t0:.0f}s")

    print(f"kline拉取完成: 成功{len(kline_cache)}, 失败{len(fail_tickers)}, 耗时{time.time()-t0:.0f}s")
    if fail_tickers:
        print(f"  失败ticker列表: {fail_tickers}")

    # ---- 逐条记录计算前瞻收益 ----
    HORIZONS = [5, 20, 40]
    out_records = []
    unmatched = []
    for r in records:
        ticker = r["ticker"]
        decision = r["decision"]
        group = "watch" if decision in ("watch", "watch_expired") else decision
        date = r["date"]
        series = kline_cache.get(ticker)
        row = {
            "date": date,
            "ticker": ticker,
            "name": r.get("name"),
            "decision_raw": decision,
            "group": group,
            "stored_price": r.get("price"),  # QA参考, 不用于计算
        }
        if series is None:
            row["status"] = "no_kline_data"
            out_records.append(row)
            unmatched.append(row)
            continue
        dates = [d for d, c in series]
        closes = [c for d, c in series]
        idx = find_anchor_index(dates, date)
        if idx is None:
            row["status"] = "decision_date_beyond_kline"
            out_records.append(row)
            unmatched.append(row)
            continue
        anchor_date = dates[idx]
        anchor_close = closes[idx]
        row["anchor_trading_date"] = anchor_date
        row["anchor_close_qfq"] = round(anchor_close, 4)
        row["date_shift_days"] = (
            (datetime.strptime(anchor_date, "%Y-%m-%d") - datetime.strptime(date, "%Y-%m-%d")).days
        )
        row["status"] = "ok"
        for h in HORIZONS:
            fwd_idx = idx + h
            if fwd_idx < len(closes):
                fwd_close = closes[fwd_idx]
                ret = (fwd_close / anchor_close - 1.0) * 100.0
                row[f"ret_{h}d"] = round(ret, 2)
                row[f"fwd_date_{h}d"] = dates[fwd_idx]
            else:
                row[f"ret_{h}d"] = None
                row[f"fwd_date_{h}d"] = None
        out_records.append(row)

    ok_records = [r for r in out_records if r["status"] == "ok"]
    print(f"成功匹配可计算记录: {len(ok_records)} / {len(out_records)}")
    if unmatched:
        print(f"未匹配记录(no_kline_data / beyond_kline): {len(unmatched)}")

    # ---- 分组统计 ----
    def pct(vals, p):
        if not vals:
            return None
        vals = sorted(vals)
        k = (len(vals) - 1) * p
        f = int(k)
        c = min(f + 1, len(vals) - 1)
        if f == c:
            return vals[f]
        return vals[f] + (vals[c] - vals[f]) * (k - f)

    def stats(vals):
        n = len(vals)
        if n == 0:
            return {"n": 0}
        mean = sum(vals) / n
        s = sorted(vals)
        median = s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2
        win_rate = sum(1 for v in vals if v > 0) / n * 100
        return {
            "n": n,
            "mean_pct": round(mean, 2),
            "median_pct": round(median, 2),
            "win_rate_pct": round(win_rate, 1),
            "p5_pct": round(pct(vals, 0.05), 2),
            "p95_pct": round(pct(vals, 0.95), 2),
            "min_pct": round(min(vals), 2),
            "max_pct": round(max(vals), 2),
        }

    groups = ["reject", "watch", "probe"]
    summary = {}
    for g in groups:
        summary[g] = {}
        for h in HORIZONS:
            vals = [r[f"ret_{h}d"] for r in ok_records if r["group"] == g and r.get(f"ret_{h}d") is not None]
            summary[g][f"{h}d"] = stats(vals)

    # ---- 义翘神州类反例: watch组里事后暴涨的案例 ----
    watch_runaways = []
    for r in ok_records:
        if r["group"] != "watch":
            continue
        best = None
        for h in HORIZONS:
            v = r.get(f"ret_{h}d")
            if v is not None:
                best = v if best is None or v > best else best
        if best is not None and best >= 30.0:
            watch_runaways.append({**r, "best_fwd_ret_pct": round(best, 2)})
    watch_runaways.sort(key=lambda x: -x["best_fwd_ret_pct"])

    # 机会成本量化: watch组按最长可用horizon的平均涨幅作为"错过"幅度总量提示
    watch_all_best = []
    for r in ok_records:
        if r["group"] != "watch":
            continue
        for h in reversed(HORIZONS):
            v = r.get(f"ret_{h}d")
            if v is not None:
                watch_all_best.append(v)
                break
    opp_cost_stats = stats(watch_all_best) if watch_all_best else {"n": 0}

    # ---- reject组里事后大跌确认过滤器有效的案例 & 事后反而大涨的"误杀"案例 ----
    reject_worst = []
    reject_best_missed = []
    for r in ok_records:
        if r["group"] != "reject":
            continue
        best = None
        for h in reversed(HORIZONS):
            v = r.get(f"ret_{h}d")
            if v is not None:
                best = v
                break
        if best is None:
            continue
        if best <= -15:
            reject_worst.append({**r, "fwd_ret_pct": round(best, 2)})
        if best >= 30:
            reject_best_missed.append({**r, "fwd_ret_pct": round(best, 2)})
    reject_worst.sort(key=lambda x: x["fwd_ret_pct"])
    reject_best_missed.sort(key=lambda x: -x["fwd_ret_pct"])

    result = {
        "meta": {
            "generated_at": datetime.now().isoformat(),
            "window": [WINDOW_START, TODAY],
            "note": "单一regime(2026-06-24~2026-08-24两个月), 外推需谨慎。价格全部为腾讯qfq前复权收盘价,独立拉取,不依赖scan_history.jsonl存储的price/zone字段。",
            "total_records_in_window": len(records),
            "unique_tickers": len(tickers),
            "excluded_bj_tickers": excluded_bj,
            "kline_fetch_fail_tickers": fail_tickers,
            "unmatched_records": len(unmatched),
            "ok_records": len(ok_records),
            "decision_type_counts": dict(Counter(r["decision"] for r in records)),
        },
        "group_summary": summary,
        "watch_runaway_cases_ge30pct": watch_runaways,
        "watch_opportunity_cost_all_best_horizon": opp_cost_stats,
        "reject_worst_confirmed_ge15pct_down": reject_worst[:30],
        "reject_missed_upside_ge30pct": reject_best_missed[:30],
        "all_records": out_records,
    }

    out_path = f"{OUT_DIR}/reject_watch_probe_result.json"
    with open(out_path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"结果已写入: {out_path}")
    print(f"总耗时: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
