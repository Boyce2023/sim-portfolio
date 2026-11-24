#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Build 100% Zero-Lookahead PIT Dataset for 20cm Beta-Resonance V1.0:
- Fixes static sec_name lookahead leak on delisted/ST stocks via historical notice title prefixes + zt_micro_tape.
- Recomputes exact forward paths & T+1 open buyability on all 37 delisted + active 20cm stocks.
- Attaches PIT Top10 lockup (NOTICE_DATE < dt), KPL T-60~T-1 dynamic Elo & T0 theme ZT, LHB, CNINFO catalysts/tox, IR QA, and zero-leak Community posts.
"""
import bisect, datetime, glob, json, os, re, sqlite3, time, pickle
from collections import defaultdict
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
P1_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part1_beta_waves"
P2_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_beta_scorecard_exit"
os.makedirs(OUT_DIR, exist_ok=True)

NON_THEME = {
    "其他", "公告", "ST板块", "科创板", "三季报增长", "业绩增长", "半年报增长",
    "年报增长", "一季报增长", "中报增长", "次新股", "新股与次新股", "北交所",
    "预盈预增", "回购", "增持", "高送转", "摘帽",
}
CSRC_TECH_RE = re.compile(r"(?:计算机|软件|电子|通信|仪器|专用设备|通用设备|电气|医药|互联网)")
TOX_RE = re.compile(r"(?:减持计划|股东减持|减持股份|拟减持|立案调查|收到立案|退市风险|违法违规|终止上市|资金占用)")
REG_RE = re.compile(r"(?:监管工作函|监管函|关注函|问询函|重点监控|停牌核查|严重异常波动)")
REG_EXC = re.compile(r"(?:回复|回函|延期|核查意见|复牌|募集资金|监事|独立董事|保荐|审计)")
EARN_POS_RE = re.compile(r"(?:预增|扭亏|略增|减亏)")
EARN_NEG_RE = re.compile(r"(?:预减|首亏|续亏|增亏|略减|预亏)")
CONT_RE = re.compile(r"(?:重大合同|中标|战略合作|签订.*合同|采购订单)")
MA_RE = re.compile(r"(?:重大资产重组|发行股份购买|收购.*股权)")
MA_NEG_RE = re.compile(r"(?:终止|取消|撤回|放弃)")
BB_RE = re.compile(r"(?:回购股份|回购预案|回购方案|回购报告书|增持股份|增持计划)")
RE_LHASA = re.compile(r"(?:拉萨|东方财富证券.*拉萨)")
RE_QUANT = re.compile(r"(?:华鑫证券.*上海分公司|华鑫证券.*东大名路|中金.*上海|量化|摩根大通|瑞银证券.*花园石桥|高盛.*上海)")
RE_SURF = re.compile(r"(?:上塘路|财通.*杭州上塘|佛山|绿景路|季华|苏南|消闲派|宜昌沿江|宜昌珍珠|国泰君安.*宜昌|开源.*西安西大街|东方财富.*昌都)")
IS_GOOD_CODES = {"10430845", "10102873", "10046704", "10023415", "10026767", "10142874", "10122927", "10045035", "10025390", "10147201", "10318896", "10434470", "10634757"}
IS_BAD_CODES = {"10063083", "10000147202", "10050414", "10115140", "10023543", "10046458", "10046604", "10485003", "10028577", "10547746", "10456237", "10027014", "10143030", "10477736", "10023559", "10026729"}
NON_NAME_PREF = re.compile(r"^(?:\d{6}|深交所|上交所|北交所|证监会|关于|独立董事|监事会|董事会|股东大会|保荐|中信|华泰|国泰|海通|广发|招商|中金|申万|兴业|天风|光大|东方|安信|民生|国信|东吴|长江|方正|会计师|律师|评估)")


def extract_title_name(ttl: str) -> str:
    if not ttl or (":" not in ttl and "：" not in ttl):
        return ""
    pref = ttl.replace("：", ":").split(":", 1)[0].strip()
    if not (2 <= len(pref) <= 9) or NON_NAME_PREF.search(pref):
        return ""
    return pref


def build_zero_leak_st_map() -> dict:
    """Reconstruct pure PIT (date, is_st, name) events without static sec_name backfill."""
    obs = defaultdict(list)
    con_z = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    for dt, sc, nm in con_z.execute(
        "SELECT trade_date, sec_code, sec_name FROM zt_micro_tape "
        "WHERE sec_name IS NOT NULL AND (sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%')"
    ):
        c6 = str(sc).strip()[:6].zfill(6)
        nm_s = str(nm).strip()
        if nm_s:
            obs[c6].append((str(dt)[:10], int("ST" in nm_s or "退" in nm_s), nm_s))
    con_z.close()

    con_n = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for dt, sc, ttl in con_n.execute(
        "SELECT trade_date_avail, sec_code, title FROM notices "
        "WHERE sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%'"
    ):
        c6 = str(sc).strip()[:6].zfill(6)
        dt_s = str(dt)[:10]
        t_s = str(ttl or "")
        pref = extract_title_name(t_s)
        if pref:
            is_st = int(pref.startswith(("ST", "*ST", "S*ST")) or pref.endswith("退") or "退市" in pref)
            obs[c6].append((dt_s, is_st, pref))
        if re.search(r"被实施.*风险警示|股票交易实施.*风险警示|进入退市整理期", t_s) and not re.search(r"可能|申请|撤销|进展", t_s):
            obs[c6].append((dt_s, 1, pref or "ST_RISK"))
        elif re.search(r"撤销.*风险警示", t_s) and not re.search(r"可能|申请", t_s):
            obs[c6].append((dt_s, 0, pref or "UNST"))
    con_n.close()

    tox = pd.read_parquet(f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet", columns=["sec_code", "pub_datetime_cst", "title"])
    tox = tox[tox["sec_code"].astype(str).str.startswith(("30", "688", "689"))]
    for sc, pts, ttl in zip(tox["sec_code"], tox["pub_datetime_cst"], tox["title"]):
        c6 = str(sc).strip()[:6].zfill(6)
        pref = extract_title_name(str(ttl or ""))
        if pref:
            is_st = int(pref.startswith(("ST", "*ST", "S*ST")) or pref.endswith("退") or "退市" in pref)
            obs[c6].append((str(pts)[:10], is_st, pref))

    out = {}
    for c6, evs in obs.items():
        evs.sort(key=lambda x: x[0])
        out[c6] = evs
    return out


def main():
    t0 = time.time()
    print("[1/5] Loading panel_20cm & market_daily & rebuilding zero-leak PIT ST...")
    mkt = pd.read_parquet(f"{P1_DIR}/market_daily.parquet").sort_values("dt").reset_index(drop=True)
    p20 = pd.read_parquet(f"{P1_DIR}/panel_20cm.parquet").sort_values(["c6", "dt"]).reset_index(drop=True)

    st_evs = build_zero_leak_st_map()
    csrc_df = pd.read_csv(f"{SIM}/data/csrc_industry_pit_clean.csv", dtype=str).fillna("")
    static_nm = dict(zip(csrc_df["sec_code"].str[:6], csrc_df["code_name"]))

    st_pit_arr = np.zeros(len(p20), dtype=np.int8)
    nm_pit_arr = [""] * len(p20)
    idx_pos = 0
    for c6, grp_dts in p20.groupby("c6", sort=False)["dt"]:
        evs = st_evs.get(c6)
        fb = static_nm.get(c6, c6)
        if not evs:
            for d in grp_dts:
                st_pit_arr[idx_pos] = 0
                nm_pit_arr[idx_pos] = fb
                idx_pos += 1
        else:
            edts = [e[0] for e in evs]
            for d in grp_dts:
                pos = bisect.bisect_right(edts, d) - 1
                if pos >= 0:
                    st_pit_arr[idx_pos] = evs[pos][1]
                    nm_pit_arr[idx_pos] = evs[pos][2]
                else:
                    st_pit_arr[idx_pos] = 0
                    nm_pit_arr[idx_pos] = fb
                idx_pos += 1

    old_st = p20["is_st_pit"].to_numpy(dtype=bool)
    p20["is_st_pit"] = st_pit_arr.astype(bool)
    p20["sec_name_pit"] = nm_pit_arr
    p20["is_clean_v1"] = (~p20["is_recent_ipo_10d"]) & (~p20["is_st_pit"]) & (p20["ret"].abs() <= 0.22) & (p20["volume"] > 0)

    dl_old = p20[(p20["_act"] == 0) & (p20["dt"] >= "2021-01-04") & old_st].shape[0]
    dl_new = p20[(p20["_act"] == 0) & (p20["dt"] >= "2021-01-04") & p20["is_st_pit"]].shape[0]
    print(f"  Delisted ST rows >=2021: old={dl_old:,} -> true PIT={dl_new:,} (recovered {dl_old - dl_new:,} clean pre-ST stock-days!)")

    print("[2/5] Computing rolling features & exporting clean OHLC stock paths...")
    g = p20.groupby("c6", sort=False)
    p20["ma5_pre"] = g["adj_close"].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
    p20["ma5_t"] = g["adj_close"].transform(lambda s: s.rolling(5, min_periods=3).mean())
    p20["ma20_pre"] = g["adj_close"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    p20["ma60_pre"] = g["adj_close"].transform(lambda s: s.shift(1).rolling(60, min_periods=20).mean())
    p20["ma20_pre5"] = g["ma20_pre"].shift(5)
    p20["high20_pre"] = g["adj_high"].transform(lambda s: s.shift(1).rolling(20, min_periods=5).max())
    p20["low20_pre"] = g["adj_low"].transform(lambda s: s.shift(1).rolling(20, min_periods=5).min())
    p20["high60_pre"] = g["adj_high"].transform(lambda s: s.shift(1).rolling(60, min_periods=15).max())
    p20["low60_pre"] = g["adj_low"].transform(lambda s: s.shift(1).rolling(60, min_periods=15).min())
    p20["amt_ma5_pre"] = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
    p20["amt_ma20_pre"] = g["amount"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    p20["std5_pre"] = g["ret"].transform(lambda s: s.shift(1).rolling(5, min_periods=4).std())
    p20["std20_pre"] = g["ret"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).std())
    p20["prev_ret5"] = p20["prev_adj_c"] / g["adj_close"].shift(6) - 1.0
    p20["prev_ret10"] = p20["prev_adj_c"] / g["adj_close"].shift(11) - 1.0
    p20["prev_ret20"] = p20["prev_adj_c"] / g["adj_close"].shift(21) - 1.0

    big7_flag = ((p20["ret"] >= 0.07) & p20["is_clean_v1"]).astype(float)
    p20["big7_cnt_20d_pre"] = big7_flag.groupby(p20["c6"], sort=False).transform(lambda s: s.shift(1).rolling(20, min_periods=1).sum())
    p20["big7_cnt_60d_pre"] = big7_flag.groupby(p20["c6"], sort=False).transform(lambda s: s.shift(1).rolling(60, min_periods=1).sum())
    zt_flag = (p20["is_zt"] & p20["is_clean_v1"]).astype(float)
    p20["zt_cnt_60d_pre"] = zt_flag.groupby(p20["c6"], sort=False).transform(lambda s: s.shift(1).rolling(60, min_periods=1).sum())

    p20["open_gap"] = p20["adj_open"] / p20["prev_adj_c"] - 1.0
    p20["intraday_ret"] = p20["adj_close"] / p20["adj_open"] - 1.0
    hl_rng = np.maximum(p20["high"] - p20["low"], 1e-4)
    p20["clv"] = (p20["close"] - p20["low"]) / hl_rng
    p20["upper_shadow_pct"] = (p20["high"] - np.maximum(p20["open"], p20["close"])) / p20["prev_c_adj"]
    p20["turn_pct"] = p20["turn"] * 100.0
    p20["amt_yi"] = p20["amount"] / 1e8
    p20["amt_ratio_5"] = p20["amount"] / np.maximum(p20["amt_ma5_pre"], 1e4)
    p20["vol_contraction_5_20"] = p20["std5_pre"] / np.maximum(p20["std20_pre"], 1e-5)
    p20["pos20_pre"] = (p20["prev_adj_c"] - p20["low20_pre"]) / np.maximum(p20["high20_pre"] - p20["low20_pre"], 1e-4)
    p20["pos60_pre"] = (p20["prev_adj_c"] - p20["low60_pre"]) / np.maximum(p20["high60_pre"] - p20["low60_pre"], 1e-4)
    p20["dist_ma20_pre"] = p20["prev_adj_c"] / p20["ma20_pre"] - 1.0
    p20["dist_ma60_pre"] = p20["prev_adj_c"] / p20["ma60_pre"] - 1.0
    p20["dd_20h_pre"] = p20["prev_adj_c"] / p20["high20_pre"] - 1.0
    p20["dd_60h_pre"] = p20["prev_adj_c"] / p20["high60_pre"] - 1.0
    p20["is_first_bigup_20d"] = (p20["big7_cnt_20d_pre"] == 0).astype(float)
    p20["is_first_bigup_60d"] = (p20["big7_cnt_60d_pre"] == 0).astype(float)
    p20["is_star_f"] = p20["is_star"].astype(float)
    p20["is_chinext"] = (~p20["is_star"]).astype(float)
    p20["list_age_capped"] = np.where(p20["first_dt"] >= "2020-08-01", p20["list_day_idx"], 1500.0)

    # Recompute exact buyable_B & t1_open_ret cleanly for ALL rows (including newly recovered delisted pre-ST rows!)
    all_dts = mkt["dt"].tolist()
    dt_to_gidx = {d: i for i, d in enumerate(all_dts)}
    p20["gidx"] = p20["dt"].map(dt_to_gidx)
    p20["next_gidx"] = g["gidx"].shift(-1)
    p20["next_dt"] = g["dt"].shift(-1).fillna("")
    p20["next_vol"] = g["volume"].shift(-1).fillna(0.0)
    p20["next_op"] = g["open"].shift(-1).fillna(0.0)
    p20["next_zt"] = g["zt_px"].shift(-1).fillna(999999.0)
    p20["next_ao"] = g["adj_open"].shift(-1)
    p20["t1_dt"] = np.where(p20["next_gidx"] == p20["gidx"] + 1, p20["next_dt"], "")
    p20["buyable_B"] = (p20["t1_dt"] != "") & (p20["next_vol"] > 0) & (p20["next_op"] < p20["next_zt"] - 0.011)
    p20["t1_adj_open"] = np.where(p20["buyable_B"], p20["next_ao"], np.nan)
    p20["t1_open_gap"] = p20["t1_adj_open"] / p20["adj_close"] - 1.0
    p20["t1_open_minus_t0"] = p20["t1_open_gap"] - p20["ret"]

    # Build fast stock paths dict for exit tree simulation
    paths = {}
    for c6, gs in p20[p20["gidx"].notna()].groupby("c6", sort=False):
        gv = gs["gidx"].to_numpy(dtype=np.int32)
        paths[c6] = {
            "gidx": gv, "dt": gs["dt"].to_numpy(),
            "ao": gs["adj_open"].to_numpy(dtype=np.float64), "ah": gs["adj_high"].to_numpy(dtype=np.float64),
            "al": gs["adj_low"].to_numpy(dtype=np.float64), "ac": gs["adj_close"].to_numpy(dtype=np.float64),
            "op": gs["open"].to_numpy(dtype=np.float64), "cl": gs["close"].to_numpy(dtype=np.float64),
            "zt_px": gs["zt_px"].to_numpy(dtype=np.float64), "dt_px": gs["dt_px"].to_numpy(dtype=np.float64),
            "adjf": gs["adjf"].to_numpy(dtype=np.float64), "vol": gs["volume"].to_numpy(dtype=np.float64),
            "is_dt": gs["is_dt"].to_numpy(dtype=bool), "is_zt": gs["is_zt"].to_numpy(dtype=bool),
            "ret": gs["ret"].to_numpy(dtype=np.float64), "ma5": gs["ma5_t"].to_numpy(dtype=np.float64),
            "gidx_pos": {int(v): idx for idx, v in enumerate(gv)},
        }
    with open(f"{OUT_DIR}/v1_stock_paths.pkl", "wb") as f:
        pickle.dump({"paths": paths, "all_dts": all_dts, "dt_to_gidx": dt_to_gidx}, f)

    print("[3/5] Filtering Beta-day 20cm [5%, 15%) candidates & attaching PIT Top10 lockup...")
    beta_dts = set(mkt[(mkt["dt"] >= "2021-01-04") & (mkt["ew_ret_all"] >= 0.02) & (mkt["up_ratio_all"] >= 0.80)]["dt"])
    cand = p20[p20["dt"].isin(beta_dts) & p20["is_clean_v1"] & (p20["ret"] >= 0.05) & (p20["ret"] < 0.15) & (p20["amt_yi"] >= 1.0)].copy().reset_index(drop=True)
    print(f"  Clean Beta-day [5%,15%) amt>=1e8 rows={len(cand):,}, days={cand['dt'].nunique()}, delisted_rows={(cand['_act']==0).sum()}")

    # PIT Top10 lockup (NOTICE_DATE < dt)
    t10 = json.load(open(f"{P2_DIR}/pit_top10_20cm_summary.json", encoding="utf-8"))
    n = len(cand)
    lock_top10 = np.full(n, np.nan)
    lock_big5 = np.full(n, np.nan)
    for idx, (dt, c6) in enumerate(zip(cand["dt"], cand["c6"])):
        recs = t10.get(c6)
        if not recs:
            continue
        best_ed, b_l10, b_b5 = "", np.nan, np.nan
        for nd, ed, l10, b5 in recs:
            if nd < dt and ed >= best_ed:
                best_ed, b_l10, b_b5 = ed, l10, b5
        lock_top10[idx] = b_l10
        lock_big5[idx] = b_b5
    cand["lock_top10"] = lock_top10
    cand["lock_big5"] = lock_big5
    cand["has_top10_pit"] = np.isfinite(lock_top10).astype(float)
    lock_fill = np.where(np.isnan(lock_top10), 40.0, np.clip(lock_top10, 0.0, 95.0))
    cand["lock_top10_fill"] = lock_fill
    cand["real_free_mcap"] = cand["circ_mcap"] * (1.0 - lock_fill / 100.0)
    cand["real_to"] = cand["turn_pct"] / (1.0 - lock_fill / 100.0)

    print("[4/5] Attaching PIT KPL historical themes + Dynamic Elo, LHB, CNINFO, IR QA & Community...")
    # 10cm + 20cm ZT maps for needed dates (beta_dts)
    needed_dts = set(beta_dts)
    con_z = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    zt10_by_dt = defaultdict(set)
    for dt_s, sc in con_z.execute("SELECT trade_date, sec_code FROM zt_micro_tape WHERE trade_date >= '2021-01-01'"):
        c6 = str(sc)[:6].zfill(6)
        if not c6.startswith(("30", "688", "689")) and dt_s in needed_dts:
            zt10_by_dt[dt_s].add(c6)
    con_z.close()
    zt20_by_dt = defaultdict(set)
    for dt_s, c6 in zip(p20.loc[p20["dt"].isin(needed_dts) & p20["is_zt"], "dt"], p20.loc[p20["dt"].isin(needed_dts) & p20["is_zt"], "c6"]):
        zt20_by_dt[dt_s].add(c6)

    # Chronological KPL processing -> T-60/T-180 stock themes + causal Dynamic Elo (log1p ZT strength) + T0 KPL stats
    plate_elo = defaultdict(lambda: 0.0)
    hist_themes = defaultdict(list)  # c6 -> list of (dt, pname)
    plate_t0_stats = {}  # (dt, pname) -> (n10, n20, elo_pre)
    kpl_t0_stock = {}    # (dt, c6) -> (rk, n10, n20, elo_pre, pname)
    kpl_t0_max_pzt = {}
    all_kpl_objs = []
    with open(f"{SIM}/data/kpl_plates_2018_2026_merged.jsonl", encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                obj = json.loads(ln)
                if obj.get("date", "") >= "2020-08-01":
                    all_kpl_objs.append(obj)
    all_kpl_objs.sort(key=lambda x: x.get("date", ""))
    # Also load all-A ZT for non-beta dates so Elo accumulates accurately every trading day!
    all_zt_by_dt = defaultdict(set)
    con_z2 = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    for dt_s, sc in con_z2.execute("SELECT trade_date, sec_code FROM zt_micro_tape WHERE trade_date >= '2020-08-01'"):
        all_zt_by_dt[dt_s].add(str(sc)[:6].zfill(6))
    con_z2.close()
    for dt_s, c6 in zip(p20.loc[p20["is_zt"], "dt"], p20.loc[p20["is_zt"], "c6"]):
        all_zt_by_dt[dt_s].add(c6)

    for obj in all_kpl_objs:
        dt_s = obj.get("date", "")
        z10 = zt10_by_dt.get(dt_s, set())
        z20 = zt20_by_dt.get(dt_s, set())
        z_any = all_zt_by_dt.get(dt_s, set())
        today_p = []
        rk = 0
        max_pzt = 0
        for pl in obj.get("plates", []):
            pname = str(pl.get("plate", ""))
            if not pname or pname in NON_THEME:
                continue
            rk += 1
            today_p.append((pname, pl))
            mems = {str(s[0]).strip()[:6].zfill(6) for s in pl.get("stocks", [])}
            elo_pre = plate_elo[pname]
            n_any = len(mems & z_any)
            if dt_s in beta_dts:
                n10 = len(mems & z10)
                n20 = len(mems & z20)
                max_pzt = max(max_pzt, n10 + n20)
                plate_t0_stats[(dt_s, pname)] = (n10, n20, elo_pre)
                for c6 in mems:
                    if c6.startswith(("30", "688", "689")) and (dt_s, c6) not in kpl_t0_stock:
                        kpl_t0_stock[(dt_s, c6)] = (rk, n10, n20, elo_pre, pname)
            for c6 in mems:
                if c6.startswith(("30", "688", "689")):
                    hist_themes[c6].append((dt_s, pname))
        if dt_s in beta_dts:
            kpl_t0_max_pzt[dt_s] = max_pzt
        seen_today = set()
        for pn, pl in today_p:
            seen_today.add(pn)
            mems = {str(s[0]).strip()[:6].zfill(6) for s in pl.get("stocks", [])}
            n_any = len(mems & z_any)
            plate_elo[pn] = plate_elo[pn] * 0.90 + 10.0 * np.log1p(n_any)
        for pn in list(plate_elo.keys()):
            if pn not in seen_today:
                plate_elo[pn] *= 0.92

    hist_th_dts = {c6: [x[0] for x in v] for c6, v in hist_themes.items()}
    k_h60_10zt = np.zeros(n); k_h60_allzt = np.zeros(n); k_h60_elo = np.zeros(n)
    k_h180_allzt = np.zeros(n); k_h180_elo = np.zeros(n)
    k_t0_in = np.zeros(n); k_t0_rk = np.full(n, 99.0); k_t0_allzt = np.zeros(n); k_t0_elo = np.zeros(n)
    k_t0_maxpzt = np.zeros(n); k_main_theme = [""] * n
    for i, (dt_s, c6) in enumerate(zip(cand["dt"], cand["c6"])):
        k_t0_maxpzt[i] = kpl_t0_max_pzt.get(dt_s, 0)
        ti = kpl_t0_stock.get((dt_s, c6))
        if ti:
            k_t0_in[i] = 1.0; k_t0_rk[i] = ti[0]; k_t0_allzt[i] = ti[1] + ti[2]; k_t0_elo[i] = ti[3]; k_main_theme[i] = ti[4]
        ht = hist_th_dts.get(c6)
        if ht:
            d60 = (datetime.date.fromisoformat(dt_s) - datetime.timedelta(days=60)).isoformat()
            d180 = (datetime.date.fromisoformat(dt_s) - datetime.timedelta(days=180)).isoformat()
            i0_180 = bisect.bisect_left(ht, d180)
            i0_60 = bisect.bisect_left(ht, d60)
            i1 = bisect.bisect_left(ht, dt_s)  # strictly < T0!
            pns60 = {hist_themes[c6][j][1] for j in range(i0_60, i1)} if i1 > i0_60 else set()
            pns180 = {hist_themes[c6][j][1] for j in range(i0_180, i1)} if i1 > i0_180 else set()
            m10 = mall = 0; melo = 0.0
            for pn in pns60:
                ps = plate_t0_stats.get((dt_s, pn))
                if ps:
                    m10 = max(m10, ps[0]); mall = max(mall, ps[0] + ps[1]); melo = max(melo, ps[2])
            mall180 = 0; melo180 = 0.0; best_pn = ""
            for pn in pns180:
                ps = plate_t0_stats.get((dt_s, pn))
                if ps:
                    if ps[0] + ps[1] > mall180:
                        mall180 = ps[0] + ps[1]; best_pn = pn
                    melo180 = max(melo180, ps[2])
            k_h60_10zt[i] = m10; k_h60_allzt[i] = mall; k_h60_elo[i] = melo
            k_h180_allzt[i] = mall180; k_h180_elo[i] = melo180
            if not k_main_theme[i] and best_pn:
                k_main_theme[i] = best_pn
    cand["kpl_hist60_10zt_max"] = k_h60_10zt
    cand["kpl_hist60_allzt_max"] = k_h60_allzt
    cand["kpl_hist60_elo_max"] = k_h60_elo
    cand["kpl_hist180_allzt_max"] = k_h180_allzt
    cand["kpl_hist180_elo_max"] = k_h180_elo
    cand["in_kpl_t0"] = k_t0_in
    cand["kpl_t0_rk"] = k_t0_rk
    cand["kpl_t0_allzt"] = k_t0_allzt
    cand["kpl_t0_elo"] = k_t0_elo
    cand["kpl_t0_max_pzt"] = k_t0_maxpzt
    cand["kpl_main_theme"] = k_main_theme

    # KPL theme peers T+1 09:25 open average (leave-one-out)
    grp_sums = cand[cand["kpl_main_theme"] != ""].groupby(["dt", "kpl_main_theme"])["t1_open_gap"].agg(["sum", "count"]).to_dict("index")
    peers_o = np.full(n, np.nan)
    for i, (dt_s, thm, og) in enumerate(zip(cand["dt"], cand["kpl_main_theme"], cand["t1_open_gap"])):
        if thm and (dt_s, thm) in grp_sums:
            s_v, c_v = grp_sums[(dt_s, thm)]["sum"], grp_sums[(dt_s, thm)]["count"]
            if pd.notna(og) and c_v > 1:
                peers_o[i] = (s_v - og) / (c_v - 1)
            elif pd.isna(og) and c_v >= 1:
                peers_o[i] = s_v / c_v
    cand["kpl_peers_t1_open"] = peers_o

    # LHB (T0 post-close + T-10..T-1)
    lhb = pd.read_parquet(f"{SIM}/backtests_astock2/rd016_famous_youzi_seats_20261117/clean_lhb_5y.parquet")
    lhb = lhb[lhb["stock_code"].astype(str).str.startswith(("30", "688", "689"))].copy()
    lhb["is_org"] = lhb["dept_name"].str.contains("机构专用", na=False) | (lhb["dept_code"] == "0")
    lhb["is_lhasa"] = lhb["dept_name"].str.contains(RE_LHASA, na=False) & (~lhb["dept_name"].str.contains("东亚", na=False))
    lhb["is_quant"] = lhb["dept_name"].str.contains(RE_QUANT, na=False)
    lhb["is_surf"] = lhb["dept_name"].str.contains(RE_SURF, na=False) | lhb["dept_code"].isin(IS_BAD_CODES)
    lhb["is_good"] = lhb["dept_code"].isin(IS_GOOD_CODES)

    bayes = pd.read_parquet(f"{SIM}/backtests_astock2/rd016_famous_youzi_seats_20261117/bayes_seat_scores_d1_5y.parquet")
    bayes = bayes[bayes["stock_code"].astype(str).str.startswith(("30", "688", "689"))]
    b_map = {}
    for (dt_s, sc), grp in bayes.groupby(["date", "stock_code"], sort=False):
        w = np.maximum(grp["NET"].to_numpy(dtype=float), 1.0)
        b_map[(dt_s, sc)] = float(np.sum(w * grp["b_t2"].to_numpy()) / np.sum(w))

    lhb_d1, lhb_hist = {}, defaultdict(list)
    for (dt_s, sc, is3), grp in lhb.groupby(["date", "stock_code", "is_three"], sort=False):
        if int(is3) == 1:
            continue
        b = grp[grp["side"] == "B"]
        tot_b = float(b["BUY"].sum())
        org_net = float(grp[grp["is_org"]]["NET"].sum()) / 1e8
        org_cnt = int(b["is_org"].sum())
        lh_cnt = int(len(set(b[b["is_lhasa"]]["dept_code"])))
        lh_sh = float(b[b["is_lhasa"]]["BUY"].sum() / tot_b) if tot_b > 0 else 0.0
        q_cnt = int(b["is_quant"].sum())
        has_surf = int(b[b["NET"] > 0]["is_surf"].any())
        has_good = int(b[b["NET"] > 0]["is_good"].any())
        lhb_d1[(dt_s, sc)] = (org_net, org_cnt, lh_cnt, lh_sh, q_cnt, has_surf, has_good, b_map.get((dt_s, sc), 0.0))
        lhb_hist[sc].append((dt_s, org_net, lh_cnt))
    for sc in lhb_hist: lhb_hist[sc].sort(key=lambda x: x[0])

    l_on = np.zeros(n); l_onet = np.zeros(n); l_ocnt = np.zeros(n); l_pure = np.zeros(n)
    l_lh_cnt = np.zeros(n); l_lh_sh = np.zeros(n); l_surf = np.zeros(n); l_good = np.zeros(n); l_bt2 = np.zeros(n)
    l_lh_10d = np.zeros(n); l_org_10d = np.zeros(n)
    for i, (dt_s, c6) in enumerate(zip(cand["dt"], cand["c6"])):
        d1 = lhb_d1.get((dt_s, c6))
        if d1:
            l_on[i] = 1.0; l_onet[i] = d1[0]; l_ocnt[i] = d1[1]
            l_pure[i] = float(d1[1] >= 2 and d1[0] > 0.10 and d1[2] == 0)
            l_lh_cnt[i] = d1[2]; l_lh_sh[i] = d1[3]; l_surf[i] = d1[5]; l_good[i] = d1[6]; l_bt2[i] = d1[7]
        arr = lhb_hist.get(c6)
        if arr:
            lo = (datetime.date.fromisoformat(dt_s) - datetime.timedelta(days=14)).isoformat()
            dts_o = [x[0] for x in arr]
            i0 = bisect.bisect_left(dts_o, lo); i1 = bisect.bisect_left(dts_o, dt_s)
            if i1 > i0:
                sl = arr[i0:i1]
                l_lh_10d[i] = float(any(x[2] > 0 for x in sl))
                l_org_10d[i] = float(any(x[1] > 0 for x in sl))
    cand["lhb_on_t0"] = l_on; cand["lhb_t0_org_net_yi"] = l_onet; cand["lhb_t0_org_cnt"] = l_ocnt
    cand["lhb_t0_pure_org"] = l_pure; cand["lhb_t0_lhasa_cnt"] = l_lh_cnt; cand["lhb_t0_lhasa_share"] = l_lh_sh
    cand["lhb_t0_surf_bad"] = l_surf; cand["lhb_t0_good_yz"] = l_good; cand["lhb_t0_bayes_t2"] = l_bt2
    cand["lhb_has_lhasa_10d_pre"] = l_lh_10d; cand["lhb_has_org_10d_pre"] = l_org_10d

    # CNINFO notices, IR QA, Reg-Tox (covering up to 2026-11-24!)
    cand_c6 = set(cand["c6"].unique())
    tox_m, ep_m, en_m, cont_m, ma_m, bb_m = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    tox_df = pd.read_parquet(f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet", columns=["sec_code", "pub_datetime_cst", "title"])
    for sc, pts, ttl in zip(tox_df["sec_code"], tox_df["pub_datetime_cst"], tox_df["title"]):
        c6 = str(sc)[:6].zfill(6)
        if c6 in cand_c6:
            t_s = str(ttl or "")
            if TOX_RE.search(t_s) or (REG_RE.search(t_s) and not REG_EXC.search(t_s)):
                tox_m[c6].append(str(pts)[:19])
    for zf in glob.glob(f"{SIM}/data/kpl/zdjk/*.json"):
        for it in json.load(open(zf, encoding="utf-8")).get("List", []):
            c6 = str(it[0]).zfill(6)
            if c6 in cand_c6:
                tox_m[c6].append(str(it[2])[:10] + " 08:00:00")
    con_n = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for sc, pts, at, ttl in con_n.execute("SELECT sec_code, pub_datetime_cst, ann_type, title FROM notices WHERE sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%'"):
        c6 = str(sc)[:6].zfill(6)
        if c6 not in cand_c6 or not pts:
            continue
        p_s, a_s, t_s = str(pts)[:19], str(at or ""), str(ttl or "")
        if TOX_RE.search(t_s) or (REG_RE.search(t_s) and not REG_EXC.search(t_s)):
            tox_m[c6].append(p_s)
        if (EARN_POS_RE.search(a_s) or EARN_POS_RE.search(t_s)) and not EARN_NEG_RE.search(a_s + t_s):
            ep_m[c6].append(p_s)
        elif EARN_NEG_RE.search(a_s):
            en_m[c6].append(p_s)
        if "重大合同" in a_s or CONT_RE.search(t_s):
            cont_m[c6].append(p_s)
        if ("重组" in a_s or "收购" in a_s or MA_RE.search(t_s)) and not MA_NEG_RE.search(t_s):
            ma_m[c6].append(p_s)
        if "回购" in a_s or "增持" in a_s or BB_RE.search(t_s):
            bb_m[c6].append(p_s)
    con_n.close()

    con_ir = sqlite3.connect(f"file:{SIM}/data/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
    ir_m = defaultdict(list)
    for sc, pts in con_ir.execute("SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%'"):
        c6 = str(sc)[:6].zfill(6)
        if c6 in cand_c6 and pts:
            ir_m[c6].append(str(pts)[:19])
    con_ir.close()
    for mp in (tox_m, ep_m, en_m, cont_m, ma_m, bb_m, ir_m):
        for k in mp: mp[k] = sorted(set(mp[k]))

    def cnt_win(mp, c6, lo, hi):
        a = mp.get(c6)
        return max(0, bisect.bisect_right(a, hi) - bisect.bisect_left(a, lo)) if a else 0

    r_tox = np.zeros(n); ep_post = np.zeros(n); ep_30 = np.zeros(n); en_60 = np.zeros(n)
    c_cont30 = np.zeros(n); c_ma30 = np.zeros(n); c_bb30 = np.zeros(n); ir_30 = np.zeros(n); ir_90 = np.zeros(n)
    for i, (dt_s, t1_s, c6) in enumerate(zip(cand["dt"], cand["t1_dt"], cand["c6"])):
        d_o = datetime.date.fromisoformat(dt_s)
        cut_a = f"{dt_s} 14:55:00"
        cut_b = f"{t1_s} 09:25:00" if t1_s else f"{(d_o + datetime.timedelta(days=1)).isoformat()} 09:25:00"
        d30 = (d_o - datetime.timedelta(days=30)).isoformat() + " 00:00:00"
        d60 = (d_o - datetime.timedelta(days=60)).isoformat() + " 00:00:00"
        d90 = (d_o - datetime.timedelta(days=90)).isoformat() + " 00:00:00"
        r_tox[i] = float(cnt_win(tox_m, c6, d90, cut_b) > 0)
        ep_post[i] = float(cnt_win(ep_m, c6, cut_a, cut_b) > 0)
        ep_30[i] = float(cnt_win(ep_m, c6, d30, cut_b) > 0)
        en_60[i] = float(cnt_win(en_m, c6, d60, cut_b) > 0)
        c_cont30[i] = float(cnt_win(cont_m, c6, d30, cut_b) > 0)
        c_ma30[i] = float(cnt_win(ma_m, c6, d30, cut_b) > 0)
        c_bb30[i] = float(cnt_win(bb_m, c6, d30, cut_b) > 0)
        ir_30[i] = float(cnt_win(ir_m, c6, d30, cut_b) > 0)
        ir_90[i] = float(cnt_win(ir_m, c6, d90, cut_b))
    cand["reg_tox_90d_B"] = r_tox; cand["earn_pos_t0_post_B"] = ep_post
    cand["earn_pos_30d_B"] = ep_30; cand["earn_neg_60d_B"] = en_60
    cand["cat_contract_30d_B"] = c_cont30; cand["cat_ma_30d_B"] = c_ma30; cand["cat_buyback_30d_B"] = c_bb30
    cand["cat_any_30d_B"] = ((c_cont30 + c_ma30 + c_bb30) > 0).astype(float)
    cand["ir_qa_30d_B"] = ir_30; cand["ir_qa_cnt90_B"] = ir_90

    csrc_map = dict(zip(csrc_df["sec_code"].str[:6], csrc_df["industry"].fillna("")))
    cand["csrc_hard_tech"] = [float(bool(CSRC_TECH_RE.search(csrc_map.get(c, "")))) for c in cand["c6"]]

    # Zero-Leak Community Heat (xueqiu_guba_5y_pit filtered strictly to d1_date <= dt! + astock_community)
    con_xq = sqlite3.connect(f"file:{SIM}/data/xueqiu_guba_5y_pit.db?mode=ro", uri=True)
    gb_df = pd.read_sql_query("SELECT sec_code, pub_time, d1_date FROM guba_posts WHERE (sec_code LIKE '30%' OR sec_code LIKE '688%') AND pub_time >= '2020-12-20'", con_xq)
    xq_df = pd.read_sql_query("SELECT symbol, created_time_str, d1_date FROM xueqiu_posts WHERE (symbol LIKE '30%' OR symbol LIKE '688%') AND created_time_str >= '2020-12-20'", con_xq)
    con_xq.close()
    gb_zero = defaultdict(list)
    for sc, pt, d1 in zip(gb_df["sec_code"], gb_df["pub_time"], gb_df["d1_date"]):
        gb_zero[str(sc).zfill(6)].append((str(d1)[:10], str(pt)[:19]))
    xq_zero = defaultdict(list)
    for sc, pt, d1 in zip(xq_df["symbol"], xq_df["created_time_str"], xq_df["d1_date"]):
        xq_zero[str(sc).zfill(6)].append((str(d1)[:10], str(pt)[:19]))

    con_c = sqlite3.connect(f"file:{SIM}/data/astock_community_5y_pit.db?mode=ro", uri=True)
    for src, sc, pt in con_c.execute("SELECT source, symbol, pub_datetime_cst FROM community_posts WHERE (symbol LIKE '30%' OR symbol LIKE '688%') AND pub_datetime_cst >= '2020-12-20'"):
        c6 = str(sc).zfill(6)
        if src in ("eastmoney_guba", "guba"):
            gb_zero[c6].append(("1900-01-01", str(pt)[:19]))
        elif src == "xueqiu":
            xq_zero[c6].append(("1900-01-01", str(pt)[:19]))
    con_c.close()

    gb_p3 = np.zeros(n); xq_p3 = np.zeros(n)
    for i, (dt_s, t1_s, c6) in enumerate(zip(cand["dt"], cand["t1_dt"], cand["c6"])):
        d3 = (datetime.date.fromisoformat(dt_s) - datetime.timedelta(days=3)).isoformat() + " 00:00:00"
        cut_b = f"{t1_s} 09:25:00" if t1_s else f"{(datetime.date.fromisoformat(dt_s) + datetime.timedelta(days=1)).isoformat()} 09:25:00"
        g_list = gb_zero.get(c6)
        if g_list:
            gb_p3[i] = sum(1 for d1, pt in g_list if d1 <= dt_s and d3 <= pt <= cut_b)
        x_list = xq_zero.get(c6)
        if x_list:
            xq_p3[i] = sum(1 for d1, pt in x_list if d1 <= dt_s and d3 <= pt <= cut_b)
    cand["gb_posts_3d_pit"] = gb_p3
    cand["xq_posts_3d_pit"] = xq_p3
    cand["comm_posts_3d_pit"] = gb_p3 + xq_p3

    # Merge Market Macro
    mkt_cols = [
        "dt", "ew_ret_all", "up_ratio_all", "ew_ret_20cm", "ew_ret_10cm", "tot_amt_trillion",
        "amt_ma20_trillion", "amt_ratio_20", "zt_all_cnt", "zt_20cm_cnt", "seal_rate_all",
        "yest_1b_promo_rate", "mkt_prev1d_ew", "mkt_prev3d_ew", "mkt_prev5d_ew", "mkt_prev20d_ew",
        "mkt_is_above_ma20", "sh000300",
    ]
    cand = cand.merge(mkt[mkt_cols].rename(columns={"amt_ratio_20": "mkt_amt_ratio_20"}), on="dt", how="left")
    cand["mkt_20cm_minus_10cm"] = cand["ew_ret_20cm"] - cand["ew_ret_10cm"]
    cand["mkt_is_ice_rebound"] = (cand["mkt_prev5d_ew"] < -0.02).astype(float)
    dt_ts = pd.to_datetime(cand["dt"])
    cand["is_monday"] = (dt_ts.dt.dayofweek == 0).astype(float)
    cand["is_friday"] = (dt_ts.dt.dayofweek == 4).astype(float)
    cand["is_earnings_month"] = dt_ts.dt.month.isin([1, 4, 7, 8, 10]).astype(float)
    cand["is_delisted"] = (cand["_act"] == 0).astype(int)

    # Filter reg_tox_90d_B == 0 cleanly into base_pool (save full pre-tox too!)
    cand.to_parquet(f"{OUT_DIR}/v1_beta_candidates_all.parquet", index=False)
    base = cand[cand["reg_tox_90d_B"] == 0].copy().reset_index(drop=True)
    base.to_parquet(f"{OUT_DIR}/v1_beta_base_pool.parquet", index=False)
    print(f"[5/5] Saved v1_beta_base_pool.parquet ({len(base):,} rows, delisted={base['is_delisted'].sum()}, "
          f"IS={len(base[base['dt']<='2024-08-31']):,}, OOS={len(base[base['dt']>='2024-09-01']):,}, "
          f"2026-11-23={len(base[base['dt']=='2026-11-23']):,}) in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
