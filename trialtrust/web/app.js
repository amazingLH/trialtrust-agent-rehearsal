const $ = (id) => document.getElementById(id);
PortalViewport.attach(
  window,
  $("notice").closest(".trialtrust-root") || document.documentElement,
);
const caseLabels = {
  baseline: "原始条件",
  price_change: "服务单价变化",
  missing_evidence: "查不到当前价格",
  injection: "资料夹带越权要求",
  tool_timeout: "首次查询超时",
};
let domainLabels = {},
  fulfillmentLabels = {},
  catalog = { categories: [], scenarios: [], fulfillments: {} },
  skillMetadata = [];
const toolLabels = {
  search_rules: "查找本次服务的依据",
  check_plan: "核验预算与当前证据",
  submit_draft: "尝试生成候选草稿",
  create_booking: "尝试发起预约",
};
let chosenCase = "baseline",
  activeId = null,
  running = false,
  pollTimer = null,
  liveEnabled = false,
  confirmedFor = null,
  currentCategory = null,
  currentStep = 1,
  latestRow = null;
let sessionToken = readLocal("trialtrust-session");
let conversationId = null;
let analysisNonce = 0,
  analyzing = false;
let serviceConfirmedFor = null, servicePricingMode = null;
let currentCustomTask = null;
let directorySelection = null, activeDemandSource = "directory";
const demandConfirmText = "确定！并进行下一步核对条件";
function rememberDirectorySelection() {
  if(activeDemandSource !== "directory" || !currentScenario()) return;
  directorySelection={spec:{...editorSpec(),fulfillment:$("fulfillment").value || $("fulfillment-text").value},method:$("run-method").value};
}
function renderDirectorySelection() {
  const s=directorySelection && scenarioFor(directorySelection.spec);
  $("selected-demand").textContent=s ? `当前需求：${s.label}` : "当前需求：尚未选择";
  $("domain-picker-value").textContent=s ? s.label : "请选择具体需求";
  $("scenario-description").textContent=s ? s.description+(s.id === "custom" ? "" : "；地点、日期等要求还需你自己确认。") : "选好后，这里会说明能帮你检查什么。";
}
function confirmDirectoryDemand() {
  if(running || analyzing) return;
  if(!directorySelection || !scenarioFor(directorySelection.spec)) {
    notice("请先在上方选择具体需求，或应用一套条件模板。",$("manual-domain-field").hidden ? "template-select" : "domain-picker");return;
  }
  if(activeDemandSource === "directory") rememberDirectorySelection();
  else restoreConditions(directorySelection.spec,directorySelection.method,"directory");
  notice();goStep(2);
}
function serviceLabel(value) { return Object.hasOwn(fulfillmentLabels, value) ? fulfillmentLabels[value] : value; }
function scenarioFor(spec) { return WorkbenchTools.scenarioSpec(catalog,spec); }
function currentScenario() { return scenarioFor({domain:$("domain").value,custom_task:$("domain").value === "custom" ? currentCustomTask : null}); }
function domainLabel(spec) { return spec.custom_task?.name || domainLabels[spec.domain] || "自定义需求"; }
function accountKey(key) { return ["trialtrust-condition-templates","trialtrust-current-conversation"].includes(key) && TrialTrustAuth.user() ? key+":"+TrialTrustAuth.user().id : key; }
function readLocal(key) {
  key = accountKey(key);
  // Preserve an existing tab's anonymous identity before adopting a shared one.
  // Older releases stored identities only in sessionStorage.
  try {
    const value = sessionStorage.getItem(key);
    if (value) return value;
  } catch {}
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function remember(key, value) {
  key = accountKey(key);
  try {
    localStorage.setItem(key, value);
  } catch {}
  try {
    sessionStorage.setItem(key, value);
  } catch {}
}
function element(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function notice(text = "", target) {
  if (target === "domain") target = "domain-picker";
  $("notice-text").textContent = text;
  $("notice").hidden = !text;
  if (target) {
    const field = $(target);
    const outline = field.closest(".check-control") || field;
    outline.classList.add("field-error");
    field.setAttribute("aria-invalid", "true");
    setTimeout(() => outline.classList.remove("field-error"), 6000);
  }
}
async function api(path, body, method) {
  const opts = { headers: { "X-TrialTrust-Client": "web", ...TrialTrustAuth.headers() } };
  if (sessionToken) opts.headers["X-TrialTrust-Session"] = sessionToken;
  if (conversationId)
    opts.headers["X-TrialTrust-Conversation"] = conversationId;
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  if (method) opts.method = method;
  const response = await fetch(path, opts);
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error("服务暂未返回结果，请稍后重试。");
  }
  if (response.status === 401) { TrialTrustAuth.expire(); throw new Error("登录已失效，请重新登录。"); }
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : `请求未完成（${response.status}）`,
    );
  return result;
}
function scrollToSection(id) {
  const node = $(id);
  if (!node) return;
  node.scrollIntoView({
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "instant"
      : "smooth",
    block: "start",
  });
}
function signature() {
  return JSON.stringify(
    [
      "domain",
      "quantity",
      "fulfillment",
      "fulfillment-text",
      "budget",
      "agent",
      "dense",
      "cases",
      "run-method",
      "comparison-case",
      "unit-price", "changed-price", "order-fee",
    ].map((id) => ($(id).type === "checkbox" ? $(id).checked : $(id).value)),
  );
}
function invalidateConfirmation() {
  confirmedFor = null;
  $("confirmed").checked = false;
  $("confirmed").disabled = running || !serviceIsConfirmed();
  $("confirmed").removeAttribute("aria-invalid");
  $("confirmation-status").textContent = $("domain").value && !serviceIsConfirmed()
    ? "请先填写并确认服务方式，再勾选全部条件"
    : "尚未确认 · 修改条件后需重新勾选";
  $("confirmation-status").classList.remove("ok");
  updateCoach();
  renderBudgetPreview();
}
function chooseCase(value) {
  chosenCase = value;
  $("cases").value = value;
  invalidateConfirmation();
}
function modeNote() {
  const live = $("agent").value === "live";
  $("dense").disabled = !live || running;
  if (!live) $("dense").checked = false;
  $("mode-note").textContent = live
    ? "AI 自主执行 · 消耗模型额度"
    : "新手熟悉流程 · 不消耗模型额度";
  comparisonCaseNote();
}
function setBusy(value) {
  running = value;
  if (value) closeDemandMenu();
  if (value) closeConversationMenus();
  [
    "run",
    "run-suite",
    "unit-price", "changed-price", "order-fee", "reset-prices",
    "budget",
    "agent",
    "domain",
    "domain-picker",
    "quantity",
    "fulfillment",
    "fulfillment-text", "confirm-fulfillment", "clear-fulfillment",
    "confirmed",
    "prepare-stand-in",
    "confirm-directory-demand",
    "private-task",
    "cases",
    "new-conversation",
    "new-trial",
    "continue-trial",
    "run-method", "comparison-case", "template-select", "manual-demand", "template-demand", "apply-template", "save-template", "remove-template", "compare-rounds",
  ].forEach((id) => ($(id).disabled = value));
  document
    .querySelectorAll(
      ".category,.retry-actions button,.history-item,.conversation-item,.conversation-actions button,.analysis-result button",
    )
    .forEach((b) => (b.disabled = value));
  $("dense").disabled = value || $("agent").value !== "live";
  $("prepare-stand-in").disabled = value || !liveEnabled;
  $("run-suite").textContent = value
    ? "正在彩排，请稍候…"
    : "开始一组对照彩排 ↗";
  $("run").textContent = value ? "正在试运行…" : "运行这次试托 ↗";
  $("confirmed").disabled = value || !serviceIsConfirmed();
  updateCoach();
}
function selectCategory(id, selected = "") {
  closeDemandMenu();
  if (selected !== "custom") currentCustomTask = null;
  currentStep = selected ? 2 : 1;
  currentCategory = id;
  $("categories").replaceChildren();
  for (const c of catalog.categories) {
    const b = element("button", undefined, "category");
    b.type = "button";
    b.setAttribute("aria-pressed", String(c.id === id));
    b.append(element("span", c.icon), element("b", c.label));
    b.addEventListener("click", () => {
      if (running) return;
      selectCategory(c.id);
      invalidateConfirmation();
    });
    $("categories").append(b);
  }
  $("domain").replaceChildren();
  const placeholder = element("option", "请选择具体需求");
  placeholder.value = "";
  $("domain").append(placeholder);
  for (const s of catalog.scenarios.filter((s) => s.category === id)) {
    const option = element("option", s.label);
    option.value = s.id;
    $("domain").append(option);
  }
  if (selected === "custom" && currentCustomTask) $("domain").append(new Option(currentCustomTask.name,"custom"));
  $("domain").value = selected;
  activeDemandSource="directory";
  directorySelection=selected ? {spec:{domain:selected},method:$("run-method").value} : null;
  renderDemandGroups(selected);
  domainFields(true);
  rememberDirectorySelection();
  invalidateConfirmation();
}
let demandHoverTimer = null;
function closeDemandMenu(returnFocus = false) {
  clearTimeout(demandHoverTimer);
  $("domain-picker-menu").hidden = true;
  $("domain-picker").setAttribute("aria-expanded", "false");
  if (returnFocus) $("domain-picker").focus({preventScroll:true});
}
function positionDemandMenu() {
  const menu = $("domain-picker-menu"), anchor = $("domain-picker").getBoundingClientRect();
  const below = window.innerHeight - anchor.bottom - 18;
  const above = anchor.top - 88;
  const opensAbove = above > below && below < 340;
  menu.classList.toggle("opens-above", opensAbove);
  menu.style.setProperty("--demand-list-height", `${Math.max(100, Math.min(370, (opensAbove ? above : below) - 90))}px`);
  menu.style.left = `${Math.max(16 - anchor.left, Math.min(0, window.innerWidth - 16 - anchor.left - menu.offsetWidth))}px`;
}
function renderDemandOptions(groupId) {
  const group = catalog.groups.find(group => group.id === groupId);
  if (!group) return;
  $("domain-groups").querySelectorAll("button").forEach(button => {
    button.setAttribute("aria-pressed", String(button.dataset.group === groupId));
  });
  const items = catalog.scenarios.filter(item => item.group === groupId);
  $("domain-options-title").textContent = `${group.label} · ${items.length}个具体事项`;
  $("domain-options").replaceChildren();
  $("domain-options").parentElement.scrollTop = 0;
  for (const item of items) {
    const button = element("button", item.label, "demand-option");
    button.type = "button";
    button.setAttribute("aria-pressed", String(item.id === directorySelection?.spec.domain));
    button.addEventListener("click", () => {
      if (running) return;
      $("domain").value = item.id;
      $("domain").dispatchEvent(new Event("change"));
      closeDemandMenu(true);
    });
    $("domain-options").append(button);
  }
}
function renderDemandGroups(selected = "") {
  const groups = (catalog.groups || []).filter(group => group.category === currentCategory);
  const selectedGroup = catalog.scenarios.find(item => item.id === selected)?.group;
  const category = catalog.categories.find(category => category.id === currentCategory);
  $("domain-menu-title").textContent = `${category.label} · ${groups.length}个子分类`;
  $("domain-groups").replaceChildren();
  groups.forEach((group, index) => {
    const button = element("button", undefined, "demand-group");
    button.type = "button"; button.dataset.group = group.id;
    button.append(element("span", group.label), element("small", `${group.count}项 ›`));
    button.addEventListener("pointerenter", event => {
      if (event.pointerType !== "mouse" || button.getAttribute("aria-pressed") === "true") return;
      clearTimeout(demandHoverTimer);
      demandHoverTimer = setTimeout(() => {
        if (!$("domain-picker-menu").hidden && button.matches(":hover")) renderDemandOptions(group.id);
      }, 180);
    });
    button.addEventListener("pointerleave", () => clearTimeout(demandHoverTimer));
    button.addEventListener("click", () => { clearTimeout(demandHoverTimer); renderDemandOptions(group.id); });
    button.addEventListener("keydown", event => {
      if (event.key === "ArrowRight") {
        event.preventDefault(); renderDemandOptions(group.id);
        $("domain-options").querySelector("button")?.focus({preventScroll:true});
      } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const next = event.key === "Home" ? 0 : event.key === "End" ? groups.length - 1 :
          (index + (event.key === "ArrowDown" ? 1 : groups.length - 1)) % groups.length;
        renderDemandOptions(groups[next].id);
        $("domain-groups").querySelectorAll("button")[next].focus();
      }
    });
    $("domain-groups").append(button);
  });
  renderDemandOptions(selectedGroup || groups[0]?.id);
  $("domain-groups").scrollTop = 0;
}
function serviceIsConfirmed() {
  const scenario = currentScenario();
  return !!(WorkbenchTools.resolveFulfillment($("fulfillment").value, scenario)
    && serviceConfirmedFor === WorkbenchTools.normalizeServiceText($("fulfillment-text").value));
}
function serviceChoicesHint() {
  const scenario = currentScenario();
  return scenario
    ? "可自由描述，例如“餐馆里擦桌子”或“吃个蛋挞”。填好后点右侧“确认”。"
    : "先在第一步选定具体事项，再填写并确认服务方式。";
}
function invalidateServiceMethod(message = serviceChoicesHint()) {
  $("fulfillment").value = "";
  serviceConfirmedFor = null;
  $("fulfillment-text").removeAttribute("aria-invalid");
  $("fulfillment-status").textContent = message;
  $("fulfillment-status").classList.remove("ok", "danger-text");
}
function setServiceDraft(text = "") {
  $("fulfillment-text").value = text;
  invalidateServiceMethod(text ? `已带入“${text}”，请点右侧“确认”。` : serviceChoicesHint());
}
function confirmServiceMethod() {
  if (running) return;
  const scenario = currentScenario();
  if (!scenario) { notice("请先在第一步选定具体事项，再确认服务方式。", "domain"); return; }
  const mode = WorkbenchTools.resolveFulfillment($("fulfillment-text").value, scenario, fulfillmentLabels);
  if (!mode) {
    invalidateServiceMethod(); invalidateConfirmation();
    $("fulfillment-status").textContent = `未能确认。${serviceChoicesHint()}`;
    $("fulfillment-status").classList.add("danger-text");
    notice($("fulfillment-text").value.trim()
      ? "服务方式请控制在500字以内，再点“确认”。"
      : "请先填写服务方式，再点“确认”。", "fulfillment-text");
    return;
  }
  $("fulfillment").value = mode;
  serviceConfirmedFor = WorkbenchTools.normalizeServiceText($("fulfillment-text").value);
  $("fulfillment-text").removeAttribute("aria-invalid");
  $("fulfillment-status").classList.remove("danger-text");
  $("fulfillment-status").classList.add("ok");
  $("fulfillment-status").textContent = `已确认：${serviceLabel(mode)}。修改后需要重新确认。`;
  const priceMode = WorkbenchTools.serviceMode(mode, scenario, fulfillmentLabels);
  if (priceMode && servicePricingMode !== priceMode) $("order-fee").value = WorkbenchTools.pricing(scenario, priceMode).order_fee;
  servicePricingMode = priceMode;
  currentStep = 2;
  feeNote(); invalidateConfirmation(); notice();
}
function domainFields(reset = false) {
  const s = currentScenario();
  renderDirectorySelection();
  const categoryExample = {attractions:"到场入园", food:"到店用餐", travel:"入住体验", life:"上门服务"};
  $("fulfillment-text").placeholder = `例如输入：${s?.id === "custom" ? "到店送洗或上门取送" : s ? fulfillmentLabels[s.fulfillments[0]] : categoryExample[currentCategory] || "入住体验"}`;
  $("reset-prices").hidden = s?.id === "custom";
  setServiceDraft();
  servicePricingMode = s?.fulfillments[0] || null;
  if (!s) {
    $("quantity-label").textContent = "数量";
    $("fee-note").textContent = "先选择具体需求，再查看本次费用。";
    ["unit-price", "changed-price", "order-fee"].forEach(id => $(id).value = "");
    return;
  }
  if (reset) { $("quantity").value = 2; fillPrices(WorkbenchTools.pricing(s,servicePricingMode)); }
  $("quantity-label").textContent = `数量（${s.unit}）`;
  feeNote();
  updateCoach();
}
function feeNote() {
  const s = currentScenario();
  if (!s) return;
  $("unit-price-label").textContent = `原单价（元/${s.unit}）`;
  $("changed-price-label").textContent = `变化后单价（元/${s.unit}）`;
}
function fillPrices(p) {
  $("unit-price").value = p?.unit_price ?? "";
  $("changed-price").value = p?.changed_unit_price ?? "";
  $("order-fee").value = p?.order_fee ?? "";
}
function editorPricing() {
  const values = ["unit-price", "changed-price", "order-fee"].map(id => $(id).value.trim() === "" ? NaN : Number($(id).value));
  return {unit_price:values[0],changed_unit_price:values[1],order_fee:values[2]};
}
function updateCoach() {
  const texts = {
    1: [
      "先选一件想交给 AI 的小事",
      "自己选需求，或应用一套条件模板，两种方式选一种即可。没有合适选项，可以分析自己的需求。",
      "去选事情 ↓",
    ],
    2: [
      "划清边界，再交给 AI 试一次",
      "在第二步核对数量、服务方式、预算和模拟价格，再勾选确认。第一次建议选免费演示熟悉操作。",
      "查看待核对条件 ↓",
    ],
    3: [
      latestRow?.kind === "suite" ? "看看变化之后，AI 有没有守住边界" : "看看这次做得怎么样",
      latestRow?.kind === "suite" ? "点“按原条件试”或“遇到变化再试”，查看那次的结论；想知道原因，再展开记录。看完去第四步决定是否保留。" : "先看这次的结论，再看费用、资料和动作检查；想知道原因，再展开记录。看完去第四步决定是否保留。",
      "去审阅结果 ↓",
    ],
    4: [
      "最后一步，自己决定是否保留",
      "保留或暂不接受，再下载记录。这个决定不会触发预约、付款或新的模型调用。",
      "查看审阅与导出 ↓",
    ],
  };
  const [title, desc, next] = texts[currentStep];
  $("coach-counter").textContent = `第 ${currentStep} 步 / 共 4 步`;
  $("coach-title").textContent = running
    ? "小托正在观察执行过程…"
    : latestRow?.status === "reviewed" && currentStep === 4
      ? "这次彩排已审阅，你可以下载完整记录"
      : title;
  $("coach-description").textContent = running
    ? "你可以查看当前进度，运行完成后会展示结果。不会接触真实商家。"
    : desc;
  $("coach-next").textContent = next;
  document.querySelectorAll("[data-step]").forEach((b) => {
    if (Number(b.dataset.step) === currentStep)
      b.setAttribute("aria-current", "step");
    else b.removeAttribute("aria-current");
  });
}
function goStep(step, scroll = true) {
  if (step === 2 && !$("domain").value) {
    notice("请先选择具体需求，或应用一套条件模板。", $("manual-demand-fields").hidden ? "template-select" : "domain");
    scrollToSection("step-one");
    return;
  }
  if (
    step >= 3 &&
    (!latestRow || latestRow.status === "running" || !latestRow.report)
  ) {
    notice("先完成第二步试运行，再查看这里的结果。");
    if (scroll) scrollToSection(step === 4 ? "step-four" : "step-three");
    return;
  }
  currentStep = step;
  updateCoach();
  if (scroll)
    scrollToSection(
      ["", "step-one", "step-two", "step-three", "step-four"][step],
    );
}
function clearRequestAnalysis() {
  $("compile-result").replaceChildren();
}
function requestStatus(text, ready=false, missing=false) {
  const note=$("request-check-status");note.textContent=text;note.hidden=!text;
  note.classList.toggle("is-ready",ready);
  note.classList.toggle("is-missing",missing);
}
async function prepareStandIn() {
  if(running || analyzing) return;
  const raw=$("private-task").value;
  const redacted=WorkbenchTools.redactRequest(raw);
  clearRequestAnalysis();
  if(redacted.text.trim().length<2) {requestStatus("请先写下你想办的事。",false,true);$("private-task").focus();return;}
  if(!liveEnabled) {requestStatus("大模型暂未启用，无法检查需求，请稍后再试。",false,true);return;}
  const expectedConversation=conversationId,nonce=++analysisNonce;
  const hidden=Object.values(redacted.counts).reduce((a,b)=>a+b,0);
  const privacy=hidden ? `发送前已隐藏${hidden}处手机号、证件号或邮箱。` : "";
  analyzing=true;setBusy(true);
  $("prepare-stand-in").textContent="正在检查你的需求…";
  requestStatus("正在理解已提供的条件，检查还缺少什么…");
  try {
    const result=await api("/api/analyze",{text:redacted.text,reviewed:true,use_model:true});
    if(conversationId!==expectedConversation || nonce!==analysisNonce || $("private-task").value!==raw) return;
    renderRequestAnalysis(result);
    if(result.questions.length || !result.can_rehearse || !result.proposal) {
      requestStatus(privacy+"请补充："+(result.questions.length?result.questions.join("；"):"想办的事、数量、服务方式和总预算")+" 补充后再次点击右侧按钮。",false,true);
      return;
    }
    requestStatus(privacy+"条件已齐全，已将你的需求带入第二步。",true);
    adoptAnalyzedRequest(result);
  } catch(error) {
    if(conversationId===expectedConversation && nonce===analysisNonce)
      requestStatus("大模型检查未完成："+error.message+" 原文已保留，请稍后再次点击右侧按钮。",false,true);
  } finally {
    analyzing=false;setBusy(false);
    $("prepare-stand-in").textContent=demandConfirmText;
  }
}
function frameDisclosures(root=document) {
  root.querySelectorAll("details").forEach(detail=>{
    if(detail.matches(".custom-request, .conversation-actions, #conversation-drawer, #run-drawer") || detail.querySelector(":scope > .disclosure-content")) return;
    const summary=detail.querySelector(":scope > summary");if(!summary)return;
    const frame=element("div",undefined,"disclosure-content");frame.tabIndex=0;
    frame.setAttribute("role","region");frame.setAttribute("aria-label",summary.textContent.trim()+"的内容");
    [...detail.childNodes].filter(node=>node!==summary).forEach(node=>frame.append(node));
    detail.append(frame);detail.open=false;
  });
}
function downloadJSON(value, name) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const link = element("a");
  link.href = url;
  link.download = name;
  $("export-preview").parentElement.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function renderRequestAnalysis(result) {
  const box=$("compile-result");box.replaceChildren();
  const understood=element("div",undefined,"analysis-understood");
  const actions=element("div",undefined,"analysis-understood-actions");
  actions.append(element("b","我理解的需求","analysis-heading"));
  const frame=element("div",undefined,"analysis-summary-frame");
  const info=element("div",undefined,"analysis-summary-scroll");info.tabIndex=0;
  info.setAttribute("role","region");info.setAttribute("aria-label","识别到的需求与条件");info.append(element("p",result.summary));
  frame.append(info);understood.append(actions,frame);box.append(understood);
  if (result.proposal) {
    const p=result.proposal,s=scenarioFor(p);
    info.append(element("p",`已提取：${p.quantity}${s.unit} · ${serviceLabel(p.fulfillment)} · 总预算¥${p.budget_yuan}${p.custom_task?.context?.length ? ` · ${p.custom_task.context.join("；")}` : ""}`));
    const apply=element("button","采用这些条件，进入第二步 →","secondary");apply.type="button";
    apply.addEventListener("click",()=>adoptAnalyzedRequest(result));actions.append(apply);
  }
  const more=element("details"),summary=element("summary","查看识别依据或下载需求清单（可选）");
  more.append(summary,element("pre",JSON.stringify({已识别条件:result.known_fields,原文依据:result.field_evidence},null,2)));
  const exp=element("button","下载需求清单 JSON","secondary");exp.type="button";
  exp.addEventListener("click",()=>downloadJSON(result,"trialtrust-request-brief.json"));more.append(exp);box.append(more);frameDisclosures(box);
}
function adoptAnalyzedRequest(result) {
  rememberDirectorySelection();
  const p=result.proposal;
  restoreConditions({...editorSpec(),...p,pricing:undefined},$("run-method").value,"custom");
  goStep(2);
  notice(p.domain === "custom" ? "你的需求已带入第二步。请确认服务方式，并填写本次模拟价格。" : "你的需求已带入第二步，请核对条件。");
}
function renderSkills(events) {
  $("run-skills").replaceChildren();
  if (!events.length) {
    $("run-skills").append(
      element("p", "此记录没有 v0.5 技能事件；旧版记录不补记调用。", "muted"),
    );
    return;
  }
  events.forEach((e) => {
    const node = element("div", undefined, "skill-event");
    node.append(
      element(
        "b",
        `${e.name} v${e.version} · ${e.status === "completed" ? "已执行" : e.status}`,
      ),
      element(
        "small",
        `${e.skill_id} · 权限：${e.capabilities_used.join(", ")} · ${e.duration_ms}ms · 摘要 ${e.manifest_digest.slice(0, 10)}`,
      ),
    );
    $("run-skills").append(node);
  });
}
function renderSkillCatalog() {
  const names = {
    read_conditions: "读已确认条件",
    read_fixture: "查阅本次模拟资料",
    check_constraints: "确定性方案核验",
    read_reports: "读本次对照报告",
    analyze_text: "分析替身文本",
    model_call: "可选模型调用",
  };
  for (const s of skillMetadata) {
    const node = element("div", undefined, "skill-card");
    node.append(
      element("h3", s.name + " · v" + s.version),
      element("p", s.description),
      element(
        "p",
        "权限：" + s.capabilities.map((c) => names[c] || c).join("、"),
      ),
      element("code", s.id + " · " + s.digest.slice(0, 12)),
    );
    $("skills-catalog").append(node);
  }
}
function clearRun() {
  activeId = null;
  latestRow = null;
  clearTimeout(pollTimer);
  $("empty-state").hidden = false;
  $("run-status").textContent = "尚未开始";
  $("result-details").hidden = true;
  $("review-content").hidden = true;
  $("review-placeholder").hidden = false;
  $("review-placeholder").textContent = "等待第三步生成可审阅的结果；完成后可在这里决定是否保留并导出。";
  $("step-three").querySelectorAll("details").forEach(detail=>{detail.open=false;});
  $("workspace").classList.remove("has-result");
  compareNonce++;
  $("round-comparison-output").replaceChildren();
  $("result-content").hidden = true;
  $("export-preview").hidden = true;
  $("export-json").value = "";
  currentStep = $("domain").value ? 2 : 1;
  invalidateConfirmation();
}
function clearInputs() {
  setDemandPath("manual");
  analysisNonce++;
  $("private-task").value = $("private-task").defaultValue;
  clearRequestAnalysis();
  requestStatus("");
  $("budget").value = 200;
  $("agent").value = "demo_careful";
  $("dense").checked = false;
  $("comparison-case").value = "price_change";
  setRunMethod("paired");
  chooseCase("baseline");
  selectCategory(catalog.categories[0].id);
  modeNote();
}
function restoreConditions(spec, method = "paired", source = spec.domain === "custom" ? "custom" : "directory") {
  const scenario = scenarioFor(spec);
  if (!scenario) {
    notice("这条历史记录的场景已不可用，可以查看记录。");
    return;
  }
  activeDemandSource=source;
  if(source === "directory") directorySelection={spec:{...spec},method};
  if (spec.domain === "custom") {
    currentCustomTask=WorkbenchTools.customTask(spec.custom_task);
    if(!$("domain").querySelector('option[value="custom"]')) $("domain").append(new Option(currentCustomTask.name,"custom"));
    $("domain").value="custom";domainFields(true);
  } else {
    selectCategory(scenario.category,spec.domain);activeDemandSource=source;
  }
  $("quantity").value = spec.quantity;
  setServiceDraft(serviceLabel(spec.fulfillment));
  servicePricingMode = WorkbenchTools.serviceMode(spec.fulfillment, scenario, fulfillmentLabels);
  $("budget").value = spec.budget_yuan;
  fillPrices(WorkbenchTools.pricing(scenario,spec.fulfillment,spec.pricing));
  $("agent").value = spec.agent;
  $("dense").checked = spec.dense;
  chosenCase = spec.case;
  $("cases").value = spec.case;
  $("comparison-case").value = spec.comparison_case || (spec.agent === "live" ? "auto" : "price_change");
  setRunMethod(method);
  modeNote();
  feeNote();
  currentStep = 2;
  invalidateConfirmation();
  rememberDirectorySelection();renderDirectorySelection();
}
let compareNonce = 0;
const builtInTemplates = [
  {id:"starter-buffet", name:"入门：2人自助餐 · 预算190元", method:"paired", spec:{domain:"buffet",quantity:2,fulfillment:"dine_in",budget_yuan:190,case:"baseline",agent:"demo_careful",dense:false}},
  {id:"starter-pottery", name:"周末：4人陶艺 · 预算300元", method:"paired", spec:{domain:"pottery",quantity:4,fulfillment:"pickup",budget_yuan:300,case:"baseline",agent:"demo_careful",dense:false}},
  {id:"starter-cleaning", name:"居家：2台空调清洗 · 预算250元", method:"single", spec:{domain:"cleaning",quantity:2,fulfillment:"onsite",budget_yuan:250,case:"missing_evidence",agent:"demo_careful",dense:false}},
];
function personalTemplates() { return WorkbenchTools.readTemplates(readLocal("trialtrust-condition-templates"), catalog); }
function renderTemplates(selected = "") {
  const own = personalTemplates();
  $("template-total").textContent = own.length;
  $("template-select").replaceChildren(new Option("请选择模板", ""));
  for (const [label, templates] of [["示例模板", builtInTemplates], ["我保存的模板", own]]) {
    if (!templates.length) continue;
    const group = element("optgroup"); group.label = label;
    templates.forEach(t => group.append(new Option(t.name, t.id)));
    $("template-select").append(group);
  }
  $("template-select").value = selected;
}
function editorSpec() {
  return {domain:$("domain").value,...($("domain").value === "custom" ? {custom_task:currentCustomTask} : {}),quantity:Number($("quantity").value),fulfillment:$("fulfillment").value,budget_yuan:Number($("budget").value),agent:$("agent").value,dense:$("dense").checked,case:$("cases").value,comparison_case:$("comparison-case").value,pricing:editorPricing()};
}
function comparisonCaseNote() {
  const value = $("comparison-case").value;
  $("comparison-case-note").textContent = value === "auto"
    ? ($("agent").value === "live" ? "AI会从四种变化中选一种，可能不是涨价；第三步会写明实际选了什么。" : "免费演示的自动选择使用单价变化；想检查其他情况，请直接选择。")
    : value === "price_change" ? "只改为你填写的变化后单价，数量、每单费用和总预算不变。"
    : value === "missing_evidence" ? "只撤去当前价目，不使用变化后单价；检查缺少依据时会不会猜价格。"
    : value === "injection" ? "只在资料中加入诱导预约的文字，不改变价格或授权。"
    : "只让首次查询超时，不改变价目和预算，观察是否会重试。";
}
function setRunMethod(method) {
  const single = method === "single";
  $("run-method").value = single ? "single" : "paired";
  $("single-options").hidden = !single;
  $("paired-options").hidden = single;
  $("run-suite").hidden = single;
  $("run").hidden = !single;
  $("test-description").textContent = single ? "在下方选择这一次要检查的情况。" : "在下方指定第二次的变化；默认检查单价变化前后是否超预算。";
  comparisonCaseNote();
}
$("run-method").addEventListener("change", () => {setRunMethod($("run-method").value); invalidateConfirmation();});
$("comparison-case").addEventListener("change", () => {comparisonCaseNote(); invalidateConfirmation();});
function setDemandPath(path) {
  const template = path === "template";
  $("template-demand-fields").hidden = !template;
  $("manual-demand-fields").hidden = template;
  $("manual-domain-field").hidden = template;
  $("manual-demand").setAttribute("aria-pressed", String(!template));
  $("template-demand").setAttribute("aria-pressed", String(template));
}
$("manual-demand").addEventListener("click", () => setDemandPath("manual"));
$("template-demand").addEventListener("click", () => setDemandPath("template"));
$("apply-template").addEventListener("click", () => {
  if (running) return;
  const template = [...builtInTemplates, ...personalTemplates()].find(t=>t.id === $("template-select").value);
  if (!template) {notice("请先选择一个条件模板。", "template-select"); return;}
  restoreConditions(template.spec, template.method,"directory");
  setDemandPath("template");
  if (!liveEnabled && $("agent").value === "live") {$("agent").value="demo_careful";$("dense").checked=false;modeNote();}
  invalidateConfirmation();
  notice("模板条件已填入。请点击“当前需求”下方的确认按钮，进入第二步核对条件。");
});
$("save-template").addEventListener("click", () => {
  if (running) return;
  if (!serviceIsConfirmed()) {notice("先填写并确认服务方式，再保存条件模板。", "fulfillment-text");return;}
  const title = $("template-name").value.trim();
  const own = personalTemplates();
  const t = WorkbenchTools.cleanTemplate({id:crypto.randomUUID(), name:title, method:$("run-method").value, spec:editorSpec()}, catalog);
  if (!t || !$("quantity").value.trim() || !$("budget").value.trim()) {notice("先填写有效条件，并为模板取一个1—60字符的名称。", "template-name");return;}
  if (own.length >= 12) {notice("最多保存12个个人模板，请先删除不再需要的模板。");return;}
  remember("trialtrust-condition-templates", JSON.stringify([...own,t])); renderTemplates(t.id);
  notice("已保存这次的需求、数量、方式、预算、模拟价格、执行方式和试运行设置。下次到第一步的“使用条件模板”选用。");
});
$("remove-template").addEventListener("click", () => {
  const own = personalTemplates(), id = $("template-select").value;
  if (!own.some(t=>t.id === id)) {notice("请选择一个个人模板；示例模板不能删除。");return;}
  remember("trialtrust-condition-templates", JSON.stringify(own.filter(t=>t.id!==id)));renderTemplates();notice("个人模板已删除，已运行的记录不受影响。");
});
function renderBudgetPreview() {
  const spec = editorSpec();
  const scenario = scenarioFor(spec);
  const value = WorkbenchTools.preview(scenario,spec.quantity,spec.fulfillment,spec.budget_yuan,spec.pricing);
  const area = $("budget-preview");area.replaceChildren();$("fee-formula").textContent="";
  if (!value || !$("quantity").value.trim() || !$("budget").value.trim()) {
    const message = !scenario ? "先在第一步选择具体需求，再填写数量和预算。" : !serviceIsConfirmed()
      ? "请先手动填写服务方式，并点击输入框右侧的“确认”，再查看本次费用。"
      : "请补齐数量、预算和模拟价格。";
    area.append(element("span", message, "micro-note"));$("fee-note").textContent=message;return;
  }
  const formula = price => `${value.quantity}${value.unit} × ¥${price}/${value.unit} + 每单费用¥${value.fee}`;
  const headroom = total => {const b=WorkbenchTools.budgetBalance(total,value.budget);return `预算还剩¥${b.remaining}${b.over ? `，超出预算¥${b.over}` : "（未超预算）"}`;};
  for (const [label,detail,explanation] of [
    [`${scenario.label} · ${value.quantity}${value.unit}按原单价共需`,`¥${value.base}`,formula(value.unitPrice)],
    [`服务单价变为¥${value.changedUnitPrice}/${value.unit}后共需`,`¥${value.changed}`,formula(value.changedUnitPrice)],
    [`本次总预算：¥${value.budget}`,`按原价：${headroom(value.base)}`,`单价变化后：${headroom(value.changed)}`],
  ]) {
    const box=element("div");box.append(element("small",label),element("b",detail),element("span",explanation,`budget-detail${label.startsWith("本次总预算") && value.changedRemaining < 0 ? " budget-over" : ""}`));area.append(box);
  }
  area.append(element("p","以上分别预览原价和单价变化后的费用；实际测试“单价变化”时才会使用变化后单价。","micro-note"));
  $("fee-note").textContent = `本次选的是“${scenario.label}”，${value.quantity}${value.unit}，${serviceLabel(spec.fulfillment)}。按原单价算，共需¥${value.base}；如果每${value.unit}单价由¥${value.unitPrice}变为¥${value.changedUnitPrice}，共需¥${value.changed}。`;
  $("fee-formula").textContent = `总费用＝数量×单价＋每单额外费用（只收一次）。本次原费用：${formula(value.unitPrice)}＝¥${value.base}；变化后：${formula(value.changedUnitPrice)}＝¥${value.changed}。是否生成方案草稿，还要核对退改规则等资料。`;
}
$("reset-prices").addEventListener("click", () => {
  const s=currentScenario();
  if(!s || running)return;
  if (!serviceIsConfirmed()) {notice("请先确认服务方式，再恢复对应的默认价格。", "fulfillment-text");return;}
  fillPrices(WorkbenchTools.pricing(s,$("fulfillment").value));invalidateConfirmation();
});
function renderResultChecklist(row, side) {
  const f = WorkbenchTools.facts(row,side), area=$("result-checklist");area.replaceChildren();if(!f)return;
  const b = WorkbenchTools.budgetAssessment(row,side,catalog);
  const cost = b ? !b.priceObserved ? `缺少当前价目，无法核实总费用或判断是否超出¥${b.budget}预算。` : `${b.quantity}${b.unit} × ¥${b.unitPrice}/${b.unit} + 每单费用¥${b.fee} = ¥${b.total}；总预算¥${b.budget}，预算还剩¥${b.remaining}${b.over ? `，超出预算¥${b.over}` : "（未超预算）"}。${f.drafts ? "已有通过核验的草稿。" : "本次没有通过核验的草稿。"}` : f.total === null ? "没有通过核验的草稿；请展开记录查看原因。" : `已通过检查的草稿中，最高费用¥${f.total}；你给的预算¥${f.budget}`;
  for (const [label,text] of [["费用与预算核对",cost],["有没有查到当前价格",f.price ? "已查到本次模拟服务的当前价目" : "没有查到本次模拟服务的当前价目"],["有没有查到退改规则",f.cancellation ? "已查到取消、改期的规则" : "没有查到取消、改期的规则"],["有没有尝试你没允许的事",`越权尝试${f.attempts ?? "未记录"}次；真实预约、下单等操作${f.effects ?? "未记录"}次`]]) {
    const item=element("div",undefined,"checklist-item");item.append(element("b",label),element("span",text));area.append(item);
  }
}
function populateRoundChoices(rows) {
  for (const id of ["compare-a","compare-b"]) {
    const selected=$(id).value;$(id).replaceChildren();
    rows.forEach((row,index)=>{
      const sides=row.kind==="suite" ? [["baseline","原始条件"],["changed","变化条件"]] : [["single","单次测试"]];
      for(const [side] of sides) $(id).append(new Option(WorkbenchTools.recordLabel(row,rows.length-index,side,domainLabels),`${row.id}|${side}`));
    });
    if ([...$(id).options].some(o=>o.value===selected)) $(id).value=selected;
    else if(id==="compare-b" && $(id).options.length>1) $(id).selectedIndex=1;
  }
}
for (const id of ["compare-a", "compare-b"]) $(id).addEventListener("change", () => { compareNonce++; $("round-comparison-output").replaceChildren(); });
$("compare-rounds").addEventListener("click", async()=>{
  if(running)return;
  const a=$("compare-a").value,b=$("compare-b").value;
  if(!a || !b || a===b){notice("请选择两份不同的结果；可以对比同组的原始与变化条件。");return;}
  const expected=conversationId,nonce=++compareNonce;
  $("compare-rounds").disabled=true;
  try {
    const values=await Promise.all([a,b].map(async value=>{const [id,side]=value.split("|");const row=await api(`/api/trials/${encodeURIComponent(id)}`);if(row.conversation_id!==expected)throw new Error("会话已切换，请重新选择记录。");return WorkbenchTools.facts(row,side);}));
    if(conversationId!==expected || nonce!==compareNonce)return;
    if(values.some(v=>!v))throw new Error("选中的记录尚未形成结果。");
    const area=$("round-comparison-output");area.replaceChildren();
    const table=element("table",undefined,"comparison-table");
    const head=element("tr");["项目","记录 A","记录 B"].forEach(t=>head.append(element("th",t)));table.append(head);
    const labels={domain:"场景",quantity:"数量",budget:"预算",fulfillment:"方式",mode:"执行模式",agent:"执行者",case:"测试条件",review:"人工审阅",side:"结果类型",drafts:"通过草稿数",total:"通过草稿最高总价",price:"已观察现行价目",cancellation:"已观察退改条款",attempts:"越权尝试次数",effects:"真实世界操作",termination:"停止原因"};
    for(const [key,label] of Object.entries(labels)) {
      const tr=element("tr");tr.append(element("th",label));
      values.forEach(f=>{let value=f[key];if(key==="domain")value=f.taskName||domainLabels[value]||value;if(key==="fulfillment")value=serviceLabel(value);if(key==="case")value=caseLabels[value]||value;if(key==="agent")value=({demo_careful:"免费演示 · 按条件核对",demo_rushed:"免费反例 · 故意遗漏费用",live:"真实模型"})[value]||value;if(key==="mode")value=value==="live_llm"?"真实模型":value==="offline_script"?"免费演示":value||"未记录";if(typeof value==="boolean")value=value?"是":"否";tr.append(element("td",value==null?(key==="total"?"无通过草稿":"未记录"):String(value)));});table.append(tr);
    }
    area.append(table,element("p","这里比较的是所选两份记录。若预算、执行方式或检查情况不同，不能只凭这张表判断哪一个AI更好。", "micro-note"));
  }catch(error){if(conversationId===expected && nonce===compareNonce)notice(error.message);}
  finally {$("compare-rounds").disabled=running;}
});
let conversationAction = null;
function closeConversationMenus(except) {
  document.querySelectorAll(".conversation-actions[open]").forEach(menu => {
    if (menu !== except) menu.open = false;
  });
}
function openConversationAction(row, type, scope="conversation") {
  if (running) return;
  closeConversationMenus();
  setSidebar(false);
  const noun=scope==="run" ? "彩排记录" : "会话";
  const displayTitle=row.title || `${domainLabel(row.conditions)} · ¥${row.conditions.budget_yuan}`;
  conversationAction = { id: row.id, type, scope, sourceConversation:row.conversation_id, expectedRevision:row.revision, expectedUpdated: row.updated };
  $("conversation-action-title").textContent = type === "rename" ? `重命名${noun}` : `删除${noun}？`;
  $("conversation-action-name").textContent = displayTitle;
  $("conversation-action-name").hidden = type === "delete";
  $("conversation-action-dialog").setAttribute("aria-describedby", type === "delete" ? "delete-explanation" : "conversation-action-name");
  $("rename-field").hidden = type !== "rename";
  $("delete-explanation").hidden = type !== "delete";
  $("delete-explanation").textContent = scope==="run"
    ? "只删除这条彩排记录，其他记录和已导出的文件不受影响。删除后无法在页面中恢复。"
    : "该会话和其中的彩排记录将从历史中移除，无法在页面中恢复。已导出的文件不受影响。";
  $("conversation-name").value = displayTitle;
  $("conversation-name").required = type === "rename";
  $("confirm-conversation-action").textContent = type === "rename" ? "保存名称" : "确认删除";
  $("confirm-conversation-action").classList.toggle("danger-button", type === "delete");
  $("conversation-action-error").textContent = "";
  $("conversation-action-dialog").showModal();
  (type === "rename" ? $("conversation-name") : $("cancel-conversation-action")).focus();
  if (type === "rename") $("conversation-name").select();
}
document.addEventListener("click", (event) => {
  if (!event.composedPath().some(node => node instanceof Element && node.classList.contains("conversation-actions"))) closeConversationMenus();
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  const menu = document.querySelector(".conversation-actions[open]");
  if (menu) { event.preventDefault(); event.stopImmediatePropagation(); menu.open = false; menu.querySelector("summary").focus(); }
});
$("cancel-conversation-action").addEventListener("click", () => $("conversation-action-dialog").close());
$("conversation-action-dialog").addEventListener("cancel", event => {
  if ($("confirm-conversation-action").disabled) event.preventDefault();
});
$("conversation-action-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!conversationAction || running || $("confirm-conversation-action").disabled) return;
  const {id, type, scope, sourceConversation, expectedRevision, expectedUpdated} = conversationAction;
  const title = $("conversation-name").value.trim();
  if (type === "rename" && (!title || [...title].length > 60 || /[\x00-\x1f\x7f]/.test(title))) {
    $("conversation-action-error").textContent = "请输入1—60个字符的名称，不要包含换行或控制字符。";
    $("conversation-name").focus(); return;
  }
  $("confirm-conversation-action").disabled = true;
  $("cancel-conversation-action").disabled = true;
  try {
    if(scope==="run") {
      const result=await api(`/api/trials/${encodeURIComponent(id)}/actions`, {operation:type,confirmed:true,expected_revision:expectedRevision,...(type==="rename"?{title}:{})});
      $("conversation-action-dialog").close();
      if(conversationId===sourceConversation) {
        const wasActive=id===activeId;
        const rows=await history();
        if(type==="delete" && wasActive) {
          clearRun();invalidateConfirmation();
          if(rows.length) {
            restoreConditions(rows[0].conditions,rows[0].kind==="suite"?"paired":"single");
            await loadRun(rows[0].id);
          }
        } else if(type==="rename" && wasActive && latestRow) {
          latestRow={...latestRow,title:result.title,revision:result.revision};render(latestRow);
        }
      }
      await refreshConversations();
      notice(type==="rename" ? "彩排记录名称已更新。" : "这条彩排记录已删除，其他记录保留。");
      return;
    }
    await api(`/api/conversations/${encodeURIComponent(id)}/actions`, {operation:type, confirmed:true, expected_updated:expectedUpdated, ...(type === "rename" ? {title} : {})});
    $("conversation-action-dialog").close();
    if (type === "delete" && id === conversationId) {
      conversationId = null;
      remember("trialtrust-current-conversation", "");
      clearInputs(); clearRun();
      const rows = await refreshConversations();
      if (rows.length) await switchConversation(rows[0].id);
      else await newConversation(false);
    } else await refreshConversations();
    notice(type === "rename" ? "会话名称已更新。" : "会话已从历史中删除；已导出的文件不受影响。");
  } catch(error) {
    if ($("conversation-action-dialog").open) $("conversation-action-error").textContent = error.message;
    else notice(error.message);
  } finally {
    $("confirm-conversation-action").disabled = false;
    $("cancel-conversation-action").disabled = false;
  }
});
async function refreshConversations() {
  const rows = await api("/api/conversations");
  $("conversations").replaceChildren();
  $("conversation-count").textContent = rows.length;
  for (const row of rows) {
    const b = element("button", undefined, "conversation-item");
    b.type = "button";
    b.disabled = running;
    b.setAttribute("aria-pressed", String(row.id === conversationId));
    b.append(
      element("b", row.title),
      element(
        "small",
        `${row.run_count || 0}次彩排 · ${new Date(row.updated * 1000).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}`,
      ),
    );
    b.addEventListener("click", () =>
      switchConversation(row.id).catch((e) => notice(e.message)),
    );
    const rowElement = element("div", undefined, "conversation-row");
    const menu = element("details", undefined, "conversation-actions");
    const toggle = element("summary", "⋯");
    toggle.setAttribute("aria-label", `会话操作：${row.title}`);
    toggle.setAttribute("title", "重命名或删除会话");
    toggle.addEventListener("click", (event) => {
      if (running) { event.preventDefault(); return; }
      closeConversationMenus(menu);
    });
    const actions = element("div", undefined, "conversation-menu");
    for (const [label, type] of [["重命名", "rename"], ["删除会话", "delete"]]) {
      const action = element("button", label, type === "delete" ? "danger-text" : "");
      action.type = "button";
      action.disabled = running;
      action.addEventListener("click", () => openConversationAction(row, type));
      actions.append(action);
    }
    menu.append(toggle, actions);
    rowElement.append(b, menu);
    $("conversations").append(rowElement);
    if (row.id === conversationId) {
      $("conversation-title").textContent = row.title;
      $("conversation-meta").textContent =
        `本会话已记录 ${row.run_count || 0} 次彩排；查看旧结果或沿用条件继续。`;
    }
  }
  return rows;
}
async function switchConversation(id) {
  if (running) {
    notice("当前彩排仍在进行，请完成后切换会话。");
    return;
  }
  conversationId = id;
  remember("trialtrust-current-conversation", id);
  clearInputs();
  clearRun();
  await refreshConversations();
  const rows = await history();
  if (conversationId !== id) return;
  if (rows.length) {
    restoreConditions(rows[0].conditions, rows[0].kind === "suite" ? "paired" : "single");
    await loadRun(rows[0].id);
    currentStep = latestRow?.status === "reviewed" ? 4 : 3;
  }
  updateCoach();
  setSidebar(false);
}
async function newConversation(notify = true) {
  if (running) {
    notice("当前彩排仍在进行，请完成后新建会话。");
    return;
  }
  const row = await api("/api/conversations", {});
  await switchConversation(row.id);
  if (notify) notice("新会话已创建。先选择事情；历史会话仍然保留。");
}
async function history() {
  const expected = conversationId;
  if (!expected) return [];
  const rows = await api(
    `/api/trials?conversation_id=${encodeURIComponent(expected)}`,
  );
  if (conversationId !== expected) return [];
  $("history-count").textContent = rows.length;
  $("round-total").textContent = rows.length;
  populateRoundChoices(rows);
  $("history").replaceChildren();
  if (!rows.length) {
    $("history").append(
      element("p", "还没有记录。从一组离线对照彩排开始吧。", "muted"),
    );
    return rows;
  }
  for (const row of rows) {
    const b = element("button", undefined, "history-item");
    b.classList.toggle("active", row.id === activeId);
    b.disabled = running;
    b.append(
      element(
        "b",
        row.title || `${domainLabel(row.conditions)} · ¥${row.conditions.budget_yuan}`,
      ),
      element(
        "small",
        `${row.conditions.agent === "live" ? "真实模型" : "离线示例"} · ${caseLabels[row.conditions.case]} · ${row.status === "reviewed" ? "已审阅" : row.status === "running" ? "进行中" : "查看记录"}`,
      ),
    );
    b.addEventListener("click", async () => {
      invalidateConfirmation();
      await loadRun(row.id);
      setSidebar(false);
      if (latestRow?.report) goStep(3);
    });
    const item=element("div",undefined,"history-row");
    const menu=element("details",undefined,"conversation-actions run-actions");
    const toggle=element("summary","⋯");
    toggle.setAttribute("aria-label",`彩排记录操作：${row.title || domainLabel(row.conditions)}`);
    toggle.setAttribute("title","重命名或删除彩排记录");
    toggle.addEventListener("click",event=>{if(running || row.status==="running"){event.preventDefault();return;}closeConversationMenus(menu);});
    const actions=element("div",undefined,"conversation-menu");
    for(const [label,type] of [["重命名","rename"],["删除记录","delete"]]) {
      const action=element("button",label,type==="delete"?"danger-text":"");action.type="button";
      action.disabled=running || row.status==="running";
      action.addEventListener("click",()=>openConversationAction(row,type,"run"));actions.append(action);
    }
    menu.append(toggle,actions);item.append(b,menu);$("history").append(item);
  }
  return rows;
}
function render(row, pairSelection = "baseline") {
  $("result-details").querySelectorAll(".comparison-method").forEach(node => node.remove());
  $("result-details").hidden = true;
  $("review-content").hidden = true;
  $("review-placeholder").hidden = false;
  $("review-placeholder").textContent = row.status === "running"
    ? "彩排进行中，完成后可在这里审阅并导出结果。"
    : "本次尚无可审阅的结果，请先在第三步查看执行状态。";
  $("workspace").classList.add("has-result");
  $("paired-comparison").hidden = true;
  $("paired-comparison").replaceChildren();
  $("empty-state").hidden = true;
  $("result-content").hidden = false;
  $("finding").replaceChildren();
  $("metrics").replaceChildren();
  $("trace").replaceChildren();
  $("trace-count").textContent = "";
  $("answer").textContent = "";
  $("progress").replaceChildren();
  $("review").hidden = true;
  $("reviewed").hidden = true;
  $("export").hidden = true;
  $("preview-export").hidden = true;
  $("export-preview").hidden = true;
  $("export-json").value = "";
  $("contract-report").hidden = true;
  $("run-skills").replaceChildren();
  $("result-checklist").replaceChildren();
  const suite = row.report?.kind === "suite" ? row.report : null;
  const report = suite ? suite[pairSelection] : row.report,
    mode =
      row.conditions.agent === "live" ? "真实模型试运行" : "免费演示 · 熟悉操作流程";
  $("run-info-title").textContent = row.conditions.agent === "live" ? "真实模型执行 · 查看本次设置" : "免费演示 · 查看本次设置";
  $("run-meta").textContent =
    `${row.title ? `记录：${row.title} · ` : ""}${mode} · ${domainLabel(row.conditions)} · ${caseLabels[report?.conditions?.case || row.conditions.case]} · 预算 ¥${row.conditions.budget_yuan}`;
  if (row.conditions.agent === "live" && report?.execution_metadata?.model) {
    const models=report.execution_metadata.models?.length ? report.execution_metadata.models : [report.execution_metadata.model];
    const names={"deepseek-v4.1-flash":"DeepSeek V4.1 Flash","qwen3.7-flash":"Qwen3.7-Flash"};
    $("run-meta").textContent += ` · 本次实际模型：${models.map(m=>names[m] || m).join("、")}`;
  }
  const savedScenario=scenarioFor(row.conditions);
  if(savedScenario) {
    const savedPricing=WorkbenchTools.pricing(savedScenario,row.conditions.fulfillment,row.conditions.pricing);
    const savedUnitPrice=(report?.conditions?.case || row.conditions.case) === "price_change" ? savedPricing.changed_unit_price : savedPricing.unit_price;
    $("run-meta").textContent += ` · ${row.conditions.quantity}${savedScenario.unit} · ${serviceLabel(row.conditions.fulfillment)} · 本次设定的模拟价目：¥${savedUnitPrice}/${savedScenario.unit}，每单另收¥${savedPricing.order_fee}`;
  }
  if (row.status === "running") {
    $("run-status").textContent = "进行中";
    const box = element("div", undefined, "finding");
    box.append(
      element("h2", "正在观察这次委托"),
      element("p", "每一步决策和工具结果会记录下来。不会操作真实商家。"),
    );
    $("finding").append(box);
    $("progress").append(element("div", row.stage, "progress-line"));
    return;
  }
  if (!report) {
    $("run-status").textContent = "未完成";
    const box = element("div", undefined, "finding");
    box.append(
      element("h2", "这次试运行已停止"),
      element("p", row.error || row.stage),
    );
    if (["failed", "interrupted"].includes(row.status)) {
      const retry = element("button", "从检查点继续 ↗", "primary");
      retry.addEventListener("click", async () => {
        try {
          retry.disabled = true;
          await api(`/api/trials/${row.id}/resume`, {});
          await loadRun(row.id);
        } catch (error) {
          notice(error.message);
          retry.disabled = false;
        }
      });
      box.append(retry);
    }
    $("finding").append(box);
    return;
  }
  $("result-details").hidden = false;
  $("review-content").hidden = false;
  $("review-placeholder").hidden = true;
  renderResultChecklist(row, pairSelection);
  const draftCount = report.drafts.length,
    outside = report.attempted_out_of_scope_actions;
  let title = "当前条件下，没有可接受的草稿",
    description =
      "先看下面的检查依据：可能是超预算，也可能是资料不够。停止生成草稿有时是正确选择。";
  if (report.termination !== "model_finished") {
    title =
      report.termination === "round_limit"
        ? "试运行到达轮数上限"
        : "模型输出不完整，已停止";
    description =
      "这次没有完整结束。已有草稿也需继续审阅，不能据此认定任务成功。";
  } else if (outside) {
    title = "它尝试了未授权动作，已被拦截";
    description =
      "模拟工具拒绝了这次动作，没有真实预约或付款；执行者的越权尝试仍会记下。";
  } else if (draftCount) {
    title = "生成了符合本次条件的草稿";
    description =
      "本次模拟服务的费用和依据已检查，方案在预算内。展开下方记录可查看计算和查证过程；不会产生实际订单。";
  } else if (!report.evidence_coverage?.current_price_observed) {
    title = "缺少当前价目，无法确认是否超预算";
    description = `没有查到当前价格依据，无法核实总费用或判断是否超出¥${row.conditions.budget_yuan}预算，因此没有通过核验的草稿。缺价目与涨价是两种不同的测试。`;
  } else if (WorkbenchTools.budgetAssessment(row,pairSelection,catalog)?.over > 0) {
    const b = WorkbenchTools.budgetAssessment(row,pairSelection,catalog);
    title = `费用超出预算¥${b.over}，没有通过核验的草稿`;
    description = `按本次保存的现行价目计算，总费用¥${b.total}，你给的总预算¥${b.budget}，预算还剩¥0。没有放行超预算的方案；具体计算见下方“费用与预算核对”。`;
  } else if (!report.evidence_coverage?.cancellation_terms_observed) {
    title = "缺少退改规则，没有通过核验的草稿";
    description = "当前价格已查到，但还没有查到取消或改期的规则，需要先补齐依据。";
  }
  $("run-status").textContent = row.status === "reviewed" ? "已审阅" : "待审阅";
  const box = element("div", undefined, "finding");
  box.append(element("h2", suite ? `${pairSelection === "baseline" ? "按原条件试" : "遇到变化再试"}：${title}` : title), element("p", description));
  $("finding").append(box);
  for (const [value, label] of [
    [draftCount, "已核验草稿"],
    [outside, "越权动作尝试"],
    [report.real_world_side_effects, "真实世界操作"],
  ]) {
    const metric = element("div", undefined, "metric");
    metric.append(element("b", String(value)), element("small", label));
    $("metrics").append(metric);
  }
  $("answer").replaceChildren();
  WorkbenchTools.verificationSegments(report.answer || "没有最终说明，请查看工具记录。").forEach((line,i)=>{
    if(i) $("answer").append("\n");
    $("answer").append(element("span",line.text,line.failedVerdict ? "failed-verdict" : undefined));
  });
  if (report.mandate) {
    const m = report.mandate,
      c = report.evidence_coverage;
    $("contract-report").hidden = false;
    $("contract-report").textContent =
      `本次确认条件：${domainLabel(m)} / ${m.quantity}${scenarioFor(m)?.unit || "项"} / ${serviceLabel(m.fulfillment)} / 总预算¥${m.budget_yuan}${m.custom_task?.context?.length ? `\n补充条件：${m.custom_task.context.join("；")}` : ""}\n查到当前价格：${c.current_price_observed ? "是" : "否"}；查到退改规则：${c.cancellation_terms_observed ? "是" : "否"}\n本次故意模拟查询故障：${report.injected_tool_faults || 0}次（用于观察能否恢复，不算AI自身出错）\n${report.delegation_note}\n条件版本：${m.digest.slice(0, 12)}`;
  }
  $("trace-count").textContent = `${report.trace.length} 步`;
  report.trace.forEach((entry, i) => {
    const fault = entry.result.fault_origin === "test_harness",
      bad =
        entry.result.allowed === false ||
        entry.result.valid === false ||
        entry.result.error;
    const detail = element(
      "details",
      undefined,
      `trace-step${bad ? " bad" : ""}`,
    );
    const summary = element(
      "summary",
      `${String(i + 1).padStart(2, "0")}  ${toolLabels[entry.tool] || entry.tool}`,
    );
    summary.append(
      element(
        "small",
        fault ? "测试工具故障" : bad ? "拦截 / 未通过" : "查看依据",
      ),
    );
    detail.append(
      summary,
      element(
        "pre",
        JSON.stringify({ 请求: entry.arguments, 结果: entry.result }, null, 2),
      ),
    );
    $("trace").append(detail);
  });
  renderSkills([
    ...(report.skill_events || []),
    ...(suite?.skill_events || []),
  ]);
  if (row.status === "waiting_review") $("review").hidden = false;
  if (row.status === "reviewed") {
    $("reviewed").hidden = false;
    $("reviewed").textContent = row.reviewed
      ? "你已保留这份试托结果。未产生预约、付款或新的模型调用。"
      : "你暂不接受这份结果。可以调整条件，开启新一次试托。";
  }
  $("export").hidden = false;
  $("preview-export").hidden = false;
  $("export").href = `/api/trials/${row.id}/export`;
  if (suite) {
    const area = $("paired-comparison");
    area.hidden = false;
    const summary=WorkbenchTools.comparisonSummary(row,catalog);
    const intro=element("p",undefined,"comparison-intro");
    const selection=row.conditions.comparison_case === "auto" && suite.execution_mode === "live_llm"
      ? `这次AI自动选中了“${caseLabels[suite.design.case]}”。` : `本组实际测试的变化：${caseLabels[suite.design.case]}。`;
    intro.append(`${selection}${summary.explanation} `,
      element("strong",summary.conclusion,"comparison-outcome"));
    area.append(
      element("h3", "先对比两次结果"),
      intro,
    );
    const cards = element("div", undefined, "pair-grid");
    for (const [key, label] of [
      ["baseline", "按原条件试"],
      ["changed", "遇到变化再试"],
    ]) {
      const r = suite[key],
        button = element(
          "button",
          undefined,
          `pair-card${pairSelection === key ? " selected" : ""}`,
        );
      button.type = "button";
      button.setAttribute("aria-pressed", String(pairSelection === key));
      button.setAttribute("aria-controls", "finding result-details");
      button.append(
        element("b", key === "changed" ? `${label} · ${caseLabels[suite.design.case]}` : label),
        element(
          "strong",
          r.drafts.length
            ? `¥${r.drafts[0].total_yuan} · ${r.drafts.length}份草稿`
            : "没有通过核验的草稿",
        ),
        element(
          "small",
          pairSelection === key ? "正在查看这次 ↓" : "点击查看这次 ↓",
        ),
      );
      button.addEventListener("click", () => render(row, key));
      cards.append(button);
    }
    area.append(cards);
    const audit = suite.audit;
    const auditDetail = element("details", undefined, "trace-step comparison-method");
    auditDetail.append(element("summary", "这组对比怎么设计、怎么核对？"));
    auditDetail.append(
      element("p", suite.design.rationale),
      element("p", "两次沿用同一份已确认条件，只改变一个测试项。这一次的结果不能用来给模型排名。"),
      element("p", `${suite.execution_mode === "offline_script" ? "预设审阅示例" : "审阅智能体"}对照执行记录，核实了${audit.verified_facts.length}条事实，排除了${audit.rejected_facts.length}条无记录支持的说法。`),
    );
    const facts = element("div", undefined, "audit-facts");
    const metricNames = {
      accepted_drafts: "通过条件的草稿数",
      out_of_scope_attempts: "越权动作尝试数",
      tool_faults: "注入工具故障数",
      termination: "结束原因",
      current_price_observed: "已查到现行价目",
      cancellation_observed: "已查到退改条款",
    };
    for (const fact of audit.verified_facts) {
      const value =
        typeof fact.value === "boolean"
          ? fact.value
            ? "是"
            : "否"
          : ({
              model_finished: "正常结束",
              round_limit: "轮数上限",
              output_limit: "输出截断",
            }[fact.value] ?? String(fact.value));
      facts.append(
        element(
          "p",
          `${fact.run === "baseline" ? "原始" : "变化"}条件 · ${metricNames[fact.metric]}：${value}`,
        ),
      );
    }
    auditDetail.append(facts);
    $("result-details").append(auditDetail);
    $("run-meta").textContent +=
      ` · 两次对比 / 正在查看：${pairSelection === "baseline" ? "按原条件试" : "遇到变化再试"}`;
  }
  frameDisclosures($("step-three"));
}
async function loadRun(id) {
  activeId = id;
  clearTimeout(pollTimer);
  try {
    const row = await api(`/api/trials/${id}`);
    if (activeId !== id || row.conversation_id !== conversationId) return;
    const wasRunning = running;
    latestRow = row;
    render(row);
    setBusy(row.status === "running");
    await history();
    await refreshConversations();
    if (row.status === "running")
      pollTimer = setTimeout(() => loadRun(id), 1200);
    else if (wasRunning && row.report) {
      currentStep = 3;
      updateCoach();
      notice("彩排完成。请切换两张对照卡，查看变化和工具证据。");
      scrollToSection("step-three");
    }
  } catch (error) {
    notice(error.message);
    setBusy(false);
  }
}
async function start(isSuite = false) {
  if (running) return;
  if (analyzing) {
    notice("需求分析仍在进行，请等待结果返回后再开始彩排。");
    return;
  }
  notice();
  if (!$("domain").value) {
    notice("请先选择具体需求，或应用一套条件模板。", $("manual-demand-fields").hidden ? "template-select" : "domain");
    return;
  }
  if (!serviceIsConfirmed()) {
    invalidateConfirmation();
    notice("请先手动填写服务方式，并点击右侧“确认”。", "fulfillment-text");
    return;
  }
  const budget = Number($("budget").value),
    quantity = Number($("quantity").value);
  if (
    $("budget").value.trim() === "" ||
    !Number.isInteger(budget) ||
    budget < 0 ||
    budget > WorkbenchTools.maxBudget
  ) {
    notice("请填写0—1,000,000元之间的整数预算。", "budget");
    return;
  }
  if (!Number.isSafeInteger(quantity) || quantity < 1) {
    notice("数量请填写大于0的整数；过长的数字请检查是否误填。", "quantity");
    return;
  }
  if (!WorkbenchTools.pricing(currentScenario(),$("fulfillment").value,editorPricing())) {
    document.querySelector(".fee-help").open = true;
    notice("单价和每单费用请填写非负整数。", "unit-price");return;
  }
  if (!$("confirmed").checked || confirmedFor !== signature()) {
    invalidateConfirmation();
    notice("请核对当前场景、数量、方式和预算，重新勾选确认。", "confirmed");
    return;
  }
  if ($("agent").value === "live" && !liveEnabled) {
    notice("真实模型调用尚未启用。", "agent");
    return;
  }
  const payload = {
    domain: $("domain").value,
    ...($("domain").value === "custom" ? {custom_task:currentCustomTask} : {}),
    quantity,
    fulfillment: $("fulfillment").value,
    budget_yuan: budget,
    pricing: editorPricing(),
    case: isSuite ? "baseline" : $("cases").value,
    comparison_case: $("comparison-case").value,
    agent: $("agent").value,
    dense: $("dense").checked,
    confirmed: $("confirmed").checked,
  };
  invalidateConfirmation();
  setBusy(true);
  try {
    const created = await api(isSuite ? "/api/suites" : "/api/trials", payload);
    currentStep = 3;
    updateCoach();
    await loadRun(created.id);
  } catch (error) {
    notice(error.message);
    setBusy(false);
  }
}
async function review(accepted) {
  if (!activeId || running) return;
  try {
    await api(`/api/trials/${activeId}/review`, { accepted });
    await loadRun(activeId);
    currentStep = 4;
    updateCoach();
    notice("已保存你的审阅决定。可以下载完整记录；未产生任何真实预约或付款。");
  } catch (error) {
    notice(error.message);
  }
}
$("confirmed").addEventListener("change", () => {
  if ($("confirmed").checked && !serviceIsConfirmed()) {
    invalidateConfirmation(); notice("请先填写并确认服务方式。", "fulfillment-text"); return;
  }
  confirmedFor = $("confirmed").checked ? signature() : null;
  if ($("confirmed").checked) notice();
  $("confirmed").removeAttribute("aria-invalid");
  $("confirmation-status").textContent = $("confirmed").checked
    ? "✓ 已确认当前条件 · 取消勾选后不可运行"
    : "尚未确认 · 修改条件后需重新勾选";
  $("confirmation-status").classList.toggle("ok", $("confirmed").checked);
});
$("domain").addEventListener("change", () => {
  closeDemandMenu();
  activeDemandSource="directory";currentCustomTask=null;
  directorySelection=$("domain").value ? {spec:{domain:$("domain").value},method:$("run-method").value} : null;
  currentStep = $("domain").value ? 2 : 1;
  domainFields(true);
  rememberDirectorySelection();
  invalidateConfirmation();
});
$("domain-picker").addEventListener("click", () => {
  if (running) return;
  if (!$("domain-picker-menu").hidden) { closeDemandMenu(); return; }
  renderDemandGroups(directorySelection?.spec.domain || "");
  $("domain-picker-menu").hidden = false;
  $("domain-picker").setAttribute("aria-expanded", "true");
  positionDemandMenu();
  const nav = $("domain-groups"), selected = nav.querySelector('[aria-pressed="true"]');
  if (selected) nav.scrollTop += selected.getBoundingClientRect().top - nav.getBoundingClientRect().top - Math.max(0, (nav.clientHeight - selected.offsetHeight) / 2);
});
$("close-domain-menu").addEventListener("click", () => closeDemandMenu(true));
$("domain-picker").addEventListener("keydown", event => {
  if (event.key === "Escape") closeDemandMenu(true);
  if (event.key === "ArrowDown" && !running) {
    event.preventDefault();
    if ($("domain-picker-menu").hidden) $("domain-picker").click();
    $("domain-groups").querySelector('[aria-pressed="true"]')?.focus({preventScroll:true});
  }
});
$("domain-picker-menu").addEventListener("keydown", event => {
  if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeDemandMenu(true); }
});
$("domain-options").addEventListener("keydown", event => {
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    $("domain-groups").querySelector('[aria-pressed="true"]')?.focus({preventScroll:true});
  }
});
$("domain-picker").closest(".demand-picker").addEventListener("focusout", event => {
  if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) closeDemandMenu();
});
window.addEventListener("resize", () => { if (!$("domain-picker-menu").hidden) positionDemandMenu(); });
window.addEventListener("scroll", () => { if (!$("domain-picker-menu").hidden) positionDemandMenu(); }, {passive:true});
document.addEventListener("click", event => {
  if (!event.target.closest(".demand-picker")) closeDemandMenu();
});
$("fulfillment-text").addEventListener("input", () => {
  invalidateServiceMethod();
  if ($("domain").value) currentStep = 2;
  invalidateConfirmation();
});
$("fulfillment-text").addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.isComposing) {event.preventDefault();confirmServiceMethod();}
});
$("confirm-fulfillment").addEventListener("click", confirmServiceMethod);
$("clear-fulfillment").addEventListener("click", () => {
  if (running) return;
  setServiceDraft(); invalidateConfirmation();
  $("fulfillment-text").focus({preventScroll:true});
});
["quantity", "budget", "unit-price", "changed-price", "order-fee"].forEach((id) =>
  $(id).addEventListener("input", () => {
    currentStep = 2;
    feeNote();
    invalidateConfirmation();
  }),
);
$("agent").addEventListener("change", () => {
  modeNote();
  invalidateConfirmation();
});
$("dense").addEventListener("change", invalidateConfirmation);
$("cases").addEventListener("change", () => chooseCase($("cases").value));
$("run").addEventListener("click", () => start(false));
$("run-suite").addEventListener("click", () => start(true));
$("accept").addEventListener("click", () => review(true));
$("reject").addEventListener("click", () => review(false));
$("prepare-stand-in").addEventListener("click", prepareStandIn);
$("private-task").addEventListener("input", () => {
  analysisNonce++;
  currentStep = 1;
  if(activeDemandSource === "custom") invalidateConfirmation();
  else updateCoach();
  clearRequestAnalysis();
  if(!$("request-check-status").classList.contains("is-missing"))
    requestStatus("内容已修改，请再次点击右侧按钮检查。");
});
$("try-budget").addEventListener("click", () => {
  $("budget").value = 250;
  invalidateConfirmation();
  goStep(2);
  notice("预算已改为250元。请核对并重新勾选确认，不会自动运行。");
});
for (const [id, value] of [
  ["try-price", "price_change"],
  ["try-missing", "missing_evidence"],
])
  $(id).addEventListener("click", () => {
    chooseCase(value);
    setRunMethod("single");
    goStep(2);
    notice("已选择测试条件。请重新确认，再点击单次试运行。");
  });
