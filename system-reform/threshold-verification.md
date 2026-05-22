# Threshold Verification Report
> Generated: 2026-05-23 | Scope: trading-system-prompts.md vs strategy.md / US_TRADING_SYSTEM_V4.md / conflict_resolution.md / rule_authority.md
> Purpose: Verify every numerical threshold in the prompts against the system docs.

---

## Summary

- Total thresholds checked: 15 categories (30+ individual values)
- Matches: 18
- Mismatches: 5
- Needs clarification (context-dependent): 4
- Critical mismatches (can cause wrong trading behavior): 2

---

## Full Verification Table

| # | Threshold | Prompt Says | System Doc Says | Match? | Source Doc | Action |
|---|-----------|-------------|-----------------|--------|-----------|--------|
| 1a | A股 过热：成交量 | 连续7天成交>3万亿=过热 | 沪市成交>**12000亿**=过热 | **MISMATCH** | strategy.md §3.4.3 B1指标；§1.1 D3；§2.2 触发信号表 | Prompt阈值3万亿是**全市场**（沪深合计），strategy.md用12000亿是**沪市单边**。概念不同，实际数值量级差异极大。需确认prompt用哪种口径——当前prompt会导致从不触发（全市沪深成交很少达3万亿/天）。正确触发应改为"沪市单边>12000亿"或明确注明"全市合计" |
| 1b | A股 过热：连续天数 | 连续7天成交>3万亿 | strategy.md无"连续7天"设定；§2.2触发词是"成交量异常"即触发，无天数门槛 | **MISMATCH** | strategy.md §1.1 D3 / §2.2 | Prompt的"连续7天"条件在system docs中找不到依据。System docs是单日触发，不需要连续7天才行动 |
| 2 | A股 两融：牛市信号 | 两融破2.1万亿=牛市加速 | **两融余额破2.1万亿=牛市加速信号，可适当提高仓位上限至85%** | MATCH | strategy.md §2.2触发信号表 / §3.4.3 B1指标 | 数值一致。Prompt省略了"可适当提高仓位上限至85%"的具体行动，但核心阈值正确 |
| 3 | A股 TMT拥挤度 | TMT成交占比>45%=拥挤 | **TMT板块成交占比>45%=拥挤度过高，即便看多也不加仓** | MATCH | strategy.md §1.1 D3 / §2.2 / §3.4.3 B1指标 | 完全一致 |
| 4 | A股 科创50 ETF赎回 | 科创50 ETF连续6日赎回=机构减仓 | **找不到此规则**。Strategy.md中无"科创50 ETF"赎回信号 | **NOT IN DOCS** | strategy.md全文 | 这条规则在strategy.md中不存在。相关ETF规则只有"北向资金连续5日净流入=外资确认主题（正面）"（§3.4.3 B1），方向和对象均不同。建议删除此条或注明来源 |
| 5 | A股 板块尾声信号 | 板块连涨3日→降仓位 | **板块连续5日无新高→开始分批止盈** | **MISMATCH** | strategy.md §3.4.3 "三阶段操作规则" 尾声期；§2.5 出场规则表 / §3.4.5 | Prompt说"3日"，system docs说"5日"。此外触发动作不同：3日后是"降仓位"，docs是"分批止盈"（更被动）。同一信号在§3.4.3 B2也有提及"同一板块连续3日领涨=过热信号，新进资金收益有限"——但这是**不建新仓**，不是"降现有仓位"。Prompt将B2的"不追新"和§3.4.5的"5日止盈"混淆了 |
| 6a | US 做空单只上限 | 单只≤5% | **单只空头上限5%（$7,500），无例外** | MATCH | US_V4 §5.4 / conflict_resolution.md N2 / rule_authority.md Part 6做空速查 | 完全一致 |
| 6b | US 做空单只金额验证 | （prompt未提$金额） | 5%=$7,500（$150K账户），与最低建仓金额$7,500对齐 | N/A | US_V4 §5.4 | Prompt仅说5%，金额隐含于账户规模。一致 |
| 7 | US 做空止损 | 止损-10%硬规则 | **止损-10%（硬规则），做空没有"等回来"的选项** | MATCH | US_V4 §5.4 / conflict_resolution.md N2 / rule_authority.md Part 6做空速查 | 完全一致。注意还有第二触发：VIX>25立即cover（rule_authority.md C9裁决：立即，非24h内） |
| 8a | US 做空类型胜率：Type 1 | Type 1 ~85%WR | **Type 1: 结构性（~85%WR）** | MATCH | US_V4 §5.2 | 完全一致 |
| 8b | US 做空类型胜率：Type 2 | Type 2 ~75% | **Type 2: 催化剂（~75%）** | MATCH | US_V4 §5.2 | 完全一致 |
| 8c | US 做空类型胜率：Type 3 | Type 3 ~70% | **Type 3: 估值（~70%）** | MATCH | US_V4 §5.2 | 完全一致 |
| 8d | US 做空类型胜率：Type 4 | Type 4 ~60% | **Type 4: 行业ETF Put（~60%）** | MATCH | US_V4 §5.2 | 完全一致 |
| 9 | US 总持仓上限 | 最多9只（6多+3空） | **最多9只（多6+空3）** | MATCH | US_V4 §3.2 / §0 Critical Rule 1 / conflict_resolution.md D12 | 完全一致 |
| 10 | US 单只最低金额 | 单只≥$7,500 | **最低建仓金额$7,500，低于此金额一律拒绝** | MATCH | US_V4 §1.3 / §3.2 / §0 Critical Rule 2 | 完全一致 |
| 11 | US 单板块上限 | 单板块≤35% | **单板块仓位≤35%，当日减仓至限制以内** | MATCH | US_V4 §7.7 / §8.3 / rule_authority.md C21 | 完全一致 |
| 12a | US 现金下限 | 现金≥15% | **现金下限≥15%（$22,500）** | MATCH | US_V4 §3.2 / rule_authority.md C8 / conflict_resolution.md C18 | 完全一致 |
| 12b | US 加仓前现金 | 加仓前≥20% | **加仓前须≥20%（$30,000）** | MATCH | US_V4 §3.2附录速查 | Prompt写"加仓前≥20%"——这条在rule_authority.md C8b裁决中认为是A股专项约束，US_V4正文无此额外要求。但US_V4附录速查写"加仓前现金≥20%（$30K）"，两者实际一致 |
| 13a | Bear case T1阈值 | T1 <15% | strategy.md §4.1: **≤15%**正常建仓（A股）；US_V4附录+conflict_resolution C15裁决: **≤15%** Safe任意（美股） | MATCH | strategy.md §4.1 / US_V4附录速查 / conflict_resolution.md C15 | 完全一致 |
| 13b | Bear case T2阈值 | T2 15-25% | strategy.md A股: **15-25%**需明确止损点；US_V4美股+C15裁决: **15-25%** Elevated最高C级 | **PARTIAL MISMATCH** | strategy.md §4.1 / conflict_resolution.md C15裁决 | T2数值边界一致（15-25%），但触发行动有差异：Prompt说"C级≤8%小仓，催化剂确认后加"——这与docs一致（美股最高C级）。A股动作略有不同（需设止损点，不必降至C级）。总体可接受 |
| 13c | Bear case T3阈值 | T3 25-40% | 美股（US_V4+C15裁决）: **25-35%**仅T级+明确止损；A股（strategy.md）: **25-40%**仅A级+事件驱动+减半 | **MISMATCH（美股）** | US_V4 §3.5快速5项检查 / conflict_resolution.md C15 / rule_authority.md Part 6 Bear case速查 | **关键差异**：Prompt的T3上限是40%，而美股docs的T3上限是35%（>35%=排除）。Prompt把A股门槛(40%)套用到了美股。美股bear case门槛是35%，不是40%。Prompt在美股方向会多容忍5%的downside risk |
| 13d | Bear case T4阈值 | T4 >40% | A股: **>40%**不建仓（硬规则）；美股: **>35%**排除 | **MISMATCH（美股）** | strategy.md §4.1 C5 / US_V4 §0 Critical Rule 4 / conflict_resolution.md C14-C16 | 同13c。Prompt用>40%作为T4（不建仓），这是A股规则。美股的硬排除门槛是>35%。在美股语境下，35%-40%区间（prompt允许进入"观察池"）应该是排除（>35%=Extreme）。这是一个会导致美股过多建仓的错误 |
| 14a | ABCD分类：A类阈值（A股） | A类：参考指数同步跌→Hold（无%）| strategy.md: **沪深300同步跌≥1.5%**→A类Hold | **INCOMPLETE** | strategy.md §5.2 / §0 C3 | Prompt的A类描述为"参考指数同步跌"，缺少1.5%量化阈值。会造成判断模糊——跌多少才算"同步跌"？需补充"≥1.5%"量化标准 |
| 14b | ABCD分类：A类阈值（美股） | （prompt未区分美股） | US_V4 §9.1: **SPY/SOX/KWEB跌≥2.5%**→A类Hold | **MISSING** | US_V4 §9.1 / 附录ABCD速查 | Prompt的共享规则部分ABCD只写了一套，未区分A股（1.5%）和美股（2.5%）的不同阈值。这是一个重要的市场差异——美股A类阈值更高，因为美股波动率天然更高，1.5%在美股是正常噪音 |
| 14c | ABCD B类 | B类：指数稳/涨+无新闻+跌<3%→Hold 1-2天 | **完全一致** | MATCH | strategy.md §5.2 B类 / US_V4 §9.1 B类 | 两市场B类阈值相同（<3%），Hold时间相同（1-2天） |
| 14d | ABCD C类 | C类：有新闻但不涉及核心thesis→评估减仓 | **完全一致** | MATCH | strategy.md §5.2 / US_V4 §9.1 | 一致 |
| 14e | ABCD D类 | D类：硬数据证伪thesis→48h内清仓 | **完全一致** | MATCH | strategy.md §5.2 / US_V4 §9.1 | 一致 |
| 15a | Conviction A级仓位 | A≤25% | A股A级: **≤25%**；美股A级: **≤15%** | **MISMATCH（美股）** | strategy.md §3.1 / US_V4 §3.1 / conflict_resolution.md C5 / rule_authority.md C2 | Prompt写A≤25%是A股规则。美股A级上限是15%，不是25%。在美股上下文中用25%会严重超配——差10个百分点 |
| 15b | Conviction B级仓位 | B≤15% | A股B级: **≤15%**；美股B级: **≤10%** | **MISMATCH（美股）** | strategy.md §3.1 / US_V4 §3.1 / conflict_resolution.md C2 / rule_authority.md C2 | 同15a逻辑。Prompt的B≤15%是A股规则，美股B级上限是10% |
| 15c | Conviction C级仓位 | C≤8% | A股C级: **≤8%**；美股C级: **≤8%** | MATCH | strategy.md §3.1 / US_V4 §1.3 | 两市场C级一致 |

