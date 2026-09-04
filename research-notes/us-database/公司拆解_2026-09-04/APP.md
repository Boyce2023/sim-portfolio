# AppLovin (APP) — 为什么是2024-2025最大长牛(+1638%)

数据来源: 本地财报电话会全文(`~/Desktop/选股/earnings call/APP/FY2021Q1~FY2026Q2.txt`) + 高盛模型(`APP_model.xlsx`, P&L Summary/Revenue Summary sheet, data_only) + `yf quote/history APP`(2026-09-03/04验证)。凡标"(call)"为管理层原话/电话会披露口径, 标"(模型)"为财务报表/模型算出的数字, 未验证的一律标"材料未覆盖"。

---

## 1. 生意是什么

AppLovin是一个**移动广告DSP(需求方平台)**, 本质是"用AI模型帮广告主在AppLovin的MAX交易所里买量, 并抽成"。历史上曾经是"游戏发行商+广告平台"双业务, 2025年剥离游戏发行业务后变成纯广告技术公司。

**收入结构演变(模型 Revenue Summary sheet, USD mn)**:
| 季度 | 总收入 | 广告平台收入(Advertising) | Apps(自有游戏)收入 |
|---|---|---|---|
| 1Q23 | 715.4 | 354.8 (50%) | 360.6 (50%) |
| 4Q23 | 953.3 | 576.5 (60%) | 376.8 (40%) |
| 4Q24 | 1372.8 | 999.5 (73%) | 373.3 (27%) |
| 1Q25 | 1484.0 | 1159.0 (78%) | 325.0 (22%, 最后一次单独披露) |
| 2Q25起 | — | 全部并入"Advertising Revenue"(游戏发行业务已卖出) | 不再存在 |
| 1Q26 | 1842.4 | 1842.4 (100%) | — |
| 2Q26 | ~1920 (call: "almost $2 billion") | ~1920 | — |

**谁付钱、单位经济怎么算(call, FY2023Q4, line 378-383)**: 广告主(游戏发行商/后来的电商及跨品类广告主)在MAX交易所里通过AXON模型竞价买流量, AppLovin对**实时竞价(real-time bidding)成交收5%的take rate**, 非实时竞价的瀑布流(waterfall)不收费。广告主付费逻辑是ROAS(投产比)驱动: 广告主设定目标ROAS, AXON模型预测哪个用户最可能转化/花钱, 出价买这个曝光——本质是"AppLovin替广告主做媒体采买的自动化决策", 收入=广告主愿意花的钱×take rate。

---

## 2. 增长的引擎: 量、价、结构三者中谁主导

**结论: 主要是"量"(广告主愿意投放的预算规模), 由AXON模型的预测精度提升驱动, 不是简单提价。**

- **AXON 2.0**于**2023年Q2**上线(call FY2023Q4, line 104: "AXON 2.0...in Q2 last year")。上线后效果(call, FY2023Q4管理层原话): "software platform revenue growing by 76% in 2023...in Q4 2023, our incremental revenue had an approximate 80% flow-through to Adjusted EBITDA"。
- **机制解释**(call, FY2023Q4, line 285-298, Adam Foroughi原话): "AXON 2 makes them [predictions] better than the prior version, and that creates a lot of efficiency gain"——他把AXON迭代类比GPT3→3.5→4, 强调这是"预测更准→广告主用同样的钱买到更多有效曝光→广告主敢投更多预算"的正反馈, 不是涨价。
- **量化证据**(call, FY2025Q1, line 280-291, Adam原话): "pre-Axon 2...customers get better ROAS and more scale...ad spend on the platform has roughly **quadrupled(4倍)** since we rolled out Axon 2...that's [not] ROAS is 30% to 40% better...It means at the comparable ROAS, they get 30% to 40% more scale." ——即模型每次迭代不是让每笔转化更贵, 而是让广告主在同样的目标ROAS下能安全地把预算规模扩大30-40%, 这是量增而非价增。
- **收入增速的结构性拐点(模型, YoY增速)**: 广告收入YoY从1Q23的+199%(低基数)降到常态化的2Q23 +28%, 之后随AXON 2扩散重新加速: 1Q24 +91%, 2Q24 +75%, 3Q24 +66%, 4Q24 +73%; 2025年因剥离游戏发行业务并表口径变化, 广告收入(含并表后全部收入)同比进一步冲高: 2Q25 +77%, 3Q25 +68%, 4Q25 +66%。
- **eCPM/客户留存**: **材料未覆盖**——电话会全文(FY2023Q4~FY2026Q2共11份)搜索"eCPM"关键词零命中, 管理层从不披露具体eCPM/留存率数字, 只给方向性描述(ROAS/scale)。这是AppLovin一贯的"黑盒"披露风格(见下第5节)。

