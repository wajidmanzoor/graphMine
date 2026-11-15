"use strict";
window.GraphMineTableMappings = ({node, W, container, source}) => {
  const editor = node("div", {class: "mapping-editor"});
  const advanced = node("details");
  const json = node("textarea", {id: "connection-mappings", rows: "8", class: "code-editor", "aria-label": "Table mappings JSON", spellcheck: "false"});
  const error = node("p", {class: "connection-field-error", role: "status"});
  advanced.append(node("summary", {}, "Advanced · edit mappings as JSON"), json, error);
  const addNode = node("button", {type: "button", class: "secondary"}, "Add node table");
  const addEdge = node("button", {type: "button", class: "secondary"}, "Add relationship table");
  const actions = node("div", {class: "source-query-actions"}); actions.append(addNode, addEdge);
  container.append(editor, actions, advanced);
  let value = {entities: structuredClone(source?.entities || []), relationships: structuredClone(source?.relationships || [])};
  const sync = () => { json.value = W.stringify(value, true); json.setCustomValidity(""); error.textContent = ""; };
  function render() {
    editor.replaceChildren();
    for (const kind of ["entities", "relationships"]) value[kind].forEach((mapping, index) => {
      const row = node("details", {class: "mapping-row"}); row.open = !mapping.id;
      const title = node("summary", {}, `${kind === "entities" ? "Node" : "Relationship"} table · ${mapping.table || "New mapping"}`);
      const fields = node("div", {class: "mapping-fields"});
      const addField = (key, text, list = false, optional = false) => {
        const input = node("input", {type: "text", "aria-label": text, "data-mapping-field": `${kind}.${index}.${key}`});
        input.value = list ? (mapping[key] || []).join(", ") : mapping[key] || "";
        input.required = !optional;
        if (!list) input.pattern = "[A-Za-z_][A-Za-z0-9_]*";
        const label = node("label", {}, text); label.append(input); fields.append(label);
        input.oninput = () => {
          const next = input.value.trim();
          if (list) {
            const names = next ? next.split(",").map(v => v.trim()) : [];
            input.setCustomValidity(names.some(name => !/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) ? "Use comma-separated column names." : "");
            mapping[key] = names;
          } else if (next || !optional) mapping[key] = next;
          else delete mapping[key];
          title.textContent = `${kind === "entities" ? "Node" : "Relationship"} table · ${mapping.table || "New mapping"}`;
          sync();
        };
      };
      addField("id", "Mapping name");
      addField("schema_name", "SQL schema");
      addField("table", "SQL table");
      addField("label", kind === "entities" ? "Neo4j label" : "Relationship type");
      addField("key", "Unique key columns", true);
      addField("attributes", "Exposed attribute columns", true, true);
      if (kind === "entities") addField("display", "Display column (optional)", false, true);
      else {
        for (const [key, text] of [["source_entity", "Source node mapping"], ["target_entity", "Target node mapping"]]) {
          const select = node("select", {"aria-label": text, required: "", "data-mapping-field": `${kind}.${index}.${key}`});
          const fill = () => {
            select.replaceChildren(node("option", {value: ""}, "Choose a node mapping"));
            for (const entity of value.entities) if (entity.id) select.append(node("option", {value: entity.id}, entity.id));
            select.value = mapping[key] || "";
          };
          fill(); select.onfocus = fill;
          select.onchange = () => { mapping[key] = select.value; sync(); };
          const label = node("label", {}, text); label.append(select); fields.append(label);
        }
        addField("source_columns", "Source key columns", true);
        addField("target_columns", "Target key columns", true);
        addField("weight", "Weight column (optional)", false, true);
        addField("timestamp", "Timestamp column (optional)", false, true);
      }
      const remove = node("button", {type: "button", class: "quiet"}, "Remove mapping");
      remove.onclick = () => { value[kind].splice(index, 1); sync(); render(); };
      row.append(title, fields, remove); editor.append(row);
    });
  }
  json.oninput = () => {
    try {
      const parsed = W.parse(json.value);
      if (!Array.isArray(parsed.entities) || !Array.isArray(parsed.relationships)) throw new Error("Provide entities and relationships arrays.");
      value = parsed; json.setCustomValidity(""); error.textContent = ""; render();
    } catch (e) { json.setCustomValidity(e.message); error.textContent = e.message; }
  };
  const add = kind => {
    value[kind].push({id: "", schema_name: "public", table: "", label: "", key: [], attributes: []});
    sync(); render(); editor.querySelector(".mapping-row:last-child input")?.focus();
  };
  addNode.onclick = () => add("entities"); addEdge.onclick = () => add("relationships");
  sync(); render();
  return {
    read: () => W.parse(json.value),
    showError(message) {
      const field = [...editor.querySelectorAll("[data-mapping-field]")].find(el => message.startsWith(el.dataset.mappingField));
      if (field) { field.closest("details").open = true; field.setAttribute("aria-invalid", "true"); field.focus(); }
      error.textContent = message; advanced.open = true;
    },
  };
};