---

## Critical Issues (Must Fix)

以下5个错误会直接导致错误的交易行为，按优先级排序：

### Issue 1 [CRITICAL] — Conviction sizing在美股上下文用A股数字
**问题**: 共享铁律中"A≤25%, B≤15%"是A股规则，在美股session中执行会导致超配
**正确值**:
- 美股: A≤15%, B≤10%, C≤8%
- A股: A≤25%, B≤15%, C≤8%
**影响**: 美股A级标的最多建15%但prompt允许25%——差10pp，相当于$15K超配

### Issue 2 [CRITICAL] — Bear case T3/T4在美股上下文用A股门槛
**问题**: 美股排除门槛是>35%，但prompt的T3写25-40%（观察池），T4写>40%（排除），用的是A股标准
**正确值**:
- 美股: T3=25-35%（仅T级+止损）；T4=**>35%**（排除）
- A股: T3=25-40%（仅A级+事件驱动+减半）；T4=**>40%**（排除）
**影响**: 美股bearer case 35%-40%区间，prompt会放入"观察池"，docs要求"排除"。少了5pp的保护

### Issue 3 [MEDIUM] — A股过热成交量阈值概念不一致
**问题**: Prompt写"连续7天成交>3万亿"，strategy.md写"沪市单边>12000亿"单日触发
**正确值**: 沪市成交>12000亿（单日，不需要连续7天）
**影响**: 若按"全市合计3万亿"，阈值过高几乎永不触发；若理解为沪市12000亿，则"连续7天"条件多余且延迟触发

