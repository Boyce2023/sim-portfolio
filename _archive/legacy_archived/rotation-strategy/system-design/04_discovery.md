# Track B Discovery System — TB-DS v1.0

> 设计日期：2026-05-28 | 基于 ROTATION_STRATEGY_V1.2 + strategy.md §2.4b + _DISCOVERY_SYSTEM.md v2.0
> Claude分析意见，非用户投资建议。
> 适用市场：A股牛市/吸气期。呼气期硬关闭，仅保留TB-S4（龙头状态追踪）以监控持仓安全。

---

## 一、设计原理：Track B的发现问题与Track A不同

Track A（基本面）的茧房问题是：只看AI/科技，错过化工/周期/消费。解法：Anti-Sector扫描 + 多维信号驱动。

Track B（轮动）的茧房问题不同，有三层：

**层1 - 主线茧房**：只盯当前主线（如光模块），不看相邻方向（PCB/CCL/封装）正在启动传导。错过时机不是因为不知道AI链，而是不知道AI链内哪一环节在轮动。

**层2 - 深度茧房**：只看TMT/科技，消费/周期/金融的轮动机会完全不在视野里。926行情金融股爆发时措手不及。

**层3 - 类型茧房**：只会识别Type 2（产业催化），不识别Type 4（政策驱动）、Type 5（游资），或反过来只会游资题材不会产业催化。

**解法框架**：TB-DS用7个Scanner覆盖轮动的三个维度：
- **情绪维度**（TB-S1, TB-S2）：市场整体情绪健康度 + 涨停生态，判断"现在是什么环境"
- **主线维度**（TB-S3, TB-S6）：当前产业链传导位置 + 龙头状态，判断"当前主线在哪一环"
- **发现维度**（TB-S4, TB-S5, TB-S7）：资金流向 + 催化剂日历 + Anti-Cocoon，发现"下一个在哪里"

---

## 二、F20主控开关（继承Track A规则）

TB-DS在F20呼气期**硬关闭**（继承ROTATION_STRATEGY_V1.2 §1.4的策略硬开关逻辑）。

| F20状态 | Scanner功率 | 操作 |
|--------|------------|------|
| 强吸气 | 100%全功率 | 所有7个Scanner全跑 |
| 吸气 | 100%全功率 | 所有7个Scanner全跑 |
| 中性 | 60% | TB-S1/S2/S3/S4运行；TB-S5/S6/S7降频 |
| 呼气 | 0% | **仅TB-S3（龙头状态）保留**，用于监控持仓安全 |
| 深度呼气 | 0% | TB-S3降为每日确认持仓止损位，其余全停 |

**紧急关闭触发（直接跳过F20判断）**：
- 当日跌停家数 > 50家 → 立即停止所有新入场
- 涨停家数48小时降幅 > 40% → TB-DS进入仅监控模式

---

## 三、7个Signal Scanner

### TB-S1: 涨停生态监控（Limit-Up Ecosystem）

**扫描维度**：全市场情绪健康度。Track B入场的前提条件之一。

**输入数据**：
- 全市场当日涨停家数（主板10%/创业板科创板20%）
- 炸板率（=（涨停后开板家数）/（曾涨停家数））
- 连板高度分布（最高几连板/3板以上家数）
- 涨停家数按板块分布（TMT / 消费医药 / 周期材料 / 金融地产）

**判定规则**：

```
情绪分级:
  HIGH（主升期）：涨停≥60家 + 炸板率<30% + 连板3+板家数≥5
  MID（启动期/分歧期）：涨停30-60家 OR 炸板率30-50%
  LOW（退潮期/无人区）：涨停<30家 OR 炸板率>50%
  CRASH（崩溃期）：跌停>50家 OR 炸板率>60%（V1.2铁律，当日清仓审查）

板块分布解读:
  TMT涨停>总量60% → 科技行情主导，关注拥挤度（>48%减仓区间）
  消费/金融涨停突然出现10%+ → 风格切换预警（触发TB-S7 Anti-Cocoon检查）
  多板块均匀分布 → 普涨行情，Track B弹性降低
```

**输出信号**：
```json
{
  "scanner": "TB-S1",
  "timestamp": "2026-05-28",
  "limit_up_count": 85,
  "fried_plate_rate": 0.22,
  "top_plate_count": 8,
  "sector_distribution": {"tmt": 0.55, "consumer": 0.12, "cyclical": 0.18, "financial": 0.15},
  "emotion_level": "HIGH",
  "signal": "MONITOR",
  "note": "主升期信号，TMT 55%仍在安全区（<48%拥挤阈值）"
}
```

