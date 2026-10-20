"use strict";
window.GraphMineDatabaseWorkspace = ({state, api, W, node, runAction, notice, openSession, loadSessions, go, renderFiles, renderGraph, previewActive}) => {
  const $ = id => document.getElementById(id);
  const launch = node("button", {id: "open-database-workspace", class: "primary", type: "button"}, "Select database & write Cypher");
  const start = node("div", {class: "database-start"});
  start.append(node("strong", {}, "Start from your database"), node("p", {}, "Choose your data, query a graph, then explore it in conversation."), launch);
  $("domain-grid").before(start);
  const nav = node("button", {id: "nav-database", class: "nav-item", type: "button"}, "Database queries");
  document.querySelector(".sidebar-navigation").append(nav);
  const context = node("details", {id: "database-context", class: "database-context", hidden: true});
  $("messages").before(context);
  let previewCy = null;
  const overlays = new Map();
  const viewKey = () => state.resultView ? [state.record?.id, state.record?.revision, state.resultView.step, state.resultView.port, state.resultView.index].join("/") : state.active;
  const show = () => runAction(async () => {
    const sources = await api("/api/database-sources");
    const dialog = node("dialog", {id: "database-workspace", class: "database-dialog", "aria-label": "Database query workspace"});
    const heading = node("div", {class: "section-heading"}), close = node("button", {type: "button", class: "quiet"}, "Close");
    heading.append(node("h2", {}, "Choose data. Write Cypher. Open a conversation."), close);
    const source = node("select", {id: "database-source", "aria-label": "Database"});
    for (const item of sources) source.append(node("option", {value: item.id}, item.name));
    const status = node("p", {id: "database-query-status", role: "status"});
    const schema = node("div", {class: "database-schema", id: "database-schema"});
    const editor = node("textarea", {id: "cypher-editor", class: "code-editor", rows: "12", spellcheck: "false", "aria-label": "Cypher query"});
    editor.value = "MATCH p = (a)-[r]->(b)\nRETURN p\nLIMIT 1000";
    const parameters = node("textarea", {id: "cypher-parameters", class: "code-editor", rows: "3", "aria-label": "Query parameters (JSON)"}); parameters.value = "{}";
    const parameterBox = node("details"); parameterBox.append(node("summary", {}, "Query parameters"), parameters);
    const direction = node("select", {id: "query-graph-direction", "aria-label": "Graph direction for analysis"});
    direction.append(node("option", {value: "directed"}, "Directed · preserve relationship direction"), node("option", {value: "undirected"}, "Undirected · for density, cliques and shared connections"));
    const preview = node("button", {id: "preview-cypher", type: "button", class: "secondary"}, "Preview query");
    const open = node("button", {id: "run-cypher-chat", type: "button", class: "primary"}, "Run & open chat");
    const sync = node("button", {id: "sync-database", type: "button", class: "quiet"}, "Refresh graph from tables");
    const actions = node("div", {class: "form-actions"}); actions.append(preview, open, sync);
    const form = node("div", {class: "database-editor"}); form.append(node("label", {}, "Cypher"), editor, parameterBox, direction, actions, status);
    const canvas = node("div", {id: "database-query-graph", class: "database-query-graph", role: "img", "aria-label": "Query graph preview"});
    const rows = node("pre", {id: "database-query-rows", class: "database-row-preview"});
    const grid = node("div", {class: "database-grid"}); grid.append(schema, form, canvas);
    const rowDetails = node("details"); rowDetails.append(node("summary", {}, "Inspect returned query rows"), rows);
    dialog.append(heading, source, grid, rowDetails); document.body.append(dialog);
    let saved = null, generation = 0;
    const invalidate = () => { generation++; saved = null; };
    editor.oninput = parameters.oninput = invalidate;
    direction.onchange = invalidate;
    const describe = () => {
      invalidate(); schema.replaceChildren();
      const selected = sources.find(s => s.id === source.value);
      if (!selected) { status.textContent = "No databases are configured yet. Add a source mapping in the server's database setup."; preview.disabled = open.disabled = sync.disabled = true; return; }
      schema.append(node("h3", {}, "Graph schema"));
      for (const item of selected.entities) {
        const block = node("details", {open: ""}); block.append(node("summary", {}, item.label), node("p", {}, (item.graph_attributes || item.attributes).join(" · ") || "No imported attributes"), node("p", {class: "muted"}, `Available from tables: ${item.attributes.join(" · ")}`)); schema.append(block);
      }
      schema.append(node("h3", {}, "Relationships"));
      for (const item of selected.relationships) schema.append(node("p", {}, `${item.source_entity} → ${item.label} → ${item.target_entity}`));
      status.textContent = "Return nodes, relationships or paths. Your query defines the graph used for analysis.";
    };
    source.onchange = describe; describe();
    const finish = () => { generation++; previewCy?.destroy(); previewCy = null; dialog.close(); dialog.remove(); };
    close.onclick = finish; dialog.oncancel = event => { event.preventDefault(); finish(); };
    const query = async () => {
      const body = {statement: editor.value, parameters: W.parse(parameters.value || "{}"), directed: direction.value === "directed"};
      const signature = source.value + W.stringify(body);
      if (saved?.signature === signature) return saved.response;
      const current = generation;
      status.textContent = "Executing query and saving its graph…";
      const response = await api(`/api/database-sources/${encodeURIComponent(source.value)}/queries`, {method: "POST", body: W.stringify(body)});
      if (current !== generation || !dialog.isConnected) return null;
      saved = {signature, response};
      status.textContent = `${response.vertex_count} vertices · ${response.edge_count} relationships · ${response.row_count} result rows. ${response.message}`;
      rows.textContent = W.stringify(response.rows, true);
      previewCy?.destroy();
      const graph = response.graph;
      if (window.cytoscape) previewCy = window.cytoscape({container: canvas, elements: [
        ...graph.vertices.map(v => ({data: {id: W.idKey(v.id), label: v.label || v.type || String(v.id)}})),
        ...graph.edges.map((e, i) => ({data: {id: `edge:${i}`, source: W.idKey(e.source), target: W.idKey(e.target)}}))
      ], style: [{selector: "node", style: {label: "data(label)", "font-size": 10, "background-color": "#478663"}}, {selector: "edge", style: {"target-arrow-shape": graph.graph.directed ? "triangle" : "none", "curve-style": "bezier", width: 1.5, "line-color": "#adc5b9", "target-arrow-color": "#adc5b9"}}], layout: {name: "cose", animate: false}});
      if (graph.vertices.length < response.vertex_count || graph.edges.length < response.edge_count) status.textContent += " Preview is bounded; chat uses the full saved query graph.";
      return response;
    };
    const action = fn => runAction(async () => { preview.disabled = open.disabled = sync.disabled = true; try { await fn(); } catch (error) { status.textContent = error.message; throw error; } finally { preview.disabled = open.disabled = sync.disabled = !sources.length; } });
    preview.onclick = () => action(query);
    open.onclick = () => action(async () => {
      const response = await query(); if (!response?.dataset) return;
      const result = await api(`/api/database-query-snapshots/${response.dataset.id}/chat`, {method: "POST", body: "{}"});
      finish(); await openSession(result.session.id); await loadSessions(); go("chat");
      $("question").focus(); notice("Your query graph is attached. Ask what you want to discover.");
    });
    sync.onclick = () => action(async () => { invalidate(); status.textContent = "Reading mapped tables and refreshing the imported graph…"; const result = await api(`/api/database-sources/${source.value}/sync`, {method: "POST"}); status.textContent = `Graph refreshed: ${result.nodes} vertices · ${result.relationships} relationships. Run your query to create a new snapshot.`; });
    dialog.showModal();
  });
  launch.onclick = nav.onclick = show;
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
  const enrichment = node("div", {class: "source-enrichment"}); enrichment.append(attributes, relationships, enrichedNote); $("selection-detail").after(enrichment);
  async function enrichDialog(expand) {
    const file = sourceFile(); if (!file) throw new Error("This view has no source-table mapping. Start with a database query graph.");
    const originalKey = viewKey(), epoch = state.epoch;
    const schema = await api(`/api/files/${file.id}/source-schema`);
    if (epoch !== state.epoch || originalKey !== viewKey()) return;
    const dialog = node("dialog", {id: "enrichment-dialog", class: "wide-dialog", "aria-label": expand ? "Add relationships" : "Add table attributes"});
    const title = node("h2", {}, expand ? "Expand this graph from source records" : "Add source attributes to this view");
    const kind = node("select", {id: "enrichment-kind", "aria-label": "Entity kind"}); kind.append(node("option", {value: "vertices"}, "Vertices")); if (!expand) kind.append(node("option", {value: "edges"}, "Relationships"));
    const mapping = node("select", {id: "enrichment-mapping", "aria-label": "Source table mapping"}), fields = node("fieldset", {id: "enrichment-fields"});
    const scope = node("select", {id: "enrichment-scope", "aria-label": "Selection scope"});
    scope.append(node("option", {value: "result"}, "Current result view (all retained members)"), node("option", {value: "selected"}, "Selected visible entities"));
    const status = node("p", {id: "enrichment-status", role: "status"}), apply = node("button", {id: "apply-enrichment", type: "button", class: "primary"}, expand ? "Add relationships to a new graph version" : "Fetch & add attributes"), close = node("button", {type: "button", class: "quiet"}, "Close");
    const options = () => { mapping.replaceChildren(); for (const m of expand || kind.value === "edges" ? schema.relationships : schema.entities) mapping.append(node("option", {value: m.id}, m.label)); renderFields(); };
    const renderFields = () => { fields.replaceChildren(node("legend", {}, "Attributes")); const m = [...schema.entities, ...schema.relationships].find(m => m.id === mapping.value); for (const name of m?.attributes || []) { const label = node("label", {class: "check"}), checkbox = node("input", {type: "checkbox", value: name, checked: ""}); label.append(checkbox, document.createTextNode(name)); fields.append(label); } fields.hidden = expand; apply.disabled = !m; };
    mapping.onchange = renderFields; kind.onchange = options; options();
    dialog.append(title, kind, mapping, scope, fields, node("p", {class: "muted"}, "Values are fetched from the current source records. Earlier calculations keep their original graph version."), status, apply, close);
    document.body.append(dialog); close.onclick = () => { dialog.close(); dialog.remove(); }; dialog.oncancel = event => { event.preventDefault(); close.click(); };
    apply.onclick = () => runAction(async () => {
      if (epoch !== state.epoch || originalKey !== viewKey()) throw new Error("The displayed result changed. Reopen source details for the current view.");
      const body = {mapping: mapping.value, kind: kind.value, fields: [...fields.querySelectorAll("input:checked")].map(input => input.value)};
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
        const use = node("button", {id: "use-enriched-graph", type: "button", class: "secondary"}, "Use new graph version in chat");
        use.onclick = () => runAction(async () => { state.active = response.file.id; state.record = null; state.result = null; state.resultView = null; renderFiles(); await previewActive(); go("chat"); close.click(); $("question").focus(); });
        dialog.append(use); renderFiles();
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
    for (const select of [labels, colors]) { const selected = select.value; select.replaceChildren(node("option", {value: ""}, "Default")); for (const name of names) select.append(node("option", {value: name}, name)); select.value = names.includes(selected) ? selected : ""; }
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
    attributes.disabled = relationships.disabled = !sourceFile() || Boolean(state.resultView && !state.resultView.enrichable);
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
  return {updateContext, overlayGraph, decorate};
};
