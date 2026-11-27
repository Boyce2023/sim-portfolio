#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_dirB_3to4_to_4to5.py
【方向 B：三进四基因（买前结构 + 7 因子持仓卖点）反向赋能「四进五」买点与卖点】
- 严格基于 G1_StrictJianchi_114 (37 raw / 33 ss) 与 G1_FixPIT_120 (17 raw / 15 ss)，
  并以 G1_FixPIT_114 (45 ss) 与 G1_FixPIT_100 (~100+ ss) 作大样本防过拟合辅助检验池。
- 严格零未来函数（支持 2024-12-31 物理截断验证 max_abs_diff == 0.0）；
  全部 30bps 实盘滑点 + 50bps 压力；10,000 次 Bootstrap 下界、去前 2 笔极值、IS/OOS/25-26/26/26H2 五窗口。
"""
import argparse
import bisect
import gc
import json
import math
import os
import pickle
import re
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
sys.dont_write_bytecode = True
assert "yfinance" not in sys.modules, "D12 VIOLATION"

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)
import _p1a_common as cm

SIM = cm.SIM
P3_DIR = f"{SIM}/backtests_astock2/p3_deep_100"
RD048_W1A = f"{SIM}/backtests_astock2/rd048_4small_gems_polish_integration_20261126/wave1a_gem1_gem3"
RD036_P2 = f"{SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part2_other5"
WAVE1_BASE = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
for p in (P3_DIR, RD048_W1A, RD036_P2):
    if p not in sys.path:
        sys.path.insert(0, p)

from step1_gem1_4to5_polish import (
    TOX_RE,
    REG_INC,
    REG_EXC,
    build_extension_20261110_20261124,
    build_daily_7factor_hold_map,
    convert_fee_arr,
    load_daily_bars_rich,
    score_fixed_4to5,
)
import run_m3_m4_3way_4way_trees as m34

TOX_STRICT_RE = re.compile(r"(?:减持.*(?:计划|预披露|公告)|(?:计划|预披露).*减持|立案调查|收到立案|退市风险|违法违规|股票交易风险提示)")
F7 = ["xf21_135", "xf03_20m", "xf28_35", "xf02", "xf07_new", "xf22", "xf23_reb20"]


def _cnt_win(arr: Optional[np.ndarray], lo: str, hi: str) -> int:
    if arr is None or len(arr) == 0:
        return 0
    i0 = int(np.searchsorted(arr, lo, side="left"))
    i1 = int(np.searchsorted(arr, hi, side="left"))
    if i1 > 0:
        assert arr[i1 - 1] < hi, f"PIT time breach: {arr[i1-1]} >= {hi}"
    return max(0, i1 - i0)


def build_pos20_d0_and_xq_pit(b6: pd.DataFrame, rich_bars: dict, max_dt: str) -> pd.DataFrame:
    """
    Compute strictly PIT 3to4 pre-buy genes on 4to5 B6 candidates:
      - `pos20_d0`: 20-day box position at D0 (`pos - 5`, prior to 4-board launch!)
      - `xq_cnt_2d`, `xq_cnt_24h`: strictly `< buy_date 09:25:00` from SQLite (mode=ro)
      - `csrc_zt_cnt`, `plate_fb_ho_cnt`, `plate_fb_yz_cnt`, `plate_peers_open_avg`, `p_elo` (hydrated for extension rows too).
    """
    codes = set(b6["code6"])
    # 1. Xueqiu posts strictly <= max_dt 23:59:59 (mode=ro)
    xq_seen = defaultdict(set)
    xq_posts = defaultdict(list)
    con_xq = sqlite3.connect(f"file:{SIM}/data/xueqiu_guba_5y_pit.db?mode=ro", uri=True)
    for sym, pid, cts in con_xq.execute(
        "SELECT symbol, post_id, created_time_str FROM xueqiu_posts WHERE created_time_str >= '2021-10-01' AND created_time_str <= ?",
        (f"{max_dt} 23:59:59",),
    ):
        c6 = str(sym)[:6].zfill(6)
        if c6 in codes and cts:
            pid_c = str(pid).replace("xq_", "")
            if pid_c not in xq_seen[c6]:
                xq_seen[c6].add(pid_c)
                xq_posts[c6].append(str(cts))
    con_xq.close()

    con_cm = sqlite3.connect(f"file:{SIM}/data/astock_community_5y_pit.db?mode=ro", uri=True)
    for sym, pid, cts in con_cm.execute(
        "SELECT symbol, post_id, pub_datetime_cst FROM community_posts WHERE source='xueqiu' AND pub_datetime_cst >= '2021-10-01' AND pub_datetime_cst <= ?",
        (f"{max_dt} 23:59:59",),
    ):
        c6 = str(sym)[:6].zfill(6)
        if c6 in codes and cts:
            pid_c = str(pid).replace("xq_", "")
            if pid_c not in xq_seen[c6]:
                xq_seen[c6].add(pid_c)
                xq_posts[c6].append(str(cts))
    con_cm.close()
    xq_arr_map = {c6: np.sort(np.array(v, dtype=str)) for c6, v in xq_posts.items()}

    # 2. Compute pos20_d0 from rich_bars (pre-4board launch = pos - 5; 20-day rolling [pos-24 .. pos-5] using adjusted prices)
    pos20_d0_list = []
    xq_2d_list = []
    xq_24h_list = []
    for r in b6.itertuples(index=False):
        c6 = r.code6
        bd = str(r.buy_date)[:10]
        sd = str(r.sig_date)[:10]
        cb = rich_bars.get(c6)
        if cb is not None and bd in cb["dt_idx"]:
            pos = cb["dt_idx"][bd]
            d0_pos = max(0, pos - 5)  # Day before D1 of the 4-board streak
            lo_i = max(0, d0_pos - 19)
            adj_c = cb["close"][lo_i : d0_pos + 1] * cb["adjf"][lo_i : d0_pos + 1]
            adj_h = cb["high"][lo_i : d0_pos + 1] * cb["adjf"][lo_i : d0_pos + 1]
            adj_l = cb["low"][lo_i : d0_pos + 1] * cb["adjf"][lo_i : d0_pos + 1]
            if len(adj_c) >= 5:
                mn, mx = float(np.min(adj_l)), float(np.max(adj_h))
                p20 = float((adj_c[-1] - mn) / max(1e-6, mx - mn))
            else:
                p20 = 0.50
            d1_dt = cb["dts"][max(0, pos - 4)]
        else:
            p20 = float(r.pos20) if pd.notna(getattr(r, "pos20", np.nan)) else 0.50
            d1_dt = sd
        pos20_d0_list.append(round(p20, 4))

        arr_x = xq_arr_map.get(c6)
        end_cut = f"{bd} 09:25:00"
        xq_2d_list.append(_cnt_win(arr_x, f"{d1_dt} 00:00:00", end_cut))
        xq_24h_list.append(_cnt_win(arr_x, f"{sd} 09:25:00", end_cut))

    out = b6.copy()
    out["pos20_d0"] = pos20_d0_list
    out["pos20_d4"] = pd.to_numeric(out.get("pos20", 0.5), errors="coerce").fillna(0.50)
    out["xq_cnt_2d"] = xq_2d_list
    out["xq_cnt_24h"] = xq_24h_list
    out["plate_fb_ho_cnt"] = pd.to_numeric(out.get("plate_fb_ho_cnt", 0), errors="coerce").fillna(0).astype(int)
    out["plate_fb_yz_cnt"] = pd.to_numeric(out.get("plate_fb_yz_cnt", 0), errors="coerce").fillna(0).astype(int)
    out["csrc_zt_cnt"] = pd.to_numeric(out.get("csrc_zt_cnt", 1), errors="coerce").fillna(1).astype(int)
    out["p_elo"] = pd.to_numeric(out.get("p_elo", 100.0), errors="coerce").fillna(100.0)
    out["plate_peers_open_avg"] = pd.to_numeric(out.get("plate_peers_open_avg", 0.0), errors="coerce").fillna(0.0)
    return out


def _get_double_dev_px_pit(c6: str, cb: dict, cp: int, sh_map: dict, sz_map: dict, ratio: float) -> float:
    """Strictly causal double-dev standing limit price using idx_{t-1}."""
    if cp < 1:
        return 99999.0
    imap = sh_map if c6.startswith("60") else sz_map
    sd = cb["dts"][cp - 1]
    ir = imap.get(sd)
    if not ir:
        return 99999.0
    disc = 1.0 - ratio
    bp = 99999.0
    adj_cp = float(cb["adjf"][cp])
    for lb in range(1, min(11, cp + 1)):
        p = cp - lb
        bi = imap.get(cb["dts"][p])
        bc = float(cb["close"][p] * cb["adjf"][p] / adj_cp)
        if bi and bc > 0:
            bp = min(bp, bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0)))
    for lb in range(1, min(31, cp + 1)):
        p = cp - lb
        bi = imap.get(cb["dts"][p])
        bc = float(cb["close"][p] * cb["adjf"][p] / adj_cp)
        if bi and bc > 0:
            bp = min(bp, bc * (1.0 + (2.0 - disc) + (ir / bi - 1.0)))
    return float(bp)


def compute_4to5_hold_states(
    b6: pd.DataFrame,
    rich_bars: dict,
    risk_ctx: tuple,
    max_dt: str,
) -> dict[tuple[str, str], dict[int, dict]]:
    """Precompute causal t-1 7-factor states (F7) for each B6 trade holding day k."""
    kpl_elo, lhb_risk, reg_dates, (mk_map, f7_by_dt) = risk_ctx
    out = {}
    for r in b6.itertuples(index=False):
        c6 = r.code6
        bd = str(r.buy_date)[:10]
        cb = rich_bars.get(c6)
        if cb is None or bd not in cb["dt_idx"]:
            continue
        pos = cb["dt_idx"][bd]
        n = len(cb["dts"])
        k_map = {}
        for k in range(pos + 1, min(n, pos + 20)):
            dt_k = cb["dts"][k]
            if dt_k > max_dt:
                break
            dt_prev = cb["dts"][k - 1]
            elo_v = kpl_elo.get((c6, dt_prev), 100.0)
            lr = lhb_risk.get((c6, dt_prev))
            inst_20m = bool(lr is not None and (lr[0] > 2e7 or (lr[0] - lr[1]) > 2e7))
            daysurf = bool(lr is not None and lr[2])
            blow35 = bool(cb["amt"][k - 1] > 3.5 * max(1.0, cb["ma5_amt_prev"][k - 1]))
            lo_ts, hi_ts = f"{bd} 09:25:00", f"{dt_k} 09:25:00"
            sreg_new = any(lo_ts <= ts < hi_ts for ts in reg_dates.get(c6, []))
            csi_slump = bool(mk_map.get(dt_k, {}).get("mkt_csi300_ret1d_t1", 0.0) <= -2.0)
            reb20 = bool(f7_by_dt.get(dt_k, False))
            rpts = (
                int(elo_v >= 135.0) + int(inst_20m) + int(blow35)
                + int(daysurf) + int(sreg_new) + int(csi_slump) + int(reb20)
            )
            k_map[k] = {
                "risk7": rpts,
                "xf21_135": elo_v >= 135.0,
                "xf03_20m": inst_20m,
                "xf28_35": blow35,
                "xf02": daysurf,
                "xf07_new": sreg_new,
                "xf22": csi_slump,
                "xf23_reb20": reb20,
            }
        out[(c6, bd)] = k_map
    return out


def sim_4to5_exit_unified(
    row: dict,
    cb: Optional[dict],
    b5m: dict,
    sh_map: dict,
    sz_map: dict,
    k_states: dict,
    exit_mode: str,
    fee: float = cm.FEE_MAIN,
) -> tuple[str, float, int, float]:
    """
    Simulate 4to5 exit strictly causally:
      - `E4_Base`: exact E4_F61_high_dragon_handoff (with E1 fallback for post-1109 extension), 0.0 diff vs RD048!
      - `E4_DtDefer`: E4 + V19.1 is_dt_exact deferral check (control audit!)
      - `E_V41_7f_d70` / `d60` / `d80`: E4 + 3to4 7-factor risk switch tightening 13:45 guard (5% -> 7%/6%/8%)
      - `E_NoYangImm` / `E_7f_StripImm` / `E_7f2_StripImm`: strip true-yang immunity (always or risk-gated)
      - `E_Dev93_All` / `E_Dev95_All` / `E_Dev93_5b` / `E_Dev95_5b`: standing 09:25 causal double-dev limit sell
      - `E_Reb20_Dev96` / `E_Reb20_Dev95` / `E_Reb20_Dev93`: XF23 reb20 cold double-dev limit sell
      - `E_Risk7_Dev95`: risk7 >= 1 -> 95% double-dev limit sell
      - `E_V41_Reb20Dev96`: exact XF30_7f_Reb20dev96 ported to 4to5!
      - `E1_CutWeak`: E1 without F61 handoff.
    """
    bd = str(row["buy_date"])[:10]
    c6 = str(row["code6"]).zfill(6)
    bpx = float(row["buy_price_val"])

    if exit_mode == "E4_Base" and pd.notna(row.get("ret_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff")) and bd <= "2026-11-09":
        r20 = float(row["ret_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"])
        ed = str(row["exdt_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"])[:10]
        return ed, float(cm.convert_fee(r20, 0.0020, fee)), 1500, r20

    if cb is None or bd not in cb["dt_idx"]:
        r20 = float(row["ret_E4_020"])
        return str(row["exit_date"])[:10], float(cm.convert_fee(r20, 0.0020, fee)), 1500, r20

    pos = cb["dt_idx"][bd]
    n = len(cb["dts"])
    if pos + 1 >= n:
        r20 = float(row["ret_E4_020"])
        return str(row["exit_date"])[:10], float(cm.convert_fee(r20, 0.0020, fee)), 1500, r20

    a0 = float(cb["adjf"][pos])
    def _ret(k_i: int, px: float, f_v: float) -> float:
        return (px * float(cb["adjf"][k_i])) / (bpx * a0) * (1.0 - f_v) - 1.0

    # Day 5 (entry day) unsealed handling
    use_f61 = (exit_mode != "E1_CutWeak")
    if not bool(cb["is_zt"][pos]):
        is_f61 = bool(row.get("f61_eligible", False)) and use_f61
        if is_f61:
            k = pos + 1
            while k < n and bool(cb["is_yizi_dt"][k]):
                k += 1
            if k >= n:
                k = n - 1
                px = float(cb["close"][k])
                return cb["dts"][k], _ret(k, px, fee), 1500, _ret(k, px, 0.0020)
            o6, p6, c6_px = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
            if (o6 / p6 - 1.0) <= -0.035:
                return cb["dts"][k], _ret(k, o6, fee), 925, _ret(k, o6, 0.0020)
            if bool(cb["is_zt"][k]):
                pos_start = k + 1
            else:
                return cb["dts"][k], _ret(k, c6_px, fee), 1500, _ret(k, c6_px, 0.0020)
        else:
            k = pos + 1
            while k < n and bool(cb["is_yizi_dt"][k]):
                k += 1
            if k >= n:
                k = n - 1
                px = float(cb["close"][k])
                return cb["dts"][k], _ret(k, px, fee), 1500, _ret(k, px, 0.0020)
            if k > pos + 1:
                px = float(cb["open"][k])
                return cb["dts"][k], _ret(k, px, fee), 925, _ret(k, px, 0.0020)
            o4, c4, p4 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])
            o5, p5, c5_px = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
            if not ((c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005)):
                return cb["dts"][k], _ret(k, o5, fee), 925, _ret(k, o5, 0.0020)
            if bool(cb["is_zt"][k]):
                pos_start = k + 1
            else:
                return cb["dts"][k], _ret(k, c5_px, fee), 1500, _ret(k, c5_px, 0.0020)
    else:
        pos_start = pos + 1

    # Ride ZT streak
    k = pos_start
    imm_used = False
    boards = 5 + max(0, pos_start - (pos + 1))
    apply_dt_defer = exit_mode.endswith("_DtDefer")
    exit_mode = "E4_Base" if exit_mode == "E4_DtDefer" else exit_mode.replace("_DtDefer", "")

    while k < n:
        if bool(cb["is_yizi_dt"][k]):
            k += 1
            continue
        dt_s = cb["dts"][k]
        ok = float(cb["open"][k])
        hk = float(cb["high"][k])
        pck = float(cb["pre_c"][k])
        clk = float(cb["close"][k])
        ztk = float(cb["zt_px"][k])
        dtk = round(pck * 0.90, 2)

        if k > pos_start and bool(cb["is_yizi_dt"][k - 1]):
            return dt_s, _ret(k, ok, fee), 925, _ret(k, ok, 0.0020)

        st = k_states.get(k, {})
        rpts = int(st.get("risk7", 0))
        reb20 = bool(st.get("xf23_reb20", False))

        # 1. Double-dev standing limit order check
        dev_ratio: Optional[float] = None
        if exit_mode == "E_Dev93_All":
            dev_ratio = 0.93
        elif exit_mode == "E_Dev95_All":
            dev_ratio = 0.95
        elif exit_mode == "E_Dev93_5b" and boards >= 6:
            dev_ratio = 0.93
        elif exit_mode == "E_Dev95_5b" and boards >= 6:
            dev_ratio = 0.95
        elif exit_mode in ("E_Reb20_Dev96", "E_V41_Reb20Dev96") and reb20 and boards >= 6:
            dev_ratio = 0.96
        elif exit_mode == "E_Reb20_Dev95" and reb20 and boards >= 6:
            dev_ratio = 0.95
        elif exit_mode == "E_Reb20_Dev93" and reb20 and boards >= 6:
            dev_ratio = 0.93
        elif exit_mode == "E_Risk7_Dev95" and rpts >= 1 and boards >= 6:
            dev_ratio = 0.95

        if dev_ratio is not None:
            pl = _get_double_dev_px_pit(c6, cb, k, sh_map, sz_map, dev_ratio)
            if ok >= pl and ok > dtk + 0.005:
                return dt_s, _ret(k, ok, fee), 925, _ret(k, ok, 0.0020)
            arr_d = b5m.get((c6, dt_s))
            if arr_d is not None and len(arr_d) > 0:
                for row5 in arr_d:
                    hh5, bo5, bh5 = int(row5[0]), float(row5[1]), float(row5[2])
                    if bh5 <= dtk + 0.005:
                        continue
                    if bh5 >= pl:
                        px_fill = min(ztk, max(bo5, pl))
                        return dt_s, _ret(k, px_fill, fee), hh5, _ret(k, px_fill, 0.0020)
            elif hk >= pl and hk > dtk + 0.005:
                px_fill = min(ztk, pl)
                return dt_s, _ret(k, px_fill, fee), 1030, _ret(k, px_fill, 0.0020)

        # 2. 13:45 5m profit guard
        drop_thr = 0.050
        if exit_mode in ("E_V41_7f_d70", "E_V41_Reb20Dev96") and rpts >= 1:
            drop_thr = 0.070
        elif exit_mode == "E_V41_7f_d60" and rpts >= 1:
            drop_thr = 0.060
        elif exit_mode == "E_V41_7f_d80" and rpts >= 1:
            drop_thr = 0.080

        arr = b5m.get((c6, dt_s))
        if arr is not None and len(arr) > 0:
            pk_v = ok
            for row5 in arr:
                hh5, bo5, bh5, bl5, bc5 = int(row5[0]), float(row5[1]), float(row5[2]), float(row5[3]), float(row5[4])
                if bh5 <= dtk + 0.005:
                    continue
                if hh5 >= 1345 and pk_v >= pck * 1.085 and bl5 <= pck * (1.0 + drop_thr) and bc5 < ztk - 0.01:
                    spx_g = float(min(bo5, pck * (1.0 + drop_thr)))
                    return dt_s, _ret(k, spx_g, fee), hh5, _ret(k, spx_g, 0.0020)
                if bh5 > pk_v:
                    pk_v = bh5

        if bool(cb["is_zt"][k]):
            boards += 1
            k += 1
            continue

        # 3. True-yang immunity
        strip_imm = False
        if exit_mode == "E_NoYangImm":
            strip_imm = True
        elif exit_mode == "E_7f_StripImm" and rpts >= 1:
            strip_imm = True
        elif exit_mode == "E_7f2_StripImm" and rpts >= 2:
            strip_imm = True

        if (not strip_imm) and (not imm_used) and (clk > ok) and (clk >= pck):
            imm_used = True
            k += 1
            continue

        # Optional dt_exact deferral audit
        if apply_dt_defer and (clk <= round(pck * 0.90, 2) + 0.005):
            kd = k + 1
            while kd < n - 1 and bool(cb["is_yizi_dt"][kd]):
                kd += 1
            if kd < n:
                return cb["dts"][kd], _ret(kd, float(cb["open"][kd]), fee), 925, _ret(kd, float(cb["open"][kd]), 0.0020)

        return dt_s, _ret(k, clk, fee), 1500, _ret(k, clk, 0.0020)

    k_end = n - 1
    px_end = float(cb["close"][k_end])
    return cb["dts"][k_end], _ret(k_end, px_end, fee), 1500, _ret(k_end, px_end, 0.0020)


def build_causal_wf_4way_with_34genes(b6: pd.DataFrame, base_mask: np.ndarray, wf_start: str = "2023-01-03") -> np.ndarray:
    """Strictly causal expanding Walk-Forward 4-way minefield blacklist (`exit_date < t`) augmented with 3to4 genes."""
    n = len(b6)
    bd_arr = b6["buy_date"].astype(str).to_numpy()
    ex_arr = b6["exit_date"].astype(str).to_numpy()
    ret_030 = b6["ret_E4_030"].to_numpy(float)
    y_win = (ret_030 > 0).astype(float)

    feats = {
        "cold_zt45": (b6["mkt_zt_prev"].fillna(60) < 45).to_numpy(np.int8),
        "cold_zt50": (b6["mkt_zt_prev"].fillna(60) < 50).to_numpy(np.int8),
        "lock45": (b6["lock_top10"].fillna(0) >= 45).to_numpy(np.int8),
        "small_mcap": (b6["real_free_mcap"].fillna(25) <= 35).to_numpy(np.int8),
        "sole_4b": (b6["is_sole_4b"].fillna(0) == 1).to_numpy(np.int8),
        "rival_ge2": (b6["b4_rival_cnt"].fillna(1) >= 2).to_numpy(np.int8),
        "open_3_6": ((b6["open_pct"] >= 0.030) & (b6["open_pct"] <= 0.060)).to_numpy(np.int8),
        "obc_ge1": (b6["open_board_count"].fillna(0) >= 1).to_numpy(np.int8),
        "seal_early": (b6["first_seal_time"].astype(str) <= "09:45:00").to_numpy(np.int8),
        "hi_to25": (b6["prev_real_to"].fillna(20) >= 25.0).to_numpy(np.int8),
        # 3to4 genes
        "pos20_d0_le40": (b6["pos20_d0"].fillna(0.5) <= 0.40).to_numpy(np.int8),
        "pos20_d0_gt65": (b6["pos20_d0"].fillna(0.5) > 0.65).to_numpy(np.int8),
        "xq_ge4": (b6["xq_cnt_2d"].fillna(0) >= 4).to_numpy(np.int8),
        "xq_quiet": (b6["xq_cnt_2d"].fillna(0) < 4).to_numpy(np.int8),
        "fb_assist2": ((b6["plate_fb_ho_cnt"].fillna(0) >= 2) & (b6["plate_fb_yz_cnt"].fillna(0) == 0)).to_numpy(np.int8),
        "fb_yizi": (b6["plate_fb_yz_cnt"].fillna(0) >= 1).to_numpy(np.int8),
        "csrc_zt_ge2": (b6["csrc_zt_cnt"].fillna(1) >= 2).to_numpy(np.int8),
        "p_elo_115": (b6["p_elo"].fillna(100) >= 115).to_numpy(np.int8),
    }
    base_names = list(feats.keys())
    Xb = np.column_stack([feats[k] for k in base_names]).astype(np.int8)
    uniq_dts = sorted(set(bd_arr[bd_arr >= wf_start]))
    dt_to_rows = {d: np.where(bd_arr == d)[0] for d in uniq_dts}
    all_bd_sorted = sorted(set(bd_arr))
    bd_id_map = {d: j for j, d in enumerate(all_bd_sorted)}
    day_ids = np.array([bd_id_map[d] for d in bd_arr], dtype=int)

    bl_mask = np.ones(n, dtype=bool)
    last_cnt = -1
    cur_card = None
    for dt_v in uniq_dts:
        r_idx = dt_to_rows[dt_v]
        tr_mask = base_mask & (ex_arr < dt_v) & (ex_arr != "None") & np.isfinite(ret_030)
        tr_cnt = int(tr_mask.sum())
        if tr_cnt < 30:
            continue
        if tr_cnt != last_cnt:
            last_cnt = tr_cnt
            cur_card = m34.fit_4way_synergy_card(
                Xb[tr_mask], ret_030[tr_mask], y_win[tr_mask], day_ids[tr_mask],
                base_names, min_leaf=8, min_days=6, max_deltas=(10, 15),
                orig_tr=None, mode="minefield_bl",
                t_min_4way=1.8, t_syn_min=1.2, top_k_rules=3, shrink_tau=15.0,
            )
        if cur_card is not None and cur_card.get("mine_rules"):
            for rl in cur_card["mine_rules"]:
                idxs = [base_names.index(c) for c in rl["conj"]]
                hit = np.all(Xb[r_idx][:, idxs] == 1, axis=1)
                bl_mask[r_idx] &= ~hit
    return bl_mask


def eval_4to5_variant(
    name: str,
    group: str,
    tier_tag: str,
    b6: pd.DataFrame,
    entry_mask: np.ndarray,
    exit_mode: str,
    rich_bars: dict,
    b5m: dict,
    sh_map: dict,
    sz_map: dict,
    hold_states: dict,
    bench_df: pd.DataFrame,
    cal_dts: list[str],
    bar_lu: dict,
    max_dt: str,
    score_col: str = "fixed_score",
    rev_mask: Optional[np.ndarray] = None,
    tie_col: Optional[str] = None,
) -> dict:
    """Evaluate a Direction B variant across 5 windows + 10,000x Bootstrap + 50bps stress."""
    sub_df = b6[entry_mask].copy().reset_index(drop=True)
    recs = []
    for r in sub_df.to_dict("records"):
        c6 = r["code6"]
        bd = str(r["buy_date"])[:10]
        ed, r30, ehh, r20 = sim_4to5_exit_unified(
            r, rich_bars.get(c6), b5m, sh_map, sz_map, hold_states.get((c6, bd), {}), exit_mode, fee=cm.FEE_MAIN
        )
        if ed > max_dt:
            continue
        r50 = float(cm.convert_fee(r20, 0.0020, cm.FEE_STRESS))
        recs.append({
            "buy_date": bd, "buy_hhmm": 925, "exit_date": ed, "exit_hhmm": int(ehh),
            "code": c6, "name": str(r["name"]), "score": float(r[score_col]),
            "open_pct": float(r["open_pct"]), "buy_price": float(r["buy_price_val"]),
            "net_ret": float(r30), "net_ret_020": float(r20), "net_ret_030": float(r30), "net_ret_050": float(r50),
        })

    raw_df = pd.DataFrame(recs)
    raw_srt, slot_df = cm.select_single_slot_4to5(raw_df, score_col="score", tie_col=tie_col)
    if not slot_df.empty:
        slot_df["mtm_pairs_json"] = cm.build_mtm_pairs(slot_df, cal_dts, bar_lu, ret_col="net_ret", px_col="buy_price")

    windows = cm.eval_all_windows(slot_df, raw_srt, bench_df, max_dt=max_dt, base_fee=cm.FEE_MAIN)
    rets_ss = slot_df["net_ret"].to_numpy(float) if not slot_df.empty else np.array([], dtype=float)
    boot = cm.bootstrap_10k(rets_ss, n_boot=10000, seed=42)

    perm_rev = {}
    if rev_mask is not None and np.any(rev_mask):
        rev_df_raw = b6[rev_mask].copy()
        rev_recs = []
        for r in rev_df_raw.to_dict("records"):
            c6, bd = r["code6"], str(r["buy_date"])[:10]
            ed, r30, ehh, _ = sim_4to5_exit_unified(r, rich_bars.get(c6), b5m, sh_map, sz_map, hold_states.get((c6, bd), {}), exit_mode, fee=cm.FEE_MAIN)
            if ed <= max_dt:
                rev_recs.append({"buy_date": bd, "buy_hhmm": 925, "exit_date": ed, "exit_hhmm": int(ehh), "code": c6, "score": float(r[score_col]), "open_pct": float(r["open_pct"]), "net_ret": float(r30)})
        if rev_recs:
            _, rev_ss = cm.select_single_slot_4to5(pd.DataFrame(rev_recs), score_col="score", tie_col=tie_col)
            perm_rev = cm.perm_2sample_10k(rets_ss, rev_ss["net_ret"].to_numpy(float) if not rev_ss.empty else np.array([]), n_perm=10000, seed=42)

    return {
        "name": name, "group": group, "tier": tier_tag, "exit_mode": exit_mode,
        "windows": windows, "bootstrap_10k": boot, "perm_vs_excluded": perm_rev,
        "raw_df": raw_srt, "slot_df": slot_df,
    }


def run_pipeline(max_date: str = "2026-11-16", trunc_mode: bool = False) -> dict:
    t0 = time.time()
    bench_df, sh2, sz2, csi, all_dts = cm.load_bench_and_indices(max_dt=max_date)
    cal_dts = bench_df["trade_date"].tolist()

    df_e = pd.read_parquet(f"{P3_DIR}/w2_4to5_enriched_master.parquet")
    df_e = df_e[df_e["buy_date"].astype(str).str[:10] <= max_date].copy().reset_index(drop=True)
    with open(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json") as f:
        holders = json.load(f)
    holders = {c6: [rec for rec in lst if str(rec[0])[:10] <= max_date] for c6, lst in holders.items()}

    df_tox_all = pd.read_parquet(f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet")
    df_tox_all = df_tox_all[df_tox_all["pub_datetime_cst"].astype(str) <= max_date + " 23:59:59"].copy()
    df_real_tox = df_tox_all[df_tox_all["title"].astype(str).str.contains(TOX_RE)].copy()
    df_strict_tox = df_tox_all[df_tox_all["title"].astype(str).str.contains(TOX_STRICT_RE)].copy()

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
    flt_sc = ((ds.field("prev_streak") >= 4) | (ds.field("dt") >= "2026-11-08")) & (ds.field("dt") <= max_date)
    sc_ds = ds.dataset(f"{WAVE1_BASE}/stock_day_core_features_pit.parquet", format="parquet")
    chunks = [b.to_pandas() for b in sc_ds.scanner(columns=sc_cols, filter=flt_sc, batch_size=65536, use_threads=False).to_batches()]
    df_sc = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=sc_cols)
    del chunks
    df_sc["dt"] = df_sc["dt"].astype(str)
    df_sc["c6"] = df_sc["c6"].astype(str)

    codes_needed = set(df_e["code"].astype(str).str.zfill(6))
    if max_date >= "2026-11-10":
        codes_needed |= set(df_sc[(df_sc["dt"] >= "2026-11-10") & (df_sc["dt"] <= max_date) & (df_sc["prev_streak"] == 4) & (~df_sc["is_st_pit"]) & (~df_sc["is_20cm"])]["c6"].astype(str).str.zfill(6))

    hyd_cols = ["dt", "c6", "kpl_in_t1", "kpl_zt3_t1", "real_turn_pct_t1", "lock_top10_pct_pre", "d1_first_seal_hhmm_t1"]
    chunks2 = [b.to_pandas() for b in sc_ds.scanner(columns=hyd_cols, filter=ds.field("c6").isin(sorted(codes_needed)) & (ds.field("dt") <= max_date), batch_size=65536, use_threads=False).to_batches()]
    df_hyd = pd.concat(chunks2, ignore_index=True).drop_duplicates(["dt", "c6"], keep="first") if chunks2 else pd.DataFrame(columns=hyd_cols)
    del chunks2
    df_hyd["dt"] = df_hyd["dt"].astype(str)
    df_hyd["c6"] = df_hyd["c6"].astype(str)

    df_mk = pd.read_parquet(f"{WAVE1_BASE}/market_daily_all_new_factors_pit.parquet")
    df_mk = df_mk[df_mk["trade_date"] <= max_date].copy()

    b6_codes = set(df_e[df_e["B6_auc_sweet_2_7_bought"] == 1]["code"].astype(str).str.zfill(6))
    if max_date >= "2026-11-10":
        b6_codes |= set(df_sc[(df_sc["dt"] >= "2026-11-10") & (df_sc["dt"] <= max_date) & (df_sc["prev_streak"] == 4) & (~df_sc["is_st_pit"]) & (~df_sc["is_20cm"])]["c6"].astype(str).str.zfill(6))

    rich_bars = load_daily_bars_rich(b6_codes, max_dt=max_date)
    bar_lu = {
        (c6_k, cb["dts"][i_k]): (float(cb["open"][i_k]), float(cb["close"][i_k]), float(cb["adjf"][i_k]))
        for c6_k, cb in rich_bars.items()
        for i_k in range(len(cb["dts"]))
    }
    b5m = cm.load_merged_5m_bars(b6_codes, max_dt=max_date)

    if max_date >= "2026-11-10":
        df_ext = build_extension_20261110_20261124(list(df_e.columns), df_sc, df_mk, holders, df_real_tox, rich_bars, cal_dts, max_dt=max_date)
        if not df_ext.empty:
            df_e = pd.concat([df_e, df_ext], ignore_index=True)

    df_e["code6"] = df_e["code"].astype(str).str.zfill(6)
    df_e = df_e.merge(df_hyd.rename(columns={"dt": "buy_date", "c6": "code6"}), on=["buy_date", "code6"], how="left")
    del df_hyd
    df_e["kpl_in_t1"] = df_e["kpl_in_t1"].fillna(0)
    df_e["prev_real_to"] = df_e["prev_real_to"].fillna(df_e["real_turn_pct_t1"]).fillna(20.0)
    df_e["lock_top10"] = np.where(df_e["lock_top10_pct_pre"].notna() & (df_e["lock_top10_pct_pre"] > 0), df_e["lock_top10_pct_pre"], df_e["lock_top10"])

    # Score FixPIT and StrictJianchi
    fix_res = [score_fixed_4to5(r.to_dict(), holders, df_real_tox) for _, r in df_e.iterrows()]
    df_e["fixed_score"] = [x[0] for x in fix_res]
    strict_res = [score_fixed_4to5(r.to_dict(), holders, df_strict_tox) for _, r in df_e.iterrows()]
    df_e["strict_score"] = [x[0] for x in strict_res]
    df_e["buy_price_val"] = df_e["B6_auc_sweet_2_7_px"].fillna(0.0).astype(float)

    b6 = df_e[df_e["B6_auc_sweet_2_7_bought"] == 1].copy().reset_index(drop=True)
    b6["exit_date"] = b6["exdt_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"].astype(str)
    b6["ret_E4_020"] = b6["ret_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"].astype(float)
    b6["ret_E4_030"] = convert_fee_arr(b6["ret_E4_020"].to_numpy(float), 0.0020, 0.0030)
    b6 = b6[b6["exit_date"] <= max_date].copy().reset_index(drop=True)

    # Hydrate 3to4 pre-buy genes (pos20_d0, xq_cnt_2d, plate_fb, csrc_zt, p_elo) & holding 7-factor states
    b6 = build_pos20_d0_and_xq_pit(b6, rich_bars, max_dt=max_date)
    risk_ctx = build_daily_7factor_hold_map(b6_codes, df_mk, df_sc, rich_bars, max_dt=max_date)
    hold_states = compute_4to5_hold_states(b6, rich_bars, risk_ctx, max_dt=max_date)
    del df_sc, df_mk, risk_ctx, holders, df_tox_all, df_real_tox, df_strict_tox, df_e
    gc.collect()
    pa.default_memory_pool().release_unused()

    # Exact baseline masks
    m_sj114 = b6["strict_score"].to_numpy(float) >= 114
    m_fix120 = b6["fixed_score"].to_numpy(float) >= 120
    m_fix114 = b6["fixed_score"].to_numpy(float) >= 114
    m_fix100 = b6["fixed_score"].to_numpy(float) >= 100
    m_gate = b6["fixed_score"].to_numpy(float) > -500

    # 3to4 pre-buy gene masks
    m_pos20_le40 = b6["pos20_d0"].to_numpy(float) <= 0.40
    m_pos20_le50 = b6["pos20_d0"].to_numpy(float) <= 0.50
    m_pos20_le65 = b6["pos20_d0"].to_numpy(float) <= 0.65
    m_xq_quiet = b6["xq_cnt_2d"].to_numpy(int) < 4
    m_xq_lt8 = b6["xq_cnt_2d"].to_numpy(int) < 8
    m_fb_ho1 = b6["plate_fb_ho_cnt"].to_numpy(int) >= 1
    m_fb_ho2 = (b6["plate_fb_ho_cnt"].to_numpy(int) >= 2) & (b6["plate_fb_yz_cnt"].to_numpy(int) == 0)
    m_fb_noyz = b6["plate_fb_yz_cnt"].to_numpy(int) == 0
    m_peers_ok = b6["plate_peers_open_avg"].to_numpy(float) >= -0.015
    m_csrc2 = b6["csrc_zt_cnt"].to_numpy(int) >= 2
    m_elo115 = b6["p_elo"].to_numpy(float) >= 115.0
    m_cold45 = b6["mkt_zt_prev"].fillna(60).to_numpy(float) < 45
    m_cold50 = b6["mkt_zt_prev"].fillna(60).to_numpy(float) < 50
    m_warm35_85 = b6["mkt_zt_prev"].fillna(60).between(35, 85).to_numpy(bool)
    m_sole = b6["is_sole_4b"].fillna(0).to_numpy(int) == 1
    m_lock45 = b6["lock_top10"].fillna(0).to_numpy(float) >= 45.0
    m_wf4way_34 = build_causal_wf_4way_with_34genes(b6, m_gate, wf_start="2023-01-03")

    # Verify baseline parity vs RD048 JSON/parquet at full mode
    # Note: RD048 `_rd048_w2_lib.py` & `step1_redteam_wave1_audit.py` break score ties by `code asc` (SJ114=24.4855),
    # while `step1_gem1_4to5_polish.py` breaks ties by `open_pct desc` (SJ114=22.8251, Fix114=18.3275; raw 37 trades identical!).
    base_sj = eval_4to5_variant("SJ114_Base", "0_BASE", "StrictJianchi_114", b6, m_sj114, "E4_Base", rich_bars, b5m, sh2, sz2, hold_states, bench_df, cal_dts, bar_lu, max_date, score_col="strict_score", tie_col=None)
    base_sj_open = eval_4to5_variant("SJ114_Base_TieOpen", "0_BASE", "StrictJianchi_114", b6, m_sj114, "E4_Base", rich_bars, b5m, sh2, sz2, hold_states, bench_df, cal_dts, bar_lu, max_date, score_col="strict_score", tie_col="open_pct")
    base_f120 = eval_4to5_variant("Fix120_Base", "0_BASE", "FixPIT_120", b6, m_fix120, "E4_Base", rich_bars, b5m, sh2, sz2, hold_states, bench_df, cal_dts, bar_lu, max_date, score_col="fixed_score", tie_col=None)
    if not trunc_mode:
        assert base_sj["windows"]["FULL_5Y"]["raw_n"] == 37, f"SJ114 raw_n={base_sj['windows']['FULL_5Y']['raw_n']}"
        assert base_sj["windows"]["FULL_5Y"]["ss_n"] == 33, f"SJ114 ss_n={base_sj['windows']['FULL_5Y']['ss_n']}"
        assert abs(base_sj["windows"]["FULL_5Y"]["nav"] - 24.4855) < 0.001, f"SJ114 code-tie nav={base_sj['windows']['FULL_5Y']['nav']}"
        assert abs(base_sj_open["windows"]["FULL_5Y"]["nav"] - 22.8251) < 0.001, f"SJ114 open-tie nav={base_sj_open['windows']['FULL_5Y']['nav']}"
        assert base_f120["windows"]["FULL_5Y"]["ss_n"] == 15, f"Fix120 ss_n={base_f120['windows']['FULL_5Y']['ss_n']}"
        assert abs(base_f120["windows"]["FULL_5Y"]["nav"] - 9.3298) < 0.001, f"Fix120 nav={base_f120['windows']['FULL_5Y']['nav']}"

    # Build low-DOF experiments for BOTH tiers (StrictJianchi_114 & FixPIT_120) + FixPIT_114 & FixPIT_100 checks
    entry_rules = [
        ("Base", lambda m: m, None),
        ("SkipCold45", lambda m: m & (~m_cold45), lambda m: m & m_cold45),
        ("Cold50_ReqSoleOrLock45", lambda m: m & ((~m_cold50) | m_sole | m_lock45), lambda m: m & m_cold50 & (~m_sole) & (~m_lock45)),
        ("Cold50_ReqQuietOrSole", lambda m: m & ((~m_cold50) | m_xq_quiet | m_sole), lambda m: m & m_cold50 & (~m_xq_quiet) & (~m_sole)),
        ("Warm35_85", lambda m: m & m_warm35_85, lambda m: m & (~m_warm35_85)),
        ("WF_4WayBL_34Genes", lambda m: m & m_wf4way_34, lambda m: m & (~m_wf4way_34)),
        ("Pos20_d0_le65", lambda m: m & m_pos20_le65, lambda m: m & (~m_pos20_le65)),
        ("Pos20_d0_le50", lambda m: m & m_pos20_le50, lambda m: m & (~m_pos20_le50)),
        ("Pos20_d0_le40", lambda m: m & m_pos20_le40, lambda m: m & (~m_pos20_le40)),
        ("XQ_QuietLt4", lambda m: m & m_xq_quiet, lambda m: m & (~m_xq_quiet)),
        ("XQ_Lt8", lambda m: m & m_xq_lt8, lambda m: m & (~m_xq_lt8)),
        ("Plate_FBAssist1", lambda m: m & m_fb_ho1, lambda m: m & (~m_fb_ho1)),
        ("Plate_FBNoYZ", lambda m: m & m_fb_noyz, lambda m: m & (~m_fb_noyz)),
        ("Plate_PeersOk", lambda m: m & m_peers_ok, lambda m: m & (~m_peers_ok)),
        ("CSRC_ZT_ge2", lambda m: m & m_csrc2, lambda m: m & (~m_csrc2)),
        ("PElo_115", lambda m: m & m_elo115, lambda m: m & (~m_elo115)),
    ]

    exit_rules = [
        ("E4_Base", "0_BASE"),
        ("E4_DtDefer", "E_AUDIT"),
        ("E1_CutWeak", "E_34GENE"),
        ("E_V41_7f_d70", "E_34GENE"),
        ("E_V41_7f_d70_DtDefer", "E_AUDIT"),
        ("E_V41_7f_d60", "E_34GENE"),
        ("E_V41_7f_d80", "E_34GENE"),
        ("E_NoYangImm", "E_34GENE"),
        ("E_7f_StripImm", "E_34GENE"),
        ("E_7f2_StripImm", "E_34GENE"),
        ("E_Dev93_All", "E_34GENE"),
        ("E_Dev95_All", "E_34GENE"),
        ("E_Dev93_5b", "E_34GENE"),
        ("E_Dev95_5b", "E_34GENE"),
        ("E_Reb20_Dev96", "E_34GENE"),
        ("E_Reb20_Dev96_DtDefer", "E_AUDIT"),
        ("E_Reb20_Dev95", "E_34GENE"),
        ("E_Reb20_Dev93", "E_34GENE"),
        ("E_Risk7_Dev95", "E_34GENE"),
        ("E_V41_Reb20Dev96", "E_34GENE"),
        ("E_V41_Reb20Dev96_DtDefer", "E_AUDIT"),
    ]

    variants = {}
    summary_rows = []
    tier_specs = [
        ("SJ114", "StrictJianchi_114", m_sj114, "strict_score", base_sj),
        ("Fix120", "FixPIT_120", m_fix120, "fixed_score", base_f120),
    ]

    for tshort, tname, tmask, sc_col, base_obj in tier_specs:
        # 1. Single entry rules with E4_Base
        for ern, mfn, rfn in entry_rules:
            vname = f"{tshort}__Ent_{ern}"
            grp = "0_BASE" if ern == "Base" else "B_ENTRY"
            if ern == "Base":
                res = base_obj
            else:
                res = eval_4to5_variant(vname, grp, tname, b6, mfn(tmask), "E4_Base", rich_bars, b5m, sh2, sz2, hold_states, bench_df, cal_dts, bar_lu, max_date, score_col=sc_col, rev_mask=rfn(tmask) if rfn else None)
            variants[vname] = res

        # 2. Single exit rules with Base entry
        for exm, grp in exit_rules:
            if exm == "E4_Base":
                continue
            vname = f"{tshort}__Ex_{exm}"
            res = eval_4to5_variant(vname, grp, tname, b6, tmask, exm, rich_bars, b5m, sh2, sz2, hold_states, bench_df, cal_dts, bar_lu, max_date, score_col=sc_col)
            variants[vname] = res

        # 3. Low-DOF (<=2 rules) entry + exit combinations (strictly anchored on top interpretable 3to4 genes)
        combo_specs = [
            ("XQQuiet_x_V41_7f", m_xq_quiet, "E_V41_7f_d70"),
            ("XQQuiet_x_Reb20Dev96", m_xq_quiet, "E_Reb20_Dev96"),
            ("XQQuiet_x_V41_Reb20Dev96", m_xq_quiet, "E_V41_Reb20Dev96"),
            ("Cold50SoleLock_x_V41_7f", (~m_cold50) | m_sole | m_lock45, "E_V41_7f_d70"),
            ("Cold50SoleLock_x_V41_Reb20Dev96", (~m_cold50) | m_sole | m_lock45, "E_V41_Reb20Dev96"),
            ("Pos20_le65_x_V41_7f", m_pos20_le65, "E_V41_7f_d70"),
            ("Pos20_le65_x_V41_Reb20Dev96", m_pos20_le65, "E_V41_Reb20Dev96"),
            ("XQQuiet_x_Pos20_le65", m_xq_quiet & m_pos20_le65, "E4_Base"),
            ("XQQuiet_x_Cold50SoleLock", m_xq_quiet & ((~m_cold50) | m_sole | m_lock45), "E4_Base"),
            ("SkipCold45_x_V41_Reb20Dev96", ~m_cold45, "E_V41_Reb20Dev96"),
        ]
        for cname, cmask, cex in combo_specs:
            vname = f"{tshort}__Cmb_{cname}"
            res = eval_4to5_variant(vname, "B_COMBO_2DOF", tname, b6, tmask & cmask, cex, rich_bars, b5m, sh2, sz2, hold_states, bench_df, cal_dts, bar_lu, max_date, score_col=sc_col, rev_mask=tmask & (~cmask))
            variants[vname] = res

    # Also compute summary rows & auxiliary large-sample FixPIT_114 (N=45) & FixPIT_100 checks
    aux_large = {}
    if not trunc_mode:
        for ltag, lmask in [("Fix114_N45", m_fix114), ("Fix100_Large", m_fix100)]:
            aux_large[ltag] = {}
            for anm, emask, eex in [
                ("Base", lmask, "E4_Base"),
                ("Ent_XQQuiet", lmask & m_xq_quiet, "E4_Base"),
                ("Ent_Pos20_le65", lmask & m_pos20_le65, "E4_Base"),
                ("Ent_Pos20_le50", lmask & m_pos20_le50, "E4_Base"),
                ("Ent_Cold50SoleLock", lmask & ((~m_cold50) | m_sole | m_lock45), "E4_Base"),
                ("Ent_SkipCold45", lmask & (~m_cold45), "E4_Base"),
                ("Ent_WF4Way34", lmask & m_wf4way_34, "E4_Base"),
                ("Ent_FBAssist1", lmask & m_fb_ho1, "E4_Base"),
                ("Ent_PeersOk", lmask & m_peers_ok, "E4_Base"),
                ("Ex_V41_7f_d70", lmask, "E_V41_7f_d70"),
                ("Ex_Reb20_Dev96", lmask, "E_Reb20_Dev96"),
                ("Ex_V41_Reb20Dev96", lmask, "E_V41_Reb20Dev96"),
                ("Ex_Dev95_5b", lmask, "E_Dev95_5b"),
                ("Ex_7f_StripImm", lmask, "E_7f_StripImm"),
                ("Ex_DtDefer", lmask, "E4_DtDefer"),
            ]:
                ar = eval_4to5_variant(f"{ltag}__{anm}", "AUX", ltag, b6, emask, eex, rich_bars, b5m, sh2, sz2, hold_states, bench_df, cal_dts, bar_lu, max_date, score_col="fixed_score", tie_col=("open_pct" if ltag == "Fix114_N45" else None))
                aw = ar["windows"]
                aux_large[ltag][anm] = {
                    "ss_n": aw["FULL_5Y"]["ss_n"],
                    "IS_nav": aw["IS_21_23"]["nav"], "OOS_nav": aw["OOS_24_26"]["nav"],
                    "Y2526_nav": aw["Y2025_2026"]["nav"], "FULL_nav": aw["FULL_5Y"]["nav"],
                    "FULL_ex2": aw["FULL_5Y"]["ex2_nav"], "FULL_50bps": aw["FULL_5Y"]["nav_50bps"],
                    "boot_p05": ar["bootstrap_10k"]["mean_p05_pct"], "prob_gt0": ar["bootstrap_10k"]["prob_mean_gt_0"],
                }

    if not trunc_mode:
        for vn, vd in variants.items():
            tshort = vn.split("__")[0]
            bw = variants[f"{tshort}__Ent_Base"]["windows"]
            w = vd["windows"]
            w_is, w_oos, w_25, w_26, w_h2, w_5y = w["IS_21_23"], w["OOS_24_26"], w["Y2025_2026"], w["Y2026"], w["Y2026_H2"], w["FULL_5Y"]
            b_is, b_oos, b_25, b_5y = bw["IS_21_23"], bw["OOS_24_26"], bw["Y2025_2026"], bw["FULL_5Y"]
            bt = vd["bootstrap_10k"]
            beat_3win = (
                (w_is["nav"] >= b_is["nav"] - 1e-4)
                and (w_oos["nav"] >= b_oos["nav"] - 1e-4)
                and (w_25["nav"] >= b_25["nav"] - 1e-4)
                and (w_5y["nav"] > b_5y["nav"] + 1e-4)
                and (w_5y["ex2_nav"] >= b_5y["ex2_nav"] - 1e-4)
            )
            summary_rows.append({
                "name": vn, "tier": tshort, "group": vd["group"],
                "ss_n": w_5y["ss_n"], "wr_pct": w_5y["wr_pct"], "plr": w_5y["plr"], "mean_pct": w_5y["mean_pct"],
                "IS_n": w_is["ss_n"], "IS_nav": w_is["nav"],
                "OOS_n": w_oos["ss_n"], "OOS_nav": w_oos["nav"],
                "Y2526_nav": w_25["nav"], "Y26_nav": w_26["nav"], "H2_nav": w_h2["nav"],
                "FULL_nav": w_5y["nav"], "FULL_eq": w_5y["eq_nav"], "FULL_ex2": w_5y["ex2_nav"],
                "FULL_50bps": w_5y["nav_50bps"], "FULL_sh": w_5y["daily_sharpe"], "FULL_mdd": w_5y["daily_mdd_pct"],
                "boot_mean_p05": bt["mean_p05_pct"], "boot_nav_p05": bt["nav_p05"], "boot_p_gt0": bt["prob_mean_gt_0"],
                "beat_3win_and_ex2": beat_3win,
            })

    return {
        "max_date": max_date,
        "elapsed_sec": round(time.time() - t0, 2),
        "b6_count": int(len(b6)),
        "variants": {k: {kk: vv for kk, vv in v.items() if kk not in ("raw_df", "slot_df")} for k, v in variants.items()},
        "ledgers": {k: (v["raw_df"], v["slot_df"]) for k, v in variants.items()},
        "summary_rows": summary_rows,
        "aux_large_pools": aux_large,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trunc-only-out", default="")
    args = parser.parse_args()

    if args.trunc_only_out:
        tr = run_pipeline(max_date="2024-12-31", trunc_mode=True)
        out = {
            vn: {
                "ss_n": vd["windows"]["FULL_5Y"]["ss_n"],
                "nav": vd["windows"]["FULL_5Y"]["nav"],
                "mean_pct": vd["windows"]["FULL_5Y"]["mean_pct"],
            }
            for vn, vd in tr["variants"].items()
        }
        with open(args.trunc_only_out, "w", encoding="utf-8") as f:
            json.dump(cm.sanitize_json(out), f, ensure_ascii=False)
        return

    print("[Dir B: 3to4 -> 4to5] Running full 2022-01-04..2026-11-16 audit...")
    full_res = run_pipeline(max_date="2026-11-16", trunc_mode=False)

    df_sum = pd.DataFrame(full_res["summary_rows"]).sort_values(["tier", "beat_3win_and_ex2", "FULL_nav"], ascending=[True, False, False])
    df_sum.to_csv(f"{cm.OUT_DIR}/dirB_summary_all_variants.csv", index=False, encoding="utf-8-sig")

    # Save baselines + any beat_3win_and_ex2 passing ledgers
    pass_names = [r["name"] for r in full_res["summary_rows"] if r["beat_3win_and_ex2"]]
    for save_nm in sorted(set(["SJ114__Ent_Base", "Fix120__Ent_Base"] + pass_names)):
        raw_df, slot_df = full_res["ledgers"][save_nm]
        slot_df.to_csv(f"{cm.OUT_DIR}/dirB_{save_nm}_slot.csv", index=False, encoding="utf-8-sig")
        slot_df.to_parquet(f"{cm.OUT_DIR}/dirB_{save_nm}_slot.parquet", index=False)
        raw_df.to_parquet(f"{cm.OUT_DIR}/dirB_{save_nm}_raw.parquet", index=False)

    # Physical 2024-12-31 truncation check in isolated child process
    print("[Dir B] Running 2024-12-31 physical truncation verification in isolated child process...")
    tmp_trunc = f"{cm.OUT_DIR}/_tmp_dirB_trunc.json"
    subprocess.run([sys.executable, os.path.abspath(__file__), "--trunc-only-out", tmp_trunc], check=True)
    with open(tmp_trunc, encoding="utf-8") as f:
        trunc_res = json.load(f)
    os.remove(tmp_trunc)

    max_abs_diff = 0.0
    trunc_audit = {}
    for vn, (raw_df, slot_df) in full_res["ledgers"].items():
        sub24 = slot_df[slot_df["exit_date"] <= "2024-12-31"] if not slot_df.empty else slot_df
        fn = int(len(sub24))
        fnav = round(float(np.prod(1.0 + sub24["net_ret"].to_numpy(float))), 4) if fn > 0 else 1.0
        fmean = round(float(sub24["net_ret"].to_numpy(float).mean() * 100.0), 2) if fn > 0 else 0.0
        tv = trunc_res.get(vn, {})
        tn = int(tv.get("ss_n", 0))
        tnav = float(tv.get("nav", 1.0))
        tmean = float(tv.get("mean_pct", 0.0))
        d_nav, d_mean, d_n = abs(fnav - tnav), abs(fmean - tmean), abs(fn - tn)
        max_abs_diff = max(max_abs_diff, d_nav, d_mean, float(d_n))
        trunc_audit[vn] = {"full_n": fn, "trunc_n": tn, "nav_diff": round(d_nav, 10), "mean_diff": round(d_mean, 10)}

    out_json = {
        "direction": "B_3to4_to_4to5_entry_exit",
        "max_date": full_res["max_date"],
        "trunc_20241231_max_abs_diff": round(max_abs_diff, 10),
        "n_variants_tested": len(full_res["variants"]),
        "pass_candidates": pass_names,
        "aux_large_pools": full_res["aux_large_pools"],
        "variants": full_res["variants"],
        "trunc_audit_sample": {k: trunc_audit[k] for k in list(trunc_audit.keys())[:10]},
    }
    with open(f"{cm.OUT_DIR}/dirB_audit.json", "w", encoding="utf-8") as f:
        json.dump(cm.sanitize_json(out_json), f, ensure_ascii=False, indent=2)

    print(f"[Dir B DONE in {full_res['elapsed_sec']}s] max_trunc_diff={max_abs_diff} | pass_candidates={pass_names}")
    for t in ("SJ114", "Fix120"):
        print(f"\n--- {t} Summary ---")
        print(df_sum[df_sum["tier"] == t].to_string(index=False))


if __name__ == "__main__":
    main()
