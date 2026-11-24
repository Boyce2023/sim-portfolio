#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 2 (IS-ONLY <= 2024-08-31):
Systematically optimize 36+ dynamic exit tree variants across D1 4 branches,
D2 09:25 gap switches, intraday TP/SL (conservative same-day SL priority + gap fill),
and holding-period risk switches — strictly on IS before touching OOS!
"""
import sys
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"


def compute_scorecard_v1(d: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """
    IS-locked 18-item pure-integer orthogonal scorecard (Base = 70, A >= 78, S >= 88).
    """
    f = pd.DataFrame(index=d.index)
    # Dim 1: Chips & Free Float (2 items)
    f["F01_lock_top10_ge40"] = np.where(d["lock_top10"].fillna(0.0) >= 40.0, 6, 0)
    f["F02_rfmcap_tier"] = np.where(d["real_free_mcap"].fillna(999.0) <= 20.0, 4, np.where(d["real_free_mcap"].fillna(0.0) > 40.0, -4, 0))
    # Dim 2: Position, Open Gap, Abn Space, ZT Microstructure (6 items)
    f["F03_open_gap_zone"] = np.where(d["f1_o_pct"] < -0.080, -12, np.where(d["f1_o_pct"].between(-0.065, -0.030), 5, 0))
    f["F04_bias20_le12"] = np.where(d["bias20"].fillna(1.0) <= 0.12, 8, 0)
    f["F05_dist3d30_ge10"] = np.where(d["dist_3d30"].fillna(0.0) >= 0.10, 4, 0)
    f["F06_zt60d_ge2"] = np.where(d["zt_cnt_60d"].fillna(0) >= 2, 5, 0)
    f["F07_zt_early_le945_pen"] = np.where(d["zt_hhmm"] <= 945, -5, 0)
    f["F08_seal_ratio_ge10_pen"] = np.where(d["zt_seal_ratio"].fillna(0.0) >= 0.10, -6, 0)
    # Dim 3: LHB Capital Seats (3 items)
    f["F09_inst_net_pos"] = np.where(d["lhb_inst_net"].fillna(0.0) > 0.0, 7, 0)
    f["F10_quant_noinst_pen"] = np.where((d["lhb_quant"].fillna(0) >= 1) & (d["lhb_inst_net"].fillna(0.0) <= 0.0), -6, 0)
    f["F11_surf_yz_pen"] = np.where((d["lhb_surf"].fillna(0) == 1) & (d["lhb_lh_net_pos"].fillna(0) == 0), -5, 0)
    # Dim 4: Theme & 09:25 Market Sentiment (4 items)
    f["F12_mkt10_zt_gt70"] = np.where(d["mkt10_zt_cnt"].fillna(0) > 70, 8, 0)
    f["F13_kpl_overheat_pen"] = np.where((d["kpl_elo"].fillna(100.0) >= 112.0) | (d["kpl_20zt"].fillna(0) >= 3), -6, 0)
    f["F14_peers20_nuke_pen"] = np.where(d["f1_mkt20_prev1b_open"].fillna(0.0) < -0.015, -8, 0)
    f["F15_yizi20_siphon_pen"] = np.where(d["f1_mkt20_0925_zt"].fillna(0) >= 1, -5, 0)
    # Dim 5: Community & Announcements <09:00 (2 items)
    f["F16_xq_pre_ge1_pen"] = np.where(d["xq_t1_0900"].fillna(0) >= 1, -12, 0)
    f["F17_earn_pos_sellnews_pen"] = np.where(d["cat_earn_pos_3d"].fillna(0) == 1, -10, 0)
    # Dim 6: Calendar (1 item)
    f["F18_monday_pen"] = np.where(d["f1_weekday"] == 0, -10, 0)
    sc = pd.Series(70.0 + f.sum(axis=1).to_numpy(), index=d.index)
    return sc, f


def defer_to_sellable_close(r, k: int) -> tuple[int, float]:
    """Defer sealed 20cm limit-down (or suspended) to first sellable_strict bar close."""
    while k < 11 and not getattr(r, f"f{k}_sellable_strict", False):
        k += 1
    while k >= 2 and np.isnan(getattr(r, f"f{k}_ac", np.nan)):
        k -= 1
    if k < 2:
        return -1, np.nan
    return k, float(getattr(r, f"f{k}_ac"))


def try_intraday_tp_sl(r, k: int, tp_ratio: float | None, sl_ratio: float | None, ref_px: float) -> tuple[bool, float, str]:
    """
    Physically exact intraday limit TP / SL fill on bar k relative to ref_px (e.g. prev_ac or buy_px):
      - Check open gap first: if f{k}_ao <= sl_px (and not open limit-down), fill at f{k}_ao (gap_sl).
      - Else if f{k}_ao >= tp_px (and not open limit-down), fill at f{k}_ao (gap_tp).
      - Else if BOTH hit intraday (f{k}_al <= sl_px AND f{k}_ah >= tp_px), CONSERVATIVELY fill at sl_px (or defer if close sealed DT!).
      - Else if SL hit intraday (f{k}_al <= sl_px): fill at sl_px (if not yizi_dt; if sealed DT at close and sl_px <= dt_px_adj -> defer!).
      - Else if TP hit intraday (f{k}_ah >= tp_px): fill at tp_px (if not yizi_dt; note TP is positive so never at limit-down!).
    """
    ao = float(getattr(r, f"f{k}_ao", np.nan))
    ah = float(getattr(r, f"f{k}_ah", np.nan))
    al = float(getattr(r, f"f{k}_al", np.nan))
    if np.isnan(ao) or np.isnan(ah) or np.isnan(al):
        return False, np.nan, ""
    open_dt = bool(getattr(r, f"f{k}_open_is_dt", False))
    yizi_dt = (not getattr(r, f"f{k}_sellable", False))
    if yizi_dt or open_dt:
        # Cannot transact at open if locked limit-down at open; if yizi_dt all day, cannot sell!
        if yizi_dt:
            return False, np.nan, ""

    tp_px = ref_px * (1.0 + tp_ratio) if tp_ratio is not None else 1e18
    sl_px = ref_px * (1.0 + sl_ratio) if sl_ratio is not None else -1e18

    # Check open gaps first (when not open_is_dt)
    if sl_ratio is not None and ao <= sl_px and not open_dt:
        return True, ao, "gap_sl"
    if tp_ratio is not None and ao >= tp_px and not open_dt:
        return True, ao, "gap_tp"

    hit_sl = (sl_ratio is not None) and (al <= sl_px)
    hit_tp = (tp_ratio is not None) and (ah >= tp_px)
    # Conservative collision rule: if BOTH SL and TP hit same bar, ALWAYS fill SL!
    if hit_sl and hit_tp:
        # Check if sl_px is below limit-down price (shouldn't happen unless extreme)
        dt_px = float(getattr(r, f"f{k}_dt_px_adj", 0.0) or 0.0)
        if sl_px <= dt_px and bool(getattr(r, f"f{k}_is_dt", False)):
            return False, np.nan, ""
        return True, max(sl_px, al), "collision_sl"
    if hit_sl:
        dt_px = float(getattr(r, f"f{k}_dt_px_adj", 0.0) or 0.0)
        if sl_px <= dt_px and bool(getattr(r, f"f{k}_is_dt", False)):
            return False, np.nan, ""
        return True, max(sl_px, al), "intraday_sl"
    if hit_tp:
        return True, min(tp_px, ah), "intraday_tp"
    return False, np.nan, ""


def sim_exit_tree(df: pd.DataFrame, cfg: dict, fee: float = 0.0030) -> pd.DataFrame:
    """
    Parameterized 4-branch dynamic exit tree engine:
      cfg keys:
        - zt_imm: bool (D1 ZT continuation: allow 1 true-yang immunity on first broken ZT)
        - zt_d2_gap_tp: float | None (e.g. 0.08, 0.10: during ZT continuation, if f_o_pct >= thr and not yizi_zt? Wait: if open >= thr sell 09:25!)
        - b2_body: float (e.g. 0.06, 0.08), b2_clv: float (e.g. 0.65)
        - b2_mode: 'd2_close' | 'd2_tp' | 'd3_hold' | 'd3_if_d2_ty'
        - b2_tp: float | None
        - b3_tp_mode: 'none' | 'fixed' | 'adaptive'
        - b3_tp: float | None (e.g. 0.06, 0.08, 0.10, 0.12, 0.15)
        - b3_adapt_k: float (e.g. 1.5, 1.8)
        - b3_sl: float | None (relative to f1_ac or buy_px)
        - b3_d3_if_ty: bool (if B3 mild didn't hit TP on D2 and D2 is true yang with f2_ac > f1_ac, hold to D3 close)
        - b4_body: float (e.g. -0.05), b4_only_dt: bool
        - b4_mode: 'd2_close' | 'd2_open_cut' | 'd2_open_cut_if_neg'
        - d2_hi_open_tp: float | None (for B2/B3: if f2_o_pct >= thr, sell at D2 09:25 open!)
        - d2_lo_open_cut: float | None (for B2/B3: if f2_o_pct <= thr, cut at D2 09:25 open!)
        - risk_mode: 'none' | 'inst_dt' | 'freeze' (D1 post-close risk switch tightens TP / disables D3)
    """
    rows = []
    for r in df.itertuples(index=False):
        b_px = float(r.f1_ao)
        if np.isnan(b_px) or b_px <= 0:
            continue
        b_dt = r.f1_dt

        # Check holding-period risk signal (known by D2 09:25!)
        risk_hit = False
        rm = cfg.get("risk_mode", "none")
        if rm == "inst_dt":
            risk_hit = (r.f1_lhb_inst_net < -2000.0) or (r.f1_mkt20_dt_cnt >= 3) or (r.f1_mkt10_dt_cnt >= 20)
        elif rm == "freeze":
            risk_hit = (r.f1_lhb_inst_net < -2000.0) or (r.f1_mkt20_dt_cnt >= 3) or (r.f2_mkt10_0925_zt < 5)

        sell_k, s_px, reason = 2, np.nan, "d2_close"

        # Branch 1: D1 sealed 20cm ZT!
        if r.f1_zt:
            k = 2
            imm_used = False
            zt_gap_tp = cfg.get("zt_d2_gap_tp", None)
            while k < 10:
                ao_k = float(getattr(r, f"f{k}_ao", np.nan))
                op_k = float(getattr(r, f"f{k}_o_pct", np.nan))
                open_dt_k = bool(getattr(r, f"f{k}_open_is_dt", False))
                open_zt_k = bool(getattr(r, f"f{k}_open_is_zt", False))
                zt_k = bool(getattr(r, f"f{k}_zt", False))
                ty_k = bool(getattr(r, f"f{k}_ty", False))
                ac_k = float(getattr(r, f"f{k}_ac", np.nan))
                ac_prev = float(getattr(r, f"f{k-1}_ac", np.nan))
                if np.isnan(ac_k):
                    k = max(2, k - 1)
                    break
                # D2+ extreme high open take-profit (only if NOT yizi ZT open? Wait: if open >= +8% and <20% or even at open if non-yizi! Wait if open_is_zt and yizi_zt, maybe cannot sell? Actually you CAN sell on limit-up! Wait: only cannot BUY yizi_zt, you CAN always sell at zt_px open!)
                if zt_gap_tp is not None and not np.isnan(op_k) and op_k >= zt_gap_tp and not open_dt_k:
                    s_px, sell_k, reason = ao_k, k, "B1_zt_gap_tp"
                    break
                if zt_k:
                    k += 1
                    continue
                if cfg.get("zt_imm", False) and (not imm_used) and ty_k and (ac_k > ac_prev):
                    imm_used = True
                    k += 1
                    continue
                sell_k, reason = k, "B1_zt_break"
                break
            else:
                sell_k, reason = 10, "B1_zt_max10"

        else:
            f1_ac = float(r.f1_ac)
            f1_ao = float(r.f1_ao)
            f1_body = float(r.f1_body) if not np.isnan(r.f1_body) else 0.0
            f1_clv = float(r.f1_clv) if not np.isnan(r.f1_clv) else 0.5
            f2_ao = float(r.f2_ao) if not np.isnan(r.f2_ao) else np.nan
            f2_op = float(r.f2_o_pct) if not np.isnan(r.f2_o_pct) else np.nan
            f2_open_dt = bool(getattr(r, "f2_open_is_dt", False))

            is_b4 = (r.f1_is_dt) if cfg.get("b4_only_dt", False) else (f1_body <= cfg.get("b4_body", -0.05) or r.f1_is_dt)
            is_b2 = (not is_b4) and (f1_body >= cfg.get("b2_body", 0.06)) and (f1_clv >= cfg.get("b2_clv", 0.65))

            # Branch 4: D1 Deep Yin / DT
            if is_b4:
                b4m = cfg.get("b4_mode", "d2_close")
                if b4m == "d2_open_cut" and not np.isnan(f2_ao) and not f2_open_dt:
                    s_px, sell_k, reason = f2_ao, 2, "B4_d2_open_cut"
                elif b4m == "d2_open_cut_if_neg" and not np.isnan(f2_op) and f2_op < 0.0 and not f2_open_dt:
                    s_px, sell_k, reason = f2_ao, 2, "B4_d2_neg_cut"
                else:
                    sell_k, reason = 2, "B4_d2_close"

            # Branch 2: D1 Strong True Yang
            elif is_b2:
                # Check D2 09:25 extreme gap switches first
                hi_g = cfg.get("d2_hi_open_tp", None)
                lo_g = cfg.get("d2_lo_open_cut", None)
                if hi_g is not None and not np.isnan(f2_op) and f2_op >= hi_g and not f2_open_dt:
                    s_px, sell_k, reason = f2_ao, 2, "B2_d2_hi_open_tp"
                elif lo_g is not None and not np.isnan(f2_op) and f2_op <= lo_g and not f2_open_dt:
                    s_px, sell_k, reason = f2_ao, 2, "B2_d2_lo_open_cut"
                else:
                    b2m = cfg.get("b2_mode", "d2_close")
                    tp2 = cfg.get("b2_tp", None)
                    if risk_hit and tp2 is not None:
                        tp2 = min(tp2, 0.07)
                    if b2m in ("d2_tp", "d3_hold", "d3_if_d2_ty") and tp2 is not None:
                        hit, px_h, r_h = try_intraday_tp_sl(r, 2, tp2, cfg.get("b3_sl", None), f1_ac)
                        if hit:
                            s_px, sell_k, reason = px_h, 2, f"B2_{r_h}"
                    if np.isnan(s_px):
                        if b2m == "d3_hold" and (not risk_hit) and not np.isnan(r.f3_ac):
                            # Check if D2 sealed ZT -> ride ZT, else check D3 TP or D3 close
                            if r.f2_zt:
                                k = 3
                                while k < 10 and getattr(r, f"f{k}_zt", False):
                                    k += 1
                                sell_k, reason = k, "B2_d2zt_ride"
                            else:
                                if tp2 is not None:
                                    hit3, px3, r3 = try_intraday_tp_sl(r, 3, tp2, None, float(r.f2_ac))
                                    if hit3:
                                        s_px, sell_k, reason = px3, 3, f"B2_d3_{r3}"
                                if np.isnan(s_px):
                                    sell_k, reason = 3, "B2_d3_close"
                        elif b2m == "d3_if_d2_ty" and (not risk_hit) and (r.f2_zt or (r.f2_ty and float(r.f2_ac) > f1_ac)) and not np.isnan(r.f3_ac):
                            if r.f2_zt:
                                k = 3
                                while k < 10 and getattr(r, f"f{k}_zt", False):
                                    k += 1
                                sell_k, reason = k, "B2_d2zt_ride"
                            else:
                                if tp2 is not None:
                                    hit3, px3, r3 = try_intraday_tp_sl(r, 3, tp2, None, float(r.f2_ac))
                                    if hit3:
                                        s_px, sell_k, reason = px3, 3, f"B2_d3_{r3}"
                                if np.isnan(s_px):
                                    sell_k, reason = 3, "B2_d3_ty_close"
                        else:
                            sell_k, reason = 2, "B2_d2_close"

            # Branch 3: D1 Mild Oscillation
            else:
                hi_g = cfg.get("d2_hi_open_tp", None)
                lo_g = cfg.get("d2_lo_open_cut", None)
                if risk_hit and hi_g is not None:
                    hi_g = min(hi_g, 0.05)
                if hi_g is not None and not np.isnan(f2_op) and f2_op >= hi_g and not f2_open_dt:
                    s_px, sell_k, reason = f2_ao, 2, "B3_d2_hi_open_tp"
                elif lo_g is not None and not np.isnan(f2_op) and f2_op <= lo_g and not f2_open_dt:
                    s_px, sell_k, reason = f2_ao, 2, "B3_d2_lo_open_cut"
                else:
                    tpm = cfg.get("b3_tp_mode", "none")
                    tp_val = None
                    if tpm == "fixed":
                        tp_val = cfg.get("b3_tp", 0.10)
                    elif tpm == "adaptive":
                        tp_val = max(0.06, min(0.15, abs(float(r.f1_o_pct)) * cfg.get("b3_adapt_k", 1.5)))
                    if risk_hit and tp_val is not None:
                        tp_val = min(tp_val, 0.07)

                    sl_val = cfg.get("b3_sl", None)
                    if tp_val is not None or sl_val is not None:
                        hit, px_h, r_h = try_intraday_tp_sl(r, 2, tp_val, sl_val, f1_ac)
                        if hit:
                            s_px, sell_k, reason = px_h, 2, f"B3_{r_h}"

                    if np.isnan(s_px):
                        if cfg.get("b3_d3_if_ty", False) and (not risk_hit) and (r.f2_zt or (r.f2_ty and float(r.f2_ac) > f1_ac)) and not np.isnan(r.f3_ac):
                            if r.f2_zt:
                                k = 3
                                while k < 10 and getattr(r, f"f{k}_zt", False):
                                    k += 1
                                sell_k, reason = k, "B3_d2zt_ride"
                            else:
                                if tp_val is not None:
                                    hit3, px3, r3 = try_intraday_tp_sl(r, 3, tp_val, None, float(r.f2_ac))
                                    if hit3:
                                        s_px, sell_k, reason = px3, 3, f"B3_d3_{r3}"
                                if np.isnan(s_px):
                                    sell_k, reason = 3, "B3_d3_ty_close"
                        else:
                            sell_k, reason = 2, "B3_d2_close"

        # If closing exit (s_px is nan), enforce strict 20cm limit-down sell deferral!
        if np.isnan(s_px):
            sell_k, s_px = defer_to_sellable_close(r, sell_k)
            if sell_k < 2:
                continue
        s_dt = getattr(r, f"f{sell_k}_dt")
        if not s_dt or np.isnan(s_px) or s_px <= 0:
            continue
        gross = s_px / b_px - 1.0
        net = (1.0 + gross) * (1.0 - fee) - 1.0
        rows.append({
            "sig_date": r.dt, "buy_date": b_dt, "exit_date": s_dt,
            "c6": r.c6, "name": r.name, "dl": int(r.dl),
            "score": float(getattr(r, "score", 0.0)),
            "open_pct": round(float(r.f1_o_pct) * 100.0, 2),
            "buy_px": b_px, "exit_px": s_px,
            "gross_ret": gross, "net_ret": net, "hold_bars": sell_k - 1,
            "exit_reason": reason,
        })
    return pd.DataFrame(rows)


def eval_is_exit(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"n1": 0, "wr": 0.0, "mean": 0.0, "po": 0.0, "nav1": 1.0, "ew": 1.0, "mdd": 0.0}
    srt = tr.sort_values(["buy_date", "score", "c6"], ascending=[True, False, True])
    free_dt, taken = "", []
    for r in srt.itertuples(index=False):
        if free_dt == "" or r.buy_date > free_dt:
            taken.append(r.net_ret)
            free_dt = r.exit_date
    r1 = np.array(taken, dtype=float)
    w, l = r1[r1 > 0], r1[r1 <= 0]
    po = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else 99.0
    cum = np.cumprod(1.0 + r1)
    pk = np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]
    mdd = float(np.max((pk - cum) / pk) * 100.0)
    ew = float(np.prod(1.0 + tr.groupby("buy_date")["net_ret"].mean().to_numpy()))
    return {
        "raw_n": int(len(tr)), "n1": int(len(r1)),
        "wr": round(float((r1 > 0).mean() * 100.0), 2),
        "mean": round(float(tr["net_ret"].mean() * 100.0), 2),
        "po": round(po, 2),
        "nav1": round(float(cum[-1]), 3),
        "ew": round(ew, 3),
        "mdd": round(mdd, 2),
        "col_sl": int(tr["exit_reason"].str.contains("collision_sl").sum()),
    }


def make_36_configs() -> list[tuple[str, dict]]:
    cfgs = [
        # 01-03: Baselines
        ("01_Pure_T2_Close", {"b3_tp_mode": "none"}),
        ("02_Pure_T3_Close", {"b2_body": 0.0, "b2_clv": 0.0, "b2_mode": "d3_hold", "b3_tp_mode": "none"}),
        ("03_ZT_Ride_Only", {"zt_imm": False}),
        ("04_ZT_Ride_TYImm1", {"zt_imm": True}),
        ("05_ZT_Ride_GapTP10", {"zt_imm": False, "zt_d2_gap_tp": 0.10}),
        ("06_ZT_Ride_Imm1_GapTP12", {"zt_imm": True, "zt_d2_gap_tp": 0.12}),
        # 07-12: B3 fixed TP grid (+6%, +8%, +10%, +12%, +15%) & adaptive TP
        ("07_B3_TP06", {"b3_tp_mode": "fixed", "b3_tp": 0.06}),
        ("08_B3_TP08", {"b3_tp_mode": "fixed", "b3_tp": 0.08}),
        ("09_B3_TP10", {"b3_tp_mode": "fixed", "b3_tp": 0.10}),
        ("10_B3_TP12", {"b3_tp_mode": "fixed", "b3_tp": 0.12}),
        ("11_B3_TP15", {"b3_tp_mode": "fixed", "b3_tp": 0.15}),
        ("12_B3_AdaptTP_1.5x", {"b3_tp_mode": "adaptive", "b3_adapt_k": 1.5}),
        ("13_B3_AdaptTP_1.8x", {"b3_tp_mode": "adaptive", "b3_adapt_k": 1.8}),
        # 14-17: Intraday SL sensitivity (with collision conservative check!)
        ("14_B3_TP10_SL05", {"b3_tp_mode": "fixed", "b3_tp": 0.10, "b3_sl": -0.05}),
        ("15_B3_TP10_SL07", {"b3_tp_mode": "fixed", "b3_tp": 0.10, "b3_sl": -0.07}),
        ("16_B3_TP10_SL09", {"b3_tp_mode": "fixed", "b3_tp": 0.10, "b3_sl": -0.09}),
        ("17_B3_Adapt_SL07", {"b3_tp_mode": "adaptive", "b3_adapt_k": 1.5, "b3_sl": -0.07}),
        # 18-22: Branch 2 (Strong True Yang) variants
        ("18_B2_TP12_D2Close", {"b2_body": 0.06, "b2_clv": 0.65, "b2_mode": "d2_tp", "b2_tp": 0.12, "b3_tp_mode": "fixed", "b3_tp": 0.10}),
        ("19_B2_D3Hold_TP12", {"b2_body": 0.06, "b2_clv": 0.65, "b2_mode": "d3_hold", "b2_tp": 0.12, "b3_tp_mode": "fixed", "b3_tp": 0.10}),
        ("20_B2_D3Hold_NoTP", {"b2_body": 0.06, "b2_clv": 0.65, "b2_mode": "d3_hold", "b2_tp": None, "b3_tp_mode": "fixed", "b3_tp": 0.10}),
        ("21_B2_D3IfD2TY_TP14", {"b2_body": 0.06, "b2_clv": 0.65, "b2_mode": "d3_if_d2_ty", "b2_tp": 0.14, "b3_tp_mode": "fixed", "b3_tp": 0.10}),
        ("22_B2_8pct_D3Hold_TP14", {"b2_body": 0.08, "b2_clv": 0.65, "b2_mode": "d3_hold", "b2_tp": 0.14, "b3_tp_mode": "fixed", "b3_tp": 0.10}),
        # 23-26: Branch 4 (D1 Deep Yin / DT) tests: 09:25 cut vs D2 close!
        ("23_B4_OpenCut_All", {"b4_body": -0.05, "b4_mode": "d2_open_cut", "b3_tp_mode": "fixed", "b3_tp": 0.10}),
        ("24_B4_OpenCut_IfNeg", {"b4_body": -0.05, "b4_mode": "d2_open_cut_if_neg", "b3_tp_mode": "fixed", "b3_tp": 0.10}),
        ("25_B4_DTOnly_OpenCut", {"b4_only_dt": True, "b4_mode": "d2_open_cut", "b3_tp_mode": "fixed", "b3_tp": 0.10}),
        ("26_B4_KeepD2Close", {"b4_body": -0.05, "b4_mode": "d2_close", "b3_tp_mode": "fixed", "b3_tp": 0.10}),
        # 27-31: D2 09:25 Open Switches
        ("27_D2_HiOpen06_TP", {"d2_hi_open_tp": 0.06, "b3_tp_mode": "fixed", "b3_tp": 0.10}),
        ("28_D2_HiOpen08_TP", {"d2_hi_open_tp": 0.08, "b3_tp_mode": "fixed", "b3_tp": 0.10}),
        ("29_D2_HiOpen10_TP", {"d2_hi_open_tp": 0.10, "b3_tp_mode": "fixed", "b3_tp": 0.10}),
        ("30_D2_LoOpenNeg5_Cut", {"d2_lo_open_cut": -0.05, "b3_tp_mode": "fixed", "b3_tp": 0.10}),
        ("31_D2_Hi08_LoNeg5", {"d2_hi_open_tp": 0.08, "d2_lo_open_cut": -0.05, "b3_tp_mode": "fixed", "b3_tp": 0.10}),
        # 32-34: B3 True-Yang extension to D3
        ("32_B3_TP10_D3IfTY", {"b3_tp_mode": "fixed", "b3_tp": 0.10, "b3_d3_if_ty": True}),
        ("33_B3_Adapt_D3IfTY", {"b3_tp_mode": "adaptive", "b3_adapt_k": 1.5, "b3_d3_if_ty": True}),
        ("34_B2_D3TY_B3_TP10_D3TY", {"b2_body": 0.06, "b2_clv": 0.65, "b2_mode": "d3_if_d2_ty", "b2_tp": 0.14, "b3_tp_mode": "fixed", "b3_tp": 0.10, "b3_d3_if_ty": True}),
        # 35-38: Holding-period Risk Switches + Composite 4-Branch Trees
        ("35_TreeA_TP10_RiskInstDT", {"zt_imm": True, "b2_mode": "d3_if_d2_ty", "b2_tp": 0.14, "b3_tp_mode": "fixed", "b3_tp": 0.10, "risk_mode": "inst_dt"}),
        ("36_TreeB_TP10_RiskFreeze", {"zt_imm": True, "b2_mode": "d3_if_d2_ty", "b2_tp": 0.14, "b3_tp_mode": "fixed", "b3_tp": 0.10, "risk_mode": "freeze"}),
        ("37_TreeC_Adapt_Hi08_RiskInst", {"zt_imm": True, "b2_mode": "d3_if_d2_ty", "b2_tp": 0.14, "b3_tp_mode": "adaptive", "b3_adapt_k": 1.5, "d2_hi_open_tp": 0.08, "risk_mode": "inst_dt"}),
        ("38_TreeD_TP10_B3D3TY_RiskInst", {"zt_imm": True, "b2_mode": "d3_if_d2_ty", "b2_tp": 0.14, "b3_tp_mode": "fixed", "b3_tp": 0.10, "b3_d3_if_ty": True, "risk_mode": "inst_dt"}),
    ]
    return cfgs


def main():
    df = pd.read_parquet(f"{OUT_DIR}/p1_clean_candidates.parquet")
    sc, _ = compute_scorecard_v1(df)
    df["score"] = sc
    # IS ONLY!
    is_base = df[(df["f1_dt"] <= "2024-08-31") & df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy()
    is_A = is_base[is_base["score"] >= 78.0].copy()
    is_W = is_base[is_base["score"] >= 70.0].copy()

    print(f"=== [IS ONLY EXIT TREE OPTIMIZATION] A(>=78) N={len(is_A)} | Wide(>=70) N={len(is_W)} ===")
    cfgs = make_36_configs()
    for nm, cfg in cfgs:
        sA = eval_is_exit(sim_exit_tree(is_A, cfg))
        sW = eval_is_exit(sim_exit_tree(is_W, cfg))
        print(f"  {nm:28s} | A: N={sA['n1']:3d} WR={sA['wr']:5.1f}% mn={sA['mean']:+5.2f}% PO={sA['po']:4.2f} 1s={sA['nav1']:6.2f}x EW={sA['ew']:6.2f}x MDD={sA['mdd']:4.1f}% col={sA['col_sl']} | "
              f"W: N={sW['n1']:3d} WR={sW['wr']:5.1f}% mn={sW['mean']:+5.2f}% 1s={sW['nav1']:5.2f}x EW={sW['ew']:5.2f}x")


if __name__ == "__main__":
    main()
