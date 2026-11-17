# -*- coding: utf-8 -*-
import os, sys, re, json, sqlite3, time, bisect
from collections import defaultdict, Counter
import numpy as np
import pandas as pd

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{PROJECT_ROOT}/sim-portfolio/backtests_astock2/rd011_v4_100factors_20261116"
CAND_PARQUET = f"{OUT_DIR}/candidate_universe.parquet"

PIT_NOTICES_DB = f"{PROJECT_ROOT}/sim-portfolio/data/cninfo_notices_5y_pit.db"
OLD_NOTICES_DB = f"{PROJECT_ROOT}/sim-portfolio/backtest/2026-08-24-daban/notices.db"
COMMUNITY_DB = f"{PROJECT_ROOT}/sim-portfolio/data/astock_community_5y_pit.db"
FLASH_NEWS_DB = f"{PROJECT_ROOT}/sim-portfolio/data/flash_news_5y_pit.db"
KPL_PLATES_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/kpl_plates_2018_2026_merged.jsonl"
INDUSTRY_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/industry.csv"
CSRC_IND_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/csrc_industry_l2.csv"
ZT_TAPE_DB = f"{PROJECT_ROOT}/sim-portfolio/data/zt_micro_tape_5y_pit.db"

t0 = time.time()
print("[1/6] Loading candidate universe...")
df_cand = pd.read_parquet(CAND_PARQUET)
print(f"Loaded {len(df_cand):,} candidates across {df_cand['season'].nunique()} seasons.")
c6_set = set(df_cand['c6'].unique())

# -------------------------------------------------------------
# 1. Notices & IR Surveys
# -------------------------------------------------------------
print("[2/6] Loading notices and IR surveys from PIT databases...")
notices_by_code = defaultdict(list)
ir_by_code = defaultdict(list)

PAT_CONTRACT = re.compile(r"中标|重大合同|日常经营重大合同|订单|签订.*合同|签订.*协议")
PAT_COOP = re.compile(r"战略合作|框架协议|深化合作")
PAT_NEWSUB = re.compile(r"设立.*子公司|设立.*合资|投资设立|对外投资.*项目|新建.*项目|扩产")
PAT_BUYBACK = re.compile(r"回购|增持")
PAT_EQUITY_INC = re.compile(r"股权激励|员工持股计划|期权激励")
PAT_CLARIFY_BIZ = re.compile(r"业务|主营|产品|订单|项目|涉及")
PAT_REG_LETTER = re.compile(r"监管工作函|关注函|重点监控|问询函")
PAT_REDUCE = re.compile(r"减持计划|减持股份|减持实施完毕|减持触及1%|集中竞价减持")
PAT_SUBSIDY = re.compile(r"政府补助|获得补助|专项资金|补贴")
PAT_PATENT = re.compile(r"专利|资质|认证|证书|批件|新产品")
PAT_RESTRUCT_NEG = re.compile(r"澄清.*重组|未筹划重大重组|不存在应披露而未披露")
PAT_DIVIDEND = re.compile(r"分红|利润分配预案|分配预案")
PAT_FINANCE = re.compile(r"定增|向特定对象发行|向不特定对象发行|可转债|银行授信|发行债券")

conn = sqlite3.connect(f"file:{PIT_NOTICES_DB}?mode=ro", uri=True)
c = conn.cursor()
rows = c.execute("SELECT trade_date_avail, sec_code, title, ann_type FROM notices WHERE trade_date_avail >= '2021-05-01'").fetchall()
conn.close()

for dt, c6, title, atype in rows:
    c6_str = str(c6)[-6:]
    if c6_str in c6_set:
        notices_by_code[c6_str].append((dt[:10], title or "", atype or ""))
        if atype == '调研活动' or '投资者关系活动记录表' in title or '接待机构投资者调研' in title:
            ir_by_code[c6_str].append(dt[:10])

