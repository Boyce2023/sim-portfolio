# Execution Forcing Mechanisms
## Claude模拟盘强制执行系统 v1.0

> 核心诊断：规则写得比执行快。Day 1-5的失败模式是：
> `写方法论 → 生成建议 → 不执行 → 再写方法论`
> 本文档设计5个机制打断这个循环。

---

## 背景：失败的证据清单

| 违反 | 持续时间 | 规则存在时间 | 执行率 |
|------|---------|------------|--------|
| L18 空头配额=0 | Day 1–Day 5（5天全程） | Day 1起即存在 | 0% |
| L16 散弹枪禁令 | Day 1–Day 5（4/5天） | Day 1起即存在 | 20% |
| v3.0 rebalance建议（卖GOOGL+SRUUF，买FPS+GEV） | 写于Day 3，Day 5仍未完整执行 | 2个交易日 | 50% |
| pending_actions 7条创建 | Day 5全部仍为pending | 从创建起即应执行 | 0% |
| A股前3天30%现金部署规则 | Day 1–Day 4 | strategy.md §3.5 | 0% |

**根因诊断**：系统缺乏强制执行层。现有结构中，pending_actions.json 是一个记录工具，不是一个阻断工具。规则可以被无限期搁置而不产生系统级后果。

---

## 机制一：Pending Action 自动升级系统

### 设计原理

pending_actions.json 中的每条记录增加 `escalation` 字段，记录时间戳、当前级别、升级历史。每次 session 启动时（L17 §4 的检查步骤），`check_pending_escalation()` 函数自动评估并更新所有 pending 条目的升级状态。

### 升级时间线（适用于非 trigger-gated 类型）

```
Day 0: created       — 正常记录，无特殊标记
Day 1: reminder      — 复盘中列出，提醒尚未执行
Day 2: WARNING       — 必须在本session处理，或写明defer_reason（理由不充分则不接受）
Day 3: CRITICAL      — 阻断新建仓：任何新 position 操作被 execute_trade.py 拒绝
Day 5: FORCE         — 自动生成最简合规操作（见下方 auto-force 规则）
```

**trigger-gated 类型例外**：PA-001至PA-005这类"等催化剂落地再执行"的 rebalance，Day 计数从 `trigger_date` 触发后才开始，而非从 `created_at` 开始。

**urgent 类型例外**：PA-007（立即触发类）Day 0 即为 CRITICAL，同 session 必须处理。

### JSON Schema：escalation 字段

每条 pending_actions.json 条目新增以下字段：

```json
{
  "id": "PA-001",
  "...existing fields...": "...",
  "escalation": {
    "clock_start": "2026-05-22T10:00:00+08:00",
    "clock_type": "trigger_gated",
    "trigger_date_actual": null,
    "level": "normal",
    "level_history": [
      {
        "level": "normal",
        "set_at": "2026-05-22T10:00:00+08:00",
        "reason": "created"
      }
    ],
    "defer_log": [],
    "force_action_generated": false,
    "blocks_new_positions": false
  }
}
```

**clock_type 枚举：**
- `"immediate"` — 创建即开始计时（PA-006, PA-007类）
- `"trigger_gated"` — 从 `trigger_date` 后第一个交易日开始计时（PA-001至PA-005类）
- `"weekly"` — 每周固定日期复位（做空扫描SOP类）

**level 枚举：** `"normal"` | `"reminder"` | `"warning"` | `"critical"` | `"force"`

**defer_log 单条结构：**
```json
{
  "deferred_at": "2026-05-23T09:30:00+08:00",
  "deferred_by_session": "cn-morning: 2026-05-23",
  "reason": "ASCO数据未发布，无法执行。下一评估：2026-05-29 ASCO后",
  "accepted": true,
  "next_review_date": "2026-05-29"
}
```

### 阻断逻辑：blocks_new_positions

当任何 pending 条目达到 `"critical"` 或 `"force"` 级别，且 `blocks_new_positions: true` 时：

1. `execute_trade.py` 在执行任何 `buy` 或 `short` 操作前，先调用 `check_pending_blocks()`
2. 如果有阻断项目，打印 CRITICAL 警告并拒绝执行，exit code 2
3. 阻断解除条件：将对应 pending 条目移入 `completed` 数组，或写入有效 `defer_log` 条目

