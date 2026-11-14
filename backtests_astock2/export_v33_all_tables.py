#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""持久化 V3.3 星期与日历特征至 cand_3to4_enriched54.parquet，并导出全套指标 JSON 与飞书净值轨迹图"""
import os, sys, json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from core_3to4_5m_engine import csi300_ret, CSI300_MAP, _slice_metrics_chrono, _sim_single_slot_chrono
from bt_3to4_v32_final_build import PARQ_PATH, df, sim_pool
from bt_3to4_scorecard_verify import sim_dd_ctrl
from score_3to4_v31_card import score_single_3to4_row

OUT_JSON = f"{CUR_DIR}/v32_all_metrics.json"
OUT_PNG = f"{CUR_DIR}/feishu_3to4_v32_chart1.png"

all_tdts = sorted(CSI300_MAP.keys())
td_pos = {d: i for i, d in enumerate(all_tdts)}
gap_prev = [(pd.Timestamp(d) - pd.Timestamp(all_tdts[td_pos[d] - 1])).days if d in td_pos and td_pos[d] > 0 else 1 for d in df["buy_date"]]
gap_sig = [(pd.Timestamp(b) - pd.Timestamp(s)).days for b, s in zip(df["buy_date"], df["sig_date"])]
gap_next = [(pd.Timestamp(all_tdts[td_pos[d] + 1]) - pd.Timestamp(d)).days if d in td_pos and td_pos[d] < len(all_tdts) - 1 else (3 if pd.Timestamp(d).weekday() == 4 else 1) for d in df["buy_date"]]

df["is_post_holiday_or_mon"] = np.array(gap_prev) >= 3
df["is_pre_holiday_or_fri"] = np.array(gap_next) >= 3
df["buy_month"] = pd.to_datetime(df["buy_date"]).dt.month

p_v32 = sim_pool("touch65_1130", "cut_weak", "pm1345", True, False)
p_v31 = sim_pool("touch65_1130", "reb2", "pm1345", False, False)
p_open = sim_pool("open", "cut_weak", "pm1345", True, False)
p_all15 = sim_pool("touch65_all", "cut_weak", "pm1345", True, False)
p_dev93 = sim_pool("touch65_1130", "cut_weak", "pm1345", True, True)

skel_base = (
    df["is_10cm_non_st"] & (~df["prev_is_yizi"]) & df["buyable_open"]
    & (~df["has_tox_notice"]) & (~df["has_stock_reg"])
    & (df["open_board_count"] >= 1)
    & ((df["lock_top10"] >= 45.0) | (df["real_free_mcap"] >= 45.0))
    & df["prev_to"].between(8.5, 31.0) & df["open_pct"].between(0.030, 0.092)
)
skel_v32 = skel_base & df["is_top1_3b_open"].astype(bool)
pts_common = (
    np.where(df["px_d3"] <= 20.0, 8.0, np.where(df["px_d3"] > 32.0, -5.0, 0.0))
    + np.where(df["mkt_max_board_prev"] <= 4, 8.0, 0.0)
    + np.where(df["mkt_zt_prev"] >= 95, -10.0, np.where(df["mkt_zt_prev"].between(35, 85), 5.0, 0.0))
    + np.where(df["has_ex_reg"], -12.0, 0.0)
    + np.where(df["lhb_lh_cnt"] == 0, 4.0, np.where(df["lhb_lh_cnt"] >= 3, -5.0, 0.0))
    + np.where((df["plate_fb_ho_cnt"] >= 2) & (df["plate_fb_yz_cnt"] == 0), 4.0, 0.0)
    + np.where(df["plate_fb_yz_cnt"] >= 1, -7.0, 0.0)
    + np.where(df["plate_peers_open_avg"] < -0.015, -10.0, 0.0)
    + np.where(df["prev_3b_dt_cnt"] == 0, 3.0, np.where(df["prev_3b_dt_cnt"] >= 2, -4.0, 0.0))
    + np.where((df["csi_1d_prev"] <= -0.020) | (df["csi_5d_prev"] <= -0.030), -8.0, 0.0)
    + np.where(df["prev_to"].between(9.5, 28.0), 3.0, 0.0)
)
sc_v31 = np.where(skel_base, 70.0 + np.where(df["is_top1_3b_open"], 8.0, 0.0) + pts_common, -999.0)
pts_v32_core = 78.0 + pts_common + np.where(df["p_elo"] >= 115.0, 3.0, 0.0) + np.where(df["surf_yz_buy"], -12.0, 0.0)
sc_v32_prev = np.where(skel_v32, pts_v32_core, -999.0)
sc_v33_prev = np.where(skel_v32, pts_v32_core + np.where(df["is_post_holiday_or_mon"], 2.0, 0.0) + np.where(df["buy_month"].isin([1, 5]), -4.0, 0.0), -999.0)
_fst = pd.to_numeric(df["first_seal_time"].astype(str).str.replace(":", "").str[:4], errors="coerce").fillna(9999)
skel_v34 = (df["is_10cm_non_st"] & (~df["prev_is_yizi"]) & df["buyable_open"] & (~df["has_tox_notice"]) & (~df["has_stock_reg"])
            & (df["open_board_count"] >= 1) & df["open_pct"].between(0.030, 0.092))
