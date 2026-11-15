"use strict";
window.GraphMineDatabaseConnectionSettings = ({api, W, node, container, source, onSaved, onCancel}) => {
  const label = (text, field) => { const el = node("label", {}, text); el.append(field); return el; };
  const input = (id, value = "", attributes = {}) => { const el = node("input", {id, ...attributes}); el.value = value; return el; };
  const form = node("form", {id: "connection-editor", class: "paired-connection-form"});
  const sql = source?.connection?.sql || {}, neo = source?.connection?.neo4j || {};
  const name = input("connection-label", source?.name, {required: "", maxlength: "160", placeholder: "e.g. Research database"});
  const host = input("connection-host", sql.host, {required: "", placeholder: "localhost or db.example.com", autocomplete: "off"});
  const port = input("connection-port", sql.port || 5432, {type: "number", min: "1", max: "65535", required: ""});
  const database = input("connection-database", sql.database, {required: "", placeholder: "Database name", autocomplete: "off"});
  const username = input("connection-username", sql.username, {required: "", autocomplete: "off"});
  const password = input("connection-password", "", {type: "password", autocomplete: "new-password", placeholder: source ? "Leave blank to keep saved password" : "Database password"});
  const ssl = node("select", {id: "connection-ssl"});
  for (const [value, text] of [["prefer", "Prefer TLS"], ["require", "Require TLS"], ["verify-ca", "Verify certificate"], ["verify-full", "Verify certificate & hostname"], ["disable", "Local connection (no TLS)"]]) ssl.append(node("option", {value}, text));
  ssl.value = sql.sslmode || "prefer";
  const uri = input("connection-neo4j-uri", neo.uri, {required: "", placeholder: "bolt://localhost:7687", autocomplete: "off"});
  const neoDatabase = input("connection-neo4j-database", neo.database || "neo4j", {required: ""});
  const neoUsername = input("connection-neo4j-username", neo.username || "neo4j", {required: "", autocomplete: "off"});
  const neoPassword = input("connection-neo4j-password", "", {type: "password", autocomplete: "new-password", placeholder: source ? "Leave blank to keep saved password" : "Neo4j password"});
  if (!source) neoPassword.required = true;
  const sqlEnabled = node("input", {id: "connection-use-sql", type: "checkbox"});
  sqlEnabled.checked = Boolean(source?.sql_type);
  const sqlToggle = node("label", {class: "check"}); sqlToggle.append(sqlEnabled, node("span", {}, "Add PostgreSQL for table enrichment and synchronization"));
  const sqlFields = node("fieldset"), sqlGrid = node("div", {class: "connection-fields"});
  sqlFields.append(node("legend", {}, "PostgreSQL · optional"), node("p", {}, "Your source records and attributes."));
  sqlGrid.append(label("Host", host), label("Port", port), label("Database", database), label("Username", username), label("Password", password), label("Transport", ssl)); sqlFields.append(sqlGrid);
  const neoFields = node("fieldset"), neoGrid = node("div", {class: "connection-fields"});
  neoFields.append(node("legend", {}, "Neo4j"), node("p", {}, "Your graph, ready to query with Cypher."));
  const uriLabel = label("Server URI", uri); uriLabel.className = "connection-full-field";
  neoGrid.append(uriLabel, label("Database", neoDatabase), label("Username", neoUsername), label("Password", neoPassword)); neoFields.append(neoGrid);
  const pair = node("div", {class: "connection-pair"}); pair.append(neoFields, sqlFields);
  const mappingBox = node("details", {class: "connection-mappings"});
  mappingBox.append(node("summary", {}, "Table mappings · optional"), node("p", {class: "source-hint"}, "Choose source tables, their unique keys, and the attributes to expose. Benchmark datasets use their imported catalog mappings."));
  const mappingsEditor = window.GraphMineTableMappings({node, W, container: mappingBox, source});
  const save = node("button", {id: "save-connection-settings", type: "submit", class: "primary"}, "Connect & save");
  const back = node("button", {id: "cancel-connection-settings", type: "button", class: "secondary"}, "Cancel");
  const status = node("p", {id: "connection-form-status", role: "status", class: "source-status"});
  const actions = node("div", {class: "source-query-actions"}); actions.append(status, back, save);
  const remove = node("button", {type: "button", class: "quiet", id: "delete-connection", hidden: !source?.managed}, "Remove connection");
  let confirmRemoval = false;
  remove.onclick = async () => {
    if (!confirmRemoval) {
      confirmRemoval = true; remove.textContent = "Confirm removal";
      status.textContent = "Remove the saved connection and credentials? Existing graph snapshots will remain available.";
      return;
    }
    remove.disabled = save.disabled = back.disabled = true;
    try {
      await api(`/api/database-sources/${encodeURIComponent(source.id)}`, {method: "DELETE"});
      clearSecrets(); if (form.isConnected) await onSaved(null);
    } catch (error) { status.textContent = error.message; status.classList.add("source-error"); }
    finally { remove.disabled = save.disabled = back.disabled = false; }
  };
  actions.prepend(remove);
  const sqlChanged = () => {
    sqlFields.hidden = sqlFields.disabled = mappingBox.hidden = !sqlEnabled.checked;
    pair.classList.toggle("connection-single", !sqlEnabled.checked);
    password.required = sqlEnabled.checked && !source?.sql_type;
  };
  sqlEnabled.onchange = sqlChanged; sqlChanged();
  form.append(node("h3", {}, source ? "Edit Neo4j connection" : "Connect Neo4j"), node("p", {class: "source-hint"}, "Query and analyze your Neo4j graph directly. Add SQL when you need mapped source records. Changing the connection leaves saved graph snapshots intact."), label("Connection name", name), sqlToggle, pair, mappingBox, actions);
  container.replaceChildren(form);
  const clearSecrets = () => { password.value = neoPassword.value = ""; };
  back.onclick = () => { clearSecrets(); onCancel(); };
  form.onsubmit = async event => {
    event.preventDefault(); if (save.disabled) return;
    save.disabled = true; back.disabled = true; status.classList.remove("source-error"); status.textContent = sqlEnabled.checked ? "Connecting to PostgreSQL and Neo4j…" : "Connecting to Neo4j…";
    try {
      const mappings = sqlEnabled.checked ? mappingsEditor.read() : {};
      const body = {name: name.value.trim(), sql_enabled: sqlEnabled.checked,
        ...(sqlEnabled.checked ? {host: host.value.trim(), port: Number(port.value), database: database.value.trim(), username: username.value.trim(), sslmode: ssl.value} : {}),
        neo4j_uri: uri.value.trim(), neo4j_database: neoDatabase.value.trim(), neo4j_username: neoUsername.value.trim(),
        entities: mappings.entities || [], relationships: mappings.relationships || [],
        ...(sqlEnabled.checked && password.value ? {password: password.value} : {}), ...(neoPassword.value ? {neo4j_password: neoPassword.value} : {})};
      const result = await api(source ? `/api/database-sources/${encodeURIComponent(source.id)}` : "/api/database-sources", {method: source ? "PUT" : "POST", body: W.stringify(body)});
      clearSecrets(); if (form.isConnected) await onSaved(result);
    } catch (error) {
      status.textContent = error.message; status.classList.add("source-error");
      if (/entities|relationships|mapping|column|key/i.test(error.message)) { mappingBox.open = true; mappingsEditor.showError(error.message); }
      const key = error.message.split(":")[0], fields = {name, host, port, database, username, neo4j_uri: uri, neo4j_database: neoDatabase, neo4j_username: neoUsername};
      if (fields[key]) { fields[key].setAttribute("aria-invalid", "true"); fields[key].focus(); }
    }
    finally { save.disabled = false; back.disabled = false; }
  };
  name.focus();
};
