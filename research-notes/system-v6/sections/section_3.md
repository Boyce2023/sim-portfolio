# §3 PRE-TRADE GATE — 美股五条核心规则（V6.1）

> 每笔交易必须过此节。无waiver。违反=不执行该笔交易。

**Gate 0: Circuit Breaker + Pain Memory Check**
读取 `conviction_scorecard.json`:
  🔴 RED → 本session禁止新建仓。只允许减仓+Discovery。到此停止，不往下走。
  🟡 YELLOW → sizing全线×0.5。继续Gate 1-4但所有仓位上限减半。
  🟢 GREEN → 正常执行。

读取 `pain_memory.md`:
  检查: 本次建仓的sector/pattern/grade是否match最近5条post-mortem中的任何一条？
  Match → 必须写: "我知道上次{ticker}亏了{loss%}因为{reason}，这次不同因为{具体原因}"
  不写 → Gate不通过。

**R1 唯一真相源**
价格/仓位/P&L只从`portfolio_state.json`读取。不从memory估算，不用~近似值。
每session第一步：`uv run --script scripts/update_prices.py`。数据未刷新=不做交易决策。

**R2 仓位硬上限**
SABCT sizing：S≤20% / A+≤15% / A≤12% / A-≤8% / Pod III任何等级≤12%。
Pod上限：A≤35% / B≤25% / C≤20% / D≤5% / Cash≥10%(BULL)/20%(NEUTRAL)/40%(BEAR)。
单标的≤20%。总持仓≤12只（跨三Pod）。违反→先调整，不可建完再说。

**R3 无thesis不建仓（4-Gate，顺序检查，一票否决）**
- Gate 1 Edge声明：supply constraint / earnings acceleration / rotation capture / short thesis。说不出一句话=watchlist only，不做。
- Gate 2 F9 + Cyclical Modifier：T1(<15%)=绿灯 / T2(15-25%)=BULL+周期性bear才可入 / T3/T4在NEUTRAL/BEAR=不做。结构性bear case无modifier，严格执行原tier。
- Gate 3 催化剂日期：必须有具体日期（YYYY-MM-DD或明确事件名+日期）。模糊时间=watchlist only。
- Gate 4 Sizing合规：新仓位+现有Pod占比≤Pod上限，且总持仓≤12只。不合规=缩size或不做。

**R4 止损不可协商**
触及止损线当日执行。不等，不分类先于执行。止损线：Pod I/II=15% / Pod III=12% / 空头亏损方向=15%。
执行后做ABCD分类（复盘用，不是执行前的拖延理由）。D类=当日出；I/II/III类=仍执行止损，thesis review事后做。

**R5 If-Then盘中不可修改**
If-Then预承诺在收盘后写入`portfolio_state.json → pending_actions`。盘中只执行，不新增，不修改条件。
想改=情绪干扰信号。处理：记录daily-review，收盘后改，次日生效。

---
*§3 V6.1 | 2026-05-27 | 对应US_TRADING_SYSTEM_V6.md §4 + §5*
