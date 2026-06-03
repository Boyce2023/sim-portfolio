# 模拟盘投资策略 v2.0

> 价值投资 × 科技信仰 × 攻击性。不是巴菲特那种回避科技的价值投资——巴菲特不碰NVDA是错的。
> 我们相信改变世界的新科技和星辰大海，用价值投资的纪律去持有它们，用攻击性去兑现conviction。

---

## §0 第零原则：现金 = 亏损仓位（Cash Is a Losing Position）

**2026-06-03用户明确指出**："现金是一个不如QQQ或者三倍纳指的东西，在大跌以外，把现金当作亏损于指数的东西。你的思路一直不对。"

### 错误心智模型（必须覆写）

```
现金 = 安全/中性           ← ⛔ 错
买入 = 增加风险             ← ⛔ 错
卖出 = 降低风险 = 好事      ← ⛔ 错
留现金buffer = 审慎         ← ⛔ 错
```

### 正确心智模型

```
现金 = 每天跑输QQQ的亏损仓位   ← ✅ BULL regime下，现金年化~4%，QQQ年化~20%，日损1.6BP/dollar
满仓/杠杆 = 基准状态           ← ✅ 不是"激进"，是"正常"
卖出不买回 = 主动持有最差标的   ← ✅ 现金的夏普比任何conviction标的都低
现金留存 = 需要辩护的异常       ← ✅ 跟亏损仓位一样，必须有理由才保留
```

**Why：** 在BULL regime（VIX<20），每一美元现金都在支付机会成本。$100K现金1个月 = $1,400跑输QQQ。"安全"是幻觉——你没亏钱，但你确定性地跑输了benchmark，这就是亏损。

**决策翻转测试：** 每次想"留点现金安全"时，改问："我要不要用这些钱买QQQ？"答案在BULL regime下几乎永远是Yes。既然连QQQ都比现金好，那conviction更高的个股更应该买。

**ETF作为现金替代：** QQQ可作为现金的替代品持有，不计入9只仓位限制。

**唯一例外：** Regime = BEAR（VIX>30 或 SPY低于200日均线），或用户明确说"保守/降杠杆"。非BEAR regime下，正现金 > 5% NAV = Aggression Gate自动触发（详见§9）。

---

## §0.5 Regime定义

| Regime | 条件 | 现金规则 | 杠杆目标 |
|--------|------|---------|---------|
| **BULL** | VIX<20 **且** SPY高于200日均线 | 正现金>5%净值 = BLOCKED | **1.8x-2.0x** |
| **NEUTRAL** | 介于BULL和BEAR之间 | 现金<10%，减仓须有理由 | 1.3x-1.5x |
| **BEAR** | VIX>30 **或** SPY低于200日均线 | 可持有现金做防御 | 1.0x-1.1x |

Gate 4（现金拖累检查）和所有现金规则均以当前Regime为条件。

**⛔ 杠杆补回铁律（Leverage Backfill Rule）：** 卖出个股释放的资金必须立即用ETF/指数产品补回等额杠杆。可选工具：QQQ、sector ETF（SMH/XLF/XBI等）、国家ETF（EWY/FXI等）、杠杆ETF（TQQQ/SSO等）。**不允许卖了不买回，留现金 ≠ 主动基金该做的事。** 唯一例外：BEAR regime或用户明确说"降杠杆"。

---

## §1 投资哲学

**一句话：找到改变世界的公司，在合理价格买入，拿到故事兑现。**

四个支柱：
1. **研究深度 = Conviction** — 研究越深，conviction越高，仓位越重，拿得越稳
2. **终局思维** — 这个行业10年后什么样？谁在终局里占最好的位置？
3. **供给侧优先** — 看物理约束和制度约束，不听需求侧故事
4. **攻击性优先** — conviction够就重仓，不犹豫，不分散。80分以上直接攻，不等100分

