"""The expanded picker must contain executable, unambiguous supported requests."""
from collections import Counter
from typing import get_args
import pytest
from pydantic import ValidationError
from trialtrust.catalog import CATALOG, CATEGORIES, FULFILLMENTS, Domain, public_catalog
from trialtrust.catalog_groups import GROUPS
from trialtrust.compiler import compile_stand_in
from trialtrust.scenarios import RunSpec
from trialtrust.skill_runtime import load


def test_hierarchy_has_varied_group_counts_and_distinct_executable_leaves():
    public = public_catalog()
    assert Counter(g['category'] for g in public['groups']) == {
        'attractions': 6, 'food': 7, 'travel': 8, 'life': 9}
    assert Counter(s['category'] for s in public['scenarios']) == {
        'attractions': 58, 'food': 67, 'travel': 77, 'life': 89}
    assert len(CATALOG) == len({s['label'] for s in CATALOG.values()}) == 291
    assert len({g['id'] for g in GROUPS}) == 30
    assert set(get_args(Domain)) == set(CATALOG) | {'custom'}
    group_ids = {g['id'] for g in GROUPS}
    assert all(s['group'] in group_ids for s in CATALOG.values())
    assert all(g['category'] in {c['id'] for c in CATEGORIES} for g in GROUPS)
    for group in public['groups']:
        leaves = [s for s in public['scenarios'] if s['group'] == group['id']]
        assert 8 <= len(leaves) == group['count'] <= 12
        assert all(s['category'] == group['category'] for s in leaves)


def test_old_record_ids_prices_and_delivery_modes_are_preserved():
    expected = {'museum':40, 'garden':30, 'aquarium':90, 'buffet':80,
                'teatime':60, 'picnic':45, 'citywalk':50, 'daytrip':100,
                'hotel':180, 'pottery':70, 'cleaning':90, 'organizing':120}
    for key, price in expected.items():
        assert CATALOG[key]['price'] == price
    assert CATALOG['pottery']['fulfillments'] == ['pickup', 'shipping']
    assert CATALOG['cleaning']['unit'] == '台'


def test_skill_schemas_allow_the_entire_catalog_and_keep_unknown_domains_closed():
    for name in ('mandate-review', 'evidence-retrieval'):
        fields = load(name)['input_schema']['properties']
        assert set(fields['domain']['enum']) == set(CATALOG) | {'custom'}
        if 'fulfillment' in fields:
            assert fields['fulfillment'] == {'type':'string','minLength':1,'maxLength':500}
            assert 'maximum' not in fields['quantity']
    with pytest.raises(ValidationError):
        RunSpec(domain='not-a-catalog-service')
    assert RunSpec(domain='public_transport-01', fulfillment='自由描述').fulfillment == '自由描述'


@pytest.mark.parametrize('group', GROUPS, ids=lambda g:g['id'])
def test_specific_group_choice_can_be_used_in_a_custom_brief(group):
    label = group['choices'][-1]
    key, entry = next((k, v) for k, v in CATALOG.items() if v['label'] == label)
    result = compile_stand_in(f"2{entry['unit']}，{label}，{FULFILLMENTS[entry['fulfillments'][0]]}，总预算900元")
    assert result['proposal'] is not None, result
    assert result['proposal']['domain'] == key
