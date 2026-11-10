                    best[key] = (fl, tidx, val)
    return {k: v[2] for k, v in best.items()}

def match_end(lkp, target_end, bucket, tol_days=14):
    if (target_end, bucket) in lkp:
        return lkp[(target_end, bucket)], target_end
    best_e, best_d = None, tol_days + 1
    for (en, b) in lkp:
        if b != bucket: continue
        dd = abs((en - target_end).days)
        if dd <= tol_days and dd < best_d:
            best_d = dd
            best_e = en
    return (lkp[(best_e, bucket)], best_e) if best_e else (None, None)

def safe_minus_years(d, yrs=1):
    y = d.year - yrs
    m = d.month
    day = min(d.day, 28) if m == 2 else d.day
    return date(y, m, day)

def get_ttm(lkp, q_end, is_fy, fy_ends):
    if is_fy:
        v, _ = match_end(lkp, q_end, "FY", tol_days=14)
        if v is not None:
            return v
    prev_fy = None
    for fye in reversed(fy_ends):
        gap = (q_end - fye).days
        if 60 <= gap <= 320:
            prev_fy = fye
            break
    if prev_fy is not None:
        gap = (q_end - prev_fy).days
        ytd_b = "1Q" if gap <= 122 else ("2Q" if gap <= 215 else "3Q")
        ytd_cur, _ = match_end(lkp, q_end, ytd_b, tol_days=14)
        fy_prev, _ = match_end(lkp, prev_fy, "FY", tol_days=14)
        ytd_prev, _ = match_end(lkp, safe_minus_years(q_end, 1), ytd_b, tol_days=18)
        if ytd_cur is not None and fy_prev is not None and ytd_prev is not None:
            return ytd_cur + fy_prev - ytd_prev
    # Fallback: sum of 4 consecutive 1Q buckets
    total = 0.0
    cur_e = q_end
    for _ in range(4):
        vq, matched_e = match_end(lkp, cur_e, "1Q", tol_days=18)
        if vq is None: return None
        total += vq
        cur_e = (pd.Timestamp(matched_e) - pd.Timedelta(days=91)).date()
    return total

