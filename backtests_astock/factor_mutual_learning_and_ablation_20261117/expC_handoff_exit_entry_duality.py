#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
expC_handoff_exit_entry_duality.py
全量实证检验：
1. Day 3 (一进二卖 <-> 二进三买, N=7738) 与 Day 4 (二进三卖 <-> 三进四买, N=1259/2161) 的「前手卖点正向指标 == 后手买点反向指标」对偶律；
2. 双向买卖点互锁改造回测（IS 2021-2023 -> OOS 2024-2026）：
   - 改造1（二进三封三板后 Day 4 卖点学三进四拒接盘条件）：当三进四在 Day 4 明确不接盘（Day4开盘<+3%弱开，或 score_v34<80/85 且未封板）时，二进三在 Day 4 09:25 早盘顺势卖出 vs 原版死扛至午后/收盘；
   - 改造2（三进四 Day 4 买点学二进三/一进二卖出信号）：当 Day 4 盘中触发前手卖出信号（10:00后才滞后点火 / 早盘水下深砸 / 前手雪球>=4帖出逃）时三进四拒接盘；
   - 改造3（二进三 Day 3 买点学一进二 Day 3 必卖信号）：在 Day 3 剔除一进二必卖高危信号（同题材队友竞价核按钮<-1.5% / 深绿核按钮<-4%等）。
