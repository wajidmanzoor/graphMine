"use strict";
window.GraphMineExplorer = {
  install({state, W, node, selectRow}) {
    const $ = id => document.getElementById(id), time = node("details", {id: "time-controls", hidden: true});
    time.append(node("summary", {}, "Explore connections over time"));
    const controls = node("div", {class: "parameter-grid"}), low = node("input", {id: "time-start", type: "range", min: "0", step: "1"}), high = node("input", {id: "time-end", type: "range", min: "0", step: "1"});
    for (const [text, input] of [["First timestamp", low], ["Last timestamp", high]]) { const label = node("label", {}, text); label.append(input); controls.append(label); }
    const untimed = node("input", {type: "checkbox", id: "include-untimed"}); untimed.checked = true;
    const label = node("label", {class: "check"}, "Include connections without timestamps"); label.prepend(untimed);
    const scope = node("p", {id: "time-scope", class: "muted", role: "status"}); time.append(controls, label, scope); $("network").before(time);
    this.clearTime = () => { time.hidden = true; };
    this.timeView = () => {
      const cy = state.cy; if (!cy) return;
      const stamp = edge => {
        const value = edge.data("original")?.timestamp;
        if (typeof value === "bigint" || typeof value === "number" && Number.isFinite(value)) return value;
        if (typeof value === "string") { const parsed = Date.parse(value); if (Number.isFinite(parsed)) return parsed; }
        return null;
      };
      const values = new Map(); for (const edge of cy.edges()) { const value = stamp(edge); if (value !== null) values.set(String(value), {value, label: String(edge.data("original").timestamp)}); }
      const timestamps = [...values.values()].sort((a, b) => a.value < b.value ? -1 : a.value > b.value ? 1 : 0);
      time.hidden = !timestamps.length; if (!timestamps.length) return;
      low.max = high.max = String(timestamps.length - 1); low.value = "0"; high.value = high.max;
      const apply = changed => {
        if (Number(low.value) > Number(high.value)) { if (changed === low) high.value = low.value; else low.value = high.value; }
        const first = timestamps[Number(low.value)], last = timestamps[Number(high.value)]; let shown = 0;
        for (const edge of cy.edges()) { const at = stamp(edge), show = at === null ? untimed.checked : at >= first.value && at <= last.value; edge.style("display", show ? "element" : "none"); if (show) shown++; }
        scope.textContent = `${first.label} to ${last.label}, inclusive · ${shown} of ${cy.edges().length} displayed connections. This filters the current graph preview; calculations and saved results are unchanged.`;
      };
      low.oninput = () => apply(low); high.oninput = () => apply(high); untimed.onchange = () => apply(); apply();
    };
    this.embedding = () => {
      if (!["vertex_embeddings", "relation_embeddings"].includes(state.port?.type)) return;
      const rows = state.rows.filter(row => Array.isArray(row.values) && row.values.length && row.values.every(Number.isFinite)).slice(0, 1000);
      if (!rows.length) return;
      const dimensions = Math.min(...rows.map(row => row.values.length)), x = node("select", {id: "embedding-x", "aria-label": "Horizontal embedding dimension"}), y = node("select", {id: "embedding-y", "aria-label": "Vertical embedding dimension"});
      for (let i = 0; i < dimensions; i++) { x.append(node("option", {value: i}, `Horizontal: dimension ${i + 1}`)); y.append(node("option", {value: i}, `Vertical: dimension ${i + 1}`)); } y.value = String(Math.min(1, dimensions - 1));
      const controls = node("div", {class: "parameter-grid"}), plot = node("div", {id: "embedding-plot"}); controls.append(x, y);
      $("chart").append(node("p", {}, `${rows.length} of ${state.port.total_items ?? state.rows.length} retained embeddings. Axes show original dimensions; distances in this projection may differ from the full embedding.`), controls, plot);
      const draw = () => {
        plot.replaceChildren(); const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
        svg.setAttribute("viewBox", "0 0 500 340"); svg.setAttribute("aria-label", "Embedding projection; choose a point to inspect its original vector"); svg.setAttribute("role", "group");
        const xs = rows.map(r => r.values[Number(x.value)]), ys = rows.map(r => r.values[Number(y.value)]), minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
        rows.forEach((row, i) => {
          const point = document.createElementNS(ns, "circle"), title = document.createElementNS(ns, "title"), entity = row.vertex ?? row.relation ?? i;
          const description = `${W.idLabel(entity)}: ${xs[i]}, ${ys[i]}`; title.textContent = description;
          point.setAttribute("cx", String(25 + (xs[i] - minX) / (maxX - minX || 1) * 450)); point.setAttribute("cy", String(315 - (ys[i] - minY) / (maxY - minY || 1) * 290));
          point.setAttribute("r", "5"); point.setAttribute("fill", "#397b60"); point.setAttribute("tabindex", "0"); point.setAttribute("role", "button"); point.setAttribute("aria-label", description); point.append(title);
          const choose = () => { $("selection-detail").textContent = W.stringify(row, true); selectRow(row); };
          point.onclick = choose; point.onkeydown = event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); choose(); } }; svg.append(point);
        });
        plot.append(svg, node("p", {class: "muted"}, `Horizontal range ${minX} to ${maxX}; vertical range ${minY} to ${maxY}. Exact vectors remain in the table and exports.`));
      }; x.onchange = y.onchange = draw; draw();
    };
  },
};
