"use strict";
window.GraphMineViewAlternates = ({W, node, charts, label, context, select, overrides, changed}) => {
  const S = window.GraphMineViewStyle; let instances = [], timer = null, epoch = 0;
  function clear() { epoch++; clearInterval(timer); timer = null; instances.forEach(cy => cy.destroy()); instances = []; }
  const control = (host, name, element) => { const l = node("label", {}, name); l.append(element); host.append(l); return element; };
  function scene(host, graph, spec, fixed = null) {
    const canvas = node("div", {class: "comparison-graph", style: "height:440px"}); host.append(canvas);
    const render = S.renderData(W, graph, spec), positions = fixed || new Map((graph.positions || []).map(p => [W.idKey(p.id), p]));
    render.elements.forEach((e, i) => { if (e.data.entity !== undefined) e.position = {...(positions.get(e.data.id) || {x: -180, y: i * 70})}; });
    const cy = window.cytoscape({container: canvas, elements: render.elements, style: S.stylesheet(graph.graph?.directed), layout: {name: positions.size ? "preset" : "circle", animate: false}, minZoom: 1e-6, maxZoom: 20});
    S.fit(cy); cy.on("zoom", () => S.screenSizes(cy)); cy.on("tap", "node", e => select([e.target.data("entity")])); instances.push(cy); return cy;
  }
  const supported = new Set(["eigenvector", "filtration", "visit_heat", "walk", "predicted_edges", "occurrence_overlay", "input_comparison", "cut"]);
  async function render(host, view, choice) {
    if (!supported.has(choice)) return false;
    clear(); const version = epoch; host.replaceChildren(node("p", {}, "Loading the saved input…"));
    const source = await context(); if (version !== epoch) return true;
    host.replaceChildren(); const data = view.chart_data || {}, rows = data.rows || [], spec = view.view_spec;
    if (choice === "cut") {
      if (!data.cut_sides) { host.append(node("p", {class: "view-scope"}, "This calculation did not retain source-side and sink-side memberships. Its positive flow and recorded cut edges remain available in the graph and table.")); return true; }
      const positions = new Map(), sides = new Map(); data.cut_sides.forEach((ids, side) => ids.forEach((id, i) => { positions.set(W.idKey(id), {x: side * 300, y: (i - (ids.length - 1) / 2) * 70}); sides.set(W.idKey(id), side); }));
      scene(host, {...source, vertices: source.vertices.map(v => ({...v, view: {...v.view, side: sides.get(W.idKey(v.id))}}))}, {...spec, nodes: {...spec.nodes, color: {field: "side"}}}, positions);
      host.append(node("p", {class: "view-scope"}, "Recorded source side (left) and sink side (right). Cut edges are orange and dashed; width shows recorded flow."));
    } else if (choice === "eigenvector") {
      const field = control(host, "Recorded eigenvector", node("select")); rows.forEach((r, i) => field.append(node("option", {value: i}, `Eigenvalue ${r.eigenvalue}`)));
      const canvas = node("div"); host.append(canvas); const draw = () => { instances.forEach(c => c.destroy()); instances = []; canvas.replaceChildren(); const row = rows[Number(field.value)], values = new Map((data.vertex_order || []).map((id, i) => [W.idKey(id), row?.eigenvector?.[i]])), finite = [...values.values()].filter(Number.isFinite), bound = Math.max(1e-12, ...finite.map(Math.abs));
        scene(canvas, {...source, vertices: source.vertices.map(v => ({...v, view: {...v.view, score: values.get(W.idKey(v.id))}}))}, {...spec, nodes: {...spec.nodes, size: {value: 24}, lightness: {field: "score", scale: "diverging", domain: [-bound, bound]}}}); overrides().eigenvector = Number(field.value); changed(); };
      field.value = String(overrides().eigenvector || 0); field.onchange = draw; draw(); host.append(node("p", {class: "view-scope"}, "Colors use the retained eigenvector and its explicit vertex order. The sign of an eigenvector is arbitrary; missing entries remain uncolored."));
    } else if (choice === "filtration") {
      const unique = new Map(); for (const edge of source.edges) { const key = [W.idKey(edge.source), W.idKey(edge.target)].sort().join("\u0000"), previous = unique.get(key); if (typeof edge.weight === "number" && (!previous || edge.weight < previous.weight)) unique.set(key, edge); }
      const weights = [...new Set([...unique.values()].map(e => e.weight))].sort((a, b) => a - b), range = control(host, "Filtration threshold", node("input", {type: "range", min: 0, max: Math.max(0, weights.length - 1), step: 1})), caption = node("p", {role: "status"}); range.value = String(weights.length - 1);
      if (Number.isFinite(overrides().filtration)) { const i = weights.findLastIndex(v => v <= overrides().filtration); range.value = String(Math.max(0, i)); }
      const cy = scene(host, {...source, edges: [...unique.values()]}, spec); host.append(caption); range.oninput = () => { const value = weights[Number(range.value)]; cy.edges().forEach(e => e.toggleClass("view-hidden", e.data("original").weight > value)); caption.textContent = `Edges with filtration weight ≤ ${value ?? "unavailable"}. Parallel records use their minimum weight. This displays the graph skeleton; it does not recalculate homology.`; overrides().filtration = value ?? null; changed(); }; range.oninput();
    } else if (choice === "visit_heat" || choice === "walk") {
      const visits = new Map((data.visits || []).map(r => [W.idKey(r.vertex), r.count])), counts = [...visits.values()], high = Math.max(1, ...counts), graph = {...source, vertices: source.vertices.map(v => ({...v, view: {...v.view, score: visits.get(W.idKey(v.id)) || 0}}))};
      const cy = scene(host, graph, {...spec, nodes: {...spec.nodes, size: {field: "score", scale: "sqrt"}, lightness: {field: "score", scale: "sequential", domain: [0, high]}}});
      host.append(node("p", {class: "view-scope"}, `Visit counts use at most ${data.visit_scan_limit || 10000} retained walk steps. Repeated visits count separately.`));
      if (choice === "walk") { const walk = rows[view.index || 0] || [], range = control(host, "Recorded walk step", node("input", {type: "range", min: 0, max: Math.max(0, walk.length - 1), step: 1})), status = node("p", {role: "status"}), play = node("button", {type: "button"}, "Play recorded walk"); range.value = "0"; host.append(play, status);
        range.oninput = () => { const i = Number(range.value), id = walk[i]; cy.nodes().forEach(n => n.toggleClass("chosen", n.id() === W.idKey(id))); select(id === undefined ? [] : [id]); status.textContent = `Step ${i + 1} of ${walk.length}: ${id === undefined ? "No retained steps" : label(id)}`; };
        play.onclick = () => { if (timer) { clearInterval(timer); timer = null; play.textContent = "Play recorded walk"; return; } range.value = "0"; play.textContent = "Stop"; timer = setInterval(() => { range.oninput(); if (+range.value >= +range.max) { clearInterval(timer); timer = null; play.textContent = "Play recorded walk"; } else range.value = String(+range.value + 1); }, 650); }; range.oninput(); }
    } else if (choice === "predicted_edges") {
      if (view.profile_facts?.operation !== "link-prediction") throw new Error("This output does not declare predicted relationships.");
      const edges = rows.slice().sort((a, b) => b.score - a.score).slice(0, 200).map((r, i) => ({id: "prediction:" + i, source: r.source, target: r.target, weight: r.score, view: {edge_role: "derived", relationship_type: "Predicted relationship", weight: r.score}})), ids = new Set(source.vertices.map(v => W.idKey(v.id)));
      scene(host, {...source, edges: edges.filter(e => ids.has(W.idKey(e.source)) && ids.has(W.idKey(e.target)))}, spec); host.append(node("p", {class: "view-scope"}, "Dashed connections are the top 200 loaded link predictions. They are not recorded input edges."));
    } else if (choice === "occurrence_overlay") {
      const ids = new Set(); let count = 0; memberships: for (const row of rows) for (const id of (Array.isArray(row) ? row : row.vertices || [])) { if (++count > 100000) break memberships; ids.add(W.idKey(typeof id === "object" ? id.data_vertex : id)); }
      scene(host, {...source, vertices: source.vertices.map(v => ({...v, view: {...v.view, result: ids.has(W.idKey(v.id))}}))}, spec); host.append(node("p", {class: "view-scope"}, "Highlighting members of the loaded occurrences. Connections show saved input context; select an individual occurrence for its exact witness."));
    } else if (choice === "input_comparison") {
      const grid = node("div", {class: "view-comparison"}); host.append(grid);
      for (const [name, graph] of [["Saved input", source], ["Returned graph", view]]) { const panel = node("section"); panel.append(node("h3", {}, name)); grid.append(panel); scene(panel, graph, graph.view_spec); }
      host.append(node("p", {class: "view-scope"}, "Input and returned graph are separate snapshots. Coarsened or generated identifiers do not imply source entity identity."));
    }
    return true;
  }
  return {render, clear, supported};
};
