#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
p2_enrich_factors.py: Enrich all 6,637 trigger cases with 200+ factors.
Strict zero-future-function PIT check: all stock features on T-1 (pos - 1)!
"""
import os, sys, time, json, pickle, sqlite3, bisect, datetime
import numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SANDBOX = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab"
MATRIX = f"{SANDBOX}/grand_factor_matrix_20261112"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/p4_pry_board"

print("[+] Loading raw triggers & daily env...")
t0 = time.time()
df_trig = pd.read_parquet(f"{OUT_DIR}/p2_all_triggers_with_exits.parquet")
df_env = pd.read_parquet(f"{MATRIX}/daily_env_5y.parquet").set_index("dt_str").to_dict(orient="index")

with open(f"{MATRIX}/code_bars_5y.pkl", "rb") as f:
    cb = pickle.load(f)["code_bars"]

with open(f"{MATRIX}/pit_top10_all_codes.json") as f:
    holders_idx = json.load(f)

# Load existing candidate tables for fast left join
df_h = pd.read_parquet(f"{MATRIX}/cand_high_dragon.parquet")
df_23 = pd.read_parquet(f"{MATRIX}/cand_2to3.parquet")
df_34 = pd.read_parquet(f"{ROOT}/sim-portfolio/backtests_astock2/data_5y/cand_3to4_enriched54.parquet")

# Common 83 columns
common_cols = [c for c in df_h.columns if c in df_23.columns and c not in ("sig_date", "gap_days", "open_pct", "h_pct", "l_pct", "pct", "buyable_open", "is_yizi_open", "is_zt_today", "touch_zt_today", "touch_dt_today")]
df_feat = pd.concat([df_h[common_cols], df_23[common_cols]], ignore_index=True)
df_feat.drop_duplicates(subset=["code", "buy_date"], keep="first", inplace=True)
df_feat["c6"] = df_feat["code"].astype(str).str.zfill(6)
df_feat["bd"] = df_feat["buy_date"].astype(str).str[:10]
feat_map = df_feat.set_index(["c6", "bd"]).to_dict(orient="index")

print(f"Loaded existing feature map with {len(feat_map)} records in {time.time()-t0:.2f}s")

# Load notices DB
t_not = time.time()
con_not = sqlite3.connect(f"file:{ROOT}/sim-portfolio/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
df_not = pd.read_sql_query("SELECT sec_code, pub_datetime_cst, ann_type, title FROM notices WHERE trade_date_avail >= '2021-12-01'", con_not)
con_not.close()
df_not["c6"] = df_not["sec_code"].astype(str).str.zfill(6)
df_not["dt"] = df_not["pub_datetime_cst"].astype(str)

notice_by_c6 = {}
for c6, grp in df_not.groupby("c6"):
    notice_by_c6[c6] = sorted(zip(grp["dt"], grp["ann_type"], grp["title"]))
print(f"Loaded notices for {len(notice_by_c6)} codes in {time.time()-t_not:.2f}s")

def get_lock(c6, dt_str):
    valid = [r for r in holders_idx.get(c6, []) if r[0] < dt_str]
    if not valid: return 38.0, 25.0
    b = max(valid, key=lambda x: x[1])
    return float(b[2]), float(b[3])

def check_notices(c6, bd):
    start_cut = (datetime.date.fromisoformat(bd) - datetime.timedelta(days=90)).isoformat()
    end_cut = f"{bd} 09:25:00"
    n_list = notice_by_c6.get(c6, [])
    nh = n_ma = n_earn = n_bad = False
    if n_list:
        lo = bisect.bisect_left(n_list, (start_cut, "", ""))
        for idx in range(lo, len(n_list)):
            pdt, atype, title = n_list[idx]
            if pdt > end_cut: break
            t_str = f"{atype} {title}"
            if any(k in t_str for k in ("立案", "违规", "处罚", "警示", "退市", "风险", "占用", "造假", "虚假")):
                n_bad = True
            if any(k in t_str for k in ("重组", "收购", "合并", "重大资产")):
                n_ma = True
            if any(k in t_str for k in ("预增", "扭亏", "增长", "业绩快报")):
                n_earn = True
            if any(k in t_str for k in ("芯片", "算力", "半导体", "人工智能", "机器人", "光伏")):
                nh = True
    return nh, n_ma, n_earn, n_bad

print("[+] Enriching candidate rows with factors...")
t_enr = time.time()
enriched_rows = []

for r in df_trig.itertuples(index=False):
    c6 = str(r.code).zfill(6)
    bd = str(r.buy_date)[:10]
    b = cb.get(c6)
    pos = r.pos
    env = df_env.get(bd, {})
    
    # Base price metrics on T-1 (pos - 1)
    prev_cl = float(b["close"][pos-1]) if pos > 0 else float(b["pre_c"][pos])
    op = float(b["open"][pos])
    p_to = float(b["to"][pos-1]) if pos > 0 else 8.0
    
    # Price positions on T-1 strictly
    p_close20 = b["close"][max(0, pos-20):pos]
    min20 = float(np.min(p_close20)) if len(p_close20) > 0 else prev_cl
    max20 = float(np.max(p_close20)) if len(p_close20) > 0 else prev_cl
    pos20 = (prev_cl - min20) / (max20 - min20 + 1e-6)
    dd20 = prev_cl / (max20 + 1e-6)
    
    p_close60 = b["close"][max(0, pos-60):pos]
    max60 = float(np.max(p_close60)) if len(p_close60) > 0 else prev_cl
    dd60 = prev_cl / (max60 + 1e-6)
    
    ret_pre10 = (b["close"][pos-1] / (b["close"][max(0, pos-10)] + 1e-6) - 1.0) if pos > 0 else 0.0
    
    # Streaks and ZT counts on T-1 strictly
    p_streak = 0
    if pos > 0:
        for k in range(pos-1, -1, -1):
            if b["is_zt"][k]: p_streak += 1
            else: break
    zt20 = int(np.sum(b["is_zt"][max(0, pos-20):pos]))
    zt10 = int(np.sum(b["is_zt"][max(0, pos-10):pos]))
    
    # Lockup
    l10, l5 = get_lock(c6, bd)
    
    # Notices
    nh, n_ma, n_earn, n_bad = check_notices(c6, bd)
    
    # Existing features if present
    ef = feat_map.get((c6, bd), {})
    
    # 身位垄断
    mkt_max_b = int(env.get("mkt_max_board_prev", 0))
    mkt_top_cnt = int(env.get("mkt_top_cnt_prev", 0))
    is_max_b = (p_streak == mkt_max_b) and (mkt_max_b >= 3)
    is_sole_max = is_max_b and (mkt_top_cnt == 1)
    is_mid_nuke = (p_streak >= 2) and (p_streak < mkt_max_b)
    
    row_dict = r._asdict()
    row_dict.update({
        # 身位
        "prev_streak": p_streak,
        "mkt_max_board_prev": mkt_max_b,
        "mkt_top_cnt_prev": mkt_top_cnt,
        "is_max_board_prev": is_max_b,
        "is_sole_max_board_prev": is_sole_max,
        "is_mid_nuke": is_mid_nuke,
        "prior_mb_gap": mkt_max_b - p_streak,
        "dom_gap": float(ef.get("dom_gap", 0.0)),
        "is_dominant_day": bool(ef.get("is_dominant_day", False)),
        "is_melee_day": bool(ef.get("is_melee_day", False)),
        
        # 换手基因 vs 一字
        "prev_is_yizi": bool(b["is_yizi"][pos-1]) if pos > 0 else False,
        "prev_to": p_to,
        "prev_real_to": p_to / max(0.05, 1.0 - l10 / 100.0),
        "pos20": pos20,
        "dd20": dd20,
        "dd60": dd60,
        "ret_pre10": ret_pre10,
        "clean_brk60": bool(ef.get("clean_brk60", False)),
        
        # 板块活口与助攻
        "plate": ef.get("plate", "其他"),
        "p_sz": int(ef.get("p_sz", 1)),
        "s_prior": float(ef.get("s_prior", 100.0)),
        "p_elo": float(ef.get("p_elo", 100.0)),
        "s_elo": float(ef.get("s_elo", 100.0)),
        "plate_peers_open_avg": float(ef.get("plate_peers_open_avg", 0.0)),
        "plate_yizi_cnt": int(ef.get("plate_yizi_cnt", 0)),
        "is_event_basket": bool(ef.get("is_event_basket", False)),
        "is_broad_ind": bool(ef.get("is_broad_ind", False)),
        "sub_cluster_cnt": int(ef.get("sub_cluster_cnt", 1)),
        
        # 筹码与容量
        "lock_top10": l10,
        "lock_big5": l5,
        "open_px_raw": op,
        "mcap": float(ef.get("mcap", 40.0)),
        "real_free_mcap": float(ef.get("real_free_mcap", 20.0)),
        
        # 席位与公告
        "lhasa_seats_prev": int(ef.get("lhasa_seats_prev", 0)),
        "lhasa_buy_share_prev": float(ef.get("lhasa_buy_share_prev", 0.0)),
        "notice_hard": nh,
        "notice_ma": n_ma,
        "notice_earn": n_earn,
        "notice_bad": n_bad,
        "has_ir_8d": bool(ef.get("has_ir_8d", False)),
        "comm_posts_24h": int(ef.get("comm_posts_24h", 0)),
        
        # 大盘环境与日历
        "mkt_zt_prev": int(env.get("mkt_zt_prev", 40)),
        "mkt_dt_prev": int(env.get("mkt_dt_prev", 10)),
        "mkt_seal_rate_prev": float(env.get("mkt_seal_rate_prev", 0.70)),
        "mkt_fb_open_avg": float(env.get("mkt_fb_open_avg", 0.02)),
        "mkt_promo_1to2_5d": float(env.get("mkt_promo_1to2_5d", 0.20)),
        "csi300_ret5": float(env.get("csi300_ret5", 0.0)),
        "csi300_ret20": float(env.get("csi300_ret20", 0.0)),
        "month": int(bd[5:7]),
        "weekday": datetime.date.fromisoformat(bd).weekday(),
        "quarter": (int(bd[5:7]) - 1) // 3 + 1,
    })
    enriched_rows.append(row_dict)

df_enriched = pd.DataFrame(enriched_rows)
out_p = f"{OUT_DIR}/p2_master_enriched_triggers.parquet"
df_enriched.to_parquet(out_p)
print(f"[+] Successfully saved {len(df_enriched)} rows x {len(df_enriched.columns)} columns to {out_p} in {time.time()-t_enr:.2f}s")
