"""Conservative rule compiler with a loss ledger; not an LLM or anonymizer.

It only extracts supported explicit fields. Ambiguity blocks a proposal and
unmodeled text remains visible for human comparison, never becomes authority.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .mandate import Mandate


class CompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stand_in_text: str = Field(min_length=1, max_length=1200)


PRIVATE_PATTERNS = [r"(?<!\d)1[3-9]\d{9}(?!\d)",
                    r"(?<!\d)\d{17}[0-9Xx](?!\d)",
                    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"]


def has_recognizable_identifier(text):
    return any(re.search(pattern, text) for pattern in PRIVATE_PATTERNS)


def compile_stand_in(text: str) -> dict:
    if has_recognizable_identifier(text):
        raise ValueError("替身仍含可识别的手机号、邮箱或身份证格式，请先在本地替换")
    fields: dict[str, list] = {name: [] for name in Mandate.model_fields}
    spans, issues = [], []
    numeral = {str(i): i for i in range(1, 9)} | dict(zip("一二三四五六七八", range(1, 9))) | {"两": 2}

    def add(field, value, match):
        before = text[max(0, match.start() - 5):match.start()]
        if re.search(r"不[是想选要用去]|不能|无需|禁止|不要|或|[0-9][-至到]$", before):
            issues.append({"field": field, "reason": "negated_or_conditional_expression", "text": match.group()})
            return
        fields[field].append(value)
        spans.append({"field": field, "value": value, "text": match.group(),
                      "start": match.start(), "end": match.end()})

    for match in re.finditer(r"陶艺|空调清洗|清洗空调", text):
        add("domain", "pottery" if match.group() == "陶艺" else "cleaning", match)
    for match in re.finditer(r"(?<![\d一二三四五六七八九十百])([1-8一二两三四五六七八])\s*(人|台)", text):
        add("quantity", numeral[match.group(1)], match)
    for match in re.finditer(r"(?:总预算|预算)(?:为|是|不超过|最多|[：:])?\s*([0-9]{1,4})\s*元", text):
        add("budget_yuan", int(match.group(1)), match)
    for match in re.finditer(r"到店自取|自取|作品邮寄|邮寄|上门", text):
        value = "shipping" if "邮寄" in match.group() else "onsite" if "上门" in match.group() else "pickup"
        add("fulfillment", value, match)
    chosen = {}
    for field, values in fields.items():
        unique = set(values)
        if len(unique) != 1:
            issues.append({"field": field, "reason": "missing" if not unique else "conflicting_values"})
        else:
            chosen[field] = values[0]

    # Preserve every unmatched span, even apparently harmless wording. We do not
    # silently claim to support dates, locations, allergies or additional clauses.
    covered = [False] * len(text)
    for span in spans:
        covered[span["start"]:span["end"]] = [True] * (span["end"] - span["start"])
    leftovers = []
    for match in re.finditer(r"[^，。；;、\n]+", text):
        fragment = "".join(char if not covered[i] else " " for i, char in enumerate(text[match.start():match.end()], match.start())).strip(" 、:：，。；;\t")
        if fragment:
            leftovers.append(fragment)
    proposal = None
    if not issues:
        try:
            proposal = Mandate(**chosen).model_dump()
        except ValidationError:
            issues.append({"field": "combination", "reason": "unsupported_combination"})
    return {"compiler": "explicit_rules_v1", "proposal": proposal, "field_evidence": spans,
            "issues": issues, "unmodeled_fragments": leftovers,
            "requires_human_confirmation": True,
            "limits": ["只提取明确的场景、数量、预算和服务方式。",
                       "时间、地址、机型和其他附加要求没有进入试验条件，请逐项核对。",
                       "本地格式替换不是完全匿名化；请手动删除仍能识别你的描述。",
                       "原文和替身不写入试托记录；只保存你确认的结构化条件。"]}
