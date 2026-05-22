# /// script
# requires-python = ">=3.9"
# dependencies = ["yfinance>=0.2.40", "rich>=13.0"]
# ///
"""
S级候选扫描器 — 全仓短线机会初筛 v1.0

S级标准: 供应链瓶颈+催化剂在30天内+小票已先飞+量价突破+浅跌幅bear case
得分 ≥3 → 潜在S级候选
得分 ≥4 → 强S级候选

用法:
  uv run --script scripts/sgrade_scanner.py                              # 扫描watchlist
  uv run --script scripts/sgrade_scanner.py --tickers 002938,002475,002273  # 指定标的
  uv run --script scripts/sgrade_scanner.py --json                      # JSON输出
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

# A股ticker后缀
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


# ─────────────────────────────────────────────
# 五项评分标准
# ─────────────────────────────────────────────

def score_supply_chain(sector: str) -> tuple[int, str]:
    """S1: 供应链瓶颈赛道（0/1）"""
    sector_upper = sector.upper()
    for kw in SGRADE_SECTORS:
        if kw.upper() in sector_upper:
            return 1, f"赛道匹配: {sector}"
    # 检查sector字段中的关键词
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
        # 小票已飞 且 本股滞后 >= 3%
        if sector_small_caps_5d > 5 and (sector_small_caps_5d - stock_5d_ret) >= 3:
            return 1, f"小票已涨{sector_small_caps_5d:+.1f}%，本股仅{stock_5d_ret:+.1f}%"
        return 0, f"未满足: 小票{sector_small_caps_5d:+.1f}% vs 本股{stock_5d_ret:+.1f}%"
    else:
        # 无小票数据 → 代理: 本股5日涨幅<2%（还没动，可能是补涨机会）
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

    # 用可用的数据做均线（优先20日，最少用全部可用数据）
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
    # 优先使用watchlist中的bear case
    if watchlist_item:
        bc = watchlist_item.get("bear_case_downside_pct")
        if bc is not None:
            bc_abs = abs(bc)
            if bc_abs < 15:
                return 1, f"Bear case {bc}%（watchlist，浅）"
            return 0, f"Bear case {bc}%（watchlist，超15%）"

    # 回退: 从价格计算20日低点到当前跌幅
    if len(close) < 5:
        return 0, "数据不足"
    window = min(20, len(close))
    low_20d = min(close[-window:])
    current = close[-1]
    downside = (low_20d / current - 1) * 100  # 负数
    if downside > -10:   # 跌幅 <10%
        return 1, f"20日低点支撑{downside:.1f}%（浅）"
    return 0, f"20日低点支撑{downside:.1f}%（>10%）"


# ─────────────────────────────────────────────
# 单股扫描
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

    # 20日变化
    open_20d = close_1mo[0] if close_1mo else current_price
    ret_20d  = (current_price / open_20d - 1) * 100 if open_20d else 0

    # 量比（最新成交量 / 20日均量）
    window   = min(20, len(volume_1mo))
    vol_ma   = sum(volume_1mo[-window:]) / window if window > 0 else 1
    vol_ratio = volume_1mo[-1] / vol_ma if vol_ma > 0 else 0

    # 五项评分
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
# 显示
# ─────────────────────────────────────────────

def print_table(results: list[dict]) -> None:
    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box
    except ImportError:
        # Fallback plain text
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
            return f"[green]✓[/green]" if s else f"[dim]✗[/dim]"

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

    # 详细失败原因（仅对潜在S级候选）
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


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="S级候选扫描器 — A股全仓短线机会初筛",
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
        help="只显示得分 >= N 的标的（默认0=全显示）",
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
            print("[ERROR] watchlist为空且未指定--tickers", file=sys.stderr)
            sys.exit(1)

    print(f"[扫描] {date.today()} | 标的数: {len(scan_list)}", file=sys.stderr)

    results = []
    for ticker in scan_list:
        wl_item = watchlist_map.get(ticker)
        sector  = wl_item.get("sector", "未知") if wl_item else "未知"
        print(f"  → {ticker} ({sector})", file=sys.stderr, end=" ")
        r = scan_ticker(ticker, wl_item, sector)
        if r:
            results.append(r)
            print(f"[{r.get('score', '?')}/5]", file=sys.stderr)

    # 排序: 高分优先
    results.sort(key=lambda x: (-x.get("score", 0), x.get("ticker", "")))

    # 过滤
    if args.min_score > 0:
        results = [r for r in results if r.get("score", 0) >= args.min_score]

    if args.json_output:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_table(results)

        # 摘要
        strong = [r for r in results if r.get("score", 0) >= 4]
        potential = [r for r in results if r.get("score", 0) == 3]
        print(f"\n摘要: 强S级={len(strong)} | 潜在S级={len(potential)} | 共扫描={len(results)}只")
        if strong:
            names = [f"{r['ticker']} {r.get('name', '')}" for r in strong]
            print(f"强S级候选: {', '.join(names)}")


if __name__ == "__main__":
    main()
