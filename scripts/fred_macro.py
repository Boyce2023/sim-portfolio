# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests",
#     "pandas",
# ]
# ///
"""
FRED 宏观数据拉取器 — 无需 API key，用公共 CSV 端点
https://fred.stlouisfed.org/graph/fredgraph.csv?id=CODE

灵魂(百年校准, 防过度反应):
- 估值类信号(CAPE/ERP/集中度)=长期回报信号, 不进 timing/减仓触发。贵≠脆弱。
- 真触发(高权重, 才减杠杆):
    HY OAS>1000bp / SOFR-EFFR走阔(回购冻结) / 实际利率DFII10一月升>50bp /
    5Y5Y breakeven破2.5% / Sahm≥0.5 / 曲线倒挂后转正。任两个同现=减仓。
- 反向买点: VIX>50, AAII空>50%(本脚本只覆盖FRED部分)。
- 先验默认"不是这次"。对吓人估值默认降权, 把警惕预算留给真触发。

用法:
    uv run --script fred_macro.py            # 打印核心读数表
    uv run --script fred_macro.py --refresh  # 忽略缓存强制重拉
"""
from __future__ import annotations

import io
import json
import sys
import time
from datetime import datetime, date
from pathlib import Path

import requests
import pandas as pd

CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# 缓存: 项目 data/ 目录, 日级 TTL
CACHE_PATH = (Path(__file__).resolve().parent.parent / "data" / "fred_cache.json")

# 注册表里的核心 FRED 代码 (_TRACKER_REGISTRY.md)
CODES = [
    # 信用利差
    "BAMLH0A0HYM2",   # HY OAS  ★★★#1领先
    "BAMLC0A0CM",     # IG OAS
    "BAMLH0A3HYC",    # CCC OAS
    # 实际利率/通胀预期
    "DFII10",         # 10Y 实际利率 ★最高
    "T10YIE",         # 10Y breakeven
    "T5YIFR",         # 5Y5Y 远期通胀锚
    # 融资管道
    "SOFR", "EFFR", "IORB",
    "WRESBAL",        # 准备金余额
    "RRPONTSYD",      # ON RRP
    "WTREGEN",        # TGA
    "WALCL",          # Fed 总资产
    # 周/月频硬数据
    "ICSA",           # 初请失业金
    "SAHMREALTIME",   # Sahm Rule
    "PCEPILFE",       # Core PCE (index)
    "STICKCPIM157SFRBATL",  # Sticky CPI
    # 金融条件
    "NFCI",
]

# 显示元数据: code -> (label, unit, 触发提示)
META = {
    "BAMLH0A0HYM2": ("HY OAS", "bp", "真触发>1000bp / 日变>+50bp"),
    "BAMLC0A0CM": ("IG OAS", "bp", ">200bp 信用周期转向"),
    "BAMLH0A3HYC": ("CCC OAS", "bp", ">1500bp 违约潮"),
    "DFII10": ("10Y 实际利率", "%", "真触发 月升>50bp / >2%警戒"),
    "T10YIE": ("10Y Breakeven", "%", ">2.8% 通胀预期失锚"),
    "T5YIFR": ("5Y5Y 远期", "%", "真触发 破2.5%"),
    "SOFR": ("SOFR", "%", "持续>IORB+20bp 连3日=回购冻结"),
    "EFFR": ("EFFR", "%", "—"),
    "IORB": ("IORB", "%", "SOFR-IORB 利差看管道"),
    "WRESBAL": ("准备金余额", "$M", "跌破~3.0万亿=稀缺区"),
    "RRPONTSYD": ("ON RRP", "$B", "耗尽至0=缓冲没了"),
    "WTREGEN": ("TGA", "$B", "激增=财政抽水"),
    "WALCL": ("Fed 总资产", "$M", "连2周转正=QT结束"),
    "ICSA": ("初请失业金", "人", "MA4>300k 加速=衰退裂缝"),
    "SAHMREALTIME": ("Sahm Rule", "", "真触发 ≥0.50"),
    "PCEPILFE": ("Core PCE (index)", "idx", "看 YoY 二阶导"),
    "STICKCPIM157SFRBATL": ("Sticky CPI YoY", "%", "上行=结构性通胀"),
    "NFCI": ("NFCI 金融条件", "", "穿0上行=系统性收紧"),
}

# bp 单位序列 (OAS 原始单位是百分点, 转 bp 显示)
BP_SERIES = {"BAMLH0A0HYM2", "BAMLC0A0CM", "BAMLH0A3HYC"}


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def _fetch_one(code: str, session: requests.Session) -> dict | None:
    """拉单个 series 的 CSV, 返回 {latest, date, prev, change} 或 None(失败)。"""
    url = CSV_URL.format(code=code)
    try:
        r = session.get(url, timeout=30, headers={"User-Agent": UA})
        if r.status_code != 200:
            return None
        text = r.text
        # FRED bot 防护会返回 HTML/JS 而非 CSV
        if "<html" in text[:200].lower() or "," not in text.split("\n", 1)[0]:
            return None
        df = pd.read_csv(io.StringIO(text))
        if df.shape[1] < 2:
            return None
        dcol, vcol = df.columns[0], df.columns[1]
        df[vcol] = pd.to_numeric(df[vcol], errors="coerce")
        df = df.dropna(subset=[vcol])
        if df.empty:
            return None
        df = df.tail(2).reset_index(drop=True)
        latest = float(df[vcol].iloc[-1])
        ldate = str(df[dcol].iloc[-1])
        prev = float(df[vcol].iloc[-2]) if len(df) > 1 else None
        change = (latest - prev) if prev is not None else None
        return {"latest": latest, "date": ldate, "prev": prev, "change": change}
    except Exception:
        return None


