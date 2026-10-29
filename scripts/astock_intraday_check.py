#!/usr/bin/env python3
"""A股盘中1秒异动与竞价核查只读工具 (astock_intraday_check.py)

功能（纯标准库，零第三方依赖，纯只读不写盘，耗时约 0.4~0.9 秒）：
  1. 实时拉取腾讯行情（现价、今开涨幅、现涨幅、最高最低、买一卖一封单量、涨跌停硬字段 f[47]/f[48]、换手率、流通市值）
  2. 按沪深交易所精确对标指数硬算「今日」与「明日预演」的 10日100% / 30日200% 严重异动红线、98%线、93%异动提前线：
       - 沪市主板 (60xxxx)   -> 上证A股指数 (sh000002)
       - 科创板   (688/689)  -> 科创50指数   (sh000688)
       - 深市主板 (00xxxx)   -> 深证A股指数 (sz399107)
       - 创业板   (300/301)  -> 创业板综指   (sz399102)
  3. 拉取东财公告接口核查近 10 个交易日内已披露的「股票交易异常波动公告」次数，预警「10日4次同向严重异动」风险

用法：
  python3 sim-portfolio/scripts/astock_intraday_check.py 600838 000678
  python3 sim-portfolio/scripts/astock_intraday_check.py 600838 --json
"""
import argparse
import concurrent.futures
import json
import ssl
import sys
import time
import urllib.request

SSL_CTX = ssl._create_unverified_context()
HEADERS = {"User-Agent": "Mozilla/5.0"}


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


def analyze_one(code: str, quotes: dict, klines: dict, notices: list[dict], notice_err: str | None) -> dict:
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

    # 剥离可能已写入日线末尾的当日K线，确保 past_before_today 严格为「今日之前已收盘交易日」
    if k_stk and k_stk[-1]["day"] == live_day_fmt:
        past_stk = [(r["day"], r["close"]) for r in k_stk[:-1]]
    else:
        past_stk = [(r["day"], r["close"]) for r in k_stk]

    idx_map = {r["day"]: r["close"] for r in k_idx}
    idx_now = q_idx.get("now") or (k_idx[-1]["close"] if k_idx else 1.0)

    prev_c = q["prev_close"]
    now_p = q["now"]
    zt_p = q["zt_price"] or round(prev_c * (1.20 if code.startswith(("30", "68")) else 1.10), 2)

    today_10d = calc_window_threshold(past_stk, idx_map, idx_now, 10, 1.00, prev_c)
    today_30d = calc_window_threshold(past_stk, idx_map, idx_now, 30, 2.00, prev_c)

    # 明日预演：将今日收盘（按现价收盘）追加进历史序列，计算下一交易日的最紧10日100%异动线
    past_for_tmr = past_stk + [(live_day_fmt or "TODAY", now_p)]
    idx_map_tmr = dict(idx_map)
    idx_map_tmr[live_day_fmt or "TODAY"] = idx_now
    tmr_10d = calc_window_threshold(past_for_tmr, idx_map_tmr, idx_now, 10, 1.00, now_p)

    is_20cm = code.startswith(("300", "301", "688", "689"))
    lim_mult = 1.20 if is_20cm else 1.10
    safe_close_today = round(tmr_10d["p_hard"] / lim_mult - 0.01, 2) if tmr_10d else None

    recent_10_days_cutoff = past_stk[-10][0] if len(past_stk) >= 10 else (past_stk[0][0] if past_stk else "")
    recent_notices = [n for n in notices if n["notice_date"] >= recent_10_days_cutoff]

    return {
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
    args = ap.parse_args()

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

    results = [analyze_one(c, quotes, klines, notices[c], notice_errs[c]) for c in codes]
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
    print(f"[耗时 {elapsed_ms:.0f} 毫秒 · 纯只读]")


if __name__ == "__main__":
    main()