**执行频率**：每日收盘后（W2）。盘前30分钟做昨日数据回顾。

---

### TB-S2: 板块成交占比变化（Sector Flow Shift）

**扫描维度**：资金在大板块间的流动方向，识别风格切换早期信号。

**输入数据**：
- 各大板块当日成交额占全市场比例
  - TMT（计算机/通信/电子/传媒）
  - 消费（食品饮料/医药/家电/汽车）
  - 周期材料（煤炭/钢铁/化工/有色/机械）
  - 金融地产（银行/非银/房地产/建筑）
  - 新能源（电力/光伏/储能/充电）
- 与过去5日均值比较（变化量）
- 与过去20日均值比较（趋势方向）

**判定规则**：

```
单板块成交占比变化阈值（5日均值 vs 今日）:
  +5pp以上：资金净流入（INVESTIGATE该板块）
  -5pp以上：资金净流出（减持信号）
  
趋势判断（20日基准）:
  连续3日上升 + 今日占比>20日均值+8pp → 主线确立信号
  连续3日下降 + 今日占比<20日均值-5pp → 风格切换启动
  
TMT特殊规则（基于ROTATION_STRATEGY §4.2 T2豁免）:
  TMT占比 > 40% → 正常减仓关注区
  TMT占比 > 48% → 非T2标的减仓50%；T2（有BOM/季报支撑）减至半仓
  TMT占比 > 2.4×历史标准差 → 无条件减仓（T2无豁免）
  
跨板块共振（发现信号）:
  原主线成交占比-3pp + 新板块+3pp + 新板块有涨停→ 资金搬家日信号（触发TB-S3验证）
```

**输出信号**：
```json
{
  "scanner": "TB-S2",
  "timestamp": "2026-05-28",
  "sector_flows": {
    "tmt": {"today_pct": 0.42, "5d_avg": 0.38, "20d_avg": 0.35, "delta_5d": "+4pp"},
    "cyclical": {"today_pct": 0.18, "5d_avg": 0.14, "20d_avg": 0.13, "delta_5d": "+4pp"}
  },
  "rotation_signal": "cyclical上升趋势，+4pp",
  "signal": "INVESTIGATE",
  "priority_sector": "周期材料",
  "note": "TMT仍主导但周期材料资金流入加速，关注是否风格切换早期信号"
}
```

**执行频率**：每日收盘后（W2）。每周一汇总周度趋势。

---

### TB-S3: 龙头状态追踪（Lead Dragon Monitor）

**扫描维度**：当前3条主线龙头的实时状态，是Track B持仓的安全阀。

**设计原则**：Track B的止损铁律是"板块龙头跌>5%当日全出"（strategy.md §2.4b + ROTATION_STRATEGY §4.4）。TB-S3是这条铁律的信息前端。

**追踪对象**：同时追踪最多3条主线，每条主线只追"主龙头"（市值最大+成交额最大）。

**输入数据**：
- 每条主线主龙头当日涨跌幅
- 连板高度（当前是第几板）
- 当日成交额 vs 前5日均量（量价状态）
- 封板时间（<14:00为强势）
- 龙虎榜净买卖方向（T+1延迟，辅助参考）

**判定规则**：

```
龙头状态分级:
  STRONG（强势）：涨停且成交量<2×均量（缩量封板）+ 封板<14:00
  HEALTHY（健康）：涨幅≥3% + 成交量正常 + 未断板
  WARNING（预警）：涨停后开板（炸板） OR 高开低走至收盘涨幅<1%
  DANGER（危险）：当日跌幅 -3% 至 -5%（Track B降仓50%准备）
  EXIT（出场）：当日跌幅 > -5% → ★触发Track B铁律，当日全出
  
量价背离预警（ROTATION_STRATEGY §5.2辅助信号）:
  龙头创新高 + 当日成交量较前5日萎缩>20% → 冲顶预警，降仓50%观察
  
多龙头分化处理（ROTATION_STRATEGY §4.4 V1.2规则）:
  主龙头EXIT → Track B无条件全出（铁律）
  非主龙头EXIT → 减仓50% + 检查主龙头是否同日走弱
```

