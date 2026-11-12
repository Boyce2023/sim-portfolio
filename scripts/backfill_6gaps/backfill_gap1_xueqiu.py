#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缺口 1: 雪球五年历史个股原帖CDP高频穿透引擎 (增强修复版)
目标库: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/xueqiu_guba_5y_pit.db
"""
import os
import re
import sys
import time
import json
import sqlite3
import datetime
import urllib.request
import urllib.parse
import random

DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/xueqiu_guba_5y_pit.db"
KPL_JSONL = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl"
LOCK_FILE = "/Users/huaichuaibeimeng/claude-projects/news-dashboard/output/_twitter_fetch.lock"

def check_lock():
    return os.path.exists(LOCK_FILE)

def cdp_call(path, data=None):
    url = f"http://127.0.0.1:3456{path}"
    req = urllib.request.Request(url, data=data.encode("utf-8") if data else None,
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", "ignore")

def get_xueqiu_tab():
    try:
        targets = json.loads(cdp_call("/targets"))
        for t in targets:
            if "xueqiu.com" in t.get("url", ""):
                return t["targetId"]
        res = json.loads(cdp_call("/new?url=https://xueqiu.com/"))
        time.sleep(3)
        return res.get("targetId")
    except Exception:
        return None

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS xueqiu_posts (
        post_id INTEGER PRIMARY KEY,
        symbol TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        created_time_str TEXT NOT NULL,
        text TEXT NOT NULL,
        reply_count INTEGER DEFAULT 0,
        retweet_count INTEGER DEFAULT 0,
        fav_count INTEGER DEFAULT 0,
        query_term TEXT,
        d1_date TEXT,
        created_at_dt TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_xq_symbol ON xueqiu_posts(symbol);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_xq_created ON xueqiu_posts(created_at);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_xq_d1 ON xueqiu_posts(d1_date);")
    conn.commit()
    conn.close()

def fetch_xueqiu_posts_for_term(target_id, symbol, q_term, page=1):
    market_sym = ("SH" if symbol.startswith("6") else "SZ") + symbol
    enc_q = urllib.parse.quote(q_term)
    js = f"""
    (async () => {{
        try {{
            const url = '/query/v1/symbol/search/status.json?count=20&comment=0&symbol={market_sym}&hl=0&source=all&sort=time&page={page}&q={enc_q}';
            const resp = await fetch(url, {{credentials: 'include'}});
            if (resp.status !== 200) return {{status: resp.status, list: []}};
            const data = await resp.json();
            return {{
                status: 200,
                list: (data.list || []).map(x => ({{
                    id: x.id,
                    text: (x.text || '').replace(/<[^>]+>/g, ''),
                    created_at: x.created_at,
                    reply_count: x.reply_count || 0,
                    retweet_count: x.retweet_count || 0,
                    fav_count: x.fav_count || 0
                }}))
            }};
        }} catch(e) {{
            return {{status: -1, error: e.toString(), list: []}};
        }}
    }})()
    """
    try:
        res = json.loads(cdp_call(f"/eval?target={target_id}", data=js))
        val = res.get("value") or {}
        return val.get("list", [])
    except Exception:
        return []

def main():
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 启动缺口1 雪球五年个股原帖CDP穿透回补引擎 (修复版)...")
    init_db()
    
    # 提取首板任务
    stock_tasks = []
    seen = set()
    with open(KPL_JSONL, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                d1 = row.get("date")
                for p in row.get("plates", []):
                    pname = p.get("plate", "")
                    for st in p.get("stocks", []):
                        if isinstance(st, list) and len(st) >= 1:
                            code = st[0]
                            r_kw = st[2] if len(st) > 2 else pname
                            key = f"{code}_{d1}"
                            if key not in seen and len(code) == 6:
                                seen.add(key)
                                stock_tasks.append((code, d1, r_kw))
            except Exception:
                pass
                
    print(f"提取首板候选股票-日期共: {len(stock_tasks)} 组")
    
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS crawl_progress (source TEXT, task_key TEXT PRIMARY KEY, status TEXT, count INTEGER, updated_at TEXT);")
    done_keys = set(r[0] for r in cur.execute("SELECT task_key FROM crawl_progress WHERE source='xueqiu' AND status='OK'").fetchall())
    conn.commit()
    conn.close()
    
    print(f"已处理: {len(done_keys)} 组，待抓取: {len(stock_tasks) - len(done_keys)} 组")
    
    tab_id = get_xueqiu_tab()
    if not tab_id:
        print("无法连上雪球 CDP Tab，退出！")
        return
    print(f"雪球已连上 CDP Tab: {tab_id}")
    
    total_new_saved = 0
    t0 = time.time()
    
    for idx, (code, d1, r_kw) in enumerate(stock_tasks, 1):
        t_key = f"{code}_{d1}"
        if t_key in done_keys:
            continue
            
        while check_lock():
            time.sleep(1)
            
        # 优先使用原因词，无原因词使用通用词
        query_terms = [r_kw, "涨停"] if r_kw else ["涨停", "首板"]
        
        all_posts = []
        for q_term in query_terms:
            posts = fetch_xueqiu_posts_for_term(tab_id, code, q_term, page=1)
            if not posts and tab_id:
                # 检查 tab 是否失效
                tab_id = get_xueqiu_tab()
                if tab_id:
                    posts = fetch_xueqiu_posts_for_term(tab_id, code, q_term, page=1)
            if posts:
                all_posts.extend(posts)
                
        # 入库
        conn = sqlite3.connect(DB_PATH, timeout=60.0)
        cur = conn.cursor()
        inserted_this = 0
        for p in all_posts:
            p_id = p.get("id")
            if not p_id:
                continue
            ts = p.get("created_at") or 0
            dt_str = datetime.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M:%S") if ts else ""
            try:
                cur.execute("""
                INSERT OR IGNORE INTO xueqiu_posts
                (post_id, symbol, created_at, created_time_str, text, reply_count, retweet_count, fav_count, query_term, d1_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    p_id, code, ts, dt_str, p.get("text", ""),
                    p.get("reply_count", 0), p.get("retweet_count", 0), p.get("fav_count", 0),
                    r_kw or "涨停", d1
                ))
                if cur.rowcount > 0:
                    inserted_this += 1
            except Exception:
                pass
                
        cur.execute("""
        INSERT OR REPLACE INTO crawl_progress (source, task_key, status, count, updated_at)
        VALUES ('xueqiu', ?, 'OK', ?, CURRENT_TIMESTAMP)
        """, (t_key, inserted_this))
        conn.commit()
        conn.close()
        
        total_new_saved += inserted_this
        done_keys.add(t_key)
        
        if idx % 10 == 0:
            elapsed = max(time.time() - t0, 1.0)
            rate = idx / elapsed
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 进度: [{idx}/{len(stock_tasks)}] 累计新增雪球原帖: {total_new_saved} 条 (速度: {rate:.1f}组/秒, 当组入库: {inserted_this})", flush=True)
            
        time.sleep(random.uniform(0.2, 0.4))
        
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 雪球回补全量完成，累计入库 {total_new_saved} 条。")

if __name__ == "__main__":
    main()
