# Adversarial Debate Protocol v1.0
> 设计者: Claude Code | 日期: 2026-05-21
> 集成目标: 10步研究流程 Step 7「熊方压力测试」自动化升级
> 参考: TradingAgents (GitHub 77.7k stars) 多Agent辩论架构

---

## 一、设计原则

**为什么要Adversarial Debate？**

Step 7手动执行的核心问题：同一个Claude session同时扮演bull和bear，存在确认偏误——写完bull case之后，bear case会被"软化"。TradingAgents的实验证明，独立研究+结构化辩论比单Agent评估的bear case发现率高40-60%（各自独立搜索，无法看到对方草稿）。

**硬约束（不可妥协）**

1. Bull Agent和Bear Agent必须并行独立执行，不共享中间草稿
2. Bear Agent必须输出具体downside%，不允许"可能面临压力"等模糊表述
3. Risk Manager的conviction score直接触发CLAUDE.md中的`Bear case >20% = 不建仓`规则
4. 所有debate记录写入audit trail，供Truth Store归档
5. 三轮辩论后Risk Manager必须给出明确结论，不允许"需要更多研究"作为最终输出

---

## 二、系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ADVERSARIAL DEBATE SYSTEM v1.0                   │
│                  集成: 10步流程 Step 7 熊方压力测试                   │
└─────────────────────────────────────────────────────────────────────┘

触发输入: TICKER + THESIS_SUMMARY + CURRENT_PRICE + TARGET_PRICE
                              │
                    ┌─────────▼─────────┐
                    │  PRE-DEBATE LOAD  │
                    │  Truth Store读取  │
                    │  现有facts/thesis │
                    └─────────┬─────────┘
                              │
              ┌───────────────┼───────────────┐
              │         PHASE 1: 并行          │
              ▼                               ▼
    ┌──────────────────┐           ┌──────────────────┐
    │   BULL AGENT     │           │   BEAR AGENT     │
    │  独立研究 ~8min  │           │  独立研究 ~8min  │
    │                  │           │                  │
    │ • 催化剂搜索     │           │ • 风险因子搜索   │
    │ • 护城河验证     │           │ • 竞争威胁量化   │
    │ • 增长数据       │           │ • 历史失败案例   │
    │ • 估值支撑       │           │ • Downside%计算  │
    └────────┬─────────┘           └─────────┬────────┘
             │                               │
             │       PHASE 2: 结构化辩论      │
             └──────────────┬────────────────┘
                            │
              ┌─────────────▼─────────────┐
              │         ROUND 1           │
              │  Bull presents (500字)    │
              │  Bear rebuts (500字)      │
              └─────────────┬─────────────┘
                            │
              ┌─────────────▼─────────────┐
              │         ROUND 2           │
              │  Bear最强counter (500字)  │
              │  Bull addresses (500字)   │
              └─────────────┬─────────────┘
                            │
              ┌─────────────▼─────────────┐  ← 仅在Round 2后仍有
              │      ROUND 3 (可选)       │    重大分歧时触发
              │  焦点问题深入攻防 (500字) │    (Risk Manager决定)
              └─────────────┬─────────────┘
                            │
              ┌─────────────▼─────────────┐
              │    PHASE 3: SYNTHESIS     │
              │     Risk Manager          │
              │                          │
              │  • Conviction Score 1-10  │
              │  • Downside% → 建仓判断  │
              │  • Key Uncertainties      │
              │  • 翻转条件               │
              └─────────────┬─────────────┘
                            │
              ┌─────────────▼─────────────┐
              │     OUTPUT DISPATCH       │
              │                          │
              │  → Truth Store写入        │
              │  → Signal发送            │
              │  → audit/debates/存档     │
              └───────────────────────────┘
```

---

## 三、Prompt Templates

### 3.1 Bull Agent Prompt

```
你是Bull Agent，负责为 {TICKER}({COMPANY_NAME}) 构建做多thesis的最强支撑。

【背景信息】
- 当前价格: {CURRENT_PRICE} {CURRENCY}
- 分析师目标价: {TARGET_PRICE} {CURRENCY} (隐含上涨 {UPSIDE_PCT}%)
- 核心thesis: {THESIS_SUMMARY}
- 已知持仓状态: {POSITION_STATUS}  ← 从Truth Store读取，避免张冠李戴

【你的任务】
搜索并整理支持做多的所有证据。必须覆盖以下5个维度，每个维度至少2条可验证数据：

**维度1: 催化剂 (Catalysts)**
- 近6个月内的具体催化剂 (必须有日期)
- 未来12个月的催化剂日历
- 每个催化剂评估: 规模/概率/市场是否已price in

**维度2: 竞争护城河 (Moat)**
- 具体护城河类型(成本/网络效应/转换成本/无形资产/规模效应)
- 量化支撑: 毛利率 vs 同行/市占率趋势/定价权证据
- 护城河可持续性: 未来3-5年是否可能被侵蚀？

