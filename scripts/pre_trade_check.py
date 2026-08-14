#!/usr/bin/env python3
"""
建仓前置检查 · pre_trade_check.py · 2026-08-14 (重建任务A4)
────────────────────────────────────────────────────────────────────────────
【为什么有这个脚本】
astock_scan_sop.md (2026-08-10定版) 声称"配套脚本scan_sop.py把流程固化,每一步都有
代码级检查点"——但 scan_sop.py 从未被创建。规则退化成纯文本软约束,和它想解决的问题
(规则改错三版/幸存者偏差/自我篡改计划仓位)是同一类病:写在文档里的规则没有执法层。

本脚本不是 scan_sop.py 的重建(七步全流程编排价值存疑,见SOP修改建议),只做其中
**能被数字/日期/布尔值机械判定**的那一半——决策前的客观事实核查。判断层(值不值得买/
现在买不买)已经在 organism_decision.py 代码化,不重复。

⛔本脚本只回答客观事实,覆盖且只覆盖以下7项:
  ①现金是否够            ②单票SABCT上限是否会超
  ③该标的是否已有持仓     ④最近定期报告是否已披露+披露当日市场反应(R9,08-14 SOP新增,此前从未落地)
  ⑤灾难线(-12%硬止损)距离 ⑥前10日低距离(信息项,不否决)
  ⑦T+1限制

⛔明确不做(已被回测证伪为负expectancy,见organism_decision.py注释/astock_scan_sop.md R5):
  位置门(距25日高否决)/追涨熔断(20日涨幅类否决)/普跌门/regime乘数/量比否决(天量>=3.0除外,
  且天量否决是"能不能出场"不是"该不该买"的范畴,不在本脚本内)。
  这些是"该不该买"的判断,不是"数据允不允许买",不属于本脚本范围。

数据源(⛔D12铁律,禁yfinance):
  astock_data_layer(Eastmoney主源+腾讯兜底,实时价) + 新浪日K(tree_anomaly_scan.fetch_kline_sina)
  + akshare stock_report_disclosure(巨潮资讯预约披露,R9)

用法:
  python3 pre_trade_check.py --ticker 600690 --pct 0.05
  python3 pre_trade_check.py --ticker 600690 --pct 0.05 --sabct A-
  python3 pre_trade_check.py --ticker 600690 --pct 0.05 --period 2026半年报 --json

--pct 语义: 本次拟买入金额 占 total_assets 的比例(增量买入额,不是买完后的目标总仓位)。
            单票上限检查会自动加总"已持有市值+本次拟买入额"来判定是否超SABCT上限。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

import astock_data_layer as adl          # noqa: E402  (import即设NO_PROXY+装yfinance拦截器)
import tree_anomaly_scan as tas          # noqa: E402  (复用fetch_kline_sina等新浪K线拉取)
from core.config import ASTOCK_HARD_STOP_PCT, ASTOCK_POSITION_LIMITS  # noqa: E402

TZ_BEIJING = timezone(timedelta(hours=8))
PORTFOLIO_PATH = SCRIPT_DIR.parent / "portfolio_state.json"
WATCHLIST_PATH = SCRIPT_DIR.parent / "watchlist_config.json"
CN_ACCOUNT_KEY = "a_share"
PREVLOW_N = 10  # 前N日低,与portfolio_trend_check.py的EXIT_N=10对齐


# ──────────────────────────────────────────────────────────────────────────
# 基础工具
# ──────────────────────────────────────────────────────────────────────────

def now_bj() -> datetime:
    return datetime.now(TZ_BEIJING)


def load_portfolio() -> dict:
    with open(PORTFOLIO_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_watchlist() -> dict:
    try:
        with open(WATCHLIST_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def find_position(positions: list, ticker: str) -> dict | None:
    for p in positions:
        if p.get("ticker") == ticker:
            return p
    return None


def lookup_sabct(ticker: str, position: dict | None, watchlist: dict) -> tuple[str | None, str | None]:
    """SABCT评级优先级: ①已持仓的conviction_level ②watchlist_config.cn_watchlist.confidence ③无(需--sabct)"""
    if position and position.get("conviction_level") in ASTOCK_POSITION_LIMITS:
        return position["conviction_level"], "portfolio_state.positions.conviction_level"
    for w in (watchlist or {}).get("cn_watchlist", []):
        if w.get("ticker") == ticker and w.get("confidence") in ASTOCK_POSITION_LIMITS:
            return w["confidence"], "watchlist_config.cn_watchlist.confidence"
    return None, None


def current_report_period(dt: datetime) -> str:
    """A股定期报告披露窗口启发式映射(可用--period覆盖精确值):
       1-4月→上一年年报(Apr30截止) / 5-8月→当年半年报(Aug31截止) / 9-12月→当年三季报(Oct31截止)
       akshare巨潮接口有效period格式(2026-08-14实测确认): {year}一季 / {year}半年报 / {year}三季 / {year}年报
       (不是"一季报"/"三季报",少一个"报"字——akshare源码period_map硬编码如此)"""
    y, m = dt.year, dt.month
    if 1 <= m <= 4:
        return f"{y - 1}年报"
    if 5 <= m <= 8:
        return f"{y}半年报"
    return f"{y}三季"


# ──────────────────────────────────────────────────────────────────────────
# 各检查项(每项返回 dict(id, name, status, detail, **data)) status ∈ PASS/WARNING/BLOCK
# ──────────────────────────────────────────────────────────────────────────

def check_cash(cash: float, buy_amount: float) -> dict:
    ok = cash >= buy_amount
    return dict(
        id="cash", name="现金是否够",
        status="PASS" if ok else "BLOCK",
        cash=round(cash, 2), buy_amount=round(buy_amount, 2),
        shortfall=round(max(0.0, buy_amount - cash), 2),
        detail=(f"现金¥{cash:,.0f} 足够本次拟买入¥{buy_amount:,.0f}"
                if ok else
                f"⛔现金¥{cash:,.0f} 不足本次拟买入¥{buy_amount:,.0f},差¥{buy_amount - cash:,.0f}"),
    )


def check_single_cap(ticker: str, sabct: str | None, sabct_source: str | None,
                      existing_value: float, buy_amount: float, total_assets: float) -> dict:
    if sabct is None:
        return dict(
            id="single_cap", name="单票SABCT上限",
            status="WARNING", detail="⚠️未找到SABCT评级(未持仓且不在watchlist_config.cn_watchlist),"
                                      "无法判定上限,请用--sabct显式提供。SABCT<A-一律不建仓(strategy_astock.md T13)。",
        )
    cap = ASTOCK_POSITION_LIMITS[sabct]
    new_value = existing_value + buy_amount
    new_pct = new_value / total_assets if total_assets else 0.0
    over = new_pct > cap + 1e-6
    return dict(
        id="single_cap", name="单票SABCT上限",
        status="BLOCK" if over else "PASS",
        sabct=sabct, sabct_source=sabct_source, cap_pct=round(cap, 4),
        pct_after_buy=round(new_pct, 4), headroom_pct=round(cap - new_pct, 4),
        detail=(f"⛔{sabct}级上限{cap * 100:.0f}%,买后仓位达{new_pct * 100:.1f}%,超{(new_pct - cap) * 100:.1f}pp"
                if over else
                f"{sabct}级上限{cap * 100:.0f}%,买后仓位{new_pct * 100:.1f}%,余量{(cap - new_pct) * 100:.1f}pp"),
    )


def check_existing_position(ticker: str, position: dict | None, current_price: float | None) -> dict:
    if position is None:
        return dict(id="existing_position", name="是否已有持仓", status="PASS",
                     held=False, detail="无持仓,全新建仓")
    shares = position.get("shares", 0)
    avg_cost = position.get("avg_cost", 0)
    mv = shares * current_price if current_price else position.get("market_value")
    pct = position.get("portfolio_pct")
    return dict(
        id="existing_position", name="是否已有持仓", status="PASS", held=True,
        shares=shares, avg_cost=avg_cost, market_value=round(mv, 2) if mv else None,
        current_pct=pct, hold_nature=position.get("type"), entry_date=position.get("entry_date"),
        detail=f"已持{shares}股,成本{avg_cost},现占{pct * 100 if pct else 0:.1f}%,持仓性质={position.get('type')}",
    )


def check_disclosure(ticker: str, period: str, current_price: float | None) -> dict:
    """R9: 定期报告披露状态+已披露时的市场反应。"""
    try:
        import akshare as ak
        import pandas as pd
    except Exception as e:
        return dict(id="disclosure", name="定期报告披露(R9)", status="WARNING",
                     detail=f"akshare/pandas不可用: {e}")
    try:
        df = ak.stock_report_disclosure(market="沪深京", period=period)
    except Exception as e:
        return dict(id="disclosure", name="定期报告披露(R9)", status="WARNING",
                     period=period, detail=f"查询失败(巨潮资讯接口): {e}")
    row = df[df["股票代码"] == ticker]
    if row.empty:
        return dict(id="disclosure", name="定期报告披露(R9)", status="WARNING",
                     period=period, detail=f"{ticker}不在{period}披露名单内(数据源未覆盖/代码有误)")
    r = row.iloc[0]
    actual, scheduled = r["实际披露"], r["首次预约"]
    today = now_bj().date()

    if pd.isna(actual):
        sched_str = str(scheduled)[:10] if not pd.isna(scheduled) else "未预约"
        days_left = (pd.Timestamp(scheduled).date() - today).days if not pd.isna(scheduled) else None
        return dict(
            id="disclosure", name="定期报告披露(R9)", status="PASS",
            period=period, disclosed=False, scheduled=sched_str, days_to_disclosure=days_left,
            detail=(f"{period}尚未披露,预约日{sched_str}" +
                    (f"(还有{days_left}天)" if days_left is not None else "")),
        )

    actual_str = str(actual)[:10]
    days_since = (today - pd.Timestamp(actual).date()).days
    reaction = None
    bars = tas.fetch_kline_sina(ticker, n=90)
    if bars:
        idx = next((i for i, b in enumerate(bars) if b["d"] >= actual_str), None)
        if idx is not None and idx > 0:
            day_bar, prev_bar = bars[idx], bars[idx - 1]
            day_chg = (day_bar["c"] - prev_bar["c"]) / prev_bar["c"] * 100 if prev_bar["c"] else None
            since_chg = ((current_price - day_bar["c"]) / day_bar["c"] * 100
                         if (current_price and day_bar["c"]) else None)
            reaction = dict(disclosure_day_chg_pct=round(day_chg, 2) if day_chg is not None else None,
                             since_disclosure_chg_pct=round(since_chg, 2) if since_chg is not None else None)

    reacted = bool(reaction and reaction.get("disclosure_day_chg_pct") is not None
                   and abs(reaction["disclosure_day_chg_pct"]) >= 5)
    status = "WARNING" if reacted else "PASS"
    detail = f"{period}已披露({actual_str},{days_since}天前)"
    if reaction:
        dchg = reaction["disclosure_day_chg_pct"]
        schg = reaction["since_disclosure_chg_pct"]
        detail += (f",披露当日{dchg:+.1f}%" if dchg is not None else "")
        detail += (f",披露后累计{schg:+.1f}%" if schg is not None else "")
        if reacted:
            detail += " ⚠️市场已对该事件有明显反应(披露当日|涨跌|≥5%),现在买非抢跑窗口,是追认兑现"
    else:
        detail += ",市场反应数据不足(K线缺失)"
    return dict(id="disclosure", name="定期报告披露(R9)", status=status, period=period,
                disclosed=True, disclosure_date=actual_str, days_since_disclosure=days_since,
                **({"reaction": reaction} if reaction else {}), detail=detail)


def check_disaster_line(ticker: str, position: dict | None, current_price: float | None) -> dict:
    """灾难线(-12%硬止损,core.config.ASTOCK_HARD_STOP_PCT)距离。已持仓用stop_loss字段
    (无则用avg_cost推算);未持仓给出以现价建仓的假设线,纯信息项不否决(新建仓天然距灾难线12%)。"""
    if current_price is None:
        return dict(id="disaster_line", name="灾难线距离", status="WARNING", detail="现价获取失败,无法计算")
    if position is not None:
        avg_cost = position.get("avg_cost")
        disaster_price = position.get("stop_loss") or (avg_cost * (1 + ASTOCK_HARD_STOP_PCT) if avg_cost else None)
        if disaster_price is None:
            return dict(id="disaster_line", name="灾难线距离", status="WARNING", detail="缺avg_cost/stop_loss,无法计算")
        dist_pct = (current_price - disaster_price) / current_price
        if current_price <= disaster_price:
            status = "BLOCK"
            detail = f"⛔现价{current_price}已触及/跌破灾难线{disaster_price:.2f}(该持仓按T18硬信号本应已清仓,不应加仓)"
        elif dist_pct < 0.03:
            status = "WARNING"
            detail = f"⚠️现价{current_price}距灾难线{disaster_price:.2f}仅{dist_pct * 100:.1f}%,临近硬止损"
        else:
            status = "PASS"
            detail = f"现价{current_price}距灾难线{disaster_price:.2f}尚有{dist_pct * 100:.1f}%"
        return dict(id="disaster_line", name="灾难线距离", status=status,
                    disaster_price=round(disaster_price, 2), distance_pct=round(dist_pct, 4), detail=detail)
    # 未持仓: 假设以现价建仓
    hypo = current_price * (1 + ASTOCK_HARD_STOP_PCT)
    return dict(id="disaster_line", name="灾难线距离", status="PASS",
                disaster_price=round(hypo, 2), distance_pct=round(-ASTOCK_HARD_STOP_PCT, 4),
                detail=f"新建仓,假设灾难线=现价×{1 + ASTOCK_HARD_STOP_PCT:.2f}={hypo:.2f}(距现价{-ASTOCK_HARD_STOP_PCT * 100:.0f}%,定义使然)")


def check_prevlow(ticker: str, current_price: float | None) -> dict:
    """前10日低距离。⛔信息项,不否决(R5实证: 位置类否决在两段point-in-time回测都垫底)。
    仅用于提示: 若已破前低,提醒持仓侧可能已触发portfolio_trend_check.py的破位出场门。"""
    if current_price is None:
        return dict(id="prevlow", name="前10日低距离", status="WARNING", detail="现价获取失败,无法计算")
    bars = tas.fetch_kline_sina(ticker, n=30)
    if len(bars) < PREVLOW_N + 1:
        return dict(id="prevlow", name="前10日低距离", status="WARNING", detail=f"K线不足{PREVLOW_N}日,无法计算(可能次新股/停牌)")
    low10 = min(b["l"] for b in bars[-PREVLOW_N - 1:-1])
    broken = current_price < low10
    dist_pct = (current_price - low10) / current_price
    return dict(
        id="prevlow", name="前10日低距离", status="WARNING" if broken else "PASS",
        low10=round(low10, 2), distance_pct=round(dist_pct, 4), broken=broken,
        detail=(f"现价{current_price}已破前{PREVLOW_N}日低{low10:.2f}"
                f"(⛔不否决买入,R5证伪;若已持仓提示复核portfolio_trend_check.py出场门)"
                if broken else
                f"现价{current_price}距前{PREVLOW_N}日低{low10:.2f} 尚有{dist_pct * 100:.1f}%"),
    )


def check_t1(ticker: str, position: dict | None) -> dict:
    if position is None:
        return dict(id="t1", name="T+1限制", status="PASS", restricted=False, detail="无持仓,不涉及T+1")
    entry_date = position.get("entry_date", "")
    entry_day = entry_date[:10] if entry_date else None
    today = now_bj().strftime("%Y-%m-%d")
    restricted = entry_day == today
    return dict(id="t1", name="T+1限制", status="WARNING" if restricted else "PASS",
                restricted=restricted, entry_date=entry_day,
                detail=(f"⚠️{ticker}今日({today})已买入,当日不可卖出(T+1)"
                        if restricted else
                        f"非当日买入(entry_date={entry_day}),无T+1限制"))


# ──────────────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────────────

def run_check(ticker: str, pct: float, sabct_override: str | None, period_override: str | None,
              account_key: str = CN_ACCOUNT_KEY) -> dict:
    ticker = adl.bare_code(ticker)
    portfolio = load_portfolio()
    account = portfolio["accounts"][account_key]
    positions = account.get("positions", [])
    position = find_position(positions, ticker)
    watchlist = load_watchlist()

    price_data = adl.get_batch_prices([ticker]).get(ticker, {})
    current_price = price_data.get("price")
    if current_price is None:
        # 兜底: 用持仓里最后已知价,仍失败则整份检查标NO_DATA
        current_price = position.get("current_price") if position else None

    total_assets = account.get("total_assets", 0.0)
    cash = account.get("cash", 0.0)
    buy_amount = pct * total_assets
    existing_value = (position["shares"] * current_price
                       if position and current_price else
                       (position.get("market_value", 0.0) if position else 0.0))

    sabct, sabct_source = (sabct_override, "--sabct参数") if sabct_override else lookup_sabct(ticker, position, watchlist)
    period = period_override or current_report_period(now_bj())

    checks = [
        check_cash(cash, buy_amount),
        check_single_cap(ticker, sabct, sabct_source, existing_value, buy_amount, total_assets),
        check_existing_position(ticker, position, current_price),
        check_disclosure(ticker, period, current_price),
        check_disaster_line(ticker, position, current_price),
        check_prevlow(ticker, current_price),
        check_t1(ticker, position),
    ]

    if any(c["status"] == "BLOCK" for c in checks):
        overall = "BLOCK"
    elif any(c["status"] == "WARNING" for c in checks):
        overall = "WARNING"
    else:
        overall = "PASS"

    return dict(
        ticker=ticker, name=position.get("name") if position else price_data.get("name"),
        checked_at=now_bj().isoformat(timespec="seconds"),
        current_price=current_price, price_source=price_data.get("source"),
        intended_pct=pct, intended_amount=round(buy_amount, 2),
        total_assets=total_assets, cash=cash,
        overall=overall, checks=checks,
    )


def print_report(result: dict) -> None:
    mark = {"PASS": "✅PASS", "WARNING": "⚠️WARNING", "BLOCK": "⛔BLOCK"}
    print("=" * 100)
    print(f"建仓前置检查 · {result['ticker']} {result.get('name') or ''}"
          f"  现价{result['current_price']}({result.get('price_source')})"
          f"  拟买入{result['intended_pct'] * 100:.1f}%(¥{result['intended_amount']:,.0f})")
    print(f"总资产¥{result['total_assets']:,.0f}  现金¥{result['cash']:,.0f}  检查时刻{result['checked_at']}")
    print("=" * 100)
    for c in result["checks"]:
        print(f"[{mark[c['status']]:<12}] {c['name']:<16} {c['detail']}")
    print("-" * 100)
    print(f"总裁决: {mark[result['overall']]}")
    if result["overall"] == "BLOCK":
        print("⛔存在硬阻断项,不得执行execute_trade.py。")
    elif result["overall"] == "WARNING":
        print("⚠️存在警告项,人工复核后再决定是否执行。")
    else:
        print("✅客观项全部通过。⚠️本脚本不判断'该不该买'(供给侧/edge/催化剂等主观判断仍需完成)。")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ticker", required=True, help="A股代码,如600690")
    ap.add_argument("--pct", type=float, required=True,
                     help="本次拟买入金额占total_assets比例,如0.05=5%%(不是买完后的目标总仓位)")
    ap.add_argument("--sabct", default=None, choices=sorted(ASTOCK_POSITION_LIMITS.keys()),
                     help="SABCT评级,不给则自动从持仓/watchlist查找")
    ap.add_argument("--period", default=None, help="定期报告期,如'2026半年报'/'2026三季'/'2026年报'。不给则按当前日期启发式推断")
    ap.add_argument("--account", default=CN_ACCOUNT_KEY, help="账户key,默认a_share")
    ap.add_argument("--json", action="store_true", help="输出JSON而非表格")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    result = run_check(args.ticker, args.pct, args.sabct, args.period, args.account)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print_report(result)
    return {"PASS": 0, "WARNING": 0, "BLOCK": 1}[result["overall"]]


if __name__ == "__main__":
    sys.exit(main())
