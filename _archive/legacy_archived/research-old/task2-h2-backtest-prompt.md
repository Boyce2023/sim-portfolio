# Task 2: H2回测 — 优化后执行Prompt

> 覆盖期间: 2025-11-22 → 2026-05-21 (约126个交易日)
> 基于H1回测经验优化: JSON格式统一、PnL字段标准化、agent数量与日期分配优化
> 用法: 手动执行，直接复制下方prompt给Claude

---

## 执行Prompt（完整版，直接使用）

你是美股回测引擎。执行H2半年回测（2025-11-22 → 2026-05-21）。

### 方法论（不可违反）

**核心规则：No-Cheat Backtest**
1. 每个agent负责一个时间窗口（约8-10个交易日）
2. 对每个交易日：先搜索**当天**的新闻/催化剂（WebSearch限定日期），基于当天信息做出L/S/Pass判断
3. 不使用未来信息。判断必须基于当天可获得的信息
4. 判断完成后，用yfinance获取**20个交易日后**的实际价格计算PnL
5. 每笔trade记录完整的进场理由、催化剂、退出结果

### ★★★ JSON格式规范（H1最大教训：格式不统一导致无法聚合）

**所有agent必须严格使用以下schema，不允许任何变体：**

```json
{
  "agent_id": 1,
  "period": "2025-11-22 to 2025-12-05",
  "trading_days_covered": 10,
  "market_context": "本时段宏观背景概述（200字以内）",
  "trades": [
    {
      "date": "2025-11-22",
      "ticker": "NVDA",
      "direction": "LONG",
      "thesis": "一句话核心逻辑",
      "catalyst": "具体催化剂+日期",
      "entry_price": 145.00,
      "target": 160.00,
      "stop_loss": 135.00,
      "exit_date": "2025-12-19",
      "exit_price": 158.50,
      "pnl_pct": 9.3,
      "outcome": "WIN",
      "lesson": "这笔交易的教训（100字以内）"
    }
  ],
  "period_summary": {
    "total_trades": 8,
    "wins": 6,
    "losses": 2,
    "win_rate": 75.0,
    "avg_pnl": 5.2,
    "best_trade": "NVDA +9.3%",
    "worst_trade": "CRM -4.1%",
    "regime_notes": "本时段市场regime判断"
  }
}
```

**字段铁律（违反 = 文件作废重写）：**
- `trades` 必须是顶层数组，不允许嵌套在 `daily_log` / `daily_analysis` / `trading_days` 等结构中
- `pnl_pct` 是唯一PnL字段名，不允许 `pnl_t10_pct` / `pnl_t15_pct` / `exit_result.pnl_pct` 等变体
- `direction` 只允许: `"LONG"` / `"SHORT"` / `"LONG (Call)"` / `"SHORT (Put)"`
- `entry_price` 和 `exit_price` 必须是数字（float），不是字符串
- `outcome` 只允许: `"WIN"` / `"LOSS"` / `"FLAT"`
- 每笔trade必须有 `exit_date` + `exit_price` + `pnl_pct`，不允许"待验证"
- `period_summary` 必须包含上述所有字段，数字必须与trades数组一致

### Agent日期分配（15个agent）

| Agent | 日期范围 | 交易日≈ | 关键事件提示 |
|-------|---------|---------|------------|
| 01 | Nov 22 - Dec 5 | 10 | FOMC鹰派余波, 感恩节/黑五, 中美关系 |
| 02 | Dec 8 - Dec 19 | 10 | FOMC 12月会议(12/17-18), CPI, 年末调仓 |
| 03 | Dec 22 - Jan 2 | 7 | 圣诞/新年薄交易, Santa Rally?, 2025总结 |
| 04 | Jan 5 - Jan 16 | 10 | 新年开局, CES 2026, 银行财报季开启 |
| 05 | Jan 19 - Jan 31 | 10 | Trump就职(1/20), 行政令密集期, 关税政策 |
| 06 | Feb 2 - Feb 13 | 10 | DeepSeek冲击?, 科技财报(GOOGL/AMZN/META/AAPL), 非农 |
| 07 | Feb 17 - Feb 28 | 10 | 总统日, NVDA Q4财报, 关税升级? |
| 08 | Mar 3 - Mar 14 | 10 | FOMC 3月会议(3/18-19前瞻), 非农, CPI |
| 09 | Mar 17 - Mar 28 | 10 | FOMC会议, 季末调仓, 关税政策进展 |
| 10 | Mar 31 - Apr 11 | 10 | Q1结束, 关税Liberation Day(4/2)?, 非农 |
| 11 | Apr 14 - Apr 25 | 10 | Q1财报季, 中美贸易谈判?, 复活节 |
| 12 | Apr 28 - May 9 | 10 | 科技大厂Q1财报(AAPL/MSFT/AMZN/META), FOMC 5月? |
| 13 | May 12 - May 21 | 8 | 中美贸易协议?, CPI, 尾声期 |

