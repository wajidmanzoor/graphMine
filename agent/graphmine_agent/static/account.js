(() => {
  "use strict";
  const nativeFetch = window.fetch.bind(window);
  const account = window.GraphMineAccount = {enabled: false, ready: null};
  if (document.getElementById("graphmine-report")) { account.ready = Promise.resolve(false); return; }
  let dialog, error, username, password, form, quota, accountName, manageUsers, resolveLogin, authenticated = false, refreshTimer;
  const make = (tag, attrs = {}, text) => {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
    if (text !== undefined) el.textContent = text;
    return el;
  };
  async function request(path, options = {}) {
    const response = await nativeFetch(path, {...options, credentials: "same-origin", headers: {"Content-Type": "application/json", "X-GraphMine-Request": "1", ...options.headers}});
    const body = response.status === 204 ? {} : await response.json();
    if (!response.ok) throw new Error(body.error?.message || "Sign-in is unavailable. Please try again.");
    return body;
  }
  function renderUsage(data) {
    accountName.textContent = data.user.username;
    manageUsers.hidden = data.user.role !== "admin";
    const q = data.quota, reset = new Date(q.resets_at).toLocaleString();
    quota.textContent = `${q.tokens_remaining.toLocaleString()} / ${q.token_limit.toLocaleString()} AI tokens left`;
    quota.title = `Resets ${reset}. ${Math.max(0, q.job_limit - q.jobs_used)} of ${q.job_limit} graph jobs left. Input and generated tokens count toward your allowance.`;
    if (q.server_tokens_remaining === 0) {
      quota.textContent += " · Server allowance used";
      quota.title += ` The server allowance resets ${new Date(q.server_resets_at).toLocaleString()}.`;
    }
    quota.setAttribute("aria-label", `${quota.textContent}. ${quota.title}`);
  }
  function showLogin(message = "") {
    if (!dialog.open) dialog.showModal();
    error.textContent = message;
    username.focus();
  }
  function mountAdministration() {
    const panel = make("dialog", {class: "account-dialog account-admin", "aria-labelledby": "account-admin-heading"});
    const heading = make("h2", {id: "account-admin-heading"}, "Manage users");
    const message = make("p", {id: "account-admin-message", role: "status"});
    const users = make("div", {id: "account-admin-users"});
    const close = make("button", {type: "button", class: "quiet"}, "Close");
    close.addEventListener("click", () => panel.close());
    const labelFor = (name, field) => { const label = make("label", {}, name); label.append(field); return label; };
    const newUser = make("input", {id: "account-new-username", autocomplete: "off", required: "", minlength: "3", maxlength: "64"});
    const newPassword = make("input", {id: "account-new-password", type: "password", autocomplete: "new-password", required: "", minlength: "12", maxlength: "128"});
    const create = make("form");
    create.append(make("h3", {}, "Create an account"), labelFor("Username", newUser), labelFor("Password (at least 12 characters)", newPassword), make("button", {type: "submit", id: "account-create-user"}, "Create account"));
    const resetUser = make("select", {id: "account-reset-user", required: ""});
    const resetPassword = make("input", {id: "account-reset-password", type: "password", autocomplete: "new-password", required: "", minlength: "12", maxlength: "128"});
    const reset = make("form");
    reset.append(make("h3", {}, "Reset a password"), labelFor("Account", resetUser), labelFor("New password", resetPassword), make("button", {type: "submit"}, "Reset password"));
    panel.append(heading, make("p", {class: "muted"}, "Create accounts for the people you invite. Resetting a password or disabling an account signs that person out."), message, users, create, reset, close);
    document.body.append(panel);
    async function loadUsers() {
      const data = await request("/api/auth/admin/users");
      users.replaceChildren(); resetUser.replaceChildren();
      for (const user of data) {
        resetUser.append(make("option", {value: user.username}, user.username));
        const row = make("div", {class: "account-user-row"});
        row.append(make("span", {}, `${user.username} · ${user.role}${user.disabled ? " · Disabled" : ""}`));
        const toggle = make("button", {type: "button", class: "quiet"}, user.disabled ? "Enable" : "Disable");
        toggle.disabled = user.username === accountName.textContent;
        toggle.addEventListener("click", async () => {
          toggle.disabled = true;
          try {
            await request(`/api/auth/admin/users/${encodeURIComponent(user.username)}/${user.disabled ? "enable" : "disable"}`, {method: "POST"});
            await loadUsers(); message.textContent = "Account updated.";
          } catch (failure) { message.textContent = failure.message; toggle.disabled = false; }
        });
        row.append(toggle); users.append(row);
      }
    }
    manageUsers.addEventListener("click", async () => {
      message.textContent = ""; panel.showModal();
      try { await loadUsers(); } catch (failure) { message.textContent = failure.message; }
    });
    create.addEventListener("submit", async event => {
      event.preventDefault(); const button = create.querySelector("button"); button.disabled = true;
      try {
        await request("/api/auth/admin/users", {method: "POST", body: JSON.stringify({username: newUser.value, password: newPassword.value})});
        newUser.value = ""; await loadUsers(); message.textContent = "Account created. Give the credentials to its owner privately.";
      } catch (failure) { message.textContent = failure.message; }
      finally { newPassword.value = ""; button.disabled = false; }
    });
    reset.addEventListener("submit", async event => {
      event.preventDefault(); const button = reset.querySelector("button"); button.disabled = true;
      try {
        await request(`/api/auth/admin/users/${encodeURIComponent(resetUser.value)}/reset-password`, {method: "POST", body: JSON.stringify({password: resetPassword.value})});
        if (resetUser.value === accountName.textContent) { location.reload(); return; }
        message.textContent = "Password reset. Existing logins have been revoked.";
      } catch (failure) { message.textContent = failure.message; }
      finally { resetPassword.value = ""; button.disabled = false; }
    });
    panel.addEventListener("close", () => { newPassword.value = ""; resetPassword.value = ""; });
  }
  function mount() {
    const style = make("link", {rel: "stylesheet", href: "/account.css"});
    document.head.append(style);
    dialog = make("dialog", {class: "account-dialog", "aria-labelledby": "account-heading"});
    form = make("form");
    form.append(make("p", {class: "eyebrow"}, "GraphMine"), make("h1", {id: "account-heading"}, "Sign in to your workspace"), make("p", {class: "muted"}, "Use the username and password provided by your administrator."));
    const userLabel = make("label", {}, "Username");
    username = make("input", {id: "account-username", name: "username", autocomplete: "username", required: "", maxlength: "64", autocapitalize: "none", spellcheck: "false"});
    userLabel.append(username);
    const passLabel = make("label", {}, "Password");
    password = make("input", {id: "account-password", name: "password", type: "password", autocomplete: "current-password", required: "", maxlength: "128"});
    passLabel.append(password);
    error = make("p", {id: "account-error", role: "alert", class: "account-error"});
    const submit = make("button", {type: "submit", id: "account-sign-in"}, "Sign in");
    form.append(userLabel, passLabel, error, submit);
    dialog.append(form); document.body.append(dialog);
    dialog.addEventListener("cancel", event => event.preventDefault());
    form.addEventListener("submit", async event => {
      event.preventDefault(); submit.disabled = true; error.textContent = "Signing in…";
      try {
        await request("/api/auth/login", {method: "POST", body: JSON.stringify({username: username.value, password: password.value})});
        const data = await request("/api/auth/me");
        if (authenticated) { location.hash = ""; location.reload(); return; }
        authenticated = true; renderUsage(data); dialog.close(); resolveLogin(true);
      } catch (failure) { error.textContent = failure.message; }
      finally { password.value = ""; submit.disabled = false; }
    });
    const bar = make("div", {class: "account-bar"});
    accountName = make("span", {class: "account-name"});
    quota = make("span", {id: "account-quota", role: "status"});
    manageUsers = make("button", {class: "quiet", id: "account-manage-users", type: "button", hidden: ""}, "Manage users");
    const logout = make("button", {class: "quiet", id: "account-sign-out", type: "button"}, "Sign out");
    logout.addEventListener("click", async () => {
      logout.disabled = true;
      try { await request("/api/auth/logout", {method: "POST"}); location.hash = ""; location.reload(); }
      catch (failure) { logout.disabled = false; showLogin(failure.message); }
    });
    bar.append(accountName, quota, manageUsers, logout);
    (document.querySelector(".header-actions") || document.querySelector(".app-header") || document.body).append(bar);
    mountAdministration();
    for (const id of ["connection-button", "settings-button"]) { const button = document.getElementById(id); if (button) button.hidden = true; }
  }
  async function refreshUsage() {
    if (!account.enabled || !authenticated) return;
    try { renderUsage(await request("/api/auth/me")); } catch (_) { /* The next API request handles expiry. */ }
  }
  window.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (!account.enabled || url.origin !== location.origin || !url.pathname.startsWith("/api/")) return nativeFetch(input, options);
    const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
    headers.delete("Authorization"); headers.delete("X-GraphMine-Token"); headers.set("X-GraphMine-Request", "1");
    const response = await nativeFetch(input, {...options, headers, credentials: "same-origin"});
    if (response.status === 401) showLogin("Your session expired. Please sign in again.");
    if ((options.method || "GET") !== "GET" || response.status === 429) {
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
