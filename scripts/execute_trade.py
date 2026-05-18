# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40"]
# ///
"""
模拟盘交易执行器

用法:
  uv run scripts/execute_trade.py buy   --account us --ticker NVDA --shares 10 --reason "AI infra base position"
  uv run scripts/execute_trade.py sell  --account us --ticker NVDA --shares 5  --reason "target reached"
  uv run scripts/execute_trade.py sell  --account cn --ticker 002929 --all     --reason "stop loss"
  uv run scripts/execute_trade.py short --account us --ticker MSTR --shares 20 --reason "BTC overexposure thesis"
  uv run scripts/execute_trade.py cover --account us --ticker MSTR --shares 20 --reason "target reached"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yfinance as yf

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PORTFOLIO_PATH = Path(__file__).parent.parent / "portfolio_state.json"
CN_LOT_SIZE = 100  # A股最小交易单位
MAX_SINGLE_POSITION_PCT = 0.15  # 单一持仓上限 15%
MAX_SHORT_POSITION_PCT = 0.10   # 单一空头上限 10%
MAX_GROSS_EXPOSURE = 300000     # 美股总敞口上限 $300K (2x leverage)
SHORT_STOP_LOSS_PCT = 0.15      # 空头止损: 反向+15%
CN_ACCOUNT_KEY = "a_share"
US_ACCOUNT_KEY = "us"

TZ_BEIJING = timezone(timedelta(hours=8))

# OTC / special tickers that need yfinance remapping
YF_TICKER_MAP: dict[str, str] = {
    "SPUT": "SRUUF",    # Sprott Uranium Trust trades OTC as SRUUF
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(TZ_BEIJING).isoformat(timespec="seconds")


def load_portfolio() -> dict:
    with open(PORTFOLIO_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_portfolio_atomic(state: dict) -> None:
    """写 tmp 文件再 rename，保证原子性。"""
    dir_ = PORTFOLIO_PATH.parent
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp", prefix="portfolio_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, PORTFOLIO_PATH)
        except Exception:
            # 清理 tmp
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        raise RuntimeError(f"JSON写入失败，回滚: {e}") from e


def get_account_key(account_arg: str) -> str:
    mapping = {
        "us": US_ACCOUNT_KEY,
        "cn": CN_ACCOUNT_KEY,
        "a_share": CN_ACCOUNT_KEY,
    }
    key = mapping.get(account_arg.lower())
    if key is None:
        sys.exit(f"[ERROR] 未知账户 '{account_arg}'，支持: us / cn")
    return key


def is_cn_ticker(ticker: str) -> bool:
    return ticker.isdigit() and len(ticker) == 6


def yf_cn_ticker(ticker: str) -> str:
    if ticker.startswith("6"):
        return ticker + ".SS"
    return ticker + ".SZ"  # 0开头 / 3开头 → 深交所


def fetch_price(ticker: str, account_key: str) -> float:
    """获取实时价格（含重试）；失败则 sys.exit。"""
    import time
    if account_key == CN_ACCOUNT_KEY:
        yf_sym = yf_cn_ticker(ticker)
    else:
        # Apply OTC remapping (e.g. SPUT → SRUUF)
        yf_sym = YF_TICKER_MAP.get(ticker.upper(), ticker.upper())

    retries = 3
    last_error = ""
    for attempt in range(retries):
        try:
            t = yf.Ticker(yf_sym)
            info = t.fast_info
            price = info.last_price
            if price is None or price <= 0:
                # 尝试 history fallback
                hist = t.history(period="1d", auto_adjust=True)
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
            if price and price > 0:
                return round(float(price), 4)
            last_error = "no valid price"
        except Exception as e:
            last_error = str(e)
        if attempt < retries - 1:
            time.sleep(1.5)

    sys.exit(f"[ERROR] 无法获取 {ticker} ({yf_sym}) 的有效价格（{last_error}），交易取消。")


def find_position(positions: list, ticker: str) -> tuple[int, dict | None]:
    """返回 (index, position_dict)，未找到返回 (-1, None)。"""
    for i, pos in enumerate(positions):
        if pos.get("ticker") == ticker:
            return i, pos
    return -1, None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_buy(account: dict, account_key: str, ticker: str, shares: int, price: float,
                 bear_case_downside: float | None = None):
    """
    Validate a buy order. Raises sys.exit on failure.
    bear_case_downside: if provided, checked against -0.20 threshold (rule: >20% downside = no position).
    """
    currency = account["currency"]
    cost = shares * price
    cash = account["cash"]

    # Bear case >20% downside check (硬规则：不建仓)
    if bear_case_downside is not None and bear_case_downside < -0.20:
        sys.exit(
            f"[ERROR] {ticker} Bear case downside = {bear_case_downside:.1%} > 20%。"
            f"硬规则：bear case >20% downside 不建仓。交易取消。"
        )

    # 现金检查
    if cost > cash:
        sym = "¥" if currency == "CNY" else "$"
        sys.exit(
            f"[ERROR] 现金不足。需要 {sym}{cost:,.2f}，可用 {sym}{cash:,.2f}。交易取消。"
        )

    # 现金≥20%检查（买入后）
    total_assets = account.get("total_assets", 0)
    if total_assets > 0:
        remaining_cash = cash - cost
        cash_pct_after = remaining_cash / total_assets
        if cash_pct_after < 0.20:
            sym = "¥" if currency == "CNY" else "$"
            print(
                f"[WARN] 买入后现金将降至 {cash_pct_after:.1%}（低于20%下限）。"
                f"剩余: {sym}{remaining_cash:,.2f}"
            )
            # Warning only, not hard stop — agent decides

    # 15% 上限检查
    if total_assets > 0:
        _, existing = find_position(account["positions"], ticker)
        existing_value = 0.0
        if existing:
            existing_value = existing.get("shares", 0) * price
        new_value = existing_value + cost
        pct = new_value / total_assets
        if pct > MAX_SINGLE_POSITION_PCT:
            sys.exit(
                f"[ERROR] 买入后 {ticker} 持仓占比将达 {pct:.1%}，超过 15% 上限。"
                f"（现有价值: {existing_value:,.2f}，本次买入: {cost:,.2f}，总资产: {total_assets:,.2f}）\n交易取消。"
            )

    # A股整数倍检查
    if account_key == CN_ACCOUNT_KEY:
        if shares % CN_LOT_SIZE != 0:
            sys.exit(
                f"[ERROR] A股交易必须为 {CN_LOT_SIZE} 股整数倍，收到 {shares} 股。交易取消。"
            )


def validate_sell(account: dict, ticker: str, shares: int, sell_all: bool) -> int:
    """验证卖出，返回实际卖出股数。"""
    _, pos = find_position(account["positions"], ticker)
    if pos is None:
        sys.exit(f"[ERROR] 账户中没有 {ticker} 的持仓，无法卖出。交易取消。")
    if pos.get("instrument_type") == "call_option":
        sys.exit(f"[ERROR] {ticker} 是期权，跳过（不支持自动执行期权交易）。")

    held = pos.get("shares", 0)
    if sell_all:
        return held
    if shares > held:
        sys.exit(
            f"[ERROR] 持仓不足。持有 {held} 股，尝试卖出 {shares} 股。交易取消。"
        )
    return shares


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

def execute_buy(state: dict, account_key: str, ticker: str, shares: int, price: float, reason: str):
    account = state["accounts"][account_key]
    currency = account["currency"]
    cost = round(shares * price, 4)

    idx, existing = find_position(account["positions"], ticker)
    if existing is None:
        # 新建持仓
        new_pos = {
            "ticker": ticker,
            "shares": shares,
            "avg_cost": price,
            "instrument_type": "stock",
            "entry_date": now_iso(),
            "last_updated": now_iso(),
        }
        account["positions"].append(new_pos)
        print(f"  [+] 新建持仓: {ticker}")
    else:
        # 加权平均更新 avg_cost
        old_shares = existing["shares"]
        old_cost = existing["avg_cost"]
        new_shares = old_shares + shares
        new_avg = round((old_shares * old_cost + shares * price) / new_shares, 6)
        account["positions"][idx]["shares"] = new_shares
        account["positions"][idx]["avg_cost"] = new_avg
        account["positions"][idx]["last_updated"] = now_iso()
        print(f"  [+] 加仓: {ticker}，新持仓 {new_shares} 股，新均成本 {new_avg:.4f}")

    account["cash"] = round(account["cash"] - cost, 4)
    account["trade_count"] = account.get("trade_count", 0) + 1
    _update_total_assets(account, price, ticker)

    trade_entry = {
        "id": f"TRD-{len(state['trade_log']) + 1:04d}",
        "timestamp": now_iso(),
        "action": "buy",
        "account": account_key,
        "ticker": ticker,
        "shares": shares,
        "price": price,
        "value": cost,
        "currency": currency,
        "reason": reason,
    }
    state["trade_log"].append(trade_entry)
    state["_meta"]["last_updated"] = now_iso()
    state["_meta"]["update_trigger"] = "execute_trade"

    sym = "¥" if currency == "CNY" else "$"
    print(f"\n{'='*50}")
    print(f"  交易确认 — 买入")
    print(f"  账户:   {account_key}")
    print(f"  标的:   {ticker}")
    print(f"  股数:   {shares:,}")
    print(f"  成交价: {sym}{price:,.4f}")
    print(f"  成交额: {sym}{cost:,.2f}")
    print(f"  剩余现金: {sym}{account['cash']:,.2f}")
    print(f"  交易ID: {trade_entry['id']}")
    print(f"  备注:   {reason}")
    print(f"{'='*50}\n")


def execute_sell(state: dict, account_key: str, ticker: str, actual_shares: int, price: float, reason: str):
    account = state["accounts"][account_key]
    currency = account["currency"]
    proceeds = round(actual_shares * price, 4)

    idx, pos = find_position(account["positions"], ticker)
    avg_cost = pos["avg_cost"]
    realized_pnl = round((price - avg_cost) * actual_shares, 4)

    remaining = pos["shares"] - actual_shares
    if remaining <= 0:
        # 清空持仓
        account["positions"].pop(idx)
        print(f"  [-] 清空持仓: {ticker}")
    else:
        account["positions"][idx]["shares"] = remaining
        account["positions"][idx]["last_updated"] = now_iso()
        print(f"  [-] 减仓: {ticker}，剩余 {remaining} 股")

    account["cash"] = round(account["cash"] + proceeds, 4)
    account["realized_pnl"] = round(account.get("realized_pnl", 0) + realized_pnl, 4)
    account["trade_count"] = account.get("trade_count", 0) + 1
    _update_total_assets(account, price, ticker)

    trade_entry = {
        "id": f"TRD-{len(state['trade_log']) + 1:04d}",
        "timestamp": now_iso(),
        "action": "sell",
        "account": account_key,
        "ticker": ticker,
        "shares": actual_shares,
        "price": price,
        "value": proceeds,
        "currency": currency,
        "realized_pnl": realized_pnl,
        "reason": reason,
    }
    state["trade_log"].append(trade_entry)
    state["_meta"]["last_updated"] = now_iso()
    state["_meta"]["update_trigger"] = "execute_trade"

    sym = "¥" if currency == "CNY" else "$"
    pnl_sign = "+" if realized_pnl >= 0 else ""
    print(f"\n{'='*50}")
    print(f"  交易确认 — 卖出")
    print(f"  账户:     {account_key}")
    print(f"  标的:     {ticker}")
    print(f"  股数:     {actual_shares:,}")
    print(f"  成交价:   {sym}{price:,.4f}")
    print(f"  成交额:   {sym}{proceeds:,.2f}")
    print(f"  均成本:   {sym}{avg_cost:,.4f}")
    print(f"  已实现PnL: {sym}{pnl_sign}{realized_pnl:,.2f}")
    print(f"  剩余现金: {sym}{account['cash']:,.2f}")
    print(f"  交易ID:   {trade_entry['id']}")
    print(f"  备注:     {reason}")
    print(f"{'='*50}\n")


def execute_short(state: dict, account_key: str, ticker: str, shares: int, price: float, reason: str):
    account = state["accounts"][account_key]
    currency = account["currency"]
    proceeds = round(shares * price, 4)

    if account_key == CN_ACCOUNT_KEY:
        sys.exit("[ERROR] A股不支持做空。交易取消。")

    gross = _calc_gross_exposure(account, price, ticker)
    new_short_value = shares * price
    if gross + new_short_value > MAX_GROSS_EXPOSURE:
        sys.exit(
            f"[ERROR] 做空后总敞口将达 ${gross + new_short_value:,.0f}，"
            f"超过 ${MAX_GROSS_EXPOSURE:,.0f} 上限。交易取消。"
        )

    total_assets = account["total_assets"]
    if total_assets > 0:
        if "short_positions" not in account:
            account["short_positions"] = []
        _, existing = find_position(account["short_positions"], ticker)
        existing_value = existing["shares"] * price if existing else 0
        if (existing_value + new_short_value) / total_assets > MAX_SHORT_POSITION_PCT:
            sys.exit(
                f"[ERROR] {ticker} 空头将占 {(existing_value + new_short_value) / total_assets:.1%}，"
                f"超过 10% 上限。交易取消。"
            )

    if "short_positions" not in account:
        account["short_positions"] = []

    idx, existing = find_position(account["short_positions"], ticker)
    if existing is None:
        new_pos = {
            "ticker": ticker,
            "shares": shares,
            "entry_price": price,
            "instrument_type": "short",
            "entry_date": now_iso(),
            "stop_loss": round(price * (1 + SHORT_STOP_LOSS_PCT), 2),
            "last_updated": now_iso(),
        }
        account["short_positions"].append(new_pos)
        print(f"  [S] 新建空头: {ticker}")
    else:
        old_shares = existing["shares"]
        old_price = existing["entry_price"]
        new_shares = old_shares + shares
        new_avg = round((old_shares * old_price + shares * price) / new_shares, 6)
        account["short_positions"][idx]["shares"] = new_shares
        account["short_positions"][idx]["entry_price"] = new_avg
        account["short_positions"][idx]["stop_loss"] = round(new_avg * (1 + SHORT_STOP_LOSS_PCT), 2)
        account["short_positions"][idx]["last_updated"] = now_iso()
        print(f"  [S] 加空: {ticker}，新持仓 {new_shares} 股，新均价 {new_avg:.4f}")

    account["trade_count"] = account.get("trade_count", 0) + 1
    _update_total_assets(account, price, ticker)

    trade_entry = {
        "id": f"TRD-{len(state['trade_log']) + 1:04d}",
        "timestamp": now_iso(),
        "action": "short",
        "account": account_key,
        "ticker": ticker,
        "shares": shares,
        "price": price,
        "value": proceeds,
        "currency": currency,
        "reason": reason,
    }
    state["trade_log"].append(trade_entry)
    state["_meta"]["last_updated"] = now_iso()
    state["_meta"]["update_trigger"] = "execute_trade"

    print(f"\n{'='*50}")
    print(f"  交易确认 — 做空")
    print(f"  标的:     {ticker}")
    print(f"  股数:     {shares:,}")
    print(f"  开仓价:   ${price:,.4f}")
    print(f"  敞口:     ${proceeds:,.2f}")
    print(f"  止损:     ${round(price * (1 + SHORT_STOP_LOSS_PCT), 2):,.2f} (+{SHORT_STOP_LOSS_PCT:.0%})")
    print(f"  交易ID:   {trade_entry['id']}")
    print(f"  备注:     {reason}")
    print(f"{'='*50}\n")


def execute_cover(state: dict, account_key: str, ticker: str, shares: int, price: float, reason: str, cover_all: bool = False):
    account = state["accounts"][account_key]
    currency = account["currency"]

    if "short_positions" not in account:
        sys.exit(f"[ERROR] 账户中没有空头持仓。交易取消。")

    idx, pos = find_position(account["short_positions"], ticker)
    if pos is None:
        sys.exit(f"[ERROR] 账户中没有 {ticker} 的空头持仓。交易取消。")

    held = pos["shares"]
    actual_shares = held if cover_all else shares
    if actual_shares > held:
        sys.exit(f"[ERROR] 空头持仓不足。持有 {held} 股空头，尝试平 {actual_shares} 股。交易取消。")

    entry_price = pos["entry_price"]
    realized_pnl = round((entry_price - price) * actual_shares, 4)

    remaining = held - actual_shares
    if remaining <= 0:
        account["short_positions"].pop(idx)
        print(f"  [C] 平空完毕: {ticker}")
    else:
        account["short_positions"][idx]["shares"] = remaining
        account["short_positions"][idx]["last_updated"] = now_iso()
        print(f"  [C] 部分平空: {ticker}，剩余空头 {remaining} 股")

    account["realized_pnl"] = round(account.get("realized_pnl", 0) + realized_pnl, 4)
    account["trade_count"] = account.get("trade_count", 0) + 1
    _update_total_assets(account, price, ticker)

    trade_entry = {
        "id": f"TRD-{len(state['trade_log']) + 1:04d}",
        "timestamp": now_iso(),
        "action": "cover",
        "account": account_key,
        "ticker": ticker,
        "shares": actual_shares,
        "price": price,
        "value": round(actual_shares * price, 4),
        "currency": currency,
        "realized_pnl": realized_pnl,
        "reason": reason,
    }
    state["trade_log"].append(trade_entry)
    state["_meta"]["last_updated"] = now_iso()
    state["_meta"]["update_trigger"] = "execute_trade"

    pnl_sign = "+" if realized_pnl >= 0 else ""
    print(f"\n{'='*50}")
    print(f"  交易确认 — 平空")
    print(f"  标的:     {ticker}")
    print(f"  股数:     {actual_shares:,}")
    print(f"  平仓价:   ${price:,.4f}")
    print(f"  开仓均价: ${entry_price:,.4f}")
    print(f"  已实现PnL: ${pnl_sign}{realized_pnl:,.2f}")
    print(f"  交易ID:   {trade_entry['id']}")
    print(f"  备注:     {reason}")
    print(f"{'='*50}\n")


def _calc_gross_exposure(account: dict, last_price: float = 0, last_ticker: str = "") -> float:
    long_value = 0.0
    for pos in account.get("positions", []):
        if pos.get("instrument_type") == "call_option":
            continue
        p = last_price if pos["ticker"] == last_ticker else pos.get("avg_cost", 0)
        long_value += pos["shares"] * p
    short_value = 0.0
    for pos in account.get("short_positions", []):
        p = last_price if pos["ticker"] == last_ticker else pos.get("entry_price", 0)
        short_value += pos["shares"] * p
    return long_value + short_value


def _update_total_assets(account: dict, last_price: float, last_ticker: str):
    positions_value = 0.0
    for pos in account.get("positions", []):
        if pos.get("instrument_type") == "call_option":
            continue
        if pos["ticker"] == last_ticker:
            positions_value += pos["shares"] * last_price
        else:
            positions_value += pos["shares"] * pos.get("avg_cost", 0)
    short_unrealized = 0.0
    for pos in account.get("short_positions", []):
        if pos["ticker"] == last_ticker:
            short_unrealized += (pos["entry_price"] - last_price) * pos["shares"]
    account["total_assets"] = round(account["cash"] + positions_value + short_unrealized, 4)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="模拟盘交易执行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="action", required=True)

    # --- buy ---
    buy_p = sub.add_parser("buy", help="买入")
    buy_p.add_argument("--account", required=True, help="账户: us / cn")
    buy_p.add_argument("--ticker", required=True, help="股票代码，A股用6位数字")
    buy_p.add_argument("--shares", required=True, type=int, help="买入股数")
    buy_p.add_argument("--reason", required=True, help="交易理由")
    buy_p.add_argument("--bear-case-downside", type=float, default=None,
                       help="Bear case downside (负数, 如 -0.15 表示-15%)")

    # --- sell ---
    sell_p = sub.add_parser("sell", help="卖出")
    sell_p.add_argument("--account", required=True, help="账户: us / cn")
    sell_p.add_argument("--ticker", required=True, help="股票代码")
    shares_grp = sell_p.add_mutually_exclusive_group(required=True)
    shares_grp.add_argument("--shares", type=int, help="卖出股数")
    shares_grp.add_argument("--all", dest="sell_all", action="store_true", help="卖出全部")
    sell_p.add_argument("--reason", required=True, help="交易理由")

    # --- short ---
    short_p = sub.add_parser("short", help="做空(仅美股)")
    short_p.add_argument("--account", required=True, help="账户: us")
    short_p.add_argument("--ticker", required=True, help="股票代码")
    short_p.add_argument("--shares", required=True, type=int, help="做空股数")
    short_p.add_argument("--reason", required=True, help="做空理由(含thesis)")

    # --- cover ---
    cover_p = sub.add_parser("cover", help="平空")
    cover_p.add_argument("--account", required=True, help="账户: us")
    cover_p.add_argument("--ticker", required=True, help="股票代码")
    cover_shares_grp = cover_p.add_mutually_exclusive_group(required=True)
    cover_shares_grp.add_argument("--shares", type=int, help="平仓股数")
    cover_shares_grp.add_argument("--all", dest="cover_all", action="store_true", help="全部平仓")
    cover_p.add_argument("--reason", required=True, help="平仓理由")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    account_key = get_account_key(args.account)
    ticker = args.ticker.upper() if not args.ticker.isdigit() else args.ticker

    # 期权跳过
    if "CALL" in ticker or "PUT" in ticker:
        print(f"[SKIP] {ticker} 识别为期权，跳过自动执行。")
        sys.exit(0)

    print(f"[INFO] 获取 {ticker} 实时价格...")
    price = fetch_price(ticker, account_key)
    print(f"[INFO] 成交价: {price}")

    # 加载状态（在价格获取成功后再加载，减少锁定时间）
    try:
        state = load_portfolio()
    except Exception as e:
        sys.exit(f"[ERROR] 无法读取 portfolio_state.json: {e}")

    account = state["accounts"][account_key]

    if args.action == "buy":
        bear_case = getattr(args, "bear_case_downside", None)
        validate_buy(account, account_key, ticker, args.shares, price, bear_case)
        execute_buy(state, account_key, ticker, args.shares, price, args.reason)

    elif args.action == "sell":
        sell_all = getattr(args, "sell_all", False)
        sell_shares = getattr(args, "shares", None) or 0
        actual_shares = validate_sell(account, ticker, sell_shares, sell_all)
        execute_sell(state, account_key, ticker, actual_shares, price, args.reason)

    elif args.action == "short":
        execute_short(state, account_key, ticker, args.shares, price, args.reason)

    elif args.action == "cover":
        cover_all = getattr(args, "cover_all", False)
        cover_shares = getattr(args, "shares", None) or 0
        execute_cover(state, account_key, ticker, cover_shares, price, args.reason, cover_all)

    try:
        save_portfolio_atomic(state)
        print(f"[OK] portfolio_state.json 已更新。")
    except RuntimeError as e:
        print(f"[CRITICAL] {e}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print("[CRITICAL] 未预期错误，交易未执行:")
        traceback.print_exc()
        sys.exit(2)
