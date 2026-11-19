"use strict";
window.GraphMineDatabaseWorkspace = argumentsForSource => {
  const {state, api, W, node, runAction, notice, go, renderFiles, renderGraph, previewActive, clearResults, viewScope} = argumentsForSource;
  const $ = id => document.getElementById(id);
  const {show, close, mount} = window.GraphMineDataSource({...argumentsForSource});
  const context = node("details", {id: "database-context", class: "database-context", hidden: true});
  $("messages").before(context);
  const overlays = new Map();
  const viewKey = (scope = viewScope()) => scope?.result ? [scope.result.workflow_id, scope.result.revision, scope.result.step, scope.result.port, scope.result.index].join("/") : scope?.file_id || "";
  const restoring = new Map();
  const sourceFile = () => {
    const enriched = overlays.get(viewKey())?.file_id;
    if (enriched) return state.files.find(f => f.id === enriched);
    const ids = state.resultView?.source_file_ids || [state.active];
    return state.files.find(f => ids.includes(f.id) && f.provenance?.source?.database_source);
  };
  function updateContext() {
    const file = state.files.find(f => f.id === state.active), source = file?.provenance?.source;
    context.replaceChildren(); context.hidden = !source?.database_source;
    if (context.hidden) return;
    context.append(node("summary", {}, `${source.database_source.name} · graph version ${file.provenance.version} · ${file.metadata?.vertex_count ?? "?"} vertices`), node("pre", {}, source.query || "Expanded database graph"), node("p", {class: "muted"}, `Saved ${source.fetched_at || ""}. Analysis uses this snapshot.`));
  }
  const attributes = node("button", {id: "enrich-attributes", type: "button", class: "secondary"}, "Add table attributes");
  const relationships = node("button", {id: "enrich-relationships", type: "button", class: "secondary"}, "Add relationships");
  const enrichedNote = node("p", {id: "enrichment-note", class: "muted", role: "status"});
  const retryOverlay = node("button", {id: "retry-enrichment-restore", type: "button", class: "quiet", hidden: true}, "Retry saved attributes");
  const enrichment = node("div", {class: "source-enrichment"}); enrichment.append(attributes, relationships, enrichedNote); $("selection-detail").after(enrichment);
  enrichment.append(retryOverlay); retryOverlay.onclick = () => renderGraph(state.graph);
  async function enrichDialog(expand) {
    let file = sourceFile(); if (!file) throw new Error("This view has no source-table mapping. Start with a database query graph.");
    const originalKey = viewKey(), epoch = state.epoch;
    const schema = await api(`/api/files/${file.id}/source-schema`);
    if (epoch !== state.epoch || originalKey !== viewKey()) return;
    if (schema.capabilities?.[expand ? "expansion" : "enrichment"] === false) throw new Error("This connection has no SQL table mappings for this action. Its saved graph is ready for analysis.");
    const dialog = node("dialog", {id: "enrichment-dialog", class: "wide-dialog", "aria-label": expand ? "Add relationships" : "Add table attributes"});
    const title = node("h2", {}, expand ? "Expand this graph from source records" : "Add source attributes to this view");
    const kind = node("select", {id: "enrichment-kind", "aria-label": "Entity kind"}); kind.append(node("option", {value: "vertices"}, "Vertices")); if (!expand) kind.append(node("option", {value: "edges"}, "Relationships"));
    const mapping = node("select", {id: "enrichment-mapping", "aria-label": "Source table mapping"}), fields = node("fieldset", {id: "enrichment-fields"});
    const scope = node("select", {id: "enrichment-scope", "aria-label": "Selection scope"});
    scope.append(node("option", {value: "result"}, "Current result view (all retained members)"), node("option", {value: "selected"}, "Selected visible entities"));
    const status = node("p", {id: "enrichment-status", role: "status"}), apply = node("button", {id: "apply-enrichment", type: "button", class: "primary"}, expand ? "Add relationships to a new graph version" : "Fetch & add attributes"), close = node("button", {type: "button", class: "quiet"}, "Close");
    const options = () => { mapping.replaceChildren(); for (const m of expand || kind.value === "edges" ? schema.relationships : schema.entities) mapping.append(node("option", {value: m.id}, m.label)); renderFields(); };
    const renderFields = () => { fields.replaceChildren(node("legend", {}, "Attributes · choose up to 64")); const m = [...schema.entities, ...schema.relationships].find(m => m.id === mapping.value); for (const [index, name] of (m?.attributes || []).entries()) { const label = node("label", {class: "check"}), checkbox = node("input", {type: "checkbox", value: name}); checkbox.checked = index < 64; label.append(checkbox, document.createTextNode(name)); fields.append(label); } fields.hidden = expand; apply.disabled = !m; };
    mapping.onchange = renderFields; kind.onchange = options; options();
    dialog.append(title, kind, mapping, scope, fields, node("p", {class: "muted"}, "Values are fetched from the current source records. Earlier calculations keep their original graph version."), status, apply, close);
    document.body.append(dialog); close.onclick = () => { dialog.close(); dialog.remove(); }; dialog.oncancel = event => { event.preventDefault(); close.click(); };
    const use = node("button", {id: "use-enriched-graph", type: "button", class: "secondary", hidden: true}, "Use new graph version in chat");
    use.onclick = () => runAction(async () => { state.active = file.id; state.record = null; clearResults(); renderFiles(); await previewActive(); go("chat"); close.click(); $("question").focus(); });
    dialog.append(use);
    apply.onclick = () => runAction(async () => {
      if (epoch !== state.epoch || originalKey !== viewKey()) throw new Error("The displayed result changed. Reopen source details for the current view.");
      const body = {mapping: mapping.value, kind: kind.value, fields: [...fields.querySelectorAll("input:checked")].map(input => input.value)};
      if (!expand && (!body.fields.length || body.fields.length > 64)) throw new Error("Choose between 1 and 64 attributes per fetch.");
      const view = state.resultView;
      if (view && state.record) body.selection = {workflow_id: state.record.id, revision: state.record.revision, step: view.step, port: view.port, index: view.index};
      if (scope.value === "selected") {
        body.ids = kind.value === "vertices" ? state.cy?.nodes().filter(n => state.selected.has(n.id())).map(n => n.data("entity")) || [] : state.selectedEdges ? state.cy?.edges().filter(e => state.selectedEdges.has(W.idKey(e.data("original").id))).map(e => e.data("original").id) || [] : [];
        if (!body.ids.length) throw new Error("Select at least one visible entity, or choose the current result view.");
      }
      status.textContent = "Fetching source records…"; apply.disabled = true;
      try {
        const response = await api(`/api/files/${file.id}/${expand ? "expansions" : "enrichments"}`, {method: "POST", body: W.stringify(body)});
        if (epoch !== state.epoch || originalKey !== viewKey()) return;
        file = response.file;
        if (!state.files.some(f => f.id === response.file.id)) state.files.push(response.file);
        state.kinds[response.file.id] = "graph";
        if (!expand && state.graph) {
          const updates = new Map(response.updates.map(row => [W.idKey(row.id), row.attributes]));
          const overlay = overlays.get(originalKey) || {vertices: new Map(), edges: new Map(), fields: new Set()};
          overlay.file_id = response.file.id;
          for (const [id, attrs] of updates) overlay[response.entity_kind].set(id, {...overlay[response.entity_kind].get(id), ...attrs});
          body.fields.forEach(name => overlay.fields.add(name)); overlays.set(originalKey, overlay);
          renderGraph(state.graph);
          enrichedNote.textContent = `${response.updates.length} entities enriched at ${response.fetched_at}. ${response.missing.length} source records missing; ${response.unmapped_count} outside this table mapping. Metrics retain their original graph version.`;
        } else enrichedNote.textContent = `${response.added.vertices} vertices and ${response.added.edges} relationships added to graph version ${response.dataset.version}.`;
        status.textContent = response.note;
        use.hidden = false; renderFiles();
      } finally { apply.disabled = false; }
    });
    dialog.showModal();
  }
  attributes.onclick = () => runAction(() => enrichDialog(false)); relationships.onclick = () => runAction(() => enrichDialog(true));
  const labels = node("select", {id: "attribute-label", "aria-label": "Node label attribute"}), colors = node("select", {id: "attribute-color", "aria-label": "Node color attribute"});
  const styles = node("div", {class: "attribute-styles", hidden: true}); styles.append(node("span", {}, "Label"), labels, node("span", {}, "Color"), colors); enrichment.append(styles);
  const legend = node("div", {class: "attribute-legend", "aria-label": "Source attribute colors"}); enrichment.append(legend);
  const tableBox = node("details", {id: "source-attribute-table", hidden: true});
  const search = node("input", {id: "source-attribute-search", placeholder: "Filter fetched attributes", "aria-label": "Filter fetched attributes"}), attributeTable = node("table");
  tableBox.append(node("summary", {}, "Fetched source attributes"), search, attributeTable); enrichment.append(tableBox);
  function refreshStyles(names) {
    styles.hidden = false;
    for (const select of [labels, colors]) { const selected = wantedStyles ? select === labels ? wantedStyles.label : wantedStyles.color : select.value; select.replaceChildren(node("option", {value: ""}, "Default")); for (const name of names) select.append(node("option", {value: name}, name)); select.value = names.includes(selected) ? selected : ""; }
    wantedStyles = null;
  }
  labels.onchange = () => { for (const n of state.cy?.nodes() || []) { const original = n.data("original"); n.data("label", labels.value ? String(original.attributes?.[labels.value] ?? original.label ?? original.id) : String(original.label ?? original.id)); } };
  colors.onchange = () => {
    legend.replaceChildren();
    if (!colors.value) { renderGraph(state.graph); return; }
    const nodes = state.cy?.nodes() || [], get = n => n.data("original").attributes?.[colors.value] ?? null;
    const values = [...new Map([...nodes].map(n => [W.stringify(get(n)), get(n)])).values()].filter(v => v !== null);
    const numeric = values.length && values.every(v => typeof v === "number" && Number.isFinite(v)), low = numeric ? Math.min(...values) : 0, high = numeric ? Math.max(...values) : 1;
    const palette = new Map(values.map((v, i) => [W.stringify(v), `hsl(${(i * 137.508 + 148) % 360}, 42%, 43%)`]));
    for (const n of nodes) { const v = get(n), color = v === null ? "#a5aaa7" : numeric ? `hsl(${125 - (v - low) / (high - low || 1) * 105}, 55%, 43%)` : palette.get(W.stringify(v)); n.style("background-color", colors.value ? color : n.data("color")); }
    if (!colors.value) return;
    if (numeric) legend.append(node("span", {}, `${colors.value}: ${low} (green) → ${high} (orange)`));
    else for (const value of values.slice(0, 16)) { const key = node("span", {}), swatch = node("span", {class: "group-swatch", "aria-hidden": "true"}); swatch.style.backgroundColor = palette.get(W.stringify(value)); key.append(swatch, document.createTextNode(String(value))); legend.append(key); }
    if (values.length > 16 && !numeric) legend.append(node("span", {}, `+ ${values.length - 16} values; inspect exact attributes in the table.`));
    if ([...nodes].some(n => get(n) === null)) legend.append(node("span", {}, "Gray: attribute unavailable"));
  };
  function overlayGraph(graph) {
    const overlay = overlays.get(viewKey()); if (!graph || !overlay) return graph;
    const result = {...graph};
    for (const kind of ["vertices", "edges"]) result[kind] = graph[kind].map(row => overlay[kind].has(W.idKey(row.id)) ? {...row, attributes: {...row.attributes, ...overlay[kind].get(W.idKey(row.id))}} : row);
    return result;
  }
  function decorate() {
    const overlay = overlays.get(viewKey()); tableBox.hidden = styles.hidden = !overlay;
    const file = sourceFile(), capabilities = file?.provenance?.source?.database_source?.capabilities;
    const benchmark = Boolean(file?.provenance?.source?.database_dataset?.registry);
    attributes.hidden = relationships.hidden = benchmark;
    const unavailable = !file || Boolean(state.resultView && !state.resultView.enrichable);
    attributes.disabled = unavailable || capabilities?.enrichment === false;
    relationships.disabled = unavailable || capabilities?.expansion === false;
    attributes.hidden = benchmark || attributes.disabled; relationships.hidden = benchmark || relationships.disabled;
    attributes.title = attributes.disabled ? "Needs a source table mapping for these entities" : ""; relationships.title = relationships.disabled ? "Needs a source relationship mapping for these entities" : "";
    const optionalSqlNote = "This graph comes directly from Neo4j. SQL enrichment is optional and is not configured.";
    if (!overlay && capabilities?.sql === false && !benchmark) enrichedNote.textContent = optionalSqlNote;
    else if (enrichedNote.textContent === optionalSqlNote) enrichedNote.textContent = "";
    attributeTable.replaceChildren(); if (!overlay) { legend.replaceChildren(); return; }
    refreshStyles([...overlay.fields]);
    labels.onchange(); if (colors.value) colors.onchange();
    const fields = [...overlay.fields], head = node("tr"); ["Entity", "Kind", ...fields].forEach(k => head.append(node("th", {}, k))); attributeTable.append(head);
    let count = 0;
    for (const kind of ["vertices", "edges"]) for (const [key, attrs] of overlay[kind]) {
      if (search.value && !W.stringify([key, attrs]).toLocaleLowerCase().includes(search.value.toLocaleLowerCase())) continue;
      if (count++ >= 200) continue;
      const entity = state.graph?.[kind]?.find(row => W.idKey(row.id) === key);
      const tr = node("tr"); [entity?.label || key, kind, ...fields.map(f => attrs[f] ?? null)].forEach(value => tr.append(node("td", {}, typeof value === "string" ? value : W.stringify(value)))); attributeTable.append(tr);
    }
    if (count > 200) { const tr = node("tr"); tr.append(node("td", {colspan: fields.length + 2}, `Showing 200 of ${count} matching entities. Filter to narrow the table.`)); attributeTable.append(tr); }
  }
  search.oninput = decorate;
  function settings() { return {overlay_file_id: overlays.get(viewKey())?.file_id || null, label_attribute: wantedStyles?.label ?? labels.value, color_attribute: wantedStyles?.color ?? colors.value}; }
  let wantedStyles = null;
  function restoreSettings(saved) { wantedStyles = {label: saved.label_attribute, color: saved.color_attribute}; search.value = saved.filters?.attribute_search || ""; }
  async function restoreOverlay(saved, current) {
    const key = viewKey(saved.scope), id = saved.overlay_file_id;
    if (!id || overlays.get(key)?.file_id === id) return;
    const requestKey = W.stringify([key, id, Boolean(saved.scope.result?.context)]);
    if (restoring.has(requestKey)) return restoring.get(requestKey);
    const original = overlays.get(key), originalId = original?.file_id;
    const pending = (async () => {
      const response = await api(`/api/sessions/${encodeURIComponent(state.session.id)}/exploration/overlay`, {method: "POST", body: W.stringify({scope: saved.scope, file_id: id})});
      if (!current() || overlays.get(key) !== original || overlays.get(key)?.file_id !== originalId) return;
      overlays.set(key, {file_id: id, vertices: new Map(response.vertices.map(row => [W.idKey(row.id), row.attributes])), edges: new Map(response.edges.map(row => [W.idKey(row.id), row.attributes])), fields: new Set([...response.fields.vertices, ...response.fields.edges])});
      retryOverlay.hidden = true;
      enrichedNote.textContent = `Source attributes restored from the saved graph version fetched at ${response.fetched_at}. No fresh source lookup was performed.`;
      renderGraph(state.graph);
    })();
    restoring.set(requestKey, pending);
    try { await pending; }
    catch (error) { if (current()) { enrichedNote.textContent = `Saved source attributes could not be restored. ${error.message}`; retryOverlay.hidden = false; } throw error; }
    finally { if (restoring.get(requestKey) === pending) restoring.delete(requestKey); }
  }
  function clearExploration() { overlays.clear(); restoring.clear(); labels.value = colors.value = search.value = ""; wantedStyles = null; enrichedNote.textContent = ""; retryOverlay.hidden = true; }
  return {show, close, mount, updateContext, overlayGraph, decorate, settings, restoreSettings, restoreOverlay, clearExploration};
};
