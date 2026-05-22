# Rule Authority Hierarchy — Claude模拟盘交易系统
> 版本: 1.0 | 生成: 2026-05-22 | 目的: 消除规则冲突导致的执行瘫痪
> 适用范围: strategy.md (v5.0) / US_TRADING_SYSTEM_V4.md / CLAUDE.md / system-v4/框架文件群

---

## Part 0: 速查 — 规则归属一览

> 遇到冲突时先查这张表，找到规则类别，对应权威文档即为最终裁定。

| 规则类别 | 权威文档 | 说明 |
|---------|---------|------|
| A股仓位上限（S/A/B/C/T级） | **strategy.md §3.1** | A股独有市场结构，strategy.md专项定义 |
| A股板块/现金/持仓数硬约束 | **strategy.md §3.2** | 同上 |
| A股选股框架（五步法/五层信号） | **strategy.md §4.1** | A股方法论权威 |
| A股Bear case分级门槛 | **strategy.md §4.1** | A股专项；美股用US_TRADING_SYSTEM_V4 |
| A股进出场时机规则 | **strategy.md §4.5** | A股专项 |
| A股ABCD下跌分类 | **strategy.md §5.2 / CLAUDE.md** | 两者一致，任一可查 |
| **美股仓位上限（S/A/B/C/T级）** | **US_TRADING_SYSTEM_V4.md §3.1** | v4.0权威；strategy.md旧值已过时 |
| **美股5维度评分体系** | **US_TRADING_SYSTEM_V4.md §1** | 权威评分卡；strategy.md仅摘要参考 |
| **美股Bear case门槛** | **US_TRADING_SYSTEM_V4.md** | 35%排除；strategy.md同步但US系统为准 |
| **美股S级S5条件** | **US_TRADING_SYSTEM_V4.md §1.4** | S5定义不同，US系统的S5"Momentum分≥8"为准 |
| 美股入场时机 | **entry-framework.md** | 详细决策树权威 |
| 美股退出/止损/时间止损 | **exit-framework.md + US_TRADING_SYSTEM_V4.md §4** | 两者一致，以US_V4为准 |
| 美股做空系统（评分/仓位/SOP） | **short-framework.md + US_TRADING_SYSTEM_V4.md §5** | 两者一致；冲突时US_V4为准 |
| 美股Regime Detection | **risk-framework.md + US_TRADING_SYSTEM_V4.md §7** | 两者完全一致 |
| 美股组合级风控阈值（日/周损失） | **US_TRADING_SYSTEM_V4.md §7.7** | 权威；strategy.md §13有不同值（见冲突表） |
| 美股仓位集中度（持仓只数/最低金额） | **US_TRADING_SYSTEM_V4.md §3.2** | 权威 |
| 美股A级止损方式 | **US_TRADING_SYSTEM_V4.md §4.1** | Trailing -12%；position-framework.md有矛盾值 |
| 美股B级止损方式 | **US_TRADING_SYSTEM_V4.md §4.1** | Trailing -10%；position-framework.md有矛盾值 |
| 美股分批锁利规则 | **US_TRADING_SYSTEM_V4.md §4.2** | 目标50%减1/3 / 目标100%再减1/3 |
| 美股时间止损（T/C/B/A/S级） | **US_TRADING_SYSTEM_V4.md §4.4** | 权威；exit-framework.md一致确认 |
| 行为铁律 L1-L18 | **strategy.md §8 + CLAUDE.md** | 运行时强制执行；两者内容一致 |
| 做空评分卡（10分制） | **short-framework.md §二 + US_TRADING_SYSTEM_V4.md §5.3** | 两者一致，均为10分制 |
| 每日4-window执行流程 | **strategy.md §6 = CLAUDE.md** | 两者一致 |
| 期权规则 | **US_TRADING_SYSTEM_V4.md §6** | 唯一来源 |

---

## Part 1: 权威层级声明

### 层级顺序（冲突时按此顺序裁定）

```
Level 1 (最高): 用户实时互动纠偏（280+条feedback，实盘即时纠错）
Level 2: US_TRADING_SYSTEM_V4.md（美股所有规则的权威来源，20-agent重建，v4.0）
Level 3: strategy.md v5.0（A股所有规则的权威来源 + 通用行为铁律）
Level 4: CLAUDE.md（运行时执行层，同步strategy.md，主要作为agent操作手册）
Level 5: system-v4/框架文件群（entry/exit/position/risk/short-framework.md）
          — 这些文件是US_V4的详细展开，与US_V4有冲突时以US_V4为准
          — 框架文件之间互相独立，不互相引用
Level 6 (最低): 回测参考（backtest-reference-2021-2024.md），仅作规则验证，不作规则来源
```

