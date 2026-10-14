(() => {
  "use strict";
  const nativeFetch = window.fetch.bind(window);
  const account = window.GraphMineAccount = {enabled: false, ready: null};
  if (document.getElementById("graphmine-report")) { account.ready = Promise.resolve(false); return; }
  let dialog, error, username, password, form, quota, accountName, resolveLogin, authenticated = false, refreshTimer;
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
    const logout = make("button", {class: "quiet", id: "account-sign-out", type: "button"}, "Sign out");
    logout.addEventListener("click", async () => {
      logout.disabled = true;
      try { await request("/api/auth/logout", {method: "POST"}); location.hash = ""; location.reload(); }
      catch (failure) { logout.disabled = false; showLogin(failure.message); }
    });
    bar.append(accountName, quota, logout);
    (document.querySelector(".header-actions") || document.querySelector(".app-header") || document.body).append(bar);
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
