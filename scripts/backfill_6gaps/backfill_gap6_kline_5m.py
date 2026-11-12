#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缺口 6: 五年首板股分时分钟线历史回补 (腾讯毫秒级 HTTP 接口)
目标库: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/first_board_5min_kline_5y.db
"""
import os
import sys
import time
import json
import sqlite3
import datetime
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/first_board_5min_kline_5y.db"
KPL_JSONL = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl"

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS kline_minute (
        sec_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        time_min TEXT NOT NULL,
        price REAL NOT NULL,
        volume INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (sec_code, trade_date, time_min)
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_km_code_date ON kline_minute(sec_code, trade_date);")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS crawl_progress (
        sec_code TEXT PRIMARY KEY,
        status TEXT,
        bars_count INTEGER,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()

def fetch_minute_bars(code: str):
    pre = "sh" if code.startswith("6") else "sz"
    url = f"http://data.gtimg.cn/flashdata/hushen/minute/{pre}{code}.js"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            txt = resp.read().decode("gbk", "ignore")
            # 解析 min_data
            # date:211008
            # 0930 18.17 69011
            lines = txt.split("\\n")
            date_str = ""
            bars = []
            for line in lines:
                line = line.strip().strip('"').strip(';')
                if line.startswith("date:"):
                    raw_d = line.split(":")[1].strip()
                    # 211008 -> 2021-10-08
                    if len(raw_d) == 6:
                        date_str = f"20{raw_d[:2]}-{raw_d[2:4]}-{raw_d[4:]}"
                elif len(line.split()) >= 3:
                    parts = line.split()
                    t_min = parts[0]
                    p_val = float(parts[1])
                    v_val = int(parts[2])
                    if date_str:
                        bars.append((code, date_str, t_min, p_val, v_val))
            return code, bars
    except Exception:
        return code, []

def main():
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 启动缺口6 首板股分时线回补引擎...")
    init_db()
    
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    cur = conn.cursor()
    done = set(r[0] for r in cur.execute("SELECT sec_code FROM crawl_progress WHERE status='OK'").fetchall())
    
    # 提取首板唯一股票池
    unique_stocks = set()
    with open(KPL_JSONL, "r") as f:
        for line in f:
            if line.strip():
                try:
                    obj = json.loads(line)
                    for pl in obj.get("plates", []):
                        for st in pl.get("stocks", []):
                            c = st[0]
                            if len(c) == 6 and c.isdigit():
                                unique_stocks.add(c)
                except Exception:
                    pass
                    
    tasks = sorted(list(unique_stocks - done))
    print(f"首板股池唯一股票数: {len(unique_stocks)}, 待拉取: {len(tasks)}")
    if not tasks:
        print("所有首板股分时线已全部就绪!")
        conn.close()
        return

    total_inserted = 0
    batch_size = 20
    t0 = time.time()
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        for i in range(0, len(tasks), batch_size):
            chunk = tasks[i:i+batch_size]
            futures = [executor.submit(fetch_minute_bars, c) for c in chunk]
            
            for f in as_completed(futures):
                code, bars = f.result()
                ins = 0
                for b in bars:
                    try:
                        cur.execute("""
                        INSERT OR IGNORE INTO kline_minute (sec_code, trade_date, time_min, price, volume)
                        VALUES (?, ?, ?, ?, ?)
                        """, b)
                        if cur.rowcount > 0:
                            ins += 1
                    except Exception:
                        pass
                cur.execute("""
                INSERT OR REPLACE INTO crawl_progress (sec_code, status, bars_count, updated_at)
                VALUES (?, 'OK', ?, CURRENT_TIMESTAMP)
                """, (code, ins))
                total_inserted += ins
                
            conn.commit()
            elapsed = time.time() - t0
            done_cnt = min(i + batch_size, len(tasks))
            rate = done_cnt / (elapsed + 0.001)
            if (i // batch_size) % 5 == 0:
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 分时拉取进度: {done_cnt}/{len(tasks)} 股, 累计落盘条数: {total_inserted}, 速度: {rate:.1f}股/秒", flush=True)

    conn.close()
    print("缺口6 回补完成!")

if __name__ == "__main__":
    main()
