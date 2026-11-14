#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
A股三进四盘感刷题机与挑战赛统一构建器（对齐 V3.4 定版）
生成4个单文件交付HTML至 最新交付题库/
"""
import os, sys, importlib

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)
ASSETS_DIR = os.path.join(CUR_DIR, "assets")
if ASSETS_DIR not in sys.path:
    sys.path.insert(0, ASSETS_DIR)

qb_m = importlib.import_module("assets.3to4_question_builder")
as_m = importlib.import_module("assets.3to4_trainer_assembler")

OUT_DIR = os.path.join(CUR_DIR, "最新交付题库")
os.makedirs(OUT_DIR, exist_ok=True)

def main():
    print("开始生成三进四 V3.4 题库数据集...")
    std_cases, chal_cases = qb_m.build_datasets()
    print(f"已构建标准卷 {len(std_cases)} 关，挑战赛 {len(chal_cases)} 关")

    # 1. 标准卷 50 关免密版
    p_std_un = os.path.join(OUT_DIR, "A股三进四盘感刷题机_V3.4第1套50题免密版.html")
    html_std_un = as_m.build_unlocked_html(std_cases, "A股三进四盘感刷题机 · V3.4 第1套50题（免密版）", "3to4_std50")
    with open(p_std_un, "w", encoding="utf-8") as f:
        f.write(html_std_un)
    print(f"已生成: {p_std_un} ({os.path.getsize(p_std_un)/1024:.1f} KB)")

    # 2. 标准卷 50 关口令版
    p_std_lock = os.path.join(OUT_DIR, "A股三进四盘感刷题机_V3.4第1套50题口令版.html")
    html_std_lock = as_m.build_locked_html(std_cases, "A股三进四盘感刷题机 · V3.4 第1套50题（内部口令版）", "3to4_std50")
    with open(p_std_lock, "w", encoding="utf-8") as f:
        f.write(html_std_lock)
    print(f"已生成: {p_std_lock} ({os.path.getsize(p_std_lock)/1024:.1f} KB)")

    # 3. 挑战赛 5 关免密版
    p_chal_un = os.path.join(OUT_DIR, "A股三进四盘感挑战赛_V3.4第1辑5关免密版.html")
    html_chal_un = as_m.build_unlocked_html(chal_cases, "A股三进四盘感挑战赛 · V3.4 第1辑5关（免密版）", "3to4_chal5")
    with open(p_chal_un, "w", encoding="utf-8") as f:
        f.write(html_chal_un)
    print(f"已生成: {p_chal_un} ({os.path.getsize(p_chal_un)/1024:.1f} KB)")

    # 4. 挑战赛 5 关口令版
    p_chal_lock = os.path.join(OUT_DIR, "A股三进四盘感挑战赛_V3.4第1辑5关口令版.html")
    html_chal_lock = as_m.build_locked_html(chal_cases, "A股三进四盘感挑战赛 · V3.4 第1辑5关（内部口令版）", "3to4_chal5")
    with open(p_chal_lock, "w", encoding="utf-8") as f:
        f.write(html_chal_lock)
    print(f"已生成: {p_chal_lock} ({os.path.getsize(p_chal_lock)/1024:.1f} KB)")

    print("\n三进四全部4个交付HTML生成完毕！")

if __name__ == "__main__":
    main()
