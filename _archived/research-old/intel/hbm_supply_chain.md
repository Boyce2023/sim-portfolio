# HBM供应链深度分析
**写于**: 2026-05-27 | **适用标的**: MU (Micron) / 000660.KS (SK Hynix) / 005930.KS (Samsung)
**研究员**: Claude分析意见

---

## 一句话核心问题（F2供给端优先）

**HBM的结构性短缺能持续多久，谁在这个瓶颈节点上有最强的物理产能护城河？**

---

## 1. 市场份额：谁是最紧节点

### 当前格局（2025 → 2026预测）

| 公司 | 2025市占率 | 2026预测 | 核心驱动 |
|------|-----------|---------|---------|
| **SK Hynix** | 62% | ~50-55% | 供应NVIDIA ~90%的HBM；HBM4率先量产；良率近80% |
| **Micron** | ~21% | ~25-30% | 2026全年HBM供给已售罄；MU最强历史竞争地位 |
| **Samsung** | ~17% | ~20-28% | HBM4良率问题仍在，2026年目标产能提升50% |

**数据来源**: Introl Blog（Q2 2025实测数据）; Astute Group（2026预测）; TrandingKey分析

### 关键动态：Micron超越Samsung
- 2026年HBM市场出现结构性重排：Micron凭借良率优势和NVIDIA/AMD双线布局，已在市场份额上超越Samsung
- Samsung HBM4 12层堆叠良率问题是核心风险；SK Hynix良率~80% vs Samsung仍在攻关
- HBM4时代（2026 H2启动）是Samsung的翻盘窗口，但执行是关键

---

## 2. 定价：每GB多少钱，趋势往哪走

### 现货定价（估算，无一手公开披露）

| 产品 | 每stack容量 | 每stack价格(估算) | 每GB价格(估算) |
|------|-----------|----------------|-------------|
| HBM3 | 24 GB | ~$200 | ~$8.3/GB |
| HBM3E | 36 GB | ~$300 | ~$8.3/GB |
| HBM4 (预测) | 48 GB | ~$500 | ~$10.4/GB |

**注：以上价格为行业估算，非公司官方披露。来源：Silicon Analysts 2026，置信度：低（无一手来源）**

### ASP趋势

**近期（2025→2026）**：涨价周期明确
- Samsung和SK Hynix对2026年订单提价~20%（TrendForce, 2025-12-24；Digitimes, 2025-12-24）
- TrendForce预计2026年HBM3E ASP小幅上涨，高DDR5盈利能力加剧产能竞争，推升HBM3E价格动能
- HBM3E vs DDR5 ASP差距：2025年约4-5倍，2026年底有望收窄至1-2倍（意味着HBM3E需求拉动有所回落，或常规DRAM大幅涨价）

**中期（2026-2028）**：HBM4溢价周期
- HBM4预计以~55%营收比重占据2026年下半年主力（估算，来源：行业报告）
- 每GB价格随堆叠层数增加（8-Hi → 12-Hi → 16-Hi）而上升，因为：(1) TSV密度提升，良率下降；(2) 单次缺陷废整栈；(3) 测试成本大幅增加

---

## 3. 产能约束：瓶颈在哪，什么时候能解

### 三层瓶颈解剖（F2供给端优先框架）

#### 瓶颈1：HBM Die制造 + 堆叠（当前最紧节点）

- **物理约束**：HBM需将8-12块DRAM晶片通过TSV垂直堆叠。单颗缺陷废整栈，良率损耗乘数效应严重
- **技术难点**：从8层HBM3E → 12层HBM4 → 16层HBM4E，每增加一层：CTE失配导致翘曲和分层风险升高、铜扩散和TSV可靠性下降
- **良率现状**：SK Hynix ~80%（行业领先）；Samsung 12层堆叠资质认证仍在进行（来源：EnkiAI, PatSnap）
- **需求侧加速**：NVIDIA B200 = 192GB HBM3E（比H100的80GB增加140%）；AMD MI400 = 432GB HBM4
- **解决时间**：SK Hynix领先，Micron追赶中；Samsung若在2026年H2完成12层量产资质，可能使整体供给显著增加，但2026全年仍处于短缺

#### 瓶颈2：先进封装（CoWoS）

| 指标 | 数值 | 来源 |
|------|------|------|
| CoWoS产能 2024底 | ~35,000 wpm | FinancialContent/TokenRing |
| CoWoS产能 2026底目标 | ~130,000 wpm | FinancialContent/TokenRing |
| CoWoS产能 2027底目标 | ~170,000 wpm | 多方估计 |
| NVIDIA在CoWoS占比 | >60%（2025-2026） | 行业报告 |
| 当前交货周期 | 52-78周 | Silicon Analysts Q1 2026 |