function sidebarShell() { return $("conversation-sidebar").closest(".trialtrust-responsive"); }
function activeControl() { return $("conversation-sidebar").getRootNode().activeElement || document.activeElement; }
function sidebarIsNarrow() {
  return sidebarShell().getBoundingClientRect().width <= 1050;
}
function setSidebar(open) {
  sidebarShell().classList.toggle("sidebar-open", open);
  $("sidebar-backdrop").hidden = !open;
  $("toggle-sidebar").setAttribute("aria-expanded", String(open));
  const mobile = sidebarIsNarrow();
  $("conversation-sidebar").inert = mobile && !open;
  $("workspace").closest(".app-content").inert = mobile && open;
  if (mobile) $("conversation-sidebar").setAttribute("role", "dialog");
  else $("conversation-sidebar").removeAttribute("role");
  if (mobile && open) $("conversation-sidebar").setAttribute("aria-modal", "true");
  else $("conversation-sidebar").removeAttribute("aria-modal");
  if (mobile && open) $("close-sidebar").focus();
  else if (mobile && $("conversation-sidebar").contains(activeControl())) $("toggle-sidebar").focus();
}
$("toggle-sidebar").addEventListener("click", () => setSidebar(true));
$("close-sidebar").addEventListener("click", () => setSidebar(false));
$("sidebar-backdrop").addEventListener("click", () => setSidebar(false));
document.addEventListener("keydown", (event) => {
  if (!sidebarShell().classList.contains("sidebar-open")) return;
  if (event.key === "Escape") { event.preventDefault(); setSidebar(false); }
  if (event.key === "Tab" && sidebarIsNarrow()) {
    const focusable = [...$("conversation-sidebar").querySelectorAll("button:not(:disabled), summary")].filter(el => el.checkVisibility());
    const first = focusable[0], last = focusable.at(-1);
    if (event.shiftKey && activeControl() === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && activeControl() === last) { event.preventDefault(); first?.focus(); }
  }
});
let sidebarWasNarrow = sidebarIsNarrow();
new ResizeObserver(() => {
  const narrow = sidebarIsNarrow();
  if (narrow !== sidebarWasNarrow) { sidebarWasNarrow = narrow; setSidebar(false); }
}).observe(sidebarShell());
setSidebar(false);
$("new-conversation").addEventListener("click", () =>
  newConversation().catch((e) => notice(e.message)),
);
$("new-trial").addEventListener("click", () => {
  if (running) {
    notice("当前彩排仍在进行，请完成后再试。");
    return;
  }
  clearRun();
  history().catch((e) => notice(e.message));
  scrollToSection($("domain").value ? "step-two" : "step-one");
});
$("continue-trial").addEventListener("click", () => {
  if (running || !latestRow) return;
  clearInputs();
  restoreConditions(latestRow.conditions, latestRow.kind === "suite" ? "paired" : "single");
  goStep(2);
  notice("已把这次的需求、数量、服务方式、预算和模拟价格填回第二步。请先确认服务方式，再核对并勾选全部条件，之后再运行。");
});
$("preview-export").addEventListener("click", async () => {
  const expectedId = activeId;
  try {
    const record = await api(`/api/trials/${expectedId}/export`);
    if (activeId !== expectedId) return;
    $("export-json").value = JSON.stringify(record, null, 2);
    $("export-preview").hidden = false;
    $("export-json").focus();
    notice("完整记录已展开，可全选复制保存。", "export-json");
  } catch (error) {
    notice(error.message);
  }
});
$("export").addEventListener("click", async (event) => {
  event.preventDefault();
  try {
    downloadJSON(
      await api(`/api/trials/${activeId}/export`),
      `trialtrust-${activeId}.json`,
    );
  } catch (error) {
    notice(error.message);
  }
});
$("confirm-directory-demand").addEventListener("click", confirmDirectoryDemand);
document
  .querySelectorAll("[data-step]")
  .forEach((b) =>
    b.addEventListener("click", () => goStep(Number(b.dataset.step))),
  );
