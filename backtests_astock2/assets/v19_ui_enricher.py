# -*- coding: utf-8 -*-
"""
v19_ui_enricher.py: 为 V19 历史刷题机 JSON 补齐前日板块均幅与纯客观盘面展示字段
严格 PIT：仅使用 <= d1_date 的 KPL 板块历史成分股与 dmap[c6, d1_date] 前收涨跌幅。
"""
import os
import re
import json
from collections import defaultdict
import numpy as np

from v191_dt_defer_helper import load_dt_defer_tables

SIM_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
KPL_5Y_PATH = os.path.join(SIM_DIR, "data", "kpl_plates_5y_2021_2026_complete.jsonl")


def _build_plate_member_snapshots(target_pairs: set[tuple[str, str]]) -> dict[tuple[str, str], set[str]]:
    """按严格 <= d1_date 累计 KPL 板块成分股，返回 {(d1_date, plate): set(c6)}。"""
    if not target_pairs or not os.path.exists(KPL_5Y_PATH):
        return {}
    plates_by_dt = defaultdict(set)
    for d1, p in target_pairs:
        plates_by_dt[d1].add(p)
    sorted_d1s = sorted(plates_by_dt.keys())
    cur_idx = 0
    cum_members = defaultdict(set)
    snapshots = {}

    day_entries = []
    with open(KPL_5Y_PATH, "r", encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            d = json.loads(ln)
            dt = d.get("date", "")
            if dt:
                day_entries.append((dt, d.get("plates", [])))
    day_entries.sort(key=lambda x: x[0])

    for dt, plist in day_entries:
        while cur_idx < len(sorted_d1s) and sorted_d1s[cur_idx] < dt:
            d_t = sorted_d1s[cur_idx]
            for p in plates_by_dt[d_t]:
                snapshots[(d_t, p)] = set(cum_members.get(p, ()))
            cur_idx += 1
        for p_obj in plist:
            pn = str(p_obj.get("plate", "")).strip()
            for s in p_obj.get("stocks", []):
                cum_members[pn].add(str(s[0]).strip()[:6].zfill(6))
        while cur_idx < len(sorted_d1s) and sorted_d1s[cur_idx] == dt:
            d_t = sorted_d1s[cur_idx]
            for p in plates_by_dt[d_t]:
                snapshots[(d_t, p)] = set(cum_members.get(p, ()))
            cur_idx += 1

    while cur_idx < len(sorted_d1s):
        d_t = sorted_d1s[cur_idx]
        for p in plates_by_dt[d_t]:
            snapshots[(d_t, p)] = set(cum_members.get(p, ()))
        cur_idx += 1
    return snapshots


def enrich_v19_cases_ui_fields(cases: list[dict]) -> list[dict]:
    """为 50 题/5 关案例补齐 d1_plate_avg_* 与 raw_* / quant_* 展示字段。"""
    target_pairs = {(c["d1_date"], th["name"]) for c in cases for th in c.get("themes", [])}
    snaps = _build_plate_member_snapshots(target_pairs)
    dmap = load_dt_defer_tables()["dmap"]

    for c in cases:
        d1 = c["d1_date"]
        is_mon = bool(c.get("is_mon_window", False))
        win_hi = 8.8 if is_mon else 7.8
        if "promo_ma5_raw" not in c:
            c["promo_ma5_raw"] = str(c.get("promo_ma5_str", "20.0%")).split()[0]

        for th in c.get("themes", []):
            pname = th["name"]
            mems = snaps.get((d1, pname), set())
            vals = []
            for c6 in mems:
                bar = dmap.get((c6, d1))
                if bar is not None and float(bar.prev_c_adj) > 0:
                    vals.append((float(bar.close) / float(bar.prev_c_adj) - 1.0) * 100.0)
            if vals:
                avg_v = round(float(np.mean(vals)), 2)
                th["d1_plate_avg_pct"] = avg_v
                th["d1_plate_mem_cnt"] = len(vals)
                th["d1_plate_avg_str"] = f"{avg_v:+.2f}% ({len(vals)}只成分股)"
            else:
                th["d1_plate_avg_pct"] = 10.0
                th["d1_plate_mem_cnt"] = 0
                th["d1_plate_avg_str"] = "昨日首板涨停梯队"

            yz_cnt = int(th.get("plate_yizi_cnt", 0))
            ov_cnt = max(0, int(th.get("front_lock_cnt", 0)) - yz_cnt)
            th["raw_term_type"] = f"同细分分支最多 {int(th.get('sub_cluster_cnt', 1))} 只涨停"
            th["raw_escort"] = f"今一字 {yz_cnt} 只 · 高开超{win_hi:.1f}%共 {ov_cnt} 只"
            th["quant_term_type"] = th.get("term_type", "")
            th["quant_escort"] = th.get("escort", "")

            cands = th.get("cands", [])
            sorted_open = sorted(cands, key=lambda x: float(x.get("o_pct", -99.0)), reverse=True)
            rk_in_card = {x["code"]: i + 1 for i, x in enumerate(sorted_open)}
            top1_o = float(sorted_open[0]["o_pct"]) if sorted_open else 0.0
            top2_o = float(sorted_open[1]["o_pct"]) if len(sorted_open) >= 2 else None

            for cd in cands:
                cd["raw_desc"] = re.sub(r"\s*【[^】]*】", "", str(cd.get("desc", ""))).strip()
                cd["raw_blind_desc"] = re.sub(r"\s*【[^】]*】", "", str(cd.get("blind_desc", ""))).strip()
                cd["raw_d1_board"] = str(cd.get("d1_board_detail", "")).replace("(硬换手+5分)", "").strip()
                amt_w = int(cd.get("seal_amt_wan", 0))
                cd["raw_d1_seal"] = (
                    f"封单{amt_w}万 · {cd.get('seal', '')}"
                    if amt_w > 0
                    else f"紧密度{float(cd.get('tightness', 0.0)):.0f}分 · {cd.get('seal', '')}"
                )
                c_rk = rk_in_card.get(cd["code"], 1)
                m_rk = int(cd["rk"][1]) if cd.get("rk") and len(cd["rk"]) > 1 else 99
                cd["raw_rk"] = [c_rk, m_rk]
                cd["raw_rk_str"] = f"同卡竞价第{c_rk}名 / 全场第{m_rk}名"
                if len(cands) == 1:
                    cd["raw_lead"] = float(cd.get("lead", 0.0))
                    cd["raw_lead_str"] = str(cd.get("lead_detail_str", ""))
                elif c_rk == 1 and top2_o is not None:
                    ld = round(float(cd["o_pct"]) - top2_o, 2)
                    cd["raw_lead"] = ld
                    cd["raw_lead_str"] = f"领先第2名 +{ld:.2f}%"
                else:
                    ld = round(float(cd["o_pct"]) - top1_o, 2)
                    cd["raw_lead"] = ld
                    cd["raw_lead_str"] = f"较第1名 {ld:.2f}%"
                ts = str(cd.get("trig_str", ""))
                cd["raw_trig_str"] = ts.replace("挂卖五价", "11:30前条件单")
    return cases
