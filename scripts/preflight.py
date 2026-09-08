#!/opt/homebrew/bin/python3
"""动作前必调用清单 — Buwen 2026-09-08: "学了很多东西, 但是在对应的时候不调用"
⛔病根不是知识不够, 是**取用这一步不存在于流程里**, 全靠"我恰好想起来"。
   今天实证: 锚点写在我自己发的信号里却没在交付前跑 / 学完交易规则还是把撤单当卖出 /
   一整天给别处建门自己路径上一个没有 / 09-04撤回的数字09-08又用。**每次都不是不知道, 是没去取。**
用法: preflight.py deliver|buy|sell|answer [标的]
"""
import sys,os,subprocess,json
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def sh(c): 
    r=subprocess.run(c,shell=True,capture_output=True,text=True,cwd=ROOT); return r.stdout.strip() or r.stderr.strip()

CHAINS={
'deliver':[
 ("① 省略号/截断", "python3 scripts/deliver_check.py <你的文本>", "他要完整就给完整。09-08我给'前8条……后4条'被骂"),
 ("② 已撤回结论回流", "同上, deliver_check 内置撤回门", "09-04撤回的'漏75%'我09-08又当事实用了"),
 ("③ 数字锚点", "有唯一正确答案的量必须对一次", "竞价涨幅必须==开盘涨幅; 我用09:25:03取价而锚点用09:25:06, 两栏自相矛盾"),
 ("④ 别加戏", "他给的条件就是全部条件", "我给'9:24阴量'加了'占比≥60%'把真形态筛掉; 给仲裁加样本门槛; 给B加单笔上限——他都没说过"),
],
'buy':[
 ("① 历史公告回溯", "cd ~/claude-projects/news-dashboard && python3 announce_lookup.py {code} 3", "兴业银锡矿停产一个月我不知道就建仓, 亏19389"),
 ("② 可成交性", "execute_trade Gate -2 自动跑", "封板69分钟后挂涨停价=现实排不进=往流水投毒"),
 ("③ 交易规则硬约束", "astock_rules: 涨跌幅/涨停价三层取整/申报数量(科创板200股)/费用", "买卖双边12.3bp, B策略溢价81bp被吃15%"),
 ("④ 时点", "B的买点是触板那一瞬间; 集合竞价只能限价单; 9:25-9:30交易所不接受申报", "错过就作废不补"),
],
'sell':[
 ("① 先分清是撤单还是平仓", "未成交委托随时可撤(9:20-9:25与14:57-15:00除外), 不走sell接口", "09-08我把撤销无效录入当成卖出, 被T+1挡住还说'撤不掉'"),
 ("② T18 thesis三问", "供给约束/主beta/催化时间线 变了吗", "判断型20日卖对率87% vs 机械型36%"),
 ("③ 卖出理由合法性", "扫描名单变化不构成卖出理由(T14)", "顺络'扫描未重现'卖飞+30%"),
 ("④ 扳机用收盘价", "盘中越线=计数候选不是执行信号, 判断类与风控类一视同仁", "08-28: 金对簇盘中-3.18%越线/收盘-2.82%未越, 差0.18点。⛔不许因为'风险类该更快'对不利方向用盘中数——那是双标, 方向总是支持我此刻想做的事"),
 ("⑤ 费用", "卖出单边8.6bp含印花税, 已自动扣", ""),
],
'answer':[
 ("① 先查再答", "memory/规则/数据源, 不凭印象", "宪法第4条: 事实必须先验证"),
 ("② 数字先跑工具", "价格问题第一个动作是取数, 不是开口", "D10/宪法第5条"),
 ("③ 我说过的话", "查自己历史结论, 别和四天前的自己矛盾", "09-04撤回09-08复用"),
 ("④ 授权", "模拟盘买卖=自主决策+执行+事后报告, 不请示", "已复发4次"),
],
}
def main():
    a=sys.argv[1:] 
    if not a or a[0] not in CHAINS:
        print(__doc__); print("可用:", ' / '.join(CHAINS)); sys.exit(2)
    act=a[0]; code=a[1] if len(a)>1 else None
    print(f"\n{'='*72}\n必调用链 · {act}{f'  [{code}]' if code else ''}\n{'='*72}")
    for i,(name,how,why) in enumerate(CHAINS[act],1):
        print(f"{name}")
        print(f"   做什么: {how.replace('{code}',code or '<code>')}")
        if why: print(f"   为什么: {why}")
    if act=='buy' and code:
        print(f"\n{'─'*72}\n自动执行 ①历史公告回溯:\n")
        print(sh(f"cd ~/claude-projects/news-dashboard && env -u HTTPS_PROXY -u HTTP_PROXY python3 announce_lookup.py {code} 3")[:1800])
    print()
if __name__=='__main__': main()
