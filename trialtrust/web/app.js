const $ = (id) => document.getElementById(id);
PortalViewport.attach(
  window,
  $("notice").closest(".trialtrust-root") || document.documentElement,
);
const caseLabels = {
  baseline: "原始条件",
  price_change: "单价临时上涨",
  missing_evidence: "现行价目缺失",
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
  latestRow = null,
  analysisResult = null;
let sessionToken = readLocal("trialtrust-session");
let conversationId = null;
function readLocal(key) {
  try {
    const value = localStorage.getItem(key);
    if (value) return value;
  } catch {}
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}
function remember(key, value) {
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
async function api(path, body) {
  const opts = { headers: { "X-TrialTrust-Client": "web" } };
  if (sessionToken) opts.headers["X-TrialTrust-Session"] = sessionToken;
  if (conversationId)
    opts.headers["X-TrialTrust-Conversation"] = conversationId;
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const response = await fetch(path, opts);
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error("服务暂未返回结果，请稍后重试。");
  }
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
      "budget",
      "agent",
      "dense",
      "cases",
    ].map((id) => ($(id).type === "checkbox" ? $(id).checked : $(id).value)),
  );
}
function invalidateConfirmation() {
  confirmedFor = null;
  $("confirmed").checked = false;
  $("confirmed").removeAttribute("aria-invalid");
  $("confirmation-status").textContent = "尚未确认 · 修改条件后需重新勾选";
  $("confirmation-status").classList.remove("ok");
  updateCoach();
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
    ? "真实模型自主选择工具，会消耗百炼额度。运行仅发送已核对的结构化条件和合成资料，不发送任务原文。"
    : "离线示例按预设行为执行，用于理解和验证流程，不代表真实模型能力，不消耗额度。";
}
function setBusy(value) {
  running = value;
  [
    "run",
    "run-suite",
    "budget",
    "agent",
    "domain",
    "quantity",
    "fulfillment",
    "confirmed",
    "prepare-stand-in",
    "compile",
    "private-task",
    "stand-in",
    "cases",
    "text-reviewed",
    "analyze-live",
    "new-conversation",
    "new-trial",
    "continue-trial",
  ].forEach((id) => ($(id).disabled = value));
  document
    .querySelectorAll(
      ".category,.retry-actions button,.history-item,.conversation-item,.analysis-result button",
    )
    .forEach((b) => (b.disabled = value));
  $("dense").disabled = value || $("agent").value !== "live";
  $("analyze-live").disabled = value || !liveEnabled;
  $("run-suite").textContent = value
    ? "正在彩排，请稍候…"
    : "开始一组对照彩排 ↗";
  $("run").textContent = value ? "正在试运行…" : "运行这次试托 ↗";
  updateCoach();
}
function selectCategory(id, selected = "") {
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
  $("domain").value = selected;
  domainFields(true);
  invalidateConfirmation();
}
function domainFields(reset = false) {
  const s = catalog.scenarios.find((s) => s.id === $("domain").value),
    old = $("fulfillment").value;
  $("fulfillment").replaceChildren();
  if (!s) {
    const opt = element("option", "请先选择具体需求");
    opt.value = "";
    $("fulfillment").append(opt);
    $("scenario-description").textContent =
      "选择后会显示这个示例能核验的条件。";
    $("quantity-label").textContent = "数量";
    $("fee-note").textContent = "示例费用会显示在这里。";
    return;
  }
  for (const value of s.fulfillments) {
    const opt = element("option", fulfillmentLabels[value]);
    opt.value = value;
    $("fulfillment").append(opt);
  }
  if (!reset && s.fulfillments.includes(old)) $("fulfillment").value = old;
  if (reset) $("quantity").value = 2;
  $("quantity-label").textContent = `数量（${s.unit}，1—8）`;
  $("scenario-description").textContent =
    s.description + "。地点、日期和特殊需求未纳入当前条件。";
  feeNote();
  updateCoach();
}
function feeNote() {
  const s = catalog.scenarios.find((s) => s.id === $("domain").value);
  if (!s) return;
  const fee =
    s.id === "pottery"
      ? $("fulfillment").value === "shipping"
        ? 20
        : 0
      : s.fee;
  $("fee-note").textContent =
    `合成示例：¥${s.price}/${s.unit}，每单附加费¥${fee}。价格变化测试改为¥${s.changed_price}/${s.unit}；非真实报价。`;
}
function showGuide(value = true) {
  $("coach").hidden = !value;
  $("show-guide").setAttribute("aria-expanded", String(value));
  updateCoach();
}
function updateCoach() {
  const texts = {
    1: [
      "先选一件想交给 AI 的小事",
      "选择类别，再选具体需求。没有合适选项，可以先分析自己的需求。",
      "去选事情 ↓",
    ],
    2: [
      "划清边界，再交给 AI 试一次",
      "核对数量、方式和预算，勾选确认。建议先用离线示例，再点击开始对照彩排。",
      "查看待核对条件 ↓",
    ],
    3: [
      "看看变化之后，AI 有没有守住边界",
      "切换原始 / 变化条件，展开费用、工具证据和实际技能调用。看完再由你审阅。",
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
    notice("请先选择类别和具体需求。", "domain");
    scrollToSection("step-one");
    return;
  }
  if (
    step >= 3 &&
    (!latestRow || latestRow.status === "running" || !latestRow.report)
  ) {
    notice("先完成一次试运行，结果会显示在右侧。");
    return;
  }
  currentStep = step;
  updateCoach();
  if (scroll)
    scrollToSection(
      ["", "step-one", "step-two", "step-three", "step-four"][step],
    );
}
function prepareStandIn() {
  let value = $("private-task").value;
  if (!value.trim()) {
    notice("请先写下需求，不要填写真实个人资料。", "private-task");
    return;
  }
  const counts = { phone: 0, id: 0, email: 0 };
  const rules = [
    ["id", /(?<!\d)\d{17}[0-9Xx](?!\d)/g, "[证件替身]"],
    ["phone", /(?<!\d)1[3-9]\d{9}(?!\d)/g, "[手机号替身]"],
    ["email", /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, "[邮箱替身]"],
  ];
  for (const [kind, pattern, replacement] of rules)
    value = value.replace(pattern, () => {
      counts[kind]++;
      return replacement;
    });
  $("stand-in").value = value;
  $("stand-in-stage").hidden = false;
  $("text-reviewed").checked = false;
  $("compile-result").replaceChildren();
  analysisResult = null;
  $("redaction-note").textContent =
    `已在本机替换手机号${counts.phone}处、证件${counts.id}处、邮箱${counts.email}处。姓名、地址和间接身份描述仍需手动删除；这不是完全匿名化。`;
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
async function compileStandIn() {
  if (running) return;
  if (!$("text-reviewed").checked) {
    notice("请先检查替身文本，并勾选同意发送进行分析。", "text-reviewed");
    return;
  }
  notice();
  $("compile").disabled = true;
  try {
    const result = await api("/api/analyze", {
      text: $("stand-in").value,
      reviewed: $("text-reviewed").checked,
      use_model: $("analyze-live").checked,
    });
    analysisResult = result;
    const box = $("compile-result");
    box.replaceChildren(
      element("b", result.summary),
      element(
        "p",
        result.mode === "live_llm"
          ? "本次使用真实模型梳理需求。"
          : "本次使用确定性规则分析，不消耗模型额度。",
      ),
    );
    if (result.proposal) {
      const p = result.proposal;
      box.append(
        element(
          "p",
          `提取到：${domainLabels[p.domain]} / ${p.quantity}${catalog.scenarios.find((s) => s.id === p.domain).unit} / ${fulfillmentLabels[p.fulfillment]} / 预算¥${p.budget_yuan}`,
        ),
      );
      const apply = element("button", "采用这4项条件 →", "secondary");
      apply.addEventListener("click", () => {
        const s = catalog.scenarios.find((s) => s.id === p.domain);
        selectCategory(s.category, p.domain);
        $("quantity").value = p.quantity;
        $("fulfillment").value = p.fulfillment;
        $("budget").value = p.budget_yuan;
        feeNote();
        invalidateConfirmation();
        goStep(2);
        notice("已填入明确的4项条件。请重新核对，未建模内容不会随彩排执行。");
      });
      box.append(apply);
    } else
      box.append(
        element(
          "p",
          "当前不能进入彩排：尚未匹配受支持场景，或条件缺失 / 有歧义。请补充信息，下面可以下载需求清单。",
        ),
      );
    if (result.questions.length)
      box.append(element("p", "需要澄清：" + result.questions.join("；")));
    box.append(
      element(
        "p",
        "未纳入试验：" +
          (result.unmodeled_fragments.join(" / ") || "无剩余片段") +
          "。日期、地点、库存和特殊要求仍需另行确认。",
      ),
      element("p", "待找证据：" + result.evidence_needed.join("；")),
      element("p", result.data_notice),
    );
    for (const e of result.skill_events)
      box.append(
        element("p", `实际调用：${e.name} v${e.version} · ${e.status}`),
      );
    const exp = element("button", "下载需求清单 JSON", "secondary");
    exp.addEventListener("click", () =>
      downloadJSON(result, "trialtrust-request-brief.json"),
    );
    box.append(exp);
  } catch (error) {
    notice(error.message);
  } finally {
    $("compile").disabled = false;
  }
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
    read_fixture: "只读合成资料",
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
  $("result-column").hidden = true;
  $("workspace").classList.remove("has-result");
  $("result-content").hidden = true;
  $("export-preview").hidden = true;
  $("export-json").value = "";
  currentStep = $("domain").value ? 2 : 1;
  invalidateConfirmation();
}
function clearInputs() {
  $("private-task").value = "";
  $("stand-in").value = "";
  $("stand-in-stage").hidden = true;
  $("compile-result").replaceChildren();
  $("text-reviewed").checked = false;
  $("analyze-live").checked = false;
  analysisResult = null;
  $("budget").value = 200;
  $("agent").value = "demo_careful";
  $("dense").checked = false;
  chooseCase("baseline");
  selectCategory(catalog.categories[0].id);
  modeNote();
}
function restoreConditions(spec) {
  const scenario = catalog.scenarios.find((s) => s.id === spec.domain);
  if (!scenario) {
    notice("这条历史记录的场景已不可用，可以查看记录。");
    return;
  }
  selectCategory(scenario.category, spec.domain);
  $("quantity").value = spec.quantity;
  $("fulfillment").value = spec.fulfillment;
  $("budget").value = spec.budget_yuan;
  $("agent").value = spec.agent;
  $("dense").checked = spec.dense;
  chosenCase = spec.case;
  $("cases").value = spec.case;
  modeNote();
  feeNote();
  currentStep = 2;
  invalidateConfirmation();
}
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
    $("conversations").append(b);
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
    restoreConditions(rows[0].conditions);
    await loadRun(rows[0].id);
    currentStep = latestRow?.report
      ? latestRow.status === "reviewed"
        ? 4
        : 3
      : 2;
  }
  updateCoach();
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
        `${domainLabels[row.conditions.domain] || row.conditions.domain} · ¥${row.conditions.budget_yuan}`,
      ),
      element(
        "small",
        `${row.conditions.agent === "live" ? "真实模型" : "离线示例"} · ${caseLabels[row.conditions.case]} · ${row.status === "reviewed" ? "已审阅" : row.status === "running" ? "进行中" : "查看记录"}`,
      ),
    );
    b.addEventListener("click", async () => {
      invalidateConfirmation();
      await loadRun(row.id);
      if (latestRow?.report) goStep(3);
    });
    $("history").append(b);
  }
  return rows;
}
function render(row, pairSelection = "baseline") {
  $("result-column").hidden = false;
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
  const suite = row.report?.kind === "suite" ? row.report : null;
  const report = suite ? suite[pairSelection] : row.report,
    mode =
      row.conditions.agent === "live" ? "真实模型试运行" : "离线预设行为演示";
  $("run-meta").textContent =
    `${mode} · ${domainLabels[row.conditions.domain || "pottery"]} · ${caseLabels[report?.conditions?.case || row.conditions.case]} · 预算 ¥${row.conditions.budget_yuan}`;
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
  const draftCount = report.drafts.length,
    outside = report.attempted_out_of_scope_actions;
  let title = "当前条件下，没有可接受的草稿",
    description =
      "请查看模型是否指出了缺失证据或费用问题。没有草稿并不自动表示模型做错了。";
  if (report.termination !== "model_finished") {
    title =
      report.termination === "round_limit"
        ? "试运行到达轮数上限"
        : "模型输出不完整，已停止";
    description =
      "这次没有完整结束。已有草稿也需继续审阅，不能据此认定任务成功。";
  } else if (outside) {
    title = "出现越权尝试，已在沙盒拦住";
    description =
      "拦截机制发挥了作用，但被测执行者仍尝试超出授权。两件事要分别判断。";
  } else if (draftCount) {
    title = "草稿通过了当前合成条件检查";
    description =
      "已核对数量、服务方式、全部费用、预算及两类证据。自然语言说明和现实服务可用性仍需你判断。";
  }
  $("run-status").textContent = row.status === "reviewed" ? "已审阅" : "待审阅";
  const box = element("div", undefined, "finding");
  box.append(element("h2", title), element("p", description));
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
  $("answer").textContent = report.answer || "没有最终说明，请查看工具记录。";
  if (report.mandate) {
    const m = report.mandate,
      c = report.evidence_coverage;
    $("contract-report").hidden = false;
    $("contract-report").textContent =
      `本次确认条件：${domainLabels[m.domain]} / ${m.quantity}${catalog.scenarios.find((s) => s.id === m.domain)?.unit || "项"} / ${fulfillmentLabels[m.fulfillment]} / ¥${m.budget_yuan}\n查到现行价目：${c.current_price_observed ? "是" : "否"}；查到退改条款：${c.cancellation_terms_observed ? "是" : "否"}\n注入的工具故障：${report.injected_tool_faults || 0}次（与智能体错误分开记录）\n${report.delegation_note}\n条件版本：${m.digest.slice(0, 12)}`;
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
    area.append(
      element("div", "同一份委托，换一个条件", "eyebrow"),
      element("h2", `对照：${caseLabels[suite.design.case]}`),
      element("p", suite.design.rationale),
    );
    const cards = element("div", undefined, "pair-grid");
    for (const [key, label] of [
      ["baseline", "原始条件"],
      ["changed", "变化条件"],
    ]) {
      const r = suite[key],
        button = element(
          "button",
          undefined,
          `pair-card${pairSelection === key ? " selected" : ""}`,
        );
      button.append(
        element("b", label),
        element(
          "strong",
          r.drafts.length
            ? `¥${r.drafts[0].total_yuan} · ${r.drafts.length}份草稿`
            : "没有通过核验的草稿",
        ),
        element(
          "small",
          `越权尝试${r.attempted_out_of_scope_actions}次 · 测试故障${r.injected_tool_faults}次`,
        ),
      );
      button.addEventListener("click", () => render(row, key));
      cards.append(button);
    }
    area.append(
      cards,
      element(
        "p",
        "两次使用同一份已确认条件；只改变一个测试项。单次对照不构成模型排名或统计因果结论。",
        "pair-note",
      ),
    );
    const audit = suite.audit;
    area.append(
      element(
        "p",
        `${suite.execution_mode === "offline_script" ? "审阅示例" : "审阅智能体"}选出${audit.verified_facts.length}条与记录一致的事实；${audit.rejected_facts.length}条未获支持，已剔除。`,
        "pair-note",
      ),
    );
    const auditDetail = element("details", undefined, "trace-step");
    auditDetail.append(element("summary", "查看已核对的审阅事实"));
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
    area.append(auditDetail);
    if (suite.execution_mode === "live_llm") {
      const usages = [
        suite.role_usage,
        suite.baseline.run_usage,
        suite.changed.run_usage,
      ];
      if (
        usages.every((u) => u && typeof u.conservative_valued_cny === "number")
      ) {
        const total = usages.reduce((n, u) => n + u.conservative_valued_cny, 0);
        area.append(
          element(
            "p",
            `本组调用保守估值约 ¥${total.toFixed(3)}，不是账户账单；免费额度余额未核验。`,
            "pair-note",
          ),
        );
      }
    }
    $("run-meta").textContent +=
      ` · 三角色对照 / 当前回放：${pairSelection === "baseline" ? "原始条件" : "变化条件"}`;
    $("finding").prepend(
      element(
        "div",
        pairSelection === "baseline" ? "原始条件的结果" : "变化条件的结果",
        "eyebrow",
      ),
    );
  }
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
  notice();
  if (!$("domain").value) {
    notice("请先选择类别和具体需求。", "domain");
    return;
  }
  const budget = Number($("budget").value),
    quantity = Number($("quantity").value);
  if (
    $("budget").value.trim() === "" ||
    !Number.isInteger(budget) ||
    budget < 0 ||
    budget > 1000
  ) {
    notice("请填写0—1000之间的整数预算。", "budget");
    return;
  }
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > 8) {
    notice("数量目前支持1—8。", "quantity");
    return;
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
    quantity,
    fulfillment: $("fulfillment").value,
    budget_yuan: budget,
    case: isSuite ? "baseline" : $("cases").value,
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
  confirmedFor = $("confirmed").checked ? signature() : null;
  if ($("confirmed").checked) notice();
  $("confirmed").removeAttribute("aria-invalid");
  $("confirmation-status").textContent = $("confirmed").checked
    ? "✓ 已确认当前条件 · 取消勾选后不可运行"
    : "尚未确认 · 修改条件后需重新勾选";
  $("confirmation-status").classList.toggle("ok", $("confirmed").checked);
});
$("domain").addEventListener("change", () => {
  currentStep = $("domain").value ? 2 : 1;
  domainFields(true);
  invalidateConfirmation();
});
["quantity", "fulfillment", "budget"].forEach((id) =>
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
$("compile").addEventListener("click", compileStandIn);
$("stand-in").addEventListener("input", () => {
  currentStep = 1;
  $("domain").value = "";
  domainFields();
  invalidateConfirmation();
  $("text-reviewed").checked = false;
  $("compile-result").replaceChildren();
  analysisResult = null;
});
$("private-task").addEventListener("input", () => {
  currentStep = 1;
  $("domain").value = "";
  domainFields();
  invalidateConfirmation();
  $("stand-in-stage").hidden = true;
  $("text-reviewed").checked = false;
  $("compile-result").replaceChildren();
  analysisResult = null;
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
    $("single-options").open = true;
    goStep(2);
    notice("已选择测试条件。请重新确认，再点击单次试运行。");
  });
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
  restoreConditions(latestRow.conditions);
  goStep(2);
  notice("已沿用这次记录的结构化条件。请核对并重新勾选确认；不会自动运行。");
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
$("show-guide").addEventListener("click", () => showGuide($("coach").hidden));
$("close-guide").addEventListener("click", () => showGuide(false));
$("restart-guide").addEventListener("click", () => {
  showGuide();
  scrollToSection("coach");
});
$("to-conditions").addEventListener("click", () => goStep(2));
document
  .querySelectorAll("[data-step]")
  .forEach((b) =>
    b.addEventListener("click", () => goStep(Number(b.dataset.step))),
  );
$("coach-next").addEventListener("click", () =>
  goStep(currentStep === 3 ? 4 : currentStep),
);
$("help").addEventListener("click", () => $("help-dialog").showModal());
$("close-help").addEventListener("click", () => $("help-dialog").close());
$("start-tutorial").addEventListener("click", () => {
  $("help-dialog").close();
  showGuide();
  scrollToSection("coach");
});
$("dismiss-notice").addEventListener("click", () => notice());
(async () => {
  try {
    $("full-screen").hidden = !window.location.hostname.endsWith(".ms.show");
    const config = await api("/api/session", {});
    if (config.session_token) {
      sessionToken = config.session_token;
      remember("trialtrust-session", sessionToken);
    }
    liveEnabled = config.live_enabled;
    catalog = await api("/api/catalog");
    domainLabels = Object.fromEntries(
      catalog.scenarios.map((s) => [s.id, s.label]),
    );
    fulfillmentLabels = catalog.fulfillments;
    const sk = await api("/api/skills");
    skillMetadata = sk.skills;
    renderSkillCatalog();
    $("data-notice").textContent = catalog.data_notice;
    selectCategory(catalog.categories[0].id);
    const option = $("agent").querySelector('[value="live"]');
    option.disabled = !liveEnabled;
    option.textContent = liveEnabled
      ? "DeepSeek · 真实模型实测"
      : "真实模型 · 尚未启用";
    $("analyze-live").disabled = !liveEnabled;
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
