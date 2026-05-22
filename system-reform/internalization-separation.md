# 内化分离协议

Date: 2026-05-23
Status: Active — enforced from Phase 2 onwards

---

## 原则

A股和美股的研究产出、行为反馈、知识条目完全分开存储和调用。

单个session只能内化本市场的内容。跨市场的通用认知（心理规则、沟通偏好等）标注 `[通用]`，两个系统均可引用，不重复存储。

---

## Memory文件标注规则

### knowledge_research.md

每条知识条目必须以市场前缀开头：

```
[A股] K{编号}. {事实} — {来源}（{日期}）
[US]  K{编号}. {事实} — {来源}（{日期}）
```

Session内化时只写本市场的条目。不存在不带前缀的新条目（存量条目无前缀时补标，下次引用该条目时强制补标）。

### watchlist.md

A股标的和美股标的分开章节，格式：

```markdown
## A股 Watch Universe
| 股票代码 | 名称 | SABCT | Tier | thesis摘要 | 下次催化剂 |
|---------|------|-------|------|-----------|-----------|
...

## 美股 Watch Universe
| Ticker | Name | Grade | Tier | Thesis | Next Catalyst |
|--------|------|-------|------|--------|--------------|
...
```

不在同一表格混排。

### feedback_behavioral.md

每条行为反馈标注适用范围：

- `[A股]` — 仅适用于A股交易/研究session
- `[US]` — 仅适用于美股交易/研究session
- `[通用]` — 心理规则、沟通偏好、数据质量规则，跨市场适用

示例：
```
#282. [A股] T+1限制下，不在收盘前30分钟追入高位股 — 触发场景：A股W1尾盘
#283. [US]  VIX>25时立即cover空头，无24h窗口 — 触发场景：美股W3风控
#284. [通用] 被challenge时先说"让我确认"，找到证据再回答 — 触发场景：任何市场
```

---

## Session内化流程

### A股session结束时

只内化以下内容：
1. A股标的的知识条目 → `knowledge_research.md`，前缀 `[A股]`
2. A股持仓的watchlist更新 → `watchlist.md` A股章节
3. A股交易行为反馈 → `feedback_behavioral.md`，标注 `[A股]`
4. A股公司数据 → `truth/companies/astock/`
5. 跨市场通用认知（如心理铁律被触发）→ 标注 `[通用]`

**不内化**：美股价格、US公司数据、VIX读数、Regime状态

### 美股session结束时

只内化以下内容：
1. 美股标的的知识条目 → `knowledge_research.md`，前缀 `[US]`
2. 美股持仓的watchlist更新 → `watchlist.md` 美股章节
3. 美股交易行为反馈 → `feedback_behavioral.md`，标注 `[US]`
4. 美股公司数据 → `truth/companies/us/`
5. 跨市场通用认知 → 标注 `[通用]`

**不内化**：A股价格、A股公司数据、T+1记录、成交量选股结果

---

## Daily Review分离

`daily-reviews/YYYY-MM-DD.md` 内部结构：

```markdown
# 交易日复盘 YYYY-MM-DD

---

## A股 (W1/W2)

### 持仓状态
...

### 今日操作
...

### 复盘评分
执行质量: /10
选股质量: /10
规则遵守: /10

### 明日计划
...

---

## 美股 (W3/W4)

### 持仓状态
...

### 今日操作
...

### 复盘评分
执行质量: /10
选股质量: /10
规则遵守: /10

### 明日计划
...
```

规则：
- 每个section独立评分，不合并为单一分数
- A股session写A股section，美股session写美股section
- 如当日只有一个市场活跃，另一个section留 `N/A（休市）` 或 `N/A（未交易）`
- 不跨section引用持仓或交易（如A股涨了不写进美股section）

---

## Truth Store分离

### 目录结构

```
~/.claude/nexus/truth/
├── companies/
│   ├── astock/          ← A股公司JSON文件
│   │   ├── 002028.json  ← 思源电气
│   │   └── ...
│   └── us/              ← 美股公司JSON文件
│       ├── GEV.json
│       ├── CEG.json
│       └── ...
├── portfolio/
│   └── positions.json   ← 统一文件，内部有 market 字段区分
├── macro/
│   └── indicators.json  ← 共用（宏观影响两个市场）
└── personal/
    └── career.json      ← 共用
```

### 写入规则

- A股公司数据写 `truth/companies/astock/{ticker}.json`
- 美股公司数据写 `truth/companies/us/{ticker}.json`
- A股session不写 `us/` 目录；美股session不写 `astock/` 目录
- `truth/macro/indicators.json` 两个session均可读写（VIX对美股/A股情绪均有参考）
- `truth/portfolio/positions.json` 两个session均可读写，写入前先读最新版本，只修改本市场的 positions 条目

---

## pending_actions.json 过滤规则

每个条目必须有 `"market"` 字段：`"astock"` / `"us"` / `"both"`

```json
{
  "id": "PA-009",
  "market": "astock",
  "description": "执行思源电气减仓至15%",
  ...
}
```

Session启动时：
- A股session → 只加载 `market: "astock"` 或 `market: "both"` 的条目
- 美股session → 只加载 `market: "us"` 或 `market: "both"` 的条目
- 不处理对方市场的pending actions，即使它们是CRITICAL级别（留给对应市场的session处理）

例外：`market: "both"` 的条目（如"更新portfolio_state.json资产总额"）在任意session均可执行。

---

## 违规检测

以下行为视为内化分离违规，session结束前自我检查：

| 违规 | 检测方法 |
|------|---------|
| A股session写了US公司的truth条目 | 检查本session写入的文件路径是否含 `us/` |
| 美股session写了A股持仓的watchlist条目 | 检查写入的watchlist行是否在A股章节 |
| knowledge条目无市场前缀 | 检查新增条目是否以 `[A股]` / `[US]` 开头 |
| daily-review跨section引用 | 检查A股section是否引用了美股数据，反之亦然 |
| pending_actions处理了另一市场的条目 | 检查processed的PA的market字段 |

发现违规 → 立即修正，不延期到下一session。

---

## 存量数据迁移

Phase 2之前的存量knowledge条目（无前缀）按以下规则补标：

- 条目明确提到A股代码（6位数字）/ 沪深港 / T+1 / 成交量 / 北向资金 → `[A股]`
- 条目明确提到US ticker / VIX / Regime / Fed / SPY / 做空 → `[US]`
- 条目是行为/心理/沟通规则 → `[通用]`
- 无法判断 → 暂标 `[通用]`，下次研究相关标的时再细化

迁移不要求一次性完成。每次session引用存量条目时顺手补标前缀即可。
