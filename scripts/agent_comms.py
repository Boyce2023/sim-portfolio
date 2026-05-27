# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""agent_comms.py — 异步agent间通信系统

session之间通过JSON消息板异步对话。消息存储在agent_messages.json，
Telegram作为实时通知层（可选），pre_session_check启动时展示收件箱。

Usage:
  uv run --script scripts/agent_comms.py send \
    --from trading_astock --to trading_us \
    --subject "思源放量突破" --body "可能影响NVDA供应链，请关注"

  uv run --script scripts/agent_comms.py inbox --session trading_us
  uv run --script scripts/agent_comms.py inbox --session trading_us --unread-only

  uv run --script scripts/agent_comms.py reply \
    --session trading_us --msg-id msg-20260527-103000 \
    --body "收到。NVDA当前Pod I 18.5%，无需调整。"

  uv run --script scripts/agent_comms.py thread --msg-id msg-20260527-103000

  uv run --script scripts/agent_comms.py ack --session trading_us --msg-id msg-20260527-103000

  uv run --script scripts/agent_comms.py broadcast \
    --from nexus_meta --subject "系统升级" --body "所有session需重载config"
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

REPO = Path(__file__).parent.parent
MSG_FILE = REPO / "agent_messages.json"
TZ_BJT = timezone(timedelta(hours=8))

VALID_SESSIONS = {
    "trading_astock", "trading_us", "nexus_meta", "research", "tracking",
}


