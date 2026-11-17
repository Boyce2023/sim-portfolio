#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
backfill_cninfo_ir_qa_5y.py
================================================================================
五年巨潮「投资者关系活动记录表」机构调研问答正文全文回补引擎 (2021-01-04 至 2026-11-11)
================================================================================
核心规范与纪律：
1. 目标隔离：所有代码与产出数据库落盘于 backtests_astock2/data_5y/，绝不碰 sim-portfolio/data/ 写锁。
2. 零未来函数 PIT：严格保留发布秒级时间戳 (pub_datetime_cst)，结合交易日历计算 trade_date_avail。
3. 严格两批次调度：
   - 批次一（实战核心）：五年全部沪深主板首板股在 [D1-15天, D2 09:25:00] 窗口内的机构调研纪要 100% 优先落盘！
   - 批次二（全量回补）：自动无缝继续回补五年全市场剩余全部机构调研纪要！
4. 高性能与容错：
   - 巨潮查询 API 带平滑节流与 403 指数退避，防 CCDN 封控
   - 多线程并发下载静态附件 (static.cninfo.com.cn 不限流) + PyMuPDF (fitz) 高速内存解析
   - SQLite WAL 模式 + 事务批量提交
   - 断点续传 (checkpointing) + 异常自动重试
5. 零 yfinance、零造假，实测落盘数据与进度实时可查。
================================================================================
"""

import os
import sys
import re
import io
import time
import json
import bisect
import sqlite3
import calendar as cal_lib
import datetime
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

import urllib.request
import urllib.parse
import fitz  # PyMuPDF
try:
    import docx
except ImportError:
    docx = None
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

import pandas as pd
import pyarrow.dataset as ds

# 路径常量
BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2"
DATA_5Y_DIR = os.path.join(BASE_DIR, "data_5y")
TARGET_DB = os.path.join(DATA_5Y_DIR, "cninfo_ir_qa_5y_pit.db")
A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
SRC_NOTICES_DB = "file:/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cninfo_notices_5y_pit.db?mode=ro"

# 巨潮接口常量
CNINFO_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STATIC_URL = "http://static.cninfo.com.cn/"
SEARCH_KEY = "投资者关系活动记录表"

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
]


class TradingCalendar:
    """交易日历与可用交易日精确计算器 (严格无未来函数)"""
    def __init__(self, parquet_path: str):
        print(f"[Calendar] 正在从 {parquet_path} 加载完整交易日历...")
        ds_act = ds.dataset(parquet_path, format="parquet")
        dates_table = ds_act.scanner(columns=["date"]).to_table()
        df_dates = dates_table.to_pandas()
        self.trade_days = sorted(df_dates["date"].dt.strftime("%Y-%m-%d").unique())
        self.trade_days_set = set(self.trade_days)
        print(f"[Calendar] 交易日加载完毕，共 {len(self.trade_days)} 个交易日 ({self.trade_days[0]} ~ {self.trade_days[-1]})")

    def next_trade_day(self, date_str: str) -> str:
        idx = bisect.bisect_right(self.trade_days, date_str)
        if idx < len(self.trade_days):
            return self.trade_days[idx]
        return date_str

    def resolve_trade_date_avail(self, pub_datetime_cst: str) -> str:
        """
        根据秒级发布时间计算实际可用于回测/实盘的交易日:
        1. 盘前: < 09:25:00
           - 若当日为交易日，则当日可用 (09:25:00 开盘前)
           - 若当日为非交易日，顺延下一交易日
        2. 盘中: 09:25:00 ~ 14:59:59
           - 若当日为交易日，当日可用
           - 若非交易日，顺延下一交易日
        3. 盘后: >= 15:00:00 或周末节假日
           - 顺延下一交易日
        """
        pdate = pub_datetime_cst[:10]
        ptime = pub_datetime_cst[11:19] if len(pub_datetime_cst) >= 19 else "00:00:00"

        if ptime < "09:25:00":
            if pdate in self.trade_days_set:
                return pdate
            return self.next_trade_day(pdate)
        elif ptime < "15:00:00":
            if pdate in self.trade_days_set:
                return pdate
            return self.next_trade_day(pdate)
        else:
            return self.next_trade_day(pdate)


def load_main_board_first_board_windows(parquet_path: str, calendar: TradingCalendar):
    """
    计算 2021-01-01 至 2026-11-11 全部沪深主板首板股窗口:
    定义: 主板股票 (00xxxx, 60xxxx), 当日涨停且前一日未涨停 (is_zt & ~prev_zt)
    首板窗口: [D1 - 15个交易日, D2 09:25:00] (其中 D2 为 D1 的次一交易日)
    返回: dict[sec_code -> list of (window_start_date, d2_date)]
    """
    t0 = time.time()
    print("[FirstBoard] 正在从行情库加载沪深主板首板记录...")
    cols = ["date", "ticker", "close"]
    ds_act = ds.dataset(parquet_path, format="parquet")
    df = ds_act.scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2020-11-01"))).to_table().to_pandas()
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["c6"].str.startswith(("00", "60")) & (~df["ticker"].str.endswith(".BJ"))].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(subset=["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    g = df.groupby("c6")
    df["pre_c"] = g["close"].shift(1)
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["zt_price"] = (df["pre_c"] * 1.10 * 100.0 + 0.5).floordiv(1) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_price"] - 0.01) & (df["pct"] >= 0.095) & (df["pre_c"] > 0)
    df["prev_zt"] = g["is_zt"].shift(1).fillna(False)
    df["is_first_board"] = df["is_zt"] & (~df["prev_zt"])

    # 过滤 2021-01-01 之后
    fb_df = df[df["is_first_board"] & (df["dt_str"] >= "2021-01-01")].copy()
    print(f"[FirstBoard] 沪深主板首板事件共 {len(fb_df)} 次，涉及股票 {fb_df['c6'].nunique()} 只 (耗时 {time.time()-t0:.2f}s)")

    date_to_idx = {d: i for i, d in enumerate(calendar.trade_days)}
    fb_windows = defaultdict(list)
    for _, row in fb_df.iterrows():
        code = row["c6"]
        d1 = row["dt_str"]
        idx = date_to_idx.get(d1)
        if idx is not None:
            d2 = calendar.trade_days[idx + 1] if idx + 1 < len(calendar.trade_days) else d1
            start_idx = max(0, idx - 15)
            d_start = calendar.trade_days[start_idx]
            fb_windows[code].append((d_start, d2))

    return fb_windows


def init_db(db_path: str):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ir_qa (
            announcement_id TEXT PRIMARY KEY,
            sec_code TEXT,
            sec_name TEXT,
            pub_datetime_cst TEXT,
            trade_date_avail TEXT,
            title TEXT,
            adjunct_url TEXT,
            full_text TEXT,
            text_len INTEGER DEFAULT 0,
            is_firstboard_window INTEGER DEFAULT 0,
            fetched_at TEXT,
            fetch_status TEXT DEFAULT 'PENDING'
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ir_code ON ir_qa(sec_code);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ir_avail ON ir_qa(trade_date_avail);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ir_fb ON ir_qa(is_firstboard_window);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ir_status ON ir_qa(fetch_status);")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta_sync_status (
            month_str TEXT PRIMARY KEY,
            total_count INTEGER,
            synced_at TEXT
        );
    """)
    conn.commit()
    conn.close()
    print(f"[DB] 数据库已初始化: {db_path} (WAL 模式启用)")


