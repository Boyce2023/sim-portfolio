# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests",
#     "pandas",
# ]
# ///
"""
macro_engine.py — 宏观第一判断引擎(每天开盘前跑)

设计依据: research-notes/macro/_TRACKER_REGISTRY.md (5域投票引擎+硬触发距离表)
        research-notes/macro/_HISTORY_CALIBRATION.md (百年校准, 防过度反应)

⛔灵魂(百年校准):
- 估值类信号(CAPE/ERP/集中度)=长期回报信号, 权重低, 绝不进 timing/减仓触发。贵≠脆弱。
- 真触发(高权重, 才减杠杆):
    HY OAS>1000bp / SOFR-EFFR走阔(回购冻结) / 实际利率DFII10一月升>50bp /
    5Y5Y breakeven破2.5% / Sahm≥0.5 / 曲线倒挂后转正。任两个同现=减仓。
- 反向买点: VIX>50 且 AAII空>50%(AAII需外部源, 本引擎只判 VIX)。
- 先验默认"不是这次"。对吓人估值默认降权, 把警惕预算留给真触发。

数据源:
- yf 市场proxy层(实时): /Users/huaichuaibeimeng/.claude/skills/yahoo-finance/scripts/yf
- FRED 官方序列(T+1日频): fred_macro.py(同目录) + 直拉 CSV 算 DFII10 一月升幅

用法:
    uv run --script macro_engine.py            # 一屏 dashboard
    uv run --script macro_engine.py --refresh  # 忽略 FRED 缓存强制重拉
    uv run --script macro_engine.py --json      # 输出 regime dict(JSON)
import:
    from macro_engine import get_regime
    r = get_regime()  # -> dict
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import requests
import pandas as pd

# ── 路径 ─────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
YF = "/Users/huaichuaibeimeng/.claude/skills/yahoo-finance/scripts/yf"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# 复用 fred_macro 的拉取器(同目录)
sys.path.insert(0, str(HERE))
try:
    from fred_macro import fetch_fred  # type: ignore
except Exception:
    fetch_fred = None  # 降级: 标注缺失, 不编数字


# ── yf 取数(诚实标注, 拉不到返回 None) ─────────────────
def yf_price(symbol: str) -> float | None:
    try:
        out = subprocess.run(
            [YF, "price", symbol, "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return None
        d = json.loads(out.stdout.strip())
        p = d.get("price")
        return float(p) if p is not None else None
    except Exception:
        return None


def yf_history_close(symbol: str, period: str) -> list[tuple[str, float]] | None:
    try:
        out = subprocess.run(
            [YF, "history", symbol, period, "--json"],
            capture_output=True, text=True, timeout=40,
        )
        if out.returncode != 0:
            return None
        d = json.loads(out.stdout.strip())
        rows = d.get("data") or []
        series = [(r["date"], float(r["close"])) for r in rows if r.get("close") is not None]
        return series or None
    except Exception:
        return None


# ── FRED: DFII10 一月升幅(真触发需要, fred_macro 只给日delta) ──
def fred_series_recent(code: str, tail: int = 40) -> list[tuple[str, float]] | None:
    try:
        r = requests.get(FRED_CSV.format(code=code), timeout=30,
                         headers={"User-Agent": UA})
        if r.status_code != 200 or "<html" in r.text[:200].lower():
            return None
        df = pd.read_csv(io.StringIO(r.text))
        if df.shape[1] < 2:
            return None
        dcol, vcol = df.columns[0], df.columns[1]
        df[vcol] = pd.to_numeric(df[vcol], errors="coerce")
        df = df.dropna(subset=[vcol]).tail(tail)
        return [(str(a), float(b)) for a, b in zip(df[dcol], df[vcol])]
    except Exception:
        return None


def dfii10_one_month_change(series: list[tuple[str, float]] | None) -> float | None:
    """DFII10 当前值 vs ~21个交易日前(约一月)。返回 bp。"""
    if not series or len(series) < 22:
        return None
    latest = series[-1][1]
    month_ago = series[-22][1]
    return (latest - month_ago) * 100  # %→bp


# ── 信号助手 ─────────────────────────────────────────
def _g(d: dict, code: str) -> float | None:
    v = d.get(code)
    return v["latest"] if v else None


def _gdate(d: dict, code: str) -> str | None:
    """取某 FRED 序列的 as_of 日期(数据真实截止日, 非today)。"""
    v = d.get(code)
    return v.get("date") if v else None


def _bdays_lag(as_of: str | None, today: "date") -> int | None:
    """as_of 距今的工作日数(粗算: 按日历日数过滤周末)。None=无日期。"""
    if not as_of:
        return None
    try:
        from datetime import date as _d
        y, m, dd = (int(x) for x in as_of[:10].split("-"))
        ao = _d(y, m, dd)
    except Exception:
        return None
    if ao >= today:
        return 0
    n = 0
    cur = ao
    while cur < today:
        cur = cur.fromordinal(cur.toordinal() + 1)
        if cur.weekday() < 5:
            n += 1
    return n


# 各域 staleness 容忍(工作日): 融资管道最敏感=1日, 信用=3日, 利率/通胀=2日
_STALE_TOL = {"信用": 3, "融资管道": 1, "实际利率": 2, "通胀预期": 2}


# ══════════════════════════════════════════════════════
# 核心: 拉全部 tracker
# ══════════════════════════════════════════════════════
def collect(refresh: bool = False) -> dict:
    t: dict = {"missing": []}

    # ── yf 市场proxy层 ──
    t["TNX"] = yf_price("^TNX")          # 10Y 名义
    t["IRX"] = yf_price("^IRX")          # 13wk bill(短端/3M代理)
    t["VIX"] = yf_price("^VIX")
    t["VIX9D"] = yf_price("^VIX9D")
    t["VIX3M"] = yf_price("^VIX3M")
    t["HYG"] = yf_price("HYG")
    t["LQD"] = yf_price("LQD")
    t["HG"] = yf_price("HG=F")           # 铜
    t["GC"] = yf_price("GC=F")           # 金
    t["JPY"] = yf_price("JPY=X")         # USDJPY

    # 铜金比 5日Δ
    hg_hist = yf_history_close("HG=F", "1mo")
    gc_hist = yf_history_close("GC=F", "1mo")
    t["copper_gold_5d_chg_pct"] = None
    if hg_hist and gc_hist and len(hg_hist) >= 6 and len(gc_hist) >= 6:
        def ratio(hg, gc, i):
            return hg[i][1] / gc[i][1]
        now = ratio(hg_hist, gc_hist, -1)
        ago = ratio(hg_hist, gc_hist, -6)
        if ago:
            t["copper_gold_5d_chg_pct"] = (now / ago - 1) * 100

    # RSP/SPY 广度 vs 200dma
    rsp = yf_history_close("RSP", "1y")
    spy = yf_history_close("SPY", "1y")
    t["rsp_spy_vs_200dma"] = None
    t["rsp_spy_now"] = None
    if rsp and spy and len(rsp) >= 200 and len(spy) >= 200:
        # 对齐到共同长度
        n = min(len(rsp), len(spy))
        rsp, spy = rsp[-n:], spy[-n:]
        ratio_series = [rsp[i][1] / spy[i][1] for i in range(n)]
        now_r = ratio_series[-1]
        ma200 = sum(ratio_series[-200:]) / 200
        t["rsp_spy_now"] = now_r
        t["rsp_spy_vs_200dma"] = (now_r / ma200 - 1) * 100  # %相对200dma

    # 衍生比率
    t["vix_term"] = None   # VIX/VIX3M >1=backwardation
    if t["VIX"] and t["VIX3M"]:
        t["vix_term"] = t["VIX"] / t["VIX3M"]
    t["vix9d_vix"] = None
    if t["VIX9D"] and t["VIX"]:
        t["vix9d_vix"] = t["VIX9D"] / t["VIX"]

    t["hyg_lqd"] = None
    if t["HYG"] and t["LQD"]:
        t["hyg_lqd"] = t["HYG"] / t["LQD"]

    # 曲线 10Y-3M 代理 (^TNX - ^IRX)
    t["curve_10y3m"] = None
    if t["TNX"] is not None and t["IRX"] is not None:
        t["curve_10y3m"] = t["TNX"] - t["IRX"]  # 单位 %; <0=倒挂

    # ── FRED 官方序列 ──
    fred = {}
    if fetch_fred is not None:
        codes = ["BAMLH0A0HYM2", "BAMLC0A0CM", "BAMLH0A3HYC",
                 "DFII10", "T10YIE", "T5YIFR",
                 "SOFR", "EFFR", "IORB",
                 "WRESBAL", "SAHMREALTIME", "ICSA", "NFCI"]
        try:
            fred = fetch_fred(codes, refresh=refresh)
        except Exception:
            fred = {}
    t["fred"] = fred

    t["HY_OAS"] = _g(fred, "BAMLH0A0HYM2")        # %
    t["HY_OAS_chg"] = (fred.get("BAMLH0A0HYM2") or {}).get("change")  # %日变
    t["IG_OAS"] = _g(fred, "BAMLC0A0CM")
    t["CCC_OAS"] = _g(fred, "BAMLH0A3HYC")
    t["DFII10"] = _g(fred, "DFII10")
    t["T10YIE"] = _g(fred, "T10YIE")
    t["T5YIFR"] = _g(fred, "T5YIFR")
    t["SOFR"] = _g(fred, "SOFR")
    t["EFFR"] = _g(fred, "EFFR")
    t["IORB"] = _g(fred, "IORB")
    t["WRESBAL"] = _g(fred, "WRESBAL")
    t["SAHM"] = _g(fred, "SAHMREALTIME")
    t["NFCI"] = _g(fred, "NFCI")

    # ── Staleness 检查(修复: 同fetch_prices 6/12滞后病, 防陈数据当今天用)──
    from datetime import date as _date
    _today = _date.today()
    t["fred_dates"] = {
        "信用": _gdate(fred, "BAMLH0A0HYM2"),
        "融资管道": _gdate(fred, "SOFR"),
        "实际利率": _gdate(fred, "DFII10"),
        "通胀预期": _gdate(fred, "T5YIFR"),
    }
    t["stale"] = {}
    for dom, tol in _STALE_TOL.items():
        lag = _bdays_lag(t["fred_dates"].get(dom), _today)
        t["stale"][dom] = (lag is not None and lag > tol)
    t["any_stale"] = any(t["stale"].values())

    # 衍生 FRED — ⛔跨日期对齐检查(SOFR-IORB是回购冻结触发器, 最该实时)
    t["sofr_iorb_bp"] = None
    t["sofr_iorb_misaligned"] = False
    if t["SOFR"] is not None and t["IORB"] is not None:
        if _gdate(fred, "SOFR") == _gdate(fred, "IORB"):
            t["sofr_iorb_bp"] = (t["SOFR"] - t["IORB"]) * 100
        else:
            t["sofr_iorb_misaligned"] = True  # 两个序列日期不对齐, 不算, 不静默
    t["sofr_effr_bp"] = None
    if t["SOFR"] is not None and t["EFFR"] is not None and _gdate(fred, "SOFR") == _gdate(fred, "EFFR"):
        t["sofr_effr_bp"] = (t["SOFR"] - t["EFFR"]) * 100
    t["hy_ig_bp"] = None
    if t["HY_OAS"] is not None and t["IG_OAS"] is not None:
        t["hy_ig_bp"] = (t["HY_OAS"] - t["IG_OAS"]) * 100

    # DFII10 一月升幅(真触发)
    dfii_series = fred_series_recent("DFII10")
    t["dfii10_1m_bp"] = dfii10_one_month_change(dfii_series)

    return t


# ══════════════════════════════════════════════════════
# Regime 引擎: 5域投票(注册表 §2)
# ══════════════════════════════════════════════════════
def score_domains(t: dict) -> list[dict]:
    """每域返回 {name, reading, vote(on/neutral/off/na), note}。"""
    domains = []

    # 1. 信用: HY OAS
    hy = t.get("HY_OAS")
    hy_chg = t.get("HY_OAS_chg")
    if hy is None:
        domains.append(dict(name="信用", reading="HY OAS 拉不到", vote="na", note="FRED未返回"))
    else:
        bp = hy * 100
        chg_bp = (hy_chg * 100) if hy_chg is not None else None
        spike = chg_bp is not None and chg_bp > 50
        if bp > 600 or spike:
            vote = "off"
        elif bp < 400:
            vote = "on"
        else:
            vote = "neutral"
        note = f"<400绿/400-600中/>600或日变>50bp红"
        rd = f"HY OAS {bp:.0f}bp"
        if chg_bp is not None:
            rd += f" (日变{chg_bp:+.0f}bp)"
        domains.append(dict(name="信用", reading=rd, vote=vote, note=note))

    # 2. 实际利率: DFII10 水平 + 1月Δ
    dfii = t.get("DFII10")
    d1m = t.get("dfii10_1m_bp")
    if dfii is None:
        domains.append(dict(name="实际利率", reading="DFII10 拉不到", vote="na", note="FRED未返回"))
    else:
        accel = d1m is not None and d1m > 50
        if dfii > 2.0 or accel:
            vote = "off"
        elif dfii < 1.5:
            vote = "on"
        else:
            vote = "neutral"
        rd = f"DFII10 {dfii:.2f}%"
        if d1m is not None:
            rd += f" (月Δ{d1m:+.0f}bp)"
        domains.append(dict(name="实际利率", reading=rd, vote=vote,
                            note="<1.5%稳/1.5-2%中/>2%或月升>50bp红"))

    # 3. 融资管道: SOFR-IORB
    si = t.get("sofr_iorb_bp")
    if si is None:
        domains.append(dict(name="融资管道", reading="SOFR-IORB 拉不到", vote="na", note="FRED未返回"))
    else:
        if si > 20:
            vote = "off"
        elif si <= 0:
            vote = "on"
        else:
            vote = "neutral"
        domains.append(dict(name="融资管道", reading=f"SOFR-IORB {si:+.0f}bp",
                            vote=vote, note="<0绿/0-20中/>20bp连3日红(回购冻结)"))

    # 4. 增长: 铜金比5日Δ + 曲线
    cg = t.get("copper_gold_5d_chg_pct")
    curve = t.get("curve_10y3m")
    parts = []
    if cg is not None:
        parts.append(f"铜金比5d {cg:+.1f}%")
    if curve is not None:
        parts.append(f"曲线10Y-3M {curve:+.2f}%")
    if cg is None and curve is None:
        domains.append(dict(name="增长", reading="铜金比/曲线 拉不到", vote="na", note="yf未返回"))
    else:
        vote = "neutral"
        # 倒挂转正(短端暴跌)是危机临近; 这里简化: 倒挂=警觉
        inverted = curve is not None and curve < 0
        cg_drop = cg is not None and cg < -3  # 5日急跌
        cg_up = cg is not None and cg > 0
        if cg_drop or inverted:
            vote = "off"
        elif cg_up and (curve is None or curve > 0):
            vote = "on"
        domains.append(dict(name="增长", reading=" / ".join(parts), vote=vote,
                            note="铜金比上行+曲线正=绿; 急跌/倒挂=红"))

    # 5. 波动结构: VIX/VIX3M
    vt = t.get("vix_term")
    vix = t.get("VIX")
    if vt is None:
        domains.append(dict(name="波动结构", reading="VIX期限 拉不到", vote="na", note="yf未返回"))
    else:
        if vt > 1.0:
            vote = "off"   # backwardation = 真实压力
        elif vt < 0.95:
            vote = "on"
        else:
            vote = "neutral"
        rd = f"VIX/VIX3M {vt:.3f}"
        if vix is not None:
            rd = f"VIX {vix:.1f} | " + rd
        domains.append(dict(name="波动结构", reading=rd, vote=vote,
                            note="<0.95 contango绿/>1.0 backwardation红"))

    return domains


def reverse_buy_gate(t: dict) -> dict:
    """反向买点闸: VIX>50 (AAII需外部源, 标注缺失)。"""
    vix = t.get("VIX")
    triggered = vix is not None and vix > 50
    return {
        "triggered": triggered,
        "vix": vix,
        "note": "VIX>50触发器满足" if triggered else "VIX<50未触发",
        "aaii": "AAII Bear%需外部源(aaii.com), 本引擎未覆盖 — 实战需人工确认配对",
    }


# ── 硬触发距离表(注册表 §3) ──
def hard_trigger_distances(t: dict) -> list[dict]:
    rows = []

    def row(name, cur, thr, dist, note, fired=False):
        rows.append(dict(name=name, current=cur, threshold=thr,
                         distance=dist, note=note, fired=fired))

    # 信用利差极端
    hy = t.get("HY_OAS")
    if hy is not None:
        bp = hy * 100
        row("信用利差极端", f"{bp:.0f}bp", "1000bp",
            f"{bp-1000:+.0f}bp", "破1000bp=系统性事件; 500-1000先降仓",
            fired=bp > 1000)
    else:
        row("信用利差极端", "拉不到", "1000bp", "—", "FRED未返回HY OAS")

    # 融资管道冻结
    si = t.get("sofr_iorb_bp")
    se = t.get("sofr_effr_bp")
    if si is not None:
        row("融资管道冻结", f"SOFR-IORB {si:+.0f}bp", "+20bp",
            f"{si-20:+.0f}bp", "连3日>+20bp / SOFR-EFFR>10bp=回购冻结",
            fired=si > 20)
    elif se is not None:
        row("融资管道冻结", f"SOFR-EFFR {se:+.0f}bp", "+10bp",
            f"{se-10:+.0f}bp", "回购冻结真触发", fired=se > 10)
    else:
        row("融资管道冻结", "拉不到", "+20bp", "—", "FRED未返回SOFR/IORB")

    # 实际利率转正加速
    dfii = t.get("DFII10")
    d1m = t.get("dfii10_1m_bp")
    if dfii is not None:
        lvl_ok = dfii > 2.0
        if d1m is not None:
            fired = lvl_ok and d1m > 50
            row("实际利率转正加速", f"{dfii:.2f}% 月Δ{d1m:+.0f}bp", ">2% & 月升>50bp",
                f"水平{dfii-2.0:+.2f}pp / 月升{d1m-50:+.0f}bp", "杀growth/SOXL引擎",
                fired=fired)
        else:
            row("实际利率转正加速", f"{dfii:.2f}% (月Δ缺)", ">2% & 月升>50bp",
                f"水平{dfii-2.0:+.2f}pp", "月升幅拉不到, 只判水平")
    else:
        row("实际利率转正加速", "拉不到", ">2% & 月升>50bp", "—", "FRED未返回DFII10")

    # 5Y5Y 通胀失锚
    t5 = t.get("T5YIFR")
    if t5 is not None:
        row("通胀预期失锚", f"5Y5Y {t5:.2f}%", "2.5%",
            f"{t5-2.5:+.2f}pp", "破2.5%=Fed最看重的锚松动",
            fired=t5 > 2.5)
    else:
        row("通胀预期失锚", "拉不到", "2.5%", "—", "FRED未返回T5YIFR")

    # 曲线倒挂
    curve = t.get("curve_10y3m")
    if curve is not None:
        row("曲线倒挂(中期)", f"10Y-3M {curve:+.2f}%", "倒挂后转正",
            f"{'已倒挂' if curve<0 else f'+{curve:.2f}pp'}",
            "倒挂后转正+2Y单月跌>50bp=衰退临近", fired=False)
    else:
        row("曲线倒挂(中期)", "拉不到", "倒挂后转正", "—", "yf未返回^TNX/^IRX")

    # Sahm
    sahm = t.get("SAHM")
    if sahm is not None:
        row("衰退确认(Sahm)", f"{sahm:.2f}", "0.50",
            f"{sahm-0.5:+.2f}", "≥0.50=衰退(历史100%准)",
            fired=sahm >= 0.5)
    else:
        row("衰退确认(Sahm)", "拉不到", "0.50", "—", "FRED未返回SAHMREALTIME")

    # 尾部去杠杆 USDJPY (需3日变, 这里只给水平+提示)
    jpy = t.get("JPY")
    if jpy is not None:
        row("尾部去杠杆(JPY)", f"USDJPY {jpy:.1f}", "3日内日元升>3-4%",
            "需3日变, 见history", "carry unwind→全球去杠杆", fired=False)
    else:
        row("尾部去杠杆(JPY)", "拉不到", "3日内升>3-4%", "—", "yf未返回JPY=X")

    return rows


# ══════════════════════════════════════════════════════
# Regime 合成
# ══════════════════════════════════════════════════════
def get_regime(refresh: bool = False) -> dict:
    t = collect(refresh=refresh)
    domains = score_domains(t)
    rev = reverse_buy_gate(t)
    triggers = hard_trigger_distances(t)

    votes = [d["vote"] for d in domains if d["vote"] != "na"]
    n_off = votes.count("off")
    n_on = votes.count("on")
    n_neu = votes.count("neutral")
    n_valid = len(votes)

    # 方向 = 多数票(校准: 真触发域才驱动防御, 估值类不在这5域)
    if n_off > n_on:
        direction = "RISK-OFF"
    elif n_on > n_off:
        direction = "RISK-ON"
    else:
        direction = "NEUTRAL"

    # 程度 = 触发(off)域数
    fired_triggers = [r for r in triggers if r.get("fired")]
    n_fired = len(fired_triggers)
    if n_off == 0:
        degree = "平静"
    elif n_off <= 2:
        degree = "警觉"
    elif n_off <= 3:
        degree = "收紧"
    else:
        degree = "系统性"

    # ⛔校准: 真触发驱动防御。任两个硬触发同现=减仓建议
    defensive = n_fired >= 2
    if defensive:
        direction = "RISK-OFF"
        degree = "系统性(硬触发≥2)"

    # 置信度: valid域多+票一致=高
    if n_valid >= 4 and max(n_on, n_off) >= n_valid - 1:
        confidence = "高"
    elif n_valid >= 3:
        confidence = "中"
    else:
        confidence = "低(数据缺失多)"

    # ⛔修复(对抗审查Q3): 有stale域时置信封顶"中"——陈数据不能给"高"。
    stale_doms = [k for k, v in t.get("stale", {}).items() if v]
    if stale_doms and confidence == "高":
        confidence = "中(含陈数据)"

    missing = [d["name"] for d in domains if d["vote"] == "na"]

    return {
        "date": date.today().isoformat(),
        "direction": direction,
        "degree": degree,
        "confidence": confidence,
        "votes": {"on": n_on, "neutral": n_neu, "off": n_off, "valid": n_valid},
        "domains": domains,
        "reverse_buy_gate": rev,
        "hard_triggers": triggers,
        "fired_triggers": [r["name"] for r in fired_triggers],
        "defensive_recommendation": defensive,
        "missing_domains": missing,
        "stale_domains": stale_doms,
        "fred_dates": t.get("fred_dates", {}),
        "sofr_iorb_misaligned": t.get("sofr_iorb_misaligned", False),
        "_raw": t,
    }


# ══════════════════════════════════════════════════════
# 一屏 Dashboard
# ══════════════════════════════════════════════════════
VOTE_TAG = {"on": "绿", "neutral": "黄", "off": "红", "na": "—"}


def _pad(label: str, width: int) -> str:
    w = sum(2 if ord(c) > 127 else 1 for c in label)
    return label + " " * max(width - w, 1)


def print_dashboard(reg: dict) -> None:
    d = reg
    print()
    print(f"═══ MACRO REGIME  {d['date']} ═══")
    v = d["votes"]
    green = f"{v['on']}绿/{v['neutral']}黄/{v['off']}红 (共{v['valid']}域)"
    rev = d["reverse_buy_gate"]
    rev_txt = "⚡触发(VIX>50)" if rev["triggered"] else "未触发"
    print(f"方向: {d['direction']}   程度: {d['degree']}   "
          f"置信: {d['confidence']}   反向买点闸: {rev_txt}")
    print(f"投票: {green}")
    # ⛔staleness 横幅(对抗审查Q3): 陈数据不静默当今天
    stale = d.get("stale_domains", [])
    if stale:
        fd = d.get("fred_dates", {})
        parts = [f"{s}@{fd.get(s, '?')}" for s in stale]
        print(f"⚠ 数据陈旧(非今天, 已封顶置信): {' '.join(parts)}")
    if d.get("sofr_iorb_misaligned"):
        print("⚠ SOFR/IORB 日期不对齐, 融资管道触发未算(不跨日期估算)")
    print("─" * 78)

    print("【5域投票】")
    for dom in d["domains"]:
        tag = VOTE_TAG[dom["vote"]]
        print(f"  {_pad(dom['name'],10)}[{tag}] {_pad(dom['reading'],36)} {dom['note']}")

    print("─" * 78)
    print("【硬触发距离(百年校准真触发)】")
    for r in d["hard_triggers"]:
        mark = "🔴FIRED" if r["fired"] else "  "
        print(f"  {mark} {_pad(r['name'],16)} 当前 {_pad(r['current'],22)} "
              f"阈值 {_pad(r['threshold'],14)} 距 {r['distance']}")
        print(f"       └ {r['note']}")

    if d["fired_triggers"]:
        print(f"\n  ⚠ 已触发硬触发({len(d['fired_triggers'])}): {', '.join(d['fired_triggers'])}")

    print("─" * 78)
    print("【对 semi-heavy 杠杆组合(SOXL/AVGX/半导体重仓)的含义】")
    print("  " + portfolio_implication(d))

    if d["missing_domains"] or d["_raw"].get("missing"):
        print("─" * 78)
        miss = d["missing_domains"]
        print(f"⚠ 数据缺失(诚实标注, 未编数字): "
              f"{', '.join(miss) if miss else '无域级缺失'}")
        # 列出具体拉不到的 tracker
        raw = d["_raw"]
        na_list = []
        for k in ["HY_OAS", "DFII10", "SOFR", "T5YIFR", "SAHM", "VIX", "vix_term",
                  "copper_gold_5d_chg_pct", "curve_10y3m", "dfii10_1m_bp"]:
            if raw.get(k) is None:
                na_list.append(k)
        if na_list:
            print(f"  拉不到的tracker: {', '.join(na_list)}")
    print()


def portfolio_implication(d: dict) -> str:
    """对 semi-heavy 杠杆组合的判断(校准: 真触发才喊防御)。"""
    if d["defensive_recommendation"]:
        return ("≥2个硬触发同现 → 减杠杆。这是百年校准认可的真防御信号, "
                "不是估值恐慌。建议降 SOXL/半导体杠杆敞口。")
    raw = d["_raw"]
    notes = []
    # 信用绿灯
    hy = raw.get("HY_OAS")
    if hy is not None and hy * 100 < 400:
        notes.append("信用绿灯(HY OAS低)")
    # 曲线
    curve = raw.get("curve_10y3m")
    if curve is not None and curve > 0:
        notes.append("曲线正(无衰退临近信号)")
    # 实际利率
    dfii = raw.get("DFII10")
    d1m = raw.get("dfii10_1m_bp")
    if dfii is not None:
        if dfii > 2.0 and (d1m is None or d1m <= 50):
            notes.append(f"实际利率{dfii:.2f}%已在警戒水位但月升未加速(盯月升速,非水平)")
        elif dfii <= 2.0:
            notes.append(f"实际利率{dfii:.2f}%未破警戒")

    if d["direction"] == "RISK-OFF":
        base = ("方向偏 risk-off 但未达硬触发减仓门槛。提高警觉, 不机械减仓 — "
                "校准: 单域走弱是警觉信号不是扳机。盯是否升级为≥2硬触发。")
    else:
        base = ("信用/曲线给 risk-on 绿灯, growth/SOXL 无估值杀压力, 维持攻击仓位。"
                "对吓人估值(CAPE/集中度)默认降权 — 贵≠脆弱。")
    if notes:
        base += " [" + "; ".join(notes) + "]"
    return base


def main() -> int:
    refresh = "--refresh" in sys.argv
    as_json = "--json" in sys.argv
    reg = get_regime(refresh=refresh)
    if as_json:
        out = {k: v for k, v in reg.items() if k != "_raw"}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print_dashboard(reg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
