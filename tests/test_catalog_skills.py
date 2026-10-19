# These regressions exercise the explicitly enabled legacy anonymous migration mode.
# The deployed factories default to accounts; tests/test_accounts.py covers that boundary.
"""v0.5 domain, skill-gate and custom-brief regressions; no live model calls."""
import json
import pytest
from fastapi.testclient import TestClient
from jsonschema.exceptions import ValidationError
from trialtrust.catalog import CATALOG, public_catalog
from trialtrust.scenarios import RunSpec, make_world
from trialtrust.cli import run_trial
from trialtrust.request_analysis import AnalysisRequest, analyze
from trialtrust.skill_runtime import discover, load, invoke, instructions_for
from trialtrust.webapp import create_app

@pytest.mark.parametrize('domain', list(CATALOG))
@pytest.mark.parametrize('case', ['baseline','price_change','missing_evidence','injection','tool_timeout'])
def test_every_catalog_domain_runs_with_its_own_evidence(tmp_path,domain,case):
    entry=CATALOG[domain]
    spec=RunSpec(domain=domain,quantity=2,fulfillment=entry['fulfillments'][0],budget_yuan=1000,case=case,confirmed=True)
    report=run_trial(tmp_path, spec=spec)
    assert report['mandate']['domain']==domain
    assert report['real_world_side_effects']==0
    assert report['termination']=='model_finished'
    assert bool(report['drafts']) == (case!='missing_evidence')
    assert {'mandate-review','evidence-retrieval'} <= {e['skill_id'] for e in report['skill_events']}
    if report['drafts']:
        price=entry['changed_price'] if case=='price_change' else entry['price']
        assert report['drafts'][0]['total_yuan']==price*2+entry['fee']
        assert 'plan-verification' in {e['skill_id'] for e in report['skill_events']}


def test_trusted_skills_refuse_unknown_and_ungranted_execution():
    assert len(discover())==5
    assert all('instructions' not in s for s in discover())
    assert '委托' in instructions_for(['mandate-review'])
    for name in ['../evil','untrusted','https://example.org/code']:
        with pytest.raises(ValueError): load(name)
    called=[]
    with pytest.raises(PermissionError):
        invoke('request-analysis',{},lambda *a:called.append(True),granted={'analyze_text'},required={'model_call'})
    assert called==[]
    with pytest.raises(PermissionError):
        invoke('mandate-review',{},lambda *a:called.append(True),granted=set(),required=set())
    with pytest.raises(ValidationError):
        invoke('request-analysis',{'text':1},lambda *a:{},granted={'analyze_text'},required={'analyze_text'})
    with pytest.raises(ValidationError):
        invoke('mandate-review',{'domain':'pottery','quantity':2,'fulfillment':'pickup','budget_yuan':300},lambda *a:{'allowed_actions':[]},granted={'read_conditions'},required={'read_conditions'})
    output,event=invoke('mandate-review',{'domain':'pottery','quantity':2,'fulfillment':'pickup','budget_yuan':300},lambda *a:{'digest':'fixed','allowed_actions':[]},granted={'read_conditions'},required={'read_conditions'})
    assert event['status']=='completed' and event['manifest_digest']==load('mandate-review')['digest']
    assert len(event['input_digest'])==len(event['output_digest'])==64

@pytest.mark.parametrize('text', ['帮我比较三家宠物托管，预算300元','2人到店用餐，总预算200元','2人去自助餐和博物馆，到场，总预算200元','2台自助餐，到店用餐，总预算200元'])
def test_unsupported_or_ambiguous_text_never_silently_maps_to_a_domain(text):
    result=analyze(AnalysisRequest(text=text,reviewed=True))
    assert not result['can_rehearse'] and result['proposal'] is None
    assert result['questions'] and result['evidence_needed']
    assert result['skill_events'][0]['skill_id']=='request-analysis'


def test_custom_brief_needs_consent_and_blocks_recognizable_identifiers():
    with pytest.raises(ValueError): analyze(AnalysisRequest(text='帮我去自助餐'))
    with pytest.raises(ValueError): analyze(AnalysisRequest(text='联系13800138000去自助餐',reviewed=True))
    result=analyze(AnalysisRequest(text='2人到店用餐吃自助餐，总预算200元，不能吃辣',reviewed=True))
    assert result['proposal']=={'domain':'buffet','quantity':2,'fulfillment':'dine_in','budget_yuan':200}
    assert '不能吃辣' in result['unmodeled_fragments']
    assert result['mode']=='explicit_rules'


