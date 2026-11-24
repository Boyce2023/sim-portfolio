#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Layers 3-7: zt_micro_tape, KPL themes+10cm synergy, LHB+Youzi+Bayes, Xueqiu/Guba, Cninfo catalysts/tox/IR, CSRC."""
import bisect, glob, json, re, sqlite3
from collections import defaultdict
import numpy as np
import pandas as pd

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
NON_THEME = {"其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长", "年报增长", "一季报增长", "中报增长", "次新股"}

RE_LHASA = re.compile(r"(?:拉萨|东方财富证券.*拉萨)")
RE_INST = re.compile(r"机构专用")
RE_NORTH = re.compile(r"(?:沪股通专用|深股通专用)")
RE_QUANT = re.compile(r"(?:华鑫证券.*上海分公司|华鑫证券.*东大名路|中金.*上海|量化|摩根大通|瑞银证券.*花园石桥|高盛.*上海)")
RE_SURF_YZ = re.compile(r"(?:上塘路|财通.*杭州上塘|佛山|绿景路|季华|苏南|消闲派|宜昌沿江|宜昌珍珠|国泰君安.*宜昌|开源.*西安西大街|东方财富.*昌都)")
IS_GOOD_CODES = {"10430845", "10102873", "10046704", "10023415", "10026767", "10142874", "10122927", "10045035", "10025390", "10147201", "10318896", "10434470", "10634757"}
IS_BAD_CODES = {"10063083", "10000147202", "10050414", "10115140", "10023543", "10046458", "10046604", "10485003", "10028577", "10547746", "10456237", "10027014", "10143030", "10477736", "10023559", "10026729"}

TOX_RE = re.compile(r"(?:减持计划|股东减持|减持股份|立案调查|收到立案|退市风险|违法违规|业绩预亏|预亏)")
REG_RE = re.compile(r"(?:监管工作函|监管函|关注函|重点监控|停牌核查|严重异常波动)")
REG_EXC = re.compile(r"(?:回复|回函|延期|核查意见|复牌|募集资金|监事|独立董事|保荐)")
EARN_POS_RE = re.compile(r"(?:预增|扭亏|业绩快报|略增|减亏)")
EARN_NEG_RE = re.compile(r"(?:预减|首亏|续亏|增亏|略减|修正.*向下)")
CONT_RE = re.compile(r"(?:重大合同|中标|战略合作|签订.*合同|采购订单)")
MA_RE = re.compile(r"(?:重大资产重组|并购|发行股份购买|收购.*股权)")
MA_NEG_RE = re.compile(r"(?:终止|取消|撤回|放弃)")
BUYBACK_RE = re.compile(r"(?:回购股份|回购预案|回购方案|回购报告书|增持股份|增持计划)")
CSRC_TECH = {"C39", "I65", "C35", "C38", "C40", "C27", "M73"}