**攻击性原则（底层逻辑，贯穿所有决策）：**
- **现金 = 每天跑输指数的亏损仓位（详见§0）。** 高conviction时满仓+杠杆是正确姿态，不是冒险
- **建仓就要有意义。** 新建仓最低10%起步，5%以下的"试探仓"=没conviction不该买
- **集中是超额收益的来源。** 10只以内，前5重仓占70%+，不为分散而分散
- **杠杆是conviction的自然延伸。** 不怕杠杆，怕的是没conviction就上杠杆
- **赢家要加不要卖。** Thesis+催化剂链完整的赢家，涨了是加仓理由不是减仓理由
- **速度就是alpha。** 研究完成→conviction确立→立即建仓。等回调=等别人先上车

不做的事：
- 不做日内交易、不追涨停、不做轮动
- 不用复杂规则替代判断力
- 不因为"涨多了"卖掉好公司
- 不因为"跌了"就加仓垃圾公司
- 不建3-5%的"感受一下"仓位——要么有conviction建10%+，要么不买

---

## §2 选股标准

### ⛔ 估值铁律：PEG唯一，Fwd PE禁用

**Fwd PE禁止单独作为估值论据。** 所有估值判断必须用PEG（= Fwd PE ÷ EPS增长率%）。

- Fwd PE是sell-side共识的直接产物，天然偏向"已在赚钱"的公司，系统性低估盈利拐点前的高增长公司
- PEG归一化了增长，才能跨增速比较（AVGO 26x vs MRVL 48x看似AVGO便宜，但PEG分别0.10 vs 0.43，结论相同但理由不同）
- `yf quote` 已将PEG置顶，Fwd PE降为PEG计算中间量

**违反判定：** 分析中出现"Fwd PE Xx太高/太低"而不附PEG = 违规。正确写法："PEG X.X（Fwd PE Xx ÷ 增长Y%）"

### 什么样的公司值得买

| 维度 | 要求 |
|------|------|
| **终局位置** | 在行业终局中占关键节点（瓶颈/平台/标准制定者） |
| **供给侧壁垒** | 物理约束（产能/交期/技术）或制度约束（授权/牌照/标准） |
| **增长质量** | 营收增长伴随利润率扩张，不是纯量增长 |
| **管理层** | 诚信 + 资本配置能力 + 战略清晰 |
| **催化剂** | 有明确的价值兑现事件（财报/产品发布/政策/订单） |

### 两类标的

**A类 — 科技变革（星辰大海）**
- AI基础设施：NVDA, AVGO, MRVL, ALAB, DELL, AMD, MU, AMAT, CLS
- 能源变革：GEV, VST, FSLR
- 特征：高增长、高波动、需要对技术路线有判断

**B类 — 价值重估（被低估的好公司）**
- 品牌/IP：DIS
- 特征：现金流稳、估值低、有催化剂触发重估

**C类 — 主线外价值（Off-Narrative Value）**
- 非科技或不在主线叙事中的公司，PEG<1.0 + T1-T2 bear case
- 持仓逻辑独立于主线叙事，需要有自身催化剂
- 特征：低分析师覆盖、机构忽视、估值而非叙事驱动

---

## §3 仓位管理

### 评级与仓位（SABCT v3.0）

| 评级 | 单一持仓上限 | 最低建仓 | 备注 |
|------|------------|---------|------|
| **S** | 50% | 20% | 最强conviction，能讲清三层逻辑 |
| **A+** | 35% | 20% | — |
| **A** | 25% | 15% | 核心持仓，thesis清晰+催化剂明确 |
| **A-** | 20% | 12% | — |
| **B+** | 15% | 12% | — |
| **B** | 12% | 10% | 标准持仓，有thesis但深度不够 |
| **B-** | 10% | 8% | — |
| **C** | 观察池 | — | thesis初步成立待验证，不建仓 |

> **核心原则：bear case管仓位，不管入选。** bear case大 = 仓位小，但标的仍在universe里。高bear case不是排除理由，是缩仓理由。

