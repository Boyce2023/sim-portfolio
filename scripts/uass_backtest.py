# /// script
# requires-python = ">=3.10"
# dependencies = ["akshare>=1.14", "baostock>=0.8", "pandas>=2.0"]
# ///
"""UASS v3.0 Backtest Engine — 历史回测，无前视偏差。

用法:
  uv run --script scripts/uass_backtest.py --start 20260302 --end 20260306 --output /tmp/bt_w1.json

每个交易日独立评估：
1. 涨停池 → 主线检测（板块≥2只涨停）
2. 主线内非涨停强势股 → D5 K线弹性 + D6 筹码健康
3. 买入信号 = 主线内 + D5≥5 + D6 HEALTHY
4. 记录信号后用未来数据计算T+1/3/5/10收益（仅用于评估，不影响信号生成）
"""

import json, sys, os, time
from datetime import datetime, timedelta, date
from collections import defaultdict
from pathlib import Path

import akshare as ak
import baostock as bs
import pandas as pd


def get_trade_days(start: str, end: str) -> list[str]:
    df = ak.tool_trade_date_hist_sina()
    s = date(int(start[:4]), int(start[4:6]), int(start[6:8]))
    e = date(int(end[:4]), int(end[4:6]), int(end[6:8]))
    days = df[(df["trade_date"] >= s) & (df["trade_date"] <= e)]
    return sorted([d.strftime("%Y%m%d") for d in days["trade_date"]])


def get_all_trade_days() -> list[str]:
    df = ak.tool_trade_date_hist_sina()
    return sorted([d.strftime("%Y%m%d") for d in df["trade_date"]])


def fetch_zt_pool(dt: str) -> pd.DataFrame:
    try:
        df = ak.stock_zt_pool_em(date=dt)
        return df
    except Exception as e:
        print(f"  [WARN] 涨停池 {dt} 失败: {e}")
        return pd.DataFrame()


def fetch_strong_pool(dt: str) -> pd.DataFrame:
    try:
        df = ak.stock_zt_pool_strong_em(date=dt)
        return df
    except Exception as e:
        return pd.DataFrame()


def detect_mainlines(zt_df: pd.DataFrame) -> dict:
    if zt_df.empty:
        return {}
    sector_col = "所属行业" if "所属行业" in zt_df.columns else None
    if sector_col is None:
        for c in zt_df.columns:
            if "行业" in c or "板块" in c:
                sector_col = c
                break
    if sector_col is None:
        return {}

    sector_counts = defaultdict(list)
    for _, row in zt_df.iterrows():
        sec = str(row.get(sector_col, ""))
        code = str(row.get("代码", ""))
        name = str(row.get("名称", ""))
        if sec and code:
            sector_counts[sec].append({"code": code, "name": name})

    return {sec: stocks for sec, stocks in sector_counts.items() if len(stocks) >= 2}


def bs_login():
    lg = bs.login()
    return lg


def bs_logout():
    bs.logout()


def fetch_kline_bs(code: str, end_date: str, days: int = 60) -> pd.DataFrame:
    dt = datetime.strptime(end_date, "%Y%m%d")
    start = (dt - timedelta(days=days * 2)).strftime("%Y-%m-%d")
    end = dt.strftime("%Y-%m-%d")

    if code.startswith("6"):
        bs_code = f"sh.{code}"
    else:
        bs_code = f"sz.{code}"

    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,high,low,close,volume,amount,turn,pctChg",
        start_date=start, end_date=end,
        frequency="d", adjustflag="2"
    )
    rows = []
    while rs.error_code == '0' and rs.next():
        rows.append(rs.get_row_data())

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=rs.fields)
    for c in ["open", "high", "low", "close", "volume", "amount", "turn", "pctChg"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["close"])
    return df.tail(days)


def score_d5(kline: pd.DataFrame) -> int:
    if len(kline) < 10:
        return 0
    score = 0
    recent = kline.tail(20)

    # Amplitude: (high-low)/close average
    if len(recent) > 0:
        amp = ((recent["high"] - recent["low"]) / recent["close"].clip(lower=0.01)).mean() * 100
        if amp >= 6: score += 6
        elif amp >= 4: score += 4
        elif amp >= 2.5: score += 2

    # Explosion rate: max single-day gain in 20d
    if "pctChg" in recent.columns:
        max_gain = recent["pctChg"].max()
        if max_gain >= 15: score += 5
        elif max_gain >= 9.5: score += 4
        elif max_gain >= 5: score += 2

    # Limit-up frequency: days with pctChg >= 9.5%
    if "pctChg" in recent.columns:
        zt_days = (recent["pctChg"] >= 9.5).sum()
        if zt_days >= 3: score += 4
        elif zt_days >= 2: score += 3
        elif zt_days >= 1: score += 1

    return score


