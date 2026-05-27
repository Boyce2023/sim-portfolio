# Pain/Reward Architecture V6.2

> Extracted from US_TRADING_SYSTEM_V6.md §11. Fully operationalized in conviction_check.py.
> Last updated: 2026-05-27

---

## §11 PAIN/REWARD ARCHITECTURE — 双向行为反馈系统

> 核心原理: 亏钱必须改变行为，赢钱必须复制模式。六层独立运作，不依赖agent自觉。
> 理论基础: Reflexion记忆注入(LLM Agent) + 电路熔断(交易Bot) + 前景理论λ=2.25(Kahneman)
> + Minervini Victory Journal + Druckenmiller加注赢家 + SMB Capital PlayBook + Van Tharp R-Multiple/Expectancy + Steenbarger解决聚焦 + Huang&Guenther 2024去偏差

---

### PART A: PAIN SYSTEM（失败反馈，惩罚即时生效）

#### Layer 1: Pain Memory（Reflexion式失败记忆注入）

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

#### Layer 2: Circuit Breaker（电路熔断分级）

**状态机**: 三级，自动触发，不可手动覆盖

| 状态 | 触发条件 | 限制 | 恢复条件 |
|------|---------|------|---------|
| 🟢 GREEN | 默认 | 正常运行 | — |
| 🟡 YELLOW | 单周跌>3% OR 连续止损≥2次 | sizing全线×0.5 | 连续2周无新止损 |
| 🔴 RED | 单周跌>5% OR 连续止损≥3次 | 禁止新建仓，只允许减仓+discovery | 连续2周无新止损→升至YELLOW |

**关键设计**: 亏损时判断力最不可靠 → 熔断自动，不靠自觉。恢复速度慢于触发速度（不对称）。

#### Layer 3: Conviction Credit（评级信用分）

| 触发事件 | 后果 | 恢复条件 |
|---------|------|---------|
| A+/A持仓触止损 | 30天内不可新建A+级，最高A | 降级后连续3笔A级盈利出场 |
| A-/B+持仓触止损 | 记录，不限制评级 | — |
| 同一错误模式第2次 | 该模式相关持仓全降一级 | 写post-mortem + 新if-then规则 |
| Grade准确率<50%（rolling 10笔） | 全线评级上限降一级 | 准确率恢复>60% |

---

### PART B: VICTORY PROTOCOL（成功反馈，奖励需持续验证）

> 研究来源: Minervini胜利日志(情绪强化) + Druckenmiller"赢了就加注" + SMB Capital PlayBook(赢家模式库) + Van Tharp R-倍数/期望值系统 + Steenbarger解决聚焦疗法 + Huang&Guenther 2024 debiasing(处置效应研究) + John Sweeney MFE分析
> 核心差异: Pain系统聚焦"不重复错误"；Victory Protocol聚焦"复制成功模式"。两者对称运行，互不替代。

#### Layer 4: Victory Memory（胜利记忆注入）

**文件**: `victory_memory.md`（portfolio根目录，与pain_memory.md对称）
**机制**: 每次盈利出场 → 写VM模板(5-10min) → 存入rolling window（保留最近5条）

```
每条胜利记忆必须回答3个问题:
  1. 哪个信号我读对了？（什么数据/图形/催化剂让我判断正确）
  2. 我做对了什么决策？（entry timing/sizing/holding/adding/不过早卖出）
  3. 下次同类setup的if-then（IF相同条件重现 THEN 相同动作+优化点）
```

**注入时机**:
- Session Open: 读victory_memory.md → 生成"赢家模式摘要" → 与当前持仓交叉: 哪些正在重演胜利模式？
- Pre-Trade (Gate 0.5): 扫描PlayBook，当前setup匹配赢家模式？匹配→信心+1档(B→B+)，最多+1档
- In-Trade: 浮盈持仓检查 "上次{类似setup}拿住{N}天赚了{R}R" → 校准持有信心 vs MFE capture历史