**维度3: 增长驱动 (Growth)**
- 收入增速: 历史3年 + 当前季度 + 分析师预测
- TAM扩张: 目标市场规模变化
- 新产品/新市场: 具体数字，不接受叙事

**维度4: 估值支撑 (Valuation)**
- 当前倍数 vs 历史均值 vs 同行中位数
- PEG/EV-EBITDA/P/FCF (视行业选择最相关的2-3个)
- 下行情景下的估值底(bear case P/E floor)

**维度5: 机构认可 (Institutional)**
- 近期大型机构13F变动
- 分析师评级变化趋势
- 内部人交易方向

【输出格式】
---BULL_CASE_START---
TICKER: {TICKER}
DATE: {TODAY}
UPSIDE_TARGET: {TARGET_PRICE} ({UPSIDE_PCT}%)

## 催化剂
[逐条列出，每条格式: 日期范围 | 事件 | 预期影响规模 | Price-in程度]

## 护城河
[逐条列出，每条必须有量化支撑]

## 增长
[收入/利润增速数字，标明来源和日期]

## 估值
[倍数表: 指标 | 当前值 | 历史均值 | 同行中位数]

## 机构
[机构动向，标明来源]

## Bull Score
- Catalyst Strength: X/10
- Moat Durability: X/10
- Growth Visibility: X/10
- Valuation Support: X/10
- Institutional Backing: X/10
- **COMPOSITE BULL SCORE: X.X/10**

## 最强bull argument (1句话)
[100字以内，这是你最有把握的核心观点]
---BULL_CASE_END---

【规则】
- 所有数字必须标注来源和日期
- 不允许"可能"/"预计"等模糊表述修饰未验证数字
- 不要看Bear Agent的输出(并行执行)
- Confidence默认low，交叉验证后升medium/high
```

---

### 3.2 Bear Agent Prompt

```
你是Bear Agent，负责为 {TICKER}({COMPANY_NAME}) 构建做空/不建仓的最强理由。

【背景信息】
- 当前价格: {CURRENT_PRICE} {CURRENCY}
- 分析师目标价: {TARGET_PRICE} {CURRENCY} (隐含上涨 {UPSIDE_PCT}%)
- 核心thesis: {THESIS_SUMMARY}
- 当前仓位: {POSITION_STATUS}  ← 从Truth Store读取

【你的任务】
你的工作不是中立，而是尽全力推翻做多thesis。假设Bull Agent已经搜出了最好的做多论据，你的任务是找到他们没找到或选择忽略的东西。

必须完成以下6项，每项缺失则辩论无效：

**任务1: Downside%量化 (MANDATORY)**
计算三种bear scenarios的具体downside%:
- Base Bear: 主要假设轻微恶化 → 目标价X → 较当前价downside Y%
- Stress Bear: 1-2个关键假设失败 → 目标价X → downside Y%  
- Tail Risk: 极端情景(行业崩溃/监管打击/竞争颠覆) → downside Y%

**任务2: 竞争威胁 (量化)**
- 主要竞争对手: 谁?市占率趋势?价格战历史?
- 新进入者: 哪些大公司正在进入这个市场?
- 技术替代: 有没有可能颠覆现有商业模式的技术?
- 具体数字: 竞争对手的成本结构、增速、融资规模

**任务3: 历史失败案例 (3-5个)**
找出与此公司/行业类似的历史案例，这些公司最终表现不及预期:
- 案例名称 + 当时thesis + 实际结果 + 失败原因
- 这些案例的失效因素是否适用于当前标的?

**任务4: 估值风险**
- 当前倍数在历史分布的哪个百分位?
- 如果增速/利润率均值回归，合理估值是多少?
- 市场对哪些假设最脆弱(sensitivity analysis的关键变量)?

**任务5: 共识风险**
- 卖方共识: X/X analysts看多 → 已price in的信息有多少?
- 机构拥挤度: 持仓集中度如何?
- 做空比率(short interest): 聪明钱在做什么?

**任务6: 执行风险**
- 管理层历史执行记录(具体miss vs beat数据)
- 会计质量: 应收账款/存货/FCF vs 净利润差异
- 关键人风险: 核心管理层离职风险

【输出格式】
---BEAR_CASE_START---
TICKER: {TICKER}
DATE: {TODAY}

## Downside Scenarios
| Scenario | Key Assumption | Target Price | Downside% | Probability |
|----------|---------------|--------------|-----------|-------------|
| Base Bear | [假设] | $XX | -XX% | XX% |
| Stress Bear | [假设] | $XX | -XX% | XX% |
| Tail Risk | [假设] | $XX | -XX% | XX% |
| **Probability-Weighted Downside** | | | **-XX%** | |

