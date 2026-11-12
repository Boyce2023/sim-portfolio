#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
首板 5 年真实 5 分钟 K 线与盘口历史落盘库
数据源:
  1. 微观盘口首封/炸板数据: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/zt_micro_tape_5y_pit.db (只读 mode=ro)
  2. 真实 5 分钟 K 线: Baostock (114.94.20.42:10030 直走物理网卡 en0 穿透 Clash 虚拟拦截)
目标库:
  /Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/data_5y/firstboard_5m_5y_pit.db
严禁日线插值拟合，100% 真实外部接口数据。
"""

import os
import sys
import time
import datetime as dt
import sqlite3
import argparse
import subprocess
import socket
import ctypes

# 1. 突破 Clash 虚拟网卡 utun4 劫持，将 socket 精确绑定至 en0
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("all_proxy", None)
os.environ.pop("ALL_PROXY", None)

_idx = ctypes.CDLL(None).if_nametoindex(b"en0")
_OrigSocket = socket.socket


class En0Socket(_OrigSocket):
    def __init__(self, family=-1, type=-1, proto=-1, fileno=None):
        super().__init__(family, type, proto, fileno)
        if family in (-1, socket.AF_INET):
            try:
                self.setsockopt(socket.IPPROTO_IP, 25, _idx)
            except Exception:
                pass


socket.socket = En0Socket
socket.setdefaulttimeout(15.0)

import baostock as bs
import baostock.common.contants as cons

cons.BAOSTOCK_SERVER_IP = "114.94.20.42"
cons.BAOSTOCK_SERVER_PORT = 10030

SRC_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/zt_micro_tape_5y_pit.db"
DST_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/data_5y"
DST_DB_PATH = os.path.join(DST_DIR, "firstboard_5m_5y_pit.db")
CALENDAR_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"


def get_bs_code(code: str) -> str:
    """转换6位A股代码至 Baostock 规范格式"""
    code = str(code).strip().zfill(6)
    if code.startswith(("6", "9")):
        return f"sh.{code}"
    elif code.startswith(("0", "3", "2")):
        return f"sz.{code}"
    elif code.startswith(("4", "8")):
        return f"bj.{code}"
    return f"sz.{code}"


def format_bar_time(time_str: str) -> str:
    """将 Baostock 20210104093500000 转换为 2021-01-04 09:35:00"""
    s = str(time_str).strip()
    if len(s) >= 14:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}:{s[12:14]}"
    return s


def load_trading_calendar():
    """读取交易日历构建 D1 -> D2 映射字典"""
    import pandas as pd

    df = pd.read_parquet(CALENDAR_PATH, columns=["date"])
    dates = sorted(df["date"].unique())
    dates_str = [str(d)[:10] for d in dates]
    date_set = set(dates_str)
    sorted_dates = sorted(list(date_set))
    next_day_map = {}
    for i in range(len(sorted_dates) - 1):
        next_day_map[sorted_dates[i]] = sorted_dates[i + 1]
    return next_day_map, sorted_dates


def init_dst_db():
    os.makedirs(DST_DIR, exist_ok=True)
    conn = sqlite3.connect(DST_DB_PATH, timeout=60.0)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("PRAGMA busy_timeout = 60000;")

    # 首板微观事件元数据表（从 zt_micro_tape_5y_pit.db 镜像）
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS firstboard_events (
        trade_date TEXT NOT NULL,
        sec_code TEXT NOT NULL,
        sec_name TEXT,
        first_seal_time TEXT,
        first_seal_ts INTEGER,
        seal_amount REAL,
        continuous_plate_tag TEXT,
        board_count INTEGER,
        open_board_count INTEGER,
        plate_name TEXT,
        reason_desc TEXT,
        d1_date TEXT NOT NULL,
        d2_date TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (trade_date, sec_code)
    );
    """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_fbe_date ON firstboard_events(trade_date);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_fbe_code ON firstboard_events(sec_code);"
    )

    # 真实 5 分钟 K 线历史明细表
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS firstboard_5m_kline (
        trade_date TEXT NOT NULL,
        sec_code TEXT NOT NULL,
        bar_time TEXT NOT NULL,
        day_type TEXT NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL,
        amount REAL NOT NULL,
        source TEXT DEFAULT 'baostock_5m',
        PRIMARY KEY (trade_date, sec_code, bar_time)
    );
    """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_fb5m_event ON firstboard_5m_kline(trade_date, sec_code);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_fb5m_time ON firstboard_5m_kline(bar_time);"
    )

    # 抓取断点续传进度表
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS fetch_progress (
        trade_date TEXT NOT NULL,
        sec_code TEXT NOT NULL,
        d1_bars INTEGER DEFAULT 0,
        d2_bars INTEGER DEFAULT 0,
        status TEXT NOT NULL,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (trade_date, sec_code)
    );
    """
    )
    conn.commit()
    conn.close()


