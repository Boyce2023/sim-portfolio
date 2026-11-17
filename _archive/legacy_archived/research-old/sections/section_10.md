## §10 DISCOVERY SYSTEM — 信息茧房对策

> 信息茧房问题: 只扫已知名字→错过ETN/EME/APH/FORM这类机会。成功本身强化茧房: 已持仓赚钱→更多时间看持仓→搜索算法锁定→Pod围墙越来越厚。唯一解法: 用thesis-agnostic的SIGNAL驱动发现，不用thesis驱动发现。

---

### 5 Signal Scanners (每周一 10min，`discovery_scan.py`)

| Scanner | 维度 | 频率 | 脚本 | 输出 |
|---------|------|------|------|------|
| S1 Earnings Surprise | 基本面突变 | 周一 | `discovery_scan.py` | top 20 non-portfolio beats >10% |
| S2 Volume Breakout | 技术面 | 周一 | `discovery_scan.py` | Nokia pattern candidates |
| S3 RS Acceleration | 相对强弱 | 周一 | `discovery_scan.py` | rank improvement top 15 |
| S4 Anti-Sector | 板块盲区 | 周一 | `discovery_scan.py` | 0-exposure sector top 5 |
| S5 New Highs | 价格突破 | 周一 | `discovery_scan.py` | 52W highs excl known names |

---

### Anti-Portfolio Protocol (每周五，`anti_portfolio.py`)

```
全市场 top 50 performers (rolling 4W)
  → 排除: portfolio + watchlist + 30天内看过的名字
  → 剩余 = "茧房外的赢家"

检查:
  3+ 来自同一 sector → 板块盲区，强制S4扫描
  top 5 → 进入 INVESTIGATE queue (当周必看)
```

---

### Signal Aggregation Rules

| Hits (同一标的触发scanners数) | Level | Action | 时间预算 |
|------------------------------|-------|--------|---------|
| 1 | MONITOR | 加入 expanded watchlist | 0 min |
| 2 | INVESTIGATE | 15min deep look | 15 min |
| 3+ | PRIORITY | vs 最弱conviction持仓对比 | 30 min + 4-Gate |

---

### Override Protocol

```
PRIORITY通过4-Gate → 与最弱conviction持仓比较:
  Discovery Grade > Weakest Holding Grade → displacement swap
  同级 → Discovery有近期catalyst → swap; 否则MONITOR

约束:
  每周 ≤1次 Override swap
  执行后写入 daily-review，标注 "Discovery Override"
```

---

### Anti-Cocoon Metrics (每周五 Sizing Reconciliation后检查)

| Metric | Target | Alert阈值 |
|--------|--------|----------|
| Discovery Rate | ≥5 new names/week | <2 连续2周 |
| Pipeline Freshness | ≥30% new in rolling 30d | <15% |
| Sector Coverage | ≥6/11 GICS sectors | <4 sectors |
| Anti-Portfolio Gap | <50% of top 50 unknown | >70% unknown |

**3/4 metrics 触红 → 茧房警报: 暂停持仓分析 1 session，强制跑 anti_portfolio.py + S4 Anti-Sector full scan**

---

### PRIORITY Rejection Protocol

```
每个PRIORITY名字必须二选一:
  A) INVESTIGATE (30min + 4-Gate)
  B) REJECT — 写1句rejection reason到daily-review

合法rejection: "信号为一次性事件(并购/拆分), 非持续趋势"
                "流动性不足(日均成交<$5M)"
                "已在expanded watchlist, 上周已investigate"

非法rejection: "不是我的sector" ← 你的edge是分析方法，不是行业标签
               "没时间" ← Discovery排第一，时间不够砍后面的
               "感觉不熟" ← 不熟才是Discovery的意义
```

---

### Discovery-First Rule

```
Discovery Rate <2 连续3周:
  → 下一session前30min只做discovery，不看持仓
  → 用顺序控制注意力，不用禁令控制行为
```

---

### Integration Rules

- **§8周五例行插入**: Discovery (15min) 排在步骤1 REGIME CHECK **之前**，不可后移，不可省略
- **零发现也要报**: 即使"本周无新名字"也必须跑scanner，在daily-review写 "Discovery: 0 new"
- **月度复盘**: 每月最后一个周五回顾当月所有discovery findings — 哪些MONITOR→转仓位，哪些漏掉了
- **能力圈定义**: edge=分析方法(供应链穿透/催化剂识别/earnings节奏)，不是sector标签。任何sector的PRIORITY都必须investigate或写合法rejection

---

*§10 V6.1 | 2026-05-27 | Discovery System — 信息茧房对策 + PRIORITY Rejection Protocol + Discovery-First Rule*
