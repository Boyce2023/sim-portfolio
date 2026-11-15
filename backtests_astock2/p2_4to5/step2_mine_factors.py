#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四进五 36+ 因子双期检验与单变量筛选 (<=150 行)"""
import json, pickle, numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
ENRICHED_PATH = f"{ROOT}/sim-portfolio/backtests_astock2/p2_4to5/cand_4to5_enriched.parquet"
BARS_PKL = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/code_bars_5y.pkl"
OUT_CSV = f"{ROOT}/sim-portfolio/backtests_astock2/p2_4to5/factor_36_screen.csv"
OUT_JSON = f"{ROOT}/sim-portfolio/backtests_astock2/p2_4to5/factor_36_screen.json"

def compute_base_returns(df, cb_map):
    rets, zt5s, dts = [], [], []
    for r in df.itertuples(index=False):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        cb = cb_map.get(c6); pos = cb["date_to_pos"].get(bd, -1) if cb else -1
        if cb is None or pos < 0 or pos >= len(cb["dts"]) - 1: rets.append(0.0); zt5s.append(0); dts.append(bd); continue
        op = float(cb["open"][pos]); zt5s.append(int(cb["is_zt"][pos]))
        # Benchmark exit: sell at next day close or open if limit up
        nxt = pos + 1
        if bool(cb["is_zt"][pos]):
            # hold while zt
            k = pos + 1; n = len(cb["dts"])
            while k < n and bool(cb["is_zt"][k]): k += 1
            while k < n and bool(cb["is_yizi_dt"][k]): k += 1
            if k >= n: k = n - 1
            spx = float(cb["close"][k])
            ret = (spx * cb["adjf"][k]) / (op * cb["adjf"][pos]) - 1.0 - 0.0020
        else:
            # next day exit
            spx = float(cb["close"][nxt])
            ret = (spx * cb["adjf"][nxt]) / (op * cb["adjf"][pos]) - 1.0 - 0.0020
        rets.append(ret); dts.append(bd)
    df["base_ret"] = rets; df["is_zt5"] = zt5s; df["is_win"] = [int(x > 0) for x in rets]
    return df

