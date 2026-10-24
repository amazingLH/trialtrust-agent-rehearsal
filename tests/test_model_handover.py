"""Provider-confirmed free-quota exhaustion hands the same request to Qwen once."""
import json
import sqlite3

import httpx
import pytest

from trialtrust.provider import Bailian, TokenLedger, PRIMARY_MODEL, FALLBACK_MODEL


def responses(monkeypatch, items):
    calls=[]
    def send(self, url, *, headers, json):
        calls.append(json)
        item=items.pop(0)
        if isinstance(item, Exception):
            raise item
        return httpx.Response(item[0], json=item[1])
    monkeypatch.setenv('DASHSCOPE_API_KEY','fixture-private-key')
    monkeypatch.setattr(httpx.Client,'post',send)
    return calls


QUOTA=(403,{'error':{'code':'AllocationQuota.FreeTierOnly','message':'do not expose raw response'}})
OK=(200,{'choices':[{'message':{'role':'assistant','content':'ok'},'finish_reason':'stop'}],
         'usage':{'total_tokens':12}})


def test_free_quota_exhaustion_preserves_request_and_persists_across_runs(tmp_path,monkeypatch):
    tools=[{'type':'function','function':{'name':'search_rules','parameters':{'type':'object'}}}]
    messages=[{'role':'system','content':'same mandate'},{'role':'user','content':'same request'}]
    choices=[QUOTA,OK,OK]
    calls=responses(monkeypatch,choices)
    ledger=TokenLedger(tmp_path/'usage.sqlite')
    provider=Bailian(ledger.for_run('first'))
    assert provider.chat(messages,tools,max_tokens=900)['content']=='ok'
    assert provider.model==FALLBACK_MODEL
    assert calls[1]=={**calls[0],'model':FALLBACK_MODEL}
    assert calls[1]['messages']==messages and calls[1]['tools']==tools
    restarted=Bailian(TokenLedger(ledger.path).for_run('second'))
    assert restarted.chat(messages)['content']=='ok'
    assert [x['model'] for x in calls]==[PRIMARY_MODEL,FALLBACK_MODEL,FALLBACK_MODEL]
    assert ledger.summary()['charged_or_reserved_tokens']==24
    assert ledger.summary()['models']==[FALLBACK_MODEL]
    assert ledger.for_run('first').summary(run_only=True)['last_chat_model']==FALLBACK_MODEL
    assert ledger.for_run('unknown').summary(run_only=True)['last_chat_model'] is None
    assert ledger.summary()['application_limits_enabled'] is False
    with sqlite3.connect(ledger.path) as db:
        assert db.execute('SELECT actual,status,model FROM calls ORDER BY id').fetchall()==[
            (0,'rejected',PRIMARY_MODEL),(12,'completed',FALLBACK_MODEL),(12,'completed',FALLBACK_MODEL)]
        route=json.dumps(db.execute('SELECT * FROM provider_routes').fetchall())
        assert 'fixture-private-key' not in route
    # A different credential must not inherit another account's exhausted quota.
    choices.append(OK)
    monkeypatch.setenv('DASHSCOPE_API_KEY','other-key')
    Bailian(TokenLedger(ledger.path)).chat(messages)
    assert calls[-1]['model']==PRIMARY_MODEL


@pytest.mark.parametrize('status,code',[(401,'InvalidApiKey'),(403,'AccessDenied'),
    (429,'Throttling.AllocationQuota'),(429,'BudgetLimitExceeded'),(500,'InternalError')])
def test_other_provider_errors_do_not_switch_or_retry(tmp_path,monkeypatch,status,code):
    calls=responses(monkeypatch,[(status,{'error':{'code':code,'message':'private raw text'}})])
    provider=Bailian(TokenLedger(tmp_path/'usage.sqlite'))
    with pytest.raises(RuntimeError,match=f'Provider HTTP {status}') as error:
        provider.chat([{'role':'user','content':'hello'}])
    assert 'private raw text' not in str(error.value)
    assert len(calls)==1 and provider.model==PRIMARY_MODEL


def test_network_error_does_not_pay_for_a_duplicate_request(tmp_path,monkeypatch):
    calls=responses(monkeypatch,[httpx.ReadTimeout('unknown outcome')])
    ledger=TokenLedger(tmp_path/'usage.sqlite')
    with pytest.raises(httpx.ReadTimeout): Bailian(ledger).chat([])
    assert len(calls)==1 and ledger.summary()['charged_or_reserved_tokens']>0


def test_exhausted_qwen_is_not_retried_forever(tmp_path,monkeypatch):
    calls=responses(monkeypatch,[QUOTA,QUOTA])
    with pytest.raises(RuntimeError,match='free tier exhausted'):
        Bailian(TokenLedger(tmp_path/'usage.sqlite')).chat([])
    assert len(calls)==2


def test_tool_call_response_survives_handover(tmp_path,monkeypatch):
    tool_call={'id':'call-1','type':'function','function':{'name':'search_rules','arguments':'{"query":"price"}'}}
    reply=(200,{'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[tool_call]},'finish_reason':'tool_calls'}],
                'usage':{'total_tokens':20}})
    responses(monkeypatch,[QUOTA,reply])
    message=Bailian(TokenLedger(tmp_path/'usage.sqlite')).chat([])
    assert message['tool_calls']==[tool_call] and message['_finish_reason']=='tool_calls'


def test_successful_primary_request_stays_primary_and_migrates_old_ledger(tmp_path,monkeypatch):
    path=tmp_path/'usage.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE calls (id INTEGER PRIMARY KEY,kind TEXT,reserved INTEGER,actual INTEGER,status TEXT)')
        db.execute("INSERT INTO calls VALUES(1,'old',500000,NULL,'reserved')")
    calls=responses(monkeypatch,[OK,OK])
    provider=Bailian(TokenLedger(path))
    provider.chat([]);provider.chat([])
    assert [x['model'] for x in calls]==[PRIMARY_MODEL,PRIMARY_MODEL]
    assert provider.ledger.summary()['charged_or_reserved_tokens']==500024
    assert provider.ledger.summary()['models']==[PRIMARY_MODEL]


@pytest.mark.parametrize('body',[{},[],{'error':None},{'error':{'message':'AllocationQuota.FreeTierOnly'}}])
def test_unknown_refusal_body_is_not_a_quota_signal(tmp_path,monkeypatch,body):
    calls=responses(monkeypatch,[(403,body)])
    with pytest.raises(RuntimeError,match='Provider HTTP 403'):
        Bailian(TokenLedger(tmp_path/'usage.sqlite')).chat([])
    assert len(calls)==1
