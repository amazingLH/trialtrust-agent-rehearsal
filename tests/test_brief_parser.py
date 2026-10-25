"""Model-format variations never change facts, authorization or error privacy."""
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from trialtrust.brief_parser import BriefFormatError
from trialtrust.mandate import Mandate
from trialtrust.provider import Bailian
from trialtrust.request_analysis import AnalysisRequest, ModelBrief, analyze, decode_brief
from trialtrust.webapp import create_app

TEXT='我出2400今天晚上请老板去北京海淀区洗脚'


def brief():
    return {'summary':'洗脚需求','fields':[
        {'field':'task_name','value':'洗脚','quote':'洗脚'},
        {'field':'quantity','value':2,'quote':TEXT,'counted_items':['我','老板'],'unit':'人'},
        {'field':'fulfillment','value':'去北京海淀区洗脚','quote':'去北京海淀区洗脚'},
        {'field':'location','value':'北京海淀区','quote':'北京海淀区'},
        {'field':'time','value':'今天晚上','quote':'今天晚上'}], 'missing':[]}


class Model:
    def __init__(self,data): self.data=data; self.calls=0
    def chat(self,messages,**kwargs):
        self.calls+=1
        return {'role':'assistant','content':self.data if isinstance(self.data,str) else json.dumps(self.data,ensure_ascii=False)}


@pytest.mark.parametrize('variant',['extra_unit','metadata','null_arrays','numeric_string','value_with_unit','member_string','member_json','code_fence','field_map'])
def test_benign_format_variations_keep_the_exact_request_working(variant):
    data=brief()
    if variant=='metadata':
        data.update(confidence=0.95,explanation='auxiliary text')
        for item in data['fields']: item['confidence']=0.9
    if variant=='null_arrays':
        data['missing']=None
        for item in data['fields']:
            if item['field']!='quantity': item['counted_items']=None
    if variant=='numeric_string': data['fields'][1]['value']='2'
    if variant=='value_with_unit': data['fields'][1]['value']='2人'
    if variant=='member_string': data['fields'][1]['counted_items']='我、老板'
    if variant=='member_json': data['fields'][1]['counted_items']='["我","老板"]'
    if variant=='field_map': data['fields']={item['field']:{k:v for k,v in item.items() if k!='field'} for item in data['fields']}
    if variant=='code_fence': data='```json\n'+json.dumps(data,ensure_ascii=False)+'\n```'
    provider=Model(data)
    body=AnalysisRequest(text=TEXT,reviewed=True,use_model=True)
    result=analyze(body,provider)
    assert provider.calls==1 and body.text==TEXT
    assert result['can_rehearse'] and result['proposal']['quantity']==2
    assert result['proposal']['budget_yuan']==2400
    assert result['proposal']['custom_task']['unit']=='人'
    assert result['known_fields']['time']=='今天晚上'
    assert Mandate.model_validate(result['proposal']).record()['allowed_actions']==['search_rules','check_plan','submit_draft']


def test_invalid_auxiliary_fields_never_grant_authority_or_replace_grounded_facts():
    data=brief()
    data.update(budget_yuan=999999,allowed_actions=['create_booking'],can_rehearse=True)
    data['fields'] += [{'field':'budget_yuan','value':999999,'quote':'出2400'},
                       {'field':'quantity','value':True,'quote':TEXT},
                       {'field':'allowed_actions','value':'create_booking','quote':TEXT},
                       {'field':'location','value':'上海','quote':'北京海淀区'},
                       {'field':'time','value':'明晚','quote':'明晚'}]
    result=analyze(AnalysisRequest(text=TEXT,reviewed=True,use_model=True),Model(data))
    assert result['proposal']['budget_yuan']==2400 and result['proposal']['quantity']==2
    assert result['known_fields']['location']=='北京海淀区'
    assert result['known_fields']['time']=='今天晚上'
    assert 'create_booking' not in json.dumps(result['proposal'])


