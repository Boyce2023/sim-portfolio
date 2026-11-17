#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""逐项硬核回测检验 astock 提出的 9 项建议在三进四真实 5 分钟引擎上的胜率、赔率、净值与回撤效应"""
import os, sys, glob, json, re, pickle, numpy as np, pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path: sys.path.insert(0, CUR_DIR)
ROOT = "/Users/huaichuaibeimeng/claude-projects"

from core_3to4_5m_engine import FEE_RATE, BARS_5M_PATH, MATRIX_DIR, sim_buy_5m, evaluate_5m_d15
from bt_3to4_scorecard_verify import build_scores

# 1. 加载三进四 111列全量表 + 5m K线 + 指数缓存
df = pd.read_parquet(f"{CUR_DIR}/data_5y/cand_3to4_enriched54.parquet")
with open(f"{MATRIX_DIR}/code_bars_5y.pkl", "rb") as f:
    code_bars = pickle.load(f)["code_bars"]
df_5m = pd.read_parquet(BARS_5M_PATH)
df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
bars_5m_map = {(c6, dt_s): g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float) for (c6, dt_s), g in df_5m.groupby(["c6", "date"], sort=False)}

with open(f"{MATRIX_DIR}/../index_klines_5y_cache.json", "r") as f:
    idx_k = json.load(f)
SH_MAP, SZ_MAP, CSI_MAP = idx_k["sh000002"], idx_k["sz399107"], idx_k["sh000300"]
dts_s = sorted(CSI_MAP.keys()); d_pos = {d: i for i, d in enumerate(dts_s)}
df["csi_1d_prev"] = [(CSI_MAP[r.sig_date] / CSI_MAP[dts_s[d_pos[r.sig_date]-1]] - 1.0) if r.sig_date in d_pos and d_pos[r.sig_date] >= 1 else 0.0 for r in df.itertuples(index=False)]
df["prio_3to4"] = df["open_pct"] * 1000.0 + df["lock_top10"] * 0.5 + df["csrc_zt_cnt"] * 2.0
skel, sc_v31, _ = build_scores(df)

def get_double_dev_px(cb, cp, imap, disc=0.07):
    cd = cb["dts"][cp]; ir = imap.get(cd)
    if not ir: return 99999.0
    bp = 99999.0
    for k in range(1, min(11, cp + 1)):
        p = cp - k; bi = imap.get(cb["dts"][p]); bc = cb["close"][p]
        if bi and bc > 0: bp = min(bp, bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0)))
    for k in range(1, min(31, cp + 1)):
        p = cp - k; bi = imap.get(cb["dts"][p]); bc = cb["close"][p]
        if bi and bc > 0: bp = min(bp, bc * (1.0 + (2.0 - disc) + (ir / bi - 1.0)))
    return bp

