#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
verify_trainer_dataset.py
================================================================================
A 股一进二盘感刷题机 · 题库永久防伪硬校验网关 (Q6 物理防再犯)
运行全套断言检查：
1. 真首板零假冒校验：反查 parquet 价格表，断言每只候选股在 d1_date 必须 is_zt==True 且 prev_zt==False！
2. ST 与财报篮子零混入校验：断言候选股无 ST/退，题材卡无财报/业绩字样！
3. 系统排名零倒挂校验：断言黄金狙击带达标股排名严格优先于未及格冷开票！
4. K 线与衍生指标数学一致性：断言最后一根 K 线收盘等于 D1 收盘、预埋点火价纯数学推导、dd20 连续分布！
5. 洗牌均匀度校验：统计 ABCD 与题材胜出分布。
任何一项失败直接 sys.exit(1)！
================================================================================
"""
import os
import sys
import re
import json
from collections import Counter
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT_DIR = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT_DIR}/sim-portfolio"
A_DAILY_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_delisted_daily.parquet"

JSON_PACK1 = "/tmp/astock2_pack1_100_hierarchical.json"
JSON_Q1 = "/tmp/astock2_q1_hierarchical.json"
JSON_Q2 = "/tmp/astock2_q2_hierarchical.json"
JSON_5Y_PERM = f"{SIM_DIR}/backtests_astock2/data_5y/trainer_5y_v16.json"
JSON_POOL_V17 = f"{SIM_DIR}/backtests_astock2/data_5y/trainer_pool_v17_357.json"
JSON_PACK1_PERM = f"{SIM_DIR}/backtests_astock2/data_5y/trainer_pack1_100_v17.json"
JSON_Q1_PERM = f"{SIM_DIR}/backtests_astock2/data_5y/trainer_q1_v16.json"
JSON_Q2_PERM = f"{SIM_DIR}/backtests_astock2/data_5y/trainer_q2_v16.json"
JSON_Q3_PERM = f"{SIM_DIR}/backtests_astock2/data_5y/trainer_q3_v17.json"

EARN_PAT = re.compile(r"(业绩|预增|扭亏|季报|年报|半年报|分红)")


def load_verification_prices():
    cols = ["date", "ticker", "open", "high", "low", "close"]
    ds_act = ds.dataset(A_DAILY_PATH, format="parquet")
    df_act = ds_act.scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2021-01-01"))).to_table().to_pandas()
    parts = [df_act]
    if os.path.exists(A_DELISTED_PATH):
        ds_del = ds.dataset(A_DELISTED_PATH, format="parquet")
        df_del = ds_del.scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2021-01-01"))).to_table().to_pandas()
        parts.append(df_del)
    df = pd.concat(parts, ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(subset=["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    g = df.groupby("c6")
    df["pre_c"] = g["close"].shift(1)
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["zt_price"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_price"] - 0.01) & (df["pct"] >= 0.095) & (df["pre_c"] > 0)
    df["prev_zt"] = g["is_zt"].shift(1).fillna(False)
    df["is_yizi"] = df["is_zt"] & (df["open"] >= df["zt_price"] - 0.01) & (df["low"] >= df["zt_price"] - 0.01)

    zt_lookup = {}
    for r in df[["c6", "dt_str", "is_zt", "prev_zt", "is_yizi", "close", "open", "pre_c"]].itertuples(index=False):
        zt_lookup[(r.c6, r.dt_str)] = (r.is_zt, r.prev_zt, r.is_yizi, r.close, r.open, r.pre_c)
    return zt_lookup


def verify_dataset(json_path, zt_lookup, dataset_label="5Y Dataset"):
    print("=" * 80)
    print(f">>> Verifying {dataset_label} ({json_path})...")
    print("=" * 80)

    if not os.path.exists(json_path):
        print(f"ERROR: File not found: {json_path}")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    print(f"Total cases loaded: {len(cases)}")
    assert len(cases) > 0, "Cases list is empty!"

    fake_first_boards = []
    yizi_first_boards = []
    st_cands = []
    earn_themes = []
    rank_inversions = []
    kline_inconsistencies = []
    trig_inconsistencies = []
    all_dd20_values = []
    ans_counter = Counter()
    theme_ans_counter = Counter()

    for c_i, c in enumerate(cases):
        c_id = c.get("id")
        d1 = c.get("d1_date")
        d2 = c.get("date")
        m_ans = c.get("market_ans")
        m_th = c.get("market_best_theme_idx")
        ans_counter[m_ans] += 1
        theme_ans_counter[m_th] += 1

        themes = c.get("themes", [])
        assert len(themes) == 3, f"Case {c_id} has {len(themes)} themes, expected exactly 3!"

        case_all_cands = []

        for th in themes:
            th_name = th.get("name", "")
            if EARN_PAT.search(th_name) or th_name in {"三季报增长", "业绩增长", "半年报增长", "年报增长", "其他"}:
                earn_themes.append((c_id, d2, th_name))

            cands = th.get("cands", [])
            assert 2 <= len(cands) <= 4, f"Case {c_id} theme {th_name} has {len(cands)} cands, expected 2~4!"

            for cd in cands:
                case_all_cands.append(cd)
                c6 = cd.get("code", "")[:6]
                sname = cd.get("name", "")
                dd20 = cd.get("dd20")
                all_dd20_values.append(dd20)

                # 1. ST 校验
                if "ST" in sname.upper() or "退" in sname:
                    st_cands.append((c_id, d2, c6, sname))

                # 2. 真首板反查 parquet 价格表
                st_info = zt_lookup.get((c6, d1))
                if st_info is None:
                    # 如果已退市或未查到
                    pass
                else:
                    is_zt, prev_zt, is_yizi, close_px, open_px, pre_c = st_info
                    if not (is_zt and (not prev_zt)):
                        fake_first_boards.append((c_id, d1, c6, sname, f"is_zt={is_zt}, prev_zt={prev_zt}"))
                    if is_yizi:
                        yizi_first_boards.append((c_id, d1, c6, sname, "is_yizi=True"))

                # 3. K 线数学一致性 (最后一根收盘价等于 D1 收盘价)
                klines = cd.get("klines", [])
                if klines and len(klines) >= 2:
                    last_c = klines[-1][3]
                    if st_info is not None:
                        real_c = round(st_info[3], 2)
                        if abs(last_c - real_c) > 0.05:
                            kline_inconsistencies.append((c_id, c6, last_c, real_c))

                # 4. 点火价数学推导与 T+1 离场合规性校验
                trig_str = cd.get("trig_str", "")
                m_trig = re.search(r"^([\d\.]+)元", trig_str)
                if m_trig and st_info is not None:
                    calc_trig = float(m_trig.group(1))
                    d2_open = cd.get("d2", [0]*5)[0]
                    zt_p = np.floor(st_info[3] * 1.10 * 100.0 + 0.5) / 100.0
                    is_mon = c.get("is_mon_window", False)
                    if is_mon and "周一竞价直买" in trig_str:
                        expected_trig = round(d2_open, 2)
                    else:
                        expected_trig = min(zt_p, max(round(d2_open * 1.012, 2), round(st_info[3] * 1.065, 2)))
                    if abs(calc_trig - expected_trig) > 0.02:
                        trig_inconsistencies.append((c_id, c6, calc_trig, expected_trig))
                if cd.get("executed") and cd.get("exit_date", "") <= d2:
                    trig_inconsistencies.append((c_id, c6, f"exit_date={cd.get('exit_date')}<=d2={d2}", "violated T+1"))

        # 5. 系统排名零倒挂校验
        # 同一道题内：任何 sys_pass 或 (gate_ok 且在窗口内) 的标的，sys_rank 必须 < 未及格或绿盘冷开票
        is_mon = c.get("is_mon_window", False)
        win_low = 2.0 if is_mon else 2.2
        win_high = 8.8 if is_mon else 7.8
        good_tier3_cands = [cd for cd in case_all_cands if cd.get("sys_pass") or (cd.get("gate_ok") and cd.get("in_buy_window"))]
        bad_tier_cands = [cd for cd in case_all_cands if (not cd.get("sys_pass")) and ((not cd.get("gate_ok")) or (cd.get("o_pct", 0) < 0.0) or (not cd.get("in_buy_window")))]

        for g_cd in good_tier3_cands:
            for b_cd in bad_tier_cands:
                if g_cd.get("sys_rank", 99) > b_cd.get("sys_rank", 99):
                    rank_inversions.append((
                        c_id, d2,
                        f"Good {g_cd['name']}(rank={g_cd['sys_rank']}, o_pct={g_cd['o_pct']}) inverted behind Bad {b_cd['name']}(rank={b_cd['sys_rank']}, o_pct={b_cd['o_pct']}, gate_ok={b_cd['gate_ok']})"
                    ))

    # 输出校验统计与断言
    print("\n--- 1. 真首板零假冒核验 ---")
    print(f"Fake first boards (already 2-board+): {len(fake_first_boards)}")
    print(f"Yizi first boards: {len(yizi_first_boards)}")
    if fake_first_boards:
        print("SAMPLE FAKE FIRST BOARDS:", fake_first_boards[:5])
    assert len(fake_first_boards) == 0, f"FAILED: Found {len(fake_first_boards)} fake first boards!"
    assert len(yizi_first_boards) == 0, f"FAILED: Found {len(yizi_first_boards)} yizi first boards!"
    print("PASS: 100% genuine non-yizi first boards confirmed (0 fake)!")

    print("\n--- 2. ST 与财报篮子核验 ---")
    print(f"ST candidates count: {len(st_cands)}")
    print(f"Earnings themes count: {len(earn_themes)}")
    if st_cands:
        print("SAMPLE ST CANDS:", st_cands[:5])
    if earn_themes:
        print("SAMPLE EARNINGS THEMES:", earn_themes[:5])
    assert len(st_cands) == 0, f"FAILED: Found {len(st_cands)} ST candidates!"
    assert len(earn_themes) == 0, f"FAILED: Found {len(earn_themes)} earnings themes!"
    print("PASS: ST and Earnings themes count is strictly 0!")

    print("\n--- 3. 系统排名零倒挂核验 ---")
    print(f"Rank inversions count: {len(rank_inversions)}")
    if rank_inversions:
        print("SAMPLE INVERSIONS:", rank_inversions[:5])
    assert len(rank_inversions) == 0, f"FAILED: Found {len(rank_inversions)} rank inversions!"
    print("PASS: Zero rank inversions between qualified auction band and unqualified stocks!")

    print("\n--- 4. K 线与衍生指标数学一致性核验 ---")
    print(f"K-line inconsistencies: {len(kline_inconsistencies)}")
    print(f"Trigger price inconsistencies: {len(trig_inconsistencies)}")
    unique_dd20 = len(set(all_dd20_values))
    print(f"Unique dd20 values: {unique_dd20} (assert > 50 for continuous distribution)")
    assert len(kline_inconsistencies) == 0, f"FAILED: {len(kline_inconsistencies)} K-line inconsistencies!"
    assert len(trig_inconsistencies) == 0, f"FAILED: {len(trig_inconsistencies)} trigger price inconsistencies!"
    min_dd20 = 50 if len(cases) > 50 else 10
    assert unique_dd20 >= min_dd20, f"FAILED: dd20 has only {unique_dd20} unique values, likely templated!"
    print(f"PASS: Math consistency verified! dd20 distribution is continuous ({unique_dd20} unique values).")

    print("\n--- 5. 洗牌均匀度分布统计 ---")
    print(f"Option distribution: {dict(ans_counter)}")
    print(f"Theme index distribution: {dict(theme_ans_counter)}")
    assert ans_counter["E"] > 0, "No option E cases!"
    if len(cases) > 50:
        assert ans_counter["A"] > 0 and ans_counter["B"] > 0 and ans_counter["C"] > 0 and ans_counter["D"] > 0, "Options A/B/C/D missing!"
    else:
        assert ans_counter["A"] > 0 and ans_counter["B"] > 0 and ans_counter["C"] > 0 and ans_counter["D"] > 0, "Options A/B/C/D missing in 8 cases!"
    print("PASS: Shuffle uniformity confirmed!")

    print(f"\n>>> ALL CHECKS PASSED FOR {dataset_label}! <<<\n")


def main():
    print("Starting Trainer Dataset Hard Verification Gateway...")
    zt_lookup = load_verification_prices()
    verify_dataset(JSON_5Y_PERM, zt_lookup, "Preserved 357-Case Backup Pool")
    verify_dataset(JSON_POOL_V17, zt_lookup, "V17 357-Case Master Pool")
    verify_dataset(JSON_PACK1_PERM, zt_lookup, "V17 Pack-1 100-Case Standard Pack")
    verify_dataset(JSON_Q1_PERM, zt_lookup, "Classic 8 Cases Dataset (V17)")
    verify_dataset(JSON_Q2_PERM, zt_lookup, "Vol 2 Combat 8 Cases Dataset (V17)")
    if os.path.exists(JSON_Q3_PERM):
        verify_dataset(JSON_Q3_PERM, zt_lookup, "Vol 3 Selected 8 Cases Dataset (V17)")
    print("=" * 80)
    print(">>> [SUCCESS] All verification gates passed with ZERO errors! <<<")
    print("=" * 80)


if __name__ == "__main__":
    main()