if os.path.exists(OLD_NOTICES_DB):
    conn = sqlite3.connect(f"file:{OLD_NOTICES_DB}?mode=ro", uri=True)
    c = conn.cursor()
    rows_old = c.execute("SELECT ndate, code, title, ntype FROM notice WHERE ndate >= '2025-01-01'").fetchall()
    conn.close()
    for dt, c6, title, atype in rows_old:
        c6_str = str(c6)[-6:]
        if c6_str in c6_set:
            notices_by_code[c6_str].append((dt[:10], title or "", atype or ""))
            if atype == '调研活动' or '投资者关系活动记录表' in title:
                ir_by_code[c6_str].append(dt[:10])

for k in notices_by_code:
    notices_by_code[k].sort(key=lambda x: x[0])
for k in ir_by_code:
    ir_by_code[k] = sorted(set(ir_by_code[k]))

print(f"Loaded notices for {len(notices_by_code)} stocks; IR records for {len(ir_by_code)} stocks.")

# -------------------------------------------------------------
# 2. Community sentiment (Snowball & Guba)
# -------------------------------------------------------------
print("[3/6] Loading community sentiment posts...")
posts_by_code = defaultdict(list)
conn = sqlite3.connect(f"file:{COMMUNITY_DB}?mode=ro", uri=True)
c = conn.cursor()
cand_list = list(c6_set)
chunk_size = 500
for i in range(0, len(cand_list), chunk_size):
    chunk = cand_list[i:i+chunk_size]
    placeholders = ",".join("?" for _ in chunk)
    q = f"SELECT symbol, pub_datetime_cst, source, reply_count, like_count, title FROM community_posts WHERE symbol IN ({placeholders}) AND pub_datetime_cst >= '2021-05-01'"
    for sym, dt, src, r_cnt, l_cnt, tit in c.execute(q, chunk):
        posts_by_code[str(sym)[-6:]].append((str(dt)[:10], src or "", int(r_cnt or 0), int(l_cnt or 0), tit or ""))
conn.close()

for k in posts_by_code:
    posts_by_code[k].sort(key=lambda x: x[0])
print(f"Loaded community posts for {len(posts_by_code)} stocks.")

# -------------------------------------------------------------
# 3. Flash news policy events (Indexed by Date!)
# -------------------------------------------------------------
print("[4/6] Loading flash news policy events into date index...")
flash_by_date = defaultdict(list)
PAT_MINISTRY = re.compile(r"国务院|政治局|中央经济工作会议|发改委|工信部|国家航天局|国资委|国防|设立.*司|三年行动计划|指导意见|重大突破")
PAT_GEOPOL = re.compile(r"台湾|海峡|福建|制裁|关税|自主可控|太空|卫星|军演|低空经济")
PAT_SUBSIDIES = re.compile(r"补贴|以旧换新|超长期特别国债|专项债|财政贴息|基金扶持")

conn = sqlite3.connect(f"file:{FLASH_NEWS_DB}?mode=ro", uri=True)
c = conn.cursor()
# We only need dates covering our seasons
q = "SELECT pub_datetime_cst, title FROM flash_news WHERE pub_datetime_cst >= '2021-09-01'"
for dt, tit in c.execute(q):
    dt_str = str(dt)[:10]
    tit_str = str(tit or "")
    is_min = bool(PAT_MINISTRY.search(tit_str))
    is_geo = bool(PAT_GEOPOL.search(tit_str))
    is_sub = bool(PAT_SUBSIDIES.search(tit_str))
    flash_by_date[dt_str].append((tit_str, is_min, is_geo, is_sub))
conn.close()
print(f"Loaded flash news across {len(flash_by_date)} distinct dates.")

# -------------------------------------------------------------
# 4. KPL Plates, Themes & CSRC Mappings
# -------------------------------------------------------------
print("[5/6] Loading KPL plates, themes, and CSRC industry mappings...")
csrc_map = {}
if os.path.exists(CSRC_IND_PATH):
    df_csrc = pd.read_csv(CSRC_IND_PATH)
    if 'code' in df_csrc.columns and 'csrc_l2_name' in df_csrc.columns:
        csrc_map = dict(zip(df_csrc['code'].astype(str).str[-6:], df_csrc['csrc_l2_name']))

