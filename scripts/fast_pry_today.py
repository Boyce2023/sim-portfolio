#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_pry_today.py — 超跌橡皮筋撬板次日弱转强 V2.1 (满165分高严档, s_pry, 第3顺位, XF30_V21动态阶梯卖法) 实盘极速决策引擎
五年零穿越验证基准 (XF30_V21, f3_pry):
  P165单仓: 16笔 / 胜率 87.50% / 净值 2.4400x / 回撤 19.15% / 25日等权 3.8110x
V2.1 四步动态阶梯卖法 (买点/四道硬门/10项整数打分 100% 沿用 V1.0 不变):
  1. 09:25 熔断: 每日 09:25 全场竞价涨停 < 5 家无条件开盘清仓
  2. T+1 分化: 盘前不挂低位止盈单放飞涨停(转连板至断板); 未涨停且未触发D0强真阳豁免时14:55较前收跌超1.5%清(D0封死跌停则T+1 09:25止损)
  3. 双因子加成(+3%/+3%, 总上限18.0%): 买入日收光头强真阳(close>open且CLV>=0.70)免T+1尾盘弱斩且+3%; 前日全场跌停<10家(止血)+3%
  4. 时间阶梯: T+2挂 clip(0.45*|ret10|,6%,16%)+加成; T+3基准降至+5.0%+加成; T+4基准降至+2.0%+加成且收盘必清
模式:
  1. --build-cache : 盘后读取只读行情/股东/公告/龙虎榜构建下一交易日盘前缓存 (pry_premarket_cache.json)
  2. --premarket   : 早盘 09:15 前秒读缓存输出候选池、静态预评分与 V2.1 阶梯止盈说明
  3. 默认盘中秒跑  : 09:25:03 秒读缓存并抓腾讯实时竞价，输出唯一头名指令与 V2.1 阶梯挂单公式
  4. --hold <CODE> : [--buy-date YYYY-MM-DD --buy-px FLOAT] 实时检查D0 CLV/前日跌停/今早涨停并打印T+0~T+4精确挂单价
  5. --date / --recent : 查询五年严校台账 v1_oversold_pry_165_strict_ledger.csv