def test_analysis_model_cannot_create_unsupported_rehearsal():
    class Fake:
        def chat(self,messages,tools=None,**kwargs):
            assert '需求' in messages[0]['content']
            return {'role':'assistant','content':json.dumps({'summary':'仍需提供真实商家规则','questions':['选择哪一家？'],'next_actions':['补充证据后再确认']},ensure_ascii=False)}
    result=analyze(AnalysisRequest(text='帮我选择宠物托管，预算300元',reviewed=True,use_model=True),Fake())
    assert result['mode']=='live_llm' and result['proposal'] is None
    assert result['skill_events'][0]['capabilities_used']==['analyze_text','model_call']


def test_new_endpoints_and_confirmed_false_after_prior_success(tmp_path):
    headers={'X-TrialTrust-Client':'web'}
    with TestClient(create_app(tmp_path/'web',enable_live=False, require_accounts=False)) as client:
        assert len(client.get('/api/catalog').json()['scenarios'])==12
        assert len(client.get('/api/skills').json()['skills'])==5
        body={'text':'2人到店用餐吃自助餐，总预算200元','reviewed':True,'use_model':False}
        assert client.post('/api/analyze',headers=headers,json=body).status_code==401
        client.post('/api/session',headers=headers,json={})
        assert client.post('/api/analyze',headers=headers,json={**body,'reviewed':False}).status_code==422
        assert client.post('/api/analyze',headers=headers,json={**body,'use_model':True}).status_code==403
        assert client.post('/api/analyze',headers=headers,json=body).json()['proposal']['domain']=='buffet'
        spec={'domain':'buffet','quantity':2,'fulfillment':'dine_in','budget_yuan':200,'confirmed':False}
        assert client.post('/api/trials',headers=headers,json=spec).status_code==409
        response=client.post('/api/trials',headers=headers,json={**spec,'confirmed':True})
        assert response.status_code==202
        row=client.get('/api/trials/'+response.json()['id']).json()
        assert row['report']['drafts'][0]['total_yuan']==170
        assert client.post('/api/trials',headers=headers,json=spec).status_code==409
        assert client.post('/api/suites',headers=headers,json=spec).status_code==409
        # Historical review / export never turns an unchecked new request into authority.
        client.post('/api/trials/'+row['id']+'/review',headers=headers,json={'accepted':False})
        assert client.post('/api/trials',headers=headers,json=spec).status_code==409


def test_skill_events_survive_snapshot_without_repeating_mandate_review():
    from trialtrust.retrieval import EvidenceIndex
    spec=RunSpec(domain='museum',quantity=2,fulfillment='entry',confirmed=True)
    sources,world,_=make_world(spec)
    index=EvidenceIndex(sources)
    world.execute('search_rules',{'query':'价格 退改 授权'},index)
    restored=world.restored(world.snapshot())
    restored.execute('search_rules',{'query':'当前价目'},index)
    assert [e['skill_id'] for e in restored.skill_events].count('mandate-review')==1
    assert [e['skill_id'] for e in restored.skill_events].count('evidence-retrieval')==2
    assert restored.seen_evidence >= world.seen_evidence
    assert len(world.skill_events)==2


def test_live_executor_receives_the_loaded_skill_instructions(tmp_path,monkeypatch):
    from trialtrust import cli
    from trialtrust.scenarios import DemoAgent
    spec=RunSpec(domain='museum',quantity=2,fulfillment='entry',budget_yuan=100,agent='live',confirmed=True)
    prompts=[]
    class Fake(DemoAgent):
        model='local_fake_for_instruction_test'
        def __init__(self,ledger): super().__init__(spec.model_copy(update={'agent':'demo_careful'}))
        def chat(self,messages,tools=None):
            prompts.append(messages[0]['content'])
            return super().chat(messages,tools)
    monkeypatch.setattr(cli,'Bailian',Fake)
    report=cli.run_trial(tmp_path,spec=spec)
    assert report['drafts'][0]['total_yuan']==80
    for name in ['mandate-review','evidence-retrieval','plan-verification']:
        assert load(name)['instructions'] in prompts[0]
    assert len(report['execution_metadata']['skill_hashes'])==10