**L18 专项阻断（立即生效）：** PA-007（空头配额修复）已标记 `status: "urgent"`，在当前系统升级后应立即设为 `blocks_new_positions: true`。从今日起，执行任何美股买入/加仓前，必须先确认空头扫描已执行或已写入 `"无空头理由: [具体原因]"` 记录。

### FORCE 级别的自动最简操作

当条目达到 Day 5（`"force"` 级别），系统在当日 `daily_run.sh` 中自动写入 `decisions.json`，生成对应的最简合规动作：

| pending 类型 | FORCE 自动生成 |
|-------------|--------------|
| `short` (L18 空头扫描) | 生成一条 `short MSTR 50股` 建议（取 watchlist_config.json 第一个 short_candidate，最低 $7,500 仓位），写入 decisions.json，标记 `source: "force_escalation"` |
| `rebalance` (散弹枪违规) | 生成 `sell [最弱持仓]` 直至仓位数合规 |
| `rebalance` (sizing 修正) | 生成最小操作：减最大违规持仓至目标上限的 50%，而非直接到目标 |
| `regime_adjustment` | 生成空头扫描 SOP 执行记录模板，要求 agent 填写 |

FORCE 生成的操作不自动执行，agent 仍需人工确认，但：
1. 已写入 decisions.json，session 开始时强制展示
2. 拒绝执行需写入 `force_refused_reason`，否则下一条新 pending 被拒创建

### 集成点

- **check_pending_escalation()** — 添加至 `scripts/risk_monitor.py` 的检查流程，在现有风控检查之前运行
- **check_pending_blocks()** — 添加至 `scripts/execute_trade.py` 的 pre-flight 检查，在价格查询之前运行
- **force_action_generator()** — 添加至 `scripts/decision_engine.py`，在常规 decision logic 之后运行

---

## 机制二：方法论-执行绑定

### 设计原理

当 strategy.md 或任何方法论文档更新版本号（如 v3.0 → v4.0，或写入新的 `##` 级别规则），系统检测到版本变化时，必须同步创建对应执行计划，并写入 pending_actions.json。

**Day 3 的失败案例：** v3.0 写了"卖GOOGL 10股+卖SRUUF 200股，买FPS 100+买GEV 3"，但这条建议仅存在于 research-notes 文档中，从未进入 pending_actions.json，因此在 L17 §4 的 session 检查中完全不可见，就这样被忽视了。

### 执行计划 Schema

每次写入新方法论版本时，必须同步在 pending_actions.json 的 `pending` 数组中创建对应条目，类型为 `"methodology_execution"`：

```json
{
  "id": "PA-008",
  "type": "methodology_execution",
  "methodology_version": "v4.0",
  "methodology_source": "research-notes/system-v4/US_TRADING_SYSTEM_V4.md",
  "name": "v4.0方法论执行计划 — L16/L17/L18实施",
  "execution_items": [
    {
      "item_id": "EX-001",
      "description": "执行v3.0 rebalance: 卖GOOGL 10股 + 卖SRUUF 200股",
      "deadline": "2026-05-26",
      "status": "pending",
      "blocking": true
    },
    {
      "item_id": "EX-002",
      "description": "部署空头: 从short candidates选1只，建仓≥$7,500",
      "deadline": "2026-05-28",
      "status": "pending",
      "blocking": true
    },
    {
      "item_id": "EX-003",
      "description": "CRM/DG/COPX三只C级试单: 财报后升至B级或清仓，不允许停留>2周",
      "deadline": "2026-06-05",
      "status": "pending",
      "blocking": false
    }
  ],
  "completion_threshold": 0.5,
  "status": "pending",
  "priority": "high",
  "created_at": "2026-05-22T10:00:00+08:00",
  "escalation": {
    "clock_type": "immediate",
    "level": "critical",
    "blocks_new_positions": true
  }
}
```

### 50% 完成门槛规则

**规则：** 当新方法论版本被写入（任何 `strategy.md` 版本号变化，或新 `##` 级别规则的加入），系统检查上一版本的 `methodology_execution` 条目。如果其 `execution_items` 中 `status: "pending"` 的 blocking 项超过 50%，则：

