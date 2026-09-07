#!/usr/bin/env python3
"""
ifind_data_layer.py — 同花顺 iFinD HTTP 数据接口封装 (机构级A股/港股/美股)
==================================================================
2026-07-24 接入。相比 akshare/东财: 机构级数据、无代理DNS劫持问题、覆盖全。
token 存钥匙串(不留明文): refresh_token(service=ifind-refresh-token) → 自动换 access_token。
access_token 会过期, 本模块遇鉴权错自动用 refresh_token 重新换。
⚠️ refresh_token 本身 2026-07-26 过期 — 到期需在 quantapi.10jqka.com.cn 重新生成并更新钥匙串。

用法:
    from ifind_data_layer import realtime, history, basic
    realtime(["600519.SH"], "latest,changeRatio,pe_ttm")
    history("600519.SH", "2026-01-01", "2026-07-24", "close")
"""
import json
import time
import subprocess
import urllib.request
import urllib.error

BASE = "https://quantapi.10jqka.com.cn/api/v1"
_UID = "728027802"
_at_cache = {"token": "", "ts": 0}


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
    """历史行情。period: D/W/M。返回原始tables。"""
    return _post("cmd_history_quotation", {"codes": code, "indicators": indicators,
                                           "startdate": start, "enddate": end,
                                           "functionpara": {"period": period}})


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
