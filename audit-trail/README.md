# Decision Audit Trail 系统

## 用途

每笔交易自动生成一个JSON文件，记录完整推理链，使每个交易决策可追溯、可审计。

核心价值：
- 事后复盘：为什么当时做了这个决策？推理链清晰可查。
- 行为铁律追踪：止损是否无条件执行？ABCD分类是否正确？Bear case是否通过 ≤ -20% 规则？
- 策略进化：多笔交易的decision_chain对比，找出系统性偏差。

## 文件命名

```
YYYY-MM-DD-TICKER-ACTION.json
```

同日同ticker多笔时加序号：
```
2026-05-18-NVDA-buy-001.json
2026-05-18-NVDA-buy-002.json
```

A股ticker直接用代码（不加后缀）：
```
2026-05-18-002028-buy.json
2026-05-20-300433-sell.json
```

## 目录结构

```
audit-trail/
├── README.md                     本文件
├── _schema.json                  完整JSON Schema定义 + 枚举参考
│
├── 2026-05-18-NVDA-buy.json      TRD-D1-001 美股Day1建仓
├── 2026-05-18-HSAI-buy.json      TRD-D1-002 美股Day1建仓
├── 2026-05-18-AAPL-buy.json      TRD-D1-003 美股Day1建仓
├── 2026-05-18-GOOGL-buy.json     TRD-D1-004 美股Day1建仓
├── 2026-05-18-ADBE-buy.json      TRD-D1-005 美股Day1建仓
├── 2026-05-18-SPUT-buy.json      TRD-D1-006 美股Day1建仓
├── 2026-05-18-GEV-buy.json       TRD-D1-007 美股Day1建仓
├── 2026-05-18-LEU-buy.json       TRD-D1-008 美股Day1建仓
├── 2026-05-18-002028-buy.json    TRD-A-001 A股Day1建仓（思源电气）
├── 2026-05-18-603005-buy.json    TRD-A-002 A股Day1建仓（晶方科技）
├── 2026-05-18-300433-buy.json    TRD-A-003 A股Day1建仓（蓝思科技）
│
├── 2026-05-20-HSAI-sell.json     TRD-0009 美股止损清仓
├── 2026-05-20-300433-sell.json   TRD-0010 A股止损清仓
├── 2026-05-20-002938-buy.json    TRD-0011 A股新建仓（鹏鼎控股）
├── 2026-05-20-002472-buy.json    TRD-0012 A股新建仓（双环传动）
├── 2026-05-20-NVDA-buy.json      TRD-0013 美股动量加仓
│
└── 2026-05-21-FPS-buy.json       TRD-0014 美股IPO新建仓
```

## Schema 核心字段

每个audit trail文件包含：

| 字段 | 说明 |
|------|------|
| `trade_id` | 对应 portfolio_state.json trade_log 中的 id |
| `timestamp` | ISO 8601 格式，含时区 |
| `ticker` | 交易标的代码 |
| `action` | buy / sell / short / cover |
| `account` | us / a_share |
| `decision_chain.trigger` | 触发类型 + 描述 + 来源 |
| `decision_chain.thesis_check` | thesis有效性 + bear case + ABCD分类（仅卖出时） |
| `decision_chain.risk_check` | 单仓/板块/现金三道限额检查 |
| `decision_chain.sizing` | 仓位计算方法 + 信心等级(A/B/C) |
| `decision_chain.final_decision` | 批准状态 + 是否有规则覆盖 + 备注 |
| `post_trade_state` | 交易后账户现金/持仓数/NAV快照 |

完整schema定义见 `_schema.json`。

## 触发类型（trigger.type）

| 类型 | 说明 | 典型例子 |
|------|------|---------|
| `portfolio_init` | 组合首次建仓 | Day1批量建立底仓 |
| `catalyst` | 事件催化剂 | 财报/WWDC/政策 |
| `stop_loss` | 止损触发 | 价格跌破止损线 |
| `research` | 研究驱动 | 新数据验证赛道 |
| `momentum` | 动量跟随 | 财报前run-up |
| `rebalance` | 再平衡 | 仓位调整 |
| `new_ipo` | 新股IPO | 首次建立IPO仓位 |

## 信心等级（sizing.confidence_level）

| 等级 | 说明 | 仓位范围 |
|------|------|---------|
| A | 充分研究+催化剂明确+bear case通过 | 10-15% |
| B | thesis初步验证，等催化剂加仓 | 5-8% |
| C | 观察仓，主要目的跟踪赛道 | <5% |

## 铁律追踪（每笔交易必须验证）

1. **Bear case ≤ -20%**：`thesis_check.bear_case_rule_pass` 必须为 true
2. **单仓 ≤ 15%**：`risk_check.single_position_limit_ok` 必须为 true
3. **现金 ≥ 20%**：`risk_check.cash_minimum_ok` 必须为 true
4. **止损无条件执行**：`trigger.type = "stop_loss"` 时 `approver = "auto"`
5. **同日新建仓 ≤ 3只**：同日 action=buy 且非加仓文件不超过3个
6. **事件当天不追涨**：catalyst触发当日不建仓（预案触发当日除外）
7. **ABCD分类**：卖出时 `abcd_classification` 不得为空

## 新增交易时如何创建

1. 从 `portfolio_state.json` trade_log 读取交易基本信息
2. 按文件命名规则创建 `YYYY-MM-DD-TICKER-ACTION.json`
3. 填写 `decision_chain` 各字段（可参考 `_schema.json` 中的 example）
4. 验证所有铁律字段均已填写
5. `post_trade_state` 从交易后的 portfolio_state.json 快照
