#!/usr/bin/env python3
"""
Wave 2 Orchestrator: 18 Deep Supplementary & Wu Qing Word-Shift Carbon Shards (E01 - E18).
Strictly Carbon (--model carbon --effort medium), zero Opus.
"""
import concurrent.futures
import json
import os
import subprocess
import time
import sys

sys.path.insert(0, "/tmp")
from csrc_wave1_runner import PROMPT_TEMPLATE, HEADLESS_BIN, SHARD_DIR

LOG_PATH = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/wave2_progress.log"

WAVE2_SHARDS = [
    ("E01", "2019-01 to 2026-11", "证监会副主席与核心分管领导公开发言（方星海谈外资QFII与境外上市备案、李超谈机构监管REITs与公募改革、王建军谈上市公司质量与退市分红、陈华平谈投保稽查、刘浩凌2026上交所国际投资者大会讲话），精选12-15个代表性事件与随后分管政策落地。"),
    ("E02", "2019-01 to 2026-11", "上交所、深交所、北交所理事长/总经理重大公开演讲与发布会（黄红元、蔡建春、邱勇2024-2026国际投资者大会/陆家嘴讲话、沙雁、周贵华北交所深改讲话），精选12-15个事件与交易所细则落地。"),
    ("E03", "2005-01 to 2025-12", "全国人大常委会重大资本市场修法节点与证监会说明：2005证券法公司法大修、2013优先股、2018-10-26公司法专项修改库存股回购、2019-12-28新证券法通过全面注册制、2020-12刑法修正案十一提高欺诈发行刑期、2023-12新公司法修订，精选10-14个节点。"),
    ("E04", "2004-03 to 2026-03", "历年3月全国两会《政府工作报告》涉资本市场原话精选台账（温家宝、李克强、李强2004-2026历年报告中涉股市改革、注册制、稳市场、增强内在稳定性、投融资综合改革、耐心资本原话与3月行情反应），精选14-16个年份节点。"),
    ("E05", "2005-10 to 2026-11", "历次五年规划纲要与二十届三中全会、四中/五中全会『十五五』规划建议涉资本市场最高纲领表述（十一五至十五五），核实发布日期、原话与中长期制度兑现，精选10-14个节点。"),
    ("E06", "2007-01 to 2026-02", "证监会每年年初『全国证券期货监管工作会议』（年度一号定调会）核心部署与当年政策兑现核验（2007-2026精选14-16次年初监管工作会议精确日期、主席定调关键词与当年头号政策）。"),
    ("E07", "2001-08 to 2026-11", "证监会重大稽查执法风暴与先行赔付标志性通报（银广夏、光大乌龙指、2015配资罚单、2017鲜言34.7亿罚单、康美康得新、紫晶存储泽达易盛先行赔付、恒大地产、2024宁波灵均量化处罚、2026先行赔付指导意见与财务造假严惩），精选12-15个节点。"),
    ("E08", "2000-10 to 2026-11", "公募基金与机构投资者制度变革全节点（2000超常规发展机构投资者、2012券商资管松绑、2018养老目标基金、2022个人养老金启动、2023-07公募基金费率改革启动、2024被动ETF爆发、2025-05公募基金高质量发展行动方案业绩基准挂钩、2026-10-19首批18只主动ETF获批），精选12-15个节点。"),
    ("E09", "2002-11 to 2026-11", "资本市场对外开放与互联互通重大官宣节点（2002 QFII、2011 RQFII、2014沪港通官宣与开通、2016深港通、2017纳入MSCI官宣、2019取消QFII额度限制、2023境外上市备案制生效、2024-04惠港五条、2026-10金融街论坛QFII优化与REITs纳入沪深港通），精选12-15个节点。"),
    ("E10", "2006-05 to 2026-11", "A股再融资（定增、配股、可转债）松紧周期独立台账：2006再融资重启、2014创业板小额快速定增、2017-02-17再融资新规严限18个月间隔、2018-11补流间隔缩短至6个月、2020-02-14再融资松绑8折锁6个月引爆定增牛、2023-08收紧破发破净再融资、2024-2026分类审核优胜劣汰，精选12-14个节点。"),
    ("E11", "2009-10 to 2026-11", "创业板与北交所专项深改节点：2009创业板首批28家、2013并购潮、2014创业板再融资、2020-04-27创业板注册制改革官宣与08-24落地、2021-09-02北交所官宣与11-15开市、2023-09-01北交所深改19条（北证50暴涨！）、2026创业板深化改革，精选12-15个节点。"),
    ("E12", "2001-06 to 2024-02", "【防幸存者偏差核心对照组】专门搜集2001-2024历史上『口头维稳喊话、座谈会吹风或单兵利好出台后，市场短暂冲高即回落甚至继续创出新低』的14-16个真实失败/磨底案例（如2001暂停减持后阴跌、2008.04降印花税后腰斩、2011-2012多次蓝筹喊话磨底、2015.06.27双降高开暴跌、2018.10.14春天不远后继续探底、2023.07政治局与08.18/08.27后跌至2635点）。"),
    ("E13", "2007-05 to 2025-12", "【监管降温与刺破泡沫专项组】专门搜集2007-2025历史上监管层风险提示、查配资、严控并购、批妖精、发重点监控或央媒给疯牛降温的14-16个关键节点（含高位降温见顶与低位严监管错杀两类样本）。"),
    ("E14", "2020-01 to 2026-11", "国家发改委、科技部、工信部、金融监管总局联合证监会发布的『科技金融、创投国十七条（2024.06.19）、并购贷款试点、险资私募长期投资试点（鸿鹄基金一期二期三期）』跨部门产业资本政策节点，精选12-14个事件。"),
    ("E15", "2024-02 to 2026-11", "吴清任期内（2024.02至今）历次重要公开发言『措辞边际变化与兑现时滞』专项精算：逐一核实吴清首次提『一年多次分红』『科创板八条』『并购六条』『中长期资金入市实施方案』『科创成长层第五套标准』『主动ETF』『违规减持细化处罚』『量化交易评估优化』的发言日期与正式文件落地日期的精确天数差！写入 `/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/shards/E15.json`。"),
    ("E16", "2026-10-19 to 2026-11-14", "深度对比吴清最近两场重磅演讲（2026-10-19北京金融街论坛 vs 2026-11-14上海首届中国资本市场学术年会）及2026-11上交所国际投资者大会（邱勇/刘浩凌），输出标准 events JSON 到 `E16.json`，并在 `key_observations` 中详细列出：10月19日到11月14日这26天里哪些话变重了、哪些是全新首提词、每个首提词对应什么具体监管工具！"),
]


