# /// script
# requires-python = ">=3.10"
# dependencies = ["baostock>=0.8", "pandas>=2.0"]
# ///
"""UASS v3.0 Backtest V2 — uses pre-built ZT database for historical periods.

Usage:
  # Step 1: Merge batch files
  python3 scripts/uass_backtest_v2.py --merge --batches /tmp/zt_batch_{0..9}.json --output /tmp/zt_merged.json

  # Step 2: Run backtest on merged data
  python3 scripts/uass_backtest_v2.py --backtest --zt-db /tmp/zt_merged.json --start 20260302 --end 20260513 --output /tmp/bt_historical.json

The ZT database is built by build_zt_history.py (baostock K-line reconstruction).
Industry classification from baostock is mapped to sector names for mainline detection.
"""

import json, sys, time
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

import baostock as bs
import pandas as pd


INDUSTRY_TO_SECTOR = {}


def simplify_industry(raw: str) -> str:
    """Map baostock industry classification to simplified sector name."""
    if not raw:
        return "其他"
    clean = raw.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    mappings = {
        "电力": "电力", "热力": "电力",
        "半导体": "半导体", "集成电路": "半导体",
        "计算机": "计算机", "软件": "软件开发",
        "通信": "通信设备", "电信": "通信设备",
        "汽车": "汽车零部", "零部件": "汽车零部",
        "化学": "化学制品", "化工": "化学制品",
        "医药": "医药", "制药": "医药", "生物": "生物制品",
        "电子": "电子", "元件": "元件", "光电": "光学光电",
        "机械": "通用设备", "设备": "专用设备",
        "房地产": "房地产开", "建筑": "基础建设",
        "金属": "工业金属", "矿": "采矿",
        "食品": "食品饮料", "饮料": "食品饮料", "酒": "白酒Ⅱ",
        "纺织": "服装家纺", "服装": "服装家纺",
        "银行": "银行", "保险": "保险", "证券": "证券",
        "资本市场": "证券", "货币金融": "银行",
        "农": "农业", "林": "农业", "牧": "养殖业", "渔": "农业",
        "石油": "石油石化", "燃气": "燃气Ⅱ", "煤": "煤炭开采",
        "零售": "一般零售", "商业": "一般零售",
        "运输": "交通运输", "物流": "物流", "航空": "航空",
        "旅游": "旅游", "酒店": "旅游",
        "传媒": "数字媒体", "文化": "数字媒体", "影视": "影视院线",
        "环境": "环境治理", "环保": "环境治理",
        "电池": "电池", "光伏": "光伏设备", "新能源": "新能源",
        "军工": "军工电子", "国防": "军工电子",
    }
    for keyword, sector in mappings.items():
        if keyword in clean:
            return sector
    if len(clean) > 4:
        return clean[:4]
    return clean if clean else "其他"


def merge_batches(batch_files: list[str], output_path: str):
    """Merge multiple batch outputs into a single ZT database."""
    merged = {}
    total_stocks = 0
    total_success = 0
    total_zt = 0

    for bf in batch_files:
        try:
            with open(bf) as f:
                data = json.load(f)
            total_stocks += data.get("stocks_queried", 0)
            total_success += data.get("stocks_success", 0)
            for dt, events in data.get("zt_events", {}).items():
                if dt not in merged:
                    merged[dt] = []
                merged[dt].extend(events)
                total_zt += len(events)
            print(f"  ✓ {bf}: {data.get('stocks_success',0)} stocks, "
                  f"{sum(len(v) for v in data.get('zt_events',{}).values())} ZT events")
        except Exception as e:
            print(f"  ✗ {bf}: {e}")

    for dt in merged:
        merged[dt].sort(key=lambda x: x.get("pctChg", 0), reverse=True)

    output = {
        "type": "zt_database",
        "total_stocks_queried": total_stocks,
        "total_stocks_success": total_success,
        "total_zt_events": total_zt,
        "trading_days_with_zt": len(merged),
        "zt_events": merged,
        "daily_counts": {dt: len(events) for dt, events in sorted(merged.items())},
    }

    with open(output_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Merged: {total_stocks} stocks, {total_zt} ZT events, "
          f"{len(merged)} days with limit-ups → {output_path}")

    for dt in sorted(merged.keys())[:5]:
        print(f"  {dt}: {len(merged[dt])} limit-ups")
    print(f"  ...")
    for dt in sorted(merged.keys())[-5:]:
        print(f"  {dt}: {len(merged[dt])} limit-ups")


def detect_mainlines_from_db(zt_list: list[dict]) -> dict:
    """Detect mainlines from ZT database entries (uses industry field)."""
    sector_stocks = defaultdict(list)
    for item in zt_list:
        sector = simplify_industry(item.get("industry", ""))
        sector_stocks[sector].append({
            "code": item["code"],
            "name": item["name"],
            "pctChg": item.get("pctChg", 0),
        })
    return {sec: stocks for sec, stocks in sector_stocks.items() if len(stocks) >= 2}


def bs_login():
    lg = bs.login()
    return lg


def bs_logout():
    bs.logout()


def fetch_kline_bs(code: str, end_date: str, days: int = 120) -> pd.DataFrame:
    dt = datetime.strptime(end_date, "%Y%m%d")
    start = (dt - timedelta(days=days * 2)).strftime("%Y-%m-%d")
    end = (dt + timedelta(days=30)).strftime("%Y-%m-%d")

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
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["close"])
    return df