**输出信号**：
```json
{
  "scanner": "TB-S3",
  "timestamp": "2026-05-28",
  "active_mainlines": [
    {
      "name": "光模块主线",
      "lead_dragon": "中际旭创300308",
      "today_change": "+7.2%",
      "boards": 3,
      "volume_vs_5d": 1.45,
      "seal_time": "10:23",
      "status": "STRONG"
    },
    {
      "name": "PCB主线",
      "lead_dragon": "胜宏科技300476",
      "today_change": "+3.1%",
      "boards": 0,
      "volume_vs_5d": 1.12,
      "status": "HEALTHY"
    }
  ],
  "signal": "MONITOR",
  "action": "无需操作，主线健康",
  "exit_triggers": []
}
```

**执行频率**：盘中（W1）每2小时刷新，收盘后（W2）记录终态。**呼气期这是唯一保留运行的Scanner。**

---

### TB-S4: 催化剂日历前瞻（Catalyst Calendar）

**扫描维度**：未来7天/30天的α级催化剂，以及这些催化剂影响产业链的哪个层级。

**设计原则**：Track B的优势是提前布局，在催化剂兑现之前进入。"催化剂日期是几号"是建仓的第一问。

**输入数据**：
- 全球科技大会日历（COMPUTEX/GTC/MWC/CES/苹果WWDC/Google I/O等）
- 国内重要会议/政策窗口（两会/CEWC/产业规划发布）
- 财报季日历（当月发布的季报/业绩预告）
- 海外科技巨头财报日期（NVDA/MSFT/AAPL/TSLA/META）
- 产业链特定事件（BOM发布/订单公告/技术认证）

**判定规则**：

```
催化剂分级（复用strategy.md §2.4分类）:
  α级：特定日期+明确机制（COMPUTEX 6/1, ASCO 5/29）→ 可建仓
  β级：日期范围+方向明确（月度数据窗口，政策季）→ 减半仓
  γ级：主题驱动/无日期 → 不触发TB Discovery

产业链传导映射（基于ROTATION_STRATEGY §5.1 L0-L6）:
  L0催化（海外财报/GTC/COMPUTEX）→ 首先布局L1（光模块/CPO）
  L1已启动≥3日 → 开始关注L2（PCB/覆铜板）建仓窗口
  L2已启动≥5日 → 开始关注L5（CCL/铜箔），L4（封装）3-4周后
  政治局级政策 → 关注Type 4方向性受益板块（不依赖L0-L6传导）
  
预警时间轴:
  7天内有α级催化 → PRIORITY（提前布局窗口开启）
  7-30天有α级催化 → INVESTIGATE（开始研究传导层级）
  30天内只有β/γ级 → MONITOR
```

**输出信号**：
```json
{
  "scanner": "TB-S4",
  "timestamp": "2026-05-28",
  "upcoming_7d": [
    {
      "event": "COMPUTEX 2026",
      "date": "2026-06-01",
      "type": "alpha",
      "days_away": 4,
      "affected_layers": ["L1-光模块/CPO", "L2-PCB/AI服务器"],
      "actionable_now": "L1已启动，关注L2入场时机（T+1-T+2）"
    }
  ],
  "upcoming_30d": [
    {
      "event": "NVDA财报Q2",
      "date": "2026-06-18",
      "type": "alpha",
      "days_away": 21,
      "affected_layers": ["L1-光模块", "L4-HBM封装"]
    }
  ],
  "signal": "PRIORITY",
  "layout_action": "COMPUTEX前4天，L2-PCB建仓窗口已开（D+0至D+2）"
}
```

**执行频率**：每周一更新（W3）。有新重磅事件时实时触发。

---

### TB-S5: 资金流向（Capital Flow Detector）

**扫描维度**：龙虎榜机构/游资方向 + 超大单净流入板块排名，识别主力资金正在布局的方向。

**设计原则**：
- 龙虎榜对于Type 2/4（机构参与）有预测价值；对Type 5（游资主导）仅作入场参考，退出主要靠TB-S3实时监控（ROTATION_STRATEGY §4.5 V1.2）。
- 超大单净流入是机构行为的代理指标，比游资榜更稳定。

**输入数据**：
- 龙虎榜前5席位（机构专用席位 / 已知游资席位）净买卖方向
- 超大单（单笔>500万）净流入板块排名（TOP 10）
- 超大单持续净流入天数（连续3日以上才计）
- 北向月度配置盘变化（6周维度，作为确认信号）

**判定规则**：

