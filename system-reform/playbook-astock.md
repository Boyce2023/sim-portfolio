# A股 Session Playbooks
> 版本: v1.0 | 生效: 2026-05-23 | A股专用。

---

## Pre-Flight（每次A股session开始，约30秒，不可跳过）

```
1. uv run --script scripts/pre_session_check.py --market astock
   → exit code 1 = BLOCKED。先读报告修复，本session禁止交易直到PASSED
   → exit code 0 = PASSED，继续下一步

2. 读 pending_actions.json，筛选 market=astock 的条目
   → 标记 URGENT项（deadline=today 或 overdue）
   → URGENT项本session必须处理

3. 确认今日A股是否交易日（查 market_calendar.json）
   → 休市 → 跳过交易步骤，仅可做复盘/研究
```

---

## W1: A股交易日（09:15–15:00 BJT）

```
1. [开盘前] B1市场呼吸扫描（web-access获取沪市成交额）：
   <8000亿 = 低温：不追高，不新建仓，只监控止损
   8000-12000亿 = 正常，按策略执行
   >12000亿 = 过热，不加仓，评估减仓
   TMT占比>45% = 拥挤，不加仓

2. [开盘前] 查A股持仓实时价格：
   uv run --script scripts/fetch_prices.py
   → 当前A股持仓数 ≤ 8只（超过禁止新建仓）

3. [09:30后] 止损监控：对每只持仓核对止损线
   → S级: 跌7%立即执行，不等ABCD分类
   → 其他: ABCD分类完成前禁止任何卖出（60秒分类流程）
   → D类: 48h内清仓，无例外

4. 执行 pending_actions（market=astock的预案）：
   → If-Then条件触发检查 → 条件满足 → 完成进场检查表再执行
   → 条件未满足 → 跳过

5. [可选，仅B1=正常时] 小票先飞信号扫描（web-access）：
   → 同一主题下2+只小票连板 → 找真龙头，完成进场检查表后建仓
   → 新建仓：单日 ≤ 3只（含新开，加仓不计）

6. [13:00-14:30] 止损复查：
   → 今日组合亏损>2.5%？→ 暂停当日剩余新建仓
   → 未执行的止损 → 当日盘中执行，不留到明日

7. [有交易时] 更新 portfolio_state.json
```

**本窗口适用**: L1仓位上限 / L2 thesis先行 / L5下跌先分类 / L7实时价格 / L10-L15铁律 / B1市场呼吸 / ABCD分类 / Bear case 4-tier / T+1约束

**本窗口专注**: A股持仓管理、新仓评估、止损监控

---

## W2: A股收盘后复盘（16:00 BJT）

```
1. 记录A股收盘价，更新 portfolio_state.json：
   → 所有A股持仓 current_price = 今日收盘价
   → 完整性: Σ持仓市值 + 现金 = total_assets（误差<0.5%）

2. 计算今日A股P&L，与沪深300对比：
   → A股 alpha = 组合P&L% - 沪深300P&L%
   → 现金比例 ≥ 15%？（加仓后须 ≥ 20%，违反→标记待处理）

3. 止损遗留检查：今日是否有触发止损未执行？
   → 有 → 写入 pending_actions（明日W1优先执行）

4. 5维度研究（约30分钟）：
   D1: 从 watchlist_config 选1只A股候选，完成97分制评分
   D3: 选1只现有持仓找反面证据（"对手方怎么攻击这个thesis？"）
   D4: 今日宏观数据 → 判断 → 对A股持仓含义
   D5: 扫描今日涨停板，识别小票先飞信号

5. 更新 catalyst_calendar：已过期事件标为 completed/expired

6. [如是周五] 周度检查：
   → 周度亏损>5%？→ 下周前3日禁止新建仓
   → 周度亏损>8%？→ 全仓review，写降级决策

7. 写 daily-reviews/YYYY-MM-DD.md（A股部分）

8. git commit + push
```

**本窗口专注**: 收盘复盘、持仓研究、次日计划（收盘后无法交易）

---

> **来源**: Pre-Flight←CLAUDE.md | W1←strategy.md §3.4.5+§0+§1 | W2←strategy.md §3.6 W2+§3.7