1. 新方法论条目被写入 pending_actions.json，但标记 `"methodology_blocked": true`
2. 当日复盘（daily-reviews）在摘要区域显示红色警告：`⛔ 新方法论已写入但被阻断：上版本执行率 {X}% < 50%`
3. 当前版本的规则不在 execute_trade.py 中生效，直到执行率超过 50%

**当前状态（v4.0）：** v3.0 的 rebalance 建议执行率约 30%（只执行了 FPS 加仓，未执行 GOOGL/SRUUF 减仓），应在本次系统升级时补录为 `methodology_execution` 条目并立即标记阻断。

### 检测机制

在 `scripts/daily_run.sh` 中加入版本检测步骤：

```bash
# 在 git pull 之后，每日运行开始时
python3 scripts/check_methodology_version.py
# 该脚本读取 strategy.md 第一行的版本号（"# 策略文件 — v{X.Y}"）
# 对比 pending_actions.json 中最新 methodology_execution 条目的 methodology_version
# 如不一致，生成新的 PA 条目并写入 pending_actions.json
```

---

## 机制三：决策冷静期

### 设计原理

在系统升级或方法论写作完成后的 5 个交易日内，禁止写入新规则。这不是靠意志力实现的——通过 `strategy.md` 文件的修改日期追踪来强制执行。

### 冷静期状态文件

新增 `/sim-portfolio/system-reform/cooldown_state.json`：

```json
{
  "_meta": {
    "purpose": "追踪方法论写作后的执行冷静期",
    "schema_version": "1.0"
  },
  "cooldown": {
    "active": false,
    "triggered_by": null,
    "trigger_event": null,
    "trigger_date": null,
    "end_date": null,
    "trading_days_remaining": 0,
    "exception_log": []
  },
  "rule_write_history": [],
  "execution_ratio_7d": null,
  "blocked_rule_proposals": []
}
```

**触发条件：** 任何 strategy.md 版本号升级，或 `research-notes/` 下新建 `US_TRADING_SYSTEM_V{N}.md`

**触发后状态：**
```json
{
  "cooldown": {
    "active": true,
    "triggered_by": "strategy.md v5.0",
    "trigger_event": "methodology_major_update",
    "trigger_date": "2026-05-22",
    "end_date": "2026-05-29",
    "trading_days_remaining": 5,
    "exception_log": []
  }
}
```

### 冷静期执行规则

**允许（冷静期内）：**
- 执行已有 pending_actions
- 执行既有规则下的交易
- 修复明确 bug（标记 `exception_type: "critical_fix"`，写入 exception_log）

**禁止（冷静期内）：**
- strategy.md 版本号升级
- 新增 `##` 级别规则（铁律/L系列）
- 新增 `###` 级别子规则（超过 3 条时）
- 新建 US_TRADING_SYSTEM_V{N+1}.md

**强制执行机制：**
- `scripts/daily_run.sh` 的 session 启动时读取 cooldown_state.json
- 如果 `cooldown.active: true`，在 session 报告顶部打印 COOLDOWN ACTIVE 警告
- 如果当日 git diff 显示 strategy.md 有 `+` 行新增了 `##` 或 `**L` 开头的规则，打印 VIOLATION 警告

**例外申请格式（critical_fix）：**
```json
{
  "exception_type": "critical_fix",
  "requested_at": "2026-05-24T10:00:00+08:00",
  "rule_change": "修正L18：空头扫描的VIX阈值从25→20，因回测数据显示VIX 20-25区间的空头WR更高",
  "justification": "数据驱动，不是新规则，是参数修正",
  "accepted": true
}
```

### 冷静期倒计时集成

在每日复盘 `daily-reviews/YYYY-MM-DD.md` 的 session 报告顶部自动添加：
```
[COOLDOWN] 执行冷静期剩余 3 个交易日（至 2026-05-29）。本期聚焦执行，不写新规则。
```

---

## 机制四：Rebalance 强制执行

### 设计原理

当 conviction ranking 变化时（由 decision_engine.py 检测），自动生成 rebalance 交易并写入 pending_actions.json。2个交易日未执行 → 新建仓被阻断。5个交易日 → rebalance 建议变 stale，需重新评估。

### Conviction Ranking 变化检测

在 `decisions.json` 中新增 `conviction_ranking` 字段，记录每次 session 的 conviction 排序：