```
龙虎榜信号解读（ROTATION_STRATEGY §3.1 + §4.5）:
  机构席位净买入>1亿 + 游资同榜 → A级信号（Type 2/4入场加分项）
  机构+游资三方共振（各>1.5亿）→ S级信号（直接PRIORITY）
  核心游资净卖出≥买入50% → S级退出信号（T+1开盘全出）
  锁仓缩量型连续上榜 → 出货信号（反向，不入场）

超大单净流入规则:
  单板块超大单净流入连续3日 → 该板块INVESTIGATE
  超大单净流入突然从板块A转向板块B（变化>8亿）→ 资金搬家信号
  主线板块超大单净流出>10亿 → 配合TB-S3判断是否减仓（ROTATION_STRATEGY §5.2）

机构vs游资区分（ROTATION_STRATEGY §7.6）:
  仅有游资 → 20日后均跌-1.69%，仅作短期博弈参考
  机构参与 → 20日后均涨+0.71%，适合Type 2更长持有
```

**输出信号**：
```json
{
  "scanner": "TB-S5",
  "timestamp": "2026-05-28",
  "top_big_order_sectors": [
    {"sector": "PCB/覆铜板", "net_inflow_3d": "15.3亿", "consecutive_days": 3, "signal": "INVESTIGATE"},
    {"sector": "CCL材料", "net_inflow_1d": "6.2亿", "consecutive_days": 1, "signal": "MONITOR"}
  ],
  "dragon_tiger_alerts": [
    {
      "ticker": "胜宏科技300476",
      "date": "2026-05-27",
      "institutional_net": "+2.1亿",
      "hotmoney_net": "+0.8亿",
      "type": "机构+游资共振",
      "signal": "PRIORITY"
    }
  ],
  "capital_rotation_signal": "超大单从光模块（净流出-8亿）流向PCB（净流入+12亿），资金搬家确认",
  "signal": "PRIORITY",
  "sector_to_investigate": "PCB/覆铜板"
}
```

**执行频率**：每日收盘后（W2），龙虎榜T+1延迟需次日早上补充。

---

### TB-S6: 产业链传导检测（Industrial Chain Propagation）

**扫描维度**：实时检测L0-L6哪个层级正在启动，有没有新的传导开始。

**设计原则**：这是Track B的核心竞争优势——比随机扫描提前2-10天知道下一个应该看哪里。但ROTATION_STRATEGY §5.1明确警告：Lag天数只是参考范围，每个周期需重新校准，入场以实时日内资金流向为准。

**输入数据**：
- 当前活跃主线的各层级（L1-L6）标的涨跌幅 + 成交量变化
- 各层级龙头启动时间（首次涨停日期）
- 产业链传导进度（哪些层级已启动/哪些未启动）
- L6末端扩散信号（超级电容/元器件小票首次涨停）

**判定规则**：

```
传导层级启动信号:
  某层级3只以上标的同日涨幅≥5% + 成交放量 → 该层级"启动确认"
  某层级首只标的出现涨停 → 该层级"启动预警"（需第二天确认）
  
传导进度判断（基于ROTATION_STRATEGY §5.1修正Lag）:
  L1启动（0-3天后）→ 开始扫描L2入场时机（不依赖历史Lag，看实时资金流）
  L2启动（0-2周后）→ 开始扫描L5（CCL/上游材料）入场时机
  L4（封装）：滞后L1高点2-4个月，特殊路径
  L6首次出现 → ★★★ 退潮预警（主线降仓50%，L6本身不建仓）
  L6连续2-3天 → 可能独立主线（需TB-S4确认有自身产业催化）
  
T1→T2升级监测（ROTATION_STRATEGY §2.4）:
  T1事件发生后D+3到D+7：扫描是否出现具体BOM数字/订单验证
  有 → 标记"T1→T2升级"，触发PRIORITY
  无 → 继续按T1规则（5天持仓上限）
  
新传导链检测（非AI算力链）:
  非L0-L6传导序列中的板块出现连续3日涨停 → "独立主线启动"
  触发TB-S4确认是否有α级催化剂支撑
```

**输出信号**：
```json
{
  "scanner": "TB-S6",
  "timestamp": "2026-05-28",
  "ai_chain_status": {
    "L1_光模块": {"status": "started", "start_date": "2026-05-06", "days_since": 22, "note": "主升期结束，进入分歧"},
    "L2_PCB": {"status": "started", "start_date": "2026-05-22", "days_since": 6, "note": "启动确认，Rubin BOM驱动"},
    "L5_CCL": {"status": "starting", "start_date": "2026-05-26", "days_since": 2, "note": "启动预警，提价逻辑"},
    "L6_末端": {"status": "warning", "signal_date": "2026-05-19", "note": "江海股份第1次=退潮预警已发，第2-3次独立主线待确认"}
  },
  "new_chain_signals": [],
  "t1_to_t2_check": null,
  "signal": "INVESTIGATE",
  "action": "L5-CCL处于启动预警，关注今明两天成交量确认；L6已出现退潮预警，主线降仓"
}
```

