# A股筛股全流程 + 报告展示规范化 SOP

> **权威版 v1.0 | 2026-07-20 | 本文件是流程+展示标准的唯一权威。**
>
> **与现有文档的关系（防重复）**:
> - `astock-workflows.md` v2.0 — 旧3步SOP(扫描/深扫/持仓复盘)+报告4块格式+样例。本文档**不取代**，其报告格式/执行卡片模板/七条筛股铁律仍有效。本文档在其基础上**新增**：完整Step0-6流程（含交易侧整合）、扫描入口规范（跑astock_full_scan而非旧astock_v3）、HTML报告强制标准、扫描触发/调用规则。
> - `integrated_trading_system.md` — 买入双确认/卖出5道门/回测参数的权威定义。本文档直接引用不重复定义。
> - `data-interfaces.md` — 脚本接口/数据源铁律。本文档引用不重复。
> - `feedback_full_scan_and_sizing.md` — 2026-07-16血泪纠正的历史记录（"完整扫描≠只选股"+"sizing分档"）。本文档是该纠正的**落地执行标准**。
> - `feedback_astock_screening_sop.md` — 旧memory版精简规则，已被本文档和astock-workflows.md v2.0覆盖。

---

## 零、铁律先读（动手前必看）

每次扫描前先读这两项，不是"可以参考"，是门禁：

1. **⛔ 健康检查**：`python3 scripts/health_check.py` — 数据链19项全绿才开扫，有FAIL先修再扫。跳过=系统腐烂中途才发现（血泪根因）。
2. **⛔ 完整扫描入口唯一**：`astock_full_scan.workflow.js`（选股×交易侧焊一体，Step0-6）。**禁止跑旧的astock_v3（纯选股侧，无交易侧整合=残缺输出）**。

---

## 一、完整筛股流程（Step 0-6，写死，不许缩水）

### Step 0 — 宏观体检（regime定调）

**做什么**：A股自上而下宏观体检，定调当日market water level，输出sizing系数。

**规格**：
- 先跑 `python3 scripts/news_layer.py` 读内部消息面（写 `data/news_today.json`）
- 核心指数近1周/1月/3月（沪深300/中证1000/创业板/科创50）
- 全市场市值中位数 vs 指数（揭穿失真：指数涨+中位数跌=缩圈）
- 赚钱效应（涨家占比，收窄=缩圈尾声）
- 今日板块强弱 + 风格（大盘/小盘/成长/价值）
- 消息面（隔夜美股费半/纳指 + 政策 + 龙头公告），判断大跌是错杀还是趋势反转
- ⛔ regime锚定多周结构（单日不算，1周/1月/3月连续背离才是真缩圈）

**产出**：regime定调（`REGIME=普涨` / `REGIME=缩圈` / `REGIME=普跌`）+ sizing系数（普涨1.0/缩圈0.5/普跌0.3）

**用哪个脚本**：Step0 agent直调（`news_layer.py` + 腾讯qt.gtimg + astock_data_layer），数据源禁ak.*_em东财（NO_PROXY问题）。

---

### Step 1 — 18树全市场扫描（产品树→埋伏候选）

**做什么**：18条产品树，每树判今天状态+is_hot+埋伏候选（追到矿端，供给侧不妥协）。

**规格（写死，违反报错）**：
- **18树数量硬校验**（workflow代码 `if (TREES.length !== 18) throw new Error()`）
- 每树输出 schema：`{tree, today_state, is_hot, ambush[{ticker, name, env, why_ambush}]}`
- 18树定义（不许改、不许合并）：
  - AI算力(VR200机架重构) / AI端侧(AI手机换机) / 人形机器人(替代人力)
  - 电动车(消费者+碳中和) / 固态电池 / 智能驾驶(Robotaxi)
  - 苹果新形态(折叠+AI眼镜) / 创新药(MNC扫货) / 脑机/手术机器人
  - AI供电(电网扩容) / 制冷剂(配额涨价) / 钨硬质合金(刀具+军工)
  - 半导体设备国产化 / 商业航天/卫星互联网 / 可控核聚变/核电
  - 军工/低空经济 / 稳定币/金融科技 / 猪周期反转
- 候选池：**全树埋伏候选都进池**（不只热树），热树优先排序
- 去重：同一ticker只进一次；排除当前持仓

**产出**：全树候选池（allCands，按热度排序）

---

### Step 2 — 全树Top候选5维深扫（头部打分表）

**做什么**：对候选池前30只（MAX_DEEPSCAN=30，热树优先）做5维深扫，产出完整头部打分表。

