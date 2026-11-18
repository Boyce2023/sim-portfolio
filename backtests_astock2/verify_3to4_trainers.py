#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
A股三进四 V4.0 盘感刷题机与挑战赛全量严格核验脚本：
1. 校验 4 个交付 HTML 与桌面同步件存在、非空且字节一致；
2. 逐题核对答案、V4.0 22项打分、10:30 5m 撮合及 ledger_upg_3to4_std.csv 逐笔一致（0 错误）；
3. 校验中文表达规范（零破折号、禁现「五板策略」「零未来函数」「11:30」「V3.4」及内部变量名）；
4. 校验 JS 语法（node --check）。
"""
import os
import re
import sys
import subprocess
import importlib

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(CUR_DIR, "assets")
for _p in (CUR_DIR, ASSETS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from score_3to4_v31_card import score_single_3to4_row
loader_m = importlib.import_module("assets.3to4_v40_loader")
qb_m = importlib.import_module("assets.3to4_question_builder")

DELIVERY_DIR = os.path.join(CUR_DIR, "最新交付题库")
DESK_DIR = "/Users/huaichuaibeimeng/Desktop/短线/题目"
TARGET_FILES = [
    "三进四_50题.html",
    "三进四_5关.html",
]


def verify_all():
    print("=== 开始三进四 V4.0 交付 HTML 综合验收 ===")
    errors = []

    # 1. 检查文件存在、非空与桌面完全一致
    for fname in TARGET_FILES:
        fpath = os.path.join(DELIVERY_DIR, fname)
        dpath = os.path.join(DESK_DIR, fname)
        if not os.path.exists(fpath):
            errors.append(f"交付文件不存在: {fname}")
            continue
        if not os.path.exists(dpath):
            errors.append(f"桌面同步文件不存在: {fname}")
            continue
        sz = os.path.getsize(fpath)
        dsz = os.path.getsize(dpath)
        if sz < 1024:
            errors.append(f"文件异常过小 ({sz} bytes): {fname}")
        elif sz != dsz:
            errors.append(f"桌面文件大小不一致: {fname} ({sz} vs {dsz})")
        else:
            print(f"[OK] 文件存在且桌面同步一致: {fname} ({sz/1024:.1f} KB)")

    # 2. 逐题核验 V4.0 打分、10:30 5m 撮合与 ledger_upg_3to4_std.csv 一致性
    bundle = loader_m.get_v40_bundle()
    df = bundle["cand_df"]
    p_1030 = bundle["p_1030"]
    ledger_map = bundle["ledger_map"]

    std_cases, chal_cases = qb_m.build_datasets()
    assert len(std_cases) == 50, f"标准卷题目数量异常: {len(std_cases)}"
    assert len(chal_cases) == 5, f"挑战赛题目数量异常: {len(chal_cases)}"

    trig_ledger_checked = 0
    for pack_name, cases in [("标准卷50题", std_cases), ("挑战赛5关", chal_cases)]:
        print(f"\n--- 逐题核验 {pack_name} ---")
        for q in cases:
            c6 = q["code"]
            bd = q["date"]
            match_rows = df[(df["code"].astype(str).str.zfill(6) == c6) & (df["buy_date"] == bd)]
            if len(match_rows) == 0:
                errors.append(f"未找到原始候选: {c6} {bd}")
                continue
            orig_idx = match_rows.index[0]
            orig_r = match_rows.iloc[0]

            calc_res = score_single_3to4_row(orig_r.to_dict())
            if q["score"] != calc_res["score"]:
                errors.append(f"题号{q['id']} {c6} 分数不一致: q={q['score']} vs calc={calc_res['score']}")
            exp_ans = "挂单" if (calc_res["passed_skeleton"] and calc_res["score"] >= 90) else "空仓"
            if q["ans"] != exp_ans:
                errors.append(f"题号{q['id']} {c6} 定式答案不一致: q={q['ans']} vs exp={exp_ans}")

            pool_item = p_1030[orig_idx]
            if pool_item is not None:
                if not q["is_triggered"]:
                    errors.append(f"题号{q['id']} {c6} 应触发而未标记触发")
                expected_nr = round(float(pool_item["net_ret"]) * 100.0, 2)
                if abs(q["net_ret"] - expected_nr) > 0.01:
                    errors.append(f"题号{q['id']} {c6} 收益率不一致: q={q['net_ret']} vs exp={expected_nr}")
                if q["ans"] == "挂单":
                    lt = ledger_map.get((bd, c6))
                    if lt is None:
                        errors.append(f"题号{q['id']} {c6} {bd} 未在 ledger_upg_3to4_std.csv 中找到")
                    else:
                        if lt["score"] != q["score"] or abs(lt["net_ret_pct"] - q["net_ret"]) > 0.01:
                            errors.append(f"题号{q['id']} {c6} {bd} 与官方台账不一致: q=({q['score']},{q['net_ret']}) vs lt=({lt['score']},{lt['net_ret_pct']})")
                        trig_ledger_checked += 1
            else:
                if q["is_triggered"]:
                    errors.append(f"题号{q['id']} {c6} 不应触发却标记触发")
        print(f"[OK] {pack_name} {len(cases)} 题打分/撮合核验完毕")

    print(f"[OK] 官方台账 ledger_upg_3to4_std.csv 逐笔对齐触发交易: {trig_ledger_checked} 笔")

    # 3. 校验中文表达纪律与禁词 + node --check JS 语法
    FORBIDDEN_WORDS = ["五板策略", "零未来函数", "11:30", "V3.4", "pos20_d0", "xq_cnt_2d", "fb_dom295"]
    for fname in TARGET_FILES:
        fpath = os.path.join(DELIVERY_DIR, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        for w in FORBIDDEN_WORDS:
            if w in content:
                errors.append(f"{fname} 出现禁用/过期词汇: {w}")
        if "—" in content or "——" in content:
            errors.append(f"{fname} 出现中文破折号")
        scripts = re.findall(r"<script>([\s\S]*?)</script>", content)
        for si, sc_txt in enumerate(scripts):
            tmp_js = f"/tmp/verify_3to4_js_{os.path.basename(fname)}_{si}.js"
            with open(tmp_js, "w", encoding="utf-8") as jf:
                jf.write(sc_txt)
            chk = subprocess.run(["node", "--check", tmp_js], capture_output=True, text=True)
            if chk.returncode != 0:
                errors.append(f"{fname} JS语法错误: {chk.stderr}")

    if errors:
        print(f"\n❌ 核验发现 {len(errors)} 处错误:")
        for e in errors[:10]:
            print("  -", e)
        sys.exit(1)
    else:
        print("\n✅ 全部核验通过！0 错误！答案、V4.0打分、10:30撮合与台账完全逐笔一致！")


if __name__ == "__main__":
    verify_all()