### Issue 4 [MEDIUM] — 板块尾声信号天数不对
**问题**: Prompt写"板块连涨3日→降仓位"，docs写"板块连续**5**日无新高→分批止盈"
**正确值**: 连续5日无新高触发分批止盈（不是连涨3日降仓位）
**影响**: 提前2天出场，且动作不同（"降仓位"vs"分批止盈"——前者更主动）

### Issue 5 [MEDIUM] — ABCD分类A类阈值缺失/混用
**问题**: 共享prompt未区分A股（≥1.5%）和美股（≥2.5%）的A类触发阈值
**正确值**: A股A类触发=沪深300跌≥1.5%；美股A类触发=SPY/SOX/KWEB跌≥2.5%
**影响**: 在美股session用1.5%触发A类会导致正常波动被误判为系统性下跌（Hold而不是评估减仓）

---

## Items Not Found in System Docs

| Threshold | Prompt | Verdict |
|-----------|--------|---------|
| 科创50 ETF连续6日赎回=机构减仓 | Prompt写了此规则 | **在strategy.md和US_V4全文中均找不到对应规则**。最近的规则是"北向资金连续5日净流入=外资确认主题"，方向（流入vs流出）、对象（科创50 ETF vs 北向）、天数（6 vs 5）均不同。来源待确认，建议删除或注明独立来源 |

