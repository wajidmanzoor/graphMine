"use strict";
window.GraphMineSemanticRefinement = ({state, api, W, node, openSession, loadSessions, go, renderFiles, previewActive, clearResults, notice}) => {
  let closeActive = null, opening = 0;
  const button = (id, text, style = "secondary") => node("button", {id, type: "button", class: style}, text);
  const label = (text, field) => { const el = node("label", {}, text); el.append(field); return el; };
  function close() { opening++; closeActive?.(); closeActive = null; }
  async function open(baseId, recorded = null, domainId = "general") {
    close();
    const requestId = opening, epoch = state.epoch, sessionId = state.session?.id, identity = [state.base, state.token].join("\n");
    const focusBefore = document.activeElement;
    const dialog = node("dialog", {id: "semantic-refinement", class: "semantic-dialog", "aria-labelledby": "semantic-title"});
    const header = node("header", {class: "section-heading"}), dismiss = button("close-semantic", "Close", "quiet");
    header.append(node("h2", {id: "semantic-title"}, "Refine saved snapshot"), dismiss);
    const status = node("p", {id: "semantic-status", role: "status"}, "Loading the complete snapshot schema…");
    const warning = node("p", {class: "semantic-notice"}, "Plain snapshot reads and explicit mocks are available. Live models await engine fixes. Each successful run creates a new version.");
    const nav = node("nav", {class: "semantic-navigation", "aria-label": "Refinement sections"});
    const grid = node("div", {class: "semantic-grid"});
    const schemaBox = node("section", {id: "semantic-schema", tabindex: "-1"}), work = node("section", {id: "semantic-query-pane", tabindex: "-1"}), output = node("section", {id: "semantic-output", tabindex: "-1", hidden: true});
    for (const [name, pane] of [["Schema", schemaBox], ["Query", work], ["Preview", output]]) {
      const link = button("semantic-nav-" + name.toLowerCase(), name, "quiet");
      link.onclick = () => { if (!pane.hidden) { pane.scrollIntoView({block: "start"}); pane.focus(); } }; nav.append(link);
    }
    schemaBox.append(node("h3", {}, "Snapshot schema"));
    work.append(node("h3", {}, "Semantic Cypher"));
    const fields = node("fieldset", {class: "semantic-fields", disabled: true});
    const editor = node("textarea", {id: "semantic-editor", class: "code-editor", rows: "9", spellcheck: "false", maxlength: "20000", "aria-label": "Semantic query"});
    const hint = node("p", {id: "semantic-query-hint", class: "source-hint"}, "Use Vertex with has_label(n, 'Label'). Model templates use simulated answers.");
    const syntax = node("pre", {class: "semantic-highlight", "aria-hidden": "true"});
    const syntaxDetails = node("details"); syntaxDetails.append(node("summary", {}, "Highlighted query"), syntax);
    const parameters = node("textarea", {id: "semantic-parameters", rows: "3", class: "code-editor", "aria-label": "Semantic parameters (JSON)"});
    const parameterBox = node("details"); parameterBox.append(node("summary", {}, "Parameters"), parameters);
    const templates = node("select", {id: "semantic-template", "aria-label": "Query template"}), insert = button("semantic-insert-template", "Use template");
    const templateTools = node("div", {class: "semantic-actions"}); templateTools.append(templates, insert);
    const model = node("select", {id: "semantic-model"}), limit = node("input", {id: "semantic-call-limit", type: "number", min: "1", step: "1"});
    const projection = node("select", {id: "semantic-projection"}); projection.append(node("option", {value: "elements"}, "Returned graph elements / scalar table"), node("option", {value: "rows"}, "Connections from source / target rows"));
    const direction = node("select", {id: "semantic-direction"}); direction.append(node("option", {value: ""}, "Keep snapshot direction"), node("option", {value: "directed"}, "Directed"), node("option", {value: "undirected"}, "Undirected"));
    const weight = node("input", {id: "semantic-weight", type: "text", maxlength: "128"});
    const reuse = node("input", {id: "semantic-reuse", type: "checkbox", disabled: true});
    const options = node("div", {class: "semantic-options"});
    options.append(label("Model", model), label("Call limit per expression", limit), label("Projection", projection), label("Direction", direction), label("Edge weight property (optional)", weight), label("Reuse saved answers · unavailable", reuse));
    const policyNote = node("p", {class: "source-hint"});
    const draftNote = node("p", {id: "semantic-draft-status", class: "source-hint"}), discardDraft = button("semantic-discard-draft", "Discard refinement draft", "quiet");
    fields.append(templateTools, node("label", {for: editor.id}, "Query"), editor, hint, syntaxDetails, parameterBox, options, policyNote, draftNote, discardDraft);
    const steps = node("section", {id: "semantic-steps", "aria-label": "Model steps"});
    const check = button("semantic-check", "Check query"), run = button("semantic-run", "Run refinement", "primary"); check.disabled = run.disabled = true;
    const actions = node("div", {class: "semantic-actions"}); actions.append(check, run);
    const jobsBox = node("div"); work.append(fields, steps, actions, jobsBox);
    grid.append(schemaBox, work, output); dialog.append(header, warning, nav, grid, status);
    document.body.append(dialog); dialog.showModal();
    const controller = new AbortController();
    let generation = 0, busy = false, description = null, drafts = null, result = null, cy = null, tableView = null;
    const current = () => dialog.isConnected && requestId === opening && epoch === state.epoch && sessionId === state.session?.id && identity === [state.base, state.token].join("\n");
    const jobs = window.GraphMineQueryProgress({api, W, node, container: jobsBox, prefix: "semantic-"});
    const queryTools = window.GraphMineQueryEditor({api, W, node, editor, parameters, parameterBox, prefix: "semantic-", hintId: hint.id,
      schemaLoader: () => ({entities: [{label: "Vertex", properties: description.schema.vertex_properties}], relationships: description.schema.relationships.map(r => ({label: r.table, properties: r.properties}))}), onChange: changed});
    function finish() { controller.abort(); jobs.destroy(); queryTools.destroy(); cy?.destroy(); tableView?.destroy(); dialog.close(); dialog.remove(); if (focusBefore?.isConnected) focusBefore.focus(); }
    closeActive = finish; dismiss.onclick = close; dialog.oncancel = event => { event.preventDefault(); close(); };
    function setBusy(value) { busy = value; fields.disabled = value || !description; check.disabled = run.disabled = value || !description; queryTools.setBusy(value); }
    function draft() { return {query: editor.value, parameters: parameters.value, direction: direction.value || "inherit", projection: projection.value, model: model.value, call_limit: limit.value, weight_property: weight.value}; }
    function changed() {
      generation++; result = null; cy?.destroy(); cy = null; tableView?.destroy(); tableView = null; output.replaceChildren(); output.hidden = true;
      steps.replaceChildren(node("p", {class: "source-hint"}, "Check the query to inspect its model steps. Edits require a new run."));
      syntax.replaceChildren(...window.GraphMineCypherTools.tokens(editor.value).map(t => node("span", {class: t.kind === "word" && /^llm(?:_score|_agg|_path_agg|_sg_agg)?$/i.test(t.text) ? "semantic-token-model" : "semantic-token-" + t.kind}, t.text)));
      if (drafts) {
        const value = draft(); // Preserve the existing draft contract; inherit has its own flag.
        const persisted = drafts.put("semantic", baseId, {...value, inherit_direction: !direction.value, direction: direction.value || "directed"});
        draftNote.textContent = persisted ? "Refinement draft saved for this snapshot and conversation." : "Refinement draft saved for this tab only.";
      }
      status.classList.remove("source-error"); status.textContent = "Ready to check or run this refinement.";
    }
    for (const input of [editor, parameters, model, limit, projection, direction, weight]) input.addEventListener(input.tagName === "SELECT" ? "change" : "input", changed);
    for (const name of ["input", "change"]) fields.addEventListener(name, event => { if (event.target.closest(".query-parameter-row")) changed(); });
    projection.addEventListener("change", () => { weight.disabled = projection.value === "rows"; if (weight.disabled) weight.value = ""; changed(); });
    function body() {
      queryTools.validate();
      let values;
      try { values = W.parse(parameters.value || "{}"); if (!values || Array.isArray(values) || typeof values !== "object") throw new Error(); }
      catch { parameterBox.open = true; parameters.focus(); throw new Error("Parameters must be a JSON object."); }
      const calls = Number(limit.value);
      if (!Number.isInteger(calls) || calls < 1 || calls > description.capabilities.max_mock_calls_per_expression) throw new Error(`Choose a call limit from 1 to ${description.capabilities.max_mock_calls_per_expression}.`);
      if (!editor.value.trim()) throw new Error("Write a semantic query first.");
      return {base_version_id: baseId, statement: editor.value, parameters: values, model: model.value || "qwen", call_limit: calls, reuse_answers: false,
        projection: projection.value, directed: direction.value ? direction.value === "directed" : null, weight_property: projection.value === "elements" && weight.value.trim() ? weight.value.trim() : null};
    }
    function errorState(error) {
      status.classList.add("source-error");
      const guidance = {semantic_call_limit: "Lower the input scope or raise the limit within the administrator maximum.", semantic_timeout: "Narrow the query before retrying.", semantic_syntax: "Correct the query using the loaded schema.", semantic_worker_failed: "Review the request and retry explicitly.", semantic_model_server: "The model server is unavailable. Plain snapshot reads remain available.", semantic_live_unsupported: "Select an explicit mock or remove model steps."};
      status.textContent = [error.message, guidance[error.code], "No new result was selected."].filter(Boolean).join(" ");
      queryTools.error(error);
    }
    async function action(fn) {
      if (busy || !current()) return;
      setBusy(true); status.classList.remove("source-error");
      try { await fn(); } catch (error) { if (current() && error.name !== "AbortError") errorState(error); }
      finally { if (current()) setBusy(false); }
    }
    async function inspect(request) {
      const at = generation;
      const inspected = await api("/api/semantic-queries/validate", {method: "POST", body: W.stringify(request), signal: controller.signal});
      if (!current() || generation !== at) return false;
      steps.replaceChildren(node("h3", {}, `Model steps · ${inspected.steps.length}`));
      for (const step of inspected.steps) {
        const section = node("div", {class: "semantic-step"});
        section.append(node("strong", {}, `${step.kind} · ${step.model_alias}`), node("p", {}, step.prompt), node("p", {}, "Outputs: " + step.outputs.map(o => `${o.name} ${o.type}`).join(", "))); steps.append(section);
      }
      if (!inspected.steps.length) steps.append(node("p", {}, "Plain snapshot query. No model calls."));
      steps.append(node("p", {class: "source-hint"}, inspected.message));
      return true;
    }
    check.onclick = () => action(async () => { if (await inspect(body())) status.textContent = "Query policy checked. Ready to run."; });
    run.onclick = () => action(async () => {
      const request = body(); changed(); const at = generation;
      status.textContent = "Checking the query…";
      if (!await inspect(request)) return;
      status.textContent = "Running against the complete saved snapshot. Closing stops monitoring; the job continues until it finishes or is cancelled.";
      const response = await jobs.execute("/api/semantic-queries", request);
      if (!current() || at !== generation) return;
      renderResult(response);
    });
    editor.addEventListener("keydown", event => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); run.click(); } });
    function renderResult(response) {
      result = response; const snapshot = response.dataset || response.table;
      output.hidden = false;
      output.append(node("h3", {}, response.table ? "New table preview" : "New graph preview"), node("p", {}, `${response.row_count} rows · ${response.vertex_count} vertices · ${response.edge_count} relationships`));
      output.append(window.GraphMineSemanticDetails({node, W, source: snapshot.source, versionId: snapshot.id}));
      const preview = node("div", {class: "semantic-graph", role: "img", "aria-label": "Refined graph preview"});
      if (response.dataset && response.graph.vertices.length && !response.graph.preview_skipped) {
        output.append(preview);
        window.GraphMineGraphLibrary().then(() => {
          if (!current() || result !== response) return;
          const graph = response.graph;
          cy = window.cytoscape({container: preview, elements: [
            ...graph.vertices.map(v => ({data: {id: W.idKey(v.id), label: String(v.label || v.type || v.id)}})),
            ...graph.edges.map((e, i) => ({data: {id: `edge:${i}`, source: W.idKey(e.source), target: W.idKey(e.target)}}))],
            maxZoom: 2, style: [{selector: "node", style: {label: "data(label)", "font-size": 11, "background-color": "#35775c", color: "#234638"}}, {selector: "edge", style: {"target-arrow-shape": graph.graph.directed ? "triangle" : "none", "curve-style": "bezier"}}], layout: {name: "cose", animate: false}});
        }).catch(error => { if (current() && result === response) preview.textContent = error.message; });
      }
      if (response.dataset) output.append(node("p", {class: "source-hint"}, `Visible graph: ${response.graph.vertices.length} vertices and ${response.graph.edges.length} relationships. Save and chat use the complete result.`));
      const rows = node("details"); rows.open = Boolean(response.table); rows.append(node("summary", {}, `Returned rows${response.rows_truncated ? " · limited sample" : ""}`));
      if (response.table) { const host = node("div"); rows.append(host); tableView = window.GraphMineQueryTable({api, W, node, container: host}); tableView.setSnapshot(snapshot); }
      else rows.append(node("pre", {tabindex: "0"}, W.stringify(response.rows, true)));
      output.append(rows);
      const save = button("semantic-save", "Save version to datasets"), use = button("semantic-use", response.table ? "Use table in chat" : "Use graph in chat", "primary"), discard = button("semantic-discard", "Discard result", "quiet");
      const resultActions = node("div", {class: "semantic-actions"}); resultActions.append(save, use, discard); output.append(resultActions);
      save.disabled = !snapshot.temporary; discard.hidden = !snapshot.temporary;
      save.onclick = () => action(async () => {
        await api(`/api/database-query-snapshots/${encodeURIComponent(snapshot.id)}/save`, {method: "POST"});
        if (current() && result === response) { save.disabled = true; discard.hidden = true; status.textContent = "Version saved to datasets. The original snapshot is unchanged."; }
      });
      discard.onclick = () => action(async () => {
        await api(`/api/database-query-snapshots/${encodeURIComponent(snapshot.id)}`, {method: "DELETE"});
        if (current() && result === response) changed();
      });
      use.onclick = () => action(async () => {
        const id = snapshot.id; let tableFileId = null;
        if (sessionId) {
          const imported = await api(`/api/sessions/${encodeURIComponent(sessionId)}/datasets/${encodeURIComponent(id)}/import`, {method: "POST"});
          if (!current() || result !== response) return;
          state.files.push(imported.file); state.kinds[imported.file.id] = imported.kind;
          if (imported.kind === "table") tableFileId = imported.file.id;
          else { state.active = imported.file.id; state.record = null; clearResults(); }
          renderFiles();
          if (!tableFileId) await previewActive();
          if (!current()) return;
        } else {
          const attached = await api(`/api/database-query-snapshots/${encodeURIComponent(id)}/chat`, {method: "POST", body: W.stringify({domain_id: domainId})});
          if (!current()) return;
          await openSession(attached.session.id);
          if (state.session?.id !== attached.session.id) return;
          await loadSessions();
          if (state.session?.id !== attached.session.id) return;
          if (attached.kind === "table") tableFileId = attached.file.id;
        }
        close(); go("chat");
        if (tableFileId) document.dispatchEvent(new CustomEvent("graphmine:project-table", {detail: {fileId: tableFileId}}));
        else document.getElementById("question").focus();
        notice("Refined version attached. Earlier inputs and analyses keep their saved snapshots.");
      });
      status.textContent = response.message + (snapshot.temporary ? " Save or use this preview within 24 hours to retain it." : "");
      output.scrollIntoView({block: "start"}); output.focus();
    }
    try {
      const loaded = await api(`/api/database-query-snapshots/${encodeURIComponent(baseId)}/semantic-schema`, {signal: controller.signal});
      if (!current()) return;
      description = loaded;
      drafts = await window.GraphMineQueryDrafts({base: state.base, token: state.token, userId: window.GraphMineAccount?.user?.id, conversationId: sessionId || "new", inputId: "semantic:" + baseId});
      if (!current()) return;
      const s = loaded.schema, caps = loaded.capabilities;
      schemaBox.append(node("p", {class: "semantic-identity"}, `Base version: ${baseId}\nSHA-256: ${loaded.sha256}`), node("p", {}, "All original labels: " + s.labels.join(", ")));
      for (const table of [{table: "Vertex", properties: s.vertex_properties}, ...s.relationships]) {
        const group = node("details"); group.open = true;
        group.append(node("summary", {}, table.table + (table.source_type ? ` · source ${table.source_type}` : "")));
        for (const p of table.properties) group.append(node("p", {}, `${p.name}: ${p.type}${p.source_property !== p.name ? ` · source ${p.source_property}` : ""}`));
        schemaBox.append(group);
      }
      schemaBox.append(node("p", {class: "source-hint"}, s.helpers.join(" · ")), node("p", {class: "source-hint"}, "Nested values are preserved as JSON. JSON path functions are unavailable."));
      model.append(node("option", {value: ""}, "No model steps"));
      for (const m of loaded.models) {
        const option = node("option", {value: m.alias}, `${m.alias} · ${m.model_id}${m.alias === "mock" ? " · simulated" : " · live unavailable"}${m.alias === "mock" && !m.available ? " · access disabled" : ""}`);
        option.disabled = !m.available; model.append(option);
      }
      limit.max = String(caps.max_mock_calls_per_expression);
      policyNote.textContent = `Maximum ${caps.max_mock_calls_per_expression} calls per expression; this is not a total query budget. Timeout: ${caps.timeout_seconds}s. ${caps.mock_queries ? "Mock calls send no provider requests." : "Model steps are unavailable to this account. Plain reads remain available."} Answer reuse, estimates and judgment inspection are unavailable.`;
      const choices = window.GraphMineSemanticTemplates(s).filter(t => t[0] === "plain" || caps.mock_queries);
      templates.append(...choices.map(([id, name]) => node("option", {value: id}, name)));
      function restore(value) {
        editor.value = value?.query || "MATCH (n:Vertex)\nRETURN n"; parameters.value = value?.parameters || "{}";
        projection.value = value?.projection || "elements"; direction.value = value?.inherit_direction === false ? value.direction : "";
        model.value = value?.model || ""; limit.value = String(Math.min(Number(value?.call_limit) || caps.default_call_limit, caps.max_mock_calls_per_expression)); weight.value = value?.weight_property || "";
        weight.disabled = projection.value === "rows"; changed(); queryTools.sync();
      }
      restore(recorded ? {query: recorded.query, parameters: W.stringify(recorded.parameters || {}, true), projection: recorded.projection, weight_property: recorded.weight_property,
        model: recorded.settings?.mock ? "mock" : "", call_limit: recorded.requested_call_limit,
        inherit_direction: recorded.directed == null, direction: recorded.directed ? "directed" : "undirected"} : drafts.get("semantic", baseId));
      insert.onclick = () => { const choice = choices.find(t => t[0] === templates.value); editor.value = choice[2]; model.value = choice[0] === "plain" ? "" : "mock"; projection.value = "elements"; weight.disabled = false; changed(); queryTools.sync(); editor.focus(); };
      discardDraft.onclick = () => { restore(null); drafts.discard("semantic", baseId); draftNote.textContent = "Refinement draft discarded."; };
      setBusy(false); editor.focus();
    } catch (error) { if (current() && error.name !== "AbortError") { description = null; errorState(error); } }
  }
  document.addEventListener("graphmine:refine-snapshot", event => { if (event.detail?.baseId) open(event.detail.baseId, event.detail.recorded); });
  return {open, close};
};