### 市场归属原则

| 规则涉及 | 权威文档 |
|---------|---------|
| 纯A股规则 | strategy.md（A股部分） |
| 纯美股规则 | US_TRADING_SYSTEM_V4.md |
| 美股+A股均有的通用规则（如ABCD分类、行为铁律） | strategy.md（两市通用）|
| 同一规则在美股存在专项规定 | US_TRADING_SYSTEM_V4.md的美股专项规定优先 |

---

## Part 2: 冲突完整清单与裁定

> 格式: 每行代表一个实质性冲突。"重复"类冲突单独列在Part 3。

### 冲突组 C1: 美股S级仓位上限

| Conflict | Doc A (strategy.md §3.1) | Doc B (US_TRADING_SYSTEM_V4.md §3.1) | 裁定 | 理由 |
|----------|--------------------------|---------------------------------------|------|------|
| C1a: S级建仓目标仓位 | 30% | 15% | **US_V4: 15%** | US_V4是v4.0专门重建的美股规则；strategy.md的"30%目标"是旧规则残留（已在§11变更清单中记录"v3.0→v4.0: S级上限从≤40%降至初始15%最大25%"）|
| C1b: S级最大仓位上限（美股） | 25%（strategy.md §3.1表格中"美股列"） | 25% | **一致，无冲突** | 两者最大仓位上限均为25% |
| C1c: S级A股最大仓位 | 40% | 不涉及（仅美股） | **strategy.md: 40%** | A股规则US_V4不管辖 |

**执行规则**: 美股S级 初始仓位15%，最大仓位25%，同时最多1只。A股S级 目标30%，上限40%。

---

### 冲突组 C2: 美股A/B级仓位上限

| Conflict | Doc A (strategy.md §3.1) | Doc B (US_TRADING_SYSTEM_V4.md §3.1) | Doc C (position-framework.md §二) | 裁定 | 理由 |
|----------|--------------------------|---------------------------------------|-----------------------------------|------|------|
| C2a: A级最大仓位（美股） | 15% | 15% | 15% | **一致: 15%** | 三者一致 |
| C2b: B级最大仓位（美股） | 10% | 10% | 10% | **一致: 10%** | 三者一致 |
| C2c: A级建仓目标仓位（美股） | "15%"（建仓目标列） | 10% | 10% | **US_V4: 10%** | US_V4 v4.0专项；strategy.md的"目标=上限"表述是旧惯例 |

---

### 冲突组 C3: 美股止损方式（A级/B级）

| Conflict | Doc A (US_TRADING_SYSTEM_V4.md §4.1) | Doc B (position-framework.md §二) | 裁定 | 理由 |
|----------|---------------------------------------|-----------------------------------|------|------|
| C3a: A级止损 | Trailing -12%（从高点） | **-10% EOD**（position-framework §二表格） | **US_V4: Trailing -12%** | US_V4 §4和§3.1均明确-12%；position-framework.md的-10%系笔误（该文件其他处均写-12%） |
| C3b: B级止损 | Trailing -10% | **-12% EOD**（position-framework §二表格） | **US_V4: Trailing -10%** | 同上，position-framework.md在此处A/B止损值对调，是明确错误 |

**验证**: exit-framework.md §二明确写"A级: Trailing stop, ATR×2或高点-12%（取较宽）"和"B级: Trailing stop, ATR×1.5或高点-10%"，与US_V4一致，确认position-framework的错误。

---

### 冲突组 C4: 日损失触发阈值（美股组合级）

| Conflict | Doc A (strategy.md §13) | Doc B (US_TRADING_SYSTEM_V4.md §7.7) | 裁定 | 理由 |
|----------|--------------------------|---------------------------------------|------|------|
| C4a: 暂停新建仓阈值 | 单日亏损>2.5% | 单日亏损>-2% | **US_V4: 2%** | US_V4是美股专项系统，阈值更保守合理；strategy.md的2.5%是旧版混合规则 |
| C4b: 暂停所有交易阈值 | 单日亏损>4% | 单日亏损>-3% | **US_V4: 3%** | 同上；3%触发全面review比4%更保守，与H1/H2教训一致 |
| C4c: 组合回撤强制减仓 | 月度亏损>15%→仓位降50% | 组合回撤-15%（从NAV高点）→减仓至50%总仓位 | **US_V4: 从NAV高点回撤15%** | 度量基准明确（高点而非月度），消除模糊 |

