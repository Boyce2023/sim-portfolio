# -*- coding: utf-8 -*-
"""
live_daily_tiers_scorer.py
09:25 实时竞价融合评分器（全战区字段与涨跌数值100%标准化对齐一进二规范）：
1) 置顶关注池（紧凑单行 + 换手上限 = 100% - 十大锁仓%）
2) 战区二：二进三 V2.0（题材战场分卡 + 标准11列透视表 + 拍板复盘卡）
3) 战区三：三进四 V4.0（全市场全部三连板全给 + 标准11列透视表 + 拍板复盘卡）
4) 战区四：唯一高标（严格只给全场第1名最高标 + 标准11列透视表 + 二选一拍板复盘卡）
"""
import os
import re
import sys
import random
from collections import defaultdict
import numpy as np

ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
BACKTESTS_DIR = os.path.dirname(ASSETS_DIR)
SCRIPTS_DIR = os.path.join(os.path.dirname(BACKTESTS_DIR), "scripts")
for _p in (BACKTESTS_DIR, ASSETS_DIR, SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ths_watchlist_sync import load_and_sync_watchlist
from live_daily_watchlist_builder import load_stock_static_profiles
from score_3to4_v31_card import score_single_3to4_row
from fast_2to3_today import evaluate_2to3_candidate


def fmt_pct_zh(val: float) -> str:
    if val > 0.005:
        return f"+{val:.2f}%"
    if val < -0.005:
        return f"-{abs(val):.2f}%"
    return "0.00%"


def _clean_zh(s: str) -> str:
    txt = re.sub(r"\b[PU]\d(?:_\d)?_?", "", str(s)).replace("[-6.5%,+2.5%]", "-6.5%至+2.5%").replace("[-6.5%, +2.5%]", "-6.5%至+2.5%").replace("—", " ").replace("——", " ")
    return txt


def _full_code(c6: str) -> str:
    return f"{c6}.SH" if c6.startswith("6") else f"{c6}.SZ"


def assemble_extra_live_sections(extra_static: dict, live_quotes: dict | None, live_stage: str) -> dict:
    d1_date = extra_static["d1_date"]
    profiles = dict(extra_static.get("profiles", {}))
    wl_state, _ = load_and_sync_watchlist()
    wl_codes = wl_state["codes"]
    ths_now = set(wl_state.get("ths_pinned_now", []))
    missing = [c for c in wl_codes if c not in profiles]
    if missing:
        profiles.update(load_stock_static_profiles(missing, d1_date))

    quotes = live_quotes or {}
    is_auc = (live_stage != "premarket")
    opts = "ABCDEFGHIJKL"

    # 1. 置顶关注池（紧凑扁平标准化）
    wl_rows = []
    for c6 in wl_codes:
        pf, q = profiles.get(c6, {}), quotes.get(c6, {})
        pre_c = float(q.get("pre") or pf.get("d1_close") or 0.0)
        op_px = float(q.get("open") or 0.0) if is_auc else 0.0
        cur_px = float(q.get("cur") or op_px or pre_c)
        tmcap = round(float(q.get("tmcap") or pf.get("tmcap_d1") or pf.get("fmcap_d1") or 0.0), 1)
        fmcap = round(float(q.get("fmcap") or pf.get("fmcap_d1") or tmcap), 1)
        lk = float(pf.get("lock_pct", 35.0))
        rfmcap = round(fmcap * max(0.05, 1.0 - lk / 100.0), 1)
        to_cap = round(max(5.0, 100.0 - lk), 1)
        d1_nom = float(pf.get("d1_nom_to", 10.0))

        kl_20 = list(pf.get("klines_20d", []))
        if is_auc and op_px > 0 and pre_c > 0:
            auc_pct = round((op_px / pre_c - 1.0) * 100.0, 2)
            cur_pct = round((cur_px / pre_c - 1.0) * 100.0, 2)
            auc_s = f"{op_px:.2f}元 ({fmt_pct_zh(auc_pct)})"
            cur_s = f"现 {cur_px:.2f} ({fmt_pct_zh(cur_pct)})"
            kl_draw = kl_20 + [[round(op_px, 2), round(max(float(q.get("high") or op_px), op_px, cur_px), 2), round(min(float(q.get("low") or op_px), op_px, cur_px), 2), round(cur_px, 2), 0.2]]
            h20_live = max(float(pf.get("h20", pre_c)), op_px)
            dd_v = round(max(0.0, (1.0 - op_px / max(h20_live, 0.01)) * 100.0), 1)
            dd_s = f"回撤 {dd_v:.1f}%" if dd_v > 0.05 else "创20日新高"
        else:
            auc_pct, cur_pct = None, None
            auc_s, cur_s, kl_draw = f"待09:25 (昨{pre_c:.2f})", "", kl_20
            dd_d1 = float(pf.get("dd_d1", 0.0))
            dd_s = f"回撤 {dd_d1:.1f}%" if dd_d1 > 0.05 else "创20日新高"

        ret20 = float(pf.get("ret_20d", 0.0))
        wl_rows.append({
            "code": _full_code(c6), "c6": c6, "name": q.get("name") or pf.get("name") or c6, "in_ths": bool(c6 in ths_now),
            "mcap_s": f"流{fmcap:.0f}亿 / 真流{rfmcap:.0f}亿 (总{tmcap:.0f}亿)",
            "theme": _clean_zh(pf.get("theme", "轮动")), "board_s": _clean_zh(pf.get("board_str", "")),
            "to_cap_s": f"{to_cap:.1f}%", "to_sub_s": f"锁{lk:.0f}% · 昨{d1_nom:.1f}%", "near_cap": bool(d1_nom >= to_cap * 0.65),
            "klines": kl_draw, "ret20_num": ret20, "trend_s": f"{fmt_pct_zh(ret20)} · {pf.get('trend_tag', '')}",
            "auc_pct_num": auc_pct, "auc_s": auc_s, "cur_pct_num": cur_pct, "cur_s": cur_s,
            "dd_s": dd_s, "max_dd_s": f"最大{pf.get('max_dd_20d', 0.0):.0f}%",
        })

    # 2. 二进三战区（与一进二完全同款题材分卡 + 标准化11列候选股）
    c23_raw = extra_static.get("c23_obj", {}).get("candidates", [])
    heat_map = extra_static.get("heat_2to3", {})
    by_plate = defaultdict(list)
    all_23 = []
    for c in c23_raw:
        c6 = c["code"]
        pf, q = profiles.get(c6, {}), quotes.get(c6, {})
        pre_c = float(c.get("prev_close") or q.get("pre") or pf.get("d1_close") or 0.0)
        op_px = float(q.get("open") or 0.0) if is_auc else round(pre_c * 0.99, 2)
        op_pct = (op_px / pre_c - 1.0) if (is_auc and op_px > 0 and pre_c > 0) else -0.01
        buyable = bool((not q.get("is_yizi", False)) and op_pct < 0.098) if is_auc else True
        ev = evaluate_2to3_candidate(c, op_pct, buyable)
        p_name = c.get("plate") if (c.get("plate") and c.get("plate") != "其他") else "独立暗牌组"
        rec = (c, pf, q, pre_c, op_px, op_pct, buyable, ev, p_name)
        by_plate[p_name].append(rec)
        all_23.append(rec)

    rk_sorted_23 = sorted(all_23, key=lambda x: (-int(x[7]["passed_std90"]), -x[7]["score"]))
    sys_rk_23 = {x[0]["code"]: i + 1 for i, x in enumerate(rk_sorted_23)}
    plate_keys = list(by_plate.keys())
    random.Random(f"astock2_23th_{d1_date}").shuffle(plate_keys)
    themes_23 = []
    for t_idx, p_name in enumerate(plate_keys):
        recs = list(by_plate[p_name])
        random.Random(f"astock2_23cd_{d1_date}_{p_name}").shuffle(recs)
        s0 = recs[0][0]
        psz, prk, elo = int(s0.get("plate_sz", 0)), int(s0.get("plate_rk_noev", 99)), round(float(s0.get("d2_s_elo", 100.0)), 1)
        p3b = max(int(x[0].get("plate_3b_cnt_sd", 0)) for x in recs)
        if p_name == "独立暗牌组": st_tag = "无热题材拥挤 · 个股暗牌博弈"
        elif any(x[0].get("d1_is_dying_pulse") for x in recs): st_tag = "退潮脉冲警示"
        elif any(x[0].get("d2_own_new_term") for x in recs): st_tag = "细分新词破冰"
        elif elo <= 95.0 or s0.get("a22_elo_ice_lt95"): st_tag = "题材极寒冰点破冰"
        elif psz >= 7 and prk <= 2: st_tag = "前排热门拥挤"
        elif s0.get("c21_w2_reb_20d_ge6") or s0.get("c22_w2_reb_30d_ge6"): st_tag = "老主线分化回流"
        else: st_tag = "板块温热分歧适中"
        avg_op = round(float(np.mean([x[5] * 100.0 for x in recs])), 2) if is_auc else None
        t_cands = []
        for ci, (c, pf, q, pre_c, op_px, op_pct, buyable, ev, _) in enumerate(recs):
            c6 = c["code"]
            lk = float(c.get("lock_top10") or pf.get("lock_pct") or 35.0)
            to_cap = round(max(5.0, 100.0 - lk), 1)
            fmcap = round(float(q.get("fmcap") or pf.get("fmcap_d1") or 25.0), 1)
            veto_txt = "；".join(_clean_zh(v) for v in ev["veto_reasons"])
            bd_txt = _clean_zh(ev["breakdown_str"])
            o_num = round(op_pct * 100.0, 2) if is_auc else None
            v2_tags = []
            if c.get("is_pure_outsider_causal"): v2_tags.append("跨界硬科技")
            if c.get("d2_own_new_term"): v2_tags.append("15日新词")
            if c.get("d1_is_yizi"): v2_tags.append("首板一字")
            if c.get("d1_is_dying_pulse"): v2_tags.append("退潮脉冲")
            v2_suffix = f" · {'/'.join(v2_tags)}" if v2_tags else ""
            t_cands.append({
                "opt": opts[ci], "code": _full_code(c6), "c6": c6, "name": c.get("name") or q.get("name") or c6,
                "sys_rank": sys_rk_23[c6], "theme_desc": f"{_clean_zh(pf.get('theme', p_name))} · {c.get('ths_tag', '2连板')}{v2_suffix}",
                "mcap_main": f"{fmcap:.1f} 亿", "mcap_sub": f"昨收 {pre_c:.2f}元 · 锁仓 {lk:.0f}%",
                "to_main": f"上限 {to_cap:.1f}%", "to_sub": f"昨换手 {pf.get('d1_nom_to', 10.0):.1f}%",
                "tape_main": f"二板开板 {int(c.get('d2_open_cnt_tape') or 0)} 次", "tape_sub": f"雪球热帖 {int(c.get('xq_cnt_tot') or 0)} 条",
                "dd_main": f"回撤 {pf.get('dd_d1', 0.0):.1f}% · 位置 {int(round(float(c.get('pos_20d_d0') if c.get('pos_20d_d0') is not None else 0.5)*100))}%",
                "dd_sub": f"20日最大回撤 {pf.get('max_dd_20d', 0.0):.0f}%",
                "o_pct_num": o_num, "auc_s": (f"{fmt_pct_zh(o_num)}" + (" (一字)" if not buyable else "") if is_auc else "待09:25"),
                "auc_sub": f"开盘 {op_px:.2f}元" if is_auc else "待竞价生成",
                "peer_main": f"同板三板以上 {p3b} 只", "peer_sub": "买窗 -6.5%至+2.5%",
                "trig_s": f"{op_px:.2f}元 · 09:25竞价直买" if (is_auc and buyable) else ("一字封死无买点" if is_auc else f"绿开预评 {c.get('pre_score_green', 60)}分"),
                "score": int(ev["score"]), "score_disp": f"{int(ev['score'])} 分",
                "passed": bool(ev["passed_std90"]) if is_auc else False, "passed_s96": bool(ev["passed_strict96"]) if is_auc else False,
                "why": (f"否决：{veto_txt} | {bd_txt}" if veto_txt else f"门禁全过 | {bd_txt}"),
                "klines": list(pf.get("klines_20d", [])),
                "d2_bar": [round(op_px, 2), round(op_px, 2), round(op_px, 2), round(op_px, 2), 0.2] if (is_auc and op_px > 0) else None,
            })
        themes_23.append({
            "idx": t_idx, "name": p_name,
            "elo_badge": "量化题材分：独立暗牌池" if p_name == "独立暗牌组" else f"量化题材分：第 {prk} 名 ({elo}分)",
            "p_sz": psz, "p3b_str": f"{p3b} 只", "stage_str": st_tag,
            "avg_open_num": avg_op, "avg_open_str": fmt_pct_zh(avg_op) if is_auc else "待09:25竞价",
            "heat_bars": heat_map.get(p_name, [1] * 10), "cands": t_cands,
        })

    win23 = sorted([x for t in themes_23 for x in t["cands"] if x["passed"]], key=lambda x: -x["score"])
    if not is_auc: v23_c6, v23_txt = "", "待 09:25 竞价生成二进三裁决"
    elif win23:
        w = win23[0]
        v23_c6 = w["c6"]
        v23_txt = f"{'★满96分高胜率单独提醒' if w['passed_s96'] else '标准满90分过线'}：{w['name']}（{w['c6']} · V2.0总分 {w['score']}分 >= 90分 · {w['trig_s']}）"
    else:
        top_any = rk_sorted_23[0] if rk_sorted_23 else None
        v23_c6 = ""
        v23_txt = f"今日量化空仓休息（全场最高分 {top_any[0]['name']} {top_any[7]['score']}分，未同时满足纯2连板买窗与90分门槛）" if top_any else "今日量化空仓休息"

    # 3. 三进四战区（全市场全部三连板全量给出 + 标准化11列）
    c34_obj = extra_static.get("c34_obj", {})
    env34 = c34_obj.get("env", {})
    c34_tmp = []
    for c in c34_obj.get("candidates", []):
        c6, q = c["code"], quotes.get(c["code"], {})
        pre_c = float(c.get("px_d3") or q.get("pre") or 0.0)
        op_px = float(q.get("open") or 0.0) if is_auc else round(pre_c * 1.055, 2)
        op_pct = (op_px / pre_c - 1.0) if (is_auc and op_px > 0 and pre_c > 0) else 0.055
        buyable = not bool(op_pct >= 0.098 or (is_auc and q.get("is_yizi", False)))
        c34_tmp.append((c, q, pre_c, op_px, op_pct, buyable))
    random.Random(f"astock2_34_{d1_date}").shuffle(c34_tmp)
    max_op34 = max([x[4] for x in c34_tmp if x[5]], default=-9.9)
    c34_evals = []
    for c, q, pre_c, op_px, op_pct, buyable in c34_tmp:
        fb_ho, fb_yz, p_ops = 0, 0, []
        for s6 in c.get("plate_fb_codes", []):
            sq = quotes.get(s6, {})
            so = (float(sq["open"]) / float(sq["pre"]) - 1.0) if (is_auc and sq.get("open", 0) > 0 and sq.get("pre", 0) > 0) else 0.015
            if so >= 0.098: fb_yz += 1
            elif so >= 0.03: fb_ho += 1
        for z6 in c.get("plate_zt_codes", []):
            zq = quotes.get(z6, {})
            if is_auc and zq.get("open", 0) > 0 and zq.get("pre", 0) > 0:
                p_ops.append(float(zq["open"]) / float(zq["pre"]) - 1.0)
        row = dict(c, open_pct=op_pct, buyable_open=buyable, is_top1_3b_open=bool(buyable and op_pct >= max_op34 - 1e-5),
                   plate_fb_ho_cnt=fb_ho, plate_fb_yz_cnt=fb_yz, plate_peers_open_avg=(float(np.mean(p_ops)) if p_ops else 0.01),
                   prev_3b_dt_cnt=env34.get("prev_3b_dt_cnt", 0), csi_1d_prev=env34.get("csi_1d_prev", 0.0),
                   csi_5d_prev=env34.get("csi_5d_prev", 0.0), mkt_zt_prev=env34.get("mkt_zt_prev", 50))
        c34_evals.append((c, q, pre_c, op_px, op_pct, buyable, fb_ho, fb_yz, score_single_3to4_row(row)))

    rk34_map = {x[0]["code"]: i + 1 for i, x in enumerate(sorted(c34_evals, key=lambda z: -int(z[8]["score"])))}
    c34_cards = []
    for idx, (c, q, pre_c, op_px, op_pct, buyable, fb_ho, fb_yz, sc_res) in enumerate(c34_evals):
        c6, pf = c["code"], profiles.get(c["code"], {})
        sc_v = int(sc_res["score"])
        lk = float(c.get("lock_top10", pf.get("lock_pct", 35.0)))
        to_cap = round(max(5.0, 100.0 - lk), 1)
        fmcap = round(float(q.get("fmcap") or pf.get("fmcap_d1") or 30.0), 1)
        trig = max(round(pre_c * 1.065, 2), round(op_px, 2))
        o_num = round(op_pct * 100.0, 2) if is_auc else None
        c34_cards.append({
            "opt": opts[idx], "code": _full_code(c6), "c6": c6, "name": c.get("name") or q.get("name") or c6,
            "sys_rank": rk34_map[c6], "theme_desc": f"{_clean_zh(c.get('plate') or pf.get('theme', ''))} · {_clean_zh(pf.get('board_str', '3连板'))}",
            "mcap_main": f"{fmcap:.1f} 亿", "mcap_sub": f"真流 {float(c.get('real_free_mcap', 20.0)):.1f}亿 · 锁仓 {lk:.0f}%",
            "to_main": f"上限 {to_cap:.1f}%", "to_sub": f"昨换手 {float(c.get('prev_to', 10.0)):.1f}%",
            "tape_main": f"{str(c.get('first_seal_time', '09:35'))[:5]} 首封 · 开板 {int(c.get('open_board_count', 0))} 次", "tape_sub": f"雪球热帖 {int(c.get('xq_cnt_2d', 0) or 0)} 条",
            "dd_main": f"回撤 {pf.get('dd_d1', 0.0):.1f}% · 位置 {int(round(float(c.get('pos20_d0', 0.5))*100))}%", "dd_sub": f"20日最大回撤 {pf.get('max_dd_20d', 0.0):.0f}%",
            "o_pct_num": o_num, "auc_s": (f"{fmt_pct_zh(o_num)}" + (" (一字)" if not buyable else "") if is_auc else "待09:25"),
            "auc_sub": f"开盘 {op_px:.2f}元" if is_auc else f"昨收 {pre_c:.2f}元",
            "peer_main": f"首板高开助攻 {fb_ho} 只" if is_auc else "待竞价统计", "peer_sub": f"同板一字 {fb_yz} 只" if is_auc else "买窗 +3.0%至+9.2%",
            "trig_s": f"{trig:.2f}元 · 10:30前条件单" if buyable else "一字封死无买点",
            "score_disp": f"{sc_v} 分" if sc_v > 0 else "未过前置门",
            "passed": bool(sc_v >= 90 and sc_res["passed_skeleton"] and buyable) if is_auc else False,
            "why": _clean_zh(sc_res.get("breakdown_str", "")),
            "klines": list(pf.get("klines_20d", [])),
            "d2_bar": [round(op_px, 2), round(op_px, 2), round(op_px, 2), round(op_px, 2), 0.2] if (is_auc and op_px > 0) else None,
        })
    w34 = [x for x in c34_cards if x["passed"]]
    v34_c6 = w34[0]["c6"] if w34 else ""
    if not is_auc and c34_cards:
        v34_txt = f"待 09:25 竞价生成三进四裁决（候选：{c34_cards[0]['name']}，预估静态 {c34_cards[0]['score_disp']}）"
    else:
        v34_txt = f"主力过线：{w34[0]['name']}（{w34[0]['c6']} · V4.0总分 {w34[0]['score_disp']} >= 90分 · {w34[0]['trig_s']}）" if w34 else "今日量化空仓休息（全市场三连板候选均未同时满足非一字可买与满90分门槛）"

    # 4. 唯一高标战区（严格只给全场唯一第 1 名最高标）
    hi_cards = []
    ch51_cands = sorted(extra_static.get("ch51_obj", {}).get("candidates", []), key=lambda x: (-int(not x.get("is_vetoed")), -int(x.get("static_score", 0))))
    c45_cands = sorted(extra_static.get("c45_obj", {}).get("candidates", []), key=lambda x: -int(x.get("static_score", 0)))
    hi5_top1 = extra_static.get("hi5_top1")

    if ch51_cands:
        c = ch51_cands[0]
        c6, pf, q = c["code"], profiles.get(c["code"], {}), quotes.get(c["code"], {})
        pre_c = float(c.get("close_d1") or pf.get("d1_close") or 0.0)
        op_px = float(q.get("open") or 0.0) if is_auc else 0.0
        op_pct = (op_px / pre_c - 1.0) if (is_auc and op_px > 0 and pre_c > 0) else 0.0
        o_num = round(op_pct * 100.0, 2) if is_auc else None
        tot_sc = int(c.get("static_score", 60)) + ((8 if op_pct < 0 else (6 if op_pct <= 0.025 else 0)) if is_auc else 0)
        ok_hi = bool(is_auc and (not c.get("is_vetoed")) and (-0.065 <= op_pct <= 0.045) and tot_sc >= 88 and not q.get("is_yizi", False))
        lk = float(c.get("lock_pct", pf.get("lock_pct", 35.0)))
        to_cap = round(max(5.0, 100.0 - lk), 1)
        v_rsn = "；".join(_clean_zh(v) for v in c.get("veto_reasons", []))
        hi_cards.append({
            "opt": "A", "code": _full_code(c6), "c6": c6, "name": c.get("name") or q.get("name") or c6, "sys_rank": 1,
            "theme_desc": f"{_clean_zh(pf.get('theme', '高标总龙'))} · 前{c.get('streak_d0', 4)}连板首阴第1名",
            "mcap_main": f"{float(c.get('fmcap', 30.0)):.1f} 亿", "mcap_sub": f"昨收 {pre_c:.2f}元 · 锁仓 {lk:.0f}%",
            "to_main": f"上限 {to_cap:.1f}%", "to_sub": f"昨换手 {float(c.get('turnover_d1', 15.0)):.1f}%",
            "tape_main": "首阴真阳反包池", "tape_sub": f"静态底分 {c.get('static_score', 60)} 分",
            "dd_main": f"回撤 {pf.get('dd_d1', 0.0):.1f}%", "dd_sub": f"20日最大回撤 {pf.get('max_dd_20d', 0.0):.0f}%",
            "o_pct_num": o_num, "auc_s": fmt_pct_zh(o_num) if is_auc else "待09:25", "auc_sub": f"开盘 {op_px:.2f}元" if is_auc else "待竞价",
            "peer_main": "全场唯一第1高标", "peer_sub": "买窗 -6.5%至+4.5%",
            "trig_s": (f"{op_px:.2f}元 · 09:25竞价直买" if op_pct >= 0 else f"{round(op_px*1.015,2):.2f}元 · 11:30前条件单") if is_auc else "待09:25定",
            "score_disp": f"V5.1 {tot_sc} 分", "passed": ok_hi,
            "why": f"高标首阴V5.1总分 {tot_sc}分(门槛88分)" + (f" · 否决：{v_rsn}" if v_rsn else " · 满足真阳承接"),
            "klines": list(pf.get("klines_20d", [])),
            "d2_bar": [round(op_px, 2), round(op_px, 2), round(op_px, 2), round(op_px, 2), 0.2] if (is_auc and op_px > 0) else None,
        })
    elif hi5_top1 or c45_cands:
        c6 = hi5_top1["code"] if hi5_top1 else c45_cands[0]["code"]
        c4 = c45_cands[0] if (not hi5_top1 and c45_cands) else {}
        pf, q = profiles.get(c6, {}), quotes.get(c6, {})
        pre_c = float(c4.get("close") or (hi5_top1["close"] if hi5_top1 else 0.0) or pf.get("d1_close") or 0.0)
        op_px = float(q.get("open") or 0.0) if is_auc else 0.0
        op_pct = (op_px / pre_c - 1.0) if (is_auc and op_px > 0 and pre_c > 0) else 0.0
        o_num = round(op_pct * 100.0, 2) if is_auc else None
        lk = float(c4.get("lock_top10", pf.get("lock_pct", 35.0)))
        to_cap = round(max(5.0, 100.0 - lk), 1)
        fmcap = round(float(q.get("fmcap") or pf.get("fmcap_d1") or 35.0), 1)
        hr_pit = (float(c4.get("tight_px", pre_c * 1.25)) / op_px - 1.0) if (is_auc and op_px > 0 and c4) else float(c4.get("hr_est", 0.20))
        sc45 = int(c4.get("static_score", 100)) if c4 else 100
        ok45 = bool(c4 and is_auc and (not c4.get("has_tox_notice")) and (not c4.get("has_stock_reg")) and (not c4.get("d4_blown_pm")) and (0.02 <= op_pct <= 0.075) and hr_pit >= 0.12 and sc45 >= 120)
        hi_cards.append({
            "opt": "A", "code": _full_code(c6), "c6": c6, "name": q.get("name") or pf.get("name") or c6, "sys_rank": 1,
            "theme_desc": f"{_clean_zh(pf.get('theme', '空间最高板'))} · 全场最高 {_clean_zh(pf.get('board_str', '4连板'))}",
            "mcap_main": f"{fmcap:.1f} 亿", "mcap_sub": f"真流 {float(c4.get('real_free_mcap', 30.0)):.1f}亿 · 锁仓 {lk:.0f}%",
            "to_main": f"上限 {to_cap:.1f}%", "to_sub": f"昨换手 {pf.get('d1_nom_to', 20.0):.1f}%",
            "tape_main": f"异动空间 {hr_pit*100:.1f}%", "tape_sub": f"监管函：{'有' if c4.get('has_stock_reg') else '无'}",
            "dd_main": f"回撤 {pf.get('dd_d1', 0.0):.1f}%", "dd_sub": f"20日最大回撤 {pf.get('max_dd_20d', 0.0):.0f}%",
            "o_pct_num": o_num, "auc_s": fmt_pct_zh(o_num) if is_auc else "待09:25", "auc_sub": f"开盘 {op_px:.2f}元" if is_auc else f"昨收 {pre_c:.2f}元",
            "peer_main": "全场唯一最高身位", "peer_sub": "今日无首阴高标候选",
            "trig_s": f"{op_px:.2f}元 · 甜区+2.0%至+7.5%" if is_auc else "待09:25定",
            "score_disp": f"V2.0 {sc45} 分" if c4 else "在板第1高标", "passed": ok45,
            "why": f"全场唯一第1高度龙 · 四进五评分 {sc45}分(满120分且开在+2.0%至+7.5%才出手)",
            "klines": list(pf.get("klines_20d", [])),
            "d2_bar": [round(op_px, 2), round(op_px, 2), round(op_px, 2), round(op_px, 2), 0.2] if (is_auc and op_px > 0) else None,
        })

    vhi_c6 = hi_cards[0]["c6"] if (hi_cards and hi_cards[0]["passed"]) else ""
    if not is_auc and hi_cards:
        vhi_txt = f"待 09:25 竞价生成高标裁决（全场唯一第1名：{hi_cards[0]['name']} · {hi_cards[0]['score_disp']}）"
    else:
        vhi_txt = (f"锁定全场唯一第1高标：{hi_cards[0]['name']}（{hi_cards[0]['c6']} · {hi_cards[0]['score_disp']}）" if vhi_c6
                   else (f"今日量化空仓休息（唯一第1名 {hi_cards[0]['name']}：{hi_cards[0]['why']}）" if hi_cards else "今日量化空仓休息（全场无4板及以上候选）"))

    return {
        "watchlist": {"updated_at": wl_state.get("updated_at", ""), "rows": wl_rows},
        "tier_2to3": {"themes": themes_23, "sys_c6": v23_c6, "sys_verdict": v23_txt, "thr_str": "V2.0标准满90分 / 高胜率S档满96分 · 未封三板次日收盘清仓，封三板次日高开超9.2%非一字09:25止盈"},
        "tier_3to4": {"cands": c34_cards, "sys_c6": v34_c6, "sys_verdict": v34_txt, "thr_str": "V4.0标准主力满90分（S档满102分） · 10:30未触及午休前撤单"},
        "tier_high": {"cands": hi_cards, "sys_c6": vhi_c6, "sys_verdict": vhi_txt, "thr_str": "高标首阴V5.1满88分 / 四进五满120分"},
    }
