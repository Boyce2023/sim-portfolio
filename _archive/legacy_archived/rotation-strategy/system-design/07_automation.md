# Track B 自动化系统设计 v1.0

> 编制日期：2026-05-28
> 适用策略：ROTATION_STRATEGY_V1.md + system-design/01_rating.md
> 上位系统：sim-portfolio Track A（daily_run.sh / trading_engine.py / decision_engine.py）
> Claude分析意见，非用户投资结论。

---

## §0 设计原则

### 0.1 两条核心约束

1. **Track B不自动执行买入**。daily_run.sh可自动执行Track A的critical止损，但Track B买入信号必须写入`pending_orders`等用户确认——轮动时机窗口窄（分钟级），但错误风险高（断板信号必须人工判断）。
2. **Track B系统是Track A系统的插件，不是替代**。所有文件（portfolio_state.json / trade_log / daily-reviews）复用已有格式，只增加必要字段，不另起数据孤岛。

### 0.2 设计边界

| 操作 | 自动化级别 | 说明 |
|------|-----------|------|
| 市场环境硬开关检测 | 全自动 | rotation_scan.py检测，结果写rotation_state.json |
| 轮动信号扫描（盘前） | 全自动 | rotation_scan.py每日08:00跑，结果写rotation_signals.json |
| 评级打分（5维） | 半自动 | rotation_engine.py生成打分草稿，用户session中确认 |
| 买入执行 | 手动 | 用户session中调execute_trade.py |
| Track B止损监控（盘中） | 全自动（alert-only） | rotation_monitor.py检测龙头跌>5%/断板，写alert到pending_actions.json |
| Track B critical止损 | 半自动 | 龙头跌>5%时写critical信号，daily_run.sh的Step 4b自动执行全清 |
| 持仓天数超限 | 全自动 | trading_engine.py每日检查，超限写critical卖出信号 |
| session状态传递 | 全自动 | rotation_state.json每次扫描后原子更新 |

---

## §1 新脚本清单

### 1.1 `scripts/rotation_scan.py` — 每日轮动信号扫描

**对应**：Discovery System（每日盘前主线识别）

**触发时机**：daily_run.sh Step 2（fetch_prices后，decision_engine前）

**功能（伪代码）**：
```python
"""
rotation_scan.py — Track B每日主线扫描
用法: uv run --script scripts/rotation_scan.py [--date YYYY-MM-DD] [--dry-run]

流程:
  1. 读取 rotation_state.json（上次主线状态）
  2. 从 latest_news.json 提取板块热点关键词（news_collector已采集）
  3. 硬开关检查（§1.4 ROTATION_STRATEGY_V1.md）:
       a. 从latest_prices.json读沪深300 20日收益率
       b. 读rotation_state.json中的market_breath字段（F20每周一人工更新）
       c. 检查涨停家数/成交额（从latest_prices.json）
       触发任一 → 写 rotation_state.json.market_switch = "CLOSED" → 输出HALT信号
  4. 主线持续性检查:
       a. 如果rotation_state.json有active_theme，检查:
          - 龙头昨日涨跌（latest_prices.json）
          - 持仓天数是否超类型上限
          - 炸板率代理指标（板块涨停家数变化）
       b. 输出：HOLD / WATCH / EXIT三种信号
  5. 新主线扫描（仅市场处于OPEN状态时）:
       a. 从latest_news.json筛选"产业催化"关键词（BOM/订单/季报等T2特征）
       b. 生成候选主线列表（板块名 + 驱动事件 + 初步类型判断T1-T5）
       c. 不做5维打分（信号缺失太多），只输出候选供session确认
  6. 写 rotation_signals.json（结果文件）
  7. stdout打印摘要（供remote agent读取）
"""

INPUT_FILES = [
    "latest_news.json",        # news_collector.py已生成
    "latest_prices.json",      # fetch_prices.py已生成
    "rotation_state.json",     # Track B状态（本脚本维护）
    "market_calendar.json",    # 休市日历
]
OUTPUT_FILES = [
    "rotation_signals.json",   # 本次扫描结果
    "rotation_state.json",     # 更新market_switch/持续性信号
]
```

**关键逻辑：硬开关检测**：
```python
def check_hard_switch(state: dict, prices: dict, news: dict) -> str:
    """返回 'OPEN' / 'CLOSED' / 'EMERGENCY_CLOSE'"""
    # 条件1: 沪深300 20日收益率 < -8%
    hs300_20d_return = prices.get("hs300_20d_return", 0)
    if hs300_20d_return < -0.08:
        return "CLOSED"
    # 条件2: 全市场成交额 < 1.5万亿连续5日
    vol_streak = state.get("low_volume_streak", 0)
    if prices.get("market_volume_bn", 99) < 15000 :  # 亿
        vol_streak += 1
    if vol_streak >= 5:
        return "CLOSED"
    # 条件3: F20判定呼气期（每周一人工写入）
    if state.get("market_breath") == "exhale":
        return "CLOSED"
    # 条件4: 涨停家数连续5日 < 30家
    if state.get("limit_up_low_streak", 0) >= 5:
        return "CLOSED"
    # 紧急关闭：当日跌停 > 50家（V1.2）
    if prices.get("limit_down_count", 0) > 50:
        return "EMERGENCY_CLOSE"
    # 48小时内涨停降幅 > 40%（V1.2）
    yesterday_limit_up = state.get("yesterday_limit_up_count", 999)
    today_limit_up = prices.get("limit_up_count", 999)
    if yesterday_limit_up > 0 and (today_limit_up / yesterday_limit_up) < 0.60:
        return "EMERGENCY_CLOSE"
    return "OPEN"
```

---

### 1.2 `scripts/rotation_engine.py` — 轮动交易决策引擎

**对应**：decision_engine.py的Track B版本

**触发时机**：session中手动调用（不在daily_run.sh中，因为需要人工判断）

