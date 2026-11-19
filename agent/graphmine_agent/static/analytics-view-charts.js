"use strict";
window.GraphMineViewCharts = ({W, node, label, select}) => {
  const ns = "http://www.w3.org/2000/svg", colors = () => window.GraphMineViewStyle.palette();
  const observed = new Set(), textSizes = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(entries => { for (const {target, contentRect} of entries) { if (!target.isConnected) { textSizes.unobserve(target); observed.delete(target); continue; } if (contentRect.width) { const matrix = target.getScreenCTM(), scale = matrix ? Math.hypot(matrix.a, matrix.b) : Math.min(contentRect.width / target.viewBox.baseVal.width, contentRect.height / target.viewBox.baseVal.height); if (scale > 0) target.querySelectorAll("text").forEach(t => t.style.setProperty("font-size", String(12 / scale) + "px")); } } });
  const svgNode = (tag, attrs = {}, text = null) => { const e = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v)); if (text !== null) e.textContent = text; if (tag === "svg" && textSizes) { for (const old of observed) if (!old.isConnected) { textSizes.unobserve(old); observed.delete(old); } textSizes.observe(e); observed.add(e); } return e; };
  const numeric = x => typeof x === "number" && Number.isFinite(x);
  const rowsOf = view => view.chart_data?.rows || [];
  const memberIds = r => Array.isArray(r) ? r.flatMap(v => typeof v === "object" ? v.data_vertex !== undefined ? [v.data_vertex] : [] : [v]) : r && typeof r === "object" ? r.vertices || [...(r.left_vertices || r.left || []), ...(r.right_vertices || r.right || [])] : [r];
  const identityRows = r => r && typeof r === "object" && !Array.isArray(r) ? [r.vertex, r.anomaly_target && r.anomaly_target !== "vertex" ? null : r.entity, r.source, r.target].filter(x => x !== undefined && x !== null) : [];
  function activate(element, description, action, ids = [], index = null) {
    element.setAttribute("role", "button"); element.setAttribute("tabindex", "0"); element.setAttribute("aria-label", description);
    element.dataset.viewEntities = W.stringify(ids); if (index !== null) { element.dataset.viewItem = index; element.dataset.resultRow = index; }
    element.setAttribute("aria-pressed", "false");
    element.addEventListener("click", action);
    element.addEventListener("keydown", event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); action(); } });
    return element;
  }
  function frame(container, title) {
    const card = node("section", {class: "view-card"}); card.append(node("h3", {}, title)); container.append(card); return card;
  }
  function chart(container, title) {
    const card = frame(container, title), svg = svgNode("svg", {viewBox: "0 0 600 300", class: "view-chart", role: "group", "aria-label": title}); card.append(svg);
    return {card, svg};
  }
  function bars(container, title, items, {signed = false} = {}) {
    const card = frame(container, title), largest = items.slice().sort((a, b) => b.value - a.value).slice(0, 20), max = Math.max(1, ...largest.map(i => Math.abs(i.value)));
    if (!largest.length) { card.append(node("p", {}, "No recorded numeric values are available for this chart.")); return; }
    for (const item of largest) {
      const button = node("button", {type: "button", class: "bar-row"}), track = node("span", {class: "bar-track"}), fill = node("span", {class: "bar-fill"});
      fill.style.width = `${Math.abs(item.value) / max * 100}%`; fill.style.display = "block"; fill.style.backgroundColor = item.color || colors()[item.value < 0 ? 1 : 0]; track.append(fill);
      button.append(node("span", {class: "bar-label"}, item.label), track, node("span", {}, String(item.value)));
      activate(button, `${item.label}: ${item.value}`, () => select(item), item.ids || [], item.index ?? null); card.append(button);
    }
    if (items.length > 20) card.append(node("p", {class: "muted"}, `Highest 20 of ${items.length} loaded values.`));
    if (signed || largest.some(i => i.value < 0)) card.append(node("p", {class: "muted"}, "Bar length shows magnitude; orange marks negative values. Values retain their sign."));
  }
  function histogram(container, title, items) {
    const values = items.filter(i => numeric(i.value)); if (!values.length) return;
    const {card, svg} = chart(container, title), low = Math.min(...values.map(i => i.value)), high = Math.max(...values.map(i => i.value));
    const count = low === high ? 1 : Math.min(16, Math.ceil(Math.sqrt(values.length))), bins = Array.from({length: count}, () => []);
    const range = high / 2 - low / 2;
    values.forEach(item => bins[Math.min(count - 1, range ? Math.floor((item.value / 2 - low / 2) / range * count) : 0)].push(item));
    const maximum = Math.max(...bins.map(b => b.length), 1);
    bins.forEach((bin, i) => {
      const height = bin.length / maximum * 210, first = low * (1 - i / count) + high * i / count, last = low * (1 - (i + 1) / count) + high * (i + 1) / count;
      const rect = svgNode("rect", {x: 48 + i * 520 / count, y: 245 - height, width: 500 / count, height, fill: colors()[0]});
      const description = `${bin.length} records in ${first.toPrecision(4)} to ${last.toPrecision(4)}`;
      rect.append(svgNode("title", {}, description)); activate(rect, description, () => select({ids: bin.flatMap(v => v.ids || []), indices: bin.map(v => v.index)}), bin.flatMap(v => v.ids || [])); svg.append(rect);
    });
    svg.append(svgNode("text", {x: 45, y: 274, fill: "currentColor", "font-size": 12}, low.toPrecision(4)), svgNode("text", {x: 565, y: 274, "text-anchor": "end", fill: "currentColor", "font-size": 12}, high.toPrecision(4)));
    card.append(node("p", {class: "muted"}, `${values.length} loaded observations · select a bin to highlight its members.`));
  }
  function scatter(container, title, items, axis = ["X", "Y"]) {
    const points = items.filter(p => numeric(p.x) && numeric(p.y));
    const {card, svg} = chart(container, title);
    if (!points.length) { card.append(node("p", {}, "No valid coordinates were recorded.")); return; }
    const xs = points.map(p => p.x), ys = points.map(p => p.y), lowX = Math.min(...xs), highX = Math.max(...xs), lowY = Math.min(...ys), highY = Math.max(...ys);
    svg.append(svgNode("line", {x1: 55, x2: 565, y1: 250, y2: 250, stroke: "currentColor"}), svgNode("line", {x1: 55, x2: 55, y1: 20, y2: 250, stroke: "currentColor"}));
    const ratio = (value, low, high) => high === low ? .5 : (value / 2 - low / 2) / (high / 2 - low / 2);
    for (let i = 0; i <= 5; i++) {
      const xv = lowX + (highX - lowX) * i / 5, yv = lowY + (highY - lowY) * i / 5;
      const x = 60 + i * 495 / 5, y = 245 - i * 215 / 5;
      svg.append(svgNode("text", {x, y: 267, "text-anchor": "middle", fill: "currentColor"}, Number(xv.toPrecision(3))), svgNode("text", {x: 45, y: y + 4, "text-anchor": "end", fill: "currentColor"}, Number(yv.toPrecision(3))));
    }
    const buckets = new Map();
    for (const p of points.slice(0, 2000)) { const key = `${p.x}/${p.y}`; if (!buckets.has(key)) buckets.set(key, []); buckets.get(key).push(p); }
    for (const values of buckets.values()) {
      const p = values[0], x = 60 + ratio(p.x, lowX, highX) * 495, y = 245 - ratio(p.y, lowY, highY) * 215;
      const dot = svgNode("circle", {cx: x, cy: y, r: 5 + Math.min(9, Math.sqrt(values.length - 1) * 3), fill: colors()[0], "fill-opacity": .75});
      const description = `${axis[0]} ${p.x}, ${axis[1]} ${p.y}${values.length > 1 ? ` · ${values.length} items; click to cycle` : ""}`;
      dot.append(svgNode("title", {}, description));
      dot.dataset.viewItems = W.stringify(values.map(v => v.index).filter(Number.isInteger));
      activate(dot, description, () => { const current = Number(dot.dataset.currentItem); const i = values.findIndex(v => v.index === current); select(values[(i + 1) % values.length]); }, p.ids || [], p.index ?? null); svg.append(dot);
      if (values.length > 1) svg.append(svgNode("text", {x, y: y + 4, "text-anchor": "middle", fill: "white", "pointer-events": "none"}, values.length));
    }
    svg.append(svgNode("text", {x: 310, y: 285, "text-anchor": "middle", fill: "currentColor", "font-size": 12}, axis[0]), svgNode("text", {x: 8, y: 15, fill: "currentColor", "font-size": 12}, axis[1]));
    card.append(node("p", {class: "muted"}, `${axis[0]}: ${lowX}–${highX}; ${axis[1]}: ${lowY}–${highY}.`));
  }
  function matrix(container, view, pairs = false) {
    const card = frame(container, pairs ? "Recorded pairs" : "Adjacency matrix"), scroll = node("div", {class: "view-matrix", tabindex: 0, role: "region", "aria-label": "Scrollable matrix"}), table = node("table");
    let left, right, values = new Map();
    if (pairs) {
      const rows = rowsOf(view).filter(r => r && typeof r === "object" && r.source !== undefined && r.target !== undefined);
      left = [...new Map(rows.map(r => [W.idKey(r.source), r.source])).values()].slice(0, 50); right = [...new Map(rows.map(r => [W.idKey(r.target), r.target])).values()].slice(0, 50);
      for (const [index, row] of rows.entries()) values.set(W.stringify([row.source, row.target]), {text: row.distance === null ? "∞" : String(row.distance ?? row.score ?? row.similarity ?? row.reachable ?? "✓"), index, row});
    } else {
      const sides = view.bipartite_sides;
      left = (sides?.[0] || view.vertices.map(v => v.id)).slice(0, 300); right = (sides?.[1] || left).slice(0, 300);
      const add = (a, b, edge) => { const key = W.stringify([a, b]), existing = values.get(key); values.set(key, {text: String((existing?.count || 0) + 1), count: (existing?.count || 0) + 1, edge}); };
      for (const edge of view.edges) { add(edge.source, edge.target, edge); if (!view.graph?.directed && W.idKey(edge.source) !== W.idKey(edge.target)) add(edge.target, edge.source, edge); }
    }
    if (!left.length || !right.length) { card.append(node("p", {}, "No pair records are available.")); return; }
    const header = node("tr"); header.append(node("th", {scope: "col"}, "From / to")); right.forEach(id => header.append(node("th", {scope: "col", title: label(id)}, label(id)))); const head = node("thead"); head.append(header); table.append(head);
    const body = node("tbody");
    left.forEach(a => { const tr = node("tr"); tr.append(node("th", {scope: "row"}, label(a))); right.forEach(b => {
      const entry = values.get(W.stringify([a, b])), cell = node("td"), button = node("button", {type: "button", title: `${label(a)} → ${label(b)}`}, entry?.text ?? (pairs ? "—" : "0"));
      const current = view.current_bipartite_sides;
      if (current && current[0].some(id => W.idKey(id) === W.idKey(a)) && current[1].some(id => W.idKey(id) === W.idKey(b))) cell.classList.add("matrix-current");
      if (entry) button.style.backgroundColor = "color-mix(in srgb, var(--graph-category-1) 20%, transparent)";
      activate(button, `${label(a)} to ${label(b)}: ${entry?.text ?? "not recorded"}`, () => select({ids: [a, b], index: pairs ? entry?.index : null, edges: entry?.edge ? [entry.edge.id] : []}), [a, b]); cell.append(button); tr.append(cell);
    }); body.append(tr); }); table.append(body); scroll.append(table); card.append(scroll);
    card.append(node("p", {class: "muted"}, pairs ? "Up to 50 × 50 entities. A missing cell means no retained pair value; it is not a zero or a predicted relationship." : "Cells count recorded connections, including parallel edges. Rows and columns cover the saved input. Outlined cells belong to the current item."));
  }
  let galleryKey = null, galleryPage = 0;
  function gallery(container, view) {
    const key = W.stringify([view.workflow_id, view.step, view.port]); if (key !== galleryKey) { galleryKey = key; galleryPage = Math.floor((view.index || 0) / 12); }
    const card = frame(container, "Recorded items"), grid = node("div", {class: "view-gallery"}), rows = rowsOf(view), pages = Math.max(1, Math.ceil(rows.length / 12));
    galleryPage = Math.min(galleryPage, pages - 1);
    rows.slice(galleryPage * 12, (galleryPage + 1) * 12).forEach((row, position) => {
      const index = galleryPage * 12 + position, ids = row?.pattern?.vertices?.map(v => v.id) || memberIds(row), button = node("button", {class: "view-thumbnail", type: "button"});
      const svg = svgNode("svg", {viewBox: "0 0 180 90", "aria-hidden": true}), shown = ids.slice(0, 40), bipartite = view.profile.kind === "bipartite";
      const sides = [row.left_vertices || row.left || [], row.right_vertices || row.right || []];
      const preview = view.chart_data.item_previews?.[index], members = preview?.vertices?.length ? preview.vertices.map(v => v.id) : shown;
      const positions = new Map();
      if (bipartite) sides.forEach((part, side) => part.slice(0, 40).forEach((id, i) => positions.set(W.idKey(id), {x: part.length === 1 ? 90 : 12 + 156 * i / Math.max(1, part.length - 1), y: side ? 67 : 22, side})));
      else members.forEach((id, i) => { const angle = i * 2.399963, radius = 10 * Math.sqrt(i); positions.set(W.idKey(id), {x: 90 + Math.cos(angle) * radius, y: 45 + Math.sin(angle) * radius}); });
      const edges = bipartite ? sides[0].flatMap(a => sides[1].map(b => ({source: a, target: b}))) : preview?.edges || [];
      for (const edge of edges.slice(0, 200)) { const a = positions.get(W.idKey(edge.source)), b = positions.get(W.idKey(edge.target)); if (a && b) svg.append(svgNode("line", {x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: colors()[0], "stroke-opacity": .25})); }
      for (const p of positions.values()) svg.append(svgNode("circle", {cx: p.x, cy: p.y, r: 4, fill: colors()[p.side || 0]}));
      const names = view.bipartite_names || ["Left member", "Right member"], plural = (name, count) => `${count} ${name.toLowerCase()}${count === 1 ? "" : name.endsWith("s") ? "es" : "s"}`;
      const caption = bipartite ? `${plural(names[0], sides[0].length)} × ${plural(names[1], sides[1].length)}` : `${ids.length} members`;
      button.append(svg, node("strong", {}, caption), node("div", {}, `Item ${index + 1}`));
      activate(button, `View item ${index + 1}: ${caption}`, () => select({index, ids}), ids, index); button.setAttribute("aria-pressed", String(index === view.index)); grid.append(button);
    });
    const controls = node("div", {class: "pagination"}), previous = node("button", {type: "button", id: "gallery-previous"}, "Previous"), next = node("button", {type: "button", id: "gallery-next"}, "Next");
    previous.disabled = galleryPage === 0; next.disabled = galleryPage + 1 >= pages;
    previous.onclick = () => { galleryPage--; container.replaceChildren(); gallery(container, view); }; next.onclick = () => { galleryPage++; container.replaceChildren(); gallery(container, view); };
    controls.append(previous, node("span", {}, `${galleryPage + 1} / ${pages} · ${rows.length} items`), next); card.append(grid, controls);
  }
  function barcode(container, view) {
    const intervals = rowsOf(view).filter(r => numeric(r.birth)).slice(0, 100), {card, svg} = chart(container, "Persistence intervals");
    const finite = intervals.flatMap(r => [r.birth, r.death]).filter(numeric), low = Math.min(0, ...finite), high = Math.max(1, ...finite);
    const x = v => 45 + (v / 2 - low / 2) / (high / 2 - low / 2 || 1) * 490;
    intervals.forEach((r, i) => { const y = 20 + i * 230 / Math.max(1, intervals.length), description = `Dimension ${r.dimension}: birth ${r.birth}; ${r.death === null ? "survives the retained filtration range" : "death " + r.death}`;
      const group = svgNode("g"); group.append(svgNode("line", {x1: x(r.birth), x2: numeric(r.death) ? x(r.death) : 550, y1: y, y2: y, stroke: colors()[Math.abs(r.dimension || 0) % 8], "stroke-width": 4}));
      if (!numeric(r.death)) group.append(svgNode("text", {x: 552, y: y + 4, fill: "currentColor", "font-size": 12}, "→"));
      group.append(svgNode("title", {}, description)); activate(group, description, () => select({index: i, ids: []}), [], i); svg.append(group);
    }); card.append(node("p", {class: "muted"}, `Filtration range ${low}–${high}. Arrows mean no death was retained; this may be an essential interval or one censored by the calculation's cutoff.`));
  }
  function mapping(container, view, merged = false) {
    const rows = rowsOf(view).filter(r => r && typeof r === "object"), {card, svg} = chart(container, "Correspondences between input graphs");
    const pairs = rows.map((r, index) => ({left: r.graph_a_vertex ?? r.source ?? r.left ?? r.source_vertex, right: r.graph_b_vertex ?? r.target ?? r.right ?? r.target_vertex, index})).filter(r => r.left !== undefined && r.left !== null && r.right !== undefined && r.right !== null).slice(0, 500);
    const graphs = view.chart_data?.mapping_graphs;
    if (graphs?.length === 2) {
      const points = new Map(), names = new Map(), matches = new Map();
      if (merged) for (const pair of pairs) { const point = {x: 300 + 150 * Math.cos(pair.index * 2.39996), y: 140 + 100 * Math.sin(pair.index * 2.39996)}; matches.set("0:" + W.idKey(pair.left), point); matches.set("1:" + W.idKey(pair.right), point); }
      for (const [side, graph] of graphs.entries()) for (const [i, vertex] of graph.vertices.entries()) { const id = side + ":" + W.idKey(vertex.id); points.set(id, matches.get(id) || {x: (side ? 455 : 145) + 105 * Math.cos(i * 2 * Math.PI / Math.max(1, graph.vertices.length)), y: 140 + 105 * Math.sin(i * 2 * Math.PI / Math.max(1, graph.vertices.length))}); names.set(id, vertex.label || W.idLabel(vertex.id)); }
      for (const [side, graph] of graphs.entries()) for (const edge of graph.edges) { const a = points.get(side + ":" + W.idKey(edge.source)), b = points.get(side + ":" + W.idKey(edge.target)); if (a && b) svg.append(svgNode("line", {x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: colors()[side], "stroke-opacity": .25})); }
      if (!merged) for (const pair of pairs) { const a = points.get("0:" + W.idKey(pair.left)), b = points.get("1:" + W.idKey(pair.right)); if (!a || !b) continue; const line = svgNode("path", {d: `M ${a.x},${a.y} C 280,${a.y} 320,${b.y} ${b.x},${b.y}`, fill: "none", stroke: colors()[2], "stroke-width": 2, "stroke-dasharray": "4 3"}); activate(line, `${names.get("0:" + W.idKey(pair.left))} corresponds to ${names.get("1:" + W.idKey(pair.right))}`, () => select({index: pair.index, ids: []}), [], pair.index); svg.append(line); }
      for (const [id, p] of points) { const dot = svgNode("circle", {cx: p.x, cy: p.y, r: 5, fill: colors()[Number(id[0])]}); dot.append(svgNode("title", {}, `${id[0] === "0" ? "Left" : "Right"}: ${names.get(id)}`)); svg.append(dot); if (points.size <= 40) svg.append(svgNode("text", {x: p.x + 7, y: p.y + 4, fill: "currentColor", "font-size": 12}, names.get(id).slice(0, 18))); }
      card.append(node("p", {class: "muted"}, merged ? "Matched endpoints share display positions only. The saved graphs, edges, and identities stay separate." : "Two saved input graphs; dashed curves show recorded correspondences. Each graph retains its own identifier namespace. Up to 500 vertices per graph.")); return;
    }
    for (const [i, pair] of pairs.entries()) { const y = 20 + i * 250 / Math.max(1, pairs.length), g = svgNode("g");
      g.append(svgNode("line", {x1: 180, x2: 420, y1: y, y2: y, stroke: colors()[0]}), svgNode("text", {x: 170, y: y + 4, "text-anchor": "end", "font-size": 12, fill: "currentColor"}, "Left: " + W.idLabel(pair.left)), svgNode("text", {x: 430, y: y + 4, "font-size": 12, fill: "currentColor"}, "Right: " + W.idLabel(pair.right)));
      activate(g, `Left ${W.idLabel(pair.left)} matched to right ${W.idLabel(pair.right)}`, () => select({index: pair.index, ids: []}), [], pair.index); svg.append(g);
    }
    card.append(node("p", {class: "muted"}, "Left and right identifiers belong to separate graphs. A correspondence does not merge the underlying entities."));
  }
  function scores(view) { const field = view.profile_facts?.scores?.field || "score"; return rowsOf(view).map((r, index) => { const edgeId = r?.edge ?? (r?.anomaly_target === "edge" ? r.entity : undefined), edge = edgeId !== undefined ? view.edges.find(e => W.idKey(e.id) === W.idKey(edgeId)) : null; return {index, ids: edge ? [edge.source, edge.target] : identityRows(r), edges: edge ? [edge.id] : [], label: edge ? `${label(edge.source)} → ${label(edge.target)}` : r?.anomaly_target && r.anomaly_target !== "vertex" ? `${r.anomaly_target} ${index + 1}` : label(r?.vertex ?? r?.entity ?? index), value: field === "value[0]" ? r?.value?.[0] : r?.[field] ?? r?.value}; }).filter(i => numeric(i.value)); }
  function renderPrimary(container, view, primary) {
    container.replaceChildren();
    const rows = rowsOf(view), kind = view.profile.kind;
    if (primary === "timeline") scatter(container, "Recorded departure and arrival times", rows.map((r, index) => ({index, ids: identityRows(r), label: label(r.vertex ?? r.target ?? index), x: r.departure, y: r.arrival})), ["Departure time (input units)", "Arrival time (input units)"]);
    else if (primary === "matrix") matrix(container, view, kind === "pairs");
    else if (primary === "small_multiples") gallery(container, view);
    else if (primary === "barcode") barcode(container, view);
    else if (primary === "mapping" || primary === "merged_mapping") mapping(container, view, primary === "merged_mapping");
    else if (primary === "histogram") histogram(container, "Sample distribution", rows.map((r, index) => ({index, ids: [], value: typeof r === "object" ? r.value ?? r.statistic : r})));
    else if (primary === "spectrum") {
      scatter(container, "Eigenvalue spectrum", rows.map((r, index) => ({index, ids: [], label: `Eigenpair ${index + 1}`, x: index + 1, y: r.eigenvalue ?? r.value})), ["Eigenpair", "Eigenvalue"]);
    } else if (primary === "coordinates" || primary === "scatter") {
      let points;
      if (kind === "intervals") points = rows.map((r, index) => ({index, ids: [], label: `Interval ${index + 1}`, x: r.birth, y: r.death}));
      else if (kind === "bipartite") points = rows.map((r, index) => ({index, ids: memberIds(r), label: `Biclique ${index + 1}`, x: (r.left_vertices || r.left || []).length, y: (r.right_vertices || r.right || []).length}));
      else points = rows.map((r, index) => ({index, ids: identityRows(r), label: label(r.vertex ?? r.entity ?? r.relation ?? index), x: r.location?.longitude ?? r.longitude ?? r.coordinates?.[0] ?? r.values?.[0] ?? r.embedding?.[0], y: r.location?.latitude ?? r.latitude ?? r.coordinates?.[1] ?? r.values?.[1] ?? r.embedding?.[1]}));
      scatter(container, kind === "locations" ? "Estimated geographic coordinates" : kind === "intervals" ? "Persistence diagram" : "Recorded coordinates", points, kind === "locations" ? ["Longitude", "Latitude"] : kind === "intervals" ? ["Birth", "Death"] : ["Dimension 1", "Dimension 2"]);
      if (kind === "embedding") container.append(node("p", {class: "muted"}, "Original embedding dimensions are shown. Use Calculate PCA projection for a separate, saved display projection."));
    } else if (primary === "metric") {
      const card = frame(container, view.view_spec.title), value = rows[0]; card.append(node("strong", {class: "view-large-metric"}, typeof value === "object" ? String(value?.display ?? value?.value ?? "See exact result below") : String(value ?? "No value retained")));
      card.append(node("p", {class: "muted"}, "This output contains summary values. Listing instances requires a separate calculation."));
    } else if (primary === "table") container.append(node("p", {class: "view-scope"}, "The recorded values are shown in the result table below."));
  }
  function renderLinked(container, view) {
    container.replaceChildren(); const rows = rowsOf(view);
    for (const definition of view.view_spec.linked) {
      const id = definition.id;
      if (id === "group_sizes") bars(container, definition.title, (view.chart_data?.group_sizes || []).map((r, index) => ({label: view.view_spec.nodes.color.categories.find(c => W.stringify(c.value) === W.stringify(r.id))?.label || `Group ${index + 1}`, color: view.view_spec.nodes.color.categories.find(c => W.stringify(c.value) === W.stringify(r.id))?.color, value: r.size, index: r.index ?? index, group: r.id, ids: []})));
      else if (id === "recorded_counts") bars(container, definition.title, rows.map(r => ({label: String(r.pattern ?? r.motif ?? r.graphlet ?? "Count"), value: r.count, ids: []})).filter(r => numeric(r.value)));
      else if (id === "visits") bars(container, definition.title, (view.chart_data.visits || []).map(r => ({label: label(r.vertex), value: r.count, ids: [r.vertex]})));
      else if (id === "group_matrix") {
        const card = frame(container, definition.title), table = node("table"), scroll = node("div", {class: "view-matrix"}), rows = view.chart_data.group_connections || [], groups = [...new Set(rows.flatMap(r => [W.stringify(r.source), W.stringify(r.target)]))].slice(0, 32), counts = new Map(rows.map(r => [W.stringify([r.source, r.target]), r.count]));
        table.append(node("caption", {}, view.chart_data.group_connections_complete ? "Counts of saved input edge records between disjoint groups" : "Bounded counts among singly assigned groups; overlapping memberships are omitted"));
        const header = node("tr"); header.append(node("th", {}, "From / to")); groups.forEach(key => header.append(node("th", {scope: "col"}, "Group " + W.parse(key)))); table.append(header);
        for (const a of groups) { const tr = node("tr"); tr.append(node("th", {scope: "row"}, "Group " + W.parse(a))); for (const b of groups) { const count = counts.get(W.stringify([W.parse(a), W.parse(b)])) ?? (!view.profile_facts.input?.directed ? counts.get(W.stringify([W.parse(b), W.parse(a)])) : 0) ?? 0, cell = node("td"), button = node("button", {type: "button"}, String(count)); if (count) button.style.backgroundColor = "color-mix(in srgb, var(--graph-category-1) 25%, transparent)"; button.onclick = () => select({ids: view.vertices.filter(v => v.view?.groups?.some(g => W.stringify(g) === a || W.stringify(g) === b)).map(v => v.id)}); cell.append(button); tr.append(cell); } table.append(tr); } scroll.append(table); card.append(scroll);
      }
      else if (id === "ranked_scores") bars(container, definition.title, scores(view));
      else if (id === "score_histogram") histogram(container, definition.title, scores(view));
      else if (id === "biclique_sizes") scatter(container, definition.title, rows.map((r, index) => ({index, ids: memberIds(r), label: `Biclique ${index + 1}`, x: (r.left_vertices || r.left || []).length, y: (r.right_vertices || r.right || []).length})), ["Left members", "Right members"]);
      else if (id === "edge_weights" || id === "degrees") histogram(container, definition.title, (id === "degrees" ? view.chart_data.degrees : view.edges).map((r, index) => ({index, ids: r.vertex !== undefined ? [r.vertex] : [r.source, r.target], value: r.degree ?? r.weight})));
      else if (["pair_values", "match_scores", "confidence"].includes(id)) histogram(container, definition.title, (id === "confidence" ? view.chart_data.location_dispersion || rows : rows).map((r, index) => ({index, ids: identityRows(r), value: r.weighted_mean_neighbor_distance_km ?? r.score ?? r.distance ?? r.confidence ?? r.similarity})));
      else if (id === "persistence") scatter(container, definition.title, rows.map((r, index) => ({index, ids: [], label: `Interval ${index + 1}`, x: r.birth, y: r.death})), ["Birth", "Death"]);
      else if (id === "support") bars(container, definition.title, rows.map((r, index) => ({index, ids: [], label: `Pattern ${r.pattern_id ?? index + 1}`, value: r.support ?? r.support_count})).filter(r => numeric(r.value)));
      else if (id === "flow_capacity") bars(container, definition.title, (view.flow_rows || []).map((r, index) => ({index, ids: [r.source, r.target], edges: [r.id], label: `${label(r.source)} → ${label(r.target)} (capacity ${r.capacity ?? r.weight ?? "unrecorded"})`, value: r.flow})).filter(r => numeric(r.value)));
      else if (id === "route") {
        const route = view.chart_data.route || [], card = frame(container, definition.title), list = node("ol"); route.forEach((row, index) => { const v = row.vertex, li = node("li"), details = Object.entries(row).filter(([k]) => k !== "vertex").map(([k, value]) => `${k}: ${value}`).join(" · "), button = node("button", {type: "button", class: "quiet"}, label(v) + (details ? " · " + details : "")); activate(button, `Step ${index + 1}: ${label(v)}`, () => select({ids: [v]}), [v]); li.append(button); list.append(li); }); card.append(list, node("p", {class: "muted"}, route.length ? view.chart_data.route_note : "Select a recorded destination or item to inspect its ordered route."));
      } else if (id === "metrics" || id === "prediction_metrics") {
        const card = frame(container, definition.title), list = node("dl");
        for (const metric of [...(view.chart_data?.metrics || []), ...(view.chart_data?.learning_metrics || [])]) list.append(node("dt", {}, metric.name), node("dd", {}, String(metric.value)));
        for (const row of view.chart_data?.confusion || []) list.append(node("dt", {}, `Truth ${row.truth} → predicted ${row.prediction}`), node("dd", {}, String(row.count)));
        const baseline = view.chart_data?.baseline;
        if (baseline) for (const [name, value] of [["Saved input vertices", baseline.vertices], ["Saved input edges", baseline.edges], ["Saved input density", baseline.density], ["Displayed result vertices", view.vertex_count]]) if (value !== null) list.append(node("dt", {}, name), node("dd", {}, String(value)));
        card.append(list); if (baseline?.density !== null) card.append(node("p", {class: "muted"}, baseline?.density_definition || ""));
      } else if (id === "occurrences") {
        const counts = new Map(); rows.forEach((r, index) => { const key = r.pattern ?? r.pattern_id ?? "Occurrences", item = counts.get(key) || {label: String(key), value: 0, ids: [], index}; item.value++; counts.set(key, item); }); bars(container, definition.title, [...counts.values()]);
      }
    }
    if (view.chart_data?.core_scores?.length) histogram(container, "Recorded core numbers", view.chart_data.core_scores.map(r => ({ids: [r.vertex], label: label(r.vertex), value: r.score ?? r.core})));
    if (view.chart_data && !view.chart_data.rows_complete) container.append(node("p", {class: "view-scope"}, `Charts use ${view.chart_data.rows.length} of ${view.chart_data.total_rows} retained rows.${view.chart_data.nested_truncated ? " Nested memberships or coordinates are also bounded." : ""} ${view.complete ? "Use the table for the complete retained output." : "The saved collection is incomplete."}`));
  }
  function selectionChanged(selected, items = new Set()) {
    document.querySelectorAll("[data-view-entities]").forEach(el => {
      let ids; try { ids = W.parse(el.dataset.viewEntities); } catch { return; }
      const group = el.dataset.viewItems ? W.parse(el.dataset.viewItems) : el.dataset.viewItem !== undefined ? [Number(el.dataset.viewItem)] : [];
      const item = group.find(index => items.has(index)), active = item !== undefined || !group.length && ids.length > 0 && ids.every(id => selected.has(W.idKey(id)));
      el.setAttribute("aria-pressed", String(active)); if (item !== undefined) el.dataset.currentItem = item;
      if (el.tagName.toLowerCase() === "circle") { el.setAttribute("stroke", active ? "currentColor" : "none"); el.setAttribute("stroke-width", "3"); }
    });
  }
  return {renderPrimary, renderLinked, selectionChanged, svgNode, scatter, bars, histogram, matrix};
};
