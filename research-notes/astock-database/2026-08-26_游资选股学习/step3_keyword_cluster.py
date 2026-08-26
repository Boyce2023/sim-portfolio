import pandas as pd

OUT = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26_游资选股学习/raw'
sub = pd.read_csv(f'{OUT}/mar_apr_2025_zhangting_full.csv')
sub['name'] = sub['name'].astype(str)

# keyword buckets built from eyeballing the top-day lists (agri, robot-components, retail/SOE-chain, defense, chip)
KW = {
    '农业/种业/养殖/食品(粮食安全)': ['种业', '农', '牧业', '养殖', '生物', '食品', '乳业', '粮', '果蔬', '猪', '禽', '饲料'],
    '机器人/精密传动(轴承丝杠减速器)': ['轴承', '传动', '减速', '丝杠', '驱动', '精机', '精密', '智能装备'],
    '零售/百货/商业连锁(内需)': ['商业', '百货', '连锁', '集团', '商城', '超市', '王府井'],
    '军工/航天/装备': ['航天', '航空', '军工', '兵器', '装备', '重工', '船', '防务'],
    '半导体/电子/芯片': ['半导体', '电子', '芯片', '微电子', '科技'],
    '港口/航运/物流': ['港', '航运', '物流', '海运'],
    '房地产/建筑': ['地产', '建筑', '建设', '城建', '城'],
}

def classify(name):
    hits = []
    for cat, kws in KW.items():
        if any(k in name for k in kws):
            hits.append(cat)
    return hits[0] if hits else '其他/未归类'

sub['cluster'] = sub['name'].apply(classify)

print("=== whole period (Mar-Apr 2025) cluster distribution, n=%d ===" % len(sub))
print(sub['cluster'].value_counts())

TOP_DAYS = ['2025-04-08', '2025-04-09', '2025-04-10', '2025-04-14',
            '2025-04-21', '2025-03-06', '2025-03-14', '2025-03-26']
for dt in TOP_DAYS:
    day = sub[sub['date'] == dt]
    print(f"\n--- {dt} n={len(day)} ---")
    print(day['cluster'].value_counts())
