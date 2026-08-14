#!/usr/bin/env python3
"""
PreToolUse hook (设计稿·未接入settings.json，需人工激活): 物理挡死"没读加载协议就下单"。

背景: 重建任务A5(2026-08-14) 诊断出的核心失败模式——规则写对了(如
feedback_screening_two_axis.md两轴分离)但决策时没被"调用"，靠自觉记得读=
两个月后同类错误照犯。本hook把"决策前先查DECISION_PROTOCOL.md"从自觉
升级为强制: execute_trade.py对A股账户的buy/sell/short/cover调用前，
必须在本session transcript里找到一次对 sim-portfolio/DECISION_PROTOCOL.md
的Read，否则deny。

只挡A股(--account cn)，不影响美股/研究/面试session — 即使将来接入全局
settings.json(PreToolUse是全局钩子)，其他session从不调用这个组合命令，
天然零干扰。

⛔ 激活步骤(本脚本写好后默认不生效，需显式操作):
  1. 把下面这段加进 ~/.claude/settings.json 的 "PreToolUse" 数组:
     {
       "matcher": "Bash",
       "hooks": [{"type": "command",
                  "command": "python3 /Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/decision_protocol_gate.py",
                  "timeout": 5}]
     }
  2. 这是改公共设施(hooks配置全局共享) — 按 feedback_cross_session_protocol.md
     必须先telegram广播给其他session再改，不能単session静默上线。
  3. 激活后失败模式=fail-open(hook自身报错/超时不拦单，只在明确判定"没读"
     时才deny)，避免hook bug把真实下单锁死。

失败模式设计: 任何解析异常 → 放行(print {})。宁可漏拦，不可误伤(交易系统
可用性优先于本机制本身的完备性)。
"""
import collections
import json
import os
import re
import sys

# 只挡A股账户的下单动作。美股/研究/面试session不受影响。
CMD_PATTERN = re.compile(
    r"execute_trade\.py\s+(buy|sell|short|cover).*--account[= ]cn", re.IGNORECASE
)
PROTOCOL_FILENAME = "DECISION_PROTOCOL.md"


def was_protocol_read(transcript_path: str) -> bool:
    """扫描本session transcript尾部，找有没有Read过DECISION_PROTOCOL.md。"""
    if not transcript_path or not os.path.exists(transcript_path):
        return True  # 拿不到transcript = 无法判断 = fail-open放行
    try:
        with open(transcript_path, encoding="utf-8") as f:
            tail = collections.deque(f, maxlen=400)
        for raw_line in tail:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except Exception:
                continue
            if entry.get("type") != "assistant":
                continue
            msg = entry.get("message", {})
            content = msg.get("content", "") if isinstance(msg, dict) else ""
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use":
                    continue
                if block.get("name") != "Read":
                    continue
                fp = (block.get("input", {}) or {}).get("file_path", "")
                if PROTOCOL_FILENAME in fp:
                    return True
        return False
    except Exception:
        return True  # 解析出错 = fail-open放行


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        print(json.dumps({}))
        return

    tool_name = data.get("tool_name", "")
    if tool_name != "Bash":
        print(json.dumps({}))
        return

    command = (data.get("tool_input", {}) or {}).get("command", "")
    if not CMD_PATTERN.search(command):
        print(json.dumps({}))
        return

    transcript_path = data.get("transcript_path", "")
    if was_protocol_read(transcript_path):
        print(json.dumps({}))
        return

    action = CMD_PATTERN.search(command).group(1).lower()
    section = "建仓判断" if action in ("buy",) else "卖出判断"
    reason = (
        f"⛔ 决策加载协议(重建A5·2026-08-14): 本session还没读过 "
        f"sim-portfolio/DECISION_PROTOCOL.md 就要跑 execute_trade.py {action} "
        f"(A股账户)。先 Read sim-portfolio/DECISION_PROTOCOL.md，定位到"
        f"'{section}'场景对应的任务层文件，读完再执行。"
        f"这不是走过场——feedback_screening_two_axis.md两轴分离规则写对两个月"
        f"没被调用、strategy_astock.md卖出规则版本漂移，两次事故都是'规则存在但"
        f"决策时没读'，这个gate就是治这个病。"
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
