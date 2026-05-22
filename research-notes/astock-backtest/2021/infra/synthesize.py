#!/usr/bin/env python3
"""Synthesize all 2021 walk-forward simulation results into a comprehensive report."""
import json, os, glob
from collections import defaultdict, Counter

RESULTS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-backtest/2021/sim-results"

def main():
    files = sorted(glob.glob(os.path.join(RESULTS_DIR, "sim-2021-*.json")))
    print(f"Found {len(files)} result files\n")

    all_picks = []
    agent_summaries = []
    stock_stats = defaultdict(lambda: {"picks": 0, "big_wins": 0, "wins": 0, "neutral": 0, "losses": 0, "returns": []})
    monthly_stats = defaultdict(lambda: {"picks": 0, "big_wins": 0, "wins": 0, "neutral": 0, "losses": 0})
    sector_stats = defaultdict(lambda: {"picks": 0, "big_wins": 0, "wins": 0, "losses": 0, "returns": []})

    SECTORS = {
        "半导体": ["002371","688012","688019","603501","603986","600584"],
        "光伏新能源": ["601012","600438","002129","002459","300274"],
        "锂电EV": ["300750","002594","002466","002460","300014"],
        "PCB消费电子": ["002475","002273","002916","002938","002463","300433"],
        "智能驾驶": ["002920","002906","300496"],
        "机器人制造": ["688017","300124","002747"],
        "医药": ["603259","300760","600276"],
        "电力电网": ["600406","600900","002028"],
        "资源": ["600188","601225","601899","600988"],
        "消费白酒": ["600519","000858","603288","600809"],
        "其他": ["000333","601888","002607","002472","002241"],
    }
    code_to_sector = {}
    for sec, codes in SECTORS.items():
        for c in codes:
            code_to_sector[c] = sec

    for fpath in files:
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)

        agent_id = data.get("agent_id", os.path.basename(fpath))
        summary = data.get("summary", {})
        agent_summaries.append({
            "id": agent_id,
            "range": data.get("date_range", ""),
            "total_picks": summary.get("total_picks", 0),
            "big_wins": summary.get("big_wins", 0),
            "wins": summary.get("wins", 0),
            "neutral": summary.get("neutral", 0),
            "losses": summary.get("losses", 0),
            "win_rate": summary.get("win_rate", 0),
        })

        for dec in data.get("decisions", []):
            date = dec.get("date", "")
            month = date[:7] if date else "unknown"
            for pick in dec.get("picks", []):
                code = pick.get("stock", "")
                name = pick.get("name", "")
                result = pick.get("result", "NEUTRAL")
                max_ret = pick.get("fwd_10d_max_pct", 0) or 0
                close_ret = pick.get("fwd_10d_close_pct", 0) or 0

                entry = {
                    "date": date, "stock": code, "name": name,
                    "result": result, "max_ret": max_ret, "close_ret": close_ret,
                    "agent": agent_id
                }
                all_picks.append(entry)

                # Stock stats
                ss = stock_stats[f"{code} {name}"]
                ss["picks"] += 1
                ss["returns"].append(max_ret)
                if result == "BIG_WIN": ss["big_wins"] += 1
                elif result == "WIN": ss["wins"] += 1
                elif result == "NEUTRAL": ss["neutral"] += 1
                elif result == "LOSS": ss["losses"] += 1

                # Monthly stats
                ms = monthly_stats[month]
                ms["picks"] += 1
                if result == "BIG_WIN": ms["big_wins"] += 1
                elif result == "WIN": ms["wins"] += 1
                elif result == "NEUTRAL": ms["neutral"] += 1
                elif result == "LOSS": ms["losses"] += 1

                # Sector stats
                sec = code_to_sector.get(code, "未分类")
                scs = sector_stats[sec]
                scs["picks"] += 1
                scs["returns"].append(max_ret)
                if result == "BIG_WIN": scs["big_wins"] += 1
                elif result == "WIN": scs["wins"] += 1
                elif result == "LOSS": scs["losses"] += 1

    # Overall stats
    total = len(all_picks)
    results = Counter(p["result"] for p in all_picks)
    win_total = results.get("BIG_WIN", 0) + results.get("WIN", 0)
    avg_max = sum(p["max_ret"] for p in all_picks) / total if total else 0
    avg_close = sum(p["close_ret"] for p in all_picks) / total if total else 0

    print("=" * 70)
    print("2021年A股Walk-Forward回测全年汇总")
    print("=" * 70)
    print(f"\n总选股次数: {total}")
    print(f"BIG_WIN (10日最高>10%): {results.get('BIG_WIN', 0)} ({results.get('BIG_WIN',0)/total*100:.1f}%)")
    print(f"WIN (10日最高5-10%):    {results.get('WIN', 0)} ({results.get('WIN',0)/total*100:.1f}%)")
    print(f"NEUTRAL:                {results.get('NEUTRAL', 0)} ({results.get('NEUTRAL',0)/total*100:.1f}%)")
    print(f"LOSS (10日收盘<-5%):    {results.get('LOSS', 0)} ({results.get('LOSS',0)/total*100:.1f}%)")
    print(f"\n综合胜率 (BIG_WIN+WIN): {win_total/total*100:.1f}%")
    print(f"平均10日最高收益: +{avg_max:.1f}%")
    print(f"平均10日收盘收益: +{avg_close:.1f}%")

    # Best/worst picks
    sorted_by_max = sorted(all_picks, key=lambda x: x["max_ret"], reverse=True)
    print(f"\n{'='*70}")
    print("TOP 10 最佳选股")
    print(f"{'='*70}")
    for p in sorted_by_max[:10]:
        print(f"  {p['date']} {p['stock']} {p['name']}: 最高+{p['max_ret']:.1f}% 收盘{p['close_ret']:+.1f}%")

    sorted_by_worst = sorted(all_picks, key=lambda x: x["close_ret"])
    print(f"\n{'='*70}")
    print("TOP 10 最差选股")
    print(f"{'='*70}")
    for p in sorted_by_worst[:10]:
        print(f"  {p['date']} {p['stock']} {p['name']}: 最高+{p['max_ret']:.1f}% 收盘{p['close_ret']:+.1f}%")

    # Per-agent summary
    print(f"\n{'='*70}")
    print("各Agent期间表现")
    print(f"{'='*70}")
    print(f"{'ID':<15} {'期间':<28} {'选股':>4} {'大胜':>4} {'胜':>4} {'中':>4} {'亏':>4} {'胜率':>6}")
    for a in agent_summaries:
        tp = a["total_picks"]
        wr = (a["big_wins"] + a["wins"]) / tp * 100 if tp else 0
        print(f"{a['id']:<15} {a['range']:<28} {tp:>4} {a['big_wins']:>4} {a['wins']:>4} {a['neutral']:>4} {a['losses']:>4} {wr:>5.1f}%")

    # Monthly breakdown
    print(f"\n{'='*70}")
    print("月度表现")
    print(f"{'='*70}")
    for month in sorted(monthly_stats.keys()):
        ms = monthly_stats[month]
        tp = ms["picks"]
        wr = (ms["big_wins"] + ms["wins"]) / tp * 100 if tp else 0
        print(f"  {month}: {tp}选 | 大胜{ms['big_wins']} 胜{ms['wins']} 中{ms['neutral']} 亏{ms['losses']} | 胜率{wr:.0f}%")

    # Sector breakdown
    print(f"\n{'='*70}")
    print("板块表现")
    print(f"{'='*70}")
    for sec in sorted(sector_stats.keys(), key=lambda x: sum(sector_stats[x]["returns"])/len(sector_stats[x]["returns"]) if sector_stats[x]["returns"] else 0, reverse=True):
        ss = sector_stats[sec]
        tp = ss["picks"]
        avg = sum(ss["returns"]) / tp if tp else 0
        wr = (ss["big_wins"] + ss["wins"]) / tp * 100 if tp else 0
        print(f"  {sec:<12}: {tp:>3}选 | 大胜{ss['big_wins']:>2} 胜{ss['wins']:>2} 亏{ss['losses']:>2} | 胜率{wr:>5.1f}% | 均收益+{avg:.1f}%")

    # Most picked stocks
    print(f"\n{'='*70}")
    print("最常选股TOP15")
    print(f"{'='*70}")
    sorted_stocks = sorted(stock_stats.items(), key=lambda x: x[1]["picks"], reverse=True)
    for name, ss in sorted_stocks[:15]:
        tp = ss["picks"]
        avg = sum(ss["returns"]) / tp if tp else 0
        wr = (ss["big_wins"] + ss["wins"]) / tp * 100 if tp else 0
        print(f"  {name:<20}: {tp:>2}次 | 大胜{ss['big_wins']:>2} 胜{ss['wins']:>2} 中{ss['neutral']:>2} 亏{ss['losses']:>2} | 胜率{wr:>5.1f}% | 均+{avg:.1f}%")

    # Save synthesis JSON
    synthesis = {
        "year": 2021,
        "total_picks": total,
        "results": dict(results),
        "win_rate": round(win_total / total * 100, 1) if total else 0,
        "avg_max_return": round(avg_max, 1),
        "avg_close_return": round(avg_close, 1),
        "top10_picks": [{"date": p["date"], "stock": p["stock"], "name": p["name"], "max_ret": p["max_ret"]} for p in sorted_by_max[:10]],
        "worst10_picks": [{"date": p["date"], "stock": p["stock"], "name": p["name"], "close_ret": p["close_ret"]} for p in sorted_by_worst[:10]],
        "agent_summaries": agent_summaries,
        "monthly_stats": {k: dict(v) for k, v in sorted(monthly_stats.items())},
        "sector_stats": {k: {"picks": v["picks"], "big_wins": v["big_wins"], "wins": v["wins"], "losses": v["losses"], "avg_return": round(sum(v["returns"])/len(v["returns"]),1) if v["returns"] else 0} for k, v in sector_stats.items()},
    }
    out = os.path.join(RESULTS_DIR, "synthesis-2021.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(synthesis, f, ensure_ascii=False, indent=1)
    print(f"\n汇总JSON已写入: {out}")

if __name__ == "__main__":
    main()