---

## 3. 供给侧约束/护城河

**护城河=数据规模×模型迭代速度形成的"数据飞轮", 不是单一技术专利。**

- **飞轮语言**(call, FY2025Q1 line 136-141, FY2025Q2 line 317-318/574/636-637, Adam/Matt原话): "You get a really strong flywheel embedded into this type of a machine learning model. As we get more impressions, more engagements with the ads, more conversions, the thing just continues to get smarter and smarter"; "the data flywheel and the system that benefits both sides"。
- **规模优势的来源**: MAX是AppLovin自建的程序化广告交易所, 覆盖大量移动应用的广告库存(供给侧); AXON是需求侧竞价引擎。两者绑定意味着AppLovin同时看到"哪个广告在哪个应用哪个用户身上转化", 这个数据量级第三方DSP(如Meta/Google体系外的独立DSP)难以复制——因为它们要么没有自己的交易所(供给), 要么没有跨应用的转化归因数据。
- **管理层对可复制性的表态**(call, FY2024Q3 line 452, 分析师提问原话转述管理层此前立场): "Axon 2 is so good that you could put the open code out, and you don't think that there would be competitors who would be able to catch up with you"——即管理层自己认为，即使公开算法代码，没有等量数据和交易所规模，竞争对手也追不上，护城河是数据/规模而非算法保密。
- **谁能复制/需要多久**: **材料未覆盖具体时间估计**。管理层从未给出"竞争对手需要X年追上"的量化判断，只反复用"data moat"(FY2025Q1 line 70: "our growing data moat and AI expertise")定性表述。判断：Meta/Google体系内的自有DSP规模远大于AppLovin，但它们服务的是自己的广告位库存（walled garden），不做第三方MAX式跨应用竞价；能做同类跨应用DSP+交易所双边网络的潜在对手（如Unity/ironSource, Digital Turbine）过去两年在游戏广告市场份额持续被AppLovin挤压，暗示复制难度高，但会议材料没有给出直接的时间量化——这是判断层，不是材料层。

---

## 4. 单位经济与现金流

**逐季数据(模型 P&L Summary, Non-GAAP口径, USD mn / %)**:

| 季度 | 毛利率(Non-GAAP GP%) | 经营利润率(Non-GAAP OpInc%) | Adj.EBITDA margin | FCF | SBC占收入% |
|---|---|---|---|---|---|
| 1Q23 | 77.4% | 36.3% | 38.3% | 283.1 | -11.6% |
| 4Q23 | 81.4% | 49.1% | 50.0% | 339.1 | -9.1% |
| 4Q24 | 83.5% | 60.1% | 61.8% | 695.0 | -7.4% |
| 1Q25 | 85.4% | 66.3% | 67.7% | 818.2 | -4.1% |
| 4Q25 | 87.0% | 80.3% | 84.4% | 1308.6 | -4.7% |
| 1Q26 | 89.6% | 84.1% | 84.5% | 1291.4 | -4.5% |
| 2Q26 | ~89.3%(推算) | ~84.0%(推算, call: EBITDA margin约83%) | ~83.8%(call: "up 58% YoY, margins expanding ~300bps") | 材料显示FCF转化率本季偏低, 管理层预计全年恢复至约75%(call line 86) | ~-4%区间(模型2Q26E -3.9%) |

**利润率跃升的两大驱动**:
1. **游戏发行业务(Apps)被剥离**——这是低毛利业务(1Q25最后披露: Apps收入325M, 相比广告平台业务毛利率结构性拖累), 2025年Q2起并表口径全部是高毛利广告平台收入, 直接推高整体毛利率/EBITDA margin台阶式上升(4Q24 61.8% → 4Q25 84.4%)。
2. **经营杠杆**: S&M/R&D/G&A占收入比例逐季下降(S&M占比从1Q23的23.7%降到1Q25的10.1%再到2Q25的2.1%——注意2Q25这个断崖式下降主因是分母/分子口径因剥离业务重编, 需谨慎解读为"纯效率提升", 部分是并表结构变化)。

