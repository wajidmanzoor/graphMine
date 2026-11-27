/* GraphMine's administrator console. All measurements come from the agent API. */
(() => {
  "use strict";
  const $ = selector => document.querySelector(selector);
  const transport = window.GraphMineTransport({state: {base: "", token: ""}, W: window.AnalyticsWire});
  const api = (path, options = {}) => transport(path, {...options, credentials: "same-origin", headers: {"X-GraphMine-Request": "1", ...options.headers}});
  const mutate = (path, body = {}, method = "POST") => api(path, {method, body: JSON.stringify(body)});
  const el = (tag, attrs = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value == null || value === false) continue;
      if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
      else if (key === "checked" || key === "disabled" || key === "hidden") node[key] = Boolean(value);
      else node.setAttribute(key, value === true ? "" : String(value));
    }
    for (const child of children.flat(Infinity)) if (child != null) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    return node;
  };
  const n = value => value == null ? "Not available yet" : Number(value).toLocaleString();
  const bytes = value => value == null ? "Not available yet" : value >= 2 ** 30 ? `${(value / 2 ** 30).toLocaleString([], {maximumFractionDigits: 2})} GB` : value >= 2 ** 20 ? `${(value / 2 ** 20).toLocaleString([], {maximumFractionDigits: 1})} MB` : `${n(value)} bytes`;
  const stamp = value => value == null ? "Not available yet" : new Date(typeof value === "number" ? value * 1000 : value).toLocaleString([], {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
  const duration = value => value == null ? "Not available yet" : `${(value / 1000).toLocaleString([], {maximumFractionDigits: 2})} s`;
  const hint = text => el("p", {class: "hint"}, text);
  const unavailable = reason => el("div", {class: "empty"}, el("strong", {}, "Not available yet"), hint(reason));
  const badge = (text, kind = "") => el("span", {class: `tag ${kind}`}, text);
  const button = (text, action, style = "") => el("button", {type: "button", class: `btn ${style}`, onclick: action}, text);
  const field = (label, control, help) => el("label", {class: "field"}, label, control, help ? hint(help) : null);
  const check = (label, checked = false) => { const input = el("input", {type: "checkbox", checked}); return {input, label: el("label", {class: "check"}, input, label)}; };
  const heading = (title, subtitle, ...actions) => el("div", {class: "page-heading"}, el("div", {}, el("h1", {}, title), el("p", {class: "subtitle"}, subtitle)), el("div", {class: "actions"}, actions));
  const option = (value, text) => el("option", {value}, text);
  const table = (headers, rows) => el("div", {class: "card flush"}, el("div", {class: "table-scroll"}, el("table", {}, el("thead", {}, el("tr", {}, headers.map(x => el("th", {scope: "col"}, x)))), el("tbody", {}, rows))));
  const details = entries => el("dl", {class: "details"}, entries.flatMap(([name, value]) => [el("dt", {}, name), el("dd", {}, value ?? "Not available yet")]));
  const state = {user: null, users: null, route: null, revision: 0, timer: null, supportTimer: null, now: null};
  const routes = new Map();
  const iconPaths = {
    overview: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
    health: "M2 12h5l3-8 4 16 3-8h5", activity: "M4 5h16 M4 12h16 M4 19h11",
    usage: "M3 21h18 M6 18V9 M12 18V3 M18 18V12", performance: "M3 17a9 9 0 1 1 18 0 M12 15l5-7",
    users: "M16 21v-3a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v3 M16 4a4 4 0 0 1 0 8 M22 21v-3a4 4 0 0 0-3-4 M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
    jobs: "M3 4h18v6H3z M3 14h18v6H3z M7 7h1 M7 17h1",
    model: "M5 6h14v15H5z M9 6V3h6v3 M9 11h6 M9 15h6", data: "M3 5c0-4 18-4 18 0s-18 4-18 0 M3 5v14c0 4 18 4 18 0V5 M3 12c0 4 18 4 18 0",
    capacity: "M5 2v6 M5 12v10 M2 8h6v4H2z M12 2v12 M12 18v4 M9 14h6v4H9z M19 2v3 M19 9v13 M16 5h6v4h-6z",
    semantic: "M5 6h14v15H5z M9 6V3h6v3 M9 11h6 M9 15h6",
  };
  function navIcon(key) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"), path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true"); svg.classList.add("nav-icon");
    path.setAttribute("d", iconPaths[key]); svg.append(path); return svg;
  }
  const groups = [
    ["Monitor", [["overview", "Overview", "◫"], ["health", "Health", "♡"], ["activity", "Activity", "≋"], ["usage", "Usage analytics", "▥"], ["performance", "Performance", "↗"]]],
    ["Manage", [["users", "Users", "♙"], ["jobs", "Jobs & queue", "☷"], ["model", "Model", "◇"], ["data", "Data & storage", "▤"]]],
    ["Configure", [["capacity", "Capacity settings", "☷"], ["semantic", "Semantic engine", "◇"]]],
  ];
  const titles = Object.fromEntries(groups.flatMap(([, items]) => items.map(([route, title]) => [route, title])));
  function notice(text = "", error = false) {
    const node = $("#page-notice"); node.className = `notice${error ? " error" : ""}`; node.textContent = text;
  }
  async function action(control, target, work) {
    control.disabled = true; target.textContent = "";
    try { return await work(); }
    catch (error) { target.textContent = error.message; target.setAttribute("role", "alert"); }
    finally { if (control.isConnected) control.disabled = false; }
  }
  async function download(path, filename) {
    try {
      const blob = await api(path, {asBlob: true});
      const url = URL.createObjectURL(blob), link = el("a", {href: url, download: filename});
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { notice(error.message, true); }
  }
  function dialog(title, drawer = false) {
    if (drawer) for (const previous of document.querySelectorAll("dialog.drawer")) previous.close();
    const node = el("dialog", {class: drawer ? "drawer" : "", "aria-label": title});
    const panel = drawer && $("#page-content .panel-layout");
    if (panel) { node.classList.add("inline-panel"); panel.classList.add("has-panel"); }
    const close = button("×", () => node.close(), "quiet close"); close.setAttribute("aria-label", "Close");
    node.append(el("div", {class: "dialog-head"}, el("h2", {}, title), close));
    node.addEventListener("close", () => { if (panel) panel.classList.remove("has-panel"); for (const input of node.querySelectorAll("input")) input.value = ""; node.replaceChildren(); node.remove(); });
    (panel || $("#dialog-root")).append(node);
    return {node, open: () => panel ? node.show() : node.showModal(), close: () => node.close()};
  }
  function footer(d, submit, cancelText = "Cancel") { return el("div", {class: "dialog-footer"}, button(cancelText, d.close), submit); }
  function studioNotice(result) {
    if (result.studio && !result.studio.ok) notice(`${result.studio.message}. ${result.studio.reason}`, true);
  }
  function oneTimePassword(username, password) {
    const d = dialog(`Temporary password for ${username}`);
    d.node.append(hint("Copy this password now and share it privately. It will not be shown again."), el("div", {class: "password-value"}, password));
    const message = el("p", {class: "form-notice", role: "status"});
    const copy = button("Copy password", event => action(event.currentTarget, message, async () => { await navigator.clipboard.writeText(password); message.textContent = "Copied"; }));
    d.node.append(message, el("div", {class: "dialog-footer"}, copy, button("Done", d.close, "primary"))); d.open();
  }
  function userFields(user = {}, defaults = {}, roleCards = false) {
    const editing = Boolean(user.id);
    const name = el("input", {value: user.username || "", required: true, minlength: 3, maxlength: 64, autocomplete: "off", pattern: "[a-z0-9][a-z0-9_.-]{2,63}"});
    const role = el("select", {}, option("user", "Member"), option("admin", "Administrator")); role.value = user.role || "user";
    const tokens = el("input", {type: "number", min: 0, max: state.users.server_token_limit, step: 1, value: user.daily_token_limit ?? (editing ? "" : defaults.daily_token_limit ?? ""), placeholder: defaults.daily_token_limit == null ? "" : `Default: ${n(defaults.daily_token_limit)}`});
    const storage = el("input", {type: "number", min: 1, step: 1, value: user.storage_limit ?? (editing ? "" : defaults.storage_limit ?? ""), placeholder: defaults.storage_limit == null ? "" : `Default: ${bytes(defaults.storage_limit)}`});
    const graphmine = check("GraphMine", user.graphmine_access ?? true), studio = check("Dataset Studio", Boolean(user.studio_access));
    const explanation = hint(role.value === "admin" ? "Administrators manage users, services, and server settings." : "Members use GraphMine with their assigned allowances.");
    role.addEventListener("change", () => { explanation.textContent = role.value === "admin" ? "Administrators manage users, services, and server settings." : "Members use GraphMine with their assigned allowances."; });
    const choices = el("fieldset", {class: "choice-group"}, el("legend", {}, "Role"), [["user", "Member", "Uses GraphMine with their own daily limits."], ["admin", "Administrator", "Can open this console and change users, limits and settings."]].map(([value, title, text]) => el("label", {class: "choice-card"}, el("input", {type: "radio", name: "new-user-role", value, checked: value === role.value, onchange: () => { role.value = value; }}), el("span", {}, el("strong", {}, title), hint(text)))));
    const nodes = [field("Username", name), roleCards ? choices : field("Role", role), roleCards ? null : explanation, el("div", {class: "field-row"}, field("Daily tokens", tokens, "Blank uses the new-user default."), field("Storage limit (bytes)", storage, "Blank uses the new-user default.")), el("p", {class: "form-heading"}, "Access"), graphmine.label, studio.label].filter(Boolean);
    return {nodes, values: () => ({username: name.value, role: role.value, daily_token_limit: tokens.value === "" ? null : Number(tokens.value), storage_limit: storage.value === "" ? null : Number(storage.value), graphmine_access: graphmine.input.checked, studio_access: studio.input.checked})};
  }
  function addUser() {
    const d = dialog("Add user"), form = el("form"), fields = userFields({}, state.users.defaults, true);
    const password = el("input", {type: "password", minlength: 12, maxlength: 128, autocomplete: "new-password", placeholder: "Generate on create"});
    const generate = button("Generate", () => { const raw = crypto.getRandomValues(new Uint8Array(20)); password.value = Array.from(raw, x => x.toString(16).padStart(2, "0")).join(""); password.type = "text"; });
    const must = check("Must change password at first sign-in", true), message = el("p", {class: "form-notice", role: "status"});
    const submit = el("button", {type: "submit", class: "btn primary"}, "Create user");
    form.append(fields.nodes[0], field("Temporary password", el("div", {class: "actions"}, password, generate)), must.label, ...fields.nodes.slice(1), message, footer(d, submit));
    form.addEventListener("submit", event => { event.preventDefault(); action(submit, message, async () => {
      const result = await mutate("/api/admin/users", {...fields.values(), password: password.value || null, must_change_password: must.input.checked});
      d.close(); await route(); notice(`Created ${result.user.username}.`); studioNotice(result);
      if (result.temporary_password) oneTimePassword(result.user.username, result.temporary_password);
    }); });
    d.node.append(form); d.open();
  }
  async function simpleUserAction(user, kind, control, message) {
    return action(control, message, async () => {
      const result = await mutate(`/api/admin/users/${encodeURIComponent(user.username)}/${kind}`);
      if (result.temporary_password) oneTimePassword(user.username, result.temporary_password);
      else message.textContent = kind === "force-signout" ? `${n(result.sessions_removed)} sessions removed.` : "Saved.";
      await refreshUsers(); studioNotice(result);
    });
  }
  function openActivity(user) { for (const node of $("#dialog-root").querySelectorAll("dialog")) node.close(); location.hash = `activity?user_id=${encodeURIComponent(user.id)}`; }
  function editUser(user) {
    notice();
    const d = dialog(user.username, true), form = el("form"), fields = userFields(user, state.users.defaults);
    const message = el("p", {class: "form-notice", role: "status"}), submit = el("button", {type: "submit", class: "btn primary"}, "Save changes");
    d.node.append(details([["Created", stamp(user.created_at)], ["Created by", user.created_by || "Not available yet · not recorded"], ["Last sign-in", stamp(user.last_sign_in)], ["Failed sign-ins", n(user.failed_sign_ins)]]));
    form.append(...fields.nodes, message, footer(d, submit));
    form.addEventListener("submit", event => { event.preventDefault(); action(submit, message, async () => {
      const result = await mutate(`/api/admin/users/${encodeURIComponent(user.username)}`, fields.values(), "PATCH");
      d.close(); await route(); notice(`Saved changes to ${result.user.username}.`); studioNotice(result);
    }); });
    d.node.append(form, el("hr", {class: "divider"}), el("h3", {}, "Account actions"));
    const tools = el("div", {class: "actions"});
    for (const [label, kind] of [["Reset password", "reset-password"], ["Reset today's tokens", "reset-tokens"], ["Force sign-out", "force-signout"], [user.disabled ? "Enable" : "Disable", user.disabled ? "enable" : "disable"]]) tools.append(button(label, event => simpleUserAction(user, kind, event.currentTarget, message)));
    tools.append(button("View activity", () => openActivity(user)), button("Delete…", async () => { d.close(); await deleteUser(user); }, "danger"));
    if (user.studio_sync_error) tools.append(button("Studio not updated: retry", event => simpleUserAction(user, "studio-sync", event.currentTarget, message)));
    d.node.append(tools); d.open();
  }
  async function deleteUser(user) {
    let preview;
    try { preview = await api(`/api/admin/users/${encodeURIComponent(user.username)}/delete-preview`); }
    catch (error) { notice(error.message, true); return; }
    const d = dialog(`Delete ${user.username}`), form = el("form"), mode = el("select", {}, option("transfer", `Move it to ${state.user.username}`), option("erase", "Erase it permanently"));
    const modes = el("fieldset", {class: "choice-group"}, el("legend", {}, "What happens to their data?"), [["transfer", `Move it to ${state.user.username}`, "Conversations and files stay available to you."], ["erase", "Erase it", "Permanently deleted. This cannot be undone."]].map(([value, title, text]) => el("label", {class: "choice-card"}, el("input", {type: "radio", name: "delete-data", value, checked: value === "transfer", onchange: () => { mode.value = value; }}), el("span", {}, el("strong", {}, title), hint(text)))));
    const name = el("input", {required: true, autocomplete: "off"}), message = el("p", {class: "form-notice", role: "status"});
    const submit = el("button", {class: "btn danger primary", type: "submit"}, "Delete user");
    form.append(hint("Disable keeps the account and all its work. Deleting removes the account and signs out every device."), details([["Conversations", n(preview.conversations)], ["Saved analyses", n(preview.saved_analyses)], ["Uploaded files", `${n(preview.uploaded_files)} · ${bytes(preview.uploaded_bytes)}`], ["Project shares", n(preview.project_shares)], ["Total stored", bytes(preview.storage.stored)]]), modes, field(`Type ${user.username} to confirm`, name), message, footer(d, submit));
    name.addEventListener("input", () => name.setCustomValidity(""));
    form.addEventListener("submit", event => { event.preventDefault(); if (name.value !== user.username) { name.setCustomValidity("Type the username exactly."); name.reportValidity(); return; }
      action(submit, message, async () => {
        const result = await mutate(`/api/admin/users/${encodeURIComponent(user.username)}`, {data: mode.value, confirm: true, confirm_username: name.value}, "DELETE");
        d.close(); await route(); notice(`Deleted ${user.username}.`); studioNotice(result);
        if (result.cleanup?.pending) notice(`Account deleted. ${n(result.cleanup.pending)} file locations still need cleanup.`, true);
      });
    });
    d.node.append(form); d.open();
  }
  function userRow(user) {
    const name = el("div", {}, button(user.username, () => editUser(user), "quiet"), user.id === state.user.id ? badge("you") : null, el("span", {class: "small"}, `Created ${new Date(user.created_at * 1000).toLocaleDateString([], {month: "short", day: "numeric"})}`));
    const meter = el("div", {}, `${n(user.quota.tokens_used)} of ${n(user.quota.token_limit)}`, el("progress", {value: user.quota.tokens_used, max: Math.max(user.quota.token_limit, 1), class: user.quota.tokens_used > user.quota.token_limit * .7 ? "high" : "", "aria-label": `${user.username} token allowance`}));
    const message = el("span", {class: "small", role: "status"});
    const menu = el("details", {class: "row-menu"}, el("summary", {"aria-label": `Actions for ${user.username}`}, "⋯"));
    const items = el("div", {class: "row-menu-content"});
    items.append(button("Edit", () => { menu.open = false; editUser(user); }, "quiet"));
    for (const [label, kind] of [["Reset password", "reset-password"], ["Reset today's tokens", "reset-tokens"], ["Force sign-out", "force-signout"], [user.disabled ? "Enable" : "Disable", user.disabled ? "enable" : "disable"]]) items.append(button(label, event => { menu.open = false; simpleUserAction(user, kind, event.currentTarget, message); }, "quiet"));
    items.append(button("Open activity", () => openActivity(user), "quiet"), button("Delete…", () => { menu.open = false; deleteUser(user); }, "danger quiet")); menu.append(items);
    const access = el("div", {}, user.graphmine_access ? el("span", {class: "small"}, "GraphMine") : null, user.studio_access ? el("span", {class: "small"}, "Dataset Studio") : null);
    if (user.studio_sync_error) access.append(button("Studio not updated: retry", event => simpleUserAction(user, "studio-sync", event.currentTarget, message), "quiet"));
    return el("tr", {}, el("td", {}, el("div", {class: "user-cell"}, el("span", {class: "avatar", "aria-hidden": "true"}, user.username.slice(0, 2).toUpperCase()), name)), el("td", {}, badge(user.role === "admin" ? "Administrator" : "Member", user.role)), el("td", {}, el("span", {class: `status ${user.status.toLowerCase().replaceAll(" ", "-")}`}, user.status)), el("td", {}, access), el("td", {class: "nowrap"}, stamp(user.last_active)), el("td", {}, n(user.questions_7d)), el("td", {}, meter), el("td", {}, bytes(user.storage.stored)), el("td", {}, menu, message));
  }
  async function refreshUsers() {
    state.users = await api("/api/admin/users");
    if (state.route === "users" && state.renderUsers) state.renderUsers();
    await badges();
  }
  routes.set("users", async (container, params, revision) => {
    const data = await api("/api/admin/users"); if (revision !== state.revision) return;
    state.users = data;
    const search = el("input", {class: "search", type: "search", placeholder: "Search users", "aria-label": "Search users"});
    const list = el("div"), pending = el("div"), chips = el("div", {class: "chips"}), subtitle = el("p", {class: "subtitle"}); let filter = "all";
    const chipNodes = new Map();
    for (const [key, label] of [["all", "All"], ["admins", "Admins"], ["members", "Members"], ["disabled", "Disabled"], ["never", "Never signed in"]]) {
      const chip = button(label, () => { filter = key; render(); }); chip.className = "chip"; chipNodes.set(key, {chip, label}); chips.append(chip);
    }
    const render = () => {
      const users = state.users;
      subtitle.textContent = `${n(users.counts.all)} accounts · ${n(users.counts.admins)} administrators · one list for GraphMine and Dataset Studio`;
      pending.replaceChildren(...(users.studio_pending || []).map(item => {
        const message = el("span", {role: "status"});
        return el("div", {class: "warning"}, `${item.username} · Studio not updated: ${item.reason}. `,
          button("Retry Studio update", event => action(event.currentTarget, message, async () => {
            const result = await mutate(`/api/admin/studio-sync/${encodeURIComponent(item.id)}/retry`);
            await refreshUsers(); studioNotice(result);
          })), message);
      }));
      for (const [key, {chip, label}] of chipNodes) { chip.replaceChildren(label, el("span", {class: "count"}, n(users.counts[key]))); chip.setAttribute("aria-pressed", String(filter === key)); }
      const chosen = users.items.filter(user => user.username.includes(search.value.toLowerCase()) && (filter === "all" || filter === "admins" && user.role === "admin" || filter === "members" && user.role === "user" || filter === "disabled" && user.disabled || filter === "never" && user.status === "Never signed in"));
      list.replaceChildren(chosen.length ? table(["User", "Role", "Status", "Access", "Last active", "Questions · 7d", "Tokens today", "Storage", ""], chosen.map(userRow)) : el("div", {class: "card empty"}, "No matching accounts."));
    };
    state.renderUsers = render;
    search.addEventListener("input", render);
    const head = heading("Users", "", button("Export CSV", () => download("/api/admin/users/export", "graphmine-users.csv")), button("+ Add user", addUser, "primary")); head.querySelector(".subtitle").replaceWith(subtitle);
    container.replaceChildren(head, pending, el("div", {class: "toolbar user-filters"}, search, chips), el("div", {class: "panel-layout"}, list),
      hint(`Activity counts are recorded from ${stamp(data.recording_since)}. Earlier activity may not be available.`)); render();
  });
  async function supportDialog(conversationId) {
    const d = dialog("Open conversation with support access"), form = el("form"), reason = el("textarea", {required: true, maxlength: 1000}), period = el("select", {}, option("hour", "1 hour"), option("session", "This session"));
    const message = el("p", {class: "form-notice", role: "status"}), submit = el("button", {type: "submit", class: "btn primary"}, "Open read-only");
    form.append(hint("Support access lets you read this conversation to help its owner. You cannot change it."), el("p", {class: "warning"}, "This access is logged and visible in the user's account history."), field("Reason for access", reason), field("Access lasts", period), message, footer(d, submit));
    form.addEventListener("submit", event => { event.preventDefault(); action(submit, message, async () => {
      const grant = await mutate("/api/admin/support-access", {conversation_id: conversationId, reason: reason.value, duration: period.value});
      d.close(); location.hash = `support?grant=${encodeURIComponent(grant.id)}`;
    }); }); d.node.append(form); d.open();
  }
  function eventDetails(item) {
    const d = dialog("Activity details", true), detail = item.details || {};
    d.node.append(badge(item.type.replaceAll("_", " "), item.type), el("h3", {style: "margin-top:20px"}, item.summary), details([["Time", stamp(item.ts)], ["User", item.username || "Unknown / removed account"], ["Result", item.outcome], ["Duration", duration(item.duration_ms)], ["Request ID", item.request_id]]));
    if (item.type === "admin_change") d.node.append(el("h3", {}, "Before → after"), el("h4", {}, "Before"), el("pre", {class: "code"}, JSON.stringify(detail.before, null, 2)), el("h4", {}, "After"), el("pre", {class: "code"}, JSON.stringify(detail.after, null, 2)));
    else if (item.type === "question") {
      d.node.append(el("hr", {class: "divider"}), el("h3", {}, "Question and conversation"), hint("Question text and conversation content require a support-access grant."));
      const stages = Object.entries(detail.stage_ms || {}), total = stages.reduce((sum, [, value]) => sum + value, 0);
      d.node.append(el("h3", {}, "Where the time went"));
      if (total) d.node.append(el("div", {class: "timing-bar", role: "img", "aria-label": stages.map(([key, value]) => `${key}: ${duration(value)}`).join(", ")}, stages.map(([key, value]) => el("span", {class: "timing-segment", title: `${key}: ${duration(value)}`, style: `width:${value / total * 100}%`}))), ...stages.map(([key, value]) => el("div", {class: "timing-row"}, key, duration(value))));
      else d.node.append(unavailable("Step timing was not recorded for this question."));
      d.node.append(details([["Model queue wait", detail.model_queue_ms == null ? "Not available yet · queue timing was not recorded" : duration(detail.model_queue_ms)], ["Tokens", detail.tokens == null ? "Not available yet · usage was not recorded" : n(detail.tokens)], ["Reasoning tokens", detail.reasoning_tokens == null ? "Not available yet · reasoning usage was not recorded" : n(detail.reasoning_tokens)]]));
      if (detail.conversation_id) d.node.append(button("Open conversation (support)…", () => { d.close(); supportDialog(detail.conversation_id); }, "primary"));
    } else d.node.append(el("pre", {class: "code"}, JSON.stringify(detail, null, 2)));
    const message = el("p", {class: "form-notice", role: "status"});
    d.node.append(el("hr", {class: "divider"}), button("Copy request ID", event => action(event.currentTarget, message, async () => { await navigator.clipboard.writeText(item.request_id); message.textContent = "Copied"; })), message); d.open();
  }
  routes.set("support", async (container, params, revision) => {
    const result = await api(`/api/admin/support-access/${encodeURIComponent(params.get("grant") || "")}/conversation`); if (revision !== state.revision) return;
    const expires = result.grant.expires_at * 1000;
    container.replaceChildren(heading(result.title || "Conversation", "Support view"), el("div", {class: "support-banner"}, `Support access · read-only · expires ${new Date(expires).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}`, hint(result.grant.reason)), el("div", {class: "card"}, result.messages.map(message => el("div", {class: "message"}, el("strong", {}, message.role || "Message"), message.message || message.summary || "No text in this entry."))));
    state.supportTimer = setInterval(() => {
      if (Date.now() >= expires) { clearInterval(state.supportTimer); container.replaceChildren(unavailable("Support access has expired. Request a new grant to read this conversation.")); }
    }, 1000);
  });
  routes.set("activity", async (container, params, revision) => {
    const users = await api("/api/admin/users"); if (revision !== state.revision) return;
    const search = el("input", {class: "search", type: "search", placeholder: "Search activity", "aria-label": "Search activity"});
    const user = el("select", {"aria-label": "Filter by user"}, option("", "All users"), users.items.map(item => option(item.id, item.username))); user.value = params.get("user_id") || "";
    const range = el("select", {"aria-label": "Date range"}, option("1", "Today"), option("7", "Last 7 days"), option("30", "Last 30 days"), option("custom", "Custom")); range.value = "7";
    const start = el("input", {type: "date", "aria-label": "Start date"}), end = el("input", {type: "date", "aria-label": "End date"});
    const custom = el("div", {class: "actions", hidden: true}, field("From", start), field("Through", end));
    const chips = el("div", {class: "chips"}), rows = el("div"), more = button("Load older", () => load(true)); let kind = params.get("kind") || "", cursor = null, items = [], requestRevision = 0;
    const chipNodes = new Map();
    for (const [value, label] of [["", "All"], ["question", "Questions"], ["calculation", "Calculations"], ["sign_in", "Sign-ins"], ["error", "Errors"], ["admin_change", "Admin changes"], ["support_access", "Support access"]]) {
      const chip = button(label, () => { kind = value; load(); }); chip.className = "chip"; chipNodes.set(value, {chip, label}); chips.append(chip);
    }
    function query(older = false) {
      const query = new URLSearchParams(); if (user.value) query.set("user_id", user.value); if (kind) query.set("kind", kind); if (search.value) query.set("search", search.value);
      const now = new Date(users.now * 1000), midnight = new Date(now); midnight.setHours(0, 0, 0, 0);
      if (range.value === "custom") { if (start.value) query.set("start", new Date(start.value + "T00:00:00").getTime() / 1000); if (end.value) query.set("end", new Date(end.value + "T00:00:00").getTime() / 1000 + 86400); }
      else query.set("start", range.value === "1" ? midnight.getTime() / 1000 : users.now - Number(range.value) * 86400);
      if (older && cursor) query.set("before", cursor); return query;
    }
    async function load(older = false) {
      const active = ++requestRevision; more.disabled = true;
      try {
        const result = await api(`/api/admin/activity?${query(older)}`); if (revision !== state.revision || active !== requestRevision) return;
        cursor = result.next_cursor; items = older ? items.concat(result.items) : result.items;
        for (const [value, {chip, label}] of chipNodes) { chip.setAttribute("aria-pressed", String(kind === value)); chip.replaceChildren(label, el("span", {class: "count"}, n(value ? result.counts[value] : result.total))); }
        rows.replaceChildren(items.length ? table(["Time", "User", "Type", "What happened", "Result"], items.map(item => el("tr", {}, el("td", {class: "nowrap"}, stamp(item.ts)), el("td", {}, item.username || "Unknown / removed"), el("td", {}, badge(item.type.replaceAll("_", " "), item.type)), el("td", {}, el("button", {class: "link-button", onclick: () => eventDetails(item)}, item.summary)), el("td", {}, badge(item.outcome, item.outcome))))) : el("div", {class: "card empty"}, "No recorded events match these filters."));
        more.hidden = !cursor;
      } catch (error) { notice(error.message, true); }
      finally { more.disabled = false; }
    }
    let debounce; search.addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(() => load(), 250); });
    for (const control of [user, start, end]) control.addEventListener("change", () => load());
    range.addEventListener("change", () => { custom.hidden = range.value !== "custom"; load(); });
    container.replaceChildren(heading("Activity", "A record of questions, calculations, sign-ins, and every administrative change.", button("Export CSV", () => download(`/api/admin/activity/export?${query()}`, "graphmine-activity.csv"))), el("div", {class: "toolbar"}, search, user, range, custom), chips, el("div", {class: "panel-layout"}, rows), el("div", {class: "bottom-actions"}, more)); await load();
  });
  async function badges() {
    try {
      const data = await api("/api/admin/badges"); state.now = data.now;
      for (const key of ["health", "users", "jobs"]) { const node = $(`[data-badge="${key}"]`); node.textContent = data[key] == null ? "—" : n(data[key]); node.title = data[key] == null ? data[`${key}_reason`] || "Not available yet" : ""; }
    } catch (_) { /* The page retains its last measured values during a failed refresh. */ }
  }
  async function route() {
    if (state.cleanup) { state.cleanup(); state.cleanup = null; }
    for (const node of document.querySelectorAll("dialog.drawer")) node.close();
    clearInterval(state.timer); clearInterval(state.supportTimer);
    const revision = ++state.revision, [name, search = ""] = location.hash.slice(1).split("?");
    state.route = name || "overview"; state.renderUsers = null; notice();
    for (const link of document.querySelectorAll(".nav-item")) link.setAttribute("aria-current", link.dataset.route === state.route ? "page" : "false");
    document.title = `GraphMine · ${titles[state.route] || "Support access"}`;
    const container = $("#page-content"); container.replaceChildren(el("p", {role: "status", class: "muted"}, "Loading…"));
    try {
      if (routes.has(state.route)) await routes.get(state.route)(container, new URLSearchParams(search), revision);
      else container.replaceChildren(heading(titles[state.route] || "Page not found", "GraphMine administration"), el("div", {class: "card"}, unavailable("This page is being implemented in the next console phase.")));
      await badges();
    } catch (error) {
      if (revision !== state.revision) return;
      if (error.status === 403 || error.status === 401) { showAccess(); return; }
      container.replaceChildren(heading(titles[state.route] || "Admin console", ""), el("p", {class: "notice error", role: "alert"}, error.message), button("Try again", route));
    }
  }
  function showAccess() {
    clearInterval(state.timer); clearInterval(state.supportTimer);
    $("#admin-layout").hidden = true; const message = $("#access-message"); message.hidden = false;
    message.replaceChildren(el("h1", {}, "You need administrator access"), hint("Sign in with an active administrator account to open the console."), el("a", {class: "btn primary", href: "/"}, "Back to GraphMine"));
    $("#dialog-root").replaceChildren();
  }
  async function start() {
    try {
      const me = await api("/api/auth/me"); if (me.user.role !== "admin" || me.user.must_change_password) { showAccess(); return; }
      state.user = me.user; $("#admin-identity").textContent = `${me.user.username} · Administrator`;
      $("#admin-navigation").replaceChildren(...groups.flatMap(([group, items]) => [el("p", {class: "nav-group"}, group), ...items.map(([key, title, icon]) => el("a", {class: "nav-item", href: `#${key}`, "data-route": key}, navIcon(key), title, ["health", "users", "jobs"].includes(key) ? el("span", {class: "nav-count", "data-badge": key}, "—") : null))]));
      $("#access-message").hidden = true; $("#admin-layout").hidden = false;
      window.addEventListener("hashchange", route); await route(); await badges(); setInterval(badges, 30000);
    } catch (_) { showAccess(); }
  }
  window.GraphMineAdmin = {api, mutate, el, n, bytes, stamp, duration, hint, unavailable, badge, button, field, check, heading, option, table, details, state, routes, notice, action, download, dialog, footer, route};
  window.addEventListener("DOMContentLoaded", start);
})();
