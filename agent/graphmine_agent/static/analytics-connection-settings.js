"use strict";
window.GraphMineConnectionSettings = ({api, W, node, runAction, notice, dialog, form, choice, getSources, refresh}) => {
  const label = (text, field) => { const element = node("label", {}, text); element.append(field); return element; };
  const input = (id, attrs = {}) => node("input", {id, ...attrs});
  const action = (id, text) => node("button", {id, type: "button", class: "secondary"}, text);
  const controls = node("div", {class: "connector-actions"});
  const add = action("add-connection", "Add connection"), edit = action("edit-connection", "Edit connection"), remove = action("delete-connection", "Remove connection");
  controls.append(add, edit, remove);
  const editor = node("form", {id: "connection-editor", hidden: true});
  const kind = node("select", {id: "connection-type"}), name = input("connection-label", {required: "", maxlength: "160"});
  for (const [value, text] of [["sqlite", "SQLite database"], ["rest", "Node.js / REST API"], ["neo4j", "Neo4j"]]) kind.append(node("option", {value}, text));
  const file = input("connection-file", {type: "file", accept: ".db,.sqlite,.sqlite3"}), upload = action("upload-connection", "Upload database"), table = node("select", {id: "connection-table"});
  const sqlite = node("fieldset"); sqlite.append(node("legend", {}, "SQLite source"), label("Database backup file", file), upload, label("Table", table), node("p", {}, "A private copy is stored in your account. Later changes to the original file are not synchronized."));
  const url = input("connection-url", {type: "url", required: "", maxlength: "2048", placeholder: "https://your-server.example"});
  const network = node("fieldset"); network.append(node("legend", {}, "Server"), label("HTTP(S) address", url));
  const format = node("select", {id: "connection-format"});
  for (const [value, text] of [["json_rows", "JSON records"], ["graph", "Graph JSON"], ["csv", "CSV"]]) format.append(node("option", {value}, text));
  const rows = input("connection-rows-field", {placeholder: "Optional, for example data"}), token = input("connection-token", {type: "password", autocomplete: "new-password"}), complete = input("connection-complete", {type: "checkbox"});
  const rest = node("fieldset"); rest.append(node("legend", {}, "API export"), label("Response format", format), label("JSON array field", rows), label("Bearer token (optional)", token), label("This endpoint returns the complete source", complete), node("p", {}, "Works with Node.js and other HTTP APIs. Supply one JSON or CSV export without pagination."));
  const database = input("connection-database", {value: "neo4j", required: ""}), username = input("connection-username", {value: "neo4j", required: "", autocomplete: "off"}), password = input("connection-password", {type: "password", autocomplete: "new-password"});
  const nodeLabel = input("connection-node-label"), relationship = input("connection-relationship-type");
  const neo4j = node("fieldset"); neo4j.append(node("legend", {}, "Neo4j Query API"), label("Database", database), label("Username", username), label("Password", password), label("Source node label (optional)", nodeLabel), label("Relationship type (optional)", relationship), node("p", {}, "Imports matching relationships and their endpoints; isolated nodes are excluded. Use the HTTP(S) Query API address and an account with read access."));
  const source = input("connection-source", {value: "source", list: "connection-columns"}), target = input("connection-target", {value: "target", list: "connection-columns"}), columns = node("datalist", {id: "connection-columns"}), directed = input("connection-directed", {type: "checkbox"});
  const mapping = node("fieldset"); mapping.append(node("legend", {}, "Relationship columns"), label("Source column", source), label("Target column", target), columns, label("Directed connections", directed));
  const save = node("button", {id: "save-connection-settings", class: "primary"}, "Save connection"), back = action("cancel-connection-settings", "Back");
  editor.append(node("h3", {}, "Connection settings"), label("Type", kind), label("Connection name", name), sqlite, network, rest, neo4j, mapping, save, back);
  dialog.insertBefore(controls, form); dialog.insertBefore(editor, form);
  let editing = null, tables = [];
  const clearSecrets = () => { token.value = password.value = ""; };
  const reset = () => { edit.disabled = remove.disabled = !getSources().find(s => s.id === choice.value)?.managed; };
  const fields = () => {
    for (const [element, show] of [[sqlite, kind.value === "sqlite"], [network, kind.value !== "sqlite"], [rest, kind.value === "rest"], [neo4j, kind.value === "neo4j"], [mapping, kind.value === "sqlite" || kind.value === "rest" && format.value !== "graph"]]) { element.hidden = !show; element.disabled = !show; }
    file.disabled = upload.disabled = !!editing; save.disabled = kind.value === "sqlite" && !editing;
  };
  const selectedTable = (preserve = false) => {
    const names = tables.find(t => t.name === table.value)?.columns || [];
    columns.replaceChildren(...names.map(value => node("option", {value})));
    if (!preserve) { source.value = names.includes("source") ? "source" : names[0] || "source"; target.value = names.includes("target") ? "target" : names.find(n => n !== source.value) || "target"; }
  };
  const populate = data => {
    editing = data?.id || null; tables = data?.tables || []; kind.disabled = !!editing;
    kind.value = data?.type || "sqlite"; name.value = data?.name || ""; url.value = data?.url || "";
    format.value = data?.format || "json_rows"; rows.value = data?.rows_field || "";
    source.value = data?.source_column || "source"; target.value = data?.target_column || "target"; directed.checked = !!data?.directed;
    database.value = data?.database || "neo4j"; username.value = data?.username || "neo4j";
    nodeLabel.value = data?.node_label || ""; relationship.value = data?.relationship_type || "";
    clearSecrets(); token.placeholder = password.placeholder = data?.has_credentials ? "Leave blank to keep the saved credential" : "";
    complete.checked = !!data?.complete_response; table.replaceChildren(...tables.map(t => node("option", {value: t.name}, t.name)));
    table.value = data?.table || tables[0]?.name || ""; selectedTable(true); fields();
    form.hidden = controls.hidden = true; editor.hidden = false;
  };
  const finish = () => { clearSecrets(); editor.hidden = true; form.hidden = controls.hidden = false; reset(); };
  add.onclick = () => populate(null);
  edit.onclick = () => runAction(async () => populate(await api(`/api/connectors/${choice.value}`)));
  back.onclick = finish; kind.onchange = fields; format.onchange = fields; table.onchange = () => selectedTable(); choice.addEventListener("change", reset);
  upload.onclick = () => runAction(async () => {
    if (!file.files[0]) throw new Error("Choose a SQLite database file first.");
    const body = new FormData(); body.append("file", file.files[0]);
    const result = await api("/api/connectors/sqlite", {method: "POST", body});
    if (!dialog.isConnected) return;
    const chosenName = name.value; await refresh(result.id); populate(result); if (chosenName) name.value = chosenName;
    notice("Database uploaded. Choose its table and columns, then save the connection.");
  });
  editor.onsubmit = event => { event.preventDefault(); runAction(async () => {
    const body = {name: name.value, type: kind.value};
    if (kind.value === "sqlite") Object.assign(body, {table: table.value, source_column: source.value, target_column: target.value, directed: directed.checked});
    else body.url = url.value;
    if (kind.value === "rest") Object.assign(body, {format: format.value, rows_field: rows.value || null, source_column: source.value, target_column: target.value, directed: directed.checked, complete_response: complete.checked, ...(token.value ? {bearer_token: token.value} : {})});
    if (kind.value === "neo4j") Object.assign(body, {database: database.value, username: username.value, node_label: nodeLabel.value || null, relationship_type: relationship.value || null, ...(password.value ? {password: password.value} : {})});
    const result = await api(editing ? `/api/connectors/${editing}` : "/api/connectors", {method: editing ? "PUT" : "POST", body: W.stringify(body)});
    if (!dialog.isConnected) return;
    await refresh(result.id); finish(); notice("Connection saved. Preview it before importing.");
  }); };
  remove.onclick = () => runAction(async () => {
    if (!window.confirm("Remove this connection? Imported dataset versions will stay in your library.")) return;
    await api(`/api/connectors/${choice.value}`, {method: "DELETE"}); await refresh(); reset(); notice("Connection removed.");
  });
  dialog.addEventListener("close", clearSecrets); reset();
};
