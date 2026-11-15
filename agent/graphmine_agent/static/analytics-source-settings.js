"use strict";
window.GraphMineConnectionSettings = args => {
  const {node, container, source, canManageImports = false} = args;
  const type = node("select", {id: "connection-type"}), label = node("label", {}, "Connection type"), body = node("div");
  for (const [value, text] of [["neo4j", "Neo4j · Cypher queries"], ["sqlite", "SQLite · uploaded database"], ["rest", "REST API · graph or relationship records"]]) {
    const option = node("option", {value}, text); option.disabled = value !== "neo4j" && !canManageImports; type.append(option);
  }
  if (source?.source_kind === "connector" && source.type === "neo4j") type.append(node("option", {value: "neo4j_http"}, "Neo4j · HTTP export"));
  type.value = source?.source_kind === "connector" ? source.type === "neo4j" ? "neo4j_http" : source.type : "neo4j";
  type.disabled = Boolean(source); label.append(type); container.replaceChildren(label, body);
  if (!canManageImports) container.append(node("p", {class: "source-hint"}, "SQLite uploads and saved API credentials require a signed-in account. Server-configured sources remain available in the picker."));
  const render = () => {
    body.replaceChildren();
    const options = {...args, container: body, kind: type.value};
    if (type.value === "neo4j") window.GraphMineDatabaseConnectionSettings(options);
    else window.GraphMineImportConnectionSettings(options);
  };
  type.onchange = render; render();
};

