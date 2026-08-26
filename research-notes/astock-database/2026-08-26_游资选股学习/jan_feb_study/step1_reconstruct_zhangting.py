#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step1: 用 univ2025.db 重构 2025-01-01~2025-02-28 期间涨停股 + 连板数
涨停判定: close == round(preclose*(1+limit_pct), 2)  (允许0.01误差)
limit_pct: 主板/中小板(60/00开头,非创业非科创)=10%; 创业板(300/301)/科创板(688/689)=20%;
           北交所(8/4/9开头)=30%; ST/*ST(isST=1) 主板=5%, 创业科创ST=20%(实际2025年后ST票在创业科创科创板仍20%,
           但为稳妥+isST统一按5%处理仅对主板/中小板生效,创业科创ST仍20%不变)
"""
import sqlite3, json, os
from collections import defaultdict

DB = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/univ2025.db"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26_游资选股学习/jan_feb_study"

START = "2025-01-01"
END = "2025-02-28"

def limit_pct(code, isST):
    code = code.strip()
    # 北交所: 8/4/9 开头 (常见前缀 83/87/88/43/92 etc, 统一按首位数字8/4/9判断)
    if code.startswith(('8', '4', '92')):
        return 0.30
    # 创业板 300/301
    if code.startswith(('300', '301')):
        return 0.20
    # 科创板 688/689
    if code.startswith(('688', '689')):
        return 0.20
    # 主板/中小板 60/00
    if isST:
        return 0.05
    return 0.10

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT code, date, open, high, low, close, preclose, volume, amount, turn, isST
        FROM k WHERE date BETWEEN ? AND ?
        ORDER BY code, date
    """, (START, END))
    rows = cur.fetchall()
    print(f"total rows fetched: {len(rows)}")

    # group by code to compute consecutive board count
    by_code = defaultdict(list)
    for r in rows:
        by_code[r['code']].append(r)

    zt_records = []  # each: code,date,close,preclose,pct,limit_pct_used,turn,amount,is_zt,board_count(consecutive up to this day)
    for code, recs in by_code.items():
        recs.sort(key=lambda r: r['date'])
        board_streak = 0
        for r in recs:
            preclose = r['preclose']
            close = r['close']
            isST = r['isST']
            if preclose is None or close is None or preclose <= 0:
                board_streak = 0
                continue
            lp = limit_pct(code, isST)
            theo_limit_price = round(preclose * (1 + lp), 2)
            is_zt = abs(close - theo_limit_price) <= 0.011  # tolerance for rounding
            if is_zt:
                board_streak += 1
            else:
                board_streak = 0
            if is_zt:
                pct = (close - preclose) / preclose * 100
                zt_records.append({
                    "code": code,
                    "date": r['date'],
                    "close": close,
                    "preclose": preclose,
                    "pct": round(pct, 3),
                    "limit_pct_used": lp,
                    "turn": r['turn'],
                    "amount": r['amount'],
                    "volume": r['volume'],
                    "isST": isST,
                    "board_streak": board_streak,
                })

    print(f"total zhangting instances (2025-01-01~2025-02-28): {len(zt_records)}")

    # per-day counts
    day_counts = defaultdict(int)
    for z in zt_records:
        day_counts[z['date']] += 1
    day_counts_sorted = sorted(day_counts.items(), key=lambda x: -x[1])

    # lianban (>=3 consecutive) - take the max streak instance per code (the day it peaked before breaking, i.e. last day of streak with board_streak>=3)
    # We want: for each code, list of "streak end events" where board_streak>=3 and next day is NOT zt (or last day in period)
    lianban_events = []
    for code, recs in by_code.items():
        recs.sort(key=lambda r: r['date'])
        # recompute streak inline to find end-of-streak points
        streak = 0
        streak_dates = []
        for r in recs:
            preclose = r['preclose']; close = r['close']; isST = r['isST']
            if preclose is None or close is None or preclose <= 0:
                if streak >= 3:
                    lianban_events.append({"code": code, "peak_streak": streak, "dates": streak_dates[:]})
                streak = 0; streak_dates = []
                continue
            lp = limit_pct(code, isST)
            theo = round(preclose*(1+lp), 2)
            is_zt = abs(close - theo) <= 0.011
            if is_zt:
                streak += 1
                streak_dates.append(r['date'])
            else:
                if streak >= 3:
                    lianban_events.append({"code": code, "peak_streak": streak, "dates": streak_dates[:]})
                streak = 0; streak_dates = []
        if streak >= 3:
            lianban_events.append({"code": code, "peak_streak": streak, "dates": streak_dates[:]})

    lianban_events.sort(key=lambda x: -x['peak_streak'])

    # save outputs
    with open(os.path.join(OUT_DIR, "zt_records_janfeb2025.json"), "w", encoding="utf-8") as f:
        json.dump(zt_records, f, ensure_ascii=False, indent=1)

    with open(os.path.join(OUT_DIR, "day_counts_janfeb2025.json"), "w", encoding="utf-8") as f:
        json.dump(day_counts_sorted, f, ensure_ascii=False, indent=1)

    with open(os.path.join(OUT_DIR, "lianban_events_janfeb2025.json"), "w", encoding="utf-8") as f:
        json.dump(lianban_events, f, ensure_ascii=False, indent=1)

    print("\n=== TOP 10 涨停数最多的交易日 ===")
    for d, c in day_counts_sorted[:10]:
        print(d, c)

    print(f"\n=== 连板股(>=3板) 事件数: {len(lianban_events)} ===")
    for e in lianban_events[:20]:
        print(e['code'], e['peak_streak'], e['dates'])

if __name__ == "__main__":
    main()
