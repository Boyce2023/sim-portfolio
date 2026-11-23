#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""rd_incremental_sources.py — 五策略底层增量同步组件 (指数/龙虎榜/KPL合并/微观涨停池/调研库)"""
import os, sys, json, time, sqlite3, datetime, importlib.util, urllib.request
import pandas as pd, requests

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM_DIR}/data"
IDX_PATH = f"{SIM_DIR}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
LHB_DIR = f"{SIM_DIR}/backtest/2026-10-20-lhasa"
KPL_V2_PATH = f"{ROOT}/news-dashboard/output/kpl_plates_v2.jsonl"
KPL_MERGED_PATH = f"{DATA_DIR}/kpl_plates_2018_2026_merged.jsonl"
ZT_TAPE_DB = f"{DATA_DIR}/zt_micro_tape_5y_pit.db"
PIT_NOTICES_DB = f"{DATA_DIR}/cninfo_notices_5y_pit.db"
IR_QA_DB = f"{SIM_DIR}/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db"
THS_DIR = f"{DATA_DIR}/ths_limit_up_daily"
LHB_COLS = ["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_CODE", "OPERATEDEPT_NAME", "BUY", "SELL",
            "NET", "EXPLANATION", "CHANGE_TYPE", "CHANGE_RATE", "CLOSE_PRICE", "TRADE_ID"]
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

def sync_index_klines_cache(latest_dt: str) -> dict:
    cache = json.load(open(IDX_PATH, "r", encoding="utf-8")) if os.path.exists(IDX_PATH) else {}
    syms = ["sh000002", "sz399107", "sh000300", "sh000001", "sz399001"]
    for sym in syms:
        mp = cache.get(sym, {})
        url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData?symbol={sym}&scale=240&ma=no&datalen=60"
        try:
            txt = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=6).read().decode("utf-8", "ignore")
            i, j = txt.find("["), txt.rfind("]")
            if i >= 0 and j > i:
                for r in json.loads(txt[i:j + 1]):
                    mp[str(r["day"])[:10]] = float(r["close"])
        except Exception as e:
            print(f"[WARN] sina index kline {sym}: {e}", file=sys.stderr)
        if latest_dt not in mp:
            try:
                raw = urllib.request.urlopen(urllib.request.Request(f"http://qt.gtimg.cn/q={sym}", headers=UA), timeout=5).read().decode("gbk", "ignore")
                f = raw.split("~")
                if len(f) > 30 and float(f[3] or 0) > 0:
                    q_dt = f"{f[30][:4]}-{f[30][4:6]}-{f[30][6:8]}" if len(f[30]) >= 8 else latest_dt
                    mp[q_dt] = float(f[3])
            except Exception as e:
                print(f"[WARN] tencent index fallback {sym}: {e}", file=sys.stderr)
        cache[sym] = dict(sorted(mp.items()))
    tmp = IDX_PATH + ".tmp"
    json.dump(cache, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, IDX_PATH)
    return {k: max(v.keys()) for k, v in cache.items() if v}

def sync_lhb_parquets(latest_dt: str) -> dict:
    sess = requests.Session(); sess.trust_env = False
    res_max = {}
    for side in ("buy", "sell"):
        pq_path = f"{LHB_DIR}/lhb_{side}.parquet"
        old_df = pd.read_parquet(pq_path)
        max_old = str(old_df["TRADE_DATE"].max())[:10]
        start_dt = (datetime.date.fromisoformat(max_old) - datetime.timedelta(days=2)).isoformat()
        rep = f"RPT_BILLBOARD_DAILYDETAILS{side.upper()}"
        flt = f"(TRADE_DATE>='{start_dt}')(TRADE_DATE<='{latest_dt}')"
        got, pg, pages = [], 1, 1
        while pg <= pages:
            r = sess.get("https://datacenter-web.eastmoney.com/api/data/v1/get", params=dict(
                reportName=rep, columns=",".join(LHB_COLS), filter=flt, pageNumber=pg, pageSize=500,
                sortColumns="TRADE_DATE,SECURITY_CODE,TRADE_ID", sortTypes="1,1,1", source="WEB", client="WEB"
            ), headers=UA, timeout=20).json()
            res = r.get("result")
            if not res or not res.get("data"): break
            pages = int(res.get("pages") or 1)
            got.extend(res["data"])
            pg += 1
        if got:
            new_df = pd.DataFrame(got)[LHB_COLS]
            comb = pd.concat([old_df[LHB_COLS], new_df], ignore_index=True)
            comb["_dt10"] = comb["TRADE_DATE"].astype(str).str[:10]
            comb.drop_duplicates(subset=["_dt10", "SECURITY_CODE", "OPERATEDEPT_CODE", "TRADE_ID", "BUY", "SELL"], keep="last", inplace=True)
            comb.drop(columns=["_dt10"], inplace=True)
            comb.sort_values(["TRADE_DATE", "SECURITY_CODE"], inplace=True, kind="mergesort")
            tmp = pq_path + ".tmp"
            comb.to_parquet(tmp, index=False)
            os.replace(tmp, pq_path)
            res_max[side] = str(comb["TRADE_DATE"].max())[:10]
        else:
            res_max[side] = max_old
    return res_max

