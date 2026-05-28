# Track B 系统设计 — 跨模块一致性审计报告

> 审计日期：2026-05-28
> 审计范围：01_rating.md / 02_entry.md / 03_exit_stop.md / 04_discovery.md / 05_playbook.md / 06_pain_reward.md / 07_automation.md / 08_lifecycle.md
> Track A参考：strategy.md §1五条核心规则 + §2.4b双轨系统 + §3.2组合约束
> Claude分析意见，非用户投资结论。

---

## 矛盾 (C: Contradiction)

**C1: B+仓位上限在不同文件中描述不一致**
- 01_rating.md §2.1：B+仓位上限 = **15%**
- 02_entry.md §1 Step4：主板Type 1/2/3/4仓位上限 = **≤15%** ✅ 一致
- 02_entry.md §6.1（资金分配注释）："Track B绝不超过总仓的30%（**硬性建议，非死规则**）" — 与01_rating.md §3.2将其列为"硬约束"（`Track B总仓位 ≤ 40%（绝对上限）`）措辞不一致
- 03_exit_stop.md §4.3：Track B总仓位"≤30%（建议）/ ≤40%（绝对上限）"
- **具体矛盾**：02_entry.md §6.1明确说"非死规则"，01_rating.md §3.2和03_exit_stop.md §4.3都说"绝对上限40%"。前者比后两者松。
- **建议修复**：02_entry.md §6.1改为与01_rating.md §3.2一致："Track B总仓≤30%（正常）/ 牛市高峰期可临时至40%（绝对上限）"，删除"硬性建议，非死规则"措辞。

---

**C2: B-等级ATR K值在01_rating.md与strategy.md间不一致**
- 01_rating.md §2.1表格：B-等级 ATR K值 = **1.5**
- strategy.md §1 R2（Track A B-）：K值 = **1.5** ✅ 一致
- 08_lifecycle.md §1.3：`棘轮止损参数 K=2.0固定`（Track B专用）
- **矛盾**：01_rating.md给B-配K=1.5，但08_lifecycle.md说Track B棘轮止损K值固定为2.0（不区分B+/B/B-等级）。哪个优先？
- **建议修复**：08_lifecycle.md §1.3加注："K=2.0适用于B+/B级；B-级棘轮K值降至1.5，与01_rating.md §2.1一致。"

---

**C3: 炸板率清仓阈值在不同模块表述不一致（50% vs 60%）**
- 01_rating.md §4.2降级条件：`炸板率升至30-50%（分歧期开始）→ -1档`；无60%的清仓阈值
- 01_rating.md §4.3一票否决：`炸板率>60%（崩溃期）→ 直接C清仓` ✅
- 03_exit_stop.md §1 Layer 2 2B：`炸板率>50%→当日减仓`；`炸板率>60%→当日清仓` ✅
- 05_playbook.md SS-001：明确注释"炸板率≥60%（非50%）在历史上是'当日清仓'而非'当日减仓'的信号" ✅
- 04_discovery.md TB-S1判定规则：`CRASH（崩溃期）：炸板率>60%` ✅
- **实际矛盾**：01_rating.md §4.2的降级表格**缺失**炸板率>60%的清仓路径（只写了分歧期-1档），但§4.3用一票否决补救了。两个不同机制处理同一信号，容易造成执行混乱。
- **建议修复**：01_rating.md §4.2降级表格增加一行：`炸板率>60%（崩溃期）→ 直接进入§4.3一票否决，不经过降级流程`，与§4.3对接。

---

**C4: 拥挤度阈值T2豁免在不同模块标准略有差异**
- 03_exit_stop.md §1 Layer 2 2B：`拥挤度>40%→T2豁免（仅关注，不减）`；`拥挤度>48%→T2减至半仓（非清仓）`；`修正值>2.4→即日清仓（无T2豁免）`
- 04_discovery.md TB-S2判定规则（TMT特殊规则）：`TMT占比>40%→正常减仓关注区`；`TMT占比>48%→非T2减仓50%；T2减至半仓`；`TMT占比>2.4×历史标准差→无条件减仓（T2无豁免）`
- **潜在矛盾**：03_exit_stop.md写的是"修正值>2.0→减仓>50%"（无T2豁免），但04_discovery.md没有对应的2.0阈值处理。04_discovery.md跳过了2.0直接到2.4标准差。数值表述不完全对应（03用绝对值2.0/2.4，04用2.4倍标准差）。
- **建议修复**：04_discovery.md TB-S2增加`TMT占比修正值>2.0（绝对值）→减仓>50%`，与03_exit_stop.md §1 Layer 2 2B保持一致。

