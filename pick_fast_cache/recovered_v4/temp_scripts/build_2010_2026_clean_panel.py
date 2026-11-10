import os, json, glob, math
import pandas as pd
import numpy as np
import yfinance as yf

CACHE = "/tmp/sec_frames_cache"
PRICE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/prices"

# 1. Fetch SPY full history 1995-2026 via yfinance for exact benchmark excess returns (D15)
spy_hist = yf.Ticker("SPY").history(start="1995-01-01", end="2026-10-30", auto_adjust=True)
spy_s = spy_hist["Close"]
spy_s.index = pd.to_datetime(spy_s.index).tz_localize(None)
spy_s = spy_s.sort_index()
print(f"SPY loaded: {spy_s.index.min().date()} to {spy_s.index.max().date()}, rows={len(spy_s)}")

# 2. Load CIK <-> Ticker map
with open(os.path.join(CACHE, "company_tickers.json")) as f:
    tj = json.load(f)
cik_to_ticker = {}
ticker_to_cik = {}
for v in tj.values():
    c = int(v["cik_str"])
    tk = v["ticker"].upper()
    if c not in cik_to_ticker:
        cik_to_ticker[c] = tk
    ticker_to_cik[tk] = c

# Add well-known delisted/acquired CIK->ticker labels so human audit is crystal clear
KNOWN_DELISTED = {
    815094: "ABMD",     # Abiomed (acq by JNJ Nov 2022 for $16.6B)
    899866: "ALXN",     # Alexion (acq by AZN Jul 2021 for $39B)
    816284: "CELG",     # Celgene (acq by BMY Nov 2019 for $74B)
    1385867: "COUP",    # Coupa Software (acq by Thoma Bravo Feb 2023 for $8B)
    1764925: "WORK",    # Slack (acq by CRM Jul 2021 for $27.7B)
    1353283: "SPLK",    # Splunk (acq by CSCO Mar 2024 for $28B)
    1642545: "SWAV",    # Shockwave Medical (acq by JNJ May 2024 for $13.1B)
    1060736: "SGEN",    # Seagen (acq by PFE Dec 2023 for $43B)
    1463172: "ZEN",     # Zendesk (taken private Nov 2022 for $10.2B)
    1689923: "AYX",     # Alteryx (taken private Mar 2024)
    1639825: "PTON",    # Peloton
    1590895: "LVGO",    # Livongo Health (merged into TDOC Oct 2020 for $18.5B!)
    1477294: "HZNP",    # Horizon Therapeutics (acq by AMGN Oct 2023 for $27.8B)
    1527590: "CTLT",    # Catalent
    1783879: "SIVB",    # SVB Financial
    1288776: "GOOG_OLD",
}
for c, tk in KNOWN_DELISTED.items():
    if c not in cik_to_ticker:
        cik_to_ticker[c] = tk

# 3. Load SEC XBRL annual flows & instants (2009-2025)
def load_flow(tags, years=range(2009, 2026)):
    out = {}
    names = {}
    for y in years:
        for tag in reversed(tags):
            fn = os.path.join(CACHE, f"us-gaap__{tag}__CY{y}.json")
            if not os.path.exists(fn): continue
            with open(fn) as f:
                data = json.load(f).get("data", [])
            for r in data:
                cik = r["cik"]
                val = r.get("val")
                if val is None: continue
                names[cik] = r.get("entityName", names.get(cik, ""))
                prev = out.get((cik, y))
                if prev is None or (val > 0 and prev[0] > 0 and val > prev[0] * 1.3):
                    out[(cik, y)] = (float(val), r.get("end", ""))
    return out, names

REV_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "SalesRevenueServicesNet",
]
rev_panel, name_map = load_flow(REV_TAGS)
gp_panel, _ = load_flow(["GrossProfit"])
cor_panel, _ = load_flow(["CostOfRevenue", "CostOfGoodsAndServicesSold"])
op_panel, _ = load_flow(["OperatingIncomeLoss"])
ni_panel, _ = load_flow(["NetIncomeLoss"])
ocf_panel, _ = load_flow(["NetCashProvidedByUsedInOperatingActivities"])
capex_panel, _ = load_flow(["PaymentsToAcquirePropertyPlantAndEquipment"])
sbc_panel, _ = load_flow(["ShareBasedCompensation"])

