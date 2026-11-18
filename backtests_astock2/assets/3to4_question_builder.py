# -*- coding: utf-8 -*-
"""三进四 V4.0 刷题机题库数据构建器（无偷看时点严格隔离，输出标准JSON）"""
import os
import re
import sys
import importlib
import pandas as pd

CUR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in (CUR_DIR, ASSETS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from score_3to4_v31_card import score_single_3to4_row
loader_m = importlib.import_module("3to4_v40_loader")
sel_m = importlib.import_module("3to4_case_selector")


def _fmt_d(d_str):
    return f"{d_str[:4]}年{d_str[5:7]}月{d_str[8:10]}日"


def _fmt_signed(v: float) -> str:
    if abs(v) < 0.005:
        return "0.00%"
    return f"{v:+.2f}%"


def _clean_txt(s):
    if not isinstance(s, str):
        return s
    return s.replace("——", " ").replace("—", " ")
    s = re.sub(r"-(\d+(\.\d+)?)%", r"跌\1%", s)
    s = s.replace("—", " ").replace("——", " ").replace("-", "")
    return s


def build_single_case(idx, q_id):
    bundle = loader_m.get_v40_bundle()
    df = bundle["cand_df"]
    code_bars = bundle["code_bars"]
    p_1030 = bundle["p_1030"]

    r = df.iloc[idx]
    row_dict = r.to_dict()
    res = score_single_3to4_row(row_dict)
    c6 = str(r["code"]).zfill(6)
    bd = str(r["buy_date"])
    cb = code_bars[c6]
    pos = cb["date_to_pos"][bd]
    op = float(cb["open"][pos])
    pc = float(cb["pre_c"][pos])
    trig_px = max(round(pc * 1.065, 2), round(op, 2))
    p_res = p_1030[idx]
    skel = res["passed_skeleton"]
    sc = res["score"]
    ans = "挂单" if (skel and sc >= 90) else "空仓"
    is_trig = bool(p_res is not None)
    nr = round(float(p_res["net_ret"]) * 100.0, 2) if is_trig else 0.0
    uret = nr if is_trig else 0.0
    sret = uret if ans == "挂单" else 0.0

    start_k = max(0, pos - 20)
    klines = [
        [round(float(cb["open"][k]), 2), round(float(cb["high"][k]), 2),
         round(float(cb["low"][k]), 2), round(float(cb["close"][k]), 2)]
        for k in range(start_k, pos)
    ]
    ex_pos = cb["date_to_pos"].get(p_res["exit_date"], pos + 1) if p_res else pos
    post_k = [
        [round(float(cb["open"][k]), 2), round(float(cb["high"][k]), 2),
         round(float(cb["low"][k]), 2), round(float(cb["close"][k]), 2)]
        for k in range(pos, min(len(cb["dts"]), ex_pos + 1))
    ]

    # 轨迹与复盘
    if is_trig and ans == "挂单":
        bhh = int(p_res["buy_hhmm"])
        shh = int(p_res["exit_hhmm"])
        ex_d = p_res["exit_date"]
        c_ret = round(loader_m.csi300_ret_v40(bd, ex_d) * 100.0, 2)
        story = (
            f"09:26挂条件单，{bhh//100:02d}:{bhh%100:02d}触及{p_res['buy_price']:.2f}元触发买入；"
            f"{_fmt_d(ex_d)} {shh//100:02d}:{shh%100:02d}以{p_res['exit_price']:.2f}元卖出，"
            f"持仓{p_res['hold_bars']}天，扣费净收益 {_fmt_signed(nr)}"
        )
        pm = (
            "符合三进四 V4.0 硬骨架且打分过线，盘中突破触发买入并按规则止盈离场。"
            if nr > 0 else
            "打分过线但次日未能连板，严格执行弱斩强留或分时离场纪律，坚决控制回撤。"
        )
    elif ans == "挂单":
        c_ret = 0.0
        story = "09:26挂突破条件单，上午10:30前盘中未触及突破价，10:30撤单空仓防守，净收益 0.00%"
        pm = "虽打分过线，但10:30前未向上触及突破点火价，按 V4.0 撤单窗红线果断撤单，成功规避盘中诱多反抽与冲高回落大面。"
    else:
        c_ret = round(float(r.get("csi_1d_prev", 0.0)) * 100.0, 2)
        v_str = "、".join(res["veto_reasons"]) if res["veto_reasons"] else f"打分仅{sc}分未达90分标准"
        if is_trig:
            extra_sim = f"；若强行挂单且于{int(p_res['buy_hhmm'])//100:02d}:{int(p_res['buy_hhmm'])%100:02d}触及{p_res['buy_price']:.2f}元成交，按纪律卖出净收益 {_fmt_signed(nr)}"
        else:
            extra_sim = ""
        story = f"策略裁决空仓防守；未挂单，定式净收益 0.00%（标的{v_str}{extra_sim}）"
        pm = f"标的{v_str}，盘中诱多陷阱极重，一律坚决空仓防守。"

    w_map = {0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五"}
    w_str = w_map.get(pd.Timestamp(bd).weekday(), "交易日")
    cal_win = "1月年报预告防守期" if int(bd[5:7]) == 1 else ("5月退潮防守期" if int(bd[5:7]) == 5 else "常规交易窗")

    return {
        "id": q_id, "code": c6, "name": str(r["name"]), "date": bd, "date_fmt": _fmt_d(bd),
        "weekday_str": w_str, "cal_window_str": cal_win, "plate": str(r["plate"]),
        "p_elo": round(float(r["p_elo"]), 1), "px_d3": round(float(r["px_d3"]), 2),
        "prev_to": round(float(r["prev_to"]), 1), "first_seal_time": str(r["first_seal_time"]),
        "open_board_count": int(r["open_board_count"]), "lock_top10": round(float(r["lock_top10"]), 1),
        "real_free_mcap": round(float(r["real_free_mcap"]), 1), "open_pct": round(float(r["open_pct"]) * 100.0, 2),
        "open_px": round(op, 2), "is_top1_3b_open": bool(r["is_top1_3b_open"]), "b3_rival_cnt": int(r["b3_rival_cnt"]),
        "mkt_zt_prev": int(r["mkt_zt_prev"]), "mkt_max_board_prev": int(r["mkt_max_board_prev"]),
        "prev_3b_dt_cnt": int(r.get("prev_3b_dt_cnt", 0)),
        "pos20_pct": int(round(float(r.get("pos20_d0", 0.5)) * 100.0)),
        "pre_xq_posts": int(r.get("xq_cnt_2d", 0) or 0),
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
