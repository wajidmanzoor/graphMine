"use strict";

const state = {
  manifest: null,
  operations: [],
  problemRecords: new Map(),
  problemSpecs: new Map(),
  filter: "all",
  query: "",
  manifestUrl: "",
};

const operationGrid = document.querySelector("#operation-grid");
const catalogSummary = document.querySelector("#catalog-summary");
const catalogError = document.querySelector("#catalog-error");
const operationSearch = document.querySelector("#operation-search");
const operationDialog = document.querySelector("#operation-dialog");
const dialogContent = document.querySelector("#dialog-content");
const copyToast = document.querySelector("#copy-toast");

const escapeHtml = (value) =>
  String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

const humanize = (value) =>
  String(value)
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());

const operationTitle = (operation) => {
  const titles = {
    "maximal-cliques": "Maximal cliques",
    "maximum-clique": "Maximum clique",
    "k-cliques": "k-Cliques",
    "quasi-cliques": "Quasi-cliques",
    "k-core": "k-Core decomposition",
    "maximal-bicliques": "Maximal bicliques",
    "triangle-counting": "Triangle counting",
    "dynamic-triangle-counting": "Dynamic triangle counting",
    "graph-motifs": "Graph motifs",
    "subgraph-isomorphism": "Subgraph isomorphism",
    "temporal-motif-mining": "Temporal motif mining",
    "community-detection": "Community detection",
    "betweenness-centrality": "Betweenness centrality",
  };
  return titles[operation.id] || humanize(operation.id);
};

const categoryLabel = (category) => {
  const labels = {
    dense_structure_mining: "Dense structures",
    pattern_and_motif_mining: "Patterns & motifs",
    community_and_structural_analysis: "Graph analysis",
  };
  return labels[category] || humanize(category || "Graph mining");
};

function manifestCandidates() {
  const raw =
    "https://raw.githubusercontent.com/wajidmanzoor/graphMine/main/graphmine_catalog.json";
  if (window.location.hostname.endsWith("github.io")) {
    return [raw];
  }
  return ["./graphmine_catalog.json", "../graphmine_catalog.json", raw];
}

