"use strict";
window.GraphMineEditor = ({state, W, node, card, refs, runAction, notice, parameterControl, parametersFrom, loadEditor, submitPlan}) => {
  const $ = id => document.getElementById(id), button = node("button", {id: "open-visual-editor", type: "button", class: "secondary"}, "Edit visually");
  $("save-editor").after(button);
  button.onclick = () => runAction(async () => {
    if (!state.caps) throw new Error("Load calculation capabilities first.");
    if (!$("plan-editor").value.trim()) loadEditor();
    const plan = W.parse($("plan-editor").value), sessionId = state.session?.id, originalId = state.record?.id, originalRevision = state.record?.revision;
    const dialog = node("dialog", {id: "visual-editor", class: "wide-dialog", "aria-label": "Visual workflow editor"}), form = node("form"), list = node("div"), diagram = node("div", {id: "workflow-diagram", style: "height:220px", "aria-label": "Workflow dependencies"});
    const operation = node("select", {id: "visual-operation", "aria-label": "Calculation to add"}), add = node("button", {id: "visual-add", type: "button", class: "secondary"}, "Add step"), close = node("button", {type: "button", class: "quiet"}, "Close");
    for (const c of state.caps.operations.filter(c => c.execution.cpu || c.execution.gpu)) operation.append(node("option", {value: c.id}, c.title));
    form.append(list, operation, add, node("button", {id: "visual-save", type: "submit", class: "primary"}, "Validate and save for review"));
    dialog.append(node("h2", {}, "Visual workflow editor"), node("p", {class: "muted"}, "Connect each calculation to an uploaded input or an earlier graph output. Existing parameter bindings are retained. Use the JSON editor for selectors and other advanced bindings."), diagram, form, close); document.body.append(dialog);
    let cy;
    const finish = () => { cy?.destroy(); dialog.close(); dialog.remove(); };
    close.onclick = finish; dialog.oncancel = event => { event.preventDefault(); finish(); };
    function collect(skip) {
      for (const section of list.children) {
        if (section.dataset.step === skip) continue;
        const step = plan.steps.find(s => s.id === section.dataset.step), selected = card(step.operation);
        step.parameters = parametersFrom(section, selected, step.parameters || {});
        step.input = W.parse(section.querySelector("[data-step-input]").value);
      }
    }
    function render() {
      list.replaceChildren(); const inputs = state.record?.input_files || refs();
      plan.steps.forEach((step, index) => {
        const c = card(step.operation); if (!c) throw new Error(`The calculation ${step.operation} is unavailable.`);
        const section = node("fieldset", {"data-step": step.id}), source = node("select", {"data-step-input": "", required: "", "aria-label": `Input for step ${index + 1}`});
        for (const [alias, ref] of Object.entries(inputs)) if (ref.kind === c.input_kind) source.append(node("option", {value: W.stringify({input: alias})}, `Input: ${alias}`));
        for (const previous of plan.steps.slice(0, index)) for (const [port, spec] of Object.entries(card(previous.operation)?.output_ports || {})) if (spec.type === c.input_kind) source.append(node("option", {value: W.stringify({step: previous.id, port})}, `${card(previous.operation).title}: ${port}`));
        const current = W.stringify(step.input); if (![...source.options].some(option => option.value === current)) source.append(node("option", {value: current}, "Existing reference or selector (checked on validation)")); source.value = current;
        section.append(node("legend", {}, `${index + 1}. ${c.title}`), source);
        for (const [key, spec] of Object.entries(c.parameters)) if (!(key in (step.bindings || {}))) {
          const field = parameterControl(key, spec, step.parameters?.[key] ?? spec.default, `visual-${step.id}`); field.querySelectorAll("[data-binding-parameter]").forEach(el => el.remove()); section.append(field);
        }
        const remove = node("button", {type: "button", class: "quiet danger"}, "Remove step"); remove.onclick = () => {
          try { collect(step.id); if (plan.steps.some(s => s.input.step === step.id || Object.values(s.bindings || {}).some(ref => ref.step === step.id))) throw new Error("Change the dependent steps' inputs before removing this step."); plan.steps.splice(index, 1); render(); } catch (error) { notice(error.message, true); }
        };
        source.onchange = () => { step.input = W.parse(source.value); draw(); }; section.append(remove); list.append(section);
      }); draw();
    }
    function draw() {
      cy?.destroy(); const elements = [], ids = new Set();
      const vertex = (id, label) => { if (!ids.has(id)) { elements.push({data: {id, label}}); ids.add(id); } };
      for (const step of plan.steps) vertex(`step:${step.id}`, card(step.operation)?.title || step.operation);
      for (const step of plan.steps) for (const ref of [step.input, ...Object.values(step.bindings || {})]) {
        const source = ref.input ? `input:${ref.input}` : `step:${ref.step}`; if (ref.input) vertex(source, ref.input);
        if (ids.has(source)) elements.push({data: {id: `link:${elements.length}`, source, target: `step:${step.id}`}});
      }
      cy = window.cytoscape({container: diagram, elements, style: [{selector: "node", style: {label: "data(label)", "font-size": 10, "text-wrap": "wrap", "text-max-width": 110, "background-color": "#72a98f"}}, {selector: "edge", style: {"target-arrow-shape": "triangle", "curve-style": "bezier", width: 2}}], layout: {name: "breadthfirst", directed: true, padding: 40}});
    }
    add.onclick = () => {
      try { collect(); const c = card(operation.value), inputs = state.record?.input_files || refs(), alias = Object.keys(inputs).find(key => inputs[key].kind === c.input_kind); if (!alias && !plan.steps.some(step => Object.values(card(step.operation)?.output_ports || {}).some(port => port.type === c.input_kind))) throw new Error(`Add a ${c.input_kind} input first.`);
        let n = plan.steps.length + 1; while (plan.steps.some(step => step.id === `step_${n}`)) n++;
        const previous = [...plan.steps].reverse().find(step => Object.values(card(step.operation)?.output_ports || {}).some(port => port.type === c.input_kind));
        const input = alias ? {input: alias} : {step: previous.id, port: Object.keys(card(previous.operation).output_ports).find(name => card(previous.operation).output_ports[name].type === c.input_kind)};
        plan.steps.push({id: `step_${n}`, operation: c.id, input, parameters: {}, bindings: {}}); render();
      } catch (error) { notice(error.message, true); }
    };
    form.onsubmit = event => { event.preventDefault(); runAction(async () => {
      if (state.session?.id !== sessionId || state.record?.id !== originalId || state.record?.revision !== originalRevision) throw new Error("The conversation or workflow changed. Reopen the editor.");
      collect(); $("plan-editor").value = W.stringify(plan, true); await submitPlan(plan, Boolean(state.record), null, null, "interactive"); finish();
    }); };
    dialog.showModal(); render();
  });
};
