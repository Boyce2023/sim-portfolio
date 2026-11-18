#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_3to4_today.py — 三进四主战策略 V4.0 (互学瘦身正式版) 实盘极速决策引擎
五年零穿越验证基准 (ledger_upg_3to4_std.csv / summary_upg_3to4.json):
  标准 >=90分: 95笔 / 胜率 68.42% / 单仓 1799.99x / Cap10M_1M 75.49x / 等权 4458.94x / 回撤 31.25% / DSR 0.9818
模式:
  1. --build-cache : 读取只读 PIT 库 + astock_community.json 增量构建 data/3to4_premarket_cache.json
  2. --premarket   : 早盘 09:15 前秒读盘前缓存，输出 V4.0 22项预评分、U01/U02 明细与 10:30 撤单触发价
  3. 无参默认实时  : 09:25:03 秒读缓存并发抓腾讯实时竞价，输出 V4.0 整数总分与 09:26 突破条件单指令 (10:30 撤单)
  4. --mock-open   : 模拟竞价开盘涨幅，如 '603396=0.055,002148=0.040'
  5. --date / --recent N : 查询 V4.0 历史台账 ledger_upg_3to4_std.csv 与 V4.0 评分明细
严禁 import yfinance (D12); SQLite 全程 file:...?mode=ro 只读; 严禁触碰 portfolio_state.json。
"""
import argparse
import json
import os
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from live_3to4_v40_engine import (
    CACHE_FILE,
    build_premarket_cache,
    query_history,
    run_live_mode,
    run_premarket,
)


def main():
    parser = argparse.ArgumentParser(description="三进四主战策略 V4.0 实盘极速决策引擎")
    parser.add_argument("--build-cache", action="store_true", help="构建/刷新 V4.0 盘前特征缓存")
    parser.add_argument("--premarket", action="store_true", help="输出早盘盘前 V4.0 推演面板")
    parser.add_argument("--mock-open", type=str, default="", help="模拟竞价开盘涨幅，如 '603396=0.055,002148=0.040'")
    parser.add_argument("--date", type=str, default="", help="查询 V4.0 历史台账指定买日 (YYYY-MM-DD)")
    parser.add_argument("--recent", type=int, default=0, help="查询 V4.0 历史台账最近 N 笔")
    args = parser.parse_args()

    if args.date or args.recent > 0:
        query_history(date_str=args.date, recent_n=args.recent)
        return

    if args.build_cache:
        build_premarket_cache(verbose=True)
        return

    if not os.path.exists(CACHE_FILE):
        print("[*] 盘前缓存不存在，自动触发 V4.0 构建...")
        build_premarket_cache(verbose=True)

    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        cache = json.load(f)

    if args.premarket:
        run_premarket(cache)
        return

    mock_map = {}
    if args.mock_open:
        for pair in args.mock_open.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                mock_map[k.strip()] = float(v.strip())

    run_live_mode(cache, mock_open_map=mock_map)


if __name__ == "__main__":
    main()
