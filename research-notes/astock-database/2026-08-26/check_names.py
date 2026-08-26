import akshare as ak
df = ak.stock_board_industry_name_em()
targets = ['半导体','电子','计算机','通信','软件开发','消费电子','元件','光学光电子','IT服务','互联网','软件','元器件','光电子']
for t in targets:
    matches = df[df['板块名称'].str.contains(t, na=False)]
    if len(matches):
        print(t, '->', matches[['板块名称','板块代码']].values.tolist())
