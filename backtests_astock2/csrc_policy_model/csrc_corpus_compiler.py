#!/usr/bin/env python3
"""
Compile all Wave 1/2 JSON shards into a deduplicated, point-in-time aligned Master Event-Market Table.
Strictly zero lookahead: ex-ante state from t_prior, tradable returns from open[t_entry] -> close[t_entry+h-1].
"""
import glob
import json
import os
import numpy as np
import pandas as pd

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114"
SHARD_DIR = os.path.join(BASE_DIR, "shards")
BACKTEST_DIR = os.path.join(BASE_DIR, "backtest")

CHAIR_START = {
    "周小川": "2000-02-24",
    "尚福林": "2002-12-27",
    "郭树清": "2011-10-29",
    "肖钢": "2013-03-17",
    "刘士余": "2016-02-20",
    "易会满": "2019-01-26",
    "吴清": "2024-02-07",
}

AUTH_RANK = {
    "POLITBURO": 100, "CENTRAL_ECON_CONF": 95, "CENTRAL_FIN_CONF": 95,
    "STATE_COUNCIL_NINE_ARTICLES": 92, "FSDC_VICE_PREMIER": 90, "STATE_COUNCIL_EXEC": 85,
    "JOINT_MINISTRY_SCIO": 82, "PBOC_HARD_TOOL": 80, "HUIJIN_NATIONAL_TEAM": 78,
    "FISCAL_SASAC": 75, "CSRC_CHAIR": 70, "CSRC_OFFICIAL": 55,
    "STATE_MEDIA_EDITORIAL": 50, "EXCHANGE_SURVEILLANCE": 45,
}

TONE_KEYS = [
    "market_rescue_signal", "liquidity_long_term_capital", "ipo_supply_tightening",
    "share_reduction_crackdown", "quant_short_selling_tightening", "speculation_fraud_crackdown",
    "tech_innovation_support", "ma_restructuring_support", "dividend_buyback_push",
    "brokerage_investment_bank",
]


def infer_era(dt_str: str) -> str:
    if dt_str < "2002-12-27": return "周小川"
    if dt_str < "2011-10-29": return "尚福林"
    if dt_str < "2013-03-17": return "郭树清"
    if dt_str < "2016-02-20": return "肖钢"
    if dt_str < "2019-01-26": return "刘士余"
    if dt_str < "2024-02-07": return "易会满"
    return "吴清"