- TSMC CoWoS-L/S 截至2025年12月已全满订单（TrendForce, 2025-12-08）
- AP3/AP5/AP6三个后端封装厂均满产至2027年，二三线ASIC客户几乎无法获得配额
- HBM4需要更精密封装技术（12-16层HBM + 2nm GPU die），CoWoS-L需求进一步上升
- OSAT替代方案：ASE的CoWoP作为替代，但良率和带宽密度仍弱于TSMC CoWoS

#### 瓶颈3：HBM测试（上升中的新瓶颈）

- HBM封装后内部通道无法访问，要求晶圆级高速测试前置（"shift left testing"）
- 12层 → 16层信号完整性验证复杂度非线性上升
- 测试成本和周期拖慢整体产能利用率（SemiEngineering, 2026）

### 产能约束总结

**最紧节点**：HBM die堆叠良率 = 当前最核心约束（SK Hynix占优）
**次紧节点**：CoWoS封装（TSMC垄断，NVIDIA优先，外部客户严重受限）
**上升节点**：HBM测试（HBM4时代更突出）

**解除时间**：
- HBM die：2028年有望部分缓解（SK Hynix M15X / Micron Idaho中期贡献 / Samsung量产资质）
- CoWoS：2027年扩容后局部改善，但NVIDIA继续吸走60%+，二线客户仍紧
- 整体供需：供给增速50-60%/年 vs 需求增速80-100%/年，缺口在2028-2029年前不会闭合

---

## 4. 需求：NVIDIA/AMD每颗GPU吃多少HBM

### GPU级HBM消耗

| GPU | HBM规格 | 每颗容量 | 8-GPU系统总量 |
|-----|---------|---------|-------------|
| NVIDIA H100 | HBM3 | 80 GB | 640 GB |
| NVIDIA B200 | HBM3E | 192 GB | 1,536 GB |
| NVIDIA B300 (Blackwell Ultra) | HBM3E | 288 GB | 2,304 GB |
| AMD MI350 | HBM3E | 288 GB | 2,304 GB |
| AMD MI400 (2026) | HBM4 | **432 GB** | 3,456 GB |

**数据来源**: TweakTown（AMD MI400确认）；Spheron/AceCloud（NVIDIA B200/B300规格）

### 需求规模测算

- Micron CEO在Q1 FY2026财报电话会议（2025-12-17）确认：Nvidia单季度贡献营收$23.2亿，占Micron季度营收17%，同比翻倍
- 超大规模云厂商2026年AI基础设施支出承诺总计$6500亿（行业报告）
- AI服务器单元增速：2025年"高十几个百分点"（Micron管理层）

---

## 5. 供需缺口：2026-2028平衡状态

### 供需动态矩阵

| 时间 | 供给增速 | 需求增速 | 平衡状态 | ASP方向 |
|------|---------|---------|---------|--------|
| 2026 | ~50-60% YoY | ~80-100% YoY | **严重缺口**，SK Hynix+Micron全年售罄 | 上涨20%+ |
| 2027 | ~60-70% YoY | ~50-70% YoY | **仍短缺，趋势收窄** | 横盘到小涨 |
| 2028 | ~60-70% YoY | ~40-60% YoY | **初步接近平衡**，部分品类可能过剩 | 可能下行压力 |

**来源**: 供给增速来自EnkiAI/PatSnap研究；需求增速来自Micron管理层+TrendForce预测

### 关键信号：Samsung 2026重大努力

- Samsung宣布2026年HBM产能提升50%（TrendForce, 2025-12-30）
- 若Samsung在2026年H2完成HBM4 12层量产资质 → 供给侧冲击，可能使短缺加速收敛
- 这是最大的供给侧尾部风险（对MU/SK Hynix的定价权是负面事件）

### 公司方指引

- **SK Hynix**（Q1 2026财报）："客户对HBM的需求已超过未来三年我们计划的产能"
- **Micron**（FY2026 Q1/Q2）："2026年全年HBM生产已全部售罄（含HBM4）"；Idaho新厂首批产出在"2027年中期"
- **SK Hynix CFO**："我们已卖出2026年全部HBM供给"

---

## 6. 终局：2028市场规模和CAGR

### 权威预测汇总

| 来源 | 2025E | 2026E | 2028E | CAGR |
|------|-------|-------|-------|------|
| **Micron管理层（最权威）** | $35B | - | **$100B** | **~40%** |
| NextPlatform（修正后） | $35B | - | $100B | 40%+ |
| Introl Blog | $35B | $9B（低估可疑）| - | - |
| 市场研究（GMInsights等） | $3-9B（方法论差异大）| - | - | 25-26% |

**注：小市场研究公司数字($3-9B)与Micron内部预测($35B 2025)差距巨大，可能是定义口径不同（全球HBM收入 vs 组件供应商口径）。投资分析以Micron管理层披露为准。**

### 终局判断（F17终局情景树）

**2028终局情景**：

**基本情景（概率55%）**：$100B TAM，SK Hynix ~45%、Micron ~30%、Samsung ~25%市占
- 驱动：HBM需求持续被AI训推规模扩张支撑，供给跟不上
- 对应：SK Hynix和Micron维持高ASP、高毛利率

