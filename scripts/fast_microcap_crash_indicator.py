#!/usr/bin/env python3
"""
只读小微盘大踩踏预警指标（供 astock 一号席每日盘前/09:25 报盘参考，零改动任何现役 V20.0 规则）。
来源：RD044 量化四大家族实证（小市值排雷加 20 日动量切国债开关 + 极端踩踏红灯分层）。
数据源：腾讯国内直连行情接口（国证 2000 sz399303 + 中证 1000 sh000852 + 沪深 300 sh000300），严守 D12 零 yfinance。
"""
import argparse
import datetime
import json
import sys
import time
import urllib.request
from typing import Dict, List, Tuple


def fetch_tencent_daily(secid: str, n: int = 45, include_intraday: bool = True) -> List[Tuple[str, float, float, float, float]]:
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={secid},day,,,{n},"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8"))
    d = raw["data"][secid]
    rows = d.get("day") or []
    out: List[Tuple[str, float, float, float, float]] = []
    for r in rows:
        if len(r) >= 5:
            out.append((str(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    if include_intraday:
        qt = d.get("qt", {}).get(secid)
        if qt and len(qt) > 35:
            qdate = str(qt[30])[:8]
            if len(qdate) == 8 and qdate.isdigit():
                qdate_fmt = f"{qdate[:4]}-{qdate[4:6]}-{qdate[6:8]}"
                cur_c = float(qt[3])
                if cur_c > 0:
                    if out and out[-1][0] == qdate_fmt:
                        out[-1] = (qdate_fmt, float(qt[5]), cur_c, float(qt[33]), float(qt[34]))
                    elif not out or qdate_fmt > out[-1][0]:
                        out.append((qdate_fmt, float(qt[5]), cur_c, float(qt[33]), float(qt[34])))
    return out


def compute_metrics(rows: List[Tuple[str, float, float, float, float]], asof_closed_only: bool = False) -> Dict[str, float]:
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    now_hm = datetime.datetime.now().strftime("%H:%M")
    if asof_closed_only and rows and rows[-1][0] == today_str and now_hm < "15:01":
        rows = rows[:-1]
    if len(rows) < 22:
        raise RuntimeError(f"Insufficient rows: {len(rows)}")
    closes = [r[2] for r in rows]
    c = closes[-1]
    m1 = (c / closes[-2] - 1.0) * 100.0
    m5 = (c / closes[-6] - 1.0) * 100.0
    m10 = (c / closes[-11] - 1.0) * 100.0
    m20 = (c / closes[-21] - 1.0) * 100.0
    ma20 = sum(closes[-20:]) / 20.0
    vs_ma20 = (c / ma20 - 1.0) * 100.0
    peak20 = max(closes[-21:])
    dd20 = (c / peak20 - 1.0) * 100.0
    return {
        "date": rows[-1][0],
        "close": round(c, 2),
        "m1_pct": round(m1, 2),
        "m5_pct": round(m5, 2),
        "m10_pct": round(m10, 2),
        "m20_pct": round(m20, 2),
        "vs_ma20_pct": round(vs_ma20, 2),
        "dd20_pct": round(dd20, 2),
    }


def evaluate_indicator(premarket: bool = False) -> Dict[str, object]:
    t0 = time.time()
    r_gz2000 = fetch_tencent_daily("sz399303", n=45, include_intraday=not premarket)
    r_zz1000 = fetch_tencent_daily("sh000852", n=45, include_intraday=not premarket)
    r_hs300 = fetch_tencent_daily("sh000300", n=45, include_intraday=not premarket)

    gz = compute_metrics(r_gz2000, asof_closed_only=premarket)
    zz = compute_metrics(r_zz1000, asof_closed_only=premarket)
    hs = compute_metrics(r_hs300, asof_closed_only=premarket)

    rel10_vs_hs300 = round(gz["m10_pct"] - hs["m10_pct"], 2)

    # 分级标准（来源 RD044 实证）：
    # 黄灯（常规切国债防守线，6 年约占 28% 交易日）：20 日跌超 4% 或破 20 日均线超 3%
    # 红灯（极端小微盘大踩踏预警，6 年仅占 6.7% 交易日）：5 日跌超 7% 或 10 日跌超 10% 或 20 日高点回撤超 12%
    is_red = (gz["m5_pct"] <= -7.0) or (gz["m10_pct"] <= -10.0) or (gz["dd20_pct"] <= -12.0)
    is_yellow = (gz["m20_pct"] < -4.0) or (gz["vs_ma20_pct"] < -3.0)

    if is_red:
        level = "RED"
        label = "红灯极端踩踏预警"
        advice = "小微盘正处极端急杀踩踏区（小市值量化切国债防守；打板主账按原规则执行，仅作极端环境提示）"
    elif is_yellow:
        level = "YELLOW"
        label = "黄灯常规走弱"
        advice = "小微盘低于 20 日线常规走弱（小市值量化切国债；非极端踩踏，打板主账照常）"
    else:
        level = "GREEN"
        label = "绿灯正常"
        advice = "小微盘趋势正常，无踩踏风险"

    return {
        "mode": "premarket" if premarket else "live",
        "asof_date": gz["date"],
        "level": level,
        "label": label,
        "advice": advice,
        "gz2000": gz,
        "zz1000": zz,
        "hs300": hs,
        "rel10_vs_hs300_pct": rel10_vs_hs300,
        "elapsed_sec": round(time.time() - t0, 2),
    }


def format_one_line(res: Dict[str, object]) -> str:
    gz = res["gz2000"]
    hs = res["hs300"]
    rel = res["rel10_vs_hs300_pct"]
    mode_cn = "盘前截至昨收" if res["mode"] == "premarket" else "实时"
    return (
        f"【小微盘踩踏温度计】{res['asof_date']}（{mode_cn} | 耗时 {res['elapsed_sec']:.2f}s）："
        f"{res['label']} | 国证2000 5日 {gz['m5_pct']:+.2f}% / 10日 {gz['m10_pct']:+.2f}% / "
        f"20日回撤 {gz['dd20_pct']:+.2f}% / 偏离20日线 {gz['vs_ma20_pct']:+.2f}% "
        f"（近10日相对沪深300 {hs['m10_pct']:+.2f}% 超额 {rel:+.2f} 点）"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="只读小微盘极端踩踏预警指标（零 yfinance）")
    parser.add_argument("--premarket", action="store_true", help="盘前模式（仅取截至昨日已收盘数据）")
    parser.add_argument("--json-only", action="store_true", help="仅输出 JSON")
    args = parser.parse_args()
    res = evaluate_indicator(premarket=args.premarket)
    if args.json_only:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print(format_one_line(res))
        print(f"  提示：{res['advice']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