**注意**: strategy.md §13的"周度"和"月度"触发在US_V4中未列出——这些是A股规则补充，仍然有效，但不适用于美股。

---

### 冲突组 C5: S5条件定义

| Conflict | Doc A (strategy.md §3.6) | Doc B (US_TRADING_SYSTEM_V4.md §1.4) | 裁定 | 理由 |
|----------|--------------------------|---------------------------------------|------|------|
| C5a: S5条件内容 | "催化剂失败后bear case < 10%"（基本面兜底） | "Momentum分≥8/10"（技术面要求） | **US_V4 for 美股, strategy.md for A股** | A股S级的S5合理（催化剂驱动，基本面兜底有意义）；美股S级的S5用Momentum≥8更符合v4.0体系（Momentum是首要因子） |

**执行规则**: 
- A股S级: S5 = bear case < 10%（strategy.md定义）
- 美股S级: S5 = Momentum分≥8/10（US_V4定义）

---

### 冲突组 C6: 止盈分批比例

| Conflict | Doc A (strategy.md §5.3) | Doc B (US_TRADING_SYSTEM_V4.md §4.2 + exit-framework.md §三) | 裁定 | 理由 |
|----------|--------------------------|--------------------------------------------------------------|------|------|
| C6a: 第一批锁利触发点 | "达到目标价的70%" | "涨至目标价50%" | **US_V4: 50%** | US_V4和exit-framework.md一致；strategy.md的70%是旧规则（已在§5.3明确说明分批规则，但后方的Trailing stop段写的是"50%锁利"——内部不一致，取US_V4） |
| C6b: 分批比例 | 25%/25%/25%（三批，各25%） | 1/3 / 1/3 / 剩余trailing | **US_V4: 1/3 / 1/3 / trailing** | 1/3制度在exit-framework和US_V4完全一致，且持仓<200股不可执行25%分批（A股约束导致25%批次机械执行困难） |

**A股注意**: strategy.md §5.3后段的"第一批/第二批/第三批"(25%/25%/25%)仅适用A股，且有"持仓≤200股时全仓一次性出场"的例外规定。美股统一用1/3制度。

---

### 冲突组 C7: 做空止损比例

| Conflict | Doc A (strategy.md §2) | Doc B (US_TRADING_SYSTEM_V4.md §5.4 + short-framework.md §三) | 裁定 | 理由 |
|----------|-------------------------|---------------------------------------------------------------|------|------|
| C7: 空头止损阈值 | strategy.md §2说明"-10%硬规则（做空无'等回来'选项）" | "-10%（硬规则），做空没有'等回来'的选项" | **一致: -10%** | 两者完全一致，无冲突 |

---

### 冲突组 C8: 现金下限

| Conflict | Doc A (strategy.md §3.2, v4.0修订) | Doc B (US_TRADING_SYSTEM_V4.md §3.2) | Doc C (position-framework.md §三) | 裁定 | 理由 |
|----------|------------------------------------|---------------------------------------|-----------------------------------|------|------|
| C8a: 现金下限（美股） | ≥15%（v4.0修订，原20%） | ≥15%（$22.5K） | ≥15%（注明"从20%下调"） | **一致: 15%** | 三者均已更新至15%，无冲突 |
| C8b: 加仓前现金要求 | 加仓前须≥20%（§3.4条件③） | 无专项规定 | 无专项规定 | **strategy.md: 加仓前≥20%** | 这是A股专项约束（A股加仓场景更谨慎），美股无此额外要求 |

---

### 冲突组 C9: 美股空头VIX触发处理

| Conflict | Doc A (strategy.md §2 "做空硬规则") | Doc B (US_TRADING_SYSTEM_V4.md §4.1 + §7.3) | 裁定 | 理由 |
|----------|-------------------------------------|---------------------------------------------|------|------|
| C9: VIX>25时现有空头处理 | "VIX>25 = 停止所有新做空 **+ 24h内cover所有现有空头**" | "VIX>25立即cover（所有空头，一次全退）" | **US_V4: 立即（非24h内）** | US_V4写"立即"cover；strategy.md给24h宽限。实操以US_V4"立即"执行为准，因H2教训是延迟cover导致损失扩大 |

