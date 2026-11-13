# -*- coding: utf-8 -*-
"""
build_true_v16_trainer_data.py: 题库全量 5 年 (360 关) + Q1 经典 8 关 + Q2 实战 8 关总生成器
严格对齐 V16 终极完全体 (211.36倍/105笔) 实盘账本。
"""
import os, sys, re, json, time, random
from collections import defaultdict, Counter
import numpy as np, pandas as pd

CURR_DIR = os.path.dirname(os.path.abspath(__file__))
if CURR_DIR not in sys.path:
    sys.path.insert(0, CURR_DIR)

from v16_data_loader import (
    load_all_market_base, load_5m_bars_map, load_kpl_metadata,
    load_sh_index_series, load_v16_candidates_full, EVENT_BASKET_PLATES
)
from v16_trade_matcher import make_v16_trade_engine
from v16_cand_builder import build_cand_dict
from v16_case_builder import build_theme_dict, build_case_dict

LEDGER_CSV = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/trial_v1_final_ledger.csv"
DATA_5Y_DIR = f"{CURR_DIR}/data_5y"
OUT_POOL_V17 = f"{DATA_5Y_DIR}/trainer_pool_v17_357.json"
OUT_PACK1_100 = f"{DATA_5Y_DIR}/trainer_pack1_100_v17.json"
OUT_PACK1_TMP = "/tmp/astock2_pack1_100_hierarchical.json"
OUT_Q1_PERM = f"{DATA_5Y_DIR}/trainer_q1_v16.json"
OUT_Q1_TMP = "/tmp/astock2_q1_hierarchical.json"
OUT_Q2_PERM = f"{DATA_5Y_DIR}/trainer_q2_v16.json"
OUT_Q2_TMP = "/tmp/astock2_q2_hierarchical.json"

EARN_PAT = re.compile(r"(业绩|预增|扭亏|季报|年报|半年报|分红)")
EVENT_PAT = re.compile(r"(重组|股权转让|实控人|举牌|借壳|摘帽)")
NON_THEME = {'年报增长', '业绩增长', '中报增长', 'ST板块', '其他', '次新股', '半年报增长', '三季报增长', '公告', '一季报增长'}

Q1_DATES = ['2022-01-21', '2022-05-20', '2023-02-06', '2023-03-21', '2024-04-11', '2025-01-27', '2025-03-07', '2026-01-05']
Q2_DATES = ['2022-06-20', '2023-01-04', '2023-06-16', '2024-02-22', '2024-10-22', '2025-05-07', '2025-08-20', '2026-03-25']