```json
{
  "conviction_ranking": {
    "session_date": "2026-05-22",
    "us": [
      {"ticker": "FPS", "grade": "B+", "score": 87},
      {"ticker": "GEV", "grade": "B+", "score": 85},
      {"ticker": "AAPL", "grade": "B+", "score": 84},
      {"ticker": "NVDA", "grade": "B+", "score": 82},
      {"ticker": "ADBE", "grade": "B", "score": 78},
      {"ticker": "GOOGL", "grade": "C+", "score": 62},
      {"ticker": "SRUUF", "grade": "C-", "score": 45}
    ],
    "changed_from_previous": true,
    "changes": [
      {"ticker": "FPS", "from_rank": 8, "to_rank": 1, "reason": "thesis验证+4.74%"},
      {"ticker": "GOOGL", "from_rank": 4, "to_rank": 6, "reason": "无催化剂，共识溢价低"},
      {"ticker": "SRUUF", "from_rank": 5, "to_rank": 7, "reason": "流动性差，无近期催化剂"}
    ]
  }
}
```

### 自动生成 Rebalance Pending Action

当 `changed_from_previous: true` 且排名变化超过 2 位时，`decision_engine.py` 自动写入 pending_actions.json：

```json
{
  "id": "PA-RBAL-001",
  "type": "rebalance_auto",
  "name": "自动Rebalance — Conviction变化 (2026-05-22)",
  "source": "conviction_ranking_change",
  "trades": [
    {
      "ticker": "GOOGL",
      "action": "sell",
      "shares": 10,
      "reason": "Conviction下降(rank 4→6)，sizing与conviction对齐",
      "target_pct": 0.05,
      "current_pct": 0.078
    },
    {
      "ticker": "SRUUF",
      "action": "sell",
      "shares": 200,
      "reason": "Conviction下降(rank 5→7)，流动性风险，无催化剂",
      "target_pct": 0.05,
      "current_pct": 0.081
    },
    {
      "ticker": "FPS",
      "action": "buy",
      "shares": 100,
      "reason": "Conviction上升(rank 8→1)，thesis验证",
      "target_pct": 0.08,
      "current_pct": 0.046
    }
  ],
  "deadline_trading_days": 2,
  "deadline_date": "2026-05-26",
  "stale_date": "2026-05-29",
  "status": "pending",
  "priority": "high",
  "created_at": "2026-05-22T10:00:00+08:00",
  "escalation": {
    "clock_type": "immediate",
    "level": "critical",
    "blocks_new_positions": true,
    "blocking_after_days": 2
  }
}
```

### 2个交易日阻断逻辑

- `deadline_date` 过后，`blocks_new_positions: true` 激活
- `execute_trade.py` 在任何美股 buy/short 前检查是否有过期 `rebalance_auto` 条目
- 提示：`⛔ 阻断：PA-RBAL-001 rebalance 已逾期 {N} 个交易日，先执行或明确推迟`

### Stale 处理

当前日期达到 `stale_date`：
- 条目状态更新为 `"stale"`
- 不再阻断新建仓（price may have moved significantly）
- 自动触发 `decision_engine.py --dry-run` 重新生成当前建议
- 新建议写入 decisions.json，等待 agent 评估是否仍适用

### 集成点

- `decision_engine.py` — 在 decision logic 末尾调用 `generate_rebalance_actions()`，对比上次 decisions.json 中的 `conviction_ranking`，如有变化写入 pending_actions.json
- `execute_trade.py` — `check_rebalance_blocks()` 检查是否有过期 rebalance_auto 条目

---

## 机制五：每周执行记分卡

### 设计原理

每周五（或周五收盘后当日）自动生成 `weekly-reports/YYYY-WNN-execution-scorecard.md`，追踪本周 规则写入 vs 规则执行 的比率，在比率过低时阻断下周的规则写作权限。

### 执行记分卡自动生成

`scripts/daily_run.sh` 在每周五 W2 窗口（16:00 BJT A股收盘后）执行：

```bash
python3 scripts/generate_scorecard.py --week current
```

### 记分卡计算逻辑

