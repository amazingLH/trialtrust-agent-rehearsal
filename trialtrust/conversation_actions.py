"""Typed same-origin conversation commands for method-limited public gateways."""
from typing import Literal
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class ConversationAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["rename", "delete"]
    confirmed: StrictBool
    expected_updated: float = Field(strict=True, gt=0, allow_inf_nan=False)
    title: str | None = Field(default=None, strict=True, min_length=1, max_length=60)

    @model_validator(mode="after")
    def validate_operation(self):
        if self.operation == "rename":
            if self.title is None:
                raise ValueError("重命名需要会话名称")
            self.title = self.title.strip()
            if not self.title or any(ord(c) < 32 or ord(c) == 127 for c in self.title):
                raise ValueError("会话名称需为1—60个可见字符")
        elif self.title is not None:
            raise ValueError("删除操作不接受会话名称")
        return self


def register_conversation_actions(app, store, require_owner):
    @app.post("/api/conversations/{conversation_id}/actions")
    def conversation_action(conversation_id: str, body: ConversationAction, request: Request):
        owner = require_owner(request)
        if not body.confirmed:
            raise HTTPException(409, "请先明确确认本次会话操作")
        return store.change_conversation(
            conversation_id, owner, title=body.title if body.operation == "rename" else None,
            expected_updated=body.expected_updated
        )
