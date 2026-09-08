# 美股持仓 thesis 关键词表（供 broadcast.py 实时读取）

维护者：us session · 最后更新 2026-09-07
**用途**：命中任一关键词 → 直接投递到 us inbox，**不走 ticker 匹配，不受 REQUIRE_CTX 约束**。
**起因**：2026-09-07 抽检漏报「卡塔尔 LNG 运输船返航」——它不含 cheniere/sabine pass 字样，被 LNG 的正向门挡掉，但它是 Cheniere 本周 thesis 的核心变量。
⛔ **判据（main 09-07 认同，记为通则）**：**方向未知使一条情报更该投递，不是更该丢。** 船"返航"可能是通行恢复(利空)也可能是受阻加深(利多)，两个方向含义相反 → 必须让 us 自己读原文。门做不了方向判断。
⛔ **维护规则**：清仓或 thesis 变化时，同一动作里改这张表。`why` 栏写清它是 thesis 里的哪个变量——**没有 why 的词表半年后没人敢删也没人敢改**。

⛔ **关键词栏是机器读的，不是给人看的**（2026-09-07 事故）：栏内**只准放词和英文逗号**。加粗、括号注释、⚠️符号都会被解析器吃掉或劈碎——我写 `F-35(⚠️需限定,见表下注)` 时那个中文逗号把它切成两个非词，**连原本正常的 F-35 一起失效**，双方都无感知。**一切说明写进 why 栏或表下小节。**

| ticker | 权重 | 关键词 | why（它是 thesis 里的哪个变量） |
|---|---|---|---|
| HALO | 9.9% | ENHANZE, 皮下注射, subcutaneous, 药物递送, drug delivery, 专利到期, patent cliff, 罗氏, 强生, Roche, J&J, royalty | thesis 是"ENHANZE 平台专利+大药企独家授权的高转换成本"，**证伪点是专利悬崖**（2027后部分到期）与大客户集中度。授权方动向直接改 thesis |
| LLY | 9.2% | GLP-1, tirzepatide, Zepbound, Mounjaro, 诺和诺德, Novo Nordisk, 司美格鲁肽, semaglutide, 口服GLP-1, PBM, 医保控价, 减肥药产能 | thesis 是"专利保护至2030+产能多年建厂周期"，**证伪点是寡头竞对与定价压力**。诺和的任何进展直接压 thesis |
| LNG | 9.1% | 霍尔木兹, Hormuz, 卡塔尔LNG, Qatari LNG, 海峡通行, LNG运输船, LNG tanker, FERC, DOE出口许可, take-or-pay, 照付不议, Sabine Pass, Corpus Christi, LNG新增供应 | thesis 是"出口终端多年建设周期+FERC/DOE许可壁垒+照付不议锁定现金流"，**证伪点是2026-27全球新增供应集中投产压低价差**。⭐霍尔木兹通行状况决定卡塔尔LNG能否入市，是本周最活的变量 |
| V | 8.8% | 稳定币, stablecoin, FedNow, 实时支付, real-time payments, interchange, 交换费, 反垄断, antitrust, swipe fee, 卡组织 | thesis 是"双寡头清算网络+转换成本+持续提价权"，**证伪点是绕开卡组织的清算路径**（稳定币/FedNow）与交换费诉讼 |
| VRTX | 8.4% | 囊性纤维化, cystic fibrosis, CF, Trikafta, Alyftrek, 疼痛管线, VX-548, suzetrigine, 1型糖尿病, islet cell | thesis 是"CF 近乎垄断+罕见病审批壁垒"，**证伪点是CF渗透已近饱和，新管线(疼痛/糖尿病)放量速度**。管线读数是唯一能改 thesis 的东西 |
| TDG | 7.1% | 售后件, aftermarket, FAA适航, FAA certification, 唯一指定件, sole source, 商用航空周期, 国防预算, defense budget, 净债务EBITDA, 杠杆 | thesis 是"单一供应商+FAA认证壁垒+年年提价"，**证伪点是净债务/EBITDA 5x+对利率敏感**。⭐若9/11 CPI走加息路径，四只双负股里它第一个重审 |
| RGLD | 5.8% | 金价, gold price, 实际利率, real rates, 矿权, royalty, streaming, 版税, 矿山寿命, mine life, 续约 | thesis 是"版税模式锁定多年现金流+矿产稀缺"，**证伪点是金价回落直接压版税收入**，以及部分矿山寿命有限的续约风险 |
| ICE | 5.6% | NYSE, 洲际交易所, Intercontinental Exchange, 抵押贷款科技, ICE Mortgage, 住房成交量, 交易所牌照, 指数业务, 流动性池 | thesis 是"交易所牌照稀缺+网络效应"，**证伪点是 ICE Mortgage 分部对利率与住房成交量敏感** |
| CEG | 5.6% | 核电, nuclear fleet, PPA, 购电协议, 数据中心供电, data center power, Calvert Cliffs, Clinton, Byron, Braidwood, 核准入, 电价, 容量市场 | thesis 是"全美最大核电机队，投资周期内不可复制"，**证伪点是熊方7分指出的：股价YTD-20.5%且距高点-27.8%，市场可能不信AI供电叙事**。PPA签约是最直接的证真/证伪 |
| BWXT | 5.6% | SMR, 小型模堆, 微堆, microreactor, 海军核推进, naval nuclear, 单一来源合同, sole-source, DOE, 核级认证, 项目延误 | thesis 是"海军核推进仅两家之一+核级认证需10年+"，**证伪点是国防预算周期与核项目执行延误**（核项目常见）。SMR订单流是长期约束的验证 |
| ADBE | 5.6% | Firefly, Creative Cloud, PDF标准, Figma, Canva, AI原生设计, 生成式设计, 提价, price increase, freemium, 订阅增长, Creative Agent, 第三方模型, 算力成本 | thesis 已经很弱(供给侧仅5/10)，**证伪点是AI原生工具侵蚀+定价权流失**。⭐9/10财报第一件事看它会不会**第三次推迟提价**；另外它把Agent放进Claude/ChatGPT/Copilot/Gemini分发，模型厂上移会两头夹 |
| WM | 5.5% | 填埋场, landfill, 选址许可, NIMBY, 固废, 环评, Stericycle, 医疗废物, 并购整合, 垃圾处理提价 | thesis 是"填埋场牌照与选址壁垒+区域垄断+定价权"，**证伪点是Stericycle并购协同不及预期**，以及利率高位压制资本密集型估值 |
| RTX | 4.6% | F-35, F135, GTF发动机, Pratt Whitney, 普惠, Collins Aerospace, 防空系统, 中东冲突, 国防预算, 锻件产能, 供应链瓶颈, 导弹订单, 停飞, grounding | thesis 是"军工三巨头+涉密认证+项目锁定"，**证伪点是GTF质量问题拖累交付与锻件产能瓶颈**。中东升级是催化不是thesis |
| FCX | 4.4% | 铜价, copper price, 铜精矿, Grasberg, 印尼, Indonesia, 资源民族主义, 智利, 秘鲁, 冶炼费, TC/RC, 能源转型金属 | thesis 是"矿山10年+开发周期+许可壁垒+铜是能源转型刚需"，**证伪点是印尼资源民族主义**与铜价随中国需求回调 |
| NEM | 3.5% | 金价, gold price, 实际利率, 矿权审批, 矿业成本, 能源成本, 人工成本, 品位下降, AISC, 全维持成本 | thesis 是"金矿不可再生+新矿8-10年投产周期"，**证伪点是矿业成本通胀侵蚀利润率**（能源/人工），叠加金价回调时的高弹性 |
| NBIX | 1.6% | Ingrezza, VMAT2, Austedo, 迟发性运动障碍, tardive dyskinesia, Crinecerfont, NBI-568, 精神分裂, DOJ调查, 专利悬崖 | probe仓。thesis 是"Ingrezza专利+罕见适应症壁垒"，**证伪点是Austedo份额侵蚀+单产品集中度**。⭐**DOJ调查**是我在盯的独立风险项，出现计提用语要立刻知道 |