**规格**：
- **深扫上限30只**（防agent爆炸，取强供给侧热树优先）
- **5维深扫内容（每只必须全部完整输出，⛔严禁压成一行摘要）**：
  1. **基本面轴（产品树环节 + 供给侧Edge全文）**：物理/制度壁垒？中国份额？追到矿。Kill Shot（真概念蹭/暴雷/估值无边际）。中国edge三分（真受益/卡脖子吃不到/伪关联）。
  2. **量价结构**：主升中（放量上涨：量比≥1.5且涨>3%/台阶突破/回踩不破）vs 末段见顶（放量滞涨：量比≥2且涨<1.5%/高位巨阴/破位）。**⛔涨幅大≠末段，看量价结构**。
  3. **SABCT评级**：A+/A/A-/B+/B。A-为建仓最低门槛，B+以下只进观察池。
  4. **二维裁决**：probe（基本面好+主升中）/ watch（基本面好+末段等回踩，必填三件套）/ reject（基本面差）/ hold（已持仓）。**⛔禁因涨过/PE高reject好基本面**（涨跌永不否决基本面）。
  5. **催化剂日期 + watch三件套 + 止损 + 一句话**：催化剂事件+具体日期。watch必填：回踩位+失效期5-8日+未触发动作。止损类型。一句话非共识supply-side thesis。

**产出格式（每只完整结构）**：
```
{ticker, name, tree, env, is_hot, verdict: {
  decision: probe/watch/reject/hold,
  fundamental: "基本面轴全文（Edge真假+份额+概念蹭判断）",
  trend: "量价结构全文（量比数值+涨幅+结构判断）",
  sabct: "A+/A/A-/B+/B",
  size_now: "建议仓位%",
  stop: "止损价(-X%)",
  catalyst_date: "YYYY-MM-DD",
  watch_expiry: "回踩位¥XX | 失效期N日 | 未触发→[动作]",
  one_line: "一句话非共识thesis"
}}
```

**数据源**：腾讯qt.gtimg.cn / ak.stock_zh_a_daily新浪 / astock_data_layer，**禁ak.*_em东财，禁import yfinance**（A股市值少算10倍）。

---

### Step 3-5 — 交易侧整合（买入双确认 + 卖出5道门 + Sizing）

**做什么**：把头部打分表（SABCT）交给整合脚本，代码级跑趋势信号/买入双确认/sizing/持仓5道门，产出建仓调仓计划。**⛔用代码级整合层，不靠agent肉眼估sizing**。

**规格**：
1. 把头部打分表写 `/tmp/full_scan_cands.json`
2. **调 `organism_portfolio_builder.py` 实跑**（非可选步骤）：
   ```bash
   python3 scripts/organism_portfolio_builder.py \
     --candidates /tmp/full_scan_cands.json \
     --regime [普涨/缩圈/普跌] \
     --holdings
   ```
3. 脚本输出JSON：`build_list`（建仓裁决含action/size_pct/突破%/量价）+ `hold_actions`（持仓守/减/清）
4. 基于脚本输出产出四块报告

**sizing分档规则（已焊进decide_buy，不许flat sizing）**：
- **大力满档**：probe裁决 + 放量突破/近突破（距前高≥-3%）→ regime系数×A级仓位上限
- **小仓半档**：probe裁决 + timing次一点（放量但未突破，距前高-8%~-3%）→ 半档
- **watch = 0**：量价未确认（距前高<-8%/普通/末段）→ 不建仓，列回踩清单

**⛔当机械trend_signals与深扫agent判断冲突时（如机械=probe但深扫=watch末段长上影）：深扫更细，优先深扫**。

**卖出5道门（`integrated_trading_system.md` 权威，不重复定义，仅列触发）**：
| 门 | 触发 |
|---|---|
| 1 破位 | 收盘 < 前10日最低 |
| 2 灾难线 | 收盘 ≤ 成本 -12% |
| 3 round-trip | 峰值≥+15% 又吐回成本 |
| 4 thesis证伪 | 供给约束/主beta/催化时间线变坏 |
| 5 催化兑现 | 利好落地+动能衰竭 |
| — | **没门响 = 让它跑** |

**持仓判断脚本辅助**：`python3 scripts/portfolio_trend_check.py` — 看多窗口结构，禁单日量比下结论（T18）。

---

### Step 6 — 四块报告（⛔头部打分表必须完整展开，不许压行）

**做什么**：把Step0-5的产出整合成标准四块报告（markdown），最终由 `scripts/scan_report.py` 渲染成HTML。