**执行频率**：盘中（W1）12:00/14:30各扫一次。收盘后（W2）汇总。每周一（W3）做完整周度回顾。

---

### TB-S7: Anti-Cocoon for Track B（轮动策略反茧房）

**扫描维度**：专门检测Track B轮动策略的茧房风险。三层茧房各有独立检查项。

**设计原则**：与Track A的Anti-Cocoon Dashboard（8指标/Cocoon Index）独立运行，因为Track B的茧房类型完全不同——不是"行业不看全"，而是"只会一种轮动类型"或"只看一条产业链"。

**5个反茧房检查项**：

```
TC1 - 主线集中度检查（防止主线茧房）:
  当前活跃监控的主线是否全部来自同一大板块（如全部TMT）？
  绿灯：3条主线中至少1条来自非TMT板块
  黄灯：2条以上来自TMT，无消费/周期
  红灯：3条全部TMT，完全没有非科技主线在视野内
  → 红灯时：强制扫描当周成交额TOP 5的非TMT板块

TC2 - 轮动类型覆盖检查（防止类型茧房）:
  过去4周参与/研究的Track B机会，Type 1/2/3/4/5各占多少？
  绿灯：覆盖至少3种类型
  黄灯：仅覆盖1-2种类型（如只有Type 2和Type 3）
  红灯：连续4周只有1种类型
  → 红灯时：强制研究最近1次未参与的其他类型案例

TC3 - 板块轮动盲区检查（防止深度茧房）:
  本周全市场TOP 30涨幅中，完全没有在TB-S2/S5监控中出现的板块有多少？
  绿灯：盲区板块 < 5个
  黄灯：盲区板块 5-10个
  红灯：盲区板块 > 10个
  → 红灯时：对盲区板块做TB-S4催化剂检查

TC4 - 北交所覆盖检查（防止北交所盲区）:
  当主板吸气期已≥5天，北交所对应标的是否已在监控中？
  ROTATION_STRATEGY §3.3：北交所最佳建仓点在主板启动T+3至T+5
  绿灯：主板吸气期≥3天时，北交所有对应标的在MONITOR
  黄灯：主板吸气期≥5天但北交所仍无标的
  红灯：主板吸气期≥7天且未研究北交所任何标的
  → 红灯时：强制扫描北交所对应板块（日均成交>2000万的标的）

TC5 - 末端追逐检查（防止L6追逐茧房）:
  最近2周内是否有在L6（末端扩散）出现后才入场的记录？
  "末端茧房"：只看见末端涨停，忽视L1-L2正在启动
  绿灯：无L6追逐记录
  黄灯：1次L6后期入场（L6出现2-3天后才发现）
  红灯：2次以上L6后追，或专门追末端题材
  → 红灯时：复盘为什么TB-S6没有提前发现L1-L2启动
```

**输出信号**：
```json
{
  "scanner": "TB-S7",
  "timestamp": "2026-05-28",
  "checks": {
    "TC1_mainline_concentration": {"status": "GREEN", "detail": "光模块(TMT)+PCB(TMT)+巨化(化工) 2TMT+1非TMT"},
    "TC2_type_coverage": {"status": "YELLOW", "detail": "近4周仅Type 2+Type 3，未参与Type 4/5"},
    "TC3_sector_blindspot": {"status": "GREEN", "detail": "盲区板块3个，在安全范围"},
    "TC4_bse_coverage": {"status": "GREEN", "detail": "蘅东光已在MONITOR"},
    "TC5_tail_chasing": {"status": "GREEN", "detail": "无L6后追记录"}
  },
  "tb_cocoon_index": 82,
  "signal": "MONITOR",
  "action": "TC2黄灯：下周研究1次Type 4政策驱动案例（如新能源/国防政策方向）"
}
```

**执行频率**：每周一（W3）全量跑。每周五（W4）TC3补充Anti-Portfolio逻辑检查。

---

## 四、信号聚合规则

### 4.1 聚合逻辑

同一方向/标的触发的Scanner数量决定信号级别：