def build_case_for_day(d2, cands_today, engine_fn, stk_hist, all_dts, dt_to_idx, price_lookup, zt_cnt_map, dt_cnt_map, fb_cnt_map, seal_rate_map, promo_ma5_map, max_height_map, d1_fb_open_map, sh_date_to_idx, sh_rows, plate_daily_sz, kpl_dates, seed=42, forced_plates=None):
    idx2 = dt_to_idx.get(d2, -1)
    if idx2 <= 0:
        return None
    d1 = all_dts[idx2 - 1]
    gap_days = (pd.to_datetime(d2) - pd.to_datetime(d1)).days
    is_mon = gap_days >= 3

    # 有效候选股与有效板块（同时保留含一字板的完整同板块首板池供精确统计前排一字数）
    full_plate_cands = defaultdict(list)
    for c in cands_today:
        if (c.dt_str == d1) and (not c.is_st):
            full_plate_cands[c.plate].append(c)

    valid_cands_today = [
        c for c in cands_today if (c.dt_str == d1) and (not c.is_st) and (c.d2_open < c.d2_zt_p - 0.005)
        and (c.plate not in EVENT_BASKET_PLATES) and (c.plate not in NON_THEME)
        and (not EARN_PAT.search(c.plate)) and (not EVENT_PAT.search(c.plate))
    ]
    plate_cands = defaultdict(list)
    for c in valid_cands_today:
        plate_cands[c.plate].append(c)

    chosen_plates = []
    if forced_plates:
        for fp in forced_plates:
            if fp in plate_cands and len(plate_cands[fp]) >= 2 and fp not in NON_THEME and not EARN_PAT.search(fp):
                chosen_plates.append(fp)

    # 优先保证 V16 出手股所在板块入选
    v16_trig_cands = [c for c in valid_cands_today if getattr(c, "v16_tot", False)]
    if v16_trig_cands and len(chosen_plates) < 3:
        best_trig = min(v16_trig_cands, key=lambda c: -getattr(c, "v16_sv", 0.0))
        if best_trig.plate in plate_cands and len(plate_cands[best_trig.plate]) >= 2 and best_trig.plate not in chosen_plates:
            chosen_plates.append(best_trig.plate)

    # 其余按热度最高补齐 3 个
    other_plates = sorted([p for p, cl in plate_cands.items() if len(cl) >= 2 and p not in chosen_plates], key=lambda p: max(getattr(c, "t_score_c", 100.0) for c in plate_cands[p]), reverse=True)
    for p in other_plates:
        if len(chosen_plates) >= 3:
            break
        chosen_plates.append(p)
    chosen_plates = chosen_plates[:3]

    if len(chosen_plates) < 3:
        return None

    rng = random.Random(seed)
    rng.shuffle(chosen_plates)

    # 选候选股 (2~4 只)
    theme_cands_map = {}
    all_case_cands = []
    for p in chosen_plates:
        pool = sorted(plate_cands[p], key=lambda c: getattr(c, "sys_rank_score", 0.0), reverse=True)
        if len(pool) > 4:
            picked = pool[:3] + [pool[-1]]
        else:
            picked = pool
        theme_cands_map[p] = picked
        all_case_cands.extend(picked)

    # 计算 sys_rank
    all_case_cands.sort(key=lambda c: getattr(c, "sys_rank_score", 0.0), reverse=True)
    cand_to_sysrank = {c.c6: i + 1 for i, c in enumerate(all_case_cands)}

    # 构建 cands 与 themes
    themes_json = []
    all_built_cands = []
    k_idx = kpl_dates.index(d1) if d1 in kpl_dates else -1

    for p_idx, p in enumerate(chosen_plates):
        pool_shuffled = list(theme_cands_map[p])
        rng.shuffle(pool_shuffled)
        opt_letters = ["A", "B", "C", "D"]

        all_p_cands = plate_cands[p]
        p_cands_in_win = sorted([c for c in all_p_cands if c.is_buyable_open and (not c.nuclear_halt) and (not c.promo_freeze) and ((is_mon and (0.020 <= c.d2_o_pct <= 0.088)) or ((not is_mon) and (0.022 <= c.d2_o_pct <= 0.078)))], key=lambda c: c.d2_o_pct, reverse=True)
        p_non_yizi = sorted(all_p_cands, key=lambda c: c.d2_o_pct, reverse=True)

        built_cands = []
        d3_dt = all_dts[dt_to_idx[d2] + 1] if dt_to_idx.get(d2, 0) + 1 < len(all_dts) else d2
        for opt_i, c in enumerate(pool_shuffled):
            opt = opt_letters[opt_i]
            sim_res = engine_fn(c)
            d2_bar = price_lookup.get((c.c6, d2))
            d2_k = [round(float(d2_bar[0]), 2), round(float(d2_bar[1]), 2), round(float(d2_bar[2]), 2), round(float(d2_bar[3]), 2), round(float(d2_bar[8]), 0)] if d2_bar else [round(c.d2_open, 2), round(c.d2_high, 2), round(c.d2_low, 2), round(c.d2_close, 2), 100000.0]
            d3_bar = price_lookup.get((c.c6, d3_dt))
            d3_k = [round(float(d3_bar[0]), 2), round(float(d3_bar[1]), 2), round(float(d3_bar[2]), 2), round(float(d3_bar[3]), 2), round(float(d3_bar[8]), 0)] if d3_bar else d2_k
            cd = build_cand_dict(
                c, opt, p_idx, sim_res, stk_hist.get(c.c6, []),
                d1, d2_k, d3_k, is_mon, p_cands_in_win, p_non_yizi, cand_to_sysrank, full_plate_cands[p]
            )
            built_cands.append(cd)
            all_built_cands.append(cd)

        if k_idx >= 0:
            heat_bars = [plate_daily_sz[kpl_dates[j]].get(p, 0) for j in range(max(0, k_idx - 9), k_idx + 1)]
            if len(heat_bars) < 10: heat_bars = [0] * (10 - len(heat_bars)) + heat_bars
        else: heat_bars = [1] * 10

        th_obj = build_theme_dict(p_idx, p, theme_cands_map[p], all_p_cands, pool_shuffled[0].p_sz, heat_bars, is_mon, built_cands, full_plate_cands[p])
        themes_json.append(th_obj)

    case_obj = build_case_dict(
        1, d2, d1, themes_json, all_built_cands, cands_today,
        zt_cnt_map, dt_cnt_map, fb_cnt_map, seal_rate_map, promo_ma5_map,
        max_height_map, d1_fb_open_map, sh_date_to_idx, sh_rows
    )
    return case_obj

