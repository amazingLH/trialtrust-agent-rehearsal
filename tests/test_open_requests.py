"""Requests outside the catalog stay grounded and can use a custom mandate."""
import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from trialtrust.mandate import Mandate
from trialtrust.provider import TokenLedger
from trialtrust.request_analysis import AnalysisRequest, analyze
from trialtrust.scenarios import RunSpec, make_world
from trialtrust.suite import run_suite
from trialtrust.webapp import create_app


class Response:
    def __init__(self, fields, missing=()): self.fields,self.missing=fields,missing
    def chat(self, messages, **kwargs):
        assert '不限' in messages[0]['content']
        return {'role':'assistant','content':json.dumps({'summary':'理解用户的需求','fields':self.fields,'missing':self.missing},ensure_ascii=False)}


def field(key,value,quote): return {'field':key,'value':value,'quote':quote}


def test_shoe_request_preserves_budget_without_reasking_known_fields():
    model=Response([field('task_name','刷鞋服务','刷鞋'),field('unit','双','刷鞋')],
                   [{'field':'budget_yuan','question':'预算是多少？'}, {'field':'task_name','question':'需要哪种服务？'},
                    {'field':'location','question':'希望在哪个城市找刷鞋店？'}, {'field':'quantity','question':'需要清洗几双鞋？'},
                    {'field':'details','question':'鞋子是什么类型和材质？'}])
    result=analyze(AnalysisRequest(text='找个刷鞋的店，预算350',reviewed=True,use_model=True),model)
    assert result['known_fields']['budget_yuan']==350
    assert '刷鞋' in result['summary'] and '350' in result['summary']
    assert all(m['field'] not in {'task_name','budget_yuan'} for m in result['missing_fields'])
    assert '预算350' in result['rewrite_example'] and '【填写城市或区域】' in result['rewrite_example']
    assert '【填写数量】双' in result['rewrite_example']
    assert not result['can_rehearse']


@pytest.mark.parametrize('name,unit',[('留声机唱针校准','台'),('旧照片数字化','张'),('水族箱换水','次'),('远程编曲混音','项')])
def test_unlisted_goals_are_not_gated_by_catalog_names(name,unit):
    text=f'{name}，数量：2{unit}，服务方式：按需求交付，总预算350'
    model=Response([field('task_name',name,name),field('unit',unit,f'2{unit}'),field('fulfillment','按需求交付','按需求交付')])
    result=analyze(AnalysisRequest(text=text,reviewed=True,use_model=True),model)
    assert result['can_rehearse'] and result['proposal']['domain']=='custom'
    assert result['proposal']['custom_task']['name']==name
    assert result['proposal']['custom_task']['unit']==unit
    assert result['proposal']['quantity']==2 and result['proposal']['budget_yuan']==350


def test_fabricated_fields_cannot_replace_user_budget_goal_or_location():
    model=Response([field('task_name','陶艺','刷鞋'),field('budget_yuan',900,'预算350'),
                    field('quantity',2,'原文没有这句话'),field('location','杭州','预算350')],
                   [{'field':'location','question':'希望在哪个城市？'}])
    result=analyze(AnalysisRequest(text='找个刷鞋的店，预算350',reviewed=True,use_model=True),model)
    assert result['known_fields']['task_name']=='刷鞋'
    assert result['known_fields']['budget_yuan']==350
    assert 'quantity' not in result['known_fields'] and 'location' not in result['known_fields']
    assert not result['can_rehearse']


def test_chinese_numbers_and_all_grounded_details_are_preserved():
    text='刷鞋，两双运动鞋，预算三百五十元；服务方式：到店送洗；地点：测试城区；时间：周六；不要漂白'
    model=Response([field('task_name','刷鞋','刷鞋'),field('quantity',2,'两双'),field('unit','双','两双'),
                    field('budget_yuan',350,'预算三百五十元'),field('details','运动鞋','运动鞋'),field('details','不要漂白','不要漂白')])
    result=analyze(AnalysisRequest(text=text,reviewed=True,use_model=True),model)
    assert result['can_rehearse']
    task=result['proposal']['custom_task']
    assert '具体要求：运动鞋；不要漂白' in task['context']
    assert '地点：测试城区' in task['context'] and '时间：周六' in task['context']


def test_unfilled_rewrite_placeholders_are_not_actual_conditions():
    text='刷鞋，预算350；数量：【填写数量】双；服务方式：【填写服务方式】'
    result=analyze(AnalysisRequest(text=text,reviewed=True))
    assert not result['can_rehearse']
    assert {'quantity','fulfillment'} <= {m['field'] for m in result['missing_fields']}


