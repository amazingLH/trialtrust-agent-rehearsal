"""Normalize untrusted model formatting, never user facts or tool authority."""
import json
import re

from pydantic import ValidationError


class BriefFormatError(RuntimeError):
    pass


def _object(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('Duplicate JSON key')
        result[key]=value
    return result


def _records(value, questions=False):
    if value is None: return []
    if isinstance(value,list): return value
    if isinstance(value,dict):
        return [({'field':key,**{k:v for k,v in item.items() if k!='field'}} if isinstance(item,dict)
                 else {'field':key,'question':item})
                for key,item in value.items() if isinstance(item,dict) or questions and isinstance(item,str)]
    raise ValueError('Invalid collection')


def parse_model_brief(content, schema, field_schema, missing_schema, parse_number):
    try:
        if not isinstance(content,str) or len(content)>50000: raise ValueError('Invalid content')
        text=content.strip()
        fenced=re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?```',text,re.I|re.S)
        if fenced: text=fenced.group(1)
        data=json.loads(text,object_pairs_hook=_object)
        if not isinstance(data,dict) or not {'summary','fields','missing'} & data.keys():
            raise ValueError('Invalid root')
        records=_records(data.get('fields'))
        missing=_records(data.get('missing'),questions=True)
        if len(records)>20 or len(missing)>5: raise ValueError('Oversized brief')
        fields=[]
        units=[]
        for record in records:
            if not isinstance(record,dict): continue
            # Ignore explanatory metadata, not malformed facts. Each retained
            # record still passes its schema and the caller's quote grounding.
            item={k:record[k] for k in ('field','value','quote','counted_items') if k in record}
            if type(item.get('value')) not in (str,int): continue
            members=item.get('counted_items')
            if members is None: item['counted_items']=[]
            elif isinstance(members,str):
                if members.strip().startswith('['):
                    try: item['counted_items']=json.loads(members)
                    except ValueError: item['counted_items']=[]
                else: item['counted_items']=[s.strip() for s in re.split(r'[,，、;；]',members) if s.strip()]
            unit=record.get('unit')
            if item.get('field') in {'quantity','budget_yuan'} and isinstance(item['value'],str):
                match=re.fullmatch(r'\s*([0-9零〇一二两三四五六七八九十百千万]+)\s*([^0-9\s]{0,12})\s*',item['value'])
                if match:
                    amount=parse_number(match.group(1))
                    suffix=match.group(2)
                    if amount is not None and (not suffix or item['field']=='quantity' or suffix=='元'):
                        item['value']=amount
                        if item['field']=='quantity' and suffix: unit=suffix.removeprefix('个')
            try: parsed=field_schema.model_validate(item)
            except ValidationError: continue
            fields.append(parsed.model_dump())
            if parsed.field=='quantity' and isinstance(unit,str) and 0<len(unit.strip())<=12:
                units.append({'field':'unit','value':unit.strip(),'quote':parsed.quote,'counted_items':[]})
        if not any(item['field']=='unit' for item in fields) and units:
            fields.append(units[0])
        questions=[]
        for record in missing:
            if not isinstance(record,dict): continue
            item={k:record[k] for k in ('field','question','example_hint','example_value') if k in record}
            for key in ('example_hint','example_value'):
                if item.get(key) is None: item[key]=''
            try: questions.append(missing_schema.model_validate(item).model_dump())
            except ValidationError: continue
        summary=data.get('summary')
        cleaned={'summary':summary[:500] if isinstance(summary,str) and len(summary.strip())>=2 else '需求分析',
                 'fields':fields,'missing':questions}
        # A fully malformed list is not a successful empty analysis.
        if data.get('fields') and not fields: raise ValueError('No valid field records')
        if data.get('missing') and not questions: raise ValueError('No valid missing records')
        return schema.model_validate(cleaned)
    except (ValueError,TypeError,RecursionError):
        raise BriefFormatError('需求检查结果暂时无法读取，请重试。') from None