$("coach-next").addEventListener("click", () =>
  goStep(currentStep === 3 ? 4 : currentStep),
);
// The help map only explains the workflow; it never edits or runs a task.
const helpModules = [
      {n:'01',name:'选择需求',title:'这次，想先试哪类事情？',purpose:'先选清楚要让AI试办的事，让后面的查资料、算费用都有明确目标。',problem:'只说“帮我安排一下”，AI可能理解错。先选具体需求，例如“自助餐聚会”，再填写人数和预算；自己写的要求也要检查是否已被采用。',output:'确定这次要试办的事情，接着到第二步填写条件。',steps:[
        {name:'选择需求来源',why:'确定是重新填写需求，还是沿用之前保存的设置。',how:'在“01 选择需求”中，点“自己选择需求”；已有模板时，也可以点“使用条件模板”，选模板后点“应用模板”。两种方式选一种即可。'},
        {name:'选定具体事情',why:'告诉AI本次要处理哪一种服务，让它知道该查什么、怎么算钱。',how:'先点大类，例如“美食聚会”，再打开“具体想做什么”。鼠标移到左侧的“自助聚餐”，或点击这个子分类，右侧就会显示具体事项；点“自助餐聚会”完成选择。核对“当前需求”，再点它下方的“确定！并进行下一步核对条件”。这个按钮只使用目录选择或已应用的模板，不分析下方手写内容。'},
        {name:'分析自己写的需求（可选）',why:'理解你实际想做的事，保留已填条件，只问还缺什么。',how:'展开“写下自己的需求”，可编辑框内格式，也可直接用自己的话描述。点击“你的需求”右侧的“确定！并进行下一步核对条件”，只分析这份手写内容：先隐去手机号等信息，再用大模型检查（消耗模型额度）。缺项在框下用红字提示，原文不变；补充时红字保留，再次点击后更新。每次分析结束后，“我理解的需求”会直接显示识别结果，条件齐全就自动带入第二步。即使上方也选了目录或模板，这个按钮也只使用手写需求。目录外的事项需在第二步填写模拟价格。'}
      ]},
      {n:'02',name:'核对条件并试运行',title:'核对条件，再开始彩排',purpose:'告诉AI有多少人、最多花多少钱、允许做什么，再选怎么试并开始运行。',problem:'需求选好了，AI仍可能漏掉预算或服务方式。先确认这些条件，再观察价格变化、资料缺失等情况出现时，它会不会超支或做你没允许的事。',output:'得到一份试运行结果，或“按原条件／遇到变化”的两份结果，供第三步检查。',steps:[
        {name:'填好条件与模拟价格',why:'让AI知道有多少人、怎样服务、最多花多少钱；提供本次可查证的价目。',how:'填写数量，手动输入服务方式（灰字只是例子，不是已填内容），再点输入框右侧的“确认”。服务方式可以自己描述，例如“餐馆里擦桌子”或“吃个蛋挞”，不必照着灰字填；改过文字要重新确认。“清空”只清掉这项文字。再填总预算，看费用预览；需要改变价格时，展开“查看费用明细 / 调整这次的模拟价格”。数量×单价加上每单费用，就是总费用。模板或记录带入的服务方式也要重新点确认。'},
        {name:'选择执行方式',why:'决定先熟悉操作，还是观察真实AI自己如何查资料、检查方案。',how:'第一次选“免费演示 · 按条件核对”，不消耗模型额度。想观察AI真实决策时再选“真实模型”。可选的混合检索会同时查关键词与意思相近的资料，额外消耗模型额度。'},
        {name:'选择试运行的情况',why:'明确这次要检查涨价、缺价目还是其他问题，避免把不同测试混为一谈。',how:'推荐选对比两次，在“第二次要测试哪种变化”中选择。默认“单价变化”使用你填写的变化后单价；选“缺少当前价目”只撤去价格资料，不使用变化后单价。只有选“自动选择”时，AI才自行选择一种变化。第三步会写明实际测试项。也可选单次运行，再选具体情况。'},
        {name:'确认并开始',why:'确保运行的是你核对过的设置，避免填错条件就开始。',how:'核对以上设置，勾选确认，再点“开始一组对照彩排”或单次运行按钮。常用时可先保存模板：保存需求、数量、方式、预算、模拟价格、执行方式和检查设置；下次从第一步的“使用条件模板”选用。'}
      ]},
      {n:'03',name:'看结果与检查依据',title:'它做了什么，依据在哪？',purpose:'检查费用算得对不对、资料有没有依据、动作有没有超出你的允许范围。',problem:'AI回答得流畅，不代表它查过资料或算对了钱。把结果和费用依据、查询记录放在一起看，找出漏项、超支或不该做的动作。',output:'知道本次哪里符合要求、哪里有问题、哪些信息还需要补充。',steps:[
        {name:'先看结论与两次差异',why:'先弄清是否形成可检查的方案，以及变化前后结果为什么不同。',how:'对照运行完成后，分别点“按原条件试”和“遇到变化再试”两张卡。看总费用、是否有方案草稿，以及停止原因。没有草稿可能是在超预算或缺资料时正确停止，并不一定是报错。'},
        {name:'核对费用与资料',why:'避免只看AI说得好不好听，要确认费用、当前价目和退改规则是否有依据。',how:'查看“检查依据”里的费用、价格、退改规则和未授权操作检查。想看本次实际使用的设置，展开“AI的说明与本次实际使用的条件”。这里的方案草稿还没有实际执行。'},
        {name:'回看具体过程',why:'查清它究竟查询了什么、依据是什么，以及有没有尝试不该做的动作。',how:'展开“查看它一步步查了什么、做了什么”，逐项看查询、费用检查与生成草稿的记录。有需要再看本次使用的技能，或选本会话两份记录生成对照表。'}
      ]},
      {n:'04',name:'审阅与保存记录',title:'这份结果，你愿意保留吗？',purpose:'由你判断这次结果是否符合要求，记下判断，保存过程，必要时改条件再试。',problem:'看过一次容易忘记当时用了什么条件、哪里出了问题。保存结果和你的判断，之后就能回看或比较；这里的“保留”不会替你预约或付款。',output:'留下你的判断和完整过程，方便之后回看、对照或继续试运行。',steps:[
        {name:'给本次结果一个判断',why:'把最后的判断留给你，AI生成方案不等于你已经认可。',how:'看完第三步后，符合要求就点“保留结果”，还需要改进就点“暂不接受”。两种选择都会保留试运行与审阅记录，不会同意真实预约或付款。'},
        {name:'回看或导出记录',why:'以后能找到当时的条件、过程与判断，不必凭印象比较。',how:'同一账号登录后，从左侧“历史会话”找回记录。需要保存文件时点“下载完整记录 JSON”；下载不成功可查看并复制完整JSON。不需要文件也能正常使用。'},
        {name:'调整后再试（可选）',why:'验证改过预算、价格或检查情况后，AI的表现是否有所变化。',how:'点“用这份条件再试一次”，回到第二步修改设置，重新勾选确认，再开始。新的试运行会形成另一条记录，之后可以与旧记录对照。'}
      ]}
    ];
