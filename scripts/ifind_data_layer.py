#!/usr/bin/env python3
"""
ifind_data_layer.py — 同花顺 iFinD HTTP 数据接口封装 (机构级A股/港股/美股)
==================================================================
2026-07-24 接入。相比 akshare/东财: 机构级数据、无代理DNS劫持问题、覆盖全。
token 存钥匙串(不留明文): refresh_token(service=ifind-refresh-token) → 自动换 access_token。
access_token 会过期, 本模块遇鉴权错自动用 refresh_token 重新换。
⚠️ refresh_token 本身 2026-07-26 过期 — 到期需在 quantapi.10jqka.com.cn 重新生成并更新钥匙串。

⛔⛔ 2026-09-29 Buwen: "ifind没了"。默认不再请求 iFinD, 改由 cn_free_data(腾讯加新浪双源互校)转接, 返回格式不变:
  history: 只要开高低收与成交量 → 免费日线(沪深腾讯主新浪复核, 北交所新浪);
           起止都是今天且已过 15:05 → 双源快照, 另可给 amount/turnoverRatio/preClose;
           历史区间还要其他字段 → errorcode=-9001, 调用方按原设计退到宝硕。两源对不上的代码不出表(当作没取到)。
  realtime: 双源快照。basic: errorcode=-9002(免费源没有财务数据)。直接调 _post(如 snap_shot 竞价补采): errorcode=-9000。
  返回的 dict 带 "source" 字段标明真实来源。若日后恢复 iFinD, 设环境变量 IFIND_ENABLED=1 即走原接口。

用法:
    from ifind_data_layer import realtime, history, basic
    realtime(["600519.SH"], "latest,changeRatio,pe_ttm")
    history("600519.SH", "2026-01-01", "2026-07-24", "close")
"""
import json
import os
import sys
import time
import datetime as _dtm
import subprocess
import urllib.request
import urllib.error

BASE = "https://quantapi.10jqka.com.cn/api/v1"
_UID = "728027802"
_at_cache = {"token": "", "ts": 0}
IFIND_ENABLED = os.environ.get("IFIND_ENABLED") == "1"
_FREE_OK = {"open", "high", "low", "close", "volume"}
_SNAP_OK = _FREE_OK | {"amount", "turnoverRatio", "preClose", "latest", "changeRatio"}
_warned = []


def _note(msg):
    if msg not in _warned:
        _warned.append(msg)
        print(f"[ifind_data_layer] {msg}", file=sys.stderr, flush=True)


def _free():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import cn_free_data
    return cn_free_data


def _off(ec, what):
    return {"errorcode": ec, "errmsg": f"iFinD 已停用(2026-09-29), 免费源不提供{what}", "tables": [], "source": "none"}


def _kc(service):
    r = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                       capture_output=True, text=True)
    return r.stdout.strip()


def _refresh_access_token():
    rt = _kc("ifind-refresh-token")
    if not rt:
        raise RuntimeError("钥匙串无 refresh_token (service=ifind-refresh-token)")
    req = urllib.request.Request(f"{BASE}/get_access_token",
                                 headers={"Content-Type": "application/json", "refresh_token": rt},
                                 method="POST")
    r = json.loads(urllib.request.urlopen(req, timeout=20).read())
    if r.get("errorcode") not in (0, "0"):
        raise RuntimeError(f"换access_token失败 errorcode={r.get('errorcode')} "
                           f"msg={r.get('errmsg', '')} — refresh_token可能已过期(07-26到期), "
                           f"去 quantapi.10jqka.com.cn 重新生成后更新钥匙串")
    at = r["data"]["access_token"]
    _at_cache.update(token=at, ts=time.time())
    subprocess.run(["security", "add-generic-password", "-U", "-s", "ifind-access-token",
                    "-a", _UID, "-w", at], capture_output=True)
    return at


def _access_token():
    # 缓存内存中的; 首次从钥匙串取; 都没有再换
    if _at_cache["token"]:
        return _at_cache["token"]
    at = _kc("ifind-access-token")
    if at:
        _at_cache["token"] = at
        return at
    return _refresh_access_token()


def _post(endpoint, payload, _retry=True):
    if not IFIND_ENABLED:
        _note(f"iFinD 已停用, {endpoint} 无免费替代, 返回 errorcode=-9000")
        return _off(-9000, f" {endpoint} 接口")
    at = _access_token()
    req = urllib.request.Request(f"{BASE}/{endpoint}", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "access_token": at},
                                 method="POST")
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=25).read())
    except urllib.error.HTTPError as e:
        r = {"errorcode": e.code, "errmsg": e.read().decode()[:120]}
    # 鉴权类错误(access_token过期) → 刷新一次重试
    ec = r.get("errorcode")
    if ec not in (0, "0") and _retry and ec in (-1010, -1011, 401, "-1010", "-1011"):
        _refresh_access_token()
        return _post(endpoint, payload, _retry=False)
    return r


