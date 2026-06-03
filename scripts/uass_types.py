"""UASS v6.0 — 共享类型、常量、评分表。

所有UASS模块从此文件导入共享定义，确保一致性。
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

REPO = Path(__file__).resolve().parent.parent
SCAN_OUTPUT = REPO / "uass_scan_output.json"
MAINLINE_HISTORY = REPO / "data" / "mainline_history.json"

# ── Track B 评分常量 ─────────────────────────────────────────────────────────

D1_SCORES = {"S": 45, "A": 35, "B": 25, "C": 12, "X": 0}
D2_SCORES = {"S": 30, "A": 24, "B": 18, "C": 10, "D": 0}
D3_SCORES = {"龙头": 25, "先手": 20, "跟涨": 12, "补涨": 6, "掉队": 0}
D4_SCORES = {"启动": 20, "主升早": 16, "主升中晚": 8, "高潮分歧": 3, "退潮": 0}

# D5 弹性评分 — 基于K线实际波动性（替代旧的市值代理）
# 三维度: 振幅(6) + 爆发力(5) + 涨停频率(4) = 15分满分
D5_AMPLITUDE_THRESHOLDS = [(8.0, 6), (5.0, 4), (3.0, 2)]   # avg daily amplitude %
D5_EXPLOSION_THRESHOLDS = [(25.0, 5), (15.0, 3), (8.0, 1)]  # max 5d rolling return %
D5_ZT_FREQ_THRESHOLDS = [(3, 4), (2, 3), (1, 2)]            # limit-up days in 20d

GRADE_THRESHOLDS = [
    (120, "S"), (108, "A+"), (95, "A"), (85, "A-"),
    (75, "B+"), (65, "B"), (55, "B-"), (40, "C"), (0, "D"),
]

STAGE_PRIORITY = {
    "启动(首日)": 0,
    "主升早": 1,
    "主升中": 2,
    "高潮/退潮风险": 3,
}

# ── D6 筹码健康标记 ──────────────────────────────────────────────────────────

D6_FLAGS = {
    "EXTREME_RUN":      "⛔ 20日涨幅>60%，翻倍行情末段",
    "HEAVY_RUN":        "⚠️ 20日涨幅>40%，获利盘沉重",
    "VOLUME_CLIMAX":    "⛔ 近5日出现过最大量日+放量>均量2x，冲顶放量",
    "VOL_SHRINK":       "⚠️ 今日成交量<近5日均量50%，买盘衰竭",
    "VOL_PRICE_DIV":    "⚠️ 近5日价格新高但成交量递减30%+，量价背离",
    "PROFIT_TRAPPED":   "⚠️ 20日均价远低于现价(>25%)，获利盘悬顶",
    "MA_OVEREXTEND":    "⛔ 价格远超MA20(>25%)，严重偏离均线",
    "MA_BEARISH":       "⚠️ MA5<MA10<MA20空头排列，趋势向下",
    "MACD_TOP_DIV":     "⛔ 价格新高但MACD柱缩短，顶背离",
    "RSI_EXTREME":      "⚠️ RSI(14)>85，极度超买",
    "STAGNANT_VOL":     "⛔ 高位放量(>2x)但涨幅<2%，放量滞涨=出货",
    "HIGH_SHADOW":      "⚠️ 近3日高位长上影线(>实体2x)，上方抛压重",
    "60D_EXTREME_RUN":  "⛔ 3月涨幅>80%，中期严重过热",
    "60D_HEAVY_RUN":    "⚠️ 3月涨幅>50%，中期涨幅偏高",
    "60D_TOP_RANGE":    "⚠️ 处于60日高低区间顶部(>90%)",
    "MA60_OVEREXTEND":  "⛔ 价格远超MA60(>30%)，中期严重偏离",
    "250D_TOP_RANGE":   "⚠️ 处于年线高低区间顶部(>95%)",
    "MA250_OVEREXTEND": "⛔ 价格远超MA250(>40%)，年线严重偏离",
    "MA250_DEEP_BELOW": "⚠️ 价格深度跌破MA250(>20%)，长期弱势",
    "52W_HIGH_BREAKOUT":"ℹ️ 接近或突破52周高点(距高点<2%)",
    "52W_DEEP_DRAWDOWN":"ℹ️ 距52周高点回撤>40%，深度调整",
    "HEALTHY":          "✓ 全时间框架筹码+技术面健康",
}

# ── 板块→产业链映射 (B→A发散用) ──────────────────────────────────────────────

SUPPLY_CHAIN_MAP = {
    "MLCC": ["被动元件", "电子元件", "MLCC概念", "元件"],
    "MLCC上游": ["覆铜板", "PCB", "离型膜", "载带", "元件"],
    "PCB": ["印制电路板", "覆铜板", "电子元件", "元件"],
    "光通信": ["CPO概念", "光模块", "光芯片", "5G概念", "通信设备"],
    "半导体": ["芯片概念", "半导体", "光刻机", "EDA概念", "半导体及元件"],
    "CVD金刚石": ["超硬材料", "金刚石", "人造钻石"],
    "稀有金属": ["小金属", "稀土永磁", "锗", "钼", "有色金属"],
    "电力设备": ["特高压", "电网设备", "智能电网"],
    "创新药": ["创新药", "CRO概念", "ADC概念", "生物医药", "医药商业", "化学制药", "生物制品"],
    "智能驾驶": ["无人驾驶", "智能座舱", "车联网", "汽车电子", "汽车零部件", "汽车整车"],
    "AI算力": ["算力概念", "AI概念", "服务器", "液冷概念", "通信设备", "计算机设备"],
    "军工": ["国防军工", "航天航空", "军工电子", "航天装备", "军工电子Ⅱ"],
    "电力": ["煤炭开采", "电力设备", "天然气"],
    "煤炭": ["煤化工", "电力"],
    "机器人": ["人形机器人", "机器人概念", "工业机器人", "减速器", "丝杠", "自动化设备", "通用设备"],
    "光伏": ["光伏设备", "太阳能", "光伏组件", "HJT电池", "钙钛矿", "电源设备"],
    "储能": ["储能概念", "液流电池", "钠离子电池", "储能电站"],
    "新能源车": ["新能源汽车", "动力电池", "锂电池", "电动汽车", "充电桩", "汽车零部件", "汽车整车"],
    "医疗器械": ["医疗器械", "体外诊断", "骨科器械", "手术机器人", "高值耗材", "专用设备"],
    "消费电子": ["消费电子", "苹果概念", "折叠屏", "智能穿戴", "TWS耳机", "光学光电子"],
    "低空经济": ["低空经济", "无人机", "eVTOL", "航空发动机", "飞行汽车"],
    "CDMO": ["CDMO概念", "CXO概念", "医药外包", "原料药", "创新药研发", "医药商业", "化学制药", "生物制品"],
    "氟化工": ["氟化工", "含氟材料", "制冷剂", "锂电材料", "氟聚合物"],
    "核能": ["核电", "核能概念", "核废料处理", "小堆核能", "铀矿开采", "电力"],
    "卫星互联网": ["卫星互联网", "卫星导航", "低轨卫星", "北斗导航", "太空经济"],
    "数据要素": ["数据要素", "数字经济", "数据中心", "大数据", "数据安全"],
    "信创": ["信创概念", "国产替代", "国产操作系统", "国产芯片", "鸿蒙概念", "计算机设备", "软件开发"],
    "固态电池": ["固态电池", "全固态电池", "钠电池", "电解质", "新型储能"],
}


# ── StockRecord 类型定义 ─────────────────────────────────────────────────────

class StockRecord(TypedDict, total=False):
    代码: str
    名称: str
    行业: str
    总市值_亿: float
    流通市值_亿: float
    涨跌幅: float
    成交额_亿: float
    封板资金_亿: float
    换手率: float
    连板数: int
    炸板次数: int
    首次封板时间: str
    龙虎榜净买_亿: float
    龙虎榜解读: str
    D1: str
    D1分: int
    D2: str
    D2分: int
    D3: str
    D3分: int
    D4: str
    D4分: int
    D5_弹性: str
    D5分: int
    D5_振幅分: int
    D5_爆发力分: int
    D5_涨停频率分: int
    TB总分: int
    TB总分_raw: int
    TB评级: str
    D6_flags: list
    D6_20d涨幅: float | None
    D6_30d涨幅: float | None
    D6_量比: float | None
    D6_20日均价: float | None
    D6_MA偏离: float | None
    D6_RSI: float | None
    D6_60d涨幅: float | None
    D6_60d位置: float | None
    D6_MA60偏离: float | None
    D6_250d涨幅: float | None
    D6_250d位置: float | None
    D6_52w距高: float | None
    D6_综合位置: float | None
    D6_penalty: int
    veto: bool
    veto_reasons: list
    涨停: bool
    可操作性: str
    数据源: str


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def score_to_grade(total: int) -> str:
    for threshold, grade in GRADE_THRESHOLDS:
        if total >= threshold:
            return grade
    return "D"


def safe_float(val, default: float = 0.0) -> float:
    if val is None or val == "-" or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def mainline_sort_key(item: tuple) -> tuple:
    sec, info = item
    stage = info.get("stage_auto", "")
    priority = STAGE_PRIORITY.get(stage, 99)
    return (priority, -info.get("today_count", 0))
