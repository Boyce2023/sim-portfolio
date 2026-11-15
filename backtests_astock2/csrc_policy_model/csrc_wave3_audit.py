#!/usr/bin/env python3
"""
Wave 3 Orchestrator: 12 Carbon Audit, Timestamp-Verification & Deep Mechanism Synthesis Agents.
Strictly Carbon (--model carbon --effort medium), zero Opus.
Reads the compiled 144-factor backtest CSV & perturbation grids and outputs audited synthesis JSONs.
"""
import concurrent.futures
import json
import os
import subprocess
import time

HEADLESS_BIN = "/Users/huaichuaibeimeng/.claude/nexus/scripts/claude-headless"
BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114"
BT_DIR = os.path.join(BASE_DIR, "backtest")
AUDIT_DIR = os.path.join(BASE_DIR, "audit")
os.makedirs(AUDIT_DIR, exist_ok=True)

TASKS = [
    ("W3_01", "核查 `backtest/master_events_pit.parquet` 中所有 POLITBURO 与 CENTRAL_ECON_CONF 事件的日期与发布时段准确性，挑出历史最关键10次政治局定调转向并总结政治局措辞与排序规律。"),
    ("W3_02", "核查 `backtest/master_events_pit.parquet` 中排名前25个市场波动最大的救市与降温事件（如2005.06.27、2008.09.18、2015.07.08、2018.10.19、2022.03.16、2023.08.27、2024.02.06、2024.09.24、2025.01.23、2026.10.19、2026.11.14）的 `release_slot` 是否存在任何未来函数偏差，如有需修正的条目按 `{\"event_date\": \"YYYY-MM-DD\", \"new_release_slot\": \"AMC|BMO|INTRADAY\"}` 写入 `fixes` 数组。"),
    ("W3_03", "读取 `backtest/factors_144_full_ledger.csv` 中 F001至F036（权力层级与话语兑现真伪）回测结果，用通俗大白话与第一性原理提炼核心规律：为什么单兵口头喊话失效、多部委加央行资产负债表工具才有效？"),
    ("W3_04", "读取 `backtest/factors_144_full_ledger.csv` 中 F037至F056 及 `backtest/perturbation_grids.json` 的左右打磨表，精确指出回撤深度、成交分位与首日高开幅度的最优买点区间与追高死穴区间。"),
    ("W3_05", "读取 F057至F072（严监打假、退市、量化高频、违规减持与大小盘剪刀差）回测数据，提炼严监管表态如何抽干纯炒作微盘流动性并把资金逼向红利与真成长。"),
    ("W3_06", "读取 F073至F096（硬科技科创、并购重组、中特估红利、券商渣男放量与缩量分化）回测数据，给出四大行业政策主线的真实胜率、超额幅度与放量确认条件。"),
    ("W3_07", "读取 F097至F114 及 `grid4_seven_chairmen_scorecard`（周小川至吴清七任主席横向成绩单、新官蜜月期与两会/陆家嘴/金融街场域规律），提炼历任主席施政风格与吴清时代的最大结构性不同。"),
    ("W3_08", "读取 F115至F144 及 `grid5_exchange_surveillance_sweep`（超短线连板接力、一进二、高标首阴与一级底部/双轨配对合成模型样本外表现），诚实指出哪些政策信号能帮短线避坑、哪些只适合管中线仓位。"),
    ("W3_09", "读取 `shards/A24.json` 与 `shards/E16.json` 及144因子表，逐句拆解吴清 2026-10-19 金融街论坛演讲（首批18只主动ETF、警惕境外挂钩A股个股杠杆产品、违规减持认定细化）的真实含义与市场影响。"),
    ("W3_10", "读取 `shards/A24.json`、`shards/E15.json`、`shards/E16.json` 及 `grid3_verb_to_policy_lead`（动词领先天数表），逐句深度拆解吴清今天（2026-11-14）首届中国资本市场学术年会致辞五大方向的真实政策密码、与过往措辞的边际变化及未来15至60天即将落地的具体细则预判。"),
    ("W3_11", "专门复盘 `factors_144_full_ledger.csv` 中被证伪的典型死胡同与诱多陷阱因子（如单降印花税开盘追高、高位天量利好、纯口头喊话无后续政策、缩量炒券商），讲透散户踩坑的供需本质。"),
    ("W3_12", "综合全量144因子得分与吴清2026.10-11最新定调，输出2026年11月中旬至2027年初（含12月政治局与中央经济工作会议窗口）的A股主基调判断、占优方向、规避方向与可检验的观察锚点。"),
]

W3_PROMPT = """你是东方港湾买方首席策略审计员（Carbon 模型）。
请读取 `/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/` 下的真实回测结果文件，执行专项审计任务 {tid}：
{desc}

【严格写作纪律】
1. 每一条结论必须引用我们回测账本里的真实样本数 N、胜率、开盘起算净超额百分比，零编造。
2. 全程说通俗大白话，每句 15 至 38 字，零连字符 `-`、零破折号 `—/——`、零感叹号 `！`、零禁用黑话（禁写赋能/生态/闭环/范式/矩阵/全景/硬核/抓手/撬动/罕见/胜负手；涨跌统一写『涨 X%』『跌 X%』『跑赢 X%』『跑输 X%』）。
3. 将输出保存为合法 JSON：`/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/audit/{tid}.json`，结构为：
{{
  "task_id": "{tid}",
  "core_conclusion": "一句话直白总结论",
  "key_findings": ["带真实回测数字的发现1", "发现2", "发现3", "发现4", "发现5"],
  "fixes": []
}}
写完核验 JSON 合法后回复 `DONE {tid}`。
"""


def run_one(spec):
    tid, desc = spec
    out_p = os.path.join(AUDIT_DIR, f"{tid}.json")
    prompt = W3_PROMPT.format(tid=tid, desc=desc)
    t0 = time.time()
    subprocess.run([HEADLESS_BIN, "--model", "carbon", "--effort", "medium", "-t", "420"], input=prompt, text=True, capture_output=True, timeout=440)
    ok = os.path.exists(out_p)
    print(f"[{time.strftime('%H:%M:%S')}] {tid} {'OK' if ok else 'MISS'} ({time.time()-t0:.1f}s)", flush=True)
    return tid, ok


def main():
    print(f"=== Wave 3: Launching {len(TASKS)} Carbon Audit & Synthesis Agents (max_workers=12) ===", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        res = list(ex.map(run_one, TASKS))
    print(f"=== Wave 3 DONE: {sum(1 for _, ok in res if ok)}/{len(TASKS)} OK ===", flush=True)


if __name__ == "__main__":
    main()
