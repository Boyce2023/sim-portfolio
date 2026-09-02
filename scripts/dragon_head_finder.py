#!/usr/bin/env python3
"""龙头/游资龙识别 v0.1 + v0.2 (2026-09-02, Buwen: "选龙头的能力增强一些")
用法(v0.1 实时): python3 scripts/dragon_head_finder.py --codes 600110,301511,... --beta 601899 [--days 45]
用法(v0.2 历史波段回测/离线): python3 scripts/dragon_head_finder.py --wave-mode --db <univ2025.db> --limitups <limitups_full2025.json> --indmap <ind_map.json> [--min-members 3] [--lookback 10]

v0.1思路: 龙头=题材波里"资金最先认、最敢打、最抗跌"的那只, 与beta龙头(紫金这种)是两回事。
六维打分(各0-100, 加权):
  ①先手: 波段内首个涨停日越早分越高(谁先板谁是龙)         w=0.25
  ②高度: 波段内涨停次数+最大连板                               w=0.20
  ③资金: 换手率/量比(游资票换手常>5%, 龙头放量不砸)             w=0.15
  ④抗跌: 距波段高点回撤越小越高(龙头回撤最浅)                  w=0.15
  ⑤alpha: 20日超额收益 vs beta代理(剔除板块beta后的独立涨幅)   w=0.15
  ⑥盘子: 流通市值30-300亿最易被游资做龙, 超大/超小减分         w=0.10
输出: 排名 + alpha/beta分离标签(纯alpha=beta不动它动; 纯beta=跟板块). 数据: 腾讯K线+astock_data_layer实时。

v0.2升级(2026-09-02, 已知缺陷修复: "先手"分v0.1用45日绝对窗口非题材波起点, 导致无关早期涨停股排前):
  - 题材波起点检测(detect_waves): 用行业(ind_map.json)当日涨停家数>=阈值(默认3)且为近10个交易日内首次达到 = T0
  - 波段成员: T0-2到T0(交易日)区间内该行业发生涨停的全部代码
  - T+1识别(score_wave_members): 只用T0+1及之前数据(PIT), 先手改为波内涨停先后顺序(不再是45日绝对窗口)
  - 盘子/资金/alpha改用本地sqlite日线(k表)+turn字段反推流通市值, 不再依赖实时行情接口(可离线回测)
⛔A股禁yfinance。仅识别, 不构成建仓理由(建仓仍走SABCT A-门槛)。
"""
import sys,json,argparse,urllib.request,sqlite3
sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts')

# ============================== v0.1 (实时, 保留不动) ==============================
from astock_data_layer import get_batch_prices
def kl(code,n):
    p=('sh' if code[0]=='6' else 'bj' if code[0] in '48' else 'sz')+code
    u=f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={p},day,,,{n},qfq'
    d=json.load(urllib.request.urlopen(u,timeout=8))['data'][p]; k=d.get('qfqday') or d.get('day')
    return [(r[0],float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[5])) for r in k]
def is_zt(prev,close,code):
    lim=0.199 if code.startswith(('30','68')) else 0.099
    return prev>0 and close>=round(prev*(1+lim),2)-0.005
