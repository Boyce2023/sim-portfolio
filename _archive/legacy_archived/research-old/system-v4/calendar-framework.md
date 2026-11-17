<!-- DEPRECATED: This file is preserved as reference only.
     Authority: US_TRADING_SYSTEM_V4.md §0-§8
     Last sync: 2026-05-22
     Do not modify this file — changes go to the main doc
     Note: §三中的简化做空评分体系（4维无权重，VIX≥18阈值）已废弃；做空评分用主文档§5.3
     Use case: 催化剂链条详细说明、事件checklists完整版（重大事件前准备参考） -->

# 催化剂日历系统 — v4.0框架
**Agent-18 | 美股交易系统v4.0 | 2026-05-22**

---

## 一、固定事件年度模板（2026下半年）

### FOMC（8次/年，2026下半年4次）

| 日期 | 类型 | 关键看点 |
|------|------|---------|
| 2026-07-28~29 | 7月FOMC | 通胀路径确认，dot plot不更新 |
| 2026-09-15~16 | 9月FOMC ★ | 含新dot plot + SEP，最重要一次 |
| 2026-11-04~05 | 11月FOMC | 选后首次，政策转向窗口 |
| 2026-12-15~16 | 12月FOMC ★ | 含dot plot，H2 Dec 100%WR原型事件 |

> ★ = dot plot更新场，利率敏感板块方向性最强。回测锚点：H2 Dec FOMC鹰派cut→100%WR(25笔)，关键在dot plot而非cut本身。

### CPI（每月第二周二/三，8月起固定规律）

| 月份 | 大致日期 | 备注 |
|------|---------|------|
| 2026-07 | 7月14日（周二） | |
| 2026-08 | 8月12日（周三） | |
| 2026-09 | 9月15日（周二） | FOMC同周，叠加效应 |
| 2026-10 | 10月14日（周三） | |
| 2026-11 | 11月12日（周四） | |
| 2026-12 | 12月10日（周四） | FOMC同周，叠加效应 |

### NFP（每月第一周五）

| 月份 | 大致日期 |
|------|---------|
| 2026-07 | 7月3日 |
| 2026-08 | 8月7日 |
| 2026-09 | 9月4日 |
| 2026-10 | 10月2日 |
| 2026-11 | 11月6日（选后周） |
| 2026-12 | 12月4日 |

### 财报季（四次，每次约6周）

| 季度 | 开始 | 高峰 | 结束 |
|------|------|------|------|
| Q2 2026 (H2财报季第一波) | 7月中旬 | 7月下旬~8月初 | 8月中旬 |
| Q3 2026 | 10月中旬 | 10月下旬~11月初 | 11月中旬 |

**财报季核心节点（按依赖链排序）：**
- TSMC Q报 → NVDA财报领先指标（L12，H1验证两次）：TSMC通常早于NVDA 2-3周
- 大行（JPM/GS）财报第一周 → 宏观情绪定基调
- FAANG财报第二三周 → 科技板块定方向

### 期权到期（OpEx）

- **Monthly OpEx**：每月第三周五
  - 2026年下半年：7/17, 8/21, 9/18, 10/16, 11/20, 12/18
- **Weekly OpEx**：每周五
- **Triple Witching**（季度结算）：9/18（最重要），12/18

---

## 二、催化剂链条速查表（已验证）

### Chain 1：TSMC → NVDA领先信号
```
TSMC季度财报（超预期/下调guidance）
    ↓ T+2~7天
NVDA财报预判调整 → 入场/减仓决策
```
- 验证次数：H1两次均有效
- 操作：TSMC beat + AI收入超预期 → NVDA财报前3-5天建仓；TSMC guidance下调 → NVDA减仓
- 注意：NVDA本身是高PE（H2 L13）—— 财报后是卖出窗口，不是买入

### Chain 2：S&P指数调整 → 机械买入套利
```
标准普尔公告新成分股（公告日T=0）
    ↓ T+1执行买入
持有至effective date（通常T+5~20天）
    ↓ effective date当天或前1天减仓
```
- 历史胜率：~80%+（APP +26.8%，HOOD +24.8%，H1 L13）
- 规则：公告日T+1入场；仓位≤15%（B级）；effective date当天清仓，不贪
- 风险：大盘系统性下跌会压制alpha；已成为共识trade，alpha在收窄

### Chain 3：FOMC dot plot → 利率敏感板块
```
FOMC会议（含dot plot更新）
    ↓ 声明+记者会当天
利率预期变化 → 板块方向
```
- 鸽派（降息+点阵图维持）→ 多：REITs/TMT长久期/GLD；空：银行/美元
- 鹰派cut（降息但dot plot删减次数，H2 Dec原型）→ 多：短久期；空：TLT/长久期债券
- 操作：FOMC前24h建仓，声明后执行，不持有过夜超过3天

### Chain 4：CPI数据 → GLD/TLT方向
```
CPI数据公布（8:30 ET）
    ↓ 15分钟内市场定价
高于预期 → GLD上/TLT下；低于预期 → TLT上/GLD观望
```
- GLD H2验证：13笔交易平均+3.8%，在通胀和避险两种regime均为正

