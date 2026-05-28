# Hyperscaler AI Capex Flow Map 2026
**Date**: 2026-05-27 | **Author**: Claude (web-research synthesis) | **Status**: Claude分析意见

---

## 一、量级确认：四大合计 $335B+ in 2026 (Q1 guidance)

| 公司 | 2026年全年Capex Guidance | Q1 2026实际 | YoY |
|------|------------------------|------------|-----|
| **AMZN** | ~$176B+ (annualized) | $44.2B/Q | AWS +28% |
| **GOOGL** | **$180-190B** (raised) | $35.67B | 2x+ YoY |
| **MSFT** | ~$120B+ | $30.88B | +84% YoY |
| **META** | **$125-145B** (raised) | ~$32B | 大幅提升 |
| **合计** | **~$620-650B** (Big 4) | ~$143B/Q | ~+64% |

> **数据来源**: Q1 2026 earnings calls. CreditSights, Yahoo Finance (2026-04/05). 全球9大CSP合计$830B (TrendForce 2026-05).
> **注**: 原题"$325B+"为估计低值；实际Q1 2026 guidance升级后Big 4合计已达$620-650B范围。

---

## 二、Capex拆分：每一美元流向哪里

### 核心框架：IT设备 vs 物理基础设施

| 大类 | 占总Capex | 金额 ($620B基础) | 核心驱动 |
|------|----------|----------------|---------|
| **IT设备（含GPU）** | ~63% | ~$390B | AI加速器、服务器、HBM内存 |
| **物理基础设施** | ~37% | ~$230B | 电力、冷却、建筑、土地 |

> 来源: IoT Analytics, Avanza Energy (Substack), Dell'Oro Group

---

### 详细Category拆分表

| Category | % of Total | $ Amount | YoY Growth | Top Beneficiary | Bottleneck? |
|----------|-----------|----------|------------|-----------------|-------------|
| **GPU/Accelerators** | ~35-40% | ~$220-250B | +92% (NVDA DC) | NVDA, AVGO ASIC, MRVL ASIC | **是——CoWoS封装产能** (TSMC sold out through 2026) |
| **HBM/Memory** | ~4-5% | ~$25-30B | +20% ASP + 量增 | MU, SK Hynix, Samsung | **是——HBM3E 100%卖光到2026年底，HBM4提价20%** |
| **Networking** | ~8-12% | ~$50-75B | +199% (NVDA InfiniBand) | AVGO, MRVL, NVDA (InfiniBand) | **中等——Ethernet vs InfiniBand竞争激烈但需求>>供给** |
| **Servers/Racks** | ~8-10% | ~$50-65B | +30-40% | DELL, SMCI | 供给相对充裕，主要依赖GPU到货时间 |
| **Power/Electrical** | ~10-12% | ~$65-75B | 快速扩张 | GEV (GE Vernova), VST (Vistra), ETN, HUBB | **是——变压器交期5年(2026)，配电盘缺货** |
| **Cooling** | ~4-5% | ~$25-30B | +20-33% CAGR | VRT (Vertiv), 液冷正成为标配 | **中等——液冷渗透率从22%快速爬升，供给追赶中** |
| **Construction/Civil** | ~8-10% | ~$50-65B | 施工成本+50% YoY | EME (EMCOR), PRIM (Primoris), PWR | 劳工+材料紧张，7GW项目延期 |
| **Software/Ops** | ~3-5% | ~$20-30B | 稳定增长 | MSFT Azure, CRM, SNOW | 无明显瓶颈 |

> **数据来源**:
> - GPU份额: alcapitaladvisory.com AI Capex CFA Analysis (2026-05)；$250B NVDA GPU estimate
> - HBM: TrendForce (2025-12)，HBM3E $300/stack (2026-04)
> - Networking +199%: NVDA Q1 FY2027 earnings (2026-05-20)
> - Power分项: Avanza Energy Substack (物理基础设施内电力占40-45%)
> - 冷却增速: 市场CAGR 20-33% (多来源)
> - 建筑成本+50% YoY: data center $/sqft数据
> - EMCOR backlog: Q1 2026 earnings (数据中心backlog $1.7B+)

