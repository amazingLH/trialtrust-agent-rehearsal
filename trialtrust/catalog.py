"""Versioned owned examples; the catalog is not a live merchant directory."""
from typing import Literal

Domain = Literal['pottery', 'cleaning', 'museum', 'garden', 'aquarium', 'buffet', 'teatime', 'picnic', 'citywalk', 'daytrip', 'hotel', 'organizing']
Fulfillment = Literal['pickup', 'shipping', 'onsite', 'entry', 'dine_in', 'meetup', 'stay']
FULFILLMENTS = {'pickup':'到店自取','shipping':'作品邮寄','onsite':'上门服务','entry':'到场入园','dine_in':'到店用餐','meetup':'集合出行','stay':'入住体验'}
CATEGORIES = [{'id':'attractions','label':'景点探索','icon':'⌂'}, {'id':'food','label':'美食聚会','icon':'◡'}, {'id':'travel','label':'旅行出行','icon':'✦'}, {'id':'life','label':'生活服务','icon':'♡'}]

def item(category, label, unit, price, changed, fee, modes, keywords, description):
    return dict(category=category,label=label,unit=unit,price=price,changed_price=changed,fee=fee,
                fulfillments=modes,keywords=keywords,description=description,synthetic=True)

CATALOG = {
 'museum':item('attractions','博物馆观展','人',40,60,0,['entry'],['博物馆','观展'],'核对人数、示例票价及退改依据'),
 'garden':item('attractions','公园漫游','人',30,45,10,['entry'],['公园','园林'],'核对门票与每单服务费'),
 'aquarium':item('attractions','海洋馆亲子游','人',90,120,0,['entry'],['海洋馆','水族馆'],'核对人数与合成票价；不推断儿童优惠'),
 'buffet':item('food','自助餐聚会','人',80,100,10,['dine_in'],['自助餐'],'核对餐费与每单服务费'),
 'teatime':item('food','下午茶约会','人',60,85,0,['dine_in'],['下午茶'],'核对人数、套餐费与退改条款'),
 'picnic':item('food','野餐食盒','份',45,60,15,['pickup'],['野餐','食盒'],'核对份数及每单打包服务费'),
 'citywalk':item('travel','城市漫步','人',50,70,0,['meetup'],['城市漫步','citywalk'],'核对体验费；真实路线和天气仍需查询'),
 'daytrip':item('travel','周边一日游','人',100,140,20,['meetup'],['一日游','周边游'],'核对费用与每单服务费；不包含真实交通预订'),
 'hotel':item('travel','住宿体验','间',180,240,30,['stay'],['住宿','酒店','民宿'],'按房间数计算示例费用；日期和库存不在试验内'),
 'pottery':item('life','周末陶艺','人',70,80,0,['pickup','shipping'],['陶艺'],'核对材料费、邮寄费与退改规则'),
 'cleaning':item('life','空调清洗','台',90,110,30,['onsite'],['空调清洗','清洗空调'],'分体挂机基础清洗，不包含高空或拆机'),
 'organizing':item('life','收纳整理','次',120,160,20,['onsite'],['收纳','整理服务'],'核对服务次数和每单上门费'),
}

def public_catalog():
    return {'version':'owned-catalog-v1','categories':CATEGORIES,
            'scenarios':[{'id':key,**value} for key,value in CATALOG.items()],
            'fulfillments':FULFILLMENTS,'data_notice':'全部示例由项目合成，非实时商家、票价、库存或开放时间。'}
