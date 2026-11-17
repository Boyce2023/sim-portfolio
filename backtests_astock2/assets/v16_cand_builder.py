# -*- coding: utf-8 -*-
"""
v16_cand_builder.py: 题库候选股对象构建器 (100% 契约对齐)
"""
import re, numpy as np, pandas as pd
from v16_vernacular_review import generate_vernacular_review

def _safe_float(val, default=0.0):
    if val is None or pd.isna(val): return default
    try:
        f = float(val)
        return default if np.isnan(f) else f
    except: return default

def _safe_int(val, default=0):
    return int(_safe_float(val, default))

def build_cand_dict(c, opt, p_idx, sim_res, stk_hist, d1, d2, d3, is_mon, plate_cands_in_win, plate_all_non_yizi, cand_to_sysrank, full_p_cands=None):
    executed = bool(sim_res and sim_res.get("executed", True))
    buy_px = sim_res["buy_price"] if executed else (c.d2_open if c.d2_open >= c.d2_zt_p - 0.005 else c.trig_p)
    sell_px = sim_res["exit_price"] if executed else buy_px
    exit_dt = sim_res["exit_date"] if executed else c.d2_dt
    net_ret = round(sim_res["net_ret"] * 100.0, 2) if executed else 0.0
    sealed = bool(sim_res["sealed_2b"]) if executed else bool(c.d2_is_zt)
    f_height = sim_res["final_height"] if executed else (2 if c.d2_is_zt else 1)

    zt2 = c.d2_zt_p
    rev = generate_vernacular_review(sim_res, c.d2_open, c.d2_high, c.trig_p, zt2, c.d2_is_zt)

    # seal str
    if c.open >= c.zt_price - 0.02 and c.low < c.zt_price - 0.02: seal_str = "T字回封"
    elif c.d1_dip >= -0.005 and c.d1_entity >= 0.065 and c.f_d1_vol_ratio <= 1.9: seal_str = "缩量硬板"
    elif c.f_d1_vol_ratio >= 2.8 or c.d1_dip <= -0.03: seal_str = "放量换手板"
    else: seal_str = "震荡封板"

    csrc_raw = str(getattr(c, "csrc_ind", ""))
    csrc_clean = re.sub(r"^[A-Z]\d+", "", csrc_raw).strip()[:8] or "精选行业"
    r_sh = str(getattr(c, "r_short", "热点主线"))
    r_lg = str(getattr(c, "r_long", ""))
    base_logic = f"{r_sh} · {r_lg}" if (r_lg and r_lg != r_sh and len(r_lg) <= 40) else r_sh

    desc = f"{base_logic} [主业:{csrc_clean}]"
    if getattr(c, "is_outsider_pen", False): desc += " 【硬科技题材配传统主业：扣20分】"
    if getattr(c, "notice_hard", False) or getattr(c, "is_ma", False): desc += " 【盘前合同或并购公告：先验+18分】"
    if getattr(c, "has_ir_pit", False): desc += " 【近8日披露机构调研：+5分】"
    if getattr(c, "is_pioneer_word", False) or getattr(c, "has_new_term", False) or getattr(c, "own_new_term", False): desc += " 【近15日首现细分词：+15分】"
    if getattr(c, "clean_brk60", False): desc += " 【创60日新高首板】"
    if getattr(c, "notice_bad", False): desc += " 【盘前业绩或风险提示公告：扣35分并拦截】"
    blind_desc = desc.replace(c.name, "该司")

    b_cnt = int(c.open_board_count) if (hasattr(c, "open_board_count") and np.isfinite(c.open_board_count)) else -1
    fst = str(getattr(c, "first_seal_time", ""))
    fst_hhmm = fst[:5] if (fst and fst != "99:99:99" and len(fst) >= 5) else "日线封板"
    amt_wan = int(round(_safe_float(getattr(c, "seal_amount", 0.0), 0.0) / 10000.0))
    tight = round(_safe_float(getattr(c, "d1_seal_tightness", 0.0), 0.0), 1)
    is_ht = bool(getattr(c, "is_hard_turnover", False))

    if b_cnt < 0: d1_board_detail = f"{seal_str} · 日线未开板"
    else:
        b_str = "0次炸板" if b_cnt == 0 else ("炸1次(硬换手+5分)" if is_ht else f"炸{b_cnt}次")
        d1_board_detail = f"{fst_hhmm}首封 · {b_str}"

    if amt_wan > 0: d1_seal_detail = f"封单{amt_wan}万 · 紧密度{tight:.0f}分"
    else: d1_seal_detail = f"紧密度{tight:.0f}分 · {seal_str}"
    if tight < 37.0: d1_seal_detail += " (烂板否决)"

    pos20 = int(np.clip(round(_safe_float(getattr(c, "f_pos20_d0", 0.5), 0.5) * 100.0), 0, 100))
    common_ok = c.is_buyable_open and (not c.nuclear_halt) and (not c.promo_freeze)
    in_buy_win = bool(c.is_buyable_open and ((is_mon and (0.020 <= c.d2_o_pct <= 0.088)) or ((not is_mon) and (0.022 <= c.d2_o_pct <= 0.078))))

    p_rk = int(c.true_buy_rk) if in_buy_win else int(c.buyable_plate_rk)
    m_rk = int(c.buyable_mkt_open_rk)
    if in_buy_win: rk_str = f"题材第{p_rk}名 / 全场第{m_rk}名"
    elif c.d2_o_pct > (0.088 if is_mon else 0.078): rk_str = f"高开超窗(原排第{p_rk}) / 全场第{m_rk}名"
    else: rk_str = f"弱开超窗(原排第{p_rk}) / 全场第{m_rk}名"

    if in_buy_win and c.true_buy_rk == 1:
        if len(plate_cands_in_win) >= 2:
            lead = round((c.d2_o_pct - plate_cands_in_win[1].d2_o_pct) * 100.0, 2)
            lead_str = f"领先第2名 +{lead:.2f}%"
        elif len(plate_all_non_yizi) >= 2:
            o_2nd = [x.d2_o_pct for x in plate_all_non_yizi if x.c6 != c.c6][0]
            lead = round((c.d2_o_pct - o_2nd) * 100.0, 2)
            lead_str = f"领先第2名 +{lead:.2f}%"
        else:
            lead = 0.0; lead_str = "板块唯一可买"
    elif in_buy_win and c.true_buy_rk >= 2:
        top1_o = plate_cands_in_win[0].d2_o_pct if plate_cands_in_win else plate_all_non_yizi[0].d2_o_pct
        lead = round((c.d2_o_pct - top1_o) * 100.0, 2)
        lead_str = f"落后头名 {lead:.2f}%"
    else:
        ref_o = plate_cands_in_win[0].d2_o_pct if plate_cands_in_win else plate_all_non_yizi[0].d2_o_pct
        diff = round((c.d2_o_pct - ref_o) * 100.0, 2)
        lead = diff
        lead_str = f"高开超窗 {diff:+.2f}%" if c.d2_o_pct > (0.088 if is_mon else 0.078) else f"弱开落后 {diff:.2f}%"

    do_mon_direct = is_mon and (getattr(c, "sc_v", 0.0) >= 310.0) and (getattr(c, "buy_open_lead", 0.0) >= 0.025)
    trig_str = f"{c.d2_open:.2f}元 ({c.d2_o_pct*100:+.1f}%) · 周一竞价直买" if do_mon_direct else f"{c.trig_p:.2f}元 (+{(c.trig_p / c.close - 1.0)*100:.1f}%) · 挂卖五价"

    # 提取 K 线
    d1_idx = -1
    for idx_s, sr in enumerate(stk_hist):
        if sr.dt_str == d1: d1_idx = idx_s; break
    if d1_idx >= 0:
        klines = [[round(float(k.open), 2), round(float(k.high), 2), round(float(k.low), 2), round(float(k.close), 2), round(float(k.volume), 0)] for k in stk_hist[max(0, d1_idx - 19): d1_idx + 1]]
    else: klines = [[round(c.close, 2)]*4 + [100000.0]]

    stat_pool = full_p_cands if full_p_cands is not None else plate_all_non_yizi
    win_hi_lim = 0.088 if is_mon else 0.078
    ahead_lim = max(win_hi_lim, float(getattr(c, "d2_o_pct", 0.0)))
    yz_peers = [x.name for x in stat_pool if getattr(x, "d2_is_yizi", False) and x.c6 != c.c6]
    over_peers = [x.name for x in stat_pool if (not getattr(x, "d2_is_yizi", False)) and (x.d2_o_pct > ahead_lim) and x.c6 != c.c6]
    front_yz_cnt = len(yz_peers)
    front_ov_cnt = len(over_peers)

    return {
        "opt": opt, "code": f"{c.c6}.SH" if c.c6.startswith("60") else f"{c.c6}.SZ", "name": c.name, "theme": c.plate,
        "desc": desc, "blind_desc": blind_desc, "mcap": round(_safe_float(getattr(c, "mcap", 0.0)), 1), "d1_turn": round(_safe_float(getattr(c, "to", 0.0)), 2),
        "d1_amt": round(_safe_float(getattr(c, "amount", 0.0)) / 1e8, 2), "vr": f"{_safe_float(getattr(c, 'f_d1_vol_ratio', 1.0), 1.0):.2f}倍", "seal": seal_str,
        "dd20": round((_safe_float(getattr(c, "f_dd20_d0", 1.0), 1.0) - 1.0) * 100.0, 1), "zt20": _safe_int(getattr(c, "f_zt_cnt_pre20", 0)), "pre_d1": round(_safe_float(getattr(c, "f_d0_pct", 0.0)) * 100.0, 2),
        "o_pct": round(_safe_float(getattr(c, "d2_o_pct", 0.0)) * 100.0, 2), "close_d1": round(_safe_float(getattr(c, "close", 0.0)), 2), "csrc_ind": csrc_clean,
        "front_yizi_cnt": front_yz_cnt, "front_over_cnt": front_ov_cnt, "front_lock_cnt": front_yz_cnt + front_ov_cnt, "front_yizi_names": yz_peers,
        "is_outsider_pen": bool(getattr(c, "is_outsider_pen", False)), "blast_count": b_cnt, "first_seal_hhmm": fst_hhmm,
        "seal_amt_wan": amt_wan, "tightness": tight, "is_hard_turnover": is_ht, "d1_board_detail": d1_board_detail,
        "d1_seal_detail": d1_seal_detail, "pos20_pct": pos20, "in_buy_window": in_buy_win, "rk": [p_rk, m_rk],
        "rk_detail_str": rk_str, "lead": lead, "lead_detail_str": lead_str, "trig_str": trig_str,
        "v16_tot_score": round(float(getattr(c, "sc_v", 0.0)), 1), "buy_price": round(float(buy_px), 2),
        "sell_price": round(float(sell_px), 2), "exit_date": exit_dt, "exit_reason": rev["exit_reason"],
        "net_ret": net_ret, "executed": executed, "is_sealed": sealed, "final_height": f_height,
        "sys_rank": cand_to_sysrank[c.c6], "sys_pass": bool(getattr(c, "v16_tot", False)),
        "gate_ok": bool(c.gate_ok), "pm_comment": rev["pm_comment"], "klines": klines,
        "d2": d2, "d3": d3, "theme_idx": p_idx
    }