---

### 冲突组 C10: 美股入场后仓位建立节奏

| Conflict | Doc A (strategy.md §4.6 "情景A") | Doc B (US_TRADING_SYSTEM_V4.md §2.1 "GAP规则") | 裁定 | 理由 |
|----------|------------------------------------|------------------------------------------------|------|------|
| C10: 小gap（<5%）建仓方式 | 趋势初期"小仓入场（C级3-4%）→ 验证Beat → 加至目标" | "<5% gap一次性建仓至目标仓位" | **US_V4: 一次性建至目标** | US_V4的GAP规则更精确且有H1/H2数据支撑；strategy.md的"C级3-4%"对应低VIX趋势市分批入场逻辑，与US_V4在Momentum≥28/35时"任何3%回调即入"相同。统一以US_V4GAP规则为执行标准 |

---

### 冲突组 C11: 美股时间止损（A股额外14天规则）

| Conflict | Doc A (strategy.md §5.3条件4, 时间止损) | Doc B (US_TRADING_SYSTEM_V4.md §4.4) | 裁定 | 理由 |
|----------|-----------------------------------------|---------------------------------------|------|------|
| C11: A股时间止损 | 14个交易日无新催化 → 重新评估是否继续持有 | 不适用（US_V4专管美股） | **strategy.md: A股用14天** | 两套系统管辖不同市场；A股14天，美股按等级分（T=10/C=20/B=30/A=60/S=10天）。strategy.md §5.3注释中已明确"美股使用分级时间止损见US_V4" |

---

### 冲突组 C12: 美股S级（strategy.md对position-framework不一致）

| Conflict | Doc A (strategy.md §3.1表格) | Doc B (position-framework.md §二) | 裁定 | 理由 |
|----------|-----------------------------|-----------------------------------|------|------|
| C12: 美股S级止损说明 | "-7%（硬止损，无商量余地）" | "-7%（硬规则，EOD确认）" | **两者一致: -7%** | 实质一致，"EOD确认"是执行细节，不是冲突 |

---

## Part 3: 重复规则裁定（16条）

> 以下规则在多个文档中出现，内容实质相同但措辞或位置有重复。声明哪份是"主版本"（canonical copy），其他为参考性镜像。

| 编号 | 规则内容 | 主版本（Canonical） | 镜像位置 | 镜像说明 |
|------|---------|-------------------|---------|---------|
| D1 | L13三行检查表（买的理由/跌20%割不割/今天才知道吗） | **strategy.md §8 L13** | CLAUDE.md, strategy.md §5.1进场检查表 | CLAUDE.md是运行时镜像，与主版本一致 |
| D2 | L15 Thesis验证（搜索"[标的名]最近为什么涨"） | **strategy.md §8 L15** | CLAUDE.md, strategy.md §5.1进场检查表 | 同D1 |
| D3 | S级S1-S5条件（A股版）| **strategy.md §3.6** | CLAUDE.md S级额外强制检查 | CLAUDE.md是执行清单镜像，美股S5改为US_V4定义 |
| D4 | ABCD下跌分类（A/B/C/C+/D五类） | **strategy.md §5.2** | CLAUDE.md, US_TRADING_SYSTEM_V4.md（部分引用） | CLAUDE.md完整镜像；US_V4仅引用D类全退规则 |
| D5 | VIX>25禁止做空 | **US_TRADING_SYSTEM_V4.md §5.6 / §7.3** | strategy.md §2, short-framework.md §五, risk-framework.md | 所有镜像内容一致；US_V4为主版本（完整rationale） |
| D6 | 每周三空头扫描SOP（5步骤） | **US_TRADING_SYSTEM_V4.md §5.5** | strategy.md §2, short-framework.md §四 | short-framework.md是完整版本，与US_V4一致；strategy.md为简略摘要 |
| D7 | Regime Detection三重信号（VIX 5日delta / 10Y / 2Y-10Y利差） | **US_TRADING_SYSTEM_V4.md §7.2** | risk-framework.md §一, strategy.md §8.5 | risk-framework.md是详细展开版，完全一致；strategy.md为摘要 |
| D8 | 空头止盈目标（-20%至-30%或catalyst消失） | **US_TRADING_SYSTEM_V4.md §5.4** | short-framework.md §三 | 完全一致 |
| D9 | 时间止损分级（T=10/C=20/B=30/A=60/S=10天） | **US_TRADING_SYSTEM_V4.md §4.4** | exit-framework.md §四 | exit-framework.md完全一致 |
| D10 | 分批锁利规则（目标50%减1/3 / 目标100%再减1/3 / 剩余trailing） | **US_TRADING_SYSTEM_V4.md §4.2** | exit-framework.md §三, strategy.md §5.3（美股部分） | exit-framework.md一致；strategy.md的A股版本有25%批次差异（见C6裁定） |
| D11 | 美股最低建仓金额$7,500 | **US_TRADING_SYSTEM_V4.md §1.3** | position-framework.md §二, strategy.md §3.2, CLAUDE.md | 所有文档一致 |
| D12 | 美股总持仓上限9只（多6+空3） | **US_TRADING_SYSTEM_V4.md §3.2** | position-framework.md §三, strategy.md §3.2, CLAUDE.md | 所有文档一致 |
| D13 | S级持仓≤2周（≤10个交易日）/ 催化剂后Day3全退 | **US_TRADING_SYSTEM_V4.md §4.3** | strategy.md §3.6, CLAUDE.md, exit-framework.md §三 | 所有文档一致 |
| D14 | L10-L15行为铁律 | **strategy.md §8 L10-L15** | CLAUDE.md L10-L15 | CLAUDE.md是逐字镜像，strategy.md为主版本 |
| D15 | 空头4分类（Type1结构性/Type2催化剂/Type3估值/Type4对冲）及胜率 | **short-framework.md §一** | US_TRADING_SYSTEM_V4.md §5.2, strategy.md §2 | short-framework.md最完整；US_V4为权威摘要；strategy.md为简版 |
| D16 | 每日4-window执行流程（W1/W2/W3/W4） | **strategy.md §6** | CLAUDE.md（4个监测窗口表格） | CLAUDE.md是运行时简化版，strategy.md为主版本 |

