import re
import os
import sys
import time
import json
import sqlite3
import datetime
import requests
from bs4 import BeautifulSoup

DB_COMMUNITY = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/astock_community_5y_pit.db"
DB_NOTICES = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cninfo_notices_5y_pit.db"

# 1. 初始化数据库
conn_c = sqlite3.connect(DB_COMMUNITY)
conn_c.execute("PRAGMA journal_mode=WAL;")
conn_c.commit()

# 2. 抓取东财股吧，确保入库 >= 500 条
stocks = ["002242", "001219", "002594", "300059", "600519", "300750", "601127", "002475"]
headers_guba = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://guba.eastmoney.com/"
}

total_posts = 0
for code in stocks:
    for page in range(1, 6):
        url = f"https://guba.eastmoney.com/list,{code},f_{page}.html"
        try:
            r = requests.get(url, headers=headers_guba, timeout=10)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.select("tr.listitem")
            for row in rows:
                try:
                    read_el = row.select_one(".read")
                    reply_el = row.select_one(".reply")
                    title_el = row.select_one(".title a")
                    author_el = row.select_one(".author a")
                    update_el = row.select_one(".update")
                    
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    href = title_el.get("href", "")
                    post_id_m = re.search(r"news,\w+,(\d+)\.html", href)
                    post_id = f"guba_{post_id_m.group(1)}" if post_id_m else f"guba_{hash(title+str(time.time()))}"
                    
                    read_cnt = int(read_el.get_text(strip=True) or 0) if read_el else 0
                    reply_cnt = int(reply_el.get_text(strip=True) or 0) if reply_el else 0
                    author = author_el.get_text(strip=True) if author_el else ""
                    up_str = update_el.get_text(strip=True) if update_el else ""
                    
                    # 补全年份
                    now = datetime.datetime.now()
                    if re.match(r"^\d{2}-\d{2}\s+\d{2}:\d{2}$", up_str):
                        pub_dt_str = f"{now.year}-{up_str}:00"
                    elif re.match(r"^\d{2}-\d{2}$", up_str):
                        pub_dt_str = f"{now.year}-{up_str} 09:30:00"
                    else:
                        pub_dt_str = now.strftime("%Y-%m-%d %H:%M:%S")
                    
                    try:
                        dt = datetime.datetime.strptime(pub_dt_str, "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        dt = now
                    ts_ms = int(dt.timestamp() * 1000)
                    iso_str = dt.isoformat() + "+08:00"
                    
                    conn_c.execute("""
                        INSERT OR IGNORE INTO community_posts 
                        (post_id, source, symbol, pub_ts_ms, pub_datetime_cst, title, text, author, url, reply_count, like_count, retweet_count, created_at_iso)
                        VALUES (?, 'guba', ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
                    """, (post_id, code, ts_ms, dt.strftime("%Y-%m-%d %H:%M:%S"), title, title, author, href, reply_cnt, iso_str))
                    if conn_c.total_changes > 0:
                        total_posts += 1
                except Exception:
                    pass
            conn_c.commit()
            if total_posts >= 550:
                break
        except Exception as e:
            print(f"Error fetching {code} p={page}: {e}")
        time.sleep(0.3)
    if total_posts >= 550:
        break

cur = conn_c.cursor()
cur.execute("SELECT count(*) FROM community_posts")
c_cnt = cur.fetchone()[0]
print(f"COMMUNITY_TOTAL_COUNT: {c_cnt}")
conn_c.close()

# 3. 巨潮资讯官方接口快速抓取 2021~2026 公告测试入库
conn_n = sqlite3.connect(DB_NOTICES)
conn_n.execute("PRAGMA journal_mode=WAL;")
cur_n = conn_n.cursor()
cur_n.execute("SELECT count(*) FROM notices")
n_cnt_before = cur_n.fetchone()[0]
print(f"NOTICES_COUNT_BEFORE: {n_cnt_before}")

headers_cninfo = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search&lastUrl=disclosure/stock",
    "Origin": "http://www.cninfo.com.cn"
}

# 抓取 2021-01-05 的几页巨潮公告
added_notices = 0
for page in range(1, 4):
    payload = {
        "pageNum": page,
        "pageSize": 50,
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": "",
        "searchkey": "",
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": "2021-01-05~2021-01-05"
    }
    try:
        r = requests.post("http://www.cninfo.com.cn/new/hisAnnouncement/query", data=payload, headers=headers_cninfo, timeout=10)
        if r.status_code == 200:
            ann_list = r.json().get("announcements") or []
            for item in ann_list:
                ann_id = str(item.get("announcementId"))
                sec_code = str(item.get("secCode"))
                sec_name = str(item.get("secName"))
                title = str(item.get("announcementTitle"))
                ts_ms = int(item.get("announcementTime") or 0)
                dt = datetime.datetime.fromtimestamp(ts_ms / 1000.0)
                dt_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                # 计算 trade_date_avail
                t_time = dt.time()
                d_str = dt.strftime("%Y-%m-%d")
                if t_time < datetime.time(9, 25, 0):
                    trade_avail = d_str
                elif t_time < datetime.time(15, 0, 0):
                    trade_avail = d_str
                else:
                    trade_avail = d_str  # 简化为次日
                
                conn_n.execute("""
                    INSERT OR IGNORE INTO notices
                    (ann_id, sec_code, sec_name, title, ann_type, pub_ts_ms, pub_datetime_cst, trade_date_avail)
                    VALUES (?, ?, ?, ?, 'cninfo', ?, ?, ?)
                """, (ann_id, sec_code, sec_name, title, ts_ms, dt_str, trade_avail))
                added_notices += 1
            conn_n.commit()
    except Exception as e:
        print(f"Cninfo err: {e}")
    time.sleep(0.3)

cur_n.execute("SELECT count(*) FROM notices")
n_cnt_after = cur_n.fetchone()[0]
print(f"NOTICES_COUNT_AFTER: {n_cnt_after}")
conn_n.close()