rows = []
for cik, info in sorted(META.items()):
    px_fp = f"/tmp/pit_sec_cache/prices/CIK{cik:010d}.parquet"
    facts_fp = f"/tmp/pit_sec_cache/facts/CIK{cik:010d}.json"
    if not (os.path.exists(px_fp) and os.path.exists(facts_fp)): continue
    
    px_df = pd.read_parquet(px_fp).sort_index()
    px_df = px_df[(px_df["raw_close"] > 0) & (px_df["adj_close"] > 0)]
    if len(px_df) < 15: continue
    px_dates = px_df.index.values
    raw_arr = px_df["raw_close"].values
    adj_arr = px_df["adj_close"].values

    d = json.load(open(facts_fp))
    us = d.get("facts", {}).get("us-gaap", {})
    dei = d.get("facts", {}).get("dei", {})

    rev_raw = extract_flow(us, REV_TAGS)
    if not rev_raw: continue

    # Deduplicate quarterly filing triggers: group by q_end, prefer is_fy=True if FY ends on q_end, take earliest valid filing date
    q_events = {}
    for fl, en, b, val, tidx in rev_raw:
        if en.year < 2010 or en > date(2026, 10, 31): continue
        lag = (parse_dt(fl) - en).days
        if lag < 2 or lag > 125: continue
        is_fy = (b == "FY")
        cur = q_events.get(en)
        if cur is None:
            q_events[en] = [is_fy, fl]
        else:
            if is_fy and not cur[0]:
                q_events[en] = [True, fl]
            elif is_fy == cur[0] and fl < cur[1]:
                q_events[en][1] = fl

    # Merge q_ends within 20 days (e.g. 52/53 week comparative quirk)
    sorted_q = sorted(q_events.items(), key=lambda kv: kv[0])
    dedup_q = []
    for en, (is_fy, fl) in sorted_q:
        if dedup_q and (en - dedup_q[-1][0]).days < 25:
            if is_fy and not dedup_q[-1][1]:
                dedup_q[-1] = (en, is_fy, fl)
        else:
            dedup_q.append((en, is_fy, fl))

    gp_raw = extract_flow(us, GP_TAGS)
    cogs_raw = extract_flow(us, COGS_TAGS)
    opinc_raw = extract_flow(us, OPINC_TAGS)
    ce_raw = extract_flow(us, COSTS_EXP_TAGS)
    opex_raw = extract_flow(us, OPEX_TAGS)
    rd_raw = extract_flow(us, RD_TAGS)
    sga_raw = extract_flow(us, SGA_TAGS)
    sm_raw = extract_flow(us, SM_TAGS)
    ga_raw = extract_flow(us, GA_TAGS)
    ebt_raw = extract_flow(us, EBT_TAGS)
    nonop_raw = extract_flow(us, NONOP_TAGS)

    # Extract share counts & public float & assets for PIT Market Cap
    sh_records = []
    for src, obj_d, tag in [
        ("dei", dei, "EntityCommonStockSharesOutstanding"),
        ("gaap_cs", us, "CommonStockSharesOutstanding"),
        ("basic", us, "WeightedAverageNumberOfSharesOutstandingBasic"),
    ]:
        for u, arr in obj_d.get(tag, {}).get("units", {}).items():
            if "share" not in u.lower(): continue
            for x in arr:
                en, fl, val, fm = x.get("end"), x.get("filed"), x.get("val"), x.get("form")
                if en and fl and val and val > 0 and fm in ("10-Q", "10-Q/A", "10-K", "10-K/A", "20-F", "20-F/A"):
                    # For weighted basic, prefer single-quarter or FY matching end
                    st = x.get("start")
                    if src == "basic" and st:
                        dd = (parse_dt(en) - parse_dt(st)).days
                        if not (70 <= dd <= 115 or 340 <= dd <= 385): continue
                    sh_records.append((fl, parse_dt(en), src, float(val)))

    flt_records = []
    for x in dei.get("EntityPublicFloat", {}).get("units", {}).get("USD", []):
        en, fl, val = x.get("end"), x.get("filed"), x.get("val")
        if en and fl and val and 0 < val < 6e12:
            flt_records.append((fl, parse_dt(en), float(val)))

    ast_records = []
    for x in us.get("Assets", {}).get("units", {}).get("USD", []):
        en, fl, val = x.get("end"), x.get("filed"), x.get("val")
        if en and fl and val and val > 0:
            ast_records.append((fl, parse_dt(en), float(val)))

    sic = info["sic"]
    is_hc = ((sic in PURE_HC_SICS) or (cik in EXTRA_HC_CIKS)) and (cik not in NON_HC_EXCLUDE_CIKS)

    prev_valid_gm = None
    for q_end, is_fy, fl in dedup_q:
        # Find entry_date: first trading day strictly AFTER fl
        f_ts = np.datetime64(fl)
        idx0 = int(np.searchsorted(px_dates, f_ts, side="right"))
        if idx0 >= len(px_dates): continue
        entry_ts = pd.Timestamp(px_dates[idx0])
        if (entry_ts - pd.Timestamp(fl)).days > 14: continue

        rev_lkp = build_pit_lkp(rev_raw, fl, is_rev=True)
        fy_ends = sorted([en for (en, b) in rev_lkp if b == "FY" and en <= q_end])
        rev_ttm = get_ttm(rev_lkp, q_end, is_fy, [e for e in fy_ends if e < q_end])
        if rev_ttm is None or rev_ttm < 100e6: continue # Hard requirement: TTM rev >= $100M!

        q_prev_yr = safe_minus_years(q_end, 1)
        rev_ttm_prev = get_ttm(rev_lkp, q_prev_yr, is_fy, [e for e in fy_ends if e < q_prev_yr])
        if rev_ttm_prev is None or rev_ttm_prev < 20e6: continue
        yoy_ttm = rev_ttm / rev_ttm_prev - 1.0

        # Single quarter YoY as auxiliary metric
        q1_cur, _ = match_end(rev_lkp, q_end, "1Q", tol_days=14)
        q1_prv, _ = match_end(rev_lkp, q_prev_yr, "1Q", tol_days=18)
        yoy_1q = (q1_cur / q1_prv - 1.0) if (q1_cur and q1_prv and q1_prv >= 5e6) else np.nan

        # Gross Margin & Operating Margin waterfall (strictly PIT: filed <= fl)
        gp_ttm = get_ttm(build_pit_lkp(gp_raw, fl), q_end, is_fy, [e for e in fy_ends if e < q_end])
        cogs_lkp = build_pit_lkp(cogs_raw, fl)
        cogs_ttm = get_ttm(cogs_lkp, q_end, is_fy, [e for e in fy_ends if e < q_end])
        has_cogs_tag = (cogs_ttm is not None and cogs_ttm > 0)

        gm = None
        gm_src = "missing"
        if gp_ttm is not None and -1.0 <= gp_ttm / rev_ttm <= 0.995:
            gm = gp_ttm / rev_ttm; gm_src = "GrossProfit"
        elif cogs_ttm is not None and 0 < cogs_ttm <= rev_ttm * 2.0:
            gm = (rev_ttm - cogs_ttm) / rev_ttm; gm_src = "Rev_minus_COGS"

        opinc_ttm = get_ttm(build_pit_lkp(opinc_raw, fl), q_end, is_fy, [e for e in fy_ends if e < q_end])
        ce_ttm = get_ttm(build_pit_lkp(ce_raw, fl), q_end, is_fy, [e for e in fy_ends if e < q_end])
        rd_ttm = get_ttm(build_pit_lkp(rd_raw, fl), q_end, is_fy, [e for e in fy_ends if e < q_end])
        sga_ttm = get_ttm(build_pit_lkp(sga_raw, fl), q_end, is_fy, [e for e in fy_ends if e < q_end])
        if sga_ttm is None:
            sm_v = get_ttm(build_pit_lkp(sm_raw, fl), q_end, is_fy, [e for e in fy_ends if e < q_end])
            ga_v = get_ttm(build_pit_lkp(ga_raw, fl), q_end, is_fy, [e for e in fy_ends if e < q_end])
            if sm_v is not None or ga_v is not None:
                sga_ttm = (sm_v or 0.0) + (ga_v or 0.0)

        if opinc_ttm is None and ce_ttm is not None:
            opinc_ttm = rev_ttm - ce_ttm
        if opinc_ttm is None:
            ebt_v = get_ttm(build_pit_lkp(ebt_raw, fl), q_end, is_fy, [e for e in fy_ends if e < q_end])
            nonop_v = get_ttm(build_pit_lkp(nonop_raw, fl), q_end, is_fy, [e for e in fy_ends if e < q_end])
            if ebt_v is not None:
                opinc_ttm = ebt_v - (nonop_v or 0.0)

        if gm is None and opinc_ttm is not None:
            opex_v = get_ttm(build_pit_lkp(opex_raw, fl), q_end, is_fy, [e for e in fy_ends if e < q_end])
            if opex_v is not None:
                cand_gp = opinc_ttm + opex_v
                if 0.01 * rev_ttm < cand_gp < 0.99 * rev_ttm and abs(cand_gp - rev_ttm) / rev_ttm > 0.02:
                    gm = cand_gp / rev_ttm; gm_src = "OpInc_plus_OpEx"

        if gm is None and ce_ttm is not None and sga_ttm is not None:
            imp_cogs = ce_ttm - (rd_ttm or 0.0) - sga_ttm
            if 0 <= imp_cogs <= rev_ttm * 1.8:
                gm = (rev_ttm - imp_cogs) / rev_ttm; gm_src = "Residual_CE_RD_SGA"

        if gm is None and opinc_ttm is not None and sga_ttm is not None and (rd_ttm is not None):
            # GP = OpInc + R&D + SGA
            cand_gp = opinc_ttm + rd_ttm + sga_ttm
            if 0.01 * rev_ttm <= cand_gp <= 0.995 * rev_ttm:
                gm = cand_gp / rev_ttm; gm_src = "OpInc_RD_SGA"

        if gm is not None:
            prev_valid_gm = (q_end, gm)
        elif prev_valid_gm is not None and (q_end - prev_valid_gm[0]).days <= 200:
            gm = prev_valid_gm[1]; gm_src = "PIT_Carry1Q"

        opm = (opinc_ttm / rev_ttm) if (opinc_ttm is not None and -15.0 <= opinc_ttm / rev_ttm <= 0.98) else np.nan

        # Point-in-Time Market Cap at entry_ts
        p_adj_ent = float(adj_arr[idx0])
        p_raw_ent = float(raw_arr[idx0])

        # Helper to price a date near dt
        def px_near(dt_obj):
            ts64 = np.datetime64(dt_obj)
            ix = int(np.searchsorted(px_dates, ts64, side="right")) - 1
            if ix < 0: ix = 0
            if abs((pd.Timestamp(px_dates[ix]) - pd.Timestamp(dt_obj)).days) <= 15:
                return float(raw_arr[ix]), float(adj_arr[ix])
            return None, None

        # Float anchor (strictly filed <= fl)
        flt_vis = [x for x in flt_records if x[0] <= fl and x[1] <= entry_ts.date()]
        flt_scaled = None
        if flt_vis:
            _, f_end, f_val = max(flt_vis, key=lambda z: (z[1], z[0]))
            _, padj_f = px_near(f_end)
            if padj_f and padj_f > 0:
                flt_scaled = f_val * (p_adj_ent / padj_f)

        # Assets anchor (strictly filed <= fl)
        ast_vis = [x for x in ast_records if x[0] <= fl and x[1] <= entry_ts.date()]
        ast_latest = max(ast_vis, key=lambda z: (z[1], z[0]))[2] if ast_vis else None
        if flt_scaled and ast_latest and flt_scaled / ast_latest > 50 and flt_scaled / rev_ttm > 120:
            flt_scaled = None # XBRL 1000x float typo

        # Shares anchor (strictly filed <= fl, recent period >= q_end - 60d)