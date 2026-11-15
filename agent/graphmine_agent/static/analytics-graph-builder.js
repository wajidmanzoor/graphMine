/* Schema-guided query generation never executes or replaces the editor on its own. */
"use strict";
window.GraphMineGraphBuilder = ({api, node, container, onApply}) => {
  const panel = node("details", {id: "graph-builder", class: "graph-builder"});
  panel.append(node("summary", {}, "Build a graph with guided choices"));
  const status = node("p", {id: "graph-builder-status", role: "status", class: "source-hint"});
  const form = node("div", {hidden: true}), fields = node("div", {class: "builder-fields"});
  const select = id => node("select", id ? {id} : {});
  const label = (text, input) => { const el = node("label", {}, text); el.append(input); return el; };
  const button = (text, id) => node("button", {type: "button", class: "secondary", ...(id ? {id} : {})}, text);
  const entity = select("builder-entity"), relation = select("builder-relationship"), target = select("builder-target");
  const match = select("builder-match-direction"), direction = select("builder-analysis-direction"), weight = select("builder-weight");
  for (const [value, text] of [["outgoing", "Outgoing relationships"], ["incoming", "Incoming relationships"], ["either", "Either direction"]]) match.append(node("option", {value}, text));
  direction.append(node("option", {value: "directed"}, "Keep original direction"), node("option", {value: "undirected"}, "Treat as undirected"));
  const limit = node("input", {id: "builder-limit", type: "number", min: "1", step: "1", value: "1000"});
  fields.append(label("Starting entity", entity), label("Relationship", relation), label("Matching direction", match), label("Other entity", target), label("Analysis direction", direction), label("Edge weight", weight), label("Maximum rows", limit));
  const filterBox = node("div", {class: "builder-filters"}), addFilter = button("Add filter", "builder-add-filter");
  const generate = button("Generate Cypher", "builder-generate"), apply = button("Use generated query", "builder-apply");
  const generated = node("section", {class: "builder-generated", hidden: true});
  const code = node("pre", {id: "builder-cypher"}), params = node("pre", {id: "builder-parameters"});
  const description = node("p", {class: "source-hint"});
  generated.append(description, code, node("p", {class: "source-hint"}, "Parameters"), params, apply);
  const controls = node("div", {class: "source-preview-actions"}); controls.append(addFilter, generate);
  form.append(fields, filterBox, controls, generated); panel.append(status, form); container.append(panel);
  let context = null, schema = null, loading = false, busy = false, generation = 0, compiled = null, controller = null;
  let filters = [];
  const selected = () => ({source: schema?.entities.find(e => e.id === entity.value), relationship: schema?.relationships.find(r => r.id === relation.value), target: schema?.entities.find(e => e.id === target.value)});
  const stale = () => { generation++; compiled = null; generated.hidden = true; };
  function filterProperties(filter) {
    const previous = filter.property.value;
    filter.property.replaceChildren(...(selected()[filter.scope.value]?.properties || []).map(p => node("option", {value: p.name}, p.name + (p.type ? ` (${p.type})` : ""))));
    if ([...filter.property.options].some(p => p.value === previous)) filter.property.value = previous;
  }
  function refreshFields() {
    const chosen = selected().relationship;
    target.disabled = match.disabled = weight.disabled = !chosen;
    const previous = weight.value;
    weight.replaceChildren(node("option", {value: ""}, "Use stored weights"), ...(chosen?.properties || []).map(p => node("option", {value: p.name}, p.name)));
    if ([...weight.options].some(p => p.value === previous)) weight.value = previous;
    filters.forEach(filterProperties);
  }
  function endpoints() {
    const chosen = selected().relationship;
    if (chosen?.source_entity && chosen?.target_entity) {
      entity.value = match.value === "incoming" ? chosen.target_entity : chosen.source_entity;
      target.value = match.value === "incoming" ? chosen.source_entity : chosen.target_entity;
    }
    refreshFields(); stale();
  }
  function lock(value) {
    busy = value;
    form.querySelectorAll("input, select, button").forEach(input => { input.disabled = value; });
    if (!value) {
      refreshFields(); addFilter.disabled = filters.length >= 20;
      filters.forEach(f => { f.type.disabled = f.value.disabled = ["is_null", "not_null"].includes(f.operator.value); });
    }
  }
  async function load() {
    if (!context || !panel.open || schema || loading) return;
    loading = true; controller?.abort(); controller = new AbortController();
    const current = ++generation;
    status.textContent = "Loading graph choices…";
    try {
      const result = await api(`/api/database-sources/${encodeURIComponent(context.source)}/graph-builder?dataset_id=${encodeURIComponent(context.dataset)}`, {signal: controller.signal});
      if (current !== generation || !panel.isConnected) return;
      schema = result;
      entity.replaceChildren(...schema.entities.map(e => node("option", {value: e.id}, e.label)));
      target.replaceChildren(...schema.entities.map(e => node("option", {value: e.id}, e.label)));
      relation.replaceChildren(node("option", {value: ""}, "Nodes only"), ...schema.relationships.map(r => node("option", {value: r.id}, r.label)));
      limit.max = String(schema.max_rows); limit.value = String(Math.min(1000, schema.max_rows));
      status.textContent = result.message || "Choose graph elements and filters. Review the generated query before using it.";
      form.hidden = !schema.entities.length; refreshFields();
    } catch (error) { if (current === generation && error.name !== "AbortError") status.textContent = error.message + " Close and reopen the builder to retry."; }
    finally { if (current === generation) loading = false; }
  }
  panel.ontoggle = load;
  relation.onchange = match.onchange = endpoints;
  entity.onchange = target.onchange = () => { refreshFields(); stale(); };
  direction.onchange = weight.onchange = limit.oninput = stale;
  addFilter.onclick = () => {
    if (busy || filters.length >= 20) return;
    const row = node("fieldset", {class: "builder-filter"}), scope = select(), property = select(), operator = select(), type = select();
    const value = node("input", {type: "text", maxlength: "8000"}), remove = button("Remove filter");
    scope.append(...[["source", "Starting node"], ["relationship", "Relationship"], ["target", "Other node"]].map(([value, text]) => node("option", {value}, text)));
    for (const [value, text] of [["eq", "equals"], ["ne", "does not equal"], ["gt", "greater than"], ["gte", "at least"], ["lt", "less than"], ["lte", "at most"], ["contains", "contains text"], ["starts_with", "starts with"], ["is_null", "is missing"], ["not_null", "is present"]]) operator.append(node("option", {value}, text));
    type.append(...["Text", "Number", "Boolean"].map(t => node("option", {value: t.toLowerCase()}, t)));
    row.append(node("legend", {}, "All filters must match"), label("Graph element", scope), label("Property", property), label("Condition", operator), label("Value type", type), label("Value", value), remove);
    const filter = {row, scope, property, operator, type, value}; filters.push(filter); filterBox.append(row); filterProperties(filter);
    scope.onchange = () => { filterProperties(filter); stale(); };
    operator.onchange = () => { type.disabled = value.disabled = ["is_null", "not_null"].includes(operator.value); stale(); };
    property.onchange = type.onchange = value.oninput = stale;
    remove.onclick = () => { filters = filters.filter(f => f !== filter); row.remove(); addFilter.disabled = false; stale(); addFilter.focus(); };
    stale(); addFilter.disabled = filters.length >= 20; scope.focus();
  };
  generate.onclick = async () => {
    if (busy || !schema || !context) return;
    const current = ++generation; compiled = null; generated.hidden = true;
    try {
      if (!limit.reportValidity()) return;
      const conditions = filters.map(f => {
        if (!f.property.value) throw new Error("Choose an available property for every filter.");
        let value = f.value.value;
        if (!["is_null", "not_null"].includes(f.operator.value)) {
          if (f.type.value === "number") {
            if (!value.trim() || !Number.isFinite(Number(value)) || /^[-+]?\d+$/.test(value) && !Number.isSafeInteger(Number(value))) throw new Error("Enter a finite number within the browser's exact integer range.");
            value = Number(value);
          } else if (f.type.value === "boolean") {
            if (!["true", "false"].includes(value.toLowerCase())) throw new Error("Boolean values must be true or false.");
            value = value.toLowerCase() === "true";
          }
        } else value = null;
        return {scope: f.scope.value, property: f.property.value, operator: f.operator.value, value};
      });
      const body = {dataset_id: context.dataset, source_entity: entity.value, relationship: relation.value || null, target_entity: relation.value ? target.value : null, match_direction: match.value, directed: direction.value === "directed", weight_property: relation.value ? weight.value || null : null, limit: Number(limit.value), filters: conditions};
      lock(true); status.textContent = "Generating query…";
      const result = await api(`/api/database-sources/${encodeURIComponent(context.source)}/graph-builder`, {method: "POST", body: JSON.stringify(body), signal: controller?.signal});
      if (current !== generation || !panel.isConnected) return;
      compiled = result; code.textContent = result.statement; params.textContent = JSON.stringify(result.parameters, null, 2);
      description.textContent = result.description; generated.hidden = false;
      status.textContent = "Review the query below. Using it replaces the current editor contents.";
    } catch (error) { if (current === generation && error.name !== "AbortError") status.textContent = error.message; }
    finally { if (current === generation) lock(false); }
  };
  apply.onclick = () => { if (compiled) { onApply(compiled); status.textContent = "Query copied to the editor. Preview it when you are ready."; } };
  return {
    setContext(source, dataset, ready) {
      controller?.abort(); stale(); loading = busy = false; schema = null;
      filters = []; filterBox.replaceChildren(); form.hidden = true;
      context = source && dataset && ready ? {source, dataset} : null;
      status.textContent = context ? "Open the builder to load graph choices." : "Choose a ready dataset to build a graph.";
      load();
    },
    destroy() { controller?.abort(); stale(); panel.remove(); },
    setBusy(value) { lock(value); },
  };
};