**功能（伪代码）**：
```python
"""
rotation_engine.py — Track B评级引擎 + pending_orders生成
用法: uv run --script scripts/rotation_engine.py [--ticker 600938] [--dry-run]
      uv run --script scripts/rotation_engine.py --review-holdings  # 检查所有Track B持仓

功能:
  1. 读取 rotation_signals.json（扫描结果）
  2. 对指定标的执行5维打分（01_rating.md §1）:
       D1: 入场信号等级（需用户输入：S/A/B/C）
       D2: 轮动类型（需用户输入：T1-T5）
       D3: 传导位置（从sector推断L1-L6，可覆盖）
       D4: 时间位置（从market_context推断，需确认）
       D5: 流动性（从latest_prices.json自动计算）
  3. 一票否决检查（§2.2 01_rating.md）
  4. 强制降档检查
  5. 计算总分 → 等级（B+/B/B-/C）
  6. 计算建仓股数（等级上限 × NAV / 当前价格）
  7. 生成 pending_order（等待用户确认）
  8. --review-holdings: 检查所有Track B持仓的升降级条件
"""

# 5维打分 — D5流动性可自动计算，其他需输入或从rotation_signals推断
def score_d5_liquidity(ticker: str, prices: dict) -> int:
    market_cap = prices.get(f"{ticker}_market_cap_bn", 0)  # 亿
    avg_volume_5d = prices.get(f"{ticker}_avg_vol_5d_bn", 0)
    today_volume = prices.get(f"{ticker}_volume_bn", 0)

    # 市值分层
    if market_cap < 15:  # 超小北交所
        return 0
    elif ticker.startswith("8"):  # 北交所（43/82/83/87/88开头）
        if market_cap >= 30 and avg_volume_5d >= 0.2:
            return 8
        elif market_cap >= 15:
            return 4
    elif market_cap < 100:
        base = 10 if avg_volume_5d >= 2 else 4
    else:
        base = 10 if avg_volume_5d >= 5 else 4

    # 流动性萎缩惩罚
    if today_volume < avg_volume_5d * 0.5:
        base -= 5
    return max(0, base)

# 生成pending_order（Track B格式）
def make_pending_order(ticker, action, shares, rating, reason, theme_id) -> dict:
    return {
        "ticker": ticker,
        "action": action,   # "buy" / "sell"
        "shares": shares,
        "account": "a_share",
        "track": "B",           # ★ Track B标记
        "tb_rating": rating,    # "B+" / "B" / "B-"
        "tb_theme_id": theme_id,  # 对应rotation_state中的theme_id
        "reason": reason,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": None,  # Track B买单当日有效（开盘前生成，收盘前过期）
        "status": "pending",
    }
```

---

### 1.3 `scripts/rotation_monitor.py` — 盘中实时监控

**对应**：trading_engine.py的盘中轮动版本

**触发时机**：
- W1盘中（09:30-15:00）可手动触发，或由launchd每30分钟触发
- 仅在daily_run.sh之外的专用launchd任务（trading_session.plist）中运行

**功能（伪代码）**：
```python
"""
rotation_monitor.py — Track B盘中实时状态检测
用法: uv run --script scripts/rotation_monitor.py [--quick] [--save]
      --quick: 只检查critical信号（省context），不生成报告
      --save: 写入 pending_actions.json（默认只stdout）

功能:
  1. 读取 rotation_state.json（当前主线+龙头）
  2. 用 yfinance 拉取龙头（dragon_head_ticker）当日价格
  3. 检查6个关键指标（按优先级排序）:
       a. 龙头是否跌>5% → CRITICAL_EXIT（Track B全出铁律）
       b. 龙头是否断板（开板且未重新封板）→ EXIT_SIGNAL
       c. 炸板率是否>50% → REDUCE_SIGNAL（-1档降级）
       d. 持仓天数是否超类型上限 → TIME_EXIT
       e. 退出信号有效期是否到期 → 检查rotation_state.exit_signal_expiry
       f. TMT拥挤度是否>48% → REDUCE_SIGNAL（Track A规则延伸）
  4. 对Track B持仓中的每个标的额外检查:
       a. 标的自身止损（ATR K值×ATR，见01_rating.md §2.1）
       b. 今日成交量 < 历史5日均量50% → LIQUIDITY_WARNING
  5. critical信号写入 pending_actions.json（触发daily_run.sh Step 4b自动止损）
  6. 非critical信号写入 rotation_state.json.intraday_alerts（供session读取）
  7. stdout打印精简报告（--quick模式）
"""

# critical止损信号格式（与Track A decisions.json保持一致）
def make_critical_sell(ticker: str, reason: str, theme_id: str) -> dict:
    return {
        "ticker": ticker,
        "action": "sell",
        "account": "a_share",
        "track": "B",
        "priority": "critical",   # ★ 触发daily_run.sh Step 4b自动执行
        "tb_theme_id": theme_id,
        "reason": f"TRACK_B_EXIT: {reason}",
        "sell_all": True,
    }

# 龙头跌>5% → 所有Track B持仓全出
def handle_dragon_drop(state: dict, portfolio: dict) -> list[dict]:
    tb_positions = [
        p for p in portfolio["accounts"]["a_share"]["positions"]
        if p.get("track") == "B"
    ]
    return [
        make_critical_sell(
            p["ticker"],
            f"龙头{state['dragon_head_ticker']}跌>5%，Track B铁律全出",
            p.get("tb_theme_id", state.get("current_theme_id", "unknown"))
        )
        for p in tb_positions
    ]
```

---

### 1.4 `scripts/rotation_review.py` — 盘后Track B日评

**对应**：trading_engine.py的daily review生成部分

**触发时机**：daily_run.sh Step 3（trading_engine后，decision_engine前）

**功能（伪代码）**：
```python
"""
rotation_review.py — Track B盘后日评生成
用法: uv run --script scripts/rotation_review.py [--date YYYY-MM-DD]

功能:
  1. 读取 rotation_state.json + portfolio_state.json（Track B持仓）
  2. 计算每个Track B持仓的当日P&L
  3. 检查升降级条件（01_rating.md §4）
  4. 生成持仓天数警告（超类型上限-2天时黄色预警）
  5. 追加写入 daily-reviews/YYYY-MM-DD.md 的 "Track B" 小节
  6. 更新 rotation_state.json（持仓天数/主线状态/升降级结果）
  7. 更新 tb_pain_memory.md / tb_victory_memory.md（止损/盈利出场后）
"""
```