| 触发Scanner数量 | 信号级别 | 行动 | 时间预算 |
|-------------|---------|------|---------|
| 1个 | **MONITOR** | 加入TB观察列表，等确认信号 | 0分钟 |
| 2个（含TB-S4或TB-S5任一） | **INVESTIGATE** | 15分钟快速研究：类型判断/龙头验证/入场时机 | 15分钟 |
| 2个（均为TB-S1+TB-S2组合） | **MONITOR**（情绪Scanner共振价值低） | 记录，等主线Scanner确认 | 0分钟 |
| 3个及以上 | **PRIORITY** | 30分钟完整评估，执行TB 4-Gate | 30分钟 |
| TB-S3触发EXIT | **HARD EXIT** | 立即执行Track B铁律，当日全出（无需聚合评估） | 0分钟（直接执行） |
| TB-S1触发CRASH + TB-S3任何WARNING | **HARD EXIT** | 触发ROTATION_STRATEGY §1.4紧急关闭条件 | 0分钟 |

### 4.2 Scanner共振加权（特殊组合）

某些Scanner组合的含义远超简单叠加：

| 组合 | 含义 | 处理 |
|------|------|------|
| TB-S4（α催化剂7天内）+ TB-S6（对应层级启动）| 催化剂+市场确认，入场窗口开启 | 直接PRIORITY |
| TB-S5（机构+游资共振）+ TB-S4（α催化剂支撑）| S级入场信号（ROTATION_STRATEGY §3.1） | 直接PRIORITY，可适当加速入场 |
| TB-S2（板块成交占比急升）+ TB-S6（该层级传导启动）| 资金流入+板块动作双确认 | PRIORITY |
| TB-S1（LOW/退潮）+ TB-S3（龙头WARNING）| 情绪+龙头双恶化 | 触发§1.4 退出检查 |
| TB-S7红灯（任意TC）+ TB-S4（新方向催化）| 茧房突破信号——正在遗漏的板块有催化剂 | 强制INVESTIGATE，不可拒绝 |
| TB-S5（超大单板块A→板块B资金搬家）+ TB-S2（板块B成交占比上升）+ TB-S6（板块B层级启动）| 三信号资金搬家确认 | PRIORITY，旧仓减半，新方向建仓 |

### 4.3 TB 4-Gate评估（PRIORITY标的用）

```
Gate 0：策略硬开关 — F20呼气期/涨停家数<30家/TB-S1 CRASH 任一 = 停止
Gate 1：类型判断 — 是Type 1/2/3/4/5哪种？不同类型持仓上限/止损规则不同（§2.1）
Gate 2：Bear Case过滤 — 龙头已见顶迹象（量价背离+主力净卖出）→ 排除
Gate 3：SABCD评级 — Track B最高B+级（strategy.md §2.4b铁律）
Gate 4：仓位容量 — 现有Track B仓位是否已满15%？北交所≤5%是否有空间？
```

---

## 五、扫描频率与时间窗口

### 5.1 完整时间表

| 时间 | Scanner | 频率 | 说明 |
|------|---------|------|------|
| **盘前 08:30-09:00** | TB-S3快速检查 | 每日 | 检查昨日龙头状态，确认今日止损线 |
| **盘中 W1-09:15** | TB-S3实时监控 | 每日，2小时间隔 | 主线龙头状态实时追踪 |
| **盘中 W1-12:00** | TB-S6中间扫描 | 每日 | 产业链传导日内变化 |
| **盘中 W1-14:30** | TB-S6 + TB-S3 | 每日 | 临收盘前综合判断，确认If-Then执行 |
| **收盘后 W2-15:15** | TB-S1 + TB-S2 + TB-S3终态 | 每日 | 情绪 + 资金流 + 龙头终态 |
| **收盘后 W2-16:00** | TB-S5（龙虎榜T+0） | 每日 | 大单净流入，当日龙虎榜（T+1延迟需次日补充） |
| **次日早 09:00** | TB-S5（龙虎榜T+1补充） | 每日 | 前日龙虎榜席位确认 |
| **每周一 W3** | 全量：TB-S1~S7 | 每周 | 完整Discovery扫描，配合F20状态更新 |
| **每周一 W3** | TB-S4完整催化剂日历 | 每周 | 更新30天催化剂前瞻 |
| **每周一 W3** | TB-S7 Anti-Cocoon全量 | 每周 | 5项反茧房检查 |
| **每周五 W4** | TB-S7 TC3（成交TOP 30检查）| 每周 | Anti-Portfolio for Track B |

### 5.2 与Track A Discovery的时间错开

Track A Discovery（_DISCOVERY_SYSTEM.md）在每周一 W3 执行，约需30分钟：

