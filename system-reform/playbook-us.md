# 美股 Session Playbooks v1.0
> 版本: 1.0 | 生效: 2026-05-23 | 来源: US_TRADING_SYSTEM_V4.md + CLAUDE.md
> 设计原则: 纯美股。

---

## Pre-Flight（所有美股session启动前，约30秒，不可跳过）

```
1. git pull origin main
2. uv run --script scripts/pre_session_check.py --market us
   → exit code 1 = BLOCKED。先读报告修复block项，BLOCKED=禁止交易
   → exit code 0 = PASSED，进入W3或W4 playbook
3. 读 pending_actions.json（过滤 market=us 的项）
   → URGENT项（deadline=today或overdue）→ 本session必须处理
4. 确认今日NYSE是否交易日：读 market_calendar.json
   → 休市 → 跳过所有交易步骤，仅做研究/复盘
```

---

## W3 — 美股盘前+盘中 (22:00 BJT / 10:00 ET)

**账户范围: 美股只（$150K账户）**

```
[L17强制执行链，5步，按序不可跳过]

1. 读 portfolio_state.json → 确认美股持仓/现金/NAV（SSOT）
   → Integrity check: Σ多头市值 + Σ空头市值×(-1) + 现金 = total_assets（误差<0.5%）
   → 不平衡 → 先修复再做任何交易决策

2. 空头暴露检查：
   → 当前空头仓位数: ___（目标1-3只，暴露目标10-15%）
   → 空头=0 → 记录原因；若连续超5个交易日=系统失败，立即触发L18扫描

3. Regime Detection（30秒，三重信号）：
   → VIX: ___（<18绿灯 / 18-25黄灯暂停新建仓 / >25红灯禁空头 / >35逆向做多）
   → VIX 5日delta: ___（>+20%=Warning; >+30%=Action立即评估所有持仓）
   → TNX 5日变化: ___bp（>+10bp=Warning; >+15bp=Action; 突破4.7%=禁高PE多头）
   → 信号汇总: 0个=维持 / 1个=Cautious等2天 / 2+个=Regime Shift执行24h协议

4. 执行 pending_actions.json 中 market=us 的URGENT项

5. 催化剂24h倒计时扫描（财报/FOMC/CPI/NFP等）：
   → <12h到期 → L11默认持有；复查ABCD分类状态
   → <48h到期 → 确认If-Then预案是否写入pending_actions

[Regime通过后继续以下步骤]

6. 查美股持仓实时价格：
   uv run --script scripts/fetch_prices.py
   → 持仓数量确认：多头___/6只，空头___/3只（总___/9）[L16]
   → 任何持仓单只<$7,500 → 标记（不新建低于此门槛的仓位）

7. 止损复查（对每只持仓核对）：
   → S级: 从入场价跌7%→EOD立即全退（硬规则，不等ABCD分类）
   → A/B级: 从高点回落-12%/-10%→按trailing分批减
   → C/T级: 跌8%→硬止损全退
   → 所有空头: VIX>25→立即全cover（硬规则）
   → 空头亏损-10%→硬止损
   → 今日组合亏损>2.5%→暂停新建仓

8. ABCD分类（任何持仓有下跌时先分类再决定）：
   → A类（SPY同步跌≥2.5%，无个股新闻）→ Hold
   → D类（财报miss/重大客户流失/政策否决）→ 48h内清仓

9. 执行美股预案（If-Then触发检查）：
   → 读 portfolio_state.json 中的 if_then 字段
   → 条件满足 → 完成5维度评分表后执行（无表=不交易）
   → 条件未满足 → 跳过

10. [仅周三22:00] L18强制做空扫描SOP（不可跳过，0笔也必须写记录）：
    a. 读 watchlist_config.json → us_short_candidates
    b. 查VIX → >25则跳过本周，记录原因
    c. 对每个候选打空头评分卡（10分制，≥7.0双重门槛均满足才执行）
    d. ≥8.5立即执行（裸空或Put）；7.0-8.4优先Put等待；<7.0移除
    e. 写扫描记录到daily-reviews

11. 新建仓（如有需求）：
    → 运行5维度评分（无表=不能交易）：uv run --script scripts/decision_engine.py --dry-run
    → 评分≥20（排除线）→ 完成全部进场检查表 → 执行
    uv run --script scripts/execute_trade.py buy|short --account us --ticker XXX --shares N --reason "..."
    → 执行后立即更新 portfolio_state.json

12. 更新 portfolio_state.json（每笔交易后立即更新，不攒到最后）
```

