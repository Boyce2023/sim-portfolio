# AI半导体Supercycle终局情景树（F17框架）
**日期**: 2026-05-27 | **框架**: F17终局情景树 + F9 v2 4-tier淘汰 | **Claude分析意见**

---

## 0. 核心问题（一句话）

**AI半导体supercycle 5年后（2030/2031），哪个节点赢家通吃，哪个节点被商品化——当前价格隐含的终局是否正确？**

---

## 1. 市场基础数字（有来源，2026-05验证）

| 数据点 | 数值 | 来源 | 置信度 |
|--------|------|------|--------|
| 全球DC capex 2030预测 | $1.7万亿（Dell'Oro, 2026-01） | Dell'Oro Group press release | 高 |
| 另一口径 | $7万亿（含全部基础设施，McKinsey） | McKinsey estimate | 中 |
| Top 4超大规模商capex 2026 | ~$6000亿 | DataCenterKnowledge | 高 |
| AI加速器市场2024 | $1405亿 | Mordor Intelligence | 中 |
| AI加速器市场2030预测 | $4400亿（Mordor）/ $6000亿+（Bloomberg Intelligence, 2033） | 多来源 | 中 |
| HBM市场2024 | ~$170亿 | Mordor Intelligence | 高 |
| HBM市场2028预测 | ~$1000亿 | Micron管理层指引 | 高（一手） |
| HBM市场2030预测 | ~$980亿，CAGR 33% | Mordor Intelligence | 中 |
| DC半导体总TAM 2024 | $2090亿 | Yole Group | 中 |
| DC半导体总TAM 2030预测 | ~$5000亿 | Yole Group | 中 |
| NVIDIA FY2026实际营收 | $2159亿（+65% YoY） | NVIDIA官方财报 | 高 |
| NVIDIA FY2027 consensus | ~$3668亿 | StockAnalysis/分析师共识 | 高 |
| NVIDIA Q1FY2027 guidance | $780亿 | NVIDIA官方 | 高 |
| NVIDIA Q2FY2027 guidance | $910亿 | NVIDIA官方 | 高 |
| Broadcom AI芯片2027目标 | >$1000亿 | CEO Hock Tan原话 | 高（一手） |
| Dell AI服务器FY2027目标 | ~$500亿 | Dell官方指引 | 高 |
| Dell FY2026 AI服务器backlog | $430亿 | Dell财报 | 高 |
| Micron FY2026全年收入consensus | ~$760亿 | Wall Street consensus | 高 |
| Micron HBM TAM 2028目标 | $1000亿 | Micron管理层指引 | 高 |
| Arista 2025全年营收 | $90亿（+29% YoY） | 公司报告 | 高 |
| Vistra 2026 revenue forecast | $233亿 | 分析师consensus | 中 |

---

## 2. 供应链节点图（供给端优先，F2）

```
[超大规模商/AI模型公司]
         ↓ capex
[AI服务器OEM] DELL / HPE / Supermicro
         ↓
    ┌────────────────────────────────────┐
    │           核心硬件节点              │
    ├──────────────┬─────────────────────┤
    │  GPU/ASIC   │  Memory (HBM)       │
    │  NVDA/AVGO/ │  MU/SK Hynix/       │
    │  MRVL/AMZN/ │  Samsung            │
    │  GOOG/MSFT  │                     │
    ├──────────────┼─────────────────────┤
    │  Networking │  Power              │
    │  ANET/MRVL  │  VST/CEG/AES        │
    │  NVDA InfB  │  (核能/天然气)       │
    └──────────────┴─────────────────────┘
         ↓
[半导体制造：台积电（最紧节点）]
```

**最紧节点判断**（F2供给端优先）：
- **2026-2027最紧**：台积电CoWoS先进封装产能（HBM叠加GPU产能）
- **2028+次紧**：HBM4堆叠层数物理限制、高速Ethernet 1.6T光模块产能
- **相对宽松**：AI服务器OEM（门槛低，DELL/HPE均可组装）

