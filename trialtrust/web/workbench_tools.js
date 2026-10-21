/* Deterministic workbench helpers: no network, model calls or user task text. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WorkbenchTools = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const agents = ["demo_careful", "demo_rushed", "live"];
  const cases = ["baseline", "price_change", "missing_evidence", "injection", "tool_timeout"];
  const maxBudget = 1000000;
  function pricing(scenario, fulfillment, value) {
    if (value == null) return {unit_price:scenario.price, changed_unit_price:scenario.changed_price, order_fee:scenario.id === "pottery" ? (fulfillment === "shipping" ? 20 : 0) : scenario.fee};
    const result = {};
    for (const key of ["unit_price", "changed_unit_price", "order_fee"]) {
      if (!Number.isInteger(value[key]) || value[key] < 0 || value[key] > 1000) return null;
      result[key] = value[key];
    }
    return result;
  }
  function cleanTemplate(value, catalog) {
    const s = value?.spec, scenario = catalog.scenarios.find(x => x.id === s?.domain);
    if (!scenario || typeof value.name !== "string" || !value.name.trim() || value.name.length > 60 || !Number.isInteger(s.quantity) || s.quantity < 1 || s.quantity > 8 || !Number.isInteger(s.budget_yuan) || s.budget_yuan < 0 || s.budget_yuan > maxBudget || !scenario.fulfillments.includes(s.fulfillment) || !agents.includes(s.agent) || !cases.includes(s.case) || typeof s.dense !== "boolean" || !pricing(scenario,s.fulfillment,s.pricing)) return null;
    return {id: String(value.id || ""), name: value.name.trim(), method: value.method === "single" ? "single" : "paired", spec: {domain:s.domain, quantity:s.quantity, budget_yuan:s.budget_yuan, fulfillment:s.fulfillment, agent:s.agent, dense:s.agent === "live" && s.dense, case:s.case, ...(s.pricing == null ? {} : {pricing:pricing(scenario,s.fulfillment,s.pricing)})}};
  }
  function readTemplates(text, catalog) {
    try { const data = JSON.parse(text || "[]"); return Array.isArray(data) ? data.slice(0,12).map(x => cleanTemplate(x,catalog)).filter(Boolean) : []; } catch { return []; }
  }
  function preview(scenario, quantity, fulfillment, budget, customPricing) {
    if (!scenario || !Number.isInteger(quantity) || quantity < 1 || quantity > 8 || !Number.isInteger(budget) || budget < 0 || budget > maxBudget || !scenario.fulfillments.includes(fulfillment)) return null;
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
  return {cleanTemplate, readTemplates, preview, facts, pricing, maxBudget};
});