---

**C5: 龙头跌>5%铁律的触发范围描述不一致**
- 01_rating.md §4.2：`龙头跌>5% → 直接C，所有Track B当日全出（铁律，不分析）`
- 02_entry.md Step5：`主龙头跌>5% = 当日全出，不分析`
- 03_exit_stop.md §1 Layer 1：`主龙头单日跌幅>5% → Track B全部出场`
- 08_lifecycle.md §1.5铁律1：`板块龙头（主龙头）单日跌>5% → Track B当日市价全出`
- **差异**：以上均一致；**但**06_pain_reward.md §1 PART A TBL1："触发定义：止损出场（铁律止损1/2/3触发）或亏损>2%出场"。
- 06_pain_reward.md中Pain触发阈值为"亏损>2%"，而铁律是"龙头跌>5%"。当龙头跌4%时，自身标的可能已跌8%+，亏损>2%的Pain触发和铁律触发之间存在灰色地带（龙头跌3%，自身跌6%=亏损>2%，但铁律未触发）。
- **建议修复**：06_pain_reward.md TBL1增加注释："亏损>2%但未触发铁律止损的出场（如Board阶段减仓）同样触发Pain Memory，与铁律止损触发并列。"

---

**C6: Type 4政策型持仓天数上限在03_exit_stop.md和02_entry.md存在差异**
- 03_exit_stop.md §1 Layer 3时间止损表格：`Type 4政策方向性→跟政策落地节点`；`Type 4政策落地性→1-3天`
- 02_entry.md §3.2（Type 4分批规则）："Type 4方向性政策→40%探针→D+3确认补至80%"，隐含可持有到政策落地节点
- 05_playbook.md PP-001（政治局会议入场）出场规则：`§6.1 ★★★信号→全部清仓`；`炸板率≥60%→当日清仓`；`§4.4龙头跌>5%→全出`
- **矛盾**：05_playbook.md PP-001中出场规则引用`§6.1 ★★★信号`，但§6.1是ROTATION_STRATEGY_V1.md的引用编号，在8个系统设计文档中均无对应章节定义。这是悬空引用。
- **建议修复**：05_playbook.md PP-001出场规则改为直接描述信号内容："主力净卖出主线龙头>10亿+同日新方向涨停→Track B全部清仓"，不依赖§6.1悬空引用。

---

**C7: Type 5游资坐庄仓位上限在不同模块数字不一致**
- 01_rating.md §1维度一（B级信号附注）："Type 5游资坐庄→最高B-（5-10%硬顶）"
- 01_rating.md §3.1建仓规则：`Type 5游资附加约束：入场≤3板，单只≤10%`
- 02_entry.md §1 Step4：`Type 5游资坐庄→≤10%（信息滞后折价）`
- 05_playbook.md HP-002：`仓位5%（硬上限，不可加仓）`
- 06_pain_reward.md TBL3（Type 5连亏惩罚后）：`sizing压至≤5%（原5-10%上限进一步压缩）`
- **矛盾**：正常状态下，01_rating.md说"5-10%硬顶"，02_entry.md说"≤10%"，05_playbook.md HP-002说"5%"。三个不同数字，哪个优先？HP-002的5%是针对特定Pattern（商业航天场景）还是通用规则？
- **建议修复**：统一为：`Type 5游资坐庄标准上限≤10%；有专门的游资连板Pattern（HP-002）时压至5%；信息确认度低时取下限5%`。在01_rating.md §3.1加注HP-002优先规则。

---

