#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_a4_4to5_left_leakage.py — 四进五 12 个跨策略左端衔接因子专项回测
覆盖：F35-F44 + F64 换手收敛 + F66 断层拱卫
双买法评测：
  1. 右侧突破买法: open_pct.between(0.015, 0.085) & touch65_1130 + pm1345_5m + yang_imm
  2. 09:25 开盘买法: buyable_open & open + pm1345_5m + yang_imm
遵循 D12 (零 yfinance), D15 (单仓时序轮动 + 按日等权 + 5年全期/3年近期 + 沪深300净超额 + 去Top3), SQLite mode=ro。
"""
import os, sys, json, pickle
from collections import defaultdict
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
AST2_DIR = f"{ROOT}/sim-portfolio/backtests_astock2"
P3_DIR = f"{AST2_DIR}/p3_deep_100"
sys.path.insert(0, AST2_DIR)
sys.path.insert(0, P3_DIR)

from common_eval_harness import eval_factor_slice, load_production_3_ledgers
from score_3to4_v31_card import score_single_3to4_row
from core_3to4_5m_engine import sim_buy_5m, sim_exit_5m

MAT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
ENRICHED_45_PATH = f"{AST2_DIR}/p2_4to5/cand_4to5_enriched.parquet"
ENRICHED_34_PATH = f"{AST2_DIR}/data_5y/cand_3to4_enriched54.parquet"
BARS_PKL = f"{MAT_DIR}/code_bars_5y.pkl"
OUT_CSV = f"{P3_DIR}/a4_4to5_left_leakage_F35_F44.csv"
OUT_JSON = f"{P3_DIR}/a4_summary.json"
FEE = 0.0020

def load_all_5m_bars():
    d5 = pd.read_parquet(f"{AST2_DIR}/p2_4to5/cand_4to5_5m_bars.parquet")
    d34 = pd.read_parquet(f"{AST2_DIR}/data_5y/cand_3to4_5m_bars.parquet")
    f_v15 = f"{ROOT}/sim-portfolio/data/cand_5m_bars_v15_complete.parquet"
    dv15 = pd.read_parquet(f_v15)
    all_5m = pd.concat([d5, d34, dv15[["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"]]], ignore_index=True)
    all_5m.drop_duplicates(subset=["c6", "date", "hhmm_int"], inplace=True)
    return {(str(c).zfill(6), str(d)): g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float) 
            for (c, d), g in all_5m.groupby(["c6", "date"], sort=False)}

def compute_mkt_nuke_map(cb_map):
    nuke_cnt_map = defaultdict(int)
    for c6, cb in cb_map.items():
        dts = cb["dts"]; zt = cb["is_zt"]; dt = cb["is_dt"]
        hi = cb["high"]; lo = cb["low"]; op = cb["open"]; cl = cb["close"]; pc = cb["pre_c"]
        streak = 0
        for pos in range(len(dts)):
            cur_dt = dts[pos]
            if streak >= 4:
                is_nuke = False
                if dt[pos]:
                    is_nuke = True
                elif pc[pos] > 0:
                    amp = (hi[pos] - lo[pos]) / pc[pos]
                    ret = cl[pos] / pc[pos] - 1.0
                    if amp >= 0.18 and ret < 0:
                        is_nuke = True
                if is_nuke:
                    nuke_cnt_map[cur_dt] += 1
            streak = (streak + 1) if zt[pos] else 0
    return nuke_cnt_map

def prepare_candidates(cb_map, b5m):
    print("[1/5] Loading 4to5 and 3to4 enriched universes...")
    df45 = pd.read_parquet(ENRICHED_45_PATH)
    df45["c6"] = df45["code"].astype(str).str.zfill(6)
    df45["buy_date"] = df45["buy_date"].astype(str)
    df45["sig_date"] = df45["sig_date"].astype(str)

    df34 = pd.read_parquet(ENRICHED_34_PATH)
    df34["c6"] = df34["code"].astype(str).str.zfill(6)
    df34["buy_date"] = df34["buy_date"].astype(str)
    print("      Scoring 3to4 universe with V3.4 scorecard...")
    s34 = [score_single_3to4_row(r)["score"] for r in df34.to_dict("records")]
    df34["v34_score"] = s34

    # Merge Day 4 features from df34 to df45
    m34 = df34[["c6", "buy_date", "prev_is_yizi", "open_board_count", "open_pct", "buyable_open", "v34_score"]].copy()
    m34.rename(columns={
        "buy_date": "sig_date",
        "prev_is_yizi": "d3_prev_is_yizi",
        "open_board_count": "d3_open_board_count",
        "open_pct": "d4_open_pct",
        "buyable_open": "d4_buyable_open",
        "v34_score": "d4_v34_score"
    }, inplace=True)
    df = pd.merge(df45, m34, on=["c6", "sig_date"], how="left")

    # 1. F35: 3to4 Production Ledger Overlap
    print("[2/5] Loading 3to4 production ledger...")
    ledgers = load_production_3_ledgers()
    l34 = ledgers["3to4"]
    l34_set = set(zip(l34["c6"], l34["buy_date"]))
    df["is_held_3to4"] = [((c, d) in l34_set) for c, d in zip(df["c6"], df["sig_date"])]

    # 2. F41: Day 4 afternoon blown board detection from 5m bars
    print("[3/5] Scanning Day 4 5m bars for afternoon blown board (F41)...")
    d4_blown_pm = []
    for r in df.itertuples(index=False):
        c6, sd = str(r.c6), str(r.sig_date)
        arr = b5m.get((c6, sd))
        cb = cb_map.get(c6)
        if arr is None or cb is None:
            d4_blown_pm.append(False)
            continue
        pos_sd = cb["date_to_pos"].get(sd, -1)
        if pos_sd < 0:
            d4_blown_pm.append(False)
            continue
        pc = float(cb["pre_c"][pos_sd])
        blown = False
        for row in arr:
            hhmm, bl = int(row[0]), float(row[3])
            if hhmm >= 1345 and bl <= pc * 1.050:
                blown = True
                break
        d4_blown_pm.append(blown)
    df["d4_blown_pm_5m"] = d4_blown_pm
    df["d4_blown_pm_proxy"] = (df["first_seal_time"].astype(str) > "13:45:00") & (df["open_board_count"] >= 1)

    # 3. F42: Plate firstboard yizi count
    f_1b = f"{MAT_DIR}/cand_0to1_firstboard.parquet"
    df_1b = pd.read_parquet(f_1b, columns=["buy_date", "plate", "open_pct", "is_zt_today", "is_yizi_open"])
    df_1b_yz = df_1b[(df_1b["is_zt_today"] == True) & ((df_1b["open_pct"] >= 0.095) | (df_1b["is_yizi_open"] == True))]
    fb_yz_cnt = df_1b_yz.groupby(["buy_date", "plate"]).size().to_dict()
    df["plate_fb_yz"] = [fb_yz_cnt.get((r.sig_date, r.plate), 0) for r in df.itertuples(index=False)]

    # 4. F44: Market >=4b nuke count on sig_date
    print("[4/5] Computing market-wide >=4b nuke count on sig_date (F44)...")
    nuke_cnt_map = compute_mkt_nuke_map(cb_map)
    df["d4_mkt_nuke_cnt"] = [nuke_cnt_map[d] for d in df["sig_date"]]

    # 5. F66: Plate 3-board count on buy_date
    df_3b = pd.read_parquet(f"{MAT_DIR}/cand_3to4.parquet", columns=["buy_date", "plate"])
    b3_plate_cnt = df_3b.groupby(["buy_date", "plate"]).size().to_dict()
    df["plate_3b_cnt"] = [b3_plate_cnt.get((r.buy_date, r.plate), 0) for r in df.itertuples(index=False)]

    return df

def simulate_all_trades(df, cb_map, b5m):
    print("[5/5] Simulating trade trajectories under both execution modes...")
    n = len(df)
    # Mode 1: 09:25 open
    open_res = [None] * n
    for idx, r in enumerate(df.itertuples(index=False)):
        if not bool(r.buyable_open): continue
        c6, bd = str(r.c6), str(r.buy_date)
        cb = cb_map.get(c6)
        if cb is None: continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or pos >= len(cb["dts"]) - 1: continue
        bpx, bhh = sim_buy_5m(c6, bd, cb, pos, b5m, "open")
        if bpx is None: continue
        ex_dt, spx, adjs, hb, shh = sim_exit_5m(c6, cb, pos, b5m, exit_mode="pm1345_5m", day5_unsealed_mode="cut_weak", use_yang_imm=True)
        nr = (spx * adjs) / (bpx * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0
        open_res[idx] = {"buy_date": bd, "exit_date": ex_dt, "buy_px": bpx, "sell_px": spx, "net_ret": float(nr), "hold_bars": int(hb)}

    # Mode 2: breakthrough touch65_1130
    t65_res = [None] * n
    for idx, r in enumerate(df.itertuples(index=False)):
        if not bool(r.buyable_open) or not (0.015 <= r.open_pct <= 0.085): continue
        c6, bd = str(r.c6), str(r.buy_date)
        cb = cb_map.get(c6)
        if cb is None: continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or pos >= len(cb["dts"]) - 1: continue
        bpx, bhh = sim_buy_5m(c6, bd, cb, pos, b5m, "touch65_1130")
        if bpx is None: continue
        ex_dt, spx, adjs, hb, shh = sim_exit_5m(c6, cb, pos, b5m, exit_mode="pm1345_5m", day5_unsealed_mode="cut_weak", use_yang_imm=True)
        nr = (spx * adjs) / (bpx * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0
        t65_res[idx] = {"buy_date": bd, "exit_date": ex_dt, "buy_px": bpx, "sell_px": spx, "net_ret": float(nr), "hold_bars": int(hb)}

    return open_res, t65_res

def run_all_factor_tests():
    with open(BARS_PKL, "rb") as f: cb_map = pickle.load(f)["code_bars"]
    b5m = load_all_5m_bars()
    df = prepare_candidates(cb_map, b5m)
    open_res, t65_res = simulate_all_trades(df, cb_map, b5m)

    df["ret_open"] = [x["net_ret"] if x else np.nan for x in open_res]
    df["exit_open"] = [x["exit_date"] if x else None for x in open_res]
    df["ret_t65"] = [x["net_ret"] if x else np.nan for x in t65_res]
    df["exit_t65"] = [x["exit_date"] if x else None for x in t65_res]

    # Baseline means
    base_open = float(df["ret_open"].dropna().mean())
    base_t65 = float(df["ret_t65"].dropna().mean())
    print(f"Baselines: Open mode N={df['ret_open'].notna().sum()} AvgRet={base_open*100:.2f}%; Touch65 mode N={df['ret_t65'].notna().sum()} AvgRet={base_t65*100:.2f}%")

    factor_defs = [
        # 1. F35: 三进四已持仓物理互斥锁
        ("F35", "F35_三进四已持仓物理互斥锁", "基准全池", lambda d: d["buyable_open"] == True),
        ("F35", "F35_三进四已持仓物理互斥锁", "纯增量池(物理剔除3to4已成交)", lambda d: (d["buyable_open"] == True) & (d["is_held_3to4"] == False)),
        ("F35", "F35_三进四已持仓物理互斥锁", "3to4已锁仓重合池", lambda d: (d["buyable_open"] == True) & (d["is_held_3to4"] == True)),

        # 2. F36: 三板一字/死封硬否决 + 四板爆量换手15%~32%涅槃回封
        ("F36", "F36_三板死封四板换手涅槃", "命中(三板死封+四板换手15~32%开板回封)", 
         lambda d: (d["buyable_open"] == True) & ((d["d3_prev_is_yizi"] == True) | (d["d3_open_board_count"] == 0)) & (d["open_board_count"] >= 1) & (d["prev_to"].between(15.0, 32.0))),
        ("F36", "F36_三板死封四板换手涅槃", "三板死封但四板未达成良性换手", 
         lambda d: (d["buyable_open"] == True) & ((d["d3_prev_is_yizi"] == True) | (d["d3_open_board_count"] == 0)) & ~((d["open_board_count"] >= 1) & (d["prev_to"].between(15.0, 32.0)))),
        ("F36", "F36_三板死封四板换手涅槃", "三板本身正常开板换手", 
         lambda d: (d["buyable_open"] == True) & (d["d3_prev_is_yizi"] == False) & (d["d3_open_board_count"] >= 1)),

        # 3. F37: 四板竞价超抢漏买股的 Day5 温和分歧首买 (2%~6%)
        ("F37", "F37_四板超抢漏买Day5温和分歧首买", "命中(四板超抢>9.2%或一字+Day5高开2%~6%)", 
         lambda d: (d["buyable_open"] == True) & ((d["d4_open_pct"] > 0.092) | (d["d4_buyable_open"] == False) | (d["prev_is_yizi"] == True)) & (d["open_pct"].between(0.020, 0.060))),
        ("F37", "F37_四板超抢漏买Day5温和分歧首买", "四板超抢但Day5未现温和分歧", 
         lambda d: (d["buyable_open"] == True) & ((d["d4_open_pct"] > 0.092) | (d["d4_buyable_open"] == False) | (d["prev_is_yizi"] == True)) & ~(d["open_pct"].between(0.020, 0.060))),
        ("F37", "F37_四板超抢漏买Day5温和分歧首买", "四板正常开盘+Day5高开2%~6%", 
         lambda d: (d["buyable_open"] == True) & (d["d4_open_pct"] <= 0.092) & (d["d4_buyable_open"] == True) & (d["prev_is_yizi"] == False) & (d["open_pct"].between(0.020, 0.060))),

        # 4. F38: 四板竞价弱开(<3%)深水大长腿拉板 (补3to4竞价下限漏网妖)
        ("F38", "F38_四板弱开深水大长腿拉板", "命中(四板竞价<3%且曾绿盘拉板)", 
         lambda d: (d["buyable_open"] == True) & (d["d4_open_pct"] < 0.030) & (d["d4_intraday_dip"] < 0)),
        ("F38", "F38_四板弱开深水大长腿拉板", "四板竞价<3%全天未破绿", 
         lambda d: (d["buyable_open"] == True) & (d["d4_open_pct"] < 0.030) & (d["d4_intraday_dip"] >= 0)),
        ("F38", "F38_四板弱开深水大长腿拉板", "四板正常高开(>=3%)", 
         lambda d: (d["buyable_open"] == True) & (d["d4_open_pct"] >= 0.030)),

        # 5. F39: 四板午盘(11:30后)逆势独立点火回封 (补3to4午休撤单漏网龙)
        ("F39", "F39_四板午盘逆势独立点火回封", "四板午后首封(>11:30)", 
         lambda d: (d["buyable_open"] == True) & (d["first_seal_time"].astype(str) > "11:30:00")),
        ("F39", "F39_四板午盘逆势独立点火回封", "四板尾盘偷袭首封(>13:45)", 
         lambda d: (d["buyable_open"] == True) & (d["first_seal_time"].astype(str) > "13:45:00")),
        ("F39", "F39_四板午盘逆势独立点火回封", "四板上午早盘封板(<=11:30)", 
         lambda d: (d["buyable_open"] == True) & (d["first_seal_time"].astype(str) <= "11:30:00")),

        # 6. F40: 三进四 82~89分惜败落选但四板独自活下逆袭
        ("F40", "F40_三进四82至89分惜败逆袭", "3to4得分82~89分", 
         lambda d: (d["buyable_open"] == True) & (d["d4_v34_score"].between(82, 89))),
        ("F40", "F40_三进四82至89分惜败逆袭", "3to4得分82~89分且同日唯一四板孤龙", 
         lambda d: (d["buyable_open"] == True) & (d["d4_v34_score"].between(82, 89)) & (d["is_sole_4b"] == 1)),
        ("F40", "F40_三进四82至89分惜败逆袭", "3to4得分>=90分标准龙", 
         lambda d: (d["buyable_open"] == True) & (d["d4_v34_score"] >= 90)),
        ("F40", "F40_三进四82至89分惜败逆袭", "3to4低分或硬否决(<82分)", 
         lambda d: (d["buyable_open"] == True) & (d["d4_v34_score"] < 82)),

        # 7. F41: 四板当日下午 13:45 后曾炸板跌破 +5.0% 尾盘勉强偷封排雷
        ("F41", "F41_四板1345后炸板破5%偷封排雷", "排雷组(5m确认13:45后跌破+5%)", 
         lambda d: (d["buyable_open"] == True) & (d["d4_blown_pm_5m"] == True)),
        ("F41", "F41_四板1345后炸板破5%偷封排雷", "安全组(13:45后未破+5%或未炸板)", 
         lambda d: (d["buyable_open"] == True) & (d["d4_blown_pm_5m"] == False)),
        ("F41", "F41_四板1345后炸板破5%偷封排雷", "全样本代理排雷(首封>13:45且曾开板)", 
         lambda d: (d["buyable_open"] == True) & (d["d4_blown_pm_proxy"] == True)),

        # 8. F42: has_4321_echelon 翻负拆解 (有首板一字 vs 纯换手梯队)
        ("F42", "F42_4321梯队翻负拆解", "有梯队且纯换手(无一字板)", 
         lambda d: (d["buyable_open"] == True) & (d["has_4321_echelon"] == 1) & (d["plate_yizi_cnt"] == 0)),
        ("F42", "F42_4321梯队翻负拆解", "有梯队但有一字板虚假拥挤", 
         lambda d: (d["buyable_open"] == True) & (d["has_4321_echelon"] == 1) & (d["plate_yizi_cnt"] >= 1)),
        ("F42", "F42_4321梯队翻负拆解", "无3-2-1梯队孤立无援", 
         lambda d: (d["buyable_open"] == True) & (d["has_4321_echelon"] == 0)),

        # 9. F43: 同题材队友 Day5 竞价均值 <-1.5% 核按钮排雷
        ("F43", "F43_同题材队友竞价核按钮排雷", "排雷组(同题材队友竞价均值<-1.5%)", 
         lambda d: (d["buyable_open"] == True) & (d["plate_peers_open_avg"] < -0.015)),
        ("F43", "F43_同题材队友竞价核按钮排雷", "安全组(同题材队友竞价均值>=-1.5%)", 
         lambda d: (d["buyable_open"] == True) & (d["plate_peers_open_avg"] >= -0.015)),

        # 10. F44: 前一日 >=4 板高标出现跌停或天地板核辐射排雷
        ("F44", "F44_前日高标跌停核辐射排雷", "安全期(前日>=4板跌停/大阴线==0)", 
         lambda d: (d["buyable_open"] == True) & (d["d4_mkt_nuke_cnt"] == 0)),
        ("F44", "F44_前日高标跌停核辐射排雷", "核辐射期(前日>=4板跌停/大阴线>=1)", 
         lambda d: (d["buyable_open"] == True) & (d["d4_mkt_nuke_cnt"] >= 1)),

        # 11. F64: 三板与四板连续两日开板换手且换手率温和收敛
        ("F64", "F64_三板四板换手温和收敛", "温和收敛(0.70<=to_ratio<=1.35)", 
         lambda d: (d["buyable_open"] == True) & (d["to_ratio_d4_d3"].between(0.70, 1.35))),
        ("F64", "F64_三板四板换手温和收敛", "缩量加速(to_ratio<0.60)", 
         lambda d: (d["buyable_open"] == True) & (d["to_ratio_d4_d3"] < 0.60)),
        ("F64", "F64_三板四板换手温和收敛", "爆量分歧(to_ratio>1.60)", 
         lambda d: (d["buyable_open"] == True) & (d["to_ratio_d4_d3"] > 1.60)),
        ("F64", "F64_三板四板换手温和收敛", "连续开板换手且温和收敛(d4_ob>=1&d3_ob>=1&0.70~1.35)", 
         lambda d: (d["buyable_open"] == True) & (d["open_board_count"] >= 1) & (d["d3_open_board_count"] >= 1) & (d["to_ratio_d4_d3"].between(0.70, 1.35))),

        # 12. F66: 同题材「1只四板孤龙 + 首板补涨>=1 + 中间零3板紧追」断层拱卫
        ("F66", "F66_四板孤龙首板断层拱卫", "断层拱卫(1只4板+首板>=1+零3板紧追)", 
         lambda d: (d["buyable_open"] == True) & (d["is_sole_4b"] == 1) & (d["plate_fb_cnt"] >= 1) & (d["plate_3b_cnt"] == 0)),
        ("F66", "F66_四板孤龙首板断层拱卫", "有3板紧追内卷(1只4板+首板>=1+3板>=1)", 
         lambda d: (d["buyable_open"] == True) & (d["is_sole_4b"] == 1) & (d["plate_fb_cnt"] >= 1) & (d["plate_3b_cnt"] >= 1)),
        ("F66", "F66_四板孤龙首板断层拱卫", "无首板补涨或非孤龙结构", 
         lambda d: (d["buyable_open"] == True) & ~((d["is_sole_4b"] == 1) & (d["plate_fb_cnt"] >= 1))),
    ]

    records = []
    summary_dict = {
        "benchmark": {"open_mode_mean": base_open, "touch65_mode_mean": base_t65},
        "factors": defaultdict(dict)
    }

    for fid, fname, sname, cond_fn in factor_defs:
        mask = cond_fn(df)
        sub = df[mask].copy()

        # 1. Open Mode
        m_open = eval_factor_slice(sub, ret_col="ret_open", exit_col="exit_open", rank_col="open_pct", base_mean=base_open)
        rec_open = {
            "factor_id": fid, "factor_name": fname, "slice_name": sname, "buy_mode": "open_925", **m_open
        }
        records.append(rec_open)

        # 2. Touch65 Mode
        m_t65 = eval_factor_slice(sub, ret_col="ret_t65", exit_col="exit_t65", rank_col="open_pct", base_mean=base_t65)
        rec_t65 = {
            "factor_id": fid, "factor_name": fname, "slice_name": sname, "buy_mode": "touch65_1130", **m_t65
        }
        records.append(rec_t65)

        summary_dict["factors"][fid][sname] = {
            "open_925": m_open,
            "touch65_1130": m_t65
        }

    res_df = pd.DataFrame(records)
    res_df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary_dict, f, ensure_ascii=False, indent=2)

    print(f"\n[Done] All 12 factors evaluated and saved:")
    print(f"  -> CSV: {OUT_CSV} ({len(res_df)} rows)")
    print(f"  -> JSON: {OUT_JSON}")
    return res_df, summary_dict

if __name__ == "__main__":
    run_all_factor_tests()
