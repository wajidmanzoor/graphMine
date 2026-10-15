"use strict";
window.GraphMineImport = async ({file, options, sessionId, api, W, node}) => {
  const dialog = node("dialog", {id: "import-dialog", class: "wide-dialog", "aria-label": "Preview CSV import"});
  const form = node("form"), source = node("select", {id: "import-source"}), target = node("select", {id: "import-target"});
  const directed = node("input", {type: "checkbox", id: "import-directed"}); directed.checked = options.directed;
  const summary = node("p", {id: "import-summary", role: "status"}), sample = node("pre", {id: "import-sample"});
  const accept = node("button", {type: "submit", class: "primary", id: "confirm-import"}, "Import this graph");
  const cancel = node("button", {type: "button", class: "quiet"}, "Cancel");
  form.append(node("h2", {}, "Preview CSV import"), node("p", {class: "muted"}, "Check which columns form connections. This preview has not saved a file."));
  for (const [text, input] of [["From column", source], ["To column", target], ["Directed connections", directed]]) { const label = node("label", {}, text); label.append(input); form.append(label); }
  form.append(summary, sample, accept, cancel); dialog.append(form); document.body.append(dialog);
  let generation = 0, checked = null;
  async function refresh(initial = false) {
    const current = ++generation; accept.disabled = true; checked = null; summary.textContent = "Checking the full file…";
    const chosen = initial ? options : {directed: directed.checked, source_column: source.value, target_column: target.value};
    const body = new FormData(); body.append("file", file); body.append("directed", String(chosen.directed));
    for (const key of ["source_column", "target_column"]) if (chosen[key]) body.append(key, chosen[key]);
    try {
      const result = await api(`/api/sessions/${sessionId}/files/preview`, {method: "POST", body});
      if (current !== generation) return;
      for (const [select, column] of [[source, result.provenance.source_column], [target, result.provenance.target_column]]) {
        select.replaceChildren(...result.columns.map(c => node("option", {value: c}, c))); select.value = column;
      }
      const m = result.metadata; summary.textContent = `${result.row_count.toLocaleString()} rows · ${m.vertex_count.toLocaleString()} vertices · ${m.edge_count.toLocaleString()} connections. ${m.allows_parallel_edges ? "Repeated connections retained. " : ""}${m.allows_self_loops ? "Self connections retained. " : ""}IDs such as 001 remain text.`;
      sample.textContent = W.stringify(result.sample, true); checked = {directed: chosen.directed, source_column: source.value, target_column: target.value}; accept.disabled = false;
    } catch (error) { if (current === generation) summary.textContent = error.message; }
  }
  return new Promise(resolve => {
    const finish = value => { generation++; dialog.close(); dialog.remove(); resolve(value); };
    cancel.onclick = () => finish(null);
    dialog.oncancel = event => { event.preventDefault(); finish(null); };
    form.onsubmit = event => { event.preventDefault(); if (checked) finish(checked); };
    for (const input of [source, target, directed]) input.onchange = () => refresh();
    dialog.showModal(); refresh(true);
  });
};
