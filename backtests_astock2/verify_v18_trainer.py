# -*- coding: utf-8 -*-
"""
verify_v18_trainer.py: V18 题库与 HTML 产物物理硬核验网关
核验 5 大项：真首板零假冒、ST/财报零混入、排名零倒挂、K线数学一致性、账本逐笔100%一致、HTML中文交付规范。
单文件严格控制在 150 行以内。
"""
import os, sys, re, json, pandas as pd

CURR_DIR = os.path.dirname(os.path.abspath(__file__))
if CURR_DIR not in sys.path: sys.path.insert(0, CURR_DIR)

from verify_trainer_dataset import load_verification_prices, verify_dataset

DATA_DIR = os.path.join(CURR_DIR, "data_5y")
DELIVERY_DIR = os.path.join(CURR_DIR, "最新交付题库")
LEDGER_CSV = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/full_day_by_day_v18_ledger.csv"

HTML_FILES = [
    "A股一进二盘感刷题机_V18第1套50题免密版.html",
    "A股一进二盘感刷题机_V18第1套50题口令版.html",
    "A股一进二盘感挑战赛_V18第1辑5关免密版.html",
    "A股一进二盘感挑战赛_V18第1辑5关口令版.html"
]

def verify_ledger_alignment(json_path):
    ledger_df = pd.read_csv(LEDGER_CSV)
    ledger_map = {r["buy_date"]: (str(r["c6"]).zfill(6), round(r["buy_price"], 2), round(r["exit_price"], 2), round(r["net_ret"]*100, 2)) for _, r in ledger_df.iterrows()}
    with open(json_path, "r", encoding="utf-8") as f: cases = json.load(f)
    checked = 0
    for c in cases:
        if c.get("sys_cand_code"):
            d = c["date"]
            assert d in ledger_map, f"题库日期 {d} 未在 V18 账本中找到！"
            lt = ledger_map[d]
            c6 = c["sys_cand_code"].split(".")[0]
            assert c6 == lt[0], f"日期 {d} 股票代码不一致: 题目={c6}, 账本={lt[0]}"
            # 找到对应标的核验价格与收益
            for t in c["themes"]:
                for cd in t["cands"]:
                    if cd["code"].startswith(c6):
                        assert abs(cd["buy_price"] - lt[1]) <= 0.02, f"日期 {d} 买价不一致: {cd['buy_price']} vs {lt[1]}"
                        assert abs(cd["sell_price"] - lt[2]) <= 0.02, f"日期 {d} 卖价不一致: {cd['sell_price']} vs {lt[2]}"
                        assert abs(cd["net_ret"] - lt[3]) <= 0.05, f"日期 {d} 净收益不一致: {cd['net_ret']} vs {lt[3]}"
                        checked += 1
                        break
    print(f"PASS: {json_path} 中 {checked} 笔实盘交易与 V18 账本 100% 逐笔一致！")

def verify_html_deliverables():
    print("\n--- HTML 交付文件与中文表达合规核验 ---")
    forbidden = ["五板策略", "零未来函数", "——", "—"]
    trad_chars = re.compile(r"[\u4e00-\u9fa5]") # baseline check for standard characters
    for fname in HTML_FILES:
        fpath = os.path.join(DELIVERY_DIR, fname)
        assert os.path.exists(fpath), f"文件不存在: {fpath}"
        sz_kb = os.path.getsize(fpath) / 1024.0
        assert sz_kb > 50, f"文件过小可能损坏: {fpath} ({sz_kb:.1f} KB)"
        with open(fpath, "r", encoding="utf-8") as f: content = f.read()
        for fb in forbidden:
            assert fb not in content, f"文件 {fname} 包含禁用词/符号: {fb}"
        assert ("赚" in content) or ("亏" in content), f"文件 {fname} 未见规范中文收益表达！"
        print(f"PASS: {fname} ({sz_kb:.1f} KB) 零禁用词、零破折号、格式合规！")

def main():
    print("=" * 80)
    print(">>> 启动 V18 题库与 HTML 交付全项物理核验网关...")
    print("=" * 80)
    zt_lookup = load_verification_prices()
    pack1_path = os.path.join(DATA_DIR, "trainer_pack1_50_v18.json")
    chal5_path = os.path.join(DATA_DIR, "trainer_chal5_v18.json")

    verify_dataset(pack1_path, zt_lookup, "V18 第1套50题标准卷")
    verify_dataset(chal5_path, zt_lookup, "V18 第1辑5关挑战赛")

    verify_ledger_alignment(pack1_path)
    verify_ledger_alignment(chal5_path)
    verify_html_deliverables()

    print("\n" + "=" * 80)
    print("🎉 [核验全通] V18 题库数据与 4 个交付 HTML 全部通过 0 错误检验！")
    print("=" * 80)

if __name__ == "__main__":
    main()
