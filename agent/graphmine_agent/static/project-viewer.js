"use strict";
window.GraphMineProjectViewer = (() => {
  const W = window.AnalyticsWire;
  const node = (tag, attrs = {}, text) => { const el = document.createElement(tag); for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value); if (text !== undefined) el.textContent = text; return el; };
  function show(container, item) {
    container.replaceChildren(node("h2", {}, item.name));
    const snapshot = item.snapshot, graph = snapshot.kind === "graph" ? snapshot.data : snapshot.kind === "workflow" ? Object.values(snapshot.result.steps || {}).flatMap(s => Object.values(s.result?.ports || {})).find(p => p.type === "graph")?.value || Object.values(snapshot.inputs || {}).find(i => i.kind === "graph")?.data : null;
    container.append(node("p", {class: "muted"}, `Shared ${item.kind.replaceAll("_", " ")} snapshot · ${new Date(item.created_at).toLocaleString()}`));
    let cy, layout = "cose";
    if (graph?.vertices && graph?.edges) {
      const vertices = graph.vertices.slice(0, 500), ids = new Set(vertices.map(v => W.idKey(v.id))), edges = graph.edges.filter(e => ids.has(W.idKey(e.source)) && ids.has(W.idKey(e.target))).slice(0, 2000);
      const graphNode = node("div", {id: "project-graph", style: "height:420px", "aria-label": "Shared graph preview"}), choices = node("select", {id: "project-layout", "aria-label": "Graph layout"});
      for (const [id, name] of [["cose", "Spread connections"], ["circle", "Circle"], ["grid", "Grid"]]) choices.append(node("option", {value: id}, name));
      const detail = node("p", {id: "project-selection", class: "muted", role: "status"}, "Choose vertices to save a selection.");
      container.append(choices, graphNode, detail, node("p", {class: "muted"}, `${vertices.length} of ${graph.vertices.length} vertices and ${edges.length} of ${graph.edges.length} connections shown. The download retains the full snapshot.`));
      cy = window.cytoscape({container: graphNode, elements: [...vertices.map(v => ({data: {id: W.idKey(v.id), entity: v.id, label: v.label || W.idLabel(v.id)}})), ...edges.map((e, i) => ({data: {id: `edge:${i}`, source: W.idKey(e.source), target: W.idKey(e.target)}}))], style: [{selector: "node", style: {label: "data(label)", "font-size": 12, "background-color": "#72a98f"}}, {selector: ":selected", style: {"background-color": "#e99040", "border-width": 3, "border-color": "#194837"}}, {selector: "edge", style: {width: 2, "curve-style": "bezier", "target-arrow-shape": graph.graph.directed ? "triangle" : "none"}}], layout: {name: layout, animate: false}, selectionType: "additive"});
      choices.onchange = () => { layout = choices.value; cy.layout({name: layout, animate: false}).run(); };
      cy.on("select unselect", "node", () => { detail.textContent = cy.$("node:selected").map(n => W.idLabel(n.data("entity"))).join(", ") || "No vertices selected."; });
    }
    const download = node("button", {type: "button", id: "download-shared", class: "secondary"}, "Download full snapshot");
    download.onclick = () => { const url = URL.createObjectURL(new Blob([W.stringify(snapshot, true)], {type: "application/json"})); const a = node("a", {href: url, download: "graphmine-shared-snapshot.json"}); a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
    const raw = W.stringify(snapshot, true), details = node("details"); details.append(node("summary", {}, "Snapshot data and plan"), node("pre", {}, `SHA-256 ${item.sha256}\n\n${raw.slice(0, 12000)}${raw.length > 12000 ? "\nPreview excerpt. Download the full snapshot for all records." : ""}`)); container.append(download, details);
    return {
      destroy: () => cy?.destroy(),
      capture: () => ({layout, selected: cy ? cy.$("node:selected").map(n => n.data("entity")) : [], positions: cy ? cy.nodes().map(n => ({vertex: n.data("entity"), ...n.position()})) : []}),
      apply: view => { if (!cy) return; layout = view.layout; container.querySelector("#project-layout").value = layout; cy.nodes().unselect(); for (const id of view.selected) cy.getElementById(W.idKey(id)).select(); const positions = new Map(view.positions.map(p => [W.idKey(p.vertex), p])); if (positions.size) { cy.nodes().positions(n => positions.get(n.id()) || n.position()); cy.fit(); } else cy.layout({name: layout, animate: false}).run(); },
    };
  }
  return {node, show};
})();