def load_zt_tape_20cm() -> dict:
    con = sqlite3.connect(f"file:{BASE}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    rows = con.execute(
        "SELECT trade_date, sec_code, sec_name, first_seal_time, seal_amount, board_count, open_board_count, plate_name "
        "FROM zt_micro_tape WHERE sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%'"
    ).fetchall()
    con.close()
    out, st_names = {}, defaultdict(list)
    for td, sc, nm, fst, sa, bc, obc, pl in rows:
        c6 = str(sc).zfill(6)
        fst_s = str(fst or "15:00:00").replace(":", "")[:6]
        hhmm = int(fst_s[:4]) if fst_s[:4].isdigit() else 1500
        mins = (hhmm // 100 - 9) * 60 + (hhmm % 100 - 30)
        if hhmm >= 1300:
            mins -= 90
        out[(str(td), c6)] = (hhmm, max(0, mins), float(sa or 0.0), int(bc or 1), int(obc or 0), str(pl or ""), str(nm or ""))
        if "ST" in str(nm or "") or "退" in str(nm or ""):
            st_names[c6].append(str(td))
    return out, {k: min(v) for k, v in st_names.items()}


def load_kpl_and_synergy(zt10_map: dict, all_dts: list) -> tuple[dict, dict, dict]:
    """Return stock_kpl[(dt,c6)], plate_10cm[(dt,plate)], and PIT 30d theme map for dormant 20cm peers."""
    stock_kpl = {}
    plate_stats = {}
    hist_themes = defaultdict(list)  # c6 -> list of (dt, sub_plate, main_plate)
    plate_elo = defaultdict(lambda: 100.0)
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}

    with open(f"{BASE}/data/kpl_plates_2018_2026_merged.jsonl", encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            obj = json.loads(ln)
            dt = obj.get("date", "")
            if dt < "2020-11-01" or dt > "2026-11-23":
                continue
            today_plates = []
            for pl in obj.get("plates", []):
                pname = str(pl.get("plate", ""))
                stks = pl.get("stocks", [])
                if not stks or pname in NON_THEME:
                    continue
                n10_zt, n10_yz, n20_c, c6s = 0, 0, 0, []
                sub_counts = defaultdict(int)
                for s in stks:
                    c6 = str(s[0]).strip()[:6].zfill(6)
                    sub_p = str(s[2]).strip() if len(s) > 2 else pname
                    c6s.append((c6, sub_p))
                    if c6.startswith(("00", "60")):
                        z10, y10, _ = zt10_map.get((dt, c6), (0, 0, 0))
                        n10_zt += z10
                        n10_yz += y10
                    elif c6.startswith(("30", "688", "689")):
                        n20_c += 1
                    if sub_p and sub_p not in NON_THEME:
                        sub_counts[sub_p] += 1
                sz = len(stks)
                elo_val = plate_elo[pname]
                today_plates.append(pname)
                if dt >= "2021-01-01":
                    plate_stats[(dt, pname)] = (sz, n10_zt, n10_yz, n20_c, elo_val)
                    for c6, sub_p in c6s:
                        if c6.startswith(("30", "688", "689")):
                            cur = stock_kpl.get((dt, c6))
                            if cur is None or sz > cur[1]:
                                stock_kpl[(dt, c6)] = (pname, sz, n10_zt, n10_yz, n20_c, elo_val, sub_p)
                for c6, sub_p in c6s:
                    if c6.startswith(("30", "688", "689")):
                        hist_themes[c6].append((dt, pname, sub_p))
            for pname in set(today_plates):
                plate_elo[pname] = plate_elo[pname] * 0.96 + 4.5
    return stock_kpl, plate_stats, dict(hist_themes)


def load_lhb_20cm() -> dict:
    lhb = pd.read_parquet(f"{BASE}/backtests_astock2/rd016_famous_youzi_seats_20261117/clean_lhb_5y.parquet")
    lhb = lhb[lhb["stock_code"].str.startswith(("30", "688", "689"))].copy()
    ths = pd.read_parquet(f"{BASE}/backtests_astock2/rd016_famous_youzi_seats_20261117/ths_pit_youzi_5y.parquet")
    ths = ths[ths["stock_code"].str.startswith(("30", "688", "689"))].copy()
    bayes = pd.read_parquet(f"{BASE}/backtests_astock2/rd016_famous_youzi_seats_20261117/bayes_seat_scores_d1_5y.parquet")
    bayes = bayes[bayes["stock_code"].str.startswith(("30", "688", "689"))].copy()

    b_map = {}
    for (dt, sc), g in bayes.groupby(["date", "stock_code"], sort=False):
        w = np.maximum(g["NET"].to_numpy(dtype=float), 1.0)
        b_map[(dt, sc)] = (float(np.sum(w * g["b_c"]) / np.sum(w)), float(np.sum(w * g["b_t2"]) / np.sum(w)))

    ths_map = {}
    for r in ths.itertuples(index=False):
        ths_map[(r.date, r.stock_code, int(r.is_three))] = (
            float(r.cap_inflow) if pd.notna(r.cap_inflow) else 0.0,
            float(r.org_inflow) if pd.notna(r.org_inflow) else 0.0,
            int(r.n_capital_icons or 0),
        )

    out = {}
    # Prefer is_three == 0 over 1
    lhb = lhb.sort_values(["date", "stock_code", "is_three"])
    for (dt, sc, is3), grp in lhb.groupby(["date", "stock_code", "is_three"], sort=False):
        if is3 == 1 and (dt, sc) in out:
            continue
        b_rows = grp[grp["side"] == "B"]
        s_rows = grp[grp["side"] == "S"]
        tot_b = float(b_rows["BUY"].sum())
        tot_s = float(s_rows["SELL"].sum())
        inst_rows = grp[grp["dept_code"] == "0"]
        inst_b = float(b_rows[b_rows["dept_code"] == "0"]["BUY"].sum())
        inst_s = float(s_rows[s_rows["dept_code"] == "0"]["SELL"].sum())
        inst_net = float(inst_rows["NET"].sum())
        inst_cnt_b = int((b_rows["dept_code"] == "0").sum())
        dnames_b = b_rows["dept_name"].astype(str).tolist()
        dcodes_b = set(b_rows[b_rows["NET"] > 0]["dept_code"].astype(str))
        lh_cnt = sum(1 for d in dnames_b if RE_LHASA.search(d) and "东亚" not in d)
        lh_buy = float(sum(v for d, v in zip(dnames_b, b_rows["BUY"]) if RE_LHASA.search(d) and "东亚" not in d))
        lh_net = float(sum(v for d, v in zip(dnames_b, b_rows["NET"]) if RE_LHASA.search(d) and "东亚" not in d))
        north_net = float(grp[grp["dept_name"].str.contains(RE_NORTH, na=False)]["NET"].sum())
        quant_cnt = sum(1 for d in dnames_b if RE_QUANT.search(d))
        surf_cnt = sum(1 for d in dnames_b if RE_SURF_YZ.search(d))
        has_good = int(bool(dcodes_b & IS_GOOD_CODES))
        has_bad = int(bool(dcodes_b & IS_BAD_CODES))
        tinfo = ths_map.get((dt, sc, int(is3)), (0.0, 0.0, 0))
        bc, bt2 = b_map.get((dt, sc), (0.0, 0.0))
        out[(dt, sc)] = {
            "lhb_has": 1, "lhb_is3": int(is3), "lhb_tot_b": tot_b, "lhb_tot_s": tot_s,
            "lhb_net": tot_b - tot_s, "lhb_inst_b": inst_b, "lhb_inst_s": inst_s,
            "lhb_inst_net": inst_net, "lhb_inst_cnt_b": inst_cnt_b,
            "lhb_lh_cnt": lh_cnt, "lhb_lh_share": (lh_buy / tot_b) if tot_b > 0 else 0.0,
            "lhb_lh_net_pos": int(lh_net > 0), "lhb_north_net": north_net,
            "lhb_quant_cnt": quant_cnt, "lhb_surf": int(surf_cnt > 0 or has_bad),
            "lhb_good_yz": has_good, "ths_cap_in": tinfo[0], "ths_icons": tinfo[2],
            "bayes_c": bc, "bayes_t2": bt2,
        }
    return out


def load_community_notices_csrc() -> dict:
    xq = defaultdict(list)
    seen = defaultdict(set)
    con_x = sqlite3.connect(f"file:{BASE}/data/xueqiu_guba_5y_pit.db?mode=ro", uri=True)
    for sym, pid, cts in con_x.execute(
        "SELECT symbol, post_id, created_time_str FROM xueqiu_posts "
        "WHERE created_time_str >= '2020-12-01' AND (symbol LIKE '30%' OR symbol LIKE '688%' OR symbol LIKE '689%')"
    ):
        c6 = str(sym)[:6].zfill(6)
        p = str(pid).replace("xq_", "")
        if p not in seen[c6] and cts:
            seen[c6].add(p)
            xq[c6].append(str(cts)[:19])
    # Guba daily counts by pub_time[:10] (post_count, read_sum)
    gb_rows = con_x.execute(
        "SELECT sec_code, substr(pub_time,1,10), COUNT(*), SUM(read_cnt) FROM guba_posts "
        "WHERE pub_time >= '2020-12-01' AND (sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%') "
        "GROUP BY sec_code, substr(pub_time,1,10)"
    ).fetchall()
    con_x.close()
    gb_map = {(str(sc).zfill(6), str(d)): (int(c), float(r or 0)) for sc, d, c, r in gb_rows}

    con_c = sqlite3.connect(f"file:{BASE}/data/astock_community_5y_pit.db?mode=ro", uri=True)
    for sym, pid, cts in con_c.execute(
        "SELECT symbol, post_id, pub_datetime_cst FROM community_posts "
        "WHERE source='xueqiu' AND pub_datetime_cst >= '2020-12-01' AND (symbol LIKE '30%' OR symbol LIKE '688%' OR symbol LIKE '689%')"
    ):
        c6 = str(sym)[:6].zfill(6)
        p = str(pid).replace("xq_", "")
        if p not in seen[c6] and cts:
            seen[c6].add(p)
            xq[c6].append(str(cts)[:19])
    con_c.close()
    xq_arr = {c6: sorted(v) for c6, v in xq.items()}

    # Notices: tox, reg, st_first_dt, earn_pos, contract, ma, buyback
    tox, reg, st_dts = defaultdict(list), defaultdict(list), defaultdict(list)
    cat_earn, cat_cont, cat_ma, cat_bb = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    rt = pd.read_parquet(f"{BASE}/data/pit_reg_tox_notices_5y_complete.parquet", columns=["sec_code", "pub_datetime_cst", "title"])
    rt["c6"] = rt["sec_code"].astype(str).str[:6].str.zfill(6)
    for r in rt[rt["c6"].str.startswith(("30", "688", "689"))].itertuples(index=False):
        ts, ti = str(r.pub_datetime_cst)[:19], str(r.title)
        if TOX_RE.search(ti): tox[r.c6].append(ts)
        if REG_RE.search(ti) and not REG_EXC.search(ti): reg[r.c6].append(ts)

    for zf in glob.glob(f"{BASE}/data/kpl/zdjk/*.json"):
        for it in json.load(open(zf, encoding="utf-8")).get("List", []):
            c6 = str(it[0]).zfill(6)
            if c6.startswith(("30", "688", "689")):
                reg[c6].append(str(it[2])[:10] + " 08:00:00")

    con_n = sqlite3.connect(f"file:{BASE}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for sc, sn, ti, at, ts in con_n.execute(
        "SELECT sec_code, sec_name, title, ann_type, pub_datetime_cst FROM notices "
        "WHERE sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%'"
    ):
        c6, ts_s, t_s, a_s = str(sc).zfill(6), str(ts)[:19], str(ti or ""), str(at or "")
        if "ST" in str(sn or "") or "退" in str(sn or ""):
            st_dts[c6].append(ts_s[:10])
        if TOX_RE.search(t_s): tox[c6].append(ts_s)
        if REG_RE.search(t_s) and not REG_EXC.search(t_s): reg[c6].append(ts_s)
        if (EARN_POS_RE.search(a_s) or EARN_POS_RE.search(t_s)) and not EARN_NEG_RE.search(a_s + t_s):
            cat_earn[c6].append(ts_s)
        if "重大合同" in a_s or CONT_RE.search(t_s):
            cat_cont[c6].append(ts_s)
        if ("重组" in a_s or "收购" in a_s or MA_RE.search(t_s)) and not MA_NEG_RE.search(t_s):
            cat_ma[c6].append(ts_s)
        if "回购" in a_s or "增持" in a_s or BUYBACK_RE.search(t_s):
            cat_bb[c6].append(ts_s)
    con_n.close()

    con_ir = sqlite3.connect(f"file:{BASE}/data/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
    ir_map = defaultdict(list)
    for sc, ts in con_ir.execute(
        "SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%'"
    ):
        ir_map[str(sc).zfill(6)].append(str(ts)[:19])
    con_ir.close()

    csrc_df = pd.read_csv(f"{BASE}/data/csrc_industry_pit_clean.csv", dtype=str).fillna("")
    csrc_map = defaultdict(list)
    for r in csrc_df[csrc_df["sec_code"].str.startswith(("30", "688", "689"))].itertuples(index=False):
        csrc_map[r.sec_code.zfill(6)].append((r.start_date[:10], r.end_date[:10], r.industry[:3]))

    def sort_map(m):
        return {k: sorted(set(v)) for k, v in m.items()}

    return {
        "xq": xq_arr, "gb": gb_map, "tox": sort_map(tox), "reg": sort_map(reg),
        "st_first": {k: min(v) for k, v in st_dts.items()},
        "cat_earn": sort_map(cat_earn), "cat_cont": sort_map(cat_cont),
        "cat_ma": sort_map(cat_ma), "cat_bb": sort_map(cat_bb),
        "ir": sort_map(ir_map), "csrc": dict(csrc_map),
    }
