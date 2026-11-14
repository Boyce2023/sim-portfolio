# -*- coding: utf-8 -*-
"""
build_v18_trainer_data.py: V18 第1套50题标准卷与第1辑5关挑战赛数据总构建器
严格对齐 V18 实盘账本 (95笔/68.4%/320.36倍)，单文件严格控制在 150 行以内。
"""
import os, sys, json, time, random, numpy as np, pandas as pd
from collections import defaultdict

CURR_DIR = os.path.dirname(os.path.abspath(__file__))
if CURR_DIR not in sys.path: sys.path.insert(0, CURR_DIR)

from v16_data_loader import (
    load_all_market_base, load_5m_bars_map, load_kpl_metadata,
    load_sh_index_series, load_v16_candidates_full
)
from v16_trade_matcher import make_v16_trade_engine
from v18_scoring import compute_v18_features_and_scores
from v18_case_builder import build_case_for_day_v18
from v18_case_selector import select_pack1_50, select_chal_5

LEDGER_CSV = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/full_day_by_day_v18_ledger.csv"
DATA_5Y_DIR = f"{CURR_DIR}/data_5y"
OUT_PACK1_PERM = f"{DATA_5Y_DIR}/trainer_pack1_50_v18.json"
OUT_PACK1_TMP = "/tmp/astock2_pack1_50_hierarchical.json"
OUT_CHAL5_PERM = f"{DATA_5Y_DIR}/trainer_chal5_v18.json"
OUT_CHAL5_TMP = "/tmp/astock2_chal5_hierarchical.json"

def clean_nans(obj):
    if isinstance(obj, float): return 0.0 if (np.isnan(obj) or np.isinf(obj)) else obj
    elif isinstance(obj, dict): return {k: clean_nans(v) for k, v in obj.items()}
    elif isinstance(obj, list): return [clean_nans(v) for v in obj]
    return obj

