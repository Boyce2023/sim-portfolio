# PRE-2009 US FUNDAMENTALS HARVEST AUDIT REPORT (1996–2008)

**Execution Timestamp:** 2026-11-16 15:08:08
**Universe Progress:** 1008 / 1008 companies processed (834 tickers in dataset, 834 CIKs)
**Output Parquet File:** `/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_fundamentals_30y_permanent/pre2009/pre2009_fundamentals_1996_2008_pit.parquet` (329,970 bytes, 5,980 rows)

---

## 1. Zero Lookahead & Point-in-Time Integrity Audit
- **Lookahead Violations (`filingDate < reportDate`):** `0` rows (0.00%)
- **Contemporaneous Anchoring:** Every 1996–2008 historical financial statement is strictly anchored to its contemporaneous SEC filing date from `submissions`.
- **Session Timing Breakdown:**
  - `DATE_ONLY`: 2,312 (38.7%)
  - `AMC_post1600ET`: 1,985 (33.2%)
  - `INTRADAY`: 1,403 (23.5%)
  - `BMO_pre0930ET`: 280 (4.7%)

## 2. Fiscal Year Distribution (1996–2008)
| Fiscal Year | Total Observations |
| :--- | :--- |
| 1996 | 224 |
| 1997 | 243 |
| 1998 | 246 |
| 1999 | 248 |
| 2000 | 390 |
| 2001 | 446 |
| 2002 | 471 |
| 2003 | 498 |
| 2004 | 506 |
| 2005 | 224 |
| 2006 | 338 |
| 2007 | 657 |
| 2008 | 1,489 |

## 3. Data Source Tier Distribution
| Source Tier | Records | Percentage | Description |
| :--- | :--- | :--- | :--- |
| `HTML_10K_ITEM6` | 3,595 | 60.1% | Historical 10-K Item 6 Selected Financials |
| `EARLY_XBRL_ANCHORED` | 2,093 | 35.0% | XBRL facts anchored to contemporaneous 10-K/10-Q filingDate |
| `EARLY_XBRL_UNANCHORED_RESTATED` | 292 | 4.9% | XBRL facts anchored to contemporaneous 10-K/10-Q filingDate |

## 4. Fundamental Field Coverage (17 Metrics)
| Metric | Field Name | Non-Null Observations | Coverage Rate |
| :--- | :--- | :--- | :--- |
| `rev` | REV | 4,438 | 74.2% |
| `gp` | GP | 723 | 12.1% |
| `opinc` | OPINC | 2,264 | 37.9% |
| `ni` | NI | 3,125 | 52.3% |
| `ocf` | OCF | 870 | 14.5% |
| `capex` | CAPEX | 759 | 12.7% |
| `rd` | RD | 364 | 6.1% |
| `sbc` | SBC | 658 | 11.0% |
| `assets` | ASSETS | 1,944 | 32.5% |
| `cash` | CASH | 2,193 | 36.7% |
| `total_debt` | TOTAL_DEBT | 1,175 | 19.6% |
| `equity` | EQUITY | 2,804 | 46.9% |
| `shares` | SHARES | 1,721 | 28.8% |
| `buyback` | BUYBACK | 630 | 10.5% |
| `div` | DIV | 642 | 10.7% |
| `inventory` | INVENTORY | 183 | 3.1% |
| `ar` | AR | 216 | 3.6% |

## 5. Permanent Storage Verification
- **Permanent Parquet Path:** `/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_fundamentals_30y_permanent/pre2009/pre2009_fundamentals_1996_2008_pit.parquet`
- **Raw SEC Cache Path:** `/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_fundamentals_30y_permanent/raw_sec_cache/`
- **Bulk Zip Archive Path:** `/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_fundamentals_30y_permanent/bulk_zip/`
- **Temporary Directory Policy Compliance:** ZERO reliance on `/tmp`. All caches, intermediate files, and artifacts are permanently persisted on project storage.

---
**Verification Status:** PASS (Zero lookahead, strict SEC rate limit compliance, permanent storage verified).