def query_cninfo_page(page: int, se_date: str, searchkey: str = SEARCH_KEY, max_retries: int = 5):
    """查询巨潮公告列表 (带 403 智能退避与速率平滑)"""
    params = {
        "pageNum": page,
        "pageSize": 30,
        "column": "",
        "tabName": "fulltext",
        "plate": "",
        "searchkey": searchkey,
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": se_date
    }
    data = urllib.parse.urlencode(params).encode("utf-8")
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                CNINFO_QUERY_URL,
                data=data,
                headers={
                    "User-Agent": USER_AGENTS[attempt % len(USER_AGENTS)],
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                    "Origin": "http://www.cninfo.com.cn",
                    "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search"
                }
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return res
        except urllib.error.HTTPError as he:
            if he.code == 403:
                # 遭遇 403 触发限流，休眠退避
                wait_sec = 5.0 * (attempt + 1)
                print(f"  [CCDN 403 避让] 正在休眠 {wait_sec:.0f}s 后自动重试 ({se_date} p{page})...")
                time.sleep(wait_sec)
            else:
                time.sleep(1.0 * (attempt + 1))
        except Exception as e:
            time.sleep(1.0 * (attempt + 1))
            if attempt == max_retries - 1:
                print(f"[Warn] 检索最终失败 {se_date} 第 {page} 页: {e}")
                return None
    return None