---

## Part 4: 特别说明 — strategy.md中存在的内部不一致

以下是strategy.md自身内部的不一致（不是跨文档冲突），裁定后统一执行规则：

| 编号 | 位置 | 不一致内容 | 裁定 |
|------|------|---------|------|
| I1 | §3.1表格的"止损宽度"列 vs §5.3出场5条规则中的"Trailing Stop参数" | §3.1写A级止损"15-20%（A股）/ trailing -12%（美股）"；§5.3的Trailing Stop写"A级-7%硬止损"（这是S级的止损，写错位置了） | **A级止损 = A股15-20% / 美股trailing -12%（§3.1为准）** |
| I2 | §5.1进场检查表"止损幅度%"注释 | 写"S=-7%硬止损 / A=15-20% / B=10-15% / C=7-10%"但前面写A的止损宽度是15-20%，这里又是A≥B的止损宽度 | **维持§3.1: A=15-20%（A股）/ B=10-15%（A股）** |
| I3 | §3.2"单只仓位"约束行 vs §3.1等级表 | §3.2写"超额减至目标值（S级30% / A级20% / B级12% / C级6%）"但§3.1的目标是S=30%/A=15%/B=10%/C=5% | **超配减至目标值时以§3.1等级目标仓位为准（S=30%/A=15%/B=10%/C=5%）；§3.2表格中的"20%/12%/6%"是超配时减到的过渡目标，不是等级定义值** |
| I4 | §4.3中美股Bear case阈值 vs §5.1进场检查表 | §4.3表格写"25-35%仅T级"；§5.1检查表写"≤15%=Safe; 15-25%=Elevated最高C级; **25-35%=High仅T级+止损**; >35%=排除" | **两处一致（>35%排除），无实质冲突** |
| I5 | 美股Bear case在Checklist脚注 vs CLAUDE.md铁律第4条 | strategy.md Checklist脚注: "Bear case >35%（美股）不买"；CLAUDE.md: "Extreme(>35%)硬性排除" | **一致: >35%排除** |

---

## Part 5: 文档权威分类总结

### US_TRADING_SYSTEM_V4.md 是权威的规则

- 美股5维度评分体系（含加权公式、评分细则、等级映射）
- 美股Conviction→Sizing表（初始仓位、最大仓位、止损线）
- 美股集中度规则（9只总上限 / 现金≥15% / $7,500最低）
- 美股入场GAP规则（三档：>15% / 5-15% / <5%）
- 美股退出分批规则（目标50%减1/3 / 100%再减1/3 / trailing）
- 美股时间止损（T=10天/C=20天/B=30天/A=60天/S=10天）
- 美股做空系统（10分制评分卡 / 仓位规则 / 每周三SOP）
- Regime Detection三重信号（S1 VIX / S2 TNX / S3利差）
- 日损失/回撤触发阈值（-2%暂停新建仓 / -3%全面review / -15%强制减半）
- 美股S级S5条件 = Momentum分≥8/10（非bear case<10%）

