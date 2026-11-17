#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_4to5_today.py — 四进五接力策略 V2.0 (满120分高严档, 纯单仓研发版)
------------------------------------------------------------------------------------------------
注意：四进五策略（s_4to5）已下放 astock2 研发观察，不上实盘！
本文件维护仅供研发端对照与基准历史检验，实盘严格执行三大主战策略与超跌撬板/五板辅助策略。
------------------------------------------------------------------------------------------------
模式：
  1. --build-cache：盘后读取只读库构建下一交易日盘前特征缓存 (4to5_premarket_cache.json)；
  2. --premarket：早盘 09:15 前秒级读取盘前缓存，输出环境面板、静态预评分与异动安全垫；
  3. 无参数默认盘中秒跑模式：09:25:03 秒读缓存并抓腾讯实时竞价行情，秒级输出一步到位整数总分与 09:25 竞价直买指令；
  4. --date YYYY-MM-DD / --recent N：查询五年严校台账 w2_4to5_v20_ledger.csv。
"""
import os, sys, json, time, re, sqlite3, glob, argparse, urllib.request
import pandas as pd, numpy as np, pyarrow.dataset as ds

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
DATA_DIR = f"{ROOT}/sim-portfolio/data"
CACHE_FILE = f"{DATA_DIR}/4to5_premarket_cache.json"
CACHE_3TO4 = f"{DATA_DIR}/3to4_premarket_cache.json"
A_DAILY = f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet"
HOLDERS_PATH = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"
IDX_PATH = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
DB_NOTICES = f"{ROOT}/sim-portfolio/backtest/2026-08-24-daban/notices.db"
DB_PIT_NOTICES = f"{DATA_DIR}/cninfo_notices_5y_pit.db"
LHB_PATH = f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet"
LHB_SELL_PATH = f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_sell.parquet"
LEDGER_CSV = f"{ROOT}/sim-portfolio/backtests_astock2/p3_deep_100/w2_4to5_v20_ledger.csv"

def _query_em_lhb_online(c6: str, sig_date: str) -> tuple[list[str], list[str]]:
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
                        out_list.append(str(r.get("OPERATEDEPT_NAME", "")).strip())
        except Exception as e:
            print(f"[WARN] fast_4to5 online LHB {side} fallback failed for {c6}: {e}", file=sys.stderr)
    return buys, sells

TOX_RE = re.compile(r"(?:减持计划|股东减持|立案调查|收到立案|退市风险|违法违规)")
REG_INC = ["监管工作函", "监管函", "关注函", "重点监控", "停牌核查"]
REG_EXC = ["ST", "回复", "回函", "延期", "核查意见", "复牌", "募集资金", "监事", "独立董事", "保荐"]
TECH_RE = re.compile(r"(?:算力|芯片|半导体|机器人|人工智能|AI|华为|低空|固态电池)")

def fetch_tencent_batch(codes: list[str]) -> dict[str, dict]:
    if not codes: return {}
    res = {}
    chunks = [codes[i:i+60] for i in range(0, len(codes), 60)]
    for ch in chunks:
        q_list = [f"{'sh' if c.startswith('60') else 'sz'}{c}" for c in ch]
        req = urllib.request.Request(f"http://qt.gtimg.cn/q={','.join(q_list)}", headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                for line in resp.read().decode("gbk", errors="ignore").strip().split(";"):
                    if "~" not in line: continue
                    p = line.split("~")
                    if len(p) > 30:
                        c6, px, pc, op = p[2].strip(), float(p[3] or 0), float(p[4] or 0), float(p[5] or 0)
                        b1, s1 = float(p[10] or 0), float(p[20] or 0)
                        op_px = op if op > 0 else px
                        op_pct = (op_px / pc - 1.0) if pc > 0 else -1.0
                        zt_px = np.floor(pc * 1.10 * 100.0 + 0.5) / 100.0 if pc > 0 else 999.0
                        is_yz = bool(op_px >= zt_px - 0.011 or (b1 > 0 and s1 == 0 and op_pct >= 0.090))
                        res[c6] = {"name": p[1], "open": op_px, "pre_c": pc, "open_pct": op_pct, "is_zt_open": op_px >= zt_px - 0.011, "is_yizi": is_yz}
        except Exception:
            pass
    return res

def _is_clean_reg(title: str) -> bool:
    ti = str(title)
    if any(k in ti for k in REG_INC) and not any(k in ti for k in REG_EXC):
        return True
    return False

def build_premarket_cache(verbose: bool = True) -> dict:
    t0 = time.time()
    cols = ["date", "ticker", "open", "high", "low", "close", "turn", "oshare", "amount"]
    df_act = ds.dataset(A_DAILY, format="parquet").scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2026-09-01"))).to_table().to_pandas()
    df_act["c6"] = df_act["ticker"].astype(str).str[:6]
    df_act = df_act[df_act["c6"].str.startswith(("00", "60"))].copy()
    df_act["dt_str"] = df_act["date"].dt.strftime("%Y-%m-%d")
    df_act.sort_values(["c6", "dt_str"], inplace=True)
    g = df_act.groupby("c6")
    df_act["pre_c"] = g["close"].shift(1)
    df_act["pct"] = df_act["close"] / df_act["pre_c"] - 1.0
    df_act["zt_px"] = np.floor(df_act["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df_act["is_zt"] = (df_act["close"] >= df_act["zt_px"] - 0.011) & (df_act["pct"] >= 0.095) & (df_act["pre_c"] > 0)
    df_act["is_yizi"] = df_act["is_zt"] & (df_act["low"] >= df_act["zt_px"] - 0.011)

    s_zt = df_act["is_zt"].astype(int)
    s_shift = g["is_zt"].shift().fillna(False).infer_objects(copy=False).astype(bool)
    df_act["streak"] = s_zt.groupby([df_act["c6"], (s_zt != s_shift).cumsum()]).cumsum() * s_zt

    d_list = sorted(df_act["dt_str"].unique())
    sig_date = d_list[-1]
    sig_df = df_act[df_act["dt_str"] == sig_date]
    mkt_max_b = int(sig_df["streak"].max()) if not sig_df.empty else 4

    # 1. 查找近90日毒丸公告与近10日重点监控（含周末/晚间最新公告，双库交叉校验）
    sig_ts = pd.Timestamp(sig_date)
    nxt_buy_date = (sig_ts + pd.Timedelta(days=(3 if sig_ts.weekday() == 4 else 1))).strftime("%Y-%m-%d")
    d90 = (sig_ts - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    d10 = (sig_ts - pd.Timedelta(days=15)).strftime("%Y-%m-%d")
    tox_codes = set()
    stock_reg_codes = set()
    for db_p in (DB_NOTICES, DB_PIT_NOTICES):
        if not os.path.exists(db_p):
            continue
        con = sqlite3.connect(f"file:{db_p}?mode=ro", uri=True)
        try:
            col_c = "sec_code" if "cninfo" in db_p else "code"
            col_d = "pub_datetime_cst" if "cninfo" in db_p else "ndate"
            tbl = "notices" if "cninfo" in db_p else "notice"
            for c_raw, pdt, title in con.execute(f"SELECT {col_c}, {col_d}, title FROM {tbl} WHERE {col_d} >= ?", (d90,)):
                c6 = str(c_raw).strip()[:6].zfill(6)
                dt = str(pdt)[:10]
                if TOX_RE.search(str(title)):
                    tox_codes.add(c6)
                if dt >= d10 and _is_clean_reg(title):
                    stock_reg_codes.add(c6)
        except Exception as e:
            print(f"[WARN] fast_4to5 notice DB error ({db_p}): {e}", file=sys.stderr)
        finally:
            con.close()

    # 合并 kpl/zdjk 重点监控
    for zf in glob.glob(f"{ROOT}/sim-portfolio/data/kpl/zdjk/*.json"):
        try:
            zd_data = json.load(open(zf, "r", encoding="utf-8"))
            for it in zd_data.get("List", []):
                stock_reg_codes.add(str(it[0]).zfill(6))
        except Exception:
            pass

    # 2. 股东持股与真实自由流通市值
    holders = json.load(open(HOLDERS_PATH)) if os.path.exists(HOLDERS_PATH) else {}

    # 3. 龙虎榜席位（买入榜看游资与拉萨，卖出榜看量化出逃与机构砸盘）
    lhb_quant_sell, lhb_inst_sell, lhb_top_yz_buy, lhb_lhasa_cnt = set(), set(), set(), {}
    lhb_has_sig_date = False
    if os.path.exists(LHB_SELL_PATH):
        try:
            ldf_s = pd.read_parquet(LHB_SELL_PATH, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "SELL"])
            ldf_s = ldf_s[ldf_s["TRADE_DATE"].astype(str).str[:10] == sig_date]
            if not ldf_s.empty:
                for c6, sub in ldf_s.groupby(ldf_s["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)):
                    seat_list = sub["OPERATEDEPT_NAME"].astype(str).tolist()
                    seats = " ".join(seat_list)
                    if re.search(r"(?:量化|华鑫.*上海分|中信.*上海分|高盛|瑞银)", seats): lhb_quant_sell.add(c6)
                    if "机构专用" in seats: lhb_inst_sell.add(c6)
        except Exception as e:
            print(f"[WARN] fast_4to5 LHB sell parquet error: {e}", file=sys.stderr)

    if os.path.exists(LHB_PATH):
        try:
            ldf = pd.read_parquet(LHB_PATH, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"])
            ldf = ldf[ldf["TRADE_DATE"].astype(str).str[:10] == sig_date]
            if not ldf.empty:
                lhb_has_sig_date = True
                for c6, sub in ldf.groupby(ldf["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)):
                    seat_list = sub["OPERATEDEPT_NAME"].astype(str).tolist()
                    seats = " ".join(seat_list)
                    if re.search(r"(?:六一中路|金马路|江苏路|朱雀大街)", seats): lhb_top_yz_buy.add(c6)
                    lhb_lhasa_cnt[c6] = sum(1 for s in seat_list if "拉萨" in s)
        except Exception as e:
            print(f"[WARN] fast_4to5 LHB buy parquet error: {e}", file=sys.stderr)

    # 4. 指数数据用于双严重异动预算
    idx_data = json.load(open(IDX_PATH)) if os.path.exists(IDX_PATH) else {}
    sh_map = idx_data.get("sh000001", idx_data.get("sh000002", {}))
    sz_map = idx_data.get("sz399001", idx_data.get("sz399107", {}))

    # 同花顺当日题材与三板跟风统计
    ths_p = f"{DATA_DIR}/ths_limit_up_daily/{sig_date}.json"
    ths_stocks_map = {}
    if os.path.exists(ths_p):
        try:
            for s in json.load(open(ths_p)).get("stocks", []):
                ths_stocks_map[str(s.get("code"))[:6]] = s
        except Exception: pass

    # 5. 筛选四连板候选
    b4_df = sig_df[sig_df["streak"] == 4].copy()
    b4_codes = b4_df["c6"].tolist()
    is_sole_4b = (len(b4_codes) == 1)
    if not lhb_has_sig_date and b4_codes:
        for c6_u in b4_codes:
            b_seats, s_seats = _query_em_lhb_online(c6_u, sig_date)
            if s_seats:
                s_txt = " ".join(s_seats)
                if re.search(r"(?:量化|华鑫.*上海分|中信.*上海分|高盛|瑞银)", s_txt): lhb_quant_sell.add(c6_u)
                if "机构专用" in s_txt: lhb_inst_sell.add(c6_u)
            if b_seats:
                b_txt = " ".join(b_seats)
                if re.search(r"(?:六一中路|金马路|江苏路|朱雀大街)", b_txt): lhb_top_yz_buy.add(c6_u)
                lhb_lhasa_cnt[c6_u] = sum(1 for s in b_seats if "拉萨" in s)

    cands = []
    for c6 in b4_codes:
        sub = df_act[df_act["c6"] == c6].sort_values("dt_str")
        if len(sub) < 5: continue
        r = sub.iloc[-1]
        px_d4 = float(r["close"])
        pre_c_d4 = float(r["pre_c"])
        oshare = float(r["oshare"]) if "oshare" in r and r["oshare"] > 0 else 0.0

        h_recs = [x for x in holders.get(c6, []) if isinstance(x, (list, tuple)) and len(x) > 2 and str(x[0]) <= sig_date]
        lock = float(max(h_recs, key=lambda x: str(x[1]))[2]) if h_recs else 38.0
        fmcap = float(px_d4 * oshare * (1.0 - lock / 100.0) / 1e8) if oshare > 0 else 25.0

        # 双严重异动门槛预算 (PIT)
        imap = sh_map if c6.startswith("60") else sz_map
        ir = imap.get(sig_date, 1.0)
        p100, p200 = 99999.0, 99999.0
        dts = sub["dt_str"].tolist()
        cls = sub["close"].tolist()
        pos = len(sub) - 1
        for k in range(1, min(10, pos) + 1):
            bi = imap.get(dts[pos - k])
            bc = cls[pos - k]
            if bi and bc > 0:
                p100 = min(p100, bc * (2.0 + (ir / bi - 1.0)))
        for k in range(1, min(30, pos) + 1):
            bi = imap.get(dts[pos - k])
            bc = cls[pos - k]
            if bi and bc > 0:
                p200 = min(p200, bc * (3.0 + (ir / bi - 1.0)))
        tight_px = min(p100, p200)

        # 预估 09:25 开盘价 (按涨幅4.5%估算)
        est_open = px_d4 * 1.045
        hr_est = (tight_px / est_open - 1.0) if est_open > 0 else 0.0

        # 静态因子打分 (100分底分)
        sc = 100
        bd = {}

        # 1. 筹码轻盈锁仓 F49
        f49 = 0
        if (lock >= 50.0) and (12.0 <= fmcap <= 35.0): f49 = 8
        elif (lock >= 45.0) or (fmcap >= 45.0): f49 = 3
        elif (lock < 45.0) and (fmcap < 45.0): f49 = -8
        sc += f49
        bd["f49_chip"] = f49

        # 2. 双严重异动 F58
        f58 = 0
        if hr_est >= 0.25: f58 = 6
        elif hr_est >= 0.22: f58 = 4
        sc += f58
        bd["f58_headroom"] = f58

        # 3. 身位周期
        status_sc = 0
        if mkt_max_b == 4: status_sc = 5
        elif mkt_max_b == 5: status_sc = 2
        elif mkt_max_b >= 6: status_sc = -5
        sc += status_sc
        bd["status_lead"] = status_sc

        # 4. 同身位竞争
        rival_sc = 0
        if is_sole_4b: rival_sc += 6
        sc += rival_sc
        bd["rival_open"] = rival_sc

        # 5. 左端晋级基因 (单项累加，最高加15分)
        left_sc = 0
        d4_s34 = -999.0
        if os.path.exists(CACHE_3TO4):
            try:
                c3_obj = json.load(open(CACHE_3TO4))
                for c3_cand in c3_obj.get("candidates", []):
                    if c3_cand.get("code") == c6:
                        d4_s34 = float(c3_cand.get("score", c3_cand.get("static_score", 85.0)))
            except Exception: pass
        if (82.0 <= d4_s34 <= 89.0) and is_sole_4b:
            left_sc += 5
        d3_row = sub.iloc[-2] if len(sub) >= 2 else None
        d3_is_yz = bool(d3_row["is_yizi"]) if d3_row is not None else False
        d4_is_yz = bool(r["is_yizi"])
        if d3_is_yz and not d4_is_yz:
            left_sc += 4
        to_d4 = float(r["turn"] * 100.0 if r["turn"] < 1.0 else r["turn"])
        if to_d4 >= 10.0 and not d4_is_yz:
            left_sc += 3
        left_sc = min(15, left_sc)
        sc += left_sc
        bd["left_gene"] = left_sc

        # 6. 席位博弈 (卖出榜看量化出逃与机构砸盘)
        lhb_sc = 0
        if c6 in lhb_quant_sell: lhb_sc -= 5
        if c6 in lhb_inst_sell: lhb_sc -= 3
        if c6 in lhb_top_yz_buy: lhb_sc -= 3
        if lhb_lhasa_cnt.get(c6, 0) >= 3: lhb_sc -= 6
        sc += lhb_sc
        bd["lhb_seat"] = lhb_sc

        # 7. 题材与日历节律 (加12至扣24)
        cal_sc = 0
        if px_d4 > 20.0: cal_sc -= 6
        dow = pd.Timestamp(sig_date).weekday() + 1
        nxt_dow = 1 if dow == 5 else (dow + 1)
        if nxt_dow == 1: cal_sc += 6
        if nxt_dow in (4, 5): cal_sc -= 3
        buy_month = pd.Timestamp(nxt_buy_date).month
        if buy_month in (1, 5): cal_sc -= 4
        ths_item = ths_stocks_map.get(c6, {})
        my_reason = ths_item.get("reason_type", "")
        plate_3b_cnt = sum(1 for sc_code, s in ths_stocks_map.items() if sc_code != c6 and "3板" in s.get("high_days", "") and any(w in s.get("reason_type", "") for w in my_reason.split("+") if len(w) >= 2))
        if plate_3b_cnt >= 1: cal_sc -= 4
        sc += cal_sc
        bd["theme_calendar"] = cal_sc

        has_tox = (c6 in tox_codes)
        has_reg = (c6 in stock_reg_codes)

        cands.append({
            "code": c6,
            "close": round(px_d4, 2),
            "tight_px": round(tight_px, 2),
            "lock_top10": round(lock, 2),
            "real_free_mcap": round(fmcap, 2),
            "hr_est": round(hr_est, 4),
            "static_score": int(sc),
            "breakdown": bd,
            "has_tox_notice": has_tox,
            "has_stock_reg": has_reg,
            "is_sole_4b": is_sole_4b,
            "mkt_max_board_prev": mkt_max_b,
        })

    cache = {
        "built_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sig_date": sig_date,
        "buy_date": nxt_buy_date,
        "mkt_max_board": mkt_max_b,
        "candidates": cands,
        "build_time_sec": round(time.time() - t0, 3)
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    if verbose:
        print(f"[+] 四进五盘前缓存已生成 ({sig_date}): 4连板候选 {len(cands)} 只 (全场最高连板={mkt_max_b}板, 耗时 {cache['build_time_sec']}s)")
    return cache

def main():
    ap = argparse.ArgumentParser(description="四进五接力策略 V2.0 实盘极速决策引擎")
    ap.add_argument("--build-cache", action="store_true", help="构建盘前特征缓存")
    ap.add_argument("--premarket", action="store_true", help="输出早盘盘前推演面板")
    ap.add_argument("--date", type=str, default="", help="查询历史台账指定日期")
    ap.add_argument("--recent", type=int, default=0, help="查询历史台账最近 N 笔")
    args = ap.parse_args()

    if args.date or args.recent > 0:
        if not os.path.exists(LEDGER_CSV):
            print(f"[-] 历史台账不存在: {LEDGER_CSV}")
            return
        df = pd.read_csv(LEDGER_CSV)
        sub = df[df["buy_date"] == args.date] if args.date else df.sort_values("buy_date").tail(args.recent)
        cols_show = ["buy_date", "code", "name", "buy_px", "exit_date", "net_ret", "v20_score", "is_held_3to4"]
        print(sub[[c for c in cols_show if c in sub.columns]].to_string(index=False))
        return

    if args.build_cache or not os.path.exists(CACHE_FILE):
        cache = build_premarket_cache(verbose=True)
        if args.build_cache: return
    else:
        cache = json.load(open(CACHE_FILE, "r", encoding="utf-8"))

    cands = cache.get("candidates", [])
    if args.premarket:
        print(f"=== 四进五 V2.0 (纯单仓第3顺位, 满120分高严档) 盘前推演 [信号日 {cache.get('sig_date')}] ===")
        if not cands:
            print("今日无沪深主板非ST四连板候选标的，开盘顺延至第4顺位超跌撬板或第5顺位一进二。")
        else:
            for c in cands:
                print(f"标的代码: {c['code']} | 昨收: {c['close']}元 | 静态预评: {c['static_score']}分 | 锁仓: {c['lock_top10']}% | 自由流通值: {c['real_free_mcap']}亿 | 毒丸: {c['has_tox_notice']} | 监管: {c['has_stock_reg']}")
        return

    if not cands:
        print(f"[4to5 第3顺位] 信号日 {cache.get('sig_date')} 无四连板候选，今日空缺顺延至第4顺位超跌撬板。")
        return

    # 实时盘中竞价
    q_map = fetch_tencent_batch([c["code"] for c in cands])
    passed = []
    for c in cands:
        q = q_map.get(c["code"])
        if not q: continue
        op_pct = q["open_pct"]
        op_px = q["open"]
        # 六道前置门核验
        if c.get("has_tox_notice") or c.get("has_stock_reg"): continue
        if q.get("is_yizi"): continue
        if not (0.020 <= op_pct <= 0.075): continue
        tight_px = c["tight_px"]
        hr_pit = (tight_px / op_px - 1.0) if op_px > 0 else 0.0
        if hr_pit < 0.12: continue

        # 动态打分修正
        sc = c["static_score"]
        # 异动修正
        f58_diff = 0
        if hr_pit >= 0.25 and c["breakdown"].get("f58_headroom", 0) < 6: f58_diff = 6 - c["breakdown"].get("f58_headroom", 0)
        elif hr_pit >= 0.22 and c["breakdown"].get("f58_headroom", 0) < 4: f58_diff = 4 - c["breakdown"].get("f58_headroom", 0)
        sc += f58_diff

        # 仅同身位竞价涨幅真正排第1名才加3分，非第一或对手>=2只扣5分
        valid_cands_for_rank = [cand for cand in cands if cand["code"] in q_map and not q_map[cand["code"]].get("is_yizi", False)]
        max_op_same_streak = max((q_map[cand["code"]]["open_pct"] for cand in valid_cands_for_rank), default=-999.0)
        is_top1 = bool(abs(op_pct - max_op_same_streak) < 1e-5 and op_pct > -0.10)
        if is_top1:
            sc += 3
        elif len(cands) >= 2:
            sc -= 5
        if sc >= 120:
            passed.append({
                "code": c["code"],
                "name": q["name"],
                "open": op_px,
                "open_pct": round(op_pct * 100, 2),
                "score": sc,
                "hr_pit": round(hr_pit * 100, 2),
                "is_sole": c["is_sole_4b"],
            })

    passed.sort(key=lambda x: -x["score"])
    print(f"[4to5 第3顺位] 竞价可买候选={len(cands)}只 | 满120分过线={len(passed)}只")
    if passed:
        p0 = passed[0]
        print(f"唯一头名指令: 买入 {p0['code']} {p0['name']} (开盘涨幅: +{p0['open_pct']}%, 总分: {p0['score']}分, 异动空间: {p0['hr_pit']}%)")
    else:
        print("[4to5 第3顺位] 今日无标的满足满120分且竞价开在2.0%至7.5%甜区，不扣扳机，顺延至第4顺位。")

if __name__ == "__main__":
    main()