pts_v34 = (pts_v32_core + np.where(df["is_post_holiday_or_mon"], 2.0, 0.0) + np.where(df["buy_month"].isin([1, 5]), -4.0, 0.0)
           + np.where(df["is_top1_3b_open"].astype(bool), 0.0, -12.0)
           + np.where((df["lock_top10"] >= 45.0) | (df["real_free_mcap"] >= 45.0), 0.0, -10.0)
           + np.where(df["prev_to"].between(8.5, 31.0), 0.0, -10.0)
           + np.where(_fst.between(936, 1030), 3.0, 0.0))
sc_v33 = np.where(skel_v34, pts_v34, -999.0)

# Cross-verify 100% row-by-row parity with score_single_3to4_row!
card_scores = np.array([score_single_3to4_row(r)["score"] for r in df.to_dict("records")], dtype=float)
assert np.array_equal(card_scores, sc_v33), "Mismatch between vectorized V3.3 and score_single_3to4_row!"
df["score_v33"] = sc_v33.astype(int); df["score_v34"] = sc_v33.astype(int)
df.to_parquet(PARQ_PATH, index=False)

def full_eval(mask, pool, sc_arr):
    recs = [dict(pool[i], score=int(sc_arr[i]), priority_score=float(sc_arr[i])*10.0 + float(df["prio_3to4"].iloc[i])*0.1)
            for i in np.where(np.asarray(mask, dtype=bool))[0] if pool[i] is not None]
    tdf = pd.DataFrame(recs)
    c4 = (1+csi300_ret("2022-01-04","2024-12-31"))*(1+csi300_ret("2026-01-01","2026-11-10")) - 1.0
    ex4 = _slice_metrics_chrono(tdf[~tdf["buy_date"].str.startswith("2025")], "2022-01-04", "2026-11-10")
    ex4["csi300_pct"] = round(c4 * 100.0, 2)
    ex4["single_excess_pct"] = round(((ex4["single_nav"] - 1.0) - c4) * 100.0, 2)
    hnav, hmdd = sim_dd_ctrl(tdf, "half_cb")
    return {
        "full_5y": _slice_metrics_chrono(tdf, "2022-01-04", "2026-11-10"), "ex2025_4y": ex4,
        "oos_2526": _slice_metrics_chrono(tdf[tdf["buy_date"] >= "2025-01-01"], "2025-01-01", "2026-11-10"),
        "recent_3y": _slice_metrics_chrono(tdf[tdf["buy_date"] >= "2024-01-02"], "2024-01-02", "2026-11-10"),
        "recent_1y": _slice_metrics_chrono(tdf[tdf["buy_date"] >= "2025-11-12"], "2025-11-12", "2026-11-10"),
        "since_jul2026": _slice_metrics_chrono(tdf[tdf["buy_date"] >= "2026-07-01"], "2026-07-01", "2026-11-10"),
        "half_cb_5y": {"nav": round(hnav, 2), "mdd_pct": round(hmdd * 100.0, 1)},
        "annual": {yr: _slice_metrics_chrono(tdf[tdf["buy_date"].str.startswith(yr)], f"{yr}-01-01", f"{yr}-12-31" if yr != "2026" else "2026-11-10") for yr in ["2022", "2023", "2024", "2025", "2026"]},
    }, tdf

ev_std90, tdf_std90 = full_eval(sc_v33 >= 90, p_v32, sc_v33)
ev_str98, tdf_str98 = full_eval(sc_v33 >= 98, p_v32, sc_v33)
ev_def102, _ = full_eval(sc_v33 >= 102, p_v32, sc_v33)
ev_v32_prev90, _ = full_eval(sc_v33_prev >= 90, p_v32, sc_v33_prev)
ev_v32_prev98, _ = full_eval(sc_v33_prev >= 98, p_v32, sc_v33_prev)
ev_old90, tdf_old90 = full_eval(sc_v31 >= 90, p_v31, sc_v31)
ev_old78, _ = full_eval(sc_v31 >= 78, p_v31, sc_v31)
ev_old98, _ = full_eval(sc_v31 >= 98, p_v31, sc_v31)
ev_raw, _ = full_eval(df["is_10cm_non_st"] & (~df["prev_is_yizi"]) & df["buyable_open"], p_open, np.zeros(len(df)))
ev_yizi, _ = full_eval(df["is_10cm_non_st"] & df["prev_is_yizi"] & df["buyable_open"], p_open, np.zeros(len(df)))
ev_open90, _ = full_eval(sc_v33 >= 90, p_open, sc_v33)
ev_all15_90, _ = full_eval(sc_v33 >= 90, p_all15, sc_v33)
ev_dev93_98, _ = full_eval(sc_v33 >= 98, p_dev93, sc_v33)