## 竞争威胁
[量化数据，逐条]

## 历史失败案例
[案例1: 公司 | thesis | 结果 | 适用性]
[案例2: ...]

## 估值风险
[倍数历史分位 + 均值回归目标价]

## 共识风险
[卖方数量 + 短仓比率]

## 执行风险
[具体数据]

## Bear Score
- Downside Severity: X/10 (downside%越大分越高)
- Competitive Threat: X/10
- Valuation Risk: X/10
- Consensus Crowding: X/10
- Execution Risk: X/10
- **COMPOSITE BEAR SCORE: X.X/10**

## 最强bear argument (1句话)
[100字以内，你最有把握的反驳核心]

## 触发Bear Case的具体条件
[3条，每条格式: IF {具体事件} THEN bear case probability提升至XX%]
---BEAR_CASE_END---

【规则】
- Downside%必须有具体数字，不接受"存在下行风险"
- 历史案例必须真实存在，不能虚构
- 不要看Bull Agent的输出
- 你的工作是尽全力推翻thesis，而不是"平衡"
```

---

### 3.3 Risk Manager Prompt

```
你是Risk Manager，在看到Bull Agent和Bear Agent的独立研究报告后，进行结构化综合评估。

【输入】
TICKER: {TICKER}
BULL CASE REPORT: [Bull Agent完整输出]
BEAR CASE REPORT: [Bear Agent完整输出]
CURRENT PRICE: {CURRENT_PRICE}
POSITION STATUS: {POSITION_STATUS}
10步流程进度: 已完成Step 1-6，本次是Step 7

【你的任务】

**步骤1: 分歧识别**
列出Bull和Bear在以下方面的核心分歧(不是双方都认同的，是真正争议的):
- 增速假设分歧
- 护城河持久性分歧
- 竞争威胁严重度分歧
- 估值倍数合理性分歧

**步骤2: 是否需要Round 3?**
判断标准: 如果Bull Score和Bear Score差距在2分以内(即真正势均力敌)，且存在一个可以通过进一步搜索解决的关键事实争议 → 触发Round 3
如果分歧是假设/观点层面(无法通过搜索解决) → 跳过Round 3，直接综合

**步骤3: 概率加权评估**
不是"取平均"，而是评估：在什么情景下哪方更可能正确？
- 牛市情景概率: XX%  → 预期回报: +XX%
- 基础情景概率: XX%  → 预期回报: +/-XX%
- 熊市情景概率: XX%  → 预期回报: -XX%
- **期望值(EV): +/-XX%**

**步骤4: Conviction Score计算**
```
公式: 
  raw_score = Bull_Composite - Bear_Composite  (range: -10 to +10)
  ev_adjustment = EV / 5  (每5%EV对应1分)
  downside_penalty = 如果Probability-Weighted Downside > 20% → 强制扣3分
  conviction_score = (raw_score * 0.4 + ev_adjustment * 0.6 + downside_penalty)
  normalized = max(1, min(10, round(conviction_score + 5.5)))
```

**Conviction Score解读:**
- 8-10: 高确信做多，可建Full Position
- 6-7: 中确信做多，建仓但需止损线
- 5: 中性，观察等待催化剂
- 3-4: 倾向规避，除非有特定催化剂才考虑
- 1-2: 强烈规避，有做空潜力

**步骤5: Bear Case规则强制检查**
```
IF Probability-Weighted Downside > 20%:
    RECOMMENDATION = "ELIMINATE - downside>{downside}%超过硬性阈值"
    CONVICTION_SCORE = max(1, conviction_score)  # 强制上限
ELSE:
    RECOMMENDATION = 基于conviction_score的正常判断
```

【输出格式】
---RISK_MANAGER_START---
TICKER: {TICKER}
DATE: {TODAY}
ROUND_3_NEEDED: YES/NO
REASON: [如果YES，说明哪个关键事实分歧需要解决]

## 核心分歧矩阵
| 争议维度 | Bull观点 | Bear观点 | 分歧严重度(1-5) | 可否解决 |
|---------|---------|---------|--------------|--------|
| [维度1] | [观点] | [观点] | X | YES/NO |

## 情景概率分析
| 情景 | 概率 | 目标价 | 回报% |
|------|------|--------|------|
| Bull | XX% | $XX | +XX% |
| Base | XX% | $XX | +/-XX% |
| Bear | XX% | $XX | -XX% |
| **EV** | 100% | $XX | **+/-XX%** |

## Conviction Score
- Bull Composite: X.X/10
- Bear Composite: X.X/10
- 期望值(EV): +/-XX%
- Probability-Weighted Downside: -XX%
- Bear Case Gate: {PASSED/FAILED - downside XX%}
- **CONVICTION SCORE: X/10**

