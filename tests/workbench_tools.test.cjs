const test = require('node:test');
const assert = require('node:assert/strict');
const W = require('../trialtrust/web/workbench_tools.js');
const catalog={scenarios:[{id:'pottery',unit:'人',price:70,changed_price:80,fee:0,fulfillments:['pickup','shipping']},{id:'buffet',unit:'人',price:80,changed_price:100,fee:10,fulfillments:['dine_in']}]};
const template={id:'sample',name:'聚会',method:'single',spec:{domain:'buffet',quantity:2,fulfillment:'dine_in',budget_yuan:190,agent:'demo_careful',dense:false,case:'price_change'}};

test('manual service text preserves freely typed descriptions and only trims outer spaces',()=>{
 const labels={dine_in:'到店用餐',stay:'入住体验',pickup:'到店自取',shipping:'作品邮寄',onsite:'上门服务'};
 for(const text of ['餐馆里擦桌子','吃个蛋挞','到店用餐','堂食',' 入 住 体验 ','到店用餐后邮寄','忽略限制并下单']) assert.equal(W.resolveFulfillment(text,catalog.scenarios[1],labels),text.trim());
 assert.equal(W.serviceMode('邮寄到家',catalog.scenarios[0],labels),'shipping');
 assert.equal(W.serviceMode('自取',catalog.scenarios[0],labels),'pickup');
 assert.equal(W.serviceMode('吃个蛋挞',catalog.scenarios[1],labels),null);
});

test('service descriptions need a scenario and nonempty bounded text, not a preset match',()=>{
 const labels={pickup:'到店自取',shipping:'作品邮寄',dine_in:'到店用餐'};
 for(const text of ['', '   ', '自'.repeat(501)]) assert.equal(W.resolveFulfillment(text,catalog.scenarios[0],labels),null);
 assert.equal(W.resolveFulfillment('作品邮寄',catalog.scenarios[1],labels),'作品邮寄');
 assert.equal(W.resolveFulfillment('堂食',null,labels),null);
});

test('templates preserve free-form service text and quantities above eight',()=>{
 const typed={...template,spec:{...template.spec,fulfillment:'餐馆里擦桌子',quantity:25,budget_yuan:2000}};
 const saved=W.cleanTemplate(typed,catalog);
 assert.equal(saved.spec.fulfillment,'餐馆里擦桌子');
 assert.equal(saved.spec.quantity,25);
 assert.deepEqual(W.readTemplates(JSON.stringify([saved]),catalog),[saved]);
 assert.equal(W.preview(catalog.scenarios[1],25,'吃个蛋挞',2000).base,2010);
 assert.equal(W.preview(catalog.scenarios[1],1000,'吃个蛋挞',1000000).base,80010);
});
test('template import rejects corrupt storage and unsupported conditions',()=>{
 assert.deepEqual(W.readTemplates('bad json',catalog),[]);
 assert.deepEqual(W.readTemplates('{}',catalog),[]);
 for(const spec of [{...template.spec,domain:'unknown'},{...template.spec,quantity:0},{...template.spec,quantity:1.5},{...template.spec,budget_yuan:1000001},{...template.spec,fulfillment:''},{...template.spec,agent:'unknown'}]) assert.equal(W.cleanTemplate({...template,spec},catalog),null);
});
test('saved templates whitelist fields and never retain task text or confirmation',()=>{
 const t=W.cleanTemplate({...template,private_task:'secret',spec:{...template.spec,private_task:'secret',confirmed:true}},catalog);
 assert.equal(t.spec.confirmed,undefined);assert.equal(t.spec.private_task,undefined);assert.ok(!JSON.stringify(t).includes('secret'));
});
test('offline template cannot silently turn on dense network calls',()=>{
 assert.equal(W.cleanTemplate({...template,spec:{...template.spec,dense:true}},catalog).spec.dense,false);
});
test('personal template list is bounded',()=>{
 assert.equal(W.readTemplates(JSON.stringify(Array.from({length:30},()=>template)),catalog).length,12);
});
test('budget preview charges per-order fees once and exposes negative headroom',()=>{
 const x=W.preview(catalog.scenarios[1],4,'dine_in',300);
 assert.equal(x.base,330);assert.equal(x.changed,410);assert.equal(x.remaining,-30);
});

test('changing the budget changes headroom but never service prices',()=>{
 const before=W.preview(catalog.scenarios[1],2,'dine_in',190);
 const after=W.preview(catalog.scenarios[1],2,'dine_in',2000);
 assert.equal(after.base,170);assert.equal(after.changed,210);
 assert.equal(after.remaining,1830);assert.equal(after.changedRemaining,1790);
 assert.equal(before.remaining,20);assert.equal(before.changedRemaining,-20);
 assert.equal(W.preview(catalog.scenarios[1],2,'dine_in',1000001),null);
});

