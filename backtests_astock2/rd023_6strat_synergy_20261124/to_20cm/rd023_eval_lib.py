#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD023 Evaluation & Extended Exit Engine (preserving DeepOpen V1.1 100% identically)."""
import itertools, math, sys
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
V1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
P2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
V11_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
sys.path.insert(0, V1_DIR); sys.path.insert(0, P2_DIR); sys.path.insert(0, V11_DIR)

from backtest_utils import _sim_k_slots
from step2_is_exit_tree_opt import defer_to_sellable_close
from v11_core import V11_EXIT_CFG, compute_scorecard_v11


def cscv_pbo(df_all_sig: pd.DataFrame, thr: float, all_dts: list[str]) -> dict:
    """Compute CSCV PBO on local threshold ladder [thr-4, thr-2, thr, thr+2, thr+4] & wide ladder."""
    t_days = [d for d in sorted(all_dts) if "2021-01-04" <= d <= "2026-11-23"]
    day_idx = {d: i for i, d in enumerate(t_days)}

    def _mat(ths):
        cols = []
        for t in ths:
            s1, _, _ = _sim_k_slots(df_all_sig[df_all_sig["score"] >= t], 1)
            arr = np.zeros(len(t_days), dtype=float)
            for r in s1.itertuples(index=False):
                i = day_idx.get(str(r.exit_date))
                if i is not None:
                    arr[i] += float(r.net_ret_eval)
            cols.append(arr)
        return np.column_stack(cols)

    def _pbo(R, S):
        gs = len(R) // S
        gidx = [list(range(i * gs, (i + 1) * gs if i < S - 1 else len(R))) for i in range(S)]
        om = []
        for te in itertools.combinations(range(S), S // 2):
            trg = [k for k in range(S) if k not in te]
            rt = R[[x for k in trg for x in gidx[k]]]
            re_ = R[[x for k in te for x in gidx[k]]]
            sdt, sde = rt.std(0, ddof=1), re_.std(0, ddof=1)
            st = np.divide(rt.mean(0), sdt, out=np.zeros_like(sdt), where=sdt > 1e-12)
            se = np.divide(re_.mean(0), sde, out=np.zeros_like(sde), where=sde > 1e-12)
            b = int(np.argmax(st))
            om.append(float(np.mean(se > se[b])))
        return round(float(np.mean(np.array(om) > 0.50) * 100.0), 2)

    Rw = _mat([70, 72, 74, 76, 78, 80, 82])
    Rl = _mat([int(thr + d) for d in (-4, -2, 0, 2, 4)])
    return {"wide_S8": _pbo(Rw, 8), "wide_S10": _pbo(Rw, 10), "loc_S8": _pbo(Rl, 8), "loc_S10": _pbo(Rl, 10)}


def eval_splits(tr: pd.DataFrame) -> dict:
    """Evaluate FULL, IS, OOS, 2026 on 1-slot + EW + ex5 + WR + PO + MDD + Calmar."""
    res = {}
    wins = [("FULL", "2021-01-04", "2026-11-23", 5.88), ("IS", "2021-01-04", "2024-08-31", 3.66),
            ("OOS", "2024-09-01", "2026-11-23", 2.22), ("Y26", "2026-01-01", "2026-11-23", 0.89)]
    for lbl, sdt, edt, yrs in wins:
        sub = tr[(tr["buy_date"] >= sdt) & (tr["buy_date"] <= edt)] if not tr.empty else pd.DataFrame()
        if sub.empty:
            res[lbl] = {"raw_n": 0, "n": 0, "wr": 0.0, "po": 0.0, "mean": 0.0, "nav": 1.0, "ew_nav": 1.0, "ex5": 1.0, "mdd": 0.0, "calmar": 0.0}
            continue
        t1, nav, mdd = _sim_k_slots(sub, 1)
        ew_nav = float(np.prod(1.0 + sub.groupby("buy_date")["net_ret"].mean().to_numpy(dtype=float)))
        r = t1["net_ret_eval"].to_numpy(dtype=float)
        w, l = r[r > 0], r[r <= 0]
        po = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
        ex5 = float(np.prod(1.0 + np.sort(r)[:-5])) if len(r) > 5 else 1.0
        cagr = (nav ** (1.0 / yrs) - 1.0) * 100.0 if nav > 0 else -100.0
        calmar = round(cagr / (mdd * 100.0), 2) if mdd > 1e-6 else 99.0
        res[lbl] = {
            "raw_n": int(len(sub)), "n": int(len(t1)),
            "wr": round(float((r > 0).mean() * 100.0), 2),
            "po": round(po, 2),
            "mean": round(float(r.mean() * 100.0), 2),
            "nav": round(float(nav), 3),
            "ew_nav": round(ew_nav, 3),
            "ex5": round(ex5, 3),
            "mdd": round(float(mdd * 100.0), 2),
            "calmar": calmar,
        }
    return res


def sim_v11_exit_ext(df: pd.DataFrame, cfg: dict, fee: float = 0.0030, tp_buf: float = 0.0030) -> pd.DataFrame:
    """Extended V1.1 exit engine supporting all Module 1 exit experiments."""
    rows = []
    extra_risk = set(cfg.get("extra_risk", []))
    for r in df.itertuples(index=False):
        b_px = float(r.f1_ao)
        if np.isnan(b_px) or b_px <= 0:
            continue
        rm = cfg.get("risk_mode", "inst_dt")
        risk_hit = False
        if rm == "inst_dt":
            risk_hit = (r.f1_lhb_inst_net < -2000.0) or (r.f1_mkt20_dt_cnt >= 3) or (r.f1_mkt10_dt_cnt >= 20)
        if "R_vol35x" in extra_risk and pd.notna(r.f1_vol_ratio5) and r.f1_vol_ratio5 > 3.5:
            risk_hit = True
        if "R_hs300_drop" in extra_risk and ((r.f1_csi_1d <= -0.020) or (r.f1_csi_5d <= -0.025)):
            risk_hit = True
        if "R_reg_new" in extra_risk and getattr(r, "f2_reg_new", 0) >= 1:
            risk_hit = True
        if "R_reb4_lt20" in extra_risk and pd.notna(r.f1_reb4_10d) and r.f1_reb4_10d < 0.20:
            risk_hit = True
        if "R_sen20_lt40" in extra_risk and pd.notna(r.sensor20_d2_red) and r.sensor20_d2_red < 0.40:
            risk_hit = True
        if "R_elo135" in extra_risk and pd.notna(r.f1_kpl_elo) and r.f1_kpl_elo >= 135.0:
            risk_hit = True

        boost = 0.0
        cb_mode = cfg.get("clv_boost_mode", "none")
        f1_body_v = float(r.f1_body or 0.0)
        f1_clv_v = float(r.f1_clv or 0.5)
        if cb_mode in ("clv70", "both") and (f1_body_v > 0.0) and (f1_clv_v >= 0.70):
            boost += 0.03
        if cb_mode in ("dt10", "both") and (r.f1_mkt10_dt_cnt + getattr(r, "f1_mkt20_dt_cnt", 0) < 10):
            boost += 0.03

        sell_k, s_px, reason = 2, np.nan, "d2_close"

        def try_tp(k, tp_r, ref_px, dev_check=False):
            ao = float(getattr(r, f"f{k}_ao", np.nan))
            ah = float(getattr(r, f"f{k}_ah", np.nan))
            if np.isnan(ao) or np.isnan(ah) or (not getattr(r, f"f{k}_sellable", False)):
                return False, np.nan, ""
            open_dt = bool(getattr(r, f"f{k}_open_is_dt", False))
            if cfg.get("pry_mkt_lt5_exit", False):
                m_zt = getattr(r, f"f{k}_mkt_all_nonst_0925_zt", 99)
                if pd.notna(m_zt) and m_zt < 5 and not open_dt:
                    return True, ao, "pry_mkt_lt5_open"
            dev_px = float(getattr(r, f"f{k}_dev93_px", np.nan)) if dev_check else np.nan
            tp_px = ref_px * (1.0 + tp_r) if tp_r is not None else 1e18
            if pd.notna(dev_px) and dev_px > 0 and dev_px < tp_px:
                tp_px = dev_px
                tag = "dev93"
            else:
                tag = "tp"
            if tp_px > 1e17:
                return False, np.nan, ""
            if ao >= tp_px and not open_dt:
                return True, ao, f"gap_{tag}"
            zt_px_k = float(getattr(r, f"f{k}_zt_px_adj", 1e18) or 1e18)
            need_ah = min(tp_px * (1.0 + tp_buf), zt_px_k - 1e-4)
            if ah >= need_ah:
                return True, tp_px, f"intraday_{tag}"
            return False, np.nan, ""

        dev_mode = cfg.get("dual_dev93", "none")
        if r.f1_zt:
            k, imm = 2, False
            while k < 10:
                ac_k = float(getattr(r, f"f{k}_ac", np.nan))
                ac_p = float(getattr(r, f"f{k-1}_ac", np.nan))
                if np.isnan(ac_k):
                    k = max(2, k - 1); break
                op_k = float(getattr(r, f"f{k}_o_pct", np.nan))
                ao_k = float(getattr(r, f"f{k}_ao", np.nan))
                open_dt_k = bool(getattr(r, f"f{k}_open_is_dt", False))
                open_zt_k = bool(getattr(r, f"f{k}_open_is_zt", False))
                if cfg.get("pry_mkt_lt5_exit", False):
                    m_zt = getattr(r, f"f{k}_mkt_all_nonst_0925_zt", 99)
                    if pd.notna(m_zt) and m_zt < 5 and not open_dt_k:
                        s_px, sell_k, reason = ao_k, k, "B1_pry_mkt_lt5_open"; break
                hi_tp_b1 = cfg.get("b1_d2_hiopen_tp", None)
                if hi_tp_b1 is not None and pd.notna(op_k) and op_k >= hi_tp_b1 and (not open_dt_k) and (not open_zt_k):
                    s_px, sell_k, reason = ao_k, k, "B1_hiopen_tp"; break
                if dev_mode in ("b1_only", "all"):
                    hit_d, px_d, r_d = try_tp(k, None, ac_p, dev_check=True)
                    if hit_d:
                        s_px, sell_k, reason = px_d, k, f"B1_{r_d}"; break
                g15 = cfg.get("guard_15_tp", None)
                if g15 is not None and (not getattr(r, f"f{k}_zt", False)):
                    ah_k = float(getattr(r, f"f{k}_ah", np.nan))
                    if pd.notna(ah_k) and ah_k >= ac_p * (1.15 + tp_buf):
                        s_px, sell_k, reason = ac_p * (1.0 + g15), k, "B1_guard15"; break
                if getattr(r, f"f{k}_zt", False):
                    k += 1; continue
                if cfg.get("zt_imm", False) and (not imm) and getattr(r, f"f{k}_ty", False) and ac_k > ac_p:
                    imm = True; k += 1; continue
                sell_k, reason = k, "B1_zt_break"; break
            else:
                sell_k, reason = 10, "B1_zt_max10"
        else:
            f1_ac = float(r.f1_ac)
            is_b4 = (f1_body_v <= cfg.get("b4_body", -0.05) or r.f1_is_dt)
            is_b2 = (not is_b4) and (f1_body_v >= cfg.get("b2_body", 0.06)) and (f1_clv_v >= cfg.get("b2_clv", 0.65))
            d_dev_all = (dev_mode == "all")
            if is_b4:
                if cfg.get("d1_yin_mode") in ("d2_open_cut_all", "d2_open_cut") and pd.notna(r.f2_ao) and (not r.f2_open_is_dt):
                    if cfg.get("d1_yin_mode") == "d2_open_cut_all" or (pd.notna(r.f2_o_pct) and r.f2_o_pct <= 0.0):
                        s_px, sell_k, reason = float(r.f2_ao), 2, "B4_d2_open_cut"
                if np.isnan(s_px):
                    sell_k, reason = 2, "B4_d2_close"
            elif is_b2:
                tp2 = cfg.get("b2_tp", 0.12)
                if tp2 is not None and boost > 0:
                    tp2 = min(0.18, tp2 + boost)
                if risk_hit and tp2 is not None:
                    tp2 = min(tp2, 0.07)
                if cfg.get("b2_mode") in ("d2_tp", "d3_hold") and tp2 is not None:
                    hit, px_h, r_h = try_tp(2, tp2, f1_ac, dev_check=d_dev_all)
                    if hit: s_px, sell_k, reason = px_h, 2, f"B2_{r_h}"
                if np.isnan(s_px):
                    if cfg.get("b2_mode") == "d3_hold" and (not risk_hit) and not np.isnan(r.f3_ac):
                        if r.f2_zt:
                            k = 3
                            while k < 10 and getattr(r, f"f{k}_zt", False): k += 1
                            sell_k, reason = k, "B2_d2zt_ride"
                        else:
                            if tp2 is not None:
                                hit3, px3, r3 = try_tp(3, tp2, float(r.f2_ac), dev_check=d_dev_all)
                                if hit3: s_px, sell_k, reason = px3, 3, f"B2_d3_{r3}"
                            if np.isnan(s_px): sell_k, reason = 3, "B2_d3_close"
                    else:
                        sell_k, reason = 2, "B2_d2_close"
            else:
                yin_m = cfg.get("d1_yin_mode", "none")
                if f1_body_v < 0 and yin_m in ("d2_open_cut", "d2_open_cut_all") and pd.notna(r.f2_ao) and (not r.f2_open_is_dt):
                    if yin_m == "d2_open_cut_all" or (pd.notna(r.f2_o_pct) and r.f2_o_pct <= 0.0):
                        s_px, sell_k, reason = float(r.f2_ao), 2, "B3_yin_open_cut"
                if np.isnan(s_px):
                    tp3 = max(0.06, min(0.15, abs(float(r.f1_o_pct)) * cfg.get("b3_adapt_k", 1.5))) if cfg.get("b3_tp_mode") == "adaptive" else cfg.get("b3_tp", None)
                    if f1_body_v < 0 and yin_m == "d2_tp_down":
                        tp3 = 0.05
                    elif tp3 is not None and boost > 0:
                        tp3 = min(0.18, tp3 + boost)
                    if risk_hit and tp3 is not None:
                        tp3 = min(tp3, 0.07)
                    if tp3 is not None:
                        hit, px_h, r_h = try_tp(2, tp3, f1_ac, dev_check=d_dev_all)
                        if hit: s_px, sell_k, reason = px_h, 2, f"B3_{r_h}"
                    if np.isnan(s_px):
                        if f1_body_v < 0 and yin_m == "d3_hold_down" and pd.notna(r.f3_ac) and (float(r.f2_ac) < f1_ac):
                            hit3, px3, r3 = try_tp(3, 0.05, float(r.f2_ac), dev_check=d_dev_all)
                            if hit3: s_px, sell_k, reason = px3, 3, f"B3_d3down_{r3}"
                            else: sell_k, reason = 3, "B3_d3down_close"
                        elif cfg.get("b3_d3_if_ty", False) and (not risk_hit) and pd.notna(r.f3_ac) and (r.f2_zt or (r.f2_ty and float(r.f2_ac) > f1_ac)):
                            if r.f2_zt:
                                k = 3
                                while k < 10 and getattr(r, f"f{k}_zt", False): k += 1
                                sell_k, reason = k, "B3_d2zt_ride"
                            else:
                                hit3, px3, r3 = try_tp(3, tp3, float(r.f2_ac), dev_check=d_dev_all)
                                if hit3: s_px, sell_k, reason = px3, 3, f"B3_d3ty_{r3}"
                                else: sell_k, reason = 3, "B3_d3ty_close"
                        else:
                            sell_k, reason = 2, "B3_d2_close"

        if np.isnan(s_px):
            sell_k, s_px = defer_to_sellable_close(r, sell_k)
            if sell_k < 2: continue
        s_dt = getattr(r, f"f{sell_k}_dt")
        if not s_dt or np.isnan(s_px) or s_px <= 0: continue
        gross = s_px / b_px - 1.0
        net = (1.0 + gross) * (1.0 - fee) - 1.0
        rows.append({
            "sig_date": r.dt, "buy_date": r.f1_dt, "exit_date": s_dt,
            "c6": r.c6, "name": r.name, "dl": int(r.dl), "amount": float(r.amount),
            "score": float(getattr(r, "score", 0.0)), "open_pct": round(float(r.f1_o_pct) * 100.0, 2),
            "buy_px": b_px, "exit_px": s_px, "gross_ret": gross, "net_ret": net,
            "hold_bars": sell_k - 1, "exit_reason": reason, "risk_hit": int(risk_hit),
        })
    return pd.DataFrame(rows)