**会计上可疑/需注意处**:
- **SBC(股权激励)占收入比重逐季下降**(1Q23 -11.6% → 4Q25 -4.7%), 部分原因是剥离游戏工作室后员工基数减少, 部分是收入分母扩大摊薄——GAAP净利润与Non-GAAP指标之间的差距(GAAP EPS vs Adj.EBITDA)主要来自这部分SBC和一次性交易成本调整, 属于常规科技公司做法, 材料中未发现异常收入确认问题。
- **一次性项目**: 2024年Q4宣布剥离Apps业务, 交易对价$900M(现金$500M+私有公司少数股权, call FY2024Q4 line 76), 2025年Q1末完成交割(call FY2025Q1 line 597)。这笔交易的少数股权部分公允价值计量存在主观性, **材料未覆盖**具体的减值/公允价值调整细节。
- **回购**: 2025全年回购+扣缴约640万股, 耗资$2.58B, 全部由自由现金流出资(call FY2025Q4 line 97-98), 剩余回购授权约$3.28B。资本配置激进, 未见明显财务工程痕迹(无杠杆回购, 2Q26净杠杆仅0.1x EBITDA, call line 87)。

---

## 5. 首次跳涨那份call, 当时能不能看出后面还有13倍

**关于日期的更正**: 用户给出的日期"2024年2月2日"与本地材料记录的实际call日期不符——AppLovin报告2023Q4业绩的电话会**call_date为2024年2月14日**(材料文件头部`# call_date: Feb 14, 2024`), 股价的历史性跳涨发生在这次财报公布后(2/15前后), 不是2/2。以下分析基于这份FY2023Q4(实际是那次导致史诗级跳涨的call)。

**能看出的信号(call原文, line 26-38, 60, 104-117, 379-381)**:
1. "software platform revenue growing by **76%** in 2023" + "our incremental revenue had an approximate **80% flow-through** to Adjusted EBITDA"——这两个数字合在一起说明: 收入增长的边际利润极高, 是纯软件平台的经济模型, 不是靠加人加钱堆出来的增长。这是一个"有心人"能读出来的高质量增长信号。
2. 管理层明确把增长归因于"a market shift to real-time bidding"结构性行业变迁+AXON 2.0升级(line 60), 而不是单一季度的运气——real-time bidding渗透率提升是可持续的行业级beta, 叠加AXON 2这个alpha。
3. take rate经济学被首次清晰披露(line 378-381): 5% take rate只在real-time bidding时收取, 行业正在从瀑布流转向real-time bidding——这意味着同样的广告量, take rate基数在扩大, 是一个可预测、可外推的收入结构性利好, 且当时渗透率远未到顶(暗示后续还有空间, 但call没给具体渗透率数字)。
4. Q4 2023单季度EBITDA margin 50%(call line 25: "That's an impressive 50% Adjusted EBITDA margin"), 相比同行业公司算是极高水平——一个只读这份材料的人能判断这是一门好生意, 但"好生意"不等于"13倍"。

**事后才显得重要, 但当时没有/难以判断的**:
1. **AXON延伸到非游戏品类(电商/CTV)的可行性和规模**——这份call里管理层已经提到"expand into new applications...significantly broaden our TAM"(line 33-34), 但完全是定性展望, 没有任何量化指引。真正让市场意识到"这不只是个游戏广告公司"的是2024年下半年到2025年Q1的电商self-serve平台数据("ad spend quadrupled since Axon 2"这个数字是**2025年Q1才披露的**, FY2023Q4当时不存在)。
2. **游戏发行业务(低毛利、低增长的Apps segment)会被整体剥离**——这个决定在2024年Q4才宣布(即之后整整4个季度), FY2023Q4完全没有暗示。这一举措是后续毛利率/EBITDA margin台阶式跃升(61.8%→84.4%)的核心结构性变量, 2024年2月的读者不可能预判。
3. **AXON模型能持续每年迭代且效果不衰减**——2024年2月的call只能看到AXON 2.0一次成功迭代的结果, "模型持续变好"这件事需要之后8个季度(2024-2025全年)反复验证才能确立为可信赖的复利机制。这是"时间验证的信任", 不是2024年2月那一份材料能给的。
4. 具体的股价倍数(+1638%)显然不是任何一份call能推导的——call给的是business quality signal, 不是价格目标。

**结论**: 2024年2月那份call能让一个仔细读材料的人判断"这是一家利润率结构极佳、且处在行业结构性渗透率提升周期中的高质量成长股"，理由充分到可以建仓，但看不出"未来两年13倍"这个具体量级——那需要后续AXON持续迭代不衰减 + 电商品类真正放量 + 游戏发行业务剥离释放利润率三件事全部兑现，其中后两件在2024年2月完全不存在于公开信息里。

---

## 6. 卖出游戏工作室业务对财务结构的影响

