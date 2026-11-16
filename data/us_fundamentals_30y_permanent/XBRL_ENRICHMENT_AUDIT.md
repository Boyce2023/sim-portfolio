# XBRL 2009–2026 Financial Database Permanent Enrichment Audit

**Audit Date**: 2026-11-16 14:39:33  
**Engine**: `XBRL-2009-2026-Enricher-And-MissingGiant-Fixer`  
**Location**: `/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_fundamentals_30y_permanent/xbrl_master_enriched_2009_2026.parquet` (Size: `49.66 MB`, NEVER `/tmp`!)  
**Cache**: `/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_fundamentals_30y_permanent/raw_sec_cache/companyfacts_gz` (`.json.gz` atomic cache)  

---

## 1. Executive Summary & Gaps Permanently Closed

| Metric | Original Database | Enriched Database | Change / Verification |
|---|---|---|---|
| **Total Rows** | `66,680` | `66,850` | `+170` (+170 quarters from domestic US giants) |
| **Unique Tickers** | `1,310` | `1,313` | `+3` (`WBD`, `FOXA`, `BRK-B` integrated) |
| **NaN `mcap_usd_b` Rows** | `7,898` (`11.84%`) | `454` (`0.68%`) | Rescued 7,440+ rows; reduced NaN down to `0.68%` |
| **Visa (`V`) Coverage** | 0/69 rows valid | **69/69 rows valid** | Fully restored via split-adjusted price-anchored historical market cap |
| **Baker Hughes (`BKR`) Coverage** | 9/38 rows valid | **38/38 rows valid** | Fully restored |
| **Constellation (`STZ`) Coverage** | 0/64 rows valid | **64/64 rows valid** | Fully restored |
| **Erie Indemnity (`ERIE`) Coverage** | 0/66 rows valid | **66/66 rows valid** | Fully restored |
| **Brookfield Asset Mgmt (`BAM`)** | 0/6 rows valid | **6/6 rows valid** | Fully restored |
| **Coterra Energy (`CTRA`)** | 0/68 rows valid | **68/68 rows valid** | Fully restored via SEC EntityPublicFloat Point-in-Time |
| **Universal Display (`OLED`)** | 0/62 rows valid | **62/62 rows valid** | Fully restored via price-anchored / EntityPublicFloat |
| **Symbotic (`SYM`) Multi-Class Fix** | $5.3B (undercounted) | **$26.0B (full equity value)** | Rescued from Class A single-tag undercounting |
| **TKO Group (`TKO`) Multi-Class Fix** | $14.0B (undercounted) | **$35.2B (full equity value)** | Rescued from Class A single-tag undercounting |

---

## 2. Rescued Tickers Detailed Verification Table

| ticker   |     cik |   rows |   nan_mcap |   mean_mcap_b |   latest_mcap_b | latest_pe   | primary_source   |
|:---------|--------:|-------:|-----------:|--------------:|----------------:|:------------|:-----------------|
| V        | 1403161 |     69 |          0 |        225.78 |          664.03 | 28.3        | price_anchored   |
| BKR      | 1701605 |     38 |          0 |         37.46 |           69.17 | 23.9        | price_anchored   |
| BAM      | 1937926 |      6 |          0 |         81.96 |           85.99 | 28.1        | price_anchored   |
| MRNA     | 1682852 |     32 |          0 |         44.59 |           62.81 | -22.5       | sec_shares       |
| RVMD     | 1628171 |     21 |          0 |          9.94 |           46.42 | N/A         | price_anchored   |
| STZ      |   16918 |     64 |          0 |         20.97 |           18.44 | 9.6         | price_anchored   |
| ERIE     |  922621 |     66 |          0 |          6.4  |           11.11 | 19.3        | price_anchored   |
| CTRA     |  858470 |     68 |          0 |         11.29 |           19.2  | 11.5        | sec_public_float |
| OLED     | 1005284 |     62 |          0 |          4.87 |            4.29 | 18.6        | price_anchored   |
| CASY     |  726958 |     65 |          0 |          7.14 |           23.36 | 30.2        | sec_shares       |
| INCY     |  879169 |     64 |          0 |         14.57 |           24.47 | 60.7        | sec_shares       |
| INSM     | 1104506 |     61 |          0 |          7.29 |           24.63 | -40.7       | price_anchored   |
| JBHT     |  728535 |     66 |          0 |         12.89 |           21.25 | 31.4        | sec_shares       |
| LPLA     | 1397911 |     62 |          0 |         10.77 |           22.41 | 16.1        | sec_shares       |
| LVS      | 1300514 |     66 |          0 |         41.3  |           23.4  | 14.5        | sec_shares       |
| NVT      | 1720635 |     35 |          0 |          8.98 |           20.29 | 29.9        | sec_shares       |
| Q        | 2058873 |      5 |          0 |         25.79 |           23.11 | N/A         | sec_shares       |
| RDDT     | 1713445 |     12 |          0 |         39    |           27.46 | 27.7        | price_anchored   |
| SYF      | 1601712 |     50 |          0 |         23.52 |           23.74 | 7.1         | sec_shares       |
| SYM      | 1837240 |     16 |          0 |         30.08 |           29.53 | 2339.5      | price_anchored   |
| TKO      | 1973266 |     13 |          0 |         27.51 |           34.07 | 118.6       | sec_shares       |