---

### 1.5 辅助：不需要新脚本的功能

以下功能通过**改造现有脚本**实现（见§7），不新建脚本：

| 功能 | 现有脚本 | 改造方式 |
|------|---------|---------|
| Track B持仓价格更新 | `update_prices.py` | 自动处理（不区分track） |
| Track B止损自动执行 | `daily_run.sh Step 4b` | 读decisions.json中priority=critical且track=B的信号 |
| Track B交易记录 | `execute_trade.py` | 增加`--track B`参数 |
| Track B conviction check | `conviction_check.py` | 增加`--track B`过滤 |

---

## §2 数据文件设计

### 2.1 `rotation_state.json` — Track B核心状态文件

**位置**：`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/rotation_state.json`

**更新协议**：
- rotation_scan.py（每日08:00，原子写入）
- rotation_engine.py（session中，用户确认后写入）
- rotation_review.py（每日盘后，追加写入）
- rotation_monitor.py（盘中，仅写intraday_alerts字段）

**Schema**：
```json
{
  "_meta": {
    "version": "1.0",
    "purpose": "Track B轮动状态。rotation_scan.py维护，session中可覆盖。",
    "last_updated": "2026-05-28T08:00:00+08:00",
    "last_updated_by": "rotation_scan"
  },

  "market_switch": "OPEN",
  // OPEN / CLOSED / EMERGENCY_CLOSE
  // CLOSED触发条件见ROTATION_STRATEGY_V1.md §1.4

  "market_breath": "inhale",
  // "inhale" / "neutral" / "exhale"
  // 每周一人工更新（F20，不自动推断）
  // rotation_scan.py读此字段，不写此字段

  "market_context": {
    "limit_up_count": 72,        // 今日涨停家数（rotation_scan从prices读取）
    "limit_down_count": 3,       // 今日跌停家数
    "limit_up_yesterday": 68,    // 昨日涨停家数（48h降幅计算用）
    "market_volume_bn": 18500,   // 全市场成交额（亿）
    "hs300_20d_return": 0.032,   // 沪深300 20日收益率
    "low_volume_streak": 0,      // 连续低成交额天数（<1.5万亿）
    "limit_up_low_streak": 0,    // 连续涨停<30家天数
    "as_of_date": "2026-05-28"
  },

  "active_themes": [
    // 可有0-2条活跃主线
    {
      "theme_id": "TB-20260528-AI-PCB",
      // 格式: TB-{YYYYMMDD}-{行业缩写}-{核心驱动}
      "theme_name": "AI算力PCB轮动",
      "rotation_type": "T2",       // T1/T2/T3/T4/T5
      "dragon_head_ticker": "002586",
      "dragon_head_name": "天富能源",
      // 此主线的龙头（不是持仓标的，是整个板块的风向标）
      "trigger_event": "Rubin BOM拆解，PCB价值量+13.3%",
      "trigger_date": "2026-05-22",
      "current_phase": "主升期早",
      // 启动期/主升期早/主升期中晚/高潮分歧期/退潮期
      "days_since_trigger": 6,
      "max_holding_days": 45,      // 对应轮动类型的上限（§2.3 ROTATION_STRATEGY_V1）
      "l_layer": "L2",             // 当前主要持仓所在传导层
      "exit_signal_active": false,
      "exit_signal_expiry": null,  // 退出信号有效期（ISO8601，48h内有效）
      "crowding_pct": 0.22,        // 板块拥挤度（0-1）
      "intraday_alerts": [],       // rotation_monitor.py盘中写入，session读取后清空
      "last_scan_rating": {
        "d1_signal": 22,  "d2_type": 25, "d3_position": 16,
        "d4_timing": 12,  "d5_liquidity": 10,
        "total": 85,      "grade": "B+"
      }
    }
  ],

  "watch_pool": [
    // C级观察池（不占名额，不影响仓位）
    {
      "theme_id": "TB-20260528-WATCH-超级电容",
      "theme_name": "超级电容独立主线",
      "rotation_type": "T2",
      "trigger_reason": "新能源+储能双催化，L6已成独立主线",
      "watch_since": "2026-05-28",
      "promote_condition": "L6连续2-3天+独立产业催化验证",
      "current_score": 40,
      "grade": "C"
    }
  ],

  "restart_confirmation": {
    // 硬开关关闭后的重启计数（V1.2规则）
    "switch_closed_date": null,
    "reopen_days_met": 0,
    // ≥2日=谨慎重启（半仓）; ≥3日=正常重启
    "catalyst_confirmed": false
  },

  "daily_stats": {
    "date": "2026-05-28",
    "tb_total_pct": 0.18,       // Track B总仓位占比
    "tb_position_count": 2,     // Track B持仓数
    "tb_unrealized_pnl": 12500, // Track B未实现盈亏（CNY）
    "tb_realized_pnl_mtd": 8400 // 本月已实现盈亏
  }
}
```

---

### 2.2 `rotation_signals.json` — 每日扫描结果

**位置**：`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/rotation_signals.json`

**更新频率**：每日一次（rotation_scan.py 08:00覆盖写）

