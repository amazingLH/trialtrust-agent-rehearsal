/* Deterministic workbench helpers: no network, model calls or user task text. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WorkbenchTools = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const agents = ["demo_careful", "demo_rushed", "live"];
  const cases = ["baseline", "price_change", "missing_evidence", "injection", "tool_timeout"];
  const comparisonCases = ["auto", ...cases.filter(x => x !== "baseline")];
  const maxBudget = 1000000;
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
    if (value == null) return {unit_price:scenario.price, changed_unit_price:scenario.changed_price, order_fee:scenario.id === "pottery" ? (serviceMode(fulfillment,scenario,{shipping:"作品邮寄"}) === "shipping" ? 20 : 0) : scenario.fee};
    const result = {};
    for (const key of ["unit_price", "changed_unit_price", "order_fee"]) {
      if (!Number.isInteger(value[key]) || value[key] < 0 || value[key] > 1000) return null;
      result[key] = value[key];
    }
    return result;
  }
  function cleanTemplate(value, catalog) {
    const s = value?.spec, scenario = catalog.scenarios.find(x => x.id === s?.domain);
    if (!scenario || typeof value.name !== "string" || !value.name.trim() || value.name.length > 60 || !Number.isSafeInteger(s.quantity) || s.quantity < 1 || !Number.isInteger(s.budget_yuan) || s.budget_yuan < 0 || s.budget_yuan > maxBudget || !resolveFulfillment(s.fulfillment,scenario) || !agents.includes(s.agent) || !cases.includes(s.case) || (s.comparison_case != null && !comparisonCases.includes(s.comparison_case)) || typeof s.dense !== "boolean" || !pricing(scenario,s.fulfillment,s.pricing)) return null;
    return {id: String(value.id || ""), name: value.name.trim(), method: value.method === "single" ? "single" : "paired", spec: {domain:s.domain, quantity:s.quantity, budget_yuan:s.budget_yuan, fulfillment:s.fulfillment, agent:s.agent, dense:s.agent === "live" && s.dense, case:s.case, ...(s.comparison_case == null ? {} : {comparison_case:s.comparison_case}), ...(s.pricing == null ? {} : {pricing:pricing(scenario,s.fulfillment,s.pricing)})}};
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
    return {domain:row.conditions.domain, quantity:row.conditions.quantity, budget:row.conditions.budget_yuan, fulfillment:row.conditions.fulfillment, mode:r.execution_mode || row.report.execution_mode, agent:row.conditions.agent, case:r.conditions?.case || (suite && side === "changed" ? row.report.design?.case : row.conditions.case), review:row.status === "reviewed" ? (row.reviewed ? "已保留" : "暂不接受") : "尚未审阅", side:suite ? (side === "changed" ? "变化条件" : "原始条件") : "单次测试", drafts:drafts.length, total:totals.length ? Math.max(...totals) : null, price:r.evidence_coverage?.current_price_observed === true, cancellation:r.evidence_coverage?.cancellation_terms_observed === true, attempts:r.attempted_out_of_scope_actions ?? null, effects:r.real_world_side_effects ?? null, termination:r.termination || "未记录"};
  }
  function budgetBalance(total, budget) {
    return {remaining:Math.max(0,budget-total), over:Math.max(0,total-budget)};
  }
  function budgetAssessment(row, side, catalog) {
    const f = facts(row,side);
    if (!f) return null;
    const scenario = catalog.scenarios.find(s => s.id === f.domain);
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
    return `当前会话中的第${number}次彩排 · ${names[row.conditions.domain] || row.conditions.domain} · 预算¥${row.conditions.budget_yuan} · ${label}`;
  }
  return {cleanTemplate, readTemplates, preview, facts, pricing, maxBudget, normalizeServiceText, resolveFulfillment, serviceMode, budgetBalance, budgetAssessment, recordLabel};
});
