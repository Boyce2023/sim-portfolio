# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
verify_isolation.py — 持仓泄露检测器 (H1 执行层)

统一互联管道 Spec §2.4。三级扫描 nexus/signals/ + nexus/truth/(除 portfolio/),
按 isolation_schema.json 的 FORBIDDEN 黑名单 + 正则 + 隐含模式检测,
任何能反推账户状态(量/价/成本/盈亏/现金/仓位规模)的字段进入跨 session
可读的 signal/truth 文件即为违规。

设计宪法锚点:
  H1  持仓绝对不跨 session。持仓明细只存在于 portfolio_state.json(SSOT) 与
      truth/portfolio/positions.json(只读参考层, restricted: tracking-only),
      绝不进 signal payload。
  H3  补缺口不重构。本脚本 additive, 落 sim-portfolio/scripts/ 与既有 6 脚本同栈。

三级扫描:
  1. scan_json_keys()    — 递归 JSON 键名匹配 FORBIDDEN 黑名单
  2. scan_content_regex() — 正则扫 value(shares 数字 / avg_cost / ¥6位数 等量价模式)
  3. scan_implicit()     — account 级 positions[] 数组检测(隐含整账户泄露)

分类规则 (category_check):
  - signals/ 下任何命中           = violation (硬, exit 1)
  - truth/portfolio/*             = restricted: tracking-only, 记为 restricted_ok 不报错
    (positions / shadow-portfolio / trade-outcomes / calls-log 同属敏感参考层)
  - truth/ 其余(macro/companies/personal) 出现 FORBIDDEN = violation
  - signals/_schema.json / isolation_schema.json / routing.json 等规范文件
    出现黑名单"词"是定义而非数据 → 白名单豁免(schema_definition)

输出: audit_isolation.json
  {
    "generated_at": ...,
    "clean": bool,
    "scanned_files": N,
    "violations": [{file, line, field, kind, snippet, suggestion}],
    "restricted_ok": [...],   # truth/portfolio 合法敏感文件, 仅记录不报错
  }

退出码:
  0  clean (无 violation)        — pipeline 继续
  1  有 violation                — daily_run.sh gate 阻断 sync_nexus, 防泄露推公网
  2  内部错误(读不到 nexus 等)

模式:
  (默认)        全树扫描, 写 audit_isolation.json, 有 violation → exit 1
  --baseline    记录当前干净基线到 isolation_baseline.json (违规也记录, 但不阻断)
  --quiet       只输出 exit code + 一行摘要 (供 daily_run.sh gate)
  --json        把 audit 报告打到 stdout (供其他脚本 import / 管道)
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径锚定 — 与 maintain_truth.py / sync_nexus.py 同一约定
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
NEXUS_DIR = Path.home() / ".claude" / "nexus"
SIGNALS_DIR = NEXUS_DIR / "signals"
TRUTH_DIR = NEXUS_DIR / "truth"
ISOLATION_SCHEMA = SIGNALS_DIR / "isolation_schema.json"
AUDIT_OUT = SCRIPT_DIR / "audit_isolation.json"
BASELINE_OUT = SCRIPT_DIR / "isolation_baseline.json"

BJT = timezone(timedelta(hours=8))
NOW = datetime.now(BJT)

# ---------------------------------------------------------------------------
# 内置默认 (isolation_schema.json 未建时的 fallback — 见 §2.1)
# 一旦 isolation_schema.json 存在, 以其为准 (load_isolation_schema 合并)
# ---------------------------------------------------------------------------
DEFAULT_FORBIDDEN_FIELDS = [
    # 个仓量价
    "shares", "avg_cost", "cost_basis", "current_price",
    "market_value", "unrealized_pnl", "unrealized_pnl_pct",
    "stop_loss", "position_size", "position_pct",
    # 账户级
    "account_balance", "cash", "total_assets", "nav",
    # account 级数组
    "positions",
]

# signal payload 允许的决策语义字段 (§2.1 ALLOWED) — 仅作文档/参考, 不用于判定
DEFAULT_ALLOWED_FIELDS = [
    "affected_tickers", "direction", "catalyst", "expected_timing",
    "key_dates", "confidence", "conviction_level", "evidence",
    "truth_refs", "change_magnitude", "rating",
]

# 内容正则 — 检测量价"模式"(即使字段名被改写 / 藏在 prose 里, value 形态仍会暴露)
# 用元组 (kind, 编译后正则) 便于报告。
#
# ⚠️ 设计要点: 量价词(avg_cost/stop_loss 等)的真实 JSON 字段由级别1(forbidden_key)
# 结构化捕获; 内容正则只补两类级别1 抓不到的:
#   (a) value-bearing 形态  — "stop_loss": 30.42 / avg_cost=245.99 (字段名被改写或非标准 JSON)
#   (b) prose 泄露          — "335股@$20.18" / "120 shares + 2 Call" / "¥1634500"
# 因此量价词正则一律要求"后跟分隔符+数字"(value context), 避免误伤分析性 tag
# (如 "tags":["stop-loss"] / 句子里的 "stop-loss" 讨论词)。这是真实树验证后的修正:
# 2525HK/600089 的 "stop-loss" 是 bear-case tag 不是账户止损, 不应 flag。
_VAL = r"['\"]?\s*[:=]\s*['\"]?\s*[\d¥￥$.,]"  # 后接 :/= + 数字/货币 = value 形态
DEFAULT_CONTENT_PATTERNS = [
    # prose 泄露: 数字 + shares/股 (持仓量) — 这是最常见的"藏在叙述里"的泄露
    ("shares_count", re.compile(r"\b\d{2,}\s*(?:shares|股)\b", re.IGNORECASE)),
    # value-bearing 量价字段 (字段名被改写 / 非标准 JSON 时兜底)
    ("avg_cost", re.compile(r"avg[._\- ]?cost" + _VAL, re.IGNORECASE)),
    ("cost_basis", re.compile(r"cost[._\- ]?basis" + _VAL, re.IGNORECASE)),
    ("market_value", re.compile(r"market[._\- ]?value" + _VAL, re.IGNORECASE)),
    ("unrealized_pnl", re.compile(r"unrealized[._\- ]?pnl" + _VAL, re.IGNORECASE)),
    ("stop_loss", re.compile(r"stop[._\- ]?loss" + _VAL, re.IGNORECASE)),
    # prose 泄露: realized/unrealized P&L 带金额
    ("realized_pnl", re.compile(r"(?:realized|unrealized)\s*P&?L\s*[-+]?\s*[¥￥$]?\s*\d", re.IGNORECASE)),
    # ¥ + 6位以上数字 = 账户/持仓级金额 (个股价格通常 <6 位, 持仓市值 6 位起)
    ("cny_large_amount", re.compile(r"[¥￥]\s*\d{6,}")),
    # $ + 大额 ( >=6 位, 含千分位 ) = 账户/持仓级金额
    ("usd_large_amount", re.compile(r"\$\s*\d{1,3}(?:,\d{3}){2,}")),
    # 账户口径金额词带 value: total_assets / NAV / 账户余额
    ("account_balance", re.compile(
        r"(?:total[._\- ]?assets|net[._\- ]?asset[._\- ]?value|账户余额|\bnav\b)" + _VAL,
        re.IGNORECASE)),
]

# 这些文件是"定义"黑名单词的规范文件本身, 出现关键词是 schema/路由定义而非真实持仓数据
# → 白名单豁免, 不当 violation
SCHEMA_DEFINITION_FILES = {
    "isolation_schema.json",
    "_schema.json",
    "_schema-extended.json",
    "routing.json",
    "routing.json.proposed",
    "_index.json",
}

# truth/portfolio/ 下合法的敏感参考层文件 (restricted: tracking-only)
# 这些文件"应该"含持仓量价 — 它们是只读参考层, 不报 violation, 仅记录为 restricted_ok
RESTRICTED_PORTFOLIO_FILES = {
    "positions.json",
    "shadow-portfolio.json",
    "trade-outcomes.json",
    "calls-log.json",
}


# ---------------------------------------------------------------------------
# Schema 加载 (graceful fallback)
# ---------------------------------------------------------------------------
def load_isolation_schema() -> dict:
    """
    加载 isolation_schema.json。若不存在(sibling task 尚未建), 用内置默认。
    返回 {forbidden_fields, allowed_fields, content_patterns, restricted_files}
    content_patterns 始终用内置编译版(schema 里若有 regex 字符串则追加编译)。
    """
    forbidden = list(DEFAULT_FORBIDDEN_FIELDS)
    allowed = list(DEFAULT_ALLOWED_FIELDS)
    restricted = set(RESTRICTED_PORTFOLIO_FILES)
    patterns = list(DEFAULT_CONTENT_PATTERNS)
    schema_loaded = False

    if ISOLATION_SCHEMA.exists():
        try:
            data = json.loads(ISOLATION_SCHEMA.read_text(encoding="utf-8"))
            schema_loaded = True
            # 字段黑名单 — schema 优先, 与内置取并集 (防止 schema 漏定义关键字段)
            sf = data.get("forbidden_fields") or data.get("FORBIDDEN") or []
            if isinstance(sf, dict):  # 容忍 {field: desc} 形态
                sf = list(sf.keys())
            forbidden = sorted(set(forbidden) | set(sf))

            sa = data.get("allowed_fields") or data.get("ALLOWED") or []
            if isinstance(sa, dict):
                sa = list(sa.keys())
            allowed = sorted(set(allowed) | set(sa))

            # restricted (tracking-only) 文件清单
            sr = data.get("restricted_files") or data.get("restricted") or []
            if isinstance(sr, dict):
                sr = list(sr.keys())
            if sr:
                restricted = set(restricted) | {Path(p).name for p in sr}

            # schema 里若提供额外 regex 字符串, 编译追加
            for raw in (data.get("content_patterns") or []):
                try:
                    if isinstance(raw, dict):
                        kind = raw.get("kind", "schema_pattern")
                        rx = raw.get("regex", "")
                    else:
                        kind, rx = "schema_pattern", str(raw)
                    if rx:
                        patterns.append((kind, re.compile(rx, re.IGNORECASE)))
                except re.error:
                    pass
        except (json.JSONDecodeError, OSError) as e:
            print(f"[verify_isolation] WARN: isolation_schema.json 读取失败, 用内置默认: {e}",
                  file=sys.stderr)

    return {
        "forbidden_fields": forbidden,
        "allowed_fields": allowed,
        "content_patterns": patterns,
        "restricted_files": restricted,
        "schema_loaded": schema_loaded,
    }


# ---------------------------------------------------------------------------
# 行号定位 — 在原始文本中找某个 JSON key 第一次出现的行 (尽力而为)
# ---------------------------------------------------------------------------
def find_key_line(raw_text: str, key: str, occurrence_idx: int = 0) -> int:
    """在原始文本里定位 "key" 出现的行号 (1-based)。失败返回 0。"""
    pat = re.compile(r'"' + re.escape(key) + r'"\s*:')
    hits = [m.start() for m in pat.finditer(raw_text)]
    if not hits:
        return 0
    idx = min(occurrence_idx, len(hits) - 1)
    return raw_text.count("\n", 0, hits[idx]) + 1


# ---------------------------------------------------------------------------
# 级别 1: 递归 JSON 键名匹配黑名单
# ---------------------------------------------------------------------------
def scan_json_keys(obj, forbidden: set, path="$"):
    """递归遍历, 命中黑名单键名 → yield (field, json_path)。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in forbidden:
                yield (k, f"{path}.{k}")
            yield from scan_json_keys(v, forbidden, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            yield from scan_json_keys(item, forbidden, f"{path}[{i}]")


# ---------------------------------------------------------------------------
# 级别 2: 内容正则扫 value
# ---------------------------------------------------------------------------
def scan_content_regex(raw_text: str, patterns):
    """逐行跑量价正则。yield (kind, line_no, snippet)。"""
    for lineno, line in enumerate(raw_text.splitlines(), start=1):
        for kind, rx in patterns:
            m = rx.search(line)
            if m:
                snippet = line.strip()
                if len(snippet) > 140:
                    snippet = snippet[:137] + "..."
                yield (kind, lineno, snippet)


# ---------------------------------------------------------------------------
# 级别 3: 隐含泄露 — account 级 positions[] 数组
# ---------------------------------------------------------------------------
def scan_implicit(obj):
    """
    检测 account 级持仓数组: 顶层或嵌套出现 'positions' 键, 且其值是
    含 ticker + (shares|market_value|avg_cost) 的对象数组 = 整账户泄露。
    yield (json_path, count)。
    """
    def walk(o, path="$"):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("positions", "holdings") and isinstance(v, list) and v:
                    sample = v[0] if isinstance(v[0], dict) else {}
                    leak_keys = {"shares", "market_value", "avg_cost",
                                 "unrealized_pnl_pct", "current_price"}
                    if leak_keys & set(sample.keys()):
                        yield (f"{path}.{k}", len(v))
                yield from walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, item in enumerate(o):
                yield from walk(item, f"{path}[{i}]")
    yield from walk(obj)


# ---------------------------------------------------------------------------
# 修复建议
# ---------------------------------------------------------------------------
def suggestion_for(field_or_kind: str) -> str:
    f = field_or_kind.lower()
    if f in ("positions", "holdings"):
        return ("删除整个 positions[] 数组。signal 只传 affected_tickers (纯 ticker 列表), "
                "持仓明细留在 portfolio_state.json (SSOT)。")
    if "shares" in f or "shares_count" in f:
        return "删除 shares。如需表达开/平仓, 用 direction(long/short)+affected_tickers, 不带量。"
    if "cost" in f or "avg_cost" in f or "cost_basis" in f:
        return "删除成本字段。成本只存在于 truth/portfolio/positions.json(tracking-only), 绝不进 signal。"
    if "value" in f or "market_value" in f:
        return "删除 market_value/金额。signal 用 change_magnitude(minor/moderate/major) 表达量级, 不传金额。"
    if "pnl" in f:
        return "删除盈亏字段。盈亏是账户状态, signal 不承载; 决策语义用 thesis/direction/catalyst 表达。"
    if "stop_loss" in f:
        return "删除 stop_loss。止损线是账户级风控参数, 不跨 session。"
    if "cash" in f or "balance" in f or "asset" in f or "nav" in f:
        return "删除账户级现金/总资产/NAV。这些绝不进任何跨 session 可读文件。"
    if f in ("position_size", "position_pct"):
        return "删除仓位规模。conviction_level(信心等级) 可传, 但仓位百分比/规模不可传。"
    if "cny_large_amount" in f or "usd_large_amount" in f or "amount" in f:
        return "疑似账户/持仓级金额(6位+)。改用相对量级描述(change_magnitude), 不写绝对金额。"
    return ("移除该量价/账户字段。signal 只传决策语义(thesis/催化剂/方向/事件/信心等级), "
            "不传账户状态(量/价/成本/盈亏)。")


# ---------------------------------------------------------------------------
# 单文件扫描
# ---------------------------------------------------------------------------
def scan_file(fp: Path, schema: dict):
    """
    扫一个 JSON 文件, 返回 (violations, restricted_record_or_None, hit_count)。
    violations: list[dict]
    restricted_record: truth/portfolio 合法敏感文件 → 记录但不报错
    """
    forbidden = set(schema["forbidden_fields"])
    patterns = schema["content_patterns"]
    restricted_files = schema["restricted_files"]

    name = fp.name
    rel = _rel(fp)

    # 规范定义文件豁免 (黑名单词是定义而非数据)
    if name in SCHEMA_DEFINITION_FILES:
        return [], None, 0

    try:
        raw = fp.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return ([{
            "file": rel, "line": 0, "field": "<read-error>",
            "kind": "read_error", "snippet": str(e),
            "suggestion": "文件无法读取, 人工检查编码/权限。",
        }], None, 1)

    # ---- 分类: truth/portfolio 下的 restricted 敏感文件 ----
    is_portfolio = (TRUTH_DIR / "portfolio") in fp.parents
    if is_portfolio:
        if name in restricted_files:
            # 合法只读参考层: 记录为 restricted_ok, 不报 violation
            return [], {
                "file": rel,
                "status": "restricted: tracking-only",
                "note": "合法敏感参考层, 仅 tracking workstream 可读; 不进 signal。",
            }, 0
        # portfolio 下的未知文件 — 也按敏感处理, 不报错但记录待人工确认
        return [], {
            "file": rel,
            "status": "restricted: portfolio-dir (unlisted)",
            "note": "位于 truth/portfolio/ 但不在 restricted 清单, 默认按敏感处理。",
        }, 0

    # ---- 非 portfolio 文件: 任何黑名单命中都是 violation ----
    violations = []

    # 尝试结构化解析(用于键名扫描 + 隐含数组)
    parsed = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None  # 不是合法 JSON, 仅跑正则

    seen_field_count = {}
    if parsed is not None:
        # 级别 1: 键名
        for field, jpath in scan_json_keys(parsed, forbidden):
            occ = seen_field_count.get(field, 0)
            seen_field_count[field] = occ + 1
            violations.append({
                "file": rel,
                "line": find_key_line(raw, field, occ),
                "field": field,
                "kind": "forbidden_key",
                "snippet": jpath,
                "suggestion": suggestion_for(field),
            })
        # 级别 3: 隐含 positions[] 数组
        for jpath, count in scan_implicit(parsed):
            violations.append({
                "file": rel,
                "line": find_key_line(raw, jpath.rsplit(".", 1)[-1]),
                "field": "positions[]",
                "kind": "implicit_account_array",
                "snippet": f"{jpath} (含 {count} 条持仓明细)",
                "suggestion": suggestion_for("positions"),
            })

    # 级别 2: 内容正则 (对所有文件跑, 含非法 JSON / 改写过字段名的泄露)
    for kind, lineno, snippet in scan_content_regex(raw, patterns):
        violations.append({
            "file": rel,
            "line": lineno,
            "field": kind,
            "kind": "content_pattern",
            "snippet": snippet,
            "suggestion": suggestion_for(kind),
        })

    return violations, None, len(violations)


def _rel(fp: Path) -> str:
    """相对 nexus 根的可读路径。"""
    try:
        return str(fp.relative_to(NEXUS_DIR))
    except ValueError:
        return str(fp)


# ---------------------------------------------------------------------------
# 全树扫描
# ---------------------------------------------------------------------------
def collect_targets():
    """
    扫描目标:
      - signals/ 全部 *.json (pending + processed + 根级 schema)
      - truth/ 全部 *.json, 含 portfolio/(走 restricted 分类逻辑)
    """
    targets = []
    if SIGNALS_DIR.exists():
        targets += sorted(SIGNALS_DIR.rglob("*.json"))
    if TRUTH_DIR.exists():
        targets += sorted(TRUTH_DIR.rglob("*.json"))
    return targets


def run_scan(schema: dict) -> dict:
    targets = collect_targets()
    all_violations = []
    restricted = []
    scanned = 0

    for fp in targets:
        scanned += 1
        vios, restricted_rec, _ = scan_file(fp, schema)
        if vios:
            all_violations.extend(vios)
        if restricted_rec:
            restricted.append(restricted_rec)

    report = {
        "generated_at": NOW.isoformat(),
        "nexus_dir": str(NEXUS_DIR),
        "schema_source": "isolation_schema.json" if schema["schema_loaded"] else "built-in default",
        "scanned_files": scanned,
        "violation_count": len(all_violations),
        "clean": len(all_violations) == 0,
        "violations": all_violations,
        "restricted_ok": restricted,
        "forbidden_fields_used": schema["forbidden_fields"],
    }
    return report


def atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="持仓泄露检测器 (H1 执行层) — 扫 nexus/signals + nexus/truth")
    ap.add_argument("--baseline", action="store_true",
                    help="记录当前干净基线到 isolation_baseline.json (不阻断 pipeline)")
    ap.add_argument("--quiet", action="store_true",
                    help="只输出一行摘要 + exit code (供 daily_run.sh gate)")
    ap.add_argument("--json", action="store_true",
                    help="把完整 audit 报告打到 stdout")
    args = ap.parse_args(argv)

    if not NEXUS_DIR.exists():
        print(f"[verify_isolation] ERROR: nexus 目录不存在: {NEXUS_DIR}", file=sys.stderr)
        return 2

    schema = load_isolation_schema()
    report = run_scan(schema)

    # baseline 模式: 写基线快照, 永远 exit 0 (用于建立"当前状态"参照)
    if args.baseline:
        atomic_write_json(BASELINE_OUT, report)
        status = "CLEAN" if report["clean"] else f"{report['violation_count']} violation(s)"
        print(f"[verify_isolation] baseline 已写入 {BASELINE_OUT.name} "
              f"({report['scanned_files']} 文件, {status})")
        return 0

    # 常规模式: 写 audit 报告
    atomic_write_json(AUDIT_OUT, report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))

    if report["clean"]:
        if not args.quiet:
            print(f"[verify_isolation] CLEAN — 扫描 {report['scanned_files']} 文件, "
                  f"0 泄露 ({len(report['restricted_ok'])} 个 restricted 文件已豁免)。")
            print(f"[verify_isolation] schema 源: {report['schema_source']}; "
                  f"报告: {AUDIT_OUT.name}")
        else:
            print(f"isolation OK ({report['scanned_files']} files, 0 leaks)")
        return 0

    # 有 violation → 阻断
    if args.quiet:
        print(f"isolation FAIL: {report['violation_count']} leak(s) — see {AUDIT_OUT.name}")
    else:
        print(f"[verify_isolation] ⛔ FAIL — 检出 {report['violation_count']} 处持仓泄露:")
        for v in report["violations"][:25]:
            print(f"  - {v['file']}:{v['line']}  [{v['kind']}] {v['field']}")
            print(f"      → {v['suggestion']}")
        if report["violation_count"] > 25:
            print(f"  ... 另有 {report['violation_count'] - 25} 处, 详见 {AUDIT_OUT.name}")
        print(f"[verify_isolation] gate 触发: daily_run.sh 应在此阻断 sync_nexus(防泄露推公网)。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