def score(codes,beta,days):
    live=get_batch_prices(codes+[beta]); out=[]
    kb=kl(beta,days); cb=[r[2] for r in kb]; beta20=cb[-1]/cb[-21]-1 if len(cb)>21 else 0
    for c in codes:
        try: k=kl(c,days)
        except Exception: continue
        cl=[r[2] for r in k];
        if len(cl)<22: continue
        zt_days=[i for i in range(1,len(k)) if is_zt(k[i-1][2],k[i][2],c)]
        first=zt_days[0] if zt_days else None
        # 最大连板
        mx=cur=0
        for i in range(1,len(k)):
            cur=cur+1 if i in zt_days else 0; mx=max(mx,cur)
        q=live.get(c,{}); px=q.get('price') or cl[-1]; cap=q.get('circulating_cap') or q.get('market_cap') or 0
        turn=q.get('turnover_rate') or 0; v20=sum(r[5] for r in k[-21:-1])/20; vr=k[-1][5]/v20 if v20 else 0
        hi=max(cl); dd=px/hi-1; g20=px/cl[-21]-1; alpha=g20-beta20
        s1=0 if first is None else max(0,100-(len(k)-first)*0)  # 先手: 用相对顺序在下面统一算
        s2=min(100,len(zt_days)*20+mx*20)
        s3=min(100,turn*8+vr*15)
        s4=max(0,100+dd*250)          # 回撤-40%→0分
        s5=max(0,min(100,50+alpha*200))
        s6=100 if 30<=cap<=300 else (60 if cap<30 else max(0,100-(cap-300)/20))
        out.append(dict(code=c,name=q.get('name',''),px=px,cap=cap,turn=turn,vr=vr,zt=len(zt_days),maxlb=mx,first=first,dd=dd,g20=g20,alpha=alpha,s2=s2,s3=s3,s4=s4,s5=s5,s6=s6))
    # 先手分: 按首板日先后排序
    firsts=sorted([o for o in out if o['first'] is not None],key=lambda o:o['first'])
    for rank,o in enumerate(firsts): o['s1']=max(0,100-rank*25)
    for o in out: o.setdefault('s1',0); o['total']=0.25*o['s1']+0.20*o['s2']+0.15*o['s3']+0.15*o['s4']+0.15*o['s5']+0.10*o['s6']
    for o in out:
        o['tag']=('纯alpha' if o['alpha']>0.15 and abs(beta20)<0.05 else '跟beta' if abs(o['alpha'])<0.05 else 'alpha+beta' if o['alpha']>0 else '弱于beta')
    return sorted(out,key=lambda o:-o['total']),beta20

# ============================== v0.2 (历史波段回测/离线, PIT-safe) ==============================
import pandas as pd

def load_ind_map(path):
    """code(不带前缀,如'600000') -> 行业字符串(如'J66货币金融服务')"""
    return json.load(open(path))

def load_limitups(path):
    """返回list of dict, 剔除ST"""
    d = json.load(open(path))
    return [r for r in d if not r.get('isST')]

def load_k(db_path):
    """返回宽表: close/volume/turn 三个 DataFrame(index=code含前缀, columns=date字符串排序), 以及trading_days列表"""
    con = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT code,date,close,volume,turn,isST FROM k WHERE isST=0", con)
    con.close()
    trading_days = sorted(df['date'].unique())
    close = df.pivot(index='code', columns='date', values='close').reindex(columns=trading_days)
    volume = df.pivot(index='code', columns='date', values='volume').reindex(columns=trading_days)
    turn = df.pivot(index='code', columns='date', values='turn').reindex(columns=trading_days)
    return close, volume, turn, trading_days

def bare(code):
    return code.split('.')[-1] if '.' in code else code

def detect_waves(limitups, ind_map, trading_days, min_members=3, lookback=10):
    """题材波起点检测: 某行业当日涨停家数>=min_members 且为近lookback个交易日内首次达到 -> T0
    返回 list of dict: {industry, t0, t0_idx, member_codes(T0-2..T0窗口涨停过的代码,去重), day_counts}
    """
    di = {d: i for i, d in enumerate(trading_days)}
    # per industry per date -> set of codes that limit-up that day
    ind_day_codes = {}
    for r in limitups:
        c = r['code']; ind = ind_map.get(bare(c))
        if ind is None or r['date'] not in di:
            continue
        ind_day_codes.setdefault(ind, {}).setdefault(r['date'], set()).add(c)

    waves = []
    for ind, day_codes in ind_day_codes.items():
        # big days: count>=min_members, sorted by trading-day index
        big_days = sorted([(di[d], d) for d, codes in day_codes.items() if len(codes) >= min_members])
        last_t0_idx = None
        for idx, d in big_days:
            if last_t0_idx is not None and idx - last_t0_idx <= lookback:
                continue  # 不是"近lookback日内首次达到"
            last_t0_idx = idx
            # members: T0-2..T0 (交易日索引) 区间内该行业发生涨停的全部代码
            win_lo = max(0, idx - 2)
            members = set()
            first_date = {}
            for wd in trading_days[win_lo: idx + 1]:
                for c in day_codes.get(wd, ()):  # 只在有涨停的日期上有记录
                    members.add(c)
                    if c not in first_date:
                        first_date[c] = wd
            # 需要覆盖不止当天：把窗口内所有该行业当日涨停(不论是否>=min_members)也纳入
            for wd in trading_days[win_lo: idx + 1]:
                pass
            waves.append(dict(industry=ind, t0=d, t0_idx=idx, members=sorted(members),
                               first_date={c: first_date[c] for c in members}))
    waves.sort(key=lambda w: (w['t0'], w['industry']))
    return waves