def load_instant(tax, tag, qs=("Q1I", "Q2I", "Q3I", "Q4I"), years=range(2009, 2026), agg="last"):
    out = {}
    for y in years:
        for q in qs:
            fn = os.path.join(CACHE, f"{tax}__{tag}__CY{y}{q}.json")
            if not os.path.exists(fn): continue
            with open(fn) as f:
                data = json.load(f).get("data", [])
            for r in data:
                cik = r["cik"]
                val = r.get("val")
                if val is None: continue
                if cik not in name_map and r.get("entityName"):
                    name_map[cik] = r["entityName"]
                prev = out.get((cik, y))
                if prev is None or (agg == "max" and val > prev[0]) or (agg == "last" and r.get("end", "") >= prev[1]):
                    out[(cik, y)] = (float(val), r.get("end", ""))
    return out

eq_panel = load_instant("us-gaap", "StockholdersEquity", ("Q4I", "Q1I"))
assets_panel = load_instant("us-gaap", "Assets", ("Q4I", "Q1I"))
cash_panel = load_instant("us-gaap", "CashAndCashEquivalentsAtCarryingValue", ("Q4I", "Q1I"))
debt_panel = load_instant("us-gaap", "LongTermDebtNoncurrent", ("Q4I", "Q1I"))
float_panel = load_instant("dei", "EntityPublicFloat", ("Q1I", "Q2I", "Q3I", "Q4I"), range(2010, 2026), agg="max")

# Merge old GOOG CIK 1288776 (2009-2014) into Alphabet CIK 1652044 so longitudinal series is unbroken!
for d in [rev_panel, gp_panel, cor_panel, op_panel, ni_panel, ocf_panel, capex_panel, sbc_panel, eq_panel, assets_panel, cash_panel, debt_panel, float_panel]:
    for y in range(2009, 2016):
        if (1288776, y) in d and (1652044, y) not in d:
            d[(1652044, y)] = d[(1288776, y)]

# Load 2026H1 vs 2025H1 quarterly rev
rev_q = {}
for per in ["CY2025Q1", "CY2025Q2", "CY2026Q1", "CY2026Q2"]:
    for tag in ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"]:
        fn = os.path.join(CACHE, f"us-gaap__{tag}__{per}.json")
        if not os.path.exists(fn): continue
        with open(fn) as f:
            for r in json.load(f).get("data", []):
                rev_q[(r["cik"], per)] = max(rev_q.get((r["cik"], per), 0.0), float(r["val"]))

# Load us_price_db universe & prices
univ_df = pd.read_csv("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/universe.csv")
cur_mcap_by_ticker = dict(zip(univ_df["ticker"].str.upper(), univ_df["market_cap"]))
sector_by_ticker = dict(zip(univ_df["ticker"].str.upper(), univ_df["sector"]))
ind_by_ticker = dict(zip(univ_df["ticker"].str.upper(), univ_df["industry"]))

price_cache = {}
def get_px(tk):
    if not tk: return None
    if tk in price_cache: return price_cache[tk]
    fp = os.path.join(PRICE_DIR, f"{tk}.parquet")
    if os.path.exists(fp):
        df = pd.read_parquet(fp)
        s = df["adj_close"] if "adj_close" in df.columns else df["close"]
        s.index = pd.to_datetime(s.index).tz_localize(None)
        s = s.sort_index()
        price_cache[tk] = s
        return s
    price_cache[tk] = None
    return None

def px_at(s, dt_str):
    if s is None or not dt_str: return None
    dt = pd.Timestamp(dt_str)
    sub = s.loc[dt - pd.Timedelta(days=10) : dt + pd.Timedelta(days=10)]
    if sub.empty: return None
    sub_before = sub.loc[:dt]
    return float(sub_before.iloc[-1]) if not sub_before.empty else float(sub.iloc[0])

# Compute clean Market Cap at FY_end (point-in-time)
# Priority:
# 1) For active tickers in us_price_db: anchor on SEC EntityPublicFloat in a clean recent year (or cur_mcap if dual-class like META/GOOGL/SNOW/PLTR/DASH/ABNB) and scale by split-adjusted price ratio, OR use EntityPublicFloat directly when Float >= 0.80 * price-implied mcap!
# Wait: even cleaner — let's check both Float-scaled Year-End Market Cap AND Price-Implied Total Market Cap, while strictly requiring Assets >= $500M so tiny unit-typo shells are 100% excluded!