---

## 3. 终局情景树（F17框架）

### 情景A：AI Capex超级周期持续至2030（概率60%）

**定义**：DC capex年增25-30%+，AI模型迭代维持需求；2030年超大规模商+主权AI capex合计$1.5-1.7万亿（Dell'Oro基准预测）。

**节点市场规模（2030，Claude分析意见，中置信度）**：

| 节点 | 2024实际 | 2030情景A预测 | CAGR | 依据 |
|------|---------|--------------|------|------|
| GPU/ASIC总量 | ~$1400亿 | $4400-6000亿 | 20-25% | Mordor/Bloomberg Intelligence |
| 其中NVIDIA GPU | ~$1000亿 | $2150亿+ | ~14% | Bloomberg Intelligence GPU份额 |
| 其中定制ASIC | ~$400亿 | $1000-1300亿 | 18-21% | Counterpoint; AVGO CEO指引 |
| HBM | $170亿 | ~$980亿 | ~33% | Micron TAM指引+Mordor |
| AI networking | $200亿 | $1000亿+ | 30%+ | Arista TAM声明 |
| DC半导体总TAM | $2090亿 | ~$5000亿 | ~16% | Yole Group |

**情景A下各标的天花板**：

#### NVIDIA (NVDA)
- **2030 Revenue路径**：FY2027 $3668亿 → 以20%复合增长 → FY2031 ~$7500-9000亿
  - 注：FY为1月结束，FY2031=CY2030
  - 下行风险：ASIC蚕食份额（AVGO/GOOG/AMZN），增速放缓至15%则 ~$6000亿
- **合理倍数**：软件护城河（CUDA生态）支撑25-30x P/E；增速放缓后可能压缩至20x
- **情景A市值天花板**：Revenue ~$7500亿 × net margin ~55% × 25x P/E = **~$10万亿**
  - 当前市值：~$3.3万亿（2026-05）
  - 情景A上涨空间：**3x**（5年）
- **失效条件**：ASIC份额超40%（Counterpoint预测2028超越GPU出货量），增速<15% → 倍数压缩到18x，市值天花板降至$6-7万亿

#### Broadcom (AVGO)
- **核心驱动**：定制ASIC（Google TPU, Meta MTIA, Apple Neural Engine）+ Ethernet网络
- **2027 AI revenue guidance**：>$1000亿（CEO Hock Tan直接指引，高置信度）
- **2030 Revenue路径**：AI $1000亿(2027) → 年增30% → 2030 AI $2200亿；总revenue含VMware ~$3000亿
- **合理倍数**：独特的双引擎（ASIC+软件/VMware），26-30x P/E合理
- **情景A市值天花板**：Net income ~$800亿 × 28x = **~$2.2万亿**
  - 当前市值：~$1.1万亿（2026-05）
  - 情景A上涨空间：**2x**（5年）
- **关键风险**：ASIC客户自建（Apple已减少外包），VMware整合不及预期

#### Micron Technology (MU)
- **HBM天花板**：TAM $980亿(2030) × MU市场份额目标~25% = MU HBM Revenue ~$250亿
- **FY2026 consensus**：~$760亿总revenue；HBM业务Q3指引margin 81%
- **2030 Revenue路径**：HBM ~$250亿 + 传统DRAM/NAND ~$500亿 = 总计 ~$750亿（持平，因HBM利润率更高但NAND可能商品化）
  - 注：记忆体本质周期性，2030预测置信度低
- **合理倍数**：周期高点5-8x P/S，周期低点1-2x；HBM改善结构但不消除周期
- **情景A市值天花板**：Revenue ~$800亿 × 5x P/S（周期高点）= **~$4000亿**
  - 当前市值：~$1300亿（2026-05）
  - 情景A上涨空间：**3x**（但周期性风险高，时机依赖）
- **F9 Tier判断**：T2黄灯（HBM结构改善 vs 传统DRAM周期风险，bear case 15-25%）

