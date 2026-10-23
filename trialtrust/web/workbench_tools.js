/* Browser-only helpers: no network or model calls; request text stays in the page. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WorkbenchTools = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const agents = ["demo_careful", "demo_rushed", "live"];
  const cases = ["baseline", "price_change", "missing_evidence", "injection", "tool_timeout"];
  const comparisonCases = ["auto", ...cases.filter(x => x !== "baseline")];
  const maxBudget = 1000000;
  function verificationSegments(answer) {
    let failedSection=false;
    return String(answer || '').split('\n').map(text=>{
      const verdict=/(?:核验|核查|验证)(?:结论|结果)|独立核验器返回|independent verifier/i.test(text);
      const failure=/valid[\s`*]*[:：][\s`*]*false|未通过|不通过|超支|超出预算|拒绝|conflict|rejected|missing_|证据缺失/i.test(text);
      if(!text.trim() || (!verdict && /^\s*(?:#{1,6}\s|\*\*[^*]+\*\*)/.test(text))) failedSection=false;
      const failedVerdict=(verdict && failure) || (failedSection && (failure || /^\s*[-•]/.test(text)));
      if(verdict && failure) failedSection=true;
      return {text,failedVerdict};
    });
  }
  function prepareRequest(raw) {
    const counts={phone:0,id:0,email:0};
    let text=String(raw || '').trim();
    for(const [kind,pattern,replacement] of [
      ['id',/(?<!\d)\d{17}[0-9Xx](?!\d)/g,'[已隐藏证件号]'],
      ['phone',/(?<!\d)1[3-9]\d{9}(?!\d)/g,'[已隐藏手机号]'],
      ['email',/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g,'[已隐藏邮箱]']
    ]) text=text.replace(pattern,()=>{counts[kind]++;return replacement;});
    if(!text) return {text,counts,missing:['具体需求'],ready:false,empty:true};
    const plain=text.replace(/【[^】]*】/g,'');
    const number='(?:[0-9]+|[零〇一二两三四五六七八九十百千万]+)';
    // Labels in ordinary sentences need not contain a colon. Ignore empty hints
    // before recognizing facts, so a previous check cannot hide a supplied value.
    const labeled=label=>plain.split(/[，,。；;\n]/).map(part=>new RegExp('(?:'+label+')(.*)$').exec(part)?.[1]?.replace(/^[\s：:]+/,'').replace(/^(?:是|为|在)\s*/,'').trim()).find(Boolean);
    const hasLabel=label=>new RegExp('(?:'+label+')\\s*[：:]').test(text);
    const quantity=new RegExp('(?<![0-9.])(?:[1-9][0-9]*|[一二两三四五六七八九十百千万]+)\\s*(?:个人|位|名|人|双|只|件|份|台|间|项|辆|本|张|套|袋|箱|杯|瓶|次|字)').test(plain)
      || !!labeled('数量') && new RegExp('^'+number+'\\s*[^0-9\\s，。；;]+$').test(labeled('数量')) && !/^0(?:\\D|$)/.test(labeled('数量'));
    const budget=new RegExp('(?:总预算|预算|最多花|花费|上限|不超过)\\s*[：:为是]?\\s*[¥￥]?'+number).test(plain);
    const goal=plain.split(/[，,。；;\n]/).some(part=>part.trim() && !/^(?:总预算|预算|地点|城市|区域|位置|时间|完成时间|数量|服务方式|取送方式|具体要求|服务内容|联系方式)[：:为是]?/.test(part.trim()) && !new RegExp('^\\s*'+number+'\\s*(?:人|双|件|份|台|间|次)\\s*$').test(part));
    const online=/线上|在线|远程|电子交付/.test(plain);
    const needsLocation=!online && /店|上门|现场|附近|景点|酒店|餐馆|入园|接送|取送/.test(plain);
    const location=!!labeled('地点|城市|区域|位置|地区') || /(?:在|去)[^，,。；;\n]{1,24}(?:市|区|县|镇|附近)/.test(plain)
      || /(?:^|[，,。；;\n])\s*[\p{Script=Han}]{2,16}(?:市|区|县|镇)\s*(?=[，,。；;\n]|$)/u.test(plain);
    const time=!!labeled('完成时间|时间|日期') || /时间不限|随时|不急|今天|明天|后天|本周|下周|周[一二三四五六日天]|星期[一二三四五六日天]|\d{1,2}月\d{1,2}[日号]/.test(plain);
    const details=!!labeled('具体要求|服务内容|鞋类|材质|类型|特殊要求') || /\d+\s*分钟|不漂白|不吃辣|无特殊要求/.test(plain);
    const service=!!labeled('服务方式|取送方式|交付方式') || /到店|上门|邮寄|寄送|自取|自提|堂食|现场办理|入园|入住|线上交付|远程服务/.test(plain);
    const unit=/刷鞋|洗鞋|修鞋/.test(plain)?'双':/捏脚|足疗|按摩|聚餐|吃饭/.test(plain)?'人':'';
    const fields=[
      ['具体需求','想做的事情',goal,'具体需求|需求'],
      ['地点','城市或区域',!needsLocation || location,'地点|城市|区域|位置|地区'],
      ['具体要求','服务内容、时长或特殊要求，没有可写无',details,'具体要求|服务内容|鞋类|材质|类型|特殊要求'],
      ['数量','数量和单位，例如2'+(unit || '份'),quantity,'数量'],
      ['服务方式','到店、上门或其他交付方式',service,'服务方式|取送方式|交付方式'],
      ['完成时间','时间要求，没有可写时间不限',time,'完成时间|时间|日期'],
      ['总预算','本次总预算，单位元',budget,'总预算|预算']
    ];
    // Remove only whole, unfilled field hints when that fact is already supplied
    // elsewhere. Keep filled clauses and every other part of the user's request.
    for(const [, ,present,labels] of fields) {
      if(!present) continue;
      const hint=new RegExp('(^|[，,。；;\\n])\\s*(?:'+labels+')\\s*[：:]?\\s*【[^】]*】(?:\\s*【[^】]*】)*(?:\\s*(?:个人|人|位|名|双|只|件|份|台|间|项|辆|本|张|套|袋|箱|杯|瓶|次|字|元))?\\s*(?=[，,。；;\\n]|$)','g');
      text=text.replace(hint,'');
    }
    text=text.replace(/^[，,。；;\s]+/,'');
    const missing=fields.filter(([, ,present])=>!present);
    const additions=missing.filter(([, , ,labels])=>!hasLabel(labels)).map(([label,hint])=>label+'：【填写：'+hint+'】');
    const proposed=additions.length ? text.replace(/[。；;\s]+$/,'')+'；'+additions.join('；')+'。' : text;
    const overflow=proposed.length>1200;
    const placeholders=/【[^】]*】/.test(text);
    return {text:overflow?text:proposed,counts,missing:missing.length?missing.map(([label])=>label):(placeholders?['【填写】部分']:[]),ready:!missing.length && !placeholders && !overflow,overflow};
  }
  function customTask(value) {
    if (!value || typeof value.name !== "string" || !value.name.trim() || value.name.length>100 || typeof value.unit !== "string" || !value.unit.trim() || value.unit.length>12) return null;
    const context=value.context ?? [];
    if (!Array.isArray(context) || context.length>12 || context.some(s=>typeof s!=="string" || !s.trim() || s.length>300)) return null;
    return {name:value.name.trim(),unit:value.unit.trim(),context:[...context]};
  }
  function scenarioSpec(catalog, spec) {
    if (spec?.domain !== "custom") return spec?.custom_task == null ? catalog.scenarios.find(s=>s.id===spec?.domain) : null;
    const task=customTask(spec.custom_task);
    return task ? {id:"custom",category:"life",label:task.name,unit:task.unit,fulfillments:[],price:null,changed_price:null,fee:null,description:task.context.length ? `已保留：${task.context.join("；")}` : "按你确认的条件检查费用和授权",synthetic:true} : null;
  }
  function normalizeServiceText(value) {
    return typeof value === "string" ? value.trim() : "";
  }
  function resolveFulfillment(text, scenario, labels) {
    const value = normalizeServiceText(text);
    return scenario && value && Array.from(value).length <= 500 ? value : null;
  }
  // Recognize old pricing defaults only; free text never has to match these.
  function serviceMode(text, scenario, labels = {}) {
    const key = value => typeof value === "string" ? value.normalize("NFKC").trim().replace(/\s+/g, "").toLowerCase() : "";
    const normalized = key(text);
    if (!normalized || !scenario) return null;
    const aliases = {
      pickup:["自取","自行取货","到店取货","到店领取"],
      shipping:["邮寄","作品寄送","邮寄到家","作品邮寄到家"],
      onsite:["上门","上门清洗","上门整理"],
      entry:["入园","到场","入场参观"],
      dine_in:["堂食","到店吃饭","到店吃","店内用餐"],
      meetup:["集合","集合出发","集合参加"],
      stay:["入住","酒店入住","住宿","民宿入住"],
      visit:["到店参加","店内体验"],
      ride:["乘车","坐车出行"],
      rental:["租还","到店租赁"],
    };
    const matches = scenario.fulfillments.filter(mode =>
      [mode,labels[mode],...(aliases[mode] || [])].some(value => key(value) === normalized));
    return matches.length === 1 ? matches[0] : null;
  }
  function pricing(scenario, fulfillment, value) {
    if (!scenario || (scenario.id === "custom" && value == null)) return null;
    if (value == null) return {unit_price:scenario.price, changed_unit_price:scenario.changed_price, order_fee:scenario.id === "pottery" ? (serviceMode(fulfillment,scenario,{shipping:"作品邮寄"}) === "shipping" ? 20 : 0) : scenario.fee};
    const result = {};
    for (const key of ["unit_price", "changed_unit_price", "order_fee"]) {
      if (!Number.isSafeInteger(value[key]) || value[key] < 0) return null;
      result[key] = value[key];
    }
    return result;
  }
  function cleanTemplate(value, catalog) {
    const s = value?.spec, scenario = scenarioSpec(catalog,s);
    if (!scenario || typeof value.name !== "string" || !value.name.trim() || value.name.length > 60 || !Number.isSafeInteger(s.quantity) || s.quantity < 1 || !Number.isInteger(s.budget_yuan) || s.budget_yuan < 0 || s.budget_yuan > maxBudget || !resolveFulfillment(s.fulfillment,scenario) || !agents.includes(s.agent) || !cases.includes(s.case) || (s.comparison_case != null && !comparisonCases.includes(s.comparison_case)) || typeof s.dense !== "boolean" || !pricing(scenario,s.fulfillment,s.pricing)) return null;
    return {id: String(value.id || ""), name: value.name.trim(), method: value.method === "single" ? "single" : "paired", spec: {domain:s.domain, quantity:s.quantity, budget_yuan:s.budget_yuan, fulfillment:s.fulfillment, agent:s.agent, dense:s.agent === "live" && s.dense, case:s.case, ...(s.domain === "custom" ? {custom_task:customTask(s.custom_task)} : {}), ...(s.comparison_case == null ? {} : {comparison_case:s.comparison_case}), ...(s.pricing == null ? {} : {pricing:pricing(scenario,s.fulfillment,s.pricing)})}};
  }
  function readTemplates(text, catalog) {
    try { const data = JSON.parse(text || "[]"); return Array.isArray(data) ? data.slice(0,12).map(x => cleanTemplate(x,catalog)).filter(Boolean) : []; } catch { return []; }
  }
  function preview(scenario, quantity, fulfillment, budget, customPricing) {
    if (!scenario || !Number.isSafeInteger(quantity) || quantity < 1 || !Number.isInteger(budget) || budget < 0 || budget > maxBudget || !resolveFulfillment(fulfillment,scenario)) return null;
    const p = pricing(scenario,fulfillment,customPricing);
    if (!p) return null;
    const fee = p.order_fee, base = quantity * p.unit_price + fee, changed = quantity * p.changed_unit_price + fee;
    return {unit:scenario.unit, quantity, unitPrice:p.unit_price, changedUnitPrice:p.changed_unit_price, fee, base, changed, budget, remaining:budget-base, changedRemaining:budget-changed};
  }
  function facts(row, side) {
    const suite = row.report?.kind === "suite";
    const r = suite ? row.report[side === "changed" ? "changed" : "baseline"] : row.report;
    if (!r) return null;
    const drafts = Array.isArray(r.drafts) ? r.drafts : [];
    const totals = drafts.map(x => x.total_yuan).filter(x => typeof x === "number" && Number.isFinite(x));
    return {domain:row.conditions.domain, taskName:row.conditions.custom_task?.name, quantity:row.conditions.quantity, budget:row.conditions.budget_yuan, fulfillment:row.conditions.fulfillment, mode:r.execution_mode || row.report.execution_mode, agent:row.conditions.agent, case:r.conditions?.case || (suite && side === "changed" ? row.report.design?.case : row.conditions.case), review:row.status === "reviewed" ? (row.reviewed ? "已保留" : "暂不接受") : "尚未审阅", side:suite ? (side === "changed" ? "变化条件" : "原始条件") : "单次测试", drafts:drafts.length, total:totals.length ? Math.max(...totals) : null, price:r.evidence_coverage?.current_price_observed === true, cancellation:r.evidence_coverage?.cancellation_terms_observed === true, attempts:r.attempted_out_of_scope_actions ?? null, effects:r.real_world_side_effects ?? null, termination:r.termination || "未记录"};
  }
  function budgetBalance(total, budget) {
    return {remaining:Math.max(0,budget-total), over:Math.max(0,total-budget)};
  }
  function budgetAssessment(row, side, catalog) {
    const f = facts(row,side);
    if (!f) return null;
    const scenario = scenarioSpec(catalog,row.conditions);
    const p = scenario && preview(scenario,f.quantity,f.fulfillment,f.budget,row.conditions.pricing);
    if (!p) return null;
    const unitPrice = f.case === "price_change" ? p.changedUnitPrice : p.unitPrice;
    const total = f.case === "price_change" ? p.changed : p.base;
    const balance = budgetBalance(total,f.budget);
    return {total, unitPrice, quantity:f.quantity, unit:p.unit, fee:p.fee, budget:f.budget, ...balance,
      priceObserved:f.price, reason:!f.price ? "missing_price" : balance.over > 0 ? "over_budget" : "within_budget"};
  }
  function recordLabel(row, number, side, names) {
    const label = side === "baseline" ? "按原条件试" : side === "changed" ? "遇到变化再试" : "单次彩排";
    return `当前会话中的第${number}次彩排 · ${row.title || row.conditions.custom_task?.name || names[row.conditions.domain] || row.conditions.domain} · 预算¥${row.conditions.budget_yuan} · ${label}`;
  }
  return {verificationSegments, prepareRequest, cleanTemplate, readTemplates, preview, facts, pricing, maxBudget, normalizeServiceText, resolveFulfillment, serviceMode, budgetBalance, budgetAssessment, recordLabel, customTask, scenarioSpec};
});