- 总持仓：不超过10只（集中才有超额收益）；QQQ作为现金替代不计入限制
- 前5大持仓占比目标：≥70%（集中在最高conviction标的上）
- 现金：**现金 = 亏损仓位（详见§0）。** BULL regime下正现金>5%必须部署
- 杠杆：**1.8x-2.0x目标区间（BULL regime正常状态）**，1.8x硬下限，2.0x硬上限（margin limit）。卖出个股→必须立即用ETF补回等额杠杆（§0.5杠杆补回铁律）。不用杠杆才需要理由
- 新建仓最低10%：低于10%不建仓（没conviction建什么仓）；EM/高波动标的允许8%下限

### 加仓与减仓

**加仓**：thesis被验证（财报beat、产品发布、订单落地）→ 加到上限
**减仓**：三个理由才减 —
1. Thesis被证伪（不是股价跌了，是逻辑错了）
2. 催化剂已兑现，没有下一个催化剂
3. 发现了更好的机会且当前标的conviction下降

**绝不因为"涨多了"卖。绝不因为"跌了"就加仓。**

---

## §4 买入纪律

### 估值原则（05-29回测修订）

- **PEG > 静态PE**：高增长公司用PE筛 = 看后视镜。PEG = Fwd PE ÷ 未来2年EPS CAGR。PEG<1.0 = 增长未被充分定价。盈利拐点公司用Revenue增速替代
- **任何单一指标不能auto-exclude**：筛选器排优先级，不关门。PE高但PEG<1的标的必须看完整thesis
- **催化剂链**：卖出前问"下一个催化剂在哪"。连续beat+guidance上修 = 链完整 → 不卖

买入前四个问题：
1. **为什么值这个价？** — 用PEG而非静态PE。市场定价多年盈利，不只一年
2. **Bear case是什么？跌多少？** — 说不出bear case = 没研究透。但bear case是过滤器，不是定价工具
3. **催化剂是什么？什么时候？** — 没有催化剂 = 不知道什么时候兑现
4. **Thesis兑现了多少？** — 看长/中/短三个时间框架：为什么涨/跌？原因能持续吗？市场已经看到了几成？还有多少是市场没看到的？见§4.5 TRA v2

买入前不做的事：
- 不因为"涨了"买（那是FOMO）
- 不因为"别人推荐"买（那是从众）
- 不因为"看起来便宜"买（那可能是价值陷阱）
- 不因为"PE太高"就排除高增长标的（PEG<1说明增长没被定价）
- 不买alpha已被提取的标的——标准不是机械看涨幅，而是问"以当前价格买入，我的edge是什么？"答不出来不买

---

## §4.5 Thesis兑现度评估（TRA v2 — Thesis Realization Assessment）

**核心原理：价格是thesis的计分板，但你必须读懂它在说什么，而不是只看涨跌幅。**

涨了不一定是"兑现完了"——可能是thesis刚开始被验证，后面还有更大的兑现空间。跌了不一定是"风险price in了"——可能是基本面在恶化，"便宜"其实是"坏了"。关键永远是**为什么**。

### 三时间框架分析（每次建仓/持有/卖出必做）

| 时间框架 | 看什么 | 告诉你什么 | 必须回答的问题 |
|---------|--------|-----------|--------------|
| **长期 (1-3Y)** | 股价结构性方向+幅度 | 公司是否经历了根本性变化 | 长期涨/跌的原因是什么？这个原因是结构性的还是周期性的？ |
| **中期 (3-6M)** | 当前趋势+相对大盘强弱 | 市场正在定价什么故事 | 中期驱动力是什么？(earnings cycle / macro / sentiment / rotation) 这个驱动力能持续吗？ |
| **短期 (1-4W)** | 近期异动+成交量变化 | 催化剂反应+情绪定位 | 近期走势对应什么事件？是否过度反应？ |

