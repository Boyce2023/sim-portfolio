#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 0: Build 100% leak-free, PIT-clean P1_S1_DeepOpen candidate dataset.
Fixes delisted/ST future-name leak (keeps all 37 delisted 20cm stocks causally),
adds strict is_dt (closed sealed 20cm limit-down) flags, leave-self-out peer open,
<09:00 Xueqiu/Guba/Cninfo events, and D1..D11 path columns for dynamic exit trees.
"""
import bisect, json, os, pickle, re, sqlite3, sys, time
from collections import defaultdict
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
PART2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
os.makedirs(OUT_DIR, exist_ok=True)

ST_ON_RE = re.compile(r"(?:^(?:\*?ST|S\*?ST)|(?:股票交易|股票)(?:被)?实施(?:退市|其他)风险警示|进入退市整理期|作出.*终止上市)")
ST_EXC_RE = re.compile(r"(?:可能被实施|不实施|未实施|免于实施|申请撤销|撤销.*风险警示)")
ST_REV_RE = re.compile(r"(?:撤销(?:退市|其他)风险警示|股票交易撤销.*风险警示)")
TOX_RE = re.compile(r"(?:减持计划|股东减持|减持股份|立案调查|收到立案|退市风险|违法违规|业绩预亏|预亏)")
REG_RE = re.compile(r"(?:监管工作函|监管函|关注函|重点监控|停牌核查|严重异常波动)")
REG_EXC = re.compile(r"(?:回复|回函|延期|核查意见|复牌|募集资金|监事|独立董事|保荐)")
EARN_POS_RE = re.compile(r"(?:预增|扭亏|业绩快报|略增|减亏)")
EARN_NEG_RE = re.compile(r"(?:预减|首亏|续亏|增亏|略减|修正.*向下|预亏)")
EARN_GEN_RE = re.compile(r"(?:业绩预告|业绩快报|年度报告|半年度报告|季度报告)")
CLARIFY_RE = re.compile(r"(?:澄清|风险提示|异常波动公告|股价异动)")
CONT_RE = re.compile(r"(?:重大合同|中标|战略合作|签订.*合同|采购订单)")
MA_RE = re.compile(r"(?:重大资产重组|并购|发行股份购买|收购.*股权)")
MA_NEG_RE = re.compile(r"(?:终止|取消|撤回|放弃)")
BUYBACK_RE = re.compile(r"(?:回购股份|回购预案|回购方案|回购报告书|增持股份|增持计划)")


def shift_cal(dt_s: str, days: int) -> str:
    return (datetime.strptime(dt_s, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def cnt_ts_win(ts_list: list, start_ts: str, end_ts: str) -> int:
    if not ts_list:
        return 0
    lo = bisect.bisect_left(ts_list, start_ts)
    hi = bisect.bisect_left(ts_list, end_ts)
    return max(0, hi - lo)


def build_true_pit_st_and_names(c6_set: set[str]) -> tuple[dict, dict, dict]:
    """Chronological ST status timeline (NO static sec_name leak!) + PIT name lookup."""
    events = defaultdict(list)  # c6 -> list of (ts, st_flag)
    zt_names = defaultdict(list)  # c6 -> list of (dt, sec_name)

    con_z = sqlite3.connect(f"file:{BASE}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    for td, sc, nm in con_z.execute(
        "SELECT trade_date, sec_code, sec_name FROM zt_micro_tape WHERE sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%'"
    ):
        c6 = str(sc).zfill(6)
        s = str(nm or "").strip()
        if not s:
            continue
        zt_names[c6].append((str(td), s))
        if c6 in c6_set:
            st_f = 1 if ("ST" in s or "退" in s) else 0
            events[c6].append((f"{td} 15:00:00", st_f))
    con_z.close()

    cninfo_title_names = defaultdict(list)
    cninfo_static_names = {}
    con_n = sqlite3.connect(f"file:{BASE}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for sc, sn, ti, ts in con_n.execute(
        "SELECT sec_code, sec_name, title, pub_datetime_cst FROM notices WHERE sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%'"
    ):
        c6 = str(sc).zfill(6)
        if sn:
            cninfo_static_names[c6] = str(sn).strip()
        if c6 not in c6_set:
            continue
        t = str(ti or "")
        t_s = str(ts)[:19]
        if ":" in t:
            pfx = t.split(":", 1)[0].strip()
            if 2 <= len(pfx) <= 10 and not pfx[0].isdigit():
                cninfo_title_names[c6].append((t_s[:10], pfx))
        if ST_REV_RE.search(t) and "不" not in t[:10]:
            events[c6].append((t_s, 0))
        elif ST_ON_RE.search(t) and not ST_EXC_RE.search(t):
            events[c6].append((t_s, 1))
    con_n.close()

    rt = pd.read_parquet(f"{BASE}/data/pit_reg_tox_notices_5y_complete.parquet", columns=["sec_code", "pub_datetime_cst", "title"])
    rt["c6"] = rt["sec_code"].astype(str).str[:6].str.zfill(6)
    for r in rt[rt["c6"].isin(c6_set)].itertuples(index=False):
        t = str(r.title or "")
        t_s = str(r.pub_datetime_cst)[:19]
        if ST_REV_RE.search(t):
            events[r.c6].append((t_s, 0))
        elif ST_ON_RE.search(t) and not ST_EXC_RE.search(t):
            events[r.c6].append((t_s, 1))

    st_timeline = {}
    for c6, evl in events.items():
        evl.sort(key=lambda x: x[0])
        st_timeline[c6] = ([x[0] for x in evl], [x[1] for x in evl])

    pit_name_map = {}
    for c6 in c6_set:
        arr = sorted(set(zt_names.get(c6, []) + cninfo_title_names.get(c6, [])))
        pit_name_map[c6] = (arr, cninfo_static_names.get(c6, c6))
    return st_timeline, pit_name_map


def is_st_at(st_timeline: dict, c6: str, cutoff_ts: str) -> int:
    tl = st_timeline.get(c6)
    if not tl:
        return 0
    ts_list, fl_list = tl
    idx = bisect.bisect_left(ts_list, cutoff_ts)
    if idx == 0:
        return 0
    return int(fl_list[idx - 1])


def get_pit_name(pit_name_map: dict, c6: str, dt: str) -> str:
    arr, fb = pit_name_map.get(c6, ([], c6))
    if not arr:
        return fb
    dts = [x[0] for x in arr]
    idx = bisect.bisect_right(dts, dt)
    return arr[idx - 1][1] if idx > 0 else arr[0][1]


def main():
    t0 = time.time()
    print("[1/4] Loading cache_20cm_panel.parquet & aux...")
    df = pd.read_parquet(f"{PART2_DIR}/cache_20cm_panel.parquet")
    aux = pickle.load(open(f"{PART2_DIR}/cache_20cm_aux.pkl", "rb"))
    mkt10 = aux["mkt10"]
    df["mkt10_dt_cnt"] = df["dt"].map({k: v["mkt10_dt_cnt"] for k, v in mkt10.items()}).fillna(0).astype(int)

    # Compute forward & lagged fields BEFORE filtering rows!
    g = df.groupby("c6", sort=False)
    df["low20_prev"] = g["low20"].shift(1)
    df["box20_prev"] = np.where(df["low20_prev"] > 0, df["high20_prev"] / df["low20_prev"] - 1.0, np.nan)
    df["prev_to"] = g["to"].shift(1)
    df["prev_vol_ratio5"] = g["vol_ratio5"].shift(1)

    # Exact open limit-up / limit-down & close limit-down (is_dt) flags on every row
    scale = np.where(df["close"] > 0, df["adj_close"] / df["close"], 1.0)
    df["zt_px_adj"] = df["zt_px"] * scale
    df["dt_px_adj"] = df["dt_px"] * scale
    df["open_is_dt"] = (df["prev_ac"] > 0) & (df["open"] <= df["dt_px"] + 0.011) & (df["o_pct"] <= -0.195)
    df["open_is_zt"] = (df["prev_ac"] > 0) & (df["open"] >= df["zt_px"] - 0.011) & (df["o_pct"] >= 0.195)
    df["sellable_strict"] = df["sellable_close"] & (~df["is_dt"])
    df["clv"] = np.where(df["ah"] > df["al"], (df["ac"] - df["al"]) / (df["ah"] - df["al"]), 0.5)

    for k in range(1, 12):
        df[f"f{k}_is_dt"] = g["is_dt"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_open_is_dt"] = g["open_is_dt"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_open_is_zt"] = g["open_is_zt"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_sellable_strict"] = g["sellable_strict"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_zt_px_adj"] = g["zt_px_adj"].shift(-k)
        df[f"f{k}_dt_px_adj"] = g["dt_px_adj"].shift(-k)

    # Compute true PIT ST timeline across ALL 20cm tickers (fixes mkt20_zt_cnt / mkt20_dt_cnt future ST leak too!)
    all_20cm_c6 = set(df["c6"].unique())
    st_timeline, pit_name_map = build_true_pit_st_and_names(all_20cm_c6)
    df_st_all = np.array([is_st_at(st_timeline, r.c6, f"{r.dt} 15:00:00") for r in df.itertuples(index=False)], dtype=np.int8)
    mkt20_zt_clean = df[df["is_zt"] & (df_st_all == 0)].groupby("dt").size().to_dict()
    mkt20_dt_clean = df[df["is_dt"] & (df_st_all == 0)].groupby("dt").size().to_dict()
    df["mkt20_zt_cnt"] = df["dt"].map(mkt20_zt_clean).fillna(0).astype(int)
    df["mkt20_dt_cnt"] = df["dt"].map(mkt20_dt_clean).fillna(0).astype(int)

    df["f1_abn_ret"] = g["abn_ret"].shift(-1).fillna(False).astype(bool)
    df["f1_clv"] = g["clv"].shift(-1)
    df["f1_body"] = np.where(df["f1_ao"] > 0, df["f1_ac"] / df["f1_ao"] - 1.0, np.nan)
    df["f1_lhb_has"] = g["lhb_has"].shift(-1).fillna(0).astype(int)
    df["f1_lhb_inst_net"] = g["lhb_inst_net"].shift(-1).fillna(0.0)
    df["f1_lhb_lh_cnt"] = g["lhb_lh_cnt"].shift(-1).fillna(0).astype(int)
    df["f1_zt_obc"] = g["zt_obc"].shift(-1).fillna(-1).astype(int)
    df["f1_vol_ratio5"] = g["vol_ratio5"].shift(-1)
    df["f1_kpl_elo"] = g["kpl_elo"].shift(-1).fillna(100.0)
    df["f1_mkt20_zt_cnt"] = df["f1_dt"].map(mkt20_zt_clean).fillna(0).astype(int)
    df["f1_mkt20_dt_cnt"] = df["f1_dt"].map(mkt20_dt_clean).fillna(0).astype(int)
    df["f1_mkt10_dt_cnt"] = g["mkt10_dt_cnt"].shift(-1).fillna(0).astype(int)
    df["f2_mkt10_0925_zt"] = g["f1_mkt10_0925_zt"].shift(-1).fillna(0).astype(int)

    # Market-wide 20cm 09:25 auction stats (f1_mkt20_0925_zt, and leave-self-out f1_mkt20_prev1b_open & kpl_peers_f1o_ex)
    mkt20_ozt = df.groupby("dt")["open_is_zt"].sum().to_dict()
    df["f1_mkt20_0925_zt"] = df["f1_dt"].map(mkt20_ozt).fillna(0).astype(int)
    df["f2_mkt20_0925_zt"] = df["f2_dt"].map(mkt20_ozt).fillna(0).astype(int)

    first_b = df[df["is_zt"] & (df["streak"] == 1) & (~df["is_yizi_zt"]) & df["f1_o_pct"].notna()]
    fb_sum = first_b.groupby("dt")["f1_o_pct"].agg(["sum", "count"]).to_dict("index")

    kpl_sub = df[(df["kpl_in"] == 1) & df["f1_o_pct"].notna()]
    kpl_sum = kpl_sub.groupby(["dt", "kpl_plate"])["f1_o_pct"].agg(["sum", "count"]).to_dict("index")

    # Base pre-filter (WITHOUT old is_st_pit!)
    cand = df[
        df["tradable"] & (df["close"] >= 2.0)
        & df["is_zt"] & (df["streak"] == 1) & (~df["is_yizi_zt"])
        & (df["amount"] >= 1e8)
        & df["f1_buyable"] & (~df["f1_abn_ret"]) & df["f1_o_pct"].between(-0.15, 0.00)
    ].copy().reset_index(drop=True)
    print(f"[2/4] Pre-ST/tox/reg P1 wide candidates: {len(cand)} (delisted={int((cand['dl']==1).sum())})")

    # Leave-self-out peer opens
    f1_20_1b_open = []
    kpl_peers_ex = []
    for r in cand.itertuples(index=False):
        fs = fb_sum.get(r.dt)
        if fs and fs["count"] > 1:
            f1_20_1b_open.append((fs["sum"] - r.f1_o_pct) / (fs["count"] - 1))
        else:
            f1_20_1b_open.append(np.nan)
        if r.kpl_in == 1:
            ks = kpl_sum.get((r.dt, r.kpl_plate))
            if ks and ks["count"] > 1:
                kpl_peers_ex.append((ks["sum"] - r.f1_o_pct) / (ks["count"] - 1))
            else:
                kpl_peers_ex.append(np.nan)
        else:
            kpl_peers_ex.append(np.nan)
    cand["f1_mkt20_prev1b_open"] = f1_20_1b_open
    cand["kpl_peers_f1o_ex"] = kpl_peers_ex
    cand["kpl_10_20_zt"] = cand["kpl_10zt"] + cand["kpl_20zt"]

    c6_set = set(cand["c6"].unique())
    print(f"[3/4] Reconstructing strict <09:00 PIT notices/Xueqiu/Guba/IR for {len(c6_set)} tickers...")

    # Query Xueqiu & Guba (< f1_dt 09:00:00) from BOTH DBs
    xq_posts = defaultdict(list)
    seen_xq = defaultdict(set)
    gb_posts = defaultdict(list)
    seen_gb = defaultdict(set)

    con_x = sqlite3.connect(f"file:{BASE}/data/xueqiu_guba_5y_pit.db?mode=ro", uri=True)
    ph = ",".join("?" * len(c6_set))
    c6_list = sorted(c6_set)
    for sym, pid, cts in con_x.execute(f"SELECT symbol, post_id, created_time_str FROM xueqiu_posts WHERE substr(symbol,1,6) IN ({ph}) AND created_time_str >= '2020-12-01'", c6_list):
        c6 = str(sym)[:6].zfill(6)
        p = str(pid).replace("xq_", "")
        if p not in seen_xq[c6] and cts:
            seen_xq[c6].add(p)
            xq_posts[c6].append(str(cts)[:19])
    for sc, pid, pt in con_x.execute(f"SELECT sec_code, post_id, pub_time FROM guba_posts WHERE sec_code IN ({ph}) AND pub_time >= '2020-12-01'", c6_list):
        c6 = str(sc).zfill(6)
        p = str(pid)
        if p not in seen_gb[c6] and pt:
            seen_gb[c6].add(p)
            gb_posts[c6].append(str(pt)[:19])
    con_x.close()

    con_c = sqlite3.connect(f"file:{BASE}/data/astock_community_5y_pit.db?mode=ro", uri=True)
    for sym, src, pid, cts in con_c.execute(f"SELECT symbol, source, post_id, pub_datetime_cst FROM community_posts WHERE substr(symbol,1,6) IN ({ph}) AND pub_datetime_cst >= '2020-12-01'", c6_list):
        c6 = str(sym)[:6].zfill(6)
        p = str(pid).replace("xq_", "")
        if src == "xueqiu":
            if p not in seen_xq[c6] and cts:
                seen_xq[c6].add(p)
                xq_posts[c6].append(str(cts)[:19])
        elif src in ("eastmoney_guba", "guba"):
            if p not in seen_gb[c6] and cts:
                seen_gb[c6].add(p)
                gb_posts[c6].append(str(cts)[:19])
    con_c.close()
    xq_sorted = {k: sorted(v) for k, v in xq_posts.items()}
    gb_sorted = {k: sorted(v) for k, v in gb_posts.items()}

    # Query Cninfo notices & IR strictly < f1_dt 09:00:00
    tox_m, reg_m = defaultdict(list), defaultdict(list)
    ep_m, en_m, eg_m, cl_m, co_m, ma_m, bb_m = [defaultdict(list) for _ in range(7)]
    rt = pd.read_parquet(f"{BASE}/data/pit_reg_tox_notices_5y_complete.parquet", columns=["sec_code", "pub_datetime_cst", "title"])
    rt["c6"] = rt["sec_code"].astype(str).str[:6].str.zfill(6)
    for r in rt[rt["c6"].isin(c6_set)].itertuples(index=False):
        ts, ti = str(r.pub_datetime_cst)[:19], str(r.title or "")
        if TOX_RE.search(ti): tox_m[r.c6].append(ts)
        if REG_RE.search(ti) and not REG_EXC.search(ti): reg_m[r.c6].append(ts)
    import glob
    for zf in glob.glob(f"{BASE}/data/kpl/zdjk/*.json"):
        for it in json.load(open(zf, encoding="utf-8")).get("List", []):
            c6 = str(it[0]).zfill(6)
            if c6 in c6_set:
                reg_m[c6].append(str(it[2])[:10] + " 08:00:00")

    con_n = sqlite3.connect(f"file:{BASE}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for sc, ti, at, ts in con_n.execute(f"SELECT sec_code, title, ann_type, pub_datetime_cst FROM notices WHERE sec_code IN ({ph})", c6_list):
        c6, ts_s, t_s, a_s = str(sc).zfill(6), str(ts)[:19], str(ti or ""), str(at or "")
        if TOX_RE.search(t_s): tox_m[c6].append(ts_s)
        if REG_RE.search(t_s) and not REG_EXC.search(t_s): reg_m[c6].append(ts_s)
        if (EARN_POS_RE.search(a_s) or EARN_POS_RE.search(t_s)) and not EARN_NEG_RE.search(a_s + t_s):
            ep_m[c6].append(ts_s)
        if EARN_NEG_RE.search(a_s + t_s):
            en_m[c6].append(ts_s)
        if EARN_GEN_RE.search(a_s + t_s) or EARN_POS_RE.search(a_s + t_s) or EARN_NEG_RE.search(a_s + t_s):
            eg_m[c6].append(ts_s)
        if CLARIFY_RE.search(t_s):
            cl_m[c6].append(ts_s)
        if "重大合同" in a_s or CONT_RE.search(t_s):
            co_m[c6].append(ts_s)
        if ("重组" in a_s or "收购" in a_s or MA_RE.search(t_s)) and not MA_NEG_RE.search(t_s):
            ma_m[c6].append(ts_s)
        if "回购" in a_s or "增持" in a_s or BUYBACK_RE.search(t_s):
            bb_m[c6].append(ts_s)
    con_n.close()

    con_ir = sqlite3.connect(f"file:{BASE}/data/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
    ir_m = defaultdict(list)
    for sc, ts in con_ir.execute(f"SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE sec_code IN ({ph})", c6_list):
        ir_m[str(sc).zfill(6)].append(str(ts)[:19])
    con_ir.close()

    for m in (tox_m, reg_m, ep_m, en_m, eg_m, cl_m, co_m, ma_m, bb_m, ir_m):
        for k in list(m.keys()):
            m[k] = sorted(set(m[k]))

    n = len(cand)
    names = []
    st_t0 = np.zeros(n, dtype=np.int8)
    st_f1 = np.zeros(n, dtype=np.int8)
    tox_0900 = np.zeros(n, dtype=np.int8)
    reg_0900 = np.zeros(n, dtype=np.int8)
    xq_0900 = np.zeros(n, dtype=np.int16)
    xq_post_0900 = np.zeros(n, dtype=np.int16)
    xq_3d_0900 = np.zeros(n, dtype=np.int16)
    gb_0900 = np.zeros(n, dtype=np.int16)
    gb_post_0900 = np.zeros(n, dtype=np.int16)
    cat_ep, cat_en, cat_ea, cat_cl, cat_co, cat_ma2, cat_bb2 = [np.zeros(n, dtype=np.int8) for _ in range(7)]
    ir_10_0900 = np.zeros(n, dtype=np.int16)
    ir_30_0900 = np.zeros(n, dtype=np.int16)

    for i, r in enumerate(cand.itertuples(index=False)):
        c6, dt, f1dt = r.c6, r.dt, r.f1_dt or r.dt
        names.append(get_pit_name(pit_name_map, c6, dt))
        t1_cut = f"{f1dt} 09:00:00"
        st_t0[i] = is_st_at(st_timeline, c6, f"{dt} 15:00:00")
        st_f1[i] = is_st_at(st_timeline, c6, t1_cut)
        d2, d3, d5, d10, d30, d90 = shift_cal(dt, -2), shift_cal(dt, -3), shift_cal(dt, -5), shift_cal(dt, -10), shift_cal(dt, -30), shift_cal(dt, -90)
        if cnt_ts_win(tox_m.get(c6), f"{d90} 00:00:00", t1_cut) > 0: tox_0900[i] = 1
        if cnt_ts_win(reg_m.get(c6), f"{d10} 00:00:00", t1_cut) > 0: reg_0900[i] = 1
        xl = xq_sorted.get(c6)
        if xl:
            xq_0900[i] = cnt_ts_win(xl, f"{dt} 00:00:00", t1_cut)
            xq_post_0900[i] = cnt_ts_win(xl, f"{dt} 15:00:00", t1_cut)
            xq_3d_0900[i] = cnt_ts_win(xl, f"{d2} 00:00:00", t1_cut)
        gl = gb_sorted.get(c6)
        if gl:
            gb_0900[i] = cnt_ts_win(gl, f"{dt} 00:00:00", t1_cut)
            gb_post_0900[i] = cnt_ts_win(gl, f"{dt} 15:00:00", t1_cut)
        if cnt_ts_win(ep_m.get(c6), f"{d3} 00:00:00", t1_cut) > 0: cat_ep[i] = 1
        if cnt_ts_win(en_m.get(c6), f"{d3} 00:00:00", t1_cut) > 0: cat_en[i] = 1
        if cnt_ts_win(eg_m.get(c6), f"{d3} 00:00:00", t1_cut) > 0: cat_ea[i] = 1
        if cnt_ts_win(cl_m.get(c6), f"{d3} 00:00:00", t1_cut) > 0: cat_cl[i] = 1
        if cnt_ts_win(co_m.get(c6), f"{d3} 00:00:00", t1_cut) > 0: cat_co[i] = 1
        if cnt_ts_win(ma_m.get(c6), f"{d5} 00:00:00", t1_cut) > 0: cat_ma2[i] = 1
        if cnt_ts_win(bb_m.get(c6), f"{d5} 00:00:00", t1_cut) > 0: cat_bb2[i] = 1
        irl = ir_m.get(c6)
        if irl:
            ir_10_0900[i] = cnt_ts_win(irl, f"{d10} 00:00:00", t1_cut)
            ir_30_0900[i] = cnt_ts_win(irl, f"{d30} 00:00:00", t1_cut)

    cand["name"] = names
    cand["is_st_true_pit"] = st_t0
    cand["f1_is_st_true_pit"] = st_f1
    cand["tox_90d_0900"] = tox_0900
    cand["reg_10d_0900"] = reg_0900
    cand["xq_t1_0900"] = xq_0900
    cand["xq_post_0900"] = xq_post_0900
    cand["xq_3d_0900"] = xq_3d_0900
    cand["gb_t1_0900"] = gb_0900
    cand["gb_post_0900"] = gb_post_0900
    cand["cat_earn_pos_3d"] = cat_ep
    cand["cat_earn_neg_3d"] = cat_en
    cand["cat_earn_any_3d"] = cat_ea
    cand["cat_clarify_3d"] = cat_cl
    cand["cat_cont_3d_0900"] = cat_co
    cand["cat_ma_5d_0900"] = cat_ma2
    cand["cat_bb_5d_0900"] = cat_bb2
    cand["ir_10d_0900"] = ir_10_0900
    cand["ir_30d_0900"] = ir_30_0900
    cand["f1_weekday"] = pd.to_datetime(cand["f1_dt"]).dt.dayofweek.fillna(-1).astype(int)
    cand["f1_month"] = cand["f1_dt"].astype(str).str.slice(5, 7)
    cand["is_chinext"] = cand["c6"].str.startswith("30").astype(np.int8)

    # Clean final pool (keeping clean PIT non-ST, non-tox, non-reg!)
    clean = cand[(cand["is_st_true_pit"] == 0) & (cand["f1_is_st_true_pit"] == 0) & (cand["tox_90d_0900"] == 0) & (cand["reg_10d_0900"] == 0)].copy().reset_index(drop=True)
    # Also save pre-filter dataset in case we check reg_10d marginal effect
    cand.to_parquet(f"{OUT_DIR}/p1_prefilter_candidates.parquet", index=False)
    clean.to_parquet(f"{OUT_DIR}/p1_clean_candidates.parquet", index=False)

    meta = {
        "prefilter_rows": int(len(cand)),
        "clean_rows": int(len(clean)),
        "clean_is_rows": int((clean["f1_dt"] <= "2024-08-31").sum()),
        "clean_oos_rows": int((clean["f1_dt"] >= "2024-09-01").sum()),
        "delisted_prefilter": int((cand["dl"] == 1).sum()),
        "delisted_clean": int((clean["dl"] == 1).sum()),
        "delisted_clean_tickers": sorted(clean[clean["dl"] == 1]["c6"].unique().tolist()),
        "old_st_false_positives_rescued": int(((clean["is_st_pit"] == 1) & (clean["is_st_true_pit"] == 0)).sum()),
        "elapsed_sec": round(time.time() - t0, 2),
    }
    with open(f"{OUT_DIR}/step0_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("[4/4] DONE:", json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