```
rules_written_this_week = 本周 strategy.md 新增的 ## 级别规则数
                         + 本周 pending_actions.json 新增的 methodology_execution 条目
                         + 本周新增的 L{N} 铁律数

rules_executed_this_week = 本周移入 completed 的 pending 条目数（非trigger-gated类）
                          + 本周 methodology_execution 条目中标记完成的 EX-{N} 项数

execution_ratio = rules_executed_this_week / max(rules_written_this_week, 1)
```

### 记分卡 JSON Schema

`weekly-reports/execution_scorecard_state.json`：

```json
{
  "current_week": {
    "week_id": "2026-W21",
    "start_date": "2026-05-18",
    "end_date": "2026-05-22",
    "rules_written": 12,
    "rules_executed": 2,
    "execution_ratio": 0.17,
    "violations_recorded": {
      "L16": 4,
      "L18": 5,
      "rebalance_pending": 1
    },
    "flag": "BLOCKED",
    "flag_reason": "执行率0.17 < 0.3阈值，下周规则写作被阻断",
    "generated_at": "2026-05-22T16:30:00+08:00"
  },
  "next_week_rule_write_allowed": false,
  "history": []
}
```

### 阈值和后果

| 执行率范围 | 标志 | 后果 |
|-----------|------|------|
| ≥ 0.5 | GREEN | 正常运营，可写新规则 |
| 0.3–0.5 | WARNING | 黄色警告，新规则写入时提示"本周执行率偏低" |
| < 0.3 | BLOCKED | 下周禁止写新规则（strategy.md 版本号冻结），冷静期自动触发 |

**第一周特殊情况（v1.0~v4.0，Day 1–5）：**
- rules_written = 12（v1.0 → v4.0 + L10-L18 + 20条 backtest lesson + 7条 pending 操作）
- rules_executed = 2（蓝思止损清仓 + 双环传动清仓 + Day5 6笔交易中约2条符合规则驱动）
- execution_ratio ≈ 0.17 → BLOCKED 状态
- 后果：本次系统升级（v5.0）应被自动标记为 `"methodology_blocked": true`，需先执行 Day 5 遗留的 7 条 pending 操作

### 记分卡文件格式

`weekly-reports/2026-W21-execution-scorecard.md`：

```markdown
# 执行记分卡 — Week 2026-W21 (2026-05-18 ~ 2026-05-22)

## 总评

**执行率: 0.17 — 🔴 BLOCKED（下周规则写作被阻断）**

| 指标 | 本周 |
|------|------|
| 规则写入数 | 12 |
| 规则执行数 | 2 |
| 执行率 | 0.17 |
| L18违反次数 | 5/5天 |
| L16违反次数 | 4/5天 |
| Pending创建 | 7 |
| Pending完成 | 0 |

## 未执行清单（需在下周优先处理）

1. **PA-007**: L18空头配额修复 — 0空头已5天，立即执行
2. **PA-006**: 周三做空扫描SOP
3. **v3.0 Rebalance**: 卖GOOGL+SRUUF，买FPS+GEV（写于Day 3，2个交易日未执行）
4. PA-002 / PA-003: DG/CRM财报预案（trigger-gated，不计入阻断但需review）

## 下周行动约束

- 规则写作：**BLOCKED**，冷静期5个交易日（2026-05-26 ~ 2026-05-30）
- 必须先执行：PA-007 → PA-006 → v3.0 Rebalance
- 解除阻断条件：以上3项全部完成或写入有效defer理由
```

### 集成点

- `scripts/generate_scorecard.py` — 新建脚本，每周五自动调用
- `scripts/daily_run.sh` — 每周五加入 `python3 scripts/generate_scorecard.py` 调用
- `scripts/risk_monitor.py` — 在报告顶部读取 `execution_scorecard_state.json`，如 `next_week_rule_write_allowed: false` 则展示 BLOCKED 警告

---

## 全系统集成视图

```
session 启动（每次）
        │
        ▼
check_methodology_version.py     ← 检测版本变化，自动创建 methodology_execution PA
        │
        ▼
check_pending_escalation()        ← 更新所有 PA 的升级状态（normal/reminder/warning/critical/force）
        │
        ▼
check_cooldown_state()            ← 检查是否在规则写作冷静期
        │
        ▼
L17 §4: 展示 pending_actions     ← 按升级级别排序，CRITICAL/FORCE 置顶红色显示
        │
        ▼
用户/agent 决策执行
        │
        ▼
execute_trade.py                  ← pre-flight 检查：
  check_pending_blocks()          ←   有 CRITICAL blocking PA？→ 拒绝，exit 2
  check_rebalance_blocks()        ←   有过期 rebalance_auto？→ 拒绝，exit 2
        │
        ▼
执行后：更新 PA completed 数组
        │
        ▼
每周五：generate_scorecard.py     ← 更新 execution_scorecard_state.json
        │
        ▼
如 execution_ratio < 0.3：
  cooldown_state.json active=true ← 下周自动进入冷静期
```