**Schema**：
```json
{
  "_meta": {
    "scan_date": "2026-05-28",
    "scan_time": "2026-05-28T08:05:32+08:00",
    "market_switch": "OPEN",
    "scan_duration_sec": 12.4
  },

  "market_environment": {
    "switch_status": "OPEN",
    "breath": "inhale",
    "limit_up_count": 72,
    "volume_bn": 18500,
    "hard_switch_flags": {
      "hs300_20d_bear": false,
      "low_volume_5d": false,
      "exhale_period": false,
      "limit_up_low_5d": false,
      "emergency_limit_down": false,
      "emergency_48h_drop": false
    }
  },

  "active_theme_updates": [
    // 对现有active_themes的持续性判断
    {
      "theme_id": "TB-20260528-AI-PCB",
      "signal": "HOLD",
      // HOLD / WATCH（注意信号劣化）/ EXIT
      "dragon_head_change_pct": 0.029,
      "days_since_trigger": 6,
      "days_until_limit": 39,
      "notes": "龙头+2.9%，主升期持续，炸板率<30%"
    }
  ],

  "new_candidates": [
    // 新发现的主线候选（未评级，供session判断）
    {
      "candidate_id": "CAND-20260528-001",
      "theme_name": "人形机器人减速器",
      "preliminary_type": "T2",   // 初判，需session确认
      "trigger_summary": "特斯拉减速器订单披露，涉及3家A股供应商",
      "source": "latest_news.json",
      "news_ids": ["news-20260528-045"],
      "preliminary_tickers": ["688011", "300827"],
      "needs_session_review": true,
      "confidence": "low"  // 纯新闻推断，未做5维打分
    }
  ],

  "exit_signals": [
    // 需要处理的退出信号（写入pending_actions.json）
    {
      "theme_id": "TB-20260528-AI-PCB",
      "ticker": "002028",
      "signal_type": "TIME_LIMIT",  // DRAGON_DROP / BOARD_BREAK / TIME_LIMIT / CROWDING
      "priority": "warning",  // critical / warning / info
      "action_required": "减仓至B级（12%）上限",
      "auto_execute": false
    }
  ]
}
```

---

### 2.3 `tb_playbook.json` — Track B赢家模式库

**位置**：`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/tb_playbook.json`

**对标**：`playbook_astock.json`（Track A版本）

**Schema**：
```json
{
  "_meta": {
    "version": "1.0",
    "purpose": "Track B赢家模式库。盈利出场后人工更新。",
    "last_updated": "2026-05-28",
    "total_patterns": 0
  },

  "patterns": [
    {
      "pattern_id": "TB-PAT-001",
      "name": "T2产业催化L2早期入场",
      "description": "BOM拆解当日，L2（PCB/覆铜板）主升期早，A级信号，分2批建至B+（15%）",
      "rotation_type": "T2",
      "l_layer": "L2",
      "phase_at_entry": "主升期早",
      "signal_grade": "A",
      "entry_grade": "B+",
      "avg_hold_days": 8,
      "avg_return_pct": 0.187,
      "win_rate": 0.75,
      "sample_trades": ["胜宏科技 2026-05-22"],
      "entry_conditions": [
        "BOM拆解当日或T+1",
        "龙头首板或连板",
        "涨停≥60家",
        "炸板率<30%"
      ],
      "exit_conditions": [
        "龙头断板",
        "炸板率>50%",
        "持仓≥D+8无新催化"
      ],
      "conviction_boost": true,
      // 匹配此模式时，建仓信心+1档（最多+1档）
      "created_at": "2026-05-28",
      "trade_count": 1
    }
  ],

  "anti_patterns": [
    {
      "pattern_id": "TB-ANTI-001",
      "name": "L6首板追入（主线末端陷阱）",
      "description": "主线已高位，L6首次出现，追入后第2-3天炸板",
      "lesson": "L6首次出现=退出信号，不是入场信号",
      "rule_ref": "01_rating.md §1.3维度三",
      "sample_trades": [],
      "created_at": "2026-05-28"
    }
  ]
}
```

---

### 2.4 `tb_pain_memory.md` — Track B止损复盘

**位置**：`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/tb_pain_memory.md`

**对标**：`pain_memory.md`（Track A版本）

**模板**：
```markdown
# Track B Pain Memory（最近10条）

---

## [TB-PAIN-001] {标的} {日期} | {主线} | 亏损: -{X}%

**入场**：{YYYY-MM-DD} | 评级{B+/B/B-} | 仓位{X}%
**出场**：{YYYY-MM-DD} | 原因：{龙头断板/炸板>50%/超期/主动止损}
**主线类型**：{T1/T2/T3/T4/T5} | 传导层：{L1-L6} | 入场阶段：{xxx期}
**龙头状态**：{出场当日龙头价格变化}

**5维入场评分回顾**：
- D1信号：{实际得分} / 当时判断：{xxx}
- D2类型：{实际得分} / 当时判断：{xxx}
- D3位置：{实际得分} / 当时判断：{xxx}
- D4时间：{实际得分} / 当时判断：{xxx}
- D5流动性：{实际得分} / 当时判断：{xxx}
- 总分：{X}分 → {B+/B/B-}

**哪个维度打错了**：
{具体分析：实际结果证明D4时间打了12分（主升期早），但实际是主升期中晚，应得6分}

**规则执行**：
- 止损铁律（龙头跌>5%当日全出）：[✓ 执行 / ✗ 未执行，原因xxx]
- 持仓天数上限：[入场时预期{X}天，实际持仓{X}天]

**下次改进**：
{一句话，可操作的规则修改}

---
```

---

### 2.5 `tb_victory_memory.md` — Track B盈利出场记录

**位置**：`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/tb_victory_memory.md`

**模板**：
```markdown
# Track B Victory Memory（最近10条）

---

## [TB-VIC-001] {标的} {日期} | {主线} | 盈利: +{X}%

**入场**：{YYYY-MM-DD} | 评级{B+/B/B-} | 仓位{X}%
**出场**：{YYYY-MM-DD} | 持仓：{N}天 | R-Multiple: {X.Xr}
**主线类型**：{T1/T2/T3/T4/T5} | 传导层：{L1-L6}

**出场触发**：{龙头断板/持仓天数到期/用户主动减仓/目标位}

**赢在哪**（对照tb_playbook.json）：
1. 入场时机：{具体判断}
2. 仓位管理：{是否分批建仓，加仓决策}
3. 出场纪律：{是否按预设出场，有无犹豫}

**Playbook匹配**：{TB-PAT-001 / 新模式（更新tb_playbook.json）}

**下次复用条件**：
{一句话，下次遇到什么情况可以用同样的打法}

---
```

---