### Chain 5：AI突破消息 → 硬件vs软件分化
```
重大AI算法/模型突破公告（如DeepSeek类事件）
    ↓ 当天盘后
硬件（NVDA/AVGO）：contracted capex，短期波动后回归
软件（MSFT/CRM）：cloud margin压力，持续承压
```
- 验证：DeepSeek事件MSFT -16.4%，NVDA恢复（H2 L5）
- 操作：突破公告后，做空high-valuation AI软件名字（MSFT/PLTR），持有1-2周

---

## 三、每周三空头扫描协议（固定）

**执行时间**：每周三（W3窗口22:00 ET）

**扫描步骤**：
1. 读 `watchlist_config.json` 中 `short_candidates` 字段
2. 检查VIX水位：VIX<15做空胜率低，VIX>20做空胜率高（H2 L8: 75% WR）
3. 对每个候选打评分（满10分）：
   - Thesis清晰度（0-3）：能一句话说清楚为什么跌
   - 催化剂（0-3）：30天内有具体日期触发
   - 估值水位（0-2）：高PE/高期望是做空的加速器
   - 技术面（0-2）：破位/死叉
4. 评分≥7 + VIX≥18 → 执行，仓位≤8%（C级）
5. 全部pass也必须写记录（日期 + 扫描标的 + pass原因）

**禁止做空的情形**：
- 大盘连续下跌3周+（H2 L3/L12：做空质量compounder在多周跌后=最贵错误）
- 催化剂模糊（"感觉要跌"不算催化剂）
- VIX<15且无具体触发

---

## 四、每次事件Pre-trade Checklist

### FOMC前Checklist
- [ ] 查CME FedWatch当前降息概率（https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html）
- [ ] 确认本次是否含dot plot更新（3/6/9/12月）
- [ ] 准备两种场景预案：
  - 鸽派（超预期降息或维持）→ 目标标的 + 方向 + 仓位
  - 鹰派（不降或删减次数）→ 目标标的 + 方向 + 仓位
- [ ] 检查组合中利率敏感持仓（TLT/REITs/长久期科技）
- [ ] 声明前不重仓单一方向（避免赌方向）

### CPI前Checklist
- [ ] 查彭博/WSJ预期值（Core CPI YoY/MoM）
- [ ] 准备两种场景：
  - 高于预期（>0.1%偏差）→ GLD多/TLT空/科技空
  - 低于预期（<-0.1%偏差）→ TLT多/GLD观望/REITs多
- [ ] 确认GLD当前持仓水位（默认持有作为macro hedge）

### 财报前Checklist
- [ ] 查options implied move（财报当周ATM straddle价格/当前股价）
- [ ] 查历史平均earnings move（过去8季度平均）
- [ ] implied move vs 历史平均：implied明显低估→考虑做多波动率
- [ ] 确认PE水位（>50x = 高PE模式，beat也可能下跌）
- [ ] 查pre-earnings run-up：财报前30天涨幅>20%→不做earnings bet（已price in）
- [ ] 决策树判断（见agent-earnings.md §七）
- [ ] 仓位上限：单笔earnings bet ≤ 8%（L15铁律）

### S&P成分股调整Checklist
- [ ] 公告日确认（标普通常在收盘后发布）
- [ ] 确认effective date（通常公告后5-20个交易日）
- [ ] T+1开盘建仓，≤15%仓位
- [ ] 日历标注effective date，提前1天减仓提醒
- [ ] 检查是否已成为拥挤trade（同一标的多个媒体都在报）

---

## 五、催化剂过期处理规则

| 状态 | 条件 | 动作 |
|------|------|------|
| 催化剂落地+方向确认 | 事件如期发生，stock按预期走 | 持有，按exit framework管理（不因"已兑现"提前离场，L11） |
| 催化剂落地+不及预期 | Beat但stock下跌，或guidance miss | 24h内决定：减仓30-50%（C+处理）；48h仍无反转→降级清仓 |
| 催化剂落地+gap is the move | 大gap开盘>10% | gap当天减仓50%；>15%全退（META模式，H2 L14） |
| 催化剂延期 | 事件推迟无新日期 | 重新评估thesis；降一个信心级别；无新催化剂→T级处理 |
| 催化剂已过30天无新催化剂 | 持仓超30天且无upcoming events | T/C级清退；A/B级重新写thesis后决定 |
| Thesis被证伪 | 硬数据否定买入逻辑 | D类处理：48h内无条件清仓 |

---

## 六、日历维护协议

**每周日（30分钟）**：
1. 更新 `CLAUDE.md` 中"催化剂日历（30天内）"表格
2. 标注下周FOMC/CPI/NFP/OpEx
3. 更新所有持仓的财报日期（来源：ir.company.com 或 earnings whispers）
4. 删除已过期催化剂行（标COMPLETED）

**每月初（月初第一个周日，15分钟）**：
1. 更新当月所有固定事件日期（CPI/NFP/FOMC/OpEx）
2. 检查财报季是否开始（7月中/10月中）
3. 重置月度空头扫描记录

**财报季前2周**：
1. 更新组合内所有持仓财报日期
2. 更新watchlist所有跟踪标的财报日期
3. 标注TSMC财报日期（NVDA领先指标）
4. 检查哪些标的有earnings bet资格（PE水位+pre-earnings run-up）

**新建仓时（当场执行）**：
1. 查标的下一个catalyst（财报/发布会/数据日期）
2. 写入催化剂日历
3. 设置30天重评提醒

---

*来源：H1/H2回测数据锚点 + agent-earnings.md + H2_SUMMARY.md Lessons | 2026-05-22*
