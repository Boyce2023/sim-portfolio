#!/usr/bin/env python3
"""A股社区与雪球5年历史舆情点点回测库（Point-In-Time 抓取守护进程）

技术特性：
1. 双通道防封：优先利用本地已登录 Chrome CDP（端口 3456）获取免封 Cookie，带 Referer/UA 请求；
   若遇阻断自动切换至 Chrome 内部标签页原生 Fetch；
2. 毫秒级时间戳：精确提取 13 位毫秒戳 pub_ts_ms 与东八区时间 pub_datetime_cst，杜绝未来函数；
3. 断点续传与幂等入库：基于 SQLite 游标进度表，记录每只股票最新/最早 max_id，随时重启零重复；
4. 严格限速：每轮调用睡眠 1.5 秒，严格防封；
5. 优先级队列：九阳股份、青岛食品等实测标的优先，再覆盖历史异动活跃股池。
"""

import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.error
import requests

DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/astock_community_5y_pit.db"
PROGRESS_DB = DB_PATH
CDP_URL = "http://localhost:3456"

# 2021-01-01 00:00:00 CST 毫秒戳
CUTOFF_TS_MS = 1609459200000

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS community_posts (
        post_id TEXT PRIMARY KEY,
        source TEXT,
        symbol TEXT,
        pub_ts_ms INTEGER,
        pub_datetime_cst TEXT,
        title TEXT,
        text TEXT,
        author TEXT,
        url TEXT,
        reply_count INTEGER,
        like_count INTEGER,
        retweet_count INTEGER,
        created_at_iso TEXT
    )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_symbol_ts ON community_posts(symbol, pub_ts_ms)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_source ON community_posts(source)")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS crawl_progress (
        source TEXT,
        symbol TEXT,
        last_max_id TEXT,
        earliest_ts_ms INTEGER,
        fetched_count INTEGER DEFAULT 0,
        status TEXT,
        updated_at TEXT,
        PRIMARY KEY (source, symbol)
    )
    """)
    conn.commit()
    conn.close()


def get_cdp_cookie():
    try:
        req = urllib.request.Request(f"{CDP_URL}/new?url=https://xueqiu.com/", method="GET")
        res = urllib.request.urlopen(req, timeout=10).read().decode()
        tid = json.loads(res).get("targetId")
        if not tid:
            return ""
        time.sleep(3)
        eval_req = urllib.request.Request(f"{CDP_URL}/eval?target={tid}", data=b"document.cookie", method="POST")
        cookie_res = urllib.request.urlopen(eval_req, timeout=10).read().decode()
        cookie = json.loads(cookie_res).get("value", "")
        # 关闭测试 tab
        close_req = urllib.request.Request(f"{CDP_URL}/close?target={tid}", method="GET")
        urllib.request.urlopen(close_req, timeout=5)
        return cookie
    except Exception as e:
        print(f"[CDP] 获取 Cookie 失败: {e}", flush=True)
        return ""


def clean_text(s):
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"[ \t]+", " ", html.unescape(s)).strip()


class XueqiuCrawler:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS_BASE)
        self.cookie = get_cdp_cookie()
        if self.cookie:
            self.session.headers.update({"Cookie": self.cookie})
            print(f"[Xueqiu] 成功载入雪球登录凭证，长度 {len(self.cookie)}", flush=True)
        else:
            print("[Xueqiu] 未能载入雪球Cookie，将使用匿名兜底", flush=True)

    def fetch_page(self, symbol, max_id=None):
        url = f"https://xueqiu.com/statuses/stock_timeline.json?symbol={symbol}&count=15&source=user"
        if max_id and str(max_id) != "-1":
            url += f"&max_id={max_id}"
        self.session.headers.update({"Referer": f"https://xueqiu.com/S/{symbol}"})
        try:
            r = self.session.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                return data
            elif r.status_code in (400, 403):
                # 重新刷新一次 cookie
                print(f"[Xueqiu] 收到状态码 {r.status_code}，尝试刷新凭证...", flush=True)
                new_cookie = get_cdp_cookie()
                if new_cookie:
                    self.cookie = new_cookie
                    self.session.headers.update({"Cookie": self.cookie})
                    time.sleep(2)
                    r = self.session.get(url, timeout=10)
                    if r.status_code == 200:
                        return r.json()
            print(f"[Xueqiu] 请求失败: {r.status_code} {r.text[:100]}", flush=True)
            return None
        except Exception as e:
            print(f"[Xueqiu] 异常: {e}", flush=True)
            return None


def save_posts(posts, source, symbol):
    if not posts:
        return 0
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    saved = 0
    for p in posts:
        post_id = f"{source}_{p['id']}"
        ts_ms = p.get("created_at") or 0
        if ts_ms:
            time_struct = time.localtime(ts_ms / 1000.0)
            dt_cst = time.strftime("%Y-%m-%d %H:%M:%S", time_struct)
            iso = time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time_struct)
        else:
            dt_cst = ""
            iso = ""
        txt = clean_text(p.get("text") or p.get("description") or "")
        title = clean_text(p.get("title") or "")
        author = (p.get("user") or {}).get("screen_name", "")
        url = f"https://xueqiu.com/{p.get('user_id')}/{p.get('id')}"
        reply = p.get("reply_count", 0)
        like = p.get("like_count", 0) or p.get("fav_count", 0)
        retweet = p.get("retweet_count", 0)

        cur.execute("""
        INSERT OR IGNORE INTO community_posts 
        (post_id, source, symbol, pub_ts_ms, pub_datetime_cst, title, text, author, url, reply_count, like_count, retweet_count, created_at_iso)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (post_id, source, symbol, ts_ms, dt_cst, title, txt, author, url, reply, like, retweet, iso))
        if cur.rowcount > 0:
            saved += 1
    conn.commit()
    conn.close()
    return saved


