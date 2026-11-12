#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
build_1to2_trainer_5y.py
================================================================================
一进二盘感刷题机【2021-2026 五年全量实战题库版】最终定版生成器
100% 落实全部硬规则：
1. 彻底清除作答前的后视镜剧透文案（列名：09:26 预埋点火价（条件单），只显示纯数学价格涨幅）
2. 选项 A / B / C / D 彻底随机打乱（Fisher-Yates 洗牌）
3. 3题材 x 2~4候选首板股两级树状真联动 + 题材卡标注【题材热度排名与 Elo 分数】
4. 候选股新增【系统综合排名】（全场第 1、第 2...），顶部支持一键隐藏/开启参考
5. 真实买卖点全真模拟：点火价买入、一字排单未成交、次日竞价止损、连板断板止盈分批落袋净收益
6. 客观无偏抽样，以市场真实走出来的真金白银收益为唯一裁判，并加设人机 PK 判词！
================================================================================
"""
import os
import sys

sys.path.append('/tmp')
from astock2_html_assembler import build_unlocked_html

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2"
JSON_5Y = "/tmp/astock2_5y_hierarchical.json"
JSON_Q1 = "/tmp/astock2_q1_hierarchical.json"

FULL_5Y = os.path.join(OUT_DIR, "1to2_trainer_5y_full.html")
FULL_Q1 = os.path.join(OUT_DIR, "1to2_trainer_q1.html")

print("Generating 1to2_trainer_5y_full.html and 1to2_trainer_q1.html...")

build_unlocked_html(
    data_json_path=JSON_5Y,
    out_html_path=FULL_5Y,
    page_title="A股一进二盘感刷题机 · 五年全量版"
)

build_unlocked_html(
    data_json_path=JSON_Q1,
    out_html_path=FULL_Q1,
    page_title="A股一进二盘感刷题机 · 经典8关精选版"
)

print("Build complete!")
