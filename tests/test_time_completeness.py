"""Time completeness follows the current text, even when a model forgets to ask."""
import json

import pytest
from fastapi.testclient import TestClient

from trialtrust.provider import Bailian
from trialtrust.request_analysis import AnalysisRequest, analyze
from trialtrust.webapp import create_app

ORIGINAL='我拿出2500请客刘总去东莞捏个脚'
TIMED='我明晚拿出2500请客刘总去东莞捏个脚'


def model_reply(text, stale_time=False):
    # Explicit participants, service and city; model deliberately omits time checks.
    fields=[{'field':'task_name','value':'捏个脚','quote':'捏个脚'},
            {'field':'quantity','value':2,'quote':text,'counted_items':['我','刘总']},
            {'field':'unit','value':'人','quote':'捏个脚'},
            {'field':'fulfillment','value':'去东莞捏个脚','quote':'去东莞捏个脚'},
            {'field':'location','value':'东莞','quote':'东莞'}]
    if stale_time: fields.append({'field':'time','value':'明晚','quote':'明晚'})
    return {'role':'assistant','content':json.dumps({'summary':'足疗需求','fields':fields,'missing':[]})}


class Model:
    def __init__(self, text, stale_time=False): self.text,self.stale_time=text,stale_time
    def chat(self, messages, **kwargs): return model_reply(self.text,self.stale_time)


def check(text,stale_time=False):
    return analyze(AnalysisRequest(text=text,reviewed=True,use_model=True),Model(text,stale_time))


def test_remove_time_after_a_valid_request_requires_time_again_every_time():
    for text in [ORIGINAL,TIMED,ORIGINAL,ORIGINAL]:
        result=check(text,stale_time=True)
        assert result['known_fields']['budget_yuan']==2500
        if text==TIMED:
            assert result['can_rehearse']
            assert '时间：明晚' in result['proposal']['custom_task']['context']
        else:
            assert not result['can_rehearse'] and result['proposal'] is None
            assert 'time' not in result['known_fields']
            assert [m['field'] for m in result['missing_fields']]==['time']
            assert '时间不限' in result['questions'][0]
            assert result['completion_example'].startswith(ORIGINAL+'，')
            assert '时间不限' in result['completion_example']
            assert '共2人' in result['completion_example']


@pytest.mark.parametrize('time',['明晚','明天下午','周六晚上','下周一','2026-10-28','10月28日','下午三点','18:30','两天内','时间不限','随时','没有时间要求'])
def test_literal_time_and_explicit_no_preference_work_even_if_model_omits_time(time):
    result=check(ORIGINAL+'；'+time)
    assert result['can_rehearse'] and 'time' in result['known_fields']
    assert all(m['field']!='time' for m in result['missing_fields'])


@pytest.mark.parametrize('time',['时间：待定','时间：还没想好','完成时间：【填写：例如明晚】','不是明晚'])
def test_unknown_negated_or_template_time_is_not_a_completed_condition(time):
    result=check(ORIGINAL+'；'+time)
    assert not result['can_rehearse'] and 'time' not in result['known_fields']
    assert any(m['field']=='time' for m in result['missing_fields'])


def test_model_can_understand_event_relative_time_without_a_keyword_whitelist():
    text=ORIGINAL+'；演出结束后去'
    class EventTime:
        def chat(self,messages,**kwargs):
            reply=model_reply(text)
            data=json.loads(reply['content'])
            data['fields'].append({'field':'time','value':'演出结束后','quote':'演出结束后去'})
            return {**reply,'content':json.dumps(data)}
    result=analyze(AnalysisRequest(text=text,reviewed=True,use_model=True),EventTime())
    assert result['can_rehearse']
    assert '时间：演出结束后' in result['proposal']['custom_task']['context']


def test_same_session_api_does_not_carry_time_between_requests(tmp_path,monkeypatch):
    def chat(self,messages,**kwargs):
        current=json.loads(messages[1]['content'])['request']
        return model_reply(current,stale_time=True)
    monkeypatch.setattr(Bailian,'chat',chat)
    headers={'X-TrialTrust-Client':'web'}
    with TestClient(create_app(tmp_path/'web',enable_live=True,require_accounts=False)) as client:
        client.post('/api/session',json={},headers=headers)
        for text in [ORIGINAL,TIMED,ORIGINAL]:
            response=client.post('/api/analyze',json={'text':text,'reviewed':True,'use_model':True},headers=headers)
            assert response.status_code==200
            result=response.json()
            assert result['can_rehearse']==(text==TIMED)
            if text==ORIGINAL:
                assert [m['field'] for m in result['missing_fields']]==['time']
                assert result['proposal'] is None
