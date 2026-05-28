# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""changelog_sync.py — 跨session变更通知系统

每个session启动时自动检查，显示未确认的变更，确认后标记已读。
任何session完成系统变更后调用 --post 写入新条目通知其他session。

Usage:
  uv run --script scripts/changelog_sync.py --check --session trading_us
  uv run --script scripts/changelog_sync.py --ack chg-20260527-7phase --session trading_us
  uv run --script scripts/changelog_sync.py --post --from nexus_meta --target trading_astock,trading_us --title "..." --summary "..."
  uv run --script scripts/changelog_sync.py --history
"""

import json, sys, argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

REPO = Path(__file__).parent.parent
CHANGELOG = REPO / "system_changelog.json"
TZ_BJT = timezone(timedelta(hours=8))


def _load():
    if not CHANGELOG.exists():
        return {"_schema": "system_changelog v1.0", "entries": []}
    with open(CHANGELOG) as f:
        return json.load(f)


def _save(data):
    with open(CHANGELOG, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cmd_check(session_id: str):
    """Show unacknowledged entries for this session."""
    data = _load()
    pending = []
    for entry in data["entries"]:
        targets = entry.get("target", [])
        if "all" not in targets and session_id not in targets:
            continue
        ack = entry.get("ack", {})
        if session_id in ack:
            continue
        pending.append(entry)

    if not pending:
        print(f"[changelog] {session_id}: 无新变更通知 ✓")
        return

    print(f"═══ [系统变更通知] {len(pending)}条未确认 ═══")
    for e in pending:
        priority_icon = {"critical": "🔴", "high": "🟡", "medium": "🔵", "low": "⚪"}.get(
            e.get("priority", "medium"), "🔵"
        )
        print(f"\n{priority_icon} [{e['id']}] {e['title']}")
        print(f"  来自: {e['from']} | {e['timestamp']}")
        print(f"  摘要: {e['summary']}")
        if e.get("changes"):
            for c in e["changes"][:5]:
                print(f"    • {c}")
            if len(e.get("changes", [])) > 5:
                print(f"    ... 共{len(e['changes'])}项变更")
        if e.get("action_required"):
            print(f"  ⚡ 建议操作: {e['action_required']}")
    print(f"\n确认命令: uv run --script scripts/changelog_sync.py --ack <id> --session {session_id}")


def cmd_ack(entry_id: str, session_id: str):
    """Mark an entry as acknowledged by this session."""
    data = _load()
    found = False
    for entry in data["entries"]:
        if entry["id"] == entry_id:
            if "ack" not in entry:
                entry["ack"] = {}
            entry["ack"][session_id] = datetime.now(TZ_BJT).isoformat()
            found = True
            break

    if not found:
        print(f"[changelog] 未找到条目 {entry_id}", file=sys.stderr)
        sys.exit(1)

    _save(data)

    # Check if all targets have acked
    entry = next(e for e in data["entries"] if e["id"] == entry_id)
    targets = entry.get("target", [])
    all_acked = all(t in entry.get("ack", {}) for t in targets if t != "all")

    print(f"[changelog] {session_id} 已确认 {entry_id} ✓")
    if all_acked:
        print(f"[changelog] 所有目标session已确认此变更 ✓✓")


def cmd_ack_all(session_id: str):
    """Mark all pending entries as acknowledged."""
    data = _load()
    count = 0
    for entry in data["entries"]:
        targets = entry.get("target", [])
        if "all" not in targets and session_id not in targets:
            continue
        if session_id in entry.get("ack", {}):
            continue
        if "ack" not in entry:
            entry["ack"] = {}
        entry["ack"][session_id] = datetime.now(TZ_BJT).isoformat()
        count += 1

    if count > 0:
        _save(data)
    print(f"[changelog] {session_id} 已确认 {count} 条变更 ✓")


def _send_telegram(entry: dict):
    """Send changelog entry to Telegram for real-time cross-session delivery."""
    try:
        sys.path.insert(0, str(REPO / "telegram-bot"))
        from notifications import SystemChangeAlert, TelegramNotifier
        alert = SystemChangeAlert(
            entry_id=entry["id"],
            from_session=entry["from"],
            target_sessions=entry["target"],
            title=entry["title"],
            summary=entry["summary"],
            changes=entry.get("changes", []),
            priority=entry.get("priority", "medium"),
            action_required=entry.get("action_required", ""),
        )
        notifier = TelegramNotifier()
        ok = notifier.send(alert)
        if ok:
            print(f"[changelog] Telegram 通知已发送 ✓")
        else:
            print(f"[changelog] Telegram 发送失败（bot token可能未设置）")
    except Exception as e:
        print(f"[changelog] Telegram 发送跳过: {e}")


def cmd_post(from_id: str, targets: list[str], title: str, summary: str,
             changes: list[str] | None = None, priority: str = "medium",
             action_required: str | None = None, no_telegram: bool = False):
    """Write a new changelog entry + push Telegram notification."""
    data = _load()
    now = datetime.now(TZ_BJT)
    entry_id = f"chg-{now.strftime('%Y%m%d-%H%M%S')}"

    entry = {
        "id": entry_id,
        "timestamp": now.isoformat(),
        "from": from_id,
        "target": targets,
        "priority": priority,
        "title": title,
        "summary": summary,
    }
    if changes:
        entry["changes"] = changes
    if action_required:
        entry["action_required"] = action_required
    entry["ack"] = {}

    data["entries"].append(entry)
    _save(data)
    print(f"[changelog] 已发布 {entry_id} → {', '.join(targets)}")

    if not no_telegram:
        _send_telegram(entry)


def cmd_history():
    """Show all entries with ack status."""
    data = _load()
    if not data["entries"]:
        print("[changelog] 无历史记录")
        return

    for e in data["entries"]:
        targets = e.get("target", [])
        ack = e.get("ack", {})
        acked = [t for t in targets if t in ack]
        pending = [t for t in targets if t not in ack and t != "all"]
        status = "✓ 全部确认" if not pending else f"待确认: {', '.join(pending)}"
        print(f"[{e['id']}] {e['title']} | {status}")


def main():
    parser = argparse.ArgumentParser(description="跨session变更通知系统")
    parser.add_argument("--check", action="store_true", help="检查未确认变更")
    parser.add_argument("--ack", type=str, help="确认指定条目ID")
    parser.add_argument("--ack-all", action="store_true", help="确认所有待处理条目")
    parser.add_argument("--post", action="store_true", help="发布新变更通知")
    parser.add_argument("--history", action="store_true", help="查看所有历史记录")
    parser.add_argument("--session", type=str, help="当前session ID")
    parser.add_argument("--from-id", type=str, help="发布者session ID")
    parser.add_argument("--target", type=str, help="目标session (逗号分隔)")
    parser.add_argument("--title", type=str, help="变更标题")
    parser.add_argument("--summary", type=str, help="变更摘要")
    parser.add_argument("--changes", type=str, nargs="*", help="具体变更列表")
    parser.add_argument("--priority", type=str, default="medium",
                        choices=["critical", "high", "medium", "low"])
    parser.add_argument("--action-required", type=str, help="建议操作")
    parser.add_argument("--no-telegram", action="store_true", help="不发Telegram通知")

    args = parser.parse_args()

    if args.history:
        cmd_history()
    elif args.check:
        if not args.session:
            parser.error("--check 需要 --session")
        cmd_check(args.session)
    elif args.ack:
        if not args.session:
            parser.error("--ack 需要 --session")
        cmd_ack(args.ack, args.session)
    elif args.ack_all:
        if not args.session:
            parser.error("--ack-all 需要 --session")
        cmd_ack_all(args.session)
    elif args.post:
        if not all([args.from_id, args.target, args.title, args.summary]):
            parser.error("--post 需要 --from-id, --target, --title, --summary")
        targets = [t.strip() for t in args.target.split(",")]
        cmd_post(args.from_id, targets, args.title, args.summary,
                 args.changes, args.priority, args.action_required,
                 no_telegram=args.no_telegram)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