**三框架共振判断：**
- 三个时间框架一致向上 → 强趋势，顺势做多（但问：趋势在哪个阶段？）
- 长期涨 + 短期回调 → 可能是好入口（**前提：回调原因是情绪性的而非基本面恶化**）
- 长期跌 + 短期反弹 → 高概率是反弹陷阱（**除非有明确的基本面拐点**）
- 长期涨 + 中期盘整 → 等待催化剂，不急

### "为什么"优先于"多少"

**上涨时必须回答：**
1. **为什么涨？** — 是earnings beat（可持续）？叙事热度（会退潮）？短逼（一次性）？
2. **涨的原因能持续吗？** — 连续beat+guidance上修=自我强化趋势→持有。单一事件驱动=一次性→兑现后走
3. **公司本质变了吗？** — MOD从汽车零部件变成数据中心冷却=不同公司，旧价格基准失效。用新身份重新评估估值，不机械看52周涨幅

**下跌时必须回答：**
1. **为什么跌？** — 基本面恶化（收入/利润下滑）？还是情绪性（宏观恐慌/sector rotation/获利回吐）？
2. **跌的原因会持续吗？** — 如果是结构性恶化→"便宜"可能是"坏了"（价值陷阱）。如果是情绪性→可能是入口
3. **最近2-3次财报趋势？** — 连续miss+guidance下修=基本面在恶化→跌有道理，不抄底。连续beat但股价跌=市场可能在犯错→机会

### Thesis兑现度判断（定性为主，定量为辅）

不用机械公式。回答这个问题：**我的thesis里，市场已经看到了几成？还有多少是市场没看到或不愿相信的？**

| 状态 | 判断依据 | 投资含义 |
|------|---------|---------|
| **thesis未被发现** | 分析师少、叙事未形成、股价未反映基本面改善 | 最大alpha区间，重仓 |
| **thesis早期定价** | 开始有人讨论、股价有初步反应、但市场共识尚未形成 | 标准入场，正常评估 |
| **thesis充分定价中** | 叙事广为人知、分析师密集覆盖、但增长仍在持续验证 | 关键分叉：增长能持续→持有（NVDA式）；增长见顶→减仓 |
| **thesis充分兑现** | 催化剂链已兑现、增长开始减速、市场开始找下一个故事 | 卖出——不是因为"涨多了"，是因为剩余alpha<持有机会成本 |

**⚠️ PEG vs 兑现度矛盾时的处理：**
- PEG<1 + thesis广为人知 + 股价已大涨 → 增长快≠alpha还在。问自己：**如果我今天第一次看到这只股，以当前价格买入，我的edge是什么？** 答不出来→alpha已被提取
- PEG>1 + thesis未被发现 + 股价低迷 → 市场可能低估了增长的持续性。需要验证增长是否真的能持续

### 风险兑现度

"跌了"不等于"风险已price in"。必须回答：

1. **跌的原因对应哪个具体risk？** — 不能笼统说"风险已反映"。MA从$602→$492：是recession risk？是监管risk？是竞争risk？找到具体risk
2. **那个risk真的在发生吗？** — 如果是recession risk但经济数据还OK→市场过度悲观=好入口。如果确实在衰退→可能还没跌够
3. **估值压缩 vs 基本面恶化？** — 估值压缩（PE从30x→20x但EPS没变）=可修复。基本面恶化（EPS在下修）=结构性问题，低PE可能是陷阱

---

## §5 卖出纪律

| 信号 | 动作 |
|------|------|
| Thesis证伪 | 全部卖出，不犹豫 |
| 止损触及（-15%） | 重新评估thesis。thesis没变→持有；thesis动摇→卖 |
| 催化剂兑现 | 检查催化剂链：下一个<3个月→持有；无后续→减仓 |
| **Thesis充分兑现** | **催化剂链已兑现 + 增长开始减速 + 市场在找下一个故事 → 卖出。不是"涨多了"，是剩余alpha<持有机会成本** |
| 更好的机会 | 先确认新机会thesis成立，再换 |

