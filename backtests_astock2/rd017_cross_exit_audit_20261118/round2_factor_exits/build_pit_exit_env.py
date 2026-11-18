#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
build_pit_exit_env.py — 第二轮持仓期动态卖点因子的严格 PIT 环境底座构建与缓存
覆盖 2021-01-04 ~ 2026-11-16 全市场日线截断、龙虎榜去重席位、公告时间锚点、雪球贴时序、涨停微盘口与 KPL 题材映射。
"""
import os, sys, re, json, glob, time, pickle, sqlite3
from collections import defaultdict
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 VIOLATION!"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock2/rd017_cross_exit_audit_20261118/round2_factor_exits"
os.makedirs(OUT_DIR, exist_ok=True)

DATA_END = "2026-11-16"

RE_LHASA = re.compile(r"(?:拉萨|东方财富证券.*拉萨)")
RE_SURF_YZ = re.compile(r"(?:上塘路|财通.*杭州上塘|佛山|绿景路|季华|苏南|消闲派|宜昌沿江|宜昌珍珠|国泰君安.*宜昌|开源.*西安西大街|东方财富.*昌都)")
RE_INST = re.compile(r"机构专用")
RE_TOP_YZ = re.compile(
    r"(?:大连金马路|大连黄河路|六一中路|天津东丽开发区二纬路|北京东直门南大街|北京广渠门内大街|"
    r"上海江苏路|上海建国西路|杭州延安路|兴业证券.*陕西分公司|西安朱雀大街|"
    r"南京太平南路|宁波桑田路|上海宛平南路|上海红宝石路|上海茅台路|宁波和源路|北京长椿街)"
)

TOX_RE = re.compile(r"(?:减持计划|股东减持|减持股份|立案调查|收到立案|退市风险|违法违规|业绩预亏|预亏|亏损)")
REG_INC_RE = re.compile(r"(?:监管工作函|监管函|关注函|重点监控|停牌核查|严重异常波动)")
REG_EXC_RE = re.compile(r"(?:ST|回复|回函|延期|核查意见|复牌|募集资金|监事|独立董事|保荐)")
ABN_RE = re.compile(r"(?:股票交易异常波动|异常波动|风险提示|澄清)")

NON_THEME = {"其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长", "年报增长", "一季报增长", "中报增长", "次新股"}
EVENT_BASKET = {"并购重组", "股权转让", "资产注入", "国企改革", "央企改革", "地方国资改革", "业绩增长", "预盈预增", "摘帽", "回购", "增持", "次新股", "高送转", "参股新股"}
CSRC_OUTSIDER = {
    "A01", "A02", "A03", "A04", "A05", "D44", "D45", "D46", "E47", "E48", "E49", "E50",
    "F51", "F52", "G53", "G54", "G55", "G56", "G58", "G59", "H61", "H62", "K70",
    "L72", "N77", "N78", "C13", "C14", "C15", "C17", "C18", "C19", "C20", "C21", "C22",
}


def main():
    t0 = time.time()
    print("[1/5] Loading A-share daily panel (active + delisted <= 2026-11-16)...")
    cols = ["date", "ticker", "open", "high", "low", "close", "volume", "amount", "turn", "oshare"]
    flt = (ds.field("date") >= pd.Timestamp("2020-11-01")) & (ds.field("date") <= pd.Timestamp(DATA_END))
    d1 = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet", format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    d2 = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da = pd.concat([d1, d2], ignore_index=True)
    da["c6"] = da["ticker"].astype(str).str[:6]
    da = da[da["c6"].str.startswith(("00", "60")) & (~da["ticker"].astype(str).str.endswith(".BJ"))].copy()
    da["dt"] = da["date"].dt.strftime("%Y-%m-%d")
    da = da[da["dt"] <= DATA_END].sort_values(["c6", "dt"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)

    g = da.groupby("c6")
    da["pre_c"] = g["close"].shift(1)
    da["pct"] = da["close"] / da["pre_c"] - 1.0
    da["o_pct"] = da["open"] / da["pre_c"] - 1.0
    da["h_pct"] = da["high"] / da["pre_c"] - 1.0
    da["l_pct"] = da["low"] / da["pre_c"] - 1.0
    da["to"] = da["turn"] * 100.0
    da["zt_px"] = np.floor(da["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    da["dt_px"] = np.floor(da["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    da["is_zt"] = (da["pre_c"] > 0) & (da["close"] >= da["zt_px"] - 0.011) & (da["pct"] >= 0.095)
    da["is_dt"] = (da["pre_c"] > 0) & (da["close"] <= da["dt_px"] + 0.011) & (da["pct"] <= -0.095)
    da["is_zt_open"] = (da["pre_c"] > 0) & (da["open"] >= da["zt_px"] - 0.011)
    da["is_dt_open"] = (da["pre_c"] > 0) & (da["open"] <= da["dt_px"] + 0.011)
    s_zt = da["is_zt"].astype(int)
    s_sh = g["is_zt"].shift(1).fillna(False).infer_objects(copy=False).astype(bool)
    da["streak"] = s_zt.groupby([da["c6"], (s_zt != s_sh).cumsum()]).cumsum() * s_zt
    da["prev_streak"] = g["streak"].shift(1).fillna(0).astype(int)
    da["prev_is_zt"] = g["is_zt"].shift(1).fillna(False).infer_objects(copy=False).astype(bool)
    da["prev_is_dt"] = g["is_dt"].shift(1).fillna(False).infer_objects(copy=False).astype(bool)
    da["amt_ma5_prev"] = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())

    # Cross-sectional market 09:25 and EOD stats
    all_dts = sorted(da[da["dt"] >= "2021-01-01"]["dt"].unique())
    mkt_stats = {}
    brk_hist = []
    prev_zt_cnt = 50
    for dt, grp in da[da["dt"] >= "2020-12-15"].groupby("dt", sort=True):
        pzt = grp[grp["prev_is_zt"] & grp["o_pct"].notna()]
        p1b = grp[(grp["prev_streak"] == 1) & grp["o_pct"].notna()]
        broken_hi = grp[(grp["prev_streak"] >= 4) & (~grp["is_zt"])]
        brk_hist.append((dt, int(broken_hi["is_dt"].sum()), int(len(broken_hi))))
        if dt >= "2021-01-01":
            # Strictly prior 10 days brk_r10 (excluding today dt!)
            w10 = brk_hist[-11:-1]
            dt_s = sum(x[1] for x in w10); brk_s = sum(x[2] for x in w10)
            mkt_stats[dt] = {
                "mkt_0925_zt_cnt": int(grp["is_zt_open"].sum()),
                "mkt_0925_dt_cnt": int(grp["is_dt_open"].sum()),
                "mkt_prev_zt_open_avg": float(pzt["o_pct"].mean()) if len(pzt) else 0.0,
                "mkt_prev_1b_open_avg": float(p1b["o_pct"].mean()) if len(p1b) else 0.0,
                "mkt_prev_zt_cnt": prev_zt_cnt,
                "brk_r10_prev": float(dt_s / brk_s) if brk_s > 0 else 0.0,
            }
        prev_zt_cnt = int(grp["is_zt"].sum())

    idx_cache = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
    sh300 = idx_cache["sh000300"]
    csi_dts = sorted(sh300.keys())
    csi_5d_prev = {}
    for i, d in enumerate(csi_dts):
        if i >= 6:
            csi_5d_prev[d] = float(sh300[csi_dts[i - 1]] / sh300[csi_dts[i - 6]] - 1.0)
        else:
            csi_5d_prev[d] = 0.0

    print("[2/5] Building KPL plate & 09:25 peers open map...")
    kpl_by_dt = {}
    with open(f"{SIM}/data/kpl_plates_2018_2026_merged.jsonl", encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                obj = json.loads(ln)
                dt_k = obj.get("date", "")
                if "2021-01-01" <= dt_k <= DATA_END:
                    kpl_by_dt[dt_k] = obj.get("plates", [])
    stock_plate_map = {}  # (dt, c6) -> (main_plate, plate_sz, all_plates_list, reason)
    plate_stocks_map = {}  # (dt, plate) -> list of c6
    for dt_k, pls in kpl_by_dt.items():
        for p in pls:
            pn = p.get("plate", "")
            stks = p.get("stocks", [])
            if not stks or pn in NON_THEME:
                continue
            sz = len(stks)
            c6s = []
            for s in stks:
                c6 = str(s[0]).strip()[:6].zfill(6)
                c6s.append(c6)
                r_sh = str(s[2]).strip() if len(s) > 2 else ""
                cur = stock_plate_map.get((dt_k, c6))
                if cur is None or sz > cur[1]:
                    stock_plate_map[(dt_k, c6)] = (pn, sz, [pn], r_sh)
                else:
                    if pn not in cur[2]:
                        cur[2].append(pn)
            plate_stocks_map[(dt_k, pn)] = c6s

    # Per (dt, c6) o_pct, l_pct, is_dt for fast peer lookup
    day_o_pct = {(r.dt, r.c6): float(r.o_pct) for r in da[da["dt"] >= "2021-01-01"][["dt", "c6", "o_pct"]].itertuples(index=False) if pd.notna(r.o_pct)}
    day_prev_dt = {(r.dt, r.c6): bool(r.prev_is_dt) for r in da[da["dt"] >= "2021-01-01"][["dt", "c6", "prev_is_dt"]].itertuples(index=False)}
    day_amt = {(r.dt, r.c6): float(r.amount) for r in da[da["dt"] >= "2021-01-01"][["dt", "c6", "amount"]].itertuples(index=False) if pd.notna(r.amount)}
    day_to_map = {(r.dt, r.c6): (float(r.to), float(r.open), float(r.high), float(r.low), float(r.close), float(r.pre_c), float(r.amt_ma5_prev) if pd.notna(r.amt_ma5_prev) else 0.0)
                  for r in da[da["dt"] >= "2021-01-01"][["dt", "c6", "to", "open", "high", "low", "close", "pre_c", "amt_ma5_prev"]].itertuples(index=False) if pd.notna(r.pre_c)}

    print("[3/5] Loading & deduplicating LHB (lhb_buy + lhb_sell <= 2026-11-16)...")
    lhb_b = pd.read_parquet(f"{SIM}/backtest/2026-10-20-lhasa/lhb_buy.parquet", columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY", "SELL"])
    lhb_s = pd.read_parquet(f"{SIM}/backtest/2026-10-20-lhasa/lhb_sell.parquet", columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY", "SELL"])
    for df_l in (lhb_b, lhb_s):
        df_l["dt"] = df_l["TRADE_DATE"].astype(str).str[:10]
        df_l["c6"] = df_l["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
    lhb_b = lhb_b[(lhb_b["dt"] >= "2021-01-01") & (lhb_b["dt"] <= DATA_END)]
    lhb_s = lhb_s[(lhb_s["dt"] >= "2021-01-01") & (lhb_s["dt"] <= DATA_END)]

    lhb_b_ded = lhb_b.groupby(["dt", "c6", "OPERATEDEPT_NAME"], as_index=False)["BUY"].min()
    lhb_s_ded = lhb_s.groupby(["dt", "c6", "OPERATEDEPT_NAME"], as_index=False)["SELL"].min()

    lhb_buy_info = {}  # (dt, c6) -> dict(lh_cnt, lh_ratio, surf_yz, inst_buy_amt, tot_buy, top_yz_depts)
    for (dt_l, c6_l), grp in lhb_b_ded.groupby(["dt", "c6"], sort=False):
        depts = grp["OPERATEDEPT_NAME"].astype(str).tolist()
        buys = grp["BUY"].fillna(0.0).to_numpy(dtype=float)
        tot_b = float(buys.sum())
        lh_cnt = sum(1 for d in depts if RE_LHASA.search(d))
        lh_amt = float(sum(b for d, b in zip(depts, buys) if RE_LHASA.search(d)))
        surf_yz = any(RE_SURF_YZ.search(d) for d in depts)
        inst_b = float(sum(b for d, b in zip(depts, buys) if RE_INST.search(d)))
        top_yz = [d for d in depts if RE_TOP_YZ.search(d)]
        lhb_buy_info[(dt_l, c6_l)] = {
            "lh_cnt": lh_cnt, "lh_ratio": (lh_amt / tot_b) if tot_b > 0 else 0.0,
            "surf_yz": surf_yz, "inst_buy": inst_b, "tot_buy": tot_b, "top_yz": top_yz,
        }

    lhb_sell_info = {}  # (dt, c6) -> dict(inst_sell_amt, tot_sell, sell_depts)
    for (dt_l, c6_l), grp in lhb_s_ded.groupby(["dt", "c6"], sort=False):
        depts = grp["OPERATEDEPT_NAME"].astype(str).tolist()
        sells = grp["SELL"].fillna(0.0).to_numpy(dtype=float)
        tot_s = float(sells.sum())
        inst_s = float(sum(s for d, s in zip(depts, sells) if RE_INST.search(d)))
        lhb_sell_info[(dt_l, c6_l)] = {"inst_sell": inst_s, "tot_sell": tot_s, "sell_depts": depts}

    print("[4/5] Loading PIT notices (pit_reg_tox + cninfo_notices_5y_pit + part1_cache + zdjk)...")
    reg_ts_map = defaultdict(list)  # c6 -> sorted list of ts strings
    tox_ts_map = defaultdict(list)
    abn_ts_map = defaultdict(list)
    ex_reg_events = {"SH": [], "SZ": []}  # list of (ts_str, c6)

    with open(f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/part1_cache.pkl", "rb") as f:
        pkg = pickle.load(f)
    for c6_r, dts_r in pkg[10].items():
        c6 = str(c6_r).zfill(6)
        for d in dts_r:
            ds_v = str(d)[:10]
            if ds_v <= DATA_END:
                reg_ts_map[c6].append(ds_v + " 08:00:00")
                ex_reg_events["SH" if c6.startswith("60") else "SZ"].append((ds_v + " 08:00:00", c6))
    for ex_k in ("SH", "SZ"):
        for d in pkg[11].get(ex_k, []):
            if str(d)[:10] <= DATA_END:
                ex_reg_events[ex_k].append((str(d)[:10] + " 08:00:00", f"EX_{d}"))
    for c6_r, dts_r in pkg[12].items():
        c6 = str(c6_r).zfill(6)
        for d in dts_r:
            ds_v = str(d)[:10]
            if ds_v <= DATA_END:
                tox_ts_map[c6].append(ds_v + " 08:00:00")

    rt = pd.read_parquet(f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet", columns=["sec_code", "pub_datetime_cst", "title"])
    rt = rt[rt["pub_datetime_cst"].astype(str).str[:10] <= DATA_END]
    for sc, pdt, ti in zip(rt["sec_code"].astype(str).str[:6].str.zfill(6), rt["pub_datetime_cst"].astype(str), rt["title"].astype(str)):
        if TOX_RE.search(ti):
            tox_ts_map[sc].append(pdt)
        if REG_INC_RE.search(ti) and (not REG_EXC_RE.search(ti)):
            reg_ts_map[sc].append(pdt)
            if sc.startswith(("00", "60")):
                ex_reg_events["SH" if sc.startswith("60") else "SZ"].append((pdt, sc))
        if ABN_RE.search(ti):
            abn_ts_map[sc].append(pdt)

    con_n = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for sc, pdt, ti in con_n.execute("SELECT sec_code, pub_datetime_cst, title FROM notices WHERE pub_datetime_cst <= ?", (f"{DATA_END} 23:59:59",)):
        c6 = str(sc)[:6].zfill(6)
        if not c6.startswith(("00", "60")):
            continue
        t_s = str(ti)
        if TOX_RE.search(t_s):
            tox_ts_map[c6].append(str(pdt))
        if REG_INC_RE.search(t_s) and (not REG_EXC_RE.search(t_s)):
            reg_ts_map[c6].append(str(pdt))
        if ABN_RE.search(t_s):
            abn_ts_map[c6].append(str(pdt))
    con_n.close()

    for zf in glob.glob(f"{SIM}/data/kpl/zdjk/*.json"):
        for it in json.load(open(zf, encoding="utf-8")).get("List", []):
            dz = str(it[2])[:10]
            if dz <= DATA_END:
                c6 = str(it[0]).zfill(6)
                reg_ts_map[c6].append(dz + " 08:00:00")
                if c6.startswith(("00", "60")):
                    ex_reg_events["SH" if c6.startswith("60") else "SZ"].append((dz + " 08:00:00", c6))

    for m in (reg_ts_map, tox_ts_map, abn_ts_map):
        for k in list(m.keys()):
            m[k] = np.sort(np.array(sorted(set(m[k])), dtype=str))
    for ex_k in ("SH", "SZ"):
        ex_reg_events[ex_k] = sorted(set(ex_reg_events[ex_k]))

    print("[5/5] Loading zt_micro_tape & Xueqiu timestamps...")
    con_t = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    tape_map = {}
    for td, sc, fst, obc, sa in con_t.execute("SELECT trade_date, sec_code, first_seal_time, open_board_count, seal_amount FROM zt_micro_tape WHERE trade_date >= '2021-01-01' AND trade_date <= ?", (DATA_END,)):
        c6 = str(sc)[:6].zfill(6); td_s = str(td)
        am = day_amt.get((td_s, c6), 0.0)
        sr = (float(sa) / am) if (sa is not None and am > 0) else np.nan
        tape_map[(td_s, c6)] = (str(fst or "99:99:99"), int(obc or 0), sr)
    con_t.close()

    xq_seen = defaultdict(set); xq_posts = defaultdict(list)
    con_x1 = sqlite3.connect(f"file:{SIM}/data/xueqiu_guba_5y_pit.db?mode=ro", uri=True)
    for sym, pid, cts in con_x1.execute("SELECT symbol, post_id, created_time_str FROM xueqiu_posts WHERE created_time_str >= '2020-12-01' AND created_time_str <= ?", (f"{DATA_END} 23:59:59",)):
        c6 = str(sym)[:6].zfill(6)
        if c6.startswith(("00", "60")) and cts:
            p = str(pid).replace("xq_", "")
            if p not in xq_seen[c6]: xq_seen[c6].add(p); xq_posts[c6].append(str(cts))
    con_x1.close()
    con_x2 = sqlite3.connect(f"file:{SIM}/data/astock_community_5y_pit.db?mode=ro", uri=True)
    for sym, pid, cts in con_x2.execute("SELECT symbol, post_id, pub_datetime_cst FROM community_posts WHERE source='xueqiu' AND pub_datetime_cst >= '2020-12-01' AND pub_datetime_cst <= ?", (f"{DATA_END} 23:59:59",)):
        c6 = str(sym)[:6].zfill(6)
        if c6.startswith(("00", "60")) and cts:
            p = str(pid).replace("xq_", "")
            if p not in xq_seen[c6]: xq_seen[c6].add(p); xq_posts[c6].append(str(cts))
    con_x2.close()
    xq_arr = {c6: np.sort(np.array(v, dtype=str)) for c6, v in xq_posts.items()}

    # Also CSRC PIT for fake-theme detection
    csrc_df = pd.read_csv(f"{SIM}/data/csrc_industry_pit_clean.csv", dtype=str).fillna("")
    csrc_by_c6 = defaultdict(list)
    for r in csrc_df.itertuples(index=False):
        csrc_by_c6[str(r.sec_code).strip()[:6].zfill(6)].append((str(r.start_date)[:10], str(r.end_date)[:10], str(r.industry)[:3]))

    env = {
        "all_dts": all_dts,
        "mkt_stats": mkt_stats,
        "csi_5d_prev": csi_5d_prev,
        "stock_plate_map": stock_plate_map,
        "plate_stocks_map": plate_stocks_map,
        "day_o_pct": day_o_pct,
        "day_prev_dt": day_prev_dt,
        "day_amt": day_amt,
        "day_to_map": day_to_map,
        "lhb_buy_info": lhb_buy_info,
        "lhb_sell_info": lhb_sell_info,
        "reg_ts_map": dict(reg_ts_map),
        "tox_ts_map": dict(tox_ts_map),
        "abn_ts_map": dict(abn_ts_map),
        "ex_reg_events": ex_reg_events,
        "tape_map": tape_map,
        "xq_arr": xq_arr,
        "csrc_by_c6": dict(csrc_by_c6),
    }
    out_pkl = f"{OUT_DIR}/pit_exit_env.pkl"
    with open(out_pkl, "wb") as f:
        pickle.dump(env, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[DONE] Saved {out_pkl} ({os.path.getsize(out_pkl)/1e6:.1f} MB) in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
