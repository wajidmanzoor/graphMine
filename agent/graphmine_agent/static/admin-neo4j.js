/* Source for the admin backend card; build.mjs copies it into static assets. */
(() => {
  "use strict";
  let switching = false;
  window.GraphMineNeo4jCard = async () => {
    const A = window.GraphMineAdmin;
    const {api, mutate, el, hint, badge, button, details, bytes, stamp, n, dialog, footer, check} = A;
    const root = el("section", {class: "card", "aria-label": "Neo4j backend"});
    const message = el("p", {role: "status", "aria-live": "polite"});
    let data, buttons = [];
    const names = {local: "Local Neo4j", "iu-remote": "Indiana University"};
    const labels = {connections: "Connections", curated_datasets: "Curated datasets", snapshots: "Saved datasets and snapshots",
      saved_queries: "Saved queries", files: "Imported files", workflows: "Workflows", results: "Results"};
    const setBusy = value => {
      switching = value;
      root.setAttribute("aria-busy", String(value));
      for (const [target, control] of buttons) control.disabled = value || data.switching || data.active_backend === target;
    };
    async function perform(target, force) {
      setBusy(true);
      message.textContent = "Preparing the database switch…";
      let after = 0, timer, polling = false, observing = true;
      const poll = async () => {
        if (polling || !observing) return;
        polling = true;
        try {
          const progress = await api(`/api/database-progress?after=${after}`);
          after = progress.after;
          for (const event of progress.events) {
            if (observing && event.type === "database.switch" && event.payload.backend_id === target
                || observing && event.type === "database.power" && target === "iu-remote") {
              message.textContent = event.payload.message;
            }
          }
        } catch (_) { /* The mutation returns the authoritative outcome. */ }
        finally { polling = false; }
      };
      try {
        after = (await api("/api/database-progress")).after;
        timer = setInterval(poll, 500);
        await mutate("/api/admin/neo4j/switch", {target, force});
        observing = false;
        message.textContent = `${names[target]} is active. Its datasets and saved Neo4j work are now shown.`;
        try { localStorage.setItem("graphmine-backend-changed", String(Date.now())); } catch (_) { /* Optional cross-tab hint. */ }
      } catch (error) {
        observing = false;
        message.textContent = error.message;
      } finally {
        clearInterval(timer);
        try { await load(); } catch (error) { message.textContent += ` ${error.message}`; }
        setBusy(false);
      }
    }
    function confirm(target) {
      if (switching || data.switching) return;
      const d = dialog(`Switch to ${names[target]}?`);
      const force = check("Cancel running database jobs before switching", false);
      const accept = button("Switch backend", () => { d.close(); return perform(target, force.input.checked); }, "primary");
      d.node.append(el("p", {}, `The datasets and saved Neo4j work shown will change to ${names[target]}'s. Uploaded files remain available. Your existing work is kept and reappears when you switch back.`));
      if (data.running_jobs.length) d.node.append(hint(`${n(data.running_jobs.length)} database jobs are running.`), force.label);
      d.node.append(footer(d, accept)); d.open();
    }
    async function load() {
      data = await api("/api/admin/neo4j");
      buttons = [];
      const cards = Object.keys(names).map(target => {
        const local = target === "local", status = local ? data.local : data.remote;
        const active = data.active_backend === target;
        const controls = button("Switch", () => confirm(target));
        controls.disabled = switching || data.switching || active;
        buttons.push([target, controls]);
        const state = local ? (status.units.some(unit => unit.active === "active") ? "Running" : "Parked")
          : !status.vpn_reachable ? "VPN tunnel is down" : status.is_up ? "Running" : "Asleep or unavailable";
        const rows = local ? [["Status", state], ["RAM", bytes(status.rss_bytes)]]
          : [["Status", state], ["Started by GraphMine", status.started_by_graphmine ? "Yes" : "No"],
             ["Last used", status.last_used ? stamp(status.last_used) : "No recorded use"],
             ["Automatic wake / sleep", status.autowake ? `On · idle ${n(status.idle_minutes)} minutes` : "Off"]];
        const unitDetails = local ? el("details", {}, el("summary", {}, "Local service states"),
          ...status.units.map(unit => hint(`${unit.unit}: ${unit.active}, ${unit.enabled} · ${bytes(unit.rss_bytes)}`))) : null;
        return el("section", {}, el("h3", {}, names[target], " ", active ? badge("Active", "good") : null),
          details(rows), details(Object.entries(data.record_counts[target]).map(([key, count]) => [labels[key], n(count)])), unitDetails, controls);
      });
      root.replaceChildren(el("h2", {}, "Neo4j backend"), hint("Choose which database supplies this workspace. Switching preserves saved work in both backends."),
        el("div", {class: "field-row"}, cards), message);
      if (data.switching && !switching) message.textContent = "A database switch is in progress. Refresh to see its outcome.";
    }
    try { await load(); }
    catch (error) { root.replaceChildren(el("h2", {}, "Neo4j backend"), hint(error.message)); }
    return root;
  };
})();
