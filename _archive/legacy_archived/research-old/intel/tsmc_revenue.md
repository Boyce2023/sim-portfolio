# TSMC月度营收追踪 — AI需求实时体温计

**数据截至**: 2026年5月（4月报告，5月数据待公布）
**数据来源**: TSMC官方IR页面 + Q1 2026 Earnings Call官方transcript（Yahoo Finance/Quartr）+ SEC Form 6-K

---

## 一、月度营收数据表

（单位：NT$百亿 = NT$B）

| 月份 | Revenue (NT$B) | YoY% | MoM% | 备注 |
|------|---------------|------|------|------|
| Jan 2026 | 401.26 | +36.8% | — | 无前月基准（YTD起点） |
| Feb 2026 | 317.66 | +22.2% | -20.8% | 2月季节性低谷（春节） |
| Mar 2026 | 415.19 | +45.2% | +30.7% | TSMC史上最高单月营收 |
| Apr 2026 | 410.73 | +17.5% | -1.1% | 史上第二高；MoM小幅回落正常 |
| May 2026 | — | — | — | 预计6月10日公布 |

**Jan–Apr 2026 YTD合计**: NT$1,544.83B，YoY +29.9%

**注**: 数字来自TSMC官网investor.tsmc.com/english/monthly-revenue/2026，未经审计。YoY%已直接来自官方报告；MoM%为本表自行计算，以NT$M原始数据（401,255 / 317,657 / 415,191 / 410,726）为基。

---

## 二、技术节点占营收比例（Q1 2026）

来源：Q1 2026 Earnings Call，CFO Wendell Huang原文（April 16, 2026）

> "3 nm process technology contributed 25% of wafer revenue in the first quarter, while 5 nm and 7 nm accounted for 36% and 13% respectively. Advanced technologies, defined as 7 nm and below, accounted for 74% of wafer revenue."

| 技术节点 | Q1 2026营收占比 | 节点状态 |
|---------|--------------|---------|
| 3nm (N3) | **25%** | 高-volume ramp；毛利率预计H2 2026越过公司均值 |
| 5nm (N5) | **36%** | 最大单节点贡献，AI GPU + 消费 |
| 7nm (N7) | **13%** | 成熟先进节点，辅助支撑 |
| 7nm以下合计 (先进制程) | **74%** | 较Q4 2025继续提升 |
| 2nm (N2) | 小量（已进入HVM，Q4 2025启动） | H2 2026 ramp，将带来2-3%毛利摊薄 |

**趋势解读**: 3nm+5nm合计61%，主力战场清晰。3nm毛利即将达到公司均值（mid-60s%），意味着mix shift将开始正向拉动而非摊薄。

---

## 三、AI相关Wafer Loading

来源：Q1 2026 Earnings Call，CFO原文

> "HPC increased 20% quarter-over-quarter to account for 61% of our first quarter revenue."

| 平台 | Q1 2026占比 | QoQ |
|-----|------------|-----|
| HPC（含AI GPU/ASIC/HBM） | **61%** | +20% QoQ |
| Smartphone | 26% | -11% QoQ |
| IoT | 6% | +12% QoQ |
| Automotive | 4% | -7% QoQ |
| DCE | 1% | +28% QoQ |

**历史趋势**（HPC占比）：
- Q1 2025: 48%
- Q3 2025: 51%
- Q4 2025: 53%
- Q1 2026: **61%** ← 跳升8个百分点，创历史新高

**含义**: AI对TSMC的营收拉动已不是边际贡献，而是主引擎。HPC单季度+20% QoQ在TSMC体量下属罕见。

---

## 四、管理层2026 Guidance关键原话

### CEO C.C. Wei（Q1 2026 Earnings Call，April 16, 2026）

**AI需求展望**：
> "AI related demand continued to be extremely robust. The shift from generative AI and the query mode to agentic AI and the command and the action mode is leading to another step up in the amount of tokens being consumed. This is driving the need for more and more computation, which supports the robust demand for leading-edge silicon."

