# Victory Memory — 胜利记忆

> 与 pain_memory.md 对称。Rolling 5条，最新在前。
> 触发: 盈利出场 / PEAD ADD确认 / 连胜里程碑 / 周度最佳交易
> 注入: Session Open必读 → Pre-Trade模式匹配 → In-Trade持有信心校准

---

## 当前记录 (0/5)

_系统刚初始化。第一条胜利记忆将在首笔盈利出场后写入。_

---

<!-- TEMPLATE (parser ignores HTML comments)
### VM-{序号} | {TICKER} | {DATE} | +{GAIN%} | +{R}R | 持有{N}天

**策略**: {MOM_ROTATION | DIP_BUY | PEAD_ADD | PROBE_THEN_PRESS}
**入场Grade**: {S/A+/A/A-/B+/B/B-}
**MFE Capture**: {exit_pnl ÷ max_unrealized_gain}%

**1. 哪个信号我读对了？**
{具体: 什么数据/图形/催化剂让我判断对了}

**2. 我做对了什么决策？**
{entry timing / sizing / holding discipline / adding / 不过早卖出}

**3. 下次同类setup的if-then：**
IF {相同条件重现} THEN {相同动作 + 优化点}

**Pattern tag**: {momentum_ride | probe_then_press | pead_confirmation | catalyst_nailed | dip_recovery | regime_read | earnings_hold}
-->

---

## 注入协议

### Session Open (与pain_memory.md同时读取)
1. 读全部victory_memory.md
2. 生成"赢家模式摘要"——最近5次胜利的共同特征
3. 与当前持仓交叉对比: 哪些持仓正在重演胜利模式？

### Pre-Trade Gate (Gate 0.5 — 痛感检查后、建仓前)
- 扫描PlayBook: 当前setup是否匹配已知赢家模式？
- 匹配命中: "这个setup和VM-{X}一样——{TICKER}上次{策略}赚了{R}R因为{原因}"
- 匹配 → 信心+1档 (B→B+), 不匹配 → 信心不变 (不惩罚)
- ⚠️ 信心提升有上限: 一次匹配最多+1档, 不能从B直接跳A+

### In-Trade 持有校准 (每个session持仓Review时)
- 对每个浮盈持仓, 检查: "上次{类似setup}我拿住了{N}天赚了{R}R"
- 正在重演赢家模式 → 系统说: "继续持有。历史MFE capture {X}%, 当前{Y}%, 仍有空间"
- 已达历史MFE中位数 → 系统说: "接近典型出场区间。检查trailing stop是否到位"

### Post-Trade 记录 (盈利出场后5分钟内)
- 填写VM模板 (5分钟, 比30分钟的痛感post-mortem短——因为λ=2.25, 痛感应该花更多时间)
- 检查PlayBook是否已有同类模式 → 有: 累加实例 → 无: 评估是否新建模式条目
- 更新R倍数仪表盘