**乐观情景（概率25%）**：$120-130B TAM，AI算力需求超预期
- 驱动：HBM4E渗透率快于预期、推理端HBM需求爆发、Agent时代GPU密度进一步提升
- 对应：SK Hynix M15X满产、Micron Idaho提前投产

**悲观情景（概率20%）**：$60-70B TAM，供给过剩
- 驱动：Samsung 2026年产能突破 + AI投资周期拐点 + HBM效率提升降低每美元算力的HBM消耗
- 对应：ASP崩溃，2028年毛利率回到正常化区间

---

## 7. 投资含义：MU vs SK Hynix

### F9淘汰法评估（Claude分析意见）

| 维度 | Micron (MU) | SK Hynix (000660.KS) |
|------|------------|---------------------|
| **HBM竞争地位** | 强（从落后到第二名，全年售罄） | 最强（62%市占，NVIDIA主供） |
| **产能节奏** | Idaho厂2027中才出产，短期产能受限 | M15X提前4个月开工，2026主力增量 |
| **良率护城河** | 有竞争力，但未公布具体数字 | 明确~80%（行业第一） |
| **定价能力** | 2026全年已锁定合同价 | 三年订单积压，议价权极强 |
| **宏观beta** | 美股，受US-China关税/出口管制影响 | 韩股，受韩元/全球记忆体周期影响 |
| **估值** | 需单独建模（美股，流动性好） | 需单独建模（韩股，外资可持有） |
| **F9 bear case** | 待建模（Samsung复苏 + AI投资放缓风险） | 待建模 |

### 核心投资thesis判断

**Buwen应注意（Claude分析意见）**：

1. **最紧节点已经定价了多少**：SK Hynix Q1 2026的72%运营利润率和198%的YoY营收增长已经市场公知，问题是当前股价隐含的是哪个终局情景
2. **Samsung恢复是最大的单点风险**：市场份额从17%升至25-28%的路径，若在2026年H2实现，将直接压制HBM3E/HBM4 ASP
3. **CoWoS仍是结构性护城河**：不管三家谁供HBM die，都需要经过TSMC CoWoS，这个节点的垄断定价权支撑整个产业链定价
4. **MU的不对称性**：Micron从2024年HBM落后位置到2026年跻身第二，还没被充分定价；但Idaho产能2027年中才贡献，2026年增量有限

### 需要进一步研究的问题

- [ ] MU和SK Hynix当前股价隐含的HBM ASP和市占率是多少（逆向DCF）
- [ ] Samsung HBM4产能资质进度：有没有任何一手信号（NVIDIA供应商资质认证节点）
- [ ] 推理端（inference）vs训练端（training）HBM需求比例：两者对HBM规格要求不同，影响需求质量
- [ ] CoWoS替代方案成熟度：ASE CoWoP/Intel EMIB能否在2027年前规模化

---

## 数据质量说明

| 数据点 | 来源 | 置信度 |
|--------|------|--------|
| SK Hynix Q1 2026营收52.6T KRW | 公司财报（CNBC/NineScrolls） | **高** |
| Micron HBM TAM $35B(2025)→$100B(2028) | Micron管理层FY2026 Q1财报电话会 | **高** |
| SK Hynix+Micron 2026 HBM全年售罄 | 公司CFO/CEO公开声明 | **高** |
| CoWoS产能35K→130K wpm | FinancialContent/TokenRing分析文章 | **中**（非TSMC官方） |
| HBM市占率SK Hynix 62% | Introl Blog (Q2 2025) | **中** |
| HBM3E每stack ~$300、每GB ~$8.3 | Silicon Analysts估算 | **低**（无一手来源） |
| 供给增速50-60%/需求增速80-100% | EnkiAI/PatSnap研究文章 | **低-中** |
| Samsung HBM4良率问题 | 多方行业报道（无官方确认） | **低** |

---

## 信息来源

- SK Hynix Q1 2026财报：CNBC (2026-04-23), NineScrolls, StorageNewsletter
- Micron FY2026 Q1财报：Motley Fool Transcript (2025-12-17), Blocks&Files, Futurum
- HBM市场份额：Astute Group, Introl Blog, TradingKey
- HBM定价：TrendForce (2025-12-24), Digitimes (2025-12-24), Seeking Alpha
- CoWoS产能：FinancialContent/TokenRing系列分析, TrendForce (2025-12-08), Tom's Hardware
- GPU HBM规格：TweakTown, Spheron Blog, AceCloud, Videocardz
- 供需分析：NextPlatform (2025-12-19), EnkiAI, Tom's Hardware, AI CERTs
- HBM TAM预测：DataM Intelligence (PR Newswire), Mordor Intelligence, NextPlatform

*注：本文件为Claude分析意见，非投资建议。核心数字引用均标注来源和置信度，低置信度数据不应直接用于模型输入。*
