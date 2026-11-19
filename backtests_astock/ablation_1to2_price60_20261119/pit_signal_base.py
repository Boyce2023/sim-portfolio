#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
pit_signal_base.py
严格复用 upgrade_1to2_pit.py 的底层 PIT 数据加载与特征构建逻辑，
仅将 `close <= 60.0` 从 gate_ok 剥离为可参数化消融变量。
"""

import bisect
import datetime
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd

UPG_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
if UPG_DIR not in sys.path:
    sys.path.insert(0, UPG_DIR)

import upgrade_1to2_pit as u


def build_base_ctx_pit(end_date_cutoff: str = u.DATA_END_DT) -> dict:
    """加载全市场日线(含退市)、KPL 8年题材与全部 PIT 特征，保留 gate_no_price 与 close。"""
    t0 = time.time()
    df_daily, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = u.load_full_prices_pit(end_date_cutoff)
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    price_lookup = {
        (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
        for r in df_daily[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
    }
    amt_lookup = {
        (r.c6, r.dt_str): float(r.amount)
        for r in df_daily[["c6", "dt_str", "amount"]].itertuples(index=False) if pd.notna(r.amount)
    }

    stock_theme_5y, pioneer_word_history = u.build_8y_purified_theme_metadata_pit(df_daily, end_date_cutoff)

    fb = df_daily[df_daily["is_first_board"] & (~df_daily["is_yizi"]) & (df_daily["dt_str"] >= "2021-01-04")].copy()
    c6_set = set(fb["c6"].unique())

    # 1. 严格 PIT 公告
    notice_by_c6 = defaultdict(list)
    if os.path.exists(u.DB_NOTICES_PATH):
        conn_notices = sqlite3.connect(f"file:{u.DB_NOTICES_PATH}?mode=ro", uri=True)
        for sec_code, pub_dt, avail_dt, title in conn_notices.execute(
            "SELECT sec_code, pub_datetime_cst, trade_date_avail, title FROM notices WHERE pub_datetime_cst >= '2020-12-25' AND pub_datetime_cst <= ?",
            (f"{end_date_cutoff} 09:25:00",),
        ):
            c6 = str(sec_code)[:6].zfill(6)
            if c6 not in c6_set or not pub_dt:
                continue
            ts = str(title or "")
            is_neg = bool(u.NEG_NOTICE_PAT.search(ts)) or bool(u.BAD_NOTICE_PAT.search(ts))
            if is_neg:
                flags = (False, False, False, bool(u.EARN_NOTICE_PAT.search(ts)), True)
            else:
                flags = (
                    bool(u.HARD_NOTICE_ORIG_PAT.search(ts)),
                    bool(u.HARD_NOTICE_PAT.search(ts)),
                    bool(u.MA_NOTICE_PAT.search(ts)),
                    bool(u.EARN_NOTICE_PAT.search(ts)),
                    False,
                )
            if any(flags):
                notice_by_c6[c6].append((str(pub_dt), str(avail_dt or ""), flags))
        conn_notices.close()

    if os.path.exists(u.PARQUET_TOX_PATH):
        df_tox = pd.read_parquet(u.PARQUET_TOX_PATH)
        df_tox = df_tox[df_tox["pub_datetime_cst"].astype(str) <= f"{end_date_cutoff} 09:25:00"]
        for sec_code, pub_dt, title in df_tox[["sec_code", "pub_datetime_cst", "title"]].itertuples(index=False):
            c6 = str(sec_code)[:6].zfill(6)
            if c6 not in c6_set or not pub_dt:
                continue
            ts = str(title or "")
            is_neg = bool(u.NEG_NOTICE_PAT.search(ts)) or bool(u.BAD_NOTICE_PAT.search(ts)) or ("澄清" in ts)
            if is_neg:
                flags = (False, False, False, bool(u.EARN_NOTICE_PAT.search(ts)), True)
                notice_by_c6[c6].append((str(pub_dt), "", flags))

    for c6 in notice_by_c6:
        notice_by_c6[c6].sort(key=lambda x: x[0])

    rows_meta = []
    cols_needed = [
        "c6", "dt_str", "d2_dt", "mcap", "amount", "f_dd20_d0", "f_dd60_d0", "f_pos20_d0",
        "f_d0_pct", "f_ret_pre10", "to", "f_d1_vol_ratio", "f_zt_cnt_pre20", "f_break60", "close", "d1_seal_tightness"
    ]
    for r in fb[cols_needed].itertuples(index=False):
        c6, d1 = r.c6, r.dt_str
        d2 = r.d2_dt if (pd.notna(r.d2_dt) and r.d2_dt <= end_date_cutoff) else end_date_cutoff
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
                if pdt >= end_cut:
                    break
                assert pdt < end_cut, f"Notice lookahead violation: {pdt} >= {end_cut}"
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

        gate_no_price = bool(
            (not is_st) and (not is_earn_f) and (not n_bad)
            and (18.0 <= mcap <= 220.0) and (to <= 20.0)
            and (not (zt20 >= 4 and pos20 > 0.38))
        )
        tot_thr = 255.0 if seal_r > 0.75 else 230.0

        r_txt = str(ti.get("r_short", "")) + " " + str(ti.get("name", ""))
        is_pioneer_word = False
        for m in re.finditer(r"[\u4e00-\u9fa5A-Za-z0-9]{2,8}(?:技术|材料|产品|装备|芯片|器件|电池|系统|模块|平台|光模块|算法|模型|协议)", r_txt):
            w = u.norm_term(m.group(0))
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
            "notice_bad": n_bad, "clean_brk60": int(clean_brk60), "gate_no_price": gate_no_price,
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
    hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= end_date_cutoff)].copy().reset_index(drop=True)
    hist_fb["gap_days"] = (pd.to_datetime(hist_fb["d2_dt"]) - pd.to_datetime(hist_fb["dt_str"])).dt.days
    hist_fb["c6"] = hist_fb["ticker"].astype(str).str[:6]

    # 2. 严格截断 PIT 行业表
    df_csrc_pit = pd.read_csv(u.CSV_CSRC_PIT_PATH)
    df_csrc_pit["c6"] = df_csrc_pit["sec_code"].astype(str).str.zfill(6)
    csrc_pit_lookup = defaultdict(list)
    for r in df_csrc_pit[["c6", "start_date", "end_date", "industry"]].itertuples(index=False):
        sd_s = str(r.start_date)
        if sd_s <= end_date_cutoff:
            csrc_pit_lookup[r.c6].append((sd_s, str(r.end_date), str(r.industry) if pd.notna(r.industry) else ""))

    def get_pit_ind_strict(c6_val, dt_val):
        intervals = [x for x in csrc_pit_lookup.get(c6_val, []) if x[0] <= dt_val]
        if not intervals:
            return ""
        for s, e, ind in intervals:
            if s <= dt_val <= e:
                return ind
        return intervals[-1][2]

    hist_fb["csrc_ind"] = [get_pit_ind_strict(c6, d2) for c6, d2 in zip(hist_fb["c6"], hist_fb["d2_dt"])]

    # 3. 严格只读微观盘口
    conn_tape = sqlite3.connect(f"file:{u.DB_TAPE_PATH}?mode=ro", uri=True)
    tape_df = pd.read_sql_query(
        "SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape WHERE trade_date <= ?",
        conn_tape, params=(end_date_cutoff,),
    )
    conn_tape.close()
    tape_df = tape_df.drop_duplicates(["trade_date", "sec_code"])
    hist_fb = hist_fb.merge(tape_df, left_on=["dt_str", "c6"], right_on=["trade_date", "sec_code"], how="left")
    tape_map = {
        (r.trade_date, str(r.sec_code).zfill(6)): (r.first_seal_time, r.seal_amount, r.open_board_count)
        for r in tape_df.itertuples(index=False)
    }

    # 4. 严格 PIT 机构调研
    conn_ir = sqlite3.connect(f"file:{u.DB_IR_QA_PATH}?mode=ro", uri=True)
    ir_df = pd.read_sql_query(
        "SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE pub_datetime_cst IS NOT NULL AND pub_datetime_cst <= ?",
        conn_ir, params=(f"{end_date_cutoff} 09:25:00",),
    )
    conn_ir.close()
    ir_df["c6"] = ir_df["sec_code"].astype(str).str.zfill(6)
    ir_grp = ir_df.groupby("c6")["pub_datetime_cst"].apply(lambda s: np.sort(s.unique())).to_dict()
    ir_7d_pit = np.zeros(len(hist_fb), dtype=bool)
    for idx, (c6, d2) in enumerate(zip(hist_fb["c6"], hist_fb["d2_dt"])):
        arr = ir_grp.get(c6)
        if arr is not None:
            pos = np.searchsorted(arr, f"{d2} 09:25:00", side="left")
            if pos > 0:
                pdt_ir = arr[pos - 1]
                assert pdt_ir < f"{d2} 09:25:00"
                if 0 <= (pd.Timestamp(d2) - pd.Timestamp(pdt_ir[:10])).days <= 8:
                    ir_7d_pit[idx] = True
    hist_fb["has_ir_pit"] = ir_7d_pit

    # 5. 严格 PIT 雪球盘前舆情
    con_xq = sqlite3.connect(f"file:{u.DB_XUEQIU_PATH}?mode=ro", uri=True)
    xq_df = pd.read_sql_query(
        "SELECT symbol, created_time_str FROM xueqiu_posts WHERE created_time_str >= '2021-01-01' AND created_time_str <= ?",
        con_xq, params=(f"{end_date_cutoff} 09:25:00",),
    )
    con_xq.close()
    xq_df["c6"] = xq_df["symbol"].astype(str).str[:6].str.zfill(6)
    xq_by_c6 = {c6: np.sort(g["created_time_str"].astype(str).to_numpy()) for c6, g in xq_df.groupby("c6")}

    xq_d2 = np.zeros(len(hist_fb), dtype=int)
    for i, (c6, d1, d2) in enumerate(zip(hist_fb["c6"], hist_fb["dt_str"], hist_fb["d2_dt"])):
        arr = xq_by_c6.get(c6)
        if arr is not None:
            lo = np.searchsorted(arr, f"{d1} 00:00:00", side="left")
            hi = np.searchsorted(arr, f"{d2} 09:25:00", side="left")
            assert hi == 0 or arr[hi - 1] < f"{d2} 09:25:00"
            xq_d2[i] = int(hi - lo)
    hist_fb["xq_pre_d2"] = xq_d2

    # 6. 严格 PIT D1 龙虎榜
    lb = pd.read_parquet(u.LHB_BUY_PATH, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY", "SELL"])
    lb["dt_str"] = lb["TRADE_DATE"].astype(str).str[:10]
    lb["c6"] = lb["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
    lb = lb[(lb["dt_str"] >= "2021-01-01") & (lb["dt_str"] <= end_date_cutoff)].drop_duplicates(
        subset=["dt_str", "c6", "OPERATEDEPT_NAME"]
    )
    lhb_map = {}
    for (dt, c6), grp in lb.groupby(["dt_str", "c6"], sort=False):
        seats = grp["OPERATEDEPT_NAME"].astype(str).tolist()
        lh_cnt = sum(1 for s in seats if "拉萨" in s)
        surf_pure = int(any(u.SURF_YZ_PURE.search(s) for s in seats))
        lhb_map[(dt, c6)] = (1, lh_cnt, surf_pure)
    hist_fb["lhb_lh_cnt_d1"] = [lhb_map.get((d1, c6), (0, 0, 0))[1] for d1, c6 in zip(hist_fb["dt_str"], hist_fb["c6"])]
    hist_fb["surf_yz_d1"] = [lhb_map.get((d1, c6), (0, 0, 0))[2] for d1, c6 in zip(hist_fb["dt_str"], hist_fb["c6"])]

    # 7. 动态题材日排名
    valid_plate = hist_fb[(hist_fb["plate"] != "其他") & (~hist_fb["is_event_basket"])].copy()
    pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(p_sz_max=("p_sz", "max"), p_theme_med=("s_prior_dual", "median"))
    pg_m = pg[pg["p_sz_max"] >= 2].copy()
    pg_m["rk_theme"] = pg_m.groupby("d2_dt")["p_theme_med"].rank(ascending=False, method="min")
    hist_fb = hist_fb.merge(pg_m[["d2_dt", "plate", "rk_theme"]], on=["d2_dt", "plate"], how="left")

    # 8. 5 分钟 K 线索引 (合并 gt60 独立补齐缓存，不覆盖原数据既有键)
    df_5m = pd.read_parquet(u.PARQUET_5M_PATH)
    df_5m = df_5m[df_5m["date"].astype(str) <= end_date_cutoff].copy()
    df_5m["hhmm_int"] = df_5m["hhmm"].astype(int)
    df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    bars_5m_map = {
        (c6, dt): grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy()
        for (c6, dt), grp in df_5m.groupby(["c6", "date"], sort=False)
    }
    patch_p = os.path.join(os.path.dirname(__file__), "gt60_5m_patch.parquet")
    if os.path.exists(patch_p):
        df_p = pd.read_parquet(patch_p)
        df_p = df_p[df_p["date"].astype(str) <= end_date_cutoff].copy()
        df_p["hhmm_int"] = df_p["hhmm"].astype(int)
        df_p.sort_values(["c6", "date", "hhmm_int"], inplace=True)
        added_keys = 0
        for (c6, dt), grp in df_p.groupby(["c6", "date"], sort=False):
            if (c6, dt) not in bars_5m_map:
                bars_5m_map[(c6, dt)] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy()
                added_keys += 1
        print(f"  [5m Patch Loaded] added {added_keys} missing (c6, date) keys from gt60_5m_patch.parquet")

    valid_sr_d1 = hist_fb["seal_amount"].dropna() / hist_fb.loc[hist_fb["seal_amount"].notna(), "amount"]
    assert 0.01 < float(valid_sr_d1.median()) < 0.50

    print(f"[Base PIT <= {end_date_cutoff}] rows={len(hist_fb):,}, elapsed={time.time()-t0:.1f}s")
    return {
        "all_dts": all_dts, "dt_to_idx": dt_to_idx, "price_lookup": price_lookup,
        "amt_lookup": amt_lookup, "tape_map": tape_map, "xq_by_c6": xq_by_c6,
        "bars_5m_map": bars_5m_map, "hist_fb_base": hist_fb, "pg_m": pg_m,
    }


def apply_variant_v19(base_ctx: dict, price_cap: float | None = 60.0, soft_pen_gt60: float = 0.0) -> dict:
    """基于共享底层 PIT 数据，按指定股价硬门槛或软扣分重算竞价排名与 V19 信号掩码。"""
    hist_fb = base_ctx["hist_fb_base"].copy()
    if price_cap is None:
        hist_fb["gate_ok"] = hist_fb["gate_no_price"].astype(bool)
    else:
        hist_fb["gate_ok"] = hist_fb["gate_no_price"].astype(bool) & (hist_fb["close"] <= float(price_cap))

    hist_fb = u.compute_purifier_auction_scores_pit(hist_fb)
    pg_m = base_ctx["pg_m"]

    seal_time = hist_fb["first_seal_time"].fillna("99:99:99")
    open_cnt = hist_fb["open_board_count"].fillna(0)
    dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
    clean_brk60 = hist_fb["clean_brk60"].values == 1

    is_gran = hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
    bonus_spear = np.where(is_gran, 15.0, 0.0) + np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))
    common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
    pass_l1 = ~hist_fb["is_event_basket"]
    pass_l2 = ~hist_fb["is_dying_pulse"]
    pass_l3 = (hist_fb["plate_fb_cnt"] <= 1) | (
        (hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2))
    )
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
    is_hard_tech = hist_fb["plate"].astype(str).str.contains(
        r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)",
        regex=True,
    ).values
    has_ma_hard = (hist_fb["notice_hard"] | hist_fb["is_ma"]).values
    is_pure_outsider = np.array([ht and (cs in u.CSRC_PURE_OUTSIDER) and (not hm) for ht, cs, hm in zip(is_hard_tech, csrc_sec, has_ma_hard)], dtype=bool)
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
    sensors_map = df_daily_s.set_index("date")["roll20_ho_zt"].to_dict()
    roll20_vec = hist_fb["d2_dt"].map(sensors_map).fillna(0.45).values
    pen_thr_vec = np.where(roll20_vec < 0.45, 0.035, 0.031)
    pen_val_vec = np.where(roll20_vec < 0.45, 25.0, 15.0)
    q_pen = -np.where((~wk_mask.values) & (hist_fb["d2_o_pct"].values < pen_thr_vec), pen_val_vec, 0.0)

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

    price_pen = np.where(hist_fb["close"].values > 60.0, float(soft_pen_gt60), 0.0)
    sp_v = hist_fb["s_prior_wk"].values + name_sub20 + y_v17 * 0.5
    sq_v = hist_fb["s_quant_dual"].values + q_pen + d_ov + bon_tape + rk_fix_delta + y_v17 * 0.5 + price_pen
    sc_v = sp_v + sq_v + v18_pen
    hist_fb["score_active"] = sc_v

    p_tight = (hist_fb["d1_seal_tightness"] >= 37.0).values
    open_in_win = (
        (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
        | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
    ).values

    m_t1 = common_ok.values & open_in_win & (sp_v >= 45.0) & (sc_v >= thr_vec)
    mm = ((m_t1 & pass_l1.values & pass_l2.values & pass_l3.values & pass_nd_true.values & pass_ac.values) | (m_t2_base.values & pass_l2.values)) & p_tight
    mmon = (
        common_ok.values & wk_mask.values & hist_fb["d2_o_pct"].between(0.015, 0.090).values
        & (sp_v >= 38.0) & (sc_v >= thr_vec)
        & pass_l1.values & pass_l2.values & pass_l3.values & pass_nd_true.values & pass_ac.values & p_tight
    )
    tot_v18 = mm | (mmon & (~mm))
    sv_v18 = np.where(mm, sc_v + 1000.0, sc_v)

    rk_t = hist_fb["rk_theme"].fillna(99).values
    pos20_arr = hist_fb["f_pos20_d0"].fillna(0.5).values
    cat_ok = (hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"]).values
    xq2_arr = hist_fb["xq_pre_d2"].values
    lh_arr = hist_fb["lhb_lh_cnt_d1"].values
    syz_arr = hist_fb["surf_yz_d1"].values == 1

    fb_dom295 = (
        common_ok.values & open_in_win
        & pass_l1.values & pass_l2.values & pass_l3.values & pass_nd_true.values & pass_ac.values & p_tight
        & np.isin(rk_t, [2, 3]) & (tbrk == 1)
        & (xq2_arr < 4) & (pos20_arr <= 0.40) & cat_ok & (lh_arr == 0) & (~syz_arr)
        & ((sc_v - sc_t3_pen) >= 295.0)
    )
    tot_v19 = tot_v18 | fb_dom295
    sv_v19 = np.where(mm, sc_v + 1000.0, np.where(mmon, sc_v, sc_v + 500.0))

    dom_no_dragon, melee_days = set(), set()
    for d in sorted(daily_t1.index):
        t1_row = daily_t1.loc[d]
        t2_row = daily_t2.loc[d] if d in daily_t2.index else None
        t3_row = daily_t3.loc[d] if d in daily_t3.index else None
        t1_med = float(t1_row["p_theme_med"])
        t2_med = float(t2_row["p_theme_med"]) if t2_row is not None else 0.0
        t1_sz = int(t1_row["p_sz_max"])
        t2_sz = int(t2_row["p_sz_max"]) if t2_row is not None else 1
        if ((t1_med - t2_med) >= 20.0) or ((t1_sz >= 6) and (t1_sz / max(1, t2_sz) >= 2.0)):
            sub_d_v18 = hist_fb[(hist_fb["d2_dt"] == d) & tot_v18]
            if not (len(sub_d_v18) > 0 and (sub_d_v18["plate"] == t1_row["plate"]).any()):
                dom_no_dragon.add(d)
        if t1_row is not None and t2_row is not None and t3_row is not None:
            t3_med = float(t3_row["p_theme_med"])
            sz_max = max(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
            sz_min = min(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
            if (t1_med - t3_med) <= 15.0 and sz_max <= 5 and sz_min >= 2:
                melee_days.add(d)

    def apply_day_blocks(tot_mask, sv_arr):
        sub_t = hist_fb[tot_mask].copy()
        sub_t["_sv_tmp"] = sv_arr[tot_mask]
        bad_dts = set()
        for d, grp in sub_t.groupby("d2_dt"):
            if (grp["rk_theme"] == 1).any():
                top_rk = grp.sort_values("_sv_tmp", ascending=False).iloc[0]["rk_theme"]
                if pd.notna(top_rk) and top_rk >= 4:
                    bad_dts.add(d)
        res_mask = tot_mask & (~hist_fb["d2_dt"].isin(bad_dts)).values
        dom_blk = np.array([(d in dom_no_dragon and rk == 3) for d, rk in zip(hist_fb["d2_dt"], hist_fb["rk_theme"])], dtype=bool)
        mel_blk = np.array([
            (d in melee_days) and (not ((mrk <= 2) or bool(nh) or bool(hm)))
            for d, mrk, nh, hm in zip(hist_fb["d2_dt"], hist_fb["buyable_mkt_open_rk"], hist_fb["notice_hard"], hist_fb["is_ma"])
        ], dtype=bool)
        return res_mask & (~dom_blk) & (~mel_blk)

    final_v19_mask = apply_day_blocks(tot_v19, sv_v19)
    hist_fb["_sv_v19"] = sv_v19

    return {
        "all_dts": base_ctx["all_dts"],
        "dt_to_idx": base_ctx["dt_to_idx"],
        "price_lookup": base_ctx["price_lookup"],
        "amt_lookup": base_ctx["amt_lookup"],
        "tape_map": base_ctx["tape_map"],
        "xq_by_c6": base_ctx["xq_by_c6"],
        "bars_5m_map": base_ctx["bars_5m_map"],
        "hist_fb": hist_fb,
        "mask_v19": final_v19_mask,
    }