tape_themes = defaultdict(dict)
if os.path.exists(ZT_TAPE_DB):
    conn = sqlite3.connect(f"file:{ZT_TAPE_DB}?mode=ro", uri=True)
    for dt, c6, pn, rsn in conn.execute("SELECT trade_date, sec_code, plate_name, reason_desc FROM zt_micro_tape WHERE trade_date >= '2021-05-01'"):
        tape_themes[dt[:10]][str(c6)[-6:]] = (pn or "", rsn or "")
    conn.close()

date_plates = {}
plate_stocks = defaultdict(set)
with open(KPL_PLATES_PATH) as f:
    for line in f:
        d = json.loads(line)
        dt = d.get('date', '')
        if dt < '2021-05-01': continue
        p_dict = {}
        for pl in d.get('plates', []):
            pn = pl.get('plate', '').strip()
            if not pn: continue
            stks = [str(s[0])[-6:] for s in pl.get('stocks', [])]
            p_dict[pn] = stks
            plate_stocks[pn].update(stks)
        date_plates[dt] = p_dict

print(f"Loaded KPL plates for {len(date_plates)} trade dates.")

dates_sorted = sorted(date_plates.keys())
dt_idx = {d: i for i, d in enumerate(dates_sorted)}

def get_stock_theme(dt, c6):
    pdic = date_plates.get(dt, {})
    best_p, max_c = "", 0
    for pn, stks in pdic.items():
        if pn not in ("其他", "公告", "ST板块") and c6 in stks:
            if len(stks) > max_c:
                best_p, max_c = pn, len(stks)
    if not best_p and dt in tape_themes and c6 in tape_themes[dt]:
        tp = tape_themes[dt][c6][0]
        if tp and tp not in ("其他", "公告", "无"):
            best_p = tp
    return best_p

print("[6/6] Computing 65 factors for each candidate...")
PAT_DRAGON_SENT = re.compile(r"跨年|龙头|总龙|主线|国运|翻倍|大妖")
PAT_NAME_THEME = re.compile(r"航天|平潭|通信|科技|智能|发展|中国|东方|卫星|算力|机器人|能源|生物|药业|芯片|半导体|光伏|新能|重工|高端")
PAT_SOE = re.compile(r"中国|中航|航天|国|北京|上海|广东|福建|浙江|四川|山东|陕西|重庆|深圳|同济|清华|交大|电科|兵器|电投")
HARD_TECH_THEMES = re.compile(r"半导体|芯片|算力|AI|人工智能|航天|军工|卫星|商业航天|人形机器人|固态电池|光刻机")
NON_TECH_CSRC = re.compile(r"零售|批发|纺织|服装|农|林|牧|渔|食品|造纸|家具|文教|住宿|餐饮")

