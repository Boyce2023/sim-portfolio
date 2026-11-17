# Backtesting框架调研 + Nexus集成设计
> 生成时间: 2026-05-21 | 环境: Mac Intel x86_64, macOS 15.7.4 (Sequoia), Python 3.13.12
> 目标: 为Nexus模拟盘选择最合适的日线级回测框架

---

## 1. 框架对比表（1=最差 / 5=最好）

| 维度 | 权重 | VectorBT | Backtrader | backtesting.py | zipline-reloaded | NautilusTrader | LEAN |
|------|------|----------|------------|----------------|------------------|----------------|------|
| Python兼容性/易用性 | 高 | 4 | 4 | 5 | 3 | 3 | 2 |
| Walk-forward validation | 高 | 5 | 3 | 2 | 3 | 4 | 3 |
| 滑点/手续费建模 | 高 | 4 | 5 | 3 | 4 | 5 | 5 |
| 多市场支持(US+A股) | 高 | 4 | 4 | 3 | 2 | 4 | 4 |
| Mac Intel安装复杂度 | 中 | 4 | 5 | 5 | 2 | 3 | 1 |
| 社区活跃度 | 中 | 4 | 3 | 4 | 2 | 5 | 4 |
| 现有sim-portfolio集成 | 高 | 4 | 4 | 5 | 3 | 3 | 2 |
| 实时数据(yfinance) | 中 | 5 | 4 | 4 | 2 | 3 | 2 |
| **加权总分** | — | **4.2** | **3.9** | **3.8** | **2.4** | **3.5** | **2.6** |

### 框架关键参数对照

| 指标 | VectorBT | Backtrader | backtesting.py | zipline-reloaded | NautilusTrader | LEAN |
|------|----------|------------|----------------|------------------|----------------|------|
| 最新版本 | 1.0.0 (2026-04) | 1.9.78.123 (2024-08) | 0.6.5 (2025-12) | 3.1.1 (2026-01) | 1.227.0 (2026-05-20) | C# core |
| GitHub Stars | 7,631 | 21,619 | 8,388 | 1,770 | 22,847 | 19,056 |
| 最后活跃 | 2026-04-25 | 2024-08-19★停滞 | 2025-12-20 | 2026-01-06 | 2026-05-20✓ | 2026-05-20✓ |
| Python版本要求 | ≥3.10 | 无限制 | ≥3.9 | ≥3.10 | 3.12-3.14 | N/A |
| Python 3.13兼容 | ✓ | ✓(老旧) | ✓ | 待验证 | ✓ | 需.NET |
| Mac Intel x86_64 | ✓ | ✓ | ✓ | 部分依赖有问题 | ✓(Rust编译) | 需Docker |
| A股数据支持 | 手动接入 | 手动接入 | 手动接入 | Bundle限制 | 手动接入 | 手动接入 |
| 核心语言 | Python+Numba | Python | Python | Python | Python+Rust | C# |
| Walk-forward原生支持 | ✓(内置) | 需手写 | 无 | 有限 | ✓ | ✓ |
| 向量化回测速度 | 极快(ms级) | 慢(事件循环) | 中等 | 中等 | 快 | 快 |

---

## 2. 推荐方案

### 第一选择：VectorBT

**理由（5条，不对冲）**：

1. **Walk-forward原生支持**：内置`Portfolio.from_signals()`可一行跑rolling window回测，不用手写滑窗逻辑，直接满足核心需求
2. **yfinance深度集成**：`vbt.YFData.pull('NVDA', start='2023-01-01')`一行拉数据，现有`fetch_prices.py`的yfinance调用可直接复用
3. **A股友好**：接受任意pandas DataFrame，AKShare/yfinance拉的A股数据格式直接兼容，不像zipline需要bundle ingestion
4. **trade_log导入简单**：portfolio_state.json里的14条交易记录可直接转成`vbt.Portfolio.from_orders()`的输入格式（timestamp+ticker+shares+price）
5. **安装零障碍**：`pip install vectorbt`，无C++/Rust编译，Mac Intel无兼容问题，Python 3.13 ✓

**弱点**（不掩盖）：
- 复杂信号逻辑（bear case检查、动态止损更新）需要用pandas向量化思维重写，比Backtrader的事件驱动更难表达
- 面向"信号矩阵"设计，单笔定制逻辑（如"NVDA财报日特殊规则"）实现不如Backtrader直观

### 备选：backtesting.py

**适用场景**：单只股票策略原型、规则简单时。API极简，10行代码出结果。