**为什么有效**: Steenbarger解决聚焦——把注意力从"避免什么"移到"复制什么"。与Pain Memory形成完整认知闭环。

#### Layer 5: Conviction Amplifier（信念放大器，对称Circuit Breaker）

**状态机**: 三级，基于PROCESS质量（不是结果），自动计算

| 状态 | 触发条件 | 效果 | 降级条件 |
|------|---------|------|---------|
| ⚪ NORMAL | 默认 | sizing×1.0 | — |
| 🔵 ELEVATED | A-grade率≥60%(rolling 10) + R期望值>0.5(rolling 20) | sizing×1.25 | A-rate<60% OR expectancy<0.5 |
| 🟣 PEAK | A-grade率≥75% + R期望值>1.0 + A连续≥5 | sizing×1.5 | 任一条件不满足→回落 |

**关键设计**:
- 奖励PROCESS不奖励OUTCOME: A-grade衡量是否遵守系统，不是是否赚钱
- CA只在GREEN时生效: Circuit Breaker RED/YELLOW优先级高于Conviction Amplifier
- PEAK需要三重验证: 防止短期运气误触发加仓
- 恢复快于Pain: CA降级即时，不需等待期（反映"信心可以快速恢复但惩罚需要时间消化"）

**Trade Process Grading (A/B/C)**:
```
A-grade: 完全遵守系统规则（4-Gate通过，sizing合规，止损到位，按if-then执行）
B-grade: 基本遵守但有小偏差（sizing略超/timing略偏/未写完整pre-trade理由）
C-grade: 明显违反系统（情绪交易/跳过Gate/无止损/Round Trip）
```

**跟踪**: `conviction_scorecard.json` → `conviction_amplifier` + `trade_grades`

#### Layer 6: PlayBook + R-Multiple Dashboard（赢家模式库 + 量化追踪）

**文件**: `playbook.json`（portfolio根目录）

**PlayBook** (SMB Capital模型):
- 从胜利交易中逆向工程可复制的setup
- 每个模式需≥2个实例才算validated。单实例=观察中(observation)
- 结构: id / name / status / conditions / if_then / anti_pattern / edge_source / instances
- 已验证模式: PB-001 Probe Then Press(85%WR,+6.85R) / PB-002 Momentum Ride(80%WR,+3.95R) / PB-003 PEAD Confirmation Add(100%WR,+3.8R)

**R-Multiple Dashboard** (Van Tharp):
- 每笔交易记录R倍数 = 实际盈亏 ÷ 初始风险额
- Rolling 20笔: win_rate / avg_win_r / avg_loss_r / expectancy
- Expectancy = (win_rate × avg_win) + ((1-win_rate) × avg_loss) → 每R赚多少
- Expectancy>0.5R = 系统有正edge。<0 = 系统需要修正

**MFE Capture** (John Sweeney):
- MFE(Maximum Favorable Excursion) = 持仓期间最大浮盈
- MFE Capture = exit_pnl ÷ max_unrealized_gain
- <40% = 系统性过早卖出(处置效应) → 需放宽trailing stop
- >70% = 优秀的利润捕获

**Anti-Disposition Rules** (Huang & Guenther 2024):
- Hold Review: 隐藏成本价，只显示前瞻信息(thesis/催化剂/止损线)
- 强制声明: 浮盈>5%的持仓必须写"我选择继续持有{ticker}因为催化剂{X}尚未兑现"
- L11锚定: "已涨了不少"不是卖出理由。减仓需提供"与催化剂无关"的充分理由

---

### PART C: SCORECARD + 集成

#### Conviction Scorecard（每session开头生成，不可跳过）