def log2(msg: str):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_w2_shard(idx: int, total: int, spec):
    sid, win, desc = spec
    out_file = os.path.join(SHARD_DIR, f"{sid}.json")
    if os.path.exists(out_file):
        try:
            d = json.load(open(out_file, encoding="utf-8"))
            if len(d.get("events", [])) >= 3:
                log2(f"[{idx}/{total}] SKIP {sid} ({len(d['events'])} events)")
                return sid, True, len(d["events"])
        except Exception:
            pass
    prompt = PROMPT_TEMPLATE.format(shard_id=sid, window=win, desc=desc)
    for att in (1, 2):
        t0 = time.time()
        log2(f"[{idx}/{total}] START {sid} (att {att}, carbon-medium)")
        try:
            subprocess.run(
                [HEADLESS_BIN, "--model", "carbon", "--effort", "medium", "-t", "660"],
                input=prompt, text=True, capture_output=True, timeout=680
            )
            if os.path.exists(out_file):
                d = json.load(open(out_file, encoding="utf-8"))
                evs = d.get("events", [])
                if len(evs) >= 2:
                    log2(f"[{idx}/{total}] OK {sid} in {time.time()-t0:.1f}s -> {len(evs)} events")
                    return sid, True, len(evs)
        except Exception as e:
            log2(f"[{idx}/{total}] ERR {sid}: {e}")
        time.sleep(2)
    return sid, False, 0


def main():
    total = len(WAVE2_SHARDS)
    log2(f"=== Launching Wave 2: {total} Carbon Shards (max_workers=6) ===")
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(lambda x: run_w2_shard(x[0] + 1, total, x[1]), enumerate(WAVE2_SHARDS)))
    ok = sum(1 for _, s, _ in res if s)
    n_ev = sum(n for _, s, n in res if s)
    log2(f"=== Wave 2 COMPLETE in {time.time()-t0:.1f}s: {ok}/{total} shards OK, {n_ev} events ===")


if __name__ == "__main__":
    main()