- **交易条款**(call, FY2024Q4, line 75-77, 649-651, Matt Stumpf原话): 2024年Q4宣布"signed a term sheet to divest our apps business", 对价总计**$900M**(其中现金$500M + 剩余部分是private company的少数股权), 目标2025年Q2内完成交割, 需监管批准。"selling the entirety of the apps business...that would all come off of the P&L and the balance sheet all at once"。
- **交割确认**(call, FY2025Q1 line 597, Matt原话): "After signing the agreement today with Triple Dot to divest the apps business...transaction is going to close towards the end of the quarter"——买方确认为Triple Dot Studios，2025年Q1季末前后完成。
- **对营收结构的影响**: Apps收入(1Q25最后一次单独披露: $325.0M, YoY -14.4%)整体从合并报表消失, 2Q25起AppLovin变成100%广告平台收入的公司(见第1节表格)。
- **对利润率的影响**: 剥离前Apps segment的EBITDA margin显著低于广告平台(4Q24 Apps segment EBITDA margin约19%, call line 78: "$71 million in Adjusted EBITDA representing a 19% margin", 对比同期公司整体Adj.EBITDA margin 61.8%)。剥离后整体margin结构性跳升, 是"利润率暴力抬升"叙事的直接账面来源, 不是单纯的经营效率提升——这是解读2025年利润率数据时必须扣除的结构性因素。
- **对UA成本的潜在影响**(call, FY2025Q1 line 598-600, Matt原话): "Within the guidance, we have not assumed any incremental uplift from having those studios be external parties and the premium rate on the user acquisition cost that we would normally charge...It is not a material impact on the business one way or the other"——管理层明确说剥离后, 这些游戏工作室作为外部客户在MAX平台买量的溢价对整体业务"不会有实质性影响", 即剥离不构成对广告平台收入的重大风险敞口。

---

## 7. 现在(2026年9月)的状态

**最新一季(2Q26, call_date 2026-08-05)数据**:
- 收入: **~$1.92B, YoY +53%**(call summary), 略低于guidance区间中值(call line 27: "just below the midpoint of our guidance range")。
- Adj. EBITDA: **$1.61B, YoY +58%**, margin同比扩张约300bp, 但**同样略低于guidance区间**(call line 50, 78)。
- 环比flow-through(增量收入转化为EBITDA的比例): 本季仅70%(call line 79), 低于此前常态80%左右, 反映本季追加了训练/推理算力投入。
- 管理层给出的未达标原因(call line 32-38, Adam原话): "Our pace of meaningful model improvement was lighter than normal during the quarter, and the next step up in model performance landed just after quarter end"——即模型迭代节奏放缓, 新版本在Q2结束后才上线, 属于时点错配(timing), 管理层强调"nothing we saw suggested weakening advertiser demand"(需求端没有走弱, MAX发布商收入环比双位数增长)。
- **消费者(非游戏, 电商等)业务表现**: 本季消费者广告主投放规模创新高, 环比4Q25季节性峰值仍高28%(call line 41-42: "finishing 28% above Q4 2025 levels")。
- 3Q26指引: Adj. EBITDA guidance $1.71-1.74B, YoY +48-50%, margin约83%(call line 97)——增速已经从2025年动辄70-80%YoY的Adj.EBITDA增速降至50%左右量级, **增长斜率在放缓**, 这是趋势层面的结构性变化, 不是一次性噪音。

**股价(yf验证, 2026-09-03/04)**:
- 现价 **$313.58**, 52周区间 **$297.50 - $745.61**, 距52周高点回撤约**-57.9%**(与题面"-57%"吻合)。
- **2026-08-05(2Q26财报公布当日)收盘$417.80 → 2026-08-06(次日)收盘$335.67, 单日跌幅约-19.7%**——这是本轮回撤的最主要单一驱动事件, 直接对应上文的"guidance miss + 模型迭代放缓"。
- 财报后至今(8/6~9/3)股价继续阴跌, 从$335.67进一步跌到$313.58附近, 累计再跌约-6.6%, 显示市场对"模型迭代放缓是否只是一次性timing问题"仍未完全买账, 属于持续的信任重建期。