**2026全年guidance上调**：
> "Supported by our robust technology differentiation and broader customer base, we maintain strong confidence for our full year 2026 revenue to now grow by above 30% in U.S. dollar terms."

**3nm扩产原因**：
> "Based on our assessment, to meet the strong demand in AI application, we are stepping up our CapEx investment to increase our N3 capacity... which are used by smartphone, HPC AI, including HBM-based ASICs, automotive and IoT customers."

**先进封装产能状况**：
> "Our advanced packaging capacity is very tight also. We have to work with our OSAT partners. We hope that we can increase capacity to support our customer... it just have been very tight. That's what our situation today." （Laura Chen问答，April 16, 2026）

### CFO Wendell Huang（Q1 2026 Earnings Call）

**Q2 2026 Guidance**：
> "We expect our second quarter revenue to be between $39.0 billion–$40.2 billion, which represents a 10% sequential increase or a 32% year-over-year increase at the midpoint."

**CapEx**：
> "We now expect our 2026 capital budget to be towards the high end of our range of between $52 billion–$56 billion."

**毛利率展望**：
> Q2 guidance: 65.5%–67.5%毛利率；N3毛利预计H2 2026越过公司均值

---

## 五、CoWoS产能扩张

### 现状（Q1 2026 Earnings Call）

- **产能状态**: "Advanced packaging capacity is very tight" — C.C. Wei原话
- **已知信息**: CoWoS sold out through 2027（来源：multiple analyst reports，非earnings call原文）

### 扩张路线图（C.C. Wei，Q1 2026 Earnings Call）

**CoWoS-L（大reticle size）**: 当前主力方案，已量产，继续扩容
> "We have a very large reticle size CoWoS. Of course, we are also working on CoPoS. Together we try to make sure that we give enough capacity to support our customer with a reasonable cost."

**CoPoS（下一代面板级封装）**:
> "We build a CoPoS pilot line right now and expect production a couple years later."
→ 量产预计2028年前后

**CapEx配套**: $52-56B高端，含先进封装

### 配套前端制程扩产时间表（N3用于AI）

| 地点 | 节点 | 状态 | 量产时间 |
|-----|------|------|---------|
| 台南（新增N3 fab） | 3nm | 建设中 | 2027上半年 |
| 亚利桑那Fab 2 | 3nm | 建设完成 | 2027下半年 |
| 日本Fab 2 | 3nm（新公告） | 规划中 | 2028 |
| N2（新竹+高雄） | 2nm | HVM已启动 | 2025 Q4进入，2026 ramp |

---

## 六、信号解读

**当前读数**: TSMC营收加速 ✅

| 信号 | 读数 | 含义 |
|-----|------|------|
| YTD YoY | +29.9% | 加速，远超年初预期 |
| 3月 YoY | +45.2% | 历史最高单月YoY增速之一 |
| HPC占比 | 61%（Q1），QoQ+20% | AI需求无放缓迹象 |
| 全年guidance | "above 30%"（从"mid-20s"上调） | 管理层信心高 |
| 先进封装产能 | "very tight" | 供给瓶颈仍在，利于定价 |
| 4月 MoM | -1.1% | 正常季节性波动，非趋势逆转 |

**Red flag条件**: MoM连续两个月负增长 + YoY增速跌破20% + HPC占比回落 → 当前均不满足

**下一个数据点**: 5月营收预计6月10日公布；Q2 2026财报预计7月中旬

---

*数据来源索引*:
- TSMC官方月度营收: https://investor.tsmc.com/english/monthly-revenue/2026
- April 2026 Revenue PR: https://pr.tsmc.com/english/news/3305
- Q1 2026 Earnings Transcript: https://finance.yahoo.com/quote/TSM/earnings/TSM-Q1-2026-earnings_call-541404.html
- SEC Form 6-K (April revenue): https://www.sec.gov/Archives/edgar/data/0001046179/000104617926000213/tsm-revenue20260508.htm