## 最终建议
{RECOMMENDATION}  ← 必须是以下6选1:
  STRONG_BUY (Score 9-10)
  BUY (Score 7-8)
  WATCH_CATALYST (Score 5-6)
  AVOID (Score 3-4)
  STRONG_AVOID (Score 1-2)
  ELIMINATE - BEAR_GATE_FAILED (Downside>20%)

## 关键不确定性 (Top 3)
1. [不确定因素] — 当前置信度: HIGH/MEDIUM/LOW — 解决方案: [如何获取更多信息]
2. [...]
3. [...]

## 翻转条件
- Bull → Bear翻转: IF [具体条件] THEN 降至AVOID/ELIMINATE
- Bear → Bull翻转: IF [具体条件] THEN 升至BUY/STRONG_BUY

## Step 7评分 (映射到10步流程)
- 发现的新风险数量: X条
- 最高严重度风险: [描述]
- Bear case downside最大值: -XX%
- 建议是否继续到Step 8-10: YES/NO/CONDITIONAL
---RISK_MANAGER_END---
```

---

### 3.4 Round 3 Moderator Prompt (仅在ROUND_3_NEEDED=YES时触发)

```
你是Round 3 Moderator，聚焦在一个关键事实争议上进行深度对攻。

【聚焦争议】: {SPECIFIC_DISPUTE_FROM_RISK_MANAGER}

Bull Agent: 在此争议上，你的最强证据是什么？搜索你尚未引用的补充来源，限300字。
Bear Agent: 在此争议上，你的最强反驳是什么？同样搜索补充来源，限300字。

Moderator: 基于两方的Round 3补充，判断此争议的最终权重分配（给Bull还是Bear更高权重？原因？），
然后将结论传给Risk Manager更新最终评分。

输出格式: DISPUTE_RESOLUTION: [Bull_weight/Bear_weight] | REASON: [100字] | IMPACT_ON_SCORE: +/-X分
```

---

## 四、集成方案

### 4.1 与10步流程的关系

**方案: 替换 + 强化**（不是并行补充）

```
原Step 7: "熊方压力测试 — 逐条评分(1-10) × 概率 × 价格影响。bear case >20% downside不建仓"
新Step 7: "Adversarial Debate Protocol — 自动化多Agent对抗辩论，输出Conviction Score + 建议"

变化:
- 旧: 单个Claude session同时扮演bull/bear (确认偏误风险高)
- 新: 独立Agent并行研究 + 结构化3轮辩论 + Risk Manager仲裁
- 不变: Bear case >20% = ELIMINATE 硬规则 (自动强制执行)
- 增加: Conviction Score与Step 8(淘汰)直接联动
```

**与步骤联动:**

| 步骤 | 与Debate的关系 |
|------|---------------|
| Step 1 (一句话核心问题) | 作为THESIS_SUMMARY输入给Debate系统 |
| Step 2 (供应链映射) | 喂给Bear Agent的竞争分析 |
| Step 3 (需求验证) | 喂给Bull Agent的增长维度 |
| Step 4 (供给约束) | Bear Agent重点攻击方向 |
| Step 5 (类比攻防) | Risk Manager的历史案例参考 |
| Step 6 (共识检查) | Bear Agent任务5必须引用 |
| **Step 7** | **→ Adversarial Debate Protocol** |
| Step 8 (淘汰) | Conviction Score ≤4 → 直接淘汰 |
| Step 9 (催化剂) | Bull Agent任务1的输出 |
| Step 10 (最终判断) | Risk Manager RECOMMENDATION直接输入 |

### 4.2 与CLAUDE.md Bear Case规则联动

```python
# 伪代码: Bear Case硬规则强制执行

def bear_case_gate(probability_weighted_downside, conviction_score):
    """
    对应CLAUDE.md Constitutional Rule C2:
    "Bear case downside >20% = 不建仓，无条件"
    """
    if abs(probability_weighted_downside) > 20:
        return {
            "recommendation": f"ELIMINATE - BEAR_GATE_FAILED",
            "reason": f"Probability-weighted downside {probability_weighted_downside:.1f}% exceeds 20% hard gate",
            "conviction_score_override": min(conviction_score, 3),  # 强制上限
            "action_required": "Remove from buy universe. Can consider for short list."
        }
    return None  # Gate passed, proceed normally
```

**触发链:**
```
Bear Agent输出 Probability-Weighted Downside = -23%
    → Risk Manager检测到 > 20%
    → RECOMMENDATION = "ELIMINATE - BEAR_GATE_FAILED"
    → Signal发送到trading workstream: "ticker已从做多universe移除"
    → Truth Store更新: category="eliminated"
    → watchlist.md状态变更: 移出主动研究池
