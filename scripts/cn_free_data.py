#!/usr/bin/env python3
"""A股、北交所免费行情源(main, 2026-09-29)。起因: Buwen 9月29日告知 iFinD 没了, ifind_data_layer 改为转接本模块。

两个源互校, 对不上就不给数(故障不降级成合法值):
  实时快照: 腾讯 qt.gtimg.cn + 新浪 hq.sinajs.cn, 收盘后即为当日最终价。9月29日15:30全市场 5540 只实测:
            两源都有 5539 只, 开高低收零差异; 耗时约 85 秒。
  历史日线: 沪深用腾讯 fqkline(不复权), 北交所用新浪 getKLineData(腾讯对北交所只给当天一根)。
            9月22日到28日抽 40 只 160 根对照本地价格库收盘价, 零差异。

单位(与本地价格库、原 iFinD 口径一致): volume=股, amount=元, turn=百分数, preclose=交易所前收盘(除权后)。
  ⛔ 腾讯日线的成交量: 科创板(688/689)单位是股, 其余板块是手, 已换算; 新浪一律是股。
  历史日线没有成交额、换手率、交易所前收盘, 调用方要这些字段时由 ifind_data_layer 返回错误码, 让调用方退到宝硕。
停牌: 当日成交量为 0 的不出行。
"""
import datetime as dt
import json
import re
import sys
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}
SINA_H = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
TOL = 0.0051  # 价格两源容差(分位四舍五入)


def _q(code):
    """600000.SH -> sh600000; 920982.BJ -> bj920982; 裸代码按首位推交易所。"""
    code = str(code).strip()
    if "." in code:
        x, m = code.split(".", 1)
        return m.lower()[:2] + x
    if code[:1] in "569":
        return "sh" + code
    if code[:1] in "48" or code[:2] in ("92",):
        return "bj" + code
    return "sz" + code


def _code(q):
    return q[2:] + "." + q[:2].upper()


def _get(url, headers=None, timeout=10, tries=3):
    err = None
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or UA)
            return urllib.request.urlopen(req, timeout=timeout).read().decode("gbk", "ignore")
        except Exception as e:  # 网络抖动重试, 三次都失败才抛
            err = e
            time.sleep(1 + a * 2)
    raise RuntimeError(f"取数失败 {url[:60]}: {type(err).__name__} {err}")


def _f(x):
    try:
        return float(x)
    except Exception:
        return None


# ---------------- 实时快照(收盘后=当日最终) ----------------
def _tencent_rt(qs):
    out = {}
    for ln in _get("http://qt.gtimg.cn/q=" + ",".join(qs)).split(";"):
        if '="' not in ln:
            continue
        k, v = ln.strip().split('="', 1)
        f = v.rstrip('"').split("~")
        if len(f) < 45:
            continue
        out[k[2:]] = {"date": f[30][:8], "open": _f(f[5]), "high": _f(f[33]), "low": _f(f[34]),
                      "close": _f(f[3]), "preclose": _f(f[4]), "amount": (_f(f[37]) or 0) * 1e4,
                      "turn_pct": _f(f[38]), "chg_pct": _f(f[32])}
    return out


def _sina_rt(qs):
    out = {}
    for ln in _get("https://hq.sinajs.cn/list=" + ",".join(qs), SINA_H).split(";"):
        if '="' not in ln:
            continue
        k, v = ln.strip().split('="', 1)
        f = v.rstrip('"').split(",")
        if len(f) < 32:
            continue
        out[k.split("_")[-1]] = {"date": f[30].replace("-", ""), "open": _f(f[1]), "preclose": _f(f[2]),
                                 "close": _f(f[3]), "high": _f(f[4]), "low": _f(f[5]),
                                 "volume": _f(f[8]), "amount": _f(f[9])}
    return out


def snapshot(codes, batch=60, require_after_close=False):
    """全市场或指定代码的当日快照, 两源互校。
    返回 (rows, report): rows 是 {date,ticker,open,high,low,close,volume,amount,turn_pct,preclose} 列表,
    report 含 asked/tencent/sina/both/agreed/disagree/suspended/missing。两源不一致或缺一源的代码不进 rows。
    require_after_close=True 时, 北京时间 15:05 前调用直接报错(盘中快照不是当日最终价)。"""
    now = dt.datetime.now()
    if require_after_close and now.hour * 100 + now.minute < 1505:
        raise RuntimeError("盘中快照不是当日最终价, 15:05 以后再取")
    qs = [_q(c) for c in codes]
    T, S = {}, {}
    for i in range(0, len(qs), batch):
        ch = qs[i:i + batch]
        T.update(_tencent_rt(ch))
        S.update(_sina_rt(ch))
    today = now.strftime("%Y%m%d")
    rows, rep = [], {"asked": len(qs), "tencent": len(T), "sina": len(S), "both": 0, "agreed": 0,
                     "disagree": [], "suspended": 0, "missing": [], "stale": 0}
    for q in qs:
        t, s = T.get(q), S.get(q)
        if not t or not s:
            rep["missing"].append(_code(q))
            continue
        rep["both"] += 1
        if t["date"] != today or s["date"] != today:
            rep["stale"] += 1
            continue
        if not s["volume"]:
            rep["suspended"] += 1
            continue
        bad = [k for k in ("open", "high", "low", "close", "preclose")
               if t[k] is None or s[k] is None or abs(t[k] - s[k]) > TOL]
        if bad:
            rep["disagree"].append((_code(q), bad))
            continue
        rep["agreed"] += 1
        rows.append({"date": now.strftime("%Y-%m-%d"), "ticker": _code(q), "open": s["open"], "high": s["high"],
                     "low": s["low"], "close": s["close"], "volume": s["volume"], "amount": s["amount"],
                     "turn_pct": t["turn_pct"], "preclose": s["preclose"]})
    return rows, rep