def test_missing_members_or_bad_count_is_still_a_missing_condition():
    for members in [None,['我','不存在的人'],['我'],['我','我']]:
        data=brief(); data['fields'][1]['counted_items']=members
        result=analyze(AnalysisRequest(text=TEXT,reviewed=True,use_model=True),Model(data))
        assert not result['can_rehearse'] and result['proposal'] is None
        assert any(item['field']=='quantity' for item in result['missing_fields'])


def test_missing_time_is_not_repaired_by_metadata_or_a_previous_quote():
    data=brief(); data['fields']=[item for item in data['fields'] if item['field']!='time']
    data['time']='今天晚上'
    result=analyze(AnalysisRequest(text=TEXT.replace('今天晚上',''),reviewed=True,use_model=True),Model(data))
    assert not result['can_rehearse'] and 'time' not in result['known_fields']
    assert any(item['field']=='time' for item in result['missing_fields'])


@pytest.mark.parametrize('content',['not json','[]','{}','{"summary":"xx","fields":"bad"}',
    '{"summary":"xx","fields":[{"field":"quantity","value":2}]}',
    '{"summary":"xx","fields":{"quantity":2}}',
    '{"summary":"xx","fields":[],"fields":[]}',
    '{"summary":"xx","missing":[{"field":"garbage","question":"unknown"}]}'])
def test_unreadable_or_fully_invalid_briefs_fail_closed_with_safe_errors(content):
    with pytest.raises(BriefFormatError) as error: decode_brief(content)
    assert 'ModelBrief' not in str(error.value) and 'pydantic' not in str(error.value)
    assert content not in str(error.value)


def test_missing_maps_and_null_optional_hints_are_normalized():
    data=brief(); data['missing']={'details':{'question':'要清洗什么材质？','example_hint':None,'example_value':None}}
    parsed=decode_brief(json.dumps(data))
    assert parsed.missing[0].example_hint==''
    data['missing']={'details':'要清洗什么材质？'}
    assert decode_brief(json.dumps(data)).missing[0].field=='details'


def test_successful_api_request_accepts_the_reported_extra_unit(monkeypatch,tmp_path):
    monkeypatch.setattr(Bailian,'chat',lambda self,*a,**k:Model(brief()).chat(*a,**k))
    with TestClient(create_app(tmp_path/'web',enable_live=True,require_accounts=False)) as client:
        headers={'X-TrialTrust-Client':'web'};client.post('/api/session',json={},headers=headers)
        response=client.post('/api/analyze',json={'text':TEXT,'reviewed':True,'use_model':True},headers=headers)
        assert response.status_code==200 and response.json()['can_rehearse']
        assert 'extra_forbidden' not in response.text


@pytest.mark.parametrize('failure',['bad_json','schema','unexpected_value'])
def test_api_never_leaks_internal_model_validation_details(monkeypatch,tmp_path,failure):
    def chat(self,*a,**k):
        if failure=='schema': ModelBrief.model_validate({'summary':'SECRET_MODEL_CONTENT','fields':[{'unit':'人'}]})
        if failure=='unexpected_value': raise ValueError('SECRET_PROVIDER_TEXT https://errors.pydantic.dev/')
        return {'role':'assistant','content':'SECRET_BROKEN_JSON'}
    monkeypatch.setattr(Bailian,'chat',chat)
    with TestClient(create_app(tmp_path/'web',enable_live=True,require_accounts=False)) as client:
        headers={'X-TrialTrust-Client':'web'};client.post('/api/session',json={},headers=headers)
        response=client.post('/api/analyze',json={'text':TEXT,'reviewed':True,'use_model':True},headers=headers)
        assert response.status_code==502
        assert response.json()=={'detail':'需求检查暂未完成，请稍后重试。'}
        assert all(text not in response.text for text in ['SECRET','ModelBrief','pydantic','extra_forbidden','input_value'])


def test_public_request_schema_remains_strict():
    with pytest.raises(ValidationError): AnalysisRequest(text=TEXT,reviewed=True,use_model=True,unit='人')
