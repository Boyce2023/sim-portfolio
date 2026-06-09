# /// script
# requires-python = ">=3.11"
# ///
"""
研究宪法 — 代码级底层规则执行

所有研究/扫描/交易脚本必须import此模块。
违反规则的操作会被BLOCK，不是WARNING。

v1.0 | 2026-06-05
"""

import re
import sys

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §0 A股数据层 — import时自动激活yfinance拦截器
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
try:
    from astock_data_layer import YFinanceCNBlocker  # noqa: F401
except ImportError:
    pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §1 覆盖范围
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MARKET_SCOPE = {
    "sse_main":   {"prefix": "60", "suffix": ".SS", "name": "沪市主板"},
    "szse_main":  {"prefix": "00", "suffix": ".SZ", "name": "深市主板"},
    "chinext":    {"prefix": "30", "suffix": ".SZ", "name": "创业板"},
    "star":       {"prefix": "68", "suffix": ".SS", "name": "科创板"},
    "bse":        {"prefix": ("8", "4"), "suffix": ".BJ", "name": "北交所"},
    "hk_connect": {"prefix": None, "suffix": ".HK", "name": "港股通"},
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §2 数据源层级
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DATA_SOURCES = {
    "primary": {
        "name": "akshare (stock_zh_a_spot_em)",
        "coverage": "5,500+ A股",
        "speed": "3秒全量",
        "use_for": ["实时行情", "全量扫描", "涨停池", "龙虎榜", "北向资金"],
    },
    "secondary": {
        "name": "push2delay.eastmoney.com HTTPS",
        "coverage": "5,857 A股",
        "speed": "30秒(59页)",
        "use_for": ["akshare失败时的备源", "价格验证"],
    },
    "validation": {
        "name": "baostock",
        "coverage": "5,494 (无北交所)",
        "speed": "慢(逐只查询)",
        "use_for": ["T+0日线验证", "行业分类", "财务数据交叉验证"],
    },
    "batch_price": {
        "name": "腾讯 qt.gtimg.cn",
        "coverage": "~4,800",
        "speed": "12秒(900只/次)",
        "use_for": ["批量收盘价查询"],
    },
    "hk": {
        "name": "yfinance (.HK)",
        "coverage": "港股",
        "speed": "中等",
        "use_for": ["港股通价格和基本面"],
    },
}

# 已淘汰的数据源 — 代码中出现这些import就是bug
DEPRECATED_SOURCES = {
    "yfinance_astock": "A股用yfinance已淘汰(慢+无北交所)。用akshare替代。",
    "netease_api": "网易财经API全域502已死。",
    "tushare_free": "tushare免费tier不够用。",
    "bse_official": "北交所官方API全线停用。",
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §3 卖方信息过滤（铁律）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 卖方信息中可用的部分（事实和数据）
SELLSIDE_ALLOWED = [
    "产品出货量/产能/市占率等硬数据",
    "客户名单/合同金额/订单数据",
    "管理层guidance原话（一手来源）",
    "行业格局描述（供应商数量/技术路线/产能分布）",
    "财报已公布的历史数据",
]

# 卖方信息中禁止使用的部分（观点和预测）
SELLSIDE_BLOCKED = [
    "EPS预测/盈利预测（任何forward estimates）",
    "目标价/target price",
    "评级（买入/增持/中性/减持）",
    "卖方观点/看法/判断（'我们认为'/'预计'）",
    "估值模型输出（DCF/SOTP等卖方自建模型结果）",
    "行业增速预测（卖方自己估的）",
]

# 卖方共识规则（废除旧F15）
CONSENSUS_RULE = """
旧规则（已废除）: 15/15卖方看多 = priced in = 排除
新规则: 分析师人头数不决定任何事。判断priced in看：
  1. 股价 vs 供需基本面 — 价格已反映了多少好消息？
  2. 估值 vs 增长 — PEG是否仍有空间？
  3. 持仓结构 — 机构是否已经满配？
卖方全看多只说明thesis没有争议，不说明价格合理。
"""

# 检测reason/thesis中的卖方污染
_SELLSIDE_CONTAMINATION_PATTERNS = [
    r'目标价\s*[¥$\d]',
    r'target\s*(?:price)?\s*[¥$\d]',
    r'(?:卖方|券商|研报|分析师)\s*(?:预测|预计|认为|看好|推荐)',
    r'(?:买入|增持|强烈推荐)\s*评级',
    r'(?:EPS|盈利)\s*预[测期计]',
    r'consensus\s*(?:EPS|estimate|target)',
    r'(?:一致|共识)\s*(?:预期|预测)',
]


def check_sellside_contamination(text: str) -> list[str]:
    """检查文本中是否包含卖方观点污染。返回匹配到的问题列表。"""
    issues = []
    for pattern in _SELLSIDE_CONTAMINATION_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            issues.append(f"卖方污染: '{matches[0]}' (pattern: {pattern})")
    return issues


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §4 估值铁律
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VALUATION_RULES = """
1. PEG唯一: 估值判断用PEG(Fwd PE ÷ 2Y EPS CAGR)，禁止单独用PE判断贵贱。
2. PE 66x但增长70% → PEG<1 → 不算贵。
3. 盈利拐点公司(亏转盈/YoY>200%)用Revenue PEG替代。
4. 任何单一指标不能auto-exclude。
5. 卖方EPS预测不作为PEG计算输入 — 用公司guidance或历史增速外推。
"""


def validate_peg_not_pe(text: str) -> list[str]:
    """检查文本是否用了standalone PE论据（没有配合增长率）。"""
    issues = []
    pe_mentions = re.findall(r'(?:PE|P/E|市盈率)\s*(?:=|为|是|只有|高达|太[高低])?\s*(\d+)', text)
    peg_mentions = re.findall(r'PEG', text, re.IGNORECASE)
    growth_mentions = re.findall(r'(?:增[速长]|CAGR|growth)\s*\d+%?', text, re.IGNORECASE)

    if pe_mentions and not peg_mentions and not growth_mentions:
        issues.append(f"Standalone PE论据(PE={pe_mentions[0]}x)未配合增长率/PEG。违反D8。")
    return issues


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §5 Agent研究Prompt注入模板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AGENT_RESEARCH_RULES = """
## 研究宪法（每个research agent必须遵守）

### 数据源
- A股行情: akshare stock_zh_a_spot_em() 为主源，push2delay为备源
- 港股: yfinance (.HK)
- 覆盖: 沪深主板+创业板+科创板+北交所+港股通，不遗漏任何板块

### 卖方信息过滤
- ✅ 可用: 产品出货量/客户名单/产能数字/管理层原话/行业格局事实
- ⛔ 禁用: 卖方EPS预测/目标价/评级/观点/估值模型输出
- 卖方研报只取事实和硬数据，一切观点和前瞻预测忽略
- "分析师一致看多"不代表priced in，也不代表值得买 — 不是判断依据

### 估值
- PEG唯一: PE必须除以增长率才有意义，禁止"PE Xx太高/太低"
- PEG计算用公司guidance或历史增速，不用卖方预测
- 盈利拐点(亏转盈)用Revenue PEG

### 输出要求
- 每个数字标注来源(公司公告/财报/行业数据)
- 无来源的数字标"估算(无公开来源)"
- 事实和判断明确分层
"""


def get_agent_prompt_prefix() -> str:
    """返回应注入每个research agent prompt开头的规则文本。"""
    return AGENT_RESEARCH_RULES


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §6 建仓reason验证（被execute_trade.py调用）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def validate_trade_reason(reason: str) -> tuple[list[str], list[str]]:
    """
    验证交易reason是否符合研究宪法。
    Returns: (blocks: list[str], warnings: list[str])
    blocks非空时交易应被拦截。
    """
    blocks = []
    warnings = []

    # 卖方污染检查
    sellside_issues = check_sellside_contamination(reason)
    if sellside_issues:
        blocks.extend(sellside_issues)

    # Standalone PE检查
    pe_issues = validate_peg_not_pe(reason)
    if pe_issues:
        warnings.extend(pe_issues)

    return blocks, warnings


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI: 直接运行时打印所有规则
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    print("=" * 60)
    print("  研究宪法 v1.0 — 代码级底层规则")
    print("=" * 60)

    print("\n§1 覆盖范围:")
    for key, info in MARKET_SCOPE.items():
        print(f"  {info['name']}: prefix={info['prefix']}, suffix={info['suffix']}")

    print("\n§2 数据源层级:")
    for tier, info in DATA_SOURCES.items():
        print(f"  [{tier}] {info['name']} — {', '.join(info['use_for'])}")

    print("\n§3 卖方信息过滤:")
    print("  ✅ 可用:")
    for item in SELLSIDE_ALLOWED:
        print(f"    - {item}")
    print("  ⛔ 禁用:")
    for item in SELLSIDE_BLOCKED:
        print(f"    - {item}")

    print(f"\n§4 估值铁律:")
    print(VALUATION_RULES)

    print("\n§5 共识规则:")
    print(CONSENSUS_RULE)

    # Self-test
    print("\n--- Self-test ---")
    test_cases = [
        ("卖方目标价¥250看好", True),
        ("PEG 0.39(Fwd PE 24x÷增长62%),供给约束", False),
        ("分析师一致预测EPS 5.2元", True),
        ("管理层guidance: H1收入+40%", False),
        ("consensus EPS estimate $3.50", True),
    ]
    for text, should_fail in test_cases:
        issues = check_sellside_contamination(text)
        status = "BLOCKED" if issues else "PASS"
        expected = "BLOCKED" if should_fail else "PASS"
        ok = "✓" if status == expected else "✗ WRONG"
        print(f"  {ok} [{status}] {text[:50]}...")