def sync_month_metadata(month_tuple, calendar: TradingCalendar, fb_windows: dict):
    """同步单月全量元数据"""
    m_key, s_str, e_str = month_tuple
    se_date = f"{s_str}~{e_str}"

    first_res = query_cninfo_page(1, se_date)
    if not first_res:
        return m_key, 0, []

    total_ann = first_res.get("totalAnnouncement", 0)
    total_pages = first_res.get("totalpages", 1)
    announcements = first_res.get("announcements") or []

    records = []
    def parse_item(a):
        aid = str(a.get("announcementId") or "").strip()
        code = str(a.get("secCode") or "").strip().zfill(6)
        name = str(a.get("secName") or "").strip()
        title = re.sub(r"<.*?>", "", str(a.get("announcementTitle") or "")).strip()
        aurl = str(a.get("adjunctUrl") or "").strip()
        ts_ms = a.get("announcementTime") or 0
        if not aid or not aurl:
            return None

        # 秒级时间戳转换
        dt_cst = datetime.datetime.fromtimestamp(
            ts_ms / 1000.0,
            datetime.timezone(datetime.timedelta(hours=8))
        ).strftime("%Y-%m-%d %H:%M:%S")

        # 交易可用日
        avail = calendar.resolve_trade_date_avail(dt_cst)

        # 首板窗口判定
        pdate = dt_cst[:10]
        ptime = dt_cst[11:19]
        is_fb = 0
        windows = fb_windows.get(code, [])
        for d_start, d2 in windows:
            if d_start <= pdate < d2 or (pdate == d2 and ptime <= "09:25:00"):
                is_fb = 1
                break

        return (aid, code, name, dt_cst, avail, title, aurl, is_fb)

    for a in announcements:
        it = parse_item(a)
        if it:
            records.append(it)

    for p in range(2, total_pages + 1):
        time.sleep(0.35)  # 保持 350ms 节流防 CCDN 封控
        res = query_cninfo_page(p, se_date)
        if res and res.get("announcements"):
            for a in res["announcements"]:
                it = parse_item(a)
                if it:
                    records.append(it)

    return m_key, total_ann, records