**C8: pain_memory文件名在06_pain_reward.md和07_automation.md命名不一致**
- 06_pain_reward.md §附录文件索引：`pain_memory_tb.md`
- 06_pain_reward.md PART A TBL1：`pain_memory_tb.md（rolling 5条）`
- 07_automation.md §2.4：文件名写作`tb_pain_memory.md`（前缀顺序不同）
- 07_automation.md §2.4模板标题：`# Track B Pain Memory（最近10条）`（说rolling 10条，06说rolling 5条）
- **矛盾1**：文件名 `pain_memory_tb.md` vs `tb_pain_memory.md`
- **矛盾2**：rolling条数 5条（06_pain_reward.md）vs 10条（07_automation.md §2.4模板）
- **建议修复**：统一文件名为 `tb_pain_memory.md`（前缀tb_与其他TB文件一致：tb_playbook.json / tb_victory_memory.md）。rolling条数统一为10条（07的更合理，5条太少）。

---

**C9: victory_memory文件名在06_pain_reward.md和07_automation.md命名不一致**
- 06_pain_reward.md §附录文件索引：`victory_memory_tb.md`
- 07_automation.md §2.5：文件名写作`tb_victory_memory.md`（前缀顺序不同）
- 07_automation.md §2.5模板标题：`# Track B Victory Memory（最近10条）`（06说rolling 5条）
- **矛盾1**：文件名 `victory_memory_tb.md` vs `tb_victory_memory.md`
- **矛盾2**：rolling条数 5条 vs 10条（同C8）
- **建议修复**：统一为 `tb_victory_memory.md`，rolling 10条。

---

**C10: PlayBook文件名在06_pain_reward.md和07_automation.md命名不一致**
- 06_pain_reward.md §附录文件索引：`playbook_tb.json`
- 07_automation.md §2.3：文件名写作`tb_playbook.json`
- **建议修复**：统一为 `tb_playbook.json`（前缀tb_一致性）。

---

**C11: conviction_scorecard文件命名差异**
- 06_pain_reward.md §附录：`conviction_scorecard_tb.json`
- 07_automation.md中无独立定义该文件（使用existing `conviction_scorecard_cn.json`）
- CLAUDE.md §9规则索引：`conviction_scorecard_cn.json`（Track A A股版本）
- **潜在矛盾**：06_pain_reward.md设计了独立的`conviction_scorecard_tb.json`，但07_automation.md §1.5"不需要新脚本"清单说"`conviction_check.py`增加`--track B`过滤"，暗示复用Track A的文件。两种方案有冲突。
- **建议修复**：明确选择一种方案：推荐独立文件`tb_scorecard.json`（TB状态独立，防止Track A/B互相污染），在07_automation.md中同步。

---

## 遗漏 (M: Missing)

**M1: 05_playbook.md中PlayBook触发点未与02_entry.md建仓五步法对接**
- 02_entry.md中的TB建仓五步法（Step 1~5）中未提及PlayBook匹配步骤
- 05_playbook.md第七部分说"建仓前匹配流程（<2分钟）"，但这一步骤在02_entry.md的五步法中完全缺失
- **应该在哪里出现**：02_entry.md Step 3（标的门）或Step 4（Sizing）前，应有一步"PlayBook匹配检查"
- **建议修复**：02_entry.md §1 Step 3结尾增加："PlayBook匹配（可选，<2分钟）：对照05_playbook.md第七部分；匹配≥80分→sizing可至B+硬顶×1.2（不超上限）"

---

**M2: 04_discovery.md输出信号如何触发02_entry.md Entry流程，链条断裂**
- 04_discovery.md §四 TB 4-Gate评估（Gate 3）写了"SABCD评级 — Track B最高B+级"，但这里的评级应是01_rating.md的5维打分，而非SABCD
- 04_discovery.md产出PRIORITY信号后，如何流入02_entry.md的五步法，文档中没有明确说明
- **应该在哪里出现**：04_discovery.md §4.3 TB 4-Gate的Gate 3应改为"5维打分（01_rating.md §1）→等级B+/B/B-"；同时说明"PRIORITY信号触发后，进入02_entry.md五步法执行"
- **建议修复**：04_discovery.md §4.3 Gate 3修改为："5维评级打分（01_rating.md §1）→等级B+/B/B-（注：此处不是SABCD系统，Track B用专属评级）"；并在§4.3末尾加："PRIORITY标的通过4-Gate后，直接进入02_entry.md §1 TB建仓五步法执行"

