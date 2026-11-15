"use strict";
window.GraphMineDatabaseJobs = ({api, W, node, container, onResume, onError}) => {
  const request = window.GraphMineClient(api, W);
  const section = node("section", {class: "database-jobs", "aria-label": "Database jobs"});
  const monitor = node("div", {class: "database-job-monitor", hidden: true});
  const status = node("p", {id: "database-job-status", role: "status"});
  const progress = node("progress", {"aria-label": "Database job progress"});
  const hint = node("p", {class: "source-hint"}, "You can close this dialog. Work continues on the server; reopen Database jobs to recover it.");
  const cancel = node("button", {id: "cancel-database-job", type: "button", class: "quiet"}, "Cancel job");
  const refresh = node("button", {id: "refresh-database-job", type: "button", class: "quiet"}, "Refresh status");
  const actions = node("div", {class: "database-job-actions"}); actions.append(cancel, refresh);
  const synchronization = node("section", {id: "database-sync-summary", class: "database-sync-summary", hidden: true, "aria-label": "Synchronization changes"});
  monitor.append(status, progress, actions, hint, synchronization);
  const history = node("details", {id: "database-job-history"});
  history.append(node("summary", {}, "Database jobs"));
  const historyStatus = node("p", {class: "source-hint", role: "status"});
  const reload = node("button", {type: "button", class: "quiet", id: "reload-database-jobs"}, "Refresh jobs");
  const list = node("div", {class: "database-job-list"});
  const historyKind = node("select", {id: "database-job-kind", "aria-label": "Job history type"});
  for (const [value, label] of [["", "All database jobs"], ["query", "Queries"], ["sync", "Graph synchronization"]]) historyKind.append(node("option", {value}, label));
  const more = node("button", {type: "button", class: "quiet", hidden: true}, "More jobs");
  history.append(historyStatus, historyKind, reload, list, more); section.append(monitor, history); container.append(section);
  let source = null, listGeneration = 0, generation = 0, controller = null, listController = null, timer = null;
  let active = null, pending = null, failures = 0, inFlight = false, locked = false, destroyed = false, offset = 0;
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
    active = job; monitor.hidden = false;
    const stage = job.progress || {};
    status.textContent = job.status === "cancelling" ? "Cancellation requested. Waiting for the current database operation to return and roll back."
      : ["failed", "interrupted", "cancelled"].includes(job.status) ? errorFrom(job).message
      : `${job.kind === "sync" ? "Graph refresh" : "Query"}: ${stages[stage.stage] || job.status}${stage.completed != null ? ` · ${stage.completed.toLocaleString()}${stage.total != null ? ` / ${stage.total.toLocaleString()}` : ""}` : ""}`;
    if (stage.total > 0 && stage.completed != null) { progress.max = stage.total; progress.value = stage.completed; }
    else progress.removeAttribute("value");
    progress.hidden = !["queued", "running", "cancelling"].includes(job.status);
    cancel.hidden = !["queued", "running", "cancelling"].includes(job.status);
    cancel.disabled = !job.cancellable;
    hint.textContent = ["committing", "saving"].includes(stage.stage) && job.status === "running"
      ? "This job is committing its result and can no longer be cancelled. You can still close this dialog."
      : "You can close this dialog. Work continues on the server; reopen Database jobs to recover it.";
  }
  function stopObservation() {
    generation++; clearTimeout(timer); controller?.abort(); inFlight = false;
    if (pending) { pending.reject(new DOMException("Stopped observing database work.", "AbortError")); pending = null; }
  }
  function finish(current, result, error) {
    if (current !== generation || !pending) return;
    const waiter = pending; pending = null; clearTimeout(timer);
    loadList();
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
      status.textContent = "Status connection interrupted. Your job remains on the server; reconnecting…";
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
  function updateButtons() {
    list.querySelectorAll("button").forEach(button => { button.disabled = locked; });
  }
  async function resume(id, retry = false) {
    if (locked || destroyed) return;
    const current = listGeneration;
    locked = true; updateButtons();
    try {
      const response = await api(`/api/database-jobs/${encodeURIComponent(id)}${retry ? "/retry" : ""}`, retry ? {method: "POST", headers: {"Idempotency-Key": requestKey()}} : {});
      if (destroyed || current !== listGeneration) return;
      locked = false;
      await onResume(response.job || response);
    } catch (error) { if (!destroyed && current === listGeneration) onError(error); }
    finally { if (!destroyed && current === listGeneration) { locked = false; updateButtons(); } }
  }
  async function loadList(append = false) {
    if (!source || destroyed) return;
    listController?.abort(); listController = new AbortController();
    const current = ++listGeneration;
    if (!append) { offset = 0; list.replaceChildren(); }
    historyStatus.textContent = "Loading jobs…"; more.disabled = true;
    try {
      const query = {source_id: source, offset, limit: 10, ...(historyKind.value ? {kind: historyKind.value} : {})};
      const result = await request("get", "/api/database-jobs", {query, signal: listController.signal});
      if (current !== listGeneration || destroyed) return;
      for (const job of result.items || []) {
        const row = node("div", {class: "database-job-row", "data-job-id": job.id});
        row.append(node("span", {}, `${job.kind === "sync" ? "Graph refresh" : "Query"} · ${job.status} · ${new Date(job.created_at).toLocaleString()}`));
        if (job.error?.message) row.append(node("span", {class: "source-hint"}, job.error.message));
        if (job.synchronization) row.append(node("span", {class: "source-hint"}, synchronizationSummary(job.synchronization)));
        const button = node("button", {type: "button", class: "quiet", "data-job-action": "open"}, job.status === "completed" ? job.kind === "sync" ? "View changes" : "View result" : ["queued", "running", "cancelling"].includes(job.status) ? "Follow job" : "View details");
        button.onclick = () => resume(job.id); row.append(button);
        if (["failed", "cancelled", "interrupted"].includes(job.status)) {
          const retry = node("button", {type: "button", class: "quiet", "data-job-action": "retry"}, "Retry job");
          retry.onclick = () => resume(job.id, true); row.append(retry);
        }
        list.append(row);
      }
      offset += result.items?.length || 0;
      more.hidden = !result.has_more; historyStatus.textContent = offset ? "View a saved result or follow work already on the server. Retry creates a new job." : "No database jobs yet.";
      updateButtons();
    } catch (error) {
      if (current === listGeneration && !destroyed && error.name !== "AbortError") historyStatus.textContent = `Job history unavailable. ${error.message}`;
    } finally { if (current === listGeneration) more.disabled = false; }
  }
  reload.onclick = () => loadList(); more.onclick = () => loadList(true);
  historyKind.onchange = () => loadList();
  return {
    async execute(path, body) {
      const response = await api(path, {method: "POST", headers: {Prefer: "respond-async", "Idempotency-Key": requestKey()}, ...(body ? {body: W.stringify(body)} : {})});
      if (destroyed) throw new DOMException("Dialog closed.", "AbortError");
      if (!response.job) { if (response.changes) { monitor.hidden = false; renderSynchronization(response); } return response; }
      loadList(); return watch(response.job);
    },
    watch,
    synchronizationSummary,
    setBusy(value) { locked = value; updateButtons(); },
    setContext(value) { if (value !== source) { stopObservation(); active = null; monitor.hidden = true; renderSynchronization(null); source = value; listGeneration++; listController?.abort(); list.replaceChildren(); if (source) loadList(); } },
    destroy() { destroyed = true; stopObservation(); listGeneration++; listController?.abort(); window.removeEventListener("online", reconcile); document.removeEventListener("visibilitychange", reconcile); section.remove(); },
  };
};
