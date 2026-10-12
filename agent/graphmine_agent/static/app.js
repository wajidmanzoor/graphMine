(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const stored = name => { try { return localStorage.getItem(name) || ""; } catch (_) { return ""; } };
  const state = {
    base: stored("graphmine.apiBase"),
    token: stored("graphmine.apiToken"),
    domains: [], session: null, files: [], graphId: null,
    result: null, graphPreview: null, socket: null, lastEvent: 0,
    networks: [], explorers: [], selections: new Map(), page: "chat", savedResults: [], activity: new Map(),
    feedbackTarget: {}, feedbackCount: 0, lastTurnId: null, resultJob: null,
    busy: false, sessionEpoch: 0, reconnectTimer: null, announcedResults: new Set(),
    reasoningRefresh: 0,
  };

  const domainGlyphs = ["◇", "⌁", "✣", "⌾", "◎", "▦", "◈", "⌬", "↝"];

  function headers(json = true) {
    const value = json ? {"Content-Type": "application/json"} : {};
    if (state.token) value.Authorization = `Bearer ${state.token}`;
    return value;
  }

  async function api(path, options = {}) {
    const response = await fetch(`${state.base}${path}`, {
      ...options,
      headers: {...headers(!(options.body instanceof FormData)), ...(options.headers || {})},
    });
    let body = null;
    try { body = await response.json(); } catch (_) { body = {}; }
    if (!response.ok) {
      const detail = body.error?.message || body.detail?.message || body.detail || response.statusText;
      const error = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      error.turnId = body.turn_id; throw error;
    }
    return body;
  }

  function toast(message, error = false) {
    const node = $("#toast");
    node.textContent = message;
    node.className = `toast show${error ? " error" : ""}`;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => node.className = "toast", 3500);
  }

  function escape(value) {
    return String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  }

  async function loadSessions() {
    const sessions = await api("/api/sessions?limit=40");
    $("#recent-sessions").innerHTML = sessions.length ? sessions.map(session => `<a class="recent-session" href="#session/${escape(session.id)}"><strong>${escape(session.title || "Untitled conversation")}</strong><span>${escape(session.participant_id || session.domain_id.replaceAll("_", " "))} · ${escape(new Date(session.updated_at).toLocaleString())}</span><span aria-hidden="true">↗</span></a>`).join("") : '<p class="muted">Your saved conversations will appear here.</p>';
  }

  function disconnectEvents() {
    clearTimeout(state.reconnectTimer);
    if (state.socket) { state.socket.onclose = null; state.socket.close(); state.socket = null; }
  }

  function resetWorkspace() {
    disconnectEvents(); state.sessionEpoch++;
    state.networks.forEach(network => network.destroy()); state.networks = [];
    clearExplorers();
    Object.assign(state, {session:null, files:[], graphId:null, result:null, resultJob:null, graphPreview:null, lastEvent:0, lastTurnId:null, savedResults:[], feedbackCount:0});
    state.activity.clear(); state.announcedResults.clear();
    $("#messages").innerHTML = ""; $("#activity-list").innerHTML = "";
    $("#reasoning-count").textContent = "0"; $("#model-reasoning").innerHTML = '<p class="muted">No reasoning text returned yet. Some stages run with thinking disabled.</p>';
    $("#model-reasoning-panel").open = false;
    $("#activity-empty").classList.remove("hidden");
    $("#job-state").classList.add("hidden");
    $("#result-content").classList.add("hidden"); $("#empty-insights").classList.remove("hidden");
    $("#raw-result").classList.add("hidden"); $("#projection-toggle").checked = false;
    renderResultPicker(); renderFeedbackCount();
  }

  async function restoreSession(id) {
    resetWorkspace(); const epoch = state.sessionEpoch;
    const saved = await api(`/api/sessions/${encodeURIComponent(id)}/workspace`);
    if (epoch !== state.sessionEpoch) return;
    state.session = saved.session; state.files = saved.files;
    state.graphId = [...state.files].reverse().find(file => file.role === "graph")?.id || null;
    state.feedbackCount = saved.feedback_count;
    const domain = state.domains.find(item => item.id === saved.session.domain_id);
    $("#active-domain").textContent = domain?.name || saved.session.domain_id;
    $("#active-domain-description").textContent = domain?.description || "";
    $("#workspace-title").textContent = saved.session.title || "Untitled conversation";
    $("#results-session-title").textContent = saved.session.title || "Untitled conversation";
    state.savedResults = saved.jobs.filter(job => job.result_id).map(job => ({id:job.result_id, title:job.plan.application_intent?.objective || "Completed analysis"}));
    for (const row of saved.messages) {
      addMessage(row.role, row.message, row.plan, row);
      if (row.result_id) state.announcedResults.add(row.result_id);
      if (row.kind?.startsWith("chat.")) state.lastTurnId = row.turn_id;
    }
    if (!saved.messages.length) addMessage("assistant", "Upload your relationship data and ask a question in your own words. You can follow the analysis here, then explore the evidence on the Results page.");
    for (const event of saved.events) { state.lastEvent = Math.max(state.lastEvent, event.sequence || 0); handleEvent(event, true); }
    renderFiles(); renderFeedbackCount(); renderResultPicker();
    showPage("chat"); connectEvents(); loadReasoning();
    if (state.savedResults.length) await loadResult(state.savedResults.at(-1).id, false);
  }

  function showPage(page) {
    state.page = page;
    $("#domain-view").classList.add("hidden");
    $("#workspace-nav").classList.remove("hidden");
    $("#workspace-view").classList.toggle("hidden", page !== "chat");
    $("#results-view").classList.toggle("hidden", page !== "results");
    for (const name of ["chat", "results"]) {
      const link = $(`#${name}-page-link`);
      link.href = `#session/${state.session?.id}${name === "results" ? "/results" : ""}`;
      if (name === page) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    }
    if (page === "results" && state.result) renderResult();
  }

  function navigate(page) {
    if (!state.session) return;
    history.pushState(null, "", `#session/${state.session.id}${page === "results" ? `/results${state.result ? "/" + state.result.id : ""}` : ""}`);
    showPage(page);
  }

  async function routeLocation() {
    const match = window.location.hash.match(/^#session\/([A-Za-z0-9_-]+)(?:\/(results)(?:\/([A-Za-z0-9_-]+))?)?$/);
    if (!match) {
      resetWorkspace(); $("#workspace-view").classList.add("hidden"); $("#results-view").classList.add("hidden");
      $("#workspace-nav").classList.add("hidden"); $("#domain-view").classList.remove("hidden");
      await loadSessions(); return;
    }
    try {
      if (state.session?.id !== match[1]) await restoreSession(match[1]);
      if (match[3] && state.result?.id !== match[3]) await loadResult(match[3], false);
      showPage(match[2] ? "results" : "chat");
    } catch (error) { toast(error.message, true); }
  }

  function recordActivity(event) {
    let key, item;
    if (event.type === "analysis.activity") { key = event.payload.activity_id; item = event.payload; }
    else if (event.type.startsWith("job.")) {
      key = event.job_id;
      const labels = {"job.queued":"Waiting to run", "job.running":"Computing your answer", "job.interpreting":"Checking and explaining the result", "job.completed":"Results ready", "job.failed":"Analysis failed", "job.cancelled":"Analysis cancelled"};
      item = {stage:"Computation", message:labels[event.type] || event.type, status:event.type === "job.completed" ? "completed" : event.type === "job.failed" || event.type === "job.cancelled" ? "failed" : "running"};
    } else return;
    state.activity.set(key, {...item, created_at:event.created_at});
    $("#activity-empty").classList.add("hidden");
    $("#activity-list").innerHTML = [...state.activity.values()].slice(-24).map(item => `<li class="activity-step ${escape(item.status)}"><div class="activity-marker" aria-hidden="true">${item.status === "completed" ? "✓" : item.status === "failed" ? "!" : "·"}</div><div><div class="activity-heading"><strong>${escape(item.stage)}</strong><small>${item.elapsed_seconds != null ? escape(item.elapsed_seconds) + "s" : escape(new Date(item.created_at).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}))}</small></div><p>${escape(item.message)}</p><span class="activity-status">${escape(item.status)}</span></div></li>`).join("");
    const column = $("#activity-column"); column.scrollTop = column.scrollHeight;
  }

  async function loadReasoning() {
    if (!state.session) return;
    const sessionId = state.session.id, refresh = ++state.reasoningRefresh;
    try {
      const records = await api(`/api/sessions/${sessionId}/reasoning`);
      if (state.session?.id !== sessionId || refresh !== state.reasoningRefresh) return;
      $("#reasoning-count").textContent = records.length;
      if (!records.length) return;
      const labels = {PlanDraft:"Plan validation", RouteDecision:"Request interpretation", TurnDecision:"Follow-up decision", GroundedNarrative:"Answer preparation"};
      $("#model-reasoning").innerHTML = records.slice(-24).map(record => `<details class="reasoning-record"><summary>${escape(labels[record.stage] || record.stage)} · ${escape(new Date(record.created_at).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}))}</summary><small>${escape(record.model)}</small><pre>${escape(record.reasoning)}</pre></details>`).join("");
    } catch (_) { /* A reconnect can recover the persisted model logs. */ }
  }

  function renderResultPicker() {
    $("#result-count").textContent = state.savedResults.length;
    $("#result-select").innerHTML = state.savedResults.length ? state.savedResults.map((result, index) => `<option value="${escape(result.id)}">${index + 1}. ${escape(result.title)}</option>`).join("") : '<option value="">No results yet</option>';
    if (state.result) $("#result-select").value = state.result.id;
    $("#download-report").disabled = !state.result; $("#result-feedback").disabled = !state.result;
  }

  function renderFeedbackCount() { $("#feedback-count").textContent = `${state.feedbackCount} saved annotation${state.feedbackCount === 1 ? "" : "s"}`; }

  function openFeedback(target = {}) {
    state.feedbackTarget = {turn_id:target.turn_id || null, job_id:target.job_id || null, result_id:target.result_id || null};
    if (!Object.values(state.feedbackTarget).some(Boolean)) state.feedbackTarget.turn_id = state.lastTurnId;
    $("#feedback-form").reset();
    $("#feedback-target").textContent = target.result_id ? "Reviewing this saved result. Your note and the full conversation are stored without calling the model." : "Reviewing this turn. Your note and the full conversation are stored without calling the model.";
    $("#feedback-dialog").showModal(); $("#feedback-note").focus();
  }

  async function saveFeedback(event) {
    event.preventDefault(); if (!state.session) return;
    const category = $("#feedback-kind").value;
    const expected = $("#feedback-expected").value.trim() || null;
    const rating = $("#feedback-rating").value ? Number($("#feedback-rating").value) : null;
    if (category === "rating" && !rating) { toast("Choose a rating from 1 to 5.", true); return; }
    if (category === "correction" && !expected) { toast("Add the corrected answer in Expected answer.", true); return; }
    $("#save-feedback").disabled = true;
    try {
      await api(`/api/sessions/${state.session.id}/feedback`, {method:"POST", body:JSON.stringify({...state.feedbackTarget, category, rating, what_went_wrong:$("#feedback-note").value.trim(), expected_behavior:expected})});
      state.feedbackCount++; renderFeedbackCount(); $("#feedback-dialog").close(); toast("Feedback saved with the conversation. No model call was made.");
    } catch (error) { toast(error.message, true); }
    finally { $("#save-feedback").disabled = false; }
  }

  async function download(path, filename) {
    const response = await fetch(`${state.base}${path}`, {headers:headers(false)});
    if (!response.ok) throw new Error(`Download failed (${response.status}).`);
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a"); link.href = url; link.download = filename; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function loadDomains() {
    try {
      state.domains = await api("/api/domains");
      $("#domain-grid").innerHTML = state.domains.map((domain, index) => `
        <button class="domain-card" data-domain="${escape(domain.id)}">
          <span class="domain-icon">${domainGlyphs[index % domainGlyphs.length]}</span>
          <h2>${escape(domain.name)}</h2><p>${escape(domain.description)}</p>
        </button>`).join("");
      document.querySelectorAll(".domain-card").forEach(card => card.addEventListener("click", () => startSession(card.dataset.domain)));
      await Promise.all([health(), loadSessions()]);
    } catch (error) {
      $("#domain-grid").innerHTML = `<div class="loading-card">Could not reach the GraphMine server. Open connection settings and check the API address or token.</div>`;
      setStatus("Offline", "degraded"); toast(error.message, true);
    }
  }

  async function health() {
    const report = await api("/api/health");
    const version = report.version ? ` · v${report.version}` : "";
    setStatus(report.status === "ready" ? `Server ready${version}` : `Server degraded${version}`, report.status === "ready" ? "ready" : "degraded");
    $("#graphmine-state").textContent = report.graphmine.binary_available && !report.graphmine.error ? `${report.graphmine.compiled_backend_count} backends · v${report.graphmine.library_version || "?"}` : "Unavailable";
    $("#llm-state").textContent = report.llm.enabled ? report.llm.model.split("/").pop() : "Offline fallback";
    $("#model-version").textContent = report.deployment?.version || "Base model";
    $("#model-version").title = `Analysis selection: ${report.deployment?.routing_model || report.llm.model}${report.deployment?.routing_experimental ? " (experimental for the current catalog)" : ""}\nAnswers: ${report.llm.model}`;
  }

  function setStatus(label, kind) {
    const node = $("#server-status"); node.textContent = label; node.className = `status status-${kind}`;
  }

  async function startSession(domainId) {
    const title = $("#session-title").value.trim() || null;
    try {
      const session = await api("/api/sessions", {method:"POST", body:JSON.stringify({domain_id:domainId, title, participant_id:$("#participant-id").value.trim() || null})});
      window.location.hash = `session/${session.id}`;
    } catch (error) { toast(error.message, true); }
  }

  function connectEvents() {
    clearTimeout(state.reconnectTimer);
    if (state.socket) { state.socket.onclose = null; state.socket.close(); }
    if (!state.session) return;
    const origin = state.base || window.location.origin;
    const url = new URL(`/api/sessions/${state.session.id}/events/ws`, origin);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.searchParams.set("after", state.lastEvent);
    const protocols = ["graphmine"];
    if (state.token) {
      const bytes = new TextEncoder().encode(state.token);
      let binary = "";
      bytes.forEach(byte => binary += String.fromCharCode(byte));
      const encoded = btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
      protocols.push(`graphmine.token.${encoded}`);
    }
    const socket = new WebSocket(url, protocols); state.socket = socket;
    socket.onmessage = event => {
      const value = JSON.parse(event.data);
      if (value.type === "heartbeat" || value.session_id !== state.session?.id) return;
      state.lastEvent = Math.max(state.lastEvent, value.sequence || 0);
      handleEvent(value);
    };
    socket.onclose = () => {
      if (state.session && state.socket === socket) state.reconnectTimer = setTimeout(connectEvents, 1800);
    };
  }

  function handleEvent(event, replay = false) {
    recordActivity(event);
    if (!replay && (event.type === "job.completed" || event.type === "analysis.activity" && ["completed", "failed"].includes(event.payload.status))) loadReasoning();
    if (event.type.startsWith("analysis.")) {
      $("#job-state").textContent = event.payload.stage ? `${event.payload.stage}${event.payload.status === "completed" ? " · done" : event.payload.status === "failed" ? " · failed" : ""}` : event.payload.message || "Preparing your analysis";
      $("#job-state").classList.remove("hidden");
      return;
    }
    const labels = {"job.queued":"Queued for GPU", "job.running":"Running on GPU", "job.interpreting":"Interpreting result", "job.completed":"Complete", "job.failed":"Failed", "job.cancelled":"Cancelled"};
    const node = $("#job-state"); node.textContent = labels[event.type] || event.type; node.classList.remove("hidden");
    if (event.type === "job.completed" && !replay) loadResult(event.payload.result_id);
    if (event.type === "job.failed" && !replay) { toast(event.payload.error?.message || "Analysis failed", true); addMessage("assistant", event.payload.error?.message || "The analysis failed.", null, {job_id:event.job_id}); }
  }

  async function upload(files) {
    if (!state.session) return;
    for (const file of files) {
      const data = new FormData(); data.append("file", file); data.append("role", $("#file-role").value); data.append("directed", $("#directed").checked);
      for (const key of ["source-column", "target-column", "timestamp-unit"]) { const value = $("#" + key).value.trim(); if (value) data.append(key.replaceAll("-", "_"), value); }
      try {
        toast(`Uploading ${file.name}…`);
        const record = await api(`/api/sessions/${state.session.id}/files`, {method:"POST", body:data});
        state.files.push(record); if (record.role === "graph") { state.graphId = record.id; $("#projection-toggle").checked = false; }
        renderFiles(); toast(`${file.name} is ready`);
      } catch (error) { toast(`${file.name}: ${error.message}`, true); }
    }
  }

  function renderFiles() {
    $("#file-list").innerHTML = state.files.map(file => `<div class="file-item" title="${escape(file.id)}"><span>${escape(file.original_name)}</span><em>${escape(file.role.replaceAll("_", " "))}</em></div>`).join("");
  }

  function addMessage(role, content, plan = null, metadata = {}) {
    const article = document.createElement("article"); article.className = `message ${role}`;
    const planHtml = plan ? `<details class="plan-card"><summary>Analysis details</summary><p>${escape(plan.application_intent?.objective || "Validated computation")}</p><div class="plan-grid"><span>Operation</span><b>${escape(plan.operation_id)}</b><span>Backend</span><b>${escape(plan.backend_id)}</b>${Object.keys(plan.parameters || {}).length ? `<span>Parameters</span><b>${escape(JSON.stringify(plan.parameters))}</b>` : ""}</div></details>` : "";
    article.innerHTML = `<div class="avatar">${role === "user" ? "Y" : "G"}</div><div class="bubble"><p>${escape(content).replaceAll("\n", "<br>")}</p>${planHtml}</div>`;
    if (metadata.command || metadata.kind?.startsWith("feedback_command")) article.classList.add("local-command");
    const actions = document.createElement("div"); actions.className = "message-actions";
    if (metadata.result_id) {
      const link = document.createElement("a"); link.className = "result-link"; link.textContent = "Open results & visualizations →";
      link.href = `#session/${state.session?.id}/results/${metadata.result_id}`; actions.appendChild(link);
    }
    if (role === "assistant" && !metadata.command && !metadata.kind?.startsWith("feedback_command") && (metadata.turn_id || metadata.result_id || metadata.job_id)) {
      const review = document.createElement("button"); review.className = "text-button"; review.textContent = "Give feedback";
      review.addEventListener("click", () => openFeedback(metadata)); actions.appendChild(review);
    }
    if (actions.children.length) article.querySelector(".bubble").appendChild(actions);
    $("#messages").appendChild(article); $("#messages").scrollTop = $("#messages").scrollHeight;
  }

  async function sendChat(message, context = {}) {
    if (!state.session || state.busy) return;
    const sessionId = state.session.id;
    state.busy = true;
    addMessage("user", message); $("#send-button").disabled = true;
    try {
      const response = await api(`/api/sessions/${state.session.id}/chat`, {method:"POST", body:JSON.stringify({message, graph_id:state.graphId, result_id:state.result?.id || null, ...context, mode:"auto", execute:$("#execute-toggle").checked, ...($("#projection-toggle").checked ? {allow_directed_projection:true} : {})})});
      if (state.session?.id !== sessionId) return;
      if (!response.command) state.lastTurnId = response.turn_id;
      addMessage("assistant", response.message, response.plan, response);
      if (response.feedback_id) { state.feedbackCount++; renderFeedbackCount(); }
      if (response.download_url) await download(response.download_url, `${sessionId}.zip`);
      if (response.interpretation && response.result_id) await loadResult(response.result_id, false);
      if (response.job_id) { $("#job-state").textContent = "Queued for GPU"; $("#job-state").classList.remove("hidden"); }
    } catch (error) { if (state.session?.id === sessionId) { state.lastTurnId = error.turnId || state.lastTurnId; addMessage("assistant", `I couldn't complete that request: ${error.message}`, null, {turn_id:error.turnId}); toast(error.message, true); } }
    finally { state.busy = false; $("#send-button").disabled = false; }
  }

  async function loadResult(resultId, announce = true) {
    const epoch = state.sessionEpoch;
    try {
      const result = await api(`/api/results/${resultId}`);
      if (epoch !== state.sessionEpoch) return;
      if (result.session_id !== state.session?.id) throw new Error("This result belongs to another conversation.");
      state.result = result;
      try {
        const job = await api(`/api/jobs/${state.result.job_id}`);
        if (epoch !== state.sessionEpoch) return;
        state.resultJob = job;
        if (state.result.answer?.network) { state.graphPreview = null; }
        else {
        state.graphPreview = await api(`/api/files/${job.plan.graph_id}/graph-preview?vertex_limit=500&edge_limit=2000`);
        }
      } catch (_) { state.graphPreview = null; }
      if (epoch !== state.sessionEpoch) return;
      if (!state.savedResults.some(item => item.id === resultId)) state.savedResults.push({id:resultId, title:state.result.answer?.question || "Completed analysis"});
      renderResultPicker();
      if (state.page === "results") renderResult();
      if (announce && !state.announcedResults.has(resultId)) {
        addMessage("assistant", state.result.interpretation?.summary || "Your analysis is ready. Open the Results page to explore the evidence.", null, {result_id:resultId, job_id:state.result.job_id, turn_id:state.resultJob?.turn_id});
        state.announcedResults.add(resultId);
      }
    } catch (error) { toast(error.message, true); }
  }

  function resolvePath(object, path) {
    return path.split(".").filter(Boolean).reduce((value, key) => value != null && Object.prototype.hasOwnProperty.call(value, key) ? value[key] : undefined, object);
  }

  function answerContext(answer) {
    if (answer.steps) return Object.values(answer.steps).map((step, index) => `<section class="answer-step"><h3>Analysis ${index + 1}</h3>${answerContext(step)}</section>`).join("");
    const source = answer.provenance || {};
    const statuses = (answer.result_status || []).map(item => `<span class="result-status ${item.tone === "caution" ? "status-caution" : item.tone === "positive" ? "status-positive" : ""}" title="${escape(item.detail)}">${escape(item.label)}</span>`).join("");
    const scope = Number.isInteger(source.input_vertices) && Number.isInteger(source.input_edges)
      ? `<p>Analysed <strong>${escape(formatValue(source.input_vertices))} ${escape(answer.entity_noun || "entities")}</strong> and <strong>${escape(formatValue(source.input_edges))} relationships</strong>${Number.isInteger(source.source_vertices) && (source.source_vertices !== source.input_vertices || source.source_edges !== source.input_edges) ? ` from ${escape(formatValue(source.source_vertices))} entities and ${escape(formatValue(source.source_edges))} relationships in the upload` : ""}.</p>` : "";
    const filters = (answer.facts || []).filter(item => ["filter_evidence", "scope"].includes(item.kind));
    return `${statuses ? `<div class="result-statuses" aria-label="Result status">${statuses}</div>` : ""}${answer.method_explanation ? `<section class="answer-method"><h3>How to read this result</h3><p>${escape(answer.method_explanation)}</p></section>` : ""}${scope || filters.length ? `<section class="answer-scope"><h3>Data and filters used</h3>${scope}${filters.length ? `<ul>${filters.map(item => `<li>${escape(item.statement)}</li>`).join("")}</ul>` : ""}</section>` : ""}`;
  }

  function renderResult() {
    if (!state.result) return;
    clearExplorers();
    const result = state.result, interpretation = result.interpretation;
    $("#insight-column").classList.remove("empty"); $("#empty-insights").classList.add("hidden"); $("#result-content").classList.remove("hidden");
    $("#result-title").textContent = interpretation?.summary || "Analysis result";
    $("#raw-result").textContent = JSON.stringify({result: result.payload, diagnostics: result.answer?.diagnostics}, null, 2);
    if (interpretation) {
      const additional = interpretation.findings.filter(value => value !== interpretation.summary);
      const answer = result.answer || {};
      const scopeFacts = new Set((answer.facts || []).filter(item => ["filter_evidence", "scope"].includes(item.kind)).map(item => item.statement));
      const findings = additional.filter(value => !scopeFacts.has(value));
      const evidence = (interpretation.evidence || []).map(item => `<li><p>${escape(item.claim)}</p><small>Recorded value: ${escape(formatValue(item.value))}</small></li>`).join("");
      const explanation = (interpretation.explanation || []).map(item => {
        const support = (answer.facts || []).filter(fact => item.fact_ids.includes(fact.id));
        return `<div class="analysis-paragraph"><p>${escape(item.text)}</p><details><summary>Supporting evidence</summary><ul>${support.map(fact => `<li>${escape(fact.statement)}</li>`).join("")}</ul></details></div>`;
      }).join("");
      $("#interpretation").innerHTML = `${answer.question ? `<p class="answer-question"><span>Your question</span>${escape(answer.question)}</p>` : ""}${explanation ? `<section class="analysis-explanation"><h3>What this means</h3>${explanation}</section>` : ""}${listSection(explanation ? "Computed findings" : "Key findings", findings)}${answerContext(answer)}${listSection("Limitations", interpretation.limitations)}${listSection("Possible implications · model suggestions, not verified findings", interpretation.hypotheses)}${evidence ? `<details class="answer-evidence"><summary>Inspect supporting values</summary><ol>${evidence}</ol></details>` : ""}`;
      state.networks.forEach(network => network.destroy()); state.networks = [];
      $("#visualizations").innerHTML = "";
      interpretation.visualizations.forEach(spec => renderVisualization(spec, resolvePath({...result.payload, answer: result.answer}, spec.data_ref)));
      const actions = document.createElement("section"); actions.className = "followup-actions";
      actions.innerHTML = "<h3>Explore next</h3>";
      (interpretation.followup_actions || []).forEach(action => {
        const button = document.createElement("button"); button.className = "secondary-button"; button.textContent = action.label;
        if (action.kind === "show_view") button.addEventListener("click", () => {
          const target = [...document.querySelectorAll(".viz-card")].find(card => card.dataset.viewId === action.view_id);
          if (target) target.scrollIntoView({behavior:"smooth",block:"start"});
        });
        else if (action.kind === "ask") {
          button.title = action.request;
          button.addEventListener("click", () => {
            if (document.querySelector("#graphmine-report")) { toast("Open a live session to ask: " + action.request); return; }
            const context = {result_id:result.id, graph_id:state.resultJob?.plan.graph_id || null};
            navigate("chat"); sendChat(action.request, context);
          });
        }
        actions.appendChild(button);
      });
      if (actions.children.length > 1) $("#visualizations").appendChild(actions);
    } else {
      $("#interpretation").innerHTML = "<p>The computation completed; interpretation is not yet available.</p>";
      state.networks.forEach(network => network.destroy()); state.networks = [];
      $("#visualizations").innerHTML = "";
    }
  }

  function listSection(title, items) {
    return items?.length ? `<h3>${escape(title)}</h3><ul>${items.map(item => `<li>${escape(item)}</li>`).join("")}</ul>` : "";
  }

  function renderVisualization(spec, data) {
    data = applyViewFilters(data, spec.filters || []);
    const card = document.createElement("section"); card.className = "viz-card";
    card.dataset.viewId = spec.id;
    const previewNote = spec.type === "network" && !Array.isArray(data?.nodes) && state.graphPreview && (state.graphPreview.vertices_truncated || state.graphPreview.edges_truncated)
      ? ` Preview shows ${state.graphPreview.vertices.length}/${state.graphPreview.vertex_count} vertices and ${state.graphPreview.edges.length}/${state.graphPreview.edge_count} edges.` : "";
    card.innerHTML = `<div class="viz-head"><div><h3>${escape(spec.title)}</h3><p>${escape((spec.description || "") + previewNote)}</p></div><span class="viz-kind">${escape(spec.type === "vega_lite" ? "Custom chart" : spec.type)}</span></div><div class="viz-body"></div>`;
    const body = card.querySelector(".viz-body");
    $("#visualizations").appendChild(card);
    if (spec.type === "vega_lite") renderVega(body, spec);
    else if (spec.type === "metric_cards") renderMetrics(body, data, spec.encodings);
    else if (["bar", "histogram"].includes(spec.type)) renderBars(body, data, spec);
    else if (spec.type === "line") renderLine(body, data, spec);
    else if (spec.type === "timeline") renderTimeline(body, data, spec);
    else if (spec.type === "heatmap") renderHeatmap(body, data, spec);
    else if (spec.type === "network") renderNetwork(body, data, spec);
    else {
      const legacy = spec.data_ref.match(/^(answer(?:\.steps\.[^.]+)*)\.tables\.(members|groups)$/);
      const scope = spec.encodings?.answer_ref || legacy?.[1], kind = spec.encodings?.table || legacy?.[2];
      const answer = resolvePath({answer: state.result?.answer}, scope || "");
      const model = Array.isArray(answer?.rows) && ["members", "groups"].includes(kind) ? answerTableModel(answer, kind) : null;
      renderTable(body, data, spec.limit || 1000, spec.data_ref.includes(".tables.") || spec.encodings?.readable === "true", model, {...spec, encodings: {...spec.encodings, answer_ref: scope}});
    }
  }

  async function renderVega(body, spec) {
    const scope = spec.encodings?.answer_ref || "answer";
    const host = document.createElement("div"); host.className = "vega-chart";
    host.setAttribute("role", "figure"); host.setAttribute("aria-label", spec.title);
    host.tabIndex = 0;
    const scrollHint = document.createElement("p"); scrollHint.className = "chart-scroll-hint muted";
    scrollHint.textContent = "Scroll sideways to see the full chart."; scrollHint.hidden = true;
    const updateOverflow = () => { scrollHint.hidden = host.scrollWidth <= host.clientWidth + 1; };
    const status = document.createElement("p"); status.className = "chart-selection-status muted";
    const reset = document.createElement("button"); reset.className = "text-button"; reset.textContent = "Clear shared selection";
    reset.addEventListener("click", () => selectEntities(scope, []));
    body.append(host, scrollHint, status, reset);
    let view = null, disposed = false;
    const explorer = {
      scope,
      update() {
        const keys = [...selectedEntities(scope)];
        status.textContent = keys.length ? `${keys.length} entities selected across these views.` : "Select an entity or group to explore the supporting views.";
        if (view && !disposed) view.signal("graphmine_selection", keys).runAsync().catch(() => {});
      },
      destroy() { disposed = true; view?.finalize(); }
    };
    state.explorers.push(explorer); explorer.update();
    try {
      if (!window.vegaEmbed || !spec.vega_lite) throw new Error("Visualization renderer unavailable");
      const chart = structuredClone(spec.vega_lite);
      chart.params = [...(chart.params || []).filter(param => param.name !== "graphmine_selection"), {name:"graphmine_selection", value:[]}];
      function link(node) {
        if (node.mark && node.encoding && !node.encoding.opacity) node.encoding.opacity = {condition:{test:"!isValid(datum.entity_key) || length(graphmine_selection) === 0 || indexof(graphmine_selection, datum.entity_key) >= 0", value:1}, value:0.2};
        for (const key of ["layer", "hconcat", "vconcat", "concat"]) (node[key] || []).forEach(link);
        if (node.spec) link(node.spec);
      }
      link(chart);
      const rendered = await window.vegaEmbed(host, chart, {
        mode:"vega-lite", renderer:"svg", defaultStyle:true,
        actions:{export:true, source:true, compiled:false, editor:false},
        loader:{load(){return Promise.reject(new Error("External data is disabled"));}, sanitize(){return Promise.reject(new Error("External resources are disabled"));}},
        config:{font:"system-ui", background:"transparent", axis:{labelFontSize:12,titleFontSize:13}, legend:{labelFontSize:12,titleFontSize:13}, view:{stroke:null}}
      });
      view = rendered.view;
      if (disposed) { view.finalize(); return; }
      host.graphmineVega = view;
      view.addEventListener("click", (_event, item) => {
        const row = item?.datum;
        if (row?.entity_key != null) selectEntities(scope, [String(row.entity_key)]);
        else if (row?.group_id != null) {
          const answer = resolvePath({answer:state.result?.answer}, scope);
          const group = answer?.groups?.find(group => String(group.id) === String(row.group_id));
          if (group?.member_keys) selectEntities(scope, group.member_keys);
        }
      });
      for (const parameter of chart.params) {
        if (parameter.select?.fields?.includes("entity_key")) view.addSignalListener(parameter.name, (_name, value) => {
          if (Array.isArray(value?.entity_key)) selectEntities(scope, value.entity_key.map(String));
        });
      }
      const observer = new ResizeObserver(() => { if (!disposed) view.resize().runAsync().then(updateOverflow).catch(() => {}); });
      observer.observe(host);
      explorer.destroy = () => { disposed = true; observer.disconnect(); view.finalize(); };
      explorer.update();
      updateOverflow();
    } catch (error) {
      if (!disposed) {
        host.replaceChildren();
        const message = document.createElement("p"); message.className = "muted";
        message.textContent = "This chart could not be drawn. The computed findings and supporting tables are still available.";
        host.appendChild(message); host.dataset.renderError = String(error);
      }
    }
  }

  function selectEntities(scope, keys) {
    state.selections.set(scope, new Set(keys));
    state.explorers.filter(view => view.scope === scope).forEach(view => view.update());
  }

  function clearExplorers() {
    state.explorers.forEach(view => view.destroy?.());
    state.explorers = []; state.selections.clear();
  }

  function selectedEntities(scope) { return state.selections.get(scope) || new Set(); }

  function answerTableModel(answer, kind) {
    const rows = answer.rows || [], columns = answer.tables?.columns || legacyTableColumns(rows);
    const byId = kind === "groups" ? new Map(rows.map(row => [row.key, row])) : null;
    const aliases = kind === "groups" && answer.groups.some(group => !group.member_keys) ? legacyEntityAliases(rows) : null;
    if (aliases && [...aliases.values()].some(value => value === null)) {
      const preview = answer.tables?.groups || [];
      return {length: preview.length, row: index => Object.fromEntries(Object.entries(preview[index]).map(([label, value]) => [label, label === "Original ID" && typeof value === "number" && !Number.isSafeInteger(value) ? "Unavailable in this older preview" : value])), keys: [...new Set(preview.flatMap(row => Object.keys(row)))], notice:"This older group preview contains identifiers that cannot be linked reliably. The returned-entities table still has every available named entity."};
    }
    const ends = []; let length = 0;
    if (kind === "groups") (answer.groups || []).forEach(group => { length += group.vertices.length; ends.push(length); });
    else length = rows.length;
    const source = index => {
      if (kind !== "groups") return {entity: rows[index]};
      let low = 0, high = ends.length - 1;
      while (low < high) { const mid = Math.floor((low + high) / 2); if (index < ends[mid]) high = mid; else low = mid + 1; }
      const group = answer.groups[low], offset = low ? ends[low - 1] : 0;
      return {group, entity: byId.get(group.member_keys?.[index - offset] ?? aliases?.get(JSON.stringify(group.vertices[index - offset])))};
    };
    return {
      length, keys: [...(kind === "groups" ? ["Group"] : []), ...columns.map(column => column.label)],
      entity: index => source(index).entity?.key,
      row: index => {
        const {group, entity} = source(index);
        return {...(group ? {Group: group.label} : {}), ...Object.fromEntries(columns.map(column => [column.label, column.path.length === 1 && column.path[0] === "id" && typeof entity?.id === "number" && !Number.isSafeInteger(entity.id) ? entity.key : column.path.reduce((value, field) => value != null && Object.prototype.hasOwnProperty.call(value, field) ? value[field] : undefined, entity)]))};
      },
    };
  }

  function legacyEntityAliases(rows) {
    const aliases = new Map();
    for (const row of rows) { const key = JSON.stringify(row.id); aliases.set(key, aliases.has(key) && aliases.get(key) !== row.key ? null : row.key); }
    return aliases;
  }

  function legacyTableColumns(rows) {
    // Old saved answers retain full source-derived rows but predate column
    // metadata. Reconstruct display columns without rewriting stored evidence.
    const columns = new Map([["Name", ["label"]], ["Original ID", ["id"]]]);
    const titles = {rank:"Rank", score:"Connection score", core_number:"Remaining-partner threshold", assigned_to:"Assigned to", assignment_cost:"Assignment cost"};
    for (const [field, label] of Object.entries(titles)) if (rows.some(row => row[field] !== undefined)) columns.set(label, [field]);
    const attributeTitles = {string_id:"STRING ID", participant_id:"Participant ID", iata:"Airport code"};
    for (const row of rows) {
      for (const [field, value] of Object.entries(row.attributes || {})) {
        if (["import_note", "note", "description"].includes(field) || value !== null && typeof value === "object") continue;
        if (["gene_name", "name", "display_name"].includes(field) && String(value) === String(row.label)) continue;
        const plain = field.replaceAll("_", " "), label = attributeTitles[field] || plain.charAt(0).toUpperCase() + plain.slice(1).toLowerCase();
        const title = columns.has(label) && columns.get(label)[0] !== "attributes" ? `Attribute: ${label}` : label;
        if (!columns.has(title) && columns.size < 15) columns.set(title, ["attributes", field]);
      }
      if (columns.size >= 15) break;
    }
    return [...columns].map(([label, path]) => ({label, path}));
  }

  function applyViewFilters(data, filters) {
    if (!Array.isArray(data) || !filters.length) return data;
    return data.filter(row => filters.every(filter => {
      const value = pick(row, filter.field), expected = filter.value;
      if (value === undefined) return false;
      if (filter.operator === "eq") return value === expected;
      if (filter.operator === "ne") return value !== expected;
      if (filter.operator === "in") return Array.isArray(expected) && expected.includes(value);
      if (filter.operator === "gt") return value > expected;
      if (filter.operator === "gte") return value >= expected;
      if (filter.operator === "lt") return value < expected;
      if (filter.operator === "lte") return value <= expected;
      return false;
    }));
  }

  function rowsFrom(data) {
    if (Array.isArray(data)) return data.map((value, index) => typeof value === "object" && value !== null ? {index, ...value} : {index, value});
    if (data && typeof data === "object") return Object.entries(data).map(([key, value]) => typeof value === "object" && value !== null && !Array.isArray(value) ? {key, ...value} : {key, value});
    return [{value:data}];
  }

  function pick(row, field) {
    if (!field) return undefined;
    if (field.endsWith(".length")) { const value = pick(row, field.slice(0,-7)); return value?.length; }
    return field.split(".").reduce((value,key) => value?.[key], row);
  }

  function renderMetrics(body, data, encodings) {
    const entries = Object.entries(encodings || {}).map(([label, field]) => [label, pick(data, field)]).filter(([,value]) => value !== undefined);
    const values = (entries.length ? entries : Object.entries(data || {})).filter(([,value]) => ["number","string"].includes(typeof value)).slice(0,12);
    if (!values.length) { body.textContent = "See the result status and findings above."; return; }
    body.innerHTML = `<div class="metric-grid">${values.map(([label,value]) => `<div class="metric"><strong>${escape(formatValue(value))}</strong><span>${escape(label.replaceAll("_"," "))}</span></div>`).join("")}</div>`;
  }

  function renderBars(body, data, spec) {
    const rows = rowsFrom(data), category = spec.encodings?.category || spec.encodings?.x, valueField = spec.encodings?.value || spec.encodings?.y, scope = spec.encodings?.answer_ref;
    let aliases;
    let points = rows.map((row,index) => {
      const numeric = pick(row,valueField) ?? row.value;
      let keys = scope && typeof row.key === "string" && row.id !== undefined ? [row.key] : [];
      if (scope && Array.isArray(row.vertices)) {
        if (row.member_keys) keys = row.member_keys;
        else { aliases ||= legacyEntityAliases(resolvePath({answer: state.result?.answer}, scope)?.rows || []); const candidates = row.vertices.map(value => aliases.get(JSON.stringify(value))); keys = candidates.every(value => typeof value === "string") ? candidates : []; }
      }
      return {label:String(pick(row,category) ?? row.key ?? row.vertex ?? row.index ?? index), value:numeric, keys};
    }).filter(point => typeof point.value === "number" && Number.isFinite(point.value));
    if (spec.type === "histogram") {
      const counts = new Map();
      points.forEach(point => { const bin = counts.get(point.value) || {value:0, keys:[]}; bin.value++; bin.keys.push(...point.keys); counts.set(point.value, bin); });
      points = [...counts].map(([label, bin]) => ({label:String(label), ...bin})).sort((a,b)=>Number(a.label)-Number(b.label));
    } else points.sort((a,b) => b.value - a.value);
    if (!points.length) { body.textContent = "No values to plot."; return; }
    const total = points.length; points = points.slice(0, Math.min(spec.limit || 20, 20));
    const min = Math.min(0, ...points.map(point => point.value)), max = Math.max(0, ...points.map(point => point.value)), span = max - min || 1, zero = -min / span * 100;
    body.innerHTML = `<p class="chart-scope">${total > points.length ? `Showing ${spec.type === "histogram" ? "the first" : "the highest"} ${points.length} of ${total} ${spec.type === "histogram" ? "thresholds" : "entries"}. ` : ""}Bars share a zero baseline. Exact values are shown alongside each label.</p><div class="chart-bars" role="list" aria-label="${escape(spec.title)}">${points.map((point,index) => {
      const tag = point.keys.length ? "button" : "div", left = Math.min(zero, (point.value - min) / span * 100), width = Math.abs(point.value) / span * 100;
      return `<div role="listitem"><${tag} class="bar-row" data-bar-index="${index}"${tag === "button" ? ' aria-pressed="false"' : ""}><span class="bar-label">${escape(point.label)}</span><span class="bar-track" aria-hidden="true"><span class="bar-zero" style="left:${zero}%"></span><span class="bar-fill${point.value < 0 ? " negative" : ""}" style="left:${left}%;width:${width}%"></span></span><span class="bar-value">${escape(formatValue(point.value))}</span></${tag}></div>`;
    }).join("")}</div>`;
    body.querySelector(".chart-bars").addEventListener("click", event => {
      const button = event.target.closest("button.bar-row"); if (button) selectEntities(scope, points[Number(button.dataset.barIndex)].keys);
    });
    if (scope) state.explorers.push({scope, update: () => {
      const selected = selectedEntities(scope);
      body.querySelectorAll("button.bar-row").forEach(button => {
        const keys = points[Number(button.dataset.barIndex)].keys;
        button.setAttribute("aria-pressed", String(keys.every(key => selected.has(key))));
        button.classList.toggle("contains-selection", keys.some(key => selected.has(key)));
      });
    }});
  }

  function numericSeries(data, spec, limit = 200) {
    const rows = rowsFrom(data).slice(0, spec.limit || limit);
    const xField = spec.encodings?.x || spec.encodings?.time;
    const yField = spec.encodings?.y || spec.encodings?.value;
    return rows.map((row, index) => {
      const candidate = pick(row, yField) ?? row.value ?? Object.values(row).find(value => typeof value === "number");
      const value = Number(candidate);
      return {
        label: String(pick(row, xField) ?? row.key ?? row.vertex ?? row.index ?? index),
        value,
      };
    }).filter(point => Number.isFinite(point.value));
  }

  function renderLine(body, data, spec) {
    const points = numericSeries(data, spec);
    if (!points.length) { renderTable(body, data, spec.limit || 100); return; }
    const width=620,height=240,pad=38,min=Math.min(...points.map(point=>point.value)),max=Math.max(...points.map(point=>point.value)),span=max-min||1;
    const positioned=points.map((point,index)=>({...point,x:pad+(points.length===1?0.5:index/(points.length-1))*(width-pad*2),y:height-pad-(point.value-min)/span*(height-pad*2)}));
    body.innerHTML=`<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(spec.title)}"><line class="axis" x1="${pad}" y1="${height-pad}" x2="${width-pad}" y2="${height-pad}"/><polyline class="line-series" points="${positioned.map(point=>`${point.x},${point.y}`).join(" ")}"/>${positioned.map(point=>`<circle class="line-point" cx="${point.x}" cy="${point.y}" r="4"><title>${escape(point.label)}: ${escape(point.value)}</title></circle>`).join("")}<text x="4" y="${pad}">${escape(max)}</text><text x="4" y="${height-pad}">${escape(min)}</text></svg>`;
  }

  function renderTimeline(body, data, spec) {
    if (Array.isArray(data) && data.some(row => Number.isFinite(row.timestamp))) {
      const available = [...new Set(data.map(row => row.sequence))], sequences = available.slice(0, Math.min(spec.limit || 8, 8));
      const visible = new Set(sequences), events = data.filter(row => visible.has(row.sequence));
      const minimum = Math.min(...events.map(row => row.timestamp)), maximum = Math.max(...events.map(row => row.timestamp));
      const width = 660, pad = 75, height = Math.max(160, sequences.length * 55 + 75);
      const x = time => pad + (time - minimum) / (maximum - minimum || 1) * (width - pad - 40);
      body.innerHTML = `<svg class="chart timeline-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(spec.title)}">${sequences.map((id,index) => {
        const y = 38 + index * 55;
        return `<text x="5" y="${y+4}">Match ${escape(id)}</text><line class="timeline-track" x1="${pad}" y1="${y}" x2="${width-30}" y2="${y}"/>${events.filter(row => row.sequence === id).map(row => `<g class="matched-event" data-event-id="${escape(row.id)}"><circle class="timeline-event" cx="${x(row.timestamp)}" cy="${y}" r="6"><title>${escape(row.source_label)} → ${escape(row.target_label)} · ${escape(row.timestamp)}</title></circle><text x="${x(row.timestamp)}" y="${y-14}" text-anchor="middle">${escape(row.order)}</text></g>`).join("")}`;
      }).join("")}<line class="axis" x1="${pad}" y1="${height-37}" x2="${width-40}" y2="${height-37}"/><text x="${pad}" y="${height-17}">${escape(minimum)}</text><text x="${width-40}" y="${height-17}" text-anchor="end">${escape(maximum)}</text></svg>`;
      const svg = body.querySelector("svg"), scroll = document.createElement("div"); scroll.className = "timeline-scroll"; svg.replaceWith(scroll); scroll.appendChild(svg);
      body.insertAdjacentHTML("afterbegin", `<p class="chart-scope">Showing ${sequences.length} of ${available.length} available sequences, including all available events for each shown sequence. Positions show time; numbers show event order. Hover over a point or inspect the table for names and timestamps. The table contains all ${data.length} available event rows; the same event can belong to multiple matches.</p>`);
      body.insertAdjacentHTML("beforeend", '<details class="timeline-values"><summary>Inspect all event values</summary><div class="event-values"></div></details>');
      renderTable(body.querySelector(".event-values"), [], 50, true, {
        length: data.length, keys: ["Match", "Order", "From", "To", "Timestamp"],
        row: index => ({Match: data[index].sequence, Order: data[index].order, From: data[index].source_label, To: data[index].target_label, Timestamp: data[index].timestamp}),
      }, {title: "Events in the available matches"});
      return;
    }
    const rows=rowsFrom(data).slice(0,spec.limit||30);
    const eventField=spec.encodings?.events||spec.encodings?.edges||"edges_in_temporal_order";
    const sequences=rows.map((row,index)=>{
      const events=pick(row,eventField)??row.edges_in_temporal_order??row.timestamps;
      return {label:String(row.id??row.key??row.index??index),events:Array.isArray(events)?events:[]};
    }).filter(row=>row.events.length);
    if(!sequences.length){renderTable(body,data,spec.limit||100);return;}
    const width=620,pad=65,rowHeight=34,height=Math.max(130,sequences.length*rowHeight+45),maximum=Math.max(...sequences.map(row=>row.events.length),2);
    body.innerHTML=`<svg class="chart timeline-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(spec.title)}">${sequences.map((row,rowIndex)=>{const y=28+rowIndex*rowHeight;return `<text x="5" y="${y+4}">${escape(row.label.slice(0,9))}</text><line class="timeline-track" x1="${pad}" y1="${y}" x2="${width-20}" y2="${y}"/>${row.events.map((event,eventIndex)=>{const x=pad+(eventIndex/(maximum-1))*(width-pad-25);return `<circle class="timeline-event" cx="${x}" cy="${y}" r="5"><title>${escape(formatValue(event))}</title></circle><text x="${x-3}" y="${y-9}">${eventIndex+1}</text>`}).join("")}`}).join("")}</svg>`;
  }

  function renderHeatmap(body, data, spec) {
    let labels=[],columns=[],matrix=[];
    if(Array.isArray(data)&&data.every(row=>Array.isArray(row))){matrix=data;labels=data.map((_,index)=>String(index));columns=(data[0]||[]).map((_,index)=>String(index));}
    else {
      const rows=rowsFrom(data).slice(0,spec.limit||25);
      columns=[...new Set(rows.flatMap(row=>Object.keys(row).filter(key=>Number.isFinite(Number(row[key])))))].slice(0,20);
      labels=rows.map((row,index)=>String(row.key??row.vertex??row.index??index));
      matrix=rows.map(row=>columns.map(column=>Number(row[column])));
    }
    matrix=matrix.slice(0,25).map(row=>row.slice(0,20));labels=labels.slice(0,matrix.length);columns=columns.slice(0,matrix[0]?.length||0);
    const values=matrix.flat().filter(Number.isFinite);
    if(!values.length){renderTable(body,data,spec.limit||100);return;}
    const max=Math.max(...values.map(Math.abs),1),cell=Math.max(13,Math.min(25,500/Math.max(columns.length,1))),left=90,top=32,width=left+columns.length*cell+15,height=top+matrix.length*cell+20;
    body.innerHTML=`<div class="heatmap-wrap"><svg class="chart heatmap-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(spec.title)}">${columns.map((column,index)=>`<text x="${left+index*cell+cell/2}" y="20" text-anchor="middle">${escape(column.slice(0,7))}</text>`).join("")}${matrix.map((row,rowIndex)=>`<text x="${left-7}" y="${top+rowIndex*cell+cell*.7}" text-anchor="end">${escape(labels[rowIndex].slice(0,12))}</text>${row.map((value,columnIndex)=>{const opacity=.12+.82*Math.abs(value)/max;const fill=value<0?`rgba(238,123,45,${opacity})`:`rgba(22,115,75,${opacity})`;return `<rect class="heat-cell" x="${left+columnIndex*cell}" y="${top+rowIndex*cell}" width="${cell-1}" height="${cell-1}" style="fill:${fill}"><title>${escape(labels[rowIndex])} · ${escape(columns[columnIndex])}: ${escape(value)}</title></rect>`}).join("")}`).join("")}</svg></div>`;
  }

  function networkData(data) {
    let rawNodes=[], rawEdges=[];
    const preview = state.graphPreview;
    if (Array.isArray(data)) {
      const first = data[0];
      if (first && typeof first === "object" && !Array.isArray(first) && first.vertex !== undefined) {
        rawNodes = data.map(row => ({
          id: String(row.vertex),
          value: row.community ?? row.core_number ?? row.score ?? row.count,
        }));
      } else {
        const selection = Array.isArray(first)
          ? first
          : [...(first?.vertices || first?.clique || first?.left || []), ...(first?.right || [])];
        rawNodes = selection.map(value => ({id:String(value)}));
      }
      if (first?.edges) rawEdges = first.edges;
    } else if (data && typeof data === "object") rawNodes = Object.entries(data).map(([id,value]) => ({id, value:typeof value === "object" ? JSON.stringify(value) : value}));
    if (preview) {
      const values = new Map(rawNodes.map(node => [String(node.id), node.value]));
      const selected = new Set(rawNodes.map(node => String(node.id)));
      const useSelection = selected.size > 0 && selected.size < preview.vertices.length;
      rawNodes = preview.vertices
        .filter(vertex => !useSelection || selected.has(String(vertex.id)))
        .map(vertex => ({id:String(vertex.id), value:values.get(String(vertex.id))}));
      const nodeIds = new Set(rawNodes.map(node => node.id));
      rawEdges = preview.edges.filter(edge => nodeIds.has(String(edge.source)) && nodeIds.has(String(edge.target)));
    }
    rawNodes = rawNodes.slice(0,120);
    const visible = new Set(rawNodes.map(node => node.id));
    rawEdges = rawEdges.filter(edge => visible.has(String(edge.source??edge[0])) && visible.has(String(edge.target??edge[1])));
    return {nodes:rawNodes,edges:rawEdges};
  }

  function renderNetwork(body, data, spec) {
    if (Array.isArray(data?.nodes)) { renderAnswerNetwork(body, data, spec); return; }
    const {nodes,edges}=networkData(data); if(!nodes.length){renderTable(body,data,spec.limit||100);return;}
    const width=620,height=310,cx=width/2,cy=height/2,r=Math.min(width,height)*.35;
    const positioned=nodes.map((node,i)=>({...node,x:cx+Math.cos(i/nodes.length*Math.PI*2)*r,y:cy+Math.sin(i/nodes.length*Math.PI*2)*r})); const byId=new Map(positioned.map(n=>[String(n.id),n]));
    const palette=["#16734b","#ee7b2d","#3e9b72","#d6a029","#577f69","#b7562e","#57a89a"];
    const color=value=>{const text=String(value??"");let hash=0;for(const character of text)hash=(hash*31+character.charCodeAt(0))>>>0;return palette[hash%palette.length]};
    body.innerHTML=`<div class="network-stage"><svg class="chart" viewBox="0 0 ${width} ${height}"><g class="network-transform">${edges.map(edge=>{const a=byId.get(String(edge.source??edge[0])),b=byId.get(String(edge.target??edge[1]));return a&&b?`<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>`:""}).join("")}${positioned.map(node=>{const radius=spec.encodings?.node_size?6+Math.min(8,Math.abs(Number(node.value))||0):7;const fill=spec.encodings?.node_color?color(node.value):"#16734b";return `<g><circle cx="${node.x}" cy="${node.y}" r="${radius}" style="fill:${fill}"><title>${escape(node.id)}${node.value!==undefined?`: ${escape(node.value)}`:""}</title></circle>${nodes.length<35?`<text x="${node.x+8}" y="${node.y+3}">${escape(node.id.slice(0,12))}</text>`:""}</g>`}).join("")}</g></svg></div>`;
    body.querySelectorAll("circle").forEach(circle=>circle.addEventListener("click",()=>circle.classList.toggle("selected")));
    enablePanZoom(body.querySelector("svg"),body.querySelector(".network-transform"));
  }

  function renderAnswerNetwork(body, data, spec) {
    if (!window.cytoscape) { renderTable(body, data.nodes, 1000); return; }
    const scope = spec.encodings?.answer_ref || spec.data_ref.replace(/\.network$/, "");
    const answer = resolvePath({answer: state.result?.answer}, scope);
    const key = value => JSON.stringify(value), palette = ["#246a73", "#d17b36", "#7765a6", "#36845b", "#bf5275", "#5576b4", "#898039"];
    let colorDomain = new Map();
    const color = value => palette[(colorDomain.get(String(value ?? "Unknown")) || 0) % palette.length];
    const attributes = [...new Set(data.nodes.flatMap(node => Object.keys(node.attributes || {})))];
    const colorFields = ["community", "type", ...attributes.map(name => `attributes.${name}`)].filter(field => data.nodes.some(node => pick(node, field) != null));
    const numericFields = ["score", "core_number", ...attributes.map(name => `attributes.${name}`)].filter(field => data.nodes.some(node => typeof pick(node, field) === "number"));
    body.innerHTML = `<div class="network-controls"><label>Show<select class="group-selector"><option value="all">Answer overview</option>${(data.groups || []).map(group => `<option value="${escape(key(group.id))}">${escape(group.label)} · ${group.size} members</option>`).join("")}</select></label><label>Color by<select class="color-selector">${colorFields.length ? colorFields.map(field => `<option value="${escape(field)}">${escape(field === "community" ? "Detected group" : field.replace("attributes.", ""))}</option>`).join("") : '<option value="">Entity</option>'}</select></label><label>Size by<select class="size-selector"><option value="">Equal size</option>${numericFields.map(field => `<option value="${escape(field)}">${escape(field.replace("attributes.", ""))}</option>`).join("")}</select></label><button class="secondary-button fit-network">Fit</button></div><div class="answer-network" role="img" aria-label="${escape(spec.title)}"></div><div class="network-legend"></div><div class="entity-details" aria-live="polite">Select an entity or connection to inspect its original attributes.</div><details class="network-accessible"><summary>Entities shown</summary><ul></ul></details>`;
    body.querySelector(".network-controls").insertAdjacentHTML("beforeend", '<label class="network-search-label">Find in network preview<input type="search" class="network-search" placeholder="Name, ID or attribute…"></label><button class="secondary-button focus-selection" disabled>Focus selection</button><button class="secondary-button reset-network">Reset view</button>');
    body.querySelector(".network-legend").insertAdjacentHTML("afterend", '<p class="network-selection" role="status">Select a name in a table or in the network to highlight it across views.</p>');
    const container = body.querySelector(".answer-network");
    if (colorFields.includes(spec.encodings?.node_color)) body.querySelector(".color-selector").value = spec.encodings.node_color;
    if (data.default_group !== null && data.default_group !== undefined) body.querySelector(".group-selector").value = key(data.default_group);
    let cy;
    const showDetails = original => {
      body.querySelector(".entity-details").innerHTML = `<strong>${escape(original.label ?? original.id)}</strong><dl>${Object.entries(original).filter(([field]) => !["key", "source_key", "target_key", "groups"].includes(field)).map(([field,value]) => `<dt>${escape(field)}</dt><dd>${escape(field === "id" && typeof value === "number" && !Number.isSafeInteger(value) && original.key ? original.key : formatValue(value))}</dd>`).join("")}</dl>`;
      if (original.groups?.length) body.querySelector(".entity-details dl").insertAdjacentHTML("beforeend", `<dt>Returned groups</dt><dd>${original.groups.map(id => escape(data.groups?.find(group => key(group.id) === key(id))?.label ?? id)).join(", ")}</dd>`);
    };
    const updateSelection = () => {
      if (!cy) return;
      const selected = selectedEntities(scope);
      const outsideGroup = data.nodes.some(node => selected.has(node.key) && !cy.getElementById(node.key).length);
      if (outsideGroup) { body.querySelector(".group-selector").value = "all"; draw(); return; }
      const nodes = cy.nodes().filter(node => selected.has(node.id()));
      cy.batch(() => {
        cy.elements().unselect().removeClass("selection-muted");
        if (selected.size) {
          cy.elements().addClass("selection-muted");
          nodes.closedNeighborhood().union(nodes.parents()).removeClass("selection-muted");
          nodes.select();
        }
      });
      body.querySelector(".focus-selection").disabled = !nodes.length;
      const missing = selected.size - nodes.length;
      body.querySelector(".network-selection").textContent = selected.size
        ? `${selected.size} selected · ${nodes.length} in the network preview.${missing ? ` ${missing} outside this preview; inspect their table rows and original attributes below.` : " Use Focus selection to zoom to their nearby connections."}`
        : "Select a name in a table or in the network to highlight it across views.";
      body.querySelectorAll(".network-entity").forEach(button => button.setAttribute("aria-pressed", String(selected.has(button.dataset.nodeId))));
      const original = (answer?.rows || data.nodes).find(node => selected.has(node.key));
      if (original) showDetails(original);
      else body.querySelector(".entity-details").textContent = "Select an entity or connection to inspect its original attributes.";
    };
    const draw = () => {
      if (cy) { cy.destroy(); state.networks = state.networks.filter(value => value !== cy); }
      const group = body.querySelector(".group-selector").value, colorField = body.querySelector(".color-selector").value, sizeField = body.querySelector(".size-selector").value;
      colorDomain = new Map([...new Set(data.nodes.map(node => String(pick(node, colorField) ?? "Unknown")))].sort().map((value, index) => [value, index]));
      const nodes = data.nodes.filter(node => group === "all" || (node.groups || []).some(value => key(value) === group));
      const ids = new Set(nodes.map(node => node.key)), edges = data.edges.filter(edge => ids.has(edge.source_key) && ids.has(edge.target_key));
      const maxSize = Math.max(1, ...nodes.map(node => Math.abs(Number(pick(node, sizeField))) || 0));
      const grouped = group === "all" && data.groups?.length > 1 && data.groups.length <= 12 && nodes.every(node => node.groups?.length === 1);
      const groups = grouped ? data.groups.filter(item => nodes.some(node => node.groups.includes(item.id))) : [];
      // Keep disjoint answer groups compact and labels readable. A free-force
      // compound layout can stretch both clusters around one bridging edge.
      const positions = new Map();
      if (grouped) {
        const radius = Math.max(60, Math.min(220, Math.max(...groups.map(item => item.size)) * 12));
        const spacing = radius * 2 + 150, columns = Math.min(3, Math.ceil(Math.sqrt(groups.length)));
        groups.forEach((item, groupIndex) => {
          const members = nodes.filter(node => node.groups.includes(item.id));
          members.forEach((node, index) => {
            const angle = -Math.PI / 2 + index * Math.PI * 2 / members.length;
            positions.set(node.key, {x: (groupIndex % columns) * spacing + Math.cos(angle) * radius, y: Math.floor(groupIndex / columns) * spacing + Math.sin(angle) * radius});
          });
        });
      }
      const types = [...new Set(nodes.map(node => node.type || "Entity"))].sort();
      const shapes = ["ellipse", "round-rectangle", "diamond", "hexagon"];
      const elements = [
        ...groups.map(item => ({data: {id: `group:${key(item.id)}`, label: item.label}, classes: "answer-group"})),
        ...nodes.map((node,index) => ({data: {id: node.key, label: node.label, original: node,
          color: color(pick(node, colorField)), shape: shapes[types.indexOf(node.type || "Entity") % shapes.length], size: sizeField ? 22 + 24 * Math.sqrt(Math.abs(Number(pick(node, sizeField))) / maxSize || 0) : 28,
          parent: grouped ? `group:${key(node.groups[0])}` : undefined},
          position: positions.get(node.key) || {x: (index % 8) * 75, y: Math.floor(index / 8) * 75}})),
        ...edges.map((edge,index) => ({data: {id: `edge:${index}`, source: edge.source_key, target: edge.target_key, original: edge,
          width: typeof edge.weight === "number" ? Math.min(5, 1 + Math.log1p(Math.abs(edge.weight))) : 1.6}}))
      ];
      cy = window.cytoscape({container, elements, minZoom: .15, maxZoom: 4,
        style: [
          {selector:"node",style:{"background-color":"data(color)",shape:"data(shape)",width:"data(size)",height:"data(size)",label:"data(label)","font-size":12,"font-family":"system-ui",color:"#203e37","text-valign":"bottom","text-margin-y":8,"text-background-color":"#f8fbf9","text-background-opacity":.9,"text-background-padding":3,"border-width":2,"border-color":"#fff"}},
          {selector:"edge",style:{width:"data(width)","line-color":"#a8bcb3","curve-style":"bezier",opacity:.7}},
          {selector:".answer-group",style:{"background-color":"#edf3ef","background-opacity":.65,"border-width":1,"border-style":"dashed","border-color":"#bdcfc5",padding:28,label:"data(label)","text-valign":"top","text-margin-y":-7,"font-weight":650}},
          {selector:":selected",style:{"border-color":"#a65d1f","border-width":4,"line-color":"#a65d1f"}},
          {selector:".selection-muted",style:{opacity:.25}}
        ], layout:grouped ? {name:"preset",fit:true,padding:40} : {name:"cose",animate:false,randomize:false,nodeDimensionsIncludeLabels:true,nodeRepulsion:()=>18000,idealEdgeLength:()=>125,componentSpacing:70,padding:32,numIter:500}});
      if (data.layout === "bipartite" && types.length === 2) {
        types.forEach((type,column) => cy.nodes().filter(node => node.data("original")?.type === type).forEach((node,index) => node.position({x:column*270,y:index*90})));
        cy.fit(undefined, 45);
      }
      if (nodes.length <= 40) {
        if (cy.zoom() > 1.5) { cy.zoom(1.5); cy.center(); }
        cy.nodes().filter(node => !!node.data("original")).style("font-size", Math.max(12, 11 / cy.zoom()));
      }
      state.networks.push(cy); container.graphmineNetwork = cy;
      if (data.directed ?? answer?.provenance?.directed) cy.edges().style({"target-arrow-shape":"triangle","target-arrow-color":"#a8bcb3"});
      cy.on("tap", "node, edge", event => {
        const original = event.target.data("original"); if (!original) return;
        selectEntities(scope, event.target.isNode() ? [original.key] : [original.source_key, original.target_key]);
        showDetails(original);
      });
      const legend = [...new Set(nodes.map(node => String(pick(node, colorField) ?? "Unknown")))];
      body.querySelector(".network-legend").innerHTML = `<span>${nodes.length} of ${data.total_nodes ?? data.nodes.length} returned ${escape(data.entity_noun || "entities")} · ${edges.length} of ${data.total_edges ?? data.edges.length} returned connections${data.truncated ? " · limited preview" : ""}</span>` + legend.slice(0,12).map(value => `<span><i style="background:${color(value)}"></i>${escape(colorField === "community" ? data.groups?.find(item => String(item.id) === value)?.label || value : value)}</span>`).join("") + (legend.length > palette.length ? "<span>Some colors repeat; inspect names and attributes to distinguish categories.</span>" : "") + (types.length > 1 ? `<span>Shapes: ${types.map((type,index) => `${escape(shapes[index % shapes.length])} = ${escape(type)}`).join("; ")}</span>` : "");
      if (colorField === "community" && nodes.some(node => node.groups?.length > 1)) body.querySelector(".network-legend").insertAdjacentHTML("beforeend", "<span>Overlapping memberships use the first group's color. Select an entity to see every returned group it belongs to.</span>");
      body.querySelector(".network-accessible ul").innerHTML = nodes.map(node => `<li data-node-id="${escape(node.key)}"><button class="network-entity" data-node-id="${escape(node.key)}" aria-pressed="false">${escape(node.label)}</button>${node.type ? ` · ${escape(node.type)}` : ""}${Object.keys(node.attributes || {}).length ? ` · ${escape(formatValue(node.attributes))}` : ""}</li>`).join("");
      updateSelection();
    };
    body.querySelectorAll("select").forEach(select => select.addEventListener("change", () => {
      if (select.classList.contains("group-selector")) { state.selections.delete(scope); body.querySelector(".network-search").value = ""; }
      draw();
      if (select.classList.contains("group-selector")) selectEntities(scope, []);
    }));
    body.querySelector(".fit-network").addEventListener("click", () => cy?.fit(undefined, 35));
    body.querySelector(".network-search").addEventListener("input", event => {
      const query = event.target.value.trim().toLocaleLowerCase();
      if (query && body.querySelector(".group-selector").value !== "all") { body.querySelector(".group-selector").value = "all"; state.selections.delete(scope); draw(); }
      const matches = query ? data.nodes.filter(node => [node.label, node.id, formatValue(node.attributes)].some(value => String(value).toLocaleLowerCase().includes(query))) : [];
      selectEntities(scope, matches.map(node => node.key));
      body.querySelector(".network-selection").textContent = query ? `${matches.length} matches in the available network preview. Search the tables to include every available answer row.` : "Selection cleared.";
    });
    body.querySelector(".network-accessible ul").addEventListener("click", event => {
      const button = event.target.closest(".network-entity");
      if (button) selectEntities(scope, [button.dataset.nodeId]);
    });
    body.querySelector(".focus-selection").addEventListener("click", () => {
      const nodes = cy.nodes(":selected"); if (nodes.length) cy.fit(nodes.closedNeighborhood().union(nodes.parents()), 45);
    });
    body.querySelector(".reset-network").addEventListener("click", () => {
      body.querySelector(".network-search").value = "";
      body.querySelector(".group-selector").value = "all";
      state.selections.delete(scope); draw(); selectEntities(scope, []);
    });
    // Refit when a results pane becomes visible or changes width. Keeping the
    // old desktop pan after a mobile resize can place every node off screen.
    let dimensions = "";
    const resizeObserver = new ResizeObserver(entries => {
      const {width, height} = entries[0].contentRect, next = `${width}:${height}`;
      if (!cy || cy.destroyed() || !width || !height || dimensions === next) return;
      dimensions = next; cy.resize(); cy.fit(undefined, 35);
      if (cy.zoom() > 1.5) { cy.zoom(1.5); cy.center(); }
    });
    state.explorers.push({scope, update: updateSelection, destroy: () => resizeObserver.disconnect()});
    draw();
    resizeObserver.observe(container);
  }

  function enablePanZoom(svg,group) {
    let scale=1,x=0,y=0,drag=null; const apply=()=>group.setAttribute("transform",`translate(${x} ${y}) scale(${scale})`);
    svg.addEventListener("wheel",event=>{event.preventDefault();scale=Math.min(4,Math.max(.5,scale*(event.deltaY<0?1.12:.89)));apply()},{passive:false});
    svg.addEventListener("pointerdown",event=>{drag={x:event.clientX-x,y:event.clientY-y};svg.setPointerCapture(event.pointerId)});
    svg.addEventListener("pointermove",event=>{if(drag){x=event.clientX-drag.x;y=event.clientY-drag.y;apply()}}); svg.addEventListener("pointerup",()=>drag=null);
  }

  function renderTable(body, data, limit, readable=false, model=null, spec={}) {
    if (!model) {
      const rows = readable && Array.isArray(data) ? data : rowsFrom(data);
      model = {length: rows.length, row: index => rows[index], keys: [...new Set(rows.flatMap(row => Object.keys(row)))].slice(0,15)};
    }
    const keys = model.keys, scope = spec.encodings?.answer_ref;
    if (readable) body.classList.add("readable-table");
    body.innerHTML = `<div class="table-controls"><label>Search all available rows<input type="search" class="viz-filter" placeholder="Name, ID or attribute…"></label><label>Rows per page<select class="page-size"><option>25</option><option selected>50</option><option>100</option></select></label></div><p class="table-status" role="status"></p><div class="table-wrap" tabindex="0" role="region" aria-label="${escape(spec.title || "Result table")}"><table class="data-table"><caption class="sr-only">${escape(spec.title || "Result table")}</caption><thead><tr>${keys.map(key=>`<th scope="col">${escape(key)}</th>`).join("")}</tr></thead><tbody></tbody></table></div><div class="table-pagination"><button class="secondary-button first-page" aria-label="First page">First</button><button class="secondary-button previous-page" aria-label="Previous page">Previous</button><span class="page-label"></span><button class="secondary-button next-page" aria-label="Next page">Next</button><button class="secondary-button last-page" aria-label="Last page">Last</button></div>`;
    let indices = null, page = 0, pageSize = 50, revision = 0, searching = false;
    const count = () => indices === null ? model.length : indices.length;
    const sourceIndex = index => indices === null ? index : indices[index];
    const draw = () => {
      const total = count(), pages = Math.max(1, Math.ceil(total / pageSize));
      page = Math.min(page, pages - 1);
      const start = page * pageSize, end = Math.min(total, start + pageSize), selected = selectedEntities(scope);
      body.querySelector(".table-status").textContent = searching ? `Searching ${formatValue(model.length)} available rows…` : `${total ? `Rows ${formatValue(start + 1)}–${formatValue(end)}` : "No matching rows"} of ${formatValue(total)}${indices !== null ? ` matches across ${formatValue(model.length)} available rows` : " available rows"}.${selected.size ? ` ${formatValue(selected.size)} entities selected across views.` : ""}${model.notice ? ` ${model.notice}` : ""}`;
      body.querySelector("tbody").innerHTML = Array.from({length: end - start}, (_, offset) => {
        const index = sourceIndex(start + offset), row = model.row(index), entity = model.entity?.(index), active = entity !== undefined && selected.has(entity);
        return `<tr${active ? ' class="selected-row"' : ""}>${keys.map((key, column) => `<td title="${escape(formatValue(row[key]))}">${entity !== undefined && (key === "Name" || !keys.includes("Name") && column === 0) ? `<button class="table-entity" data-row-index="${index}" aria-pressed="${active}">${escape(formatValue(row[key]))}</button>` : escape(formatValue(row[key]))}</td>`).join("")}</tr>`;
      }).join("") || `<tr><td colspan="${Math.max(keys.length, 1)}">No rows match the current search.</td></tr>`;
      body.querySelector(".page-label").textContent = `Page ${page + 1} of ${pages}`;
      for (const name of ["first", "previous"]) body.querySelector(`.${name}-page`).disabled = page === 0 || searching;
      for (const name of ["next", "last"]) body.querySelector(`.${name}-page`).disabled = page >= pages - 1 || searching;
    };
    const search = () => {
      const current = ++revision, query = body.querySelector("input").value.trim().toLocaleLowerCase();
      page = 0;
      if (!query && !spec.filters?.length) { indices = null; searching = false; draw(); return; }
      indices = []; searching = true; draw();
      let cursor = 0;
      const scan = () => {
        if (current !== revision || !body.isConnected) return;
        const end = Math.min(model.length, cursor + 1000);
        for (; cursor < end; cursor++) {
          const row = model.row(cursor);
          if (applyViewFilters([row], spec.filters || []).length && (!query || Object.values(row).some(value => formatValue(value).toLocaleLowerCase().includes(query)))) indices.push(cursor);
        }
        if (cursor < model.length) setTimeout(scan, 0);
        else { searching = false; draw(); }
      };
      scan();
    };
    body.querySelector("input").addEventListener("input", search);
    body.querySelector(".page-size").addEventListener("change", event => { pageSize = Number(event.target.value); page = 0; draw(); });
    for (const [name, destination] of [["first", () => 0], ["previous", () => Math.max(0, page - 1)], ["next", () => page + 1], ["last", () => Math.max(0, Math.ceil(count() / pageSize) - 1)]]) {
      body.querySelector(`.${name}-page`).addEventListener("click", () => { page = destination(); draw(); body.querySelector(".table-wrap").scrollTop = 0; });
    }
    body.querySelector("tbody").addEventListener("click", event => {
      const button = event.target.closest(".table-entity");
      if (!button) return;
      const index = Number(button.dataset.rowIndex);
      selectEntities(scope, [model.entity(index)]);
      // Redrawing a linked table must not lose the keyboard user's focus.
      body.querySelector(`.table-entity[data-row-index="${index}"]`)?.focus({preventScroll: true});
    });
    state.explorers.push({scope, update: draw, destroy: () => { revision++; }});
    search();
  }

  function formatValue(value){if(value===null||value===undefined)return "—";if(typeof value==="object")return JSON.stringify(value);if(typeof value==="number")return Number.isInteger(value)?String(value):value.toLocaleString(undefined,{maximumSignificantDigits:6});return String(value)}

  $("#chat-form").addEventListener("submit", event => { event.preventDefault(); const input=$("#chat-input"),message=input.value.trim(); if(message && !state.busy){input.value="";sendChat(message);} });
  $("#chat-input").addEventListener("keydown", event => { if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();$("#chat-form").requestSubmit();} });
  $("#file-input").addEventListener("change", event => upload(event.target.files));
  const drop=$("#drop-zone"); ["dragenter","dragover"].forEach(name=>drop.addEventListener(name,event=>{event.preventDefault();drop.classList.add("dragging")})); ["dragleave","drop"].forEach(name=>drop.addEventListener(name,event=>{event.preventDefault();drop.classList.remove("dragging")})); drop.addEventListener("drop",event=>upload(event.dataTransfer.files));
  $("#new-session").addEventListener("click",()=>{window.location.hash="";});
  $("#refresh-sessions").addEventListener("click", () => loadSessions().catch(error => toast(error.message, true)));
  $("#back-to-chat").addEventListener("click", () => navigate("chat"));
  $("#result-select").addEventListener("change", event => {if(event.target.value) window.location.hash = `session/${state.session.id}/results/${event.target.value}`;});
  $("#feedback-button").addEventListener("click", () => openFeedback());
  $("#result-feedback").addEventListener("click", () => openFeedback({result_id:state.result?.id, job_id:state.result?.job_id, turn_id:state.resultJob?.turn_id}));
  $("#close-feedback").addEventListener("click", () => $("#feedback-dialog").close());
  $("#feedback-form").addEventListener("submit", saveFeedback);
  $("#commands-button").addEventListener("click", () => sendChat("/help"));
  $("#export-session").addEventListener("click", () => download(`/api/sessions/${state.session.id}/history/archive`, `${state.session.id}.zip`).catch(error => toast(error.message,true)));
  $("#export-feedback").addEventListener("click", () => download(`/api/sessions/${state.session.id}/feedback/export`, `${state.session.id}-feedback.jsonl`).catch(error => toast(error.message,true)));
  $("#download-report").addEventListener("click", () => download(`/api/results/${state.result.id}/report`, `${state.result.id}.html`).catch(error => toast(error.message,true)));
  $("#raw-toggle").addEventListener("click",()=>$("#raw-result").classList.toggle("hidden"));
  $("#settings-button").addEventListener("click",()=>{$("#api-base").value=state.base;$("#api-token").value=state.token;$("#settings-dialog").showModal()});
  $("#save-settings").addEventListener("click",()=>{state.base=$("#api-base").value.trim().replace(/\/$/,"");state.token=$("#api-token").value;localStorage.setItem("graphmine.apiBase",state.base);localStorage.setItem("graphmine.apiToken",state.token);resetWorkspace();setTimeout(async()=>{await loadDomains();await routeLocation();},0)});

  const report = $("#graphmine-report");
  if (report) {
    state.result = JSON.parse(report.textContent);
    state.page = "results";
    $("#domain-view").classList.add("hidden"); $("#workspace-view").classList.add("hidden"); $("#results-view").classList.remove("hidden");
    $("#settings-button").classList.add("hidden");
    document.querySelector(".result-tools").classList.add("hidden"); document.querySelector(".result-picker").classList.add("hidden");
    $("#model-version").textContent = "Saved report";
    $("#results-session-title").textContent = state.result.answer?.question || "Saved answer";
    setStatus("Offline report · no server connection", "ready");
    renderResult();
  } else {
    window.addEventListener("hashchange", routeLocation);
    loadDomains().then(() => {if(window.location.hash) routeLocation();});
  }
})();
