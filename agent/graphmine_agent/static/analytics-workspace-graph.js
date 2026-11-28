"use strict";
window.GraphMineWorkspaceGraph = ({node, W, canvas, controls, details, schema = false}) => {
  const select = node("select", {"aria-label": schema ? "Schema layout" : "Graph layout"});
  for (const [value, text] of [["cose", "Spread"], ["circle", "Circular"], ["bipartite", "Bipartite"], ["grid", "Grid"], ["concentric", "Concentric"], ["breadthfirst", "Hierarchy"]]) select.append(node("option", {value}, text));
  const fit = node("button", {type: "button", class: "quiet"}, "Fit view");
  const note = node("span", {class: "source-hint", role: "status"});
  controls.append(select, fit, note);
  let cy = null, revision = 0, graph = null;
  function arrange() {
    if (!cy) return;
    note.textContent = "";
    if (select.value === "bipartite") {
      const colors = new Map(), neighbors = new Map(cy.nodes().map(n => [n.id(), []]));
      for (const edge of cy.edges()) { neighbors.get(edge.source().id()).push(edge.target().id()); neighbors.get(edge.target().id()).push(edge.source().id()); }
      for (const n of cy.nodes()) {
        if (colors.has(n.id())) continue;
        colors.set(n.id(), 0); const queue = [n.id()];
        for (let i = 0; i < queue.length; i++) for (const next of neighbors.get(queue[i])) {
          if (!colors.has(next)) { colors.set(next, 1 - colors.get(queue[i])); queue.push(next); }
          else if (colors.get(next) === colors.get(queue[i])) {
            select.value = "cose"; arrange();
            note.textContent = "This graph has an odd cycle; showing Spread instead of Bipartite."; return;
          }
        }
      }
      const counts = [0, 0], gap = schema ? 145 : 70;
      cy.nodes().positions(n => ({x: colors.get(n.id()) * (schema ? 500 : 340), y: counts[colors.get(n.id())]++ * gap}));
      cy.fit(undefined, 40); return;
    }
    cy.layout({name: select.value, animate: false, randomize: true, padding: 40, fit: true, nodeDimensionsIncludeLabels: true,
      nodeRepulsion: () => schema ? 800000 : 12000, idealEdgeLength: () => schema ? 250 : 90, directed: Boolean(graph?.graph?.directed)}).run();
  }
  async function draw(value) {
    const current = ++revision; graph = value; cy?.destroy(); cy = null; canvas.replaceChildren(); details.replaceChildren();
    if (!value.vertices.length) return;
    await window.GraphMineGraphLibrary();
    if (current !== revision || !canvas.isConnected) return;
    const palette = ["#35775c", "#5276a7", "#a66a39", "#82599b", "#39838a", "#ae5f72"], types = [...new Set(value.vertices.map(v => v.type || "Node"))];
    const caption = v => schema ? `${v.label || v.type}\n${(v.attributes?.properties || []).slice(0, 6).map(p => p.name).join("\n")}${v.attributes?.properties?.length > 6 ? "\n…" : ""}` : v.label || v.type || String(v.id);
    cy = window.cytoscape({container: canvas, maxZoom: schema ? 1.5 : 3, elements: [
      ...value.vertices.map(v => ({data: {id: W.idKey(v.id), label: caption(v), original: v, color: palette[types.indexOf(v.type || "Node") % palette.length]}})),
      ...value.edges.map((e, i) => ({data: {id: `edge:${i}`, source: W.idKey(e.source), target: W.idKey(e.target), label: e.type || "", original: e}}))
    ], style: [
      {selector: "node", style: {label: "data(label)", "background-color": "data(color)", color: schema ? "#fff" : "#234638", "font-size": schema ? 12 : 11,
        "text-wrap": "wrap", "text-max-width": 190, "text-valign": schema ? "center" : "bottom", "text-margin-y": schema ? 0 : 6,
        shape: schema ? "round-rectangle" : "ellipse", width: schema ? 200 : 28, height: schema ? 130 : 28}},
      {selector: "edge", style: {label: "data(label)", "font-size": 9, "text-background-color": "#fff", "text-background-opacity": .85, "text-background-padding": 2,
        "target-arrow-shape": value.graph.directed ? "triangle" : "none", "curve-style": "bezier", width: 1.5, "line-color": "#a4bdae", "target-arrow-color": "#809f8d"}},
      {selector: ":selected", style: {"border-width": 3, "border-color": "#d89532", "line-color": "#d89532", "target-arrow-color": "#d89532"}}
    ], layout: {name: "preset"}});
    cy.on("tap", "node, edge", event => {
      const value = event.target.data("original"), heading = node("strong", {}, value.label || value.type || String(value.id));
      details.replaceChildren(heading, node("pre", {}, W.stringify(value.attributes || {}, true)));
    });
    details.append(node("p", {class: "source-hint"}, schema ? "Select a label or relationship to inspect its properties. Drag to arrange; scroll to zoom." : "Select a node or edge to inspect its attributes, including generated summaries."));
    requestAnimationFrame(() => { if (current === revision) { cy?.resize(); arrange(); } });
  }
  select.onchange = arrange; fit.onclick = () => cy?.fit(undefined, 40);
  return {draw, resize: () => cy?.resize(), reset() { revision++; cy?.destroy(); cy = null; canvas.replaceChildren(); details.replaceChildren(); note.textContent = ""; },
    destroy() { revision++; cy?.destroy(); cy = null; }, label(property) { cy?.nodes().forEach(n => { const v = n.data("original"); n.data("label", String(v.attributes?.[property] ?? v.label ?? v.type ?? v.id)); }); }};
};