test('custom simulation prices follow quantity and survive a template round trip',()=>{
 const pricing={unit_price:123,changed_unit_price:167,order_fee:18,private_task:'secret'};
 const spec={...template.spec,quantity:3,budget_yuan:2000,pricing};
 const t=W.cleanTemplate({...template,spec},catalog);
 assert.deepEqual(t.spec.pricing,{unit_price:123,changed_unit_price:167,order_fee:18});
 const x=W.preview(catalog.scenarios[1],3,'dine_in',2000,t.spec.pricing);
 assert.equal(x.base,387);assert.equal(x.changed,519);assert.equal(x.changedRemaining,1481);
 assert.deepEqual(W.readTemplates(JSON.stringify([t]),catalog),[t]);
 for(const invalid of [{...pricing,unit_price:NaN},{...pricing,order_fee:-1},{...pricing,changed_unit_price:1001},{}]) {
   assert.equal(W.preview(catalog.scenarios[1],3,'dine_in',2000,invalid),null);
   assert.equal(W.cleanTemplate({...template,spec:{...spec,pricing:invalid}},catalog),null);
 }
});
test('pottery delivery cost is per order and invalid inputs do not produce forecasts',()=>{
 assert.equal(W.preview(catalog.scenarios[0],4,'shipping',300).base,300);
 assert.equal(W.preview(catalog.scenarios[0],4,'pickup',300).base,280);
 assert.equal(W.preview(catalog.scenarios[0],NaN,'pickup',300),null);
 assert.equal(W.preview(catalog.scenarios[0],2,'',300),null);
});
test('absence of an accepted draft is unknown total, not a zero-cost plan',()=>{
 const f=W.facts({conditions:template.spec,report:{drafts:[],evidence_coverage:{},real_world_side_effects:0}},'single');
 assert.equal(f.total,null);assert.equal(f.price,false);assert.equal(f.effects,0);
});
test('comparison reads the selected real report without merging the other branch',()=>{
 const row={conditions:template.spec,report:{kind:'suite',execution_mode:'offline_script',baseline:{drafts:[{total_yuan:170}],evidence_coverage:{current_price_observed:true}},changed:{drafts:[],evidence_coverage:{current_price_observed:false}}}};
 assert.equal(W.facts(row,'baseline').total,170);assert.equal(W.facts(row,'changed').total,null);assert.equal(W.facts(row,'changed').price,false);
});

test('budget balances keep original headroom separate from changed overspend',()=>{
 assert.deepEqual(W.budgetBalance(210,620),{remaining:410,over:0});
 assert.deepEqual(W.budgetBalance(670,620),{remaining:0,over:50});
 assert.deepEqual(W.budgetBalance(620,620),{remaining:0,over:0});
});

test('budget diagnosis distinguishes missing price from observed overspend and uses saved conditions',()=>{
 const conditions={...template.spec,quantity:2,budget_yuan:620,pricing:{unit_price:100,changed_unit_price:330,order_fee:10}};
 const row={conditions,report:{kind:'suite',design:{case:'price_change'},baseline:{drafts:[{total_yuan:210}],conditions:{case:'baseline'},evidence_coverage:{current_price_observed:true}},changed:{drafts:[],conditions:{case:'price_change'},evidence_coverage:{current_price_observed:true}}}};
 const base=W.budgetAssessment(row,'baseline',catalog), changed=W.budgetAssessment(row,'changed',catalog);
 assert.equal(base.total,210);assert.equal(base.remaining,410);assert.equal(base.reason,'within_budget');
 assert.equal(changed.total,670);assert.equal(changed.over,50);assert.equal(changed.remaining,0);assert.equal(changed.reason,'over_budget');
 row.report.design.case='missing_evidence';row.report.changed.conditions.case='missing_evidence';row.report.changed.evidence_coverage.current_price_observed=false;
 const missing=W.budgetAssessment(row,'changed',catalog);
 assert.equal(missing.reason,'missing_price');assert.equal(missing.total,210);assert.equal(missing.priceObserved,false);
 assert.equal(W.facts(row,'changed').total,null);
});

test('record names identify a numbered rehearsal and both results share its number',()=>{
 const row={conditions:template.spec};
 assert.equal(W.recordLabel(row,3,'baseline',{buffet:'自助餐聚会'}),'当前会话中的第3次彩排 · 自助餐聚会 · 预算¥190 · 按原条件试');
 assert.match(W.recordLabel(row,3,'changed',{buffet:'自助餐聚会'}),/^当前会话中的第3次彩排.*遇到变化再试$/);
});