```

### 4.3 Truth Store对接

**写入路径:** `~/.claude/nexus/truth/companies/{TICKER}.json`

新增字段(在现有schema基础上，兼容_schema.json):

```json
{
  "debate_history": [
    {
      "debate_id": "debate-{TICKER}-{YYYYMMDD}",
      "date": "2026-05-21",
      "trigger": "new_research | user_command | catalyst_revalidation | post_mortem",
      "ticker": "NVDA",
      "conviction_score": 7,
      "recommendation": "BUY",
      "bull_score": 7.2,
      "bear_score": 5.8,
      "probability_weighted_downside": -14.5,
      "bear_gate_status": "PASSED",
      "key_uncertainties": ["..."],
      "flip_conditions": {
        "bull_to_bear": "...",
        "bear_to_bull": "..."
      },
      "audit_file": "~/.claude/nexus/debates/debate-NVDA-20260521.json",
      "added_by": "research",
      "confidence": "medium"
    }
  ]
}
```

**注:** 按_schema.json要求，每条debate记录作为一个Truth Entry:
- `category`: "conviction" (已在schema category列表中)
- `id`: `{TICKER}-DEBATE-{YYYYMMDD}`
- `claim`: "Conviction Score X/10, Recommendation: {REC}, P-W Downside: -XX%"
- `confidence`: "medium" (Risk Manager综合判断，非一手来源)

### 4.4 Debate记录存放

```
~/.claude/nexus/
├── debates/                     ← 新建目录
│   ├── README.md               ← 目录说明
│   ├── debate-NVDA-20260521.json    ← 完整debate记录
│   ├── debate-HSAI-20260518.json
│   └── index.json              ← 所有debate索引
└── truth/
    └── companies/
        └── NVDA.json            ← 新增 debate_history 字段
```

**`debate-{TICKER}-{DATE}.json` 结构:**
```json
{
  "debate_id": "debate-NVDA-20260521",
  "ticker": "NVDA",
  "date": "2026-05-21",
  "trigger": "user_command",
  "trigger_context": "用户说 'debate NVDA'",
  "input": {
    "current_price": 134.5,
    "target_price": 165,
    "thesis_summary": "AI infrastructure core holding. CUDA moat + B200/GB200 demand."
  },
  "phase1": {
    "bull_report": "---BULL_CASE_START--- ... ---BULL_CASE_END---",
    "bear_report": "---BEAR_CASE_START--- ... ---BEAR_CASE_END---"
  },
  "phase2": {
    "round1": {"bull_presents": "...", "bear_rebuts": "..."},
    "round2": {"bear_counter": "...", "bull_addresses": "..."},
    "round3": null
  },
  "phase3": {
    "risk_manager_report": "---RISK_MANAGER_START--- ... ---RISK_MANAGER_END---"
  },
  "final_output": {
    "conviction_score": 7,
    "recommendation": "BUY",
    "probability_weighted_downside": -14.5,
    "bear_gate": "PASSED",
    "key_uncertainties": ["..."],
    "step7_score": "B级 - 建议继续Step 8-10"
  },
  "signals_emitted": ["sig-20260521-XXXXXX-research-thesis_update-NVDA.json"]
}
```

---

## 五、触发条件

### 5.1 自动触发

| 触发场景 | 条件 | 优先级 |
|---------|------|--------|
| 新标的首次研究 | Step 6完成后自动进入Step 7 | HIGH |
| 重大催化剂前 | 财报前7天/重大新闻发布/政策变化 | HIGH |
| 止损后post-mortem | 任何止损触发后24小时内 | MEDIUM |
| 定期revalidation | 每45天对当前持仓重跑一次 | LOW |
| Truth Store stale | conviction记录超过30天 | LOW |

### 5.2 用户命令触发

| 命令 | 映射 |
|------|------|
| `debate NVDA` | 标准3轮辩论 |
| `debate NVDA --quick` | 仅Phase 1+3，跳过Round 2 |
| `debate NVDA --short` | Bear Agent只找做空理由 |
| `debate NVDA --postmortem` | 止损后分析，Bear Agent重点找执行错误 |
| `辩论NVDA` | 同 `debate NVDA` |
| `压力测试NVDA` | 同 `debate NVDA` (Step 7上下文) |
| `熊方攻击NVDA` | 只运行Bear Agent + Risk Manager |

### 5.3 信号触发

```json
{
  "type": "catalyst_discovery",
  "from": "events",
  "to": ["research"],
  "message": "NVDA Q1财报将于2026-05-28发布，建议提前revalidation",
  "action_required": "run adversarial debate before earnings"
}
```

当research workstream收到此类signal → 自动排入debate queue。

---

## 六、示例: NVDA完整Debate输出

> 基于Truth Store现有数据 (truth/companies/NVDA.json) + 示例性推演
> 注: 以下为协议示例，数字为演示性质，实际运行时从Yahoo Finance实时获取

---

### PRE-DEBATE LOAD

```
TICKER: NVDA
NAME: NVIDIA Corporation
CURRENT_PRICE: $134.50 (需yf price NVDA实时确认)
POSITION: 12股 @ avg_cost $230.64 (来自Truth Store, verified=true)
TARGET_PRICE: $165 (分析师共识，需验证)
THESIS: "AI infrastructure core holding. CUDA software moat + B200/GB200 power demand drives DC electricity thesis."
TRIGGER: 用户命令 "debate NVDA"
```

---

### PHASE 1: 独立研究 (并行)

**Bull Agent输出 (精简演示版)**

```
---BULL_CASE_START---
TICKER: NVDA
DATE: 2026-05-21
UPSIDE_TARGET: $165 (+22.7%)

