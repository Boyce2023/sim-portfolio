#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
task2_2to3_exit_audit.py — 二进三 V2.0 (s_2to3) 跨策略卖点移植实证
100% 复现 upgrade_2to3_pit.py 基准 (94笔std / 35笔strict, 0误差), 并在 IS/OOS/全5年/2026 双轨对比:
  - 2a: 未封三板次日分流 (15:00 vs 10:30 VWAP vs M1暗牌豁免 vs 低开止损 vs V1 cut_weak)
  - 2b: 封死三板连板期卖点 (13:45护利 vs 一进二 10:30+14:30 vs 高标双严重异动93/96/98缓冲止盈[4b+/5b+] vs 组合)
"""
import os, sys, json, time, sqlite3
from collections import defaultdict
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
OUT_DIR = f"{SIM}/backtests_astock2/rd017_cross_exit_audit_20261118"
os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, UPG_DIR)
import upgrade_2to3_pit as u2

assert "yfinance" not in sys.modules
FEE = u2.FEE_ROUNDTRIP
IDX_CACHE = json.load(open(u2.IDX_JSON, encoding="utf-8"))
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
    ("is_21_23_canon", "2021-11-16", "2023-12-31", csi_ret_pct("2021-11-16", "2023-12-31")),
    ("is_21_23_full", "2021-01-04", "2023-12-31", csi_ret_pct("2021-01-04", "2023-12-31")),
    ("oos_24_26", "2024-01-01", "2026-11-16", csi_ret_pct("2024-01-01", "2026-11-16")),
    ("y2026_1y", "2026-01-01", "2026-11-16", csi_ret_pct("2026-01-01", "2026-11-16")),
]


def load_extra_pit_data(da: pd.DataFrame, gated: pd.DataFrame):
    """加载只读雪球帖子(<D4 09:25)与D3封单金额比率、以及每只股票历史日线数组供双严重异动计算"""
    codes = set(gated["code"].astype(str).str.zfill(6).unique())
    xq_seen = defaultdict(set)
    xq_posts = defaultdict(list)
    con1 = sqlite3.connect(f"file:{SIM}/data/xueqiu_guba_5y_pit.db?mode=ro", uri=True)
    for sym, pid, cts in con1.execute(
        "SELECT symbol, post_id, created_time_str FROM xueqiu_posts WHERE created_time_str >= '2020-12-01' AND created_time_str <= '2026-11-16 23:59:59'"
    ):
        c6 = str(sym)[:6].zfill(6)
        if c6 in codes and cts:
            p = str(pid).replace("xq_", "")
            if p not in xq_seen[c6]:
                xq_seen[c6].add(p); xq_posts[c6].append(str(cts))
    con1.close()
    con2 = sqlite3.connect(f"file:{SIM}/data/astock_community_5y_pit.db?mode=ro", uri=True)
    for sym, pid, cts in con2.execute(
        "SELECT symbol, post_id, pub_datetime_cst FROM community_posts WHERE source='xueqiu' AND pub_datetime_cst >= '2020-12-01' AND pub_datetime_cst <= '2026-11-16 23:59:59'"
    ):
        c6 = str(sym)[:6].zfill(6)
        if c6 in codes and cts:
            p = str(pid).replace("xq_", "")
            if p not in xq_seen[c6]:
                xq_seen[c6].add(p); xq_posts[c6].append(str(cts))
    con2.close()
    xq_arr = {c6: np.sort(np.array(v, dtype=str)) for c6, v in xq_posts.items()}

    # ZT seal amount for D3
    con_t = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    seal_amt = {}
    for td, sc, sa in con_t.execute("SELECT trade_date, sec_code, seal_amount FROM zt_micro_tape WHERE trade_date <= '2026-11-16'"):
        c6 = str(sc)[:6].zfill(6)
        if c6 in codes and sa is not None:
            seal_amt[(str(td), c6)] = float(sa)
    con_t.close()

    # Build per-code daily arrays for double_dev (needs up to 31 prior trading days)
    da_sub = da[da["c6"].isin(codes)].copy()
    code_hist = {}
    amt_map = {}
    for c6, grp in da_sub.groupby("c6", sort=False):
        dts = grp["dt"].to_numpy(dtype=str)
        cls = grp["close"].to_numpy(dtype=float)
        amt = grp["amount"].to_numpy(dtype=float)
        code_hist[c6] = {"dts": dts, "close": cls, "pos": {d: i for i, d in enumerate(dts)}}
        for d, a in zip(dts, amt):
            amt_map[(c6, str(d))] = float(a)

    # Precompute D3 seal ratio & D4 pre-09:25 xq count
    xq_d4_map, d3_sr_map = {}, {}
    for r in gated.itertuples(index=False):
        c6 = str(r.code).zfill(6)
        bd = str(r.buy_date)
        d1_dt = str(r.d1_date)
        ch = code_hist.get(c6)
        p_bd = ch["pos"].get(bd, -1) if ch else -1
        if ch and 0 <= p_bd < len(ch["dts"]) - 1:
            d4_dt = str(ch["dts"][p_bd + 1])
            arr = xq_arr.get(c6)
            if arr is not None and len(arr) > 0:
                hi = int(np.searchsorted(arr, f"{d4_dt} 09:25:00", side="left"))
                lo = int(np.searchsorted(arr, f"{d1_dt} 00:00:00", side="left"))
                xq_d4_map[(c6, bd)] = max(0, hi - lo)
            else:
                xq_d4_map[(c6, bd)] = 0
        else:
            xq_d4_map[(c6, bd)] = int(r.xq_cnt_tot)
        sa3 = seal_amt.get((bd, c6))
        a3 = amt_map.get((c6, bd), 0.0)
        d3_sr_map[(c6, bd)] = (sa3 / a3) if (sa3 is not None and a3 > 0) else np.nan

    return code_hist, xq_d4_map, d3_sr_map


def get_double_dev_px_causal(code_hist: dict, c6: str, dk: str, disc: float) -> float:
    """严格因果 10日100% & 30日200% 双严重异动缓冲止盈价 (参考前一日收盘指数作为盘前挂单锚)"""
    ch = code_hist.get(c6)
    if not ch:
        return 99999.0
    cp = ch["pos"].get(dk, -1)
    if cp <= 0:
        return 99999.0
    imap = SH_MAP if c6.startswith("60") else SZ_MAP
    prev_dt = str(ch["dts"][cp - 1])
    ir = imap.get(prev_dt)
    if not ir:
        return 99999.0
    bp = 99999.0
    for k in range(1, min(11, cp + 1)):
        p = cp - k
        bi = imap.get(str(ch["dts"][p]))
        bc = ch["close"][p]
        if bi and bc > 0:
            bp = min(bp, bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0)))
    for k in range(1, min(31, cp + 1)):
        p = cp - k
        bi = imap.get(str(ch["dts"][p]))
        bc = ch["close"][p]
        if bi and bc > 0:
            bp = min(bp, bc * (1.0 + (2.0 - disc) + (ir / bi - 1.0)))
    return round(float(bp), 2)


def sim_2to3_variant(
    gated: pd.DataFrame, all_dts: list, dt_idx: dict, plook: dict, b5m: dict,
    code_hist: dict, xq_d4_map: dict, d3_sr_map: dict,
    unsealed_mode: str = "eod1500",
    relay_mode: str = "pm1345",
    d4_high_open_thr: float | None = 0.092,
    use_yang_imm: bool = True,
    dev_disc: float | None = None,
    dev_min_board: int = 4,  # 4 means active on 4b+ (D4 after 3b sealed); 5 means active on 5b+ (D5 after 4b sealed)
    use_m1_d4_exempt: bool = False,
) -> tuple[list, list, list]:
    rets, eds, ehs = [], [], []
    for r in gated.itertuples(index=False):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        pos = dt_idx.get(bd, -1)
        if pos < 0 or pos >= len(all_dts) - 1 or not plook.get((c6, bd)):
            rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
            continue
        buy_px = round(float(r.prev_close) * (1.0 + float(r.open_pct)), 2)

        def run_zt_hold(sp_idx: int, boards_at_sp: int):
            k = sp_idx + 1
            used_imm = False
            boards = boards_at_sp
            while k < len(all_dts) and (k - pos <= 18):
                dk = all_dts[k]
                bk = plook.get((c6, dk))
                if not bk:
                    k += 1; continue
                ok, hk, lk, ck, pck, ztk, dtk, iztk, idtk, iyzk, iyzdtk = bk
                if iyzdtk:
                    k += 1; continue
                if k > sp_idx + 1:
                    pb = plook.get((c6, all_dts[k - 1]))
                    if pb and (pb[10] or pb[8]):
                        return (ok / buy_px) * (1.0 - FEE) - 1.0, dk, 925

                # D4 ultra-high open non-yizi take profit (only right after D3 sealed)
                if d4_high_open_thr is not None and k == pos + 1 and boards_at_sp == 3:
                    d4_op = ok / pck - 1.0 if pck > 0 else 0.0
                    if (d4_op > d4_high_open_thr) and (ok < ztk - 0.005):
                        return (ok / buy_px) * (1.0 - FEE) - 1.0, dk, 925

                # High Dragon double severe abnormality limit sell (active when attempting boards+1 >= dev_min_board)
                pl_dev = None
                if dev_disc is not None and (boards + 1) >= dev_min_board:
                    pl_dev = get_double_dev_px_causal(code_hist, c6, dk, dev_disc)
                    if ok >= pl_dev and ok > dtk + 0.005:
                        return (ok / buy_px) * (1.0 - FEE) - 1.0, dk, 925

                arr = b5m.get((c6, dk))
                # Check 5m chronological order: dev limit sell vs intraday exit rule
                if arr is not None and len(arr) > 0:
                    if relay_mode == "pm1345":
                        pk = ok
                        for row5 in arr:
                            hh, bo, bh, bl, bc = int(row5[0]), row5[1], row5[2], row5[3], row5[4]
                            if bh <= dtk + 0.005:
                                continue
                            if pl_dev is not None and bh >= pl_dev:
                                px_d = max(bo, pl_dev)
                                if px_d > dtk + 0.005:
                                    return (px_d / buy_px) * (1.0 - FEE) - 1.0, dk, hh
                            if hh >= 1345 and pk >= pck * 1.085 and bl <= pck * 1.050 and bc < ztk - 0.01:
                                px = min(bo, pck * 1.050)
                                if px > dtk + 0.005:
                                    return (px / buy_px) * (1.0 - FEE) - 1.0, dk, hh
                            if bh > pk:
                                pk = bh
                    elif relay_mode == "v19_1030_1430":
                        exempt_d4 = False
                        if use_m1_d4_exempt and k == pos + 1:
                            op_k = ok / pck - 1.0 if pck > 0 else 0.0
                            xq_d4 = xq_d4_map.get((c6, bd), 99)
                            sr_d3 = d3_sr_map.get((c6, bd), np.nan)
                            if (-0.065 <= op_k <= 0.025) and (xq_d4 < 4) and (np.isnan(sr_d3) or sr_d3 < 0.25):
                                exempt_d4 = True

                        cum_v = cum_a = 0.0
                        sealed_at_1030 = False
                        n5 = len(arr)
                        for bi in range(n5):
                            hh, bo, bh, bl, bc, bv, ba = int(arr[bi, 0]), arr[bi, 1], arr[bi, 2], arr[bi, 3], arr[bi, 4], arr[bi, 5], arr[bi, 6]
                            if pl_dev is not None and bh >= pl_dev and bh > dtk + 0.005:
                                px_d = max(bo, pl_dev)
                                if px_d > dtk + 0.005:
                                    return (px_d / buy_px) * (1.0 - FEE) - 1.0, dk, hh
                            cum_v += bv; cum_a += ba
                            if hh == 1030:
                                vwap_1030 = cum_a / cum_v if cum_v > 0 else bc
                                if bc >= ztk - 0.01:
                                    sealed_at_1030 = True
                                elif bc < vwap_1030 and (not exempt_d4):
                                    px = float(arr[bi + 1, 1]) if bi + 1 < n5 else float(bc)
                                    ehh = int(arr[bi + 1, 0]) if bi + 1 < n5 else 1030
                                    if px > dtk + 0.005:
                                        return (px / buy_px) * (1.0 - FEE) - 1.0, dk, ehh
                            if sealed_at_1030 and hh >= 1430 and bc < ztk - 0.01 and bi + 1 < n5:
                                px = float(arr[bi + 1, 1])
                                if px > dtk + 0.005:
                                    return (px / buy_px) * (1.0 - FEE) - 1.0, dk, int(arr[bi + 1, 0])
                elif pl_dev is not None and hk >= pl_dev and pl_dev > dtk + 0.005:
                    return (pl_dev / buy_px) * (1.0 - FEE) - 1.0, dk, 1030

                if iztk:
                    boards += 1; k += 1; continue
                if idtk:
                    k += 1; continue
                if use_yang_imm and (not used_imm) and (ck > ok) and (ck >= pck):
                    used_imm = True; k += 1; continue
                return (ck / buy_px) * (1.0 - FEE) - 1.0, dk, 1500
            return float(r.ret_opn_cc), str(r.exit_dt_cc), int(r.exit_hh_cc)

        b3 = plook[(c6, bd)]
        if b3[7]:
            rv, edv, ehv = run_zt_hold(pos, 3)
            rets.append(rv); eds.append(edv); ehs.append(ehv)
            continue

        # Unsealed D3 branch
        k = pos + 1
        while k < len(all_dts):
            bk = plook.get((c6, all_dts[k]))
            if bk and not bk[10]:
                break
            k += 1
        if k >= len(all_dts):
            rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
            continue
        dk = all_dts[k]
        ok, hk, lk, ck, pck, ztk, dtk, iztk, idtk, iyzk, iyzdtk = plook[(c6, dk)]
        if k > pos + 1:
            rets.append((ok / buy_px) * (1.0 - FEE) - 1.0); eds.append(dk); ehs.append(925)
            continue

        d4_op = ok / pck - 1.0 if pck > 0 else 0.0
        # Check open cut conditions for unsealed D3
        if unsealed_mode == "v1_cut_weak_open_lt_05":
            if d4_op < 0.005:
                rets.append((ok / buy_px) * (1.0 - FEE) - 1.0); eds.append(dk); ehs.append(925); continue
        elif unsealed_mode in ("open_lt_m3", "open_m3_plus_1030_vwap"):
            if d4_op < -0.03:
                rets.append((ok / buy_px) * (1.0 - FEE) - 1.0); eds.append(dk); ehs.append(925); continue
        elif unsealed_mode == "open_lt_m2":
            if d4_op < -0.02:
                rets.append((ok / buy_px) * (1.0 - FEE) - 1.0); eds.append(dk); ehs.append(925); continue
        elif unsealed_mode == "open_lt_m4":
            if d4_op < -0.04:
                rets.append((ok / buy_px) * (1.0 - FEE) - 1.0); eds.append(dk); ehs.append(925); continue

        # Check intraday 10:30 VWAP on D4 if unsealed_mode uses it
        if unsealed_mode in ("d4_1030_vwap", "d4_1030_vwap_m1_d3xq", "d4_1030_vwap_m1_d4xq", "open_m3_plus_1030_vwap", "d4_1030_vwap_plus_1430"):
            exempt = False
            sr_d2 = float(r.d2_seal_amt_ratio) if pd.notna(r.d2_seal_amt_ratio) else np.nan
            if unsealed_mode == "d4_1030_vwap_m1_d3xq":
                if (int(r.xq_cnt_tot) < 4) and (np.isnan(sr_d2) or sr_d2 < 0.25):
                    exempt = True
            elif unsealed_mode == "d4_1030_vwap_m1_d4xq":
                xq_d4 = xq_d4_map.get((c6, bd), 99)
                if (xq_d4 < 4) and (np.isnan(sr_d2) or sr_d2 < 0.25):
                    exempt = True

            arr = b5m.get((c6, dk))
            if arr is not None and len(arr) >= 12:
                cum_v = cum_a = 0.0
                sealed_1030 = False
                sold_intraday = False
                n5 = len(arr)
                for bi in range(n5):
                    hh, bc, bv, ba = int(arr[bi, 0]), arr[bi, 4], arr[bi, 5], arr[bi, 6]
                    cum_v += bv; cum_a += ba
                    if hh == 1030:
                        vwap_1030 = cum_a / cum_v if cum_v > 0 else bc
                        if bc >= ztk - 0.01:
                            sealed_1030 = True
                        elif bc < vwap_1030 and (not exempt):
                            px = float(arr[bi + 1, 1]) if bi + 1 < n5 else float(bc)
                            ehh = int(arr[bi + 1, 0]) if bi + 1 < n5 else 1030
                            if px > dtk + 0.005:
                                rets.append((px / buy_px) * (1.0 - FEE) - 1.0); eds.append(dk); ehs.append(ehh)
                                sold_intraday = True
                            break
                    if unsealed_mode == "d4_1030_vwap_plus_1430" and sealed_1030 and hh >= 1430 and bc < ztk - 0.01 and bi + 1 < n5:
                        px = float(arr[bi + 1, 1])
                        if px > dtk + 0.005:
                            rets.append((px / buy_px) * (1.0 - FEE) - 1.0); eds.append(dk); ehs.append(int(arr[bi + 1, 0]))
                            sold_intraday = True
                        break
                if sold_intraday:
                    continue

        if iztk:
            rv, edv, ehv = run_zt_hold(k, 3)  # rebounds to ZT on D4 (streak=1 or 3rd/4th board equivalent)
            rets.append(rv); eds.append(edv); ehs.append(ehv)
        elif idtk:
            m = k + 1
            sold = False
            while m < len(all_dts):
                bm = plook.get((c6, all_dts[m]))
                if bm and not bm[10]:
                    rets.append((bm[0] / buy_px) * (1.0 - FEE) - 1.0); eds.append(all_dts[m]); ehs.append(925)
                    sold = True; break
                m += 1
            if not sold:
                rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
        else:
            rets.append((ck / buy_px) * (1.0 - FEE) - 1.0); eds.append(dk); ehs.append(1500)

    return rets, eds, ehs


def eval_windows(gated: pd.DataFrame, th: int, rcol: str, ecol: str, hcol: str) -> dict:
    sub_all = gated[gated["score_v2"] >= th].copy()
    sub_5y = sub_all[sub_all["buy_date"] >= u2.CANON_5Y_START].copy()
    led_5y = u2.sim_single_slot(sub_5y, "score_v2", rcol, ecol, hcol)
    led_full = u2.sim_single_slot(sub_all, "score_v2", rcol, ecol, hcol)

    res = {}
    for wn, sdt, edt, csip in WINDOWS:
        sa = sub_all[(sub_all["buy_date"] >= sdt) & (sub_all["buy_date"] <= edt)].copy()
        ws = (led_full if wn == "is_21_23_full" else led_5y)
        ws = ws[(ws["buy_date"] >= sdt) & (ws["buy_date"] <= edt)]

        if ws.empty:
            s_stats = {"n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0, "nav": 1.0, "ret_pct": 0.0, "mdd_pct": 0.0, "trim3_nav": 1.0, "trim5_nav": 1.0, "csi300_pct": csip, "excess_pp": round(-csip, 2)}
        else:
            rr = ws["net_ret"].to_numpy(dtype=float)
            w, ls = rr[rr > 0], rr[rr <= 0]
            nc = np.cumprod(1.0 + rr)
            pk = np.maximum.accumulate(np.insert(nc, 0, 1.0))[1:]
            sr = np.sort(rr)
            s_stats = {
                "n": int(len(rr)), "wr_pct": round(float((rr > 0).mean() * 100.0), 2),
                "plr": round(float(w.mean() / abs(ls.mean())) if (len(w) and len(ls) and ls.mean() < 0) else 99.0, 2),
                "mean_pct": round(float(rr.mean() * 100.0), 2),
                "nav": round(float(nc[-1]), 4), "ret_pct": round((float(nc[-1]) - 1.0) * 100.0, 2),
                "mdd_pct": round(float(np.max((pk - nc) / pk) * 100.0), 2),
                "trim3_nav": round(float(np.prod(1.0 + sr[:-3])) if len(rr) > 3 else 1.0, 4),
                "trim5_nav": round(float(np.prod(1.0 + sr[:-5])) if len(rr) > 5 else 1.0, 4),
                "csi300_pct": csip, "excess_pp": round((float(nc[-1]) - 1.0) * 100.0 - csip, 2),
            }

        if sa.empty:
            eq_stats = {"raw_n": 0, "days_n": 0, "wr_pct": 0.0, "plr": 0.0, "nav": 1.0, "ret_pct": 0.0, "mdd_pct": 0.0, "trim3_nav": 1.0, "trim5_nav": 1.0, "csi300_pct": csip, "excess_pp": round(-csip, 2)}
        else:
            dq = sa.groupby("buy_date")[rcol].mean().sort_index().to_numpy(dtype=float)
            dw, dls = dq[dq > 0], dq[dq <= 0]
            dnc = np.cumprod(1.0 + dq)
            dpk = np.maximum.accumulate(np.insert(dnc, 0, 1.0))[1:]
            dsr = np.sort(dq)
            eq_stats = {
                "raw_n": int(len(sa)), "days_n": int(len(dq)),
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
    raw_all, df_all, gated, asof = u2.build_pit_dataset("2026-11-16")
    gated["score_v2"] = 60.0 + u2.compute_v20_components(gated).sum(axis=1)
    da, b5m = u2.load_daily_and_5m("2026-11-16")

    all_dts = sorted(da["dt"].unique())
    dt_idx = {d: i for i, d in enumerate(all_dts)}
    plook = {
        (r.c6, r.dt): (
            float(r.open), float(r.high), float(r.low), float(r.close),
            float(r.pre_c) if pd.notna(r.pre_c) else float(r.close),
            float(r.zt_px) if pd.notna(r.zt_px) else 9999.0,
            float(r.dt_px) if pd.notna(r.dt_px) else 0.0,
            bool(r.is_zt), bool(r.is_dt_exact), bool(r.is_yizi), bool(r.is_yizi_dt),
        )
        for r in da[da["dt"] >= "2020-12-25"][
            ["c6", "dt", "open", "high", "low", "close", "pre_c", "zt_px", "dt_px", "is_zt", "is_dt_exact", "is_yizi", "is_yizi_dt"]
        ].itertuples(index=False)
    }

    code_hist, xq_d4_map, d3_sr_map = load_extra_pit_data(da, gated)

    # Check 5m coverage on holding days of std90 & strict96
    g5 = gated[(gated["buy_date"] >= u2.CANON_5Y_START) & (gated["score_v2"] >= 90)].copy()
    l_std = u2.sim_single_slot(g5, "score_v2", "ret_v2", "ed_v2", "eh_v2")
    l_str = u2.sim_single_slot(g5[g5["score_v2"] >= 96], "score_v2", "ret_v2", "ed_v2", "eh_v2")
    ref_std = pd.read_csv(f"{UPG_DIR}/ledger_upg_2to3_std.csv")
    ref_str = pd.read_csv(f"{UPG_DIR}/ledger_upg_2to3_strict.csv")
    assert len(l_std) == len(ref_std) == 94 and (l_std["net_ret"] - ref_std["net_ret"]).abs().max() < 1e-12
    assert len(l_str) == len(ref_str) == 35 and (l_str["net_ret"] - ref_str["net_ret"]).abs().max() < 1e-12

    # 5m coverage stats on D4 (pos+1) and all holding days
    def cov_5m_check(sub_led):
        d4_tot = d4_cov = hold_tot = hold_cov = 0
        for r in sub_led.itertuples(index=False):
            c6 = str(r.code).zfill(6)
            p_b = dt_idx.get(r.buy_date, -1)
            p_e = dt_idx.get(r.exit_date, -1)
            if p_b >= 0 and p_b + 1 < len(all_dts):
                d4_tot += 1
                d4_cov += int((c6, all_dts[p_b + 1]) in b5m)
            if p_b >= 0 and p_e > p_b:
                for k in range(p_b + 1, p_e + 1):
                    hold_tot += 1
                    hold_cov += int((c6, all_dts[k]) in b5m)
        return {
            "d4_5m_cov": f"{d4_cov}/{d4_tot}", "d4_5m_cov_pct": round(d4_cov / max(1, d4_tot) * 100.0, 2),
            "hold_days_5m_cov": f"{hold_cov}/{hold_tot}", "hold_days_5m_cov_pct": round(hold_cov / max(1, hold_tot) * 100.0, 2),
        }

    cov_info = {"std90_94trades": cov_5m_check(l_std), "strict96_35trades": cov_5m_check(l_str)}
    print("5m Coverage 2to3:", cov_info)

    # Verify sim_2to3_variant baseline matches exact upgrade_2to3_pit.py
    rb, edb, ehb = sim_2to3_variant(gated, all_dts, dt_idx, plook, b5m, code_hist, xq_d4_map, d3_sr_map)
    assert np.max(np.abs(np.array(rb) - gated["ret_v2"].to_numpy())) < 1e-12, "Baseline sim diff!"

    experiments = [
        ("baseline_v20", "baseline", dict(unsealed_mode="eod1500", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True, dev_disc=None)),
        # 2a Unsealed D3 variants
        ("2a_v1_open_lt_05_cut", "2a_unsealed", dict(unsealed_mode="v1_cut_weak_open_lt_05", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True)),
        ("2a_d4_open_lt_m2", "2a_unsealed", dict(unsealed_mode="open_lt_m2", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True)),
        ("2a_d4_open_lt_m3", "2a_unsealed", dict(unsealed_mode="open_lt_m3", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True)),
        ("2a_d4_open_lt_m4", "2a_unsealed", dict(unsealed_mode="open_lt_m4", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True)),
        ("2a_d4_1030_vwap", "2a_unsealed", dict(unsealed_mode="d4_1030_vwap", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True)),
        ("2a_d4_1030_vwap_m1_d3xq", "2a_unsealed", dict(unsealed_mode="d4_1030_vwap_m1_d3xq", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True)),
        ("2a_d4_1030_vwap_m1_d4xq", "2a_unsealed", dict(unsealed_mode="d4_1030_vwap_m1_d4xq", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True)),
        ("2a_d4_open_m3_plus_1030_vwap", "2a_unsealed", dict(unsealed_mode="open_m3_plus_1030_vwap", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True)),
        ("2a_d4_1030_vwap_plus_1430", "2a_unsealed", dict(unsealed_mode="d4_1030_vwap_plus_1430", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True)),
        # 2b Sealed 3b relay variants
        ("2b_v19_1030_1430_ho92_noimm", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="v19_1030_1430", d4_high_open_thr=0.092, use_yang_imm=False)),
        ("2b_v19_1030_1430_ho92_imm", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="v19_1030_1430", d4_high_open_thr=0.092, use_yang_imm=True)),
        ("2b_v19_1030_1430_ho92_m1d4", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="v19_1030_1430", d4_high_open_thr=0.092, use_yang_imm=True, use_m1_d4_exempt=True)),
        ("2b_v19_1030_1430_noho_noimm", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="v19_1030_1430", d4_high_open_thr=None, use_yang_imm=False)),
        ("2b_v19_1030_1430_noho_imm", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="v19_1030_1430", d4_high_open_thr=None, use_yang_imm=True)),
        ("2b_pm1345_noho92", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="pm1345", d4_high_open_thr=None, use_yang_imm=True)),
        ("2b_pm1345_no_imm", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=False)),
        ("2b_pm1345_dev93_4b", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True, dev_disc=0.07, dev_min_board=4)),
        ("2b_pm1345_dev96_4b", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True, dev_disc=0.04, dev_min_board=4)),
        ("2b_pm1345_dev98_4b", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True, dev_disc=0.02, dev_min_board=4)),
        ("2b_pm1345_dev93_5b", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True, dev_disc=0.07, dev_min_board=5)),
        ("2b_pm1345_dev96_5b", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True, dev_disc=0.04, dev_min_board=5)),
        ("2b_pm1345_dev98_5b", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True, dev_disc=0.02, dev_min_board=5)),
        ("2b_v19_imm_dev93_4b", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="v19_1030_1430", d4_high_open_thr=0.092, use_yang_imm=True, dev_disc=0.07, dev_min_board=4)),
        ("2b_v19_imm_dev96_5b", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="v19_1030_1430", d4_high_open_thr=0.092, use_yang_imm=True, dev_disc=0.04, dev_min_board=5)),
        ("2b_combo_1030vwap_v19_imm", "2b_combo", dict(unsealed_mode="d4_1030_vwap", relay_mode="v19_1030_1430", d4_high_open_thr=0.092, use_yang_imm=True)),
        ("2b_combo_1030vwap_pm1345_dev96_5b", "2b_combo", dict(unsealed_mode="d4_1030_vwap", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=True, dev_disc=0.04, dev_min_board=5)),
    ]

    results = []
    for name, grp, kw in experiments:
        rv, edv, ehv = sim_2to3_variant(gated, all_dts, dt_idx, plook, b5m, code_hist, xq_d4_map, d3_sr_map, **kw)
        gated["r_tmp"] = rv; gated["ed_tmp"] = edv; gated["eh_tmp"] = ehv
        m_std = eval_windows(gated, 90, "r_tmp", "ed_tmp", "eh_tmp")
        m_str = eval_windows(gated, 96, "r_tmp", "ed_tmp", "eh_tmp")
        results.append({"name": name, "group": grp, "params": kw, "std90": m_std, "strict96": m_str})

    out = {"coverage_5m": cov_info, "baseline_repro_verified": True, "experiments": results}
    with open(f"{OUT_DIR}/task2_2to3_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE Task 2 in {time.time()-t0:.1f}s] Summary std90 (94b) & strict96 (35b):")
    for e in results:
        s90 = e["std90"]
        s96 = e["strict96"]
        f5, is_, oo, y26 = s90["full_5y"]["single_slot"], s90["is_21_23_full"]["single_slot"], s90["oos_24_26"]["single_slot"], s90["y2026_1y"]["single_slot"]
        eq5 = s90["full_5y"]["daily_eq"]
        f5_s = s96["full_5y"]["single_slot"]
        print(f"  {e['name']:32s} | std90: 5Y={f5['nav']:6.2f}x(WR={f5['wr_pct']:4.1f}%,MDD={f5['mdd_pct']:4.1f}%,T3={f5['trim3_nav']:5.2f}x) IS={is_['nav']:5.2f}x OOS={oo['nav']:5.2f}x 26={y26['nav']:4.2f}x EQ={eq5['nav']:6.2f}x | S96: 5Y={f5_s['nav']:5.2f}x(IS={s96['is_21_23_full']['single_slot']['nav']:4.2f},OOS={s96['oos_24_26']['single_slot']['nav']:4.2f})")


if __name__ == "__main__":
    main()