def sync_all_metadata(db_path: str, calendar: TradingCalendar, fb_windows: dict):
    """平滑同步 2021-01 至 2026-11 全部 71 个月的元数据"""
    print("=" * 70)
    print(">>> 阶段 1: 扫描同步五年 (2021-01 至 2026-11) 巨潮机构调研公告元数据清单...")
    print("=" * 70)

    # 生成月份清单 (从 2026 倒序向前同步，优先保证最新与首板)
    months = []
    cur = datetime.date(2021, 1, 1)
    end = datetime.date(2026, 11, 11)
    while cur <= end:
        yr = cur.year
        mo = cur.month
        _, last_day = cal_lib.monthrange(yr, mo)
        m_end = min(datetime.date(yr, mo, last_day), end)
        s_str = f"{yr:04d}-{mo:02d}-01"
        e_str = m_end.strftime("%Y-%m-%d")
        m_key = f"{yr:04d}-{mo:02d}"
        months.append((m_key, s_str, e_str))
        if mo == 12:
            cur = datetime.date(yr + 1, 1, 1)
        else:
            cur = datetime.date(yr, mo + 1, 1)

    # 倒序同步 (2026 -> 2025 -> 2024 ...)
    months.reverse()

    # 检查已成功同步月份 (total_count > 0)
    conn = sqlite3.connect(db_path, timeout=60.0)
    cursor = conn.cursor()
    cursor.execute("SELECT month_str FROM meta_sync_status WHERE total_count > 0")
    done_months = {row[0] for row in cursor.fetchall()}
    conn.close()

    pending_months = [m for m in months if m[0] not in done_months or m[0] == "2026-11"]
    print(f"[MetaSync] 全部月份: {len(months)} 个，待同步: {len(pending_months)} 个")

    if not pending_months:
        print("[MetaSync] 所有月份元数据均已同步完毕！")
        return

    total_new_records = 0
    # 采用串行单线程加微延迟平滑拉取元数据，彻底规避 CCDN 封锁
    for idx, m in enumerate(pending_months, 1):
        m_key = m[0]
        try:
            m_key, total_ann, records = sync_month_metadata(m, calendar, fb_windows)
            if records:
                conn = sqlite3.connect(db_path, timeout=60.0)
                conn.executemany("""
                    INSERT INTO ir_qa (announcement_id, sec_code, sec_name, pub_datetime_cst, trade_date_avail, title, adjunct_url, is_firstboard_window, fetch_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
                    ON CONFLICT(announcement_id) DO UPDATE SET
                        is_firstboard_window=excluded.is_firstboard_window,
                        trade_date_avail=excluded.trade_date_avail;
                """, records)
                conn.execute("""
                    INSERT OR REPLACE INTO meta_sync_status (month_str, total_count, synced_at)
                    VALUES (?, ?, ?);
                """, (m_key, total_ann, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                conn.commit()
                conn.close()
                total_new_records += len(records)
                fb_cnt = sum(1 for r in records if r[7] == 1)
                print(f"[{idx}/{len(pending_months)}] 月份 {m_key} 同步完成: 接口总数 {total_ann} 条，入库有效 {len(records)} 条 (首板窗口: {fb_cnt} 条)")
            else:
                print(f"[{idx}/{len(pending_months)}] 月份 {m_key} 接口返回 0 条")
            time.sleep(0.5)
        except Exception as e:
            print(f"[MetaSync Error] 月份 {m_key} 异常: {e}")

    print(f"[MetaSync] 元数据同步阶段结束，本轮累计新增/更新 {total_new_records} 条公告记录！")


def download_and_extract_text(adjunct_url: str, max_retries: int = 3) -> str:
    """下载附件并在内存中使用 PyMuPDF (fitz) / python-docx 高速提取纯文本"""
    full_url = f"{CNINFO_STATIC_URL}{adjunct_url}"
    content = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                full_url,
                headers={"User-Agent": USER_AGENTS[attempt % len(USER_AGENTS)]}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                content = resp.read()
                break
        except Exception:
            if attempt == max_retries - 1:
                return ""
            time.sleep(0.3 * (attempt + 1))

    if not content:
        return ""

    text = ""
    try:
        url_lower = adjunct_url.lower()
        if url_lower.endswith(".pdf") or content[:4] == b"%PDF":
            doc = fitz.open(stream=content, filetype="pdf")
            pages = [page.get_text() for page in doc]
            text = "\n".join(pages)
        elif url_lower.endswith(".docx") and docx is not None:
            doc = docx.Document(io.BytesIO(content))
            text = "\n".join([p.text for p in doc.paragraphs])
        elif url_lower.endswith((".html", ".htm")) and BeautifulSoup is not None:
            soup = BeautifulSoup(content, "html.parser")
            text = soup.get_text(separator="\n")
        else:
            try:
                text = content.decode("utf-8")
            except Exception:
                text = content.decode("gbk", errors="ignore")
    except Exception:
        return ""

    return text.strip()


def fetch_worker_task(item):
    """单个抓取任务"""
    aid, code, name, aurl, is_fb, title, pdt = item
    t0 = time.time()
    text = download_and_extract_text(aurl)
    elapsed = time.time() - t0
    status = "DONE" if len(text) > 20 else "EMPTY"
    return aid, text, len(text), status, elapsed, code, name, is_fb, title, pdt


def run_batch_fetch(db_path: str, max_workers: int = 8, limit: int = 0):
    """
    分批调度下载器:
    优先调度 is_firstboard_window=1 批次全部抓齐，
    再无缝继续抓取全市场剩余部分！
    """
    print("=" * 70)
    print(f">>> 阶段 2: 启动正文抓取引擎 (并发数: {max_workers})...")
    print("=" * 70)

    conn = sqlite3.connect(db_path, timeout=60.0)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM ir_qa")
    total_in_db = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM ir_qa WHERE fetch_status='DONE' AND text_len > 0")
    done_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM ir_qa WHERE is_firstboard_window=1")
    fb_total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM ir_qa WHERE is_firstboard_window=1 AND fetch_status='DONE' AND text_len > 0")
    fb_done = c.fetchone()[0]
    conn.close()

    print(f"[Status] 数据库总记录数: {total_in_db} | 已抓取正文: {done_count} | 待抓取: {total_in_db - done_count}")
    print(f"[Status] 首板窗口总记录: {fb_total} | 已抓取: {fb_done} | 首板窗口待抓取: {fb_total - fb_done}")

    # 查询待抓任务，严格排序：首板窗口优先 (is_firstboard_window DESC)，最新优先 (pub_datetime_cst DESC)
    conn = sqlite3.connect(db_path, timeout=60.0)
    c = conn.cursor()
    query = """
        SELECT announcement_id, sec_code, sec_name, adjunct_url, is_firstboard_window, title, pub_datetime_cst
        FROM ir_qa
        WHERE fetch_status != 'DONE' OR text_len = 0
        ORDER BY is_firstboard_window DESC, pub_datetime_cst DESC
    """
    if limit > 0:
        query += f" LIMIT {limit}"
    c.execute(query)
    tasks = c.fetchall()
    conn.close()

    if not tasks:
        print("[Fetch] 当前无待抓取任务！")
        return

    print(f"[Fetch] 本轮装载抓取任务: {len(tasks)} 条 (其中首板窗口优先任务: {sum(1 for t in tasks if t[4]==1)} 条)")

    t_batch_start = time.time()
    batch_records = []
    processed_count = 0
    success_count = 0
    total_chars = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_worker_task, t): t[0] for t in tasks}
        for future in as_completed(futures):
            aid, text, tlen, status, elap, code, name, is_fb, title, pdt = future.result()
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            batch_records.append((text, tlen, now_str, status, aid))
            processed_count += 1
            if status == "DONE":
                success_count += 1
                total_chars += tlen

            if is_fb:
                fb_tag = "[★首板窗口★]"
            else:
                fb_tag = "[全市场常规]"

            if processed_count <= 10 or processed_count % 50 == 0 or is_fb:
                print(f"  {fb_tag} [{code} {name}] {title[:22]} | 长度: {tlen}字 | 耗时: {elap*1000:.0f}ms | 进度: {processed_count}/{len(tasks)}")

            if len(batch_records) >= 50:
                conn = sqlite3.connect(db_path, timeout=60.0)
                conn.executemany("""
                    UPDATE ir_qa
                    SET full_text = ?, text_len = ?, fetched_at = ?, fetch_status = ?
                    WHERE announcement_id = ?;
                """, batch_records)
                conn.commit()
                conn.close()
                batch_records.clear()

        if batch_records:
            conn = sqlite3.connect(db_path, timeout=60.0)
            conn.executemany("""
                UPDATE ir_qa
                SET full_text = ?, text_len = ?, fetched_at = ?, fetch_status = ?
                WHERE announcement_id = ?;
            """, batch_records)
            conn.commit()
            conn.close()
            batch_records.clear()

    total_sec = time.time() - t_batch_start
    qps = processed_count / max(0.01, total_sec)
    print("=" * 70)
    print(f"[Summary] 本轮完成: {processed_count} 条 | 成功入库: {success_count} 条 | 累计文本: {total_chars:,} 字")
    print(f"[Summary] 耗时: {total_sec:.2f}秒 | 吞吐速度: {qps:.2f} 篇/秒 ({qps * 60:.1f} 篇/分)")
    print("=" * 70)


