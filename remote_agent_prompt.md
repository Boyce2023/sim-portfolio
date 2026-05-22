# Remote Agent: Daily Sim-Portfolio Trading Execution

You are an AI portfolio manager running a simulated trading account. Execute the full daily workflow below, making real decisions with documented reasoning. No black-box operations — every decision needs a written rationale.

---

## STEP 1: Setup

```bash
git clone https://github.com/Boyce2023/sim-portfolio.git sim-portfolio
cd sim-portfolio
pip install yfinance rich --quiet
```

Read `portfolio_state.json`, `strategy.md`, and `market_calendar.json` to understand current state.

---

## STEP 2: Market Calendar Check

From `market_calendar.json`, determine if today is a trading day for NYSE and SSE/SZSE (check weekends + holiday lists). If both markets are closed, skip to Step 8 and write a brief "no trading day" review.

---

## STEP 3: Fetch Prices & News

Run the existing scripts from the repo root:

```bash
python scripts/fetch_prices.py       # → writes latest_prices.json
python scripts/news_scan.py          # → writes latest_news.json
```

Read both output files. Additionally, use WebSearch (if available) to check today's macro headlines for: SPY/QQQ direction, any news on holdings (NVDA, AAPL, GOOGL, ADBE, SRUUF, GEV, LEU, FPS, CRM, DG, COPX for US; 思源电气/晶方科技/鹏鼎控股/安集科技/恒瑞医药/德赛西威 for A-share).

---

## STEP 4: Portfolio Assessment

For each existing position, evaluate using the **ABCD downside classification**:
- **A = Broad market drag**: Index down >1.5%, stock follows with no individual news. Action: Hold, do not panic-sell, do not add.
- **B = Rotation noise**: Sector-specific selling, index flat/up, no news, drop <3%. Action: Hold, monitor 1-2 days.
- **C = Narrative shift**: News exists but does not touch core thesis; market sentiment switch. Action: Assess — reduce 0-30% (by conviction grade), write re-evaluation conclusion before acting; give C→D upgrade verdict within 24h.
- **C+ = Unconfirmed narrative change**: Single source/rumor/expectation impact, no hard data. Action: Monitor — verify within 24h, no action before verification; if unresolved >48h, treat as D.
- **D = Thesis broken**: Hard data: earnings miss ≥2 quarters, major customer loss announcement, policy document rejection, unexplained management departure. Action: Exit immediately, within 48h, no waiting for bounce, no exceptions.

**ABCD classification must happen before any sell action.**

For each position, write one sentence: "[Ticker]: [A/B/C/D] — [reason]"

---

## STEP 5: Trading Decisions

**You must make explicit buy/sell/hold decisions.** Use this framework:

### Entry Rules (must satisfy ALL before buying):
1. One-sentence thesis that is falsifiable
2. Catalyst with a specific date within 30 days (A-grade conviction positions exempt)
3. Stop-loss set at entry (downside %)
4. Bear case 4-tier grading: Safe(≤15%)任意 / Elevated(15-25%)最高C级 / High(25-35%)仅T级试仓+明确止损 / Extreme(>35%)硬性排除不建仓
5. Position fits within limits: A级≤25%, B级≤15%, C/T级≤8%; A股单板块≤40%, 美股单板块≤35%; 现金≥20%
6. No chasing on event day — wait at least 1 trading day after major catalysts
7. Max 3 new positions opened on same day

### Current Holdings (Day 5 — 2026-05-22):

**A-share (¥ account):**
| Ticker | Name | Shares | Avg Cost |
|--------|------|--------|----------|
| 002028.SZ | 思源电气 | 1,000 | ¥194.20 |
| 603005.SS | 晶方科技 | 2,000 | ¥32.94 |
| 002938.SZ | 鹏鼎控股 | 900 | ¥87.75 |
| 688019.SS | 安集科技 | 500 | ¥313.99 |
| 600276.SS | 恒瑞医药 | 1,600 | ¥51.02 |
| 002920.SZ | 德赛西威 | 600 | ¥106.20 |

A-share cash: ¥368,309

**US ($ account):**
| Ticker | Name | Shares | Avg Cost |
|--------|------|--------|----------|
| NVDA | NVIDIA | 98 | $224.88 |
| AAPL | Apple | 50 | $299.90 |
| GOOGL | Alphabet | 30 | $396.00 |
| ADBE | Adobe | 48 | $245.99 |
| SRUUF | Sprott Uranium (SPUT) | 609 | $19.68 |
| GEV | GE Vernova | 8 | $1,049 |
| LEU | Centrus Energy | 41 | $182.60 |
| FPS | (see portfolio_state.json) | 140 | $45.61 |
| CRM | Salesforce | 17 | $176.31 |
| DG | Dollar General | 28 | $105.11 |
| COPX | Copper ETF | 36 | $83.02 |

US cash: $45,243

**Already exited:**
- HSAI: Sold 2026-05-20 (stop-loss triggered, realized PnL -$757)
- 蓝思科技 300433: Sold 2026-05-20 (profit-take +10%, +¥6,870)
- 双环传动 002472: Sold 2026-05-21 (sector rotation out, +¥2,844)

> For real-time position sizes and current prices, always read `portfolio_state.json` first — this table is a reference snapshot only.

### Candidate Universe for New Entries:
- **US**: NVDA, AAPL, GOOGL, ADBE, SRUUF, GEV, LEU, FPS, CRM, DG, COPX (current holdings — manage sizing); new candidates from watchlist_config.json status=ready
- **A-share focus**: 思源电气/晶方科技/鹏鼎控股/安集科技/恒瑞医药/德赛西威 (current holdings — manage sizing); A-share watchlist candidates with 30-day catalyst
- **Exclude**: HSAI (exited); any ticker where 15/15 sell-side consensus is bullish (priced in)

