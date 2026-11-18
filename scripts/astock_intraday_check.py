#!/opt/homebrew/bin/python3.13
"""A股盘中1秒异动与竞价核查只读工具 (astock_intraday_check.py)

功能（纯标准库，零第三方依赖，纯只读不写盘，耗时约 0.4~0.9 秒）：
  1. 实时拉取腾讯行情（现价、今开涨幅、现涨幅、最高最低、买一卖一封单量、涨跌停硬字段 f[47]/f[48]、换手率、流通市值）
  2. 按沪深交易所精确对标指数硬算「今日」与「明日预演」的 10日100% / 30日200% 严重异动红线、98%线、93%异动提前线：
       - 沪市主板 (60xxxx)   -> 上证A股指数 (sh000002)
       - 科创板   (688/689)  -> 科创50指数   (sh000688)
       - 深市主板 (00xxxx)   -> 深证A股指数 (sz399107)
       - 创业板   (300/301)  -> 创业板综指   (sz399102)
  3. 拉取东财公告接口核查近 10 个交易日内已披露的「股票交易异常波动公告」次数，预警「10日4次同向严重异动」风险
  4. 可选 --strategy 参数输出对应现役策略的盘中买点撤单窗与出场盯盘铁律：
       - s_3to4 (三进四 V4.1): 09:30至10:30 突破条件单有效窗口；连板期7因子风险开关命中>=1收紧13:45护利至+7.0%(0命中+5.0%)
       - s_1to2 (一进二 V19): 封二板次日暗牌区 ([-6.5%, +2.5%] 且 雪球<4帖 且 封成比<25%或缺失) 豁免 10:30 破分时均价线弱斩
       - s_2to3 (二进三 V2.1): 未封三板次日不割 09:25 地板，14:55 清仓；封三板极高开 >+9.2% 非一字 09:25 止盈，否则 13:45 摸+8.5%破+6.5%护利
       - s_pry  (超跌撬板 V2.1): 09:25<5家熔断 + T+1放飞兼14:55跌1.5%清 + 强阳/止血+3% + T+2~T+4阶梯

用法：
  /opt/homebrew/bin/python3.13 sim-portfolio/scripts/astock_intraday_check.py 600838 000678
  /opt/homebrew/bin/python3.13 sim-portfolio/scripts/astock_intraday_check.py 002205 --strategy s_3to4
  /opt/homebrew/bin/python3.13 sim-portfolio/scripts/astock_intraday_check.py 002748 --strategy s_2to3 --json
"""
import argparse
import concurrent.futures
import json
import ssl
import sys
import time
import urllib.request

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance imported!"

SSL_CTX = ssl._create_unverified_context()
HEADERS = {"User-Agent": "Mozilla/5.0"}

STRATEGY_INTRADAY_RULES = {
    "s_high": {
        "name": "高标首阴 V5.1",
        "buy_window": "09:26 绿开条件单(今开*1.015)至 11:30 撤单；红开<=+4.5% 直接买",
        "exit_rule": "买日封板次日起预埋93%双异动止盈单，连板首次真阳断板免死1天；买日未封板不挂93%单，次日不板 14:55 清仓",
    },
    "s_3to4": {
        "name": "三进四 V4.1",
        "buy_window": "09:26 突破条件单(max(昨收*1.065, 今开)) 有效窗口收紧为 09:30至10:30，10:30 未触发立即撤单（拦截诱多反抽单）",
        "exit_rule": "买日封板次日起连板期走 13:45 摸+8.5%回落护利（7项风险因子命中>=1收紧至+7.0%，0命中保持+5.0%）+ 首次真阳断板免死1次；买日未封板仅当收阳不跌且次日高开>=+0.5%留至收盘，否则 09:25 斩",
    },
    "s_1to2": {
        "name": "一进二 V19",
        "buy_window": "周一断层强开 09:25 直买；其余 11:30 前触及点火价买入，11:30 未点火下午撤单",
        "exit_rule": "买日未封板次日<+0.5%于09:25全清；封二板次日(D3)若开盘[-6.5%,+2.5%]且雪球<4帖且D2封成比<25%(或缺失)豁免10:30破均线弱斩，否则10:30未封破均线10:35全卖、14:30后炸板抢跑",
    },
    "s_2to3": {
        "name": "二进三 V2.1",
        "buy_window": "09:25 集合竞价窗口 [-6.5%, +2.5%] 非一字直买",
        "exit_rule": "未封三板次日不割 09:25 地板，持仓过早盘抛压至 14:55/15:00 清仓（若反包涨停切入连板骑乘）；封三板/连板期次日极高开 >+9.2% 非一字 09:25 止盈兑现，否则 13:45 摸+8.5%破+6.5%护利 + 首次真阳免死1次",
    },
    "s_pry": {
        "name": "超跌撬板 V2.1",
        "buy_window": "09:25 集合竞价直买（0.0%~+5.0%）",
        "exit_rule": "每日09:25全场竞价涨停<5家熔断清仓；T+1放飞涨停(未板且非D0强真阳CLV>=0.70豁免则14:55跌>1.5%清，D0跌停T+1 09:25止损)；强真阳/昨跌停<10家各+3%(封顶18%)；T+2挂dyn_tp+加成，T+3降+5%+加成，T+4降+2%+加成收盘必清",
    },
}