# 可配置买卖与持仓模拟器 (逐项对照 Item 1, 2, 3)
def sim_pool_custom(use_dev93=False, d4_mode="reb2", hold_mode="pm1345", use_yang_imm=False):
    out = [None] * len(df)
    for idx, r in enumerate(df.itertuples(index=False)):
        if not bool(r.is_10cm_non_st) or bool(r.prev_is_yizi) or (not bool(r.buyable_open)): continue
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        cb = code_bars.get(c6)
        if cb is None: continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or pos >= len(cb["dts"]) - 1: continue
        bpx, bhh = sim_buy_5m(c6, bd, cb, pos, bars_5m_map, "touch65_1130")
        if bpx is None: continue
        imap = SH_MAP if c6.startswith("60") else SZ_MAP
        n = len(cb["dts"])

        def run_zt_hold(start_p):
            k = start_p + 1
            imm_used = False
            while k < n:
                if bool(cb["is_yizi_dt"][k]): k += 1; continue
                ok, pck, clk, ztk = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k]), float(cb["zt_px"][k])
                dtk = round(pck * 0.90, 2)
                if k > start_p + 1 and bool(cb["is_yizi_dt"][k - 1]):
                    return cb["dts"][k], ok, float(cb["adjf"][k]), k - pos, 925
                arr = bars_5m_map.get((c6, cb["dts"][k]))
                # Item 1: 双异动 93% 预埋限价止盈单
                if use_dev93:
                    pl = get_double_dev_px(cb, k, imap, 0.07)
                    if ok >= pl: return cb["dts"][k], ok, float(cb["adjf"][k]), k - pos, 925
                    if arr is not None:
                        for row in arr:
                            if row[2] >= pl and row[2] > dtk + 0.005:
                                return cb["dts"][k], float(max(row[1], pl)), float(cb["adjf"][k]), k - pos, int(row[0])
                # Item 3a: 持仓盘中规则 (pm1345 vs v17_1030_1430)
                if hold_mode == "pm1345" and arr is not None and len(arr) > 0:
                    peak = ok
                    for row in arr:
                        hh, bo, bh, bl, bc = int(row[0]), row[1], row[2], row[3], row[4]
                        if bh <= dtk + 0.005: continue
                        if hh >= 1345 and peak >= pck * 1.085 and bl <= pck * 1.050 and bc < ztk - 0.01:
                            return cb["dts"][k], float(min(bo, pck * 1.050)), float(cb["adjf"][k]), k - pos, hh
                        if bh > peak: peak = bh
                elif hold_mode == "v17_1030" and arr is not None and len(arr) >= 4:
                    cv, ca, locked1030 = 0.0, 0.0, False
                    for i in range(len(arr) - 1):
                        hh, bo, bh, bl, bc, bv, ba = int(arr[i,0]), arr[i,1], arr[i,2], arr[i,3], arr[i,4], arr[i,5], arr[i,6]
                        cv += bv; ca += ba; vwap = (ca / cv) if cv > 0 else bc
                        if hh == 1030:
                            if bc >= ztk - 0.01: locked1030 = True
                            elif bc < vwap:
                                nxo = arr[i+1, 1]
                                if nxo > dtk + 0.005: return cb["dts"][k], float(nxo), float(cb["adjf"][k]), k - pos, int(arr[i+1,0])
                        if locked1030 and hh >= 1430 and bc < ztk - 0.01:
                            nxo = arr[i+1, 1]
                            if nxo > dtk + 0.005: return cb["dts"][k], float(nxo), float(cb["adjf"][k]), k - pos, int(arr[i+1,0])
                if bool(cb["is_zt"][k]): k += 1; continue
                # Item 3b: 首次断板真阳免死一次
                if use_yang_imm and (not imm_used) and (clk > ok) and (clk >= pck):
                    imm_used = True; k += 1; continue
                return cb["dts"][k], clk, float(cb["adjf"][k]), max(1, k - pos), 1500
            k = n - 1
            return cb["dts"][k], float(cb["close"][k]), float(cb["adjf"][k]), max(1, k - pos), 1500

        if not bool(cb["is_zt"][pos]):
            k = pos + 1
            while k < n and bool(cb["is_yizi_dt"][k]): k += 1
            k = min(k, n - 1)
            o4, c4, p4 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])
            o5, p5, c5 = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
            dt5 = round(p5 * 0.90, 2)
            if k > pos + 1:
                ex_dt, spx, adjs, hb, shh = cb["dts"][k], o5, float(cb["adjf"][k]), k - pos, 925
            elif d4_mode == "reb2":
                arr = bars_5m_map.get((c6, cb["dts"][k]))
                spx, shh = (o5, 925) if o5 >= p5 * 1.02 else (c5, 1500)
                if o5 < p5 * 1.02 and arr is not None:
                    for row in arr:
                        if row[2] > dt5 + 0.005 and row[2] >= p5 * 1.02:
                            spx, shh = float(max(row[1], p5 * 1.02)), int(row[0]); break
                ex_dt, adjs, hb = cb["dts"][k], float(cb["adjf"][k]), max(1, k - pos)
            elif d4_mode == "cut_weak":
                # Item 2: D4未封板 -> 收绿(c4<o4 或 c4<p4) 或 D5高开<0.5% 则 D5 09:25竞价立斩；收真阳且D5高开>=0.5%留仓博反包(涨停转锁仓)
                d4_strong = (c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005)
                if not d4_strong:
                    ex_dt, spx, adjs, hb, shh = cb["dts"][k], o5, float(cb["adjf"][k]), max(1, k - pos), 925
                elif bool(cb["is_zt"][k]):
                    ex_dt, spx, adjs, hb, shh = run_zt_hold(k)
                else:
                    ex_dt, spx, adjs, hb, shh = cb["dts"][k], c5, float(cb["adjf"][k]), max(1, k - pos), 1500
            elif d4_mode == "pure_open":
                ex_dt, spx, adjs, hb, shh = cb["dts"][k], o5, float(cb["adjf"][k]), max(1, k - pos), 925
        else:
            ex_dt, spx, adjs, hb, shh = run_zt_hold(pos)

        nr = (spx * adjs) / (bpx * float(cb["adjf"][pos])) * (1.0 - FEE_RATE) - 1.0
        out[idx] = {"code": c6, "name": r.name, "buy_date": bd, "buy_price": bpx, "buy_hhmm": bhh, "exit_date": ex_dt, "exit_price": spx, "exit_hhmm": shh, "hold_bars": hb, "net_ret": nr, "priority_score": float(r.prio_3to4)}
    return out