def _mcap_yi(amount, turn_pct):
    """流通市值(亿元) 反推: turn字段为百分比数值(如0.27表示0.27%)"""
    if not turn_pct or turn_pct <= 0:
        return None
    return amount / (turn_pct / 100.0) / 1e8

def score_wave_members(wave, close, volume, turn, trading_days, limitups_by_code, industry_g20_mean):
    """T0+1时点(PIT: 只用<=T0+1的数据)对波段成员打分, 返回排序后的list of dict"""
    di = {d: i for i, d in enumerate(trading_days)}
    t0_idx = wave['t0_idx']
    score_idx = t0_idx + 1
    if score_idx >= len(trading_days):
        return None  # T0已是最后一个交易日, 无法做T+1识别
    score_date = trading_days[score_idx]
    win_lo = max(0, t0_idx - 2)

    out = []
    for c in wave['members']:
        if c not in close.index:
            continue
        row_c = close.loc[c]
        row_v = volume.loc[c]
        row_t = turn.loc[c]
        px = row_c.iloc[score_idx]
        if pd.isna(px):
            continue
        # ①先手: 波内(T0-2..T0)涨停先后顺序, 越早分越高
        out.append(dict(code=c, first_date=wave['first_date'].get(c), px=px))

    if not out:
        return None
    # 先手打分(按窗口内首次涨停日先后)
    order = sorted(out, key=lambda o: o['first_date'])
    for rank, o in enumerate(order):
        o['s1'] = max(0, 100 - rank * 25)

    for o in out:
        c = o['code']
        row_c = close.loc[c]; row_v = volume.loc[c]; row_t = turn.loc[c]
        # ②高度: 窗口T0-2..score_date内涨停次数+最大连板(来自limitups记录)
        evs = [e for e in limitups_by_code.get(c, []) if win_lo <= di.get(e['date'], -1) <= score_idx]
        zt_n = len(evs); mx_streak = max([e.get('streak', 1) for e in evs], default=0)
        o['zt'] = zt_n; o['maxlb'] = mx_streak
        o['s2'] = min(100, zt_n * 20 + mx_streak * 20)
        # ③资金: score_date换手率 + 量比(vs 前20日均量, 不含score_date)
        turn_v = row_t.iloc[score_idx]
        turn_v = 0 if pd.isna(turn_v) else turn_v
        v_lo = max(0, score_idx - 20)
        v20 = row_v.iloc[v_lo:score_idx].mean()
        vr = (row_v.iloc[score_idx] / v20) if v20 and v20 > 0 else 0
        o['turn'] = turn_v; o['vr'] = vr
        o['s3'] = min(100, turn_v * 8 + vr * 15)
        # ④抗跌: score_date收盘 vs 窗口(win_lo..score_date)最高收盘的回撤
        hi = row_c.iloc[win_lo:score_idx + 1].max()
        dd = (o['px'] / hi - 1) if hi and hi > 0 else 0
        o['dd'] = dd
        o['s4'] = max(0, 100 + dd * 250)
        # ⑤alpha: 20日收益 vs 行业等权20日收益(beta代理), PIT截至score_date
        lb = score_idx - 20
        g20 = (o['px'] / row_c.iloc[lb] - 1) if lb >= 0 and not pd.isna(row_c.iloc[lb]) and row_c.iloc[lb] > 0 else None
        beta20 = industry_g20_mean.get((wave['industry'], score_date))
        if g20 is not None and beta20 is not None:
            alpha = g20 - beta20
        else:
            alpha = None
        o['g20'] = g20; o['beta20'] = beta20; o['alpha'] = alpha
        o['s5'] = 50 if alpha is None else max(0, min(100, 50 + alpha * 200))
        # ⑥盘子: 流通市值反推(亿元), turn需用amount, 这里用volume*px近似amount(无amount宽表, 用turn+价量近似)
        # 用当日turn与流通股本关系: turn(%) = volume/circ_shares*100 -> circ_shares = volume/(turn/100)
        # 市值 = circ_shares * px
        cs = row_v.iloc[score_idx] / (turn_v / 100.0) if turn_v and turn_v > 0 else None
        cap_yi = (cs * o['px'] / 1e8) if cs else None
        o['cap_yi'] = cap_yi
        if cap_yi is None:
            o['s6'] = 50
        else:
            o['s6'] = 100 if 30 <= cap_yi <= 300 else (60 if cap_yi < 30 else max(0, 100 - (cap_yi - 300) / 20))
        o['total'] = 0.25*o['s1'] + 0.20*o['s2'] + 0.15*o['s3'] + 0.15*o['s4'] + 0.15*o['s5'] + 0.10*o['s6']

    return sorted(out, key=lambda o: -o['total']), score_date