### 2.6 其他必要文件（小改现有文件）

| 文件 | 改动 | 说明 |
|------|------|------|
| `portfolio_state.json` | 持仓增加`track/tb_theme_id/tb_rating`字段 | 见§4 |
| `pending_actions.json` | 增加`track`字段 | 区分Track A/B的pending action |
| `decisions.json` | sell_signals增加`track`字段 | 区分自动止损来源 |
| `daily-reviews/YYYY-MM-DD.md` | 追加"## Track B"小节 | rotation_review.py写入 |

---

## §3 daily_run.sh 集成方案

### 3.1 完整修改后的流程

```
[现有] Step 1: git pull
[现有] Step 1b: news_collector.py（采集新闻 → latest_news.json）
[现有] Step 1c: catalyst_recognizer.py（催化剂识别）

[现有] Step 2: fetch_prices.py（获取价格 → latest_prices.json）
[现有] Step 2b: update_prices.py（价格写入 portfolio_state.json）

★ [新增] Step 2c: rotation_scan.py（轮动信号扫描 → rotation_signals.json）
   - 必须在 fetch_prices.py 之后（依赖 latest_prices.json）
   - 必须在 decision_engine.py 之前（结果供 decision_engine 参考）
   - 失败处理：非阻断（rotation_state.json已有状态，不影响Track A流程）

[现有] Step 3: trading_engine.py（Track A持仓更新 + daily review）
★ [新增] Step 3b: rotation_review.py（Track B盘后日评 + 状态更新）
   - 必须在 trading_engine.py 之后（依赖已更新的 portfolio_state.json）
   - 必须在 decision_engine.py 之前（更新的状态影响Track B决策建议）

[现有] Step 4: decision_engine.py（Track A决策建议 → decisions.json）
[现有] Step 4b: auto-execute critical sells（执行 decisions.json critical信号）
   ★ 已兼容 Track B（decisions.json中有track=B的critical信号时同样执行）
[现有] Step 4b2: auto-execute pending_orders
   ★ 已兼容 Track B（pending_orders中有track=B的订单时同样执行）
   ★ 但Track B买入订单设expires_at，过期自动跳过（不执行昨天的买单）

[现有] Step 4c: sync_nexus.py

[现有] Step 5: git commit & push
```

### 3.2 具体插入代码

在 daily_run.sh 的 Step 2b 和 Step 3 之间插入：

```bash
# ---------- Step 2c: Track B轮动信号扫描 ----------
if [ -f "${SCRIPTS_DIR}/rotation_scan.py" ]; then
    log "📊 Scanning rotation signals..."
    if "${UV_BIN}" run --script "${SCRIPTS_DIR}/rotation_scan.py" >> "${LOG_FILE}" 2>&1; then
        log "    ✓ rotation_scan.py 成功"
    else
        log "    ⚠ rotation_scan.py 失败（非阻断，Track A流程继续）"
    fi
else
    log ">>> rotation_scan.py 不存在，跳过"
fi
```

在 Step 3（trading_engine.py）之后，Step 4（decision_engine.py）之前插入：

```bash
# ---------- Step 3b: Track B盘后日评 ----------
if [ -f "${SCRIPTS_DIR}/rotation_review.py" ]; then
    run_step "rotation_review.py" \
        "${UV_BIN}" run --script "${SCRIPTS_DIR}/rotation_review.py"
fi
```

### 3.3 pending_orders过期处理（改造Step 4b2）

在Step 4b2的pending_orders处理循环中，增加Track B过期检查：

```python
# Track B买入订单过期检查
if order.get("track") == "B" and order.get("action") == "buy":
    expires_at = order.get("expires_at")
    if expires_at:
        from datetime import datetime, timezone
        exp = datetime.fromisoformat(expires_at)
        if datetime.now(timezone.utc) > exp:
            print(f"Track B买单已过期，跳过: {ticker}")
            continue  # 过期不执行，但从pending_orders中移除
```

### 3.4 失败处理逻辑

| 脚本 | 失败类型 | 处理 |
|------|---------|------|
| `rotation_scan.py` | 价格获取失败 | 保留上次rotation_state.json，标记scan_failed=true，继续 |
| `rotation_scan.py` | rotation_state.json写入失败 | log_err但非阻断，下次session手动修复 |
| `rotation_review.py` | 持仓计算错误 | 标记review_failed=true，不影响Track A的daily review |
| `rotation_monitor.py`（盘中）| yfinance超时 | 重试3次，仍失败→log，不写pending_actions |

---

## §4 与 portfolio_state.json 的集成

### 4.1 Track B持仓字段（在现有positions数组中添加）

Track B持仓在`a_share.positions`数组中，与Track A并列，通过`track`字段区分：

```json
{
  "ticker": "002586",
  "name": "天富能源",
  "sector": "PCB",
  "track": "B",                    // ★ 新增：Track标记
  "tb_theme_id": "TB-20260528-AI-PCB",  // ★ 新增：所属主线
  "tb_rating": "B+",               // ★ 新增：轮动评级
  "tb_rotation_type": "T2",        // ★ 新增：轮动类型
  "tb_l_layer": "L2",              // ★ 新增：传导层
  "tb_entry_phase": "主升期早",     // ★ 新增：入场阶段
  "tb_entry_score": 85,            // ★ 新增：入场总分
  "tb_entry_date": "2026-05-22",   // ★ 新增（tb_专用，entry_date已有但用tb_前缀避免混淆）
  "tb_holding_days": 6,            // ★ 新增：持仓天数（rotation_review.py每日更新）
  "tb_max_holding_days": 45,       // ★ 新增：类型上限
  "tb_dragon_head": "002586",      // ★ 新增：对应龙头（可能是自身或板块龙头）
  "tb_exit_trigger": null,         // ★ 新增：退出触发条件（null=正常持有）

  // 以下字段与Track A通用（保持一致）
  "type": "rotation",              // Track B用 "rotation"，Track A用 "core_position"/"watchlist_position"
  "conviction_level": "B+",        // 与tb_rating一致
  "shares": 2000,
  "avg_cost": 58.30,
  "cost_basis": 116600.0,
  "current_price": 62.10,
  "market_value": 124200.0,
  "portfolio_pct": 0.117,
  "unrealized_pnl": 7600.0,
  "stop_loss": 52.47,              // ATR止损（ATR K=2.0）
  "stop_loss_pct": -0.10,
  "target_1": 70.0,
  "entry_date": "2026-05-22",
  "thesis": "T2产业催化：Rubin BOM +13.3%，L2 PCB，主升期早，B+入场",
  "bear_case": "龙头断板/炸板率>50%/持仓超45天",
  "bear_case_downside": -0.10,
  "next_catalyst": "龙头次日状态",
  "last_updated": "2026-05-28T00:01:19+08:00"
}
```