def eval_pool(label, msk, pool, sc_arr, use_skip_cb=False):
    recs = []
    for i in np.where(np.asarray(msk, dtype=bool))[0]:
        if pool[i] is not None:
            d = dict(pool[i])
            d["priority_score"] = float(sc_arr[i]) * 10.0 + float(df["prio_3to4"].iloc[i]) * 0.1
            recs.append(d)
    tdf = pd.DataFrame(recs)
    if tdf.empty:
        print(f"{label:38s} | 0 trades"); return
    if use_skip_cb:
        srt = tdf.sort_values(["buy_date", "buy_hhmm", "priority_score"], ascending=[True, True, False])
        taken, fd, fh, cl, sk = [], "", 0, 0, False
        for r in srt.itertuples(index=False):
            bd, bh = r.buy_date, int(r.buy_hhmm)
            if not ((fd == "") or (bd > fd) or (bd == fd and bh > fh)): continue
            fd, fh = r.exit_date, int(r.exit_hhmm)
            if sk:
                sk, cl = False, 0
                continue
            taken.append(r._asdict())
            if r.net_ret < -0.02:
                cl += 1
                if cl >= 2: sk = True
            elif r.net_ret > 0:
                cl = 0
        tdf = pd.DataFrame(taken)
    ev = evaluate_5m_d15(tdf)
    s5, r3 = ev["full_5y"], ev["recent_3y"]
    print(f"{label:38s} | 5Y:{s5['single_n']:3d}b WR={s5['wr']:4.1f}% PO={s5['payoff']:4.2f} NAV={s5['single_nav']:6.2f}x MDD={s5['single_mdd_pct']:4.1f}% Eq={s5['eq_nav']:5.2f}x | 24-26:{r3['single_n']:2d}b WR={r3['wr']:4.1f}% PO={r3['payoff']:4.2f} NAV={r3['single_nav']:5.2f}x MDD={r3['single_mdd_pct']:4.1f}%")

print("=== [Part I] 买卖与持仓引擎 4 项逐一与组合回测 (对比 V3.1 78分 / 90分 / 98分) ===")
p_base = sim_pool_custom(False, "reb2", "pm1345", False)
p_dev93 = sim_pool_custom(True, "reb2", "pm1345", False)
p_cutw = sim_pool_custom(False, "cut_weak", "pm1345", False)
p_open5 = sim_pool_custom(False, "pure_open", "pm1345", False)
p_v17h = sim_pool_custom(False, "reb2", "v17_1030", False)
p_yimm = sim_pool_custom(False, "reb2", "pm1345", True)
p_comb = sim_pool_custom(True, "cut_weak", "pm1345", True)
p_comb_v17 = sim_pool_custom(True, "cut_weak", "v17_1030", True)

for th in [78, 90, 98]:
    print(f"\n--- 门槛 >= {th} 分 ---")
    m = sc_v31 >= th
    eval_pool(f"0.现版基准(reb2+pm1345)", m, p_base, sc_v31)
    eval_pool(f"1.+双异动93%限价止盈", m, p_dev93, sc_v31)
    eval_pool(f"2.+D4未封弱斩强留博反包(cut_weak)", m, p_cutw, sc_v31)
    eval_pool(f"2b.+D4未封次日无脑09:25竞价走", m, p_open5, sc_v31)
    eval_pool(f"3a.+持仓改10:30均线+14:30炸板抢跑", m, p_v17h, sc_v31)
    eval_pool(f"3b.+首次断板真阳免死一次", m, p_yimm, sc_v31)
    eval_pool(f"4.+连亏2笔超2%强制空仓歇1笔", m, p_base, sc_v31, True)
    eval_pool(f"★组合(双异动93+弱斩强留+真阳免死)", m, p_comb, sc_v31, False)
    eval_pool(f"★组合+连亏2笔歇1笔(CB)", m, p_comb, sc_v31, True)
    eval_pool(f"★组合(双异动93+弱斩强留+10:30+免死+CB)", m, p_comb_v17, sc_v31, True)

# === [Part II] 传感器 + 同批排位 + 三大未接因子库 (Items 5, 6, 7, 8, 9) 在三进四上的真实边际检验 ===
print("\n=== [Part II] 传感器与三大本地因子库在三进四上的真实胜率与收益差检验 ===")
df["base_ret"] = [p["net_ret"] if p is not None else np.nan for p in p_base]
df["comb_ret"] = [p["net_ret"] if p is not None else np.nan for p in p_comb]

