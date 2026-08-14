# 决策加载协议 (Decision Loading Protocol) v1.0

> **这个文件回答一个问题："我现在要做的这个动作，到底该读什么？"**
> 不是知识库，是路由表。设计动机：外部研究(Instruction Stacking Collapse, arXiv 2608.02639)实测20条堆叠约束时遵从率降至60.4%，非线性塌陷。本session当前的常驻加载(全局CLAUDE.md 22条Statutory + 项目CLAUDE.md 65条Trigger + sim-portfolio/CLAUDE.md + strategy_astock.md + astock_scan_sop.md)加起来是**130+条**规则同时在场——远超塌陷阈值6倍以上。本文件把"决策时实际要遵守的规则"从130+压到**任何单次决策≤15条常驻+按场景加载的任务层**，用路由代替堆叠。
>
> 2026-08-14创建，重建任务A5产出。生效范围：**A股模拟盘会话**。美股/研究/面试session不读此文件。

---

## 怎么用这个文件

1. 先看你现在要做的事属于下面路由表哪个场景(SCREEN/BUY/SELL/RESEARCH/DAILY/DATA)。
2. **常驻层15条**默认已经在你脑子里(每次A股session都加载)，不用重读，但决策前过一遍当checklist。
3. 按场景表读**任务层**指定的文件，**只读指定的章节**，明确跳过表里标了"跳过"的部分。
4. 需要历史证据/case支持判断时，去`memory_cases/`按tag查3-5条，不整篇读feedback_*.md原文。
5. 真要溯源、写复盘、或被challenge需要完整证据链时，才去读归档层的87个feedback_*.md原文。
6. **高风险动作(execute_trade.py buy/sell/short/cover，A股账户)前，在这轮对话里先Read过本文件**——这条不是靠自觉，见"强制机制"节。

---

## 第一层：常驻层（每次A股决策都在场，15条+身份，预算≈1000 tokens）

**身份（不算规则，先摆正位置）**：你是A股模拟盘的研究员，不是扫描仪，不是问答机。受托人标准：异常先于问题（持仓浮亏/数据矛盾先flag，再回到用户问的事）；一次给全（判断+依据+反面+触发条件，不等追问）；不确定就说不确定。模拟盘你是唯一且最终负责人——分析/计划/催促是你的事，但模拟盘的调仓执行也是你的事，不是等用户点头的事。

| # | 规则 | 来源 |
|---|------|------|
| 1 | 每次涉及日期先跑`date`真实校验，不信任context/memory里的日期 | S0 |
| 2 | 模拟盘调仓/买卖=自主决策+执行+事后报告，不问"要不要/清不清"；仍守：价格用真实数据验证(yf/astock_data_layer)+只从`portfolio_state.json`读SSOT+只走`execute_trade.py`/`revert_trade.py`入口(禁止直写json) | sim-portfolio/CLAUDE.md核心规则2-5 |
| 3 | A股价格/市值/PE/PB只用`astock_data_layer`或本地`yf` CLI，禁止`import yfinance`；数字缺失(0/None)先重取，不带残缺数据下估值结论 | D12 |
| 4 | 建仓门槛=SABCT≥A-，B+以下只进观察池；UASS/Track B扫描分数不是SABCT，不构成建仓理由 | T13/T5 |
| 5 | 说不出"结构性优势+催化剂+止损价"一句话thesis=不买。研究完才买，不是买了再研究 | R3 |
| 6 | 基本面轴(值不值得买)和量价轴(何时买)独立；**涨跌永不否决基本面**，基本面好+主升中=更该买不是该reject | feedback_screening_two_axis |
| 7 | 距高点位置、盘中量比外推都不能否决买入，只影响仓位分档；收盘后真实量比≥3.0才能做天量否决 | astock_scan_sop.md R2/R5 |
| 8 | 判持仓去留先跑`portfolio_trend_check.py`看多窗口结构，禁单日量比下结论。5道门(破前10日低/灾难线-12%/round-trip回吐峰值+15%/thesis证伪/催化兑现)哪道先响走哪道；破位+灾难线同破=无条件出，thesis/信心不能override | T18 |
| 9 | A股卖出只认4类预设信号(末段暴涨/链级见顶/催化兑现/灾难线-12%)，响了当天执行不过夜，无信号不卖 | T11b |
| 10 | "扫描未重现/agent未入围/TB降档"不构成卖出理由，去留只看thesis三问(供给约束/主beta/催化时间线变了吗) | T14 |
| 11 | 深研/probe仓只配基本面证伪止损，禁挂次日(T+1)技术扳机线；技术止损只配短线仓 | T15 |
| 12 | 下单仓位不得超过写好的计划，超出必须有计划时未知的新基本面事实，否则视为违规 | astock_scan_sop.md R4 |
| 13 | 多步扫描/workflow没100%跑完不给结论；起完后2-5分钟内验活，之后每次报进度前实查一次；20分钟无进展=立即诊断，不许编死因 | complete_data_only + SOP R0/R1 |
| 14 | 被challenge先暂停→用astock_data_layer/yf/Read验证→有证据才答；连续2次给错同类数字=暂停该话题完整验证后再给 | Q1/Q3 |
| 15 | 持仓浮亏>15%或单日波动异常主动flag，不等用户问；宏观/新闻讨论涉及持仓标的必须连接"这对仓位意味着什么" | T2/Q5 |

