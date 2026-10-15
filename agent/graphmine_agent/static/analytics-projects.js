"use strict";
window.GraphMineProjects = ({state, api, W, node, runAction, notice, renderFiles, previewActive}) => {
  const $ = id => document.getElementById(id), link = node("a", {href: "/projects.html", class: "secondary full-width"}, "Project workspaces"); $("open-datasets").after(link);
  const publish = async result => {
    const projects = (await api("/api/projects")).filter(p => p.role !== "viewer"), dialog = node("dialog", {class: "wide-dialog", id: "publish-project"}), form = node("form"), choices = node("select", {id: "publish-project-choice", required: ""}), name = node("input", {id: "publish-project-name", required: "", maxlength: "160"});
    if (!projects.length) throw new Error("Create a project first, or ask its owner to add you as an editor.");
    let source;
    if (result) { if (!state.record || !state.result) throw new Error("Open a saved result first."); source = {workflow_id: state.record.id, expected_revision: state.record.revision}; name.value = "Analysis result"; }
    else { const file = state.files.find(f => f.id === state.active); if (!file) throw new Error("Choose an input first."); source = {file_id: file.id, kind: state.kinds[file.id] || "graph"}; name.value = file.original_name; }
    for (const p of projects) choices.append(node("option", {value: p.id}, p.name));
    const close = node("button", {type: "button", class: "quiet"}, "Cancel"); close.onclick = () => { dialog.close(); dialog.remove(); };
    for (const [text, control] of [["Project", choices], ["Shared snapshot name", name]]) { const label = node("label", {}, text); label.append(control); form.append(label); }
    form.append(node("p", {}, result ? "This shares the full saved result, input snapshots, plan and provenance with project members. Your conversation messages remain private." : "This shares the full selected input and its provenance with project members as an independent snapshot."), node("button", {class: "primary"}, "Share snapshot"), close); dialog.append(form); document.body.append(dialog); dialog.showModal();
    form.onsubmit = event => { event.preventDefault(); runAction(async () => { await api(`/api/projects/${choices.value}/items`, {method: "POST", body: W.stringify({name: name.value, ...source})}); dialog.close(); dialog.remove(); notice("Snapshot shared with the project."); }); };
  };
  const input = node("button", {id: "share-project-input", class: "quiet full-width", type: "button"}, "Share input to project"), result = node("button", {id: "share-project-result", class: "quiet", type: "button"}, "Share result to project"); $("open-datasets").after(input); $("result-actions").append(result); input.onclick = () => runAction(() => publish(false)); result.onclick = () => runAction(() => publish(true));
  const reuse = node("button", {id: "import-project-item", class: "quiet full-width", type: "button"}, "Use a project input"); input.after(reuse);
  (window.GraphMineAccount?.ready || Promise.resolve(false)).then(enabled => { for (const control of [link, input, result, reuse]) control.hidden = !enabled; });
  reuse.onclick = () => runAction(async () => {
    if (!state.session) throw new Error("Open a conversation first."); const sid = state.session.id, projects = await api("/api/projects"), dialog = node("dialog", {class: "wide-dialog"}), select = node("select", {"aria-label": "Project input"}), options = [];
    for (const project of projects) for (const item of (await api(`/api/projects/${project.id}`)).items) if (item.kind !== "workflow") { options.push(item); select.append(node("option", {value: item.id}, `${project.name} · ${item.name}`)); }
    const button = node("button", {type: "button", class: "primary"}, "Import independent copy"), close = node("button", {type: "button", class: "quiet"}, "Close"); button.disabled = !options.length; close.onclick = () => { dialog.close(); dialog.remove(); };
    button.onclick = () => runAction(async () => { if (state.session?.id !== sid) throw new Error("The conversation changed. Reopen project inputs."); const data = await api(`/api/sessions/${sid}/project-items/${select.value}/import`, {method: "POST"}); if (state.session?.id !== sid) return; state.files.push(data.file); state.kinds[data.file.id] = data.kind; state.active = data.file.id; renderFiles(); await previewActive(); close.click(); notice("Project input copied into this conversation."); });
    dialog.append(node("h2", {}, "Use a shared project input"), select, button, close); document.body.append(dialog); dialog.showModal();
  });
};