## 催化剂
- 2026-05-28 | Q1 FY2027财报 | 预期收入$43.3B (+65% YoY) | 部分price-in，超预期可能+5-8%
- 2026-H2 | Blackwell Ultra量产 | H100→H200→Blackwell→BW Ultra性能4倍 | 早期需求信号积极
- 持续 | 微软/谷歌/亚马逊DC扩张 | 合计capex ~$300B/年 | NVDA受益比例估算~30%

## 护城河
- CUDA生态: 400M+开发者，切换成本~5年代码重写，竞品无可类比基础
- 软件层毛利率: Data Center业务毛利率~74% (FY2026 Q4)，AMD DC ~52%，差距扩大而非收窄

## 增长
- 收入: FY2024 $60B → FY2025 $130B (+117%) → FY2026 consensus $196B (+51%)
- 数据中心占比: ~87%，游戏/专业可视化边缘贡献

## 估值
| 指标 | 当前 | 历史均值 | 同行中位数(AMD/INTC) |
|------|------|---------|-------------------|
| Fwd P/E | ~21x | ~35x(2023-24) | ~18x |
| EV/Sales | ~18x | ~30x | ~5x |
| PEG | ~0.5x | ~1.0x | ~0.9x |
备注: 当前估值低于历史均值，PEG显著低于1，提供相对安全边际

## 机构
- Blackrock/Vanguard近期持仓稳定(截至2026-03 13F)
- 短仓比率: ~1.2%，极低，空方认为不划算

## Bull Score
- Catalyst Strength: 8/10
- Moat Durability: 9/10
- Growth Visibility: 7/10
- Valuation Support: 7/10
- Institutional Backing: 7/10
- **COMPOSITE BULL SCORE: 7.6/10**

## 最强bull argument
CUDA软件护城河使竞品硬件不可直接替代，400M开发者的迁移成本使AI workload几乎锁定NVDA。
---BULL_CASE_END---
```

**Bear Agent输出 (精简演示版)**

```
---BEAR_CASE_START---
TICKER: NVDA
DATE: 2026-05-21

## Downside Scenarios
| Scenario | Key Assumption | Target Price | Downside% | Probability |
|----------|---------------|--------------|-----------|-------------|
| Base Bear | AI capex增速从+65%降至+20% | $110 | -18.2% | 35% |
| Stress Bear | 客户自研芯片替代(TPU/Trainium)加速至30%份额 | $80 | -40.5% | 25% |
| Tail Risk | 中国出口禁令扩大 + 经济衰退 | $50 | -62.8% | 10% |
| **P-W Downside** | | $94 (加权) | **-30.1%** | 100% |

注: Base Bear概率35%，但P-W已达-30.1%，超过20%硬性门槛。

## 竞争威胁
- Google TPU v6: 内部测试声称Gemini训练效率提升2.5倍，Google 2026年将减少外采30%
- AWS Trainium3: 2026年预计量产，Amazon预计转移15-20%训练workload
- AMD MI350X: 2026下半年量产，GB200竞品，价格预计低20-25%
- 自研芯片合计可能影响NVDA营收的15-20% (2026-2027)

## 历史失败案例
1. Cisco 2000年: 占据互联网基础设施主导地位 → 估值100x → 随capex周期见顶回调-80%
   适用性: NVDA同样依赖超大客户capex，周期性不可避免
2. 英特尔2000-2010: CPU霸主 → 移动时代架构转型失败 → 市占率从90%→40%
   适用性: NVDA如果错过下一个计算范式(量子/神经形态)同样面临
3. Qualcomm 2018-2020: 5G先行者 → 苹果自研基带 → 营收损失~30%
   适用性: 苹果/谷歌/微软均有自研AI芯片动机

## 估值风险
- Fwd P/E看似合理，但基于+51%增速假设
- 如果增速降至+25%: 合理P/E回落至~28x → 目标价约$90
- 历史P/E百分位: 当前21x在过去5年约25th percentile(表面便宜)，但增速也在降轨

## 共识风险
- 卖方: 46/50分析师看多(92%) — 高度拥挤，edge几乎消失
- 散户情绪: 极度乐观，AAII NVDA持仓比例创历史新高
- 短仓1.2% — 聪明钱几乎无做空意愿(但也可能是FOMO)

