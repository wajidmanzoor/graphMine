"use strict";
window.GraphMineQueryWorkspace = ({api, node, W, container, editor, parameters, parameterBox, getQuery, onApply, onChange}) => {
  const label = (text, input) => { const el = node("label", {}, text); el.append(input); return el; };
  const button = (id, text) => node("button", {id, type: "button", class: "quiet"}, text);
  const library = node("details", {id: "query-library", class: "query-library"});
  library.append(node("summary", {}, "Saved queries & history"));
  const kind = node("select", {id: "query-library-kind", "aria-label": "Query collection"});
  kind.append(node("option", {value: "saved"}, "Saved queries"), node("option", {value: "history"}, "Recent runs"));
  const choices = node("select", {id: "query-library-choices", "aria-label": "Choose a query"});
  const load = button("load-library-query", "Load into editor"), remove = button("delete-library-query", "Delete query");
  const previous = button("previous-library-page", "Previous"), next = button("next-library-page", "Next"), refresh = button("refresh-query-library", "Refresh");
  const name = node("input", {id: "saved-query-name", type: "text", maxlength: "160", placeholder: "Name this query"});
  const save = button("save-library-query", "Save as new query"), update = button("update-library-query", "Update loaded query");
  const status = node("p", {id: "query-library-status", class: "source-hint", role: "status"});
  const browse = node("div", {class: "query-library-controls"}), manage = node("div", {class: "query-library-controls"});
  browse.append(kind, choices, load, remove, previous, next, refresh);
  manage.append(label("Query name", name), save, update); library.append(browse, manage, status); container.append(library);
  const toolbar = node("div", {class: "query-editor-tools"});
  const format = button("format-cypher", "Format query"), suggest = button("suggest-cypher", "Schema suggestions");
  const toolStatus = node("span", {id: "query-tools-status", class: "source-hint", role: "status"});
  toolbar.append(format, suggest, toolStatus); editor.before(toolbar);
  const suggestionBox = node("div", {class: "query-suggestions", hidden: true});
  const suggestions = node("select", {id: "cypher-suggestions", size: "5", "aria-label": "Query suggestions"});
  const insert = button("insert-cypher-suggestion", "Insert suggestion"), closeSuggestions = button("close-cypher-suggestions", "Close suggestions");
  suggestionBox.append(suggestions, insert, closeSuggestions); toolbar.after(suggestionBox);
  const paramForm = node("div", {id: "query-parameter-form", class: "query-parameter-form"});
  const paramStatus = node("p", {id: "query-parameter-status", class: "source-hint", role: "status"});
  parameters.before(paramForm, paramStatus);
  const errorBox = node("div", {id: "query-inline-error", class: "query-inline-error", role: "alert", hidden: true});
  const errorText = node("p"), goToError = button("goto-query-error", "Go to error");
  errorBox.append(errorText, goToError); editor.after(errorBox);
  editor.setAttribute("aria-describedby", "cypher-hint query-inline-error");
  let context = null, epoch = 0, readGeneration = 0, controller = null, page = 0, hasMore = false, entries = [], loaded = null;
  let pending = false, externalBusy = false, schema = null, schemaPromise = null, parameterTimer = null, suggestionRange = null, selectedSaved = null;
  function lock() {
    const busy = pending || externalBusy || !context;
    library.querySelectorAll("button, select, input").forEach(input => { input.disabled = busy; });
    update.disabled = busy || loaded?.kind !== "saved";
    previous.disabled = busy || page === 0; next.disabled = busy || !hasMore;
    load.disabled = remove.disabled = busy || !choices.value;
    format.disabled = suggest.disabled = externalBusy;
    paramForm.querySelectorAll("input, select").forEach(input => { input.disabled = externalBusy; });
  }
  async function list(reset = false) {
    if (!context || !library.open) return;
    if (reset) page = 0;
    const current = epoch, generation = ++readGeneration;
    status.textContent = "Loading queries…";
    try {
      const params = new URLSearchParams({source_id: context.source, dataset_id: context.dataset, kind: kind.value, offset: String(page * 30), limit: "30"});
      const data = await api(`/api/query-library?${params}`, {signal: controller.signal});
      if (current !== epoch || generation !== readGeneration) return;
      entries = data.items; hasMore = data.has_more;
      if (selectedSaved && !entries.some(entry => entry.id === selectedSaved.id)) entries.unshift(selectedSaved);
      choices.replaceChildren(...entries.map(entry => node("option", {value: entry.id}, `${entry.name}${entry.status ? ` · ${entry.status}` : ""} · ${new Date(entry.updated_at).toLocaleString()}`)));
      if (selectedSaved) choices.value = selectedSaved.id;
      status.textContent = entries.length ? `${page * 30 + 1}–${page * 30 + entries.length}${hasMore ? " · More queries available" : ""}. Loading a query replaces the editor contents.` : kind.value === "saved" ? "No saved queries for this dataset yet." : "No runs for this dataset yet. The most recent 200 runs are retained across your connections.";
      if (selectedSaved) status.textContent = "Saved query selected. Load it into the editor when you’re ready to replace the current draft.";
      lock();
    } catch (error) { if (current === epoch && generation === readGeneration && error.name !== "AbortError") status.textContent = error.message; }
  }
  async function action(fn) {
    if (pending || externalBusy || !context) return;
    const current = epoch; pending = true; lock();
    try { await fn(current); } catch (error) { if (current === epoch && error.name !== "AbortError") status.textContent = error.message; }
    finally { if (current === epoch) { pending = false; lock(); } }
  }
  const currentContext = current => current === epoch && library.isConnected;
  library.ontoggle = () => { if (library.open) list(); };
  kind.onchange = () => { selectedSaved = null; list(true); }; refresh.onclick = () => list(true);
  previous.onclick = () => { selectedSaved = null; page--; list(); }; next.onclick = () => { selectedSaved = null; page++; list(); }; choices.onchange = () => { selectedSaved = null; lock(); };
  load.onclick = () => action(async current => {
    const entry = await api(`/api/query-library/${encodeURIComponent(choices.value)}`, {signal: controller.signal});
    if (!currentContext(current)) return;
    if (entry.source_id && (entry.source_id !== context.source || entry.dataset_id !== context.dataset)) throw new Error("This saved query moved to a different connection or dataset. Reopen it from home.");
    selectedSaved = null; loaded = entry; name.value = entry.name; onApply(entry.query); sync();
    status.textContent = entry.kind === "history"
      ? `Loaded a ${entry.status} run${entry.row_count != null ? ` · ${entry.row_count.toLocaleString()} rows` : ""}${entry.elapsed_ms != null ? ` · ${(entry.elapsed_ms / 1000).toFixed(2)}s` : ""}.${entry.error?.message ? ` Previous error: ${entry.error.message}` : ""} Review the parameters before running it again.`
      : "Query loaded. Review its parameters before running it.";
  });
  const saveQuery = replace => action(async current => {
    if (!name.value.trim()) { name.focus(); throw new Error("Enter a name for the saved query."); }
    const body = {source_id: context.source, name: name.value.trim(), query: getQuery(), ...(replace ? {expected_revision: loaded.revision} : {})};
    const entry = await api(replace ? `/api/query-library/${loaded.id}` : "/api/query-library", {method: replace ? "PUT" : "POST", body: W.stringify(body), signal: controller.signal});
    if (!currentContext(current)) return;
    loaded = entry; kind.value = "saved"; await list(true);
    if (currentContext(current)) { choices.value = entry.id; status.textContent = `Saved “${entry.name}”.`; }
  });
  save.onclick = () => saveQuery(false); update.onclick = () => { if (loaded?.kind === "saved") saveQuery(true); };
  remove.onclick = () => action(async current => {
    const entry = entries.find(e => e.id === choices.value); if (!entry) return;
    await api(`/api/query-library/${entry.id}?revision=${entry.revision}`, {method: "DELETE", signal: controller.signal});
    if (!currentContext(current)) return;
    if (loaded?.id === entry.id) loaded = null;
    if (selectedSaved?.id === entry.id) selectedSaved = null;
    await list(true); if (currentContext(current)) status.textContent = "Query deleted. The current editor contents are still available.";
  });
  function renderParameters(force = false) {
    clearTimeout(parameterTimer);
    if (!force && paramForm.querySelector('[aria-invalid="true"]')) return;
    let values;
    try { values = W.parse(parameters.value || "{}"); if (!values || Array.isArray(values) || typeof values !== "object") throw new Error(); }
    catch { paramStatus.textContent = "Correct the parameter JSON below to use the parameter form."; paramForm.replaceChildren(); return; }
    paramForm.replaceChildren();
    const names = window.GraphMineCypherTools.parameters(editor.value);
    paramStatus.textContent = names.length ? "Set each parameter here, or edit the JSON below. Extra JSON parameters are preserved." : "No parameters found. Use $name in the query to add one.";
    for (const key of names) {
      const type = node("select", {"aria-label": `Type for $${key}`}), input = node("input", {type: "text", "aria-label": `Value for $${key}`, "data-query-parameter": key});
      type.append(...["text", "number", "boolean", "json"].map(t => node("option", {value: t}, t[0].toUpperCase() + t.slice(1))));
      const present = Object.prototype.hasOwnProperty.call(values, key), value = values[key];
      type.value = !present || typeof value === "string" ? "text" : ["number", "bigint"].includes(typeof value) ? "number" : typeof value === "boolean" ? "boolean" : "json";
      input.value = present ? typeof value === "string" ? value : W.stringify(value) : "";
      input.placeholder = present ? "" : "Required parameter";
      const row = node("div", {class: "query-parameter-row"}); row.append(label(`$${key}`, input), type); paramForm.append(row);
      const changed = () => {
        clearTimeout(parameterTimer); clearError();
        try {
          const current = W.parse(parameters.value || "{}");
          let parsed = type.value === "text" ? input.value : W.parse(input.value);
          if (type.value === "number" && !["number", "bigint"].includes(typeof parsed)) throw new Error("Enter a number.");
          if (type.value === "boolean" && typeof parsed !== "boolean") throw new Error("Enter true or false.");
          // Define rather than assign so a parameter named __proto__ stays data.
          Object.defineProperty(current, key, {value: parsed, enumerable: true, configurable: true, writable: true});
          parameters.value = W.stringify(current, true); input.removeAttribute("aria-invalid");
          paramStatus.textContent = "Parameter updated."; onChange();
        } catch (error) { input.setAttribute("aria-invalid", "true"); paramStatus.textContent = `Invalid $${key}: ${error.message}`; }
      };
      input.oninput = type.onchange = changed;
    }
    lock();
  }
  function clearError() { errorBox.hidden = true; editor.removeAttribute("aria-invalid"); parameters.removeAttribute("aria-invalid"); }
  function sync() { clearError(); if (parameterBox.open) renderParameters(true); }
  const edit = event => { clearError(); suggestionBox.hidden = true; suggestionRange = null; clearTimeout(parameterTimer); parameterTimer = setTimeout(() => { if (parameterBox.open) renderParameters(event.target === parameters); }, 250); };
  editor.addEventListener("input", edit); parameters.addEventListener("input", edit);
  parameterBox.addEventListener("toggle", () => { if (parameterBox.open) renderParameters(); });
  format.onclick = () => { editor.value = window.GraphMineCypherTools.format(editor.value); onChange(); sync(); toolStatus.textContent = "Query formatted. Strings and comments are preserved."; };
  async function getSchema() {
    if (schema) return schema;
    if (!context) return {entities: [], relationships: []};
    if (!schemaPromise) {
      const current = epoch;
      schemaPromise = api(`/api/database-sources/${encodeURIComponent(context.source)}/graph-builder?dataset_id=${encodeURIComponent(context.dataset)}`, {signal: controller.signal}).then(data => {
        if (current === epoch) schema = data; return data;
      }).finally(() => { if (current === epoch) schemaPromise = null; });
    }
    return schemaPromise;
  }
  suggest.onclick = async () => {
    const current = epoch, cursor = editor.selectionStart;
    const prefix = editor.value.slice(0, cursor).match(/[A-Za-z_][A-Za-z0-9_]*$/)?.[0] || "";
    let start = cursor - prefix.length, end = editor.selectionEnd;
    if (editor.value[start - 1] === "`") start--;
    if (editor.value[end] === "`") end++;
    const before = editor.value[start - 1], query = editor.value;
    let data = {entities: [], relationships: []};
    try { data = await getSchema(); } catch (error) { if (current !== epoch || error.name === "AbortError") return; toolStatus.textContent = "Schema is unavailable. Showing query keywords and parameters."; }
    if (current !== epoch || editor.value !== query) return;
    const identifier = text => "`" + text.replaceAll("`", "``") + "`";
    let items = [];
    if (before === "$") items = window.GraphMineCypherTools.parameters(editor.value).map(name => [name, /^[A-Za-z_]\w*$/.test(name) ? name : identifier(name)]);
    else if (before === ".") items = [...data.entities, ...data.relationships].flatMap(e => e.properties).map(p => [p.name, identifier(p.name)]);
    else if (before === ":") items = [...data.entities, ...data.relationships].map(e => [e.label, identifier(e.label)]);
    else items = ["MATCH", "OPTIONAL MATCH", "WHERE", "WITH", "RETURN", "ORDER BY", "LIMIT", "UNWIND", "DISTINCT"].map(word => [word, word]);
    const unique = new Map(items.filter(([label]) => label.toLowerCase().startsWith(prefix.toLowerCase())).map(([label, text]) => [label, text]));
    suggestions.replaceChildren(...[...unique].map(([label, value]) => node("option", {value}, label)));
    suggestionRange = {start, end}; suggestionBox.hidden = unique.size === 0;
    toolStatus.textContent = unique.size ? `${unique.size} suggestions. Choose one and press Enter.` : "No matching suggestions.";
    if (unique.size) { suggestions.selectedIndex = 0; suggestions.focus(); }
  };
  insert.onclick = () => {
    if (!suggestionRange || suggestions.selectedIndex < 0) return;
    editor.setRangeText(suggestions.value, suggestionRange.start, suggestionRange.end, "end");
    suggestionBox.hidden = true; editor.focus(); onChange(); sync();
  };
  closeSuggestions.onclick = () => { suggestionBox.hidden = true; editor.focus(); };
  suggestions.onkeydown = event => { if (event.key === "Enter") { event.preventDefault(); insert.click(); } if (event.key === "Escape") { event.preventDefault(); closeSuggestions.click(); } };
  editor.addEventListener("keydown", event => { if (event.ctrlKey && event.code === "Space") { event.preventDefault(); suggest.click(); } });
  return {
    setContext(source, dataset, ready) {
      epoch++; readGeneration++; controller?.abort(); controller = new AbortController();
      context = ready && source && dataset ? {source, dataset} : null;
      page = 0; hasMore = false; entries = []; loaded = null; pending = false; schema = schemaPromise = selectedSaved = null;
      name.value = ""; choices.replaceChildren(); suggestionBox.hidden = true; clearError(); sync(); lock();
      status.textContent = context ? "Open to browse this dataset's saved queries and recent runs." : "Choose a ready dataset to save or load queries.";
      if (library.open) list();
    },
    showSaved(entry) {
      if (!context || entry.source_id !== context.source || entry.dataset_id !== context.dataset) return;
      selectedSaved = entry; kind.value = "saved"; library.open = true; void list(true);
    },
    setBusy(value) { externalBusy = value; lock(); },
    setVisible(value) { toolbar.hidden = !value; if (!value) { suggestionBox.hidden = true; clearError(); } },
    sync,
    validate() { if (paramForm.querySelector('[aria-invalid="true"]')) throw new Error("Correct the invalid parameter value before saving or running the query."); },
    completed() { if (kind.value === "history") list(true); },
    error(error) {
      if (!["cypher_syntax", "cypher_parameters", "cypher_read_only"].includes(error.code)) return;
      errorBox.hidden = false; errorText.textContent = error.message;
      (error.code === "cypher_parameters" ? parameters : editor).setAttribute("aria-invalid", "true");
      const position = error.details;
      goToError.hidden = !Number.isInteger(position?.offset);
      goToError.onclick = () => {
        // Neo4j offsets count Unicode code points; textarea selection uses UTF-16.
        const offset = [...editor.value].slice(0, Math.max(0, position.offset)).join("").length;
        editor.focus(); editor.setSelectionRange(offset, Math.min(editor.value.length, offset + 1));
      };
      if (error.code === "cypher_parameters") { parameterBox.open = true; renderParameters(); }
    },
    destroy() { epoch++; controller?.abort(); clearTimeout(parameterTimer); library.remove(); toolbar.remove(); suggestionBox.remove(); errorBox.remove(); paramForm.remove(); paramStatus.remove(); },
  };
};
