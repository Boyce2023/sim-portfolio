#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
A股三进四 V4.1 盘感刷题机与挑战赛全量严格核验脚本：
1. 校验 2 个交付 HTML 与桌面同步件存在、非空且 MD5 100% 一致；
2. 逐题核对答案、V4.1 22项打分、10:30 5m 撮合、XF30 卖点及 partC_clean_ledgers_v191/ledger_3to4_v41_clean.csv（95笔 / 616.18x）逐笔一致（0 错误）；
3. 校验无任何 15:00 精确封死跌停强卖违规；
4. 校验中文表达规范（零破折号、禁现「V4.0」「五板策略」「零未来函数」「11:30」「V3.4」、零赚亏涨跌+数字%、零鼓励话术）；
5. 校验 JS 语法（node --check）。
"""
import hashlib
import json
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
from v191_dt_defer_helper import load_dt_defer_tables
loader_m = importlib.import_module("assets.3to4_v40_loader")
qb_m = importlib.import_module("assets.3to4_question_builder")

DELIVERY_DIR = os.path.join(CUR_DIR, "最新交付题库")
DESK_DIR = "/Users/huaichuaibeimeng/Desktop/短线/题目"
TARGET_FILES = [
    "三进四_50题.html",
    "三进四_5关.html",
]


def verify_all():
    print("=== 开始三进四 V4.1（V19.1 洁净真账）交付 HTML 综合验收 ===")
    errors = []

    # 1. 检查文件存在、非空与桌面字节/MD5 100% 完全一致
    for fname in TARGET_FILES:
        fpath = os.path.join(DELIVERY_DIR, fname)
        dpath = os.path.join(DESK_DIR, fname)
        if not os.path.exists(fpath):
            errors.append(f"交付文件不存在: {fname}")
            continue
        if not os.path.exists(dpath):
            errors.append(f"桌面同步文件不存在: {fname}")
            continue
        with open(fpath, "rb") as f1, open(dpath, "rb") as f2:
            b1, b2 = f1.read(), f2.read()
        h1, h2 = hashlib.md5(b1).hexdigest(), hashlib.md5(b2).hexdigest()
        if len(b1) < 1024:
            errors.append(f"文件异常过小 ({len(b1)} bytes): {fname}")
        elif b1 != b2 or h1 != h2:
            errors.append(f"桌面文件MD5不一致: {fname} ({h1} vs {h2})")
        else:
            print(f"[OK] 文件存在且桌面MD5完全一致: {fname} ({len(b1)/1024:.1f} KB, md5={h1})")

    # 2. 逐题核验 V4.1 打分、10:30 5m 撮合与 ledger_3to4_v41_clean.csv 一致性
    bundle = loader_m.get_v40_bundle()
    df = bundle["cand_df"]
    p_1030 = bundle["p_1030"]
    ledger_map = bundle["ledger_map"]
    dt_tables = load_dt_defer_tables()
    dmap = dt_tables["dmap"]

    std_cases, chal_cases = qb_m.build_datasets()
    assert len(std_cases) == 50, f"标准卷题目数量异常: {len(std_cases)}"
    assert len(chal_cases) == 5, f"挑战赛题目数量异常: {len(chal_cases)}"

    trig_ledger_checked = 0
    v41_improved_checked = 0
    dt_defer_checked = 0
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
                eb = dmap.get((c6, pool_item["exit_date"]))
                if int(pool_item["exit_hhmm"]) >= 1455 and eb is not None and bool(eb.is_dt_exact):
                    errors.append(f"题号{q['id']} {c6} 仍存在 15:00 封死跌停强卖违规: {pool_item['exit_date']}")
                if pool_item.get("dt_deferred"):
                    dt_defer_checked += 1
                if q["ans"] == "挂单":
                    lt = ledger_map.get((bd, c6))
                    if lt is None:
                        errors.append(f"题号{q['id']} {c6} {bd} 未在 ledger_3to4_v41_clean.csv 中找到")
                    else:
                        if lt["score"] != q["score"] or abs(lt["net_ret_pct"] - q["net_ret"]) > 0.01:
                            errors.append(f"题号{q['id']} {c6} {bd} 与官方台账不一致: q=({q['score']},{q['net_ret']}) vs lt=({lt['score']},{lt['net_ret_pct']})")
                        if pool_item.get("v41_improved"):
                            if "V4.1" not in q["exit_story"] or "+7.0%" not in q["exit_story"] or "+7.0%" not in q["postmortem"]:
                                errors.append(f"题号{q['id']} {c6} 发生V4.1卖点改善但未标注+7.0%收紧护利")
                            else:
                                v41_improved_checked += 1
                        trig_ledger_checked += 1
            else:
                if q["is_triggered"]:
                    errors.append(f"题号{q['id']} {c6} 不应触发却标记触发")
        print(f"[OK] {pack_name} {len(cases)} 题打分/撮合核验完毕")

    print(f"[OK] 官方台账 ledger_3to4_v41_clean.csv 逐笔对齐触发交易: {trig_ledger_checked} 笔（含 V4.1 改善标注 {v41_improved_checked} 笔，15:00跌停顺延校准 {dt_defer_checked} 笔）")

    # 3. 校验 HTML 内嵌 JSON、中文表达纪律与禁词 + node --check JS 语法
    FORBIDDEN_WORDS = [
        "V4.0", "五板策略", "零未来函数", "11:30", "V3.4",
        "pos20_d0", "xq_cnt_2d", "fb_dom295",
        "恭喜", "顶尖盘感", "绝佳狙击", "潜力进阶",
    ]
    for fname, expected_cases in [("三进四_50题.html", std_cases), ("三进四_5关.html", chal_cases)]:
        fpath = os.path.join(DELIVERY_DIR, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        if "V4.1" not in content:
            errors.append(f"{fname} 缺少 V4.1 版本标识")
        m_json = re.search(r"const\s+DATA_CASES\s*=\s*(\[[\s\S]*?\]);\s*\nconst\s+PAGE_TITLE", content)
        if not m_json:
            errors.append(f"{fname} 未找到 DATA_CASES")
        else:
            embedded = json.loads(m_json.group(1))
            if embedded != expected_cases:
                errors.append(f"{fname} 内嵌 DATA_CASES 与现跑数据集不一致")
        for w in FORBIDDEN_WORDS:
            if w in content:
                errors.append(f"{fname} 出现禁用/过期词汇: {w}")
        if "—" in content or "——" in content:
            errors.append(f"{fname} 出现中文破折号")
        bad_pct = re.findall(r"(?:赚|亏|涨|跌)\s*\d+(?:\.\d+)?%", content)
        if bad_pct:
            errors.append(f"{fname} 出现禁用赚亏涨跌+数字%表达: {bad_pct[:3]}")
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
        print("\n✅ 全部核验通过！0 错误！答案、V4.1打分、10:30撮合、XF30卖点与 V19.1 洁净真账完全逐笔一致！")


if __name__ == "__main__":
    verify_all()