---

## 三、三个关键问题

### Q1. 哪个Category增速最快？（下一个爆发点）

**结论：Networking，特别是AI以太网**

| Category | 2026增速证据 |
|---------|------------|
| **Networking (AI Fabrics)** | **+199% YoY** (NVDA InfiniBand)；AVGO AI ASIC含networking +106% YoY |
| GPU/Accelerators | +92% YoY (NVDA DC revenue Q1 FY2027) |
| HBM Memory | +20% ASP涨价 + 供给持续紧张 |
| Power/Cooling | 结构性增长，增速相对稳定但持续 |

**为什么Networking是下一个爆发点**：
- GPU cluster规模从1K → 10K → 100K，互联需求指数级增长
- InfiniBand vs Ethernet战争激烈：AVGO押注Ultra Ethernet，NVDA护卫InfiniBand
- AVGO Q2 FY2026 AI revenue $33.6B annualized，networking是核心驱动之一
- META、Google、Amazon转向自研ASIC→需要定制networking fabric→AVGO/MRVL直接受益

---

### Q2. 哪个Category供给最紧？（定价权最强）

**结论：双重瓶颈——电力基础设施（物理约束）+ HBM内存（寡头垄断）**

#### 电力基础设施（最硬的物理约束）
- 美国：50%已宣布数据中心项目延期或取消（Bloomberg 2026）
- 7 GW计划容量受阻，原因是变压器、配电盘短缺，而非GPU
- **变压器交期：5年**（2026年订货，2031年交付）
- 12 GW在建中，仅1/3是已激活项目
- 电力短缺：美国当前缺口11 GW，2028年预计40+ GW（Goldman Sachs）
- **定价权**：超强。GEV (GE Vernova)、ETN (Eaton)、HUBB (Hubbell)

#### HBM内存（寡头垄断+全部卖完）
- SK Hynix 50-55%市场份额，Samsung 35-40%，Micron 8-12%
- **2026年全年产能100%已预售**（Micron, SK Hynix均确认）
- 2026 HBM3E涨价20%；HBM4另追加20%溢价
- META公开表示：HBM sold out through 2026，价格飙升
- **定价权**：极强。但只有3家供应商，无法简单投资

---

### Q3. 哪个Category估值最低？（Mispricing）

**结论：建筑/电气EPC（EME/PRIM）和电力设备（GEV/ETN），被市场当作传统工业股定价**

| 标的 | 估值 | 市场定价逻辑 | 实际驱动逻辑 | Mispricing程度 |
|-----|------|------------|------------|--------------|
| **EME (EMCOR)** | **P/E 30.7x** | 传统建筑承包商 | AI数据中心电气/机械EPC，backlog $11.5B，数据中心部分$1.7B+ | **强** — 行业中位48x，同类75.3x |
| **PRIM (Primoris)** | ~15-18x | 工程服务 | Utilities backlog $6.9B (含大量数据中心电力基础设施) | **中强** |
| **GEV (GE Vernova)** | 战略性 | 电力设备 | 变压器卖断货，AI数据中心+电网双驱动 | **中** — 市场已部分定价 |
| **VRT (Vertiv)** | **P/E 53x** | 已被认可为AI纯播 | 液冷+电力管理，backlog $15B，30%有机增长 | 溢价充分，alpha已被提取 |
| **AVGO (Broadcom)** | >$2T市值 | AI网络+ASIC龙头 | 自定义AI芯片+以太网交换，+106% YoY | 已充分定价 |
| **MU (Micron)** | 周期股定价 | DRAM周期股 | HBM3E结构性短缺，FY2026 revenue ~$38B base | **中** — 市场仍用周期框架看待 |

---

## 四、三问交集：主线投资方向