def _load() -> dict:
    if not MSG_FILE.exists():
        return {"_schema": "agent_messages v1.0 — 异步agent通信消息板", "messages": []}
    with open(MSG_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(MSG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _gen_id() -> str:
    now = datetime.now(TZ_BJT)
    return f"msg-{now.strftime('%Y%m%d-%H%M%S')}"


def _send_telegram(msg: dict) -> None:
    """Push message notification to Telegram (best-effort)."""
    try:
        sys.path.insert(0, str(REPO / "telegram-bot"))
        from notifications import TelegramNotifier
        notifier = TelegramNotifier()

        to_str = ", ".join(msg["to"]) if isinstance(msg["to"], list) else msg["to"]
        text = (
            f"💬 <b>Agent消息</b>\n"
            f"👤 {msg['from']} → {to_str}\n"
            f"📌 {msg['subject']}\n"
            f"📝 {msg['body'][:300]}"
        )
        if msg.get("reply_to"):
            text += f"\n↩️ 回复: {msg['reply_to']}"

        notifier.send(text)
        print(f"[agent_comms] Telegram通知已发送 ✓")
    except Exception as e:
        print(f"[agent_comms] Telegram跳过: {e}")


def cmd_send(from_id: str, to_ids: list[str], subject: str, body: str,
             priority: str = "medium", reply_to: str | None = None,
             no_telegram: bool = False) -> str:
    """Send a message. Returns the message ID."""
    data = _load()
    msg_id = _gen_id()
    now = datetime.now(TZ_BJT)

    msg = {
        "id": msg_id,
        "timestamp": now.isoformat(),
        "from": from_id,
        "to": to_ids,
        "subject": subject,
        "body": body,
        "priority": priority,
        "read_by": {},
        "replies": [],
    }
    if reply_to:
        msg["reply_to"] = reply_to
        for existing in data["messages"]:
            if existing["id"] == reply_to:
                existing.setdefault("replies", []).append(msg_id)
                break

    data["messages"].append(msg)
    _save(data)
    print(f"[agent_comms] 已发送 {msg_id}: {from_id} → {', '.join(to_ids)}")

    if not no_telegram:
        _send_telegram(msg)

    return msg_id


def cmd_inbox(session_id: str, unread_only: bool = False) -> list[dict]:
    """Show inbox for a session. Returns list of messages."""
    data = _load()
    inbox = []

    for msg in data["messages"]:
        targets = msg.get("to", [])
        if isinstance(targets, str):
            targets = [targets]
        if "all" not in targets and session_id not in targets:
            continue
        if unread_only and session_id in msg.get("read_by", {}):
            continue
        inbox.append(msg)

    if not inbox:
        print(f"[agent_comms] {session_id}: {'无未读消息' if unread_only else '收件箱为空'} ✓")
        return []

    unread_count = sum(1 for m in inbox if session_id not in m.get("read_by", {}))
    total = len(inbox)
    print(f"═══ [Agent收件箱] {session_id} — {unread_count}条未读 / {total}条总计 ═══")

    icons = {"critical": "🔴", "high": "🟡", "medium": "🔵", "low": "⚪"}
    for msg in inbox[-10:]:
        is_unread = session_id not in msg.get("read_by", {})
        marker = "📩" if is_unread else "📨"
        icon = icons.get(msg.get("priority", "medium"), "🔵")
        ts = msg.get("timestamp", "")[:16]
        reply_tag = f" ↩️{msg['reply_to']}" if msg.get("reply_to") else ""
        print(f"\n{marker} {icon} [{msg['id']}] {msg['subject']}{reply_tag}")
        print(f"  来自: {msg['from']} | {ts}")
        body_preview = msg.get("body", "")[:200]
        print(f"  {body_preview}")
        if msg.get("replies"):
            print(f"  💬 {len(msg['replies'])}条回复")

    return inbox


def cmd_reply(session_id: str, reply_to_id: str, body: str,
              no_telegram: bool = False) -> str | None:
    """Reply to a message. Returns new message ID."""
    data = _load()
    original = None
    for msg in data["messages"]:
        if msg["id"] == reply_to_id:
            original = msg
            break

    if not original:
        print(f"[agent_comms] 未找到消息 {reply_to_id}", file=sys.stderr)
        return None

    to_ids = [original["from"]]
    subject = f"Re: {original['subject']}"

    return cmd_send(
        from_id=session_id,
        to_ids=to_ids,
        subject=subject,
        body=body,
        reply_to=reply_to_id,
        no_telegram=no_telegram,
    )


def cmd_ack(session_id: str, msg_id: str) -> None:
    """Mark a message as read."""
    data = _load()
    found = False
    for msg in data["messages"]:
        if msg["id"] == msg_id:
            msg.setdefault("read_by", {})[session_id] = datetime.now(TZ_BJT).isoformat()
            found = True
            break

    if not found:
        print(f"[agent_comms] 未找到消息 {msg_id}", file=sys.stderr)
        sys.exit(1)

    _save(data)
    print(f"[agent_comms] {session_id} 已读 {msg_id} ✓")


def cmd_ack_all(session_id: str) -> int:
    """Mark all inbox messages as read. Returns count."""
    data = _load()
    count = 0
    now_str = datetime.now(TZ_BJT).isoformat()
    for msg in data["messages"]:
        targets = msg.get("to", [])
        if isinstance(targets, str):
            targets = [targets]
        if "all" not in targets and session_id not in targets:
            continue
        if session_id in msg.get("read_by", {}):
            continue
        msg.setdefault("read_by", {})[session_id] = now_str
        count += 1

    if count > 0:
        _save(data)
    print(f"[agent_comms] {session_id} 已读 {count} 条消息 ✓")
    return count


def cmd_thread(msg_id: str) -> None:
    """Show a message thread (original + all replies)."""
    data = _load()
    by_id = {m["id"]: m for m in data["messages"]}

    root_id = msg_id
    msg = by_id.get(msg_id)
    if not msg:
        print(f"[agent_comms] 未找到消息 {msg_id}", file=sys.stderr)
        sys.exit(1)

    while msg.get("reply_to") and msg["reply_to"] in by_id:
        root_id = msg["reply_to"]
        msg = by_id[root_id]

    def _print_msg(m: dict, depth: int = 0) -> None:
        indent = "  " * depth
        prefix = "└─" if depth > 0 else "📌"
        print(f"{indent}{prefix} [{m['id']}] {m['from']}: {m['subject']}")
        print(f"{indent}   {m.get('timestamp', '')[:16]}")
        print(f"{indent}   {m.get('body', '')[:300]}")
        for reply_id in m.get("replies", []):
            if reply_id in by_id:
                _print_msg(by_id[reply_id], depth + 1)

    print(f"═══ [消息线程] ═══")
    _print_msg(by_id[root_id])


def cmd_broadcast(from_id: str, subject: str, body: str,
                  priority: str = "high", no_telegram: bool = False) -> str:
    """Broadcast to all sessions."""
    return cmd_send(
        from_id=from_id,
        to_ids=["all"],
        subject=subject,
        body=body,
        priority=priority,
        no_telegram=no_telegram,
    )


def get_unread_for_session(session_id: str) -> list[dict]:
    """Get unread messages for a session (used by pre_session_check)."""
    if not MSG_FILE.exists():
        return []
    try:
        data = _load()
    except (json.JSONDecodeError, OSError):
        return []

    unread = []
    for msg in data["messages"]:
        targets = msg.get("to", [])
        if isinstance(targets, str):
            targets = [targets]
        if "all" not in targets and session_id not in targets:
            continue
        if session_id in msg.get("read_by", {}):
            continue
        unread.append(msg)
    return unread


def auto_ack_all(session_id: str) -> int:
    """Auto-ack all messages for session (called by pre_session_check after display)."""
    if not MSG_FILE.exists():
        return 0
    try:
        data = _load()
    except (json.JSONDecodeError, OSError):
        return 0

    count = 0
    now_str = datetime.now(TZ_BJT).isoformat()
    for msg in data["messages"]:
        targets = msg.get("to", [])
        if isinstance(targets, str):
            targets = [targets]
        if "all" not in targets and session_id not in targets:
            continue
        if session_id in msg.get("read_by", {}):
            continue
        msg.setdefault("read_by", {})[session_id] = now_str
        count += 1

    if count > 0:
        _save(data)
    return count


def main():
    parser = argparse.ArgumentParser(description="异步agent间通信系统")
    sub = parser.add_subparsers(dest="command")

    # send
    p_send = sub.add_parser("send", help="发送消息")
    p_send.add_argument("--from", dest="from_id", required=True)
    p_send.add_argument("--to", required=True, help="目标session (逗号分隔)")
    p_send.add_argument("--subject", required=True)
    p_send.add_argument("--body", required=True)
    p_send.add_argument("--priority", default="medium", choices=["critical", "high", "medium", "low"])
    p_send.add_argument("--reply-to", help="回复的消息ID")
    p_send.add_argument("--no-telegram", action="store_true")

    # inbox
    p_inbox = sub.add_parser("inbox", help="查看收件箱")
    p_inbox.add_argument("--session", required=True)
    p_inbox.add_argument("--unread-only", action="store_true")

    # reply
    p_reply = sub.add_parser("reply", help="回复消息")
    p_reply.add_argument("--session", required=True)
    p_reply.add_argument("--msg-id", required=True)
    p_reply.add_argument("--body", required=True)
    p_reply.add_argument("--no-telegram", action="store_true")

    # ack
    p_ack = sub.add_parser("ack", help="标记已读")
    p_ack.add_argument("--session", required=True)
    p_ack.add_argument("--msg-id", required=True)

    # ack-all
    p_ack_all = sub.add_parser("ack-all", help="全部标记已读")
    p_ack_all.add_argument("--session", required=True)

    # thread
    p_thread = sub.add_parser("thread", help="查看消息线程")
    p_thread.add_argument("--msg-id", required=True)

    # broadcast
    p_bcast = sub.add_parser("broadcast", help="广播消息")
    p_bcast.add_argument("--from", dest="from_id", required=True)
    p_bcast.add_argument("--subject", required=True)
    p_bcast.add_argument("--body", required=True)
    p_bcast.add_argument("--priority", default="high", choices=["critical", "high", "medium", "low"])
    p_bcast.add_argument("--no-telegram", action="store_true")

    args = parser.parse_args()

    if args.command == "send":
        to_ids = [t.strip() for t in args.to.split(",")]
        cmd_send(args.from_id, to_ids, args.subject, args.body,
                 args.priority, args.reply_to, args.no_telegram)
    elif args.command == "inbox":
        cmd_inbox(args.session, args.unread_only)
    elif args.command == "reply":
        cmd_reply(args.session, args.msg_id, args.body, args.no_telegram)
    elif args.command == "ack":
        cmd_ack(args.session, args.msg_id)
    elif args.command == "ack-all":
        cmd_ack_all(args.session)
    elif args.command == "thread":
        cmd_thread(args.msg_id)
    elif args.command == "broadcast":
        cmd_broadcast(args.from_id, args.subject, args.body,
                      args.priority, args.no_telegram)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
