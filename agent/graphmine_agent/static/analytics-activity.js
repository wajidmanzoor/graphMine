/* One stable timeline row per question and stage, built from recorded evidence. */
"use strict";
window.GraphMineActivitySteps = (events, {record = null, answer = null, pending = false} = {}) => {
  const rows = new Map(), calls = window.GraphMineModelCalls(events);
  const terminal = events.some(event => event.type === "workflow.chat" && event.payload.role === "assistant");
  const get = stage => { if (!rows.has(stage)) rows.set(stage, {stage, events: [], calls: [], status: "running"}); return rows.get(stage); };
  for (const event of events) {
    const payload = event.payload || {};
    if (event.type === "workflow.planning") { const row = get(payload.stage); row.events.push(payload); row.status = payload.status || row.status; }
    else if (["workflow.model_call", "workflow.reasoning", "workflow.reasoning.delta", "workflow.diagnostics"].includes(event.type)) get(payload.stage);
  }
  for (const call of calls) get(call.stage).calls.push(call);
  const reply = events.findLast(event => event.type === "workflow.chat" && event.payload.role === "assistant")?.payload;
  if (reply?.status === "needs_information" || reply?.pending_question) get("clarify").question = reply;
  if (record) { const row = get("calculation"); row.record = record; row.status = record.status; }
  if (answer?.sources?.length || answer?.web_search?.search_url) get("sources").status = "completed";
  if (answer?.grounding) { const row = get("grounding"); row.status = answer.grounding.checked ? "passed" : "failed"; }
  for (const row of rows.values()) {
    const last = row.events.at(-1);
    if (row.stage === "calculation") row.state = ["queued", "running"].includes(row.status) ? "running" : row.status === "completed" && record.complete !== false ? "done" : ["ready", "awaiting_review"].includes(row.status) ? "waiting" : "failed";
    else if (["failed", "error", "rejected", "cancelled", "interrupted"].includes(row.status)) row.state = "failed";
    else if (row.status === "waking" && !terminal) row.state = "running";
    else if (!["running", "waking"].includes(row.status)) row.state = "done";
    else if (row.calls.length && row.calls.every(call => !call.running)) row.state = row.calls.at(-1).outcome && row.calls.at(-1).outcome !== "ok" ? "failed" : "done";
    else if (row.stage === "clarify" && row.question) row.state = "done";
    else row.state = terminal && !(row.stage === "answer" && answer?.pending) || !pending && !answer?.pending ? "incomplete" : "running";
    row.latest = last || {};
  }
  return [...rows.values()];
};
window.GraphMineActivity = ({state, api, node, W, methodName, qualityDescriptions, plannedQuality, formatAnswer, route, notice, onChange}) => {
  const turns = new Map(), savedResults = new Map(), requests = new Map();
  const resultKey = record => `${record.id}:${record.revision}`;
  async function loadResult(record) {
    const key = resultKey(record);
    if (savedResults.has(key) || requests.has(key)) return;
    const session = state.session?.id;
    const request = api(`/api/workflows/${encodeURIComponent(record.id)}/result?summary=true&expected_revision=${record.revision}`);
    requests.set(key, request);
    try { const result = await request; if (state.session?.id === session) { savedResults.set(key, result); onChange(); } }
    catch (error) { notice(`Calculation details could not be loaded. ${error.message}`, true); }
    finally { requests.delete(key); }
  }
  const stageNames = {family: "Family", topic: "Topic", route: "Route", candidates: "Candidates", clarify: "Clarify", plan: "Plan", validation: "Validation", calculation: "Calculation", answer: "Answer", grounding: "Grounding", sources: "Sources"};
  const statusNames = {reply: "Documentation answer", answered: "Answered", calculate: "Use the selected calculation", needs_information: "Needs clarification", options: "Choose a calculation", ready: "Ready for review", awaiting_review: "Ready for review", selected: "Selected", passed: "Passed", completed: "Complete", running: "Running", waking: "Waking the model…", failed: "Failed"};
  const title = value => String(value || "").replaceAll("_", " ").replace(/^./, c => c.toUpperCase());
  const pretty = value => typeof value === "string" ? value : W.stringify(value, true);
  function copyId(value) {
    const button = node("button", {class: "quiet copy-id", type: "button", "aria-label": "Copy ID", title: "Copy ID"}, "⧉");
    button.onclick = async () => { try { await navigator.clipboard.writeText(String(value)); button.title = "Copied"; } catch { notice("Could not copy the ID.", true); } };
    return button;
  }
  function clean(text, answer) {
    const sources = new Map((answer?.sources || []).map(source => [source.id, source.title]));
    return String(text || "").replace(/\{\{([^{}]+)\}\}/g, (_, key) => sources.get(key) || "").replace(/workflow:[^\s<>]+/g, "Recorded result");
  }
  const md = (text, answer) => window.GraphMineMarkdown(clean(text, answer), node);
  function fields(parent, values) {
    const dl = node("dl", {class: "activity-facts"});
    for (const [label, value] of values) if (value !== undefined && value !== null && value !== "") dl.append(node("dt", {}, label), node("dd", {}, pretty(value)));
    if (dl.children.length) parent.append(dl);
  }
  const problem = id => state.caps?.problems?.find(row => row.id === id);
  const family = id => (state.caps?.task_families || state.caps?.families || []).find(row => row.id === id)?.title || title(id);
  const topic = id => state.caps?.problems?.find(row => row.topic_id === id)?.topic_title || title(id);
  function sourceContent(parent, answer) {
    parent.append(node("h4", {}, "Sources"));
    for (const source of answer?.sources || []) {
      const section = node("section", {class: "activity-source", "data-source": source.id});
      section.append(node("strong", {}, source.title || "Recorded source"), copyId(source.ref || source.id));
      if (/^https?:\/\//i.test(source.ref || "")) section.append(node("a", {href: source.ref, target: "_blank", rel: "noopener noreferrer"}, source.ref));
      else if (source.ref && !source.ref.startsWith("workflow:")) section.append(node("small", {class: "source-ref"}, source.ref));
      section.append(md(source.text || source.statement, answer));
      if (source.provenance) section.append(node("small", {class: "source-provenance"}, clean(source.provenance, answer)));
      parent.append(section);
    }
    if (/^https:\/\//.test(answer?.web_search?.search_url || "")) parent.append(node("a", {href: answer.web_search.search_url, target: "_blank", rel: "noopener noreferrer"}, "Open this search in Google"));
  }
  function calculation(parent, record, answer) {
    const elapsed = Date.parse(record.finished_at) - Date.parse(record.started_at);
    for (const step of record.validation?.plan?.steps || []) {
      const result = record.steps?.[step.id] || {}, card = problem(step.problem);
      const output = savedResults.get(resultKey(record))?.steps?.[step.id]?.result || (state.record?.id === record.id ? state.result?.steps?.[step.id]?.result : null);
      const backend = output?.backend || result.backend || {};
      const device = backend.device?.toUpperCase() || ((step.device || record.validation.plan.device) === "auto" ? "Automatic (GPU first)" : (step.device || record.validation.plan.device)?.toUpperCase());
      const section = node("section", {class: "activity-calculation"});
      section.append(node("h4", {}, methodName(step.problem)), copyId(`${record.id}:${step.id}`));
      fields(section, [["Family", family(card?.family)], ["Topic", card?.topic_title || title(card?.topic_id)], ["Problem", step.problem],
        ["Algorithm", backend.algorithm || backend.algorithm_id || output?.diagnostics?.solver || (backend.id ? `${backend.id} · ${step.problem}` : "Not recorded")],
        ["Parameters", Object.keys(output?.parameters || step.parameters || {}).length ? output?.parameters || step.parameters : "Defaults"],
        ["Device", device], ["Device selection", backend.selection_reason || backend.fallback_reason],
        ["Calculation time", output?.elapsed_seconds != null ? `${output.elapsed_seconds.toLocaleString(undefined, {maximumFractionDigits: 6})} s` : null],
        ["Runtime", Number.isFinite(elapsed) && elapsed >= 0 ? `${(elapsed / 1000).toLocaleString(undefined, {maximumFractionDigits: 3})} s` : null],
        ["Guarantee", result.quality ? qualityDescriptions[result.quality] || title(result.quality) : plannedQuality(card, step.parameters, step.bindings)]]);
      if (output?.ports) {
        const counts = Object.entries(output.ports).map(([name, port]) => [title(name), port.type === "scalar" ? port.value : port.total_count ?? port.row_count ?? (Array.isArray(port.value) ? port.value.length : null)]);
        if (counts.some(([, count]) => count != null)) { section.append(node("h4", {}, "Result counts")); fields(section, counts); }
      }
      if (Object.keys(step.bindings || {}).length) fields(section, [["Input bindings", step.bindings]]);
      parent.append(section);
    }
    parent.append(node("h4", {}, "Input snapshot"));
    const used = new Set();
    const collectInputs = value => {
      if (!value || typeof value !== "object") return;
      if (typeof value.input === "string") used.add(value.input);
      for (const nested of Object.values(value)) collectInputs(nested);
    };
    collectInputs(record.validation?.plan?.steps);
    for (const [alias, input] of Object.entries(record.input_files || {})) {
      if (used.size && !used.has(alias)) continue;
      const provenance = record.input_provenance?.[alias] || {}, file = state.files.find(file => file.id === input.file_id);
      let origin = provenance;
      const lineage = [], visited = new Set();
      while (origin.source_file_id && !visited.has(origin.source_file_id)) {
        visited.add(origin.source_file_id);
        if (origin.choice?.label) lineage.unshift(origin.choice.label);
        const previous = Object.values(record.input_provenance || {}).find(item => item.file_id === origin.source_file_id);
        if (!previous) break;
        origin = previous;
      }
      const snapshot = provenance.file_snapshot || {}, source = origin.source || file?.provenance?.source || {}, graph = snapshot.graph || file?.metadata || {};
      const item = node("section", {class: "activity-snapshot"});
      fields(item, [["Name", snapshot.name || file?.original_name || "Saved input"], ["Version", provenance.version || (origin.version ? `Derived from version ${origin.version}` : file?.provenance?.version || "Not recorded")],
        ["Vertices", graph.vertex_count], ["Edges", graph.edge_count], ["Saved", snapshot.created_at || file?.created_at || source.fetched_at ? new Date(snapshot.created_at || file?.created_at || source.fetched_at).toLocaleString() : null]]);
      if (lineage.length) { const preparations = node("details"); preparations.append(node("summary", {}, "Input preparation")); for (const label of lineage) preparations.append(node("p", {}, label)); item.append(preparations); }
      if (source.query) { const query = node("details"); query.append(node("summary", {}, "Cypher query"), node("pre", {}, source.query)); item.append(query); }
      item.append(copyId(input.file_id)); parent.append(item);
    }
    parent.append(node("h4", {}, "Validation checks"));
    const checks = node("ul", {class: "activity-checks"});
    checks.append(node("li", {}, `${record.validation?.workflow_hash ? "✓" : "—"} Plan and input validation${record.validation?.workflow_hash ? " passed" : " not recorded"}`));
    checks.append(node("li", {}, record.approved_hash ? (record.approved_hash === record.validation?.workflow_hash ? "✓ Approved plan matches saved validation" : "✗ Approved plan does not match saved validation") : "— Plan approval not recorded"));
    for (const step of record.validation?.plan?.steps || []) {
      const result = record.steps?.[step.id] || {};
      checks.append(node("li", {}, `${result.status === "completed" ? "✓" : result.status === "failed" ? "✗" : "—"} ${methodName(step.problem)}: ${result.status || "pending"}${result.complete === false ? " · incomplete output" : ""}`));
      if (result.error?.message) checks.append(node("li", {}, result.error.message));
    }
    parent.append(checks);
    if (answer?.facts?.length) { parent.append(node("h4", {}, "Findings")); for (const fact of answer.facts) parent.append(md(fact.text || fact.statement, answer)); }
    if (record.status === "completed" || Object.values(record.steps || {}).some(step => step.status === "completed")) parent.append(node("a", {href: route("results", record.id), class: "result-link"}, "View results →"));
  }
  function summary(row, answer) {
    const data = row.latest, name = stageNames[row.stage] || title(row.stage);
    let value = row.stage === "family" ? family(data.family_id) : row.stage === "topic" ? (data.candidates || []).map(item => topic(item.topic_id)).join(", ") : "";
    if (row.stage === "calculation") value = row.record.validation.plan.steps.map(step => methodName(step.problem)).join(" → ");
    else if (row.stage === "sources") value = (answer?.sources || []).map(source => source.title).filter(Boolean).join(", ");
    else if (!value) value = statusNames[data.status || row.status] || title(data.status || row.status);
    if (row.state === "incomplete") value = "Not completed";
    return `${name}${value && value !== name ? " → " + value : ""}`;
  }
  function content(row, answer, question, events, allQuestions, record) {
    const body = node("div", {class: "activity-step-content"});
    for (const [index, call] of row.calls.entries()) {
      const section = node("section", {class: "activity-model-call", "data-call": call.key});
      if (row.calls.length > 1) section.append(node("h4", {}, `Attempt ${index + 1}`));
      if (call.text) section.append(md(call.text, answer));
      else section.append(node("p", {class: "muted"}, call.running && row.state === "running" ? "Waiting for reasoning…" : "No reasoning was recorded for this call."));
      fields(section, [["Model", call.model], ["Latency", call.seconds != null ? `${call.seconds.toLocaleString()} s` : null], ["Samples", call.samples > 1 ? call.samples : null]]);
      body.append(section);
    }
    const data = row.latest;
    if (row.stage === "calculation") calculation(body, row.record, answer);
    else if (row.stage === "sources") sourceContent(body, answer);
    else if (row.stage === "grounding") {
      body.append(node("p", {class: "grounding-status"}, answer?.grounding?.checked || row.status === "passed" ? "✓ Answer checked against recorded evidence" : "✗ Answer verification did not pass"));
      const sources = answer?.sources || [], sentences = String(answer?.text || answer?.lead || "").split(/\n+|(?<=[.!?])\s+(?=[A-Z])/).filter(Boolean);
      for (const sentence of sentences) {
        const matches = sources.filter(source => (source.text || source.statement || "").includes(sentence) || sentence.includes(source.text || source.statement || "\0"));
        if (!matches.length) continue;
        const mapping = node("section", {class: "grounding-evidence"}); mapping.append(md(formatAnswer({...answer, text: sentence}, record), answer));
        for (const source of matches) mapping.append(node("small", {}, `Supported by ${source.title || "recorded fact"}`), copyId(source.ref || source.id));
        body.append(mapping);
      }
      if (sources.some(source => source.kind !== "fact")) sourceContent(body, answer);
    } else if (row.stage === "clarify") {
      const asked = row.question;
      if (asked) {
        body.append(node("h4", {}, "Question"), md(asked.message, answer));
        const replied = allQuestions.find(item => item.clarification_id && item.clarification_id === asked.pending_question?.id);
        if (replied) body.append(node("h4", {}, "Your reply"), node("p", {}, replied.message));
        else body.append(node("p", {class: "muted"}, "Awaiting your reply"));
      }
    } else {
      if (data.message && !(row.stage === "route" && data.status === "needs_information" && data.source === "selected")) body.append(md(data.message, answer));
      if (data.family_id) fields(body, [["Chosen family", family(data.family_id)]]);
      if (data.problems?.length) fields(body, [["Chosen problem", data.problems.join(", ")]]);
      const choices = data.candidates || data.alternatives || [];
      if (choices.length) {
        body.append(node("h4", {}, choices.length > 1 ? "Options considered" : "Chosen topic"));
        for (const choice of choices) { const item = node("section"); item.append(node("strong", {}, choice.title || topic(choice.topic_id) || choice.problem)); if (choice.reason) item.append(md(choice.reason, answer)); fields(item, [["Score", choice.score ?? choice.confidence]]); body.append(item); }
      }
      if (row.stage === "candidates") {
        const reply = events.findLast(event => event.type === "workflow.chat" && event.payload.options?.length)?.payload;
        for (const option of reply?.options || []) fields(body, [["Option", option.title], ["Match", option.match], ["Score", option.score ?? option.confidence]]);
      }
    }
    return body;
  }
  function render(questions, getEvents, records, getAnswer, numbers) {
    const active = new Set(); let count = 0;
    for (const [index, question] of questions.entries()) {
      const key = question.turn_id, events = getEvents(key), record = records.get(key);
      const answer = (record && getAnswer(record)) || events.findLast(event => event.type === "workflow.chat" && event.payload.answer)?.payload.answer;
      const calls = window.GraphMineModelCalls(events); count += calls.length;
      active.add(key);
      let turn = turns.get(key);
      if (!turn) {
        const host = node("li", {class: "activity-turn", "data-turn": key, tabindex: "-1"}), heading = node("h3"), text = node("p", {class: "turn-question"}), total = node("small", {class: "model-call-count"}), timeline = node("ol", {class: "activity-timeline"});
        host.append(heading, text, total, timeline); turn = {host, heading, text, total, timeline, rows: new Map()}; turns.set(key, turn);
      }
      turn.heading.textContent = `Question ${numbers.get(key) || index + 1}`; turn.text.textContent = question.message;
      turn.total.textContent = calls.length ? `${calls.length} model ${calls.length === 1 ? "call" : "calls"}` : state.planning && key === questions.at(-1)?.turn_id ? "Preparing your question…" : "Reused your earlier choice";
      const steps = window.GraphMineActivitySteps(events, {record, answer, pending: state.planning && key === questions.at(-1)?.turn_id || state.pendingQuestion?.id === key}), retained = new Set();
      for (const row of steps) {
        retained.add(row.stage); let entry = turn.rows.get(row.stage);
        if (!entry) { const li = node("li"), detail = node("details", {class: "activity-step", "data-stage": row.stage}), label = node("summary"), icon = node("span", {class: "activity-step-icon", "aria-hidden": "true"}), name = node("span"); label.append(icon, name); detail.append(label); li.append(detail); entry = {li, detail, icon, name, body: null, signature: ""}; turn.rows.set(row.stage, entry);
          detail.addEventListener("toggle", () => { if (detail.open && entry.row?.record && entry.row.record.status === "completed") void loadResult(entry.row.record); });
        }
        entry.detail.dataset.state = row.state; entry.icon.textContent = {done: "✓", failed: "✗", running: "◌", incomplete: "—", waiting: "○"}[row.state];
        entry.name.textContent = summary(row, answer);
        entry.row = row;
        const signature = JSON.stringify([row, answer, row.record ? savedResults.get(resultKey(row.record)) : null, state.caps?.problems?.length, state.files.map(file => file.id), questions.map(q => q.clarification_id)], (_, value) => typeof value === "bigint" ? `bigint:${value}` : value);
        if (entry.signature !== signature) { const body = content(row, answer, question, events, questions, record); if (entry.body) entry.body.replaceWith(body); else entry.detail.append(body); entry.body = body; entry.signature = signature; }
        if (turn.timeline.children[[...retained].length - 1] !== entry.li) turn.timeline.insertBefore(entry.li, turn.timeline.children[[...retained].length - 1] || null);
      }
      for (const [stage, entry] of turn.rows) if (!retained.has(stage)) { entry.li.remove(); turn.rows.delete(stage); }
      const list = document.getElementById("activity-list"); if (list.children[index] !== turn.host) list.insertBefore(turn.host, list.children[index] || null);
    }
    for (const [key, turn] of turns) if (!active.has(key)) { turn.host.remove(); turns.delete(key); }
    document.getElementById("reasoning-count").textContent = String(count);
    return count;
  }
  function open(turnId, stage = null, sourceId = null, trigger = document.activeElement) {
    window.GraphMineShell.setPanel("activity", true, trigger);
    const turn = turns.get(turnId); if (!turn) return;
    const detail = stage && turn.rows.get(stage)?.detail;
    if (detail) detail.open = true;
    const target = sourceId && [...(detail || turn.host).querySelectorAll("[data-source]")].find(el => el.dataset.source === sourceId) || detail || turn.host;
    requestAnimationFrame(() => { target.scrollIntoView({block: "nearest", behavior: "smooth"}); turn.host.focus({preventScroll: true}); target.classList.remove("activity-highlight"); void target.offsetWidth; target.classList.add("activity-highlight"); setTimeout(() => target.classList.remove("activity-highlight"), 1800); });
  }
  return {render, open, clean, markdown: md, copyId};
};
