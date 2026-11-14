#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_3to4_today.py — 三进四主战策略 V3.4 实盘极速决策引擎（对标 fast_high_dragon_today.py 与 fast_1to2_today.py）
模式：
  1. --build-cache：盘后读取只读库构建下一交易日盘前静态特征缓存 (3to4_premarket_cache.json)；
  2. --premarket：早盘 09:15 前秒级读取盘前缓存，输出环境面板、静态预评分与突破触发价；
  3. 无参数默认盘中秒跑模式：09:25:03 秒读缓存并抓腾讯实时竞价行情，秒级输出一步到位整数总分与 09:26 突破买单指令；
  4. --date YYYY-MM-DD / --recent N：兼容历史回测表 cand_3to4_enriched54.parquet 历史查询。
"""
import os, sys, json, argparse, subprocess

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BTEST_DIR = f"{ROOT}/sim-portfolio/backtests_astock2"
CACHE_FILE = f"{ROOT}/sim-portfolio/data/3to4_premarket_cache.json"

if BTEST_DIR not in sys.path:
    sys.path.insert(0, BTEST_DIR)

from live_3to4_cache_builder import build_premarket_cache
from live_3to4_intraday import run_premarket, run_live_mode

def main():
    parser = argparse.ArgumentParser(description="三进四主战策略 V3.4 实盘极速决策引擎")
    parser.add_argument("--build-cache", action="store_true", help="构建/刷新盘前特征缓存")
    parser.add_argument("--premarket", action="store_true", help="输出早盘盘前推演面板")
    parser.add_argument("--mock-open", type=str, default="", help="模拟竞价开盘涨幅，如 '603396=0.055,002148=0.040'")
    parser.add_argument("--date", type=str, default="", help="历史回测查询指定日期 (YYYY-MM-DD)")
    parser.add_argument("--recent", type=int, default=0, help="历史回测查询最近 N 笔")
    args = parser.parse_args()

    if args.date or args.recent > 0:
        scorer = os.path.join(BTEST_DIR, "score_3to4_v31_card.py")
        cmd = [sys.executable, scorer] + sys.argv[1:]
        raise SystemExit(subprocess.call(cmd))

    if args.build_cache:
        build_premarket_cache(verbose=True)
        return

    if not os.path.exists(CACHE_FILE):
        print(f"[*] 盘前缓存不存在，自动触发构建...")
        build_premarket_cache(verbose=True)

    cache = json.load(open(CACHE_FILE, "r", encoding="utf-8"))

    if args.premarket:
        run_premarket(cache)
        return

    mock_map = {}
    if args.mock_open:
        for pair in args.mock_open.split(","):
            if "=" in pair:
                k, v = pair.split("=")
                mock_map[k.strip()] = float(v.strip())

    run_live_mode(cache, mock_open_map=mock_map)

if __name__ == "__main__":
    main()