**不选它当主选的原因**：无原生walk-forward、多标的组合管理弱（本质是单资产框架）、A股多市场组合需大量胶水代码。

### 排除说明

| 框架 | 排除原因 |
|------|---------|
| zipline-reloaded | bundle数据摄入对A股不友好；依赖旧版bcolz在Mac Intel Python 3.13有编译问题；社区最不活跃(1,770 stars) |
| NautilusTrader | 定位HFT/L2订单薄，日线策略用纳秒精度是过度工程；Rust编译在Mac Intel可能耗时30+分钟 |
| LEAN | C#核心，Python只是API层；本地运行需Docker；与现有Python脚本生态完全割裂 |
| Backtrader | 主库已2024-08停止维护（1年无提交）；Python 3.12+有若干已知兼容问题；事件循环速度慢 |

---

## 3. 集成架构设计（ASCII）

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Nexus模拟盘回测系统 v1.0                          │
│                   (日线级 | US+A股双市场)                            │
└─────────────────────────────────────────────────────────────────────┘

━━━━━━━━━━━━━━━━━━━━━ 数据层 (Data Layer) ━━━━━━━━━━━━━━━━━━━━━

  ┌─────────────────────┐     ┌─────────────────────┐
  │   美股数据源         │     │   A股数据源           │
  │  yfinance           │     │  AKShare / yfinance  │
  │  fetch_prices.py    │     │  (ticker.SS/.SZ)     │
  └──────────┬──────────┘     └──────────┬──────────┘
             │                           │
             └──────────┬────────────────┘
                        ▼
            ┌───────────────────────┐
            │  data_loader.py       │
            │  标准化OHLCV格式      │
            │  MultiIndex: (date,   │
            │    ticker) × column   │
            └───────────┬───────────┘
                        │
━━━━━━━━━━━━━━ 规则引擎 (Strategy Layer) ━━━━━━━━━━━━━━━━━━━━

                        ▼
            ┌───────────────────────────────────────┐
            │  nexus_strategy.py                    │
            │  读取 strategy.md 规则转化为信号矩阵  │
            │                                       │
            │  Rule 1: bear_case > 20% → no entry   │
            │  Rule 2: position_pct > 15% → trim    │
            │  Rule 3: stop_loss触发 → sell         │
            │  Rule 4: catalyst_date → eval         │
            │  Rule 5: T+1约束(A股买入次日才可卖)   │
            │  Rule 6: A股只做多 / 美股可做空       │
            └───────────┬───────────────────────────┘
                        │
━━━━━━━━━━━━━━ 回测引擎 (Backtest Engine) ━━━━━━━━━━━━━━━━━━━

                        ▼
            ┌───────────────────────────────────────┐
            │  VectorBT Portfolio Engine            │
            │                                       │
            │  ① 历史验证模式                       │
            │     Portfolio.from_orders(            │
            │       trade_log → orders_df)          │
            │     → 验证实际交易的历史表现           │
            │                                       │
            │  ② Walk-Forward模式                   │
            │     Portfolio.from_signals(           │
            │       signals, freq='1D',             │
            │       slippage=0.001,                 │
            │       fees=0.0003)                    │
            │     → 策略参数优化+过拟合检验          │
            │                                       │
            │  ③ 压力测试模式                       │
            │     Monte Carlo + regime filter       │
            │     → 熊市/波动放大时的策略韧性        │
            └───────────┬───────────────────────────┘
                        │
━━━━━━━━━━━━━━ 输出层 (Output Layer) ━━━━━━━━━━━━━━━━━━━━━━━

                        ▼
        ┌───────────────┴────────────────────────┐
        │                                        │
        ▼                                        ▼
┌──────────────────┐                 ┌────────────────────────┐
│  backtest_       │                 │  Nexus Truth Store     │
│  report.json     │                 │  truth/portfolio/      │
│  (策略指标)      │                 │  backtest-results.json │
│  Sharpe / MaxDD  │                 │                        │
│  Win Rate / CAGR │                 │  信号发送至             │
│  Alpha vs SPY/   │                 │  signals/pending/      │
│  沪深300         │                 │  (如策略需调整)         │
└──────────────────┘                 └────────────────────────┘

━━━━━━━━━━━━━━ 文件映射 (File Integration) ━━━━━━━━━━━━━━━━━━

  portfolio_state.json                     strategy.md
       ├── trade_log[14条]      →       (risk rules)
       ├── positions            →    nexus_strategy.py
       └── performance          →    (信号生成逻辑)
              │
              ▼
     data_loader.py → vbt → backtest_runner.py → report
