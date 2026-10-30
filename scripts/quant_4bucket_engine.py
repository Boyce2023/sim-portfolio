#!/opt/homebrew/bin/python3.13
"""A股四分仓纯机械自动交易与日终对账引擎 (quant_4bucket_engine.py)

职责（对应 strategy_astock.md 第二节 & data/quant_4bucket_ledger.json）：
  1. open      (09:26)       : 周一承接候选(-2%~+1%) + 第3桶(三连跌停纯超跌撬板) + 第4桶(五板手册/高标断板真阳反包/唯一最高标独苗)
  2. intraday  (09:35~14:50) : T+1已解锁持仓实时监控止盈（第1/2桶 +4.0%，第3桶/反包 +5.0%，五板/独苗 10日100%异动93%提前线）
  3. tail      (14:55/14:57) : 14:55 到期平仓(T+5满5日收盘卖 / 五板第4天收盘卖 / 独苗断板收盘卖)；14:57 全市场5200+只扫描第1桶与第2桶尾盘真阳线自动买入
  4. reconcile (15:08)       : 日终信号与成交零漏单核验 + 持仓收盘市值与沪深300(sh000300)基准净超额同步 + 落盘 data/eod_done/YYYYMMDD
  5. status                  : 打印四桶独立台账、胜率、盈亏与当前持仓
  6. backfill_1026_1029      : 严格按当时时点可见数据(前视镜口径、零事后挑股)补齐 2026-10-26 至 2026-10-29 全部触发交易与净值快照
"""
from __future__ import annotations

import os as _np_os
_np_os.environ.setdefault("NO_PROXY", "*")
_np_os.environ.setdefault("no_proxy", "*")

import argparse
import concurrent.futures
import datetime as dt
import json
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import astock_intraday_check as AIC
import astock_rules as AR
import portfolio_io
from nav_calc import calc_nav, apply_nav

def _sync_account_nav(acc: dict) -> None:
    for pos in acc.get("positions", []):
        sh = int(pos.get("shares", 0))
        cp = float(pos.get("current_price") or pos.get("avg_cost") or 0.0)
        ac = float(pos.get("avg_cost") or 0.0)
        mv = round(sh * cp, 2)
        cb = round(sh * ac, 2)
        pos["market_value"] = mv
        pos["cost_basis"] = cb
        pos["unrealized_pnl"] = round(mv - cb, 2)
        pos["unrealized_pnl_pct"] = round((cp / ac - 1.0) * 100.0, 2) if ac > 0 else 0.0
    apply_nav(acc, calc_nav(acc), initial_capital=INITIAL_CAPITAL_CN)

TZ_CN = dt.timezone(dt.timedelta(hours=8))
SSL_CTX = ssl._create_unverified_context()
HEADERS = {"User-Agent": "Mozilla/5.0"}

LEDGER_PATH = ROOT / "data" / "quant_4bucket_ledger.json"
PARQUET_PATH = ROOT / "data" / "cn_hk_price_db" / "a_daily.parquet"
UNIVERSE_PATH = ROOT / "data" / "cn_hk_price_db" / "universe_codes.json"
LOCKUP_CACHE_PATH = ROOT / "data" / "cn_hk_price_db" / "sh_lockup_cache.json"
ZT_POOL_DIR = ROOT / "data" / "zt_pool"
EOD_DONE_DIR = ROOT / "data" / "eod_done"
AUDIT_TRAIL_DIR = ROOT / "audit-trail"
SIGNAL_LOG_PATH = ROOT / "data" / "quant_4bucket_signals.jsonl"
CALENDAR_PATH = ROOT / "market_calendar.json"

DAY1_HS300_BASE = 4833.52  # 2026-05-18 组合建账基准日沪深300收盘点位
INITIAL_CAPITAL_CN = 10_000_000.0
RED_FLAG_KEYWORDS = ("立案", "退市风险警示", "终止上市", "暂停上市", "重大违法强制退市", "全面停产")


def now_cn() -> dt.datetime:
    return dt.datetime.now(TZ_CN)


def send_feishu(msg: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"[DRY_RUN 飞书不发] {msg}")
        return
    try:
        sh = os.path.expanduser("~/.claude/session-remote/fs-reply.sh")
        r = subprocess.run(["bash", sh, msg], capture_output=True, text=True, timeout=25)
        if r.returncode != 0:
            print(f"[quant_4bucket] ⛔ 飞书发送失败 rc={r.returncode}: {(r.stderr or '')[:160]}", file=sys.stderr)
    except Exception as e:
        print(f"[quant_4bucket] ⛔ 飞书异常: {e}", file=sys.stderr)


def is_trading_day(d: dt.date | None = None) -> bool:
    d = d or now_cn().date()
    if d.weekday() >= 5:
        return False
    if CALENDAR_PATH.exists():
        cal = json.load(open(CALENDAR_PATH, encoding="utf-8"))
        closed = set(cal.get("trading_days_by_market", {}).get("cn_closed_dates", []))
        if d.isoformat() in closed:
            return False
    return True