records = []
all_ciks_years = set(float_panel.keys())
for tk, mc in cur_mcap_by_ticker.items():
    if mc >= 5e9 and tk in ticker_to_cik:
        c = ticker_to_cik[tk]
        for y in range(2010, 2026):
            if (c, y) in rev_panel:
                all_ciks_years.add((c, y))

# Exclude ADRs of foreign non-US companies if we want pure US stocks? Wait: Buwen said "美股两万多只，20B以上市值的" -> US-listed stocks (let's flag ADRs/REITs so we can check with & without REITs/ADRs!).
for (cik, y) in sorted(all_ciks_years):
    if cik == 1288776: continue  # merged into 1652044
    r0 = rev_panel.get((cik, y))
    r_1 = rev_panel.get((cik, y - 1))
    if not r0 or not r_1: continue
    rev_t, fy_end = r0
    rev_t1, _ = r_1
    if rev_t < 250e6 or rev_t1 < 100e6: continue  # commercial revenue base
    assets_t = assets_panel.get((cik, y), (None, ""))[0]
    if assets_t is not None and assets_t < 400e6: continue  # eliminates small-cap 1000x XBRL float typos!

    tk = cik_to_ticker.get(cik, "")
    s = get_px(tk)

    fl_entry = float_panel.get((cik, y))
    fval, fend = fl_entry if fl_entry else (None, "")

    # Price-implied total mcap at fy_end from latest mcap
    px_imp_ye = None
    if tk in cur_mcap_by_ticker and s is not None and len(s) > 0:
        p_ye = px_at(s, fy_end)
        p_now = float(s.iloc[-1])
        if p_ye and p_now > 0:
            # Moderate 2%/yr historical share dilution discount so we don't overstate past mcap from today's diluted share count
            px_imp_ye = cur_mcap_by_ticker[tk] * (p_ye / p_now) / ((1.02) ** max(0, 2026 - y))

    # Clean fval against unit typos
    fl_ye = None
    if fval is not None and fval > 0:
        max_cap = 700e9 if y <= 2017 else (2800e9 if y <= 2022 else 5600e9)
        clean_f = fval
        if px_imp_ye is not None and px_imp_ye > 0:
            if clean_f / px_imp_ye > 25:  # XBRL 1000x or 100x unit typo (e.g. SailPoint, GOLD.COM, Roku 2018, Steven Madden)
                clean_f = None
        else:
            # Not in us_price_db (e.g. delisted or smaller today): check Assets & Revenue sanity!
            ref_sz = assets_t if assets_t else rev_t
            if clean_f > max_cap or (clean_f / ref_sz > 35):
                # Check if known biotech/software delisted or unit typo: no $20B+ company has Float > 35x Total Assets!
                # Even SNOW at 130x P/S had $5.9B cash/assets on $78B mcap (= 13x Assets)!
                clean_f = None

        if clean_f is not None:
            if s is not None and fend and fy_end:
                pf = px_at(s, fend)
                py = px_at(s, fy_end)
                if pf and py and pf > 0:
                    fl_ye = clean_f * (py / pf)
                else:
                    fl_ye = clean_f
            else:
                fl_ye = clean_f

    # Combine fl_ye and px_imp_ye (use max if dual-class founder shares like META/SNOW/PLTR/GOOGL where px_imp_ye > fl_ye, provided both are sane)
    if fl_ye is not None and px_imp_ye is not None:
        if 0.35 <= fl_ye / px_imp_ye <= 1.25:
            mcap = max(fl_ye, px_imp_ye)
        else:
            mcap = fl_ye if fl_ye <= px_imp_ye * 2.5 else px_imp_ye
    elif fl_ye is not None:
        mcap = fl_ye
    elif px_imp_ye is not None:
        mcap = px_imp_ye
    else:
        continue

    if mcap < 20e9:
        continue

    g0 = rev_t / rev_t1 - 1.0
    ps = mcap / rev_t

    # Profitability / ROE / ROIC at year t
    gp_t = gp_panel.get((cik, y), (None, ""))[0]
    if gp_t is None and (cik, y) in cor_panel:
        gp_t = rev_t - cor_panel[(cik, y)][0]
    gm_t = gp_t / rev_t if (gp_t is not None and rev_t > 0) else np.nan

    op_t = op_panel.get((cik, y), (np.nan, ""))[0]
    ni_t = ni_panel.get((cik, y), (np.nan, ""))[0]
    ocf_t = ocf_panel.get((cik, y), (np.nan, ""))[0]
    capx_t = capex_panel.get((cik, y), (0.0, ""))[0]
    fcf_t = ocf_t - capx_t if not np.isnan(ocf_t) else np.nan

    eq_t = eq_panel.get((cik, y), (np.nan, ""))[0]
    eq_t1 = eq_panel.get((cik, y - 1), (eq_t, ""))[0]
    avg_eq = np.nanmean([eq_t, eq_t1]) if not (np.isnan(eq_t) and np.isnan(eq_t1)) else np.nan
    roe_t = (ni_t / avg_eq) if (not np.isnan(ni_t) and not np.isnan(avg_eq) and avg_eq > 50e6) else np.nan

    cash_t = cash_panel.get((cik, y), (0.0, ""))[0]
    debt_t = debt_panel.get((cik, y), (0.0, ""))[0]
    ic_t = (eq_t + debt_t - min(cash_t, (eq_t + debt_t) * 0.85)) if (not np.isnan(eq_t) and (eq_t + debt_t) > 0) else np.nan
    nopat_t = op_t * (0.79 if op_t > 0 else 1.0) if not np.isnan(op_t) else np.nan
    roic_t = (nopat_t / ic_t) if (not np.isnan(nopat_t) and not np.isnan(ic_t) and ic_t > 50e6) else np.nan

    # Forward Fundamental Revenue Growth (Y+1, Y+2, Y+3, Y+5)
    def get_rev(yr):
        v = rev_panel.get((cik, yr))
        return v[0] if v else np.nan

    rev_p1 = get_rev(y + 1)
    rev_p2 = get_rev(y + 2)
    rev_p3 = get_rev(y + 3)
    rev_p5 = get_rev(y + 5)

    # For y == 2025, check 2026H1 YoY if available
    g_2026h1 = np.nan
    if y == 2025:
        h1_26 = rev_q.get((cik, "CY2026Q1"), 0) + rev_q.get((cik, "CY2026Q2"), 0)
        h1_25 = rev_q.get((cik, "CY2025Q1"), 0) + rev_q.get((cik, "CY2025Q2"), 0)
        if rev_q.get((cik, "CY2026Q1")) and rev_q.get((cik, "CY2026Q2")) and h1_25 > 0:
            g_2026h1 = h1_26 / h1_25 - 1.0

    g_p1 = (rev_p1 / rev_t - 1.0) if (not np.isnan(rev_p1) and rev_t > 0) else g_2026h1
    g_p2 = (rev_p2 / rev_p1 - 1.0) if (not np.isnan(rev_p2) and not np.isnan(rev_p1) and rev_p1 > 0) else np.nan
    g_p3 = (rev_p3 / rev_p2 - 1.0) if (not np.isnan(rev_p3) and not np.isnan(rev_p2) and rev_p2 > 0) else np.nan
    cagr_3y = ((rev_p3 / rev_t) ** (1/3) - 1.0) if (not np.isnan(rev_p3) and rev_p3 > 0 and rev_t > 0) else np.nan
    cagr_5y = ((rev_p5 / rev_t) ** (1/5) - 1.0) if (not np.isnan(rev_p5) and rev_p5 > 0 and rev_t > 0) else np.nan

    # Y+3 Operating Margin & ROE
    op_p3 = op_panel.get((cik, y + 3), (np.nan, ""))[0]
    opm_t = op_t / rev_t if not np.isnan(op_t) else np.nan
    opm_p3 = op_p3 / rev_p3 if (not np.isnan(op_p3) and not np.isnan(rev_p3) and rev_p3 > 0) else np.nan
    fcfm_t = fcf_t / rev_t if not np.isnan(fcf_t) else np.nan

    # Forward Stock Returns (Point-in-time: enter 60 days after FY_end so 10-K is public! Zero lookahead!)
    ret_1y = ret_3y = spy_1y = spy_3y = np.nan
    if s is not None and fy_end: