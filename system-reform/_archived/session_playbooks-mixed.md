# Session Playbooks — 模拟盘4窗口执行手册
> 版本: v1.0 | 生效: 2026-05-22 | 来源: CLAUDE.md + strategy.md v5.0 + US_TRADING_SYSTEM_V4.md
> 设计原则: 每个窗口只做该窗口的事。不相关的规则不读不查。

---

## UNIVERSAL PRE-FLIGHT（所有session启动前，约30秒，不可跳过）

```
1. git pull origin main
2. uv run --script scripts/risk_monitor.py --no-save
   → exit code 1 = BLOCKED。先读报告修复block，本session禁止交易直到PASSED
   → exit code 0 = PASSED，进入窗口专属playbook
3. 读 pending_actions.json → 标记URGENT项（deadline=today或overdue的）
   → URGENT项必须在本session中处理（不论窗口类型）
4. 确认今日是否交易日：读 market_calendar.json
   → 对应市场休市 → 跳过该市场的所有交易步骤，仅做复盘/研究
```

> APPLIES TO: W1 / W2 / W3 / W4（无例外）
> 完成Pre-Flight后，跳转到对应窗口playbook。

---

## W1 — A股全天 (09:30–15:00 BJT)

**账户范围: A股只（¥1M账户）| 美股不操作**

```
1. [开盘前] 市场呼吸B1扫描：查沪市成交额均值（web-access获取）
   → <8000亿 = 低温：不追高，不新建仓，只监控止损
   → 8000-12000亿 = 正常，按策略执行
   → >12000亿 = 过热，不加仓，评估减仓

2. [开盘前] 查A股持仓实时价格：
   uv run --script scripts/fetch_prices.py
   → 仅读A股持仓（002028/002938/603005/688019/600276/002920）
   → 当前A股持仓数 ≤ 8只（硬约束，超过禁止新建仓）

3. [09:30后] 止损监控：对每只持仓核对止损线
   → S级: 跌7%立即执行，不等ABCD分类
   → 其他级别: 先ABCD分类，D类48h内清仓
   → ABCD分类前禁止任何卖出（60秒分类流程）

4. 检查隔夜美股映射信号：美股大涨/大跌>5%？
   → 是 → 评估对应A股板块影响（30分钟窗口，超过不追）
   → 否 → 跳过

5. 执行pending_actions中的A股预案（If-Then条件触发检查）：
   → 恒瑞600276: ASCO 2026-05-29预案（已触发？）
   → 鹏鼎002938: WWDC 2026-06-08预案
   → 有效预案触发条件满足 → 执行，写进场检查表
   → 条件未满足 → 跳过

6. [可选，仅B1=正常或过热时] 小票先飞信号扫描（web-access）：
   → 同一主题下2+只小票连板？
   → 是 → 找对应真龙头，完成进场检查表后建仓
   → 新建仓上限：单日≤3只（含加仓以外的新开）

7. [13:00-14:30 尾盘前] 止损复查：
   → 今日亏损>2.5%组合净值？→ 暂停新建仓
   → 有触发止损的持仓？→ 当日盘中执行，不留到明日

8. 更新 portfolio_state.json（如有交易）
```

**A股规则适用清单（本窗口）:**
- 适用: L1(仓位上限) / L2(先thesis后建仓) / L5(下跌先分类) / L7(实时价格) / L10(关注点漂移) / L11(催化剂前持有) / L13(追涨三联动) / L14(仓位-Conviction) / L15(Thesis验证) / B1市场呼吸 / ABCD分类 / A股Bear case 4级
- **跳过（本窗口不执行）:** L16/L17/L18（美股专项）/ Regime Detection（VIX/10Y）/ 做空扫描 / 美股进场检查表 / 5维度评分表

---

## W2 — A股收盘结算 (16:00 BJT)

**账户范围: A股收盘后结算 | 不执行新交易（T+1已关市）**

```
1. 记录A股收盘价（yf获取），更新 portfolio_state.json：
   → A股所有持仓 current_price = 今日收盘价
   → 检查日内integrity: Σ持仓市值 + 现金 = total_assets（误差<0.5%）

2. 计算今日A股P&L，与沪深300对比：
   → 今日A股alpha = 组合P&L% - 沪深300P&L%
   → 现金比例 ≥ 15%？（加仓后须≥20%，违反→标记待处理）

3. W1止损检查复盘：今日是否有触发止损未执行？
   → 有 → 写入pending_actions（明日W1优先执行）
   → 无 → 继续

4. [如是周五] 周度触发检查（strategy.md §13）：
   → 周度亏损>5%？→ 下周前3日禁止新建仓
   → 周度亏损>8%？→ 全仓review，写降级决策

5. 5维度研究（D1/D3/D4/D5，约30-45分钟）：
   D1: 从watchlist_config选1只A股候选，完成97分制评分
   D3: 选1只现有持仓找反面证据（"空头怎么攻击？"）
   D4: 宏观——今日数据→判断→对A股持仓含义
   D5: 扫描今日涨停板名单，识别小票先飞信号

6. 更新catalyst_calendar：已过期事件标为completed/expired

7. 写 daily-reviews/YYYY-MM-DD.md 的A股部分
```

**本窗口适用规则:** L9(计划偏差记录) / D1-D5研究框架（A股部分）
**本窗口不执行:** 任何新交易（收盘后无法成交）/ 美股规则 / L16/L17/L18 / 做空

---

## W3 — 美股开盘 (22:00 BJT / 10:00 ET)

**账户范围: 美股只（$150K账户）| 不操作A股**

```
1. [L17强制执行链，5步，不可跳过任何一步]
   Step 1: 读 portfolio_state.json → 确认当前美股状态
   Step 2: 检查空头暴露：当前空头仓位数量___（目标0<x≤3）
           → 空头=0 → 记录原因，如超过5个交易日=系统失败，触发L18
   Step 3: Regime Detection（30秒）：
           VIX___（5日delta>+20%=Warning; >+30%=Action）
           10Y yield___（5日变化>+10bp=Warning; >+15bp=Action）
           → 1个信号触发 = Cautious，暂停新建仓
           → 2+信号触发 = Regime Shift，24h内减仓调方向
   Step 4: 读 pending_actions.json → 执行美股URGENT项
   Step 5: 催化剂24h倒计时扫描：
           → 06-02 DG Q1财报（<12h？→ 持有，L11默认持有）
           → 06-03 CRM Q1财报（<12h？→ 同上）
           → 06-08 AAPL WWDC / 06-11 ADBE（跟踪）

2. 查美股持仓实时价格：uv run --script scripts/fetch_prices.py
   → 美股持仓数量检查：多头 ≤ 6只，空头 ≤ 3只（总≤9）[L16]
   → 单只低于$7,500？→ 标记（不新建低于此门槛的仓位）

3. ABCD分类（下跌>2.5% SPY同步才考虑A类）：
   → 任何持仓单日亏损>7%：强制ABCD分类
   → D类：48h内清仓
   → C+类：24h内核实

4. 执行美股预案（If-Then触发检查）：
   → 评估CRM/DG预承诺条件是否触发
   → 如需建仓：必须先完成5维度评分表（无表=不交易）

5. [仅周三22:00] L18强制做空扫描SOP（不可跳过）：
   a. 读 watchlist_config.json us_short_candidates（MSTR/INTC/WMT）
   b. 查VIX：>25 → 暂停，不建空头，记录原因
   c. 对候选标的打空头评分（满10分，≥7.0执行）
   d. 执行或pass，写扫描记录（0笔也写）

6. 止损复查：
   → S级: 跌7%立即执行
   → C级: 跌8%硬止损
   → 今日组合亏损>2.5%？→ 暂停新建仓

7. 有新建仓需求时，运行决策建议（可选）：
   uv run --script scripts/decision_engine.py --dry-run
   → agent审阅后决定是否执行

8. 执行交易（如有）：
   uv run --script scripts/execute_trade.py ...
   → 执行后立即更新 portfolio_state.json

9. 更新 portfolio_state.json
```

**美股规则适用清单（本窗口）:**
- 适用: L16(散弹枪禁令) / L17(执行链5步) / L18(做空配额) / Regime Detection三重信号 / 美股5维度评分 / 美股Bear case 4级(35%门槛) / 美股Momentum框架 / 美股做空4分类 / VIX路径决策树 / GAP规则 / L13 / L14 / L15
- **跳过（本窗口不执行）:** A股规则一切 / 市场呼吸B1-B5 / 小票先飞扫描 / A股97分制 / A股Bear case阈值(用美股35%替代) / T+1约束

---

## W4 — 美股收盘 + 全面复盘 (04:00 BJT / 16:00 ET)

**账户范围: 美股结算 + 全组合复盘 | 不执行新交易**