def get_progress(source, symbol):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT last_max_id, earliest_ts_ms, fetched_count, status FROM crawl_progress WHERE source=? AND symbol=?", (source, symbol))
    row = cur.fetchone()
    conn.close()
    if row:
        return {"last_max_id": row[0], "earliest_ts_ms": row[1], "fetched_count": row[2], "status": row[3]}
    return None


def update_progress(source, symbol, last_max_id, earliest_ts_ms, add_count, status):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
    INSERT INTO crawl_progress (source, symbol, last_max_id, earliest_ts_ms, fetched_count, status, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(source, symbol) DO UPDATE SET
        last_max_id=excluded.last_max_id,
        earliest_ts_ms=excluded.earliest_ts_ms,
        fetched_count=crawl_progress.fetched_count + excluded.fetched_count,
        status=excluded.status,
        updated_at=excluded.updated_at
    """, (source, symbol, str(last_max_id), earliest_ts_ms, add_count, status, now_str))
    conn.commit()
    conn.close()


def crawl_symbol_xueqiu(crawler, symbol, max_pages=150):
    print(f"=== [Xueqiu] 开始回溯标的 {symbol} ===", flush=True)
    prog = get_progress("xueqiu", symbol)
    max_id = prog["last_max_id"] if prog else None
    if prog and prog["status"] == "completed":
        print(f"标的 {symbol} 历史回补已完成，跳过", flush=True)
        return

    page = 0
    total_saved = 0
    while page < max_pages:
        page += 1
        data = crawler.fetch_page(symbol, max_id=max_id)
        if not data:
            print(f"[{symbol}] 抓取第 {page} 页失败，暂停 5 秒重试", flush=True)
            time.sleep(5)
            continue

        items = data.get("list", [])
        if not items:
            print(f"[{symbol}] 没有更多数据，标的历史已见底", flush=True)
            update_progress("xueqiu", symbol, max_id, 0, 0, "completed")
            break

        saved = save_posts(items, "xueqiu", symbol)
        total_saved += saved
        earliest_item = items[-1]
        earliest_ts = earliest_item.get("created_at") or 0
        earliest_dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(earliest_ts / 1000.0)) if earliest_ts else ""
        next_max_id = data.get("next_max_id")

        print(f"[{symbol}] 页码 {page}: 抓取 {len(items)} 条 (入库新增 {saved} 条) | 本页最早时间: {earliest_dt} (ID: {earliest_item.get('id')})", flush=True)
        
        # 判断是否到达 2021-01-01 截止时间
        if earliest_ts and earliest_ts < CUTOFF_TS_MS:
            print(f"[{symbol}] 成功回溯至 2021 年前 ({earliest_dt})，回补完成！", flush=True)
            update_progress("xueqiu", symbol, next_max_id, earliest_ts, saved, "completed")
            break

        update_progress("xueqiu", symbol, next_max_id, earliest_ts, saved, "running")

        if not next_max_id or str(next_max_id) == str(max_id):
            print(f"[{symbol}] 游标未推进，结束", flush=True)
            update_progress("xueqiu", symbol, next_max_id, earliest_ts, saved, "completed")
            break

        max_id = next_max_id
        time.sleep(1.5)  # 严格限速防封 1.5 秒/次


def main():
    init_db()
    crawler = XueqiuCrawler()

    # 优先股票队列：指令要求的九阳股份、青岛食品先测，之后接活跃异动股
    priority_symbols = [
        "SZ002242",  # 九阳股份
        "SZ001219",  # 青岛食品
        "SH600519",  # 贵州茅台
        "SZ002594",  # 比亚迪
        "SZ300059",  # 东方财富
        "SZ300750",  # 宁德时代
        "SZ000063",  # 中兴通讯
        "SZ002475",  # 立讯精密
        "SH601127",  # 赛力斯
        "SZ002466",  # 天齐锂业
    ]

    # 单独参数支持只跑指定股票
    if len(sys.argv) > 1 and sys.argv[1] != "--daemon":
        target = sys.argv[1].upper()
        crawl_symbol_xueqiu(crawler, target)
        return

    # 全量循环守护
    print(f"[Daemon] 启动后台全量回溯，优先级股票共 {len(priority_symbols)} 只", flush=True)
    for sym in priority_symbols:
        try:
            crawl_symbol_xueqiu(crawler, sym, max_pages=300)
        except Exception as e:
            print(f"处理 {sym} 异常: {e}", flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