def fetch_fred(codes: list, refresh: bool = False) -> dict:
    """
    返回 {code: {latest, date, prev, change}}。
    日级缓存到 data/fred_cache.json(TTL=当天)。拉不到的 code 不进结果。
    """
    cache = _load_cache()
    today = date.today().isoformat()
    fresh_ok = (
        not refresh
        and cache.get("_cached_date") == today
        and "data" in cache
    )
    if fresh_ok:
        cached = cache["data"]
        if all(c in cached for c in codes):
            return {c: cached[c] for c in codes}

    out: dict = dict(cache.get("data", {})) if cache.get("_cached_date") == today else {}
    session = requests.Session()
    for code in codes:
        if not refresh and code in out:
            continue
        res = _fetch_one(code, session)
        if res is not None:
            out[code] = res
        time.sleep(3.0)  # FRED 限流: 每请求间隔 3s, 防 bot 挑战

    _save_cache({"_cached_date": today, "_fetched_at": datetime.now().isoformat(), "data": out})
    return {c: out[c] for c in codes if c in out}


def _fmt_val(code: str, v: float) -> str:
    if code in BP_SERIES:
        return f"{v * 100:.0f}bp"
    meta = META.get(code, ("", "", ""))
    unit = meta[1]
    if unit in ("%",):
        return f"{v:.2f}%"
    if unit in ("idx", ""):
        return f"{v:.3f}".rstrip("0").rstrip(".")
    if unit == "人":
        return f"{v:,.0f}"
    return f"{v:,.0f}"


def _fmt_chg(code: str, c: float | None) -> str:
    if c is None:
        return ""
    if code in BP_SERIES:
        return f"{c * 100:+.0f}bp"
    meta = META.get(code, ("", "", ""))
    if meta[1] == "%":
        return f"{c:+.2f}"
    return f"{c:+,.0f}"


def _derived(data: dict) -> list:
    """衍生信号: HY-IG质差, SOFR-IORB, SOFR-EFFR。"""
    rows = []

    def have(*ks):
        return all(k in data for k in ks)

    if have("BAMLH0A0HYM2", "BAMLC0A0CM"):
        d = (data["BAMLH0A0HYM2"]["latest"] - data["BAMLC0A0CM"]["latest"]) * 100
        rows.append(("HY-IG 质量利差", f"{d:.0f}bp", "急速走阔=质量逃离(早于HY突破)"))
    if have("SOFR", "IORB"):
        d = (data["SOFR"]["latest"] - data["IORB"]["latest"]) * 100
        rows.append(("SOFR-IORB", f"{d:+.0f}bp", "持续>+20bp连3日=回购冻结(真触发)"))
    if have("SOFR", "EFFR"):
        d = (data["SOFR"]["latest"] - data["EFFR"]["latest"]) * 100
        rows.append(("SOFR-EFFR", f"{d:+.0f}bp", ">+10bp=短端融资紧张"))
    return rows


def print_table(data: dict, requested: list) -> None:
    today = date.today().isoformat()
    print(f"\n═══ FRED MACRO 核心读数  {today} ═══")
    print(f"{'指标':<18} {'最新值':<12} {'日期':<12} {'变动':<10} 触发提示")
    print("─" * 92)
    missing = []
    for code in requested:
        meta = META.get(code, (code, "", ""))
        label = meta[0]
        if code not in data:
            missing.append(f"{label}({code})")
            print(f"{label:<17} {'拉不到':<12} {'—':<12} {'—':<10} (FRED未返回, 不编数字)")
            continue
        d = data[code]
        val = _fmt_val(code, d["latest"])
        chg = _fmt_chg(code, d.get("change"))
        # 中文宽字符对齐补偿
        pad = 18 - sum(2 if ord(ch) > 127 else 1 for ch in label)
        print(f"{label}{' ' * max(pad,1)}{val:<12} {d['date']:<12} {chg:<10} {meta[2]}")

    deriv = _derived(data)
    if deriv:
        print("\n── 衍生信号 ──")
        for name, val, hint in deriv:
            pad = 18 - sum(2 if ord(ch) > 127 else 1 for ch in name)
            print(f"{name}{' ' * max(pad,1)}{val:<12} {'':12} {'':10} {hint}")

    if missing:
        print(f"\n⚠ 未拉到({len(missing)}): {', '.join(missing)} — 标注缺失, 不编数字")
    print()


def main() -> int:
    refresh = "--refresh" in sys.argv
    data = fetch_fred(CODES, refresh=refresh)
    print_table(data, CODES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
