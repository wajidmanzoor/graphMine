"use strict";

const state = {
  manifest: null,
  operations: [],
  problems: [],
  families: [],
  family: "",
  problem: "",
  filter: "all",
  query: "",
};
const operationGrid = document.querySelector("#operation-grid");
const catalogSummary = document.querySelector("#catalog-summary");
const catalogError = document.querySelector("#catalog-error");
const operationSearch = document.querySelector("#operation-search");
const operationDialog = document.querySelector("#operation-dialog");
const dialogContent = document.querySelector("#dialog-content");
const copyToast = document.querySelector("#copy-toast");
const familySelect = document.querySelector("#family-select");
const escapeHtml = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
const humanize = (value) =>
  String(value)
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
const displayValue = (value) =>
  typeof value === "object" ? JSON.stringify(value) : String(value);
const sourceLink = (path) =>
  `https://github.com/wajidmanzoor/graphMine/blob/main/${path}`;
const familyTitle = (family) =>
  ({
    community: "Overlapping communities",
    communities: "Community detection",
  })[family.id] || family.title;
const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;
const qualityTitle = (value) =>
  ({
    parameter_dependent: "Quality depends on parameters",
    backend_dependent: "Quality depends on backend",
  })[value] || humanize(value);

function externalLink(url, label) {
  try {
    const parsed = new URL(url);
    if (!["https:", "http:"].includes(parsed.protocol)) return "";
    return `<a href="${escapeHtml(parsed.href)}" target="_blank" rel="noreferrer">${escapeHtml(label)} ↗</a>`;
  } catch {
    return "";
  }
}

function problemOperations(problem) {
  return state.operations.filter(
    (op) =>
      op.problem_id === problem.id &&
      (state.filter === "all" ||
        op.backends.some((b) => b.device === state.filter && b.compiled)),
  );
}

function problemMatches(problem) {
  if (state.filter !== "all" && !problemOperations(problem).length)
    return false;
  if (!state.query) return true;
  const family = state.families.find((f) => f.id === problem.family);
  return JSON.stringify([
    familyTitle(family),
    problem,
    ...problemOperations(problem),
  ])
    .toLowerCase()
    .replaceAll(/[_-]+/g, " ")
    .includes(state.query.replaceAll(/[_-]+/g, " "));
}

function familyCard(family, problems) {
  const count = problems.reduce(
    (sum, p) => sum + problemOperations(p).length,
    0,
  );
  const names = problems
    .slice(0, 3)
    .map((p) => p.name)
    .join(" · ");
  return `<a class="family-card" href="#family/${family.id}" data-family="${family.id}">
    <span class="family-card-top"><span class="family-symbol" aria-hidden="true">◈</span><span>${plural(problems.length, family.id === "query" ? "utility group" : "problem")}</span></span>
    <h3>${escapeHtml(familyTitle(family))}</h3><p>${escapeHtml(names)}${problems.length > 3 ? "…" : ""}</p>
    <span class="family-card-bottom">${plural(count, "algorithm operation")} <span aria-hidden="true">→</span></span>
  </a>`;
}

function operationCard(operation) {
  const devices = [
    ...new Set(
      operation.backends
        .filter((b) => b.compiled)
        .map((b) => b.device.toUpperCase()),
    ),
  ];
  return `<article class="operation-card" data-algorithm="${operation.id}">
    <div class="operation-meta"><span class="category-pill">${escapeHtml(qualityTitle(operation.quality))}</span><span class="backend-count">${devices.join(" / ")}</span></div>
    <h4>${escapeHtml(humanize(operation.id))}</h4><p class="operation-description">${escapeHtml(operation.title)}</p>
    <div class="backend-list" aria-label="Implementation choices">${operation.backends.map((b) => `<span class="backend-chip">${escapeHtml(b.id)}${b.compiled ? "" : " · not compiled"}</span>`).join("")}</div>
    <button class="operation-action" type="button" data-operation="${operation.id}">Algorithm details <span aria-hidden="true">→</span></button>
  </article>`;
}

