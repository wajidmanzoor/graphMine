(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const stored = name => { try { return localStorage.getItem(name) || ""; } catch (_) { return ""; } };
  const state = {
    base: stored("graphmine.apiBase"),
    token: stored("graphmine.apiToken"),
    domains: [], session: null, files: [], graphId: null,
    result: null, graphPreview: null, socket: null, lastEvent: 0,
    networks: [], page: "chat", savedResults: [], activity: new Map(),
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
    $("#model-version").title = `Analysis selection: ${report.deployment?.routing_model || report.llm.model}\nAnswers: ${report.llm.model}`;
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

  async function sendChat(message) {
    if (!state.session || state.busy) return;
    const sessionId = state.session.id;
    state.busy = true;
    addMessage("user", message); $("#send-button").disabled = true;
    try {
      const response = await api(`/api/sessions/${state.session.id}/chat`, {method:"POST", body:JSON.stringify({message, graph_id:state.graphId, result_id:state.result?.id || null, mode:"auto", execute:$("#execute-toggle").checked, ...($("#projection-toggle").checked ? {allow_directed_projection:true} : {})})});
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

  function renderResult() {
    if (!state.result) return;
    const result = state.result, interpretation = result.interpretation;
    $("#insight-column").classList.remove("empty"); $("#empty-insights").classList.add("hidden"); $("#result-content").classList.remove("hidden");
    $("#result-title").textContent = interpretation?.summary || "Analysis result";
    $("#raw-result").textContent = JSON.stringify({result: result.payload, diagnostics: result.answer?.diagnostics}, null, 2);
    if (interpretation) {
      const additional = interpretation.findings.filter(value => value !== interpretation.summary);
      $("#interpretation").innerHTML = `${listSection("What this means", interpretation.limitations)}<details class="answer-evidence"><summary>Question and supporting evidence</summary><p>${escape(result.answer?.question || "")}</p>${listSection("Computed findings", additional)}${listSection("Possible implications · model suggestions, not verified findings", interpretation.hypotheses)}</details>`;
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
            navigate("chat"); sendChat(action.request);
          });
        }
        actions.appendChild(button);
      });
      if (actions.children.length > 1) $("#visualizations").appendChild(actions);
    } else {
      $("#interpretation").innerHTML = "<p>The computation completed; interpretation is not yet available.</p>";
    }
  }

  function listSection(title, items) {
    return items?.length ? `<h3>${escape(title)}</h3><ul>${items.map(item => `<li>${escape(item)}</li>`).join("")}</ul>` : "";
  }

  function renderVisualization(spec, data) {
    data = applyViewFilters(data, spec.filters || []);
    const card = document.createElement("section"); card.className = "viz-card";
    card.dataset.viewId = spec.id;
    const previewNote = spec.type === "network" && state.graphPreview && (state.graphPreview.vertices_truncated || state.graphPreview.edges_truncated)
      ? ` Preview shows ${state.graphPreview.vertices.length}/${state.graphPreview.vertex_count} vertices and ${state.graphPreview.edges.length}/${state.graphPreview.edge_count} edges.` : "";
    card.innerHTML = `<div class="viz-head"><div><h3>${escape(spec.title)}</h3><p>${escape((spec.description || "") + previewNote)}</p></div><span class="viz-kind">${escape(spec.type)}</span></div><div class="viz-body"></div>`;
    const body = card.querySelector(".viz-body");
    $("#visualizations").appendChild(card);
    if (spec.type === "metric_cards") renderMetrics(body, data, spec.encodings);
    else if (["bar", "histogram"].includes(spec.type)) renderBars(body, data, spec);
    else if (spec.type === "line") renderLine(body, data, spec);
    else if (spec.type === "timeline") renderTimeline(body, data, spec);
    else if (spec.type === "heatmap") renderHeatmap(body, data, spec);
    else if (spec.type === "network") renderNetwork(body, data, spec);
    else renderTable(body, data, spec.limit || 1000, spec.data_ref.includes(".tables."));
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
    const values = entries.length ? entries : Object.entries(data || {}).filter(([,value]) => ["number","string","boolean"].includes(typeof value)).slice(0,12);
    body.innerHTML = `<div class="metric-grid">${values.map(([label,value]) => `<div class="metric"><strong>${escape(formatValue(value))}</strong><span>${escape(label.replaceAll("_"," "))}</span></div>`).join("")}</div>`;
  }

  function renderBars(body, data, spec) {
    const rows = rowsFrom(data).slice(0, spec.limit || 80), category = spec.encodings?.category || spec.encodings?.x, valueField = spec.encodings?.value || spec.encodings?.y;
    let points = rows.map((row,index) => {
      const numeric = Number(pick(row,valueField) ?? row.value ?? Object.values(row).find(value => typeof value === "number") ?? 0);
      return {label:String(pick(row,category) ?? row.key ?? row.vertex ?? row.index ?? index), value:Number.isFinite(numeric) ? numeric : 0};
    });
    if (spec.type === "histogram") {
      const counts = new Map(); points.forEach(point => counts.set(point.value, (counts.get(point.value)||0)+1)); points = [...counts].map(([label,value]) => ({label:String(label),value})).sort((a,b)=>Number(a.label)-Number(b.label));
    }
    if (!points.length) { body.textContent = "No values to plot."; return; }
    const width=620,height=230,pad=35,max=Math.max(...points.map(p=>Math.abs(p.value)),1),barWidth=Math.max(3,(width-pad*2)/points.length-3);
    body.innerHTML = `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(spec.title)}"><line class="axis" x1="${pad}" y1="${height-pad}" x2="${width-pad/2}" y2="${height-pad}"/>${points.map((point,index)=>{const h=Math.abs(point.value)/max*(height-pad*2);const x=pad+index*((width-pad*2)/points.length);return `<rect class="bar" x="${x}" y="${height-pad-h}" width="${barWidth}" height="${h}"><title>${escape(point.label)}: ${escape(point.value)}</title></rect>${points.length<18?`<text x="${x}" y="${height-17}" transform="rotate(30 ${x} ${height-17})">${escape(point.label.slice(0,10))}</text>`:""}`}).join("")}</svg>`;
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
      const events = data.slice(0, spec.limit || 300), sequences = [...new Set(events.map(row => row.sequence))];
      const minimum = Math.min(...events.map(row => row.timestamp)), maximum = Math.max(...events.map(row => row.timestamp));
      const width = 660, pad = 75, height = Math.max(160, sequences.length * 75 + 65);
      const x = time => pad + (time - minimum) / (maximum - minimum || 1) * (width - pad - 40);
      body.innerHTML = `<svg class="chart timeline-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(spec.title)}">${sequences.map((id,index) => {
        const y = 38 + index * 75;
        return `<text x="5" y="${y+4}">Match ${escape(id)}</text><line class="timeline-track" x1="${pad}" y1="${y}" x2="${width-30}" y2="${y}"/>${events.filter(row => row.sequence === id).map(row => `<g class="matched-event" data-event-id="${escape(row.id)}"><circle class="timeline-event" cx="${x(row.timestamp)}" cy="${y}" r="6"><title>${escape(row.source_label)} → ${escape(row.target_label)} · ${escape(row.timestamp)}</title></circle><text x="${x(row.timestamp)}" y="${y+23}" text-anchor="middle">${escape(row.timestamp)}</text><text x="${x(row.timestamp)}" y="${y-14}" text-anchor="middle">${escape(row.source_label)} → ${escape(row.target_label)}</text></g>`).join("")}`;
      }).join("")}</svg>`;
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
    const key = value => JSON.stringify(value), palette = ["#246a73", "#d17b36", "#7765a6", "#36845b", "#bf5275", "#5576b4", "#898039"];
    const color = value => { let hash = 0; for (const c of String(value ?? "Unknown")) hash = (hash * 31 + c.charCodeAt(0)) >>> 0; return palette[hash % palette.length]; };
    const attributes = [...new Set(data.nodes.flatMap(node => Object.keys(node.attributes || {})))];
    const colorFields = ["community", "type", ...attributes.map(name => `attributes.${name}`)].filter(field => data.nodes.some(node => pick(node, field) != null));
    const numericFields = ["score", "core_number", ...attributes.map(name => `attributes.${name}`)].filter(field => data.nodes.some(node => typeof pick(node, field) === "number"));
    body.innerHTML = `<div class="network-controls"><label>Show<select class="group-selector"><option value="all">Answer overview</option>${(data.groups || []).map(group => `<option value="${escape(key(group.id))}">${escape(group.label)} · ${group.size} members</option>`).join("")}</select></label><label>Color by<select class="color-selector">${colorFields.length ? colorFields.map(field => `<option value="${escape(field)}">${escape(field === "community" ? "Detected group" : field.replace("attributes.", ""))}</option>`).join("") : '<option value="">Entity</option>'}</select></label><label>Size by<select class="size-selector"><option value="">Equal size</option>${numericFields.map(field => `<option value="${escape(field)}">${escape(field.replace("attributes.", ""))}</option>`).join("")}</select></label><button class="secondary-button fit-network">Fit</button></div><div class="answer-network" role="img" aria-label="${escape(spec.title)}"></div><div class="network-legend"></div><div class="entity-details" aria-live="polite">Select an entity or connection to inspect its original attributes.</div><details class="network-accessible"><summary>Entities shown</summary><ul></ul></details>`;
    const container = body.querySelector(".answer-network");
    if (colorFields.includes(spec.encodings?.node_color)) body.querySelector(".color-selector").value = spec.encodings.node_color;
    if (data.default_group !== null && data.default_group !== undefined) body.querySelector(".group-selector").value = key(data.default_group);
    let cy;
    const draw = () => {
      if (cy) { cy.destroy(); state.networks = state.networks.filter(value => value !== cy); }
      const group = body.querySelector(".group-selector").value, colorField = body.querySelector(".color-selector").value, sizeField = body.querySelector(".size-selector").value;
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
          {selector:":selected",style:{"border-color":"#e48b3e","border-width":4,"line-color":"#e48b3e"}}
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
      if (state.result?.answer?.provenance?.directed) cy.edges().style({"target-arrow-shape":"triangle","target-arrow-color":"#a8bcb3"});
      cy.on("tap", "node, edge", event => {
        const original = event.target.data("original"); if (!original) return;
        body.querySelector(".entity-details").innerHTML = `<strong>${escape(original.label || original.id)}</strong><dl>${Object.entries(original).filter(([field]) => !["key", "source_key", "target_key", "groups"].includes(field)).map(([field,value]) => `<dt>${escape(field)}</dt><dd>${escape(formatValue(value))}</dd>`).join("")}</dl>`;
      });
      const legend = [...new Set(nodes.map(node => String(pick(node, colorField) ?? "Unknown")))];
      body.querySelector(".network-legend").innerHTML = `<span>${nodes.length} ${escape(data.entity_noun || "entities")} · ${edges.length} connections${data.truncated ? " · limited view" : ""}</span>` + legend.slice(0,12).map(value => `<span><i style="background:${color(value)}"></i>${escape(colorField === "community" ? data.groups?.find(item => String(item.id) === value)?.label || value : value)}</span>`).join("") + (types.length > 1 ? `<span>Shapes: ${types.map((type,index) => `${escape(shapes[index % shapes.length])} = ${escape(type)}`).join("; ")}</span>` : "");
      body.querySelector(".network-accessible ul").innerHTML = nodes.map(node => `<li data-node-id="${escape(node.key)}">${escape(node.label)}${node.type ? ` · ${escape(node.type)}` : ""}${Object.keys(node.attributes || {}).length ? ` · ${escape(formatValue(node.attributes))}` : ""}</li>`).join("");
    };
    body.querySelectorAll("select").forEach(select => select.addEventListener("change", draw));
    body.querySelector(".fit-network").addEventListener("click", () => cy?.fit(undefined, 35));
    draw();
  }

  function enablePanZoom(svg,group) {
    let scale=1,x=0,y=0,drag=null; const apply=()=>group.setAttribute("transform",`translate(${x} ${y}) scale(${scale})`);
    svg.addEventListener("wheel",event=>{event.preventDefault();scale=Math.min(4,Math.max(.5,scale*(event.deltaY<0?1.12:.89)));apply()},{passive:false});
    svg.addEventListener("pointerdown",event=>{drag={x:event.clientX-x,y:event.clientY-y};svg.setPointerCapture(event.pointerId)});
    svg.addEventListener("pointermove",event=>{if(drag){x=event.clientX-drag.x;y=event.clientY-drag.y;apply()}}); svg.addEventListener("pointerup",()=>drag=null);
  }

  function renderTable(body, data, limit, readable=false) {
    const rows=(readable && Array.isArray(data) ? data : rowsFrom(data)).slice(0,limit), keys=[...new Set(rows.flatMap(row=>Object.keys(row)))].slice(0,15);
    if (readable) body.classList.add("readable-table");
    body.innerHTML=`<input class="viz-filter" placeholder="Filter rows…"><div class="table-wrap"><table class="data-table"><thead><tr>${keys.map(key=>`<th>${escape(key)}</th>`).join("")}</tr></thead><tbody>${tableRows(rows,keys)}</tbody></table></div>`;
    body.querySelector("input").addEventListener("input",event=>{const match=event.target.value.toLowerCase();body.querySelector("tbody").innerHTML=tableRows(rows.filter(row=>JSON.stringify(row).toLowerCase().includes(match)),keys)});
  }

  function tableRows(rows,keys){return rows.map(row=>`<tr>${keys.map(key=>`<td title="${escape(formatValue(row[key]))}">${escape(formatValue(row[key]))}</td>`).join("")}</tr>`).join("")}
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
