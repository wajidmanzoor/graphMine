/* Capacity, measured storage and the optional installed performance suite. */
(() => {
  "use strict";
  const A = window.GraphMineAdmin;
  const {api, mutate, el, n, bytes, stamp, duration, hint, unavailable, badge, button, field, check, heading, option, table, details, state, routes, notice, action, download, dialog, footer} = A;
  const card = (title, ...children) => el("section", {class: "card manage-card"}, el("h2", {}, title), children);
  const emptyRow = (columns, text) => el("tr", {}, el("td", {colspan: columns, class: "empty"}, text));
  const percent = value => value == null ? "Not available yet" : `${Number(value).toLocaleString([], {maximumFractionDigits: 1})}%`;

  routes.set("capacity", async (container, params, revision) => {
    const data = await api("/api/admin/capacity"); if (revision !== state.revision) return;
    const inputs = new Map(), rows = new Map(), bar = el("div", {class: "capacity-savebar", hidden: true, role: "status"});
    const value = row => row.nullable && inputs.get(row.key).value === "" ? null : Number(inputs.get(row.key).value);
    const display = number => number == null ? "No limit" : n(number);
    const changes = () => Object.fromEntries(data.rows.filter(row => value(row) !== row.value || !row.nullable && inputs.get(row.key).value === "").map(row => [row.key, value(row)]));
    const update = () => {
      const changed = changes(), entries = data.rows.filter(row => row.key in changed);
      for (const row of data.rows) rows.get(row.key).classList.toggle("changed", row.key in changed);
      bar.hidden = !entries.length;
      const restart = entries.some(row => row.restart);
      bar.replaceChildren(el("div", {}, el("strong", {}, `${entries.length} unsaved change${entries.length === 1 ? "" : "s"}`),
        el("p", {}, entries.map(row => `${row.label} ${display(row.value)} → ${display(changed[row.key])}`).join(" · ")),
        restart ? el("small", {}, "vLLM requests take effect after a model restart.") : el("small", {}, "Applies live. Existing work keeps its current limits.")),
      el("div", {class: "actions"}, button("Discard", () => { for (const row of data.rows) inputs.get(row.key).value = row.value ?? ""; update(); }),
        button(restart && data.model_restart_available ? "Save and restart model…" : "Save…", save, "primary")));
    };
    function save() {
      for (const input of inputs.values()) if (!input.reportValidity()) return;
      const changed = changes(), entries = data.rows.filter(row => row.key in changed);
      const d = dialog("Save capacity settings"), error = el("p", {class: "error", role: "alert"});
      const needsRestart = entries.some(row => row.restart), restart = check("Restart the model after saving", needsRestart && data.model_restart_available);
      const submit = button("Save changes", () => action(submit, error, async () => {
        const result = await mutate("/api/admin/capacity", {values: changed, expected: data.values, confirm: true, restart_model: needsRestart && data.model_restart_available && restart.input.checked}, "PATCH");
        d.close(); await A.route(); notice(result.restart ? "Settings saved. Model restart requested; check Health for its status." : result.restart_required.length ? "Settings saved. A model restart is still required." : "Settings saved and applied. The change is recorded in Activity.");
      }), "primary");
      d.node.append(el("p", {}, "Review these changes. They apply to all users and are recorded in Activity."),
        details(entries.map(row => [row.label, `${display(row.value)} → ${display(changed[row.key])}${row.unit ? ` ${row.unit}` : ""}`])),
        needsRestart && data.model_restart_available ? restart.label : needsRestart ? hint("The model must be restarted by the operator before its new request limit takes effect.") : hint("These changes apply without restarting the service."), error, footer(d, submit)); d.open();
    }
    container.replaceChildren(heading("Capacity settings", "How much work GraphMine can do at once. Changes apply to everyone."));
    const pending = data.rows.filter(row => row.effective != null && row.value !== row.effective);
    if (pending.length) container.append(el("div", {class: "notice warning"}, `${pending.map(row => `${row.label}: saved ${n(row.value)}, currently ${n(row.effective)}`).join(" · ")}. A model restart is pending. `, el("a", {href: "#model"}, "Open Model")));
    for (const section of [...new Set(data.rows.map(row => row.section))]) {
      const list = el("div", {class: "capacity-rows"});
      for (const row of data.rows.filter(row => row.section === section)) {
        const input = el("input", {id: `capacity-${row.key}`, type: "number", min: row.minimum, max: row.maximum, step: 1, required: !row.nullable, value: row.value ?? "", placeholder: row.nullable ? "No limit" : "", "aria-label": row.label});
        inputs.set(row.key, input); input.addEventListener("input", update);
        const limit = row.maximum === Number.MAX_SAFE_INTEGER ? `${n(row.minimum)} or more` : `${n(row.minimum)}–${n(row.maximum)}`;
        const node = el("div", {class: "capacity-row"}, el("div", {}, el("label", {for: input.id, class: "capacity-label"}, row.label), row.restart ? badge("Model restart", "warning") : null, hint(row.description)),
          el("div", {class: "capacity-value"}, input, row.unit ? el("span", {class: "hint"}, row.unit) : null),
          el("div", {class: "capacity-baseline"}, `Was ${display(row.value)} · default ${display(row.default)}`, el("br"), `Allowed ${limit}${row.nullable ? ", or blank for no limit" : ""}`, row.effective_reason ? hint(`Not available yet · ${row.effective_reason}`) : null),
          button("Reset", () => { input.value = row.default ?? ""; update(); }, "quiet"));
        rows.set(row.key, node); list.append(node);
      }
      container.append(card(section, list));
    }
    container.append(hint("Reset restores the built-in default for that row; Save is still required. Individual user limits are managed on the Users page."), bar);
  });

  async function cleanupPreview(kind, days = 90, identifier = null) {
    const query = new URLSearchParams({kind, days: String(days)}); if (identifier) query.set("file_id", identifier);
    const preview = await api(`/api/admin/data/cleanup-preview?${query}`), d = dialog(kind === "unused" ? "Delete unused files" : "Delete older results");
    const error = el("p", {class: "error", role: "alert"});
    const submit = button(`Delete ${n(preview.count)} ${kind === "unused" ? "files" : "results"}`, () => action(submit, error, async () => {
      const result = await mutate("/api/admin/data/cleanup", {kind, days, identifiers: preview.items.map(row => row.id), preview_token: preview.preview_token, confirm: true});
      d.close(); await A.route(); notice(`Removed ${n(result.removed)} items (${bytes(result.bytes)}).${result.cleanup.pending ? " Some files await a filesystem cleanup retry; their references have been removed." : " The change is recorded in Activity."}`);
    }), "danger"); submit.disabled = !preview.count;
    d.node.append(el("p", {}, `${n(preview.count)} eligible ${kind === "unused" ? "files" : "results"} · ${bytes(preview.bytes)}. This cannot be undone.`), hint(preview.reason),
      preview.total > preview.count ? hint(`Showing the first ${n(preview.count)} of ${n(preview.total)} eligible items. Preview again after this batch.`) : null,
      el("div", {class: "cleanup-preview"}, table(["File / analysis", "Owner", "Size"], preview.items.length ? preview.items.map(row => el("tr", {}, el("td", {}, row.name), el("td", {}, row.owner || "Unknown owner"), el("td", {}, bytes(row.size_bytes)))) : [emptyRow(3, "No items are eligible for deletion.")])),
      kind === "results" ? hint("The saved plans and inputs remain. Results can be calculated again. Embedded database space may be reused without immediately shrinking the database file; archived history has its own retention policy.") : null,
      error, footer(d, submit)); d.open();
  }

  function restoreBackup(snapshot) {
    const d = dialog("Restore snapshot"), typed = el("input", {autocomplete: "off"}), error = el("p", {class: "error", role: "alert"});
    const submit = button("Restore to a new directory", () => action(submit, error, async () => {
      const result = await mutate(`/api/admin/data/backups/${encodeURIComponent(snapshot.name)}/restore`, {confirm: true, confirm_name: typed.value});
      d.close(); notice(`${result.reason} Restored data directory: ${result.data_root}`);
    }), "danger"); submit.disabled = true;
    typed.addEventListener("input", () => { submit.disabled = typed.value !== snapshot.name; });
    d.node.append(el("p", {}, "The snapshot is verified and restored into a new directory using GraphMine's restore-backup command. An operator must switch the service to that directory to activate it."),
      details([["Snapshot", snapshot.name], ["Created", stamp(snapshot.created_at)], ["Size", bytes(snapshot.size_bytes)]]), field(`Type ${snapshot.name} to confirm`, typed), error, footer(d, submit)); d.open();
  }

  routes.set("data", async (container, params, revision) => {
    const data = await api("/api/admin/data"); if (revision !== state.revision) return;
    const filter = params.get("filter") || "all", selected = data.files.filter(row => filter === "unused" ? !row.used_by.length : filter === "large" ? row.size_bytes > 100 * 2 ** 20 : true);
    const palette = ["#16734b", "#9dc7b1", "#ee7b2d", "#4e82b4", "#d5e4da"];
    const storage = card("Storage", el("div", {class: "storage-headline"}, el("div", {}, el("strong", {}, bytes(data.total_bytes)), el("span", {}, " total stored")), el("span", {class: data.disk.percent >= 80 ? "warning" : "hint"}, `${bytes(data.disk.used)} of ${bytes(data.disk.total)} disk used · ${percent(data.disk.percent)}`)),
      el("div", {class: "storage-stack", role: "img", "aria-label": data.categories.map(row => `${row.name}: ${bytes(row.bytes)}`).join(", ")}, data.categories.map((row, i) => el("span", {style: `width:${data.total_bytes ? row.bytes / data.total_bytes * 100 : 0}%;background:${palette[i]}`, title: `${row.name}: ${bytes(row.bytes)}`}))),
      el("div", {class: "storage-legend"}, data.categories.map((row, i) => el("span", {}, el("i", {style: `background:${palette[i]}`}), row.name, el("strong", {}, bytes(row.bytes))))));
    const filters = el("div", {class: "chips"}, ...[["all", "All"], ["unused", "Not used by anything"], ["large", "Over 100 MB"]].map(([value, label]) => button(label, () => { location.hash = `data?filter=${value}`; }, filter === value ? "primary" : "")));
    const files = card("Files", filters, table(["File", "Owner", "Size", "Used by", "Last used", ""], selected.length ? selected.map(row => {
      const remove = button("Delete", () => cleanupPreview("unused", 90, row.id).catch(error => notice(error.message, true)), "danger quiet");
      remove.disabled = !row.deletable; remove.title = row.used_by.length ? "Referenced by saved work" : row.busy ? "This owner has active work" : !row.managed ? "Outside the managed data directory" : "Preview deletion";
      const get = button("Download", () => download(`/api/admin/data/files/${encodeURIComponent(row.id)}/download`, row.name), "quiet"); get.disabled = !row.managed;
      return el("tr", {}, el("td", {class: "storage-filename"}, el("strong", {}, row.name)), el("td", {}, row.owner || "Unknown owner"), el("td", {}, bytes(row.size_bytes)),
        el("td", {title: row.used_by.join("\n")}, row.analyses ? `${n(row.analyses)} analyses` : row.used_by[0] || badge("Nothing", "warning"), row.used_by.length > row.analyses && row.analyses ? hint("Also used by saved data") : null),
        el("td", {}, row.last_used ? stamp(row.last_used) : "Not recorded yet"), el("td", {}, el("div", {class: "row-actions"}, get, remove)));
    }) : [emptyRow(6, "No files match this filter.")]), hint("Referenced files cannot be deleted here. Downloads and cleanup are recorded in Activity."));
    const age = el("select", {"aria-label": "Result retention period"}, option(90, "90 days"), option(180, "180 days"));
    const clean = card("Clean up", el("p", {}, el("strong", {}, `${n(data.unused_count)} eligible unused files`), el("br"), `${bytes(data.unused_bytes)} · no saved references or active owner work`),
      button("Delete unused files…", () => cleanupPreview("unused").catch(error => notice(error.message, true))),
      el("hr"), el("p", {}, "Delete results not opened for"), el("div", {class: "actions"}, age, button("Preview…", () => cleanupPreview("results", Number(age.value)).catch(error => notice(error.message, true)))), hint(`Access tracking began ${stamp(data.access_recording_since)}. A preview explains what can be removed.`));
    const users = card("Storage by user", data.users.length ? data.users.map(row => el("div", {class: "storage-user"}, el("div", {}, el("strong", {}, row.username), el("span", {}, `${bytes(row.used)} / ${bytes(row.limit)}`)), el("progress", {value: row.used, max: row.limit || 1, "aria-label": `${row.username} storage`}))) : unavailable("No accounts have storage measurements"));
    const backupInfo = data.backups, backupError = el("p", {class: "error", role: "alert"}), select = el("select", {"aria-label": "Snapshot"}, backupInfo.items.map(row => option(row.name, `${stamp(row.created_at)} · ${row.name}`))), status = el("div");
    const updateSnapshot = () => {
      const snapshot = backupInfo.items.find(row => row.name === select.value);
      if (!snapshot) { status.replaceChildren(hint("No snapshots have been created yet.")); return; }
      const verify = button("Verify", () => action(verify, backupError, async () => { await mutate(`/api/admin/data/backups/${encodeURIComponent(snapshot.name)}/verify`); await A.route(); notice("Snapshot integrity verified."); }));
      status.replaceChildren(details([["Created", stamp(snapshot.created_at)], ["Size", bytes(snapshot.size_bytes)], ["Integrity", snapshot.verified ? `Verified ${stamp(snapshot.verified_at)}` : "Not verified yet"]]), el("div", {class: "actions"}, verify, button("Restore…", () => restoreBackup(snapshot))));
    };
    select.addEventListener("change", updateSnapshot); updateSnapshot();
    const backup = button("Back up now", () => action(backup, backupError, async () => { backup.textContent = "Backing up…"; try { await mutate("/api/admin/data/backups"); await A.route(); notice("Snapshot created and verified."); } finally { backup.textContent = "Back up now"; } }), "primary");
    const backups = card("Backups", backupInfo.items.length ? select : null, status, backup, backupError,
      hint(backupInfo.scheduled ? `Every ${n(backupInfo.interval_hours)} hours · keep ${n(backupInfo.keep)} scheduled snapshots.` : `Automatic backups are not configured. Manual snapshots are available; retention is ${n(backupInfo.keep)} for scheduled snapshots.`),
      hint("Manual snapshots are retained until removed by the operator. Restore stages data in a new directory."), el("a", {href: "#capacity"}, "Retention settings"));
    container.replaceChildren(heading("Data & storage", "Uploaded files, saved analyses and backups.", button("Refresh", () => A.route())), storage, el("div", {class: "storage-layout"}, files, el("div", {class: "storage-sidebar"}, clean, users, backups)), hint(data.scope));
  });

  function startPerformance(data) {
    const d = dialog("Start a performance test"), type = el("select", {}, data.allowed_tests.map(value => option(value, value === "load" ? "Load · 10 users" : value === "benchmark" ? "Benchmark · 1 user" : value[0].toUpperCase() + value.slice(1)))),
      label = el("input", {required: true, maxlength: 60, pattern: "[A-Za-z0-9][A-Za-z0-9_-]{0,59}", placeholder: "capacity-review"}), slot = el("input", {required: true, maxlength: 200, placeholder: "Agreed date and time window"}), error = el("p", {class: "error", role: "alert"});
    const submit = button("Start test", () => { if (!label.reportValidity() || !slot.reportValidity()) return; return action(submit, error, async () => {
      await mutate("/api/admin/performance/start", {test: type.value, label: label.value, lab_window: slot.value, confirm: true}); d.close(); await A.route(); notice("Test requested. Progress appears here while it runs.");
    }); }, "primary");
    d.node.append(el("div", {class: "notice warning"}, "Tests use the shared model and GPU. Record the agreed slot before starting. Stress, spike and soak require the operator's shared-GPU setting."),
      field("Test", type), field("Run label", label, "Letters, numbers, hyphens and underscores."), field("Agreed time slot", slot), hint("The suite creates isolated test accounts and storage. Its model workload still shares this deployment's GPU."), error, footer(d, submit)); d.open();
  }

  routes.set("performance", async (container, params, revision) => {
    const chosen = new Set();
    const render = async () => {
      const data = await api("/api/admin/performance"); if (revision !== state.revision) return;
      const comparison = card("Compare selected", hint("Select two completed runs above to compare their headline numbers."));
      const format = (value, unit) => value == null ? "Not available yet" : unit === "ms" ? duration(value) : unit === "%" ? percent(value) : unit === "MiB" ? `${n(value)} MiB` : n(value);
      const compare = button("Compare selected (0)", () => { updateCompare(); comparison.scrollIntoView({behavior: "smooth", block: "center"}); });
      const updateCompare = () => {
        compare.textContent = `Compare selected (${chosen.size})`; compare.disabled = chosen.size !== 2;
        if (chosen.size !== 2) { comparison.replaceChildren(el("h2", {}, "Compare selected"), hint("Select two completed runs above to compare their headline numbers.")); return; }
        const [before, after] = data.runs.filter(row => chosen.has(row.id)).sort((a, b) => (a.created_at || 0) - (b.created_at || 0));
        comparison.replaceChildren(el("h2", {}, "Compare selected"), hint(`${before.label} → ${after.label}`), table(["Metric", "Before", "After", "Change"], data.metrics.map(metric => {
          const a = before.metrics[metric.key], b = after.metrics[metric.key], delta = a == null || b == null ? null : b - a;
          return el("tr", {}, el("td", {}, metric.label), el("td", {}, format(a, metric.unit)), el("td", {}, format(b, metric.unit)), el("td", {class: delta == null || delta === 0 ? "" : delta < 0 ? "metric-better" : "metric-worse"}, delta == null ? "Not available yet" : `${delta > 0 ? "+" : ""}${format(delta, metric.unit)}`));
        })), hint("Not available yet means the report did not record that metric. Lower values are green. Compare equivalent workloads and review answer quality alongside timing and token changes."));
      };
      const runs = card("Test runs", table(["", "Run", "Type", "Date", "Users", "Answer p50", "p95", "Error %", "Flags", ""], data.runs.length ? data.runs.map(row => {
        const select = check(`Select ${row.label}`, chosen.has(row.id)); select.input.disabled = !row.summary_available;
        select.input.setAttribute("aria-label", `Select ${row.label}`);
        select.input.addEventListener("change", () => { if (select.input.checked) chosen.add(row.id); else chosen.delete(row.id); updateCompare(); });
        return el("tr", {}, el("td", {}, select.input), el("td", {}, el("strong", {}, row.label), hint(row.settings_note)), el("td", {}, badge(row.type)), el("td", {}, stamp(row.created_at)), el("td", {}, n(row.users)),
          el("td", {}, duration(row.metrics.answer_p50_ms)), el("td", {}, duration(row.metrics.answer_p95_ms)), el("td", {}, percent(row.metrics.question_error_percent)), el("td", {}, row.summary_available ? badge(n(row.flags.length), row.flags.length ? "warning" : "active") : "Pending"),
          el("td", {}, row.report ? el("a", {class: "btn quiet", href: `/api/admin/performance/runs/${encodeURIComponent(row.id)}/report`, target: "_blank", rel: "noopener"}, "Open report") : badge(row.status)));
      }) : [emptyRow(10, "No tests have run yet.")]));
      const latest = data.runs.find(row => row.summary_available), flags = card("Flags from the latest run", latest ? hint(latest.label) : null,
        latest ? latest.flags.length ? el("ul", {class: "performance-flags"}, latest.flags.map(flag => el("li", {}, flag.message))) : hint("No flags were reported in this run.") : unavailable("A completed test report is needed"),
        el("div", {class: "actions"}, el("a", {class: "btn", href: "#capacity"}, "Capacity settings"), el("a", {class: "btn", href: "#model"}, "Model")));
      for (const id of chosen) if (!data.runs.some(row => row.id === id)) chosen.delete(id);
      updateCompare();
      container.replaceChildren(heading("Performance", "Recorded tests on this server. Compare runs before changing capacity.", compare, data.installed ? button("Start a test…", () => startPerformance(data), "primary") : null),
        el("div", {class: "notice warning"}, "Stress, spike and soak tests use the shared GPU and need an agreed slot. Run them when the lab has agreed it is safe to do so."),
        ...(!data.installed ? [el("div", {class: "notice"}, el("strong", {}, "Performance suite isn't installed. "), data.install_reason, " ", el("a", {href: data.install_url, target: "_blank", rel: "noopener"}, "Review the performance suite"))] : []),
        ...data.jobs.filter(row => ["starting", "running", "failed", "interrupted"].includes(row.status)).slice(0, 3).map(row => el("div", {class: `notice ${row.status === "failed" || row.status === "interrupted" ? "warning" : ""}`}, el("strong", {}, `${row.label} · ${row.progress}`), row.reason ? hint(row.reason) : hint(`Started ${stamp(row.started_at || row.created_at)} · ${row.type} · agreed slot ${row.lab_window}`))),
        runs, el("div", {class: "performance-lower"}, comparison, flags));
    };
    await render(); state.timer = setInterval(() => render().catch(error => notice(error.message, true)), 5000);
  });
})();