**不卖的情况**：
- 股价跌了但thesis没变 → 持有甚至加仓
- 短期波动 → 无视
- 市场恐慌但公司基本面没变 → 持有
- 股价涨了很多但增长驱动力仍在持续+催化剂链完整 → 赢家要加不要卖（NVDA式：涨了5年thesis还在验证中）

---

## §6 做空

做空是核心竞争力之一，但只做确定性高的：
- Thesis清晰（商业模式有根本缺陷/估值泡沫/财务造假嫌疑）
- 催化剂明确（财报miss/解禁/政策变化）
- 仓位控制在总资产5%以内（单只），总空头不超15%

---

## §7 每日流程

1. 更新价格：`uv run --script scripts/update_prices.py`
2. 看持仓：`uv run --script scripts/session_view.py --market cn/us`
3. 看风控：`uv run --script scripts/risk_monitor.py --compact --no-save`
4. 有交易想法 → 讨论 → 确认 → 执行
5. 写日评：`daily-reviews/YYYY-MM-DD.md`

就这些。不需要更多流程。

---

## §8 开放宇宙扫描（Open Universe Scan）

### 茧房问题

系统只扫pre-curated的30只股票 = 永远在同一个池子里选。
修正：从"我觉得什么好"改为"市场在交易什么 → 我在其中找价值"。

### 叙事情报层（从A股Track B吸收）

扫描前先回答四个问题，建立"市场在交易什么"的全景：

1. **什么在涨？** — 过去1-4周板块ETF回报排名，找到资金正在流入的方向
2. **谁在领涨？** — 每个活跃叙事里区分Leader（涨幅最大+成交量最大）/ Early Mover（同叙事、涨幅靠前但未被广泛讨论）/ Follower（跟涨、滞后）
3. **为什么涨？** — 每个叙事的核心驱动力：earnings beat / 政策变化 / 供需拐点 / 资金再配置？区分"有基本面支撑的涨"和"纯流动性驱动的涨"
4. **走到哪了？** — 叙事生命周期判断：

| 阶段 | 特征 | 对价值投资者的含义 |
|------|------|------------------|
| Early | 少数领涨股异动，分析师覆盖<10人，ETF流入刚起 | 信息差最大，conviction够就重仓 |
| Acceleration | 二阶受益者开始涨，分析师密集initiate coverage | 追leader风险高，找supply chain上被忽视的节点 |
| Late | >20分析师覆盖，散户讨论热度高，ETF拥挤 | conviction自动降一档，只持有不新建仓 |
| Distribution | 领涨股放量滞涨或高位震荡，sector rotation开始 | 不买。已持仓评估是否减仓 |

这一层不决定买卖（那是PEG+F9+供给侧的事），只提供"市场正在定价什么"的背景板。

### 三步流程

1. **识别主线** — 当前美股最强的1-2个叙事是什么？资金在流向哪里？（叙事情报层的输出）
2. **三分类** —
   - **主线内**：直接受益于主线叙事的公司（含二阶受益者）
   - **主线外科技**：不在主线叙事中的科技公司（软件/非AI半导体/硬件）
   - **科技外**：非科技（医疗/金融/工业/消费/能源/材料/REITs）
3. **统一扫描** — 三类都用同一套PEG + F9 + 供给侧标准评估

### Leader→Supply Chain发散（从A股B→A发散吸收）

识别了领涨股后，沿supply chain找被低估的关联标的：
- Leader涨了 → 它的上游供应商/下游客户/配套服务商是谁？
- 其中PEG<1 + 还没涨的 = 价值投资的最佳入口
- 这是A股Track B"涨停→产业链→先手票"在美股的价值投资版本：不追leader，找leader背后被忽视的supply chain节点

### 规则

- 科技外类必须扫，无论主线是什么（反茧房强制项）
- 三类用同一标准评分，不因"不是我的领域"降低覆盖质量
- 主线晚期（Late）+ 分析师>20人 = 信息差已无，conviction自动降一档
- Distribution阶段的叙事：已持仓评估减仓，不新建仓
- 结果统一展示，不分优先级地呈现给决策者

