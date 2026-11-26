#!/opt/homebrew/bin/python3.13
"""Pure plain-Chinese Feishu payload builder for RD036 master audit report."""

import re

TITLE = "高阶三四因子协同实证"
HUB_ROW = [
    "高阶三四因子协同实证",
    "2023至2026 六策略1073次",
    "20cm半融合与三路均值入影子，余五策略0过关",
    "守死V20，影子盯20cm一季",
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


def build_rd036_payload(chart1_path: str, chart2_path: str) -> dict:
    """Build pure plain-Chinese payload strictly audited for RD036."""
    blocks = [
        MIXED([
            ("结论：高阶三因子半融合与三路均值对20cm冷清日有用，正式纳入影子账本观察一季。", True, True),
            ("冷清三层浅树因单点尖峰且挤占合富中国遭毙杀；其余五大策略525项验证全没用。", False, False),
        ]),
        BL(),
        T("一、总结论与最终定级", bold=True),
        B("联动前轮6945次与本轮548次试错，共计7493次校正；全部方案无一达到直接升级实盘门槛。", bold=False),
        B("冷清半融合146.36倍与三路均值125.96倍获第二档；两项均纳入影子账本跟踪观察一季。", bold=False),
        B("两套备选合体单仓分别达174.3万倍与153.3万倍；显著跑赢80分原版97.1万倍。", bold=False),
        B("为何暂不上实盘：按7493次保守方差校正，两者防撞大运概率仅0.15与0.13。", bold=False),
        B("冷清三层浅树107.88倍遭第四档毙杀；合体时误挤占合富中国，反输80分原版。", bold=False),
        B("其余一进二等五大策略共测525组新变体；跨模块严格防伪检验最终0组通过。", bold=False),
        B("其余五大策略全数维持V20.0原版；严禁拿未过关交互项或深树规则改动线上版本。", bold=False),
        BL(),
        T("二、20cm高阶协同逐笔验尸与高原真相", bold=True),
        T("冷清半融合在80分门槛16组全胜原版；中位净值92.07倍且合体单仓实增近八成。", bold=True, hl=True),
        B("逐笔防伪全干净，五大样本均无买入当日戴帽股；同样零一字涨停板与零未满10日次新。", bold=False),
        B("成交深度扎实：半融合135笔中133笔成交超2亿；三路均值129笔中127笔超2亿。", bold=False),
        B("剔除两亿以下成交后，半融合仍有74.00倍；三路均值75.44倍，远胜原版28.70倍。", bold=False),
        B("对大牛股的收益依赖度出现显著下降；前五牛股对数收益占比由46.22%降至30.20%。", bold=False),
        B("剔除前五牛股后半融合仍有32.47倍；叠加80bps重滑点也有74.24倍，原版仅9.85倍。", bold=False),
        B("四舍五入真相：关闭银行家舍入后半融合降至104.13倍；改标准进位制则为112.33倍。", bold=False),
        B("三路均值极抗舍入扰动，无舍入仍达111.88倍；最大回撤26.08%最低且胜率61.24%最高。", bold=False),
        B("半融合合体单仓增益84.6%来自20cm真增量；三路均值对五大主板及撬板实现零挤占。", bold=False),
        B("浅树3层毙杀实证：合体92.4万倍反输80分原版；邻近参数净值直接跌至48至61倍。", bold=False),
        BL(),
        T("三、最硬三因子人话规则与四因子过拟合教训", bold=True),
        T("高阶三因子交互在当前样本下已触及统计上限；强推四因子与四层深树只会背下偶然规律。", bold=True, hl=True),
        B("正向第一硬规律要求三年放量叠加次新股；并在非温和涨停日逆势挑选冷清题材。", bold=False),
        B("上述正向三因子最新一期样本共录得49笔；胜率高达73.47%且均收+5.31%，协同强度2.51倍。", bold=False),
        B("跨月最稳正向三因子为非周一加外盘高波动；再叠加非温和逆转，47个月现身12个月。", bold=False),
        B("避雷第一组合：上市老股 + 近5日换手剧增；再叠加同题材10cm前排已一字涨停。", bold=False),
        B("该避雷组合样本66笔，胜率仅25.76%；单笔均收-3.45%且单笔重损占比达24.24%。", bold=False),
        B("另一高频避雷在银行强且近60日少涨停时触发；再叠同题材10cm大高开后胜率仅28.70%。", bold=False),
        B("四因子失效根因：切片缩水至24至25笔样本；4层树垫底过拟合概率由27.4%翻至55.6%。", bold=False),
        B("四层深树上线样本外后随即出现显著坍塌；浅树由3层加到4层，净值由107.88倍腰斩至60.49倍。", bold=False),
        BL(),
        T("四、其余五大策略冷暖环境画像与上限实证", bold=True),
        T("其余五大策略均已逼近现有公开量价信息上限；继续守死现行V20原版才是理性最优选。", bold=True, hl=True),
        B("一进二偏好活跃日：50分位以上33笔37.83倍，冷清日3.26倍；113组全输123.47倍原版。", bold=False),
        B("二进三偏好冷清日，冷清日35笔13.42倍胜54.3%；活跃日仅2.76倍，硬套浅树垫底71%。", bold=False),
        B("三进四冷暖双栖：冷清19.48倍、活跃12.28倍；新组虽达277倍但无显著且防撞0.29。", bold=False),
        B("高标首阴仅31笔且撬板仅10笔且仅活跃日成单；双方均无统计学改造空间，守死V20原版。", bold=False),
        BL(),
        BL(),
        BL(),
    ]

    t1_rows = [
        [C("策略简称", True), C("试错与最高表现", True), C("关键防伪破绽", True), C("最终定级", True)],
        [C("20cm半融合"), C("146.36倍 胜59.3%"), C("全局防撞0.15 无舍入104倍"), C("二档影子观察一季")],
        [C("20cm三路均值"), C("125.96倍 回撤26.1%"), C("全局防撞0.13 配对检验边缘"), C("二档备选影子一季")],
        [C("20cm浅树3层"), C("107.88倍 单策略"), C("合体92.4万倍反输且d8尖峰"), C("四档直接毙杀")],
        [C("一进二"), C("113组 0通过 原123.5倍"), C("偏活跃日 原版已难超越"), C("维持V20原版")],
        [C("二进三"), C("105组 0通过 原37.0倍"), C("偏冷清日 新树垫底概率71%"), C("维持V20原版")],
        [C("三进四/高标/撬板"), C("307组全0通过"), C("样本薄或无增量 概率<=0.29"), C("维持V20原版")],
    ]

    t2_rows = [
        [C("方案名称", True), C("全样本/胜率/回撤", True), C("去前五与80bps滑点", True), C("合体单仓与增量来源", True)],
        [C("82分现行原版"), C("21.45倍 54.2% 30.3%"), C("5.20倍 / 11.73倍"), C("53.4万倍 基准参考")],
        [C("80分降门槛原版"), C("44.42倍 55.0% 31.6%"), C("9.85倍 / 22.99倍"), C("97.1万倍 降门槛贡献")],
        [C("冷清半融合(二档)"), C("146.36倍 59.3% 31.6%"), C("32.47倍 / 74.24倍"), C("174.3万倍 85%真增量")],
        [C("冷清三路均值(二档)"), C("125.96倍 61.2% 26.1%"), C("27.94倍 / 65.85倍"), C("153.3万倍 0笔挤占")],
        [C("冷清浅树3层(毙杀)"), C("107.88倍 60.4% 31.6%"), C("23.93倍 / 53.63倍"), C("92.4万倍 误挤占合富")],
    ]

    t3_rows = [
        [C("规律类型", True), C("人话触发条件", True), C("样本与盈亏实测", True), C("红队评语", True)],
        [C("正向三因子硬规律"), C("三年放量+次新+非温和逆势"), C("49笔 胜73.5% 均收+5.31%"), C("真实有效核心构件")],
        [C("跨月最稳正向"), C("非周一+外盘波动高+情绪逆转"), C("47个月现身12个月(25.5%)"), C("跨周期稳定性最佳")],
        [C("避雷三因子组合"), C("老股+5日爆量+10cm一字封"), C("66笔 胜25.8% 均收-3.45%"), C("极强负向排雷过滤")],
        [C("四层深树过拟合"), C("20cm加4层树与4因子深切"), C("净值107.9跌至60.5倍"), C("每叶仅25笔 垫底56%")],
    ]

    t4_rows = [
        [C("策略", True), C("原版净值与样本", True), C("冷清日 vs 活跃日", True), C("最高候选与定级", True)],
        [C("一进二"), C("123.47倍 (59笔)"), C("3.26倍 vs 37.83倍"), C("最高62.16倍 守原版")],
        [C("二进三"), C("36.98倍 (66笔)"), C("13.42倍 vs 2.76倍"), C("最高22.13倍 守原版")],
        [C("三进四"), C("239.18倍 (73笔)"), C("19.48倍 vs 12.28倍"), C("277倍无显著 守原版")],
        [C("高标首阴"), C("9.83倍 (31笔)"), C("3.52倍 vs 2.80倍"), C("10.12倍小样本 守原版")],
        [C("撬板"), C("1.49倍 (10笔)"), C("0.95倍 vs 1.56倍"), C("仅10笔 保持原版")],
    ]

    sections_tables = [
        ("表1：六大策略红队终审总定级", t1_rows, None),
        ("表2：20cm核心方案逐笔验尸与合体单仓对照", t2_rows, chart1_path),
        ("表3：20cm最硬三因子人话规律与四层过拟合对照", t3_rows, chart2_path),
        ("表4：其余五大策略525次试错与冷暖画像汇总", t4_rows, None),
    ]

    return {
        "title": TITLE,
        "blocks": blocks,
        "tables": [(ttl, rows) for ttl, rows, _ in sections_tables],
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
        for r_i, row in enumerate(t_rows):
            for c_i, cell in enumerate(row):
                ct = "".join(txt for txt, _ in cell)
                all_strs.append((f"{t_ttl}[{r_i},{c_i}]", ct))

    for c_i, htxt in enumerate(HUB_ROW):
        all_strs.append((f"hub_row_c{c_i}", htxt))
        s9_mod.check_text_punc_and_vars(htxt, f"hub_row_c{c_i}")
        if len(htxt) > 32:
            raise ValueError(f"Hub单元格超32字: {htxt}")

    for loc, txt in all_strs:
        for bw in s6_mod.BANNED_WORDS + s6_mod.EXTRA_BANNED_WORDS:
            if bw in txt:
                raise ValueError(f"[{loc}] 命中 step6 禁用词 '{bw}': {txt}")
        if s6_mod.HUMAN_PROSE_BAD_RE.search(txt):
            raise ValueError(f"[{loc}] 命中 step6 HUMAN_PROSE_BAD_RE: {txt}")
        for tok in RD036_FORBIDDEN_TOKENS:
            if re.fullmatch(r"[A-Za-z0-9\-]+", tok):
                if re.search(rf"(?<![A-Za-z0-9]){re.escape(tok)}(?![A-Za-z0-9])", txt):
                    raise ValueError(f"[{loc}] 命中 RD036 禁用英文缩写 '{tok}': {txt}")
            elif tok in txt:
                raise ValueError(f"[{loc}] 命中 RD036 禁用词 '{tok}': {txt}")
    print("[DryRun PASS] All strict checks passed with 0 long sentences, 0 short body sentences, 0 jargon, 0 banned punc!")
