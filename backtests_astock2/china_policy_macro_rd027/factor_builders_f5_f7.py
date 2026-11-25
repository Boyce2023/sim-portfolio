#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD027 Wave 2A Factor Builders: F5 (Top Meetings Diff & Regulatory Events),
F6 (Sector Traffic Lights), F7 (8 Regime Gates x 28 Core Policy/Waterpool Factors).
Strictly PIT: event_date <= Friday_date (never reads post-event returns).
"""
import numpy as np
import pandas as pd


def _add(cols: dict, meta: list, name: str, ser: pd.Series, family: str, formula: str, source: str):
    cols[name] = ser.astype(float)
    meta.append({"factor": name, "family": family, "formula": formula, "source": source})


def _compute_window_pulses(
    wk_ns: np.ndarray,
    ev_ns: np.ndarray,
    values: np.ndarray,
    windows_days: list[int],
    taus_days: list[int],
) -> dict[str, np.ndarray]:
    """Causal backward window sums & exponential decay pulses for event_date <= Friday_date."""
    vals = np.asarray(values, dtype=float)
    diff_days = (wk_ns[:, None] - ev_ns[None, :]) / 86_400_000_000_000.0
    valid_past = diff_days >= 0.0
    out = {}
    for w in windows_days:
        m = valid_past & (diff_days <= float(w))
        out[f"w{w}"] = (m * vals[None, :]).sum(axis=1)
    for tau in taus_days:
        wt = np.where(valid_past, np.exp(-np.maximum(diff_days, 0.0) / float(tau)), 0.0)
        out[f"dec{tau}"] = (wt * vals[None, :]).sum(axis=1)
    return out


def build_f5_meetings_events(
    wk_dates: pd.DataFrame,
    p2_raw: pd.DataFrame,
    me_raw: pd.DataFrame,
    dmp_daily: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict]]:
    """F5_顶层会议diff与监管松紧 (~135 factors)."""
    cols, meta = {}, []
    fam = "F5_顶层会议diff与监管松紧"

    wk_ts = pd.to_datetime(wk_dates["date"])
    wk_ns = wk_ts.to_numpy(dtype="datetime64[ns]").astype(np.int64)

    p2 = p2_raw.sort_values("event_date").reset_index(drop=True).copy()
    p2["ev_ts"] = pd.to_datetime(p2["event_date"])
    p2_ns = p2["ev_ts"].to_numpy(dtype="datetime64[ns]").astype(np.int64)

    latest_cols = [
        "tone_monetary", "tone_fiscal", "tone_property", "tone_equity",
        "tone_deleveraging", "tone_growth_urgency", "macro_stance_score",
        "monetary_fiscal_sum", "equity_unmentioned_flag", "equity_strong_upgrade_flag",
        "property_easing_flag", "policy_constraint_flag", "off_schedule_flag",
        "first_mention_new_theme", "delta_monetary", "delta_fiscal", "delta_property",
        "delta_equity", "delta_deleveraging", "delta_growth_urgency",
        "delta_macro_stance", "delta_monetary_fiscal", "delta_yoy_stance",
        "delta_yoy_equity", "delta_yoy_monetary", "delta_yoy_property",
        "max_abs_delta", "upgrade_axis_cnt", "downgrade_axis_cnt",
        "is_upgrade_any", "is_downgrade_any", "is_equity_upgrade",
        "is_monetary_upgrade", "is_fiscal_upgrade", "is_property_upgrade",
        "surprise_shift", "surprise_direction",
    ]
    m_p2 = pd.merge_asof(
        pd.DataFrame({"date": wk_ts}).sort_values("date"),
        p2[["ev_ts"] + latest_cols].sort_values("ev_ts").drop_duplicates("ev_ts", keep="last"),
        left_on="date",
        right_on="ev_ts",
        direction="backward",
    )
    for c in latest_cols:
        _add(cols, meta, f"f5_p2_last_{c}", m_p2[c], fam, f"最近一次顶层会议:{c}", "pillar2_top_meetings_diff")

    diff_p2 = (wk_ns[:, None] - p2_ns[None, :]) / 86_400_000_000_000.0
    past_p2 = diff_p2 >= 0.0
    d_last_meet = np.where(past_p2, diff_p2, np.inf).min(axis=1)
    d_last_meet = np.where(np.isfinite(d_last_meet), d_last_meet, np.nan)
    _add(cols, meta, "f5_p2_days_since_meeting", pd.Series(d_last_meet, index=wk_dates.index), fam, "距最近顶层会议天数", "pillar2_top_meetings_diff")

    up_mask = (p2["delta_macro_stance"].to_numpy() >= 1)[None, :] & past_p2
    d_last_up = np.where(up_mask, diff_p2, np.inf).min(axis=1)
    d_last_up = np.where(np.isfinite(d_last_up), d_last_up, 365.0)
    _add(cols, meta, "f5_p2_days_since_upgrade", pd.Series(np.where(np.isfinite(d_last_meet), d_last_up, np.nan), index=wk_dates.index), fam, "距最近宏调升级天数", "pillar2_top_meetings_diff")

    p2_streams = {
        "delta_stance": p2["delta_macro_stance"].to_numpy(dtype=float),
        "delta_stance_pos": np.maximum(0.0, p2["delta_macro_stance"].to_numpy(dtype=float)),
        "delta_stance_neg": np.minimum(0.0, p2["delta_macro_stance"].to_numpy(dtype=float)),
        "delta_equity": p2["delta_equity"].to_numpy(dtype=float),
        "delta_monetary": p2["delta_monetary"].to_numpy(dtype=float),
        "delta_fiscal": p2["delta_fiscal"].to_numpy(dtype=float),
        "delta_property": p2["delta_property"].to_numpy(dtype=float),
        "f009_unmentioned": p2["equity_unmentioned_flag"].to_numpy(dtype=float),
        "surprise_pos": ((p2["surprise_shift"] == 1) & (p2["surprise_direction"] > 0)).to_numpy(dtype=float),
        "upgrade_any": p2["is_upgrade_any"].to_numpy(dtype=float),
    }
    for snm, vals in p2_streams.items():
        res = _compute_window_pulses(wk_ns, p2_ns, vals, [30, 90], [30, 60])
        for k, arr in res.items():
            arr_clean = np.where(np.isfinite(d_last_meet), arr, np.nan)
            _add(cols, meta, f"f5_p2_{snm}_{k}", pd.Series(arr_clean, index=wk_dates.index), fam, f"顶层会议{snm}窗口/衰减:{k}", "pillar2_top_meetings_diff")

    # Part B: master_events_v2 (strictly ex-ante metadata & flags, event_date <= Friday_date)
    me = me_raw.sort_values("event_date").reset_index(drop=True).copy()
    me["ev_ts"] = pd.to_datetime(me["event_date"])
    me_ns = me["ev_ts"].to_numpy(dtype="datetime64[ns]").astype(np.int64)
    hl = me["hard_levers_joined"].fillna("").astype(str)
    auth = me["authority_level"].fillna("").astype(str)
    verb = me["action_verb_stage"].fillna("").astype(str)
    venue = me["venue_type"].fillna("").astype(str)

    me_streams = {
        "all_events": np.ones(len(me), dtype=float),
        "hard_rescue": (
            (me["market_rescue_signal"] == 1)
            & ((verb == "HARD_ACTION_NOW") | (hl != "") | auth.isin(["HUIJIN_NATIONAL_TEAM", "PBOC_HARD_TOOL", "STATE_COUNCIL_EXEC", "POLITBURO", "CENTRAL_FIN_CONF", "FSDC_VICE_PREMIER"]))
        ).to_numpy(dtype=float),
        "slogan_only": (
            (verb == "ROUTINE_SLOGAN") & (me["market_rescue_signal"] == 1) & (hl == "")
        ).to_numpy(dtype=float),
        "routine_slogan": (verb == "ROUTINE_SLOGAN").to_numpy(dtype=float),
        "crackdown": (
            (me["speculation_fraud_crackdown"] == 1) | (me["quant_short_selling_tightening"] == 1)
            | hl.str.contains("DELISTING_CRACKDOWN|QUANT_SHORT_RULE")
        ).to_numpy(dtype=float),
        "exchange_surv": ((auth == "EXCHANGE_SURVEILLANCE") | (venue == "EXCHANGE_NOTICE")).to_numpy(dtype=float),
        "ipo_red_tighten": (
            (me["ipo_supply_tightening"] == 1) | (me["share_reduction_crackdown"] == 1)
            | hl.str.contains("IPO_PAUSE|REDUCTION_RULE")
        ).to_numpy(dtype=float),
        "long_cap_div": ((me["liquidity_long_term_capital"] == 1) | (me["dividend_buyback_push"] == 1)).to_numpy(dtype=float),
        "tech_ma_supp": ((me["tech_innovation_support"] == 1) | (me["ma_restructuring_support"] == 1)).to_numpy(dtype=float),
        "nt_pboc_hard": (
            auth.isin(["HUIJIN_NATIONAL_TEAM", "PBOC_HARD_TOOL", "FISCAL_SASAC"])
            | hl.str.contains("HUIJIN_BUY|PBOC_SFISF|STAMP_DUTY|FISCAL_CAPITAL_INJECT")
        ).to_numpy(dtype=float),
    }
    me_cache = {}
    for snm, vals in me_streams.items():
        res = _compute_window_pulses(wk_ns, me_ns, vals, [30, 60, 90], [30, 60])
        me_cache[snm] = res
        for k, arr in res.items():
            _add(cols, meta, f"f5_me_{snm}_{k}", pd.Series(arr, index=wk_dates.index), fam, f"证监会/监管事件{snm}:{k}", "master_events_v2")

    for win in ["w30", "w60", "w90", "dec60"]:
        _add(cols, meta, f"f5_me_rescue_minus_crackdown_{win}",
             pd.Series(me_cache["hard_rescue"][win] - me_cache["crackdown"][win], index=wk_dates.index),
             fam, f"硬救市减严监管净差:{win}", "master_events_v2")
        _add(cols, meta, f"f5_me_hard_minus_slogan_{win}",
             pd.Series(me_cache["hard_rescue"][win] - me_cache["slogan_only"][win], index=wk_dates.index),
             fam, f"硬救市减纯口号净差:{win}", "master_events_v2")

    dmp = dmp_daily.sort_values("date").reset_index(drop=True).copy()
    dmp["date"] = pd.to_datetime(dmp["date"])
    dmp["notices_halt_check_20d"] = dmp["notices_halt_check_cnt"].rolling(20, min_periods=5).sum()
    dmp["notices_sev_abn_20d"] = dmp["notices_sev_abn_cnt"].rolling(20, min_periods=5).sum()
    w_nt = wk_dates[["date"]].merge(
        dmp[["date", "notices_sev_abn_5d", "notices_reg_letter_5d", "notices_halt_check_20d", "notices_sev_abn_20d"]],
        on="date",
        how="left",
    )
    for c in ["notices_sev_abn_5d", "notices_reg_letter_5d", "notices_halt_check_20d", "notices_sev_abn_20d"]:
        _add(cols, meta, f"f5_{c}", w_nt[c], fam, f"交易所监管函/异动密度(2025+):{c}", "daily_market_panel_v2")

    return pd.DataFrame(cols, index=wk_dates.index), meta


def build_f6_traffic_lights(
    wk_dates: pd.DataFrame,
    p3_raw: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict]]:
    """F6_产业部委红绿灯脉冲 (~85 factors). Effective start 2008-09-05."""
    cols, meta = {}, []
    fam = "F6_产业部委红绿灯脉冲"

    wk_ts = pd.to_datetime(wk_dates["date"])
    wk_ns = wk_ts.to_numpy(dtype="datetime64[ns]").astype(np.int64)
    p3 = p3_raw.sort_values("event_date").reset_index(drop=True).copy()
    p3["ev_ts"] = pd.to_datetime(p3["event_date"])
    p3_ns = p3["ev_ts"].to_numpy(dtype="datetime64[ns]").astype(np.int64)

    first_p3_ns = p3_ns.min()
    active_mask = wk_ns >= first_p3_ns

    pol = p3["signal_polarity"].to_numpy(dtype=float)
    inten = p3["intensity"].to_numpy(dtype=float)
    stype = p3["signal_type"].astype(str)
    sec = p3["sector_code"].astype(str)

    tech_secs = {"NEW_ENERGY", "SEMI_HARDTECH", "TMT_AI_MEDIA", "DEFENSE_AERO"}
    val_secs = {"CENTRAL_SOE_DIV", "BANK", "REAL_ESTATE", "SUPPLY_CYCLICAL"}
    red_plat_secs = {"EDU_INTERNET", "PHARMA", "REAL_ESTATE"}

    streams = {
        "green_cnt": (pol == 1).astype(float),
        "green_int": np.where(pol == 1, inten, 0.0),
        "red_cnt": (pol == -1).astype(float),
        "red_int": np.where(pol == -1, inten, 0.0),
        "net_cnt": pol,
        "net_int": pol * inten,
        "sub_cnt": (stype == "GREEN_SUBSIDY_PLAN").astype(float),
        "sub_int": np.where(stype == "GREEN_SUBSIDY_PLAN", inten, 0.0),
        "dereg_cnt": (stype == "GREEN_DEREG_MA").astype(float),
        "dereg_int": np.where(stype == "GREEN_DEREG_MA", inten, 0.0),
        "supcut_cnt": (stype == "GREEN_SUPPLY_CUT").astype(float),
        "crack_cnt": (stype == "RED_CRACKDOWN_BAN").astype(float),
        "crack_int": np.where(stype == "RED_CRACKDOWN_BAN", inten, 0.0),
        "cap_cnt": (stype == "RED_PRICE_CAP_TAX").astype(float),
        "green_tech_cnt": ((pol == 1) & sec.isin(tech_secs)).astype(float),
        "green_tech_int": np.where((pol == 1) & sec.isin(tech_secs), inten, 0.0),
        "green_val_cnt": ((pol == 1) & sec.isin(val_secs)).astype(float),
        "green_val_int": np.where((pol == 1) & sec.isin(val_secs), inten, 0.0),
        "red_plat_cnt": ((pol == -1) & sec.isin(red_plat_secs)).astype(float),
        "red_plat_int": np.where((pol == -1) & sec.isin(red_plat_secs), inten, 0.0),
    }

    cache = {}
    for snm, vals in streams.items():
        if snm in {"green_cnt", "green_int", "red_cnt", "red_int", "net_cnt", "net_int"}:
            res = _compute_window_pulses(wk_ns, p3_ns, vals, [30, 60, 120, 250], [30, 60, 120])
        else:
            res = _compute_window_pulses(wk_ns, p3_ns, vals, [60, 120, 250], [])
        cache[snm] = res
        for k, arr in res.items():
            arr_clean = np.where(active_mask, arr, np.nan)
            _add(cols, meta, f"f6_{snm}_{k}", pd.Series(arr_clean, index=wk_dates.index), fam, f"部委产业红绿灯{snm}:{k}", "pillar3_sector_traffic_lights")

    for win in ["w60", "w120", "w250"]:
        _add(cols, meta, f"f6_green_tech_minus_val_cnt_{win}",
             pd.Series(np.where(active_mask, cache["green_tech_cnt"][win] - cache["green_val_cnt"][win], np.nan), index=wk_dates.index),
             fam, f"科技绿灯减价值绿灯计数:{win}", "pillar3_sector_traffic_lights")
        _add(cols, meta, f"f6_green_tech_minus_val_int_{win}",
             pd.Series(np.where(active_mask, cache["green_tech_int"][win] - cache["green_val_int"][win], np.nan), index=wk_dates.index),
             fam, f"科技绿灯减价值绿灯强度:{win}", "pillar3_sector_traffic_lights")

    diff_p3 = (wk_ns[:, None] - p3_ns[None, :]) / 86_400_000_000_000.0
    past_p3 = diff_p3 >= 0.0
    d_green = np.where(past_p3 & (pol[None, :] == 1), diff_p3, np.inf).min(axis=1)
    d_red = np.where(past_p3 & (pol[None, :] == -1), diff_p3, np.inf).min(axis=1)
    _add(cols, meta, "f6_days_since_green", pd.Series(np.where(active_mask & np.isfinite(d_green), d_green, np.nan), index=wk_dates.index), fam, "距最近部委绿灯天数", "pillar3_sector_traffic_lights")
    _add(cols, meta, "f6_days_since_red", pd.Series(np.where(active_mask & np.isfinite(d_red), d_red, np.nan), index=wk_dates.index), fam, "距最近部委红灯天数", "pillar3_sector_traffic_lights")

    sec_codes = sorted(sec.unique())
    for win_d in [120, 250]:
        m_win = past_p3 & (diff_p3 <= float(win_d))
        sec_shares_sq = np.zeros(len(wk_ns))
        tot_g = np.maximum(cache["green_cnt"][f"w{win_d}"], 1e-9)
        for sc in sec_codes:
            sc_m = m_win & ((pol == 1) & (sec == sc)).to_numpy()[None, :]
            sec_shares_sq += (sc_m.sum(axis=1) / tot_g) ** 2
        hhi = np.where(active_mask & (cache["green_cnt"][f"w{win_d}"] > 0), sec_shares_sq, np.where(active_mask, 0.0, np.nan))
        _add(cols, meta, f"f6_green_hhi_w{win_d}", pd.Series(hhi, index=wk_dates.index), fam, f"近{win_d}日绿灯行业集中度HHI", "pillar3_sector_traffic_lights")
        g_share = np.where(active_mask, cache["green_cnt"][f"w{win_d}"] / np.maximum(cache["green_cnt"][f"w{win_d}"] + cache["red_cnt"][f"w{win_d}"], 1.0), np.nan)
        _add(cols, meta, f"f6_green_share_w{win_d}", pd.Series(g_share, index=wk_dates.index), fam, f"近{win_d}日绿灯占比", "pillar3_sector_traffic_lights")

    return pd.DataFrame(cols, index=wk_dates.index), meta


def build_f7_regime_interactions(
    df_all: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    """
    F7_8大门控体制×核心政策水池交互 (8 gates x 28 core factors = 224 factors).
    Also returns the 8 physical gate columns for downstream hypothesis & Jordà LP checks.
    """
    cols, meta = {}, []
    fam = "F7_8大门控体制×核心政策水池交互"

    g1 = ((df_all["f2_bench_dd_250d"] <= -0.20) | (df_all["f2_pct_above_ma200"] <= 0.15) | (df_all["f2_pct_new_low_250d"] >= 0.25)).astype(float)
    g2 = (df_all["wp_drain_total_mcap_pct3y"] <= 0.25).astype(float).where(df_all["wp_drain_total_mcap_pct3y"].notna(), np.nan)
    g3 = ((df_all["f2_erp_csi300_pct_3y"] >= 0.75) | (df_all["f2_erp_csi300_pct"] >= 5.5)).astype(float).where(df_all["f2_erp_csi300_pct"].notna(), np.nan)
    g4 = ((df_all["f4_cn_us_10y_spread_bp"] < 0.0) | (df_all["f4_usdcny"] >= 7.0)).astype(float).where(df_all["f4_cn_us_10y_spread_bp"].notna(), np.nan)
    g5 = ((df_all["f3_cn_m1_m2_diff"] <= -3.0) & ((df_all["f3_cn_ppi_yoy"] <= 0.0) | (df_all["f3_cn_pmi_mfg"] < 50.0))).astype(float).where(df_all["f3_cn_m1_m2_diff"].notna(), np.nan)
    g6 = ((df_all["f2_amount_pct_3y"] >= 0.85) & ((df_all["f2_pct_above_ma200"] >= 0.70) | (df_all["f2_turn_pct_3y"] >= 0.85))).astype(float)
    g7 = (df_all["f5_p2_delta_stance_pos_w30"] >= 1.0).astype(float).where(df_all["f5_p2_delta_stance_pos_w30"].notna(), np.nan)
    g8 = ((df_all["d_margin_chg_20d_pct"] < 0.0) & (df_all["d_nt_wflow_20d_mcap"] > 0.0)).astype(float).where(df_all["d_margin_chg_20d_pct"].notna() & df_all["d_nt_wflow_20d_mcap"].notna(), np.nan)

    gates = [
        ("g1_deep_freeze", g1, "深跌冰点门控"),
        ("g2_drain_welded", g2, "抽血阀焊死门控"),
        ("g3_high_erp", g3, "高ERP便宜区门控"),
        ("g4_fx_strain", g4, "中美利差汇率承压门控"),
        ("g5_m1m2_pain", g5, "M1-M2通缩痛阈门控"),
        ("g6_overheat", g6, "高位过热狂热门控"),
        ("g7_top_up30d", g7, "近30日顶层升级门控"),
        ("g8_delev_nt", g8, "两融去杠杆+国家队托底门控"),
    ]
    gate_df = pd.DataFrame({f"gate_{nm}": s for nm, s, _ in gates}, index=df_all.index)

    core_28 = [
        ("wp_net_waterpool_trading_mcap_1m", "交易净水池1M"),
        ("wp_net_waterpool_trading_mcap_3m", "交易净水池3M"),
        ("wp_net_waterpool_incl_div_mcap_3m", "含分红净水池3M"),
        ("wp_drain_total_mcap_1m", "总抽血1M"),
        ("wp_drain_total_mcap_3m", "总抽血3M"),
        ("wp_ipo_raised_mcap_3m", "IPO抽血3M"),
        ("wp_insider_net_reduce_mcap_3m", "产业净减持3M"),
        ("wp_inject_trading_mcap_3m", "交易输血3M"),
        ("wp_buyback_mcap_3m", "回购3M"),
        ("d_nt_wflow_20d_mcap", "日频国家队ETF20日流"),
        ("d_margin_chg_20d_mcap", "日频两融20日变化"),
        ("d_stamp_tax_20d_mcap", "日频印花税20日抽血"),
        ("f2_pct_above_ma200", "站上MA200宽度"),
        ("f2_pct_new_low_250d", "250日新低占比"),
        ("f2_erp_csi300_pct", "沪深300 ERP"),
        ("f2_erp_all_a_median_pct", "全A中位数ERP"),
        ("f2_turn_pct_3y", "换手率3Y分位"),
        ("f3_cn_m1_m2_diff", "M1-M2剪刀差"),
        ("f3_cn_new_loan_12m_yoy", "12M新增信贷YoY"),
        ("f3_cn_pmi_mfg", "制造业PMI"),
        ("f3_cn_ppi_minus_cpi", "PPI-CPI剪刀差"),
        ("f3_cn_corp_real_rate_ppi", "企业实际利率"),
        ("f4_cn_us_10y_spread_bp", "中美10Y利差"),
        ("f4_usdcny_chg13w", "USDCNY 13周变化"),
        ("f5_p2_delta_stance_dec60", "顶层会议60日衰减diff"),
        ("f5_p2_f009_unmentioned_dec60", "F009未提股市60日衰减"),
        ("f5_me_hard_rescue_w60", "60日硬稳市密度"),
        ("f5_me_slogan_only_w60", "60日纯口号喊话密度"),
    ]

    for g_nm, g_ser, g_desc in gates:
        for x_nm, x_desc in core_28:
            inter = g_ser * df_all[x_nm]
            _add(cols, meta, f"f7_{g_nm}__x__{x_nm}", inter, fam, f"{g_desc} × {x_desc}", "gate_interaction")

    return pd.DataFrame(cols, index=df_all.index), gate_df, meta