**四块结构（按序，缺一不完整）**：

**① 宏观定调**（2-3句）
- regime = [普涨/缩圈/普跌] + 持续几周 + 所处阶段（早期/中段/尾声）
- sizing系数 + 关键背离（如指数涨但市值中位数跌=缩圈）
- 关键消息面catalyst（推动今日主线的核心事件）

**② 完整头部打分表（⛔核心，用户痛点，必须完整展开每只5维，不许压成一行摘要）**

表格必须包含以下列，每只候选一行，**probe/watch/reject分组配色（probe绿色/watch黄色/reject灰色）**：

| 标的 | SABCT | 供给侧Edge（非共识全文） | 量价结构（量比+涨幅+结构判断） | 二维裁决 | 建议仓位% | 距突破% | 催化日期 | watch三件套/止损 | 一句话 |
|------|-------|--------|--------|------|------|------|------|------|------|

**⛔补充要求**：
- 每只的"供给侧Edge"列必须是完整非共识判断（不是"有供给约束"这种废话）
- 量价结构列必须有量比数值和涨幅（"放量主升"不够，要"量比1.8×涨4.2%，台阶突破"）
- watch的三件套必须完整：回踩位+失效期+未触发动作
- **⛔严禁**把整行压成"[名称]：一句话，建议观察"——这是用户明确批评的"太随意"

**③ 建仓/调仓逻辑**（决策层，说清为什么）
- **probe建仓**：哪几只现价probe→为什么（双确认过了：SABCT≥A- + 突破前25日高 + 距突破≤8%）→ 建多少（脚本sizing分档结果）→ 止损线
- **watch等回踩**：哪几只等回踩→回踩位具体价位→失效期→若触发则建多少
- **持仓守/减/清**：脚本hold_actions结果，5道门触发情况，配thesis-delta三问（供给约束/主beta/催化时间线变了吗）
- ⛔若全watch零probe：老实说"缩圈今日无双确认建仓，列回踩清单待触发"。不硬凑probe。

**④ 执行情况/执行卡片**（每个probe标的一张，格式同astock-workflows.md）
```
🟢 [名称 代码] | SABCT: A- | Tier: T2(半仓)
现价 ¥XX(astock_data_layer) | PEG X.X(G来源:Gn) | 前瞻PE XXx(26E/27E)
供给侧thesis(一句非共识): [别人给不了什么+为什么市场没看到]
催化剂: [具体事件] [具体日期]
中国edge: 真受益/卡脖子吃不到/伪关联 [一句判据]
主题位置: 启动/主升早/台阶/尾声
执行卡片: 建仓¥XX-XX | 止损¥XX(-12%) | 仓位X% | 出场:[催化剂过+什么信号出现]
```
- 若全watch零probe：列回踩清单（每个watch：回踩位/失效期/触发后建仓计划）
- ⑤（可选）**持仓复盘**（单独附，不混入①-④）：逐只5道门状态 + thesis-delta三问状态 + 建议动作（等go才执行）

---

## 二、HTML报告强制标准

### 触发条件
扫描完成（Step0-6全部跑完）→ **自动调 `scripts/scan_report.py` 生成HTML** → 返回HTML路径给用户 + chat里给结论摘要。

**⛔摘要可短，但HTML必须完整**（摘要≠报告替代品）。

### HTML报告必须包含（5块）
1. **宏观定调区**：regime + sizing系数 + 今日关键消息面，用色块区分（普涨绿/缩圈黄/普跌红）
2. **完整头部打分表**：全部≤30候选，**每只展开5维**（probe绿色区/watch黄色区/reject灰色区分组）
   - ⛔禁压行：点开/折叠都可以，但展开态必须显示5维完整内容
3. **建仓/调仓逻辑**：probe建仓（双确认说明+sizing）+ watch回踩清单 + 持仓5道门状态
4. **执行卡片区**：每个probe一张完整卡片（同上格式）；全watch时展示回踩清单
5. **持仓复盘**：独立区块，逐只5道门触发状态 + thesis-delta + 建议（等go才执行）

### HTML格式要求（遵循 `~/.claude/standards/report_visual_standard.md`）
- 读 `report.css`，不手搓CSS
- probe分组：绿色背景框
- watch分组：黄色背景框
- reject分组：灰色，折叠
- 头部打分表用正常表格，无斑马纹
- 字号：h2=14px, h3-h4=12px, 正文/表格=10-9px

---

## 三、触发与调用规则

