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


def basic(codes, indicators):
    """基础/财务数据。indicators如 'pe_ttm,pb,total_shares,mv'。"""
    if isinstance(codes, (list, tuple)):
        codes = ",".join(codes)
    return _post("basic_data_service", {"codes": codes, "indicators": indicators})


if __name__ == "__main__":
    print("iFinD 数据层自检:")
    print("  实时:", realtime(["600519.SH"], "latest,changeRatio"))