def sync_ths_kpl_and_micro_tape(trade_dates: list[str]) -> dict:
    latest_dt = trade_dates[-1]
    os.makedirs(THS_DIR, exist_ok=True)
    for dt in trade_dates[-3:]:
        out_p = f"{THS_DIR}/{dt}.json"
        if not os.path.exists(out_p) or dt == latest_dt:
            try:
                ymd = dt.replace("-", "")
                url = (f"https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=1&limit=200&"
                       f"field=199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004&"
                       f"filter=HS,GEM2STAR&order_field=330324&order_type=0&date={ymd}")
                info = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=10).read().decode("utf-8")).get("data", {}).get("info", [])
                if info:
                    json.dump({"date": dt, "archived_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "total_count": len(info), "stocks": info},
                              open(out_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[WARN] THS archive {dt}: {e}", file=sys.stderr)

    merged_dates = set()
    if os.path.exists(KPL_MERGED_PATH):
        with open(KPL_MERGED_PATH, "r", encoding="utf-8") as f:
            for ln in f:
                if ln.strip(): merged_dates.add(json.loads(ln).get("date"))
    if os.path.exists(KPL_V2_PATH):
        add_lines = []
        with open(KPL_V2_PATH, "r", encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    d = json.loads(ln).get("date")
                    if d and d not in merged_dates:
                        merged_dates.add(d); add_lines.append(ln.rstrip("\n"))
        if add_lines:
            with open(KPL_MERGED_PATH, "a", encoding="utf-8") as f:
                for ln in add_lines: f.write(ln + "\n")

    spec = importlib.util.spec_from_file_location("gap5", f"{SIM_DIR}/scripts/backfill_6gaps/backfill_gap5_zt_micro_tape.py")
    gap5 = importlib.util.module_from_spec(spec); spec.loader.exec_module(gap5)
    kpl = gap5.load_kpl_client()
    conn = sqlite3.connect(ZT_TAPE_DB, timeout=30.0)
    done_t = set(r[0] for r in conn.execute("SELECT trade_date FROM crawl_progress WHERE status='OK' AND stock_count > 0").fetchall())
    for dt in [d for d in trade_dates[-10:] if d not in done_t]:
        recs = gap5.fetch_day_tape(kpl, dt)
        if not recs and os.path.exists(f"{THS_DIR}/{dt}.json"):
            for s in json.load(open(f"{THS_DIR}/{dt}.json", encoding="utf-8")).get("stocks", []):
                c6 = str(s.get("code", ""))[:6]
                fts = int(s.get("first_limit_up_time") or 0)
                fstr = datetime.datetime.fromtimestamp(fts).strftime("%H:%M:%S") if fts > 1000000000 else "09:30:00"
                raw_open_num = s.get("open_num")
                open_cnt_val = int(raw_open_num) if raw_open_num is not None else None
                recs.append({"trade_date": dt, "sec_code": c6, "sec_name": str(s.get("name", "")), "first_seal_time": fstr,
                             "first_seal_ts": fts, "seal_amount": float(s.get("order_amount") or 0), "continuous_plate_tag": str(s.get("high_days", "")),
                             "board_count": 1, "open_board_count": open_cnt_val,
                             "plate_name": str(s.get("reason_type", "")).split("+")[0], "reason_desc": str(s.get("reason_type", ""))[:300]})
        if recs:
            conn.executemany("INSERT OR REPLACE INTO zt_micro_tape (trade_date,sec_code,sec_name,first_seal_time,first_seal_ts,seal_amount,continuous_plate_tag,board_count,open_board_count,plate_name,reason_desc) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             [(r["trade_date"], r["sec_code"], r["sec_name"], r["first_seal_time"], r["first_seal_ts"], r["seal_amount"], r["continuous_plate_tag"], r["board_count"], r["open_board_count"], r["plate_name"], r["reason_desc"]) for r in recs])
            conn.execute("INSERT OR REPLACE INTO crawl_progress (trade_date, stock_count, status, updated_at) VALUES (?, ?, 'OK', CURRENT_TIMESTAMP)", (dt, len(recs)))
            conn.commit()
    max_tape = conn.execute("SELECT max(trade_date) FROM zt_micro_tape").fetchone()[0]
    conn.close()
    return {"kpl_merged_max": max(merged_dates) if merged_dates else "", "zt_micro_tape_max": max_tape or ""}