### 数据源铁律（Agent扫描同样适用）

Agent手动扫描和脚本自动扫描必须使用同一套数据源，不允许"agent用WebSearch搜个数字就当事实"。

| 数据类型 | 必须用 | 禁止用 |
|----------|--------|--------|
| 价格/PE/市值 | `yf quote TICKER` | WebSearch搜来的价格 |
| EPS/收入/利润率 | `yf fundamentals TICKER` | 记忆中的数字/未验证搜索结果 |
| PEG | `yf quote`取数 → 手算(price ÷ earnings_estimate ÷ growth) | FinViz/Macrotrends等网站PEG直接引用 |
| 催化剂/earnings日期 | `yf quote` earnings_date + WebSearch交叉 | 单一来源 |
| 定性信息(供给侧/竞争/叙事) | WebSearch（这里可以用） | — |

**执行流程：**
1. Agent Phase 2（候选发现）→ WebSearch找标的名单 ✅
2. Agent Phase 3（深度扫描）→ **必须用`yf quote`+`yf fundamentals`取所有数字** ✅，WebSearch仅用于定性分析
3. Phase 4（验证）→ 候选shortlist全部跑 `us_ous_scanner.py --ticker X,Y,Z` 做6层正式验证 ✅
4. 未经 `us_ous_scanner.py` 验证的标的不进入 `ous_universe.json`

### 工具

`us_ous_scanner.py` — OUS统一扫描器，读取 `ous_universe.json`（62股三分类持久化宇宙），一条命令完成PEG+F21+数据验证+Delta追踪+跨分类反茧房验证。
- 全扫描：`uv run --script scripts/us_ous_scanner.py`（~4min，智能F21）
- 增量更新：`--ticker NVDA,AVGO`（只扫指定票）
- 单分类：`--category mainline/offnarr_tech/non_tech`
- 快速PEG：`--skip-f21`（~2min，跳过earnings_dates）

输出：三分类表格 → PEG Top 10跨分类排名 → Supply Moat Leaders → 反茧房验证（non_tech≥mainline）→ 分类平衡。

`decision_engine.py` 自动读取 `ous_universe.json` 计算持仓分类平衡（category_balance），non_tech权重<10%触发反茧房警告。

宇宙维护：`ous_universe.json` 手动更新，每次OUS后增删标的。每股必须有category+supply_moat。

### 触发条件

- 每月至少1次
- 或：组合连续4周跑输SPY
- 或：用户手动触发"全盘扫描"

---

## §9 Aggression Gate（执行前强制检查）

> **WHEN**: 即将执行任何交易批次（≥2笔交易）之前。
> **THEN**: 过以下4项机械检查，任一项FAIL则修正后才执行。
> **核心执行逻辑**: "先定目标杠杆和配比，再倒推交易量。" 不是"卖了多少余出多少再买"，而是"目标gross是多少，差多少就买多少"。

### Gate 1: 净敞口检查

```
计算: 本批次总卖出金额 vs 总买入金额
规则: 买入 ≥ 卖出 × 0.9（允许10%净减仓margin）
违反: 如果卖$500K但只买$300K → BLOCKED → 必须增加买入到≥$450K
例外: 止损/thesis被证伪的卖出不计入
```

### Gate 2: 杠杆下限检查

```
计算: 执行后预估杠杆 = 新gross / 新net_assets
规则: 
  - 执行后杠杆 ≥ 1.80x（BULL regime硬下限）
  - 目标区间: 1.8x-2.0x（正常操作区间）
  - 硬上限: 2.0x（margin limit，不超越）
违反: 如果执行后杠杆<1.80x → BLOCKED → 必须用ETF/指数补回至≥1.90x
       卖出个股后杠杆下降 → 立即买入QQQ/sector ETF/杠杆ETF补回等额敞口
       不允许"卖了不买回留现金"，这不是主动基金该做的事
例外: 用户明确说"降杠杆/保守一点" 或 Regime ≠ BULL
```

