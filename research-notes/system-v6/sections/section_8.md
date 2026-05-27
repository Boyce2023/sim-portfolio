## §8 OPERATIONAL CORE — Daily Trading Templates

> 日常只读这个section就能交易。其余sections是背景知识，疑问时查阅。

```
=== 周五62分钟例行 ===

-1. CONVICTION SCORECARD (2min) — 先面对自己的记录
   Run: `uv run --script scripts/conviction_check.py --update`
   
   Circuit Breaker: 🟢/🟡/🔴
   ⚠️ 若🔴RED: 本session禁止新建仓。跳过步骤3/4的建仓评估，只做减仓+Discovery
   ⚠️ 若🟡YELLOW: 所有sizing×0.5
   
   评级权限: A+ [✓/✗]  |  Grade准确率: ___%
   最近止损: ___________

0. DISCOVERY SCAN (15min) — 先看市场，再看自己
   Run: `uv run --script scripts/discovery_scan.py`
   
   PRIORITY (3+ hits): ___________
   → 本session必须花30min深入, 与最弱持仓比较
   
   INVESTIGATE (2 hits): ___________
   → 本session花15min看一眼
   
   New names found: ___  
   Sector coverage: ___/11 GICS
   
   ⚠️ 若PRIORITY非空: 在Portfolio Review步骤中与最弱conviction持仓对比
   ⚠️ 若连续4周PRIORITY=0且INVESTIGATE=0: 茧房警报，扩大universe

1. REGIME CHECK (5min)
   VIX=___  方向=↑/↓/→
   SPY vs 50dma=___% (正=上方/负=下方)
   SOX趋势=上/平/下
   → 当前Regime: BULL / NEUTRAL / BEAR
   ⚠️ 若Regime较上周变化: 先执行POD REALLOCATION再往下走

2. ROTATION SCAN (10min)
   NVDA周=____%  SOX周=____% 价差=____%
   MU/AMD/ARM vs NVDA本周=____%
   ANET/CRDO/DELL vs NVDA本周=____%
   rotation触发? Y/N  → 触发方向: semis / networking / energy
   ⚠️ NVDA -5% + SOX平: 48h内扫MU/AMD/ARM Pod III入场

3. PORTFOLIO REVIEW (10min)
   | Ticker | Pod | Grade | F21状态 | 催化剂日期 | 止损距离 | 动作 |
   |--------|-----|-------|---------|-----------|---------|------|
   | ___ | I/II/III/IV | ___ | Exp/Maint/Det/Miss | ___ | ___% | Hold/Add/Cut |
   | ___ | I/II/III/IV | ___ | Exp/Maint/Det/Miss | ___ | ___% | Hold/Add/Cut |
   | ___ | I/II/III/IV | ___ | Exp/Maint/Det/Miss | ___ | ___% | Hold/Add/Cut |
   | ___ | I/II/III/IV | ___ | Exp/Maint/Det/Miss | ___ | ___% | Hold/Add/Cut |
   | ___ | I/II/III/IV | ___ | Exp/Maint/Det/Miss | ___ | ___% | Hold/Add/Cut |

4. PIPELINE SCAN (5min)
   本周earnings beats: ___________
   新突破(base breakout): ___________
   hyperscaler capex新闻: Y/N → 影响: ___________
   30天内催化剂: ___________
   新Pod III候选: ___________

5. SIZING RECONCILIATION (5min)
   Pod I=___% (目标35%)  ✓/超限
   Pod II=___% (目标25%)  ✓/超限
   Pod III=___% (目标20%)  ✓/超限
   Pod IV Short=___% (≤5%) ✓/超限
   Beta Reserve=___% (≤5%) ✓/超限
   Cash=___% (≥10%)  ✓/不足
   ⚠️ 超限: 卖最弱conviction名字 | 不足现金: 减Pod III优先

6. ANTI-PORTFOLIO + NEXT WEEK PLAN (10min)
   Run: `uv run --script scripts/anti_portfolio.py`
   
   Anti-Portfolio Gap: ___% (target <50%)
   Sector blind spots: ___________
   Top investigate candidate: ___________
   
   下周催化剂: ___________
   planned entries: ___________
   planned exits: ___________
   Discovery Override candidate: ___________ (if any)


=== PRE-TRADE GATE (每笔交易前，4关全过才能交易) ===

Gate 1 Edge: _________________________
   [Supply constraint / Earnings accel / Rotation capture / Short thesis]
   一句话说不清 → 不交易，进watchlist

Gate 2 F9: Bear case=____%  Cyclical(C) or Secular(S)?
   → Tier: T1(<15%) / T2(15-25%) / T3(25-40%) / T4(>40%)
   T1 ✓ | T2+BULL+C ✓ | T2+NEUTRAL/BEAR ✗ | T3/T4 ✗

Gate 3 Catalyst: 日期=________  事件=_________________________
   无具体日期 → watchlist only，不开仓

Gate 4 Sizing: Grade=___  Pod=___  Size=___%
   对照§5表格: 合规? Y/N
   主题集中度: AI semis总=___%(≤40%) Energy=___%(≤20%) 单只=___%(≤20%)
   ✗ → resize或取消


=== F21 CHECK (每次持仓earnings后24h内必填) ===

标的: ___  日期: ___
EPS Beat? Y/N  Revenue Beat? Y/N
Guidance vs 上季: 上调↑ / 持平→ / 下调↓

Beat type:
  Exp (Beat+Guidance↑) → Hold，考虑加仓至grade上限
  Maint (Beat+Guidance→) → Hold，不加仓，下季复查
  Det (Beat+Guidance↓) → 减仓50%，止损收紧至8%
  Miss (任何miss) → 当日清仓，24h内写post-mortem

Action执行: ___________________________


=== F15 BULL OVERRIDE CHECK (新仓位加入时) ===

Regime: BULL / NEUTRAL / BEAR
分析师共识方向: 看多 / 中性 / 看空
Upgrade cycle中? Y/N
Stock vs consensus target: ___% (正=高于target / 负=低于target)

判断:
  BULL + 共识看多 + 股价低于target → INCLUDE (ERM alpha, 不是price-in)
  BULL + 共识看多 + 股价高于target >5% → EXCLUDE (真正price-in)
  NEUTRAL/BEAR → 按标准F15执行 (15/15看多=排除)
结论: Include / Exclude


=== EXIT TRIGGER CHECKLIST (任何减仓/清仓前对照) ===

[ ] F21 Det或Miss → 减50%或当日全出
[ ] Stop hit → 先ABCD分类:
    A(大盘跌SPY<-2.5%) → Hold
    B(板块跌, 大盘平) → Hold+监控rotation
    C(叙事变化, thesis完整) → 评估, 可Hold
    D(基本面破, thesis证伪) → 当日清仓
[ ] Catalyst failed (到日期没兑现) → 48h重估, 无新日期→出
[ ] Pod超限 → 卖最弱conviction
[ ] Regime → NEUTRAL: Pod III减50%, 现金≥20%
[ ] Regime → BEAR: Pod III清零, Pod I/II减至BEAR配置, 现金≥40%
[ ] Rotation确认离开本板块 → Pod III减50%, 48h内


=== SIZING QUICK REF ===

Regime:  BULL → A=35% B=25% C=20% D≤5% Beta≤5% Cash≥10%
         NEUTRAL → A=25% B=20% C=15% D≤8% Beta≤7% Cash≥25%
         BEAR → A=15% B=15% C=0% D≤15% Beta≤5% Cash≥45%

Per position max:  S=20%  A+=15%  A=12%  A-=8%  Pod III max=12%
Short: 单只≤2.5%  Short book≤10%  活跃空单≤3只
Theme: AI semis≤40%  Energy≤20%  Single stock≤20%
频率: ≤5trades/week  ≤2/day

=== ANTI-COCOON METRICS (每月底检查) ===

Discovery Rate: ___ new names/week (target ≥5, alert <2×2weeks)
Pipeline Freshness: ___% added last 30d (target ≥30%, alert <15%)
Sector Coverage: ___/11 GICS (target ≥6, alert <4)
Anti-Portfolio Gap: ___% (target <50%, alert >70%)

3/4 red → 茧房警报: 下个session全部时间用于discovery，暂停持仓分析

=== CONVICTION SCORECARD QUICK REF ===
Circuit Breaker触发:
  🟡 YELLOW: 单周跌>3% OR 连续止损≥2 → sizing×0.5
  🔴 RED: 单周跌>5% OR 连续止损≥3 → 禁止新建仓
  恢复: 连续2周无新止损 → 升一级（RED→YELLOW→GREEN）

评级权限:
  A+/A止损 → 30天不可给A+
  Grade准确率<50%(rolling 10) → 全线降一级
  恢复: 降级后连续3笔盈利

Pain Memory:
  建仓前match pain_memory → 写"这次不同因为___"
  不写 = Gate 0不通过
```

---

*§8 v6.1 | 2026-05-27 | +Discovery System嵌入(Step 0) + Anti-Portfolio(Step 6) + Anti-Cocoon Metrics + Pain/Reward Integration(Conviction Scorecard)*