"""
import json
import pickle
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/huaichuaibeimeng/claude-projects")
SIM = ROOT / "sim-portfolio"
OUT_DIR = SIM / "backtests_astock/factor_mutual_learning_and_ablation_20261117"
FEE = 0.002
sys.path.insert(0, str(SIM / "backtests_astock2"))
from core_3to4_5m_engine import _sim_single_slot_chrono

c23 = pd.read_parquet(SIM / "backtests_astock/clean_2to3_v10_20261117/data_pit/clean_2to3_5y.parquet")
fa = pd.read_parquet(SIM / "backtests_astock/clean_2to3_v10_20261117/data_pit/factors_a.parquet")
fb = pd.read_parquet(SIM / "backtests_astock/clean_2to3_v10_20261117/data_pit/factors_b.parquet")
fc = pd.read_parquet(SIM / "backtests_astock/clean_2to3_v10_20261117/data_pit/factors_c.parquet")
c_23_raw90 = pd.read_csv(SIM / "backtests_astock/clean_2to3_v10_20261117/candidates_2to3_v10_all_raw90.csv")
l_23 = pd.read_csv(SIM / "backtests_astock/clean_2to3_v10_20261117/ledger_base_2to3_v10_std90.csv")

with open(SIM / "backtests_astock/special_26q4/3to4_26q4/cache_d_and_p.pkl", "rb") as f:
    pkg_34 = pickle.load(f)
d34 = pkg_34["df"].copy()
p34 = pkg_34["p_v32"]
sc34 = np.asarray(pkg_34["sc_v34"], dtype=float)
d34["sc_v34"] = sc34
d34["c6"] = d34["code"].astype(int).astype(str).str.zfill(6)
d34["p_trig"] = [p is not None for p in p34]
d34["p_ret"] = [float(p["net_ret"]) if p is not None else np.nan for p in p34]
d34["p_bhh"] = [int(p["buy_hhmm"]) if p is not None else -1 for p in p34]
d34["p_edate"] = [str(p["exit_date"]) if p is not None else "" for p in p34]

# 三行硬校验
assert c23["open_pct"].abs().median() < 0.20, "unit check c23"
assert len(d34) == len(p34) and len(c23) > 10000, "shape check"
assert c23["buy_date"].max() >= "2026-11-01", "date anchor check"

# --- 1. NODE 1 DUALITY (Day 3: 1进2卖 vs 2进3买) ---
m23 = c23.merge(fa[["code", "buy_date", "b01_hhi_low_q25", "b10_top1_share_ge30", "a22_elo_ice_lt95"]], on=["code", "buy_date"], how="left")
m23 = m23.merge(fb[["code", "buy_date", "xq_cnt_tot", "ir_cnt_20d"]], on=["code", "buy_date"], how="left")
m23 = m23.merge(fc[["code", "buy_date", "d2_seal_amt_ratio", "d2_low_pct", "lock_top10", "d2_real_turn", "peers_open_avg_2b"]], on=["code", "buy_date"], how="left")
m23["c6"] = m23["code"].astype(int).astype(str).str.zfill(6)

u23 = m23[(m23["buy_date"] >= "2021-11-15") & (~m23["prev_is_yizi"]) & (m23["buyable_open"])].copy()
u23["is_oos"] = u23["buy_date"] >= "2024-01-01"
u23["hold_val"] = (1.0 + u23["open_pct"]) * (1.0 + u23["ret_opn_cc"]) / (1.0 - FEE)
u23["sell0925_val"] = 1.0 + u23["open_pct"]
u23["delta_1to2_sell_pct"] = (u23["sell0925_val"] / u23["hold_val"] - 1.0) * 100.0
u23["relay_2to3_buy_pct"] = u23["ret_opn_cc"] * 100.0

print("=== 1. NODE 1 DUALITY (Day 3 二板交接棒: 1进2立卖超额 vs 2进3买入净收益, N=%d) ===" % len(u23))
node1_rows = []
for name, mask in [
    ("D3高开 +2.5%~+9.2% (1进2冲高兑现区)", (u23["open_pct"] > 0.025) & (u23["open_pct"] <= 0.092)),
    ("雪球盘前热帖 >=4帖 (散户吹票)", u23["xq_cnt_tot"].fillna(0) >= 4),
    ("D2缩量死锁 (封成比>=25%)", u23["d2_seal_amt_ratio"].fillna(0) >= 0.25),
    ("主概念涨停 >=15家 (前排吸血)", u23["plate_sz"] >= 15),
    ("近20日机构调研 (机构逢高兑现)", u23["ir_cnt_20d"].fillna(0) >= 1),
    ("昨全场涨停 >=95家 (高潮次日)", u23["mkt_zt_prev"] >= 95),
    ("同题材队友竞价 <-1.5% (核按钮拖累)", u23["peers_open_avg_2b"].fillna(0) < -0.015),
    ("D3深水核按钮 <-4.5%", u23["open_pct"] < -0.045),
    ("[反向对偶:2进3高分接力区] 暗牌弱封低开", (u23["open_pct"].between(-0.065, 0.025)) & (u23["xq_cnt_tot"].fillna(0) == 0) & (u23["d2_seal_amt_ratio"].fillna(0.1) < 0.05) & (u23["lock_top10"].fillna(0) >= 50)),
]:
    si, so, sa = u23[mask & (~u23["is_oos"])], u23[mask & u23["is_oos"]], u23[mask]
    r = {
        "factor": name, "n": int(len(sa)),
        "sell_is": round(float(si["delta_1to2_sell_pct"].mean()), 2),
        "sell_oos": round(float(so["delta_1to2_sell_pct"].mean()), 2),
        "buy_is": round(float(si["relay_2to3_buy_pct"].mean()), 2),
        "buy_oos": round(float(so["relay_2to3_buy_pct"].mean()), 2),
        "buy_wr": round(float((sa["relay_2to3_buy_pct"] > 0).mean() * 100), 1),
    }
    node1_rows.append(r)
    print(f"  {name:38s} | n={r['n']:4d} | 1进2早卖超额(IS/OOS):{r['sell_is']:+6.2f}%/{r['sell_oos']:+6.2f}% | 2进3买入收益(IS/OOS):{r['buy_is']:+6.2f}%/{r['buy_oos']:+6.2f}% WR={r['buy_wr']}%")

# --- 2. NODE 2 DUALITY (Day 4: 2进3卖 vs 3进4买) ---
# Join sealed_3b rows from u23 with d34 (sig_date of d34 == buy_date of u23, i.e. Day 3!)
d34_sub = d34[(d34["buy_date"] >= "2021-11-15") & (~d34["prev_is_yizi"]) & (d34["buyable_open"])].copy()
d34_sub["is_oos"] = d34_sub["buy_date"] >= "2024-01-01"
# Link u23 sealed_3b to get exact 2to3 hold return from D3 close to exit vs selling at D4 09:25 open!
# If 2to3 sealed 3b on D3 (D3 close = prev_close*(1+close_pct) = D3 ZT), holding to cc exit gives ret_opn_cc from D3 open:
# Value at cc exit relative to D3 close = (1 + u23.open_pct) * (1 + u23.ret_opn_cc) / ((1 + u23.close_pct) * (1 - FEE))
u23_s3 = u23[u23["sealed_3b"]].copy()
u23_s3["val_hold_rel_d3c"] = (1.0 + u23_s3["open_pct"]) * (1.0 + u23_s3["ret_opn_cc"]) / ((1.0 + u23_s3["close_pct"]) * (1.0 - FEE))
j34 = d34_sub.merge(
    u23_s3[["c6", "buy_date", "val_hold_rel_d3c", "xq_cnt_tot"]].rename(columns={"buy_date": "sig_date"}),
    on=["c6", "sig_date"], how="inner"
)
# Normalize open_pct in d34 (check scale: decimal or percent?)
op4_dec = j34["open_pct"] / 100.0 if j34["open_pct"].abs().max() > 1.5 else j34["open_pct"]
j34["op4_dec"] = op4_dec
j34["val_sell_d4_open"] = 1.0 + j34["op4_dec"]
j34["delta_2to3_sell_pct"] = (j34["val_sell_d4_open"] / j34["val_hold_rel_d3c"] - 1.0) * 100.0
# For 3to4 buyer: if triggered p_ret*100, and also open-buy return = (val_hold_rel_d3c*(1-FEE)/(1+op4_dec) - 1)*100
j34["relay_3to4_open_pct"] = (j34["val_hold_rel_d3c"] * (1.0 - FEE) / (1.0 + j34["op4_dec"]) - 1.0) * 100.0

print("\n=== 2. NODE 2 DUALITY (Day 4 三板交接棒: 2进3立卖超额 vs 3进4接力净收益, N=%d) ===" % len(j34))
node2_rows = []
for name, mask in [
    ("D4弱开 <+3.0% (三进四拒接死门)", j34["op4_dec"] < 0.030),
    ("D4极高开 >+9.2% (三进四拒接死门)", j34["op4_dec"] > 0.092),
    ("D3零开板死封 (open_board_count==0)", j34["open_board_count"] == 0),
    ("D3一日游席位砸盘 (surf_yz_buy==1)", j34["surf_yz_buy"] == 1),
    ("同题材队友竞价 <-1.5% (核按钮)", j34["plate_peers_open_avg"] < (-1.5 if j34["plate_peers_open_avg"].abs().max() > 1.5 else -0.015)),
    ("雪球盘前热帖 >=4帖", j34["xq_cnt_tot"].fillna(0) >= 4),
    ("昨涨停>=95家高潮", j34["mkt_zt_prev"] >= 95),
    ("三进四低分拒接池 (sc_v34 < 82)", j34["sc_v34"] < 82),
    ("[反向对偶:三进四>=90分抢筹池]", (j34["sc_v34"] >= 90) & j34["op4_dec"].between(0.030, 0.092) & (j34["open_board_count"] >= 1)),
]:
    si, so, sa = j34[mask & (~j34["is_oos"])], j34[mask & j34["is_oos"]], j34[mask]
    trig = sa[sa["p_trig"]]
    r = {
        "factor": name, "n": int(len(sa)), "n_trig": int(len(trig)),
        "sell_is": round(float(si["delta_2to3_sell_pct"].mean()), 2) if len(si) else 0.0,
        "sell_oos": round(float(so["delta_2to3_sell_pct"].mean()), 2) if len(so) else 0.0,
        "buy_op_is": round(float(si["relay_3to4_open_pct"].mean()), 2) if len(si) else 0.0,
        "buy_op_oos": round(float(so["relay_3to4_open_pct"].mean()), 2) if len(so) else 0.0,
        "trig_ret": round(float(trig["p_ret"].mean() * 100), 2) if len(trig) else None,
        "trig_wr": round(float((trig["p_ret"] > 0).mean() * 100), 1) if len(trig) else None,
    }
    node2_rows.append(r)
    print(f"  {name:38s} | n={r['n']:4d} | 2进3早卖超额(IS/OOS):{r['sell_is']:+6.2f}%/{r['sell_oos']:+6.2f}% | 3进4开盘接盘(IS/OOS):{r['buy_op_is']:+6.2f}%/{r['buy_op_oos']:+6.2f}% | t65触发:{r['n_trig']}笔/{r['trig_ret']}%")

# --- 3. CONCRETE INTERLOCK BACKTESTS ---
# Interlock A: 2to3 V1.0 sealed_3b entering Day 4 -> sell at Day 4 09:25 if 3to4 refuses to relay!
raw90 = c_23_raw90[c_23_raw90["buy_date"] >= "2021-11-15"].copy()
raw90["c6"] = raw90["code"].astype(int).astype(str).str.zfill(6)
raw90 = raw90.merge(m23[["c6", "buy_date", "open_pct", "close_pct", "sealed_3b", "plate_sz", "peers_open_avg_2b"]], on=["c6", "buy_date"], how="left")
d4_lookup = d34_sub[["c6", "sig_date", "buy_date", "open_pct", "open_board_count", "surf_yz_buy", "sc_v34", "is_zt_today"]].rename(
    columns={"sig_date": "buy_date", "buy_date": "d4_date", "open_pct": "d4_op"}
)
d4_lookup["d4_op_dec"] = d4_lookup["d4_op"] / 100.0 if d4_lookup["d4_op"].abs().max() > 1.5 else d4_lookup["d4_op"]
raw90 = raw90.merge(d4_lookup, on=["c6", "buy_date"], how="left")

def sim_2to3_interlock(df_in, mode):
    df = df_in.copy()
    new_ret, new_ed, new_eh = [], [], []
    for r in df.itertuples(index=False):
        ret, ed, eh = float(r.net_ret), str(r.exit_date), int(r.exit_hhmm)
        if bool(r.sealed_3b) and pd.notna(r.d4_op_dec) and r.d4_op_dec > -0.095:
            sell_d4_open_ret = (1.0 + float(r.close_pct)) * (1.0 + float(r.d4_op_dec)) / (1.0 + float(r.open_pct)) * (1.0 - FEE) - 1.0
            cond = False
            if mode == "M1_d4_op_lt_0":
                cond = r.d4_op_dec < 0.0
            elif mode == "M2_d4_op_lt_3pct_and_low_v34":
                cond = (r.d4_op_dec < 0.030) and (float(r.sc_v34) < 82)
            elif mode == "M3_3to4_dead_surf_or_deepgreen":
                cond = (r.d4_op_dec < -0.020) or (int(r.surf_yz_buy or 0) == 1 and r.d4_op_dec < 0.030)
            elif mode == "M4_all_d4_op_lt_3pct":
                cond = r.d4_op_dec < 0.030
            if cond:
                ret, ed, eh = sell_d4_open_ret, str(r.d4_date), 925
        new_ret.append(ret); new_ed.append(ed); new_eh.append(eh)
    df["r_sim"], df["ed_sim"], df["eh_sim"] = new_ret, new_ed, new_eh
    srt = df.sort_values(["buy_date", "score", "open_pct", "plate_sz", "code"], ascending=[True, False, True, True, True])
    taken, fdt, fhh = [], "", 0
    for r in srt.itertuples(index=False):
        if fdt == "" or str(r.buy_date) > fdt or (str(r.buy_date) == fdt and 925 > fhh):
            taken.append(r); fdt, fhh = str(r.ed_sim), int(r.eh_sim)
    tk = pd.DataFrame(taken)
    def stat(sub):
        rr = sub["r_sim"].to_numpy()
        return len(rr), round(float((rr > 0).mean()*100), 2), round(float(np.prod(1+rr)), 2)
    n5, wr5, nav5 = stat(tk)
    ni, wri, navi = stat(tk[tk["buy_date"] < "2024-01-01"])
    no, wro, navo = stat(tk[tk["buy_date"] >= "2024-01-01"])
    pk = cur = 1.0; mdd = 0.0
    for x in tk["r_sim"]:
        cur *= 1+x; pk = max(pk, cur); mdd = max(mdd, (pk-cur)/pk)
    return {"mode": mode, "n5": n5, "wr5": wr5, "nav5": nav5, "mdd5": round(mdd*100, 2), "is": (ni, wri, navi), "oos": (no, wro, navo)}

print("\n=== 3. INTERLOCK BACKTEST: 2进3封三板后在Day4用「三进四拒接信号」提前09:25止盈/避险 ===")
interlock_23 = []
for m in ["Base_V10", "M1_d4_op_lt_0", "M2_d4_op_lt_3pct_and_low_v34", "M3_3to4_dead_surf_or_deepgreen", "M4_all_d4_op_lt_3pct"]:
    res = sim_2to3_interlock(raw90, m)
    interlock_23.append(res)
    print(f"  {m:34s} | 5Y: {res['n5']}b WR={res['wr5']}% NAV={res['nav5']}x MDD={res['mdd5']}% | IS:{res['is']} | OOS:{res['oos']}")

out = {"node1_day3_duality": node1_rows, "node2_day4_duality": node2_rows, "interlock_2to3_day4": interlock_23}
(OUT_DIR / "result_C_handoff_exit_entry_duality.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
print("SAVED result_C_handoff_exit_entry_duality.json")