### 4.2 Track B的 pending_orders 格式

```json
{
  "pending_orders": [
    {
      "ticker": "002586",
      "action": "buy",
      "shares": 2000,
      "account": "a_share",
      "track": "B",                      // ★ Track标记
      "tb_rating": "B+",                 // ★ 评级
      "tb_theme_id": "TB-20260528-AI-PCB", // ★ 主线ID
      "tb_batch": 1,                     // ★ 建仓批次（1=首批，2=加仓）
      "tb_batch_total": 2,               // ★ 总批次
      "reason": "Track B B+入场：T2产业催化，L2 PCB，主升期早，评分85分",
      "created_at": "2026-05-22T08:30:00+08:00",
      "expires_at": "2026-05-22T15:00:00+08:00",  // 当日收盘前过期
      "status": "pending"
    }
  ]
}
```

### 4.3 Track B交易在 trade_log 中的标记

trade_log条目新增`track`字段：

```json
{
  "trade_id": "TRD-20260522-005",
  "ticker": "002586",
  "name": "天富能源",
  "action": "buy",
  "shares": 2000,
  "price": 58.30,
  "amount": 116600.0,
  "account": "a_share",
  "track": "B",                          // ★ 新增
  "tb_theme_id": "TB-20260528-AI-PCB",   // ★ 新增
  "tb_rating": "B+",                     // ★ 新增
  "reason": "Track B B+入场：T2产业催化...",
  "timestamp": "2026-05-22T09:45:00+08:00",
  "executed_by": "manual"  // Track B买入永远是 "manual"，不会是 "auto"
}
```

---

## §5 session流程设计

### 5.1 W1盘前（Track B部分，在§3 A股模式之后）

```
W1盘前 Track B Checklist（约3分钟）:

1. 读取 rotation_state.json（market_switch + active_themes）
   命令: cat rotation_state.json | python3 -c "..."（或rotation_engine.py --summary）

2. 如果 market_switch = "CLOSED" / "EMERGENCY_CLOSE"
   → 不做任何新入场，检查是否需要清仓
   → 查看 restart_confirmation.reopen_days_met

3. 如果有 active_themes，检查每个主线:
   → 持仓天数 vs 类型上限
   → 龙头昨日状态（latest_prices.json）
   → 有无退出信号（exit_signals in rotation_signals.json）

4. 读取 rotation_signals.json 的 new_candidates
   → 对感兴趣的候选，调 rotation_engine.py 做5维打分
   → 打分结果 ≥ B-（45分）→ 生成 pending_order

5. 执行买入（pending_orders确认后）:
   uv run --script scripts/execute_trade.py buy --account cn \
     --ticker XXXXXX --shares N --reason "Track B B+入场: ..."
   # rotation_engine.py已准备好--shares计算结果

6. 更新 rotation_state.json（新主线信息）:
   # rotation_engine.py --confirm 写入
```

### 5.2 W1盘中（Track B部分）

```
盘中监控（可手动触发，每30分钟一次）:
  uv run --script scripts/rotation_monitor.py --quick

关注信号（按优先级）:
  CRITICAL_EXIT: 龙头跌>5% → 立即执行Track B全清
    uv run --script scripts/execute_trade.py sell --account cn --ticker XXXXX --all \
      --reason "TRACK_B_EXIT: 龙头跌>5%铁律"

  EXIT_SIGNAL: 龙头断板 → 当日减仓至B-等级
    （人工判断，不自动执行）

  REDUCE_SIGNAL: 炸板率>50% → 减仓1档
    （人工判断）

如有 If-Then 预承诺:
  R5规则：盘前写入，盘中只执行，不修改
  格式写入 portfolio_state.json 对应持仓的 catalyst_action 字段
```

### 5.3 W2盘后（Track B部分）

```
盘后 Track B Review（约2分钟）:

1. rotation_review.py已自动运行，读取结果:
   cat daily-reviews/YYYY-MM-DD.md | grep -A 50 "## Track B"

2. 手动更新F20市场呼吸（每周一更新）:
   直接编辑 rotation_state.json 的 market_breath 字段

3. 如有出场，更新 tb_pain_memory.md 或 tb_victory_memory.md:
   uv run --script scripts/rotation_engine.py --post-mortem \
     --ticker XXXXX --loss-pct X.X --grade TB-B+

4. git commit:
   git add rotation_state.json rotation_signals.json portfolio_state.json daily-reviews/
   git commit -m "track-b: YYYY-MM-DD | 主线: {主题} | NAV: ¥{X}"
```

---

## §6 跨session状态传递

### 6.1 rotation_state.json 是 Track B 的 SSOT

Track B的所有跨session状态都通过`rotation_state.json`传递，不依赖memory推断。

**读取协议**：
- session开始 → rotation_scan.py已在08:00更新了rotation_state.json
- session中需要状态 → 直接读 rotation_state.json（不从memory重建）
- session修改了状态（如确认新主线）→ rotation_engine.py --confirm 原子写入

**与 portfolio_state.json 的关系**：
- 持仓数据的真相源（SSOT）仍是`portfolio_state.json`
- `rotation_state.json`只存主线状态/市场环境/监控信号
- 两者通过`tb_theme_id`关联（外键关系）

### 6.2 与 pending_actions.json 的关系

