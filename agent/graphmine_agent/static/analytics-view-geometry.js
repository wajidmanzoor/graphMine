"use strict";
window.GraphMineViewGeometry = (() => {
  const make = (tag, attrs = {}, text) => { const e = document.createElementNS("http://www.w3.org/2000/svg", tag); for (const [key, value] of Object.entries(attrs)) e.setAttribute(key, String(value)); if (text !== undefined) e.textContent = text; return e; };
  function svg(cy, legend = []) {
    const root = make("svg", {xmlns: "http://www.w3.org/2000/svg", width: cy.width(), height: cy.height(), viewBox: `0 0 ${cy.width()} ${cy.height()}`}), zoom = cy.zoom(), pan = cy.pan();
    const point = p => ({x: p.x * zoom + pan.x, y: p.y * zoom + pan.y}), at = p => `${p.x},${p.y}`, defs = make("defs"); root.append(defs);
    const background = getComputedStyle(cy.container()).backgroundColor;
    root.append(make("rect", {width: "100%", height: "100%", fill: background === "rgba(0, 0, 0, 0)" ? getComputedStyle(document.body).backgroundColor : background}));
    const overlay = cy.container().querySelector(".view-geometry");
    for (const item of overlay?.querySelectorAll(".group-hull") || []) root.append(item.cloneNode(true));
    for (const [index, edge] of [...cy.edges(":visible")].entries()) {
      const a = point(edge.sourceEndpoint()), b = point(edge.targetEndpoint()), controls = (edge.controlPoints() || []).map(point), color = edge.style("line-color"), width = parseFloat(edge.style("width")) * zoom;
      let path = `M ${at(a)} L ${at(b)}`, tangent = a;
      if (controls.length === 1) { path = `M ${at(a)} Q ${at(controls[0])} ${at(b)}`; tangent = controls[0]; }
      else if (controls.length >= 2) { path = `M ${at(a)} C ${at(controls[0])} ${at(controls[1])} ${at(b)}`; tangent = controls[1]; }
      const line = make("path", {d: path, fill: "none", stroke: color, "stroke-width": width, opacity: edge.style("opacity"), "stroke-dasharray": edge.style("line-style") === "dashed" ? "6 4" : edge.style("line-style") === "dotted" ? "2 3" : "none"}); root.append(line);
      if (edge.style("target-arrow-shape") !== "none") {
        const angle = Math.atan2(b.y - tangent.y, b.x - tangent.x), size = 5 + width * 1.5;
        root.append(make("polygon", {points: `${at(b)} ${at({x: b.x - size * Math.cos(angle) + size / 2 * Math.sin(angle), y: b.y - size * Math.sin(angle) - size / 2 * Math.cos(angle)})} ${at({x: b.x - size * Math.cos(angle) - size / 2 * Math.sin(angle), y: b.y - size * Math.sin(angle) + size / 2 * Math.cos(angle)})}`, fill: edge.style("target-arrow-color"), opacity: edge.style("opacity")}));
      }
    }
    for (const n of cy.nodes(":visible")) {
      const p = n.renderedPosition(), w = n.renderedWidth(), h = n.renderedHeight(), style = {fill: n.style("background-color"), stroke: n.style("border-color"), "stroke-width": parseFloat(n.style("border-width")) * zoom, opacity: n.style("opacity")}, shape = n.style("shape");
      let body;
      if (shape === "diamond") body = make("polygon", {...style, points: `${p.x},${p.y - h / 2} ${p.x + w / 2},${p.y} ${p.x},${p.y + h / 2} ${p.x - w / 2},${p.y}`});
      else if (shape === "triangle") body = make("polygon", {...style, points: `${p.x},${p.y - h / 2} ${p.x + w / 2},${p.y + h / 2} ${p.x - w / 2},${p.y + h / 2}`});
      else if (["rectangle", "round-rectangle"].includes(shape)) body = make("rect", {...style, x: p.x - w / 2, y: p.y - h / 2, width: w, height: h, rx: shape === "round-rectangle" ? 5 : 0});
      else body = make("ellipse", {...style, cx: p.x, cy: p.y, rx: w / 2, ry: h / 2});
      body.append(make("title", {}, n.data("fullLabel"))); root.append(body);
      if (n.data("shared") || n.data("original")?.view?.prediction_error) root.append(make("ellipse", {cx: p.x, cy: p.y, rx: w / 2 + 3, ry: h / 2 + 3, fill: "none", stroke: style.stroke, "stroke-width": 1, opacity: style.opacity}));
      if (Number(n.style("text-opacity")) > 0) root.append(make("text", {x: p.x, y: p.y + h / 2 + 17, "text-anchor": "middle", "font-family": "sans-serif", "font-size": 12, fill: n.style("color"), opacity: style.opacity}, n.data("label")));
    }
    for (const item of overlay?.querySelectorAll(".entity-badge,.bipartite-row-label") || []) root.append(item.cloneNode(true));
    if (legend.length) {
      const x = Math.max(8, cy.width() - 230), group = make("g", {id: "export-legend"});
      group.append(make("rect", {x, y: 10, width: 220, height: 30 + legend.length * 19, rx: 6, fill: "white", "fill-opacity": .95, stroke: "#d1ddd8"}), make("text", {x: x + 10, y: 29, "font-family": "sans-serif", "font-size": 12, fill: "#203b43"}, "Legend"));
      legend.forEach((row, index) => {
        const y = 47 + index * 19;
        if (row.color) group.append(make("rect", {x: x + 10, y: y - 10, width: 10, height: 10, rx: 2, fill: row.color}));
        group.append(make("text", {x: x + (row.color ? 27 : 10), y, "font-family": "sans-serif", "font-size": 12, fill: "#203b43"}, row.label));
      }); root.append(group);
    }
    return new XMLSerializer().serializeToString(root);
  }
  function snapshot(host) {
    const rect = host.getBoundingClientRect(), width = Math.max(1, Math.ceil(rect.width)), height = Math.max(1, Math.ceil(rect.height));
    if (width * height > 32000000) throw new Error("This view exceeds the 32-megapixel export budget. Choose a smaller view.");
    const root = make("svg", {xmlns: "http://www.w3.org/2000/svg", width, height, viewBox: `0 0 ${width} ${height}`}), foreign = make("foreignObject", {width, height});
    const clone = host.cloneNode(true), originals = [host, ...host.querySelectorAll("*")], copies = [clone, ...clone.querySelectorAll("*")];
    originals.forEach((original, i) => {
      const copy = copies[i], style = getComputedStyle(original);
      for (const name of style) if (!name.startsWith("--")) copy.style.setProperty(name, style.getPropertyValue(name));
      for (const attr of [...copy.attributes]) if (attr.name.startsWith("on")) copy.removeAttribute(attr.name);
      if (original.tagName === "CANVAS") { const img = document.createElement("img"); img.src = original.toDataURL(); img.setAttribute("style", copy.getAttribute("style")); copy.replaceWith(img); }
    });
    clone.setAttribute("xmlns", "http://www.w3.org/1999/xhtml"); clone.style.margin = "0"; clone.style.width = `${width}px`; foreign.append(clone); root.append(foreign);
    return new XMLSerializer().serializeToString(root);
  }
  async function png(source) {
    const url = URL.createObjectURL(new Blob([source], {type: "image/svg+xml"})), image = new Image();
    try { await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = () => reject(new Error("The SVG could not be rasterized.")); image.src = url; }); const canvas = document.createElement("canvas"); canvas.width = image.width * 2; canvas.height = image.height * 2; canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height); return await new Promise(resolve => canvas.toBlob(resolve)); }
    finally { URL.revokeObjectURL(url); }
  }
  const cross = (a, b, c) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
  function hull(points) {
    points.sort((a, b) => a.x - b.x || a.y - b.y); const lower = [], upper = [];
    for (const p of points) { while (lower.length > 1 && cross(lower.at(-2), lower.at(-1), p) <= 0) lower.pop(); lower.push(p); }
    for (const p of points.slice().reverse()) { while (upper.length > 1 && cross(upper.at(-2), upper.at(-1), p) <= 0) upper.pop(); upper.push(p); }
    return [...lower.slice(0, -1), ...upper.slice(0, -1)];
  }
  function overlay(cy, selected) {
    const container = cy.container(), layer = make("svg", {class: "view-geometry", "aria-hidden": "true"}); container.append(layer);
    let polygon = [], active = false, mode = false;
    const draw = () => {
      layer.setAttribute("viewBox", `0 0 ${cy.width()} ${cy.height()}`); layer.replaceChildren();
      const groups = new Map(); for (const n of cy.nodes(":visible")) { const group = n.data("original")?.view?.group; if (group === undefined || group === null) continue; const key = String(group); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(n); }
      for (const nodes of [...groups.values()].slice(0, 64)) {
        const points = nodes.slice(0, 2000).flatMap(n => { const p = n.renderedPosition(); return [{x: p.x - 24, y: p.y - 24}, {x: p.x + 24, y: p.y - 24}, {x: p.x + 24, y: p.y + 35}, {x: p.x - 24, y: p.y + 35}]; });
        layer.append(make("polygon", {class: "group-hull", points: hull(points).map(p => `${p.x},${p.y}`).join(" "), fill: nodes[0].data("color"), "fill-opacity": .06, stroke: nodes[0].data("color"), "stroke-opacity": .4, "stroke-width": 1}));
      }
      for (const side of cy.scratch("layoutName") === "bipartite" ? [0, 1] : []) {
        const members = cy.nodes(":visible").filter(n => n.data("original")?.view?.side === side && n.data("result"));
        if (!members.length) continue;
        const names = [...new Set(members.map(n => n.data("original").view.vertex_type))], name = names.length === 1 ? names[0] : side ? "Right" : "Left";
        const y = members.reduce((sum, n) => sum + n.renderedPosition().y, 0) / members.length;
        layer.append(make("text", {class: "bipartite-row-label", x: 12, y: Math.max(18, y - 30), "font-size": 12, "font-family": "sans-serif", fill: getComputedStyle(container).color}, `${name.endsWith("s") ? name + "es" : name + "s"} (${members.length})`));
      }
      const visible = cy.nodes(":visible"), count = visible.length;
      for (const n of visible) {
        const p = n.renderedPosition(), data = n.data("original")?.view || {};
        if (data.expanded) layer.append(make("circle", {class: "entity-badge", cx: p.x, cy: p.y, r: n.renderedWidth() / 2 + 4, fill: "none", stroke: n.data("color"), "stroke-width": 2, "stroke-dasharray": "3 2"}));
        const text = n.locked() ? "⌖" : data.more_neighbors ? `+${data.more_neighbors}` : count <= 100 && data.rank > 0 && data.rank <= 10 ? `#${data.rank}` : "";
        if (text) { const badge = make("text", {class: "entity-badge", x: p.x + n.renderedWidth() / 2 + 3, y: p.y - n.renderedHeight() / 2, "font-size": 12, "font-family": "sans-serif", fill: getComputedStyle(container).color, "paint-order": "stroke", stroke: getComputedStyle(document.body).backgroundColor, "stroke-width": 3}, text); badge.append(make("title", {}, n.locked() ? "Pinned" : "Additional saved input neighbors")); layer.append(badge); }
      }
      if (polygon.length) layer.append(make("polyline", {points: polygon.map(p => `${p.x},${p.y}`).join(" "), fill: "#0072b2", "fill-opacity": .1, stroke: "#0072b2", "stroke-width": 2}));
    };
    const point = event => { const rect = container.getBoundingClientRect(); return {x: event.clientX - rect.left, y: event.clientY - rect.top}; };
    const stop = event => { event.preventDefault(); event.stopImmediatePropagation(); };
    const inside = p => { let yes = false; for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) { const a = polygon[i], b = polygon[j]; if ((a.y > p.y) !== (b.y > p.y) && p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x) yes = !yes; } return yes; };
    const down = event => { if (!(mode || event.shiftKey)) return; stop(event); active = true; polygon = [point(event)]; container.setPointerCapture(event.pointerId); };
    const move = event => { if (!active) return; stop(event); const p = point(event), last = polygon.at(-1); if (Math.hypot(p.x - last.x, p.y - last.y) > 4 && polygon.length < 2000) polygon.push(p); draw(); };
    const up = event => { if (!active) return; stop(event); active = false; if (polygon.length >= 3) selected(cy.nodes(":visible").filter(n => inside(n.renderedPosition())).map(n => n.id())); else { const p = point(event); selected(cy.nodes(":visible").filter(n => { const q = n.renderedPosition(); return Math.hypot(q.x - p.x, q.y - p.y) <= n.renderedWidth() / 2 + 5; }).map(n => n.id()), true); } polygon = []; mode = false; draw(); };
    for (const [name, callback] of [["pointerdown", down], ["pointermove", move], ["pointerup", up], ["pointercancel", up]]) container.addEventListener(name, callback, true);
    let scheduled = false; const redraw = () => { if (!scheduled) { scheduled = true; requestAnimationFrame(() => { scheduled = false; if (!cy.destroyed()) draw(); }); } }; cy.on("pan zoom position", redraw); draw();
    cy.one("destroy", () => { for (const [name, callback] of [["pointerdown", down], ["pointermove", move], ["pointerup", up], ["pointercancel", up]]) container.removeEventListener(name, callback, true); layer.remove(); });
    return {lasso: () => { mode = true; }, draw};
  }
  return {svg, snapshot, png, overlay};
})();