## 跨持仓的宏观变量（命中即投递，不归属单只）

| 关键词 | why |
|---|---|
| 8月CPI, 核心CPI, core CPI, 9月加息, rate hike, FOMC, Waller, 沃勒, 沃什, Warsh | **9/11 CPI 是金对簇17%与生物医药29%久期敞口的共同裁决点**。美银+0.22%(加息) vs 花旗+0.18%(按兵)，分歧仅4bp但结论相反 |
| 美元指数, DXY, dollar index | **扳机A的判据**（连续3收盘>99.60且5/10/30日同向 → 金对降至12%） |
| 霍尔木兹, Hormuz, 伊朗封锁, 油价飙升 | 同时打 LNG(利多)、RTX/TDG(利多)、以及通胀路径(利空久期) |

## ⚠️ 需要限定的关键词（2026-09-07 加）

**只有 `F-35` 需要**。它属于「**被当成计量单位用的名词**」——太有名以至于被拿去衡量别的东西（实例：`@SemiAnalysis_` 拿一架 F-35 的造价去衡量 Rubin GPU 成本，与国防采购毫无关系）。

**限定**：`F-35` 需同时出现下列之一才算命中 —— `采购, 交付, 订单, 预算, procurement, delivery, order, budget, 对外军售, FMS`

⛔ **`F135` 不需要限定，且必须是独立关键词不是限定词**。它是普惠造的 F-35 发动机型号、RTX 的直接业务，没人拿它当尺子。**真出交付或质量问题时，报道常直接写 F135 而不写 F-35** —— 若它只作为 F-35 的限定词存在，`F135 engine core upgrade funded in FY27 budget` 这类会整条漏掉（main 单测实证）。同理 `停飞/grounding` 也提为独立词。

**自查**：全表 198 词里属于"计量单位型"的只有 F-35 一个。`Grasberg`/`Calvert Cliffs`/`ENHANZE`/`Trikafta`/`Ingrezza` 这类专名反而安全，没人拿它们当尺子。
