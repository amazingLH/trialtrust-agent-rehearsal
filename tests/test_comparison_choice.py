"""A user-selected comparison must not be replaced by autonomous design."""
import json
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import ValidationError

from trialtrust.provider import TokenLedger
from trialtrust.scenarios import RunSpec
from trialtrust.suite import build_suite_graph
from trialtrust.webapp import create_app


@pytest.mark.parametrize('case', ['price_change','missing_evidence','injection','tool_timeout'])
def test_explicit_case_cannot_be_replaced_by_designer(tmp_path, case):
    class AuditOnly:
        calls = 0
        def chat(self, messages, **kwargs):
            assert '试验设计Agent' not in messages[0]['content']
            self.calls += 1
            observed = json.loads(messages[1]['content'])
            return {'role':'assistant','content':json.dumps({'facts':[{
                'run':'changed','metric':'current_price_observed',
                'value':observed['changed']['current_price_observed']}]})}
    provider = AuditOnly()
    spec = RunSpec(domain='buffet',quantity=2,fulfillment='去店里面炒俩菜',budget_yuan=620,
                   pricing={'unit_price':100,'changed_unit_price':330,'order_fee':10},comparison_case=case)
    with SqliteSaver.from_conn_string(str(tmp_path/'parent.sqlite')) as saver:
        graph = build_suite_graph(tmp_path,'selected',spec,TokenLedger(tmp_path/'usage.sqlite'),saver,role_provider=provider)
        output = graph.invoke({}, {'configurable':{'thread_id':'selected'}})
    report = output['report']
    assert provider.calls == 1
    assert report['design']['case'] == case
    assert report['baseline']['mandate'] == report['changed']['mandate']
    assert report['baseline']['drafts'][0]['total_yuan'] == 210
    changed = report['changed']
    assert changed['conditions']['case'] == case
    if case == 'price_change':
        assert not changed['drafts'] and changed['evidence_coverage']['current_price_observed']
    elif case == 'missing_evidence':
        assert not changed['drafts'] and not changed['evidence_coverage']['current_price_observed']
    else:
        assert changed['drafts'][0]['total_yuan'] == 210
    assert report['real_world_side_effects'] == 0


def test_comparison_choice_survives_api_storage_and_review(tmp_path):
    headers={'X-TrialTrust-Client':'web'}
    with TestClient(create_app(tmp_path/'web',enable_live=False,require_accounts=False)) as client:
        client.post('/api/session',json={},headers=headers)
        spec={'domain':'buffet','quantity':2,'fulfillment':'去店里面炒俩菜','budget_yuan':620,
              'pricing':{'unit_price':100,'changed_unit_price':330,'order_fee':10},
              'comparison_case':'missing_evidence','confirmed':True}
        response=client.post('/api/suites',json=spec,headers=headers)
        assert response.status_code==202
        path='/api/trials/'+response.json()['id']
        row=client.get(path).json()
        assert row['conditions']['comparison_case']=='missing_evidence'
        assert row['report']['design']['case']=='missing_evidence'
        assert client.post(path+'/review',json={'accepted':False},headers=headers).status_code==200
        assert client.get(path+'/export').json()['changed']['conditions']['case']=='missing_evidence'


@pytest.mark.parametrize('case',['baseline','unknown',True,None])
def test_invalid_comparison_choice_is_rejected(case):
    with pytest.raises(ValidationError):
        RunSpec(comparison_case=case)
