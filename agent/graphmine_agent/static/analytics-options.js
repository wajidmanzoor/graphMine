/* Code-supplied parameter contracts; values come from the person or the card. */
(() => {
  "use strict";
  window.GraphMineOptionCard = ({option, node, wire, onChoose}) => {
    const card = node("section", {class: "calculation-option", "data-option": option.id});
    card.classList.toggle("is-preselected", Boolean(option.preselected));
    const heading = node("div", {class: "option-heading"});
    heading.append(node("strong", {class: `match-level match-${String(option.match).toLowerCase()}`}, `${option.match} match`));
    if (option.preselected) heading.append(node("small", {}, "Preselected · awaiting your choice"));
    card.append(heading, node("h3", {}, option.title), node("p", {class: "option-interpretation"}, option.interpretation || option.description));
    const quality = option.quality === "mixed"
      ? Object.entries(option.operation_qualities || {}).map(([operation, value]) => `${operation}: ${value}`).join(" · ")
      : option.quality === "exact" ? "Exact" : `${option.quality} · no exact guarantee`;
    card.append(node("p", {class: "option-quality"}, quality));
    if (option.cost_hint) card.append(node("p", {class: "option-cost"}, option.cost_hint));
    if (option.difference) card.append(node("p", {class: "option-difference"}, option.difference));
    const description = node("details");
    description.append(node("summary", {}, "What this finds"), node("p", {}, option.description));
    card.append(description);
    const fields = node("details", {class: "option-parameters"});
    fields.append(node("summary", {}, "Parameters · review or edit"));
    const controls = [];
    for (const [index, field] of (option.parameter_fields || []).entries()) {
      const id = `${option.id}-parameter-${index}-${Math.random().toString(36).slice(2, 8)}`;
      const row = node("div", {class: "option-parameter"});
      row.append(node("label", {for: id}, `${option.operations.length > 1 ? field.operation + " · " : ""}${field.label}${field.required ? " (required)" : ""}`));
      const choices = field.schema.enum || field.schema.anyOf?.find(branch => branch.enum)?.enum;
      let control, parse;
      if (choices || field.kind === "boolean") {
        control = node("select", {id, "data-parameter": field.name});
        control.append(node("option", {value: ""}, field.application_filled ? "Filled from the selected input" : "Use default / ask if required"));
        for (const value of choices || [true, false]) control.append(node("option", {value: wire.stringify(value)}, String(value).replaceAll("_", " ")));
        control.value = field.has_value ? wire.stringify(field.value) : "";
        parse = () => control.value === "" ? undefined : wire.parse(control.value);
      } else {
        const compound = ["array", "object"].includes(field.kind);
        control = node(compound ? "textarea" : "input", {id, "data-parameter": field.name,
          ...(compound ? {rows: "3", spellcheck: "false"} : {type: "text"}),
          placeholder: field.application_filled ? "Filled from the full selected input; optional JSON override" : field.has_value ? "" : "Use default / ask if required"});
        control.value = field.has_value ? field.kind === "string" ? field.value : wire.stringify(field.value) : "";
        parse = () => {
          const value = control.value.trim();
          if (!value) return undefined;
          if (field.kind === "string") return control.value;
          if (field.kind === "vertex_id") {
            try { return wire.parse(value); } catch { return value; }
          }
          return wire.parse(value);
        };
      }
      control.addEventListener("input", () => {
        card.classList.remove("is-preselected");
        heading.replaceChildren(node("small", {}, "Parameters edited · review before choosing"));
      });
      controls.push({field, control, parse}); row.append(control);
      if (field.description) row.append(node("small", {}, field.description));
      fields.append(row);
    }
    if (controls.length) card.append(fields);
    const error = node("p", {class: "option-error", role: "alert", hidden: ""});
    const button = node("button", {class: "primary", type: "button", "data-pick-option": option.id}, "Use this option");
    button.addEventListener("click", async () => {
      const parameters = controls.length ? (option.operations.length > 1 ? Object.fromEntries(option.operations.map(op => [op, {}])) : {}) : option.parameters;
      try {
        for (const {field, control, parse} of controls) {
          let value;
          try { value = parse(); } catch { control.focus(); throw new Error(`Enter valid ${field.kind === "array" || field.kind === "object" ? "JSON" : field.kind} for ${field.label}.`); }
          if (value !== undefined) (option.operations.length > 1 ? parameters[field.operation] : parameters)[field.name] = value;
        }
        error.hidden = true; button.disabled = true;
        await onChoose({...option, parameters});
      } catch (failure) {
        error.textContent = failure.message; error.hidden = false;
      } finally { button.disabled = false; }
    });
    card.append(error, button);
    return card;
  };
})();
