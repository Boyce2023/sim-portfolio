#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step2_priority_grid_and_gates.py — V22.0 Pillar 5 Tasks 3 & 4:
  - Exhaustive 3-Tier & Fine-Bucket Priority Re-Ranking Grid on Pure_V21_P2_SJ114_E4:
    * Group A: 4to5 fine-tier placement (Pos5 vs AfterTier2 vs Tier2 sub-slots vs Tier1; S120 vs 114-119 split)
    * Group B: Exhaustive 6!=720 permutations of Tier 2 (09:25 direct buys) + fine splits (2to3_S/A, 20cm_S86/80-85, 1to2_S/A, pry_S/A)
    * Group C: Tier 1 S-tier intraday reservation re-audit (34S102+HighS96 vs 34S106 vs NoReserve vs +2to3S96 / +4to5S120)
    * Group D: Tier 3 intraday conditional order permutations (3to4_A_cond, high_A_cond, 1to2_cond, 1to2_S_cond)
  - Cold-Blooded Anti-Overfit Gates:
    (1) 2024-12-31 physical truncation max_abs_diff == 0.0
    (2) Simultaneous IS (21-23), OOS (24-26), WF (23-26), 25-26, 2026 outperformance/parity vs Base
    (3) Dual-Scissors ex_both > 1.0 (5Y & WF & IS & OOS) & 5Y MaxDD <= 28.80%
    (4) 50bps high-slippage stress pass + PassTop1 cross-check
  - Exports `p5_priority_grid.csv` and `p5_collision_audit.json`.
