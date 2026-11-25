#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Stock-level atomic PIT factors: Family 5(stock), Family 6(RD011), Family 7(stock), Family 8(LHB), Family 9(mcap)."""
import bisect
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"

PAT_SOE = re.compile(r"中国|中航|航天|国|北京|上海|广东|福建|浙江|四川|山东|陕西|重庆|深圳|同济|清华|交大|电科|兵器|电投")
PAT_CONTRACT = re.compile(r"中标|重大合同|日常经营重大合同|订单|签订.*合同|签订.*协议")
PAT_EARN_POS = re.compile(r"业绩预增|预增|略增|续盈|扭亏")
PAT_REG = re.compile(r"监管工作函|关注函|重点监控|问询函|监管函")


def _shift_cal(dt_s: str, days: int) -> str:
    return (datetime.strptime(dt_s, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def _cnt_range(arr, lo, hi):
    return max(0, bisect.bisect_left(arr, hi) - bisect.bisect_left(arr, lo)) if arr else 0


def load_stock_aux(pool_codes: set):
    t10 = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"))
    qm = ",".join("?" for _ in pool_codes)
    clist = sorted(pool_codes)

    ir_ts = defaultdict(list)
    con_ir = sqlite3.connect(f"file:{SIM}/data/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
    for sc, ts in con_ir.execute(f"SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE sec_code IN ({qm})", clist):
        ir_ts[str(sc).zfill(6)].append(str(ts)[:19])
    con_ir.close()
    for k in ir_ts: ir_ts[k].sort()

    con_ts, earn_ts, reg_ts = defaultdict(list), defaultdict(list), defaultdict(list)
    con_n = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for sc, ti, at, ts in con_n.execute(f"SELECT sec_code, title, ann_type, pub_datetime_cst FROM notices WHERE sec_code IN ({qm})", clist):
        c6, s_ts, t_s = str(sc).zfill(6), str(ts)[:19], f"{ti or ''} {at or ''}"
        if at == "重大合同" or PAT_CONTRACT.search(t_s): con_ts[c6].append(s_ts)
        if PAT_EARN_POS.search(t_s): earn_ts[c6].append(s_ts)
        if PAT_REG.search(t_s) and "回复" not in t_s: reg_ts[c6].append(s_ts)
    con_n.close()
    con_o = sqlite3.connect(f"file:{SIM}/backtest/2026-08-24-daban/notices.db?mode=ro", uri=True)
    for sc, ti, at, nd in con_o.execute(f"SELECT code, title, ntype, ndate FROM notice WHERE code IN ({qm}) AND ndate >= '2025-01-01'", clist):
        c6, s_ts, t_s = str(sc).zfill(6), f"{str(nd)[:10]} 23:59:59", f"{ti or ''} {at or ''}"
        if at == "重大合同" or PAT_CONTRACT.search(t_s): con_ts[c6].append(s_ts)
        if PAT_EARN_POS.search(t_s): earn_ts[c6].append(s_ts)
        if PAT_REG.search(t_s) and "回复" not in t_s: reg_ts[c6].append(s_ts)
    con_o.close()
    for d in (con_ts, earn_ts, reg_ts):
        for k in d: d[k].sort()

    # KPL plates (d-1) -> stock themes map
    kpl_stk_th = defaultdict(list)
    kpl_th_stks = defaultdict(lambda: defaultdict(set))
    with open(f"{SIM}/data/kpl_plates_2018_2026_merged.jsonl", encoding="utf-8") as f:
        for ln in f:
            obj = json.loads(ln)
            dt = obj.get("date", "")
            if dt < "2021-10-01": continue
            for pl in obj.get("plates", []):
                pn = str(pl.get("plate", "")).strip()
                if not pn or pn in ("其他", "公告", "ST板块"): continue
                stks = [str(s[0])[:6].zfill(6) for s in pl.get("stocks", [])]
                kpl_th_stks[dt][pn].update(stks)
                for c6 in stks:
                    if c6 in pool_codes:
                        kpl_stk_th[(dt, c6)].append(pn)

    # LHB Bayes + Lhasa 3-state (strictly d-1)
    bay = pd.read_parquet(f"{SIM}/backtests_astock2/rd016_famous_youzi_seats_20261117/bayes_seat_scores_d1_5y.parquet")
    bay["stock_code"] = bay["stock_code"].astype(str).str.zfill(6)
    bay = bay[bay["stock_code"].isin(pool_codes)].copy()
    bay_map = {}
    for (dt, sc), g in bay.groupby(["date", "stock_code"], sort=False):
        w = np.maximum(g["NET"].to_numpy(float), 1.0)
        bay_map[(dt, sc)] = float(np.sum(w * g["b_t2"].to_numpy(float)) / np.sum(w))

    lhb = pd.read_parquet(f"{SIM}/backtests_astock2/rd016_famous_youzi_seats_20261117/clean_lhb_5y.parquet",
                          columns=["date", "stock_code", "dept_code", "dept_name", "side", "NET", "is_three"])
    lhb["stock_code"] = lhb["stock_code"].astype(str).str.zfill(6)
    lhb = lhb[lhb["stock_code"].isin(pool_codes)].copy()
    lhb["is_lh"] = lhb["dept_name"].str.contains("拉萨", na=False) & (~lhb["dept_name"].str.contains("东亚", na=False))
    lhb_map = {}
    for (dt, sc), grp in lhb.groupby(["date", "stock_code"], sort=False):
        g = grp[grp["is_three"] == 0] if (grp["is_three"] == 0).any() else grp
        lh_rows = g[g["is_lh"]]
        lh_net = float(lh_rows["NET"].sum()) if len(lh_rows) else 0.0
        lh_buy = int((lh_rows["side"] == "B").any() and (lh_net > 0))
        lh_sell = int((len(lh_rows) > 0) and (lh_net < 0))
        org_net = float(g[g["dept_code"] == "0"]["NET"].sum()) / 1e8
        lhb_map[(dt, sc)] = (1 if lh_sell else (-1 if lh_buy else 0), lh_buy, lh_sell, org_net)

    return {"t10": t10, "ir_ts": ir_ts, "con_ts": con_ts, "earn_ts": earn_ts, "reg_ts": reg_ts,
            "kpl_stk_th": kpl_stk_th, "kpl_th_stks": kpl_th_stks, "bay_map": bay_map, "lhb_map": lhb_map}


def enrich_pool_with_stock_factors(df_pool: pd.DataFrame, stock_bars, big_active, aux, sh_idx, sz_idx, prev_td) -> pd.DataFrame:
    rows = []
    for r in df_pool.itertuples(index=False):
        c6, bd, nm = r.code, r.buy_date, str(r.name)
        sb = stock_bars.get(c6)
        idx_d = sh_idx if c6.startswith("60") else sz_idx
        p_bd = sb["dt_to_idx"].get(bd, -1) if sb else -1
        p_d1 = (p_bd - 1) if p_bd >= 1 else (int(np.searchsorted(sb["dts"], bd, side="left")) - 1 if sb else -1)
        d1_dt = str(sb["dts"][p_d1]) if (sb and p_d1 >= 0) else prev_td.get(bd, "")
        buy_open = float(sb["open"][p_bd]) if (sb and p_bd >= 0) else float(r.buy_price)

        buy_open_adj = buy_open * float(sb["adj_close"][p_bd] / sb["close"][p_bd]) if (sb and p_bd >= 0 and sb["close"][p_bd] > 0) else buy_open

        def _dev_and_pmax(pos, win, mult):
            if not sb or pos < 1: return 0.0, 999999.0
            c_i = float(sb["adj_close"][pos]); i_cur = idx_d.get(str(sb["dts"][pos]))
            if not i_cur or c_i <= 0: return 0.0, 999999.0
            mdv, mp = -9.9, 999999.0
            for w in range(1, min(win + 1, pos + 1)):
                bi = pos - w; i_b = idx_d.get(str(sb["dts"][bi])); bc_a = float(sb["adj_close"][bi])
                if not i_b or bc_a <= 0: continue
                ichg = i_cur / i_b - 1.0
                mdv = max(mdv, (c_i / bc_a - 1.0) - ichg)
                mp = min(mp, bc_a * (mult + ichg))
            return (mdv if mdv > -9.0 else 0.0), mp

        def _hr(pos, win, mult):
            if not sb or pos < 1 or buy_open_adj <= 0: return 0.50
            _, mp = _dev_and_pmax(pos, win, mult)
            return float(np.clip((mp / buy_open_adj) - 1.0, -0.5, 5.0)) if mp < 999990.0 else 1.50

        hr10 = _hr(p_d1, 10, 2.0); hr30 = _hr(p_d1, 30, 3.0)
        d10_now, _ = _dev_and_pmax(p_d1, 10, 2.0)
        d10_3, _ = _dev_and_pmax(p_d1 - 3, 10, 2.0) if p_d1 >= 4 else (d10_now, 999999.0)
        ac = sb["adj_close"] if sb else None
        ret20 = float(ac[p_d1] / ac[p_d1 - 20] - 1.0) if (sb and p_d1 >= 20 and ac[p_d1 - 20] > 0) else 0.0
        ret5 = float(ac[p_d1] / ac[p_d1 - 5] - 1.0) if (sb and p_d1 >= 5 and ac[p_d1 - 5] > 0) else 0.0
        ma20 = float(np.mean(ac[max(0, p_d1 - 19):p_d1 + 1])) if (sb and p_d1 >= 0) else 1.0
        ma20_dist = float(ac[p_d1] / ma20 - 1.0) if (sb and p_d1 >= 0 and ma20 > 0) else 0.0
        mcap_yi = float(sb["mcap_yi"][p_d1]) if (sb and p_d1 >= 0) else 50.0
        t10_recs = [x for x in aux["t10"].get(c6, []) if x[0] < bd]
        lock10 = float(t10_recs[-1][2]) / 100.0 if t10_recs else 0.38
        free_mcap = mcap_yi * max(0.05, 1.0 - lock10)

        t_cut = f"{bd} 09:25:00"
        ir30 = _cnt_range(aux["ir_ts"].get(c6), f"{_shift_cal(bd, -30)} 00:00:00", t_cut)
        con45 = int(_cnt_range(aux["con_ts"].get(c6), f"{_shift_cal(bd, -45)} 00:00:00", t_cut) > 0)
        earn90 = int(_cnt_range(aux["earn_ts"].get(c6), f"{_shift_cal(bd, -90)} 00:00:00", t_cut) > 0)
        reg15 = int(_cnt_range(aux["reg_ts"].get(c6), f"{_shift_cal(bd, -15)} 00:00:00", t_cut) > 0)

        th_list = aux["kpl_stk_th"].get((d1_dt, c6), [])
        big_set = big_active.get(d1_dt, set())
        has_mid = int(any(len((aux["kpl_th_stks"].get(d1_dt, {}).get(p, set()) & big_set) - {c6}) > 0 for p in th_list) or mcap_yi >= 100.0)
        is_reb = int(bool(sb and p_d1 >= 2 and sb["is_zt"][p_d1] and (not sb["is_zt"][p_d1 - 1]) and np.any(sb["is_zt"][max(0, p_d1 - 4):p_d1 - 1])))

        sig_d = str(getattr(r, "sig_date", "")) if hasattr(r, "sig_date") else d1_dt
        lhb_d = sig_d if (sig_d, c6) in aux["lhb_map"] else d1_dt
        lh_st, lh_b, lh_s, org_n = aux["lhb_map"].get((lhb_d, c6), (0, 0, 0, 0.0))
        bt2 = aux["bay_map"].get((lhb_d, c6), 0.0)

        rows.append({
            "f28_stk_ret20_d1": ret20, "f29_stk_ret5_d1": ret5,
            "f30_rd11_hr10d": hr10, "f31_rd11_hr30d": hr30, "f32_rd11_tight_hr": min(hr10, hr30),
            "f33_rd11_dev10_slope3": d10_now - d10_3, "f34_rd11_ma20_dist": ma20_dist,
            "f35_rd11_ir_cnt30d": ir30, "f36_rd11_soe_flag": int(bool(PAT_SOE.search(nm))),
            "f37_rd11_contract45d": con45, "f38_rd11_earn_pos90d": earn90, "f39_rd11_reg_letter15d": reg15,
            "f40_rd11_mid100yi_theme": has_mid, "f44_reb_is_rebound_stk": is_reb,
            "f45_lhb_bayes_t2_d1": bt2, "f46_lhb_lhasa_state_d1": lh_st,
            "f47_lhb_lhasa_net_buy_d1": lh_b, "f48_lhb_lhasa_net_sell_d1": lh_s, "f49_lhb_org_net_yi_d1": org_n,
            "f58_mcap_yi_d1": mcap_yi, "f59_mcap_log_d1": float(np.log1p(max(1.0, mcap_yi))),
            "f60_free_mcap_yi_d1": free_mcap,
        })
    return pd.concat([df_pool.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
