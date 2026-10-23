"""Open-ended extraction with quoted evidence and explicit confirmation."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .compiler import compile_stand_in
from .catalog import CATALOG, MAX_BUDGET_YUAN
from .mandate import CustomTask, Mandate
from .skill_runtime import invoke

FieldName = Literal['task_name','quantity','unit','fulfillment','budget_yuan','location','time','details']
NUM = r'[0-9]+|[零〇一二两三四五六七八九十百千万]+'
UNITS = r'双|只|件|份|人|台|间|次|天|小时|项|辆|本|张|套|位|名'
PLACEHOLDER = re.compile(r'【[^】]*(?:填写|待填|补充|待补)[^】]*】')

class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=2,max_length=1200)
    reviewed: bool = Field(default=False,strict=True)
    use_model: bool = Field(default=False,strict=True)

class ExtractedField(BaseModel):
    model_config = ConfigDict(extra='forbid')
    field: FieldName
    value: str | int
    quote: str = Field(min_length=1,max_length=1200)
    counted_items: list[str] = Field(default_factory=list,max_length=100)

class MissingField(BaseModel):
    model_config = ConfigDict(extra='forbid')
    field: FieldName
    question: str = Field(min_length=2,max_length=100)
    example_hint: str = Field(default='',max_length=80)

class ModelBrief(BaseModel):
    model_config = ConfigDict(extra='forbid')
    summary: str = Field(min_length=2,max_length=500)
    fields: list[ExtractedField] = Field(default_factory=list,max_length=20)
    missing: list[MissingField] = Field(default_factory=list,max_length=5)
    questions: list[str] = Field(default_factory=list,max_length=6)
    next_actions: list[str] = Field(default_factory=list,max_length=6)

def number(token):
    if token.isascii() and token.isdigit(): return int(token)
    digits = dict(zip('零〇一二两三四五六七八九',[0,0,1,2,2,3,4,5,6,7,8,9]))
    total = section = current = 0
    for char in token:
        if char in digits: current = digits[char]
        elif char in '十百千':
            section += (current or 1)*{'十':10,'百':100,'千':1000}[char]; current=0
        elif char == '万': total += (section+current)*10000; section=current=0
        else: return None
    return total+section+current

def quantities(text):
    return [(number(m.group(1)),m.group(2),m) for m in re.finditer(rf'(?<![\d.\-])({NUM})\s*(?:个\s*(?=人|位|名))?({UNITS})',text)]

def _base_fields(text,compiled):
    known,evidence={},list(compiled['field_evidence'])
    for key in ('quantity','fulfillment','budget_yuan'):
        values={s['value'] for s in evidence if s['field']==key}
        if len(values)==1 and not any(i['field']==key for i in compiled['issues']): known[key]=values.pop()
    pairs={(n,u) for n,u,_ in quantities(text) if n is not None and n>0}
    if len(pairs)==1: known['quantity'],known['unit']=pairs.pop()
    elif len(pairs)>1: known.pop('quantity',None)
    domain=next((s['value'] for s in evidence if s['field']=='domain'),None)
    if domain and not known.get('unit'): known['unit']=CATALOG[domain]['unit']
    if compiled['proposal']: known['task_name']=CATALOG[compiled['proposal']['domain']]['label']
    else:
        goal=next((c.strip() for c in re.split(r'[，,。；;\n]',text) if c.strip() and not re.fullmatch(
            r'(?:总预算|预算|地点|时间|数量|服务方式|鞋类|材质|城市|区域)[：:为是]?.*',c.strip())
            and not re.fullmatch(rf'\s*({NUM})\s*({UNITS})\s*',c)),None)
        if goal: known['task_name']=goal[:100]
    for key,labels in {'location':'地点|城市|区域|位置|地区',
                       'time':'完成时间|时间|日期',
                       'details':'具体要求|鞋类|材质|服务内容|特殊要求',
                       'fulfillment':'服务方式|取送方式|交付方式'}.items():
        # A colon is optional in ordinary wording, e.g. 地点上海青浦区.
        # Inspect separate clauses so empty hints never swallow the next field.
        for clause in re.split(r'[。；;\n]' if key=='details' else r'[，,。；;\n]',text):
            match=re.search(rf'(?:{labels})(.*)$',clause)
            if not match: continue
            value=match.group(1).lstrip(' ：:\t').strip()
            if key=='location': value=re.sub(r'^(?:是|为|在)\s*','',value)
            if value and not PLACEHOLDER.search(value):
                known[key]=value
                break
    if 'location' not in known:
        match=re.search(r'(?:在|去)([^，,。；;\n]{1,24}(?:市|区|县|镇|附近))',text)
        if not match:
            match=re.search(r'(?:^|[，,。；;\n])\s*([\u4e00-\u9fff]{2,16}(?:市|区|县|镇))\s*(?=[，,。；;\n]|$)',text)
        if match and not PLACEHOLDER.search(match.group(1)): known['location']=match.group(1)
    if 'fulfillment' not in known:
        match=re.search(r'到店送洗|上门取送|快递寄送|到店自提|到店办理|到店|线上办理|线上交付|远程服务',text)
        if match: known['fulfillment']=match.group()
    return known,evidence

def _grounded_field(item,text):
    if item.quote not in text or PLACEHOLDER.search(item.quote): return None
    value=item.value
    if item.field=='quantity':
        if type(value) is not int or value<=0: return None
        if item.counted_items:
            # The model may count clearly enumerated participants (我和我哥).
            # Each member must have a separate, literal, nonoverlapping span.
            if len(item.counted_items)!=value: return None
            cursor=0
            for member in item.counted_items:
                if not member.strip(): return None
                start=item.quote.find(member,cursor)
                if start<0: return None
                cursor=start+len(member)
            return value
        return value if any(n==value for n,_,_ in quantities(item.quote)) else None
    if item.field=='budget_yuan':
        numbers=[number(m.group()) for m in re.finditer(NUM,item.quote)]
        return value if type(value) is int and 0<=value<=MAX_BUDGET_YUAN and value in numbers and re.search(r'预算|元|[¥￥]|花费|花|上限',item.quote) else None
    if not isinstance(value,str) or not value.strip(): return None
    value=value.strip()
    if item.field=='task_name': return (value if value in item.quote else item.quote.strip())[:100]
    if item.field=='fulfillment':
        # A semantic label such as 到店 may summarize a longer sentence. Carry
        # the user's quoted wording into the mandate instead of inventing text.
        return (value if value in item.quote else item.quote.strip())[:300]
    if item.field=='unit': return value if len(value)<=12 else None
    return value if value in item.quote and len(value)<=300 else None

def analyze(body,provider=None):
    if not body.reviewed: raise ValueError('请先检查并确认这段文字已去除个人资料')
    # Template instructions are not user facts (e.g. “例如2人” is not a count).
    facts_text=PLACEHOLDER.sub(lambda match:' '*len(match.group()),body.text)
    compiled=compile_stand_in(facts_text)
    def handle(payload,instructions):
        known,evidence=_base_fields(facts_text,compiled)
        brief=None
        if body.use_model:
            if provider is None: raise ValueError('真实模型尚未启用')
            from .suite import role_json
            brief=role_json(provider,instructions+'''
理解用户实际想做的事，不限任何目录、行业或关键词。只提取原文明确提供的条件；不得猜数量、预算、地点、日期或取送方式。
fields逐项输出field、value、quote、counted_items；quote必须逐字引用原文。task_name可简短概括；unit可根据事项推断计价单位，但数量必须有原文依据。
理解自然表达，不要求用户按模板填写。忽略所有【填写…】示例文字，不把示例的数字、地点、方式等当作已提供条件。模板空项若已在别处说清楚，不重复问。
明确列举的参与者可以计数，例如“我和我哥”就是2人，quantity字段value=2、quote="我和我哥"、counted_items=["我","我哥"]；列出的每一项都必须按顺序逐字出现在quote里，且不重叠、不重复计算。同一句“去修脚店铺找人修脚”也已经表达了到店服务。
counted_items仅用于明确列举的参与者人数，并同时输出unit="人"字段。显式数量或其他字段的counted_items用空数组。不能从“我们一家”“和几个朋友”等模糊表达猜人数；只列举实际接受服务的人，不把服务人员、未参加的人算进去。
用户已描述去店里接受服务时，不因缺少“到店”二字而反问服务方式；fulfillment的value保留原话中表达服务方式的片段即可，不能写原文没有的词。
quantity、budget_yuan用整数；fulfillment用用户自己的服务描述，不要输出代码。location/time/details原样保留。
missing最多5项，只问这项具体任务确实缺少的信息；已给“预算350”就是350元预算，不要再问总预算、单次预算或重复问需求是什么。
字段已有值时不要再询问该字段。数量和单位可以一起问。无地点要求的线上任务不问城市；没有明确必要性不额外问条件。
应结合事项判断关键规格是否缺少，例如清洗对象的类型/材质/范围、维修对象型号、文稿主题字数等；需要时用details提问。
每个missing的example_hint给出该怎么填的简短提示，例如“城市或区域”“鞋子类型、材质和清洗要求”“到店送洗或上门取送”；不要编具体城市、数量或日期。所有面向用户的提问用中文。
summary最多一小句。不要推荐或编造真实店铺、价格、库存，不要写免责声明或工具介绍。''',
                            {'request':body.text,'known_fields':known},ModelBrief,max_tokens=1800)
            model_values={}
            for item in brief.fields:
                value=_grounded_field(item,body.text)
                if value is not None:
                    model_values.setdefault(item.field,[]).append(value)
                    if item.field=='quantity' and item.counted_items and 'unit' not in known:
                        known['unit']='人'
                    evidence.append({'field':item.field,'value':value,'text':item.quote,'start':body.text.index(item.quote),'end':body.text.index(item.quote)+len(item.quote)})
            for key,values in model_values.items():
                if key in {'location','time','details'}:
                    prior=known.get(key)
                    retained=[prior] if prior and not any(prior in value for value in values) else []
                    known[key]='；'.join(dict.fromkeys(retained+[value for value in values if not prior or value not in prior or value==prior]))
                elif len(set(values))==1 and (key not in {'budget_yuan','quantity'} or key not in known): known[key]=values[0]
            if any(m.field=='task_name' for m in brief.missing) and 'task_name' not in model_values and not compiled['proposal']:
                known.pop('task_name',None)
            if 'unit' not in known:
                for item in brief.missing:
                    match=re.search(rf'(?:几|多少)(?:个)?({UNITS})',item.question) if item.field=='quantity' else None
                    if match:
                        known['unit']=match.group(1)
                        break
        if not 0<=known.get('budget_yuan',0)<=MAX_BUDGET_YUAN: known.pop('budget_yuan',None)
        known={k:v for k,v in known.items() if not isinstance(v,str) or not PLACEHOLDER.search(v)}
        missing=[]
        prompts={'task_name':'你具体想做什么？','quantity':'需要多少？请写清数量和单位。','unit':'数量按什么计算，例如双、件或次？',
                 'fulfillment':'你希望怎样服务或交付？','budget_yuan':'总预算是多少元？','location':'希望在哪个城市或区域？',
                 'time':'有什么时间要求？没有可写“时间不限”。','details':'还有哪些具体类型或服务要求需要补充？'}
        if brief:
            for item in brief.missing:
                if 'budget_yuan' in known and item.field!='budget_yuan' and re.search(r'预算|多少钱|金额',item.question): continue
                if item.field not in known and item.field not in {m['field'] for m in missing}: missing.append(item.model_dump())
        for key in ('task_name','quantity','unit','fulfillment','budget_yuan'):
            if key not in known and key not in {m['field'] for m in missing}:
                if key=='unit' and any(m['field']=='quantity' for m in missing): continue
                missing.append({'field':key,'question':prompts[key]})
        for issue in compiled['issues']:
            key=issue['field']
            if key in ('quantity','budget_yuan') and issue['reason']!='missing':
                known.pop(key,None)
                if key not in {m['field'] for m in missing}: missing.append({'field':key,'question':f'请明确一个{ "数量" if key=="quantity" else "预算" }值，原文有多种说法。'})
        proposal=None
        if not body.use_model and compiled['proposal']: proposal=compiled['proposal']; missing=[]
        elif not missing and all(k in known for k in ('task_name','quantity','unit','fulfillment','budget_yuan')):
            context=tuple(f'{label}：{known[key][start:start+280]}' for key,label in [('location','地点'),('time','时间'),('details','具体要求')]
                          if key in known for start in range(0,len(known[key]),280))
            proposal=Mandate(domain='custom',quantity=known['quantity'],fulfillment=known['fulfillment'],budget_yuan=known['budget_yuan'],
                             custom_task=CustomTask(name=known['task_name'],unit=known['unit'],context=context)).model_dump(exclude_none=True,mode='json')
        placeholders={'task_name':('具体需求','【填写想做的事情】'),'quantity':('数量','【填写数量】'+known.get('unit','【填写单位】')),
                      'unit':('计价单位','【填写单位】'),'fulfillment':('服务方式','【填写服务方式】'),'budget_yuan':('总预算','【填写总预算】元'),
                      'location':('地点','【填写城市或区域】'),'time':('完成时间','【填写时间要求，没有可写不限】'),'details':('具体要求','【填写类型、材质或服务内容】')}
        additions=[f'{placeholders[m["field"]][0]}：'+(f'【填写：{m["example_hint"]}】' if m.get('example_hint') and m['field'] not in {'quantity','unit','budget_yuan'} else placeholders[m['field']][1]) for m in missing]
        example=body.text.rstrip('。；; ')+('；'+'；'.join(additions) if additions else '')+'。'
        summary=known.get('task_name','还需要明确想办的事情')+(f'；预算{known["budget_yuan"]}元' if 'budget_yuan' in known else '')
        return {'summary':summary,'known_fields':known,'missing_fields':missing,'questions':[m['question'] for m in missing],
                'rewrite_example':example,'proposal':proposal,'can_rehearse':proposal is not None,'mode':'live_llm' if body.use_model else 'explicit_rules',
                'field_evidence':evidence,'unmodeled_fragments':compiled['unmodeled_fragments'],
                'next_actions':['在原文补充缺少的条件后，再点①检查。'] if missing else ['核对已提取条件，进入第二步。'],
                'evidence_needed':['现行价格及全部附加费','退改条款'],'data_notice':'自定义需求使用你确认的模拟条件，不代表已查询真实商家。'}
    required={'analyze_text'}|({'model_call'} if body.use_model else set())
    result,event=invoke('request-analysis',{'text':body.text},handle,granted=required,required=required)
    return {**result,'skill_events':[event]}
