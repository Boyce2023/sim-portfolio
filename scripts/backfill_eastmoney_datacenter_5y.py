#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东方财富数据中心 5 年全量结构化公告高速入库引擎

数据源:
1. 东方财富数据中心 RPT_PUBLIC_OP_NEWPREDICT (业绩预告): 2021-01-01 ~ 2026-11-10 全量 (9.2万+条)
2. 历史核心公告合并: backtest/2026-08-24-daban/notices.db (90.6万条全量2025-2026公告)
3. 严格计算 trade_date_avail (零未来函数)
"""

import os
import sys
import math
import time
import json
import sqlite3
import datetime
import bisect
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

TARGET_DB = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cninfo_notices_5y_pit.db"
BT_NOTICES_DB = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/notices.db"
KLINE_DB = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kline_cache.db"

DC_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
    "Connection": "keep-alive",
}

def load_trading_days() -> list:
    days = set()
    if os.path.exists(KLINE_DB):
        try:
            c = sqlite3.connect(KLINE_DB)
            rows = c.execute("SELECT DISTINCT date FROM daily_kline WHERE date >= '2020-01-01'").fetchall()
            for r in rows:
                if r[0]:
                    days.add(str(r[0])[:10])
            c.close()
        except Exception:
            pass

    if not days:
        try:
            import akshare as ak
            df = ak.tool_trade_date_hist_sina()
            for d in df['trade_date']:
                s = str(d)[:10]
                if s >= '2020-01-01':
                    days.add(s)
        except Exception:
            pass

    if not days:
        cur = datetime.date(2020, 1, 1)
        end = datetime.date(2027, 1, 1)
        while cur <= end:
            if cur.weekday() < 5:
                days.add(cur.strftime("%Y-%m-%d"))
            cur += datetime.timedelta(days=1)

    return sorted(list(days))

class DateResolver:
    def __init__(self, trading_days: list):
        self.days = trading_days
        self.days_set = set(trading_days)
        self.cutoff_close = datetime.time(15, 0, 0)

    def resolve(self, dt_str: str) -> str:
        if not dt_str:
            return ""
        s = dt_str.strip()
        date_part = s[:10]
        time_part = s[11:19] if len(s) >= 19 else "00:00:00"

        # 如果只有日期或者时间为 00:00:00，代表官方披露日 T 日
        # 官方披露日 T 日若为交易日，早间即已知(或者早盘前挂牌)，可在 T 日竞价使用；
        # 若为非交易日（周末/节假日），顺延至下一交易日开盘
        if time_part == "00:00:00":
            if date_part in self.days_set:
                return date_part
            idx = bisect.bisect_right(self.days, date_part)
            return self.days[idx] if idx < len(self.days) else date_part

        try:
            t = datetime.time.fromisoformat(time_part)
        except Exception:
            t = datetime.time(0, 0, 0)

        if date_part in self.days_set:
            if t < self.cutoff_close:
                return date_part
            else:
                idx = bisect.bisect_right(self.days, date_part)
                return self.days[idx] if idx < len(self.days) else date_part
        else:
            idx = bisect.bisect_right(self.days, date_part)
            return self.days[idx] if idx < len(self.days) else date_part

def init_target_db(db_path: str):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notices (
            ann_id TEXT PRIMARY KEY,
            sec_code TEXT,
            sec_name TEXT,
            title TEXT,
            ann_type TEXT,
            pub_ts_ms INTEGER,
            pub_datetime_cst TEXT,
            trade_date_avail TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_avail ON notices(trade_date_avail);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sec_code ON notices(sec_code);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pub_ts ON notices(pub_ts_ms);")
    conn.commit()
    conn.close()

def fetch_page_pred(page: int, page_size: int = 500, retries: int = 3):
    params = {
        'reportName': 'RPT_PUBLIC_OP_NEWPREDICT',
        'columns': 'SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,NOTICE_DATE,REPORT_DATE,PREDICT_FINANCE,PREDICT_AMT_LOWER,PREDICT_AMT_UPPER,ADD_AMP_LOWER,ADD_AMP_UPPER,PREDICT_CONTENT,PREDICT_TYPE',
        'filter': "(NOTICE_DATE>='2021-01-01')(NOTICE_DATE<='2026-11-10')",
        'pageNumber': page,
        'pageSize': page_size,
        'sortTypes': '-1',
        'sortColumns': 'NOTICE_DATE',
        'source': 'WEB',
        'client': 'WEB',
    }
    for attempt in range(retries):
        try:
            r = requests.get(DC_URL, params=params, headers=HEADERS, timeout=12)
            if r.status_code == 200:
                js = r.json()
                res = js.get("result")
                if res:
                    return res.get("data", [])
            time.sleep(0.5)
        except Exception:
            time.sleep(1.0)
    return []

def backfill_predictions(resolver: DateResolver):
    print(">>> [1/3] 开始拉取东方财富数据中心 5 年全量业绩预告 (RPT_PUBLIC_OP_NEWPREDICT)...")
    # 先探测总数
    params = {
        'reportName': 'RPT_PUBLIC_OP_NEWPREDICT',
        'columns': 'SECURITY_CODE',
        'filter': "(NOTICE_DATE>='2021-01-01')(NOTICE_DATE<='2026-11-10')",
        'pageNumber': 1,
        'pageSize': 10,
        'sortTypes': '-1',
        'sortColumns': 'NOTICE_DATE',
        'source': 'WEB',
        'client': 'WEB',
    }
    r = requests.get(DC_URL, params=params, headers=HEADERS, timeout=10)
    data = r.json()
    total_count = data.get("result", {}).get("count", 92579)
    page_size = 500
    total_pages = math.ceil(total_count / float(page_size))
    print(f"  总记录数: {total_count}, 总页数: {total_pages} (pageSize={page_size})")

    records = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_page_pred, p, page_size): p for p in range(1, total_pages + 1)}
        done_cnt = 0
        for f in as_completed(futures):
            p = futures[f]
            done_cnt += 1
            items = f.result()
            if items:
                for it in items:
                    code = str(it.get("SECURITY_CODE") or "").zfill(6)
                    name = str(it.get("SECURITY_NAME_ABBR") or "")
                    ndt = str(it.get("NOTICE_DATE") or "")
                    rdt = str(it.get("REPORT_DATE") or "")[:10]
                    ptype = str(it.get("PREDICT_TYPE") or "业绩预告")
                    amp_l = it.get("ADD_AMP_LOWER")
                    amp_u = it.get("ADD_AMP_UPPER")
                    content = str(it.get("PREDICT_CONTENT") or "")

                    amp_desc = ""
                    if amp_l is not None and amp_u is not None:
                        amp_desc = f"{amp_l}%~{amp_u}%"
                    elif amp_l is not None:
                        amp_desc = f"{amp_l}%"
                    elif amp_u is not None:
                        amp_desc = f"{amp_u}%"

                    title = f"【业绩预告-{ptype}】{name} {rdt} 净利润变动 {amp_desc}" if amp_desc else f"【业绩预告-{ptype}】{name} {rdt}"
                    if content and len(title) < 50:
                        title += f": {content[:60]}"

                    avail_date = resolver.resolve(ndt)
                    try:
                        pub_dt = datetime.datetime.fromisoformat(ndt)
                        pub_ts = int(pub_dt.timestamp() * 1000)
                    except Exception:
                        pub_ts = 0

                    ann_id = f"em_pred_{code}_{ndt[:10]}_{rdt}_{hashlib.md5(title.encode()).hexdigest()[:8]}"
                    records.append((
                        ann_id,
                        code,
                        name,
                        title,
                        f"业绩预告:{ptype}",
                        pub_ts,
                        ndt,
                        avail_date
                    ))
            if done_cnt % 20 == 0 or done_cnt == total_pages:
                print(f"  [进度] 业绩预告已抓取 {done_cnt}/{total_pages} 页, 累计结构化记录 {len(records)} 条")

    # 写入数据库
    print(f"  正在写入 target db (共 {len(records)} 条业绩预告)...")
    conn = sqlite3.connect(TARGET_DB, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executemany("""
        INSERT OR REPLACE INTO notices (ann_id, sec_code, sec_name, title, ann_type, pub_ts_ms, pub_datetime_cst, trade_date_avail)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    conn.close()
    print("  >>> 业绩预告入库完成！")

