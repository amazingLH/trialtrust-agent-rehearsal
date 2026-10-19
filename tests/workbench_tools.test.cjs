const test = require('node:test');
const assert = require('node:assert/strict');
const W = require('../trialtrust/web/workbench_tools.js');
const catalog={scenarios:[{id:'pottery',unit:'人',price:70,changed_price:80,fee:0,fulfillments:['pickup','shipping']},{id:'buffet',unit:'人',price:80,changed_price:100,fee:10,fulfillments:['dine_in']}]};
const template={id:'sample',name:'聚会',method:'single',spec:{domain:'buffet',quantity:2,fulfillment:'dine_in',budget_yuan:190,agent:'demo_careful',dense:false,case:'price_change'}};
test('template import rejects corrupt storage and unsupported conditions',()=>{
 assert.deepEqual(W.readTemplates('bad json',catalog),[]);
 assert.deepEqual(W.readTemplates('{}',catalog),[]);
 for(const spec of [{...template.spec,domain:'unknown'},{...template.spec,quantity:0},{...template.spec,budget_yuan:1001},{...template.spec,fulfillment:'shipping'},{...template.spec,agent:'unknown'}]) assert.equal(W.cleanTemplate({...template,spec},catalog),null);
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
test('pottery delivery cost is per order and invalid inputs do not produce forecasts',()=>{
 assert.equal(W.preview(catalog.scenarios[0],4,'shipping',300).base,300);
 assert.equal(W.preview(catalog.scenarios[0],4,'pickup',300).base,280);
 assert.equal(W.preview(catalog.scenarios[0],NaN,'pickup',300),null);
 assert.equal(W.preview(catalog.scenarios[0],2,'not-supported',300),null);
});
test('absence of an accepted draft is unknown total, not a zero-cost plan',()=>{
 const f=W.facts({conditions:template.spec,report:{drafts:[],evidence_coverage:{},real_world_side_effects:0}},'single');
 assert.equal(f.total,null);assert.equal(f.price,false);assert.equal(f.effects,0);
});
test('comparison reads the selected real report without merging the other branch',()=>{
 const row={conditions:template.spec,report:{kind:'suite',execution_mode:'offline_script',baseline:{drafts:[{total_yuan:170}],evidence_coverage:{current_price_observed:true}},changed:{drafts:[],evidence_coverage:{current_price_observed:false}}}};
 assert.equal(W.facts(row,'baseline').total,170);assert.equal(W.facts(row,'changed').total,null);assert.equal(W.facts(row,'changed').price,false);
});
