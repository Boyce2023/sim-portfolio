#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""美股稳健取价、SEC 13F 量纲自检与飞书财报空间读取公共工具（2026-11-25 全员复盘 Phase 2 沉淀）。

固化修复：
- U9: yfinance.history() 必须链式 .dropna()，并在美股刚收盘后的早盘窗口（CST 05:00 至 10:00）
      自动与 fast_info.lastPrice 交叉回退，彻底杜绝末尾 NaN 占位行。
- U3: SEC 13F XML 金额列自动按中位数 (value/shares)/price 做量纲自检，识别旧版 $000 千美元填报并自动 ×1000。
- U8: 飞书《财报纪要 / 2026Q3 财报季专区》指向实测活跃空间 7702350621394947083（替代失效旧 ID 7614873368775544429）。
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import statistics
import subprocess
import urllib.error
import urllib.request
from typing import Dict, Iterable, List, Tuple

import yfinance as yf

FEISHU_EARNINGS_SPACE_ID = "7702350621394947083"
FEISHU_Q3_2026_NODE_TOKEN = "N6v9wJ59BioybdkYOaucbl9HnUf"


def _fetch_one_us_quote(ticker: str) -> Tuple[str, dict]:
    tk = yf.Ticker(ticker)
    hist = tk.history(period="10d")["Close"].dropna()
    hist_dt = str(hist.index[-1].date()) if len(hist) else None
    hist_px = float(hist.iloc[-1]) if len(hist) else None
    hist_prev = float(hist.iloc[-2]) if len(hist) >= 2 else hist_px

    fi_px = None
    fi_prev = None
    try:
        fi = tk.fast_info
        raw_lp = fi.get("lastPrice") or fi.get("regularMarketPrice")
        raw_pc = fi.get("previousClose") or fi.get("regularMarketPreviousClose")
        fi_px = float(raw_lp) if raw_lp is not None else None
        fi_prev = float(raw_pc) if raw_pc is not None else None
    except Exception:
        pass

    # 若 fast_info 存在有效价格且与日线末价不一致（常见于刚收盘后日线尚未落盘或盘中），优先 fast_info
    use_fi = fi_px is not None and (hist_px is None or abs(fi_px - hist_px) / max(hist_px, 1e-6) > 1e-4)
    price = fi_px if use_fi else hist_px
    prev = (fi_prev if (use_fi and fi_prev) else hist_prev) or price
    chg_pct = round((price / prev - 1.0) * 100.0, 2) if (price and prev) else None
    return ticker, {
        "ticker": ticker,
        "price": round(price, 4) if price is not None else None,
        "prev_close": round(prev, 4) if prev is not None else None,
        "change_pct": chg_pct,
        "hist_date": hist_dt,
        "source": "fast_info" if use_fi else "history_dropna",
    }


def fetch_us_close_safe(tickers: Iterable[str], max_workers: int = 10) -> Dict[str, dict]:
    """并发拉取美股/全球 yfinance 收盘或实时价，强制 .dropna() + fast_info 防 NaN。"""
    tks = list(dict.fromkeys(tickers))
    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(tks)))) as ex:
        return dict(ex.map(_fetch_one_us_quote, tks))


def normalize_13f_values(rows: List[dict], price_map: Dict[str, float]) -> Tuple[List[dict], dict]:
    """校验单份 13F XML 持仓列表的金额单位（$000 vs $1），自动纠偏千美元旧口径。

    rows 每项需包含 ticker, shares, value（原始 XML 整数）。
    返回 (normalized_rows, audit_info)。
    """
    ratios = []
    implied_pxs = []
    for r in rows:
        sh = float(r.get("shares") or 0)
        val = float(r.get("value") or 0)
        if sh <= 0 or val <= 0:
            continue
        imp = val / sh
        implied_pxs.append(imp)
        ref = price_map.get(r.get("ticker", ""))
        if ref and ref > 0:
            ratios.append(imp / ref)

    scale = 1.0
    unit_detected = "USD_exact"
    med_ratio = statistics.median(ratios) if ratios else None
    med_imp = statistics.median(implied_pxs) if implied_pxs else None

    if med_ratio is not None:
        if 0.0002 <= med_ratio <= 0.01:
            scale = 1000.0
            unit_detected = "USD_thousands_auto_x1000"
        elif med_ratio < 0.1 or med_ratio > 10.0:
            raise ValueError(f"13F 量纲异常：median(implied_px/ref_px)={med_ratio:.4f}，请人工核查原件")
    elif med_imp is not None and med_imp < 1.5:
        scale = 1000.0
        unit_detected = "USD_thousands_fallback_x1000"

    out = []
    for r in rows:
        nr = dict(r)
        nr["value_usd"] = round(float(r.get("value") or 0) * scale, 2)
        out.append(nr)
    return out, {
        "scale": scale,
        "unit_detected": unit_detected,
        "median_ratio_to_price": round(med_ratio, 6) if med_ratio is not None else None,
        "median_implied_px": round(med_imp, 4) if med_imp is not None else None,
    }


def list_feishu_q3_earnings_nodes() -> dict:
    """读取飞书《财报纪要》(7702350621394947083) 下 2026Q3 财报季专区子节点，用于健康巡检与底稿检索。"""
    tok = subprocess.check_output(
        ["/opt/homebrew/bin/python3.13", os.path.expanduser("~/.claude/session-remote/feishu_token.py")],
        text=True,
    ).strip()
    url = (
        f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{FEISHU_EARNINGS_SPACE_ID}/nodes"
        f"?parent_node_token={FEISHU_Q3_2026_NODE_TOKEN}&page_size=50"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        res = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
        items = (res.get("data") or {}).get("items") or []
        return {"ok": True, "space_id": FEISHU_EARNINGS_SPACE_ID, "count": len(items), "titles": [x.get("title") for x in items]}
    except urllib.error.HTTPError as e:
        return {"ok": False, "space_id": FEISHU_EARNINGS_SPACE_ID, "http": e.code, "body": e.read().decode(errors="ignore")[:200]}


if __name__ == "__main__":
    q = fetch_us_close_safe(["NVDA", "LRCX", "SPY"])
    assert all(v["price"] is not None and v["price"] > 0 for v in q.values()), f"Bad quote: {q}"
    print("QUOTE_TEST_OK:", {k: (v["price"], v["change_pct"], v["source"]) for k, v in q.items()})

    # 13F $000 auto-detection unit test
    sample_000 = [{"ticker": "NVDA", "shares": 1000, "value": 155}, {"ticker": "LRCX", "shares": 500, "value": 98}]
    norm, audit = normalize_13f_values(sample_000, {"NVDA": q["NVDA"]["price"], "LRCX": q["LRCX"]["price"]})
    assert audit["scale"] == 1000.0 and norm[0]["value_usd"] == 155000.0, f"13F test failed: {audit}"
    print("13F_UNIT_TEST_OK:", audit)

    fs = list_feishu_q3_earnings_nodes()
    print("FEISHU_EARNINGS_TEST:", fs["ok"], "space=", fs["space_id"], "q3_children=", fs.get("count"), fs.get("titles", [])[:5])
