#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Pure plain-Chinese Feishu payload for RD040 (Falsified Tombstone)."""
import re

TITLE = "卡异动解禁二波实证"
HUB_ROW = [
    "卡异动解禁二波实证",
    "5年1326笔事件",
    "常规全亏，低平开火花近4年去前5剩0.99倍且撞毁V20",
    "禁作独立策略或空仓补位",
]

FORBIDDEN_TOKENS = [
    "WF", "OOS", "IS", "PIT", "BH-FDR", "DSR", "CSCV", "PBO", "MTM",
    "Sharpe", "MDD", "NAV", "PLR", "GBDT", "ANOVA", "Calmar", "LOO", "bps", "KPL",
    "E1a", "E1b", "E2", "E3", "S1", "S7", "t值", "p值", "q值",
    "消融", "门禁", "闭环", "矩阵", "铁证", "重锚", "回灌", "王牌", "天花板",
]

T = lambda txt, bold=False, hl=False: {
    "block_type": 2, "text": {"elements": [{"text_run": {"content": txt, "text_element_style": {**({"bold": True} if bold else {}), **({"background_color": 3} if hl else {})}}}], "style": {"align": 1, "folded": False}},
}
B = lambda txt, bold=False, hl=False: {
    "block_type": 12, "bullet": {"elements": [{"text_run": {"content": txt, "text_element_style": {**({"bold": True} if bold else {}), **({"background_color": 3} if hl else {})}}}], "style": {"align": 1, "folded": False}},
}
MIXED = lambda parts: {
    "block_type": 2, "text": {"elements": [{"text_run": {"content": tx, "text_element_style": {**({"bold": True} if bd else {}), **({"background_color": 3} if h else {})}}} for tx, bd, h in parts], "style": {"align": 1, "folded": False}},
}
BL = lambda: T("")
C = lambda txt, bold=False: [(txt, {"bold": True} if bold else {})]


def build_rd040_payload(c1_path: str, c2_path: str) -> dict:
    blocks = [
        MIXED([
            ("结论：卡异动横盘解禁二波整体没用，五大常规买点及排雷后五年单仓全亏至零头。", True, True),
            ("20套前视打分卡零组过关，唯一低平开火花近四年去极值跌破一倍且撞毁主力V20。", False, False),
        ]),
        BL(),
        T("一、公式校准与全市场五年盲测对比", bold=True),
        B("复现深证A指与上证A指十日偏离口径，停牌期不累入指数收益。", False),
        B("对八个官方公告及标杆样本点位核对，十日偏离最大误差仅 0.0047 个百分点。", False),
        B("九阳股份十月十六日 99.54%，海洋王十月三十日 100.02%，与公告吻合。", False),
        B("严格排除 129 条高偏离风险警示股后，五年共扫出 1326 笔卡异动解禁事件。", False),
        B("四大常规买点在七种卖法下全部亏损，五年单仓净值全压在 0.28x 以下。", False, True),
        B("两步排雷剔除触百红线与毒公告后仅剩 208 笔，五年净值仍全在 0.13x 以下。", False),
        BL(),
        T("二、为什么十月九阳股份能成功，全市场却亏钱", bold=True),
        B("只要收盘冲破 100% 触发严重异动公告，次日直接面临核按钮与停牌风险。", False, True),
        B("海洋王与大业股份十月三十日刚越线即遭公告，下个交易日双双跌停闷杀。", False),
        B("等收盘偏离跌回安全区次日买，或等放量阳线次日追，往往买在高潮兑现末端。", False),
        B("慈文传媒十月二十三日看似解禁放量涨停，次日开盘低开 -5.6% 即封死跌停。", False),
        BL(),
        T("三、唯一低平开火花的红队四刀拆解", bold=True),
        B("唯一赚钱口袋是：昨日未破百、今天滚掉老涨停且竞价在 -4.5% 至 +2.5%。", False, True),
        B("该切片 134 笔按涨停持有至断板五年 12.60x，扣千八滑点仍见 7.47x。", False),
        B("红队第一刀：近四年去前五极值只剩 0.99x，靠海能达单笔 +110.9% 撑场。", False, True),
        B("红队第二刀：2023 年当年实战实亏 -37.4%，全年十三笔胜率仅 30.8%。", False),
        B("红队第三刀：叠前视因子打分不仅无效，精选前三成反而亏成 0.57x。", False),
        B("红队第四刀：塞入现役 V20.0 空仓日后，近半数交易撞车挤掉十七笔主力大单。", False, True),
        B("强行合体把V20.0由61.17万倍压至40.23万倍，拖累 -34.2%。", False),
        BL(),
        T("四、多因子前视打分全部落榜与截断零误差", bold=True),
        B("在二十套严格按时间前推的整数打分模型里，一百五十多档门槛全部无一过关。", False, True),
        B("全池与排雷净池高分精选在 2026 年下半年及千五滑点下均无法稳居一倍以上。", False),
        B("全部核心赛道均通过 2024 年底物理截断检验，打分与收益最大差值均为 0.0。", False),
        B("实操边界明确：此形态只作老仓逢高兑现窗，严禁当成独立买点或空仓补位。", False, True),
        BL(),
        BL(),
        BL(),
    ]

    t1 = [
        [C("盲测买点切片", True), C("样本/胜率", True), C("五年净值/去前5", True), C("近四年/2026年", True)],
        [C("预解禁早盘全池(401笔)"), C("401 / 38.9%"), C("0.28x / 0.03x"), C("0.10x / 0.44x")],
        [C("收盘解禁次早(473笔)"), C("473 / 47.4%"), C("0.02x / 0.01x"), C("0.01x / 0.59x")],
        [C("缩量低平开承接(262笔)"), C("262 / 38.6%"), C("0.16x / 0.03x"), C("0.05x / 0.80x")],
        [C("放量阳线次早(190笔)"), C("190 / 43.1%"), C("0.27x / 0.05x"), C("0.25x / 0.62x")],
        [C("两步排雷净池(208笔)"), C("208 / 36.8%"), C("0.13x / 0.04x"), C("0.24x / 0.69x")],
        [C("预解禁未破百+低平开"), C("134 / 52.9%"), C("12.60x / 2.43x"), C("4.99x / 1.41x")],
        [C("同上(次日收盘卖)"), C("134 / 57.0%"), C("5.35x / 1.94x"), C("1.68x / 1.26x")],
    ]
    t2 = [
        [C("红队拆解与打分维度", True), C("检验条件", True), C("实测表现", True), C("红队裁决", True)],
        [C("低平开连板去前5极值"), C("2023至2026样本外"), C("由4.99x跌至0.99x"), C("依赖海能达极值")],
        [C("低平开2023单年"), C("13笔实战交易"), C("胜率30.8% 实收 -37.4%"), C("熊市大回撤")],
        [C("低平开叠前视打分"), C("精选前30% (17笔)"), C("净值崩至0.57x"), C("打分无法挽救")],
        [C("低平开补V20空仓"), C("严格竞价不抢跑"), C("空仓去前5仅0.45x"), C("拖累V20 -34.2%")],
        [C("全池打分最高档"), C("全样本80分 (14笔)"), C("1.41x 去前5 0.59x"), C("随机置换未过")],
        [C("2024年底物理截断"), C("事件池与打分引擎"), C("最大差值均为 0.0"), C("零未来偷看")],
    ]
    sections_tables = [
        ("表一：卡异动解禁四大买点与低平开切片五年单仓实测（千三费用）", t1, c1_path),
        ("表二：唯一低平开火花红队四刀拆解与多因子前视打分终审", t2, c2_path),
    ]
    return {
        "title": TITLE,
        "blocks": blocks,
        "tables": [(ttl, rows) for ttl, rows, _ in sections_tables],
        "sections_tables": sections_tables,
        "img_path": c1_path,
        "img_path2": c2_path,
    }


