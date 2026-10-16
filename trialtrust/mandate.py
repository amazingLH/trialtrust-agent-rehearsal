"""Closed, reviewable task contracts. Text is never executable authority."""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .catalog import CATALOG, FULFILLMENTS, Domain, Fulfillment


DOMAIN_LABELS = {key: value['label'] for key, value in CATALOG.items()}
FULFILLMENT_LABELS = FULFILLMENTS


class Mandate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    domain: Domain = "pottery"
    quantity: int = Field(default=4, ge=1, le=8, strict=True)
    fulfillment: Fulfillment = "pickup"
    budget_yuan: int = Field(default=300, ge=0, le=1000, strict=True)

    @model_validator(mode="after")
    def supported_combination(self):
        if self.fulfillment not in CATALOG[self.domain]['fulfillments']:
            raise ValueError("该场景不支持当前服务方式，请核对后重新确认")
        return self

    @property
    def digest(self):
        body = {"version": "mandate-v1", **self.model_dump(),
                "allowed_actions": ["search_rules", "check_plan", "submit_draft"],
                "required_evidence": ["price", "cancellation"]}
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    def task(self):
        noun = CATALOG[self.domain]['unit']
        return (f"为{self.quantity}{noun}的{DOMAIN_LABELS[self.domain]}查清全部费用和退改规则。"
                f"方式是{FULFILLMENT_LABELS[self.fulfillment]}，总预算{self.budget_yuan}元。"
                "只查询、核验和生成候选草稿，不预约、付款、联系商家或共享个人资料。"
                "费用超支、证据缺失或条件不支持时明确说明，不编造草稿。")

    def record(self):
        return {"version": "mandate-v1", **self.model_dump(), "digest": self.digest,
                "allowed_actions": ["search_rules", "check_plan", "submit_draft"],
                "required_evidence": ["price", "cancellation"],
                "scope": "owned_synthetic_fixture_only"}
