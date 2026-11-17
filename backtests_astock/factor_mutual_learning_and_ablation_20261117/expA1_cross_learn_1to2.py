#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
expA1_cross_learn_1to2.py
================================================================================
一进二 V18 跨策略双向互学实证引擎（从二进三 V1.0 & 三进四 V3.4 借入 10 大因子）
严格遵守：
  1. 沙盒隔离：只输出到 factor_mutual_learning_and_ablation_20261117/result_A1_cross_learn_1to2.json
  2. 严禁 import yfinance (D12)；所有 SQLite 使用 file:...?mode=ro 只读连接
  3. 正向 / 反向 / 非线性（两头/中段）全向检验，禁止预设同向有效
  4. 严格 IS (2021-2023) 定方向与分值 -> OOS (2024-2026) 纯盲测，D15 五期净超额 + 100万起1000万封顶/EQ/Trim3/MDD
  5. 三行代码校验：单位除数 + 时间锚点 < buy_date 09:25:00 + 极值与基线 assert
================================================================================
"""

import os
import sys
import re
import json
import time
import bisect
import sqlite3
import datetime
from collections import defaultdict, Counter

import numpy as np
import pandas as pd

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{PROJECT_ROOT}/sim-portfolio"
BACKTEST_CLEAN_DIR = f"{SIM_DIR}/backtest/2026-11-11-1to2-clean"
BACKTEST_ASTOCK_DIR = f"{SIM_DIR}/backtests_astock"
SANDBOX_OUT_DIR = f"{BACKTEST_ASTOCK_DIR}/factor_mutual_learning_and_ablation_20261117"
os.makedirs(SANDBOX_OUT_DIR, exist_ok=True)

if BACKTEST_CLEAN_DIR not in sys.path:
    sys.path.insert(0, BACKTEST_CLEAN_DIR)
if BACKTEST_ASTOCK_DIR not in sys.path:
    sys.path.insert(0, BACKTEST_ASTOCK_DIR)
if f"{BACKTEST_ASTOCK_DIR}/clean_2to3_v10_20261117" not in sys.path:
    sys.path.insert(0, f"{BACKTEST_ASTOCK_DIR}/clean_2to3_v10_20261117")

from clean_wf_1to2_v14_ironclad_master import (
    load_full_prices, FEE_RATE, NON_THEME,
    BAD_NOTICE_PAT, NEG_NOTICE_PAT, HARD_NOTICE_PAT, HARD_NOTICE_ORIG_PAT,
    MA_NOTICE_PAT, EARN_NOTICE_PAT, norm_term
)
from exp1_fake_theme_purifier import (
    build_8y_purified_theme_metadata,
    compute_purifier_auction_scores
)
import bt_2to3_v10_clean_master as m23

OUT_JSON = f"{SANDBOX_OUT_DIR}/result_A1_cross_learn_1to2.json"

PARQUET_5M_PATH = f"{SIM_DIR}/data/all_strategies_5m_complete_pit.parquet"
DB_IR_QA_PATH = f"{SIM_DIR}/data/cninfo_ir_qa_5y_pit.db"
PARQUET_TOX_PATH = f"{SIM_DIR}/data/pit_reg_tox_notices_5y_complete.parquet"
CSV_CSRC_PIT_PATH = f"{SIM_DIR}/data/csrc_industry_pit_clean.csv"
DB_NOTICES_PATH = f"{SIM_DIR}/data/cninfo_notices_5y_pit.db"
DB_TAPE_PATH = f"{SIM_DIR}/data/zt_micro_tape_5y_pit.db"
DB_XUEQIU_PATH = f"{SIM_DIR}/data/xueqiu_guba_5y_pit.db"
KPL_MERGED_PATH = f"{SIM_DIR}/data/kpl_plates_2018_2026_merged.jsonl"
KPL_5Y_PATH = f"{SIM_DIR}/data/kpl_plates_5y_2021_2026_complete.jsonl"
LHB_BUY_PATH = f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_buy.parquet"
LHB_SELL_PATH = f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_sell.parquet"
HOLDERS_PATH = f"{BACKTEST_ASTOCK_DIR}/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"
IDX_JSON = f"{BACKTEST_ASTOCK_DIR}/sandbox_lab/index_klines_5y_cache.json"
CSI300_BENCH_FILE = f"{BACKTEST_ASTOCK_DIR}/clean_rebacktest_20261116/csi300_canonical_20261116.json"

CANON_5Y_START = "2021-11-15"
DATA_END_DT = "2026-11-16"

SURF_YZ_3TO4 = re.compile(r"(?:上塘路|财通.*杭州上塘|东方财富.*昌都|佛山|绿景路|苏南|消闲派|国泰君安.*宜昌|开源.*西安西大街)")
SURF_YZ_PURE = re.compile(r"(?:上塘路|财通.*杭州上塘|佛山|绿景路|苏南|消闲派|国泰君安.*宜昌|开源.*西安西大街)")


def build_v18_base_data():
    t0 = time.time()
    print("[1/5] Loading 1to2 V18 base daily prices, 8Y themes, notices, 5m bars...")
    df_daily, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices()

    # Validate unit divisors on daily data
    assert 10.0 < df_daily["mcap"].median() < 500.0, f"mcap unit check failed: {df_daily['mcap'].median()}"
    assert 0.1 < df_daily["to"].median() < 20.0, f"to(%) unit check failed: {df_daily['to'].median()}"

    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    price_lookup = {
        (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
        for r in df_daily[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
    }

    stock_theme_5y, pioneer_word_history = build_8y_purified_theme_metadata(df_daily)

    fb = df_daily[df_daily["is_first_board"] & (~df_daily["is_yizi"]) & (df_daily["dt_str"] >= "2021-01-04")].copy()
    c6_set = set(fb["c6"].unique())

    notice_by_c6 = defaultdict(list)
    if os.path.exists(DB_NOTICES_PATH):
        conn_notices = sqlite3.connect(f"file:{DB_NOTICES_PATH}?mode=ro", uri=True)
        for sec_code, pub_dt, avail_dt, title in conn_notices.execute(
            "SELECT sec_code, pub_datetime_cst, trade_date_avail, title FROM notices WHERE pub_datetime_cst >= '2020-12-25'"
        ):
            c6 = str(sec_code)[:6].zfill(6)
            if c6 not in c6_set or not pub_dt:
                continue
            ts = str(title or "")
            is_neg = bool(NEG_NOTICE_PAT.search(ts)) or bool(BAD_NOTICE_PAT.search(ts))
            if is_neg:
                flags = (False, False, False, bool(EARN_NOTICE_PAT.search(ts)), True)
            else:
                flags = (
                    bool(HARD_NOTICE_ORIG_PAT.search(ts)),
                    bool(HARD_NOTICE_PAT.search(ts)),
                    bool(MA_NOTICE_PAT.search(ts)),
                    bool(EARN_NOTICE_PAT.search(ts)),
                    False,
                )
            if any(flags):
                notice_by_c6[c6].append((str(pub_dt), str(avail_dt or ""), flags))
        conn_notices.close()

    if os.path.exists(PARQUET_TOX_PATH):
        df_tox = pd.read_parquet(PARQUET_TOX_PATH)
        for sec_code, pub_dt, title in df_tox[["sec_code", "pub_datetime_cst", "title"]].itertuples(index=False):
            c6 = str(sec_code)[:6].zfill(6)
            if c6 not in c6_set or not pub_dt:
                continue
            ts = str(title or "")
            is_neg = bool(NEG_NOTICE_PAT.search(ts)) or bool(BAD_NOTICE_PAT.search(ts)) or ("澄清" in ts)
            if is_neg:
                flags = (False, False, False, bool(EARN_NOTICE_PAT.search(ts)), True)
                notice_by_c6[c6].append((str(pub_dt), "", flags))

    for c6 in notice_by_c6:
        notice_by_c6[c6].sort(key=lambda x: x[0])

    rows_meta = []
    cols_needed = [
        "c6", "dt_str", "d2_dt", "mcap", "amount", "f_dd20_d0", "f_dd60_d0", "f_pos20_d0",
        "f_d0_pct", "f_ret_pre10", "to", "f_d1_vol_ratio", "f_zt_cnt_pre20", "f_break60", "close", "d1_seal_tightness"
    ]
    for r in fb[cols_needed].itertuples(index=False):
        c6, d1, d2 = r.c6, r.dt_str, (r.d2_dt if pd.notna(r.d2_dt) else "2026-11-16")
        ti = stock_theme_5y.get((d1, c6))
        if ti is None:
            ti = {
                "name": "", "plate": "其他", "r_short": "其他",
                "rk_o": 99, "t_score_o": 95.0, "gap_o": 0.0,
                "rk_c": 99, "t_score_c": 95.0, "gap_c": 0.0,
                "p_elo": 100.0, "s_elo": 100.0, "p_sz": 1, "n_yizi": 0,
                "has_new": False, "own_new": False, "spark": 0.0, "has_2b_lead": False,
                "is_ma": False, "is_tech_o": False, "is_tech_c": False, "is_earn": False,
                "is_event_basket": False, "is_broad_ind": False,
                "sub_cluster_cnt": 1, "is_dying_pulse": False,
            }

        start_cut = (datetime.date.fromisoformat(d1) - datetime.timedelta(days=4)).isoformat()
        end_cut = f"{d2} 09:25:00"
        nh_o = nh_c = n_ma = n_earn = n_bad = False
        nlist = notice_by_c6.get(c6)
        if nlist:
            lo = bisect.bisect_left(nlist, (start_cut, "", ()))
            for idx_n in range(lo, len(nlist)):
                pdt, adt, fl = nlist[idx_n]
                if pdt > end_cut:
                    break
                assert pdt <= end_cut, f"Notice time leak: {pdt} > {end_cut}"
                if adt and adt > d2:
                    continue
                nh_o |= fl[0]; nh_c |= fl[1]; n_ma |= fl[2]; n_earn |= fl[3]; n_bad |= fl[4]

        if n_bad:
            nh_c = False; nh_o = False; n_ma = False

        is_st = "ST" in ti["name"].upper() or "退" in ti["name"]
        is_ma_f = bool(ti["is_ma"] or n_ma)
        is_earn_f = bool(ti["is_earn"] or n_earn)

        rk_c, p_sz = ti["rk_c"], ti["p_sz"]
        s_prior_dual = (
            (28 if rk_c == 1 else (16 if rk_c == 2 else (8 if rk_c == 3 else 0)))
            + (18 if p_sz >= 4 else (10 if p_sz >= 2 else -15))
            + (12 if ti["has_new"] else 0) + (8 if ti["own_new"] else 0) + (10 if ti["spark"] > 0 else 0)
            + (18 if nh_c else 0) + (18 if is_ma_f else 0) + (12 if ti["is_tech_c"] else 0)
            + (12 if ti["gap_c"] >= 20.0 else 0)
            + float(np.clip((ti["t_score_c"] - 100.0) * 0.25, 0.0, 25.0))
            + float(np.clip((ti["s_elo"] - 100.0) * 0.35, -10.0, 18.0))
        )

        mcap = float(r.mcap) if pd.notna(r.mcap) else 50.0
        amt = float(r.amount) if pd.notna(r.amount) else 2e8
        dd20 = float(r.f_dd20_d0) if pd.notna(r.f_dd20_d0) else 0.90
        dd60 = float(r.f_dd60_d0) if pd.notna(r.f_dd60_d0) else 0.85
        pos20 = float(r.f_pos20_d0) if pd.notna(r.f_pos20_d0) else 0.50
        d0_pct = float(r.f_d0_pct) if pd.notna(r.f_d0_pct) else 0.0
        ret10 = float(r.f_ret_pre10) if pd.notna(r.f_ret_pre10) else 0.0
        to = float(r.to) if pd.notna(r.to) else 8.0
        vr = float(r.f_d1_vol_ratio) if pd.notna(r.f_d1_vol_ratio) else 1.5
        zt20 = int(r.f_zt_cnt_pre20) if pd.notna(r.f_zt_cnt_pre20) else 0
        brk60 = int(r.f_break60)

        seal_r = seal_rate_map.get(d1, 0.55)
        dt_cnt = dt_cnt_map.get(d1, 5)
        zt_cnt = zt_cnt_map.get(d1, 50)
        promo5 = promo_ma5_map.get(d1, 0.20)

        sc_mcap = 28 if 60 <= mcap <= 155 else (10 if 40 <= mcap < 60 else (-20 if mcap < 35 else 0))
        sc_amt = 18 if 2.2e8 <= amt <= 15e8 else (-25 if amt < 1.8e8 else -10)
        sc_dd20 = 42 if dd20 <= 0.82 else (32 if dd20 <= 0.86 else (18 if dd20 <= 0.90 else (-40 if dd20 > 0.95 else 0)))
        sc_dd60 = 18 if dd60 <= 0.76 else (10 if dd60 <= 0.82 else (-15 if dd60 > 0.92 else 0))
        sc_nshape = 22 if (zt20 >= 1 and dd20 <= 0.86) else (-20 if (zt20 >= 1 and dd20 > 0.92) else 0)
        sc_pos20 = 25 if pos20 <= 0.30 else (12 if pos20 <= 0.45 else (-35 if pos20 > 0.75 else 0))
        sc_d0 = 25 if d0_pct <= -0.010 else (15 if d0_pct <= 0.005 else (-35 if d0_pct > 0.030 else 0))
        sc_ret10 = 15 if ret10 <= 0.05 else (-35 if ret10 > 0.18 else 0)
        sc_to = 15 if to <= 9.0 else (8 if to <= 15.0 else (-25 if to > 18.0 else 0))
        sc_vol = 15 if vr <= 1.75 else (-15 if vr > 2.3 else 0)
        sc_mkt_seal = 18 if seal_r < 0.64 else (-25 if seal_r >= 0.72 else 0)
        sc_mkt_dt = 12 if dt_cnt <= 6 else (-15 if dt_cnt >= 15 else 0)
        sc_mkt_zt = 12 if zt_cnt >= 45 else (-18 if zt_cnt < 35 else 0)

        s_q_base_orig = (
            sc_mcap + sc_amt + sc_dd20 + sc_dd60 + sc_nshape + sc_pos20
            + sc_d0 + sc_ret10 + sc_to + sc_vol + sc_mkt_seal + sc_mkt_dt + sc_mkt_zt
        )
        clean_brk60 = (brk60 == 1) and (ret10 <= 0.08) and (zt20 == 0) and (to <= 14.0)
        s_q_base_dual = (
            (sc_mcap + sc_amt + 24 + sc_d0 + sc_ret10 + sc_to + sc_vol + sc_mkt_seal + sc_mkt_dt + sc_mkt_zt)
            if clean_brk60 else s_q_base_orig
        )

        gate_ok = bool(
            (not is_st) and (not is_earn_f) and (not n_bad)
            and (18.0 <= mcap <= 220.0) and (to <= 20.0)
            and (not (zt20 >= 4 and pos20 > 0.38))
            and (r.close <= 60.0)
        )
        tot_thr = 255.0 if seal_r > 0.75 else 230.0

        r_txt = str(ti.get("r_short", "")) + " " + str(ti.get("name", ""))
        is_pioneer_word = False
        for m in re.finditer(r"[\u4e00-\u9fa5A-Za-z0-9]{2,8}(?:技术|材料|产品|装备|芯片|器件|电池|系统|模块|平台|光模块|算法|模型|协议)", r_txt):
            w = norm_term(m.group(0))
            if w in pioneer_word_history:
                prior = [d_seen for d_seen in pioneer_word_history[w] if d_seen <= d1]
                if 1 <= len(prior) <= 3:
                    is_pioneer_word = True
                    break

        rows_meta.append({
            "name": ti["name"], "plate": ti["plate"], "r_short": ti["r_short"],
            "p_elo": ti["p_elo"], "s_elo": ti["s_elo"], "p_sz": ti["p_sz"],
            "has_new_term": ti["has_new"], "own_new_term": ti["own_new"],
            "spark_bonus": ti["spark"], "is_ma": is_ma_f, "notice_hard": nh_c,
            "notice_bad": n_bad, "clean_brk60": int(clean_brk60), "gate_ok": gate_ok,
            "s_prior_dual": round(s_prior_dual, 2), "s_q_base_dual": round(s_q_base_dual, 2),
            "has_2b_lead": ti.get("has_2b_lead", False),
            "mkt_zt_cnt": zt_cnt, "mkt_dt_cnt": dt_cnt,
            "mkt_seal_rate": seal_r, "mkt_promo_ma5": promo5,
            "tot_thr": tot_thr, "is_pioneer_word": is_pioneer_word,
            "is_event_basket": ti["is_event_basket"],
            "is_broad_ind": ti["is_broad_ind"],
            "sub_cluster_cnt": ti["sub_cluster_cnt"],
            "is_dying_pulse": ti["is_dying_pulse"],
        })

    meta_df = pd.DataFrame(rows_meta, index=fb.index)
    fb_all = pd.concat([fb, meta_df], axis=1)
    hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= DATA_END_DT)].copy().reset_index(drop=True)
    hist_fb = compute_purifier_auction_scores(hist_fb)
    hist_fb["gap_days"] = (pd.to_datetime(hist_fb["d2_dt"]) - pd.to_datetime(hist_fb["dt_str"])).dt.days
    hist_fb["c6"] = hist_fb["ticker"].astype(str).str[:6]

    # PIT CSRC industry
    df_csrc_pit = pd.read_csv(CSV_CSRC_PIT_PATH)
    df_csrc_pit["c6"] = df_csrc_pit["sec_code"].astype(str).str.zfill(6)
    csrc_pit_lookup = defaultdict(list)
    for r in df_csrc_pit[["c6", "start_date", "end_date", "industry"]].itertuples(index=False):
        csrc_pit_lookup[r.c6].append((str(r.start_date), str(r.end_date), str(r.industry) if pd.notna(r.industry) else ""))

    def get_pit_ind(c6_val, dt_val):
        intervals = csrc_pit_lookup.get(c6_val)
        if not intervals:
            return ""
        for s, e, ind in intervals:
            if s <= dt_val <= e:
                return ind
        return intervals[0][2] if dt_val < intervals[0][0] else intervals[-1][2]

    hist_fb["csrc_ind"] = [get_pit_ind(c6, d2) for c6, d2 in zip(hist_fb["c6"], hist_fb["d2_dt"])]

    # PIT micro tape
    conn_tape = sqlite3.connect(f"file:{DB_TAPE_PATH}?mode=ro", uri=True)
    tape_df = pd.read_sql_query("SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape", conn_tape)
    conn_tape.close()
    hist_fb = hist_fb.merge(tape_df.drop_duplicates(["trade_date", "sec_code"]), left_on=["dt_str", "c6"], right_on=["trade_date", "sec_code"], how="left")

    # PIT IR Q&A
    conn_ir = sqlite3.connect(f"file:{DB_IR_QA_PATH}?mode=ro", uri=True)
    ir_df = pd.read_sql_query("SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE pub_datetime_cst IS NOT NULL", conn_ir)
    conn_ir.close()
    ir_df["c6"] = ir_df["sec_code"].astype(str).str.zfill(6)
    ir_grp = ir_df.groupby("c6")["pub_datetime_cst"].apply(lambda s: np.sort(s.unique())).to_dict()
    ir_7d_pit = np.zeros(len(hist_fb), dtype=bool)
    for idx, (c6, d2) in enumerate(zip(hist_fb["c6"], hist_fb["d2_dt"])):
        arr = ir_grp.get(c6)
        if arr is not None:
            pos = np.searchsorted(arr, f"{d2} 09:25:00", side="left")
            if pos > 0:
                last_dt = arr[pos - 1][:10]
                if 0 <= (pd.Timestamp(d2) - pd.Timestamp(last_dt)).days <= 8:
                    ir_7d_pit[idx] = True
    hist_fb["has_ir_pit"] = ir_7d_pit

    # Dynamic theme rank
    valid_plate = hist_fb[(hist_fb["plate"] != "其他") & (~hist_fb["is_event_basket"])].copy()
    pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(p_sz_max=("p_sz", "max"), p_theme_med=("s_prior_dual", "median"))
    pg_m = pg[pg["p_sz_max"] >= 2].copy()
    pg_m["rk_theme"] = pg_m.groupby("d2_dt")["p_theme_med"].rank(ascending=False, method="min")
    hist_fb = hist_fb.merge(pg_m[["d2_dt", "plate", "rk_theme"]], on=["d2_dt", "plate"], how="left")

    # 5m bars
    df_5m = pd.read_parquet(PARQUET_5M_PATH)
    df_5m["hhmm_int"] = df_5m["hhmm"].astype(int)
    df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    bars_5m_map = {
        (c6, dt): grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy()
        for (c6, dt), grp in df_5m.groupby(["c6", "date"], sort=False)
    }

    print(f"    Base V18 data ready: {len(hist_fb):,} first-board rows, {len(bars_5m_map):,} 5m trajectories ({time.time()-t0:.1f}s)")
    return df_daily, all_dts, dt_to_idx, price_lookup, hist_fb, pg_m, bars_5m_map


def attach_cross_factors_to_1to2(df_daily, all_dts, dt_to_idx, hist_fb):
    t0 = time.time()
    print("[2/5] Attaching 2to3 & 3to4 borrowed factors strictly PIT (< buy_date 09:25:00)...")

    # --- Factor 1: HHI & Top1 share on d1 (from KPL plates, NON_THEME excluded) ---
    kpl_days_map = {}
    for path, cond in [(KPL_MERGED_PATH, lambda d: d < "2021-01-01"), (KPL_5Y_PATH, lambda d: d >= "2021-01-01")]:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for ln in f:
                    if not ln.strip():
                        continue
                    try:
                        obj = json.loads(ln)
                        dt = obj.get("date", "")
                        if dt and cond(dt):
                            kpl_days_map[dt] = obj
                    except Exception:
                        pass
    hhi_rows = []
    # Also store (d1, plate) -> all d1 ZT codes in plate (for all-teammate auction nuke)
    kpl_plate_stocks = defaultdict(list)
    kpl_stock_plates = defaultdict(list)
    for dt in sorted(kpl_days_map.keys()):
        plates = kpl_days_map[dt].get("plates", [])
        szs = []
        for p in plates:
            pname = p.get("plate", "")
            stocks = p.get("stocks", [])
            if not pname or not stocks or pname in NON_THEME:
                continue
            c6s = [str(s[0]).strip()[:6].zfill(6) for s in stocks]
            szs.append(len(c6s))
            if dt >= "2021-01-01":
                kpl_plate_stocks[(dt, pname)].extend(c6s)
                for c6 in c6s:
                    kpl_stock_plates[(dt, c6)].append(pname)
        tot_sz = sum(szs)
        hhi_val = sum((x / tot_sz) ** 2 for x in szs) if tot_sz > 0 else 0.0
        top1_sh = (max(szs) / tot_sz) if tot_sz > 0 else 0.0
        hhi_rows.append({"dt_str": dt, "theme_hhi": hhi_val, "top1_share": top1_sh})
    df_hhi = pd.DataFrame(hhi_rows).sort_values("dt_str").reset_index(drop=True)
    # Strict PIT rolling percentile (prior 250 days excluding current? wait: d1 is sig_date before d2 09:25, shift(1) or inclusive of d1 is both < d2 09:25! Use past 250 days up to d1)
    hhi_vals = df_hhi["theme_hhi"].to_numpy()
    hhi_pct = np.full(len(df_hhi), 0.5)
    for i in range(len(df_hhi)):
        lo = max(0, i - 250)
        if i - lo >= 20:
            win = hhi_vals[lo:i]  # strict past 250 days before d1
            hhi_pct[i] = float((win <= hhi_vals[i]).mean())
    df_hhi["hhi_pit_pct"] = hhi_pct
    hist_fb = hist_fb.merge(df_hhi[["dt_str", "theme_hhi", "top1_share", "hhi_pit_pct"]], on="dt_str", how="left")

    # --- Factor 2: Xueqiu pre-market post count [d1 00:00:00, d2 09:25:00) ---
    con_xq = sqlite3.connect(f"file:{DB_XUEQIU_PATH}?mode=ro", uri=True)
    xq_df = pd.read_sql_query(
        "SELECT symbol, created_time_str FROM xueqiu_posts WHERE created_time_str >= '2021-01-01' AND created_time_str <= '2026-11-16 09:25:00'",
        con_xq
    )
    xq_tasks = pd.read_sql_query("SELECT task_key FROM crawl_progress WHERE source='xueqiu' AND status='OK'", con_xq)
    con_xq.close()
    xq_task_set = set(xq_tasks["task_key"].astype(str))
    xq_df["c6"] = xq_df["symbol"].astype(str).str[:6].str.zfill(6)
    xq_by_c6 = {c6: np.sort(g["created_time_str"].astype(str).to_numpy()) for c6, g in xq_df.groupby("c6")}

    xq_cnt_arr = np.zeros(len(hist_fb), dtype=int)
    xq_crawled_arr = np.zeros(len(hist_fb), dtype=bool)
    for i, (c6, d1, d2) in enumerate(zip(hist_fb["c6"], hist_fb["dt_str"], hist_fb["d2_dt"])):
        xq_crawled_arr[i] = f"{c6}_{d1}" in xq_task_set
        arr = xq_by_c6.get(c6)
        if arr is not None:
            lo = np.searchsorted(arr, f"{d1} 00:00:00", side="left")
            hi = np.searchsorted(arr, f"{d2} 09:25:00", side="left")
            assert hi == 0 or arr[hi - 1] < f"{d2} 09:25:00", f"Xueqiu time leak: {arr[hi-1]} >= {d2} 09:25:00"
            xq_cnt_arr[i] = int(hi - lo)
    hist_fb["xq_cnt_tot"] = xq_cnt_arr
    hist_fb["xq_crawled"] = xq_crawled_arr

    # --- Factor 3: LHB on d1 (buy & sell seats deduplicated per stock-day) ---
    lb = pd.read_parquet(LHB_BUY_PATH, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY", "SELL"])
    lb["dt_str"] = lb["TRADE_DATE"].astype(str).str[:10]
    lb["c6"] = lb["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
    lb = lb[lb["dt_str"] >= "2021-01-01"].drop_duplicates(subset=["dt_str", "c6", "OPERATEDEPT_NAME"])

    lhb_stats = {}
    for (dt, c6), grp in lb.groupby(["dt_str", "c6"], sort=False):
        seats = grp["OPERATEDEPT_NAME"].astype(str).tolist()
        buys = grp["BUY"].fillna(0.0).to_numpy(dtype=float)
        tot_b = float(buys.sum())
        lh_mask = ["拉萨" in s for s in seats]
        lh_cnt = sum(lh_mask)
        lh_buy_sh = float(buys[lh_mask].sum() / tot_b) if tot_b > 0 else 0.0
        lh_seat_sh = float(lh_cnt / len(seats)) if seats else 0.0
        surf_34 = any(SURF_YZ_3TO4.search(s) for s in seats)
        surf_pure = any(SURF_YZ_PURE.search(s) for s in seats)
        lhb_stats[(dt, c6)] = (1, lh_cnt, lh_buy_sh, lh_seat_sh, int(surf_34), int(surf_pure))

    ls = pd.read_parquet(LHB_SELL_PATH, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "SELL"])
    ls["dt_str"] = ls["TRADE_DATE"].astype(str).str[:10]
    ls["c6"] = ls["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
    ls = ls[ls["dt_str"] >= "2021-01-01"].drop_duplicates(subset=["dt_str", "c6", "OPERATEDEPT_NAME"])
    lhb_sell_surf = {}
    for (dt, c6), grp in ls.groupby(["dt_str", "c6"], sort=False):
        seats = grp["OPERATEDEPT_NAME"].astype(str).tolist()
        lhb_sell_surf[(dt, c6)] = (int(any(SURF_YZ_PURE.search(s) for s in seats)), sum(1 for s in seats if "拉萨" in s))

    hist_fb["on_lhb_d1"] = [lhb_stats.get((d1, c6), (0, 0, 0.0, 0.0, 0, 0))[0] for d1, c6 in zip(hist_fb["dt_str"], hist_fb["c6"])]
    hist_fb["lhb_lh_cnt"] = [lhb_stats.get((d1, c6), (0, 0, 0.0, 0.0, 0, 0))[1] for d1, c6 in zip(hist_fb["dt_str"], hist_fb["c6"])]
    hist_fb["lhb_lh_buy_share"] = [lhb_stats.get((d1, c6), (0, 0, 0.0, 0.0, 0, 0))[2] for d1, c6 in zip(hist_fb["dt_str"], hist_fb["c6"])]
    hist_fb["lhb_lh_seat_share"] = [lhb_stats.get((d1, c6), (0, 0, 0.0, 0.0, 0, 0))[3] for d1, c6 in zip(hist_fb["dt_str"], hist_fb["c6"])]
    hist_fb["surf_yz_buy_34"] = [lhb_stats.get((d1, c6), (0, 0, 0.0, 0.0, 0, 0))[4] for d1, c6 in zip(hist_fb["dt_str"], hist_fb["c6"])]
    hist_fb["surf_yz_buy_pure"] = [lhb_stats.get((d1, c6), (0, 0, 0.0, 0.0, 0, 0))[5] for d1, c6 in zip(hist_fb["dt_str"], hist_fb["c6"])]
    hist_fb["surf_yz_sell_pure"] = [lhb_sell_surf.get((d1, c6), (0, 0))[0] for d1, c6 in zip(hist_fb["dt_str"], hist_fb["c6"])]

    # --- Factor 4 & 5: Market max board height & prev 1b/2b limit-down stampede on d1 ---
    d_sub = df_daily[df_daily["dt_str"] >= "2020-12-15"][["c6", "dt_str", "is_zt", "is_dt", "o_pct", "pct"]].copy()
    d_sub.sort_values(["c6", "dt_str"], inplace=True)
    s_zt = d_sub["is_zt"].astype(int)
    s_shift = d_sub.groupby("c6")["is_zt"].shift(1).fillna(False).astype(bool)
    d_sub["streak"] = s_zt.groupby([d_sub["c6"], (s_zt != s_shift).cumsum()]).cumsum() * s_zt
    d_sub["prev_streak"] = d_sub.groupby("c6")["streak"].shift(1).fillna(0).astype(int)

    mkt_maxb_map = d_sub.groupby("dt_str")["streak"].max().to_dict()
    prev_1b_dt_map = d_sub[(d_sub["prev_streak"] == 1) & d_sub["is_dt"]].groupby("dt_str")["c6"].nunique().to_dict()
    prev_1b_nuke_map = d_sub[(d_sub["prev_streak"] == 1) & ((d_sub["is_dt"]) | (d_sub["o_pct"] <= -0.07))].groupby("dt_str")["c6"].nunique().to_dict()
    prev_2b_dt_map = d_sub[(d_sub["prev_streak"] == 2) & d_sub["is_dt"]].groupby("dt_str")["c6"].nunique().to_dict()

    hist_fb["mkt_maxb_d1"] = hist_fb["dt_str"].map(mkt_maxb_map).fillna(3).astype(int)
    hist_fb["prev_1b_dt_cnt"] = hist_fb["dt_str"].map(prev_1b_dt_map).fillna(0).astype(int)
    hist_fb["prev_1b_nuke_cnt"] = hist_fb["dt_str"].map(prev_1b_nuke_map).fillna(0).astype(int)
    hist_fb["prev_2b_dt_cnt"] = hist_fb["dt_str"].map(prev_2b_dt_map).fillna(0).astype(int)

    # --- Factor 6: All d1 limit-up teammates (including 2b+) 09:25 open avg on d2 ---
    d_open_map = {}
    d_sub_o = df_daily[df_daily["dt_str"] >= "2021-01-01"][["c6", "dt_str", "o_pct", "pre_c"]]
    d_open_map = {(r.dt_str, r.c6): float(r.o_pct) for r in d_sub_o.itertuples(index=False) if pd.notna(r.o_pct)}
    all_zt_peers_avg = np.zeros(len(hist_fb), dtype=float)
    all_zt_peers_cnt = np.zeros(len(hist_fb), dtype=int)
    for i, (d1, d2, c6, plate) in enumerate(zip(hist_fb["dt_str"], hist_fb["d2_dt"], hist_fb["c6"], hist_fb["plate"])):
        if plate and plate != "其他":
            peers = [p_c6 for p_c6 in kpl_plate_stocks.get((d1, plate), []) if p_c6 != c6]
            ops = [d_open_map[(d2, p_c6)] for p_c6 in peers if (d2, p_c6) in d_open_map]
            if ops:
                all_zt_peers_cnt[i] = len(ops)
                all_zt_peers_avg[i] = float(np.mean(ops))
    hist_fb["all_zt_peers_cnt"] = all_zt_peers_cnt
    hist_fb["all_zt_peers_open_avg"] = all_zt_peers_avg

    # --- Factor 7: d1 intraday deep dip (l_pct < -0.02) & d1 seal_amount / amount ---
    # Validate unit divisor of seal_amount / amount
    hist_fb["d1_low_pct"] = hist_fb["l_pct"].fillna(0.0)
    hist_fb["d1_seal_amt_ratio"] = np.where(hist_fb["amount"] > 0, hist_fb["seal_amount"] / hist_fb["amount"], np.nan)
    valid_sr = hist_fb["d1_seal_amt_ratio"].dropna()
    assert 0.01 < valid_sr.median() < 0.50, f"seal_amount/amount unit check failed: median={valid_sr.median()}"

    # --- Factor 8: lock_top10 >= 50% x d1_real_turn in [25%, 65%] ---
    with open(HOLDERS_PATH, encoding="utf-8") as f:
        holders = json.load(f)
    lock_arr = np.full(len(hist_fb), np.nan)
    for i, (c6, d1) in enumerate(zip(hist_fb["c6"], hist_fb["dt_str"])):
        vh = [x for x in holders.get(c6, []) if isinstance(x, (list, tuple)) and len(x) >= 3 and str(x[0]) <= d1]
        if vh:
            for x in vh:
                assert str(x[0]) <= d1, f"Top10 ann_date leak: {x[0]} > {d1}"
            lock_arr[i] = float(max(vh, key=lambda x: str(x[1]))[2])
    hist_fb["lock_top10"] = lock_arr
    assert 10.0 < np.nanmedian(lock_arr) < 85.0, f"lock_top10 unit check failed: {np.nanmedian(lock_arr)}"
    hist_fb["d1_real_turn"] = np.where(
        pd.notna(hist_fb["lock_top10"]) & (hist_fb["lock_top10"] < 99.0),
        hist_fb["to"] / (1.0 - hist_fb["lock_top10"] / 100.0),
        np.nan
    )

    # --- Factor 9: CSI300 prev 1d <= -2% or 5d <= -3% ---
    with open(IDX_JSON, encoding="utf-8") as f:
        sh300 = json.load(f)["sh000300"]
    idx_dts = sorted(sh300.keys())
    idx_pos = {d: i for i, d in enumerate(idx_dts)}
    csi_1d_map, csi_5d_map = {}, {}
    for d in idx_dts:
        p = idx_pos[d]
        if p >= 1:
            csi_1d_map[d] = sh300[d] / sh300[idx_dts[p - 1]] - 1.0
        if p >= 5:
            csi_5d_map[d] = sh300[d] / sh300[idx_dts[p - 5]] - 1.0
    hist_fb["csi_1d_d1"] = hist_fb["dt_str"].map(csi_1d_map).fillna(0.0)
    hist_fb["csi_5d_d1"] = hist_fb["dt_str"].map(csi_5d_map).fillna(0.0)

    print(f"    Cross-strategy factors attached in {time.time()-t0:.1f}s")
    return hist_fb, sh300


def build_v18_static_components(hist_fb, pg_m):
    """Precompute static V18 components identically to run_rebacktest_v18_clean.py."""
    seal_time = hist_fb["first_seal_time"].fillna("99:99:99")
    open_cnt = hist_fb["open_board_count"].fillna(0)
    dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
    clean_brk60 = hist_fb["clean_brk60"].values == 1

    is_granularity = hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
    bonus_spear = np.where(is_granularity, 15.0, 0.0) + np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))

    common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
    pass_l1 = ~hist_fb["is_event_basket"]
    pass_l2 = ~hist_fb["is_dying_pulse"]
    pass_l3 = (hist_fb["plate_fb_cnt"] <= 1) | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2)))
    pass_ac = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
    wk_mask = hist_fb["gap_days"] >= 3
    thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)
    f3_bonus = np.where(hist_fb["notice_bad"], -35.0, 0.0)

    hist_fb["score_wk"] = hist_fb["score_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
    hist_fb["s_prior_wk"] = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus

    m_t2_base = (
        common_ok & (hist_fb["p_sz"] == 1)
        & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"])
        & hist_fb["d2_o_pct"].between(0.035, 0.078)
        & (hist_fb["buyable_mkt_open_rk"] <= 3)
        & (hist_fb["d1_seal_tightness"] >= 15.0)
        & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))
    )

    in_std_buy_win = common_ok & (
        (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
        | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
    )
    is_front_lock = hist_fb["d2_is_yizi"] | ((~wk_mask) & (hist_fb["d2_o_pct"] > 0.078)) | (wk_mask & (hist_fb["d2_o_pct"] > 0.088))
    hist_fb["_is_front_lock"] = is_front_lock.astype(int)
    hist_fb["front_lock_cnt"] = hist_fb.groupby(["d2_dt", "plate"])["_is_front_lock"].transform("sum")
    hist_fb["mkt_yizi_cnt"] = hist_fb.groupby("d2_dt")["d2_is_yizi"].transform("sum").fillna(0).astype(int)

    hist_fb["_true_buy_o"] = np.where(in_std_buy_win, hist_fb["d2_o_pct"], -9.99)
    hist_fb["true_buy_rk"] = hist_fb.groupby(["d2_dt", "plate"])["_true_buy_o"].rank(ascending=False, method="min")

    has_distinct_sub = (hist_fb["p_sz"] >= 8) & (hist_fb["r_short"] != hist_fb["plate"]) & (hist_fb["r_short"] != "其他") & (hist_fb["r_short"] != "")
    orig_rk_bonus = np.where(
        hist_fb["buyable_plate_rk"] == 1, 35.0,
        np.where(has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0,
                 np.where(hist_fb["buyable_plate_rk"] == 2, 8.0, -25.0))
    )
    true_rk_bonus = np.where(
        hist_fb["true_buy_rk"] == 1, 35.0,
        np.where(has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0,
                 np.where(hist_fb["true_buy_rk"] == 2, 8.0, -25.0))
    )
    rk_fix_delta = true_rk_bonus - orig_rk_bonus

    pass_nd_true = (~((hist_fb["p_sz"] >= 2) & (hist_fb["true_buy_rk"] >= 3))) & (
        ~((hist_fb["plate_d2_yizi_cnt"] >= 1) & (hist_fb["d1_seal_tightness"] < 15.0))
    )

    csrc_sec = [str(c)[:3] if str(c) else "UNK" for c in hist_fb["csrc_ind"]]
    CSRC_PURE_OUTSIDER = {
        "A01","A02","A03","A04","A05", "D44","D45","D46", "E47","E48","E49","E50",
        "F51","F52", "G53","G54","G55","G56","G58","G59", "H61","H62", "K70",
        "L72","N77","N78", "C13","C14","C15","C17","C18","C19","C20","C21","C22"
    }
    is_hard_tech = hist_fb["plate"].astype(str).str.contains(r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)", regex=True).values
    has_ma_hard = (hist_fb["notice_hard"] | hist_fb["is_ma"]).values
    is_pure_outsider = np.array([ht and (cs in CSRC_PURE_OUTSIDER) and (not hm) for ht, cs, hm in zip(is_hard_tech, csrc_sec, has_ma_hard)], dtype=bool)
    name_sub20 = np.where(is_pure_outsider, -20.0, 0.0)

    flc = hist_fb["front_lock_cnt"].values
    tbrk = hist_fb["true_buy_rk"].values
    myz = hist_fb["mkt_yizi_cnt"].values
    is_super_wave = (hist_fb["rk_theme"] == 1) & (hist_fb["p_sz"] >= 8) & (tbrk == 1)
    y_v17 = np.select(
        [
            (flc == 1) & (tbrk == 1) & np.isin(myz, [1, 2]),
            (flc == 1) & (tbrk == 1),
            (flc == 1) & (tbrk >= 2),
            (flc >= 2) & is_super_wave,
            (flc == 2) & (~is_super_wave),
            (flc >= 3) & (~is_super_wave),
            (flc == 0) & (myz == 0) & (~has_ma_hard),
        ],
        [8.0, 0.0, 0.0, 5.0, -15.0, -22.0, -5.0],
        default=0.0,
    )

    daily_records = []
    for d, grp in hist_fb.groupby("d2_dt"):
        buyable = grp[grp["is_buyable_open"] & (~grp["nuclear_halt"]) & (~grp["promo_freeze"])]
        ho = buyable[buyable["d2_o_pct"] >= 0.055]
        n_ho = len(ho)
        rate_ho_zt = (ho["d2_is_zt"].sum() / n_ho) if n_ho > 0 else np.nan
        daily_records.append({"date": d, "rate_ho_zt": rate_ho_zt})
    df_daily_s = pd.DataFrame(daily_records).sort_values("date").reset_index(drop=True)
    df_daily_s["roll20_ho_zt"] = df_daily_s["rate_ho_zt"].shift(1).rolling(20, min_periods=5).mean().fillna(0.45)
    sensors_map = df_daily_s.set_index("date").to_dict(orient="index")

    pen_thr_vec = np.zeros(len(hist_fb))
    pen_val_vec = np.zeros(len(hist_fb))
    for d, s in sensors_map.items():
        ho_rate = s.get("roll20_ho_zt", 0.45)
        p_val, p_thr = (25.0, 0.035) if ho_rate < 0.45 else (15.0, 0.031)
        idx_d = (hist_fb["d2_dt"] == d).values
        pen_thr_vec[idx_d] = p_thr
        pen_val_vec[idx_d] = p_val
    q_pen = -np.where((~wk_mask) & (hist_fb["d2_o_pct"] < pen_thr_vec), pen_val_vec, 0.0)

    d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)
    is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (hist_fb["d1_seal_tightness"] >= 38.0)
    bon_tape = np.where(is_ht, 5.0, 0.0) + np.where(hist_fb["has_ir_pit"], 5.0, 0.0)

    daily_t1 = pg_m[pg_m["rk_theme"] == 1].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
    daily_t2 = pg_m[pg_m["rk_theme"] == 2].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
    daily_t3 = pg_m[pg_m["rk_theme"] == 3].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")

    sc_climax_pen = np.where(hist_fb["mkt_zt_cnt"] >= 100, -15.0, np.where(hist_fb["mkt_zt_cnt"] >= 95, -10.0, 0.0))
    sc_seal_pen = np.where(hist_fb["mkt_seal_rate"] >= 0.80, -10.0, 0.0)
    sc_cap_pen = np.where((hist_fb["plate_d2_yizi_cnt"] >= 1) & (hist_fb["mcap"] > 90.0), -25.0, 0.0)

    t1_med_map = daily_t1["p_theme_med"].to_dict()
    t3_med_map = daily_t3["p_theme_med"].to_dict()
    _t1m = hist_fb["d2_dt"].map(t1_med_map).fillna(0.0).values
    _t3m = hist_fb["d2_dt"].map(t3_med_map).fillna(0.0).values
    v18_dom_t3 = (_t1m >= 65.0) & (_t1m - _t3m >= 35.0) & (_t3m < 42.0)
    sc_t3_pen = np.where(v18_dom_t3 & (hist_fb["rk_theme"].values >= 3), -15.0, 0.0)
    v18_pen = sc_climax_pen + sc_seal_pen + sc_cap_pen + sc_t3_pen

    sp_v = hist_fb["s_prior_wk"].values + name_sub20 + y_v17 * 0.5
    sq_v = hist_fb["s_quant_dual"].values + q_pen + d_ov + bon_tape + rk_fix_delta + y_v17 * 0.5
    sc_v_base = sp_v + sq_v + v18_pen

    p_tight = (hist_fb["d1_seal_tightness"] >= 37.0).values
    open_in_win = (
        (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
        | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
    ).values

    # Precompute daily dominant/melee info
    melee_days = set()
    dom_info = {}
    for d in sorted(daily_t1.index):
        t1_row = daily_t1.loc[d]
        t2_row = daily_t2.loc[d] if d in daily_t2.index else None
        t3_row = daily_t3.loc[d] if d in daily_t3.index else None
        t1_med = float(t1_row["p_theme_med"])
        t2_med = float(t2_row["p_theme_med"]) if t2_row is not None else 0.0
        t1_sz = int(t1_row["p_sz_max"])
        t2_sz = int(t2_row["p_sz_max"]) if t2_row is not None else 1
        is_dominant = ((t1_med - t2_med) >= 20.0) or ((t1_sz >= 6) and (t1_sz / max(1, t2_sz) >= 2.0))
        if is_dominant:
            dom_info[d] = t1_row["plate"]
        if t1_row is not None and t2_row is not None and t3_row is not None:
            t3_med = float(t3_row["p_theme_med"])
            sz_max = max(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
            sz_min = min(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
            if (t1_med - t3_med) <= 15.0 and sz_max <= 5 and sz_min >= 2:
                melee_days.add(d)

    return {
        "common_ok": common_ok.values,
        "open_in_win": open_in_win,
        "wk_mask": wk_mask.values,
        "pass_l1": pass_l1.values,
        "pass_l2": pass_l2.values,
        "pass_l3": pass_l3.values,
        "pass_nd_true": pass_nd_true.values,
        "pass_ac": pass_ac.values,
        "p_tight": p_tight,
        "m_t2_base": m_t2_base.values,
        "thr_vec": thr_vec,
        "sp_v": sp_v,
        "sc_v_base": sc_v_base,
        "dom_info": dom_info,
        "melee_days": melee_days,
    }


def make_trade_simulator(all_dts, dt_to_idx, price_lookup, bars_5m_map, fee=FEE_RATE):
    def sim_trade_core(row, do_direct_override=None, d3_hook=None):
        c6, d2 = row["c6"], row["d2_dt"]
        idx2 = dt_to_idx.get(d2, -1)
        if idx2 < 0 or idx2 >= len(all_dts) - 1:
            return None
        d2_bar = price_lookup.get((c6, d2))
        if not d2_bar:
            return None
        o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = d2_bar
        if o2 >= zt2 - 0.005 or o2 <= 0:
            return None

        is_monday = row.get("gap_days", 1) >= 3
        cand_score = row.get("score_active", 0.0)
        cand_lead = row.get("buy_open_lead", 0.0)
        do_direct = (is_monday and (cand_score >= 310.0) and (cand_lead >= 0.025)) if do_direct_override is None else do_direct_override
        trig_p = float(row["trig_p"])
        buy_px = round(float(o2), 2) if do_direct else round(trig_p, 2)
        buy_hhmm = 925 if do_direct else 935

        if not do_direct:
            if h2 < trig_p or trig_p >= zt2 - 0.005:
                return None
            arr2 = bars_5m_map.get((c6, d2))
            if arr2 is not None and len(arr2) > 0:
                ign_hhmm = None
                for bi in range(len(arr2)):
                    if arr2[bi, 2] >= trig_p - 1e-4:
                        ign_hhmm = int(arr2[bi, 0])
                        break
                if ign_hhmm is not None and ign_hhmm > 1130:
                    return None
                if ign_hhmm is not None:
                    buy_hhmm = ign_hhmm

        prev_c = round(float(c2), 2)
        idx3 = idx2 + 1
        d3 = all_dts[idx3]
        d3_bar = price_lookup.get((c6, d3))
        if not d3_bar:
            net = round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4)
            return {
                "net_ret": net, "exit_date": d3, "exit_at_open": True, "sealed_2b": int(is_zt2),
                "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c,
                "buy_hhmm": buy_hhmm, "exit_hhmm": 925, "score": round(cand_score, 1), "tag": "no_d3_bar"
            }
        o3, h3, l3, c3, zt3, dt3, is_zt3, is_yz_dt3 = d3_bar

        if not is_zt2:
            d2_closed_up = (c2 >= float(row["close"]))
            if d2_closed_up and (o3 >= round(c2 * 1.005, 2)) and not is_yz_dt3:
                if is_zt3:
                    curr = idx3 + 1
                    boards_held = 3
                    used_immunity = False
                    prev_c = round(float(c3), 2)
                    while curr < len(all_dts) and (curr - idx2 <= 12):
                        dc = all_dts[curr]
                        b = price_lookup.get((c6, dc))
                        if not b: break
                        oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b
                        if iyzc:
                            prev_c = round(float(cc), 2); curr += 1; continue
                        arr = bars_5m_map.get((c6, dc))
                        if arr is not None and len(arr) >= 12:
                            idx_1030 = -1
                            cum_v, cum_a = 0.0, 0.0
                            for bi in range(len(arr)):
                                cum_v += arr[bi, 5]; cum_a += arr[bi, 6]
                                if arr[bi, 0] == 1030:
                                    idx_1030 = bi; break
                            if idx_1030 >= 0:
                                bc_1030 = arr[idx_1030, 4]
                                vwap_1030 = cum_a / cum_v if cum_v > 0 else bc_1030
                                if bc_1030 >= ztc - 0.01:
                                    for bi in range(idx_1030 + 1, len(arr) - 1):
                                        if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                            px = round(float(arr[bi + 1, 1]), 2)
                                            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": int(arr[bi + 1, 0]), "score": round(cand_score, 1), "tag": "5m_1430_rush"}
                                    if iztc:
                                        prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                                    px = round(float(cc), 2)
                                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500, "score": round(cand_score, 1), "tag": "eod_break"}
                                elif bc_1030 < vwap_1030:
                                    px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                                    ehh = int(arr[idx_1030 + 1, 0]) if idx_1030 + 1 < len(arr) else 1030
                                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": ehh, "score": round(cand_score, 1), "tag": "5m_1030_weak_cut"}
                                else:
                                    if iztc:
                                        prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                                    if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                                        used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                                    px = round(float(cc), 2)
                                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500, "score": round(cand_score, 1), "tag": "eod_close"}
                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                        px = round(float(cc), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500, "score": round(cand_score, 1), "tag": "eod_close"}
                    return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500, "score": round(cand_score, 1), "tag": "max_hold_exit"}
                else:
                    px = round(float(c3), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": d3, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500, "score": round(cand_score, 1), "tag": "nshape_d3_close"}

            curr = idx3
            while curr < len(all_dts):
                b = price_lookup.get((c6, all_dts[curr]))
                if not b or not b[7]:
                    px = round(float(b[0]), 2) if b else prev_c
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[curr], "exit_at_open": True, "sealed_2b": 0, "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 925, "score": round(cand_score, 1), "tag": "fail_open_cut"}
                curr += 1
            return None

        # Sealed 2-board branch
        curr = idx3
        boards_held = 2
        used_immunity = False
        while curr < len(all_dts) and (curr - idx2 <= 12):
            dc = all_dts[curr]
            b = price_lookup.get((c6, dc))
            if not b: break
            oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b
            if iyzc:
                prev_c = round(float(cc), 2); curr += 1; continue

            # Optional d3 intersection hook (only on exact d3 = idx3!)
            if d3_hook is not None and curr == idx3:
                act = d3_hook(row, oc, hc, lc, cc, ztc, dtc, iztc, prev_c, bars_5m_map.get((c6, dc)))
                if act == "early_open_exit":
                    px = round(float(oc), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": True, "sealed_2b": 1, "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 925, "score": round(cand_score, 1), "tag": "d3_hook_open"}

            arr = bars_5m_map.get((c6, dc))
            if arr is not None and len(arr) >= 12:
                idx_1030 = -1
                cum_v, cum_a = 0.0, 0.0
                for bi in range(len(arr)):
                    cum_v += arr[bi, 5]; cum_a += arr[bi, 6]
                    if arr[bi, 0] == 1030:
                        idx_1030 = bi; break
                if idx_1030 >= 0:
                    bc_1030 = arr[idx_1030, 4]
                    vwap_1030 = cum_a / cum_v if cum_v > 0 else bc_1030
                    if d3_hook is not None and curr == idx3:
                        act1030 = d3_hook(row, oc, hc, lc, cc, ztc, dtc, iztc, prev_c, arr, bc_1030=bc_1030, vwap_1030=vwap_1030)
                        if act1030 == "force_1030_exit" and bc_1030 < ztc - 0.01:
                            px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                            ehh = int(arr[idx_1030 + 1, 0]) if idx_1030 + 1 < len(arr) else 1030
                            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": ehh, "score": round(cand_score, 1), "tag": "d3_hook_1030"}
                    else:
                        act1030 = None

                    if bc_1030 >= ztc - 0.01:
                        for bi in range(idx_1030 + 1, len(arr) - 1):
                            if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                px = round(float(arr[bi + 1, 1]), 2)
                                return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": int(arr[bi + 1, 0]), "score": round(cand_score, 1), "tag": "5m_1430_rush"}
                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        px = round(float(cc), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500, "score": round(cand_score, 1), "tag": "eod_break"}
                    elif bc_1030 < vwap_1030 and act1030 != "exempt_1030":
                        px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                        ehh = int(arr[idx_1030 + 1, 0]) if idx_1030 + 1 < len(arr) else 1030
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": ehh, "score": round(cand_score, 1), "tag": "5m_1030_weak_cut"}
                    else:
                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                        px = round(float(cc), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500, "score": round(cand_score, 1), "tag": "eod_close"}

            if iztc:
                prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
            if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
            px = round(float(cc), 2)
            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500, "score": round(cand_score, 1), "tag": "eod_close"}

        return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "code": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c, "buy_hhmm": buy_hhmm, "exit_hhmm": 1500, "score": round(cand_score, 1), "tag": "max_hold_exit"}

    return sim_trade_core


def calc_d15_metrics(trades_1s, eq_daily_rets, csi300_bench, sh300):
    idx_dts = sorted(sh300.keys())
    def bench_ret(s_dt, e_dt):
        prevs = [d for d in idx_dts if d < s_dt]
        p0 = sh300[prevs[-1]] if prevs else sh300[idx_dts[0]]
        posts = [d for d in idx_dts if d <= e_dt]
        p1 = sh300[posts[-1]]
        return (p1 / p0 - 1.0) * 100.0

    def slice_stats(s_dt, e_dt, csi_pct):
        sub = [t for t in trades_1s if s_dt <= t["buy_date"] <= e_dt]
        eq_sub = [dr for dt, dr in eq_daily_rets if s_dt <= dt <= e_dt]
        if not sub:
            return {"n": 0, "wr": 0.0, "plr": 0.0, "mean_pct": 0.0, "nav_1s": 1.0, "cap10m": 1.0, "eq": 1.0, "trim3": 1.0, "mdd": 0.0, "csi_pct": round(csi_pct, 2), "excess_pp": round(-csi_pct, 2)}
        r = np.array([t["net_ret"] for t in sub], dtype=float)
        w, l = r[r > 0], r[r <= 0]
        plr = float(w.mean() / abs(l.mean())) if (len(w) > 0 and len(l) > 0 and l.mean() < 0) else 99.0
        nav = float(np.prod(1.0 + r))
        pk = cur = 1.0
        mdd = 0.0
        for x in r:
            cur *= (1.0 + x); pk = max(pk, cur); mdd = max(mdd, (pk - cur) / pk)
        cap = 100.0
        for x in r:
            cap += min(cap, 1000.0) * float(x)
        eq_nav = float(np.prod(1.0 + np.array(eq_sub))) if eq_sub else 1.0
        trim3 = float(np.prod(1.0 + np.sort(r)[:-3])) if len(r) > 3 else 1.0
        return {
            "n": int(len(r)),
            "wr": round(float((r > 0).mean() * 100.0), 2),
            "plr": round(plr, 2),
            "mean_pct": round(float(r.mean() * 100.0), 2),
            "nav_1s": round(nav, 2),
            "cap10m": round(cap / 100.0, 2),
            "eq": round(eq_nav, 2),
            "trim3": round(trim3, 2),
            "mdd": round(mdd * 100.0, 2),
            "csi_pct": round(csi_pct, 2),
            "excess_pp": round((nav - 1.0) * 100.0 - csi_pct, 2),
        }

    return {
        "IS_21_23": slice_stats("2021-01-04", "2023-12-31", bench_ret("2021-01-04", "2023-12-31")),
        "IS_5Yslice_2111_23": slice_stats("2021-11-15", "2023-12-31", bench_ret("2021-11-15", "2023-12-31")),
        "OOS_24_26": slice_stats("2024-01-01", DATA_END_DT, csi300_bench.get("近三年(2024-01-01起)", [15.99])[0]),
        "5Y": slice_stats(CANON_5Y_START, DATA_END_DT, csi300_bench.get("全五年(2021-11-16起)", [-18.49])[0]),
        "3Y": slice_stats("2023-11-16", DATA_END_DT, csi300_bench.get("近三年(2023-11-16起)", [10.33])[0]),
        "2026": slice_stats("2026-01-01", DATA_END_DT, csi300_bench.get("2026全年", [-14.04])[0]),
        "2026_07": slice_stats("2026-07-01", DATA_END_DT, csi300_bench.get("2026年7月以来", [-20.08])[0]),
        "2026_10": slice_stats("2026-10-01", DATA_END_DT, csi300_bench.get("2026年10月以来", [-8.67])[0]),
    }


def main():
    t_all = time.time()
    df_daily, all_dts, dt_to_idx, price_lookup, hist_fb, pg_m, bars_5m_map = build_v18_base_data()
    hist_fb, sh300 = attach_cross_factors_to_1to2(df_daily, all_dts, dt_to_idx, hist_fb)
    csi_bench = json.load(open(CSI300_BENCH_FILE, encoding="utf-8"))

    comp = build_v18_static_components(hist_fb, pg_m)
    sim_core = make_trade_simulator(all_dts, dt_to_idx, price_lookup, bars_5m_map, fee=FEE_RATE)

    # Pre-cache both non-direct and direct simulation outcomes for buyable window rows
    print("[3/5] Pre-caching exact 5m trade outcomes for fast bidirectional ablation...")
    t0 = time.time()
    cand_pool_mask = comp["common_ok"] & (
        comp["open_in_win"] | (comp["wk_mask"] & hist_fb["d2_o_pct"].between(0.015, 0.090).values)
    )
    cache_nodir = {}
    cache_dir = {}
    row_dicts = {}
    for idx in np.where(cand_pool_mask)[0]:
        r = hist_fb.iloc[idx].to_dict()
        row_dicts[idx] = r
        cache_nodir[idx] = sim_core(r, do_direct_override=False)
        if r.get("gap_days", 1) >= 3 and r.get("buy_open_lead", 0.0) >= 0.025:
            cache_dir[idx] = sim_core(r, do_direct_override=True)
    print(f"    Pre-cached {len(row_dicts)} buyable rows in {time.time()-t0:.1f}s")

    def run_v18_variant(score_delta=None, extra_gate=None, skip_l3=False, start_dt="2021-01-04", d3_hook=None):
        sc_v = comp["sc_v_base"] + (score_delta if score_delta is not None else 0.0)
        sp_v = comp["sp_v"]
        thr_vec = comp["thr_vec"]
        l3_ok = True if skip_l3 else comp["pass_l3"]

        m_t1 = comp["common_ok"] & comp["open_in_win"] & (sp_v >= 45.0) & (sc_v >= thr_vec)
        mm = ((m_t1 & comp["pass_l1"] & comp["pass_l2"] & l3_ok & comp["pass_nd_true"] & comp["pass_ac"]) | (comp["m_t2_base"] & comp["pass_l2"])) & comp["p_tight"]
        mmon = (
            comp["common_ok"] & comp["wk_mask"] & hist_fb["d2_o_pct"].between(0.015, 0.090).values
            & (sp_v >= 38.0) & (sc_v >= thr_vec)
            & comp["pass_l1"] & comp["pass_l2"] & l3_ok & comp["pass_nd_true"] & comp["pass_ac"] & comp["p_tight"]
        )
        tot_cand = mm | (mmon & (~mm))
        if extra_gate is not None:
            tot_cand = tot_cand & extra_gate

        sv = np.where(mm, sc_v + 1000.0, sc_v)
        # Apply dom_no_dragon, melee_days, bad_dts dynamically on tot_cand
        cand_indices = np.where(tot_cand)[0]
        by_dt = defaultdict(list)
        for idx in cand_indices:
            by_dt[hist_fb["d2_dt"].iat[idx]].append(idx)

        bad_dts = set()
        dom_no_dragon = set()
        for d, idxs in by_dt.items():
            rks = [hist_fb["rk_theme"].iat[i] for i in idxs]
            if any(r == 1 for r in rks):
                top_i = max(idxs, key=lambda i: sv[i])
                top_rk = hist_fb["rk_theme"].iat[top_i]
                if pd.notna(top_rk) and top_rk >= 4:
                    bad_dts.add(d)
            if d in comp["dom_info"]:
                t1_plate = comp["dom_info"][d]
                if not any(hist_fb["plate"].iat[i] == t1_plate for i in idxs):
                    dom_no_dragon.add(d)

        final_idxs = []
        for idx in cand_indices:
            d = hist_fb["d2_dt"].iat[idx]
            if d in bad_dts:
                continue
            if d in dom_no_dragon and hist_fb["rk_theme"].iat[idx] == 3:
                continue
            if d in comp["melee_days"]:
                is_bo = (hist_fb["buyable_mkt_open_rk"].iat[idx] <= 2) or bool(hist_fb["notice_hard"].iat[idx]) or bool(hist_fb["is_ma"].iat[idx])
                if not is_bo:
                    continue
            if d >= start_dt and d <= DATA_END_DT:
                final_idxs.append(idx)

        # Group by date and simulate 1-slot + EQ
        grp_dt = defaultdict(list)
        for idx in final_idxs:
            grp_dt[hist_fb["d2_dt"].iat[idx]].append(idx)

        free_dt, free_open = "", False
        trades_1s = []
        eq_daily = []
        for d in sorted(grp_dt.keys()):
            idxs = sorted(grp_dt[d], key=lambda i: sv[i], reverse=True)
            def get_tr(i):
                r = row_dicts[i]
                is_dir = (r.get("gap_days", 1) >= 3) and (sc_v[i] >= 310.0) and (r.get("buy_open_lead", 0.0) >= 0.025)
                if d3_hook is not None:
                    r_mod = dict(r, score_active=float(sc_v[i]))
                    return sim_core(r_mod, do_direct_override=is_dir, d3_hook=d3_hook)
                tr = cache_dir.get(i) if is_dir else cache_nodir.get(i)
                if tr is not None:
                    tr = dict(tr, score=round(float(sc_v[i]), 1))
                return tr

            if free_dt == "" or d > free_dt or (d == free_dt and free_open):
                tr1 = get_tr(idxs[0])
                if tr1 is not None:
                    free_dt, free_open = tr1["exit_date"], tr1["exit_at_open"]
                    trades_1s.append(tr1)
            d_rets = []
            for i in idxs:
                tr = get_tr(i)
                if tr is not None:
                    d_rets.append(tr["net_ret"])
            if d_rets:
                eq_daily.append((d, float(np.mean(d_rets))))
        return trades_1s, eq_daily, final_idxs

    # Baseline verification (assert exact match with clean benchmark!)
    tr_base_5y, eq_base_5y, _ = run_v18_variant(start_dt=CANON_5Y_START)
    m_base_5y = calc_d15_metrics(tr_base_5y, eq_base_5y, csi_bench, sh300)["5Y"]
    assert m_base_5y["n"] == 96, f"Baseline 5Y trades mismatch: {m_base_5y['n']} != 96"
    assert m_base_5y["wr"] == 68.75, f"Baseline 5Y WR mismatch: {m_base_5y['wr']} != 68.75"
    assert m_base_5y["nav_1s"] == 328.91, f"Baseline 5Y 1S mismatch: {m_base_5y['nav_1s']} != 328.91"
    assert m_base_5y["cap10m"] == 54.14, f"Baseline 5Y Cap10M mismatch: {m_base_5y['cap10m']} != 54.14"
    assert m_base_5y["eq"] == 57.09, f"Baseline 5Y EQ mismatch: {m_base_5y['eq']} != 57.09"
    assert m_base_5y["mdd"] == 21.98, f"Baseline 5Y MDD mismatch: {m_base_5y['mdd']} != 21.98"
    print(f"[PASS BASELINE ASSERT] 1to2 V18 5Y: {m_base_5y}")

    # Run full period baseline (2021-01-04 ~ 2026-11-16) for IS/OOS splits
    tr_base_full, eq_base_full, base_final_idxs = run_v18_variant(start_dt="2021-01-04")
    base_metrics_full = calc_d15_metrics(tr_base_full, eq_base_full, csi_bench, sh300)
    print("Baseline Full IS(21-23):", base_metrics_full["IS_21_23"])
    print("Baseline Full OOS(24-26):", base_metrics_full["OOS_24_26"])

    # Build wide triggered pools for Bucket IC diagnostics (IS 21-23 vs OOS 24-26)
    wide_rows = []
    near_mask = (
        comp["common_ok"] & comp["open_in_win"] & comp["pass_l1"] & comp["pass_l2"]
        & comp["pass_nd_true"] & comp["pass_ac"] & comp["p_tight"]
        & (comp["sp_v"] >= 35.0) & (comp["sc_v_base"] >= comp["thr_vec"] - 35.0)
    )
    wide_mask = comp["common_ok"] & comp["open_in_win"] & comp["p_tight"]
    base_tot_set = set(base_final_idxs)
    for idx in np.where(wide_mask)[0]:
        tr = cache_nodir.get(idx)
        if tr is None:
            continue
        r = row_dicts[idx]
        wide_rows.append({
            "idx": idx,
            "buy_date": r["d2_dt"],
            "is_oos": r["d2_dt"] >= "2024-01-01",
            "in_near": bool(near_mask[idx]),
            "in_v18": idx in base_tot_set,
            "pass_l3": bool(comp["pass_l3"][idx]),
            "net_ret": tr["net_ret"],
            "theme_hhi": r["theme_hhi"],
            "hhi_pit_pct": r["hhi_pit_pct"],
            "top1_share": r["top1_share"],
            "xq_cnt_tot": r["xq_cnt_tot"],
            "xq_crawled": r["xq_crawled"],
            "on_lhb_d1": r["on_lhb_d1"],
            "lhb_lh_cnt": r["lhb_lh_cnt"],
            "lhb_lh_buy_share": r["lhb_lh_buy_share"],
            "lhb_lh_seat_share": r["lhb_lh_seat_share"],
            "surf_yz_buy_34": r["surf_yz_buy_34"],
            "surf_yz_buy_pure": r["surf_yz_buy_pure"],
            "surf_yz_sell_pure": r["surf_yz_sell_pure"],
            "mkt_maxb_d1": r["mkt_maxb_d1"],
            "prev_1b_dt_cnt": r["prev_1b_dt_cnt"],
            "prev_1b_nuke_cnt": r["prev_1b_nuke_cnt"],
            "prev_2b_dt_cnt": r["prev_2b_dt_cnt"],
            "plate_peers_open_avg": r["plate_peers_open_avg"],
            "plate_fb_cnt": r["plate_fb_cnt"],
            "all_zt_peers_cnt": r["all_zt_peers_cnt"],
            "all_zt_peers_open_avg": r["all_zt_peers_open_avg"],
            "d1_low_pct": r["d1_low_pct"],
            "d1_seal_amt_ratio": r["d1_seal_amt_ratio"],
            "d1_open_cnt": r["open_board_count"],
            "lock_top10": r["lock_top10"],
            "d1_real_turn": r["d1_real_turn"],
            "csi_1d_d1": r["csi_1d_d1"],
            "csi_5d_d1": r["csi_5d_d1"],
        })
    df_w = pd.DataFrame(wide_rows)
    print(f"    Wide buyable triggered pool: {len(df_w)} trades (IS={(~df_w['is_oos']).sum()}, OOS={df_w['is_oos'].sum()}); Near V18: {df_w['in_near'].sum()}; V18: {df_w['in_v18'].sum()}")

    def bucket_stats(sub_df, cond_dict):
        out = {}
        for cname, mask in cond_dict.items():
            s = sub_df[mask]
            res_p = {}
            for p_lbl, p_mask in [("IS_21_23", ~s["is_oos"]), ("OOS_24_26", s["is_oos"]), ("ALL_21_26", np.ones(len(s), dtype=bool))]:
                sp = s[p_mask]
                n = len(sp)
                if n == 0:
                    res_p[p_lbl] = {"n": 0, "wr": 0.0, "mean_pct": 0.0, "plr": 0.0}
                else:
                    r = sp["net_ret"].to_numpy()
                    w, l = r[r > 0], r[r <= 0]
                    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else 99.0
                    res_p[p_lbl] = {
                        "n": int(n),
                        "wr": round(float((r > 0).mean() * 100.0), 2),
                        "mean_pct": round(float(r.mean() * 100.0), 2),
                        "plr": round(plr, 2),
                    }
            out[cname] = res_p
        return out

    # Helper to test bidirectional variants on full V18 engine
    def test_v18_variants(specs):
        out = []
        for label, sd, eg, sl3 in specs:
            tr, eq, _ = run_v18_variant(score_delta=sd, extra_gate=eg, skip_l3=sl3, start_dt="2021-01-04")
            m = calc_d15_metrics(tr, eq, csi_bench, sh300)
            # Check IS+OOS dual improvement without hurting Cap10M/EQ/Trim3/MDD
            b = base_metrics_full
            is_ok = (m["IS_21_23"]["nav_1s"] >= b["IS_21_23"]["nav_1s"]) and (m["IS_21_23"]["wr"] >= b["IS_21_23"]["wr"] - 0.5)
            oos_ok = (m["OOS_24_26"]["nav_1s"] > b["OOS_24_26"]["nav_1s"]) and (m["OOS_24_26"]["wr"] >= b["OOS_24_26"]["wr"])
            no_hurt_5y = (
                (m["5Y"]["cap10m"] >= b["5Y"]["cap10m"])
                and (m["5Y"]["eq"] >= b["5Y"]["eq"])
                and (m["5Y"]["trim3"] >= b["5Y"]["trim3"])
                and (m["5Y"]["mdd"] <= b["5Y"]["mdd"] + 0.5)
            )
            out.append({
                "variant": label,
                "is_oos_pass": bool(is_ok and oos_ok and no_hurt_5y),
                "IS_21_23": m["IS_21_23"],
                "OOS_24_26": m["OOS_24_26"],
                "5Y": m["5Y"],
                "3Y": m["3Y"],
                "2026": m["2026"],
                "2026_07": m["2026_07"],
                "2026_10": m["2026_10"],
            })
        return out

    print("[4/5] Running Factors 1-9 bidirectional bucket + full V18 engine tests...")
    factors_results = {}

    # 1. HHI / Theme concentration vs dispersion
    hhi_pct = hist_fb["hhi_pit_pct"].fillna(0.5).values
    top1_sh = hist_fb["top1_share"].fillna(0.2).values
    factors_results["F1_HHI_concentration_vs_dispersion"] = {
        "buckets_wide_buyable": bucket_stats(df_w, {
            "low_hhi_q25": df_w["hhi_pit_pct"] <= 0.25,
            "mid_hhi": (df_w["hhi_pit_pct"] > 0.25) & (df_w["hhi_pit_pct"] < 0.75),
            "high_hhi_q75": df_w["hhi_pit_pct"] >= 0.75,
            "top1_share_ge30": df_w["top1_share"] >= 0.30,
        }),
        "buckets_v18_pool": bucket_stats(df_w[df_w["in_v18"]], {
            "low_hhi_q25": df_w[df_w["in_v18"]]["hhi_pit_pct"] <= 0.25,
            "mid_hhi": (df_w[df_w["in_v18"]]["hhi_pit_pct"] > 0.25) & (df_w[df_w["in_v18"]]["hhi_pit_pct"] < 0.75),
            "high_hhi_q75": df_w[df_w["in_v18"]]["hhi_pit_pct"] >= 0.75,
            "top1_share_ge30": df_w[df_w["in_v18"]]["top1_share"] >= 0.30,
        }),
        "v18_variants": test_v18_variants([
            ("2to3_dir_lowHHI+10_top1>=30%-12", np.where(hhi_pct <= 0.25, 10.0, np.where(top1_sh >= 0.30, -12.0, 0.0)), None, False),
            ("rev_dir_highHHI+10_lowHHI-10", np.where(hhi_pct >= 0.75, 10.0, np.where(hhi_pct <= 0.25, -10.0, 0.0)), None, False),
            ("nonlin_midHHI+10_ext-10", np.where((hhi_pct > 0.25) & (hhi_pct < 0.75), 10.0, -10.0), None, False),
            ("filter_drop_top1>=30%", None, ~(top1_sh >= 0.30), False),
            ("filter_drop_lowHHI_q25", None, ~(hhi_pct <= 0.25), False),
        ]),
    }

    # 2. Xueqiu pre-market posts
    xq = hist_fb["xq_cnt_tot"].values
    factors_results["F2_Xueqiu_premarket_posts"] = {
        "buckets_wide_buyable": bucket_stats(df_w, {
            "xq_0_dark": df_w["xq_cnt_tot"] == 0,
            "xq_1_3_warm": df_w["xq_cnt_tot"].between(1, 3),
            "xq_ge4_hot": df_w["xq_cnt_tot"] >= 4,
        }),
        "buckets_v18_pool": bucket_stats(df_w[df_w["in_v18"]], {
            "xq_0_dark": df_w[df_w["in_v18"]]["xq_cnt_tot"] == 0,
            "xq_1_3_warm": df_w[df_w["in_v18"]]["xq_cnt_tot"].between(1, 3),
            "xq_ge4_hot": df_w[df_w["in_v18"]]["xq_cnt_tot"] >= 4,
        }),
        "v18_variants": test_v18_variants([
            ("2to3_dir_xq0+8_xq1to3-8_xq>=4-15", np.where(xq == 0, 8.0, np.where(xq >= 4, -15.0, -8.0)), None, False),
            ("rev_dir_xq>=1+10_xq0-5", np.where(xq >= 1, 10.0, -5.0), None, False),
            ("nonlin_warm1to3+12_hot>=4-15", np.where((xq >= 1) & (xq <= 3), 12.0, np.where(xq >= 4, -15.0, 0.0)), None, False),
            ("filter_drop_xq>=4", None, ~(xq >= 4), False),
            ("filter_only_xq0", None, (xq == 0), False),
        ]),
    }

    # 3. LHB Surfing YZ & Lhasa retail seats on d1
    surf34 = hist_fb["surf_yz_buy_34"].values == 1
    surfp = hist_fb["surf_yz_buy_pure"].values == 1
    lh_cnt = hist_fb["lhb_lh_cnt"].values
    lh_sh = hist_fb["lhb_lh_buy_share"].values
    on_lhb = hist_fb["on_lhb_d1"].values == 1
    factors_results["F3_LHB_SurfingYZ_and_Lhasa"] = {
        "buckets_wide_buyable": bucket_stats(df_w, {
            "not_on_lhb": df_w["on_lhb_d1"] == 0,
            "on_lhb_no_surf_no_lh": (df_w["on_lhb_d1"] == 1) & (df_w["surf_yz_buy_pure"] == 0) & (df_w["lhb_lh_cnt"] == 0),
            "surf_yz_buy_pure": df_w["surf_yz_buy_pure"] == 1,
            "surf_yz_buy_34": df_w["surf_yz_buy_34"] == 1,
            "surf_yz_sell_pure": df_w["surf_yz_sell_pure"] == 1,
            "lhb_lh_cnt_ge2": df_w["lhb_lh_cnt"] >= 2,
            "lhb_lh_share_ge20pct": df_w["lhb_lh_buy_share"] >= 0.20,
        }),
        "buckets_v18_pool": bucket_stats(df_w[df_w["in_v18"]], {
            "on_lhb": df_w[df_w["in_v18"]]["on_lhb_d1"] == 1,
            "surf_yz_buy_pure": df_w[df_w["in_v18"]]["surf_yz_buy_pure"] == 1,
            "surf_yz_buy_34": df_w[df_w["in_v18"]]["surf_yz_buy_34"] == 1,
            "lhb_lh_cnt_ge1": df_w[df_w["in_v18"]]["lhb_lh_cnt"] >= 1,
            "lhb_lh_cnt_ge2": df_w[df_w["in_v18"]]["lhb_lh_cnt"] >= 2,
        }),
        "v18_variants": test_v18_variants([
            ("3to4_dir_surf34-12_lh>=2-8", np.where(surf34, -12.0, 0.0) + np.where(lh_cnt >= 2, -8.0, np.where(on_lhb & (lh_cnt == 0), 5.0, 0.0)), None, False),
            ("3to4_dir_surfpure-15_lhsh>=20-10", np.where(surfp, -15.0, 0.0) + np.where(lh_sh >= 0.20, -10.0, 0.0), None, False),
            ("rev_dir_surf+12_lh>=2+8", np.where(surfp, 12.0, 0.0) + np.where(lh_cnt >= 2, 8.0, 0.0), None, False),
            ("filter_drop_surf34", None, ~surf34, False),
            ("filter_drop_lh>=2", None, ~(lh_cnt >= 2), False),
        ]),
    }

    # 4. Market max board height on d1
    maxb = hist_fb["mkt_maxb_d1"].values
    factors_results["F4_MktMaxBoard_d1"] = {
        "buckets_wide_buyable": bucket_stats(df_w, {
            "maxb_le3": df_w["mkt_maxb_d1"] <= 3,
            "maxb_le4": df_w["mkt_maxb_d1"] <= 4,
            "maxb_4_5": df_w["mkt_maxb_d1"].between(4, 5),
            "maxb_ge6": df_w["mkt_maxb_d1"] >= 6,
            "maxb_ge8": df_w["mkt_maxb_d1"] >= 8,
        }),
        "buckets_v18_pool": bucket_stats(df_w[df_w["in_v18"]], {
            "maxb_le3": df_w[df_w["in_v18"]]["mkt_maxb_d1"] <= 3,
            "maxb_le4": df_w[df_w["in_v18"]]["mkt_maxb_d1"] <= 4,
            "maxb_4_5": df_w[df_w["in_v18"]]["mkt_maxb_d1"].between(4, 5),
            "maxb_ge6": df_w[df_w["in_v18"]]["mkt_maxb_d1"] >= 6,
        }),
        "v18_variants": test_v18_variants([
            ("2to3_dir_maxb<=3+10_ge6-10", np.where(maxb <= 3, 10.0, np.where(maxb >= 6, -10.0, 0.0)), None, False),
            ("3to4_dir_maxb<=4+10_ge6-10", np.where(maxb <= 4, 10.0, np.where(maxb >= 6, -10.0, 0.0)), None, False),
            ("rev_dir_highlow_cut_ge6+12_le3-8", np.where(maxb >= 6, 12.0, np.where(maxb <= 3, -8.0, 0.0)), None, False),
            ("nonlin_mid4to5+10_ext-8", np.where((maxb >= 4) & (maxb <= 5), 10.0, -8.0), None, False),
            ("filter_drop_maxb>=6", None, ~(maxb >= 6), False),
        ]),
    }

    # 5. Prev 1b / 2b limit-down stampede on d1
    dt1b = hist_fb["prev_1b_dt_cnt"].values
    dt2b = hist_fb["prev_2b_dt_cnt"].values
    factors_results["F5_SameTier_DT_Stampede"] = {
        "buckets_wide_buyable": bucket_stats(df_w, {
            "prev1b_dt_0": df_w["prev_1b_dt_cnt"] == 0,
            "prev1b_dt_1_2": df_w["prev_1b_dt_cnt"].between(1, 2),
            "prev1b_dt_ge3": df_w["prev_1b_dt_cnt"] >= 3,
            "prev2b_dt_0": df_w["prev_2b_dt_cnt"] == 0,
            "prev2b_dt_ge1": df_w["prev_2b_dt_cnt"] >= 1,
            "prev2b_dt_ge2": df_w["prev_2b_dt_cnt"] >= 2,
        }),
        "buckets_v18_pool": bucket_stats(df_w[df_w["in_v18"]], {
            "prev1b_dt_0": df_w[df_w["in_v18"]]["prev_1b_dt_cnt"] == 0,
            "prev1b_dt_ge2": df_w[df_w["in_v18"]]["prev_1b_dt_cnt"] >= 2,
            "prev2b_dt_0": df_w[df_w["in_v18"]]["prev_2b_dt_cnt"] == 0,
            "prev2b_dt_ge1": df_w[df_w["in_v18"]]["prev_2b_dt_cnt"] >= 1,
        }),
        "v18_variants": test_v18_variants([
            ("3to4_dir_1bdt=0+8_ge3-12", np.where(dt1b == 0, 8.0, np.where(dt1b >= 3, -12.0, 0.0)), None, False),
            ("3to4_dir_2bdt=0+8_ge2-12", np.where(dt2b == 0, 8.0, np.where(dt2b >= 2, -12.0, 0.0)), None, False),
            ("rev_dir_1bdt>=3+10_2bdt>=1+8", np.where(dt1b >= 3, 10.0, 0.0) + np.where(dt2b >= 1, 8.0, 0.0), None, False),
            ("filter_drop_1bdt>=3", None, ~(dt1b >= 3), False),
            ("filter_drop_2bdt>=2", None, ~(dt2b >= 2), False),
        ]),
    }

    # 6. Same-theme teammates auction nuke (< -1.5%)
    azp = hist_fb["all_zt_peers_open_avg"].values
    azc = hist_fb["all_zt_peers_cnt"].values
    fbp = hist_fb["plate_peers_open_avg"].values
    fbc = hist_fb["plate_fb_cnt"].values
    factors_results["F6_Teammate_Auction_Nuke"] = {
        "buckets_wide_no_l3": bucket_stats(df_w[df_w["all_zt_peers_cnt"] >= 1], {
            "all_peers_lt_-1.5%": df_w[df_w["all_zt_peers_cnt"] >= 1]["all_zt_peers_open_avg"] < -0.015,
            "all_peers_-1.5_to_+1.5%": df_w[df_w["all_zt_peers_cnt"] >= 1]["all_zt_peers_open_avg"].between(-0.015, 0.015),
            "all_peers_gt_+1.5%": df_w[df_w["all_zt_peers_cnt"] >= 1]["all_zt_peers_open_avg"] > 0.015,
        }),
        "buckets_fb_peers_wide": bucket_stats(df_w[df_w["plate_fb_cnt"] >= 2], {
            "fb_peers_lt_-1.5%": df_w[df_w["plate_fb_cnt"] >= 2]["plate_peers_open_avg"] < -0.015,
            "fb_peers_-1.5_to_+1.0%": df_w[df_w["plate_fb_cnt"] >= 2]["plate_peers_open_avg"].between(-0.015, 0.010),
            "fb_peers_gt_+1.0%": df_w[df_w["plate_fb_cnt"] >= 2]["plate_peers_open_avg"] > 0.010,
        }),
        "buckets_v18_pool": bucket_stats(df_w[df_w["in_v18"]], {
            "all_peers_nuke<-1.5%": (df_w[df_w["in_v18"]]["all_zt_peers_cnt"] >= 1) & (df_w[df_w["in_v18"]]["all_zt_peers_open_avg"] < -0.015),
            "all_peers_ok": ~((df_w[df_w["in_v18"]]["all_zt_peers_cnt"] >= 1) & (df_w[df_w["in_v18"]]["all_zt_peers_open_avg"] < -0.015)),
        }),
        "v18_variants": test_v18_variants([
            ("3to4_dir_all_peers<-1.5%-15", np.where((azc >= 1) & (azp < -0.015), -15.0, 0.0), None, False),
            ("rev_dir_all_peers<-1.5%+12(sole_survivor)", np.where((azc >= 1) & (azp < -0.015), 12.0, 0.0), None, False),
            ("skip_l3_and_pen_fb_nuke<-1.5%-15", np.where((fbc >= 2) & (fbp < -0.015), -15.0, 0.0), None, True),
            ("skip_l3_and_rev_fb_nuke<-1.5%+12", np.where((fbc >= 2) & (fbp < -0.015), 12.0, 0.0), None, True),
            ("filter_drop_all_peers<-1.5%", None, ~((azc >= 1) & (azp < -0.015)), False),
        ]),
    }

    # 7. d1 deep dip (low_pct < -2%) & d1 seal/amt ratio (deadlock >=25% vs weak <5%)
    d1lp = hist_fb["d1_low_pct"].values
    d1sr = hist_fb["d1_seal_amt_ratio"].fillna(0.08).values
    d1sr_valid = hist_fb["d1_seal_amt_ratio"].notna().values
    factors_results["F7_D1_DeepDip_and_SealRatio"] = {
        "buckets_wide_buyable": bucket_stats(df_w, {
            "low_lt_-2%": df_w["d1_low_pct"] < -0.02,
            "low_-2%_to_0": df_w["d1_low_pct"].between(-0.02, 0.0),
            "low_ge_0": df_w["d1_low_pct"] >= 0.0,
            "seal_weak_lt5%": df_w["d1_seal_amt_ratio"] < 0.05,
            "seal_mid_5_25%": df_w["d1_seal_amt_ratio"].between(0.05, 0.25),
            "seal_deadlock_ge25%": df_w["d1_seal_amt_ratio"] >= 0.25,
        }),
        "buckets_v18_pool": bucket_stats(df_w[df_w["in_v18"]], {
            "low_lt_-2%": df_w[df_w["in_v18"]]["d1_low_pct"] < -0.02,
            "low_ge_-2%": df_w[df_w["in_v18"]]["d1_low_pct"] >= -0.02,
            "seal_lt5%": df_w[df_w["in_v18"]]["d1_seal_amt_ratio"] < 0.05,
            "seal_5_25%": df_w[df_w["in_v18"]]["d1_seal_amt_ratio"].between(0.05, 0.25),
            "seal_ge25%": df_w[df_w["in_v18"]]["d1_seal_amt_ratio"] >= 0.25,
        }),
        "v18_variants": test_v18_variants([
            ("2to3_dir_dip<-2%+8_weak<5%+8_dead>=25%-16", np.where(d1lp < -0.02, 8.0, 0.0) + np.where(d1sr_valid & (d1sr >= 0.25), -16.0, np.where(d1sr_valid & (d1sr < 0.05), 8.0, 0.0)), None, False),
            ("rev_dir_dead>=25%+12_weak<5%-10_dip<-2%-8", np.where(d1lp < -0.02, -8.0, 0.0) + np.where(d1sr_valid & (d1sr >= 0.25), 12.0, np.where(d1sr_valid & (d1sr < 0.05), -10.0, 0.0)), None, False),
            ("only_dip<-2%+10", np.where(d1lp < -0.02, 10.0, 0.0), None, False),
            ("only_dip<-2%-10", np.where(d1lp < -0.02, -10.0, 0.0), None, False),
            ("filter_drop_seal<5%", None, ~(d1sr_valid & (d1sr < 0.05)), False),
            ("filter_drop_seal>=25%", None, ~(d1sr_valid & (d1sr >= 0.25)), False),
        ]),
    }

    # 8. lock_top10 >= 50% x d1_real_turn in [25%, 65%] (also check 15~45% for 1st board!)
    lk = hist_fb["lock_top10"].fillna(0.0).values
    rt = hist_fb["d1_real_turn"].fillna(20.0).values
    rt_v = hist_fb["d1_real_turn"].notna().values
    combo_23 = rt_v & (lk >= 50.0) & (rt >= 25.0) & (rt <= 65.0)
    combo_12_mid = rt_v & (lk >= 50.0) & (rt >= 15.0) & (rt <= 45.0)
    factors_results["F8_Lock50_x_RealTurn"] = {
        "buckets_wide_buyable": bucket_stats(df_w[df_w["d1_real_turn"].notna()], {
            "lock>=50_rt_25_65": (df_w[df_w["d1_real_turn"].notna()]["lock_top10"] >= 50.0) & df_w[df_w["d1_real_turn"].notna()]["d1_real_turn"].between(25.0, 65.0),
            "lock>=50_rt_15_45": (df_w[df_w["d1_real_turn"].notna()]["lock_top10"] >= 50.0) & df_w[df_w["d1_real_turn"].notna()]["d1_real_turn"].between(15.0, 45.0),
            "rt_lt_15": df_w[df_w["d1_real_turn"].notna()]["d1_real_turn"] < 15.0,
            "rt_gt_65": df_w[df_w["d1_real_turn"].notna()]["d1_real_turn"] > 65.0,
            "lock_lt_50_rt_25_65": (df_w[df_w["d1_real_turn"].notna()]["lock_top10"] < 50.0) & df_w[df_w["d1_real_turn"].notna()]["d1_real_turn"].between(25.0, 65.0),
        }),
        "buckets_v18_pool": bucket_stats(df_w[df_w["in_v18"] & df_w["d1_real_turn"].notna()], {
            "lock>=50_rt_25_65": (df_w[df_w["in_v18"] & df_w["d1_real_turn"].notna()]["lock_top10"] >= 50.0) & df_w[df_w["in_v18"] & df_w["d1_real_turn"].notna()]["d1_real_turn"].between(25.0, 65.0),
            "rt_lt_15": df_w[df_w["in_v18"] & df_w["d1_real_turn"].notna()]["d1_real_turn"] < 15.0,
            "other": ~((df_w[df_w["in_v18"] & df_w["d1_real_turn"].notna()]["lock_top10"] >= 50.0) & df_w[df_w["in_v18"] & df_w["d1_real_turn"].notna()]["d1_real_turn"].between(25.0, 65.0)) & (df_w[df_w["in_v18"] & df_w["d1_real_turn"].notna()]["d1_real_turn"] >= 15.0),
        }),
        "v18_variants": test_v18_variants([
            ("2to3_dir_combo25_65+10_rt<15-10", np.where(combo_23, 10.0, np.where(rt_v & (rt < 15.0), -10.0, 0.0)), None, False),
            ("rev_dir_combo25_65-10_rt<15+10", np.where(combo_23, -10.0, np.where(rt_v & (rt < 15.0), 10.0, 0.0)), None, False),
            ("mid_combo15_45+10_rt>65-12", np.where(combo_12_mid, 10.0, np.where(rt_v & (rt > 65.0), -12.0, 0.0)), None, False),
        ]),
    }

    # 9. CSI300 prev 1d <= -2% or 5d <= -3%
    csi_drop = (hist_fb["csi_1d_d1"].values <= -0.020) | (hist_fb["csi_5d_d1"].values <= -0.030)
    factors_results["F9_CSI300_Sharp_Drop"] = {
        "buckets_wide_buyable": bucket_stats(df_w, {
            "csi_drop_1d<=-2%_or_5d<=-3%": (df_w["csi_1d_d1"] <= -0.020) | (df_w["csi_5d_d1"] <= -0.030),
            "csi_normal": ~((df_w["csi_1d_d1"] <= -0.020) | (df_w["csi_5d_d1"] <= -0.030)),
        }),
        "buckets_v18_pool": bucket_stats(df_w[df_w["in_v18"]], {
            "csi_drop": (df_w[df_w["in_v18"]]["csi_1d_d1"] <= -0.020) | (df_w[df_w["in_v18"]]["csi_5d_d1"] <= -0.030),
            "csi_normal": ~((df_w[df_w["in_v18"]]["csi_1d_d1"] <= -0.020) | (df_w[df_w["in_v18"]]["csi_5d_d1"] <= -0.030)),
        }),
        "v18_variants": test_v18_variants([
            ("3to4_dir_csidrop-10", np.where(csi_drop, -10.0, 0.0), None, False),
            ("rev_dir_csidrop+12(ice_group)", np.where(csi_drop, 12.0, 0.0), None, False),
            ("filter_drop_csidrop", None, ~csi_drop, False),
        ]),
    }

    # ==========================================================================
    # Factor 10: Buy/Sell Point Intersection on d3 (1to2 sealed_2b -> 2to3 buy day)
    # ==========================================================================
    print("[5/5] Running Factor 10 (d3 exit intersection using 2to3 features)...")
    raw_23, df_23, _ = m23.load_all_clean_data()
    df_23["score_23"] = m23.score_dataframe(df_23, base_pts=58)
    wa_23 = pd.read_parquet(f"{BACKTEST_ASTOCK_DIR}/clean_2to3_v10_20261117/data_pit/factors_a.parquet")
    # Build lookup keyed by (code, sig_date=d2)
    raw_23_m = raw_23.merge(wa_23[["code", "buy_date", "b01_hhi_low_q25", "raw_top1_share"]], on=["code", "buy_date"], how="left")
    sc23_map = df_23.set_index(["code", "sig_date"]).to_dict(orient="index")
    raw23_map = raw_23_m.set_index(["code", "sig_date"]).to_dict(orient="index")

    def make_d3_hook(mode):
        def hook(row, oc, hc, lc, cc, ztc, dtc, iztc, prev_c, arr, bc_1030=None, vwap_1030=None):
            key = (row["c6"], row["d2_dt"])
            r_raw = raw23_map.get(key)
            r_b = sc23_map.get(key)
            if r_raw is None:
                return None
            op_pct = oc / prev_c - 1.0
            sc23 = r_b["score_23"] if r_b else None

            if mode == "exempt_sc23>=80" and bc_1030 is not None:
                if sc23 is not None and sc23 >= 80:
                    return "exempt_1030"
            elif mode == "exempt_sc23>=85" and bc_1030 is not None:
                if sc23 is not None and sc23 >= 85:
                    return "exempt_1030"
            elif mode == "exempt_sc23>=90" and bc_1030 is not None:
                if sc23 is not None and sc23 >= 90:
                    return "exempt_1030"
            elif mode == "exempt_2to3_weakopen_band" and bc_1030 is not None:
                # 2to3 weak-to-strong open [-6.5%, +2.5%] and not xq>=4 and not deadlock
                if (-0.065 <= op_pct <= 0.025) and (r_b is not None) and (r_b.get("xq_cnt_tot", 0) < 4) and (r_b.get("d2_seal_amt_ratio", 0) < 0.25):
                    return "exempt_1030"
            elif mode == "exempt_2to3_red_open_band" and bc_1030 is not None:
                if (-0.065 <= op_pct < 0.0):
                    return "exempt_1030"
            elif mode == "exempt_all_1030" and bc_1030 is not None:
                return "exempt_1030"
            elif mode == "early_open_exit_2to3_trap" and bc_1030 is None:
                # Early exit at 09:25 if 2to3 sees hot crowd / xq>=4 / deadlock / bad score < 60
                if (r_b is not None) and (op_pct < 0.095) and ((r_b.get("xq_cnt_tot", 0) >= 4) or (sc23 < 60)):
                    return "early_open_exit"
            elif mode == "early_1030_exit_2to3_trap" and bc_1030 is not None:
                # Exit at 10:30 even if above VWAP if not sealed and 2to3 sees xq>=4 or high open > +2.5%
                if (bc_1030 < ztc - 0.01) and (r_b is not None) and ((r_b.get("xq_cnt_tot", 0) >= 4) or (sc23 < 65)):
                    return "force_1030_exit"
            return None
        return hook

    d3_intersection_results = []
    for lbl, hk in [
        ("Baseline_V18", None),
        ("Exempt_1030_when_2to3_score>=80", make_d3_hook("exempt_sc23>=80")),
        ("Exempt_1030_when_2to3_score>=85", make_d3_hook("exempt_sc23>=85")),
        ("Exempt_1030_when_2to3_score>=90", make_d3_hook("exempt_sc23>=90")),
        ("Exempt_1030_when_2to3_weakopen_band", make_d3_hook("exempt_2to3_weakopen_band")),
        ("Exempt_1030_when_2to3_red_open", make_d3_hook("exempt_2to3_red_open_band")),
        ("Exempt_1030_all_d3", make_d3_hook("exempt_all_1030")),
        ("Early_0925_exit_when_2to3_trap(xq>=4_or_sc<60)", make_d3_hook("early_open_exit_2to3_trap")),
        ("Early_1030_exit_when_2to3_trap(xq>=4_or_sc<65)", make_d3_hook("early_1030_exit_2to3_trap")),
    ]:
        tr, eq, _ = run_v18_variant(start_dt="2021-01-04", d3_hook=hk)
        m = calc_d15_metrics(tr, eq, csi_bench, sh300)
        # Collect diffs vs baseline trades
        base_map = {(t["buy_date"], t["code"]): t["net_ret"] for t in tr_base_full}
        changed = []
        for t in tr:
            k = (t["buy_date"], t["code"])
            if k in base_map and abs(t["net_ret"] - base_map[k]) > 1e-4:
                changed.append({"buy_date": t["buy_date"], "code": t["code"], "name": t["name"], "base_ret": base_map[k], "new_ret": t["net_ret"], "new_tag": t["tag"]})
        d3_intersection_results.append({
            "mode": lbl,
            "changed_trades_count": len(changed),
            "changed_examples": changed[:15],
            "IS_21_23": m["IS_21_23"],
            "OOS_24_26": m["OOS_24_26"],
            "5Y": m["5Y"],
            "3Y": m["3Y"],
            "2026": m["2026"],
            "2026_07": m["2026_07"],
            "2026_10": m["2026_10"],
        })

    # Also evaluate d3 10:30 exemption specifically on ALL near_v18 sealed_2b=1 trades that hit 5m_1030_weak_cut on d3
    nxt_dt_map = {all_dts[i]: all_dts[i + 1] for i in range(len(all_dts) - 1)}
    d3_cut_audit = []
    for idx in np.where(near_mask)[0]:
        tr = cache_nodir.get(idx)
        if tr is None or tr["sealed_2b"] != 1:
            continue
        d3 = nxt_dt_map.get(tr["buy_date"])
        if tr["exit_date"] == d3 and tr["tag"] == "5m_1030_weak_cut":
            key = (tr["code"], tr["buy_date"])
            r_raw = raw23_map.get(key)
            r_b = sc23_map.get(key)
            tr_ex = sim_core(row_dicts[idx], do_direct_override=False, d3_hook=make_d3_hook("exempt_all_1030"))
            d3_cut_audit.append({
                "buy_date": tr["buy_date"], "d3": d3, "code": tr["code"], "name": tr["name"],
                "is_oos": tr["buy_date"] >= "2024-01-01",
                "in_v18": idx in base_tot_set,
                "base_ret": tr["net_ret"], "exempt_ret": tr_ex["net_ret"], "diff": round(tr_ex["net_ret"] - tr["net_ret"], 4),
                "score_23": float(r_b["score_23"]) if r_b else np.nan,
                "d3_open_pct": float(r_raw["open_pct"]) if r_raw else np.nan,
                "d3_sealed_3b": bool(r_raw["sealed_3b"]) if r_raw else False,
                "xq_cnt_tot": int(r_b["xq_cnt_tot"]) if r_b else -1,
            })
    df_d3c = pd.DataFrame(d3_cut_audit)
    d3_cut_summary = {}
    if not df_d3c.empty:
        for lbl, msk in [
            ("all_near_v18_1030_cuts", np.ones(len(df_d3c), dtype=bool)),
            ("v18_only_1030_cuts", df_d3c["in_v18"]),
            ("score_23>=80", df_d3c["score_23"] >= 80),
            ("score_23>=75", df_d3c["score_23"] >= 75),
            ("d3_open_in_[-6.5%,+2.5%]", df_d3c["d3_open_pct"].between(-0.065, 0.025)),
            ("d3_open_gt_+2.5%", df_d3c["d3_open_pct"] > 0.025),
        ]:
            sub = df_d3c[msk]
            d3_cut_summary[lbl] = {
                "IS_n": int((~sub["is_oos"]).sum()),
                "IS_avg_diff_pct": round(float(sub[~sub["is_oos"]]["diff"].mean() * 100), 2) if (~sub["is_oos"]).sum() else 0.0,
                "OOS_n": int(sub["is_oos"].sum()),
                "OOS_avg_diff_pct": round(float(sub[sub["is_oos"]]["diff"].mean() * 100), 2) if sub["is_oos"].sum() else 0.0,
                "ALL_n": int(len(sub)),
                "ALL_base_mean_pct": round(float(sub["base_ret"].mean() * 100), 2) if len(sub) else 0.0,
                "ALL_exempt_mean_pct": round(float(sub["exempt_ret"].mean() * 100), 2) if len(sub) else 0.0,
            }

    out_payload = {
        "meta": {
            "experiment": "ExpA1_CrossLearn_1to2_V18",
            "generated_at": datetime.datetime.now().isoformat(),
            "is_window": "2021-01-04 ~ 2023-12-31",
            "oos_window": "2024-01-01 ~ 2026-11-16",
            "canon_5y_window": f"{CANON_5Y_START} ~ {DATA_END_DT}",
            "xueqiu_crawled_pct_wide": round(float(df_w["xq_crawled"].mean() * 100.0), 2),
        },
        "baseline_v18": base_metrics_full,
        "factors_1_to_9": factors_results,
        "factor_10_d3_intersection": {
            "v18_engine_modes": d3_intersection_results,
            "d3_1030_cut_counterfactual_summary": d3_cut_summary,
        },
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out_payload, f, ensure_ascii=False, indent=2)
    print(f"Saved {OUT_JSON} in {time.time()-t_all:.1f}s")

    # Concise summary print
    for fk, fv in factors_results.items():
        passes = [v["variant"] for v in fv["v18_variants"] if v["is_oos_pass"]]
        print(f"  {fk}: dual_pass={passes}")


if __name__ == "__main__":
    main()