def build_strategy_intraday_hint(
    strategy_id: str,
    quote: dict,
    xq_cnt: int | None = None,
    d2_seal_ratio: float | None = None,
    sealed_board: bool | None = None,
) -> list[str]:
    """根据策略ID与实时报价生成盘中盯盘与撤单提醒。"""
    sid = strategy_id.strip().lower()
    targets = list(STRATEGY_INTRADAY_RULES.keys()) if sid == "all" else ([sid] if sid in STRATEGY_INTRADAY_RULES else [])
    if not targets:
        return []

    op_pct = float(quote.get("open_pct", 0.0)) / 100.0
    prev_c = float(quote.get("prev_close", 0.0))
    now_p = float(quote.get("now", 0.0))
    open_p = float(quote.get("open", 0.0)) or now_p
    zt_p = float(quote.get("zt_price", 0.0)) or (round(prev_c * 1.10, 2) if prev_c > 0 else 999.0)
    is_yz = bool(open_p >= zt_p - 0.005 and quote.get("bid1_vol", 0) > 0 and quote.get("ask1_vol", 0) == 0)

    hints: list[str] = []
    high_p = float(quote.get("high", 0.0)) or now_p
    low_p = float(quote.get("low", 0.0)) or now_p

    for k in targets:
        rule = STRATEGY_INTRADAY_RULES[k]
        if k == "s_3to4":
            trig_px = max(round(prev_c * 1.065, 2), round(open_p, 2)) if prev_c > 0 else 0.0
            p85 = round(prev_c * 1.085, 2) if prev_c > 0 else 0.0
            p70 = round(prev_c * 1.070, 2) if prev_c > 0 else 0.0
            p50 = round(prev_c * 1.050, 2) if prev_c > 0 else 0.0
            hints.append(
                f"[s_3to4 三进四 V4.1] 触发价 {trig_px:.2f}元 | 撤单窗 09:30至10:30 | "
                f"连板13:45护利线: 摸+8.5%({p85:.2f})破+7.0%({p70:.2f},7因子风险>=1)或+5.0%({p50:.2f},0风险)；{rule['exit_rule']}"
            )
        elif k == "s_1to2":
            in_dark_op = (-0.065 <= op_pct <= 0.025)
            xq_ok = (xq_cnt is not None and xq_cnt < 4)
            sr_ok = (d2_seal_ratio is None or d2_seal_ratio < 0.25)
            if in_dark_op and xq_ok and sr_ok:
                m1_msg = f"触发 M1 暗牌区豁免（今开{op_pct*100:+.2f}%在[-6.5%,+2.5%] & 雪球{xq_cnt}帖<4 & 封成比达标）-> 今日 10:30 破分时均线免弱斩，拿至收盘/连板"
            elif in_dark_op:
                m1_msg = f"今开{op_pct*100:+.2f}%落入[-6.5%,+2.5%]，若确认D1~D3雪球<4帖且D2封成比<25%(或缺失)，则豁免 10:30 破均线弱斩"
            else:
                m1_msg = "若为封二板次日且不在暗牌豁免区，10:30 未封且破分时均价线则 10:35 全卖，14:30 后炸板抢跑"
            hints.append(f"[s_1to2 一进二 V19] {m1_msg}")
        elif k == "s_2to3":
            p92 = round(prev_c * 1.092, 2) if prev_c > 0 else 0.0
            p85 = round(prev_c * 1.085, 2) if prev_c > 0 else 0.0
            p65 = round(prev_c * 1.065, 2) if prev_c > 0 else 0.0
            guard_alert = (prev_c > 0) and (high_p >= p85) and (now_p <= p65) and (now_p < zt_p - 0.005)
            if sealed_board is True:
                if op_pct > 0.092 and not is_yz:
                    s23_msg = f"⚠️触发 V2.1 极高开止盈（今开{op_pct*100:+.2f}% > +9.2% 且非一字）-> 09:25 止盈兑现！"
                elif guard_alert:
                    s23_msg = f"🚨已触及 V2.1 13:45 +6.5%护利线（最高{high_p:.2f}>=+8.5%且现价{now_p:.2f}<=+6.5% {p65:.2f}元未封板）-> 午后立即锁利！"
                else:
                    s23_msg = f"封三板次日未触>+9.2%非一字止盈 -> 走 13:45 摸+8.5%({p85:.2f})破+6.5%({p65:.2f})护利 + 真阳免死1次"
            elif sealed_board is False:
                s23_msg = "未封三板次日 -> V2.1 不割 09:25 地板，持仓过早盘抛压至 14:55/15:00 清仓（若反包涨停切连板骑乘）"
            else:
                if guard_alert:
                    s23_msg = f"🚨盘中已摸+8.5%({p85:.2f})回落破+6.5%({p65:.2f})报警线(13:45后连板期触发锁利) | {rule['exit_rule']}"
                else:
                    s23_msg = f"{rule['exit_rule']} | 精准线: +9.2%({p92:.2f}) / +8.5%({p85:.2f}) / +6.5%护利({p65:.2f})"
            hints.append(f"[s_2to3 二进三 V2.1] {s23_msg}")
        elif k == "s_pry":
            clv = (now_p - low_p) / (high_p - low_p) if (high_p > low_p > 0) else 0.5
            weak_cut_px = round(prev_c * 0.985, 2) if prev_c > 0 else 0.0
            hints.append(
                f"[s_pry 超跌撬板 V2.1] 实时CLV={clv:.3f}(收阳且>=0.70激活+3%兼免T+1弱斩) | "
                f"14:55跌1.5%弱斩线={weak_cut_px:.2f}元 | 离场: {rule['exit_rule']}"
            )
        else:
            hints.append(f"[{k} {rule['name']}] 买窗: {rule['buy_window']} | 离场: {rule['exit_rule']}")
    return hints


