"use strict";
window.GraphMineWorkspaceTools = ({api, W, node, host, context, onChange}) => {
  let active = null, epoch = 0, controller = null, preview = null, settings = {};
  const schema = node("button", {type: "button", id: "open-dataset-schema", class: "secondary"}, "Schema");
  const model = node("button", {type: "button", id: "open-query-models", class: "secondary"}, "Model configuration");
  host.append(schema, model);
  function close() { epoch++; controller?.abort(); preview?.destroy(); preview = null; active?.close(); active?.remove(); active = null; }
  function dialog(title) {
    close(); controller = new AbortController();
    active = node("dialog", {class: "workspace-tool-dialog", "aria-label": title});
    const header = node("header"), done = node("button", {type: "button", class: "quiet", "aria-label": "Close " + title}, "Close");
    header.append(node("h2", {}, title), done); active.append(header);
    done.onclick = close; active.oncancel = event => { event.preventDefault(); close(); };
    document.body.append(active); active.showModal(); return active;
  }
  schema.onclick = async () => {
    const selected = context(), box = dialog("Dataset schema"), current = epoch;
    const status = node("p", {class: "source-hint", role: "status"}, "Reading the selected dataset schema…"); box.append(status);
    if (!selected.source || !selected.dataset) { status.textContent = "Select a ready dataset first."; return; }
    try {
      const data = await api(`/api/database-sources/${encodeURIComponent(selected.source)}/schema?dataset_id=${encodeURIComponent(selected.dataset)}&diagram=true`, {signal: controller.signal});
      if (current !== epoch) return;
      const controls = node("div", {class: "workspace-graph-controls"}), canvas = node("div", {class: "workspace-schema-canvas", role: "img", "aria-label": "Selected dataset schema diagram"}), details = node("div", {class: "workspace-element-details"});
      box.append(controls, canvas, details);
      const vertices = data.entities.map(v => ({id: v.id, label: v.label, type: v.label, attributes: {properties: v.properties}}));
      const known = new Set(vertices.map(v => v.id));
      const edges = data.relationships.filter(e => known.has(e.source_entity) && known.has(e.target_entity)).map(e => ({id: e.id, source: e.source_entity, target: e.target_entity, type: e.label, attributes: {properties: e.properties}}));
      status.textContent = `${data.entities.length} labels · ${data.relationships.length} relationship patterns. ${data.message || ""}`;
      preview = window.GraphMineWorkspaceGraph({node, W, canvas, controls, details, schema: true});
      await preview.draw({graph: {directed: true}, vertices, edges});
    } catch (error) { if (current === epoch) status.textContent = error.message; }
  };
  model.onclick = async () => {
    const box = dialog("Model configuration"), current = epoch;
    const status = node("p", {class: "source-hint", role: "status"}, "Loading model settings…"); box.append(status);
    try {
      const data = await api("/api/query-models", {signal: controller.signal});
      if (current !== epoch) return;
      status.textContent = data.available ? "The alias in each llm() call selects its model. Every run uses fresh model calls." : "Model execution is unavailable for this account. An administrator can enable live model access.";
      const aliases = node("dl", {class: "workspace-model-aliases"});
      for (const value of data.models) aliases.append(node("dt", {}, value.alias), node("dd", {}, value.model_id));
      box.append(aliases);
      const fields = new Map(), form = node("div", {class: "workspace-model-fields"});
      for (const [name, title, min] of [["call_limit", "Maximum HTTP requests per query", 1], ["batch_size", "Inputs per model batch", 1], ["model_timeout_seconds", "Model timeout (seconds)", 5]]) {
        const input = node("input", {type: "number", min, max: data.limits[name], step: "1", required: true, value: settings[name] ?? data.defaults[name], "aria-label": title});
        const label = node("label", {}, title); label.append(input); form.append(label); fields.set(name, input);
      }
      const apply = node("button", {type: "button", class: "primary"}, "Apply query settings");
      apply.onclick = () => { if ([...fields.values()].every(input => input.reportValidity())) { settings = Object.fromEntries([...fields].map(([name, input]) => [name, Number(input.value)])); onChange(); close(); } };
      box.append(form, node("p", {class: "source-hint"}, "Structured output · temperature 0 · thinking off. Query limits stay within the server limits."), apply);
      if (data.can_administer) box.append(node("a", {href: "/admin#semantic", target: "_blank", rel: "noopener", class: "workspace-model-manage"}, "Manage model aliases and providers"));
    } catch (error) { if (current === epoch) status.textContent = error.message; }
  };
  return {settings: () => ({...settings}), contextChanged: close, destroy: close};
};