---

## 当前积压的 Pending Actions 处置建议

根据上述机制，对现有 7 条 pending 的即时处置建议：

| ID | 当前状态 | 机制应用后状态 | 建议行动 |
|----|---------|--------------|---------|
| PA-007 | urgent | CRITICAL + blocks_new_positions=true | 本周W3窗口（05-28 22:00）执行做空扫描，这是最高优先级 |
| PA-006 | pending | CRITICAL（immediate，已5天） | 与PA-007合并执行，同一个W3窗口 |
| v3.0 rebalance（PA缺失）| 存在于研究笔记，未入PA | 补录为 PA-008，type=methodology_execution，deadline=2026-05-26 | 05-26周一美股开盘前补录并执行 |
| PA-001 | trigger_gated，2026-05-29 | normal，触发后计时 | 05-29 ASCO后按预案24h内执行 |
| PA-002 / PA-003 | trigger_gated | normal，触发后计时 | 分别在6/2、6/3财报后24h内执行 |
| PA-004 | trigger_gated，2026-06-08 | normal | WWDC后1个交易日评估并执行 |
| PA-005 | trigger_gated，2026-06-11 | normal | ADBE Q2后24h内执行 |

**最紧急：PA-007 + PA-006 + v3.0 rebalance（应补录为PA-008）**
这三项在机制一生效后会立即阻断新建仓，且两项早应执行，必须在下个交易日（05-26）前处理。

---

## 实施优先级

| 优先级 | 实施项 | 文件 | 工作量 |
|--------|--------|------|-------|
| P0 | 为现有PA-007/PA-006补录escalation字段并设为CRITICAL+blocking | pending_actions.json | 5分钟 |
| P0 | 补录v3.0 rebalance为PA-008 | pending_actions.json | 5分钟 |
| P1 | 新建 check_pending_escalation() 函数并集成至 risk_monitor.py | scripts/risk_monitor.py | 1-2小时 |
| P1 | 新建 check_pending_blocks() 函数并集成至 execute_trade.py | scripts/execute_trade.py | 30分钟 |
| P2 | 新建 cooldown_state.json + check_cooldown_state() | system-reform/cooldown_state.json + scripts/ | 1小时 |
| P2 | 新建 generate_scorecard.py + 第一周数据回填 | scripts/generate_scorecard.py | 2小时 |
| P3 | conviction_ranking 变化检测 + auto rebalance PA 生成 | scripts/decision_engine.py | 3小时 |
| P3 | check_methodology_version.py | scripts/check_methodology_version.py | 1小时 |

---

## 核心原则总结

**1. 阻断优于提醒。** 本文档中所有机制的设计核心是：规则不执行 → 系统物理拒绝新操作，而不是仅发出警告。

**2. 时间计时从写入那刻开始。** 任何规则或建议写入系统的那一刻，执行时钟就开始倒计时，没有免费的"研究期"。

**3. Trigger-gated 类型是真正的等待，其余类型没有借口。** PA-001到PA-005等催化剂是合理等待。PA-006、PA-007、v3.0 rebalance没有合理理由可以等待5天。

**4. 最简执行优于完美执行。** FORCE 级别自动生成的操作是最简合规操作，不是最优操作。接受不完美的执行，好过完美的拖延。

**5. 执行率是比收益率更重要的早期指标。** 在模拟盘的前期，execution_ratio 是系统健康度的核心指标。执行率低的系统，收益率数据是虚假的——它只反映了偶然执行的那部分规则，而非整个方法论的效果。

---

*文档版本: v1.0 | 创建日期: 2026-05-22 | 作者: Claude模拟盘系统*
*基于: pending_actions.json v1.0 + CLAUDE.md + self-review-day5.md + daily-reviews 2026-05-19/05-22*