def load_and_dedup_shards():
    raw_events = []
    for p in sorted(glob.glob(os.path.join(SHARD_DIR, "*.json"))):
        sid = os.path.basename(p).replace(".json", "")
        try:
            data = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            print(f"WARN bad shard {p}: {e}")
            continue
        for ev in data.get("events", []):
            dt = str(ev.get("event_date", "")).strip()[:10]
            if len(dt) != 10 or not dt[:4].isdigit() or dt < "1996-01-01" or dt > "2026-11-15":
                continue
            ev["_shard"] = sid
            ev["event_date"] = dt
            ev["chairman_era"] = infer_era(dt)
            raw_events.append(ev)

    # Deduplicate same-date + similar authority/title events while preserving distinct mechanisms
    grouped = {}
    for ev in raw_events:
        dt = ev["event_date"]
        auth = ev.get("authority_level", "CSRC_OFFICIAL")
        # Group key: (date, top_category) so Politburo + CSRC rule on same day stay distinct if different body,
        # while duplicate descriptions of the SAME press conference merge cleanly!
        body_bucket = (
            "POLIT" if "POLITBURO" in auth or "CENTRAL_" in auth else
            "SC" if "STATE_COUNCIL" in auth or "FSDC" in auth else
            "HUIJIN_PBOC" if auth in ("HUIJIN_NATIONAL_TEAM", "PBOC_HARD_TOOL") else
            "EXCH" if auth == "EXCHANGE_SURVEILLANCE" else
            "MEDIA" if auth == "STATE_MEDIA_EDITORIAL" else
            "MINISTRY_CSRC"
        )
        key = (dt, body_bucket)
        if key not in grouped:
            grouped[key] = ev
        else:
            cur = grouped[key]
            if AUTH_RANK.get(auth, 40) > AUTH_RANK.get(cur.get("authority_level", ""), 40):
                cur["authority_level"] = auth
                cur["speaker_or_body"] = ev.get("speaker_or_body", cur.get("speaker_or_body"))
                cur["title_or_occasion"] = ev.get("title_or_occasion", cur.get("title_or_occasion"))
            cur["is_joint_ministry"] = bool(cur.get("is_joint_ministry")) or bool(ev.get("is_joint_ministry"))
            stg_rank = {"ROUTINE_SLOGAN": 1, "RESEARCH_EVALUATE": 2, "DRAFT_CONSULT": 3, "IMMINENT_RULE": 4, "HARD_ACTION_NOW": 5}
            if stg_rank.get(ev.get("action_verb_stage", ""), 0) > stg_rank.get(cur.get("action_verb_stage", ""), 0):
                cur["action_verb_stage"] = ev["action_verb_stage"]
            slot_rank = {"BMO": 1, "INTRADAY": 2, "AMC": 3, "WEEKEND_HOLIDAY": 3}
            if slot_rank.get(str(ev.get("release_time_slot", "")).upper(), 2) > slot_rank.get(str(cur.get("release_time_slot", "")).upper(), 2):
                cur["release_time_slot"] = ev["release_time_slot"]
            # Merge tone dimensions by max magnitude
            td_cur = cur.setdefault("tone_dimensions", {})
            td_new = ev.get("tone_dimensions") or {}
            for k in TONE_KEYS:
                v1, v2 = int(td_cur.get(k, 0) or 0), int(td_new.get(k, 0) or 0)
                td_cur[k] = v2 if abs(v2) > abs(v1) else v1
            # Merge quotes, sectors, subsequent policies
            cur["verbatim_quotes"] = list(dict.fromkeys((cur.get("verbatim_quotes") or []) + (ev.get("verbatim_quotes") or [])))[:5]
            cur["named_sectors"] = list(dict.fromkeys((cur.get("named_sectors") or []) + (ev.get("named_sectors") or [])))
            sp_all = (cur.get("subsequent_policies") or []) + (ev.get("subsequent_policies") or [])
            seen_p = set()
            dedup_sp = []
            for sp in sp_all:
                if isinstance(sp, dict):
                    pk = (str(sp.get("policy_date", ""))[:10], str(sp.get("hard_lever_type", "")))
                    if pk not in seen_p and pk[0]:
                        seen_p.add(pk)
                        dedup_sp.append(sp)
            cur["subsequent_policies"] = dedup_sp
            cur["_shard"] = f"{cur['_shard']}+{ev['_shard']}"

    deduped = sorted(grouped.values(), key=lambda x: x["event_date"])
    print(f"Compiled {len(raw_events)} raw events -> {len(deduped)} deduplicated canonical events")
    return deduped