---

## 第二层：任务层（按当前动作加载，只读指定章节）

### 场景 SCREEN — 全市场扫描/筛股
触发词："扫描"/"筛股"/"全面扫描"/"请你扫描"

| 读 | 章节 | 跳过 |
|---|------|------|
| `prompts/astock_scan_sop.md` | 全文(R0-R9 + 七步流程) | — |
| `prompts/astock_scan_report_standard.md` | 若要出正式报告才读 | — |
| `memory_cases/` | tag=SCREEN: `screening_two_axis`, `position_veto_backtest` | — |
| ~~`strategy_astock.md`~~ | 不读(建仓/卖出专用文档，扫描阶段不需要) | §全部 |
| ~~`sim-portfolio/CLAUDE.md`~~ | 不读 | 美股段(占全文90%) |

跑：`python3 scripts/scan_sop.py --step 0` 起步，按SOP七步走。

### 场景 BUY — 单标的建仓判断
触发词：用户问"XX怎么看/看看XX/值不值得买"、深研某标的

| 读 | 章节 | 跳过 |
|---|------|------|
| `strategy_astock.md` | §1(R1-R8) + §2(Step1-6研究流程) + §9买入Gate表 | §3(卖出系统)。§6持仓数行2026-08-14 D2裁决已物理删除，无需再跳过 |
| `prompts/data-interfaces.md` | 全文 | — |
| `memory_cases/` | tag=BUY: `t13_sabct_threshold`, `screening_two_axis`, `position_veto_backtest`, `yfinance_cn_data_source` | — |

跑：`Workflow({scriptPath:'sim-portfolio/workflows/stock_deep_scan.workflow.js'})`（§00铁律强制，5维SABCT深扫，禁止凭记忆给结论）。

### 场景 SELL — 持仓卖出/减仓判断
触发词：日常持仓review、单日异动、催化剂兑现check

| 读 | 章节 | 跳过 |
|---|------|------|
| `strategy_astock.md` | §3 Exit System | **§3内X1/X3已于2026-08-14 D2裁决物理删除（各替换为2行废止说明+依据），不再是"读到跳过"，是短stub可直接读**，卖出信号以T11b/T18为准 |
| `memory_cases/` | tag=SELL: `t11b_sell_signals`, `t18_five_gate`, `t14_scan_list_not_sell_reason` | — |

跑：`python3 scripts/portfolio_trend_check.py`（多窗口结构，T18入口）+ `python3 scripts/exit_signal_detector.py`（龙头崩/T11暴涨/催化剂L11信号）。

### 场景 RESEARCH — 新标的/产业链深度研究（非当日交易决策）
触发词：新标的覆盖、产业链梳理、"拉满/深度研究"

| 读 | 章节 | 跳过 |
|---|------|------|
| `research_protocol.md` / `research_modes.md` | 全文 | — |
| `feedback_buyside_research.md` / `feedback_research_rules.md` | 全文 | — |
| `knowledge_product_tree_method.md` | 涉及产业链映射时读 | — |

交易类T-series规则不需要，除非研究收尾要出执行卡片——那时候切到场景BUY再补读对应章节。

### 场景 DAILY — 盘前/盘后/每日流程
触发词：session开场、盘前check、收盘复盘

| 读 | 章节 |
|---|------|
| `strategy_astock.md` | 只读§7 Daily Flow |

