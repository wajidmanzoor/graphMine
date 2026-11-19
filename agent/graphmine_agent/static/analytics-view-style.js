"use strict";
// Renderer adapter for a server-owned ViewSpec. No model-generated expressions.
window.GraphMineViewStyle = (() => {
  const token = (name, fallback) => typeof getComputedStyle === "function" ? getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback : fallback;
  const palette = () => Array.from({length: 8}, (_, i) => token(`--graph-category-${i + 1}`, ["#0072b2", "#d55e00", "#009e73", "#cc79a7", "#e69f00", "#56b4e9", "#7465a8", "#76722e"][i]));
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const field = (record, path) => {
    if (!path) return null;
    if (Object.hasOwn(record?.view || {}, path)) return record.view[path];
    let value = record;
    for (const part of path.split(".")) { if (["__proto__", "prototype", "constructor"].includes(part) || !value || typeof value !== "object" || !Object.hasOwn(value, part)) return null; value = value[part]; }
    return value;
  };
  function fraction(value, low, high, scale = "linear") {
    if (![value, low, high].every(finite)) return .5;
    if (high === low) return .5;
    const transform = x => scale === "symlog" ? Math.sign(x) * Math.log1p(Math.abs(x)) : scale === "log1p" ? Math.log1p(Math.max(0, x)) : x;
    const a = transform(low), b = transform(high), x = transform(value);
    const result = Math.max(0, Math.min(1, (x / 2 - a / 2) / (b / 2 - a / 2)));
    return scale === "sqrt" ? Math.sqrt(result) : result;
  }
  function categories(records, key, W) {
    const counts = new Map();
    for (const row of records) { const value = field(row, key) ?? "Unspecified", id = W.stringify(value); const previous = counts.get(id); counts.set(id, {value, count: (previous?.count || 0) + 1}); }
    const rows = [...counts].sort((a, b) => b[1].count - a[1].count || a[0].localeCompare(b[0]));
    const colors = palette(), mapping = new Map();
    rows.forEach(([key, value], i) => mapping.set(key, {...value, color: rows.length > 8 && i >= 7 ? token("--graph-other", "#858b94") : colors[i % 8]}));
    return mapping;
  }
  function renderData(W, source, spec, overrides = {}) {
    const nodes = source.vertices || [], edges = source.edges || [];
    const rules = overrides.style_rules || [];
    const channel = (target, name, fallback) => rules.find(r => r.target === target && r.channel === name) || fallback || {};
    const color = channel("node", "color", spec?.nodes?.color), size = channel("node", "size", spec?.nodes?.size), label = channel("node", "label", spec?.nodes?.label);
    const shape = channel("node", "shape", spec?.nodes?.shape), shapeValues = [...categories(nodes, shape.field || "role", W).keys()], shapes = ["ellipse", "diamond", "rectangle", "triangle"];
    const shapeMap = new Map((shape.categories || []).map(row => [W.stringify(row.value), row.shape]));
    const edgeColor = channel("edge", "color", spec?.edges?.color), edgeWidth = channel("edge", "width", spec?.edges?.width);
    const members = nodes.filter(v => v.view?.result !== false);
    const colors = categories(members, color.field || "vertex_type", W), edgeColors = categories(edges, edgeColor.field || "relationship_type", W);
    for (const row of color.categories || []) colors.set(W.stringify(row.value), {...row, count: colors.get(W.stringify(row.value))?.count || 0});
    const values = nodes.map(v => field(v, size.field)).filter(finite), weights = edges.map(e => field(e, edgeWidth.field)).filter(finite);
    const domain = values.length ? values.reduce((range, v) => [Math.min(range[0], v), Math.max(range[1], v)], [Infinity, -Infinity]) : [0, 0];
    const edgeDomain = weights.length ? weights.reduce((range, v) => [Math.min(range[0], v), Math.max(range[1], v)], [Infinity, -Infinity]) : [0, 0];
    const edgeColorDomain = edges.map(e => field(e, edgeColor.field)).filter(finite).reduce((range, v) => [Math.min(range[0], v), Math.max(range[1], v)], [Infinity, -Infinity]);
    const ramp = (record, encoding, low, high, normal) => {
      const value = field(record, encoding.field);
      if (encoding.mode === "single") return W.stringify(value) === W.stringify(encoding.equals) ? encoding.color || palette()[0] : token("--graph-context", "#b5bbc4");
      if (encoding.mode === "range" || encoding.scale === "sequential" || encoding.scale === "diverging") {
        const ratio = fraction(value, low, high, encoding.scale);
        if (!finite(value)) return token("--graph-other", "#858b94");
        if (encoding.scale === "diverging" || low < 0 && high > 0) { const strength = Math.min(1, Math.abs(value) / Math.max(Math.abs(low), Math.abs(high), 1e-300)); return `hsl(${value < 0 ? 24 : 206} ${strength * 70}% ${94 - strength * 57}%)`; }
        return `hsl(206 65% ${82 - ratio * 45}%)`;
      }
      return normal;
    };
    const colorValues = nodes.map(v => field(v, color.field)).filter(finite);
    const colorDomain = colorValues.reduce((range, v) => [Math.min(range[0], v), Math.max(range[1], v)], [Infinity, -Infinity]);
    const elements = nodes.map(v => {
      const info = v.view || {}, value = field(v, size.field), bucket = colors.get(W.stringify(field(v, color.field || "vertex_type") ?? "Unspecified"));
      const name = String(field(v, label.field) ?? v.label ?? v.attributes?.name ?? v.attributes?.display_name ?? v.id);
      let fill = ramp(v, color, ...colorDomain, bucket?.color || palette()[0]);
      if (!rules.some(r => r.target === "node" && r.channel === "color") && spec?.nodes?.lightness && finite(info.score)) {
        const [low, high] = spec.nodes.lightness.domain;
        fill = ramp(v, spec.nodes.lightness, low, high, fill);
      }
      if (info.result === false) fill = token("--graph-context", "#b5bbc4");
      return {data: {id: W.idKey(v.id), entity: v.id, original: v, label: name.length > 18 ? name.slice(0, 17) + "…" : name,
        fullLabel: name, color: fill, size: size.mode === "single" ? W.stringify(value) === W.stringify(size.equals) ? 36 : 14 : finite(value) ? 14 + 22 * fraction(value, ...domain, size.scale || "sqrt") : 24,
        shape: shape.mode === "single" ? W.stringify(field(v, shape.field)) === W.stringify(shape.equals) ? "diamond" : "ellipse" : shape.value || shapeMap.get(W.stringify(field(v, shape.field))) || (shape.field && shape.field !== "role" ? shapes[Math.max(0, Math.min(3, shapeValues.indexOf(W.stringify(field(v, shape.field) ?? "Unspecified"))))] : ["source", "endpoint"].includes(info.role) ? "diamond" : info.role === "sink" ? "rectangle" : info.role === "cut_vertex" ? "triangle" : "ellipse"), predictionError: Boolean(info.prediction_error),
        result: info.result !== false, category: W.stringify(field(v, color.field || "vertex_type") ?? "Unspecified"), shared: Boolean(info.shared)}};
    });
    edges.forEach((e, index) => elements.push({data: {id: `edge:${index}`, source: W.idKey(e.source), target: W.idKey(e.target), original: e,
      color: e.view?.cut ? token("--graph-category-2", "#d55e00") : ramp(e, edgeColor, ...edgeColorDomain, edgeColors.get(W.stringify(field(e, edgeColor.field || "relationship_type") ?? "Unspecified"))?.color || token("--graph-edge", "#8c96a3")),
      width: edgeWidth.mode === "single" ? W.stringify(field(e, edgeWidth.field)) === W.stringify(edgeWidth.equals) ? 4 : 1 : finite(field(e, edgeWidth.field)) ? 1 + 3 * fraction(field(e, edgeWidth.field), ...edgeDomain, edgeWidth.scale || "sqrt") : 1.5,
      lineStyle: e.view?.cut || e.view?.edge_role === "derived" ? "dashed" : e.view?.edge_role === "context" ? "dotted" : "solid"}}));
    const numericColor = color.mode === "range" ? {field: color.field, domain: colorDomain} : !rules.some(r => r.target === "node" && r.channel === "color") && spec?.nodes?.lightness && nodes.some(v => finite(v.view?.score)) ? spec.nodes.lightness : null;
    return {elements, legend: [...colors.values()].filter(row => row.count), colorRamp: numericColor, edgeLegend: [...edgeColors.values()], shapeLegend: shape.categories?.length ? shape.categories.map(row => ({value: row.label || row.value, shape: row.shape})) : [], colorField: color.field, sizeField: size.field};
  }
  function stylesheet(directed) {
    return [
      {selector: "node", style: {"background-color": "data(color)", "border-color": token("--graph-paper", "#ffffff"), "border-width": 2, width: "data(size)", height: "data(size)", shape: "data(shape)", label: "data(label)", "font-size": 12, color: token("--graph-ink", "#253648"), "text-valign": "bottom", "text-margin-y": 6, "text-background-color": token("--graph-paper", "#ffffff"), "text-background-opacity": .9, "text-background-padding": 2}},
      {selector: "edge", style: {width: "data(width)", "line-color": "data(color)", "target-arrow-color": "data(color)", "target-arrow-shape": directed ? "triangle" : "none", "curve-style": "bezier", "line-style": "data(lineStyle)", opacity: .65}},
      {selector: "node.chosen", style: {"border-color": token("--graph-ink", "#253648"), "border-width": 3}},
      {selector: "node[!result]", style: {opacity: .25}},
      {selector: "node.shared-member", style: {"border-width": 5, "border-style": "double"}},
      {selector: "node[?shared]", style: {"border-style": "double"}},
      {selector: "node[?predictionError]", style: {"border-style": "double", "border-color": token("--graph-category-2", "#d55e00")}},
      {selector: "node.faded", style: {opacity: .25}},
      {selector: "edge.faded", style: {opacity: .15}},
      {selector: "edge.chosen", style: {opacity: 1, width: 4}},
      {selector: ".view-hidden", style: {display: "none"}},
      {selector: "node.search-match", style: {"underlay-color": token("--graph-category-5", "#e69f00"), "underlay-opacity": .3, "underlay-padding": 7}},
    ];
  }
  function screenSizes(cy, selected = new Set()) {
    if (!cy || cy.destroyed()) return;
    const zoom = cy.zoom(), previous = cy.scratch("viewSizes"), nodes = cy.nodes(), count = nodes.length;
    if (previous?.zoom === zoom && previous.count === count && previous.selected.size === selected.size && [...selected].every(id => previous.selected.has(id))) return;
    const ranked = [...nodes].sort((a, b) => b.data("size") - a.data("size")).slice(0, 20), keys = new Set(ranked.map(n => n.id()));
    cy.scratch("viewSizes", {zoom, count, selected: new Set(selected)});
    cy.batch(() => {
      nodes.forEach(n => {
        const show = count <= 60 || selected.size <= 60 && selected.has(n.id()) || keys.has(n.id());
        n.style({width: (n.data("size") || 24) / zoom, height: (n.data("size") || 24) / zoom, "font-size": 12 / zoom, "text-margin-y": 6 / zoom, "text-background-padding": 2 / zoom,
          "border-width": (n.data("shared") ? 5 : selected.has(n.id()) ? 3 : 2) / zoom, "text-opacity": show ? 1 : 0});
      });
      cy.edges().forEach(e => e.style("width", (e.data("width") || 1.5) / zoom));
    });
  }
  function fitAndClamp(cy) {
    if (!cy?.nodes().length) return;
    const nodes = cy.nodes(":visible"); if (!nodes.length) return;
    cy.fit(nodes, 32);
    cy.zoom(Math.max(.8, Math.min(1.8, cy.zoom())));
    screenSizes(cy);
    cy.center(nodes);
  }
  let graphics;
  function passes(record, filter) {
    const value = field(record, filter.field); if (filter.operator === "exists") return value !== null && value !== undefined;
    if (filter.operator === "contains") return String(value ?? "").toLocaleLowerCase().includes(String(filter.value).toLocaleLowerCase());
    if (filter.operator === "eq") return String(value) === String(filter.value);
    const number = typeof value === "number" ? value : typeof value === "string" ? Date.parse(value) : NaN;
    return Number.isFinite(number) && (filter.operator === "gte" ? number >= filter.value : number <= filter.value);
  }
  function webGLAvailable() { if (graphics !== undefined) return graphics; try { const canvas = document.createElement("canvas"), gl = canvas.getContext("webgl2"); graphics = Boolean(gl); gl?.getExtension("WEBGL_lose_context")?.loseContext(); } catch { graphics = false; } return graphics; }
  function canWebGL(graph) { return webGLAvailable() && (graph.edges || []).every(e => !e.view?.cut && !["derived", "context"].includes(e.view?.edge_role)); }
  return {palette, field, fraction, categories, renderData, stylesheet, screenSizes, fitAndClamp, fit: fitAndClamp, passes, webGLAvailable, canWebGL};
})();