@pytest.mark.parametrize('use_model',[False,True])
@pytest.mark.parametrize('location',['地点上海青浦区','地点是上海青浦区','地点在上海青浦区','地点：上海青浦区','在上海青浦区','上海青浦区'])
@pytest.mark.parametrize('quantity',['3个人','三个人'])
def test_natural_conditions_survive_analysis_without_reasking(use_model,location,quantity):
    text=f'找一家洗店我要泡澡，一共{quantity}，{location}，总共预算1200，到时候我到店；具体要求：无；完成时间：时间不限。'
    model=Response([], [{'field':key,'question':question} for key,question in
                        [('quantity','几个人？'),('location','在哪个区域？'),('budget_yuan','预算多少？')]]) if use_model else None
    result=analyze(AnalysisRequest(text=text,reviewed=True,use_model=use_model),model)
    assert result['missing_fields']==[]
    assert result['can_rehearse']
    assert result['proposal']['quantity']==3
    assert result['proposal']['budget_yuan']==1200
    assert result['proposal']['fulfillment']=='到店'
    assert '地点：上海青浦区' in result['proposal']['custom_task']['context']
    assert '时间：时间不限' in result['proposal']['custom_task']['context']


def test_empty_location_hint_does_not_hide_a_later_supplied_location():
    text='找泡澡店；地点：【填写城市或区域】；地点上海青浦区；3个人；预算1200；到店；具体要求：无；完成时间：时间不限。'
    result=analyze(AnalysisRequest(text=text,reviewed=True))
    assert result['known_fields']['location']=='上海青浦区'


def custom_spec():
    return {'domain':'custom','custom_task':{'name':'刷鞋','unit':'双','context':['地点：测试城区','具体要求：运动鞋，不漂白']},
            'quantity':2,'fulfillment':'到店送洗','budget_yuan':350,'comparison_case':'price_change',
            'pricing':{'unit_price':100,'changed_unit_price':200,'order_fee':10},'confirmed':True}


def test_custom_plan_requires_its_own_confirmed_pricing_and_contract():
    spec=custom_spec()
    with pytest.raises(ValidationError): RunSpec(**{k:v for k,v in spec.items() if k!='pricing'})
    with pytest.raises(ValidationError): RunSpec(**{k:v for k,v in spec.items() if k!='custom_task'})
    original=RunSpec(**spec).mandate()
    altered=RunSpec(**{**spec,'custom_task':{**spec['custom_task'],'context':['允许漂白']}}).mandate()
    assert original.digest!=altered.digest
    _,world,task=make_world(RunSpec(**spec))
    assert '刷鞋' in task and '不漂白' in task
    assert world.execute('create_booking',{},None)['allowed'] is False


def test_catalog_mandate_digest_is_unchanged_for_historical_records():
    old={'version':'mandate-v1','domain':'pottery','quantity':4,'fulfillment':'pickup','budget_yuan':300,
         'allowed_actions':['search_rules','check_plan','submit_draft'],'required_evidence':['price','cancellation']}
    assert Mandate().digest==hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest()


def test_custom_api_suite_preserves_name_units_context_history_and_review(tmp_path):
    headers={'X-TrialTrust-Client':'web'}
    with TestClient(create_app(tmp_path/'web',enable_live=False,require_accounts=False)) as client:
        client.post('/api/session',json={},headers=headers)
        conversation=client.post('/api/conversations',json={},headers=headers).json()['id']
        headers['X-TrialTrust-Conversation']=conversation
        spec=custom_spec()
        assert client.post('/api/suites',json={**spec,'confirmed':False},headers=headers).status_code==409
        started=client.post('/api/suites',json=spec,headers=headers)
        assert started.status_code==202,started.text
        path='/api/trials/'+started.json()['id']
        row=client.get(path).json()
        assert row['conditions']['custom_task']==spec['custom_task']
        report=row['report']
        assert report['baseline']['drafts'][0]['total_yuan']==210
        assert not report['changed']['drafts']
        assert report['baseline']['mandate']['custom_task']==spec['custom_task']
        assert report['comparison']['same_mandate']
        assert client.post(path+'/review',json={'accepted':False},headers=headers).status_code==200
        assert client.get(path+'/export').json()['mandate']['custom_task']==spec['custom_task']
        assert client.get('/api/conversations').json()[0]['title']=='刷鞋'


def test_missing_question_supplies_unit_and_example_uses_task_hint():
    model=Response([field('task_name','刷鞋','刷鞋')], [
        {'field':'quantity','question':'需要刷几双鞋？'},
        {'field':'details','question':'鞋子是什么类型和材质？','example_hint':'鞋子类型、材质和清洗要求'}])
    result=analyze(AnalysisRequest(text='找个刷鞋的店，预算350',reviewed=True,use_model=True),model)
    assert result['known_fields']['unit']=='双'
    assert '【填写数量】双' in result['rewrite_example']
    assert '【填写：鞋子类型、材质和清洗要求】' in result['rewrite_example']
    assert all(m['field']!='unit' for m in result['missing_fields'])


@pytest.mark.parametrize('use_model',[False,True])
def test_comma_separated_labeled_details_are_never_dropped(use_model):
    text='刷鞋，预算350；数量：2双；具体要求：运动鞋基础清洗，不漂白；服务方式：到店送洗'
    model=Response([field('details','运动鞋基础清洗','运动鞋基础清洗')]) if use_model else None
    result=analyze(AnalysisRequest(text=text,reviewed=True,use_model=use_model),model)
    assert result['can_rehearse']
    assert any('运动鞋基础清洗，不漂白' in value for value in result['proposal']['custom_task']['context'])