def print_stats(db_path: str):
    """打印数据库详实统计信息"""
    if not os.path.exists(db_path):
        print(f"[Error] 数据库文件不存在: {db_path}")
        return

    conn = sqlite3.connect(db_path, timeout=60.0)
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM ir_qa")
    total_cnt = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM ir_qa WHERE fetch_status='DONE' AND text_len > 0")
    done_cnt = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM ir_qa WHERE is_firstboard_window=1")
    fb_total = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM ir_qa WHERE is_firstboard_window=1 AND fetch_status='DONE' AND text_len > 0")
    fb_done = c.fetchone()[0]

    c.execute("SELECT MIN(pub_datetime_cst), MAX(pub_datetime_cst) FROM ir_qa")
    min_date, max_date = c.fetchone()

    c.execute("SELECT substr(pub_datetime_cst, 1, 4) as yr, COUNT(*), SUM(CASE WHEN fetch_status='DONE' THEN 1 ELSE 0 END) FROM ir_qa GROUP BY yr ORDER BY yr")
    year_stats = c.fetchall()

    c.execute("SELECT AVG(text_len), MAX(text_len) FROM ir_qa WHERE fetch_status='DONE' AND text_len > 0")
    avg_len, max_len = c.fetchone()
    conn.close()

    print("\n" + "=" * 70)
    print(f"五年巨潮机构调研问答全文库统计 (PIT SSOT): {db_path}")
    print("=" * 70)
    print(f"总收录公告数:         {total_cnt:,} 篇")
    print(f"已抓取落盘全文数:     {done_cnt:,} 篇 (完成度: {done_cnt/max(1, total_cnt)*100:.2f}%)")
    print(f"沪深主板首板窗口总数: {fb_total:,} 篇")
    print(f"首板窗口已落盘全文数: {fb_done:,} 篇 (首板完成度: {fb_done/max(1, fb_total)*100:.2f}%)")
    print(f"覆盖日期区间:         {min_date} 至 {max_date}")
    print(f"正文平均长度:         {avg_len or 0:.0f} 字 (最大单篇: {max_len or 0:,} 字)")
    print("-" * 70)
    print("按年度拆分统计:")
    for yr, tot, d in year_stats:
        print(f"  - {yr}年: 总计 {tot:5d} 篇 | 已抓取落盘 {d:5d} 篇 ({(d/tot*100):.1f}%)")
    print("=" * 70 + "\n")


