#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Pure plain-Chinese Feishu payload builder for RD038 master audit report."""

import re

TITLE = "备选合体联测实证"
HUB_ROW = [
    "备选合体联测实证",
    "2023至2026 合体联测109次",
    "合体稳健319.8万倍入影子，两项假信号剔除",
    "守死V20，影子跟四件套一季",
]

RD036_FORBIDDEN_TOKENS = [
    "WF", "OOS", "IS", "PIT", "BH-FDR", "DSR", "CSCV", "PBO", "MTM",
    "Sharpe", "MDD", "NAV", "PLR", "GBDT", "ANOVA", "Calmar", "LOO",
    "t值", "p值", "q值", "消融", "门禁", "闭环", "矩阵", "铁证", "重锚", "回灌",
    "王牌", "天花板",
]


def T(txt: str, bold: bool = False, hl: bool = False) -> dict:
    """Text block helper."""
    st = {}
    if bold:
        st["bold"] = True
    if hl:
        st["background_color"] = 3
    return {
        "block_type": 2,
        "text": {
            "elements": [{"text_run": {"content": txt, "text_element_style": st}}],
            "style": {"align": 1, "folded": False},
        },
    }


def MIXED(parts: list) -> dict:
    """Text block with mixed runs: list of (text, bold, hl)."""
    els = []
    for txt, bold, hl in parts:
        st = {}
        if bold:
            st["bold"] = True
        if hl:
            st["background_color"] = 3
        els.append({"text_run": {"content": txt, "text_element_style": st}})
    return {
        "block_type": 2,
        "text": {"elements": els, "style": {"align": 1, "folded": False}},
    }


def B(txt: str, bold: bool = False, hl: bool = False) -> dict:
    """Bullet block helper."""
    st = {}
    if bold:
        st["bold"] = True
    if hl:
        st["background_color"] = 3
    return {
        "block_type": 12,
        "bullet": {
            "elements": [{"text_run": {"content": txt, "text_element_style": st}}],
            "style": {"align": 1, "folded": False},
        },
    }


def BL() -> dict:
    """Blank line block."""
    return {
        "block_type": 2,
        "text": {
            "elements": [{"text_run": {"content": "", "text_element_style": {}}}],
            "style": {"align": 1, "folded": False},
        },
    }


def C(txt: str, bold: bool = False) -> list:
    """Table cell helper returning list of (str, style_dict)."""
    return [(txt, {"bold": True} if bold else {})]


