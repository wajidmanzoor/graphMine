(() => {
  "use strict";
  const W = window.AnalyticsWire, $ = id => document.getElementById(id);
  const read = key => { try { return localStorage.getItem(key) || ""; } catch { return ""; } };
  const save = (key, value) => { try { localStorage.setItem(key, value); } catch { /* private browsing */ } };
  const state = {base: read("graphmine.apiBase"), token: read("graphmine.apiToken"), caps: null, session: null, files: [], kinds: {}, active: "", mode: "normal", family: "", operation: "", record: null, result: null, cy: null, graph: null, selected: new Set(), port: null, rows: [], filtered: [], page: 0, previews: new Map(), poll: null, epoch: 0, busy: false};
  const PAGE = 30;
  const descriptions = {normal: "Describe your question or choose a task. Validated plans run automatically.", interactive: "Review the calculation, inputs and settings before you approve execution.", expert: "Build an explicit workflow from registered operations and typed outputs."};
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
  function notice(message, error = false) { $("notice").textContent = message; $("notice").className = `notice${error ? " error" : ""}`; $("notice").hidden = !message; }
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
  function methodName(id) { return card(id)?.title || id; }
  function capable(c) { return c.execution[$("device").value === "gpu" ? "gpu" : "cpu"]; }
  function setMode(mode) {
    state.mode = mode;
    document.querySelectorAll("[data-mode]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.mode === mode)));
    $("mode-description").textContent = descriptions[mode];
    $("expert-panel").hidden = mode !== "expert";
    $("use-operation").textContent = mode === "normal" ? "Run this analysis" : "Build a plan to review";
    if (mode === "expert" && !$("plan-editor").value) loadEditor();
  }
  async function runAction(fn) {
    if (state.busy) return;
    state.busy = true;
    const controls = ["plan-question", "use-operation", "save-editor", "sample-data", "data-upload"];
    controls.forEach(id => $(id).disabled = true);
    try { await fn(); } catch (error) { notice(error.message, true); }
    finally { state.busy = false; controls.forEach(id => $(id).disabled = false); }
  }
  async function loadSessions() {
    const sessions = await api("/api/sessions?limit=100");
    const selected = state.session?.id || "";
    $("session-select").replaceChildren(node("option", {value: ""}, "New analysis"));
    sessions.forEach(session => $("session-select").append(node("option", {value: session.id}, session.title || "Untitled analysis")));
    $("session-select").value = selected;
  }
  async function ensureSession() {
    if (!state.session) {
      state.session = await api("/api/sessions", {method: "POST", body: W.stringify({domain_id: "general", title: $("session-name").value.trim() || "Network analysis"})});
      await loadSessions();
      history.replaceState(null, "", `#workspace/${encodeURIComponent(state.session.id)}`);
    }
    return state.session;
  }
  async function openSession(id) {
    clearTimeout(state.poll); state.epoch++;
    state.session = null; state.files = []; state.kinds = {}; state.active = ""; state.record = null; state.previews.clear();
    $("workflow-panel").hidden = true; $("result-controls").hidden = true; $("download-result").disabled = true; $("raw-details").hidden = true; $("raw-result").textContent = ""; $("routing-trace").replaceChildren();
    $("plan-editor").value = "";
    notice(""); clearResults("Upload a graph to preview its connections.");
    if (id) {
      state.session = await api(`/api/sessions/${encodeURIComponent(id)}`);
      $("session-name").value = state.session.title || "";
      state.files = await api(`/api/sessions/${encodeURIComponent(id)}/files`);
      state.files = state.files.filter(f => ["graph", "query_graph", "motif", "attachment"].includes(f.role));
      try { state.kinds = W.parse(read(`graphmine.inputKinds.${id}`) || "{}"); } catch { state.kinds = {}; }
      for (const f of state.files) if (f.role !== "attachment") state.kinds[f.id] = "graph";
      state.active = state.files[0]?.id || "";
      history.replaceState(null, "", `#workspace/${encodeURIComponent(id)}`);
    } else { $("session-name").value = ""; history.replaceState(null, "", location.pathname); }
    renderFiles(); await loadSaved(); if (state.active) await previewActive();
  }
  function renderFiles() {
    $("active-input").replaceChildren(node("option", {value: ""}, "Choose an input"));
    state.files.forEach(f => $("active-input").append(node("option", {value: f.id}, f.original_name)));
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
    renderFiles(); await previewActive(); notice("Your data is ready. Choose a task or describe your question.");
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
  function renderFamilies() {
    $("family-cards").replaceChildren();
    for (const family of state.caps.task_families) {
      const choices = family.operations.filter(id => capable(card(id)));
      if (!choices.length) continue;
      const button = node("button", {class: "family-card", "data-family": family.id, "aria-pressed": String(state.family === family.id)});
      button.append(node("strong", {}, family.title), node("small", {}, `${choices.length} available calculations`));
      button.title = family.description;
      button.addEventListener("click", () => { state.family = family.id; state.operation = ""; renderFamilies(); renderOperations(); });
      $("family-cards").append(button);
    }
  }
  function renderOperations() {
    const family = state.caps.task_families.find(f => f.id === state.family);
    $("operation-panel").hidden = !family;
    if (!family) return;
    $("operation-select").replaceChildren(node("option", {value: ""}, "Choose a specific calculation"));
    family.operations.map(card).filter(capable).forEach(c => $("operation-select").append(node("option", {value: c.id}, c.title)));
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
    $("operation-quality").textContent = selected ? `Input: ${title(selected.input_kind)} · Method profile: ${title(selected.quality)} · ${selected.library}` : "";
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
    if (!selected) throw new Error("Choose a task family and a calculation first.");
    if (!activeFile()) throw new Error("Upload or choose an input first.");
    if (state.kinds[state.active] !== selected.input_kind) throw new Error(`This calculation needs ${title(selected.input_kind)} input. Choose the matching uploaded data.`);
    return {version: 1, device: $("device").value, steps: [{id: "analysis", operation: selected.id, input: {input: "main"}, parameters: parametersFrom($("operation-parameters"), selected), bindings: bindingsFrom($("operation-parameters"))}]};
  }
  function loadEditor() {
    const plan = state.record?.validation.plan || (state.operation ? planFromOperation() : {version: 1, device: $("device").value, steps: [{id: "groups", operation: "connected-components", input: {input: "main"}, parameters: {}}]});
    $("plan-editor").value = W.stringify(plan, true);
  }
  async function submitPlan(plan, revise = false) {
    await ensureSession();
    if (!state.active) throw new Error("Choose an input before saving the plan.");
    const body = {mode: state.mode, plan, inputs: revise && state.record ? state.record.input_files : refs()};
    let path = `/api/sessions/${state.session.id}/workflows`;
    if (revise && state.record) { path = `/api/workflows/${state.record.id}/revise`; body.expected_revision = state.record.revision; }
    const result = await api(path, {method: "POST", body: W.stringify(body)});
    state.record = result; clearResults(result.status === "queued" ? "The calculation is queued; no new result has been produced." : "This plan is awaiting execution; no new result has been produced."); renderWorkflow(); await loadSaved();
    $("workflow-panel").scrollIntoView({behavior: "smooth", block: "nearest"});
    notice(result.status === "queued" ? "The validated workflow is queued." : "Your plan is ready to review. Execution has not started.");
    if (["queued", "running"].includes(result.status)) pollWorkflow();
  }
  async function askQuestion(event) {
    event.preventDefault();
    await runAction(async () => {
      if (!$("question").value.trim()) throw new Error("Describe what you want to learn, or choose a task family.");
      if (!state.active) throw new Error("Upload or choose an input first.");
      await ensureSession(); notice("Choosing a task family, then checking the specific calculation…");
      const response = await api(`/api/sessions/${state.session.id}/analytics/plan`, {method: "POST", body: W.stringify({message: $("question").value, inputs: refs(), device: $("device").value, previous_workflow_id: state.record?.id || null})});
      $("routing-trace").replaceChildren();
      for (const decision of response.trace || []) {
        const values = decision.families || decision.operations || [decision.status];
        $("routing-trace").append(node("span", {}, `${title(decision.stage)}: ${values.map(id => state.caps.task_families.find(f => f.id === id)?.title || card(id)?.title || id).join(", ")}`));
      }
      if (response.status !== "ready" || !response.plan) { notice(response.message); return; }
      $("plan-editor").value = W.stringify(response.plan, true);
      await submitPlan(response.plan);
    });
  }
  async function loadSaved() {
    $("saved-workflows").replaceChildren();
    if (!state.session) { $("saved-workflows").append(node("p", {class: "muted"}, "Your workflows will appear here.")); return; }
    const records = await api(`/api/sessions/${state.session.id}/workflows`);
    for (const record of records.slice().reverse()) {
      const button = node("button", {"data-workflow": record.id, "aria-current": String(record.id === state.record?.id)}, record.validation.plan.steps.map(step => methodName(step.operation)).join(" → "));
      button.append(node("small", {}, `${title(record.status)} · revision ${record.revision}`));
      button.addEventListener("click", () => runAction(() => openWorkflow(record.id)));
      $("saved-workflows").append(button);
    }
  }
  function renderWorkflow() {
    const record = state.record; if (!record) return;
    $("workflow-panel").hidden = false;
    $("workflow-status").textContent = title(record.status);
    $("workflow-summary").textContent = `Revision ${record.revision} · ${title(record.mode)} mode · ${record.validation.plan.device === "auto" ? "Automatic device choice" : record.validation.plan.device.toUpperCase() + " only"}. ${record.error?.message || ""}`;
    $("plan-details").textContent = W.stringify({plan: record.validation.plan, input_fingerprints: record.validation.inputs, workflow_hash: record.validation.workflow_hash, approved_hash: record.approved_hash}, true);
    $("workflow-steps").replaceChildren();
    for (const id of record.validation.order) {
      const step = record.validation.plan.steps.find(s => s.id === id), status = record.steps[id]?.status || "pending";
      const li = node("li", {class: "workflow-step", "data-step": id, "data-status": status});
      li.append(node("span", {class: "step-state"}, status));
      const button = node("button", {}, methodName(step.operation));
      button.addEventListener("click", () => { if (state.result?.steps[id]?.result) { $("result-step").value = id; selectStep(); } });
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
        state.record = record; renderWorkflow();
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
    $("result-port").value = Object.entries(step.ports).find(([,p]) => p.type === "vertex_scores")?.[0] || Object.keys(step.ports)[0] || "__result";
    await selectPort();
  }
  async function selectPort() {
    const stepId = $("result-step").value, result = state.result?.steps[stepId]?.result;
    if (!result) return;
    const name = $("result-port").value;
    state.port = name === "__result" ? {type: "result", complete: result.complete, value: result.result} : result.ports[name];
    const port = state.port; state.rows = Array.isArray(port.value) ? port.value : [port.value]; state.page = 0; state.selected.clear(); $("table-search").value = "";
    $("result-completeness").classList.toggle("incomplete", !port.complete || !result.complete);
    $("result-completeness").textContent = `${port.complete ? "This output collection is complete." : "This output is incomplete or count-only; it cannot supply a full downstream collection."} Method quality: ${title(result.quality)}. Computed by ${result.backend.library} on ${result.backend.device.toUpperCase()}.`;
    if (!port.complete && result.diagnostics?.narrowing_hint) $("result-completeness").textContent += ` ${result.diagnostics.narrowing_hint}`;
    state.patternId = port.type === "pattern_collection" ? port.value[0]?.pattern_id || null : null;
    const graph = port.type === "graph" ? port.value : port.type === "pattern_collection" ? port.value[0]?.pattern || null : await graphForStep(stepId);
    if (port.type === "vertex_positions") $("graph-layout").value = "computed";
    renderGraph(graph); renderOutput();
  }
  function renderGraph(data) {
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
    const query = $("table-search").value.trim().toLocaleLowerCase();
    state.filtered = state.rows.map((_, index) => index).filter(i => !query || W.stringify(state.rows[i]).toLocaleLowerCase().includes(query));
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
    state.caps = await api("/api/analytics/capabilities");
    const cpu = state.caps.operations.filter(c => c.execution.cpu).length;
    $("verified-count").textContent = `${cpu} verified CPU calculations`;
    $("connection-state").textContent = cpu ? "Library ready" : "Verification needed";
    $("device").querySelector('[value="gpu"]').disabled = !state.caps.device_configuration?.gpu_configured;
    $("device-note").textContent = state.caps.device_configuration?.gpu_configured ? "GPU uses the configured compute device. Each calculation still checks its supported parameters." : "No compute GPU is configured. Automatic and CPU-only use the CPU library.";
    if (!state.caps.question_planner_enabled) $("planner-note").textContent = "The question planner is disabled here. You can choose a task below.";
    renderFamilies(); await loadSessions();
    const match = /^#workspace\/([^/]+)$/.exec(location.hash);
    if (match) await openSession(decodeURIComponent(match[1]));
    else renderFiles();
  }
  document.querySelectorAll("[data-mode]").forEach(button => button.addEventListener("click", () => { try { setMode(button.dataset.mode); } catch (error) { notice(error.message, true); } }));
  $("connection-button").addEventListener("click", () => { $("api-base").value = state.base; $("api-token").value = state.token; $("connection-dialog").showModal(); });
  $("close-connection").addEventListener("click", () => $("connection-dialog").close());
  $("connection-form").addEventListener("submit", event => { event.preventDefault(); state.base = $("api-base").value.trim().replace(/\/$/, ""); state.token = $("api-token").value.trim(); save("graphmine.apiBase", state.base); save("graphmine.apiToken", state.token); $("connection-dialog").close(); runAction(connect); });
  $("new-session").addEventListener("click", () => runAction(() => openSession("")));
  $("session-select").addEventListener("change", () => runAction(() => openSession($("session-select").value)));
  $("data-upload").addEventListener("change", () => { const file = $("data-upload").files[0]; if (file) runAction(async () => { await upload(file); $("data-upload").value = ""; }); });
  $("sample-data").addEventListener("click", () => runAction(async () => {
    const ids = ["Alice", "Bob", "Carol", "Dara", "Eli", "Fatima", "Gus"];
    const pairs = [[0,1],[1,2],[0,2],[2,3],[3,4],[4,5],[5,6],[4,6]];
    const graph = {graph: {id: "example-team", directed: false, allows_self_loops: false, allows_parallel_edges: false}, vertices: ids.map(id => ({id, label: id})), edges: pairs.map(([a,b], id) => ({id, source: ids[a], target: ids[b]}))};
    await upload(new File([W.stringify(graph)], "example-team.json", {type: "application/json"}), "graph");
  }));
  $("active-input").addEventListener("change", () => runAction(async () => { state.active = $("active-input").value; renderFiles(); await previewActive(); }));
  $("active-kind").addEventListener("change", () => runAction(async () => { state.kinds[state.active] = $("active-kind").value; renderFiles(); await previewActive(); }));
  $("device").addEventListener("change", () => { if (state.operation && !capable(card(state.operation))) state.operation = ""; renderFamilies(); renderOperations(); });
  $("operation-select").addEventListener("change", () => { state.operation = $("operation-select").value; renderParameters(); });
  $("toggle-tasks").addEventListener("click", () => { $("task-picker").hidden = !$("task-picker").hidden; $("toggle-tasks").setAttribute("aria-expanded", String(!$("task-picker").hidden)); });
  $("operation-form").addEventListener("submit", event => { event.preventDefault(); runAction(() => submitPlan(planFromOperation())); });
  $("question-form").addEventListener("submit", askQuestion);
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
  new ResizeObserver(() => { state.cy?.resize(); state.cy?.fit(undefined, 35); }).observe($("network"));
  window.GraphMineWorkspace = {state, wire: W};
  setMode("normal"); renderOutput(); runAction(connect);
})();
