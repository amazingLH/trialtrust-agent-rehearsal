"""Versioned owned examples; the catalog is not a live merchant directory."""
from typing import Annotated, Literal
from pydantic import StringConstraints
from .catalog_groups import GROUPS

Fulfillment = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500)]
FULFILLMENTS = {'pickup':'到店自取','shipping':'作品邮寄','onsite':'上门服务','entry':'到场入园','dine_in':'到店用餐','meetup':'集合出行','stay':'入住体验','visit':'到店体验','ride':'乘车出行','rental':'到店租还'}
MAX_BUDGET_YUAN = 1_000_000
CATEGORIES = [{'id':'attractions','label':'景点探索','icon':'⌂'}, {'id':'food','label':'美食聚会','icon':'◡'}, {'id':'travel','label':'旅行出行','icon':'✦'}, {'id':'life','label':'生活服务','icon':'♡'}]

def item(category, label, unit, price, changed, fee, modes, keywords, description):
    return dict(category=category,label=label,unit=unit,price=price,changed_price=changed,fee=fee,
                fulfillments=modes,keywords=keywords,description=description,synthetic=True)

CATALOG = {
 'museum':item('attractions','博物馆观展','人',40,60,0,['entry'],['博物馆','观展'],'按人数算票钱，查看能否取消或改期'),
 'garden':item('attractions','公园漫游','人',30,45,10,['entry'],['公园','园林'],'帮你算清门票和每单额外收取的服务费'),
 'aquarium':item('attractions','海洋馆亲子游','人',90,120,0,['entry'],['海洋馆','水族馆'],'按人数算票钱，暂不计算儿童优惠'),
 'buffet':item('food','自助餐聚会','人',80,100,10,['dine_in'],['自助餐'],'帮你算清餐费和每单额外收取的服务费'),
 'teatime':item('food','下午茶约会','人',60,85,0,['dine_in'],['下午茶'],'按人数算套餐钱，查看能否取消或改期'),
 'picnic':item('food','野餐食盒','份',45,60,15,['pickup'],['野餐','食盒'],'按份数算食盒的钱，加上每单打包费'),
 'citywalk':item('travel','城市漫步','人',50,70,0,['meetup'],['城市漫步','citywalk'],'帮你算清体验费，真实路线和天气需另查'),
 'daytrip':item('travel','周边一日游','人',100,140,20,['meetup'],['一日游','周边游'],'帮你算清活动费和服务费，不会实际预订交通'),
 'hotel':item('travel','住宿体验','间',180,240,30,['stay'],['住宿','酒店','民宿'],'按房间数算费用，不查询真实日期和剩余房间'),
 'pottery':item('life','周末陶艺','人',70,80,0,['pickup','shipping'],['陶艺'],'帮你算清材料费、邮费，查看能否取消或改期'),
 'cleaning':item('life','空调清洗','台',90,110,30,['onsite'],['空调清洗','清洗空调'],'只按普通壁挂空调的基础清洗算钱，不含高空作业和拆机'),
 'organizing':item('life','收纳整理','次',120,160,20,['onsite'],['收纳','整理服务'],'按服务次数算费用，加上每单上门费'),
}

# Preserve the original IDs and prices so saved templates and records still work.
legacy_by_label = {entry['label']: key for key, entry in CATALOG.items()}
for group in GROUPS:
    for slot, label in enumerate(group['choices'], 1):
        key = legacy_by_label.get(label, f'{group["id"]}-{slot:02d}')
        if key not in CATALOG:
            price = group['price'] + ((slot - 1) % 4) * 5
            CATALOG[key] = item(group['category'], label, group['unit'], price,
                                price + group['delta'], group['fee'], group['fulfillments'],
                                [label], group['description'])
        CATALOG[key]['group'] = group['id']
        CATALOG[key]['keywords'] = list(dict.fromkeys([label, *CATALOG[key]['keywords']]))

# The same closed set validates API contracts, the MCP schema and saved conditions.
Domain = Literal[tuple(CATALOG)]


def public_catalog():
    return {'version':'owned-catalog-v2','categories':CATEGORIES,
            'groups':[{key: group[key] for key in ('id','category','label')} |
                      {'count':len(group['choices'])} for group in GROUPS],
            'scenarios':[{'id':key,**value} for key,value in CATALOG.items()],
            'fulfillments':FULFILLMENTS,'limits':{'budget_yuan':MAX_BUDGET_YUAN}}
