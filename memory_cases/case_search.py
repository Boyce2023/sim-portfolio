#!/usr/bin/env python3
"""
case_search.py — 交易案例库轻量检索(重建任务A3, 2026-08-14)

设计目的: RPD决策模型(Klein)靠"匹配过去案例"而不是"翻规则表"。这个脚本
不是语义检索/向量数据库，就是按 decision_type + 关键词/标签 做粗筛，
输出 <20 条候选的 case_id + one_line，决策时人工/agent再去对应的
cases_*.md 文件里读命中案例的全文。

用法:
  python3 case_search.py --decision 建仓 --keyword 灾难线
  python3 case_search.py --ticker 600549
  python3 case_search.py --keyword "扫描未重现" --limit 5
  python3 case_search.py --decision 观察 --attribution 情绪drift
  python3 case_search.py --tag T14
  python3 case_search.py --list-buckets          # 列出4个bucket文件+计数
  python3 case_search.py --show EX-001           # 直接打印某个case的索引记录(不含全文)

不做的事: 不读取/解析 cases_*.md 全文做语义匹配（那是Read工具的活，不是
本脚本的活）；不依赖任何向量库/embedding；不联网。纯本地JSON过滤，几十行。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(HERE, "cases_index.json")


def load_cases():
    with open(INDEX_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data


def matches(case, args):
    if args.decision and case.get("decision_type", "") != args.decision:
        # 允许模糊：'放弃(推测)' 之类的后缀也算命中 '放弃'
        if not case.get("decision_type", "").startswith(args.decision):
            return False
    if args.ticker:
        tks = (case.get("ticker") or "")
        if args.ticker not in tks.split(",") and args.ticker not in tks:
            return False
    if args.attribution and args.attribution not in (case.get("attribution") or ""):
        return False
    if args.keyword:
        kw = args.keyword.lower()
        haystack = " ".join([
            case.get("one_line", ""),
            case.get("transferable_pattern_short", ""),
            case.get("name", "") or "",
            " ".join(case.get("tags", [])),
        ]).lower()
        if kw not in haystack:
            return False
    if args.tag:
        tags_lower = [t.lower() for t in case.get("tags", [])]
        if args.tag.lower() not in tags_lower:
            return False
    if args.source_type and case.get("source_type") != args.source_type:
        return False
    if args.verified_only and not case.get("verified_via_sina"):
        return False
    return True


def print_case_row(case):
    print(f"[{case['case_id']}] {case.get('name','')}({case.get('ticker','')}) "
          f"| {case.get('decision_type','')} {case.get('date') or ''}")
    print(f"    {case.get('one_line','')}")
    print(f"    归因: {case.get('attribution','')} | 置信度: {case.get('confidence','')} "
          f"| 验证: {'sina已核实' if case.get('verified_via_sina') else '未额外核实'}")
    if case.get("cross_reference"):
        print(f"    关联: {case['cross_reference']}")
    print(f"    -> 全文见 {case.get('file','')} 内 {case['case_id']} 章节")
    print()


def main():
    ap = argparse.ArgumentParser(description="交易案例库检索(decision_type+关键词粗筛)")
    ap.add_argument("--decision", choices=["建仓", "加仓", "减仓", "清仓", "观察", "放弃"],
                     help="按决策类型过滤")
    ap.add_argument("--ticker", help="按股票代码过滤(6位数字)")
    ap.add_argument("--keyword", help="在one_line/pattern/name/tags里做子串匹配(不区分大小写)")
    ap.add_argument("--tag", help="精确匹配某个tag")
    ap.add_argument("--attribution", help="按归因bucket过滤(子串匹配，如'情绪drift'/'规则误用')")
    ap.add_argument("--source-type", dest="source_type",
                     choices=["trade_log", "scan_history", "sop_doc", "data_gap"],
                     help="按数据来源类型过滤")
    ap.add_argument("--verified-only", action="store_true",
                     help="只看用sina日K额外核实过结果的案例")
    ap.add_argument("--limit", type=int, default=20, help="最多返回几条(默认20)")
    ap.add_argument("--list-buckets", action="store_true", help="列出4个bucket文件及计数，不做过滤")
    ap.add_argument("--show", help="直接按case_id打印单条索引记录(不含全文)")
    args = ap.parse_args()

    data = load_cases()
    cases = data["cases"]

    if args.list_buckets:
        print(f"案例库总计: {len(cases)} 条 (meta声称: {data['_meta']['total_cases']})")
        for bucket, desc in data["_meta"]["buckets"].items():
            print(f"  {bucket}: {desc}")
        print(f"\n与 INDEX.json (同目录，8条种子集，规则速查格式) 的关系:")
        print(f"  {data['_meta']['relation_to_existing_INDEX_json'][:200]}...")
        return

    if args.show:
        hit = [c for c in cases if c["case_id"] == args.show]
        if not hit:
            print(f"未找到 case_id={args.show}", file=sys.stderr)
            sys.exit(1)
        print_case_row(hit[0])
        return

    if not any([args.decision, args.ticker, args.keyword, args.tag,
                args.attribution, args.source_type, args.verified_only]):
        print("至少提供一个过滤条件 (--decision/--ticker/--keyword/--tag/--attribution/"
              "--source-type/--verified-only)，或用 --list-buckets / --show CASE_ID",
              file=sys.stderr)
        sys.exit(1)

    results = [c for c in cases if matches(c, args)]
    results = results[: args.limit]

    if not results:
        print("无命中。放宽条件再试，或直接去 cases_*.md 通读对应bucket。")
        return

    print(f"命中 {len(results)} 条（上限{args.limit}）:\n")
    for c in results:
        print_case_row(c)


if __name__ == "__main__":
    main()
