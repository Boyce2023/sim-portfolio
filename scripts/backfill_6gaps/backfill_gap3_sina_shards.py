#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缺口 3: 新浪 7x24 小时五年财经快讯五分片高并发穿透引擎 (2021-01-01 至 2026-11-11)
目标库: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/flash_news_5y_pit.db
"""
import os
import re
import sys
import time
import json
import sqlite3
import datetime
import threading
import requests

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/flash_news_5y_pit.db"
UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn/"
}

# 5 个分片区间 (ID 降序倒退)
SHARDS = [
    ("Shard-2021", 1980000, 2600000), # 2021 ~ early 2022
    ("Shard-2022", 2600000, 3250000), # 2022 ~ early 2023
    ("Shard-2023", 3250000, 3900000), # 2023 ~ early 2024
    ("Shard-2024", 3900000, 4550000), # 2024 ~ 2025
    ("Shard-2025-2026", 4550000, 5210000), # 2025 ~ 2026
]

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("PRAGMA busy_timeout = 60000;")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS flash_news (
        news_id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        pub_datetime_cst TEXT NOT NULL,
        pub_ts_ms INTEGER NOT NULL,
        is_weekend INTEGER DEFAULT 0,
        title TEXT,
        content TEXT NOT NULL,
        raw_json TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fn_pub_dt ON flash_news(pub_datetime_cst);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fn_is_wk ON flash_news(is_weekend);")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS shard_progress (
        shard_name TEXT PRIMARY KEY,
        current_cursor INTEGER,
        min_id INTEGER,
        max_id INTEGER,
        total_inserted INTEGER,
        status TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()

def is_weekend_window(dt: datetime.datetime) -> bool:
    wd = dt.weekday()
    hour = dt.hour
    minute = dt.minute
    if wd == 4 and (hour > 15 or (hour == 15 and minute >= 0)):
        return True
    if wd in (5, 6):
        return True
    if wd == 0 and (hour < 9 or (hour == 9 and minute <= 25)):
        return True
    return False

def get_session():
    s = requests.Session()
    s.trust_env = False
    adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=3)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

def fetch_cursor_batch(session, cursor_id):
    url = f"https://zhibo.sina.com.cn/api/zhibo/feed?zhibo_id=152&id={cursor_id}&type=1&page_size=50"
    for _ in range(3):
        try:
            r = session.get(url, headers=UA, timeout=12)
            if r.status_code == 200:
                data = r.json()
                items = data.get("result", {}).get("data", {}).get("feed", {}).get("list", [])
                return items
        except Exception:
            time.sleep(0.5)
    return None

db_lock = threading.Lock()

def run_shard(shard_name: str, min_id: int, max_id: int):
    session = get_session()
    
    # 查断点
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=60.0)
        cur = conn.cursor()
        cur.execute("SELECT current_cursor FROM shard_progress WHERE shard_name=?", (shard_name,))
        row = cur.fetchone()
        conn.close()
        
    current_cursor = row[0] if (row and row[0]) else max_id
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 启动分片 [{shard_name}]: 起始游标 ID {current_cursor} -> 终点 ID {min_id}")
    
    empty_streak = 0
    total_shard_inserted = 0
    
    while current_cursor > min_id:
        items = fetch_cursor_batch(session, current_cursor)
        if items is None:
            time.sleep(1)
            continue
            
        if not items:
            empty_streak += 1
            if empty_streak >= 5:
                # 尝试越过坏块
                current_cursor -= 500
                empty_streak = 0
                if current_cursor <= min_id:
                    break
                continue
            time.sleep(0.5)
            continue
            
        empty_streak = 0
        batch_news = []
        batch_ids = []
        
        for it in items:
            create_time = it.get("create_time", "")
            if not create_time:
                continue
            try:
                dt = datetime.datetime.strptime(create_time[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
                
            ts_ms = int(dt.timestamp() * 1000)
            doc_id = str(it.get("id"))
            try:
                batch_ids.append(int(doc_id))
            except ValueError:
                pass
                
            rich_text = it.get("rich_text", "") or ""
            clean_text = re.sub(r"<.*?>", "", rich_text).strip()
            title = ""
            m = re.search(r"【(.*?)】", clean_text)
            if m:
                title = m.group(1).strip()
            else:
                title = clean_text[:40].strip()
                
            is_wk = 1 if is_weekend_window(dt) else 0
            
            batch_news.append((
                doc_id,
                "sina_724",
                create_time,
                ts_ms,
                is_wk,
                title,
                clean_text,
                json.dumps(it, ensure_ascii=False)
            ))
            
        if not batch_ids:
            current_cursor -= 100
            continue
            
        next_cursor = min(batch_ids)
        if next_cursor >= current_cursor:
            next_cursor = current_cursor - 50
        current_cursor = next_cursor
        
        # 写入数据库
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=60.0)
            cur = conn.cursor()
            if batch_news:
                cur.executemany("""
                INSERT OR IGNORE INTO flash_news (news_id, source, pub_datetime_cst, pub_ts_ms, is_weekend, title, content, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """, batch_news)
                total_shard_inserted += cur.rowcount
            cur.execute("""
            INSERT OR REPLACE INTO shard_progress (shard_name, current_cursor, min_id, max_id, total_inserted, status, updated_at)
            VALUES (?, ?, ?, ?, ?, 'RUNNING', datetime('now', 'localtime'));
            """, (shard_name, current_cursor, min_id, max_id, total_shard_inserted))
            conn.commit()
            conn.close()
            
        time.sleep(0.15)
        
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 分片 [{shard_name}] 到达终点 ID {min_id}，顺利完成！")

def main():
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 启动新浪 7x24 五大分片高并发穿透回补引擎...")
    init_db()
    
    threads = []
    for name, s_min, s_max in SHARDS:
        t = threading.Thread(target=run_shard, args=(name, s_min, s_max), daemon=True)
        threads.append(t)
        t.start()
        time.sleep(0.3)
        
    for t in threads:
        t.join()
        
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 所有分片均已完成！")

if __name__ == "__main__":
    main()