```
增速最快 (Networking) ∩ 供给最紧 (Power/HBM) ∩ 估值最低 (Construction/Power Equip)
```

**交集落在：AI数据中心电力/电气基础设施**

| 维度 | 证据 |
|-----|------|
| **增速** | 每新建1MW AI算力需$20M+ 全包成本，电力是最大单项。YoY增速快于市场理解 |
| **供给紧** | 变压器5年交期 = 物理硬约束，无法靠资金解决 |
| **估值低** | EME P/E 30.7x vs 行业48x，市场未将AI特供定价进去 |
| **催化剂可见** | Q2 2026 earnings将继续确认数据中心backlog增长 |

### 主线标的排序（Claude分析意见，非用户持仓建议）

1. **EME (EMCOR)** — 最清晰的mispricing。建筑EPC龙头，但P/E比行业打折30%+。AI数据中心backlog持续扩张中。
2. **MU (Micron)** — HBM3E结构性短缺但仍被周期框架定价。FY2026 revenue $38B base case。风险：Samsung竞争。
3. **GEV (GE Vernova)** — 变压器+grid设备唯一硬约束受益者。已部分定价但约束持续3-5年。

### 主动回避（定价充分或风险高）
- **VRT**: P/E 53x，已是公认AI纯播，alpha基本被提取
- **NVDA**: 每$1 hyperscaler capex中57¢流向NVDA，但$2T+市值已高度定价
- **AVGO**: $2T市值，+106%增速已在价格里

---

## 五、数据质量说明

| 数据点 | 置信度 | 来源 |
|-------|-------|------|
| GOOGL 2026 capex $180-190B | **高** | 公司官方Q1 2026 earnings guidance |
| META 2026 capex $125-145B | **高** | 公司官方Q1 2026 earnings guidance |
| NVDA DC revenue +92% YoY | **高** | NVDA Q1 FY2027 earnings (2026-05-20) |
| NVDA Networking +199% YoY | **高** | NVDA Q1 FY2027 earnings |
| AVGO AI revenue $8.4B Q1, +106% YoY | **高** | AVGO Q1 FY2026 earnings |
| IT设备占总capex ~63% | **中** | IoT Analytics, multiple analyst sources |
| 电力系统占物理基础设施40-45% | **中** | Avanza Energy, 工程测算 |
| 变压器交期5年 | **中** | Tech-insider, Sandstone Group (引用Bloomberg) |
| HBM3E $300/stack | **中** | Silicon Analysts (2026-04) |
| 50%数据中心项目延期 | **中** | Bloomberg (引用自多个二手来源) |
| EME P/E 30.7x | **中** | Sahm Capital analysis (2026-05-09) |
| GPU占总capex ~35-40% | **中低** | 多来源推算，非公司直接披露 |
| Category % 拆分 | **估算** | 综合多个分析师框架推断，非一手数据 |

> **注意**: Category百分比拆分为分析师综合估算，四大hyperscaler均未公开披露明细capex breakdown。所有%数字应视为数量级参考，非精确数据。

---

## 六、信息来源

- NVDA Q1 FY2027 Earnings (2026-05-20): $81.6B revenue, DC $75.2B
- GOOGL Q1 2026 Earnings: capex $35.67B, 2026 guidance $180-190B
- META Q1 2026 Earnings: full-year guidance raised to $125-145B
- MSFT Q3 FY2026 Earnings: capex $30.88B, +84% YoY
- AVGO Q1 FY2026: AI revenue $8.4B, +106% YoY
- VRT Q1 2026: revenue $2.65B, backlog $15B+
- EME Q1 2026: backlog $11.5B, DC exposure $1.7B+
- TrendForce (2025-12): HBM3E 20% price hike plan
- Goldman Sachs: power grid as "binding constraint"
- Dell'Oro Group: data center capex CAGR 21% through 2029
- alcapitaladvisory.com: AI Capex CFA Analysis $725B flow model
- avanzaenergy.substack.com: $640B breakdown physical vs IT split
