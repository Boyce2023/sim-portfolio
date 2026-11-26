#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Build strict plain-Chinese Feishu payload for 《单策略夏普提纯实证》."""

import os
import sys

FEISHU_MASTER_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
if FEISHU_MASTER_DIR not in sys.path:
    sys.path.insert(0, FEISHU_MASTER_DIR)

import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd039_single_strat_sharpe_lift_20261126/front4_redteam_and_assembly"

TITLE = "单策略夏普提纯实证"
PARENT_VALID_NODE = "OPKUwAqCDibLfRkRE87cd2aCnVc"
HUB_VALID_DOC = "IRxgdlpOUoqfV4xVYYGczGurnyD"

HUB_EXISTING_TITLES = [
    "多因子打分前视镜总阅兵",
    "六策略退化与进化体检",
    "极值商品三圈层十年实证",
    "政策与国家队雷达",
    "跨年大票 V4.0",
    "跨年妖十五年深度回测",
    "暴跌尾盘切高ROE城商行",
    "美股大跌A股低开高走实证",
    "美股对A股传导回归实证",
    "六大商品股期联动十年回测",
    "大哥护盘五句口诀十年实证",
    "A股15年16套投资理论TEI",
    "同高度PK与拉萨席位实证",
    "首板与高标市值悖论实证",
    "连板断层真空日回测",
    "高阶三四因子协同实证",
    "备选合体联测实证",
]

HUB_ROW_18 = [
    [("单策略夏普提纯实证", {})],
    [("2023至2026 四战线逐笔验", {})],
    [("盘中条件买与次日止损均没用，现役五件套维持原样", {})],
    [("零改实盘，影子稳健五件套不变", {})],
]

# Extra plain-Chinese guard covering all banned stats/engineering jargon & old RD prefixes
RD039_EXTRA_BANNED = [
    "WF", "OOS", "IS", "PIT", "BH", "FDR", "DSR", "CSCV", "PBO", "LOO", "MTM",
    "Sharpe", "Calmar", "MDD", "NAV", "PLR", "t值", "p值", "q值",
    "消融", "门禁", "闭环", "矩阵", "铁证", "RD038", "RD039", "RD036", "RD035",
    "s34_af_", "BC_zt_", "M4_CausalLOO", "Clean5", "GRAND_COMBO",
]


def _tr_elements(runs):
    if not runs:
        return [{"text_run": {"content": "", "text_element_style": {}}}]
    out = []
    for txt, st in runs:
        style = {}
        if st.get("bold"):
            style["bold"] = True
        if st.get("bg") is not None:
            style["background_color"] = st["bg"]
        elif st.get("background_color") is not None:
            style["background_color"] = st["background_color"]
        if st.get("color") is not None:
            style["text_color"] = st["color"]
        out.append({"text_run": {"content": txt.replace("`", ""), "text_element_style": style}})
    return out


def _p(runs):
    return {
        "block_type": 2,
        "text": {"elements": _tr_elements(runs), "style": {"align": 1, "folded": False}},
    }


def _b(runs):
    return {
        "block_type": 12,
        "bullet": {"elements": _tr_elements(runs), "style": {"align": 1, "folded": False}},
    }


def _o(runs):
    return {
        "block_type": 13,
        "ordered": {"elements": _tr_elements(runs), "style": {"align": 1, "folded": False}},
    }


def _cell(txt, bold=False, color=None, bg=None):
    st = {}
    if bold:
        st["bold"] = True
    if color:
        st["color"] = color
    if bg:
        st["bg"] = bg
    return [(txt, st)]


