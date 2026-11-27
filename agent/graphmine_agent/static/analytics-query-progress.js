"use strict";
window.GraphMineQueryProgress = ({api, W, node: makeNode, container, prefix = ""}) => {
  const node = (tag, attrs = {}, text) => makeNode(tag, {...attrs, ...(attrs.id ? {id: prefix + attrs.id} : {})}, text);
  const request = window.GraphMineClient(api, W);
  const section = node("section", {class: "query-progress", "aria-label": "Query progress", hidden: true});
  const monitor = node("div", {class: "database-job-monitor", hidden: true});
  const status = node("p", {id: "database-job-status", role: "status"});
  const progress = node("progress", {"aria-label": "Query progress"});
  const hint = node("p", {class: "source-hint"}, "Keep this view open to receive the result.");
  const cancel = node("button", {id: "cancel-database-job", type: "button", class: "quiet"}, "Cancel query");
  const refresh = node("button", {id: "refresh-database-job", type: "button", class: "quiet"}, "Refresh status");
  const actions = node("div", {class: "database-job-actions"}); actions.append(cancel, refresh);
  const synchronization = node("section", {id: "database-sync-summary", class: "database-sync-summary", hidden: true, "aria-label": "Synchronization changes"});
  monitor.append(status, progress, actions, hint, synchronization);
  section.append(monitor); container.append(section);
  const semantic = node("div", {class: "semantic-progress", hidden: true});
  monitor.append(semantic);
  let source = null, generation = 0, controller = null, timer = null;
  let active = null, pending = null, failures = 0, inFlight = false, destroyed = false;
  const stages = {queued: "Waiting for a database worker", connecting: "Connecting", validating: "Validating the query", reading: "Reading query rows", hydrating: "Loading relationship endpoints", reading_tables: "Reading source tables", comparing: "Comparing the managed graph", writing: "Applying graph changes", committing: "Committing graph changes", saving: "Saving the query snapshot", completed: "Completed"};
  const changeActions = [["created", "Added"], ["updated", "Updated"], ["deleted", "Removed"], ["unchanged", "Unchanged"]];
  function synchronizationSummary(result) {
    if (!result?.changes) return `${result.nodes} nodes · ${result.relationships} relationships`;
    return changeActions.map(([key, label]) => `${((result.changes.nodes?.[key] || 0) + (result.changes.relationships?.[key] || 0)).toLocaleString()} ${label.toLowerCase()}`).join(" · ");
  }
  function renderSynchronization(result) {
    synchronization.replaceChildren(); synchronization.hidden = !result;
    if (!result) return;
    synchronization.append(node("h3", {}, "Synchronization changes"));
    if (result.changes) {
      for (const [kind, label] of [["nodes", "Nodes"], ["relationships", "Relationships"]]) {
        const values = result.changes[kind]; if (!values) continue;
        const counts = node("dl", {class: "sync-change-counts", "data-sync-kind": kind});
        for (const [key, title] of changeActions) {
          const pair = node("div"); pair.append(node("dt", {}, title), node("dd", {"data-sync-change": key}, (values[key] || 0).toLocaleString())); counts.append(pair);
        }
        synchronization.append(node("h4", {}, label), counts);
      }
      if (result.changes.relationships?.recreated) synchronization.append(node("p", {class: "source-hint"}, `${result.changes.relationships.recreated.toLocaleString()} updated relationships changed endpoints or type.`));
    } else synchronization.append(node("p", {}, `${synchronizationSummary(result)}. Individual change counts were not recorded for this job.`));
    if (result.schema_change?.changed) synchronization.append(node("p", {class: "sync-mapping-change"}, `Mapping revision ${result.schema_change.revision} applied. Obsolete mapped fields and labels were reconciled.`));
    if (result.source_read_mode === "complete_snapshot") synchronization.append(node("p", {class: "source-hint"}, "Compared the complete mapped SQL snapshot. Unchanged graph records were left in place."));
    synchronization.append(node("p", {class: "source-hint"}, "Saved analyses keep their original inputs. Preview a new query to use the updated graph."));
    if (result.finished_at || result.mapped_content_sha256) {
      const record = node("details"); record.append(node("summary", {}, "Synchronization record"));
      if (result.finished_at) record.append(node("p", {}, "Completed " + new Date(result.finished_at).toLocaleString()));
      if (result.mapped_content_sha256) record.append(node("p", {class: "sync-content-hash"}, "Mapped content SHA-256: " + result.mapped_content_sha256));
      synchronization.append(record);
    }
  }
  const errorFrom = job => Object.assign(new Error(job.error?.message || (job.status === "cancelled" ? "Database job cancelled." : "Database job did not finish.")), {code: job.error?.code || "database_cancelled", details: job.error?.details});
  // getRandomValues also works on the supported HTTP LAN workspace; randomUUID
  // is restricted to secure contexts in browsers.
  const requestKey = () => Array.from(window.crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, "0")).join("");
  function render(job) {
    renderSynchronization(job.kind === "sync" ? job.synchronization : null);
    active = job; monitor.hidden = section.hidden = false;
    const stage = job.progress || {};
    const isSemantic = job.kind === "semantic";
    semantic.hidden = !isSemantic;
    if (isSemantic) {
      const terminal = ["failed", "cancelled", "interrupted"].includes(job.status);
      const stageNames = {queued: "Waiting for a semantic worker", waiting_for_semantic_slot: "Waiting for a semantic worker", loading: "Loading the saved snapshot", validated: "Checked the query", loaded: "Snapshot loaded", asking_model: "Running simulated model steps", querying: "Matching the query pattern", building_graph: "Building the result", validating: "Validating the complete result", saving: "Saving a new version", completed: "Completed"};
      const usage = job.error?.details?.usage || stage.usage || {};
      semantic.replaceChildren(node("p", {}, stageNames[stage.stage] || stage.stage || job.status),
        node("p", {class: "source-hint"}, "Pattern match counts and completed judgments are not reported by this engine."));
      const stages = node("ol", {class: "semantic-progress-stages", "aria-label": "Refinement stages"});
      const building = ["building_graph", "saving", "completed"].includes(stage.stage) || stage.stage === "validating" && stage.completed != null;
      const checked = ["validated", "loaded", "asking_model", "querying", "building_graph", "saving", "completed"].includes(stage.stage) || building;
      for (const text of [checked ? "Checked query · observed" : "Check query", "Match pattern · separate progress unavailable",
        stage.stage === "asking_model" ? "Model steps · running simulation" : "Model steps · if requested",
        building ? "Build result · " + (job.status === "completed" ? "complete" : "in progress") : "Build result"]) stages.append(node("li", {}, text));
      semantic.append(stages);
      const start = Date.parse(job.started_at || job.created_at), end = Date.parse(job.finished_at || job.updated_at);
      if (Number.isFinite(start)) semantic.append(node("p", {}, `Elapsed: ${Math.max(0, ((["completed", "failed", "cancelled", "interrupted"].includes(job.status) && Number.isFinite(end) ? end : Date.now()) - start) / 1000).toFixed(1)}s`));
      const counts = Object.entries({calls: "Engine calls observed", llm_rows: "Selected inputs", cache_hits: "In-worker cache hits"}).filter(([key]) => usage[key] != null).map(([key, label]) => `${label}: ${usage[key]}`);
      if (counts.length) semantic.append(node("p", {}, counts.join(" · ")));
      if (terminal) semantic.append(node("p", {}, "No new graph was published. Independently retained answers: 0."));
    }
    status.textContent = job.status === "cancelling" ? isSemantic ? "Cancellation requested. Stopping the snapshot worker." : "Cancellation requested. Waiting for the current database problem to return and roll back."
      : ["failed", "interrupted", "cancelled"].includes(job.status) ? errorFrom(job).message
      : stage.message ? stage.message
      : `${job.kind === "sync" ? "Graph refresh" : "Query"}: ${stages[stage.stage] || job.status}${stage.completed != null ? ` · ${stage.completed.toLocaleString()}${stage.total != null ? ` / ${stage.total.toLocaleString()}` : ""}` : ""}`;
    if (stage.total > 0 && stage.completed != null) { progress.max = stage.total; progress.value = stage.completed; }
    else progress.removeAttribute("value");
    progress.hidden = !["queued", "running", "cancelling"].includes(job.status);
    cancel.hidden = refresh.hidden = !["queued", "running", "cancelling"].includes(job.status);
    cancel.textContent = job.kind === "sync" ? "Cancel refresh" : "Cancel query";
    cancel.disabled = !job.cancellable;
    hint.textContent = ["committing", "saving"].includes(stage.stage) && job.status === "running"
      ? "Saving the result; cancellation is no longer available."
      : job.status === "completed" ? "Result ready."
      : ["failed", "cancelled", "interrupted"].includes(job.status) ? "Review the request before running it again."
      : "Keep this view open to receive the result.";
  }
  function stopObservation() {
    generation++; clearTimeout(timer); controller?.abort(); inFlight = false;
    if (pending) { pending.reject(new DOMException("Stopped observing database work.", "AbortError")); pending = null; }
  }
  function finish(current, result, error) {
    if (current !== generation || !pending) return;
    const waiter = pending; pending = null; clearTimeout(timer);
    if (error) waiter.reject(error); else waiter.resolve(result);
  }
  function schedule(current, delay) {
    clearTimeout(timer);
    timer = setTimeout(() => poll(current), delay);
  }
  async function poll(current) {
    if (destroyed || current !== generation || !pending || inFlight) return;
    inFlight = true;
    try {
      const job = await request("get", "/api/database-jobs/{identifier}", {path: {identifier: active.id}, signal: controller.signal});
      if (current !== generation || destroyed) return;
      failures = 0; render(job);
      if (job.status === "completed") {
        const result = await request("get", "/api/database-jobs/{identifier}/result", {path: {identifier: job.id}, signal: controller.signal});
        if (current === generation && !destroyed && job.kind === "sync") renderSynchronization(result);
        finish(current, result); return;
      }
      if (["failed", "interrupted", "cancelled"].includes(job.status)) { finish(current, null, errorFrom(job)); return; }
      schedule(current, document.hidden ? 5000 : 750);
    } catch (error) {
      if (current !== generation || destroyed || error.name === "AbortError") return;
      if (error.status && ![408, 429].includes(error.status) && error.status < 500) {
        status.textContent = error.message; finish(current, null, error); return;
      }
      failures++;
      status.textContent = "Status connection interrupted; reconnecting…";
      schedule(current, window.GraphMineAsync.backoff(failures, error.retryAfter || 0, 750));
    } finally { if (current === generation) inFlight = false; }
  }
  function watch(job) {
    stopObservation(); controller = new AbortController(); failures = 0; render(job);
    const current = generation;
    return new Promise((resolve, reject) => { pending = {resolve, reject}; poll(current); });
  }
  cancel.onclick = async () => {
    if (!active || cancel.disabled) return;
    const current = generation, id = active.id; cancel.disabled = true;
    try {
      const job = await request("delete", "/api/database-jobs/{identifier}", {path: {identifier: id}});
      if (current === generation && !destroyed) { render(job); schedule(current, 0); }
    } catch (error) {
      if (current === generation && !destroyed) { status.textContent = error.message; cancel.disabled = !active.cancellable; schedule(current, 750); }
    }
  };
  const reconcile = () => { if (!document.hidden && pending) schedule(generation, 0); };
  refresh.onclick = reconcile;
  window.addEventListener("online", reconcile); document.addEventListener("visibilitychange", reconcile);
  return {
    async execute(path, body) {
      const response = await api(path, {method: "POST", headers: {Prefer: "respond-async", "Idempotency-Key": requestKey()}, ...(body ? {body: W.stringify(body)} : {})});
      if (destroyed) throw new DOMException("Dialog closed.", "AbortError");
      if (!response.job) { if (response.changes) { monitor.hidden = section.hidden = false; renderSynchronization(response); } return response; }
      return watch(response.job);
    },
    synchronizationSummary,
    setContext(value) { if (value !== source) { stopObservation(); active = null; monitor.hidden = section.hidden = true; renderSynchronization(null); source = value; } },
    destroy() { destroyed = true; stopObservation(); window.removeEventListener("online", reconcile); document.removeEventListener("visibilitychange", reconcile); section.remove(); },
  };
};