window.GraphMineImportConnectionSettings = ({api, W, node, container, source, kind, onSaved, onCancel}) => {
  const label = (text, field) => { const value = node("label", {}, text); value.append(field); return value; };
  const checkLabel = (text, field) => { const value = node("label", {class: "check"}); value.append(field, node("span", {}, text)); return value; };
  const input = (id, value = "", attrs = {}) => node("input", {id, value: value || "", ...attrs});
  const form = node("form", {id: "connection-editor", class: "paired-connection-form"}), grid = node("div", {class: "connection-fields"});
  let current = source, tables = source?.tables || [], deleted = false, saving = false;
  const sqlite = kind === "sqlite", legacyNeo = kind === "neo4j_http";
  const name = input("connection-label", source?.name, {required: "", maxlength: "160"});
  const url = input("connection-url", source?.url, {type: "url", required: !sqlite, placeholder: "https://example.com/graph", autocomplete: "off"});
  const credential = input("connection-token", "", {type: "password", autocomplete: "new-password", maxlength: "4096", placeholder: source?.has_credentials ? "Leave blank to keep the saved credential" : legacyNeo ? "Neo4j password" : "Bearer token · optional"});
  const file = input("connection-sqlite-file", "", {type: "file", accept: ".sqlite,.sqlite3,.db"});
  const table = node("select", {id: "connection-table"}), from = node("select", {id: "connection-source-column"}), to = node("select", {id: "connection-target-column"});
  const fromText = input("connection-source-column", source?.source_column || "source", {required: "", maxlength: "256"});
  const toText = input("connection-target-column", source?.target_column || "target", {required: "", maxlength: "256"});
  const format = node("select", {id: "connection-format"});
  for (const [value, text] of [["json_rows", "JSON records"], ["graph", "Graph JSON"], ["csv", "CSV"]]) format.append(node("option", {value}, text));
  format.value = source?.format || "json_rows";
  const rowsField = input("connection-rows-field", source?.rows_field, {maxlength: "256", placeholder: "Optional field containing the records"});
  const directed = input("connection-directed", "", {type: "checkbox"}); directed.checked = Boolean(source?.directed);
  const complete = input("connection-complete", "", {type: "checkbox"}); complete.checked = Boolean(source?.complete_response);
  const username = input("connection-http-username", source?.username || "neo4j", {required: ""});
  const database = input("connection-http-database", source?.database || "neo4j", {required: ""});
  const nodeLabel = input("connection-node-label", source?.node_label), relation = input("connection-relationship-type", source?.relationship_type);
  const mappings = node("fieldset"), status = node("p", {id: "connection-form-status", role: "status", class: "source-status"});
  const save = node("button", {id: "save-connection-settings", type: "submit", class: "primary"}, "Save connection");
  const cancel = node("button", {id: "cancel-connection-settings", type: "button", class: "secondary"}, "Cancel");
  const remove = node("button", {id: "delete-connection", type: "button", class: "quiet", hidden: !current}, "Remove connection");
  const actions = node("div", {class: "source-query-actions"}); actions.append(status, remove, cancel, save);
  grid.append(label("Connection name", name));
  if (sqlite) grid.append(label("Upload and save a private SQLite copy", file), label("Table", table));
  else grid.append(label("Export URL", url), label(legacyNeo ? "Password" : "Bearer token", credential));
  if (legacyNeo) grid.append(label("Database", database), label("Username", username), label("Node label · optional", nodeLabel), label("Relationship type · optional", relation));
  else {
    mappings.append(node("legend", {}, "Relationship columns"), label("From", sqlite ? from : fromText), label("To", sqlite ? to : toText), checkLabel("Directed graph", directed));
    if (!sqlite) grid.append(label("Response format", format), label("Records field · optional", rowsField), checkLabel("This response contains the complete source selection", complete));
  }
  form.append(node("h3", {}, sqlite ? "Connect a SQLite snapshot" : legacyNeo ? "Edit Neo4j HTTP export" : "Connect a REST API"),
    node("p", {class: "source-hint"}, sqlite ? "Uploads are private saved copies. Preview the selected table before importing a graph. Your original database is not changed." : "Preview the response before saving it as a dataset. Tokens are kept on the server and are never returned to the browser."), grid, mappings, actions);
  container.append(form);
  function columns() {
    const values = tables.find(item => item.name === table.value)?.columns || [];
    for (const [select, preferred, fallback] of [[from, current?.source_column, 0], [to, current?.target_column, 1]]) {
      select.replaceChildren(...values.map(value => node("option", {value}, value)));
      select.value = values.includes(preferred) ? preferred : values[fallback] || "";
    }
    save.disabled = saving || sqlite && !current;
  }
  function availableTables() { table.replaceChildren(...tables.map(item => node("option", {value: item.name}, item.name))); if (current?.table) table.value = current.table; columns(); }
  function shape() { mappings.hidden = legacyNeo || !sqlite && format.value === "graph"; fromText.disabled = toText.disabled = mappings.hidden; rowsField.disabled = format.value !== "json_rows"; }
  availableTables(); shape(); table.onchange = columns; format.onchange = shape;
  const done = value => { credential.value = ""; if (form.isConnected) return onSaved(value ? {...value, source_kind: "connector"} : null); };
  cancel.onclick = () => { credential.value = ""; if (!source && current) done(current); else onCancel(); };
  file.onchange = async () => {
    if (!file.files[0] || saving) return;
    const data = new FormData(); data.append("file", file.files[0]);
    saving = true; save.disabled = cancel.disabled = file.disabled = true; status.textContent = "Saving the private SQLite copy…";
    try {
      const value = await api("/api/connectors/sqlite", {method: "POST", body: data});
      if (!form.isConnected) return;
      current = value; tables = value.tables; if (!name.value.trim()) name.value = value.name;
      availableTables(); remove.hidden = false; file.hidden = true;
      status.textContent = "SQLite copy saved. Choose the relationship columns, then save the mapping.";
    } catch (error) { if (form.isConnected) status.textContent = error.message; }
    finally { saving = false; cancel.disabled = file.disabled = false; save.disabled = !current; file.value = ""; }
  };
  remove.onclick = async () => {
    if (!deleted) { deleted = true; remove.textContent = "Confirm removal"; status.textContent = "Remove this connection and its credentials? Saved dataset versions remain available."; return; }
    saving = true; remove.disabled = save.disabled = cancel.disabled = true;
    try { await api(`/api/connectors/${encodeURIComponent(current.id)}`, {method: "DELETE"}); await done(null); }
    catch (error) { if (form.isConnected) status.textContent = error.message; }
    finally { saving = false; remove.disabled = save.disabled = cancel.disabled = false; }
  };
  form.onsubmit = async event => {
    event.preventDefault(); if (saving || sqlite && !current) return;
    saving = true; save.disabled = cancel.disabled = true; status.textContent = "Saving connection…";
    const body = {name: name.value.trim(), type: legacyNeo ? "neo4j" : kind,
      ...(sqlite ? {table: table.value, source_column: from.value, target_column: to.value, directed: directed.checked} : {
        url: url.value.trim(), format: format.value, rows_field: rowsField.value.trim() || null,
        source_column: fromText.value, target_column: toText.value, directed: directed.checked, complete_response: complete.checked,
        ...(legacyNeo ? {database: database.value.trim(), username: username.value.trim(), node_label: nodeLabel.value.trim() || null, relationship_type: relation.value.trim() || null} : {}),
        ...(credential.value ? {[legacyNeo ? "password" : "bearer_token"]: credential.value} : {}),
      })};
    try {
      if ((sqlite || !legacyNeo && format.value !== "graph") && body.source_column === body.target_column) throw new Error("Choose two different relationship columns.");
      const result = await api(current ? `/api/connectors/${encodeURIComponent(current.id)}` : "/api/connectors", {method: current ? "PUT" : "POST", body: W.stringify(body)});
      await done(result);
    } catch (error) { if (form.isConnected) { status.textContent = error.message; status.classList.add("source-error"); } }
    finally { saving = false; save.disabled = cancel.disabled = false; }
  };
  name.focus();
};