def build_rd038_payload(chart1_path: str, chart2_path: str) -> dict:
    """Build pure plain-Chinese payload strictly audited for RD038."""
    blocks = [
        MIXED([
            ("结论：备选合体联测确实有用，稳健包达319.79万倍且几乎零挤占。", True, True),
            ("但8127次校正后增量过关概率仅0.6%且回撤未降；实盘守死V20.0并把稳健包入影子观察一季。", False, False),
        ]),
        BL(),
        T("一、合体总结论与实盘定级", bold=True),
        B("单策略拆开样本薄，放进全系统单仓才见真章；合体稳健319.79万倍，进攻323.95万倍。", bold=False),
        B("两套合体包相对现役53.43万倍基准分别大涨近5倍；年化夏普由4.624升至5.333与5.323。", bold=False),
        B("仅改20cm得134万至153万倍，仅改其余五策略得143.5万倍；合体联测起乘数共振飙至320万倍。", bold=False),
        B("稳健包为影子首选：80bps魔鬼滑点下稳健包115.2万倍反超进攻包；且关闭银行家舍入后净值仅微降0.3%。", bold=False),
        B("进攻包在去舍入后骤降19.8%至259.7万倍；合体稳健包在两亿成交过滤下亦达173.7万倍领跑。", bold=False),
        B("暂不上实盘两大铁因：累计8127次试错校正后增量概率仅0.6%；最大回撤仍停在47.58%未降。", bold=False),
        BL(),
        T("二、留一法拆解真功臣与两条假信号", bold=True),
        T("并非所有备选都真有用：三件套贡献九成真增量，弱红换仓与一进二预约挂单必须当场剔除。", bold=True, hl=True),
        B("真增量主力：20cm均值贡献2.23倍，三进四排雷1.45倍；高标冷清删拖油瓶另加1.26倍增量。", bold=False),
        B("二进三组合贡献+7.8%，撬板冷清跳过贡献+18.6%；一进二无干净增量，继续维持0项升级。", bold=False),
        B("弱红早盘换仓属伪增厚：2023至2026样本外触发0次；该规则对合体单仓净值实际为零贡献。", bold=False),
        B("一进二预约挂单仅提档已触发反而拖累11%，净值跌至283.8万；必须从精简包中当场剔除该假信号。", bold=False),
        B("预约挂单表面+1.6%全靠2026年7月28日一次未成交挂单；刚好撞大运躲过长城军工的-12.39%。", bold=False),
        B("剔除上述两假动作后的精简五件套达318.83万倍；精简四件套稳健包262.97万倍配对显著跑赢基准。", bold=False),
        BL(),
        T("三、逐笔挤占验尸与静态事后幻觉实证", bold=True),
        T("合体包对现役主仓大牛股几乎零误伤；静态事后对照看似回撤骤降实因偷看全样本删掉单笔大亏。", bold=True, hl=True),
        B("主仓合富中国、艾艾精工、超越科技全保留；盛帮股份亦完好，新规则零误伤主仓牛股。", bold=False),
        B("全包合体仅挤掉一笔轻微盈利的万邦医药(+2.47%)；其余删减多为二进三与撬板自身避开的大亏坑。", bold=False),
        B("典型排雷如2024年2月5日撬板登云股份(-19.23%)；高标冷清删减则精准剔除张江高科(-2.91%)。", bold=False),
        B("静态事后删因子对照回撤看似由47.58%降至31.12%；逐笔核查抓出它删了2025年初的友好集团。", bold=False),
        B("该笔友好集团实亏-23.90%且正逢组合最大回撤期；任何严格按时间前推的因果模型均不可能提前看见。", bold=False),
        BL(),
        T("四、冷血红队四道硬检验与影子执行纪律", bold=True),
        T("2024年底物理截断前后全部零误差且24组邻域全胜基准；唯一过关门槛卡在8127次累计多重检验。", bold=True, hl=True),
        B("2024年底物理截断复算四套核心包167至170笔交割；前后打分误差0.0且收益率误差0.0。", bold=False),
        B("全包24组邻域参数中位256.7万倍，最弱邻域103.3万倍仍胜基准；24组参数100%全面跑赢现役V20.0。", bold=False),
        B("全局交叉过拟合率0.511，但稳健包极稳；其样本内夺冠切分落入后半段仅占0.03%。", bold=False),
        B("按全系统从零出发标准，稳健包与现役基准过关概率均逼近1.0；若以现役夏普4.624为底座仅0.6%。", bold=False),
        B("下季执行：实盘严守现役V20.0一行不改；影子账本同步跟踪精简稳健包一个季度。", bold=False),
        BL(),
        BL(),
        BL(),
    ]

    t1_rows = [
        [C("合体总包(30bps)", True), C("样本外净值与夏普", True), C("去前五与80bps滑点", True), C("26下与两亿过滤", True)],
        [C("现役V20.0基准"), C("53.43万倍 / 4.624"), C("1.90万倍 / 18.87万倍"), C("2.69倍 / 43.79万倍")],
        [C("仅20cm三路均值"), C("134.07万倍 / 4.855"), C("4.78万倍 / 46.18万倍"), C("3.75倍 / 69.34万倍")],
        [C("仅改其余五策略"), C("143.53万倍 / 5.132"), C("5.12万倍 / 53.04万倍"), C("3.17倍 / 未另测")],
        [C("仅20cm半融合"), C("152.86万倍 / 4.873"), C("5.45万倍 / 51.86万倍"), C("3.74倍 / 74.08万倍")],
        [C("精简四件套稳健"), C("262.97万倍 / 5.175"), C("9.38万倍 / 93.35万倍"), C("3.70倍 / 148.5万倍")],
        [C("精简五件套进攻"), C("318.83万倍 / 5.220"), C("11.37万倍 / 111.5万倍"), C("3.69倍 / 158.7万倍")],
        [C("全包合体稳健"), C("319.79万倍 / 5.333"), C("11.40万倍 / 115.2万倍"), C("3.74倍 / 173.7万倍")],
        [C("全包合体进攻"), C("323.95万倍 / 5.323"), C("11.55万倍 / 114.4万倍"), C("3.85倍 / 161.2万倍")],
    ]

    t2_rows = [
        [C("拆解模块", True), C("因果归属", True), C("留一净值乘数与夏普", True), C("诊断定性", True)],
        [C("20cm三路均值"), C("严格因果前推"), C("2.23倍 / +0.201"), C("第一核心增量引擎")],
        [C("三进四4因子排雷"), C("严格因果前推"), C("1.45倍 / +0.214"), C("显著降噪主力功臣")],
        [C("高标冷清删拖油瓶"), C("严格因果前推"), C("1.26倍 / +0.070"), C("避开张江高科让仓位")],
        [C("撬板冷清跳过"), C("纯物理环境过滤"), C("1.19倍 / +0.052"), C("避登云股份(-19.2%)")],
        [C("二进三冷清两两组合"), C("严格因果前推"), C("1.08倍 / +0.053"), C("稳定小幅正增厚")],
        [C("弱红早盘换仓"), C("严格因果前推"), C("1.00倍 / +0.000"), C("样本外0次触发剔除")],
        [C("一进二预约挂单"), C("严格因果前推"), C("1.03倍 (纯触发0.89倍)"), C("靠单次未成交撞大运")],
        [C("一进二模型升级"), C("无有效因果备选"), C("0项入选 (0.00%增量)"), C("维持现役V20.0原版")],
    ]

    t3_rows = [
        [C("红队核查维度", True), C("稳健合体/四件套", True), C("进攻合体/五件套", True), C("最终裁决", True)],
        [C("2024年底物理截断"), C("167笔 0.0分/收差"), C("170笔 0.0分/收差"), C("100%零未来信息")],
        [C("去银行家舍入冲击"), C("318.9万倍 (-0.3%)"), C("259.7万倍 (-19.8%)"), C("稳健包极抗舍入")],
        [C("24组邻域高原"), C("103至356万(24/24胜)"), C("中位256.7万倍"), C("非单点脆弱孤岛")],
        [C("8127次增量概率"), C("相对V20仅0.63%"), C("相对V20仅0.61%"), C("暂不足升实盘理由")],
        [C("最大回撤真实底线"), C("47.58% (零虚降)"), C("47.58% (零虚降)"), C("静态31%系偷看幻觉")],
    ]

    sections_tables = [
        ("表1：各总包合体联测全滑点与成交深度对照", t1_rows, chart1_path),
        ("表2：留一法逐模块贡献与假信号诊断明细", t2_rows, chart2_path),
        ("表3：冷血红队物理截断与多重检验终审表", t3_rows, None),
    ]

    return {
        "title": TITLE,
        "blocks": blocks,
        "tables": [(ttl, rows) for ttl, rows in [(t[0], t[1]) for t in sections_tables]],
        "sections_tables": sections_tables,
        "img_path": chart1_path,
        "img_path2": chart2_path,
    }


