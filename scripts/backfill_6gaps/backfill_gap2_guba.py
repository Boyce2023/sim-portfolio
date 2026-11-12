#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缺口 2: 东财股吧五年首板隔夜/周末讨论帖极速回补 (gbcdn 纯静态 CDN + 二分查找)
接口: https://gbcdn.dfcfw.com/gbapi/webarticlelist_api_Article_ArticleList.js?ps=80&p={page}&code={code}
0.05秒直连, 零 WAF 拦截, 每页 80 条带精确秒级发布时间、阅读数、评论数
目标库: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/xueqiu_guba_5y_pit.db
"""
import os
import sys
import time
import json
import sqlite3
import datetime
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/xueqiu_guba_5y_pit.db"
KPL_JSONL = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS guba_posts (
        post_id TEXT PRIMARY KEY,
        sec_code TEXT NOT NULL,
        title TEXT NOT NULL,
        author TEXT,
        pub_time TEXT NOT NULL,
        read_cnt INTEGER DEFAULT 0,
        comment_cnt INTEGER DEFAULT 0,
        d1_date TEXT NOT NULL,
        page INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_guba_code_dt ON guba_posts(sec_code, pub_time);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_guba_d1 ON guba_posts(d1_date);")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS crawl_progress (
        source TEXT,
        task_key TEXT,
        status TEXT,
        count INTEGER,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (source, task_key)
    );
    """)
    conn.commit()
    conn.close()

def fetch_guba_page_json(code: str, page: int):
    url = f"https://gbcdn.dfcfw.com/gbapi/webarticlelist_api_Article_ArticleList.js?ps=80&p={page}&code={code}"
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            txt = resp.read().decode("utf-8", "ignore")
            idx = txt.find("{")
            last_idx = txt.rfind("}")
            if idx != -1 and last_idx != -1:
                data = json.loads(txt[idx:last_idx+1])
                return data.get("re", [])
    except Exception:
        pass
    return []

def binary_search_guba_d1(code: str, d1_date: str):
    """
    针对该首板股票与 D1 日期，用二分查找跳到 D1 所在页码，并拉取该窗口的帖子
    """
    # 探测第 1 页
    p1 = fetch_guba_page_json(code, 1)
    if not p1:
        return []
    
    # 若第 1 页最早时间都已经早于 d1_date，不用二分直接返回 p1
    if p1[-1].get("post_publish_time", "") < d1_date:
        return [p for p in p1 if p.get("post_publish_time", "")[:10] == d1_date]
        
    low = 1
    high = 800
    best_page = 1
    
    for _ in range(8):
        mid = (low + high) // 2
        items = fetch_guba_page_json(code, mid)
        if not items:
            high = mid - 1
            continue
            
        first_time = items[0].get("post_publish_time", "")[:10]
        last_time = items[-1].get("post_publish_time", "")[:10]
        
        if last_time > d1_date:
            low = mid + 1
            best_page = mid
        elif first_time < d1_date:
            high = mid - 1
        else:
            best_page = mid
            break
            
    # 拉取 best_page 及其前后各 1 页
    results = []
    for pg in range(max(1, best_page - 1), best_page + 2):
        items = fetch_guba_page_json(code, pg)
        for it in items:
            p_time = it.get("post_publish_time", "")
            # 取前后 2 天窗口
            results.append({
                "post_id": str(it.get("post_id")),
                "sec_code": code,
                "title": it.get("post_title", ""),
                "author": it.get("user_nickname", ""),
                "pub_time": p_time,
                "read_cnt": it.get("post_click_count", 0),
                "comment_cnt": it.get("post_comment_count", 0),
                "page": pg,
                "d1_date": d1_date
            })
    return results

def process_item(task):
    code, d1_date = task
    posts = binary_search_guba_d1(code, d1_date)
    return code, d1_date, posts

def main():
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 启动缺口2 东财股吧五年隔夜/周末讨论帖极速回补引擎 (gbcdn CDN)...")
    init_db()
    
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    cur = conn.cursor()
    done = set(r[0] for r in cur.execute("SELECT task_key FROM crawl_progress WHERE source='eastmoney_guba' AND count > 0").fetchall())
    conn.close()
    
    tasks = []
    seen = set()
    with open(KPL_JSONL, "r") as f:
        for line in f:
            if line.strip():
                try:
                    obj = json.loads(line)
                    dt = obj.get("date")
                    for pl in obj.get("plates", []):
                        for st in pl.get("stocks", []):
                            c = st[0]
                            k = f"{c}_{dt}"
                            if len(c) == 6 and c.isdigit() and k not in done and k not in seen:
                                seen.add(k)
                                tasks.append((c, dt))
                except Exception:
                    pass
                    
    print(f"待拉取首板讨论窗口: {len(tasks)}")
    if not tasks:
        print("所有首板讨论帖已全部回补完毕!")
        return

    db_conn = sqlite3.connect(DB_PATH, timeout=60.0)
    db_cur = db_conn.cursor()
    
    batch_size = 20
    total_saved = 0
    t0 = time.time()
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        for i in range(0, len(tasks), batch_size):
            chunk = tasks[i:i+batch_size]
            futures = [executor.submit(process_item, t) for t in chunk]
            
            for f in as_completed(futures):
                code, d1_date, posts = f.result()
                t_key = f"{code}_{d1_date}"
                ins = 0
                for p in posts:
                    try:
                        db_cur.execute("""
                        INSERT OR IGNORE INTO guba_posts
                        (post_id, sec_code, title, author, pub_time, read_cnt, comment_cnt, d1_date, page)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            p["post_id"], code, p["title"], p["author"],
                            p["pub_time"], p["read_cnt"], p["comment_cnt"],
                            d1_date, p["page"]
                        ))
                        if db_cur.rowcount > 0:
                            ins += 1
                    except Exception:
                        pass
                db_cur.execute("""
                INSERT OR REPLACE INTO crawl_progress (source, task_key, status, count, updated_at)
                VALUES (?, ?, 'OK', ?, CURRENT_TIMESTAMP)
                """, ("eastmoney_guba", t_key, ins))
                total_saved += ins
                
            db_conn.commit()
            elapsed = time.time() - t0
            done_cnt = min(i + batch_size, len(tasks))
            rate = done_cnt / (elapsed + 0.001)
            eta = (len(tasks) - done_cnt) / (rate + 0.001) / 60
            if (i // batch_size) % 5 == 0 or i + batch_size >= len(tasks):
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 股吧已处理 {done_cnt}/{len(tasks)} 窗口, 累计落盘帖子: {total_saved}, 速率: {rate:.1f}窗口/秒, 预计剩余: {eta:.1f}分", flush=True)

    db_conn.close()
    print("缺口2 回补完毕!")

if __name__ == "__main__":
    main()