#### Marvell Technology (MRVL)
- **定位**：AWS Trainium芯片代工 + 微软Maia + 1.6T光学DSP（Ethernet网络）
- **Data center revenue mix**：已达74%
- **2030 Revenue路径**：AI revenue CAGR 40%+(公司指引FY2027) → 若持续至2030，AI revenue从~$60亿(FY2026) → ~$250亿
- **合理倍数**：高增速成长股，35-45x P/E合理（benchmark Broadcom并购前）
- **情景A市值天花板**：Net income ~$80亿 × 40x = **~$3200亿**
  - 当前市值：~$800亿（2026-05）
  - 情景A上涨空间：**4x**（5年，最高弹性）
- **关键风险**：大客户集中度（AWS+MSFT超60%），任何一单丢失冲击大

#### Dell Technologies (DELL)
- **定位**：AI服务器OEM，但本质是组装商，利润率薄
- **FY2027 AI服务器目标**：~$500亿；backlog $430亿（超高可见度）
- **FY2026-2031 CAGR指引**：ISG（基础设施）高十几%
- **2030 Revenue路径**：ISG ~$1200亿 + PC/CSG ~$500亿 = 总计~$1700亿
- **核心问题**：AI服务器毛利率5-7%，远低于芯片/软件；量大但留不住利润
- **合理倍数**：0.5-0.7x P/S（低margin硬件OEM历史区间）
- **情景A市值天花板**：Revenue $1700亿 × 0.6x = **~$1000亿**
  - 当前市值：~$700亿（2026-05）
  - 情景A上涨空间：**1.4x**（最低弹性）
- **结论**：供应链中利润最薄的环节，不是瓶颈节点

#### Vistra (VST)
- **定位**：AI数据中心电力需求受益者，核能+天然气组合
- **已签协议**：AWS（Comanche Peak核电站），Meta（3座核电站20年协议）
- **2026 EPS forecast**：$9.40 | Revenue $233亿
- **2030 Revenue路径**：ERCOT负荷增长5-6%/年 → 电力需求复合增长 → Revenue ~$350亿
- **关键约束**：发电能力受限于许可证和建设周期，不是纯AI beta
- **合理倍数**：公用事业+成长溢价，15-18x P/E
- **情景A市值天花板**：Net income ~$50亿 × 17x = **~$850亿**
  - 当前市值：~$400亿（2026-05）
  - 情景A上涨空间：**2x**（5年）
- **失效风险**：PJM容量市场不确定性、天然气价格波动

---

### 情景B：2028年capex放缓但不崩（概率25%）

**定义**：AI模型边际收益递减信号出现，企业AI ROI受质疑，DC capex增速降至10-15%/年。总体规模2030约$8000-1万亿（低于情景A的$1.7万亿）。

**哪些节点受损最大**：

| 节点 | 受损程度 | 原因 |
|------|---------|------|
| NVIDIA GPU | 高（⚠️） | 最高杠杆，增速从30%→15%，P/E从28→18x，市值砍40-50% |
| Dell AI服务器 | 极高（⚠️⚠️） | 低毛利业务量敏感，backlog消化后无定价权 |
| HBM/Micron | 高（⚠️） | 历史证明：DRAM价格崩溃速度远超市场预期 |
| AVGO | 中（⚠） | ASIC合同相对黏性（3-5年），VMware业务对冲 |
| MRVL | 中（⚠） | 长周期定制芯片合同，但高集中度风险 |
| Arista/ANET | 低（✓） | 校园+企业网络提供基本盘，纯DC exposure约40% |
| VST/电力 | 极低（✓） | 核能20年长协，电力需求结构性（电动车、工业化无关AI） |

**情景B各标的下跌幅度（Claude分析意见，低置信度）**：
- NVDA：-35% to -45%（从当前价格，18个月horizon）
- MU：-40% to -55%（周期反转历史教训）
- AVGO：-20% to -30%
- MRVL：-30% to -40%（高估值最脆弱）
- DELL：-25% to -35%
- VST：-10% to -15%

