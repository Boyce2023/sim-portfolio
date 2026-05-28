## §7 ROTATION DETECTION PROTOCOL

> New in V6. V5 had no detection mechanism — NVDA→MU/AMD/ARM rotation was predictable but missed.

---

### Weekly Monday Scan (10 min, non-negotiable)

Run before market open. Five checks in order:

1. **NVDA vs SOX**: Pull Friday-to-Friday returns. NVDA week return minus SOX week return > 5% (positive or negative spread) = **yellow signal**.
2. **MU / AMD / ARM vs NVDA**: If any outperform NVDA by >5% same week = **rotation confirmed**.
3. **ANET / CRDO / DELL vs NVDA**: Networking/storage outperforming semis = **next-leg signal** (hyperscaler capex read-through).
4. **VST / GEV vs XLU**: Energy names beating utility index = **energy re-rate signal**, Pod II watch.
5. **HBM pricing news check**: Scan Korea semiconductor press (SK Hynix, Samsung) for HBM contract pricing. Price up = MU upside revision trigger.

---

### Rotation vs Pullback Decision Table

| Condition | SOX | Old Leader (NVDA) | Emerging (MU/AMD/ARM) | Verdict | Action |
|-----------|-----|-------------------|----------------------|---------|--------|
| True Rotation | flat / up | down / flat | up | Sector bid shifting | Trim leader, add emerging |
| Sector Pullback | down | down | down | Risk-off within sector | Hold all, do not rotate |
| Market Risk-Off | all down | all down | all down | Macro selling | Reduce total exposure |

Rule: Never rotate during a sector pullback. Rotation requires the emerging names to be **up** while leader stalls.

---

### Signal Escalation and Action Rules

| Stage | Definition | Action |
|-------|-----------|--------|
| Yellow | 1 week: NVDA vs SOX spread >5% | Prepare Pod III capital. No trades. |
| Red | 2 consecutive weeks confirming same signal | Execute: trim 25% old position, add 25% new target. |

Hard limits:
- **Single rotation event**: move ≤50% of affected Pod III capital. Never flip the whole pod in one week.
- **50/50 split on entry**: deploy 50% of proceeds into new target immediately; hold 50% in cash pending week-2 confirmation.
- Do not sit in old position while waiting. Yellow = free the capital, park in cash.

---

### Capital Redeployment Rule

Pod III rotation exit proceeds must be redeployed or returned to cash within **5 trading days**. No exceptions. Proceeds sitting in an old stalling position while scanning for the next one is the exact failure mode this protocol exists to prevent.
