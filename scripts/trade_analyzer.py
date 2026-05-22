# /// script
# requires-python = ">=3.9"
# dependencies = ["yfinance>=0.2.40", "rich>=13.0"]
# ///
"""
交易分析脚本 — Claude模拟盘
对 trade_log 中每笔交易评分(1-5)，识别行为模式，输出可操作洞察。
用法: python scripts/trade_analyzer.py [--state PATH] [--json] [--no-yf] [--no-save]
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
CNY_USD_FALLBACK = 7.25
STOP_KEYWORDS = ("stop", "stoploss", "止损", "stop_loss", "AUTO-STOPLOSS")
CATALYST_KEYWORDS = ("catalyst", "催化剂", "财报", "earnings", "beat", "WWDC", "ASCO", "ipo")

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    RICH = True
    console = Console()
except ImportError:
    RICH = False
    console = None  # type: ignore[assignment]


def load_state(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_state_path(override: Optional[Path]) -> Path:
    if override:
        return override.resolve()
    candidates = [Path.cwd() / "portfolio_state.json",
                  Path.cwd().parent / "portfolio_state.json",
                  REPO_ROOT / "portfolio_state.json"]
    p = next((c for c in candidates if c.exists()), None)
    if p is None:
        print("错误: 找不到 portfolio_state.json，请用 --state 指定路径。", file=sys.stderr)
        sys.exit(1)
    return p


def yf_price_at(ticker: str, target_date: str, use_yf: bool) -> Optional[float]:
    """获取 target_date 后最近交易日收盘价，失败返回 None。"""
    if not use_yf:
        return None
    try:
        import yfinance as yf
        end = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=10)).strftime("%Y-%m-%d")
        df = yf.download(ticker, start=target_date, end=end, auto_adjust=True, progress=False)
        if df.empty:
            return None
        v = df["Close"].iloc[0]
        return float(v) if v is not None else None
    except Exception:
        return None


# ── 5维评分 (1-5) ─────────────────────────────────────────────────────────────

def score_selection(trade: dict, later_price: Optional[float]) -> tuple[int, str]:
    """选股质量：股价事后是否朝预期方向运动？"""
    action = trade.get("action", "").lower()
    price = float(trade.get("price", 0) or 0)
    realized_pnl = float(trade.get("realized_pnl", 0) or 0)
    reason = trade.get("reason", "").lower()

    if later_price and price > 0:
        pct = (later_price - price) / price * 100
        if action in ("buy", "open"):
            if pct >= 10:   return 5, f"买后+{pct:.1f}%，方向完全正确"
            if pct >= 3:    return 4, f"买后+{pct:.1f}%，方向正确"
            if pct >= -3:   return 3, f"买后{pct:+.1f}%，持平"
            if pct >= -10:  return 2, f"买后{pct:+.1f}%，方向略错"
            return 1, f"买后{pct:+.1f}%，方向错误"
        else:  # sell/short/cover
            if pct <= -10:  return 5, f"卖后又跌{pct:.1f}%，卖时机极好"
            if pct <= -3:   return 4, f"卖后又跌{pct:.1f}%，卖得合理"
            if pct <= 3:    return 3, f"卖后{pct:+.1f}%，卖得尚可"
            if pct <= 10:   return 2, f"卖后涨{pct:.1f}%，卖早了"
            return 1, f"卖后涨{pct:.1f}%，过早止盈"

    # 回退：仅 sell/cover 有 realized_pnl
    if action in ("sell", "cover") and realized_pnl != 0:
        if realized_pnl > 0:    return 4, f"盈利出场 +{realized_pnl:,.0f}"
        if realized_pnl > -500: return 3, f"小亏出场 {realized_pnl:,.0f}"
        return 2, f"亏损出场 {realized_pnl:,.0f}"

    # 回退：buy 时看理由关键词质量
    has_thesis = any(k in reason for k in ("thesis", "bear case", "护城河", "催化剂", "catalyst"))
    return (4 if has_thesis else 3), "无后续价格，按理由质量评估"


def score_timing(trade: dict, later_price: Optional[float]) -> tuple[int, str]:
    """入场时机：入场价是否接近阶段低/高点？"""
    action = trade.get("action", "").lower()
    price = float(trade.get("price", 0) or 0)
    reason = trade.get("reason", "").lower()

    # 回调/低点信号词
    dip_signals = ("回调", "回撤", "跌", "低", "dip", "pullback", "下跌", "oversold")
    chasing_signals = ("涨", "run-up", "momentum", "追涨", "新高")
    catalyst_match = any(k in reason for k in CATALYST_KEYWORDS)
    dip_match = any(k in reason for k in dip_signals)
    chasing_match = any(k in reason for k in chasing_signals)

    if later_price and price > 0:
        pct = (later_price - price) / price * 100
        if action in ("buy", "open"):
            if pct >= 5:    return 5, f"买入点良好，次周+{pct:.1f}%"
            if pct >= 1:    return 4, f"买入点合理，次周+{pct:.1f}%"
            if pct >= -2:   return 3, f"买入点一般，次周{pct:+.1f}%"
            if pct >= -8:   return 2, f"买入偏早，次周{pct:+.1f}%"
            return 1, f"买入时机差，次周{pct:+.1f}%"

    # 回退：看理由关键词
    if dip_match and catalyst_match:    return 4, "回调+催化剂入场，时机合理"
    if catalyst_match:                   return 4, "催化剂驱动入场"
    if dip_match:                        return 4, "回调入场，时机偏好"
    if chasing_match:                    return 2, "存在追涨信号，时机偏差"
    return 3, "无足够信息判断时机"


def score_sizing(trade: dict, state: dict) -> tuple[int, str]:
    """仓位质量：是否符合 A≤25%/B≤15%/C≤8%/T≤8% 信心等级？"""
    pct_after = float(trade.get("portfolio_pct_after", 0) or 0) * 100
    reason = trade.get("reason", "").lower()
    # 从reason推断信心等级
    if "a级" in reason or "a级conviction" in reason or "core" in reason:
        grade, limit = "A", 25.0
    elif "b级" in reason or "b级conviction" in reason:
        grade, limit = "B", 15.0
    elif any(k in reason for k in ("试单", "scout", "3k", "小仓", "小票")):
        grade, limit = "C/T", 8.0
    else:
        grade, limit = "B", 15.0  # 默认

    if pct_after == 0:
        return 3, "无仓位占比数据"

    ratio = pct_after / limit
    if ratio <= 0.6:    return 4, f"仓位保守({pct_after:.1f}%，{grade}级上限{limit:.0f}%)，留有加仓空间"
    if ratio <= 1.0:    return 5, f"仓位匹配({pct_after:.1f}%≤{grade}级上限{limit:.0f}%)"
    if ratio <= 1.2:    return 3, f"仓位略超({pct_after:.1f}%>{grade}级上限{limit:.0f}%)"
    return 1, f"仓位严重超限({pct_after:.1f}%>{grade}级上限{limit:.0f}%)，违反风控"


def score_exit(trade: dict, later_price: Optional[float]) -> tuple[int, str]:
    """出场质量：sell/cover 专用，买入返回 0/N/A。"""
    action = trade.get("action", "").lower()
    if action in ("buy", "open"):
        return 0, "N/A (买入交易)"

    price = float(trade.get("price", 0) or 0)
    realized_pnl = float(trade.get("realized_pnl", 0) or 0)
    reason = trade.get("reason", "").lower()
    stop_triggered = any(k.lower() in reason for k in STOP_KEYWORDS)

    if later_price and price > 0:
        pct_after_exit = (later_price - price) / price * 100
        if action == "sell":
            # 卖出后价格跌 = 卖得好
            if pct_after_exit <= -15: return 5, f"退出后又跌{pct_after_exit:.1f}%，出场极佳"
            if pct_after_exit <= -5:  return 4, f"退出后又跌{pct_after_exit:.1f}%，出场合理"
            if pct_after_exit <= 5:   return 3, f"退出后{pct_after_exit:+.1f}%，出场尚可"
            if pct_after_exit <= 15:  return 2, f"退出后涨{pct_after_exit:.1f}%，过早离场"
            return 1, f"退出后涨{pct_after_exit:.1f}%，过早离场"

    # 回退
    if stop_triggered:
        if realized_pnl > 0:    return 5, "止盈止损触发，纪律执行"
        if realized_pnl > -500: return 4, "小亏止损，纪律执行"
        return 3, "止损触发，损失可控"
    if realized_pnl > 0:        return 4, f"盈利出场 +{realized_pnl:,.0f}"
    if realized_pnl > -1000:    return 3, f"小亏出场 {realized_pnl:,.0f}"
    return 2, f"较大亏损出场 {realized_pnl:,.0f}"


def score_discipline(trade: dict) -> tuple[int, str]:
    """行为纪律：止损执行、催化剂驱动、L10-L15规则遵守度。"""
    reason = (trade.get("reason", "") or "").lower()
    action = trade.get("action", "").lower()

    stop_ok     = any(k.lower() in reason for k in STOP_KEYWORDS)
    catalyst_ok = any(k in reason for k in CATALYST_KEYWORDS)
    rule_ref    = any(k in reason for k in ("l10", "l11", "l12", "l13", "l14", "l15"))
    chasing     = any(k in reason for k in ("涨了", "涨停", "跟涨", "run-up", "momentum"))
    no_reason   = len(reason.strip()) < 10

    score, notes = 3, []
    if stop_ok and action in ("sell", "cover"):
        score += 1; notes.append("止损/纪律执行")
    if catalyst_ok:
        score += 1; notes.append("催化剂驱动")
    if rule_ref:
        score += 1; notes.append("引用规则铁律")
    if chasing and not catalyst_ok:
        score -= 1; notes.append("存在追涨嫌疑")
    if no_reason:
        score -= 2; notes.append("缺少理由")

    score = max(1, min(5, score))
    note = "、".join(notes) if notes else "常规操作"
    return score, note


def score_trade(trade: dict, state: dict, use_yf: bool) -> dict:
    ticker = trade.get("ticker", "?")
    action = trade.get("action", "buy").lower()
    trade_date = (trade.get("timestamp") or trade.get("date", ""))[:10]
    currency = trade.get("currency", "USD")

    later_price = None
    if use_yf and trade_date:
        try:
            later_date = (datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")
            if currency == "CNY":
                yf_ticker = ticker + (".SS" if (ticker.startswith("6") or ticker.startswith("688")) else ".SZ")
            else:
                YF_MAP = {"SPUT": "SRUUF"}
                yf_ticker = YF_MAP.get(ticker.upper(), ticker.upper())
            later_price = yf_price_at(yf_ticker, later_date, use_yf)
        except Exception:
            later_price = None

    sel_score, sel_note = score_selection(trade, later_price)
    tim_score, tim_note = score_timing(trade, later_price)
    siz_score, siz_note = score_sizing(trade, state)
    ext_score, ext_note = score_exit(trade, later_price)
    dis_score, dis_note = score_discipline(trade)

    # 买入无出场分数，平均仅用4项
    active_scores = [sel_score, tim_score, siz_score, dis_score]
    if ext_score > 0:
        active_scores.append(ext_score)
    avg = sum(active_scores) / len(active_scores)

    return {
        "id": trade.get("id", "?"),
        "date": trade_date,
        "action": action,
        "ticker": ticker,
        "name": trade.get("name", ticker),
        "account": trade.get("account", "us"),
        "currency": currency,
        "price": float(trade.get("price", 0) or 0),
        "shares": int(trade.get("shares", 0) or 0),
        "value": float(trade.get("value", 0) or 0),
        "realized_pnl": float(trade.get("realized_pnl", 0) or 0),
        "later_price": later_price,
        "scores": {
            "selection": sel_score,    "selection_note": sel_note,
            "timing":    tim_score,    "timing_note":    tim_note,
            "sizing":    siz_score,    "sizing_note":    siz_note,
            "exit":      ext_score,    "exit_note":      ext_note,
            "discipline":dis_score,    "discipline_note":dis_note,
            "average": round(avg, 2),
        },
        "reason": trade.get("reason", ""),
        "sector": _infer_sector(trade, state),
    }


def _infer_sector(trade: dict, state: dict) -> str:
    ticker, account_key = trade.get("ticker", ""), trade.get("account", "us")
    for pos in state.get("accounts", {}).get(account_key, {}).get("positions", []):
        if pos.get("ticker") == ticker:
            return pos.get("sector", "Unknown")
    return "Unknown"


def analyze_patterns(scored_trades: list[dict]) -> dict:
    if not scored_trades:
        return {}

    def _wr(tlist):
        closed = [t for t in tlist if t["action"] in ("sell", "cover") and t["realized_pnl"] != 0]
        if not closed: return None, 0, 0
        wins = sum(1 for t in closed if t["realized_pnl"] > 0)
        return wins / len(closed), wins, len(closed)

    def _infer_type(t):
        r = (t.get("reason") or "").lower()
        if any(k in r for k in ("core", "a级", "底仓", "base")): return "core"
        if any(k in r for k in ("催化剂", "catalyst", "财报")):  return "catalyst"
        if any(k in r for k in ("scout", "试单", "小仓")):        return "scout"
        if any(k in r for k in ("momentum", "trading")):          return "trading"
        return "other"

    def _norm(t): return t["realized_pnl"] / CNY_USD_FALLBACK if t["currency"] == "CNY" else t["realized_pnl"]

    by_account: dict[str, list] = defaultdict(list)
    by_type: dict[str, list]    = defaultdict(list)
    sector_counts: dict[str, int]   = defaultdict(int)
    dow_scores: dict[str, list]     = defaultdict(list)
    for t in scored_trades:
        by_account[t["account"]].append(t)
        by_type[_infer_type(t)].append(t)
        sector_counts[t["sector"]] += 1
        try:
            dow_scores[datetime.strptime(t["date"], "%Y-%m-%d").strftime("%A")].append(t["scores"]["average"])
        except Exception:
            pass

    account_stats = {}
    for acc, tlist in by_account.items():
        wr, wins, total = _wr(tlist)
        account_stats[acc] = {
            "win_rate": wr, "wins": wins, "closed_trades": total,
            "total_pnl": sum(t["realized_pnl"] for t in tlist if t["action"] in ("sell", "cover")),
            "currency": "CNY" if acc == "a_share" else "USD",
            "avg_score": round(sum(t["scores"]["average"] for t in tlist) / len(tlist), 2) if tlist else 0,
        }

    type_stats = {}
    for ptype, tlist in by_type.items():
        wr, wins, total = _wr(tlist)
        type_stats[ptype] = {"win_rate": wr, "wins": wins, "closed_trades": total, "count": len(tlist)}

    closed_only = [t for t in scored_trades if t["action"] in ("sell", "cover") and t["realized_pnl"] != 0]
    sorted_abs = sorted(closed_only, key=_norm, reverse=True)
    sorted_pct = sorted(closed_only, key=lambda t: t["realized_pnl"] / (t.get("value") or 1), reverse=True)

    return {
        "account_stats": account_stats,
        "type_stats": type_stats,
        "best_abs":  sorted_abs[0]  if sorted_abs else None,
        "worst_abs": sorted_abs[-1] if sorted_abs else None,
        "best_pct":  sorted_pct[0]  if sorted_pct else None,
        "worst_pct": sorted_pct[-1] if sorted_pct else None,
        "sector_concentration": dict(sorted(sector_counts.items(), key=lambda x: -x[1])),
        "day_of_week": {dow: {"avg_score": round(sum(s)/len(s), 2), "count": len(s)} for dow, s in dow_scores.items()},
    }


def behavioral_metrics(scored_trades: list[dict], state: dict) -> dict:
    """行为量化指标。"""

    actual_stops = sum(
        1 for t in scored_trades
        if t["action"] in ("sell", "cover")
        and any(k.lower() in (t.get("reason") or "").lower() for k in STOP_KEYWORDS)
    )
    buy_trades = [t for t in scored_trades if t["action"] in ("buy", "open")]
    avg_selection  = sum(t["scores"]["selection"]  for t in buy_trades) / len(buy_trades) if buy_trades else 0
    avg_discipline = sum(t["scores"]["discipline"] for t in scored_trades) / len(scored_trades) if scored_trades else 0

    closed    = [t for t in scored_trades if t["action"] in ("sell", "cover") and t["realized_pnl"] != 0]
    wins_pnl  = [norm_pnl_usd(t) for t in closed if t["realized_pnl"] > 0]
    loss_pnl  = [norm_pnl_usd(t) for t in closed if t["realized_pnl"] < 0]
    avg_win   = sum(wins_pnl) / len(wins_pnl) if wins_pnl else 0
    avg_loss  = sum(loss_pnl) / len(loss_pnl) if loss_pnl else 0
    wl_ratio  = abs(avg_win / avg_loss) if avg_loss != 0 else None

    buy_with_cat = sum(1 for t in buy_trades if any(k in (t.get("reason") or "").lower() for k in CATALYST_KEYWORDS))
    catalyst_pct = buy_with_cat / len(buy_trades) * 100 if buy_trades else 0

    return {
        "actual_stop_losses":         actual_stops,
        "avg_selection_score":        round(avg_selection, 2),
        "avg_discipline_score":       round(avg_discipline, 2),
        "avg_win_usd":                round(avg_win, 2),
        "avg_loss_usd":               round(avg_loss, 2),
        "win_loss_ratio":             round(wl_ratio, 2) if wl_ratio else None,
        "inverted_win_loss_warning":  wl_ratio is not None and wl_ratio < 0.8,
        "buy_with_catalyst_pct":      round(catalyst_pct, 1),
        "total_buys":                 len(buy_trades),
        "total_sells":                len(closed),
    }


def norm_pnl_usd(t: dict) -> float:
    return t["realized_pnl"] / CNY_USD_FALLBACK if t["currency"] == "CNY" else t["realized_pnl"]


def generate_insights(scored_trades: list[dict], patterns: dict, behavioral: dict) -> list[str]:
    """生成最多 8 条可操作建议。"""
    insights = []

    # 1. 止损纪律
    stops = behavioral.get("actual_stop_losses", 0)
    if stops > 0:
        insights.append(f"[纪律] 已执行 {stops} 次止损 — 铁律执行记录良好")
    else:
        insights.append("[纪律] 尚无止损记录 — 注意不要回避止损")

    # 2. 胜率
    for acc, stats in patterns.get("account_stats", {}).items():
        wr = stats["win_rate"]
        cur = stats["currency"]
        if wr is None:
            continue
        if wr >= 0.6:
            insights.append(f"[{acc}] 胜率 {wr:.0%} ({stats['wins']}/{stats['closed_trades']}) — 选股质量良好")
        elif wr >= 0.4:
            insights.append(f"[{acc}] 胜率 {wr:.0%} ({stats['wins']}/{stats['closed_trades']}) — 尚可，关注选股质量")
        else:
            insights.append(f"[{acc}] ★ 胜率偏低 {wr:.0%} ({stats['wins']}/{stats['closed_trades']}) — 需复盘选股逻辑")

    # 3. 赢小输大预警
    if behavioral.get("inverted_win_loss_warning"):
        wl = behavioral.get("win_loss_ratio", 0)
        insights.append(
            f"[行为#L12] ★★ 赢小输大 — 平均盈利/亏损比 {wl:.2f} < 0.8，"
            "需检查是否快速了结盈利而死扛亏损"
        )

    # 4. 催化剂纪律
    cat_pct = behavioral.get("buy_with_catalyst_pct", 0)
    if cat_pct >= 70:
        insights.append(f"[催化剂] 买入 {cat_pct:.0f}% 有明确催化剂 — 纪律良好")
    elif cat_pct >= 40:
        insights.append(f"[催化剂] 买入 {cat_pct:.0f}% 有催化剂 — 建议提升至70%+")
    else:
        insights.append(f"[催化剂] ★ 仅 {cat_pct:.0f}% 买入有催化剂 — 存在冲动建仓风险(L13)")

    # 5. 最弱维度
    dim_names = {"selection": "选股", "timing": "时机", "sizing": "仓位", "discipline": "纪律"}
    avg_by_dim = {
        d: (lambda v: sum(v)/len(v) if v else 3.0)([t["scores"][d] for t in scored_trades if t["scores"][d] > 0])
        for d in dim_names
    }
    worst_dim = min(avg_by_dim, key=lambda d: avg_by_dim[d])
    insights.append(f"[改进重点] 平均分最低: {dim_names[worst_dim]} ({avg_by_dim[worst_dim]:.2f}/5.0) — 优先改善")

    # 6. 板块集中度
    conc = patterns.get("sector_concentration", {})
    if conc:
        top, top_cnt, total_cnt = next(iter(conc)), next(iter(conc.values())), sum(conc.values())
        if total_cnt > 0 and top_cnt / total_cnt > 0.4:
            insights.append(f"[集中度] {top} 占 {top_cnt}/{total_cnt} 笔 ({top_cnt/total_cnt:.0%}) — 注意板块风险")

    return insights[:8]

def score_color(s: int) -> "Text":
    return Text(str(s), style={5:"bold green",4:"green",3:"yellow",2:"red",1:"bold red"}.get(s,"white"))


def build_trade_score_table(scored_trades: list[dict]) -> "Table":
    table = Table(
        title=f"交易评分明细（共 {len(scored_trades)} 笔）",
        box=box.ROUNDED,
        header_style="bold cyan",
        show_lines=False,
    )
    table.add_column("日期", width=11)
    table.add_column("代码", width=9)
    table.add_column("方向", width=5)
    table.add_column("账户", width=8)
    table.add_column("选股", justify="center", width=5)
    table.add_column("时机", justify="center", width=5)
    table.add_column("仓位", justify="center", width=5)
    table.add_column("出场", justify="center", width=5)
    table.add_column("纪律", justify="center", width=5)
    table.add_column("均分", justify="right", width=6)
    table.add_column("盈亏", justify="right", width=12)

    for t in scored_trades:
        sc = t["scores"]
        pnl = t["realized_pnl"]
        sym = "¥" if t["currency"] == "CNY" else "$"
        if pnl > 0:
            pnl_text = Text(f"+{sym}{pnl:,.0f}", style="bold green")
        elif pnl < 0:
            pnl_text = Text(f"{sym}{pnl:,.0f}", style="bold red")
        else:
            pnl_text = Text("—", style="dim")

        ext = sc["exit"]
        avg_score = sc["average"]
        avg_style = "bold green" if avg_score >= 4 else ("yellow" if avg_score >= 3 else "bold red")

        table.add_row(
            t["date"],
            t["ticker"],
            t["action"].upper(),
            t["account"],
            score_color(sc["selection"]),
            score_color(sc["timing"]),
            score_color(sc["sizing"]),
            score_color(ext) if ext > 0 else Text("—", style="dim"),
            score_color(sc["discipline"]),
            Text(f"{avg_score:.1f}", style=avg_style),
            pnl_text,
        )
    return table


def build_pattern_table(patterns: dict) -> "Table":
    table = Table(
        title="账户维度模式",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("账户", width=12)
    table.add_column("胜率", justify="right", width=10)
    table.add_column("已结盈亏", justify="right", width=14)
    table.add_column("平均评分", justify="right", width=10)

    for acc, stats in patterns.get("account_stats", {}).items():
        wr = stats["win_rate"]
        wr_str = f"{wr:.0%} ({stats['wins']}/{stats['closed_trades']})" if wr is not None else "—"
        pnl = stats["total_pnl"]
        sym = "¥" if stats["currency"] == "CNY" else "$"
        pnl_style = "bold green" if pnl > 0 else ("bold red" if pnl < 0 else "white")
        table.add_row(
            acc,
            wr_str,
            Text(f"{sym}{pnl:+,.0f}", style=pnl_style),
            f"{stats['avg_score']:.2f}/5.0",
        )
    return table


def build_insights_panel(insights: list[str]) -> "Panel":
    return Panel("\n".join(f"• {i}" for i in insights), title="可操作洞察", border_style="cyan", expand=False)


def print_plain(scored_trades, patterns, behavioral, insights):
    print(f"\n=== 交易评分明细 ({len(scored_trades)} 笔) ===")
    for t in scored_trades:
        sc = t["scores"]
        print(f"  {t['date']} {t['ticker']} {t['action'].upper()} | "
              f"选={sc['selection']} 时={sc['timing']} 仓={sc['sizing']} "
              f"出={sc['exit'] or '—'} 纪={sc['discipline']} 均={sc['average']:.1f} | "
              f"pnl={t['realized_pnl']:+,.0f}")
    print("\n=== 账户模式 ===")
    for acc, s in patterns.get("account_stats", {}).items():
        wr_s = f"{s['win_rate']:.0%}" if s["win_rate"] is not None else "N/A"
        print(f"  {acc}: 胜率={wr_s} 均分={s['avg_score']:.2f}")
    print("\n=== 可操作洞察 ===")
    for ins in insights:
        print(f"  {ins}")


def build_json_output(scored_trades, patterns, behavioral, insights, state_path):
    excl = ("best_abs", "worst_abs", "best_pct", "worst_pct")
    return {
        "generated_at": datetime.now().isoformat(),
        "source": str(state_path),
        "trade_count": len(scored_trades),
        "scored_trades": scored_trades,
        "patterns": {k: v for k, v in patterns.items() if k not in excl},
        "top_trades": {k: patterns.get(k) for k in excl},
        "behavioral": behavioral,
        "insights": insights,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Claude模拟盘交易分析 — 评分 + 模式识别 + 可操作洞察",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--state", type=Path, default=None, help="portfolio_state.json 路径")
    parser.add_argument("--json", action="store_true", help="机器可读 JSON 输出（同时写文件）")
    parser.add_argument("--no-yf", action="store_true", help="跳过 yfinance 调用，仅用 JSON 内价格")
    parser.add_argument("--no-save", action="store_true", help="不写 analysis/ 文件")
    args = parser.parse_args()

    use_yf = not args.no_yf
    state_path = find_state_path(args.state)

    if RICH and not args.json:
        console.print(Panel(
            f"[bold cyan]Claude 模拟盘交易分析[/bold cyan]\n"
            f"读取: {state_path}  |  yfinance: {'开启' if use_yf else '关闭'}",
            expand=False,
        ))

    state = load_state(state_path)
    trade_log = state.get("trade_log", [])

    if not trade_log:
        if RICH:
            console.print("[yellow]trade_log 为空，无可分析交易。[/yellow]")
        else:
            print("trade_log 为空，无可分析交易。")
        sys.exit(0)

    # 评分
    if RICH and not args.json:
        with console.status("[cyan]正在评分交易...[/cyan]"):
            scored = [score_trade(t, state, use_yf) for t in trade_log]
    else:
        scored = [score_trade(t, state, use_yf) for t in trade_log]

    patterns   = analyze_patterns(scored)
    behavioral = behavioral_metrics(scored, state)
    insights   = generate_insights(scored, patterns, behavioral)

    if args.json:
        output = build_json_output(scored, patterns, behavioral, insights, state_path)
        print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
        if not args.no_save:
            _save_analysis(output, state_path)
        return

    if RICH:
        console.print()
        console.print(build_trade_score_table(scored))
        console.print()
        console.print(build_pattern_table(patterns))

        # 最佳/最差
        best  = patterns.get("best_abs")
        worst = patterns.get("worst_abs")
        if best or worst:
            lines = []
            if best:
                sym = "¥" if best["currency"] == "CNY" else "$"
                lines.append(f"[green]最赚(绝对): {best['ticker']} {sym}{best['realized_pnl']:+,.0f} ({best['date']})[/green]")
            if worst:
                sym = "¥" if worst["currency"] == "CNY" else "$"
                lines.append(f"[red]最亏(绝对): {worst['ticker']} {sym}{worst['realized_pnl']:+,.0f} ({worst['date']})[/red]")
            console.print(Panel("\n".join(lines), title="极值交易", border_style="yellow"))

        console.print()
        console.print(build_insights_panel(insights))

        # 行为摘要
        beh_lines = [
            f"止损执行次数: [bold]{behavioral['actual_stop_losses']}[/bold]",
            f"平均选股分: [bold]{behavioral['avg_selection_score']:.2f}[/bold]/5.0",
            f"平均纪律分: [bold]{behavioral['avg_discipline_score']:.2f}[/bold]/5.0",
            f"催化剂买入占比: [bold]{behavioral['buy_with_catalyst_pct']}%[/bold]",
            f"平均盈利(USD): [green]{behavioral['avg_win_usd']:+.0f}[/green]   "
            f"平均亏损(USD): [red]{behavioral['avg_loss_usd']:+.0f}[/red]   "
            f"盈亏比: [bold]{behavioral['win_loss_ratio'] or 'N/A'}[/bold]"
            + (" [bold red]★ 赢小输大[/bold red]" if behavioral["inverted_win_loss_warning"] else ""),
        ]
        console.print(Panel("\n".join(beh_lines), title="行为指标", border_style="magenta"))
        console.print()
    else:
        print_plain(scored, patterns, behavioral, insights)

    if not args.no_save:
        output = build_json_output(scored, patterns, behavioral, insights, state_path)
        saved = _save_analysis(output, state_path)
        if RICH:
            console.print(f"[dim]分析已保存: {saved}[/dim]")
        else:
            print(f"分析已保存: {saved}")


def _save_analysis(output: dict, state_path: Path) -> Path:
    analysis_dir = state_path.parent / "analysis"
    analysis_dir.mkdir(exist_ok=True)
    today = date.today().strftime("%Y-%m-%d")
    out_path = analysis_dir / f"trade-analysis-{today}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    return out_path


if __name__ == "__main__":
    main()