---

### 情景C：AI泡沫破裂（概率15%）

**定义**：2026-2027年某次重大AI能力瓶颈或商业模式危机导致hyperscaler capex砍30-50%，类比2001年电信泡沫破裂。

**触发条件**：
1. GPT-N类模型出现明确的scaling law失效证据
2. 主要hyperscaler（META/MSFT/GOOG）季度capex指引大幅下调（>30%）
3. 企业AI订阅续约率系统性崩塌（类似SaaS 2022）

**各节点downside（以情景C为极端压力测试）**：

| 标的 | 情景C downside | F9 Tier |
|------|---------------|---------|
| NVDA | -60% to -70% | T4红灯（纯情景C） |
| MU | -65% to -75% | T4红灯（周期崩塌） |
| AVGO | -40% to -55% | T3橙灯（ASIC合同缓冲） |
| MRVL | -55% to -65% | T4红灯 |
| DELL | -45% to -60% | T3橙灯 |
| VST | -20% to -30% | T2黄灯（最防御） |

---

## 4. 当前价格隐含的终局诊断

**方法**：用当前市值反算当前股价"定价的是哪个情景"

| 标的 | 当前市值 | 情景A天花板 | 情景B公允值 | 当前隐含 |
|------|---------|-----------|-----------|---------|
| NVDA | ~$3.3万亿 | ~$10万亿 | ~$4-5万亿 | **介于A/B之间**，市场定价约50% A情景概率 |
| AVGO | ~$1.1万亿 | ~$2.2万亿 | ~$1.2-1.5万亿 | **接近B情景定价**，A情景有2x空间 |
| MU | ~$1300亿 | ~$4000亿 | ~$600-800亿 | **接近B情景，略高**，A情景3x但时机风险大 |
| MRVL | ~$800亿 | ~$3200亿 | ~$400-600亿 | **折价于B情景**，市场低估定制ASIC长期价值 |
| DELL | ~$700亿 | ~$1000亿 | ~$400-500亿 | **A情景仅1.4x**，低弹性不是瓶颈节点 |
| VST | ~$400亿 | ~$850亿 | ~$350亿 | **接近B情景**，核能长协提供地板 |

---

## 5. 节点竞争力排序（F13可得性护城河 + F9终局淘汰）

从"终局受益最大、当前定价最低"综合排序：

### 做多优先级（情景A，18个月horizon）

**第一梯队 — 瓶颈节点，当前定价有折价**：
1. **AVGO** — ASIC合同黏性强，CEO直接指引$1000亿，市场低估VMware+ASIC协同。F9 T1（情景A，<15%下行）
2. **MRVL** — 最高弹性（4x），AWS+MSFT定制ASIC独特卡位，当前定价低于B情景。F9 T2（集中度风险，15-25%下行）

**第二梯队 — 高弹性但需时机**：
3. **NVDA** — 最大赢家但已定价A情景50%概率，买在情景C恐慌时更佳。F9 T2（市场共识充分，下行15-20%）
4. **MU** — 时机依赖，HBM结构改善不消除DRAM周期性。F9 T2（历史周期volatility高）

**第三梯队 — 低弹性或非瓶颈节点**：
5. **VST** — 防御属性，A情景2x但上限低，适合减少组合波动
6. **DELL** — 供应链中利润最薄，1.4x天花板，不是有效配置

### 做空/规避信号（情景C观察池）：
- NVDA >100x P/E 时（泡沫估值信号）
- MU连续两季度revenue guidance下调时（周期反转早期信号）
- 任何hyperscaler capex guidance单季下调>20%时（C情景触发器）

---

## 6. 翻转条件时间线

