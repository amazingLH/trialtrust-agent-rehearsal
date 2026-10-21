"""Editable fixture prices must reach evidence, checks, saved runs and reviews."""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from trialtrust.catalog import CATALOG
from trialtrust.compiler import compile_stand_in
from trialtrust.scenarios import RunSpec, make_world
from trialtrust.webapp import create_app


@pytest.mark.parametrize('domain', list(CATALOG))
@pytest.mark.parametrize('case,price', [('baseline', 123), ('price_change', 167)])
def test_custom_prices_drive_both_world_and_current_evidence(domain, case, price):
    spec = RunSpec(domain=domain, quantity=3, fulfillment=CATALOG[domain]['fulfillments'][0],
                   budget_yuan=2000, case=case,
                   pricing={'unit_price':123, 'changed_unit_price':167, 'order_fee':18})
    sources, world, _ = make_world(spec)
    assert world.expected_total_cents == (price * 3 + 18) * 100
    current = next(s for s in sources if s.id == world.price_evidence_id)
    assert str(price) in current.text and '18' in current.text
    assert world.check_plan(price * 3 + 18, [world.price_evidence_id, world.cancellation_evidence_id],
                            3, spec.fulfillment)['valid']
    assert not world.check_plan(price * 3, [world.price_evidence_id, world.cancellation_evidence_id],
                                3, spec.fulfillment)['valid']


def test_large_budget_compilation_does_not_truncate_or_exceed_limit():
    for amount in (2000, 1000000):
        result = compile_stand_in(f'2人到店用餐吃自助餐，总预算{amount}元')
        assert result['proposal']['budget_yuan'] == amount
    assert compile_stand_in('2人到店用餐吃自助餐，总预算1000001元')['proposal'] is None
    with pytest.raises(ValidationError):
        RunSpec(budget_yuan=1000001)


def test_custom_price_suite_persists_reviews_and_replays_without_changing_mandate(tmp_path):
    headers = {'X-TrialTrust-Client':'web'}
    with TestClient(create_app(tmp_path/'web', enable_live=False, require_accounts=False)) as client:
        client.post('/api/session', json={}, headers=headers)
        spec = {'domain':'buffet', 'quantity':3, 'fulfillment':'dine_in', 'budget_yuan':2000,
                'pricing':{'unit_price':123, 'changed_unit_price':167, 'order_fee':18}, 'confirmed':True}
        created = client.post('/api/suites', json=spec, headers=headers)
        assert created.status_code == 202
        path = '/api/trials/' + created.json()['id']
        row = client.get(path).json()
        report = row['report']
        assert report['baseline']['drafts'][0]['total_yuan'] == 387
        assert report['changed']['drafts'][0]['total_yuan'] == 519
        assert report['baseline']['mandate']['digest'] == report['changed']['mandate']['digest']
        assert row['conditions']['pricing'] == spec['pricing']
        assert report['real_world_side_effects'] == 0
        reviewed = client.post(path+'/review', json={'accepted':True}, headers=headers)
        assert reviewed.status_code == 200
        replay = client.get(path).json()
        assert replay['status'] == 'reviewed'
        assert replay['report']['changed']['drafts'][0]['total_yuan'] == 519


@pytest.mark.parametrize('value', [-1, 1001, 1.5, True, None])
def test_invalid_simulation_prices_are_rejected(value):
    with pytest.raises(ValidationError):
        RunSpec(pricing={'unit_price':value, 'changed_unit_price':100, 'order_fee':10})
