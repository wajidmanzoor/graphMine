"use strict";
window.GraphMineVisualization = ({state, api, W, node, notice, renderGraph, renderTable, applySelection, selectRow, getExploration, getResultViews, askSelection, enumerateResult}) => {
  const debug = new URLSearchParams(location.search).get("debug") === "1";
  const $ = id => document.getElementById(id), S = window.GraphMineViewStyle, graphCard = $("network").closest(".graph-card");
  const toolbar = node("div", {class: "view-toolbar", id: "view-toolbar"}), primary = node("select", {id: "view-as", "aria-label": "View as"});
  const search = node("input", {id: "view-search", type: "search", placeholder: "Find an entity…", "aria-label": "Find an entity in this view"});
  const summary = node("span", {id: "view-selection-count", role: "status", "aria-live": "polite"});
  const scope = node("p", {id: "view-sampling", class: "view-scope", role: "status"});
  const primaryHost = node("div", {id: "view-primary"}), linkedHost = node("div", {id: "view-linked-charts"});
  const legend = node("details", {id: "view-legend", class: "view-legend"}), legendRows = node("div", {class: "view-legend-list"});
  const legendTitle = node("summary", {}, "Legend & style"); legend.append(legendTitle, legendRows); legend.open = matchMedia("(min-width: 901px)").matches;
  const accessible = node("details", {class: "view-accessible"}), accessibleList = node("ul"); accessible.append(node("summary", {}, "Explore entities with the keyboard"), accessibleList);
  const recordContextHost = $("result-context");
  const tooltip = node("div", {class: "view-tooltip", hidden: true, role: "dialog", "aria-label": "Entity details"}); document.body.append(tooltip);
  const minimap = node("canvas", {class: "view-minimap", width: 300, height: 200, tabindex: 0, role: "button", "aria-label": "Graph overview. Click to center; press Enter to fit.", hidden: true});
  const chips = node("div", {class: "view-filter-chips", "aria-label": "Active display filters"});
  const empty = node("div", {id: "view-empty", class: "view-empty", hidden: true, role: "status"});
  const selectionChip = node("div", {id: "view-selection-chip", class: "view-selection-chip", hidden: true});
  toolbar.append(primary, search);
  const oldTools = graphCard.querySelector(".graph-tools"); if (oldTools) { toolbar.append(...oldTools.children); oldTools.remove(); }
  if ($("result-focus")) toolbar.append($("result-focus"));
  graphCard.prepend(toolbar); $("network").before(scope, selectionChip, chips, primaryHost, empty); graphCard.append(legend, minimap, accessible);
  const placeLegend = () => { const top = `${$("network").offsetTop + 10}px`; if (legend.style.top !== top) legend.style.top = top; };
  const toolbarSize = new ResizeObserver(() => { placeLegend(); state.cy?.resize(); }); toolbarSize.observe(toolbar); toolbarSize.observe(scope); toolbarSize.observe(selectionChip); toolbarSize.observe(chips); requestAnimationFrame(placeLegend);
  $("network").addEventListener("mousedown", () => state.cy?.resize(), true);
  $("chart").append(linkedHost);
  let viewKey = null, contextKey = null, generation = 0, primaryGeneration = 0, activeCy = null, frame = null, hoverTimer = null, comparison = null, aggregateCy = null, playback = null, focusKeys = null, geometry = null, layoutWorker = null;
  const labels = new Map(), label = id => labels.get(W.idKey(id)) || state.graph?.vertices?.find(v => W.idKey(v.id) === W.idKey(id))?.label || W.idLabel(id);
  const requestedLabels = new Set(); let requestingLabels = false;
  const overrides = () => state.visualOverrides || (state.visualOverrides = {style_rules: [], property_filters: [], hidden_vertices: [], hidden_categories: [], search: ""});
  const spec = () => state.resolvedViewSpec || state.resultView?.view_spec;
  const changed = () => getExploration()?.changed();
  const button = (id, text, action, parent = toolbar) => { const b = node("button", {id, type: "button", class: "quiet"}, text); b.onclick = () => Promise.resolve().then(action).then(() => { notice.clearError?.(); if (parent.classList.contains("view-menu")) parent.closest("details").open = false; }).catch(error => notice(error.message, true)); parent.append(b); return b; };
  const charts = window.GraphMineViewCharts({W, node, label, select: item => {
    state.selectedItems = new Set(item.indices || (Number.isInteger(item.index) ? [item.index] : []));
    if (item.open) { overrides().primary = "graph"; primary.value = "graph"; }
    if (Number.isInteger(item.index) && state.resultView?.item_count) { void getResultViews()?.select(item.index); return; }
    let ids = item.ids || [];
    if (item.group !== undefined) ids = (state.graph?.vertices || []).filter(v => (v.view?.groups || []).some(g => W.stringify(g) === W.stringify(item.group))).map(v => v.id);
    state.selected = new Set(ids.map(W.idKey)); state.selectedEdges = new Set((item.edges || []).map(W.idKey)); applySelection();
  }});
  const endpoint = () => `/api/workflows/${[state.record.id, "steps", $("result-step").value, "ports", $("result-port").value, "view"].map(encodeURIComponent).join("/")}`;
  const alternatives = window.GraphMineViewAlternates({W, node, charts, label, overrides, changed, context: () => api(endpoint() + "?" + new URLSearchParams({context: true, expected_revision: state.record.revision})), select: ids => { state.selected = new Set(ids.map(W.idKey)); applySelection(); }});
  async function action(name, data = {}) {
    const version = generation, response = await api(endpoint() + "/" + name, {method: "POST", body: W.stringify({expected_revision: state.record.revision, index: state.resultView?.index ?? null, ...data})});
    if (version !== generation) throw new Error("The displayed result changed before this action finished.");
    return response;
  }
  async function loadLabels(rows) {
    if (!state.resultView || requestingLabels || ["cross_graph_mapping", "relation_embeddings", "graph_predictions"].includes(state.port?.type)) return;
    const ids = [];
    for (const row of rows.slice(0, 100)) for (const id of (row && typeof row === "object" ? [row.vertex, row.entity, row.source, row.target, row[state.port?.vertex_field], ...(row.vertices || []).slice(0, 100)] : state.port?.type === "vertex_set" ? [row] : [])) {
      if (["number", "string", "bigint"].includes(typeof id) && !labels.has(W.idKey(id)) && !requestedLabels.has(W.idKey(id)) && ids.length < 1000) { requestedLabels.add(W.idKey(id)); ids.push(id); }
    }
    if (!ids.length) return;
    requestingLabels = true;
    try { const data = await action("labels", {vertices: ids}); for (const row of data.labels) labels.set(W.idKey(row.id), row.label); if (data.labels.length) renderTable(); }
    catch (error) { notice("Some entity names could not be resolved: " + error.message, true); }
    finally { requestingLabels = false; }
  }
  function selectedIds() { return [...state.selection.entities].map(key => key.startsWith("s:") ? key.slice(2) : W.parse(key.slice(2))); }
  const friendly = field => state.resultView?.property_fields?.find(p => p.field === field)?.label || ({degree: "Connections in input", vertex_type: "Entity type", side: "Bipartite side", group: "Group"}[field]) || field.replace(/^attributes\./, "").replaceAll("_", " ").replace(/^./, c => c.toUpperCase());
  const filterText = f => `${friendly(f.field)} ${{eq: "=", gte: "≥", lte: "≤", contains: "contains", exists: "has a value"}[f.operator]} ${f.operator === "exists" ? "" : f.value ?? ""}`.trim();
  function updateCounts() {
    const cy = state.cy; if (!cy || !state.resultView) return;
    const visible = cy.nodes().filter(n => !n.hasClass("view-hidden")), edges = cy.edges().filter(e => !e.hasClass("view-hidden"));
    const added = state.resultView.expanded_count || 0;
    $("preview-scope").textContent = `${visible.length} vertices · ${edges.length} connections${added ? ` (${added} added by expanding)` : ""}`;
    summary.textContent = `${visible.length} visible`;
    empty.hidden = visible.length > 0 || !state.resultView.graph_available || $("network").hidden;
    if (!empty.hidden) {
      empty.replaceChildren(node("span", {}, `No entities match ${(overrides().property_filters || []).map(filterText).join(" · ") || "the active filters"} · `));
      button("view-clear-filter", "Clear filter", () => { overrides().property_filters = []; overrides().hidden_vertices = []; overrides().hidden_categories = []; applyFilters(true); changed(); }, empty);
    }
  }
  function resetDefault(initial) {
    state.ignoreSavedView = true; state.visualOverrides = {style_rules: [], property_filters: [], hidden_vertices: [], hidden_categories: [], search: ""};
    state.viewContext = {vertices: [], edges: []}; state.selected.clear(); state.selectedEdges.clear();
    state.cy?.nodes().unlock(); focusKeys = null; contextKey = null;
    if (initial?.layout) $("graph-layout").value = initial.layout;
  }
  function dialog(title, build) {
    const d = node("dialog"), form = node("form"), header = node("div", {class: "section-heading"}), close = node("button", {type: "button", class: "quiet"}, "Close");
    header.append(node("h2", {}, title), close); form.append(header); d.append(form); document.body.append(d); close.onclick = () => d.close();
    d.addEventListener("close", () => d.remove()); build(form, () => d.close()); d.showModal(); return d;
  }
  const fieldsFor = target => (state.resultView?.property_fields || []).filter(p => p.target === target);
  const fieldNames = target => fieldsFor(target).map(p => [p.field, p.label]);
  function propertyOptions(select, target) {
    select.replaceChildren();
    for (const group of ["Result fields", "Entity properties"]) {
      const section = node("optgroup", {label: group});
      for (const field of fieldsFor(target).filter(p => p.group === group)) section.append(node("option", {value: field.field}, field.label));
      if (section.children.length) select.append(section);
    }
  }
  function propertyHistogram(host, target, field) {
    host.replaceChildren(); const meta = fieldsFor(target).find(p => p.field === field);
    if (meta?.kind !== "numeric") return;
    host.append(node("p", {}, `Range: ${meta.minimum}–${meta.maximum}`));
    charts.histogram(host, meta.label, (target === "edge" ? state.graph.edges : state.graph.vertices).map(r => ({ids: [], value: S.field(r, field)})));
  }
  function selectInput(form, text, values) { const l = node("label", {}, text), input = node("select", {"aria-label": text}); for (const value of values) { const [v, caption] = Array.isArray(value) ? value : [value, value.replaceAll("_", " ")]; input.append(node("option", {value: v}, caption)); } l.append(input); form.append(l); return input; }
  function textInput(form, text, type = "text") { const l = node("label", {}, text), input = node("input", {type}); l.append(input); form.append(l); return input; }
  function styleEditor() {
    dialog("Style by a property", (form, close) => {
      const target = selectInput(form, "Entities", [["node", "Nodes"], ["edge", "Edges"]]);
      const channel = selectInput(form, "Visual channel", ["color", "size", "label", "shape"]);
      const property = selectInput(form, "Property", []), mode = selectInput(form, "Rule", []);
      const equals = textInput(form, "Matches value"), color = textInput(form, "Condition color", "color"), preview = node("div");
      color.value = S.palette()[0]; form.append(preview);
      const condition = () => { equals.parentElement.hidden = mode.value !== "single"; color.parentElement.hidden = mode.value !== "single" || channel.value !== "color"; };
      const refresh = () => {
        const meta = fieldsFor(target.value).find(p => p.field === property.value);
        const allowed = meta?.kind === "numeric" && ["color", "size", "width"].includes(channel.value) ? [["range", "Numeric range"], ["single", "Single condition"]] : [...(meta?.unique_allowed ? [["unique", "Unique values"]] : []), ["single", "Single condition"]];
        mode.replaceChildren(...allowed.map(([value, text]) => node("option", {value}, text))); condition();
        propertyHistogram(preview, target.value, property.value);
      };
      target.onchange = () => { propertyOptions(property, target.value); channel.replaceChildren(...(target.value === "edge" ? ["color", "width"] : ["color", "size", "label", "shape"]).map(value => node("option", {value}, friendly(value)))); refresh(); };
      mode.onchange = condition; property.onchange = channel.onchange = refresh; target.onchange();
      button("apply-view-style", "Apply style", () => {
        let match = equals.value; try { match = W.parse(match); } catch { /* Literal text. */ }
        const rule = {target: target.value, channel: channel.value, field: property.value, mode: mode.value, scale: mode.value === "range" ? "sequential" : "categorical", equals: match, color: color.value};
        overrides().style_rules = [...(overrides().style_rules || []).filter(r => r.target !== rule.target || r.channel !== rule.channel), rule]; restyle(); changed(); close();
      }, form);
    });
  }
  function propertyFilter() {
    dialog("Filter the displayed graph", (form, close) => {
      const target = selectInput(form, "Entities", [["node", "Nodes"], ["edge", "Edges"]]), property = selectInput(form, "Property", []);
      const operator = selectInput(form, "Condition", [["eq", "Equals"], ["contains", "Contains text"], ["gte", "At least"], ["lte", "At most"], ["exists", "Has a value"]]), value = textInput(form, "Value"), preview = node("div");
      form.append(preview); property.onchange = () => { const numeric = fieldsFor(target.value).find(p => p.field === property.value)?.kind === "numeric"; value.type = numeric ? "number" : "text"; value.step = "any"; operator.value = numeric ? "gte" : "eq"; propertyHistogram(preview, target.value, property.value); };
      target.onchange = () => { propertyOptions(property, target.value); property.onchange(); }; target.onchange();
      button("add-view-filter", "Add filter", () => { let v = value.value; if (["gte", "lte"].includes(operator.value)) { v = Number(v); if (!value.value.trim() || !Number.isFinite(v)) throw new Error("Enter a numeric value."); } overrides().property_filters.push({target: target.value, field: property.value, operator: operator.value, value: v}); applyFilters(true); changed(); close(); }, form);
    });
  }
  function slicer() {
    dialog("Slide through a numeric or date property", (form, close) => {
      const target = selectInput(form, "Entities", [["node", "Nodes"], ["edge", "Edges"]]), property = selectInput(form, "Property", fieldNames("node")), plot = node("div");
      const range = textInput(form, "Maximum value", "range"), text = node("p", {role: "status"}); let values = [];
      const read = r => { const v = S.field(r, property.value); return typeof v === "number" ? v : typeof v === "string" ? Date.parse(v) : NaN; };
      const refresh = () => { const rows = target.value === "node" ? state.graph.vertices : state.graph.edges; values = [...new Set(rows.map(read).filter(Number.isFinite))].sort((a, b) => a - b); range.min = "0"; range.max = String(Math.max(0, values.length - 1)); range.step = "1"; range.value = range.max; range.disabled = !values.length; plot.replaceChildren(); charts.histogram(plot, "Loaded distribution", rows.map((r, index) => ({index, ids: [], value: read(r)}))); text.textContent = values.length ? `${values.length} distinct values` : "No numeric or date values are available."; };
      target.onchange = () => { property.replaceChildren(...fieldNames(target.value).map(k => node("option", {value: k}, k))); refresh(); }; property.onchange = refresh;
      range.oninput = () => { const value = values[Number(range.value)]; text.textContent = `Showing values up to ${value}`; overrides().property_filters = overrides().property_filters.filter(r => !(r.field === property.value && r.target === target.value && r.operator === "lte")); overrides().property_filters.push({target: target.value, field: property.value, operator: "lte", value}); applyFilters(); changed(); };
      form.append(plot, text); const play = button("play-view-slicer", "Play", () => { if (playback) { clearInterval(playback); playback = null; play.textContent = "Play"; return; } range.value = "0"; play.textContent = "Stop"; playback = setInterval(() => { range.oninput(); if (Number(range.value) >= Number(range.max)) { clearInterval(playback); playback = null; play.textContent = "Play"; } else range.value = String(Number(range.value) + 1); }, 500); }, form);
      form.closest("dialog").addEventListener("close", () => { clearInterval(playback); playback = null; }); refresh();
    });
  }
  function passes(record, filter) {
    const value = S.field(record, filter.field); if (filter.operator === "exists") return value !== null && value !== undefined;
    if (filter.operator === "contains") return String(value ?? "").toLocaleLowerCase().includes(String(filter.value).toLocaleLowerCase());
    if (filter.operator === "eq") return String(value) === String(filter.value);
    const number = typeof value === "number" ? value : typeof value === "string" ? Date.parse(value) : NaN;
    return Number.isFinite(number) && (filter.operator === "gte" ? number >= filter.value : number <= filter.value);
  }
  function applyFilters(refit = false) {
    const cy = state.cy; if (!cy) return;
    const hidden = new Set((overrides().hidden_vertices || []).map(W.idKey)), categories = new Set(overrides().hidden_categories || []), filters = overrides().property_filters || [];
    cy.batch(() => {
      cy.nodes().forEach(n => n.toggleClass("view-hidden", hidden.has(n.id()) || categories.has(n.data("category")) || !filters.filter(r => r.target === "node").every(r => passes(n.data("original"), r))));
      cy.edges().forEach(e => e.toggleClass("view-hidden", e.source().hasClass("view-hidden") || e.target().hasClass("view-hidden") || !filters.filter(r => r.target === "edge").every(r => passes(e.data("original"), r))));
    });
    chips.replaceChildren(); filters.forEach((f, i) => button(`view-filter-${i}`, `${filterText(f)} ×`, () => { overrides().property_filters.splice(i, 1); applyFilters(true); changed(); }, chips));
    if (hidden.size || categories.size) button("restore-hidden-entities", "Show hidden entities", () => { overrides().hidden_vertices = []; overrides().hidden_categories = []; applyFilters(true); renderLegend(); changed(); }, chips);
    cy.style().update(); if (refit) S.fitAndClamp(cy); updateCounts(); drawMinimap();
    const allowed = new Set(cy.nodes(":visible").map(n => n.id()));
    document.querySelectorAll("[data-view-entities]").forEach(el => { const ids = W.parse(el.dataset.viewEntities); el.classList.toggle("view-filtered", ids.length > 0 && !ids.some(id => allowed.has(W.idKey(id)))); });
  }
  function renderLegend() {
    legendRows.replaceChildren(); const data = state.viewStyleData; if (!data) return;
    legendRows.append(node("p", {}, `Color: ${friendly(data.colorField || "vertex_type")}`));
    if (data.colorRamp) { legendRows.firstChild.textContent = `Color: ${data.colorRamp.field} · ${data.colorRamp.domain[0]} to ${data.colorRamp.domain[1]}`; legendRows.append(node("p", {class: "muted"}, data.colorRamp.domain[0] < 0 ? "Orange: negative · pale: zero · blue: positive" : "Pale to dark blue: smaller to larger values")); legendRows.append(node("p", {}, `Filter by ${data.colorField || "entity type"}`)); }
    for (const item of data.legend) {
      const key = W.stringify(item.value), hidden = overrides().hidden_categories?.includes(key), b = node("button", {type: "button", "aria-pressed": String(!hidden)}), swatch = node("span", {class: "view-swatch", "aria-hidden": true}); swatch.style.setProperty("--swatch", item.color);
      if (!data.colorRamp) b.append(swatch); b.append(node("span", {}, `${item.label || item.value} (${item.count})`)); b.onclick = event => { const current = new Set(overrides().hidden_categories || []); if (event.shiftKey) { if (current.has(key)) current.delete(key); else current.add(key); } else { const allOthersHidden = data.legend.every(v => W.stringify(v.value) === key || current.has(W.stringify(v.value))); current.clear(); if (!allOthersHidden) data.legend.forEach(v => { if (W.stringify(v.value) !== key) current.add(W.stringify(v.value)); }); } overrides().hidden_categories = [...current]; applyFilters(true); renderLegend(); changed(); }; legendRows.append(b);
    }
    if (data.legend.length > 8) legendRows.append(node("p", {class: "muted"}, "Smaller categories share gray but remain separate groups."));
    if (data.sizeField) legendRows.append(node("p", {}, `Size: ${friendly(data.sizeField)}`));
    for (const item of data.shapeLegend || []) legendRows.append(node("p", {}, `Shape: ${item.value} · ${item.shape}`));
    for (const item of data.edgeLegend?.length > 1 ? data.edgeLegend : []) { const line = node("span", {class: "view-swatch"}); line.style.setProperty("--swatch", item.color); const row = node("p", {}, `Edge type: ${item.value} (${item.count})`); row.prepend(line); legendRows.append(row); }
    button("view-style-by", "Style by…", styleEditor, legendRows);
  }
  function restyle() {
    if (!state.cy || !state.graph?.vertices) return;
    const data = S.renderData(W, state.graph, spec(), overrides()); state.viewStyleData = data;
    state.cy.batch(() => { for (const element of data.elements) state.cy.getElementById(element.data.id).data(element.data); state.cy.style(S.stylesheet(Boolean(state.graph.graph?.directed || state.flowRows))); });
    state.cy.removeScratch("viewSizes"); S.screenSizes(state.cy, state.selected); applySelection(); renderLegend(); applyFilters();
  }
  function tooltipFor(element, event = null) {
    clearTimeout(hoverTimer); tooltip.replaceChildren(); const record = element.data("original"), isNode = element.isNode();
    tooltip.append(node("strong", {}, isNode ? element.data("fullLabel") || element.data("label") : `${label(record.source)} → ${label(record.target)}`));
    const dl = node("dl");
    for (const meta of fieldsFor(isNode ? "node" : "edge").filter(p => p.group === "Result fields" || ["degree", "vertex_type"].includes(p.field)).slice(0, 10)) { const value = S.field(record, meta.field); if (value !== null && value !== undefined) dl.append(node("dt", {}, meta.label), node("dd", {}, String(value))); }
    tooltip.append(dl, node("code", {}, String(record.id))); button("copy-entity-id", "Copy ID", async () => { await navigator.clipboard.writeText(W.stringify(record.id)); }, tooltip); button("close-entity-details", "Close", () => { tooltip.hidden = true; }, tooltip);
    const bounds = $("network").getBoundingClientRect(), position = isNode ? element.renderedPosition() : {x: bounds.width / 2, y: bounds.height / 2};
    const x = event?.clientX ?? bounds.left + position.x, y = event?.clientY ?? bounds.top + position.y;
    tooltip.style.left = `${Math.min(innerWidth - 330, Math.max(8, x + 24))}px`; tooltip.style.top = `${Math.min(innerHeight - 280, Math.max(8, y + 20))}px`; tooltip.hidden = false;
  }
  function drawMinimap() {
    const cy = state.cy; minimap.hidden = !cy || cy.nodes().length < 150 || $("network").hidden; if (minimap.hidden) return;
    const context = minimap.getContext("2d"), box = cy.nodes().boundingBox({includeLabels: false}); context.clearRect(0, 0, 300, 200); const scale = Math.min(280 / Math.max(1, box.w), 180 / Math.max(1, box.h));
    cy.nodes(":visible").forEach(n => { const p = n.position(); context.fillStyle = n.data("color"); context.fillRect(10 + (p.x - box.x1) * scale, 10 + (p.y - box.y1) * scale, 3, 3); });
    const extent = cy.extent(); context.strokeStyle = S.palette()[0]; context.lineWidth = 2; context.strokeRect(10 + (extent.x1 - box.x1) * scale, 10 + (extent.y1 - box.y1) * scale, extent.w * scale, extent.h * scale);
    minimap.onclick = event => { const rect = minimap.getBoundingClientRect(), x = box.x1 + ((event.clientX - rect.left) * 300 / rect.width - 10) / scale, y = box.y1 + ((event.clientY - rect.top) * 200 / rect.height - 10) / scale; cy.pan({x: cy.width() / 2 - x * cy.zoom(), y: cy.height() / 2 - y * cy.zoom()}); };
    minimap.onpointerdown = event => { minimap.setPointerCapture(event.pointerId); minimap.dataset.dragging = "true"; minimap.onclick(event); };
    minimap.onpointermove = event => { if (minimap.dataset.dragging === "true") minimap.onclick(event); };
    minimap.onpointerup = minimap.onpointercancel = () => { minimap.dataset.dragging = "false"; };
  }
  minimap.onkeydown = event => { if (event.key === "Enter") S.fit(state.cy); if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) { event.preventDefault(); event.stopPropagation(); state.cy?.panBy({x: event.key === "ArrowLeft" ? 80 : event.key === "ArrowRight" ? -80 : 0, y: event.key === "ArrowUp" ? 80 : event.key === "ArrowDown" ? -80 : 0}); } };
  function selectionChanged() {
    const item = state.selection.item?.index;
    charts.selectionChanged(state.selected, new Set(Number.isInteger(item) ? [item] : []));
    if (state.cy) S.screenSizes(state.cy, state.selected);
    selectionChip.hidden = state.selected.size === 0;
    selectionChip.replaceChildren(node("span", {}, `${state.selected.size} selected · ${selectedIds().map(label).join(", ")}`));
    button("view-clear-selection", "Clear", () => { state.selected.clear(); state.selectedEdges.clear(); applySelection(); changed(); }, selectionChip);
    $("selection-detail").hidden = true;
    updateCounts();
  }
  let mapInstance = null;
  function showProjection(host, response) {
    state.displayProjection = response;
    host.replaceChildren(); charts.scatter(host, "PCA projection", response.points.map(p => ({...p, ids: p.entity === null ? [] : [p.entity], label: label(p.entity)})), ["Principal component 1", "Principal component 2"]);
    host.append(node("p", {class: "view-scope"}, response.note + ` Explained variance: ${response.explained_variance_ratio.map(v => (v * 100).toFixed(1) + "%").join(", ")}.`));
  }
  async function renderMap(host, view, request) {
    const version = generation; mapInstance?.remove(); mapInstance = null;
    const config = await api("/api/visualization/map-config"); if (version !== generation || request !== primaryGeneration) return;
    if (!config.enabled) { charts.renderPrimary(host, view, "coordinates"); host.append(node("p", {class: "view-scope"}, config.note)); return; }
    if (!window.L) {
      if (!document.getElementById("graph-map-css")) document.head.append(node("link", {id: "graph-map-css", rel: "stylesheet", href: "/vendor/leaflet.css"}));
      await new Promise((resolve, reject) => { const script = node("script", {src: "/vendor/leaflet.js"}); script.onload = resolve; script.onerror = () => { script.remove(); reject(new Error("The local map renderer could not load.")); }; document.head.append(script); });
    }
    if (version !== generation || request !== primaryGeneration) return;
    const points = (view.chart_data.rows || []).map(r => ({id: r.vertex, latitude: r.location?.latitude, longitude: r.location?.longitude})).filter(p => Number.isFinite(p.latitude) && Number.isFinite(p.longitude) && Math.abs(p.latitude) <= 90 && Math.abs(p.longitude) <= 180);
    if (!points.length) throw new Error("No valid geographic coordinates were retained.");
    const canvas = node("div", {style: "height:460px", role: "region", "aria-label": "Estimated geographic locations"}); host.replaceChildren(canvas);
    mapInstance = window.L.map(canvas, {zoomAnimation: !matchMedia("(prefers-reduced-motion: reduce)").matches});
    const attribution = node("span", {}, config.attribution); window.L.tileLayer(config.tile_url, {maxZoom: 18, attribution: attribution.innerHTML}).addTo(mapInstance);
    const locations = new Map(points.map(p => [W.idKey(p.id), [p.latitude, p.longitude]]));
    points.forEach(p => { const text = node("span", {}, label(p.id)), marker = window.L.circleMarker([p.latitude, p.longitude], {radius: 6, color: S.palette()[0]}).addTo(mapInstance).bindTooltip(text); marker.on("click", () => { state.selected = new Set([W.idKey(p.id)]); applySelection(); }); });
    for (const edge of view.edges || []) { const a = locations.get(W.idKey(edge.source)), b = locations.get(W.idKey(edge.target)); if (a && b) window.L.polyline([a, b], {color: S.palette()[0], weight: 1, opacity: .4}).addTo(mapInstance); }
    mapInstance.fitBounds(points.map(p => [p.latitude, p.longitude]), {padding: [24, 24], maxZoom: 12});
    const list = node("details"), entries = node("ul"); list.append(node("summary", {}, "Select a location"), entries); points.forEach(p => { const li = node("li"); button("map-location-" + entries.children.length, label(p.id), () => { state.selected = new Set([W.idKey(p.id)]); applySelection(); mapInstance.panTo([p.latitude, p.longitude]); }, li); entries.append(li); }); host.append(list);
  }
  async function renderPrimary() {
    const view = state.resultView; if (!view?.view_spec) return; if (view.answer?.count_only) { primaryHost.hidden = true; $("network").hidden = true; legend.hidden = accessible.hidden = true; for (const child of toolbar.children) child.hidden = child.id !== "result-download-menu"; return; } const choice = overrides().primary || spec().view, request = ++primaryGeneration;
    alternatives.clear(); aggregateCy?.destroy(); aggregateCy = null; mapInstance?.remove(); mapInstance = null;
    primary.value = choice; $("network").hidden = !["graph", "result_only", "concentric", "grid", "radial"].includes(choice) || !view.graph_available;
    primaryHost.hidden = !$("network").hidden; legend.hidden = $("network").hidden; accessible.hidden = $("network").hidden;
    if (["concentric", "grid", "radial"].includes(choice)) { $("graph-layout").value = choice; layout(); }
    if (!$("network").hidden) { primaryHost.replaceChildren(); state.cy?.resize(); if (choice === "result_only" && view.context) { $("result-view-mode").value = "focus"; void getResultViews()?.load(); } }
    else if (choice === "meta_graph") {
      primaryHost.replaceChildren(node("p", {}, "Loading recorded group connections…"));
      try { const data = await action("meta-graph"); if (request !== primaryGeneration) return; aggregateCy?.destroy(); primaryHost.replaceChildren(); const canvas = node("div", {class: "comparison-graph"}); canvas.style.height = "440px"; primaryHost.append(canvas, node("p", {class: "muted"}, data.note));
        const render = S.renderData(W, data, {nodes: {color: {field: "attributes.group"}, size: {field: "attributes.size", scale: "sqrt"}}});
        aggregateCy = window.cytoscape({container: canvas, elements: render.elements, style: S.stylesheet(data.graph.directed), layout: {name: "circle"}, minZoom: 1e-6, maxZoom: 20}); S.fit(aggregateCy);
        aggregateCy.on("tap", "node", e => { const group = e.target.data("original").attributes.group; state.selected = new Set((state.graph?.vertices || []).filter(v => v.view?.groups?.some(g => W.stringify(g) === W.stringify(group))).map(v => W.idKey(v.id))); applySelection(); });
      } catch (error) { if (request === primaryGeneration) primaryHost.replaceChildren(node("p", {class: "view-scope"}, error.message)); }
    } else if (choice === "pca") { const data = await action("projection", {method: "pca", seed: 0, cached_only: true}); if (request !== primaryGeneration) return; if (data.id !== overrides().projection_id) throw new Error("The saved projection does not match this view."); showProjection(primaryHost, data); }
    else if (choice === "matrix" && view.profile.kind === "bipartite") {
      const data = await api(endpoint() + "?" + new URLSearchParams({context: true, index: view.index ?? 0, expected_revision: view.revision}));
      if (request !== primaryGeneration) return;
      for (const row of data.labels || []) labels.set(W.idKey(row.id), row.label);
      const rows = view.chart_data.rows, unique = side => [...new Map(rows.flatMap(row => row[side + "_vertices"] || row[side] || []).map(id => [W.idKey(id), id])).values()];
      const current = view.bipartite_sides || [[], []];
      const order = (ids, side) => { const selected = new Set(current[side].map(W.idKey)); return ids.sort((a, b) => Number(selected.has(W.idKey(b))) - Number(selected.has(W.idKey(a))) || label(a).localeCompare(label(b))); };
      charts.renderPrimary(primaryHost, {...view, ...data, chart_data: view.chart_data, bipartite_sides: [order(data.input_bipartite_sides?.[0] || unique("left"), 0), order(data.input_bipartite_sides?.[1] || unique("right"), 1)], current_bipartite_sides: current}, "matrix");
    }
    else if (choice === "map") await renderMap(primaryHost, view, request);
    else if (alternatives.supported.has(choice)) { await alternatives.render(primaryHost, view, choice); }
    else charts.renderPrimary(primaryHost, view, choice);
    if (choice === "metric" && ["maximal-biclique-counting", "triangle-counting", "k-cliques", "motif-counting", "graphlet-counting", "temporal-motifs"].includes(view.profile_facts?.operation)) button("view-enumerate", "List the instances in a new calculation", enumerateResult, primaryHost);
    const graphMode = !$("network").hidden;
    $("graph-layout").parentElement.hidden = !graphMode; $("fit-graph").hidden = !graphMode;
    $("view-lasso").hidden = !graphMode; $("view-surrounding").hidden = !graphMode;
    search.hidden = !graphMode; updateCounts(); drawMinimap();
  }
  function renderCharts() {
    const view = state.resultView; if (!view?.view_spec) { linkedHost.replaceChildren(); return; }
    $("result-building-block").hidden = true; $("chart").hidden = false;
    if (linkedHost.parentElement !== $("chart") || $("chart").children.length !== 1) $("chart").replaceChildren(linkedHost);
    charts.renderLinked(linkedHost, view); renderItemTable(); void renderPrimary().catch(error => notice(error.message, true)); selectionChanged();
  }
  function renderAnswer(view) {
    const answer = view.answer; if (!answer) return;
    $("results-question").textContent = answer.title; $("result-answer-sentence").textContent = answer.sentence;
    $("answer-metrics").replaceChildren();
    for (const metric of answer.metrics) {
      const card = node("div", {class: "metric"}); card.append(node("span", {}, metric.label), node("strong", {}, String(metric.value)));
      if (metric.note) card.append(node("small", {}, metric.note)); $("answer-metrics").append(card);
    }
    $("result-answer").classList.toggle("count-only", answer.count_only);
    $("answer-footer").textContent = [answer.quality && friendly(answer.quality), answer.device?.toUpperCase(), answer.validated && "Validated"].filter(Boolean).join(" · ");
    const details = $("answer-detail-content"); if (recordContextHost) recordContextHost.remove(); details.replaceChildren();
    for (const [caption, value] of [["Plan", state.record.validation?.plan], ["Input snapshot", view.input_graph], ["Rules applied", view.view_spec.rules_applied]]) {
      const disclosure = node("details"); disclosure.append(node("summary", {}, caption), node("pre", {}, W.stringify(value, true))); details.append(disclosure);
    }
    const context = recordContextHost; if (context) { details.append(context); context.querySelector(".section-heading").hidden = true; $("result-context-summary").hidden = true; $("result-context-grid").hidden = false; }
    const picker = $("result-select").closest("label"); picker.hidden = [...$("result-select").options].filter(o => o.value).length <= 1;
    if (picker.firstChild?.nodeType === Node.TEXT_NODE) picker.firstChild.textContent = "";
    $("result-select").setAttribute("aria-label", "Saved analysis");
    document.querySelector(".results-toolbar").append(picker);
    graphCard.classList.toggle("count-only", answer.count_only); $("network").hidden = answer.count_only;
    document.querySelector(".result-card").hidden = answer.count_only;
  }
  let itemSort = {field: "index", ascending: true}, tableItem = null;
  function renderItemTable() {
    const view = state.resultView;
    if (!view?.view_spec || !["bipartite", "groups", "partition"].includes(view.profile.kind)) return false;
    const rows = view.chart_data.rows, bipartite = view.profile.kind === "bipartite", names = view.bipartite_names || ["Left", "Right"];
    const namesText = ids => { const values = ids.map(label); return values.slice(0, 3).join(", ") + (values.length > 3 ? ` +${values.length - 3} more` : ""); };
    const items = rows.map((row, index) => { const left = row.left_vertices || row.left || [], right = row.right_vertices || row.right || [], members = bipartite ? [...left, ...right] : row.vertices || []; return {index, left: namesText(left), right: namesText(right), size: `${left.length} × ${right.length}`, members: members.length, names: namesText(members), ids: members, search: members.map(label).join(" ").toLocaleLowerCase()}; });
    const query = $("table-search").value.trim().toLocaleLowerCase(), shown = items.filter(r => !query || r.search.includes(query) || String(r.index + 1) === query);
    shown.sort((a, b) => (typeof a[itemSort.field] === "number" ? a[itemSort.field] - b[itemSort.field] : String(a[itemSort.field]).localeCompare(String(b[itemSort.field]))) * (itemSort.ascending ? 1 : -1));
    const headers = bipartite ? [["index", "#"], ["left", names[0] + "s"], ["right", names[1].endsWith("s") ? names[1] + "es" : names[1] + "s"], ["size", "Size"], ["members", "Members"]] : [["index", "Group"], ["names", "Entities"], ["members", "Members"]];
    const head = $("result-table").querySelector("thead"), body = $("result-table").querySelector("tbody"), header = node("tr"); head.replaceChildren(header); body.replaceChildren();
    for (const [field, caption] of headers) {
      const th = node("th", {scope: "col", "aria-sort": itemSort.field === field ? itemSort.ascending ? "ascending" : "descending" : "none"});
      const b = node("button", {type: "button"}, caption); b.onclick = () => { itemSort = {field, ascending: itemSort.field === field ? !itemSort.ascending : true}; renderItemTable(); }; th.append(b); header.append(th);
    }
    const pageSize = 30, pages = Math.max(1, Math.ceil(shown.length / pageSize));
    const currentItem = W.stringify([view.workflow_id, view.revision, view.step, view.port, view.index]);
    if (currentItem !== tableItem) {
      tableItem = currentItem; const position = shown.findIndex(row => row.index === view.index);
      if (position >= 0) state.page = Math.floor(position / pageSize);
    }
    state.page = Math.min(state.page, pages - 1);
    for (const row of shown.slice(state.page * pageSize, (state.page + 1) * pageSize)) {
      const tr = node("tr", {"data-result-row": row.index, "aria-selected": String(row.index === view.index)});
      for (const [field] of headers) { const td = node("td"); const text = field === "index" ? row.index + 1 : row[field]; if (field === "index") { const b = node("button", {type: "button"}, String(text)); b.onclick = () => getResultViews()?.select(row.index); td.append(b); } else td.textContent = text; tr.append(td); }
      tr.onclick = event => { if (!event.target.closest("button")) void getResultViews()?.select(row.index); }; body.append(tr);
    }
    $("table-count").textContent = `${shown.length} of ${view.item_count} items`; $("table-page").textContent = `${state.page + 1} / ${pages}`;
    $("table-prev").disabled = state.page === 0; $("table-next").disabled = state.page + 1 >= pages;
    return true;
  }
  async function prepare(view) {
    if (!view?.view_spec) { primaryGeneration++; toolbar.hidden = false; primary.hidden = search.hidden = true; toolbar.querySelectorAll("button[id^=view-]").forEach(b => { b.hidden = true; }); return; }
    toolbar.querySelectorAll("button[id^=view-]").forEach(b => { b.hidden = false; });
    for (const child of toolbar.children) child.hidden = false;
    $("clear-selection").hidden = true;
    primary.hidden = search.hidden = false;
    for (const id of ["view-filter", "view-lasso", "view-slicer", "view-expand", "view-connection", "view-hide", "view-ask", "view-run", "view-unpin"]) if ($(id)) $(id).hidden = !view.graph_available;
    if ($("view-project-embedding")) $("view-project-embedding").hidden = !["vertex_embeddings", "relation_embeddings", "entity_embeddings"].includes(view.profile_facts?.port_type);
    const key = W.stringify([view.workflow_id, view.revision, view.step, view.port]);
    if (key !== viewKey) {
      generation++; viewKey = key; labels.clear(); requestedLabels.clear(); focusKeys = null; comparison?.destroy(); comparison = null; alternatives.clear();
      const saved = state.ignoreSavedView ? null : getExploration()?.settings(); state.visualOverrides = saved?.overrides ? W.parse(W.stringify(saved.overrides)) : {style_rules: [], property_filters: [], hidden_vertices: [], hidden_categories: [], search: ""};
      if (saved && state.restoreEntitySelection) { state.selected = new Set(saved.selected_vertices.map(W.idKey)); state.selectedEdges = new Set(saved.selected_edges.map(W.idKey)); }
      state.selectedItems = new Set(saved?.selected_items || []); state.displayProjection = null;
      state.resolvedViewSpec = view.view_spec;
      const name = saved?.layout || state.resolvedViewSpec.layout.name; if ([...$("graph-layout").options].some(o => o.value === name)) $("graph-layout").value = name;
    }
    state.resolvedViewSpec = view.view_spec;
    renderAnswer(view);
    const nextContext = W.stringify([key, view.index, view.context]);
    if (contextKey !== nextContext) {
      contextKey = nextContext; const saved = state.ignoreSavedView ? null : getExploration()?.settings();
      const matchesItem = saved?.scope?.result?.index === view.index;
      state.viewContext = {vertices: matchesItem ? saved?.context_vertices || [] : [], edges: matchesItem ? saved?.context_edges || [] : []};
    }
    if (state.viewContext?.vertices.length || state.viewContext?.edges.length) {
      try { const data = await action("context", state.viewContext); Object.assign(view, mergeContext(view, data)); }
      catch (error) { notice("Saved input context could not be restored: " + error.message, true); }
    }
    if (!view.graph_available) { const saved = state.ignoreSavedView ? null : getExploration()?.settings(); if (saved) { view.selected_vertices = saved.selected_vertices || []; view.selected_edges = saved.selected_edges || []; } }
    for (const row of view.labels || []) labels.set(W.idKey(row.id), row.label);
    for (const v of view.vertices || []) labels.set(W.idKey(v.id), v.label || String(v.id));
    state.viewLabels = labels;
    const options = [...new Set([spec().view, ...(spec().alternates || []), ...(overrides().projection_id ? ["pca"] : [])])].filter(v => !["table", "result_only", "concentric", "grid", "radial"].includes(v));
    primary.replaceChildren(...options.map(v => node("option", {value: v}, ({graph: "Graph", matrix: "Matrix", small_multiples: "Gallery"}[v] || friendly(v))))); primary.value = overrides().primary || spec().view; search.value = overrides().search || "";
    toolbar.hidden = false; graphCard.hidden = false;
    for (const id of ["view-upgrade", "view-story", "view-export-spec", "view-slicer", "view-unpin"]) $(id).hidden = !debug;
    $("view-vertex-limit").parentElement.hidden = !debug;
    $("view-surrounding-input").checked = Boolean(view.context);
    configureLayoutMenu();
    const limits = view.view_spec.limits;
    scope.textContent = limits.sampled ? `Showing ${limits.shown_vertices.toLocaleString()} of ${limits.total_vertices.toLocaleString()} vertices and ${limits.shown_edges.toLocaleString()} of ${limits.total_edges.toLocaleString()} connections. ${limits.strategy}.` : "";
    if (!limits.collection_complete) scope.textContent += " The saved result collection is incomplete; absent items cannot be inferred.";
    for (const id of ["result-step", "result-port"]) $(id).parentElement.hidden = $(id).options.length <= 1;
  }
  async function layout() {
    const cy = state.cy; if (!cy?.nodes().length) return; const name = $("graph-layout").value;
    state.currentLayout = name; cy.scratch("layoutName", name);
    cy.zoom(1); cy.removeScratch("viewSizes"); S.screenSizes(cy, state.selected);
    // Seed each fresh layout from server positions; repeated defaults are identical.
    if (!state.incrementalLayout) {
      const seed = new Map((state.resultView?.positions || []).map(p => [W.idKey(p.id), p]));
      cy.nodes().forEach((n, i) => { const p = seed.get(n.id()); if (!n.locked()) n.position(p ? {x: p.x, y: p.y} : {x: (i % 5) * 110, y: Math.floor(i / 5) * 80}); });
    }
    const finish = () => {
      if (cy !== state.cy || cy.destroyed()) return;
      if (!state.incrementalLayout && name !== "bipartite" && cy.nodes().length <= 50 && !cy.nodes().some(n => n.locked())) compactLayout(cy);
      S.fitAndClamp(cy); geometry?.draw(); updateCounts(); changed(); notice.clearError?.();
    };
    layoutWorker?.terminate(); layoutWorker = null;
    if (cy.nodes().length > 500 && ["force", "hierarchical"].includes(name)) {
      scope.textContent = "Arranging this view in a background worker…";
      const worker = layoutWorker = new Worker("/vendor/layout-worker.min.js"), version = generation;
      const timeout = setTimeout(() => { worker.terminate(); if (worker === layoutWorker) { layoutWorker = null; scope.textContent = "Layout reached its 30-second display budget. Initial positions are retained; choose a smaller view to refine it."; } }, 30000);
      worker.onmessage = ({data}) => { clearTimeout(timeout); worker.terminate(); if (cy !== state.cy || version !== generation || worker !== layoutWorker) return; layoutWorker = null; if (data.error) { notice(data.error, true); return; } const positions = new Map(data.positions.map(p => [p.id, p])); cy.batch(() => cy.nodes().forEach(n => { if (!n.locked() && positions.has(n.id())) n.position(positions.get(n.id())); })); finish(); scope.textContent = ""; };
      worker.onerror = () => { clearTimeout(timeout); worker.terminate(); if (worker === layoutWorker) { layoutWorker = null; notice("The layout worker could not run. Saved initial positions remain available.", true); } };
      worker.postMessage({layout: name, seed: spec()?.layout.seed || 0, nodes: cy.nodes().map(n => ({id: n.id(), ...n.position(), pinned: n.locked()})), edges: cy.edges().map(e => ({source: e.source().id(), target: e.target().id()}))});
      return;
    }
    if (["force", "hierarchical"].includes(name)) { await window.GraphMineLayoutLibrary(); if (cy !== state.cy || cy.destroyed()) return; }
    const pinned = cy.nodes().filter(n => n.locked());
    let options;
    if (name === "bipartite") {
      const sides = state.resultView?.bipartite_sides || [], assigned = new Set(sides.flat().map(W.idKey));
      const width = Math.max(300, cy.width() - 130);
      cy.batch(() => sides.forEach((ids, side) => ids.forEach((id, i) => {
        const n = cy.getElementById(W.idKey(id));
        if (!n.locked()) n.position({x: (i - (ids.length - 1) / 2) * Math.min(135, width / Math.max(1, ids.length - 1)), y: side * 200});
      })));
      const context = cy.nodes().filter(n => !assigned.has(n.id()));
      context.forEach((n, i) => { if (!n.locked() && !state.incrementalLayout) n.position({x: (i - (context.length - 1) / 2) * Math.min(110, width / Math.max(1, context.length - 1)), y: 100}); });
      options = null;
    } else if (name === "hierarchical") options = {name: "elk", elk: {algorithm: "layered", "elk.direction": "RIGHT", "elk.randomSeed": 0, "elk.spacing.nodeNode": 50}, nodeDimensionsIncludeLabels: true, fit: false, animate: false};
    else if (name === "force") options = cy.nodes().length > 500 ? null : {name: "fcose", quality: "proof", randomize: false, animate: false, fit: false, nodeDimensionsIncludeLabels: true, nodeRepulsion: () => 9000, idealEdgeLength: () => 110, numIter: 1000, fixedNodeConstraint: pinned.map(n => ({nodeId: n.id(), position: n.position()}))};
    else if (name === "radial") options = {name: "breadthfirst", circle: true, directed: true, fit: false, animate: false};
    else if (name === "concentric") options = {name: "concentric", concentric: n => n.data("size"), levelWidth: () => 5, minNodeSpacing: 60, fit: false, animate: false};
    else if (["clustered", "groups"].includes(name)) {
      const groups = new Map(); cy.nodes().forEach(n => { const key = W.stringify(n.data("original").view?.group ?? "Ungrouped"); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(n); });
      const count = Math.ceil(Math.sqrt(groups.size)); [...groups.values()].forEach((nodes, group) => nodes.forEach((n, i) => { if (n.locked()) return; const angle = i * Math.PI * (3 - Math.sqrt(5)), radius = 40 * Math.sqrt(i); n.position({x: group % count * 340 + Math.cos(angle) * radius, y: Math.floor(group / count) * 300 + Math.sin(angle) * radius}); })); options = null;
    } else if (name === "computed") {
      const rows = state.port?.value || [], scale = rows.reduce((m, r) => Math.max(m, ...((r.coordinates || []).slice(0, 2).map(Math.abs))), 1); cy.batch(() => rows.forEach(r => { const n = cy.getElementById(W.idKey(r.vertex)); if (n.length && r.coordinates?.length >= 2 && !n.locked()) n.position({x: r.coordinates[0] / scale * 700, y: r.coordinates[1] / scale * 700}); })); options = null;
    } else options = {name: name === "cose" ? "cose" : name, animate: false, fit: false, randomize: false, nodeDimensionsIncludeLabels: true, spacingFactor: 1.5};
    if (options) await new Promise(resolve => { cy.one("layoutstop", () => { finish(); resolve(); }); cy.layout(options).run(); });
    else finish();
  }
  function compactLayout(cy) {
    // Small layouts must fit at readable screen sizes, not by shrinking labels.
    const nodes = [...cy.nodes(":visible")]; if (!nodes.length) return;
    const xs = nodes.map(n => n.position("x")), ys = nodes.map(n => n.position("y"));
    const x0 = Math.min(...xs), y0 = Math.min(...ys), dx = Math.max(...xs) - x0, dy = Math.max(...ys) - y0;
    const width = Math.max(180, cy.width() - 200), height = Math.max(140, cy.height() - 140);
    const scale = Math.min(1, width / Math.max(1, dx), height / Math.max(1, dy));
    nodes.forEach(n => n.position({x: (n.position("x") - x0 - dx / 2) * scale, y: (n.position("y") - y0 - dy / 2) * scale}));
    for (let round = 0; round < 70; round++) {
      let overlaps = 0;
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j], p = a.position(), q = b.position();
        const bx = a.boundingBox(), by = b.boundingBox();
        const overlapX = Math.min(bx.x2, by.x2) - Math.max(bx.x1, by.x1) + 8;
        const overlapY = Math.min(bx.y2, by.y2) - Math.max(bx.y1, by.y1) + 8;
        if (overlapX <= 0 || overlapY <= 0) continue;
        overlaps++;
        const axis = round > 30 || overlapY < overlapX ? "y" : "x", push = (axis === "x" ? overlapX : overlapY) / 2 + .5;
        const sign = q[axis] >= p[axis] ? 1 : -1;
        a.position(axis, p[axis] - sign * push); b.position(axis, q[axis] + sign * push);
      }
      nodes.forEach(n => n.position({x: Math.max(-width / 2, Math.min(width / 2, n.position("x"))), y: Math.max(-height / 2, Math.min(height / 2, n.position("y")))}));
      if (!overlaps) break;
    }
    const boxes = nodes.map(n => n.boundingBox());
    const collisions = boxes.reduce((sum, a, i) => sum + boxes.slice(i + 1).filter(b => Math.min(a.x2, b.x2) > Math.max(a.x1, b.x1) && Math.min(a.y2, b.y2) > Math.max(a.y1, b.y1)).length, 0);
    if (collisions > 3) {
      // Constrained labels can trap repulsion at the boundary. Use spaced
      // slots nearest the computed positions, retaining their relative order.
      const columnWidth = Math.max(...boxes.map(b => b.w)) * 1.3 + 20;
      const columns = Math.min(nodes.length, Math.max(1, Math.floor(width / columnWidth))), rows = Math.ceil(nodes.length / columns);
      const slots = Array.from({length: columns * rows}, (_, i) => ({x: columns === 1 ? 0 : -width / 2 + i % columns * width / (columns - 1), y: rows === 1 ? 0 : -height / 2 + Math.floor(i / columns) * height / (rows - 1)}));
      nodes.forEach(n => {
        const box = n.boundingBox(), center = {x: (box.x1 + box.x2) / 2, y: (box.y1 + box.y2) / 2};
        let best = 0;
        slots.forEach((p, i) => { if (Math.hypot(p.x - center.x, p.y - center.y) < Math.hypot(slots[best].x - center.x, slots[best].y - center.y)) best = i; });
        const target = slots.splice(best, 1)[0]; n.position({x: n.position("x") + target.x - center.x, y: n.position("y") + target.y - center.y});
      });
    }
  }
  function afterGraph(reused = false) {
    const cy = state.cy; if (!cy || !state.resultView?.view_spec) return;
    $("network").style.removeProperty("height"); cy.resize();
    restyle();
    if (activeCy !== cy) {
      activeCy = cy; cy.on("zoom pan", () => { if (frame) return; frame = requestAnimationFrame(() => { frame = null; if (state.cy === cy && !cy.destroyed()) { S.screenSizes(cy, state.selected); drawMinimap(); } }); });
      geometry = window.GraphMineViewGeometry.overlay(cy, (ids, toggle) => { ids.forEach(id => toggle && state.selected.has(id) ? state.selected.delete(id) : state.selected.add(id)); applySelection(); });
      cy.on("mouseover", "node, edge", e => { hoverTimer = setTimeout(() => tooltipFor(e.target), 150); }); cy.on("mouseout", "node, edge", () => clearTimeout(hoverTimer));
      cy.on("layoutstop", () => S.fitAndClamp(cy));
      cy.on("dragfree", "node", e => { e.target.lock(); e.target.data("pinned", true); geometry?.draw(); changed(); });
      cy.on("cxttap", "node", e => { state.selected = new Set([e.target.id()]); applySelection(); tooltipFor(e.target); button("context-expand", "Expand neighbors", expand, tooltip); button("context-ask", "Ask about selection", () => askSelection?.(selectedIds(), "ask"), tooltip); button("context-run", "Run calculation", () => askSelection?.(selectedIds(), "run"), tooltip); });
      if (state.resultView.positions) { const map = new Map(state.resultView.positions.map(p => [W.idKey(p.id), p])); cy.nodes().forEach(n => { const p = map.get(n.id()); if (p) n.position({x: p.x, y: p.y}); }); }

    }
    const saved = state.ignoreSavedView ? null : getExploration()?.settings();
    const pins = new Set((saved?.pinned || []).map(W.idKey));
    const positions = new Map((saved?.viewport?.positions || []).map(p => [W.idKey(p.id), p]));
    // Lossless JSON records have no prototype; Cytoscape setters need plain objects.
    cy.nodes().forEach(n => { const p = positions.get(n.id()); if (pins.has(n.id()) && p) { n.unlock(); n.position({x: p.x, y: p.y}); n.lock(); } });
    if ((!reused || state.ignoreSavedView) && !state.incrementalLayout) void layout().then(() => {
      if (cy !== state.cy || cy.destroyed()) return;
      if (saved?.viewport && state.restoreEntitySelection) { cy.viewport({zoom: Math.max(.8, Math.min(1.8, saved.viewport.zoom)), pan: {...saved.viewport.pan}}); S.screenSizes(cy, state.selected); }
      state.ignoreSavedView = false; state.restoreEntitySelection = false; changed();
    }).catch(error => notice(error.message, true));
    accessibleList.replaceChildren(); cy.nodes().slice(0, 200).forEach(n => { const li = node("li"), b = node("button", {type: "button", class: "quiet"}, n.data("fullLabel") || n.data("label")); b.onclick = event => { state.selectedItems = new Set(); if (event.shiftKey || event.ctrlKey || event.metaKey) { if (state.selected.has(n.id())) state.selected.delete(n.id()); else state.selected.add(n.id()); } else state.selected = new Set([n.id()]); applySelection(); tooltipFor(n); }; li.append(b); accessibleList.append(li); });
    if (cy.nodes().length > 200) accessibleList.append(node("li", {}, "Use search or the paged result table for additional entities."));
    renderLegend(); applyFilters(); search.oninput(); renderCharts(); configureLayoutMenu();
  }
  function mergeContext(view, response) {
    const vertices = new Map(view.vertices.map(v => [W.idKey(v.id), v])), edges = new Map(view.edges.map(e => [W.idKey(e.id), e]));
    for (const v of response.vertices) if (!vertices.has(W.idKey(v.id))) vertices.set(W.idKey(v.id), {...v, view: {...v.view, display_name: v.view?.display_name || v.label || v.attributes?.name || String(v.id), vertex_type: v.view?.vertex_type || v.type || v.attributes?.type || "Entity", result: false, role: "context", expanded: true}});
    for (const e of response.edges) if (!edges.has(W.idKey(e.id))) edges.set(W.idKey(e.id), {...e, view: {edge_role: "context", result: false}});
    return {...view, vertices: [...vertices.values()], edges: [...edges.values()], vertex_count: vertices.size, edge_count: edges.size};
  }
  function rememberContext(response) {
    const context = state.viewContext || {vertices: [], edges: []};
    state.viewContext = {vertices: [...new Map([...context.vertices, ...response.vertices.map(v => v.id)].map(id => [W.idKey(id), id])).values()], edges: [...new Map([...context.edges, ...response.edges.map(e => e.id)].map(id => [W.idKey(id), id])).values()]};
    changed();
  }
  async function expand() {
    const ids = selectedIds(); if (!ids.length) throw new Error("Select one or more source entities first.");
    const response = await action("neighbors", {vertices: ids.slice(0, 50), visible: state.graph.vertices.map(v => v.id)});
    const graph = mergeContext(state.graph, response);
    if (graph.vertices.length > 2000 || graph.edges.length > 5000) throw new Error("Expansion reached the 2,000-vertex / 5,000-connection context budget. Open a smaller result item to expand further.");
    for (const v of graph.vertices) if (ids.some(id => W.idKey(id) === W.idKey(v.id))) v.view = {...v.view, more_neighbors: response.remaining};
    const old = new Map(state.cy.nodes().map(n => [n.id(), {position: {...n.position()}, pinned: n.locked()}]));
    const origin = old.get(W.idKey(ids[0]))?.position || {x: 0, y: 0};
    rememberContext(response); state.resultView = {...state.resultView, ...graph, expanded_count: (state.resultView.expanded_count || 0) + graph.vertices.length - state.graph.vertices.length};
    state.incrementalLayout = true; renderGraph(state.resultView);
    const cy = state.cy;
    cy.nodes().forEach((n, i) => { const previous = old.get(n.id()); n.unlock(); if (previous) { n.position(previous.position); n.lock(); } else { const angle = i * 2.399963; n.position({x: origin.x + Math.cos(angle) * (85 + i * 6), y: origin.y + Math.sin(angle) * (85 + i * 6)}); } });
    try { await layout(); } finally { cy.nodes().forEach(n => { if (!old.get(n.id())?.pinned) n.unlock(); }); state.incrementalLayout = false; }
    S.fitAndClamp(cy); updateCounts(); changed();
    scope.textContent = `Expanded ${response.vertices.length} neighbors from the saved input${response.remaining ? `; +${response.remaining} more available` : ""}. ${response.edges_truncated ? "Some connections exceed the display limit." : ""}`;
  }
  async function connection() {
    const ids = selectedIds(); if (ids.length !== 2) throw new Error("Select exactly two entities for a shortest-hop connection.");
    const response = await action("connection", {source: ids[0], target: ids[1]});
    if (!response.found) { scope.textContent = "No connection was found within 50 hops in the saved input."; return; }
    const graph = mergeContext(state.graph, response);
    if (graph.vertices.length > 2000 || graph.edges.length > 5000) throw new Error("The connection exceeds this display's context budget. Open a smaller result item.");
    rememberContext(response); state.resultView = {...state.resultView, ...graph};
    state.selectedEdges = new Set(response.edges.map(e => W.idKey(e.id))); renderGraph(graph); scope.textContent = response.note;
  }
  function download(data, filename, type = "application/json") { const url = URL.createObjectURL(data instanceof Blob ? data : new Blob([data], {type})), a = node("a", {href: url, download: filename}); a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
  const exportLegend = data => [...(data?.colorRamp ? [{label: `${friendly(data.colorRamp.field)}: ${data.colorRamp.domain.join("–")}`}] : (data?.legend || []).map(row => ({color: row.color, label: `${row.label || row.value} (${row.count})` }))), ...(data?.sizeField ? [{label: "Size: " + friendly(data.sizeField)}] : [])];
  function currentSVG() { return !$("network").hidden && state.cy?.nodes().length ? window.GraphMineViewGeometry.svg(state.cy, exportLegend(state.viewStyleData)) : window.GraphMineViewGeometry.snapshot(primaryHost); }
  function svgExport() { download(currentSVG(), "graphmine-view.svg", "image/svg+xml"); }
  async function pngExport() {
    const G = window.GraphMineViewGeometry;
    if (!$("network").hidden && state.cy?.nodes().length) { download(await G.png(currentSVG()), "graphmine-view.png", "image/png"); return; }
    if (!window.html2canvas) await new Promise((resolve, reject) => { const script = node("script", {src: "/vendor/html2canvas.min.js"}); script.onload = resolve; script.onerror = () => reject(new Error("The offline export renderer could not load.")); document.head.append(script); });
    const canvas = await window.html2canvas(primaryHost, {backgroundColor: getComputedStyle(graphCard).backgroundColor, scale: Math.min(2, 8000 / Math.max(primaryHost.scrollWidth, primaryHost.scrollHeight)), logging: false});
    download(await new Promise(resolve => canvas.toBlob(resolve)), "graphmine-view.png", "image/png");
  }
  async function reportImage(target) {
    const path = [target.workflow, "steps", target.step, "ports", target.port, "view"].map(encodeURIComponent).join("/");
    const view = await api(`/api/workflows/${path}?` + new URLSearchParams({context: false, expected_revision: target.revision}));
    const G = window.GraphMineViewGeometry;
    let blob;
    if (!view.graph_available) {
      const canvas = document.createElement("canvas"); canvas.width = 1920; canvas.height = 1080;
      const c = canvas.getContext("2d"); c.fillStyle = "white"; c.fillRect(0, 0, canvas.width, canvas.height); c.fillStyle = "#203b43"; c.textAlign = "center";
      c.font = "128px sans-serif"; c.fillText(String(view.answer.metrics[0]?.value ?? ""), 960, 540); c.font = "32px sans-serif"; c.fillText(view.answer.metrics[0]?.note || "", 960, 620);
      blob = await new Promise(resolve => canvas.toBlob(resolve));
    } else {
      const host = node("div", {style: "position:fixed;left:-10000px;top:0;width:960px;height:540px;background:white"}); document.body.append(host);
      const data = S.renderData(W, view, view.view_spec), cy = window.cytoscape({container: host, elements: data.elements, style: S.stylesheet(view.graph?.directed), layout: {name: "preset"}, minZoom: .8, maxZoom: 1.8});
      try {
        const name = view.view_spec.layout.name; cy.scratch("layoutName", name);
        cy.nodes().forEach((n, i) => n.position({x: i % 5 * 110, y: Math.floor(i / 5) * 80}));
        if (name === "bipartite") (view.bipartite_sides || []).forEach((ids, side) => ids.forEach((id, i) => cy.getElementById(W.idKey(id)).position({x: (i - (ids.length - 1) / 2) * Math.min(135, 830 / Math.max(1, ids.length - 1)), y: side * 200})));
        else if (name === "clustered") cy.nodes().forEach((n, i) => n.position({x: Math.cos(i * 2.399963) * 40 * Math.sqrt(i), y: Math.sin(i * 2.399963) * 40 * Math.sqrt(i)}));
        else {
          if (name === "force" || name === "hierarchical") await window.GraphMineLayoutLibrary();
          const options = name === "force" ? {name: "fcose", quality: "proof", randomize: false, nodeRepulsion: () => 9000, idealEdgeLength: () => 110, numIter: 1000} : name === "hierarchical" ? {name: "elk", elk: {algorithm: "layered", "elk.direction": "RIGHT", "elk.randomSeed": 0, "elk.spacing.nodeNode": 50}} : {name: ["circle", "grid", "concentric"].includes(name) ? name : "grid"};
          await new Promise(resolve => { cy.one("layoutstop", resolve); cy.layout({...options, fit: false, animate: false, nodeDimensionsIncludeLabels: true}).run(); });
        }
        if (name !== "bipartite" && cy.nodes().length <= 50) compactLayout(cy); S.fitAndClamp(cy); G.overlay(cy, () => {}).draw();
        blob = await G.png(G.svg(cy, exportLegend(data)));
      } finally { cy.destroy(); host.remove(); }
    }
    return await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(",")[1]); reader.onerror = reject; reader.readAsDataURL(blob); });
  }
  function exportDocument() {
    const exploration = getExploration(); exploration?.capture();
    return {format: "graphmine-view", version: 2, view: exploration?.settings() || null, rules_version: spec()?.rules_version, rules_applied: spec()?.rules_applied};
  }
  async function compare() {
    dialog("Compare with another run", (form, close) => {
      const candidates = state.workflows.filter(r => r.id !== state.record.id && r.status === "completed"), picker = selectInput(form, "Saved run", candidates.map(r => [r.id, (state.session?.title || "Saved input") + " · " + r.validation?.plan?.steps?.map(s => s.operation.replaceAll("-", " ")).join(", ") + " · " + new Intl.DateTimeFormat("en-GB", {day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true}).format(new Date(r.updated_at || r.created_at))]));
      const explicit = selectInput(form, "Compatibility", [["same", "Same saved input and operation"], ["any", "Explicit comparison of different runs"]]);
      button("compare-selected-runs", "Compare", async () => {
        const record = candidates.find(r => r.id === picker.value); if (!record) throw new Error("Choose another completed run.");
        const saved = await api(`/api/workflows/${encodeURIComponent(record.id)}/result?summary=true&expected_revision=${record.revision}`), step = record.validation.order.find(id => saved.steps[id]?.result.operation === state.result.steps[$("result-step").value]?.result.operation) || record.validation.order.at(-1), result = saved.steps[step].result, port = result.ports[$("result-port").value] ? $("result-port").value : Object.keys(result.ports)[0];
        const data = await action("compare", {workflow_id: record.id, revision: record.revision, step, port, allow_different_inputs: explicit.value === "any"}); close();
        dialog("Run comparison", (host, finish) => {
          host.closest("dialog").style.maxWidth = "min(1400px, 95vw)"; const grid = node("div", {class: "view-comparison"}); host.append(grid);
          const instances = []; let syncing = false; const positions = new Map(state.cy?.nodes().map(n => [n.id(), n.position()]) || []);
          const union = [...new Map([...data.left.vertices, ...data.right.vertices].map(v => [W.idKey(v.id), v])).keys()];
          union.forEach((id, i) => { if (!positions.has(id)) positions.set(id, {x: (i % 20) * 100, y: Math.floor(i / 20) * 80}); });
          for (const [side, view] of [["A", data.left], ["B", data.right]]) { const panel = node("section"), canvas = node("div", {class: "comparison-graph"}); panel.append(node("h3", {}, `Run ${side}`), canvas); grid.append(panel); const rendering = S.renderData(W, view, view.view_spec); for (const e of rendering.elements) if (positions.has(e.data.id)) e.position = positions.get(e.data.id);
            const cy = window.cytoscape({container: canvas, elements: rendering.elements, style: S.stylesheet(view.graph?.directed), layout: {name: data.comparable_entities && positions.size ? "preset" : "circle"}, minZoom: 1e-6, maxZoom: 20}); S.fit(cy); instances.push(cy); }
          instances.forEach((cy, i) => cy.on("pan zoom", () => { if (syncing) return; syncing = true; instances[1 - i].viewport({zoom: cy.zoom(), pan: cy.pan()}); instances.forEach(c => S.screenSizes(c)); syncing = false; }));
          host.append(node("p", {class: "view-scope"}, data.comparable_entities ? `${data.diff.left_only.length} vertices only in A · ${data.diff.right_only.length} only in B · ${data.diff.both.length} in both. Edges: ${data.edge_diff.left_only.length} only in A, ${data.edge_diff.right_only.length} only in B.${data.diff_complete ? "" : " Comparison covers retained display data only."}` : "Different snapshots or generated namespaces: matching IDs are not treated as proven entity correspondences."));
          if (data.comparable_entities) button("compare-highlight-diff", "Highlight differences", () => {
            const shared = new Set(data.diff.both.map(W.idKey)), sharedEdges = new Set(data.edge_diff.both.map(W.idKey));
            instances.forEach((cy, i) => cy.batch(() => { cy.nodes().forEach(n => n.style("background-color", shared.has(n.id()) ? "#858b94" : S.palette()[i ? 1 : 2])); cy.edges().forEach(e => { const color = sharedEdges.has(W.idKey(e.data("original").id)) ? "#858b94" : S.palette()[i ? 1 : 2]; e.style({"line-color": color, "target-arrow-color": color}); }); }));
          }, host);
          if (data.membership_transitions?.length) {
            const svg = charts.svgNode("svg", {class: "view-chart", viewBox: "0 0 600 300", role: "img", "aria-label": "Recorded group membership transitions"}), rows = data.membership_transitions.slice(0, 30), left = [...new Set(rows.map(r => W.stringify(r.source)))], right = [...new Set(rows.map(r => W.stringify(r.target)))], maximum = Math.max(...rows.map(r => r.count));
            for (const r of rows) { const a = 25 + left.indexOf(W.stringify(r.source)) * 240 / Math.max(1, left.length - 1), b = 25 + right.indexOf(W.stringify(r.target)) * 240 / Math.max(1, right.length - 1), path = charts.svgNode("path", {d: `M 120,${a} C 270,${a} 330,${b} 480,${b}`, fill: "none", stroke: S.palette()[0], "stroke-width": 1 + 16 * r.count / maximum, opacity: .4}); path.append(charts.svgNode("title", {}, `${r.count} entities: group ${r.source} → group ${r.target}`)); svg.append(path); }
            left.forEach((key, i) => svg.append(charts.svgNode("text", {x: 110, y: 29 + i * 240 / Math.max(1, left.length - 1), "text-anchor": "end", fill: "currentColor"}, "A · " + W.parse(key)))); right.forEach((key, i) => svg.append(charts.svgNode("text", {x: 490, y: 29 + i * 240 / Math.max(1, right.length - 1), fill: "currentColor"}, "B · " + W.parse(key)))); host.append(svg, node("p", {class: "muted"}, `Top ${rows.length} retained membership transitions. Shared or ambiguous memberships omitted: ${data.ambiguous_memberships ?? "scan exceeded budget"}.`));
          }
          const details = node("details"); details.append(node("summary", {}, "Compare recorded parameters"), node("pre", {}, W.stringify(data.parameters, true))); host.append(details);
          host.closest("dialog").addEventListener("close", () => instances.forEach(c => c.destroy()));
        });
      }, form);
    });
  }
  function namedViews() {
    dialog("Named views", (form, close) => {
      const name = textInput(form, "Name this view"); name.maxLength = 160;
      button("save-named-view", "Save current view", async () => { if (!name.value.trim()) throw new Error("Enter a view name."); await getExploration()?.saveNamed(name.value.trim()); close(); }, form);
      for (const saved of getExploration()?.namedViews() || []) { const b = node("button", {type: "button", class: "quiet"}, saved.name); b.onclick = async () => { await getExploration().restoreNamed(saved.id); close(); }; form.append(b); }
    });
  }
  async function story() {
    const view = state.resultView; if (!view) throw new Error("Open a saved result first.");
    const query = {expected_revision: state.record.revision, ...(view.index === null ? {} : {index: view.index})};
    const [input, recorded] = await Promise.all([api(endpoint() + "?" + new URLSearchParams({...query, context: true})), api(endpoint() + "?" + new URLSearchParams({...query, context: false}))]);
    dialog("Explain this saved result", (host, close) => {
      const title = node("h3"), caption = node("p", {role: "status"}), canvas = node("div", {class: "comparison-graph"}), controls = node("div", {class: "view-toolbar"}); host.append(title, caption, canvas, controls); let index = 0, cy = null;
      const facts = view.profile_facts, metrics = view.chart_data.metrics || [], frames = [
        {title: "1 · Saved input", graph: input, caption: facts.input ? `${facts.input.vertices} vertices and ${facts.input.edges} connections in this saved input.` : "This calculation did not retain a graph input.", fact_refs: ["profile_facts.input.vertices", "profile_facts.input.edges"]},
        {title: "2 · Recorded result", graph: recorded, caption: `${recorded.profile.title}. ${recorded.vertex_count} vertices and ${recorded.edge_count} connections in the recorded display witness.${view.complete ? "" : " The retained collection is incomplete."}`, fact_refs: ["profile.title", "vertex_count", "edge_count", "complete"]},
        {title: "3 · Recorded measurements", graph: view, caption: metrics.length ? metrics.map(m => `${m.name}: ${m.value}`).join(" · ") : `Retained output items: ${facts.items}. ${view.note || ""}`, fact_refs: metrics.length ? ["chart_data.metrics"] : ["profile_facts.items", "note"]}
      ];
      state.storyFrames = frames.map(({title, caption, fact_refs, graph}) => ({title, caption, fact_refs, graph, provenance: graph.view_spec.provenance}));
      const show = () => { cy?.destroy(); canvas.replaceChildren(); const frame = frames[index]; title.textContent = frame.title; caption.textContent = frame.caption;
        if (frame.graph.graph_available && frame.graph.vertices.length) { const data = S.renderData(W, frame.graph, frame.graph.view_spec); const positions = new Map((state.cy?.nodes().map(n => [n.id(), n.position()]) || [])); data.elements.forEach((e, i) => { if (positions.has(e.data.id)) e.position = positions.get(e.data.id); else if (e.data.entity !== undefined) e.position = {x: (i % 20) * 100, y: Math.floor(i / 20) * 80}; }); cy = window.cytoscape({container: canvas, elements: data.elements, style: S.stylesheet(frame.graph.graph?.directed), layout: {name: positions.size ? "preset" : "circle"}, minZoom: 1e-6, maxZoom: 20}); S.fit(cy); cy.on("zoom", () => S.screenSizes(cy)); }
        else charts.renderPrimary(canvas, frame.graph, frame.graph.view_spec.view);
      };
      button("story-back", "Previous frame", () => { index = Math.max(0, index - 1); show(); }, controls); button("story-next", "Next frame", () => { index = Math.min(frames.length - 1, index + 1); show(); }, controls); button("story-export", "Export captioned frames", () => download(W.stringify({provenance: view.view_spec.provenance, frames: state.storyFrames}, true), "graphmine-story.json"), controls);
      host.closest("dialog").addEventListener("close", () => cy?.destroy()); show();
    });
  }
  primary.onchange = () => { overrides().primary = primary.value; void renderPrimary().catch(error => notice(error.message, true)); changed(); };
  search.oninput = () => { overrides().search = search.value; const query = search.value.toLocaleLowerCase(); state.cy?.nodes().forEach(n => n.toggleClass("search-match", Boolean(query) && String(n.data("fullLabel") || n.data("label")).toLocaleLowerCase().includes(query))); changed(); };
  let searchIndex = 0; search.onkeydown = event => { if (event.key !== "Enter") return; const matches = state.cy?.nodes(".search-match"); if (matches?.length) { const n = matches[searchIndex++ % matches.length]; state.cy.center(n); state.selected = new Set([n.id()]); applySelection(); } };
  button("view-filter", "Filter", propertyFilter); button("view-slicer", "Slicer", slicer);
  button("view-lasso", "Lasso", () => { geometry?.lasso(); scope.textContent = "Draw around entities to add them to the selection. Shift-drag also starts a lasso; the entity list provides keyboard selection."; });
  button("view-expand", "Expand neighbors", expand); button("view-connection", "Shortest connection", connection);
  button("view-hide", "Hide selected", () => { overrides().hidden_vertices = [...new Map([...(overrides().hidden_vertices || []), ...selectedIds()].map(id => [W.idKey(id), id])).values()]; applyFilters(); changed(); });
  button("view-ask", "Ask about selection", () => askSelection?.(selectedIds(), "ask")); button("view-run", "Run on selection", () => askSelection?.(selectedIds(), "run"));
  button("view-fullscreen", "Fullscreen", () => document.fullscreenElement ? document.exitFullscreen() : graphCard.requestFullscreen());
  const more = node("details", {id: "view-more", class: "view-menu-container"}), moreTools = node("div", {class: "view-menu"}); more.append(node("summary", {}, "More"), moreTools); toolbar.append(more);
  moreTools.addEventListener("click", event => { if (event.target.closest("button")) more.open = false; });
  for (const id of ["view-filter", "view-lasso", "view-slicer", "view-expand", "view-connection", "view-hide", "view-ask", "view-run"]) moreTools.append($(id));
  button("view-unpin", "Unpin all", () => { state.cy?.nodes().unlock(); geometry?.draw(); changed(); }, moreTools); button("view-named", "Saved views", namedViews, moreTools);
  button("view-compare", "Compare with another run", compare, moreTools);
  button("view-story", "Explain in frames", story, moreTools);
  button("view-export-png", "PNG", pngExport);
  button("view-export-svg", "SVG", svgExport);
  button("view-export-spec", "View JSON", () => dialog("View settings", form => form.append(node("pre", {}, W.stringify(exportDocument(), true)))), moreTools);
  button("view-export-visible", "Visible CSV", () => { const visibleItems = new Set([...primaryHost.querySelectorAll("[data-view-item]")].map(e => Number(e.dataset.viewItem))); const rows = !$("network").hidden ? state.cy?.nodes(":visible").map(n => ({id: n.data("entity"), name: n.data("fullLabel"), ...n.data("original").view})) || [] : (state.resultView?.chart_data?.rows || []).filter((r, i) => !visibleItems.size || visibleItems.has(i)).map(r => r && typeof r === "object" ? r : {value: r}), fields = [...new Set(rows.flatMap(Object.keys))].filter(f => !["expanded", "more_neighbors", "prediction_error", "result", "shared", "display_name"].includes(f) && rows.some(r => r[f] !== null && r[f] !== undefined && r[f] !== "" && (!Array.isArray(r[f]) || r[f].length))), quote = value => '"' + String(value ?? "").replaceAll('"', '""') + '"'; download([fields, ...rows.map(r => fields.map(f => r[f] && typeof r[f] === "object" ? W.stringify(r[f]) : r[f]))].map(r => r.map(quote).join(",")).join("\r\n"), "graphmine-visible.csv", "text/csv"); });
  button("view-upgrade", "Use current view rules", () => { state.resolvedViewSpec = state.resultView.current_view_spec || state.resultView.view_spec; overrides().primary = null; restyle(); renderCharts(); changed(); }, moreTools);
  const detail = selectInput(moreTools, "Visible vertex limit", [["2000", "2,000"], ["10000", "10,000"], ["50000", "50,000"]]); detail.id = "view-vertex-limit";
  detail.onchange = () => { state.viewVertexLimit = Number(detail.value); void getResultViews()?.load(); };
  button("view-project-embedding", "Calculate PCA projection", async () => {
    const response = await action("projection", {method: "pca", seed: 0}); primaryHost.hidden = false; $("network").hidden = true; legend.hidden = true; primaryHost.replaceChildren();
    showProjection(primaryHost, response);
    state.displayProjection = response; overrides().projection_id = response.id; overrides().primary = "pca"; if (![...primary.options].some(o => o.value === "pca")) primary.append(node("option", {value: "pca"}, "PCA projection")); primary.value = "pca"; changed();
  }, moreTools);
  function configureLayoutMenu() {
    const select = $("graph-layout"), recommended = spec()?.layout?.alternates || [];
    for (const option of select.options) option.hidden = option.value !== "__more" && (!recommended.includes(option.value) || option.disabled);
    if (!select.querySelector('[value="__more"]')) select.append(node("option", {value: "__more"}, "More layouts…"));
    if (recommended.includes(select.value)) state.currentLayout = select.value;
  }
  $("graph-layout").addEventListener("change", event => {
    if (event.target.value !== "__more") return;
    event.stopImmediatePropagation(); event.target.value = state.currentLayout || spec().layout.name;
    dialog("More layouts", (form, close) => {
      for (const option of [...event.target.options].filter(o => !o.disabled && o.value !== "__more" && !spec().layout.alternates.includes(o.value))) {
        button("choose-layout-" + option.value, option.textContent, async () => { event.target.value = option.value; close(); await layout(); changed(); }, form);
      }
    });
  }, true);
  const surrounding = node("label", {id: "view-surrounding", class: "check"}), surroundingInput = node("input", {id: "view-surrounding-input", type: "checkbox"});
  surrounding.append(surroundingInput, document.createTextNode("Show surrounding graph")); scope.before(surrounding);
  surroundingInput.onchange = () => { $("result-view-mode").value = surroundingInput.checked ? "context" : "focus"; void getResultViews()?.load(); };
  $("result-view-mode").hidden = true; $("result-focus-description").hidden = true;
  moreTools.prepend($("reset-result-focus")); moreTools.append($("result-destination"));
  button("view-style-menu", "Style by…", styleEditor, moreTools);
  $("fit-graph").textContent = "Fit"; $("graph-layout").parentElement.firstChild.textContent = "Layout ";
  $("clear-selection").hidden = true;
  const downloads = node("details", {id: "result-download-menu", class: "view-menu-container"}), downloadItems = node("div", {class: "view-menu"});
  downloads.append(node("summary", {}, "Download ▾"), downloadItems);
  for (const [id, text] of [["view-export-png", "Image (PNG)"], ["view-export-svg", "Image (SVG)"], ["export-csv", "Table with names (CSV)"], ["view-export-visible", "Visible entities (CSV)"], ["export-report", "Full report (ZIP)"], ["download-result", "Raw result (JSON)"]]) {
    const element = $(id); if (element) { element.textContent = text; downloadItems.append(element); }
  }
  $("export-image")?.remove(); $("compare-runs")?.remove();
  $("result-actions-panel").hidden = true;
  const status = $("exploration-status"); if (status) $("view-named").after(status);
  toolbar.append(primary, $("graph-layout").parentElement, $("result-focus"), search, $("fit-graph"), $("view-fullscreen"), downloads, more);
  $("network").closest(".graph-card").append(summary); summary.className = "visually-hidden";
  document.addEventListener("keydown", event => {
    if (state.view !== "results" || /INPUT|TEXTAREA|SELECT/.test(event.target.tagName) || event.target.isContentEditable || document.querySelector("dialog[open]")) return;
    if (event.key.toLowerCase() === "f" && !event.ctrlKey && !event.metaKey && !$("network").hidden) { event.preventDefault(); S.fit(state.cy); }
    if (event.key === "Escape") { tooltip.hidden = true; focusKeys = null; state.selected.clear(); state.selectedItems = new Set(); state.selectedEdges?.clear(); applySelection(); }
    if (["ArrowLeft", "ArrowRight"].includes(event.key) && state.resultView?.item_count > 1) { event.preventDefault(); const i = Math.max(0, Math.min(state.resultView.item_count - 1, (state.resultView.index || 0) + (event.key === "ArrowLeft" ? -1 : 1))); void getResultViews()?.select(i); }
  });
  const resultCard = document.querySelector(".result-card"), tablePanel = node("section", {class: "result-item-table", "aria-label": "Result items"});
  for (const child of [...resultCard.children]) if (!["chart", "result-building-block"].includes(child.id)) tablePanel.append(child);
  resultCard.append(tablePanel);
  toolbar.hidden = true; legend.hidden = true; accessible.hidden = true;
  return {prepare, afterGraph, layout, updateCounts, resetDefault, renderItemTable, renderCharts, loadLabels, selectionChanged, restyle, label, applyFilters, exportDocument, currentSVG, pngExport, reportImage, fit: () => S.fit(state.cy), clear: () => { generation++; primaryGeneration++; mapInstance?.remove(); mapInstance = null; alternatives.clear(); layoutWorker?.terminate(); viewKey = contextKey = null; state.viewContext = null; state.displayProjection = null; state.storyFrames = []; labels.clear(); state.viewLabels = labels; state.resolvedViewSpec = null; state.visualOverrides = null; toolbar.hidden = legend.hidden = accessible.hidden = true; linkedHost.replaceChildren(); primaryHost.replaceChildren(); scope.textContent = ""; tooltip.hidden = true; $("network").hidden = false; $("chart").hidden = false; aggregateCy?.destroy(); }, action};
};