---

## What Matches Correctly

以下所有数值在prompt和system docs中完全一致，无需修改：

- 两融2.1万亿牛市信号 ✓
- TMT占比>45%拥挤 ✓  
- US 做空单只≤5% ✓
- US 做空止损-10%硬规则 ✓
- US Type 1~85% / Type 2~75% / Type 3~70% / Type 4~60% ✓
- US 最多9只（6多+3空）✓
- US 单只≥$7,500 ✓
- US 单板块≤35% ✓
- US 现金≥15%（加仓前≥20%）✓
- Bear case T1 <15% ✓
- ABCD B类跌<3% ✓
- ABCD C类有新闻但thesis未破 ✓
- ABCD D类48h内清仓 ✓
- Conviction C级≤8% ✓
- L10-L15行为铁律（无数值，逻辑一致）✓

---

## Recommended Fixes to Prompts

### A股大脑 Prompt 过热信号部分

```
当前（错误）:
- 连续7天成交>3万亿=过热
- 板块连涨3日→降仓位

修改为:
- 沪市成交>12000亿（单日）=过热，减仓不追新仓
- 沪市成交<8000亿（单日）=冷市，守底仓不建仓  
- 板块连续5日无新高=尾声信号，开始分批止盈

删除（无依据）:
- 科创50 ETF连续6日赎回=机构减仓
```

### 共享铁律 Prompt Conviction等级部分

```
当前（混用A股/美股）:
A级（能讲清3层逻辑）→ ≤25%
B级（1-2层逻辑）→ ≤15%
C级（直觉+单一数据点）→ ≤8%

修改为（明确区分市场）:
A级（能讲清3层逻辑）:
  → A股: ≤25% | 美股: ≤15%
B级（1-2层逻辑）:
  → A股: ≤15% | 美股: ≤10%
C级（直觉+单一数据点）→ ≤8%（两市场一致）
```

### 共享铁律 Prompt ABCD分类部分

```
当前（缺少量化阈值且未区分市场）:
A类：参考指数同步跌 → Hold

修改为:
A类（系统性下跌）:
  → A股: 沪深300跌≥1.5%且无个股新闻 → Hold
  → 美股: SPY/SOX/KWEB跌≥2.5%且无个股新闻 → Hold
```

### 美股大脑 Prompt Bear case 4-tier部分

```
当前（用A股门槛）:
T3 25-40%：事件驱动短期，不拿过催化日期
T4 >40%：不建仓

修改为（美股专用门槛）:
T3 25-35%：仅T级试仓+明确止损，不拿过催化日期
T4 >35%：排除做多
```

---

*文件依据: /tmp/trading-system-prompts.md / strategy.md v6.1 / US_TRADING_SYSTEM_V4.md v4.1 / conflict_resolution.md / rule_authority.md v1.0*
*审查日期: 2026-05-23*
