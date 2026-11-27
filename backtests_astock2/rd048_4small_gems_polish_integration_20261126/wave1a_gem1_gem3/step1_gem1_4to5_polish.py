#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD048 Wave 1-A Gem 1 (`4to5` 114/120 tier):
  1. 100% exact baseline reproduction of `w2_4to5_v20_ledger.csv` (51 trades, 7.50x @ 20bps)
     + forward extension through 2026-11-24 (`stock_day_core_features_pit.parquet`) + 2021 coverage audit
  2. Exit-side polishing (strictly causal executable prices, zero high-peeking):
     native E4/E1/E2/E3 vs causal daily broken-ZT, yang immunity, V4.1 7-factor hold guard,
     official 10d dev 95%/100% red-line standing limit order (`sh000002`/`sz399107`), MA5, vol-break
  3. Entry-side low-DOF polishing + strictly causal Walk-Forward (`exit_date < t`):
     PIT lock/turnover, cold (<45/<50) vs active interaction, KPL theme, seal/open board,
     causal 4-way minefield blacklist (`m4_4way_bl`), causal Mode-B expanding delta card
  4. D15 (30/50/80bps, ex5, exact MTM Sharpe/MDD, CSI300 excess) + 4 small-sample tests
     + 2024-12-31 physical truncation verification (`max_abs_diff == 0.0`)
