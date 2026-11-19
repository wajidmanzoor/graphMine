/* Code-supplied parameter contracts; values come from the person or the card. */
(() => {
  "use strict";
  const qualityLabel = value => value === "mixed" ? "Mixed guarantees" : String(value || "Unspecified").replaceAll("_", " ").replace(/^./, c => c.toUpperCase());
  const guarantee = (option, catalog, operation) => catalog?.operations?.find(row => row.id === operation)?.quality_guarantees || option.quality_guarantees?.[operation];
  window.GraphMineDistinctOptions = (options, catalog, wire) => {
    const seen = new Set();
    const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === "object" ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
    return options.filter(option => {
      const parameters = option.operations.map(operation => {
        const values = {...(option.operations.length === 1 ? option.parameters : option.parameters?.[operation])};
        const equivalents = guarantee(option, catalog, operation)?.canonical_requests;
        if (equivalents && Object.hasOwn(equivalents, values.solution_quality)) values.solution_quality = equivalents[values.solution_quality];
        return values;
      });
      const key = wire.stringify(canonical([option.input ?? null, option.operations, parameters]));
      if (seen.has(key)) return false;
      seen.add(key); return true;
    });
  };
  window.GraphMineOptionQuality = (option, catalog, edited = {}) => {
    let verified = true;
    const qualities = option.operations.map(operation => {
      // Current server contracts also correct the badges on historical cards.
      const contract = guarantee(option, catalog, operation);
      const values = option.operations.length === 1 ? option.parameters : option.parameters?.[operation];
      const requested = Object.hasOwn(edited, operation) ? edited[operation] : values?.solution_quality;
      if (contract) return requested == null ? contract.default : contract.by_request?.[requested] || contract.default;
      verified = false;
      return requested || option.operation_qualities?.[operation] || option.quality;
    });
    const quality = new Set(qualities).size === 1 ? qualities[0] : "mixed";
    return (verified ? "" : "Requested: ") + qualityLabel(quality);
  };
  window.GraphMineOptionCard = ({option, catalog, node, wire, onChoose}) => {
    const card = node("section", {class: "calculation-option", "data-option": option.id});
    card.classList.toggle("is-preselected", Boolean(option.preselected));
    const heading = node("div", {class: "option-heading"});
    const quality = node("span", {class: "option-quality pill"}, window.GraphMineOptionQuality(option, catalog));
    heading.append(node("strong", {class: `match-level match-${String(option.match).toLowerCase()}`}, `${option.match} match`), quality);
    if (/potentially expensive|higher cost/i.test(option.cost_hint || "")) heading.append(node("span", {class: "option-cost pill", title: option.cost_hint}, "Potentially expensive"));
    const edited = node("small", {class: "option-edited", hidden: !option.preselected}, "Preselected · awaiting your choice");
    card.append(node("h3", {}, option.title), heading, edited);
    for (const id of option.operations) {
      const operation = catalog?.operations?.find(item => item.id === id);
      const family = (catalog?.task_families || catalog?.families || []).find(item => item.id === operation?.family);
      const selection = node("dl", {class: "option-selection", "aria-label": `Selected calculation: ${id}`});
      const unavailable = catalog ? "Not available in the current catalog" : "Loading catalog…";
      for (const [label, value] of [["Family", family?.title || operation?.family || unavailable], ["Problem", operation?.problem_title || operation?.problem_id || unavailable], ["Operation", id]]) {
        const field = node("div"); field.append(node("dt", {}, label), node("dd", {}, value)); selection.append(field);
      }
      card.append(selection);
    }
    const text = option.description || (/^Another way to explore/i.test(option.interpretation || "") ? "" : option.interpretation || "");
    const description = node("div", {class: "option-description"}), paragraph = node("p", {class: "option-description-text"}, text);
    description.append(paragraph);
    if (text) {
      const more = node("button", {type: "button", class: "quiet option-more", "aria-expanded": "false", hidden: ""}, "more");
      more.onclick = () => { const expanded = more.getAttribute("aria-expanded") !== "true"; more.setAttribute("aria-expanded", String(expanded)); description.classList.toggle("expanded", expanded); more.textContent = expanded ? "less" : "more"; };
      description.append(more);
      const size = new ResizeObserver(() => {
        if (paragraph.isConnected) more.hidden = !description.classList.contains("expanded") && paragraph.scrollHeight <= paragraph.clientHeight + 1;
      });
      size.observe(paragraph);
    }
    card.append(description);
    const fields = node("details", {class: "option-parameters"});
    fields.append(node("summary", {}, "Edit parameters"));
    const controls = [], editedQuality = {};
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
        edited.hidden = false; edited.textContent = "Parameters edited · review before choosing";
        if (field.name === "solution_quality") {
          editedQuality[field.operation] = parse();
          quality.textContent = window.GraphMineOptionQuality(option, catalog, editedQuality);
        }
      });
      controls.push({field, control, parse}); row.append(control);
      if (field.description) row.append(node("small", {}, field.description));
      fields.append(row);
    }
    if (!controls.length) fields.append(node("p", {class: "muted"}, "This calculation has no editable parameters."));
    card.append(fields);
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
