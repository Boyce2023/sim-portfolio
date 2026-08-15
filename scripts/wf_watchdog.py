#!/usr/bin/env python3
"""
Workflow 卡死哨兵 — 治"规则存在但没有触发器"

⛔缘起(2026-08-14): 大beta workflow 在 48/50 卡死 44 分钟才被发现。
   根因不是不知道规则(memory 里明写"20分钟无进展=强制主动复查修复"),
   是**没有任何机制提醒我去查**,全靠自己想起来。
   这与 30agent 自审发现的"没有踏空侧自我 flag 机制"是同一类病:
   规则写在纸上,但系统里没有会响的铃。

判定逻辑:
  - 读 workflow 的 journal.jsonl,取最后写入时间与已完成 agent 数
  - 静默 > STALL_MIN 分钟且未达总数 → 判定 stalled
  - parallel() 是屏障: 单个 agent 挂住会拖死整个后续 phase,
    所以"还差 1-2 个就完成"反而是最危险的信号,单独标注

用法:
  python3 wf_watchdog.py <workflow_dir> [--total N] [--stall-min 20]
  python3 wf_watchdog.py --scan          # 扫本 session 全部 workflow

⛔会话隔离: 只扫本 session 目录下的 workflow,不跨 session。
"""
import argparse
import json
import os
import sys
import time

SESSION = "06b77c9f-f42f-428a-b19d-79569785a609"
WF_ROOT = os.path.expanduser(
    f"~/.claude/projects/-Users-huaichuaibeimeng-claude-projects/{SESSION}/subagents/workflows")
STALL_MIN = 20


def probe(wf_dir, total=None, stall_min=STALL_MIN):
    jp = os.path.join(wf_dir, "journal.jsonl")
    if not os.path.exists(jp):
        return None
    done = 0
    last_label = ""
    try:
        with open(jp) as f:
            for line in f:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("type") != "result":
                    continue
                done += 1
                r = o.get("result")
                if isinstance(r, dict):
                    last_label = (r.get("factor") or r.get("beta") or r.get("task") or "")[:40]
    except Exception as e:
        return {"dir": wf_dir, "error": str(e)[:80]}
    silent = (time.time() - os.path.getmtime(jp)) / 60
    # ⛔假阳性修复(2026-08-14首次运行即发现): 静默久 != 卡死。
    #   早已完成的历史 workflow 也永远静默(实测有静默7万分钟=49天的)。
    #   只有"最近还活着过、现在突然不动"才是卡死。超过 MAX_AGE_MIN 一律视为历史存档。
    MAX_AGE_MIN = 6 * 60
    archived = silent > MAX_AGE_MIN
    stalled = (not archived) and silent > stall_min and (total is None or done < total)
    # parallel() 屏障: 差 1-2 个未完成时,单个挂起 agent 拖死整个后续 phase
    near_done = total is not None and 0 < (total - done) <= 2
    return {
        "dir": os.path.basename(wf_dir),
        "done": done,
        "total": total,
        "silent_min": round(silent, 1),
        "last": last_label,
        "stalled": stalled,
        "archived": archived,
        "barrier_risk": stalled and near_done,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wf_dir", nargs="?", help="workflow 目录(绝对路径或 wf_xxx 名)")
    ap.add_argument("--total", type=int, default=None, help="预期 agent 总数")
    ap.add_argument("--stall-min", type=int, default=STALL_MIN)
    ap.add_argument("--scan", action="store_true", help="扫本 session 全部 workflow")
    a = ap.parse_args()

    targets = []
    if a.scan:
        if not os.path.isdir(WF_ROOT):
            print("无 workflow 目录")
            return 0
        for d in sorted(os.listdir(WF_ROOT)):
            p = os.path.join(WF_ROOT, d)
            if os.path.isdir(p):
                targets.append(p)
    elif a.wf_dir:
        p = a.wf_dir if os.path.isabs(a.wf_dir) else os.path.join(WF_ROOT, a.wf_dir)
        targets.append(p)
    else:
        ap.error("给 wf_dir 或用 --scan")

    any_stall = False
    for t in targets:
        r = probe(t, a.total, a.stall_min)
        if not r:
            continue
        if r.get("error"):
            print(f"⚠️  {r['dir']}: 读取失败 {r['error']}")
            continue
        if r.get("archived") and a.scan:
            continue          # 历史存档不刷屏,只在指定单个目录时显示
        tot = f"/{r['total']}" if r["total"] else ""
        tag = ""
        if r["barrier_risk"]:
            tag = "  ⛔⛔ 屏障风险: 只差1-2个,极可能是单agent挂死拖住整个phase"
            any_stall = True
        elif r["stalled"]:
            tag = f"  ⛔ 疑似卡死(静默>{a.stall_min}分钟)"
            any_stall = True
        print(f"{r['dir']}: {r['done']}{tot} | 静默 {r['silent_min']} 分钟 | 最后: {r['last']}{tag}")

    if any_stall:
        print("\n⛔ 处置建议(按顺序试,别反复重试同一条路):")
        print("  1. TaskStop 停掉 workflow")
        print("  2. 从 journal.jsonl 抢救已完成结果(别丢已经跑出来的东西)")
        print("  3. 用抢救的数据直接跑综合层,或 resumeFromRunId 只重跑卡住那个")
        print("  4. ⛔别干等——20分钟无进展就是修复信号,不是耐心信号")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
