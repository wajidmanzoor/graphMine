"use strict";
window.GraphMineProjectViewer = (() => {
  const W = window.AnalyticsWire;
  const node = (tag, attrs = {}, text) => { const el = document.createElement(tag); for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value); if (text !== undefined) el.textContent = text; return el; };
  function show(container, item) {
    container.replaceChildren(node("h2", {}, item.name));
    const snapshot = item.snapshot, graph = snapshot.view_data || (snapshot.kind === "graph" ? snapshot.data : snapshot.kind === "workflow" ? Object.values(snapshot.result.steps || {}).flatMap(s => Object.values(s.result?.ports || {})).find(p => p.type === "graph")?.value || Object.values(snapshot.inputs || {}).find(i => i.kind === "graph")?.data : null);
    container.append(node("p", {class: "muted"}, `Shared ${item.kind.replaceAll("_", " ")} snapshot · ${new Date(item.created_at).toLocaleString()}`));
    let cy, alternatives, aggregate, layout = "cose";
    if (graph?.vertices?.length && graph?.edges) {
      const vertices = graph.vertices.slice(0, window.GraphMineViewStyle.canWebGL(graph) ? 50000 : 2000), ids = new Set(vertices.map(v => W.idKey(v.id))), edges = graph.edges.filter(e => ids.has(W.idKey(e.source)) && ids.has(W.idKey(e.target))).slice(0, 5000);
      const graphNode = node("div", {id: "project-graph", style: "height:420px", "aria-label": "Shared graph preview"}), choices = node("select", {id: "project-layout", "aria-label": "Graph layout"});
      for (const [id, name] of [["cose", "Spread connections"], ["circle", "Circle"], ["grid", "Grid"]]) choices.append(node("option", {value: id}, name));
      const detail = node("p", {id: "project-selection", class: "muted", role: "status"}, "Choose vertices to save a selection.");
      container.append(choices, graphNode, detail, node("p", {class: "muted"}, `${vertices.length} of ${graph.vertices.length} vertices and ${edges.length} of ${graph.edges.length} connections shown. The download retains the full snapshot.`));
      cy = window.cytoscape({container: graphNode, minZoom: 1e-6, maxZoom: 20, webgl: vertices.length > 2000 && window.GraphMineViewStyle.canWebGL(graph), elements: [...vertices.map(v => ({data: {id: W.idKey(v.id), entity: v.id, label: v.label || W.idLabel(v.id)}})), ...edges.map((e, i) => ({data: {id: `edge:${i}`, source: W.idKey(e.source), target: W.idKey(e.target)}}))], style: [{selector: "node", style: {label: "data(label)", "font-size": 12, "background-color": "#72a98f"}}, {selector: ":selected", style: {"background-color": "#e99040", "border-width": 3, "border-color": "#194837"}}, {selector: "edge", style: {width: 2, "curve-style": "bezier", "target-arrow-shape": graph.graph.directed ? "triangle" : "none"}}], layout: {name: layout, animate: false}, selectionType: "additive"});
      choices.onchange = () => { layout = choices.value; cy.layout({name: layout, animate: false}).run(); };
      cy.on("select unselect", "node", () => { detail.textContent = cy.$("node:selected").map(n => W.idLabel(n.data("entity"))).join(", ") || "No vertices selected."; });
      if (snapshot.view && graph.view_spec) {
        const saved = snapshot.view, style = window.GraphMineViewStyle, render = style.renderData(W, {...graph, vertices, edges}, saved.view_spec || graph.view_spec, saved.overrides), positions = new Map((saved.viewport?.positions || []).map(p => [W.idKey(p.id), p]));
        cy.batch(() => { for (const e of render.elements) { const target = cy.getElementById(e.data.id); target.data(e.data); if (positions.has(e.data.id)) target.position({...positions.get(e.data.id)}); } cy.style(style.stylesheet(graph.graph?.directed)); });
        const hidden = new Set((saved.overrides?.hidden_vertices || []).map(W.idKey));
        cy.nodes().forEach(n => { if (hidden.has(n.id()) || saved.overrides?.hidden_categories?.includes(n.data("category")) || !(saved.overrides?.property_filters || []).filter(r => r.target === "node").every(r => style.passes(n.data("original"), r))) n.addClass("view-hidden"); if (saved.selected_vertices?.some(id => W.idKey(id) === n.id())) n.select(); });
        cy.edges().forEach(e => e.toggleClass("view-hidden", e.source().hasClass("view-hidden") || e.target().hasClass("view-hidden") || !(saved.overrides?.property_filters || []).filter(r => r.target === "edge").every(r => style.passes(e.data("original"), r))));
        if (saved.viewport && vertices.length === graph.vertices.length) cy.viewport({zoom: saved.viewport.zoom, pan: {...saved.viewport.pan}}); else style.fit(cy);
        for (const id of saved.pinned || []) cy.getElementById(W.idKey(id)).lock();
        const selected = new Set((saved.selected_vertices || []).map(W.idKey)); cy.nodes().forEach(n => n.toggleClass("chosen", selected.has(n.id())));
        style.screenSizes(cy, selected); cy.on("zoom", () => style.screenSizes(cy, selected)); window.GraphMineViewGeometry?.overlay(cy, ids => ids.forEach(id => cy.getElementById(id).select()));
        detail.textContent = "Shared view: saved positions, styles, filters, and selection. The download includes the complete view specification.";
      }
    }
    if (snapshot.view_data?.view_spec) {
      const host = node("div"), linked = node("div"), view = snapshot.view_data, labels = new Map([...(view.labels || []), ...view.vertices].map(v => [W.idKey(v.id), v.label || W.idLabel(v.id)]));
      const charts = window.GraphMineViewCharts({W, node, label: id => labels.get(W.idKey(id)) || W.idLabel(id), select: item => { if (!cy) return; cy.nodes().unselect(); for (const id of item.ids || []) cy.getElementById(W.idKey(id)).select(); }});
      const primary = snapshot.view?.overrides?.primary || snapshot.view?.view_spec?.view || view.view_spec.view;
      if (!["graph", "result_only", "concentric", "grid", "radial"].includes(primary)) {
        container.querySelector("#project-graph")?.setAttribute("hidden", "");
        container.querySelector("#project-layout")?.setAttribute("hidden", "");
        const select = ids => { if (!cy) return; cy.nodes().unselect(); ids.forEach(id => cy.getElementById(W.idKey(id)).select()); };
        alternatives = window.GraphMineViewAlternates?.({W, node, charts, label: id => labels.get(W.idKey(id)) || W.idLabel(id), context: async () => snapshot.view_context, select, overrides: () => snapshot.view.overrides, changed: () => {}});
        if (primary === "pca" && snapshot.view_projection) { charts.scatter(host, "Saved PCA projection", snapshot.view_projection.points.map(p => ({...p, ids: p.entity === null ? [] : [p.entity], label: labels.get(W.idKey(p.entity)) || W.idLabel(p.entity)}))); host.append(node("p", {}, snapshot.view_projection.note)); }
        else if (primary === "meta_graph" && snapshot.view_aggregate) {
          const canvas = node("div", {class: "comparison-graph"}); host.append(canvas); queueMicrotask(() => { const data = snapshot.view_aggregate, style = window.GraphMineViewStyle, rendering = style.renderData(W, data, {nodes: {color: {field: "attributes.group"}, size: {field: "attributes.size", scale: "sqrt"}}}); aggregate = window.cytoscape({container: canvas, elements: rendering.elements, style: style.stylesheet(data.graph.directed), layout: {name: "circle"}, minZoom: 1e-6, maxZoom: 20}); style.fit(aggregate); aggregate.on("zoom", () => style.screenSizes(aggregate)); });
        } else if (alternatives?.supported.has(primary) && snapshot.view_context) { void alternatives.render(host, view, primary).catch(error => host.append(node("p", {role: "status"}, error.message))); }
        else { charts.renderPrimary(host, view, primary === "map" ? "coordinates" : primary); if (primary === "map") host.append(node("p", {}, "Shared geographic coordinates. Map tiles depend on the viewer's configured provider.")); }
      }
      charts.renderLinked(linked, view); container.append(host, linked);
    }
    const download = node("button", {type: "button", id: "download-shared", class: "secondary"}, "Download full snapshot");
    download.onclick = () => { const url = URL.createObjectURL(new Blob([W.stringify(snapshot, true)], {type: "application/json"})); const a = node("a", {href: url, download: "graphmine-shared-snapshot.json"}); a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
    const raw = W.stringify(snapshot, true), details = node("details"); details.append(node("summary", {}, "Snapshot data and plan"), node("pre", {}, `SHA-256 ${item.sha256}\n\n${raw.slice(0, 12000)}${raw.length > 12000 ? "\nPreview excerpt. Download the full snapshot for all records." : ""}`)); container.append(download, details);
    return {
      destroy: () => { cy?.destroy(); alternatives?.clear(); aggregate?.destroy(); },
      capture: () => ({layout, selected: cy ? cy.$("node:selected").map(n => n.data("entity")) : [], positions: cy ? cy.nodes().map(n => ({vertex: n.data("entity"), ...n.position()})) : []}),
      apply: view => { if (!cy) return; layout = view.layout; container.querySelector("#project-layout").value = layout; cy.nodes().unselect(); for (const id of view.selected) cy.getElementById(W.idKey(id)).select(); const positions = new Map(view.positions.map(p => [W.idKey(p.vertex), p])); if (positions.size) { cy.nodes().positions(n => ({...(positions.get(n.id()) || n.position())})); cy.fit(); } else cy.layout({name: layout, animate: false}).run(); },
    };
  }
  return {node, show};
})();
