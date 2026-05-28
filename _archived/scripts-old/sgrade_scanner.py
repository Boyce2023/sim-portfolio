# /// script
# requires-python = ">=3.9"
# dependencies = ["yfinance>=0.2.40", "rich>=13.0", "akshare>=1.12.0"]
# ///
"""
S级候选扫描器 — 全仓短线机会初筛 v2.0

S级标准: 供应链瓶颈+催化剂在30天内+小票已先飞+量价突破+浅跌幅bear case
得分 ≥3 → 潜在S级候选
得分 ≥4 → 强S级候选

扫描器清单:
  S-GRADE: 原始五项评分（供应链/催化剂/小票先飞/技术/bear case）
  N1: 北向资金异常    — 净流入>2σ（20日基准）
  N2: 量价突破        — Nokia Pattern: ATR压缩+放量+突破20日高点
  N3: 机构调研密集    — 占位符（需web-access skill获取互动易数据）
  N4: 跨行业超额收益  — 个股超跑本板块>5%（5日）

用法:
  uv run --script scripts/sgrade_scanner.py                              # 扫描watchlist（全部扫描器）
  uv run --script scripts/sgrade_scanner.py --tickers 002938,002475     # 指定标的
  uv run --script scripts/sgrade_scanner.py --json                      # JSON输出
  uv run --script scripts/sgrade_scanner.py --scanner N1                # 只跑北向资金扫描器
  uv run --script scripts/sgrade_scanner.py --scanner N2                # 只跑量价突破扫描器
  uv run --script scripts/sgrade_scanner.py --scanner N4                # 只跑超额收益扫描器
  uv run --script scripts/sgrade_scanner.py --min-score 3               # 只显示得分≥3
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────
# S级行业关键词（供应链瓶颈赛道）
# ─────────────────────────────────────────────
SGRADE_SECTORS = {
    "AI",
    "AI服务器", "AI芯片", "AI卖铲",
    "苹果链", "NVDA供应链",
    "新能源车", "智能驾驶", "FSD",
    "半导体", "半导体材料", "先进封装", "半导体封装", "PCB",
    "军工",
    "机器人", "传感器",
    "储能", "光伏",
}

# A股板块ETF — 用于N4跨行业超额收益扫描
# 格式: {板块名: ETF代码(yfinance格式)}
SECTOR_ETFS: dict[str, str] = {
    "半导体":   "512480.SS",   # 半导体ETF
    "AI":       "515070.SS",   # 人工智能ETF
    "新能源车": "515030.SS",   # 新能源车ETF
    "军工":     "512660.SS",   # 军工ETF
    "光伏":     "515790.SS",   # 光伏ETF
    "消费":     "512010.SS",   # 白酒ETF (消费代理)
    "医药":     "512010.SS",   # 医疗ETF
    "金融":     "510230.SS",   # 金融ETF
    "储能":     "561020.SS",   # 储能ETF
    "机器人":   "562500.SS",   # 机器人ETF
}

# 默认A股扫描宇宙（如果watchlist为空时的后备）
DEFAULT_CN_UNIVERSE: list[str] = [
    "002938", "002475", "002273", "300896", "002415",
    "601138", "002304", "300059", "002049", "300750",
]


# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def _cn_yf(ticker: str) -> str:
    """将纯数字A股代码转换为yfinance格式"""
    t = ticker.strip()
    if t.startswith("6"):   # 沪市含科创板
        return f"{t}.SS"
    return f"{t}.SZ"        # 深市


def load_watchlist_tickers(watchlist_path: Path) -> list[dict]:
    """从watchlist_config.json读取A股标的"""
    try:
        with open(watchlist_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"[WARN] 无法读取watchlist: {e}", file=sys.stderr)
        return []
    return [item for item in cfg.get("cn_watchlist", []) if item.get("market") == "cn"]


def days_until(date_str: Optional[str]) -> int:
    if not date_str or date_str in ("事件驱动", "待研究"):
        return 999
    try:
        d = date.fromisoformat(date_str[:10])
        return max(0, (d - date.today()).days)
    except Exception:
        return 999


def _fetch_hist(yf_ticker: str, period: str = "3mo"):
    """获取历史行情，失败返回None"""
    try:
        import yfinance as yf
        data = yf.Ticker(yf_ticker)
        hist = data.history(period=period)
        return hist if not hist.empty else None
    except Exception:
        return None


def _calc_atr(high: list[float], low: list[float], close: list[float], window: int = 14) -> list[float]:
    """计算ATR序列"""
    if len(close) < 2:
        return []
    trs = []
    for i in range(1, len(close)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        trs.append(tr)
    # Wilder平滑
    if len(trs) < window:
        return trs
    atrs = []
    atrs.append(sum(trs[:window]) / window)
    for tr in trs[window:]:
        atrs.append((atrs[-1] * (window - 1) + tr) / window)
    return atrs


# ─────────────────────────────────────────────
# ── 原始五项评分（S-GRADE核心）──
# ─────────────────────────────────────────────

def score_supply_chain(sector: str) -> tuple[int, str]:
    """S1: 供应链瓶颈赛道（0/1）"""
    sector_upper = sector.upper()
    for kw in SGRADE_SECTORS:
        if kw.upper() in sector_upper:
            return 1, f"赛道匹配: {sector}"
    keywords = ["AI", "PCB", "半导体", "苹果", "新能源", "机器人", "军工", "储能", "封装", "芯片"]
    for kw in keywords:
        if kw in sector:
            return 1, f"关键词匹配: {kw}"
    return 0, f"赛道未匹配 ({sector})"


def score_catalyst(watchlist_item: Optional[dict]) -> tuple[int, str]:
    """S2: 30天内催化剂（0/1）"""
    if watchlist_item is None:
        return 0, "无watchlist信息"
    cat = watchlist_item.get("next_catalyst", {})
    cat_date = watchlist_item.get("next_catalyst_date", "")
    if isinstance(cat, dict):
        cat_date = cat.get("date", "") or cat_date
    d = days_until(cat_date)
    if d <= 30:
        event = cat.get("event", cat_date) if isinstance(cat, dict) else str(cat)
        return 1, f"催化剂: {event} ({d}天)"
    return 0, f"最近催化剂 {d}天后"


def score_small_cap_lead(hist_5d: list[float], sector_small_caps_5d: Optional[float] = None) -> tuple[int, str]:
    """
    S3: 小票先飞信号（0/1）
    逻辑: 板块小票已涨>5%(5日)但本股涨幅明显低于小票（落后>=3%）
    如无小票对比数据，则用本股5日涨幅<2%作为"尚未跟涨"的代理
    """
    if len(hist_5d) < 2:
        return 0, "数据不足"

    stock_5d_ret = (hist_5d[-1] / hist_5d[0] - 1) * 100

    if sector_small_caps_5d is not None:
        if sector_small_caps_5d > 5 and (sector_small_caps_5d - stock_5d_ret) >= 3:
            return 1, f"小票已涨{sector_small_caps_5d:+.1f}%，本股仅{stock_5d_ret:+.1f}%"
        return 0, f"未满足: 小票{sector_small_caps_5d:+.1f}% vs 本股{stock_5d_ret:+.1f}%"
    else:
        if stock_5d_ret < 2:
            return 1, f"本股5日涨幅{stock_5d_ret:+.1f}%（未跟涨，补涨空间存在）"
        return 0, f"本股5日已涨{stock_5d_ret:+.1f}%（先于信号）"


def score_technical(close: list[float], volume: list[float]) -> tuple[int, str]:
    """
    S4: 技术确认（0/1）
    条件: 最新成交量 > 20日均量×2 AND 最新收盘 > 20日均线
    """
    if len(close) < 5 or len(volume) < 5:
        return 0, "历史数据不足(<5天)"

    window = min(20, len(close))
    ma20 = sum(close[-window:]) / window
    vol_ma = sum(volume[-window:]) / window

    latest_close = close[-1]
    latest_vol   = volume[-1]

    vol_ratio = latest_vol / vol_ma if vol_ma > 0 else 0
    above_ma  = latest_close > ma20
    vol_break = vol_ratio >= 2.0

    if above_ma and vol_break:
        return 1, f"量价突破: 收盘¥{latest_close:.2f}>MA{window}¥{ma20:.2f}, 量比{vol_ratio:.1f}x"
    reasons = []
    if not above_ma:
        reasons.append(f"收盘¥{latest_close:.2f}<MA{window}¥{ma20:.2f}")
    if not vol_break:
        reasons.append(f"量比{vol_ratio:.1f}x<2x")
    return 0, "; ".join(reasons)


def score_bear_case(close: list[float], watchlist_item: Optional[dict] = None) -> tuple[int, str]:
    """
    S5: 浅跌幅bear case（0/1）
    方法: 从当前价到20日低点的跌幅 <10% → bear case浅
    如watchlist有bear_case_downside_pct，优先使用
    """
    if watchlist_item:
        bc = watchlist_item.get("bear_case_downside_pct")
        if bc is not None:
            bc_abs = abs(bc)
            if bc_abs < 15:
                return 1, f"Bear case {bc}%（watchlist，浅）"
            return 0, f"Bear case {bc}%（watchlist，超15%）"

    if len(close) < 5:
        return 0, "数据不足"
    window = min(20, len(close))
    low_20d = min(close[-window:])
    current = close[-1]
    downside = (low_20d / current - 1) * 100
    if downside > -10:
        return 1, f"20日低点支撑{downside:.1f}%（浅）"
    return 0, f"20日低点支撑{downside:.1f}%（>10%）"


# ─────────────────────────────────────────────
# 单股S-GRADE扫描
# ─────────────────────────────────────────────

def scan_ticker(
    ticker: str,
    watchlist_item: Optional[dict],
    sector: str,
) -> Optional[dict]:
    """获取价格数据，计算五项得分，返回结果字典"""
    try:
        import yfinance as yf
    except ImportError:
        print("[ERROR] yfinance未安装，请用 uv run --script 运行", file=sys.stderr)
        sys.exit(1)

    yf_ticker = _cn_yf(ticker)

    try:
        data = yf.Ticker(yf_ticker)
        hist_1mo = data.history(period="1mo")
        hist_5d  = data.history(period="5d")
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "score": 0}

    if hist_1mo.empty or hist_5d.empty:
        return {"ticker": ticker, "error": "无行情数据", "score": 0}

    close_1mo  = hist_1mo["Close"].tolist()
    volume_1mo = hist_1mo["Volume"].tolist()
    close_5d   = hist_5d["Close"].tolist()

    current_price = close_1mo[-1]
    open_5d  = close_5d[0] if close_5d else current_price
    ret_5d   = (current_price / open_5d - 1) * 100 if open_5d else 0

    open_20d = close_1mo[0] if close_1mo else current_price
    ret_20d  = (current_price / open_20d - 1) * 100 if open_20d else 0

    window   = min(20, len(volume_1mo))
    vol_ma   = sum(volume_1mo[-window:]) / window if window > 0 else 1
    vol_ratio = volume_1mo[-1] / vol_ma if vol_ma > 0 else 0

    s1, d1 = score_supply_chain(sector)
    s2, d2 = score_catalyst(watchlist_item)
    s3, d3 = score_small_cap_lead(close_5d)
    s4, d4 = score_technical(close_1mo, volume_1mo)
    s5, d5 = score_bear_case(close_1mo, watchlist_item)

    total = s1 + s2 + s3 + s4 + s5
    label = "强S级" if total >= 4 else ("潜在S级" if total >= 3 else "观察")

    name = watchlist_item.get("name", ticker) if watchlist_item else ticker

    return {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "score": total,
        "label": label,
        "price": round(current_price, 2),
        "ret_5d_pct": round(ret_5d, 2),
        "ret_20d_pct": round(ret_20d, 2),
        "vol_ratio": round(vol_ratio, 2),
        "scores": {
            "S1_supply_chain":   {"score": s1, "detail": d1},
            "S2_catalyst_30d":   {"score": s2, "detail": d2},
            "S3_small_cap_lead": {"score": s3, "detail": d3},
            "S4_tech_breakout":  {"score": s4, "detail": d4},
            "S5_shallow_bear":   {"score": s5, "detail": d5},
        },
        "scanned_at": datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────
# ── N1: 北向资金异常扫描器 ──
# ─────────────────────────────────────────────

def scan_n1_northbound(tickers: list[str], watchlist_map: dict) -> list[dict]:
    """
    N1: 北向资金异常（Northbound Flow Anomaly）

    方法:
      1. 尝试通过 akshare 获取沪深港通北向资金历史净流入
      2. 计算20日均值和标准差
      3. 标记最新净流入 > μ + 2σ 的标的

    数据依赖: akshare stock_hsgt_individual_em()（东方财富个股北向资金）
    如akshare不可用或数据获取失败，回退到市场级北向数据判断
    """
    results = []
    print("[N1] 北向资金异常扫描...", file=sys.stderr)

    # 尝试导入akshare
    try:
        import akshare as ak
        has_akshare = True
    except ImportError:
        has_akshare = False
        print("[N1] akshare未安装，跳过个股北向数据（安装: pip install akshare）", file=sys.stderr)

    for ticker in tickers:
        wl_item = watchlist_map.get(ticker, {})
        name = wl_item.get("name", ticker)
        result_base = {
            "ticker": ticker,
            "name": name,
            "signal_type": "N1_northbound",
            "score": 0,
            "detail": "",
        }

        if not has_akshare:
            result_base["detail"] = "akshare未安装，无法获取北向数据"
            results.append(result_base)
            continue

        try:
            # 获取个股北向持股数据（东方财富）
            # akshare接口: stock_hsgt_hold_stock_em(stock=ticker, indicator="北向资金")
            # 返回: 日期/持股数量/持股比例/持股变动/持股变动比例
            df = ak.stock_hsgt_hold_stock_em(stock=ticker, indicator="北向资金")
            if df is None or df.empty or len(df) < 5:
                result_base["detail"] = "北向持股数据不足(<5天)"
                results.append(result_base)
                continue

            # 取持股变动列（代理净流入方向）
            # 列名可能因akshare版本不同而异，尝试常见列名
            change_col = None
            for col in ["持股变动", "持仓变动", "变动数量", "净买入"]:
                if col in df.columns:
                    change_col = col
                    break

            if change_col is None:
                # 降级: 用持股比例变化
                for col in ["持股比例", "占流通股比例"]:
                    if col in df.columns:
                        change_col = col
                        break

            if change_col is None:
                result_base["detail"] = f"未找到变动列，可用列: {list(df.columns)[:4]}"
                results.append(result_base)
                continue

            # 确保数值
            df[change_col] = df[change_col].astype(str).str.replace(",", "").str.replace("%", "")
            vals = []
            for v in df[change_col]:
                try:
                    vals.append(float(v))
                except Exception:
                    pass

            if len(vals) < 5:
                result_base["detail"] = "有效数值不足"
                results.append(result_base)
                continue

            # 取最近20天
            recent = vals[:min(20, len(vals))]
            latest = recent[0]  # akshare通常最新在前
            window_vals = recent[1:]  # 去除最新，计算历史均值/标准差

            if len(window_vals) < 4:
                result_base["detail"] = "历史窗口不足"
                results.append(result_base)
                continue

            mean_val = sum(window_vals) / len(window_vals)
            variance = sum((v - mean_val) ** 2 for v in window_vals) / len(window_vals)
            std_val = variance ** 0.5

            if std_val == 0:
                result_base["detail"] = "北向持股变动无波动（std=0）"
                results.append(result_base)
                continue

            z_score = (latest - mean_val) / std_val

            if z_score > 2.0:
                result_base["score"] = 1
                result_base["detail"] = (
                    f"北向异常买入: 最新{latest:+.0f} | μ={mean_val:.0f} | "
                    f"z={z_score:.2f}σ (>{2.0}σ阈值)"
                )
            elif z_score > 1.0:
                result_base["score"] = 0
                result_base["detail"] = f"北向偏强但未超2σ: z={z_score:.2f}σ"
            else:
                result_base["detail"] = f"北向无异常: z={z_score:.2f}σ"

            result_base["z_score"] = round(z_score, 2)
            result_base["latest_flow"] = latest
            result_base["flow_mean_20d"] = round(mean_val, 2)

        except Exception as e:
            result_base["detail"] = f"获取北向数据失败: {type(e).__name__}: {e}"

        results.append(result_base)

    triggered = [r for r in results if r["score"] > 0]
    print(f"[N1] 完成 | 标的: {len(tickers)} | 触发: {len(triggered)}", file=sys.stderr)
    return results


# ─────────────────────────────────────────────
# ── N2: 量价突破扫描器（Nokia Pattern A股版）──
# ─────────────────────────────────────────────

def scan_n2_volume_price_breakout(tickers: list[str], watchlist_map: dict) -> list[dict]:
    """
    N2: 量价突破（Volume-Price Breakout）— Nokia Pattern A股版

    三重条件（均需满足）:
      1. ATR压缩: 当前ATR(14) < 0.7 × ATR(60日) → 价格进入横盘压缩
      2. 放量突破: 今日成交量 > 20日均量 × 2
      3. 价格突破: 今日收盘 > 过去20日最高收盘价

    数据: yfinance，3个月历史（含60日ATR计算需求）
    """
    results = []
    print("[N2] 量价突破扫描（Nokia Pattern）...", file=sys.stderr)

    try:
        import yfinance as yf
    except ImportError:
        print("[N2][ERROR] yfinance未安装", file=sys.stderr)
        return []

    for ticker in tickers:
        wl_item = watchlist_map.get(ticker, {})
        name = wl_item.get("name", ticker)
        yf_ticker = _cn_yf(ticker)

        result_base = {
            "ticker": ticker,
            "name": name,
            "signal_type": "N2_volume_price_breakout",
            "score": 0,
            "detail": "",
        }

        try:
            data = yf.Ticker(yf_ticker)
            hist = data.history(period="3mo")

            if hist is None or hist.empty or len(hist) < 21:
                result_base["detail"] = f"历史数据不足({len(hist) if hist is not None else 0}天，需≥21)"
                results.append(result_base)
                continue

            close  = hist["Close"].tolist()
            high   = hist["High"].tolist()
            low    = hist["Low"].tolist()
            volume = hist["Volume"].tolist()

            # ─ 条件1: ATR压缩 ─
            atrs = _calc_atr(high, low, close, window=14)
            if len(atrs) < 15:
                result_base["detail"] = "ATR数据不足"
                results.append(result_base)
                continue

            atr_current = atrs[-1]  # 最新ATR(14)
            # ATR(60): 用过去60日的平均（近似，如果数据够的话）
            # 否则用全部可用数据
            atr_window_60 = min(60, len(atrs))
            atr_60d_mean = sum(atrs[-atr_window_60:]) / atr_window_60
            atr_compressed = atr_current < 0.7 * atr_60d_mean

            # ─ 条件2: 放量 ─
            vol_window = min(20, len(volume) - 1)
            vol_ma20 = sum(volume[-vol_window - 1:-1]) / vol_window if vol_window > 0 else volume[-1]
            vol_ratio = volume[-1] / vol_ma20 if vol_ma20 > 0 else 0
            vol_spike = vol_ratio >= 2.0

            # ─ 条件3: 价格突破20日高点 ─
            price_window = min(20, len(close) - 1)
            high_20d = max(close[-price_window - 1:-1]) if price_window > 0 else close[-1]
            price_breakout = close[-1] > high_20d

            # 汇总
            conditions_met = sum([atr_compressed, vol_spike, price_breakout])

            detail_parts = [
                f"ATR压缩{'✓' if atr_compressed else '✗'}({atr_current:.3f} vs 60d均{atr_60d_mean:.3f}×0.7={0.7*atr_60d_mean:.3f})",
                f"放量{'✓' if vol_spike else '✗'}({vol_ratio:.1f}x vs 阈值2.0x)",
                f"突破{'✓' if price_breakout else '✗'}(收¥{close[-1]:.2f} vs 20d高¥{high_20d:.2f})",
            ]

            if conditions_met == 3:
                result_base["score"] = 1
                result_base["label"] = "Nokia突破"
            elif conditions_met == 2:
                result_base["score"] = 0
                result_base["label"] = "接近突破(2/3)"
            else:
                result_base["label"] = f"未突破({conditions_met}/3)"

            result_base["detail"] = " | ".join(detail_parts)
            result_base["atr_current"] = round(atr_current, 4)
            result_base["atr_60d_mean"] = round(atr_60d_mean, 4)
            result_base["vol_ratio"] = round(vol_ratio, 2)
            result_base["price"] = round(close[-1], 2)
            result_base["high_20d"] = round(high_20d, 2)
            result_base["conditions_met"] = conditions_met

        except Exception as e:
            result_base["detail"] = f"数据获取失败: {type(e).__name__}: {e}"

        results.append(result_base)

    triggered = [r for r in results if r["score"] > 0]
    print(f"[N2] 完成 | 标的: {len(tickers)} | 触发: {len(triggered)}", file=sys.stderr)
    return results


# ─────────────────────────────────────────────
# ── N3: 机构调研密集扫描器（占位符）──
# ─────────────────────────────────────────────

def scan_n3_institutional_visits(tickers: list[str], watchlist_map: dict) -> list[dict]:
    """
    N3: 机构调研密集（Institutional Research Visits）

    数据来源: 互动易 (irm.cninfo.com.cn) / 巨潮资讯
    接口: 需要web-access skill进行动态页面抓取

    当前状态: 占位符。接口定义已完成，等待web-access skill填充实现。

    预期输出格式（每个结果字典）:
      {
        "ticker": str,
        "name": str,
        "signal_type": "N3_institutional_visits",
        "score": 0 or 1,
        "detail": str,
        "visit_count_7d": int,       # 最近7天机构调研次数
        "visit_count_30d": int,      # 最近30天机构调研次数
        "institutions": list[str],   # 调研机构名称列表
        "latest_visit_date": str,    # 最新调研日期 YYYY-MM-DD
      }

    触发条件（待实现）:
      - 最近7天机构调研次数 ≥ 3次，且
      - 调研机构包含主流公募基金（易方达/华夏/富国/南方/嘉实等）

    实现路径:
      1. 使用 web-access skill 访问互动易
      2. 搜索标的代码，获取"机构调研"记录
      3. 解析最近30天记录，统计次数和机构名称
    """
    results = []
    print("[N3] 机构调研密集扫描（占位符模式）...", file=sys.stderr)
    print(
        "[N3] ⚠ 注意: N3需要web-access skill获取互动易/巨潮数据，当前返回占位结果",
        file=sys.stderr,
    )

    for ticker in tickers:
        wl_item = watchlist_map.get(ticker, {})
        name = wl_item.get("name", ticker)
        results.append({
            "ticker": ticker,
            "name": name,
            "signal_type": "N3_institutional_visits",
            "score": 0,
            "detail": "N3: 需要web-access skill获取互动易数据 | 接口已定义，等待实现",
            "visit_count_7d": None,
            "visit_count_30d": None,
            "institutions": [],
            "latest_visit_date": None,
        })

    print(f"[N3] 完成（占位符）| 标的: {len(tickers)}", file=sys.stderr)
    return results


# ─────────────────────────────────────────────
# ── N4: 跨行业超额收益扫描器 ──
# ─────────────────────────────────────────────

def scan_n4_cross_sector_rs(tickers: list[str], watchlist_map: dict) -> list[dict]:
    """
    N4: 跨行业超额收益（Cross-Sector Relative Strength）

    方法:
      1. 获取每只标的过去5日收益率
      2. 获取其所属板块ETF的5日收益率作为板块基准
      3. 标记超跑板块 >5% 的个股 → 说明存在个股催化剂，非板块轮动

    板块映射: 从watchlist的sector字段匹配SECTOR_ETFS
    如果板块无对应ETF，使用中证1000(000852.SH)作为市场基准
    """
    results = []
    print("[N4] 跨行业超额收益扫描...", file=sys.stderr)

    try:
        import yfinance as yf
    except ImportError:
        print("[N4][ERROR] yfinance未安装", file=sys.stderr)
        return []

    # 预获取板块ETF数据（批量，减少API调用次数）
    sector_returns: dict[str, Optional[float]] = {}
    etf_period = "5d"

    print("[N4] 获取板块ETF基准数据...", file=sys.stderr)

    # 获取所有需要的ETF（根据watchlist中的sector字段）
    needed_sectors: set[str] = set()
    for ticker in tickers:
        wl = watchlist_map.get(ticker, {})
        sector = wl.get("sector", "未知")
        needed_sectors.add(sector)

    # 为每个板块匹配ETF
    sector_etf_map: dict[str, str] = {}
    for sector in needed_sectors:
        matched_etf = None
        for kw, etf in SECTOR_ETFS.items():
            if kw in sector:
                matched_etf = etf
                break
        if matched_etf is None:
            # 回退到中证1000
            matched_etf = "000852.SS"
        sector_etf_map[sector] = matched_etf

    # 获取ETF历史
    unique_etfs = set(sector_etf_map.values())
    for etf_code in unique_etfs:
        try:
            etf_hist = yf.Ticker(etf_code).history(period=etf_period)
            if etf_hist is not None and not etf_hist.empty and len(etf_hist) >= 2:
                etf_close = etf_hist["Close"].tolist()
                etf_ret = (etf_close[-1] / etf_close[0] - 1) * 100
                sector_returns[etf_code] = round(etf_ret, 2)
            else:
                sector_returns[etf_code] = None
        except Exception as e:
            sector_returns[etf_code] = None
            print(f"[N4] ETF {etf_code} 获取失败: {e}", file=sys.stderr)

    # 扫描每只个股
    for ticker in tickers:
        wl_item = watchlist_map.get(ticker, {})
        name = wl_item.get("name", ticker)
        sector = wl_item.get("sector", "未知")
        yf_ticker = _cn_yf(ticker)

        result_base = {
            "ticker": ticker,
            "name": name,
            "signal_type": "N4_cross_sector_rs",
            "score": 0,
            "detail": "",
            "sector": sector,
        }

        # 获取个股5日收益
        try:
            hist = yf.Ticker(yf_ticker).history(period="5d")
            if hist is None or hist.empty or len(hist) < 2:
                result_base["detail"] = "个股数据不足"
                results.append(result_base)
                continue

            stock_close = hist["Close"].tolist()
            stock_ret = (stock_close[-1] / stock_close[0] - 1) * 100

        except Exception as e:
            result_base["detail"] = f"个股数据获取失败: {e}"
            results.append(result_base)
            continue

        # 获取板块基准收益
        etf_code = sector_etf_map.get(sector, "000852.SS")
        sector_ret = sector_returns.get(etf_code)

        if sector_ret is None:
            result_base["detail"] = f"板块ETF({etf_code})数据不可用，无法计算超额"
            result_base["stock_ret_5d"] = round(stock_ret, 2)
            results.append(result_base)
            continue

        # 计算超额收益
        excess_ret = stock_ret - sector_ret
        result_base["stock_ret_5d"] = round(stock_ret, 2)
        result_base["sector_ret_5d"] = round(sector_ret, 2)
        result_base["excess_ret_5d"] = round(excess_ret, 2)
        result_base["sector_etf"] = etf_code

        if excess_ret > 5.0:
            result_base["score"] = 1
            result_base["detail"] = (
                f"超额+{excess_ret:.1f}%: 个股{stock_ret:+.1f}% vs 板块{sector_ret:+.1f}% "
                f"[{sector}|{etf_code}] → 个股催化剂信号"
            )
        elif excess_ret > 2.0:
            result_base["detail"] = (
                f"超额+{excess_ret:.1f}%(未超5%阈值): 个股{stock_ret:+.1f}% vs 板块{sector_ret:+.1f}%"
            )
        else:
            result_base["detail"] = (
                f"无超额: 个股{stock_ret:+.1f}% vs 板块{sector_ret:+.1f}% | 超额{excess_ret:+.1f}%"
            )

        results.append(result_base)

    triggered = [r for r in results if r["score"] > 0]
    print(f"[N4] 完成 | 标的: {len(tickers)} | 触发: {len(triggered)}", file=sys.stderr)
    return results


# ─────────────────────────────────────────────
# 显示（原始S-GRADE表格）
# ─────────────────────────────────────────────

def print_table(results: list[dict]) -> None:
    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box
    except ImportError:
        print(f"\n{'='*80}")
        print(f"{'标的':<12}{'名称':<12}{'得分':>5}{'标签':<10}{'价格':>8}{'5日%':>8}{'20日%':>8}{'量比':>6}")
        print(f"{'-'*80}")
        for r in results:
            if "error" in r:
                print(f"{r['ticker']:<12}{'ERROR':<12}{0:>5}{r.get('error','')}")
                continue
            print(
                f"{r['ticker']:<12}{r['name']:<12}{r['score']:>5}"
                f"{r['label']:<10}{r['price']:>8.2f}"
                f"{r['ret_5d_pct']:>+8.1f}{r['ret_20d_pct']:>+8.1f}{r['vol_ratio']:>6.1f}x"
            )
        return

    console = Console()
    table = Table(title="S级候选扫描结果", box=box.ROUNDED, show_header=True)
    table.add_column("标的", style="cyan")
    table.add_column("名称")
    table.add_column("得分", justify="center")
    table.add_column("标签", justify="center")
    table.add_column("价格", justify="right")
    table.add_column("5日%", justify="right")
    table.add_column("20日%", justify="right")
    table.add_column("量比", justify="right")
    table.add_column("S1", justify="center")
    table.add_column("S2", justify="center")
    table.add_column("S3", justify="center")
    table.add_column("S4", justify="center")
    table.add_column("S5", justify="center")

    for r in results:
        if "error" in r:
            table.add_row(r["ticker"], "ERROR", "—", r.get("error",""), *["—"]*9)
            continue

        sc = r["scores"]
        score_color = "green" if r["score"] >= 4 else ("yellow" if r["score"] >= 3 else "dim")
        label_color = "bold green" if r["score"] >= 4 else ("bold yellow" if r["score"] >= 3 else "dim")

        def cell(s, d):
            return "[green]✓[/green]" if s else "[dim]✗[/dim]"

        table.add_row(
            r["ticker"],
            r["name"],
            f"[{score_color}]{r['score']}/5[/{score_color}]",
            f"[{label_color}]{r['label']}[/{label_color}]",
            f"¥{r['price']:.2f}",
            f"[{'green' if r['ret_5d_pct'] > 0 else 'red'}]{r['ret_5d_pct']:+.1f}%[/{'green' if r['ret_5d_pct'] > 0 else 'red'}]",
            f"[{'green' if r['ret_20d_pct'] > 0 else 'red'}]{r['ret_20d_pct']:+.1f}%[/{'green' if r['ret_20d_pct'] > 0 else 'red'}]",
            f"{r['vol_ratio']:.1f}x",
            cell(sc["S1_supply_chain"]["score"], ""),
            cell(sc["S2_catalyst_30d"]["score"], ""),
            cell(sc["S3_small_cap_lead"]["score"], ""),
            cell(sc["S4_tech_breakout"]["score"], ""),
            cell(sc["S5_shallow_bear"]["score"], ""),
        )

    console.print(table)

    candidates = [r for r in results if r.get("score", 0) >= 3 and "error" not in r]
    if candidates:
        console.print("\n[bold]候选详情:[/bold]")
        for r in candidates:
            sc = r["scores"]
            console.print(f"  [cyan]{r['ticker']} {r['name']}[/cyan] [{r['score']}/5]")
            for key, val in sc.items():
                icon = "✓" if val["score"] else "✗"
                style = "green" if val["score"] else "dim"
                console.print(f"    [{style}]{icon} {key}: {val['detail']}[/{style}]")


def print_discovery_results(scanner_id: str, results: list[dict]) -> None:
    """格式化输出N1/N2/N3/N4扫描结果"""
    SCANNER_NAMES = {
        "N1": "北向资金异常",
        "N2": "量价突破(Nokia Pattern)",
        "N3": "机构调研密集(占位符)",
        "N4": "跨行业超额收益",
    }

    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box
        console = Console()
    except ImportError:
        console = None

    title = f"{scanner_id}: {SCANNER_NAMES.get(scanner_id, scanner_id)}"
    triggered = [r for r in results if r.get("score", 0) > 0]
    not_triggered = [r for r in results if r.get("score", 0) == 0]

    if console:
        table = Table(title=title, box=box.ROUNDED, show_header=True)
        table.add_column("标的", style="cyan", width=10)
        table.add_column("名称", width=12)
        table.add_column("信号", justify="center", width=6)
        table.add_column("详情", width=60)

        # 先显示触发的
        for r in triggered:
            table.add_row(
                r["ticker"],
                r.get("name", ""),
                "[bold green]触发[/bold green]",
                r.get("detail", ""),
            )
        # 再显示未触发的
        for r in not_triggered:
            table.add_row(
                r["ticker"],
                r.get("name", ""),
                "[dim]—[/dim]",
                f"[dim]{r.get('detail', '')}[/dim]",
            )

        console.print(table)
        console.print(
            f"[bold]{scanner_id} 摘要:[/bold] 触发 [green]{len(triggered)}[/green] / "
            f"总扫描 {len(results)}"
        )
    else:
        print(f"\n{'='*80}")
        print(f"{title}")
        print(f"{'-'*80}")
        for r in triggered:
            print(f"[触发] {r['ticker']} {r.get('name','')}: {r.get('detail','')}")
        for r in not_triggered:
            print(f"[  —] {r['ticker']} {r.get('name','')}: {r.get('detail','')}")
        print(f"\n{scanner_id} 摘要: 触发 {len(triggered)} / 总扫描 {len(results)}")


def print_combined_summary(all_scanner_results: dict[str, list[dict]]) -> None:
    """汇总所有扫描器结果，输出综合摘要"""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box
        console = Console()
    except ImportError:
        console = None

    # 按ticker聚合信号
    ticker_signals: dict[str, dict] = {}
    for scanner_id, results in all_scanner_results.items():
        for r in results:
            t = r["ticker"]
            if t not in ticker_signals:
                ticker_signals[t] = {
                    "ticker": t,
                    "name": r.get("name", t),
                    "signals": [],
                    "total_score": 0,
                }
            if r.get("score", 0) > 0:
                ticker_signals[t]["signals"].append(scanner_id)
                ticker_signals[t]["total_score"] += r.get("score", 0)

    # 过滤出有至少1个信号的
    multi_signal = [v for v in ticker_signals.values() if v["total_score"] > 0]
    multi_signal.sort(key=lambda x: -x["total_score"])

    if not multi_signal:
        if console:
            console.print("[dim]综合摘要: 本次扫描无多信号共振标的[/dim]")
        else:
            print("综合摘要: 本次扫描无多信号共振标的")
        return

    if console:
        table = Table(title="综合多信号共振", box=box.ROUNDED)
        table.add_column("标的", style="cyan")
        table.add_column("名称")
        table.add_column("触发信号", style="yellow")
        table.add_column("信号数", justify="center")

        for item in multi_signal:
            signals_str = " + ".join(item["signals"])
            score_color = "bold green" if item["total_score"] >= 2 else "yellow"
            table.add_row(
                item["ticker"],
                item["name"],
                signals_str,
                f"[{score_color}]{item['total_score']}[/{score_color}]",
            )

        console.print(table)
    else:
        print("\n综合多信号共振:")
        for item in multi_signal:
            print(f"  {item['ticker']} {item['name']}: {'+'.join(item['signals'])} ({item['total_score']}信号)")


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="S级候选扫描器 v2.0 — A股全仓短线机会初筛 + 4新信号扫描器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--tickers", "-t",
        help="逗号分隔的A股代码，如 002938,002475,002273（不传则扫描watchlist）",
    )
    parser.add_argument(
        "--watchlist", "-w",
        default=str(Path(__file__).resolve().parent.parent / "watchlist_config.json"),
        help="watchlist_config.json路径",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        dest="json_output",
        help="输出JSON（机器可读）",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=0,
        help="只显示得分 >= N 的标的（仅影响S-GRADE扫描，默认0=全显示）",
    )
    parser.add_argument(
        "--scanner",
        choices=["SGRADE", "N1", "N2", "N3", "N4", "ALL"],
        default="ALL",
        help=(
            "指定运行的扫描器: "
            "SGRADE=原始五项评分 | "
            "N1=北向资金异常 | "
            "N2=量价突破(Nokia) | "
            "N3=机构调研(占位符) | "
            "N4=跨行业超额收益 | "
            "ALL=全部运行（默认）"
        ),
    )
    args = parser.parse_args()

    watchlist_path = Path(args.watchlist).resolve()
    watchlist_items = load_watchlist_tickers(watchlist_path)
    watchlist_map = {item["ticker"]: item for item in watchlist_items}

    # 确定扫描列表
    if args.tickers:
        scan_list = [t.strip() for t in args.tickers.split(",") if t.strip()]
    else:
        scan_list = [item["ticker"] for item in watchlist_items]
        if not scan_list:
            print(
                "[WARN] watchlist为空且未指定--tickers，使用默认A股宇宙",
                file=sys.stderr,
            )
            scan_list = DEFAULT_CN_UNIVERSE

    print(
        f"[扫描] {date.today()} | 标的数: {len(scan_list)} | 扫描器: {args.scanner}",
        file=sys.stderr,
    )

    run_sgrade = args.scanner in ("SGRADE", "ALL")
    run_n1     = args.scanner in ("N1", "ALL")
    run_n2     = args.scanner in ("N2", "ALL")
    run_n3     = args.scanner in ("N3", "ALL")
    run_n4     = args.scanner in ("N4", "ALL")

    all_scanner_results: dict[str, list[dict]] = {}

    # ── S-GRADE 扫描 ──
    if run_sgrade:
        print(f"\n[SGRADE] 原始五项评分扫描...", file=sys.stderr)
        sgrade_results = []
        for ticker in scan_list:
            wl_item = watchlist_map.get(ticker)
            sector  = wl_item.get("sector", "未知") if wl_item else "未知"
            print(f"  → {ticker} ({sector})", file=sys.stderr, end=" ")
            r = scan_ticker(ticker, wl_item, sector)
            if r:
                sgrade_results.append(r)
                print(f"[{r.get('score', '?')}/5]", file=sys.stderr)

        sgrade_results.sort(key=lambda x: (-x.get("score", 0), x.get("ticker", "")))

        if args.min_score > 0:
            sgrade_results = [r for r in sgrade_results if r.get("score", 0) >= args.min_score]

        all_scanner_results["SGRADE"] = sgrade_results

    # ── N1 扫描 ──
    if run_n1:
        n1_results = scan_n1_northbound(scan_list, watchlist_map)
        all_scanner_results["N1"] = n1_results

    # ── N2 扫描 ──
    if run_n2:
        n2_results = scan_n2_volume_price_breakout(scan_list, watchlist_map)
        all_scanner_results["N2"] = n2_results

    # ── N3 扫描 ──
    if run_n3:
        n3_results = scan_n3_institutional_visits(scan_list, watchlist_map)
        all_scanner_results["N3"] = n3_results

    # ── N4 扫描 ──
    if run_n4:
        n4_results = scan_n4_cross_sector_rs(scan_list, watchlist_map)
        all_scanner_results["N4"] = n4_results

    # ── 输出 ──
    if args.json_output:
        output = {"scan_date": date.today().isoformat(), "results": all_scanner_results}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    # 格式化输出
    if run_sgrade and "SGRADE" in all_scanner_results:
        print_table(all_scanner_results["SGRADE"])
        strong    = [r for r in all_scanner_results["SGRADE"] if r.get("score", 0) >= 4]
        potential = [r for r in all_scanner_results["SGRADE"] if r.get("score", 0) == 3]
        print(
            f"\n[SGRADE] 摘要: 强S级={len(strong)} | 潜在S级={len(potential)} | "
            f"共扫描={len(all_scanner_results['SGRADE'])}只"
        )
        if strong:
            names = [f"{r['ticker']} {r.get('name', '')}" for r in strong]
            print(f"强S级候选: {', '.join(names)}")

    for scanner_id in ["N1", "N2", "N3", "N4"]:
        if scanner_id in all_scanner_results:
            print_discovery_results(scanner_id, all_scanner_results[scanner_id])

    # 综合摘要（多扫描器运行时）
    if len(all_scanner_results) > 1:
        print()
        print_combined_summary(all_scanner_results)


if __name__ == "__main__":
    main()
