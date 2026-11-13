#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
开盘啦全量本地库与游资/老妖记忆深度挖掘脚本
- 严守零未来函数（100% PIT）
- 双期同向检验：2022-2024 (前三年) vs 2025-2026 (近两年)
- 数据源：zt_micro_tape_5y_pit.db, kpl_plates_2018_2026_merged.jsonl, lhb_buy/sell.parquet, severe_his.json
"""
import os, sys, json, sqlite3, pickle, re
from collections import defaultdict
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"

# 1. 读取基础缓存与高标首阴池
print("[Step 1] Loading base cache and canonical high dragon dataset...")
(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{OUT_DIR}/part1_cache.pkl", "rb"))
dfr = pd.read_pickle(f"{OUT_DIR}/dfr_deep_native.pkl")
print(f"Loaded dfr_deep_native with {len(dfr)} records.")

# 2. 读取开盘啦 2018-2026 八年半题材与涨停库
print("[Step 2] Loading KPL 2018-2026 historical merged JSONL...")
jl_path = f"{ROOT}/sim-portfolio/data/kpl_plates_2018_2026_merged.jsonl"
kpl_stock_zt_days = defaultdict(list)     # code -> list of (date_str, plate, name, reason)
kpl_plate_first_seen = {}                 # plate -> min_date
kpl_plate_dates = defaultdict(set)        # plate -> set of date_str
kpl_daily_zt_stocks = defaultdict(dict)   # date_str -> {code: (plate, name, reason)}

with open(jl_path, "r", encoding="utf-8") as f:
    for line in f:
        item = json.loads(line)
        d = item["date"]
        for pl in item.get("plates", []):
            pname = pl["plate"]
            if pname not in kpl_plate_first_seen:
                kpl_plate_first_seen[pname] = d
            kpl_plate_dates[pname].add(d)
            for st in pl.get("stocks", []):
                c6 = str(st[0]).zfill(6)
                name = st[1]
                r1 = st[2] if len(st) > 2 else ""
                r2 = st[3] if len(st) > 3 else ""
                reason = f"{r1} {r2}".strip()
                kpl_stock_zt_days[c6].append((d, pname, name, reason))
                kpl_daily_zt_stocks[d][c6] = (pname, name, reason)

# Sort each stock's historical zt entries
for c6 in kpl_stock_zt_days:
    kpl_stock_zt_days[c6].sort(key=lambda x: x[0])

print(f"Loaded KPL history: {len(kpl_stock_zt_days)} stocks, {len(kpl_plate_first_seen)} unique plates.")

# 3. 读取并清洗龙虎榜买卖全席位库
print("[Step 3] Loading LHB buy and sell parquets...")
lb = pd.read_parquet(f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet", columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"])
ls = pd.read_parquet(f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_sell.parquet", columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "SELL"])

lb["dt"] = lb["TRADE_DATE"].astype(str).str[:10]
lb["c6"] = lb["SECURITY_CODE"].astype(str).str[:6]
ls["dt"] = ls["TRADE_DATE"].astype(str).str[:10]
ls["c6"] = ls["SECURITY_CODE"].astype(str).str[:6]

# 按单日榜去重（防1日榜与3日榜双计，取 min 还原单日真实买卖额）
g_buy = lb[lb["dt"] >= "2021-10-01"].groupby(["dt", "c6", "OPERATEDEPT_NAME"], as_index=False)["BUY"].min()
g_sell = ls[ls["dt"] >= "2021-10-01"].groupby(["dt", "c6", "OPERATEDEPT_NAME"], as_index=False)["SELL"].min()

# 席位正则定义
RE_TOP_YOUZI = re.compile(
    r"(?:大连金马路|大连黄河路|六一中路|天津东丽开发区二纬路|北京东直门南大街|北京广渠门内大街|"
    r"上海江苏路|上海建国西路|杭州延安路|兴业证券.*陕西分公司|西安朱雀大街|"
    r"南京太平南路|宁波桑田路|上海宛平南路|上海红宝石路|上海茅台路|宁波和源路|北京长椿街)"
)
RE_DAY_SURF = re.compile(
    r"(?:杭州上塘路|宜昌沿江大道|宜昌珍珠路|佛山绿景路|佛山季华六路|佛山季华五路|江阴.*营业部|苏州.*营业部)"
)
RE_QUANT = re.compile(
    r"(?:华鑫.*上海分公司|国际金融.*上海分公司|中信.*上海分公司|高盛|瑞银|开源.*西安西大街|国泰君安.*总部|摩根大通)"
)
RE_LHASA = re.compile(r"(?:拉萨|东方财富证券.*拉萨)")
RE_INST = re.compile(r"机构专用")

lhb_daily_buy = defaultdict(list)
for r in g_buy.itertuples(index=False):
    lhb_daily_buy[(r.dt, r.c6)].append((r.OPERATEDEPT_NAME, float(r.BUY)))

lhb_daily_sell = defaultdict(list)
for r in g_sell.itertuples(index=False):
    lhb_daily_sell[(r.dt, r.c6)].append((r.OPERATEDEPT_NAME, float(r.SELL)))

print("LHB buy/sell indexed.")

# 4. 读取开盘啦 5 年涨停微观盘口库
print("[Step 4] Querying zt_micro_tape_5y_pit.db...")
db_path = f"{ROOT}/sim-portfolio/data/zt_micro_tape_5y_pit.db"
con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
cur = con.cursor()

# 预取全部涨停微观记录（10万条内存化）
cur.execute("""
    SELECT trade_date, sec_code, sec_name, first_seal_time, seal_amount, continuous_plate_tag,
           board_count, open_board_count, plate_name, reason_desc
    FROM zt_micro_tape
