(() => {
  "use strict";
  const nativeFetch = window.fetch.bind(window);
  const account = window.GraphMineAccount = {enabled: false, ready: null};
  if (document.getElementById("graphmine-report")) { account.ready = Promise.resolve(false); return; }
  let dialog, error, username, password, settings, accountName, manageUsers, usagePanel, profileName, profileRole, resolveLogin;
  let authenticated = false, refreshTimer, identity, adminData = [], selectedUser;
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
      if (response.status === 401 && authenticated && path !== "/api/auth/login") showLogin("Your session expired. Please sign in again.");
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
    accountName.textContent = data.user.username;
    profileName.value = data.user.username;
    profileRole.textContent = data.user.role === "admin" ? "Administrator" : "Member";
    manageUsers.hidden = data.user.role !== "admin";
    const q = data.quota;
    const card = make("section", {class: "account-card account-usage-card"});
    card.append(make("p", {class: "account-eyebrow"}, "YOUR AI ALLOWANCE"), tokenMeter(q, {id: "account-quota"}), hint("Input and generated tokens count toward your daily allowance."));
    const details = make("div", {class: "account-stat-grid"});
    const jobs = make("section", {class: "account-card"});
    jobs.append(make("h3", {}, "Graph jobs"), make("strong", {class: "account-stat"}, `${Math.max(0, q.job_limit - q.jobs_used)} / ${q.job_limit}`), hint("Jobs remaining in this 24-hour period."));
    const reset = make("section", {class: "account-card"});
    reset.append(make("h3", {}, "Automatic reset"), make("strong", {}, new Date(q.resets_at).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})), hint("Your allowance renews every 24 hours. Signing out does not reset usage."));
    details.append(jobs, reset);
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
    panel.append(make("h3", {class: "account-section-title"}, "Account"), hint("Your sign-in details and password."), summary, form, logout);
  }
  function mountAdministration(panel) {
    const notice = make("p", {class: "account-status", id: "account-admin-message", role: "status"});
    const heading = make("div", {class: "account-section-heading"});
    const title = make("div"); title.append(make("h3", {class: "account-section-title"}, "Manage users"), hint("Create accounts and manage each person's access and allowance."));
    const add = button("Create user", "account-create-toggle", true);
    heading.append(title, add);
    const create = make("form", {class: "account-card account-create-form", hidden: ""});
    const newUser = make("input", {id: "account-new-username", autocomplete: "off", required: "", minlength: "3", maxlength: "64", autocapitalize: "none", spellcheck: "false", pattern: "[a-zA-Z0-9][a-zA-Z0-9_.\\-]{2,63}", title: "3–64 letters, digits, dots, underscores or hyphens"});
    const newPassword = passwordField("account-new-password");
    // Filled when Settings opens, after the authenticated defaults have loaded.
    const newLimit = make("input", {id: "account-new-limit", type: "number", min: "0", step: "1", required: "", inputmode: "numeric"});
    const fields = make("div", {class: "account-form-grid"});
    fields.append(labelFor("Username", newUser), labelFor("Password (12+ characters)", newPassword), labelFor("Tokens per 24 hours", newLimit));
    const submit = button("Create account", "account-create-user", true); submit.type = "submit";
    create.append(make("h3", {}, "New account"), fields, hint("Give the credentials to the user privately. Set 0 tokens to pause AI access."), submit);
    add.addEventListener("click", () => {
      create.hidden = !create.hidden;
      add.textContent = create.hidden ? "Create user" : "Cancel";
      newPassword.value = "";
      if (!create.hidden) { newLimit.value = Math.min(identity.quota.default_token_limit, identity.quota.server_token_limit); newLimit.max = identity.quota.server_token_limit; newUser.focus(); }
    });
    const directory = make("div", {class: "account-directory"});
    const sidebar = make("div", {class: "account-user-sidebar"});
    const search = make("input", {type: "search", id: "account-user-search", placeholder: "Search users", "aria-label": "Search users"});
    const users = make("div", {id: "account-admin-users", class: "account-user-list", "aria-label": "User accounts"});
    sidebar.append(search, users);
    const detail = make("section", {id: "account-user-detail", class: "account-card account-user-detail", "aria-label": "Selected user"});
    directory.append(sidebar, detail);
    const refresh = button("Refresh usage", "account-refresh-users");
    panel.append(heading, notice, create, directory, refresh);
    function renderList() {
      users.replaceChildren();
      const matches = adminData.filter(user => user.username.includes(search.value.toLowerCase().trim()));
      for (const user of matches) {
        const row = make("button", {type: "button", class: "account-user-row", "aria-pressed": String(user.username === selectedUser), "data-username": user.username});
        row.append(make("strong", {}, user.username), make("span", {class: "account-hint"}, `${user.role === "admin" ? "Administrator" : "Member"}${user.disabled ? " · Disabled" : ""}`), tokenMeter(user.quota, {compact: true}));
        row.addEventListener("click", () => { selectedUser = user.username; message(notice); renderList(); renderDetail(); });
        users.append(row);
      }
      if (!matches.length) users.append(hint("No matching users."));
    }
    function renderDetail() {
      detail.replaceChildren();
      const user = adminData.find(row => row.username === selectedUser);
      if (!user) { detail.append(hint("Select an account to manage its allowance and password.")); return; }
      const endpoint = `/api/auth/admin/users/${encodeURIComponent(user.username)}`;
      const head = make("div", {class: "account-section-heading"});
      head.append(make("h3", {class: "account-selected-name"}, user.username), make("span", {class: "account-badge"}, user.disabled ? "Disabled" : "Active"));
      const quota = tokenMeter(user.quota);
      const limits = make("form", {class: "account-inline-form"});
      const input = limitField("account-user-token-limit"); input.value = user.quota.token_limit;
      const save = button("Save limit", "account-save-limit", true); save.type = "submit";
      limits.append(labelFor("Tokens per 24 hours", input), save);
      limits.addEventListener("submit", event => {
        event.preventDefault();
        action(save, notice, async () => {
          await post(`${endpoint}/token-limit`, {daily_token_limit: Number(input.value)});
          await loadUsers(user.username); await refreshUsage(); message(notice, `Daily token limit updated for ${user.username}.`);
        });
      });
      const reset = button("Reset token usage", "account-reset-tokens");
      reset.addEventListener("click", () => action(reset, notice, async () => {
        await post(`${endpoint}/reset-tokens`);
        await loadUsers(user.username); await refreshUsage(); message(notice, `Token usage reset for ${user.username}. The shared server budget is unchanged.`);
      }));
      const resetPassword = make("form", {class: "account-password-reset"});
      const field = passwordField("account-reset-password");
      const change = button("Reset password", "account-reset-user-password"); change.type = "submit";
      resetPassword.append(make("h3", {}, "Password"), labelFor("New password (12+ characters)", field), hint("Signs this user out of all devices. Token usage is kept."), change);
      resetPassword.addEventListener("submit", event => {
        event.preventDefault();
        action(change, notice, async () => {
          try {
            await post(`${endpoint}/reset-password`, {password: field.value});
            if (user.username === identity.user.username) { showLogin("Password reset. Sign in with your new password."); return; }
            message(notice, `Password reset for ${user.username}.`);
          } finally { field.value = ""; }
        });
      });
      const toggle = button(user.disabled ? "Enable account" : "Disable account", "account-toggle-user");
      toggle.disabled = user.username === identity.user.username;
      toggle.addEventListener("click", () => action(toggle, notice, async () => {
        await post(`${endpoint}/${user.disabled ? "enable" : "disable"}`);
        await loadUsers(user.username); message(notice, `Account ${user.disabled ? "enabled" : "disabled"}.`);
      }));
      detail.append(head, quota, limits, hint(`Maximum ${number(identity.quota.server_token_limit)} tokens. Use 0 to pause AI access.`), reset, hint("Reset clears this user's spent tokens. Their scheduled reset time, graph jobs and shared server usage stay the same."), resetPassword, toggle);
      if (toggle.disabled) detail.append(hint("You cannot disable your own administrator account."));
    }
    async function loadUsers(selection = selectedUser) {
      adminData = await request("/api/auth/admin/users");
      selectedUser = adminData.some(user => user.username === selection) ? selection : adminData[0]?.username;
      renderList(); renderDetail();
    }
    search.addEventListener("input", renderList);
    refresh.addEventListener("click", () => action(refresh, notice, () => loadUsers()));
    manageUsers.addEventListener("click", () => action(refresh, notice, () => loadUsers()));
    create.addEventListener("submit", event => {
      event.preventDefault();
      action(submit, notice, async () => {
        const name = newUser.value.trim().toLowerCase();
        try {
          await post("/api/auth/admin/users", {username: name, password: newPassword.value, daily_token_limit: Number(newLimit.value)});
          search.value = ""; await loadUsers(name); newUser.value = ""; create.hidden = true; add.textContent = "Create user";
          message(notice, `Account created for ${name}. Share their credentials privately.`);
        } finally { newPassword.value = ""; }
      });
    });
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
        authenticated = true; renderUsage(data); dialog.close(); resolveLogin?.(true);
      } catch (failure) { error.textContent = failure.message; }
      finally { password.value = ""; submit.disabled = false; }
    });
    const bar = make("div", {class: "account-bar"});
    accountName = make("span", {class: "account-name"});
    const open = button("", "account-settings-button");
    open.append(make("span", {class: "account-settings-icon", "aria-hidden": "true"}, "⚙"), accountName, make("span", {}, "Settings"));
    open.addEventListener("click", mountSettings());
    bar.append(open);
    (document.querySelector(".header-actions") || document.querySelector(".app-header") || document.body).append(bar);
    for (const id of ["connection-button", "settings-button"]) { const old = document.getElementById(id); if (old) old.hidden = true; }
  }
  async function refreshUsage() {
    if (!account.enabled || !authenticated) return;
    try { renderUsage(await request("/api/auth/me")); } catch (_) { /* Request handles session expiry; a later refresh retries network failures. */ }
  }
  window.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (!account.enabled || url.origin !== location.origin || !url.pathname.startsWith("/api/")) return nativeFetch(input, options);
    const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
    headers.delete("Authorization"); headers.delete("X-GraphMine-Token"); headers.set("X-GraphMine-Request", "1");
    const response = await nativeFetch(input, {...options, headers, credentials: "same-origin"});
    if (response.status === 401) showLogin("Your session expired. Please sign in again.");
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
    try { const data = await request("/api/auth/me"); authenticated = true; renderUsage(data); return true; }
    catch (_) { showLogin(); return new Promise(resolve => { resolveLogin = resolve; }); }
  })();
  setInterval(refreshUsage, 30000);
})();