```
1. 记录美股收盘价，更新 portfolio_state.json：
   → 所有美股持仓 current_price = 收盘价
   → 检查integrity: Σ持仓市值 + 现金 = total_assets（误差<0.5%）

2. 计算今日美股P&L，与SPY对比：
   → 空头暴露是否仍在10-15%目标区间？（$15-22.5K）
   → 美股现金 ≥ 15%？

3. 盘后财报反应处理（如当日AMC有财报）：
   → Beat+guidance上调 → 明日W3建仓/加仓预案写入pending_actions
   → Miss → ABCD分类，预案写入pending_actions

4. 全组合级风控检查（A股+美股合并）：
   → 跨市场同行业暴露 ≤ 45%（如AI板块A股+美股合并）
   → 现金部署进度符合Day N时间表（strategy.md §3.5）

5. 5维度研究（完整版，约30-45分钟）：
   D1: 从watchlist选1只美股候选，完成5维度评分表
   D2: 建立/更新1个做空thesis（us_short_candidates）
       → 跨市场检查: 做空thesis影响A股持仓？同步评估（如TSLA→德赛西威）
   D3: 选1只持仓（A股或美股）找反面证据
   D4: 宏观——今日数据→判断→对全组合含义
   D5: 扫描今日新闻，找新机会，更新watchlist_config.json

6. 为次日A股W1准备映射信号：
   → 美股涨跌>5%板块 → 对应A股板块受影响标的列表
   → 写入pending_actions（W1优先查阅）

7. [如是周五] 周度复盘：
   → 本周胜率 / alpha vs基准 / 执行规则违反记录
   → Conviction re-ranking（持仓按当前thesis强度重排）
   → 待观察标的watchlist维护（降级/排除/晋升）

8. 检查现金部署时间表（strategy.md §3.5）：
   → 当前Day N的现金目标是多少？
   → 现金空转连续3天超阈值？→ 强制从watchlist选1只B级以上建仓

9. 写 daily-reviews/YYYY-MM-DD.md（完整版，含A+美股+宏观+5维度产出）

10. git提交：
    git add portfolio_state.json daily-reviews/ research-notes/
    git commit -m "{window-type}: {YYYY-MM-DD} {HH:MM} | A股¥{NAV} | 美股${NAV} | {trades or no-trade} | {关键发现}"
    git push origin main
```

**本窗口适用规则:** D1-D5全部5维度 / 全组合风控（A+美股合并视图） / 现金部署时间表
**本窗口不执行:** 新交易（美股已收盘）/ 实时价格查询 / 任何止损执行（留pending_actions给次日W1/W3）

---

## 速查：各窗口规则边界

| 规则/检查项 | W1 A股全天 | W2 A股收盘 | W3 美股开盘 | W4 美股收盘 |
|------------|-----------|-----------|------------|------------|
| 实时价格查询 | A股只 | A股收盘价 | 美股只 | 美股收盘价 |
| L13三行检查 | ✓ | N/A | ✓ | N/A |
| L16散弹枪禁令 | N/A | N/A | ✓ | 复盘检查 |
| L17执行链5步 | N/A | N/A | ✓强制 | N/A |
| L18做空配额 | N/A | N/A | ✓周三强制 | 检查状态 |
| Regime Detection | N/A | N/A | ✓ | N/A |
| A股ABCD分类 | ✓ | 不可操作 | N/A | N/A |
| 市场呼吸B1-B5 | ✓ | N/A | N/A | N/A |
| 5维度研究D1-D5 | N/A | D1/D3/D4/D5 | N/A | D1-D5全部 |
| D2做空研究 | N/A | N/A | N/A | ✓ |
| If-Then预案执行 | A股预案 | N/A | 美股预案 | N/A |
| git commit | 有交易时 | N/A | 有交易时 | ✓每次必做 |
| 新交易 | ✓(A股) | ✗ | ✓(美股) | ✗ |

---

## 附：关键脚本速查

```bash
# 价格（实时）
uv run --script scripts/fetch_prices.py

# 风控检查（Pre-Flight必用）
uv run --script scripts/risk_monitor.py --no-save

# 决策建议（仅参考，agent自决）
uv run --script scripts/decision_engine.py --dry-run

# 执行交易
uv run --script scripts/execute_trade.py buy|sell|short|cover --account cn|us --ticker XXX --shares N --reason "..."

# 绩效分析（W2/W4）
uv run --script scripts/performance.py

# 新闻扫描（D5）
uv run --script scripts/news_scan.py
```

> **来源映射**: Pre-Flight←CLAUDE.md§脚本接口; W1←strategy.md§6 W1+§4.5; W2←strategy.md§6 W2+§7; W3←CLAUDE.md L16-L18+US_TRADING_SYSTEM_V4.md; W4←strategy.md§6 W4+§7
