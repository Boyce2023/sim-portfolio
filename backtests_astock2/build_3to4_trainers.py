#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
A股三进四盘感刷题机与挑战赛统一构建器（对齐 V19.1 洁净真账 ledger_3to4_v41_clean.csv：95笔 / 胜率 65.26% / 盈亏比 1.95 / 五年 616.18x）
生成2个单文件直开交付HTML至 最新交付题库/ 并同步桌面
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
DESK_DIR = "/Users/huaichuaibeimeng/Desktop/短线/题目"
os.makedirs(OUT_DIR, exist_ok=True)


def main():
    import shutil
    print("开始生成三进四 V4.1（V19.1 洁净真账校准版 616.18x）题库数据集...")
    std_cases, chal_cases = qb_m.build_datasets()
    print(f"已构建标准卷 {len(std_cases)} 关，挑战赛 {len(chal_cases)} 关")

    # 1. 标准卷 50 关
    p_std_un = os.path.join(OUT_DIR, "三进四_50题.html")
    html_std_un = as_m.build_unlocked_html(std_cases, "A股三进四盘感刷题机 · V4.1 第1套50题", "3to4_std50_v41")
    with open(p_std_un, "w", encoding="utf-8") as f:
        f.write(html_std_un)
    print(f"已生成: {p_std_un} ({os.path.getsize(p_std_un)/1024:.1f} KB)")

    # 2. 挑战赛 5 关
    p_chal_un = os.path.join(OUT_DIR, "三进四_5关.html")
    html_chal_un = as_m.build_unlocked_html(chal_cases, "A股三进四盘感挑战赛 · V4.1 第1辑5关", "3to4_chal5_v41")
    with open(p_chal_un, "w", encoding="utf-8") as f:
        f.write(html_chal_un)
    print(f"已生成: {p_chal_un} ({os.path.getsize(p_chal_un)/1024:.1f} KB)")

    try:
        os.makedirs(DESK_DIR, exist_ok=True)
        for p_u in (p_std_un, p_chal_un):
            shutil.copy2(p_u, os.path.join(DESK_DIR, os.path.basename(p_u)))
    except Exception as e:
        print(f"[WARN] Desktop sync skipped: {e}")

    print("\n三进四全部2个交付HTML生成完毕！")


if __name__ == "__main__":
    main()