def main():
    print("=" * 80)
    print(">>> [V18 Trainer Data] 开始生成 V18 第1套50题标准卷与第1辑5关挑战赛数据...")
    print("=" * 80)
    t0 = time.time()
    
    df_daily, all_dts, dt_to_idx, price_lookup, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map, max_height_map, fb_cnt_map, d1_fb_open_map, stk_hist = load_all_market_base()
    bars_5m_map = load_5m_bars_map()
    r_long_map, plate_daily_sz, kpl_dates = load_kpl_metadata()
    df_sh, sh_date_to_idx, sh_rows = load_sh_index_series()
    hist_fb = load_v16_candidates_full(df_daily, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map)
    hist_fb = compute_v18_features_and_scores(hist_fb)
    hist_fb["r_long"] = [r_long_map.get((d1, c6), "") for d1, c6 in zip(hist_fb["dt_str"], hist_fb["c6"])]
    engine_fn = make_v16_trade_engine(price_lookup, all_dts, dt_to_idx, bars_5m_map)

    fb_by_d2 = defaultdict(list)
    for r in hist_fb.itertuples():
        if "2022-01-04" <= r.d2_dt <= "2026-11-10":
            fb_by_d2[r.d2_dt].append(r)

    ledger_df = pd.read_csv(LEDGER_CSV)
    print(f"载入 V18 实盘账本: {len(ledger_df)} 笔交易。")

    buy_cases = {}
    for _, row in ledger_df.iterrows():
        d2 = row["buy_date"]
        c6 = str(row["c6"]).zfill(6)
        co = build_case_for_day_v18(
            d2, fb_by_d2[d2], engine_fn, stk_hist, all_dts, dt_to_idx,
            price_lookup, zt_cnt_map, dt_cnt_map, fb_cnt_map, seal_rate_map,
            promo_ma5_map, max_height_map, d1_fb_open_map, sh_date_to_idx,
            sh_rows, plate_daily_sz, kpl_dates, seed=42
        )
        if co and co["sys_cand_code"] and co["sys_cand_code"].startswith(c6):
            buy_cases[d2] = co

    empty_cases = {}
    eligible_days = sorted(fb_by_d2.keys())
    rng = random.Random(1337)
    rng.shuffle(eligible_days)
    for d2 in eligible_days:
        if d2 in buy_cases: continue
        co = build_case_for_day_v18(
            d2, fb_by_d2[d2], engine_fn, stk_hist, all_dts, dt_to_idx,
            price_lookup, zt_cnt_map, dt_cnt_map, fb_cnt_map, seal_rate_map,
            promo_ma5_map, max_height_map, d1_fb_open_map, sh_date_to_idx,
            sh_rows, plate_daily_sz, kpl_dates, seed=777
        )
        if co and (co["market_ans"] == "E") and (not co["sys_cand_code"]):
            empty_cases[d2] = co
            if len(empty_cases) >= 60: break

    print(f"构建完成: 有效买入题池 {len(buy_cases)} 关, 空仓题池 {len(empty_cases)} 关。")

    pack1_50 = clean_nans(select_pack1_50(buy_cases, empty_cases, seed=42))
    chal_5 = clean_nans(select_chal_5(buy_cases, empty_cases, seed=88))

    os.makedirs(DATA_5Y_DIR, exist_ok=True)
    for path in [OUT_PACK1_PERM, OUT_PACK1_TMP]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(pack1_50, f, ensure_ascii=False, indent=2, allow_nan=False)
    for path in [OUT_CHAL5_PERM, OUT_CHAL5_TMP]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(chal_5, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"已落盘: {OUT_PACK1_PERM} ({len(pack1_50)} 题), {OUT_CHAL5_PERM} ({len(chal_5)} 题)")

    # 逐笔对照 V18 实盘账本
    ledger_trades = {r["buy_date"]: (str(r["c6"]).zfill(6), round(r["buy_price"], 2), round(r["exit_price"], 2), round(r["net_ret"]*100, 2)) for _, r in ledger_df.iterrows()}
    case_trades = {}
    for c in pack1_50 + chal_5:
        if c["sys_cand_code"]:
            c6 = c["sys_cand_code"].split(".")[0]
            for t in c["themes"]:
                for cd in t["cands"]:
                    if cd["code"].startswith(c6):
                        case_trades[c["date"]] = (c6, cd["buy_price"], cd["sell_price"], cd["net_ret"])
                        break

    match_c6, match_buy, match_sell, match_ret = 0, 0, 0, 0
    common_dates = set(ledger_trades.keys()) & set(case_trades.keys())
    for d in common_dates:
        lt = ledger_trades[d]
        ct = case_trades[d]
        if lt[0] == ct[0]: match_c6 += 1
        if abs(lt[1] - ct[1]) <= 0.02: match_buy += 1
        if abs(lt[2] - ct[2]) <= 0.02: match_sell += 1
        if abs(lt[3] - ct[3]) <= 0.05: match_ret += 1

    print("\n--- V18 实盘账本逐笔核验结果 ---")
    print(f"题目包含账本交易数: {len(common_dates)}")
    print(f"股票代码一致率: {match_c6}/{len(common_dates)} ({match_c6/len(common_dates)*100:.1f}%)")
    print(f"买入价格一致率: {match_buy}/{len(common_dates)} ({match_buy/len(common_dates)*100:.1f}%)")
    print(f"卖出价格一致率: {match_sell}/{len(common_dates)} ({match_sell/len(common_dates)*100:.1f}%)")
    print(f"净收益率一致率: {match_ret}/{len(common_dates)} ({match_ret/len(common_dates)*100:.1f}%)")
    assert match_c6 == len(common_dates) and match_buy == len(common_dates) and match_ret == len(common_dates), "账本逐笔核验未达 100%!"
    print(f"全部耗时: {time.time()-t0:.2f}秒。")

if __name__ == "__main__":
    main()