```
pending_actions.json（现有）: Track A的If-Then预承诺
rotation_state.json.active_themes[*].intraday_alerts: Track B的盘中信号

分离原因:
  1. Track B的信号有时效性（48h内有效），需要单独管理
  2. Track B不用If-Then预承诺（轮动太快，盘前写不了那么具体）
  3. 盘中rotation_monitor.py写信号，不污染pending_actions.json

但以下Track B信号会写入pending_actions.json（严重级别）:
  - 龙头跌>5%的critical信号（因为daily_run.sh Step 4b会读取并自动执行）
  - 持仓天数超限的critical信号

Track B的critical信号写入格式:
{
  "action_id": "TB-PA-20260528-001",
  "type": "sell",
  "ticker": "002586",
  "account": "a_share",
  "track": "B",                        // ★ 区分标记
  "priority": "critical",
  "reason": "TRACK_B_CRITICAL: 龙头跌>5%，全出铁律",
  "sell_all": true,
  "triggered_by": "rotation_monitor",
  "created_at": "2026-05-28T10:23:00+08:00",
  "expires_at": "2026-05-28T15:00:00+08:00"
}
```

### 6.3 跨session状态一致性检查

每次session启动时（pre_session_check.py扩展）：
```
Track B快速检查（在现有pre_session_check之后，约15秒）:
  1. rotation_state.json是否今日已更新（否→警告，rotation_scan可能失败）
  2. market_switch状态（CLOSED → 提示不做Track B）
  3. active_themes中有无持仓天数超限的主线
  4. rotation_signals.json是否有exit_signals（priority=critical → BLOCKED）
```

---

## §7 execute_trade.py 改造需求

### 7.1 新增 `--track` 参数

```python
# execute_trade.py 命令行参数新增
parser.add_argument("--track", choices=["A", "B"], default="A",
                    help="交易轨道（A=基本面，B=轮动）。默认A，不影响现有调用。")
parser.add_argument("--tb-theme-id", default=None,
                    help="Track B主线ID（仅--track B时使用）")
parser.add_argument("--tb-rating", choices=["B+", "B", "B-"], default=None,
                    help="Track B评级（仅--track B时使用）")
```

**trade_log写入时**：如果`--track B`，在trade_log条目追加`track/tb_theme_id/tb_rating`字段。

### 7.2 Track B特有风控检查

在execute_trade.py的买入验证中增加Track B检查块：

```python
def validate_track_b_buy(ticker, tb_rating, portfolio, rotation_state):
    """Track B买入特有风控（仅--track B时调用）"""
    errors = []

    # 硬开关检查
    switch = rotation_state.get("market_switch", "OPEN")
    if switch in ("CLOSED", "EMERGENCY_CLOSE"):
        errors.append(f"BLOCKED: 市场硬开关={switch}，Track B禁止新建仓")

    # 总仓位检查（Track B总仓位≤40%）
    tb_positions = [p for p in portfolio["accounts"]["a_share"]["positions"]
                    if p.get("track") == "B"]
    tb_total_pct = sum(p.get("portfolio_pct", 0) for p in tb_positions)
    nav = portfolio["accounts"]["a_share"]["total_assets"]
    # 计算买入后的Track B总仓位
    current_price = get_current_price(ticker)  # 现有函数
    order_amount = shares * current_price
    new_tb_pct = tb_total_pct + order_amount / nav
    if new_tb_pct > 0.40:
        errors.append(f"BLOCKED: Track B总仓位超40%限制（当前{tb_total_pct:.1%}，买入后{new_tb_pct:.1%}）")

    # 单只上限（按等级）
    tb_limits = {"B+": 0.15, "B": 0.12, "B-": 0.10}
    limit = tb_limits.get(tb_rating, 0.10)
    existing = next((p for p in tb_positions if p["ticker"] == ticker), None)
    existing_pct = existing.get("portfolio_pct", 0) if existing else 0
    new_pct = existing_pct + order_amount / nav
    if new_pct > limit:
        errors.append(f"BLOCKED: 单只Track B {tb_rating}上限{limit:.0%}（买入后{new_pct:.1%}）")

    # 北交所特殊上限
    if ticker.startswith(("43", "82", "83", "87", "88", "8")):
        if new_pct > 0.05:
            errors.append(f"BLOCKED: 北交所单只≤5%（买入后{new_pct:.1%}）")

    # 龙头当日跌>5% → 同板块Track B当日不新建（01_rating.md §4.2）
    active_themes = rotation_state.get("active_themes", [])
    for theme in active_themes:
        # 检查ticker是否属于此主线
        # （此检查需要sector映射，简化版：检查rotation_state是否有exit_signal_active）
        if theme.get("exit_signal_active"):
            if theme.get("l_layer") in ("L1", "L2", "L3"):  # 同板块传导层
                errors.append(f"WARNING: 主线'{theme['theme_name']}'有退出信号，确认是否继续")

    return errors
```

### 7.3 Track B评级系统的仓位上限（与Track A保持一致的实现方式）

Track A在`decision_engine.py`的`CONFIDENCE_MAX_PCT`中定义。Track B的仓位上限定义在`execute_trade.py`的`validate_track_b_buy`函数中（见上），同时也硬编码在`rotation_engine.py`的建仓股数计算中：

```python
# rotation_engine.py
TB_MAX_PCT = {
    "B+": 0.15,   # 单只最高仓位
    "B":  0.12,
    "B-": 0.10,
}
TB_TARGET_PCT = {
    "B+": 0.07,   # 首批建仓目标（分2批时）
    "B":  0.05,
    "B-": 0.10,   # B-一次性建仓
}
TB_MAX_TOTAL = 0.40   # Track B总仓位硬顶

def calc_entry_shares(ticker, rating, nav, current_price, batch=1, batch_total=2):
    """计算建仓股数（A股100股最小单位）"""
    if batch == 1 and batch_total > 1:
        target_pct = TB_TARGET_PCT[rating]
    else:
        target_pct = TB_MAX_PCT[rating]

    target_amount = nav * target_pct
    raw_shares = target_amount / current_price
    # A股向下取整到100股
    return int(raw_shares / 100) * 100
```