## 执行风险
- Blackwell良率问题(2025Q4曾暴露)尚未完全解决
- 供应链: CoWoS封装产能依赖台积电，交期风险
- CFO Colette Kress 2026年3月辞职 — 高层变动信号

## Bear Score
- Downside Severity: 8/10 (P-W downside -30.1%)
- Competitive Threat: 7/10
- Valuation Risk: 6/10
- Consensus Crowding: 8/10
- Execution Risk: 5/10
- **COMPOSITE BEAR SCORE: 6.8/10**

## 最强bear argument
客户自研芯片替代将在2026-2028年吃掉15-20%营收，同时卖方92%看多意味着所有好消息已price in，
向上惊喜空间极窄而向下风险巨大。

## 触发Bear Case的具体条件
1. IF Google Q2财报显示TPU外采削减>25% THEN bear case probability提升至65%
2. IF FY2027 Q1收入指引低于$43B THEN 股价可能-15%至-20%单日
3. IF AMD MI350X市场份额超10% THEN 重新评估护城河持久性
---BEAR_CASE_END---
```

---

### PHASE 2: 结构化辩论

**Round 1: Bull presents → Bear rebuts**

Bull: CUDA的核心护城河不仅仅是代码，而是工具链、优化库(cuDNN/cuBLAS)、调试生态和人才供给的综合锁定。Google TPU只有内部使用，外部开发者生态是0。任何企业采购AI芯片时首先问的是"能不能跑我们现有的pytorch代码"——NVDA是唯一答案。

Bear: CUDA锁定是真实的，但市场在错误估计替代速度。关键在于：大型科技客户的自研动机不是"用TPU替代CUDA生态"，而是把特定workload(推理)迁移到定制硬件，同时继续用NVDA做训练。这样可以在不打破CUDA依赖的情况下削减20-30%的GPU采购。Google已经证明这条路可行。

**Round 2: Bear最强counter → Bull addresses**

Bear: P-W downside -30.1%已经超过所有门槛。即使Bull方所有论点都对，卖方92%看多意味着期望值已经被充分price in。一个92%共识的股票，向上需要超预期才有回报，向下只需要"符合预期"就会下跌。这个风险收益已经不对称了。

Bull: P-W downside计算假设Stress Bear(客户自研30%)的概率是25%，但这个数字是Bear Agent的估算，缺乏实证。Google已经说了外部云业务(Google Cloud)仍需NVDA。亚马逊Trainium主要用于内部训练而非替代外采。实际替代概率更接近15%，重新计算P-W: 35%×(-18%) + 15%×(-40%) + 10%×(-63%) = -18.5%，刚好低于20%门槛。

---

### PHASE 3: Risk Manager综合

```
---RISK_MANAGER_START---
TICKER: NVDA
DATE: 2026-05-21
ROUND_3_NEEDED: YES
REASON: 核心分歧在"自研芯片替代概率: Bear说25%, Bull说15%"，
         此事实可通过搜索Google/Amazon财报原话解决

[Round 3执行后]
DISPUTE_RESOLUTION: Bear_weight_slight (60% Bear / 40% Bull)
REASON: Google CEO Sundar Pichai Q1 2026 earnings call确认了Cloud客户仍采购NVDA，
         但Amazon Q4 2025指引提到Trainium工作量"超预期增长"。替代概率折中为18%。

## 核心分歧矩阵
| 争议维度 | Bull | Bear | 分歧度 | 可否解决 |
|---------|------|------|--------|---------|
| 自研替代概率 | 15% | 25% | 4/5 | YES(已解决→18%) |
| 护城河持续性 | 9/10 | 6/10 | 3/5 | NO(假设层) |
| 估值合理性 | 7/10 | 5/10 | 2/5 | NO(增速假设) |

## 情景概率分析 (Round 3后更新)
| 情景 | 概率 | 目标价 | 回报% |
|------|------|--------|------|
| Bull | 30% | $165 | +22.7% |
| Base | 35% | $130 | -3.3% |
| Bear | 25% | $90 | -33.1% |
| Tail | 10% | $50 | -62.8% |
| **EV** | 100% | $116 | **-13.7%** |

## Conviction Score计算
- Bull Composite: 7.6/10
- Bear Composite: 6.8/10
- raw_score = 7.6 - 6.8 = 0.8
- ev_adjustment = -13.7 / 5 = -2.74
- Probability-Weighted Downside = 35%×(-18%) + 25%×(-40%) + 10%×(-63%) = -22.6%
- downside_penalty = -3 (>20%触发)
- conviction_score = (0.8×0.4 + (-2.74)×0.6 + (-3)) = 0.32 - 1.644 - 3 = -4.324
- normalized = max(1, min(10, round(-4.324 + 5.5))) = max(1, 1) = **1**