注意：如果某个时间窗口交易日不足（假期等），agent应如实记录，不需要凑数。每个交易日不必都有trade——**Pass也是决策**。

### 每个Agent的Prompt模板

```
你是H2回测Agent {N}，负责 {日期范围}。

方法论：
1. 对你负责的每个交易日，搜索当天的新闻（WebSearch，限定日期）
2. 基于当天信息判断：做多/做空/观望哪些股票
3. 判断后用yfinance获取20个交易日后的实际收盘价
4. 计算PnL: (exit_price - entry_price) / entry_price × 100（做空反向）
5. entry_price用yfinance获取当天收盘价（不是你搜到的价格）

搜索策略（按优先级）：
- "{date} stock market news" / "{date} US market recap"
- 具体事件搜索：FOMC/CPI/earnings等（如果你知道该日有重大事件）
- 板块搜索：科技/能源/医药/金融等当周热点

交易标的范围（不限于此，但优先关注）：
- 核心科技: NVDA, AAPL, MSFT, GOOGL, AMZN, META, TSLA, AMD
- AI链: AVGO, ARM, SMCI, PLTR, CRM, ADBE, NOW
- 半导体: ASML, TSM, AMAT, KLAC, LRCX
- 消费/零售: AMZN, COST, WMT, NKE, LULU, DG
- 金融: JPM, GS, BAC, WFC, V, MA
- 能源/商品: XOM, CVX, GLD, SLV, USO, UNG
- 加密: COIN, MARA, CLSK, MSTR
- 核能: CEG, VST, SMR, NNE, LEU, CCJ
- ETF: SPY, QQQ, IWM, XLK, XLE, XLF, TLT, TBT, FXI
- 期权: 对高conviction标的可用Call/Put

每笔trade要求：
- thesis必须具体（不是"看好科技"，而是"NVDA Q4指引>$37B因Blackwell ramp"）
- 催化剂必须有日期
- 做空必须有明确的空头thesis（L5-L9参考）
- 每个交易日最多3笔trade（质量>数量）
- 全时段总trade数建议8-15笔（别散弹枪）

H1回测20条核心Lesson（你的交易应避免违反）：
- L1: >15% gap不追，等3-5天
- L2: 地缘事件前入场，不是当天
- L3: 财报前dip buy高conviction名字
- L4: NVDA空头等财报后
- L5: 做空growth decel+高估值SaaS确定性最高
- L6: 结构性空头 >> 催化剂博弈空头
- L7: 高估值AI股财报后8-10天蜜月期结束
- L8: 投机核能 vs 运营核能 pairs trade
- L9: TSLA公开交付数据 = 重复做空edge
- L10: GLD = 降息周期标配
- L11: September effect在Fed pivot年失效
- L12: TSMC财报 = NVDA领先指标
- L13: S&P入选公告日买effective date卖
- L14: 政策链条trade > 个股
- L15: 单笔earnings bet ≤ 8%
- L16: 同方向选beta最高标的
- L17: AI邻接股比核心AI拥挤度低
- L18: $20B+回购 = 持续买盘地板
- L19: Regime shift = 最贵错误，FOMC转向24h内翻转方向
- L20: F15共识反向 ≠ 做空信号

★★★ 输出格式：严格使用以下JSON schema，不允许任何变体 ★★★
{schema如上}

写入文件: sim-portfolio/research-notes/h2/agent-{NN}.json
```

### 执行架构

```
阶段1: 部署15个agent（每个写自己的h2/agent-{NN}.json）
阶段2: 所有agent完成后，聚合写 h2/H2_SUMMARY.md（格式同H1_SUMMARY.md）
```

聚合统计必须包含：
1. Overall: 总trades, WR, avg PnL, profit factor
2. Agent scorecard（每个agent一行）
3. Top 10 Winners / Losers
4. Direction analysis（多空对比）
5. Ticker leaderboard
6. Monthly performance
7. 与H1对比（同期不同regime的表现差异）
8. 20条H2-specific lessons

### 与H1的关键差异

| 维度 | H1 (May-Nov 2025) | H2 (Nov 2025-May 2026) |
|------|-------------------|------------------------|
| 美联储 | 从加息尾声→首次降息 | 降息周期→可能暂停 |
| 政治 | Biden→选举季 | Trump就职+行政令+关税 |
| AI | NVDA Blackwell预期期 | Blackwell交付+DeepSeek冲击 |
| 市场 | 震荡上行+局部回调 | 关税冲击+V型反弹? |
| 地缘 | 以色列-伊朗 | 中美贸易战2.0 |

H2的核心看点：**关税政策的市场传导**是H1没有的新维度。Agent需要特别关注关税对不同板块的差异化影响。

---

*执行时直接部署15个agent，每个用上述模板填入对应日期范围。完成后聚合。*
