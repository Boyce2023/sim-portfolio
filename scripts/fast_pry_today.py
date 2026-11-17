#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_pry_today.py — 超跌橡皮筋撬板次日弱转强 V1.0 (满165分高严档, s_pry, 纯单仓第4顺位) 实盘极速决策引擎
模式:
  1. --build-cache : 盘后读取只读行情/股东/公告/龙虎榜构建下一交易日盘前缓存 (pry_premarket_cache.json)
  2. --premarket   : 早盘 09:15 前秒读缓存输出候选池、静态预评分与动态止盈幅度
  3. 默认盘中秒跑  : 09:25:03 秒读缓存并抓腾讯实时竞价，输出唯一头名指令与盘前限价止盈公式
  4. --date / --recent : 查询五年严校台账 v1_oversold_pry_165_strict_ledger.csv
"""
import os, sys, json, re, sqlite3, argparse, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np, pandas as pd, pyarrow.dataset as ds

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
DATA_DIR = f"{ROOT}/sim-portfolio/data"
CACHE_FILE = f"{DATA_DIR}/pry_premarket_cache.json"
A_DAILY = f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet"
HOLDERS_PATH = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"
DB_NOTICES = f"{ROOT}/sim-portfolio/backtest/2026-08-24-daban/notices.db"
DB_PIT_NOTICES = f"{DATA_DIR}/cninfo_notices_5y_pit.db"
LHB_PATH = f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet"
LHB_SELL_PATH = f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_sell.parquet"
LEDGER_CSV = f"{ROOT}/sim-portfolio/backtests_astock2/p5_full_pry_universe/v1_oversold_pry_165_strict_ledger.csv"
TOX_RE = re.compile(r"(?:减持计划|股东减持|立案调查|收到立案|退市风险|违法违规)")

def _query_em_lhb_online(c6: str, sig_date: str) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    buys, sells = [], []
    for side, out_list in [("BUY", buys), ("SELL", sells)]:
        url = (
            "https://datacenter-web.eastmoney.com/api/data/v1/get?"
            f"reportName=RPT_BILLBOARD_DAILYDETAILS{side}&columns=TRADE_DATE,SECURITY_CODE,OPERATEDEPT_NAME,{side}&"
            f"filter=(SECURITY_CODE%3D%22{c6}%22)&sortColumns=TRADE_DATE&sortTypes=-1&pageNumber=1&pageSize=50&source=WEB&client=WEB"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8", "ignore"))
                for r in (data.get("result") or {}).get("data") or []:
                    if str(r.get("TRADE_DATE", ""))[:10] == sig_date:
                        out_list.append((str(r.get("OPERATEDEPT_NAME", "")).strip(), float(r.get(side) or 0.0)))
        except Exception as e:
            print(f"[WARN] fast_pry online LHB {side} fallback failed for {c6}: {e}", file=sys.stderr)
    return buys, sells

def fetch_single_chunk(ch: list[str]) -> dict[str, dict]:
    q_list = [f"{'sh' if c.startswith('60') else 'sz'}{c}" for c in ch]
    url = f"http://qt.gtimg.cn/q={','.join(q_list)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    res = {}
    for retry in range(3):
        try:
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                for line in resp.read().decode("gbk", errors="ignore").strip().split(";"):
                    if "~" not in line: continue
                    p = line.split("~")
                    if len(p) > 30:
                        c6, px, pc, op = p[2].strip(), float(p[3] or 0), float(p[4] or 0), float(p[5] or 0)
                        b1, s1 = float(p[10] or 0), float(p[20] or 0)
                        hi = float(p[33] or 0) if len(p) > 34 else px
                        lo = float(p[34] or 0) if len(p) > 34 else px
                        amt = float(p[37] or 0) * 10000.0 if len(p) > 38 else 0.0
                        trn = float(p[38] or 0) / 100.0 if len(p) > 38 else 0.0
                        dt8 = str(p[30]).strip()[:8] if len(p) > 30 else ""
                        q_dt = f"{dt8[:4]}-{dt8[4:6]}-{dt8[6:8]}" if len(dt8) == 8 and dt8.isdigit() else ""
                        op_px = op if op > 0 else px
                        op_pct = (op_px / pc - 1.0) if pc > 0 else -1.0
                        zt_px = np.floor(pc * 1.10 * 100.0 + 0.5) / 100.0 if pc > 0 else 999.0
                        is_yz = bool(op_px >= zt_px - 0.011 or (b1 > 0 and s1 == 0 and op_pct >= 0.090))
                        res[c6] = {"name": p[1], "open": op_px, "close": px, "high": hi, "low": lo, "amount": amt, "turn": trn, "q_dt": q_dt, "pre_c": pc, "open_pct": op_pct, "is_zt_open": op_px >= zt_px - 0.011, "is_yizi": is_yz}
            if res:
                return res
        except Exception:
            if retry == 2:
                print(f"[WARN] fast_pry chunk failed after 3 attempts: {ch[:3]}...", file=sys.stderr)
    return res

def fetch_tencent_parallel(codes: list[str], max_workers: int = 24, batch_size: int = 80) -> dict[str, dict]:
    if not codes: return {}
    chunks = [codes[i:i + batch_size] for i in range(0, len(codes), batch_size)]
    res = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch_single_chunk, ch) for ch in chunks]
        for f in as_completed(futures):
            res.update(f.result())
    return res

def build_premarket_cache(verbose: bool = True) -> dict:
    cutoff = (pd.Timestamp.now() - pd.Timedelta(days=65)).strftime("%Y-%m-%d")
    cols = ["date", "ticker", "open", "high", "low", "close", "turn", "oshare", "amount"]
    df = ds.dataset(A_DAILY, format="parquet").scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp(cutoff))).to_table().to_pandas()
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["c6"].str.startswith(("00", "60"))].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    max_p_date = df["dt_str"].max()
    try:
        idx_raw = urllib.request.urlopen("http://qt.gtimg.cn/q=sh000300", timeout=3).read().decode("gbk", errors="ignore")
        idx_p = idx_raw.split("~")
        dt14 = str(idx_p[30]).strip() if len(idx_p) > 30 else ""
        q_dt = f"{dt14[:4]}-{dt14[4:6]}-{dt14[6:8]}" if len(dt14) >= 8 and dt14[:8].isdigit() else ""
        q_hhmm = int(dt14[8:12]) if len(dt14) >= 12 and dt14[8:12].isdigit() else 0
        if q_dt > max_p_date and q_hhmm >= 1500:
            last_sub = df[df["dt_str"] == max_p_date]
            c_list = last_sub["c6"].tolist()
            tk_map = dict(zip(last_sub["c6"], last_sub["ticker"]))
            osh_map = dict(zip(last_sub["c6"], last_sub["oshare"]))
            live_q = fetch_tencent_parallel(c_list, max_workers=24, batch_size=80)
            patch_rows = [
                {"date": pd.Timestamp(q_dt), "ticker": tk_map[c], "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"], "turn": q["turn"], "oshare": osh_map.get(c, np.nan), "amount": q["amount"], "c6": c, "dt_str": q_dt}
                for c in c_list if (q := live_q.get(c)) is not None and q.get("q_dt") == q_dt and q.get("close", 0) > 0
            ]
            if len(patch_rows) >= 2000:
                df = pd.concat([df, pd.DataFrame(patch_rows)], ignore_index=True)
                df.drop_duplicates(subset=["c6", "dt_str"], keep="last", inplace=True)
    except Exception as e:
        print(f"[WARN] fast_pry close patch skipped: {e}", file=sys.stderr)
    df.sort_values(["c6", "dt_str"], inplace=True)
    g = df.groupby("c6")
    df["pre_c"] = g["close"].shift(1)
    df["zt_px"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["dt_px"] = np.floor(df["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_px"] - 0.011) & (df["pre_c"] > 0)
    df["is_dt"] = (df["close"] <= df["dt_px"] + 0.011) & (df["pre_c"] > 0)
    df["touch_dt"] = (df["low"] <= df["dt_px"] + 0.011) & (df["pre_c"] > 0)
    sig_date = sorted(df["dt_str"].unique())[-1]
    all_main_codes = sorted(df[df["dt_str"] == sig_date]["c6"].unique().tolist())

    holders = json.load(open(HOLDERS_PATH)) if os.path.exists(HOLDERS_PATH) else {}
    sig_ts = pd.Timestamp(sig_date)
    nxt_buy_date = (sig_ts + pd.Timedelta(days=(3 if sig_ts.weekday() == 4 else 1))).strftime("%Y-%m-%d")
    d90 = (sig_ts - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    tox_codes = set()
    if os.path.exists(DB_NOTICES):
        con = sqlite3.connect(f"file:{DB_NOTICES}?mode=ro", uri=True)
        try:
            for c_raw, title in con.execute("SELECT code, title FROM notice WHERE ndate >= ?", (d90,)):
                if TOX_RE.search(str(title)):
                    tox_codes.add(str(c_raw).strip()[:6].zfill(6))
        except Exception as e:
            print(f"[WARN] fast_pry DB_NOTICES error: {e}", file=sys.stderr)
        finally:
            con.close()
    if os.path.exists(DB_PIT_NOTICES):
        con = sqlite3.connect(f"file:{DB_PIT_NOTICES}?mode=ro", uri=True)
        try:
            for c_raw, title in con.execute("SELECT sec_code, title FROM notices WHERE pub_datetime_cst >= ?", (d90,)):
                if TOX_RE.search(str(title)):
                    tox_codes.add(str(c_raw).strip()[:6].zfill(6))
        except Exception as e:
            print(f"[WARN] fast_pry DB_PIT_NOTICES error: {e}", file=sys.stderr)
        finally:
            con.close()

    lhb_inst_net_pos, lhb_lhasa, lhb_has_sig_date = set(), {}, False
    inst_buy_map = defaultdict(float)
    inst_sell_map = defaultdict(float)
    tot_buy_map = defaultdict(float)
    lhasa_buy_map = defaultdict(float)

    if os.path.exists(LHB_PATH):
        try:
            ldf_b = pd.read_parquet(LHB_PATH, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"])
            ldf_b = ldf_b[ldf_b["TRADE_DATE"].astype(str).str[:10] == sig_date]
            if not ldf_b.empty:
                lhb_has_sig_date = True
                for r in ldf_b.itertuples(index=False):
                    c6_s = str(r.SECURITY_CODE)[:6].zfill(6)
                    dept = str(r.OPERATEDEPT_NAME)
                    amt = float(r.BUY or 0.0)
                    tot_buy_map[c6_s] += amt
                    if "机构专用" in dept:
                        inst_buy_map[c6_s] += amt
                    if "拉萨" in dept:
                        lhasa_buy_map[c6_s] += amt
        except Exception as e:
            print(f"[WARN] fast_pry LHB buy parquet error: {e}", file=sys.stderr)

    if os.path.exists(LHB_SELL_PATH):
        try:
            ldf_s = pd.read_parquet(LHB_SELL_PATH, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "SELL"])
            ldf_s = ldf_s[ldf_s["TRADE_DATE"].astype(str).str[:10] == sig_date]
            if not ldf_s.empty:
                for r in ldf_s.itertuples(index=False):
                    c6_s = str(r.SECURITY_CODE)[:6].zfill(6)
                    dept = str(r.OPERATEDEPT_NAME)
                    amt = float(r.SELL or 0.0)
                    if "机构专用" in dept:
                        inst_sell_map[c6_s] += amt
        except Exception as e:
            print(f"[WARN] fast_pry LHB sell parquet error: {e}", file=sys.stderr)

    for c6_k in set(list(tot_buy_map.keys()) + list(inst_sell_map.keys())):
        tb = tot_buy_map[c6_k]
        lhb_lhasa[c6_k] = (lhasa_buy_map[c6_k] / tb) if tb > 0 else 0.0
        if inst_buy_map[c6_k] - inst_sell_map[c6_k] > 0:
            lhb_inst_net_pos.add(c6_k)

    st_set = set()
    st_json_p = f"{DATA_DIR}/st_universe.json"
    if os.path.exists(st_json_p):
        try:
            st_set = {str(x)[:6].zfill(6) for x in json.load(open(st_json_p, encoding="utf-8")).get("codes", [])}
        except Exception:
            pass
    cands = []
    for c6, sub in df.groupby("c6"):
        if len(sub) < 21 or c6 in tox_codes or c6 in st_set: continue
        r = sub.iloc[-1]
        if r["dt_str"] != sig_date or not r["touch_dt"] or r["is_dt"] or r["close"] < 2.0: continue
        w20 = sub.iloc[-20:]
        if int(w20["is_zt"].sum()) > 0: continue
        ma20, max20, ma10 = float(w20["close"].mean()), float(w20["close"].max()), float(sub.iloc[-10:]["close"].mean())
        c_ma20, dd20, b10 = r["close"] / ma20 - 1.0, r["close"] / max20, r["close"] / ma10 - 1.0
        if c_ma20 > -0.15 or dd20 > 0.80: continue
        if not lhb_has_sig_date:
            em_buys, em_sells = _query_em_lhb_online(c6, sig_date)
            if em_buys or em_sells:
                tot_b = sum(b for _, b in em_buys)
                lh_b = sum(b for s, b in em_buys if "拉萨" in s)
                lhb_lhasa[c6] = (lh_b / tot_b) if tot_b > 0 else 0.0
                inst_b = sum(b for s, b in em_buys if "机构专用" in s)
                inst_s = sum(s for s_dept, s in em_sells if "机构专用" in s_dept)
                if inst_b - inst_s > 0:
                    lhb_inst_net_pos.add(c6)
        st = 0
        for k in range(len(sub) - 2, -1, -1):
            if sub.iloc[k]["close"] < sub.iloc[k]["pre_c"]: st += 1
            else: break
        vr = float(r["amount"] / max(1.0, sub.iloc[-6:-1]["amount"].mean()))
        raw_h = holders.get(c6, [])
        h_list = [x for x in raw_h if isinstance(x, (list, tuple)) and len(x) > 2 and str(x[0]) <= sig_date]
        if h_list:
            lock = float(max(h_list, key=lambda x: str(x[1]))[2])
        else:
            h_dict = [x for x in raw_h if isinstance(x, dict) and str(x.get("ann_date", "")) <= sig_date]
            lock = float(h_dict[-1].get("top10_ratio", 0.0)) if h_dict else 0.0
        fmcap = float(r["close"] * r["oshare"] * (1.0 - lock / 100.0) / 1e8) if r["oshare"] > 0 else 99.0
        ret10 = float(r["close"] / sub.iloc[-11]["close"] - 1.0) if len(sub) >= 11 else -0.15
        sc = 100 + (20 if b10 <= -0.15 else 0) + (15 if st >= 4 else 0) + (15 if c_ma20 <= -0.22 else 0)
        sc += (15 if fmcap <= 25.0 else 0) + (10 if r["close"] > r["open"] else 0) + (10 if vr >= 1.5 else 0)
        sc += (10 if lock >= 50.0 else 0) + (10 if c6 in lhb_inst_net_pos else 0) - (20 if lhb_lhasa.get(c6, 0.0) > 0.25 else 0)
        cands.append({"code": c6, "close": round(float(r["close"]), 2), "static_score": int(sc), "max_possible": int(sc + 15),
                      "bias10": round(b10, 4), "c_ma20": round(c_ma20, 4), "down_streak": st, "free_mcap": round(fmcap, 2),
                      "dyn_tp_pct": round(float(np.clip(0.45 * abs(ret10), 0.06, 0.16)) * 100, 2)})
    built_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    cache = {"built_at": built_at, "sig_date": sig_date, "buy_date": nxt_buy_date,
             "candidates": sorted(cands, key=lambda x: (-x["static_score"], x["bias10"])), "main_codes_sample": all_main_codes}
    json.dump(cache, open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    if verbose: print(f"[+] 超跌撬板盘前缓存已生成 ({sig_date}): 纯超跌翘板候选 {len(cands)} 只 (最高可冲165分候选 {sum(x['max_possible']>=165 for x in cands)} 只)")
    return cache

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-cache", action="store_true")
    ap.add_argument("--premarket", action="store_true")
    ap.add_argument("--date", type=str, default="")
    ap.add_argument("--recent", type=int, default=0)
    args = ap.parse_args()
    if args.date or args.recent > 0:
        df = pd.read_csv(LEDGER_CSV)
        sub = df[df["buy_date"] == args.date] if args.date else df.sort_values("buy_date").tail(args.recent)
        print(sub[["buy_date", "exit_date", "code", "name", "score", "o_pct", "bias10", "net_ret"]].to_string(index=False))
        return
    if args.build_cache or not os.path.exists(CACHE_FILE):
        cache = build_premarket_cache(verbose=True)
        if args.build_cache: return
    else:
        cache = json.load(open(CACHE_FILE, "r", encoding="utf-8"))
    cands = cache.get("candidates", [])
    if args.premarket:
        print(f"=== 超跌橡皮筋撬板 V1.0 (s_pry, 第3顺位, 满165分) 盘前候选 [信号日 {cache.get('sig_date')}] ===")
        print("无符合四道硬门的纯超跌翘板股" if not cands else pd.DataFrame(cands).to_string(index=False))
        return
    if not cands:
        print(f"[s_pry 第3顺位] 信号日 {cache.get('sig_date')} 无纯超跌翘板候选，今日空缺顺延至第4顺位一进二。")
        return
    q_cand = fetch_tencent_parallel([x["code"] for x in cands])
    all_codes = cache.get("main_codes_sample", [])
    q_mkt = fetch_tencent_parallel(all_codes, max_workers=24, batch_size=80)
    print(f"[*] 全市场竞价行情获取成功: {len(q_mkt)} / {len(all_codes)} 只")
    if len(q_mkt) < min(len(all_codes) * 0.9, 4500):
        print(f"[WARN] 全市场竞价行情返回股票数偏低 ({len(q_mkt)} < 4500)，请排查网络！", file=sys.stderr)
    zt_open_cnt = sum(1 for v in q_mkt.values() if v.get("is_zt_open"))
    passed = []
    for c in cands:
        q = q_cand.get(c["code"])
        if not q or "ST" in str(q.get("name", "")).upper() or q["is_yizi"] or not (0.0 <= q["open_pct"] <= 0.05): continue
        tot = c["static_score"] + (15 if zt_open_cnt >= 12 else 0)
        if tot >= 165:
            tp_px = round(q["open"] * (1.0 + c["dyn_tp_pct"] / 100.0), 2)
            passed.append({**c, "name": q["name"], "open": q["open"], "open_pct": round(q["open_pct"]*100, 2), "score": tot, "tp_px": tp_px})
    passed.sort(key=lambda x: (-x["score"], x["bias10"]))
    print(f"[s_pry 第3顺位] 09:25全市场竞价涨停={zt_open_cnt}家 | 满165分过线={len(passed)}只")
    if passed: print("唯一头名指令:", passed[0])

if __name__ == "__main__":
    main()
