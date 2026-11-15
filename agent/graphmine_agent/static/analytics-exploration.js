"use strict";
window.GraphMineExploration = ({state, api, W, node, scope, database, applySelection, filterRows, reload}) => {
  const $ = id => document.getElementById(id), memory = new Map();
  const box = node("div", {class: "exploration-status"}), status = node("span", {id: "exploration-status", role: "status"});
  const retry = node("button", {id: "retry-exploration-save", type: "button", class: "quiet", hidden: true}, "Retry saving");
  const remote = node("button", {id: "reload-exploration", type: "button", class: "quiet", hidden: true}, "Reload saved view");
  const keep = node("button", {id: "keep-exploration", type: "button", class: "quiet", hidden: true}, "Keep this view");
  box.append(status, retry, remote, keep); $("preview-scope").after(box);
  const ids = {search: "table-search", group_min: "group-min-size", group_max: "group-max-size", group_member: "group-member", attribute_search: "source-attribute-search"};
  const watched = new Set([...Object.values(ids), "graph-layout", "graph-group", "highlight-overlap", "flow-direction", "time-start", "time-end", "include-untimed", "attribute-label", "attribute-color"]);
  let context = null, generation = 0, captureTimer = null, saveTimer = null, applying = false, lastGraph = null;
  const key = value => !value ? "" : value.file_id ? W.stringify(["file", value.file_id]) : W.stringify(["result", value.result.workflow_id, value.result.revision, value.result.step, value.result.port, value.result.index ?? null, Boolean(value.result.context)]);
  const clone = value => W.parse(W.stringify(value));
  const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === "object" ? Object.fromEntries(Object.keys(value).sort().map(name => [name, canonical(value[name])])) : value;
  const equal = (left, right) => W.stringify(canonical(left)) === W.stringify(canonical(right));
  const storageKey = response => response.storage_key ? `graphmine.exploration.v1.${new URL(state.base || location.origin, location.href).href}.${response.storage_key}` : null;
  function validJournal(value) {
    // Recovery data is browser-owned and may be corrupt or from an older client.
    const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
    const integer = value => Number.isSafeInteger(value) && value >= 0;
    const identifier = value => typeof value === "string" && value.length > 0 && value.length <= 128;
    const entity = value => typeof value === "bigint" || Number.isSafeInteger(value) || typeof value === "string" && value.length <= 2048;
    const point = value => object(value) && [value.x, value.y].every(n => typeof n === "number" && Number.isFinite(n) && Math.abs(n) <= 1e9);
    const scope = value => object(value) && (identifier(value.file_id) && value.result == null || value.file_id == null && object(value.result) && identifier(value.result.workflow_id) && integer(value.result.revision) && value.result.revision > 0 && identifier(value.result.step) && identifier(value.result.port) && (value.result.index == null || integer(value.result.index)) && typeof value.result.context === "boolean");
    const doc = value?.document;
    if (!integer(value?.revision) || !object(doc) || doc.active_file_id !== null && !identifier(doc.active_file_id) || doc.view !== null && !scope(doc.view) || !Array.isArray(doc.views) || doc.views.length > 32) return false;
    const keys = new Set();
    for (const view of doc.views) {
      if (!object(view) || !scope(view.scope) || keys.has(key(view.scope))) return false;
      keys.add(key(view.scope));
      if (!["cose", "groups", "circle", "grid", "computed"].includes(view.layout) || !object(view.filters)) return false;
      if (![view.label_attribute, view.color_attribute].every(v => typeof v === "string" && v.length <= 256) || view.overlay_file_id !== null && !identifier(view.overlay_file_id)) return false;
      for (const [name, val] of Object.entries(view.filters)) {
        if (["highlight_overlap", "flow_direction", "include_untimed"].includes(name)) { if (typeof val !== "boolean") return false; }
        else if (val !== null && typeof val !== "string" || typeof val === "string" && val.length > 2048) return false;
      }
      if (!Array.isArray(view.selected_vertices) || view.selected_vertices.length > 500 || !view.selected_vertices.every(entity) || !Array.isArray(view.selected_edges) || view.selected_edges.length > 2000 || !view.selected_edges.every(entity)) return false;
      const v = view.viewport;
      if (v !== null && (!object(v) || !point(v.pan) || typeof v.zoom !== "number" || !Number.isFinite(v.zoom) || v.zoom < .08 || v.zoom > 5 || !Array.isArray(v.positions) || v.positions.length > 500 || !v.positions.every(p => point(p) && entity(p.id)) || new Set(v.positions.map(p => W.idKey(p.id))).size !== v.positions.length)) return false;
    }
    return new TextEncoder().encode(W.stringify(doc)).length <= 512 * 1024;
  }
  function viewFor(value = scope()) { return context?.document.views.find(view => key(view.scope) === key(value)) || null; }
  function message(text, error = false) {
    status.textContent = text; box.classList.toggle("save-error", error);
    retry.hidden = !error || Boolean(context?.conflict);
    remote.hidden = keep.hidden = !context?.conflict;
  }
  function journal(ctx, snapshot = null) {
    if (!ctx?.storageKey) return;
    if (snapshot) {
      const value = W.stringify(snapshot); memory.set(ctx.storageKey, value);
      try { localStorage.setItem(ctx.storageKey, value); ctx.local = true; }
      catch { ctx.local = false; }
    } else {
      memory.delete(ctx.storageKey);
      try { localStorage.removeItem(ctx.storageKey); } catch { /* Server saves remain available. */ }
    }
  }
  function remember(ctx) { journal(ctx, {revision: ctx.revision, document: ctx.document}); }
  function upsert(value) {
    const found = key(value.scope);
    context.document.views = context.document.views.filter(view => key(view.scope) !== found);
    context.document.views.push(value);
    while (context.document.views.length > 32 || context.document.views.length > 1 && new TextEncoder().encode(W.stringify(context.document)).length > 500 * 1024) context.document.views.shift();
  }
  function viewport(cy) {
    return {zoom: cy.zoom(), pan: cy.pan(), positions: cy.nodes().map(n => ({id: n.data("entity"), ...n.position()}))};
  }
  function capture() {
    clearTimeout(captureTimer); captureTimer = null;
    const ctx = context;
    if (!ctx?.ready || applying) return;
    const current = scope(), previous = viewFor(current), style = database()?.settings() || {};
    ctx.document.active_file_id = state.active || null; ctx.document.view = current;
    if (state.cy && current && lastGraph?.cy === state.cy && key(lastGraph.scope) === key(current)) {
      const filters = {...previous?.filters, ...window.GraphMineExplorer?.timeState?.()};
      for (const [name, id] of Object.entries(ids)) filters[name] = $(id)?.value || "";
      Object.assign(filters, {group: state.groupFilter || "", highlight_overlap: $("highlight-overlap").checked, flow_direction: $("flow-direction").checked});
      upsert({scope: clone(current), layout: $("graph-layout").value, viewport: viewport(state.cy), filters,
        overlay_file_id: style.overlay_file_id || previous?.overlay_file_id || null, label_attribute: style.label_attribute || "", color_attribute: style.color_attribute || "",
        selected_vertices: state.cy.nodes().filter(n => state.selected.has(n.id())).map(n => n.data("entity")),
        selected_edges: state.cy.edges().filter(e => state.selectedEdges?.has(W.idKey(e.data("original").id))).map(e => e.data("original").id).filter(id => id !== undefined)});
    }
    const serialized = W.stringify(ctx.document);
    if (serialized === ctx.serialized) return;
    ctx.serialized = serialized; ctx.dirty = true; remember(ctx);
    if (!ctx.available) { message("Exploration settings could not be loaded. These changes are kept in this tab; retry to reconnect.", true); return; }
    if (!ctx.conflict) {
      message(ctx.local ? "Saving exploration… Changes are also retained in this browser." : "Saving exploration… Browser recovery storage is unavailable.");
      clearTimeout(saveTimer); saveTimer = setTimeout(() => flush(ctx), 350);
    }
  }
  function changed() {
    if (!context?.ready || applying) return;
    clearTimeout(captureTimer); captureTimer = setTimeout(capture, 100);
  }
  async function flush(ctx = context, keepalive = false) {
    clearTimeout(saveTimer);
    if (!ctx?.ready || !ctx.dirty || ctx.saving || ctx.conflict || !ctx.available) return;
    const sent = ctx.serialized, payload = {expected_revision: ctx.revision, state: W.parse(sent)};
    const body = W.stringify(payload); ctx.saving = true;
    try {
      const response = await api(`/api/sessions/${encodeURIComponent(ctx.id)}/exploration`, {method: "PUT", body, keepalive: keepalive && new TextEncoder().encode(body).length < 60_000});
      ctx.revision = response.revision;
      if (ctx.serialized === sent) { ctx.dirty = false; if (context === ctx) journal(ctx); }
      else if (context === ctx) remember(ctx);
      if (context === ctx) message("Exploration saved.");
    } catch (error) {
      if (context !== ctx) return;
      if (error.code === "exploration_conflict") {
        try {
          const latest = await api(`/api/sessions/${encodeURIComponent(ctx.id)}/exploration`);
          if (context !== ctx) return;
          if (equal(latest.state, W.parse(sent))) {
            ctx.revision = latest.revision; ctx.dirty = ctx.serialized !== sent;
            if (ctx.dirty) remember(ctx); else journal(ctx);
            message("Exploration saved."); return;
          }
        } catch { /* Keep the local draft until the user can reconcile it. */ }
        ctx.conflict = true;
        message("Exploration changed in another tab. Reload the saved view or keep this view.", true);
      } else message(`Exploration could not be saved. ${error.message}${ctx.local ? " Your changes remain in this browser." : " Keep this tab open to retry."}`, true);
    } finally {
      ctx.saving = false;
      if (context === ctx && ctx.dirty && !ctx.conflict && ctx.revision !== payload.expected_revision) saveTimer = setTimeout(() => flush(ctx), 100);
    }
  }
  async function open(id, signal) {
    const current = ++generation;
    context = {id, ready: false, available: false, revision: 0, document: {active_file_id: null, view: null, views: []}, dirty: false, conflict: false, saving: false, local: false};
    lastGraph = null; message("Loading saved exploration…");
    const ctx = context;
    try {
      const response = await api(`/api/sessions/${encodeURIComponent(id)}/exploration`, {signal});
      if (current !== generation) return null;
      ctx.available = true; ctx.revision = response.revision;
      ctx.storageKey = storageKey(response);
      let local = null;
      try { if (ctx.storageKey) local = W.parse(memory.get(ctx.storageKey) || localStorage.getItem(ctx.storageKey) || "null"); } catch { /* Ignore malformed browser recovery data. */ }
      if (local && !validJournal(local)) { journal(ctx); local = null; }
      const saved = response.state;
      if (local) {
        ctx.document = local.document; ctx.dirty = !equal(saved, local.document);
        ctx.conflict = ctx.dirty && local.revision !== response.revision; ctx.local = true;
        if (!ctx.dirty) journal(ctx);
      } else if (saved) ctx.document = saved;
      ctx.serialized = W.stringify(ctx.document);
      message(ctx.conflict ? "This browser has unsaved exploration that differs from the server. Reload the saved view or keep this view."
        : response.warnings?.join(" ") || (saved || local ? "Saved exploration restored." : "Exploration settings will save as you work."), ctx.conflict);
      return saved || local ? clone(ctx.document) : null;
    } catch (error) {
      if (current === generation) { ctx.serialized = W.stringify(ctx.document); message(`Exploration settings are unavailable. ${error.message}`, true); }
      return null;
    }
  }
  function ready() {
    if (!context) return;
    const doc = context.document, before = W.stringify(doc);
    const fileExists = id => state.files.some(file => file.id === id);
    const available = scope => scope.file_id ? fileExists(scope.file_id) : state.workflows.some(record => record.id === scope.result.workflow_id && record.revision === scope.result.revision && record.validation.order.includes(scope.result.step));
    // A local recovery journal can outlive a deleted file or revised analysis.
    if (doc.active_file_id && !fileExists(doc.active_file_id)) doc.active_file_id = null;
    if (doc.view && !available(doc.view)) doc.view = null;
    doc.views = doc.views.filter(view => available(view.scope));
    for (const view of doc.views) if (view.overlay_file_id && !fileExists(view.overlay_file_id)) view.overlay_file_id = null;
    if (W.stringify(doc) !== before) {
      context.serialized = W.stringify(doc); context.dirty = true; remember(context);
      message("Unavailable files or result revisions were omitted from the recovered exploration.", context.conflict);
    }
    context.ready = true;
    if (context.dirty && !context.conflict) void flush();
  }
  function leave() {
    capture(); void flush(); clearTimeout(captureTimer); clearTimeout(saveTimer); generation++;
    context = null; lastGraph = null; message("");
  }
  function beforeGraph() {
    if (context?.ready && lastGraph?.cy === state.cy && state.cy) {
      if (key(lastGraph.scope) === key(scope())) capture();
      const saved = viewFor(lastGraph.scope);
      if (saved) saved.viewport = viewport(state.cy);
    }
  }
  function prepareGraph() {
    const saved = viewFor();
    if (!saved) { database()?.restoreSettings({label_attribute: "", color_attribute: "", filters: {}}); return; }
    $("graph-layout").value = saved.layout;
    const filters = saved.filters || {};
    if (!state.resultView) state.groupFilter = state.groups?.some(group => group.key === filters.group) ? filters.group : "";
    $("highlight-overlap").checked = Boolean(filters.highlight_overlap);
    $("flow-direction").checked = filters.flow_direction !== false;
    for (const [name, id] of Object.entries(ids)) if ($(id)) $(id).value = filters[name] || "";
    database()?.restoreSettings(saved);
  }
  function afterGraph({hidden = false} = {}) {
    const cy = state.cy, current = scope(), saved = viewFor(current), epoch = state.epoch;
    if (!context || !current) return;
    if (saved?.overlay_file_id) {
      const ctx = context;
      void database()?.restoreOverlay(saved, () => context === ctx && state.epoch === epoch && key(scope()) === key(current)).catch(() => { /* The source-attribute panel owns its recovery message. */ });
    }
    if (!cy || hidden) return;
    applying = true;
    try {
      if (saved?.viewport) {
        const positions = new Map(saved.viewport.positions.map(p => [W.idKey(p.id), p]));
        if (cy.nodes().length === positions.size && cy.nodes().every(n => positions.has(n.id()))) {
          cy.batch(() => cy.nodes().forEach(n => { const {x, y} = positions.get(n.id()); n.position({x, y}); }));
          cy.viewport({zoom: saved.viewport.zoom, pan: saved.viewport.pan});
        }
      }
      if (saved) {
        state.selected = new Set((saved.selected_vertices || []).map(W.idKey));
        state.selectedEdges = new Set((saved.selected_edges || []).map(W.idKey));
        applySelection(); filterRows();
      }
      lastGraph = {cy, scope: clone(current)};
      cy.off("pan zoom dragfree", changed);
      cy.on("pan zoom dragfree", changed);
    } finally { applying = false; }
    changed();
  }
  function selectionFor(record, step = null, port = null) {
    const matches = value => value?.result?.workflow_id === record?.id && value.result.revision === record.revision && (!step || value.result.step === step) && (!port || value.result.port === port);
    if (!context) return null;
    if (matches(context.document.view)) return context.document.view.result;
    return [...context.document.views].reverse().find(view => matches(view.scope))?.scope.result || null;
  }
  async function resolveConflict(useLocal) {
    const ctx = context;
    if (!ctx || ctx.saving) return;
    try {
      const latest = await api(`/api/sessions/${encodeURIComponent(ctx.id)}/exploration`);
      if (context !== ctx) return;
      if (useLocal) { ctx.revision = latest.revision; ctx.conflict = false; ctx.dirty = true; remember(ctx); await flush(ctx); }
      else { journal(ctx); ctx.ready = false; ctx.dirty = false; await reload(); }
    } catch (error) { if (context === ctx) message(error.message, true); }
  }
  async function retrySave() {
    const ctx = context;
    if (!ctx || ctx.saving) return;
    capture();
    if (ctx.available) { void flush(ctx); return; }
    try {
      const latest = await api(`/api/sessions/${encodeURIComponent(ctx.id)}/exploration`);
      if (context !== ctx) return;
      if (!ctx.dirty) { await reload(); return; }
      ctx.available = true; ctx.storageKey = storageKey(latest); ctx.revision = latest.revision;
      ctx.conflict = Boolean(latest.state && !equal(latest.state, ctx.document));
      remember(ctx);
      if (ctx.conflict) message("Saved exploration is available again. Reload the saved view or keep this view.", true);
      else await flush(ctx);
    } catch (error) { if (context === ctx) message(`Exploration settings are unavailable. ${error.message} Keep this tab open to retry.`, true); }
  }
  keep.onclick = () => resolveConflict(true); remote.onclick = () => resolveConflict(false);
  retry.onclick = retrySave;
  document.addEventListener("input", event => { if (watched.has(event.target.id)) changed(); });
  document.addEventListener("change", event => { if (watched.has(event.target.id)) changed(); });
  window.addEventListener("pagehide", () => { capture(); void flush(context, true); });
  const reconcile = () => { if (!document.hidden) { capture(); void flush(); } };
  window.addEventListener("online", reconcile); document.addEventListener("visibilitychange", () => { if (document.hidden) { capture(); void flush(context, true); } else reconcile(); });
  return {open, ready, leave, changed, capture, beforeGraph, prepareGraph, afterGraph, selectionFor, settings: viewFor, key};
};