def validate_payload_strict(payload: dict, s6_mod, s9_mod) -> None:
    """Run local dry-run validation covering step6, step9, sentence len, and RD036 jargon ban."""
    s9_mod.check_first_sentence_rule(payload)
    long_sents = s9_mod.audit_doc_strict_v191(payload, require_img=True)
    if long_sents:
        raise ValueError(f"存在超40字长句({len(long_sents)}条): {long_sents}")

    all_strs = [("title", payload["title"])]
    for idx, b in enumerate(payload["blocks"]):
        els = b.get("text", b.get("bullet", b.get("ordered", {}))).get("elements", [])
        txt = "".join(e["text_run"]["content"] for e in els)
        all_strs.append((f"block_{idx+1}", txt))
        if "、" in txt:
            continue
        for sent in re.split(r"[。；]", txt):
            s_c = sent.strip()
            if s_c and len(s_c) < 15:
                raise ValueError(f"[过短句检查 block_{idx+1}] ({len(s_c)}字): {s_c}")

    for t_ttl, t_rows in payload["tables"]:
        all_strs.append((f"table_title:{t_ttl}", t_ttl))
        if len(t_rows[0]) > 4:
            raise ValueError(f"表格超4列: {t_ttl}")
        for r_i, row in enumerate(t_rows):
            for c_i, cell in enumerate(row):
                ct = "".join(txt for txt, _ in cell)
                if len(ct) > 32:
                    raise ValueError(f"单元格超32字 [{t_ttl}][{r_i},{c_i}]: {ct} ({len(ct)})")
                all_strs.append((f"{t_ttl}[{r_i},{c_i}]", ct))

    for c_i, htxt in enumerate(HUB_ROW):
        all_strs.append((f"hub_row_c{c_i}", htxt))
        s9_mod.check_text_punc_and_vars(htxt, f"hub_row_c{c_i}")
        if len(htxt) > 32:
            raise ValueError(f"Hub单元格超32字: {htxt} ({len(htxt)})")

    for loc, txt in all_strs:
        s9_mod.check_text_punc_and_vars(txt, loc)
        for bw in s6_mod.BANNED_WORDS + s6_mod.EXTRA_BANNED_WORDS:
            if bw in txt:
                raise ValueError(f"[{loc}] 命中 step6 禁用词 '{bw}': {txt}")
        if s6_mod.HUMAN_PROSE_BAD_RE.search(txt):
            raise ValueError(f"[{loc}] 命中 step6 HUMAN_PROSE_BAD_RE: {txt}")
        for tok in RD036_FORBIDDEN_TOKENS:
            if re.fullmatch(r"[A-Za-z0-9\-]+", tok):
                if re.search(rf"(?<![A-Za-z0-9]){re.escape(tok)}(?![A-Za-z0-9])", txt):
                    raise ValueError(f"[{loc}] 命中禁用缩写 '{tok}': {txt}")
            elif tok in txt:
                raise ValueError(f"[{loc}] 命中禁用词 '{tok}': {txt}")
    print("[DryRun PASS] All strict checks passed with 0 long sentences, 0 short body sentences, 0 jargon, 0 banned punc!")