def align_events_with_panel(events):
    panel = pd.read_parquet(os.path.join(BACKTEST_DIR, "daily_market_panel.parquet"))
    panel = panel.sort_values("date").reset_index(drop=True)
    dates = panel["date"].tolist()
    date_to_idx = {d: i for i, d in enumerate(dates)}

    # Precompute cumulative return indices for exact open[t_entry] -> close[t_entry+h-1] returns!
    # Notice: for an index with level series, ret(open[t] -> close[t+h-1]) = close[t+h-1] / open[t] - 1.
    # For equal-weight portfolios (ew, micro30, large10, tech_board), we reconstruct exact cumulative close level
    # from cc_ret, and open_level[t] = close_level[t-1] * (1 + gap_ret[t])!
    PORT_SERIES = ["ew", "micro30", "large10", "tech_board"]
    for ps in PORT_SERIES:
        cl = (1.0 + panel[f"{ps}_cc_ret"].fillna(0.0)).cumprod()
        prev_cl = cl.shift(1).fillna(1.0)
        op = prev_cl * (1.0 + panel[f"{ps}_gap_ret"].fillna(0.0))
        panel[f"{ps}_open"] = op
        panel[f"{ps}_close"] = cl

    # Same for spliced benchmark (csi300 spliced with sh_comp pre-2005)
    b_cl = (1.0 + panel["bench_cc_ret"].fillna(0.0)).cumprod()
    b_op = b_cl.shift(1).fillna(1.0) * (1.0 + panel["bench_gap_ret"].fillna(0.0))
    panel["bench_open"] = b_op
    panel["bench_close"] = b_cl

    ASSETS = [
        "bench", "sh_comp", "csi300", "chinext", "star50", "csi500", "csi1000",
        "sse50", "csi_div", "brokerage", "bank_idx", "new_energy", "baijiu",
        "pharma", "soe_reform", "central_soe", "defense", "media_ai", "tmt_info",
        "cons_opt", "real_estate", "semi_etf", "ew", "micro30", "large10", "tech_board"
    ]
    HORIZONS = [1, 3, 5, 10, 20, 40, 60, 120]

    rows = []
    for idx_ev, ev in enumerate(events):
        dt = ev["event_date"]
        slot = str(ev.get("release_time_slot", "AMC")).upper()
        if dt < dates[1]:
            continue

        # Strictly zero-lookahead t_entry (first tradable open AFTER release) and t_prior (last close BEFORE release)
        if dt in date_to_idx:
            i_dt = date_to_idx[dt]
            if slot == "BMO":
                t_entry = i_dt
                t_prior = i_dt - 1
            elif slot == "INTRADAY":
                t_entry = i_dt + 1
                t_prior = i_dt - 1
            else:  # AMC or WEEKEND_HOLIDAY
                t_entry = i_dt + 1
                t_prior = i_dt
        else:
            # Find first trading day > dt
            later = [i for i, d in enumerate(dates) if d > dt]
            t_entry = later[0] if later else len(dates)
            t_prior = (t_entry - 1) if t_entry > 0 else 0

        td = ev.get("tone_dimensions") or {}
        sp_list = ev.get("subsequent_policies") or []
        lead_days_list = [int(sp.get("lead_days", 999)) for sp in sp_list if isinstance(sp, dict) and str(sp.get("lead_days", "")).lstrip("-").isdigit() and int(sp.get("lead_days", 999)) >= 0]
        hard_levers = [str(sp.get("hard_lever_type", "")) for sp in sp_list if isinstance(sp, dict)]

        era = ev.get("chairman_era", infer_era(dt))
        c_start = CHAIR_START.get(era, "2000-01-01")
        days_in_office = (pd.Timestamp(dt) - pd.Timestamp(c_start)).days

        rec = {
            "master_id": f"M{idx_ev+1:04d}",
            "shard_src": ev.get("_shard", ""),
            "event_date": dt,
            "release_slot": slot,
            "tradable_date": dates[t_entry] if t_entry < len(dates) else "PENDING_NEXT_OPEN",
            "t_entry_idx": t_entry if t_entry < len(dates) else -1,
            "chairman_era": era,
            "days_in_office": days_in_office,
            "authority_level": ev.get("authority_level", "CSRC_OFFICIAL"),
            "is_joint_ministry": int(bool(ev.get("is_joint_ministry"))),
            "venue_type": ev.get("venue_type", "OFFICIAL_QA_RULE"),
            "action_verb_stage": ev.get("action_verb_stage", "ROUTINE_SLOGAN"),
            "speaker_or_body": ev.get("speaker_or_body", ""),
            "title_or_occasion": ev.get("title_or_occasion", ""),
            "quotes_joined": " | ".join(ev.get("verbatim_quotes") or []),
            "named_sectors_joined": ",".join(ev.get("named_sectors") or []),
            "n_subseq_policies": len(sp_list),
            "min_policy_lead_days": min(lead_days_list) if lead_days_list else -1,
            "has_policy_within_15d": int(any(0 <= d <= 15 for d in lead_days_list)),
            "has_policy_within_30d": int(any(0 <= d <= 30 for d in lead_days_list)),
            "has_policy_within_60d": int(any(0 <= d <= 60 for d in lead_days_list)),
            "has_policy_within_90d": int(any(0 <= d <= 90 for d in lead_days_list)),
            "hard_levers_joined": ",".join(hard_levers),
            "weekday": pd.Timestamp(dt).dayofweek,
            "month": pd.Timestamp(dt).month,
        }
        for k in TONE_KEYS:
            rec[k] = int(td.get(k, 0) or 0)

        # Ex-ante market state from t_prior (100% known before speech/entry!)
        if 0 <= t_prior < len(panel):
            pr = panel.iloc[t_prior]
            rec["prior_dd_60d"] = float(pr["bench_dd_60d"]) if pd.notna(pr["bench_dd_60d"]) else np.nan
            rec["prior_dd_250d"] = float(pr["bench_dd_250d"]) if pd.notna(pr["bench_dd_250d"]) else np.nan
            rec["prior_ret_20d"] = float(pr["bench_ret_20d"]) if pd.notna(pr["bench_ret_20d"]) else np.nan
            rec["prior_ret_5d"] = float(pr["bench_ret_5d"]) if pd.notna(pr["bench_ret_5d"]) else np.nan
            rec["prior_vol_20d"] = float(pr["bench_vol_20d"]) if pd.notna(pr["bench_vol_20d"]) else np.nan
            rec["prior_amt_pct_250d"] = float(pr["amount_pct_250d"]) if pd.notna(pr["amount_pct_250d"]) else np.nan
            rec["prior_amt_yi"] = float(pr["total_amount_yi"]) if pd.notna(pr["total_amount_yi"]) else np.nan
            rec["prior_zt_cnt"] = float(pr["zt_cnt"]) if pd.notna(pr["zt_cnt"]) else np.nan
            rec["prior_dt_cnt"] = float(pr["dt_cnt"]) if pd.notna(pr["dt_cnt"]) else np.nan
            rec["prior_max_streak"] = float(pr["max_zt_streak"]) if pd.notna(pr["max_zt_streak"]) else np.nan
            rec["prior_broken_rate"] = float(pr["broken_rate"]) if pd.notna(pr["broken_rate"]) else np.nan

        # Forward tradable returns from open[t_entry] -> close[t_entry + h - 1]
        if 0 <= t_entry < len(panel):
            en = panel.iloc[t_entry]
            rec["entry_gap_bench"] = float(en["bench_gap_ret"]) if pd.notna(en["bench_gap_ret"]) else np.nan
            rec["entry_gap_brokerage"] = float(en["brokerage_gap_ret"]) if pd.notna(en.get("brokerage_gap_ret")) else np.nan
            rec["entry_amt_ratio_20d"] = float(en["amount_ratio_20d"]) if pd.notna(en["amount_ratio_20d"]) else np.nan

            for a in ASSETS:
                op_val = en.get(f"{a}_open", np.nan)
                if pd.isna(op_val) or op_val <= 0:
                    continue
                for h in HORIZONS:
                    i_ex = t_entry + h - 1
                    if i_ex < len(panel):
                        cl_val = panel.iloc[i_ex].get(f"{a}_close", np.nan)
                        if pd.notna(cl_val) and cl_val > 0:
                            rec[f"ret_{a}_{h}d"] = float(cl_val / op_val - 1.0)

            # Short-term production strategy & microstructure forward 5d/20d averages
            sl5 = panel.iloc[t_entry: min(len(panel), t_entry + 5)]
            sl20 = panel.iloc[t_entry: min(len(panel), t_entry + 20)]
            rec["fwd5_v18_ret"] = float(sl5["v18_1to2_ret"].mean()) if "v18_1to2_ret" in sl5 else np.nan
            rec["fwd1_v18_ret"] = float(en.get("v18_1to2_ret", np.nan))
            rec["fwd5_v51_ret"] = float(sl5["v51_high_dip_ret"].mean()) if "v51_high_dip_ret" in sl5 else np.nan
            rec["fwd5_high_relay_oc"] = float(sl5["high_relay_oc_ret"].mean())
            rec["fwd1_high_relay_oc"] = float(en.get("high_relay_oc_ret", np.nan))
            rec["fwd5_zt_cnt"] = float(sl5["zt_cnt"].mean())
            rec["fwd20_zt_cnt"] = float(sl20["zt_cnt"].mean())
            rec["fwd5_max_streak"] = float(sl5["max_zt_streak"].max())
            rec["fwd20_broken_rate"] = float(sl20["broken_rate"].mean())

        rows.append(rec)

    df_ev = pd.DataFrame(rows)
    # Compute point-in-time 10-trading-day positive policy cluster count
    pos_idx = df_ev[df_ev["market_rescue_signal"] + df_ev["liquidity_long_term_capital"] >= 2]["t_entry_idx"].values
    df_ev["pos_cluster_10d"] = [
        int(np.sum((pos_idx >= idx - 10) & (pos_idx <= idx))) if idx >= 0 else 0
        for idx in df_ev["t_entry_idx"]
    ]

    out_pq = os.path.join(BACKTEST_DIR, "master_events_pit.parquet")
    df_ev.to_parquet(out_pq, index=False)
    print(f"Saved {out_pq}: {len(df_ev)} aligned events, {len(df_ev.columns)} columns")
    return df_ev


if __name__ == "__main__":
    evs = load_and_dedup_shards()
    align_events_with_panel(evs)