def score_d6(kline: pd.DataFrame) -> tuple[str, int, list[str]]:
    if len(kline) < 20:
        return "DATA_ERROR", 0, ["INSUFFICIENT_DATA"]

    flags = []
    penalty = 0
    close = kline["close"].values
    current = close[-1]

    # 20d return
    if len(close) >= 20:
        ret_20d = (current / close[-20] - 1) * 100
        if ret_20d > 30:
            flags.append("MA20_OVEREXTEND")
            penalty -= 15

    # 60d return (if available)
    if len(close) >= 60:
        ret_60d = (current / close[0] - 1) * 100
        if ret_60d > 50:
            flags.append("MA60_OVEREXTEND")
            penalty -= 15

    # MA position
    ma5 = pd.Series(close).rolling(5).mean().iloc[-1] if len(close) >= 5 else current
    ma20 = pd.Series(close).rolling(20).mean().iloc[-1] if len(close) >= 20 else current
    if current < ma20:
        flags.append("MA_BEARISH")
        penalty -= 10

    # 52-week high drawdown (approximate with available data)
    high_52w = max(close) if len(close) > 0 else current
    drawdown = (current / high_52w - 1) * 100
    if drawdown < -20:
        flags.append("52W_DEEP_DRAWDOWN")
        penalty -= 12

    # Volume analysis
    if "volume" in kline.columns and len(kline) >= 10:
        vol = kline["volume"].values
        avg_vol_10 = vol[-10:].mean()
        last_vol = vol[-1]
        if avg_vol_10 > 0 and last_vol / avg_vol_10 > 3:
            flags.append("VOLUME_CLIMAX")
            penalty -= 8

    if not flags:
        return "HEALTHY", 0, ["HEALTHY"]

    verdict = "VETO" if penalty <= -20 else "CAUTION"
    return verdict, penalty, flags


def get_forward_returns(code: str, signal_date: str, all_trade_days: list[str], kline_cache: dict) -> dict:
    if code not in kline_cache:
        return {}

    kl = kline_cache[code]
    if kl.empty:
        return {}

    dates = list(kl["date"])
    try:
        idx = dates.index(datetime.strptime(signal_date, "%Y%m%d").strftime("%Y-%m-%d"))
    except ValueError:
        return {}

    signal_close = float(kl.iloc[idx]["close"])
    result = {}
    for horizon, label in [(1, "T+1"), (3, "T+3"), (5, "T+5"), (10, "T+10")]:
        fwd_idx = idx + horizon
        if fwd_idx < len(kl):
            fwd_close = float(kl.iloc[fwd_idx]["close"])
            result[label] = round((fwd_close / signal_close - 1) * 100, 2)

    return result


