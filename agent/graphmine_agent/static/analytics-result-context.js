"use strict";
window.GraphMineResultContext = ({state, W, node, qualityDescriptions, title, pageSize, overlay}) => {
  const $ = id => document.getElementById(id);
  const host = node("section", {id: "result-context", "aria-labelledby": "result-context-heading", hidden: true});
  const heading = node("h2", {id: "result-context-heading"}, "Result context"), revision = node("p", {id: "result-context-revision", class: "muted", hidden: true});
  const summary = node("p", {id: "result-context-summary"});
  const grid = node("div", {id: "result-context-grid", class: "result-context-grid", hidden: true}), cards = {};
  const toggle = node("button", {id: "toggle-result-context", class: "quiet", type: "button", "aria-controls": `${grid.id} ${revision.id}`, "aria-expanded": "false"}, "Show details");
  const header = node("div", {class: "section-heading"}); header.append(heading, toggle);
  toggle.onclick = () => { grid.hidden = !grid.hidden; revision.hidden = grid.hidden; toggle.textContent = grid.hidden ? "Show details" : "Hide details"; toggle.setAttribute("aria-expanded", String(!grid.hidden)); };
  for (const [key, label] of [["inputs", "Saved inputs"], ["scope", "Data scope"], ["calculation", "Recorded calculation"], ["display", "Display limits"]]) {
    const card = node("section", {class: "result-context-card", "aria-labelledby": `result-context-${key}-heading`});
    const content = node("div", {id: `result-context-${key}`});
    card.append(node("h3", {id: `result-context-${key}-heading`}, label), content); grid.append(card); cards[key] = content;
  }
  host.append(header, summary, revision, grid); $("result-controls").after(host);
  const calculation = $("result-completeness"), originalPlace = document.createComment("Result status"); calculation.before(originalPlace);
  const primaryInput = node("p", {id: "result-context-primary"});
  let scheduled = false, renderedRecord = null, renderedStep = null, renderedResult = null;
  const line = (parent, label, value) => { const p = node("p"); p.append(node("strong", {}, label + ": "), document.createTextNode(String(value))); parent.append(p); };
  function details(parent, label, value) {
    const disclosure = node("details"); disclosure.append(node("summary", {}, label), node("pre", {tabindex: "0"}, typeof value === "string" ? value : W.stringify(value, true))); parent.append(disclosure);
  }
  // Trace only declared input/binding references, including intermediate steps.
  function dependencies(plan, selected) {
    const steps = new Map((plan?.steps || []).map(step => [step.id, step])), aliases = new Set(), visited = new Set(), derived = [];
    const todo = [selected]; let incomplete = false;
    while (todo.length) {
      const id = todo.pop(); if (visited.has(id)) continue; visited.add(id);
      const step = steps.get(id); if (!step) { incomplete = true; continue; }
      for (const ref of [step.input, ...Object.values(step.bindings || {})]) {
        if (!ref) continue;
        if (ref.input) aliases.add(ref.input);
        else if (ref.step) { derived.push({step: ref.step, port: ref.port, ...(ref.select ? {selection: ref.select} : {})}); todo.push(ref.step); }
      }
    }
    return {aliases: [...aliases], derived, incomplete};
  }
  function sources(record, step) {
    const refs = dependencies(record.validation?.plan, step), todo = refs.aliases.map(alias => ({label: alias, data: record.input_provenance?.[alias] || {file_id: record.input_files?.[alias]?.file_id}}));
    const entries = [], seen = new Set();
    while (todo.length && entries.length < 64) {
      const item = todo.shift(), data = item.data || {}, source = data.source || {};
      if (seen.has(data)) continue; seen.add(data);
      entries.push({...item, data, source});
      if (source.parent) todo.push({label: `${item.label} · saved source`, data: source.parent});
      for (const [alias, table] of Object.entries(data.tables || {})) todo.push({label: `${item.label} · table ${alias}`, data: {...table.source, file_id: table.file_id, sha256: table.sha256}});
      if (source.input_provenance) {
        const upstream = dependencies(source.plan, source.step);
        for (const alias of upstream.aliases) todo.push({label: `${item.label} · prior input ${alias}`, data: source.input_provenance[alias]});
      }
    }
    return {refs, entries, truncated: todo.length > 0};
  }
  function renderSources(record, step) {
    cards.inputs.replaceChildren(primaryInput); cards.scope.replaceChildren();
    const lineage = sources(record, step);
    if (!lineage.entries.length) line(cards.inputs, "Input identity", "Not recorded for this step.");
    for (const alias of lineage.refs.aliases) {
      const data = record.input_provenance?.[alias] || {}, file = data.file_snapshot || {};
      const id = data.file_id || record.input_files?.[alias]?.file_id;
      line(cards.inputs, alias, `${file.name || id || "Input identity not recorded"}${data.version != null ? ` · version ${data.version}` : ""}`);
    }
    if (lineage.refs.derived.length) {
      line(cards.inputs, "Step input", "Uses earlier workflow output. The source snapshots below describe its ancestry.");
      details(cards.inputs, "Earlier steps and selected outputs", lineage.refs.derived);
    }
    if (lineage.refs.incomplete) line(cards.inputs, "Lineage", "Some saved input references are unavailable.");
    const identities = lineage.entries.map(({label, data}) => ({input: label, file_id: data.file_id || null, sha256: data.sha256 || null, dataset_id: data.dataset_id || null, version_id: data.version_id || null, version: data.version ?? null, saved_at: data.file_snapshot?.created_at || null, graph: data.file_snapshot?.graph || null}));
    if (identities.length) details(cards.inputs, "Snapshot identifiers and hashes", identities);
    line(cards.inputs, "Analysis input", "Fixed to this revision, independently of the active conversation input.");
    let scoped = false;
    for (const {label, data, source} of lineage.entries) {
      if (source.database_source) {
        scoped = true;
        const section = node("div", {class: "result-source-scope"});
        line(section, label, `${source.database_source.name || source.database_source.id}${source.database_dataset ? ` · ${source.database_dataset.name || source.database_dataset.id}` : ""}`);
        line(section, "Saved selection", source.scope || "Query scope was not recorded.");
        if (source.row_count != null) line(section, "Query rows", source.row_count);
        if (source.fetched_at) line(section, "Snapshot captured", source.fetched_at);
        if (source.expansion) line(section, "Expanded input", "Relationships were added to the initial query graph. The query below describes the original selection.");
        if (source.enrichment) line(section, "Saved attributes", `Fetched at ${source.enrichment.fetched_at || "an unrecorded time"}.`);
        const saved = node("details"); saved.append(node("summary", {}, "Source query and parameters"));
        if (source.query) saved.append(node("pre", {tabindex: "0"}, source.query));
        saved.append(node("pre", {tabindex: "0"}, W.stringify({parameters: source.parameters || {}, projection: source.projection || null, weight_property: source.weight_property || null, connection_revision: source.database_source.revision ?? null, mapping_hash: source.database_source.mapping_hash || null}, true)));
        section.append(saved); cards.scope.append(section);
        if (source.type === "semantic_query" || source.steps?.length) cards.scope.append(window.GraphMineSemanticDetails({node, W, source, versionId: data.version_id}));
      }
      if (data.projection) {
        scoped = true; line(cards.scope, label, "Graph constructed from saved tables using recorded joins, filters and projection settings.");
        details(cards.scope, "Table projection settings", data.projection);
      }
      if (source.type === "result") {
        scoped = true; line(cards.scope, "Reused result", `${source.workflow_id} · revision ${source.revision} · ${source.step}/${source.port}${source.group_index != null ? ` · group ${source.group_index + 1}` : ""}`);
      }
    }
    if (!scoped) line(cards.scope, "Source scope", "Saved input. Database query scope was not recorded.");
    const flags = lineage.entries.map(entry => entry.data.source_complete);
    line(cards.scope, "Source completeness", flags.includes(false) ? "Includes incomplete source output. A complete calculation cannot restore missing source data."
      : flags.includes(true) && flags.every(flag => flag === true) ? "Complete within the saved source selection. This does not establish coverage of an entire database or population."
        : flags.includes(true) ? "Some saved sources are complete; completeness of other inputs was not recorded. Database or population coverage is unknown."
        : "Not recorded. No claim of full database or population coverage is available.");
    if (lineage.truncated) line(cards.scope, "Lineage display", "Showing the first 64 source records. The downloaded result retains the recorded provenance.");
  }
  function renderCalculation(record, result, port) {
    calculation.replaceChildren();
    line(calculation, "Quality", qualityDescriptions[result.quality] || (result.quality ? title(result.quality) : "Not recorded"));
    line(calculation, "Output", port.complete === true ? "This output collection is complete." : port.complete === false ? "This output is incomplete or count-only; it cannot supply a full downstream collection." : "Output completeness was not recorded.");
    calculation.classList.toggle("incomplete", port.complete === false || result.complete === false || state.result.partial_workflow === true);
    if (result.complete === false) line(calculation, "Calculation", "Some outputs from this step are incomplete.");
    if (state.result.partial_workflow || record.status !== "completed") line(calculation, "Workflow", `${title(record.status)}. This panel describes a retained completed step.`);
    if (result.backend?.device) line(calculation, "Computed on", result.backend.device.toUpperCase());
    if (result.backend?.selection_reason) line(calculation, "Device selection", result.backend.selection_reason);
    if (result.diagnostics?.solver) line(calculation, "Method", {native_positive_gain_vertex_moves: "Local vertex moves (native CPU heuristic)", gleiden: "GPU Leiden"}[result.diagnostics.solver] || title(result.diagnostics.solver));
    if (result.diagnostics?.narrowing_hint && port.complete === false) line(calculation, "Next step", result.diagnostics.narrowing_hint);
    const scope = node("p", {class: "muted"}, "Quality applies to the saved inputs and calculation settings."); calculation.append(scope);
    details(calculation, "Recorded calculation settings", result.parameters ?? record.validation?.plan?.steps?.find(s => s.id === $("result-step").value)?.parameters ?? {});
  }
  function renderDisplay() {
    cards.display.replaceChildren();
    const view = state.resultView, graph = state.graph, cy = state.cy;
    if (state.resultViewPending) line(cards.display, "Graph", "Loading the saved result view…");
    else if (state.resultViewError) line(cards.display, "Graph", "Result view unavailable. Its displayed coverage cannot be verified.");
    else if (graph && cy) {
      const vertices = cy.nodes().length, edges = cy.edges().length, shownEdges = cy.edges().filter(e => e.style("display") !== "none").length;
      const group = state.groups?.find(group => group.key === state.groupFilter);
      const source = group && state.groupGraph?.key === group.key ? state.groupGraph.data : graph;
      const n = group ? group.vertices.size : source.vertex_count ?? source.vertices.length;
      const inside = edge => !group || group.vertices.has(W.idKey(edge.source)) && group.vertices.has(W.idKey(edge.target));
      const flowMode = Boolean(state.flowRows && $("flow-direction").checked);
      let m, truncated, connectionScope;
      if (flowMode) {
        const flows = state.flowRows.filter(row => (row.flow_exact?.numerator !== undefined ? BigInt(row.flow_exact.numerator) > 0n : row.flow > 0) && inside(row));
        // Positive flow is an intentional selection, not every input connection.
        truncated = vertices < n || edges < flows.length || view?.flow_rows_truncated;
        connectionScope = `${edges} positive-flow connections loaded`;
      } else {
        const allEdges = !source.edges_truncated && source.edges.length >= (source.edge_count ?? source.edges.length);
        m = group ? allEdges ? source.edges.filter(inside).length : null : source.edge_count ?? source.edges.length;
        truncated = vertices < n || (m !== null && edges < m) || !allEdges;
        connectionScope = m === null ? `${edges} connections loaded · selected connection total unavailable` : `${edges} of ${m} connections loaded`;
      }
      line(cards.display, "Graph", `${vertices} of ${n} vertices · ${connectionScope}${shownEdges < edges ? ` · ${shownEdges} connections visible after time filtering` : ""}.`);
      line(cards.display, "Graph scope", group ? `${group.label}: selected members and their internal connections.` : view ? view.context ? "Saved step input with the result highlighted." : `Recorded result${view.index != null ? ` · item ${view.index + 1} of ${view.item_count}` : ""}.` : "Input or output graph preview.");
      if (flowMode) line(cards.display, "Connection filter", "Positive computed flow only. Zero-flow and unused input connections are intentionally excluded.");
      if (truncated) line(cards.display, "Preview bound", "Graph display is truncated. Saved calculation results are unchanged.");
      if (view?.limits) line(cards.display, "Graph cap", `${Math.min(500, view.limits.vertices)} vertices · ${Math.min(2000, view.limits.edges)} connections.`);
      if (view?.selection_truncated) line(cards.display, "Highlighted selection", "Some selected entities are outside this preview.");
    } else line(cards.display, "Graph", view?.graph_available === false ? "This output has no graph representation in the selected view." : "No graph is displayed.");
    const retained = state.remote?.total ?? state.rows.length, matched = state.remote?.matched ?? state.filtered.length;
    const shown = state.remote ? state.filtered.length : state.filtered.slice(state.page * pageSize, (state.page + 1) * pageSize).length;
    line(cards.display, "Table", state.remoteLoading ? "Loading retained rows…" : state.remoteError ? `Table page unavailable. ${state.remoteError}` : `${shown} rows on this page · ${matched} matching · ${retained} retained.`);
    if (state.port?.value_truncated) line(cards.display, "Charts", `Use ${state.rows.length} loaded rows of ${retained} retained rows. Search and pagination use the full retained table.`);
    const overlayId = overlay?.();
    if (overlayId) {
      const file = state.files.find(file => file.id === overlayId), provenance = file?.provenance;
      line(cards.display, "Display attributes", `${provenance?.version != null ? `Version ${provenance.version}` : overlayId}${provenance?.source?.fetched_at ? ` · fetched ${provenance.source.fetched_at}` : ""}. The calculation retains its original input snapshot.`);
    }
    line(cards.display, "Display controls", "Graph, time and table filters affect this view only. Layout positions are for display unless computed coordinates are selected.");
  }
  function render() {
    scheduled = false;
    const record = state.record, step = $("result-step").value, result = state.result?.steps?.[step]?.result, port = state.port;
    if (!record || !result || !port) { host.hidden = true; originalPlace.after(calculation); renderedRecord = null; return; }
    host.hidden = false; cards.calculation.append(calculation);
    revision.textContent = `Analysis ${record.id} · revision ${record.revision} · step ${step} · output ${$("result-port").value}`;
    if (record !== renderedRecord || step !== renderedStep) { renderSources(record, step); renderedRecord = record; renderedStep = step; }
    const input = record.validation?.plan?.steps?.find(s => s.id === step)?.input;
    const graph = state.resultView?.input_graph || (input?.input ? record.input_provenance?.[input.input]?.file_snapshot?.graph : null);
    primaryInput.hidden = graph?.vertex_count == null;
    if (!primaryInput.hidden) primaryInput.textContent = `Primary step input: ${graph.vertex_count} vertices · ${graph.edge_count} connections · ${graph.directed ? "directed" : "undirected"}.`;
    const aliases = dependencies(record.validation?.plan, step).aliases;
    const names = aliases.map(alias => record.input_provenance?.[alias]?.file_snapshot?.name || alias);
    const quality = result.quality ? title(result.quality) : "Quality unrecorded";
    const bound = port.complete === false ? "Incomplete or count-only output" : result.complete === false ? "Incomplete calculation" : "Saved input scope";
    summary.textContent = [names.join(", "), graph?.vertex_count != null ? `${graph.vertex_count} vertices · ${graph.edge_count} connections` : null, quality, bound].filter(Boolean).join(" · ");
    summary.classList.toggle("incomplete", port.complete === false || result.complete === false);
    // Preserve disclosure and keyboard focus while only display filters change.
    const key = `${record.id}/${record.revision}/${step}/${$("result-port").value}`;
    if (calculation.dataset.contextKey !== key || renderedResult !== result) { calculation.dataset.contextKey = key; renderedResult = result; renderCalculation(record, result, port); }
    renderDisplay();
  }
  const refresh = () => { if (!scheduled) { scheduled = true; requestAnimationFrame(render); } };
  for (const name of ["input", "change"]) document.addEventListener(name, event => { if (event.target.closest?.("#time-controls")) refresh(); });
  return {refresh, clear() { renderedRecord = renderedResult = null; delete calculation.dataset.contextKey; refresh(); }};
};
