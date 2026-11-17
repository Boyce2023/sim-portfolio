# -*- coding: utf-8 -*-
"""综合分引擎 v1.1 — 判断层(agent 50分) + 机械层(主脑自算 50分) = 0-100
⛔权重固定在本文件, 不由agent决定, 保证可复现+跨日可比。
⛔v1.1修正: 估值改用PEG(D8宪法: PEG唯一, Fwd PE禁止单独使用)。
   v1.0用纯Fwd PE的后果: AEM(FwdPE 17.3但PEG 2.54)拿8/10排第2, 正是当天按PEG筛掉的那只。
⛔v1.1修正: 供给侧权重2.2→2.5(供给侧优先是本框架第一权重; v1.0下TGT供给仅1分却靠机械层排#19)。"""
import json, os, statistics as st
D=os.path.dirname(os.path.abspath(__file__))
SPY30, SPY5 = 3.73, -1.37

def struct_score(x):
    # ⛔2026-08-27 Buwen定: 美股用基本面不用趋势确认。原版给"突破25日高"8分,
    #   直接后果是8/24一天买入五只30日已涨22%-41%的票。已删除该项。
    #   价格结构只保留"距高"作为**贵不贵的代理**(越接近高点=越贵=扣分, 与原版方向相反),
    #   且总分从20压到10。价格只调节sizing, 不决定买不买。
    d3=x['dh3']
    p = 0 if d3>=-2 else (2 if d3>=-8 else (5 if d3>=-15 else 7))   # 越跌越便宜, 给分越高
    d52=x['dh52']
    p += 0 if d52>=-5 else (1 if d52>=-15 else 3)
    return p

def rs_score(x):
    # ⛔2026-08-27 删除。相对强弱是纯动量信号, 属"趋势确认"类, 美股禁用。
    #   原版20分, 现归零, 分数全部让给判断层(供给侧/现金转化/催化剂/熊方)。
    return 0

def val_score(x,a):
    # 估值10分不变(PEG口径), 但机械层总分从50压到20后, 估值在机械层内占比升至50%
    pe=x.get('fwd_pe'); g=x.get('impl_g')
    if pe and pe>0 and g and g>0:
        peg=pe/g
        base = 10 if peg<0.5 else (8 if peg<1.0 else (5 if peg<1.5 else (2 if peg<2.5 else 0)))
    elif pe and pe>0:
        base = 6 if pe<15 else (4 if pe<25 else (2 if pe<40 else 0))
    else: base=2
    f=(a or {}).get('valuation_flag','')
    if f=='distorted': base*=0.5
    elif f=='unusable': base*=0.3
    return round(base,1)

def judge_score(a, fcf_conv=None):
    if not a: return None
    # ⛔2026-08-27: agent给的cash_conversion是它自己搜出来的判断, 现在用实测
    #   经营现金流/净利做交叉校验。实测<0.8 = 利润没转成现金, 把agent的分压到不超过5;
    #   实测>1.2 = 现金质量好, agent若给低分则抬到不低于6。只在两者背离时干预。
    c=a.get('cash_conversion',0)
    if fcf_conv is not None and -10 < fcf_conv < 20:
        if fcf_conv < 0.8 and c > 5: c = 5
        elif fcf_conv > 1.2 and c < 6: c = 6
        a=dict(a); a['cash_conversion']=c
    # ⛔2026-08-27 重配权重: 判断层 50->80分(机械层从50压到20)。
    #   供给侧4.0 + 现金转化2.5 + 催化1.0 + (10-熊方)0.5 = 40+25+10+5 = 80
    #   现金转化从1.3提到2.5: 这是我8/14定的"唯一有效因子"(backlog是原料不是产成品),
    #   却一直只占13分, 而纯动量占20分。
    return round(a.get('supply_constraint',0)*4.0 + a.get('cash_conversion',0)*2.5
                 + a.get('catalyst',0)*1.0 + (10-a.get('bear_severity',10))*0.5, 1)

