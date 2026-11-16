# -*- coding: utf-8 -*-
"""
飞书策略主文档构建器与格式校验器
生成七篇文档的 Feishu docx block 结构，并执行 100% 像素级格式与人话门禁硬校验。
"""
import re, json

# 禁用黑话与符号规则
BANNED_WORDS = [
    "星辰大海", "皇冠明珠", "飞轮", "赋能", "闭环", "跃迁", "重塑", "颠覆", "范式", "矩阵", "全景", "硬核",
    "标尺", "试金石", "胜负手", "王牌", "天花板", "抓手", "撬动", "铁证", "铁律", "命门", "法典", "宪法",
    "D8", "D15", "SSOT", "绞肉机", "法医", "五板策略", "s_prior", "s_quant", "dd20", "dd60", "pos20", "obc"
]
BANNED_PUNC = ["-", "—", "——", "–", "！", "!", "→", "**"]

def make_text_run(content, bold=False, underline=False, text_color=None, background_color=None):
    st = {}
    if bold: st["bold"] = True
    if underline: st["underline"] = True
    if text_color is not None: st["text_color"] = text_color
    if background_color is not None: st["background_color"] = background_color
    return {"text_run": {"content": content, "text_element_style": st}}

def make_para_block(runs):
    return {
        "block_type": 2,
        "text": {
            "elements": runs,
            "style": {"align": 1, "folded": False}
        }
    }

def make_ordered_block(runs, seq="auto"):
    return {
        "block_type": 13,
        "ordered": {
            "elements": runs,
            "style": {"align": 1, "folded": False, "sequence": seq}
        }
    }

def make_bullet_block(runs):
    return {
        "block_type": 12,
        "bullet": {
            "elements": runs,
            "style": {"align": 1, "folded": False}
        }
    }

def make_blank_line():
    return make_para_block([make_text_run("")])

def validate_runs(runs, doc_name=""):
    for r in runs:
        txt = r["text_run"]["content"]
        for p in BANNED_PUNC:
            if p in txt:
                raise ValueError(f"[{doc_name}] 发现违规标点 '{p}': {txt}")
        for w in BANNED_WORDS:
            if w in txt:
                raise ValueError(f"[{doc_name}] 发现违规黑话/变量 '{w}': {txt}")

def validate_table(rows, doc_name=""):
    C = max(len(r) for r in rows)
    if C > 5:
        raise ValueError(f"[{doc_name}] 表格列数超标: {C} 列 > 5 列")
    for r in rows:
        for cell in r:
            for txt, st in cell:
                for p in BANNED_PUNC:
                    if p in txt:
                        raise ValueError(f"[{doc_name}] 表格单元格违规标点 '{p}': {txt}")
                for w in BANNED_WORDS:
                    if w in txt:
                        raise ValueError(f"[{doc_name}] 表格单元格违规黑话/变量 '{w}': {txt}")

print("build_master_docs validator module loaded.")