**本窗口适用规则:** L13/L14/L15/L16/L17/L18 / Regime Detection / 5维度评分 / 美股Bear case（35%门槛）/ 美股ABCD分类（SPY跌≥2.5%=A类）/ 做空4分类 / GAP规则 / 期权SOP

**本窗口专注:** 美股持仓管理、Regime监控、做空配额、新仓评估

---

## W4 — 美股收盘复盘 (04:00 BJT / 16:00 ET)

**账户范围: 美股结算+复盘 | 不执行新交易**

```
1. 记录美股收盘价，更新 portfolio_state.json：
   → 所有美股持仓 current_price = 今日收盘价
   → Integrity check: Σ持仓市值 + 现金 = total_assets（误差<0.5%）

2. 计算今日美股P&L，与SPY对比：
   → 今日alpha = 组合P&L% - SPY P&L%
   → 空头暴露是否仍在目标区间（10-15%，$15K-$22.5K）？
   → 美股现金≥15%（$22,500）？

3. 盘后财报反应处理（当日AMC有财报时）：
   → Beat+guidance上调 → 明日W3建仓/加仓预案写入pending_actions（market=us）
   → Miss → ABCD分类 → D类预案写入pending_actions

4. 止损触发未执行检查：
   → 今日有触发止损未执行？→ 写入pending_actions（URGENT，明日W3优先执行）

5. 5维度研究（30-45分钟）：
   D1: 从watchlist选1只美股候选，完成5维度评分表
   D2: 建立/更新1个做空thesis（us_short_candidates）
   D3: 选1只美股持仓找反面证据（"空头怎么攻击？"）
   D4: 宏观——今日VIX/TNX/DXY数据→判断→对美股持仓含义
   D5: 扫描今日盘后异动（±8%+3x volume），找新机会，更新watchlist_config.json

6. [如是周五] 周度复盘：
   → 本周WR / alpha vs SPY / 规则违反记录（[VIOLATION]标注）
   → Conviction re-ranking（持仓按当前thesis强度重排）
   → 空头持仓占比<10%连续3周 → 分析原因
   → 时间止损检查（T级10天/C级20天/B级30天/A级60天）

7. 检查现金部署进度（strategy Day N时间表）：
   → 现金空转连续3天超阈值 → 强制从watchlist选1只B级以上建仓（写入pending_actions）

8. 写 daily-reviews/YYYY-MM-DD.md（美股部分，含宏观+5维度产出+违规记录）

9. git提交：
   git add portfolio_state.json daily-reviews/ research-notes/
   git commit -m "W4: {YYYY-MM-DD} {HH:MM} | US${NAV} | {trades或no-trade} | {关键发现}"
   git push origin main
```

**本窗口适用规则:** D1-D5全部5维度（美股版）/ 现金部署时间表 / 全美股风控视图 / 周度做空占比检查

**本窗口不执行:** 新交易（美股已收盘）/ 实时价格止损执行（留pending_actions给次日W3）

---

## 速查：脚本命令

```bash
uv run --script scripts/pre_session_check.py --market us   # Pre-Flight（必须第一步）
uv run --script scripts/fetch_prices.py                    # 美股实时价格
uv run --script scripts/risk_monitor.py --no-save          # 风控检查（不写文件）
uv run --script scripts/decision_engine.py --dry-run       # 决策建议（agent自决是否执行）
uv run --script scripts/execute_trade.py buy --account us --ticker NVDA --shares N --reason "..."
uv run --script scripts/execute_trade.py short --account us --ticker MSTR --shares N --reason "..."
uv run --script scripts/execute_trade.py cover --account us --ticker MSTR --shares N --reason "..."
uv run --script scripts/performance.py --no-benchmark      # 绩效
uv run --script scripts/news_scan.py                       # 新闻扫描（D5）
yf macro                                                    # VIX/DXY/TNX速查
yf price NVDA                                              # 单只价格
```

> **来源映射**: Pre-Flight←CLAUDE.md; W3←US_TRADING_SYSTEM_V4.md §10.3+§5.5+L16-L18; W4←US_TRADING_SYSTEM_V4.md §9+§8.4

*版本: 1.0 | 生效: 2026-05-23 | 美股专用。*
