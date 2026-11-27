/* Semantic administration uses the existing console, with no retained key values. */
(() => {
  "use strict";
  const A = window.GraphMineAdmin;
  const {api, mutate, el, hint, badge, button, field, check, heading, option, table, details, state, routes, notice, action, dialog, footer} = A;
  const root = "/api/admin/semantic", key = name => "GRAPHMINE_SEMANTIC_" + name;
  const card = (title, ...children) => el("section", {class: "card manage-card semantic-card"}, el("h2", {}, title), children);
  const refresh = async message => { if (state.route === "semantic") { await A.route(); notice(message); } };
  const message = () => el("p", {class: "semantic-message", role: "status", "aria-live": "polite"});

  function providerEditor(provider = null) {
    const d = dialog(provider ? "Edit semantic provider" : "Add semantic provider"), error = message();
    const name = el("input", {value: provider?.name || "", required: true, maxlength: 120});
    const url = el("input", {type: "url", value: provider?.base_url || "", required: true, placeholder: "https://provider.example/v1"});
    const secret = el("input", {type: "password", autocomplete: "new-password", maxlength: 4096, placeholder: provider?.key_configured ? "Leave empty to keep the stored key" : "Optional API key"});
    const clear = check("Remove the stored key", false);
    const save = button("Save provider", () => action(save, error, async () => {
      if (![name, url].every(input => input.reportValidity())) return;
      const body = {name: name.value, base_url: url.value, clear_key: clear.input.checked};
      if (secret.value) body.api_key = secret.value;
      if (provider) body.expected_revision = provider.revision;
      await mutate(provider ? root + "/providers/" + encodeURIComponent(provider.id) : root + "/providers", body, provider ? "PUT" : "POST");
      secret.value = ""; d.close(); await refresh("Provider saved. Its key is never returned by the API.");
    }), "primary");
    d.node.append(field("Provider name", name), field("Base URL", url, "Use the OpenAI-compatible base URL, without credentials or query parameters."),
      field("API key", secret, "Stored privately on the server. Enter a replacement or explicitly remove the stored key."),
      provider?.key_configured ? clear.label : null, error, footer(d, save)); d.open();
  }

  function aliasEditor(data, alias = null) {
    const d = dialog(alias ? "Edit model alias" : "Add model alias"), error = message();
    const name = el("input", {value: alias?.alias || "", required: true, pattern: "[a-z][a-z0-9_]{0,31}", maxlength: 32, disabled: Boolean(alias)});
    const provider = el("select", {"aria-label": "Provider"}, data.providers.map(p => option(p.id, p.name)));
    if (alias) provider.value = alias.provider_id;
    const model = el("input", {value: alias?.model_id || "", required: true, maxlength: 256});
    const save = button("Save alias", () => action(save, error, async () => {
      if (![name, model].every(input => input.reportValidity())) return;
      await mutate(root + "/aliases", {alias: name.value, provider_id: provider.value, model_id: model.value, ...(alias ? {expected_revision: alias.revision} : {})}, "PUT");
      d.close(); await refresh("Model alias saved.");
    }), "primary");
    d.node.append(field("Alias", name, "Lowercase letters, numbers and underscores; start with a letter."),
      field("Provider", provider), field("Model ID", model, "Use the model ID reported by the provider."),
      hint("Every step uses the selected alias and its configured provider."), error, footer(d, save)); d.open();
  }

  function remove(kind, item) {
    const label = item.alias || item.name, identifier = item.alias || item.id;
    const d = dialog("Remove " + label), error = message();
    const save = button("Remove", () => action(save, error, async () => {
      await mutate(root + "/" + kind + "/" + encodeURIComponent(identifier), {confirm: true, expected_revision: item.revision}, "DELETE");
      d.close(); await refresh("Configuration removed. Saved graph provenance is unchanged.");
    }), "danger");
    d.node.append(el("p", {}, "Remove this configuration? Saved results keep their recorded model and settings."),
      kind === "providers" ? hint("Remove aliases using this provider first.") : null, error, footer(d, save)); d.open();
  }

  routes.set("semantic", async (container, params, revision) => {
    const data = await api(root); if (revision !== state.revision) return;
    container.replaceChildren(heading("Semantic engine", "Configure snapshot refinement, model access and verified tests."));
    container.append(el("div", {class: "notice warning", role: "status"},
      data.capabilities.live ? "Live refinement is available when enabled below. Required controls are thinking off, strict JSON and a total HTTP request budget." : "Install the verified semantic engine to enable live refinement. Explicit mocks use simulated judgments."));
    const mockStatus = message();
    const mock = button("Test mock pipeline", () => action(mock, mockStatus, async () => {
      mockStatus.setAttribute("role", "status");
      mockStatus.textContent = "Testing in an isolated worker…";
      const result = await mutate(root + "/test-mock");
      if (revision !== state.revision || !mockStatus.isConnected) return;
      mockStatus.textContent = result.passed ? "Mock pipeline passed · " + result.usage.calls + " engine call · 0 HTTP requests · 0 retained answers." : "Mock pipeline did not pass.";
    }));
    mock.disabled = !data.engine.installed || data.values[key("MODE")] === "disabled";
    container.append(card("Engine and required controls",
      details([["Installation", data.engine.installed ? data.engine.installed_version : "Pinned semantic engine is not installed"],
        ["Source commit", data.engine.commit], ["Thinking", "Off (required for live calls)"],
        ["Structured output", "Strict JSON required"], ["Temperature", "0"]]),
      hint("A connection test does not verify live semantic execution. The mock test verifies the installed engine without contacting a model."),
      mock, mockStatus));

    const providerRows = data.providers.map(provider => {
      const result = message();
      const test = button("Test connection", () => action(test, result, async () => {
        result.setAttribute("role", "status");
        result.textContent = "Checking the model list…";
        const value = await mutate(root + "/providers/" + encodeURIComponent(provider.id) + "/test");
        if (revision !== state.revision || !result.isConnected) return;
        const missing = value.models.filter(item => !item.available).map(item => item.alias);
        if (!value.connected) result.setAttribute("role", "alert");
        result.textContent = value.connected ? "Connected · checked " + new Date(value.checked_at * 1000).toLocaleTimeString() +
          (missing.length ? " · missing model IDs for: " + missing.join(", ") : value.models.length ? " · configured model IDs found" : " · model catalog available") :
          value.code === "authentication_failed" ? "Authentication failed. Check the stored key." : "Connection could not be verified. Check the endpoint and provider status.";
      }), "quiet");
      return el("tr", {}, el("td", {}, el("strong", {}, provider.name), hint(provider.base_url)),
        el("td", {}, provider.builtin ? "Uses server authentication; no key entry" : provider.key_configured ? "Key stored" : "No key"),
        el("td", {}, el("div", {class: "row-actions"}, test, !provider.builtin ? button("Edit", () => providerEditor(provider), "quiet") : null,
          !provider.builtin ? button("Remove", () => remove("providers", provider), "danger quiet") : null), result));
    });
    container.append(card("Providers", table(["Provider", "Authentication", "Connection and actions"], providerRows),
      button("Add provider", () => providerEditor()), hint("Tests read the model catalog only. Redirects are not followed and no completion request is sent.")));
    const aliasRows = data.aliases.map(alias =>
      el("tr", {}, el("td", {}, el("code", {}, alias.alias)), el("td", {}, data.providers.find(p => p.id === alias.provider_id)?.name || "Local mock",
        hint(alias.model_id)), el("td", {}, alias.builtin ? badge("Server managed") :
        el("div", {class: "row-actions"}, button("Edit", () => aliasEditor(data, alias), "quiet"),
          button("Remove", () => remove("aliases", alias), "danger quiet")))));
    container.append(card("Model aliases", table(["Alias", "Provider / model", "Actions"], aliasRows), button("Add model alias", () => aliasEditor(data))));

    const inputs = new Map(), controls = el("div", {class: "semantic-fields"});
    const mode = el("select", {"aria-label": "Model steps"}, option("disabled", "Disabled"), option("mock", "Explicit mocks only"), el("option", {value: "live", disabled: !data.capabilities.live}, "Live models and explicit mocks"));
    mode.value = data.values[key("MODE")]; inputs.set(key("MODE"), () => mode.value);
    controls.append(field("Model steps", mode, "Plain snapshot reads remain available when model steps are disabled."));
    const numbers = [
      ["MAX_CONCURRENT_REQUESTS", "Semantic requests at once", 1, 4, "Applies across all semantic jobs and admin mock tests."],
      ["BATCH_SIZE", "Rows per request", 1, 128, "Inputs grouped into one model request."],
      ["DEFAULT_CALL_LIMIT", "Default call limit", 1, 1000, "Used when a run omits its limit."],
      ["MAX_CALLS", "Maximum call limit", 1, 1000, "Live HTTP attempts across all steps and retries share this total limit. Mock limits remain per expression."],
      ["TIMEOUT_SECONDS", "Worker timeout (seconds)", 5, 600, "The child is terminated if execution exceeds this time."],
      ["CACHE_MAX_AGE_DAYS", "Maximum answer age (days)", 1, 365, "Older retained answers are not reused."]
    ];
    for (const [name, label, minimum, maximum, help] of numbers) {
      const input = el("input", {type: "number", min: minimum, max: maximum, step: 1, required: true, value: data.values[key(name)]});
      inputs.set(key(name), () => Number(input.value)); controls.append(field(label, input, help));
    }
    const access = el("select", {"aria-label": "Who may run model steps"}, option("admins", "Administrators"), option("selected", "Administrators and selected accounts"), option("all", "All accounts"));
    access.value = data.values[key("ACCESS")]; inputs.set(key("ACCESS"), () => access.value);
    controls.append(field("Who may run model steps", access));
    const users = el("fieldset", {class: "semantic-users"}, el("legend", {}, "Selected accounts"));
    const checks = data.accounts.filter(user => user.role !== "admin").map(user => {
      const value = check(user.username + (user.disabled ? " (disabled)" : ""), data.values[key("ACCOUNTS")].includes(user.id));
      users.append(value.label); return {id: user.id, input: value.input};
    });
    inputs.set(key("ACCOUNTS"), () => checks.filter(item => item.input.checked).map(item => item.id));
    const showUsers = () => { users.hidden = access.value !== "selected"; };
    access.addEventListener("change", showUsers); showUsers();
    const warning = el("div", {class: "notice warning", role: "status", hidden: !data.concurrency.warning}, data.concurrency.message);
    const concurrency = controls.querySelector("input");
    concurrency.addEventListener("input", () => {
      warning.hidden = Number(concurrency.value) < data.concurrency.configured_vllm_limit;
      warning.textContent = "Semantic concurrency meets or exceeds the configured vLLM request limit (" + data.concurrency.configured_vllm_limit + "). Leave capacity for planner work.";
    });
    const save = button("Review settings…", () => {
      if (![...controls.querySelectorAll("input")].every(input => input.reportValidity())) return;
      const changes = Object.fromEntries([...inputs].map(([name, read]) => [name, read()]).filter(([name, value]) => JSON.stringify(value) !== JSON.stringify(data.values[name])));
      if (!Object.keys(changes).length) { notice("No settings have changed."); return; }
      const d = dialog("Save semantic settings"), error = message();
      const submit = button("Save changes", () => action(submit, error, async () => {
        await mutate(root + "/settings", {values: changes, expected: data.values, confirm: true}, "PATCH");
        d.close(); await refresh("Semantic settings saved. New workers use these limits; access is checked again before publication.");
      }), "primary");
      const labels = {MODE: "Model steps", ACCESS: "Model access", ACCOUNTS: "Selected accounts", ...Object.fromEntries(numbers.map(([name, label]) => [name, label]))};
      const display = (name, value) => name.endsWith("_ACCOUNTS") ? value.map(id => data.accounts.find(user => user.id === id)?.username || "Unavailable account").join(", ") || "None" : String(value);
      d.node.append(hint("These changes apply to semantic refinement and are recorded in Activity."),
        details(Object.entries(changes).map(([name, value]) => [labels[name.replace("GRAPHMINE_SEMANTIC_", "")] || name,
          display(name, data.values[name]) + " → " + display(name, value)])), error, footer(d, submit)); d.open();
    }, "primary");
    container.append(card("Limits and access", controls, users, warning,
      hint("One dispatch thread per worker. Live attempts share planner slots and token accounting. Mock runs send no vLLM requests."), save));
    const cache = check("Reuse saved answers", data.values[key("CACHE_ENABLED")]); cache.input.disabled = !data.capabilities.cache;
    inputs.set(key("CACHE_ENABLED"), () => cache.input.checked);
    const clear = button("Clear retained answers", () => {
      const d = dialog("Clear retained answers"), error = message();
      const submit = button("Clear answers", () => action(submit, error, async () => {
        await mutate(root + "/cache/clear", {confirm: true}); d.close(); await refresh("Retained answers cleared.");
      }), "danger");
      d.node.append(hint("Clear retained model answers for all accounts? Saved graphs and their provenance remain available."), error, footer(d, submit)); d.open();
    }); clear.disabled = !data.cache.clear_available;
    container.append(card("Answer cache", cache.label, details([["Independently retained answers", data.cache.retained_answers]]),
      hint(data.cache.reason + " Use Review settings to save the cache choice."), clear));
  });
})();
