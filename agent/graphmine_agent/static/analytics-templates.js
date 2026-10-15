"use strict";
window.GraphMineTemplates = ({state, api, W, node, runAction, notice, card, parameterControl, parametersFrom, onCreated}) => {
  const $ = id => document.getElementById(id);
  function makeDialog(id, title) {
    const dialog = node("dialog", {id, class: "wide-dialog", "aria-label": title});
    const header = node("div", {class: "section-heading"}), close = node("button", {type: "button", class: "quiet"}, "Close");
    close.onclick = () => { dialog.close(); dialog.remove(); };
    header.append(node("h2", {}, title), close); dialog.append(header); document.body.append(dialog); return dialog;
  }
  const open = node("button", {id: "open-templates", type: "button", class: "secondary full-width"}, "Workflow templates");
  $("open-datasets").after(open);
  const save = node("button", {id: "save-workflow-template", type: "button", class: "quiet"}, "Save as template");
  $("review-example").after(save);
  save.onclick = () => runAction(async () => {
    const record = state.record; if (!record) throw new Error("Open a validated workflow first.");
    const dialog = makeDialog("save-template-dialog", "Save workflow template"), form = node("form"), name = node("input", {id: "template-name", required: "", maxlength: "160"}), label = node("label", {}, "Template name");
    label.append(name); form.append(label, node("p", {class: "muted"}, "The steps and settings are saved. Each use binds new inputs and waits for review before running."), node("button", {type: "submit", class: "primary"}, "Save template")); dialog.append(form);
    form.onsubmit = event => { event.preventDefault(); runAction(async () => {
      await api("/api/workflow-templates", {method: "POST", body: W.stringify({name: name.value, workflow_id: record.id, expected_revision: record.revision})});
      dialog.close(); dialog.remove(); notice("Workflow template saved.");
    }); };
    dialog.showModal(); name.focus();
  });
  open.onclick = () => runAction(async () => {
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
  });
  const compare = node("button", {id: "compare-runs", type: "button", class: "secondary"}, "Compare saved runs");
  $("result-actions").append(compare);
  compare.onclick = () => runAction(async () => {
    const history = (await api("/api/workflow-history")).filter(r => ["completed", "failed"].includes(r.status));
    const dialog = makeDialog("comparison-dialog", "Compare saved runs"), form = node("form"), choices = node("div"), output = node("div", {id: "comparison-output", class: "table-wrap"});
    for (const row of history) {
      const label = node("label", {class: "check"}), checkbox = node("input", {type: "checkbox", value: row.id, "data-compare-run": row.id});
      checkbox.checked = row.id === state.record?.id; label.append(checkbox, document.createTextNode(`${row.conversation || "Conversation"} · ${row.operations.join(", ")} · ${row.created_at || row.id}`)); choices.append(label);
    }
    form.append(choices, node("button", {type: "submit", class: "primary"}, "Compare selected runs")); dialog.append(form, output);
    form.onsubmit = event => { event.preventDefault(); runAction(async () => {
      const ids = [...choices.querySelectorAll("input:checked")].map(input => input.value);
      if (ids.length < 2 || ids.length > 6) throw new Error("Choose between two and six saved runs.");
      const comparison = await api("/api/workflows/compare", {method: "POST", body: W.stringify({workflow_ids: ids})});
      output.replaceChildren(node("p", {}, comparison.note)); const table = node("table"), head = node("tr"); head.append(node("th", {}, "Measure"));
      for (const run of comparison.runs) head.append(node("th", {}, `${run.id.slice(0, 8)} · revision ${run.revision}`)); table.append(head);
      for (const [label, value] of [["Status", r => r.status], ["Run time (seconds)", r => r.runtime_seconds ?? "Not recorded"], ["Inputs", r => W.stringify(r.inputs, true)], ["Algorithms, parameters and outputs", r => W.stringify(r.steps, true)], ["Findings", r => r.facts.map(f => f.statement).join("\n")]]) {
        const row = node("tr"); row.append(node("th", {}, label)); for (const run of comparison.runs) { const cell = node("td"); cell.append(node("pre", {}, String(value(run)))); row.append(cell); } table.append(row);
      }
      output.append(table);
    }); };
    dialog.showModal();
  });
};
