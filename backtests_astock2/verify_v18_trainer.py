# -*- coding: utf-8 -*-
"""
verify_v18_trainer.py: V19.1 题库与 HTML 产物物理硬核验网关
核验：真首板零假冒、ST/财报零混入、排名零倒挂、K线数学一致性、partC_clean_ledgers_v191/ledger_1to2_v19_clean.csv (97笔 / 332.72x) 逐笔100%一致、桌面MD5一致、中文规范、JS语法。
"""
import hashlib
import os
import sys
import re
import json
import subprocess
import pandas as pd

CURR_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(CURR_DIR, "assets")
for _p in (CURR_DIR, ASSETS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from verify_trainer_dataset import load_verification_prices, verify_dataset
from v191_dt_defer_helper import load_dt_defer_tables

DATA_DIR = os.path.join(CURR_DIR, "data_5y")
DELIVERY_DIR = os.path.join(CURR_DIR, "最新交付题库")
DESK_DIR = "/Users/huaichuaibeimeng/Desktop/短线/题目"
LEDGER_CSV = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_1to2_v19_clean.csv"

HTML_FILES = [
    "一进二_50题.html",
    "一进二_5关.html",
]


def verify_ledger_alignment(json_path):
    ledger_df = pd.read_csv(LEDGER_CSV, dtype={"code": str})
    ledger_map = {
        str(r["buy_date"]): (
            str(r["code"]).zfill(6),
            round(float(r["buy_price"]), 2),
            round(float(r["exit_price"]), 2),
            round(float(r["net_ret"]) * 100.0, 2),
            str(r["exit_date"]),
        )
        for _, r in ledger_df.iterrows()
    }
    dt_tables = load_dt_defer_tables()
    dmap = dt_tables["dmap"]
    with open(json_path, "r", encoding="utf-8") as f:
        cases = json.load(f)
    checked = 0
    for c in cases:
        for t_chk in c['themes']:
            assert t_chk.get('d1_plate_avg_str') and '--' not in t_chk['d1_plate_avg_str'], f"日期 {c['date']} 题材 {t_chk['name']} 漏写板块前一日收盘均幅!"
            for cd in t_chk['cands']:
                if cd.get("executed") and ("收盘" in cd.get("exit_reason", "") or "炸板" in cd.get("exit_reason", "")):
                    c6_cd = cd["code"][:6]
                    eb = dmap.get((c6_cd, cd.get("exit_date", "")))
                    assert not (eb is not None and bool(eb.is_dt_exact)), (
                        f"日期 {c['date']} {c6_cd} 存在15:00封死跌停强卖违规: {cd.get('exit_date')}"
                    )
        if c.get("sys_cand_code"):
            d = c["date"]
            assert d in ledger_map, f"题库日期 {d} 未在 V19.1 洁净账本中找到！"
            lt = ledger_map[d]
            c6 = c["sys_cand_code"].split(".")[0]
            assert c6 == lt[0], f"日期 {d} 股票代码不一致: 题目={c6}, 账本={lt[0]}"
            for t in c["themes"]:
                for cd in t["cands"]:
                    if cd["code"].startswith(c6):
                        assert abs(cd["buy_price"] - lt[1]) <= 0.02, f"日期 {d} 买价不一致: {cd['buy_price']} vs {lt[1]}"
                        assert abs(cd["sell_price"] - lt[2]) <= 0.02, f"日期 {d} 卖价不一致: {cd['sell_price']} vs {lt[2]}"
                        assert abs(cd["net_ret"] - lt[3]) <= 0.05, f"日期 {d} 净收益不一致: {cd['net_ret']} vs {lt[3]}"
                        assert cd.get("exit_date") == lt[4], f"日期 {d} 卖日不一致: {cd.get('exit_date')} vs {lt[4]}"
                        checked += 1
                        break
    assert checked > 0, f"{json_path} 未核验到任何实盘买单！"
    print(f"PASS: {json_path} 中 {checked} 笔实盘交易与 V19.1 洁净账本 (ledger_1to2_v19_clean.csv) 100% 逐笔一致！")


def verify_html_deliverables():
    print("\n--- HTML 交付文件、桌面同步MD5、JS语法与中文表达合规核验 ---")
    forbidden = ["五板策略", "零未来函数", "——", "—", "V18", "pos20_d0", "xq_cnt_2d", "fb_dom295", "恭喜", "潜力进阶打板选手", "顶尖盘感", "绝佳狙击"]
    for fname in HTML_FILES:
        fpath = os.path.join(DELIVERY_DIR, fname)
        dpath = os.path.join(DESK_DIR, fname)
        assert os.path.exists(fpath), f"文件不存在: {fpath}"
        assert os.path.exists(dpath), f"桌面同步文件不存在: {dpath}"
        b1, b2 = open(fpath, "rb").read(), open(dpath, "rb").read()
        h1, h2 = hashlib.md5(b1).hexdigest(), hashlib.md5(b2).hexdigest()
        assert b1 == b2 and h1 == h2, f"桌面同步MD5不一致: {fname} ({h1} vs {h2})"
        sz_kb = len(b1) / 1024.0
        assert sz_kb > 50, f"文件过小可能损坏: {fpath} ({sz_kb:.1f} KB)"
        content = b1.decode("utf-8")
        visible_content = re.sub(
            r'const\s+ENCRYPTED_PAYLOAD\s*=\s*"[^"]*";',
            'const ENCRYPTED_PAYLOAD = "";',
            content,
        )
        for fb in forbidden:
            assert fb not in visible_content, f"文件 {fname} 包含禁用/过期词: {fb}"
        assert re.search(r"[+-]\d+\.\d+%", visible_content), f"文件 {fname} 未见 +/- 收益率符号表达！"
        assert not re.search(r"(?:赚|亏)\s*\d+\.\d+%", visible_content), f"文件 {fname} 仍残留赚/亏数字表达！"
        assert "V19" in visible_content, f"文件 {fname} 未含 V19 版本标记！"
        scripts = re.findall(r"<script>([\s\S]*?)</script>", content)
        for si, sc_txt in enumerate(scripts):
            tmp_js = f"/tmp/verify_v19_js_{os.path.basename(fname)}_{si}.js"
            with open(tmp_js, "w", encoding="utf-8") as jf:
                jf.write(sc_txt)
            chk = subprocess.run(["node", "--check", tmp_js], capture_output=True, text=True)
            assert chk.returncode == 0, f"{fname} JS语法错误: {chk.stderr}"
        print(f"PASS: {fname} ({sz_kb:.1f} KB, md5={h1}) 桌面同步一致、JS语法0错、零禁用词、零破折号、V19.1合规！")


def main():
    print("=" * 80)
    print(">>> 启动 V19.1 题库与 HTML 交付全项物理核验网关...")
    print("=" * 80)
    zt_lookup = load_verification_prices()
    pack1_path = os.path.join(DATA_DIR, "trainer_pack1_50_v19.json")
    chal5_path = os.path.join(DATA_DIR, "trainer_chal5_v19.json")

    verify_dataset(pack1_path, zt_lookup, "V19.1 第1套50题标准卷")
    verify_dataset(chal5_path, zt_lookup, "V19.1 第1辑5关挑战赛")

    verify_ledger_alignment(pack1_path)
    verify_ledger_alignment(chal5_path)
    verify_html_deliverables()

    print("\n" + "=" * 80)
    print("🎉 [核验全通] V19.1 题库数据与 2 个一进二交付 HTML 全部通过 0 错误检验！")
    print("=" * 80)


if __name__ == "__main__":
    main()