def load_ledger() -> dict:
    with open(LEDGER_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_ledger(ledger: dict) -> None:
    ledger["updated_at"] = now_cn().isoformat(timespec="seconds")
    fd, tmp_path = tempfile.mkstemp(dir=LEDGER_PATH.parent, suffix=".tmp", prefix="ledger_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(ledger, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, LEDGER_PATH)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def next_trade_id(state: dict) -> str:
    mx = len(state.get("trade_log", []))
    for t in state.get("trade_log", []):
        tid = str(t.get("id", ""))
        if tid.startswith("TRD-"):
            try:
                mx = max(mx, int(tid.split("-")[1]))
            except ValueError:
                pass
    return f"TRD-{mx + 1:04d}"


def market_prefix(code: str) -> str:
    c = str(code).zfill(6)
    if c.startswith(("6", "5")):
        return "sh"
    if c.startswith(("0", "3", "1")):
        return "sz"
    return "bj"


def fetch_quotes_batch(codes: list[str], include_indices: bool = False) -> dict[str, dict]:
    syms = [market_prefix(c) + str(c).zfill(6) for c in codes]
    if include_indices:
        syms.extend(["sh000300", "sh000001", "sz399001"])
    chunks = [syms[i : i + 80] for i in range(0, len(syms), 80)]
    out: dict[str, dict] = {}

    def _pull(chunk: list[str]) -> list[str]:
        url = "http://qt.gtimg.cn/q=" + ",".join(chunk)
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, headers=HEADERS)
                raw = urllib.request.urlopen(req, timeout=4.0).read().decode("gbk", "ignore")
                return raw.strip().splitlines()
            except Exception:
                if attempt == 1:
                    return []
        return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for lines in ex.map(_pull, chunks):
            for ln in lines:
                if "=" not in ln or "~" not in ln:
                    continue
                lhs, rhs = ln.split("=", 1)
                sym = lhs.split("_")[-1].strip()
                f = rhs.strip('";').split("~")
                if len(f) < 49:
                    continue
                try:
                    prev_c = float(f[4] or 0)
                    now_p = float(f[3] or 0)
                    open_p = float(f[5] or 0)
                    high_p = float(f[33] or 0)
                    low_p = float(f[34] or 0)
                except ValueError:
                    continue
                if prev_c <= 0 and now_p <= 0:
                    continue
                eff_now = now_p if now_p > 0 else prev_c
                open_pct = ((open_p / prev_c - 1.0) * 100.0) if (open_p > 0 and prev_c > 0) else 0.0
                key = sym if sym in ("sh000300", "sh000001", "sz399001") else str(f[2]).zfill(6)
                out[key] = {
                    "symbol": sym,
                    "code": str(f[2]).zfill(6),
                    "name": f[1].strip(),
                    "now": eff_now,
                    "prev_close": prev_c,
                    "open": open_p,
                    "open_pct": round(open_pct, 2),
                    "pct": float(f[32] or 0),
                    "high": high_p,
                    "low": low_p,
                    "vol_lots": float(f[6] or 0),
                    "bid1": float(f[9] or 0),
                    "bid1_vol": int(float(f[10] or 0)),
                    "ask1": float(f[19] or 0),
                    "ask1_vol": int(float(f[20] or 0)),
                    "turn_pct": float(f[38] or 0),
                    "float_mcap_yi": float(f[44] or 0),
                    "total_mcap_yi": float(f[45] or 0),
                    "zt_price": float(f[47] or 0),
                    "dt_price": float(f[48] or 0),
                    "raw_time": str(f[30] or ""),
                }
    return out


def load_universe_codes() -> list[str]:
    if UNIVERSE_PATH.exists():
        u = json.load(open(UNIVERSE_PATH, encoding="utf-8"))
        if isinstance(u, dict) and "codes" in u and isinstance(u["codes"], list):
            return sorted(str(x)[:6].zfill(6) for x in u["codes"] if str(x)[:6].isdigit())
        if isinstance(u, dict):
            return sorted(str(k).zfill(6) for k in u.keys() if str(k)[:6].isdigit())
        if isinstance(u, list):
            return sorted(str(x["code"] if isinstance(x, dict) else x)[:6].zfill(6) for x in u)
    df = pd.read_parquet(PARQUET_PATH, columns=["ticker"])
    return sorted(df["ticker"].astype(str).str[:6].unique().tolist())


def fetch_kline_bars(code: str, start: str = "2026-09-10", end: str = "2026-12-31", count: int = 35) -> list[dict]:
    sym = market_prefix(code) + str(code).zfill(6) if not code.startswith(("sh", "sz", "bj")) else code
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,{start},{end},{count},"
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            raw = json.loads(urllib.request.urlopen(req, timeout=6.0, context=SSL_CTX).read().decode("utf-8", "ignore"))
            kdata = (raw.get("data") or {}).get(sym) or {}
            rows = kdata.get("day") or kdata.get("qfqday") or []
            if rows:
                return [
                    {
                        "date": str(r[0]),
                        "open": float(r[1]),
                        "close": float(r[2]),
                        "high": float(r[3]),
                        "low": float(r[4]),
                        "vol_lots": float(r[5]),
                    }
                    for r in rows
                ]
        except Exception:
            if attempt == 0:
                time.sleep(0.3)
    # 备用源：新浪日K直连（防腾讯 fqkline 偶发 HTTP 501）
    s_url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData?symbol={sym}&scale=240&ma=no&datalen={max(count, 45)}"
    req2 = urllib.request.Request(s_url, headers=HEADERS)
    s_txt = urllib.request.urlopen(req2, timeout=6.0, context=SSL_CTX).read().decode("utf-8", "ignore")
    i, j = s_txt.find("["), s_txt.rfind("]")
    s_rows = json.loads(s_txt[i : j + 1]) if (i >= 0 and j > i) else []
    out = [
        {
            "date": str(r["day"]),
            "open": float(r["open"]),
            "close": float(r["close"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "vol_lots": float(r.get("volume", 0)) / 100.0,
        }
        for r in s_rows
        if start <= str(r["day"]) <= end
    ]
    return out[-count:]


def get_trading_days_recent(count: int = 40) -> list[str]:
    rows = fetch_kline_bars("sh000300", start="2026-08-15", end="2026-12-31", count=count)
    days = [r["date"] for r in rows]
    today_s = now_cn().strftime("%Y-%m-%d")
    if is_trading_day(now_cn().date()) and (now_cn().hour * 60 + now_cn().minute >= 565) and today_s not in days:
        days.append(today_s)
    return days


def check_announcement_red_flags(code: str, as_of_date: str | None = None) -> tuple[bool, list[str]]:
    """返回 (passed, red_flag_titles)。若存在立案、退市风险警示、终止上市、全面停产则拦截。"""
    url = (
        f"https://np-anotice-stock.eastmoney.com/api/security/ann?"
        f"sr=-1&page_size=25&page_index=1&ann_type=A&stock_list={code}"
    )
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        data = json.loads(urllib.request.urlopen(req, timeout=4.0, context=SSL_CTX).read().decode("utf-8", "ignore"))
        items = (data.get("data") or {}).get("list") or []
    except Exception:
        return True, []
    cutoff = (dt.date.fromisoformat(as_of_date) if as_of_date else now_cn().date()) - dt.timedelta(days=90)
    hits = []
    for it in items:
        nd = str(it.get("notice_date") or "")[:10]
        if as_of_date and nd > as_of_date:
            continue
        if nd and nd < cutoff.isoformat():
            continue
        title = str(it.get("title") or "")
        if any(kw in title for kw in RED_FLAG_KEYWORDS):
            # 排除常规"不触及退市风险警示"或"撤销退市风险警示"正面公告
            if any(ok_w in title for ok_w in ("不触及", "撤销", "解除", "恢复生产", "结案")):
                continue
            hits.append(f"{nd}:{title}")
    return (len(hits) == 0), hits


def get_lock10_pct(code: str) -> float:
    """获取前十流通股东合计持股比例(%)，优先查本地缓存，缺失则实时查东财最新财报期。"""
    cache = {}
    if LOCKUP_CACHE_PATH.exists():
        try:
            cache = json.load(open(LOCKUP_CACHE_PATH, encoding="utf-8"))
        except Exception:
            cache = {}
    if code in cache and cache[code].get("lock_top10"):
        return float(cache[code]["lock_top10"])
    try:
        import akshare as ak
        pfx = "sh" if code.startswith("6") else "sz"
        for rep_dt in ("20260930", "20260630", "20260331"):
            try:
                df = ak.stock_gdfx_free_top_10_em(symbol=f"{pfx}{code}", date=rep_dt)
                cols = [c for c in df.columns if "比例" in c]
                if cols and not df.empty:
                    val = float(df[cols[0]].astype(float).sum())
                    if val > 0:
                        return round(val, 2)
            except Exception:
                continue
    except Exception:
        pass
    return 0.0


def calc_order_shares(code: str, budget_cny: float, price: float) -> int:
    if price <= 0 or budget_cny <= 0:
        return 0
    brd = AR.board(code)
    step = 200 if brd == "star" else 100
    _, min_qty, cap_limit, _ = AR.QTY_RULE.get(brd, (100, 100, 1_000_000, 1_000_000))
    raw_sh = int(budget_cny / (price * 1.0005) // step) * step
    sh = min(raw_sh, cap_limit)
    # 若限价单单笔上限截断后仍不够(如科创板10万股上限)，严格遵守单笔申报上限
    while sh >= min_qty:
        val = round(sh * price, 2)
        fee = round(AR.fees(val, "buy")["total"], 2)
        if val + fee <= budget_cny + 1e-6:
            return sh
        sh -= step
    return 0


def count_hold_days(entry_date: str, current_date: str, trading_days: list[str]) -> int:
    """计算买入日之后经过了几个完整交易日（买入当日=0，次一交易日=1）。"""
    return sum(1 for d in trading_days if entry_date < d <= current_date)


def _write_audit_file(trade_entry: dict, pre_nav: float, post_nav: float, pre_cash_pct: float, post_cash_pct: float, pos_cnt: int) -> None:
    AUDIT_TRAIL_DIR.mkdir(parents=True, exist_ok=True)
    tid_num = trade_entry["id"].replace("TRD-", "")
    fn = f"{trade_entry['date']}-{trade_entry['ticker']}-{trade_entry['action']}-{tid_num}.json"
    doc = {
        "trade_id": trade_entry["id"],
        "timestamp": trade_entry["timestamp"],
        "ticker": trade_entry["ticker"],
        "name": trade_entry.get("name", trade_entry["ticker"]),
        "action": trade_entry["action"],
        "account": "a_share",
        "shares": trade_entry["shares"],
        "price": trade_entry["price"],
        "value": trade_entry["value"],
        "fee": trade_entry.get("fee", 0.0),
        "currency": "CNY",
        "realized_pnl": trade_entry.get("realized_pnl"),
        "reason": trade_entry["reason"],
        "decision_chain": {
            "trigger": {
                "type": "mechanical_quant_4bucket",
                "description": trade_entry["reason"],
                "source": "quant_4bucket_engine",
            },
            "risk_check": {
                "pre_trade_cash_pct": round(pre_cash_pct, 2),
                "post_trade_cash_pct": round(post_cash_pct, 2),
                "single_position_limit_ok": True,
            },
            "final_decision": {
                "approved": True,
                "approver": "quant_4bucket_engine",
                "notes": trade_entry["reason"],
            },
        },
        "pre_trade_state": {
            "account_cash_pct": round(pre_cash_pct, 2),
            "account_nav": round(pre_nav, 2),
        },
        "post_trade_state": {
            "account_cash_pct": round(post_cash_pct, 2),
            "account_total_positions": pos_cnt,
            "account_nav": round(post_nav, 2),
            "realized_pnl": trade_entry.get("realized_pnl"),
        },
    }
    (AUDIT_TRAIL_DIR / fn).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def book_buy(
    state: dict,
    ledger: dict,
    bucket_key: str,
    code: str,
    name: str,
    shares: int,
    price: float,
    ts_iso: str,
    reason: str,
    meta: dict,
    write_audit: bool = True,
) -> dict:
    acc = state["accounts"]["a_share"]
    bkt = ledger["buckets"][bucket_key]
    _sync_account_nav(acc)
    pre_nav = acc["total_assets"]
    pre_cash_pct = acc.get("cash_pct", 0.0) * 100.0

    val = round(shares * price, 2)
    fd = AR.fees(val, "buy")
    fee = round(fd["total"], 2)
    if val + fee > bkt["cash"] + 0.05:
        raise RuntimeError(f"[{bucket_key}] 桶内现金不足: 需 {val + fee:.2f}, 实有 {bkt['cash']:.2f}")

    bkt["cash"] = round(bkt["cash"] - val - fee, 4)
    acc["cash"] = round(acc["cash"] - val - fee, 4)
    acc["trade_count"] = int(acc.get("trade_count", 0)) + 1

    # 更新 SSOT 持仓
    existing = next((p for p in acc["positions"] if str(p["ticker"]).zfill(6) == code), None)
    if existing:
        tot_sh = existing["shares"] + shares
        existing["avg_cost"] = round((existing["shares"] * existing["avg_cost"] + val) / tot_sh, 4)
        existing["shares"] = tot_sh
        existing["current_price"] = price
        existing["last_updated"] = ts_iso
    else:
        acc["positions"].append(
            {
                "ticker": code,
                "name": name,
                "shares": shares,
                "avg_cost": price,
                "instrument_type": "stock",
                "entry_date": ts_iso,
                "last_updated": ts_iso,
                "book": "quant_4bucket",
                "bucket": bucket_key,
                "stop_loss": 0.0,
                "stop_loss_note": f"四分仓机械时限退出({bucket_key})",
                "current_price": price,
                "prev_close": meta.get("prev_close", price),
                "change_pct": 0.0,
                "peak_price": price,
            }
        )

    _sync_account_nav(acc)
    post_nav = acc["total_assets"]
    post_cash_pct = acc.get("cash_pct", 0.0) * 100.0

    tid = next_trade_id(state)
    t_entry = {
        "id": tid,
        "timestamp": ts_iso,
        "date": ts_iso[:10],
        "action": "buy",
        "account": "a_share",
        "bucket": bucket_key,
        "ticker": code,
        "name": name,
        "shares": shares,
        "price": price,
        "value": val,
        "fee": fee,
        "currency": "CNY",
        "reason": reason,
    }
    state["trade_log"].append(t_entry)
    state.setdefault("_meta", {})["last_updated"] = ts_iso

    pos_rec = {
        "trade_id": tid,
        "code": code,
        "name": name,
        "shares": shares,
        "entry_price": price,
        "entry_date": ts_iso[:10],
        "entry_timestamp": ts_iso,
        "buy_value": val,
        "buy_fee": fee,
        "sub_rule": meta.get("sub_rule", "standard"),
        "tp_pct": meta.get("tp_pct", 0.04),
        "tp_price": round(price * (1.0 + float(meta.get("tp_pct", 0.04))), 2) if meta.get("tp_pct") else None,
        "max_hold_days": int(meta.get("max_hold_days", 5)),
        "signal_metrics": meta.get("signal_metrics", {}),
        "current_price": price,
        "unrealized_pnl": round(-fee, 2),
        "unrealized_return_pct": round(-fee / val * 100.0, 2),
    }
    bkt.setdefault("open_positions", []).append(pos_rec)
    bkt.setdefault("trades", []).append(
        {
            "trade_id": tid,
            "code": code,
            "name": name,
            "shares": shares,
            "entry_date": ts_iso[:10],
            "entry_timestamp": ts_iso,
            "entry_price": price,
            "buy_value": val,
            "buy_fee": fee,
            "sub_rule": meta.get("sub_rule", "standard"),
            "exit_date": None,
            "exit_timestamp": None,
            "exit_price": None,
            "sell_value": None,
            "sell_fee": None,
            "net_pnl": None,
            "net_return_pct": None,
            "status": "OPEN",
            "outcome": "OPEN",
            "entry_reason": reason,
            "exit_reason": None,
        }
    )
    if write_audit:
        _write_audit_file(t_entry, pre_nav, post_nav, pre_cash_pct, post_cash_pct, len(acc["positions"]))
    return t_entry


def book_sell(
    state: dict,
    ledger: dict,
    bucket_key: str,
    code: str,
    price: float,
    ts_iso: str,
    reason: str,
    count_in_winrate: bool = True,
    write_audit: bool = True,
) -> dict:
    acc = state["accounts"]["a_share"]
    bkt = ledger["buckets"][bucket_key]
    _sync_account_nav(acc)
    pre_nav = acc["total_assets"]
    pre_cash_pct = acc.get("cash_pct", 0.0) * 100.0

    pos_idx = next((i for i, p in enumerate(acc["positions"]) if str(p["ticker"]).zfill(6) == code), None)
    if pos_idx is None:
        raise RuntimeError(f"SSOT 未找到持仓 {code}")
    ssot_pos = acc["positions"][pos_idx]
    shares = int(ssot_pos["shares"])
    avg_cost = float(ssot_pos["avg_cost"])
    name = ssot_pos.get("name", code)

    proceeds = round(shares * price, 2)
    fd = AR.fees(proceeds, "sell")
    sell_fee = round(fd["total"], 2)
    gross_pnl = round((price - avg_cost) * shares, 2)
    realized_pnl = round(gross_pnl - sell_fee, 4)

    acc["positions"].pop(pos_idx)
    acc["cash"] = round(acc["cash"] + proceeds - sell_fee, 4)
    acc["realized_pnl"] = round(float(acc.get("realized_pnl", 0.0)) + realized_pnl, 4)
    acc["trade_count"] = int(acc.get("trade_count", 0)) + 1
    bkt["cash"] = round(bkt["cash"] + proceeds - sell_fee, 4)

    _sync_account_nav(acc)
    post_nav = acc["total_assets"]
    post_cash_pct = acc.get("cash_pct", 0.0) * 100.0

    tid = next_trade_id(state)
    t_entry = {
        "id": tid,
        "timestamp": ts_iso,
        "date": ts_iso[:10],
        "action": "sell",
        "account": "a_share",
        "bucket": bucket_key,
        "ticker": code,
        "name": name,
        "shares": shares,
        "price": price,
        "value": proceeds,
        "currency": "CNY",
        "realized_pnl": round(realized_pnl, 2),
        "gross_pnl": gross_pnl,
        "fee": sell_fee,
        "fee_detail": fd,
        "reason": reason,
    }
    state["trade_log"].append(t_entry)
    state.setdefault("_meta", {})["last_updated"] = ts_iso

    # 更新桶内 open_positions 与 trades
    open_list = bkt.get("open_positions", [])
    op_idx = next((i for i, x in enumerate(open_list) if x["code"] == code), None)
    buy_fee = 0.0
    if op_idx is not None:
        op_rec = open_list.pop(op_idx)
        buy_fee = float(op_rec.get("buy_fee", 0.0))

    net_roundtrip_pnl = round(gross_pnl - buy_fee - sell_fee, 2)
    net_ret_pct = round(net_roundtrip_pnl / (shares * avg_cost) * 100.0, 2)

    tr_rec = next((x for x in reversed(bkt.get("trades", [])) if x["code"] == code and x["status"] == "OPEN"), None)
    if tr_rec is not None:
        tr_rec.update(
            {
                "sell_trade_id": tid,
                "exit_date": ts_iso[:10],
                "exit_timestamp": ts_iso,
                "exit_price": price,
                "sell_value": proceeds,
                "sell_fee": sell_fee,
                "net_pnl": net_roundtrip_pnl,
                "net_return_pct": net_ret_pct,
                "status": "CLOSED",
                "outcome": ("WIN" if net_roundtrip_pnl > 0 else "LOSS") if count_in_winrate else "LEGACY_CLOSED",
                "exit_reason": reason,
            }
        )
    else:
        bkt.setdefault("trades", []).append(
            {
                "trade_id": tid,
                "code": code,
                "name": name,
                "shares": shares,
                "entry_date": str(ssot_pos.get("entry_date", ""))[:10],
                "entry_price": avg_cost,
                "buy_value": round(shares * avg_cost, 2),
                "buy_fee": buy_fee,
                "sub_rule": "legacy_carryover",
                "exit_date": ts_iso[:10],
                "exit_timestamp": ts_iso,
                "exit_price": price,
                "sell_value": proceeds,
                "sell_fee": sell_fee,
                "net_pnl": net_roundtrip_pnl,
                "net_return_pct": net_ret_pct,
                "status": "CLOSED",
                "outcome": ("WIN" if net_roundtrip_pnl > 0 else "LOSS") if count_in_winrate else "LEGACY_CLOSED",
                "exit_reason": reason,
            }
        )

    recompute_bucket_stats(ledger)
    if write_audit:
        _write_audit_file(t_entry, pre_nav, post_nav, pre_cash_pct, post_cash_pct, len(acc["positions"]))
    return t_entry


def recompute_bucket_stats(ledger: dict, live_quotes: dict[str, dict] | None = None, trading_days: list[str] | None = None, cur_date: str | None = None) -> None:
    for bkey, bkt in ledger["buckets"].items():
        closed = [t for t in bkt.get("trades", []) if t.get("status") == "CLOSED" and t.get("outcome") in ("WIN", "LOSS")]
        wins = sum(1 for t in closed if t["outcome"] == "WIN")
        losses = sum(1 for t in closed if t["outcome"] == "LOSS")
        bkt["win_count"] = wins
        bkt["loss_count"] = losses
        bkt["win_rate"] = round(wins / (wins + losses) * 100.0, 2) if (wins + losses) > 0 else None
        all_closed = [t for t in bkt.get("trades", []) if t.get("status") == "CLOSED"]
        bkt["realized_pnl"] = round(sum(float(t.get("net_pnl") or 0.0) for t in all_closed), 2)

        mv_sum = 0.0
        unr_sum = 0.0
        for op in bkt.get("open_positions", []):
            c = op["code"]
            px = float((live_quotes or {}).get(c, {}).get("now") or op.get("current_price") or op["entry_price"])
            op["current_price"] = px
            mv = round(op["shares"] * px, 2)
            op["market_value"] = mv
            unr = round(mv - op["buy_value"] - float(op.get("buy_fee", 0.0)), 2)
            op["unrealized_pnl"] = unr
            op["unrealized_return_pct"] = round((px / op["entry_price"] - 1.0) * 100.0, 2)
            if trading_days and cur_date:
                op["hold_days"] = count_hold_days(op["entry_date"], cur_date, trading_days)
            mv_sum += mv
            unr_sum += unr
        bkt["open_market_value"] = round(mv_sum, 2)
        bkt["unrealized_pnl"] = round(unr_sum, 2)
        bkt["bucket_equity"] = round(float(bkt["cash"]) + mv_sum, 2)
        bkt["bucket_return_pct"] = round((bkt["bucket_equity"] / float(bkt["quota_cny"]) - 1.0) * 100.0, 2)


def refresh_ssot_marks(state: dict, quotes: dict[str, dict], snap_date: str, hs300_close: float | None = None) -> None:
    acc = state["accounts"]["a_share"]
    for p in acc.get("positions", []):
        c = str(p["ticker"]).zfill(6)
        q = quotes.get(c)
        if q:
            p["name"] = q.get("name") or p.get("name", c)
            p["current_price"] = round(float(q["now"]), 4)
            p["prev_close"] = round(float(q.get("prev_close") or p.get("prev_close") or q["now"]), 4)
            p["change_pct"] = round(float(q.get("pct") or 0.0), 2)
            p["peak_price"] = round(max(float(p.get("peak_price") or 0.0), float(q.get("high") or q["now"])), 4)
    _sync_account_nav(acc)

    cn_nav = round(float(acc["total_assets"]), 2)
    cn_ret = round((cn_nav / INITIAL_CAPITAL_CN - 1.0) * 100.0, 2)
    hs_c = hs300_close or float((quotes.get("sh000300") or {}).get("now") or 0.0)
    hs_ret = round((hs_c / DAY1_HS300_BASE - 1.0) * 100.0, 2) if hs_c > 0 else None
    cn_alpha = round(cn_ret - hs_ret, 2) if hs_ret is not None else None

    snaps = state.setdefault("performance", {}).setdefault("daily_snapshots", [])
    existing = next((s for s in snaps if s.get("date") == snap_date), None)
    if existing is None:
        prev_s = snaps[-1] if snaps else {}
        existing = {
            "date": snap_date,
            "us_nav": prev_s.get("us_nav"),
            "us_return_pct": prev_s.get("us_return_pct"),
            "spy_close": prev_s.get("spy_close"),
            "spy_return_pct": prev_s.get("spy_return_pct"),
        }
        snaps.append(existing)
    existing["a_share_nav"] = cn_nav
    existing["a_share_return_pct"] = cn_ret
    if hs_c > 0:
        existing["sse_close"] = round(hs_c, 2)
        existing["sse_return_pct"] = hs_ret
        existing["a_share_alpha"] = cn_alpha


# ===========================================================================
# 全市场信号扫描器（零前视镜 / 自动缝合缺失日线）
# ===========================================================================

def load_recent_parquet_window(before_date: str) -> tuple[dict[str, list[tuple[str, float, float]]], dict[str, float]]:
    """读取 a_daily.parquet 中 date < before_date 的最近25根日线与 oshare。
    返回: ({code: [(date_str, close, turn_pct), ...]}, {code: oshare_shares})
    """
    df = pd.read_parquet(PARQUET_PATH, columns=["date", "ticker", "close", "turn", "oshare"])
    df["d"] = df["date"].astype(str).str[:10]
    df = df[df["d"] < before_date].sort_values(["ticker", "d"])
    tail = df.groupby("ticker", sort=False).tail(25)
    hist_map: dict[str, list[tuple[str, float, float]]] = {}
    oshare_map: dict[str, float] = {}
    for code_raw, g in tail.groupby("ticker", sort=False):
        c = str(code_raw)[:6]
        # a_daily.parquet 中 turn 为小数换手率(如 0.025 = 2.5%) 或百分数？核查均值自适应：
        turns = g["turn"].astype(float).fillna(0.0).tolist()
        closes = g["close"].astype(float).tolist()
        dates = g["d"].tolist()
        osh = float(g["oshare"].dropna().iloc[-1]) if g["oshare"].notna().any() else 0.0
        # cn_price_db_update.py 注释：turnoverRatio 除以 100 入库（小数制，0.03 = 3%）
        # 统一转为百分数(3.0)与腾讯 f[38] 对齐
        med_t = float(np.median([x for x in turns if x > 0])) if any(x > 0 for x in turns) else 0.0
        scale = 100.0 if 0 < med_t < 0.5 else 1.0
        hist_map[c] = [(dates[i], closes[i], turns[i] * scale) for i in range(len(dates))]
        if osh > 0:
            oshare_map[c] = osh
    return hist_map, oshare_map


def scan_tail_oversold_live(quotes: dict[str, dict], today_str: str, trading_days: list[str]) -> tuple[list[dict], list[dict]]:
    """14:57 实时扫描第1桶与第2桶（自动用腾讯日K补齐 a_daily.parquet 滞后缺日）。"""
    hist_map, oshare_map = load_recent_parquet_window(today_str)
    prev_tdays = [d for d in trading_days if d < today_str]
    prev_tday = prev_tdays[-1] if prev_tdays else ""

    # 第一层粗筛：实盘硬门槛（非ST/退市、流通市值5~33亿、真阳线翻红、未涨跌停、日内分位>=0.65）
    coarse_codes = []
    for c, q in quotes.items():
        if len(c) != 6 or not c.isdigit():
            continue
        if c.startswith(("4", "8", "9")):  # 排除北交所30cm，与回测口径一致
            continue
        nm = q.get("name", "")
        if "ST" in nm.upper() or "退" in nm or nm.startswith(("N", "C")):
            continue
        fmc = q["float_mcap_yi"]
        if not (5.0 <= fmc <= 33.0):
            continue
        now_p, prev_c, op_p, hi_p, lo_p = q["now"], q["prev_close"], q["open"], q["high"], q["low"]
        if now_p <= 0 or prev_c <= 0 or hi_p <= lo_p:
            continue
        if q["zt_price"] > 0 and now_p >= q["zt_price"] - 0.005:
            continue
        if q["dt_price"] > 0 and now_p <= q["dt_price"] + 0.005:
            continue
        if not (now_p > prev_c and now_p > op_p):
            continue
        k_pos = (now_p - lo_p) / (hi_p - lo_p)
        if k_pos < 0.65:
            continue
        bars = hist_map.get(c, [])
        if len(bars) < 18:
            continue
        # 快速估算 MA10：若 parquet 缺 prev_tday，则把 q['prev_close'] 拼上做初筛(< -8.5%)
        recent_c = [b[1] for b in bars[-9:]]
        if bars[-1][0] < prev_tday:
            recent_c = [b[1] for b in bars[-8:]] + [prev_c]
        ma10_est = (sum(recent_c[-9:]) + now_p) / 10.0
        if now_p / ma10_est - 1.0 <= -0.085:
            coarse_codes.append(c)

    # 第二层精算：对粗筛出的少量候选（通常 <30 只）并发拉取腾讯精确日K补齐任何缺失交易日收盘与换手
    need_patch = [c for c in coarse_codes if (not hist_map.get(c)) or hist_map[c][-1][0] < prev_tday]
    patched_klines: dict[str, list[dict]] = {}
    if need_patch:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(fetch_kline_bars, c, "2026-09-01", today_str, 35): c for c in need_patch}
            for fut, c in futs.items():
                try:
                    patched_klines[c] = fut.result()
                except Exception:
                    patched_klines[c] = []

    b1_hits, b2_hits = [], []
    for c in coarse_codes:
        q = quotes[c]
        bars = list(hist_map.get(c, []))
        if c in patched_klines and patched_klines[c]:
            existing_dates = {b[0] for b in bars}
            osh = oshare_map.get(c, 0.0)
            # 若 oshare 缺失，由今日流通市值/现价反推流通股数
            if osh <= 0 and q["now"] > 0 and q["float_mcap_yi"] > 0:
                osh = q["float_mcap_yi"] * 1e8 / q["now"]
            for kr in patched_klines[c]:
                if kr["date"] < today_str and kr["date"] not in existing_dates:
                    tpct = (kr["vol_lots"] * 100.0 / osh * 100.0) if osh > 0 else q["turn_pct"]
                    bars.append((kr["date"], kr["close"], tpct))
            bars.sort(key=lambda x: x[0])

        if len(bars) < 20:
            continue
        closes_9 = [b[1] for b in bars[-9:]]
        ma10 = (sum(closes_9) + q["now"]) / 10.0
        bias10_pct = (q["now"] / ma10 - 1.0) * 100.0
        turn_ma20 = float(np.mean([b[2] for b in bars[-20:]]))
        if turn_ma20 <= 0:
            continue
        vr = q["turn_pct"] / turn_ma20
        k_pos = (q["now"] - q["low"]) / (q["high"] - q["low"])

        rec = {
            "code": c,
            "name": q["name"],
            "price": q["now"],
            "open": q["open"],
            "prev_close": q["prev_close"],
            "pct": round((q["now"] / q["prev_close"] - 1.0) * 100.0, 2),
            "float_mcap_yi": round(q["float_mcap_yi"], 2),
            "bias10_pct": round(bias10_pct, 2),
            "turn_ratio": round(vr, 3),
            "k_pos": round(k_pos, 3),
        }
        if 5.0 <= q["float_mcap_yi"] <= 33.0 and bias10_pct <= -14.0 and vr <= 0.70:
            b1_hits.append(rec)
        elif 5.0 <= q["float_mcap_yi"] <= 31.0 and bias10_pct <= -10.1 and vr <= 0.75:
            b2_hits.append(rec)

    b1_hits.sort(key=lambda x: x["bias10_pct"])
    b2_hits.sort(key=lambda x: x["bias10_pct"])
    return b1_hits, b2_hits


def scan_bucket3_open_live(quotes: dict[str, dict], today_str: str) -> tuple[list[dict], list[dict]]:
    """09:26 扫描第3桶（主板10cm连续封死>=3个跌停 + 此前20日0涨停 + 今日09:25非一字跌停 + 无ST/退市/立案红旗）。
    返回 (qualified_hits, rejected_audit)
    """
    hist_map, _ = load_recent_parquet_window(today_str)
    # 找出主板10cm中近几日大跌候选，拉腾讯精确日K逐根核验3连封死跌停
    suspects = []
    for c, q in quotes.items():
        if len(c) != 6 or not c.isdigit():
            continue
        if AR.board(c) not in ("main_sh", "main_sz"):
            continue
        bars = hist_map.get(c, [])
        if len(bars) >= 3:
            ref_c = bars[-3][1]
            if ref_c > 0 and q["prev_close"] / ref_c <= 0.83:
                suspects.append(c)

    qualified, rejected = [], []
    for c in suspects:
        q = quotes[c]
        nm = q.get("name", "")
        try:
            kl = [r for r in fetch_kline_bars(c, "2026-09-01", today_str, 35) if r["date"] < today_str]
        except Exception:
            continue
        if len(kl) < 24:
            continue
        # 计算每一根是否封死跌停 / 涨停
        is_dt_arr, is_zt_arr = [], []
        for i in range(1, len(kl)):
            pc = kl[i - 1]["close"]
            cl, lo, hi = kl[i]["close"], kl[i]["low"], kl[i]["high"]
            dt_p = float(AR.limit_price(pc, c, "down", is_st=("ST" in nm.upper())))
            zt_p = float(AR.limit_price(pc, c, "up", is_st=("ST" in nm.upper())))
            is_dt_arr.append(cl <= dt_p + 0.01 and cl <= lo + 0.005 and (cl / pc - 1.0) <= -0.095)
            is_zt_arr.append(cl >= zt_p - 0.01 and cl >= hi - 0.005 and (cl / pc - 1.0) >= 0.095)

        # 数截至昨日收盘的连续封死跌停数
        streak = 0
        for flag in reversed(is_dt_arr):
            if flag:
                streak += 1
            else:
                break
        if streak < 3:
            continue

        prior_window = is_zt_arr[max(0, len(is_zt_arr) - streak - 20) : len(is_zt_arr) - streak]
        zt20 = int(sum(prior_window))
        chg10 = round((kl[-1]["close"] / kl[-11]["close"] - 1.0) * 100.0, 2) if len(kl) >= 11 else -27.0

        if "ST" in nm.upper() or "退" in nm:
            rejected.append({"code": c, "name": nm, "dt_streak": streak, "zt20": zt20, "reject_reason": "ST或退市风险警示硬门否决"})
            continue
        if zt20 > 0:
            rejected.append({"code": c, "name": nm, "dt_streak": streak, "zt20": zt20, "reject_reason": f"此前20日涨停{zt20}次，属高标退潮非纯超跌"})
            continue
        if q["open"] <= 0 or (q["dt_price"] > 0 and q["open"] <= q["dt_price"] + 0.005):
            rejected.append({"code": c, "name": nm, "dt_streak": streak, "zt20": zt20, "reject_reason": f"09:25仍一字跌停开盘({q['open']})不可买"})
            continue
        if q["zt_price"] > 0 and q["open"] >= q["zt_price"] - 0.005:
            rejected.append({"code": c, "name": nm, "dt_streak": streak, "zt20": zt20, "reject_reason": f"09:25一字涨停开盘({q['open']})排不进"})
            continue
        ok_ann, flags = check_announcement_red_flags(c, today_str)
        if not ok_ann:
            rejected.append({"code": c, "name": nm, "dt_streak": streak, "zt20": zt20, "reject_reason": f"近90日公告红旗否决:{flags[0]}"})
            continue

        qualified.append(
            {
                "code": c,
                "name": nm,
                "open": q["open"],
                "prev_close": q["prev_close"],
                "open_pct": q["open_pct"],
                "dt_streak": streak,
                "zt20": zt20,
                "chg10_pct": chg10,
            }
        )

    qualified.sort(key=lambda x: x["chg10_pct"])
    return qualified, rejected


def _load_zt_pool_day(day_str: str) -> list[dict]:
    fn = ZT_POOL_DIR / f"{day_str.replace('-', '')}.json"
    if not fn.exists():
        return []
    d = json.load(open(fn, encoding="utf-8"))
    return d if isinstance(d, list) else (d.get("stocks") or d.get("data") or [])


def scan_bucket4_open_live(quotes: dict[str, dict], today_str: str, trading_days: list[str]) -> tuple[list[dict], list[dict]]:
    """09:26 扫描第4桶三大子规则（严格对照 strategy_astock.md 第二节 & 台账）：
      ① five_board        : 昨日5连板(主板10cm非ST) + 前十流通锁仓比>=50% + 今日09:25开盘<=+5.5%(且非跌停)
      ② high_break_rebound: 前日>=4连板 + 昨日断板首日收+2.0%至+7.5%真阳线(收盘>开盘) + 同板块昨日>=1只涨停活口 + 今日09:25开盘-4.0%至+5.0%
      ③ sole_leader       : 昨日全场唯一>=4连板最高标独苗 + 同板块昨日>=2只涨停 + 今日09:25高开0.0%至+6.5%
    """
    prev_days = [d for d in trading_days if d < today_str]
    if len(prev_days) < 2:
        return [], []
    d_t1, d_t2 = prev_days[-1], prev_days[-2]
    pool_t1 = _load_zt_pool_day(d_t1)
    pool_t2 = _load_zt_pool_day(d_t2)

    ind_cnt_t1: dict[str, int] = {}
    zt_codes_t1: set[str] = set()
    high4_t1: list[dict] = []
    for r in pool_t1:
        c = str(r.get("代码") or r.get("code") or "").zfill(6)
        ind = str(r.get("所属行业") or r.get("industry") or "")
        lbc = int(r.get("连板数") or r.get("boards") or 0)
        zt_codes_t1.add(c)
        ind_cnt_t1[ind] = ind_cnt_t1.get(ind, 0) + 1
        if lbc >= 4 and AR.board(c) in ("main_sh", "main_sz"):
            high4_t1.append({"code": c, "name": str(r.get("名称") or ""), "boards": lbc, "industry": ind})

    qualified, rejected = [], []

    # 子规则①：五板手册（昨日5连板）
    for item in [x for x in high4_t1 if x["boards"] == 5]:
        c, nm, ind = item["code"], item["name"], item["industry"]
        if "ST" in nm.upper() or "退" in nm:
            continue
        q = quotes.get(c)
        if not q or q["open"] <= 0:
            continue
        lock10 = get_lock10_pct(c)
        op_pct = q["open_pct"]
        if lock10 < 50.0:
            rejected.append({"code": c, "name": nm, "sub_rule": "five_board", "reject_reason": f"五板手册锁仓比{lock10:.2f}%低于50%硬门槛"})
            continue
        if op_pct > 5.5:
            rejected.append({"code": c, "name": nm, "sub_rule": "five_board", "reject_reason": f"五板次日开盘{op_pct:+.2f}%高于+5.5%硬门槛"})
            continue
        if q["dt_price"] > 0 and q["open"] <= q["dt_price"] + 0.005:
            rejected.append({"code": c, "name": nm, "sub_rule": "five_board", "reject_reason": "一字跌停开盘"})
            continue
        ok_ann, flags = check_announcement_red_flags(c, today_str)
        if not ok_ann:
            rejected.append({"code": c, "name": nm, "sub_rule": "five_board", "reject_reason": f"公告红旗:{flags[0]}"})
            continue
        qualified.append(
            {
                "code": c,
                "name": q["name"],
                "open": q["open"],
                "prev_close": q["prev_close"],
                "open_pct": op_pct,
                "sub_rule": "five_board",
                "tp_pct": None,
                "max_hold_days": 3,  # 第1天买入，第4天(hold_days==3)收盘卖出，期间卡10日100%异动93%线止盈
                "lock10_pct": lock10,
                "sector_zt": ind_cnt_t1.get(ind, 1),
                "desc": f"五板手册标准买点({d_t1}五连板，锁仓比{lock10:.1f}%>=50%，今开{op_pct:+.2f}%<=+5.5%)",
            }
        )

    # 子规则②：前日>=4连板，昨日断板首日收+2.0%至+7.5%真阳线且同板块昨日>=1只涨停活口，今开-4.0%至+5.0%
    for r in pool_t2:
        c = str(r.get("代码") or r.get("code") or "").zfill(6)
        lbc2 = int(r.get("连板数") or r.get("boards") or 0)
        ind = str(r.get("所属行业") or r.get("industry") or "")
        nm = str(r.get("名称") or "")
        if lbc2 < 4 or AR.board(c) not in ("main_sh", "main_sz") or c in zt_codes_t1:
            continue
        try:
            kl = [x for x in fetch_kline_bars(c, "2026-10-01", today_str, 15) if x["date"] <= d_t1]
        except Exception:
            continue
        if len(kl) < 2 or kl[-1]["date"] != d_t1:
            continue
        b_t1, b_t2 = kl[-1], kl[-2]
        t1_pct = (b_t1["close"] / b_t2["close"] - 1.0) * 100.0
        is_true_yang = b_t1["close"] > b_t1["open"]
        sec_alive = ind_cnt_t1.get(ind, 0)
        if not (2.0 <= t1_pct <= 7.5 and is_true_yang):
            rejected.append({"code": c, "name": nm, "sub_rule": "high_break_rebound", "reject_reason": f"{d_t1}断板日涨跌{t1_pct:+.2f}%/真阳={is_true_yang}未落入+2%~+7.5%真阳线"})
            continue
        if sec_alive < 1:
            rejected.append({"code": c, "name": nm, "sub_rule": "high_break_rebound", "reject_reason": f"{d_t1}同板块({ind})涨停活口0只"})
            continue
        q = quotes.get(c)
        if not q or q["open"] <= 0:
            continue
        if not (-4.0 <= q["open_pct"] <= 5.0):
            rejected.append({"code": c, "name": nm, "sub_rule": "high_break_rebound", "reject_reason": f"今开{q['open_pct']:+.2f}%不在-4%~+5%买点区间"})
            continue
        ok_ann, flags = check_announcement_red_flags(c, today_str)
        if not ok_ann:
            rejected.append({"code": c, "name": nm, "sub_rule": "high_break_rebound", "reject_reason": f"公告红旗:{flags[0]}"})
            continue
        if not any(x["code"] == c for x in qualified):
            qualified.append(
                {
                    "code": c,
                    "name": q["name"],
                    "open": q["open"],
                    "prev_close": q["prev_close"],
                    "open_pct": q["open_pct"],
                    "sub_rule": "high_break_rebound",
                    "tp_pct": 0.05,
                    "max_hold_days": 5,
                    "sector_zt": sec_alive,
                    "desc": f"{lbc2}板断板首日真阳反包({d_t1}收{t1_pct:+.2f}%真阳线，{ind}板块涨停活口{sec_alive}只，今开{q['open_pct']:+.2f}%)",
                }
            )

    # 子规则③：昨日全场唯一>=4板最高标独苗 + 同板块>=2只涨停 + 今开0.0%至+6.5%
    if len(high4_t1) == 1:
        sole = high4_t1[0]
        c, nm, ind, lbc = sole["code"], sole["name"], sole["industry"], sole["boards"]
        sec_cnt = ind_cnt_t1.get(ind, 0)
        q = quotes.get(c)
        if sec_cnt < 2:
            rejected.append({"code": c, "name": nm, "sub_rule": "sole_leader", "reject_reason": f"唯一{lbc}板独苗但同板块({ind})涨停仅{sec_cnt}只(<2只)"})
        elif q and q["open"] > 0:
            if not (0.0 <= q["open_pct"] <= 6.5):
                rejected.append({"code": c, "name": nm, "sub_rule": "sole_leader", "reject_reason": f"唯一{lbc}板独苗今开{q['open_pct']:+.2f}%不在0%~+6.5%区间"})
            else:
                ok_ann, flags = check_announcement_red_flags(c, today_str)
                if ok_ann and not any(x["code"] == c for x in qualified):
                    qualified.append(
                        {
                            "code": c,
                            "name": q["name"],
                            "open": q["open"],
                            "prev_close": q["prev_close"],
                            "open_pct": q["open_pct"],
                            "sub_rule": "sole_leader",
                            "tp_pct": None,
                            "max_hold_days": 5,
                            "sector_zt": sec_cnt,
                            "desc": f"全场唯一{lbc}板最高标独苗({ind}涨停{sec_cnt}只，今开{q['open_pct']:+.2f}%)",
                        }
                    )

    return qualified, rejected


def check_severe_abnormal_93(code: str, quote: dict) -> tuple[bool, float | None, str]:
    """用 astock_intraday_check 同源交易所基准指数计算今日 10日100% / 30日200% 严重异动 93% 提前止盈线。"""
    sym = market_prefix(code) + code
    idx_sym, idx_label = AIC.benchmark_index(code)
    try:
        idx_q = AIC.fetch_tencent_quotes([idx_sym]).get(idx_sym, {})
        k_stk = AIC.fetch_sina_kline(sym, 36)
        k_idx = AIC.fetch_sina_kline(idx_sym, 36)
    except Exception:
        return False, None, ""
    if not k_stk or not k_idx:
        return False, None, ""
    today_fmt = now_cn().strftime("%Y-%m-%d")
    past_stk = [(r["day"], r["close"]) for r in k_stk if r["day"] < today_fmt]
    idx_map = {r["day"]: r["close"] for r in k_idx}
    idx_now = float(idx_q.get("now") or k_idx[-1]["close"])
    t10 = AIC.calc_window_threshold(past_stk, idx_map, idx_now, 9, 1.00, quote["prev_close"])
    t30 = AIC.calc_window_threshold(past_stk, idx_map, idx_now, 29, 2.00, quote["prev_close"])
    candidates = [x["p_93"] for x in (t10, t30) if x and x.get("p_93")]
    if not candidates:
        return False, None, ""
    p93 = min(candidates)
    if quote["now"] >= p93:
        return True, p93, f"触及严重异动93%提前止盈线({p93:.2f}，对标{idx_label})"
    return False, p93, ""


# ===========================================================================
# 实盘子命令实现：open / intraday / tail / reconcile / status
# ===========================================================================

def cmd_open(args: argparse.Namespace) -> None:
    today_str = now_cn().strftime("%Y-%m-%d")
    if not args.force and not is_trading_day():
        print(f"[open] {today_str} 非交易日，跳过")
        return
    ledger = load_ledger()
    run_hist = ledger.setdefault("run_history", {})
    if not args.force and not args.dry_run and run_hist.get(f"{today_str}:open"):
        print(f"[open] {today_str} 已执行过早盘任务，幂等跳过")
        return

    codes = load_universe_codes()
    quotes = fetch_quotes_batch(codes, include_indices=True)
    if len(quotes) < 4500:
        msg = f"⛔[四分仓·09:26早盘故障] 腾讯全市场快照仅返回 {len(quotes)} 只(<4500)，拒绝盲目执行"
        print(msg, file=sys.stderr)
        send_feishu(msg, dry_run=args.dry_run)
        sys.exit(2)

    trading_days = get_trading_days_recent(40)
    b3_hits, b3_rej = scan_bucket3_open_live(quotes, today_str)
    b4_hits, b4_rej = scan_bucket4_open_live(quotes, today_str, trading_days)

    audit_day = ledger.setdefault("daily_signal_audit", {}).setdefault(today_str, {})
    audit_day["open_0926"] = {
        "checked_at": now_cn().isoformat(timespec="seconds"),
        "universe_count": len(quotes),
        "bucket_3_qualified": b3_hits,
        "bucket_3_rejected": b3_rej,
        "bucket_4_qualified": b4_hits,
        "bucket_4_rejected": b4_rej,
    }

    executed_msgs = []
    if not args.dry_run:
        state = portfolio_io.load_portfolio()
    else:
        state = json.load(open(ROOT / "portfolio_state.json", encoding="utf-8"))

    # 第3桶买入执行（最多2只等权；1只则满额）
    b3 = ledger["buckets"]["bucket_3_three_dt"]
    b3_open_codes = {x["code"] for x in b3.get("open_positions", [])}
    b3_free_slots = max(0, 2 - len(b3_open_codes))
    b3_cands = [x for x in b3_hits if x["code"] not in b3_open_codes][:b3_free_slots]
    if b3_cands and b3["cash"] >= 50_000:
        per_budget = b3["cash"] / len(b3_cands)
        for cand in b3_cands:
            px = cand["open"] if abs(now_cn().hour * 60 + now_cn().minute - 566) <= 5 else quotes[cand["code"]]["now"]
            sh = calc_order_shares(cand["code"], per_budget, px)
            if sh > 0:
                reason = f"四分仓第3桶(三连跌停纯超跌撬板): {cand['name']}({cand['code']})连续{cand['dt_streak']}跌停且前20日0涨停，09:25开盘{cand['open_pct']:+.2f}%非一字跌停买入"
                if not args.dry_run:
                    book_buy(state, ledger, "bucket_3_three_dt", cand["code"], cand["name"], sh, px, now_cn().isoformat(timespec="seconds"), reason, {"sub_rule": "three_dt", "tp_pct": 0.05, "max_hold_days": 5, "prev_close": cand["prev_close"]})
                executed_msgs.append(f"第3桶买入 {cand['name']}({cand['code']}) {sh}股@{px:.2f}")

    # 第4桶买入执行（严格单仓轮动，持仓未平绝不提前换股）
    b4 = ledger["buckets"]["bucket_4_high_board"]
    if len(b4.get("open_positions", [])) == 0 and b4_hits and b4["cash"] >= 50_000:
        cand = b4_hits[0]
        px = cand["open"] if abs(now_cn().hour * 60 + now_cn().minute - 566) <= 5 else quotes[cand["code"]]["now"]
        sh = calc_order_shares(cand["code"], b4["cash"], px)
        if sh > 0:
            reason = f"四分仓第4桶({cand['sub_rule']}): {cand['desc']}，早盘按{px:.2f}元买入"
            if not args.dry_run:
                book_buy(state, ledger, "bucket_4_high_board", cand["code"], cand["name"], sh, px, now_cn().isoformat(timespec="seconds"), reason, {"sub_rule": cand["sub_rule"], "tp_pct": cand["tp_pct"], "max_hold_days": cand["max_hold_days"], "prev_close": cand["prev_close"]})
            executed_msgs.append(f"第4桶买入 {cand['name']}({cand['code']}) {sh}股@{px:.2f} [{cand['sub_rule']}]")

    recompute_bucket_stats(ledger, quotes, trading_days, today_str)
    if not args.dry_run:
        run_hist[f"{today_str}:open"] = now_cn().isoformat(timespec="seconds")
        refresh_ssot_marks(state, quotes, today_str)
        save_ledger(ledger)
        portfolio_io.save_portfolio(state, reason=f"四分仓09:26早盘扫描({len(executed_msgs)}笔成交)", auto_sync=bool(executed_msgs))

    summary = (
        f"[四分仓·09:26早盘回执 {today_str}] 扫描宇宙{len(quotes)}只 | "
        f"第3桶信号{len(b3_hits)}只，第4桶信号{len(b4_hits)}只 | "
        + ("成交: " + "；".join(executed_msgs) if executed_msgs else "本时段无新建仓")
    )
    print(summary)
    if executed_msgs:
        send_feishu(summary, dry_run=args.dry_run)


def cmd_intraday(args: argparse.Namespace) -> None:
    today_str = now_cn().strftime("%Y-%m-%d")
    if not args.force and not is_trading_day():
        return
    ledger = load_ledger()
    eligible = []
    for bkey, bkt in ledger["buckets"].items():
        for op in bkt.get("open_positions", []):
            if op["entry_date"] < today_str:
                eligible.append((bkey, op))
    if not eligible:
        print(f"[intraday] {today_str} 无T+1可卖持仓")
        return

    codes = list({op["code"] for _, op in eligible})
    quotes = fetch_quotes_batch(codes, include_indices=True)
    trading_days = get_trading_days_recent(40)
    to_sell = []
    for bkey, op in eligible:
        c = op["code"]
        q = quotes.get(c)
        if not q or q["now"] <= 0:
            continue
        if q["dt_price"] > 0 and q["now"] <= q["dt_price"] + 0.005 and q["bid1_vol"] == 0:
            continue  # 一字跌停封死卖不出
        sub = op.get("sub_rule", "standard")
        tp_px = op.get("tp_price")
        if tp_px and q["now"] >= float(tp_px):
            to_sell.append((bkey, op, q["now"], f"盘中触及止盈线{tp_px:.2f}元(现价{q['now']:.2f}元)"))
        elif sub in ("five_board", "sole_leader"):
            hit93, p93, why93 = check_severe_abnormal_93(c, q)
            if hit93:
                to_sell.append((bkey, op, q["now"], why93))

    if not to_sell:
        print(f"[intraday] {now_cn():%H:%M:%S} 已检 {len(eligible)} 只T+1持仓，均未触及止盈线")
        return

    state = json.load(open(ROOT / "portfolio_state.json", encoding="utf-8")) if args.dry_run else portfolio_io.load_portfolio()
    sold_msgs = []
    for bkey, op, px, why in to_sell:
        reason = f"四分仓({bkey})盘中规则止盈: {why}，买入日{op['entry_date']}成本{op['entry_price']:.2f}"
        if not args.dry_run:
            book_sell(state, ledger, bkey, op["code"], px, now_cn().isoformat(timespec="seconds"), reason)
        sold_msgs.append(f"{op['name']}({op['code']}) {op['shares']}股@{px:.2f} ({why})")

    recompute_bucket_stats(ledger, quotes, trading_days, today_str)
    if not args.dry_run:
        refresh_ssot_marks(state, quotes, today_str)
        save_ledger(ledger)
        portfolio_io.save_portfolio(state, reason=f"四分仓盘中止盈({len(sold_msgs)}笔)", auto_sync=True)
    msg = f"[四分仓·盘中止盈成交 {today_str}]\n" + "\n".join(sold_msgs)
    print(msg)
    send_feishu(msg, dry_run=args.dry_run)


def cmd_tail(args: argparse.Namespace) -> None:
    today_str = now_cn().strftime("%Y-%m-%d")
    if not args.force and not is_trading_day():
        print(f"[tail] {today_str} 非交易日，跳过")
        return
    phase = args.phase
    trading_days = get_trading_days_recent(40)
    if today_str not in trading_days:
        trading_days.append(today_str)

    # 阶段1 (14:55)：检查T+1持仓到期平仓 / 独苗断板收盘卖 / 五板第4天收盘卖
    if phase in ("exit", "both"):
        cmd_intraday(args)  # 先过一遍止盈检视
        ledger = load_ledger()
        eligible = [(bkey, op) for bkey, bkt in ledger["buckets"].items() for op in bkt.get("open_positions", []) if op["entry_date"] < today_str]
        if eligible:
            quotes = fetch_quotes_batch([op["code"] for _, op in eligible], include_indices=True)
            exits = []
            for bkey, op in eligible:
                q = quotes.get(op["code"])
                if not q or q["now"] <= 0:
                    continue
                if q["dt_price"] > 0 and q["now"] <= q["dt_price"] + 0.005 and q["bid1_vol"] == 0:
                    continue
                hdays = count_hold_days(op["entry_date"], today_str, trading_days)
                sub = op.get("sub_rule", "standard")
                max_d = int(op.get("max_hold_days", 5))
                if sub == "sole_leader" and q["zt_price"] > 0 and q["now"] < q["zt_price"] - 0.01:
                    exits.append((bkey, op, q["now"], f"唯一最高标独苗断板收盘卖出(现价{q['now']:.2f}<涨停{q['zt_price']:.2f})"))
                elif sub == "five_board" and hdays >= 3:
                    exits.append((bkey, op, q["now"], f"五板手册第4天收盘到期卖出(持有满{hdays + 1}日)"))
                elif hdays >= max_d:
                    exits.append((bkey, op, q["now"], f"持有满{hdays}个交易日未触及止盈线，到期收盘平仓"))

            if exits:
                state = json.load(open(ROOT / "portfolio_state.json", encoding="utf-8")) if args.dry_run else portfolio_io.load_portfolio()
                sold_msgs = []
                for bkey, op, px, why in exits:
                    reason = f"四分仓({bkey})14:55到期规则卖出: {why}，买入日{op['entry_date']}成本{op['entry_price']:.2f}"
                    if not args.dry_run:
                        book_sell(state, ledger, bkey, op["code"], px, now_cn().isoformat(timespec="seconds"), reason)
                    sold_msgs.append(f"{op['name']}({op['code']}) {op['shares']}股@{px:.2f} ({why})")
                recompute_bucket_stats(ledger, quotes, trading_days, today_str)
                if not args.dry_run:
                    refresh_ssot_marks(state, quotes, today_str)
                    save_ledger(ledger)
                    portfolio_io.save_portfolio(state, reason=f"四分仓14:55到期平仓({len(sold_msgs)}笔)", auto_sync=True)
                msg = f"[四分仓·14:55到期平仓 {today_str}]\n" + "\n".join(sold_msgs)
                print(msg)
                send_feishu(msg, dry_run=args.dry_run)
            else:
                print(f"[tail:exit] {today_str} 14:55 无到期需平仓持仓")

    # 阶段2 (14:57)：扫描全市场第1桶与第2桶超跌缩量翻红真阳线并自动买入空闲槽位
    if phase in ("buy", "both"):
        ledger = load_ledger()
        run_hist = ledger.setdefault("run_history", {})
        if not args.force and not args.dry_run and run_hist.get(f"{today_str}:tail_buy"):
            print(f"[tail:buy] {today_str} 已执行过14:57尾盘扫描，幂等跳过")
            return

        codes = load_universe_codes()
        quotes = fetch_quotes_batch(codes, include_indices=True)
        if len(quotes) < 4500:
            msg = f"⛔[四分仓·14:57尾盘故障] 全市场快照仅取到 {len(quotes)} 只(<4500)，拒绝残缺扫描"
            print(msg, file=sys.stderr)
            send_feishu(msg, dry_run=args.dry_run)
            sys.exit(2)

        b1_hits, b2_hits = scan_tail_oversold_live(quotes, today_str, trading_days)
        audit_day = ledger.setdefault("daily_signal_audit", {}).setdefault(today_str, {})
        audit_day["tail_1457"] = {
            "checked_at": now_cn().isoformat(timespec="seconds"),
            "universe_count": len(quotes),
            "bucket_1_signals": b1_hits,
            "bucket_2_signals": b2_hits[:6],
        }
        with open(SIGNAL_LOG_PATH, "a", encoding="utf-8") as sf:
            sf.write(json.dumps({"date": today_str, "phase": "tail_1457", "b1": b1_hits, "b2": b2_hits[:6]}, ensure_ascii=False) + "\n")

        state = json.load(open(ROOT / "portfolio_state.json", encoding="utf-8")) if args.dry_run else portfolio_io.load_portfolio()
        bought_msgs = []

        # 第1桶买入（空仓时买入；1只满额，多只取最深前2只等权）
        b1 = ledger["buckets"]["bucket_1_deep_oversold"]
        b1_held = {x["code"] for x in b1.get("open_positions", [])}
        if len(b1_held) == 0 and b1_hits and b1["cash"] >= 50_000:
            valid_b1 = []
            for h in b1_hits:
                ok_ann, _ = check_announcement_red_flags(h["code"], today_str)
                if ok_ann:
                    valid_b1.append(h)
                if len(valid_b1) >= 2:
                    break
            if valid_b1:
                per_b = b1["cash"] / len(valid_b1)
                for h in valid_b1:
                    sh = calc_order_shares(h["code"], per_b, h["price"])
                    if sh > 0:
                        reason = (
                            f"四分仓第1桶(极度超跌缩量真阳线)14:57尾盘买入: {h['name']}({h['code']}) "
                            f"流通市值{h['float_mcap_yi']}亿，10日乖离{h['bias10_pct']:.2f}%，量比{h['turn_ratio']:.2f}，日内分位{h['k_pos']:.2f}"
                        )
                        if not args.dry_run:
                            book_buy(state, ledger, "bucket_1_deep_oversold", h["code"], h["name"], sh, h["price"], now_cn().isoformat(timespec="seconds"), reason, {"sub_rule": "deep_oversold", "tp_pct": 0.04, "max_hold_days": 5, "prev_close": h["prev_close"], "signal_metrics": h})
                        bought_msgs.append(f"第1桶买入 {h['name']}({h['code']}) {sh}股@{h['price']:.2f} (乖离{h['bias10_pct']:.2f}%)")

        # 第2桶买入（2个等权槽位，每槽位占桶净值50%）
        b2 = ledger["buckets"]["bucket_2_mid_oversold"]
        b2_held = {x["code"] for x in b2.get("open_positions", [])}
        free_slots_b2 = max(0, 2 - len(b2_held))
        if free_slots_b2 > 0 and b2_hits and b2["cash"] >= 50_000:
            valid_b2 = []
            for h in b2_hits:
                if h["code"] in b2_held:
                    continue
                ok_ann, _ = check_announcement_red_flags(h["code"], today_str)
                if ok_ann:
                    valid_b2.append(h)
                if len(valid_b2) >= free_slots_b2:
                    break
            if valid_b2:
                b2_eq = float(b2["cash"]) + sum(x["shares"] * quotes.get(x["code"], {}).get("now", x["entry_price"]) for x in b2.get("open_positions", []))
                slot_cap = min(b2["cash"] / len(valid_b2), b2_eq * 0.50)
                for h in valid_b2:
                    sh = calc_order_shares(h["code"], min(slot_cap, b2["cash"]), h["price"])
                    if sh > 0:
                        reason = (
                            f"四分仓第2桶(中度超跌缩量真阳线)14:57尾盘买入: {h['name']}({h['code']}) "
                            f"流通市值{h['float_mcap_yi']}亿，10日乖离{h['bias10_pct']:.2f}%，量比{h['turn_ratio']:.2f}，日内分位{h['k_pos']:.2f}"
                        )
                        if not args.dry_run:
                            book_buy(state, ledger, "bucket_2_mid_oversold", h["code"], h["name"], sh, h["price"], now_cn().isoformat(timespec="seconds"), reason, {"sub_rule": "mid_oversold", "tp_pct": 0.04, "max_hold_days": 5, "prev_close": h["prev_close"], "signal_metrics": h})
                        bought_msgs.append(f"第2桶买入 {h['name']}({h['code']}) {sh}股@{h['price']:.2f} (乖离{h['bias10_pct']:.2f}%)")

        recompute_bucket_stats(ledger, quotes, trading_days, today_str)
        if not args.dry_run:
            run_hist[f"{today_str}:tail_buy"] = now_cn().isoformat(timespec="seconds")
            refresh_ssot_marks(state, quotes, today_str)
            save_ledger(ledger)
            portfolio_io.save_portfolio(state, reason=f"四分仓14:57尾盘扫描({len(bought_msgs)}笔成交)", auto_sync=True)

        summary = (
            f"[四分仓·14:57尾盘扫描 {today_str}] 全市场{len(quotes)}只 | "
            f"第1桶信号{len(b1_hits)}只(空槽{1 if not b1_held else 0})，第2桶信号{len(b2_hits)}只(空槽{free_slots_b2}) | "
            + ("成交: " + "；".join(bought_msgs) if bought_msgs else "本时段无新建仓(槽位已满或零信号)")
        )
        print(summary)
        if bought_msgs:
            send_feishu(summary, dry_run=args.dry_run)


def cmd_reconcile(args: argparse.Namespace) -> None:
    today_str = now_cn().strftime("%Y-%m-%d")
    if not args.force and not is_trading_day():
        print(f"[reconcile] {today_str} 非交易日，跳过")
        return

    ledger = load_ledger()
    state = json.load(open(ROOT / "portfolio_state.json", encoding="utf-8")) if args.dry_run else portfolio_io.load_portfolio()
    acc = state["accounts"]["a_share"]

    held_codes = [str(p["ticker"]).zfill(6) for p in acc.get("positions", [])]
    quotes = fetch_quotes_batch(held_codes, include_indices=True)
    trading_days = get_trading_days_recent(40)
    if today_str not in trading_days:
        trading_days.append(today_str)

    recompute_bucket_stats(ledger, quotes, trading_days, today_str)
    refresh_ssot_marks(state, quotes, today_str)

    # 零漏单与账实一致性硬断言
    anomalies = []
    sum_bkt_cash = round(sum(float(b["cash"]) for b in ledger["buckets"].values()), 2)
    ssot_cash = round(float(acc["cash"]), 2)
    if abs(sum_bkt_cash - ssot_cash) > 1.0:
        anomalies.append(f"四桶现金合计({sum_bkt_cash:,.2f})与SSOT现金({ssot_cash:,.2f})不一致")

    ledger_codes = sorted(op["code"] for b in ledger["buckets"].values() for op in b.get("open_positions", []))
    ssot_codes = sorted(str(p["ticker"]).zfill(6) for p in acc.get("positions", []))
    if ledger_codes != ssot_codes:
        anomalies.append(f"台账持仓({ledger_codes})与SSOT持仓({ssot_codes})不一致")

    run_hist = ledger.get("run_history", {})
    if not run_hist.get(f"{today_str}:tail_buy") and now_cn().hour >= 15:
        anomalies.append("今日14:57尾盘扫描未留存运行记录")

    cn_nav = float(acc["total_assets"])
    cn_ret = round((cn_nav / INITIAL_CAPITAL_CN - 1.0) * 100.0, 2)
    hs_q = quotes.get("sh000300", {})
    hs_c = float(hs_q.get("now") or 0.0)
    hs_ret = round((hs_c / DAY1_HS300_BASE - 1.0) * 100.0, 2) if hs_c > 0 else 0.0
    alpha = round(cn_ret - hs_ret, 2)

    if not args.dry_run:
        run_hist[f"{today_str}:reconcile"] = now_cn().isoformat(timespec="seconds")
        save_ledger(ledger)
        portfolio_io.save_portfolio(state, reason=f"四分仓15:08日终对账与收盘净值更新({today_str})", auto_sync=True)

        # 落盘 eod_done 标记与收盘摘要，闭环 16:40 eod_receipt_check
        EOD_DONE_DIR.mkdir(parents=True, exist_ok=True)
        ymd = today_str.replace("-", "")
        close_doc = {
            "date": today_str,
            "role": "astock",
            "written_at": now_cn().isoformat(timespec="seconds"),
            "engine": "quant_4bucket_engine.py reconcile",
            "a_share_nav": round(cn_nav, 2),
            "a_share_return_pct": cn_ret,
            "hs300_close": round(hs_c, 2),
            "hs300_return_pct": hs_ret,
            "net_alpha_pct": alpha,
            "positions": ssot_codes,
            "anomalies": anomalies,
        }
        (EOD_DONE_DIR / f"{ymd}_close.json").write_text(json.dumps(close_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (EOD_DONE_DIR / ymd).write_text(f"{now_cn().isoformat(timespec='seconds')} ok\n", encoding="utf-8")

    b_lines = []
    for bkey, label in [
        ("bucket_1_deep_oversold", "第1桶(极度超跌)"),
        ("bucket_2_mid_oversold", "第2桶(中度超跌)"),
        ("bucket_3_three_dt", "第3桶(三连跌停)"),
        ("bucket_4_high_board", "第4桶(高标接力)"),
    ]:
        b = ledger["buckets"][bkey]
        ops = "、".join(f"{x['name']}({x['unrealized_return_pct']:+.2f}%)" for x in b.get("open_positions", [])) or "空仓"
        wr = f"{b['win_rate']:.1f}%" if b.get("win_rate") is not None else "暂无已平仓新单"
        b_lines.append(f"{label}: 权益{b['bucket_equity']/1e4:.2f}万({b['bucket_return_pct']:+.2f}%) | 持仓:{ops} | 胜率:{wr}")

    if anomalies:
        msg = f"⛔[四分仓·15:08日终对账异常 {today_str}] 发现 {len(anomalies)} 项不一致:\n" + "\n".join(anomalies)
    else:
        msg = (
            f"[四分仓·15:08日终对账闭环 {today_str}] 账实核对零误差\n"
            f"账户净值: {cn_nav/1e4:.2f}万 (建账以来{cn_ret:+.2f}% vs 同期沪深300 {hs_ret:+.2f}%，净超额{alpha:+.2f}%)\n"
            + "\n".join(b_lines)
        )
    print(msg)
    send_feishu(msg, dry_run=args.dry_run)


def cmd_status(_args: argparse.Namespace) -> None:
    ledger = load_ledger()
    state = json.load(open(ROOT / "portfolio_state.json", encoding="utf-8"))
    acc = state["accounts"]["a_share"]
    codes = [str(p["ticker"]).zfill(6) for p in acc.get("positions", [])]
    quotes = fetch_quotes_batch(codes, include_indices=True)
    trading_days = get_trading_days_recent(40)
    today_str = now_cn().strftime("%Y-%m-%d")
    recompute_bucket_stats(ledger, quotes, trading_days, today_str)

    tot_eq = sum(b["bucket_equity"] for b in ledger["buckets"].values())
    base_eq = float(ledger["base_net_assets"])
    hs_c = float((quotes.get("sh000300") or {}).get("now") or 0.0)
    print(f"=== A股四分仓实时台账 ({now_cn():%Y-%m-%d %H:%M:%S}) ===")
    print(f"分仓基准资产(10-23收盘): {base_eq:,.2f} 元 | 当前总权益: {tot_eq:,.2f} 元 ({(tot_eq/base_eq-1)*100:+.2f}%)")
    print(f"建账以来(05-18起): 净值 {tot_eq:,.2f} 元 ({(tot_eq/INITIAL_CAPITAL_CN-1)*100:+.2f}%) | 沪深300现价 {hs_c:.2f} ({(hs_c/DAY1_HS300_BASE-1)*100:+.2f}%)")
    for bkey, b in ledger["buckets"].items():
        print(f"\n[{bkey}] {b['name']}")
        print(f"  现金: {b['cash']:,.2f} | 持仓市值: {b['open_market_value']:,.2f} | 桶权益: {b['bucket_equity']:,.2f} ({b['bucket_return_pct']:+.2f}%)")
        print(f"  已实现净盈亏: {b['realized_pnl']:+,.2f} | 浮动盈亏: {b['unrealized_pnl']:+,.2f} | 胜/负: {b['win_count']}/{b['loss_count']} (胜率: {b['win_rate']})")
        for op in b.get("open_positions", []):
            print(f"    OPEN: {op['code']} {op['name']} {op['shares']}股 买价={op['entry_price']:.2f}({op['entry_date']}) 现价={op['current_price']:.2f} ({op['unrealized_return_pct']:+.2f}%) 持有={op.get('hold_days',0)}日 止盈={op.get('tp_price')}")


# ===========================================================================
# 2026-10-26 ~ 2026-10-29 严格前视镜历史回放与补录 (backfill_1026_1029)
# ===========================================================================

def cmd_backfill_1026_1029(args: argparse.Namespace) -> None:
    """严格站在 10-26 09:25 -> 10-29 09:25 每个真实时点，用当时可见行情与手册硬规则全量补齐四桶交易与每日净值快照。"""
    state = portfolio_io.load_portfolio() if args.execute else json.load(open(ROOT / "portfolio_state.json", encoding="utf-8"))
    acc = state["accounts"]["a_share"]

    # 幂等检查：若已经补录过 2026-10-26 之后的四分仓交易，拒绝重复叠加
    already = [t for t in state.get("trade_log", []) if t.get("account") == "a_share" and str(t.get("date", "")) >= "2026-10-26"]
    if already:
        print(f"[backfill] 检测到 2026-10-26 起已有 {len(already)} 笔A股成交记录，拒绝重复回放")
        return

    # 核验 2026-10-26 09:24 期初状态锚点
    assert round(float(acc["cash"]), 2) == 8024673.38, f"期初现金不符: {acc['cash']}"
    assert len(acc["positions"]) == 1 and str(acc["positions"][0]["ticker"]) == "603278", "期初持仓不符"
    acc["positions"][0]["name"] = "大业股份"

    ledger = load_ledger()
    # 初始化四桶期初独立现金池（四桶初始净资产严格各 2,081,978.345 元，现金合计 8,024,673.38 元零误差）
    ledger["buckets"]["bucket_1_deep_oversold"].update({"cash": 2081978.34, "open_positions": [], "trades": []})
    ledger["buckets"]["bucket_2_mid_oversold"].update({"cash": 2081978.35, "open_positions": [], "trades": []})
    ledger["buckets"]["bucket_3_three_dt"].update({"cash": 2081978.35, "open_positions": [], "trades": []})
    ledger["buckets"]["bucket_4_high_board"].update({"cash": 1778738.34, "open_positions": [], "trades": []})
    # 修正原静态台账中世名科技周五复权价笔误(真实不复权收盘为 12.50 元)
    if ledger["buckets"]["bucket_1_deep_oversold"].get("monday_20261026_candidates"):
        ledger["buckets"]["bucket_1_deep_oversold"]["monday_20261026_candidates"][0]["friday_close_unadj"] = 12.50

    # 拉取精确历史日线（不复权真实成交价）用于逐日快照核对
    kl_map = {}
    for code in ["300522", "600847", "688203", "603278", "600838", "sh000300"]:
        kl_map[code] = {r["date"]: r for r in fetch_kline_bars(code, "2026-10-20", "2026-10-30", 15)}

    live_q = fetch_quotes_batch(["300522", "600847", "688203", "603278", "600838"], include_indices=True)

    # ---------------- 2026-10-26 (周一) ----------------
    # 1) 09:25 第1桶：300522 世名科技 周五收盘12.50，周一开盘12.32(-1.44%，落在-2.0%~+1.0%承接区间)，满额买入
    sh_300522 = calc_order_shares("300522", ledger["buckets"]["bucket_1_deep_oversold"]["cash"], 12.32)
    t1 = book_buy(
        state, ledger, "bucket_1_deep_oversold", "300522", "世名科技", sh_300522, 12.32,
        "2026-10-26T09:25:05+08:00",
        "四分仓第1桶(小微盘极度超跌缩量翻红真阳线)前视镜按规建仓: 10-23触发信号(流通33.0亿，10日乖离-14.15%，量比0.70，日内分位0.94，昨收12.50)，10-26 09:25开盘12.32(-1.44%)落在-2.0%至+1.0%区间内满桶买入；T+1起5日内摸+4.0%(12.81)止盈或第5日收盘卖",
        {"sub_rule": "deep_oversold", "tp_pct": 0.04, "max_hold_days": 5, "prev_close": 12.50, "signal_metrics": {"bias10_pct": -14.15, "turn_ratio": 0.70, "k_pos": 0.94}}, write_audit=args.execute,
    )

    # 2) 09:25 第2桶：600847 万里股份(昨收11.16，今开11.10即-0.54%) 与 688203 海正生材(昨收15.26，今开15.40即+0.92%) 均落在-2.0%~+1.0%，各12.5%等权买入
    half_b2 = round(ledger["buckets"]["bucket_2_mid_oversold"]["cash"] / 2.0, 2)
    sh_600847 = calc_order_shares("600847", half_b2, 11.10)
    t2 = book_buy(
        state, ledger, "bucket_2_mid_oversold", "600847", "万里股份", sh_600847, 11.10,
        "2026-10-26T09:25:06+08:00",
        "四分仓第2桶(微盘中度超跌缩量翻红真阳线·槽位1)前视镜按规建仓: 10-23触发信号(流通17.1亿，10日乖离-10.72%，量比0.75，日内分位0.96，昨收11.16)，10-26 09:25开盘11.10(-0.54%)按12.5%等权仓位买入；T+1起5日内摸+4.0%(11.54)止盈或第5日收盘卖",
        {"sub_rule": "mid_oversold", "tp_pct": 0.04, "max_hold_days": 5, "prev_close": 11.16, "signal_metrics": {"bias10_pct": -10.72, "turn_ratio": 0.75, "k_pos": 0.96}}, write_audit=args.execute,
    )
    sh_688203 = calc_order_shares("688203", ledger["buckets"]["bucket_2_mid_oversold"]["cash"], 15.40)
    t3 = book_buy(
        state, ledger, "bucket_2_mid_oversold", "688203", "海正生材", sh_688203, 15.40,
        "2026-10-26T09:25:07+08:00",
        "四分仓第2桶(微盘中度超跌缩量翻红真阳线·槽位2)前视镜按规建仓: 10-23触发信号(流通30.9亿，10日乖离-10.18%，量比0.55，日内分位0.89，昨收15.26)，10-26 09:25开盘15.40(+0.92%)按12.5%等权仓位买入(科创板200股整数倍)；买入当日冲高16.93受T+1交割限制不可卖，次日起摸+4.0%(16.02)止盈或第5日收盘卖",
        {"sub_rule": "mid_oversold", "tp_pct": 0.04, "max_hold_days": 5, "prev_close": 15.26, "signal_metrics": {"bias10_pct": -10.18, "turn_ratio": 0.55, "k_pos": 0.89}}, write_audit=args.execute,
    )

    # 3) 14:55 第4桶存量单退出：603278 大业股份 10-26 冲7板断板收假阴线(开17.56收17.25，+8.08%)，严格按台账预设「断板则收盘卖出」平仓(存量旧B单收尾不计入四分仓新开单胜率)
    t4 = book_sell(
        state, ledger, "bucket_4_high_board", "603278", 17.25,
        "2026-10-26T14:55:05+08:00",
        "四分仓第4桶存量单按规退出: 603278大业股份(10-22买入价14.51)周一冲击7连板断板收17.25(+8.08%假阴线)，严格执行台账预设规则『断板则收盘卖出』",
        count_in_winrate=False, write_audit=args.execute,
    )

    # 更新 2026-10-26 收盘快照
    q_1026 = {
        "300522": {"name": "世名科技", "now": kl_map["300522"]["2026-10-26"]["close"], "prev_close": 12.50, "high": kl_map["300522"]["2026-10-26"]["high"], "pct": -2.48},
        "600847": {"name": "万里股份", "now": kl_map["600847"]["2026-10-26"]["close"], "prev_close": 11.16, "high": kl_map["600847"]["2026-10-26"]["high"], "pct": -1.88},
        "688203": {"name": "海正生材", "now": kl_map["688203"]["2026-10-26"]["close"], "prev_close": 15.26, "high": kl_map["688203"]["2026-10-26"]["high"], "pct": 5.24},
    }
    refresh_ssot_marks(state, q_1026, "2026-10-26", hs300_close=kl_map["sh000300"]["2026-10-26"]["close"])

    # ---------------- 2026-10-27 (周二) ----------------
    # 09:25 核验：001368通达创智周一跌4.77%未封第3跌停，放弃；603278(+8.08%假阴)与002724(-3.49%)均不满足断板+2%~+7.5%真阳；600838上海九百10-26四板但同板块涨停仅1只(<2只)且10-27今开+7.19%(>6.5%)，零新开仓。
    # 盘中T+1核验：300522最高12.36(<12.81)、600847最高11.25(<11.54)、688203最高15.57(<16.02)，均未触及+4.0%止盈。
    q_1027 = {
        "300522": {"name": "世名科技", "now": kl_map["300522"]["2026-10-27"]["close"], "prev_close": 12.19, "high": kl_map["300522"]["2026-10-27"]["high"], "pct": -5.41},
        "600847": {"name": "万里股份", "now": kl_map["600847"]["2026-10-27"]["close"], "prev_close": 10.95, "high": kl_map["600847"]["2026-10-27"]["high"], "pct": -2.37},
        "688203": {"name": "海正生材", "now": kl_map["688203"]["2026-10-27"]["close"], "prev_close": 16.06, "high": kl_map["688203"]["2026-10-27"]["high"], "pct": -16.56},
    }
    refresh_ssot_marks(state, q_1027, "2026-10-27", hs300_close=kl_map["sh000300"]["2026-10-27"]["close"])

    # ---------------- 2026-10-28 (周三) ----------------
    # 09:25 核验：600838上海九百10-27五连板，今开+4.28%<=+5.5%，但前十流通股东锁仓比41.13%(2026Q2)/41.44%(2026Q3)低于五板手册50%硬门槛，且当日全场>=4板共3只(非独苗)，不买。
    # 盘中T+2核验：300522最高11.98(<12.81)、600847最高10.92(<11.54)、688203最高14.05(<16.02)，均未触及+4.0%止盈；第1/2桶满仓无空槽。
    q_1028 = {
        "300522": {"name": "世名科技", "now": kl_map["300522"]["2026-10-28"]["close"], "prev_close": 11.53, "high": kl_map["300522"]["2026-10-28"]["high"], "pct": 3.47},
        "600847": {"name": "万里股份", "now": kl_map["600847"]["2026-10-28"]["close"], "prev_close": 10.69, "high": kl_map["600847"]["2026-10-28"]["high"], "pct": 1.40},
        "688203": {"name": "海正生材", "now": kl_map["688203"]["2026-10-28"]["close"], "prev_close": 13.40, "high": kl_map["688203"]["2026-10-28"]["high"], "pct": 2.46},
    }
    refresh_ssot_marks(state, q_1028, "2026-10-28", hs300_close=kl_map["sh000300"]["2026-10-28"]["close"])

    # ---------------- 2026-10-29 (周四早盘及盘中实时) ----------------
    # 09:25 第3桶核验：001216华瓷股份3连跌停但前20日6次涨停(高标退潮否决)；002789 *ST建艺3连跌停属*ST退市风险警示硬门否决 -> 0合格信号。
    # 09:25 第4桶核验：
    #   - 000678襄阳轴承10-28五连板，今开19.37(+9.99%一字涨停)超+5.5%及+6.5%上限，不买；
    #   - 600838上海九百10-27五连板(>=4板高标)，10-28断板首日开13.88收13.99(+5.11%落入+2.0%~+7.5%且C>O真阳线)，同板块一般零售当日有600828茂业商业2连板涨停活口(>=1只)，10-29 09:25开盘14.20(+1.50%落入-4.0%~+5.0%) -> 100%命中第4桶子规则①(高标断板首日红盘真阳反包)，满桶买入！
    sh_600838 = calc_order_shares("600838", ledger["buckets"]["bucket_4_high_board"]["cash"], 14.20)
    t5 = book_buy(
        state, ledger, "bucket_4_high_board", "600838", "上海九百", sh_600838, 14.20,
        "2026-10-29T09:25:05+08:00",
        "四分仓第4桶(4板以上高标断板首日红盘真阳反包)前视镜按规建仓: 600838上海九百10-27五连板后，10-28断板首日收13.99(+5.11%真阳线，开13.88)，一般零售板块当日有600828茂业商业2连板涨停活口，10-29 09:25开盘14.20(+1.50%落在-4%至+5%内)满桶买入；买入当日T+0不可卖，次日起5日内摸+5.0%(14.91)止盈或第5日收盘卖",
        {"sub_rule": "high_break_rebound", "tp_pct": 0.05, "max_hold_days": 5, "prev_close": 13.99, "signal_metrics": {"break_day_pct": 5.11, "sector_alive": "600828茂业商业(2板)"}}, write_audit=args.execute,
    )

    ledger["daily_signal_audit"] = {
        "2026-10-26": {
            "open_0925": "第1桶买入300522世名科技@12.32(-1.44%)；第2桶等权买入600847万里股份@11.10(-0.54%)与688203海正生材@15.40(+0.92%)；第3桶无3连跌停；第4桶603278大业股份14:55断板@17.25卖出",
            "tail_1457": "第1桶、第2桶槽位已满，全市场新触发0只极度超跌",
        },
        "2026-10-27": {
            "open_0925": "第3桶001368通达创智周一跌4.77%未封第3跌停放弃；第4桶600838上海九百同板块昨仅1只涨停且今开+7.19%>6.5%不买，603278假阴/002724收负均不满足反包",
            "intraday_tail": "300522/600847/688203盘中最高均未触及+4.0%止盈线，继续持有(T+1第1日)",
        },
        "2026-10-28": {
            "open_0925": "第4桶600838上海九百5连板次日今开+4.28%，但前十流通股东锁仓比41.13%<50%五板手册硬门槛且当日>=4板共3只非独苗，按规跳过",
            "intraday_tail": "300522(最高11.98)/600847(最高10.92)/688203(最高14.05)均未触及+4.0%止盈线，继续持有(T+1第2日)；尾盘第2桶虽有3只触发但槽位已满不买",
        },
        "2026-10-29": {
            "open_0925": "第3桶001216华瓷股份(前20日6次涨停属妖股退潮)与002789 *ST建艺(*ST退市风险警示)均按硬门否决；第4桶000678襄阳轴承今开+9.99%一字涨停超+5.5%上限跳过，600838上海九百完全命中『5板断板首日+5.11%真阳+板块茂业商业2板活口+今开+1.50%』规则按14.20元满桶买入",
        },
    }
    ledger.setdefault("run_history", {})["2026-10-29:open"] = "2026-10-29T09:26:00+08:00"

    trading_days = get_trading_days_recent(40)
    if "2026-10-29" not in trading_days:
        trading_days.append("2026-10-29")
    recompute_bucket_stats(ledger, live_q, trading_days, "2026-10-29")
    refresh_ssot_marks(state, live_q, "2026-10-29")

    print("=== 前视镜回放结果核验 (2026-10-26 ~ 2026-10-29) ===")
    for tr in [t1, t2, t3, t4, t5]:
        print(f"  {tr['id']} {tr['timestamp']} {tr['action'].upper():4s} {tr['ticker']} {tr['name']} {tr['shares']}股 @ {tr['price']:.2f} val={tr['value']:,.2f} fee={tr['fee']:.2f}")
    print(f"SSOT cash={state['accounts']['a_share']['cash']:,.2f} | total_assets={state['accounts']['a_share']['total_assets']:,.2f}")
    for sn in state["performance"]["daily_snapshots"][-5:]:
        print("  snapshot:", sn)

    if args.execute:
        EOD_DONE_DIR.mkdir(parents=True, exist_ok=True)
        for d_hist in ("20261026", "20261027", "20261028"):
            (EOD_DONE_DIR / d_hist).write_text("backfilled by quant_4bucket_engine\n", encoding="utf-8")
        save_ledger(ledger)
        portfolio_io.save_portfolio(state, reason="补录10-26至10-29四分仓前视镜机械成交(TRD-0551至TRD-0555)及沪深300净超额快照", auto_sync=True)
        print("[backfill] ✅ 已原子写入 portfolio_state.json、quant_4bucket_ledger.json 与 audit-trail/")
    else:
        print("[backfill] DRY_RUN 完成，加 --execute 正式落盘")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="A股四分仓自动交易与对账引擎")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name in ("open", "intraday", "reconcile"):
        sp = sub.add_parser(name)
        sp.add_argument("--dry-run", action="store_true")
        sp.add_argument("--force", action="store_true")

    sp_tail = sub.add_parser("tail")
    sp_tail.add_argument("--phase", choices=["exit", "buy", "both"], default="both")
    sp_tail.add_argument("--dry-run", action="store_true")
    sp_tail.add_argument("--force", action="store_true")

    sub.add_parser("status")

    sp_bf = sub.add_parser("backfill_1026_1029")
    sp_bf.add_argument("--execute", action="store_true")
    return p


def main() -> None:
    args = build_parser().parse_args()
    dispatch = {
        "open": cmd_open,
        "intraday": cmd_intraday,
        "tail": cmd_tail,
        "reconcile": cmd_reconcile,
        "status": cmd_status,
        "backfill_1026_1029": cmd_backfill_1026_1029,
    }
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