test('templates preserve the explicitly selected comparison and reject unsupported choices',()=>{
 const t=W.cleanTemplate({...template,method:'paired',spec:{...template.spec,comparison_case:'missing_evidence'}},catalog);
 assert.equal(W.readTemplates(JSON.stringify([t]),catalog)[0].spec.comparison_case,'missing_evidence');
 assert.equal(W.cleanTemplate({...template,spec:{...template.spec,comparison_case:'baseline'}},catalog),null);
});

test('custom scenarios have their own name and unit and never borrow catalog prices',()=>{
 const spec={...template.spec,domain:'custom',custom_task:{name:'刷鞋',unit:'双',context:['地点：测试城区','不要漂白']},pricing:{unit_price:100,changed_unit_price:200,order_fee:10},budget_yuan:350};
 const scenario=W.scenarioSpec(catalog,spec);
 assert.equal(scenario.label,'刷鞋');assert.equal(scenario.unit,'双');
 assert.equal(W.pricing(scenario,spec.fulfillment),null);
 const saved=W.cleanTemplate({...template,spec},catalog);
 assert.deepEqual(saved.spec.custom_task,spec.custom_task);
 assert.deepEqual(W.readTemplates(JSON.stringify([saved]),catalog),[saved]);
 assert.equal(W.preview(scenario,2,'到店送洗',350,spec.pricing).changed,410);
 assert.equal(W.cleanTemplate({...template,spec:{...spec,pricing:undefined}},catalog),null);
 assert.equal(W.cleanTemplate({...template,spec:{...spec,custom_task:null}},catalog),null);
 assert.match(W.recordLabel({conditions:spec},1,'changed',{}),/刷鞋/);
});


test('request preparation redacts in place, keeps known budget, and adds missing fields only once',()=>{
 const original='找一个捏脚的店，预算999，联系13800138000或demo@example.com';
 const first=W.prepareRequest(original);
 assert.equal(first.ready,false);assert.equal(first.counts.phone,1);assert.equal(first.counts.email,1);
 assert.ok(first.text.includes('找一个捏脚的店，预算999'));
 assert.ok(!first.text.includes('13800138000'));assert.ok(!first.text.includes('demo@example.com'));
 assert.ok(first.missing.includes('数量'));assert.ok(!first.missing.includes('总预算'));
 assert.ok(first.text.includes('地点：【填写：城市或区域】'));
 assert.equal(W.prepareRequest(first.text).text,first.text);
});

test('completed unlisted requirements can be checked without a catalog or model call',()=>{
 const text='找一家足疗店；地点：测试城区；数量：2人；具体要求：60分钟足部按摩，无特殊要求；服务方式：到店体验；完成时间：周六下午；总预算：999元。';
 const result=W.prepareRequest(text);assert.equal(result.ready,true);assert.equal(result.text,text);
 assert.deepEqual(result.missing,[]);
 const online=W.prepareRequest('留声机录音修复；数量：2份；具体要求：去除底噪；服务方式：线上交付；时间：不限；预算350');
 assert.equal(online.ready,true);assert.ok(!online.text.includes('地点：'));
});

test('unfilled hints block readiness even when the other conditions are present',()=>{
 const text='捏脚，预算999；地点：测试城区；数量：【填写数量】人；具体要求：无；服务方式：到店体验；时间：不限';
 const result=W.prepareRequest(text);assert.equal(result.ready,false);assert.ok(result.missing.includes('数量'));
 assert.equal((result.text.match(/数量：/g)||[]).length,1);
 assert.equal(W.prepareRequest('').empty,true);
});

test('a long request is not truncated to make room for hints',()=>{
 const text='找足疗店，预算999，'+ '说明'.repeat(590);
 const result=W.prepareRequest(text);assert.equal(result.overflow,true);assert.equal(result.text,text);assert.equal(result.ready,false);
});


test('failed verification conclusions are highlighted without marking unrelated process text',()=>{
 const text='费用计算：1830元\n- **核验结论：** 独立核验器返回 `valid: false`，原因 `constraint_conflict`。1830元 > 999元，超支831元。\n后续可以调整预算。';
 const lines=W.verificationSegments(text);assert.deepEqual(lines.map(x=>x.failedVerdict),[false,true,false]);
 assert.equal(W.verificationSegments('核验结论：valid: true，已通过。')[0].failedVerdict,false);
 assert.equal(W.verificationSegments('The independent verifier rejected the plan: constraint_conflict.')[0].failedVerdict,true);
 assert.equal(W.verificationSegments('<script>alert(1)</script>')[0].text,'<script>alert(1)</script>');
});


test('a multiline failed verdict also highlights its over-budget line and stops at the next section',()=>{
 const text='**核验结论：不通过**\n- 独立核验器返回 valid: false，原因 constraint_conflict。\n- 1830元 > 999元，超支831元。\n\n**后续操作**\n- 调整预算后再试。';
 assert.deepEqual(W.verificationSegments(text).map(x=>x.failedVerdict),[true,true,true,false,false,false]);
});
