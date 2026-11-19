/* Live queue metadata and fixed Vega-Lite usage charts. */
(() => {
  "use strict";
  const A = window.GraphMineAdmin;
  const {api, mutate, el, n, duration, stamp, hint, unavailable, badge, button, check, heading, table, details, state, routes, notice, action, download, dialog, footer} = A;
  const card = (title, ...children) => el("section", {class: "card monitor-card"}, el("h2", {}, title), children);
  const metric = (label, value, note, extra) => el("section", {class: "card metric"}, el("p", {class: "metric-label"}, label), el("strong", {class: `metric-value${value === "Not available yet" ? " missing" : ""}`}, value), extra, hint(note));
  const elapsed = value => duration(value == null ? null : value * 1000);
  const percent = value => value == null ? "Not available yet" : `${(value * 100).toLocaleString([], {maximumFractionDigits: 1})}%`;
  const emptyRow = (count, text) => el("tr", {}, el("td", {colspan: count, class: "empty"}, text));
  function workTable(title, headers, rows, controls) {
    const node = table(headers, rows.length ? rows : [emptyRow(headers.length, "No work in this list.")]);
    node.classList.add("work-table"); node.prepend(el("div", {class: "work-table-heading"}, el("h2", {}, title), controls)); return node;
  }
  async function calculationDetails(row) {
    const d = dialog(row.status === "failed" ? "Why it failed" : "Calculation details", true); d.open();
    try {
      const data = await api(`/api/admin/jobs/${row.kind}/${encodeURIComponent(row.id)}`);
      d.node.append(details([["User", data.username], ["Status", data.status], ["Queued", stamp(data.queued_at)], ["Waited", elapsed(data.waited_seconds)], ["Run time", elapsed(data.running_seconds)]]),
        data.error ? el("div", {class: "warning"}, el("strong", {}, data.error.code), hint(data.error.message)) : hint("No error recorded."),
        el("h3", {}, "Plan and parameters"), el("pre", {class: "code"}, JSON.stringify(data.plan, null, 2)),
        el("h3", {}, "Step log"), data.log.length ? el("pre", {class: "code"}, JSON.stringify(data.log, null, 2)) : hint("No step status has been recorded yet."));
    } catch (error) { d.node.append(hint(error.message)); }
  }
  function cancelWork(path, refresh, calculation) {
    const d = dialog(calculation ? "Cancel calculation?" : "Cancel model call?"), message = el("p", {class: "form-notice", role: "status"});
    d.node.append(hint(`The user will see “Cancelled by an administrator”. ${calculation ? "The calculation is refunded against the daily job allowance. " : ""}This action is recorded in Activity.`), message,
      footer(d, button("Cancel work", event => action(event.currentTarget, message, async () => { await mutate(path); d.close(); notice("Work cancelled. The action is recorded in Activity."); await refresh(); }), "danger primary"), "Keep running")); d.open();
  }
  routes.set("jobs", async (container, params, revision) => {
    const view = ["active", "finished", "failed"].includes(params.get("view")) ? params.get("view") : "active";
    const render = async () => {
      const data = await api(`/api/admin/jobs?view=${view}`); if (revision !== state.revision) return;
      const q = data.queues, gpu = data.gpu_leases, progress = value => el("progress", {value: value.running, max: value.limit, "aria-label": "Running capacity"});
      const filters = el("div", {class: "actions"}, [["active", "Running and waiting"], ["finished", "Finished today"], ["failed", "Failed"]].map(([key, text]) => button(text, () => { location.hash = `jobs?view=${key}`; }, key === view ? "primary" : "")));
      const calls = workTable("Model calls", ["User", "Stage", "Status", "Waited", "Running for", "Tokens so far", ""], data.model_calls.map(row => el("tr", {},
        el("td", {}, row.username), el("td", {}, row.stage || "Not available yet"), el("td", {}, badge(row.status === "waiting" ? `Waiting · position ${n(row.position)}` : "Running", row.status)),
        el("td", {}, elapsed(row.waited_seconds)), el("td", {}, elapsed(row.running_seconds)), el("td", {}, n(row.tokens), row.tokens_reason ? hint(row.tokens_reason) : null),
        el("td", {}, row.cancellable ? button("Cancel", () => cancelWork(`/api/admin/model-calls/${encodeURIComponent(row.id)}/cancel`, render, false), "danger") : hint("Cancellation requested")))));
      const calculations = workTable("Calculations", ["User", "Calculation", "Input", "Device", "Status", "Waited", "Run time", ""], data.calculations.map(row => el("tr", {},
        el("td", {}, row.username || "Deleted account"), el("td", {}, row.operations.join(", ")), el("td", {}, row.inputs.length ? row.inputs.map(input => el("div", {}, input.name || "Unknown input", hint(`${n(input.vertex_count)} vertices · ${n(input.edge_count)} edges`))) : hint("Not available yet · input metadata was not recorded")),
        el("td", {}, row.device || "Not available yet"), el("td", {}, badge(row.status, row.status)), el("td", {}, elapsed(row.waited_seconds)), el("td", {}, elapsed(row.running_seconds)),
        el("td", {}, el("div", {class: "row-actions"}, button(row.status === "failed" ? "Why it failed" : "Details", () => calculationDetails(row)), row.cancellable ? button("Cancel", () => cancelWork(`/api/admin/jobs/${row.kind}/${encodeURIComponent(row.id)}/cancel`, render, true), "danger") : null)))), filters);
      container.replaceChildren(heading("Jobs & queue", `What is running and waiting right now · live · refreshes every 5 s · ${stamp(data.now)}`),
        el("div", {class: "metrics-grid jobs-metrics"}, metric("Model calls", `${n(q.model.running)} / ${n(q.model.limit)} running`, `${n(q.model.waiting)} waiting · gives up after ${n(data.model_wait_seconds)} s`, progress(q.model)),
          metric("Calculations", `${n(q.job.running)} / ${n(q.job.limit)} running`, `${n(q.job.waiting)} waiting · ${n(data.per_user)} per user`, progress(q.job)),
          metric("GPU 1 lease", gpu.length ? "Held" : "Free", gpu.length ? gpu.map(g => `by ${g.username || "Unknown owner"} · ${g.operations.join(", ") || "operation unavailable"} · ${elapsed(g.seconds)}`).join("; ") : "No GraphMine worker holds a lease"),
          metric("CPU workers", `${n(data.cpu.busy)} / ${n(data.cpu.total)} busy`, `Pending limit ${n(data.cpu.pending_limit)} jobs`)), calls, calculations,
        data.total > data.limit ? hint(`Showing ${n(data.limit)} of ${n(data.total)} calculations. Use Activity to inspect older completion events.`) : el("span"),
        el("div", {class: "card work-note"}, el("p", {}, "Cancelling stops the work and tells the user: “Cancelled by an administrator”. A cancelled calculation does not count against their daily jobs."), el("a", {class: "btn", href: "#capacity"}, "Change limits")));
    };
    await render(); state.timer = setInterval(() => render().catch(error => notice(error.message, true)), 5000);
  });

  routes.set("usage", async (container, params, revision) => {
    const days = [7, 14, 30, 90].includes(Number(params.get("days"))) ? Number(params.get("days")) : 14, compare = params.get("compare") !== "0";
    const data = await api(`/api/admin/usage?days=${days}`); if (revision !== state.revision) return;
    const controls = check("Compare", compare), s = data.summary, previous = data.previous;
    controls.input.addEventListener("change", () => { location.hash = `usage?days=${days}&compare=${controls.input.checked ? 1 : 0}`; });
    const difference = (key, format = n) => {
      if (!compare) return "";
      if (s[key] == null || previous[key] == null) return "Comparison not available yet";
      const value = s[key] - previous[key]; return `${value > 0 ? "+" : ""}${format(value)} vs previous period`;
    };
    const charts = el("div", {class: "monitor-grid usage-charts"}), views = [];
    state.cleanup = () => views.forEach(view => view.finalize());
    container.replaceChildren(heading("Usage analytics", `Last ${days} days${compare ? ` compared with the ${days} days before` : ""} · UTC`, ...[7, 14, 30, 90].map(value => button(`${value} days`, () => { location.hash = `usage?days=${value}&compare=${compare ? 1 : 0}`; }, value === days ? "primary" : "")), controls.label, button("Export", () => download(`/api/admin/usage/export?days=${days}`, "graphmine-usage.csv"))),
      el("div", {class: "metrics-grid"}, metric("Active users", n(s.active_users), difference("active_users")), metric("Questions", n(s.questions), difference("questions")), metric("Calculations", n(s.calculations), difference("calculations")),
        metric("Tokens used", n(s.tokens), s.tokens_reason || `${percent(s.reasoning_share)} reasoning · ${difference("tokens")}`), metric("Time to answer", duration(s.answer_median_ms), `median · p95 ${duration(s.answer_p95_ms)} · ${difference("answer_median_ms", duration)}`), metric("Error rate", percent(s.error_rate), `${s.top_error || "No errors recorded"} · ${difference("error_rate", percent)}`)), charts,
      hint(`${data.error_rate_definition} Cached for ${data.cache_seconds} s. Recording began ${stamp(data.recording_since)}; periods include today's elapsed hours and the equivalent elapsed hours in the previous period.`));
    const chart = async (title, values, spec, reason, note) => {
      const host = el("div", {class: "usage-chart", "aria-label": title}), section = card(title, host, note ? hint(note) : null); charts.append(section);
      if (!values.length) { host.append(unavailable(reason)); return; }
      try {
        // Specs are defined here; user data supplies values only. No remote URLs
        // or executable expressions are accepted from account/event metadata.
        const compiled = window.vegaLite.compile({$schema: "https://vega.github.io/schema/vega-lite/v6.json", width: Math.max(220, host.clientWidth - 10), height: 180,
          autosize: {type: "fit", contains: "padding"}, data: {values}, config: {font: "Inter", view: {stroke: null}, axis: {labelColor: "#596e62", titleColor: "#596e62", gridColor: "#e8efea", labelFontSize: 11, titleFontSize: 11}, legend: {orient: "top", labelFontSize: 11}, range: {category: ["#16734b", "#ee7b2d", "#4e82b4", "#9dc7b1"]}}, ...spec}).spec;
        const view = new window.vega.View(window.vega.parse(compiled, null, {ast: true}), {expr: window.vega.expressionInterpreter, renderer: "svg", container: host,
          loader: {load: async () => { throw new Error("External chart resources are disabled"); }}});
        views.push(view); await view.runAsync();
        if (revision !== state.revision) view.finalize();
      } catch (error) { host.replaceChildren(unavailable("The chart could not be rendered"), hint(error.message)); }
    };
    const daily = data.daily.flatMap(row => [{day: row.day, type: "Questions", count: row.questions}, {day: row.day, type: "Calculations", count: row.calculations}]);
    const xday = {field: "day", type: "ordinal", title: "Date (UTC)", axis: {labelAngle: -35, labelOverlap: true}};
    await chart("Questions and calculations per day", daily, {encoding: {x: xday, xOffset: {field: "type"}, y: {field: "count", type: "quantitative", title: "Count", axis: {tickMinStep: 1}}, color: {field: "type", title: null, scale: {domain: ["Questions", "Calculations"], range: ["#16734b", "#ee7b2d"]}}}, layer: [{mark: "bar"}, {mark: {type: "text", dy: -5, fontSize: days > 14 ? 8 : 10}, encoding: {text: {field: "count", format: "d"}}}]}, "No questions or calculations have been recorded");
    const timing = data.daily.flatMap(row => [["Median", row.median_ms], ["p95", row.p95_ms]].filter(([, value]) => value != null).map(([series, value]) => ({day: row.day, series, seconds: value / 1000})));
    await chart("Time to answer", timing, {encoding: {x: xday, y: {field: "seconds", type: "quantitative", title: "Seconds"}, color: {field: "series", title: null}}, layer: [{mark: {type: "line", point: true}}, {mark: {type: "text", dy: -9, fontSize: 10}, encoding: {text: {field: "seconds", format: ".1f"}}}]}, "No question durations have been recorded");
    await chart("Where the time goes", data.time_breakdown, {height: 115, encoding: {y: {datum: "Recorded", title: null}, x: {field: "seconds", type: "quantitative", stack: "zero", title: "Recorded seconds"}, color: {field: "stage", title: null}}, layer: [{mark: {type: "bar", size: 24}}, {mark: {type: "text", dx: -5, align: "right", color: "white"}, encoding: {text: {field: "seconds", format: ".1f"}, color: {value: "white"}}}]}, "No per-stage timings have been recorded", data.timing_reason);
    const horizontal = (label, value, title, color) => ({height: 150, encoding: {y: {field: label, type: "nominal", title: null, sort: "-x", axis: {labelLimit: 160}}, x: {field: value, type: "quantitative", title, axis: {tickMinStep: 1}, scale: {padding: 24}}}, layer: [{mark: {type: "bar", color, size: 12, cornerRadiusEnd: 3}}, {mark: {type: "text", align: "left", dx: 4}, encoding: {text: {field: value, format: ",d"}}}]});
    await chart("Errors by type", data.errors, horizontal("type", "count", "Errors", "#a52e26"), "No errors have been recorded in this period");
    await chart("Tokens by user", data.tokens_by_user.filter(row => !row.missing || row.tokens), horizontal("user", "tokens", "Reported tokens", "#16734b"), "No provider token usage has been recorded", data.tokens_by_user.some(row => row.missing) ? "Partial coverage · some questions have no provider usage. Unreported tokens are not shown as zero." : null);
    await chart("Datasets used", data.datasets, horizontal("dataset", "count", "Calculations", "#16734b"), "No dataset usage has been recorded", `${n(data.datasets_missing)} calculations lack dataset metadata. Questions routed to the wrong calculation: ${n(data.routing_corrections)} · ${data.routing_reason}`);
  });
})();