**YTD -50%(题面口径, 材料未直接核实起点价, 但与52周高点-57.9%及财报暴跌-19.7%在数量级上一致)的基本面原因归纳**:
1. 直接导火索: 2Q26财报/指引不及预期, 核心解释是AI模型(AXON)迭代节奏放缓——而AXON模型迭代速度正是本报告第2节论证的"增长引擎"本身, 引擎打嗝直接冲击市场对"复利永续"的定价假设。
2. 增速能见度下降: 3Q26 EBITDA指引增速降至48-50%YoY, 相比2024-2025年常态化的60-80%区间明显放缓, 市场对高估值成长股的增速斜率变化极敏感(PEG逻辑下, 分母端估值收缩幅度可能大于增速下滑幅度本身)。
3. Consumer(电商/非游戏)业务虽然环比数据亮眼(高于Q4峰值28%), 但管理层自己承认"consumer isn't yet large enough to fully smooth a quarter"(call line 43)——即第二增长曲线还不够大, 不足以对冲主业务(游戏)模型迭代的短期波动, 市场此前对"consumer会成为新引擎、抹平游戏业务周期性"的预期被证伪(至少节奏上被推迟)。

---

## 我的判断(Claude分析意见, 3条)

1. **这轮+1638%的长牛核心是"利润率结构重估+可持续增长引擎"的双击, 不是单纯讲故事**: 剥离低毛利游戏发行业务(4Q24 Apps EBITDA margin仅19% vs 广告平台业务同期61.8%整体margin)带来了一次性、可验证的利润率台阶(2025年Adj.EBITDA margin从43%附近跳到68%+, 见模型年度列2024全年49.3% → 2025全年71.8%), 叠加AXON模型迭代带来的"同ROAS下预算规模扩大30-40%"(2025Q1管理层原话)这个可复利的量增机制——两个轮子同时转是双位数季度涨幅持续两年的根本原因, 单一因素都撑不起13倍。

2. **2Q26的暴跌本质上是在测试这套双引擎逻辑里最脆弱的那个假设——"AXON模型每次迭代都不衰减"是否永远成立**。这一假设此前从未被证伪过(2023-2025年历次电话会管理层反复强调模型持续变好, 且过去8个季度数据支持), 2026年Q2第一次出现"模型迭代节奏变慢导致guidance miss"的公开案例, 即便管理层解释为timing问题(新版本Q2结束后才上线), 市场选择先price in"这套复利机制可能不是线性/永续的"这个更悲观的假设, 这是典型的高估值成长股在增速拐点附近的估值双杀(利润率仍在扩张, 但增速斜率下降本身就压缩倍数)。

3. **护城河判断上, 材料支持"数据规模+交易所-DSP双边绑定"是真实且难以短期复制的壁垒, 但没有材料能证明这个壁垒能对冲"模型迭代放缓"这类执行风险**。数据飞轮解释了"为什么AppLovin能持续变强", 但不解释"为什么某一个季度会变慢"——这提示这门生意的短期波动性(尤其是single-quarter层面)本质上仍然是"AI模型研发进度"这个高度依赖内部工程节奏、外部难以预测的变量, 不是一个可以简单线性外推的稳态复利机器, 这是这份研究给出的最重要的风险提示, 也是解释当下-57%回撤为何发生、以及未来能否修复的关键分歧点。

---

## 材料缺口(Material Gaps)

1. **eCPM、留存率、具体转化率提升幅度**——11份电话会全文均无披露, 管理层从不给这类颗粒度数字, 只给方向性/倍数性描述(如"4倍ad spend")。
2. **护城河的量化复制时间**——管理层只做定性表述("data moat"), 没有任何一份call给出"竞争对手需要几年追上"的量化判断; 本报告第3节关于Meta/Google/Unity等潜在竞争对手的复制难度分析部分基于合理推断, 已标注为判断层, 非材料层结论。
3. **卖方研报**——用户目录`~/Desktop/选股/研报/`下唯一一份APP相关PDF是高盛《Q2'26 Earnings Review》, 因时间限制本报告未深入提取该PDF全文内容(仅使用其标题作为2Q26 miss叙事的旁证), 若需要卖方对"模型改善节奏"和目标价的具体测算, 需另行处理该PDF(注意: 按D8铁律, 卖方目标价/评级不可作为本报告估值论据, 仅可提取事实数据)。
4. **YTD起点价格未直接用yf核实**——本地yf CLI的history命令只返回最近30条记录(工具限制), 未能直接拉到2026年1月初收盘价核实题面"YTD -50%"的精确起点, 本报告用52周高点回撤(-57.9%, 已用yf quote验证)和财报单日跌幅(-19.7%, 已用yf history验证)两个独立验证过的数字做交叉支撑, 量级吻合但未做逐日精确核实。
5. **2024年2月2日 vs 2月14日的日期差异**——已在第5节明确指出并更正为2月14日(本地材料唯一记录), 未搜索验证是否存在另一次2月2日的市场事件(如行业新闻/竞品消息)导致题面日期表述, 若用户有其他信源指向2/2, 建议进一步核实。