def realtime(codes, indicators="latest,changeRatio,open,high,low,volume,amount"):
    """实时行情。codes: list或逗号串, 如 ['600519.SH']。返回 {code: {ind: val}}。"""
    if not IFIND_ENABLED:
        cl = codes if isinstance(codes, (list, tuple)) else [c for c in str(codes).split(",") if c]
        inds = [x.strip() for x in indicators.split(",") if x.strip()]
        bad = [x for x in inds if x not in _SNAP_OK]
        if bad:
            return {"_error": -9001, "_msg": f"免费源不提供 {bad}"}
        rows, rep = _free().snapshot(cl)
        _note("iFinD 已停用, 实时行情改由腾讯加新浪双源提供")
        m = {"latest": "close", "turnoverRatio": "turn_pct", "preClose": "preclose"}
        out = {}
        for r0 in rows:
            v = {k: r0.get(m.get(k, k)) for k in inds}
            if "changeRatio" in inds and r0.get("preclose"):
                v["changeRatio"] = round((r0["close"] / r0["preclose"] - 1) * 100, 4)
            out[r0["ticker"]] = v
        return out
    if isinstance(codes, (list, tuple)):
        codes = ",".join(codes)
    r = _post("real_time_quotation", {"codes": codes, "indicators": indicators})
    if r.get("errorcode") not in (0, "0"):
        return {"_error": r.get("errorcode"), "_msg": r.get("errmsg", "")}
    out = {}
    for t in r.get("tables", []):
        code = t.get("thscode", "")
        tab = t.get("table", {})
        out[code] = {k: (v[0] if isinstance(v, list) and v else v) for k, v in tab.items()}
    return out


def history(code, start, end, indicators="close", period="D"):
    """历史行情。period: D/W/M。返回原始tables。iFinD 停用后见文件头说明。"""
    if not IFIND_ENABLED:
        return _free_history(code, start, end, indicators, period)
    return _post("cmd_history_quotation", {"codes": code, "indicators": indicators,
                                           "startdate": start, "enddate": end,
                                           "functionpara": {"period": period}})


def _free_history(code, start, end, indicators, period):
    inds = [x.strip() for x in indicators.split(",") if x.strip()]
    codes = [c for c in str(code).split(",") if c]
    if period != "D":
        return _off(-9001, f" {period} 周期")
    today = _dtm.date.today().isoformat()
    now = _dtm.datetime.now()
    F = _free()
    tables, srcs = [], set()
    if start == end == today and now.hour * 100 + now.minute >= 1505 and set(inds) <= _SNAP_OK:
        rows, rep = F.snapshot(codes)
        srcs.add("tencent+sina 快照")
        m = {"turnoverRatio": "turn_pct", "preClose": "preclose", "latest": "close"}
        for r0 in rows:
            tables.append({"thscode": r0["ticker"], "time": [today],
                           "table": {k: [r0.get(m.get(k, k))] for k in inds}})
        if rep["disagree"]:
            _note(f"两源不一致已剔除 {len(rep['disagree'])} 只: {rep['disagree'][:5]}")
    elif set(inds) <= _FREE_OK:
        for c in codes:
            try:
                bars, src = F.history(c, start, end)
            except Exception as e:
                _note(f"{c} 免费日线失败: {e}")
                continue
            srcs.add(src)
            if bars:
                tables.append({"thscode": c, "time": [b["date"] for b in bars],
                               "table": {k: [b.get(k) for b in bars] for k in inds}})
    else:
        return _off(-9001, f"历史区间的 {sorted(set(inds) - _FREE_OK)}")
    _note(f"iFinD 已停用, history 改由 {'/'.join(sorted(srcs)) or '免费源'} 提供")
    return {"errorcode": 0 if tables or not codes else -9003, "errmsg": "" if tables else "免费源未取到",
            "tables": tables, "source": "/".join(sorted(srcs))}


