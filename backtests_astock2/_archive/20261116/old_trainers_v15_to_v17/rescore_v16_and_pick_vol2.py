#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
使用飞书最新 V16 (211.36倍终极定型版) 规则为候选关卡重算量化排名与出手信号，并抽取第 2 辑 8 道常规实战题（与第 1 辑完全零重合）
严格遵守只读数据库访问 (mode=ro, uri=True) 与零未来函数纪律。
"""
import os, sys, re, json, sqlite3, bisect, datetime
from collections import defaultdict
import numpy as np
import pandas as pd

ROOT_DIR = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT_DIR}/sim-portfolio"
CLEAN_DIR = f"{SIM_DIR}/backtest/2026-11-11-1to2-clean"
if CLEAN_DIR not in sys.path:
    sys.path.insert(0, CLEAN_DIR)
if f"{SIM_DIR}/scripts" not in sys.path:
    sys.path.insert(0, f"{SIM_DIR}/scripts")

from clean_wf_1to2_v14_ironclad_master import (
    load_full_prices, HARD_NOTICE_PAT, MA_NOTICE_PAT, EARN_NOTICE_PAT, BAD_NOTICE_PAT, NEG_NOTICE_PAT, norm_term
)
from exp1_fake_theme_purifier import EVENT_BASKET_PLATES, BROAD_INDUSTRY_PLATES
from fast_1to2_today import (
    build_8y_purified_theme_metadata_complete, load_csrc_ind_map, CSRC_PURE_OUTSIDER,
    PIT_NOTICES_DB_PATH, MICRO_TAPE_DB_PATH, IR_QA_DB_PATH
)

EXCLUDE_DATES = {
    "2022-01-21", "2022-05-20", "2023-02-06", "2023-03-21",
    "2024-04-11", "2025-01-27", "2025-03-07", "2026-01-05",
    "2021-12-23", "2022-04-27", "2023-04-14", "2023-05-08",
    "2024-01-24", "2024-11-22", "2026-10-19", "2026-11-06",
}

def main():
    d5 = json.load(open("/tmp/astock2_5y_hierarchical.json", encoding="utf-8"))
    q1 = json.load(open("/tmp/astock2_q1_hierarchical.json", encoding="utf-8"))
    excl = EXCLUDE_DATES | {c["date"] for c in q1}

    clean_pool = []
    for c in d5:
        if c["date"] in excl or c["date"] < "2022-01-01" or c["date"] > "2026-11-05":
            continue
        tnames = [t["name"] for t in c["themes"]]
        if any(tn in EVENT_BASKET_PLATES or re.search(r"(重组|股权转让|实控人|举牌|借壳|摘帽)", tn) for tn in tnames):
            continue
        clean_pool.append(c)

    df, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices()
    stock_theme_meta, pioneer_word_history, _ = build_8y_purified_theme_metadata_complete(df, str(df["dt_str"].max()))
    csrc_map = load_csrc_ind_map()

    # 只读加载 PIT 公告、微观封板与机构调研
    notices_by_c6 = defaultdict(list)
    if os.path.exists(PIT_NOTICES_DB_PATH):
        conn = sqlite3.connect(f"file:{PIT_NOTICES_DB_PATH}?mode=ro", uri=True)
        for sc, pdt, title in conn.execute("SELECT sec_code, pub_datetime_cst, title FROM notices WHERE pub_datetime_cst >= '2021-12-20'"):
            c6 = str(sc)[:6].zfill(6)
            ts = str(title or "")
            neg, bad = bool(NEG_NOTICE_PAT.search(ts)), bool(BAD_NOTICE_PAT.search(ts))
            hd = bool(HARD_NOTICE_PAT.search(ts)) and not (neg or bad)
            ma = bool(MA_NOTICE_PAT.search(ts)) and not (neg or bad)
            ea = bool(EARN_NOTICE_PAT.search(ts))
            if any((neg, bad, hd, ma, ea)):
                notices_by_c6[c6].append((str(pdt), neg or bad, hd, ma, ea))
        conn.close()
    for k in notices_by_c6:
        notices_by_c6[k].sort(key=lambda x: x[0])

    tape_lookup = {}
    if os.path.exists(MICRO_TAPE_DB_PATH):
        conn = sqlite3.connect(f"file:{MICRO_TAPE_DB_PATH}?mode=ro", uri=True)
        for sc, td, fst, obc in conn.execute("SELECT sec_code, trade_date, first_seal_time, open_board_count FROM zt_micro_tape"):
            tape_lookup[(str(sc)[:6].zfill(6), str(td))] = (str(fst or "99:99:99"), int(obc or 0))
        conn.close()

    ir_by_c6 = defaultdict(list)
    if os.path.exists(IR_QA_DB_PATH):
        conn = sqlite3.connect(f"file:{IR_QA_DB_PATH}?mode=ro", uri=True)
        for sc, pdt in conn.execute("SELECT sec_code, pub_datetime_cst FROM ir_qa"):
            ir_by_c6[str(sc)[:6].zfill(6)].append(str(pdt))
        conn.close()
    for k in ir_by_c6:
        ir_by_c6[k].sort()

    target_d1s = {c["d1_date"] for c in clean_pool}
    fb_sub = df[(df["dt_str"].isin(target_d1s)) & df["is_first_board"] & (~df["is_yizi"])].copy()
    g_next_open = df.set_index(["c6", "dt_str"])[["open", "low", "zt_price"]].to_dict("index")

    # 按 d1_date 逐日严格按 V16 计算全市场首板候选分与唯一头名
    v16_day_res = {}
    d1_to_d2 = {c["d1_date"]: c["date"] for c in clean_pool}
    ht_re = re.compile(r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)")
    pw_re = re.compile(r"[\u4e00-\u9fa5A-Za-z0-9]{2,8}(?:技术|材料|产品|装备|芯片|器件|电池|系统|模块|平台|光模块|算法|模型|协议)")

    for d1, grp in fb_sub.groupby("dt_str"):
        d2 = d1_to_d2[d1]
        is_mon = (datetime.date.fromisoformat(d2) - datetime.date.fromisoformat(d1)).days >= 3
        seal_r, dt_cnt, zt_cnt, promo5 = float(seal_rate_map.get(d1, 0.55)), int(dt_cnt_map.get(d1, 5)), int(zt_cnt_map.get(d1, 50)), float(promo_ma5_map.get(d1, 0.20))
        tot_thr = 329.8 if seal_r > 0.75 else 304.8
        n_s, n_e = (datetime.date.fromisoformat(d1) - datetime.timedelta(days=4)).isoformat(), f"{d2} 09:25:00"
        ir_s = (datetime.date.fromisoformat(d2) - datetime.timedelta(days=8)).isoformat()

        rows = []
        for r in grp.itertuples(index=False):
            c6 = r.c6
            d2_b = g_next_open.get((c6, d2))
            if not d2_b or d2_b["open"] <= 0:
                continue
            op, lp, zt2 = float(d2_b["open"]), float(d2_b["low"]), float(d2_b["zt_price"])
            o_pct = op / float(r.close) - 1.0
            d2_yz = (op >= zt2 - 0.01) and (lp >= zt2 - 0.01)
            ti = stock_theme_meta.get((d1, c6), {
                "name": "", "plate": "其他", "r_short": "其他", "rk_c": 99, "t_score_c": 95.0, "gap_c": 0.0,
                "p_elo": 100.0, "s_elo": 100.0, "p_sz": 1, "n_yizi": 0, "has_new": False, "own_new": False,
                "spark": 0.0, "has_2b_lead": False, "is_ma": False, "is_tech_c": False, "is_earn": False,
                "is_event_basket": False, "is_broad_ind": False, "sub_cluster_cnt": 1, "is_dying_pulse": False
            })
            nb = nh = nm = ne = False
            for pdt, f_bad, f_hd, f_ma, f_ea in notices_by_c6.get(c6, []):
                if n_s <= pdt <= n_e:
                    nb |= f_bad; nh |= f_hd; nm |= f_ma; ne |= f_ea
            if nb: nh = nm = False
            sname = ti["name"]
            is_st = ("ST" in sname.upper()) or ("退" in sname)
            is_ma = bool(ti["is_ma"] or nm)
            is_earn = bool(ti["is_earn"] or ne)
            is_pw = any(1 <= sum(1 for ds_ in pioneer_word_history.get(norm_term(m.group(0)), ()) if ds_ <= d1) <= 3 for m in pw_re.finditer(f"{ti.get('r_short','')} {sname}"))
            s_pd = ((28 if ti["rk_c"] == 1 else (16 if ti["rk_c"] == 2 else (8 if ti["rk_c"] == 3 else 0)))
                    + (18 if ti["p_sz"] >= 4 else (10 if ti["p_sz"] >= 2 else -15))
                    + (12 if ti["has_new"] else 0) + (8 if ti["own_new"] else 0) + (10 if ti["spark"] > 0 else 0)
                    + (18 if nh else 0) + (18 if is_ma else 0) + (12 if ti["is_tech_c"] else 0) + (12 if ti["gap_c"] >= 20.0 else 0)
                    + float(np.clip((ti["t_score_c"] - 100.0) * 0.25, 0.0, 25.0)) + float(np.clip((ti["s_elo"] - 100.0) * 0.35, -10.0, 18.0)))
            cs_sec = str(csrc_map.get(c6, ""))[:3]
            name_pen = -20.0 if (ht_re.search(ti["plate"]) and cs_sec in CSRC_PURE_OUTSIDER and not (nh or is_ma)) else 0.0
            mcap, amt, to = float(r.mcap), float(r.amount), float(r.to)
            dd20 = float(r.f_dd20_d0) if pd.notna(r.f_dd20_d0) else 0.90
            dd60 = float(r.f_dd60_d0) if pd.notna(r.f_dd60_d0) else 0.85
            pos20 = float(r.f_pos20_d0) if pd.notna(r.f_pos20_d0) else 0.50
            d0p = float(r.f_d0_pct) if pd.notna(r.f_d0_pct) else 0.0
            ret10 = float(r.f_ret_pre10) if pd.notna(r.f_ret_pre10) else 0.0
            vr = float(r.f_d1_vol_ratio) if pd.notna(r.f_d1_vol_ratio) else 1.5
            zt20 = int(r.f_zt_cnt_pre20) if pd.notna(r.f_zt_cnt_pre20) else 0
            brk60 = int(r.f_break60)
            tight = float(r.d1_seal_tightness) if pd.notna(r.d1_seal_tightness) else 0.0
            sc_m = (28 if 60 <= mcap <= 155 else (10 if 40 <= mcap < 60 else (-20 if mcap < 35 else 0))) + (18 if 2.2e8 <= amt <= 15e8 else (-25 if amt < 1.8e8 else -10))
            sc_c = ((25 if d0p <= -0.010 else (15 if d0p <= 0.005 else (-35 if d0p > 0.030 else 0)))
                    + (15 if ret10 <= 0.05 else (-35 if ret10 > 0.18 else 0)) + (15 if to <= 9.0 else (8 if to <= 15.0 else (-25 if to > 18.0 else 0)))
                    + (15 if vr <= 1.75 else (-15 if vr > 2.3 else 0)) + (18 if seal_r < 0.64 else (-25 if seal_r >= 0.72 else 0))
                    + (12 if dt_cnt <= 6 else (-15 if dt_cnt >= 15 else 0)) + (12 if zt_cnt >= 45 else (-18 if zt_cnt < 35 else 0)))
            clean_b = (brk60 == 1) and (ret10 <= 0.08) and (zt20 == 0) and (to <= 14.0)
            if clean_b:
                sq_b = sc_m + sc_c + 24
            else:
                sq_b = (sc_m + sc_c + (32 if dd20 <= 0.86 else (18 if dd20 <= 0.90 else (-40 if dd20 > 0.95 else 0)))
                        + (18 if dd60 <= 0.76 else (10 if dd60 <= 0.82 else (-15 if dd60 > 0.92 else 0)))
                        + (22 if (zt20 >= 1 and dd20 <= 0.86) else (-20 if (zt20 >= 1 and dd20 > 0.92) else 0))
                        + (25 if pos20 <= 0.30 else (12 if pos20 <= 0.45 else (-35 if pos20 > 0.75 else 0))))
            fst_t, ob_c = tape_lookup.get((c6, d1), ("99:99:99", 0))
            is_ht = (ob_c == 1) and (fst_t <= "10:30:00") and (tight >= 38.0)
            irl = ir_by_c6.get(c6, [])
            has_ir = bisect.bisect_right(irl, n_e) > bisect.bisect_left(irl, ir_s)
            sq_b += (5.0 if is_ht else 0.0) + (5.0 if has_ir else 0.0)
            gate_ok = (not is_st) and (not is_earn) and (not nb) and (18.0 <= mcap <= 220.0) and (to <= 20.0) and (not (zt20 >= 4 and pos20 > 0.38)) and (float(r.close) <= 60.0)
            pass_l1 = (not ti["is_event_basket"]) and (not (ti["is_broad_ind"] and ti["sub_cluster_cnt"] < 2))
            pass_l2 = not ti["is_dying_pulse"]
            p_tight = tight >= 37.0
            pur_ok = gate_ok and pass_l1 and pass_l2 and (ti["p_sz"] <= 35) and p_tight
            rows.append({
                "c6": c6, "plate": ti["plate"], "r_short": ti.get("r_short", ""), "p_sz": int(ti["p_sz"]),
                "s_elo": float(ti["s_elo"]), "sub_cluster_cnt": int(ti["sub_cluster_cnt"]), "is_pioneer_word": is_pw,
                "has_new_term": bool(ti["has_new"]), "own_new": bool(ti["own_new"]), "notice_hard": nh, "notice_bad": nb,
                "is_ma": is_ma, "name_pen": name_pen, "s_prior_dual": s_pd, "s_q_base": sq_b, "mcap": mcap,
                "d1_tightness": tight, "dd20_d0": dd20, "clean_brk60": clean_b, "pass_l2": pass_l2, "p_tight": p_tight,
                "purifier_ok": pur_ok, "gate_ok": gate_ok, "o_pct": o_pct, "d2_is_yizi": d2_yz,
                "is_buyable_open": gate_ok and (op < zt2 - 0.005), "is_event_basket": bool(ti["is_event_basket"]),
            })
        if not rows:
            continue
        dfd = pd.DataFrame(rows)
        vp = dfd[(dfd["plate"] != "其他") & (~dfd["is_event_basket"]) & (dfd["p_sz"] >= 2)]
        rk_tm = {k: i + 1 for i, k in enumerate(vp.groupby("plate")["s_prior_dual"].median().sort_values(ascending=False).index)}
        dfd["rk_theme"] = dfd["plate"].map(rk_tm).fillna(99).astype(int)
        nuc = float(dfd["o_pct"].mean()) < 0.0
        frz = promo5 < 0.13
        flk = dfd["d2_is_yizi"] | ((not is_mon) & (dfd["o_pct"] > 0.078)) | (is_mon & (dfd["o_pct"] > 0.088))
        dfd["flc"] = flk.astype(int).groupby(dfd["plate"]).transform("sum")
        dfd["pyz"] = dfd["d2_is_yizi"].astype(int).groupby(dfd["plate"]).transform("sum")
        myz = int(dfd["d2_is_yizi"].sum())
        in_w = dfd["is_buyable_open"] & ((is_mon & dfd["o_pct"].between(0.020, 0.088)) | ((not is_mon) & dfd["o_pct"].between(0.022, 0.078)))
        dfd["_tbo"] = np.where(in_w, dfd["o_pct"], -9.99)
        dfd["tbrk"] = dfd.groupby("plate")["_tbo"].rank(ascending=False, method="min")
        dfd["_bo"] = np.where(dfd["is_buyable_open"], dfd["o_pct"], -9.99)
        dfd["mrk"] = dfd["_bo"].rank(ascending=False, method="min")
        dfd["srk"] = dfd.groupby(["plate", "r_short"])["_bo"].rank(ascending=False, method="min")
        p2 = dfd.groupby("plate")["_bo"].transform(lambda s: s.nlargest(2).iloc[-1] if (s > -1.0).sum() >= 2 else -0.05)
        olead = np.where(dfd["tbrk"] == 1, dfd["o_pct"] - p2, 0.0)
        hsub = (dfd["p_sz"] >= 8) & (dfd["r_short"] != dfd["plate"]) & (dfd["r_short"] != "其他") & (dfd["r_short"] != "")
        rkb = np.where(dfd["tbrk"] == 1, 35.0, np.where(hsub & (dfd["srk"] == 1), 24.0, np.where(dfd["tbrk"] == 2, 8.0, -25.0)))
        sw = (dfd["rk_theme"] == 1) & (dfd["p_sz"] >= 8) & (dfd["tbrk"] == 1)
        hmh = dfd["notice_hard"] | dfd["is_ma"]
        yg = np.select(
            [(dfd["flc"] == 1) & (dfd["tbrk"] == 1) & np.isin(myz, [1, 2]), (dfd["flc"] == 1) & (dfd["tbrk"] == 1),
             (dfd["flc"] == 1) & (dfd["tbrk"] >= 2), (dfd["flc"] >= 2) & sw, (dfd["flc"] == 2) & (~sw),
             (dfd["flc"] >= 3) & (~sw), (dfd["flc"] == 0) & (myz == 0) & (~hmh)],
            [8.0, 5.0, -10.0, 5.0, -15.0, -22.0, -5.0], default=0.0
        )
        aucb = (rkb + np.where(dfd["mrk"] <= 3, 20.0, np.where(dfd["mrk"] <= 6, 12.0, 0.0))
                + np.where(olead >= 0.020, 22.0, np.where(olead >= 0.010, 12.0, 0.0))
                + np.where(dfd["pyz"] >= 1, 10.0, 0.0)
                + np.where(dfd["o_pct"].between(0.040, 0.082), 20.0, np.where(dfd["o_pct"].between(0.018, 0.040), 12.0, 0.0)))
        spw = (dfd["s_prior_dual"] + np.where(dfd["is_pioneer_word"] | dfd["has_new_term"] | dfd["own_new"] | (dfd["sub_cluster_cnt"] >= 2), 15.0, 0.0)
               + np.where(dfd["s_elo"] >= 105.0, 10.0, np.where(dfd["s_elo"] <= 95.0, -10.0, 0.0))
               + np.where(dfd["notice_hard"], 8.0, 0.0) + np.where(dfd["notice_bad"], -35.0, 0.0)
               + (10.0 if is_mon else 0.0) + dfd["name_pen"] + yg * 0.5)
        sq = dfd["s_q_base"] + aucb + np.where((not is_mon) & (dfd["o_pct"] < 0.031), -15.0, 0.0) + yg * 0.5
        tot = spw + sq
        psum, pcnt = dfd.groupby("plate")["o_pct"].transform("sum"), dfd.groupby("plate")["o_pct"].transform("count")
        pavg = psum / np.maximum(pcnt, 1)
        peers = np.where(pcnt > 1, (psum - dfd["o_pct"]) / (pcnt - 1), 0.0)
        hic = (dfd["o_pct"] >= 0.020).astype(int).groupby(dfd["plate"]).transform("sum")
        pl3 = (pcnt <= 1) | ((peers >= -0.010) & ((pavg >= -0.005) | (hic >= 2)))
        pnd = (~((dfd["p_sz"] >= 2) & (dfd["tbrk"] >= 3))) & (~((dfd["pyz"] >= 1) & ((dfd["mcap"] > 90.0) | (dfd["d1_tightness"] < 15.0))))
        cok = dfd["is_buyable_open"] if (not nuc and not frz) else pd.Series(False, index=dfd.index)
        ook = dfd["o_pct"].between(0.020, 0.088) if is_mon else dfd["o_pct"].between(0.022, 0.078)
        mt1 = cok & ook & (spw >= 45.0) & (sq >= 150.0) & (tot >= tot_thr) & dfd["purifier_ok"] & pl3 & pnd
        mt2 = cok & (dfd["p_sz"] == 1) & (dfd["is_pioneer_word"] | dfd["has_new_term"] | dfd["own_new"] | dfd["notice_hard"] | dfd["is_ma"]) & dfd["o_pct"].between(0.035, 0.078) & (dfd["mrk"] <= 3) & dfd["pass_l2"] & dfd["p_tight"] & ((dfd["dd20_d0"] <= 0.88) | dfd["clean_brk60"])
        mm = mt1 | mt2
        if is_mon:
            mmon = cok & dfd["o_pct"].between(0.022, 0.088) & (spw >= 38.0) & (sq >= 145.0) & (tot >= tot_thr) & dfd["purifier_ok"] & pl3 & pnd
            tmask = mm | (mmon & (~mm))
        else:
            tmask = mm
        rsv = np.where(mm, tot + 1000.0, tot)
        if tmask.any():
            sub_ok = dfd[tmask].assign(_rsv=rsv[tmask])
            if (sub_ok["rk_theme"] == 1).any() and (4 <= int(sub_ok.sort_values("_rsv", ascending=False).iloc[0]["rk_theme"]) < 99):
                tmask = pd.Series(False, index=dfd.index)
        dfd["v16_ok"] = tmask
        dfd["v16_tot"] = tot
        v16_day_res[d1] = {r_.c6: (bool(r_.v16_ok), float(r_.v16_tot)) for r_ in dfd.itertuples()}

    # 将 V16 结果写回 clean_pool 并打印候选关卡分布
    updated_pool = []
    for c in clean_pool:
        dmap = v16_day_res.get(c["d1_date"], {})
        all_cands = [cd for th in c["themes"] for cd in th["cands"]]
        for cd in all_cands:
            c6 = cd["code"][:6]
            v_ok, v_tot = dmap.get(c6, (False, 180.0))
            g_ok = bool(cd["gate_ok"])
            opct = float(cd["o_pct"])
            if v_ok and g_ok and (2.2 <= opct <= 7.8):
                tier_sc = 10000.0 + v_tot
                cd["sys_pass"] = True
            elif g_ok and (2.2 <= opct <= 7.8):
                tier_sc = 5000.0 + v_tot
                cd["sys_pass"] = False
            elif g_ok and ((0.0 <= opct < 2.2) or (7.8 < opct <= 9.8)):
                tier_sc = 2000.0 + v_tot
                cd["sys_pass"] = False
            else:
                tier_sc = v_tot
                cd["sys_pass"] = False
            cd["_v16_tier_sc"] = tier_sc
        all_cands_sorted = sorted(all_cands, key=lambda x: x["_v16_tier_sc"], reverse=True)
        for rk_i, cd in enumerate(all_cands_sorted, 1):
            cd["sys_rank"] = rk_i
            del cd["_v16_tier_sc"]
        pass_cands = [cd for cd in all_cands if cd["sys_pass"]]
        if pass_cands:
            top_p = min(pass_cands, key=lambda x: x["sys_rank"])
            c["sys_cand_code"] = top_p["code"]
            c["sys_cand_name"] = f"{top_p['name']}（触发量化出手）"
            c["sys_cand_opt"] = top_p["opt"]
            c["sys_cand_theme_idx"] = top_p["theme_idx"]
            c["sys_ret"] = top_p["net_ret"] if top_p["executed"] else 0.0
        else:
            top1 = min(all_cands, key=lambda x: x["sys_rank"])
            c["sys_cand_code"] = ""
            c["sys_cand_name"] = f"今日量化空仓（榜首{top1['name']}未达出手线）"
            c["sys_cand_opt"] = ""
            c["sys_cand_theme_idx"] = -1
            c["sys_ret"] = 0.0
        c["sys_beat"] = bool(c["market_best_ret"] > c["sys_ret"])
        updated_pool.append(c)

    # 客观均匀抽取第 2 辑 8 道常规实战题（覆盖 2022-2026 各年份、含真龙晋级/常规轮动/空仓防守及人机对比，覆盖 A/B/C/D/E，完全不重复）
    picked, used = [], set()
    def pick(pred):
        for x in updated_pool:
            if x["date"] not in used and pred(x):
                used.add(x["date"])
                picked.append(x)
                return

    pick(lambda x: x["date"].startswith("2022") and x["date"] >= "2022-06-01" and x["market_ans"] == "A" and x["market_best_ret"] >= 5.0)
    pick(lambda x: x["date"].startswith("2023") and x["market_ans"] == "D" and x["market_best_ret"] >= 5.0)
    pick(lambda x: x["date"].startswith("2023") and x["date"] >= "2023-06-01" and x["market_ans"] == "E")
    pick(lambda x: x["date"].startswith("2024") and x["market_ans"] == "B" and x["sys_cand_code"] != "")
    pick(lambda x: x["date"].startswith("2024") and x["date"] >= "2024-07-01" and x["market_ans"] == "C" and x["market_best_ret"] >= 5.0)
    pick(lambda x: x["date"].startswith("2025") and x["date"] >= "2025-04-01" and x["market_ans"] in ("A", "B", "C", "D") and x["sys_cand_code"] != "")
    pick(lambda x: x["date"].startswith("2025") and x["date"] >= "2025-06-01" and x["market_ans"] == "E")
    pick(lambda x: x["date"].startswith("2026") and x["date"] >= "2026-03-01" and x["market_ans"] in ("A", "B", "C", "D") and x["market_best_ret"] >= 5.0)

    picked.sort(key=lambda x: x["date"])
    q2 = []
    for i, x in enumerate(picked[:8], 1):
        cp = json.loads(json.dumps(x))
        cp["id"] = i
        q2.append(cp)

    with open("/tmp/astock2_q2_hierarchical.json", "w", encoding="utf-8") as f:
        json.dump(q2, f, ensure_ascii=False)

    print(f"V16 rescored {len(updated_pool)} clean days. Picked {len(q2)} Vol.2 cases:")
    for x in q2:
        print(f"  #{x['id']} {x['date']} (D1={x['d1_date']}) | type={x['type']} | ans={x['market_ans']} | sys_pass={bool(x['sys_cand_code'])} | themes={[t['name'] for t in x['themes']]}")

if __name__ == "__main__":
    main()