```

---

## 4. 实施步骤（Phase 1/2/3）

### Phase 1：历史验证（1-2天）
> 目标：把portfolio_state.json里已有的14笔交易跑进VectorBT，生成真实绩效基线

**Step 1.1 安装**
```bash
pip install vectorbt akshare
# 验证
python3 -c "import vectorbt as vbt; print(vbt.__version__)"
```

**Step 1.2 trade_log → VectorBT格式转换**
```python
# scripts/backtest_loader.py
import json, pandas as pd

with open('portfolio_state.json') as f:
    state = json.load(f)

# 美股转换
us_trades = [t for t in state['trade_log'] if t['account'] == 'us']
orders_df = pd.DataFrame([{
    'timestamp': pd.Timestamp(t['timestamp']),
    'ticker':    t['ticker'],
    'size':      t['shares'] if t['action'] == 'buy' else -t['shares'],
    'price':     t['price'],
    'fees':      t['value'] * 0.0001,   # IB佣金近似
    'slippage':  t['price'] * 0.0005,   # 0.05% 滑点
} for t in us_trades])
```

**Step 1.3 拉历史价格 + 跑回测**
```python
import vectorbt as vbt

tickers = ['NVDA', 'AAPL', 'GOOGL', 'ADBE', 'GEV', 'LEU', 'FPS']
data = vbt.YFData.pull(tickers, start='2026-05-18', end='2026-05-21')
pf = vbt.Portfolio.from_orders(data.get('Close'), orders_df)
print(pf.stats())  # Sharpe / MaxDD / Total Return
```

**交付物**：`scripts/backtest_phase1.py` + 控制台输出基线指标

---

### Phase 2：策略规则化 + Walk-Forward（3-5天）
> 目标：把strategy.md的if-then规则转成VectorBT信号，跑2023-2026历史验证

**Step 2.1 策略信号矩阵**
```python
# scripts/nexus_strategy.py
def generate_signals(prices_df, bear_cases: dict, stop_losses: dict):
    """
    prices_df: MultiIndex (date, ticker) OHLCV
    bear_cases: {'NVDA': 0.15, 'GOOGL': 0.18, ...}
    stop_losses: {'NVDA': 198.0, ...}
    
    Returns: entries (bool matrix), exits (bool matrix)
    """
    # Rule 1: bear_case > 20% → 不入场
    valid_tickers = [t for t, bc in bear_cases.items() if bc <= 0.20]
    
    # Rule 2: 止损 → 退出信号
    # Rule 3: T+1 (A股shift退出信号1日)
    # Rule 4: 仓位上限15% → trim信号
    ...
```

**Step 2.2 Walk-Forward参数验证**
```python
# 滑动窗口: 6个月训练 → 1个月测试，步进1个月
windows = vbt.split_into_ranges(
    n=24,           # 24个月历史
    train_period=6, # 6个月训练窗口
    test_period=1,  # 1个月测试
)
wf_results = vbt.Portfolio.from_signals(
    close, entries, exits,
    split_by=windows,
    fees=0.0003,     # A股: 印花税+佣金约0.03%单边
    slippage=0.001,
)
wf_results.plot_cum_returns()  # 检查过拟合
```

**Step 2.3 A股双市场集成**
```python
import akshare as ak

# A股日线 OHLCV → 标准化
def fetch_a_share(ticker: str, start: str, end: str) -> pd.DataFrame:
    df = ak.stock_zh_a_hist(symbol=ticker, period="daily",
                             start_date=start, end_date=end,
                             adjust="qfq")  # 前复权
    df = df.rename(columns={'日期':'date','开盘':'Open','收盘':'Close',
                             '最高':'High','最低':'Low','成交量':'Volume'})
    df['date'] = pd.to_datetime(df['date'])
    return df.set_index('date')