def bare_code(raw: str) -> str:
    s = raw.strip().upper()
    for p in ("SH", "SZ", "BJ", ".SS", ".SZ", ".SH", ".BJ"):
        if s.startswith(p) and len(s) > len(p):
            s = s[len(p):]
        if s.endswith(p):
            s = s[:-len(p)]
    return s.zfill(6)


def market_prefix(code: str) -> str:
    if code.startswith(("6", "5")):
        return "sh"
    if code.startswith(("0", "3", "1")):
        return "sz"
    return "bj"


def benchmark_index(code: str) -> tuple[str, str]:
    if code.startswith(("688", "689")):
        return "sh000688", "科创50(000688)"
    if code.startswith("6"):
        return "sh000002", "上证A指(000002)"
    if code.startswith(("300", "301")):
        return "sz399102", "创业板综(399102)"
    return "sz399107", "深证A指(399107)"


def fetch_tencent_quotes(symbols: list[str]) -> dict[str, dict]:
    url = "http://qt.gtimg.cn/q=" + ",".join(symbols)
    req = urllib.request.Request(url, headers=HEADERS)
    raw = urllib.request.urlopen(req, timeout=2.5).read().decode("gbk", "ignore")
    out = {}
    for ln in raw.strip().splitlines():
        if "=" not in ln or "~" not in ln:
            continue
        lhs, rhs = ln.split("=", 1)
        sym = lhs.split("_")[-1].strip()
        f = rhs.strip('";').split("~")
        if len(f) < 49:
            continue
        prev_c = float(f[4] or 0)
        now_p = float(f[3] or 0) or prev_c
        open_p = float(f[5] or 0)
        open_pct = ((open_p / prev_c - 1.0) * 100.0) if (open_p > 0 and prev_c > 0) else 0.0
        out[sym] = {
            "symbol": sym,
            "code": f[2],
            "name": f[1],
            "now": now_p,
            "prev_close": prev_c,
            "open": open_p,
            "open_pct": round(open_pct, 2),
            "pct": float(f[32] or 0),
            "high": float(f[33] or 0),
            "low": float(f[34] or 0),
            "bid1": float(f[9] or 0),
            "bid1_vol": int(float(f[10] or 0)),
            "ask1": float(f[19] or 0),
            "ask1_vol": int(float(f[20] or 0)),
            "turn_pct": float(f[38] or 0),
            "float_mcap_yi": float(f[44] or 0),
            "total_mcap_yi": float(f[45] or 0),
            "zt_price": float(f[47] or 0),
            "dt_price": float(f[48] or 0),
            "raw_time": f[30],
        }
    return out