let helpSelected = 0;
function renderHelpSteps(index) {
  helpSelected = index;
  $("help-module-cards").querySelectorAll("button").forEach((button,i) => {
    button.classList.toggle("is-current", i === index);
    button.setAttribute("aria-pressed", String(i === index));
  });
  const module = helpModules[index];
  $("help-map-location").textContent = `正在查看：${module.n} ${module.name}`;
  $("help-substeps-title").textContent = `${module.n} ${module.name} · 小步骤`;
  $("help-module-problem").textContent = `这一步帮你解决：${module.problem}`;
  const list = $("help-substeps-list"); list.replaceChildren();
  module.steps.forEach((step,i) => {
    const section=element("section",undefined,"help-substep");
    const details=element("details"); details.open=false;
    const how=element("div",step.how,"help-how");
    details.append(element("summary","查看具体操作"),how);
    section.append(element("h4",`${["①","②","③","④"][i]} ${step.name}`),element("p",`目的：${step.why}`,"help-step-purpose"),details);
    list.append(section);
  });
  frameDisclosures(list);
  $("help-substeps-output").textContent = `完成后：${module.output}`;
}
function renderHelpMap() {
  const cards=$("help-module-cards"); cards.replaceChildren();
  helpModules.forEach((module,i) => {
    const card=element("button",undefined,"help-module");card.type="button";
    card.setAttribute("aria-label",`${module.n} ${module.name}`);
    card.setAttribute("aria-controls","help-step-map");
    const heading=element("span",undefined,"help-module-heading");
    heading.append(element("small",`${module.n} · ${module.name}`),element("strong",module.title));
    card.append(heading,element("span",`作用与目的：${module.purpose}`,"help-module-purpose"),element("span",`完成后：${module.output}`,"help-output"));
    card.addEventListener("click",()=>renderHelpSteps(i));
    card.addEventListener("keydown",event=>{
      if($("help-dialog").classList.contains("module-only") || !["ArrowDown","ArrowUp","Home","End"].includes(event.key))return;
      event.preventDefault();
      const next=event.key==="Home" ? 0 : event.key==="End" ? 3 : (i+(event.key==="ArrowDown" ? 1 : 3))%4;
      renderHelpSteps(next);cards.querySelectorAll("button")[next].focus({preventScroll:true});
    });
    cards.append(card);
  });
  renderHelpSteps(helpSelected);
}
function openHelp(moduleIndex=null) {
  const onlyModule=moduleIndex!==null;
  helpSelected=onlyModule ? moduleIndex : Math.max(0,Math.min(3,currentStep-1));
  $("help-dialog").classList.toggle("module-only",onlyModule);
  $("help-title").textContent=onlyModule ? `${helpModules[helpSelected].n}模块·流程介绍` : "全流程简介";
  $("start-tutorial").textContent=onlyModule ? "返回当前模块 →" : "返回工作台 →";
  renderHelpMap();$("help-dialog").showModal();$("help-dialog").scrollTop=0;
}
$("help").addEventListener("click",()=>openHelp());
document.querySelectorAll("[data-module-help]").forEach(button=>button.addEventListener("click",()=>openHelp(Number(button.dataset.moduleHelp))));
$("close-help").addEventListener("click", () => $("help-dialog").close());
$("start-tutorial").addEventListener("click", () => {
  $("help-dialog").close();
  scrollToSection($("help-dialog").classList.contains("module-only") ? ["step-one","step-two","step-three","step-four"][helpSelected] : "coach");
});
$("dismiss-notice").addEventListener("click", () => notice());
frameDisclosures();
(async () => {
  try {
    await TrialTrustAuth.ready();
    $("full-screen").hidden = !window.location.hostname.endsWith(".ms.show");
    const config = await api("/api/session", {});
    if (config.session_token) {
      sessionToken = config.session_token;
      remember("trialtrust-session", sessionToken);
    }
    liveEnabled = config.live_enabled;
    if (typeof config.studio_url === "string" && config.studio_url.startsWith("https://www.modelscope.cn/studios/L666H666Better/")) {
      const target = new URL(config.studio_url);
      target.searchParams.set("mode", "full"); target.searchParams.set("app_path", "/api/workbench");
      $("full-screen").href = target.href;
    }
    catalog = await api("/api/catalog");
    $("scenario-total").textContent = catalog.scenarios.length;
    $("catalog-summary").textContent = `${catalog.categories.length}大类、${catalog.groups.length}个子分类、${catalog.scenarios.length}个具体事项`;
    domainLabels = Object.fromEntries(
      catalog.scenarios.map((s) => [s.id, s.label]),
    );
    fulfillmentLabels = catalog.fulfillments;
    const sk = await api("/api/skills");
    skillMetadata = sk.skills;
    renderSkillCatalog();
    renderTemplates();
    setRunMethod("paired");
    selectCategory(catalog.categories[0].id);
    const option = $("agent").querySelector('[value="live"]');
    option.disabled = !liveEnabled;
    option.textContent = liveEnabled
      ? "真实模型 · DeepSeek（免费额度用完自动切换Qwen）"
      : "真实模型 · 尚未启用";
    $("prepare-stand-in").disabled = !liveEnabled;
    if(!liveEnabled) requestStatus("大模型暂未启用，无法检查自定义需求；可先从上方目录选择。",false,true);
    modeNote();
    const conversations = await refreshConversations();
    const saved = readLocal("trialtrust-current-conversation");
    if (conversations.length)
      await switchConversation(
        conversations.some((c) => c.id === saved) ? saved : conversations[0].id,
      );
    else await newConversation(false);
  } catch (error) {
    notice(error.message);
  }
})();
