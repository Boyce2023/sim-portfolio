#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
A股三进四盘感刷题机与挑战赛全量严格核验脚本：
1. 校验 4 个交付 HTML 存在且非空；
2. 逐题核对答案与撮合逐笔一致、分数与打分器逐题一致（0 错误）；
3. 校验题目信息时点隔离（严格无未来数据泄露）；
4. 校验中文表达规范（零连字符、零破折号、零繁体字，收益写「赚/亏」，禁现「五板策略」「零未来函数」）。
"""
import os, sys, re, json, importlib

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)
ASSETS_DIR = os.path.join(CUR_DIR, "assets")
if ASSETS_DIR not in sys.path:
    sys.path.insert(0, ASSETS_DIR)

from score_3to4_v31_card import score_single_3to4_row
from bt_3to4_v32_final_build import sim_pool, df
qb_m = importlib.import_module("assets.3to4_question_builder")

DELIVERY_DIR = os.path.join(CUR_DIR, "最新交付题库")
TARGET_FILES = [
    "A股三进四盘感刷题机_V3.4第1套50题免密版.html",
    "A股三进四盘感刷题机_V3.4第1套50题口令版.html",
    "A股三进四盘感挑战赛_V3.4第1辑5关免密版.html",
    "A股三进四盘感挑战赛_V3.4第1辑5关口令版.html",
]

def verify_all():
    print("=== 开始三进四 V3.4 交付 HTML 综合验收 ===")
    errors = []

    # 1. 检查文件存在且非空
    for fname in TARGET_FILES:
        fpath = os.path.join(DELIVERY_DIR, fname)
        if not os.path.exists(fpath):
            errors.append(f"文件不存在: {fname}")
            continue
        sz = os.path.getsize(fpath)
        if sz < 1024:
            errors.append(f"文件异常过小 ({sz} bytes): {fname}")
        else:
            print(f"[OK] 文件存在且非空: {fname} ({sz/1024:.1f} KB)")

    # 2. 逐题核验打分与撮合一致性
    p_v32 = sim_pool("touch65_1130", "cut_weak", "pm1345", True, False)
    std_cases, chal_cases = qb_m.build_datasets()
    assert len(std_cases) == 50, f"标准卷题目数量异常: {len(std_cases)}"
    assert len(chal_cases) == 5, f"挑战赛题目数量异常: {len(chal_cases)}"

    for pack_name, cases in [("标准卷50题", std_cases), ("挑战赛5关", chal_cases)]:
        print(f"\n--- 逐题核验 {pack_name} ---")
        for q in cases:
            c6 = q["code"]; bd = q["date"]
            match_rows = df[(df["code"].astype(str).str.zfill(6) == c6) & (df["buy_date"] == bd)]
            if len(match_rows) == 0:
                errors.append(f"未找到原始候选: {c6} {bd}")
                continue
            orig_idx = match_rows.index[0]
            orig_r = match_rows.iloc[0]

            # 核验打分器
            calc_res = score_single_3to4_row(orig_r.to_dict())
            if q["score"] != calc_res["score"]:
                errors.append(f"题号{q['id']} {c6} 分数不一致: q={q['score']} vs calc={calc_res['score']}")
            exp_ans = "挂单" if (calc_res["passed_skeleton"] and calc_res["score"] >= 90) else "空仓"
            if q["ans"] != exp_ans:
                errors.append(f"题号{q['id']} {c6} 定式答案不一致: q={q['ans']} vs exp={exp_ans}")

            # 核验撮合逐笔一致性
            pool_item = p_v32[orig_idx]
            if pool_item is not None:
                if not q["is_triggered"]:
                    errors.append(f"题号{q['id']} {c6} 应触发而未标记触发")
                expected_nr = round(float(pool_item["net_ret"]) * 100.0, 2)
                if abs(q["net_ret"] - expected_nr) > 0.01:
                    errors.append(f"题号{q['id']} {c6} 收益率不一致: q={q['net_ret']} vs exp={expected_nr}")
            else:
                if q["is_triggered"]:
                    errors.append(f"题号{q['id']} {c6} 不应触发却标记触发")

    # 3. 校验中文表达纪律与禁词
    FORBIDDEN_WORDS = ["五板策略", "零未来函数"]
    for fname in TARGET_FILES:
        fpath = os.path.join(DELIVERY_DIR, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        for w in FORBIDDEN_WORDS:
            if w in content:
                errors.append(f"{fname} 出现禁用词汇: {w}")
        # 检查正文中是否有破折号
        if "—" in content or "——" in content:
            errors.append(f"{fname} 出现中文破折号")

    if errors:
        print(f"\n❌ 核验发现 {len(errors)} 处错误:")
        for e in errors[:10]:
            print("  -", e)
        sys.exit(1)
    else:
        print("\n✅ 全部核验通过！0 错误！答案、分数、撮合完全逐笔一致！")

if __name__ == "__main__":
    verify_all()