function problemCard(problem, index) {
  const operations = problemOperations(problem);
  const research = problem.research_algorithms || [];
  const open =
    state.problem === problem.id ||
    !!state.query ||
    (index === 0 && !!state.family && !state.problem);
  return `<details class="problem-card" id="problem-${problem.id}" ${open ? "open" : ""}>
    <summary><span><span class="problem-kind">${problem.contract ? "Problem" : "Workflow utility"}</span><strong>${escapeHtml(problem.name)}</strong></span><span class="problem-count">${plural(operations.length, "operation")}<span class="disclosure-arrow" aria-hidden="true">⌄</span></span></summary>
    <div class="problem-body"><p class="problem-statement">${escapeHtml(problem.spec.problem_statement)}</p>
      <div class="problem-links"><a href="#problem/${problem.id}">Link to this problem</a>${problem.contract ? externalLink(sourceLink(problem.contract), "Formal contract") : ""}</div>
      <h4 class="algorithm-heading">Algorithms and implementations</h4>
      <div class="operation-grid">${operations.map(operationCard).join("") || '<p class="catalog-empty">No implementation matches this filter.</p>'}</div>
      ${research.length ? `<details class="research-references"><summary>${plural(research.length, "research algorithm reference")}</summary><p>Collected papers and source implementations. A research reference does not establish runtime availability; use the implementation profiles above.</p><ul>${research.map((a) => `<li><strong>${escapeHtml(a.title || a.paper_id)}</strong><span>${escapeHtml([a.year, a.venue].filter(Boolean).join(" · "))}</span><div>${externalLink(a.publication_url, "Paper")} ${externalLink(a.code_url, "Source code")}</div></li>`).join("")}</ul></details>` : ""}
    </div>
  </details>`;
}

function renderOperations() {
  const groups = state.families
    .filter((f) => !state.family || f.id === state.family)
    .map((family) => ({
      family,
      problems: state.problems.filter(
        (p) => p.family === family.id && problemMatches(p),
      ),
    }))
    .filter((g) => g.problems.length);
  const problems = groups.flatMap((g) => g.problems);
  const count = problems.reduce(
    (sum, p) => sum + problemOperations(p).length,
    0,
  );
  const family = state.families.find((f) => f.id === state.family);
  document.querySelector("#catalog-breadcrumb").innerHTML =
    `<a href="#operations">All families</a>${family ? `<span aria-hidden="true">/</span><span>${escapeHtml(familyTitle(family))}</span>` : ""}`;
  familySelect.value = state.family;
  catalogSummary.textContent = `${plural(groups.length, "family").replace("familys", "families")} · ${plural(problems.filter((p) => p.contract).length, "formal problem")}${problems.some((p) => !p.contract) ? " + graph-record query utilities" : ""} · ${plural(count, "algorithm operation")}`;
  if (!groups.length) {
    operationGrid.innerHTML =
      '<div class="catalog-empty"><strong>No matching problems or algorithms.</strong><p>Try another family, algorithm name, implementation or output.</p><button type="button" class="button button-secondary" data-clear-catalog>Clear filters</button></div>';
    return;
  }
  const overview = !state.family && !state.query && state.filter === "all";
  operationGrid.className = overview ? "family-grid" : "family-results";
  operationGrid.innerHTML = overview
    ? groups.map((g) => familyCard(g.family, g.problems)).join("")
    : groups
        .map(
          (g) =>
            `<section class="family-section" aria-labelledby="family-title-${g.family.id}"><div class="family-section-heading"><p class="section-kicker">Problem family</p><h3 id="family-title-${g.family.id}">${escapeHtml(familyTitle(g.family))}</h3></div>${g.problems.map(problemCard).join("")}</section>`,
        )
        .join("");
}

function readCatalogLocation(scroll = false) {
  if (!state.manifest) return;
  const [kind, id] = location.hash.slice(1).split("/");
  if (!["family", "problem", "operations"].includes(kind)) return;
  const problem = kind === "problem" && state.problems.find((p) => p.id === id);
  const family = state.families.find(
    (f) => f.id === (problem ? problem.family : id),
  );
  state.family = family?.id || "";
  state.problem = problem?.id || "";
  if (problem || kind === "operations") {
    state.query = "";
    operationSearch.value = "";
    state.filter = "all";
    updateFilterButtons();
  }
  renderOperations();
  if (scroll)
    requestAnimationFrame(() => {
      const target = state.problem
        ? document.getElementById(`problem-${state.problem}`)
        : document.getElementById("operations");
      target?.scrollIntoView({ behavior: "instant", block: "start" });
    });
}

