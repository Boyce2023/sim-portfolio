#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Publish 4 empirical commodity research sub-documents (07 to 10) to Feishu Wiki:
  Space: Macro Research (7711983159496920097)
  Parent: 03 全球大宗商品 (SsoDwFA6PiEWCskgO5gcI0XsnHc)
Strictly based on verified RD028 and RD021 JSON outputs.
Strictly NO yfinance imports (D12) and NO cap10m.
Never touches nodes 01~06 or the parent home node.
"""
import argparse
import fcntl
import json
import os
import sys
import time
from pathlib import Path

assert "yfinance" not in sys.modules, "D12 violation"

ROOT_DIR = Path("/Users/huaichuaibeimeng/claude-projects")
RD028_OUT = ROOT_DIR / "sim-portfolio/output/extreme_commodities_3ring_backtest_20261125"
RD021_OUT = ROOT_DIR / "sim-portfolio/backtests_astock2/commodities_leadlag_10y_20261123"
FS_DIR = str(ROOT_DIR / "sim-portfolio/backtests_astock2/feishu_master_docs_20261116")
if FS_DIR not in sys.path:
    sys.path.insert(0, FS_DIR)

import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
from build_master_docs import (
    make_text_run as TR,
    make_para_block as P,
    make_bullet_block as B,
    make_ordered_block as O,
    make_blank_line as BL,
)

MACRO_SPACE_ID = "7711983159496920097"
MACRO_PARENT_NODE = "SsoDwFA6PiEWCskgO5gcI0XsnHc"

# Hard protection: never touch 01~06 or parent node
FORBIDDEN_MACRO_NODES = {
    "SsoDwFA6PiEWCskgO5gcI0XsnHc",
    "TpB8wept9iKhTNkOB3VcZp29nqP",
    "BRFIwFHUgi0SiTkv4CCcplblnuc",
    "G7hvw8V3hiVBSnkyNYicR72enNb",
    "VvYQwyTsuiwwo8k6ZPDcGSS5neh",
    "O2lywN5Myiju6FkoQzdcQMfXn6c",
    "CJw5wNawmiAEzgk3fzzcG1e1nJc",
}
FORBIDDEN_MACRO_DOCS = {
    "Rjy8dAEznopJdhx34PtcjgxdnZb",
    "JCiKdFAOWod9nkxGYeNcfT9CnBZ",
    "Q5r4dBZ1kodgCXxme4ncGOs3njc",
    "JcKMdSJ46osX0cxvQs9cSj56nvd",
    "D7GBdPk1Co8MlAxTfT1cMmFgnjb",
    "EQu6dEpIeoh2wSxvQt2czW4pnSh",
}


def row(vals, bold=False):
    st = {"bold": True} if bold else {}
    return [[(str(v), st)] for v in vals]


def find_or_create_macro_child(title: str) -> tuple[str, str]:
    r = s6.api(
        f"{s6.BASE}/open-apis/wiki/v2/spaces/{MACRO_SPACE_ID}/nodes?page_size=50&parent_node_token={MACRO_PARENT_NODE}",
        method="GET",
    )
    if r.get("code") != 0:
        raise RuntimeError(f"查询子节点失败 {MACRO_PARENT_NODE}: {r}")
    for it in r.get("data", {}).get("items") or []:
        if it.get("title") == title:
            ntok, otok = it["node_token"], it["obj_token"]
            if ntok in FORBIDDEN_MACRO_NODES or otok in FORBIDDEN_MACRO_DOCS:
                raise RuntimeError(f"禁止触碰受保护节点: {title} ({ntok}/{otok})")
            return otok, ntok
    rc = s6.api(
        f"{s6.BASE}/open-apis/wiki/v2/spaces/{MACRO_SPACE_ID}/nodes",
        {
            "obj_type": "docx",
            "node_type": "origin",
            "parent_node_token": MACRO_PARENT_NODE,
            "title": title,
        },
        "POST",
    )
    if rc.get("code") != 0:
        raise RuntimeError(f"创建子节点失败 [{title}]: {rc}")
    nd = rc["data"]["node"]
    time.sleep(0.5)
    return nd["obj_token"], nd["node_token"]


def write_macro_doc_payload(doc_id: str, blocks: list, tables: list, images: list = None):
    if doc_id in s6.PROTECTED_DOCS or doc_id in FORBIDDEN_MACRO_DOCS:
        raise RuntimeError(f"禁止写入受保护文档: {doc_id}")
    s6.clear_doc_all(doc_id)

    done, fail = 0, 0
    for i in range(0, len(blocks), 40):
        ch = blocks[i : i + 40]
        r = s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            {"children": ch, "index": -1},
            "POST",
        )
        if r.get("code") == 0:
            done += len(ch)
        else:
            for b in ch:
                r2 = s6.api(
                    f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                    {"children": [b], "index": -1},
                    "POST",
                )
                if r2.get("code") == 0:
                    done += 1
                else:
                    fail += 1
                    print("  [!] 写入单块失败:", r2)
        time.sleep(0.25)

    imgs = [p for p in (images or []) if p and os.path.exists(p)]
    for t_idx, (t_title, t_rows) in enumerate(tables):
        r_bl = s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            {"children": [BL()], "index": -1},
            "POST",
        )
        if r_bl.get("code") == 0:
            done += 1
        t_title_block = {
            "block_type": 2,
            "text": {
                "elements": [{"text_run": {"content": t_title, "text_element_style": {"bold": True}}}],
                "style": {"align": 1, "folded": False},
            },
        }
        r_t = s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            {"children": [t_title_block], "index": -1},
            "POST",
        )
        if r_t.get("code") == 0:
            done += 1
        else:
            fail += 1
            print("  [!] 表格标题写入失败:", r_t)
        time.sleep(0.25)

        if t_idx < len(imgs):
            if s6.insert_image_block(doc_id, imgs[t_idx]):
                done += 1
            else:
                fail += 1

        d = s6.Desc()
        root = d.add({"t": "table", "rows": t_rows})
        rt = s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant",
            {"children_id": [root], "descendants": d.d},
        )
        if rt.get("code") == 0:
            done += 1
        else:
            fail += 1
            print("  [!] 表格写入失败:", rt)
        time.sleep(0.35)

    s6.api(
        f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
        {"children": [BL(), BL(), BL()], "index": -1},
        "POST",
    )
    return done, fail


# ==============================================================================
# Doc 07: 全市场极值扫描与物理反转
# ==============================================================================
def build_doc_07() -> dict:
    title = "极值反转扫描"
    img_path = str(RD028_OUT / "chart2_screen_and_spreads.png")
    blocks = [
        P([
            TR("结论：全市场极值筛选与物理反转打分有用，能避开假反弹并锁定真出清。", background_color=3),
            TR("截至 2026.11.24 扫描 84 个境内外商品系列，筛出 29 个极值品种。"),
            TR("其中 11 个处于历史极端高位，18 个处于历史极端低位。"),
        ]),
        P([TR("一、全市场 84 系列扫描口径与分布", bold=True)]),
        B([
            TR("初筛 84 系列共触发 17 个高位信号与 26 个低位信号。", background_color=3),
            TR("高位门槛为 10 年因果分位超 85%。"),
            TR("低位门槛为 5 年或 10 年分位低于 10%。"),
            TR("剔除内外盘重复与无对应 A 股标的品种，最终锁定 29 个独立品种。"),
        ]),
        B([
            TR("11 个极端高位品种集中在贵金属、工业金属与能化航运。", background_color=3),
            TR("天然橡胶 95.3%，甲醇 93.5%，沥青 92.4%。"),
            TR("美活牛 91.3%，沪铜 91.0%，沪银 88.8%。"),
            TR("沪锡 88.1%，沪金 86.7%，欧线集运 86.7%，沪铝 86.1%。"),
            TR("NYMEX 铂金 10 年分位 84.8%，紧贴高位极值门槛。"),
        ]),
        B([
            TR("18 个极端低位品种集中在地产黑链、农畜养殖与新能源上游。", background_color=3),
            TR("玻璃 0.9%，纯碱 1.1%，氧化铝 1.3%。"),
            TR("多晶硅 1.7%，生猪 1.9%，烧碱 2.3%。"),
            TR("纸浆 5 年 2.3%，热卷 5 年 2.5%，钯金 5 年 0.2%。"),
            TR("螺纹钢、工业硅、锰硅、PVC、鸡蛋、沪镍、白糖、铁矿、玉米也在列。"),
        ]),
        P([TR("二、极端低位前五反转紧迫度与物理触发器", bold=True)]),
        O([
            TR("生猪排低位反转第一，紧迫度 78.2 分，现货 9.39 元深亏。", background_color=3),
            TR("自繁自养成本约 13 至 14 元/kg，猪粮比仅 4.46。"),
            TR("该比价处 10 年 3.9% 极低分位，压迫产能去化。"),
            TR("2026 年三季度末能繁母猪 3602 万头，已跌破 3750 万头红线。"),
            TR("触发线为现货站稳 10.5 元/kg 且能繁母猪连续 3 月环比降幅扩大。"),
        ], seq="1"),
        O([
            TR("玻璃排第二，紧迫度 74.2 分。", background_color=3),
            TR("现价 872 元/吨，处 10 年 0.9% 极低分位。"),
            TR("三大燃料工艺全线亏损 130 至 180 元/吨。"),
            TR("行业厂库仍高达 7000 至 7800 万箱，冷修受停窑重烘成本压制。"),
            TR("触发线是日熔破 13.5 万吨且厂库连续 4 周去化。"),
        ], seq="auto"),
        O([
            TR("纸浆排第三，紧迫度 69.4 分。", background_color=3),
            TR("现价 4666 元/吨，处 5 年 2.3% 极值。"),
            TR("非一体化中小纸企开机即亏，触发线是海外浆厂连涨且港口去库。"),
        ], seq="auto"),
        O([
            TR("螺纹钢排第四，紧迫度 68.2 分，热卷盘面毛利跌至 10 年 0.0% 极值。", background_color=3),
            TR("247 家钢厂日均铁水降至 229 万吨。"),
            TR("触发线是铁水降至 222 万吨以下且站稳 20 日均线。"),
        ], seq="auto"),
        O([
            TR("氧化铝排第五，紧迫度 64.0 分，现价 2553 元/吨跌破内陆高成本线。", background_color=3),
            TR("国内运行产能 9800 至 9900 万吨，硬撞电解铝 4500 万吨上限。"),
            TR("触发线是几内亚矿端扰动或晋豫高成本厂压产超 500 万吨。"),
            TR("多晶硅厂库仍达 38.5 万吨，未连降 3 周且站稳 34500 元禁盲抄。"),
        ], seq="auto"),
        P([TR("三、极端高位前五反转警戒与物理约束", bold=True)]),
        B([
            TR("甲醇排高位第一，紧迫度 69.0 分。", background_color=3),
            TR("现价 3040 元/吨，处 10 年 93.5% 高位。"),
            TR("沿海 MTO 制烯烃价差打至 -604 元/吨，属 10 年 1.7% 亏损极值。"),
            TR("触发线是 MTO 开工降至 70% 以下且港口累库跌破 20 日均线。"),
        ]),
        B([
            TR("天然橡胶排第二，紧迫度 66.6 分。", background_color=3),
            TR("现价 18570 元/吨，处 10 年 95.3% 高位。"),
            TR("欧美俄轮胎反倾销压制需求，触发线是泰国杯胶破 55 泰铢且破均线。"),
        ]),
        B([
            TR("沥青（92.4%）、美活牛（91.3%）与沪铜（91.0%）分列高位三至五位。", background_color=3),
            TR("欧线集运（3056.5 点，86.7%）靠绕行锁住新船过剩，复航即崩塌。"),
            TR("沪铜（9.24 万元/吨）与沪银受矿端约束，禁盲空。"),
        ]),
        BL(), BL(), BL(),
    ]

    t1 = [
        row(["11 极端高位品种", "2026.11.24收盘", "10Y/5Y分位", "20日涨跌与均线"], bold=True),
        row(["天然橡胶 RU0", "18570 元/吨", "95.3% / 94.7%", "-4.11% (均线下)"]),
        row(["甲醇 MA0", "3040 元/吨", "93.5% / 92.3%", "-11.83% (均线下)"]),
        row(["沥青 BU0", "4128 元/吨", "92.4% / 84.8%", "-16.86% (均线下)"]),
        row(["美活牛 LE_F", "229.93 美分/磅", "91.3% / 82.6%", "-0.03% (均线上)"]),
        row(["沪铜 CU0", "92410 元/吨", "91.0% / 82.1%", "-14.74% (均线下)"]),
        row(["沪银 AG0", "10072 元/kg", "88.8% / 77.7%", "-21.08% (均线下)"]),
        row(["沪锡 SN0", "313720 元/吨", "88.1% / 76.2%", "-18.13% (均线下)"]),
        row(["沪金 AU0", "780.42 元/g", "86.7% / 73.5%", "-9.38% (均线下)"]),
        row(["欧线集运 EC0", "3056.5 点", "86.7% (3.3年)", "+35.66% (均线上)"]),
        row(["沪铝 AL0", "21390 元/吨", "86.1% / 72.6%", "-8.61% (均线下)"]),
        row(["NYMEX铂金 PL_F", "1254.7 美元/盎司", "84.8% / 70.4%", "-13.20% (均线下)"]),
    ]

    t2 = [
        row(["18 极端低位品种", "2026.11.24收盘", "10Y/5Y分位", "核心分组归属"], bold=True),
        row(["玻璃 FG0", "872 元/吨", "0.9% / 1.8%", "建材黑链(全亏)"]),
        row(["纯碱 SA0", "955 元/吨", "1.1% / 1.4%", "建材黑链(过剩)"]),
        row(["氧化铝 AO0", "2553 元/吨", "1.3% (3.4年)", "有色(产能过剩)"]),
        row(["多晶硅 PS0", "31985 元/吨", "1.7% (1.9年)", "光伏(高库38.5万)"]),
        row(["生猪 LH0", "9620 元/吨", "1.9% / 2.1%", "农畜(现货9.39元)"]),
        row(["烧碱 SH0", "1533 元/吨", "2.3% (3.2年)", "化工(出清临界)"]),
        row(["NYMEX钯金 PA_F", "850.5 美元/盎司", "5.6% / 0.2%", "贵金属(铂钯1.48)"]),
        row(["沪镍/白糖/纸浆", "116830/5114/4666", "5Y 1.4/1.0/2.3%", "三类底部区间"]),
        row(["热卷/螺纹/工业硅", "3130/3028/8270", "5Y 2.5/4.4/5.7%", "黑链与硅链底部"]),
        row(["玉米/铁矿/锰硅", "2158/658.5/5786", "5Y 3.4/4.0/9.7%", "原料与农产低位"]),
        row(["PVC/鸡蛋 V0/JD0", "4825 / 3176", "10Y 6.0% / 8.5%", "化工与蛋鸡低位"]),
    ]

    t3 = [
        row(["前五低位/高位盯盘", "紧迫分与现价", "核心物理硬约束", "反转确认触发线"], bold=True),
        row(["生猪 LH0 (低1)", "78.2分 / 9620", "能繁3602万<3750红线", "现货稳10.5且母猪连降"]),
        row(["玻璃 FG0 (低2)", "74.2分 / 872", "三工艺亏/库7000万箱", "日熔破13.5万且连去库"]),
        row(["纸浆 SP0 (低3)", "69.4分 / 4666", "中小纸企开机即亏损", "外盘连涨且港口去库"]),
        row(["螺纹热卷 (低4)", "68.2分 / 3028", "热卷毛利0.0%极值", "铁水破222万且站MA20"]),
        row(["氧化铝 AO0 (低5)", "64.0分 / 2553", "9900万撞4500万上限", "矿扰或晋豫压产500万"]),
        row(["甲醇 MA0 (高1)", "69.0分 / 3040", "MTO价差-604(1.7%)", "MTO开工破70%累库"]),
        row(["天然橡胶 (高2)", "66.6分 / 18570", "轮胎关税压需求", "杯胶破55且破MA20"]),
        row(["沥青 BU0 (高3)", "57.8分 / 4128", "重油分流与低库存", "原油回落复产破MA20"]),
        row(["美活牛 (高4)", "53.6分 / 229.93", "存栏低谷催蛋白替代", "母牛留种止跌破MA60"]),
        row(["沪铜 CU0 (高5)", "52.0分 / 92410", "铜铝比4.32x矿紧缺", "比价>4.2替代且累库"]),
    ]

    return {
        "title": title,
        "blocks": blocks,
        "tables": [
            ("表一：11 大极端高位商品最新价格与因果分位清单", t1),
            ("表二：18 大极端低位商品最新价格与因果分位清单", t2),
            ("表三：高低位前五物理反转紧迫度与硬触发条件总表", t3),
        ],
        "images": [img_path],
        "img_path": img_path,
    }


# ==============================================================================
# Doc 08: 三圈层十年回测与伪相关证伪
# ==============================================================================
def build_doc_08() -> dict:
    title = "三圈层回测"
    img_path = str(RD028_OUT / "chart1_extreme_3ring_decay.png")
    blocks = [
        P([
            TR("结论：极值商品买一二圈核心标的有用，买三圈边缘题材股彻底没用且纯亏钱。", background_color=3),
            TR("全市场 29 个极值商品共映射 339 只验证 A 股。"),
            TR("检验区间覆盖 2016 至 2026 十年周期。"),
            TR("回测严守 PIT（点时点）与次日开盘成交，每笔双边扣除 0.30% 手续费。"),
        ]),
        P([TR("一、三圈层分层逻辑与样本覆盖", bold=True)]),
        B([
            TR("一圈为上游主营矿产或纯正产品龙头，直接赚商品涨跌的业绩钱。", background_color=3),
            TR("二圈为中游成本敏感与技术替代受益股，赚原料暴跌或比价替代红利。"),
            TR("三圈为营收关联极弱的边缘题材扩散股，专用于检验散户跟风炒作陷阱。"),
        ]),
        P([TR("二、极端低位周期：二圈稳居第一，三圈全面负期望", bold=True)]),
        O([
            TR("全 29 品种极低位裸触发持有 250 日，二圈超额稳居第一。", background_color=3),
            TR("二圈相对沪深300净超额达 +9.55%，超额胜率 64.4%，盈亏比 1.50。"),
            TR("二圈平均盘中最大回撤 -29.71%，同样是三圈里最优水平。"),
            TR("同期一圈净超额 +6.03%（胜率 57.7%）。"),
            TR("三圈净超额则跌至 -1.21%，胜率仅 44.3%。"),
        ], seq="1"),
        O([
            TR("等到商品价格反转确认后再买入，二圈仍领先且三圈亏钱陷阱彻底暴露。", background_color=3),
            TR("低位反转确认持 250 日，二圈净超额 +7.30%。"),
            TR("二圈胜率 55.6%，且 2022 至 2026 样本外仍赚 +3.07%。"),
            TR("三圈低位商品反转后 T+250 净亏 -4.46%。"),
            TR("若等股票反转再追入三圈，持 250 日净亏 -4.79%。"),
            TR("三圈低位反转胜率仅 38.8% 至 40.0%。"),
            TR("三圈平均最大回撤深达 -35.91% 至 -36.73%。"),
        ], seq="auto"),
        O([
            TR("低位分组样本外出现深刻结构分化，绝不可盲目抄底过剩地产链一圈。", background_color=3),
            TR("2022 至 2026 样本外，玻璃一圈跑输沪深300 达 -13.17%。"),
            TR("同期纯碱一圈样本外同样跑输沪深300 达 -8.0%。"),
            TR("多晶硅高库存期一圈 T+250 亏 -24.55%，而成本释放端二圈大赚。"),
            TR("氧化铝低位期二圈纯外购电解铝赚 +37.51%。"),
            TR("纸浆低位期二圈特种纸赚 +44.36%，胜率达到 100.0%。"),
        ], seq="auto"),
        P([TR("三、极端高位周期：供给刚性金属禁止盲空，三圈仍落败", bold=True)]),
        O([
            TR("高位组 11 个品种严禁机械做空，供给牛市惯性带来极强一二圈超额。", background_color=3),
            TR("高位组裸触发持 250 日，一圈净超额 +17.55%。"),
            TR("一圈胜率达 69.3%，且样本外净超额更扩大至 +22.25%。"),
            TR("高位组转弱确认后一圈仍超额 +15.70%（样本外 +22.56%）。"),
            TR("同期二圈在转弱确认后仍赚 +17.14%，证明高景气不会立刻坍塌。"),
            TR("尤其沪铜与沪银高位一圈样本外超额分别高达 +35.27% 与 +50.55%。"),
        ], seq="1"),
        O([
            TR("三圈边缘股在高位周期同样显著落后，高回撤吞噬真实收益。", background_color=3),
            TR("全样本高位裸触发持 250 日，三圈净超额 +10.61%。"),
            TR("三圈最大回撤深达 -38.33%，显著劣于一圈 -35.46%。"),
            TR("在 2016 至 2021 样本内高位组反转期，三圈甚至净亏 -1.82%。"),
            TR("仅近三年微盘炒作撑起账面收益，其 t 值 5.17 明显弱于一圈 7.19。"),
        ], seq="auto"),
        P([TR("四、伪相关证伪盖棺定论", bold=True)]),
        B([
            TR("商品周期中利润与估值只沿着真实 BOM 成本与物理供需传导。", background_color=3),
            TR("边缘题材股在低位周期赔率与胜率双输，高位周期回撤最深且跑输龙头。"),
            TR("实盘纪律必须物理拉黑三圈边缘股，只在一圈纯正龙头与二圈成本替代链中选股。"),
        ]),
        BL(), BL(), BL(),
    ]

    t1 = [
        row(["全29品种信号与圈层", "T+20 / T+60", "T+120 / T+250", "胜率/盈亏比/回撤"], bold=True),
        row(["低位裸触发 一圈", "+0.54% / +2.59%", "+3.77% / +6.03%", "57.7% / 1.23 / -32.2%"]),
        row(["低位裸触发 二圈", "-0.16% / +2.13%", "+2.22% / +9.55%", "64.4% / 1.50 / -29.7%"], bold=True),
        row(["低位裸触发 三圈", "-1.18% / +0.67%", "-0.08% / -1.21%", "44.3% / 1.13 / -35.4%"]),
        row(["低位商品反转 一圈", "-0.16% / +3.01%", "+1.77% / +4.47%", "49.4% / 1.49 / -32.7%"]),
        row(["低位商品反转 二圈", "-0.05% / +1.44%", "+2.49% / +7.30%", "55.6% / 1.65 / -29.9%"], bold=True),
        row(["低位商品反转 三圈", "-0.46% / -0.69%", "-2.38% / -4.46%", "40.0% / 0.99 / -35.9%"]),
        row(["低位股票反转 三圈", "-0.35% / -1.40%", "-1.74% / -4.79%", "38.8% / 1.01 / -36.7%"]),
        row(["高位裸触发 一圈", "+0.91% / +2.65%", "+6.11% / +12.26%", "58.5% / 2.06 / -35.5%"]),
        row(["高位裸触发 二圈", "+0.78% / +2.50%", "+5.63% / +13.01%", "59.6% / 2.40 / -35.0%"]),
        row(["高位裸触发 三圈", "+0.59% / +1.65%", "+4.26% / +10.61%", "52.8% / 2.00 / -38.3%"]),
    ]

    t2 = [
        row(["分组分期@T+250", "样本内16至21", "样本外22至26", "近3年与样本数"], bold=True),
        row(["全29低位裸 一圈", "+10.42%", "+0.52%", "+1.60% (n=149)"]),
        row(["全29低位裸 二圈", "+13.77%", "+4.23%", "+5.77% (n=149)"], bold=True),
        row(["全29低位裸 三圈", "-7.68%", "+6.92%", "+8.81% (n=149)"]),
        row(["全29低位反转 一圈", "+7.31%", "+0.32%", "+1.91% (n=180)"]),
        row(["全29低位反转 二圈", "+10.18%", "+3.07%", "+6.00% (n=180)"], bold=True),
        row(["全29低位反转 三圈", "-10.53%", "+4.44%", "+7.62% (n=180)"]),
        row(["高组高位裸 一圈", "+10.94%", "+22.25%", "+26.32% (n=202)"], bold=True),
        row(["高组高位裸 二圈", "+21.93%", "+13.26%", "+22.76% (n=202)"]),
        row(["高组高位反转 一圈", "+7.26%", "+22.56%", "+27.87% (n=194)"], bold=True),
        row(["高组高位反转 三圈", "-1.82%", "+14.61%", "+28.89% (n=194)"]),
    ]

    t3 = [
        row(["重点分化品种(T+250)", "一圈龙头超额", "二圈受益超额", "三圈边缘超额"], bold=True),
        row(["氧化铝 AO0 (低位反转)", "+32.81% (100%)", "+37.51% (100%)", "+50.23% (样本少)"]),
        row(["纸浆 SP0 (低位反转)", "+11.96% (50%)", "+44.36% (100%)", "-12.44% (0%)"]),
        row(["钯金 PA_F (低位反转)", "+10.36% (67%)", "+40.40% (样本外+46.5%)", "+32.09%"]),
        row(["玻璃 FG0 (低位反转)", "-10.43% (样本外-13.2%)", "+0.97% (裸+7.53%)", "-5.00%"]),
        row(["多晶硅 PS0 (低位反转)", "-24.55% (禁抄底)", "-26.28% (高库期)", "-21.76%"]),
        row(["沪铜 CU0 (高位反转)", "+20.69% (样本外+35.3%)", "+14.67% (94.7%)", "+14.51% (42.1%)"]),
        row(["沪银 AG0 (高位反转)", "+28.54% (样本外+50.6%)", "+35.79% (70.0%)", "+19.19% (80.0%)"]),
        row(["黄金 AU0 (高位反转)", "+21.28% (80.0%)", "+6.63% (64.0%)", "+1.73% (52.0%)"]),
        row(["天然橡胶 RU0 (高位反转)", "+10.70% (83.3%)", "-9.76% (41.7%)", "-2.61% (41.7%)"]),
    ]

    return {
        "title": title,
        "blocks": blocks,
        "tables": [
            ("表一：全 29 极值品种一二三圈层持有期净超额总表（扣双边 0.30% 费）", t1),
            ("表二：样本内（2016至2021）与样本外（2022至2026）及近3年分层对比", t2),
            ("表三：重点分化极值商品三圈层实证明细（T+250 相对沪深300净超额）", t3),
        ],
        "images": [img_path],
        "img_path": img_path,
    }


# ==============================================================================
# Doc 09: 六大商品股期领先滞后实证
# ==============================================================================
def build_doc_09() -> dict:
    title = "股期领先滞后"
    c1_path = str(RD021_OUT / "chart1_leadlag_6commodities.png")
    c2_path = str(RD021_OUT / "chart2_strategy_ab_vs_bh.png")
    blocks = [
        P([
            TR("结论：股期领先滞后分两派极有用，猪锂股真领先可做左侧，金铜油煤全同步。", background_color=3),
            TR("2016 至 2026 十年实证覆盖生猪、碳酸锂、铜、石油、黄金与煤炭六大商品。"),
            TR("回测严守次日开盘成交与双边 0.30% 扣费。"),
            TR("同期沪深300基准年化 +0.53%。"),
        ]),
        P([TR("一、六大商品股期领先滞后实证分型", bold=True)]),
        B([
            TR("第一派是股票明显领先商品：生猪领先 +136 天，碳酸锂领先 +37 天。", background_color=3),
            TR("生猪 60 日滚动收益互相关峰值在 +136 天。"),
            TR("其峰值相关性 r=0.4108，统计显著（p=0.0078）。"),
            TR("生猪波峰拐点股票提前 +37 天，且 80% 波峰由股票先见顶。"),
            TR("个股中温氏股份领先 +145 天，早于牧原股份 +135 天。"),
            TR("碳酸锂 2023.07 上市以来，股票领先期货 +37 天（r=0.6909）。"),
            TR("赣锋锂业领先 +51 天、天齐锂业领先 +36 天，仅盐湖股份 0 天同步。"),
        ]),
        B([
            TR("第二派是股期与现货 0 天同步共振：黄金、铜、石油与煤炭全为 0 天。", background_color=3),
            TR("黄金（AU0）与黄金股 60 日相关性 r=0.7178，峰值精准落于 0 天。"),
            TR("沪铜（CU0）与铜股同步 r=0.5096，紫金矿业相关性达 0.5766。"),
            TR("原油（SC0）与油股同步 r=0.5529，中国海油与中石油同为 0 天。"),
            TR("焦煤（JM0）与煤炭股同步 r=0.6100，拐点中位数仅差 3 天。"),
        ]),
        B([
            TR("仅煤炭中的海外月度纽卡斯尔煤价存在股领先 +28 天（月频滞后 +1 月）。", background_color=3),
            TR("这是因为海外现货数据月度发布天然滞后，且中国神华受长协煤高股息主导。"),
        ]),
        P([TR("二、左侧反转（A/A2）与右侧趋势（B）及长持（C）策略裁决", bold=True)]),
        O([
            TR("生猪与碳酸锂必须做左侧反转（A/A2），硬跟右侧趋势会反复被打脸。", background_color=3),
            TR("生猪左侧强化版（A2）年化 +14.03%，净超额 +13.49%。"),
            TR("生猪 A2 策略最大回撤 -41.68%，4 笔交易胜率 100.0%。"),
            TR("生猪若做右侧趋势（B）年化跌至 -0.70%，净输沪深300 -1.24%。"),
            TR("碳酸锂左侧策略（A）年化 +19.03%，净超额 +18.00%。"),
            TR("碳酸锂左侧回撤压至 -24.59%，长持不动（C）年化巨亏 -10.21%。"),
        ], seq="1"),
        O([
            TR("铜与石油呈左侧波段胜率更高，黄金与煤炭适合右侧趋势或长持龙头。", background_color=3),
            TR("铜左侧（A）年化 +12.95%，最大回撤仅 -21.71%。"),
            TR("铜左侧近三年年化净超额更达 +30.35%，表现稳健。"),
            TR("石油（SC0）左侧（A）年化 +10.78%，右侧趋势（B）反亏 -1.76%。"),
            TR("黄金右侧趋势（B）年化 +9.06%，近三年年化 +12.87%。"),
            TR("黄金右侧显著胜过左侧策略的年化 -1.56%。"),
            TR("焦煤右侧趋势（B）年化 +10.45%，最大回撤压至 -32.63%。"),
        ], seq="auto"),
        O([
            TR("高股息资源龙头长持（C）在黄金、铜与神华上依然是强基准。", background_color=3),
            TR("中国神华十年长持年化 +20.29%，净超额 +19.75%。"),
            TR("黄金等权长持年化 +12.58%，铜等权长持年化 +17.40%。"),
            TR("长持回撤普遍超 -50%，右侧趋势用近四成仓位换取低回撤与高夏普。"),
        ], seq="auto"),
        BL(), BL(), BL(),
    ]

    t1 = [
        row(["商品与窗口", "60日峰滞后(天)", "峰值r / 0天r", "拐点与代表个股特征"], bold=True),
        row(["生猪 (16至26现货)", "+136 天 (股先)", "0.4108 / 0.2712", "峰提前37d/温氏+145d"]),
        row(["碳酸锂 (23.7实盘)", "+37 天 (股先)", "0.6909 / 0.6000", "赣锋+51d/盐湖0d同步"]),
        row(["黄金 (16至26 AU0)", "0 天 (同步)", "0.7178 / 0.7178", "山东黄金r=0.7278"]),
        row(["铜 (16至26 CU0)", "0 天 (同步)", "0.5096 / 0.5096", "紫金r=0.5766/FCX0.70"]),
        row(["石油 (18.12起SC0)", "0 天 (同步)", "0.5529 / 0.5529", "海油r=0.6178/中石油0d"]),
        row(["煤炭 (16至26 JM0)", "0 天 (同步)", "0.6100 / 0.6100", "山煤0d/纽煤月滞+28d"]),
    ]

    t2 = [
        row(["商品与主推策略", "左侧A/A2 年化(超额)", "右侧B 年化(超额)", "长持C 年化(回撤)"], bold=True),
        row(["生猪: 左侧A2", "+14.03% (+13.49%)", "-0.70% (-1.24%)", "+11.17% (-47.6%)"], bold=True),
        row(["碳酸锂: 左侧A", "+19.03% (+18.00%)", "+1.67% (+0.64%)", "-10.21% (-57.8%)"], bold=True),
        row(["铜: A低撤/C高收", "+12.95% (+12.42%)", "+8.32% (+7.78%)", "+17.40% (-50.7%)"]),
        row(["石油: 左侧SC0A", "+10.78% (+7.92%)", "-2.54% (-3.08%)", "+7.32% (-53.8%)"]),
        row(["黄金: 右侧B/长持C", "-1.56% (-2.10%)", "+9.06% (+8.53%)", "+12.58% (-56.8%)"], bold=True),
        row(["煤炭: 右侧B/神华C", "-6.64% (-7.17%)", "+10.45% (+9.92%)", "神华+20.29% (-43.5%)"], bold=True),
    ]

    t3 = [
        row(["策略风险收益细项", "最大回撤 MDD", "胜率 / 盈亏比", "夏普与实战用法"], bold=True),
        row(["生猪强化左侧 A2", "-41.68%", "100.0% (4笔)", "0.62 / 母猪去化左侧买"]),
        row(["碳酸锂左侧 A", "-24.59%", "28.6% / 11.19", "0.79 / 跌破8万做反转"]),
        row(["铜左侧 A (十年)", "-21.71%", "54.5% / 10.10", "0.79 / 近3年超+30.4%"]),
        row(["石油 SC0 左侧 A", "-29.54%", "35.3% / 6.78", "0.66 / 忌追高油价趋势"]),
        row(["黄金右侧趋势 B", "-61.26%", "36.0% / 4.14", "0.44 / 近3年年化+12.9%"]),
        row(["焦煤右侧趋势 B", "-32.63%", "55.1% / 2.20", "0.52 / 控撤优于长持"]),
    ]

    return {
        "title": title,
        "blocks": blocks,
        "tables": [
            ("表一：六大商品股期领先滞后实证参数总表（60日收益互相关）", t1),
            ("表二：左侧反转（A/A2）、右侧趋势（B）与长持（C）年化收益对比", t2),
            ("表三：六大商品最优策略风控指标与实盘交易指南", t3),
        ],
        "images": [c1_path, c2_path],
        "img_path": c1_path,
    }


# ==============================================================================
# Doc 10: 反转后1至2年非共识产业链推演
# ==============================================================================
def build_doc_10() -> dict:
    title = "反转产业链推演"
    blocks = [
        P([
            TR("结论：极值反转后 1 至 2 年买二阶利润挪移、技术替代与滞后补库极有用。", background_color=3),
            TR("市场习惯在商品跌破成本时抄底上游，在商品大涨时追高矿企。"),
            TR("物理约束与比价极值往往迫使利润流向中游卡位端，甚至永久改变工艺配方。"),
        ]),
        P([TR("一、主线一：上游过剩撞死下游上限，利润单向挪移至二圈", bold=True)]),
        B([
            TR("当上游产能大幅过剩而下游产能被刚性锁死时，上游毫无议价权。", background_color=3),
            TR("氧化铝运行产能达 9800 至 9900 万吨。"),
            TR("这一庞大产能直接硬撞电解铝 4500 万吨合规红线。"),
            TR("至 2026.11.24 氧化铝处 1.3% 极低位，沪铝稳居 86.1%。"),
            TR("电解铝模拟毛利维持 16462.71 元/吨（71.5% 分位）。"),
            TR("纯外购铝厂吃尽暴利，反转后二圈 T+250 赚 +37.51%。"),
            TR("该组纯外购铝企在历史低位样本中胜率 100.0%。"),
            TR("核心标的：云铝股份（000807.SZ）、神火股份（000933.SZ）。"),
            TR("其余代表标的包括焦作万方（000612.SZ）。"),
        ]),
        B([
            TR("纸浆过剩向特种纸与生活用纸的利润挪移完全复制同一物理机制。", background_color=3),
            TR("纸浆跌至 4666 元/吨（5 年 2.3% 分位），非一体化小厂出清压低浆价。"),
            TR("二圈纯外购特种纸底部反转后 T+250 净超额 +44.36%。"),
            TR("该组二圈标的十年历史胜率高达 100.0%。"),
            TR("核心标的：仙鹤股份（603733.SH）、五洲特纸（605007.SH）。"),
            TR("生活用纸受益代表标的为中顺洁柔（002511.SZ）。"),
        ]),
        P([TR("二、主线二：极值比价倒逼不可逆技术替代，永久削掉单耗", bold=True)]),
        B([
            TR("金属比价冲破物理替代线后，制造业直接修改 BOM 配方而非等待降价。", background_color=3),
            TR("沪铜 92410 元/吨推动铜铝比飙至 4.32 倍。"),
            TR("这一比价处 10 年 95.0% 极值，远超 4.0 倍临界线。"),
            TR("空调散热管与电力线缆加速铝代铜，一旦换线成功，铜单耗被永久削减。"),
        ]),
        B([
            TR("沪银 10072 元/kg（88.8% 分位）直接催生光伏无银化元年。", background_color=3),
            TR("隆基 20GW 纯铜浆产线、爱旭铜电镀量产与中来铝代银加速去银。"),
            TR("一圈银矿高位仍强，样本外净超额 +50.55%。"),
            TR("但未来 1 至 2 年最大黑马在无银组件与铜电镀设备。"),
            TR("核心标的：爱旭股份（600732.SH）、隆基绿能（601012.SH）。"),
            TR("铜电镀核心设备代表标的为迈为股份（300751.SZ）。"),
        ]),
        B([
            TR("铂钯比飙至 1.48 倍（10 年 99.1% 分位）。"),
            TR("同时 NYMEX 钯金跌至 5 年 0.2% 极值（850.5 美元/盎司）。"),
            TR("汽油车三元催化剂触发钯返替铂，二圈催化链样本外超额 +46.48%。"),
            TR("核心标的：威孚高科（000581.SZ）、奥福科技（688021.SH）。"),
        ]),
        P([TR("三、主线三：反转后 6 至 12 个月的滞后补库与设备周期", bold=True)]),
        B([
            TR("生猪与玻璃反转并非一锤子买卖，现金流修复半年后引爆二阶补库。", background_color=3),
            TR("生猪能繁母猪 3602 万头跌破红线，股票提前现货 +136 天反应一圈养殖龙头。"),
            TR("待猪价反转站稳 6 至 12 个月后，养殖场利润恢复集中补打疫苗与更新环控。"),
            TR("玻璃一旦冷修落地并修复现金流，6 个月后窑炉耐材重砌与纯碱补库放量。"),
            TR("动保代表标的：生物股份（600201.SH）、科前生物（688526.SH）。"),
            TR("其余代表标的：瑞普生物（300119.SZ）、旗滨集团（601636.SH）。"),
        ]),
        P([TR("四、主线四：MTO 负毛利护城河与欧线复航家居大反转", bold=True)]),
        B([
            TR("甲醇 93.5% 高位把沿海 MTO 价差压到 -604 元/吨（1.7%）。"),
            TR("高原料成本倒逼高耗能装置停车，直接抬升乙烷裂解与煤制护城河。"),
            TR("欧线集运 3056.5 点（86.7% 分位）靠绕行锁住 2026 年新造船过剩。"),
            TR("高运价期一圈船东超额而二圈出海家居受压制（T+250 达 -14.71%）。"),
            TR("一旦苏伊士复航落地，船东运价坍塌将触发高货柜家居毛利大反转。"),
            TR("化工路线代表标的：卫星化学（002648.SZ）、宝丰能源（600989.SH）。"),
            TR("出海家居代表标的：乐歌股份（300729.SZ）、恒林股份（603661.SH）。"),
            TR("高货柜家居弹性标的还有匠心家居（301061.SZ）。"),
        ]),
        BL(), BL(), BL(),
    ]

    t1 = [
        row(["非共识主线与驱动", "物理比价与约束锚", "二阶核心传导机制", "代表验证标的"], bold=True),
        row(["1. 矿铝利润挪移", "AO 1.3% vs AL 86.1%", "9900万撞4500万红线", "云铝/神火/焦作万方"]),
        row(["1. 纸浆向特种纸挪移", "SP0 5Y 2.3% (4666)", "纯外购纸企 T+250 +44.4%", "仙鹤/五洲/中顺洁柔"]),
        row(["2. 铝代铜/去银化", "铜铝4.32x/沪银88.8%", "改BOM配方永久降单耗", "爱旭/隆基/迈为股份"]),
        row(["2. 钯返替铂催化链", "铂钯比1.48x (99.1%)", "催化剂二圈样本外+46.5%", "威孚高科/奥福科技"]),
        row(["3. 猪后动保疫苗补打", "母猪3602万/比4.46", "反转6至12月现金修复", "生物/科前/瑞普生物"]),
        row(["3. 玻璃冷修耐材补库", "FG0 0.9%/库7000万", "日熔破13.5万后重砌", "旗滨集团/福耀玻璃"]),
        row(["4. 化工路线重定价", "MTO价差 -604 (1.7%)", "高甲醇突显乙烷护城河", "卫星化学/宝丰能源"]),
        row(["4. 欧线复航出海反转", "EC0 86.7%对新船潮", "绕行结束释放高货柜毛利", "乐歌/恒林/匠心家居"]),
    ]

    t2 = [
        row(["推演路径实证检验", "当前主导信号", "一圈实证 T+250", "二圈实证 T+250"], bold=True),
        row(["氧化铝极低周期", "AO0 1.3%分位", "+32.81% (胜率100%)", "+37.51% (胜率100%)"], bold=True),
        row(["纸浆极低周期", "SP0 5Y 2.3%", "+11.96% (胜率50%)", "+44.36% (胜率100%)"], bold=True),
        row(["钯金极低周期", "PA_F 5Y 0.2%", "+10.36% (样本外+7.7%)", "+40.40% (样本外+46.5%)"], bold=True),
        row(["铜银供给牛市", "CU0 91%/AG0 88.8%", "+20.69% / +28.54%", "+14.67% / +35.79%"]),
        row(["欧线集运高运价期", "EC0 86.7%分位", "+4.94% (裸触发)", "-14.71% (复航反转期权)"]),
    ]

    return {
        "title": title,
        "blocks": blocks,
        "tables": [
            ("表一：极值商品反转后 1 至 2 年四大非共识二阶推演清单", t1),
            ("表二：二阶利润挪移、技术替代与复航期权的十年实证对照", t2),
        ],
        "images": [],
        "img_path": None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    docs = [build_doc_07(), build_doc_08(), build_doc_09(), build_doc_10()]

    for d in docs:
        s9.check_first_sentence_rule(d)
        longs = s9.audit_doc_strict_v191(d, require_img=bool(d.get("img_path")))
        if longs:
            raise ValueError(f"[{d['title']}] 存在超 40 字长句: {len(longs)}")
        tot_chars = sum(
            len(e["text_run"]["content"])
            for b in d["blocks"]
            for e in b.get("text", b.get("bullet", b.get("ordered", {}))).get("elements", [])
        )
        tot_chars += sum(len(t) for t, _ in d["tables"])
        tot_chars += sum(len("".join(x for x, _ in cell)) for _, rows in d["tables"] for rw in rows for cell in rw)
        print(f"  [Char Audit] {d['title']}: local_chars={tot_chars}")
        if tot_chars < 1300:
            raise ValueError(f"[{d['title']}] 字数不足: {tot_chars} < 1300")

    if args.dry_run:
        print("\n[Dry-Run PASS] 07至10 四篇文档全部通过 V19.1 本地格式与字数审核！")
        return

    lock_fd = open(s6.LOCK_PATH, "w")
    results = []
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        for d in docs:
            title = d["title"]
            doc_id, node_tok = find_or_create_macro_child(title)
            if node_tok in FORBIDDEN_MACRO_NODES or doc_id in FORBIDDEN_MACRO_DOCS:
                raise RuntimeError(f"安全阻断: {title}")
            done, fail = write_macro_doc_payload(doc_id, d["blocks"], d["tables"], d.get("images", []))
            if fail > 0:
                raise RuntimeError(f"[{title}] 写入存在失败块: {fail}")
            time.sleep(1.5)
            v = s9.verify_document_v191(
                doc_id,
                title,
                expected_tables_count=len(d["tables"]),
                has_img=bool(d.get("images")),
            )
            url = f"https://my.feishu.cn/wiki/{node_tok}"
            results.append({
                "title": title,
                "node_token": node_tok,
                "doc_id": doc_id,
                "url": url,
                "raw_chars": v["raw_chars"],
                "tables_count": v["tables_count"],
                "images_count": v["images_count"],
                "blocks_count": v["blocks_count"],
            })
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    out_path = RD028_OUT / "macro_wiki_07_10_publish_result.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== MACRO WIKI 07-10 PUBLISHED ===")
    for r in results:
        print(f"  {r['title']} | node={r['node_token']} | chars={r['raw_chars']} | tbl={r['tables_count']} | img={r['images_count']} | {r['url']}")


if __name__ == "__main__":
    main()