def run_factor_screen():
    df = pd.read_parquet(ENRICHED_PATH)
    with open(BARS_PKL, "rb") as f: cb_map = pickle.load(f)["code_bars"]
    # Filter buyable
    df = df[df["buyable_open"]].copy()
    df = compute_base_returns(df, cb_map)
    df["year"] = pd.to_datetime(df["buy_date"]).dt.year
    df_early = df[df["year"] <= 2023]
    df_recent = df[df["year"] >= 2024]
    df_huan = df[~df["prev_is_yizi"]].copy()

    factors = [
        ("Base_Pool", "Baseline", "全可买基准", lambda d: d["buyable_open"]),
        ("Base_HuanShou", "Baseline", "第四板换手基准", lambda d: ~d["prev_is_yizi"]),
        ("Base_YiZi", "Baseline", "第四板一字", lambda d: d["prev_is_yizi"]),
        # Prop 1: Space & Rivals
        ("is_mkt_highest_4b", "Prop1_Space", "昨日最高板为4板(争空间龙头)", lambda d: d["is_mkt_highest_4b"] == 1),
        ("is_mkt_max_le5", "Prop1_Space", "昨日最高板<=5板", lambda d: d["is_mkt_max_le5"] == 1),
        ("is_mkt_max_ge6", "Prop1_Space", "昨日最高板>=6板(中位跟风坟场)", lambda d: d["is_mkt_max_ge6"] == 1),
        ("is_sole_4b", "Prop1_Space", "全场唯一4板独苗", lambda d: d["is_sole_4b"] == 1),
        ("b4_rival_cnt_ge2", "Prop1_Space", "同日多只4板PK(>=2)", lambda d: d["b4_rival_cnt"] >= 2),
        ("is_top1_4b_open", "Prop1_Space", "同日4板竞价第1名", lambda d: d["is_top1_4b_open"] == 1),
        ("open_weak_to_strong", "Prop1_Space", "竞价弱转强(-2%~+3%)", lambda d: (d["open_pct"] >= -0.02) & (d["open_pct"] <= 0.03)),
        ("open_mod_high", "Prop1_Space", "竞价适度高开(+3%~+6%)", lambda d: (d["open_pct"] > 0.03) & (d["open_pct"] <= 0.06)),
        ("open_surge", "Prop1_Space", "竞价加速抢筹(>+6%)", lambda d: d["open_pct"] > 0.06),
        ("open_deep_low", "Prop1_Space", "竞价深水低开(<-2%)", lambda d: d["open_pct"] < -0.02),
        # Prop 2: Headroom
        ("headroom_100_ge22", "Prop2_Headroom", "10日异动剩余空间>=22%(安全)", lambda d: d["headroom_100"] >= 0.22),
        ("headroom_100_lt12", "Prop2_Headroom", "10日异动剩余空间<12%(紧迫)", lambda d: d["headroom_100"] < 0.12),
        ("headroom_200_ge35", "Prop2_Headroom", "30日异动剩余空间>=35%", lambda d: d["headroom_200"] >= 0.35),
        # Prop 3: Divergence & Base
        ("turn_boards_4d_eq4", "Prop3_Divergence", "前4板全换手(==4)", lambda d: d["turn_boards_4d"] == 4),
        ("turn_boards_4d_ge3", "Prop3_Divergence", "前4板>=3个换手板", lambda d: d["turn_boards_4d"] >= 3),
        ("turn_boards_4d_le2", "Prop3_Divergence", "前4板<=2个换手板(一字虚筹)", lambda d: d["turn_boards_4d"] <= 2),
        ("open_board_count_ge1", "Prop3_Divergence", "第4板曾开板分歧", lambda d: d["open_board_count"] >= 1),
        ("open_board_count_eq0", "Prop3_Divergence", "第4板硬封0开板", lambda d: d["open_board_count"] == 0),
        ("d4_dip_subzero", "Prop3_Divergence", "第4板曾水下洗盘(dip<0)", lambda d: d["d4_intraday_dip"] < 0),
        ("d4_amp_ge7", "Prop3_Divergence", "第4板振幅>=7%", lambda d: d["d4_amp"] >= 0.07),
        ("to_ratio_norm", "Prop3_Divergence", "4板/3板换手比合理(0.7~1.5)", lambda d: (d["to_ratio_d4_d3"] >= 0.7) & (d["to_ratio_d4_d3"] <= 1.5)),
        ("to_ratio_boom", "Prop3_Divergence", "4板/3板换手过热爆量(>1.8)", lambda d: d["to_ratio_d4_d3"] > 1.8),
        ("to_ratio_shrink", "Prop3_Divergence", "4板/3板换手缩量(<0.5)", lambda d: d["to_ratio_d4_d3"] < 0.5),
        ("first_seal_early", "Prop3_Divergence", "第4板早盘封板(<10:00)", lambda d: d["first_seal_time"].astype(str) < "10:00:00"),
        ("seal_tightness_hi", "Prop3_Divergence", "封单硬度高(>=0.05)", lambda d: d["seal_tightness"] >= 0.05),
        ("prev_real_to_mid", "Prop3_Divergence", "第4板真实换手(12%~28%)", lambda d: (d["prev_real_to"] >= 0.12) & (d["prev_real_to"] <= 0.28)),
        # Prop 4: Capital & Price
        ("lock_top10_ge45", "Prop4_Capital", "前十大股东锁仓>=45%", lambda d: d["lock_top10"] >= 0.45),
        ("real_free_mcap_lt25", "Prop4_Capital", "真实自由流通盘<25亿(轻体量)", lambda d: d["real_free_mcap"] < 25.0),
        ("real_free_mcap_25_40", "Prop4_Capital", "自由流通盘25~40亿", lambda d: (d["real_free_mcap"] >= 25.0) & (d["real_free_mcap"] <= 40.0)),
        ("real_free_mcap_ge45", "Prop4_Capital", "自由流通盘>=45亿(天花板)", lambda d: d["real_free_mcap"] >= 45.0),
        ("mcap_lt80", "Prop4_Capital", "总市值<80亿", lambda d: d["mcap"] < 80.0),
        ("px_d4_lt10", "Prop4_Capital", "股价<10元(低价红利)", lambda d: d["px_d4"] < 10.0),
        ("px_d4_10_20", "Prop4_Capital", "股价10~20元", lambda d: (d["px_d4"] >= 10.0) & (d["px_d4"] <= 20.0)),
        ("px_d4_ge30", "Prop4_Capital", "股价>=30元(高价劣势)", lambda d: d["px_d4"] >= 30.0),
        ("clean_brk60", "Prop4_Capital", "突破60日新高", lambda d: d["clean_brk60"] == 1),
        ("prior_mb_gap_le120", "Prop4_Capital", "120天内有妖股前科", lambda d: d["prior_mb_gap"] <= 120),
        # Prop 5: Echelon & Emotion
        ("has_4321_echelon", "Prop5_Emotion", "同题材有3-2-1梯队支撑", lambda d: d["has_4321_echelon"] == 1),
        ("plate_fb_cnt_ge2", "Prop5_Emotion", "同题材前日首板数>=2", lambda d: d["plate_fb_cnt"] >= 2),
        ("rk_theme_eq1", "Prop5_Emotion", "主线核心题材(排名第1)", lambda d: d["rk_theme"] == 1),
        ("s_elo_ge100", "Prop5_Emotion", "题材强势度Elo>=100", lambda d: d["s_elo"] >= 100),
        ("csrc_zt_cnt_ge4", "Prop5_Emotion", "所属行业涨停>=4家", lambda d: d["csrc_zt_cnt"] >= 4),
        ("lhasa_seats_eq0", "Prop5_Emotion", "龙虎榜无拉萨散户扎堆", lambda d: d["lhb_lh_cnt"] == 0),
        ("lhb_quant_ge1", "Prop5_Emotion", "龙虎榜有量化席位", lambda d: d["lhb_quant_cnt"] >= 1),
        ("lhb_inst_ge1", "Prop5_Emotion", "龙虎榜有机构席位", lambda d: d["lhb_inst_cnt"] >= 1),
        ("surf_yz_buy_ge1", "Prop5_Emotion", "龙虎榜有一日游游资", lambda d: d["surf_yz_buy"] >= 1),
        ("top_yz_buy_ge1", "Prop5_Emotion", "龙虎榜有顶级格局游资", lambda d: d["top_yz_buy"] >= 1),
        ("has_stock_reg", "Prop5_Emotion", "个股有交易所监管关注函", lambda d: d["has_stock_reg"] == 1),
        ("has_tox_notice", "Prop5_Emotion", "买入日前有减持暴雷公告", lambda d: d["has_tox_notice"] == 1),
        ("prev_break_dt_lt15", "Prop5_Emotion", "市场断板跌停率<15%", lambda d: d["prev_break_dt_rate_10d"] < 0.15),
        ("prev_3b_dt_cnt_eq0", "Prop5_Emotion", "昨日3板跌停数==0", lambda d: d["prev_3b_dt_cnt"] == 0),
        ("csi_1d_prev_pos", "Prop5_Emotion", "沪深300昨日收红", lambda d: d["csi_1d_prev"] > 0.0),
        ("is_post_holiday_or_mon", "Prop5_Emotion", "周一/节后第一个交易日", lambda d: d["is_post_holiday_or_mon"] == 1),
        ("is_earn_blackout", "Prop5_Emotion", "财报避险窗口期", lambda d: d["is_earn_blackout_month"] == 1),
    ]

    records = []
    base_m_ret = df["base_ret"].mean()
    for fname, cat, desc, fn in factors:
        sub = df[fn(df)]
        n = len(sub)
        if n < 5: continue
        ztr = sub["is_zt5"].mean(); ret_m = sub["base_ret"].mean(); win_r = sub["is_win"].mean()
        # Early vs Recent
        sub_e = df_early[fn(df_early)] if len(df_early) else sub
        sub_r = df_recent[fn(df_recent)] if len(df_recent) else sub
        ret_e = sub_e["base_ret"].mean() if len(sub_e) >= 3 else np.nan
        ret_r = sub_r["base_ret"].mean() if len(sub_r) >= 3 else np.nan
        win_e = sub_e["is_win"].mean() if len(sub_e) >= 3 else np.nan
        win_r_recent = sub_r["is_win"].mean() if len(sub_r) >= 3 else np.nan
        # Consistent if both periods beat base or both have positive ret
        is_cons = (ret_e > 0 and ret_r > 0) or (ret_e > base_m_ret and ret_r > base_m_ret) if (not np.isnan(ret_e) and not np.isnan(ret_r)) else False
        records.append({
            "factor": fname, "category": cat, "description": desc, "sample_n": n,
            "seal_5b_rate": round(float(ztr), 4), "mean_ret": round(float(ret_m), 4),
            "win_rate": round(float(win_r), 4), "mean_ret_early": round(float(ret_e), 4) if not np.isnan(ret_e) else None,
            "mean_ret_recent": round(float(ret_r), 4) if not np.isnan(ret_r) else None,
            "win_rate_early": round(float(win_e), 4) if not np.isnan(win_e) else None,
            "win_rate_recent": round(float(win_r_recent), 4) if not np.isnan(win_r_recent) else None,
            "is_consistent": bool(is_cons)
        })

    df_out = pd.DataFrame(records)
    df_out.sort_values("mean_ret", ascending=False, inplace=True)
    df_out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    with open(OUT_JSON, "w", encoding="utf-8") as f: json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"[Done] Tested {len(records)} factors -> {OUT_CSV}")
    print(df_out.head(15)[["factor", "description", "sample_n", "seal_5b_rate", "mean_ret", "win_rate", "is_consistent"]].to_string())

if __name__ == "__main__":
    run_factor_screen()