---

## §8 CLAUDE.md §6 脚本命令清单更新

以下命令需要追加到CLAUDE.md §6：

```markdown
| `uv run --script scripts/rotation_scan.py` | **Track B每日轮动扫描（daily_run自动，也可手动）** | A股 |
| `uv run --script scripts/rotation_scan.py --dry-run` | 扫描预览（不写文件） | A股 |
| `uv run --script scripts/rotation_engine.py --ticker XXXXXX` | **Track B 5维打分 + pending_order生成** | A股 |
| `uv run --script scripts/rotation_engine.py --review-holdings` | 检查所有Track B持仓升降级状态 | A股 |
| `uv run --script scripts/rotation_engine.py --confirm` | 确认评级写入rotation_state.json | A股 |
| `uv run --script scripts/rotation_monitor.py --quick` | **Track B盘中快速检查（critical信号）** | A股 |
| `uv run --script scripts/rotation_monitor.py --save` | Track B盘中检查（写pending_actions.json） | A股 |
| `uv run --script scripts/rotation_review.py` | Track B盘后日评（daily_run自动，也可手动） | A股 |
| `uv run --script scripts/execute_trade.py buy --account cn --ticker XXXXXX --shares N --track B --tb-rating B+ --tb-theme-id TB-xxx --reason "..."` | **Track B买入（必须带--track B参数）** | A股 |
```

---

## §9 实施优先级

### P0（系统运行最低要求，先做这4件）

| 优先级 | 任务 | 目的 |
|--------|------|------|
| P0-1 | 在`portfolio_state.json`持仓schema中增加`track/tb_theme_id/tb_rating`字段 | 区分Track A/B持仓 |
| P0-2 | 在`execute_trade.py`增加`--track`参数（不做风控检查也行，先记录） | Track B交易可记录 |
| P0-3 | 创建`rotation_state.json`（空模板，手动维护） | 跨session状态传递 |
| P0-4 | 创建`tb_pain_memory.md` + `tb_victory_memory.md`（空模板） | 复盘记录 |

### P1（自动化核心，1-2周实现）

| 优先级 | 任务 | 目的 |
|--------|------|------|
| P1-1 | `rotation_scan.py` — 硬开关检测（§1.1中的check_hard_switch部分） | 每日自动市场环境检测 |
| P1-2 | `rotation_review.py` — 持仓天数跟踪 + 升降级检查 | 防止超期持仓 |
| P1-3 | `daily_run.sh` — 插入rotation_scan.py（Step 2c）和rotation_review.py（Step 3b） | 自动化日常流程 |

### P2（盘中监控，2-4周）

| 优先级 | 任务 | 目的 |
|--------|------|------|
| P2-1 | `rotation_monitor.py` — 龙头跌>5%检测 + critical信号写入 | 铁律自动触发 |
| P2-2 | `rotation_engine.py` — 5维打分 + 建仓股数计算 | 加速session决策 |
| P2-3 | `execute_trade.py` — Track B完整风控验证 | 防止超仓 |

### P3（完整生态，4-8周）

| 优先级 | 任务 | 目的 |
|--------|------|------|
| P3-1 | `rotation_scan.py` — 新主线候选扫描（从latest_news.json提取T2信号） | 减少手动扫描时间 |
| P3-2 | `tb_playbook.json` — 赢家模式匹配 | 建仓时自动显示匹配模式 |
| P3-3 | `conviction_check.py` — 增加--track B支持 | Track B的Scorecard |

---

## 附录A：文件依赖图

```
news_collector.py ──────────→ latest_news.json ─────┐
fetch_prices.py ────────────→ latest_prices.json ────┤
                                                      ↓
rotation_scan.py ──(读)──────────────────────────────→ rotation_signals.json
                  ──(读写)──→ rotation_state.json ←── rotation_review.py
                                                      ↑
rotation_engine.py ─────────→ pending_orders (in portfolio_state.json)
                  ─────────→ rotation_state.json（确认后）

rotation_monitor.py ────────→ rotation_state.json（intraday_alerts）
                    ────────→ pending_actions.json（critical信号）

trading_engine.py ──(读写)──→ portfolio_state.json ←── execute_trade.py
rotation_review.py ─(读写)──→ portfolio_state.json（Track B持仓天数更新）
                    ────────→ daily-reviews/YYYY-MM-DD.md（Track B小节）

daily_run.sh ───→ [news_collector → catalyst_recognizer → fetch_prices → update_prices
                  → rotation_scan → trading_engine → rotation_review → decision_engine
                  → auto-execute → sync_nexus → git push]
```

---

## 附录B：rotation_state.json 空模板

首次创建时使用（P0-3任务）：

```json
{
  "_meta": {
    "version": "1.0",
    "purpose": "Track B轮动状态。rotation_scan.py维护。",
    "last_updated": "2026-05-28T00:00:00+08:00",
    "last_updated_by": "manual_init"
  },
  "market_switch": "OPEN",
  "market_breath": "inhale",
  "market_context": {
    "limit_up_count": null,
    "limit_down_count": null,
    "limit_up_yesterday": null,
    "market_volume_bn": null,
    "hs300_20d_return": null,
    "low_volume_streak": 0,
    "limit_up_low_streak": 0,
    "as_of_date": null
  },
  "active_themes": [],
  "watch_pool": [],
  "restart_confirmation": {
    "switch_closed_date": null,
    "reopen_days_met": 0,
    "catalyst_confirmed": false
  },
  "daily_stats": {
    "date": null,
    "tb_total_pct": 0,
    "tb_position_count": 0,
    "tb_unrealized_pnl": 0,
    "tb_realized_pnl_mtd": 0
  }
}
```

---

*版本：v1.0 | 编制日期：2026-05-28*
*来源：ROTATION_STRATEGY_V1.md + system-design/01_rating.md + daily_run.sh + trading_engine.py + decision_engine.py + portfolio_state.json schema*
*Claude分析意见，非用户投资结论。*