### 触发词
用户说以下词时，启动完整扫描流程：
- "扫描" / "完整扫描" / "筛股" / "今天的扫描" / "跑一下扫描" / "扫一下"
- "完整的扫描" / "帮我扫一下" / "今天能买什么"

### 调用顺序（严格按序）
```
Step 0: python3 scripts/health_check.py  # 全绿才继续
Step 1: 运行 astock_full_scan.workflow.js
  → Step0: news_layer.py + 宏观体检 → REGIME
  → Step1: 18树并行扫描 → 候选池
  → Step2: Top30深扫 → 头部打分表
  → Step3-5: organism_portfolio_builder.py → 建仓/持仓裁决
  → Step6: 四块报告(markdown)
Step 2: python3 scripts/scan_report.py  # 渲染HTML（由另一agent建，本文档记录接口规范）
Step 3: 返回HTML路径 + chat结论摘要
```

### 结论摘要格式（chat内）
```
扫描完成 [YYYY-MM-DD HH:MM] | regime=普涨/缩圈/普跌 | sizing=1.0/0.5/0.3
头部打分表：X只候选（probe: N只 / watch: N只 / reject: N只）
🟢 probe建仓：[名称] ¥XX | SABCT: A- | 仓位X% | 止损¥XX
⚠️ watch回踩：[名称] 回踩¥XX（失效期：N日）
持仓：[门触发情况，如无=全守]
详细报告：[HTML路径]
```

### Regime-Sizing联动
| Regime | Sizing系数 | 含义 |
|--------|-----------|------|
| 普涨 | 1.0 | 满档建仓 |
| 缩圈 | 0.5 | 半档，精选 |
| 普跌 | 0.3 | 小仓埋伏或不建 |

⚠️ **PIT回测校准（`integrated_trading_system.md` §优先级3）**：regime闸门在趋势年是拖累（+114%→+40%），**默认关**，只在明确系统性风险时手动收缩，不做机械日频闸门。本表sizing系数用于**个股仓位上限调节**，不是"缩圈不扫描"。

---

## 四、禁止清单（历史错误，严禁重犯）

| ❌ 错误 | ✅ 正确 |
|--------|--------|
| 跑旧astock_v3当"完整扫描" | 跑astock_full_scan（含交易侧） |
| 扫描一半就出报告 | 全部agent返回+脚本跑完才出 |
| 头部打分表每只压成一行 | 5维完整展开（供给侧/量价/SABCT/裁决/催化+止损） |
| flat sizing（全部建9%） | 按probe/watch/reject + 距突破%分档（大力/半档/0） |
| 深扫只跑热树候选 | 全18树Top候选（MAX_DEEPSCAN=30） |
| 缩圈强行凑probe | 老实说"今日无双确认建仓+回踩清单" |
| 持仓混在主报告里 | 持仓单独放（不混入①-④） |
| 报告缺交易侧（无双确认+5道门） | Step3-5必须实跑organism_portfolio_builder.py |
| chat结论替代HTML完整报告 | HTML必须完整，chat只是摘要 |
| 机械双确认覆盖深扫agent判断（末段标probe） | 深扫更细，冲突时深扫优先 |
| import yfinance取A股数据 | astock_data_layer（禁yfinance，市值少算10倍） |
| ak.*_em东财接口 | 腾讯qt.gtimg.cn / ak.stock_zh_a_daily新浪（NO_PROXY问题） |
| 卖方研报（罗列+不表态） | 买方决策（哪几个能买+为什么+多少+何时卖） |

---

## 五、数据源速查（完整见 `data-interfaces.md`）

| 用途 | 工具 | 禁止 |
|------|------|------|
| A股价格/市值/PE | `astock_data_layer.get_batch_prices` | ❌ yfinance（少算10倍） |
| A股指数实时 | `astock_data_layer.get_index_quotes` | ❌ ak.*_em（超时） |
| A股全量/涨停 | `astock_data_layer.get_full_market / get_limit_up_stocks` | ❌ ak.*_em |
| 消息面 | `python3 scripts/news_layer.py`（内部）→ WebSearch补 | — |
| 宏观数据 | astock_regime.py + news_layer.py | — |
| 定性（竞争/催化剂新闻） | WebSearch | ❌ WebSearch价格/PE（未验证） |

---

*v1.0 | 2026-07-20 | 来源：astock_full_scan.workflow.js实际代码 + feedback_full_scan_and_sizing（07-16血泪教训） + astock-workflows.md v2.0 + integrated_trading_system.md + data-interfaces.md*
*配套脚本（由其他agent建设中）: scan_report.py（HTML渲染器，读Step6四块markdown→输出HTML）*