---

**M3: 北交所特殊规则未在06_pain_reward.md中系统覆盖**
- 01_rating.md §1维度五：北交所单只≤5%，特殊约束明确
- 02_entry.md §3路径三、§4.1：北交所T+3~T+5入场，最大5%总仓
- 03_exit_stop.md §1 Layer 3：北交所持仓天数上限5天，单独列出
- 06_pain_reward.md TBL3：北交所连亏惩罚项存在（单只降至≤3%，持有上限压至3天）
- **遗漏**：06_pain_reward.md的Pain Patterns中**没有专门的北交所Pain Pattern**。北交所有独特的失败模式：±30%限制/T+1延迟/流动性陷阱，这些是独立于TB-P1~P7之外的失败模式，尤其是"北交所跌停无法出逃"场景
- **建议修复**：06_pain_reward.md增加TB-P8：`tb_bse_liquidity_trap`（北交所流动性陷阱），聚焦：①龙头-5%信号与北交所±30%的执行难题②T+1延迟在北交所环境下的特殊危险

---

**M4: 08_lifecycle.md阶段0建仓期中缺少PlayBook匹配步骤**
- 08_lifecycle.md §1.2阶段0（D+0~D+2）：详细描述了建仓行为和龙头观察步骤
- 05_playbook.md说明建仓前必须做PatternMatch
- **遗漏**：08_lifecycle.md阶段0的"建仓行为"列表中没有PlayBook匹配检查
- **建议修复**：08_lifecycle.md §1.2阶段0的判定标准后增加："□ PlayBook匹配（05_playbook.md §七）：匹配≥80分→可加成sizing；触发Anti-Pattern→停止建仓"

---

**M5: 07_automation.md中没有覆盖06_pain_reward.md的Circuit Breaker自动化**
- 06_pain_reward.md TBL2描述了Circuit Breaker（GREEN/YELLOW/RED）状态和触发条件
- 07_automation.md §1~§9详细描述了4个脚本和数据文件，但**没有提到CB状态**如何自动追踪
- **遗漏**：`conviction_scorecard_tb.json`（或`tb_scorecard.json`）中的CB状态如何被`rotation_review.py`或其他脚本自动更新，没有设计
- **建议修复**：07_automation.md §1.4 `rotation_review.py`功能列表中增加："7. 检查规则违反型亏损计数，更新CB状态（GREEN/YELLOW/RED），写入tb_scorecard.json"

---

**M6: 08_lifecycle.md双轨合计持仓上限与05_playbook.md SS-002反面场景之间的协同缺失**
- 08_lifecycle.md §5.1：双轨合计≤10只时，禁止新建Track B
- 05_playbook.md SS-002（科技→周期风格切换）：科技退潮时需要清仓后识别新主线
- **遗漏**：当Track A仍持有8只（满仓）、同时Track B有清仓需要时，新的Track B入场（新板块）被完全阻断——但SS-002说"科技断板后次日需要快速重建新主线的Track B仓位"。08_lifecycle.md的10只限制与SS-002的快速重建需求之间没有协调机制
- **建议修复**：08_lifecycle.md §5.1增加注释："当科技主线全面退潮（SS-002信号）且Track A持仓已达8只时，允许临时Track B入场替换同板块Track A仓位，但不新增持仓数；需在5个交易日内恢复到10只以内"

---

**M7: 02_entry.md中Portfolio Heat触发条件对Track B的影响未与08_lifecycle.md对齐**
- 02_entry.md §6.4："Portfolio Heat超红线（>15%）且有Track B建仓信号→Track B新建仓暂停"
- 08_lifecycle.md §5.2：`若加入Track B后Heat预计超过13%（红线的86%）：降低Track B单只仓位，而非拒绝入场`
- **矛盾/遗漏**：02_entry.md用>15%触发暂停，08_lifecycle.md用>13%触发减仓（而非暂停）。两个文件对同一条件给出不同处理（暂停 vs 减仓）
- **建议修复**：统一为：Heat>13%→降低Track B单只仓位（不拒绝入场）；Heat>15%→暂停新建，先降热值。02_entry.md §6.4修改与08_lifecycle.md §5.2对齐。

