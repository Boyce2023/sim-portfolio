#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import numpy as np
from verify_v33_calendar_upgrade import df, skel_v32, pts_v32, p_v32

sub = df[skel_v32 & df["ret"].notna()].copy()
m = sub["csi_5d_prev"] > 0.025
for nm, s in [("全五年", sub), ("2022至2023", sub[sub.buy_date < "2024"]), ("2024至2026", sub[sub.buy_date >= "2024"])]:
    a, b = s[m.loc[s.index]], s[~m.loc[s.index]]
    print(f"{nm}: 大涨组n={len(a)} WR={(a.ret>0).mean()*100:.1f}% 均={a.ret.mean()*100:+.2f}% | 其余n={len(b)} 均={b.ret.mean()*100:+.2f}% | 差={(a.ret.mean()-b.ret.mean())*100:+.2f}%")
loyo = 0
for y in range(2022, 2027):
    s = sub[sub.yr != y]; mm = s["csi_5d_prev"] > 0.025
    loyo += int(s[mm].ret.mean() > s[~mm].ret.mean())
print("LOYO同向:", loyo, "/5")
base = pts_v32 + np.where(df["is_post_holiday_or_mon"], 2, 0) + np.where(df["mon"].isin([1, 5]), -4, 0)
new = base + np.where(df["csi_5d_prev"] > 0.025, 3, 0)
idx = np.where(skel_v32 & (base < 90) & (new >= 90))[0]
for i in idx:
    r = df.iloc[i]; rec = p_v32[i]
    print("新放行:", r.buy_date, str(r.code).zfill(6), r["name"], int(base[i]), "->", int(new[i]), f"csi5={r.csi_5d_prev*100:+.2f}%", f"ret={rec['net_ret']*100:+.2f}%" if rec else "")