### Gate 3: 新仓位sizing检查

```
计算: 新建仓位金额 / 组合net_assets
规则: B级仓位 ≥ 10%，A级 ≥ 15%
违反: 如果新建仓只有2.7%或5.7% → BLOCKED → 必须加到≥10%
例外: EM/高波动标的可允许8%下限；C级观察池不建仓
```

### Gate 4: 现金拖累检查（§0第零原则执行层）

```
计算: 
  - BULL regime: 现金占净值比 = cash / net_assets（负现金=用margin=正常状态）
  - 现金日损 = |cash| × (QQQ年化回报 - 现金利率) / 252
规则: 
  - BULL regime下, 正现金 > 5%净值 = BLOCKED → 必须部署到conviction标的或QQQ
  - 每次展示portfolio时，现金行显示为"现金(日损$X vs QQQ)"
  - 负现金(margin) = 正常状态，不触发警告
违反: cash > 5% net_assets 且 regime ≠ BEAR → 强制提示"现金在亏钱，部署到哪？"
例外: regime = BEAR 或 用户明确说"保守/降杠杆"
```

### 失败模式清单（历史教训）

| 日期 | 失败模式 | 表现 | 根因 |
|------|---------|------|------|
| 2026-06-03 | 卖多买少 | 卖$499K只买$299K，杠杆降0.11x | 先卖后买，买入时"下意识"缩量 |

---

## §10 数据栈（US Data Stack v1.0）

> 50-agent审计结论（2026-06-02）。数据是投资决策的地基，地基错了楼必塌。

### 6层架构

| 层 | 用途 | 主源 | 备源 | 已知限制 |
|---|------|------|------|---------|
| **L1 价格** | 组合P&L，每日更新 | yfinance（±0.5%验证通过） | Finnhub（60/min RT） | 15分钟延迟；无盘前盘后；~0.4 req/sec限速 |
| **L2 基本面** | F9 bear case，利润率，收入 | SEC EDGAR XBRL API（权威） | yfinance fundamentals | EDGAR落后2-4周；yf某些字段不一致 |
| **L3 估值** | PEG = Fwd PE ÷ 2Y EPS CAGR | yf `earnings_estimate`（手算PEG） | FinViz PEG（5Y基准） | yf用FY+1非NTM，高增长股mid-year偏差可达20-40% |
| **L4 筛选** | OUS全市场扫描 | FinViz `finvizfinance`（PEG+sector+mktcap） | TradingView `tradingview-screener`（17,500股，无PEG） | FinViz PEG桶较粗（<1/<2/<3）；TV Forward PE字段为空 |
| **L5 事件** | F21 beat追踪，催化剂日历 | yf `earnings_dates`（24Q历史） | Alpha Vantage（25/day，earnings surprise） | AV日限额严格；guidance方向无免费结构化数据源 |
| **L6 验证** | 异常检测，交叉验证 | 阈值规则（div yield>10%，Fwd PE<0或>200） | FinViz vs yf PEG交叉验证（74%一致率） | 低覆盖股(<5分析师)数据可靠性下降 |

### 已确认可靠 ✅

- **价格**：15只股票 vs StockAnalysis交叉验证，全部偏差<0.5%
- **Earnings Estimate**：18只股票PEG计算成功，覆盖3-47位分析师
- **Earnings Dates**：24季度历史，NVDA/AAPL最新季度验证通过
- **财务报表**：5只股票收入/EPS与SEC EDGAR一致，无偏移
- **市场宇宙**：NASDAQ FTP 6,010只普通股（日更），$1B+约2,800只
- **FinViz筛选**：PEG<1全市场扫描609只，覆盖11个GICS板块，90秒完成

### 已确认有问题 ⚠️ + 修复状态

