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
    const get = key => health.checks.find(c => c.id === key), rows = [];
    const add = (name, data, text) => rows.push({name, status: data?.status || "unavailable", text});
    const agent = get("agent"), model = get("vllm"), gpu = get("gpus"), disk = get("disk"), db = get("databases");
    add("GraphMine agent", agent, agent?.uptime_seconds == null ? "Not available yet" : `up ${duration(agent.uptime_seconds * 1000)} · ${duration(agent.response_ms)}`);
    add("vLLM", model, model?.power ? `${model.power.sleeping ? "asleep" : "awake"} · ${n(model.running)} running · ${n(model.waiting)} waiting` : model?.reason || "Not available yet");
    for (const item of gpu?.items || []) add(`GPU ${item.index} · ${item.index === 0 ? "model" : "graph calculations"}`, gpu, `${bytes(item.used_bytes)} / ${bytes(item.total_bytes)} · ${n(item.utilisation)}%`);
    const neo = health.checks.filter(c => c.id.startsWith("neo4j")), configured = neo.filter(c => c.status !== "unavailable");
    add("Neo4j datasets", configured.find(c => c.status !== "healthy") || configured[0], configured.length ? `${n(configured.filter(c => c.status === "healthy").length)} of ${n(configured.length)} instances up` : "Not available yet · no configured datasets");
    add("Database and disk", disk?.status !== "healthy" ? disk : db, `SQLite ${bytes(db?.sqlite_bytes)} · disk ${n(disk?.percent == null ? null : Math.round(disk.percent))}%`);
    const tunnels = health.checks.filter(c => c.id.startsWith("tunnel-"));
    add("Cloudflare tunnel", tunnels.find(c => c.status !== "healthy") || tunnels[0], tunnels.every(c => c.status === "healthy") ? "GraphMine + Studio reachable" : "Not available yet · see Health");
    const studio = get("studio"); add("Dataset Studio", studio, studio?.status === "healthy" ? `${n(studio.linked_accounts)} linked accounts` : studio?.reason || "Not available yet");
    return el("ul", {class: "service-list"}, rows.map(row => el("li", {}, el("span", {class: "service-name"}, el("span", {class: `health-dot ${row.status}`}), link(row.name, "health")), el("span", {class: "service-value"}, row.text))));
  }
  routes.set("overview", async (container, params, revision) => {
    const render = async () => {
      const data = await api("/api/admin/overview"); if (revision !== state.revision) return;
      const warnings = data.health.checks.filter(c => ["warning", "critical"].includes(c.status));
      const queue = card("Queue right now", el("div", {class: "queue-columns"}, [["model", "Model calls"], ["job", "Calculations"]].map(([key, title]) => {
        const q = data.queues[key]; return el("div", {}, hint(title), el("strong", {class: "queue-value"}, `${n(q.running)} / ${n(q.limit)} running`), el("progress", {value: q.running, max: q.limit, "aria-label": title}), hint(`${n(q.waiting)} waiting · oldest ${duration(q.oldest_wait_seconds == null ? null : q.oldest_wait_seconds * 1000)}`));
      })), link("Jobs & queue →", "jobs"));
      const health = card("Service health", serviceList(data.health), link("All health checks →", "health")); health.classList.add("overview-health");
      const recent = card("Recent activity", el("ul", {class: "recent-list"}, data.recent.map(item => el("li", {}, el("time", {title: stamp(item.ts)}, new Date(item.ts * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})), el("span", {class: "recent-summary"}, `${item.username || "System"} · ${item.summary}`), badge(item.outcome)))), link("All activity →", "activity"));
      for (const section of [health, queue, recent]) {
        const title = section.querySelector("h2"), target = section.lastElementChild;
        section.prepend(el("div", {class: "card-heading"}, title, target));
      }
      const problems = card("Calculations by problem · all time", data.problems.length ? el("div", {class: "problem-bars"}, data.problems.map(row => el("div", {}, el("span", {}, row.problem), el("progress", {value: row.count, max: Math.max(...data.problems.map(r => r.count)), "aria-label": row.problem}), el("span", {}, n(row.count))))) : hint("No completed calculations have been saved."), hint(`${n(data.saved_analyses)} saved analyses across ${n(data.conversations)} conversations · ${n(data.failed_analyses)} failed`));
      container.replaceChildren(heading("Overview", `${stamp(data.now)} · refreshes every 30 s`, button("Run self-test", selftest), button("Export summary", () => download("/api/admin/overview/export", "graphmine-summary.csv"))),
        ...warnings.map(w => el("div", {class: "warning monitor-warning"}, el("span", {}, el("strong", {}, w.name + ": "), w.reason || "Service needs attention"), link(w.link === "model" ? "Open Model settings" : "View health", w.link || "health"))),
        el("div", {class: "metrics-grid"}, metric("Active now", n(data.active_now), `of ${n(data.accounts)} accounts · last 5 min`), metric("Questions today", n(data.questions_today), `${n(data.questions_yesterday)} yesterday`), metric("Calculations today", n(data.calculations_today), `${n(data.calculations_failed)} failed`), metric("Time to answer", duration(data.answer_median_ms), `median · p95 ${duration(data.answer_p95_ms)}`), metric("Errors today", n(data.errors_today), data.top_error || "No errors recorded"), metric("Tokens today", n(data.tokens_today), data.tokens_reason || `of ${n(data.token_pool)} in the daily pool`)),
        el("div", {class: "overview-middle"}, health, queue, recent),
        el("div", {class: "monitor-grid overview-bottom"}, card("Questions per day · last 14 days", bars(data.questions_per_day.map(r => ({...r, day: r.day.slice(5)})), "day", "questions"), hint("UTC calendar dates")), problems),
        hint(`Operational recording began ${stamp(data.recording_since)}. Event totals cover UTC; the account pool uses its existing rolling 24-hour window.`));
      const tokenCard = container.querySelector(".metrics-grid").lastElementChild;
      if (data.tokens_today != null) tokenCard.append(el("progress", {value: data.tokens_today, max: data.token_pool, "aria-label": "Daily token pool"}));
    };
    await render(); state.timer = setInterval(() => render().catch(error => notice(error.message, true)), 30000);
  });
  function healthPanel(title, state, ...children) {
    return el("section", {class: `card monitor-card health-card health-${state}`}, el("div", {class: "health-card-heading"}, el("h2", {}, title), status(state)), children);
  }
  function healthCard(item, postgres = []) {
    const info = [], extra = [], val = key => item[key] == null ? "Not available yet" : item[key];
    if (item.id === "agent") {
      info.push(["Uptime", duration(item.uptime_seconds == null ? null : item.uptime_seconds * 1000)], ["Response time", duration(item.response_ms)], ["Open connections", `${n(item.open_connections)} of ${n(item.connection_limit)}`], ["Build", val("commit")]);
      if (item.connections_reason) extra.push(hint(item.connections_reason));
      extra.push(button("View logs", logs));
      if (item.service) extra.push(button("Restart…", () => restart("agent")));
    } else if (item.id === "vllm") {
      info.push(["State", item.power?.sleeping == null ? "Not available yet" : `${item.power.sleeping ? "Asleep" : "Awake"} · sleep mode ${item.power.enabled ? "on" : "off"}`], ["Requests", `${n(item.running)} running · ${n(item.waiting)} waiting`], ["KV cache", item.kv_cache_percent == null ? "Not available yet" : `${n(item.kv_cache_percent)}% used`], ["Address", val("address")]);
      extra.push(link("Model settings", "model"));
    } else if (item.id === "disk") {
      extra.push(meter(item.used_bytes, item.total_bytes, "Disk use"), hint("Warning at 80%, critical at 90%"));
    } else if (item.id === "databases") {
      info.push(["SQLite (app)", bytes(item.sqlite_bytes)], ["Slow queries", item.slow_queries == null ? "Not available yet" : n(item.slow_queries)]);
      postgres.forEach(p => info.push([p.name, p.status === "healthy" ? `up · ${duration(p.response_ms)}` : p.reason || p.status]));
      info.push(["Last backup", item.last_backup ? `${stamp(item.last_backup.created_at)} · ${item.last_backup.verified ? "verified" : "not verified yet"}` : "Not available yet · no snapshot found"]);
      extra.push(hint(item.slow_queries_reason), link("Backups", "data"));
    } else {
      if (item.address) info.push(["Address", item.address]);
      if (item.http_status != null) info.push(["HTTP status", n(item.http_status)]);
      info.push(["Response time", duration(item.response_ms)]);
      if (item.id === "studio") info.push(["Linked accounts", n(item.linked_accounts)]);
    }
    return healthPanel(item.name, item.status, item.reason ? hint(item.reason) : null, details(info), el("div", {class: "actions"}, extra));
  }
  function groupedHealth(title, items) {
    const worst = items.find(c => c.status === "critical") || items.find(c => c.status === "warning") || items.find(c => c.status === "unavailable") || items[0];
    return healthPanel(title, worst?.status || "unavailable", details(items.map(c => [c.name.replace(/^(Neo4j|Cloudflare) · /, ""), c.status === "healthy" ? `${c.http_status || "up"} · ${duration(c.response_ms)}` : c.reason || c.status])));
  }
  routes.set("health", async (container, params, revision) => {
    const render = async (refresh = false) => {
      const data = await api("/api/admin/health" + (refresh ? "?refresh=true" : "")); if (revision !== state.revision) return;
      const age = Math.max(0, Math.floor(Date.now() / 1000 - data.checked_at));
      const get = id => data.checks.find(c => c.id === id), gpuData = get("gpus");
      const gpuCards = (gpuData.items?.length ? gpuData.items : [{index: 0}, {index: 1}]).map(gpu => healthPanel(`GPU ${gpu.index} · ${gpu.index === 0 ? "model" : "graph calculations"}`, gpuData.status,
        hint(gpu.name || gpuData.reason || "GPU telemetry is not available yet"), gpu.name ? meter(gpu.used_bytes, gpu.total_bytes, `GPU ${gpu.index} memory`) : null,
        gpu.name ? details([["Utilisation", gpu.utilisation == null ? "Not available yet" : `${n(gpu.utilisation)}%`], ["Temperature", gpu.temperature == null ? "Not available yet" : `${n(gpu.temperature)} °C`], ["Power", gpu.power_watts == null ? "Not available yet" : `${n(gpu.power_watts)} W`], ["Lease", (gpuData.leases || []).filter(l => l.gpu_uuid === gpu.uuid).map(l => `${l.username || "Unknown owner"} · ${l.problems.join(", ") || "problem unavailable"} · ${stamp(l.started_at)}`).join("; ") || "No GraphMine worker lease"]]) : null));
      const cards = [healthCard(get("agent")), healthCard(get("vllm")), ...gpuCards,
        groupedHealth("Neo4j datasets", data.checks.filter(c => c.id.startsWith("neo4j"))), healthCard(get("databases"), data.checks.filter(c => c.id.startsWith("postgres"))),
        healthCard(get("disk")), groupedHealth("Cloudflare tunnel", data.checks.filter(c => c.id.startsWith("tunnel-"))), healthCard(get("studio"))];
      const test = card("Self-test", hint("A test account signs in, asks one question, runs the calculation and opens the result."), data.selftest ? el("div", {}, status(data.selftest.status), hint(`Started ${stamp(data.selftest.started_at)}`), details(data.selftest.steps.map(s => [`${s.name} · ${s.status}`, duration(s.duration_ms)])), button("View steps", selftest)) : hint("No self-test has run yet."));
      const incidents = card("Recent incidents", data.incidents.length ? el("ul", {class: "recent-list"}, data.incidents.map(row => el("li", {}, badge(row.closed_at ? "Resolved" : "Open", row.closed_at ? "healthy" : row.status), el("div", {}, row.summary, hint(`${stamp(row.opened_at)}${row.closed_at ? ` · closed ${stamp(row.closed_at)}` : ""}`))))) : hint("No incidents recorded. Red checks open an incident immediately; warnings open one after 15 minutes."));
      container.replaceChildren(heading("Health", `${n(data.healthy)} healthy · ${n(data.attention)} need attention · ${n(data.unavailable)} unavailable · checked ${n(age)} s ago`, button("Check again", event => action(event.currentTarget, document.querySelector("#page-notice"), () => render(true))), button("Run self-test", selftest, "primary")),
        ...data.checks.filter(c => c.id === "model-memory" && c.status === "warning").map(c => el("div", {class: "warning monitor-warning"}, c.reason, link("Model settings", "model"))),
        el("div", {class: "monitor-grid health-grid"}, cards), el("div", {class: "monitor-grid"}, test, incidents),
        hint("Each probe has a 3-second timeout. Results are cached for 10 seconds; monitoring runs every 30 seconds. Database network checks report TCP reachability."));
    };
    await render(); state.timer = setInterval(() => render().catch(error => notice(error.message, true)), 30000);
  });
  routes.set("model", async (container, params, revision) => {
    let data = await api("/api/admin/model"); if (revision !== state.revision) return;
    const strip = el("div"), metrics = el("div", {class: "model-today"}), history = el("div", {class: "model-history"}), message = el("p", {role: "status", class: "form-notice"});
    const sleep = check("Sleep mode", data.values.GRAPHMINE_LLM_SLEEP_MODE); sleep.input.setAttribute("aria-label", "Enable sleep mode · needs a model restart");
    const idle = el("select", {"aria-label": "Idle for"}, ...[10, 20, 60].map(v => option(v, `${v} minutes`))); idle.value = data.values.GRAPHMINE_LLM_IDLE_SLEEP_MINUTES;
    const switches = [["family", "Family", "pick the topic area"], ["topic", "Topic", "pick the topic"], ["route", "Route", "pick the calculation"], ["clarify", "Clarify", "ask the user a question"], ["analyst", "Explanation", "write the answer"]].map(([key, label, note]) => {
      const c = check(`${label} · ${note}`, data.values.GRAPHMINE_LLM_THINKING_STAGES.includes(key)); c.input.setAttribute("aria-label", label); return {key, ...c};
    });
    const loaded = card("Loaded", details([["Base model", data.loaded.base_model], ["Planner adapter", data.loaded.planner_adapter || "No separate adapter configured"], ["Analyst adapter", data.loaded.analyst_adapter || "No separate adapter configured"], ["Context length", n(data.loaded.context_length)], ["Requests at once", n(data.loaded.max_requests)], ["GPU memory share", data.loaded.gpu_memory_share == null ? "Not available yet" : `${data.loaded.gpu_memory_share * 100}%`]]), hint(data.loaded.reason), link("Change in Capacity", "capacity"));
    const render = () => {
      const p = data.power, name = p.sleeping == null ? "State unavailable" : p.sleeping ? "Asleep" : "Awake";
      const powerAction = async (kind, event) => action(event.currentTarget, message, async () => { await mutate(`/api/admin/llm/power/${kind}`); data = await api("/api/admin/model"); render(); });
      const sleepNow = button("Sleep now", event => powerAction("sleep", event)), wakeNow = button("Wake now", event => powerAction("wake", event));
      sleepNow.disabled = !p.enabled || p.sleeping !== false; wakeNow.disabled = !p.enabled || p.sleeping !== true;
      const memory = data.gpu ? `GPU ${data.gpu.index} · holding ${bytes(data.gpu.model_bytes)}${data.memory_observed_since ? ` for at least ${duration((Date.now() / 1000 - data.memory_observed_since) * 1000)}` : " · hold duration not yet observed"}` : "GPU memory not available yet · telemetry is unavailable";
      strip.replaceChildren(el("section", {class: "card model-strip"}, el("div", {}, el("div", {class: "actions"}, el("h2", {}, data.name), badge(name, p.sleeping == null ? "unavailable" : "healthy"), badge(`Sleep mode ${p.enabled ? "on" : "off"}`, p.enabled ? "healthy" : "warning")), hint(`${data.address} · ${memory}`)), el("div", {class: "actions"}, sleepNow, wakeNow, data.health.service ? button("Restart…", () => restart("model")) : null)), data.values.GRAPHMINE_LLM_SLEEP_MODE !== data.effective.GRAPHMINE_LLM_SLEEP_MODE ? el("p", {class: "warning"}, "The saved sleep-mode setting takes effect after restarting the model here.") : "");
      const t = data.today;
      metrics.replaceChildren(...[["Calls", n(t.calls)], ["Median call", duration(t.median_ms)], ["Slowest", duration(t.slowest_ms)], ["Tokens / s", n(t.tokens_per_second == null ? null : Math.round(t.tokens_per_second))], ["Wakes", n(t.wakes)], ["Model busy errors", n(t.busy_errors)]].map(([label, value]) => el("div", {}, hint(label), el("strong", {class: value === "Not available yet" ? "missing" : ""}, value))));
      const buckets = new Map(); for (const row of data.gpu_history) { const key = new Date(row.ts * 1000).toISOString().slice(11, 13) + ":00"; const b = buckets.get(key) || {hour: key, total: 0, count: 0}; b.total += row.used_bytes; b.count++; buckets.set(key, b); }
      history.replaceChildren(el("h3", {}, "GPU 0 memory · last 24 h"), data.gpu_history.length ? bars([...buckets.values()].map(b => ({hour: b.hour, bytes: b.total / b.count})), "hour", "bytes", bytes) : hint("Not available yet · no GPU memory samples have been recorded"), hint(`Calls with stored diagnostics · ${n(t.manual_wakes)} manual wakes. ${t.wake_reason || ""}`));
    };
    const save = button("Save model settings", event => action(event.currentTarget, message, async () => {
      const result = await mutate("/api/admin/model/settings", {values: {GRAPHMINE_LLM_SLEEP_MODE: sleep.input.checked, GRAPHMINE_LLM_IDLE_SLEEP_MINUTES: Number(idle.value), GRAPHMINE_LLM_THINKING_STAGES: switches.filter(s => s.input.checked).map(s => s.key)}}, "PATCH");
      data = await api("/api/admin/model"); render(); message.textContent = result.restart_required.length ? "Saved. Sleep-mode changes need a restart; the other settings are live." : "Saved. New calls use these settings.";
    }), "primary");
    const sleepCard = card("Sleep when idle", hint("Frees most GPU memory when nobody is using GraphMine. The first question after that waits a few seconds while the model wakes."), sleep.label, hint("Sleep mode needs a model restart to change."), el("div", {class: "field-row"}, field("Sleep after no use for", idle), field("How deeply", el("input", {value: "Level 1 · fast wake", readOnly: true}))), el("div", {class: "soft-note"}, hint(data.ram_check.reason)));
    container.replaceChildren(heading("Model", "The language model that routes questions and writes explanations"), strip,
      el("div", {class: "monitor-grid model-controls"}, sleepCard, card("Thinking per step", hint("Thinking adds reasoning tokens. Enabled steps keep the provider defaults; changes apply to new calls."), el("div", {class: "thinking-grid"}, switches.map(s => s.label)))), message, el("div", {class: "actions settings-actions"}, save), el("div", {class: "monitor-grid model-bottom"}, loaded, card("Today", metrics, history)));
    render(); state.timer = setInterval(async () => { try { const next = await api("/api/admin/model"); if (revision === state.revision) { data = next; render(); } } catch (error) { notice(error.message, true); } }, 30000);
  });
})();
