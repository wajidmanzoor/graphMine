/* Dataset controls are independent of the conversation and graph renderer. */
"use strict";
window.GraphMineLibrary = ({state, api, W, node, notice, runAction, ensureSession, renderFiles, previewActive, questionSelection}) => {
  const $ = id => document.getElementById(id);
  const dialog = node("dialog", {id: "dataset-dialog", class: "wide-dialog", "aria-label": "Dataset library"});
  const heading = node("h2", {}, "Dataset library"), close = node("button", {type: "button", class: "quiet"}, "Close");
  close.onclick = () => dialog.close();
  const header = node("div", {class: "section-heading"}); header.append(heading, close);
  const search = node("input", {type: "search", placeholder: "Search saved datasets", "aria-label": "Search saved datasets"});
  const list = node("div", {id: "dataset-list", class: "saved-list"});
  const form = node("form", {id: "dataset-form", hidden: true});
  const name = node("input", {id: "dataset-name", required: "", maxlength: "160"});
  const label = node("label", {}, "Dataset name"); label.append(name);
  const versions = node("select", {id: "dataset-version"});
  const versionLabel = node("label", {}, "Save as"); versionLabel.append(versions);
  const save = node("button", {type: "submit", class: "primary"}, "Save snapshot");
  const detail = node("p", {id: "dataset-source", class: "muted"});
  form.append(label, versionLabel, detail, save);
  dialog.append(header, node("p", {class: "muted"}, "Saved versions remain available across your conversations. Importing a version makes an independent copy and records where it came from."), form, search, list);
  document.body.append(dialog);
  let datasets = [], source = null, sessionId = null;
  async function refresh() { datasets = await api("/api/datasets"); render(); }
  function render() {
    list.replaceChildren();
    for (const item of datasets.filter(d => `${d.name} ${d.kind}`.toLowerCase().includes(search.value.toLowerCase()))) {
      const row = node("article", {class: "dataset-row"});
      row.append(node("h3", {}, `${item.name} · version ${item.version}`), node("p", {class: "muted"}, `${item.kind.replaceAll("_", " ")} · ${item.size_bytes.toLocaleString()} bytes · ${item.source_complete ? "Complete source" : "Source result is incomplete"}`));
      const provenance = node("details"), pre = node("pre", {}, W.stringify({sha256: item.sha256, source: item.source}, true));
      provenance.append(node("summary", {}, "Source and provenance"), pre); row.append(provenance);
      const use = node("button", {type: "button", class: "secondary", "data-import-dataset": item.id}, "Use in this conversation");
      use.onclick = () => runAction(async () => {
        if (state.session?.id !== sessionId) throw new Error("The conversation changed. Reopen the dataset library.");
        const result = await api(`/api/sessions/${sessionId}/datasets/${item.id}/import`, {method: "POST"});
        if (state.session?.id !== sessionId) return;
        state.files.push(result.file); state.kinds[result.file.id] = result.kind; state.active = result.file.id;
        renderFiles(); await previewActive(); dialog.close(); notice(`Using ${item.name}, version ${item.version}.`);
      });
      const remove = node("button", {type: "button", class: "quiet danger", "data-delete-dataset": item.id}, "Delete version");
      remove.onclick = () => { if (confirm(`Delete ${item.name}, version ${item.version}? Copies already imported into conversations remain available.`)) runAction(async () => { await api(`/api/datasets/${item.id}`, {method: "DELETE"}); await refresh(); }); };
      row.append(use, remove); list.append(row);
    }
    if (!list.children.length) list.append(node("p", {class: "muted"}, "No saved datasets match. Save an uploaded input or a graph from your results to begin."));
  }
  async function open(selectedSource, defaultName = "") {
    await ensureSession(); sessionId = state.session.id; source = selectedSource;
    await refresh(); form.hidden = !source; name.value = defaultName;
    versions.replaceChildren(node("option", {value: ""}, "New dataset"));
    const seen = new Set();
    for (const item of datasets) if (item.kind === (source?.kind || "graph") && !seen.has(item.dataset_id)) {
      seen.add(item.dataset_id); versions.append(node("option", {value: item.dataset_id}, `New version of ${item.name}`));
    }
    detail.textContent = source?.workflow_id ? "The full saved graph or selected group's connections will be copied, including results beyond the preview limit. Source completeness is retained." : "This saves the full canonical input with its source and content hash.";
    dialog.showModal(); if (source) name.focus();
  }
  search.oninput = render;
  form.onsubmit = event => { event.preventDefault(); runAction(async () => {
    if (!source || state.session?.id !== sessionId) throw new Error("Reopen the dataset library for the current conversation.");
    await api("/api/datasets", {method: "POST", body: W.stringify({...source, name: name.value, ...(versions.value ? {dataset_id: versions.value} : {})})});
    source = null; form.hidden = true; await refresh(); notice("Dataset version saved. It is ready to reuse in any of your conversations.");
  }); };
  $("open-datasets").onclick = () => runAction(() => open(null));
  $("save-dataset-input").onclick = () => runAction(async () => {
    const file = state.files.find(f => f.id === state.active);
    if (!file) throw new Error("Choose an input to save first.");
    await open({file_id: file.id, kind: state.kinds[file.id] || "graph"}, file.original_name.replace(/\.[^.]+$/, ""));
  });
  const saveResult = node("button", {id: "save-dataset-result", type: "button", class: "secondary"}, "Save graph for reuse");
  $("result-actions").append(saveResult);
  saveResult.onclick = () => runAction(async () => {
    if (!state.record || !state.port) throw new Error("Open a saved graph result or select a group first.");
    const selection = questionSelection();
    if (state.port.type !== "graph" && !selection) throw new Error("Choose a graph output or select a group in the graph view first.");
    await open({workflow_id: state.record.id, expected_revision: state.record.revision, step: $("result-step").value, port: $("result-port").value, ...(selection ? {group_index: selection.index} : {})}, selection?.label || "Analysis graph");
  });
};
