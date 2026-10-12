(() => {
  "use strict";
  const W = window.AnalyticsWire, $ = id => document.getElementById(id);
  const read = key => { try { return localStorage.getItem(key) || ""; } catch { return ""; } };
  const save = (key, value) => { try { localStorage.setItem(key, value); } catch { /* private browsing */ } };
  const state = {base: read("graphmine.apiBase"), token: read("graphmine.apiToken"), caps: null, session: null, files: [], kinds: {}, active: "", mode: "normal", operation: "", record: null, result: null, cy: null, graph: null, selected: new Set(), port: null, rows: [], filtered: [], page: 0, previews: new Map(), poll: null, epoch: 0, busy: false, domains: [], workflows: [], events: [], eventCursor: 0, eventPoll: null, legacyMessages: [], view: "domains", planning: false, pendingQuestion: null, summaries: new Map()};
  const PAGE = 30;
  const descriptions = {normal: "Ask in your own words. GraphMine checks the plan and runs it for you.", interactive: "Discuss your question, review the plan, then approve the calculation.", expert: "Inspect and edit the workflow yourself before running it."};
  const friendly = {requested_k: "Minimum connections inside the core", k: "Group size (k)", source: "Starting point", source_vertex: "Starting point", sink: "Destination", target: "Destination", target_vertex: "Comparison point", sources: "Starting points", seeds: "Required starting points", seed_vertices: "Starting points", vertices_or_seeds: "Selected vertices or starting points", connectivity_mode: "Meaning of connected", weight_mode: "How to use connection weights", result_limit: "Maximum results to list", mode: "Result to return", radius: "Maximum connection steps", depth_limit: "Maximum connection steps", quality: "Solution quality", objective: "Objective to optimize"};
  const choiceNames = {enumerate: "List each result", count: "Count only", edge_weight: "Use edge weights", unweighted: "Treat each connection equally", weakly_connected: "Connected when direction is ignored", strongly_connected: "Every member can reach every other member", induced: "Connections within the selected vertices", ego: "Neighborhood around the selected vertices", exact: "Exact", heuristic: "Heuristic"};
  const title = value => friendly[value] || String(value).replaceAll("_", " ").replace(/^./, c => c.toUpperCase());
  const display = value => value === null ? "—" : typeof value === "object" ? W.stringify(value) : typeof value === "string" ? value : String(value);
  function node(tag, attributes = {}, text) {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
      if (key === "class") element.className = value;
      else if (key === "hidden") element.hidden = value;
      else element.setAttribute(key, value);
    }
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function notice(message, error = false) {
    clearTimeout(state.noticeTimer);
    $("notice").textContent = message; $("notice").className = `notice${error ? " error" : ""}`; $("notice").hidden = !message;
    if (message && !error) state.noticeTimer = setTimeout(() => { $("notice").hidden = true; }, 5500);
  }
  async function api(path, options = {}) {
    const headers = state.token ? {Authorization: `Bearer ${state.token}`} : {};
    if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
    const response = await fetch(state.base + path, {...options, headers: {...headers, ...options.headers}});
    const text = await response.text();
    let result; try { result = W.parse(text); } catch { throw new Error("The server did not return a readable response."); }
    if (!response.ok) throw new Error(result.error?.message || result.detail?.message || (typeof result.detail === "string" ? result.detail : `Request failed (${response.status}).`));
    return result;
  }
  function activeFile() { return state.files.find(f => f.id === state.active); }
  function clearResults(message = "Waiting for a completed calculation.") {
    if (state.record) state.summaries.delete(state.record.id);
    state.result = null; state.port = null; state.rows = []; state.selected.clear();
    $("result-controls").hidden = true; $("download-result").disabled = true; $("raw-details").hidden = true;
    $("result-completeness").textContent = message; $("result-completeness").classList.remove("incomplete");
    renderOutput(); renderGraph(state.previews.get(state.active) || null);
  }
  function refs() {
    const value = {};
    for (const [index, file] of state.files.entries()) {
      if (file.id !== state.active && !state.kinds[file.id]) continue;
      value[file.id === state.active ? "main" : `data_${index + 1}`] = {file_id: file.id, kind: state.kinds[file.id] || "graph"};
    }
    return value;
  }
  function card(id) { return state.caps?.operations.find(c => c.id === id); }
  const isTable = file => file.role === "attachment" && file.original_name.toLowerCase().endsWith(".csv");
  function methodName(id) { return card(id)?.title || id; }
  function capable(c) { return c.execution[$("device").value === "gpu" ? "gpu" : "cpu"]; }
  function setMode(mode) {
    state.mode = mode;
    document.querySelectorAll("[data-mode]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.mode === mode)));
    $("mode-description").textContent = descriptions[mode];
    $("expert-panel").hidden = mode !== "expert";
    $("use-operation").textContent = mode === "normal" ? "Run this analysis" : "Build a plan to review";
    if (state.session) save(`graphmine.mode.${state.session.id}`, mode);
    if (mode === "expert" && !$("plan-editor").value) loadEditor();
  }
  async function runAction(fn) {
    if (state.busy) return;
    state.busy = true;
    const controls = ["plan-question", "use-operation", "save-editor", "sample-data", "data-upload", "new-session", "session-select", "active-input", "active-kind", "device"];
    controls.forEach(id => $(id).disabled = true);
    document.querySelectorAll("[data-mode]").forEach(button => button.disabled = true);
    try { await fn(); } catch (error) { notice(error.message, true); }
    finally { state.busy = false; controls.forEach(id => $(id).disabled = false); document.querySelectorAll("[data-mode]").forEach(button => button.disabled = false); }
  }
  const stageNames = {family: "Understanding your question", operation: "Choosing the calculation", plan: "Building a valid plan", retrieval: "Checking reviewed examples"};
  function route(page = "chat", workflow = "") {
    return state.session ? `#workspace/${encodeURIComponent(state.session.id)}/${page}${workflow ? `/${encodeURIComponent(workflow)}` : ""}` : "#";
  }
  function showPage(page) {
    state.view = page;
    $("domain-view").hidden = page !== "domains";
    $("workspace-view").hidden = page !== "chat";
    $("results-view").hidden = page !== "results";
    $("workspace-nav").hidden = page === "domains";
    $("chat-page-link").href = route("chat");
    $("results-page-link").href = route("results", state.record?.id || "");
    $("chat-page-link").setAttribute("aria-current", page === "chat" ? "page" : "false");
    $("results-page-link").setAttribute("aria-current", page === "results" ? "page" : "false");
    if (page === "results") requestAnimationFrame(() => { renderGraph(state.graph); state.cy?.resize(); state.cy?.fit(undefined, 35); });
  }
  function go(page, workflow = "") {
    const next = route(page, workflow);
    if (location.hash === next) showPage(page); else location.hash = next;
  }
  async function applyRoute() {
    const match = /^#workspace\/([^/]+)(?:\/(chat|results)(?:\/([^/]+))?)?$/.exec(location.hash);
    const id = match ? decodeURIComponent(match[1]) : "";
    if (state.busy && id !== state.session?.id) { history.replaceState(null, "", route(state.view)); return; }
    if (!match) { if (state.session) await openSession(""); else showPage("domains"); return; }
    if (id !== state.session?.id) await openSession(id);
    if (match[3] && decodeURIComponent(match[3]) !== state.record?.id) {
      const workflow = state.workflows.find(row => row.id === decodeURIComponent(match[3]));
      if (!workflow) throw new Error("This analysis is not part of the selected conversation.");
      await openWorkflow(workflow.id);
    }
    showPage(match[2] || "chat");
  }
  function renderDomains() {
    const glyphs = ["◇", "↗", "◎", "⌘", "◈", "⟷", "◉", "✧"];
    $("domain-grid").replaceChildren();
    state.domains.forEach((domain, index) => {
      const button = node("button", {class: "domain-card", "data-domain": domain.id});
      button.append(node("span", {class: "domain-icon", "aria-hidden": "true"}, glyphs[index % glyphs.length]), node("strong", {}, domain.name), node("span", {}, domain.description));
      button.addEventListener("click", () => runAction(async () => {
        const session = await api("/api/sessions", {method: "POST", body: W.stringify({domain_id: domain.id, title: $("session-name").value.trim() || `${domain.name} conversation`})});
        await openSession(session.id); history.pushState(null, "", route("chat")); await loadSessions();
      }));
      $("domain-grid").append(button);
    });
  }
  async function loadSessions() {
    const sessions = await api("/api/sessions?limit=100");
    $("session-select").replaceChildren(node("option", {value: ""}, "New conversation"));
    $("recent-sessions").replaceChildren();
    for (const session of sessions) {
      $("session-select").append(node("option", {value: session.id}, session.title || "Untitled conversation"));
      const link = node("a", {class: "recent-session", href: `#workspace/${encodeURIComponent(session.id)}/chat`});
      const domain = state.domains.find(row => row.id === session.domain_id);
      link.append(node("strong", {}, session.title || "Untitled conversation"), node("span", {}, domain?.name || session.domain_id), node("span", {"aria-hidden": "true"}, "→"));
      $("recent-sessions").append(link);
    }
    $("session-select").value = state.session?.id || "";
  }
  async function ensureSession() {
    if (!state.session) throw new Error("Choose a domain to start your conversation.");
    return state.session;
  }
  async function openSession(id) {
    clearTimeout(state.poll); clearTimeout(state.eventPoll); state.epoch++;
    state.session = null; state.files = []; state.kinds = {}; state.active = ""; state.record = null; state.previews.clear();
    state.events = []; state.workflows = []; state.eventCursor = 0; state.legacyMessages = []; state.pendingQuestion = null; state.summaries.clear();
    $("workflow-panel").hidden = true; $("plan-editor").value = "";
    notice(""); clearResults("Upload a graph in Chat to preview its connections here.");
    if (!id) { showPage("domains"); renderConversation(); return; }
    const workspace = await api(`/api/sessions/${encodeURIComponent(id)}/workspace`);
    state.session = workspace.session;
    $("session-select").value = state.session.id;
    state.files = workspace.files.filter(f => ["graph", "query_graph", "motif", "attachment"].includes(f.role));
    state.legacyMessages = workspace.messages;
    state.events = workspace.events;
    state.eventCursor = Math.max(0, ...state.events.map(event => Number(event.sequence)));
    const domain = state.domains.find(row => row.id === state.session.domain_id);
    $("active-domain").textContent = domain?.name || state.session.domain_id;
    $("active-domain-description").textContent = domain?.description || "";
    $("chat-domain-label").textContent = domain?.name || "Your conversation";
    $("workspace-title").textContent = state.session.title || "New conversation";
    $("results-session-title").textContent = state.session.title || "Your conversation";
    try { state.kinds = W.parse(read(`graphmine.inputKinds.${id}`) || "{}"); } catch { state.kinds = {}; }
    for (const file of state.files) if (file.role !== "attachment") state.kinds[file.id] = "graph";
    state.active = state.files.find(file => !isTable(file))?.id || "";
    setMode(read(`graphmine.mode.${id}`) || "normal");
    showPage("chat"); renderFiles(); await loadSaved();
    if (state.workflows.length) await openWorkflow(state.workflows.at(-1).id);
    else if (state.active) await previewActive();
    renderConversation(); renderActivity(); pollConversation();
  }
  function messageElement(role, message, label = "") {
    const article = node("article", {class: `chat-message ${role}`}), bubble = node("div", {class: "chat-bubble"});
    article.append(node("div", {class: "chat-avatar", "aria-hidden": "true"}, role === "user" ? "You" : "G"));
    if (label) bubble.append(node("span", {class: "chat-label"}, label));
    bubble.append(node("p", {}, message)); article.append(bubble);
    return {article, bubble};
  }
  function appendOutcome(bubble, record) {
    const status = {completed: "Analysis complete", awaiting_review: "Ready for your review", ready: "Ready for your review", queued: "Your calculation is queued", running: "Your calculation is running", failed: "The calculation failed", interrupted: "The calculation was interrupted", cancelled: "The calculation was cancelled"}[record.status] || title(record.status);
    bubble.append(node("p", {class: "workflow-outcome"}, state.summaries.get(record.id) || `${status}. ${record.error?.message || ""}`));
    if (record.status === "completed") bubble.append(node("a", {class: "result-link", href: route("results", record.id)}, "View results & visualizations →"));
    else {
      const button = node("button", {class: "quiet", type: "button"}, ["ready", "awaiting_review"].includes(record.status) ? "Review this plan" : "Inspect this analysis");
      button.addEventListener("click", () => runAction(async () => { await openWorkflow(record.id); go("chat"); $("workflow-panel").scrollIntoView({block: "nearest"}); }));
      bubble.append(button);
    }
  }
  function renderConversation() {
    const scroll = $("conversation-scroll"), atBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 90;
    const openDetails = new Set([...$("messages").querySelectorAll("details[open]")].map(el => el.dataset.turn));
    const container = $("messages"); container.replaceChildren();
    const domain = state.domains.find(row => row.id === state.session?.domain_id);
    const greeting = messageElement("assistant", `Let's explore ${domain ? domain.name.toLowerCase() : "your network"}. Upload your data and ask a question in your own words. I'll explain the plan and help you work through the findings.`, "GraphMine");
    container.append(greeting.article);
    for (const row of state.legacyMessages) if (row.message) container.append(messageElement(row.role === "user" ? "user" : "assistant", row.message).article);
    const chats = state.events.filter(event => event.type === "workflow.chat" && !event.payload.evaluation_id);
    for (const event of chats) {
      const row = event.payload, item = messageElement(row.role, row.message, row.role === "user" ? `${title(row.mode || "normal")} mode` : "GraphMine");
      item.article.dataset.turn = row.turn_id;
      if (row.role === "assistant") {
        const decisions = state.events.filter(e => e.type === "workflow.planning" && e.payload.turn_id === row.turn_id && e.payload.message);
        if (decisions.length) {
          const details = node("details", {class: "chat-decision", "data-turn": row.turn_id}); details.open = openDetails.has(row.turn_id);
          details.append(node("summary", {}, "How this was planned"));
          decisions.forEach(e => details.append(node("p", {}, e.payload.message)));
          item.bubble.append(details);
        }
        const reasoning = state.events.filter(e => e.type === "workflow.reasoning" && e.payload.turn_id === row.turn_id);
        if (reasoning.length) {
          const details = node("details", {class: "chat-decision", "data-turn": `${row.turn_id}-reasoning`}); details.open = openDetails.has(`${row.turn_id}-reasoning`);
          details.append(node("summary", {}, "Model reasoning"));
          for (const event of reasoning) { const stage = node("details", {class: "reasoning-record"}); stage.append(node("summary", {}, stageNames[event.payload.stage] || title(event.payload.stage)), node("pre", {}, event.payload.text)); details.append(stage); }
          item.bubble.append(details);
        }
        const record = state.workflows.findLast(record => record.planning_turn_id === row.turn_id);
        if (record) appendOutcome(item.bubble, record);
        else if (row.plan && row.status === "ready") {
          const button = node("button", {class: "quiet"}, "Continue with this plan");
          button.addEventListener("click", () => runAction(() => submitPlan(row.plan, false, row.turn_id, row.inputs, row.mode)));
          item.bubble.append(button);
        }
      }
      container.append(item.article);
    }
    for (const record of state.workflows.filter(record => !record.planning_turn_id)) {
      const item = messageElement("assistant", record.validation.plan.steps.map(step => methodName(step.operation)).join(" → "), "Saved analysis");
      appendOutcome(item.bubble, record); container.append(item.article);
    }
    if (state.pendingQuestion) container.append(messageElement("user", state.pendingQuestion.message, `${title(state.mode)} mode`).article);
    if (state.planning || chats.at(-1)?.payload.role === "user") container.append(messageElement("assistant", "Working through your question… Follow the reasoning and activity alongside this conversation.", "GraphMine").article);
    if (atBottom || state.pendingQuestion) requestAnimationFrame(() => { scroll.scrollTop = scroll.scrollHeight; });
  }
  function renderActivity() {
    const latest = [...state.events].reverse().find(event => event.type === "workflow.chat" && event.payload.role === "user");
    const turn = latest?.payload.turn_id;
    const events = state.events.filter(event => event.payload.turn_id === turn);
    $("activity-list").replaceChildren();
    const stages = new Map();
    for (const event of events) if (event.type === "workflow.planning") stages.set(event.payload.stage, event.payload);
    for (const [stage, decision] of stages) {
      const running = decision.status === "running";
      const item = node("li", {class: `activity-step ${running ? "running" : "completed"}`});
      item.append(node("span", {class: "activity-marker", "aria-hidden": "true"}, running ? "·" : "✓"));
      const content = node("div"); content.append(node("strong", {}, stageNames[stage] || title(stage)), node("p", {}, decision.message || (running ? "The model is considering your question." : "Checked.")));
      item.append(content); $("activity-list").append(item);
    }
    const outcome = events.findLast(event => event.type === "workflow.chat" && event.payload.role === "assistant")?.payload;
    const running = [...stages.values()].some(stage => stage.status === "running") && !outcome;
    const workflow = state.workflows.findLast(record => record.planning_turn_id === turn) || state.record;
    const status = running || state.planning ? "Thinking through your question…" : workflow ? ({completed: "Analysis complete", awaiting_review: "Waiting for your approval", ready: "Waiting for your approval", queued: "Calculation queued", running: "Running the calculation"}[workflow.status] || title(workflow.status)) : outcome?.status === "needs_information" ? "Waiting for your reply" : outcome?.status === "failed" ? "Planning failed" : "Ready for your question";
    $("activity-status").textContent = status; $("chat-status").textContent = running || state.planning ? "Thinking…" : status;
    const detailsOpen = new Set([...$("model-reasoning").querySelectorAll("details[open]")].map(e => e.dataset.sequence));
    $("model-reasoning").replaceChildren();
    const reasoning = events.filter(event => event.type === "workflow.reasoning");
    $("reasoning-count").textContent = String(reasoning.length);
    for (const event of reasoning) {
      const details = node("details", {class: "reasoning-record", "data-sequence": event.sequence}); details.open = detailsOpen.has(String(event.sequence));
      details.append(node("summary", {}, stageNames[event.payload.stage] || title(event.payload.stage)), node("small", {}, event.payload.model), node("pre", {}, event.payload.text));
      $("model-reasoning").append(details);
    }
    if (!reasoning.length) $("model-reasoning").append(node("p", {class: "muted"}, running ? "Reasoning will appear after the model finishes each stage." : "No reasoning text returned for this question yet."));
  }
  async function syncConversation() {
    if (!state.session) return;
    const id = state.session.id, epoch = state.epoch;
    const events = await api(`/api/sessions/${id}/events?after=${state.eventCursor}`);
    if (epoch !== state.epoch) return;
    const fresh = events.filter(event => Number(event.sequence) > state.eventCursor);
    if (fresh.length) {
      state.events.push(...fresh); state.eventCursor = Number(fresh.at(-1).sequence);
      if (state.pendingQuestion && fresh.some(e => e.type === "workflow.chat" && e.payload.role === "user" && e.sequence > state.pendingQuestion.after)) state.pendingQuestion = null;
      renderConversation(); renderActivity();
    }
  }
  function pollConversation() {
    clearTimeout(state.eventPoll); const epoch = state.epoch;
    state.eventPoll = setTimeout(async () => {
      try { await syncConversation(); } catch { /* Reconnect on the next poll; saved messages remain visible. */ }
      if (epoch === state.epoch && state.session) pollConversation();
    }, 1400);
  }
  function requestId() {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = [...bytes].map(value => value.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  }
  async function savedPlanningResponse(id, originalError) {
    const started = Date.now(), epoch = state.epoch;
    while (Date.now() - started < 360000 && epoch === state.epoch) {
      try { await syncConversation(); } catch { /* A temporary disconnect can also affect the event request. */ }
      const events = state.events.filter(event => event.type === "workflow.chat" && event.payload.turn_id === id);
      const response = events.find(event => event.payload.role === "assistant");
      if (response) { notice(""); return response.payload; }
      if (!events.length && Date.now() - started > 15000) throw originalError;
      if (events.length) $("activity-status").textContent = "Your saved request is still being processed…";
      await new Promise(resolve => setTimeout(resolve, 1500));
    }
    throw new Error("Your planning request is saved. Reopen this conversation to check its progress.");
  }
  function renderFiles() {
    $("active-input").replaceChildren(node("option", {value: ""}, "Choose an input"));
    state.files.filter(f => !isTable(f)).forEach(f => $("active-input").append(node("option", {value: f.id}, f.original_name)));
    $("active-input").value = state.active;
    $("input-aliases").replaceChildren();
    for (const [alias, value] of Object.entries(refs())) $("input-aliases").append(node("span", {}, `${alias}: ${value.kind}`));
    const f = activeFile();
    $("active-kind-label").hidden = f?.role !== "attachment";
    $("active-kind").value = state.kinds[state.active] || "graph";
    $("data-summary").textContent = f ? (state.kinds[f.id] === "graph" ? `${f.original_name} · ${f.metadata?.vertex_count ?? "?"} vertices · ${f.metadata?.edge_count ?? "?"} connections. The calculation uses the full input.` : `${f.original_name} · ${title(state.kinds[f.id] || "input")}. The calculation uses the full input.`) : "Your analysis uses the full uploaded input.";
    if (state.session) save(`graphmine.inputKinds.${state.session.id}`, W.stringify(state.kinds));
    renderParameters();
  }
  async function upload(file, kind = $("upload-kind").value) {
    await ensureSession();
    const form = new FormData(); form.append("file", file); form.append("role", kind === "graph" ? "graph" : "attachment");
    form.append("directed", String($("csv-directed").checked));
    if ($("csv-source").value.trim()) form.append("source_column", $("csv-source").value.trim());
    if ($("csv-target").value.trim()) form.append("target_column", $("csv-target").value.trim());
    const result = await api(`/api/sessions/${state.session.id}/files`, {method: "POST", body: form});
    state.files.push(result); state.kinds[result.id] = kind; state.active = result.id;
    renderFiles(); await previewActive(); notice("Your data is ready. Ask a question to begin.");
  }
  async function preview(fileId) {
    if (!state.previews.has(fileId)) state.previews.set(fileId, await api(`/api/files/${fileId}/graph-preview?vertex_limit=500&edge_limit=2000`));
    return state.previews.get(fileId);
  }
  async function previewActive() {
    if (state.kinds[state.active] !== "graph") { renderGraph(null); $("preview-scope").textContent = state.kinds[state.active] === "graph_collection" ? "Each collection member has its own vertices. Computed patterns can be viewed after mining." : "A generated graph can be viewed after computation."; renderParameters(); return; }
    const id = state.active, value = await preview(id);
    if (id === state.active && !state.result) renderGraph(value);
    renderParameters();
  }
  function renderOperations() {
    $("operation-select").replaceChildren(node("option", {value: ""}, "Choose a calculation"));
    for (const selected of state.caps.operations.filter(capable)) $("operation-select").append(node("option", {value: selected.id}, selected.title));
    $("operation-select").value = state.operation;
    renderParameters();
  }
  function parameterControl(key, spec, value, prefix) {
    const label = node("label", {}, title(key)), id = `${prefix}-${key}`;
    let input;
    if (spec.choices) {
      input = node("select", {id, "data-parameter": key});
      if (spec.required) input.append(node("option", {value: ""}, "Choose…"));
      else if (spec.nullable) input.append(node("option", {value: "null"}, "Not specified"));
      spec.choices.forEach(choice => input.append(node("option", {value: W.stringify(choice)}, choiceNames[choice] || title(choice))));
      input.value = value === undefined ? (spec.required ? "" : W.stringify(spec.choices[0])) : W.stringify(value);
    } else if (spec.kind === "boolean") {
      input = node("select", {id, "data-parameter": key});
      input.append(node("option", {value: "true"}, "Yes"), node("option", {value: "false"}, "No")); input.value = String(value ?? false);
    } else if (["array", "object"].includes(spec.kind)) {
      input = node("textarea", {id, "data-parameter": key, rows: "2", spellcheck: "false", placeholder: spec.kind === "array" ? '["Alice", "Bob"]' : "{}"});
      input.value = value === undefined || value === null ? "" : W.stringify(value);
    } else {
      input = node("input", {id, "data-parameter": key, type: "text", spellcheck: "false"});
      input.value = value === undefined || value === null ? "" : spec.kind === "vertex_id" ? W.stringify(value) : String(value);
      if (["integer", "number"].includes(spec.kind)) input.setAttribute("inputmode", "decimal");
      if (spec.kind === "vertex_id") {
        input.placeholder = '"Alice" or 42';
        const list = node("datalist", {id: `${id}-choices`});
        for (const v of (state.previews.get(state.active)?.vertices || [])) list.append(node("option", {value: W.stringify(v.id)}, v.label || W.idLabel(v.id)));
        input.setAttribute("list", list.id); label.append(list);
      }
    }
    if (spec.required) input.setAttribute("aria-required", "true");
    label.append(input);
    if (["query_graph", "other_graph"].includes(key)) {
      const binding = node("select", {"data-binding-parameter": key, "aria-label": `${title(key)} input source`});
      binding.append(node("option", {value: ""}, "Enter canonical graph JSON above"));
      for (const [alias, source] of Object.entries(refs())) if (source.kind === "graph") binding.append(node("option", {value: alias}, `Use uploaded graph: ${alias}`));
      binding.addEventListener("change", () => input.disabled = Boolean(binding.value));
      label.append(binding);
    }
    if (spec.description || spec.required) label.append(node("span", {class: "parameter-hint"}, `${spec.required ? "Required. " : ""}${spec.description || ""}`));
    if (spec.nullable && !spec.choices) label.append(node("span", {class: "parameter-hint"}, "Leave empty to use the default or no limit."));
    return label;
  }
  function renderParameters() {
    const selected = card(state.operation);
    $("operation-parameters").replaceChildren();
    $("operation-description").textContent = selected?.description || "";
    $("operation-quality").textContent = selected ? `Input: ${title(selected.input_kind)} · Method profile: ${title(selected.quality)}` : "";
    if (!selected) return;
    const optional = node("details"), content = node("div");
    optional.append(node("summary", {}, "Method settings and optional outputs"), content);
    for (const [key, spec] of Object.entries(selected.parameters)) {
      const field = parameterControl(key, spec, spec.default, "parameter");
      (spec.required ? $("operation-parameters") : content).append(field);
    }
    if (content.children.length) $("operation-parameters").append(optional);
  }
  function parametersFrom(container, selected, defaults = {}) {
    const parameters = {...defaults};
    for (const input of container.querySelectorAll("[data-parameter]")) {
      const key = input.dataset.parameter, spec = selected.parameters[key], raw = input.value.trim();
      if (input.disabled) { delete parameters[key]; continue; }
      if (!raw) {
        if (spec.required) throw new Error(`Choose ${title(key).toLowerCase()} before continuing.`);
        parameters[key] = spec.default;
        continue;
      }
      try { parameters[key] = spec.kind === "string" && !spec.choices ? input.value : W.parse(raw); }
      catch { throw new Error(`${title(key)} needs a valid ${spec.kind === "vertex_id" ? 'ID (a quoted name or integer)' : spec.kind} value.`); }
    }
    return parameters;
  }
  function bindingsFrom(container, defaults = {}) {
    const bindings = {...defaults};
    for (const input of container.querySelectorAll("[data-binding-parameter]")) {
      const key = input.dataset.bindingParameter;
      if (input.value) bindings[key] = {input: input.value}; else delete bindings[key];
    }
    return bindings;
  }
  function planFromOperation() {
    const selected = card(state.operation);
    if (!selected) throw new Error("Choose a calculation first.");
    if (!activeFile()) throw new Error("Upload or choose an input first.");
    if (state.kinds[state.active] !== selected.input_kind) throw new Error(`This calculation needs ${title(selected.input_kind)} input. Choose the matching uploaded data.`);
    return {version: 1, device: $("device").value, steps: [{id: "analysis", operation: selected.id, input: {input: "main"}, parameters: parametersFrom($("operation-parameters"), selected), bindings: bindingsFrom($("operation-parameters"))}]};
  }
  function loadEditor() {
    const plan = state.record?.validation.plan || (state.operation ? planFromOperation() : {version: 1, device: $("device").value, steps: [{id: "groups", operation: "connected-components", input: {input: "main"}, parameters: {}}]});
    $("plan-editor").value = W.stringify(plan, true);
  }
  async function submitPlan(plan, revise = false, turnId = null, inputFiles = null, requestedMode = null) {
    await ensureSession();
    if (!state.active) throw new Error("Choose an input before saving the plan.");
    const body = {mode: requestedMode || state.mode, plan, inputs: revise && state.record ? state.record.input_files : inputFiles || refs()};
    if (turnId) body.planning_turn_id = turnId;
    let path = `/api/sessions/${state.session.id}/workflows`;
    if (revise && state.record) { path = `/api/workflows/${state.record.id}/revise`; body.expected_revision = state.record.revision; }
    const result = await api(path, {method: "POST", body: W.stringify(body)});
    state.record = result; setMode(result.mode); if (result.input_files.main) { state.active = result.input_files.main.file_id; renderFiles(); } clearResults(result.status === "queued" ? "The calculation is queued; no new result has been produced." : "This plan is awaiting execution; no new result has been produced."); renderWorkflow(); await loadSaved();
    if (state.view === "chat") $("workflow-panel").scrollIntoView({behavior: "smooth", block: "nearest"});
    notice(result.status === "queued" ? "The validated workflow is queued." : "Your plan is ready to review. Execution has not started.");
    if (["queued", "running"].includes(result.status)) pollWorkflow();
  }
  async function askQuestion(event) {
    event.preventDefault();
    await runAction(async () => {
      const message = $("question").value.trim();
      if (!message) throw new Error("Describe what you want to learn.");
      if (!state.active) throw new Error("Add your data first, then send your question.");
      await ensureSession();
      const inputs = refs(), mode = state.mode, previous = state.record?.id || null;
      state.pendingQuestion = {message, after: state.eventCursor}; state.planning = true;
      $("question").value = ""; notice(""); renderConversation(); renderActivity();
      try {
        const id = requestId();
        let response;
        try {
          response = await api(`/api/sessions/${state.session.id}/analytics/plan`, {method: "POST", body: W.stringify({message, mode, inputs, device: $("device").value, previous_workflow_id: previous, request_id: id})});
        } catch (error) {
          if (!["TypeError", "NetworkError"].includes(error?.name)) throw error;
          response = await savedPlanningResponse(id, error);
        }
        await syncConversation();
        if (response.status === "ready" && response.plan) {
          $("plan-editor").value = W.stringify(response.plan, true);
          await submitPlan(response.plan, false, response.turn_id, inputs, mode);
        }
      } finally { state.planning = false; state.pendingQuestion = null; await syncConversation(); renderConversation(); renderActivity(); }
    });
  }
  async function loadSaved() {
    $("saved-workflows").replaceChildren();
    if (!state.session) return;
    state.workflows = await api(`/api/sessions/${state.session.id}/workflows`);
    $("result-select").replaceChildren(node("option", {value: ""}, "Choose a saved analysis"));
    $("result-count").textContent = String(state.workflows.filter(record => record.status === "completed").length);
    for (const record of state.workflows.slice().reverse()) {
      const label = record.validation.plan.steps.map(step => methodName(step.operation)).join(" → ");
      const button = node("button", {"data-workflow": record.id, "aria-current": String(record.id === state.record?.id)}, label);
      button.append(node("small", {}, `${title(record.status)} · revision ${record.revision}`));
      button.addEventListener("click", () => runAction(async () => { await openWorkflow(record.id); go(record.status === "completed" ? "results" : "chat", record.status === "completed" ? record.id : ""); }));
      $("saved-workflows").append(button);
      $("result-select").append(node("option", {value: record.id}, `${label} · ${title(record.status)}`));
    }
    $("result-select").value = state.record?.id || "";
    renderConversation(); renderActivity();
  }
  function renderWorkflow() {
    const record = state.record; if (!record) return;
    $("results-page-link").href = route("results", record.id);
    $("workflow-panel").hidden = false;
    $("workflow-panel").dataset.review = String(record.mode !== "normal" || ["ready", "awaiting_review", "failed", "interrupted"].includes(record.status));
    const savedIndex = state.workflows.findIndex(row => row.id === record.id);
    if (savedIndex >= 0) state.workflows[savedIndex] = record;
    renderActivity();
    $("workflow-status").textContent = title(record.status);
    $("workflow-summary").textContent = `Revision ${record.revision} · ${title(record.mode)} mode · ${record.validation.plan.device === "auto" ? "Automatic device choice" : record.validation.plan.device.toUpperCase() + " only"}. ${record.error?.message || ""}`;
    $("plan-details").textContent = W.stringify({plan: record.validation.plan, input_fingerprints: record.validation.inputs, workflow_hash: record.validation.workflow_hash, approved_hash: record.approved_hash}, true);
    $("workflow-steps").replaceChildren();
    for (const id of record.validation.order) {
      const step = record.validation.plan.steps.find(s => s.id === id), status = record.steps[id]?.status || "pending";
      const li = node("li", {class: "workflow-step", "data-step": id, "data-status": status});
      li.append(node("span", {class: "step-state"}, status));
      const button = node("button", {}, methodName(step.operation));
      button.addEventListener("click", () => { if (state.result?.steps[id]?.result) { $("result-step").value = id; selectStep(); go("results", record.id); } });
      li.append(button, node("small", {}, `Step: ${id}`), node("small", {}, step.input.input ? `Input: ${step.input.input}` : `Input: ${step.input.step} / ${step.input.port}`));
      for (const [parameter, reference] of Object.entries(step.bindings)) li.append(node("small", {}, `${title(parameter)} ← ${reference.input || `${reference.step} / ${reference.port}`}`));
      if (record.steps[id]?.reused) li.append(node("small", {}, "Reused a matching verified result"));
      if (record.steps[id]?.error) li.append(node("small", {class: "step-error"}, record.steps[id].error.message));
      const details = node("details", {class: "step-editor"}); details.append(node("summary", {}, "Inspect settings"));
      const dl = node("div");
      for (const [key, value] of Object.entries(step.parameters)) dl.append(node("small", {}, `${title(key)}: ${display(value)}`));
      details.append(dl); li.append(details); $("workflow-steps").append(li);
      if (!["queued", "running"].includes(record.status)) {
        const edit = node("details", {class: "step-editor"}); edit.append(node("summary", {}, "Edit settings"));
        const form = node("form", {"data-edit-step": id}), selected = card(step.operation);
        for (const [key, value] of Object.entries(step.parameters)) form.append(parameterControl(key, selected.parameters[key], value, `edit-${id}`));
        form.append(node("button", {type: "submit", class: "secondary"}, record.mode === "normal" ? "Save and run changes" : "Save for review"));
        form.addEventListener("submit", event => { event.preventDefault(); runAction(async () => { const plan = W.parse(W.stringify(record.validation.plan)), edited = plan.steps.find(s => s.id === id); edited.parameters = parametersFrom(form, selected, step.parameters); edited.bindings = bindingsFrom(form, step.bindings); setMode(record.mode); await submitPlan(plan, true); }); });
        edit.append(form); li.append(edit);
      }
    }
    const running = ["queued", "running"].includes(record.status);
    $("cancel-workflow").hidden = !running;
    $("approve-plan").hidden = running || record.status === "completed";
    $("approve-plan").textContent = ["failed", "cancelled", "interrupted"].includes(record.status) ? "Retry reviewed plan" : "Approve and run";
    $("edit-plan").disabled = running;
    $("review-example").hidden = record.status !== "completed" || !record.complete || Boolean(record.evaluation_id);
    $("workflow-heading").textContent = running ? "Your analysis is running" : record.status === "completed" ? "Analysis complete" : "Review the steps";
  }
  async function openWorkflow(id) {
    clearTimeout(state.poll); state.record = await api(`/api/workflows/${id}`); setMode(state.record.mode);
    const input = state.record.input_files.main;
    if (input) { state.active = input.file_id; state.kinds[input.file_id] = input.kind; renderFiles(); }
    clearResults();
    renderWorkflow(); await loadSaved();
    if (["queued", "running"].includes(state.record.status)) pollWorkflow();
    else if (["completed", "failed", "cancelled", "interrupted"].includes(state.record.status)) await loadResults();
  }
  function pollWorkflow() {
    clearTimeout(state.poll);
    const id = state.record?.id, epoch = state.epoch;
    state.poll = setTimeout(async () => {
      try {
        const record = await api(`/api/workflows/${id}`);
        if (epoch !== state.epoch || state.record?.id !== id) return;
        state.record = record; renderWorkflow(); renderConversation();
        if (["queued", "running"].includes(record.status)) pollWorkflow();
        else { await loadSaved(); await loadResults(); notice(record.status === "completed" ? "The computed results are ready." : record.error?.message || `Execution ${record.status}. Inspect the step status for details.`, record.status === "failed"); }
      } catch (error) { notice(error.message, true); }
    }, 600);
  }
  async function loadResults() {
    const id = state.record.id;
    try { state.result = await api(`/api/workflows/${id}/result`); }
    catch (error) {
      const steps = {};
      for (const [step, record] of Object.entries(state.record.steps)) if (record.status === "completed") steps[step] = await api(`/api/workflows/${id}/steps/${step}/result`);
      state.result = {partial_workflow: true, complete: false, workflow: state.record, steps};
      if (!Object.keys(steps).length) { $("result-completeness").textContent = state.record.error?.message || "No step produced a completed result."; return; }
    }
    $("result-controls").hidden = false; $("download-result").disabled = false; $("raw-details").hidden = false;
    const raw = W.stringify(state.result, true);
    $("raw-result").textContent = raw.slice(0, 40000) + (raw.length > 40000 ? "\n… Preview only. Download the full result for all values." : "");
    $("result-step").replaceChildren();
    for (const step of state.record.validation.order) if (state.result.steps[step]?.result) $("result-step").append(node("option", {value: step}, `${step} · ${methodName(state.result.steps[step].result.operation)}`));
    $("result-step").value = $("result-step").lastElementChild?.value || "";
    await selectStep();
    const scalar = Object.values(state.result.steps || {}).flatMap(step => Object.entries(step.result?.ports || {})).filter(([,port]) => port.complete && ["number", "bigint"].includes(typeof port.value));
    if (state.record.status === "completed" && state.result.complete && scalar.length) state.summaries.set(id, scalar.map(([name, port]) => `${title(name)}: ${display(port.value)}`).join(" · "));
    renderConversation();
  }
  async function graphForStep(stepId) {
    const step = state.record.validation.plan.steps.find(s => s.id === stepId);
    if (step.input.input) {
      const input = state.record.input_files[step.input.input];
      return input?.kind === "graph" ? preview(input.file_id) : null;
    }
    const port = state.result.steps[step.input.step]?.result?.ports[step.input.port];
    if (port?.type === "pattern_collection" && step.input.select?.kind === "pattern_graph") return port.value[Number(step.input.select.index)]?.pattern || null;
    return port?.type === "graph" ? port.value : null;
  }
  async function selectStep() {
    const step = state.result?.steps[$("result-step").value]?.result;
    $("result-port").replaceChildren(); state.selected.clear(); state.page = 0; $("table-search").value = "";
    if (!step) return;
    Object.entries(step.ports).forEach(([name, port]) => $("result-port").append(node("option", {value: name}, `${title(name)} · ${title(port.type)}`)));
    if (!Object.keys(step.ports).length) $("result-port").append(node("option", {value: "__result"}, "Recorded result"));
    const preference = ["vertex_scores", "pattern_collection", "vertex_positions", "rational_scalar", "vertex_groups", "table", "graph"];
    const materialized = Object.entries(step.ports).filter(([,p]) => p.complete || !Array.isArray(p.value) || p.value.length);
    const choices = materialized.length ? materialized : Object.entries(step.ports);
    $("result-port").value = preference.map(type => choices.find(([,p]) => p.type === type)?.[0]).find(Boolean) || choices[0]?.[0] || "__result";
    await selectPort();
  }
  async function selectPort() {
    const stepId = $("result-step").value, result = state.result?.steps[stepId]?.result;
    if (!result) return;
    const name = $("result-port").value;
    state.port = name === "__result" ? {type: "result", complete: result.complete, value: result.result} : result.ports[name];
    const port = state.port; state.rows = Array.isArray(port.value) ? port.value : [port.value]; state.page = 0; state.selected.clear(); $("table-search").value = "";
    $("result-completeness").classList.toggle("incomplete", !port.complete || !result.complete);
    $("result-completeness").textContent = `${port.complete ? "This output collection is complete." : "This output is incomplete or count-only; it cannot supply a full downstream collection."} Method quality: ${title(result.quality)}. Computed on ${result.backend.device.toUpperCase()}.`;
    if (!port.complete && result.diagnostics?.narrowing_hint) $("result-completeness").textContent += ` ${result.diagnostics.narrowing_hint}`;
    state.patternId = port.type === "pattern_collection" ? port.value[0]?.pattern_id || null : null;
    const graph = port.type === "graph" ? port.value : port.type === "pattern_collection" ? port.value[0]?.pattern || null : await graphForStep(stepId);
    if (port.type === "vertex_positions") $("graph-layout").value = "computed";
    renderGraph(graph); renderOutput();
  }
  function renderGraph(data) {
    if (state.view !== "results") {
      state.cy?.destroy(); state.cy = null; state.graph = data;
      $("network").replaceChildren(); $("preview-scope").textContent = "";
      return;
    }
    state.cy?.destroy(); state.cy = null; state.graph = data;
    $("graph-layout").querySelector('[value="computed"]').disabled = state.port?.type !== "vertex_positions";
    if (state.port?.type !== "vertex_positions" && $("graph-layout").value === "computed") $("graph-layout").value = "cose";
    $("network").replaceChildren(); $("preview-scope").textContent = ""; $("selection-detail").textContent = "Select a node or a result row to inspect it.";
    if (!data?.vertices || !window.cytoscape) return;
    const vertices = data.vertices.slice(0, 500), keys = new Set(vertices.map(v => W.idKey(v.id)));
    const edges = data.edges.filter(e => keys.has(W.idKey(e.source)) && keys.has(W.idKey(e.target))).slice(0, 2000);
    const elements = vertices.map(v => ({data: {id: W.idKey(v.id), label: String(v.label || v.name || v.id), original: v, entity: v.id}}));
    edges.forEach((e, index) => elements.push({data: {id: `edge:${index}`, source: W.idKey(e.source), target: W.idKey(e.target), original: e}}));
    const direction = data.graph?.directed ? "triangle" : "none";
    state.cy = window.cytoscape({container: $("network"), elements, minZoom: .08, maxZoom: 5, wheelSensitivity: .2, style: [
      {selector: "node", style: {"background-color": "#73a991", "border-color": "#fff", "border-width": 2, width: 25, height: 25, label: "data(label)", "font-size": 10, color: "#284a42", "text-valign": "bottom", "text-margin-y": 5, "text-background-color": "#fdfefb", "text-background-opacity": .8, "text-background-padding": 2}},
      {selector: "edge", style: {width: 1.4, "line-color": "#adc5b9", "target-arrow-color": "#91afa0", "target-arrow-shape": direction, "curve-style": "bezier", opacity: .8}},
      {selector: "node.chosen", style: {"background-color": "#e3a465", "border-color": "#754e28", "border-width": 2}},
      {selector: "node.faded", style: {opacity: .45}},
      {selector: "edge.faded", style: {opacity: .1}},
    ], layout: layoutOptions()});
    state.cy.on("tap", "node", event => {
      state.selected = new Set([event.target.id()]);
      $("selection-detail").textContent = W.stringify(event.target.data("original"), true);
      applySelection();
    });
    state.cy.on("tap", "edge", event => { $("selection-detail").textContent = W.stringify(event.target.data("original"), true); });
    const n = data.vertex_count ?? data.vertices.length, m = data.edge_count ?? data.edges.length;
    state.previewScope = `Preview: ${vertices.length} of ${n} vertices; ${edges.length} of ${m} connections. ${vertices.length < n || edges.length < m || data.vertices_truncated || data.edges_truncated ? "The preview is truncated. " : ""}`;
    renderPreviewScope();
    applySelection();
  }
  function renderPreviewScope() {
    if (!state.graph) return;
    const computed = $("graph-layout").value === "computed" && state.port?.type === "vertex_positions";
    $("preview-scope").textContent = state.previewScope + (state.port?.type === "pattern_collection" ? "Canonical pattern; vertex IDs are local to this pattern. " : "") + (computed ? `Computed coordinates${state.port.value[0]?.coordinates?.length === 3 ? " (XY projection of 3D)" : ""}; display scale is uniform.` : "Layout positions are for display only.");
  }
  function layoutOptions() {
    if ($("graph-layout").value === "computed" && state.port?.type === "vertex_positions") {
      let scale = 1;
      for (const row of state.port.value) scale = Math.max(scale, Math.abs(row.coordinates[0]), Math.abs(row.coordinates[1]));
      const positions = new Map(state.port.value.map(row => [W.idKey(row.vertex), {x: row.coordinates[0] / scale * 200, y: row.coordinates[1] / scale * 200}]));
      return {name: "preset", positions: n => positions.get(n.id()), animate: false, fit: true, padding: 35};
    }
    return {name: $("graph-layout").value, animate: false, randomize: false, fit: true, padding: 35, nodeRepulsion: () => 7000, idealEdgeLength: () => 70};
  }
  function rowVertices(row) {
    if (!state.port) return [];
    if (state.port.type === "pattern_collection") return [];
    if (state.port.type === "vertex_set") return [row];
    if (state.port.type === "edge_ids") {
      const edge = state.graph?.edges?.find(e => W.idKey(e.id) === W.idKey(row));
      return edge ? [edge.source, edge.target] : [];
    }
    if (!row || typeof row !== "object" || Array.isArray(row)) return [];
    if (state.port.vertex_field && row[state.port.vertex_field] !== undefined) return [row[state.port.vertex_field]];
    if (Array.isArray(row.vertices)) return row.vertices;
    if (row.vertex !== undefined) return [row.vertex];
    if (row.source !== undefined && row.target !== undefined) return [row.source, row.target];
    return [];
  }
  function selectRow(row) {
    if (state.port?.type === "pattern_collection") {
      state.patternId = row.pattern_id; state.selected.clear(); renderGraph(row.pattern); applySelection(); return;
    }
    const ids = rowVertices(row); if (!ids.length) return;
    state.selected = new Set(ids.map(W.idKey));
    const visible = ids.filter(id => state.cy?.getElementById(W.idKey(id)).length);
    $("selection-detail").textContent = `${ids.length} selected: ${ids.map(W.idLabel).join(", ")}${visible.length < ids.length ? `\n${ids.length - visible.length} selected entities are outside this graph preview.` : ""}`;
    applySelection();
  }
  function applySelection() {
    if (state.cy) {
      state.cy.nodes().forEach(n => { n.toggleClass("chosen", state.selected.has(n.id())); n.toggleClass("faded", state.selected.size > 0 && !state.selected.has(n.id())); });
      state.cy.edges().forEach(e => e.toggleClass("faded", state.selected.size > 0 && !(state.selected.has(e.source().id()) || state.selected.has(e.target().id()))));
    }
    document.querySelectorAll("[data-result-row]").forEach(el => {
      const row = state.rows[Number(el.dataset.resultRow)], ids = rowVertices(row), active = state.port?.type === "pattern_collection" ? row.pattern_id === state.patternId : ids.length > 0 && ids.every(id => state.selected.has(W.idKey(id)));
      el.setAttribute(el.tagName === "TR" ? "aria-selected" : "aria-pressed", String(active));
    });
  }
  function renderOutput() {
    $("metrics").replaceChildren(); $("chart").replaceChildren();
    if (["scalar", "rational_scalar"].includes(state.port?.type)) {
      const rational = state.port.type === "rational_scalar", value = rational ? state.port.value.display : state.port.value;
      const metric = node("div", {class: "metric"}); metric.append(node("strong", {}, `${rational && !state.port.value.display_is_exact ? "≈ " : ""}${display(value)}`), node("span", {}, $("result-port").selectedOptions[0]?.textContent || "Value"));
      if (rational) metric.append(node("p", {class: "parameter-hint"}, state.port.value.display_is_exact ? "Exact cost. The numerator and denominator are preserved in the output." : "Display rounded. The exact numerator and denominator are preserved below and in the download."));
      $("metrics").append(metric);
    }
    let chartRows = [];
    if (state.port?.type === "vertex_scores") {
      const field = state.port.score_field || "score";
      chartRows = state.rows.map((row, index) => ({index, row, label: W.idLabel(row.vertex), value: row[field]})).filter(x => typeof x.value === "number" || typeof x.value === "bigint");
    } else if (state.port?.type === "vertex_groups") chartRows = state.rows.map((row, index) => ({index, row, label: `Group ${row.group ?? index + 1}`, value: row.vertices.length}));
    if (chartRows.length) {
      chartRows.sort((a, b) => {
        const field = state.port.exact_score_field, x = field && a.row[field], y = field && b.row[field];
        if (x && y) {
          const left = BigInt(x.numerator) * BigInt(y.denominator), right = BigInt(y.numerator) * BigInt(x.denominator);
          return left > right ? -1 : left < right ? 1 : a.index - b.index;
        }
        return a.value > b.value ? -1 : a.value < b.value ? 1 : a.index - b.index;
      });
      const visible = chartRows.slice(0, 20), max = Math.max(...visible.map(r => Math.abs(Number(r.value))), 0);
      $("chart").append(node("p", {class: "chart-heading"}, `${state.port.type === "vertex_groups" ? "Members in each returned group" : title(state.port.score_field || "score")} · highest ${visible.length} of ${chartRows.length} scored rows`));
      if (visible.some(row => row.value < 0)) $("chart").append(node("p", {class: "muted"}, "Bar length shows magnitude; negative values are orange. Labels retain the sign."));
      if (!Number.isFinite(max)) $("chart").append(node("p", {class: "muted"}, "These values exceed the chart range. Exact values remain in the table."));
      else for (const item of visible) {
        const button = node("button", {class: "bar-row", "data-result-row": item.index, "aria-pressed": "false", title: `${item.label}: ${display(item.value)}`});
        const track = node("span", {class: "bar-track", "aria-hidden": "true"}), fill = node("span", {class: "bar-fill"}); fill.style.display = "block"; fill.style.width = `${max ? Math.abs(Number(item.value)) / max * 100 : 0}%`; if (Number(item.value) < 0) fill.style.backgroundColor = "#c27b65"; track.append(fill);
        button.append(node("span", {class: "bar-label"}, item.label), track, node("span", {class: "bar-value"}, `${item.row.rounded ? "≈ " : ""}${display(item.value)}`));
        button.addEventListener("click", () => selectRow(item.row)); $("chart").append(button);
      }
    }
    filterRows();
  }
  function filterRows() {
    const text = $("table-search").value.trim(), query = text.toLocaleLowerCase(), scoped = /^([A-Za-z_][A-Za-z0-9_]*):(.*)$/s.exec(text);
    let expected;
    if (scoped) { try { expected = W.parse(scoped[2].trim()); } catch { expected = scoped[2].trim(); } }
    state.filtered = state.rows.map((_, index) => index).filter(i => {
      if (!query) return true;
      const row = state.rows[i];
      if (scoped) return row && typeof row === "object" && Object.hasOwn(row, scoped[1]) && W.stringify(row[scoped[1]]) === W.stringify(expected);
      return W.stringify(row).toLocaleLowerCase().includes(query);
    });
    state.page = 0; renderTable();
  }
  function renderTable() {
    const head = $("result-table").querySelector("thead"), body = $("result-table").querySelector("tbody"); head.replaceChildren(); body.replaceChildren();
    const indices = state.filtered.slice(state.page * PAGE, (state.page + 1) * PAGE), objectRows = state.rows.some(r => r !== null && typeof r === "object" && !Array.isArray(r));
    const keys = objectRows ? [...new Set(state.rows.flatMap(r => r && typeof r === "object" && !Array.isArray(r) ? Object.keys(r) : ["value"]))] : ["value"];
    const tr = node("tr"); keys.forEach(key => tr.append(node("th", {scope: "col"}, title(key)))); head.append(tr);
    indices.forEach(index => {
      const row = state.rows[index], record = objectRows && row && typeof row === "object" && !Array.isArray(row) ? row : {value: row};
      const tr = node("tr", {"data-result-row": index, "aria-selected": "false"});
      keys.forEach((key, position) => {
        const value = record[key] ?? null, text = state.port?.type === "pattern_collection" && key === "pattern" ? `${record.vertex_count} vertices · ${record.edge_count} connections` : ["vertex", "source", "target", state.port?.vertex_field].includes(key) && value !== null ? W.idLabel(value) : `${key === "value" && record.rounded && record.exact_value ? "≈ " : ""}${display(value)}`, td = node("td", {title: text});
        if (position === 0 && (rowVertices(row).length || state.port?.type === "pattern_collection")) { const button = node("button", {}, state.port?.type === "pattern_collection" ? `View pattern ${index + 1}` : text); button.addEventListener("click", () => selectRow(row)); td.append(button); } else td.textContent = text;
        tr.append(td);
      }); body.append(tr);
    });
    if (!indices.length) { const tr = node("tr"); tr.append(node("td", {colspan: Math.max(1, keys.length)}, state.port ? "No matching output rows." : "Choose an analysis to see computed results.")); body.append(tr); }
    const pages = Math.max(1, Math.ceil(state.filtered.length / PAGE));
    $("table-count").textContent = `${state.filtered.length} of ${state.rows.length} retained rows`;
    $("table-page").textContent = `${state.page + 1} / ${pages}`;
    $("table-prev").disabled = state.page === 0; $("table-next").disabled = state.page + 1 >= pages;
    $("table-scope").textContent = state.port ? `This table pages over the retained output. ${state.port.complete ? "The output collection is complete." : "The output collection is incomplete or count-only."} Search filters this table, not the computation.` : "Computed values will appear after an analysis.";
    if (state.rows.some(row => row?.rounded && row?.exact_value)) $("table-scope").textContent += " Approximate displays use ≈. Exact numerators and denominators are preserved in the table and download.";
    applySelection();
  }
  async function connect() {
    $("connection-state").textContent = "Connecting…";
    [state.caps, state.domains] = await Promise.all([api("/api/analytics/capabilities"), api("/api/domains")]);
    const cpu = state.caps.operations.filter(c => c.execution.cpu).length;
    $("verified-count").textContent = `${cpu} verified calculations`;
    $("connection-state").textContent = cpu ? "Library ready" : "Verification needed";
    $("device").querySelector('[value="gpu"]').disabled = !state.caps.device_configuration?.gpu_configured;
    $("device-note").textContent = state.caps.device_configuration?.gpu_configured ? "Automatic uses the available compute device for each calculation." : "This workspace uses the CPU library.";
    if (!state.caps.question_planner_enabled) $("planner-note").textContent = "Question planning is disabled. You can build a plan in Expert mode.";
    renderDomains(); renderOperations(); await loadSessions();
    // The initial connection runs inside runAction; allow restoring a saved route.
    const match = /^#workspace\/([^/]+)/.exec(location.hash);
    if (match) await openSession(decodeURIComponent(match[1]));
    await applyRoute();
  }
  document.querySelectorAll("[data-mode]").forEach(button => button.addEventListener("click", () => { try { setMode(button.dataset.mode); } catch (error) { notice(error.message, true); } }));
  $("connection-button").addEventListener("click", () => { $("api-base").value = state.base; $("api-token").value = state.token; $("connection-dialog").showModal(); });
  $("close-connection").addEventListener("click", () => $("connection-dialog").close());
  $("connection-form").addEventListener("submit", event => { event.preventDefault(); state.base = $("api-base").value.trim().replace(/\/$/, ""); state.token = $("api-token").value.trim(); save("graphmine.apiBase", state.base); save("graphmine.apiToken", state.token); $("connection-dialog").close(); runAction(connect); });
  $("new-session").addEventListener("click", () => { location.hash = ""; });
  $("refresh-sessions").addEventListener("click", () => runAction(loadSessions));
  $("back-to-chat").addEventListener("click", () => go("chat"));
  $("result-select").addEventListener("change", () => { if ($("result-select").value) go("results", $("result-select").value); });
  window.addEventListener("hashchange", () => { applyRoute().catch(error => notice(error.message, true)); });
  $("session-select").addEventListener("change", () => { location.hash = $("session-select").value ? `#workspace/${encodeURIComponent($("session-select").value)}/chat` : ""; });
  function projectionSettings() {
    const table = $("projection-table").value, source = $("projection-source").value, target = $("projection-target").value;
    if (!table || !source || !target || source === target) throw new Error("Choose a table and two different endpoint columns.");
    const task = $("projection-task").value, weight = $("projection-weight").value;
    const spec = {version: 1, id: "projected-network", task, edge_table: table, joins: [], source: {field: `${table}.${source}`, type: "string"}, target: {field: `${table}.${target}`, type: "string"}, directed: $("projection-directed").checked, duplicates: $("projection-duplicates").value};
    if (weight) spec.weight = {field: `${table}.${weight}`, type: "number", meaning: {shortest_paths: "cost", spanning_tree: "cost", max_flow: "capacity", ranking: "strength", topology: "strength"}[task]};
    return spec;
  }
  function weightNote() {
    $("projection-weight-note").textContent = {topology: "IDs remain text, including leading zeros. If supplied, weights represent connection strength.", shortest_paths: "Weights represent travel cost or length: smaller values mean shorter paths.", spanning_tree: "Weights represent the cost of keeping a connection.", max_flow: "Weights represent nonnegative flow capacity.", ranking: "Weights represent nonnegative connection strength. Counting repeated records can provide this weight."}[$("projection-task").value];
  }
  async function loadTableSchema() {
    const id = state.tableSources?.[$("projection-table").value];
    for (const key of ["projection-source", "projection-target", "projection-weight"]) $(key).replaceChildren(node("option", {value: ""}, key === "projection-weight" ? "No weight" : "Choose a column"));
    if (!id) return;
    const schema = await api(`/api/sessions/${state.session.id}/tables/${id}/schema`);
    for (const column of schema.columns) for (const key of ["projection-source", "projection-target", "projection-weight"]) $(key).append(node("option", {value: column.name}, column.name));
    $("projection-feedback").textContent = `${schema.row_count} records. Empty join keys do not match. Numeric conversions and duplicate handling are explicit.`;
    weightNote();
  }
  async function refreshTables() {
    state.tableSources = {};
    $("projection-table").replaceChildren();
    state.files.filter(isTable).forEach((file, i) => { const alias = `table_${i + 1}`; state.tableSources[alias] = file.id; $("projection-table").append(node("option", {value: alias}, `${alias} · ${file.original_name}`)); });
    $("table-aliases").textContent = state.files.filter(isTable).map((file, i) => `table_${i + 1}: ${file.original_name}`).join(" · ") || "Add one or more CSV tables to begin.";
    await loadTableSchema();
  }
  function projectionAction(action) { return runAction(async () => { try { await action(); } catch (error) { $("projection-feedback").textContent = error.message; } }); }
  document.querySelectorAll("[data-close]").forEach(button => button.addEventListener("click", () => $(button.dataset.close).close()));
  $("open-projection").addEventListener("click", () => projectionAction(async () => { await ensureSession(); $("projection-dialog").showModal(); await refreshTables(); }));
  $("table-upload").addEventListener("change", () => projectionAction(async () => {
    for (const file of $("table-upload").files) { const body = new FormData(); body.append("file", file); body.append("role", "attachment"); state.files.push(await api(`/api/sessions/${state.session.id}/files`, {method: "POST", body})); }
    $("table-upload").value = ""; renderFiles(); await refreshTables();
  }));
  $("projection-table").addEventListener("change", () => projectionAction(loadTableSchema));
  $("projection-task").addEventListener("change", weightNote);
  $("projection-template").addEventListener("click", () => projectionAction(async () => { $("projection-editor").value = W.stringify(projectionSettings(), true); $("projection-advanced").checked = true; }));
  $("projection-form").addEventListener("submit", event => { event.preventDefault(); projectionAction(async () => {
    const projection = $("projection-advanced").checked ? W.parse($("projection-editor").value) : projectionSettings();
    $("projection-feedback").textContent = "Building your graph…";
    const result = await api(`/api/sessions/${state.session.id}/projections`, {method: "POST", body: W.stringify({tables: state.tableSources, projection})});
    state.files.push(result.file); state.kinds[result.file.id] = "graph"; state.active = result.file.id; clearResults(); renderFiles(); await previewActive();
    $("projection-dialog").close(); notice(`Graph ready: ${result.provenance.retained_rows} source records produced ${result.provenance.edge_count} connections. Construction settings are saved with the graph.`);
  }); });
  $("review-example").addEventListener("click", () => runAction(async () => {
    state.exampleReview = await api(`/api/workflows/${state.record.id}/example-review`);
    $("example-question").value = [...state.events].reverse().find(event => event.type === "workflow.chat" && event.payload.turn_id === state.record.planning_turn_id && event.payload.role === "user")?.payload.message || ""; $("example-approved").checked = false; $("example-feedback").textContent = ""; $("example-dialog").showModal();
  }));
  $("example-form").addEventListener("submit", event => { event.preventDefault(); runAction(async () => {
    try {
      const review = state.exampleReview;
      await api(`/api/workflows/${review.workflow_id}/example-review`, {method: "POST", body: W.stringify({question: $("example-question").value, approved: $("example-approved").checked, expected_revision: review.expected_revision, workflow_hash: review.workflow_hash, result_sha256: review.result_sha256})});
      $("example-dialog").close(); notice("Approved example saved for this workspace. Evaluation cases never use reviewed examples.");
    } catch (error) { $("example-feedback").textContent = error.message; }
  }); });
  $("data-upload").addEventListener("change", () => { const file = $("data-upload").files[0]; if (file) runAction(async () => { await upload(file); $("data-upload").value = ""; }); });
  $("sample-data").addEventListener("click", () => runAction(async () => {
    const ids = ["Alice", "Bob", "Carol", "Dara", "Eli", "Fatima", "Gus"];
    const pairs = [[0,1],[1,2],[0,2],[2,3],[3,4],[4,5],[5,6],[4,6]];
    const graph = {graph: {id: "example-team", directed: false, allows_self_loops: false, allows_parallel_edges: false}, vertices: ids.map(id => ({id, label: id})), edges: pairs.map(([a,b], id) => ({id, source: ids[a], target: ids[b]}))};
    await upload(new File([W.stringify(graph)], "example-team.json", {type: "application/json"}), "graph");
  }));
  $("active-input").addEventListener("change", () => runAction(async () => { state.active = $("active-input").value; renderFiles(); await previewActive(); }));
  $("active-kind").addEventListener("change", () => runAction(async () => { state.kinds[state.active] = $("active-kind").value; renderFiles(); await previewActive(); }));
  $("device").addEventListener("change", () => { if (state.operation && !capable(card(state.operation))) state.operation = ""; renderOperations(); });
  $("operation-select").addEventListener("change", () => { state.operation = $("operation-select").value; renderParameters(); });
  $("operation-form").addEventListener("submit", event => { event.preventDefault(); runAction(() => submitPlan(planFromOperation())); });
  $("question-form").addEventListener("submit", askQuestion);
  $("question").addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (!state.busy) $("question-form").requestSubmit(); } });
  $("load-editor").addEventListener("click", () => { try { loadEditor(); } catch (error) { notice(error.message, true); } });
  $("edit-plan").addEventListener("click", () => { setMode("expert"); loadEditor(); $("expert-panel").scrollIntoView({block: "start", behavior: "smooth"}); $("plan-editor").focus(); });
  $("save-editor").addEventListener("click", () => runAction(() => submitPlan(W.parse($("plan-editor").value), Boolean(state.record))));
  $("approve-plan").addEventListener("click", () => runAction(async () => { const record = state.record; state.record = await api(`/api/workflows/${record.id}/run`, {method: "POST", body: W.stringify({workflow_hash: record.validation.workflow_hash, expected_revision: record.revision})}); clearResults(); renderWorkflow(); pollWorkflow(); }));
  $("cancel-workflow").addEventListener("click", async () => { try { clearTimeout(state.poll); state.epoch++; state.record = await api(`/api/workflows/${state.record.id}`, {method: "DELETE"}); renderWorkflow(); await loadSaved(); await loadResults(); notice("Execution cancelled. Completed step artifacts remain saved."); } catch (error) { notice(error.message, true); } });
  $("result-step").addEventListener("change", () => runAction(selectStep)); $("result-port").addEventListener("change", () => runAction(selectPort));
  $("graph-layout").addEventListener("change", () => { state.cy?.layout(layoutOptions()).run(); renderPreviewScope(); }); $("fit-graph").addEventListener("click", () => state.cy?.fit(undefined, 35));
  $("clear-selection").addEventListener("click", () => { state.selected.clear(); $("selection-detail").textContent = "Selection cleared."; applySelection(); });
  $("table-search").addEventListener("input", filterRows);
  $("table-prev").addEventListener("click", () => { state.page--; renderTable(); }); $("table-next").addEventListener("click", () => { state.page++; renderTable(); });
  $("download-result").addEventListener("click", () => { if (!state.result) return; const url = URL.createObjectURL(new Blob([W.stringify(state.result, true)], {type: "application/json"})), a = node("a", {href: url, download: `graphmine-${state.record.id}-revision-${state.record.revision}.json`}); a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); });
  new ResizeObserver(() => { if (state.view === "results") { state.cy?.resize(); state.cy?.fit(undefined, 35); } }).observe($("network"));
  window.GraphMineWorkspace = {state, wire: W};
  setMode("normal"); renderOutput(); runAction(connect);
})();