async function loadManifest() {
  let lastError;
  for (const candidate of manifestCandidates()) {
    try {
      const response = await fetch(candidate, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`${candidate} returned ${response.status}`);
      }
      const manifest = await response.json();
      if (!Array.isArray(manifest.operations) || !Array.isArray(manifest.problems)) {
        throw new Error(`${candidate} is not a GraphMine problem catalog`);
      }
      state.manifestUrl = candidate;
      return manifest;
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("No catalog source was available");
}

function hydrateManifest(manifest) {
  state.manifest = manifest;
  state.operations = manifest.operations || [];
  state.problemRecords = new Map(
    (manifest.problems || []).map((entry) => [entry.spec.problem_id, entry]),
  );
  state.problemSpecs = new Map(
    (manifest.problems || []).map((entry) => [
      entry.spec.problem_id,
      entry.spec,
    ]),
  );

  const scope = manifest.scope || {};
  const values = {
    "research-problems": scope.library_supported_problem_count,
    operations: scope.runnable_operation_count,
    backends: scope.validated_backend_count,
  };
  Object.entries(values).forEach(([name, value]) => {
    const element = document.querySelector(`[data-stat="${name}"]`);
    if (element && value !== undefined) element.textContent = value;
  });

  const manifestLink = document.querySelector("#manifest-link");
  if (manifestLink) {
    manifestLink.href = state.manifestUrl.startsWith("http")
      ? state.manifestUrl
      : "https://github.com/wajidmanzoor/graphMine/blob/main/graphmine_catalog.json";
  }

  renderOperations();
}

function searchableText(operation) {
  const spec = state.problemSpecs.get(operation.research_problem_id) || {};
  const problemRecord = state.problemRecords.get(operation.research_problem_id) || {};
  return [
    operation.id,
    operation.cpp_class,
    operation.cmake_component,
    operation.research_problem_id,
    spec.name,
    spec.category,
    spec.problem_statement,
    ...(problemRecord.intent_signals || []),
    ...(spec.problem_inputs || []).flatMap((input) => [
      input.name,
      input.description,
      input.constraints,
    ]),
    ...(operation.backends || []),
    ...(operation.parameters || []),
    ...(operation.required_outputs || []),
    ...Object.keys(operation.optional_output_flags || {}),
    ...Object.values(operation.optional_output_flags || {}).flat(),
    operation.validated_profile,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function problemInputMarkup(inputs) {
  if (!inputs || inputs.length === 0) {
    return '<p class="dialog-class">No problem-specific parameters.</p>';
  }
  return `
    <div class="dialog-table-wrap">
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
  const sourceUrl = problemRecord.source
    ? `https://github.com/wajidmanzoor/graphMine/blob/main/${problemRecord.source}`
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
                `<tr><th>${escapeHtml(humanize(name))}</th><td>${escapeHtml(value)}</td></tr>`,
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
                `<tr><th>${escapeHtml(humanize(name))}</th><td>${escapeHtml(value)}</td></tr>`,
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

function filteredOperations() {
  return state.operations.filter((operation) => {
    const backendCount = (operation.backends || []).length;
    const matchesFilter =
      state.filter === "all" ||
      (state.filter === "multiple" && backendCount > 1) ||
      (state.filter === "single" && backendCount === 1);
    const matchesQuery =
      !state.query || searchableText(operation).includes(state.query);
    return matchesFilter && matchesQuery;
  });
}

function operationCard(operation) {
  const spec = state.problemSpecs.get(operation.research_problem_id) || {};
  const backends = (operation.backends || [])
    .map((backend) => `<span class="backend-chip">${escapeHtml(backend)}</span>`)
    .join("");
  const count = (operation.backends || []).length;
  return `
    <article class="operation-card">
      <div class="operation-meta">
        <span class="category-pill">${escapeHtml(categoryLabel(spec.category))}</span>
        <span class="backend-count">${count} ${count === 1 ? "backend" : "backends"}</span>
      </div>
      <h3>${escapeHtml(operationTitle(operation))}</h3>
      <p class="operation-problem">${escapeHtml(spec.name || operation.research_problem_id)}</p>
      <div class="backend-list" aria-label="Available backends">${backends}</div>
      <div class="operation-command" title="${escapeHtml(operation.command)}">${escapeHtml(operation.command)}</div>
      <button class="operation-action" type="button" data-operation="${escapeHtml(operation.id)}">
        View contract
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10h12m-5-5 5 5-5 5" /></svg>
      </button>
    </article>`;
}

function renderOperations() {
  const operations = filteredOperations();
  const total = state.operations.length;
  catalogSummary.textContent = `Showing ${operations.length} of ${total} runnable operations`;

  if (operations.length === 0) {
    operationGrid.innerHTML = `
      <div class="catalog-empty">
        <strong>No matching operations.</strong><br />
        Try a different algorithm, backend, or output name.
      </div>`;
    return;
  }

  operationGrid.innerHTML = operations.map(operationCard).join("");
}

function listMarkup(items) {
  if (!items || items.length === 0) return '<p class="dialog-class">None</p>';
  return `<ul class="dialog-list">${items
    .map((item) => `<li><code>${escapeHtml(item)}</code></li>`)
    .join("")}</ul>`;
}

function optionalOutputRows(outputs) {
  const entries = Object.entries(outputs || {});
  if (entries.length === 0) return "";
  return `
    <div class="dialog-section">
      <h3>Optional output flags</h3>
      <table class="dialog-table">
        <tbody>
          ${entries
            .map(([flag, fields]) => {
              const value = Array.isArray(fields) ? fields.join(", ") : fields;
              return `<tr><th>${escapeHtml(flag)}</th><td>${escapeHtml(value)}</td></tr>`;
            })
            .join("")}
        </tbody>
      </table>
    </div>`;
}

function constraintRows(constraints) {
  const entries = Object.entries(constraints || {});
  if (entries.length === 0) return "";
  return `
    <div class="dialog-section">
      <h3>Backend-specific profiles</h3>
      <table class="dialog-table">
        <tbody>
          ${entries
            .map(
              ([backend, profile]) =>
                `<tr><th>${escapeHtml(backend)}</th><td>${escapeHtml(profile)}</td></tr>`,
            )
            .join("")}
        </tbody>
      </table>
    </div>`;
}

function openOperationDialog(operationId) {
  const operation = state.operations.find((item) => item.id === operationId);
  if (!operation) return;
  const spec = state.problemSpecs.get(operation.research_problem_id) || {};
  const problemRecord = state.problemRecords.get(operation.research_problem_id) || {};
  const auxiliary = operation.required_auxiliary_inputs || [];
  const profileNotes = [operation.validated_profile, operation.partition_rule].filter(Boolean);

  dialogContent.innerHTML = `
    <p class="dialog-kicker">${escapeHtml(categoryLabel(spec.category))}</p>
    <h2 class="dialog-title">${escapeHtml(operationTitle(operation))}</h2>
    <p class="dialog-class">${escapeHtml(operation.cpp_class)} · ${escapeHtml(operation.cmake_component)}</p>

    ${problemContextMarkup(spec, problemRecord)}

    <div class="dialog-section">
      <h3>Validated backends</h3>
      <div class="dialog-backends">
        ${(operation.backends || [])
          .map((backend) => `<span class="dialog-backend">${escapeHtml(backend)}</span>`)
          .join("")}
      </div>
    </div>

    <div class="dialog-section">
      <h3>Run from the CLI</h3>
      <div class="dialog-command">${escapeHtml(operation.command)}
        <button class="icon-button" type="button" data-copy-command="${escapeHtml(operation.id)}" aria-label="Copy command">
          <svg viewBox="0 0 20 20" aria-hidden="true"><rect x="7" y="7" width="9" height="9" rx="2" /><path d="M13 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2" /></svg>
        </button>
      </div>
    </div>

    <div class="dialog-section">
      <h3>Parameters</h3>
      ${listMarkup(operation.parameters)}
    </div>

    ${
      auxiliary.length
        ? `<div class="dialog-section"><h3>Auxiliary inputs</h3>${listMarkup(auxiliary)}</div>`
        : ""
    }

    ${optionalOutputRows(operation.optional_output_flags)}

    <div class="dialog-section">
      <h3>Required output fields</h3>
      ${listMarkup(operation.required_outputs)}
    </div>

    ${constraintRows(operation.backend_constraints)}

    ${profileNotes
      .map(
        (note) =>
          `<div class="dialog-section profile-note"><strong>Validated profile:</strong> ${escapeHtml(note)}</div>`,
      )
      .join("")}
  `;

  document.body.classList.add("dialog-open");
  if (typeof operationDialog.showModal === "function") {
    operationDialog.showModal();
  } else {
    operationDialog.setAttribute("open", "");
  }
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
  toastTimer = window.setTimeout(() => copyToast.classList.remove("visible"), 1600);
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

function initializeCatalogControls() {
  operationSearch?.addEventListener("input", (event) => {
    state.query = event.target.value.trim().toLowerCase();
    renderOperations();
  });

  document.querySelectorAll("[data-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.filter = button.dataset.filter;
      document.querySelectorAll("[data-filter]").forEach((candidate) => {
        candidate.classList.toggle("active", candidate === button);
      });
      renderOperations();
    });
  });

  operationGrid?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-operation]");
    if (button) openOperationDialog(button.dataset.operation);
  });
}

function initializeDialog() {
  document.querySelector("[data-dialog-close]")?.addEventListener("click", closeOperationDialog);
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

  const updateHeader = () => header?.classList.toggle("scrolled", window.scrollY > 8);
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

async function initializeManifest() {
  try {
    const manifest = await loadManifest();
    hydrateManifest(manifest);
  } catch (error) {
    console.error("GraphMine catalog loading failed", error);
    catalogSummary.textContent = "The operation catalog is unavailable.";
    operationGrid.innerHTML = "";
    catalogError.hidden = false;
  }
}

document.querySelector("#current-year").textContent = new Date().getFullYear();
initializeNavigation();
initializeReveals();
initializeCopyActions();
initializeCatalogControls();
initializeDialog();
initializeManifest();
