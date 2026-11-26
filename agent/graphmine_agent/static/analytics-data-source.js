"use strict";
window.GraphMineDataSource = ({state, api, W, node, runAction, notice, openSession, loadSessions, go, renderFiles, previewActive, upload, clearResults, openData, leaveData, dataPartChanged, dataReturnLabel}) => {
  const $ = id => document.getElementById(id);
  const icon = name => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "ui-icon"); svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(svg.namespaceURI, "use");
    use.setAttribute("href", `#icon-${name}`); svg.append(use); return svg;
  };
  const button = (id, text, style = "secondary") => node("button", {id, type: "button", class: style}, text);
  const label = (text, field) => { const el = node("label", {}, text); el.append(field); return el; };
  let opening = false, closeDialog = null, selectPart = null, mounting = 0, pendingPart = "connection";
  const launch = button("open-database-workspace", "Open data workspace", "primary");
  const start = node("div", {class: "database-start"}), startText = node("div");
  startText.append(node("strong", {}, "Start with your data"), node("p", {}, "Choose a dataset, shape your graph with Cypher, or upload a file."));
  start.append(icon("data"), startText, launch);
  document.querySelector(".domain-grid-heading").before(start);
  const nav = button("nav-database", "", "nav-item");
  nav.append(icon("data"), node("span", {}, "Data workspace")); document.querySelector(".sidebar-navigation").append(nav);
  const show = (part = "connection") => openData(part);
  const closeWorkspace = () => { mounting++; opening = false; closeDialog?.(); };
  async function mount(part = "connection") {
    pendingPart = part;
    if ($("database-workspace")) { selectPart?.(part); return; }
    if (opening) return;
    const currentMount = ++mounting, epoch = state.epoch;
    opening = true;
    const currentFile = state.files.find(f => f.id === state.active) || [...state.files].reverse().find(f => f.provenance?.kind === "table");
    let drafts, draftSelection = null, draftBackend = null;
    try {
      await window.GraphMineAccount?.ready;
    } catch (error) { if (currentMount === mounting) { opening = false; notice(error.message, true); } return; }
    if (currentMount !== mounting || epoch !== state.epoch || state.view !== "data") return;
    if (!state.domains.length) {
      try { state.domains = await api("/api/domains"); }
      catch (error) { if (currentMount === mounting) { opening = false; notice(error.message, true); } return; }
    }
    if (currentMount !== mounting || epoch !== state.epoch || state.view !== "data") return;
    window.GraphMineShell.setPanel("data", false);
    window.GraphMineShell.setPanel("navigation", false);
    const focusBefore = document.activeElement;
    const dialog = node("section", {id: "database-workspace", class: "database-dialog data-workspace", "aria-labelledby": "data-source-title"});
    const heading = node("header", {class: "source-heading"}), titleBox = node("div");
    titleBox.append(node("h1", {id: "data-source-title", tabindex: "-1"}, "Data workspace"), node("p", {}, state.session ? `For ${state.session.title || "this conversation"}` : "Choose your data, shape a query, and inspect the result."));
    const close = button("close-data-source", dataReturnLabel(), "quiet");
    heading.append(titleBox, close);
    const tabs = node("div", {class: "source-tabs", role: "tablist", "aria-label": "Data source type"});
    const databaseTab = button("source-database-tab", "Database", "source-tab");
    const fileTab = button("source-files-tab", "Upload file", "source-tab");
    for (const [tab, id] of [[databaseTab, "source-database-panel"], [fileTab, "source-files-panel"]]) {
      tab.setAttribute("role", "tab"); tab.setAttribute("aria-controls", id); tabs.append(tab);
    }
    const databasePanel = node("section", {id: "source-database-panel", class: "source-database-panel", role: "tabpanel", "aria-labelledby": databaseTab.id});
    const filePanel = node("section", {id: "source-files-panel", class: "source-files-panel", role: "tabpanel", "aria-labelledby": fileTab.id, hidden: true});
    const status = node("p", {id: "database-query-status", class: "source-status", role: "status"}, "Loading your datasets…");
    const sidebar = node("section", {class: "source-sidebar data-pane", id: "data-connection-pane", "data-heading": "data-connection-heading", tabindex: "0"});
    const source = node("select", {id: "database-source", "aria-label": "Database"});
    const dataset = node("select", {id: "database-dataset", "aria-label": "Dataset"});
    const datasetStatus = node("p", {id: "database-dataset-status", class: "source-hint", role: "status"});
    const reloadDatasets = button("refresh-database-datasets", "Refresh datasets", "quiet");
    const add = button("add-connection", "+ Add connection", "quiet");
    const edit = button("edit-connection", "Edit connection", "quiet"); edit.hidden = true;
    const health = node("div", {id: "database-health", class: "connection-health", "aria-live": "polite"});
    const check = button("check-database-connection", "Check connection", "quiet");
    const schema = node("div", {class: "database-schema", id: "database-schema"});
    const connectionDetails = node("details", {class: "source-connection-details"});
    const connectionSummary = node("summary", {}, "Connection details"), connectionActions = node("div", {class: "source-connection-actions"});
    const discoveryWarning = node("p", {id: "source-discovery-warning", class: "source-hint", role: "status", hidden: true});
    connectionDetails.append(connectionSummary, health, check); connectionActions.append(add, edit);
    const sourceLabel = label("Connection", source), datasetLabel = label("Dataset", dataset);
    const connectionHeading = node("h2", {id: "data-connection-heading"}, "Connection & schema");
    sidebar.append(connectionHeading, sourceLabel, connectionActions, discoveryWarning, connectionDetails,
      datasetLabel, datasetStatus, reloadDatasets, schema);
    const work = node("section", {class: "source-work data-pane", id: "data-query-pane", "data-heading": "data-query-heading", tabindex: "0"});
    const schemaBox = node("details", {class: "source-dataset-schema"}), schemaView = node("div");
    schemaBox.open = !window.matchMedia("(max-width: 600px)").matches;
    schemaBox.append(node("summary", {}, "Dataset schema"), schemaView);
    const queryHeading = node("div", {class: "source-section-heading"});
    const discardDraft = button("discard-query-draft", "Discard draft", "quiet"); discardDraft.disabled = true;
    const draftStatus = node("p", {id: "query-draft-status", class: "source-hint", role: "status"}, "Drafts are saved in this browser as you type.");
    queryHeading.append(node("h2", {id: "data-query-heading"}, "Query"), discardDraft, node("span", {class: "source-badge"}, "Cypher"));
    const sharedMovies = button("query-shared-movies", "Example: users who rated the same movies", "quiet");
    sharedMovies.hidden = true;
    const editor = node("textarea", {id: "cypher-editor", class: "code-editor", rows: "8", spellcheck: "false", "aria-label": "Cypher query", "aria-describedby": "cypher-hint"});
    const hint = node("span", {id: "cypher-hint", class: "source-hint", "aria-live": "polite"}, "Use the Neo4j nodes and relationships returned by your query, including those in returned paths.");
    const queryScope = node("p", {id: "database-query-scope", class: "source-hint", role: "status"});
    const parameters = node("textarea", {id: "cypher-parameters", class: "code-editor", rows: "3", "aria-label": "Query parameters (JSON)", spellcheck: "false"});
    const parameterBox = node("details", {class: "query-parameters"});
    parameterBox.append(node("summary", {}, "Parameters"), parameters);
    const direction = node("select", {id: "query-graph-direction", "aria-label": "Graph direction for analysis"});
    direction.append(node("option", {value: "directed"}, "Directed graph"), node("option", {value: "undirected"}, "Undirected graph"));
    const projection = node("select", {id: "query-graph-projection", "aria-label": "Graph mode", "aria-describedby": "cypher-hint"});
    projection.append(node("option", {value: "elements"}, "Existing Neo4j graph"), node("option", {value: "rows"}, "Connections from query rows"));
    const projectionField = label("Graph mode", projection); projectionField.append(hint);
    const describeProjection = () => {
      hint.textContent = projection.value === "rows"
        ? "Connect each row’s source and target nodes in the analysis graph, using its optional weight column."
        : "Use the Neo4j nodes and relationships returned by your query, including those in returned paths.";
    };
    const preview = button("preview-cypher", "Preview query");
    const saveSnapshot = button("save-query-snapshot", "Save graph to datasets");
    const discardPreview = button("discard-query-preview", "Discard preview", "quiet"); discardPreview.hidden = true;
    const open = button("run-cypher-chat", state.session ? "Use graph in chat" : "Start conversation", "primary");
    const actions = node("div", {class: "source-query-actions"});
    const options = node("div", {class: "source-query-options"});
    options.append(parameterBox, projectionField, label("Direction", direction));
    actions.append(node("span", {class: "source-hint"}, "⌘ / Ctrl + Enter to preview"), preview);
    const previewHeader = node("div", {class: "source-section-heading"});
    const count = node("span", {id: "database-preview-count", class: "source-hint"}, "No query run yet");
    previewHeader.append(node("h2", {id: "data-preview-heading"}, "Graph preview"), count);
    const previewActions = node("div", {class: "source-preview-actions", hidden: true});
    previewActions.append(saveSnapshot, discardPreview);
    const canvas = node("div", {id: "database-query-graph", class: "database-query-graph", role: "img", "aria-label": "Query graph preview"});
    const placeholder = node("div", {class: "source-preview-empty"});
    const emptyTitle = node("strong", {}, "A first look at your graph");
    const emptyDescription = node("p", {}, "Run a preview to see the connections your query returns.");
    placeholder.append(icon("graph"), emptyTitle, emptyDescription);
    const previewFrame = node("div", {class: "source-preview-frame"}); previewFrame.append(canvas, placeholder);
    const rows = node("pre", {id: "database-query-rows", class: "database-row-preview"});
    const rowDetails = node("details", {class: "query-rows"}), rowSummary = node("summary", {}, "Returned rows");
    const tableContainer = node("div", {id: "database-query-table"});
    const tableView = window.GraphMineQueryTable({api, W, node, container: tableContainer});
    rowDetails.append(rowSummary, tableContainer, rows);
    const domain = node("select", {id: "query-domain", "aria-label": "Conversation domain"});
    domain.append(...state.domains.map(d => node("option", {value: d.id}, d.name)));
    domain.value = state.session?.domain_id || "general";
    domain.disabled = Boolean(state.session);
    const continueBox = node("section", {class: "source-continue", id: "source-continue", hidden: true});
    continueBox.append(label("Conversation domain", domain), open);
    const footer = node("footer", {class: "source-footer"}), footerActions = node("div", {class: "data-footer-actions"});
    footerActions.append(actions, continueBox); footer.append(status, footerActions);
    const sync = button("sync-database", "Refresh graph from tables", "quiet");
    const jobsBox = node("div");
    const importDescription = node("p", {id: "source-import-description", class: "source-hint", hidden: true});
    work.append(queryHeading, queryScope, sharedMovies, editor, draftStatus, options, jobsBox);
    work.append(importDescription);
    sidebar.append(sync, schemaBox);
    const previewPane = node("section", {class: "source-preview data-pane", id: "data-preview-pane", "data-heading": "data-preview-heading", tabindex: "0"});
    previewPane.append(previewHeader, previewActions, previewFrame, rowDetails);
    const grid = node("div", {class: "database-grid"}); grid.append(sidebar, work, previewPane);
    const stepControls = node("div");
    const connectionEditor = node("section", {class: "source-connection-editor", hidden: true});
    databasePanel.append(stepControls, grid, connectionEditor, footer);
    const file = node("input", {id: "source-file-upload", type: "file", accept: ".json,.csv,.txt", "aria-label": "Choose graph file"});
    const uploadZone = node("label", {class: "source-upload-zone"});
    uploadZone.append(icon("arrow"), node("strong", {}, "Drop a file here, or browse"), node("span", {}, "Graph JSON or a CSV of relationships"), file);
    const fileKind = $("upload-kind");
    const fileStatus = node("p", {role: "status", class: "source-status"});
    const fileHeading = node("div", {class: "source-file-intro"});
    fileHeading.append(node("h3", {}, "Bring a file to the conversation"), node("p", {}, "Your file becomes the input for questions, calculations and graph exploration."));
    filePanel.append(fileHeading, uploadZone, fileStatus);
    if (currentFile) filePanel.append(node("p", {class: "source-current-file"}, `${currentFile.provenance?.kind === "table" ? "Current table" : "Current input"} · ${currentFile.original_name}`));
    const fileDomain = node("select", {id: "file-domain", "aria-label": "File conversation domain"});
    fileDomain.append(...state.domains.map(d => node("option", {value: d.id}, d.name)));
    fileDomain.value = state.session?.domain_id || "general";
    if (!state.session) filePanel.append(label("Conversation domain", fileDomain));
    const fileControls = $("data-file-controls"), controlsPlace = document.createComment("Data controls");
    if (fileControls) { fileControls.before(controlsPlace); fileControls.hidden = false; filePanel.append(fileControls); }
    dialog.append(heading, tabs, databasePanel, filePanel); $("data-workspace-view").append(dialog);
    let sources = [], datasets = [], generation = 0, healthGeneration = 0, datasetGeneration = 0, sourceGeneration = 0, saved = null, cy = null, busy = false, uploading = false, benchmarks = null;
    let canManageImports = false, discoveryPending = true, datasetPickerOnly = false;
    const selectedSource = () => sources.find(item => item.id === source.value);
    const importing = () => selectedSource()?.source_kind === "connector";
    const readController = new AbortController();
    const layout = window.GraphMineDataLayout({node, host: dialog, panes: [sidebar, work, previewPane], controls: stepControls, footer, queryAction: actions, onChange: dataPartChanged, onResize: () => cy?.resize()});
    let draftContext = null, draftPresent = false, draftDirty = false;
    const provenance = currentFile?.provenance?.source;
    const remember = () => {
      if (!draftContext || !draftDirty) return;
      const persisted = drafts.put(draftContext.source, draftContext.dataset, {query: editor.value, parameters: parameters.value, direction: direction.value, projection: projection.value});
      draftDirty = false; draftPresent = true; discardDraft.disabled = busy;
      draftStatus.textContent = persisted ? "Draft saved in this browser." : "Draft saved for this tab only. Browser storage is unavailable or full.";
    };
    const resetPreview = () => {
      generation++; saved = null; cy?.destroy(); cy = null; canvas.replaceChildren();
      tableView.setSnapshot(null); rows.hidden = false; previewFrame.hidden = false;
      previewHeader.querySelector("h2").textContent = "Graph preview";
      rows.textContent = ""; placeholder.hidden = false; count.textContent = "No query run yet";
      rowSummary.textContent = "Returned rows"; rowDetails.open = false;
      emptyTitle.textContent = "A first look at your graph";
      emptyDescription.textContent = "Run a preview to see the connections your query returns.";
      continueBox.hidden = previewActions.hidden = true; discardPreview.hidden = true; open.disabled = true;
    };
    const invalidate = () => { resetPreview(); draftDirty = true; remember(); status.textContent = "Query changed. Preview it to update the graph."; };
    const queryTools = window.GraphMineQueryEditor({api, node, W, editor, parameters, parameterBox, onChange: invalidate});
    const jobs = window.GraphMineQueryProgress({api, W, node, container: jobsBox});
    const finish = () => {
      if (!dialog.isConnected) return;
      if (source.value) remember();
      window.removeEventListener("pagehide", remember);
      generation++; healthGeneration++; datasetGeneration++; sourceGeneration++; readController.abort(); cy?.destroy(); benchmarks?.destroy(); queryTools.destroy(); tableView.destroy(); jobs.destroy(); layout.destroy();
      if (fileControls) { fileControls.hidden = true; controlsPlace.replaceWith(fileControls); }
      dialog.remove(); opening = false; closeDialog = null; selectPart = null;
    };
    close.onclick = () => { finish(); leaveData(); requestAnimationFrame(() => { if (focusBefore?.isConnected && focusBefore.getClientRects().length) focusBefore.focus(); }); };
    window.addEventListener("pagehide", remember);
    closeDialog = finish;
    const tab = (name, part = layout.current()) => {
      const isDatabase = name === "database";
      databasePanel.hidden = !isDatabase; filePanel.hidden = name !== "files";
      databaseTab.setAttribute("aria-selected", String(isDatabase)); databaseTab.tabIndex = isDatabase ? 0 : -1;
      fileTab.setAttribute("aria-selected", String(name === "files")); fileTab.tabIndex = name === "files" ? 0 : -1;
      layout.active(isDatabase && connectionEditor.hidden);
      if (isDatabase && connectionEditor.hidden) layout.select(part);
      else if (!isDatabase) dataPartChanged("files");
    };
    selectPart = part => tab(part === "files" ? "files" : "database", part === "files" ? layout.current() : part);
    databaseTab.onclick = () => tab("database"); fileTab.onclick = () => tab("files");
    tabs.onkeydown = event => {
      if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
        event.preventDefault(); const choices = [databaseTab, fileTab], index = choices.indexOf(document.activeElement);
        const next = event.key === "Home" ? databaseTab : event.key === "End" ? fileTab : choices[(index + 1) % 2];
        next.click(); next.focus();
      }
    };
    editor.oninput = parameters.oninput = direction.onchange = invalidate;
    projection.onchange = () => { describeProjection(); invalidate(); };
    sharedMovies.onclick = () => {
      editor.value = [
        "MATCH (u:User)",
        "WITH u ORDER BY u.userId LIMIT $userLimit",
        "MATCH (u)-[:RATED]->(m:Movie)",
        "WITH m, collect(DISTINCT u) AS users",
        "UNWIND users AS a",
        "UNWIND users AS b",
        "WITH a, b WHERE a.userId < b.userId",
        "RETURN a AS source, b AS target,",
        "       count(*) AS weight, 'SHARED_MOVIE' AS type",
        "ORDER BY source.userId, target.userId"
      ].join("\n");
      parameters.value = '{"userLimit": 100}'; parameterBox.open = true;
      projection.value = "rows"; direction.value = "undirected";
      describeProjection(); invalidate();
      queryTools.sync();
    };
    const setBusy = value => {
      busy = value; value = value || discoveryPending;
      const unavailable = !source.value || datasets.find(d => d.id === dataset.value)?.status !== "ready";
      const snapshot = saved?.kind === "connector" ? saved.dataset || saved.checked : saved?.response?.dataset || saved?.response?.table;
      preview.disabled = value || unavailable;
      open.disabled = value || unavailable || !snapshot || !domain.value || Boolean(saved?.response?.table && !saved.response.row_count);
      open.textContent = saved?.response?.table ? "Use table in analysis" : state.session ? "Use graph in chat" : "Start conversation";
      const canSave = saved?.kind === "connector" ? Boolean(saved.checked && !saved.dataset) : snapshot?.temporary;
      saveSnapshot.disabled = value || !canSave;
      saveSnapshot.textContent = canSave ? saved?.response?.table ? "Save table to datasets" : "Save graph to datasets" : "Saved in datasets";
      discardPreview.disabled = value;
      discardDraft.disabled = value || !draftPresent;
      queryTools.setBusy(value);
      dataset.disabled = reloadDatasets.disabled = value;
      source.disabled = edit.disabled = value;
      add.disabled = value;
      editor.disabled = parameters.disabled = direction.disabled = projection.disabled = sharedMovies.disabled = value || unavailable;
      sync.hidden = datasetPickerOnly || importing() || dataset.value !== "default" || selectedSource()?.capabilities?.sync === false;
      sync.disabled = value || !selectedSource()?.entities?.length;
      check.disabled = value || unavailable || importing();
      layout.ready(!unavailable && !value);
    };
    const endpointCard = (title, endpoint, result) => {
      const card = node("div", {class: "connection-endpoint"});
      card.append(node("strong", {}, title), node("span", {}, endpoint || "Server configured"));
      const state = node("span", {class: "connection-state", "data-state": result ? result.connected ? "connected" : "error" : "checking"}, result ? result.connected ? "Connected" : "Unavailable" : "Checking…");
      if (result?.message) state.title = result.message;
      card.append(state); return card;
    };
    function renderHealth(result) {
      const selected = sources.find(s => s.id === source.value);
      if (!selected) { health.replaceChildren(); return; }
      const connection = selected.connection || {}, sql = connection.sql || {}, neo = connection.neo4j || {};
      const sqlConfigured = selected.capabilities?.sql ?? Boolean(selected.sql_type);
      connectionSummary.textContent = result ? `Connection details · ${result.neo4j?.connected ? sqlConfigured && !result.sql?.connected ? "Neo4j ready · SQL unavailable" : "Connected" : "Check Neo4j"}` : "Connection details · Checking…";
      health.replaceChildren(endpointCard("Neo4j", (neo.uri || "") + (neo.database ? ` / ${neo.database}` : ""), result?.neo4j));
      if (sqlConfigured) health.append(endpointCard(selected.sql_type === "sqlite" ? "SQLite" : "PostgreSQL", [sql.host, sql.port].filter(Boolean).join(":") + (sql.database ? ` / ${sql.database}` : ""), result?.sql));
      else health.append(node("p", {class: "source-hint"}, "SQL enrichment is optional and is not configured."));
    }
    async function checkHealth() {
      if (!source.value || importing()) return;
      const id = source.value, current = ++healthGeneration; renderHealth();
      try {
        const result = await api(`/api/database-sources/${encodeURIComponent(id)}/status`, {method: "POST", signal: readController.signal});
        if (current === healthGeneration && dialog.isConnected && source.value === id) renderHealth(result);
      } catch (error) {
        if (current !== healthGeneration || !dialog.isConnected) return;
        renderHealth({sql: {connected: false, message: error.message}, neo4j: {connected: false, message: error.message}});
      }
    }
    async function openSource() {
      if (!source.value || importing()) return;
      const id = source.value, current = ++healthGeneration;
      let timer = null, polling = false, observing = true, after = 0;
      setBusy(true); status.textContent = "Connecting to the database…";
      try {
        const initial = await api("/api/database-progress", {signal: readController.signal});
        after = initial.after;
        timer = setInterval(async () => {
          if (polling || !observing || !dialog.isConnected || current !== healthGeneration) return;
          polling = true;
          try {
            const update = await api(`/api/database-progress?after=${after}`, {signal: readController.signal});
            after = update.after;
            if (observing && dialog.isConnected && current === healthGeneration) {
              for (const event of update.events) if (event.type === "database.power") status.textContent = event.payload.message;
            }
          } catch (_) { /* The action response reports connection failures. */ }
          finally { polling = false; }
        }, 500);
        const result = await api(`/api/database-sources/${encodeURIComponent(id)}/open`, {method: "POST", signal: readController.signal});
        if (current === healthGeneration && dialog.isConnected && source.value === id) {
          renderHealth(result);
          status.textContent = result.neo4j?.connected ? "Database is ready." : result.neo4j?.message || "The database is unavailable.";
        }
      } catch (error) {
        if (current === healthGeneration && dialog.isConnected && error.name !== "AbortError") {
          status.textContent = error.message;
          renderHealth({neo4j: {connected: false, message: error.message}});
        }
      } finally {
        observing = false; clearInterval(timer);
        if (current === healthGeneration && dialog.isConnected) setBusy(false);
      }
    }
    const defaultQuery = item => item?.entities?.length
      ? `MATCH p = (a:${item.entities[0].label})-[r${item.relationships?.length ? ":" + item.relationships[0].label : ""}]->(b)\nRETURN p\nLIMIT 1000`
      : "MATCH p = (a)-[r]->(b)\nRETURN p\nLIMIT 1000";
    function restoreDraft(useSaved = true) {
      const selected = datasets.find(d => d.id === dataset.value);
      draftContext = selected ? {source: source.value, dataset: dataset.value} : null;
      const draft = useSaved && draftContext ? drafts.get(source.value, dataset.value) : null;
      const sameInput = provenance?.database_source?.id === source.value && (provenance?.database_dataset?.id || "default") === dataset.value;
      editor.value = draft?.query ?? (sameInput ? provenance.query : null) ?? selected?.default_query ?? defaultQuery(sources.find(s => s.id === source.value));
      parameters.value = draft?.parameters ?? W.stringify(sameInput ? provenance.parameters || {} : {}, true);
      direction.value = draft?.direction ?? (sameInput && currentFile?.metadata?.directed === false ? "undirected" : "directed");
      projection.value = draft?.projection ?? (sameInput ? provenance.projection : null) ?? "elements";
      draftDirty = false; draftPresent = Boolean(draft);
      draftStatus.textContent = draft ? draft.persisted ? "Draft restored from this browser." : "Draft restored for this tab only. Browser storage is unavailable or full." : "Drafts are saved in this browser as you type.";
      if (draftContext) drafts.select(source.value, dataset.value);
    }
    discardDraft.onclick = () => {
      if (!draftContext || busy) return;
      const discarded = drafts.discard(draftContext.source, draftContext.dataset);
      restoreDraft(false); describeProjection(); resetPreview(); setBusy(false);
      queryTools.sync();
      draftStatus.textContent = discarded ? "Draft discarded. The starting query has been restored." : "Draft cleared for this tab. Browser storage could not be updated.";
    };
    function describeDataset(preserve = false) {
      resetPreview(); benchmarks?.destroy();
      const selected = datasets.find(d => d.id === dataset.value);
      queryScope.textContent = selected?.status === "ready" ? `Queries run only on ${selected.name}.` : "Choose a ready dataset to run a query.";
      schemaView.replaceChildren();
      schemaBox.hidden = !selected;
      if (!preserve || draftContext?.source !== source.value || draftContext?.dataset !== dataset.value) restoreDraft();
      queryTools.setContext(source.value, dataset.value, selected?.status === "ready");
      sharedMovies.hidden = selected?.id !== "movielens-32m";
      describeProjection();
      datasetStatus.textContent = !selected ? datasetPickerOnly ? "Choose an available dataset." : "No datasets are available in this connection."
        : selected.status === "ready" ? selected.node_count != null
          ? `${selected.node_count.toLocaleString()} nodes · ${selected.relationship_count.toLocaleString()} relationships`
          : "Ready to query"
        : selected.status === "mapping_needed" ? "SQL tables found. Add their graph mapping to this connection."
        : selected.status === "preparing_graph" ? "Tables imported. Preparing the Neo4j graph…"
        : "Importing this dataset…";
      if (selected?.source_notes?.length) datasetStatus.textContent += " See source data notes for gaps in the published files.";
      if (selected?.discovery_warning) datasetStatus.textContent += " " + selected.discovery_warning;
      if (selected) benchmarks = window.GraphMineBenchmarkDatasets({api, node, container: schemaView, dataset: selected});
      status.textContent = selected?.status !== "ready" ? datasetStatus.textContent
        : state.session ? "Preview the graph, then use it in this conversation."
        : "Preview the graph, then choose a domain to start your conversation.";
      remember(); setBusy(false);
    }
    async function describe(restore = false, preserve = false) {
      resetPreview(); schema.replaceChildren();
      const selected = sources.find(s => s.id === source.value);
      const isImport = importing();
      queryTools.setVisible(!isImport);
      healthGeneration++; datasetGeneration++;
      for (const element of [queryScope, hint, editor, draftStatus, options, jobsBox, discardDraft]) element.hidden = isImport;
      importDescription.hidden = !isImport;
      queryHeading.querySelector("h2").textContent = isImport ? "Import" : "Query";
      queryHeading.querySelector(".source-badge").textContent = isImport ? selected.type === "sqlite" ? "SQLite" : selected.type === "rest" ? "REST API" : "HTTP export" : "Cypher";
      actions.firstElementChild.hidden = isImport;
      preview.textContent = isImport ? "Preview source" : "Preview query";
      check.hidden = isImport;
      layout.mode?.(isImport ? "import" : "query");
      jobs.setContext(isImport ? null : selected?.id || null);
      edit.hidden = datasetPickerOnly || !selected?.managed; setBusy(false);
      if (isImport) {
        draftContext = null; draftDirty = false; draftPresent = false;
        queryTools.setContext(null, null, false); benchmarks?.destroy();
        schemaBox.hidden = true; sharedMovies.hidden = true;
        datasets = [{id: "import", name: "Source snapshot", status: "ready"}]; dataset.replaceChildren(node("option", {value: "import"}, "Source snapshot"));
        drafts.select(source.value, "import");
        datasetStatus.textContent = selected.type === "sqlite" ? "Read the selected table from its saved SQLite copy." : "Import the response from this saved connection.";
        importDescription.textContent = "Preview the graph, then save a complete retained version or use it in a conversation. The source is checked again when importing; changed data needs a fresh preview. Edit this connection to change its mapping.";
        health.replaceChildren(node("p", {class: "source-hint"}, "Preview checks access and reports the source scope. No Cypher or SQL service is required for this import."));
        connectionSummary.textContent = "Connection details";
        status.textContent = "Preview this source before importing.";
        setBusy(false); return true;
      }
      if (!selected) {
        editor.value = defaultQuery(); parameters.value = "{}";
        status.textContent = datasetPickerOnly ? "Choose a dataset, or upload a file to get started." : "Add a database connection, or choose Upload file to get started.";
        health.replaceChildren(); connectionSummary.textContent = "Connection details"; datasets = []; dataset.replaceChildren(); describeDataset(); return;
      }
      checkHealth(); setBusy(true); datasetStatus.textContent = datasetPickerOnly ? "Loading dataset details…" : "Loading datasets from this database…";
      queryScope.textContent = `Selecting ${selected.name}…`;
      const current = ++datasetGeneration, selectedId = selected.id;
      try {
        const entries = await api(`/api/database-sources/${encodeURIComponent(selected.id)}/datasets`, {signal: readController.signal});
        if (current !== datasetGeneration || !dialog.isConnected || source.value !== selectedId) return;
        const wanted = (restore && draftSelection?.source === selected.id ? draftSelection.dataset : null)
          || dataset.value || drafts.selection(selected.id)?.dataset
          || (provenance?.database_source?.id === selected.id ? provenance.database_dataset?.id : null) || "default";
        datasets = entries;
        dataset.replaceChildren(...datasets.map(d => node("option", {value: d.id}, d.name + (d.status === "ready" ? "" : d.status === "mapping_needed" ? " · mapping needed" : " · importing"))));
        if (datasets.some(d => d.id === wanted)) dataset.value = wanted;
        describeDataset(preserve);
        return true;
      } catch (error) {
        if (current === datasetGeneration && dialog.isConnected) { datasets = []; dataset.replaceChildren(); datasetStatus.textContent = error.message; setBusy(false); }
      }
    }
    source.onchange = async () => { remember(); dataset.replaceChildren(); await describe(); await openSource(); };
    dataset.onchange = () => { remember(); describeDataset(); };
    reloadDatasets.onclick = async () => { try { if (await refresh(source.value)) await describe(false, true); } catch (error) { if (dialog.isConnected) datasetStatus.textContent = error.message; } };
    check.onclick = openSource;
    const refresh = async selected => {
      const current = ++sourceGeneration;
      discoveryPending = true; setBusy(busy);
      try {
        let response;
        try { response = await api("/api/data-sources", {signal: readController.signal}); }
        catch (error) {
          if (error.status !== 404) throw error;
          const entries = await api("/api/database-sources", {signal: readController.signal});
          response = {items: entries.map(entry => ({provider: "database", connection: entry})), warnings: []};
        }
        if (current !== sourceGeneration || !dialog.isConnected) return false;
        const backend = response.active_backend || "local";
        if (!drafts || draftBackend !== backend) {
          if (drafts) { draftContext = null; resetPreview(); selected = null; }
          drafts = await window.GraphMineQueryDrafts({base: state.base, token: state.token, userId: window.GraphMineAccount?.user?.id, conversationId: state.session?.id || "new", inputId: currentFile?.id || state.active, backendId: backend});
          if (current !== sourceGeneration || !dialog.isConnected) return false;
          draftBackend = backend; draftSelection = drafts.selection();
          selected = draftSelection?.source || selected;
        }
        canManageImports = Boolean(response.can_manage_imports);
        datasetPickerOnly = Boolean(response.dataset_picker_only);
        sourceLabel.firstChild.nodeValue = datasetPickerOnly ? "Dataset" : "Connection";
        source.setAttribute("aria-label", datasetPickerOnly ? "Dataset" : "Database");
        connectionHeading.textContent = datasetPickerOnly ? "Dataset & schema" : "Connection & schema";
        databaseTab.textContent = datasetPickerOnly ? "Datasets" : "Database";
        connectionActions.hidden = connectionDetails.hidden = datasetLabel.hidden = datasetPickerOnly;
        layout.datasetPicker?.(datasetPickerOnly);
        sources = response.items.map(item => item.provider === "database" ? item.connection : {...item, id: `connector:${item.source_id}`, connector_id: item.source_id, source_kind: "connector"});
        discoveryWarning.textContent = (response.warnings || []).map(warning => warning.message).join(" "); discoveryWarning.hidden = !discoveryWarning.textContent;
        source.replaceChildren(...sources.map(s => node("option", {value: s.id}, s.name + (datasetPickerOnly ? "" : s.source_kind === "connector" ? ` · ${s.type === "rest" ? "REST API" : s.type === "sqlite" ? "SQLite" : "Neo4j HTTP export"}` : " · Neo4j"))));
        if (sources.some(s => s.id === selected)) source.value = selected;
        else if (selected) source.value = "";
        return true;
      } finally {
        if (current === sourceGeneration) { discoveryPending = false; setBusy(busy); }
      }
    };
    const settings = async existing => {
      try {
        const selected = selectedSource(), selectedId = source.value;
        const detail = existing ? selected?.source_kind === "connector"
          ? {...await api(`/api/connectors/${encodeURIComponent(selected.connector_id)}`, {signal: readController.signal}), source_kind: "connector"}
          : await api(`/api/database-sources/${encodeURIComponent(source.value)}/settings`, {signal: readController.signal}) : null;
        if (!dialog.isConnected || existing && source.value !== selectedId) return;
        layout.active(false); grid.hidden = footer.hidden = stepControls.hidden = true; connectionEditor.hidden = false;
        window.GraphMineConnectionSettings({api, W, node, container: connectionEditor, source: detail, canManageImports,
          onCancel: () => { connectionEditor.replaceChildren(); connectionEditor.hidden = true; grid.hidden = footer.hidden = false; layout.active(true); layout.select("connection"); },
          onSaved: async result => {
            if (!await refresh(result?.source_kind === "connector" ? `connector:${result.id}` : result?.id)) return;
            connectionEditor.replaceChildren(); connectionEditor.hidden = true; grid.hidden = footer.hidden = false; layout.active(!databasePanel.hidden); if (!databasePanel.hidden) layout.select("connection"); dataset.replaceChildren(); await describe(false, Boolean(existing && result)); if (result && !importing()) renderHealth(result.status);
          }});
      } catch (error) { status.textContent = error.message; }
    };
    add.onclick = () => settings(false); edit.onclick = () => settings(true);
    function readQuery() {
      if (!selectedSource() || datasets.find(d => d.id === dataset.value)?.status !== "ready") throw new Error("Choose a ready dataset first.");
      let values;
      try {
        values = W.parse(parameters.value || "{}");
        if (!values || Array.isArray(values) || typeof values !== "object") throw new Error("Parameters must be a JSON object.");
        queryTools.validate();
      } catch (error) { error.code = "cypher_parameters"; throw error; }
      const body = {statement: editor.value, parameters: values, directed: direction.value === "directed", dataset_id: dataset.value, projection: projection.value};
      if (!body.statement.trim()) throw new Error("Write a Cypher query first.");
      return body;
    }
    async function query() {
      if (importing()) return previewConnector();
      const body = readQuery(); queryTools.sync();
      const signature = source.value + W.stringify(body);
      resetPreview(); const current = generation;
      status.textContent = `Running your query on ${datasets.find(d => d.id === dataset.value).name}…`;
      const response = await jobs.execute(`/api/database-sources/${encodeURIComponent(source.value)}/queries`, body);
      if (current !== generation || !dialog.isConnected) return null;
      return renderQuery(response, signature);
    }
    function renderQuery(response, signature) {
      saved = {signature, response};
      const snapshot = response.dataset || response.table;
      continueBox.hidden = !snapshot;
      previewActions.hidden = !snapshot;
      discardPreview.hidden = !snapshot?.temporary;
      count.textContent = response.table ? `Query: ${response.row_count.toLocaleString()} rows · ${response.table.table.columns.length} columns` : `Query: ${response.row_count.toLocaleString()} rows · ${response.vertex_count.toLocaleString()} nodes · ${response.edge_count.toLocaleString()} relationships`;
      status.textContent = response.dataset ? `${response.row_count.toLocaleString()} rows returned${response.elapsed_ms != null ? ` in ${(response.elapsed_ms / 1000).toFixed(2)}s` : ""}. Ready to use in chat.` : response.message;
      if (snapshot?.temporary) status.textContent += " This preview expires in 24 hours. Save it or use it in analysis to keep it.";
      if (response.row_sample_warning) status.textContent += " " + response.row_sample_warning;
      rows.textContent = W.stringify(response.rows, true);
      rowSummary.textContent = response.table ? `Complete query table · ${response.row_count.toLocaleString()} rows` : `Returned rows · ${response.row_count.toLocaleString()}${response.rows_truncated ? ` (showing first ${response.rows.length})` : ""}`;
      rowDetails.open = !response.dataset;
      rows.hidden = previewFrame.hidden = Boolean(response.table);
      previewHeader.querySelector("h2").textContent = response.table ? "Table preview" : "Graph preview";
      tableView.setSnapshot(response.table || null);
      const graph = response.graph;
      placeholder.hidden = Boolean(graph.vertices.length);
      emptyTitle.textContent = graph.preview_skipped ? "Graph preview skipped" : response.row_count ? "Table results" : "No matches";
      emptyDescription.textContent = graph.preview_skipped ? graph.preview_message : response.row_count
        ? `${response.row_count.toLocaleString()} rows returned. View them below, or return graph elements to build a graph.`
        : "Check the connection, labels, filters and parameter values.";
      if (!databasePanel.hidden) layout.select("preview");
      if (!graph.preview_skipped) drawPreview(graph);
      if (graph.preview_skipped) status.textContent += ` ${graph.preview_message}`;
      else if (graph.vertices.length < response.vertex_count || graph.edges.length < response.edge_count) status.textContent += ` Visible preview: ${graph.vertices.length} nodes and ${graph.edges.length} relationships. Chat uses the full query result.`;
      return response;
    }
    function drawPreview(graph) {
      if (graph.vertices.length && !window.cytoscape) {
        const current = generation;
        window.GraphMineGraphLibrary().then(() => {
          if (current === generation && canvas.isConnected) drawPreview(graph);
        }).catch(error => { if (current === generation && canvas.isConnected) status.textContent = error.message; });
        return;
      }
      if (window.cytoscape && graph.vertices.length) cy = window.cytoscape({container: canvas, elements: [
        ...graph.vertices.map(v => ({data: {id: W.idKey(v.id), label: v.label || v.type || String(v.id)}})),
        ...graph.edges.map((e, i) => ({data: {id: `edge:${i}`, source: W.idKey(e.source), target: W.idKey(e.target)}}))
      ], style: [{selector: "node", style: {label: "data(label)", "font-size": 10, "background-color": "#35775c", color: "#234638", "text-margin-y": 6, "text-valign": "bottom", width: 22, height: 22}}, {selector: "edge", style: {"target-arrow-shape": graph.graph.directed ? "triangle" : "none", "curve-style": "bezier", width: 1.5, "line-color": "#b9cdc1", "target-arrow-color": "#b9cdc1"}}], layout: {name: "cose", animate: false, padding: 30}});
    }
    async function previewConnector() {
      const selected = selectedSource(); resetPreview(); const current = generation;
      status.textContent = "Reading the source…";
      const result = await api(`/api/connectors/${encodeURIComponent(selected.connector_id)}/preview`, {method: "POST", signal: readController.signal});
      if (current !== generation || !dialog.isConnected || source.value !== selected.id) return;
      saved = {kind: "connector", connector_id: selected.connector_id, checked: result, dataset: null};
      count.textContent = `${result.metadata.vertex_count.toLocaleString()} vertices · ${result.metadata.edge_count.toLocaleString()} connections`;
      status.textContent = `${result.source_complete ? "Complete within this scope" : "The upstream may contain more records"}: ${result.source_scope}. Visible preview: ${result.vertices.length} vertices and ${result.edges.length} connections. Import retains the full checked graph.`;
      continueBox.hidden = previewActions.hidden = false; discardPreview.hidden = true;
      rowSummary.textContent = "Source preview"; rows.textContent = W.stringify({vertices: result.vertices, edges: result.edges}, true);
      placeholder.hidden = Boolean(result.vertices.length);
      if (!result.vertices.length) { emptyTitle.textContent = "No graph elements"; emptyDescription.textContent = "Check the source mapping and returned records."; }
      if (!databasePanel.hidden) layout.select("preview");
      drawPreview({vertices: result.vertices, edges: result.edges, graph: {directed: result.metadata.directed}});
    }
    async function saveConnector() {
      const selection = saved;
      if (selection?.kind !== "connector") return null;
      if (selection.dataset) return selection.dataset;
      const metadata = await api(`/api/connectors/${encodeURIComponent(selection.connector_id)}/import`, {method: "POST", body: W.stringify({name: selection.checked.name, expected_sha256: selection.checked.sha256})});
      if (!dialog.isConnected || selection !== saved) return null;
      selection.dataset = metadata;
      status.textContent = `Saved ${metadata.name}, version ${metadata.version}. This exact snapshot is available in the Dataset library.`;
      return metadata;
    }
    const action = async fn => {
      if (busy) return;
      setBusy(true); status.classList.remove("source-error");
      try { await fn(); } catch (error) { if (dialog.isConnected) { status.textContent = error.message; status.classList.add("source-error"); if (!databasePanel.hidden) layout.select("query"); queryTools.error(error); } }
      finally { if (dialog.isConnected) setBusy(false); }
    };
    preview.onclick = () => action(query);
    saveSnapshot.onclick = () => action(async () => {
      if (saved?.kind === "connector") { await saveConnector(); return; }
      const response = saved?.response;
      const snapshot = response?.dataset || response?.table;
      if (!snapshot?.temporary) return;
      const metadata = await api(`/api/database-query-snapshots/${snapshot.id}/save`, {method: "POST"});
      if (!dialog.isConnected || response !== saved?.response) return;
      response[response.table ? "table" : "dataset"] = metadata; discardPreview.hidden = true;
      status.textContent = `${response.table ? "Table" : "Graph"} saved to your datasets. You can reuse this exact snapshot at any time.`;
    });
    discardPreview.onclick = () => action(async () => {
      const response = saved?.response;
      const snapshot = response?.dataset || response?.table;
      if (!snapshot?.temporary) return;
      await api(`/api/database-query-snapshots/${snapshot.id}`, {method: "DELETE"});
      if (!dialog.isConnected || response !== saved?.response) return;
      resetPreview(); status.textContent = "Preview discarded. Your query is still here.";
    });
    editor.onkeydown = event => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); preview.click(); } };
    open.onclick = () => action(async () => {
      const sessionId = state.session?.id, epoch = state.epoch;
      const fromConnector = saved?.kind === "connector";
      const response = saved?.response, snapshot = fromConnector ? await saveConnector() : response?.dataset || response?.table;
      if (!dialog.isConnected || state.epoch !== epoch) return;
      if (!snapshot) return;
      let tableFileId = null;
      if (sessionId && epoch === state.epoch) {
        const imported = await api(`/api/sessions/${sessionId}/datasets/${snapshot.id}/import`, {method: "POST"});
        if (!dialog.isConnected || state.session?.id !== sessionId || state.epoch !== epoch) return;
        state.files.push(imported.file); state.kinds[imported.file.id] = imported.kind;
        if (imported.kind === "table") { tableFileId = imported.file.id; renderFiles(); }
        else { state.active = imported.file.id; state.record = null; clearResults(); renderFiles(); await previewActive(); }
      } else if (!sessionId) {
        const result = await api(`/api/${fromConnector ? "datasets" : "database-query-snapshots"}/${snapshot.id}/chat`, {method: "POST", body: W.stringify({domain_id: domain.value})});
        if (!dialog.isConnected) return;
        await openSession(result.session.id); await loadSessions();
        if (result.kind === "table") tableFileId = result.file.id;
      } else return;
      finish(); go("chat");
      if (tableFileId) { document.dispatchEvent(new CustomEvent("graphmine:project-table", {detail: {fileId: tableFileId}})); notice("Table added. Choose the columns that form your graph."); }
      else { $("question").focus(); notice("Your graph is ready. Ask what you want to discover."); }
    });
    sync.onclick = () => action(async () => {
      resetPreview(); status.textContent = "Refreshing the graph from your database tables…";
      const result = await jobs.execute(`/api/database-sources/${encodeURIComponent(source.value)}/sync`);
      if (dialog.isConnected) status.textContent = `Graph refreshed: ${jobs.synchronizationSummary(result)}. Preview your query to see the updated graph.`;
    });
    async function importFile(selected) {
      if (!selected || uploading) return;
      const initialEpoch = state.epoch;
      uploading = true; file.disabled = true; fileStatus.textContent = `Uploading ${selected.name}…`;
      try {
        if (!state.session) {
          const session = await api("/api/sessions", {method: "POST", body: W.stringify({domain_id: fileDomain.value || "general", title: selected.name})});
          if (!dialog.isConnected || state.epoch !== initialEpoch) return;
          await openSession(session.id); await loadSessions();
        }
        if (!dialog.isConnected) return;
        const imported = await upload(selected, fileKind.value);
        if (!imported) { fileStatus.textContent = "Upload cancelled. Choose a file when you’re ready."; return; }
        if (!dialog.isConnected) return;
        state.record = null; clearResults(); await previewActive();
        finish(); go("chat"); $("question").focus();
      } catch (error) { fileStatus.textContent = error.message; fileStatus.classList.add("source-error"); }
      finally { uploading = false; file.disabled = false; file.value = ""; }
    }
    file.onchange = () => importFile(file.files[0]);
    uploadZone.ondragover = event => { event.preventDefault(); uploadZone.classList.add("drag-over"); };
    uploadZone.ondragleave = () => uploadZone.classList.remove("drag-over");
    uploadZone.ondrop = event => { event.preventDefault(); uploadZone.classList.remove("drag-over"); importFile(event.dataTransfer.files[0]); };
    selectPart(pendingPart); setBusy(false); opening = false;
    $("data-source-title").focus({preventScroll: true});
    async function discover() {
      try {
        if (!await refresh(draftSelection?.source || provenance?.database_source?.id || (provenance?.connector_id ? `connector:${provenance.connector_id}` : null))) return;
        if (dialog.isConnected) await describe(true);
      } catch (error) {
        if (!dialog.isConnected || error.name === "AbortError") return;
        status.textContent = error.message; status.classList.add("source-error"); setBusy(false);
      }
    }
    // Discovery belongs to this page; it must not hold the app's navigation.
    void discover();
  }
  launch.onclick = nav.onclick = () => show();
  document.addEventListener("graphmine:open-data-source", () => show());
  return {show, mount, close: closeWorkspace};
};
