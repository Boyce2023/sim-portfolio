#!/usr/bin/env python3
"""龙头/游资龙识别 v0.2 历史验证 (2025全年, 可复跑)
数据: backtest/2026-08-24-daban/{univ2025.db, limitups_full2025.json, ind_map.json} 全部本地, 无联网取价
定义详见 dragon_head_finder.py 顶部注释 + 本目录 REPORT.md
用法: python3 validate.py
输出: result.json (全部数字), 并把摘要打到 stdout
"""
import sys, json, statistics, random
sys.path.insert(0, '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts')
import dragon_head_finder as dh
import pandas as pd

DB = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/univ2025.db'
LIMITUPS = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/limitups_full2025.json'
INDMAP = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/ind_map.json'
OUT = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-09-02-dragon-head/result.json'
HORIZON = 20  # 事后真相窗口(交易日)
random.seed(42)

def build_industry_g20(close, ind_map):
    """行业等权20日收益(beta代理), 返回 dict[industry] -> pandas Series indexed by date"""
    codes = close.index
    ind_series = pd.Series({c: ind_map.get(dh.bare(c)) for c in codes})
    g20 = close.divide(close.shift(20, axis=1)) - 1
    g20 = g20.copy()
    g20['__ind__'] = ind_series
    grp = g20.groupby('__ind__').mean()
    return {ind: grp.loc[ind] for ind in grp.index if ind is not None}

def limitups_index(limitups):
    by_code = {}
    for r in limitups:
        by_code.setdefault(r['code'], []).append(r)
    for c in by_code:
        by_code[c].sort(key=lambda r: r['date'])
    return by_code

def post_truth(wave, close, trading_days, limitups_by_code):
    """事后真相: T0..T0+20(streak窗口) / 从T0基准到T0+20的最高涨幅(gain窗口)
    要求horizon内有完整20个交易日数据, 否则标记incomplete"""
    di = {d: i for i, d in enumerate(trading_days)}
    t0_idx = wave['t0_idx']
    if t0_idx + HORIZON >= len(trading_days):
        return None  # 年末数据不足20个交易日, 跳过
    base_close = close.loc[:, trading_days[t0_idx]]
    window_dates = trading_days[t0_idx+1: t0_idx+HORIZON+1]
    best_gain_code, best_gain = None, -999
    for c in wave['members']:
        if c not in close.index:
            continue
        b = base_close.get(c)
        if b is None or pd.isna(b) or b <= 0:
            continue
        fut = close.loc[c, window_dates]
        if fut.isna().all():
            continue
        g = fut.max() / b - 1
        if g > best_gain:
            best_gain, best_gain_code = g, c
    # 连板最高者: T0..T0+20区间内 limitups 记录里的最大streak
    streak_window = trading_days[t0_idx: t0_idx+HORIZON+1]
    sw_set = set(streak_window)
    best_streak_code, best_streak = None, -1
    for c in wave['members']:
        evs = [e for e in limitups_by_code.get(c, []) if e['date'] in sw_set]
        mx = max([e.get('streak', 1) for e in evs], default=0)
        if mx > best_streak:
            best_streak, best_streak_code = mx, c
    if best_gain_code is None or best_streak_code is None:
        return None
    return dict(gain_leader=best_gain_code, gain_leader_pct=best_gain, streak_leader=best_streak_code, streak_leader_n=best_streak)

def score_with_ablation(members_scored, drop_dim=None):
    """members_scored: list of dict with s1..s6 already computed. 重新按去掉某维后归一化权重排序"""
    W = dict(s1=0.25, s2=0.20, s3=0.15, s4=0.15, s5=0.15, s6=0.10)
    if drop_dim:
        w2 = {k: v for k, v in W.items() if k != drop_dim}
        tot = sum(w2.values())
        w2 = {k: v/tot for k, v in w2.items()}
    else:
        w2 = W
    out = []
    for o in members_scored:
        t = sum(o[k]*w2[k] for k in w2)
        out.append((t, o['code']))
    out.sort(key=lambda x: -x[0])
    return [c for _, c in out]

def baseline_ranks(wave, close, turn, volume, trading_days, cap_by_code):
    """三个naive基线, 均PIT(只用T0+1及之前数据), 返回 dict[name] -> ranked code list"""
    t0_idx = wave['t0_idx']; score_idx = t0_idx + 1
    di = {d: i for i, d in enumerate(trading_days)}
    members = [c for c in wave['members'] if c in close.index]
    # 1) random
    rnd = members[:]
    random.shuffle(rnd)
    # 2) T0当日涨幅最大(T0 close / T0 preclose -1近似用 close[t0]/close[t0-1]-1)
    def t0_gain(c):
        if t0_idx == 0:
            return -999
        a = close.loc[c].iloc[t0_idx]; b = close.loc[c].iloc[t0_idx-1]
        if pd.isna(a) or pd.isna(b) or b <= 0:
            return -999
        return a/b - 1
    by_t0gain = sorted(members, key=lambda c: -t0_gain(c))
    # 3) 流通市值最小(用score_idx的cap)
    def cap(c):
        v = cap_by_code.get(c)
        return v if v is not None else 1e18
    by_smallcap = sorted(members, key=cap)
    return dict(random=rnd, t0gain=by_t0gain, smallcap=by_smallcap)

