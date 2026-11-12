#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缺口 3: 7x24 小时五年财经快讯库 (新浪 7x24 游标 &id={min_id}&type=1 连续穿透倒退)
目标库: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/flash_news_5y_pit.db
"""
import os
import re
import sys
import time
import json
import sqlite3
import datetime
import requests

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/flash_news_5y_pit.db"
UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn/"
}

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
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
    cur.execute("CREATE TABLE IF NOT EXISTS crawl_progress_cursor (cursor_id TEXT PRIMARY KEY, min_time TEXT, max_time TEXT, count INTEGER, status TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);")
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
    if cursor_id:
        url = f"https://zhibo.sina.com.cn/api/zhibo/feed?zhibo_id=152&id={cursor_id}&type=1&page_size=50"
    else:
        url = "https://zhibo.sina.com.cn/api/zhibo/feed?zhibo_id=152&page=1&page_size=50&type=0"
    try:
        r = session.get(url, headers=UA, timeout=8)
        if r.status_code == 200:
            data = r.json()
            items = data.get("result", {}).get("data", {}).get("feed", {}).get("list", [])
            return items
    except Exception:
        pass
    return None

def main():
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 启动缺口3 新浪7x24游标穿透引擎...")
    init_db()
    
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    cur = conn.cursor()
    
    # 查找数据库中最小的 news_id 作为起始游标
    cur.execute("SELECT news_id, pub_datetime_cst FROM flash_news ORDER BY pub_ts_ms ASC LIMIT 1")
    row = cur.fetchone()
    current_cursor = row[0] if row else None
    earliest_time = row[1] if row else "当前最新"
    
    print(f"当前库中最早时间: {earliest_time}, 起始游标 ID: {current_cursor}")
    session = get_session()
    
    total_new_inserted = 0
    step = 0
    empty_streak = 0
    t0 = time.time()
    
    while True:
        items = fetch_cursor_batch(session, current_cursor)
        if items is None:
            time.sleep(1)
            items = fetch_cursor_batch(session, current_cursor)
            
        if not items:
            empty_streak += 1
            if empty_streak >= 5:
                print(f"连续 {empty_streak} 次游标为空，停止。")
                break
            time.sleep(1)
            continue
            
        empty_streak = 0
        min_dt = None
        max_dt = None
        min_id = None
        inserted_this_batch = 0
        
        for it in items:
            create_time = it.get("create_time", "")
            if not create_time:
                continue
            try:
                dt = datetime.datetime.strptime(create_time[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
                
            if min_dt is None or dt < min_dt:
                min_dt = dt
            if max_dt is None or dt > max_dt:
                max_dt = dt
                
            news_id = str(it.get("id", ""))
            min_id = news_id
            
            pub_datetime_cst = dt.strftime("%Y-%m-%d %H:%M:%S")
            pub_ts_ms = int(dt.timestamp() * 1000)
            is_wk = 1 if is_weekend_window(dt) else 0
            
            raw_text = it.get("rich_text") or it.get("text", "")
            clean_text = re.sub(r"<[^>]+>", "", raw_text).strip()
            
            title = ""
            m_title = re.match(r"【(.*?)】(.*)", clean_text)
            if m_title:
                title = m_title.group(1).strip()
                content = m_title.group(2).strip()
            else:
                title = clean_text[:40]
                content = clean_text
                
            try:
                cur.execute("""
                INSERT OR IGNORE INTO flash_news 
                (news_id, source, pub_datetime_cst, pub_ts_ms, is_weekend, title, content, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    news_id, "sina_724", pub_datetime_cst, pub_ts_ms, is_wk,
                    title, content, json.dumps(it, ensure_ascii=False)
                ))
                if cur.rowcount > 0:
                    inserted_this_batch += 1
            except Exception:
                pass
                
        # 游标向前推进至本批次最小 ID
        if min_id:
            current_cursor = min_id
            
        cur.execute("""
        INSERT OR REPLACE INTO crawl_progress_cursor (cursor_id, min_time, max_time, count, status, updated_at)
        VALUES (?, ?, ?, ?, 'OK', CURRENT_TIMESTAMP)
        """, (
            str(current_cursor),
            min_dt.strftime("%Y-%m-%d %H:%M:%S") if min_dt else "",
            max_dt.strftime("%Y-%m-%d %H:%M:%S") if max_dt else "",
            inserted_this_batch
        ))
        conn.commit()
        
        total_new_inserted += inserted_this_batch
        step += 1
        
        # 到达 2021-01-01 停止
        if min_dt and min_dt < datetime.datetime(2021, 1, 1):
            print(f"已回溯至 2021-01-01 以前 ({min_dt})，完成全量五年穿透!")
            break
            
        if step % 20 == 0:
            elapsed = time.time() - t0
            rate = total_new_inserted / (elapsed + 0.001)
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 游标 step {step}: 推进至 {min_dt} (ID: {current_cursor}), 新入库: {total_new_inserted}条, 速度: {rate:.1f}条/秒", flush=True)
            
        time.sleep(0.15)
        
    conn.close()
    print("缺口3 游标回补结束!")

if __name__ == "__main__":
    main()
