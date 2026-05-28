## §6 EXIT RULES

### 两段式出场

| 阶段 | 触发 | 操作 |
|------|------|------|
| 第一段 | 目标价1达成 | 卖出50% |
| 第二段 | Trailing stop触发 OR 催化剂兑现后14天 | 余下全出 |

### Trailing Stops by Pod

| Pod | 初始止损 | Trailing Stop（从最高点回撤） |
|-----|---------|----------------------------|
| A | -15% (A+/A), -12% (A-/B+) | 12% |
| B | -15% (A+/A), -20% (催化剂型如LEU) | 15% |
| C | -12% (统一) | 8%（动量反转快，止损更紧） |
| D Short | -15% against | -8% if momentum inflects |

**止损铁律**: 触及止损线→当日执行。先分类（ABCD），再决定。I/II/III类重新评估thesis；D类当日无条件执行，不等反弹。

### F21 Beat Cycle Exit（Pod I/C每次earnings后强制执行）

| Beat类型 | 信号 | 操作 |
|---------|------|------|
| Expansionary | Beat + guidance up | Hold，考虑加仓 |
| Maintenance | Beat + guidance flat | Hold，不加仓 |
| Deteriorating | Beat + guidance down | 减仓50%，设紧止损8% |
| Miss | 任何miss | **当日全出，无例外** |

**这是最重要的出场规则。执行时不带情绪。**

### ABCD下跌分类（止损触发后60秒内完成）

| 类型 | 判别 | 行动 |
|------|------|------|
| A | SPY跌≥2.5%，无个股新闻 | Hold |
| B | 板块轮动，指数稳 | Monitor |
| C | 叙事改变，thesis完整 | 评估 |
| D | 基本面证伪thesis | **当日清仓，无例外** |

**先止损执行，再分类——不是分类完了再决定要不要止损。**

### Round Trip惩罚（美股版）

同一标的买入→5个交易日内卖出且盈亏<3%：

| 次数 | 后果 |
|------|------|
| 第1次 | 记录daily-review，警告 |
| 第2次 | 下周禁止新建仓 |
| 第3次 | 系统检讨 |

### Mandatory Post-Mortem（止损出场后强制执行）

任何持仓触及止损出场 → 当日必须完成以下流程:

1. **写post-mortem到 `pain_memory.md`**（3个问题，不可省略）:
   - 哪里判断错了？（不是"市场不好"，是我的具体判断错误）
   - 有没有提前出现的信号我忽略了？
   - 下次同类情况的if-then

2. **更新 `conviction_scorecard.json`**:
   `uv run --script scripts/conviction_check.py --post-mortem --ticker {X} --loss-pct {Y} --grade {Z} --pod {W}`

3. **Circuit Breaker自动检查**: 脚本自动判断是否触发YELLOW/RED

4. **如果是A+/A级持仓止损**: 30天内评级权限降级，不可再给A+

**盈利出场流程（5min快速记录）**:
1. `uv run --script scripts/conviction_check.py --win --ticker {X} --gain-pct {Y} --grade {Z}`
2. 记录daily-review: 什么thesis/什么信号做对了（1-2句话）
3. 盈利>20% → 全流程复盘提取可复制pattern到knowledge

**不对称原则**: 止损post-mortem mandatory 30min；盈利记录 5min。痛感>快感。

---

*§6 | V6.1 | 2026-05-27 | 两段式出场（匹配A股v7.0）+ F21 Beat Cycle Exit + ABCD分类 + Round Trip惩罚 + Mandatory Post-Mortem*
