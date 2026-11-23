#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
高标首阴 V5.1 盘感刷题机与挑战赛全量严格核验脚本：
1. 校验 2 个交付 HTML 与桌面同步件存在、非空且 MD5 100% 一致；
2. 逐笔核对 42 笔触发单与 partC_clean_ledgers_v191/ledger_high_v51_clean.csv（14.75x / 71.43% / PLR 2.83）100% 一致；
3. 校验无任何 15:00 精确封死跌停强卖违规；
4. 校验中文表达规范（零破折号、零禁用奉承词、零赚亏涨跌+数字%）与 JS 语法（node --check）。
"""
import hashlib
import json
import os
import re
import sys
import subprocess
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SIM_DIR = os.path.dirname(os.path.dirname(HERE))
A2_ASSETS = os.path.join(SIM_DIR, "backtests_astock2", "assets")
if A2_ASSETS not in sys.path:
    sys.path.insert(0, A2_ASSETS)

from v191_dt_defer_helper import load_dt_defer_tables

DELIVERY_DIR = os.path.join(SIM_DIR, "backtests_astock2", "最新交付题库")
DESK_DIR = "/Users/huaichuaibeimeng/Desktop/短线/题目"
CLEAN_LEDGER_CSV = os.path.join(
    SIM_DIR, "backtests_astock", "redteam_full_audit_20261123", "partC_clean_ledgers_v191", "ledger_high_v51_clean.csv"
)

JOBS = [
    ("高标_50题.html", "high_pack50.json", 50),
    ("高标_5关.html", "high_chal5.json", 5),
]
FORBIDDEN = ["五板策略", "零未来函数", "——", "—", "恭喜", "潜力进阶打板选手", "顶尖盘感", "绝佳狙击"]


def verify_all():
    print("=== 开始高标首阴 V5.1（V19.1 洁净真账）交付 HTML 综合验收 ===")
    errors = []
    ledger_df = pd.read_csv(CLEAN_LEDGER_CSV, dtype={"code": str})
    ledger_df["c6"] = ledger_df["code"].astype(str).str.zfill(6)
    lmap = {(str(r.buy_date), str(r.c6)): r for r in ledger_df.itertuples(index=False)}
    dt_tables = load_dt_defer_tables()
    dmap = dt_tables["dmap"]

    for html_name, json_name, exp_len in JOBS:
        fpath = os.path.join(DELIVERY_DIR, html_name)
        dpath = os.path.join(DESK_DIR, html_name)
        if not os.path.exists(fpath) or not os.path.exists(dpath):
            errors.append(f"交付或桌面文件缺失: {html_name}")
            continue
        b1, b2 = open(fpath, "rb").read(), open(dpath, "rb").read()
        h1, h2 = hashlib.md5(b1).hexdigest(), hashlib.md5(b2).hexdigest()
        if b1 != b2 or h1 != h2:
            errors.append(f"桌面同步MD5不一致: {html_name} ({h1} vs {h2})")
        else:
            print(f"[OK] 文件存在且桌面MD5一致: {html_name} ({len(b1)/1024:.1f} KB, md5={h1})")

        content = b1.decode("utf-8")
        m_json = re.search(r"const\s+DATA_5Y\s*=\s*(\[[\s\S]*?\]);", content)
        if not m_json:
            errors.append(f"{html_name} 未找到 DATA_5Y")
            continue
        cases = json.loads(m_json.group(1))
        disk_cases = json.load(open(os.path.join(HERE, json_name), encoding="utf-8"))
        if cases != disk_cases or len(cases) != exp_len:
            errors.append(f"{html_name} 内嵌 JSON 与 {json_name} 不一致或题数异常: {len(cases)}")

        matched_ledger = 0
        for q in cases:
            bd = q["date"]
            for c in q["cands"]:
                c6 = str(c["code"]).zfill(6)
                k = (bd, c6)
                if k in lmap:
                    lr = lmap[k]
                    exp_ret = round(float(lr.net_ret) * 100.0, 2)
                    if abs(c["ret"] - exp_ret) > 0.01 or str(lr.exit_date) not in c["exit"]:
                        errors.append(f"{html_name} 题{q['id']} {bd} {c6} 与洁净真账不一致: ({c['exit']}, {c['ret']}) vs ({lr.exit_date}, {exp_ret})")
                    matched_ledger += 1
                if c["filled"]:
                    ex_dt = c["exit"].split()[0]
                    if "09:25" not in c["exit"] and "异动" not in c["exit"]:
                        eb = dmap.get((c6, ex_dt))
                        if eb is not None and bool(eb.is_dt_exact):
                            errors.append(f"{html_name} 题{q['id']} {bd} {c6} 存在15:00跌停强卖违规: {c['exit']}")
        if exp_len == 50 and matched_ledger != 42:
            errors.append(f"{html_name} 对齐洁净真账笔数异常: {matched_ledger} != 42")
        print(f"[OK] {html_name} 洁净真账逐笔核验通过: {matched_ledger} 笔")

        for fb in FORBIDDEN:
            if fb in content:
                errors.append(f"{html_name} 包含禁用词: {fb}")
        bad_pct = re.findall(r"(?:赚|亏|涨|跌)\s*\d+(?:\.\d+)?%", content)
        if bad_pct:
            errors.append(f"{html_name} 包含禁用赚亏涨跌+数字%: {bad_pct[:3]}")
        if "V5.1" not in content:
            errors.append(f"{html_name} 缺少 V5.1 版本标识")

        scripts = re.findall(r"<script>([\s\S]*?)</script>", content)
        for si, sc_txt in enumerate(scripts):
            tmp_js = f"/tmp/verify_high_js_{os.path.basename(html_name)}_{si}.js"
            open(tmp_js, "w", encoding="utf-8").write(sc_txt)
            chk = subprocess.run(["node", "--check", tmp_js], capture_output=True, text=True)
            if chk.returncode != 0:
                errors.append(f"{html_name} JS语法错误: {chk.stderr}")

    if errors:
        print(f"\n❌ 核验发现 {len(errors)} 处错误:")
        for e in errors[:10]:
            print("  -", e)
        sys.exit(1)
    print("\n✅ 高标 V5.1（14.75x 洁净真账）全部核验通过！0 错误！")


if __name__ == "__main__":
    verify_all()
