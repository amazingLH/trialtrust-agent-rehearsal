"""Owner-scoped metadata actions; recorded conditions and reports stay immutable."""
from typing import Literal
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class RunAction(BaseModel):
    model_config=ConfigDict(extra="forbid")
    operation: Literal['rename','delete']
    confirmed: StrictBool
    expected_revision: int=Field(ge=0,strict=True)
    title: str | None=Field(default=None,min_length=1,max_length=60,strict=True)

    @model_validator(mode='after')
    def operation_fields(self):
        if self.operation=='rename':
            if self.title is None:
                raise ValueError('请输入彩排记录名称')
            self.title=self.title.strip()
            if not self.title or any(ord(c)<32 or ord(c)==127 for c in self.title):
                raise ValueError('名称需为1—60个可见字符')
        elif self.title is not None:
            raise ValueError('删除操作不接受名称')
        return self


def register_run_actions(app,store,require_owner,locks):
    @app.post('/api/trials/{run_id}/actions')
    def run_action(run_id: str,body: RunAction,request: Request):
        owner=require_owner(request)
        if not body.confirmed:
            raise HTTPException(409,'请先确认本次记录操作')
        with locks[run_id]:
            return store.change_run(run_id,owner,title=body.title if body.operation=='rename' else None,
                                    expected_revision=body.expected_revision)
