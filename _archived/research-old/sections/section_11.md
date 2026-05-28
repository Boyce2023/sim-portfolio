## §11 PAIN/REWARD ARCHITECTURE — 行为反馈系统

> 核心原理: 亏钱必须改变行为，不只是记录。三层独立运作，不依赖agent自觉。
> 理论基础: Reflexion记忆注入(LLM Agent) + 电路熔断(交易Bot) + 前景理论λ=2.25(Kahneman)

---

### Layer 1: Pain Memory（Reflexion式失败记忆注入）

**文件**: `pain_memory.md`（portfolio根目录）
**机制**: 每次止损出场 → 写mandatory post-mortem → 存入rolling window（保留最近5条）

```
每条post-mortem必须回答3个问题:
  1. 哪里判断错了？（不是"市场不好"，是"我"错在哪）
  2. 有没有提前出现的信号我忽略了？
  3. 下次遇到同类情况的if-then是什么？
```

**注入时机**:
- 每session开头：读pain_memory.md，生成scorecard
- 每次建仓前：检查pain_memory中是否有pattern match（同sector/同类型catalyst/同grade）
- Match命中 → 必须在pre-trade gate中写"我知道上次{X}亏了{Y}%因为{Z}，这次不同因为{具体原因}"

**为什么有效**: 失败反思的语义密度天然高于成功记录。每次决策时被迫直面过去的错误，不是惩罚，是认知校准。

---

### Layer 2: Circuit Breaker（电路熔断分级）

**状态机**: 三级，自动触发，不可手动覆盖

| 状态 | 触发条件 | 限制 | 恢复条件 |
|------|---------|------|---------|
| 🟢 GREEN | 默认 | 正常运行 | — |
| 🟡 YELLOW | 单周跌>3% OR 连续止损≥2次 | sizing全线×0.5 | 连续2周无新止损 |
| 🔴 RED | 单周跌>5% OR 连续止损≥3次 | 禁止新建仓，只允许减仓+discovery | 连续2周无新止损→升至YELLOW |

**关键设计**: 
- 亏损时判断力最不可靠 → 熔断是自动的，不靠自觉
- RED状态下唯一允许的"进攻"动作是Discovery研究，不是交易
- 恢复速度慢于触发速度（不对称）：触发=瞬间，恢复=2周

**跟踪文件**: `conviction_scorecard.json`

---

### Layer 3: Conviction Credit（评级信用分）

**原理**: 给A+评级是一个判断——如果A+持仓止损出场，说明判断不可靠。限制评级权限=限制未来犯同类错误的能力。

| 触发事件 | 后果 | 恢复条件 |
|---------|------|---------|
| A+/A持仓触止损 | 30天内不可新建A+级，最高A | 降级后连续3笔A级盈利出场 |
| A-/B+持仓触止损 | 记录，不限制评级 | — |
| 同一错误模式第2次 | 该模式相关持仓全降一级 | 写post-mortem + 新if-then规则 |
| Grade准确率<50%（rolling 10笔） | 全线评级上限降一级 | 准确率恢复>60% |

**Grade准确率计算**:
```
盈利出场（任何幅度）= WIN
止损出场 = LOSS
对冲减仓（thesis变化）= NEUTRAL（不计）

准确率 = WIN / (WIN + LOSS)
分级统计: A+/A 和 B+/B 分开算
```

---

### Reward Architecture（正反馈扩展能力）

| 触发事件 | 奖励 | 意义 |
|---------|------|------|
| Discovery Override盈利 | Override频率+1/周(max 3) | 鼓励打破茧房 |
| A+持仓达标出场(+15%以上) | 回溯提取成功pattern→knowledge | 可复制的判断力 |
| 连续3月win rate>60% | Pod III上限+5%(20%→25%) | 动量能力扩展 |
| 单笔盈利>20% | 全流程复盘：什么信号→什么判断→什么timing做对了 | 正反馈强化 |

**不对称原则**: 惩罚即时生效，奖励需要持续验证。触发1次止损=立即限制；需要连续3笔盈利才恢复。Mirror前景理论λ=2.25。

---

### Conviction Scorecard（每session开头生成）

```
=== CONVICTION SCORECARD ===
Circuit Breaker: 🟢/🟡/🔴
连续止损次数: ___  |  本周drawdown: ___%
评级权限: A+ [✓/✗] | A [✓/✗] | 全线降级 [Y/N]

最近止损 (pain_memory top 1):
  {ticker} | {date} | {loss%} | {错在哪1句话}

Grade准确率 (rolling 10笔):
  A+/A: ___/___  = ___%
  B+/B: ___/___  = ___%

Discovery Override战绩: ___W / ___L = ___%
Override预算: ___次/周
```

**这个scorecard不可选——每个美股session开头必须生成，写入daily-review开头。**

---

### 集成触点

| 系统位置 | 嵌入内容 |
|---------|---------|
| §3 Pre-Trade Gate | Gate 0: Circuit Breaker检查 (🔴=拒绝建仓) + pain memory pattern match |
| §6 Exit Rules | 止损后mandatory post-mortem → pain_memory.md |
| §8 Operational Core | Session开头生成Conviction Scorecard |
| §10 Discovery | RED状态下唯一允许的进攻=Discovery研究 |
| CLAUDE.md | pre_session_check读取circuit breaker状态 |
| conviction_scorecard.json | SSOT for breaker state + grade accuracy + override budget |

---

*§11 V6.1 | 2026-05-27 | Pain/Reward Architecture — Reflexion + Circuit Breaker + Conviction Credit*
