"use strict";
window.GraphMineBenchmarkDatasets = ({api, node, container, dataset}) => {
  let generation = 0, blobUrl = null, currentSchema = null;
  const schemas = (dataset?.schemas || []).filter(schema => schema.platform === "neo4j");
  const clean = () => { if (blobUrl) URL.revokeObjectURL(blobUrl); blobUrl = null; };
  container.replaceChildren();
  if (dataset?.workload_url) {
    container.append(node("a", {href: dataset.workload_url, target: "_blank", rel: "noopener noreferrer", class: "benchmark-attribution"}, "Published Neo4j workload ↗"));
  }
  const search = node("input", {id: "database-schema-search", type: "search", placeholder: "Search tables, labels and columns", "aria-label": "Search dataset schema"});
  const tableList = node("div", {class: "dataset-schema-tables"});
  const tableStatus = node("p", {class: "source-hint", role: "status"});
  const schemaTables = dataset?.tables || [];
  function renderTables() {
    tableList.replaceChildren();
    const needle = search.value.trim().toLocaleLowerCase();
    let matches = 0;
    for (const table of schemaTables) {
      if (needle && !JSON.stringify(table).toLocaleLowerCase().includes(needle)) continue;
      matches++;
      const details = node("details", {class: "dataset-schema-table"}); details.open = Boolean(needle);
      const graphType = table.relationship_type || table.labels?.join(", ") || "SQL table";
      details.append(node("summary", {}, `${graphType} · ${table.name}${table.rows != null ? ` · ${table.rows.toLocaleString()} rows` : ""}`));
      if (table.key) details.append(node("p", {class: "source-hint"}, `Source key: ${table.key}`));
      const list = node("dl");
      for (const column of table.columns || []) {
        list.append(node("dt", {}, column.name), node("dd", {}, column.type || "Mapped attribute"));
      }
      details.append(list); tableList.append(details);
    }
    tableStatus.textContent = schemaTables.length ? `${matches} of ${schemaTables.length} imported tables. Column types are from SQL.` : "Use Cypher to explore the graph in this connection.";
  }
  search.oninput = renderTables;
  search.hidden = !schemaTables.length;
  container.append(search, tableStatus, tableList); renderTables();
  const sourceNotes = () => {
    if (!dataset?.source_notes?.length) return;
    const details = node("details", {class: "source-hint"}), list = node("ul");
    details.append(node("summary", {}, "Source data notes"));
    for (const note of dataset.source_notes) list.append(node("li", {}, note.note));
    details.append(list); container.append(details);
  };
  if (!schemas.length) {
    sourceNotes();
    return {destroy() {}};
  }
  const diagrams = node("select", {id: "benchmark-schema-diagram", "aria-label": "Neo4j schema diagram", hidden: schemas.length === 1});
  diagrams.append(...schemas.map((s, i) => node("option", {value: i}, `Diagram ${i + 1}`)));
  const image = node("img", {id: "benchmark-schema-image", hidden: true});
  const imageBox = node("div", {class: "benchmark-schema-view", tabindex: "0", role: "region", "aria-label": "Dataset schema diagram"}); imageBox.append(image);
  const download = node("button", {type: "button", class: "quiet", id: "download-benchmark-schema"}, "Download schema");
  const definitions = node("button", {type: "button", class: "quiet", id: "download-benchmark-definitions"}, "Neo4j loading commands & queries");
  const zoom = node("button", {type: "button", class: "quiet", id: "zoom-benchmark-schema", "aria-pressed": "false"}, "View full size");
  const attribution = node("a", {target: "_blank", rel: "noopener noreferrer", class: "benchmark-attribution"}, "PropGBench ↗");
  const toolbar = node("div", {class: "benchmark-toolbar"}); toolbar.append(node("span", {class: "source-badge"}, "Neo4j"), diagrams, download, zoom, attribution);
  const status = node("p", {class: "source-hint", role: "status"});
  container.append(toolbar, imageBox, definitions, status); sourceNotes();
  async function showSchema() {
    const selected = schemas[Number(diagrams.value)], current = ++generation;
    currentSchema = selected; clean(); image.hidden = true; image.removeAttribute("src");
    download.disabled = definitions.disabled = zoom.disabled = true;
    imageBox.classList.remove("schema-full-size"); zoom.textContent = "View full size"; zoom.setAttribute("aria-pressed", "false");
    attribution.href = selected.page || dataset.source_url; status.textContent = "Loading schema…";
    try {
      const blob = await api(selected.image_url, {asBlob: true});
      if (current !== generation || !container.isConnected) return;
      blobUrl = URL.createObjectURL(blob); image.src = blobUrl;
      image.alt = `${dataset.name} — Neo4j schema, from PropGBench`;
      image.hidden = false; download.disabled = zoom.disabled = false; definitions.disabled = !selected.definition_url;
      status.textContent = "The diagram shows the publisher’s graph structure.";
    } catch (error) { if (current === generation && container.isConnected) status.textContent = error.message; }
  }
  diagrams.onchange = showSchema;
  zoom.onclick = () => { const full = imageBox.classList.toggle("schema-full-size"); zoom.textContent = full ? "Fit to view" : "View full size"; zoom.setAttribute("aria-pressed", String(full)); };
  download.onclick = () => { if (blobUrl && currentSchema) node("a", {href: blobUrl, download: `${dataset.id}-${currentSchema.file}`}).click(); };
  definitions.onclick = async () => {
    if (!currentSchema?.definition_url) return;
    const selected = currentSchema; definitions.disabled = true;
    try {
      const blob = await api(selected.definition_url, {asBlob: true});
      const url = URL.createObjectURL(blob); node("a", {href: url, download: `${dataset.id}-${selected.platform}-loading-and-queries.txt`}).click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { status.textContent = error.message; }
    finally { if (currentSchema === selected) definitions.disabled = false; }
  };
  showSchema();
  return {destroy() { generation++; clean(); }};
};
