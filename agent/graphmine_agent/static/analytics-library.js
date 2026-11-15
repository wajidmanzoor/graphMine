/* Dataset controls are independent of the conversation and graph renderer. */
"use strict";
// Bounded collection picker shared by snapshot and connector forms.
window.GraphMineDatasetPicker = ({api, node, select}) => {
  const box = node("div", {class: "dataset-picker"});
  const search = node("input", {type: "search", maxlength: "200", placeholder: "Find an existing dataset", "aria-label": "Find an existing dataset"});
  const selection = node("p", {class: "source-hint dataset-choice", role: "status", hidden: true});
  const pages = node("div", {class: "query-table-pages"}), status = node("span", {role: "status"});
  const previous = node("button", {type: "button", class: "quiet"}, "Previous datasets"), next = node("button", {type: "button", class: "quiet"}, "More datasets"), retry = node("button", {type: "button", class: "quiet", hidden: true}, "Retry datasets");
  pages.append(previous, status, next, retry); box.append(selection, search, pages);
  let controller, epoch = 0, timer, offset = 0, kind = "graph";
  const selected = () => { selection.hidden = !select.value; selection.textContent = select.value ? select.selectedOptions[0]?.textContent || "" : ""; };
  select.addEventListener("change", selected);
  const stop = () => { epoch++; clearTimeout(timer); controller?.abort(); };
  async function load() {
    controller?.abort(); controller = new AbortController(); const current = ++epoch;
    previous.disabled = next.disabled = select.disabled = true; retry.hidden = true; status.textContent = "Loading datasets…";
    try {
      const page = await api(`/api/datasets/page?${new URLSearchParams({offset, limit: 20, kind, latest: true, q: search.value})}`, {signal: controller.signal});
      if (current !== epoch) return;
      const chosen = select.value, option = select.selectedOptions[0]?.cloneNode(true);
      select.replaceChildren(node("option", {value: ""}, "New dataset"));
      for (const item of page.items) select.append(node("option", {value: item.dataset_id}, `New version of ${item.name}`));
      if (chosen && !page.items.some(item => item.dataset_id === chosen) && option) select.append(option);
      select.value = chosen;
      selected();
      previous.disabled = offset === 0; next.disabled = !page.has_more;
      status.textContent = page.items.length ? `Datasets ${offset + 1}–${offset + page.items.length}` : "No matching datasets";
    } catch (error) {
      if (current !== epoch || error.name === "AbortError") return;
      status.textContent = error.message; retry.hidden = false;
    } finally { if (current === epoch) select.disabled = false; }
  }
  search.oninput = () => { stop(); offset = 0; previous.disabled = next.disabled = true; timer = setTimeout(load, 200); };
  previous.onclick = () => { offset = Math.max(0, offset - 20); load(); };
  next.onclick = () => { offset += 20; load(); }; retry.onclick = load;
  return {element: box, stop, reset: value => { stop(); kind = value; offset = 0; search.value = ""; select.replaceChildren(node("option", {value: ""}, "New dataset")); selected(); return load(); }};
};
window.GraphMineLibrary = ({state, api, W, node, notice, runAction, ensureSession, renderFiles, previewActive, questionSelection}) => {
  const $ = id => document.getElementById(id);
  const dialog = node("dialog", {id: "dataset-dialog", class: "wide-dialog", "aria-label": "Dataset library"});
  const heading = node("h2", {}, "Dataset library"), close = node("button", {type: "button", class: "quiet"}, "Close");
  close.onclick = () => dialog.close();
  const header = node("div", {class: "section-heading"}); header.append(heading, close);
  const search = node("input", {type: "search", placeholder: "Search saved datasets", "aria-label": "Search saved datasets", maxlength: "200"});
  const list = node("div", {id: "dataset-list", class: "saved-list"});
  const form = node("form", {id: "dataset-form", hidden: true});
  const name = node("input", {id: "dataset-name", required: "", maxlength: "160"});
  const label = node("label", {}, "Dataset name"); label.append(name);
  const versions = node("select", {id: "dataset-version"});
  const versionLabel = node("label", {}, "Save as"); versionLabel.append(versions);
  const save = node("button", {type: "submit", class: "primary"}, "Save snapshot");
  const detail = node("p", {id: "dataset-source", class: "muted"});
  const picker = window.GraphMineDatasetPicker({api, node, select: versions});
  form.append(label, versionLabel, picker.element, detail, save);
  const pages = node("div", {class: "query-table-pages"}), range = node("span", {role: "status"});
  const previous = node("button", {type: "button", class: "quiet", id: "datasets-previous"}, "Previous versions"), next = node("button", {type: "button", class: "quiet", id: "datasets-next"}, "Next versions"), retry = node("button", {type: "button", class: "quiet", id: "datasets-retry", hidden: true}, "Retry datasets");
  pages.append(previous, range, next, retry);
  dialog.append(header, node("p", {class: "muted"}, "Saved versions remain available across your conversations. Importing a version makes an independent copy and records where it came from."), form, search, list, pages);
  document.body.append(dialog);
  let datasets = [], source = null, sessionId = null, offset = 0, epoch = 0, controller, timer, openedRoute = "";
  const provenanceReads = new Set();
  function stop() { epoch++; clearTimeout(timer); controller?.abort(); picker.stop(); for (const read of provenanceReads) read.abort(); provenanceReads.clear(); }
  dialog.addEventListener("close", stop);
  window.addEventListener("hashchange", () => { if (dialog.open && location.hash !== openedRoute) dialog.close(); });
  async function refresh() {
    controller?.abort(); controller = new AbortController(); const current = ++epoch;
    for (const read of provenanceReads) read.abort(); provenanceReads.clear();
    list.replaceChildren(); list.setAttribute("aria-busy", "true");
    previous.disabled = next.disabled = true; retry.hidden = true; range.textContent = "Loading dataset versions…";
    try {
      const page = await api(`/api/datasets/page?${new URLSearchParams({offset, limit: 20, q: search.value})}`, {signal: controller.signal});
      if (current !== epoch || !dialog.open || state.session?.id !== sessionId) return;
      if (!page.items.length && offset) { offset = Math.max(0, offset - 20); return refresh(); }
      datasets = page.items; render(); previous.disabled = offset === 0; next.disabled = !page.has_more;
      range.textContent = datasets.length ? `Versions ${offset + 1}–${offset + datasets.length}` : "0 versions";
    } catch (error) {
      if (current !== epoch || error.name === "AbortError") return;
      range.textContent = error.message; retry.hidden = false;
    } finally { if (current === epoch) list.setAttribute("aria-busy", "false"); }
  }
  function render() {
    list.replaceChildren();
    for (const item of datasets) {
      const row = node("article", {class: "dataset-row"});
      row.append(node("h3", {}, `${item.name} · version ${item.version}`), node("p", {class: "muted"}, `${item.kind.replaceAll("_", " ")} · ${item.size_bytes.toLocaleString()} bytes · ${item.source_complete ? "Complete source" : "Source result is incomplete"}`));
      const provenance = node("details"), content = node("div");
      provenance.append(node("summary", {}, "Source and provenance"), content); row.append(provenance);
      let loaded = false, pending = false;
      async function readProvenance() {
        if (loaded || pending || !provenance.open) return;
        const current = epoch, read = new AbortController(); provenanceReads.add(read); pending = true;
        content.replaceChildren(node("p", {role: "status"}, "Loading provenance…"));
        try {
          const value = await api(`/api/datasets/${encodeURIComponent(item.id)}/provenance`, {signal: read.signal});
          if (current !== epoch || !row.isConnected || !dialog.open) return;
          loaded = true; content.replaceChildren(node("pre", {}, W.stringify({sha256: value.sha256, source: value.source}, true)));
        } catch (error) {
          if (current !== epoch || error.name === "AbortError") return;
          const retry = node("button", {type: "button", class: "quiet"}, "Retry provenance"); retry.onclick = readProvenance;
          content.replaceChildren(node("p", {role: "status"}, error.message), retry);
        } finally { pending = false; provenanceReads.delete(read); }
      }
      provenance.ontoggle = readProvenance;
      const use = node("button", {type: "button", class: "secondary", "data-import-dataset": item.id}, "Use in this conversation");
      use.onclick = async () => {
        let tableFileId = null;
        const current = epoch, sid = sessionId;
        await runAction(async () => {
        if (state.session?.id !== sessionId) throw new Error("The conversation changed. Reopen the dataset library.");
        const result = await api(`/api/sessions/${sessionId}/datasets/${item.id}/import`, {method: "POST"});
        if (state.session?.id !== sid || current !== epoch) return;
          state.files.push(result.file); state.kinds[result.file.id] = result.kind;
          if (result.kind === "table") { tableFileId = result.file.id; renderFiles(); }
          else { state.active = result.file.id; renderFiles(); await previewActive(); }
          dialog.close(); notice(`Using ${item.name}, version ${item.version}.`);
        });
        if (tableFileId && state.session?.id === sid) document.dispatchEvent(new CustomEvent("graphmine:project-table", {detail: {fileId: tableFileId}}));
      };
      if (item.kind === "table") {
        const view = node("button", {type: "button", class: "quiet", "data-view-table": item.id}, "View complete table");
        view.onclick = () => {
          const viewer = node("dialog", {class: "wide-dialog", "aria-label": "Saved query table"}), dismiss = node("button", {type: "button", class: "quiet"}, "Close table");
          viewer.append(node("h2", {}, item.name), dismiss); document.body.append(viewer);
          const table = window.GraphMineQueryTable({api, W, node, container: viewer});
          const finish = () => { dialog.removeEventListener("close", finish); table.destroy(); viewer.close(); viewer.remove(); if (dialog.open) view.focus(); };
          dialog.addEventListener("close", finish, {once: true});
          dismiss.onclick = finish; viewer.oncancel = event => { event.preventDefault(); finish(); };
          viewer.showModal(); table.setSnapshot(item);
        };
        row.append(view);
      }
      const remove = node("button", {type: "button", class: "quiet danger", "data-delete-dataset": item.id}, "Delete version");
      remove.onclick = () => { if (confirm(`Delete ${item.name}, version ${item.version}? Copies already imported into conversations remain available.`)) runAction(async () => { const current = epoch; await api(`/api/datasets/${item.id}`, {method: "DELETE"}); if (current === epoch && dialog.open) await refresh(); }); };
      row.append(use, remove); list.append(row);
    }
    if (!list.children.length) list.append(node("p", {class: "muted"}, "No saved datasets match. Save an uploaded input or a graph from your results to begin."));
  }
  async function open(selectedSource, defaultName = "") {
    stop(); const current = epoch;
    await ensureSession(); if (current !== epoch) return;
    sessionId = state.session.id; source = selectedSource; offset = 0; search.value = "";
    form.hidden = !source; name.value = defaultName;
    detail.textContent = source?.workflow_id ? "The full saved graph or selected group's connections will be copied, including results beyond the preview limit. Source completeness is retained." : "This saves the full canonical input with its source and content hash.";
    openedRoute = location.hash; dialog.showModal(); if (source) name.focus();
    await Promise.all([refresh(), source ? picker.reset(source.kind || "graph") : Promise.resolve()]);
  }
  search.oninput = () => { epoch++; controller?.abort(); clearTimeout(timer); offset = 0; list.replaceChildren(); previous.disabled = next.disabled = true; range.textContent = "Searching…"; timer = setTimeout(refresh, 200); };
  previous.onclick = () => { offset = Math.max(0, offset - 20); refresh(); };
  next.onclick = () => { offset += 20; refresh(); }; retry.onclick = refresh;
  form.onsubmit = event => { event.preventDefault(); runAction(async () => {
    if (!source || state.session?.id !== sessionId) throw new Error("Reopen the dataset library for the current conversation.");
    const current = epoch;
    await api("/api/datasets", {method: "POST", body: W.stringify({...source, name: name.value, ...(versions.value ? {dataset_id: versions.value} : {})})});
    if (current !== epoch || !dialog.open) return;
    source = null; form.hidden = true; picker.stop(); offset = 0; search.value = ""; await refresh(); notice("Dataset version saved. It is ready to reuse in any of your conversations.");
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
