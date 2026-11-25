#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Publish standalone Feishu Wiki page '临时策略：五板' as top-level root node in A-share wiki space."""
import fcntl, json, os, sys, time

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CUR_DIR)
import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
from build_master_docs import make_text_run as R, make_para_block as P, make_bullet_block as B, make_blank_line as BL

TITLE = "临时策略：五板"
MANIFEST_PATH = os.path.join(CUR_DIR, "feishu_master_manifest.json")


def _c(txt, bold=False):
    return [(txt, {"bold": True} if bold else {})]


def find_or_create_root_node(title: str) -> tuple[str, str]:
    r = s6.api(f"{s6.BASE}/open-apis/wiki/v2/spaces/{s6.SPACE_ID}/nodes?page_size=50", method="GET")
    if r.get("code") != 0:
        raise RuntimeError(f"查询根节点失败: {r}")
    for it in r.get("data", {}).get("items") or []:
        if it.get("title") == title:
            return it["obj_token"], it["node_token"]
    rc = s6.api(
        f"{s6.BASE}/open-apis/wiki/v2/spaces/{s6.SPACE_ID}/nodes",
        {"obj_type": "docx", "node_type": "origin", "title": title},
        "POST",
    )
    if rc.get("code") != 0:
        raise RuntimeError(f"创建根节点失败 [{title}]: {rc}")
    nd = rc["data"]["node"]
    time.sleep(0.6)
    return nd["obj_token"], nd["node_token"]


