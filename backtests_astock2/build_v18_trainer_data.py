# -*- coding: utf-8 -*-
"""
build_v18_trainer_data.py: V19 第1套50题标准卷与第1辑5关挑战赛数据总构建器
严格对齐 V19.1 洁净真账 (ledger_1to2_v19_clean.csv: 97笔/68.04%/332.72倍)，自动归档旧版 JSON 至 _archive/，组装 HTML 并同步桌面。
"""
import os
import sys
import json
import time
import shutil
import random
from collections import defaultdict
import numpy as np
import pandas as pd

CURR_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(CURR_DIR, "assets")
for _p in (CURR_DIR, ASSETS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from v19_data_adapter import load_v19_trainer_context
from v18_case_builder import build_case_for_day_v18
from v18_case_selector import select_pack1_50, select_chal_5
from v19_ui_enricher import enrich_v19_cases_ui_fields
from trainer_assembler_v18 import assemble_v18_deliverables

LEDGER_CSV = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_1to2_v19_clean.csv"
DATA_5Y_DIR = os.path.join(CURR_DIR, "data_5y")
ARCHIVE_DIR = os.path.join(CURR_DIR, "_archive", "20261117_v19_v40_upgrade")
OUT_PACK1_PERM = os.path.join(DATA_5Y_DIR, "trainer_pack1_50_v19.json")
OUT_CHAL5_PERM = os.path.join(DATA_5Y_DIR, "trainer_chal5_v19.json")


def clean_nans(obj):
    if isinstance(obj, float):
        return 0.0 if (np.isnan(obj) or np.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: clean_nans(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_nans(v) for v in obj]
    return obj


def archive_old_v18_jsons():
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    for fn in ("trainer_pack1_50_v18.json", "trainer_chal5_v18.json"):
        src = os.path.join(DATA_5Y_DIR, fn)
        if os.path.exists(src):
            shutil.move(src, os.path.join(ARCHIVE_DIR, fn))
            print(f"[归档] 已移入旧版JSON: {fn} -> _archive/20261117_v19_v40_upgrade/")


def main():
    print("=" * 80)
    print(">>> [V19.1 Trainer Data] 开始生成 V19 第1套50题标准卷与第1辑5关挑战赛数据（332.72x 洁净真账）...")
    print("=" * 80)
    t0 = time.time()

    ctx = load_v19_trainer_context()
    hist_fb = ctx["hist_fb"]
    fb_by_d2 = defaultdict(list)
    for r in hist_fb.itertuples():
        if "2022-01-04" <= r.d2_dt <= "2026-11-16":
            fb_by_d2[r.d2_dt].append(r)

    ledger_df = pd.read_csv(LEDGER_CSV, dtype={"code": str})
    ledger_df["c6"] = ledger_df["code"].astype(str).str.zfill(6)
    print(f"载入 V19.1 洁净实盘账本: {len(ledger_df)} 笔交易。")

    buy_cases = {}
    for _, row in ledger_df.iterrows():
        d2, c6 = str(row["buy_date"]), str(row["c6"]).zfill(6)
        if not ("2022-01-04" <= d2 <= "2026-11-16"):
            continue
        co = build_case_for_day_v18(
            d2, fb_by_d2[d2], ctx["engine_fn"], ctx["stk_hist"], ctx["all_dts"], ctx["dt_to_idx"],
            ctx["price_lookup"], ctx["zt_cnt_map"], ctx["dt_cnt_map"], ctx["fb_cnt_map"], ctx["seal_rate_map"],
            ctx["promo_ma5_map"], ctx["max_height_map"], ctx["d1_fb_open_map"], ctx["sh_date_to_idx"],
            ctx["sh_rows"], ctx["plate_daily_sz"], ctx["kpl_dates"], seed=42
        )
        if co and co["sys_cand_code"] and co["sys_cand_code"].startswith(c6):
            buy_cases[d2] = co

    empty_cases = {}
    eligible_days = sorted(fb_by_d2.keys())
    rng = random.Random(1337)
    rng.shuffle(eligible_days)
    for d2 in eligible_days:
        if d2 in buy_cases:
            continue
        co = build_case_for_day_v18(
            d2, fb_by_d2[d2], ctx["engine_fn"], ctx["stk_hist"], ctx["all_dts"], ctx["dt_to_idx"],
            ctx["price_lookup"], ctx["zt_cnt_map"], ctx["dt_cnt_map"], ctx["fb_cnt_map"], ctx["seal_rate_map"],
            ctx["promo_ma5_map"], ctx["max_height_map"], ctx["d1_fb_open_map"], ctx["sh_date_to_idx"],
            ctx["sh_rows"], ctx["plate_daily_sz"], ctx["kpl_dates"], seed=777
        )
        if co and (co["market_ans"] == "E") and (not co["sys_cand_code"]):
            empty_cases[d2] = co
            if len(empty_cases) >= 60:
                break

    print(f"构建完成: 有效买入题池 {len(buy_cases)} 关, 空仓题池 {len(empty_cases)} 关。")
    pack1_50 = enrich_v19_cases_ui_fields(clean_nans(select_pack1_50(buy_cases, empty_cases, seed=42)))
    chal_5 = enrich_v19_cases_ui_fields(clean_nans(select_chal_5(buy_cases, empty_cases, seed=88)))

    os.makedirs(DATA_5Y_DIR, exist_ok=True)
    for path, data_obj in ((OUT_PACK1_PERM, pack1_50), (OUT_CHAL5_PERM, chal_5)):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data_obj, f, ensure_ascii=False, indent=2, allow_nan=False)
    archive_old_v18_jsons()
    print(f"已落盘: {OUT_PACK1_PERM} ({len(pack1_50)} 题), {OUT_CHAL5_PERM} ({len(chal_5)} 题)")

    ledger_trades = {
        str(r["buy_date"]): (str(r["c6"]).zfill(6), round(float(r["buy_price"]), 2), round(float(r["exit_price"]), 2), round(float(r["net_ret"]) * 100, 2))
        for _, r in ledger_df.iterrows()
    }
    case_trades = {}
    for c in pack1_50 + chal_5:
        if c["sys_cand_code"]:
            c6 = c["sys_cand_code"].split(".")[0]
            for t in c["themes"]:
                for cd in t["cands"]:
                    if cd["code"].startswith(c6):
                        case_trades[c["date"]] = (c6, cd["buy_price"], cd["sell_price"], cd["net_ret"])
                        break

    common_dates = sorted(set(ledger_trades.keys()) & set(case_trades.keys()))
    m_c6 = sum(ledger_trades[d][0] == case_trades[d][0] for d in common_dates)
    m_buy = sum(abs(ledger_trades[d][1] - case_trades[d][1]) <= 0.02 for d in common_dates)
    m_sell = sum(abs(ledger_trades[d][2] - case_trades[d][2]) <= 0.02 for d in common_dates)
    m_ret = sum(abs(ledger_trades[d][3] - case_trades[d][3]) <= 0.05 for d in common_dates)
    print(f"--- V19.1 账本逐笔核验: 交易={len(common_dates)} 代码={m_c6} 买价={m_buy} 卖价={m_sell} 净收益={m_ret} ---")
    assert m_c6 == len(common_dates) and m_buy == len(common_dates) and m_sell == len(common_dates) and m_ret == len(common_dates), "V19.1 账本逐笔核验未达 100%!"

    assemble_v18_deliverables()
    print(f"全部完成，耗时: {time.time()-t0:.2f}秒。")


if __name__ == "__main__":
    main()