```
时间安排（周一，避免算力冲突）:
  W3 08:30-09:00  → F20市场呼吸状态更新（两者共用）
  W3 09:30-10:00  → Track A Discovery（S1-S6全跑）
  W3 14:30-15:00  → Track B Discovery（TB-S1~S7全跑）+ §4.5轮动检测
  
分离原因:
  1. Track A侧重基本面信号（PEAD/机构调研），Track B侧重情绪和传导信号，信息源不同
  2. 两者同时跑无实质算力冲突，但分开执行可以用Track A的发现作为Track B的信息输入
  3. Track A中的板块发现（S4 Anti-Sector）可以喂给Track B的TB-S7 TC3检查
```

---

## 六、Track A → Track B 联动机制

### 6.1 信息共享规则

**Track A发现好板块 → Track B同步寻找小市值接力票**

```
触发条件（Track A Discovery产出后检查）:
  Track A发现新标的 + 评级≥A + 催化剂<30天
    → 自动触发Track B问题：
       "同板块有市值<500亿、业务相关、尚未启动的小票吗？"
       → 有：直接进Track B INVESTIGATE流程（跳过TB-S4/S6扫描）
       → 无：记录到TB观察列表，等龙头启动后T+1再找
    
Track A板块龙头（>500亿）持仓状态 → 直接作为Track B TB-S3的龙头追踪对象
Track A发现政策催化（S5信号）→ 触发Track B TB-S4更新（政策驱动Type 4机会）
```

### 6.2 共享数据结构建议

Track A和Track B共用以下数据（建议写入 `rotation-strategy/data/tb_discovery_state.json`）：

```json
{
  "last_updated": "2026-05-28",
  "f20_state": "吸气",
  "active_mainlines": [...],
  "ta_to_tb_signals": [
    {
      "source": "Track A S5",
      "mainline": "PCB/覆铜板",
      "ta_ticker": "胜宏科技",
      "tb_candidates": ["彤程新材", "南亚新材"],
      "ta_catalyst": "Rubin BOM",
      "catalyst_date": "2026-05-22",
      "status": "INVESTIGATE"
    }
  ],
  "tb_watchlist": [...],
  "cocoon_index": 82,
  "tb_scanner_results": {...}
}
```

### 6.3 信息流方向

```
Track A S4（板块盲区）→ TB-S7 TC3（确认是否也是Track B的轮动盲区）
Track A S5（政策催化）→ TB-S4（Type 4机会前瞻更新）
Track A S6（涨停质量，龙头级别）→ TB-S3（龙头追踪启动）
Track A PRIORITY标的 → TB-S6（该板块传导层级状态）
Track B TB-S2（板块成交转向）→ Track A提醒（"某板块资金流入，是否需要基本面覆盖"）
```

---

## 七、输出格式：rotation_scan.py集成设计

### 7.1 输出格式标准

所有Scanner输出统一为JSON格式，存入 `rotation-strategy/data/tb_scan_YYYYMMDD.json`：

```json
{
  "scan_date": "2026-05-28",
  "scan_type": "daily | weekly",
  "f20_state": "吸气",
  "strategy_open": true,
  "scanners": {
    "TB-S1": { ... },
    "TB-S2": { ... },
    "TB-S3": { ... },
    "TB-S4": { ... },
    "TB-S5": { ... },
    "TB-S6": { ... },
    "TB-S7": { ... }
  },
  "aggregated_signals": [
    {
      "direction": "PCB/覆铜板",
      "scanners_triggered": ["TB-S4", "TB-S5", "TB-S6"],
      "level": "PRIORITY",
      "summary": "COMPUTEX前4天+超大单净流入+L2传导确认",
      "action": "执行TB 4-Gate评估",
      "candidates": ["胜宏科技", "沪电股份"]
    },
    {
      "direction": "CCL材料",
      "scanners_triggered": ["TB-S6"],
      "level": "MONITOR",
      "summary": "L5启动预警（仅1天），等成交量确认",
      "action": "明日再确认"
    }
  ],
  "hard_exits": [],
  "anti_cocoon": {
    "tb_cocoon_index": 82,
    "red_flags": [],
    "yellow_flags": ["TC2: 未覆盖Type 4/5"]
  }
}
```

### 7.2 rotation_scan.py 调用接口设计

```python
# 建议的脚本调用方式（与现有脚本体系一致）

# 每日收盘后（W2）
uv run --script scripts/rotation_scan.py --mode daily

# 每周一完整扫描（W3）
uv run --script scripts/rotation_scan.py --mode weekly

# 仅运行特定Scanner（如只检查龙头状态）
uv run --script scripts/rotation_scan.py --scanner TB-S3

# 仅更新催化剂日历
uv run --script scripts/rotation_scan.py --scanner TB-S4 --update-calendar

# 盘中实时监控（仅TB-S3）
uv run --script scripts/rotation_scan.py --scanner TB-S3 --realtime

# 输出聚合信号摘要
uv run --script scripts/rotation_scan.py --summary
```

