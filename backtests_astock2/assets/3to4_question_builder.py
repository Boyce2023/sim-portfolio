# -*- coding: utf-8 -*-
"""三进四刷题机题库数据构建器（无偷看时点严格隔离，输出标准JSON）"""
import os, sys, importlib
import pandas as pd
CUR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)
from score_3to4_v31_card import score_single_3to4_row
from bt_3to4_v32_final_build import sim_pool, df, code_bars
from core_3to4_5m_engine import csi300_ret

sel_m = importlib.import_module("assets.3to4_case_selector")
p_v32 = sim_pool("touch65_1130", "cut_weak", "pm1345", True, False)

def _fmt_d(d_str):
    return f"{d_str[:4]}年{d_str[5:7]}月{d_str[8:10]}日"

def _clean_txt(s):
    if not isinstance(s, str): return s
    # 替换负百分比 -X% 为 跌X%
    import re
    s = re.sub(r'-(\d+(\.\d+)?)%', r'跌\1%', s)
    s = s.replace('—', ' ').replace('——', ' ').replace('-', '')
    return s

def build_single_case(idx, q_id):
    r = df.iloc[idx]; row_dict = r.to_dict(); res = score_single_3to4_row(row_dict)
    c6 = str(r["code"]).zfill(6); bd = str(r["buy_date"]); cb = code_bars[c6]
    pos = cb["date_to_pos"][bd]
    op = float(cb["open"][pos]); pc = float(cb["pre_c"][pos])
    trig_px = max(round(pc * 1.065, 2), round(op, 2))
    p_res = p_v32[idx]
    skel = res["passed_skeleton"]; sc = res["score"]
    ans = "挂单" if (skel and sc >= 90) else "空仓"
    is_trig = bool(p_res is not None)
    nr = round(float(p_res["net_ret"]) * 100.0, 2) if is_trig else 0.0
    uret = nr if is_trig else 0.0
    sret = uret if ans == "挂单" else 0.0
    
    # 提取三板日前的20日K线与买入日后K线
    start_k = max(0, pos - 20)
    klines = [[round(float(cb["open"][k]), 2), round(float(cb["high"][k]), 2),
               round(float(cb["low"][k]), 2), round(float(cb["close"][k]), 2)] for k in range(start_k, pos)]
    ex_pos = cb["date_to_pos"].get(p_res["exit_date"], pos + 1) if p_res else pos
    post_k = [[round(float(cb["open"][k]), 2), round(float(cb["high"][k]), 2),
               round(float(cb["low"][k]), 2), round(float(cb["close"][k]), 2)] for k in range(pos, min(len(cb["dts"]), ex_pos + 1))]

    # 轨迹与复盘
    if is_trig:
        bhh = int(p_res["buy_hhmm"]); shh = int(p_res["exit_hhmm"])
        ex_d = p_res["exit_date"]
        c_ret = round(csi300_ret(bd, ex_d) * 100.0, 2)
        p_word = "赚" if nr > 0 else ("亏" if nr < 0 else "平")
        story = f"09:26挂条件单，{bhh//100:02d}:{bhh%100:02d}触及{p_res['buy_price']:.2f}元触发买入；{_fmt_d(ex_d)} {shh//100:02d}:{shh%100:02d}以{p_res['exit_price']:.2f}元卖出，持仓{p_res['hold_bars']}天，扣费后净{p_word}{abs(nr):.2f}%"
        pm = "符合三进四硬骨架且打分达标，顺应主线高确信突破，按纪律执行斩获丰厚利润。" if nr > 0 else "打分过线但次日未能连板，严格执行弱斩强留或分时离场纪律，坚决控制回撤。"
    elif ans == "挂单":
        c_ret = 0.0
        story = "09:26挂突破条件单，上午11:30前盘中未触及突破价，午休撤单空仓防守，净收益平0.00%"
        pm = "虽打分过线，但早盘未向上触及突破点火价，11:30果断撤单，成功规避冲高回落大面。"
    else:
        c_ret = round(float(r.get("csi_1d_prev", 0.0)) * 100.0, 2)
        v_str = "、".join(res["veto_reasons"]) if res["veto_reasons"] else f"打分仅{sc}分未达90分标准"
        story = f"策略裁决空仓防守；未挂单，净收益平0.00%（标的{v_str}，冲动追买极易大亏）"
        pm = f"标的{v_str}，盘中诱多陷阱极重，一律坚决空仓防守。"

    w_map = {0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五"}
    w_str = w_map.get(pd.Timestamp(bd).weekday(), "交易日")
    cal_win = "周一跨周末发酵检验" if bool(r.get("is_post_holiday_or_mon", False)) else ("1月年报预告防守期" if int(bd[5:7]) == 1 else ("5月退潮防守期" if int(bd[5:7]) == 5 else "常规交易日"))

    return {
        "id": q_id, "code": c6, "name": str(r["name"]), "date": bd, "date_fmt": _fmt_d(bd),
        "weekday_str": w_str, "cal_window_str": cal_win, "plate": str(r["plate"]),
        "p_elo": round(float(r["p_elo"]), 1), "px_d3": round(float(r["px_d3"]), 2),
        "prev_to": round(float(r["prev_to"]), 1), "first_seal_time": str(r["first_seal_time"]),
        "open_board_count": int(r["open_board_count"]), "lock_top10": round(float(r["lock_top10"]), 1),
        "real_free_mcap": round(float(r["real_free_mcap"]), 1), "open_pct": round(float(r["open_pct"]) * 100.0, 2),
        "open_px": round(op, 2), "is_top1_3b_open": bool(r["is_top1_3b_open"]), "b3_rival_cnt": int(r["b3_rival_cnt"]),
        "mkt_zt_prev": int(r["mkt_zt_prev"]), "mkt_max_board_prev": int(r["mkt_max_board_prev"]),
        "csi_1d_prev": round(float(r["csi_1d_prev"]) * 100.0, 2), "csi_5d_prev": round(float(r["csi_5d_prev"]) * 100.0, 2),
        "plate_fb_ho_cnt": int(r["plate_fb_ho_cnt"]), "plate_fb_yz_cnt": int(r["plate_fb_yz_cnt"]),
        "plate_peers_open_avg": round(float(r["plate_peers_open_avg"]) * 100.0, 2),
        "lhb_lh_cnt": int(r["lhb_lh_cnt"]), "surf_yz_buy": bool(r["surf_yz_buy"]),
        "has_ex_reg": bool(r["has_ex_reg"]), "trig_px": trig_px, "ans": ans, "score": int(sc),
        "tier": _clean_txt(res["tier"]), "breakdown_str": _clean_txt(res["breakdown_str"]), "is_triggered": is_trig,
        "net_ret": nr, "user_ret": uret, "sys_ret": sret, "exit_story": _clean_txt(story), "csi300_ret": c_ret,
        "postmortem": _clean_txt(pm), "klines": klines, "post_klines": post_k
    }

def build_datasets():
    std_idx, chal_idx = sel_m.select_case_indices()
    std_cases = [build_single_case(idx, i + 1) for i, idx in enumerate(std_idx)]
    chal_cases = [build_single_case(idx, i + 1) for i, idx in enumerate(chal_idx)]
    return std_cases, chal_cases