---

## 3. Domestic US $25B+ 10-K/10-Q Giants Integrated (2009–2026)

| ticker   |     cik | name                         | sector             |   rows | earliest_end   | latest_end   |   latest_rev_b |   latest_mcap_b |
|:---------|--------:|:-----------------------------|:-------------------|-------:|:---------------|:-------------|---------------:|----------------:|
| WBD      | 1437107 | Warner Bros. Discovery, Inc. | Telecommunications |     69 | 2009-06-30     | 2026-06-30   |           8.72 |           61.37 |
| FOXA     | 1754301 | Fox Corporation              | Industrials        |     32 | 2018-12-31     | 2026-09-30   |           4.57 |           26.92 |
| BRK-B    | 1067983 | Berkshire Hathaway Inc.      | Finance            |     69 | 2009-09-30     | 2026-09-30   |         105.65 |         1097.95 |

---

## 4. Point-in-Time Enrichment Metric Coverage

Strictly Point-in-Time enforcement: `filed <= row['filed']`, `0 < (filed - end).days <= 130`.

| column       |   non_null_rows | coverage_pct   |   positive_rows |
|:-------------|----------------:|:---------------|----------------:|
| buyback_q    |          39,211 | 58.66%         |          31,382 |
| buyback_ttm  |          32,448 | 48.54%         |          31,276 |
| div_q        |          40,488 | 60.57%         |          39,035 |
| div_ttm      |          36,637 | 54.80%         |          36,464 |
| inventory    |          37,380 | 55.92%         |          37,367 |
| ar           |          51,688 | 77.32%         |          51,645 |
| deferred_rev |          31,253 | 46.75%         |          30,802 |
| rd           |          23,324 | 34.89%         |          23,270 |
| sbc          |          58,378 | 87.33%         |          57,778 |

---

## 5. Market Cap Source Calibration Distribution

| mcap_source      |   row_count | percentage   |
|:-----------------|------------:|:-------------|
| sec_shares       |       56810 | 84.98%       |
| sec_public_float |        5729 | 8.57%        |
| price_anchored   |        4311 | 6.45%        |

---

## 6. Strict Zero-Lookahead & Quality Guarantees

1. **Zero Future Information**: Every fundamental metric (including cash flow derives, balance sheet metrics, buybacks, and dividends) was sourced exclusively from filings where `filed <= row['filed']`.
2. **Multi-Class Fairness**: Eliminated artificial dilution and missing-class undervaluation for multi-share-class capital structures (`V`, `SYM`, `TKO`, `RDDT`, `STZ`, `ERIE`, `BKR`, `FOXA`, `BRK-B`).
3. **Permanent Storage**: All cache artifacts reside in `/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_fundamentals_30y_permanent/raw_sec_cache/companyfacts_gz`, completely detached from transient `/tmp` directories.