def validate_strict(payload: dict, s6, s9):
    s9.check_first_sentence_rule(payload)
    longs = s9.audit_doc_strict_v191(payload, require_img=True)
    if longs:
        raise ValueError(f"长句>40字: {longs}")
    texts = [("title", payload["title"])]
    for i, b in enumerate(payload["blocks"]):
        els = b.get("text", b.get("bullet", {})).get("elements", [])
        txt = "".join(e["text_run"]["content"] for e in els)
        texts.append((f"block_{i+1}", txt))
        for s in re.split(r"[。；]", txt):
            if s.strip() and len(s.strip()) < 15:
                raise ValueError(f"过短句 block_{i+1} ({len(s.strip())}字): {s.strip()}")
    for ttl, rows in payload["tables"]:
        texts.append((ttl, ttl))
        assert len(rows[0]) <= 4
        for r_i, rw in enumerate(rows):
            for c_i, cell in enumerate(rw):
                ct = "".join(t for t, _ in cell)
                assert len(ct) <= 32, f"单元格超32字: {ct}"
                texts.append((f"{ttl}[{r_i},{c_i}]", ct))
    for c_i, ht in enumerate(HUB_ROW):
        assert len(ht) <= 32, f"Hub格超32字: {ht}"
        texts.append((f"hub_{c_i}", ht))
    for loc, txt in texts:
        s9.check_text_punc_and_vars(txt, loc)
        for bw in s6.BANNED_WORDS + s6.EXTRA_BANNED_WORDS:
            if bw in txt:
                raise ValueError(f"[{loc}] 命中禁用词 '{bw}': {txt}")
        if s6.HUMAN_PROSE_BAD_RE.search(txt):
            raise ValueError(f"[{loc}] 命中 HUMAN_PROSE_BAD_RE: {txt}")
        for tok in FORBIDDEN_TOKENS:
            if re.fullmatch(r"[A-Za-z0-9\-]+", tok):
                if re.search(rf"(?<![A-Za-z0-9]){re.escape(tok)}(?![A-Za-z0-9])", txt):
                    raise ValueError(f"[{loc}] 命中禁用缩写 '{tok}': {txt}")
            elif tok in txt:
                raise ValueError(f"[{loc}] 命中禁用词 '{tok}': {txt}")
    print("[DryRun PASS] RD040 payload 100% pure plain-Chinese validated!")