def verify_samples(db_path: str, n: int = 5):
    """抽检落盘记录真实性与字段完整性"""
    conn = sqlite3.connect(db_path, timeout=60.0)
    c = conn.cursor()
    c.execute("""
        SELECT announcement_id, sec_code, sec_name, pub_datetime_cst, trade_date_avail, title, text_len, full_text, is_firstboard_window
        FROM ir_qa
        WHERE fetch_status='DONE' AND text_len > 100
        ORDER BY RANDOM()
        LIMIT ?
    """, (n,))
    samples = c.fetchall()
    conn.close()

    print(f"\n[Verify] 随机抽检 {len(samples)} 篇已落盘正文样本 (绝对真实核验):")
    for i, s in enumerate(samples, 1):
        aid, code, name, pdt, avail, title, tlen, text, is_fb = s
        print(f"\n--- 样本 {i} [代码: {code} {name}] {'★首板窗口★' if is_fb else '常规'} ---")
        print(f"公告 ID:       {aid}")
        print(f"公告标题:     {title}")
        print(f"发布时间 CST:  {pdt} (秒级 PIT)")
        print(f"交易可用日:   {avail}")
        print(f"正文总字数:   {tlen:,} 字")
        print(f"正文前 200 字摘要:\n{text[:200].strip()}\n...")


def main():
    parser = argparse.ArgumentParser(description="五年巨潮机构调研问答正文回补引擎")
    parser.add_argument("--sync-meta", action="store_true", help="同步巨潮 2021-2026 全量元数据清单")
    parser.add_argument("--fetch", action="store_true", help="执行全文附件下载与解析")
    parser.add_argument("--limit", type=int, default=0, help="限制本轮下载篇数 (0为不限制)")
    parser.add_argument("--workers", type=int, default=8, help="并发工作线程数 (默认8)")
    parser.add_argument("--stats", action="store_true", help="查看数据库当前落盘统计")
    parser.add_argument("--verify", type=int, default=0, help="抽检 N 条落盘样本")
    parser.add_argument("--daemon", action="store_true", help="以守护进程模式持续运行至全部完成")
    args = parser.parse_args()

    init_db(TARGET_DB)
    calendar = TradingCalendar(A_DAILY_PATH)
    fb_windows = load_main_board_first_board_windows(A_DAILY_PATH, calendar)

    if args.stats:
        print_stats(TARGET_DB)
        return

    if args.verify > 0:
        verify_samples(TARGET_DB, args.verify)
        return

    if args.sync_meta:
        sync_all_metadata(TARGET_DB, calendar, fb_windows)
        print_stats(TARGET_DB)

    if args.fetch:
        run_batch_fetch(TARGET_DB, max_workers=args.workers, limit=args.limit)
        print_stats(TARGET_DB)

    if args.daemon:
        # 守护进程模式：先保持后台同步元数据，同时并发下载已入库的待抓附件
        def meta_loop():
            sync_all_metadata(TARGET_DB, calendar, fb_windows)

        meta_thread = threading.Thread(target=meta_loop, daemon=True)
        meta_thread.start()

        while True:
            conn = sqlite3.connect(TARGET_DB)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM ir_qa WHERE fetch_status != 'DONE' OR text_len = 0")
            remain = c.fetchone()[0]
            conn.close()
            if remain > 0:
                print(f"\n[Daemon] 当前发现待抓取任务: {remain} 篇，启动并发拉取...")
                run_batch_fetch(TARGET_DB, max_workers=args.workers, limit=500)
            elif not meta_thread.is_alive():
                print("[Daemon] 元数据同步与正文抓取已全部完毕，守护进程圆满结束！")
                break
            else:
                print("[Daemon] 等待元数据同步新批次注入中...")
                time.sleep(3.0)


if __name__ == "__main__":
    main()