| 时间节点 | 观察指标 | 情景切换信号 |
|---------|---------|-----------|
| 2026 Q3-Q4 | META/MSFT/GOOG Q3 earnings capex guidance | 下调>10% → B情景概率升至40% |
| 2027 Q1 | NVDA FY2027全年revenue vs $3668亿 consensus | Miss>10% → 增速预期修正 |
| 2027 H1 | AVGO是否宣布第4大ASIC客户（当前3个） | 新客户 → A情景概率升至70% |
| 2027-2028 | HBM4供应是否出现oversupply（SK Hynix/Samsung同时量产） | 供应过剩 → MU周期反转 |
| 2028 | ASIC出货量是否超越GPU出货量（Counterpoint预测） | 超越 → AVGO/MRVL加仓；NVDA减仓 |
| 2029-2030 | AI inference TAM是否超越training TAM | 超越 → 边缘AI/低功耗芯片重新定价 |

---

## 7. 关键失效条件（F5 v2，情景A失效部分）

**类比"AI = 互联网"的失效部分（影响估值上限）**：

1. **互联网泡沫路径**：1999-2000 Cisco/Lucent被定价为"永续高增长" → revenue从$20B砍至$5B → P/S从15x崩至1x。当前NVDA在$3.3万亿时，25x P/S已隐含完美执行。**失效条件**：任何NVDA大客户自建ASIC宣布（MSFT/Meta进一步扩大自研）

2. **Jevons悖论失效**：历史每次算力效率提升，需求确实扩大（GPT-4→Claude→DeepSeek）。**失效条件**：模型能力改善但使用场景不再扩大（B2B AI ROI低于预期，企业续约率<70%）

3. **制度约束（F19）**：美国对华半导体出口管制持续升级 → 中国市场（约占NVDA营收15-20%）强制切割。**当前价格是否含有此折价**：否，市场默认出口管制维持现状

---

## 8. 结论（一句话）

**5年终局：GPU/ASIC和HBM是真实瓶颈，OEM服务器是通道，网络和电力是中段受益；当前配置顺序AVBO>MRVL>NVDA>MU>VST>DELL，等待capex guidance miss作为加仓GPU/减仓OEM的信号。**

**（Claude分析意见——基于公开市场数据和分析师共识，未经独立验证；MU的2027-2030预测置信度低；所有市值目标为情景A基准，非买卖建议）**

---

## 来源索引

| # | 来源 | 类型 | 日期 |
|---|------|------|------|
| 1 | Dell'Oro Group: "AI Boom Drives Data Center Capex to $1.7 Trillion by 2030" | 行业报告 | 2026-01 |
| 2 | NVIDIA官方财报 FY2026 + Q1/Q2 FY2027 guidance | 一手（SEC filing等） | 2026-05-20 |
| 3 | Broadcom CEO Hock Tan "$100B AI revenue by 2027" | 一手（earnings call） | 2026 |
| 4 | Micron Management: HBM TAM $100B by 2028 | 一手（管理层指引） | 2026 |
| 5 | SK Hynix: AI memory market +30% annually through 2030 | 一手（公司声明） | 2026 |
| 6 | Mordor Intelligence: HBM 2024-2030 CAGR 33% | 行业报告 | 2025-2026 |
| 7 | Bloomberg Intelligence: AI accelerator >$600B by 2033 | 分析师报告 | 2025 |
| 8 | Dell Technologies FY2026 财报 + FY2027 指引 | 一手（公司财报） | 2026-02 |
| 9 | Counterpoint Research: ASIC出货量2028超越GPU | 行业报告 | 2025-2026 |
| 10 | Yole Group: DC semiconductor TAM 2024=$209B → 2030=$500B | 行业报告 | 2025 |
| 11 | Vistra FY2026 analyst consensus $9.40 EPS | 分析师consensus | 2026 |
| 12 | Morgan Stanley: 5M TPUs shipped 2027, 7M 2028 | 分析师报告 | 2026 |

---

*写入时间: 2026-05-27 | 下次更新触发条件: 任何hyperscaler Q2 2026 capex guidance变化 >10%*