def build_rd039_payload() -> dict:
    chart1 = f"{OUT_DIR}/chart1_rd039_redteam_autopsy.png"
    chart2 = f"{OUT_DIR}/chart2_rd039_vs_rd038_grand_pk.png"

    blocks = [
        # Block 0: First sentence MUST state 有用/没用 and have bg=3
        _p([
            ("结论：四条单策略提纯改造整体没用，现役与影子合体全部维持原样。", {"bold": True, "bg": 3}),
            ("仅三进四原版四因子排雷本就有效并已入影子五件套。", {"bg": 3}),
            ("其余盘中条件单与次日五分钟止损经逐笔核查全线证伪。", {"bg": 3}),
        ]),
        _p([("一、总判断与唯一结论", {"bold": True})]),
        _p([
            ("所有 `09:30` 后盘中条件买入全部不如 `09:25` 集合竞价直买。", {}),
            ("高标与撬板也均在次日锁死与分歧点失效，只能守死集合竞价。", {}),
        ]),
        _p([
            ("三进四次日五分钟止损去掉硬编码后无效。", {}),
            ("加进五件套样本外由 `318.8万倍` 降为 `317.7万倍`。", {"bg": 3}),
            ("两组最大回撤同为 `47.58%` 毫无压缩。", {}),
        ]),
        _p([
            ("全篇四条战线均不得直接升入实盘。", {}),
            ("现役策略维持不动，影子观察继续单盯稳健五件套一季。", {}),
        ]),

        _p([("二、二进三与20cm改盘中条件单为何大败", {"bold": True})]),
        _b([
            ("全量遍历 `684` 个盘中条件单方案。", {}),
            ("其中二进三 `186` 个，20cm 三路合计 `498` 个。", {}),
            ("结果 `0` 个在样本外波动收益比或累计净值上胜过 `09:25` 直买。", {"bg": 3}),
        ]),
        _b([
            ("物理根因在于分歧转一致恰在 `09:25` 集合竞价那一刻定价。", {}),
            ("推迟到 `09:30` 后要么等不到封板踏空大牛，要么专接冲高回落假信号。", {}),
        ]),
        _b([
            ("放入总账实战资金碰撞时冲突更大。", {}),
            ("二进三改盘中单让总账样本外净值从 `61.2万倍` 腰斩至 `32.5万倍`。", {}),
            ("主因是盘中占位挤掉了原本同日轮动的大肉仓位。", {}),
        ]),

        _p([("三、高标首阴与超跌撬板为何无法靠盘中提纯", {"bold": True})]),
        _b([
            ("高标首阴过半强票在 `09:25` 平红开后即走强，占比达 `52.2%`（`24/46`）。", {}),
            ("改成盘中翻红确认后，样本外净值从 `8.99倍` 滑落至 `6.21倍`。", {}),
            ("既没滤掉诺德股份和华森制药的假突破，还踏空首开股份 `+18.30%`。", {}),
        ]),
        _b([
            ("超跌撬板本地五分钟数据覆盖率仅 `0.46%`（`2/435`）。", {}),
            ("大亏单里 `90.77%`（`59/65`）源自跌停锁死。", {"bg": 3}),
            ("痛点集中在 `2024年2月5日` 与 `7日` 次日低开割肉，盘中根本无解。", {}),
        ]),
        _b([
            ("全市场大赚股中 `46.22%` 最高价即开盘价。", {}),
            ("包括第一名禾盛新材 `+24.66%`，延迟买必错失。", {}),
            ("第一大亏股登云股份（`-19.15%`）盘中曾冲到 `+1.53%`，延迟买反接飞刀。", {}),
            ("跳过极冷涨停小于 `5` 家日虽提高均值但样本外仅 `6` 笔，纯属样本过小。", {}),
        ]),

        _p([("四、三进四硬编码漏洞验尸与止损逐笔真相", {"bold": True})]),
        _o([
            ("原版最亮眼的回撤骤降实为硬编码泄漏假象。", {"bold": True, "bg": 3}),
            ("源码硬写死剔除 `20号因子` 触发单。", {}),
            ("这恰好躲掉 `2025年1月3日` 大亏股友好集团（`-23.90%`）。", {}),
            ("样本外回撤才从 `47.58%` 压到 `31.12%`，重演了静态伪装。", {}),
        ]),
        _o([
            ("改成全 `22` 个原生因子按历史出场先后真动态排位后，假象当场粉碎。", {}),
            ("在 `2024年12月31日` 排第一最差的是 `05号因子`（统计分 `-1.77`）。", {}),
            ("`20号因子` 当天只排第三（统计分 `-1.30`）。", {}),
            ("它当时历史触发均值 `+6.15%` 高于未触发均值 `+6.12%`。", {}),
            ("严格踢最差单因子仅得 `180.1倍`，不及原版 `239.2倍`，也躲不开友好集团。", {"bg": 3}),
            ("红队已当场废除这套加减分机制，只保留干净的原版四因子排雷。", {}),
        ]),
        _o([
            ("次日 `10:00` 破昨收减 `6%` 才止损。", {}),
            ("它把三进四单策略从 `239.2倍` 抬至 `304.5倍`。", {}),
            ("但这全靠挡住 `2025年3月27日` 的中毅达。", {}),
            ("该股单笔由 `-24.67%` 缩成 `-3.74%`。", {}),
            ("代价是 `2022` 年样本内反而被误杀两只。", {}),
            ("京粮控股由 `+10.19%` 变 `-4.53%`。", {}),
            ("长久物流则由 `+0.81%` 变 `-5.33%`。", {}),
        ]),
        _o([
            ("回到统一总账才看见最冷酷的事实：中毅达从未进入总账实盘。", {"bg": 3}),
            ("`2025年3月27日` 两套总账都买了同日 `20cm` 纳川股份（`+5.50%`）。", {}),
            ("总账实盘挨满的大面是龙江交通、鼎信通讯和友好集团。", {}),
            ("三笔分别录得 `-12.72%`、`-17.39%` 和 `-23.90%`。", {}),
            ("这三只要么当日高封后未破昨收减 `6%`，要么次日低开跳水，全没触发止损。", {}),
        ]),

        _p([("五、统一总账同台合体与抗滑点高原终裁", {"bold": True})]),
        _b([
            ("在现役基准之上单加干净五分钟止损，样本外净值从 `53.4万倍` 跌至 `53.0万倍`。", {}),
            ("五年总净值更从 `5,708.7万倍` 跌至 `5,266.1万倍`，纯属负优化。", {}),
        ]),
        _b([
            ("给五件套叠五分钟止损后，千三由 `318.8万倍` 变为 `317.7万倍`。", {}),
            ("`2025至2026` 两年两套同为 `5,099.2倍`，毫无增益。", {}),
            ("其中 `2026` 下半年同为 `3.69倍`，一分未增。", {}),
            ("止损再多扣 `50` 个基点滑点跌至 `314.5万倍`。", {}),
            ("千八重扣费下也跌至 `111.1万倍`，弱于原版 `111.5万倍`。", {}),
        ]),
        _b([
            ("遍历 `32` 组止损阈值与起点时间参数高原。", {}),
            ("全部 `32` 组最大回撤同为 `47.58%` 毫无变动。", {}),
            ("有 `26` 组总净值直接低于无止损原版 `318.8万倍`，中位数仅 `310.0万倍`。", {"bg": 3}),
            ("连破四板低点微升至 `321.3万倍`（仅 `+0.78%`），统计学配对差异完全不显著。", {}),
        ]),
        _b([
            ("按 `2024年12月31日` 物理截断重新检验全部四套干净合体。", {}),
            ("截断前后所有打分与单笔收益误差均为 `0.0`。", {}),
            ("计入累计 `9,148` 次试错惩罚后增量显著度为零。", {}),
            ("最终裁决全部不改动现役代码与实盘规则。", {"bold": True, "bg": 3}),
        ]),

        _p([("六、附表与图解核验", {"bold": True})]),
        _p([("说明：下四表分别展示四战线总判决、三进四拆解、止损十笔明细与总账同台结果。", {})]),
        _p([]),
        _p([]),
        _p([]),
    ]

    tables = [
        (
            "表一：四条单策略提纯改造线统一终审判决",
            [
                [_cell("战线与目标策略", True), _cell("尝试动作", True), _cell("实测核心结果", True), _cell("最终裁决", True)],
                [_cell("二进三与20cm"), _cell("改09:30后条件单(684组)"), _cell("0/684胜原版，总账腰斩47%"), _cell("全线否决，死守09:25")],
                [_cell("高标首阴"), _cell("平红开延迟翻红确认"), _cell("净值8.99倍降至6.21倍"), _cell("全线否决，死守09:25")],
                [_cell("超跌撬板"), _cell("盘中延迟撬板或避冷日"), _cell("90.8%亏于跌停锁死且极冷仅6笔"), _cell("不可治疗，维持原版")],
                [_cell("三进四"), _cell("剔20号因子+五分钟止损"), _cell("20号硬编码造假，止损总账零增量"), _cell("废止泄漏，止损暂不入合体")],
            ],
        ),
        (
            "表二：三进四组件拆解与无偏动态剔除对比（2023至2026千三）",
            [
                [_cell("方案口径", True), _cell("笔数与胜率", True), _cell("样本外净值与回撤", True), _cell("红队归类", True)],
                [_cell("原版三进四基准"), _cell("73笔 | 65.8%"), _cell("239.2倍 | 回撤44.7%"), _cell("原版基座")],
                [_cell("仅加五分钟止损"), _cell("73笔 | 65.8%"), _cell("304.5倍 | 回撤44.7%"), _cell("样本内误杀且总账未中")],
                [_cell("仅加原版四因子排雷"), _cell("70笔 | 68.6%"), _cell("277.2倍 | 回撤44.7%"), _cell("干净可用(已入五件套)")],
                [_cell("排雷叠五分钟止损"), _cell("70笔 | 68.6%"), _cell("353.0倍 | 回撤44.7%"), _cell("三进四单边干净最优")],
                [_cell("无偏全22因子真动态剔"), _cell("67笔 | 65.7%"), _cell("180.1倍 | 回撤44.7%"), _cell("改真动态即跑输原版")],
                [_cell("硬编码剔除20号(原B版)"), _cell("63笔 | 71.4%"), _cell("401.7倍 | 回撤27.3%"), _cell("硬编码漏删，已当场毙杀")],
            ],
        ),
        (
            "表三：次日五分钟动态止损十笔关键单逐笔验尸明细",
            [
                [_cell("买入日与标的", True), _cell("总账是否在持", True), _cell("原版 vs 止损后", True), _cell("红队核查归因", True)],
                [_cell("2022.03.29 京粮控股"), _cell("V20与五件套均在"), _cell("+10.19% 变 -4.53%"), _cell("反亏14.72点误杀样本内")],
                [_cell("2022.04.14 长久物流"), _cell("V20与五件套均在"), _cell("+0.81% 变 -5.33%"), _cell("反亏6.14点误杀样本内")],
                [_cell("2022.10.19 恒久退"), _cell("V20与五件套均在"), _cell("-16.41% 变 -4.48%"), _cell("样本内减亏11.93点")],
                [_cell("2023.08.23 正和生态"), _cell("仅五件套在持"), _cell("-3.80% 变 -3.40%"), _cell("样本外微省0.40点")],
                [_cell("2023.09.19 龙江交通"), _cell("V20与五件套均在"), _cell("-12.72% 未变"), _cell("高封后未破昨收减6%逃脱")],
                [_cell("2024.02.26 合锻智能"), _cell("V20与五件套均在"), _cell("-3.22% 变 -3.98%"), _cell("唯一总账样本外止损微亏")],
                [_cell("2024.12.23 鼎信通讯"), _cell("V20与五件套均在"), _cell("-17.39% 未变"), _cell("未破止损线直接挨满")],
                [_cell("2025.01.03 友好集团"), _cell("V20与五件套均在"), _cell("-23.90% 未变"), _cell("四板未封且次日低开全吃")],
                [_cell("2025.03.27 中毅达"), _cell("两总账均未买入"), _cell("-24.67% 变 -3.74%"), _cell("同日总账已买20cm纳川+5.5%")],
                [_cell("2026.05.06 宝光股份"), _cell("两总账均未买入"), _cell("-4.12% 未变"), _cell("仅破四板低点线触发")],
            ],
        ),
        (
            "表四：统一总账同台多口径对比（样本外 2023至2026）",
            [
                [_cell("总账组合方案", True), _cell("千三净值与波动比", True), _cell("千五与千八净值", True), _cell("两亿成交净值与回撤", True)],
                [_cell("V20现役基准"), _cell("53.4万倍 | 4.624"), _cell("35.3万 | 18.9万"), _cell("43.8万倍 | 回撤47.58%")],
                [_cell("V20仅五分钟止损"), _cell("53.0万倍 | 4.621"), _cell("35.0万 | 18.7万"), _cell("43.4万倍 | 回撤47.58%")],
                [_cell("V20加三进四净版"), _cell("76.6万倍 | 4.821"), _cell("50.7万 | 27.2万"), _cell("68.6万倍 | 回撤47.58%")],
                [_cell("稳健五件套(原版)"), _cell("318.8万倍 | 5.220"), _cell("209.6万 | 111.5万"), _cell("158.7万倍 | 回撤47.58%")],
                [_cell("五件套加五分钟止损"), _cell("317.7万倍 | 5.235"), _cell("208.8万 | 111.1万"), _cell("158.1万倍 | 回撤47.58%")],
                [_cell("五件套止损扣滑50点"), _cell("314.5万倍 | 5.230"), _cell("206.7万 | 110.0万"), _cell("156.5万倍 | 回撤47.58%")],
                [_cell("五件套加破四低止损"), _cell("321.3万倍 | 5.240"), _cell("211.2万 | 112.4万"), _cell("159.9万倍 | 回撤47.58%")],
                [_cell("全策略稳健六改+止损"), _cell("317.3万倍 | 5.329"), _cell("211.1万 | 114.3万"), _cell("172.3万倍 | 回撤47.58%")],
            ],
        ),
    ]

    return {
        "title": TITLE,
        "parent_node_token": PARENT_VALID_NODE,
        "hub_doc_id": HUB_VALID_DOC,
        "blocks": blocks,
        "tables": tables,
        "img_path": chart1,
        "charts": [chart1, chart2],
    }