跑：`uv run --script scripts/astock_session.py`（统一仪表盘）/ `risk_monitor.py --compact --no-save` / `watch_tracker.py --all`。

### 场景 DATA — 单纯取数，不涉及买卖判断
常驻层第3条已经够用，不需要额外任务层文件。跑`astock_data_layer.py`或`yf` CLI。

---

## 第三层：检索层（`memory_cases/`，按需捞3-5条）

用法：先看`memory_cases/INDEX.json`的`tags`字段（SCREEN/BUY/SELL/DATA/RESEARCH）或`rule_ids`/`tickers`字段做匹配，Read命中的case文件（每条100-200字，格式统一：情境/规则/证据/教训），上限5条。**不要因为要找一个案例就把对应的feedback_*.md整篇读完**——case文件里没写的细节，才追到归档层。

当前种子集（2026-08-14创建，8条，覆盖已验证的核心案例；87个feedback文件的完整回填是独立后续项目，不在本次任务范围内，见下方MEMORY.md建议）：

| case_id | 一句话 |
|---|---|
| `screening_two_axis` | 涨跌永不否决基本面 |
| `t11b_sell_signals` | 卖出只认4类预设信号，暴涨减半是最差策略(实盘验证) |
| `t14_scan_list_not_sell_reason` | 扫描名单变化不是卖出理由 |
| `t18_five_gate` | 5道门整合交易系统，回测净期望+5.31%/笔 |
| `strategy_astock_drift` | strategy_astock.md漏接07-06升级，本任务的直接诱因案例 |
| `yfinance_cn_data_source` | A股禁用yfinance |
| `position_veto_backtest` | 位置/盘中量比不否决买入 |
| `t13_sabct_threshold` | TB分数不是SABCT，跳过A-门槛买了两只都跌 |

---

## 第四层：归档层（不主动加载）

87个`feedback_*.md`原文(约50万字)、`MEMORY.md`索引里列出的其余知识/项目/参考文件，**默认不读**。触发读取的场景只有三种：
1. 用户明确要求溯源某条规则的完整历史/推导过程
2. 被challenge，需要给出原始证据链而不只是结论
3. `memory_cases/`里的case文件或本文件的路由表指向了某个文件但没给够细节

**不要**因为MEMORY.md索引里"看起来相关"就顺手把某个feedback文件整篇读进来——那正是当前130+条堆叠问题的成因。

---

## "该读的时候真读了"——机制设计（不靠自觉）

诊断：`feedback_screening_two_axis.md`两轴分离规则2026-06-30写对、实盘验证过，但8月的扫描/建仓判断里没被实际调用，等于白写了两个月。规则存在 ≠ 决策时被读取。同类事故第二例：`strategy_astock.md`漏接07-06的卖出制度v2升级，§3里的X1/X3两段已废止规则原样躺了一个多月才被发现(见`memory_cases/case_strategy_astock_drift.md`)。两次事故的共同根因：**多处存放同一决策的规则，加载靠记性，没有强制检查点。**

四层机制，按强度从弱到强：

1. **自报（弱，仅留痕）**：高风险输出（建仓/卖出verdict、执行卡片）前，输出一行`[加载协议] 场景=X，已读: [文件列表]`。不拦截任何东西，但让"到底读没读"这件事在transcript里可审计，而不是靠事后猜。

2. **结构收敛（中，降低出错概率）**：本文件是**唯一**决策路由入口，`sim-portfolio/CLAUDE.md`的"A股行为校准"一节已改为先指向本文件（不再是直接指向`strategy_astock.md`）。任务层表格明确标出"跳过"的死区，把"哪些是活规则"这件事从"记得banner"降级为"照表读"——降低认知负荷本身就是防塌陷手段(21+条同时堆叠时遵从率非线性掉；把决策相关的从130+砍到15+5~8个任务层文件，是直接对着论文结论下药)。

3. **强制门（强，已写好未激活）**：`scripts/decision_protocol_gate.py`——一个PreToolUse hook，拦A股账户的`execute_trade.py buy/sell/short/cover`调用，检查本session transcript里有没有Read过`DECISION_PROTOCOL.md`，没有就deny并提示该读哪个场景。脚本已写好、逻辑已实现（扫描transcript尾部400行找`Read`+`DECISION_PROTOCOL.md`的tool_use记录），**但没有接入`~/.claude/settings.json`**——这是全局hooks配置，属于"公共设施"，按`feedback_cross_session_protocol.md`必须先telegram广播给其他session、拿到明确许可再改，不能本任务单方面上线。激活方法见脚本文件头注释。设计上fail-open：hook自身报错/拿不到transcript一律放行，不会因为机制bug锁死真实下单。