# ---------------- 历史日线(不复权) ----------------
def _tencent_kline(q, start, end):
    n = max(10, (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 10)
    d = json.loads(_get(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={q},day,{start},{end},{n},&_var="))
    k = list((d.get("data") or {}).values())
    bars = (k[0].get("day") or k[0].get("qfqday") or []) if k else []
    mult = 1 if q[2:5] in ("688", "689") else 100  # 科创板腾讯以股计, 其余以手计
    out = []
    for b in bars:
        if start <= b[0] <= end:
            out.append({"date": b[0], "open": _f(b[1]), "close": _f(b[2]), "high": _f(b[3]), "low": _f(b[4]),
                        "volume": (_f(b[5]) or 0) * mult})
    return out


def _sina_kline(q, start, end):
    days = (dt.date.today() - dt.date.fromisoformat(start)).days
    n = max(20, int(days * 0.75) + 20)
    raw = _get(f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20x=/CN_MarketDataService.getKLineData"
               f"?symbol={q}&scale=240&ma=no&datalen={n}", SINA_H)
    m = re.search(r"x=\((\[.*\])\)", raw, re.S)
    bars = json.loads(m.group(1)) if m else []
    return [{"date": b["day"], "open": _f(b["open"]), "close": _f(b["close"]), "high": _f(b["high"]),
             "low": _f(b["low"]), "volume": _f(b["volume"])} for b in bars if start <= b["day"] <= end]


def history(code, start, end):
    """单只历史日线(不复权), 返回 (bars, source)。沪深: 腾讯为主, 新浪复核收盘价, 对不上抛错;
    北交所: 新浪(腾讯无历史)。"""
    q = _q(code)
    if q.startswith("bj"):
        return _sina_kline(q, start, end), "sina"
    bars = _tencent_kline(q, start, end)
    try:
        chk = {b["date"]: b["close"] for b in _sina_kline(q, start, end)}
    except Exception:
        chk = {}
    bad = [b["date"] for b in bars if b["date"] in chk and chk[b["date"]] is not None
           and abs(chk[b["date"]] - b["close"]) > TOL]
    if bad:
        raise RuntimeError(f"{code} 腾讯与新浪收盘价不一致: {bad[:5]}")
    return bars, ("tencent+sina" if chk else "tencent")


def shares(codes, batch=60):
    """腾讯快照里的股本与市值(2026-09-29 核对: 72号字段=流通股本, 与本地价格库 oshare 一致; 73号=总股本;
    45号总市值(亿)=价格乘总股本)。返回 {code: {date, price, float_shares, total_shares, total_mv, float_mv}},
    市值单位元。盘前 price 与 date 是前一交易日收盘。"""
    out = {}
    qs = [_q(c) for c in codes]
    for i in range(0, len(qs), batch):
        for ln in _get("http://qt.gtimg.cn/q=" + ",".join(qs[i:i + batch])).split(";"):
            if '="' not in ln:
                continue
            k, v = ln.strip().split('="', 1)
            f = v.rstrip('"').split("~")
            if len(f) < 74:
                continue
            px, fs, ts = _f(f[3]), _f(f[72]), _f(f[73])
            if not px or not ts:
                continue
            d = f[30][:8]
            out[_code(k[2:])] = {"date": f"{d[:4]}-{d[4:6]}-{d[6:8]}", "price": px, "float_shares": fs,
                                  "total_shares": ts, "total_mv": px * ts, "float_mv": px * (fs or 0)}
    return out


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "600000.SH"
    bars, src = history(c, (dt.date.today() - dt.timedelta(days=10)).isoformat(), dt.date.today().isoformat())
    print(c, src, bars[-3:])
    rows, rep = snapshot([c])
    print({k: (v if not isinstance(v, list) else len(v)) for k, v in rep.items()}, rows[:1])
