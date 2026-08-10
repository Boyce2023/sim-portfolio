#!/usr/bin/env python3
"""
Workflow 存活检查 · 2026-08-10
────────────────────────────────────────────────────────────────────────────
【为什么有这个脚本】
2026-08-07 13:05 起了一个25 agent的"992.8万空仓重建研究"workflow。
13:09 有8个agent启动并正常工作(各写了91~171KB),13:14 全部停止,
**零个result记录,输出文件0字节**。而我直到 08-10 用户问起才发现——**隔了3天**。

后果: 账户100%现金空转3天(1个交易日),清仓那8只全部上涨,机会成本16.38万(净值-1.65%);
      同期CXO板块全线涨停(博腾+20.02%/义翘+20.00%/药石+18.39%),而它们就在我8/7的probe名单里。
      期间我每次向用户报进度都说"它还在跑"——**报的是假进度**。

【根因】13:14 正是我在前台密集跑Bash(行情/龙虎榜/股东数据/多次WebSearch)的时候。
       把workflow放后台了, 但自己在前台又跑重活, 把它挤死了。
       更致命的是它**死得无声无息**——没有异常, 没有报错, 就是不再产出。

【铁律】(全局CLAUDE.md §00 + "20分钟无进展强制复查"的具体落地)
  ①起完workflow, 2-5分钟内必须验活一次(看journal有没有新的result或started)
  ②workflow运行期间, 前台不跑重活(大批Bash/WebSearch/并发拉数)
  ③每次向用户报进度前, 必须实际查一次, 禁止凭"我起过它"就说"它在跑"

用法:
  python3 workflow_health.py                    # 列出所有workflow的存活状态
  python3 workflow_health.py <run_id>           # 查特定workflow
  python3 workflow_health.py --stale-min 10     # 超过N分钟无更新即判定可疑(默认10)
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

WF_ROOT = os.path.expanduser(
    "~/.claude/projects/-Users-huaichuaibeimeng-claude-projects/"
    "0271364f-8cab-4319-af5d-5048f0719e12/subagents/workflows"
)


def probe(run_dir, stale_min):
    """只读 journal.jsonl(workflow自身的编排日志), 不读 agent-*.jsonl(那是subagent transcript,
    受会话隔离铁律约束且体积大)。journal足够判断存活。"""
    jp = os.path.join(run_dir, "journal.jsonl")
    if not os.path.exists(jp):
        return dict(run=os.path.basename(run_dir), state="NO_JOURNAL",
                    note="journal未生成: workflow可能起跑即失败")
    started = done = 0
    for ln in open(jp, encoding="utf-8", errors="ignore"):
        if '"type":"started"' in ln:
            started += 1
        elif '"type":"result"' in ln:
            done += 1
    age_min = (time.time() - os.path.getmtime(jp)) / 60
    if done >= started and started > 0:
        state = "DONE"
    elif age_min > stale_min:
        # ⭐这就是08-07事故的特征: 有started没result, 且长时间不再更新
        state = "SUSPECT_DEAD"
    else:
        state = "RUNNING"
    return dict(run=os.path.basename(run_dir), state=state, started=started, done=done,
                age_min=round(age_min, 1),
                last=datetime.fromtimestamp(os.path.getmtime(jp)).strftime("%m-%d %H:%M"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id", nargs="?")
    ap.add_argument("--stale-min", type=float, default=10,
                    help="超过N分钟journal无更新且未完成 → 判SUSPECT_DEAD (默认10)")
    a = ap.parse_args()

    if not os.path.isdir(WF_ROOT):
        print(f"[err] workflow目录不存在: {WF_ROOT}")
        sys.exit(1)

    dirs = sorted((os.path.join(WF_ROOT, d) for d in os.listdir(WF_ROOT)
                   if d.startswith("wf_")), key=os.path.getmtime, reverse=True)
    if a.run_id:
        dirs = [d for d in dirs if a.run_id in os.path.basename(d)]
        if not dirs:
            print(f"[err] 找不到 {a.run_id}")
            sys.exit(1)

    rows = [probe(d, a.stale_min) for d in dirs[:15]]
    print(f"{'run_id':<22}{'状态':<16}{'started':>8}{'done':>6}{'静默(分)':>10}  最后更新")
    print("-" * 78)
    bad = 0
    for r in rows:
        mark = {"DONE": "✅DONE", "RUNNING": "🔄RUNNING",
                "SUSPECT_DEAD": "⛔SUSPECT_DEAD", "NO_JOURNAL": "⛔NO_JOURNAL"}[r["state"]]
        if r["state"].startswith(("SUSPECT", "NO_")):
            bad += 1
        print(f"{r['run']:<22}{mark:<16}{r.get('started', 0):>8}{r.get('done', 0):>6}"
              f"{r.get('age_min', 0):>10}  {r.get('last', '-')}")
    if bad:
        print(f"\n⛔ {bad}个workflow疑似已死(有started无result且长时间静默)。")
        print("   这正是2026-08-07事故的特征——当时我隔了3天才发现,期间还在向用户报假进度。")
        print("   处置: 用 Workflow({scriptPath, resumeFromRunId}) 续跑(未变的agent走缓存),")
        print("         或确认无价值后重起。⛔不要假设它还在跑。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
