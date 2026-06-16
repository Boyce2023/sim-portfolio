# /// script
# requires-python = ">=3.11"
# ///
"""
Humility Guard — 美股交易系统的"谦逊护栏"硬拦截层 (2026-06-16)

起因: MnO2事故。Claude不会精确估值(无DCF), 卖方观点被禁用。
因此系统结构上禁止对"没有完整price+估值记录"的标的输出"排除/不成立/不值得"类verdict。

这是唯一让"结构上禁止排除"从口号变成事实的东西: 在任何标的记录被
dump到JSON或render到屏幕之前, 强制过一遍这个guard。带禁用词且无估值
记录的, 不是被静默放行, 而是抛错(开发期)或降级为 unscored(运行期)。

用法:
    from humility_guard import assert_no_unscored_verdict, scrub_record
    assert_no_unscored_verdict(record)        # 违规抛 HumilityViolation
    safe = scrub_record(record, mode="downgrade")  # 违规降级为 unscored
"""
from __future__ import annotations

# 禁用的"判断性"verdict —— 这些结论需要估值才能下, Claude下不了, 故禁止
FORBIDDEN_VERDICTS = {
    "排除", "不成立", "不值得", "淘汰", "毙", "没机会", "不该买", "不值",
    "exclude", "excluded", "reject", "rejected", "not worth", "avoid",
    "T4",  # 历史熊方tier标签, 未配实时downside来源时=未估值的排除
}

# 一条记录要能携带任何verdict, 必须同时具备这两个"我真做过功课"的证据
REQUIRED_VALUATION_EVIDENCE = ("price", "valuation_record")


class HumilityViolation(AssertionError):
    """系统试图对一个没估值的标的下排除类判断。"""


def _text_blob(record: dict) -> str:
    """把一条记录里所有字符串值拼起来, 用于扫禁用词。"""
    parts = []
    for v in record.values():
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, (list, tuple)):
            parts.extend(str(x) for x in v if isinstance(x, str))
    return " ".join(parts).lower()


def has_valuation_record(record: dict) -> bool:
    """这个标的是否真的被定价+估值过 —— 没有就不准对它下排除判断。"""
    price = record.get("price")
    if price is None or price == 0:
        return False
    # valuation_record: 任何一个真实估值锚存在即可(PEG/相对分位/供给侧分)
    anchors = ("peg", "peg_g3", "relative_rank", "supply_score", "pps", "valuation_record")
    return any(record.get(a) is not None for a in anchors)


def find_forbidden_verdict(record: dict) -> str | None:
    """返回记录里出现的第一个禁用verdict, 没有返回None。"""
    blob = _text_blob(record)
    for word in FORBIDDEN_VERDICTS:
        if word.lower() in blob:
            return word
    # category/bucket 字段单独精确匹配(不靠子串)
    for field in ("category", "bucket", "action", "verdict", "priority"):
        val = str(record.get(field, "")).strip().lower()
        if val in {w.lower() for w in FORBIDDEN_VERDICTS}:
            return record.get(field)
    return None


def assert_no_unscored_verdict(record: dict) -> None:
    """开发期硬拦截: 带排除verdict但无估值记录 → 抛错。"""
    verdict = find_forbidden_verdict(record)
    if verdict and not has_valuation_record(record):
        raise HumilityViolation(
            f"标的 {record.get('ticker','?')} 携带排除类判断 '{verdict}' "
            f"但无完整估值记录(price+估值锚)。系统不会估值, 禁止未估值的排除。"
            f"→ 应标 needs_user_valuation=True / unscored, 把判断留给用户。"
        )


def scrub_record(record: dict, mode: str = "downgrade") -> dict:
    """运行期: 违规记录降级为 unscored 而非放行排除结论。"""
    verdict = find_forbidden_verdict(record)
    if verdict and not has_valuation_record(record):
        if mode == "raise":
            assert_no_unscored_verdict(record)
        r = dict(record)
        r["status"] = "unscored"
        r["needs_user_valuation"] = True
        r["humility_note"] = (
            f"原含'{verdict}'但无估值记录, 已降级为未评估。系统不估值, 判断归你。"
        )
        # 抹掉verdict承载字段, 不让排除结论流出
        for f in ("category", "bucket", "action", "verdict", "priority"):
            if str(r.get(f, "")).strip().lower() in {w.lower() for w in FORBIDDEN_VERDICTS}:
                r[f] = "unscored"
        return r
    return record


def guard_emit(records: list[dict], mode: str = "downgrade") -> list[dict]:
    """dump/render前的总闸: 整批过一遍。这是该被接到每个输出点的函数。"""
    if mode == "raise":
        for r in records:
            assert_no_unscored_verdict(r)
        return records
    return [scrub_record(r, mode="downgrade") for r in records]