Zero yfinance (D12). Read-only on production files. Writes only to wave1a_gem1_gem3/.
"""
import json
import math
import os
import re
import resource
import sqlite3
import sys
import warnings
from typing import Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 VIOLATION"

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
import _common_rd048 as cm

ROOT = cm.ROOT
SIM = cm.SIM
OUT_DIR = cm.OUT_DIR
WAVE1_BASE = cm.WAVE1_BASE

P3_DIR = f"{SIM}/backtests_astock2/p3_deep_100"
RD036_DIR = f"{SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part2_other5"
sys.path.insert(0, P3_DIR)
sys.path.insert(0, RD036_DIR)
from w2_4to5_v20_scorecard import score_single_4to5_row
import run_m3_m4_3way_4way_trees as m34

TOX_RE = re.compile(r"(?:减持计划|股东减持|立案调查|收到立案|退市风险|违法违规)")
REG_INC = ("监管函", "关注函", "问询函", "监管工作函", "通报批评", "公开谴责", "立案", "风险提示")
REG_EXC = ("回复", "取消", "撤销", "解除", "不予")
DAY_SURF_RE = re.compile(r"(?:拉萨|东方财富证券|华宝证券.*(?:上海|东大名路)|华泰证券.*总部|中国银河.*北京中关村)")

WINDOWS_G1 = [
    ("Full_2022_2026", "2022-01-04", "2026-11-24"),
    ("5Y_2021_2026", "2021-01-04", "2026-11-24"),
    ("Recent_3Y_23_26", "2023-11-25", "2026-11-24"),
    ("Period_2023_2025", "2023-01-01", "2025-12-31"),
    ("Y2026", "2026-01-01", "2026-11-24"),
    ("Y26H2", "2026-07-01", "2026-11-24"),
]


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0)


def convert_fee_arr(r: np.ndarray, from_fee: float, to_fee: float) -> np.ndarray:
    return (1.0 + r) / (1.0 - from_fee) * (1.0 - to_fee) - 1.0


def load_daily_bars_rich(codes: set[str], max_dt: str = "2026-11-25") -> dict[str, dict]:
    """Load rich daily bar arrays (dts, open, high, low, close, adjf, pre_c, zt_px, dt_px, is_zt, is_dt, is_yizi_dt, amount, turn_pct, ma5) per c6."""
    import pyarrow.dataset as ds
    import pyarrow as pa
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    tks = sorted({f"{c}.SH" for c in codes} | {f"{c}.SZ" for c in codes})
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "amount", "volume"]
    flt = (ds.field("date") >= pd.Timestamp("2020-12-01")) & (ds.field("date") <= pd.Timestamp(max_dt)) & ds.field("ticker").isin(tks)
    frames = []
    for pq_path, dl_flag in [
        (f"{SIM}/data/cn_hk_price_db/a_daily.parquet", 0),
        (f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", 1),
    ]:
        sc_p = ds.dataset(pq_path, format="parquet").scanner(columns=cols, filter=flt, batch_size=65536, use_threads=False)
        for batch in sc_p.to_batches():
            dfb = batch.to_pandas()
            if not dfb.empty:
                dfb = dfb[dfb["volume"] > 0].copy()
                if not dfb.empty:
                    dfb["dl_flag"] = dl_flag
                    frames.append(dfb)
    pa.default_memory_pool().release_unused()
    if not frames:
        return {}
    df = pd.concat(frames, ignore_index=True)
    del frames
    df["c6"] = df["ticker"].astype(str).str[:6]
    df["dt"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values(["c6", "dt", "dl_flag"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)

    out = {}
    for c6, g in df.groupby("c6", sort=False):
        g = g.sort_values("dt").reset_index(drop=True)
        dts = g["dt"].tolist()
        op = g["open"].to_numpy(float)
        hi = g["high"].to_numpy(float)
        lo = g["low"].to_numpy(float)
        cl = g["close"].to_numpy(float)
        acl = g["adj_close"].to_numpy(float)
        amt = g["amount"].to_numpy(float)
        vol = g["volume"].to_numpy(float)
        adjf = np.where((cl > 0) & np.isfinite(acl) & (acl > 0), acl / cl, 1.0)
        n = len(dts)
        pre_c = np.zeros(n, dtype=float)
        pre_c[0] = cl[0]
        if n > 1:
            pre_c[1:] = cl[:-1] * adjf[:-1] / adjf[1:]
        zt_px = np.floor(pre_c * 1.10 * 100.0 + 0.5) / 100.0
        dt_px = np.floor(pre_c * 0.90 * 100.0 + 0.5) / 100.0
        pct = np.where(pre_c > 0, cl / pre_c - 1.0, 0.0)
        is_zt = (cl >= zt_px - 0.011) & (pct >= 0.095) & (pre_c > 0)
        is_dt = (cl <= dt_px + 0.011) & (pct <= -0.095) & (pre_c > 0)
        is_yizi_dt = is_dt & (op <= dt_px + 0.011) & (hi <= dt_px + 0.011)
        adj_cl = cl * adjf
        ma5_adj = pd.Series(adj_cl).rolling(5, min_periods=1).mean().to_numpy(float)
        ma5_vol = pd.Series(amt).rolling(5, min_periods=1).mean().to_numpy(float)
        out[c6] = {
            "dts": dts,
            "dt_idx": {d: i for i, d in enumerate(dts)},
            "open": op,
            "high": hi,
            "low": lo,
            "close": cl,
            "adjf": adjf,
            "pre_c": pre_c,
            "zt_px": zt_px,
            "dt_px": dt_px,
            "is_zt": is_zt,
            "is_dt": is_dt,
            "is_yizi_dt": is_yizi_dt,
            "amt": amt,
            "vol": vol,
            "ma5_adj": ma5_adj,
            "ma5_amt_prev": np.concatenate([[amt[0]], ma5_vol[:-1]]),
        }
    return out


def build_extension_20261110_20261124(
    df_e_cols: list[str],
    df_sc: pd.DataFrame,
    df_mk: pd.DataFrame,
    holders: dict,
    df_real_tox: pd.DataFrame,
    rich_bars: dict,
    cal_dts: list[str],
    max_dt: str = "2026-11-24",
) -> pd.DataFrame:
    """
    Extend `w2_4to5_enriched_master.parquet` cleanly from 2026-11-10 to `max_dt`
    using PIT `stock_day_core_features_pit`, `market_daily_all_new_factors_pit`,
    `zt_micro_tape_5y_pit.db`, `cninfo_notices_5y_pit.db`, `kpl_plates_2018_2026_merged.jsonl`,
    and `lhb_stockday_5y_pit`.
    """
    sub_sc = df_sc[(df_sc["dt"] >= "2026-11-10") & (df_sc["dt"] <= max_dt) & (df_sc["prev_streak"] == 4) & (~df_sc["is_st_pit"]) & (~df_sc["is_20cm"])].copy()
    if sub_sc.empty:
        return pd.DataFrame(columns=df_e_cols)

    con_zt = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    con_cn = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    kpl_by_dt = {}
    with open(f"{SIM}/data/kpl_plates_2018_2026_merged.jsonl", encoding="utf-8") as f:
        for ln in f:
            o = json.loads(ln)
            dt_k = str(o.get("date", ""))[:10]
            if "2026-11-01" <= dt_k <= max_dt:
                kpl_by_dt[dt_k] = o

    mk_map = df_mk.set_index("trade_date").to_dict("index")
    sc_dts = sorted(df_sc["dt"].unique())
    sc_dt_idx = {d: i for i, d in enumerate(sc_dts)}

    rows = []
    for r in sub_sc.itertuples(index=False):
        bd = str(r.dt)[:10]
        c6 = str(r.c6).zfill(6)
        bi = sc_dt_idx.get(bd)
        if bi is None or bi < 12:
            continue
        sd = sc_dts[bi - 1]
        d3d = sc_dts[bi - 2]

        # Rivals on buy_date
        rivals = df_sc[(df_sc["dt"] == bd) & (df_sc["prev_streak"] == 4) & (~df_sc["is_st_pit"]) & (~df_sc["is_20cm"]) & (df_sc["is_yizi_zt"] == 0)]
        # Also check non-yizi open
        non_yizi_rivals = rivals[rivals["open_pct"] < 9.90]
        b4_cnt = int(len(non_yizi_rivals))
        is_sole = int(b4_cnt <= 1)
        top_op = float(non_yizi_rivals["open_pct"].max()) if not non_yizi_rivals.empty else float(r.open_pct)
        is_top1 = int(float(r.open_pct) >= top_op - 1e-6)

        # D4 and D3 bars
        sc_d4 = df_sc[(df_sc["dt"] == sd) & (df_sc["c6"] == c6)]
        sc_d3 = df_sc[(df_sc["dt"] == d3d) & (df_sc["c6"] == c6)]
        d4_r = sc_d4.iloc[0] if not sc_d4.empty else None
        d3_r = sc_d3.iloc[0] if not sc_d3.empty else None

        zt4 = con_zt.execute("SELECT sec_name, first_seal_time, open_board_count, seal_amount FROM zt_micro_tape WHERE sec_code=? AND trade_date=?", (c6, sd)).fetchone()
        zt3 = con_zt.execute("SELECT open_board_count FROM zt_micro_tape WHERE sec_code=? AND trade_date=?", (c6, d3d)).fetchone()
        sec_name = zt4[0] if zt4 else c6

        # PIT notices
        d90 = (pd.Timestamp(bd) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
        d10 = (pd.Timestamp(bd) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        tox_sub = df_real_tox[(df_real_tox["sec_code"] == c6) & (df_real_tox["pub_datetime_cst"] >= d90) & (df_real_tox["pub_datetime_cst"] <= bd + " 09:25:00")]
        f_tox_90d = bool(not tox_sub.empty)
        nots10 = con_cn.execute("SELECT pub_datetime_cst, title FROM notices WHERE sec_code=? AND trade_date_avail>=? AND pub_datetime_cst<=?", (c6, d10, bd + " 09:25:00")).fetchall()
        has_reg = any(any(w in str(ti) for w in REG_INC) and not any(w in str(ti) for w in REG_EXC) for _, ti in nots10)
        has_tox_broad = f_tox_90d or any(("风险提示" in str(ti)) or ("减持" in str(ti)) for _, ti in nots10)

        # f47: 10d broken >=4b rebound rate strictly before bd
        w11 = sc_dts[bi - 11:bi]
        brk4 = df_sc[(df_sc["dt"].isin(w11[:-1])) & (df_sc["prev_streak"] >= 4) & (df_sc["is_zt"] == 0) & (~df_sc["is_st_pit"]) & (~df_sc["is_20cm"])].copy()
        if not brk4.empty:
            nxt_m = {w11[j]: w11[j + 1] for j in range(10)}
            brk4["ndt"] = brk4["dt"].map(nxt_m)
            m_reb = brk4[["c6", "ndt"]].merge(df_sc[["c6", "dt", "is_zt"]], left_on=["c6", "ndt"], right_on=["c6", "dt"], how="left")
            f47_val = float(m_reb["is_zt"].mean()) if len(m_reb) else 0.0
        else:
            f47_val = 0.0

        # plate_3b_cnt via KPL on sd
        plate_3b = 0
        s3_codes = set(df_sc[(df_sc["dt"] == sd) & (df_sc["streak"] == 3) & (~df_sc["is_st_pit"]) & (~df_sc["is_20cm"])]["c6"].tolist())
        ko = kpl_by_dt.get(sd)
        if ko:
            for pl in ko.get("plates", []):
                pcs = {str(s[0])[:6].zfill(6) for s in pl.get("stocks", [])}
                if c6 in pcs:
                    plate_3b = max(plate_3b, len(pcs & s3_codes))

        d4_nuke = int(len(df_sc[(df_sc["dt"] == sd) & (df_sc["prev_streak"] >= 2) & (df_sc["is_dt"] == 1) & (~df_sc["is_st_pit"])]))
        mk = mk_map.get(bd, {})
        op_dec = float(r.open_pct) / 100.0
        is_b6 = int((0.020 <= op_dec <= 0.075) and (r.is_yizi_zt == 0) and (op_dec < 0.098))
        cb = rich_bars.get(c6)
        buy_px = float(r.open)
        # Simulate E1/E4 causal daily trajectory on cb (no peeking high; check cut_weak + pure EOD + yang_imm)
        ret_e1 = np.nan
        exdt_e1 = None
        if is_b6 == 1 and cb is not None and bd in cb["dt_idx"]:
            pos = cb["dt_idx"][bd]
            is_zt_b = bool(cb["is_zt"][pos])
            o4, c4, p4 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])
            a4 = float(cb["adjf"][pos])
            if pos + 1 < len(cb["dts"]):
                k = pos + 1
                while k < len(cb["dts"]) and bool(cb["is_yizi_dt"][k]):
                    k += 1
                if k >= len(cb["dts"]):
                    k = len(cb["dts"]) - 1
                    exdt_e1 = cb["dts"][k]
                    spx, sa = float(cb["close"][k]), float(cb["adjf"][k])
                elif k > pos + 1:
                    exdt_e1 = cb["dts"][k]
                    spx, sa = float(cb["open"][k]), float(cb["adjf"][k])
                elif not is_zt_b:
                    o5, p5, c5 = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
                    d4_strong = (c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005)
                    if not d4_strong:
                        exdt_e1, spx, sa = cb["dts"][k], o5, float(cb["adjf"][k])
                    elif bool(cb["is_zt"][k]):
                        # ride
                        kk = k + 1
                        imm = False
                        while kk < len(cb["dts"]):
                            if bool(cb["is_yizi_dt"][kk]):
                                kk += 1
                                continue
                            if bool(cb["is_zt"][kk]):
                                kk += 1
                                continue
                            if (not imm) and (cb["close"][kk] > cb["open"][kk]) and (cb["close"][kk] >= cb["pre_c"][kk]):
                                imm = True
                                kk += 1
                                continue
                            exdt_e1, spx, sa = cb["dts"][kk], float(cb["close"][kk]), float(cb["adjf"][kk])
                            break
                        if exdt_e1 is None:
                            kk = len(cb["dts"]) - 1
                            exdt_e1, spx, sa = cb["dts"][kk], float(cb["close"][kk]), float(cb["adjf"][kk])
                    else:
                        exdt_e1, spx, sa = cb["dts"][k], c5, float(cb["adjf"][k])
                else:
                    kk = k
                    imm = False
                    while kk < len(cb["dts"]):
                        if bool(cb["is_yizi_dt"][kk]):
                            kk += 1
                            continue
                        if bool(cb["is_zt"][kk]):
                            kk += 1
                            continue
                        if (not imm) and (cb["close"][kk] > cb["open"][kk]) and (cb["close"][kk] >= cb["pre_c"][kk]):
                            imm = True
                            kk += 1
                            continue
                        exdt_e1, spx, sa = cb["dts"][kk], float(cb["close"][kk]), float(cb["adjf"][kk])
                        break
                    if exdt_e1 is None:
                        kk = len(cb["dts"]) - 1
                        exdt_e1, spx, sa = cb["dts"][kk], float(cb["close"][kk]), float(cb["adjf"][kk])
                if exdt_e1 is not None:
                    ret_e1 = (spx * sa) / (buy_px * a4) * (1.0 - 0.0020) - 1.0

        row_d = {col: np.nan for col in df_e_cols}
        row_d.update({
            "code": c6,
            "name": sec_name,
            "sig_date": sd,
            "buy_date": bd,
            "prev_streak": 4,
            "prev_is_yizi": bool(d4_r["is_yizi_zt"]) if d4_r is not None else False,
            "open_pct": op_dec,
            "pct": float(r.ret_1d) / 100.0,
            "buyable_open": bool(r.is_yizi_zt == 0 and op_dec < 0.098),
            "is_yizi_open": bool(op_dec >= 0.098 and r.is_yizi_zt == 1),
            "is_zt_today": bool(r.is_zt == 1),
            "touch_zt_today": bool(r.hit_zt == 1),
            "mkt_max_board_prev": int(mk.get("L1_max_board_t1", 4)),
            "mkt_zt_prev": float(mk.get("L1_zt_cnt_t1", 50.0)),
            "lock_top10": float(r.lock_top10_pct_pre) if pd.notna(r.lock_top10_pct_pre) else 0.0,
            "real_free_mcap": float(r.free_mcap_yi_t1) if pd.notna(r.free_mcap_yi_t1) else 20.0,
            "prev_real_to": float(r.real_turn_pct_t1) if pd.notna(r.real_turn_pct_t1) else np.nan,
            "prev_amt": float(r.amount_yi_t1) * 1e8 if pd.notna(r.amount_yi_t1) else np.nan,
            "first_seal_time": str(zt4[1]) if zt4 else "",
            "open_board_count": int(zt4[2]) if zt4 else int(r.d1_open_board_cnt_t1 if pd.notna(r.d1_open_board_cnt_t1) else 0),
            "seal_amount": float(zt4[3]) if zt4 else 0.0,
            "d3_open_board_count": float(zt3[0]) if zt3 else 0.0,
            "is_sole_4b": is_sole,
            "is_top1_4b_open": is_top1,
            "b4_rival_cnt": b4_cnt,
            "px_d4": float(d4_r["close"]) if d4_r is not None else buy_px / (1.0 + op_dec),
            "to_ratio_d4_d3": float(d4_r["turn_pct"] / max(1e-6, d3_r["turn_pct"])) if (d4_r is not None and d3_r is not None) else 1.0,
            "has_stock_reg": int(has_reg),
            "has_tox_notice": int(has_tox_broad),
            "f_tox_90d": f_tox_90d,
            "f_s_reg_10d": bool(has_reg),
            "tighter_headroom_pit": float(min(r.hr10d_space_t1, r.hr30d_space_t1)) / 100.0 if pd.notna(r.hr10d_space_t1) else 0.25,
            "B6_auc_sweet_2_7_bought": is_b6,
            "B6_auc_sweet_2_7_px": buy_px,
            "B6_auc_sweet_2_7_hhmm": 925,
            "ret_B6_auc_sweet_2_7_E1_3to4_std": ret_e1,
            "exdt_B6_auc_sweet_2_7_E1_3to4_std": exdt_e1,
            "ret_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff": ret_e1,
            "exdt_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff": exdt_e1,
            "ret_B6_auc_sweet_2_7_E2_dev93_always": ret_e1,
            "exdt_B6_auc_sweet_2_7_E2_dev93_always": exdt_e1,
            "ret_B6_auc_sweet_2_7_E3_F62_staged_dev93": ret_e1,
            "exdt_B6_auc_sweet_2_7_E3_F62_staged_dev93": exdt_e1,
            "f61_eligible": False,
            "f47_reb_zt_r10": f47_val,
            "f_d4_quant_sell": int(r.lhb_has_quant_t1) if pd.notna(r.lhb_has_quant_t1) else 0,
            "f52_d4_inst_sell": 1 if (pd.notna(r.lhb_inst_net_yi_t1) and float(r.lhb_inst_net_yi_t1) < -0.1) else 0,
            "f50_d4_top_yz_new_buy": False,
            "f51_d4_lh_cnt": int(round(float(r.lhb_lhasa_share_t1) * 5)) if pd.notna(r.lhb_lhasa_share_t1) else 0,
            "plate_3b_cnt": plate_3b,
            "d4_mkt_nuke_cnt": d4_nuke,
            "d4_v34_score": -999.0,
            "is_held_3to4": False,
            "d4_open_pct": float(d4_r["open_pct"]) / 100.0 if d4_r is not None else 0.0,
            "d4_buyable_open": bool(d4_r["is_yizi_zt"] == 0) if d4_r is not None else True,
            "d3_prev_is_yizi": bool(d3_r["is_yizi_zt"]) if d3_r is not None else False,
            "d4_blown_pm_5m": False,
            "d4_blown_pm_proxy": False,
            "is_post_holiday_or_mon_pit": bool(pd.Timestamp(bd).weekday() == 0),
            "dow": pd.Timestamp(bd).weekday() + 1,
            "buy_month": pd.Timestamp(bd).month,
        })
        rows.append(row_d)

    con_zt.close()
    con_cn.close()
    return pd.DataFrame(rows, columns=df_e_cols) if rows else pd.DataFrame(columns=df_e_cols)


def score_fixed_4to5(r: dict, holders: dict, df_real_tox: pd.DataFrame) -> tuple[int, str]:
    """Exact bug-fixed PIT scorecard from `run_partC_aux_clean_rebacktest.py::run_ref_4to5_fixed`."""
    if not (r.get("buyable_open") is True):
        return -999, "fail_not_buyable"
    c6_val = str(r["code"]).zfill(6)
    bd = str(r["buy_date"])[:10]
    d90 = (pd.Timestamp(bd) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    t_sub = df_real_tox[(df_real_tox["sec_code"] == c6_val) & (df_real_tox["pub_datetime_cst"] >= d90) & (df_real_tox["pub_datetime_cst"] <= bd + " 09:25:00")]
    if not t_sub.empty:
        return -999, "fail_tox_notice"
    if r.get("f_s_reg_10d", False) or (float(r.get("has_stock_reg", 0) or 0) > 0):
        return -999, "fail_stock_reg"
    if float(r.get("tighter_headroom_pit", 0.0) or 0.0) < 0.12:
        return -999, "fail_headroom_lt12"
    if r.get("d4_blown_pm_5m", False) or r.get("d4_blown_pm_proxy", False):
        return -999, "fail_d4_blown_pm"
    op_pct = float(r.get("open_pct", 0.0) or 0.0)
    if op_pct < 0.020 or op_pct > 0.075:
        return -999, "fail_open_not_sweet"

    score = 100
    raw_h = holders.get(c6_val, [])
    sd = str(r.get("sig_date", bd))[:10]
    h_list = [x for x in raw_h if isinstance(x, (list, tuple)) and len(x) > 2 and str(x[0]) <= sd]
    if h_list:
        lock_top10 = float(max(h_list, key=lambda x: str(x[1]))[2])
    else:
        h_dict = [x for x in raw_h if isinstance(x, dict) and str(x.get("ann_date", "")) <= sd]
        lock_top10 = float(h_dict[-1].get("top10_ratio", 0.0)) if h_dict else float(r.get("lock_top10", 0.0) or 0.0)
    real_mcap = float(r.get("real_free_mcap", 20.0) or 20.0)
    if (lock_top10 >= 50.0) and (12.0 <= real_mcap <= 35.0):
        score += 8
    elif (lock_top10 >= 45.0) or (real_mcap >= 45.0):
        score += 3
    elif (lock_top10 < 45.0) and (real_mcap < 45.0):
        score -= 8

    hr_pit = float(r.get("tighter_headroom_pit", 0.0) or 0.0)
    if hr_pit >= 0.25:
        score += 6
    elif hr_pit >= 0.22:
        score += 4

    max_b = int(r.get("mkt_max_board_prev", 0) or 0)
    if max_b == 4:
        score += 5
    elif max_b == 5:
        score += 2
    elif max_b >= 6:
        score -= 5

    is_sole = int(r.get("is_sole_4b", 0) or 0) == 1
    if is_sole:
        score += 6
    elif int(r.get("is_top1_4b_open", 0) or 0) == 1 and int(r.get("b4_rival_cnt", 0) or 0) < 2:
        score += 3
    else:
        score -= 5

    d4_s34 = float(r.get("d4_v34_score", -999) or -999)
    if (82.0 <= d4_s34 <= 89.0) and is_sole:
        score += 5
    if bool(r.get("is_held_3to4", False)):
        score += 4
    d4_op = float(r.get("d4_open_pct", 0.0) or 0.0)
    d4_buyable = bool(r.get("d4_buyable_open", True))
    d3_yizi = bool(r.get("d3_prev_is_yizi", False))
    if ((d4_op > 0.092) or (not d4_buyable) or d3_yizi) and (0.020 <= op_pct <= 0.060):
        score += 3
    obc = int(r.get("open_board_count", 0) or 0)
    d3_obc = int(r.get("d3_open_board_count", 0) or 0)
    to_r = float(r.get("to_ratio_d4_d3", 1.0) or 1.0)
    if (obc >= 1) and (d3_obc >= 1) and (0.70 <= to_r <= 1.35):
        score += 3

    if int(r.get("f_d4_quant_sell", 0) or 0) >= 1:
        score -= 5
    if int(r.get("f52_d4_inst_sell", 0) or 0) >= 1:
        score -= 3
    if bool(r.get("f50_d4_top_yz_new_buy", False)):
        score -= 3
    if int(r.get("f51_d4_lh_cnt", 0) or 0) >= 3:
        score -= 6

    if int(r.get("plate_3b_cnt", 0) or 0) >= 1:
        score -= 6
    if float(r.get("px_d4", 0.0) or 0.0) > 20.0:
        score -= 6
    if int(r.get("d4_mkt_nuke_cnt", 0) or 0) >= 1:
        score -= 3
    if float(r.get("f47_reb_zt_r10", 0.0) or 0.0) >= 0.20:
        score += 6
    dow = int(r.get("dow", 0) or 0)
    if dow == 1 or bool(r.get("is_post_holiday_or_mon_pit", False)):
        score += 6
    elif dow in (4, 5):
        score -= 3
    mo = int(r.get("buy_month", 0) or 0)
    if mo in (1, 5):
        score -= 6
    return score, "pass"


def build_daily_7factor_hold_map(
    codes: set[str],
    df_mk: pd.DataFrame,
    df_sc: pd.DataFrame,
    rich_bars: dict,
    max_dt: str = "2026-11-25",
) -> tuple[dict, dict, dict, dict]:
    """Build causal t-1 risk lookup tables for V4.1 7 hold-risk factors (zero future peek)."""
    # 1. KPL plate Elo (daily) from kpl_plates_2018_2026_merged.jsonl -> streaming tracker (zero full-list RAM spike)
    kpl_stock_elo = {}
    plate_elo = {}
    kpl_recs = []
    with open(f"{SIM}/data/kpl_plates_2018_2026_merged.jsonl", encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            o = json.loads(ln)
            dt_k = str(o.get("date", ""))[:10]
            if dt_k <= max_dt:
                kpl_recs.append((dt_k, [(pl.get("plate", ""), [str(s[0])[:6].zfill(6) for s in pl.get("stocks", [])]) for pl in o.get("plates", [])]))
    kpl_recs.sort(key=lambda x: x[0])
    for dt_k, pls in kpl_recs:
        seen = set()
        for rk, (pn, stks) in enumerate(pls):
            seen.add(pn)
            cur = plate_elo.get(pn, 100.0)
            target = 145.0 if rk == 0 else (130.0 if rk <= 2 else 110.0)
            plate_elo[pn] = cur * 0.8 + target * 0.2
            for sc6 in stks:
                if sc6 in codes:
                    prev_e = kpl_stock_elo.get((sc6, dt_k), 100.0)
                    kpl_stock_elo[(sc6, dt_k)] = max(prev_e, plate_elo[pn])
        for pn in list(plate_elo.keys()):
            if pn not in seen:
                plate_elo[pn] = 100.0 + (plate_elo[pn] - 100.0) * 0.85
    del kpl_recs

    # 2. LHB inst sell > 20M & day-surf buyer by (c6, dt) using low-RAM pyarrow scanner
    import pyarrow as pa
    import pyarrow.dataset as ds
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    lhb_risk = {}
    tks_lhb = sorted(codes)
    for fn, is_buy in [("lhb_buy.parquet", True), ("lhb_sell.parquet", False)]:
        sc_lhb = ds.dataset(f"{SIM}/backtest/2026-10-20-lhasa/{fn}", format="parquet").scanner(
            columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY", "SELL"],
            filter=ds.field("SECURITY_CODE").isin(tks_lhb),
            batch_size=65536,
            use_threads=False,
        )
        for batch in sc_lhb.to_batches():
            d = batch.to_pandas()
            if d.empty:
                continue
            d["c6"] = d["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
            d = d[d["c6"].isin(codes)].copy()
            d["dt"] = d["TRADE_DATE"].astype(str).str[:10]
            d = d[d["dt"] <= max_dt]
            for r in d.itertuples(index=False):
                k = (r.c6, r.dt)
                cur = lhb_risk.setdefault(k, [0.0, 0.0, False])
                nm = str(r.OPERATEDEPT_NAME or "")
                if "机构专用" in nm:
                    cur[0] += float(r.SELL or 0.0)
                    cur[1] += float(r.BUY or 0.0)
                if is_buy and DAY_SURF_RE.search(nm):
                    cur[2] = True

    # 3. Reg notices by (c6, pub_datetime_cst)
    reg_dates = {}
    con_cn = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    ph = ",".join("?" for _ in codes)
    for sc, pdt, ti in con_cn.execute(f"SELECT sec_code, pub_datetime_cst, title FROM notices WHERE sec_code IN ({ph}) AND pub_datetime_cst <= ?", (*sorted(codes), max_dt + " 23:59:59")):
        ti_s = str(ti or "")
        if any(w in ti_s for w in REG_INC) and not any(w in ti_s for w in REG_EXC):
            reg_dates.setdefault(str(sc).zfill(6), []).append(str(pdt)[:19])
    con_cn.close()

    # 4. CSI300 f6 & 4b+ reb_r10 f7 by dt
    mk_map = df_mk[df_mk["trade_date"] <= max_dt].set_index("trade_date").to_dict("index")
    # Precompute daily 4b+ reb_r10 cleanly from df_sc
    sc4 = df_sc[(df_sc["dt"] <= max_dt) & (df_sc["prev_streak"] >= 4) & (df_sc["is_zt"] == 0) & (~df_sc["is_st_pit"]) & (~df_sc["is_20cm"])][["dt", "c6"]].copy()
    dts_sc = sorted(df_sc[df_sc["dt"] <= max_dt]["dt"].unique())
    dt_nxt = {dts_sc[i]: dts_sc[i + 1] for i in range(len(dts_sc) - 1)}
    sc4["ndt"] = sc4["dt"].map(dt_nxt)
    sc4 = sc4.dropna(subset=["ndt"]).merge(df_sc[["dt", "c6", "is_zt"]], left_on=["ndt", "c6"], right_on=["dt", "c6"], how="left", suffixes=("_b", "_n"))
    reb_by_dt = sc4.groupby("ndt")["is_zt"].agg(["sum", "count"]).to_dict("index")
    f7_by_dt = {}
    q_hist = []
    for dt_v in dts_sc:
        if len(q_hist) >= 1:
            w10 = q_hist[-10:]
            sn, sd = sum(x[0] for x in w10), sum(x[1] for x in w10)
            f7_by_dt[dt_v] = (sn / max(1, sd)) < 0.20 if sd > 0 else False
        else:
            f7_by_dt[dt_v] = False
        st = reb_by_dt.get(dt_v)
        q_hist.append((int(st["sum"]), int(st["count"])) if st else (0, 0))

    return kpl_stock_elo, lhb_risk, reg_dates, (mk_map, f7_by_dt)


def sim_causal_daily_exit(
    c6: str,
    bd: str,
    buy_px: float,
    cb: dict,
    idx_map: dict,
    exit_rule: str,
    fee: float,
    risk_ctx: tuple,
) -> tuple[Optional[str], float, int]:
    """
    Strictly causal daily executable exit simulator (zero future high peeking):
      - `E_PureBreak_EOD`: Day 0 non-ZT cut_weak else Day k first non-ZT EOD close (defer is_dt!)
      - `E_YangImm1_EOD`: Same + 1-time true-yang (close > open & close >= pre_c) immunity
      - `E_Abn95_Limit` / `E_Abn100_Limit`: Standing 09:25 conditional limit order at official 10d dev red-line
        using idx_{t-1} (strictly causal at 09:25!) + E_YangImm1_EOD fallback
      - `E_7Factor_Guard`: V4.1 7 hold-risk factors (t-1): risk_pts >= 2 revokes yang immunity & cuts weak open < pre_c
      - `E_MA5_Close`: Close < MA5 stop (if held past Day 0 ZT) else E_YangImm1_EOD
      - `E_VolBreak_EOD`: Vol > 2.0 * ma5_amt on unsealed day revokes yang immunity
    """
    if cb is None or bd not in cb["dt_idx"]:
        return None, np.nan, 1500
    pos = cb["dt_idx"][bd]
    n = len(cb["dts"])
    if pos + 1 >= n:
        return None, np.nan, 1500

    a0 = float(cb["adjf"][pos])
    is_zt0 = bool(cb["is_zt"][pos])
    o0, c0, p0 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])

    def _sell_ret(k_idx: int, px: float) -> float:
        return (px * float(cb["adjf"][k_idx])) / (buy_px * a0) * (1.0 - fee) - 1.0

    def _defer_dt(k_idx: int) -> tuple[str, float, int]:
        kk = k_idx + 1
        while kk < n and bool(cb["is_yizi_dt"][kk]):
            kk += 1
        if kk >= n:
            kk = n - 1
            return cb["dts"][kk], _sell_ret(kk, float(cb["close"][kk])), 1500
        return cb["dts"][kk], _sell_ret(kk, float(cb["open"][kk])), 925

    kpl_elo, lhb_risk, reg_dates, (mk_map, f7_by_dt) = risk_ctx

    def _calc_7risk(dt_prev: str, k_idx: int) -> int:
        pts = 0
        if kpl_elo.get((c6, dt_prev), 100.0) >= 135.0:
            pts += 1
        lr = lhb_risk.get((c6, dt_prev))
        if lr is not None:
            if lr[0] > 2e7 or (lr[0] - lr[1]) > 2e7:
                pts += 1
            if lr[2]:
                pts += 1
        if cb["amt"][k_idx - 1] > 3.5 * max(1.0, cb["ma5_amt_prev"][k_idx - 1]):
            pts += 1
        lo_ts, hi_ts = f"{bd} 09:25:00", f"{cb['dts'][k_idx]} 09:25:00"
        if any(lo_ts <= ts < hi_ts for ts in reg_dates.get(c6, [])):
            pts += 1
        if mk_map.get(cb["dts"][k_idx], {}).get("mkt_csi300_ret1d_t1", 0.0) <= -2.0:
            pts += 1
        if f7_by_dt.get(cb["dts"][k_idx], False):
            pts += 1
        return pts

    # Day 0 unsealed
    k_start = pos + 1
    if not is_zt0:
        if bool(cb["is_yizi_dt"][k_start]):
            return _defer_dt(k_start)
        o5, p5, c5 = float(cb["open"][k_start]), float(cb["pre_c"][k_start]), float(cb["close"][k_start])
        d4_strong = (c0 >= o0) and (c0 >= p0) and (o5 >= p5 * 1.005)
        if not d4_strong:
            return cb["dts"][k_start], _sell_ret(k_start, o5), 925
        if not bool(cb["is_zt"][k_start]):
            if bool(cb["is_dt"][k_start]):
                return _defer_dt(k_start)
            return cb["dts"][k_start], _sell_ret(k_start, c5), 1500
        k_start += 1

    # Ride ZT streak
    imm_used = False
    k = k_start
    while k < n:
        dt_k = cb["dts"][k]
        dt_prev = cb["dts"][k - 1]
        if bool(cb["is_yizi_dt"][k]):
            k += 1
            continue

        # Standing causal 10d dev limit sell using idx_{t-1} known at 09:25
        if exit_rule in ("E_Abn95_Limit", "E_Abn100_Limit"):
            dev_thr = 0.95 if exit_rule == "E_Abn95_Limit" else 1.00
            idx_prev = idx_map.get(dt_prev)
            if idx_prev and k >= 10:
                p_caps = []
                for lb in range(1, 11):
                    j = k - lb
                    if j < 0:
                        continue
                    idx_base = idx_map.get(cb["dts"][j])
                    if not idx_base or idx_base <= 0:
                        continue
                    idx_ret = idx_prev / idx_base - 1.0
                    base_adj = float(cb["close"][j] * cb["adjf"][j])
                    # target_adj = base_adj * (1 + idx_ret + dev_thr)
                    t_raw = base_adj * (1.0 + idx_ret + dev_thr) / float(cb["adjf"][k])
                    p_caps.append(math.ceil(t_raw * 100.0 - 1e-12) / 100.0)
                if p_caps:
                    trig_px = min(p_caps)
                    ok, hk, dt_p = float(cb["open"][k]), float(cb["high"][k]), float(cb["dt_px"][k])
                    if ok >= trig_px:
                        if not bool(cb["is_yizi_dt"][k]):
                            return dt_k, _sell_ret(k, ok), 925
                    elif hk >= trig_px + 0.01 and trig_px > dt_p + 0.01:
                        return dt_k, _sell_ret(k, trig_px), 1030

        if exit_rule == "E_7Factor_Guard":
            rpts = _calc_7risk(dt_prev, k)
            if rpts >= 2 and float(cb["open"][k]) < float(cb["pre_c"][k]):
                return dt_k, _sell_ret(k, float(cb["open"][k])), 925

        if bool(cb["is_zt"][k]):
            k += 1
            continue

        # Unsealed day
        if exit_rule == "E_MA5_Close":
            cur_adj = float(cb["close"][k] * cb["adjf"][k])
            if cur_adj < float(cb["ma5_adj"][k]):
                if bool(cb["is_dt"][k]):
                    return _defer_dt(k)
                return dt_k, _sell_ret(k, float(cb["close"][k])), 1500
            k += 1
            continue

        allow_imm = False
        if exit_rule in ("E_YangImm1_EOD", "E_Abn95_Limit", "E_Abn100_Limit", "E_7Factor_Guard", "E_VolBreak_EOD"):
            allow_imm = (not imm_used) and (cb["close"][k] > cb["open"][k]) and (cb["close"][k] >= cb["pre_c"][k])
            if exit_rule == "E_7Factor_Guard" and _calc_7risk(dt_prev, k) >= 2:
                allow_imm = False
            if exit_rule == "E_VolBreak_EOD" and cb["amt"][k] > 2.0 * max(1.0, cb["ma5_amt_prev"][k]):
                allow_imm = False

        if allow_imm:
            imm_used = True
            k += 1
            continue

        if bool(cb["is_dt"][k]):
            return _defer_dt(k)
        return dt_k, _sell_ret(k, float(cb["close"][k])), 1500

    k = n - 1
    return cb["dts"][k], _sell_ret(k, float(cb["close"][k])), 1500


def build_causal_wf_variants(
    df_b6: pd.DataFrame,
    v20_scores: np.ndarray,
    fix_scores: np.ndarray,
    ret_arr_030: np.ndarray,
    wf_start: str = "2023-01-03",
) -> dict[str, dict]:
    """
    Strictly causal expanding Walk-Forward variants (`exit_date < t`) on 4to5 B6 pool:
      1) `WF_4Way_BL` (`m4_4way_bl`): 4-way causal minefield blacklist fitted on all B6 passing hard gates
      2) `WF_ModeB_ColdActive`: discrete interpretable Mode-B delta + cold/active interaction fitted strictly `exit_date < t`
    """
    n = len(df_b6)
    bd_arr = df_b6["buy_date"].astype(str).to_numpy()
    ex_arr = df_b6["exit_date"].astype(str).to_numpy()

    # Discrete interpretable binary matrix (strictly 09:25 PIT) for causal 4-way & Mode-B
    feats = {
        "cold_zt45": (df_b6["mkt_zt_prev"].fillna(60) < 45).to_numpy(np.int8),
        "cold_zt50": (df_b6["mkt_zt_prev"].fillna(60) < 50).to_numpy(np.int8),
        "lock45": (df_b6["lock_top10"].fillna(0) >= 45).to_numpy(np.int8),
        "lock50": (df_b6["lock_top10"].fillna(0) >= 50).to_numpy(np.int8),
        "low_lock": (df_b6["lock_top10"].fillna(0) < 45).to_numpy(np.int8),
        "small_mcap": (df_b6["real_free_mcap"].fillna(25) <= 35).to_numpy(np.int8),
        "hr_ge22": (df_b6["tighter_headroom_pit"].fillna(0) >= 0.22).to_numpy(np.int8),
        "sole_4b": (df_b6["is_sole_4b"].fillna(0) == 1).to_numpy(np.int8),
        "rival_ge2": (df_b6["b4_rival_cnt"].fillna(1) >= 2).to_numpy(np.int8),
        "open_3_6": ((df_b6["open_pct"] >= 0.030) & (df_b6["open_pct"] <= 0.060)).to_numpy(np.int8),
        "open_lt35": (df_b6["open_pct"] < 0.035).to_numpy(np.int8),
        "d4_yizi": (df_b6["prev_is_yizi"].fillna(False).astype(bool) | (~df_b6["d4_buyable_open"].fillna(True).astype(bool))).to_numpy(np.int8),
        "obc_ge1": (df_b6["open_board_count"].fillna(0) >= 1).to_numpy(np.int8),
        "seal_early": (df_b6["first_seal_time"].astype(str) <= "09:45:00").to_numpy(np.int8),
        "seal_late": (df_b6["first_seal_time"].astype(str) >= "13:00:00").to_numpy(np.int8),
        "kpl_in": (df_b6["kpl_in_t1"].fillna(0) == 1).to_numpy(np.int8),
        "nuke_ge1": (df_b6["d4_mkt_nuke_cnt"].fillna(0) >= 1).to_numpy(np.int8),
        "reb_r20": (df_b6["f47_reb_zt_r10"].fillna(0) >= 0.20).to_numpy(np.int8),
        "hi_to25": (df_b6["prev_real_to"].fillna(20) >= 25.0).to_numpy(np.int8),
        "maxb_ge6": (df_b6["mkt_max_board_prev"].fillna(4) >= 6).to_numpy(np.int8),
        "px_gt20": (df_b6["px_d4"].fillna(10) > 20.0).to_numpy(np.int8),
        "mon_post": ((df_b6["dow"].fillna(2) == 1) | df_b6["is_post_holiday_or_mon_pit"].fillna(False).astype(bool)).to_numpy(np.int8),
        "thu_fri": (df_b6["dow"].fillna(2).isin([4, 5])).to_numpy(np.int8),
    }
    base_names = list(feats.keys())
    Xb = np.column_stack([feats[k] for k in base_names]).astype(np.int8)
    y_win = (ret_arr_030 > 0).astype(float)

    # Gate-passing pool mask (non -999 on v20)
    gate_ok = v20_scores > -500
    # Monthly expanding refit (deterministic, zero future peek because fit only uses ex_arr < month_start)
    # To guarantee EXACT daily causality `exit_date < bd[i]`, refit at every unique trade date `dt` when settled pool changes!
    uniq_dts = sorted(set(bd_arr[bd_arr >= wf_start]))
    dt_to_rows = {d: np.where(bd_arr == d)[0] for d in uniq_dts}

    bl_mask_v20 = np.ones(n, dtype=bool)
    bl_mask_fix = np.ones(n, dtype=bool)
    modeb_delta = np.zeros(n, dtype=float)
    last_fit_cnt = -1
    cur_card_m4 = None
    cur_card_mb = None

    # Precompute integer day_ids
    all_bd_sorted = sorted(set(bd_arr))
    bd_id_map = {d: j for j, d in enumerate(all_bd_sorted)}
    day_ids = np.array([bd_id_map[d] for d in bd_arr], dtype=int)

    for dt_v in uniq_dts:
        r_idx = dt_to_rows[dt_v]
        # Strictly settled before dt_v: exit_date < dt_v
        tr_mask = gate_ok & (ex_arr < dt_v) & (ex_arr != "None") & np.isfinite(ret_arr_030)
        tr_cnt = int(tr_mask.sum())
        if tr_cnt < 30:
            continue
        if tr_cnt != last_fit_cnt:
            last_fit_cnt = tr_cnt
            # Causal 4-way minefield blacklist (`m4_4way_bl` style, min_leaf=8 for small 4to5 pool)
            cur_card_m4 = m34.fit_4way_synergy_card(
                Xb[tr_mask], ret_arr_030[tr_mask], y_win[tr_mask], day_ids[tr_mask],
                base_names, min_leaf=8, min_days=6, max_deltas=(10, 15),
                orig_tr=v20_scores[tr_mask], mode="minefield_bl",
                t_min_4way=1.8, t_syn_min=1.2, top_k_rules=3, shrink_tau=15.0,
            )
            # Causal Mode-B discrete L1-shrunk delta on single features + cold*feature pairs
            yr_tr = ret_arr_030[tr_mask]
            mu0 = float(yr_tr.mean())
            x_tr = Xb[tr_mask]
            # Single + key cold/active interactions
            cold_c = x_tr[:, base_names.index("cold_zt50")]
            deltas_1d = []
            for j, nm in enumerate(base_names):
                mj = x_tr[:, j] == 1
                cnt = int(mj.sum())
                if cnt >= 12 and (tr_cnt - cnt) >= 12:
                    d_mu = float(yr_tr[mj].mean() - mu0)
                    se = float(np.std(yr_tr[mj], ddof=1) / math.sqrt(cnt)) if cnt > 1 else 1.0
                    t_v = d_mu / max(1e-4, se)
                    if abs(t_v) >= 1.4:
                        shr = d_mu * (cnt / (cnt + 20.0)) * 100.0
                        deltas_1d.append((j, -1, float(np.clip(round(shr), -6, 6))))
                # Cold x lock/sole interaction
                if nm in ("lock45", "sole_4b", "kpl_in", "seal_early", "open_3_6"):
                    m_ic = (x_tr[:, j] == 1) & (cold_c == 1)
                    cnt_c = int(m_ic.sum())
                    if cnt_c >= 8:
                        d_muc = float(yr_tr[m_ic].mean() - mu0)
                        sec = float(np.std(yr_tr[m_ic], ddof=1) / math.sqrt(cnt_c)) if cnt_c > 1 else 1.0
                        if abs(d_muc / max(1e-4, sec)) >= 1.5:
                            shrc = d_muc * (cnt_c / (cnt_c + 18.0)) * 100.0
                            deltas_1d.append((j, base_names.index("cold_zt50"), float(np.clip(round(shrc), -6, 6))))
            cur_card_mb = deltas_1d

        if cur_card_m4 is not None and cur_card_m4.get("mine_rules"):
            for rl in cur_card_m4["mine_rules"]:
                idxs = [base_names.index(c) for c in rl["conj"]]
                hit = np.all(Xb[r_idx][:, idxs] == 1, axis=1)
                bl_mask_v20[r_idx] &= ~hit
                bl_mask_fix[r_idx] &= ~hit

        if cur_card_mb:
            for j1, j2, pts in cur_card_mb:
                if j2 < 0:
                    hit = Xb[r_idx, j1] == 1
                else:
                    hit = (Xb[r_idx, j1] == 1) & (Xb[r_idx, j2] == 1)
                modeb_delta[r_idx] += np.where(hit, pts, 0.0)

    return {
        "bl_mask": bl_mask_v20,
        "modeb_delta": modeb_delta,
        "wf_start": wf_start,
    }


def make_isomorphic_rows(
    df: pd.DataFrame,
    variant_name: str,
    is_slot: bool,
    score_col: str,
    ret_020: np.ndarray,
    ret_030: np.ndarray,
    ret_050: np.ndarray,
    ret_080: np.ndarray,
    cal_dts: list[str],
    bar_lu: dict,
    exit_hhmm_col: Optional[str] = None,
) -> pd.DataFrame:
    out = pd.DataFrame({
        "buy_date": df["buy_date"].astype(str).str[:10],
        "buy_hhmm": np.full(len(df), 925, dtype="int64"),
        "exit_date": df["exit_date"].astype(str).str[:10],
        "exit_hhmm": df[exit_hhmm_col].astype("int64") if (exit_hhmm_col and exit_hhmm_col in df.columns) else np.full(len(df), 1500, dtype="int64"),
        "code": df["code"].astype(str).str.zfill(6),
        "name": df["name"].astype(str),
        "strategy": np.full(len(df), "4to5"),
        "tier": np.where(df[score_col] >= 120, "120_high", "114_std"),
        "score": df[score_col].astype("float64"),
        "net_ret": ret_030.astype("float64"),
        "buy_price_val": df["buy_price_val"].astype("float64"),
        "is_adj_px": np.full(len(df), False, dtype="bool"),
        "is_untrig": np.full(len(df), False, dtype="bool"),
        "prio": np.full(len(df), 3, dtype="int64"),
        "phase": np.full(len(df), 1, dtype="int64"),
    })
    out["mtm_pairs_json"] = cm.build_mtm_pairs_for_trades(out, cal_dts, bar_lu, ret_col="net_ret", px_col="buy_price_val")
    out["variant"] = variant_name
    out["is_single_slot"] = bool(is_slot)
    out["gross_ret"] = ((1.0 + ret_030) / (1.0 - 0.0030) - 1.0).astype("float64")
    out["net_ret_020"] = ret_020.astype("float64")
    out["net_ret_030"] = ret_030.astype("float64")
    out["net_ret_050"] = ret_050.astype("float64")
    out["net_ret_080"] = ret_080.astype("float64")
    return out


def run_all_gem1(trunc_date: Optional[str] = None) -> dict:
    bench, sh2, sz2, csi, all_dts = cm.load_bench_and_index(include_1126=False)
    if trunc_date:
        bench = bench[bench["trade_date"] <= trunc_date].copy()
        sh2 = {k: v for k, v in sh2.items() if k <= trunc_date}
        sz2 = {k: v for k, v in sz2.items() if k <= trunc_date}
        all_dts = [d for d in all_dts if d <= trunc_date]

    cal_dts = bench["trade_date"].tolist()
    df_e = pd.read_parquet(f"{P3_DIR}/w2_4to5_enriched_master.parquet")
    with open(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json") as f:
        holders = json.load(f)
    df_tox = pd.read_parquet(f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet")
    df_real_tox = df_tox[df_tox["title"].astype(str).str.contains(TOX_RE)].copy()

    import gc
    import pyarrow as pa
    import pyarrow.dataset as ds
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    codes_needed = set(df_e["code"].astype(str).str.zfill(6))
    sc_cols = [
        "dt", "c6", "open", "high", "low", "close", "open_pct", "ret_1d",
        "is_zt", "hit_zt", "is_yizi_zt", "is_dt", "is_yizi_dt", "is_st_pit", "is_20cm",
        "prev_streak", "streak", "turn_pct", "real_turn_pct_t1",
        "lock_top10_pct_pre", "free_mcap_yi_t1", "amount_yi_t1",
        "hr10d_space_t1", "hr30d_space_t1", "tox_reg_30d_pre", "abn_notice_30d_pre",
        "d1_open_board_cnt_t1", "d1_first_seal_hhmm_t1", "lhb_on_t1",
        "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1", "lhb_has_quant_t1",
        "kpl_in_t1", "kpl_zt3_t1",
    ]
    flt_sc = (ds.field("prev_streak") >= 4) | (ds.field("dt") >= "2026-11-08")
    if trunc_date:
        flt_sc = flt_sc & (ds.field("dt") <= trunc_date)
    sc_ds = ds.dataset(f"{WAVE1_BASE}/stock_day_core_features_pit.parquet", format="parquet")
    chunks = [b.to_pandas() for b in sc_ds.scanner(columns=sc_cols, filter=flt_sc, batch_size=65536, use_threads=False).to_batches()]
    df_sc = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=sc_cols)
    del chunks
    df_sc["dt"] = df_sc["dt"].astype(str)
    df_sc["c6"] = df_sc["c6"].astype(str)
    if not trunc_date:
        nov_codes = set(df_sc[(df_sc["dt"] >= "2026-11-10") & (df_sc["dt"] <= "2026-11-24") & (df_sc["prev_streak"] == 4) & (~df_sc["is_st_pit"]) & (~df_sc["is_20cm"])]["c6"].astype(str).str.zfill(6))
        codes_needed |= nov_codes
    # Fetch only needed hydration cols for codes_needed
    hyd_cols = ["dt", "c6", "kpl_in_t1", "kpl_zt3_t1", "real_turn_pct_t1", "lock_top10_pct_pre", "d1_first_seal_hhmm_t1"]
    flt_c = ds.field("c6").isin(sorted(codes_needed))
    if trunc_date:
        flt_c = flt_c & (ds.field("dt") <= trunc_date)
    chunks2 = [b.to_pandas() for b in sc_ds.scanner(columns=hyd_cols, filter=flt_c, batch_size=65536, use_threads=False).to_batches()]
    df_hyd = pd.concat(chunks2, ignore_index=True).drop_duplicates(subset=["dt", "c6"], keep="first") if chunks2 else pd.DataFrame(columns=hyd_cols)
    del chunks2
    df_hyd["dt"] = df_hyd["dt"].astype(str)
    df_hyd["c6"] = df_hyd["c6"].astype(str)
    pa.default_memory_pool().release_unused()
    gc.collect()
    df_mk = pd.read_parquet(f"{WAVE1_BASE}/market_daily_all_new_factors_pit.parquet")

    if trunc_date:
        df_e = df_e[df_e["buy_date"] <= trunc_date].copy().reset_index(drop=True)
        df_real_tox = df_real_tox[df_real_tox["pub_datetime_cst"] <= trunc_date + " 23:59:59"].copy()
        df_mk = df_mk[df_mk["trade_date"] <= trunc_date].copy()

    # Enrich 2026-11-10..2026-11-24 if not truncated
    max_target = trunc_date or "2026-11-24"

    # Only B6 codes + Nov 10..24 prev_streak==4 codes ever need bars -> cuts bar count 4x!
    b6_codes = set(df_e[df_e["B6_auc_sweet_2_7_bought"] == 1]["code"].astype(str).str.zfill(6))
    if not trunc_date:
        b6_codes |= set(df_sc[(df_sc["dt"] >= "2026-11-10") & (df_sc["dt"] <= "2026-11-24") & (df_sc["prev_streak"] == 4) & (~df_sc["is_st_pit"]) & (~df_sc["is_20cm"])]["c6"].astype(str).str.zfill(6))
    max_bar_dt = trunc_date or "2026-11-25"
    rich_bars = load_daily_bars_rich(b6_codes, max_dt=max_bar_dt)
    # Build bar_lu directly from rich_bars (zero redundant parquet reload)
    bar_lu = {}
    for c6_k, cb in rich_bars.items():
        for i_k, dt_k in enumerate(cb["dts"]):
            bar_lu[(c6_k, dt_k)] = (float(cb["open"][i_k]), float(cb["close"][i_k]), float(cb["adjf"][i_k]))

    if not trunc_date:
        df_ext = build_extension_20261110_20261124(list(df_e.columns), df_sc, df_mk, holders, df_real_tox, rich_bars, cal_dts, max_dt=max_target)
        if not df_ext.empty:
            df_e = pd.concat([df_e, df_ext], ignore_index=True)

    # Hydrate kpl_in_t1 & prev_real_to from stock_day_core_features_pit for ALL df_e rows (strictly t-1 PIT)
    df_e["code6"] = df_e["code"].astype(str).str.zfill(6)
    sc_hyd = df_hyd.rename(columns={"dt": "buy_date", "c6": "code6"})
    df_e = df_e.merge(sc_hyd, on=["buy_date", "code6"], how="left")
    del df_hyd, sc_hyd
    df_e["kpl_in_t1"] = df_e["kpl_in_t1"].fillna(0)
    df_e["prev_real_to"] = df_e["prev_real_to"].fillna(df_e["real_turn_pct_t1"]).fillna(20.0)
    df_e["lock_top10"] = np.where(df_e["lock_top10_pct_pre"].notna() & (df_e["lock_top10_pct_pre"] > 0), df_e["lock_top10_pct_pre"], df_e["lock_top10"])

    # Compute V20 & Bug-Fixed PIT scores
    v20_res = [score_single_4to5_row(r.to_dict()) for _, r in df_e.iterrows()]
    df_e["v20_score"] = [x["score"] for x in v20_res]
    fix_res = [score_fixed_4to5(r.to_dict(), holders, df_real_tox) for _, r in df_e.iterrows()]
    df_e["fixed_score"] = [x[0] for x in fix_res]
    df_e["buy_price_val"] = df_e["B6_auc_sweet_2_7_px"].fillna(0.0).astype(float)

    # Set canonical B6 subset
    b6 = df_e[df_e["B6_auc_sweet_2_7_bought"] == 1].copy().reset_index(drop=True)
    b6["exit_date"] = b6["exdt_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"].astype(str)
    b6["ret_E4_020"] = b6["ret_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"].astype(float)
    b6["ret_E4_030"] = convert_fee_arr(b6["ret_E4_020"].to_numpy(float), 0.0020, 0.0030)

    # Filter out unsettled trades after trunc_date if any
    if trunc_date:
        settled = b6["exit_date"] <= trunc_date
    else:
        settled = b6["exit_date"] <= "2026-11-25"
    b6 = b6[settled].copy().reset_index(drop=True)

    # 1. Exact reproduction audit vs `w2_4to5_v20_ledger.csv`
    _, ss_orig_20 = cm.select_single_slot(
        b6.assign(score=b6["v20_score"], net_ret=b6["ret_E4_020"]),
        mask=(b6["v20_score"] >= 114) & (b6["buy_date"] <= "2026-11-09"),
        score_col="score", tie_col="open_pct"
    )
    ledger_csv = pd.read_csv(f"{P3_DIR}/w2_4to5_v20_ledger.csv")
    parity_ok = (len(ss_orig_20) == len(ledger_csv)) and (list(ss_orig_20["code6"]) == list(ledger_csv["code"].astype(str).str.zfill(6)))
    max_pct_diff = float(np.max(np.abs(ss_orig_20["net_ret"].to_numpy(float) * 100.0 - ledger_csv["net_ret"].to_numpy(float)))) if parity_ok else 999.0

    # Check delisted, yizi, broken-board stats in master & 114/120
    all_codes = set(b6["code6"])
    dl_pq = pd.read_parquet(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", columns=["ticker"])
    dl_codes = set(dl_pq["ticker"].astype(str).str[:6].unique())
    hygiene = {
        "master_rows": int(len(df_e)),
        "b6_rows": int(len(b6)),
        "master_delisted_codes": int(len(set(df_e["code6"]) & dl_codes)),
        "b6_delisted_rows": int(b6["code6"].isin(dl_codes).sum()),
        "v20_114_ss_n_thru_1109": int(len(ss_orig_20)),
        "v20_114_csv_parity_ok": bool(parity_ok),
        "v20_114_max_pct_ret_diff": round(max_pct_diff, 6),
        "v20_114_failed_zt_in_denom": int((~ss_orig_20["is_zt_today"]).sum()),
        "nov_2026_b6_candidates": df_e[df_e["buy_date"] >= "2026-11-01"][["buy_date", "code6", "name", "open_pct", "v20_score", "fixed_score", "B6_auc_sweet_2_7_bought", "ret_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"]].to_dict("records") if not trunc_date else [],
        "y2021_audit_note": "w2_4to5_enriched_master starts 2022-01-04 (pit_reg_tox_notices_5y_complete starts 2021-10-08); 2021-01..2021-09 lacks 90d toxic notice lookback.",
    }

    # 2. Causal daily exit engine across all B6 rows
    risk_ctx = build_daily_7factor_hold_map(all_codes, df_mk, df_sc, rich_bars, max_dt=max_bar_dt)
    exit_rules = ["E_PureBreak_EOD", "E_YangImm1_EOD", "E_Abn95_Limit", "E_Abn100_Limit", "E_7Factor_Guard", "E_MA5_Close", "E_VolBreak_EOD"]
    exit_cols = {}
    for er in exit_rules:
        exs, r30s, ehs = [], [], []
        for r in b6.itertuples(index=False):
            cb = rich_bars.get(r.code6)
            idx_m = sh2 if r.code6.startswith("6") else sz2
            ed, r30, eh = sim_causal_daily_exit(r.code6, r.buy_date, float(r.buy_price_val), cb, idx_m, er, 0.0030, risk_ctx)
            if ed is None or (trunc_date and ed > trunc_date) or ((not trunc_date) and ed > "2026-11-25"):
                ed = r.exit_date
                r30 = float(r.ret_E4_030)
                eh = 1500
            exs.append(ed)
            r30s.append(float(r30))
            ehs.append(int(eh))
        exit_cols[er] = {"exit_date": exs, "ret_030": np.array(r30s, dtype=float), "exit_hhmm": ehs}

    # Release heavy temporary objects before running 26-variant MTM loop
    del df_sc, rich_bars, risk_ctx, holders, df_real_tox, df_tox, df_e, df_mk
    pa.default_memory_pool().release_unused()
    gc.collect()

    # Precomputed E1/E2/E3 columns in master
    for ec, col_r, col_d in [
        ("E1", "ret_B6_auc_sweet_2_7_E1_3to4_std", "exdt_B6_auc_sweet_2_7_E1_3to4_std"),
        ("E2", "ret_B6_auc_sweet_2_7_E2_dev93_always", "exdt_B6_auc_sweet_2_7_E2_dev93_always"),
        ("E3", "ret_B6_auc_sweet_2_7_E3_F62_staged_dev93", "exdt_B6_auc_sweet_2_7_E3_F62_staged_dev93"),
    ]:
        r30 = convert_fee_arr(b6[col_r].fillna(b6["ret_E4_020"]).to_numpy(float), 0.0020, 0.0030)
        exit_cols[ec] = {"exit_date": b6[col_d].fillna(b6["exit_date"]).astype(str).tolist(), "ret_030": r30, "exit_hhmm": [1500] * len(b6)}

    # 3. Causal Walk-Forward (`exit_date < t`)
    wf = build_causal_wf_variants(b6, b6["v20_score"].to_numpy(float), b6["fixed_score"].to_numpy(float), b6["ret_E4_030"].to_numpy(float), wf_start="2023-01-03")

    # Helper masks on B6
    m_v114 = b6["v20_score"].to_numpy(float) >= 114
    m_v120 = b6["v20_score"].to_numpy(float) >= 120
    m_f114 = b6["fixed_score"].to_numpy(float) >= 114
    m_f120 = b6["fixed_score"].to_numpy(float) >= 120
    m_cold45 = b6["mkt_zt_prev"].fillna(60).to_numpy(float) < 45
    m_cold50 = b6["mkt_zt_prev"].fillna(60).to_numpy(float) < 50
    m_lock45 = b6["lock_top10"].fillna(0).to_numpy(float) >= 45.0
    m_lock50 = b6["lock_top10"].fillna(0).to_numpy(float) >= 50.0
    m_kpl = b6["kpl_in_t1"].fillna(0).to_numpy(float) == 1
    m_sole = b6["is_sole_4b"].fillna(0).to_numpy(int) == 1
    m_seal_fast = (b6["first_seal_time"].astype(str) <= "10:00:00").to_numpy(bool)
    m_obc0 = (b6["open_board_count"].fillna(0).to_numpy(int) == 0)
    m_no_high_to = (b6["prev_real_to"].fillna(20.0).to_numpy(float) < 35.0)
    m_bl = wf["bl_mask"]
    sc_mb_v20 = b6["v20_score"].to_numpy(float) + wf["modeb_delta"]
    sc_mb_fix = b6["fixed_score"].to_numpy(float) + wf["modeb_delta"]

    # Define Variants: (name, mask, score_arr, exit_key, rev_mask, rev_label, is_core)
    variants_spec = [
        # Baselines
        ("G1_Base_V20_114", m_v114, b6["v20_score"].to_numpy(float), "E4", (b6["v20_score"].to_numpy(float) >= 100) & (b6["v20_score"].to_numpy(float) < 114), "V20_100_113", True),
        ("G1_Base_V20_120", m_v120, b6["v20_score"].to_numpy(float), "E4", (b6["v20_score"].to_numpy(float) >= 114) & (b6["v20_score"].to_numpy(float) < 120), "V20_114_119", True),
        ("G1_FixPIT_114", m_f114, b6["fixed_score"].to_numpy(float), "E4", (b6["fixed_score"].to_numpy(float) >= 100) & (b6["fixed_score"].to_numpy(float) < 114), "FixPIT_100_113", True),
        ("G1_FixPIT_120", m_f120, b6["fixed_score"].to_numpy(float), "E4", (b6["fixed_score"].to_numpy(float) >= 114) & (b6["fixed_score"].to_numpy(float) < 120), "FixPIT_114_119", True),
        # Factor slices on V20 >= 114
        ("G1_V114_Lock45", m_v114 & m_lock45, b6["v20_score"].to_numpy(float), "E4", m_v114 & (~m_lock45), "V114_LockLt45", True),
        ("G1_V114_SkipCold45", m_v114 & (~m_cold45), b6["v20_score"].to_numpy(float), "E4", m_v114 & m_cold45, "V114_Cold45", False),
        ("G1_V114_ActiveOrSole", m_v114 & ((~m_cold50) | m_sole), b6["v20_score"].to_numpy(float), "E4", m_v114 & m_cold50 & (~m_sole), "V114_Cold50_NonSole", True),
        ("G1_V114_KPL", m_v114 & m_kpl, b6["v20_score"].to_numpy(float), "E4", m_v114 & (~m_kpl), "V114_NonKPL", False),
        ("G1_V114_SealClean", m_v114 & m_seal_fast, b6["v20_score"].to_numpy(float), "E4", m_v114 & (~m_seal_fast), "V114_LateSeal", False),
        ("G1_V114_RealToLt35", m_v114 & m_no_high_to, b6["v20_score"].to_numpy(float), "E4", m_v114 & (~m_no_high_to), "V114_RealToGe35", False),
        # Fixed PIT low-DOF combos & FixPIT exit sanity checks
        ("G1_Fix114_Lock45", m_f114 & m_lock45, b6["fixed_score"].to_numpy(float), "E4", m_f114 & (~m_lock45), "Fix114_LockLt45", True),
        ("G1_Fix114_SkipCold45", m_f114 & (~m_cold45), b6["fixed_score"].to_numpy(float), "E4", m_f114 & m_cold45, "Fix114_Cold45", True),
        ("G1_Fix114_SealClean", m_f114 & m_seal_fast, b6["fixed_score"].to_numpy(float), "E4", m_f114 & (~m_seal_fast), "Fix114_LateSeal", True),
        ("G1_Fix114_ActiveOrSole", m_f114 & ((~m_cold50) | m_sole), b6["fixed_score"].to_numpy(float), "E4", m_f114 & m_cold50 & (~m_sole), "Fix114_Cold50_NonSole", True),
        ("G1_Fix114_E_PureBreak", m_f114, b6["fixed_score"].to_numpy(float), "E_PureBreak_EOD", (b6["fixed_score"].to_numpy(float) >= 100) & (b6["fixed_score"].to_numpy(float) < 114), "FixPIT_100_113", False),
        ("G1_Fix114_E_Abn95", m_f114, b6["fixed_score"].to_numpy(float), "E_Abn95_Limit", (b6["fixed_score"].to_numpy(float) >= 100) & (b6["fixed_score"].to_numpy(float) < 114), "FixPIT_100_113", True),
        ("G1_Fix114_E_7Factor", m_f114, b6["fixed_score"].to_numpy(float), "E_7Factor_Guard", (b6["fixed_score"].to_numpy(float) >= 100) & (b6["fixed_score"].to_numpy(float) < 114), "FixPIT_100_113", True),
        # Exit tests on V20 >= 114 and V20 >= 120
        ("G1_V114_E_PureBreak", m_v114, b6["v20_score"].to_numpy(float), "E_PureBreak_EOD", (b6["v20_score"].to_numpy(float) >= 100) & (b6["v20_score"].to_numpy(float) < 114), "V20_100_113", False),
        ("G1_V114_E_YangImm1", m_v114, b6["v20_score"].to_numpy(float), "E_YangImm1_EOD", (b6["v20_score"].to_numpy(float) >= 100) & (b6["v20_score"].to_numpy(float) < 114), "V20_100_113", False),
        ("G1_V114_E_Abn95", m_v114, b6["v20_score"].to_numpy(float), "E_Abn95_Limit", (b6["v20_score"].to_numpy(float) >= 100) & (b6["v20_score"].to_numpy(float) < 114), "V20_100_113", True),
        ("G1_V114_E_Abn100", m_v114, b6["v20_score"].to_numpy(float), "E_Abn100_Limit", (b6["v20_score"].to_numpy(float) >= 100) & (b6["v20_score"].to_numpy(float) < 114), "V20_100_113", False),
        ("G1_V114_E_7Factor", m_v114, b6["v20_score"].to_numpy(float), "E_7Factor_Guard", (b6["v20_score"].to_numpy(float) >= 100) & (b6["v20_score"].to_numpy(float) < 114), "V20_100_113", True),
        ("G1_V114_E_MA5", m_v114, b6["v20_score"].to_numpy(float), "E_MA5_Close", (b6["v20_score"].to_numpy(float) >= 100) & (b6["v20_score"].to_numpy(float) < 114), "V20_100_113", False),
        ("G1_V114_E2_Dev93", m_v114, b6["v20_score"].to_numpy(float), "E2", (b6["v20_score"].to_numpy(float) >= 100) & (b6["v20_score"].to_numpy(float) < 114), "V20_100_113", False),
        ("G1_V120_E_Abn95", m_v120, b6["v20_score"].to_numpy(float), "E_Abn95_Limit", (b6["v20_score"].to_numpy(float) >= 114) & (b6["v20_score"].to_numpy(float) < 120), "V20_114_119", True),
        ("G1_V120_E_7Factor", m_v120, b6["v20_score"].to_numpy(float), "E_7Factor_Guard", (b6["v20_score"].to_numpy(float) >= 114) & (b6["v20_score"].to_numpy(float) < 120), "V20_114_119", False),
        # Causal Walk-Forward variants (`exit_date < t`)
        ("G1_WF_4Way_BL_V114", m_v114 & m_bl, b6["v20_score"].to_numpy(float), "E4", m_v114 & (~m_bl), "WF_4Way_Blocked", True),
        ("G1_WF_ModeB_V114", sc_mb_v20 >= 114.0, sc_mb_v20, "E4", (sc_mb_v20 >= 100.0) & (sc_mb_v20 < 114.0), "WF_ModeB_Lt114", True),
        ("G1_WF_ModeB_V120", sc_mb_v20 >= 120.0, sc_mb_v20, "E4", (sc_mb_v20 >= 114.0) & (sc_mb_v20 < 120.0), "WF_ModeB_114_119", True),
        ("G1_WF_ModeB_Fix114", sc_mb_fix >= 114.0, sc_mb_fix, "E4", (sc_mb_fix >= 100.0) & (sc_mb_fix < 114.0), "WF_FixModeB_Lt114", True),
        ("G1_WF_ModeB_V114_Abn95", sc_mb_v20 >= 114.0, sc_mb_v20, "E_Abn95_Limit", (sc_mb_v20 >= 100.0) & (sc_mb_v20 < 114.0), "WF_ModeB_Lt114", True),
    ]

    results = {}
    all_ledger_frames = []

    for vname, mask, sc_arr, ex_key, rev_mask, rev_label, is_core in variants_spec:
        df_w = b6.copy()
        df_w["score"] = sc_arr
        if ex_key == "E4":
            r30_all = b6["ret_E4_030"].to_numpy(float)
            exdt_all = b6["exit_date"].astype(str).tolist()
            exhh_all = [1500] * len(b6)
        else:
            r30_all = exit_cols[ex_key]["ret_030"]
            exdt_all = exit_cols[ex_key]["exit_date"]
            exhh_all = exit_cols[ex_key]["exit_hhmm"]
        df_w["net_ret"] = r30_all
        df_w["exit_date"] = exdt_all
        df_w["exit_hhmm"] = exhh_all

        pass_df, slot_df = cm.select_single_slot(df_w, mask=mask, score_col="score", tie_col="open_pct")
        # Build exact MTM on slot_df & pass_df
        if not pass_df.empty:
            pass_r30 = pass_df["net_ret"].to_numpy(float)
            pass_r20 = convert_fee_arr(pass_r30, 0.0030, 0.0020)
            pass_r50 = convert_fee_arr(pass_r30, 0.0030, 0.0050)
            pass_r80 = convert_fee_arr(pass_r30, 0.0030, 0.0080)
            pass_iso = make_isomorphic_rows(pass_df, vname, False, "score", pass_r20, pass_r30, pass_r50, pass_r80, cal_dts, bar_lu, "exit_hhmm")
        else:
            pass_iso = pd.DataFrame()

        if not slot_df.empty:
            slot_r30 = slot_df["net_ret"].to_numpy(float)
            slot_r20 = convert_fee_arr(slot_r30, 0.0030, 0.0020)
            slot_r50 = convert_fee_arr(slot_r30, 0.0030, 0.0050)
            slot_r80 = convert_fee_arr(slot_r30, 0.0030, 0.0080)
            slot_iso = make_isomorphic_rows(slot_df, vname, True, "score", slot_r20, slot_r30, slot_r50, slot_r80, cal_dts, bar_lu, "exit_hhmm")
        else:
            slot_iso = pd.DataFrame()

        # Verify exact mtm_diff == 0.0
        _, mtm_diff_full = cm.daily_mtm_series(slot_iso, cal_dts, ret_col="net_ret") if not slot_iso.empty else (np.zeros(len(cal_dts)), 0.0)
        d15 = cm.evaluate_d15_windows(slot_iso, pass_iso, bench, WINDOWS_G1, base_fee=0.0030)

        rets_ss = slot_iso["net_ret"].to_numpy(float) if not slot_iso.empty else np.array([], dtype=float)
        rev_df = df_w[rev_mask].copy() if np.any(rev_mask) else pd.DataFrame()

        t1 = cm.tool1_bootstrap(rets_ss, n_boot=10000, seed=42)
        t2 = cm.tool2_bayesian_posterior(rets_ss)
        t3 = cm.tool3_reverse_control_perm(rets_ss, rev_df, n_perm=10000, seed=42, rev_label=rev_label)
        t4 = cm.tool4_regime_changepoint_and_dd(slot_iso, n_perm=2000, seed=42)

        # Also 20bps reference NAV for Baseline parity clarity
        nav_20bps = round(float(np.prod(1.0 + slot_iso["net_ret_020"].to_numpy(float))), 4) if not slot_iso.empty else 1.0

        results[vname] = {
            "is_core": is_core,
            "exit_rule": ex_key,
            "ss_n": int(len(slot_iso)),
            "raw_n": int(len(pass_iso)),
            "mtm_diff": round(float(mtm_diff_full), 10),
            "full_nav_20bps_ref": nav_20bps,
            "d15": d15,
            "tool1_bootstrap": t1,
            "tool2_bayesian": t2,
            "tool3_reverse_control": t3,
            "tool4_regime_dd": t4,
        }

        if not trunc_date and is_core:
            if not slot_iso.empty:
                all_ledger_frames.append(slot_iso)
            if not pass_iso.empty:
                all_ledger_frames.append(pass_iso)

    return {
        "hygiene": hygiene,
        "variants": results,
        "ledger_df": pd.concat(all_ledger_frames, ignore_index=True) if all_ledger_frames else pd.DataFrame(),
        "b6_count": int(len(b6)),
        "rss_mb": round(rss_mb(), 1),
    }


def main():
    import argparse
    import subprocess
    import pyarrow as pa
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--trunc-only-out", default="")
    args = parser.parse_args()

    if args.trunc_only_out:
        tr = run_all_gem1(trunc_date="2024-12-31")
        tr.pop("ledger_df", None)
        pa.default_memory_pool().release_unused()
        with open(args.trunc_only_out, "w", encoding="utf-8") as f:
            json.dump(cm.sanitize_json({"rss_mb": round(rss_mb(), 1), "variants": tr["variants"]}), f, ensure_ascii=False)
        return

    print("[RD048 Wave1-A Gem 1] Running full 2022-01-04..2026-11-24 evaluation...")
    full_res = run_all_gem1(trunc_date=None)

    parquet_path = f"{OUT_DIR}/rd048_gem1_trades.parquet"
    json_path = f"{OUT_DIR}/rd048_gem1_4to5.json"
    full_ledger_df = full_res.pop("ledger_df")
    full_ledger_df.to_parquet(parquet_path, index=False)
    trunc_ref_map = {}
    for vname, full_v in full_res["variants"].items():
        if not full_v["is_core"]:
            continue
        sub_f = full_ledger_df[(full_ledger_df["variant"] == vname) & (full_ledger_df["is_single_slot"]) & (full_ledger_df["exit_date"] <= "2024-12-31")].sort_values(["buy_date", "code"]).reset_index(drop=True)
        if not sub_f.empty:
            trunc_ref_map[vname] = (
                int(len(sub_f)),
                round(float(np.prod(1.0 + sub_f["net_ret"].to_numpy(float))), 4),
                round(float(sub_f["net_ret"].to_numpy(float).mean() * 100.0), 2),
            )
        else:
            trunc_ref_map[vname] = (0, 1.0, 0.0)
    parquet_rows = int(len(full_ledger_df))
    parquet_cols = list(full_ledger_df.columns)
    del full_ledger_df
    import gc
    gc.collect()
    pa.default_memory_pool().release_unused()

    print("[RD048 Wave1-A Gem 1] Running 2024-12-31 physical truncation verification in isolated child process...")
    tmp_trunc = f"{OUT_DIR}/_tmp_g1_trunc.json"
    subprocess.run([sys.executable, os.path.abspath(__file__), "--trunc-only-out", tmp_trunc], check=True)
    with open(tmp_trunc, encoding="utf-8") as f:
        trunc_res = json.load(f)
    os.remove(tmp_trunc)

    trunc_diffs = {}
    max_abs_diff = 0.0
    for vname, (f_n, f_nav, f_mean) in trunc_ref_map.items():
        tv = trunc_res["variants"].get(vname, {})
        t_win = tv.get("d15", {}).get("Full_2022_2026", {})
        t_nav = t_win.get("nav", 1.0)
        t_mean = t_win.get("mean_pct", 0.0)
        t_n = t_win.get("ss_n", 0)
        d_nav = abs(f_nav - t_nav)
        d_mean = abs(f_mean - t_mean)
        d_n = abs(f_n - t_n)
        max_abs_diff = max(max_abs_diff, d_nav, d_mean, float(d_n))
        trunc_diffs[vname] = {"full_n": f_n, "trunc_n": t_n, "nav_diff": round(d_nav, 10), "mean_diff": round(d_mean, 10)}

    max_mtm_diff = max(v["mtm_diff"] for v in full_res["variants"].values())
    peak_rss = max(round(rss_mb(), 1), float(trunc_res.get("rss_mb", 0.0)))

    out_json = {
        "meta": {
            "strategy": "Gem1_4to5",
            "window": "2022-01-04..2026-11-24 (w2_4to5_enriched_master + 2026-11-10..24 PIT extension)",
            "primary_fee_bps": 30,
            "stress_fee_bps": [50, 80],
            "parquet_path": parquet_path,
            "parquet_rows": parquet_rows,
            "parquet_cols": parquet_cols,
            "max_mtm_diff": round(max_mtm_diff, 10),
            "trunc_20241231_max_abs_diff": round(max_abs_diff, 10),
            "peak_rss_mb": peak_rss,
            "parent_rss_mb": round(rss_mb(), 1),
            "trunc_child_rss_mb": float(trunc_res.get("rss_mb", 0.0)),
        },
        "hygiene": full_res["hygiene"],
        "truncation_20241231_audit": trunc_diffs,
        "variants": full_res["variants"],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(cm.sanitize_json(out_json), f, ensure_ascii=False, indent=2)

    print(f"Saved: {json_path} & {parquet_path} | rows={parquet_rows} | peak_rss={peak_rss:.1f}MB (parent={rss_mb():.1f}MB, child={trunc_res.get('rss_mb',0):.1f}MB)")
    print(f"Hygiene: parity_ok={full_res['hygiene']['v20_114_csv_parity_ok']}, csv_ret_diff={full_res['hygiene']['v20_114_max_pct_ret_diff']}pp, max_mtm_diff={max_mtm_diff}, trunc_max_diff={max_abs_diff}")
    print("\n--- Core Variants Summary (30bps primary) ---")
    for vn, vd in full_res["variants"].items():
        fw = vd["d15"]["Full_2022_2026"]
        p23 = vd["d15"]["Period_2023_2025"]
        y26 = vd["d15"]["Y2026"]
        h2 = vd["d15"]["Y26H2"]
        b1 = vd["tool1_bootstrap"]
        b2 = vd["tool2_bayesian"]["priors"]["Beta(2,2)_neutral"]
        t3 = vd["tool3_reverse_control"].get("perm_vs_rev_slot", {})
        t4 = vd["tool4_regime_dd"]
        print(f"{vn:24s} | n={fw['ss_n']:2d} | WR={fw['wr_pct']:5.1f}% PLR={fw['plr']:4.2f} | NAV={fw['nav']:6.2f}x (ex5={fw['ex5_nav']:5.2f}x) Sh={fw['daily_sharpe']:4.2f} MDD={fw['daily_mdd_pct']:5.1f}% | 23-25:{p23['ss_n']}b {p23['nav']:4.2f}x | 26:{y26['ss_n']}b {y26['nav']:4.2f}x | H2:{h2['ss_n']}b {h2['nav']:4.2f}x | BootP>0={b1['prob_mean_gt_0']:.3f} p05={b1['mean_p05_pct']:+.2f}% | k_stop={b2['k_consec_loss_prob50_capped25']} | perm_p={t3.get('p_mean_1s',1):.3f} | curDD={t4['current_dd_from_peak_pct']:.1f}%")


if __name__ == "__main__":
    main()