def merge_from_backtest_db(resolver: DateResolver):
    if not os.path.exists(BT_NOTICES_DB):
        print(f"  [跳过] 未找到历史公告库: {BT_NOTICES_DB}")
        return
    print(f">>> [2/3] 从 {BT_NOTICES_DB} 合并历史 2025~2026 全量公告...")
    src_conn = sqlite3.connect(BT_NOTICES_DB)
    src_rows = src_conn.execute("SELECT code, name, title, ntype, ndate FROM notice").fetchall()
    src_conn.close()
    print(f"  源库总条数: {len(src_rows)}")

    records = []
    for r in src_rows:
        code, name, title, ntype, ndate = r
        code = str(code).zfill(6)
        name = str(name or "")
        title = str(title or "")
        ntype = str(ntype or "")
        ndate = str(ndate or "")[:10]
        if not ndate:
            continue
        dt_str = f"{ndate} 19:00:00"
        avail = resolver.resolve(dt_str)
        try:
            pub_ts = int(datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
        except Exception:
            pub_ts = 0
        h = hashlib.md5(f"{code}_{title}".encode()).hexdigest()[:10]
        ann_id = f"bt_{code}_{ndate}_{h}"
        records.append((
            ann_id,
            code,
            name,
            title,
            ntype,
            pub_ts,
            dt_str,
            avail
        ))

    print(f"  正在批量写入 target db (共 {len(records)} 条)...")
    conn = sqlite3.connect(TARGET_DB, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    batch_size = 50000
    for i in range(0, len(records), batch_size):
        chunk = records[i:i+batch_size]
        conn.executemany("""
            INSERT OR IGNORE INTO notices (ann_id, sec_code, sec_name, title, ann_type, pub_ts_ms, pub_datetime_cst, trade_date_avail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, chunk)
        conn.commit()
        print(f"    已写入 {min(i+batch_size, len(records))}/{len(records)} 条...")
    conn.close()
    print("  >>> 历史全量公告合并完成！")

def fetch_major_events_5y(resolver: DateResolver):
    print(">>> [3/3] 拉取东方财富数据中心 5 年股票回购/增减持/重大事项...")
    # 东财数据中心回购接口: RPTA_WEB_GETHGLIST
    report_names = [
        ('RPTA_WEB_GETHGLIST', '回购', 'repurchase'),
        ('RPT_SHAREHOLDER_INCREASE', '重要股东增持', 'increase'),
    ]
    all_recs = []
    for rep, desc, tag in report_names:
        try:
            p = 1
            psize = 500
            while True:
                params = {
                    'reportName': rep,
                    'columns': 'ALL',
                    'pageNumber': p,
                    'pageSize': psize,
                    'sortTypes': '-1',
                    'source': 'WEB',
                    'client': 'WEB',
                }
                r = requests.get(DC_URL, params=params, headers=HEADERS, timeout=12)
                if r.status_code != 200:
                    break
                js = r.json()
                res = js.get("result")
                if not res or not res.get("data"):
                    break
                data = res.get("data")
                for it in data:
                    code = str(it.get("SECURITY_CODE") or it.get("SECUCODE") or "").split(".")[0].zfill(6)
                    name = str(it.get("SECURITY_NAME_ABBR") or it.get("SECURITY_NAME") or "")
                    ndt = str(it.get("NOTICE_DATE") or it.get("ANN_DATE") or "")
                    if not ndt or ndt < '2021-01-01':
                        continue
                    if ndt > '2026-11-10':
                        continue
                    title = f"【{desc}】{name}: {str(it.get('REPURCHASE_PURPOSE') or it.get('CHANGE_REASON') or '')[:80]}"
                    avail = resolver.resolve(ndt)
                    h = hashlib.md5(f"{code}_{ndt}_{tag}".encode()).hexdigest()[:8]
                    ann_id = f"em_{tag}_{code}_{ndt[:10]}_{h}"
                    all_recs.append((
                        ann_id, code, name, title, desc, 0, ndt, avail
                    ))
                if p >= res.get("pages", 1) or p >= 30: # 适度拉取高密度核心记录
                    break
                p += 1
            print(f"  {desc} 拉取完成，累计 {len(all_recs)} 条")
        except Exception as e:
            print(f"  {desc} 拉取异常: {e}")

    if all_recs:
        conn = sqlite3.connect(TARGET_DB, timeout=60.0)
        conn.executemany("""
            INSERT OR IGNORE INTO notices (ann_id, sec_code, sec_name, title, ann_type, pub_ts_ms, pub_datetime_cst, trade_date_avail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, all_recs)
        conn.commit()
        conn.close()

def print_summary():
    conn = sqlite3.connect(TARGET_DB)
    total = conn.execute("SELECT count(*) FROM notices").fetchone()[0]
    print(f"\n==================== 数据库汇总统计 ====================")
    print(f"数据库路径: {TARGET_DB}")
    print(f"全量总记录数: {total}")
    rows = conn.execute("""
        SELECT substr(trade_date_avail, 1, 4) AS y, count(*) 
        FROM notices 
        WHERE y >= '2021' AND y <= '2026'
        GROUP BY y 
        ORDER BY y
    """).fetchall()
    print("各年份 trade_date_avail 统计:")
    for y, cnt in rows:
        print(f"  {y}年: {cnt} 条")

    type_rows = conn.execute("""
        SELECT ann_type, count(*) 
        FROM notices 
        GROUP BY ann_type 
        ORDER BY count(*) DESC 
        LIMIT 10
    """).fetchall()
    print("\n公告类型 Top 10:")
    for t, cnt in type_rows:
        print(f"  {t}: {cnt} 条")
    conn.close()

if __name__ == "__main__":
    t0 = time.time()
    init_target_db(TARGET_DB)
    t_days = load_trading_days()
    resolver = DateResolver(t_days)
    print(f"交易日加载完成: 共 {len(t_days)} 个交易日 ({t_days[0]} ~ {t_days[-1]})")

    backfill_predictions(resolver)
    merge_from_backtest_db(resolver)
    fetch_major_events_5y(resolver)
    print_summary()
    print(f"\n全部流程耗时: {time.time() - t0:.2f} 秒")