def main():
    print("=" * 80)
    print(">>> [V16 Trainer Data] Starting V16 5Y + Q1 + Q2 Production Build...")
    print("=" * 80)
    t0 = time.time()

    df_daily, all_dts, dt_to_idx, price_lookup, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map, max_height_map, fb_cnt_map, d1_fb_open_map, stk_hist = load_all_market_base()
    bars_5m_map = load_5m_bars_map()
    r_long_map, plate_daily_sz, kpl_dates = load_kpl_metadata()
    df_sh, sh_date_to_idx, sh_rows = load_sh_index_series()
    hist_fb = load_v16_candidates_full(df_daily, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map)
    engine_fn = make_v16_trade_engine(price_lookup, all_dts, dt_to_idx, bars_5m_map)

    # Attach r_long to hist_fb
    hist_fb["r_long"] = [r_long_map.get((d1, c6), "") for d1, c6 in zip(hist_fb["dt_str"], hist_fb["c6"])]

    # Group cands by d2_dt
    fb_by_d2 = defaultdict(list)
    for r in hist_fb.itertuples():
        if "2022-01-04" <= r.d2_dt <= "2026-11-10":
            fb_by_d2[r.d2_dt].append(r)

    # Identify eligible days
    eligible_days = []
    for d2 in sorted(fb_by_d2.keys()):
        idx2 = dt_to_idx.get(d2, -1)
        if idx2 <= 0: continue
        d1_target = all_dts[idx2 - 1]
        cands = fb_by_d2[d2]
        valid = [c for c in cands if (c.dt_str == d1_target) and (not c.is_st) and (c.d2_open < c.d2_zt_p - 0.005) and (c.plate not in EVENT_BASKET_PLATES) and (c.plate not in NON_THEME) and (not EARN_PAT.search(c.plate)) and (not EVENT_PAT.search(c.plate))]
        p_cnt = Counter(c.plate for c in valid)
        if sum(1 for p, cnt in p_cnt.items() if cnt >= 2) >= 3:
            eligible_days.append(d2)

    ledger_df = pd.read_csv(LEDGER_CSV)
    ledger_dates = sorted(set(ledger_df["buy_date"]))
    print(f"Total eligible days: {len(eligible_days)} | Ledger trade dates: {len(ledger_dates)}")

    # Lock dates: ledger + Q1 + Q2
    locked_dates = set(ledger_dates) | set(Q1_DATES) | set(Q2_DATES)
    rem_eligible = [d for d in eligible_days if d not in locked_dates]
    needed_supp = 360 - len(locked_dates)
    step = len(rem_eligible) / float(needed_supp)
    sampled_supp = [rem_eligible[min(int(i * step), len(rem_eligible) - 1)] for i in range(needed_supp)]

    final_5y_dates = sorted(list(locked_dates | set(sampled_supp)))
    print(f"Selected {len(final_5y_dates)} dates for 5Y dataset.")

    # 1 & 2. Build Q1 & Q2 balanced 8 cases
    def pick_balanced_8(dates, old_themes_map, salt):
        opts_per_date = []
        for idx_q, d2 in enumerate(dates):
            forced = old_themes_map.get(d2)
            c_list = []
            for s in range(1, 30):
                co = build_case_for_day(d2, fb_by_d2[d2], engine_fn, stk_hist, all_dts, dt_to_idx, price_lookup, zt_cnt_map, dt_cnt_map, fb_cnt_map, seal_rate_map, promo_ma5_map, max_height_map, d1_fb_open_map, sh_date_to_idx, sh_rows, plate_daily_sz, kpl_dates, seed=s*salt + idx_q*17, forced_plates=forced)
                if co: c_list.append(co)
            opts_per_date.append(c_list)
        srng = random.Random(salt)
        best = None
        for _ in range(3000):
            combo = [srng.choice(opts) for opts in opts_per_date]
            if {"A", "B", "C", "D", "E"}.issubset(set(c["market_ans"] for c in combo)):
                best = combo; break
        res = best if best else [opts[0] for opts in opts_per_date]
        for i, c in enumerate(res): c["id"] = i + 1
        return res

    old_q1_p = "/tmp/astock2_q1_hierarchical.json"
    old_q1_themes = {c["date"]: [t["name"] for t in c["themes"]] for c in json.load(open(old_q1_p))} if os.path.exists(old_q1_p) else {}
    q1_cases = pick_balanced_8(Q1_DATES, old_q1_themes, 137)

    old_q2_p = "/tmp/astock2_q2_hierarchical.json"
    old_q2_themes = {c["date"]: [t["name"] for t in c["themes"]] for c in json.load(open(old_q2_p))} if os.path.exists(old_q2_p) else {}
    q2_cases = pick_balanced_8(Q2_DATES, old_q2_themes, 251)

    # 3. Build 5Y dataset (360 cases)
    q1_map = {c["date"]: c for c in q1_cases}
    q2_map = {c["date"]: c for c in q2_cases}
    cases_5y = []
    for c_i, d2 in enumerate(final_5y_dates):
        if d2 in q1_map:
            co = dict(q1_map[d2])
            co["id"] = c_i + 1
            cases_5y.append(co)
        elif d2 in q2_map:
            co = dict(q2_map[d2])
            co["id"] = c_i + 1
            cases_5y.append(co)
        else:
            co = build_case_for_day(d2, fb_by_d2[d2], engine_fn, stk_hist, all_dts, dt_to_idx, price_lookup, zt_cnt_map, dt_cnt_map, fb_cnt_map, seal_rate_map, promo_ma5_map, max_height_map, d1_fb_open_map, sh_date_to_idx, sh_rows, plate_daily_sz, kpl_dates, seed=c_i*10007 + 42)
            if co:
                co["id"] = c_i + 1
                cases_5y.append(co)

    def clean_nans(obj):
        if isinstance(obj, float):
            return 0.0 if (np.isnan(obj) or np.isinf(obj)) else obj
        elif isinstance(obj, dict):
            return {k: clean_nans(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_nans(v) for v in obj]
        return obj

    cases_5y = clean_nans(cases_5y)
    q1_cases = clean_nans(q1_cases)
    q2_cases = clean_nans(q2_cases)

    # 从重刷后的全池中均匀抽取第 1 套 100 题标准卷（覆盖 2022~2026 全年段 + 真龙局与空仓陷阱局，剩余留作后续套卷底库）
    trig_pool = [c for c in cases_5y if c["sys_cand_code"]]
    non_trig_pool = [c for c in cases_5y if not c["sys_cand_code"]]
    n_trig_pick = min(50, len(trig_pool))
    n_nontrig_pick = 100 - n_trig_pick
    picked_trig = [trig_pool[int(i * len(trig_pool) / n_trig_pick)] for i in range(n_trig_pick)]
    picked_nontrig = [non_trig_pool[int(i * len(non_trig_pool) / n_nontrig_pick)] for i in range(n_nontrig_pick)]
    pack1_dates = {c["date"] for c in (picked_trig + picked_nontrig)}
    pack1_100 = []
    for c in cases_5y:
        if c["date"] in pack1_dates and len(pack1_100) < 100:
            cp = dict(c)
            cp["id"] = len(pack1_100) + 1
            pack1_100.append(cp)

    # Save outputs (注意：绝不覆盖原 trainer_5y_v16.json，原 357 关保留不动！)
    with open(OUT_POOL_V17, "w", encoding="utf-8") as f:
        json.dump(cases_5y, f, ensure_ascii=False, indent=2, allow_nan=False)
    for path in [OUT_PACK1_100, OUT_PACK1_TMP]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(pack1_100, f, ensure_ascii=False, indent=2, allow_nan=False)
    for path in [OUT_Q1_PERM, OUT_Q1_TMP]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(q1_cases, f, ensure_ascii=False, indent=2, allow_nan=False)
    for path in [OUT_Q2_PERM, OUT_Q2_TMP]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(q2_cases, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"Saved {len(cases_5y)} V17 pool cases (untouched backup trainer_5y_v16.json preserved), {len(pack1_100)} Pack-1 100 cases, {len(q1_cases)} Q1 cases, {len(q2_cases)} Q2 cases in {time.time()-t0:.2f}s.")

    # Ledger audit
    ledger_trades = {r["buy_date"]: (str(r["c6"]).zfill(6), round(r["buy_price"], 2), round(r["exit_price"], 2), round(r["net_ret"]*100, 2)) for _, r in ledger_df.iterrows()}
    case_trades = {}
    for c in cases_5y:
        if c["sys_cand_code"]:
            c6 = c["sys_cand_code"].split(".")[0]
            # find cand
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

    print("\n--- V16 Ledger Audit ---")
    print(f"Total ledger dates: {len(ledger_trades)}, Captured in trainer: {len(common_dates)}")
    print(f"Stock code match: {match_c6}/{len(common_dates)} ({match_c6/len(common_dates)*100:.1f}%)")
    print(f"Buy price match:  {match_buy}/{len(common_dates)} ({match_buy/len(common_dates)*100:.1f}%)")
    print(f"Sell price match: {match_sell}/{len(common_dates)} ({match_sell/len(common_dates)*100:.1f}%)")
    print(f"Net ret match:    {match_ret}/{len(common_dates)} ({match_ret/len(common_dates)*100:.1f}%)")

if __name__ == "__main__":
    main()