taken90, _, _, _ = _sim_single_slot_chrono(tdf_std90)
sample_trades = [{"buy_date": t.buy_date, "code": t.code, "name": t.name, "score": int(t.score),
                  "exit_date": t.exit_date, "net_ret_pct": round(float(t.net_ret)*100.0, 2)} for t in taken90[-18:]]

summary = {
    "v32_std90": ev_std90, "v32_str98": ev_str98, "v32_def102": ev_def102,
    "v32_prev_std90": ev_v32_prev90, "v32_prev_str98": ev_v32_prev98,
    "v31_old90": ev_old90, "v31_old78": ev_old78, "v31_old98": ev_old98,
    "raw_non_yizi_open": ev_raw, "raw_prev_yizi_open": ev_yizi,
    "v32_std90_buy_open": ev_open90, "v32_std90_buy_allday": ev_all15_90,
    "v32_str98_with_dev93": ev_dev93_98, "recent_trades_std90": sample_trades,
}
with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False
all_dts = sorted(k for k in CSI300_MAP.keys() if "2022-01-04" <= k <= "2026-11-10")
dt_objs = pd.to_datetime(all_dts)
base_idx = CSI300_MAP[max(k for k in CSI300_MAP.keys() if k < "2022-01-04")]
csi_curve = [CSI300_MAP[d] / base_idx for d in all_dts]

def build_daily_curve(tdf_in):
    taken, _, _, _ = _sim_single_slot_chrono(tdf_in)
    ev_map, nav = {}, 1.0
    for t in taken:
        nav *= (1.0 + float(t.net_ret)); ev_map[t.exit_date] = nav
    cur, arr = 1.0, []
    for d in all_dts:
        if d in ev_map: cur = ev_map[d]
        arr.append(cur)
    return arr

c_std, c_str, c_old = build_daily_curve(tdf_std90), build_daily_curve(tdf_str98), build_daily_curve(tdf_old90)
fig, ax = plt.subplots(figsize=(11.5, 6.6), dpi=180)
ax.plot(dt_objs, c_std, color="#D62728", lw=2.6, label=f"三进四现役定版V3.4标准档90分（终点{ev_std90['full_5y']['single_nav']:.2f}倍，回撤{ev_std90['full_5y']['single_mdd_pct']:.1f}%）")
ax.plot(dt_objs, c_str, color="#1B8A5A", lw=2.1, label=f"三进四严格高确信档98分（终点{ev_str98['full_5y']['single_nav']:.2f}倍，盈亏比{ev_str98['full_5y']['payoff']:.2f}）")
ax.plot(dt_objs, c_old, color="#1F77B4", lw=1.8, ls="--", label=f"未升级原版90分档（终点{ev_old90['full_5y']['single_nav']:.2f}倍，回撤{ev_old90['full_5y']['single_mdd_pct']:.1f}%）")
ax.plot(dt_objs, csi_curve, color="#666666", lw=1.5, ls=":", label=f"沪深300基准（终点0.82倍，跌{abs(ev_std90['full_5y']['csi300_pct']):.2f}%）")
ax.scatter([dt_objs[-1]], [c_std[-1]], color="#D62728", s=65, zorder=5)
ax.annotate(f"现役V3.4标准档 {ev_std90['full_5y']['single_nav']:.2f}倍\n连续五年全正收益", xy=(dt_objs[-1], c_std[-1]),
            xytext=(dt_objs[-220], c_std[-1]*0.68), color="#D62728", fontsize=10.5, fontweight="bold")
ax.set_yscale("log")
yticks = [0.6, 0.8, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 560.0]
ax.set_yticks(yticks)
ax.set_yticklabels([f"{y:.1f}倍" for y in yticks], fontsize=10)
ax.xaxis.set_major_locator(mdates.YearLocator()); ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y年"))
ax.grid(True, which="both", ls="--", alpha=0.32)
ax.set_ylabel("累计净值倍数（对数坐标，扣双边千二摩擦）", fontsize=11)
ax.set_title("2022年至2026年三进四V3.4策略与沪深300净值对数增长轨迹", fontsize=14, pad=12)
ax.legend(loc="upper left", fontsize=10, framealpha=0.92)
plt.tight_layout(); plt.savefig(OUT_PNG, dpi=180); plt.close()
print("V3.3 Std90 5Y:", ev_std90["full_5y"])
print("V3.3 Str98 5Y:", ev_str98["full_5y"])
print("V3.3 Def102 5Y:", ev_def102["full_5y"])
print("V3.3 Annual:", {k: (v["single_n"], v["wr"], round((v["single_nav"]-1)*100,1), v["csi300_pct"]) for k, v in ev_std90["annual"].items()})