### 7.3 与 decision_engine.py 的集成

TB Discovery的PRIORITY信号应自动注入 `decision_engine.py` 的输入，格式参考现有 `portfolio_state.json` 的 `pending_actions` 结构：

```json
"tb_priority_queue": [
  {
    "direction": "PCB/覆铜板",
    "type": "Track B Type 2",
    "trigger_scanners": ["TB-S4", "TB-S5", "TB-S6"],
    "suggested_tickers": ["胜宏科技300476", "沪电股份002463"],
    "max_position": "15%",
    "entry_window": "今日至明日（COMPUTEX前4天）",
    "stop_rule": "龙头（胜宏科技）跌>5%当日全出",
    "gate_status": "需用户确认Gate 1-4"
  }
]
```

---

## 八、TB-DS和Track A Discovery的关键差异总结

| 维度 | Track A Discovery（_DISCOVERY_SYSTEM.md v2.0） | Track B Discovery（TB-DS v1.0） |
|------|--------------------------------------|-------------------------------|
| 核心目标 | 发现被忽视的基本面机会，打破行业茧房 | 发现轮动传导中的时机，打破主线/类型/深度茧房 |
| 主Scanner | S1-PEAD/S2-量价背离/S3-机构调研/S5-政策/S6-涨停质量 | TB-S3龙头状态/TB-S4催化剂/TB-S5资金流/TB-S6传导检测 |
| 信号窗口 | 5-30天（相对慢） | 1-5天（极快，轮动就是快进快出） |
| 反茧房设计 | 8指标Cocoon Index，防行业盲区 | 5项TC检查，防主线集中/类型单一/末端追逐 |
| 止损机制 | SABCD系统，thesis证伪 | **龙头跌>5%铁律**（覆盖所有Track B持仓） |
| F20敏感度 | 呼气期降为30%功率 | 呼气期硬关闭（除TB-S3持仓监控外） |
| 评级上限 | 无上限（可到S级） | **B+级硬顶**（strategy.md §2.4b铁律） |
| 持仓上限 | conviction决定（S级可50%） | **单只≤15%，北交所≤5%** |
| 时间执行 | 每周一 W3 09:30-10:00 | 每周一 W3 14:30-15:00 + 每日收盘后 |

---

## 附录：无发现时的零扫描报告规范

即使当周无新信号，仍必须记录：

```
TB Discovery Report [日期] [daily/weekly]:
  F20状态: [吸气/中性/呼气/强吸气]
  策略开关: [开/关]
  
  TB-S1 涨停生态: [情绪等级] — [涨停家数/炸板率/连板高度] / 信号: [MONITOR/INVESTIGATE]
  TB-S2 板块成交: [最强板块/变化方向] — [TMT占比/周期占比] / 信号: [MONITOR]
  TB-S3 龙头状态: [主线1龙头: 状态] [主线2龙头: 状态] / 触发EXIT: [无/有：列出]
  TB-S4 催化剂: [7天内α级: X个] [30天内α级: X个] / 信号: [MONITOR/PRIORITY]
  TB-S5 资金流向: [超大单TOP3板块] [龙虎榜机构信号] / 信号: [MONITOR/INVESTIGATE]
  TB-S6 产业链传导: [已启动层级] [预警层级] [L6信号: 无/有] / 信号: [MONITOR/INVESTIGATE]
  TB-S7 反茧房: TC1[G/Y/R] TC2[G/Y/R] TC3[G/Y/R] TC4[G/Y/R] TC5[G/Y/R] — CI: [分数]
  
  聚合信号: PRIORITY x个 / INVESTIGATE x个 / MONITOR x个
  硬退出触发: 无 / [有：列出标的和原因]
  
  行动: [本周无PRIORITY，维持现有持仓] / [PRIORITY: 方向X，执行4-Gate]
```

---

*TB-DS v1.0 | 2026-05-28 | 基于ROTATION_STRATEGY_V1.2 + strategy.md v9.1 + _DISCOVERY_SYSTEM.md v2.0*
*Claude分析意见。所有Scanner参数基于回测研究，实盘需按实际情况校准。*
*设计原则：信号驱动发现（不是thesis驱动），反茧房优先于发现速度，龙头状态是最高优先级的安全阀。*