### strategy.md 是权威的规则

- A股所有规则（仓位、选股框架、进出场时机、Bear case分级）
- A股S级S5条件 = bear case<10%（维持）
- 行为铁律L1-L18（通用，两市均适用）
- ABCD下跌分类（通用）
- S级进场检查表（A股版，含S1-S5 A股定义）
- 现金部署速度规则（A股专项，§3.5）
- 升降级规则（A股专项，§3.1）
- 错误模式清单E1-E21

### CLAUDE.md 作用

- 运行时操作手册（agent执行层）
- 所有规则是strategy.md + US_V4的镜像简化版
- 冲突时以strategy.md / US_V4为准，CLAUDE.md不是独立规则来源

### system-v4/框架文件群 作用

- US_TRADING_SYSTEM_V4.md的详细展开和背景推导
- 所有规则值应与US_V4一致
- 若发现不一致（如position-framework.md的A/B止损对调），以US_V4为准
- 框架文件提供的"原因/验证/决策树"是有价值的补充，不是规则来源

---

## Part 6: 执行规则速查卡（实操直用）

> 当agent遇到不确定时，按此卡查询，无需重读所有文档。

### 美股仓位速查（US_V4权威）

```
S级: 初始15% / 最大25% / 最多1只 / 止损-7%硬止损EOD / 持仓≤10交易日
A级: 初始10% / 最大15% / 最多2只 / 止损trailing -12%（从高点）/ 时间止损60天
B级: 初始7%  / 最大10% / 最多2只 / 止损trailing -10%（从高点）/ 时间止损30天
C级: 初始5%  / 最大8%  / 最多1只 / 止损-8%硬止损 / 时间止损20天
T级: 5%固定  / 最大5%  / 最多1只 / 止损-8%硬止损 / 时间止损10天
```

### A股仓位速查（strategy.md权威）

```
S级: 目标30% / 上限40% / 最多1只 / 止损-7%硬止损 / 持仓≤2周
A级: 目标15% / 上限25% / 正常建仓 / 止损15-20%
B级: 目标10% / 上限15% / 止损10-15%
C级: 目标5%  / 上限8%  / 止损7-10%
T级: 目标4%  / 上限8%  / 止损-5%
```

### Bear case分级速查

```
美股（US_V4权威）:
  ≤25%       → Safe，正常建仓
  25-35%     → High，仅T级试仓+明确止损
  >35%       → Extreme，排除做多

A股（strategy.md权威）:
  ≤15%       → 正常建仓
  15-25%     → 需设明确止损点
  25-40%     → 仅A级+事件驱动+初始减半
  >40%       → 不建仓（硬规则）
```

### 触发日损失阈值（美股，US_V4权威）

```
单日亏损>-2% → 次日暂停新建仓，只执行止损
单日亏损>-3% → 次日暂停所有交易，全面review
组合回撤-10%（从NAV高点）→ 全面持仓review，评估Regime
组合回撤-15%（从NAV高点）→ 强制减仓至50%总仓位（硬规则）
```

### 做空速查（US_V4权威）

```
评分阈值: ≥8.5立即执行 / 7.0-8.4等待更好入场点 / <7.0跳过
总空头暴露: 目标10-15%（不超15%）
单只上限: 5%（$7,500）
最多同时: 3只
止损: -10%（硬规则）
VIX>25: 立即cover全部空头（不是24h内，是立即）
每周三: 强制扫描SOP（5步，0笔也要写记录）
```

---

## 附录: 修订日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-05-22 | v1.0 | 初始版本。审查8个源文件，发现12组实质性冲突（C1-C12），16条重复规则（D1-D16），5处strategy.md内部不一致（I1-I5）。全部给出具体裁定。 |

---

*生成依据: strategy.md v5.0 (1056行) + US_TRADING_SYSTEM_V4.md (1056行) + CLAUDE.md + position-framework.md + risk-framework.md + exit-framework.md + entry-framework.md + short-framework.md 全文审查*
*原则: 每个冲突给出具体裁定，不留"待讨论"。美股规则US_V4优先，A股规则strategy.md优先。*
