#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
live_3to4_cache_builder.py — 三进四 V3.4 盘前静态特征计算与缓存构建器
识别最新交易日（如 2026-11-13）全部沪深主板非ST三连板候选股及同题材梯队队友，计算盘前特征并落盘。
"""
import os, sys, json, time, re, sqlite3, datetime, urllib.request, pandas as pd, numpy as np, pyarrow.dataset as ds
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
DATA_DIR = f"{ROOT}/sim-portfolio/data"
CACHE_FILE, A_DAILY, THS_DIR = f"{DATA_DIR}/3to4_premarket_cache.json", f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet", f"{DATA_DIR}/ths_limit_up_daily"
HOLDERS_PATH = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"
IDX_PATH = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
DB_NOTICES, DB_PIT_NOTICES = f"{ROOT}/sim-portfolio/backtest/2026-08-24-daban/notices.db", f"{DATA_DIR}/cninfo_notices_5y_pit.db"
DB_XQ_GB, DB_COMM = f"{DATA_DIR}/xueqiu_guba_5y_pit.db", f"{DATA_DIR}/astock_community_5y_pit.db"
LHB_PATH = f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet"
SURF_YZ = re.compile(r"(?:上塘路|财通.*杭州上塘|东方财富.*昌都|佛山|绿景路|苏南|消闲派|国泰君安.*宜昌|开源.*西安西大街)")
REG_INC = ["监管工作函", "监管函", "关注函", "重点监控", "停牌核查"]
REG_EXC = ["ST", "回复", "回函", "延期", "核查意见", "复牌", "募集资金", "监事", "独立董事", "保荐"]
TOX_RE = re.compile(r"(?:减持计划|股东减持|立案调查|收到立案|退市风险)")
SECTOR_SYNONYMS = {
    "半导体": {"半导体", "芯片", "光刻胶", "集成电路", "玻璃基", "玻璃基板", "存储器", "GPU"},
    "芯片": {"半导体", "芯片", "光刻胶", "集成电路", "玻璃基", "玻璃基板", "存储器", "GPU"},
    "光伏": {"光伏", "光伏设备", "储能", "风光储", "逆变器"},
    "机器人": {"机器人", "人形机器人", "减速器", "四足机器人", "伺服", "电机"},
    "游戏": {"游戏", "AI游戏", "手游", "短剧", "传媒", "影视"},
}

def _extract_keywords(reason: str) -> set:
    kws = set()
    for w in str(reason).split("+"):
        w = w.strip()
        if w and w not in ("国企", "央企", "回购", "股份回购", "股权转让", "摘帽", "预重整", "扭亏", "三季报增长", "业绩增长"):
            kws.add(w)
            for _, syn_set in SECTOR_SYNONYMS.items():
                if any(s in w for s in syn_set): kws.update(syn_set)
    return kws

def build_premarket_cache(verbose: bool = True) -> dict:
    t0 = time.time()
    cols = ["date", "ticker", "open", "high", "low", "close", "turn", "oshare", "amount"]
    cut_dt = pd.Timestamp.now() - pd.Timedelta(days=95)
    df_act = ds.dataset(A_DAILY, format="parquet").scanner(columns=cols, filter=(ds.field("date") >= cut_dt)).to_table().to_pandas()
    df_act["c6"] = df_act["ticker"].astype(str).str[:6]
    df_act = df_act[df_act["c6"].str.startswith(("00", "60"))].copy()
    df_act["dt_str"] = df_act["date"].dt.strftime("%Y-%m-%d")
    max_p_date = df_act["dt_str"].max()
    try:
        idx_raw = urllib.request.urlopen("http://qt.gtimg.cn/q=sh000300", timeout=3).read().decode("gbk", errors="ignore")
        idx_p = idx_raw.split("~")
        dt14 = str(idx_p[30]).strip() if len(idx_p) > 30 else ""
        q_dt = f"{dt14[:4]}-{dt14[4:6]}-{dt14[6:8]}" if len(dt14) >= 8 and dt14[:8].isdigit() else ""
        q_hhmm = int(dt14[8:12]) if len(dt14) >= 12 and dt14[8:12].isdigit() else 0
        if q_dt > max_p_date and q_hhmm >= 1500:
            last_sub = df_act[df_act["dt_str"] == max_p_date]
            t_list = last_sub["ticker"].tolist()
            osh_map = dict(zip(last_sub["ticker"], last_sub["oshare"]))
            def _fetch_ch(ch):
                ql = [f"{'sh' if x[:6].startswith('60') else 'sz'}{x[:6]}" for x in ch]
                out = {}
                try:
                    raw = urllib.request.urlopen(f"http://qt.gtimg.cn/q={','.join(ql)}", timeout=3).read().decode("gbk", errors="ignore")
                    for ln in raw.strip().split(";"):
                        if "~" not in ln: continue
                        p = ln.split("~")
                        if len(p) > 38 and str(p[30]).strip()[:8] == dt14[:8] and float(p[3] or 0) > 0:
                            out[p[2].strip()] = (float(p[5] or p[3]), float(p[33] or p[3]), float(p[34] or p[3]), float(p[3]), float(p[38] or 0) / 100.0, float(p[37] or 0) * 10000.0)
                except Exception:
                    pass
                return out
            live_q = {}
            with ThreadPoolExecutor(max_workers=16) as ex:
                for fq in as_completed([ex.submit(_fetch_ch, t_list[i:i+80]) for i in range(0, len(t_list), 80)]):
                    live_q.update(fq.result())
            patch_rows = [
                {"date": pd.Timestamp(q_dt), "ticker": tk, "open": v[0], "high": v[1], "low": v[2], "close": v[3], "turn": v[4], "oshare": osh_map.get(tk, np.nan), "amount": v[5], "c6": tk[:6], "dt_str": q_dt}
                for tk in t_list if (v := live_q.get(tk[:6])) is not None
            ]
            if len(patch_rows) >= 2000:
                df_act = pd.concat([df_act, pd.DataFrame(patch_rows)], ignore_index=True)
                df_act.drop_duplicates(subset=["c6", "dt_str"], keep="last", inplace=True)
    except Exception as e:
        print(f"[WARN] live_3to4 close patch skipped: {e}", file=sys.stderr)
    df_act.sort_values(["c6", "dt_str"], inplace=True)
    g = df_act.groupby("c6")
    df_act["pre_c"] = g["close"].shift(1)
    df_act["pct"] = df_act["close"] / df_act["pre_c"] - 1.0
    df_act["zt_px"] = np.floor(df_act["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df_act["is_zt"] = (df_act["close"] >= df_act["zt_px"] - 0.011) & (df_act["pct"] >= 0.095) & (df_act["pre_c"] > 0)
    df_act["touch_zt"] = (df_act["high"] >= df_act["zt_px"] - 0.011) & (df_act["pre_c"] > 0)
    df_act["is_yizi"] = df_act["is_zt"] & (df_act["open"] >= df_act["zt_px"] - 0.011) & (df_act["low"] >= df_act["zt_px"] - 0.011)
    df_act["is_dt"] = (df_act["close"] <= np.floor(df_act["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0 + 0.011) & (df_act["pct"] <= -0.095)
    s_zt = df_act["is_zt"].astype(int)
    s_shift = g["is_zt"].shift().eq(True)
    df_act["streak"] = s_zt.groupby([df_act["c6"], (s_zt != s_shift).cumsum()]).cumsum() * s_zt
    df_act["min20"] = g["low"].transform(lambda s: s.rolling(20, min_periods=10).min())
    df_act["max20"] = g["high"].transform(lambda s: s.rolling(20, min_periods=10).max())
    df_act["pos20_today"] = (df_act["close"] - df_act["min20"]) / (df_act["max20"] - df_act["min20"] + 1e-6)
    df_act["pos20_d0"] = g["pos20_today"].shift(3)  # D0 = D3前3个交易日（首板启动前一日）
    df_act["d1_dt_for_3b"] = g["dt_str"].shift(2)   # D1 = D3前2个交易日（首板当日）

    d_list = sorted(df_act["dt_str"].unique())
    d3_date, prev_d = d_list[-1], (d_list[-2] if len(d_list) >= 2 else d_list[-1])
    d3_ts = pd.Timestamp(d3_date)
    nxt_buy_date = (d3_ts + pd.Timedelta(days=(3 if d3_ts.weekday() == 4 else 1))).strftime("%Y-%m-%d")
    d3_df = df_act[df_act["dt_str"] == d3_date]
    mkt_max_b = int(d3_df["streak"].max()) if not d3_df.empty else 4
    prev_3b = set(df_act[(df_act["dt_str"] == prev_d) & (df_act["streak"] == 3)]["c6"])
    dt3_cnt = int(d3_df[d3_df["c6"].isin(prev_3b) & d3_df["is_dt"]]["c6"].nunique())

    csi_1d, csi_5d = -0.0068, -0.010
    if os.path.exists(IDX_PATH):
        try:
            csi_m = json.load(open(IDX_PATH))["sh000300"]
            d_idx = sorted(csi_m.keys())
            pos = d_idx.index(d3_date) if d3_date in d_idx else len(d_idx) - 1
            if pos >= 1: csi_1d = float(csi_m[d_idx[pos]] / csi_m[d_idx[pos-1]] - 1.0)
            if pos >= 5: csi_5d = float(csi_m[d_idx[pos]] / csi_m[d_idx[pos-5]] - 1.0)
        except Exception: pass
    ths_path = f"{THS_DIR}/{d3_date}.json"
    ths_stocks = json.load(open(ths_path)).get("stocks", []) if os.path.exists(ths_path) else []
    ths_map = {str(s.get("code"))[:6]: s for s in ths_stocks}
    mkt_zt_prev = len(ths_stocks) if ths_stocks else int(d3_df["is_zt"].sum())

    holders = json.load(open(HOLDERS_PATH)) if os.path.exists(HOLDERS_PATH) else {}
    cut_tox, cut_reg = (d3_ts - pd.Timedelta(days=90)).strftime("%Y-%m-%d"), (d3_ts - pd.Timedelta(days=15)).strftime("%Y-%m-%d")
    d_m5 = d_list[max(0, len(d_list) - 5)]
    stk_reg, tox_stk = set(), set()
    ex_reg_stocks = {"SH": set(), "SZ": set()}
    for db_p in (DB_NOTICES, DB_PIT_NOTICES):
        if not os.path.exists(db_p): continue
        con = sqlite3.connect(f"file:{db_p}?mode=ro", uri=True)
        try:
            col_c = "sec_code" if "cninfo" in db_p else "code"
            col_d = "pub_datetime_cst" if "cninfo" in db_p else "ndate"
            for c_raw, pdt, ti in con.execute(f"SELECT {col_c}, {col_d}, title FROM {'notices' if 'cninfo' in db_p else 'notice'} WHERE {col_d} >= '{cut_tox}'"):
                c6_s, dt_s, t_str = str(c_raw)[:6].zfill(6), str(pdt)[:10], str(ti)
                if dt_s >= cut_reg and any(w in t_str for w in REG_INC) and not any(w in t_str for w in REG_EXC):
                    stk_reg.add(c6_s)
                if dt_s >= d_m5 and dt_s <= d3_date and any(w in t_str for w in REG_INC) and not any(w in t_str for w in REG_EXC):
                    if c6_s.startswith("60"):
                        ex_reg_stocks["SH"].add(c6_s)
                    elif c6_s.startswith("00"):
                        ex_reg_stocks["SZ"].add(c6_s)
                if TOX_RE.search(t_str):
                    tox_stk.add(c6_s)
        except Exception as e:
            print(f"[WARN] live_3to4 notices DB error in {db_p}: {e}", file=sys.stderr)
        finally:
            con.close()

    # 真实计算截至 d3_date 的八年滚动板块 Elo 热度分
    plate_elo_map = {}
    c1_path = f"{ROOT}/sim-portfolio/data/1to2_premarket_cache.json"
    if os.path.exists(c1_path):
        try:
            c1_data = json.load(open(c1_path, "r", encoding="utf-8"))
            if c1_data.get("d1_date") == d3_date and c1_data.get("theme_board"):
                for tb in c1_data["theme_board"]:
                    plate_elo_map[tb["plate"]] = float(tb["elo"])
        except Exception:
            pass

    if not plate_elo_map:
        # 独立从 KPL 全量库计算滚动 Elo
        kpl_merged_p = f"{ROOT}/sim-portfolio/data/kpl_plates_2018_2026_merged.jsonl"
        kpl_5y_p = f"{ROOT}/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl"
        kpl_days_map = {}
        if os.path.exists(kpl_merged_p):
            for ln in open(kpl_merged_p, encoding="utf-8"):
                if ln.strip():
                    try:
                        d = json.loads(ln); dt = d.get("date", "")
                        if dt and dt < "2021-01-01": kpl_days_map[dt] = d
                    except Exception: pass
        if os.path.exists(kpl_5y_p):
            for ln in open(kpl_5y_p, encoding="utf-8"):
                if ln.strip():
                    try:
                        d = json.loads(ln); dt = d.get("date", "")
                        if dt and dt >= "2021-01-01": kpl_days_map[dt] = d
                    except Exception: pass
        sub_act = df_act[["dt_str", "c6", "is_zt", "touch_zt", "is_yizi", "pct"]]
        d_stk_map = {(r.dt_str, r.c6): (r.is_zt, r.touch_zt, r.is_yizi, r.pct) for r in sub_act.itertuples(index=False)}
        r_elo = defaultdict(lambda: 100.0)
        p_last_idx = {}
        prev_p_stks = {}
        sorted_kpl_days = [kpl_days_map[k] for k in sorted(kpl_days_map.keys()) if k <= d3_date]
        for day_idx, d_entry in enumerate(sorted_kpl_days):
            dt = d_entry["date"]
            plates = d_entry.get("plates", [])
            for pname, c6_list in prev_p_stks.items():
                touches, seals, rets = 0, 0, []
                for sc6 in c6_list:
                    st = d_stk_map.get((dt, sc6))
                    if st is not None:
                        rets.append(st[3]); touches += int(st[1]); seals += int(st[0])
                if touches >= 2 and (seals / touches) < 0.50:
                    r_elo[pname] -= 12.0 * ((touches - seals) / touches)
                elif rets and np.mean(rets) < -0.025:
                    r_elo[pname] -= 10.0
                elif seals >= 2 and (seals / max(touches, 1)) >= 0.70:
                    r_elo[pname] += min(10.0, 5.0 + seals * 1.2)
                elif rets and np.mean(rets) > 0.025:
                    r_elo[pname] += 6.0
            for p_k in list(r_elo.keys()):
                if day_idx - p_last_idx.get(p_k, day_idx) > 3:
                    r_elo[p_k] = 100.0 + (r_elo[p_k] - 100.0) * 0.85
            new_p = {}
            for p in plates:
                pname = p.get("plate", "")
                stocks = p.get("stocks", [])
                if not pname or not stocks: continue
                c6_list = [str(s[0]).strip()[:6].zfill(6) for s in stocks]
                new_p[pname] = c6_list
                p_last_idx[pname] = day_idx
            prev_p_stks = new_p
        plate_elo_map = dict(r_elo)

    lh_map, surf_map, lhb_has_d3 = {}, {}, False
    if os.path.exists(LHB_PATH):
        try:
            lb = pd.read_parquet(LHB_PATH, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME"])
            lb_d3 = lb[lb["TRADE_DATE"].astype(str).str[:10] == d3_date]
            if not lb_d3.empty:
                lhb_has_d3 = True
                for c6_u, grp in lb_d3.groupby(lb_d3["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)):
                    seats = grp["OPERATEDEPT_NAME"].astype(str).tolist()
                    lh_map[c6_u] = sum(1 for s in seats if "拉萨" in s)
                    surf_map[c6_u] = any(SURF_YZ.search(s) for s in seats)
        except Exception as e:
            print(f"[WARN] live_3to4 LHB parquet error: {e}", file=sys.stderr)

    cands_b3, candidates = d3_df[d3_df["streak"] == 3]["c6"].tolist(), []
    if not lhb_has_d3 and cands_b3:
        for c6_u in cands_b3:
            seats_buy, seats_sell = [], []
            for side, s_list in [("BUY", seats_buy), ("SELL", seats_sell)]:
                try:
                    url = (
                        "https://datacenter-web.eastmoney.com/api/data/v1/get?"
                        f"reportName=RPT_BILLBOARD_DAILYDETAILS{side}&columns=TRADE_DATE,SECURITY_CODE,OPERATEDEPT_NAME&"
                        f"filter=(SECURITY_CODE%3D%22{c6_u}%22)&sortColumns=TRADE_DATE&sortTypes=-1&pageNumber=1&pageSize=50&source=WEB&client=WEB"
                    )
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=4) as resp:
                        js = json.loads(resp.read().decode("utf-8", "ignore"))
                        for r_item in (js.get("result") or {}).get("data") or []:
                            if str(r_item.get("TRADE_DATE", ""))[:10] == d3_date:
                                s_list.append(str(r_item.get("OPERATEDEPT_NAME", "")))
                except Exception as e:
                    print(f"[WARN] live_3to4 online LHB fallback failed for {c6_u} {side}: {e}", file=sys.stderr)
            if seats_buy:
                lh_map[c6_u] = sum(1 for s in seats_buy if "拉萨" in s)
                surf_map[c6_u] = any(SURF_YZ.search(s) for s in seats_buy)

    # 盘前雪球热帖数（严格 [D1 00:00:00, nxt_buy_date 09:25:00)，双只读库按 post_id 去重）
    xq_cnt_map = {}
    if cands_b3:
        d1_min = min(str(d3_df[d3_df["c6"] == c]["d1_dt_for_3b"].iloc[0] or d3_date) for c in cands_b3)
        end_cut = f"{nxt_buy_date} 09:25:00"
        xq_seen, xq_ts = defaultdict(set), defaultdict(list)
        cset = set(cands_b3)
        if os.path.exists(DB_XQ_GB):
            con_x = sqlite3.connect(f"file:{DB_XQ_GB}?mode=ro", uri=True)
            try:
                for sym, pid, cts in con_x.execute("SELECT symbol, post_id, created_time_str FROM xueqiu_posts WHERE created_time_str >= ? AND created_time_str < ?", (f"{d1_min} 00:00:00", end_cut)):
                    c6_s = str(sym)[:6].zfill(6)
                    if c6_s in cset and cts:
                        pk = str(pid).replace("xq_", "")
                        if pk not in xq_seen[c6_s]:
                            xq_seen[c6_s].add(pk); xq_ts[c6_s].append(str(cts))
            finally:
                con_x.close()
        if os.path.exists(DB_COMM):
            con_c = sqlite3.connect(f"file:{DB_COMM}?mode=ro", uri=True)
            try:
                for sym, pid, cts in con_c.execute("SELECT symbol, post_id, pub_datetime_cst FROM community_posts WHERE source='xueqiu' AND pub_datetime_cst >= ? AND pub_datetime_cst < ?", (f"{d1_min} 00:00:00", end_cut)):
                    c6_s = str(sym)[:6].zfill(6)
                    if c6_s in cset and cts:
                        pk = str(pid).replace("xq_", "")
                        if pk not in xq_seen[c6_s]:
                            xq_seen[c6_s].add(pk); xq_ts[c6_s].append(str(cts))
            finally:
                con_c.close()
        for c in cands_b3:
            d1_c = str(d3_df[d3_df["c6"] == c]["d1_dt_for_3b"].iloc[0] or d3_date)
            beg_c = f"{d1_c} 00:00:00"
            xq_cnt_map[c] = sum(1 for ts_v in xq_ts.get(c, []) if beg_c <= ts_v < end_cut)

    for c6 in cands_b3:
        r, ts = d3_df[d3_df["c6"] == c6].iloc[0], ths_map.get(c6, {})
        name = str(ts.get("name") or "").strip()
        if not name:
            try:
                q_r = urllib.request.urlopen(f"http://qt.gtimg.cn/q={'sh' if c6.startswith('60') else 'sz'}{c6}", timeout=3).read().decode("gbk", "ignore").split("~")
                if len(q_r) > 2: name = q_r[1].strip()
            except Exception:
                name = c6
        if "ST" in name.upper(): continue
        prev_is_yizi = bool(r["open"] >= r["zt_px"] - 0.011 and r["low"] >= r["zt_px"] - 0.011)
        opn_cnt = int(ts.get("open_num") or 0)
        fst = datetime.datetime.fromtimestamp(int(ts["first_limit_up_time"])).strftime("%H:%M:%S") if ts.get("first_limit_up_time") else "09:30:00"
        pos20_v = round(float(r["pos20_d0"]), 4) if pd.notna(r.get("pos20_d0")) else 0.50
        xq_2d_v = int(xq_cnt_map.get(c6, 0))

        # 锁仓缺失显式告警
        valid_holders = [x for x in holders.get(c6, []) if isinstance(x, (list, tuple)) and len(x) > 2 and str(x[0]) <= d3_date]
        if valid_holders:
            lock10 = float(max(valid_holders, key=lambda x: str(x[1]))[2])
            lock_missing = False
        else:
            lock10 = 38.0
            lock_missing = True
            print(f"[WARN] 标的 {c6} ({name}) 缺失截至 {d3_date} 的 PIT 前十大流通股东锁仓数据，标记 lock_missing=True，按中位数 38.0% 保守兜底！", file=sys.stderr)

        osh = float(r.get("oshare", 0.0) or 0.0)
        mcap = (float(r["close"]) * osh / 1e8) if osh > 0 else (float(r["amount"]) / float(r["turn"]) / 1e8 if r["turn"] > 0 else 50.0)
        reason, my_kws = ts.get("reason_type", ""), _extract_keywords(ts.get("reason_type", ""))
        plate_fb, plate_zt = [], []
        for s in ths_stocks:
            sc6 = str(s.get("code"))[:6]
            if sc6 != c6 and (my_kws & _extract_keywords(s.get("reason_type", ""))):
                plate_zt.append(sc6)
                if "首板" in s.get("high_days", ""): plate_fb.append(sc6)

        # 真实板块 Elo 映射
        matched_elos = []
        for kw in my_kws:
            for p_name, p_val in plate_elo_map.items():
                if kw in p_name or p_name in kw:
                    matched_elos.append(float(p_val))
        for p_name, p_val in plate_elo_map.items():
            if p_name in reason:
                matched_elos.append(float(p_val))
        p_elo_cand = round(max(matched_elos, default=100.0), 2)

        # 交易所监管函密集度判断
        ex_key = "SH" if c6.startswith("60") else "SZ"
        has_ex_reg = (len(ex_reg_stocks[ex_key]) >= 2)

        candidates.append({
            "code": c6, "name": name, "sig_date": d3_date, "buy_date": nxt_buy_date,
            "is_10cm_non_st": True, "prev_is_yizi": prev_is_yizi, "open_board_count": opn_cnt,
            "prev_to": round(float(r["turn"] * 100.0 if r["turn"] < 1.0 else r["turn"]), 2),
            "px_d3": round(float(r["close"]), 2), "lock_top10": round(lock10, 2), "lock_missing": lock_missing,
            "real_free_mcap": round(mcap * (1.0 - lock10 / 100.0), 2), "first_seal_time": fst,
            "mkt_max_board_prev": mkt_max_b, "p_elo": p_elo_cand,
            "plate": ts.get("reason_type", "主线题材"), "reason_type": reason,
            "has_tox_notice": c6 in tox_stk, "has_stock_reg": c6 in stk_reg, "has_ex_reg": has_ex_reg,
            "ex_reg_cnt": len(ex_reg_stocks[ex_key]),
            "surf_yz_buy": surf_map.get(c6, False), "lhb_lh_cnt": lh_map.get(c6, 0),
            "pos20_d0": pos20_v, "xq_cnt_2d": xq_2d_v,
            "plate_fb_codes": plate_fb, "plate_zt_codes": plate_zt,
        })
    cache = {
        "version": "3TO4_V40_PROD_20261117",
        "built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "d3_date": d3_date, "buy_date": nxt_buy_date, "candidates": candidates,
        "env": {"mkt_max_board_prev": mkt_max_b, "mkt_zt_prev": mkt_zt_prev,
                "prev_3b_dt_cnt": dt3_cnt, "csi_1d_prev": round(csi_1d, 4), "csi_5d_prev": round(csi_5d, 4)}
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f: json.dump(cache, f, ensure_ascii=False, indent=2)
    if verbose: print(f"[+] Premarket cache built in {time.time()-t0:.2f}s -> {CACHE_FILE} | {len(candidates)} candidates on {d3_date}")
    return cache
if __name__ == "__main__": build_premarket_cache()
