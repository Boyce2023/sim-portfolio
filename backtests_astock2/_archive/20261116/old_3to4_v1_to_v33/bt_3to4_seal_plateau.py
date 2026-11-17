#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""首封时间子因子权重平原与早晚拆分"""
import numpy as np
from bt_3to4_split_integrate import mask_A, sc_A, fst, plateau, split

for a, b in ((2, 2), (3, 3), (4, 4), (3, 0), (0, 3), (5, 3)):
    f = np.where(fst <= 935, -a, np.where(fst.between(936, 1030), b, 0))
    plateau(f"S 秒封扣{a} 10点半前换手封加{b}", mask_A, sc_A + f)
    split(f"S {a}/{b}", mask_A, sc_A + f)