def build():
    A=json.load(open(os.path.join(D,'agent_scores.json')))
    M={x['t']:x for x in json.load(open(os.path.join(D,'mech_input.json')))}
    rows=[]; miss=[]; blocked=[]
    for t,x in M.items():
        a=A.get(t); j=judge_score(a, x.get('fcf_conv'))
        if j is None: miss.append(t); continue
        # ⛔2026-08-27 两道硬门(不是打分项, 是准入条件)。缘起: 新口径首次运行,
        #   前六里AVGO(PEG 0.08)/TSM/KLAC三只半导体全部靠前瞻EPS大跳升制造的"便宜":
        #   AVGO TTM_EPS 5.97→Fwd 19.49(+226%)=低基数失真, 而agent标的是clean;
        #   TSM FCF/净利0.58、KLAC 0.78, 都低于1.0——那是我8/14定的"唯一有效因子"却只是打分项。
        #   门一: 前瞻EPS/TTM_EPS > 1.8 → 估值口径不可用, 出候选池。
        #   门二: FCF/净利 < 1.0 → 出候选池, 无论其他分多高。
        te, fe = x.get('ttm_eps'), x.get('fwd_eps')
        if te and fe and te>0 and (fe/te) > 1.8:
            blocked.append((t,f"低基数失真 Fwd/TTM={fe/te:.2f}")); x['gate_fail']=f"低基数失真({fe/te:.2f}x)"
        # ⛔2026-08-27 撤销"FCF/净利<1.0"这道门。实测发现它是设计错误不是数据错误:
        #   RGLD经营现金流7.05亿但资本开支11.65亿→FCF为负, 因为特许权公司的"资本开支"就是
        #   买特许权本身(商业模式), 不是买厂房; LLY资本开支108亿是在建GLP-1产能=增长投资。
        #   这道门系统性歧视"正在花钱扩产的公司", 而扩产恰恰是供给侧约束兑现的方式——
        #   我用一道门把自己的核心逻辑筛掉了。改用经营现金流/净利(去掉capex)作打分项, 见下。
        s_st,s_rs,s_v = struct_score(x), rs_score(x), val_score(x,a)
        pe,g = x.get('fwd_pe'), x.get('impl_g')
        rows.append(dict(t=t,total=round(j+s_st+s_rs+s_v,1),judge=j,struct=s_st,rs=s_rs,val=s_v,
            supply=a.get('supply_constraint'),cash=a.get('cash_conversion'),
            cat=a.get('catalyst'),bear=a.get('bear_severity'),
            vflag=a.get('valuation_flag'),conf=a.get('confidence'),
            held=x['held'],weight=x.get('weight'),unreal=x.get('unreal'),
            name=x.get('name'),industry=x.get('industry'),mc=x.get('mc'),
            px=x['px'],d30=x['d30'],d5=x['d5'],ytd=x.get('ytd'),
            dh3=x['dh3'],dh52=x['dh52'],brk=x['brk'],h25=x.get('h25'),
            fwd_pe=pe,peg=(round(pe/g,2) if (pe and g and g>0) else None),
            gate_fail=x.get('gate_fail'), fcf_conv=x.get('fcf_conv'),
            ttm_eps=x.get('ttm_eps'), fwd_eps=x.get('fwd_eps'),
            supply_reason=a.get('supply_reason',''),bear_reason=a.get('bear_reason',''),
            cash_reason=a.get('cash_reason',''),catalyst_detail=a.get('catalyst_detail','')))
    # ⛔2026-08-26新增: 判断层与机械层各自独立排名。
    #   缘起: 8/25→8/26 LEU综合分排名从#90跳到#18(一天72名), 判断层30.5分一个数没变,
    #   全部由机械层(brk阶跃+8分/dh3跨档+3至5分)驱动。全样本一天排名中位变动9名、
    #   最大92名、变动>50名的15只。价格给的分和基本面给的分必须能分开看,
    #   否则一次缩量反弹就能把最差持仓抬进前20。
    #   规则: 调仓要求"综合分排名"与"判断层排名"同向支持; 只有综合分动=价格给的, 不作为买入理由。
    jr={r['t']:i+1 for i,r in enumerate(sorted(rows,key=lambda r:-r['judge']))}
    mr={r['t']:i+1 for i,r in enumerate(sorted(rows,key=lambda r:-(r['struct']+r['rs']+r['val'])))}
    for r in rows:
        r['judge_rank']=jr[r['t']]
        r['mech_rank']=mr[r['t']]
        r['mech']=round(r['struct']+r['rs']+r['val'],1)
        r['divergence']=r['mech_rank']-r['judge_rank']   # 正=价格比基本面好(小心), 负=基本面比价格好(可能是机会)
    rows.sort(key=lambda r:-r['total'])
    json.dump(rows,open(os.path.join(D,'composite.json'),'w'),ensure_ascii=False,indent=1)
    print(f"⛔硬门拦下 {len({b[0] for b in blocked})} 只: "+", ".join(f"{t}({r})" for t,r in blocked[:12]))
    return rows,miss

if __name__=='__main__':
    rows,miss=build()
    print(f"综合分完成 {len(rows)} 只 | 缺 {len(miss)}: {','.join(miss[:20])}")
