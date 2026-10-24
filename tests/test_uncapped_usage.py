"""Normal application calls keep their ledger without cumulative local caps."""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from trialtrust.provider import Bailian, TokenLedger
from trialtrust.webapp import create_app


def test_legacy_environment_caps_do_not_limit_default_application_usage(tmp_path, monkeypatch):
    monkeypatch.setenv('TRIALTRUST_TOKEN_LIMIT', '200000')
    monkeypatch.setenv('TRIALTRUST_BUDGET_CNY', '3')
    path=tmp_path/'usage.sqlite'
    previous=TokenLedger(path, limit=200000)
    old_id=previous.reserve('chat', 200000)
    with pytest.raises(RuntimeError, match='token budget'):
        previous.reserve('chat', 1)

    current=TokenLedger(path)
    new_id=current.for_run('after-upgrade').reserve('chat', 500000)
    assert new_id>old_id
    usage=current.summary()
    assert usage['charged_or_reserved_tokens']==700000
    assert usage['conservative_valued_cny']>3
    assert usage['application_token_limit'] is None
    assert usage['application_estimated_budget_cny'] is None
    assert usage['application_limits_enabled'] is False
    assert usage['budget_applies_to']=='none'
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT reserved,actual,status FROM calls WHERE id=?',(old_id,)).fetchone()==(200000,None,'reserved')
    reopened=TokenLedger(path)
    reopened.settle(new_id, 37)
    reopened.reserve('chat', 500000)
    assert reopened.summary()['requests']==3
    assert reopened.for_run('after-upgrade').summary(run_only=True)['charged_or_reserved_tokens']==37


def test_default_provider_reaches_service_after_old_token_and_cost_thresholds(tmp_path, monkeypatch):
    import trialtrust.provider as module
    monkeypatch.setenv('TRIALTRUST_TOKEN_LIMIT', '1')
    monkeypatch.setenv('TRIALTRUST_BUDGET_CNY', '0.000001')
    monkeypatch.setenv('DASHSCOPE_API_KEY','fixture-provider-key')
    path=tmp_path/'usage.sqlite'
    ledger=TokenLedger(path)
    ledger.reserve('historical-usage',500000)
    calls=[]

    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,headers,json):
            calls.append(json)
            return type('Response',(),{'status_code':200,'json':lambda self:{'usage':{'total_tokens':9},'choices':[{'message':{'role':'assistant','content':'ok'},'finish_reason':'stop'}]}})()

    monkeypatch.setattr(module.httpx,'Client',Client)
    assert Bailian(TokenLedger(path)).chat([{'role':'user','content':'hello'}])['content']=='ok'
    assert len(calls)==1
    assert ledger.summary()['charged_or_reserved_tokens']==500009


def test_existing_application_ledger_does_not_stop_requirement_analysis(tmp_path, monkeypatch):
    path=tmp_path/'usage.sqlite'
    old=TokenLedger(path)
    old_id=old.reserve('old-request',500000)
    monkeypatch.setenv('TRIALTRUST_TOKEN_LIMIT','200000')
    monkeypatch.setenv('TRIALTRUST_BUDGET_CNY','3')

    def chat(self,messages,**kwargs):
        assert self.ledger.limit is None and self.ledger.budget_nano_cny is None
        request=self.ledger.reserve('analysis',100)
        self.ledger.settle(request,23)
        return {'role':'assistant','content':json.dumps({'summary':'刷鞋','fields':[],'missing':[]})}

    monkeypatch.setattr(Bailian,'chat',chat)
    with TestClient(create_app(tmp_path/'web',enable_live=True,require_accounts=False)) as client:
        headers={'X-TrialTrust-Client':'web'}
        client.post('/api/session',json={},headers=headers)
        response=client.post('/api/analyze',json={'text':'刷鞋；数量：2双；服务方式：到店送洗；预算350元','reviewed':True,'use_model':True},headers=headers)
        assert response.status_code==200,response.text
        assert response.json()['can_rehearse']
        assert response.json()['usage']['application_limits_enabled'] is False
        assert response.json()['usage']['application_token_limit'] is None
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT reserved FROM calls WHERE id=?',(old_id,)).fetchone()==(500000,)


@pytest.mark.parametrize('limit',[0,-1,True,1.5])
def test_explicit_evaluation_token_limit_is_validated(tmp_path,limit):
    with pytest.raises(ValueError): TokenLedger(tmp_path/'usage.sqlite',limit=limit)


@pytest.mark.parametrize('budget',['0','-1','NaN','Infinity'])
def test_explicit_evaluation_cost_budget_is_validated(tmp_path,budget):
    with pytest.raises(ValueError): TokenLedger(tmp_path/'usage.sqlite',budget_cny=budget)