function parameterMarkup(parameters) {
  return `<div class="dialog-table-wrap" tabindex="0" role="region" aria-label="Scrollable table"><table class="dialog-table"><thead><tr><th>Parameter</th><th>Type and limits</th><th>Default</th></tr></thead><tbody>${Object.entries(
    parameters,
  )
    .map(
      ([name, p]) =>
        `<tr><th><code>${escapeHtml(name)}</code>${p.required ? "<small>Required</small>" : ""}</th><td>${escapeHtml(p.kind)}${p.nullable ? " or null" : ""}${p.choices ? `<br>${escapeHtml(p.choices.join(" · "))}` : ""}${p.minimum !== undefined ? `<br>Minimum: ${escapeHtml(p.minimum)}` : ""}${p.maximum !== undefined ? `<br>Maximum: ${escapeHtml(p.maximum)}` : ""}${p.json_schema ? `<details><summary>Value schema</summary><pre>${escapeHtml(JSON.stringify(p.json_schema, null, 2))}</pre></details>` : ""}</td><td>${Object.hasOwn(p, "default") ? `<code>${escapeHtml(displayValue(p.default))}</code>` : "—"}</td></tr>`,
    )
    .join("")}</tbody></table></div>`;
}

function openOperationDialog(operationId) {
  const operation = state.operations.find((op) => op.id === operationId);
  if (!operation) return;
  const problem = state.problems.find((p) => p.id === operation.problem_id);
  const family = state.families.find((f) => f.id === problem.family);
  dialogContent.innerHTML = `<p class="dialog-kicker">${escapeHtml(familyTitle(family))} / ${escapeHtml(problem.name)}</p>
    <h2 class="dialog-title" id="algorithm-dialog-title">${escapeHtml(humanize(operation.id))}</h2>
    <p>${escapeHtml(operation.description)}</p>
    <p class="dialog-class">Input: ${escapeHtml(humanize(operation.input_kind))} · ${escapeHtml(qualityTitle(operation.quality))}</p>
    ${problem.contract ? problemContextMarkup(problem.spec, problem) : ""}
    <div class="dialog-section"><h3>Implementation profiles</h3><div class="dialog-table-wrap" tabindex="0" role="region" aria-label="Scrollable table"><table class="dialog-table"><thead><tr><th>Implementation</th><th>Device</th><th>Documentation build</th></tr></thead><tbody>${operation.backends.map((b) => `<tr><th>${escapeHtml(b.id)}</th><td>${escapeHtml(b.device.toUpperCase())}</td><td>${b.compiled ? "Compiled" : "Not compiled"}${b.execution ? `<br>${escapeHtml(b.execution)}` : ""}</td></tr>`).join("")}</tbody></table></div>
      <p class="profile-note">Availability depends on your build, inputs and hardware. Application execution also requires a matching validation report; a compiled backend alone does not establish admission.</p>
      ${operation.gpu_limitations?.length ? `<h4>GPU profile limits</h4>${listMarkup(operation.gpu_limitations)}` : ""}
    </div>
    <div class="dialog-section"><h3>Native CLI</h3><p>Save the required parameters below in <code>PARAMETERS.json</code>; use <code>{}</code> when no parameters are needed.</p><div class="dialog-command">${escapeHtml(operation.command)}<button class="text-copy" type="button" data-copy-command="${operation.id}">Copy</button></div></div>
    <div class="dialog-section"><h3>Parameters</h3>${Object.keys(operation.parameters).length ? parameterMarkup(operation.parameters) : "<p>No operation-specific parameters.</p>"}</div>
    <div class="dialog-section"><h3>Outputs</h3><table class="dialog-table"><thead><tr><th>Port</th><th>Type</th></tr></thead><tbody>${Object.entries(
      operation.output_ports,
    )
      .map(
        ([key, value]) =>
          `<tr><th><code>${escapeHtml(key)}</code></th><td>${escapeHtml(value.type)}</td></tr>`,
      )
      .join(
        "",
      )}</tbody></table><p>Output availability and completeness are checked at runtime.</p></div>
    <div class="dialog-section">${externalLink(sourceLink("docs/NATIVE_CORE_MIGRATION.md"), "Native runtime guide")} · ${externalLink(sourceLink("catalog/native_execution_evidence.json"), "Execution evidence")}</div>`;
  operationDialog.setAttribute("aria-labelledby", "algorithm-dialog-title");
  document.body.classList.add("dialog-open");
  operationDialog.showModal();
}

