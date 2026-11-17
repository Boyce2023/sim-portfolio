#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
build_locked_trainer.py
================================================================================
一进二盘感刷题机【密码访问版（口令 0521）与公开自用版】统一构建器
严格落地：
1. 真加密防扒源码：不存明文 0521，用 SHA-256 哈希校验 + 流密码加密 Base64
2. 兼容本地 file:// 协议与微信离线环境：纯 JS 同步算法，不依赖 crypto.subtle
3. 白底高对比、零圆角风格极简锁屏卡，支持 sessionStorage 标签页免重复输密
4. 同步产出：
   - 1to2_trainer_5y_locked.html (五年 353 关密码版)
   - 1to2_trainer_q1_locked.html (8 关尝鲜密码版)
   - 1to2_trainer_5y_full.html (五年 353 关无密码版)
   - 1to2_trainer_q1.html (8 关尝鲜无密码版)
================================================================================
"""
import os
import sys

sys.path.append('/tmp')
from astock2_html_assembler import build_locked_html, build_unlocked_html

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2"
JSON_5Y = "/tmp/astock2_5y_hierarchical.json"
JSON_Q1 = "/tmp/astock2_q1_hierarchical.json"

LOCKED_5Y = os.path.join(OUT_DIR, "1to2_trainer_5y_locked.html")
LOCKED_Q1 = os.path.join(OUT_DIR, "1to2_trainer_q1_locked.html")
FULL_5Y = os.path.join(OUT_DIR, "1to2_trainer_5y_full.html")
FULL_Q1 = os.path.join(OUT_DIR, "1to2_trainer_q1.html")

print("Building all 4 editions of 1to2 Decision Trainer...")

# 1. 5 年全量密码版 (353 关)
build_locked_html(
    data_json_path=JSON_5Y,
    out_html_path=LOCKED_5Y,
    page_title="A股一进二盘感刷题机 · 五年实战密码版",
    password="052101"
)

# 2. 8 关尝鲜密码版
build_locked_html(
    data_json_path=JSON_Q1,
    out_html_path=LOCKED_Q1,
    page_title="A股一进二盘感刷题机 · 经典8关尝鲜密码版",
    password="052101"
)

# 3. 5 年全量自用无密版
build_unlocked_html(
    data_json_path=JSON_5Y,
    out_html_path=FULL_5Y,
    page_title="A股一进二盘感刷题机 · 五年全量版"
)

# 4. 8 关自用无密版
build_unlocked_html(
    data_json_path=JSON_Q1,
    out_html_path=FULL_Q1,
    page_title="A股一进二盘感刷题机 · 经典8关精选版"
)

print("All 4 editions built successfully!")
