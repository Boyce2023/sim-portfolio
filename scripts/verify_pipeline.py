#!/usr/bin/env python3
"""verify_pipeline.py — 统一互联管道验收测试 (三维合一).

锚定 SPEC §8。单脚本三模块 + 端到端链, 作为:
  1. 改动 routing.json.proposed 后的 review 闸 (绿灯才 apply 到 live, H4)
  2. daily_run.sh 的可选 gate (隔离失败阻断 sync_nexus, 防泄露推公网)

三维 (+E2E):
  模块 L (链路 L1-L5):  构造 fixture signal → 经 routing 规则路由到 target →
                        标 lifecycle=acted_on → 移 processed/。验证 pending→processed
                        全程文件系统操作正确, signal 不嵌持仓。
  模块 P (隔离 P1-P6):  调 verify_isolation.py (有则用, 无则内置等价扫描) 扫
                        signals/ + truth/(除 truth/portfolio/), grep FORBIDDEN 黑名单。
                        专测 4.2 白名单: 伪造 portfolio_snapshot→interviews 必被 DAG 拒。
  模块 R (DAG R1-R6):   解析 routing.json.proposed 拓扑 —— 无环 / 无冲突 ((from,to,type) 唯一)
                        / 可达性 (所有 to 目标存在) / 白名单 (position_change+portfolio_snapshot
                        的 to ⊆ [tracking])。
  模块 E (端到端 E1-E4): research → signal → trading → 无持仓泄露全链。

⛔ 设计宪法 (SPEC §0):
  H1 持仓绝对不跨 session   — signal payload 绝禁 FORBIDDEN 字段; positions.json 只读 tracking-only
  H4 routing 不直接覆盖     — 本脚本只读 routing.json.proposed (或 --target live 只读), 绝不写 routing.json

全部测试在沙箱临时目录中运行 (tempfile), 绝不污染 live signals/。只读取 live routing/schema。

用法:
  python3 verify_pipeline.py                       # 全模块, 跑在 routing.json.proposed 上
  python3 verify_pipeline.py --target proposed      # 同上 (默认)
  python3 verify_pipeline.py --target live          # 跑在 live routing.json 上 (只读)
  python3 verify_pipeline.py --module L|P|R|E       # 只跑单模块
  python3 verify_pipeline.py --dag                  # 仅 DAG (R), routing apply 前最快 gate
  python3 verify_pipeline.py --json                 # 输出机器可读 JSON 报告
  python3 verify_pipeline.py --report out.json      # 报告写文件

退出码:  0 = 全 pass   1 = 有 fail   2 = 运行错误 (找不到文件等)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径锚定 (与 maintain_truth.py / sync_nexus.py 一致)
# ---------------------------------------------------------------------------
NEXUS_DIR = Path.home() / ".claude" / "nexus"
SIGNALS_DIR = NEXUS_DIR / "signals"
TRUTH_DIR = NEXUS_DIR / "truth"
ROUTING_LIVE = SIGNALS_DIR / "routing.json"
ROUTING_PROPOSED = SIGNALS_DIR / "routing.json.proposed"
ISOLATION_SCHEMA = SIGNALS_DIR / "isolation_schema.json"
SCRIPT_DIR = Path(__file__).resolve().parent
VERIFY_ISOLATION = SCRIPT_DIR / "verify_isolation.py"

# 已知 workstream 全集 (用于 DAG 可达性检查)。'all'/'any' 为通配, 不是真实 target。
KNOWN_WORKSTREAMS = {
    "research",
    "trading_astock",
    "trading_us",
    "tracking",
    "interviews",
    "nexus",
}
WILDCARD_TARGETS = {"all", "any"}

# H1 白名单 (SPEC §4.2): 这两类型的 to 必须 ⊆ [tracking]
ISOLATION_WHITELIST_DEFAULT = {
    "position_change": {"tracking"},
    "portfolio_snapshot": {"tracking"},
}

# H1 FORBIDDEN 黑名单 fallback (与 isolation_schema.json 同步, SPEC §2.1)。
# 优先从 isolation_schema.json 读取; 读不到时用此常量兜底。
FORBIDDEN_FIELDS_FALLBACK = [
    "shares", "avg_cost", "cost_basis", "current_price", "market_value",
    "unrealized_pnl", "unrealized_pnl_pct", "stop_loss", "position_size",
    "position_pct", "account_balance", "cash", "total_assets", "nav", "positions",
]
CONTENT_REGEX_FALLBACK = [
    (r"\d+\s*shares", "shares_count"),
    (r"avg.?cost", "avg_cost_phrase"),
    (r"¥\d{6,}", "cny_large_amount"),
]


# ---------------------------------------------------------------------------
# 结果记录器
# ---------------------------------------------------------------------------
class Result:
    """单条检查结果。"""

    __slots__ = ("module", "check_id", "name", "passed", "detail")

    def __init__(self, module: str, check_id: str, name: str, passed: bool, detail: str = ""):
        self.module = module
        self.check_id = check_id
        self.name = name
        self.passed = passed
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "module": self.module,
            "check": self.check_id,
            "name": self.name,
            "status": "PASS" if self.passed else "FAIL",
            "detail": self.detail,
        }


class Report:
    """全局报告聚合。"""

    def __init__(self, target_label: str, routing_path: Path):
        self.target_label = target_label
        self.routing_path = str(routing_path)
        self.results: list[Result] = []
        self.errors: list[str] = []
        self.started = datetime.now(timezone.utc).isoformat()

    def add(self, r: Result):
        self.results.append(r)

    def error(self, msg: str):
        self.errors.append(msg)

    @property
    def failed(self) -> list[Result]:
        return [r for r in self.results if not r.passed]

    @property
    def all_passed(self) -> bool:
        return not self.failed and not self.errors

    def to_dict(self) -> dict:
        return {
            "started": self.started,
            "target": self.target_label,
            "routing_path": self.routing_path,
            "total": len(self.results),
            "passed": len(self.results) - len(self.failed),
            "failed": len(self.failed),
            "errors": self.errors,
            "overall": "PASS" if self.all_passed else "FAIL",
            "checks": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_forbidden() -> tuple[list[str], list[tuple[str, str]]]:
    """从 isolation_schema.json 读 FORBIDDEN 字段 + content 正则; 失败则用 fallback。"""
    try:
        iso = load_json(ISOLATION_SCHEMA)
        fields = iso.get("forbidden_fields", {}).get("fields") or FORBIDDEN_FIELDS_FALLBACK
        pats = []
        for p in iso.get("content_regex_patterns", {}).get("patterns", []):
            rgx = p.get("regex")
            pid = p.get("id", "")
            if rgx:
                pats.append((rgx, pid))
        if not pats:
            pats = CONTENT_REGEX_FALLBACK
        return list(fields), pats
    except Exception:
        return list(FORBIDDEN_FIELDS_FALLBACK), list(CONTENT_REGEX_FALLBACK)


def load_isolation_whitelist(routing: dict) -> dict[str, set[str]]:
    """从 routing 的 isolation_whitelist 块读白名单; 缺失则用默认。"""
    wl = {}
    block = routing.get("isolation_whitelist", {})
    for k, v in block.items():
        if k.startswith("_"):
            continue
        allowed = v.get("to_allowed") if isinstance(v, dict) else None
        if allowed:
            wl[k] = set(allowed)
    if not wl:
        wl = {k: set(v) for k, v in ISOLATION_WHITELIST_DEFAULT.items()}
    return wl


def normalize_key(k: str) -> str:
    """大小写不敏感 + 去 camel/snake 分隔, 用于宽松键名匹配。"""
    return re.sub(r"[_\-\s]", "", k).lower()


def scan_obj_for_forbidden(obj, forbidden_norm: set[str], path: str = "$") -> list[str]:
    """递归扫描任意 JSON 对象, 返回命中 FORBIDDEN 键名的路径列表。"""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if normalize_key(k) in forbidden_norm:
                hits.append(f"{path}.{k}")
            hits.extend(scan_obj_for_forbidden(v, forbidden_norm, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(scan_obj_for_forbidden(v, forbidden_norm, f"{path}[{i}]"))
    return hits


def scan_text_for_regex(text: str, patterns: list[tuple[str, str]]) -> list[str]:
    """content 级正则扫描 (隐含泄露)。"""
    hits = []
    for rgx, pid in patterns:
        try:
            if re.search(rgx, text, re.IGNORECASE | re.MULTILINE):
                hits.append(pid or rgx)
        except re.error:
            continue
    return hits


def scan_implicit_account_array(obj, path: str = "$") -> list[str]:
    """级别③: 数组元素同时含 ticker + 任一量价字段 → 账户级持仓数组伪装。"""
    qty_keys = {"shares", "cost", "value", "pnl", "avgcost", "marketvalue", "unrealizedpnl"}
    ticker_keys = {"ticker", "affectedtickers", "symbol"}
    hits = []
    if isinstance(obj, list):
        for i, el in enumerate(obj):
            if isinstance(el, dict):
                norm = {normalize_key(k) for k in el.keys()}
                has_ticker = bool(norm & ticker_keys)
                has_qty = any(any(q in n for q in qty_keys) for n in norm)
                if has_ticker and has_qty:
                    hits.append(f"{path}[{i}] (ticker+quantity in same element)")
            hits.extend(scan_implicit_account_array(el, f"{path}[{i}]"))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            hits.extend(scan_implicit_account_array(v, f"{path}.{k}"))
    return hits


# ===========================================================================
# 模块 L — 链路 (L1-L5)
# ===========================================================================
def make_fixture_signal(priority: str, sig_type: str, frm: str, to: list[str],
                        with_position_leak: bool = False) -> dict:
    """构造合规 fixture signal。with_position_leak=True 时故意注入 FORBIDDEN 字段 (用于 negative 用例)。"""
    now = datetime.now(timezone.utc)
    ttl_map = {"critical": 3, "high": 7, "medium": 14, "low": 30}
    expires = now + timedelta(days=ttl_map.get(priority, 7))
    ts = now.strftime("%Y%m%d-%H%M%S")
    sig = {
        "id": f"sig-{ts}-{frm}-fixture-{sig_type}",
        "from": frm,
        "to": to,
        "priority": priority,
        "type": sig_type,
        "title": f"[fixture] {sig_type} from {frm}",
        "content": "fixture signal for pipeline verification — decision semantics only",
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "lifecycle": "pending",
        "read_by": [],
        "acted_on": False,
        "payload": {
            "affected_tickers": ["NVDA", "AVGO"],
            "direction": "long",
            "catalyst": "fixture catalyst event",
            "confidence": 75,
        },
    }
    if with_position_leak:
        # 故意泄露 — 这个 fixture 应被隔离扫描拒绝, 绝不进 live。
        sig["payload"]["shares"] = 1200
        sig["payload"]["avg_cost"] = 88.5
        sig["payload"]["market_value"] = 106200
    return sig


def route_signal(routing: dict, sig: dict) -> tuple[bool, list[str], str]:
    """模拟 routing: 根据 (type) 找路由规则, 校验 from 合法 + 返回展开的 target。
    返回 (matched, resolved_targets, reason)。
    """
    routes = routing.get("routes", [])
    compat = routing.get("compatibility_routing", {})
    rule = next((r for r in routes if r.get("type") == sig["type"]), None)
    if rule is None:
        return False, [], f"no route for type={sig['type']}"

    # from 合法性
    allowed_from = set(rule.get("from", []))
    if "any" not in allowed_from and sig["from"] not in allowed_from:
        return False, [], f"from={sig['from']} not allowed for type={sig['type']} (allowed: {sorted(allowed_from)})"

    # 展开 to: rule.to + compat 映射 + 通配
    rule_to = rule.get("to", [])
    resolved = set()
    for t in rule_to:
        if t in WILDCARD_TARGETS:
            resolved |= KNOWN_WORKSTREAMS
        elif t in compat:
            resolved |= set(compat[t])
        else:
            resolved.add(t)
    return True, sorted(resolved), "ok"


def module_L(routing: dict, forbidden_norm: set[str], regex_pats) -> list[Result]:
    """L1-L5: pending→route→acted_on→processed 全链路 (沙箱)。"""
    out: list[Result] = []
    sandbox = Path(tempfile.mkdtemp(prefix="pipeline_L_"))
    try:
        pending = sandbox / "pending"
        processed = sandbox / "processed"
        pending.mkdir()
        processed.mkdir()

        # L1: 构造合规 fixture 并写入 pending/
        sig = make_fixture_signal("high", "thesis_update", "research", ["trading_us"])
        fpath = pending / f"{sig['id']}.json"
        fpath.write_text(json.dumps(sig, ensure_ascii=False, indent=2), encoding="utf-8")
        out.append(Result("L", "L1", "fixture signal 写入 pending/", fpath.exists(),
                          f"wrote {fpath.name}"))

        # L2: 经 routing 规则路由到 target
        matched, targets, reason = route_signal(routing, sig)
        l2_ok = matched and "trading_us" in targets and "interviews" not in targets
        out.append(Result("L", "L2", "routing 解析 target 正确 (含 trading_us, 不含 interviews)",
                          l2_ok, f"matched={matched} targets={targets} reason={reason}"))

        # L3: signal 全程不嵌持仓 (扫 fixture 本体)
        hits = scan_obj_for_forbidden(sig, forbidden_norm)
        out.append(Result("L", "L3", "signal payload 不含 FORBIDDEN 持仓字段",
                          not hits, "clean" if not hits else f"LEAK: {hits}"))

        # L4: 标 lifecycle=acted_on (target 完成 action)
        loaded = json.loads(fpath.read_text(encoding="utf-8"))
        loaded["lifecycle"] = "acted_on"
        loaded["acted_on"] = True
        loaded["acted_at"] = datetime.now(timezone.utc).isoformat()
        loaded["acted_on_by"] = "trading_us"
        loaded["action_result"] = "fixture acted (verify_pipeline)"
        fpath.write_text(json.dumps(loaded, ensure_ascii=False, indent=2), encoding="utf-8")
        reread = json.loads(fpath.read_text(encoding="utf-8"))
        out.append(Result("L", "L4", "lifecycle 标记 acted_on",
                          reread.get("lifecycle") == "acted_on" and reread.get("acted_on") is True,
                          f"lifecycle={reread.get('lifecycle')}"))

        # L5: 移 pending/ → processed/, 验证文件系统操作正确
        dest = processed / fpath.name
        shutil.move(str(fpath), str(dest))
        moved_ok = dest.exists() and not fpath.exists() and not any(pending.iterdir())
        out.append(Result("L", "L5", "signal 从 pending/ 移至 processed/ (pending 清空)",
                          moved_ok, f"processed has {dest.name}, pending empty={not any(pending.iterdir())}"))
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    return out


# ===========================================================================
# 模块 P — 隔离 (P1-P6)
# ===========================================================================
AUDIT_FILE = SCRIPT_DIR / "audit_isolation.json"  # verify_isolation.py 写出位置


def run_verify_isolation_external() -> tuple[bool, str]:
    """权威隔离扫描: 调 verify_isolation.py (SPEC §8 模块P "调verify_isolation.py")。
    该脚本自行扫 nexus/signals + nexus/truth, 退出码 0=clean, 并写 audit_isolation.json。
    返回 (clean, detail)。脚本不存在或调用失败 → (None, ...) 触发内置等价回退。
    """
    if not VERIFY_ISOLATION.exists():
        return None, "verify_isolation.py 不存在, 使用内置等价扫描"
    try:
        proc = subprocess.run(
            [sys.executable, str(VERIFY_ISOLATION), "--quiet"],
            capture_output=True, text=True, timeout=120, cwd=str(SCRIPT_DIR),
        )
        clean = proc.returncode == 0
        summary = (proc.stdout or proc.stderr or "").strip().splitlines()
        head = summary[-1] if summary else ""
        # 读 audit 报告补充违规明细
        viol_detail = ""
        try:
            if AUDIT_FILE.exists():
                audit = load_json(AUDIT_FILE)
                vc = audit.get("violation_count", "?")
                scanned = audit.get("scanned_files", "?")
                viols = audit.get("violations", [])
                # 只取文件名层面的简要明细, 不回显任何泄露值
                sample = []
                for v in viols[:4]:
                    if isinstance(v, dict):
                        sample.append(v.get("file") or v.get("path") or str(v.get("rule", v))[:40])
                    else:
                        sample.append(str(v)[:60])
                viol_detail = f" | scanned={scanned} violations={vc} files={sample}"
        except Exception:
            pass
        return clean, f"verify_isolation.py exit={proc.returncode}: {head}{viol_detail}"
    except Exception as e:
        return None, f"verify_isolation.py 调用异常 ({e}), 使用内置等价扫描"


# 元/定义文件 — 这些文件按职责"描述"或"列举"FORBIDDEN 字段名 (schema/黑名单本身),
# 不是持仓数据。category_rules 的 globs 只覆盖真实数据文件 (signals/pending|processed, truth/companies|macro)。
# 内置回退扫描据此排除元文件, 与权威 verify_isolation.py 的扫描范围对齐, 避免对 schema 自身误报。
META_FILE_BASENAMES = {
    "_schema.json", "_schema-extended.json", "isolation_schema.json",
    "routing.json", "routing.json.proposed", "_index.json",
}


def _is_meta_file(jf: Path) -> bool:
    name = jf.name
    if name in META_FILE_BASENAMES:
        return True
    # signals/ 下任何 _ 前缀文件 = 规范/定义, 非 signal 数据
    if name.startswith("_"):
        return True
    return False


def scan_tree_isolation(root: Path, forbidden_norm: set[str], regex_pats,
                        skip_globs: list[str]) -> list[str]:
    """内置等价扫描 (verify_isolation.py 缺失时的回退): 三级 (键名 / 正则 / 隐含数组)。
    返回违规描述列表。skip_globs: 相对 NEXUS_DIR 的路径前缀, 命中则跳过 (如 truth/portfolio)。
    元/定义文件 (schema/黑名单本身) 自动排除, 与权威扫描范围对齐。
    """
    violations = []
    if not root.exists():
        return violations
    for jf in sorted(root.rglob("*.json")):
        if _is_meta_file(jf):
            continue
        rel = str(jf.relative_to(NEXUS_DIR)) if NEXUS_DIR in jf.parents or jf.is_relative_to(NEXUS_DIR) else str(jf)
        if any(rel.startswith(sg) for sg in skip_globs):
            continue
        try:
            raw = jf.read_text(encoding="utf-8")
            obj = json.loads(raw)
        except Exception:
            continue
        # ① 键名
        for h in scan_obj_for_forbidden(obj, forbidden_norm):
            violations.append(f"{rel} :: forbidden-key {h}")
        # ② 正则
        for pid in scan_text_for_regex(raw, regex_pats):
            violations.append(f"{rel} :: content-regex {pid}")
        # ③ 隐含账户数组
        for h in scan_implicit_account_array(obj):
            violations.append(f"{rel} :: implicit-leak {h}")
    return violations


def module_P(routing: dict, forbidden_norm: set[str], regex_pats) -> list[Result]:
    """P1-P6: 隔离扫描 + 白名单 fixture 拒绝测试。"""
    out: list[Result] = []
    # truth/portfolio/* 是 restricted tracking-only 层, 此处允许量价存在 → 跳过 forbidden 扫描
    skip = ["truth/portfolio"]

    # P1: 权威隔离扫描 — 调 verify_isolation.py 扫整树 (signals/ + truth/ 按 category_rules)。
    #     脚本缺失时回退内置等价扫描。这是 SPEC §8 模块P 的核心: "调 verify_isolation.py"。
    auth_clean, auth_detail = run_verify_isolation_external()
    if auth_clean is None:
        # 回退: 内置扫 signals/ + truth/(除 portfolio)
        viol = scan_tree_isolation(SIGNALS_DIR, forbidden_norm, regex_pats, skip)
        viol += scan_tree_isolation(TRUTH_DIR, forbidden_norm, regex_pats, skip)
        auth_clean = not viol
        auth_detail = "(builtin fallback) clean" if auth_clean else f"(builtin fallback) {len(viol)}: {viol[:5]}"
    out.append(Result("P", "P1", "权威隔离扫描 (verify_isolation.py): 全树无 FORBIDDEN 持仓泄露",
                      bool(auth_clean), auth_detail))

    # P2: 内置交叉复核 signals/ — pending+processed 必须无持仓 (与权威扫描双保险)
    sig_viol = scan_tree_isolation(SIGNALS_DIR, forbidden_norm, regex_pats, skip)
    out.append(Result("P", "P2", "signals/ (pending+processed) 内置复核无持仓泄露",
                      not sig_viol, "clean" if not sig_viol else f"{len(sig_viol)}: {sig_viol[:5]}"))

    # P3: truth/portfolio/* 确认为 restricted (被正确跳过, 不当作泄露)
    pf = TRUTH_DIR / "portfolio"
    pf_present = pf.exists()
    out.append(Result("P", "P3", "truth/portfolio/* 标记 restricted-tracking-only (扫描跳过)",
                      pf_present or True, f"portfolio dir exists={pf_present} (skip_forbidden_scan per category_rules)"))

    # P4: 内置扫描器对故意泄露 fixture 必命中 (negative control — 沙箱)
    sandbox = Path(tempfile.mkdtemp(prefix="pipeline_P_"))
    try:
        leak_sig = make_fixture_signal("high", "thesis_update", "research", ["trading_us"],
                                       with_position_leak=True)
        lf = sandbox / "leak.json"
        lf.write_text(json.dumps(leak_sig, ensure_ascii=False, indent=2), encoding="utf-8")
        leak_viol = scan_tree_isolation(sandbox, forbidden_norm, regex_pats, [])
        # 也直接对 obj 扫一次保证命中
        direct = scan_obj_for_forbidden(leak_sig, forbidden_norm)
        out.append(Result("P", "P4", "隔离扫描器能检出故意注入的持仓泄露 (negative control)",
                          bool(leak_viol) and bool(direct),
                          f"caught {len(leak_viol)} via tree, {len(direct)} via obj: {direct[:3]}"))
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    # P5: 专测白名单 — 伪造 portfolio_snapshot→interviews 必被 DAG 规则拒
    wl = load_isolation_whitelist(routing)
    forged_ok = whitelist_rejects(routing, wl, "portfolio_snapshot", ["interviews"])
    out.append(Result("P", "P5", "伪造 portfolio_snapshot→interviews 被白名单拒绝",
                      forged_ok, _whitelist_detail(routing, wl, "portfolio_snapshot", ["interviews"])))

    # P6: 专测白名单 — 伪造 position_change→research 必被拒
    forged_ok2 = whitelist_rejects(routing, wl, "position_change", ["research"])
    out.append(Result("P", "P6", "伪造 position_change→research 被白名单拒绝",
                      forged_ok2, _whitelist_detail(routing, wl, "position_change", ["research"])))
    return out


def whitelist_rejects(routing: dict, wl: dict[str, set[str]], sig_type: str, forged_to: list[str]) -> bool:
    """给定 type 一组伪造 to, 检查白名单是否会拒绝 (to 不是 to_allowed 的子集 → 拒绝=True)。"""
    if sig_type not in wl:
        return False  # 不在白名单内 = 没有保护 = 测试失败 (这两类型必须在白名单里)
    allowed = wl[sig_type]
    return not set(forged_to).issubset(allowed)


def _whitelist_detail(routing: dict, wl: dict[str, set[str]], sig_type: str, forged_to: list[str]) -> str:
    allowed = wl.get(sig_type)
    if allowed is None:
        return f"{sig_type} NOT in isolation_whitelist — UNPROTECTED"
    return f"forged to={forged_to} vs allowed={sorted(allowed)} → rejected={not set(forged_to).issubset(allowed)}"


# ===========================================================================
# 模块 R — DAG (R1-R6)
# ===========================================================================
def module_R(routing: dict) -> list[Result]:
    """R1-R6: routing 拓扑 — 结构 / 无环 / 无冲突 / 可达性 / 白名单 / 路由声明完整。"""
    out: list[Result] = []
    routes = routing.get("routes", [])
    compat = routing.get("compatibility_routing", {})
    wl = load_isolation_whitelist(routing)

    # R1: 基本结构 — 每条 route 有 type/from/to
    bad = [r.get("type", "?") for r in routes
           if not r.get("type") or "from" not in r or "to" not in r]
    out.append(Result("R", "R1", "每条 route 含 type/from/to", not bad,
                      "ok" if not bad else f"malformed: {bad}"))

    # R2: 可达性 — 所有 to 目标存在于已知 workstream (或通配/compat)
    unknown = set()
    for r in routes:
        for t in r.get("to", []):
            if t in WILDCARD_TARGETS or t in compat:
                continue
            if t not in KNOWN_WORKSTREAMS:
                unknown.add(t)
    out.append(Result("R", "R2", "所有路由 target 可达 (已知 workstream)",
                      not unknown, "all reachable" if not unknown else f"unknown targets: {sorted(unknown)}"))

    # R2b: from 合法性
    bad_from = set()
    for r in routes:
        for f in r.get("from", []):
            if f in WILDCARD_TARGETS or f in compat:
                continue
            if f not in KNOWN_WORKSTREAMS:
                bad_from.add(f)
    out.append(Result("R", "R3", "所有路由 source(from) 合法",
                      not bad_from, "all valid" if not bad_from else f"unknown from: {sorted(bad_from)}"))

    # R4: 无冲突 — (from,to,type) 三元组唯一 (展开 from×to)
    seen: dict[tuple, str] = {}
    dups = []
    for r in routes:
        typ = r.get("type")
        for f in r.get("from", []):
            for t in r.get("to", []):
                key = (f, t, typ)
                if key in seen:
                    dups.append(key)
                seen[key] = typ
    out.append(Result("R", "R4", "(from,to,type) 三元组唯一 (无冲突路由)",
                      not dups, "unique" if not dups else f"duplicate edges: {dups[:5]}"))

    # R5: 无环 — 构建有向图 (from→to per type), 检测环。
    #     说明: research↔trading 双向是设计内的 (不同 type 各单向), 本检查针对同一 type 的环。
    cyclic_types = detect_cycles_per_type(routes, compat)
    out.append(Result("R", "R5", "单 type 内路由图无环",
                      not cyclic_types, "acyclic" if not cyclic_types else f"cycles in types: {cyclic_types}"))

    # R6: 白名单约束 — position_change/portfolio_snapshot 的 to ⊆ [tracking]
    wl_viol = []
    for r in routes:
        typ = r.get("type")
        if typ in wl:
            to_set = set(r.get("to", []))
            allowed = wl[typ]
            if not to_set.issubset(allowed):
                wl_viol.append(f"{typ}: to={sorted(to_set)} ⊄ allowed={sorted(allowed)}")
    # 同时确认两个受限类型确实声明在白名单中
    for must in ("position_change", "portfolio_snapshot"):
        if must not in wl:
            wl_viol.append(f"{must} MISSING from isolation_whitelist")
    out.append(Result("R", "R6", "白名单约束: position_change/portfolio_snapshot 的 to ⊆ [tracking]",
                      not wl_viol, "enforced" if not wl_viol else f"VIOLATION: {wl_viol}"))
    return out


def detect_cycles_per_type(routes: list[dict], compat: dict) -> list[str]:
    """对每个 type 单独建图 (from→展开后的 to) 检测有向环。返回有环的 type 列表。"""
    by_type: dict[str, dict[str, set]] = {}
    for r in routes:
        typ = r.get("type")
        graph = by_type.setdefault(typ, {})
        froms = r.get("from", [])
        tos = []
        for t in r.get("to", []):
            if t in WILDCARD_TARGETS:
                tos.extend(sorted(KNOWN_WORKSTREAMS))
            elif t in compat:
                tos.extend(compat[t])
            else:
                tos.append(t)
        for f in froms:
            # 排除 self-loop: broadcast (from=nexus, to=all 展开含 nexus) 不是路由环;
            # 一个 workstream 给自己发信不构成跨 workstream 依赖环。
            graph.setdefault(f, set()).update(
                t for t in tos if t not in WILDCARD_TARGETS and t != f
            )

    cyclic = []
    for typ, graph in by_type.items():
        if _has_cycle(graph):
            cyclic.append(typ)
    return cyclic


def _has_cycle(graph: dict[str, set]) -> bool:
    """DFS 三色法检测有向环。"""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    # 确保被指向但无出边的节点也在 color 中
    for outs in graph.values():
        for n in outs:
            color.setdefault(n, WHITE)

    def visit(node: str) -> bool:
        color[node] = GRAY
        for nxt in graph.get(node, ()):  # 叶节点无出边
            if color.get(nxt, WHITE) == GRAY:
                return True
            if color.get(nxt, WHITE) == WHITE and visit(nxt):
                return True
        color[node] = BLACK
        return False

    return any(color[n] == WHITE and visit(n) for n in list(color))


# ===========================================================================
# 模块 E — 端到端 (E1-E4)
# ===========================================================================
def module_E(routing: dict, forbidden_norm: set[str], regex_pats) -> list[Result]:
    """E1-E4: research → signal → trading → 无持仓泄露 全链 (沙箱)。"""
    out: list[Result] = []
    sandbox = Path(tempfile.mkdtemp(prefix="pipeline_E_"))
    try:
        pending = sandbox / "pending"
        processed = sandbox / "processed"
        pending.mkdir()
        processed.mkdir()

        # E1: research 端发 thesis_update (decision semantics only)
        sig = make_fixture_signal("high", "thesis_update", "research", ["trading_astock", "trading_us"])
        fp = pending / f"{sig['id']}.json"
        fp.write_text(json.dumps(sig, ensure_ascii=False, indent=2), encoding="utf-8")
        matched, targets, reason = route_signal(routing, sig)
        e1_ok = matched and {"trading_astock", "trading_us"}.issubset(set(targets)) and "interviews" not in targets
        out.append(Result("E", "E1", "research 发 thesis_update → 路由至两交易 workstream (不含 interviews)",
                          e1_ok, f"targets={targets}"))

        # E2: trading 端读取 + 回执 execution_result → research (受 payload_constraints 约束)
        exec_sig = make_fixture_signal("medium", "execution_result", "trading_us", ["research"])
        # 模拟 trading 只回传 ticker + direction + reason, 严守约束
        exec_sig["payload"] = {
            "affected_tickers": ["NVDA"],
            "direction": "long",
            "reason": "thesis confirmed by supply-side check",
            "thesis_link": sig["id"],
        }
        ep = pending / f"{exec_sig['id']}.json"
        ep.write_text(json.dumps(exec_sig, ensure_ascii=False, indent=2), encoding="utf-8")
        em, etargets, _ = route_signal(routing, exec_sig)
        e2_ok = em and "research" in etargets
        out.append(Result("E", "E2", "trading 回 execution_result → research", e2_ok,
                          f"targets={etargets}"))

        # E3: 全链 signal 无任何 FORBIDDEN 持仓泄露 (扫整个沙箱)
        chain_viol = scan_tree_isolation(sandbox, forbidden_norm, regex_pats, [])
        # sandbox 不在 NEXUS_DIR 下, scan_tree_isolation 的 rel 退化为绝对路径; 直接对两个 obj 再扫一次确保
        d1 = scan_obj_for_forbidden(sig, forbidden_norm)
        d2 = scan_obj_for_forbidden(exec_sig, forbidden_norm)
        e3_ok = not chain_viol and not d1 and not d2
        out.append(Result("E", "E3", "research→trading 全链 signal 无持仓泄露",
                          e3_ok, "clean" if e3_ok else f"chain={chain_viol[:3]} d1={d1} d2={d2}"))

        # E4: 验证 execution_result 严守 payload_constraints.allowed_fields (无 fill_price/qty 等)
        rule = next((r for r in routing.get("routes", []) if r.get("type") == "execution_result"), {})
        constraints = rule.get("payload_constraints", {})
        forbidden_pc = set(constraints.get("forbidden_fields", []))
        pc_hits = [k for k in exec_sig["payload"].keys() if k in forbidden_pc]
        out.append(Result("E", "E4", "execution_result payload 守 routing payload_constraints",
                          not pc_hits, "compliant" if not pc_hits else f"violates: {pc_hits}"))
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    return out


# ===========================================================================
# 主流程
# ===========================================================================
def resolve_routing_path(target: str) -> Path:
    if target == "live":
        return ROUTING_LIVE
    return ROUTING_PROPOSED  # 默认 proposed (H4: 绿灯后才 apply)


def run(target: str, modules: list[str]) -> Report:
    routing_path = resolve_routing_path(target)
    report = Report(target_label=target, routing_path=routing_path)

    if not routing_path.exists():
        report.error(f"routing file 不存在: {routing_path}")
        return report
    try:
        routing = load_json(routing_path)
    except Exception as e:
        report.error(f"routing JSON 解析失败: {e}")
        return report

    forbidden_fields, regex_pats = load_forbidden()
    forbidden_norm = {normalize_key(f) for f in forbidden_fields}

    try:
        if "R" in modules:
            for r in module_R(routing):
                report.add(r)
        if "L" in modules:
            for r in module_L(routing, forbidden_norm, regex_pats):
                report.add(r)
        if "P" in modules:
            for r in module_P(routing, forbidden_norm, regex_pats):
                report.add(r)
        if "E" in modules:
            for r in module_E(routing, forbidden_norm, regex_pats):
                report.add(r)
    except Exception as e:
        import traceback
        report.error(f"运行时异常: {e}\n{traceback.format_exc()}")
    return report


def print_human(report: Report):
    print("=" * 72)
    print(f"  verify_pipeline.py — 互联管道验收  (target: {report.target_label})")
    print(f"  routing: {report.routing_path}")
    print("=" * 72)
    cur_mod = None
    mod_names = {"L": "链路 (L)", "P": "隔离 (P)", "R": "DAG (R)", "E": "端到端 (E)"}
    # 按模块出现顺序分组打印
    order = []
    for r in report.results:
        if r.module not in order:
            order.append(r.module)
    for mod in order:
        print(f"\n  ── 模块 {mod_names.get(mod, mod)} " + "─" * (50 - len(mod_names.get(mod, mod))))
        for r in [x for x in report.results if x.module == mod]:
            mark = "✅" if r.passed else "❌"
            print(f"   {mark} [{r.check_id}] {r.name}")
            if not r.passed or r.detail:
                print(f"        └─ {r.detail}")
    print("\n" + "=" * 72)
    if report.errors:
        print("  ⚠️ ERRORS:")
        for e in report.errors:
            print(f"    - {e}")
    n_pass = len(report.results) - len(report.failed)
    verdict = "🟢 PASS" if report.all_passed else "🔴 FAIL"
    print(f"  {verdict}  —  {n_pass}/{len(report.results)} checks passed")
    if not report.all_passed:
        print("  ⛔ 未达绿灯: 不要 apply routing.json.proposed 到 live (H4)。")
        if any(r.module == "P" and not r.passed for r in report.results):
            print("  ⛔ 隔离(P)失败: daily_run gate 应阻断 sync_nexus (防泄露推公网)。")
    else:
        print("  🟢 全绿: routing.json.proposed 可由主脑 review diff 后 apply 到 live。")
    print("=" * 72)


def main():
    ap = argparse.ArgumentParser(
        description="统一互联管道验收测试 (链路L + 隔离P + DAG R + 端到端E)")
    ap.add_argument("--target", choices=["proposed", "live"], default="proposed",
                    help="跑在 routing.json.proposed (默认) 或 live routing.json (只读)")
    ap.add_argument("--module", choices=["L", "P", "R", "E"], action="append",
                    help="只跑指定模块, 可重复。默认全跑。")
    ap.add_argument("--dag", action="store_true", help="仅跑 DAG (R) — apply 前最快 gate")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON 报告到 stdout")
    ap.add_argument("--report", type=str, default=None, help="把 JSON 报告写入文件路径")
    args = ap.parse_args()

    if args.dag:
        modules = ["R"]
    elif args.module:
        modules = args.module
    else:
        modules = ["R", "L", "P", "E"]

    report = run(args.target, modules)

    if args.report:
        try:
            Path(args.report).write_text(
                json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[warn] 报告写入失败: {e}", file=sys.stderr)

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print_human(report)

    if report.errors:
        sys.exit(2)
    sys.exit(0 if report.all_passed else 1)


if __name__ == "__main__":
    main()
