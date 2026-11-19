/* Overview, bounded health checks and model controls. */
(() => {
  "use strict";
  const A = window.GraphMineAdmin;
  const {api, mutate, el, n, bytes, stamp, duration, hint, unavailable, badge, button, field, check, heading, option, table, details, state, routes, notice, action, download, dialog, footer} = A;
  const card = (title, ...children) => el("section", {class: "card monitor-card"}, el("h2", {}, title), children);
  const link = (text, page) => el("a", {href: `#${page}`}, text);
  const metric = (label, value, note) => el("section", {class: "card metric"}, el("p", {class: "metric-label"}, label), el("strong", {class: value === "Not available yet" ? "metric-value missing" : "metric-value"}, value), hint(note));
  const status = value => badge(value === "unavailable" ? "Not available yet" : value[0].toUpperCase() + value.slice(1), value);
  const meter = (value, total, label) => value == null || total == null ? unavailable("This measurement has not been reported") : el("div", {}, el("progress", {value, max: Math.max(total, 1), "aria-label": label}), hint(`${bytes(value)} of ${bytes(total)}`));
  function bars(rows, labelKey, valueKey, format = n) {
    if (!rows.length) return unavailable("No measurements have been recorded");
    const max = Math.max(1, ...rows.map(r => r[valueKey] || 0));
    return el("div", {class: "bar-chart", role: "img", "aria-label": rows.map(r => `${r[labelKey]}: ${format(r[valueKey])}`).join("; ")}, rows.map(row => el("div", {class: "chart-column"}, el("span", {class: "chart-value"}, format(row[valueKey])), el("div", {class: "chart-track"}, el("span", {style: `height:${Math.max(1, row[valueKey] / max * 100)}%`})), el("span", {class: "chart-label"}, row[labelKey]))));
  }
  function restart(service) {
    const d = dialog(`Restart ${service === "model" ? "model" : "GraphMine agent"}?`), message = el("p", {role: "status", class: "form-notice"});
    const save = button("Restart service", event => action(event.currentTarget, message, async () => {
      const result = await mutate(`/api/admin/services/${service}/restart`, {confirm: true}); d.close(); notice(result.reason);
    }), "danger primary");
    d.node.append(hint("Active work may be interrupted. The restart and its requested settings are recorded in Activity."), message, footer(d, save)); d.open();
  }
  async function selftest() {
    const d = dialog("Run self-test"), content = el("div"), message = el("p", {class: "form-notice", role: "status"}); let timer;
    const render = result => {
      content.replaceChildren(result ? el("div", {}, el("p", {}, status(result.status), ` · ${stamp(result.started_at)}`), table(["Step", "Result", "Time"], result.steps.map(s => el("tr", {}, el("td", {}, s.name, s.reason ? hint(s.reason) : null), el("td", {}, status(s.status)), el("td", {}, duration(s.duration_ms)))))) : hint("No self-test has run yet."));
      run.disabled = result?.status === "running";
      if (result?.status !== "running") clearInterval(timer);
    };
    const poll = async () => { try { const data = await api("/api/admin/health/selftest"); if (d.node.isConnected) render(data.result); } catch (error) { message.textContent = error.message; } };
    const run = button("Run self-test", event => action(event.currentTarget, message, async () => {
      const result = await mutate("/api/admin/health/selftest"); render(result); clearInterval(timer); timer = setInterval(poll, 1500);
    }), "primary");
    d.node.append(hint("Uses the internal selftest account to sign in, ask “What is a k-core?”, calculate a fixed triangle on the CPU, and open its result. The account cannot sign in externally. This uses the normal model and calculation queues."), content, message, footer(d, run, "Close"));
    d.node.addEventListener("close", () => clearInterval(timer)); d.open(); await poll();
    if (run.disabled) timer = setInterval(poll, 1500);
  }
  async function logs() {
    const d = dialog("GraphMine agent · last 200 log lines", true); d.open();
    try { const data = await api("/api/admin/health/logs"); d.node.append(data.lines == null ? unavailable(data.reason) : el("div", {}, hint(data.reason), el("pre", {class: "log-view"}, data.lines))); }
    catch (error) { d.node.append(hint(error.message)); }
  }
  function serviceList(health) {
    return el("ul", {class: "service-list"}, health.checks.map(item => el("li", {}, link(item.name, "health"), status(item.status))));
  }
  routes.set("overview", async (container, params, revision) => {
    const render = async () => {
      const data = await api("/api/admin/overview"); if (revision !== state.revision) return;
      const warnings = data.health.checks.filter(c => ["warning", "critical"].includes(c.status));
      container.replaceChildren(heading("Overview", `${stamp(data.now)} · refreshes every 30 s`, button("Run self-test", selftest), button("Export summary", () => download("/api/admin/overview/export", "graphmine-summary.csv"))),
        ...warnings.map(w => el("div", {class: "warning"}, el("strong", {}, w.name + ": "), w.reason || "Service needs attention", " · ", link(w.link === "model" ? "Model controls" : "View health", w.link || "health"))),
        el("div", {class: "metrics-grid"}, metric("Active now", n(data.active_now), `of ${n(data.accounts)} accounts · last 5 minutes`), metric("Questions today", n(data.questions_today), `${n(data.questions_yesterday)} yesterday`), metric("Calculations today", n(data.calculations_today), `${n(data.calculations_failed)} failed`), metric("Time to answer", duration(data.answer_median_ms), `Median · p95 ${duration(data.answer_p95_ms)}`), metric("Errors today", n(data.errors_today), data.top_error ? `Top cause: ${data.top_error}` : "No errors recorded today"), el("section", {class: "card metric"}, el("p", {class: "metric-label"}, "Tokens today"), el("strong", {class: "metric-value"}, n(data.tokens_today)), hint(data.tokens_reason || `of ${n(data.token_pool)} in the daily pool`), data.tokens_today == null ? null : el("progress", {value: data.tokens_today, max: data.token_pool, "aria-label": "Daily token pool"}))),
        el("div", {class: "monitor-grid"}, card("Service health", serviceList(data.health), link("All checks →", "health")), card("Queue right now", ...[["model", "Model calls"], ["job", "Calculations"]].map(([key, title]) => { const q = data.queues[key]; return el("div", {class: "queue-summary"}, el("h3", {}, title), details([["Running", `${n(q.running)} / ${n(q.limit)}`], ["Waiting", n(q.waiting)], ["Oldest wait", q.oldest_wait_seconds == null ? "Not available yet · " + q.wait_reason : duration(q.oldest_wait_seconds * 1000)]])); }), link("Jobs & queue →", "jobs"))),
        el("div", {class: "monitor-grid"}, card("Questions per day", hint("Questions · UTC calendar date"), bars(data.questions_per_day.map(r => ({...r, day: r.day.slice(5)})), "day", "questions")), card("Recent activity", el("ul", {class: "recent-list"}, data.recent.map(item => el("li", {}, el("div", {}, el("strong", {}, item.summary), hint(`${item.username || "System"} · ${stamp(item.ts)}`)), badge(item.outcome)))), link("Open Activity →", "activity"))),
        card("Calculations by operation · all time", hint(`${n(data.saved_analyses)} saved analyses across ${n(data.conversations)} conversations · ${n(data.failed_analyses)} failed`), data.operations.length ? table(["Operation", "Successful steps"], data.operations.map(row => el("tr", {}, el("td", {}, row.operation), el("td", {}, n(row.count))))) : hint("No completed calculations have been saved.")),
        hint(`Operational recording began ${stamp(data.recording_since)}. Today's event totals cover UTC; the account pool uses its existing rolling 24-hour window.`));
    };
    await render(); state.timer = setInterval(() => render().catch(error => notice(error.message, true)), 30000);
  });
  function healthCard(item) {
    const info = [], extra = [], val = key => item[key] == null ? "Not available yet" : item[key];
    if (item.id === "agent") {
      info.push(["Uptime", duration(item.uptime_seconds == null ? null : item.uptime_seconds * 1000)], ["Response", duration(item.response_ms)], ["Open connections", `${n(item.open_connections)} / ${n(item.connection_limit)}`], ["Build commit", val("commit")]);
      extra.push(hint(item.connections_reason), button("View logs", logs));
      if (item.service) extra.push(button("Restart…", () => restart("agent")));
    } else if (item.id === "vllm") {
      info.push(["State", item.power?.sleeping == null ? "Not available yet" : item.power.sleeping ? "Asleep" : "Awake"], ["Sleep mode", item.power ? item.power.enabled ? "On" : "Off" : "Not available yet"], ["Running / waiting", `${n(item.running)} / ${n(item.waiting)}`], ["KV cache", item.kv_cache_percent == null ? "Not available yet" : `${n(item.kv_cache_percent)}%`], ["Address", val("address")]);
      extra.push(link("Model controls →", "model"));
    } else if (item.id === "disk") extra.push(meter(item.used_bytes, item.total_bytes, "Disk use"), hint("Warning at 80% · critical at 90%"));
    else if (item.id === "databases") info.push(["SQLite stored", bytes(item.sqlite_bytes)], ["Slow queries", `Not available yet · ${item.slow_queries_reason || "check unavailable"}`], ["Last backup", item.last_backup ? stamp(item.last_backup.created_at) : "Not available yet · no snapshot found"], ["Verified", item.last_backup?.verified ? "Yes" : "Not available yet · run Verify in Data & storage"]);
    else {
      if (item.address) info.push(["Address", item.address]);
      if (item.http_status != null) info.push(["HTTP status", n(item.http_status)]);
      if (item.check) info.push(["Check", item.check]);
      if (item.id === "studio") info.push(["Linked accounts", n(item.linked_accounts)]);
      info.push(["Response", duration(item.response_ms)]);
    }
    return card(item.name, status(item.status), item.reason ? hint(item.reason) : null, details(info), el("div", {class: "actions"}, extra));
  }
  routes.set("health", async (container, params, revision) => {
    const render = async (refresh = false) => {
      const data = await api("/api/admin/health" + (refresh ? "?refresh=true" : "")); if (revision !== state.revision) return;
      const age = Math.max(0, Math.floor(Date.now() / 1000 - data.checked_at));
      const cards = data.checks.flatMap(item => item.id !== "gpus" ? [healthCard(item)] : item.items?.length ? item.items.map(gpu => card(`GPU ${gpu.index} · ${gpu.name}`, status(item.status), meter(gpu.used_bytes, gpu.total_bytes, `GPU ${gpu.index} memory`), details([["Utilisation", gpu.utilisation == null ? "Not available yet" : `${n(gpu.utilisation)}%`], ["Temperature", gpu.temperature == null ? "Not available yet" : `${n(gpu.temperature)} °C`], ["Power", gpu.power_watts == null ? "Not available yet" : `${n(gpu.power_watts)} W`], ["GPU lease", item.leases.filter(l => l.gpu_uuid === gpu.uuid).map(l => `${l.username || "Unknown owner"} · ${l.operations.join(", ") || "operation unavailable"} · ${stamp(l.started_at)}`).join("; ") || "No GraphMine worker lease"]]))) : [healthCard(item)]);
      container.replaceChildren(heading("Health", `${n(data.healthy)} healthy · ${n(data.attention)} need attention · ${n(data.unavailable)} unavailable · checked ${n(age)} s ago`, button("Check again", event => action(event.currentTarget, document.querySelector("#page-notice"), () => render(true))), button("Run self-test", selftest)), el("div", {class: "monitor-grid health-grid"}, cards),
        card("Last self-test", data.selftest ? el("div", {}, status(data.selftest.status), hint(`Started ${stamp(data.selftest.started_at)}`), button("View steps", selftest)) : hint("No self-test has run yet.")),
        card("Recent incidents", data.incidents.length ? table(["Service", "Incident", "Opened", "Closed"], data.incidents.map(row => el("tr", {}, el("td", {}, row.service), el("td", {}, row.summary), el("td", {}, stamp(row.opened_at)), el("td", {}, row.closed_at ? stamp(row.closed_at) : badge("Open", row.status))))) : hint("No incidents recorded. Red checks open an incident immediately; warnings open one after 15 minutes.")), hint("Each probe has a 3-second timeout. Results are cached for 10 seconds; monitoring runs every 30 seconds. Database network checks report TCP reachability."));
    };
    await render(); state.timer = setInterval(() => render().catch(error => notice(error.message, true)), 30000);
  });
  routes.set("model", async (container, params, revision) => {
    let data = await api("/api/admin/model"); if (revision !== state.revision) return;
    const strip = el("div"), metrics = el("div"), history = el("div"), message = el("p", {role: "status", class: "form-notice"});
    const sleep = check("Enable sleep mode · needs a model restart", data.values.GRAPHMINE_LLM_SLEEP_MODE);
    const idle = el("select", {"aria-label": "Idle for"}, ...[10, 20, 60].map(v => option(v, `${v} minutes`))); idle.value = data.values.GRAPHMINE_LLM_IDLE_SLEEP_MINUTES;
    const switches = [["family", "Family"], ["problem", "Problem"], ["route", "Route"], ["clarify", "Clarify"], ["analyst", "Explanation"]].map(([key, label]) => ({key, ...check(label, data.values.GRAPHMINE_LLM_THINKING_STAGES.includes(key))}));
    const loaded = card("Loaded", details([["Base model", data.loaded.base_model], ["Planner adapter", data.loaded.planner_adapter || "No separate adapter configured"], ["Analyst adapter", data.loaded.analyst_adapter || "No separate adapter configured"], ["Context length", n(data.loaded.context_length)], ["Requests at once", n(data.loaded.max_requests)], ["GPU memory share", data.loaded.gpu_memory_share == null ? "Not available yet" : `${data.loaded.gpu_memory_share * 100}%`]]), hint(data.loaded.reason), link("Capacity settings →", "capacity"));
    const render = () => {
      const p = data.power, name = p.sleeping == null ? "State unavailable" : p.sleeping ? "Asleep" : "Awake";
      const powerAction = async (kind, event) => action(event.currentTarget, message, async () => { await mutate(`/api/admin/llm/power/${kind}`); data = await api("/api/admin/model"); render(); });
      const sleepNow = button("Sleep now", event => powerAction("sleep", event)), wakeNow = button("Wake now", event => powerAction("wake", event));
      sleepNow.disabled = !p.enabled || p.sleeping !== false; wakeNow.disabled = !p.enabled || p.sleeping !== true;
      strip.replaceChildren(card(data.name, el("div", {class: "actions"}, badge(name, p.sleeping == null ? "unavailable" : "healthy"), badge(`Sleep mode ${p.enabled ? "on" : "off"}`)), hint(data.address), data.gpu ? meter(data.gpu.model_bytes, data.gpu.total_bytes, "Memory held by vLLM") : unavailable("Model GPU telemetry is unavailable"), hint(data.memory_observed_since ? `GPU memory held since at least ${stamp(data.memory_observed_since)}` : "Memory-hold duration has not been observed yet"), el("div", {class: "actions"}, sleepNow, wakeNow, data.health.service ? button("Restart…", () => restart("model")) : null), data.values.GRAPHMINE_LLM_SLEEP_MODE !== data.effective.GRAPHMINE_LLM_SLEEP_MODE ? el("p", {class: "warning"}, "The saved sleep-mode setting takes effect after restarting the model here.") : null));
      const t = data.today;
      metrics.replaceChildren(el("div", {class: "metrics-grid"}, metric("Calls today", n(t.calls), "Calls with stored diagnostics"), metric("Median call", duration(t.median_ms), `Slowest ${duration(t.slowest_ms)}`), metric("Output tokens / second", n(t.tokens_per_second == null ? null : Math.round(t.tokens_per_second)), "Across measured model calls"), metric("Wakes today", n(t.wakes), `${n(t.manual_wakes)} manual · ${t.wake_reason}`), metric("Model busy errors", n(t.busy_errors), "Recorded today · UTC")));
      // Samples are grouped by hour using measured values, never filled forward.
      const buckets = new Map(); for (const row of data.gpu_history) { const key = new Date(row.ts * 1000).toISOString().slice(11, 13) + ":00"; const b = buckets.get(key) || {hour: key, total: 0, count: 0}; b.total += row.used_bytes; b.count++; buckets.set(key, b); }
      history.replaceChildren(card("GPU 0 memory · last 24 hours", hint("Average observed GPU memory used by all processes · UTC hour"), bars([...buckets.values()].map(b => ({hour: b.hour, bytes: b.total / b.count})), "hour", "bytes", bytes)));
    };
    const save = button("Save model settings", event => action(event.currentTarget, message, async () => {
      const result = await mutate("/api/admin/model/settings", {values: {GRAPHMINE_LLM_SLEEP_MODE: sleep.input.checked, GRAPHMINE_LLM_IDLE_SLEEP_MINUTES: Number(idle.value), GRAPHMINE_LLM_THINKING_STAGES: switches.filter(s => s.input.checked).map(s => s.key)}}, "PATCH");
      data = await api("/api/admin/model"); render(); message.textContent = result.restart_required.length ? "Saved. Sleep-mode changes need a restart; the other settings are live." : "Saved. New calls use these settings.";
    }), "primary");
    container.replaceChildren(heading("Model", "Power, reasoning controls and measured model activity"), strip,
      el("div", {class: "monitor-grid"}, card("Sleep when idle", sleep.label, field("Idle for", idle), details([["Sleep level", "1"]]), hint(data.ram_check.reason)), card("Thinking per step", hint("Enabled steps preserve the existing provider defaults. Turning a step off explicitly disables thinking for new calls."), el("div", {class: "thinking-grid"}, switches.map(s => s.label)))), message, el("div", {class: "actions settings-actions"}, save), loaded, el("h2", {}, "Today"), metrics, history);
    render(); state.timer = setInterval(async () => { try { const next = await api("/api/admin/model"); if (revision === state.revision) { data = next; render(); } } catch (error) { notice(error.message, true); } }, 30000);
  });
})();