4. **定期体检（推荐，未建）**：建议后续加一个`scripts/decision_protocol_audit.py`，定期(比如每次触发S12"改脚本必须同轮改文档"时顺带跑一次)grep所有任务层文件里的"已废止/待裁决/superseded/已作废"标记，凡是标记存在超过7天没被物理清理的，主动报出来——把`strategy_astock.md`那种"银行发现晚了一个月"的被动考古，变成主动巡检。这条本次没有实现，只是设计，标注清楚不算完成。

---

## 已知活跃漂移 / 命名冲突清单（预先标好，别自己重新发现一遍）

> ✅ **2026-08-14更新（D2重建任务）**：下表前4行原是"已知但未清理"的漂移，本任务已逐条裁决**并物理修改正文**（不再只是路由跳过）。完整证据对比见 `prompts/rule_conflicts_registry.md`（5对冲突全量记录，含本表未覆盖的卖出止盈②/L13信息新鲜度④/F15市场归属⑤）。

| 位置 | 问题 | 当前处理 |
|---|---|---|
| `strategy_astock.md` §3 X1/X3 | 阶梯止盈/暴涨自动减半，已被T11b/T18取代 | **已物理删除**（2026-08-14 D2），各替换为2行废止说明，不再需要"跳过" |
| `strategy_astock.md` §6 Regime表"持仓数"行 | 已被v9.2(06-23)"持仓数不约束"取代 | **该行已物理删除**（2026-08-14 D2），以§1 R2/§4为准 |
| `strategy_astock.md`§1 R2/R5/R6 vs `astock_scan_sop.md` R2/R5/R6 | **同编号不同义**：前者是仓位表/If-Then/PEG，后者是盘中量比/位置门/trailing PE。两份文档各自的R-series是独立命名空间 | 读的时候看清楚是哪个文件的R，本文件路由表已分场景避免同时出现 |
| T18内部"距突破点≤8%"买入位置门 | 被`astock_scan_sop.md` R5(08-06双段回测)推翻 | **已裁决并同步5处文档**（CLAUDE.md T18/integrated_trading_system.md/astock_scan_report_standard.md/astock_full_scan.workflow.js，2026-08-14 B4+D2双任务同步）：位置不否决买入，只按`position_size_mult()`连续taper影响仓位分档，永不清零。详见`astock_scan_sop.md`§3已证伪规则登记表#1 |
| L13"今天才知道→不买" vs T13/T16/scan SOP同日发现买入流程 | 原文对"已过完整SABCT+五维深扫的当日新发现"也会误判否决 | **已裁决**（2026-08-14 D2）：`strategy_astock.md`§5 L13已收窄第③项，只否决未过研究流程的裸买 |
| F15共识信号A股/美股归属 | `feedback_research_rules.md`§4.5曾误标"F15 A股修正v2"，与`research_protocol.md`v3.0(06-02)的A股/美股分拆版矛盾 | **已裁决**（2026-08-14 D2）：以research_protocol.md为准（A股维持15/15排除，美股用折让检查），已修正§4.5标题与内容 |
| 三腿仓位制度(科技/资源/防守各≥15%) | `astock_scan_sop.md`自己标注"尚未回测验证" | 当参考不当硬约束，偏离要显式说明理由 |

---

## 本文件的自我治理（防止本身变成第131条规则堆叠源）

- 常驻层硬顶15条。新增一条=必须先把旧的一条降级到任务层或检索层（one-in-one-out），不允许只加不减。
- 本文件只做路由，不重复解释规则的完整推导/历史——推导留在归档层，本文件里每条最多两行。
- 每次触发S12(改脚本接口/数据源)时，同轮检查本文件路由表是否需要跟着改，不允许脱节超过一个session。

---

*v1.0 | 2026-08-14 | 重建任务A5产出。生效范围：A股模拟盘会话。配套文件：`scripts/decision_protocol_gate.py`(强制门，未激活) / `memory_cases/`(检索层种子集，8条)。*