# Item 5: 严格因果 t-1 滚动 10日/20日 三进四真实封板率 (仅用 buy_date < 当前 buy_date 的自然三板样本!)
clean_34 = df[df["is_10cm_non_st"] & (~df["prev_is_yizi"]) & df["buyable_open"]].copy()
day_zt = clean_34.groupby("buy_date")["is_zt_today"].agg(["count", "sum"]).sort_index()
day_zt["r10"] = day_zt["sum"].shift(1).rolling(10, min_periods=3).sum() / day_zt["count"].shift(1).rolling(10, min_periods=3).sum()
day_zt["r20"] = day_zt["sum"].shift(1).rolling(20, min_periods=5).sum() / day_zt["count"].shift(1).rolling(20, min_periods=5).sum()
df["r10_34_zt"] = df["buy_date"].map(day_zt["r10"]).fillna(0.35)
df["r20_34_zt"] = df["buy_date"].map(day_zt["r20"]).fillna(0.35)

# Item 7: 过去1年内是否走出过5连板以上老妖记忆 + 开盘啦老熟票新老题材
mem_1y_5b = []
for r in df.itertuples(index=False):
    cb = code_bars.get(str(r.code).zfill(6))
    p = cb["date_to_pos"].get(str(r.sig_date), -1) if cb else -1
    has5 = False
    if cb and p > 10:
        zts = cb["is_zt"][max(0, p-250):p-3]
        run = 0
        for z in zts:
            run = (run + 1) if z else 0
            if run >= 5: has5 = True; break
    mem_1y_5b.append(has5)
df["mem_1y_5b"] = mem_1y_5b

