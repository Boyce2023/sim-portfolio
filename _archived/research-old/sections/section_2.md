# §2 POD STRUCTURE + SABCT + REGIME CONFIGURATION

> Skeleton of V6.0. All allocation targets, grade limits, and concentration caps defined here.

---

## 2.1 Pod Definitions

**Pod I — AI Semiconductor Supply Chain (35% BULL)**
Core thesis: HBM, custom ASIC, interconnect are physically capacity-constrained through 2028 — priced as cyclical, are secular. Eligible names must have verifiable supply-side constraint (F13: backlog >6 months OR single-source position) AND direct AI DC revenue exposure >30% or segment growth >40% YoY. This is the primary alpha pod. Priority 1 for capital in every regime.

**Pod II — Energy Infrastructure (25% BULL)**
Core thesis: AI DC power demand is outpacing grid capacity by 3-5 years. Gas turbines and nuclear are physical constraints; market prices them as utilities. Eligible names must have contracted DC power delivery OR documented generation capacity with interconnection queue position. F4 (full-system LCOE) advantage required. Priority 2.

**Pod III — Compute Momentum (20% BULL) — NEW**
Core thesis: In confirmed BULL regime, F21 beat cycle + price momentum is a standalone edge. Captures NVDA-stall rotation (NVDA → MU/AMD/ARM lag 3-4 weeks; hyperscaler capex → networking/storage lag 1-2 weeks). Pod III shrinks to 5% in NEUTRAL, 0% in BEAR — it is a regime-dependent pod, not a core holding pod. Priority 3.

**Pod IV — Short Book (≤5% BULL)**
Three short types only: (1) Structural deterioration: revenue declining 2+ consecutive quarters, no reversal catalyst; (2) Narrative exhaustion: >60% above fair value + closing-gap catalyst; (3) Pair trade: long one supply chain node, short inferior adjacent node. Max 2.5% per position. Max 3 active shorts. No shorts with >30% short interest (squeeze risk).

**Beta Reserve (5%)**
Market beta exposure without consuming alpha-pod attention. Names that can't clear Pod I/II/III criteria but warrant market exposure. Not actively traded — one review per quarter. NVDA or SPY if conviction is weak.

**Cash (≥10% BULL)**
Dry powder for rotation. Not a position. Not counted in alpha calculations.

---

## 2.2 SABCT Grade System — US Version (v3.0 Alpha)

Matches A股 v7.0 format. No S grade. No C grade. No waiver mechanism.

| Grade | Position Cap (BULL) | Position Cap (NEUTRAL) | Stop Loss |
|-------|--------------------|-----------------------|-----------|
| A+    | 20%                | 15%                   | -15%      |
| A     | 15%                | 12%                   | -15%      |
| A-    | 12%                | 10%                   | -12%      |
| B+    | 10%                | 8%                    | -10%      |
| B     | 8%                 | 6%                    | -10%      |
| B-    | 5%                 | —                     | -8%       |

**Grade concentration rule**: A+/A/A- combined ≤4 positions across all pods (3 alpha pods = one extra slot vs A股's 3-pod limit). B+ and below: unlimited count but subject to pod caps.

---

## 2.3 Regime Configuration Table

| Regime  | Pod I | Pod II | Pod III | Pod IV (Short) | Beta Reserve | Cash  |
|---------|-------|-------|-------|---------------|--------------|-------|
| BULL    | 35%   | 25%   | 20%   | ≤5%           | 5%           | ≥10%  |
| NEUTRAL | 25%   | 20%   | 5%    | ≤8%           | 7%           | ≥25%  |
| BEAR    | 15%   | 15%   | 0%    | ≤15%          | 5%           | ≥40%  |

**Regime detection (weekly, Friday close, 5 minutes):**
- BULL: VIX <20 + SPY >50dma + SOX uptrend — all three required
- NEUTRAL: any one of above fails
- BEAR: VIX >28 sustained OR SPY breaks 200dma

**Regime change protocol**: If regime changes, reallocate pod targets BEFORE any other action that session. Pod III in NEUTRAL: cut to 5%, immediately move freed capital to cash. Pod III in BEAR: exit all positions within 5 trading days.

---

## 2.4 Pod Rules (Hard Limits)

| Rule | Limit |
|------|-------|
| Max positions per pod | 5 (Pods I/II/III); 3 (Pod IV) |
| Single stock cap | ≤20% total portfolio (A+ in BULL only) |
| AI semis concentration | ≤40% total portfolio |
| Energy concentration | ≤20% total portfolio |
| Short per position | ≤2.5% |
| Pod III trailing stop | 12% (tighter — momentum reverses fast) |
| Pod I/II trailing stop | 15% standard |

**F15 BULL override (mandatory):** In BULL regime, consensus bullish + analyst upgrade cycle = ERM alpha = INCLUDE in pod. Only exclude when stock price exceeds consensus target by >5% (genuinely priced in). This rule was in V5, never enforced — V6 enforces it.
