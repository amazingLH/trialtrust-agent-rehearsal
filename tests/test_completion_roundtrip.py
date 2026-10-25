"""A complete example retains supplied money and works without another missing-field cycle."""
import json

import pytest

from trialtrust.request_analysis import AnalysisRequest, analyze

ORIGINAL='我明晚拿3400去北京海淀老字号店铺请我同桌去吃饭'


def field(name,value,quote,**extra): return {'field':name,'value':value,'quote':quote,**extra}


class Model:
    def __init__(self,fields=(),missing=()): self.fields,self.missing=fields,missing
    def chat(self,*a,**k): return {'role':'assistant','content':json.dumps({'summary':'请同桌吃饭','fields':self.fields,'missing':self.missing})}


def first_model(count=True):
    fields=[field('task_name','吃饭','吃饭'),field('unit','人','吃饭'),
            field('time','明晚','明晚'),field('location','北京海淀','北京海淀')]
    if count: fields.append(field('quantity',2,ORIGINAL,counted_items=['我','我同桌']))
    return Model(fields,[{'field':'fulfillment','question':'希望怎样用餐？','example_value':'到店'},
                         {'field':'budget_yuan','question':'预算是多少？','example_value':'2000元'}])


@pytest.mark.parametrize('count',[False,True])
def test_complete_example_spells_out_quantity_even_if_first_model_already_inferred_it(count):
    request=AnalysisRequest(text=ORIGINAL,reviewed=True,use_model=True)
    first=analyze(request,first_model(count))
    assert request.text==ORIGINAL and first['known_fields']['budget_yuan']==3400
    assert 'budget_yuan' not in {m['field'] for m in first['missing_fields']}
    example=first['completion_example']
    assert ORIGINAL in example or ORIGINAL.replace('吃饭','到店吃饭') in example
    assert '共2人' in example and '到店' in example
    assert '3400' in example and '2000' not in example
    assert '明晚' in example and '北京海淀' in example
    assert '具体需求：' not in example and '服务方式：' not in example
    # A later model may omit facts or ask for them again. Explicit example
    # fields still have to survive, without extra paid model calls or history.
    forgot=Model([], [{'field':name,'question':'请补充'+name} for name in
                      ['quantity','fulfillment','budget_yuan','time']])
    second=analyze(AnalysisRequest(text=example,reviewed=True,use_model=True),forgot)
    assert second['can_rehearse'] and second['missing_fields']==[]
    assert second['proposal']['quantity']==2 and second['proposal']['budget_yuan']==3400
    assert second['proposal']['fulfillment']=='到店'
    assert second['completion_example']==''


@pytest.mark.parametrize('suffix',['；服务方式：到店；总预算：2000元。','；总预算2000元；数量：2人；服务方式：到店'])
def test_conflicting_old_example_is_not_silently_accepted_or_given_a_third_budget(suffix):
    text=ORIGINAL+suffix
    first=analyze(AnalysisRequest(text=text,reviewed=True,use_model=True),first_model())
    assert not first['can_rehearse'] and first['proposal'] is None
    assert 'budget_yuan' not in first['known_fields']
    question=next(m['question'] for m in first['missing_fields'] if m['field']=='budget_yuan')
    assert '3400' in question and '2000' in question
    example=first['completion_example']
    assert example and '3400' in example and '2000' not in example
    # This is a proposed resolution only; it becomes authoritative on resubmit.
    second=analyze(AnalysisRequest(text=example,reviewed=True,use_model=True),Model())
    assert second['can_rehearse'] and second['proposal']['budget_yuan']==3400


@pytest.mark.parametrize('time',['明晚','两天内','明天下午三点'])
def test_temporal_quantity_does_not_break_a_copyable_person_count(time):
    text=ORIGINAL.replace('明晚',time)
    model=Model([field('task_name','吃饭','吃饭'),field('unit','人','吃饭')],
                [{'field':'quantity','question':'几人？','example_value':'2'},
                 {'field':'fulfillment','question':'怎样用餐？','example_value':'到店'}])
    first=analyze(AnalysisRequest(text=text,reviewed=True,use_model=True),model)
    example=first['completion_example']
    assert example and '共2人' in example and '3400' in example
    second=analyze(AnalysisRequest(text=example,reviewed=True,use_model=True),Model())
    assert second['can_rehearse'] and second['proposal']['quantity']==2