""")
tape_all = cur.fetchall()
con.close()

# 索引：(trade_date, sec_code) -> record
tape_map = {}
tape_by_date_plate = defaultdict(list)
tape_stock_history = defaultdict(list) # sec_code -> list of records sorted by trade_date

for row in tape_all:
    td, sc, sn, fst, sa, cpt, bc, obc, pn, rd = row
    rec = {
        "trade_date": td, "sec_code": sc, "sec_name": sn,
        "first_seal_time": fst or "99:99:99",
        "seal_amount": float(sa or 0.0),
        "continuous_plate_tag": cpt or "",
        "board_count": int(bc or 1),
        "open_board_count": int(obc or 0),
        "plate_name": pn or "",
        "reason_desc": rd or "",
    }
    tape_map[(td, sc)] = rec
    tape_by_date_plate[(td, pn)].append(rec)
    tape_stock_history[sc].append(rec)

for sc in tape_stock_history:
    tape_stock_history[sc].sort(key=lambda x: x["trade_date"])

print(f"Loaded zt_micro_tape: {len(tape_map)} records indexed.")

# 5. 读取严重异动与重点监控
print("[Step 5] Loading severe abnormal history...")
p_sev = f"{ROOT}/sim-portfolio/data/kpl/severe_his.json"
severe_map = defaultdict(set)
if os.path.exists(p_sev):
    with open(p_sev, "r") as f:
        sev_data = json.load(f)
    for r in sev_data.get("rows", []):
        if len(r) >= 19:
            sc = str(r[0]).zfill(6)
            warn_dt = str(r[18])
            severe_map[sc].add(warn_dt)
print(f"Loaded severe abnormal notices for {len(severe_map)} stocks.")

# 6. 特征构建：遍历 dfr_deep_native 119 笔记录
print("[Step 6] Extracting comprehensive features for each trade...")

feats = defaultdict(list)

for r in dfr.itertuples():
    c6 = str(r.code).zfill(6)
    d0 = str(r.d0)
    d1 = str(r.d1)
    b_dt = str(r.buy_date)
    st0 = int(r.st0)
    bars = code_bars[c6]
    d1p = bars["p"][d1]
    d0p = d1p - 1

    # ==========================================
    # A. 开盘啦涨停微观盘口特征 (zt_micro_tape)
    # ==========================================
    d0_rec = tape_map.get((d0, c6))
    if d0_rec:
        fst = d0_rec["first_seal_time"]
        sa = d0_rec["seal_amount"]
        cpt = d0_rec["continuous_plate_tag"]
        obc = d0_rec["open_board_count"]
        pname = d0_rec["plate_name"]
        rdesc = d0_rec["reason_desc"]
    else:
        fst, sa, cpt, obc, pname, rdesc = "99:99:99", 0.0, "", 0, "", ""

    # D0 封板时间
    fst_clean = fst if (fst and fst != "None") else "99:99:99"
    feats["kpl_d0_seal_early_0935"].append(fst_clean <= "09:35:00")
    feats["kpl_d0_seal_early_1000"].append(fst_clean <= "10:00:00")
    feats["kpl_d0_seal_late_1400"].append(fst_clean >= "14:00:00")
    
    # D0 封单与炸板
    feats["kpl_d0_obc_0"].append(obc == 0)
    feats["kpl_d0_obc_ge2"].append(obc >= 2)
    fmcap_val = float(r.fmcap) * 1e8 if (hasattr(r, "fmcap") and r.fmcap and r.fmcap > 0) else 1e9
    feats["kpl_d0_seal_fmcap_ratio"].append(sa / fmcap_val)
    feats["kpl_d0_seal_heavy"].append((sa / fmcap_val) >= 0.03) # 封单占自由流通市值>=3%

    # 连板全程微观盘口统计
    hist_tape = [x for x in tape_stock_history.get(c6, []) if x["trade_date"] <= d0]
    streak_tape = hist_tape[-st0:] if len(hist_tape) >= st0 else hist_tape
    tot_obc = sum(x["open_board_count"] for x in streak_tape)
    feats["kpl_streak_tot_obc"].append(tot_obc)
    feats["kpl_streak_has_split"].append(tot_obc >= 2)  # 连板全程充分换手分歧
    feats["kpl_streak_zero_obc"].append(tot_obc == 0)   # 连板全程0炸板一致性顶死

    # 连板标签与反包基因
    feats["kpl_tag_has_tian"].append("天" in cpt)        # 如 6天5板、8天7板等反包妖股基因
    feats["kpl_tag_straight"].append("连板" in cpt)      # 纯连板

    # 题材梯队助攻结构
    d0_peers = tape_by_date_plate.get((d0, pname), [])
    feats["kpl_d0_plate_zt_cnt"].append(len(d0_peers))
    feats["kpl_d0_plate_has_echelon"].append(len(d0_peers) >= 3) # 同题材>=3只涨停，梯队护航
    feats["kpl_d0_plate_solo"].append(len(d0_peers) <= 1)        # 孤苗独苗

    d1_peers = tape_by_date_plate.get((d1, pname), [])
    feats["kpl_d1_plate_zt_cnt"].append(len(d1_peers))
    feats["kpl_d1_plate_alive"].append(len(d1_peers) >= 1)       # D1首阴日题材未死

    # 涨停原因关键词挖掘
    feats["kpl_reason_mna"].append(bool(re.search(r"并购|重组|借壳|实控人|股权转让|资产注入", rdesc)))
    feats["kpl_reason_tech"].append(bool(re.search(r"算力|芯片|半导体|机器人|人工智能|AI|华为|低空|固态电池", rdesc)))
    feats["kpl_reason_earnings"].append(bool(re.search(r"预增|业绩|扭亏|超预期|净利润", rdesc)))
    feats["kpl_reason_concept"].append(bool(re.search(r"次新|摘帽|ST|股权激励", rdesc)))

    # ==========================================
    # B. 老票新炒与历史妖股记忆 (kpl_plates JSONL)
    # ==========================================
    past_zts = [x for x in kpl_stock_zt_days.get(c6, []) if x[0] < d0]
    
    # 历史涨停天数统计
    d0_ts = pd.Timestamp(d0)
    zt_1y = [x for x in past_zts if (d0_ts - pd.Timestamp(x[0])).days <= 365]
    zt_3y = [x for x in past_zts if (d0_ts - pd.Timestamp(x[0])).days <= 1095]
    feats["kpl_hist_1y_zt_cnt"].append(len(zt_1y))
    feats["kpl_hist_3y_zt_cnt"].append(len(zt_3y))

    # 过去1年和3年内是否曾走出过>=4板或>=5板
    # 利用 bars 快速查该股在过去250日内的最高连续涨停
    d0_idx_in_bars = d0p
    bars_is_zt = bars["is_zt"]
    
    def get_max_streak_in_window(end_p, win_len):
        start_p = max(0, end_p - win_len)
        max_s, cur_s = 0, 0
        for p in range(start_p, end_p): # strictly before D0
            if bars_is_zt[p]:
                cur_s += 1
                max_s = max(max_s, cur_s)
            else:
                cur_s = 0
        return max_s

    # 排除当前连板段，往前看的历史最高连板
    hist_end_p = max(0, d0p - st0)
    max_s_1y = get_max_streak_in_window(hist_end_p, 250)
    max_s_3y = get_max_streak_in_window(hist_end_p, 750)
    feats["kpl_hist_1y_max_streak"].append(max_s_1y)
    feats["kpl_hist_1y_has_ge4"].append(max_s_1y >= 4)
    feats["kpl_hist_1y_has_ge5"].append(max_s_1y >= 5)
    feats["kpl_hist_3y_has_ge5"].append(max_s_3y >= 5)

    # 距离上次涨停/连板冷却天数
    last_zt_p = None
    for p in range(hist_end_p - 1, -1, -1):
        if bars_is_zt[p]:
            last_zt_p = p; break
    days_since_last_zt = (hist_end_p - last_zt_p) if last_zt_p is not None else 999
    feats["kpl_days_since_last_zt"].append(days_since_last_zt)
    feats["kpl_recent_overheated_30d"].append(days_since_last_zt <= 30)       # 假说M2: 近期过热透支
    feats["kpl_cooled_45_250d"].append(45 <= days_since_last_zt <= 250)      # 假说M2: 充分冷却复活

    # 假说M3: 真·老票新炒 vs 老题材炒冷饭 vs 纯生面孔
    hist_plates_45_500d = set(x[1] for x in past_zts if 45 <= (d0_ts - pd.Timestamp(x[0])).days <= 500)
    curr_theme = pname
    is_new_face = (len(zt_1y) == 0)
    feats["kpl_is_new_face_1y"].append(is_new_face)
    if not is_new_face and curr_theme and (curr_theme not in hist_plates_45_500d):
        feats["kpl_old_stock_new_theme"].append(True)  # ★真·老票新炒！
        feats["kpl_old_stock_old_theme"].append(False)
    elif not is_new_face and curr_theme and (curr_theme in hist_plates_45_500d):
        feats["kpl_old_stock_new_theme"].append(False)
        feats["kpl_old_stock_old_theme"].append(True)  # 老题材炒冷饭
    else:
        feats["kpl_old_stock_new_theme"].append(False)
        feats["kpl_old_stock_old_theme"].append(False)

    # 假说M4: 开盘啦题材新旧周期
    if curr_theme in kpl_plate_dates:
        # 该题材在全市场上在 D0 前最近一次出现的历史跨度
        theme_dates_past = sorted([d for d in kpl_plate_dates[curr_theme] if d <= d0])
        first_d = theme_dates_past[0] if theme_dates_past else d0
        theme_age_days = (d0_ts - pd.Timestamp(first_d)).days
    else:
        theme_age_days = 999
    feats["kpl_theme_is_new_15d"].append(theme_age_days <= 15)   # 近15天刚冒出的新题材
    feats["kpl_theme_is_old_60d"].append(theme_age_days >= 60)   # 超过60天的老疲软题材

    # ==========================================
    # C. 龙虎榜席位与游资行为图谱 (LHB)
    # ==========================================
    d0_buys = lhb_daily_buy.get((d0, c6), [])
    d1_buys = lhb_daily_buy.get((d1, c6), [])
    d1_sells = lhb_daily_sell.get((d1, c6), [])

    feats["lhb_d0_has_list"].append(len(d0_buys) > 0)
    feats["lhb_d1_has_list"].append(len(d1_buys) > 0 or len(d1_sells) > 0)

    # D0 知名游资买入
    d0_top_names = [dept for dept, amt in d0_buys if RE_TOP_YOUZI.search(dept)]
    feats["lhb_d0_top_youzi_buy"].append(len(d0_top_names) > 0)
    feats["lhb_d0_day_surf_buy"].append(any(RE_DAY_SURF.search(dept) for dept, amt in d0_buys))

    # D1 顶级游资锁仓 vs 砸盘
    d1_sell_names = [dept for dept, amt in d1_sells]
    if d0_top_names:
        # D0买入的顶级游资在D1卖榜中没出现 -> 格局锁仓！
        locked = not any(any(top_n in sell_n for top_n in d0_top_names) for sell_n in d1_sell_names)
        feats["lhb_d0_top_locked"].append(locked)
    else:
        feats["lhb_d0_top_locked"].append(False)

    feats["lhb_d1_top_dumped"].append(any(RE_TOP_YOUZI.search(dept) for dept, amt in d1_sells))
    feats["lhb_d1_top_youzi_in"].append(any(RE_TOP_YOUZI.search(dept) for dept, amt in d1_buys))
    feats["lhb_d1_day_surf_in"].append(any(RE_DAY_SURF.search(dept) for dept, amt in d1_buys)) # 上塘路抄底

    # D1 净买入占比与拉萨买入占比
    d1_amt = float(by_dt[d1].loc[by_dt[d1]["c6"] == c6, "amount"].values[0]) if c6 in by_dt[d1]["c6"].values else 1e8
    tot_b = sum(amt for dept, amt in d1_buys)
    tot_s = sum(amt for dept, amt in d1_sells)
    net_amt = tot_b - tot_s
    feats["lhb_d1_net_amt_ratio"].append(net_amt / max(d1_amt, 1e7))
    feats["lhb_d1_net_positive"].append(net_amt > 0)

    lh_b = sum(amt for dept, amt in d1_buys if RE_LHASA.search(dept))
    lh_ratio = lh_b / max(tot_b, 1.0) if tot_b > 0 else 0.0
    feats["lhb_d1_lhasa_heavy"].append(lh_ratio >= 0.20) # 拉萨买入占比>=20%

    # ==========================================
    # D. 严重异动与监管监控 (Severe Abnormal)
    # ==========================================
    feats["kpl_d1_has_severe_alert"].append(d1 in severe_map.get(c6, set()))

# 将新挖掘特征装入 DataFrame
dfr_enriched = dfr.copy()
for k, v in feats.items():
    dfr_enriched[k] = v

print(f"Extraction complete. Total columns: {len(dfr_enriched.columns)} (added {len(feats)} new mined features).")

# 保存富化结果
dfr_enriched.to_pickle(f"{OUT_DIR}/sub1_kpl_enriched.pkl")
print(f"Saved sub1_kpl_enriched.pkl to {OUT_DIR}.")

# ==========================================
# E. 双期同向防过拟合检验
# ==========================================
print("\n" + "="*80)
print("=== DUAL-PERIOD CONSISTENCY AUDIT (2022-2024 vs 2025-2026) ===")
print("="*80)

# 仅在 can_ign==True 的真实可交易样本上检验，使用真实 hyb_sm net_ret
valid_mask = dfr_enriched["can_ign"] == True
df_v = dfr_enriched[valid_mask].copy()
df_v["hyb_ret"] = [r[1] for r in df_v["hyb_sm"]]

m_22_24 = df_v["buy_date"] < "2025-01-01"
m_25_26 = df_v["buy_date"] >= "2025-01-01"

print(f"Valid trade sample size: 2022-2024 = {m_22_24.sum()} trades, 2025-2026 = {m_25_26.sum()} trades, Total = {len(df_v)}")

audit_results = []

for col in feats.keys():
    s = df_v[col]
    s1 = df_v.loc[m_22_24, [col, "hyb_ret"]]
    s2 = df_v.loc[m_25_26, [col, "hyb_ret"]]
    
    if pd.api.types.is_bool_dtype(s) or s.nunique() == 2:
        # 二元布尔特征
        n_pos1 = (s1[col] == True).sum()
        n_neg1 = (s1[col] == False).sum()
        n_pos2 = (s2[col] == True).sum()
        n_neg2 = (s2[col] == False).sum()
        
        if n_pos1 < 3 or n_neg1 < 3 or n_pos2 < 3 or n_neg2 < 3:
            continue
            
        r_pos1 = s1[s1[col] == True]["hyb_ret"].mean() * 100
        r_neg1 = s1[s1[col] == False]["hyb_ret"].mean() * 100
        diff1 = r_pos1 - r_neg1

        r_pos2 = s2[s2[col] == True]["hyb_ret"].mean() * 100
        r_neg2 = s2[s2[col] == False]["hyb_ret"].mean() * 100
        diff2 = r_pos2 - r_neg2

        wr_pos1 = (s1[s1[col] == True]["hyb_ret"] > 0).mean() * 100
        wr_neg1 = (s1[s1[col] == False]["hyb_ret"] > 0).mean() * 100
        wr_pos2 = (s2[s2[col] == True]["hyb_ret"] > 0).mean() * 100
        wr_neg2 = (s2[s2[col] == False]["hyb_ret"] > 0).mean() * 100
        
        consistent = (diff1 * diff2 > 0)
        avg_diff = (diff1 + diff2) / 2.0
        
        audit_results.append({
            "factor": col,
            "type": "bool",
            "diff1": diff1,
            "diff2": diff2,
            "avg_diff": avg_diff,
            "wr_diff1": wr_pos1 - wr_neg1,
            "wr_diff2": wr_pos2 - wr_neg2,
            "n_pos": (df_v[col] == True).sum(),
            "n_neg": (df_v[col] == False).sum(),
            "consistent": consistent,
        })
    elif pd.api.types.is_numeric_dtype(s):
        # 连续数值特征：按中位数切分
        med = s1[col].median()
        hi1 = s1[s1[col] > med]["hyb_ret"].mean() * 100
        lo1 = s1[s1[col] <= med]["hyb_ret"].mean() * 100
        diff1 = hi1 - lo1

        hi2 = s2[s2[col] > med]["hyb_ret"].mean() * 100
        lo2 = s2[s2[col] <= med]["hyb_ret"].mean() * 100
        diff2 = hi2 - lo2
        
        consistent = (diff1 * diff2 > 0)
        avg_diff = (diff1 + diff2) / 2.0
        
        audit_results.append({
            "factor": col,
            "type": f"num(>{med:.2f})",
            "diff1": diff1,
            "diff2": diff2,
            "avg_diff": avg_diff,
            "wr_diff1": 0.0,
            "wr_diff2": 0.0,
            "n_pos": (df_v[col] > med).sum(),
            "n_neg": (df_v[col] <= med).sum(),
            "consistent": consistent,
        })

df_res = pd.DataFrame(audit_results).sort_values("avg_diff", ascending=False)

print("\n【★ 双期同向真因子（Consistent True Factors）】:")
true_factors = df_res[df_res["consistent"] & (df_res["avg_diff"].abs() >= 1.0)]
for r in true_factors.itertuples():
    sign = "+" if r.avg_diff > 0 else "-"
    print(f"  {r.factor:<28} | 22-24: {r.diff1:+6.2f}% | 25-26: {r.diff2:+6.2f}% | 均值: {r.avg_diff:+6.2f}% | 样本: pos={r.n_pos}, neg={r.n_neg}")

print("\n【⛔ 反向/无效噪音因子（Inconsistent Noise Factors）】:")
noise_factors = df_res[~df_res["consistent"]]
for r in noise_factors.itertuples():
    print(f"  {r.factor:<28} | 22-24: {r.diff1:+6.2f}% | 25-26: {r.diff2:+6.2f}% | 均值: {r.avg_diff:+6.2f}%")
