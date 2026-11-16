"use strict";
window.GraphMineHome = ({state, api, W, node, runAction, onDataset}) => {
  const host = node("section", {id: "home-recents", class: "home-recents", "aria-labelledby": "home-recents-heading", hidden: true});
  const header = node("div", {class: "section-heading"}), refresh = node("button", {id: "refresh-home-recents", type: "button", class: "quiet"}, "Refresh saved work");
  header.append(node("h2", {id: "home-recents-heading"}, "Your saved work"), refresh);
  const grid = node("div", {class: "home-recent-grid"}); host.append(header, grid);
  document.querySelector(".database-start").before(host);
  const hero = document.getElementById("domain-heading"), originalTitle = hero.textContent;
  const sections = new Map();
  let active = false, generation = 0, controller = null;
  const date = value => { const time = new Date(value); return Number.isFinite(time.getTime()) ? time.toLocaleDateString(undefined, {month: "short", day: "numeric", year: "numeric"}) : "Saved"; };
  for (const [key, title, empty] of [
    ["analyses", "Recent analyses", "Your saved plans and results will appear here."],
    ["datasets", "Recent datasets", "Save an input or query result to reuse it here."],
  ]) {
    const section = node("section", {class: "home-recent-section", "aria-labelledby": `home-${key}-heading`});
    const list = node("ul", {id: `home-${key}`, class: "home-recent-list"});
    const status = node("p", {class: "muted", role: "status"});
    const more = node("button", {type: "button", class: "quiet", hidden: true, "data-more-recent": key}, "Show more");
    section.append(node("h3", {id: `home-${key}-heading`}, title), list, status, more); grid.append(section);
    const entry = {key, list, status, more, empty, items: [], offset: 0, failed: false, pending: false};
    sections.set(key, entry); more.onclick = () => load(entry, entry.items.length > 0);
  }
  const dialog = node("dialog", {id: "home-dataset-dialog", class: "home-dataset-dialog", "aria-labelledby": "home-dataset-heading"});
  const title = node("h2", {id: "home-dataset-heading"}), detail = node("p", {class: "muted"});
  const domain = node("select", {id: "home-dataset-domain"}), label = node("label", {}, "Conversation domain"); label.append(domain);
  const error = node("p", {id: "home-dataset-status", role: "status"});
  const start = node("button", {id: "start-dataset-conversation", type: "button", class: "primary"}, "Start conversation");
  const close = node("button", {type: "button", class: "quiet"}, "Cancel"); close.onclick = () => dialog.close();
  dialog.addEventListener("cancel", event => { if (close.disabled) event.preventDefault(); });
  const actions = node("div", {class: "form-actions"}); actions.append(close, start);
  dialog.append(title, detail, label, error, actions); document.body.append(dialog);
  function chooseDataset(item) {
    if (state.busy) return;
    title.textContent = item.name;
    detail.textContent = `Version ${item.version} · ${item.kind.replaceAll("_", " ")}. Start with an independent copy of this saved version.${item.source_complete ? "" : " The source result is incomplete."}`;
    domain.replaceChildren(...state.domains.map(d => node("option", {value: d.id}, d.name)));
    domain.value = state.domains.some(d => d.id === "general") ? "general" : state.domains[0]?.id || "";
    error.textContent = ""; start.disabled = !domain.value; dialog.showModal();
    start.onclick = async () => {
      let opened = null;
      await runAction(async () => {
        const current = generation;
        let response;
        start.disabled = close.disabled = domain.disabled = true; error.textContent = "Opening your saved dataset…";
        try {
          response = await api(`/api/datasets/${encodeURIComponent(item.id)}/conversation`, {method: "POST", body: W.stringify({domain_id: domain.value})});
        } catch (failure) {
          if (current === generation && dialog.open) error.textContent = failure.message;
          return;
        } finally { start.disabled = close.disabled = domain.disabled = false; }
        if (current !== generation || !active || !dialog.open) return;
        dialog.close(); if (await onDataset(response)) opened = response;
      });
      if (opened?.kind === "table" && state.session?.id === opened.session.id && state.view === "chat") document.dispatchEvent(new CustomEvent("graphmine:project-table", {detail: {fileId: opened.file.id}}));
    };
  }
  function row(section, item) {
    const li = node("li"), action = node(section === "datasets" ? "button" : "a", {class: "home-recent-link", "data-recent-id": item.id});
    let name, description;
    if (section === "datasets") {
      action.type = "button"; action.onclick = () => chooseDataset(item);
      name = item.name; description = `${item.kind.replaceAll("_", " ")} · version ${item.version}${item.source_complete ? "" : " · incomplete source"}`;
    } else {
      const complete = item.status === "completed";
      action.href = `#workspace/${encodeURIComponent(item.session_id)}/${complete ? "results" : "chat"}/${encodeURIComponent(item.id)}`;
      name = item.conversation || "Untitled conversation";
      const intent = item.status === "awaiting_review" ? "Review plan" : ["queued", "running"].includes(item.status) ? "Follow progress"
        : ["failed", "cancelled", "interrupted"].includes(item.status) ? "Review recovery" : complete ? "View results" : "Open analysis";
      description = `${intent} · ${item.status.replaceAll("_", " ")} · ${(item.operations || []).join(", ")}`;
    }
    action.append(node("strong", {}, name), node("span", {}, description), node("span", {class: "home-recent-date"}, date(item.updated_at)));
    li.append(action); return li;
  }
  function visibility() {
    const any = [...sections.values()].some(section => section.items.length);
    host.hidden = !any && ![...sections.values()].some(section => section.failed || section.pending);
    document.getElementById("domain-view").classList.toggle("returning-home", any);
    hero.textContent = any ? "Pick up where you left off." : originalTitle;
  }
  async function load(section, append = false) {
    if (!active || section.pending) return;
    const current = generation, offset = append ? section.offset : 0;
    section.pending = true; section.failed = false; section.status.textContent = "Loading…"; section.more.disabled = true;
    section.list.setAttribute("aria-busy", "true"); visibility();
    try {
      const result = await api(`/api/workspace/recent/${section.key}?limit=4&offset=${offset}`, {signal: controller.signal});
      if (current !== generation || !active) return;
      if (!Array.isArray(result.items)) throw new Error("Saved work could not be read. Try again.");
      section.items = append ? [...new Map([...section.items, ...result.items].map(item => [item.id, item])).values()] : result.items;
      section.offset = offset + result.items.length;
      section.list.replaceChildren(...section.items.map(item => row(section.key, item)));
      section.status.textContent = section.items.length ? "" : section.empty;
      section.more.hidden = !result.has_more; section.more.textContent = "Show more";
    } catch (error) {
      if (current !== generation || error.name === "AbortError") return;
      section.failed = true; section.status.textContent = `Could not load ${section.key}. ${error.message}`;
      section.more.hidden = false; section.more.textContent = "Try again";
    } finally {
      if (current === generation) { section.pending = false; section.more.disabled = false; section.list.setAttribute("aria-busy", "false"); visibility(); }
    }
  }
  function reload() {
    controller?.abort(); controller = new AbortController(); generation++;
    for (const section of sections.values()) { section.pending = false; section.items = []; section.offset = 0; section.more.hidden = true; section.list.replaceChildren(); void load(section); }
  }
  refresh.onclick = reload;
  document.addEventListener("visibilitychange", () => { if (active && !document.hidden && !dialog.open) reload(); });
  return {
    setActive(value) {
      if (value === active) return;
      active = value;
      if (value) reload();
      else { generation++; controller?.abort(); if (dialog.open) dialog.close(); }
    },
    reset() { active = false; generation++; controller?.abort(); if (dialog.open) dialog.close(); for (const section of sections.values()) { section.items = []; section.offset = 0; section.list.replaceChildren(); section.failed = section.pending = false; } visibility(); },
  };
};