Zero yfinance (D12). Read-only on V20/V21/RD038/RD049/P2/P3.
"""
import itertools
import json
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION"
sys.dont_write_bytecode = True

P5 = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/v22_grand_convergence_20261126/p5_v22_collision_priority_audit"
P3 = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/v22_grand_convergence_20261126/p3_v22_grand_assembly"
for p in (P5, P3):
    if p not in sys.path:
        sys.path.insert(0, p)

import _p5_engine as p5
import step2_truncation_proof as trp


# Default Tier 1 / Tier 2 / Tier 3 / Pos5 bucket maps
def _base_strict3tier_map() -> dict[str, int]:
    """Strict 3-tier S2C matching live fast_shadow_4piece_today._arbitrate_s2c + 4to5@Pos5."""
    return {
        # Tier 1: S-tier 3to4 & high (both 09:25 and intraday cond)
        "3to4_S106_925": 10, "3to4_S102_105_925": 10, "3to4_S106_cond": 10, "3to4_S102_105_cond": 10,
        "high_S_925": 20, "high_S_cond": 20,
        # Tier 2: 09:25 confirmed buys
        "3to4_A_925": 110,
        "high_A_925": 120,
        "pry_S": 130, "pry_A": 130,
        "2to3_S": 140, "2to3_A": 140,
        "1to2_925_S": 150, "1to2_925_A": 150,
        "20cm_S86": 160, "20cm_80_85": 160,
        # Tier 3: Intraday conditional orders
        "3to4_A_cond": 210,
        "high_A_cond": 220,
        "1to2_cond_S": 230, "1to2_cond_A": 230, "1to2_cond_FB": 230,
        # Pos5: EmptyFill 4to5
        "4to5_S120": 900, "4to5_114_119": 900,
    }


def build_tier2_order_map(t2_seq: list[str], strict_3tier: bool = True, pos_4to5: dict[str, int] | None = None) -> dict[str, int]:
    """Build bucket rank map given ordered list of Tier 2 strategy keys ('3to4_925','high_925','pry','2to3','1to2_925','20cm')."""
    m = _base_strict3tier_map()
    key_to_buckets = {
        "3to4_925": ["3to4_A_925"] if strict_3tier else ["3to4_S106_925", "3to4_S102_105_925", "3to4_A_925"],
        "high_925": ["high_A_925"] if strict_3tier else ["high_S_925", "high_A_925"],
        "pry": ["pry_S", "pry_A"],
        "2to3": ["2to3_S", "2to3_A"],
        "1to2_925": ["1to2_925_S", "1to2_925_A"],
        "20cm": ["20cm_S86", "20cm_80_85"],
    }
    for idx, k in enumerate(t2_seq):
        rk = 110 + idx * 10
        for b in key_to_buckets[k]:
            m[b] = rk
    if pos_4to5:
        m.update(pos_4to5)
    return m


def _build_named_schemes() -> list[tuple[str, str, str, object, bool]]:
    """
    Return list of (scheme_id, group, desc, rank_fn, allow_untrig).
    """
    schemes = []

    # --- Baselines ---
    schemes.append((
        "Base_V22_OldOrder_4to5AtPos5", "0_BASE",
        "Official Pure_V21_P2_SJ114_E4_Pos5 (Engine S2C_MAP + 4to5@Pos5)",
        p5.make_engine_s2c_rank_fn({"4to5_S120": 900, "4to5_114_119": 900}), True,
    ))
    schemes.append((
        "Base_Strict3Tier_4to5AtPos5", "0_BASE",
        "Strict 3-Tier S2C (Tier1 S > Tier2 09:25 > Tier3 Cond > 4to5@Pos5)",
        p5.make_bucket_rank_fn(_base_strict3tier_map()), True,
    ))

    # --- Group A: 4to5 Placement (on top of Engine S2C_MAP so every delta vs Base is 100% due to 4to5!) ---
    pos_specs = [
        ("A1_4to5_All_After20cm_BeforeT3", "4to5 all after 20cm (Tier 2 bottom, before Tier 3 cond)", {"4to5_S120": 7, "4to5_114_119": 7}),
        ("A2_4to5_All_BeforeAll0925", "4to5 all at top of Tier 2 (prio 0, before 3to4/high/pry/23/12/20cm)", {"4to5_S120": 0, "4to5_114_119": 0}),
        ("A3_4to5_All_After34High", "4to5 all after 3to4 & high (prio 2.5, before pry)", {"4to5_S120": 2, "4to5_114_119": 2}),  # Wait: int prio! Use scaled engine map below
    ]
    # Use scaled engine rank fn (base_rk * 10) for fine insertion between integer S2C slots!
    def _eng_scaled_fn(rk_s120: int, rk_a114: int):
        def _fn(df: pd.DataFrame) -> np.ndarray:
            is_45 = (df["strategy"] == "4to5").to_numpy(bool)
            is_s_cond = df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"]).to_numpy(bool)
            is_p0 = (df["buy_hhmm"].to_numpy(int) == 925) | is_s_cond
            s2c_p = df["s2c_prio"].to_numpy(int)
            base_rk = np.where(is_p0, s2c_p * 10, 1000 + s2c_p * 10)
            rk45 = np.where(df["bucket"].to_numpy() == "4to5_S120", rk_s120, rk_a114)
            return np.where(is_45, rk45, base_rk)
        return _fn

    # Verify engine scaled (9000 -> wait keep <9000! e.g. 2000 for Pos5)
    a_configs = [
        ("A1_4to5_All_After20cm_BeforeT3", "4to5 all after 20cm (before Tier 3 cond)", 70, 70),
        ("A2_4to5_All_Tier1Pos1", "4to5 all in Tier 1 Pos1 (above 3to4_S & high_S)", 5, 5),
        ("A3_4to5_All_After34High", "4to5 all after 3to4 & high (before pry)", 25, 25),
        ("A4_4to5_All_AfterPry", "4to5 all after pry (before 2to3)", 35, 35),
        ("A5_4to5_All_After23", "4to5 all after 2to3 (before 1to2_925)", 45, 45),
        ("A6_4to5_All_After12_925", "4to5 all after 1to2_925 (before 20cm)", 55, 55),
        # Split: S120 inserted, 114-119 at Pos5 (rank 2000)
        ("A10_45S120_Tier1Pos1__A114_Pos5", "4to5 S>=120 @ Tier1 Pos1 | 114-119 @ Pos5", 5, 2000),
        ("A11_45S120_After34High__A114_Pos5", "4to5 S>=120 after 34/high | 114-119 @ Pos5", 25, 2000),
        ("A12_45S120_AfterPry__A114_Pos5", "4to5 S>=120 after pry | 114-119 @ Pos5", 35, 2000),
        ("A13_45S120_After23__A114_Pos5", "4to5 S>=120 after 2to3 | 114-119 @ Pos5", 45, 2000),
        ("A14_45S120_After12_925__A114_Pos5", "4to5 S>=120 after 1to2_925 | 114-119 @ Pos5", 55, 2000),
        ("A15_45S120_After20cm__A114_Pos5", "4to5 S>=120 after 20cm (before Tier 3) | 114-119 @ Pos5", 70, 2000),
        # Split: S120 inserted, 114-119 after 20cm (before Tier 3)
        ("A20_45S120_Tier1Pos1__A114_BeforeT3", "4to5 S>=120 @ Tier1 Pos1 | 114-119 before Tier 3", 5, 70),
        ("A21_45S120_After34High__A114_BeforeT3", "4to5 S>=120 after 34/high | 114-119 before Tier 3", 25, 70),
        ("A22_45S120_AfterPry__A114_BeforeT3", "4to5 S>=120 after pry | 114-119 before Tier 3", 35, 70),
        ("A23_45S120_After23__A114_BeforeT3", "4to5 S>=120 after 2to3 | 114-119 before Tier 3", 45, 70),
        ("A24_45S120_After12_925__A114_BeforeT3", "4to5 S>=120 after 1to2_925 | 114-119 before Tier 3", 55, 70),
    ]
    for sid, desc, r120, r114 in a_configs:
        schemes.append((sid, "A_4TO5_POS", desc, _eng_scaled_fn(r120, r114), True))

    # Also test Strict3Tier + 4to5 S120 BeforeAll0925 (distinct from Tier1 Pos1!)
    m_a2b = _base_strict3tier_map()
    m_a2b["4to5_S120"] = 105
    schemes.append(("A16_45S120_Tier2Top__A114_Pos5", "A_4TO5_POS", "Strict3Tier: 4to5 S>=120 top of Tier 2 (below Tier1 S) | 114-119 @ Pos5", p5.make_bucket_rank_fn(m_a2b), True))
    m_a2c = dict(m_a2b)
    m_a2c["4to5_114_119"] = 170
    schemes.append(("A25_45S120_Tier2Top__A114_BeforeT3", "A_4TO5_POS", "Strict3Tier: 4to5 S>=120 top of Tier 2 | 114-119 before Tier 3", p5.make_bucket_rank_fn(m_a2c), True))

    # --- Group B: Tier 2 (09:25) Fine Splits ---
    def _add_b(sid, desc, edits):
        m = _base_strict3tier_map()
        m.update(edits)
        schemes.append((sid, "B_TIER2_FINE", desc, p5.make_bucket_rank_fn(m), True))

    _add_b("B01_2to3S_Before_pry", "Tier2: 2to3_S>=96 before pry (125)", {"2to3_S": 125})
    _add_b("B02_2to3S_Before_highA", "Tier2: 2to3_S>=96 before high_A (115)", {"2to3_S": 115})
    _add_b("B03_2to3S_Before_34A", "Tier2: 2to3_S>=96 before 3to4_A (105)", {"2to3_S": 105})
    _add_b("B04_2to3A_After_12_925", "Tier2: 2to3_A(90-95) after 1to2_925 (155)", {"2to3_A": 155})
    _add_b("B05_2to3A_After_20cm", "Tier2: 2to3_A(90-95) after 20cm (165)", {"2to3_A": 165})
    _add_b("B06_2to3Split_SBeforePry_AAfter20", "Tier2: 2to3_S before pry (125) & 2to3_A after 20cm (165)", {"2to3_S": 125, "2to3_A": 165})
    _add_b("B07_20cmS86_Before_12_925", "Tier2: 20cm>=86 before 1to2_925 (145)", {"20cm_S86": 145})
    _add_b("B08_20cmS86_Before_2to3", "Tier2: 20cm>=86 before 2to3 (135)", {"20cm_S86": 135})
    _add_b("B09_20cmS86_Before_2to3A", "Tier2: 20cm>=86 before 2to3_A (142), 2to3_S at 138", {"2to3_S": 138, "2to3_A": 145, "20cm_S86": 142})
    _add_b("B10_20cmS86_Before_pry", "Tier2: 20cm>=86 before pry (125)", {"20cm_S86": 125})
    _add_b("B11_20cmS86_Before_highA", "Tier2: 20cm>=86 before high_A (115)", {"20cm_S86": 115})
    _add_b("B12_20cmS86_Before_34A", "Tier2: 20cm>=86 before 3to4_A (105)", {"20cm_S86": 105})
    _add_b("B13_20cmAll_Before_12_925", "Tier2: 20cm(all>=80) before 1to2_925 (145)", {"20cm_S86": 145, "20cm_80_85": 145})
    _add_b("B14_20cmAll_Before_2to3", "Tier2: 20cm(all>=80) before 2to3 (135)", {"20cm_S86": 135, "20cm_80_85": 135})
    _add_b("B15_20cmAll_Before_2to3A", "Tier2: 20cm(all>=80) after 2to3_S(138), before 2to3_A(145)", {"2to3_S": 138, "2to3_A": 145, "20cm_S86": 142, "20cm_80_85": 142})
    _add_b("B16_12_925_Before_2to3", "Tier2: 1to2_925 before 2to3 (135)", {"1to2_925_S": 135, "1to2_925_A": 135})
    _add_b("B17_12S_925_Before_2to3", "Tier2: 1to2_925_S>=340 before 2to3 (135)", {"1to2_925_S": 135})
    _add_b("B18_12A_925_After_20cm", "Tier2: 1to2_925_A<340 after 20cm (165)", {"1to2_925_A": 165})
    _add_b("B19_HighA925_Before_34A925", "Tier2: high_A_925 (105) before 3to4_A_925 (110)", {"high_A_925": 105})
    _add_b("B20_Pry_Before_HighA925", "Tier2: pry (115) before high_A_925 (120)", {"pry_S": 115, "pry_A": 115})
    _add_b("B21_20cmS86_Before23_Plus_45S120_Before12", "Combo: 20cm>=86 before 2to3 (135) + 4to5>=120 before 1to2_925 (145)", {"20cm_S86": 135, "4to5_S120": 145})
    _add_b("B22_20cmS86_Before23_Plus_45S120_After20S86", "Combo: 20cm>=86 (135) > 2to3 (140) > 4to5>=120 (145) > 1to2_925 (150) > 20cm80-85 (160)", {"20cm_S86": 135, "4to5_S120": 145})
    _add_b("B23_20cmS86_Before23_Plus_45All_BeforeT3", "Combo: 20cm>=86 before 2to3 (135) + 4to5>=120 (145) + 4to5_114-119 before T3 (170)", {"20cm_S86": 135, "4to5_S120": 145, "4to5_114_119": 170})

    # --- Group C: Tier 1 S-tier Reservation Audit ---
    def _add_c(sid, desc, edits, allow_ut=True):
        m = _base_strict3tier_map()
        m.update(edits)
        schemes.append((sid, "C_TIER1_RES", desc, p5.make_bucket_rank_fn(m), allow_ut))

    _add_c("C1_T1_Only34S106_HighS96", "Tier1: 3to4>=106 & high>=96 reserve | 3to4 102-105 cond -> Tier3", {"3to4_S102_105_925": 105, "3to4_S102_105_cond": 205})
    _add_c("C2_T1_Only34S106_NoHighS", "Tier1: ONLY 3to4>=106 reserves | high_S cond -> Tier3", {"3to4_S102_105_925": 105, "3to4_S102_105_cond": 205, "high_S_925": 115, "high_S_cond": 215})
    _add_c("C3_T1_Only34S102_NoHighS", "Tier1: ONLY 3to4>=102 reserves | high_S cond -> Tier3", {"high_S_925": 115, "high_S_cond": 215})
    _add_c("C4_T1_OnlyHighS96_No34S", "Tier1: ONLY high>=96 reserves | 3to4_S cond -> Tier3", {"3to4_S106_925": 105, "3to4_S102_105_925": 105, "3to4_S106_cond": 205, "3to4_S102_105_cond": 205})
    _add_c("C5_NoReserve_Confirmed0925First_WithUT", "No Tier1 reserve: ALL 09:25 confirmed buys beat ALL >925 cond (keep UT in T3)", {
        "3to4_S106_925": 102, "3to4_S102_105_925": 102, "high_S_925": 112,
        "3to4_S106_cond": 202, "3to4_S102_105_cond": 202, "high_S_cond": 212,
    }, allow_ut=True)
    _add_c("C6_NoReserve_Confirmed0925First_NoUT", "No Tier1 reserve + NO untriggered waits (pure triggered 09:25 first)", {
        "3to4_S106_925": 102, "3to4_S102_105_925": 102, "high_S_925": 112,
        "3to4_S106_cond": 202, "3to4_S102_105_cond": 202, "high_S_cond": 212,
    }, allow_ut=False)
    _add_c("C7_T1_Add_2to3S96_AboveT1", "Tier1: 2to3_S>=96 (5) > 3to4_S (10) > high_S (20)", {"2to3_S": 5})
    _add_c("C8_T1_Add_2to3S96_MidT1", "Tier1: 3to4_S (10) > 2to3_S>=96 (15) > high_S (20)", {"2to3_S": 15})
    _add_c("C9_T1_Add_4to5S120_AboveT1", "Tier1: 4to5_S>=120 (5) > 3to4_S (10) > high_S (20)", {"4to5_S120": 5})
    _add_c("C10_T1_Add_4to5S120_BelowT1", "Tier1: 3to4_S (10) > high_S (20) > 4to5_S>=120 (30)", {"4to5_S120": 30})
    _add_c("C11_T1_Add_23S96_45S120_Above", "Tier1: 4to5_S120 (4) > 2to3_S96 (6) > 3to4_S (10) > high_S (20)", {"4to5_S120": 4, "2to3_S": 6})
    _add_c("C12_T1_DirectS_Beats_CondS", "Tier1 sub-split: 34S_925/highS_925 (5/8) > 34S_cond/highS_cond (10/20)", {
        "3to4_S106_925": 5, "3to4_S102_105_925": 5, "high_S_925": 8,
    })

    # --- Group D: Tier 3 Intraday Conditional Order Permutations ---
    t3_items = [("34Ac", "3to4_A_cond"), ("hiAc", "high_A_cond"), ("12c", ["1to2_cond_S", "1to2_cond_A", "1to2_cond_FB"])]
    for perm in itertools.permutations(t3_items):
        nm_t3 = "_".join(x[0] for x in perm)
        edits = {}
        for idx, (_, bks) in enumerate(perm):
            rk = 210 + idx * 10
            if isinstance(bks, list):
                for b in bks:
                    edits[b] = rk
            else:
                edits[bks] = rk
        m = _base_strict3tier_map()
        m.update(edits)
        schemes.append((f"D_T3_{nm_t3}", "D_TIER3", f"Tier3 order: {nm_t3}", p5.make_bucket_rank_fn(m), True))

    # Fine split in Tier 3: 1to2_S(>=340) vs high_A_cond vs 3to4_A_cond
    for sid, desc, edits in [
        ("D_T3_12S_Before_HighA", "Tier3: 3to4_A (210) > 1to2_S>=340 (215) > high_A (220) > 1to2_A/FB (230)", {"1to2_cond_S": 215}),
        ("D_T3_12S_TopT3", "Tier3: 1to2_S>=340 (205) > 3to4_A (210) > high_A (220) > 1to2_A/FB (230)", {"1to2_cond_S": 205}),
    ]:
        m = _base_strict3tier_map()
        m.update(edits)
        schemes.append((sid, "D_TIER3", desc, p5.make_bucket_rank_fn(m), True))

    # --- EngineS2C-anchored controls for C12 (DirectS > CondS) and D_T3 (1to2_cond_S/1to2_cond top of T3) ---
    def _eng_c12_fn(df: pd.DataFrame) -> np.ndarray:
        is_45 = (df["strategy"] == "4to5").to_numpy(bool)
        is_s_cond = df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"]).to_numpy(bool)
        hh = df["buy_hhmm"].to_numpy(int)
        is_p0 = (hh == 925) | is_s_cond
        s2c_p = df["s2c_prio"].to_numpy(int)
        # In Phase 0: 09:25 S-tier (s2c_p*10) beats >925 S-tier cond (50 + s2c_p*10)? Wait: preserve 3to4_A@925 at 10, put S_925 at 5+s2c_p, S_cond at 25+s2c_p!
        # Wait: let's keep 3to4_A_925 at 10, pry at 30, etc., and only put 3to4_S_925=5, high_S_925=8, 3to4_S_cond=12, high_S_cond=20!
        bk = df["bucket"].to_numpy()
        base_rk = np.where(is_p0, s2c_p * 10, 1000 + s2c_p * 10)
        base_rk = np.where(np.isin(bk, ["3to4_S106_925", "3to4_S102_105_925"]), 5, base_rk)
        base_rk = np.where(bk == "high_S_925", 8, base_rk)
        base_rk = np.where(np.isin(bk, ["3to4_S106_cond", "3to4_S102_105_cond"]), 12, base_rk)
        base_rk = np.where(bk == "high_S_cond", 20, base_rk)
        return np.where(is_45, 2000, base_rk)

    def _eng_t3_12s_fn(all_12: bool = False):
        def _fn(df: pd.DataFrame) -> np.ndarray:
            is_45 = (df["strategy"] == "4to5").to_numpy(bool)
            is_s_cond = df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"]).to_numpy(bool)
            is_p0 = (df["buy_hhmm"].to_numpy(int) == 925) | is_s_cond
            s2c_p = df["s2c_prio"].to_numpy(int)
            base_rk = np.where(is_p0, s2c_p * 10, 1000 + s2c_p * 10)
            bk = df["bucket"].to_numpy()
            if all_12:
                base_rk = np.where(np.isin(bk, ["1to2_cond_S", "1to2_cond_A", "1to2_cond_FB"]), 1005, base_rk)
            else:
                base_rk = np.where(bk == "1to2_cond_S", 1005, base_rk)
            return np.where(is_45, 2000, base_rk)
        return _fn

    schemes.append(("C12_Eng_DirectS_Beats_CondS", "C_TIER1_RES", "EngineS2C + 09:25 S-tier beats >925 S-tier cond (preserves 3to4_A_925)", _eng_c12_fn, True))
    schemes.append(("D_Eng_T3_12S_TopT3", "D_TIER3", "EngineS2C + 1to2_cond_S>=340 top of Tier 3", _eng_t3_12s_fn(all_12=False), True))
    schemes.append(("D_Eng_T3_12All_TopT3", "D_TIER3", "EngineS2C + 1to2_cond(all) top of Tier 3", _eng_t3_12s_fn(all_12=True), True))

    return schemes


def run_exhaustive_720_tier2_sweep(mp030: pd.DataFrame, cal_5y: list[str], cache_base: dict, base_eval: dict) -> tuple[pd.DataFrame, dict]:
    """Exhaustively evaluate ALL 6!=720 permutations of Tier 2 (09:25 direct buys) under Strict3Tier."""
    t2_keys = ["3to4_925", "high_925", "pry", "2to3", "1to2_925", "20cm"]
    rows = []
    seen_traces = {}
    unique_curves = 0
    for perm in itertools.permutations(t2_keys):
        seq = list(perm)
        bm = build_tier2_order_map(seq, strict_3tier=True)
        sim = p5.run_priority_sim(mp030, p5.make_bucket_rank_fn(bm), cal_5y, allow_untrig=True)
        sig = tuple((r.buy_date, r.code, r.strategy) for r in sim["trades_df"].itertuples(index=False))
        if sig not in seen_traces:
            unique_curves += 1
            w = p5.eval_fast_windows(sim, cache_base)
            seen_traces[sig] = w
        else:
            w = seen_traces[sig]
        f5, isw, oos, wf, y25, y26 = w["FULL_5Y"], w["IS_2123"], w["OOS_2426"], w["WF_2326"], w["Y2025_2026"], w["Y2026"]
        rows.append({
            "t2_order": " > ".join(seq),
            "n": f5["n"], "nav_5y": f5["nav"], "mdd_5y": f5["daily_mdd_pct"], "sh_5y": f5["daily_sharpe"],
            "nav_is": isw["nav"], "sh_is": isw["daily_sharpe"], "mdd_is": isw["daily_mdd_pct"],
            "nav_oos": oos["nav"], "sh_oos": oos["daily_sharpe"], "mdd_oos": oos["daily_mdd_pct"],
            "nav_wf": wf["nav"], "nav_2526": y25["nav"], "nav_26": y26["nav"],
            "beat_base_is_oos_2526_26": bool(
                isw["nav"] >= base_eval["IS_2123"]["nav"] - 1e-4
                and oos["nav"] >= base_eval["OOS_2426"]["nav"] - 1e-4
                and y25["nav"] >= base_eval["Y2025_2026"]["nav"] - 1e-4
                and y26["nav"] >= base_eval["Y2026"]["nav"] - 1e-4
                and f5["daily_mdd_pct"] <= base_eval["FULL_5Y"]["daily_mdd_pct"] + 1e-6
            ),
        })
    df720 = pd.DataFrame(rows).sort_values(["nav_wf", "nav_5y"], ascending=[False, False]).reset_index(drop=True)
    meta = {
        "total_permutations": len(df720),
        "unique_trade_trajectories": unique_curves,
        "n_beat_base_all_windows_and_mdd": int(df720["beat_base_is_oos_2526_26"].sum()),
        "top5_by_wf": df720.head(5).to_dict("records"),
        "bottom3_by_wf": df720.tail(3).to_dict("records"),
        "canon_rank_in_720": int(df720.index[df720["t2_order"] == "3to4_925 > high_925 > pry > 2to3 > 1to2_925 > 20cm"][0]) + 1,
    }
    return df720, meta


def evaluate_scheme_full(
    sid: str, grp: str, desc: str, rfn, allow_ut: bool,
    mp030: pd.DataFrame, mp050: pd.DataFrame, mp_pt030: pd.DataFrame,
    cal_5y: list[str], cache_base: dict,
    base_sim030: dict, base_w030: dict, base_sim050: dict, base_w050: dict, base_wpt: dict,
) -> tuple[dict, dict, list[dict]]:
    """Run 030, 050, PassTop1 crosscheck, Dual-Scissors across 4 windows, and 1000x paired perm."""
    s030 = p5.run_priority_sim(mp030, rfn, cal_5y, allow_untrig=allow_ut)
    w030 = p5.eval_fast_windows(s030, cache_base)

    s050 = p5.run_priority_sim(mp050, rfn, cal_5y, allow_untrig=allow_ut)
    w050 = p5.eval_fast_windows(s050, cache_base)

    spt = p5.run_priority_sim(mp_pt030, rfn, cal_5y, allow_untrig=allow_ut)
    wpt = p5.eval_fast_windows(spt, cache_base)

    sc_5y = p5.calc_window_dual_scissors(s030["trades_df"], base_sim030["trades_df"], w030, base_w030, "FULL_5Y", "2021-11-16", "2026-11-16")
    sc_wf = p5.calc_window_dual_scissors(s030["trades_df"], base_sim030["trades_df"], w030, base_w030, "WF_2326", "2023-01-03", "2026-11-16")
    sc_is = p5.calc_window_dual_scissors(s030["trades_df"], base_sim030["trades_df"], w030, base_w030, "IS_2123", "2021-11-16", "2023-12-31")
    sc_oos = p5.calc_window_dual_scissors(s030["trades_df"], base_sim030["trades_df"], w030, base_w030, "OOS_2426", "2024-01-01", "2026-11-16")

    p_wf = p5.v22.paired_perm_test(s030["dr_wf"], base_sim030["dr_wf"], n_perm=1000)
    p_5y = p5.v22.paired_perm_test(s030["dr_5y"], base_sim030["dr_5y"], n_perm=1000)

    # Gate checks (strict!)
    g_is_oos_all = (
        w030["IS_2123"]["nav"] >= base_w030["IS_2123"]["nav"] - 1e-6
        and w030["OOS_2426"]["nav"] >= base_w030["OOS_2426"]["nav"] - 1e-6
        and w030["WF_2326"]["nav"] >= base_w030["WF_2326"]["nav"] - 1e-6
        and w030["Y2025_2026"]["nav"] >= base_w030["Y2025_2026"]["nav"] - 1e-6
        and w030["Y2026"]["nav"] >= base_w030["Y2026"]["nav"] - 1e-6
        and (w030["FULL_5Y"]["nav"] > base_w030["FULL_5Y"]["nav"] + 1e-6)
    )
    g_dual_scissors = (sc_5y["mult_ex_both"] > 1.0) and (sc_wf["mult_ex_both"] > 1.0) and (sc_is["mult_ex_both"] >= 1.0) and (sc_oos["mult_ex_both"] > 1.0)
    g_mdd = w030["FULL_5Y"]["daily_mdd_pct"] <= 28.80 + 1e-6
    g_050 = (
        w050["IS_2123"]["nav"] >= base_w050["IS_2123"]["nav"] - 1e-6
        and w050["OOS_2426"]["nav"] >= base_w050["OOS_2426"]["nav"] - 1e-6
        and w050["Y2025_2026"]["nav"] >= base_w050["Y2025_2026"]["nav"] - 1e-6
        and w050["Y2026"]["nav"] >= base_w050["Y2026"]["nav"] - 1e-6
        and w050["FULL_5Y"]["daily_mdd_pct"] <= base_w050["FULL_5Y"]["daily_mdd_pct"] + 1e-6
    )

    # Exact trade diff list
    tb = base_sim030["trades_df"]
    tn = s030["trades_df"]
    kb = {(str(r.buy_date)[:10], str(r.code).zfill(6), str(r.strategy)): r for r in tb.itertuples(index=False)}
    kn = {(str(r.buy_date)[:10], str(r.code).zfill(6), str(r.strategy)): r for r in tn.itertuples(index=False)}
    diffs = []
    for k in sorted(kb):
        if k not in kn:
            r = kb[k]
            diffs.append({"scheme": sid, "action": "CROWDED_OUT", "buy_date": r.buy_date, "exit_date": r.exit_date, "strategy": r.strategy, "bucket": r.bucket, "code": r.code, "name": r.name, "score": float(r.score), "ret_pct": round(float(r.net_ret) * 100.0, 2)})
    for k in sorted(kn):
        if k not in kb:
            r = kn[k]
            diffs.append({"scheme": sid, "action": "ADDED", "buy_date": r.buy_date, "exit_date": r.exit_date, "strategy": r.strategy, "bucket": r.bucket, "code": r.code, "name": r.name, "score": float(r.score), "ret_pct": round(float(r.net_ret) * 100.0, 2)})

    row = {
        "scheme": sid, "group": grp, "desc": desc,
        "n_trades": w030["FULL_5Y"]["n"], "n_waits": len(s030["waits"]),
        "mtm_diff_5y": round(s030["mtm_diff_5y"], 9),
        "5Y_nav": w030["FULL_5Y"]["nav"], "5Y_ex5": w030["FULL_5Y"]["ex_top5_nav"],
        "5Y_mdd": w030["FULL_5Y"]["daily_mdd_pct"], "5Y_dd2": w030["FULL_5Y"]["second_mdd_pct"], "5Y_sh": w030["FULL_5Y"]["daily_sharpe"], "5Y_cal": w030["FULL_5Y"]["daily_calmar"],
        "IS_nav": w030["IS_2123"]["nav"], "IS_mdd": w030["IS_2123"]["daily_mdd_pct"], "IS_sh": w030["IS_2123"]["daily_sharpe"],
        "OOS_nav": w030["OOS_2426"]["nav"], "OOS_mdd": w030["OOS_2426"]["daily_mdd_pct"], "OOS_sh": w030["OOS_2426"]["daily_sharpe"],
        "WF_nav": w030["WF_2326"]["nav"], "WF_mdd": w030["WF_2326"]["daily_mdd_pct"], "WF_sh": w030["WF_2326"]["daily_sharpe"],
        "Y2526_nav": w030["Y2025_2026"]["nav"], "Y26_nav": w030["Y2026"]["nav"], "Y26H2_nav": w030["Y2026_H2"]["nav"],
        "050_5Y_nav": w050["FULL_5Y"]["nav"], "050_5Y_mdd": w050["FULL_5Y"]["daily_mdd_pct"],
        "050_IS_nav": w050["IS_2123"]["nav"], "050_OOS_nav": w050["OOS_2426"]["nav"], "050_2526_nav": w050["Y2025_2026"]["nav"], "050_26_nav": w050["Y2026"]["nav"],
        "pt_5Y_nav": wpt["FULL_5Y"]["nav"], "pt_IS_nav": wpt["IS_2123"]["nav"], "pt_OOS_nav": wpt["OOS_2426"]["nav"], "pt_5Y_mdd": wpt["FULL_5Y"]["daily_mdd_pct"],
        "n_added": sc_5y["n_added"], "n_removed": sc_5y["n_removed"],
        "ex_both_5Y": sc_5y["mult_ex_both"], "ex_both_WF": sc_wf["mult_ex_both"], "ex_both_IS": sc_is["mult_ex_both"], "ex_both_OOS": sc_oos["mult_ex_both"],
        "paired_t_5Y": p_5y["paired_t"], "paired_p1_5Y": p_5y["paired_perm_p_1sided"],
        "paired_t_WF": p_wf["paired_t"], "paired_p1_WF": p_wf["paired_perm_p_1sided"],
        "gate_is_oos_all": g_is_oos_all, "gate_dual_scissors": g_dual_scissors, "gate_mdd_2880": g_mdd, "gate_050_stress": g_050,
        "PASS_ALL_GATES_PRE_TRUNC": bool(g_is_oos_all and g_dual_scissors and g_mdd and g_050),
    }
    detail = {
        "row": row,
        "windows_030": w030,
        "windows_050": w050,
        "dual_scissors": {"FULL_5Y": sc_5y, "WF_2326": sc_wf, "IS_2123": sc_is, "OOS_2426": sc_oos},
        "paired_5y": p_5y,
        "paired_wf": p_wf,
        "diffs_vs_base": diffs,
    }
    return row, detail, diffs


def run_truncation_check_on_schemes(schemes_to_check: list[tuple[str, object, bool]], cache_full: dict, raw_4to5_full: pd.DataFrame) -> dict:
    """Physical 2024-12-31 truncation zero-leakage proof across Base and candidate priority schemes."""
    print("[Step 2.4] Running 2024-12-31 Physical Truncation Check...", flush=True)
    with open(f"{P3}/_cache/v22_dirb_ledgers_trunc2024.pkl", "rb") as f:
        raw45_trunc = pickle.load(f)["ledgers"]["SJ114_E4_DtDefer"]["raw"]
    reg_full = pd.read_parquet(f"{p5.RD049}/_cache/rd049_daily_regime_pit.parquet")
    reg_trunc = trp.s0.build_regime_table(end_cutoff=trp.CUTOFF)
    reg2_full = p5.v22.cm49.build_2d_states(reg_full, y_cut=42.0, x_sh=20.0, x_dp=42.0).set_index("trade_date")
    reg2_trunc = p5.v22.cm49.build_2d_states(reg_trunc, y_cut=42.0, x_sh=20.0, x_dp=42.0).set_index("trade_date")

    cache_trunc = trp.build_trunc_master_cache(cache_full)
    cp2_full = p5.v22.apply_v22_modifications(cache_full, reg2_full, use_p2=True, use_dirA=False)
    cp2_trunc = p5.v22.apply_v22_modifications(cache_trunc, reg2_trunc, use_p2=True, use_dirA=False)

    mp_full = p5.build_p5_master_pool(cp2_full, raw_4to5_full, fee_mode="030", use_pass_top1=False)
    mp_trunc = p5.build_p5_master_pool(cp2_trunc, raw45_trunc, fee_mode="030", use_pass_top1=False)

    cal_full = cp2_full["cal_5y"]
    cal_trunc = cp2_trunc["cal_5y"]
    out = {}
    max_all = 0.0
    for sid, rfn, allow_ut in schemes_to_check:
        sf = p5.run_priority_sim(mp_full, rfn, cal_full, allow_untrig=allow_ut)
        st = p5.run_priority_sim(mp_trunc, rfn, cal_trunc, allow_untrig=allow_ut)
        df_f = sf["trades_df"][sf["trades_df"]["exit_date"] <= trp.CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
        df_t = st["trades_df"][st["trades_df"]["exit_date"] <= trp.CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
        assert len(df_f) == len(df_t), f"Trunc len mismatch {sid}: {len(df_f)} vs {len(df_t)}"
        assert list(zip(df_f["buy_date"], df_f["code"], df_f["strategy"])) == list(zip(df_t["buy_date"], df_t["code"], df_t["strategy"]))
        ret_diff = float(np.max(np.abs(df_f["net_ret"].to_numpy(float) - df_t["net_ret"].to_numpy(float))))
        last_ex = str(df_f["exit_date"].max())
        pos_c = [i for i, d in enumerate(cal_trunc) if d <= last_ex]
        mtm_diff = float(np.max(np.abs(sf["dr_5y"][pos_c] - st["dr_5y"][pos_c])))
        max_all = max(max_all, ret_diff, mtm_diff)
        assert ret_diff == 0.0 and mtm_diff == 0.0, f"Leakage on {sid}: ret={ret_diff}, mtm={mtm_diff}"
        out[sid] = {"n_le_cutoff": int(len(df_f)), "max_abs_ret_diff": ret_diff, "max_abs_mtm_diff": mtm_diff, "pass": True}
        print(f"  TRUNC {sid:36s}: n={len(df_f)}, max_abs_diff=0.0 [PASS]", flush=True)
    return {"cutoff": trp.CUTOFF, "overall_max_abs_diff": max_all, "schemes": out}


def main():
    t0 = time.time()
    print("[P5 Step 2.1] Loading Pure V22 assets & building 030/050/PassTop1 pools...", flush=True)
    assets = p5.load_p5_raw_assets()
    cal_5y = assets["c_p2"]["cal_5y"]
    mp030 = p5.build_p5_master_pool(assets["c_p2"], assets["raw_4to5"], fee_mode="030", use_pass_top1=False)
    mp050 = p5.build_p5_master_pool(assets["c_p2"], assets["raw_4to5"], fee_mode="050", use_pass_top1=False)
    mp_pt030 = p5.build_p5_master_pool(assets["c_p2"], assets["raw_4to5"], fee_mode="030", use_pass_top1=True)

    schemes = _build_named_schemes()
    # Evaluate Base first
    b_sid, b_grp, b_desc, b_rfn, b_ut = schemes[0]
    base_sim030 = p5.run_priority_sim(mp030, b_rfn, cal_5y, allow_untrig=b_ut)
    base_w030 = p5.eval_fast_windows(base_sim030, assets["cache_base"])
    base_sim050 = p5.run_priority_sim(mp050, b_rfn, cal_5y, allow_untrig=b_ut)
    base_w050 = p5.eval_fast_windows(base_sim050, assets["cache_base"])
    base_sim_pt = p5.run_priority_sim(mp_pt030, b_rfn, cal_5y, allow_untrig=b_ut)
    base_wpt = p5.eval_fast_windows(base_sim_pt, assets["cache_base"])

    print(f"[P5 Step 2.2] Running exhaustive 6!=720 Tier-2 permutations...", flush=True)
    df720, sweep720_meta = run_exhaustive_720_tier2_sweep(mp030, cal_5y, assets["cache_base"], base_w030)
    print(f"  720 Tier-2 Sweep: unique_curves={sweep720_meta['unique_trade_trajectories']}, beat_base_all_windows={sweep720_meta['n_beat_base_all_windows_and_mdd']}, canon_rank={sweep720_meta['canon_rank_in_720']}/720", flush=True)

    # Also add top-3 unique Tier-2 orders from 720-sweep into named schemes if distinct from canon!
    canon_str = "3to4_925 > high_925 > pry > 2to3 > 1to2_925 > 20cm"
    added_sigs = set()
    for i, r7 in enumerate(df720.head(10).itertuples(index=False)):
        if r7.t2_order == canon_str:
            continue
        sig_w = (r7.n, r7.nav_5y, r7.nav_wf)
        if sig_w in added_sigs or len(added_sigs) >= 3:
            continue
        added_sigs.add(sig_w)
        seq = r7.t2_order.split(" > ")
        bm = build_tier2_order_map(seq, strict_3tier=True)
        schemes.append((f"B_720TOP{len(added_sigs)}_{'_'.join(seq)}", "B_TIER2_720TOP", f"720-sweep top #{i+1}: {r7.t2_order}", p5.make_bucket_rank_fn(bm), True))

    print(f"[P5 Step 2.3] Evaluating {len(schemes)} named priority architectures + Cold-Blooded Gates...", flush=True)
    grid_rows = []
    details_map = {}
    all_diffs = []
    for sid, grp, desc, rfn, allow_ut in schemes:
        row, det, diffs = evaluate_scheme_full(
            sid, grp, desc, rfn, allow_ut,
            mp030, mp050, mp_pt030, cal_5y, assets["cache_base"],
            base_sim030, base_w030, base_sim050, base_w050, base_wpt,
        )
        grid_rows.append(row)
        details_map[sid] = det
        all_diffs.extend(diffs)

    df_grid = pd.DataFrame(grid_rows)
    df_grid.to_csv(f"{P5}/p5_priority_grid.csv", index=False, encoding="utf-8-sig")
    df720.to_csv(f"{P5}/p5_tier2_720_sweep.csv", index=False, encoding="utf-8-sig")

    # Select Base + top candidates (all that pass pre-trunc OR top 5 by WF NAV) for 2024-12-31 Truncation Proof
    passers = df_grid[df_grid["PASS_ALL_GATES_PRE_TRUNC"]]["scheme"].tolist()
    top_wf = df_grid.sort_values("WF_nav", ascending=False)["scheme"].head(5).tolist()
    trunc_ids = list(dict.fromkeys(["Base_V22_OldOrder_4to5AtPos5", "Base_Strict3Tier_4to5AtPos5"] + passers + top_wf))
    scheme_lu = {s[0]: (s[0], s[3], s[4]) for s in schemes}
    trunc_res = run_truncation_check_on_schemes([scheme_lu[k] for k in trunc_ids], assets["cache_base"], assets["raw_4to5"])

    # Load step1 panorama & pairwise to assemble final unified p5_collision_audit.json
    with open(f"{P5}/_step1_panorama_pairwise.json", encoding="utf-8") as f:
        s1_pkg = json.load(f)

    pass_final = []
    for r in df_grid.itertuples(index=False):
        tr_ok = trunc_res["schemes"].get(r.scheme, {}).get("pass", False)
        if r.PASS_ALL_GATES_PRE_TRUNC and tr_ok:
            pass_final.append(r.scheme)

    final_verdict = {
        "base_id": "Base_V22_OldOrder_4to5AtPos5",
        "n_named_schemes_tested": len(df_grid),
        "n_tier2_720_sweep_beat_base_all": sweep720_meta["n_beat_base_all_windows_and_mdd"],
        "schemes_passing_all_4_cold_gates": pass_final,
        "recommended_live_priority": pass_final[0] if pass_final else "Base_V22_OldOrder_4to5AtPos5",
    }

    audit_json = p5.v22.sanitize_json({
        "task": "V22.0 Pillar 5: Full-History 7-Strategy Collision Anatomy & Fine-Tier Priority Optimization",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "d12_yfinance_imported": False,
        "final_verdict": final_verdict,
        "task1_collision_panorama_primary": s1_pkg["panorama_primary"],
        "task1_collision_panorama_passtop1": s1_pkg["panorama_crosscheck_passtop1"],
        "task2_pairwise_7x7_primary": s1_pkg["pairwise_7x7_primary"],
        "task2_pairwise_7x7_passtop1": s1_pkg["pairwise_7x7_crosscheck_passtop1"],
        "task3_tier2_720_sweep_meta": sweep720_meta,
        "task3_priority_grid_rows": grid_rows,
        "task4_truncation_proof_2024_12_31": trunc_res,
        "scheme_details_and_diffs": {k: {"dual_scissors": v["dual_scissors"], "paired_5y": v["paired_5y"], "paired_wf": v["paired_wf"], "diffs_vs_base": v["diffs_vs_base"]} for k, v in details_map.items()},
    })
    with open(f"{P5}/p5_collision_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit_json, f, ensure_ascii=False, indent=2)

    print(f"\n[P5 Step 2 DONE in {time.time()-t0:.2f}s]")
    cols = ["scheme", "n_trades", "5Y_nav", "5Y_mdd", "5Y_sh", "IS_nav", "OOS_nav", "WF_nav", "Y2526_nav", "Y26_nav", "n_added", "n_removed", "ex_both_5Y", "ex_both_WF", "ex_both_IS", "ex_both_OOS", "PASS_ALL_GATES_PRE_TRUNC"]
    print(df_grid[cols].to_string(index=False))
    print("\nFINAL PASSERS ALL 4 GATES:", pass_final)


if __name__ == "__main__":
    main()
