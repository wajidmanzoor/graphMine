"use strict";
window.GraphMineResultViews = ({state, api, W, node, renderGraph, applySelection, renderSelectionChip, notice, savedSelection, onContext, onView, onClear, onRender}) => {
  const $ = id => document.getElementById(id);
  const toolbar = node("div", {class: "result-focus", id: "result-focus", hidden: true});
  const mode = node("select", {id: "result-view-mode", "aria-label": "Result graph scope"});
  mode.append(node("option", {value: "focus"}, "Result only"), node("option", {value: "context"}, "Highlight result in input context"));
  const reset = node("button", {id: "reset-result-focus", type: "button", class: "quiet"}, "Default result view");
  const description = node("p", {id: "result-focus-description", role: "status"});
  const item = node("input", {id: "result-item-index", type: "number", min: "1", "aria-label": "Recorded item number"});
  const choose = node("button", {id: "show-result-item", type: "button", class: "quiet"}, "Show item");
  const previous = node("button", {id: "previous-result-item", type: "button", class: "quiet", "aria-label": "Previous recorded item"}, "◀");
  const next = node("button", {id: "next-result-item", type: "button", class: "quiet", "aria-label": "Next recorded item"}, "▶");
  const itemCount = node("span", {id: "result-item-count"});
  toolbar.append(mode, previous, item, itemCount, next, reset, description); $("network").before(toolbar);
  const block = node("div", {id: "result-building-block", class: "result-building-block", hidden: true}); $("chart").after(block);
  const destination = node("select", {id: "result-destination", "aria-label": "Path destination", hidden: true}); toolbar.prepend(destination);
  // chosen: the person picked (or restored) an item, as opposed to a default view.
  let generation = 0, selectedIndex = null, useSelection = true, chosen = false, restorePending = true, controller = null, initial = null;
  const vertexLabels = new Map();
  const entityLabel = id => vertexLabels.get(W.idKey(id)) || W.idLabel(id);
  async function load() {
    const record = state.record, step = $("result-step").value, port = $("result-port").value;
    if (!record || port === "__result") { toolbar.hidden = true; return; }
    const problem = state.result?.steps[step]?.result?.problem;
    if (!state.caps?.problems.some(card => card.id === problem && card.visualization)) { toolbar.hidden = true; return; }
    const selectionScope = W.stringify([record.id, record.revision, step, port]);
    if (state.selection.scope !== selectionScope) {
      state.restoreEntitySelection = state.selection.scope === null;
      state.selection.scope = selectionScope; state.selection.item = null;
      state.selected.clear(); state.selectedEdges.clear(); state.selectedItems.clear();
    }
    if (restorePending) {
      const saved = savedSelection?.(record, step, port);
      if (saved) { selectedIndex = saved.index; chosen = saved.index !== null && saved.index !== undefined; mode.value = saved.context ? "context" : "focus"; }
      restorePending = false;
    }
    const current = ++generation, epoch = state.epoch;
    controller?.abort(); controller = new AbortController();
    state.resultViewPending = true; state.resultViewError = null; onContext?.();
    for (const vertex of state.graph?.vertices || []) if (vertex.label) vertexLabels.set(W.idKey(vertex.id), String(vertex.label));
    toolbar.hidden = false;
    description.textContent = "Loading the recorded result view…";
    const params = new URLSearchParams({context: String(mode.value === "context"), expected_revision: record.revision});
    if (state.viewVertexLimit) { params.set("vertex_limit", state.viewVertexLimit); params.set("edge_limit", Math.min(100000, Math.max(5000, state.viewVertexLimit * 2))); }
    if (selectedIndex !== null) params.set("index", selectedIndex);
    const path = [record.id, "steps", step, "ports", port, "view"].map(encodeURIComponent).join("/");
    try {
      const response = await api(`/api/workflows/${path}?${params}`, {signal: controller.signal});
      if (current !== generation || epoch !== state.epoch || state.record?.id !== record.id) return;
      if (response.revision !== undefined && response.revision !== record.revision) throw new Error("This analysis revision changed. Reopen its results.");
      if (response.vertices.length > 2000 && window.GraphMineViewStyle && !window.GraphMineViewStyle.canWebGL(response)) {
        state.viewVertexLimit = 2000; notice("This browser or scene requires canvas rendering. The view is limited to 2,000 vertices to keep interaction responsive; the saved result and paged table retain all records."); return load();
      }
      state.resultView = response;
      await onView?.(response);
      if (current !== generation || epoch !== state.epoch) return;
      state.resultViewPending = false;
      for (const vertex of response.vertices) if (vertex.label) vertexLabels.set(W.idKey(vertex.id), String(vertex.label));
      // Only an item the person chose narrows a follow-up question.
      useSelection = chosen;
      selectedIndex = response.index;
      item.hidden = !response.item_count;
      previous.hidden = next.hidden = itemCount.hidden = !response.item_count;
      previous.disabled = (response.index ?? 0) <= 0; next.disabled = (response.index ?? 0) >= response.item_count - 1;
      itemCount.textContent = `of ${response.item_count}`;
      item.max = String(response.item_count); item.value = response.index === null ? "" : String(response.index + 1);
      state.groupFilter = response.context || response.index === null ? "" : state.groups?.find(g => g.index === response.index)?.key || "";
      state.groupGraph = null;
      state.selection.item = {workflow_id: record.id, step, port, index: response.index, vertices: response.selected_vertices, edges: response.selected_edges};
      state.selectedItems = new Set(response.index === null ? [] : [response.index]);
      if (!initial) initial = {index: response.index, context: response.context, layout: $("graph-layout").value || response.view_spec?.layout?.name};
      notice.clearError?.();
      if (response.flow_rows) { state.flowRows = response.flow_rows; $("flow-direction").checked = !response.context; }
      const count = response.graph_available ? ` ${response.vertex_count} vertices · ${response.edge_count} edges.` : "";
      description.textContent = response.note + count + (!response.complete ? " This result collection is incomplete or count-only." : "");
      renderGraph(response.graph_available ? response : null);
      destination.hidden = response.profile.kind !== "path_tree";
      destination.replaceChildren(node("option", {value: ""}, "Choose a path destination"));
      if (!destination.hidden) for (const [index, row] of (state.port?.value || []).entries()) if (row.vertex !== undefined) {
        const label = entityLabel(row.vertex);
        destination.append(node("option", {value: index}, `${label}${row.distance === null || row.reachable === false ? " · unreachable" : ""}`));
      }
      destination.value = selectedIndex === null ? "" : String(selectedIndex);
      if (!response.graph_available) $("preview-scope").textContent = "Choose input context to inspect the source network.";
      applySelection(); renderSelectionChip();
      renderBlocks();
    } catch (error) {
      if (current !== generation || epoch !== state.epoch || error.name === "AbortError") return;
      state.resultView = null; state.resultViewPending = false; state.resultViewError = error.message; renderGraph(null);
      description.textContent = `Could not load this result view: ${error.message}`;
      notice(error.message, true);
    }
  }
  async function select(index) {
    if (!Number.isInteger(index) || index < 0) return;
    selectedIndex = index; chosen = true; await load(); renderBlocks();
  }
  mode.onchange = () => { void load(); };
  destination.onchange = () => { if (destination.value !== "") void select(Number(destination.value)); };
  choose.onclick = () => { if (item.value && item.validity.valid) void select(Number(item.value) - 1); };
  item.onchange = choose.onclick;
  item.onkeydown = event => { if (event.key === "Enter") { event.preventDefault(); choose.onclick(); } };
  previous.onclick = () => { if ((selectedIndex ?? 0) > 0) void select(selectedIndex - 1); };
  next.onclick = () => { if ((selectedIndex ?? 0) + 1 < (state.resultView?.item_count || 0)) void select((selectedIndex ?? 0) + 1); };
  reset.onclick = () => { selectedIndex = initial?.index ?? null; chosen = false; mode.value = initial?.context ? "context" : "focus"; state.selected.clear(); state.selectedEdges.clear(); window.GraphMineWorkspace?.visualization?.resetDefault(initial); void load(); renderBlocks(); };
  function clear() { generation++; controller?.abort(); vertexLabels.clear(); selectedIndex = null; chosen = false; initial = null; state.selection.item = null; state.selected.clear(); state.selectedItems.clear(); state.resultView = null; state.resultViewPending = false; state.resultViewError = null; state.selectedEdges = null; mode.value = "focus"; toolbar.hidden = true; block.hidden = true; restorePending = true; onContext?.(); onClear?.(); }
  function selection() {
    const v = state.resultView;
    // The whole output is already the previous result; only an item narrows it.
    if (!v || !state.record || !useSelection || v.index === null || v.index === undefined) return null;
    if (state.port?.type === "scalar" || Array.isArray(state.port?.value) && !state.port.value.length) return null;
    return {workflow_id: state.record.id, step: v.step, port: v.port, index: v.index,
      label: `${v.profile.title}${v.index !== null ? ` ${v.index + 1}` : ""}`};
  }
  const svgNode = (tag, attributes) => { const e = document.createElementNS("http://www.w3.org/2000/svg", tag); for (const [k, v] of Object.entries(attributes || {})) e.setAttribute(k, v); return e; };
  const numeric = value => typeof value === "number" && Number.isFinite(value) ? value : null;
  function renderBlocks() {
    if (state.resultView?.view_spec && onRender) { block.hidden = true; onRender(); return; }
    const focusedLocation = block.querySelector("[data-location-index]:focus")?.dataset.locationIndex;
    block.replaceChildren(); block.hidden = true;
    const result = state.result?.steps[$("result-step").value]?.result, port = state.port;
    if (!result || !port) return;
    const spec = state.caps?.problems.find(c => c.id === result.problem)?.visualization || state.resultView?.profile;
    if (!spec) return;
    const rows = Array.isArray(port.value) ? port.value : ["motif_instances", "graphlet_instances"].includes(port.type) ? Object.entries(port.value || {}).flatMap(([pattern, instances]) => instances.map(vertices => ({pattern, vertices}))) : port.type === "eigenpairs" ? (port.value.eigenvalues || []).map(eigenvalue => ({eigenvalue})) : [];
    const scope = port.value_truncated ? `Showing ${rows.length} loaded rows of ${port.total_items}.` : `${rows.length} retained rows.`;
    const begin = title => { block.hidden = false; block.append(node("strong", {}, title), node("p", {class: "muted"}, scope)); };
    if (["path", "path_tree", "ordered"].includes(spec.kind)) {
      begin(spec.kind === "ordered" ? "Recorded vertex order" : port.type === "edge_sequence_collection" ? "Recorded edge order" : "Path details");
      const row = rows[selectedIndex ?? 0];
      let sequence = spec.kind === "ordered" ? rows : row?.vertices || (Array.isArray(row) ? row : null);
      if (spec.kind === "path_tree" && row?.vertex !== undefined) {
        const lookup = new Map(rows.filter(r => r.source === row.source).map(r => [W.idKey(r.vertex), r])), seen = new Set();
        sequence = []; let current = row;
        while (current && !seen.has(W.idKey(current.vertex))) { seen.add(W.idKey(current.vertex)); sequence.unshift(current.vertex); const parent = current.predecessor; current = parent !== null && parent !== undefined ? lookup.get(W.idKey(parent)) : null; if (!current && parent !== null && parent !== undefined) block.append(node("p", {}, "The beginning of this path is outside the loaded table rows. The graph resolves the complete saved predecessor chain.")); }
      }
      if (spec.kind === "path_tree" && selectedIndex === null) { sequence = null; block.append(node("p", {}, "Choose a destination to show one path from the recorded predecessor tree.")); }
      if (sequence) for (const [index, id] of sequence.slice(0, 100).entries()) block.append(node("span", {class: "path-step"}, `${index + 1}. ${entityLabel(id)}`));
      else block.append(node("p", {}, "Select a row to inspect its recorded edges and timing in the graph and table."));
      if (sequence?.length > 100) block.append(node("p", {}, "The sequence preview shows its first 100 entries."));
      if (selectedIndex !== null && row && !Array.isArray(row)) for (const name of ["distance", "total_weight", "bottleneck_capacity", "departure", "arrival", "reachable"]) if (row[name] !== undefined) block.append(node("p", {}, `${name.replaceAll("_", " ")}: ${row[name] === null ? "unavailable" : row[name]}`));
    } else if (spec.kind === "pairs") {
      const pairRows = rows.filter(r => r && r.source !== undefined && r.target !== undefined);
      if (!pairRows.length) return;
      const left = [...new Map(pairRows.map(r => [W.idKey(r.source), r.source])).values()].slice(0, 12), right = [...new Map(pairRows.map(r => [W.idKey(r.target), r.target])).values()].slice(0, 12);
      const value = r => ["distance", "score", "similarity", "value"].map(k => r[k]).find(v => v !== undefined);
      const lookup = new Map(pairRows.map(r => [W.idKey(r.source) + "/" + W.idKey(r.target), r]));
      begin("Pair matrix · up to 12 × 12 entities");
      const table = node("table"), head = node("tr"); head.append(node("th", {}, "From / to")); right.forEach(id => head.append(node("th", {}, W.idLabel(id)))); table.append(head);
      for (const a of left) { const tr = node("tr"); tr.append(node("th", {}, W.idLabel(a))); for (const b of right) { const row = lookup.get(W.idKey(a) + "/" + W.idKey(b)); const td = node("td", {}, row ? String(value(row) ?? (Object.hasOwn(row, "distance") ? "unreachable" : "returned")) : "—"); td.title = row ? W.stringify(row) : "Not returned"; tr.append(td); } table.append(tr); } block.append(table);
    } else if (["samples", "spectrum", "intervals", "locations"].includes(spec.kind)) {
      begin(spec.title);
      const svg = svgNode("svg", {viewBox: "0 0 540 260", role: spec.kind === "locations" ? "group" : "img", "aria-label": spec.title});
      svg.append(svgNode("line", {x1: 35, y1: 225, x2: 520, y2: 225, stroke: "#687e70"}));
      if (spec.kind === "intervals") {
        const intervals = rows.filter(r => numeric(r.birth) !== null).slice(0, 60);
        const finite = intervals.flatMap(r => [r.birth, r.death]).filter(v => numeric(v) !== null);
        const low = Math.min(0, ...finite), high = Math.max(1, ...finite), x = v => 40 + (v - low) / (high - low || 1) * 460;
        intervals.forEach((r, i) => { const y = 15 + i / Math.max(1, intervals.length) * 195, line = svgNode("line", {x1: x(r.birth), x2: numeric(r.death) === null ? 515 : x(r.death), y1: y, y2: y, stroke: "#478663", "stroke-width": 3}); const title = svgNode("title"); title.textContent = W.stringify(r); line.append(title); svg.append(line); });
        block.append(node("p", {}, `Filtration range ${low}–${high}. Intervals without a finite death extend to the right boundary.`));
      } else if (spec.kind === "locations") {
        const points = rows.map((r, i) => ({r, i, x: r.location?.longitude ?? r.longitude ?? r.coordinates?.[0], y: r.location?.latitude ?? r.latitude ?? r.coordinates?.[1]})).filter(p => numeric(p.x) !== null && numeric(p.y) !== null);
        const xs = points.map(p => p.x), ys = points.map(p => p.y), minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
        for (const p of points.slice(0, 500)) {
          const description = W.stringify(p.r);
          const dot = svgNode("circle", {cx: 40 + (p.x - minX) / (maxX - minX || 1) * 460, cy: 215 - (p.y - minY) / (maxY - minY || 1) * 190,
            r: 4, fill: "#478663", tabindex: 0, role: "button", "aria-label": description, "data-location-index": p.i});
          const title = svgNode("title"); title.textContent = description; dot.append(title);
          dot.onclick = () => { void select(p.i); };
          dot.onkeydown = event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); void select(p.i); } };
          svg.append(dot);
        }
        block.append(node("p", {}, "Coordinate plot: horizontal longitude/X, vertical latitude/Y. Inspect exact values and confidence in the table."));
      } else {
        let values = rows.map(r => numeric(typeof r === "object" ? r.eigenvalue ?? r.value ?? r.statistic : r)).filter(v => v !== null);
        if (spec.kind === "samples" && values.length) { const min = Math.min(...values), max = Math.max(...values), bins = new Array(12).fill(0); values.forEach(v => bins[Math.min(11, Math.floor((v - min) / (max - min || 1) * 12))]++); block.append(node("p", {}, `12 equal-width bins from ${min} to ${max}; height is sample count.`)); values = bins; }
        const shown = values.slice(0, 60), maximum = Math.max(1, ...shown.map(Math.abs));
        shown.forEach((v, i) => { const height = Math.abs(v) / maximum * 190, rect = svgNode("rect", {x: 40 + i * 470 / Math.max(1, shown.length), y: 220 - height, width: Math.max(1, 450 / Math.max(1, shown.length)), height, fill: v < 0 ? "#dd8050" : "#478663"}); const title = svgNode("title"); title.textContent = String(v); rect.append(title); svg.append(rect); });
        if (spec.kind === "spectrum") block.append(node("p", {}, "Eigenvalues in returned order. Bar height shows magnitude; orange marks negative values."));
      }
      block.append(svg);
    } else if (spec.kind === "scores" && ["entity_ranking", "vertex_signal", "edge_scores"].includes(port.type)) {
      begin(port.type === "entity_ranking" ? "Ranked anomaly scores" : port.type === "vertex_signal" ? "Estimated signal" : "Edge scores");
      const scored = rows.map((row, index) => ({row, index, value: row.score ?? (Array.isArray(row.value) ? row.value[0] : row.value)})).filter(r => numeric(r.value) !== null).sort((a, b) => b.value - a.value).slice(0, 20);
      const max = Math.max(1, ...scored.map(r => Math.abs(r.value)));
      for (const r of scored) {
        const button = node("button", {class: "bar-row", type: "button"}), track = node("span", {class: "bar-track"}), fill = node("span", {class: "bar-fill"});
        fill.style.display = "block"; fill.style.width = `${Math.abs(r.value) / max * 100}%`; if (r.value < 0) fill.style.backgroundColor = "#dd8050"; track.append(fill);
        button.append(node("span", {class: "bar-label"}, W.idLabel(r.row.vertex ?? r.row.entity ?? r.row.edge ?? r.index)), track, node("span", {}, String(r.value)));
        button.onclick = () => { void select(r.index); }; block.append(button);
      }
      block.append(node("p", {}, "Highest values among loaded rows. Vector signals show their first component; the table retains every component and anomaly explanation."));
    } else if (spec.kind === "flow") {
      begin("Flow and minimum cut");
      const raw = result.result || {};
      for (const key of ["flow_value", "cut_capacity", "min_cut_edges", "min_cut_vertices", "source_side", "sink_side"]) if (raw[key] !== undefined) block.append(node("p", {}, `${key.replaceAll("_", " ")}: ${W.stringify(raw[key])}`));
      block.append(node("p", {}, "The graph shows positive flow. Cut membership and capacities above refer to this saved analysis."));
    } else if (["instances", "bipartite", "subgraph", "vertices", "edges", "colors", "graph"].includes(spec.kind)) {
      begin(spec.title);
      if (spec.kind === "instances") block.append(node("p", {}, "Choose a recorded occurrence by its item number. The graph shows its members; temporal occurrences retain only their recorded event edges. Count-only runs have no occurrence graph."));
      else if (spec.kind === "bipartite") block.append(node("p", {}, "Left and right sides are arranged in separate columns. Select another item to inspect a different biclique."));
      else if (spec.kind === "colors") block.append(node("p", {}, "Node color represents the assigned color class. The score table records each assignment."));
      else if (spec.kind === "subgraph") block.append(node("p", {}, "Result only shows the returned vertices and their internal edges. Input context highlights these members inside the original network."));
      else if (spec.kind === "edges") block.append(node("p", {}, "Result only shows the returned edges and endpoints. Other input connections are excluded."));
      else if (spec.kind === "vertices") block.append(node("p", {}, "Selected entities are shown without unrequested connections. Input context reveals their surrounding network."));
      else block.append(node("p", {}, "This view uses the returned graph. Generated or aggregated entities need an explicit source mapping before table enrichment is possible."));
      if (spec.kind === "subgraph") for (const [name, value] of Object.entries(result.result || {})) if (numeric(value) !== null) block.append(node("p", {}, `${name.replaceAll("_", " ")}: ${value}`));
    } else if (["mapping", "predictions", "scalar"].includes(spec.kind)) {
      begin(spec.title);
      block.append(node("p", {}, spec.kind === "mapping" ? "Correspondences refer to their respective input graphs. Select source-backed entities through their original input." : spec.kind === "scalar" ? "This calculation returns a count. No individual graph instances were retained." : "Predicted values and model metrics are shown in the table; they are not source-table attributes."));
    }
    if (focusedLocation !== undefined) block.querySelector(`[data-location-index="${focusedLocation}"]`)?.focus({preventScroll: true});
  }
  function decorate() {
    if (state.resultView?.view_spec) return;
    const view = state.resultView, cy = state.cy; if (!view || !cy) return;
    if (view.profile.kind === "colors") {
      const palette = ["#4179b5", "#dd8050", "#499678", "#a765ab", "#c05a6e", "#8b8739", "#4998aa", "#8664bb"];
      for (const row of state.port?.value || []) { const color = row.color ?? row[state.port.score_field || "score"]; if (Number.isInteger(color)) cy.getElementById(W.idKey(row.vertex)).style("background-color", palette[((color % palette.length) + palette.length) % palette.length]); }
    }
    if (view.profile.kind === "bipartite" && !view.context) {
      const row = state.port?.value?.[view.index ?? 0];
      const sides = view.bipartite_sides || [row?.left_vertices ?? row?.left, row?.right_vertices ?? row?.right];
      if (sides.every(Array.isArray)) {
        for (const [side, ids] of sides.entries()) for (const [i, id] of ids.entries()) cy.getElementById(W.idKey(id)).position({x: side * 280, y: i * 65});
        cy.fit(undefined, 40);
      }
    }
  }
  function context() { mode.value = "context"; return load(); }
  function clearSelection() { useSelection = false; renderSelectionChip(); }
  return {load, select, clear, selection, renderBlocks, decorate, context, clearSelection};
};