```
=== CONVICTION SCORECARD ===
Circuit Breaker: 🟢/🟡/🔴
连续止损次数: ___  |  本周drawdown: ___%
评级权限: A+ [✓/✗] | A [✓/✗] | 全线降级 [Y/N]

── Pain System ──
最近止损 (pain_memory top 1):
  {ticker} | {date} | {loss%} | {错在哪1句话}

── Victory Protocol ──
Conviction Amplifier: ⚪/🔵/🟣 (sizing ×___)
连续胜利: ___  |  A-grade连续: ___

最近胜利 (victory_memory top 1):
  {ticker} | {date} | {gain%} | {+R}R

R-Multiple (rolling 20笔):
  胜率: ___% | 均赢: +___R | 均亏: ___R | 期望值: ___R

Process Grade (rolling 10笔): A=_ B=_ C=_ → A-rate=___%

PlayBook: _个验证模式
MFE Capture: ___%

── 综合 ──
Grade准确率: A+/A=___% | B+/B=___%
Discovery Override战绩: ___W/___L = ___%
Override预算: ___次/周
```

**生成命令**: `uv run --script scripts/conviction_check.py`

#### CLI命令速查

| 命令 | 用途 | 触发时机 |
|------|------|---------|
| `conviction_check.py` | 显示完整scorecard | 每session开头 |
| `conviction_check.py --update` | 重算CB+CA状态 | 周五例行 |
| `conviction_check.py --post-mortem --ticker X --loss-pct Y --grade Z --pod W` | 止损后更新 | 止损出场后 |
| `conviction_check.py --victory --ticker X --gain-pct Y --r-multiple R --grade Z --strategy S --mfe-capture M` | 胜利记录 | 盈利出场后 |
| `conviction_check.py --grade-trade --ticker X --process-grade A/B/C --reason "..."` | 过程评分 | 每笔交易完成后 |
| `conviction_check.py --hold-review` | 反处置效应检查(隐藏成本) | 每session持仓review |
| `conviction_check.py --playbook` | 显示赢家模式库 | 建仓前模式匹配 |
| `conviction_check.py --win --ticker X --gain-pct Y --grade Z` | 简易盈利记录(向后兼容) | — |

#### 集成触点

| 系统位置 | Pain System嵌入 | Victory Protocol嵌入 |
|---------|----------------|---------------------|
| §3 Gate 0 | CB检查(🔴=拒绝) + pain memory match | CA修正(🔵×1.25/🟣×1.5) + PlayBook match(Gate 0.5) |
| §6 Exit | 止损→mandatory post-mortem(30min) | 盈利→victory log + VM模板(5-10min) + playbook check |
| §8 Session Open | 读pain_memory + scorecard | 读victory_memory + 赢家模式摘要 + 持仓交叉对比 |
| §8 持仓Review | pain pattern match | hold-review(隐藏成本) + MFE校准 + L11提醒 |
| §8 周五例行 | --update重算CB | --update重算CA + --playbook模式审视 |
| §10 Discovery | RED=唯一允许的进攻 | PlayBook反向: 观察池中缺失的模式→Discovery目标 |
| CLAUDE.md triggers | T_PAIN: 止损触发 | T_VICTORY: 盈利触发 / T_HOLD: 持仓review触发 |

#### 不对称原则

| 维度 | Pain (λ=2.25权重) | Victory (1.0权重) |
|------|-------------------|--------------------|
| 记录时间 | 30min mandatory | 5-10min |
| 生效速度 | 即时(触止损=立即限制) | 渐进(需rolling验证) |
| 恢复/降级 | 慢(2周/30天) | 快(即时降级) |
| 注入强度 | 高(每次建仓强制match) | 中(匹配=+1档，不匹配=不变) |
| 文件优先 | pain_memory先读 | victory_memory后读 |

**设计哲学**: Pain系统防止重复犯错(守)，Victory Protocol复制成功模式(攻)。两者互不替代，共同构成完整的行为反馈闭环。Pain先行、Victory跟随——因为不亏钱比赚钱更重要。

---

*§11 V6.2 | 2026-05-27 | Pain/Reward Architecture升级: +Victory Memory(Layer 4) + Conviction Amplifier(Layer 5) + PlayBook/R-Multiple/MFE/Anti-Disposition(Layer 6) — 6层完整行为反馈系统*