| 问题 | 严重性 | 状态 | 修复方法 |
|------|--------|------|---------|
| yf `dividendYield` 100x放大 | Critical | ✅ 已修复 | yf脚本改用`trailingAnnualDividendYield` |
| yf `forwardPE` 用FY+1非NTM | Medium | ⚠️ 绕过 | 用`price / earnings_estimate['+1y']['avg']`手算 |
| FinViz PEG vs yf PEG偏差>20%（26%的股票） | Medium | ⚠️ 已知 | FinViz用5Y增长，yf用2Y CAGR，高增长股必然diverge |
| 周期股PEG失真（MU 0.04, VST 0.11） | Medium | ⚠️ 标注 | CAGR>100%自动标记"Cycle PEG"，PEG数值无效 |
| 亏损股Fwd PE无意义（ASTS, RKLB） | Low | ⚠️ 标注 | 负EPS时PEG/Fwd PE = N/A |
| SPUT.U.TO不可获取 | Low | ⚠️ 已知 | 用OTC替代ticker SRPTY |
| yf无盘前盘后价格 | Low | ⚠️ 已知 | Earnings night需外部确认 |

### 被排除的数据源

| 工具 | 原因 |
|------|------|
| FMP Premium ($59/mo) | 关键endpoint（estimates/surprise/screener）需付费 |
| Twelve Data | Forward PE/div yield修复需Pro $79/mo |
| OpenBB SDK | 免费层=100% yfinance包装，无增量数据，overhead大 |
| pandas-datareader | 2020年停更，大部分backend已死 |
| yahoo_fin | 2021年停更，Yahoo API变更已break |
| Macrotrends | DDoS防护，无法编程访问 |

### PEG计算铁律

```
Forward PE = 当前价格 ÷ earnings_estimate['+1y']['avg']
2Y EPS CAGR = (FY+1 EPS ÷ yearAgoEPS) ^ 0.5 - 1
PEG = Forward PE ÷ (2Y CAGR × 100)

⚠️ 以下情况PEG无效：
- CAGR > 100% → 周期股失真，标"Cycle PEG"
- yearAgoEPS ≤ 0 → 无法计算CAGR
- 分析师 < 5人 → 估值可靠性低，标"Low Coverage"
- FY+1 EPS < FY+0 EPS → 增长放缓/衰退，标"Declining"
```

### 新增脚本

| 脚本 | 用途 |
|------|------|
| `uv run --script scripts/us_peg_calculator.py [TICKERS] [--portfolio]` | 可靠PEG计算（手算，非yf直取） |
| `uv run --script scripts/us_data_validator.py [TICKERS] [--portfolio]` | 数据质量检查（7项异常检测） |
| `uv run --script scripts/ous_prescreener.py [--peg-max 1.5] [--all-sectors]` | OUS自动化预筛（FinViz+yf） |
| `uv run --script scripts/earnings_rhythm.py [TICKERS] [--portfolio]` | F21 Earnings节奏追踪（beat频率+趋势） |
| `uv run --script scripts/catalyst_calendar.py [--portfolio]` | 60天催化剂日历（earnings+macro+div） |
| `uv run --script scripts/us_universe_builder.py` | US股票宇宙构建（NASDAQ FTP，6,010只） |

### OUS扫描自动化升级

旧流程：30 agents全手动，~45分钟
新流程：`ous_prescreener.py`替代Phase 2（90秒完成600+候选），agents只做Phase 1（叙事判断）+ Phase 3（深度分析）
**Agent需求：30 → ~14，时间：45分钟 → ~20分钟**

### yfinance Rate Limit参考

| 操作 | 吞吐量 | 建议 |
|------|--------|------|
| `yf.download()` 批量价格 | 1 ticker/sec (50只=50秒) | 批量用download，不用逐只fast_info |
| `fast_info` 逐只 | 0.4 req/sec（被限速） | 不要无延迟循环 |
| `earnings_estimate` 逐只 | 0.56 req/sec | 500只约15分钟，加0.2s延迟 |
| 批量上限 | 无硬429，软限速 | 50只一批，批间1秒 |