def main():
    doc = {
        "title": TITLE,
        "blocks": [
            P([
                R("策略定位：本策略为 Buwen 上实盘的独立临时策略，与现行六大策略里的《高标首阴 V5.1》及研发池《四进五》完全独立，绝不混称混算。", background_color=3),
                R(" 唯一强制买入硬门只有一条：真实连续五板（及顺延六板及以上）次日 09:25 竞价开盘不高于 +5.5% 且非一字涨停。"),
                R(" 绝对禁区：严禁把筹码锁仓比或换手当成一票否决硬门删票，严禁私自预筛漏报任何一只五板及以上股票。", bold=True, text_color=1),
            ]),
            P([R("一、核心买入规则与盘口机制（唯一硬门加重要成色项）", bold=True)]),
            B([
                R("1. 真实连续五板与顺延归属：", bold=True),
                R("仅限 10cm 沪深主板非 ST 股票，按实际有成交交易日算严格连续 5 连板（停牌无成交不重置连板，中间断板如 7 天 6 板不算）。同一轮连板只买一次：若五板次日一字买不到，或开盘超 +5.5% 未买但收盘续封涨停，自动顺延至 6 板、7 板及以上等待本轮首个合格开盘。高开超 +5.5% 且当日断板则整轮作废，不在断板后另造买点。"),
            ]),
            B([
                R("2. 唯一强制硬门（09:25 竞价开盘门）：", bold=True),
                R("连板次日 09:25 竞价开盘涨幅不高于 +5.5%（-10% 至 +5.5% 全包，无下限挖洞）且非一字涨停，直接开盘买入。只认 09:25 开盘价，不拿盘中回调低点倒算。盘口逻辑在于：五板后温和分歧或深水低开释放了获利盘抛压，博弈情绪承接反包；而开盘超 +5.5% 透支了次日空间，极易高开低走派发。"),
            ]),
            B([
                R("3. 锁仓比为核心成色权重（非硬淘汰门）：", bold=True),
                R("扣除最新已披露前十大流通股东后的锁仓比（满 50% 成色更优）、末板真实换手率（满 15% 较稳）与真实流通市值、龙虎榜拉萨席位、行业同业梯队，均单列并列展示。高锁仓代表外面活筹轻、拉升与反包阻力小，实证盈亏比明显高出一档，但锁仓低于 50% 不构成一票否决条件，不得借此把股票删出名单。"),
            ]),
            P([R("二、天数编号与次日卖出树", bold=True)]),
            B([
                R("天数统一编号：", bold=True),
                R("五板当天称「五板日」，五板次日（开盘买入日）统一算第 1 天，再下一天算第 2 天，依此类推。"),
            ]),
            B([
                R("95% 严重异动止盈线卖法：", bold=True),
                R("第 1 天开盘买入后，第 2 天至第 4 天按前一日收盘冻结的对应大盘指数（沪市上证A指、深市深证A指）滚动测算 10 日 100% 严重异动最紧值的 95% 止盈线。盘中触及或开盘越线即止盈卖出；若第 2 至第 4 天始终未触及，则在第 4 天收盘卖出（遇跌停或停牌卖不出顺延至首个可卖日）。另保留第 2 天收盘卖与第 4 天收盘卖作为对照。"),
            ]),
            P([R("三、实盘汇报与标准化命名纪律", bold=True)]),
            B([
                R("全量并列播报：", bold=True),
                R("每日随六大主战策略一起全量并列播报，每天盘后与早盘 09:25 把全市场每一只 5 连板及以上主板非 ST 股票 100% 全量并列报出，同步跟踪近 3 日已触发标的的当日 95% 止盈价。"),
            ]),
            B([
                R("标准化命名与样本起点：", bold=True),
                R("凡说「五板」专指本策略，说「高标」才指《高标首阴 V5.1》，说「四进五」专指研发池策略。所有涉及本策略的回测与复盘，样本起点一律固定为 2026 年 7 月 1 日之后，不拿早年长样本覆盖当前阶段实证。"),
            ]),
            P([R("四、2026 年 7 月以来实证与近两个月深市核验", bold=True)]),
            B([R("历史实证档案覆盖 2026 年 7 月至 10 月 23 日全市场 36 轮一轮一行，28 轮触发买点，26 轮走完完整周期），叠加 2026 年 9 月 25 日至 11 月 25 日深市主板 9 只五板全量核验如下。所有净收益均已扣除双边 0.30% 交易成本。")]),
            BL(), BL(), BL(),
        ],
        "tables": [
            ("表一：2026年7月以来纯五板实证分组对比（95%止盈线卖法，已扣双边0.30%成本）", [
                [_c("样本分组", True), _c("完结笔数", True), _c("胜率", True), _c("均净收益与特征", True)],
                [_c("7月至10月全市场触发"), _c("26 笔"), _c("76.9%"), _c("+7.04%（中位 +9.84%，全包无挖洞）")],
                [_c("其中 锁仓比满 50%", True), _c("18 笔", True), _c("83.3%", True), _c("+9.00%（高锁仓活筹轻，反包硬）", True)],
                [_c("其中 锁仓比低于 50%"), _c("5 笔"), _c("60.0%"), _c("-1.11%（波动更大，保留作参考不硬删）")],
                [_c("近两月深市完结(9/25起)", True), _c("5 笔", True), _c("100.0%", True), _c("+12.26%（另有真视通在途浮盈+5.22%）", True)],
            ]),
            ("表二：近两个月深市主板全部五板股跟踪（2026年9月25日至11月25日）", [
                [_c("五板日与股票", True), _c("锁仓比", True), _c("买点归属", True), _c("95%线净收益", True)],
                [_c("10/09 002242 九阳股份"), _c("72.8%"), _c("顺延6板后开-4.93%买"), _c("+14.68%")],
                [_c("10/15 002343 慈文传媒"), _c("33.2%"), _c("开+8.31%断板未买"), _c("未买入")],
                [_c("10/15 002696 百洋股份"), _c("51.7%"), _c("5板后开-6.52%买"), _c("+4.59%")],
                [_c("10/22 002724 海洋王"), _c("63.6%"), _c("5板后开-0.62%买"), _c("+18.73%")],
                [_c("10/28 000678 襄阳轴承"), _c("47.6%"), _c("开+9.99%断板未买"), _c("未买入")],
                [_c("10/30 001219 青岛食品"), _c("55.6%"), _c("5板后开+3.31%买"), _c("+14.94%")],
                [_c("11/06 002578 闽发铝业"), _c("45.7%"), _c("顺延6板后开+4.72%买"), _c("+8.37%")],
                [_c("11/23 002771 真视通"), _c("15.0%"), _c("5板后开+2.30%买"), _c("在途+5.22%(明95线19.86)")],
                [_c("11/25 002579 中京电子"), _c("35.4%"), _c("待明09:25(<=18.80触发)"), _c("待竞价")],
            ]),
        ],
        "img_path": None,
    }
    s9.audit_doc_strict_v191(doc, require_img=False)
    lock_fd = open(s6.LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        did, ntk = find_or_create_root_node(doc["title"])
        done, fail = s6.write_document_payload(did, doc["blocks"], doc["tables"], None)
        if fail > 0:
            raise RuntimeError(f"Write fail={fail}")
        time.sleep(0.8)
        s9.verify_document_v191(did, doc["title"], expected_tables_count=2, has_img=False)
        # Update manifest
        if os.path.exists(MANIFEST_PATH):
            mf = json.load(open(MANIFEST_PATH, encoding="utf-8"))
            mf.setdefault("nodes", {})["temp_five_board"] = {
                "title": TITLE,
                "node_token": ntk,
                "obj_token": did,
                "url": f"https://my.feishu.cn/wiki/{ntk}",
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            json.dump(mf, open(MANIFEST_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"PUBLISHED_TEMP_FIVE_BOARD [{ntk}] https://my.feishu.cn/wiki/{ntk}")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