def score_d5(kline: pd.DataFrame) -> int:
    if len(kline) < 10:
        return 0
    score = 0
    recent = kline.tail(20)

    if len(recent) > 0:
        amp = ((recent["high"] - recent["low"]) / recent["close"].clip(lower=0.01)).mean() * 100
        if amp >= 6: score += 6
        elif amp >= 4: score += 4
        elif amp >= 2.5: score += 2

    if "pctChg" in recent.columns:
        max_gain = recent["pctChg"].max()
        if max_gain >= 15: score += 5
        elif max_gain >= 9.5: score += 4
        elif max_gain >= 5: score += 2

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

    if len(close) >= 20:
        ret_20d = (current / close[-20] - 1) * 100
        if ret_20d > 30:
            flags.append("MA20_OVEREXTEND")
            penalty -= 15

    if len(close) >= 60:
        ret_60d = (current / close[0] - 1) * 100
        if ret_60d > 50:
            flags.append("MA60_OVEREXTEND")
            penalty -= 15

    ma5 = pd.Series(close).rolling(5).mean().iloc[-1] if len(close) >= 5 else current
    ma20 = pd.Series(close).rolling(20).mean().iloc[-1] if len(close) >= 20 else current
    if current < ma20:
        flags.append("MA_BEARISH")
        penalty -= 10

    high_all = max(close)
    drawdown = (current / high_all - 1) * 100
    if drawdown < -20:
        flags.append("DEEP_DRAWDOWN")
        penalty -= 12

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


def run_backtest(zt_db_path: str, start: str, end: str, output_path: str):
    with open(zt_db_path) as f:
        zt_db = json.load(f)

    zt_events = zt_db["zt_events"]
    trade_days = sorted([d for d in zt_events.keys() if start <= d <= end])

    if not trade_days:
        print(f"No trading days with ZT events in {start}-{end}")
        sys.exit(1)

    print(f"回测区间: {start} → {end}, {len(trade_days)} 个有涨停的交易日")

    bs_login()

    all_codes = set()
    daily_data = {}
    mainline_history = defaultdict(int)

    for dt in trade_days:
        zt_list = zt_events.get(dt, [])
        mainlines = detect_mainlines_from_db(zt_list)

        zt_codes = set(item["code"] for item in zt_list)

        active_sectors = set(mainlines.keys())
        new_history = defaultdict(int)
        for sec in active_sectors:
            new_history[sec] = mainline_history.get(sec, 0) + 1
        mainline_history = new_history

        daily_data[dt] = {
            "zt_count": len(zt_list),
            "mainlines": {sec: {"count": len(stocks), "streak": mainline_history[sec],
                                "stocks": stocks}
                         for sec, stocks in mainlines.items()},
            "zt_codes": list(zt_codes),
        }

        for sec, stocks in mainlines.items():
            for s in stocks:
                all_codes.add(s["code"])

        print(f"  {dt}: {len(zt_list)}只涨停, {len(mainlines)}条主线")

    print(f"\n=== K线数据 ({len(all_codes)} 只) ===")
    kline_cache = {}
    for i, code in enumerate(sorted(all_codes)):
        if i % 50 == 0 and i > 0:
            print(f"  进度: {i}/{len(all_codes)}")
        kl = fetch_kline_bs(code, end, days=120)
        if not kl.empty:
            kline_cache[code] = kl
        time.sleep(0.05)
    print(f"  K线缓存: {len(kline_cache)}/{len(all_codes)} 只成功")

    print("\n=== 逐日评分 ===")
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
                signal_dt_str = datetime.strptime(dt, "%Y%m%d").strftime("%Y-%m-%d")
                kl_available = kl[kl["date"] <= signal_dt_str]

                if len(kl_available) < 10:
                    continue

                d5 = score_d5(kl_available)
                d6_verdict, d6_penalty, d6_flags = score_d6(kl_available)

                is_buyable = d5 >= 5 and d6_verdict == "HEALTHY"

                fwd = {}
                dates = list(kl["date"])
                try:
                    idx = dates.index(signal_dt_str)
                    signal_close = float(kl.iloc[idx]["close"])
                    for horizon, label in [(1, "T+1"), (3, "T+3"), (5, "T+5"), (10, "T+10")]:
                        fwd_idx = idx + horizon
                        if fwd_idx < len(kl):
                            fwd_close = float(kl.iloc[fwd_idx]["close"])
                            fwd[label] = round((fwd_close / signal_close - 1) * 100, 2)
                except ValueError:
                    pass

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
            for b in buys[:3]:
                t1 = b["forward_returns"].get("T+1", "N/A")
                t5 = b["forward_returns"].get("T+5", "N/A")
                print(f"  🟢 {dt} {b['code']} {b['name']} [{b['sector']}] D5={b['d5_score']} "
                      f"T+1={t1}% T+5={t5}%")

    bs_logout()

    # Statistics
    buy_signals = [s for s in all_signals if s["buyable"]]
    stats = {
        "total_days": len(trade_days),
        "total_buy_signals": len(buy_signals),
        "avg_signals_per_day": round(len(buy_signals) / max(len(trade_days), 1), 2),
    }

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
    sub = parser.add_subparsers(dest="mode")

    merge_p = sub.add_parser("merge")
    merge_p.add_argument("--batches", nargs="+", required=True)
    merge_p.add_argument("--output", required=True)

    bt_p = sub.add_parser("backtest")
    bt_p.add_argument("--zt-db", required=True)
    bt_p.add_argument("--start", required=True)
    bt_p.add_argument("--end", required=True)
    bt_p.add_argument("--output", required=True)

    args = parser.parse_args()

    if args.mode == "merge":
        merge_batches(args.batches, args.output)
    elif args.mode == "backtest":
        run_backtest(args.zt_db, args.start, args.end, args.output)
    else:
        parser.print_help()