def fetch_sina_kline(symbol: str, datalen: int = 36) -> list[dict]:
    url = (
        f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/"
        f"CN_MarketDataService.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    txt = urllib.request.urlopen(req, timeout=2.5, context=SSL_CTX).read().decode("utf-8", "ignore")
    i, j = txt.find("["), txt.rfind("]")
    if i < 0 or j <= i:
        return []
    rows = json.loads(txt[i : j + 1])
    return [
        {
            "day": r["day"],
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        }
        for r in rows
    ]


def fetch_abnormal_notices(code: str) -> list[dict]:
    url = (
        f"https://np-anotice-stock.eastmoney.com/api/security/ann?"
        f"sr=-1&page_size=20&page_index=1&ann_type=A&stock_list={code}"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    data = json.loads(urllib.request.urlopen(req, timeout=2.5, context=SSL_CTX).read().decode("utf-8", "ignore"))
    items = data.get("data", {}).get("list", []) or []
    hits = []
    for it in items:
        title = it.get("title", "")
        ndate = (it.get("notice_date") or "")[:10]
        if "股票交易异常波动公告" in title or ("异常波动公告" in title and "严重" not in title):
            hits.append({"notice_date": ndate, "title": title})
    return hits


def calc_window_threshold(
    past_closes: list[tuple[str, float]],
    idx_map: dict[str, float],
    idx_ref: float,
    max_days: int,
    target_dev: float,
    ref_prev_close: float,
) -> dict:
    """计算连续 1..max_days 个交易日内（含目标日当天）触发 target_dev (1.00 或 2.00) 的最紧价格。
    past_closes 为目标日之前的历史收盘序列（按日期升序，past_closes[-1] 为目标日前一交易日收盘）。
    若窗口长度 k 天（含目标日），则基准日为 past_closes[-k]！
    """
    best = None
    limit_k = min(max_days, len(past_closes))
    for k in range(1, limit_k + 1):
        b_day, b_close = past_closes[-k]
        b_idx = idx_map.get(b_day)
        if not b_idx or b_close <= 0:
            continue
        idx_chg = idx_ref / b_idx - 1.0
        p_hard = b_close * (1.0 + target_dev + idx_chg)
        if best is None or p_hard < best["p_hard"]:
            p_98 = b_close * (1.0 + (target_dev - 0.02) + idx_chg)
            p_93 = b_close * (1.0 + (target_dev - 0.07) + idx_chg)
            best = {
                "window_days": k,
                "base_day": b_day,
                "base_close": round(b_close, 2),
                "idx_chg_pct": round(idx_chg * 100.0, 2),
                "p_93": round(p_93, 2),
                "p_98": round(p_98, 2),
                "p_hard": round(p_hard, 2),
                "hard_vs_prev_pct": round((p_hard / ref_prev_close - 1.0) * 100.0, 2) if ref_prev_close > 0 else 0.0,
            }
    return best or {}


def analyze_one(
    code: str,
    quotes: dict,
    klines: dict,
    notices: list[dict],
    notice_err: str | None,
    strategy: str = "",
    xq_cnt: int | None = None,
    d2_seal_ratio: float | None = None,
    sealed_board: bool | None = None,
) -> dict:
    sym = market_prefix(code) + code
    idx_sym, idx_label = benchmark_index(code)
    q = quotes.get(sym, {})
    k_stk = klines.get(sym, [])
    k_idx = klines.get(idx_sym, [])
    q_idx = quotes.get(idx_sym, {})

    if not q or not k_stk or not k_idx:
        return {"code": code, "error": "行情或日线数据缺失"}

    live_day = q["raw_time"][:8]
    live_day_fmt = f"{live_day[:4]}-{live_day[4:6]}-{live_day[6:8]}" if len(live_day) >= 8 else ""

    if k_stk and k_stk[-1]["day"] == live_day_fmt:
        past_stk = [(r["day"], r["close"]) for r in k_stk[:-1]]
    else:
        past_stk = [(r["day"], r["close"]) for r in k_stk]

    idx_map = {r["day"]: r["close"] for r in k_idx}
    idx_now = q_idx.get("now") or (k_idx[-1]["close"] if k_idx else 1.0)

    prev_c = q["prev_close"]
    now_p = q["now"]

    today_10d = calc_window_threshold(past_stk, idx_map, idx_now, 10, 1.00, prev_c)
    today_30d = calc_window_threshold(past_stk, idx_map, idx_now, 30, 2.00, prev_c)

    past_for_tmr = past_stk + [(live_day_fmt or "TODAY", now_p)]
    idx_map_tmr = dict(idx_map)
    idx_map_tmr[live_day_fmt or "TODAY"] = idx_now
    tmr_10d = calc_window_threshold(past_for_tmr, idx_map_tmr, idx_now, 10, 1.00, now_p)

    is_20cm = code.startswith(("300", "301", "688", "689"))
    lim_mult = 1.20 if is_20cm else 1.10
    safe_close_today = round(tmr_10d["p_hard"] / lim_mult - 0.01, 2) if tmr_10d else None

    recent_10_days_cutoff = past_stk[-10][0] if len(past_stk) >= 10 else (past_stk[0][0] if past_stk else "")
    recent_notices = [n for n in notices if n["notice_date"] >= recent_10_days_cutoff]

    res = {
        "code": code,
        "name": q["name"],
        "benchmark": idx_label,
        "quote": q,
        "today_10d_100": today_10d,
        "today_30d_200": today_30d,
        "tomorrow_10d_100_if_close_now": tmr_10d,
        "today_close_below_for_tmr_zt_safe": safe_close_today,
        "recent_10d_abnormal_notices": recent_notices,
        "recent_10d_notice_count": len(recent_notices),
        "notice_error": notice_err,
    }
    if strategy:
        res["strategy_advice"] = build_strategy_intraday_hint(
            strategy, q, xq_cnt=xq_cnt, d2_seal_ratio=d2_seal_ratio, sealed_board=sealed_board
        )
    return res


def fmt_pct(val: float) -> str:
    if val > 0:
        return f"正{val:.2f}%"
    if val < 0:
        return f"负{abs(val):.2f}%"
    return "0.00%"


def main():
    t0 = time.perf_counter()
    ap = argparse.ArgumentParser(description="A股盘中1秒异动与竞价只读核查")
    ap.add_argument("tickers", nargs="+", help="股票代码，如 600838 000678")
    ap.add_argument("--json", action="store_true", help="输出JSON")
    ap.add_argument("--strategy", type=str, default="", help="附加策略盘中盯盘与撤单提醒: s_high/s_3to4/s_1to2/s_2to3/s_pry/all")
    ap.add_argument("--xq-cnt", type=int, default=None, help="可选：s_1to2 D1~D3 09:25前雪球帖数，用于判定暗牌豁免")
    ap.add_argument("--d2-seal-ratio", type=float, default=None, help="可选：s_1to2 D2封成比 (如0.18)，用于判定暗牌豁免")
    ap.add_argument("--sealed-board", type=str, default="", choices=["", "yes", "no"], help="可选：s_2to3 前日是否封死三板 (yes/no)")
    args = ap.parse_args()

    sealed_flag = True if args.sealed_board == "yes" else (False if args.sealed_board == "no" else None)

    codes = [bare_code(t) for t in args.tickers]
    stk_syms = [market_prefix(c) + c for c in codes]
    idx_syms = sorted({benchmark_index(c)[0] for c in codes})
    all_syms = stk_syms + idx_syms

    klines = {}
    notices = {}
    notice_errs = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(12, len(all_syms) + len(codes) + 2)) as ex:
        fut_quotes = ex.submit(fetch_tencent_quotes, all_syms)
        fut_klines = {sym: ex.submit(fetch_sina_kline, sym, 36) for sym in all_syms}
        fut_notices = {c: ex.submit(fetch_abnormal_notices, c) for c in codes}

        quotes = fut_quotes.result()
        for sym, fut in fut_klines.items():
            try:
                klines[sym] = fut.result()
            except Exception:
                klines[sym] = []
        for c, fut in fut_notices.items():
            try:
                notices[c] = fut.result()
                notice_errs[c] = None
            except Exception as e:
                notices[c] = []
                notice_errs[c] = str(e)

    results = [
        analyze_one(
            c, quotes, klines, notices[c], notice_errs[c],
            strategy=args.strategy, xq_cnt=args.xq_cnt,
            d2_seal_ratio=args.d2_seal_ratio, sealed_board=sealed_flag,
        )
        for c in codes
    ]
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    if args.json:
        print(json.dumps({"elapsed_ms": round(elapsed_ms, 1), "results": results}, ensure_ascii=False, indent=2))
        return

    for r in results:
        if "error" in r:
            print(f"[{r['code']}] 错误：{r['error']}")
            continue
        q = r["quote"]
        t10 = r["today_10d_100"]
        t30 = r["today_30d_200"]
        tm10 = r["tomorrow_10d_100_if_close_now"]
        print(
            f"【{r['code']} {r['name']}】现价 {q['now']:.2f}元（{fmt_pct(q['pct'])}）| "
            f"今开 {q['open']:.2f}元（{fmt_pct(q['open_pct'])}）| 昨收 {q['prev_close']:.2f}元 | "
            f"涨停 {q['zt_price']:.2f}元 跌停 {q['dt_price']:.2f}元 | "
            f"买一 {q['bid1']:.2f}({q['bid1_vol']}手) 卖一 {q['ask1']:.2f}({q['ask1_vol']}手) | "
            f"换手 {q['turn_pct']:.2f}% 流值 {q['float_mcap_yi']:.1f}亿"
        )
        if t10:
            today_hit = "【今日涨停即触线】" if q["zt_price"] >= t10["p_hard"] else "【今日涨停安全】"
            print(
                f"  · 今日10日100%异动（对标{r['benchmark']}，基准 {t10['base_day']} 收 {t10['base_close']:.2f}元）："
                f"93%提前线 {t10['p_93']:.2f}元 | 98%线 {t10['p_98']:.2f}元 | "
                f"100%硬线 {t10['p_hard']:.2f}元（较昨收{fmt_pct(t10['hard_vs_prev_pct'])}）{today_hit}"
            )
        if t30:
            t30_hit = "【今日涨停触30日线】" if q["zt_price"] >= t30["p_hard"] else "【今日涨停未触30日线】"
            print(
                f"  · 今日30日200%异动（基准 {t30['base_day']} 收 {t30['base_close']:.2f}元）："
                f"200%硬线 {t30['p_hard']:.2f}元（较昨收{fmt_pct(t30['hard_vs_prev_pct'])}）{t30_hit}"
            )
        if tm10:
            print(
                f"  · 明日10日100%预演（基准 {tm10['base_day']} 收 {tm10['base_close']:.2f}元）："
                f"93%提前线 {tm10['p_93']:.2f}元 | 98%线 {tm10['p_98']:.2f}元 | "
                f"100%硬线 {tm10['p_hard']:.2f}元（今日收盘不超 {r['today_close_below_for_tmr_zt_safe']:.2f}元 则明日涨停也不触100%硬线）"
            )
        if r["notice_error"]:
            print(f"  · 近10日同向普通异动公告：公告接口超时（{r['notice_error']}）")
        else:
            titles = "；".join(f"{n['notice_date']}" for n in r["recent_10d_abnormal_notices"]) or "无"
            print(
                f"  · 近10日普通异动公告次数：{r['recent_10d_notice_count']}次（日期：{titles}；满4次触发同向严重异动）"
            )
        for adv in r.get("strategy_advice", []):
            print(f"  · 策略盯盘提醒：{adv}")
    print(f"[耗时 {elapsed_ms:.0f} 毫秒 · 纯只读]")


if __name__ == "__main__":
    main()
