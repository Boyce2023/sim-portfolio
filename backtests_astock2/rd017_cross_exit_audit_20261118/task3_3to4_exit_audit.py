#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
task3_3to4_exit_audit.py — 三进四 V4.0 (s_3to4) 跨策略卖点移植实证
100% 复现 upgrade_3to4_pit.py 基准 (95笔std / 31笔strict, 0误差), 并在 IS/OOS/全5年/2026 双轨对比:
  - 3a: 封四板次日 (冲五板日) 借鉴二进三非一字极高开 >8.8%/9.0%/9.2% 09:25 竞价止盈 (看全量净值与去前5极值净值)
  - 3b: 连板高标期 (5板+/6板+) 借鉴高标首阴双严重异动 93%/96%/98% 缓冲限价止盈
  - 3c: 13:45护利参数灵敏度 (时间/触高/回落阈值/取消) vs 一进二 10:30/14:30 vs 未封四板次日 M1 暗牌豁免
"""
import os, sys, json, time, sqlite3
from collections import defaultdict
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
OUT_DIR = f"{SIM}/backtests_astock2/rd017_cross_exit_audit_20261118"
os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, UPG_DIR)
import upgrade_3to4_pit as u3

assert "yfinance" not in sys.modules
FEE = u3.FEE_RATE
IDX_CACHE = json.load(open(u3.IDX_JSON, encoding="utf-8"))
SH300 = IDX_CACHE["sh000300"]
SH_MAP = IDX_CACHE["sh000002"]
SZ_MAP = IDX_CACHE["sz399107"]
CSI_DTS = sorted(SH300.keys())


def csi_ret_pct(s_dt: str, e_dt: str) -> float:
    prevs = [d for d in CSI_DTS if d < s_dt]
    posts = [d for d in CSI_DTS if d <= e_dt]
    p0 = SH300[prevs[-1]] if prevs else SH300[CSI_DTS[0]]
    p1 = SH300[posts[-1]]
    return round((p1 / p0 - 1.0) * 100.0, 2)


WINDOWS = [
    ("full_5y", "2021-11-16", "2026-11-16", csi_ret_pct("2021-11-16", "2026-11-16")),
    ("is_22_23", "2022-01-04", "2023-12-31", csi_ret_pct("2022-01-04", "2023-12-31")),
    ("oos_24_26", "2024-01-01", "2026-11-16", csi_ret_pct("2024-01-01", "2026-11-16")),
    ("y2026_1y", "2026-01-01", "2026-11-16", csi_ret_pct("2026-01-01", "2026-11-16")),
]


def load_5m_and_extra(cand_df: pd.DataFrame, code_bars: dict):
    df_5m_a = ds.dataset(u3.BARS_ALL_5M, format="parquet").scanner(
        columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"],
        filter=(ds.field("date") <= "2026-11-16"),
    ).to_table().to_pandas()
    df_5m_b = ds.dataset(u3.BARS_34_5M, format="parquet").scanner(
        columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"],
        filter=(ds.field("date") <= "2026-11-16"),
    ).to_table().to_pandas()
    df_5m = pd.concat([df_5m_a, df_5m_b], ignore_index=True)
    df_5m.drop_duplicates(["c6", "date", "hhmm_int"], keep="first", inplace=True)
    df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    b5m = {
        (c6, d): grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        for (c6, d), grp in df_5m.groupby(["c6", "date"], sort=False)
    }

    # Seal amount ratio for D3 (sig_date) and D4 (buy_date)
    codes = set(cand_df["code"].astype(str).str.zfill(6).unique())
    con_t = sqlite3.connect(f"file:{u3.DB_ZT_TAPE}?mode=ro", uri=True)
    seal_amt = {}
    for td, sc, sa in con_t.execute("SELECT trade_date, sec_code, seal_amount FROM zt_micro_tape WHERE trade_date <= '2026-11-16'"):
        c6 = str(sc)[:6].zfill(6)
        if c6 in codes and sa is not None:
            seal_amt[(str(td), c6)] = float(sa)
    con_t.close()

    # Daily amount lookup
    d_amt = ds.dataset(u3.A_DAILY_PQ, format="parquet").scanner(
        columns=["date", "ticker", "amount"], filter=(ds.field("date") >= pd.Timestamp("2021-10-01")) & (ds.field("date") <= pd.Timestamp("2026-11-16"))
    ).to_table().to_pandas()
    d_amt["c6"] = d_amt["ticker"].astype(str).str[:6]
    d_amt = d_amt[d_amt["c6"].isin(codes)].copy()
    d_amt["dt"] = d_amt["date"].dt.strftime("%Y-%m-%d")
    amt_map = {(r.c6, r.dt): float(r.amount) for r in d_amt.itertuples(index=False) if pd.notna(r.amount)}

    d3_sr_map = {}
    for r in cand_df.itertuples(index=False):
        c6 = str(r.code).zfill(6); sd = str(r.sig_date)
        sa = seal_amt.get((sd, c6)); am = amt_map.get((c6, sd), 0.0)
        d3_sr_map[(c6, sd)] = (sa / am) if (sa is not None and am > 0) else np.nan

    return b5m, d3_sr_map


def get_double_dev_px_causal(cb: dict, c6: str, cp: int, disc: float) -> float:
    """严格因果 10日100% & 30日200% 双严重异动缓冲止盈价 (复权换算至当日cp口径, 用cp-1指数锚)"""
    if cp <= 0:
        return 99999.0
    imap = SH_MAP if c6.startswith("60") else SZ_MAP
    ir = imap.get(str(cb["dts"][cp - 1]))
    if not ir:
        return 99999.0
    adj_cp = float(cb["adjf"][cp])
    bp = 99999.0
    for k in range(1, min(11, cp + 1)):
        p = cp - k
        bi = imap.get(str(cb["dts"][p]))
        bc = float(cb["close"][p]) * float(cb["adjf"][p]) / adj_cp
        if bi and bc > 0:
            bp = min(bp, bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0)))
    for k in range(1, min(31, cp + 1)):
        p = cp - k
        bi = imap.get(str(cb["dts"][p]))
        bc = float(cb["close"][p]) * float(cb["adjf"][p]) / adj_cp
        if bi and bc > 0:
            bp = min(bp, bc * (1.0 + (2.0 - disc) + (ir / bi - 1.0)))
    return round(float(bp), 2)


def sim_3to4_exit_variant(
    c6: str, cb: dict, pos: int, b5m: dict, xq_cnt_2d: int, d3_sr: float,
    unsealed_mode: str = "cut_weak",  # cut_weak | cut_weak_m1 | d5_1030_vwap | d5_1030_vwap_m1 | open_lt_05
    relay_mode: str = "pm1345",  # pm1345 | v19_1030_1430 | eod_break
    pm_hhmm: int = 1345,
    pm_peak_pct: float = 0.085,
    pm_drop_pct: float = 0.050,
    d5_high_open_thr: float | None = None,
    use_yang_imm: bool = True,
    dev_disc: float | None = None,
    dev_min_board: int = 5,  # 5 means active on 5b+ (D5 after 4b sealed); 6 means active on 6b+ (D6 after 5b sealed)
) -> tuple:
    n = len(cb["dts"])

    def _run_zt_hold(start_p: int, boards_at_start: int):
        k = start_p + 1
        imm_used = False
        boards = boards_at_start
        while k < n:
            if bool(cb["is_yizi_dt"][k]):
                k += 1; continue
            dt_s = cb["dts"][k]
            ok, pck, clk, ztk = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k]), float(cb["zt_px"][k])
            hk = float(cb["high"][k])
            dtk = round(pck * 0.90, 2)
            if k > start_p + 1 and bool(cb["is_yizi_dt"][k - 1]):
                return dt_s, ok, float(cb["adjf"][k]), k - pos, 925

            # 3a: D5 ultra-high open non-yizi take profit (borrowed from 2to3 V2.0)
            if d5_high_open_thr is not None and k == pos + 1 and boards_at_start == 4:
                d5_op = ok / pck - 1.0 if pck > 0 else 0.0
                if (d5_op > d5_high_open_thr) and (ok < ztk - 0.005):
                    return dt_s, ok, float(cb["adjf"][k]), k - pos, 925

            # 3b: High Dragon double severe abnormality buffer
            pl_dev = None
            if dev_disc is not None and (boards + 1) >= dev_min_board:
                pl_dev = get_double_dev_px_causal(cb, c6, k, dev_disc)
                if ok >= pl_dev and ok > dtk + 0.005:
                    return dt_s, ok, float(cb["adjf"][k]), k - pos, 925

            arr = b5m.get((c6, dt_s))
            if arr is not None and len(arr) > 0:
                if relay_mode == "pm1345":
                    peak = ok
                    for row in arr:
                        hh, bo, bh, bl, bc = int(row[0]), row[1], row[2], row[3], row[4]
                        if bh <= dtk + 0.005:
                            continue
                        if pl_dev is not None and bh >= pl_dev:
                            px_d = float(max(bo, pl_dev))
                            if px_d > dtk + 0.005:
                                return dt_s, px_d, float(cb["adjf"][k]), k - pos, hh
                        if hh >= pm_hhmm and peak >= pck * (1.0 + pm_peak_pct) and bl <= pck * (1.0 + pm_drop_pct) and bc < ztk - 0.01:
                            return dt_s, float(min(bo, pck * (1.0 + pm_drop_pct))), float(cb["adjf"][k]), k - pos, hh
                        if bh > peak:
                            peak = bh
                elif relay_mode == "v19_1030_1430":
                    cum_v = cum_a = 0.0
                    sealed_1030 = False
                    n5 = len(arr)
                    for bi in range(n5):
                        hh, bo, bh, bl, bc, bv, ba = int(arr[bi, 0]), arr[bi, 1], arr[bi, 2], arr[bi, 3], arr[bi, 4], arr[bi, 5], arr[bi, 6]
                        if pl_dev is not None and bh >= pl_dev and bh > dtk + 0.005:
                            px_d = float(max(bo, pl_dev))
                            if px_d > dtk + 0.005:
                                return dt_s, px_d, float(cb["adjf"][k]), k - pos, hh
                        cum_v += bv; cum_a += ba
                        if hh == 1030:
                            vwap_1030 = cum_a / cum_v if cum_v > 0 else bc
                            if bc >= ztk - 0.01:
                                sealed_1030 = True
                            elif bc < vwap_1030:
                                px = float(arr[bi + 1, 1]) if bi + 1 < n5 else float(bc)
                                ehh = int(arr[bi + 1, 0]) if bi + 1 < n5 else 1030
                                if px > dtk + 0.005:
                                    return dt_s, px, float(cb["adjf"][k]), k - pos, ehh
                        if sealed_1030 and hh >= 1430 and bc < ztk - 0.01 and bi + 1 < n5:
                            px = float(arr[bi + 1, 1])
                            if px > dtk + 0.005:
                                return dt_s, px, float(cb["adjf"][k]), k - pos, int(arr[bi + 1, 0])
                elif relay_mode == "eod_break":
                    if pl_dev is not None:
                        for row in arr:
                            hh, bo, bh = int(row[0]), row[1], row[2]
                            if bh <= dtk + 0.005: continue
                            if bh >= pl_dev:
                                px_d = float(max(bo, pl_dev))
                                if px_d > dtk + 0.005:
                                    return dt_s, px_d, float(cb["adjf"][k]), k - pos, hh
            elif pl_dev is not None and hk >= pl_dev and pl_dev > dtk + 0.005:
                return dt_s, pl_dev, float(cb["adjf"][k]), k - pos, 1030

            if bool(cb["is_zt"][k]):
                boards += 1; k += 1; continue
            if use_yang_imm and (not imm_used) and (clk > ok) and (clk >= pck):
                imm_used = True; k += 1; continue
            return dt_s, clk, float(cb["adjf"][k]), max(1, k - pos), 1500
        k = n - 1
        return cb["dts"][k], float(cb["close"][k]), float(cb["adjf"][k]), max(1, k - pos), 1500

    if not bool(cb["is_zt"][pos]):
        k = pos + 1
        while k < n and bool(cb["is_yizi_dt"][k]):
            k += 1
        k = min(k, n - 1)
        o4, c4, p4 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])
        o5, p5, c5, zt5 = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k]), float(cb["zt_px"][k])
        dt5 = round(p5 * 0.90, 2)
        if k > pos + 1:
            return cb["dts"][k], o5, float(cb["adjf"][k]), k - pos, 925

        is_dark_m1 = (xq_cnt_2d < 4) and (np.isnan(d3_sr) or d3_sr < 0.25)

        if unsealed_mode in ("cut_weak", "cut_weak_m1"):
            keep_d5 = (c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005)
            if unsealed_mode == "cut_weak_m1" and is_dark_m1 and (o5 >= p5 * 0.935):
                keep_d5 = True
            if not keep_d5:
                return cb["dts"][k], o5, float(cb["adjf"][k]), max(1, k - pos), 925
            if bool(cb["is_zt"][k]):
                return _run_zt_hold(k, 4)
            return cb["dts"][k], c5, float(cb["adjf"][k]), max(1, k - pos), 1500

        if unsealed_mode == "open_lt_05":
            if o5 < p5 * 1.005:
                return cb["dts"][k], o5, float(cb["adjf"][k]), max(1, k - pos), 925
            if bool(cb["is_zt"][k]):
                return _run_zt_hold(k, 4)
            return cb["dts"][k], c5, float(cb["adjf"][k]), max(1, k - pos), 1500

        if unsealed_mode in ("d5_1030_vwap", "d5_1030_vwap_m1"):
            arr = b5m.get((c6, cb["dts"][k]))
            if arr is not None and len(arr) >= 12:
                cum_v = cum_a = 0.0
                n5 = len(arr)
                for bi in range(n5):
                    hh, bc, bv, ba = int(arr[bi, 0]), arr[bi, 4], arr[bi, 5], arr[bi, 6]
                    cum_v += bv; cum_a += ba
                    if hh == 1030:
                        vwap_1030 = cum_a / cum_v if cum_v > 0 else bc
                        exempt = (unsealed_mode == "d5_1030_vwap_m1") and is_dark_m1
                        if bc < zt5 - 0.01 and bc < vwap_1030 and (not exempt):
                            px = float(arr[bi + 1, 1]) if bi + 1 < n5 else float(bc)
                            ehh = int(arr[bi + 1, 0]) if bi + 1 < n5 else 1030
                            if px > dt5 + 0.005:
                                return cb["dts"][k], px, float(cb["adjf"][k]), 1, ehh
                        break
            if bool(cb["is_zt"][k]):
                return _run_zt_hold(k, 4)
            return cb["dts"][k], c5, float(cb["adjf"][k]), 1, 1500

        if unsealed_mode == "hold_all_d5_eod":
            if bool(cb["is_zt"][k]):
                return _run_zt_hold(k, 4)
            return cb["dts"][k], c5, float(cb["adjf"][k]), 1, 1500

    return _run_zt_hold(pos, 4)


def eval_3to4_windows(raw_df: pd.DataFrame) -> dict:
    slot_df = u3.sim_single_slot(raw_df)
    res = {}
    for wn, sdt, edt, csip in WINDOWS:
        sr = raw_df[(raw_df["buy_date"] >= sdt) & (raw_df["buy_date"] <= edt)]
        ss = slot_df[(slot_df["buy_date"] >= sdt) & (slot_df["buy_date"] <= edt)]
        if ss.empty:
            s_stats = {"n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0, "nav": 1.0, "ret_pct": 0.0, "mdd_pct": 0.0, "trim3_nav": 1.0, "trim5_nav": 1.0, "csi300_pct": csip, "excess_pp": round(-csip, 2)}
        else:
            rr = ss["net_ret"].to_numpy(dtype=float)
            w, ls = rr[rr > 0], rr[rr <= 0]
            nc = np.cumprod(1.0 + rr)
            pk = np.maximum.accumulate(np.insert(nc, 0, 1.0))[1:]
            s_rt = np.sort(rr)
            s_stats = {
                "n": int(len(rr)), "wr_pct": round(float((rr > 0).mean() * 100.0), 2),
                "plr": round(float(w.mean() / abs(ls.mean())) if (len(w) and len(ls) and ls.mean() < 0) else 99.0, 2),
                "mean_pct": round(float(rr.mean() * 100.0), 2),
                "nav": round(float(nc[-1]), 4), "ret_pct": round((float(nc[-1]) - 1.0) * 100.0, 2),
                "mdd_pct": round(float(np.max((pk - nc) / pk) * 100.0), 2),
                "trim3_nav": round(float(np.prod(1.0 + s_rt[:-3])) if len(rr) > 3 else 1.0, 4),
                "trim5_nav": round(float(np.prod(1.0 + s_rt[:-5])) if len(rr) > 5 else 1.0, 4),
                "csi300_pct": csip, "excess_pp": round((float(nc[-1]) - 1.0) * 100.0 - csip, 2),
            }
        if sr.empty:
            eq_stats = {"raw_n": 0, "days_n": 0, "wr_pct": 0.0, "plr": 0.0, "nav": 1.0, "ret_pct": 0.0, "mdd_pct": 0.0, "trim3_nav": 1.0, "trim5_nav": 1.0, "csi300_pct": csip, "excess_pp": round(-csip, 2)}
        else:
            dq = sr.groupby("buy_date")["net_ret"].mean().sort_index().to_numpy(dtype=float)
            dw, dls = dq[dq > 0], dq[dq <= 0]
            dnc = np.cumprod(1.0 + dq)
            dpk = np.maximum.accumulate(np.insert(dnc, 0, 1.0))[1:]
            dsr = np.sort(dq)
            eq_stats = {
                "raw_n": int(len(sr)), "days_n": int(len(dq)),
                "wr_pct": round(float((dq > 0).mean() * 100.0), 2),
                "plr": round(float(dw.mean() / abs(dls.mean())) if (len(dw) and len(dls) and dls.mean() < 0) else 99.0, 2),
                "nav": round(float(dnc[-1]), 4), "ret_pct": round((float(dnc[-1]) - 1.0) * 100.0, 2),
                "mdd_pct": round(float(np.max((dpk - dnc) / dpk) * 100.0), 2),
                "trim3_nav": round(float(np.prod(1.0 + dsr[:-3])) if len(dq) > 3 else 1.0, 4),
                "trim5_nav": round(float(np.prod(1.0 + dsr[:-5])) if len(dq) > 5 else 1.0, 4),
                "csi300_pct": csip, "excess_pp": round((float(dnc[-1]) - 1.0) * 100.0 - csip, 2),
            }
        res[wn] = {"single_slot": s_stats, "daily_eq": eq_stats}
    return res


def main():
    t0 = time.time()
    res = u3.run_causal_pipeline("2026-11-16", verbose=False)
    cand_df = res["cand_df"]
    sc_v40 = res["sc_v40"]
    code_bars = res["code_bars"]
    p_1030 = res["p_1030"]
    b5m, d3_sr_map = load_5m_and_extra(cand_df, code_bars)

    # Extract eligible 10:30-bought candidates (score >= 90)
    idx_90 = [i for i in np.where(sc_v40 >= 90.0)[0] if p_1030[i] is not None]
    base_items = []
    for i in idx_90:
        pi = p_1030[i]
        r = cand_df.iloc[i]
        c6 = str(r["code"]).zfill(6); bd = str(r["buy_date"]); sd = str(r["sig_date"])
        cb = code_bars[c6]; pos = cb["date_to_pos"][bd]
        base_items.append({
            "idx": i, "code": c6, "name": str(r["name"]), "buy_date": bd, "sig_date": sd,
            "buy_hhmm": int(pi["buy_hhmm"]), "buy_price_exact": float(pi["buy_price"]),
            "score": int(round(float(sc_v40[i]))),
            "priority_score": float(sc_v40[i]) * 10.0 + float(r["prio_3to4"]) * 0.1,
            "xq_cnt_2d": int(r["xq_cnt_2d"]),
            "d3_sr": float(d3_sr_map.get((c6, sd), np.nan)),
            "pos": pos, "cb": cb, "ref_ret": float(pi["net_ret"]),
            "ref_ed": str(pi["exit_date"]), "ref_eh": int(pi["exit_hhmm"]),
        })

    # Verify exact baseline reproduction (95 std / 31 strict, 0 error)
    def run_exp(kw):
        rows = []
        for it in base_items:
            cb, pos, c6 = it["cb"], it["pos"], it["code"]
            # Use exact buy_price computed in p_1030 (unrounded internal float in upgrade_3to4_pit)
            bpx_raw, _ = u3._sim_buy_5m(c6, it["buy_date"], cb, pos, b5m, 1030)
            ex_dt, spx, adjs, hb, shh = sim_3to4_exit_variant(c6, cb, pos, b5m, it["xq_cnt_2d"], it["d3_sr"], **kw)
            nr = (spx * adjs) / (bpx_raw * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0
            rows.append({
                "code": c6, "name": it["name"], "buy_date": it["buy_date"],
                "buy_hhmm": it["buy_hhmm"], "buy_price": it["buy_price_exact"],
                "exit_date": ex_dt, "exit_hhmm": shh, "exit_price": round(spx, 2),
                "hold_bars": hb, "net_ret": float(nr), "score": it["score"],
                "priority_score": it["priority_score"],
            })
        return pd.DataFrame(rows)

    df_base = run_exp(dict(unsealed_mode="cut_weak", relay_mode="pm1345"))
    slot_base_std = u3.sim_single_slot(df_base)
    slot_base_str = u3.sim_single_slot(df_base[df_base["score"] >= 102])
    ref_std = pd.read_csv(f"{UPG_DIR}/ledger_upg_3to4_std.csv")
    ref_str = pd.read_csv(f"{UPG_DIR}/ledger_upg_3to4_strict.csv")
    assert len(slot_base_std) == len(ref_std) == 95 and (slot_base_std["net_ret"].to_numpy() - ref_std["net_ret"].to_numpy()).max() < 1e-6
    assert len(slot_base_str) == len(ref_str) == 31 and (slot_base_str["net_ret"].to_numpy() - ref_str["net_ret"].to_numpy()).max() < 1e-6

    # 5m coverage check across holding days
    def cov_5m_check(sub_led):
        d5_tot = d5_cov = hold_tot = hold_cov = 0
        for r in sub_led.itertuples(index=False):
            c6 = str(r.code).zfill(6); cb = code_bars[c6]
            pb = cb["date_to_pos"][r.buy_date]; pe = cb["date_to_pos"][r.exit_date]
            if pb + 1 < len(cb["dts"]):
                d5_tot += 1; d5_cov += int((c6, cb["dts"][pb + 1]) in b5m)
            for k in range(pb + 1, pe + 1):
                hold_tot += 1; hold_cov += int((c6, cb["dts"][k]) in b5m)
        return {
            "d5_5m_cov": f"{d5_cov}/{d5_tot}", "d5_5m_cov_pct": round(d5_cov / max(1, d5_tot) * 100.0, 2),
            "hold_days_5m_cov": f"{hold_cov}/{hold_tot}", "hold_days_5m_cov_pct": round(hold_cov / max(1, hold_tot) * 100.0, 2),
        }

    cov_info = {"std90_95trades": cov_5m_check(slot_base_std), "strict102_31trades": cov_5m_check(slot_base_str)}
    print("5m Coverage 3to4:", cov_info)

    experiments = [
        ("baseline_v40", "baseline", dict(unsealed_mode="cut_weak", relay_mode="pm1345")),
        # 3a: D5 high open take profit (borrowed from 2to3 V2.0)
        ("3a_d5_ho_gt_88", "3a_d5_high_open", dict(unsealed_mode="cut_weak", relay_mode="pm1345", d5_high_open_thr=0.088)),
        ("3a_d5_ho_gt_90", "3a_d5_high_open", dict(unsealed_mode="cut_weak", relay_mode="pm1345", d5_high_open_thr=0.090)),
        ("3a_d5_ho_gt_92", "3a_d5_high_open", dict(unsealed_mode="cut_weak", relay_mode="pm1345", d5_high_open_thr=0.092)),
        # 3b: Severe abnormality buffer (borrowed from High Dragon V5.1)
        ("3b_dev93_5b", "3b_severe_abnormality", dict(unsealed_mode="cut_weak", relay_mode="pm1345", dev_disc=0.07, dev_min_board=5)),
        ("3b_dev96_5b", "3b_severe_abnormality", dict(unsealed_mode="cut_weak", relay_mode="pm1345", dev_disc=0.04, dev_min_board=5)),
        ("3b_dev98_5b", "3b_severe_abnormality", dict(unsealed_mode="cut_weak", relay_mode="pm1345", dev_disc=0.02, dev_min_board=5)),
        ("3b_dev93_6b", "3b_severe_abnormality", dict(unsealed_mode="cut_weak", relay_mode="pm1345", dev_disc=0.07, dev_min_board=6)),
        ("3b_dev96_6b", "3b_severe_abnormality", dict(unsealed_mode="cut_weak", relay_mode="pm1345", dev_disc=0.04, dev_min_board=6)),
        ("3b_dev98_6b", "3b_severe_abnormality", dict(unsealed_mode="cut_weak", relay_mode="pm1345", dev_disc=0.02, dev_min_board=6)),
        # 3c: 13:45 sensitivity, 1to2 V19 (10:30/14:30), M1 dark-card exempt on unsealed D4
        ("3c_no_pm1345_eod_break", "3c_guard_and_unsealed", dict(unsealed_mode="cut_weak", relay_mode="eod_break")),
        ("3c_pm1330_85_50", "3c_guard_and_unsealed", dict(unsealed_mode="cut_weak", relay_mode="pm1345", pm_hhmm=1330, pm_peak_pct=0.085, pm_drop_pct=0.050)),
        ("3c_pm1400_85_50", "3c_guard_and_unsealed", dict(unsealed_mode="cut_weak", relay_mode="pm1345", pm_hhmm=1400, pm_peak_pct=0.085, pm_drop_pct=0.050)),
        ("3c_pm1415_85_50", "3c_guard_and_unsealed", dict(unsealed_mode="cut_weak", relay_mode="pm1345", pm_hhmm=1415, pm_peak_pct=0.085, pm_drop_pct=0.050)),
        ("3c_pm1345_75_50", "3c_guard_and_unsealed", dict(unsealed_mode="cut_weak", relay_mode="pm1345", pm_hhmm=1345, pm_peak_pct=0.075, pm_drop_pct=0.050)),
        ("3c_pm1345_92_50", "3c_guard_and_unsealed", dict(unsealed_mode="cut_weak", relay_mode="pm1345", pm_hhmm=1345, pm_peak_pct=0.092, pm_drop_pct=0.050)),
        ("3c_pm1345_85_40", "3c_guard_and_unsealed", dict(unsealed_mode="cut_weak", relay_mode="pm1345", pm_hhmm=1345, pm_peak_pct=0.085, pm_drop_pct=0.040)),
        ("3c_pm1345_85_60", "3c_guard_and_unsealed", dict(unsealed_mode="cut_weak", relay_mode="pm1345", pm_hhmm=1345, pm_peak_pct=0.085, pm_drop_pct=0.060)),
        ("3c_pm1345_no_imm", "3c_guard_and_unsealed", dict(unsealed_mode="cut_weak", relay_mode="pm1345", use_yang_imm=False)),
        ("3c_v19_1030_1430_noimm", "3c_guard_and_unsealed", dict(unsealed_mode="cut_weak", relay_mode="v19_1030_1430", use_yang_imm=False)),
        ("3c_v19_1030_1430_imm", "3c_guard_and_unsealed", dict(unsealed_mode="cut_weak", relay_mode="v19_1030_1430", use_yang_imm=True)),
        ("3c_unsealed_cut_weak_m1", "3c_guard_and_unsealed", dict(unsealed_mode="cut_weak_m1", relay_mode="pm1345")),
        ("3c_unsealed_d5_1030_vwap", "3c_guard_and_unsealed", dict(unsealed_mode="d5_1030_vwap", relay_mode="pm1345")),
        ("3c_unsealed_d5_1030_vwap_m1", "3c_guard_and_unsealed", dict(unsealed_mode="d5_1030_vwap_m1", relay_mode="pm1345")),
        ("3c_unsealed_hold_all_d5", "3c_guard_and_unsealed", dict(unsealed_mode="hold_all_d5_eod", relay_mode="pm1345")),
    ]

    results = []
    for name, grp, kw in experiments:
        df_r = run_exp(kw)
        m_std = eval_3to4_windows(df_r)
        m_str = eval_3to4_windows(df_r[df_r["score"] >= 102])
        results.append({"name": name, "group": grp, "params": kw, "std90": m_std, "strict102": m_str})

    out = {"coverage_5m": cov_info, "baseline_repro_verified": True, "experiments": results}
    with open(f"{OUT_DIR}/task3_3to4_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE Task 3 in {time.time()-t0:.1f}s] Summary std90 (95b) & strict102 (31b):")
    for e in results:
        s90 = e["std90"]; s102 = e["strict102"]
        f5, is_, oo, y26 = s90["full_5y"]["single_slot"], s90["is_22_23"]["single_slot"], s90["oos_24_26"]["single_slot"], s90["y2026_1y"]["single_slot"]
        eq5 = s90["full_5y"]["daily_eq"]
        f5_s = s102["full_5y"]["single_slot"]
        print(f"  {e['name']:28s} | std90: 5Y={f5['nav']:6.2f}x(WR={f5['wr_pct']:4.1f}%,MDD={f5['mdd_pct']:4.1f}%,T5={f5['trim5_nav']:5.2f}x) IS={is_['nav']:5.2f}x OOS={oo['nav']:6.2f}x 26={y26['nav']:4.2f}x EQ={eq5['nav']:6.2f}x | S102: 5Y={f5_s['nav']:5.2f}x(OOS={s102['oos_24_26']['single_slot']['nav']:5.2f},T5={f5_s['trim5_nav']:4.2f})")


if __name__ == "__main__":
    main()