def validate_rd039_payload_strict(payload: dict):
    s9.check_first_sentence_rule(payload)
    long_sents = s9.audit_doc_strict_v191(payload, require_img=True)
    if long_sents:
        raise ValueError(f"存在超40字长句 ({len(long_sents)}条)")
    for cpath in payload.get("charts", []):
        if not os.path.exists(cpath):
            raise FileNotFoundError(f"缺失图表文件: {cpath}")

    texts = []
    for b in payload["blocks"]:
        bt = b["block_type"]
        if bt == 2:
            texts.append("".join(e["text_run"]["content"] for e in b["text"]["elements"]))
        elif bt == 12:
            texts.append("".join(e["text_run"]["content"] for e in b["bullet"]["elements"]))
        elif bt == 13:
            texts.append("".join(e["text_run"]["content"] for e in b["ordered"]["elements"]))
    for t_title, t_rows in payload["tables"]:
        texts.append(t_title)
        for r in t_rows:
            for c in r:
                texts.append("".join(x for x, _ in c))
    for r in HUB_ROW_18:
        texts.append("".join(x for x, _ in r))

    full_blob = "\n".join(texts)
    for w in RD039_EXTRA_BANNED:
        if w in full_blob:
            raise ValueError(f"发现禁用统计/工程缩写或代号 '{w}'")
    print(f"[RD039 Payload Audit PASS] 标题=《{payload['title']}》 正文块={len(payload['blocks'])} 表格={len(payload['tables'])} 图表={len(payload['charts'])}")