function updateFilterButtons() {
  document.querySelectorAll("[data-filter]").forEach((button) => {
    const active = button.dataset.filter === state.filter;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function initializeCatalogControls() {
  document.addEventListener("click", (event) => {
    if (
      event.target.closest('a[href="#operations"]') &&
      location.hash === "#operations"
    ) {
      readCatalogLocation();
    }
  });
  operationSearch.addEventListener("input", (event) => {
    state.query = event.target.value.trim().toLowerCase();
    state.problem = "";
    renderOperations();
  });
  familySelect.addEventListener("change", () => {
    location.hash = familySelect.value
      ? `family/${familySelect.value}`
      : "operations";
  });
  document.querySelectorAll("[data-filter]").forEach((button) =>
    button.addEventListener("click", () => {
      state.filter = button.dataset.filter;
      updateFilterButtons();
      renderOperations();
    }),
  );
  operationGrid.addEventListener("click", (event) => {
    const button = event.target.closest("[data-operation]");
    if (button) openOperationDialog(button.dataset.operation);
    if (event.target.closest("[data-clear-catalog]")) {
      state.query = "";
      operationSearch.value = "";
      state.filter = "all";
      state.family = "";
      state.problem = "";
      updateFilterButtons();
      history.replaceState(null, "", "#operations");
      renderOperations();
    }
  });
  window.addEventListener("hashchange", () => readCatalogLocation(true));
}

async function initializeManifest() {
  try {
    const response = await fetch("./catalog.json", { cache: "no-cache" });
    if (!response.ok) throw new Error(`Catalog returned ${response.status}`);
    const manifest = await response.json();
    if (manifest.schema_version !== "graphmine-docs-catalog-v1")
      throw new Error("Unknown catalog format");
    state.manifest = manifest;
    state.families = manifest.families;
    state.problems = manifest.problems;
    state.operations = manifest.operations.map((op) => ({
      ...op,
      command: `graphmine-native run ${op.id} INPUT.json --parameters PARAMETERS.json --device cpu`,
    }));
    familySelect.innerHTML =
      '<option value="">All families</option>' +
      state.families
        .map(
          (f) =>
            `<option value="${f.id}">${escapeHtml(familyTitle(f))}</option>`,
        )
        .join("");
    document.querySelectorAll("[data-stat]").forEach((el) => {
      const value = manifest.counts[el.dataset.stat];
      if (value !== undefined) el.textContent = value;
    });
    renderOperations();
    readCatalogLocation(true);
    updateFilterButtons();
    document.documentElement.dataset.catalogReady = "true";
  } catch (error) {
    console.error("GraphMine catalog loading failed", error);
    catalogSummary.textContent = "The family catalog is unavailable.";
    operationGrid.innerHTML = "";
    catalogError.hidden = false;
  }
}

function problemInputMarkup(inputs) {
  if (!inputs || inputs.length === 0) {
    return '<p class="dialog-class">No problem-specific parameters.</p>';
  }
  return `
    <div class="dialog-table-wrap" tabindex="0" role="region" aria-label="Scrollable table">
      <table class="dialog-table dialog-input-table">
        <thead><tr><th>Input</th><th>Contract</th></tr></thead>
        <tbody>
          ${inputs
            .map((input) => {
              const defaultValue = Object.hasOwn(input, "default")
                ? JSON.stringify(input.default)
                : "none";
              return `<tr>
                <th><code>${escapeHtml(input.name)}</code></th>
                <td>
                  <strong>${escapeHtml(input.type)}</strong> · ${input.required ? "required" : `default ${escapeHtml(defaultValue)}`}<br />
                  ${escapeHtml(input.description || "")}
                  ${input.constraints ? `<small>${escapeHtml(input.constraints)}</small>` : ""}
                </td>
              </tr>`;
            })
            .join("")}
        </tbody>
      </table>
    </div>`;
}

function problemContextMarkup(spec, problemRecord) {
  const requirements = Object.entries(spec.graph_input?.requirements || {});
  const semantics = Object.entries(spec.solution_semantics || {});
  const sourceUrl = problemRecord.contract
    ? `https://github.com/wajidmanzoor/graphMine/blob/main/${problemRecord.contract}`
    : "https://github.com/wajidmanzoor/graphMine/blob/main/graphmine_catalog.json";
  return `
    <div class="dialog-problem-summary">
      <p>${escapeHtml(spec.problem_statement || "")}</p>
      <a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noreferrer">Open exact problem JSON</a>
    </div>
    <details class="dialog-context">
      <summary>Full problem contract</summary>
      <div class="dialog-section">
        <h3>Problem inputs</h3>
        ${problemInputMarkup(spec.problem_inputs)}
      </div>
      <div class="dialog-section">
        <h3>Graph requirements</h3>
        <table class="dialog-table">
          <tbody>${requirements
            .map(
              ([name, value]) =>
                `<tr><th>${escapeHtml(humanize(name))}</th><td>${escapeHtml(displayValue(value))}</td></tr>`,
            )
            .join("")}</tbody>
        </table>
      </div>
      <div class="dialog-section">
        <h3>Solution semantics</h3>
        <table class="dialog-table">
          <tbody>${semantics
            .map(
              ([name, value]) =>
                `<tr><th>${escapeHtml(humanize(name))}</th><td>${escapeHtml(displayValue(value))}</td></tr>`,
            )
            .join("")}</tbody>
        </table>
      </div>
      <div class="dialog-section">
        <h3>Edge cases</h3>
        ${listMarkup(spec.edge_cases)}
      </div>
    </details>`;
}

function listMarkup(items) {
  if (!items || items.length === 0) return '<p class="dialog-class">None</p>';
  return `<ul class="dialog-list">${items
    .map((item) => `<li><code>${escapeHtml(item)}</code></li>`)
    .join("")}</ul>`;
}

function closeOperationDialog() {
  if (operationDialog.open && typeof operationDialog.close === "function") {
    operationDialog.close();
  } else {
    operationDialog.removeAttribute("open");
  }
  document.body.classList.remove("dialog-open");
}

let toastTimer;
function showCopyToast() {
  window.clearTimeout(toastTimer);
  copyToast.classList.add("visible");
  toastTimer = window.setTimeout(
    () => copyToast.classList.remove("visible"),
    1600,
  );
}

async function copyText(text) {
  const normalized = text.replace(/^\$\s?/, "").trim();
  try {
    await navigator.clipboard.writeText(normalized);
  } catch {
    const textarea = document.createElement("textarea");
    textarea.value = normalized;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.append(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
  }
  showCopyToast();
}

function initializeCopyActions() {
  document.addEventListener("click", (event) => {
    const targetButton = event.target.closest("[data-copy-target]");
    if (targetButton) {
      const target = document.getElementById(targetButton.dataset.copyTarget);
      if (target) copyText(target.innerText);
      return;
    }

    const commandButton = event.target.closest("[data-copy-command]");
    if (commandButton) {
      const operation = state.operations.find(
        (item) => item.id === commandButton.dataset.copyCommand,
      );
      if (operation) copyText(operation.command);
    }
  });
}

function initializeDialog() {
  document
    .querySelector("[data-dialog-close]")
    ?.addEventListener("click", closeOperationDialog);
  operationDialog?.addEventListener("click", (event) => {
    if (event.target === operationDialog) closeOperationDialog();
  });
  operationDialog?.addEventListener("close", () => {
    document.body.classList.remove("dialog-open");
  });
}

function initializeNavigation() {
  const header = document.querySelector("[data-header]");
  const menuToggle = document.querySelector("[data-menu-toggle]");
  const navigation = document.querySelector("[data-navigation]");

  const updateHeader = () =>
    header?.classList.toggle("scrolled", window.scrollY > 8);
  updateHeader();
  window.addEventListener("scroll", updateHeader, { passive: true });

  menuToggle?.addEventListener("click", () => {
    const expanded = menuToggle.getAttribute("aria-expanded") === "true";
    menuToggle.setAttribute("aria-expanded", String(!expanded));
    navigation?.classList.toggle("open", !expanded);
  });

  navigation?.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => {
      menuToggle?.setAttribute("aria-expanded", "false");
      navigation.classList.remove("open");
    });
  });

  const sectionLinks = new Map(
    [...document.querySelectorAll('.primary-nav a[href^="#"]')].map((link) => [
      link.getAttribute("href").slice(1),
      link,
    ]),
  );
  const sections = [...sectionLinks.keys()]
    .map((id) => document.getElementById(id))
    .filter(Boolean);

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (!visible) return;
        sectionLinks.forEach((link, id) => {
          link.classList.toggle("active", id === visible.target.id);
        });
      },
      { rootMargin: "-20% 0px -65% 0px", threshold: [0.05, 0.2, 0.5] },
    );
    sections.forEach((section) => observer.observe(section));
  }
}

function initializeReveals() {
  const elements = document.querySelectorAll(".reveal");
  if (!("IntersectionObserver" in window)) {
    elements.forEach((element) => element.classList.add("visible"));
    return;
  }
  const observer = new IntersectionObserver(
    (entries, currentObserver) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("visible");
        currentObserver.unobserve(entry.target);
      });
    },
    { rootMargin: "0px 0px -8%", threshold: 0.08 },
  );
  elements.forEach((element) => observer.observe(element));
}

document.querySelector("#current-year").textContent = new Date().getFullYear();
initializeNavigation();
initializeReveals();
initializeCopyActions();
initializeCatalogControls();
initializeDialog();
initializeManifest();