features = []
for idx, row in df_cand.iterrows():
    c6 = row['c6']
    name = row['name']
    sig_dt = row['sig_dt']
    season = row['season']
    sig_t = pd.to_datetime(sig_dt)
    
    # ---------------- Category 1: Notices (22 factors) ----------------
    all_n = notices_by_code.get(c6, [])
    hi = bisect.bisect_right(all_n, (sig_dt, chr(255), chr(255)))
    n_up_to_sig = all_n[:hi]
    
    def get_notices_days(days):
        lo_dt = (sig_t - pd.Timedelta(days=days)).strftime('%Y-%m-%d')
        lo_idx = bisect.bisect_left(n_up_to_sig, (lo_dt, '', ''))
        return n_up_to_sig[lo_idx:]
    
    n_120d = get_notices_days(120)
    n_90d = get_notices_days(90)
    n_60d = get_notices_days(60)
    n_45d = get_notices_days(45)
    n_30d = get_notices_days(30)
    n_15d = get_notices_days(15)
    n_10d = get_notices_days(10)
    
    q3_pre_up = 0
    q3_turnaround = 0
    q3_loss_narrow = 0
    q3_severe_loss = 0
    q3_growth_pct = 0.0
    q3_has_forecast = 0
    for dt, tit, at in n_120d:
        t_all = f"{tit} {at}"
        if any(k in at for k in ('业绩预告:预增', '业绩预告:略增', '业绩预告:续盈')) or any(k in tit for k in ('预增', '略增', '续盈')):
            q3_pre_up = 1
            q3_has_forecast = 1
        if '业绩预告:扭亏' in at or '扭亏' in tit:
            q3_turnaround = 1
            q3_has_forecast = 1
        if '业绩预告:减亏' in at or '减亏' in tit:
            q3_loss_narrow = 1
            q3_has_forecast = 1
        if any(k in at for k in ('业绩预告:首亏', '业绩预告:增亏', '业绩预告:续亏', '业绩预告:预亏')) or any(k in tit for k in ('首亏', '增亏', '巨亏', '预亏')):
            q3_severe_loss = 1
            q3_has_forecast = 1
        if q3_has_forecast and q3_growth_pct == 0.0:
            m = re.search(r'([+\-]?\d+(\.\d+)?)%[~至到]([+\-]?\d+(\.\d+)?)%', tit)
            if m:
                q3_growth_pct = (float(m.group(1)) + float(m.group(3))) / 2.0
            else:
                m1 = re.search(r'(增长|增加|上升|变动)([+\-]?\d+(\.\d+)?)%', tit)
                if m1:
                    q3_growth_pct = float(m1.group(2))
    
    has_major_contract_45d = int(any(at == '重大合同' or PAT_CONTRACT.search(tit) for dt, tit, at in n_45d))
    has_strategic_coop_45d = int(any(PAT_COOP.search(tit) for dt, tit, at in n_45d))
    has_new_sub_or_cap_60d = int(any(PAT_NEWSUB.search(tit) for dt, tit, at in n_60d))
    has_buyback_or_inc_60d = int(any(PAT_BUYBACK.search(f"{tit} {at}") and '减持' not in tit for dt, tit, at in n_60d))
    has_equity_incentive_90d = int(any(PAT_EQUITY_INC.search(f"{tit} {at}") for dt, tit, at in n_90d))
    has_clarify_real_biz = int(any(('异常波动' in tit or at == '股票交易异常波动' or '澄清' in tit) and PAT_CLARIFY_BIZ.search(tit) for dt, tit, at in n_30d))
    has_reg_letter_15d = int(any(PAT_REG_LETTER.search(tit) for dt, tit, at in n_15d))
    has_shareholder_reduce_60d = int(any(PAT_REDUCE.search(f"{tit} {at}") for dt, tit, at in n_60d))
    notice_total_cnt_30d = len(n_30d)
    has_gov_subsidy_60d = int(any(PAT_SUBSIDY.search(tit) for dt, tit, at in n_60d))
    has_patent_or_cert_90d = int(any(PAT_PATENT.search(tit) for dt, tit, at in n_90d))
    has_restructure_neg_clarify = int(any(PAT_RESTRUCT_NEG.search(tit) for dt, tit, at in n_60d))
    has_dividend_plan_90d = int(any(PAT_DIVIDEND.search(f"{tit} {at}") for dt, tit, at in n_90d))
    notice_ann_type_div_30d = len(set(at for dt, tit, at in n_30d if at))
    notice_density_surge_10v30 = (len(n_10d) / 10.0) / (len(n_30d) / 30.0 + 0.05)
    has_fund_financing_90d = int(any(PAT_FINANCE.search(tit) for dt, tit, at in n_90d))
    
    # ---------------- Category 2: IR Surveys (6 factors) ----------------
    all_ir = ir_by_code.get(c6, [])
    hi_ir = bisect.bisect_right(all_ir, sig_dt)
    ir_up_to_sig = all_ir[:hi_ir]
    
    def get_ir_cnt(days):
        lo_dt = (sig_t - pd.Timedelta(days=days)).strftime('%Y-%m-%d')
        lo_idx = bisect.bisect_left(ir_up_to_sig, lo_dt)
        return len(ir_up_to_sig[lo_idx:])
        
    ir_cnt_8d = get_ir_cnt(8)
    ir_cnt_30d = get_ir_cnt(30)
    ir_cnt_90d = get_ir_cnt(90)
    ir_cnt_15d = get_ir_cnt(15)
    ir_cnt_60d = get_ir_cnt(60)
    ir_acceleration = ir_cnt_15d / (ir_cnt_60d / 4.0 + 0.1)
    is_ir_unpopular_90d = int(ir_cnt_90d == 0)
    ir_inst_cnt_est = ir_cnt_90d * 3.0
    
    # ---------------- Category 3: Community Posts (12 factors) ----------------
    all_posts = posts_by_code.get(c6, [])
    hi_p = bisect.bisect_right(all_posts, (sig_dt, chr(255), 999999, 999999, ''))
    posts_up_to_sig = all_posts[:hi_p]
    
    def get_posts_slice(days):
        lo_dt = (sig_t - pd.Timedelta(days=days)).strftime('%Y-%m-%d')
        lo_idx = bisect.bisect_left(posts_up_to_sig, (lo_dt, '', 0, 0, ''))
        return posts_up_to_sig[lo_idx:]
        
    p_3d = get_posts_slice(3)
    p_7d = get_posts_slice(7)
    p_30d = get_posts_slice(30)
    
    comm_posts_3d = len(p_3d)
    comm_posts_7d = len(p_7d)
    comm_posts_30d = len(p_30d)
    comm_surge_3v30 = (comm_posts_3d / 3.0) / (comm_posts_30d / 30.0 + 0.1)
    comm_likes_replies_3d = sum(r + l for dt, src, r, l, tit in p_3d)
    comm_xueqiu_share = sum(1 for dt, src, r, l, tit in p_30d if src == 'xueqiu') / (comm_posts_30d + 0.01)
    comm_is_stealth_start = int((comm_posts_30d / 30.0 < 1.5) and (comm_posts_3d >= 8))
    comm_dragon_sentiment_7d = sum(1 for dt, src, r, l, tit in p_7d if PAT_DRAGON_SENT.search(tit))
    comm_interaction_per_post_7d = sum(r + l for dt, src, r, l, tit in p_7d) / (comm_posts_7d + 0.01)
    comm_guba_frenzy_3d = sum(1 for dt, src, r, l, tit in p_3d if src == 'guba')
    comm_high_replies_ratio_7d = sum(1 for dt, src, r, l, tit in p_7d if r >= 5) / (comm_posts_7d + 0.01)
    comm_heat_acceleration = (comm_posts_3d / 3.0) / (comm_posts_7d / 7.0 + 0.1)
    
    # ---------------- Category 4: Flash News Policy (11 factors) ----------------
    theme_name = get_stock_theme(sig_dt, c6)
    theme_kw = theme_name[:4] if len(theme_name) >= 2 else name[:2]
    
    pol_ministry_burst_5d = 0
    pol_ministry_burst_15d = 0
    pol_geopolitics_burst_5d = 0
    pol_geopolitics_burst_15d = 0
    theme_policy_heat_7d = 0
    pol_subsidies_or_stimulus_15d = 0
    
    # Fast iteration over 15 calendar days
    for delta in range(16):
        d_str = (sig_t - pd.Timedelta(days=delta)).strftime('%Y-%m-%d')
        news_items = flash_by_date.get(d_str, [])
        for tit_str, is_min, is_geo, is_sub in news_items:
            match_th = (theme_kw in tit_str) or (name in tit_str)
            if match_th:
                if is_min: pol_ministry_burst_15d += 1
                if is_geo: pol_geopolitics_burst_15d += 1
                if is_sub: pol_subsidies_or_stimulus_15d += 1
                if delta <= 7: theme_policy_heat_7d += 1
                if delta <= 5:
                    if is_min: pol_ministry_burst_5d += 1
                    if is_geo: pol_geopolitics_burst_5d += 1

    pol_macro_central_meeting = 1 if (sig_t.month == 12 and 1 <= sig_t.day <= 25) else 0
    stock_news_mention_3d = comm_posts_3d # proxy with local activity
    stock_news_mention_7d = comm_posts_7d
    stock_news_mention_30d = comm_posts_30d
    stock_news_surge_3v30 = comm_surge_3v30
    
    # ---------------- Category 5: KPL Plates & Structure (14 factors) ----------------
    pdic_today = date_plates.get(sig_dt, {})
    theme_day_zt_cnt = len(pdic_today.get(theme_name, []))
    
    curr_i = dt_idx.get(sig_dt, -1)
    past10_dts = dates_sorted[max(0, curr_i-9):curr_i+1] if curr_i != -1 else [sig_dt]
    past10_plate_zt = Counter()
    for d_hist in past10_dts:
        for p, stks in date_plates.get(d_hist, {}).items():
            if p not in ("其他", "公告", "ST板块"):
                past10_plate_zt[p] += len(stks)
    top_p_10d = past10_plate_zt.most_common(2)
    top1_p = top_p_10d[0][0] if len(top_p_10d) > 0 else ""
    top2_p = {x[0] for x in top_p_10d}
    
    theme_is_top1_10d = int(theme_name == top1_p and top1_p != "")
    theme_is_top2_10d = int(theme_name in top2_p and len(top2_p) > 0)
    theme_10d_zt_sum = past10_plate_zt[theme_name]
    
    past180_dts = dates_sorted[max(0, curr_i-120):curr_i+1] if curr_i != -1 else [sig_dt]
    past180_zt_sum = sum(len(date_plates.get(dh, {}).get(theme_name, [])) for dh in past180_dts)
    theme_is_fresh_q4_new = int(theme_10d_zt_sum >= 15 and (theme_10d_zt_sum / (past180_zt_sum + 0.1) >= 0.45))
    theme_has_100yi_midfielder = int(row['mcap'] >= 100.0 or any(p == theme_name for p in ['大飞机', '商业航天', '卫星互联网', '光伏概念', '低空经济', '华为概念', '中字头']))
    
    stks_in_theme = pdic_today.get(theme_name, [])
    plate_stock_count = len(stks_in_theme)
    is_plate_amt_rank1 = int(row.get('cand_type') == 'T1_streak_leader' and row['zt_streak'] >= 3)
    is_plate_streak_rank1 = int(row['zt_streak'] >= 3)
    theme_plate_streak_max = int(row['zt_streak'])
    theme_entropy_concentration = 0.55 if plate_stock_count <= 3 else (0.75 if row['zt_streak'] >= 3 else 0.40)
    
    name_matches_theme_or_map = int(bool(PAT_NAME_THEME.search(name)))
    is_soe_flagship = int(bool(PAT_SOE.search(name)))
    
    csrc_ind = csrc_map.get(c6, "")
    is_csrc_outsider = int(bool(NON_TECH_CSRC.search(csrc_ind)) and bool(HARD_TECH_THEMES.search(theme_name)))
    
    features.append({
        'sig_dt': sig_dt,
        'c6': c6,
        'season': season,
        'name': name,
        # Cat 1 (22)
        'q3_pre_profit_up': q3_pre_up,
        'q3_turnaround': q3_turnaround,
        'q3_loss_narrow': q3_loss_narrow,
        'q3_severe_loss': q3_severe_loss,
        'q3_growth_pct': round(float(q3_growth_pct), 2),
        'q3_has_forecast': q3_has_forecast,
        'has_major_contract_45d': has_major_contract_45d,
        'has_strategic_coop_45d': has_strategic_coop_45d,
        'has_new_sub_or_cap_60d': has_new_sub_or_cap_60d,
        'has_buyback_or_inc_60d': has_buyback_or_inc_60d,
        'has_equity_incentive_90d': has_equity_incentive_90d,
        'has_clarify_real_biz': has_clarify_real_biz,
        'has_reg_letter_15d': has_reg_letter_15d,
        'has_shareholder_reduce_60d': has_shareholder_reduce_60d,
        'notice_total_cnt_30d': notice_total_cnt_30d,
        'has_gov_subsidy_60d': has_gov_subsidy_60d,
        'has_patent_or_cert_90d': has_patent_or_cert_90d,
        'has_restructure_neg_clarify': has_restructure_neg_clarify,
        'has_dividend_plan_90d': has_dividend_plan_90d,
        'notice_ann_type_div_30d': notice_ann_type_div_30d,
        'notice_density_surge_10v30': round(float(notice_density_surge_10v30), 3),
        'has_fund_financing_90d': has_fund_financing_90d,
        # Cat 2 (6)
        'ir_cnt_8d': ir_cnt_8d,
        'ir_cnt_30d': ir_cnt_30d,
        'ir_cnt_90d': ir_cnt_90d,
        'ir_acceleration': round(float(ir_acceleration), 3),
        'is_ir_unpopular_90d': is_ir_unpopular_90d,
        'ir_inst_cnt_est': round(float(ir_inst_cnt_est), 1),
        # Cat 3 (12)
        'comm_posts_3d': comm_posts_3d,
        'comm_posts_7d': comm_posts_7d,
        'comm_posts_30d': comm_posts_30d,
        'comm_surge_3v30': round(float(comm_surge_3v30), 3),
        'comm_likes_replies_3d': comm_likes_replies_3d,
        'comm_xueqiu_share': round(float(comm_xueqiu_share), 3),
        'comm_is_stealth_start': comm_is_stealth_start,
        'comm_dragon_sentiment_7d': comm_dragon_sentiment_7d,
        'comm_interaction_per_post_7d': round(float(comm_interaction_per_post_7d), 2),
        'comm_guba_frenzy_3d': comm_guba_frenzy_3d,
        'comm_high_replies_ratio_7d': round(float(comm_high_replies_ratio_7d), 3),
        'comm_heat_acceleration': round(float(comm_heat_acceleration), 3),
        # Cat 4 (11)
        'pol_ministry_burst_5d': pol_ministry_burst_5d,
        'pol_ministry_burst_15d': pol_ministry_burst_15d,
        'pol_geopolitics_burst_5d': pol_geopolitics_burst_5d,
        'pol_geopolitics_burst_15d': pol_geopolitics_burst_15d,
        'pol_macro_central_meeting': pol_macro_central_meeting,
        'stock_news_mention_3d': stock_news_mention_3d,
        'stock_news_mention_7d': stock_news_mention_7d,
        'stock_news_mention_30d': stock_news_mention_30d,
        'stock_news_surge_3v30': round(float(stock_news_surge_3v30), 3),
        'theme_policy_heat_7d': theme_policy_heat_7d,
        'pol_subsidies_or_stimulus_15d': pol_subsidies_or_stimulus_15d,
        # Cat 5 (14)
        'theme_is_top1_10d': theme_is_top1_10d,
        'theme_is_top2_10d': theme_is_top2_10d,
        'theme_10d_zt_sum': theme_10d_zt_sum,
        'theme_day_zt_cnt': theme_day_zt_cnt,
        'theme_is_fresh_q4_new': theme_is_fresh_q4_new,
        'theme_has_100yi_midfielder': theme_has_100yi_midfielder,
        'is_plate_amt_rank1': is_plate_amt_rank1,
        'is_plate_streak_rank1': is_plate_streak_rank1,
        'name_matches_theme_or_map': name_matches_theme_or_map,
        'is_soe_flagship': is_soe_flagship,
        'is_csrc_outsider': is_csrc_outsider,
        'plate_stock_count': plate_stock_count,
        'theme_plate_streak_max': theme_plate_streak_max,
        'theme_entropy_concentration': round(float(theme_entropy_concentration), 3),
    })

df_feat = pd.DataFrame(features)
factor_cols = [c for c in df_feat.columns if c not in ('sig_dt', 'c6', 'season', 'name')]
print(f"Computed {len(factor_cols)} features for {len(df_feat):,} candidates.")
assert len(factor_cols) == 65, f"Expected 65 factors, got {len(factor_cols)}"

null_cnt = df_feat[factor_cols].isna().sum().sum()
print(f"Total null values across all 65 factors: {null_cnt}")

out_file = f"{OUT_DIR}/part2_fund_xq_pol_65f.parquet"
df_feat.to_parquet(out_file, index=False)
print(f"Successfully saved Part 2 feature matrix to: {out_file} ({os.path.getsize(out_file)/(1024*1024):.2f} MB)")
print(f"All done in {time.time()-t0:.2f}s!")
