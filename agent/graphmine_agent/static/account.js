(() => {
  "use strict";
  const nativeFetch = window.fetch.bind(window);
  const account = window.GraphMineAccount = {enabled: false, ready: null};
  if (document.getElementById("graphmine-report")) { account.ready = Promise.resolve(false); return; }
  let dialog, error, username, password, settings, accountName, manageUsers, usagePanel, profileName, profileRole, resolveLogin, expired = false;
  let authenticated = false, refreshTimer, identity;
  const tabs = new Map(), panels = new Map();
  const make = (tag, attrs = {}, text) => {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
    if (text !== undefined) el.textContent = text;
    return el;
  };
  const number = value => Number(value).toLocaleString();
  const labelFor = (name, field) => { const label = make("label", {}, name); label.append(field); return label; };
  const button = (text, id, primary = false) => make("button", {type: "button", class: primary ? "account-primary" : "account-secondary", ...(id ? {id} : {})}, text);
  const hint = text => make("p", {class: "account-hint"}, text);
  const passwordField = (id, current = false) => make("input", {id, type: "password", autocomplete: current ? "current-password" : "new-password", required: "", minlength: current ? "1" : "12", maxlength: "128"});
  const limitField = id => make("input", {id, type: "number", min: "0", step: "1", required: "", inputmode: "numeric", max: identity.quota.server_token_limit});
  function message(el, text = "", failure = false) {
    el.textContent = text;
    el.classList.toggle("is-error", failure);
  }
  async function request(path, options = {}) {
    const response = await nativeFetch(path, {...options, credentials: "same-origin", headers: {"Content-Type": "application/json", "X-GraphMine-Request": "1", ...options.headers}});
    const body = response.status === 204 ? {} : await response.json();
    if (!response.ok) {
      if (response.status === 401 && authenticated && path !== "/api/auth/login") expire();
      throw new Error(body.error?.message || (response.status === 422 ? "Check the fields and try again." : "The request could not be completed. Please try again."));
    }
    return body;
  }
  const post = (path, body) => request(path, {method: "POST", ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  async function action(control, notice, work) {
    control.disabled = true;
    message(notice);
    try { await work(); } catch (failure) { message(notice, failure.message, true); }
    finally { control.disabled = false; }
  }
  function resetText(stamp) {
    const date = new Date(stamp), minutes = Math.max(0, Math.ceil((date - Date.now()) / 60000));
    const duration = minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`;
    return `Resets in ${duration} · ${date.toLocaleString([], {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"})}`;
  }
  function tokenMeter(q, {id, compact = false} = {}) {
    const used = q.tokens_used, limit = q.token_limit;
    const percentage = limit ? Math.min(100, Math.round(100 * used / limit)) : 100;
    const meter = make("div", {class: `account-meter${compact ? " compact" : ""}`, ...(id ? {id} : {})});
    const top = make("div", {class: "account-meter-heading"});
    if (!compact) {
      const remaining = make("div");
      remaining.append(make("strong", {class: "account-token-count"}, number(q.tokens_remaining)), make("span", {class: "account-hint"}, " tokens remaining"));
      top.append(remaining, make("span", {class: "account-badge"}, "24-hour allowance"));
    } else top.append(make("span", {}, `${number(used)} / ${number(limit)} tokens used`));
    const progress = make("progress", {max: Math.max(1, limit), value: limit ? Math.min(used, limit) : 1, "aria-label": "Daily AI token usage", "aria-valuetext": limit ? `${number(used)} of ${number(limit)} tokens used; ${number(q.tokens_remaining)} remaining` : "AI allowance paused", "data-level": percentage >= 100 ? "empty" : percentage >= 80 ? "low" : "normal"});
    const bottom = make("div", {class: "account-meter-caption"});
    bottom.append(make("span", {}, compact ? `${number(q.tokens_remaining)} left` : `${number(used)} of ${number(limit)} tokens used`), make("span", {}, limit ? `${percentage}% used` : "AI allowance paused"));
    meter.append(top, progress, bottom);
    if (!compact) meter.append(hint(resetText(q.resets_at)));
    return meter;
  }
  function renderUsage(data) {
    identity = data;
    account.user = data.user;
    document.getElementById("account-admin-console").hidden = data.user.role !== "admin";
    document.getElementById("account-close-settings").disabled = Boolean(data.user.must_change_password);
    accountName.textContent = data.user.username;
    document.getElementById("account-settings-button").setAttribute("aria-label", `Account settings for ${data.user.username}`);
    profileName.value = data.user.username;
    profileRole.textContent = data.user.role === "admin" ? "Administrator" : "Member";
    manageUsers.hidden = data.user.role !== "admin";
    const q = data.quota;
    const card = make("section", {class: "account-card account-usage-card"});
    card.append(make("p", {class: "account-eyebrow"}, "YOUR AI ALLOWANCE"), tokenMeter(q, {id: "account-quota"}), hint("Input and generated tokens count toward your daily allowance."));
    // Tokens are abstract; recent questions give a practical sense of what is left.
    if (q.questions_left !== null && q.questions_left !== undefined) card.append(make("p", {class: "account-questions-left"}, `About ${q.questions_left.toLocaleString()} more questions today, at your recent average of ${q.average_question_tokens.toLocaleString()} tokens per question.`));
    if (q.tokens_reserved) card.append(hint(`${q.tokens_reserved.toLocaleString()} of the used tokens are reserved for a request in progress; the unused part returns when it finishes.`));
    if (q.recent_questions?.length) {
      const list = make("ul", {class: "account-recent"});
      for (const turn of q.recent_questions) list.append(make("li", {}, `${turn.tokens.toLocaleString()} tokens · ${new Date(turn.at).toLocaleString([], {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"})}`));
      card.append(make("h4", {}, "Recent questions"), list);
    }
    if (data.user.role !== "admin") card.append(hint(`Every account draws on a shared server pool of ${q.server_token_limit.toLocaleString()} tokens per day. If the pool runs out first, everyone waits for its reset.`));
    const details = make("div", {class: "account-stat-grid"});
    const jobs = make("section", {class: "account-card"});
    jobs.append(make("h3", {}, "Graph jobs"), make("strong", {class: "account-stat"}, `${Math.max(0, q.job_limit - q.jobs_used)} / ${q.job_limit}`), hint("Jobs remaining in this 24-hour period."));
    const reset = make("section", {class: "account-card"});
    reset.append(make("h3", {}, "Automatic reset"), make("strong", {}, new Date(q.resets_at).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})), hint("Your allowance renews every 24 hours. Signing out does not reset usage."));
    const storage = make("section", {class: "account-card"}), mib = bytes => `${(bytes / 2 ** 20).toLocaleString([], {maximumFractionDigits: 1})} MiB`;
    if (q.storage) storage.append(make("h3", {}, "Storage"), make("strong", {class: "account-stat"}, `${mib(q.storage.used)} / ${mib(q.storage.limit)}`), hint(`Uploads ${mib(q.storage.uploads)}, saved analyses ${mib(q.storage.results)}, dataset versions and templates ${mib((q.storage.datasets || 0) + (q.storage.templates || 0))}, temporary query previews ${mib(q.storage.previews || 0)}, active database work reservations ${mib(q.storage.database_jobs || 0)}, exploration settings ${mib(q.storage.exploration || 0)}, project snapshots and notes ${mib(q.storage.shared || 0)}. Unused query previews expire after 24 hours. Remove unused conversations, files or saved library/project items to free space.`));
    if (q.storage?.reset_bytes) storage.append(hint(`${mib(q.storage.stored)} saved in total. Your administrator reset the allowance with ${mib(q.storage.reset_bytes)} already stored; only storage above that amount counts toward your allowance.`));
    details.append(jobs, reset, ...(q.storage ? [storage] : []));
    usagePanel.replaceChildren(make("h3", {class: "account-section-title"}, "Usage"), hint("See what you have used and when your allowance renews."), card, details);
    if (data.user.role === "admin") {
      const server = make("section", {class: "account-card account-server-usage"});
      server.append(make("h3", {}, "Shared server allowance"), tokenMeter({tokens_used: q.server_tokens_used, token_limit: q.server_token_limit, tokens_remaining: q.server_tokens_remaining, resets_at: q.server_resets_at}, {compact: true}), hint(resetText(q.server_resets_at)), hint("Shared by all accounts. Changing a user's limit or resetting their usage keeps this server cap in place."));
      usagePanel.append(server);
    }
    if (q.server_tokens_remaining === 0) usagePanel.append(make("p", {class: "account-status is-error", role: "status"}, `The shared server allowance is used up. ${resetText(q.server_resets_at)}.`));
  }
  function showLogin(text = "") {
    if (settings?.open) settings.close();
    if (!dialog.open) dialog.showModal();
    error.textContent = text;
    username.focus();
  }
  function selectTab(name) {
    for (const [key, tab] of tabs) {
      tab.setAttribute("aria-selected", String(key === name));
      tab.tabIndex = key === name ? 0 : -1;
      panels.get(key).hidden = key !== name;
    }
  }
  function mountProfile(panel) {
    profileName = make("input", {id: "account-profile-username", readonly: "", autocomplete: "username"});
    profileRole = make("span", {class: "account-badge"});
    const summary = make("section", {class: "account-card account-profile-card"});
    summary.append(profileRole, labelFor("Username", profileName), hint("Your administrator manages your username and daily allowance."));
    const form = make("form", {class: "account-card"});
    const current = passwordField("account-current-password", true), next = passwordField("account-change-password"), confirm = passwordField("account-confirm-password");
    const notice = make("p", {class: "account-status", id: "account-password-message", role: "status"});
    const save = button("Change password", "account-save-password", true); save.type = "submit";
    for (const field of [next, confirm]) field.addEventListener("input", () => confirm.setCustomValidity(""));
    form.append(make("h3", {}, "Change password"), hint("Use at least 12 characters. Changing your password signs out all your devices."), labelFor("Current password", current), labelFor("New password", next), labelFor("Confirm new password", confirm), save, notice);
    form.addEventListener("submit", event => {
      event.preventDefault();
      if (next.value !== confirm.value) { confirm.setCustomValidity("Passwords do not match."); confirm.reportValidity(); return; }
      action(save, notice, async () => {
        try {
          await post("/api/auth/password", {current_password: current.value, password: next.value});
          showLogin("Password changed. Sign in with your new password.");
        } finally { current.value = ""; next.value = ""; confirm.value = ""; }
      });
    });
    const logout = button("Sign out", "account-sign-out");
    logout.addEventListener("click", () => action(logout, notice, async () => { await post("/api/auth/logout"); location.hash = ""; location.reload(); }));
    const history = make("section", {class: "account-card"});
    const historyRows = make("div");
    const showHistory = button("View support access history", "account-support-history");
    showHistory.addEventListener("click", () => action(showHistory, notice, async () => {
      const data = await request("/api/auth/history");
      historyRows.replaceChildren(...data.support_access.map(grant => hint(`${grant.administrator || "Former administrator"} · ${grant.reason} · ${new Date(grant.created_at * 1000).toLocaleString()} · expires ${new Date(grant.expires_at * 1000).toLocaleString()}`)));
      if (!data.support_access.length) historyRows.append(hint("No support access has been granted."));
    }));
    history.append(make("h3", {}, "Account history"), hint("Administrator support access is read-only and recorded here."), showHistory, historyRows);
    panel.append(make("h3", {class: "account-section-title"}, "Account"), hint("Your sign-in details and password."), summary, form, history, logout);
  }
  function mountAdministration(panel) {
    panel.append(make("h3", {class: "account-section-title"}, "Administration"),
      hint("Manage users, inspect server activity, and configure GraphMine."),
      make("a", {href: "/admin", class: "account-primary"}, "Open admin console"));
  }
  function requirePasswordChange() {
    selectTab("profile");
    document.getElementById("account-close-settings").disabled = true;
    message(document.getElementById("account-password-message"), "Change your temporary password before continuing.");
    if (!settings.open) settings.showModal();
  }
  function mountSettings() {
    settings = make("dialog", {class: "account-settings-dialog", "aria-labelledby": "account-settings-heading"});
    const header = make("div", {class: "account-settings-header"});
    const title = make("div"); title.append(make("p", {class: "account-eyebrow"}, "GRAPHMINE WORKSPACE"), make("h2", {id: "account-settings-heading"}, "Settings"));
    const close = button("Close", "account-close-settings"); close.setAttribute("aria-label", "Close settings"); close.addEventListener("click", () => settings.close());
    header.append(title, close);
    const layout = make("div", {class: "account-settings-layout"});
    const navigation = make("div", {class: "account-settings-nav", role: "tablist", "aria-label": "Settings sections", "aria-orientation": "vertical"});
    const mobile = window.matchMedia("(max-width: 560px)");
    const orientNavigation = () => navigation.setAttribute("aria-orientation", mobile.matches ? "horizontal" : "vertical");
    orientNavigation(); mobile.addEventListener("change", orientNavigation);
    const content = make("div", {class: "account-settings-content"});
    for (const [name, label] of [["usage", "Usage"], ["profile", "Account"], ["users", "Manage users"]]) {
      const id = name === "users" ? "account-manage-users" : `account-tab-${name}`;
      const tab = make("button", {id, type: "button", role: "tab", "aria-controls": `account-panel-${name}`, "aria-selected": "false", tabindex: "-1"}, label);
      const panel = make("section", {id: `account-panel-${name}`, role: "tabpanel", "aria-labelledby": id, hidden: ""});
      tab.addEventListener("click", () => selectTab(name));
      tabs.set(name, tab); panels.set(name, panel); navigation.append(tab); content.append(panel);
    }
    navigation.addEventListener("keydown", event => {
      if (!["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const visible = [...tabs.values()].filter(tab => !tab.hidden), index = visible.indexOf(document.activeElement);
      const next = event.key === "Home" ? 0 : event.key === "End" ? visible.length - 1 : (index + (["ArrowDown", "ArrowRight"].includes(event.key) ? 1 : -1) + visible.length) % visible.length;
      visible[next].focus(); visible[next].click();
    });
    usagePanel = panels.get("usage"); manageUsers = tabs.get("users"); manageUsers.hidden = true;
    mountProfile(panels.get("profile")); mountAdministration(panels.get("users"));
    layout.append(navigation, content); settings.append(header, layout); document.body.append(settings);
    settings.addEventListener("cancel", event => { if (identity?.user.must_change_password) event.preventDefault(); });
    settings.addEventListener("close", () => { for (const input of settings.querySelectorAll('input[type="password"]')) input.value = ""; });
    selectTab("usage");
    return () => { selectTab("usage"); settings.showModal(); refreshUsage(); };
  }
  function mount() {
    document.head.append(make("link", {rel: "stylesheet", href: "/account.css"}));
    dialog = make("dialog", {class: "account-dialog", "aria-labelledby": "account-heading"});
    const form = make("form");
    form.append(make("p", {class: "account-eyebrow"}, "GraphMine"), make("h1", {id: "account-heading"}, "Sign in to your workspace"), hint("Use the username and password provided by your administrator."));
    username = make("input", {id: "account-username", name: "username", autocomplete: "username", required: "", maxlength: "64", autocapitalize: "none", spellcheck: "false"});
    password = passwordField("account-password", true); password.name = "password";
    error = make("p", {id: "account-error", role: "alert", class: "account-status is-error"});
    const submit = button("Sign in", "account-sign-in", true); submit.type = "submit";
    form.append(labelFor("Username", username), labelFor("Password", password), error, submit);
    dialog.append(form); document.body.append(dialog);
    dialog.addEventListener("cancel", event => event.preventDefault());
    form.addEventListener("submit", async event => {
      event.preventDefault(); submit.disabled = true; error.textContent = "Signing in…";
      try {
        await post("/api/auth/login", {username: username.value, password: password.value});
        const data = await request("/api/auth/me");
        if (authenticated) { location.hash = ""; location.reload(); return; }
        authenticated = true; renderUsage(data); dialog.close();
        if (data.user.must_change_password) { requirePasswordChange(); return; }
        resolveLogin?.(true);
      } catch (failure) { error.textContent = failure.message; }
      finally { password.value = ""; submit.disabled = false; }
    });
    const bar = make("div", {class: "account-bar"});
    accountName = make("span", {class: "account-name"});
    const open = button("", "account-settings-button");
    open.append(make("span", {class: "account-settings-icon", "aria-hidden": "true"}, "⚙"), accountName, make("span", {}, "Settings"));
    open.addEventListener("click", mountSettings());
    const adminLink = make("a", {href: "/admin", id: "account-admin-console", class: "account-secondary", hidden: ""}, "Admin");
    bar.append(adminLink, open);
    (document.querySelector(".header-actions") || document.querySelector(".app-header") || document.body).append(bar);
    for (const id of ["connection-button", "settings-button"]) { const old = document.getElementById(id); if (old) old.hidden = true; }
  }
  // Signing in again reloads the page, so nothing needs to resume polling.
  function expire() {
    expired = true;
    showLogin("Your session expired. Please sign in again.");
  }
  async function refreshUsage() {
    if (!account.enabled || !authenticated || expired) return;
    try { renderUsage(await request("/api/auth/me")); } catch (_) { /* Request handles session expiry; a later refresh retries network failures. */ }
  }
  window.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (!account.enabled || url.origin !== location.origin || !url.pathname.startsWith("/api/")) return nativeFetch(input, options);
    const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
    headers.delete("Authorization"); headers.delete("X-GraphMine-Token"); headers.set("X-GraphMine-Request", "1");
    const response = await nativeFetch(input, {...options, headers, credentials: "same-origin"});
    if (response.status === 401) expire();
    if ((options.method || (input instanceof Request ? input.method : "GET")) !== "GET" || response.status === 429) {
      clearTimeout(refreshTimer); refreshTimer = setTimeout(refreshUsage, 200);
    }
    return response;
  };
  account.ready = (async () => {
    const configuration = await request("/api/auth/config");
    account.enabled = configuration.enabled;
    if (!account.enabled) return false;
    try { localStorage.removeItem("graphmine.apiToken"); localStorage.removeItem("graphmine.apiBase"); } catch (_) { /* Storage is optional. */ }
    mount();
    try { const data = await request("/api/auth/me"); authenticated = true; renderUsage(data); if (data.user.must_change_password) { requirePasswordChange(); return new Promise(resolve => { resolveLogin = resolve; }); } return true; }
    catch (_) { showLogin(); return new Promise(resolve => { resolveLogin = resolve; }); }
  })();
  setInterval(refreshUsage, 30000);
})();
