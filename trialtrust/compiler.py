"""Conservative rule compiler with a loss ledger; not an LLM or anonymizer.

It only extracts supported explicit fields. Ambiguity blocks a proposal and
unmodeled text remains visible for human comparison, never becomes authority.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .mandate import Mandate
from .catalog import CATALOG


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
    fields: dict[str, list] = {name: [] for name in ("domain", "quantity", "fulfillment", "budget_yuan")}
    spans, issues = [], []
    numeral = dict(zip("一二三四五六七八九", range(1, 10))) | {"两": 2, "十": 10}

    def add(field, value, match):
        before = text[max(0, match.start() - 5):match.start()]
        if re.search(r"不[是想选要用去]|不能|无需|禁止|不要|或|[0-9][-至到]$", before):
            issues.append({"field": field, "reason": "negated_or_conditional_expression", "text": match.group()})
            return
        fields[field].append(value)
        spans.append({"field": field, "value": value, "text": match.group(),
                      "start": match.start(), "end": match.end()})

    keywords = {word.lower(): key for key, entry in CATALOG.items() for word in entry['keywords']}
    for match in re.finditer('|'.join(re.escape(word) for word in sorted(keywords,key=len,reverse=True)), text, re.I):
        add("domain", keywords[match.group().lower()], match)
    quantity_units = []
    for match in re.finditer(r"(?<![\d.\-一二两三四五六七八九十百])([0-9]+|[一二两三四五六七八九十])\s*(人|台|份|间|次)", text):
        token = match.group(1)
        add("quantity", int(token) if token.isascii() else numeral[token], match)
        quantity_units.append(match.group(2))
    for match in re.finditer(r"(?:总预算|预算)(?:为|是|不超过|最多|[：:])?\s*[¥￥]?\s*([0-9]+)(?:\s*元)?(?![\d.])", text):
        add("budget_yuan", int(match.group(1)), match)
    modes = {'到店自取':'pickup','自取':'pickup','作品邮寄':'shipping','邮寄':'shipping','上门':'onsite','到场入园':'entry','入园':'entry','到场':'entry','到店用餐':'dine_in','用餐':'dine_in','集合出行':'meetup','集合':'meetup','入住体验':'stay','入住':'stay','到店体验':'visit','乘车出行':'ride','乘车':'ride','到店租还':'rental'}
    for match in re.finditer('|'.join(sorted(modes,key=len,reverse=True)), text):
        value = modes[match.group()]
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
    if len(set(fields['domain'])) == 1 and quantity_units:
        if any(unit != CATALOG[fields['domain'][0]]['unit'] for unit in quantity_units):
            issues.append({'field':'quantity','reason':'unsupported_quantity_unit'})
    if not issues:
        try:
            proposal = Mandate(**chosen).model_dump(exclude_none=True)
        except ValidationError:
            issues.append({"field": "combination", "reason": "unsupported_combination"})
    return {"compiler": "explicit_rules_v1", "proposal": proposal, "field_evidence": spans,
            "issues": issues, "unmodeled_fragments": leftovers,
            "requires_human_confirmation": True,
            "limits": ["只提取明确的场景、数量、预算和服务方式。",
                       "时间、地址、机型和其他附加要求没有进入试验条件，请逐项核对。",
                       "本地格式替换不是完全匿名化；请手动删除仍能识别你的描述。",
                       "原文和替身不写入试托记录；只保存你确认的结构化条件。"]}