@pytest.mark.parametrize('text',['我拿3份资料去北京','我不拿3400请客','我拿2小时去整理资料'])
def test_take_expression_does_not_turn_counts_or_negations_into_money(text):
    result=analyze(AnalysisRequest(text=text,reviewed=True,use_model=True),Model())
    assert 'budget_yuan' not in result['known_fields']


def test_example_generation_does_not_turn_suggested_conditions_into_current_facts():
    result=analyze(AnalysisRequest(text=ORIGINAL,reviewed=True,use_model=True),first_model(False))
    assert not result['can_rehearse'] and 'quantity' not in result['known_fields']
    assert result['proposal'] is None and '共2人' in result['completion_example']


def test_rule_only_catalog_shortcut_cannot_hide_conflicting_money():
    result=analyze(AnalysisRequest(text='2人自助餐，到店用餐，拿3400，预算2000',reviewed=True))
    assert result['proposal'] is None and not result['can_rehearse']
    assert any(item['field']=='budget_yuan' for item in result['missing_fields'])


def test_shopping_example_is_one_copyable_sentence_without_repeated_fields():
    text='10月30号下午我和小明去沈阳中街花1200逛街买裙子'
    model=Model([field('task_name','逛街买裙子','逛街买裙子'),
                 field('quantity',2,'我和小明',counted_items=['我','小明']),
                 field('unit','人','我和小明'),field('location','沈阳中街','沈阳中街')],
                [{'field':'fulfillment','question':'你希望怎样服务或交付？','example_value':'到店'}])
    first=analyze(AnalysisRequest(text=text,reviewed=True,use_model=True),model)
    example=first['completion_example']
    assert example=='10月30号下午我和小明共2人去沈阳中街花1200逛街买裙子，希望到店。'
    for value in ['10月30号下午','沈阳中街','1200','逛街买裙子']:
        assert example.count(value)==1
    for label in ['具体需求：','数量：','服务方式：','总预算：','完成时间：','地点：']:
        assert label not in example
    assert first['proposal'] is None and 'fulfillment' not in first['known_fields']
    completed=analyze(AnalysisRequest(text=example,reviewed=True,use_model=True),Model())
    assert completed['can_rehearse'] and completed['proposal']['quantity']==2
    assert completed['proposal']['budget_yuan']==1200


def test_existing_explicit_conditions_are_converted_to_prose_without_being_lost():
    text='我想买裙子；数量：2人；完成时间：明晚；地点：沈阳中街；总预算：1200元；具体要求：红色、不要蕾丝'
    first=analyze(AnalysisRequest(text=text,reviewed=True,use_model=True),Model())
    example=first['completion_example']
    assert example and '红色、不要蕾丝' in example and '沈阳中街' in example
    assert '1200元' in example and '明晚' in example and '共2人' in example
    assert '；数量：' not in example and '；具体要求：' not in example
    assert analyze(AnalysisRequest(text=example,reviewed=True,use_model=True),Model())['can_rehearse']


def test_grounded_service_already_in_the_request_is_not_repeated_in_the_example():
    text='我和小明准备去沈阳中街花1200逛街买裙子'
    service='去沈阳中街花1200逛街买裙子'
    model=Model([field('task_name','逛街买裙子','逛街买裙子'),
                 field('quantity',2,'我和小明',counted_items=['我','小明']),
                 field('unit','人','我和小明'),field('fulfillment',service,service)],
                [{'field':'time','question':'什么时间去？','example_value':'明天下午'}])
    result=analyze(AnalysisRequest(text=text,reviewed=True,use_model=True),model)
    assert result['completion_example']=='我和小明共2人准备去沈阳中街花1200逛街买裙子，时间定在明天下午。'
    assert result['completion_example'].count(service)==1
    assert 'time' not in result['known_fields'] and result['proposal'] is None
