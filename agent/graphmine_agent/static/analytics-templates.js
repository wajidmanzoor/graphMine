"use strict";
window.GraphMineTemplates = ({state, api, W, node, runAction, notice, card, parameterControl, parametersFrom, onCreated}) => {
  const $ = id => document.getElementById(id);
  function makeDialog(id, title) {
    const dialog = node("dialog", {id, class: "wide-dialog", "aria-label": title});
    const header = node("div", {class: "section-heading"}), close = node("button", {type: "button", class: "quiet"}, "Close");
    close.onclick = () => { dialog.close(); dialog.remove(); };
    header.append(node("h2", {}, title), close); dialog.append(header); document.body.append(dialog); return dialog;
  }
  const open = async () => {
    const sessionId = state.session?.id; if (!sessionId) throw new Error("Open a conversation first.");
    const templates = await api("/api/workflow-templates");
    const dialog = makeDialog("templates-dialog", "Workflow templates"), choice = node("select", {id: "template-choice", "aria-label": "Workflow template"}), form = node("form", {id: "use-template-form"}), inputs = node("div"), parameters = node("div");
    choice.append(node("option", {value: ""}, "Choose a template"));
    for (const template of templates) choice.append(node("option", {value: template.id}, template.name));
    const use = node("button", {type: "submit", class: "primary", disabled: ""}, "Validate and review"), remove = node("button", {type: "button", class: "quiet danger", hidden: true}, "Delete template");
    dialog.append(node("p", {class: "muted"}, "Choose inputs from this conversation. Import saved datasets through the Dataset library when needed."), choice, form);
    form.append(inputs, parameters, use, remove);
    choice.onchange = () => {
      inputs.replaceChildren(); parameters.replaceChildren(); const template = templates.find(t => t.id === choice.value); use.disabled = !template; remove.hidden = !template;
      if (!template) return;
      for (const [alias, kind] of Object.entries(template.input_kinds)) {
        const label = node("label", {}, `${alias} · ${kind.replaceAll("_", " ")}`), select = node("select", {"data-template-input": alias, required: ""});
        select.append(node("option", {value: ""}, "Choose input"));
        for (const file of state.files.filter(f => (state.kinds[f.id] || f.provenance?.kind || (f.role === "graph" ? "graph" : "")) === kind)) select.append(node("option", {value: file.id}, file.original_name));
        if (alias === "main") select.value = state.active; label.append(select); inputs.append(label);
      }
      for (const step of template.plan.steps) {
        const selected = card(step.operation), section = node("fieldset", {"data-template-step": step.id});
        section.append(node("legend", {}, selected?.title || step.operation));
        if (!selected) { use.disabled = true; section.append(node("p", {}, "This calculation is unavailable. Reconnect to load its capabilities.")); }
        for (const [key, spec] of Object.entries(selected?.parameters || {})) if (!(key in (step.bindings || {}))) {
          const field = parameterControl(key, spec, step.parameters[key] ?? spec.default, `template-${step.id}`);
          field.querySelectorAll("[data-binding-parameter]").forEach(input => input.remove()); section.append(field);
        }
        parameters.append(section);
      }
    };
    form.onsubmit = event => { event.preventDefault(); runAction(async () => {
      if (state.session?.id !== sessionId) throw new Error("The conversation changed. Reopen workflow templates.");
      const template = templates.find(t => t.id === choice.value), bound = {}, settings = {};
      for (const select of inputs.querySelectorAll("[data-template-input]")) bound[select.dataset.templateInput] = {file_id: select.value, kind: template.input_kinds[select.dataset.templateInput]};
      for (const section of parameters.querySelectorAll("[data-template-step]")) {
        const step = template.plan.steps.find(s => s.id === section.dataset.templateStep);
        settings[step.id] = parametersFrom(section, card(step.operation), step.parameters);
      }
      const record = await api(`/api/sessions/${sessionId}/workflow-templates/${template.id}/use`, {method: "POST", body: W.stringify({inputs: bound, parameters: settings})});
      dialog.close(); dialog.remove(); await onCreated(record); notice("Template validated. Review the plan before running it.");
    }); };
    remove.onclick = () => { if (confirm("Delete this saved template? Existing runs remain available.")) runAction(async () => { await api(`/api/workflow-templates/${choice.value}`, {method: "DELETE"}); dialog.close(); dialog.remove(); notice("Template deleted."); }); };
    dialog.showModal();
  };
  return {open};
};