def wave_mode(db_path, limitups_path, indmap_path, min_members=3, lookback=10, top=1):
    close, volume, turn, trading_days = load_k(db_path)
    limitups = load_limitups(limitups_path)
    ind_map = load_ind_map(indmap_path)
    waves = detect_waves(limitups, ind_map, trading_days, min_members, lookback)
    print(f"检出 {len(waves)} 个题材波 (min_members={min_members}, lookback={lookback})")
    for w in waves[:top if top else len(waves)]:
        print(f"[{w['industry']}] T0={w['t0']} 成员={len(w['members'])}: {w['members']}")
    return waves

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--codes'); ap.add_argument('--beta'); ap.add_argument('--days', type=int, default=45)
    ap.add_argument('--wave-mode', action='store_true')
    ap.add_argument('--db'); ap.add_argument('--limitups'); ap.add_argument('--indmap')
    ap.add_argument('--min-members', type=int, default=3); ap.add_argument('--lookback', type=int, default=10)
    a = ap.parse_args()
    if a.wave_mode:
        wave_mode(a.db, a.limitups, a.indmap, a.min_members, a.lookback)
    else:
        res, b20 = score(a.codes.split(','), a.beta, a.days)
        print(f'beta代理{a.beta} 20日={b20*100:+.1f}%  (先手0.25/高度0.20/资金0.15/抗跌0.15/alpha0.15/盘子0.10)')
        print(f"{'#':3}{'代码':7}{'名称':6}{'总分':>5}{'先手':>5}{'高度':>5}{'资金':>5}{'抗跌':>5}{'alpha':>6}{'盘子':>5} {'板':>2}{'连':>2}{'换手':>5}{'量比':>5}{'距高':>6}{'超额20d':>8} 标签")
        for i, o in enumerate(res, 1):
            print(f"{i:<3}{o['code']:7}{o['name']:6}{o['total']:>5.0f}{o['s1']:>5.0f}{o['s2']:>5.0f}{o['s3']:>5.0f}{o['s4']:>5.0f}{o['s5']:>6.0f}{o['s6']:>5.0f} {o['zt']:>2}{o['maxlb']:>2}{o['turn']:>5.1f}{o['vr']:>5.1f}{o['dd']*100:>+6.1f}{o['alpha']*100:>+8.1f} {o['tag']}")
