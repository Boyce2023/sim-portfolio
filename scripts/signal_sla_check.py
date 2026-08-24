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
  ③ scan_history.jsonl 里最新裁决仍是'watch'且已过失效期(T16)的标的(2026-08-24新增)
     — 复用watch_tracker.py的裁决账本读取+交易日到期计算逻辑。watch池此前"进去就出
     不来"(实证: 义翘神州07-30挂watch,回踩从未到位,股价随后暴涨,全程无人行动,
     踏空成本约¥45.6万) ——watch_tracker.py负责检测+发提醒信号,但提醒可以被安静地
     无视; 本脚本补上闭环: 到期未出现新裁决(=scan_history.jsonl里该ticker没有更新的
     probe/watch/reject记录, 即"按趋势追"或"明确放弃") → 当日内是WARNING, 过了当天
     升级BREACH, 和①②走同一套classify/breach日志/nexus signal管线, 不允许静默过期。

⛔本脚本不做用户思路的替代判断——③的"处理"完全靠scan_history.jsonl的自然supersede
   机制判定(新裁决覆盖旧watch即算处理), 不额外发明状态机。

用法:
  python3 signal_sla_check.py                # 检查现状(收盘前只警告,不算breach)
  python3 signal_sla_check.py --eod           # 日终对账模式(daily_run.sh收盘后调用)
  python3 signal_sla_check.py --json          # JSON输出
  python3 signal_sla_check.py --dispose 688981 --decision no_impact --reason "..."
                                               # 记录"已评估无影响"终态(选项③)
  python3 signal_sla_check.py --backfill-prices [--limit 30]
                                               # 给scan_history.jsonl缺price字段的裁决
                                               # (尤其reject,案例库负样本回测的前提)
                                               # 回填历史价格,见下方"价格回填"一节
  python3 signal_sla_check.py --reject-backtest [--min-days 3]
                                               # 回测reject裁决后续走势: 我拒绝对了吗

────────────────────────────────────────────────────────────────────────────
价格回填 + reject回测(2026-08-24新增, B任务第②件: 负样本落盘)
────────────────────────────────────────────────────────────────────────────
病灶: scan_history.jsonl现有383条裁决记录(含95条reject)全部没有price字段——写入
路径在 workflows/astock_full_scan.workflow.js Step4(⛔该文件不在本脚本管辖范围,
只记录不改动): 该文件目前只对 action=='watch' 的标的追加记录到scan_history.jsonl,
probe/reject完全不在这条自动化路径里,历史上出现的probe/reject记录是agent手动补记的
(参考 memory_cases/cases_noise.md 的"黑洞"记录), 且从未带price。这意味着即使reject
被记下来了, 也无法回答"这只票后来涨了多少/我拒绝对不对"——没有基准价, 回测无从算起。

本脚本在自己的管辖范围内做能做的部分(不改写入路径,只做"回填+回测"两件事):
  --backfill-prices: 对scan_history.jsonl里decision∈{probe,watch,reject,hold}且缺
    price字段的记录, 按ticker分组只拉一次K线(减少请求数), 用新浪日K线精确匹配该
    date的收盘价; 若date==今天则用腾讯实时价。⛔不编造近似值: 匹配不到(停牌/未
    上市/超出K线回看窗口≈90个交易日/数据缺口)就留null+记录具体失败原因, 绝不用
    相邻日期顶替。原子重写(临时文件+行数校验一致才replace), 只加price/price_source
    字段, 不改动任何既有字段。--limit控制单次网络请求量(默认30, 383条历史积压分批
    处理, 不做成一次性重活)。
  --reject-backtest: 对已有price(原生或已回填)的reject记录(每ticker取最新一条),
    拉腾讯实时价算"拒绝以来涨跌%", 按阈值分类: <+10%=拒绝正确(过滤器有效) /
    +10%~+25%=临界(需人工复核) / >+25%=疑似错杀(过滤器可能过严)。这就是负样本
    回测本身——不是建议, 是给案例库的原始判定数据。