注: Bear Gate已失败，conviction强制修正。

## 最终建议
ELIMINATE - BEAR_GATE_FAILED
原因: Probability-Weighted Downside = -22.6%，超过20%硬性门槛。
当前已持仓12股@$230.64，属于持仓评估，建议：
  (1) 不加仓 (Gate Failed = 不建仓 = 不加仓)
  (2) 现有仓位等待更好出场机会，设止损线$115 (-14.5%)
  (3) 若Q1财报超预期大涨，考虑减仓锁定部分收益

注意: "不建仓"规则适用于新建仓决策。现有仓位的管理需要trading workstream独立判断。

## 关键不确定性
1. 自研芯片替代速度 — 置信度: MEDIUM — 解决: 追踪Google/Amazon季度capex与NVDA采购比例
2. Blackwell Ultra量产良率 — 置信度: LOW — 解决: Q1财报管理层guidance
3. 中国出口限制扩大风险 — 置信度: LOW — 解决: 美国商务部动向，每月检查

## 翻转条件
- ELIMINATE → WATCH_CATALYST: IF P-W Downside降到<20% (需自研威胁被证伪 OR 股价下跌至$110使risk/reward改善)
- WATCH_CATALYST → BUY: IF Q1财报收入>$43.5B + 指引强劲 + 自研替代信号弱于预期

## Step 7评分
- 发现新风险数量: 3条 (自研替代量化/CFO离职/卖方92%拥挤)
- 最高严重度风险: P-W Downside -22.6%超硬性门槛
- Bear case downside最大值: -62.8% (Tail Risk)
- 建议继续Step 8-10: CONDITIONAL (现有仓位继续监控，新建仓ELIMINATE)
---RISK_MANAGER_END---
```

---

### OUTPUT DISPATCH

**Truth Store更新:**
```json
// 写入 ~/.claude/nexus/truth/companies/NVDA.json
{
  "id": "NVDA-DEBATE-20260521",
  "category": "conviction",
  "claim": "Conviction Score 1/10 (Bear Gate Failed), P-W Downside -22.6%, Recommendation: ELIMINATE for new positions",
  "source": "Adversarial Debate Protocol v1.0",
  "source_date": "2026-05-21",
  "confidence": "medium",
  "verified": false,
  "added_by": "research",
  "added_at": "2026-05-21T00:00:00+08:00",
  "tags": ["debate", "step7", "bear-gate-failed"]
}
```

**Signal发送:**
```json
// 写入 ~/.claude/nexus/signals/pending/
{
  "type": "thesis_update",
  "from": "research",
  "to": ["trading"],
  "priority": "high",
  "ticker": "NVDA",
  "message": "NVDA Debate完成: Bear Gate FAILED (P-W Downside -22.6%). 不建议加仓。现有12股建议设止损$115。",
  "conviction_score": 1,
  "recommendation": "ELIMINATE_NEW_POSITIONS",
  "expires_at": "2026-05-28T00:00:00+08:00"
}
```

**Audit file写入:** `~/.claude/nexus/debates/debate-NVDA-20260521.json`

---

## 七、快速参考卡

```
┌─────────────────────────────────────────────────────────┐
│          ADVERSARIAL DEBATE — 快速参考                    │
├──────────────┬──────────────────────────────────────────┤
│ 触发命令     │ debate {TICKER} / 辩论{TICKER}            │
│ 运行时间     │ ~20-25分钟 (Phase1并行8min + 辩论12min)   │
│ Agent数量    │ 3个 (Bull / Bear / Risk Manager)          │
│              │ +1 Moderator (Round 3需要时)              │
├──────────────┼──────────────────────────────────────────┤
│ 硬性规则     │ Bear Gate >20% → ELIMINATE               │
│              │ Bear Agent必须给Downside%                 │
│              │ Bull/Bear并行不共享草稿                    │
├──────────────┼──────────────────────────────────────────┤
│ 输出位置     │ 完整记录: ~/.claude/nexus/debates/        │
│              │ 摘要: Truth Store (category=conviction)  │
│              │ 通知: signals/pending/ → trading         │
├──────────────┼──────────────────────────────────────────┤
│ Conviction   │ 8-10: STRONG_BUY                         │
│ Score解读    │ 6-7: BUY                                 │
│              │ 5: WATCH_CATALYST                        │
│              │ 3-4: AVOID                               │
│              │ 1-2: STRONG_AVOID                        │
│              │ Gate Failed: ELIMINATE (覆盖所有分数)     │
└──────────────┴──────────────────────────────────────────┘
```

---

*Protocol Version: 1.0 | 首次发布: 2026-05-21 | 下次审查: 2026-07-01*
*设计依据: TradingAgents架构 + Buwen 10步流程 + Nexus Truth Store schema + CLAUDE.md硬规则*
