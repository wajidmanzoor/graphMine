"use strict";
window.GraphMineQueryTable = ({api, W, node, container}) => {
  const section = node("section", {class: "query-table-view", hidden: true, "aria-label": "Complete query table"});
  const status = node("p", {class: "query-table-status source-hint", role: "status"});
  const toolbar = node("div", {class: "query-table-toolbar"});
  const sort = node("select", {"aria-label": "Sort complete query table by"}), order = node("select", {"aria-label": "Table sort direction"});
  order.append(node("option", {value: "asc"}, "Ascending"), node("option", {value: "desc"}, "Descending"));
  const button = (text, action) => node("button", {type: "button", class: "quiet", "data-table-action": action}, text);
  const csv = button("Download all rows (CSV)", "csv"), json = button("Download exact JSON", "json");
  toolbar.append(sort, order, csv, json);
  const frame = node("div", {class: "query-table-scroll", tabindex: "0", "aria-label": "Scrollable query table"});
  const table = node("table"), caption = node("caption"), head = node("thead"), body = node("tbody");
  table.append(caption, head, body); frame.append(table);
  const pages = node("div", {class: "query-table-pages"});
  const previous = button("Previous rows", "previous"), next = button("Next rows", "next"), retry = button("Retry table", "retry"); retry.hidden = true;
  const range = node("span", {class: "source-hint", "aria-live": "polite"});
  pages.append(previous, range, next, retry);
  const note = node("p", {class: "source-hint"}, "CSV protects spreadsheet text and includes every row in the current sort order. JSON preserves exact values, types and original row order.");
  section.append(status, toolbar, frame, pages, note); container.append(section);
  let snapshot = null, generation = 0, controller = null, offset = 0, page = null, busy = false;
  const limit = 50;
  const text = value => value === null ? "null" : value === "" ? '""' : typeof value === "object" ? W.stringify(value) : String(value);
  function controls() {
    previous.disabled = busy || offset === 0; next.disabled = busy || !page?.has_more;
    sort.disabled = order.disabled = csv.disabled = json.disabled = busy || !snapshot;
  }
  function parameters(paging = true) {
    const params = new URLSearchParams(paging ? {offset: String(offset), limit: String(limit)} : {});
    if (sort.value) { params.set("sort", sort.value); params.set("direction", order.value); }
    return params;
  }
  function render() {
    const row = node("tr");
    for (const column of page.columns) row.append(node("th", {scope: "col", title: `${column.type}${column.nullable ? ", nullable" : ""}`}, column.name));
    head.replaceChildren(row); body.replaceChildren();
    for (const record of page.rows) {
      const tr = node("tr");
      for (const column of page.columns) {
        const value = record[column.name];
        tr.append(node("td", {class: value === null ? "query-cell-null" : ""}, text(value)));
      }
      body.append(tr);
    }
    caption.textContent = `${snapshot.name || "Query results"} · ${page.row_count.toLocaleString()} rows`;
    const selected = sort.value;
    sort.replaceChildren(node("option", {value: ""}, "Original query order"), ...page.columns.map(column => node("option", {value: column.name}, column.name)));
    sort.value = selected;
    range.textContent = page.row_count ? `Rows ${(offset + 1).toLocaleString()}–${(offset + page.rows.length).toLocaleString()} of ${page.row_count.toLocaleString()}` : "0 rows";
    status.textContent = page.complete ? "Complete query result. Sorting covers all returned rows." : "The source marked this table incomplete.";
    frame.scrollTop = 0;
  }
  async function load() {
    if (!snapshot) return;
    controller?.abort(); controller = new AbortController();
    const current = ++generation, id = snapshot.id;
    busy = true; controls(); status.textContent = "Loading table rows…"; retry.hidden = true;
    try {
      const result = await api(`/api/database-query-snapshots/${encodeURIComponent(id)}/table?${parameters()}`, {signal: controller.signal});
      if (current !== generation || !section.isConnected) return;
      page = result; render();
    } catch (error) {
      if (current !== generation || error.name === "AbortError") return;
      page = null; head.replaceChildren(); body.replaceChildren(); range.textContent = "";
      status.textContent = error.message; retry.hidden = false;
    } finally { if (current === generation) { busy = false; controls(); } }
  }
  previous.onclick = () => { offset = Math.max(0, offset - limit); load(); };
  next.onclick = () => { offset += limit; load(); };
  sort.onchange = order.onchange = () => { offset = 0; load(); };
  retry.onclick = load;
  async function download(format) {
    if (!snapshot || busy) return;
    const current = generation;
    busy = true; controls(); status.textContent = "Preparing all table rows for download…";
    try {
      const blob = await api(`/api/database-query-snapshots/${encodeURIComponent(snapshot.id)}/table/${format}${format === "csv" ? `?${parameters(false)}` : ""}`, {asBlob: true, signal: controller?.signal});
      if (current !== generation || !section.isConnected) return;
      const href = URL.createObjectURL(blob), anchor = node("a", {href, download: `${(snapshot.name || "query-table").replace(/[^A-Za-z0-9_-]/g, "_")}.${format}`});
      document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(href), 30_000);
      status.textContent = "Complete table downloaded.";
    } catch (error) { if (current === generation && error.name !== "AbortError") status.textContent = error.message; }
    finally { if (current === generation) { busy = false; controls(); } }
  }
  csv.onclick = () => download("csv"); json.onclick = () => download("json");
  return {
    setSnapshot(value) {
      generation++; controller?.abort(); snapshot = value; page = null; offset = 0; busy = false;
      section.hidden = !value; head.replaceChildren(); body.replaceChildren(); sort.replaceChildren(); range.textContent = "";
      order.value = "asc"; controls(); if (value) load();
    },
    destroy() { generation++; controller?.abort(); section.remove(); },
  };
};