```

**交付物**：
- `scripts/nexus_strategy.py` — 规则转信号
- `scripts/backtest_runner.py` — 主入口（历史验证 + walk-forward）
- `reports/strategy_backtest_YYYYMMDD.json` — 指标JSON

---

### Phase 3：Nexus自动化集成（2-3天）
> 目标：每周自动跑回测，策略参数异常时发Nexus信号

**Step 3.1 Truth Store写入**
```python
# 回测结果写入 truth/portfolio/backtest-results.json
result = {
    "generated_at": datetime.now().isoformat(),
    "source": "vectorbt walk-forward",
    "confidence": "medium",  # 回测结果天然中等置信
    "verified": True,
    "us_portfolio": {
        "sharpe":       pf.sharpe_ratio(),
        "max_drawdown": pf.max_drawdown(),
        "cagr":         pf.annualized_return(),
        "alpha_vs_spy": pf.alpha(benchmark_returns=spy_returns),
        "win_rate":     pf.win_rate(),
    },
    "a_share_portfolio": { ... },
    "walk_forward_stability": wf_consistency_score,
}
```

**Step 3.2 策略劣化触发Nexus信号**
```python
# 如果最新1个月walk-forward表现 < 历史均值 - 1.5σ
if latest_sharpe < historical_mean - 1.5 * historical_std:
    signal = {
        "from": "trading",
        "to": ["trading", "research"],
        "priority": "high",
        "type": "strategy_degradation",
        "message": f"Walk-forward Sharpe {latest_sharpe:.2f} 低于历史均值，策略需重新校准",
        "action_required": "review_strategy_rules",
    }
    # 写入 signals/pending/
```

**Step 3.3 launchd定时任务（每周日23:00）**
```bash
# 追加到现有 scripts/daily_run.sh 或新建 scripts/weekly_backtest.sh
#!/bin/bash
cd /Users/huaichuaibeimeng/claude-projects/sim-portfolio
uv run --script scripts/backtest_runner.py --mode walk-forward --write-nexus
git add reports/ truth/portfolio/backtest-results.json
git commit -m "backtest: $(date +%Y-%m-%d) walk-forward results"
```

**交付物**：
- `scripts/backtest_runner.py` 完整版（含Nexus信号写入）
- `truth/portfolio/backtest-results.json` schema
- launchd plist配置

---

## 5. 预计工作量评估

| Phase | 任务 | 工时 | 难点 |
|-------|------|------|------|
| Phase 1 | 安装 + trade_log导入 + 基线跑通 | 3-4小时 | FPS/SRUUF等小市值ticker yfinance可能缺数据 |
| Phase 2.1 | 策略规则 → 信号矩阵 | 6-8小时 | T+1约束、A股涨跌停、仓位上限的向量化实现 |
| Phase 2.2 | Walk-forward验证 | 2-3小时 | A股历史数据2023-2026 AKShare拉取稳定性 |
| Phase 2.3 | A股双市场集成 | 3-4小时 | AKShare前复权+除权处理、SSE/SZSE市场日历 |
| Phase 3 | Nexus Truth Store集成 | 2-3小时 | 回测结果schema设计、信号触发阈值校准 |
| **合计** | — | **16-22小时** | — |

**关键风险**：
1. **FPS/SRUUF历史数据**：IPO新股 + OTC品种，yfinance历史深度有限 → Phase 1只验证有足够历史的标的（NVDA/AAPL/GOOGL/ADBE）
2. **VectorBT多货币组合**：CNY + USD需要汇率处理，Phase 1先独立跑A股和美股，Phase 3再合并
3. **策略规则向量化**：bear_case>20%硬规则是per-stock配置，不是时序信号，需要在entry_signal层面mask掉，非向量化操作

---

## 6. 最优文件结构

```
sim-portfolio/
├── scripts/
│   ├── backtest_loader.py    # NEW: trade_log → VectorBT orders格式
│   ├── nexus_strategy.py     # NEW: strategy.md规则 → 信号矩阵
│   ├── backtest_runner.py    # NEW: 主入口(历史验证/walk-forward/压力测试)
│   └── ... (现有脚本不动)
├── reports/
│   └── backtest_YYYYMMDD.json  # NEW: 每次回测结果存档
└── truth/portfolio/             # (从Nexus truth store引用)
    └── backtest-results.json   # NEW: 最新回测指标供其他workstream引用
```

---

## 附：A股手续费建模参数

| 费用类型 | 数值 | 说明 |
|---------|------|------|
| 印花税 | 0.10% (卖出单边) | 2023年起降至0.05%，这里保守用0.10% |
| 佣金 | 0.03% (双边) | 中金/华泰等主流券商 |
| 过户费 | 0.002% (上交所买卖) | 深交所免 |
| 滑点 | 0.05-0.10% | A股日均成交额大，主板核心标的取0.05% |
| **总摩擦成本(单次往返)** | **~0.23%** | — |

## 附：美股手续费建模参数

| 费用类型 | 数值 | 说明 |
|---------|------|------|
| IB佣金 | $0.005/股 or min $1 | Interactive Brokers Tiered |
| SEC费 | $0.000008×成交额 | 卖出单边 |
| 滑点 | 0.03-0.05% | 大盘流动性股票 |
| **总摩擦成本(单次往返)** | **~0.10-0.15%** | 相对A股低一半 |