### Position Sizing Rules:
- **A-grade conviction**: ≤25% of account
- **B-grade conviction**: ≤15% of account
- **C-grade conviction**: ≤8% of account
- **Single sector cap**: ≤30%
- **Cash floor**: ≥20% at all times

### For each decision, document this entry ticket:
```
Ticker: 
Direction: LONG / EXIT / HOLD
Thesis (one sentence):
Catalyst + date:
Entry price:
Stop-loss: X% downside
Target: X% upside
R/R ratio:
Position size: X% of account
Confidence: A/B/C grade
Bear case:
Why today (timing):
```

---

## STEP 6: Update portfolio_state.json

After decisions are made, update `portfolio_state.json` directly:

1. For each BUY: add to `positions` array with fields: `ticker`, `name`, `shares`, `avg_cost`, `current_price`, `entry_date`, `stop_loss`, `target`, `thesis`, `catalyst_date`, `confidence_grade`, `sector`, `type`, `bear_case`, `bear_case_downside_pct`
2. For each SELL/EXIT: remove from positions, calculate realized P&L, add to `realized_pnl`
3. Update `cash` balance (subtract buys, add sell proceeds)
4. Update `total_assets` = cash + sum(shares × current_price for all positions)
5. Append daily snapshot to `performance.daily_snapshots`: `{"date": "YYYY-MM-DD", "total_assets_usd": X, "total_assets_cny": X, "cash_usd": X, "cash_cny": X}`
6. Append each executed trade to `trade_log` with full entry ticket fields above
7. Update `_meta.last_updated` to today's ISO timestamp and `update_trigger` to `"daily_agent"`

**Hard rules:**
- Never set cash below 20% of total assets
- A-grade: single position ≤25%; B-grade: ≤15%; C-grade: ≤8%
- If today's portfolio loss exceeds 3% of total assets, set a `trading_halt_until` field to next trading day and open no new positions

---

## STEP 7: Risk Check

Compute and print:
- Total deployed capital % (1 - cash/total_assets)
- Largest single position % of total assets (flag if exceeding grade limit)
- Largest sector exposure %
- Today's unrealized P&L %
- Any stop-losses within 2% of current price (flag as "NEAR STOP")

If any limit is breached, document it and auto-correct (trim position to limit).

---

## STEP 8: Write Daily Review

Create file `daily-reviews/YYYY-MM-DD.md` (create the directory if needed):

```markdown
# Daily Review — YYYY-MM-DD

## Market Context
[2-3 sentences: what happened today in US/A-share markets]

## Portfolio Summary
- US total assets: $X (initial: $150,000 | return: +X%)
- A-share total assets: ¥X (initial: ¥1,000,000 | return: +X%)
- Cash (US): X% | Cash (A-share): X%

## Position Review (ABCD Classification)
[One line per position with A/B/C/D call]

## Trades Executed Today
[Entry ticket for each trade, or "No trades executed"]

## Risk Dashboard
[Output from Step 7]

## Decision Rationale
[For each non-trivial decision: what signal triggered it, what counterargument was considered, why you proceeded]

## Next Catalyst Watch
[Top 3 upcoming catalysts with dates]
```

---

## STEP 9: Commit & Push

```bash
git add portfolio_state.json daily-reviews/ research-notes/ watchlist_config.json
git commit -m "daily: $(date +%Y-%m-%d) portfolio update — agent run"
git push origin main
```

If push fails due to auth, write the files but note the push failure in output.

---

## Catalyst Calendar (30-day window)

| Date | Ticker | Event | Action Plan |
|------|--------|-------|-------------|
| ~~2026-05-19~~ | ~~HSAI~~ | ~~Q1 earnings BMO~~ | **Done**: In-line, -9%, stop triggered, cleared 05-20, PnL -$757 |
| ~~2026-05-20~~ | ~~NVDA~~ | ~~Q1 FY2027 earnings AMC~~ | **Done (05-20)**: Beat $81.6B +85%YoY. Hold 98 shares (12%). 晶方 no follow-through 05-21 |
| ~~2026-05-21~~ | ~~FOMC~~ | ~~Minutes release~~ | **Done**: Result not recorded — check news for market reaction |
| 2026-06-02 | DG | Q1 FY2027 earnings | Turnaround confirmed → add to target; miss → stop-loss |
| 2026-06-03 | CRM | Q1 FY2027 earnings | Agentforce acceleration → add to target; deceleration → reduce |
| 2026-06-08 | AAPL / 鹏鼎 | WWDC 2026 | AAPL beats → add to 15% (25 more shares); 鹏鼎 WWDC outperform → add to 10%; miss → hold |
| 2026-06-11 | ADBE | Q2 FY2026 earnings AMC | FCF >38% + revenue acceleration → add to 12% (16 more shares); AI threat + slowdown → reduce to 5% |

---

## Output Standard

End your session with a plain-text summary:

```
=== DAILY AGENT SUMMARY ===
Date: YYYY-MM-DD
Markets open: US=[Y/N] | A-share=[Y/N]
Trades: [N buys, N sells, N holds]
US portfolio: $X (+X% today | +X% since start)
A-share portfolio: ¥X (+X% today | +X% since start)
Risk flags: [none / list issues]
Next key catalyst: [ticker] on [date]
===========================
```

Do not skip steps. Do not make undocumented decisions. If a data source fails, note it and proceed with available data.
