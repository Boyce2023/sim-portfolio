#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
exit_factor_engine.py
三进四 V4.0 持仓期跨策略动态卖点因子 (XF01~XF30) 统一 PIT 特征抽取与四动作仿真引擎。
严守：
  - 零未来函数：t 日 09:25 仅看 <= t-1 盘后与 < t 09:25:00 公告/社区及 t 09:25 竞价；
    t 日 14:55 断板决策严禁偷看 t 日晚龙虎榜或 t 日收盘后全市场统计！
  - 支持对任意持仓日状态矩阵计算全部 30 个因子及其参数化四动作卖点仿真。
"""

import bisect
import math
import os
import re
import sys

sys.dont_write_bytecode = True

import numpy as np
import pandas as pd

UPG_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
sys.path.insert(0, UPG_DIR)
import upgrade_3to4_pit as u34

FEE_RATE = 0.0020
RE_TECH_KPL = re.compile(r"(?:算力|芯片|半导体|机器人|人工智能|AI|华为|低空|固态电池)")


def _cnt_win(arr: np.ndarray | None, lo: str, hi: str) -> int:
    if arr is None or len(arr) == 0:
        return 0
    i0 = int(np.searchsorted(arr, lo, side="left"))
    i1 = int(np.searchsorted(arr, hi, side="left"))
    if i1 > 0:
        assert arr[i1 - 1] < hi, f"PIT time breach: {arr[i1-1]} >= {hi}"
    return max(0, i1 - i0)


def get_double_dev_px_pit(c6: str, cb: dict, cp: int, sh_map: dict, sz_map: dict, ratio: float = 0.93) -> tuple[float, float]:
    """严格 PIT 双严重异动限价计算（仅用昨日收盘指数 I_ref = imap[dts[cp-1]]）"""
    if cp < 1:
        return 99999.0, 99999.0
    imap = sh_map if c6.startswith("60") else sz_map
    sd = cb["dts"][cp - 1]
    ir = imap.get(sd)
    if not ir:
        return 99999.0, 99999.0
    disc = 1.0 - ratio
    bp_buf = 99999.0
    bp_100 = 99999.0
    adj_cp = cb["adjf"][cp]
    for k in range(1, min(11, cp + 1)):
        p = cp - k
        bi = imap.get(cb["dts"][p])
        bc = cb["close"][p] * cb["adjf"][p] / adj_cp
        if bi and bc > 0:
            idx_ret = ir / bi - 1.0
            bp_buf = min(bp_buf, bc * (1.0 + (1.0 - disc) + idx_ret))
            bp_100 = min(bp_100, bc * (2.0 + idx_ret))
    for k in range(1, min(31, cp + 1)):
        p = cp - k
        bi = imap.get(cb["dts"][p])
        bc = cb["close"][p] * cb["adjf"][p] / adj_cp
        if bi and bc > 0:
            idx_ret = ir / bi - 1.0
            bp_buf = min(bp_buf, bc * (1.0 + (2.0 - disc) + idx_ret))
            bp_100 = min(bp_100, bc * (3.0 + idx_ret))
    return float(bp_buf), float(bp_100)


def _get_lock10(holders_map: dict, c6: str, ref_dt: str) -> float:
    recs = [x for x in holders_map.get(c6, []) if str(x[0])[:10] <= ref_dt]
    return float(max(recs, key=lambda x: (str(x[1]), str(x[0])))[2]) if recs else 38.0


def _compute_hd_score_on_break_day(
    cache: dict,
    c6: str,
    cb: dict,
    k: int,
    d1_dt: str,
    lhb_prev: dict | None,
    lhb_prev2: dict | None,
    s_reg_hit: bool,
    tox_hit: bool,
    ex_reg5_cnt: int,
    my_plate: str,
    p_elo: float,
    lock10: float,
    top_yz_locked: bool,
) -> tuple[int, bool]:
    """
    严格按高标首阴 V5.1 口径在断板日 k 的 14:55 实时计算「首阴反包分」(0 未来函数)：
      - 使用 k-1 盘后全市场/板块/龙虎榜/封单 + k 日 <09:25 监管公告 + k 日盘中 OHLC/换手。
      - 注意：k 日当日晚龙虎榜在 14:55 尚未公布，故 LHB 项用已知最新一期 (k-1 / k-2)。
    返回 (score, is_vetoed)
    """
    dt_k = str(cb["dts"][k])
    d_prev = str(cb["dts"][k - 1])
    d_prev2 = str(cb["dts"][k - 2]) if k >= 2 else d_prev
    env_p = cache["mkt_env"].get(d_prev, {})

    ok = float(cb["open"][k])
    hk = float(cb["high"][k])
    lk = float(cb["low"][k])
    clk = float(cb["close"][k])
    pck = float(cb["pre_c"][k])
    tok = float(cb["to"][k])
    mcap_k = float(cb["mcap"][k]) if cb["mcap"][k] > 0 else 50.0
    o_pct_k = (ok / pck - 1.0) if pck > 0 else 0.0
    l_pct_k = (lk / pck - 1.0) if pck > 0 else 0.0

    # 一票否决检查（14:55 可知）
    lh_prev = lhb_prev["lh_cnt"] if lhb_prev else 0
    is_vetoed = bool(s_reg_hit or tox_hit or (ex_reg5_cnt >= 2) or (tok > 35.0) or (lh_prev >= 3))

    sc = 60
    # 1. 近10日高标断板跌停反包率 (k-1)
    brk_r10 = float(env_p.get("brk_dt_r10", 0.0))
    sc += 12 if brk_r10 >= 0.20 else -8
    # 2. 昨日涨停家数 (k-1)
    n_zt = int(env_p.get("n_zt", 50))
    sc += 10 if n_zt < 70 else (-10 if n_zt >= 95 else 0)
    # 3. 沪深300近5日涨跌幅 (至 k-1)
    csi_dts = cache["all_csi_dts"]
    csi_map = cache["csi_map"]
    ci = bisect.bisect_right(csi_dts, d_prev) - 1
    csi5 = (csi_map[csi_dts[ci]] / csi_map[csi_dts[max(0, ci - 5)]] - 1.0) if ci >= 5 else 0.0
    sc += 8 if csi5 >= -0.005 else (-10 if csi5 < -0.025 else 0)
    # 4. 断板日开盘低吸承接 (k 日早盘)
    sc += 8 if o_pct_k < 0.0 else 0
    # 5. k-1 零炸板且高封板紧度
    tp_prev = cache["tape_ext_map"].get((d_prev, c6), {})
    obc_p = int(tp_prev.get("open_board_count", 0))
    if k >= 1 and cb["pre_c"][k - 1] > 0:
        d0_pre = float(cb["pre_c"][k - 1])
        d0_lp = float(cb["low"][k - 1]) / d0_pre - 1.0
        d0_bp = (float(cb["close"][k - 1]) - float(cb["open"][k - 1])) / d0_pre
        d0_tight = (30.0 if cb["close"][k - 1] == cb["high"][k - 1] else 0.0) + np.clip(d0_lp * 100.0, -10.0, 10.0) * 1.5 + np.clip(d0_bp * 100.0, 0.0, 10.0) * 2.0
    else:
        d0_tight = 25.0
    sc += 6 if (obc_p == 0 and d0_tight >= 35.0) else 0
    # 6. 板块非过热且非独大 (k-1)
    s_d0 = int(cb["streak"][k - 1])
    top1_b = int(env_p.get("max_board", s_d0))
    top2_b = int(env_p.get("top2_board", 0))
    is_dom = bool(s_d0 >= top1_b and (s_d0 - top2_b) >= 2)
    sc += 6 if (p_elo < 135.0 and (not is_dom)) else 0
    # 7-8. 龙虎榜拉萨与机构 (已知最新 k-1)
    in_prev = lhb_prev["inst_buy_cnt"] if lhb_prev else 0
    sc += 6 if lh_prev == 0 else (-10 if lh_prev == 2 else 0)
    sc += -6 if in_prev >= 1 else 0
    # 9. 绝对股价档位 (k 日 14:55)
    sc += 5 if clk <= 20.0 else (-10 if clk > 35.0 else 0)
    # 10. 换手成龙连板数 (至 k-1)
    st_len = max(1, s_d0)
    lo_st = max(0, k - st_len)
    turn_boards = int(np.sum(cb["is_zt"][lo_st:k] & (~cb["is_yizi"][lo_st:k])))
    sc += 5 if turn_boards >= 4 else (-5 if turn_boards <= 2 else 0)
    # 11. 断板日深水撬起 (k 日低点 <= -6%)
    sc += 5 if l_pct_k <= -0.06 else 0
    # 12. 锁仓或真流通市值 >= 45
    fmcap = mcap_k * max(0.05, 1.0 - lock10 / 100.0)
    sc += 6 if (lock10 >= 45.0 or fmcap >= 45.0) else -6
    # 13. 量化做T且少拉萨 (k-1)
    qu_prev = lhb_prev["qu_buy_cnt"] if lhb_prev else 0
    sc += 4 if (qu_prev >= 1 and lh_prev <= 1) else 0
    # 14. 历史妖股记忆 (严格 < 本轮启动连板之前)
    hist_end = max(0, k - st_len)
    if hist_end > 0:
        b1 = cb["streak"][max(0, hist_end - 250):hist_end]
        b3 = cb["streak"][max(0, hist_end - 750):hist_end]
        ms1 = int(b1.max()) if len(b1) else 0
        ms3 = int(b3.max()) if len(b3) else 0
        sc += 6 if ms1 >= 5 else (3 if ms3 >= 5 else 0)
    # 15. 老票新炒与冷饭 (k-1 前 KPL 历史)
    past_zts = [x for x in cache["kpl_stock_zt_hist"].get(c6, []) if x[0] < d_prev]
    d0_ts = pd.Timestamp(d_prev)
    zt_1y = [x for x in past_zts if (d0_ts - pd.Timestamp(x[0])).days <= 365]
    if len(zt_1y) > 0 and my_plate:
        hp = {x[1] for x in past_zts if 45 <= (d0_ts - pd.Timestamp(x[0])).days <= 500}
        sc += 3 if my_plate in hp else -5
    # 16. 前手顶级游资锁仓
    if top_yz_locked:
        sc += 5
    # 17-19. 拉萨占比 / 净买正 / 一日游 (k-1)
    if lhb_prev and lhb_prev["lh_ratio"] >= 0.20 and lhb_prev["tot_b"] > 0:
        sc -= 10
    if lhb_prev and (lhb_prev["tot_b"] - lhb_prev["tot_s"] > 0) and lhb_prev["tot_b"] > 0:
        sc -= 5
    if lhb_prev and lhb_prev["daysurf_buy"]:
        sc -= 6
    # 20-21. k-1 过早秒板与科技热词
    fst_p = tp_prev.get("first_seal_time", "99:99:99")
    if fst_p <= "09:35:00":
        sc -= 5
    if RE_TECH_KPL.search(str(tp_prev.get("reason_desc", "")) + " " + my_plate):
        sc -= 4

    return int(sc), is_vetoed


def precompute_trade_day_states(cache: dict, min_score: float = 0.0) -> dict:
    """
    为每笔 buyable 核心池交易预计算其持仓窗 [pos+1 .. min(n-1, pos+18)] 内每个交易日 k 的全部 30 项因子状态。
    返回 {entry_idx: {k: state_dict}}
    """
    all_dts = cache["all_dts"]
    dt_to_idx = cache["dt_to_idx"]
    code_bars = cache["code_bars_ext"]
    lhb_map = cache["lhb_map"]
    sreg_map = cache["sreg_map"]
    ex_reg_events = cache["ex_reg_events"]
    ex_reg_full = cache.get("ex_reg_full", ex_reg_events)
    clarify_map = cache["clarify_map"]
    halt_warn_map = cache["halt_warn_map"]
    reduce_tox_map = cache["reduce_tox_map"]
    abn_notice_map = cache["abn_notice_map"]
    ir_arr_map = cache["ir_arr_map"]
    xq_arr_map = cache["xq_arr_map"]
    gb_arr_map = cache["gb_arr_map"]
    open_lookup = cache["open_lookup_by_dt"]
    kpl_plate_zt = cache["kpl_plate_zt_stocks"]
    stock_theme = cache["stock_theme_5y"]
    tape_ext = cache["tape_ext_map"]
    mkt_env = cache["mkt_env"]
    csi_map = cache["csi_map"]
    all_csi_dts = cache["all_csi_dts"]
    holders_map = cache["holders_map"]

    states_by_idx = {}

    for e in cache["buy_entries"]:
        if (not e["skel"]) or (e["buy_px"] is None) or (e["sc_v40"] < min_score):
            continue
        c6 = e["code"]
        cb = code_bars[c6]
        pos = e["pos"]
        n = len(cb["dts"])
        d1_dt = e["d1_date"]
        buy_dt = e["buy_date"]
        buy_cut = f"{buy_dt} 09:25:00"
        ex_k = "SH" if c6.startswith("60") else "SZ"

        # 买前 3 日股吧日均发帖基数 (严格 < d1_dt 00:00:00)
        d1_pos = max(0, pos - 3)
        d1_m3_dt = str(cb["dts"][max(0, d1_pos - 3)])
        gb_arr = gb_arr_map.get(c6)
        gb_pre3_cnt = _cnt_win(gb_arr, f"{d1_m3_dt} 00:00:00", f"{d1_dt} 00:00:00")
        gb_pre3_avg = gb_pre3_cnt / 3.0

        # 追踪 [d1_dt .. k-2] 曾买入过的顶级游资集合
        top_yz_bought = set()
        # 先扫描 [d1_pos .. pos-1]（即 D1, D2, D3）的顶级游资买入
        for p_i in range(d1_pos, pos):
            lhb_i = lhb_map.get((str(cb["dts"][p_i]), c6))
            if lhb_i:
                top_yz_bought |= lhb_i["top_yz_buys"]

        last_plate = e["plate"]
        last_elo = float(stock_theme.get((e["sig_date"], c6), {}).get("p_elo", 100.0))

        k_map = {}
        max_k = min(n - 1, pos + 18)
        for k in range(pos + 1, max_k + 1):
            dt_k = str(cb["dts"][k])
            d_prev = str(cb["dts"][k - 1])
            d_prev2 = str(cb["dts"][k - 2]) if k >= 2 else d_prev
            end_cut = f"{dt_k} 09:25:00"

            # 更新 k-2 之前的顶级游资持仓（到 k-1 判断其是否出逃/锁仓）
            if k - 2 >= pos:
                lhb_k2 = lhb_map.get((d_prev2, c6))
                if lhb_k2:
                    top_yz_bought |= lhb_k2["top_yz_buys"]

            lhb_p = lhb_map.get((d_prev, c6))
            lhb_p2 = lhb_map.get((d_prev2, c6))

            # 更新最近已知 KPL 板块与 Elo (截至 d_prev)
            ti_p = stock_theme.get((d_prev, c6))
            if ti_p is not None:
                last_plate = ti_p["plate"]
                last_elo = float(ti_p["p_elo"])

            # === Group 1: LHB (t-1 = d_prev) ===
            lh_cnt = lhb_p["lh_cnt"] if lhb_p else 0
            lh_ratio = lhb_p["lh_ratio"] if lhb_p else 0.0
            xf01_2 = bool(lhb_p and (lh_cnt >= 2 or lh_ratio >= 0.20))
            xf01_3 = bool(lhb_p and (lh_cnt >= 3 or lh_ratio >= 0.25))
            xf02_daysurf = bool(lhb_p and lhb_p["daysurf_buy"])
            xf03_inst_net = bool(lhb_p and lhb_p["inst_net_sell"] > 0.0)
            xf03_inst_20m = bool(lhb_p and (lhb_p["inst_sell_amt"] > 2e7 or lhb_p["inst_net_sell"] > 2e7))

            # XF04: 此前买过的顶级游资在 t-1 大额净卖出 vs 仍锁仓
            top_yz_exited = False
            if lhb_p and top_yz_bought:
                for nm in top_yz_bought:
                    sa = lhb_p["sell_amt_by_name"].get(nm, 0.0)
                    ba = lhb_p["buy_amt_by_name"].get(nm, 0.0)
                    if sa - ba > 0.0:
                        top_yz_exited = True
                        break
            xf04_exit = bool(top_yz_exited)
            xf04_lock = bool(top_yz_bought and (not top_yz_exited))

            nb_ratio = lhb_p["net_buy_amt_ratio"] if lhb_p else 0.0
            xf05_nb12 = bool(lhb_p and nb_ratio > 0.12)
            xf05_nb15 = bool(lhb_p and nb_ratio > 0.15)
            xf06_quant = bool(lhb_p and lhb_p["qu_two_way"] and lh_cnt >= 1)

            # === Group 2: 持仓期监管与公告 (< dt_k 09:25:00) ===
            d_m10 = str(cb["dts"][max(0, k - 10)])
            d_m7 = str(cb["dts"][max(0, k - 7)])
            idx_dp = dt_to_idx.get(d_prev, -1)
            d_m5_prev = all_dts[max(0, idx_dp - 4)] if idx_dp >= 0 else d_prev

            xf07_sreg_new = _cnt_win(sreg_map.get(c6), buy_cut, end_cut) > 0
            xf07_sreg_10d = _cnt_win(sreg_map.get(c6), f"{d_m10} 00:00:00", end_cut) > 0

            c_clarify = _cnt_win(clarify_map.get(c6), buy_cut, end_cut)
            c_halt = _cnt_win(halt_warn_map.get(c6), buy_cut, end_cut)
            c_red = _cnt_win(reduce_tox_map.get(c6), buy_cut, end_cut)
            xf08_clarify_tox = (c_clarify + c_halt + c_red) > 0
            xf08_strict_tox = (c_clarify + c_red) > 0

            # 交易所近5日监管函 (<= d_prev)
            ev_ex = ex_reg_events[ex_k]
            ex_reg5_cnt = bisect.bisect_right(ev_ex, d_prev) - bisect.bisect_left(ev_ex, d_m5_prev)
            xf09_ex2 = ex_reg5_cnt >= 2
            xf09_ex3 = ex_reg5_cnt >= 3
            ev_ex_full = ex_reg_full[ex_k]
            ex_reg5_full_cnt = bisect.bisect_right(ev_ex_full, d_prev) - bisect.bisect_left(ev_ex_full, d_m5_prev)
            xf09_full2 = ex_reg5_full_cnt >= 2
            xf09_full3 = ex_reg5_full_cnt >= 3

            abn_10d = _cnt_win(abn_notice_map.get(c6), f"{d_m10} 00:00:00", end_cut)
            xf10_abn2 = abn_10d >= 2
            xf10_abn3 = abn_10d >= 3

            xf11_ir_new = _cnt_win(ir_arr_map.get(c6), buy_cut, end_cut) > 0
            xf11_ir_7d = _cnt_win(ir_arr_map.get(c6), f"{d_m7} 00:00:00", end_cut) > 0

            # === Group 3: 社区舆情 (< dt_k 09:25:00) ===
            xq_arr = xq_arr_map.get(c6)
            xq_24h = _cnt_win(xq_arr, f"{d_prev} 09:25:00", end_cut)
            xq_cum = _cnt_win(xq_arr, f"{d1_dt} 00:00:00", end_cut)
            xf12_xq4 = (e["xq_cnt_2d"] < 4) and (xq_24h >= 4)
            xf12_xq8 = (e["xq_cnt_2d"] < 4) and (xq_24h >= 8)
            xf12_xq15 = (e["xq_cnt_2d"] < 4) and (xq_24h >= 15)
            xf12_cum8 = (e["xq_cnt_2d"] < 4) and (xq_cum >= 8)

            gb_t1 = _cnt_win(gb_arr, f"{d_prev} 00:00:00", end_cut)
            gb_base = max(gb_pre3_avg, 2.0)
            xf13_gb3x = (gb_t1 >= 5) and (gb_t1 >= 3.0 * gb_base)
            xf13_gb5x = (gb_t1 >= 8) and (gb_t1 >= 5.0 * gb_base)

            xf14_quiet_24h = xq_24h < 4
            xf14_quiet_cum = xq_cum < 4

            # === Group 4: 09:25 板块与全场竞价 & 宏观生态 ===
            peers = [x for x in kpl_plate_zt.get((d_prev, last_plate), []) if x != c6]
            op_dt = open_lookup.get(dt_k, {})
            peer_ops, peer_yz, peer_dt, peer_ge3, peer_max_st = [], 0, 0, 0, 0
            for px_c in peers:
                info = op_dt.get(px_c)
                if info is not None:
                    po, pyz, pdt, pst = info
                    peer_ops.append(po)
                    peer_yz += int(pyz)
                    peer_dt += int(pdt)
                    peer_ge3 += int(po >= 0.03)
                    peer_max_st = max(peer_max_st, pst)

            mates_avg = float(np.mean(peer_ops)) if peer_ops else 0.0
            xf15_mates15 = (len(peer_ops) > 0 and mates_avg < -0.015) or (peer_dt >= 1)
            xf15_mates25 = (len(peer_ops) > 0 and mates_avg < -0.025) or (peer_dt >= 1)
            xf16_lone = (peer_yz == 0) and (peer_ge3 == 0)

            env_k = mkt_env.get(dt_k, {})
            env_p = mkt_env.get(d_prev, {})
            xf17_zt_neg = float(env_k.get("mkt_zt_open_avg", 0.0)) < 0.0
            xf17_fb_neg = float(env_k.get("mkt_fb_open_avg", 0.0)) < 0.0

            n_zt_p = int(env_p.get("n_zt", 50))
            sr_p = float(env_p.get("seal_rate", 0.55))
            xf18_climax95 = (n_zt_p >= 95) or (sr_p >= 0.80)
            xf18_climax100 = (n_zt_p >= 100) or (sr_p >= 0.80)

            xf19_freeze_12 = float(env_p.get("promo_1to2_ma5", 0.20)) < 0.13
            xf19_freeze_2p = float(env_p.get("promo_2p_ma5", 0.35)) < 0.25

            my_st_p = int(cb["streak"][k - 1])
            xf20_usurp_mkt = int(env_p.get("max_board", 0)) > my_st_p
            xf20_usurp_plate = peer_max_st > my_st_p

            xf21_elo135 = last_elo >= 135.0
            xf21_elo145 = last_elo >= 145.0

            ci_p = bisect.bisect_right(all_csi_dts, d_prev) - 1
            csi_1d = (csi_map[all_csi_dts[ci_p]] / csi_map[all_csi_dts[ci_p - 1]] - 1.0) if ci_p >= 1 else 0.0
            csi_5d = (csi_map[all_csi_dts[ci_p]] / csi_map[all_csi_dts[ci_p - 5]] - 1.0) if ci_p >= 5 else 0.0
            xf22_csi_slump = (csi_1d <= -0.020) or (csi_5d <= -0.025)

            # === Group 5: 断板反包生态与微观封板 ===
            brk_dt_r10 = float(env_p.get("brk_dt_r10", 0.0))
            brk_reb_r10 = float(env_p.get("brk_reb_r10", 0.20))
            xf23_dt_cold = brk_dt_r10 < 0.20       # 高标V5.1原义 brk_r10 < 20%
            xf23_reb_lt15 = brk_reb_r10 < 0.15    # 实际反包率 < 15%
            xf23_reb_lt20 = brk_reb_r10 < 0.20    # 实际反包率 < 20%

            tp_p = tape_ext.get((d_prev, c6))
            if tp_p and bool(cb["is_zt"][k - 1]):
                fst = tp_p["first_seal_time"]
                obc = tp_p["open_board_count"]
                sa_p = tp_p["seal_amount"]
                amt_p = float(cb["amount"][k - 1])
                xf25_late1400 = (fst >= "14:00:00") or (obc >= 3)
                xf25_late1430 = (fst >= "14:30:00") or (obc >= 3)
                xf26_tiny_seal10 = (amt_p > 0) and (sa_p / amt_p < 0.010)
                xf26_tiny_seal05 = (amt_p > 0) and (sa_p / amt_p < 0.005)
            else:
                xf25_late1400 = xf25_late1430 = False
                xf26_tiny_seal10 = xf26_tiny_seal05 = False

            lock10 = _get_lock10(holders_map, c6, d_prev)
            to_p = float(cb["to"][k - 1])
            real_to_p = to_p / max(0.05, 1.0 - lock10 / 100.0)
            xf27_to32 = (to_p > 32.0) or (real_to_p > 65.0)
            xf27_to35 = (to_p > 35.0) or (real_to_p > 65.0)

            to_k = float(cb["to"][k])
            real_to_k = to_k / max(0.05, 1.0 - lock10 / 100.0)
            xf27_k_to35 = (to_k > 35.0) or (real_to_k > 65.0)

            vr_p = float(cb["vol_ratio"][k - 1])
            xf28_blow35 = vr_p > 3.5
            xf28_blow40 = vr_p > 4.0

            # Day k 收盘 K 线形态 (仅供 14:55 断板判断)
            ok_v, hk_v, lk_v, ck_v, pk_v = float(cb["open"][k]), float(cb["high"][k]), float(cb["low"][k]), float(cb["close"][k]), float(cb["pre_c"][k])
            xf29_grave = (hk_v - ck_v) > 2.0 * abs(ck_v - ok_v)
            xf29_long_leg = ((min(ok_v, ck_v) - lk_v) / pk_v >= 0.05) if pk_v > 0 else False

            # XF24: 高标首阴 V5.1 断板打分 (仅用 k-1 已知 LHB + <k 09:25 公告 + k 日 14:55 盘口)
            hd_sc, hd_veto = _compute_hd_score_on_break_day(
                cache, c6, cb, k, d1_dt, lhb_p, lhb_p2,
                xf07_sreg_10d, xf08_strict_tox, ex_reg5_cnt,
                last_plate, last_elo, lock10, xf04_lock
            )

            k_map[k] = {
                # Group 1
                "xf01_2": xf01_2, "xf01_3": xf01_3,
                "xf02": xf02_daysurf,
                "xf03_net": xf03_inst_net, "xf03_20m": xf03_inst_20m,
                "xf04_exit": xf04_exit, "xf04_lock": xf04_lock,
                "xf05_12": xf05_nb12, "xf05_15": xf05_nb15,
                "xf06": xf06_quant,
                # Group 2
                "xf07_new": xf07_sreg_new, "xf07_10d": xf07_sreg_10d,
                "xf08": xf08_clarify_tox, "xf08_strict": xf08_strict_tox,
                "xf09_2": xf09_ex2, "xf09_3": xf09_ex3,
                "xf09_full2": xf09_full2, "xf09_full3": xf09_full3,
                "xf10_2": xf10_abn2, "xf10_3": xf10_abn3,
                "xf11_new": xf11_ir_new, "xf11_7d": xf11_ir_7d,
                # Group 3
                "xf12_4": xf12_xq4, "xf12_8": xf12_xq8, "xf12_15": xf12_xq15, "xf12_cum8": xf12_cum8,
                "xf13_3x": xf13_gb3x, "xf13_5x": xf13_gb5x,
                "xf14_24h": xf14_quiet_24h, "xf14_cum": xf14_quiet_cum,
                # Group 4
                "xf15_15": xf15_mates15, "xf15_25": xf15_mates25,
                "xf16": xf16_lone,
                "xf17_zt": xf17_zt_neg, "xf17_fb": xf17_fb_neg,
                "xf18_95": xf18_climax95, "xf18_100": xf18_climax100,
                "xf19_12": xf19_freeze_12, "xf19_2p": xf19_freeze_2p,
                "xf20_mkt": xf20_usurp_mkt, "xf20_plt": xf20_usurp_plate,
                "xf21_135": xf21_elo135, "xf21_145": xf21_elo145,
                "xf22": xf22_csi_slump,
                # Group 5
                "xf23_dt_cold": xf23_dt_cold, "xf23_reb15": xf23_reb_lt15, "xf23_reb20": xf23_reb_lt20,
                "xf24_sc": hd_sc, "xf24_veto": hd_veto,
                "xf25_1400": xf25_late1400, "xf25_1430": xf25_late1430,
                "xf26_10": xf26_tiny_seal10, "xf26_05": xf26_tiny_seal05,
                "xf27_32": xf27_to32, "xf27_35": xf27_to35, "xf27_k35": xf27_k_to35,
                "xf28_35": xf28_blow35, "xf28_40": xf28_blow40,
                "xf29_grave": xf29_grave, "xf29_leg": xf29_long_leg,
            }
        states_by_idx[e["idx"]] = k_map

    return states_by_idx


def sim_exit_with_rule(entry: dict, cache: dict, k_states: dict, rule_fn) -> tuple:
    """
    通用持仓期跨策略动态卖点仿真器：
    rule_fn(st: dict, ctx: dict) -> dict of actions for day k:
      - d5_strip: bool (D4未封板时，若为True则剥夺D5保留资格，09:25斩)
      - d5_exempt: bool (D4未封板时，若为True则豁免cut_weak)
      - cut_0925: bool (持仓日 k 09:25 直接止盈/止损抢跑)
      - tight_1030vwap: bool (日内10:30未板且破均线走)
      - tight_1345_thr: float | None (e.g. 0.070 或 0.060 替代默认 0.050)
      - tight_1430rush: bool (14:30后炸板抢跑)
      - cond_dev_ratio: float | None (e.g. 0.93 或 0.96)
      - strip_imm: bool (断板日 14:55 剥夺真阳免死直接清仓)
      - grant_imm_override: bool | None (若非None则覆盖默认免死判定)
    """
    c6 = entry["code"]
    pos = entry["pos"]
    cb = cache["code_bars_ext"][c6]
    bars_5m = cache["bars_5m_map"]
    sh_map = cache["sh_map"]
    sz_map = cache["sz_map"]
    n = len(cb["dts"])

    def _run_zt_hold(start_p: int, init_boards: int):
        k = start_p + 1
        imm_used = False
        just_used_imm = False
        boards = init_boards
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

            if k > start_p + 1 and bool(cb["is_yizi_dt"][k - 1]):
                return dt_s, ok, float(cb["adjf"][k]), k - pos, 925, "yizi_dt_open"

            st = k_states.get(k, {})
            ctx = {
                "k": k, "pos": pos, "step": k - pos, "boards": boards,
                "is_d4_unsealed": False, "just_used_imm": just_used_imm, "imm_used": imm_used,
                "o_pct": (ok / pck - 1.0) if pck > 0 else 0.0,
            }
            act = rule_fn(st, ctx) if rule_fn else {}

            # Action 1: 09:25 竞价抢跑
            if act.get("cut_0925") and ok > dtk + 0.005:
                return dt_s, ok, float(cb["adjf"][k]), k - pos, 925, "xf_0925_cut"

            # Action 3: 条件挂高标 93%/96% 双严重异动止盈单
            dev_r = act.get("cond_dev_ratio")
            if dev_r is not None:
                pl_buf, _ = get_double_dev_px_pit(c6, cb, k, sh_map, sz_map, float(dev_r))
                if ok >= pl_buf and ok > dtk + 0.005:
                    return dt_s, ok, float(cb["adjf"][k]), k - pos, 925, "xf_dev_open"
                arr_d = bars_5m.get((c6, dt_s))
                if arr_d is not None and len(arr_d) > 0:
                    for row in arr_d:
                        hh_d, bo_d, bh_d = int(row[0]), float(row[1]), float(row[2])
                        if bh_d <= dtk + 0.005:
                            continue
                        if bh_d >= pl_buf:
                            return dt_s, min(ztk, max(bo_d, pl_buf)), float(cb["adjf"][k]), k - pos, hh_d, "xf_dev_5m"
                elif hk >= pl_buf and hk > dtk + 0.005:
                    return dt_s, min(ztk, pl_buf), float(cb["adjf"][k]), k - pos, 1030, "xf_dev_day"

            # Action 2 & Baseline 5m 盘中护利
            tight_1030 = bool(act.get("tight_1030vwap", False))
            tight_1430 = bool(act.get("tight_1430rush", False))
            drop_thr = float(act.get("tight_1345_thr") or 0.050)

            arr = bars_5m.get((c6, dt_s))
            if arr is not None and len(arr) > 0:
                peak = ok
                cum_v = 0.0
                cum_a = 0.0
                touched_zt_pre1430 = (ok >= ztk - 0.01)
                for bi, row in enumerate(arr):
                    hh = int(row[0])
                    bo, bh, bl, bc = float(row[1]), float(row[2]), float(row[3]), float(row[4])
                    cum_v += float(row[5])
                    cum_a += float(row[6])
                    vwap_now = (cum_a / cum_v) if cum_v > 0 else bc

                    if bh <= dtk + 0.005:
                        continue

                    if tight_1030 and hh == 1030 and bc < ztk - 0.01 and bc < vwap_now:
                        px = float(arr[bi + 1, 1]) if bi + 1 < len(arr) else bc
                        ehh = int(arr[bi + 1, 0]) if bi + 1 < len(arr) else 1030
                        if px > dtk + 0.005:
                            return dt_s, px, float(cb["adjf"][k]), k - pos, ehh, "xf_1030vwap"

                    if tight_1430 and hh >= 1430 and touched_zt_pre1430 and bc < ztk - 0.01 and bi + 1 < len(arr):
                        px = float(arr[bi + 1, 1])
                        if px > dtk + 0.005:
                            return dt_s, px, float(cb["adjf"][k]), k - pos, int(arr[bi + 1, 0]), "xf_1430rush"

                    if hh >= 1345 and peak >= pck * 1.085 and bl <= pck * (1.0 + drop_thr) and bc < ztk - 0.01:
                        return dt_s, float(min(bo, pck * (1.0 + drop_thr))), float(cb["adjf"][k]), k - pos, hh, "c_1345_guard"

                    if bh > peak:
                        peak = bh
                    if bc >= ztk - 0.01 or bh >= ztk - 0.01:
                        touched_zt_pre1430 = True

            if bool(cb["is_zt"][k]):
                boards += 1
                just_used_imm = False
                k += 1
                continue

            # Action 4: 断板日 14:55 免死判定
            base_imm = (not imm_used) and (clk > ok) and (clk >= pck)
            if act.get("grant_imm_override") is not None and (not imm_used):
                imm_ok = bool(act["grant_imm_override"])
            elif act.get("strip_imm", False):
                imm_ok = False
            else:
                imm_ok = base_imm

            if imm_ok:
                imm_used = True
                just_used_imm = True
                k += 1
                continue

            return dt_s, clk, float(cb["adjf"][k]), max(1, k - pos), 1500, "d_eod_close"

        k_end = n - 1
        return cb["dts"][k_end], float(cb["close"][k_end]), float(cb["adjf"][k_end]), max(1, k_end - pos), 1500, "end_data"

    # Branch 1: D4 未封板 -> D5 决策
    if not bool(cb["is_zt"][pos]):
        k = pos + 1
        while k < n and bool(cb["is_yizi_dt"][k]):
            k += 1
        k = min(k, n - 1)
        o4, c4, p4 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])
        o5, p5, c5 = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
        if k > pos + 1:
            return cb["dts"][k], o5, float(cb["adjf"][k]), k - pos, 925, "a_yizi_dt_open"

        st = k_states.get(k, {})
        ctx = {
            "k": k, "pos": pos, "step": 1, "boards": 3,
            "is_d4_unsealed": True, "just_used_imm": False, "imm_used": False,
            "o_pct": (o5 / p5 - 1.0) if p5 > 0 else 0.0,
        }
        act = rule_fn(st, ctx) if rule_fn else {}

        base_keep = (c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005)
        keep_d5 = (base_keep and (not act.get("d5_strip", False)) and (not act.get("cut_0925", False))) or (act.get("d5_exempt", False))
        if not keep_d5:
            return cb["dts"][k], o5, float(cb["adjf"][k]), max(1, k - pos), 925, "a_d5_cut"

        if bool(act.get("tight_1030vwap", False)):
            dtk5 = round(p5 * 0.90, 2)
            ztk5 = float(cb["zt_px"][k])
            arr5 = bars_5m.get((c6, cb["dts"][k]))
            if arr5 is not None and len(arr5) >= 12:
                idx_1030, cv, ca = -1, 0.0, 0.0
                for bi in range(len(arr5)):
                    cv += float(arr5[bi, 5])
                    ca += float(arr5[bi, 6])
                    if int(arr5[bi, 0]) == 1030:
                        idx_1030 = bi
                        break
                if idx_1030 >= 0:
                    bc_1030 = float(arr5[idx_1030, 4])
                    vwap_1030 = ca / cv if cv > 0 else bc_1030
                    if bc_1030 < ztk5 - 0.01 and bc_1030 < vwap_1030:
                        px = float(arr5[idx_1030 + 1, 1]) if idx_1030 + 1 < len(arr5) else bc_1030
                        ehh = int(arr5[idx_1030 + 1, 0]) if idx_1030 + 1 < len(arr5) else 1030
                        if px > dtk5 + 0.005:
                            return cb["dts"][k], px, float(cb["adjf"][k]), max(1, k - pos), ehh, "xf_d5_1030vwap"

        if bool(cb["is_zt"][k]):
            return _run_zt_hold(k, 4)
        return cb["dts"][k], c5, float(cb["adjf"][k]), max(1, k - pos), 1500, "a_d5_eod"

    return _run_zt_hold(pos, 4)


def evaluate_rule(cache: dict, states_by_idx: dict, rule_fn, label: str, thr: float = 90.0) -> dict:
    """全量评估某一动态卖点规则在各窗口的 Raw(EQ) 与 Single-Slot 战绩"""
    code_bars = cache["code_bars_ext"]
    recs = []
    for e in cache["buy_entries"]:
        if (not e["skel"]) or (e["sc_v40"] < thr) or (e["buy_px"] is None):
            continue
        pos = e["pos"]
        cb = code_bars[e["code"]]
        ex_dt, spx, adjs, hb, shh, rsn = sim_exit_with_rule(e, cache, states_by_idx.get(e["idx"], {}), rule_fn)
        nr = (spx * adjs) / (e["buy_px"] * float(cb["adjf"][pos])) * (1.0 - FEE_RATE) - 1.0
        recs.append({
            "idx": e["idx"],
            "code": e["code"],
            "name": e["name"],
            "buy_date": e["buy_date"],
            "buy_hhmm": e["buy_hhmm"],
            "buy_price": round(e["buy_px"], 2),
            "exit_date": ex_dt,
            "exit_hhmm": shh,
            "exit_price": round(spx, 2),
            "hold_bars": hb,
            "net_ret": float(nr),
            "score": int(round(e["sc_v40"])),
            "priority_score": e["priority_score"],
            "open_pct": e["open_pct"],
            "reason": rsn,
        })
    raw_df = pd.DataFrame(recs)
    slot_df = u34.sim_single_slot(raw_df)

    def _win(s_dt: str, e_dt: str) -> dict:
        sr = raw_df[(raw_df["buy_date"] >= s_dt) & (raw_df["buy_date"] <= e_dt)]
        ss = slot_df[(slot_df["buy_date"] >= s_dt) & (slot_df["buy_date"] <= e_dt)]
        rn = int(len(sr))
        if rn > 0:
            rr = sr["net_ret"].to_numpy(dtype=float)
            raw_wr = float((rr > 0).mean() * 100.0)
            raw_mean = float(rr.mean() * 100.0)
            eq_nav = float(np.prod(1.0 + sr.groupby("buy_date")["net_ret"].mean().sort_index().to_numpy()))
        else:
            raw_wr = raw_mean = 0.0
            eq_nav = 1.0

        sn = int(len(ss))
        if sn > 0:
            sr1 = ss["net_ret"].to_numpy(dtype=float)
            wr1 = float((sr1 > 0).mean() * 100.0)
            w1, l1 = sr1[sr1 > 0], sr1[sr1 <= 0]
            plr1 = float(w1.mean() / abs(l1.mean())) if (len(w1) and len(l1) and l1.mean() < 0) else 99.0
            mean1 = float(sr1.mean() * 100.0)
            nav1 = float(np.prod(1.0 + sr1))
            pk, cur, mdd = 1.0, 1.0, 0.0
            for x in sr1:
                cur *= 1.0 + x
                pk = max(pk, cur)
                mdd = max(mdd, (pk - cur) / pk)
            srt = np.sort(sr1)
            t3 = float(np.prod(1.0 + srt[:-3])) if len(srt) > 3 else 1.0
            t5 = float(np.prod(1.0 + srt[:-5])) if len(srt) > 5 else 1.0
        else:
            wr1 = plr1 = mean1 = mdd = 0.0
            nav1 = t3 = t5 = 1.0

        return {
            "raw_n": rn, "raw_wr": round(raw_wr, 2), "raw_mean": round(raw_mean, 2), "eq_nav": round(eq_nav, 4),
            "n_1s": sn, "wr_1s": round(wr1, 2), "plr_1s": round(plr1, 2), "mean_1s": round(mean1, 2),
            "nav_1s": round(nav1, 4), "mdd": round(mdd * 100.0, 2), "t3": round(t3, 4), "t5": round(t5, 4),
        }

    return {
        "label": label,
        "IS": _win("2021-11-15", "2023-12-31"),
        "IS_22": _win("2022-01-01", "2022-12-31"),
        "IS_23": _win("2023-01-01", "2023-12-31"),
        "OOS": _win("2024-01-01", "2026-11-16"),
        "ALL_5Y": _win("2021-11-15", "2026-11-16"),
        "raw_df": raw_df,
        "slot_df": slot_df,
    }