def basic(codes, indicators, date=None):
    """基础/财务数据。

    ⛔ 2026-09-07 修: 原实现传 indicators 字符串, 而 basic_data_service 要的是 **indipara 结构**,
    且**必须带日期**——不带日期时接口**不报错、返回 [None]**(假空, 最容易被误读成"没数据")。
    根因由 interview 实测发现(它按 main 广播的错用法调用, 一律 -4210 或静默 None)。

    indicators: 'ths_pe_ttm_stock,ths_pb_latest_stock' 或 ['ths_pe_ttm_stock', ...]
                ⛔ 指标名要带 ths_ 前缀与 _stock 后缀; A股与美股同名可用(HSAI.O/ADBE.O/CEG.O 实测通)。
                **已验证可用**: ths_pe_ttm_stock(茅台20.42/禾赛40.43/ADBE 14.65) /
                ths_pb_latest_stock(茅台6.617) / ths_market_value_stock(茅台1.6626万亿)
                **⛔ 错的**: ths_pb_stock 返回[None]不报错 / ths_mv_stock 与 ths_pbr_stock 返回-4210
    date: 'YYYY-MM-DD', 默认取今天。财务类指标必须给交易日, 给非交易日会返回空。
    """
    if not IFIND_ENABLED:
        # 只接总市值: 腾讯快照的价格乘总股本, 且仅当请求日期等于行情日期(盘前即前一交易日收盘)。
        # 其余指标(PE/PB 等)口径未核, 不冒充 iFinD; 需要 PE/PB 用 astock_data_layer.get_batch_prices。
        cl = codes if isinstance(codes, (list, tuple)) else [c for c in str(codes).split(",") if c]
        il = [x.strip() for x in (indicators.split(",") if isinstance(indicators, str) else indicators) if x.strip()]
        if il != ["ths_market_value_stock"]:
            _note("iFinD 已停用, basic 只支持 ths_market_value_stock, 其余返回 errorcode=-9002")
            return _off(-9002, f" {[x for x in il if x != 'ths_market_value_stock']}")
        sh = _free().shares(cl)
        tables, stale = [], []
        for c in cl:
            v = sh.get(c)
            if not v:
                continue
            if date and v["date"] != date:
                stale.append(c)
                continue
            tables.append({"thscode": c, "table": {"ths_market_value_stock": [v["total_mv"]]}})
        if stale:
            _note(f"总市值只能取行情日 {next(iter(sh.values()))['date'] if sh else '?'}, 请求日期 {date} 不符的 {len(stale)} 只不出表")
        _note("iFinD 已停用, 总市值改由腾讯快照(价格乘总股本)提供")
        return {"errorcode": 0 if tables else -9003, "errmsg": "" if tables else "免费源未取到或日期不符",
                "tables": tables, "source": "tencent 快照"}
    import datetime as _dt
    if isinstance(codes, (list, tuple)):
        codes = ",".join(codes)
    if isinstance(indicators, str):
        indicators = [x.strip() for x in indicators.split(",") if x.strip()]
    date = date or _dt.date.today().strftime("%Y-%m-%d")
    r = _post("basic_data_service", {
        "codes": codes,
        "indipara": [{"indicator": i, "indiparams": [date]} for i in indicators]})
    # ⛔ 假空显式化(2026-09-07, 当天第三例同族失败): errorcode=0 但某指标全 None,
    # 多半是**指标名不对**而不是"这只股票没这个数据"。接口不报错, 不喊出来就会被误读成缺数据。
    # 实测: ths_pb_stock → [None](错), ths_pb_latest_stock → 6.617(对); ths_mv_stock → -4210, ths_market_value_stock → 对。
    try:
        if r.get("errorcode") == 0:
            for tb in (r.get("tables") or []):
                for ind, vals in (tb.get("table") or {}).items():
                    if not isinstance(vals, list) or not vals:
                        continue
                    code = tb.get("thscode", "?")
                    if all(v is None for v in vals):
                        print(f"[warn] iFinD basic: {code} 的 {ind} 全为 None (errorcode=0)。"
                              f"多半是指标名不对而非无数据; 已验证可用: "
                              f"ths_pe_ttm_stock / ths_pb_latest_stock / ths_market_value_stock",
                              file=__import__("sys").stderr)
                    # ⛔ 2026-09-07 interview 实测: 美股 HSAI.O 与 港股 6181.HK 的 ths_market_value_stock
                    # 返回 **0.0** 且 errorcode=0。比返回 None 更危险——0 是个合法数字, 直接进模型或
                    # 简历就是灾难, 而且它假装成功。市值/PE/PB 这类基本面指标为 0 一律视为"没取到"。
                    elif any(k in ind for k in ("market_value", "pe_", "pb_", "ps_", "mv")) \
                            and all((v == 0 or v is None) for v in vals):
                        print(f"[warn][⛔可能是假数据] iFinD basic: {code} 的 {ind} 返回 0 (errorcode=0)。"
                              f"0 不是合法市值/估值, 视为未取到, **不要写进任何模型或对外材料**。"
                              f"已知 iFinD 对美股/港股的市值与估值指标权限不全, 该用 yfinance。",
                              file=__import__("sys").stderr)
    except Exception:
        pass
    return r


if __name__ == "__main__":
    print("iFinD 数据层自检:")
    print("  实时:", realtime(["600519.SH"], "latest,changeRatio"))
