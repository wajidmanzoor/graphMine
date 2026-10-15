"use strict";
window.GraphMineControls = ({state, W, node, refs, title, choiceNames}) => {
  function parameterControl(key, spec, value, prefix) {
    const label = node("label", {}, title(key)), id = `${prefix}-${key}`;
    let input;
    if (spec.choices) {
      input = node("select", {id, "data-parameter": key});
      if (spec.required) input.append(node("option", {value: ""}, "Choose…"));
      else if (spec.nullable) input.append(node("option", {value: "null"}, "Not specified"));
      spec.choices.forEach(choice => input.append(node("option", {value: W.stringify(choice)}, choiceNames[choice] || title(choice))));
      input.value = value === undefined ? (spec.required ? "" : W.stringify(spec.choices[0])) : W.stringify(value);
    } else if (spec.kind === "boolean") {
      input = node("select", {id, "data-parameter": key});
      input.append(node("option", {value: "true"}, "Yes"), node("option", {value: "false"}, "No")); input.value = String(value ?? false);
    } else if (["array", "object"].includes(spec.kind)) {
      input = node("textarea", {id, "data-parameter": key, rows: "2", spellcheck: "false", placeholder: spec.kind === "array" ? '["Alice", "Bob"]' : "{}"});
      input.value = value === undefined || value === null ? "" : W.stringify(value);
    } else {
      input = node("input", {id, "data-parameter": key, type: "text", spellcheck: "false"});
      input.value = value === undefined || value === null ? "" : spec.kind === "vertex_id" ? W.stringify(value) : String(value);
      if (["integer", "number"].includes(spec.kind)) input.setAttribute("inputmode", "decimal");
      if (spec.kind === "vertex_id") {
        input.placeholder = '"Alice" or 42';
        const list = node("datalist", {id: `${id}-choices`});
        for (const v of (state.previews.get(state.active)?.vertices || [])) list.append(node("option", {value: W.stringify(v.id)}, v.label || W.idLabel(v.id)));
        input.setAttribute("list", list.id); label.append(list);
      }
    }
    if (spec.required) input.setAttribute("aria-required", "true");
    label.append(input);
    if (["query_graph", "other_graph"].includes(key)) {
      const binding = node("select", {"data-binding-parameter": key, "aria-label": `${title(key)} input source`});
      binding.append(node("option", {value: ""}, "Enter canonical graph JSON above"));
      for (const [alias, source] of Object.entries(refs())) if (source.kind === "graph") binding.append(node("option", {value: alias}, `Use uploaded graph: ${alias}`));
      binding.addEventListener("change", () => input.disabled = Boolean(binding.value));
      label.append(binding);
    }
    if (spec.description || spec.required) label.append(node("span", {class: "parameter-hint"}, `${spec.required ? "Required. " : ""}${spec.description || ""}`));
    if (spec.nullable && !spec.choices) label.append(node("span", {class: "parameter-hint"}, "Leave empty to use the default or no limit."));
    return label;
  }
  function parametersFrom(container, selected, defaults = {}) {
    const parameters = {...defaults};
    for (const input of container.querySelectorAll("[data-parameter]")) {
      const key = input.dataset.parameter, spec = selected.parameters[key], raw = input.value.trim();
      if (input.disabled) { delete parameters[key]; continue; }
      if (!raw) {
        if (spec.required) throw new Error(`Choose ${title(key).toLowerCase()} before continuing.`);
        parameters[key] = spec.default;
        continue;
      }
      try { parameters[key] = spec.kind === "string" && !spec.choices ? input.value : W.parse(raw); }
      catch { throw new Error(`${title(key)} needs a valid ${spec.kind === "vertex_id" ? 'ID (a quoted name or integer)' : spec.kind} value.`); }
    }
    return parameters;
  }
  function bindingsFrom(container, defaults = {}) {
    const bindings = {...defaults};
    for (const input of container.querySelectorAll("[data-binding-parameter]")) {
      const key = input.dataset.bindingParameter;
      if (input.value) bindings[key] = {input: input.value}; else delete bindings[key];
    }
    return bindings;
  }
  return {parameterControl, parametersFrom, bindingsFrom};
};