"""
import os, sys, json, re, math, ssl, datetime, sqlite3, argparse, urllib.request
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
LHB_CAT_EXPLAIN_RE = re.compile(r"(?:10个交易日|30个交易日|严重异常)")
LHB_CAT_NAMES = {"自然人", "中小投资者", "其他自然人", "机构投资者", "深股通投资者", "机构", "沪股通", "投资者分类"}

def _load_st_set() -> set[str]:
    st_set = set()
    st_p = f"{DATA_DIR}/st_universe.json"
    if os.path.exists(st_p):
        try:
            st_set = {str(x)[:6].zfill(6) for x in json.load(open(st_p, encoding="utf-8")).get("codes", [])}
        except Exception:
            pass
    csrc_p = f"{DATA_DIR}/csrc_industry_l2.csv"
    if os.path.exists(csrc_p):
        try:
            _nm = pd.read_csv(csrc_p, usecols=["code", "code_name"]).fillna("")
            for _rc, _rn in zip(_nm["code"], _nm["code_name"]):
                _rns = str(_rn)
                if "ST" in _rns.upper() or "退" in _rns:
                    st_set.add(str(_rc)[-6:].zfill(6))
        except Exception:
            pass
    return st_set

def _count_mkt_0925_zt_open(q_mkt: dict[str, dict], st_set: set[str]) -> tuple[int, int, int, str]:
    """统一口径统计 09:25 非ST全场竞价涨停、实时涨停与跌停家数（强校 q_dt == mkt_qdt）。"""
    mkt_qdt = max((v.get("q_dt", "") for v in q_mkt.values() if v.get("q_dt")), default="")
    zt_open = now_zt = now_dt = 0
    for c_k, v in q_mkt.items():
        if c_k in st_set or v.get("q_dt") != mkt_qdt:
            continue
        nm = str(v.get("name", ""))
        if "ST" in nm.upper() or "退" in nm:
            continue
        if v.get("is_zt_open"):
            zt_open += 1
        px, pc = float(v.get("close", 0) or 0), float(v.get("pre_c", 0) or 0)
        if px > 0 and pc > 0:
            if px >= float(np.floor(pc * 1.10 * 100.0 + 0.5) / 100.0) - 0.011:
                now_zt += 1
            if px <= float(np.floor(pc * 0.90 * 100.0 + 0.5) / 100.0) + 0.011:
                now_dt += 1
    return zt_open, now_zt, now_dt, mkt_qdt

def _query_em_lhb_online(c6: str, sig_date: str) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    b_by_tid, s_by_tid, meta = defaultdict(list), defaultdict(list), {}
    for side, dst, is_b in [("BUY", b_by_tid, True), ("SELL", s_by_tid, False)]:
        url = (
            "https://datacenter-web.eastmoney.com/api/data/v1/get?"
            f"reportName=RPT_BILLBOARD_DAILYDETAILS{side}&columns=TRADE_DATE,SECURITY_CODE,OPERATEDEPT_NAME,BUY,SELL,EXPLANATION,TRADE_ID&"
            f"filter=(SECURITY_CODE%3D%22{c6}%22)&sortColumns=TRADE_DATE&sortTypes=-1&pageNumber=1&pageSize=60&source=WEB&client=WEB"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8", "ignore"))
                for r in (data.get("result") or {}).get("data") or []:
                    if str(r.get("TRADE_DATE", ""))[:10] != sig_date:
                        continue
                    exp_s, dept_s = str(r.get("EXPLANATION") or ""), str(r.get("OPERATEDEPT_NAME") or "").strip()
                    if LHB_CAT_EXPLAIN_RE.search(exp_s) or dept_s in LHB_CAT_NAMES:
                        continue
                    tid_s = str(r.get("TRADE_ID") or "")
                    bf, sf = float(r.get("BUY") or 0.0), float(r.get("SELL") or 0.0)
                    dst[tid_s].append((dept_s, bf if is_b else sf))
                    cur = meta.get(tid_s)
                    if cur is None:
                        meta[tid_s] = ["连续" in exp_s, bf + sf]
                    else:
                        cur[1] += bf + sf
        except Exception as e:
            print(f"[WARN] fast_pry online LHB {side} fallback failed for {c6}: {e}", file=sys.stderr)
    if not meta:
        return [], []
    best_tid = min(meta.items(), key=lambda kv: (1 if kv[1][0] else 0, -kv[1][1], kv[0]))[0]
    return b_by_tid.get(best_tid, []), s_by_tid.get(best_tid, [])

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
    st_set = _load_st_set()
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "turn", "oshare", "amount"]
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
                {"date": pd.Timestamp(q_dt), "ticker": tk_map[c], "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"], "adj_close": q["close"], "turn": q["turn"], "oshare": osh_map.get(c, np.nan), "amount": q["amount"], "c6": c, "dt_str": q_dt}
                for c in c_list if (q := live_q.get(c)) is not None and q.get("q_dt") == q_dt and q.get("close", 0) > 0
            ]
            if len(patch_rows) >= 2000:
                df = pd.concat([df, pd.DataFrame(patch_rows)], ignore_index=True)
                df.drop_duplicates(subset=["c6", "dt_str"], keep="last", inplace=True)
    except Exception as e:
        print(f"[WARN] fast_pry close patch skipped: {e}", file=sys.stderr)
    df.sort_values(["c6", "dt_str"], inplace=True)
    df["adjf"] = np.where((df["close"] > 0) & df["adj_close"].notna() & (df["adj_close"] > 0), df["adj_close"] / df["close"], 1.0)
    df["ac"] = df["close"] * df["adjf"]
    g = df.groupby("c6")
    df["pre_c"] = g["close"].shift(1) * g["adjf"].shift(1) / df["adjf"]
    df["zt_px"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["dt_px"] = np.floor(df["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_px"] - 0.011) & (df["pre_c"] > 0)
    df["is_dt"] = (df["close"] <= df["dt_px"] + 0.011) & (df["pre_c"] > 0)
    df["touch_dt"] = (df["low"] <= df["dt_px"] + 0.011) & (df["pre_c"] > 0)
    sig_date = sorted(df["dt_str"].unique())[-1]
    all_main_codes = sorted(df[(df["dt_str"] == sig_date) & (~df["c6"].isin(st_set))]["c6"].unique().tolist())

    holders = json.load(open(HOLDERS_PATH)) if os.path.exists(HOLDERS_PATH) else {}
    sig_ts = pd.Timestamp(sig_date)
    nxt_buy_date = (sig_ts + pd.Timedelta(days=(3 if sig_ts.weekday() == 4 else 1))).strftime("%Y-%m-%d")
    d90 = (sig_ts - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    tox_codes = set()
    if os.path.exists(DB_NOTICES):
        con = sqlite3.connect(f"file:{DB_NOTICES}?mode=ro", uri=True)
        try:
            for c_raw, title in con.execute("SELECT code, title FROM notice WHERE ndate >= ? AND ndate < ?", (d90, nxt_buy_date)):
                if TOX_RE.search(str(title)):
                    tox_codes.add(str(c_raw).strip()[:6].zfill(6))
        except Exception as e:
            print(f"[WARN] fast_pry DB_NOTICES error: {e}", file=sys.stderr)
        finally:
            con.close()
    if os.path.exists(DB_PIT_NOTICES):
        con = sqlite3.connect(f"file:{DB_PIT_NOTICES}?mode=ro", uri=True)
        try:
            for c_raw, title in con.execute("SELECT sec_code, title FROM notices WHERE pub_datetime_cst >= ? AND pub_datetime_cst < ?", (d90, f"{nxt_buy_date} 09:25:00")):
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

    try:
        lhb_cols = ["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY", "SELL", "EXPLANATION", "TRADE_ID"]
        b_by_tid, s_by_tid, tid_meta = defaultdict(list), defaultdict(list), {}
        for p_pq, dst_map, is_b in [(LHB_PATH, b_by_tid, True), (LHB_SELL_PATH, s_by_tid, False)]:
            if not os.path.exists(p_pq):
                continue
            ldf = pd.read_parquet(p_pq, columns=lhb_cols)
            ldf = ldf[ldf["TRADE_DATE"].astype(str).str[:10] == sig_date]
            if not ldf.empty and is_b:
                lhb_has_sig_date = True
            for r in ldf.itertuples(index=False):
                exp_s, dept_s = str(r.EXPLANATION or ""), str(r.OPERATEDEPT_NAME or "").strip()
                if LHB_CAT_EXPLAIN_RE.search(exp_s) or dept_s in LHB_CAT_NAMES:
                    continue
                c6_s = str(r.SECURITY_CODE)[:6].zfill(6)
                tid_s = str(r.TRADE_ID or "")
                bf, sf = float(r.BUY or 0.0), float(r.SELL or 0.0)
                dst_map[(c6_s, tid_s)].append((dept_s, bf if is_b else sf))
                cur = tid_meta.get((c6_s, tid_s))
                if cur is None:
                    tid_meta[(c6_s, tid_s)] = ["连续" in exp_s, bf + sf]
                else:
                    cur[1] += bf + sf
        best_tid = {}
        for (c6_s, tid_s), (is3, vol) in tid_meta.items():
            cand_k = (1 if is3 else 0, -vol, tid_s)
            prev_b = best_tid.get(c6_s)
            if prev_b is None or cand_k < prev_b[0]:
                best_tid[c6_s] = (cand_k, tid_s)
        for c6_s, (_, tid_s) in best_tid.items():
            for dept, amt in b_by_tid.get((c6_s, tid_s), []):
                tot_buy_map[c6_s] += amt
                if "机构专用" in dept:
                    inst_buy_map[c6_s] += amt
                if "拉萨" in dept:
                    lhasa_buy_map[c6_s] += amt
            for dept, amt in s_by_tid.get((c6_s, tid_s), []):
                if "机构专用" in dept:
                    inst_sell_map[c6_s] += amt
    except Exception as e:
        print(f"[WARN] fast_pry LHB parquet error: {e}", file=sys.stderr)

    for c6_k in set(list(tot_buy_map.keys()) + list(inst_sell_map.keys())):
        tb = tot_buy_map[c6_k]
        lhb_lhasa[c6_k] = (lhasa_buy_map[c6_k] / tb) if tb > 0 else 0.0
        if inst_buy_map[c6_k] - inst_sell_map[c6_k] > 0:
            lhb_inst_net_pos.add(c6_k)

    # st_set 已于前段统一加载（含 st_universe.json + ST/退名称过滤）
    cands = []
    for c6, sub in df.groupby("c6"):
        if len(sub) < 21 or c6 in tox_codes or c6 in st_set: continue
        r = sub.iloc[-1]
        if r["dt_str"] != sig_date or not r["touch_dt"] or r["is_dt"] or r["close"] < 2.0: continue
        w20 = sub.iloc[-20:]
        if int(w20["is_zt"].sum()) > 0: continue
        ma20, max20, ma10 = float(w20["ac"].mean()), float(w20["ac"].max()), float(sub.iloc[-10:]["ac"].mean())
        c_ma20, dd20, b10 = float(r["ac"]) / ma20 - 1.0, float(r["ac"]) / max20, float(r["ac"]) / ma10 - 1.0
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
        h_list = [x for x in raw_h if isinstance(x, (list, tuple)) and len(x) > 2 and "2000-01-01" <= str(x[0])[:10] <= sig_date]
        if h_list:
            lock = float(max(h_list, key=lambda x: str(x[1]))[2])
        else:
            h_dict = [x for x in raw_h if isinstance(x, dict) and str(x.get("ann_date", "")) <= sig_date]
            lock = float(h_dict[-1].get("top10_ratio", 0.0)) if h_dict else 0.0
        fmcap = float(r["close"] * r["oshare"] * (1.0 - lock / 100.0) / 1e8) if r["oshare"] > 0 else 99.0
        ret10 = float(r["ac"] / sub.iloc[-11]["ac"] - 1.0) if len(sub) >= 11 else -0.15
        sc = 100 + (20 if b10 <= -0.15 else 0) + (15 if st >= 4 else 0) + (15 if c_ma20 <= -0.22 else 0)
        sc += (15 if fmcap <= 25.0 else 0) + (10 if r["close"] > r["open"] else 0) + (10 if vr >= 1.5 else 0)
        sc += (10 if lock >= 50.0 else 0) + (10 if c6 in lhb_inst_net_pos else 0) - (20 if lhb_lhasa.get(c6, 0.0) > 0.25 else 0)
        cands.append({"code": c6, "close": round(float(r["close"]), 2), "static_score": int(sc), "max_possible": int(sc + 15),
                      "bias10": round(b10, 4), "c_ma20": round(c_ma20, 4), "down_streak": st, "free_mcap": round(fmcap, 2),
                      "dyn_tp_pct": round(float(np.clip(0.45 * abs(ret10), 0.06, 0.16)) * 100, 2)})
    prev_n_dt = int(df[(df["dt_str"] == sig_date) & (~df["c6"].isin(st_set))]["is_dt"].sum())
    built_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    cache = {"built_at": built_at, "sig_date": sig_date, "buy_date": nxt_buy_date, "prev_n_dt": prev_n_dt,
             "candidates": sorted(cands, key=lambda x: (-x["static_score"], x["bias10"])), "main_codes_sample": all_main_codes}
    json.dump(cache, open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    if verbose: print(f"[+] 超跌撬板盘前缓存已生成 ({sig_date}): 纯超跌翘板候选 {len(cands)} 只 (最高可冲165分候选 {sum(x['max_possible']>=165 for x in cands)} 只)")
    return cache

def _print_pry_v21_rules() -> None:
    print("\n【超跌撬板 V2.1 四步动态阶梯卖法】")
    print("  1. 09:25 全场竞价涨停 < 5 家: 无条件开盘市价清仓逃命 (XF13 二次冰点熔断)。")
    print("  2. T+1 分化: 盘前不挂低位止盈单放飞涨停(转连板至断板); 未涨停且未触发D0强真阳豁免时14:55较前收跌超1.5%清(D0跌停则T+1 09:25砍)。")
    print("  3. 双因子加成(+3%/+3%, 封顶18.0%): 买入日收光头强真阳(close>open且CLV>=0.70)免T+1弱斩且止盈+3%; 前日全场跌停<10家止盈+3%。")
    print("  4. 时间阶梯: T+2 挂 clip(0.45*|ret10|, 6%, 16%)+加成 | T+3 基准降至 +5.0%+加成 | T+4 基准降至 +2.0%+加成且收盘必清。")


def _fetch_qfq_kline_pry(symbol: str, datalen: int = 35) -> list[dict]:
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{datalen},qfq"
    try:
        ctx = ssl._create_unverified_context()
        txt = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=3, context=ctx).read().decode("utf-8", "ignore")
        d = json.loads(txt).get("data", {}).get(symbol, {})
        rows = d.get("qfqday") or d.get("day") or []
        return [{"dt_str": str(r[0])[:10], "open": float(r[1]), "close": float(r[2]), "high": float(r[3]), "low": float(r[4]), "adj_close": float(r[2])} for r in rows if len(r) >= 5]
    except Exception:
        return []


def _fetch_sina_kline_pry(symbol: str, datalen: int = 35) -> list[dict]:
    url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
    try:
        ctx = ssl._create_unverified_context()
        txt = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=3, context=ctx).read().decode("utf-8", "ignore")
        i, j = txt.find("["), txt.rfind("]")
        if i >= 0 and j > i:
            return [{"dt_str": str(r["day"])[:10], "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])} for r in json.loads(txt[i : j + 1])]
    except Exception:
        pass
    return []


def run_hold_check_pry(raw_code: str, buy_date_arg: str = "", buy_px_arg: float = 0.0, cache: dict | None = None) -> None:
    c6 = str(raw_code).strip().zfill(6)
    sym = ("sh" if c6.startswith("6") else "sz") + c6
    st_set = _load_st_set()
    all_codes = [str(x).zfill(6) for x in (cache or {}).get("main_codes_sample", []) if str(x).zfill(6) not in st_set]
    cutoff = (pd.Timestamp.now() - pd.Timedelta(days=65)).strftime("%Y-%m-%d")
    df_a = ds.dataset(A_DAILY, format="parquet").scanner(
        columns=["date", "ticker", "open", "high", "low", "close", "adj_close"],
        filter=(ds.field("date") >= pd.Timestamp(cutoff)),
    ).to_table().to_pandas()
    df_a["c6"] = df_a["ticker"].astype(str).str[:6]
    df_a = df_a[df_a["c6"].str.startswith(("00", "60"))].copy()
    df_a["dt_str"] = df_a["date"].dt.strftime("%Y-%m-%d")
    df_a.sort_values(["c6", "dt_str"], inplace=True)
    df_a["adjf"] = np.where((df_a["close"] > 0) & df_a["adj_close"].notna() & (df_a["adj_close"] > 0), df_a["adj_close"] / df_a["close"], 1.0)
    _ga = df_a.groupby("c6")
    df_a["pre_c"] = _ga["close"].shift(1) * _ga["adjf"].shift(1) / df_a["adjf"]
    df_a["dt_px"] = np.floor(df_a["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    df_a["is_dt"] = (df_a["close"] <= df_a["dt_px"] + 0.011) & (df_a["pre_c"] > 0)
    if not all_codes and not df_a.empty:
        max_dt_a = df_a["dt_str"].max()
        all_codes = sorted(df_a[(df_a["dt_str"] == max_dt_a) & (~df_a["c6"].isin(st_set))]["c6"].unique().tolist())

    fetch_list = sorted(set(all_codes + [c6]))
    q_mkt = fetch_tencent_parallel(fetch_list, max_workers=24, batch_size=80)
    q = q_mkt.get(c6, {})
    qfq_kl = _fetch_qfq_kline_pry(sym, datalen=35)
    sina_kl = _fetch_sina_kline_pry(sym, datalen=35)

    now_dt = datetime.datetime.now()
    today_str = now_dt.strftime("%Y-%m-%d")
    q_dt = q.get("q_dt", "")
    # 工作日盘前 (09:15前) q_dt 仍为昨日，禁止误设 target_dt=昨日 导致 T+off 少算1天与 XF16b 退回前前日
    if now_dt.weekday() < 5:
        target_dt = today_str
    else:
        target_dt = q_dt if (q_dt and q.get("close", 0) > 0) else today_str

    # 合并本地日线 + 复权/新浪日线 + 今日实时报价，构建完整日K序列（ret10 使用复权一致序列，买卖价保持原价）
    qfq_map = {b["dt_str"]: float(b["adj_close"]) for b in qfq_kl}
    bars_map = {}
    for r in df_a[df_a["c6"] == c6].itertuples(index=False):
        ac_v = float(r.adj_close) if pd.notna(r.adj_close) and float(r.adj_close) > 0 else float(r.close)
        bars_map[r.dt_str] = {"dt_str": r.dt_str, "open": float(r.open), "high": float(r.high), "low": float(r.low), "close": float(r.close), "adj_close": ac_v}
    for b in sina_kl:
        prev_b = bars_map.get(b["dt_str"], {})
        ac_v = qfq_map.get(b["dt_str"]) or prev_b.get("adj_close") or b["close"]
        bars_map[b["dt_str"]] = {**b, "adj_close": float(ac_v)}
    if q_dt and q.get("close", 0) > 0 and q.get("open", 0) > 0:
        bars_map[q_dt] = {"dt_str": q_dt, "open": float(q["open"]), "high": float(q["high"] or q["close"]), "low": float(q["low"] or q["close"]), "close": float(q["close"]), "adj_close": float(q["close"])}
    bars = [bars_map[k] for k in sorted(bars_map.keys())]
    dts_sorted = [b["dt_str"] for b in bars]

    # 自动识别 buy_date
    buy_date = buy_date_arg.strip()
    if not buy_date and cache:
        if any(x["code"] == c6 for x in cache.get("candidates", [])) and cache.get("buy_date"):
            buy_date = cache["buy_date"]
    if not buy_date:
        buy_date = target_dt

    # 确定 d_prev（核查日的前一已完成交易日）与 sig_date（buy_date 前一交易日）
    past_dts = [d for d in dts_sorted if d < target_dt]
    d_prev = past_dts[-1] if past_dts else (df_a["dt_str"].max() if not df_a.empty else "")
    if buy_date in bars_map:
        b_idx = dts_sorted.index(buy_date)
    else:
        prior = [i for i, d in enumerate(dts_sorted) if d < buy_date]
        b_idx = (prior[-1] + 1) if prior else len(dts_sorted) - 1
    sig_idx = max(0, b_idx - 1)
    sig_date = dts_sorted[sig_idx] if sig_idx < len(dts_sorted) else d_prev
    d10_dt = dts_sorted[sig_idx - 10] if sig_idx >= 10 else ""
    if sig_idx >= 10 and sig_date in qfq_map and d10_dt in qfq_map and qfq_map[d10_dt] > 0:
        ret10 = float(qfq_map[sig_date] / qfq_map[d10_dt] - 1.0)
    elif sig_idx >= 10 and bars[sig_idx - 10].get("adj_close", 0) > 0:
        ret10 = float(bars[sig_idx]["adj_close"] / bars[sig_idx - 10]["adj_close"] - 1.0)
    else:
        ret10 = -0.15
    dyn_tp = float(np.clip(0.45 * abs(ret10), 0.06, 0.16))

    d0_bar = bars_map.get(buy_date) or ({"open": q.get("open", 0), "high": q.get("high", 0), "low": q.get("low", 0), "close": q.get("close", 0)} if buy_date == target_dt else None)
    if not d0_bar:
        print(f"[ERR] 未找到 {c6} 在 {buy_date} 的行情数据", file=sys.stderr)
        return
    d0_o, d0_h, d0_l, d0_c = float(d0_bar["open"]), float(d0_bar["high"]), float(d0_bar["low"]), float(d0_bar["close"])
    buy_px = float(buy_px_arg) if buy_px_arg > 0 else d0_o
    d0_pre = bars[sig_idx]["close"] if sig_idx < len(bars) else float(q.get("pre_c") or buy_px)
    d0_zt = float(np.floor(d0_pre * 1.10 * 100.0 + 0.5) / 100.0)
    d0_dt = float(np.floor(d0_pre * 0.90 * 100.0 + 0.5) / 100.0)
    d0_true_yang = d0_c > d0_o
    d0_clv = (d0_c - d0_l) / (d0_h - d0_l) if d0_h > d0_l else 0.5
    xf21_hit = bool(d0_true_yang and d0_clv >= 0.70)
    req_clv_px = max(round(d0_o + 0.01, 2), math.ceil((d0_l + 0.70 * (d0_h - d0_l)) * 100.0 - 1e-9) / 100.0) if d0_h > d0_l else round(d0_o + 0.01, 2)

    # 今早 09:25 全场竞价涨停家数 (XF13) & 当前实时涨跌停参考（统一剔除 st_set 与 ST/退 名称并强校 q_dt == mkt_qdt）
    zt_open_0925, now_zt_cnt, now_dt_cnt, mkt_qdt = _count_mkt_0925_zt_open(q_mkt, st_set)

    # 前日全场非ST跌停家数 (XF16b)
    prev_n_dt = None
    max_a_dt = df_a["dt_str"].max() if not df_a.empty else ""
    if max_a_dt and d_prev and max_a_dt >= d_prev:
        prev_n_dt = int(df_a[(df_a["dt_str"] == d_prev) & (~df_a["c6"].isin(st_set))]["is_dt"].sum())
    elif cache and cache.get("sig_date") == d_prev and cache.get("prev_n_dt") is not None:
        prev_n_dt = int(cache["prev_n_dt"])
    xf16b_hit = (prev_n_dt is not None) and (prev_n_dt < 10)

    if target_dt in dts_sorted and b_idx < len(dts_sorted):
        off = max(0, dts_sorted.index(target_dt) - b_idx)
    else:
        off = sum(1 for d in dts_sorted if buy_date < d < target_dt) + (1 if target_dt > buy_date else 0)
    ref_prev_c = float(q.get("pre_c") or 0.0) if q_dt == target_dt else (bars_map[d_prev]["close"] if d_prev in bars_map else d0_c)
    cur_px = float(q.get("close") or d0_c)
    now_zt_px = float(np.floor(ref_prev_c * 1.10 * 100.0 + 0.5) / 100.0) if ref_prev_c > 0 else d0_zt

    def _px_pack(base_r: float) -> tuple[float, float, float, float]:
        b0 = round(buy_px * (1.0 + min(0.18, base_r)), 2)
        b3 = round(buy_px * (1.0 + min(0.18, base_r + 0.03)), 2)
        b6 = round(buy_px * (1.0 + min(0.18, base_r + 0.06)), 2)
        cur_b = (0.03 if xf21_hit else 0.0) + (0.03 if xf16b_hit else 0.0)
        b_cur = round(buy_px * (1.0 + min(0.18, base_r + cur_b)), 2)
        return b0, b3, b6, b_cur

    t2_0, t2_3, t2_6, t2_cur = _px_pack(dyn_tp)
    t3_0, t3_3, t3_6, t3_cur = _px_pack(0.05)
    t4_0, t4_3, t4_6, t4_cur = _px_pack(0.02)
    t1_weak_cut = round(d0_c * 0.985, 2)
    today_weak_cut = round(ref_prev_c * 0.985, 2)

    print("=" * 96)
    print(f"【超跌撬板 V2.1 持仓实时核查与 T+0~T+4 挂单表】 {c6} {q.get('name', c6)} | 买日={buy_date} (当前T+{off}) | 买入价={buy_px:.2f}元")
    print(f"信号日={sig_date} | ret10={ret10*100:+.2f}% -> 基准止盈 dyn_tp={dyn_tp*100:.2f}% | 今日({target_dt}) 昨收={ref_prev_c:.2f} 现价={cur_px:.2f} 涨停={now_zt_px:.2f}")
    print("-" * 96)
    print(f"  [XF13 09:25熔断开关] 今早竞价涨停={zt_open_0925}家 ({'🚨<5家触发清仓!' if zt_open_0925 < 5 else '✅>=5家正常'}) | 实时涨停={now_zt_cnt}家 跌停={now_dt_cnt}家")
    print(f"  [XF21 D0强真阳判定] 买日O/H/L/C={d0_o:.2f}/{d0_h:.2f}/{d0_l:.2f}/{d0_c:.2f} | CLV={d0_clv:.3f} 真阳={d0_true_yang} -> "
          f"{'✅已激活(+3%且免T+1弱斩)' if xf21_hit else f'⏳未激活(当前区间收>={req_clv_px:.2f}元即激活)'}")
    ndt_s = f"{prev_n_dt}家" if prev_n_dt is not None else "库未更新"
    print(f"  [XF16b 前日市场止血] 前日({d_prev})主板非ST跌停={ndt_s} -> {'✅<10家激活(+3%)' if xf16b_hit else '未触发(<10家才+3%，今晚盘后再核)'}")
    print("-" * 96)
    print("  [V2.1 分日精确挂单与清仓价格表 (精确到 0.01 元, 总止盈封顶 +18.0%)]")
    print(f"  T+0 ({buy_date}): 买价 {buy_px:.2f}元 | 封涨停 {d0_zt:.2f}元转连板 | 收跌停 {d0_dt:.2f}元则T+1 09:25砍 | 收>={req_clv_px:.2f}元激活XF21")
    print(f"  T+1          : 09:25核对竞价涨停<5家熔断; 盘前不设低位止盈单(放飞涨停); "
          f"{'已获XF21豁免T+1弱斩' if xf21_hit else f'未板时14:55跌破 {t1_weak_cut:.2f}元(-1.5%)清仓'}")
    print(f"  T+2          : 基准+{dyn_tp*100:.2f}%={t2_0:.2f}元 | +3%={t2_3:.2f}元 | +6%(封顶18%)={t2_6:.2f}元 | 当前有效={t2_cur:.2f}元 | 14:55弱斩=昨收*0.985(今日参考{today_weak_cut:.2f})")
    print(f"  T+3          : 基准+5.00%={t3_0:.2f}元 | +3%={t3_3:.2f}元 | +6%={t3_6:.2f}元 | 当前有效={t3_cur:.2f}元 | 14:55弱斩=昨收*0.985")
    print(f"  T+4          : 基准+2.00%={t4_0:.2f}元 | +3%={t4_3:.2f}元 | +6%={t4_6:.2f}元 | 当前有效={t4_cur:.2f}元 | 未成交14:55/15:00无条件清仓!")
    print("=" * 96)


def main():
    ap = argparse.ArgumentParser(description="超跌橡皮筋撬板 V2.1 (XF30_V21) 实盘决策与持仓核查引擎")
    ap.add_argument("--build-cache", action="store_true")
    ap.add_argument("--premarket", action="store_true")
    ap.add_argument("--hold", type=str, default="", help="核查持仓股并打印T+0~T+4精确挂单价与CLV/跌停/竞价涨停")
    ap.add_argument("--buy-date", type=str, default="", help="可选：配合--hold指定买入日期 (YYYY-MM-DD)")
    ap.add_argument("--buy-px", type=float, default=0.0, help="可选：配合--hold指定买入成交价")
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
    if args.hold:
        run_hold_check_pry(args.hold, buy_date_arg=args.buy_date, buy_px_arg=args.buy_px, cache=cache)
        return
    cands = cache.get("candidates", [])
    if args.premarket:
        print(f"=== 超跌橡皮筋撬板 V2.1 (s_pry, 第3顺位, 满165分) 盘前候选 [信号日 {cache.get('sig_date')}] ===")
        print("无符合四道硬门的纯超跌翘板股" if not cands else pd.DataFrame(cands).to_string(index=False))
        _print_pry_v21_rules()
        return
    if not cands:
        print(f"[s_pry V2.1 第3顺位] 信号日 {cache.get('sig_date')} 无纯超跌翘板候选，今日空缺顺延至第4顺位二进三。")
        return
    q_cand = fetch_tencent_parallel([x["code"] for x in cands])
    st_set = _load_st_set()
    all_codes = [str(x).zfill(6) for x in cache.get("main_codes_sample", []) if str(x).zfill(6) not in st_set]
    q_mkt = fetch_tencent_parallel(all_codes, max_workers=24, batch_size=80)
    print(f"[*] 全市场竞价行情获取成功: {len(q_mkt)} / {len(all_codes)} 只 (已剔除ST)")
    if len(q_mkt) < min(len(all_codes) * 0.9, 4500):
        print(f"[WARN] 全市场竞价行情返回股票数偏低 ({len(q_mkt)} < 4500)，请排查网络！", file=sys.stderr)
    zt_open_cnt, _, _, mkt_qdt = _count_mkt_0925_zt_open(q_mkt, st_set)
    sig_dt_cache = cache.get("sig_date", "")
    if sig_dt_cache and mkt_qdt and mkt_qdt <= sig_dt_cache:
        print(f"[s_pry V2.1 第3顺位] ⏳ 盘前/非当日竞价 (mkt_qdt={mkt_qdt} <= sig_date={sig_dt_cache})，待09:25实时竞价再裁决。")
        return
    passed = []
    for c in cands:
        q = q_cand.get(c["code"])
        if not q or "ST" in str(q.get("name", "")).upper() or q["is_yizi"] or not (0.0 <= q["open_pct"] <= 0.05): continue
        tot = c["static_score"] + (15 if zt_open_cnt >= 12 else 0)
        if tot >= 165:
            bp = q["open"]
            t2_base = round(bp * (1.0 + c["dyn_tp_pct"] / 100.0), 2)
            t2_plus3 = round(bp * (1.0 + min(18.0, c["dyn_tp_pct"] + 3.0) / 100.0), 2)
            t2_plus6 = round(bp * (1.0 + min(18.0, c["dyn_tp_pct"] + 6.0) / 100.0), 2)
            passed.append({
                **c, "name": q["name"], "open": bp, "open_pct": round(q["open_pct"]*100, 2), "score": tot,
                "t2_base_px": t2_base, "t2_plus3_px": t2_plus3, "t2_plus6_px": t2_plus6,
                "t3_base_px": round(bp * 1.05, 2), "t4_base_px": round(bp * 1.02, 2),
            })
    passed.sort(key=lambda x: (-x["score"], x["bias10"]))
    print(f"[s_pry V2.1 第3顺位] 09:25全市场竞价涨停={zt_open_cnt}家 | 满165分过线={len(passed)}只")
    if passed:
        print("唯一头名指令:", passed[0])
        _print_pry_v21_rules()

if __name__ == "__main__":
    main()
