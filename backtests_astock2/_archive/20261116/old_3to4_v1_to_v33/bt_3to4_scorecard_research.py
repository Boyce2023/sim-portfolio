#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三进四全因子双期/近期加权边际效应扫描 + 「题材内其他首板与梯队」专项实证
底座：100% 真实 5 分钟 K 线因果撮合（touch65_1130 + pm1345）
时间权重：重点考察 2024-2026 与 2025-2026 近期量化微结构，兼顾 2022-2023 防过拟合
"""
import os
import sys
import json
import pickle
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from core_3to4_5m_engine import BARS_5M_PATH, MATRIX_DIR
from bt_3to4_step1_clean_5m_master import build_clean_5m_pool


def load_enriched_and_pool():
    df = pd.read_parquet(f"{CUR_DIR}/data_5y/cand_3to4_enriched54.parquet")
    with open(f"{MATRIX_DIR}/code_bars_5y.pkl", "rb") as f:
        code_bars = pickle.load(f)["code_bars"]
    df_5m = pd.read_parquet(BARS_5M_PATH)
    df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    bars_5m_map = {
        (c6, dt_s): g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        for (c6, dt_s), g in df_5m.groupby(["c6", "date"], sort=False)
    }
    df["prio_base"] = df["open_pct"] * 1000.0 + df["lock_top10"] * 0.5
    pool = build_clean_5m_pool(df, code_bars, bars_5m_map, "touch65_1130", 1345, 1.050, prio_col="prio_base")
    df["has_trig"] = [p is not None for p in pool]
    df["net_ret_5m"] = [p["net_ret"] if p is not None else np.nan for p in pool]
    return df, pool


def bucket_stat(sub: pd.DataFrame, cond: pd.Series):
    t, f = sub[cond]["net_ret_5m"], sub[~cond]["net_ret_5m"]
    if len(t) < 6 or len(f) < 6:
        return None
    return {
        "n_on": int(len(t)), "wr_on": float((t > 0).mean() * 100), "ret_on": float(t.mean() * 100),
        "n_off": int(len(f)), "wr_off": float((f > 0).mean() * 100), "ret_off": float(f.mean() * 100),
        "d_wr": float(((t > 0).mean() - (f > 0).mean()) * 100),
        "d_ret": float((t.mean() - f.mean()) * 100),
    }


def main():
    df, _ = load_enriched_and_pool()
    # Base tradable triggered pool: 10cm non-ST, non-yizi, buyable_open, open in [1.0%, 9.2%], triggered +6.5% by 11:30
    base = df[df["has_trig"] & df["open_pct"].between(0.010, 0.092)].copy()
    print(f"Base triggered 5m pool N={len(base)} | 22-23={int((base['buy_date']<'2024').sum())} | 24-26={int((base['buy_date']>='2024').sum())} | 25-26={int((base['buy_date']>='2025').sum())}")

    # Define physically meaningful binary hypotheses to test cleanly across eras
    hyps = [
        # A. 三板洗盘与换手结构
        ("三板开板洗盘(open_board>=1)", base["open_board_count"] >= 1),
        ("前三板全换手成龙(turn_boards_3d==3)", base["turn_boards_3d"] >= 3),
        ("换手黄金带(prev_to 9~28%)", base["prev_to"].between(9.0, 28.0)),
        ("极端爆量换手(prev_to>30%)", base["prev_to"] > 30.0),
        ("极端缩量锁死(prev_to<8%)", base["prev_to"] < 8.0),
        ("早封板(<10:30硬封)", base["is_hard_open_1030"].astype(bool)),
        ("高封成比(seal_tightness>=15)", base["seal_tightness"] >= 15.0),
        # B. 筹码、容量、股价与异动空间
        ("高锁仓或大容量(lock>=45或free>=45)", (base["lock_top10"] >= 45.0) | (base["real_free_mcap"] >= 45.0)),
        ("强锁仓(lock_top10>=50)", base["lock_top10"] >= 50.0),
        ("低锁仓小散票(lock<35且free<35)", (base["lock_top10"] < 35.0) & (base["real_free_mcap"] < 35.0)),
        ("低中价股(px_d3<=20元)", base["px_d3"] <= 20.0),
        ("高价股畏高(px_d3>30元)", base["px_d3"] > 30.0),
        ("异动空间充裕(headroom_100>=35%)", base["headroom_100"] >= 0.35),
        ("临近100%异动红线(headroom<22%)", base["headroom_100"] < 0.22),
        ("竞价强势黄金窗(open 3.5~8.8%)", base["open_pct"].between(0.035, 0.088)),
        ("竞价偏弱试错(open 1.0~3.0%)", base["open_pct"] < 0.030),
        ("60日干净突破(clean_brk60)", base["clean_brk60"].astype(bool)),
        # C. 龙虎榜与监管真雷
        ("零拉萨散户席位(lhb_lh==0)", base["lhb_lh_cnt"] == 0),
        ("拉萨散户扎堆(lhb_lh>=2)", base["lhb_lh_cnt"] >= 2),
        ("拉萨重度接盘(lhb_lh>=3或占比>=18%)", (base["lhb_lh_cnt"] >= 3) | (base["lhb_lh_share"] >= 0.18)),
        ("知名量化席位参与(lhb_quant>=1)", base["lhb_quant_cnt"] >= 1),
        ("机构席位现身(lhb_inst>=1)", base["lhb_inst_cnt"] >= 1),
        ("真毒公告或个股监管(tox或stock_reg)", base["has_tox_notice"] | base["has_stock_reg"]),
        ("交易所重点监控期(has_ex_reg)", base["has_ex_reg"].astype(bool)),
        # D. 题材内其他首板、二板与梯队（100% 严守 09:25 时点，零盘中偷看！）
        ("三板当日同题材有首板小弟(plate_fb>=1)", base["plate_fb_cnt"] >= 1),
        ("三板当日同题材首板>=2家(plate_fb>=2)", base["plate_fb_cnt"] >= 2),
        ("三板当日同题材首板>=3家(plate_fb>=3)", base["plate_fb_cnt"] >= 3),
        ("首板小弟次日竞价高开>=3%助攻(fb_ho>=1)", base["plate_fb_ho_cnt"] >= 1),
        ("首板小弟次日竞价高开>=2家(fb_ho>=2)", base["plate_fb_ho_cnt"] >= 2),
        ("首板小弟次日竞价一字顶板(fb_yz>=1)", base["plate_fb_yz_cnt"] >= 1),
        ("四板09:25同题材新0进1高开>=5%(fresh>=1)", base["plate_fresh01_hi_cnt"] >= 1),
        ("四板09:25同题材新0进1高开>=5%达2家", base["plate_fresh01_hi_cnt"] >= 2),
        ("同题材有二板中位(plate_2b>=1)", base["plate_2b_cnt"] >= 1),
        ("同题材完整3+2+1梯队(has_321_plate)", base["has_321_plate"].astype(bool)),
        ("同行业或同题材3+2+1梯队(has_321_any)", base["has_321_any"].astype(bool)),
        ("三板当日同行业首板>=2家(csrc_fb>=2)", base["csrc_fb_cnt"] >= 2),
        ("三板当日同行业首板>=3家(csrc_fb>=3)", base["csrc_fb_cnt"] >= 3),
        ("同行业首板次日高开>=2家", base["csrc_fb_ho_cnt"] >= 2),
        ("同题材涨停>=3家(p_sz>=3)", base["p_sz"] >= 3),
        ("同行业涨停>=3家(csrc_zt>=3)", base["csrc_zt_cnt"] >= 3),
        ("同题材队友竞价均值>=0%(peers_op>=0)", base["plate_peers_open_avg"] >= 0.0),
        ("同题材队友竞价核按钮(peers_op<-1.5%)", base["plate_peers_open_avg"] < -0.015),
        ("主线高热度题材(p_elo>=135)", base["p_elo"] >= 135.0),
        ("纯独苗无板块(is_pure_outsider)", base["is_pure_outsider"].astype(bool)),
        ("同日三板竞价第一身位(is_top1_3b)", base["is_top1_3b_open"].astype(bool)),
        ("同日三板扎堆内卷(b3_rival>=4)", base["b3_rival_cnt"] >= 4),
        # E. 市场情绪与压回撤因子
        ("前日三板零跌停(prev_3b_dt==0)", base["prev_3b_dt_cnt"] == 0),
        ("前日三板多股核按钮(prev_3b_dt>=2)", base["prev_3b_dt_cnt"] >= 2),
        ("近20日三进四核按钮率高(nuke20>=0.25)", base["prev_3to4_nuke_rate_20d"] >= 0.25),
        ("近10日炸板大面率低(brk_dt10<0.15)", base["prev_break_dt_rate_10d"] < 0.15),
        ("沪深300近5日走稳(csi5>=-0.8%)", base["csi_5d_prev"] >= -0.008),
        ("沪深300近5日急跌(csi5<-2.2%)", base["csi_5d_prev"] < -0.022),
        ("全场涨停适中不过热(mkt_zt 35~85)", base["mkt_zt_prev"].between(35, 85)),
        ("全场百股涨停过热分化(mkt_zt>=95)", base["mkt_zt_prev"] >= 95),
        ("最高板<=4无高标压制破局期", base["mkt_max_board_prev"] <= 4),
    ]

    m_old = base["buy_date"] < "2024-01-01"
    m_rec3 = base["buy_date"] >= "2024-01-01"
    m_rec2 = base["buy_date"] >= "2025-01-01"

    rows = []
    for name, cond in hyps:
        s_all = bucket_stat(base, cond)
        s_old = bucket_stat(base[m_old], cond[m_old])
        s_r3 = bucket_stat(base[m_rec3], cond[m_rec3])
        s_r2 = bucket_stat(base[m_rec2], cond[m_rec2])
        if not s_all or not s_r3:
            continue
        d_old = s_old["d_ret"] if s_old else 0.0
        d_r3 = s_r3["d_ret"]
        d_r2 = s_r2["d_ret"] if s_r2 else d_r3
        w_score = 0.20 * d_old + 0.35 * d_r3 + 0.45 * d_r2
        rows.append((name, s_all["n_on"], s_all["d_wr"], s_all["d_ret"], d_old, s_r3["d_wr"], d_r3, d_r2, w_score))

    rows.sort(key=lambda x: x[8], reverse=True)
    print("\n=== 全因子近期高权重边际效应榜 (w_ret = 0.20*[22-23] + 0.35*[24-26] + 0.45*[25-26]) ===")
    for name, non, dwr, dret, dold, r3wr, dr3, dr2, ws in rows:
        print(f"{name:34s} | ON={non:3d} | 5Y ΔWR={dwr:+5.1f}% ΔRet={dret:+5.2f}% | 22-23={dold:+5.2f}% | 24-26 ΔWR={r3wr:+5.1f}% ΔRet={dr3:+5.2f}% | 25-26={dr2:+5.2f}% | 加权={ws:+5.2f}%")

    with open(f"{CUR_DIR}/scorecard_factor_scan_5m.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