def hit(rank_list, truth_code, topn):
    return 1 if truth_code in rank_list[:topn] else 0

def main():
    print('加载 k 表(2025全年)...')
    close, volume, turn, trading_days = dh.load_k(DB)
    print(f'交易日 {len(trading_days)} ({trading_days[0]}~{trading_days[-1]}), 股票数 {len(close)}')
    limitups = dh.load_limitups(LIMITUPS)
    ind_map = dh.load_ind_map(INDMAP)
    limitups_by_code = limitups_index(limitups)

    MIN_MEMBERS, LOOKBACK = 3, 10
    waves = dh.detect_waves(limitups, ind_map, trading_days, MIN_MEMBERS, LOOKBACK)
    print(f'题材波(min_members={MIN_MEMBERS}, lookback={LOOKBACK}): {len(waves)}')
    if len(waves) < 5:
        MIN_MEMBERS = 2
        waves = dh.detect_waves(limitups, ind_map, trading_days, MIN_MEMBERS, LOOKBACK)
        print(f'放宽到min_members=2: {len(waves)}')

    print('预计算行业等权20日收益(beta代理)...')
    industry_g20 = build_industry_g20(close, ind_map)

    records = []
    skipped_no_score = 0
    skipped_no_truth = 0
    for w in waves:
        t0_idx = w['t0_idx']
        score_idx = t0_idx + 1
        if score_idx >= len(trading_days):
            skipped_no_score += 1
            continue
        score_date = trading_days[score_idx]
        ind_g20_series = industry_g20.get(w['industry'])
        industry_g20_lookup = {}
        if ind_g20_series is not None and score_date in ind_g20_series.index:
            industry_g20_lookup[(w['industry'], score_date)] = ind_g20_series.get(score_date)
        res = dh.score_wave_members(w, close, volume, turn, trading_days, limitups_by_code, industry_g20_lookup)
        if res is None:
            skipped_no_score += 1
            continue
        ranked, sd = res
        truth = post_truth(w, close, trading_days, limitups_by_code)
        if truth is None:
            skipped_no_truth += 1
            continue
        cap_by_code = {o['code']: o.get('cap_yi') for o in ranked}
        baselines = baseline_ranks(w, close, turn, volume, trading_days, cap_by_code)
        full_rank = [o['code'] for o in ranked]
        caps = [c for c in cap_by_code.values() if c is not None]
        med_cap = statistics.median(caps) if caps else None
        # 波起点当日成员涨停数: 用 wave 检测时的行业当日涨停家数(从limitups直接数)
        t0_members_count = sum(1 for c in w['members'] if any(e['date'] == w['t0'] for e in limitups_by_code.get(c, [])))
        records.append(dict(
            industry=w['industry'], t0=w['t0'], score_date=sd, n_members=len(w['members']),
            t0_members_count=t0_members_count, median_cap_yi=med_cap,
            full_rank=full_rank, members_scored=ranked, baselines=baselines,
            gain_leader=truth['gain_leader'], gain_leader_pct=truth['gain_leader_pct'],
            streak_leader=truth['streak_leader'], streak_leader_n=truth['streak_leader_n'],
        ))

    print(f'可评估波段: {len(records)} (跳过: 无法T+1打分={skipped_no_score}, 无完整20日真相={skipped_no_truth})')

    # ---------- 命中率统计 ----------
    def hitrate_table(records, rank_key_fn, topn):
        vals_gain = [hit(rank_key_fn(r), r['gain_leader'], topn) for r in records]
        vals_streak = [hit(rank_key_fn(r), r['streak_leader'], topn) for r in records]
        return (sum(vals_gain)/len(vals_gain) if vals_gain else None,
                sum(vals_streak)/len(vals_streak) if vals_streak else None)

    methods = {
        'v0.2': lambda r: r['full_rank'],
        'baseline_random': lambda r: r['baselines']['random'],
        'baseline_t0gain': lambda r: r['baselines']['t0gain'],
        'baseline_smallcap': lambda r: r['baselines']['smallcap'],
    }
    hitrates = {}
    for name, fn in methods.items():
        top1_gain, top1_streak = hitrate_table(records, fn, 1)
        top3_gain, top3_streak = hitrate_table(records, fn, 3)
        hitrates[name] = dict(top1_vs_gain=top1_gain, top1_vs_streak=top1_streak,
                               top3_vs_gain=top3_gain, top3_vs_streak=top3_streak)

    # ---------- 分层: 波起点当日成员涨停数 ----------
    def bucket_by_t0count(r):
        n = r['t0_members_count']
        if n <= 4: return '3-4'
        if n <= 9: return '5-9'
        return '10+'
    strata_t0count = {}
    for buck in ['3-4', '5-9', '10+']:
        sub = [r for r in records if bucket_by_t0count(r) == buck]
        if not sub: continue
        t1, t1s = hitrate_table(sub, methods['v0.2'], 1)
        t3, t3s = hitrate_table(sub, methods['v0.2'], 3)
        strata_t0count[buck] = dict(n_waves=len(sub), top1_vs_gain=t1, top1_vs_streak=t1s, top3_vs_gain=t3, top3_vs_streak=t3s)

    # ---------- 分层: 行业市值中位(全部波terciles) ----------
    all_medcaps = sorted([r['median_cap_yi'] for r in records if r['median_cap_yi'] is not None])
    strata_cap = {}
    if all_medcaps:
        n = len(all_medcaps)
        t1_cut = all_medcaps[n//3]; t2_cut = all_medcaps[2*n//3]
        def cap_bucket(r):
            mc = r['median_cap_yi']
            if mc is None: return None
            if mc <= t1_cut: return 'low'
            if mc <= t2_cut: return 'mid'
            return 'high'
        for buck in ['low', 'mid', 'high']:
            sub = [r for r in records if cap_bucket(r) == buck]
            if not sub: continue
            t1, t1s = hitrate_table(sub, methods['v0.2'], 1)
            t3, t3s = hitrate_table(sub, methods['v0.2'], 3)
            strata_cap[buck] = dict(n_waves=len(sub), top1_vs_gain=t1, top1_vs_streak=t1s, top3_vs_gain=t3, top3_vs_streak=t3s, cutoffs=[t1_cut, t2_cut])

    # ---------- 特征重要性(逐维去掉) ----------
    importance = {}
    full_top1_gain = hitrates['v0.2']['top1_vs_gain']
    full_top1_streak = hitrates['v0.2']['top1_vs_streak']
    for dim in ['s1', 's2', 's3', 's4', 's5', 's6']:
        def rank_fn(r, dim=dim):
            return score_with_ablation(r['members_scored'], drop_dim=dim)
        t1g, t1s = hitrate_table(records, rank_fn, 1)
        importance[dim] = dict(top1_vs_gain=t1g, delta_vs_gain=(full_top1_gain - t1g) if (t1g is not None and full_top1_gain is not None) else None,
                                top1_vs_streak=t1s, delta_vs_streak=(full_top1_streak - t1s) if (t1s is not None and full_top1_streak is not None) else None)

    # ---------- "只有alpha没有beta"型 ----------
    alpha_only_members = 0
    total_members_with_data = 0
    alpha_only_is_gain_leader = 0
    total_waves_for_alpha = 0
    for r in records:
        total_waves_for_alpha += 1
        is_alpha_only_flag = False
        for o in r['members_scored']:
            g20 = o.get('g20'); beta20 = o.get('beta20')
            if g20 is None or beta20 is None:
                continue
            total_members_with_data += 1
            if beta20 < 0.05 and g20 > 0.15:
                alpha_only_members += 1
                if o['code'] == r['gain_leader']:
                    is_alpha_only_flag = True
        if is_alpha_only_flag:
            alpha_only_is_gain_leader += 1
    alpha_only_stats = dict(
        alpha_only_share_of_members=(alpha_only_members/total_members_with_data) if total_members_with_data else None,
        alpha_only_share_of_gain_leaders=(alpha_only_is_gain_leader/total_waves_for_alpha) if total_waves_for_alpha else None,
        n_members_with_data=total_members_with_data, n_alpha_only=alpha_only_members, n_waves=total_waves_for_alpha,
        n_gain_leader_is_alpha_only=alpha_only_is_gain_leader,
    )

    result = dict(
        params=dict(min_members=MIN_MEMBERS, lookback=LOOKBACK, horizon=HORIZON),
        n_waves_detected=len(waves), n_waves_evaluated=len(records),
        skipped_no_score=skipped_no_score, skipped_no_truth=skipped_no_truth,
        hitrates=hitrates, strata_t0count=strata_t0count, strata_cap=strata_cap,
        feature_importance=importance, alpha_only_stats=alpha_only_stats,
        waves_sample=[dict(industry=r['industry'], t0=r['t0'], n_members=r['n_members'],
                            top1=r['full_rank'][0] if r['full_rank'] else None,
                            gain_leader=r['gain_leader'], gain_leader_pct=r['gain_leader_pct'],
                            streak_leader=r['streak_leader']) for r in records],
    )
    with open(OUT, 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f'写入 {OUT}')
    print(json.dumps({k: v for k, v in result.items() if k != 'waves_sample'}, ensure_ascii=False, indent=2, default=str))

if __name__ == '__main__':
    main()