def run_backtest(start: str, end: str, output_path: str):
    trade_days = get_trade_days(start, end)
    all_days = get_all_trade_days()
    print(f"回测区间: {start} → {end}, {len(trade_days)} 个交易日")

    # Extended end for forward returns
    end_dt = datetime.strptime(end, "%Y%m%d")
    extended_end = (end_dt + timedelta(days=30)).strftime("%Y%m%d")

    bs_login()

    # Phase 1: Collect all limit-up data day by day
    print("\n=== Phase 1: 收集涨停数据 ===")
    daily_data = {}
    all_codes = set()
    mainline_history = defaultdict(int)  # sector → consecutive days

    for dt in trade_days:
        zt_df = fetch_zt_pool(dt)
        mainlines = detect_mainlines(zt_df)

        zt_codes = set(str(r["代码"]) for _, r in zt_df.iterrows()) if not zt_df.empty else set()

        # Update mainline streaks
        active_sectors = set(mainlines.keys())
        new_history = defaultdict(int)
        for sec in active_sectors:
            new_history[sec] = mainline_history.get(sec, 0) + 1
        mainline_history = new_history

        daily_data[dt] = {
            "zt_count": len(zt_df),
            "mainlines": {sec: {"count": len(stocks), "streak": mainline_history[sec],
                                "stocks": stocks}
                         for sec, stocks in mainlines.items()},
            "zt_codes": list(zt_codes),
        }

        for sec, stocks in mainlines.items():
            for s in stocks:
                all_codes.add(s["code"])

        print(f"  {dt}: {len(zt_df)}只涨停, {len(mainlines)}条主线")

    # Phase 2: Batch fetch K-lines for all candidate stocks
    print(f"\n=== Phase 2: K线数据 ({len(all_codes)} 只) ===")
    kline_cache = {}
    for i, code in enumerate(sorted(all_codes)):
        if i % 50 == 0 and i > 0:
            print(f"  进度: {i}/{len(all_codes)}")
        kl = fetch_kline_bs(code, extended_end, days=120)
        if not kl.empty:
            kline_cache[code] = kl
        time.sleep(0.1)
    print(f"  K线缓存: {len(kline_cache)}/{len(all_codes)} 只成功")

    # Phase 3: Score each day's candidates
    print("\n=== Phase 3: 逐日评分 ===")
    all_signals = []
    daily_summaries = []

    for dt in trade_days:
        dd = daily_data[dt]
        day_signals = []

        for sec, ml_info in dd["mainlines"].items():
            streak = ml_info["streak"]
            stage = "启动" if streak == 1 else ("主升早" if streak <= 3 else "主升中")

            for stock in ml_info["stocks"]:
                code = stock["code"]
                name = stock["name"]

                if code not in kline_cache:
                    continue

                kl = kline_cache[code]
                # Filter K-line to only data available on signal date
                signal_dt_str = datetime.strptime(dt, "%Y%m%d").strftime("%Y-%m-%d")
                kl_available = kl[kl["date"] <= signal_dt_str]

                if len(kl_available) < 10:
                    continue

                d5 = score_d5(kl_available)
                d6_verdict, d6_penalty, d6_flags = score_d6(kl_available)

                is_buyable = d5 >= 5 and d6_verdict == "HEALTHY"

                # Forward returns (uses future data, only for evaluation)
                fwd = get_forward_returns(code, dt, all_days, kline_cache)

                signal = {
                    "date": dt,
                    "code": code,
                    "name": name,
                    "sector": sec,
                    "mainline_streak": streak,
                    "stage": stage,
                    "d5_score": d5,
                    "d6_verdict": d6_verdict,
                    "d6_penalty": d6_penalty,
                    "d6_flags": d6_flags,
                    "buyable": is_buyable,
                    "forward_returns": fwd,
                }
                day_signals.append(signal)
                if is_buyable:
                    all_signals.append(signal)

        buy_count = sum(1 for s in day_signals if s["buyable"])
        daily_summaries.append({
            "date": dt,
            "zt_count": dd["zt_count"],
            "mainline_count": len(dd["mainlines"]),
            "candidates_scored": len(day_signals),
            "buy_signals": buy_count,
            "mainlines": {sec: {"streak": info["streak"], "count": info["count"]}
                         for sec, info in dd["mainlines"].items()},
        })

        if buy_count > 0:
            buys = [s for s in day_signals if s["buyable"]]
            for b in buys:
                t1 = b["forward_returns"].get("T+1", "N/A")
                t5 = b["forward_returns"].get("T+5", "N/A")
                print(f"  🟢 {dt} {b['code']} {b['name']} [{sec}] D5={b['d5_score']} "
                      f"T+1={t1}% T+5={t5}%")

    bs_logout()

    # Phase 4: Statistics
    print("\n=== Phase 4: 统计 ===")
    buy_signals = [s for s in all_signals if s["buyable"]]

    stats = {
        "total_days": len(trade_days),
        "total_buy_signals": len(buy_signals),
        "avg_signals_per_day": round(len(buy_signals) / max(len(trade_days), 1), 2),
    }

    # Win rates by horizon
    for horizon in ["T+1", "T+3", "T+5", "T+10"]:
        vals = [s["forward_returns"].get(horizon) for s in buy_signals
                if s["forward_returns"].get(horizon) is not None]
        if vals:
            wins = sum(1 for v in vals if v > 0)
            stats[f"{horizon}_count"] = len(vals)
            stats[f"{horizon}_win_rate"] = round(wins / len(vals) * 100, 1)
            stats[f"{horizon}_avg_return"] = round(sum(vals) / len(vals), 2)
            stats[f"{horizon}_max_gain"] = round(max(vals), 2)
            stats[f"{horizon}_max_loss"] = round(min(vals), 2)

    # By sector
    sector_stats = defaultdict(lambda: {"signals": 0, "wins_t5": 0, "total_t5": 0, "sum_t5": 0})
    for s in buy_signals:
        sec = s["sector"]
        sector_stats[sec]["signals"] += 1
        t5 = s["forward_returns"].get("T+5")
        if t5 is not None:
            sector_stats[sec]["total_t5"] += 1
            sector_stats[sec]["sum_t5"] += t5
            if t5 > 0:
                sector_stats[sec]["wins_t5"] += 1

    sector_summary = {}
    for sec, ss in sector_stats.items():
        sector_summary[sec] = {
            "signals": ss["signals"],
            "win_rate_t5": round(ss["wins_t5"] / max(ss["total_t5"], 1) * 100, 1),
            "avg_return_t5": round(ss["sum_t5"] / max(ss["total_t5"], 1), 2),
        }

    output = {
        "backtest_range": {"start": start, "end": end},
        "trade_days": len(trade_days),
        "stats": stats,
        "sector_summary": sector_summary,
        "daily_summaries": daily_summaries,
        "buy_signals": buy_signals,
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ 结果已写入 {output_path}")
    print(f"  买入信号总数: {len(buy_signals)}")
    for h in ["T+1", "T+3", "T+5", "T+10"]:
        wr = stats.get(f"{h}_win_rate", "N/A")
        ar = stats.get(f"{h}_avg_return", "N/A")
        print(f"  {h}: 胜率 {wr}%, 均收益 {ar}%")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run_backtest(args.start, args.end, args.output)
