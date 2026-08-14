#!/usr/bin/env python3
"""
signal_sla_check.py — 信号闭环SLA检查(B6前瞻信号层 · 第③件: 闭环机制)
────────────────────────────────────────────────────────────────────────────
病灶(2026-08-14实证): 中芯国际涨价快讯09:23/09:29盘前入库(及时),12:10写进
watchlist标confidence="待深扫",到13:39仍是这个中间态没有终态——信号进来了但停摆。
同一天诊断还发现: 华虹公司/扬杰科技(同一条"成熟制程涨价"产业链上的另外两只)也停在
"待深扫"。这不是单点事故,是"待XX"这种中间态本身没有任何机制逼它闭环。

本脚本不代人做研究判断(判断仍需agent/人工Gate-Core深扫),只做一件事:
让"信号停在待深扫过夜"这件事在系统层面不可能被安静地忽略。

规则(⛔同一交易日内必须清零):
  任何高分信号(打分≥SLA_SCORE_THRESHOLD)且点名了具体驱动机制(=产业关键词命中,
  见news_layer.py discover_new_candidates)的候选,当天必须产出终态三选一:
    ① 挂进已有树 + probe/watch/reject裁决  → 体现为watchlist_config.json confidence
       字段离开"待XX"标记(改写为具体裁决,如letter grade/"reject"/"probe小仓")
    ② 不在任何树里 → 新建候选树条目(product_tree_map.json patch_log会留痕)
    ③ 明确记录"已评估无影响"+理由            → 写入 data/discovery_dispositions.jsonl
  收盘前(15:00 CST)仍处于pending = 只警告(还有时间); 收盘后仍pending = BREACH,
  写审计日志 data/sla_breaches.jsonl + 发nexus critical/high信号。

扫描源:
  ① watchlist_config.json 里 confidence 字段带"待XX"标记的条目
     — 用 git log -S<ticker> 反查该条目最早出现的commit日期, 推算"已挂起天数"
  ② data/news_today.json 的 discovery 字段(news_layer.py产出) — 今日新出现、
     score≥阈值、且尚未在watchlist出现、也没有dispositions记录的候选

用法:
  python3 signal_sla_check.py                # 检查现状(收盘前只警告,不算breach)
  python3 signal_sla_check.py --eod           # 日终对账模式(daily_run.sh收盘后调用)
  python3 signal_sla_check.py --json          # JSON输出
  python3 signal_sla_check.py --dispose 688981 --decision no_impact --reason "..."
                                               # 记录"已评估无影响"终态(选项③)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WATCHLIST_FILE = REPO / "watchlist_config.json"
NEWS_TODAY_FILE = REPO / "data" / "news_today.json"
BREACH_LOG = REPO / "data" / "sla_breaches.jsonl"
DISPOSITION_LOG = REPO / "data" / "discovery_dispositions.jsonl"
NEXUS_SIGNALS = Path.home() / ".claude" / "nexus" / "signals" / "pending"

CST = timezone(timedelta(hours=8))
NOW = datetime.now(CST)
TODAY = NOW.date()
MARKET_CLOSE_HOUR = 15  # A股15:00收盘(简化, 不做午休/节假日日历, 日终对账在收盘后跑即可)

PENDING_MARKERS = ("待深扫", "待确认", "待验证", "待评估", "待研究", "TBD", "PENDING")
SLA_SCORE_THRESHOLD = 80  # 与news_layer.py的KW_HIGH tier对齐(涨价/中标/减持等高优先级关键词的base分)


def _is_pending(confidence) -> bool:
    if not confidence:
        return False
    c = str(confidence)
    return any(m in c for m in PENDING_MARKERS)


def _git_first_seen(ticker: str) -> str | None:
    """用git log -S<ticker>反查该ticker字符串最早出现在watchlist_config.json的commit日期。
    ⚠️近似值: 找的是字符串首次出现,不是"变成pending状态"那一刻(若该ticker此前以其他confidence
    存在过又被改回pending,这里会算早)。作为SLA天数下界够用,精确定位需要逐commit diff太重。"""
    try:
        out = subprocess.run(
            ["git", "log", f"-S{ticker}", "--format=%ad", "--date=short", "--follow",
             "--", "watchlist_config.json"],
            cwd=REPO, capture_output=True, text=True, timeout=15,
        ).stdout.strip().splitlines()
        return out[-1] if out else None
    except Exception:
        return None


def load_watchlist() -> dict:
    with open(WATCHLIST_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_news_today() -> dict | None:
    if not NEWS_TODAY_FILE.exists():
        return None
    with open(NEWS_TODAY_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_dispositions_today() -> set[str]:
    """今日已record的disposition ticker集合(选项③已使用过的)。"""
    if not DISPOSITION_LOG.exists():
        return set()
    out = set()
    with open(DISPOSITION_LOG, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("date") == TODAY.isoformat():
                out.add(str(d.get("ticker")))
    return out


def scan_watchlist_pending() -> list[dict]:
    """扫描watchlist_config.json里所有confidence带'待XX'标记的条目,算挂起天数。"""
    wl = load_watchlist()
    out = []
    for lst in ("cn_watchlist", "us_watchlist", "us_watchlist_new"):
        for it in wl.get(lst, []) or []:
            if not _is_pending(it.get("confidence")):
                continue
            first_seen = _git_first_seen(it["ticker"])
            days_pending = None
            if first_seen:
                try:
                    fd = datetime.strptime(first_seen, "%Y-%m-%d").date()
                    days_pending = (TODAY - fd).days
                except Exception:
                    pass
            out.append({
                "source": "watchlist_pending",
                "ticker": it["ticker"], "name": it.get("name"),
                "market": lst.replace("_watchlist", "").replace("_new", ""),
                "confidence": it.get("confidence"), "status": it.get("status"),
                "sector": it.get("sector"), "thesis": (it.get("thesis") or "")[:120],
                "first_seen_date": first_seen, "days_pending": days_pending,
            })
    return out


def scan_discovery_open() -> list[dict]:
    """扫描news_today.json的discovery字段, 挑出今天新出现、够阈值、还没被处理的候选。
    '处理'的判定: ①已经出现在watchlist(任何confidence,哪怕还是pending也算case①在途,
    不重复报—但仍会被scan_watchlist_pending抓到) ②今天已有disposition记录(case③)。
    真正"完全没人管过"的只有: discovery命中 + 不在watchlist + 没有今日disposition记录。"""
    news = load_news_today()
    if not news:
        return []
    wl = load_watchlist()
    known_tickers = set()
    for lst in ("cn_watchlist", "us_watchlist", "us_watchlist_new"):
        for it in wl.get(lst, []) or []:
            known_tickers.add(str(it.get("ticker")))
    disposed_today = load_dispositions_today()

    out = []
    for c in news.get("discovery", []):
        if (c.get("first_seen_score") or 0) < SLA_SCORE_THRESHOLD:
            continue
        tk = c["ticker"]
        if tk in known_tickers or tk in disposed_today:
            continue  # 已经被①或③处理过, 不是"停摆"
        out.append({
            "source": "discovery_open",
            "ticker": tk, "name": c.get("name"),
            "tree": c.get("tree"), "node": c.get("node"),
            "matched_keyword": c.get("matched_keyword"),
            "first_seen_title": c.get("first_seen_title"),
            "first_seen_score": c.get("first_seen_score"),
            "first_seen_date": TODAY.isoformat(),  # discovery只反映"今日新闻源",不会跨日持久化
            "days_pending": 0,
        })
    return out


def classify(items: list[dict], eod: bool) -> tuple[list[dict], list[dict]]:
    """按SLA规则把每条pending项分成 warnings(还在grace period) / breaches(已过SLA)。
    规则: days_pending>=1(跨过至少一个自然日) → 必breach,不看eod。
         days_pending==0(今天才出现) → eod模式(收盘后跑)才算breach,盘中只warn。"""
    warnings, breaches = [], []
    for it in items:
        dp = it.get("days_pending")
        if dp is not None and dp >= 1:
            breaches.append(it)
        elif dp == 0 and eod:
            breaches.append(it)
        else:
            warnings.append(it)
    return warnings, breaches


def write_breach_log(breaches: list[dict]) -> None:
    if not breaches:
        return
    BREACH_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(BREACH_LOG, "a", encoding="utf-8") as f:
        for b in breaches:
            f.write(json.dumps({**b, "detected_at": NOW.isoformat(), "resolved": False},
                                ensure_ascii=False) + "\n")


def write_nexus_signal(breaches: list[dict]) -> Path | None:
    if not breaches:
        return None
    try:
        NEXUS_SIGNALS.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None
    ts = NOW.astimezone(timezone.utc)
    tickers = [b["ticker"] for b in breaches[:5]]
    sig_id = f"sig-{NOW.strftime('%Y%m%d-%H%M%S')}-signal_sla_check-breach-{'_'.join(tickers[:2]) or 'multi'}"
    names = "、".join(f"{b.get('name')}({b['ticker']})" for b in breaches[:8])
    d = {
        "id": sig_id,
        "from": "signal_sla_check",
        "to": ["research_astock", "trading_astock"],
        "priority": "high",
        "type": "process_breach",
        "title": f"信号闭环SLA breach: {len(breaches)}个信号停在待处理状态超过同一交易日",
        "content": f"以下标的的产业信号/待深扫状态已超出'同一交易日内出终态'的SLA: {names}。"
                    f"来源分布: {sorted({b['source'] for b in breaches})}。需要人工/agent立即给出"
                    f"probe/watch/reject裁决,或明确记录'已评估无影响'(signal_sla_check.py --dispose)。",
        "action_required": "对每个breach标的执行Gate级三选一终态裁决,不许继续挂'待XX'过夜",
        "source_context": "auto-detect:signal_sla_check",
        "created_at": ts.isoformat(),
        "expires_at": (ts + timedelta(days=3)).isoformat(),
        "lifecycle": "pending",
        "read_by": [],
        "acted_on": False,
    }
    fname = NEXUS_SIGNALS / f"{d['id']}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    return fname


def cmd_dispose(ticker: str, decision: str, reason: str) -> None:
    """记录终态选项③: 明确评估过、判定无影响。这是让'待XX'合法退出闭环的唯一非-watchlist路径,
    ⛔不写disposition也不改watchlist confidence = 依然算breach, 逼着裁决必须留痕。"""
    DISPOSITION_LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "date": TODAY.isoformat(), "ts": NOW.isoformat(),
        "ticker": ticker, "decision": decision, "reason": reason,
    }
    with open(DISPOSITION_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"已记录disposition: {ticker} → {decision} ({reason})")


def main() -> None:
    ap = argparse.ArgumentParser(description="信号闭环SLA检查(B6前瞻信号层)")
    ap.add_argument("--eod", action="store_true", help="日终对账模式: 今日新出现的pending也计入breach(daily_run.sh收盘后调用)")
    ap.add_argument("--json", action="store_true", help="JSON输出")
    ap.add_argument("--dispose", metavar="TICKER", help="记录终态选项③(已评估无影响)")
    ap.add_argument("--decision", default="no_impact", help="--dispose配套: 决定类型,默认no_impact")
    ap.add_argument("--reason", default="", help="--dispose配套: 理由(必须给,不许空)")
    ap.add_argument("--no-signal", action="store_true", help="不发nexus signal(测试用)")
    args = ap.parse_args()

    if args.dispose:
        if not args.reason:
            print("⛔ --dispose 必须带 --reason, 不许空理由", file=sys.stderr)
            sys.exit(1)
        cmd_dispose(args.dispose, args.decision, args.reason)
        return

    wl_pending = scan_watchlist_pending()
    disc_open = scan_discovery_open()
    all_items = wl_pending + disc_open
    warnings, breaches = classify(all_items, eod=args.eod)

    write_breach_log(breaches)
    sig_path = None if args.no_signal else write_nexus_signal(breaches)

    if args.json:
        print(json.dumps({
            "checked_at": NOW.isoformat(), "eod_mode": args.eod,
            "sla_score_threshold": SLA_SCORE_THRESHOLD,
            "warnings": warnings, "breaches": breaches,
            "nexus_signal": str(sig_path) if sig_path else None,
        }, ensure_ascii=False, indent=2))
        return

    print(f"=== 信号闭环SLA检查 {NOW.strftime('%Y-%m-%d %H:%M')} CST {'(日终对账)' if args.eod else '(盘中/警告模式)'} ===")
    print(f"watchlist待处理: {len(wl_pending)}条 | 今日discovery未处理: {len(disc_open)}条 | "
          f"阈值: score≥{SLA_SCORE_THRESHOLD}\n")

    if breaches:
        print(f"🔴 BREACH ({len(breaches)}条,已超同交易日SLA):")
        for b in breaches:
            dp = b.get("days_pending")
            dp_str = f"{dp}天" if dp is not None else "天数未知(git反查失败)"
            print(f"  [{b['source']}] {b.get('name')}({b['ticker']}) | 挂起{dp_str} | "
                  f"confidence={b.get('confidence','-')} | {b.get('thesis') or b.get('first_seen_title','')[:60]}")
    else:
        print("🟢 无breach")

    if warnings:
        print(f"\n🟡 WARNING ({len(warnings)}条,今日内,收盘前还有时间处理):")
        for w in warnings:
            print(f"  [{w['source']}] {w.get('name')}({w['ticker']}) | {w.get('thesis') or w.get('first_seen_title','')[:60]}")

    if sig_path:
        print(f"\n已发nexus signal: {sig_path}")
    print(f"审计日志: {BREACH_LOG if breaches else '(本次无新增)'}")


if __name__ == "__main__":
    main()