⛔遗留给上游的修复(本脚本管辖外, 需workflows/astock_full_scan.workflow.js的owner处理):
  Step4当前写死"对build_list里每个action=watch的标的"才追加scan_history.jsonl,
  应改为probe/watch/reject全量追加(且带上决策时刻的价格字段), 这样"价格回填"这个
  补丁未来才能退休——本脚本的回填/回测只是在写入路径修好之前的过渡性止血。
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
SCAN_HISTORY_FILE = REPO / "scan_history.jsonl"
BREACH_LOG = REPO / "data" / "sla_breaches.jsonl"
DISPOSITION_LOG = REPO / "data" / "discovery_dispositions.jsonl"
NEXUS_SIGNALS = Path.home() / ".claude" / "nexus" / "signals" / "pending"


def _import_watch_tracker():
    """懒加载watch_tracker.py当兄弟模块(同目录, 不需要包结构)。用try/except包裹:
    watch_tracker万一加载失败(网络库缺失等)不该拖垮①②两个既有SLA来源的正常工作。"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import watch_tracker as wt
        return wt
    except Exception as e:
        print(f"⚠️ watch_tracker模块加载失败: {e}", file=sys.stderr)
        return None

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


def scan_watch_expired() -> list[dict]:
    """T16 watch池到期未裁决(第③个SLA来源, 2026-08-24新增)。
    读scan_history.jsonl最新裁决仍是'watch'的标的(watch_tracker.load_latest_watches已
    做好"每ticker取最新一条"), 用同一套交易日到期计算(parse_plan+add_trading_days)
    判定是否已过失效期。'已处理'不需要额外状态机: 只要该ticker之后出现更新的裁决
    (probe/reject终态, 或watch_expiry被刷新为新一轮watch), load_latest_watches()
    天然只返回最新那条, 这里就看不到它了——自动supersede, 和①②同样的设计。
    已建仓的ticker(watch已经转化为持仓)不算未裁决, 跳过。

    ⛔⛔ 2026-08-24 本函数已停用(return []),原因不是bug是规则变更:
    **watch/等回调路径已被废除**。依据C3实证(scan_history.jsonl 384条裁决, 2026-06-24~08-24):
    reject/watch/probe三组中 **watch组表现最差** —— "等回调"策略在本regime系统性吃亏,
    与memory feedback_no_wait_pullback(06-25 MU教训)一致。裁决现改为 reject 或 probe 二选一。
    本函数原本在逼我给58条历史watch记录补裁决——**逼我完成一件已被证明没价值的工作**,
    而且每天重复报警58条,会让我对真告警脱敏(比没有告警器更糟)。
    存量58条历史watch记录保留在scan_history.jsonl里供回测/复盘,但不再产生待办。
    若将来watch路径被重新启用(需新证据推翻C3),删掉下面这个early return即可恢复。"""
    return []
    wt = _import_watch_tracker()
    if wt is None:
        return []
    watches = wt.load_latest_watches()
    if not watches:
        return []
    held = wt.load_portfolio_tickers()
    disposed_today = load_dispositions_today()
    out = []
    for ticker, rec in watches.items():
        if ticker in held or ticker in disposed_today:
            continue
        plan = wt.parse_plan(rec)
        try:
            watch_date = datetime.strptime(rec.get("date", ""), "%Y-%m-%d").date()
        except ValueError:
            continue  # date字段坏掉的记录watch_tracker自己会报✍️需人工补,这里不重复报
        expiry_date = wt.add_trading_days(watch_date, plan["days"])
        if TODAY < expiry_date:
            continue  # 未到期,不归本脚本管(watch_tracker自己有⏳临近失效提示)
        out.append({
            "source": "watch_expired",
            "ticker": ticker, "name": rec.get("name"),
            "market": "cn",
            "confidence": f"watch(已过期{max((TODAY - expiry_date).days, 0)}天未裁决)",
            "watch_date": rec.get("date"), "expiry_date": expiry_date.isoformat(),
            "thesis": (rec.get("one_line") or "")[:120],
            "first_seen_date": expiry_date.isoformat(),
            "days_pending": (TODAY - expiry_date).days,
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
        "content": f"以下标的的产业信号/待深扫/watch到期状态已超出'同一交易日内出终态'的SLA: {names}。"
                    f"来源分布: {sorted({b['source'] for b in breaches})}(watch_expired=T16 watch池"
                    f"到期未二选一裁决,禁止静默过期)。需要人工/agent立即给出"
                    f"probe/watch/reject裁决,或明确记录'已评估无影响'(signal_sla_check.py --dispose)。",
        "action_required": "对每个breach标的执行Gate级三选一终态裁决,不许继续挂'待XX'过夜",
        "source_context": "auto-detect:signal_sla_check",
        "created_at": ts.isoformat(),
        "expires_at": (ts + timedelta(days=3)).isoformat(),
        "lifecycle": "pending",
        "read_by": [],
        "acted_on": False,
    }
    # ⛔ 2026-08-24 加同日去重: 原实现每跑一次就新建一条signal(id带时分秒),
    # 实测一上午堆了2条同类breach信号,内容几乎一样只差计数(60个→58个)。
    # 告警器自己制造工作量 → 会让人对真告警脱敏,比没有告警器更糟。
    # 处理: 同一天同类型只保留一条,后续运行覆盖它(计数会刷新到最新)。
    today = ts.strftime("%Y%m%d")
    for old in NEXUS_SIGNALS.glob(f"sig-{today}-*-signal_sla_check-*.json"):
        try:
            old.unlink()
        except OSError:
            pass
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


def _load_scan_history_raw() -> list[dict]:
    """按行读取scan_history.jsonl,parse失败的行跳过(计日志,不让单行坏数据拖垮整体)。
    ⛔append-only文件,顺序即时间序,读入后不许打乱顺序(回填/重写都要保序)。"""
    if not SCAN_HISTORY_FILE.exists():
        return []
    out = []
    with open(SCAN_HISTORY_FILE, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"⚠️ scan_history.jsonl 第{i+1}行JSON解析失败,跳过: {e}", file=sys.stderr)
    return out


def _write_scan_history_raw(records: list[dict]) -> None:
    """原子重写scan_history.jsonl(仅用于'只加price字段不删/改其他字段'的回填操作)。
    ⛔写入前后行数必须相等,否则中止不落盘——防止任何一次读/写bug静默丢记录
    (D1数据准确性宪法: 宁可不写,不可丢数据)。"""
    tmp = SCAN_HISTORY_FILE.with_suffix(".jsonl.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    before = sum(1 for _ in open(SCAN_HISTORY_FILE, encoding="utf-8")) if SCAN_HISTORY_FILE.exists() else 0
    after = sum(1 for _ in open(tmp, encoding="utf-8"))
    if SCAN_HISTORY_FILE.exists() and after != before:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"scan_history.jsonl回填中止: 写入前{before}行→写入后{after}行,"
                            f"行数不一致,拒绝落盘(防止静默丢记录)")
    os.replace(tmp, SCAN_HISTORY_FILE)


def backfill_missing_prices(limit: int = 30) -> dict:
    """给scan_history.jsonl里缺price字段的裁决记录(尤其reject,案例库负样本回测的
    前提)补录'裁决当时价格'。⛔不编造: 历史日期用新浪日K线精确匹配该date的收盘价,
    匹配不到(停牌/新股未上市/超出K线回看窗口约90个交易日/数据源缺口)就留null+记录
    failed原因,绝不用相近日期估算充数。今天日期的记录用腾讯实时价(标注
    price_source=tencent_realtime,区别于历史收盘价)。
    limit: 单次最多回填几条,按ticker分组只拉一次K线以省请求数。"""
    wt = _import_watch_tracker()
    if wt is None:
        return {"error": "watch_tracker模块加载失败", "backfilled": 0}

    records = _load_scan_history_raw()
    if not records:
        return {"backfilled": 0, "failed": 0, "already_had_price": 0,
                "skipped_over_limit": 0, "total_missing": 0, "failed_detail": []}

    today_str = TODAY.isoformat()
    missing_idx = [i for i, r in enumerate(records)
                   if r.get("decision") in ("probe", "watch", "reject", "hold")
                   and r.get("ticker") and r.get("date")
                   and r.get("price") in (None, "")]
    already_had = sum(1 for r in records if r.get("price") not in (None, ""))

    to_process = missing_idx[:max(limit, 0)]
    skipped = len(missing_idx) - len(to_process)

    by_ticker: dict[str, list[int]] = {}
    for i in to_process:
        by_ticker.setdefault(records[i]["ticker"], []).append(i)

    today_tickers = [t for t, idxs in by_ticker.items()
                      if any(records[i]["date"] == today_str for i in idxs)]
    today_px = wt.fetch_prices(today_tickers) if today_tickers else {}

    backfilled = 0
    failed = []
    for ticker, idxs in by_ticker.items():
        hist_idxs = [i for i in idxs if records[i]["date"] != today_str]
        if hist_idxs:
            earliest = min(records[i]["date"] for i in hist_idxs)
            kl = wt.fetch_kline_since(ticker, earliest)
            kl_by_day = {row["day"]: row for row in kl} if kl else {}
            for i in hist_idxs:
                d = records[i]["date"]
                row = kl_by_day.get(d)
                if row is None:
                    failed.append({"ticker": ticker, "date": d,
                                    "reason": "新浪K线无该日期记录(停牌/未上市/超出~90交易日回看窗口/数据缺口)"})
                    continue
                try:
                    records[i]["price"] = float(row["close"])
                    records[i]["price_source"] = "sina_kline_close"
                    backfilled += 1
                except (TypeError, ValueError):
                    failed.append({"ticker": ticker, "date": d, "reason": "K线close字段解析失败"})
        for i in idxs:
            if records[i]["date"] != today_str:
                continue
            px = today_px.get(ticker)
            if px:
                records[i]["price"] = px["cur"]
                records[i]["price_source"] = "tencent_realtime"
                backfilled += 1
            else:
                failed.append({"ticker": ticker, "date": today_str, "reason": "腾讯实时价拉取失败"})

    if backfilled:
        _write_scan_history_raw(records)

    return {"backfilled": backfilled, "failed": len(failed), "failed_detail": failed,
            "already_had_price": already_had, "skipped_over_limit": skipped,
            "total_missing": len(missing_idx)}


def reject_backtest(min_days: int = 3) -> list[dict]:
    """回测'我拒绝对了吗': 对scan_history.jsonl里decision=='reject'且已有price(原生
    或已被--backfill-prices回填)的记录(每ticker只取最新一条,代表当前过滤器状态),
    用腾讯实时价算'拒绝以来涨跌%',按阈值分类(阈值透明非黑箱,供人工复核而非替代判断):
      <+10%          → 拒绝正确(过滤器有效)
      +10% ~ +25%    → 临界(需人工复核)
      >+25%          → 疑似错杀(过滤器可能过严)
    min_days: 拒绝未满N个自然日的不纳入判定(样本太新,涨跌噪音大,不下结论)。"""
    records = _load_scan_history_raw()
    rejects = [r for r in records if r.get("decision") == "reject" and r.get("ticker")
               and r.get("price") not in (None, "") and r.get("date")]
    if not rejects:
        return []
    wt = _import_watch_tracker()
    if wt is None:
        return []

    latest_reject: dict[str, dict] = {}
    for r in rejects:
        t = r["ticker"]
        if t not in latest_reject or r["date"] > latest_reject[t]["date"]:
            latest_reject[t] = r

    live = wt.fetch_prices(list(latest_reject.keys()))

    out = []
    for ticker, r in latest_reject.items():
        try:
            d0 = datetime.strptime(r["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        days_since = (TODAY - d0).days
        if days_since < min_days:
            continue
        px = live.get(ticker)
        reject_price = r.get("price")
        if not px:
            out.append({"ticker": ticker, "name": r.get("name"), "date": r["date"],
                        "days_since": days_since, "reject_price": reject_price,
                        "cur_price": None, "pct_change": None,
                        "verdict": "现价拉取失败,无法判定",
                        "reason": (r.get("one_line") or "")[:100]})
            continue
        pct = (px["cur"] - reject_price) / reject_price if reject_price else None
        if pct is None:
            verdict = "拒绝价缺失,无法判定"
        elif pct < 0.10:
            verdict = "拒绝正确(过滤器有效)"
        elif pct < 0.25:
            verdict = "临界(需人工复核)"
        else:
            verdict = "疑似错杀(过滤器可能过严)"
        out.append({"ticker": ticker, "name": r.get("name"), "date": r["date"],
                    "days_since": days_since, "reject_price": reject_price,
                    "cur_price": px["cur"],
                    "pct_change": round(pct * 100, 1) if pct is not None else None,
                    "verdict": verdict, "reason": (r.get("one_line") or "")[:100]})
    out.sort(key=lambda x: (x["pct_change"] is None, -(x["pct_change"] or -999)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="信号闭环SLA检查(B6前瞻信号层)")
    ap.add_argument("--eod", action="store_true", help="日终对账模式: 今日新出现的pending也计入breach(daily_run.sh收盘后调用)")
    ap.add_argument("--json", action="store_true", help="JSON输出")
    ap.add_argument("--dispose", metavar="TICKER", help="记录终态选项③(已评估无影响)")
    ap.add_argument("--decision", default="no_impact", help="--dispose配套: 决定类型,默认no_impact")
    ap.add_argument("--reason", default="", help="--dispose配套: 理由(必须给,不许空)")
    ap.add_argument("--no-signal", action="store_true", help="不发nexus signal(测试用)")
    ap.add_argument("--backfill-prices", action="store_true",
                     help="给scan_history.jsonl缺price字段的裁决记录回填历史价格(新浪K线/腾讯实时价)")
    ap.add_argument("--limit", type=int, default=30, help="--backfill-prices配套: 单次最多回填几条,默认30")
    ap.add_argument("--reject-backtest", action="store_true",
                     help="回测scan_history.jsonl里reject裁决的后续走势(负样本回测: 我拒绝对了吗)")
    ap.add_argument("--min-days", type=int, default=3, help="--reject-backtest配套: 拒绝未满N天不纳入判定,默认3")
    args = ap.parse_args()

    if args.dispose:
        if not args.reason:
            print("⛔ --dispose 必须带 --reason, 不许空理由", file=sys.stderr)
            sys.exit(1)
        cmd_dispose(args.dispose, args.decision, args.reason)
        return

    if args.backfill_prices:
        result = backfill_missing_prices(limit=args.limit)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"=== scan_history.jsonl 价格回填 {NOW.strftime('%Y-%m-%d %H:%M')} CST ===")
            if "error" in result:
                print(f"⛔ {result['error']}")
            else:
                print(f"待回填总数: {result['total_missing']} | 本次回填: {result['backfilled']} | "
                      f"失败: {result['failed']} | 已有price跳过: {result['already_had_price']} | "
                      f"超--limit未处理: {result['skipped_over_limit']}")
                for f in result.get("failed_detail", []):
                    print(f"  ✗ {f['ticker']} {f['date']}: {f['reason']}")
        return

    if args.reject_backtest:
        rows = reject_backtest(min_days=args.min_days)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            print(f"=== reject回测(我拒绝对了吗) {NOW.strftime('%Y-%m-%d %H:%M')} CST | "
                  f"样本{len(rows)}只(min_days={args.min_days}) ===")
            if not rows:
                print("(无可判定样本: reject记录缺price,先跑 --backfill-prices)")
            for r in rows:
                pct_str = f"{r['pct_change']:+.1f}%" if r["pct_change"] is not None else "N/A"
                print(f"  [{r['verdict']}] {r.get('name')}({r['ticker']}) | "
                      f"拒绝日{r['date']}(距今{r['days_since']}天) | "
                      f"拒绝价{r['reject_price']}→现价{r.get('cur_price','-')} ({pct_str}) | "
                      f"{r.get('reason','')[:60]}")
        return

    wl_pending = scan_watchlist_pending()
    disc_open = scan_discovery_open()
    watch_expired = scan_watch_expired()
    all_items = wl_pending + disc_open + watch_expired
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
          f"watch到期未裁决: {len(watch_expired)}条 | 阈值: score≥{SLA_SCORE_THRESHOLD}\n")

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