---

## 冗余 (R: Redundancy)

**R1: 龙头跌>5%全出铁律在5个文件中重复定义**
- 01_rating.md §4.2、02_entry.md Step2/Step5/TB-L1、03_exit_stop.md §1 Layer 1 L1-A、04_discovery.md TB-S3判定规则、08_lifecycle.md §1.5铁律1 — 均有"主龙头跌>5%→Track B当日全出"的定义
- **建议**：以03_exit_stop.md §1 Layer 1为权威定义（最完整，含多龙头分级处理），其余文件改为引用："见03_exit_stop.md §1 Layer 1铁律L1-A"

---

**R2: 硬开关条件在多个文件中重复列举**
- 02_entry.md Step1附加排除条件（4条）、03_exit_stop.md §4.4策略级开关（4+2条）、04_discovery.md §二（F20主控开关+紧急关闭）、07_automation.md §1.1 check_hard_switch函数（6条）
- 所有文件都定义了相同的4条硬开关条件（沪深300 20日<-8% / 成交额<1.5万亿连续5日 / F20呼气 / 涨停<30家连续5日），加上V1.2的2条紧急关闭条件
- **建议**：以07_automation.md §1.1的check_hard_switch为权威代码实现，其余文件写"见ROTATION_STRATEGY_V1.2 §1.4硬开关"，不重复列条件。避免日后修改某文件遗漏其他文件。

---

**R3: 板块生命周期四阶段在03_exit_stop.md和04_discovery.md中重复定义**
- 03_exit_stop.md §2：启动期/主升期/高潮期/退潮期，含炸板率和涨停家数判定标准
- 04_discovery.md TB-S1（情绪分级）：HIGH/MID/LOW/CRASH，逻辑相同
- **建议**：03_exit_stop.md §2是权威定义（含出场比例映射），04_discovery.md TB-S1引用03_exit_stop.md的阶段定义，不重新定义

---

**R4: T1→T2升级条件在4个文件中重复**
- 01_rating.md §2.2 B+段注释：`T1→T2升级加分条件：D+3至D+7出现具体产业数字`
- 03_exit_stop.md §1 Layer 3：`T1→T2升级延长持仓（V1.2规则）`详细条件
- 04_discovery.md TB-S6：`T1→T2升级监测`
- 05_playbook.md EP-001：`Type 1→Type 2升级检查（DeepSeek教训）`
- **建议**：以03_exit_stop.md §1 Layer 3（"持仓延长"语境下最完整）为权威定义，其余引用。

---

**R5: 拥挤度T2豁免规则重复出现**
- 03_exit_stop.md §1 Layer 2 2C：T2豁免细则
- 04_discovery.md TB-S2：TMT特殊规则
- **建议**：以03_exit_stop.md为权威，04_discovery.md改为"按03_exit_stop.md §1 Layer 2 T2豁免规则处理"

---

## 与Track A冲突 (X: Conflict)

**X1: 双轨合计持仓上限数量 — 08_lifecycle.md说10只，strategy.md §3.2说8只**
- 08_lifecycle.md §5.1：`Track A最大8只 / Track B最大3只 / 双轨合计≤10只`
- strategy.md §3.2（组合约束）：`持仓≤8只`（v9.1从5只改为8只）
- **冲突**：strategy.md的"持仓≤8只"是否包含Track B？按字面解读，持仓总数≤8，则Track A+Track B合计不能超过8。但08_lifecycle.md定义合计≤10只
- **建议**：08_lifecycle.md §5.1的10只与strategy.md §3.2的8只存在真实冲突，需要用户裁定哪个有效。若10只是为Track B专门新增，需在strategy.md §3.2加注："双轨制下，合计持仓上限为10只（Track A≤8 + Track B≤3，但合计不超10）"

---