# KPL plates 老票老题材 vs 老票蹭陌生新概念
kpl_files = glob.glob(f"{ROOT}/sim-portfolio/**/kpl_plates_2018_2026_merged.jsonl", recursive=True)
old_old, old_new = [False]*len(df), [False]*len(df)
if kpl_files:
    from collections import defaultdict
    hist_pl = defaultdict(list)
    with open(kpl_files[0], "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            o = json.loads(line)
            c6 = str(o.get("code", o.get("c6", "")))[:6]
            dt = str(o.get("date", o.get("trade_date", "")))[:10]
            pl = str(o.get("plate", o.get("theme", "")))
            if c6 and dt and pl and pl != "其他": hist_pl[c6].append((dt, pl))
    for k in hist_pl: hist_pl[k].sort()
    for i, r in enumerate(df.itertuples(index=False)):
        c6, sd, cur_p = str(r.code).zfill(6), str(r.sig_date), str(r.plate)
        arr_p = [p for d, p in hist_pl.get(c6, []) if d < sd and (pd.Timestamp(sd) - pd.Timestamp(d)).days <= 365 and (pd.Timestamp(sd) - pd.Timestamp(d)).days >= 5]
        if len(arr_p) >= 2 and cur_p and cur_p != "其他":
            if cur_p in arr_p: old_old[i] = True
            else: old_new[i] = True
df["kpl_old_old"] = old_old; df["kpl_old_new"] = old_new

# Item 8: 龙虎榜卖出表 + 顶级格局游资锁仓 vs 一日游砸盘席位 + 拉萨买额占比>=20%
TOP_YZ = re.compile(r"(?:金田路|六一中路|呼家楼|桑田路|小鳄鱼|方新侠|章盟主|陈小群|大连黄河路|江苏路|溧阳路|西安太华路|中山东路)")
SURF_YZ = re.compile(r"(?:上塘路|财通.*杭州上塘|国盛.*宁波桑田|东方财富.*昌都|佛山|绿景路|苏南|消闲派|国泰君安.*宜昌|开源.*西安西大街)")
lb_path = f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet"
ls_files = glob.glob(f"{ROOT}/sim-portfolio/**/lhb_sell.parquet", recursive=True)
top_lock, surf_buy = [False]*len(df), [False]*len(df)
if os.path.exists(lb_path) and ls_files:
    lb = pd.read_parquet(lb_path, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"])
    ls = pd.read_parquet(ls_files[0], columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "SELL"])
    lb["dt"], lb["c6"] = lb["TRADE_DATE"].astype(str).str[:10], lb["SECURITY_CODE"].astype(str).str[:6]
    ls["dt"], ls["c6"] = ls["TRADE_DATE"].astype(str).str[:10], ls["SECURITY_CODE"].astype(str).str[:6]
    b_seats = lb[lb["dt"]>="2021-12-01"].groupby(["dt","c6"])["OPERATEDEPT_NAME"].apply(lambda s: set(s.dropna().astype(str))).to_dict()
    s_seats = ls[ls["dt"]>="2021-12-01"].groupby(["dt","c6"])["OPERATEDEPT_NAME"].apply(lambda s: set(s.dropna().astype(str))).to_dict()
    for i, r in enumerate(df.itertuples(index=False)):
        c6, sd = str(r.code).zfill(6), str(r.sig_date)
        bs = b_seats.get((sd, c6), set()); ss = s_seats.get((sd, c6), set())
        tops = [x for x in bs if TOP_YZ.search(x)]
        if tops and not any(x in ss for x in tops): top_lock[i] = True
        if any(SURF_YZ.search(x) for x in bs): surf_buy[i] = True
df["top_yz_lock"] = top_lock; df["surf_yz_buy"] = surf_buy

# 在硬骨架触发池 (skel & base_ret.notna()) 上双期检验 Items 5~9
sub = df[skel & df["comb_ret"].notna()].copy()
sub_r = sub[sub["buy_date"] >= "2024-01-01"]
def chk(nm, m_all, m_rec):
    a1, a0 = sub.loc[m_all, "comb_ret"], sub.loc[~m_all, "comb_ret"]
    r1, r0 = sub_r.loc[m_rec, "comb_ret"], sub_r.loc[~m_rec, "comb_ret"]
    if len(a1) == 0 or len(r1) == 0:
        print(f"  {nm:36s} | N_5y={len(a1)} N_rec={len(r1)}"); return
    print(f"  {nm:36s} | 5Y(n={len(a1):3d}): WR={((a1>0).mean()*100):4.1f}%(Δ{((a1>0).mean()-(a0>0).mean())*100:+5.1f}%) Mean={a1.mean()*100:+5.2f}%(Δ{(a1.mean()-a0.mean())*100:+5.2f}%) || 24-26(n={len(r1):3d}): WR={((r1>0).mean()*100):4.1f}%(Δ{((r1>0).mean()-(r0>0).mean())*100:+5.1f}%) Mean={r1.mean()*100:+5.2f}%(Δ{(r1.mean()-r0.mean())*100:+5.2f}%)")

for nm, fn in [
    ("5a.近10日三进四封板率>=35%", lambda x: x["r10_34_zt"] >= 0.35),
    ("5b.近10日三进四封板率<20%(接力冰点)", lambda x: x["r10_34_zt"] < 0.20),
    ("5c.近20日三进四封板率<25%", lambda x: x["r20_34_zt"] < 0.25),
    ("6a.仅做同日三板竞价第一名(强排他)", lambda x: x["is_top1_3b_open"].astype(bool)),
    ("6b.八年题材热度p_elo>=115", lambda x: x["p_elo"] >= 115.0),
    ("6c.断层主线日买第3+冷门题材(篡位)", lambda x: x["is_dominant_day"] & (x["rk_theme"] >= 3)),
    ("7a.近1年曾走出5连板+老妖记忆", lambda x: x["mem_1y_5b"]),
    ("7b.开盘啦老熟票炒纯正老题材", lambda x: x["kpl_old_old"]),
    ("7c.开盘啦老熟票蹭陌生新概念", lambda x: x["kpl_old_new"]),
    ("8a.拉萨买额占比>=20%", lambda x: x["lhb_lh_share"] >= 0.20),
    ("8b.顶级格局游资三板买入且未卖出", lambda x: x["top_yz_lock"]),
    ("8c.上塘路/佛山/消闲派一日游买入", lambda x: x["surf_yz_buy"]),
    ("9a.三板09:35前秒封", lambda x: x["first_seal_time"].fillna("99:99") <= "09:35:00"),
    ("9b.三板10:30前开板硬换手回封", lambda x: x["is_hard_open_1030"].astype(bool)),
    ("9c.尾盘14:00后偷袭烂封板", lambda x: x["first_seal_time"].fillna("00:00") >= "14:00:00"),
    ("9d.硬催化公告或并购重组", lambda x: x["notice_hard"].astype(bool) | x["notice_ma"].astype(bool)),
    ("9e.传统外行硬蹭科技名字(is_pure_outsider)", lambda x: x["is_pure_outsider"].astype(bool)),
    ("9f.国企改革并购事件大筐(is_event_basket)", lambda x: x["is_event_basket"].astype(bool)),
]:
    chk(nm, fn(sub), fn(sub_r))