def sync_events_from_src():
    """从源库只读同步首板事件到目标库"""
    print(
        f"[SYNC] 连接源库 {SRC_DB_PATH} (mode=ro) 提取首板事件...", flush=True
    )
    next_day_map, _ = load_trading_calendar()

    src_conn = sqlite3.connect(f"file:{SRC_DB_PATH}?mode=ro", uri=True)
    src_cur = src_conn.cursor()
    src_cur.execute(
        """
        SELECT trade_date, sec_code, sec_name, first_seal_time, first_seal_ts,
               seal_amount, continuous_plate_tag, board_count, open_board_count,
               plate_name, reason_desc
        FROM zt_micro_tape
        WHERE continuous_plate_tag = '首板' OR board_count = 1
        ORDER BY trade_date, sec_code
    """
    )
    rows = src_cur.fetchall()
    src_conn.close()
    print(f"[SYNC] 源库读取到首板候选记录: {len(rows)} 条", flush=True)

    dst_conn = sqlite3.connect(DST_DB_PATH, timeout=60.0)
    dst_cur = dst_conn.cursor()

    to_insert = []
    for r in rows:
        t_date = r[0]
        s_code = str(r[1]).strip().zfill(6)
        d1 = t_date
        d2 = next_day_map.get(t_date, None)
        to_insert.append(
            (
                t_date,
                s_code,
                r[2],
                r[3],
                r[4],
                r[5],
                r[6],
                r[7],
                r[8],
                r[9],
                r[10],
                d1,
                d2,
            )
        )

    dst_cur.executemany(
        """
        INSERT OR IGNORE INTO firstboard_events (
            trade_date, sec_code, sec_name, first_seal_time, first_seal_ts,
            seal_amount, continuous_plate_tag, board_count, open_board_count,
            plate_name, reason_desc, d1_date, d2_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        to_insert,
    )
    dst_conn.commit()

    dst_cur.execute("SELECT count(*) FROM firstboard_events")
    total_events = dst_cur.fetchone()[0]
    print(
        f"[SYNC] firstboard_events 目标库首板总记录数: {total_events} 条",
        flush=True,
    )
    dst_conn.close()
    return total_events


def run_worker(worker_id: int, num_workers: int):
    """单 Worker 抓取进程"""
    print(
        f"[WORKER {worker_id}/{num_workers}] 启动，登录 Baostock...", flush=True
    )
    lg = bs.login()
    if lg.error_code != "0":
        print(
            f"[WORKER {worker_id}] Baostock 登录失败: {lg.error_msg}",
            flush=True,
        )
        sys.exit(1)

    dst_conn = sqlite3.connect(DST_DB_PATH, timeout=60.0)
    dst_cur = dst_conn.cursor()
    dst_cur.execute("PRAGMA journal_mode = WAL;")
    dst_cur.execute("PRAGMA synchronous = NORMAL;")
    dst_cur.execute("PRAGMA busy_timeout = 60000;")

    # 获取本 Worker 需要抓取的待处理列表
    dst_cur.execute(
        """
        SELECT e.trade_date, e.sec_code, e.d1_date, e.d2_date
        FROM firstboard_events e
        LEFT JOIN fetch_progress p ON e.trade_date = p.trade_date AND e.sec_code = p.sec_code
        WHERE p.status IS NULL OR p.status = 'ERROR'
        ORDER BY e.trade_date ASC, e.sec_code ASC
    """
    )
    all_pending = dst_cur.fetchall()

    my_tasks = [
        item
        for item in all_pending
        if (abs(hash(item[1] + item[0])) % num_workers) == worker_id
    ]
    print(
        f"[WORKER {worker_id}] 待抓取任务: {len(my_tasks)} / {len(all_pending)}",
        flush=True,
    )

    processed_count = 0
    kline_count = 0
    t_start = time.time()
    batch_klines = []
    batch_progress = []

    for t_date, s_code, d1_date, d2_date in my_tasks:
        bs_code = get_bs_code(s_code)
        query_end = d2_date if d2_date else d1_date

        bars_d1 = 0
        bars_d2 = 0
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,time,code,open,high,low,close,volume,amount",
                start_date=d1_date,
                end_date=query_end,
                frequency="5",
                adjustflag="3",
            )
            if rs.error_code == "0":
                while rs.next():
                    row = rs.get_row_data()
                    r_date = row[0]
                    r_time = format_bar_time(row[1])
                    try:
                        o_val = float(row[3])
                        h_val = float(row[4])
                        l_val = float(row[5])
                        c_val = float(row[6])
                        v_val = float(row[7])
                        a_val = float(row[8])
                    except (ValueError, TypeError):
                        continue

                    if r_date == d1_date:
                        dtype = "D1"
                        bars_d1 += 1
                    else:
                        dtype = "D2"
                        bars_d2 += 1

                    batch_klines.append(
                        (
                            t_date,
                            s_code,
                            r_time,
                            dtype,
                            o_val,
                            h_val,
                            l_val,
                            c_val,
                            v_val,
                            a_val,
                            "baostock_5m",
                        )
                    )

                status = "DONE" if (bars_d1 > 0 or bars_d2 > 0) else "EMPTY"
            else:
                status = "ERROR"
        except Exception as e:
            print(
                f"[WORKER {worker_id}] 抓取异常 {bs_code} {d1_date}: {e}",
                flush=True,
            )
            status = "ERROR"
            # 遇到网络错误尝试重新登录
            try:
                bs.login()
            except Exception:
                pass

        batch_progress.append((t_date, s_code, bars_d1, bars_d2, status))
        processed_count += 1
        kline_count += bars_d1 + bars_d2

        # 每 20 个任务批量写入数据库
        if len(batch_progress) >= 20:
            if batch_klines:
                dst_cur.executemany(
                    """
                    INSERT OR REPLACE INTO firstboard_5m_kline (
                        trade_date, sec_code, bar_time, day_type,
                        open, high, low, close, volume, amount, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    batch_klines,
                )
            dst_cur.executemany(
                """
                INSERT OR REPLACE INTO fetch_progress (
                    trade_date, sec_code, d1_bars, d2_bars, status
                ) VALUES (?, ?, ?, ?, ?)
            """,
                batch_progress,
            )
            dst_conn.commit()
            batch_klines.clear()
            batch_progress.clear()

            elapsed = time.time() - t_start
            throughput = processed_count / elapsed if elapsed > 0 else 0
            kps = kline_count / elapsed if elapsed > 0 else 0
            print(
                f"[WORKER {worker_id}] 进度: {processed_count}/{len(my_tasks)} "
                f"({processed_count/len(my_tasks)*100:.1f}%), "
                f"已写入K线: {kline_count} 根, "
                f"速度: {throughput:.1f} 标的/s, {kps:.1f} 根/s",
                flush=True,
            )

    # 写入最后一批残留
    if batch_progress:
        if batch_klines:
            dst_cur.executemany(
                """
                INSERT OR REPLACE INTO firstboard_5m_kline (
                    trade_date, sec_code, bar_time, day_type,
                    open, high, low, close, volume, amount, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                batch_klines,
            )
        dst_cur.executemany(
            """
            INSERT OR REPLACE INTO fetch_progress (
                trade_date, sec_code, d1_bars, d2_bars, status
            ) VALUES (?, ?, ?, ?, ?)
        """,
            batch_progress,
        )
        dst_conn.commit()

    dst_conn.close()
    bs.logout()
    print(
        f"[WORKER {worker_id}] 全部任务完成! 共处理 {processed_count} 个首板事件, 写入 {kline_count} 根真实 5m K线。",
        flush=True,
    )


def start_daemon(num_workers: int):
    """启动主守护调度，启动并监控 N 个并发 Worker"""
    init_dst_db()
    sync_events_from_src()

    script_path = os.path.abspath(__file__)
    print(
        f"[DAEMON] 启动 {num_workers} 个后台并发 Worker 进程...", flush=True
    )
    processes = []
    log_dir = os.path.join(DST_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)

    for i in range(num_workers):
        log_file = open(os.path.join(log_dir, f"worker_{i}.log"), "w")
        cmd = [
            sys.executable,
            "-u",
            script_path,
            "--worker",
            str(i),
            "--num-workers",
            str(num_workers),
        ]
        p = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
        processes.append((p, log_file, i))
        print(
            f"   [DAEMON] Worker {i} 已启动 (PID={p.pid}) -> logs/worker_{i}.log",
            flush=True,
        )

    print(
        "[DAEMON] 所有 Worker 已就绪并在后台持续拉取 2021-2026 真实 5m K 线！",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sync", action="store_true", help="只从源库同步首板事件")
    parser.add_argument("--daemon", action="store_true", help="启动多进程后台调度")
    parser.add_argument("--worker", type=int, default=None, help="运行单个 Worker")
    parser.add_argument(
        "--num-workers", type=int, default=4, help="并发 Worker 数量 (默认 4)"
    )
    args = parser.parse_args()

    if args.sync:
        init_dst_db()
        sync_events_from_src()
    elif args.worker is not None:
        run_worker(args.worker, args.num_workers)
    elif args.daemon:
        start_daemon(args.num_workers)
    else:
        # 默认模式：初始化 -> 同步 -> 启动 4 进程
        start_daemon(args.num_workers)
