#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import numpy as np
from bt_3to4_split_integrate import mask_A, sc_A, fst, plateau, split
for b in (2, 3, 4, 5):
    f = np.where(fst.between(936, 1030), b, 0)
    plateau(f"G 10点半前换手封加{b}", mask_A, sc_A + f)
f = np.where(fst.between(936, 1000), 3, 0); plateau("G 仅09:36至10:00加3", mask_A, sc_A + f)
f = np.where(fst.between(936, 1100), 3, 0); plateau("G 09:36至11:00加3", mask_A, sc_A + f)
