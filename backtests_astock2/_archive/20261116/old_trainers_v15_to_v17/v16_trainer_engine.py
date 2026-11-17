# -*- coding: utf-8 -*-
"""
v16_trainer_engine.py: V16 题库核心引擎统一门面
整合特征挂载、V16 综合打分、5分钟分时四分支撮合引擎与大白话复盘生成器。
"""
import sys
from pathlib import Path

CURR_DIR = str(Path(__file__).resolve().parent)
if CURR_DIR not in sys.path:
    sys.path.insert(0, CURR_DIR)

from v16_scoring import (
    compute_v16_features_and_scores,
    CSRC_PURE_OUTSIDER,
    HARD_TECH_RE
)
from v16_trade_matcher import make_v16_trade_engine
from v16_vernacular_review import generate_vernacular_review

__all__ = [
    "compute_v16_features_and_scores",
    "make_v16_trade_engine",
    "generate_vernacular_review",
    "CSRC_PURE_OUTSIDER",
    "HARD_TECH_RE",
]