**X2: Track B总仓位上限—strategy.md §2.4b说"≤15%"，各TB文件说"≤30-40%"**
- strategy.md §2.4b：`仓位：≤15%`（这是单只仓位上限，Track B硬顶）
- 01_rating.md §3.2："Track B总仓位 ≤ 40%（绝对上限）"
- 03_exit_stop.md §4.3："Track B总仓位 ≤ 30%（建议）/ ≤ 40%（绝对上限）"
- **澄清说明**：strategy.md §2.4b的"≤15%"是单只仓位上限，TB文件的30%/40%是Track B组合总仓位上限。两者不冲突，但strategy.md §2.4b未定义Track B总仓位上限，TB文件是在strategy.md之上补充的。
- **建议**：strategy.md §2.4b在"仓位：≤15%"后加注："（单只上限；Track B总仓位另见rotation-strategy/system-design/01_rating.md §3.2，上限40%）"，明确区分单只vs总量

---

**X3: 现金底线 — strategy.md v9.1已删除20%现金底线，但08_lifecycle.md §5.2中性期仍写"≥20%"现金底线**
- strategy.md §3.2：`现金 → 无底线（旧: ≥20%，v9.1删除）`
- 08_lifecycle.md §5.2总仓位约束表：中性期 `现金底线 = ≥20%`
- **冲突**：Track A已删除20%现金底线，但08_lifecycle.md中性期重新引入了这条规则
- **建议修复**：08_lifecycle.md §5.2表格中性期"现金底线≥20%"改为"无硬约束，但Track B控制在≤15%时自然保留现金空间"，与strategy.md v9.1一致

---

**X4: F20状态对Track B的操作矩阵与strategy.md的Track A矩阵格式不对称**
- strategy.md §2.4 Step1 F20矩阵：`强吸气/吸气/中性/呼气/深度呼气` 5种状态
- 04_discovery.md §二F20主控开关：`强吸气/吸气/中性/呼气/深度呼气` 5种状态 ✅
- 08_lifecycle.md §5.2总仓位约束：只有`强吸气/吸气/中性/呼气` 4种状态（**缺少深度呼气**）
- 02_entry.md Step1：F20判断只列了`吸气/强吸气/中性`（也缺少深度呼气和呼气的独立处理）
- **冲突**：strategy.md有5种F20状态，Track B有些文件只处理4种（缺深度呼气）
- **建议修复**：08_lifecycle.md §5.2和02_entry.md Step1均补充`深度呼气`状态：`Track B仓位=0%，同时评估已有持仓的退出`（strategy.md深度呼气=减至30%全仓，TB需要更严格=0%新建+评估清仓）

---

**X5: Track B的A类下跌处理与strategy.md §3.3下跌分类存在设计偏差**
- strategy.md §3.3：A类下跌（沪深300跌≥1.5%）→ `Hold`（Track A标准行为）
- 03_exit_stop.md §3：A类下跌TB特殊处理 → `立即判断是否触发主动减仓30-50%`
- **说明**：这不是矛盾，是设计意图上的Track A vs Track B差异化，文档也明确说明了原因（Track B持有小票beta高）
- **但以下有真实冲突**：02_entry.md Step1"附加排除条件：今日大盘跌幅≥1.5%（A类下跌）→ NO-GO"，但下方有"例外：Type 1事件冲击型...A类下跌豁免"；03_exit_stop.md §3末尾"T1特有A类下跌豁免（审计C5）"说明仅Type 1有豁免，Type 2/3/4/5不适用。但06_pain_reward.md TB-P4描述说"A类下跌豁免仅适用Type 1（§7.3注释）"引用了不存在的§7.3。
- **建议修复**：06_pain_reward.md TB-P4的"（§7.3注释）"改为"（03_exit_stop.md §3 T1特有A类下跌豁免）"

---

*审计完成。共发现：矛盾11条 / 遗漏7条 / 冗余5条 / Track A冲突5条*
*优先修复建议（对实操影响最大）：C5（Pain触发边界）、C6（§6.1悬空引用）、C8/C9/C10（文件名不一致）、X1（持仓上限10vs8）、X3（现金底线冲突）、M1（PlayBook未入五步法）*

*Claude分析意见 | 2026-05-28*
