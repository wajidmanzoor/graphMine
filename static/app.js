"use strict";
/* Dataset Studio front end — vanilla JS, no build step. */

// ------------------------------------------------------------------ utilities
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const norm = (s) => String(s || "").trim().toLowerCase().replace(/\s+/g, " ");
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const plural = (n, w) => `${n.toLocaleString()} ${w}${n === 1 ? "" : "s"}`;
const store = {
  get(k, d) { try { const v = localStorage.getItem("dataset-studio:" + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("dataset-studio:" + k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};

// A studio served beyond localhost needs its access token. The link it prints
// carries ?token=…; it is kept in this browser and removed from the address bar.
(() => {
  const url = new URL(location.href);
  const t = url.searchParams.get("token");
  if (t) {
    store.set("token", t);
    url.searchParams.delete("token");
    history.replaceState(null, "", url.pathname + url.search + url.hash);
  }
})();
async function api(path, body) {
  const headers = body === undefined ? {} : { "Content-Type": "application/json" };
  const token = store.get("token", "");
  if (token) headers["X-Studio-Token"] = token;
  const opt = body === undefined ? { headers } : { method: "POST", headers, body: JSON.stringify(body) };
  const res = await fetch(path, opt);
  if (res.status === 401) {
    const entered = prompt("This studio needs its access token (printed when the server started):");
    if (entered) { store.set("token", entered.trim()); return api(path, body); }
  }
  const data = await res.json().catch(() => ({ error: res.statusText }));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

let toastTimer;
function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isError ? " error" : "");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), isError ? 6000 : 2600);
}
const fail = (e) => toast(e.message || String(e), true);

const tip = $("#tooltip");
function showTip(ev, html) {
  tip.innerHTML = html;
  tip.hidden = false;
  const pad = 14, r = tip.getBoundingClientRect();
  let x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - pad;
  if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - pad;
  tip.style.left = x + "px";
  tip.style.top = y + "px";
}
const hideTip = () => (tip.hidden = true);

// ------------------------------------------------------------------ constants
// In the order GraphMine runs them in a chat; labels follow the agent's own progress messages.
const STAGES = ["RouteDecision", "PlanDraft", "GroundedNarrative", "TurnDecision"];
const STAGE_LABEL = { RouteDecision: "Understanding", PlanDraft: "Planning", GroundedNarrative: "Analyst answer", TurnDecision: "Follow-up check" };
const STAGE_HELP = {
  RouteDecision: "RouteDecision (planner): which problem/operation answers the question, or what to ask the user",
  PlanDraft: "PlanDraft (planner): concrete plan with parameters, outputs and backend",
  GroundedNarrative: "GroundedNarrative (analyst): answer grounded in the computed facts",
  TurnDecision: "TurnDecision (planner): what a follow-up message needs: explain, analyze again or clarify",
};
const REVIEW = {
  unreviewed: { icon: "", cls: "muted", label: "Unreviewed" },
  approved: { icon: "✓", cls: "good", label: "Approved" },
  needs_fix: { icon: "!", cls: "serious", label: "Needs fix" },
  rejected: { icon: "✕", cls: "critical", label: "Rejected" },
};
const REVIEW_ORDER = ["unreviewed", "approved", "needs_fix", "rejected"];
const CATEGORY_LABEL = {
  dense_structure_mining: "Dense structure",
  pattern_and_motif_mining: "Patterns & motifs",
  community_and_structural_analysis: "Community & structure",
  predictive_and_unusual_structure_mining: "Predictive & unusual",
};
const NONE = "__none__";
// Variants that say nothing the thread does not already show.
const HIDDEN_VARIANTS = ["initial", "plan_first", "manual", "conversation", "recovery"];
const PAGE = 150;

// ------------------------------------------------------------------ state
const S = {
  meta: null, datasets: [], dataset: null,
  examples: [], byId: new Map(),
  facetSel: {}, facetShowAll: {}, facetFilter: {},
  query: "", parsed: { terms: [], filters: [] },
  sort: store.get("sort", "file"), showDeleted: store.get("showDeleted", false),
  // "conv": one list entry per conversation (all stages of one case); "rows": one entry per training row
  mode: store.get("mode", "conv") === "rows" ? "rows" : "conv",
  selected: new Set(), currentId: null,
  convs: new Map(), convOrder: [], convKey: null, rowView: false,
  view: "browse", tab: "conversation", outputMode: store.get("outputMode", "tree"),
  editing: null,
  visible: [], flatOrder: [], rendered: 0,
  problems: new Map(), operations: new Map(),
  contextCache: new Map(),
  coverageFiltered: false,
  // Server summaries per conversation: graph and domain, last build, freshness, next steps.
  conversations: {},
  convContext: new Map(),
  stagesPresent: new Set(),
};

// ------------------------------------------------------------------ catalog helpers
const problemName = (id) => (id && S.problems.get(id)?.name) || id || "(untagged)";
const categoryLabel = (c) => CATEGORY_LABEL[c] || String(c || "other").replace(/_/g, " ");
const opsOfProblem = (pid) => S.problems.get(pid)?.operation_ids || [];
const backendsOf = (op) => S.operations.get(op)?.backends || [];
function outcome(e) {
  const o = e.output || {};
  if (e.schema === "PlanDraft") return o.status || "unknown";
  if (e.schema === "TurnDecision") return o.action || "unknown";
  if (e.schema === "RouteDecision") {
    if (o.supported) return "supported";
    if ((o.ambiguity || []).length || (o.missing_information || []).length) return "needs_information";
    return "unsupported";
  }
  if (e.schema === "GroundedNarrative") return (o.charts || []).length ? "narrative + chart" : "narrative";
  return "unknown";
}
function isClarify(e) {
  const o = e.output || {};
  return (e.schema === "PlanDraft" && o.status === "needs_information")
    || (e.schema === "TurnDecision" && o.action === "clarify")
    || (e.schema === "RouteDecision" && ((o.ambiguity || []).length > 0 || (o.missing_information || []).length > 0));
}
const issueLevel = (e) => (e.issues.some((i) => i.level === "error") ? "error" : e.issues.some((i) => i.level === "warning") ? "warning" : "");
const primaryQ = (e) => e.prompts?.[0]?.value || "";

function prepare(e) {
  e._q = primaryQ(e);
  e._clarify = isClarify(e);
  e._outcome = outcome(e);
  e._issue = issueLevel(e);
  e._outLen = JSON.stringify(e.output ?? "").length;
  e._blob = [
    e.id, ...e.prompts.map((p) => p.value), ...e.turns.map((t) => t.text), JSON.stringify(e.output ?? ""),
    e.notes, ...e.labels, e.tags.problem_id, problemName(e.tags.problem_id), e.tags.operation_id, e.tags.backend, e.lineage,
  ].join("\n").toLowerCase();
  return e;
}

// ------------------------------------------------------------------ conversations
// A conversation is every training row generated for one question on one graph
// (rows sharing `group`, the source case; the server also joins a reply to a
// clarification question onto the case that asked it). Steps are shown in the
// order GraphMine produces them in a live chat:
//   0 question → understanding → planning
//   1 Qwen's clarification question → the user's reply → understanding → planning
//   2 (branch) retry after a failed attempt
//   3 GraphMine runs the plan → analyst answer
//   4 (branches) other first requests to the analyst
//   5 (branches) follow-up messages: follow-up check → understanding → planning → answer
// Rows remain separate training examples; this is a view.
const STEP_STAGE = { TurnDecision: 0, RouteDecision: 1, PlanDraft: 2, GroundedNarrative: 3 };
const PHASE_SECTION = ["main", "main", "recovery", "main", "analyst", "followup", "other"];
const isRecovery = (e) => e.variant === "recovery" || /-recovery-/.test(e.id);
const isCustomChart = (e) => e.variant === "custom_chart" || /-custom-chart\b/.test(e.id);
// A follow-up comes after a finished answer. Earlier turns alone do not say so:
// production also sends the planner's messages as history to the main answer.
function isAfterAnswer(e) {
  return e.schema === "TurnDecision" || e.turns.some((t) => t.role === "assistant"
    && (t.status === "answered" || t.payload?.result_id || t.payload?.interpretation));
}
// The row's earlier turns end with the agent asking for information: the user is replying to it.
function isClarifyReply(e) {
  const last = e.turns[e.turns.length - 1];
  return last?.role === "assistant" && last.status === "needs_information" && !isAfterAnswer(e)
    && (e.schema === "RouteDecision" || e.schema === "PlanDraft");
}
function stepPhase(e) {
  if (isRecovery(e)) return 2;
  if (isAfterAnswer(e)) return 5;
  if (isClarifyReply(e)) return 1;
  if (e.schema === "RouteDecision" || e.schema === "PlanDraft") return 0;
  if (e.schema === "GroundedNarrative") return isCustomChart(e) ? 4 : 3;
  return 6;
}

// How far a conversation got, in the order steps are written. A stage only counts
// when the dataset has that kind of step (a routing-only dataset is complete after
// Understanding); a dataset made in the studio expects every stage.
const PROGRESS = {
  needs_understanding: "Needs understanding", needs_planning: "Needs planning", ready_to_run: "Ready to run",
  needs_answer: "Needs analyst answer", waiting_reply: "Waiting for the user's reply", refused: "Refused",
  complete: "Complete",
};
const PROGRESS_ORDER = Object.keys(PROGRESS);
const asksForInfo = (o) => (o?.ambiguity || []).length > 0 || (o?.missing_information || []).length > 0;
function progressOf(c) {
  const has = (schema) => S.dataset?.layout === "studio" || S.stagesPresent.has(schema);
  const live = c.live.filter((e) => e._section === "main" || e._section === "analyst");
  if (live.some((e) => e.schema === "GroundedNarrative")) return "complete";
  const opening = live.filter((e) => e._phase === 0), replies = live.filter((e) => e._phase === 1);
  const path = replies.length ? replies : opening;
  const route = path.find((e) => e.schema === "RouteDecision"), plan = path.find((e) => e.schema === "PlanDraft");
  if (has("RouteDecision")) {
    if (!route) return "needs_understanding";
    if (asksForInfo(route.output)) return "waiting_reply";
    if (route.output?.supported === false) return "refused";
  }
  if (has("PlanDraft")) {
    if (!plan) return "needs_planning";
    const status = plan.output?.status;
    if (status === "needs_information") return "waiting_reply";
    if (status === "unsupported") return "refused";
    if (status !== "ready") return "needs_planning";
  }
  if (!has("GroundedNarrative")) return "complete";
  const sum = S.conversations[c.key];
  if (sum?.replayable && !(sum.built && sum.fresh && sum.ran && !sum.needs_run)) return "ready_to_run";
  return "needs_answer";
}
// Steps answering the same alternative message share one branch.
const stepBranch = (e, phase) => (phase === 4 || phase === 5 ? `${phase}:${norm(userMessage(e))}` : String(phase));
const SECTION_INFO = {
  recovery: ["Retry after a failed attempt", "An alternative path: the first understanding or plan failed a check, so Qwen redoes it before GraphMine runs anything. The failure details are in each step's model context."],
  analyst: ["Other requests to the analyst", "Same computed result, a different first request to the analyst. Each one is a separate training row."],
  followup: ["Follow-up messages", "Each box is an alternative next message after the first answer: Qwen checks the follow-up first, then answers or plans again. Each step is a separate training row."],
  other: ["Other rows", "Rows from this case that do not fit the steps above."],
};

function userMessage(e) {
  const p = e.prompts || [];
  const pick = e.adapter === "analyst" ? (p.find((x) => x.path === "user_message") || p.find((x) => x.path === "answer.question"))
    : p.find((x) => x.path === "message");
  return (pick || p[0] || {}).value || "";
}
function openingQuestion(e) {
  if (!e) return "";
  // A follow-up or a clarification reply: the conversation began with the first earlier user turn.
  if (e.turns[0]?.role === "user") return e.turns[0].text;
  const p = e.prompts || [];
  return (p.find((x) => x.path === "message") || p.find((x) => x.path === "answer.question") || p[0] || {}).value || "";
}

function buildConvs() {
  const idx = new Map(S.examples.map((e, i) => [e.id, i]));
  const map = new Map();
  for (const e of S.examples) {
    if (!map.has(e.group)) map.set(e.group, { key: e.group, steps: [] });
    map.get(e.group).steps.push(e);
  }
  for (const c of map.values()) {
    const branchStart = new Map();
    for (const e of c.steps) {
      // Clones sit right after the row they were cloned from.
      const src = e.kind === "clone" && S.byId.get(e.clone_of)?.group === c.key ? S.byId.get(e.clone_of) : e;
      e._phase = stepPhase(src);
      e._section = PHASE_SECTION[e._phase];
      e._branch = stepBranch(src, e._phase);
      e._stage = STEP_STAGE[src.schema] ?? 9;
      e._order = idx.get(src.id) + (src === e ? 0 : 0.5 + idx.get(e.id) / 1e7);
      branchStart.set(e._branch, Math.min(branchStart.get(e._branch) ?? Infinity, e._order));
    }
    c.steps.sort((a, b) => a._phase - b._phase || branchStart.get(a._branch) - branchStart.get(b._branch)
      || a._stage - b._stage || a._order - b._order);
    c.live = c.steps.filter((e) => !e.deleted);
    const pool = c.live.length ? c.live : c.steps;
    c.opener = pool.find((e) => e._section === "main") || pool[0];
    // The opening route of a clarification asks a question and has no operation to show.
    c.tagged = pool.find((e) => e._section === "main" && e.tags.problem_id) || c.opener;
    c.question = openingQuestion(c.opener);
    c.split = c.opener.split;
    c.lineage = c.opener.lineage;
    // A conversation-level fact on every step, so it filters like any row facet.
    c.progress = progressOf(c);
    for (const e of c.steps) e._progress = c.progress;
  }
  S.convs = map;
}
const convSteps = (c) => (S.showDeleted || !c.live.length ? c.steps : c.live);
const currentConv = () => S.convs.get(S.convKey);
const filtersActive = () => !!S.query.trim() || Object.values(S.facetSel).some((s) => s?.size);

// ------------------------------------------------------------------ facets & search
const FACETS = [
  { key: "adapter", label: "Model", get: (e) => [e.adapter], fmt: (v) => (v === "planner" ? "Planner" : v === "analyst" ? "Analyst" : v) },
  { key: "split", label: "Split", get: (e) => [e.split] },
  { key: "schema", label: "Stage", get: (e) => [e.schema || NONE], fmt: (v) => (v === NONE ? "(unknown)" : `${STAGE_LABEL[v] || v}`), dot: true },
  { key: "outcome", label: "Expected outcome", get: (e) => [e._outcome], fmt: (v) => v.replace(/_/g, " ") },
  { key: "conv", label: "Conversation", get: (e) => [e.turns.length ? "multi-turn" : "single turn", ...(e._clarify ? ["asks for more info"] : [])] },
  { key: "progress", label: "Progress", get: (e) => [e._progress], fmt: (v) => PROGRESS[v] || v, order: PROGRESS_ORDER },
  { key: "problem", label: "Problem", get: (e) => [e.tags.problem_id || NONE], fmt: (v) => (v === NONE ? "(untagged)" : problemName(v)), search: true, grouped: true },
  { key: "operation", label: "Operation", get: (e) => [e.tags.operation_id || NONE], fmt: (v) => (v === NONE ? "(untagged)" : v), search: true },
  { key: "backend", label: "Implementation", get: (e) => [e.tags.backend || NONE], fmt: (v) => (v === NONE ? "(auto / unknown)" : v), search: true },
  { key: "review", label: "Review", get: (e) => [e.review], fmt: (v) => REVIEW[v]?.label || v, order: REVIEW_ORDER },
  { key: "labels", label: "Labels", get: (e) => (e.labels.length ? e.labels : [NONE]), fmt: (v) => (v === NONE ? "(no label)" : v), search: true },
  { key: "issues", label: "Validation", get: (e) => (e._issue ? [e._issue === "error" ? "has errors" : "has warnings"] : ["clean"]) },
  { key: "kind", label: "Changes", get: (e) => [e.deleted ? "deleted" : e.kind], order: ["original", "annotated", "edited", "clone", "new", "deleted"] },
  { key: "tagsrc", label: "Tag source", get: (e) => [Object.keys(e.manual_tags || {}).length ? "manual tags" : "auto tags"] },
  { key: "variant", label: "Variant", get: (e) => [e.variant || NONE], fmt: (v) => (v === NONE ? "—" : v.replace(/_/g, " ")) },
  { key: "lineage", label: "Graph source", get: (e) => [e.lineage || NONE], fmt: (v) => (v === NONE ? "—" : v), search: true },
];
const FACET_BY_KEY = Object.fromEntries(FACETS.map((f) => [f.key, f]));
const FIELD_ALIASES = {
  op: "operation", operation: "operation", problem: "problem", impl: "backend", backend: "backend", implementation: "backend",
  stage: "schema", schema: "schema", split: "split", model: "adapter", adapter: "adapter", review: "review",
  label: "labels", labels: "labels", status: "outcome", outcome: "outcome", lineage: "lineage", source: "lineage",
  kind: "kind", variant: "variant", has: "has", id: "id", progress: "progress",
};

function parseQuery(q) {
  const tokens = q.match(/-?[\w]+:"[^"]*"|-?[\w]+:\S+|"[^"]*"|\S+/g) || [];
  const terms = [], filters = [];
  const unq = (s) => s.replace(/^"|"$/g, "");
  for (let t of tokens) {
    let neg = false;
    if (t.startsWith("-") && /^-\w+:/.test(t)) { neg = true; t = t.slice(1); }
    const m = t.match(/^(\w+):(.*)$/);
    if (m && FIELD_ALIASES[m[1].toLowerCase()] && m[2]) {
      filters.push({ key: FIELD_ALIASES[m[1].toLowerCase()], value: norm(unq(m[2])), neg });
    } else {
      const v = norm(unq(t));
      if (v) terms.push(v);
    }
  }
  return { terms, filters };
}

function hasFlag(e, flag) {
  switch (flag) {
    case "clarify": case "clarification": return e._clarify;
    case "turns": case "multiturn": return e.turns.length > 0;
    case "errors": case "error": return e._issue === "error";
    case "warnings": case "warning": return e._issue === "warning";
    case "issues": return !!e._issue;
    case "notes": return !!e.notes;
    case "labels": return e.labels.length > 0;
    case "manual": return Object.keys(e.manual_tags || {}).length > 0;
    case "edits": case "changes": return e.kind !== "original" || e.deleted;
    default: return false;
  }
}

function matchesQuery(e, parsed) {
  for (const t of parsed.terms) if (!e._blob.includes(t)) return false;
  for (const f of parsed.filters) {
    let ok;
    if (f.key === "has") ok = hasFlag(e, f.value);
    else if (f.key === "id") ok = e.id.toLowerCase().includes(f.value);
    else {
      const facet = FACET_BY_KEY[f.key];
      const vals = facet.get(e);
      ok = vals.some((v) => {
        const raw = String(v).toLowerCase();
        const shown = facet.fmt ? String(facet.fmt(v)).toLowerCase() : raw;
        return raw.includes(f.value) || shown.includes(f.value);
      });
    }
    if (ok === f.neg) return false;
  }
  return true;
}

function facetFails(e) {
  const fails = [];
  for (const f of FACETS) {
    const sel = S.facetSel[f.key];
    if (!sel || !sel.size) continue;
    if (!f.get(e).some((v) => sel.has(v))) fails.push(f.key);
  }
  return fails;
}

function computeVisible() {
  S.parsed = parseQuery(S.query);
  const counts = Object.fromEntries(FACETS.map((f) => [f.key, new Map()]));
  const visible = [];
  const wantsDeleted = S.showDeleted || S.facetSel.kind?.has("deleted") || S.parsed.filters.some((f) => f.key === "kind" && f.value.includes("delet"));
  // In conversation mode a facet value counts the conversations that contain a matching row.
  const byConv = S.mode === "conv";
  for (const e of S.examples) {
    if (e.deleted && !wantsDeleted) continue;
    if (!matchesQuery(e, S.parsed)) continue;
    const fails = facetFails(e);
    if (fails.length === 0) visible.push(e);
    for (const f of FACETS) {
      if (fails.length === 0 || (fails.length === 1 && fails[0] === f.key)) {
        const m = counts[f.key];
        for (const v of new Set(f.get(e))) {
          if (!byConv) { m.set(v, (m.get(v) || 0) + 1); continue; }
          if (!m.has(v)) m.set(v, new Set());
          m.get(v).add(e.group);
        }
      }
    }
  }
  if (byConv) for (const m of Object.values(counts)) for (const [v, groups] of m) m.set(v, groups.size);
  sortExamples(visible);
  S.visible = visible;
  S.visibleSet = new Set(visible.map((e) => e.id));
  S.facetCounts = counts;
  S.flatOrder = visible;
  // Conversations keep the position of their first matching row.
  const seen = new Set();
  S.convOrder = [];
  if (byConv) for (const e of visible) if (!seen.has(e.group)) { seen.add(e.group); S.convOrder.push(e.group); }
}

function sortExamples(list) {
  const idx = new Map(S.examples.map((e, i) => [e.id, i]));
  const sev = { error: 2, warning: 1, "": 0 };
  const cmp = {
    file: (a, b) => idx.get(a.id) - idx.get(b.id),
    question: (a, b) => a._q.localeCompare(b._q) || STAGES.indexOf(a.schema) - STAGES.indexOf(b.schema),
    problem: (a, b) => problemName(a.tags.problem_id).localeCompare(problemName(b.tags.problem_id)) || STAGES.indexOf(a.schema) - STAGES.indexOf(b.schema),
    issues: (a, b) => sev[b._issue] - sev[a._issue] || idx.get(a.id) - idx.get(b.id),
    updated: (a, b) => (b.updated_at || "").localeCompare(a.updated_at || "") || idx.get(a.id) - idx.get(b.id),
    output: (a, b) => b._outLen - a._outLen,
  }[S.sort] || ((a, b) => idx.get(a.id) - idx.get(b.id));
  list.sort(cmp);
}

// ------------------------------------------------------------------ rendering: facets
function renderFacets() {
  const host = $("#facet-groups");
  const focusKey = document.activeElement?.dataset?.ffilter;
  const openState = {};
  $$(".facet", host).forEach((d) => (openState[d.dataset.key] = d.open));
  const defaults = new Set(["adapter", "split", "schema", "outcome", "conv", "progress", "problem", "review", "issues", "kind"]);
  host.innerHTML = FACETS.map((f) => {
    const counts = S.facetCounts[f.key];
    const sel = S.facetSel[f.key] || new Set();
    let values = [...new Set([...counts.keys(), ...sel])];
    if (f.order) values.sort((a, b) => (f.order.indexOf(a) + 99 * (f.order.indexOf(a) < 0)) - (f.order.indexOf(b) + 99 * (f.order.indexOf(b) < 0)));
    else if (f.key === "schema") values.sort((a, b) => STAGES.indexOf(a) - STAGES.indexOf(b));
    else values.sort((a, b) => (counts.get(b) || 0) - (counts.get(a) || 0) || String(a).localeCompare(String(b)));
    if (!values.length) return "";
    const totalValues = values.length;
    const filterText = norm(S.facetFilter[f.key] || "");
    if (filterText) values = values.filter((v) => norm(f.fmt ? f.fmt(v) : v).includes(filterText) || sel.has(v));
    const limit = 8;
    const showAll = S.facetShowAll[f.key] || filterText;
    const shownValues = showAll ? values : values.slice(0, limit);
    const open = openState[f.key] ?? (defaults.has(f.key) || sel.size > 0);
    const valueHtml = (v) => {
      const c = counts.get(v) || 0;
      const label = f.fmt ? f.fmt(v) : v;
      const unsupported = f.key === "problem" && v !== NONE && S.problems.get(v) && S.problems.get(v).status !== "validated";
      const dot = f.dot && STAGES.includes(v) ? `<span class="chip stage-${v}" style="padding:0;border:0;background:none"><span class="dot"></span></span>` : "";
      const reviewIc = f.key === "review" ? reviewIcon(v) : "";
      return `<label class="fv${c ? "" : " zero"}${unsupported ? " unsupported" : ""}" title="${esc(label)}${unsupported ? " — no validated backend" : ""}">
        <input type="checkbox" data-facet="${f.key}" value="${esc(v)}"${sel.has(v) ? " checked" : ""}>
        ${dot}${reviewIc}<span class="fv-label">${esc(label)}</span><span class="fv-count">${c.toLocaleString()}</span></label>`;
    };
    let body;
    if (f.grouped && !filterText) {
      const byCat = new Map();
      for (const v of shownValues) {
        const cat = v === NONE ? "zz" : S.problems.get(v)?.category || "other";
        if (!byCat.has(cat)) byCat.set(cat, []);
        byCat.get(cat).push(v);
      }
      body = [...byCat.entries()].sort((a, b) => a[0].localeCompare(b[0]))
        .map(([cat, vs]) => `<div class="facet-sub">${cat === "zz" ? "Untagged" : esc(categoryLabel(cat))}</div>${vs.map(valueHtml).join("")}`).join("");
    } else body = shownValues.map(valueHtml).join("");
    const more = values.length > limit && !filterText
      ? `<button class="link-btn fv-more" data-more="${f.key}">${showAll ? "Show fewer" : `Show all ${values.length}`}</button>` : "";
    const search = f.search && (totalValues > limit || filterText) ? `<input class="facet-filter" data-ffilter="${f.key}" placeholder="Filter ${esc(f.label.toLowerCase())}…" value="${esc(S.facetFilter[f.key] || "")}">` : "";
    return `<details class="facet" data-key="${f.key}"${open ? " open" : ""}>
      <summary>${esc(f.label)}${sel.size ? '<span class="active-dot" title="Active filter"></span>' : ""}</summary>
      ${search}<div class="facet-values">${body}</div>${more}</details>`;
  }).join("");
  if (focusKey) {
    const el = host.querySelector(`[data-ffilter="${focusKey}"]`);
    if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
  }
}

function reviewIcon(state) {
  const r = REVIEW[state] || REVIEW.unreviewed;
  return `<span class="ic ${r.cls}" aria-hidden="true">${r.icon}</span>`;
}
function reviewBadge(state, withLabel = true) {
  const r = REVIEW[state] || REVIEW.unreviewed;
  return `<span class="status-badge" title="${r.label}">${reviewIcon(state)}${withLabel ? r.label : ""}</span>`;
}
function stageChip(schema, count = 1) {
  return `<span class="chip stage-${esc(schema)}" title="${esc(STAGE_HELP[schema] || "")}"><span class="dot"></span>${esc(STAGE_LABEL[schema] || schema || "?")}${count > 1 ? ` ×${count}` : ""}</span>`;
}
function issueBadge(e) {
  if (!e._issue) return "";
  const n = e.issues.filter((i) => i.level === e._issue).length;
  return e._issue === "error"
    ? `<span class="status-badge" title="Validation errors"><span class="ic critical">✕</span>${n} error${n > 1 ? "s" : ""}</span>`
    : `<span class="status-badge" title="Warnings"><span class="ic warning">!</span>${n} warning${n > 1 ? "s" : ""}</span>`;
}

// ------------------------------------------------------------------ rendering: list
function rowHtml(e) {
  const cur = e.id === S.currentId;
  const kindChip = e.deleted ? '<span class="chip kind-deleted">deleted</span>' : e.kind !== "original" ? `<span class="chip kind-${e.kind}">${e.kind}</span>` : "";
  const pills = [];
  if (e.tags.problem_id) pills.push(`<span class="tag-pill${e.manual_tags.problem_id ? " manual" : ""}" title="Problem">${esc(problemName(e.tags.problem_id))}</span>`);
  if (e.tags.operation_id) pills.push(`<span class="tag-pill${e.manual_tags.operation_id ? " manual" : ""}" title="Operation">${esc(e.tags.operation_id)}</span>`);
  if (e.tags.backend) pills.push(`<span class="tag-pill${e.manual_tags.backend ? " manual" : ""}" title="Implementation">⚙ ${esc(e.tags.backend)}</span>`);
  for (const l of e.labels.slice(0, 3)) pills.push(`<span class="label-chip ro">${esc(l)}</span>`);
  return `<div class="row${cur ? " current" : ""}${e.deleted ? " deleted" : ""}" data-id="${esc(e.id)}">
    <input type="checkbox" data-sel="${esc(e.id)}"${S.selected.has(e.id) ? " checked" : ""} aria-label="Select">
    <div>
      <div class="row-top">${stageChip(e.schema)}<span class="chip split ${e.split}">${esc(e.split)}</span>${kindChip}
        ${e._clarify ? '<span class="chip" title="Expected output asks the user for more information">asks for info</span>' : ""}
        ${e.turns.length ? `<span class="chip" title="Earlier conversation turns">↩ ${e.turns.length} turns</span>` : ""}
        ${e.review !== "unreviewed" ? reviewBadge(e.review) : ""}${issueBadge(e)}</div>
      <div class="row-q">${esc(e._q) || '<span class="muted">(empty question)</span>'}</div>
      <div class="row-meta">${pills.join("")}</div>
    </div></div>`;
}

function stageSummary(steps) {
  const counts = new Map();
  for (const e of steps) counts.set(e.schema, (counts.get(e.schema) || 0) + 1);
  return [...counts].map(([s, n]) => stageChip(s, n)).join("");
}
function reviewSummary(steps) {
  const n = steps.length;
  const cnt = Object.fromEntries(REVIEW_ORDER.map((r) => [r, steps.filter((e) => e.review === r).length]));
  if (!n || cnt.unreviewed === n) return "";
  for (const r of REVIEW_ORDER) if (cnt[r] === n) return reviewBadge(r);
  const worst = cnt.rejected ? "rejected" : cnt.needs_fix ? "needs_fix" : "approved";
  const detail = REVIEW_ORDER.filter((r) => cnt[r]).map((r) => `${cnt[r]} ${REVIEW[r].label.toLowerCase()}`).join(" · ");
  return `<span class="status-badge" title="${esc(detail)}">${reviewIcon(worst)}${n - cnt.unreviewed}/${n} reviewed</span>`;
}
function issueSummary(steps) {
  const err = steps.filter((e) => e._issue === "error").length;
  const warn = steps.filter((e) => e._issue === "warning").length;
  if (err) return `<span class="status-badge" title="Steps with validation errors"><span class="ic critical">✕</span>${plural(err, "step")} with errors</span>`;
  if (warn) return `<span class="status-badge" title="Steps with warnings"><span class="ic warning">!</span>${plural(warn, "step")} with warnings</span>`;
  return "";
}
// Rows of the conversation that a checkbox or bulk action covers.
const convIds = (key) => convSteps(S.convs.get(key)).map((e) => e.id);

function convRowHtml(key) {
  const c = S.convs.get(key);
  const steps = convSteps(c);
  const ids = steps.map((e) => e.id);
  const nSel = ids.filter((id) => S.selected.has(id)).length;
  const t = c.tagged.tags;
  const m = c.tagged.manual_tags;
  const pills = [];
  if (t.problem_id) pills.push(`<span class="tag-pill${m.problem_id ? " manual" : ""}" title="Problem">${esc(problemName(t.problem_id))}</span>`);
  if (t.operation_id) pills.push(`<span class="tag-pill${m.operation_id ? " manual" : ""}" title="Operation">${esc(t.operation_id)}</span>`);
  if (t.backend) pills.push(`<span class="tag-pill${m.backend ? " manual" : ""}" title="Implementation">⚙ ${esc(t.backend)}</span>`);
  if (c.lineage) pills.push(`<span class="tag-pill" title="Graph source">${esc(c.lineage)}</span>`);
  const matched = steps.filter((e) => S.visibleSet.has(e.id)).length;
  const changed = steps.filter((e) => e.kind !== "original" || e.deleted).length;
  return `<div class="row conv${key === S.convKey ? " current" : ""}${c.live.length ? "" : " deleted"}" data-conv="${esc(key)}">
    <input type="checkbox" data-csel="${esc(key)}"${nSel && nSel === ids.length ? " checked" : ""}${nSel && nSel < ids.length ? " data-partial" : ""} aria-label="Select conversation">
    <div>
      <div class="row-top"><span class="chip split ${c.split}">${esc(c.split)}</span>${stageSummary(steps)}
        ${filtersActive() && matched < steps.length ? `<span class="chip" title="Steps that match the current filters">${matched} of ${steps.length} match</span>` : ""}
        ${changed ? `<span class="chip kind-edited" title="Steps with pending changes">${changed} changed</span>` : ""}
        ${reviewSummary(steps.filter((e) => !e.deleted))}${issueSummary(steps.filter((e) => !e.deleted))}</div>
      <div class="row-q">${esc(c.question) || '<span class="muted">(empty question)</span>'}</div>
      <div class="row-meta">${pills.join("")}</div>
    </div></div>`;
}

// Row ids covered by "select all" in the current mode.
const selectableIds = () => (S.mode === "conv" ? S.convOrder.flatMap(convIds) : S.visible.map((e) => e.id));

let listObserver;
function renderList(keepScroll = true) {
  const list = $("#list");
  const top = list.scrollTop;
  const conv = S.mode === "conv";
  const items = conv ? S.convOrder : S.visible;
  const target = keepScroll ? Math.max(S.rendered, PAGE) : PAGE;
  S.rendered = Math.min(items.length, target);
  if (!S.examples.length) {
    list.innerHTML = `<div class="empty-list">This dataset has no conversations yet.<br><button class="btn primary small" data-empty-add>＋ Add conversation</button></div>`;
  } else if (!items.length) {
    list.innerHTML = `<div class="empty-list">No ${conv ? "conversations" : "examples"} match.<br><button class="link-btn" id="empty-clear">Clear filters and search</button></div>`;
  } else {
    const html = items.slice(0, S.rendered).map(conv ? convRowHtml : rowHtml).join("");
    list.innerHTML = html + (S.rendered < items.length ? `<div class="more-sentinel" id="more-sentinel">Showing ${S.rendered} of ${items.length}…</div>` : "");
    $$("input[data-partial]", list).forEach((cb) => (cb.indeterminate = true));
  }
  if (keepScroll) list.scrollTop = top;
  $("#result-count").textContent = conv
    ? `${plural(S.convOrder.length, "conversation")} · ${plural(S.visible.length, "row")}`
    : plural(S.visible.length, "example");
  syncSelectAll();
  listObserver?.disconnect();
  const sentinel = $("#more-sentinel");
  if (sentinel) {
    listObserver = new IntersectionObserver((ents) => {
      if (ents.some((x) => x.isIntersecting)) { S.rendered += PAGE; renderList(true); }
    }, { root: list, rootMargin: "300px" });
    listObserver.observe(sentinel);
  }
  renderBulkbar();
}

function syncSelectAll() {
  const sa = $("#select-all");
  const ids = selectableIds();
  const nSel = ids.filter((id) => S.selected.has(id)).length;
  sa.checked = nSel > 0 && nSel === ids.length;
  sa.indeterminate = nSel > 0 && nSel < ids.length;
}

function renderBulkbar() {
  const n = S.selected.size;
  $("#bulkbar").hidden = n === 0;
  if (S.mode === "conv") {
    const convs = new Set([...S.selected].map((id) => S.byId.get(id)?.group));
    $("#bulk-count").textContent = `${plural(convs.size, "conversation")} (${plural(n, "row")}) selected`;
  } else $("#bulk-count").textContent = `${n} selected`;
}

function renderStatus() {
  const ex = S.examples.filter((e) => !e.deleted);
  const train = ex.filter((e) => e.split === "train").length;
  const changes = S.examples.filter((e) => e.kind !== "original" || e.deleted).length;
  const d = S.dataset || {};
  $("#status-strip").innerHTML = [
    `<span title="${esc(d.description || "")}"><b>${esc(d.name || d.path || "")}</b> <span class="muted">${esc(d.path || "")} (${esc(d.layout || "")})</span></span>`,
    `<span>${new Set(ex.map((e) => e.group)).size.toLocaleString()} conversations · ${ex.length.toLocaleString()} training rows (${train.toLocaleString()} train · ${(ex.length - train).toLocaleString()} validation)</span>`,
    `<span>${new Set(ex.map((e) => norm(e._q))).size.toLocaleString()} distinct questions</span>`,
    `<span title="${esc(S.meta.strict_schema_error || "")}">Schema check: <b>${S.meta.strict_schema ? "strict (agent Pydantic models)" : "structural only"}</b></span>`,
    `<span>${changes ? `<b>${changes}</b> pending change${changes > 1 ? "s" : ""} (saved; written on export)` : "No changes"}</span>`,
  ].join('<span class="sep">|</span>');
  const pill = $("#changes-count");
  pill.hidden = !changes;
  pill.textContent = changes;
  // A dataset made in the studio is all journal rows: keep its picker count live.
  const opt = d.layout === "studio" && $(`#dataset-select option[value="${CSS.escape(d.key)}"]`);
  if (opt) opt.textContent = `${d.name || d.path} · ${plural(ex.length, "row")}`;
}

// ------------------------------------------------------------------ rendering: detail
function current() { return S.byId.get(S.currentId); }

function renderDetail() {
  const host = $("#detail");
  const e = current();
  if (!e && !S.examples.length) {
    host.innerHTML = `<div class="empty-detail"><div class="empty-art" aria-hidden="true"></div>
      <p>This dataset is empty.</p><p class="muted">Add a conversation: the question, then each Qwen step in chat order.</p>
      <p><button class="btn primary" data-empty-add>＋ Add conversation</button></p></div>`;
    return;
  }
  if (!e) {
    host.innerHTML = `<div class="empty-detail"><div class="empty-art" aria-hidden="true"></div>
      <p>Select ${S.mode === "conv" ? "a conversation to see every step (understanding, planning, answers) in one thread" : "an example to see the conversation, expected output and tags"}.</p>
      <p class="muted">Use <kbd>j</kbd>/<kbd>k</kbd> to move, <kbd>e</kbd> to edit the output, <kbd>?</kbd> for all shortcuts.</p></div>`;
    return;
  }
  if (S.mode === "conv" && !S.rowView) { renderConvDetail(host); return; }
  const inConv = S.mode === "conv";
  const convList = inConv ? convSteps(currentConv()) : null;
  const pos = inConv ? convList.findIndex((x) => x.id === e.id) : S.flatOrder.findIndex((x) => x.id === e.id);
  const posText = inConv ? `step ${pos + 1} of ${convList.length}` : pos >= 0 ? `${pos + 1} / ${S.flatOrder.length}` : "hidden by filters";
  const tabs = [["conversation", "Conversation"], ["context", "Model context"]];
  if (e.kind === "edited" || e.kind === "clone") tabs.push(["diff", "Diff vs original"]);
  tabs.push(["history", "History"]);
  if (!tabs.some(([k]) => k === S.tab)) S.tab = "conversation";
  const kindChip = e.deleted ? '<span class="chip kind-deleted">deleted</span>' : e.kind !== "original" ? `<span class="chip kind-${e.kind}">${e.kind}</span>` : "";
  host.innerHTML = `
    <div class="detail-head">
      <div class="detail-title">
        ${inConv ? '<button class="btn small" data-act="to-conv" title="Back to the whole conversation (Esc)">← Conversation</button>'
          : '<button class="icon-btn only-mobile" data-act="back" aria-label="Back to list">←</button>'}
        ${stageChip(e.schema)}<span class="chip split ${e.split}">${esc(e.split)}</span>
        <span class="chip">${e.adapter === "analyst" ? "Analyst" : "Planner"}</span>
        ${e.variant && !HIDDEN_VARIANTS.includes(e.variant) ? `<span class="chip" title="Variant">${esc(String(e.variant).replace(/_/g, " "))}</span>` : ""}${kindChip}
        <div class="detail-actions">
          <span class="muted" style="font-size:12px">${posText}</span>
          <button class="icon-btn" data-act="prev" title="${inConv ? "Previous step ([)" : "Previous (k)"}">↑</button>
          <button class="icon-btn" data-act="next" title="${inConv ? "Next step (])" : "Next (j)"}">↓</button>
          ${e.kind === "edited" || e.kind === "annotated" ? '<button class="btn small" data-act="revert" title="Undo all changes to this example">Revert</button>' : ""}
          ${e.kind === "new" || e.kind === "clone" ? '<button class="btn small danger-ghost" data-act="discard" title="Remove this added example permanently">Discard</button>' : ""}
          ${e.deleted ? '<button class="btn small" data-act="restore">Restore</button>' : '<button class="btn small danger-ghost" data-act="delete" title="Delete (Del)">Delete</button>'}
        </div>
      </div>
      <div class="detail-id"><span title="${esc(e.id)}">${esc(e.id)}</span><button class="link-btn" data-act="copy-id">copy</button>
        ${e.lineage ? `<span>· ${esc(e.lineage)}</span>` : ""}${e.teacher ? `<span>· teacher ${esc(e.teacher)}</span>` : ""}</div>
      <div class="tabs" role="tablist">${tabs.map(([k, l]) => `<button role="tab" data-tab="${k}" class="${S.tab === k ? "active" : ""}">${l}</button>`).join("")}</div>
    </div>
    <div class="detail-body" id="detail-body"></div>`;
  const body = $("#detail-body");
  if (S.tab === "conversation") body.innerHTML = conversationHtml(e);
  else if (S.tab === "context") loadContext(e, body);
  else if (S.tab === "diff") loadDiff(e, body);
  else if (S.tab === "history") loadHistory(e, body);
  if (S.editing?.kind === "output") initOutputEditor();
}

function issuesHtml(issues) {
  if (!issues?.length) return "";
  const lv = { error: ["critical", "✕", "Error"], warning: ["warning", "!", "Warning"], info: ["info", "i", "Note"] };
  return `<div class="issues">${issues.map((i) => {
    const [cls, ic, name] = lv[i.level] || lv.info;
    return `<div class="issue ${i.level === "info" ? "info" : ""}"><span class="ic ${cls}" aria-hidden="true">${ic}</span><div class="msg"><span class="lvl">${name}</span>${esc(i.message)}</div></div>`;
  }).join("")}</div>`;
}

function problemOptions(selected, auto) {
  const cats = new Map();
  for (const p of S.problems.values()) {
    if (!cats.has(p.category)) cats.set(p.category, []);
    cats.get(p.category).push(p);
  }
  let html = `<option value="">${auto ? `Auto: ${esc(problemName(auto))}` : "Auto: (none)"}</option>`;
  for (const [cat, ps] of [...cats.entries()].sort()) {
    html += `<optgroup label="${esc(categoryLabel(cat))}">` + ps.sort((a, b) => a.name.localeCompare(b.name)).map((p) =>
      `<option value="${esc(p.id)}"${p.id === selected ? " selected" : ""}>${esc(p.name)}${p.status !== "validated" ? " — no validated backend" : ""}</option>`).join("") + "</optgroup>";
  }
  if (selected && !S.problems.has(selected)) html += `<option value="${esc(selected)}" selected>${esc(selected)}</option>`;
  return html;
}
function operationOptions(selected, auto, problem) {
  const mine = opsOfProblem(problem);
  const all = [...S.operations.keys()].sort();
  let html = `<option value="">${auto ? `Auto: ${esc(auto)}` : "Auto: (none)"}</option>`;
  const opt = (o) => `<option value="${esc(o)}"${o === selected ? " selected" : ""}>${esc(o)}</option>`;
  if (mine.length) html += `<optgroup label="For this problem">${mine.map(opt).join("")}</optgroup>`;
  html += `<optgroup label="All operations">${all.filter((o) => !mine.includes(o)).map(opt).join("")}</optgroup>`;
  if (selected && !S.operations.has(selected)) html += `<option value="${esc(selected)}" selected>${esc(selected)}</option>`;
  return html;
}
function backendOptions(selected, auto, op) {
  const bs = backendsOf(op);
  let html = `<option value="">${auto ? `Auto: ${esc(auto)}` : "Auto: (none)"}</option>`;
  html += bs.map((b) => `<option value="${esc(b.id)}"${b.id === selected ? " selected" : ""}>${esc(b.name)}${b.capabilities?.length ? " · " + esc(b.capabilities.join(", ").replace(/_/g, " ")) : ""}</option>`).join("");
  if (selected && !bs.some((b) => b.id === selected)) html += `<option value="${esc(selected)}" selected>${esc(selected)}</option>`;
  return html;
}

function tagCardHtml(e) {
  const a = e.auto_tags || {};
  const m = e.manual_tags || {};
  const refs = (a.reference_backends || []).join(", ");
  const autoNote = (k, v, extra = "") => `<span class="tf-auto" title="${esc(extra)}">${m[k] ? `manual · auto was ${esc(v || "none")}` : `auto-detected${extra ? " · " + esc(extra) : ""}`}</span>`;
  return `<div class="card"><div class="card-head">Tags <span class="muted" style="font-weight:400">— what this question represents</span><span class="spacer"></span>
      ${Object.keys(m).length ? '<button class="link-btn" data-act="reset-tags">Reset to auto</button>' : ""}</div>
    <div class="card-body">
      <div class="tag-grid">
        <label class="tag-field"><span class="tf-label">Problem ${m.problem_id ? '<span class="tag-pill manual">manual</span>' : ""}</span>
          <select data-tag="problem_id">${problemOptions(m.problem_id, a.problem_id)}</select>${autoNote("problem_id", a.problem_id && problemName(a.problem_id))}</label>
        <label class="tag-field"><span class="tf-label">Operation ${m.operation_id ? '<span class="tag-pill manual">manual</span>' : ""}</span>
          <select data-tag="operation_id">${operationOptions(m.operation_id, a.operation_id, e.tags.problem_id)}</select>${autoNote("operation_id", a.operation_id)}</label>
        <label class="tag-field"><span class="tf-label">Implementation ${m.backend ? '<span class="tag-pill manual">manual</span>' : ""}</span>
          <select data-tag="backend">${backendOptions(m.backend, a.backend, e.tags.operation_id)}</select>
          ${autoNote("backend", a.backend, refs ? `reference run used ${refs}` : a.planned_backend ? `plan says ${a.planned_backend}` : "")}</label>
      </div>
      <div class="tag-row2">
        <div><div class="tf-label" style="font-size:11.5px;color:var(--text-secondary);margin-bottom:3px">Review</div>
          <div class="review-seg">${REVIEW_ORDER.map((r, i) => `<button data-review="${r}" class="${e.review === r ? "on" : ""}" title="${REVIEW[r].label} (${i + 1})">${reviewIcon(r)}${REVIEW[r].label}</button>`).join("")}</div></div>
        <div style="flex:1;min-width:220px"><div class="tf-label" style="font-size:11.5px;color:var(--text-secondary);margin-bottom:3px">Labels</div>
          <div class="labels-box">${e.labels.map((l) => `<span class="label-chip">${esc(l)}<button data-unlabel="${esc(l)}" aria-label="Remove label ${esc(l)}">×</button></span>`).join("")}
            <input id="label-input" placeholder="+ add label" list="label-options"></div></div>
      </div>
      <div class="notes-box"><textarea id="notes-input" rows="1" placeholder="Notes for reviewers (saved when you leave the field)">${esc(e.notes)}</textarea></div>
    </div></div>`;
}

function turnBubble(t) {
  const who = t.role === "assistant" ? "GraphMine" : "User";
  return `<div class="turn"><div class="avatar ${t.role}">${t.role === "assistant" ? "G" : "U"}</div>
    <div class="bubble context-turn"><div class="bubble-head">${who} · earlier turn${t.status ? ` · <span class="tag-pill">${esc(t.status)}</span>` : ""}<span class="spacer"></span></div>
    <div class="bubble-text">${esc(t.text)}</div></div></div>`;
}

function conversationHtml(e) {
  const ed = S.editing?.id === e.id ? S.editing : null;
  const editingPrompts = ed?.kind === "prompts";
  const editingOutput = ed?.kind === "output";
  const conv = S.convs.get(e.group);
  const siblings = conv ? conv.live : [];
  const sibHtml = siblings.length > 1 ? `<div class="siblings"><span class="muted">${S.mode === "conv" ? "Steps in this conversation:" : "Same conversation:"}</span>${siblings
    .map((x) => `<button class="chip stage-${esc(x.schema)}${x.id === e.id ? " current" : ""}" data-goto="${esc(x.id)}" title="${esc(x.id)}"><span class="dot"></span>${esc(STAGE_LABEL[x.schema] || x.schema)}${x.variant && !HIDDEN_VARIANTS.includes(x.variant) ? ` · ${esc(x.variant.replace(/_/g, " "))}` : ""}${x.kind === "clone" ? " · clone" : ""}</button>`).join("")}
    ${S.mode === "rows" ? '<button class="link-btn" data-act="open-conv">Open as one conversation →</button>' : ""}</div>` : "";

  const turnsBlock = e.turns.map(turnBubble).join("");
  const promptBody = editingPrompts
    ? e.prompts.map((p) => `<div class="prompt-label">${esc(p.label)}</div><textarea data-prompt="${esc(p.path)}" rows="3">${esc(ed.draft[p.path] ?? p.value)}</textarea>`).join("")
      + `<div class="editor-actions"><span class="state muted">Exact copies of the old text elsewhere in the hidden payload are updated too on export.</span>
          <button class="btn small ghost" data-act="cancel-edit">Cancel</button><button class="btn small primary" data-act="save-prompts">Save question</button></div>`
    : e.prompts.map((p) => `${e.prompts.length > 1 ? `<div class="prompt-label">${esc(p.label)}</div>` : ""}<div class="bubble-text">${esc(p.value)}</div>`).join("");

  let outputBody;
  if (editingOutput) {
    outputBody = `<textarea class="json-edit" id="output-editor" spellcheck="false">${esc(ed.text)}</textarea>
      <div class="editor-actions"><span class="state" id="editor-state"></span>
        <button class="btn small ghost" data-act="format-json">Format</button>
        <button class="btn small ghost" data-act="cancel-edit">Cancel</button>
        <button class="btn small primary" data-act="save-output" id="save-output">Save output</button></div>
      <div id="editor-issues" class="issues" style="margin-top:8px"></div>`;
  } else {
    outputBody = S.outputMode === "tree" ? `<div class="json-tree">${jsonTree(e.output)}</div>` : `<pre class="json-pretty">${highlightJson(e.output)}</pre>`;
  }

  return `
    ${issuesHtml(e.issues)}
    ${tagCardHtml(e)}
    <div class="card"><div class="card-head">Conversation
        <span class="muted" style="font-weight:400">${e.turns.length ? `${e.turns.length} earlier turn${e.turns.length > 1 ? "s" : ""} (context, not trained; other steps share them, so edit them in the conversation view)` : "single turn"}</span></div>
      <div class="card-body thread">
        ${turnsBlock}
        <div class="turn"><div class="avatar user">U</div><div class="bubble final-user">
          <div class="bubble-head">User · final message<span class="spacer"></span>${editingPrompts ? "" : '<button class="link-btn" data-act="edit-prompts">Edit (q)</button>'}</div>
          ${promptBody}</div></div>
        <div class="turn"><div class="avatar assistant">Q</div><div class="bubble target">
          <div class="bubble-head"><span class="target-tag">TRAINING TARGET</span> Expected Qwen output · ${esc(e.schema || "")}
            <span class="spacer"></span>
            ${editingOutput ? "" : `<span class="seg"><button data-omode="tree" class="${S.outputMode === "tree" ? "on" : ""}">Tree</button><button data-omode="pretty" class="${S.outputMode === "pretty" ? "on" : ""}">JSON</button></span>
            <button class="link-btn" data-act="copy-output">copy</button><button class="btn small" data-act="edit-output">Edit (e)</button>`}</div>
          ${outputBody}</div></div>
      </div></div>
    ${sibHtml}`;
}

// ---------- conversation view (all steps of one case in one thread)
function renderConvDetail(host) {
  const c = currentConv();
  const steps = convSteps(c);
  const pos = S.convOrder.indexOf(c.key);
  const teachers = [...new Set(steps.map((e) => e.teacher).filter(Boolean))];
  // Only steps written here can be discarded for good; anything else is soft-deleted.
  const allAdded = c.live.length && c.live.every((e) => e.kind === "new" || e.kind === "clone");
  const removeBtn = !c.live.length ? '<button class="btn small" data-act="conv-restore">Restore conversation</button>'
    : allAdded ? '<button class="btn small danger-ghost" data-act="conv-discard" title="Remove every step permanently">Discard conversation</button>'
      : '<button class="btn small danger-ghost" data-act="conv-delete" title="Delete every step (restorable until export)">Delete conversation</button>';
  host.innerHTML = `
    <div class="detail-head no-tabs">
      <div class="detail-title">
        <button class="icon-btn only-mobile" data-act="back" aria-label="Back to list">←</button>
        <span class="chip split ${c.split}">${esc(c.split)}</span>
        <span class="chip" title="Each step is exported as its own training row">${plural(steps.length, "training row")}</span>
        <span class="chip progress-${esc(c.progress)}" title="How far this conversation got">${esc(PROGRESS[c.progress])}</span>
        ${c.lineage ? `<span class="chip" title="Graph source">${esc(c.lineage)}</span>` : ""}
        <div class="detail-actions">
          <span class="muted" style="font-size:12px">${pos >= 0 ? `${pos + 1} / ${S.convOrder.length}` : "hidden by filters"}</span>
          <button class="icon-btn" data-act="prev" title="Previous conversation (k)">↑</button>
          <button class="icon-btn" data-act="next" title="Next conversation (j)">↓</button>
          <button class="btn small" data-act="duplicate" title="Copy every step into a new conversation, keeping their model context (c)">Duplicate</button>
          <button class="btn small" data-act="add-to-conv" title="Add missing steps or follow-up messages">+ Add steps</button>
          ${removeBtn}
        </div>
      </div>
      <div class="detail-id"><span title="${esc(c.key)}">${esc(c.key)}</span><button class="link-btn" data-act="copy-conv">copy</button>
        ${teachers.length ? `<span>· teacher ${esc(teachers.join(", "))}</span>` : ""}</div>
    </div>
    <div class="detail-body" id="detail-body">${replayCardHtml(c)}${convTagCardHtml(c, steps)}${convThreadHtml(c, steps)}</div>`;
  if (S.editing?.kind === "output") initOutputEditor();
  if (S.editing?.kind === "next") initNextEditor();
  loadConversationContext(c.key);
}

// The replay card: which graph and domain the agent runs on, whether the model
// inputs are current, and what the last build reported.
function replayCardHtml(c) {
  const engine = S.meta?.engine || {};
  const sum = S.conversations[c.key];
  if (!engine.available) {
    return c.live.some((e) => e.kind === "new") ? `<div class="callout">Steps written here get their model input from the GraphMine agent, which this studio cannot load (${esc(engine.error || "start it with the repository's .venv")}). They export to <code>needs-context.jsonl</code>.</div>` : "";
  }
  const settings = sum?.settings;
  const caseNote = sum?.case && !settings ? " (the case's own graph)" : "";
  if (!settings && !sum?.case) {
    if (!c.live.some((e) => e.kind === "new")) return "";
    return `<div class="card replay"><div class="card-head">Model inputs<span class="spacer"></span></div>
      <div class="card-body"><p class="muted" style="margin:0 0 8px">This conversation has no graph yet. With a graph and domain, the agent replays it: every step gets the model input production would send, and GraphMine computes the facts for the analyst answer.</p>
      <button class="btn small primary" data-act="choose-graph">Choose graph and domain…</button></div></div>`;
  }
  const building = S.building?.group === c.key;
  const status = building ? (S.building.run ? "Running GraphMine…" : "Building…")
    : !sum?.built ? "not built yet" : sum.fresh ? "up to date" : "out of date: the conversation changed after the last build";
  const ctx = S.convContext.get(c.key);
  const events = (ctx?.events || []).filter((e) => e.level !== "info" || /GraphMine ran/.test(e.message));
  const g = settings?.graph;
  const domain = settings ? (S.meta.catalog.domains.find((d) => d.id === settings.domain_id)?.name || settings.domain_id) : "";
  const canRun = c.progress === "ready_to_run" || sum?.needs_run;
  return `<div class="card replay"><div class="card-head">Model inputs <span class="muted" style="font-weight:400">· ${esc(status)}${sum?.built_at && !building ? ` · built ${esc(new Date(sum.built_at).toLocaleString())}` : ""}</span><span class="spacer"></span>
      <button class="btn small" data-act="build" ${building ? "disabled" : ""} title="Replay the conversation through the agent (does not run GraphMine)">${sum?.built ? "Rebuild" : "Build"}</button>
      ${canRun ? `<button class="btn small primary" data-act="run" ${building ? "disabled" : ""} title="Run the ready plan with GraphMine, then rebuild">▶ Run GraphMine</button>` : ""}</div>
    <div class="card-body">
      <div class="replay-line">${g ? `<span class="tag-pill" title="Graph">⌗ ${esc(g.name || g.id)}${g.vertices != null ? ` · ${g.vertices} records · ${g.edges} links` : ""}</span>` : `<span class="tag-pill">⌗ case graph${esc(caseNote)}</span>`}
        ${domain ? `<span class="tag-pill" title="Domain">${esc(domain)}</span>` : ""}
        ${settings && sum?.case !== true ? '<button class="link-btn" data-act="choose-graph">change</button>' : ""}
        ${ctx?.facts?.length ? `<span class="muted">· ${plural(ctx.facts.length, "computed fact")}</span>` : ""}</div>
      ${events.length ? `<ul class="replay-events">${events.map((e) => `<li class="ev-${esc(e.level)}"><b>${esc(e.stage)}</b>${e.branch && e.branch !== "main" ? ' <span class="muted">(follow-up)</span>' : ""}: ${esc(e.message)}</li>`).join("")}</ul>` : ""}
    </div></div>`;
}

function mixedNote(pool, key, fmt) {
  const counts = new Map();
  for (const e of pool) { const v = e.tags[key] || ""; counts.set(v, (counts.get(v) || 0) + 1); }
  if (counts.size <= 1) return { mixed: false, value: [...counts.keys()][0] || "" };
  const text = [...counts].map(([v, n]) => `${v ? fmt(v) : "none"} ×${n}`).join(" · ");
  return { mixed: true, value: "", text };
}
function convTagCardHtml(c, steps) {
  const pool = steps.filter((e) => !e.deleted).length ? steps.filter((e) => !e.deleted) : steps;
  const n = pool.length;
  // A manual tag is shown as selected only when every step carries the same one.
  const commonManual = (k) => { const vals = new Set(pool.map((e) => e.manual_tags[k] || "")); return vals.size === 1 ? [...vals][0] : ""; };
  const anyManual = (k) => pool.some((e) => e.manual_tags[k]);
  const field = (key, label, opts, fmt) => {
    const st = mixedNote(pool, key, fmt);
    const first = st.mixed ? "Auto: differs by step" : st.value ? `Auto: ${fmt(st.value)}` : "Auto: (none)";
    const html = opts.replace(/^<option value="">[^<]*<\/option>/, `<option value="">${esc(first)}</option>`);
    const note = st.mixed ? `<span class="tf-auto tf-mixed" title="${esc(st.text)}">differs: ${esc(st.text)}</span>`
      : `<span class="tf-auto">${anyManual(key) ? "manual" : "auto-detected"}${n > 1 ? ` · same on all ${n} steps` : ""}</span>`;
    return `<label class="tag-field"><span class="tf-label">${label} ${anyManual(key) ? '<span class="tag-pill manual">manual</span>' : ""}</span>
      <select data-ctag="${key}">${html}</select>${note}</label>`;
  };
  const op = commonManual("operation_id") || mixedNote(pool, "operation_id", String).value;
  const prob = commonManual("problem_id") || mixedNote(pool, "problem_id", String).value;
  const rev = Object.fromEntries(REVIEW_ORDER.map((r) => [r, pool.filter((e) => e.review === r).length]));
  const labels = new Map();
  for (const e of pool) for (const l of e.labels) labels.set(l, (labels.get(l) || 0) + 1);
  return `<div class="card"><div class="card-head">Tags &amp; review <span class="muted" style="font-weight:400">— applies to all ${plural(n, "step")} of this conversation</span><span class="spacer"></span>
      ${pool.some((e) => Object.keys(e.manual_tags).length) ? '<button class="link-btn" data-act="conv-reset-tags">Reset to auto</button>' : ""}</div>
    <div class="card-body">
      <div class="tag-grid">
        ${field("problem_id", "Problem", problemOptions(commonManual("problem_id"), null), problemName)}
        ${field("operation_id", "Operation", operationOptions(commonManual("operation_id"), null, prob), String)}
        ${field("backend", "Implementation", backendOptions(commonManual("backend"), null, op), String)}
      </div>
      <div class="tag-row2">
        <div><div class="tf-label" style="font-size:11.5px;color:var(--text-secondary);margin-bottom:3px">Review all steps
            <span class="muted">· ${REVIEW_ORDER.filter((r) => rev[r]).map((r) => `${rev[r]} ${REVIEW[r].label.toLowerCase()}`).join(" · ")}</span></div>
          <div class="review-seg">${REVIEW_ORDER.map((r) => `<button data-creview="${r}" class="${rev[r] === n ? "on" : ""}" title="Mark every step ${REVIEW[r].label.toLowerCase()}">${reviewIcon(r)}${REVIEW[r].label}</button>`).join("")}</div></div>
        <div style="flex:1;min-width:220px"><div class="tf-label" style="font-size:11.5px;color:var(--text-secondary);margin-bottom:3px">Labels</div>
          <div class="labels-box">${[...labels].map(([l, k]) => `<span class="label-chip" title="${k < n ? `On ${k} of ${n} steps` : "On every step"}">${esc(l)}${k < n ? ` <span class="muted">${k}/${n}</span>` : ""}<button data-cunlabel="${esc(l)}" aria-label="Remove label ${esc(l)} from every step">×</button></span>`).join("")}
            <input id="clabel-input" placeholder="+ add label to all" list="label-options"></div></div>
      </div>
    </div></div>`;
}

function reviewMini(e) {
  return `<span class="review-mini" role="group" aria-label="Review this step">${REVIEW_ORDER.map((r, i) =>
    `<button data-sreview="${r}" class="${e.review === r ? "on" : ""}" title="${REVIEW[r].label} (${i + 1} when focused)" aria-pressed="${e.review === r}">${reviewIcon(r)}</button>`).join("")}</span>`;
}

function outputEditorHtml() {
  return `<textarea class="json-edit" id="output-editor" spellcheck="false">${esc(S.editing.text)}</textarea>
    <div class="editor-actions"><span class="state" id="editor-state"></span>
      <button class="btn small ghost" data-act="format-json">Format</button>
      <button class="btn small ghost" data-act="cancel-edit">Cancel</button>
      <button class="btn small primary" data-act="save-output" id="save-output">Save output</button></div>
    <div id="editor-issues" class="issues" style="margin-top:8px"></div>`;
}

function stepHtml(e, n) {
  const ed = S.editing?.id === e.id ? S.editing : null;
  const variant = e.variant && !HIDDEN_VARIANTS.includes(e.variant) ? `<span class="chip" title="Variant">${esc(e.variant.replace(/_/g, " "))}</span>` : "";
  const kindChip = e.deleted ? '<span class="chip kind-deleted">deleted</span>' : e.kind !== "original" ? `<span class="chip kind-${e.kind}">${e.kind}</span>` : "";
  const body = ed?.kind === "output" ? outputEditorHtml()
    : S.outputMode === "tree" ? `<div class="json-tree">${jsonTree(e.output)}</div>` : `<pre class="json-pretty">${highlightJson(e.output)}</pre>`;
  const shownIssues = e.issues.filter((i) => i.level !== "info");
  const added = e.kind === "new" || e.kind === "clone";
  const remove = e.deleted ? '<button class="link-btn" data-sact="restore">Restore</button>'
    : added ? '<button class="link-btn danger" data-sact="discard" title="Remove this step permanently">Discard</button>'
      : '<button class="link-btn danger" data-sact="delete" title="Delete this step (restorable until export)">Delete</button>';
  const foot = ed?.kind === "output" ? "" : `<div class="step-foot">
      ${e.notes ? `<span class="step-note" title="${esc(e.notes)}">✎ ${esc(e.notes)}</span>` : ""}
      ${e.labels.map((l) => `<span class="label-chip ro">${esc(l)}</span>`).join("")}
      <span class="spacer"></span>
      <button class="link-btn" data-sact="copy">copy</button>
      <button class="link-btn" data-sact="edit">Edit output</button>
      ${remove}
      <button class="link-btn" data-sact="details" title="Model context, diff, history and notes for this step">Details →</button></div>`;
  return `<div class="turn step${e.id === S.currentId ? " focused" : ""}${e.deleted ? " deleted" : ""}" data-step="${esc(e.id)}">
    <div class="avatar assistant">Q</div>
    <div class="bubble target">
      <div class="bubble-head"><span class="step-no" title="Step ${n}">${n}</span>${stageChip(e.schema)}
        <span class="muted">${e.adapter === "analyst" ? "analyst" : "planner"} model</span>${variant}${kindChip}
        <span class="tag-pill" title="Expected outcome">${esc(e._outcome.replace(/_/g, " "))}</span>
        <span class="spacer"></span>${issueBadge(e)}${reviewMini(e)}</div>
      ${issuesHtml(shownIssues)}
      ${body}${foot}
    </div></div>`;
}

function stepUserBubble(e, c, label) {
  const ed = S.editing?.id === e.id && S.editing.kind === "prompts" ? S.editing : null;
  const p = e.prompts || [];
  const differs = e.adapter === "analyst" && p.some((x) => x.path === "answer.question" && norm(x.value) !== norm(c.question));
  const body = ed
    ? p.map((x) => `<div class="prompt-label">${esc(x.label)}</div><textarea data-prompt="${esc(x.path)}" rows="3">${esc(ed.draft[x.path] ?? x.value)}</textarea>`).join("")
      + `<div class="editor-actions"><span class="state muted">Changes only this step.</span>
          <button class="btn small ghost" data-act="cancel-edit">Cancel</button><button class="btn small primary" data-act="save-prompts">Save message</button></div>`
    : `<div class="bubble-text">${esc(userMessage(e)) || '<span class="muted">(empty)</span>'}</div>`;
  return `<div class="turn" data-ustep="${esc(e.id)}"><div class="avatar user">U</div><div class="bubble final-user">
    <div class="bubble-head">User · ${esc(label)}${differs ? ' <span class="tag-pill" title="This step\'s copy of the original question differs from the opening question">original question differs</span>' : ""}
      <span class="spacer"></span>${ed ? "" : `<button class="link-btn" data-sact="edit-prompt" data-for="${esc(e.id)}">Edit</button>`}</div>
    ${body}</div></div>`;
}

// Earlier turns are context, not trained. They are shared by the steps that come
// after them, so an edit here updates every copy in the conversation.
function contextTurnsHtml(e, c, texts) {
  const ed = S.editing?.kind === "ctx" && S.editing.key === c.key ? S.editing : null;
  return e.turns.map((t) => {
    if (t.role === "user" && norm(t.text) === norm(c.question)) return "";
    const who = t.role === "user" ? "User · earlier message"
      : t.status === "needs_information" ? "GraphMine · clarification question shown to the user" : "GraphMine · reply";
    const idx = texts.push(t.text) - 1;
    const editing = ed && ed.old === t.text;
    return `<div class="turn"><div class="avatar ${t.role}">${t.role === "assistant" ? "G" : "U"}</div>
      <div class="bubble context-turn"><div class="bubble-head">${who} <span class="muted">(context, not trained)</span>${t.status ? ` · <span class="tag-pill">${esc(t.status)}</span>` : ""}
        <span class="spacer"></span>${editing ? "" : `<button class="link-btn" data-act="edit-ctx" data-ctx="${idx}" title="Edit this text in every step that shares it">Edit</button>`}</div>
      ${editing ? `<textarea id="ctx-editor" rows="3">${esc(ed.text)}</textarea>
        <div class="editor-actions"><span class="state muted">Updates every step of this conversation that shares this text. A rebuild replaces text the agent derives.</span>
          <button class="btn small ghost" data-act="cancel-edit">Cancel</button><button class="btn small primary" data-act="save-ctx">Save</button></div>`
        : `<div class="bubble-text">${esc(t.text)}</div>`}</div></div>`;
  }).join("");
}

function convThreadHtml(c, steps) {
  const ed = S.editing;
  const editingQ = ed?.kind === "convq" && ed.key === c.key;
  const usesQ = steps.filter((e) => e.prompts.some((p) => p.value === c.question) || e.turns.some((t) => t.text === c.question)).length;
  const texts = (S.ctxTexts = []);
  const parts = [`<div class="turn"><div class="avatar user">U</div><div class="bubble final-user">
    <div class="bubble-head">User · question<span class="spacer"></span>${editingQ ? "" : '<button class="link-btn" data-act="edit-convq">Edit (q)</button>'}</div>
    ${editingQ ? `<textarea id="convq-editor" rows="3">${esc(ed.text)}</textarea>
      <div class="editor-actions"><span class="state muted">Updates this question in the ${plural(usesQ, "step")} that use it, including earlier-turn context.</span>
        <button class="btn small ghost" data-act="cancel-edit">Cancel</button><button class="btn small primary" data-act="save-convq">Save question</button></div>`
      : `<div class="bubble-text">${esc(c.question) || '<span class="muted">(empty question)</span>'}</div>`}</div></div>`];
  // Read as a chat: a user bubble appears only when the message changes. Each
  // alternative (retry, other analyst request, follow-up) is one boxed branch.
  let section = "main";
  let branch = null;
  let box = null;
  let mainUser = norm(c.question);
  let lastUser = mainUser;
  let lastContext = "";
  let plan = null;
  let nextPlaced = false;
  const closeBox = () => { if (box) parts.push(`<div class="branch">${box.join("")}</div>`); box = null; };
  const runDivider = (request) => {
    const op = (plan || steps.find((x) => x.schema === "PlanDraft"))?.tags.operation_id || c.tagged.tags.operation_id;
    return `<div class="run-divider"><span>⚙ GraphMine runs ${op ? `<code>${esc(op)}</code>` : "the plan"}${c.lineage ? ` on ${esc(c.lineage)}` : ""}; the analyst gets the computed result${request ? ` and the request “${esc(request)}”` : ""}</span></div>`;
  };
  const placeNext = () => { if (!nextPlaced) { nextPlaced = true; parts.push(nextStepHtml(c, plan, runDivider)); } };
  steps.forEach((e, i) => {
    // The main path ends before the alternatives: say what comes next there.
    if (e._phase >= 4 && !nextPlaced) { closeBox(); placeNext(); }
    if (e._section !== section) {
      closeBox();
      section = e._section;
      branch = null;
      const [title, desc] = SECTION_INFO[section] || [];
      if (title) parts.push(`<div class="thread-section"><div class="ts-title">${esc(title)}</div><div class="ts-desc">${esc(desc)}</div></div>`);
      if (section === "main") lastUser = mainUser;
    }
    const inBranch = section !== "main";
    if (inBranch && e._branch !== branch) {
      closeBox();
      branch = e._branch;
      box = [];
      // A retry repeats the main question; analyst requests and follow-ups are new messages.
      lastUser = section === "recovery" ? mainUser : "";
    }
    const out = inBranch ? box : parts;
    if (section === "main" && e.schema === "PlanDraft") plan = e;
    const ctx = e.turns.map((t) => `${t.role}:${t.text}`).join("\n");
    if (e.turns.length && ctx !== lastContext) {
      // Context shared by several branches sits above their boxes.
      (inBranch && !box.length ? parts : out).push(contextTurnsHtml(e, c, texts));
      lastContext = ctx;
    }
    const msg = norm(userMessage(e));
    const editingPrompt = ed?.kind === "prompts" && ed.id === e.id;
    if (e._phase === 3) {
      // The main answer's request is not typed by the user: the agent sends the
      // objective from Understanding. Show it on the run divider instead.
      out.push(runDivider(msg !== mainUser ? userMessage(e) : ""));
      if (editingPrompt) out.push(stepUserBubble(e, c, "request to the analyst"));
    } else if (editingPrompt || msg !== lastUser) {
      const label = e._phase === 1 ? "reply to the clarification question" : section === "followup" ? "follow-up message"
        : section === "analyst" ? "request to the analyst" : "message for this step";
      out.push(stepUserBubble(e, c, label));
      lastUser = msg;
      if (section === "main") mainUser = msg;
    }
    out.push(stepHtml(e, i + 1));
  });
  closeBox();
  placeNext();
  return `<div class="card"><div class="card-head">Conversation
      <span class="muted" style="font-weight:400">${plural(steps.length, "step")}, each a separate training target</span><span class="spacer"></span>
      <span class="seg"><button data-omode="tree" class="${S.outputMode === "tree" ? "on" : ""}">Tree</button><button data-omode="pretty" class="${S.outputMode === "pretty" ? "on" : ""}">JSON</button></span></div>
    <div class="card-body thread">${parts.join("")}</div></div>`;
}

// ---------- the next step of a conversation, written in place
// What production would ask for next, from the conversation's progress. When the
// conversation was built, the card shows that step's real model input (and, for
// the analyst, the computed facts), so the output can be written against it.
const NEXT_SCHEMA = { needs_understanding: "RouteDecision", needs_planning: "PlanDraft", needs_answer: "GroundedNarrative", waiting_reply: "RouteDecision" };
function derivedClarification(output) {
  if ((output?.ambiguity || []).length) return output.ambiguity.join(" ");
  if ((output?.missing_information || []).length) return "I need one more detail: " + output.missing_information.join("; ");
  return output?.explanation || "";
}
function nextStepHtml(c, plan, runDivider) {
  if (c.progress === "complete") {
    return c.live.some((e) => e._section === "followup") ? ""
      : `<div class="next-step done"><span class="muted">Complete. A follow-up message would continue it as an alternative branch.</span> <button class="btn small" data-act="add-to-conv">+ Add follow-up</button></div>`;
  }
  if (c.progress === "refused") return `<div class="next-step done"><span class="muted">The agent refuses here, so the conversation ends with this step.</span></div>`;
  const ctx = S.convContext.get(c.key);
  const sum = S.conversations[c.key];
  const fresh = sum?.built && sum?.fresh;
  if (c.progress === "ready_to_run") {
    const building = S.building?.group === c.key;
    return `${runDivider("")}<div class="next-step"><div class="ns-head"><b>Next: run GraphMine</b><span class="muted">The plan is ready. Running it computes the facts the analyst answer must cite.</span></div>
      <button class="btn primary small" data-act="run" ${building ? "disabled" : ""}>${building ? "Running…" : "▶ Run GraphMine"}</button></div>`;
  }
  const schema = NEXT_SCHEMA[c.progress];
  if (!schema) return "";
  const ed = S.editing?.kind === "next" && S.editing.key === c.key ? S.editing : null;
  const input = fresh ? (ctx?.next || []).find((n) => n.branch === "main" && n.schema === schema && n.messages) : null;
  const facts = schema === "GroundedNarrative" && fresh ? ctx?.facts || [] : [];
  const reply = c.progress === "waiting_reply";
  const ask = reply ? c.live.filter((e) => e._section === "main" && e.schema === "RouteDecision").pop() : null;
  const intro = reply
    ? `GraphMine asked: <i>“${esc(derivedClarification(ask?.output) || "…")}”</i> Write the user's reply, then the Understanding of that reply.`
    : schema === "GroundedNarrative" ? (facts.length ? `Cite the computed facts below by id (fact_ids, and fact_ids on each statement).` : `Build the conversation to see the computed facts this answer must cite.`)
      : input ? "The model input is below; write the expected output against it." : sum?.replayable ? "Rebuild the conversation to see this step's model input." : "";
  return `${schema === "GroundedNarrative" ? runDivider("") : ""}<div class="next-step" id="next-step">
    <div class="ns-head"><b>Next: ${reply ? "the user's reply" : esc(STAGE_LABEL[schema])}</b> ${stageChip(schema)}<span class="muted">${intro}</span></div>
    ${facts.length ? `<details class="ns-facts" open><summary>${plural(facts.length, "computed fact")}</summary><ul class="fact-list">${facts.map((f) => `<li><code>${esc(f.id)}</code><span>${esc(f.statement || JSON.stringify(f.value))}</span></li>`).join("")}</ul></details>` : ""}
    ${input ? `<details class="ns-input"><summary>Model input (${(input.messages.at(-1).content.length).toLocaleString()} chars)</summary><div class="json-tree" data-next-input></div></details>` : ""}
    ${ed ? `${reply ? `<label class="block">User · reply<textarea id="next-reply" rows="2">${esc(ed.reply || "")}</textarea></label>` : ""}
      <div class="label-row"><span>${esc(STAGE_LABEL[schema])} · expected output (JSON)</span><button class="link-btn" data-act="next-template">Load template</button></div>
      <textarea class="json-edit" id="next-editor" spellcheck="false">${esc(ed.text)}</textarea>
      <div class="editor-actions"><span class="state" id="next-state"></span>
        <button class="btn small ghost" data-act="cancel-edit">Cancel</button><button class="btn small primary" data-act="save-next">Save step</button></div>
      <div id="next-issues" class="issues"></div>`
    : `<button class="btn small primary" data-act="write-next">Write ${reply ? "the reply" : esc(STAGE_LABEL[schema])}</button>`}
  </div>`;
}
function initNextEditor() {
  const c = currentConv();
  const ctx = S.convContext.get(c?.key);
  const host = $("[data-next-input]");
  const schema = NEXT_SCHEMA[c?.progress];
  const input = (ctx?.next || []).find((n) => n.branch === "main" && n.schema === schema && n.messages);
  if (host && input) host.closest("details").addEventListener("toggle", () => {
    if (!host.innerHTML) { try { host.innerHTML = jsonTree(JSON.parse(input.messages.at(-1).content)); } catch { host.textContent = input.messages.at(-1).content; } }
  }, { once: true });
  const ta = $("#next-editor");
  if (!ta) return;
  const check = debounce(async () => {
    const ed = S.editing;
    if (ed?.kind !== "next") return;
    let output;
    try { output = JSON.parse(ta.value); } catch (err) { $("#next-state").innerHTML = `<span class="ic critical">✕</span> Invalid JSON: ${esc(err.message)}`; return; }
    try {
      const { issues } = await api("/api/validate", { schema: ed.schema, output, prompts: [{ value: c.question }], tags: c.tagged.tags });
      const shown = issues.filter((i) => i.field !== "context" && i.field !== "split" && i.field !== "prompts");
      ed.errors = shown.some((i) => i.level === "error");
      $("#next-state").innerHTML = ed.errors ? '<span class="ic critical">✕</span> Fails validation' : `<span class="ic good">✓</span> Valid ${esc(ed.schema)}`;
      $("#next-issues").innerHTML = issuesHtml(shown);
    } catch (err) { fail(err); }
  }, 350);
  ta.addEventListener("input", () => { S.editing.text = ta.value; check(); });
  $("#next-reply")?.addEventListener("input", (ev) => { S.editing.reply = ev.target.value; });
  if (ta.value.trim()) check();
}
// The new step's message and earlier turns follow the path it continues.
async function saveNextStep() {
  const ed = S.editing;
  const c = S.convs.get(ed.key);
  let output;
  try { output = JSON.parse($("#next-editor").value); } catch { return toast("The output is not valid JSON", true); }
  if (ed.errors && !confirm("This output fails validation. Save it anyway?")) return;
  const main = c.live.filter((e) => e._section === "main");
  const replyStep = main.find((e) => e._phase === 1);
  let message = replyStep ? userMessage(replyStep) : c.question;
  let turns = replyStep ? replyStep.turns : [];
  if (ed.reply !== undefined) {
    const reply = ($("#next-reply")?.value || "").trim();
    if (!reply) return toast("Write the user's reply", true);
    const ask = main.filter((e) => e.schema === "RouteDecision").pop();
    message = reply;
    turns = [{ role: "user", text: c.question, status: null, payload: null },
      { role: "assistant", text: derivedClarification(ask?.output), status: "needs_information", payload: null }];
  }
  const step = ed.schema === "GroundedNarrative"
    ? { adapter: "analyst", schema: ed.schema, turns: [], output,
      prompt_fields: [{ path: "answer.question", label: "Original user question", value: message }, { path: "user_message", label: "Request to the analyst", value: message }] }
    : { adapter: "planner", schema: ed.schema, turns, output, prompt_fields: [{ path: "message", label: "User question", value: message }] };
  try {
    const r = await api("/api/create-conversation", { group: c.key, steps: [{ ...step, split: c.split, tags: Object.fromEntries(Object.entries(c.tagged.tags).filter(([, v]) => v)) }] });
    r.examples.forEach(applyExample);
    applyIssues(r.issues);
    applyConversations(r.conversations);
    S.editing = null;
    refreshAll();
    renderDetail();
    toast(`${STAGE_LABEL[ed.schema]} saved`);
    autoBuild(c.key);
  } catch (err) { fail(err); }
}

// JSON tree & highlighting
function jsonLeaf(v) {
  if (v === null) return '<span class="jz">null</span>';
  if (typeof v === "string") return `<span class="js">${esc(JSON.stringify(v))}</span>`;
  if (typeof v === "number") return `<span class="jn">${v}</span>`;
  if (typeof v === "boolean") return `<span class="jb">${v}</span>`;
  return esc(String(v));
}
function jsonTree(v, key = null, depth = 0) {
  const k = key !== null ? `<span class="jk">${esc(JSON.stringify(key))}</span><span class="jp">: </span>` : "";
  if (v && typeof v === "object") {
    const isArr = Array.isArray(v);
    const entries = isArr ? v.map((x, i) => [i, x]) : Object.entries(v);
    const [o, c] = isArr ? ["[", "]"] : ["{", "}"];
    if (!entries.length) return `<div class="jt-leaf">${k}<span class="jp">${o}${c}</span></div>`;
    const sum = isArr ? plural(entries.length, "item") : plural(entries.length, "key");
    return `<details${depth < 2 ? " open" : ""}><summary>${k}<span class="jp">${o}</span> <span class="jsum">${sum}</span></summary>
      <div class="jt-children">${entries.map(([ck, cv]) => jsonTree(cv, isArr ? null : ck, depth + 1)).join("")}</div><span class="jp">${c}</span></details>`;
  }
  return `<div class="jt-leaf">${k}${jsonLeaf(v)}</div>`;
}
function highlightJson(v) {
  const s = esc(JSON.stringify(v, null, 2));
  return s.replace(/(&quot;(?:\\.|[^&\\]|&(?!quot;))*?&quot;)(\s*:)?|\b(true|false)\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g, (m, str, colon, bool) => {
    if (str) return colon ? `<span class="jk">${str}</span>${colon}` : `<span class="js">${str}</span>`;
    if (bool) return `<span class="jb">${m}</span>`;
    if (m === "null") return `<span class="jz">${m}</span>`;
    return `<span class="jn">${m}</span>`;
  });
}

// ---------- context tab
async function loadContext(e, body) {
  body.innerHTML = '<div class="muted">Loading model context…</div>';
  try {
    let ctx = S.contextCache.get(e.id);
    if (!ctx) { ctx = await api(`/api/context?id=${encodeURIComponent(e.id)}`); S.contextCache.set(e.id, ctx); }
    if (S.currentId !== e.id || S.tab !== "context") return;
    body.innerHTML = contextHtml(ctx, e);
  } catch (err) { body.innerHTML = `<div class="issue"><span class="ic critical">✕</span><div>${esc(err.message)}</div></div>`; }
}
function kvHtml(pairs) {
  const rows = pairs.filter(([, v]) => v !== undefined && v !== null && v !== "" && !(Array.isArray(v) && !v.length) && !(typeof v === "object" && !Array.isArray(v) && !Object.keys(v).length));
  if (!rows.length) return "";
  return `<dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${typeof v === "object" ? `<code>${esc(JSON.stringify(v))}</code>` : esc(String(v))}</dd>`).join("")}</dl>`;
}
function contextHtml(ctx, e) {
  if (!ctx.available) {
    return `<div class="callout">Written here, so its model input comes from replaying the conversation through the agent. ${ctx.replayable
      ? "Build the conversation (Model inputs, in the conversation view) to see it." : "Choose a graph and domain for the conversation, then build it."}
      Until then it exports to <code>needs-context.jsonl</code>.</div>`;
  }
  const p = ctx.payload || {};
  const parts = [];
  if (ctx.captured) {
    parts.push(`<div class="callout">Model input from replaying the conversation through the agent${ctx.built_at ? `, built ${esc(new Date(ctx.built_at).toLocaleString())}` : ""}.
      ${ctx.fresh ? "It is current, so this step exports as a training row." : "<b>Out of date:</b> the conversation changed after that build; rebuild it before exporting."}</div>`);
    if ((ctx.history || []).length) {
      parts.push(`<div class="card"><div class="card-head">Conversation history the model sees <span class="muted" style="font-weight:400">${ctx.history.length} message${ctx.history.length > 1 ? "s" : ""}</span></div>
        <div class="card-body thread">${ctx.history.map(turnBubble).join("")}</div></div>`);
    }
  }
  if (ctx.source_id && ctx.source_id !== e.id) parts.push(`<div class="callout">Context inherited from <button class="link-btn" data-goto="${esc(ctx.source_id)}">${esc(ctx.source_id)}</button>.</div>`);
  parts.push(`<div class="card"><div class="card-head">Task given to Qwen</div><div class="card-body">${esc(p.task || "—")}</div></div>`);
  const gm = p.graph_metadata || {};
  const graphPairs = [["Graph", gm.name], ["Vertices", gm.vertex_count], ["Edges", gm.edge_count], ["Directed", gm.directed], ["Weighted", gm.has_weights], ["Timestamps", gm.has_timestamps], ["Density", gm.density]];
  const planPairs = [
    ["Domain", p.domain?.name], ["Selected operation", p.selected_operation && `${p.selected_operation.problem_id} → ${p.selected_operation.operation_id}`],
    ["Objective", p.application_intent?.objective], ["Filters", p.application_intent?.filters], ["Supplied parameters", p.supplied_parameters],
    ["Requested outputs", p.requested_optional_outputs], ["Requested backend", p.requested_backend], ["Previous question", p.previous_question],
    ["Previous operation", p.previous_operation], ["Pending request", p.pending_request], ["Active constraints", p.active_constraints],
    ["Files", (p.available_files || []).map((f) => `${f.role}: ${f.name}`)],
  ];
  const kv1 = kvHtml(planPairs), kv2 = kvHtml(graphPairs);
  if (kv1 || kv2) parts.push(`<div class="card"><div class="card-head">Planner inputs</div><div class="card-body">${kv1}${kv2 ? `<div style="height:8px"></div>${kv2}` : ""}</div></div>`);
  const ans = p.answer;
  if (ans) {
    const facts = (ans.facts || []).map((f) => `<li><code>${esc(f.id || "")}</code><span>${esc(f.statement || JSON.stringify(f))}</span></li>`).join("");
    parts.push(`<div class="card"><div class="card-head">Computed facts the analyst may cite <span class="muted" style="font-weight:400">${(ans.facts || []).length}</span></div>
      <div class="card-body"><ul class="fact-list">${facts || "<li>—</li>"}</ul>
      ${(ans.limitations || []).length ? `<div class="prompt-label" style="margin-top:10px">Limitations</div><ul>${ans.limitations.map((l) => `<li>${esc(typeof l === "string" ? l : JSON.stringify(l))}</li>`).join("")}</ul>` : ""}</div></div>`);
    const ds = p.analysis_context?.datasets || {};
    if (Object.keys(ds).length) parts.push(`<div class="card"><div class="card-head">Chart datasets</div><div class="card-body">${kvHtml(Object.entries(ds).map(([k, v]) => [k, Object.keys(v.columns || {}).join(", ")]))}</div></div>`);
  }
  parts.push(`<details class="card"><summary class="card-head" style="cursor:pointer">System prompt <span class="muted" style="font-weight:400">${(ctx.system || "").length.toLocaleString()} chars</span></summary>
    <div class="card-body"><pre class="json-pretty">${esc(ctx.system || "")}</pre></div></details>`);
  parts.push(`<details class="card" id="raw-payload"><summary class="card-head" style="cursor:pointer">Full user payload <span class="muted" style="font-weight:400">${(ctx.user_chars || 0).toLocaleString()} chars</span></summary>
    <div class="card-body"><div class="json-tree" id="raw-payload-tree"></div></div></details>`);
  setTimeout(() => {
    const d = $("#raw-payload");
    d?.addEventListener("toggle", () => { const t = $("#raw-payload-tree"); if (d.open && !t.innerHTML) t.innerHTML = jsonTree(p); }, { once: false });
  });
  return parts.join("");
}

// ---------- diff tab
function lineDiff(a, b) {
  const n = a.length, m = b.length;
  if (n * m > 4e6) return [...a.map((l) => ["del", l]), ...b.map((l) => ["add", l])];
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push(["same", a[i]]); i++; j++; } else if (dp[i + 1][j] >= dp[i][j + 1]) out.push(["del", a[i++]]); else out.push(["add", b[j++]]);
  }
  while (i < n) out.push(["del", a[i++]]);
  while (j < m) out.push(["add", b[j++]]);
  return out;
}
function diffHtml(before, after) {
  const ops = lineDiff(before.split("\n"), after.split("\n"));
  const keep = new Set();
  ops.forEach(([t], i) => { if (t !== "same") for (let k = i - 3; k <= i + 3; k++) keep.add(k); });
  let html = "", skipped = 0;
  ops.forEach(([t, l], i) => {
    if (t === "same" && !keep.has(i)) { skipped++; return; }
    if (skipped) { html += `<div class="gap">… ${skipped} unchanged line${skipped > 1 ? "s" : ""}</div>`; skipped = 0; }
    html += `<div class="${t}">${esc(l)}</div>`;
  });
  if (skipped) html += `<div class="gap">… ${skipped} unchanged line${skipped > 1 ? "s" : ""}</div>`;
  return `<div class="diff">${html || '<div class="gap">No differences</div>'}</div>`;
}
async function loadDiff(e, body) {
  body.innerHTML = '<div class="muted">Loading original…</div>';
  try {
    const { original } = await api(`/api/original?id=${encodeURIComponent(e.id)}`);
    if (S.currentId !== e.id || S.tab !== "diff") return;
    if (!original) { body.innerHTML = '<div class="muted">No original to compare with.</div>'; return; }
    const parts = [];
    const op = Object.fromEntries(original.prompts.map((p) => [p.path, p.value]));
    for (const p of e.prompts) if (op[p.path] !== p.value) parts.push(`<div class="card"><div class="card-head">${esc(p.label)}</div><div class="card-body">${diffHtml(wrapText(op[p.path] || ""), wrapText(p.value))}</div></div>`);
    const tb = original.turns.map((t) => `${t.role}${t.status ? ` [${t.status}]` : ""}: ${t.text}`).join("\n");
    const ta = e.turns.map((t) => `${t.role}${t.status ? ` [${t.status}]` : ""}: ${t.text}`).join("\n");
    if (tb !== ta) parts.push(`<div class="card"><div class="card-head">Earlier turns</div><div class="card-body">${diffHtml(tb, ta)}</div></div>`);
    if (JSON.stringify(original.output) !== JSON.stringify(e.output)) parts.push(`<div class="card"><div class="card-head">Expected output</div><div class="card-body">${diffHtml(JSON.stringify(original.output, null, 2), JSON.stringify(e.output, null, 2))}</div></div>`);
    if (original.split !== e.split) parts.push(`<div class="card"><div class="card-head">Split</div><div class="card-body">${esc(original.split)} → <b>${esc(e.split)}</b></div></div>`);
    body.innerHTML = parts.join("") || '<div class="muted">Content is identical to the original; only tags, review, labels or notes changed.</div>';
  } catch (err) { fail(err); }
}
const wrapText = (s) => String(s).replace(/([.?!])\s+/g, "$1\n");

// ---------- history tab
async function loadHistory(e, body) {
  body.innerHTML = '<div class="muted">Loading history…</div>';
  try {
    const { history } = await api(`/api/history?id=${encodeURIComponent(e.id)}`);
    if (S.currentId !== e.id || S.tab !== "history") return;
    if (!history.length) { body.innerHTML = '<div class="muted">No edits yet. This example is identical to the source dataset.</div>'; return; }
    body.innerHTML = `<ul class="history-list" style="padding:0;margin:0">${history.slice().reverse().map((h) => {
      const st = h.state || {};
      const keys = Object.keys(st).filter((k) => k !== "updated_at");
      const summary = h.state === null ? "returned to original / discarded"
        : keys.map((k) => k === "review" ? `review → ${st.review}` : k === "deleted" ? (st.deleted ? "deleted" : "restored") : k === "tags" ? `tags → ${Object.entries(st.tags).map(([a, b]) => `${a.replace("_id", "")}=${b}`).join(", ")}` : k).join(" · ");
      return `<li><span class="muted">${esc(new Date(h.ts).toLocaleString())}</span><span>${esc(h.op)}</span><span>${esc(summary)}</span></li>`;
    }).join("")}</ul>`;
  } catch (err) { fail(err); }
}

// ------------------------------------------------------------------ editing
// kind: "output" | "prompts" | "turns" edit one row (S.editing.id); "convq" edits the
// opening question of the current conversation in every step that uses it.
function startEdit(kind, id = S.currentId, extra = null) {
  const e = S.byId.get(id);
  if (!e) return;
  const same = S.editing && S.editing.kind === kind && (kind === "convq" || kind === "ctx" ? S.editing.key === e.group && S.editing.old === extra : S.editing.id === id);
  if (S.editing && !same && !confirm("Discard unsaved edits?")) return;
  if (S.tab !== "conversation") S.tab = "conversation";
  if (kind === "output") S.editing = { kind, id, text: JSON.stringify(e.output, null, 2) };
  if (kind === "prompts") S.editing = { kind, id, draft: Object.fromEntries(e.prompts.map((p) => [p.path, p.value])) };
  if (kind === "ctx") S.editing = { kind, key: e.group, old: extra, text: extra };
  if (kind === "convq") S.editing = { kind, key: e.group, text: S.convs.get(e.group).question };
  renderDetail();
  const el = kind === "prompts" ? $(`[data-ustep="${CSS.escape(id)}"] [data-prompt]`) || $("[data-prompt]")
    : kind === "output" ? $("#output-editor") : kind === "convq" ? $("#convq-editor") : $("#ctx-editor");
  if (el) {
    el.focus();
    if (kind !== "output") el.setSelectionRange(el.value.length, el.value.length);
    if (S.mode === "conv") el.scrollIntoView({ block: "nearest" });
  }
}
function cancelEdit() { S.editing = null; renderDetail(); }
function syncDrafts() {
  const ed = S.editing;
  if (!ed) return;
  if (ed.kind === "prompts") $$("[data-prompt]").forEach((t) => (ed.draft[t.dataset.prompt] = t.value));
  if (ed.kind === "ctx" && $("#ctx-editor")) ed.text = $("#ctx-editor").value;
  if (ed.kind === "next" && $("#next-editor")) { ed.text = $("#next-editor").value; if ($("#next-reply")) ed.reply = $("#next-reply").value; }
  if (ed.kind === "output" && $("#output-editor")) ed.text = $("#output-editor").value;
  if (ed.kind === "convq" && $("#convq-editor")) ed.text = $("#convq-editor").value;
}

const validateDraft = debounce(async (id, output, schema) => {
  try {
    const { issues } = await api("/api/validate", { id, output, schema });
    if (S.editing?.kind !== "output" || S.editing.id !== id) return;
    S.editing.issues = issues;
    $("#editor-issues").innerHTML = issuesHtml(issues.filter((i) => i.field !== "split" && i.field !== "context"));
    updateEditorState();
  } catch (err) { fail(err); }
}, 350);

function updateEditorState() {
  const st = $("#editor-state");
  if (!st) return;
  const ed = S.editing;
  if (ed.parseError) st.innerHTML = `<span class="ic critical">✕</span> Invalid JSON: ${esc(ed.parseError)}`;
  else if (ed.issues?.some((i) => i.level === "error")) st.innerHTML = `<span class="ic critical">✕</span> Valid JSON, but fails validation`;
  else if (ed.issues) st.innerHTML = `<span class="ic good">✓</span> Valid ${esc(S.byId.get(ed.id)?.schema || "")}`;
  else st.innerHTML = '<span class="muted">Checking…</span>';
  $("#save-output").disabled = !!ed.parseError;
}

function initOutputEditor() {
  const ta = $("#output-editor");
  if (!ta) return;
  const e = S.byId.get(S.editing.id);
  const onInput = () => {
    S.editing.text = ta.value;
    try {
      const obj = JSON.parse(ta.value);
      S.editing.parseError = null;
      S.editing.issues = null;
      validateDraft(e.id, obj, e.schema);
    } catch (err) {
      S.editing.parseError = err.message.replace(/^JSON\.parse: /, "");
      S.editing.issues = null;
    }
    updateEditorState();
  };
  ta.addEventListener("input", onInput);
  ta.addEventListener("keydown", (ev) => {
    if (ev.key === "Tab") {
      ev.preventDefault();
      const s = ta.selectionStart;
      ta.setRangeText("  ", s, ta.selectionEnd, "end");
      onInput();
    }
  });
  ta.style.height = Math.min(Math.max(260, ta.scrollHeight + 4), innerHeight * 0.65) + "px";
  onInput();
}

async function saveOutput() {
  const ed = S.editing;
  let obj;
  try { obj = JSON.parse(ed.text); } catch { return toast("Fix the JSON first", true); }
  if (ed.issues?.some((i) => i.level === "error") && !confirm("This output fails validation and would train Qwen on an invalid target. Save anyway?")) return;
  const before = S.byId.get(ed.id);
  const oldAsk = before?.schema === "RouteDecision" && before._phase === 0 && asksForInfo(before.output) ? derivedClarification(before.output) : null;
  if (!(await update(ed.id, { output: obj }, "Output saved"))) return;
  S.editing = null;
  renderDetail();
  // The question GraphMine shows the user is derived from this output; keep the replies' copy in step.
  const newAsk = asksForInfo(obj) ? derivedClarification(obj) : null;
  if (oldAsk && newAsk && newAsk !== oldAsk) {
    const c = S.convs.get(before.group);
    const replies = c.live.filter((e) => e._phase === 1 && e.turns.some((t) => t.role === "assistant" && t.text === oldAsk));
    if (replies.length) {
      try {
        const r = await api("/api/update-many", { patches: replies.map((e) => ({ id: e.id, patch: { turns: e.turns.map((t) => (t.role === "assistant" && t.text === oldAsk ? { ...t, text: newAsk } : t)) } })) });
        r.examples.forEach(applyExample);
        applyIssues(r.issues);
        applyConversations(r.conversations);
        refreshAll();
        renderDetail();
        toast(`Clarification question updated in ${plural(replies.length, "reply step")}`);
      } catch (err) { fail(err); }
    }
  }
}

async function savePrompts() {
  const draft = {};
  $$("[data-prompt]").forEach((t) => (draft[t.dataset.prompt] = t.value));
  if (!Object.values(draft).some((v) => v.trim())) return toast("The question cannot be empty", true);
  if (!(await update(S.editing.id, { prompts: draft }, "Question saved"))) return;
  S.editing = null;
  renderDetail();
}

// Replace one text everywhere this conversation uses it verbatim: prompt fields
// (planner message, analyst question/request) and earlier turns. Used for the
// opening question and for shared context such as GraphMine's earlier replies.
async function saveConvText(old, text) {
  const c = S.convs.get(S.editing?.key || S.convKey);
  if (!text.trim()) return toast("The text cannot be empty", true);
  if (text === old) { cancelEdit(); return; }
  const patches = [];
  for (const e of c.steps) {
    const patch = {};
    // Send every prompt field: the server replaces the whole prompt overlay.
    if (e.prompts.some((p) => p.value === old)) patch.prompts = Object.fromEntries(e.prompts.map((p) => [p.path, p.value === old ? text : p.value]));
    if (e.turns.some((t) => t.text === old)) patch.turns = e.turns.map((t) => (t.text === old ? { ...t, text } : t));
    if (Object.keys(patch).length) patches.push({ id: e.id, patch });
  }
  try {
    const r = await api("/api/update-many", { patches });
    r.examples.forEach(applyExample);
    applyIssues(r.issues);
    applyConversations(r.conversations);
    S.editing = null;
    refreshAll();
    renderDetail();
    const skipped = c.steps.length - patches.length;
    toast(`Updated in ${plural(patches.length, "step")}${skipped ? ` · ${skipped} with different wording left unchanged` : ""}`);
    autoBuild(c.key);
  } catch (err) { fail(err); }
}
const saveConvQuestion = () => saveConvText(S.convs.get(S.editing.key).question, $("#convq-editor").value);

// ------------------------------------------------------------------ mutations
function applyExample(ex) {
  prepare(ex);
  const i = S.examples.findIndex((x) => x.id === ex.id);
  if (i >= 0) S.examples[i] = ex; else S.examples.push(ex);
  S.byId.set(ex.id, ex);
  S.contextCache.delete(ex.id);
}
function applyIssues(map) {
  for (const [id, issues] of Object.entries(map || {})) {
    const e = S.byId.get(id);
    if (e) { e.issues = issues; e._issue = issueLevel(e); }
  }
}
// Server summaries arrive with every change; a stale summary means the cached build report is too.
function applyConversations(map) {
  for (const [group, summary] of Object.entries(map || {})) {
    S.conversations[group] = summary;
    if (!summary.fresh) S.convContext.delete(group);
  }
}
function refreshAll() {
  buildConvs();
  computeVisible();
  renderFacets();
  renderList(true);
  renderStatus();
  refreshLabelOptions();
  if (S.view === "coverage") renderCoverage();
  if (S.view === "changes") renderChanges();
}
const CONTENT_FIELDS = ["output", "prompts", "turns", "deleted"];
async function update(id, patch, msg) {
  try {
    const r = await api("/api/update", { id, patch });
    applyExample(r.example);
    applyIssues(r.issues);
    applyConversations(r.conversations);
    refreshAll();
    if (id === S.currentId || (S.mode === "conv" && r.example.group === S.convKey)) { syncDrafts(); renderDetail(); }
    if (msg) toast(msg);
    if (CONTENT_FIELDS.some((k) => k in patch)) autoBuild(r.example.group);
    return r.example;
  } catch (err) { fail(err); return null; }
}
async function bulk(patch, msg, ids = [...S.selected]) {
  if (!ids.length) return;
  try {
    const r = await api("/api/bulk", { ids, patch });
    r.examples.forEach(applyExample);
    applyIssues(r.issues);
    applyConversations(r.conversations);
    refreshAll();
    syncDrafts();
    renderDetail();
    toast(`${msg} · ${plural(ids.length, S.mode === "conv" ? "step" : "example")}`);
    if ("deleted" in patch) new Set(r.examples.map((e) => e.group)).forEach(autoBuild);
  } catch (err) { fail(err); }
}
async function revert(ids, msg) {
  try {
    const r = await api("/api/revert", { ids });
    r.examples.forEach(applyExample);
    for (const id of r.removed || []) {
      S.examples = S.examples.filter((x) => x.id !== id);
      S.byId.delete(id);
      S.selected.delete(id);
      if (S.currentId === id) S.currentId = null;
    }
    applyIssues(r.issues);
    applyConversations(r.conversations);
    refreshAll();
    if (S.mode === "conv" && !S.currentId) {
      // The focused step was discarded: stay on what is left of the conversation.
      const c = currentConv();
      S.rowView = false;
      if (c) S.currentId = convSteps(c)[0].id; else S.convKey = null;
    }
    renderDetail();
    toast(msg);
    Object.keys(r.conversations || {}).forEach(autoBuild);
  } catch (err) { fail(err); }
}
// A duplicate keeps every step's model context (original steps become clones of their source).
async function duplicateConversation(group = S.convKey) {
  if (!group) return;
  try {
    const r = await api("/api/conversation/duplicate", { group });
    r.examples.forEach(applyExample);
    applyIssues(r.issues);
    applyConversations(r.conversations);
    S.facetSel = {};
    S.query = "";
    $("#search").value = "";
    refreshAll();
    selectConv(r.group, { scroll: true });
    toast(`Duplicated as a new conversation (${plural(r.examples.length, "step")}). Edit its question with q.`);
  } catch (err) { fail(err); }
}

// ------------------------------------------------------------------ replay through the agent
// Building replays the conversation through GraphMine's agent: every step gets the
// exact model input production would send, and the next step's input is shown
// while you write it. GraphMine itself only runs when asked (run: true).
function replayable(group) { return !!S.conversations[group]?.replayable && !!S.conversations[group]?.settings; }
async function buildConversation(group, { run = false, quiet = false } = {}) {
  if (S.building) return;
  S.building = { group, run };
  if (S.convKey === group) renderDetail();
  try {
    const r = await api("/api/conversation/build", { group, run });
    r.examples.forEach(applyExample);
    applyIssues(r.issues);
    applyConversations({ ...r.conversations, [group]: r.summary });
    S.convContext.set(group, r.context);
    refreshAll();
    const errors = (r.context.events || []).filter((x) => x.level === "error");
    if (!quiet || errors.length) {
      toast(errors.length ? `${errors[0].stage}: ${errors[0].message}`
        : run ? `Built${r.context.runs ? ` · GraphMine ran ${plural(r.context.runs, "plan")}` : ""} in ${r.context.seconds} s` : "Model inputs updated", !!errors.length);
    }
  } catch (err) { fail(err); }
  finally {
    S.building = null;
    if (S.convKey === group) renderDetail();
  }
}
// Steps written here are rebuilt after each content change so their inputs stay current.
function autoBuild(group) {
  const c = S.convs.get(group);
  if (replayable(group) && c?.live.some((e) => e.kind === "new")) buildConversation(group, { quiet: true });
}
async function loadConversationContext(group) {
  if (S.convContext.has(group) || !S.conversations[group]?.built) return;
  try {
    const r = await api(`/api/conversation?group=${encodeURIComponent(group)}`);
    applyConversations({ [group]: r.summary });
    if (r.context) S.convContext.set(group, r.context);
    if (S.convKey === group) renderDetail();
  } catch (err) { fail(err); }
}

// ------------------------------------------------------------------ selection & navigation
function select(id, { scroll = false, rowView = false } = {}) {
  if (S.mode === "conv") {
    const e = S.byId.get(id);
    if (e) selectConv(e.group, { stepId: id, scroll, rowView, reveal: true });
    return;
  }
  if (S.editing && S.currentId !== id) {
    if (!confirm("Discard unsaved edits?")) return;
    S.editing = null;
  }
  S.currentId = id;
  S.tab = S.tab === "diff" || S.tab === "history" ? "conversation" : S.tab;
  try { history.replaceState(null, "", "#" + encodeURIComponent(id)); } catch { /* ignore */ }
  // make sure the row is rendered
  const idx = S.flatOrder.findIndex((x) => x.id === id);
  if (idx >= S.rendered) S.rendered = idx + PAGE;
  renderList(true);
  renderDetail();
  document.body.classList.add("detail-open");
  if (scroll) $(`.row[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "nearest" });
}
// Open a conversation; stepId focuses one of its steps (reveal scrolls it into view).
function selectConv(key, { stepId = null, scroll = false, rowView = false, reveal = false } = {}) {
  const c = S.convs.get(key);
  if (!c) return;
  // Within one conversation an open editor survives focusing another step, unless
  // the single-step view replaces it.
  if (S.editing && (S.convKey !== key || (rowView && S.editing.id && S.editing.id !== stepId))) {
    if (!confirm("Discard unsaved edits?")) return;
    S.editing = null;
  }
  const steps = convSteps(c);
  S.convKey = key;
  S.currentId = stepId && c.steps.some((e) => e.id === stepId) ? stepId : (steps[0] || c.steps[0]).id;
  S.rowView = rowView;
  S.tab = S.tab === "diff" || S.tab === "history" ? "conversation" : S.tab;
  try { history.replaceState(null, "", "#c=" + encodeURIComponent(key)); } catch { /* ignore */ }
  const idx = S.convOrder.indexOf(key);
  if (idx >= S.rendered) S.rendered = idx + PAGE;
  renderList(true);
  renderDetail();
  document.body.classList.add("detail-open");
  if (scroll) $(`.row[data-conv="${CSS.escape(key)}"]`)?.scrollIntoView({ block: "nearest" });
  if (reveal && !rowView) $(`[data-step="${CSS.escape(S.currentId)}"]`)?.scrollIntoView({ block: "center" });
  else if (!reveal) $("#detail").scrollTop = 0;
}
// Focus a step inside the open conversation without re-rendering it.
function focusStep(id, scroll = false) {
  if (S.currentId === id) return;
  S.currentId = id;
  $$("#detail .step.focused").forEach((el) => el.classList.remove("focused"));
  const el = $(`#detail [data-step="${CSS.escape(id)}"]`);
  el?.classList.add("focused");
  if (scroll) el?.scrollIntoView({ block: "nearest" });
}
function move(delta) {
  if (S.mode === "conv") {
    const order = S.convOrder;
    if (!order.length) return;
    let i = order.indexOf(S.convKey);
    i = i < 0 ? 0 : Math.max(0, Math.min(order.length - 1, i + delta));
    if (order[i] !== S.convKey || S.rowView) selectConv(order[i], { scroll: true });
    return;
  }
  const order = S.flatOrder;
  if (!order.length) return;
  let i = order.findIndex((x) => x.id === S.currentId);
  i = i < 0 ? 0 : Math.max(0, Math.min(order.length - 1, i + delta));
  select(order[i].id, { scroll: true });
}
function moveStep(delta) {
  const c = currentConv();
  if (S.mode !== "conv" || !c) return;
  const steps = convSteps(c);
  let i = steps.findIndex((e) => e.id === S.currentId);
  i = Math.max(0, Math.min(steps.length - 1, i + delta));
  if (S.rowView) {
    if (S.editing) { if (!confirm("Discard unsaved edits?")) return; S.editing = null; }
    S.currentId = steps[i].id;
    renderDetail();
  } else focusStep(steps[i].id, true);
}
// Steps that conversation-wide tags, review and labels apply to.
function convLiveIds() {
  const c = currentConv();
  return c ? (c.live.length ? c.live : c.steps).map((e) => e.id) : [];
}
function backToConv() {
  // Every editor renders in the thread too, so an open edit survives going back.
  S.rowView = false;
  renderDetail();
  $(`[data-step="${CSS.escape(S.currentId)}"]`)?.scrollIntoView({ block: "center" });
}
function setMode(mode) {
  if (mode === S.mode) return;
  if (S.editing) { if (!confirm("Discard unsaved edits?")) return; S.editing = null; }
  S.mode = mode;
  store.set("mode", mode);
  S.rendered = 0;
  S.rowView = false;
  $$("#mode-seg button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  refreshAll();
  const e = current();
  if (e) select(e.id, { scroll: true });
  else renderDetail();
}

// ------------------------------------------------------------------ coverage view
function bucket(n, max) {
  if (!n) return 0;
  if (max <= 1) return 4;
  return Math.max(1, Math.min(7, 1 + Math.floor(6 * Math.log(n) / Math.log(max))));
}
function renderCoverage() {
  const host = $("#coverage-view");
  const base = (S.coverageFiltered ? S.visible : S.examples).filter((e) => !e.deleted);
  const n = base.length;
  const train = base.filter((e) => e.split === "train").length;
  const val = n - train;
  const distinct = new Set(base.map((e) => norm(e._q))).size;
  const nConv = new Set(base.map((e) => e.group)).size;
  const rev = Object.fromEntries(REVIEW_ORDER.map((r) => [r, base.filter((e) => e.review === r).length]));
  const reviewed = n - rev.unreviewed;
  const clarify = base.filter((e) => e._clarify).length;
  const multi = base.filter((e) => e.turns.length).length;
  const errs = base.filter((e) => e._issue === "error").length;
  const warns = base.filter((e) => e._issue === "warning").length;
  const changes = S.examples.filter((e) => e.kind !== "original" || e.deleted).length;
  const pct = (a, b) => (b ? Math.round((100 * a) / b) : 0);

  const tiles = `<div class="tiles">
    <div class="tile"><div class="t-label">Examples</div><div class="t-value">${n.toLocaleString()}</div><div class="t-sub">${train.toLocaleString()} train · ${val.toLocaleString()} validation</div>
      <div class="meter" aria-hidden="true"><span style="width:${pct(train, n)}%;background:var(--series-1)"></span><span style="width:${pct(val, n)}%;background:var(--series-2)"></span></div></div>
    <div class="tile"><div class="t-label">Conversations</div><div class="t-value">${nConv.toLocaleString()}</div><div class="t-sub">${distinct.toLocaleString()} distinct questions · ${nConv ? (n / nConv).toFixed(1) : 0} training rows per conversation</div></div>
    <div class="tile"><div class="t-label">Reviewed</div><div class="t-value">${pct(reviewed, n)}%</div><div class="t-sub">${rev.approved} approved · ${rev.needs_fix} need fix · ${rev.rejected} rejected</div>
      <div class="meter" aria-hidden="true"><span style="width:${pct(rev.approved, n)}%;background:var(--good)"></span><span style="width:${pct(rev.needs_fix, n)}%;background:var(--serious)"></span><span style="width:${pct(rev.rejected, n)}%;background:var(--critical)"></span></div></div>
    <div class="tile"><div class="t-label">Ask for more info</div><div class="t-value">${clarify.toLocaleString()}</div><div class="t-sub">${multi.toLocaleString()} multi-turn rows</div></div>
    <div class="tile"><div class="t-label">Validation</div><div class="t-value">${errs ? `<span class="ic critical" style="width:20px;height:20px;font-size:11px">✕</span> ${errs}` : `<span class="ic good" style="width:20px;height:20px;font-size:11px">✓</span> 0`}</div><div class="t-sub">${errs} with errors · ${warns} with warnings</div></div>
    <div class="tile"><div class="t-label">Pending changes</div><div class="t-value">${changes}</div><div class="t-sub">Written to a new version on export</div></div>
  </div>`;

  // heatmap: problems × stages
  const stagesPresent = STAGES.filter((s) => base.some((e) => e.schema === s));
  const counts = new Map();
  const splitCounts = new Map();
  for (const e of base) {
    const p = e.tags.problem_id || NONE;
    const k = p + "|" + e.schema;
    counts.set(k, (counts.get(k) || 0) + 1);
    const sc = splitCounts.get(k) || { train: 0, validation: 0 };
    sc[e.split] = (sc[e.split] || 0) + 1;
    splitCounts.set(k, sc);
  }
  const max = Math.max(1, ...counts.values());
  const cats = new Map();
  for (const p of S.problems.values()) {
    if (!cats.has(p.category)) cats.set(p.category, []);
    cats.get(p.category).push(p);
  }
  const extra = [...new Set(base.map((e) => e.tags.problem_id || NONE))].filter((p) => !S.problems.has(p));
  let rows = "";
  for (const [cat, ps] of [...cats.entries()].sort()) {
    rows += `<tr class="cat"><th colspan="${stagesPresent.length + 2}">${esc(categoryLabel(cat))}</th></tr>`;
    for (const p of ps.sort((a, b) => a.name.localeCompare(b.name))) rows += heatRow(p.id, p.name, p.status !== "validated");
  }
  if (extra.length) {
    rows += `<tr class="cat"><th colspan="${stagesPresent.length + 2}">Untagged / outside catalog</th></tr>`;
    for (const p of extra) rows += heatRow(p, p === NONE ? "(untagged)" : p, false);
  }
  function heatRow(pid, name, unsupported) {
    let total = 0;
    const cells = stagesPresent.map((s) => {
      const c = counts.get(pid + "|" + s) || 0;
      total += c;
      const q = bucket(c, max);
      return `<td class="cell ${q ? "q" + q : "z"}" data-heat="${esc(pid)}|${s}">${c || "·"}</td>`;
    }).join("");
    return `<tr class="${unsupported ? "unsupported" : ""}"><th title="${unsupported ? "No validated backend: examples should be refusals" : ""}">${esc(name)}${unsupported ? " ⊘" : ""}</th>${cells}<td class="total">${total || ""}</td></tr>`;
  }
  const ramp = [1, 2, 3, 4, 5, 6, 7].map((q) => `<span class="sw q${q}"></span>`).join("");
  const heat = `<div class="cov-section"><h2>Problem × stage coverage</h2>
    <p class="desc">Rows are all ${S.problems.size} catalog problems; ⊘ marks problems with no validated backend (examples should teach refusal). Click a cell to browse those examples.</p>
    <div class="legend-ramp">fewer ${ramp} more (log scale) · <span class="sw" style="box-shadow:inset 0 0 0 1px var(--border)"></span> none</div>
    <table class="heat" style="margin-top:8px"><thead><tr><th></th>${stagesPresent.map((s) => `<th class="col" title="${esc(STAGE_HELP[s])}">${esc(STAGE_LABEL[s])}</th>`).join("")}<th class="col">Total</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;

  // implementations per operation
  const byOp = new Map();
  for (const e of base) {
    const op = e.tags.operation_id;
    if (!op) continue;
    if (!byOp.has(op)) byOp.set(op, new Map());
    const m = byOp.get(op);
    const b = e.tags.backend || NONE;
    m.set(b, (m.get(b) || 0) + 1);
  }
  const maxB = Math.max(1, ...[...byOp.values()].flatMap((m) => [...m.values()]));
  let bars = "";
  for (const op of [...byOp.keys()].sort()) {
    const m = byOp.get(op);
    const all = new Set([...backendsOf(op).map((b) => b.id), ...m.keys()]);
    bars += `<div class="bar-sub">${esc(op)}</div>`;
    for (const b of [...all].sort((x, y) => (m.get(y) || 0) - (m.get(x) || 0))) {
      const c = m.get(b) || 0;
      bars += `<div class="bar-row" data-impl="${esc(op)}|${esc(b)}"><span class="bl">${b === NONE ? '<span class="muted">auto / unknown</span>' : esc(b)}</span>
        <span class="bt"><span class="bf${c ? "" : " zero"}" style="width:${c ? Math.max(1, (100 * c) / maxB) : 0}%;display:block"></span></span><span class="bv">${c}</span></div>`;
    }
  }
  const impl = `<div class="cov-section"><h2>Implementations</h2><p class="desc">Examples per backend, including validated backends with no examples (0).</p><div class="barlist">${bars || '<span class="muted">No operation tags.</span>'}</div></div>`;

  // reused questions
  const qmap = new Map();
  for (const e of base) {
    const k = norm(e._q);
    if (!qmap.has(k)) qmap.set(k, { q: e._q, rows: 0, splits: new Set(), stages: new Set() });
    const r = qmap.get(k);
    r.rows++; r.splits.add(e.split); r.stages.add(e.schema);
  }
  const topQ = [...qmap.values()].sort((a, b) => b.rows - a.rows).slice(0, 15);
  const qtable = `<div class="cov-section"><h2>Most reused questions</h2><p class="desc">The same wording repeated across graphs and stages. Questions in both splits are marked; the held-out unit is the graph source.</p>
    <table class="plain"><thead><tr><th>Question</th><th class="num">Rows</th><th>Splits</th></tr></thead><tbody>
    ${topQ.map((r) => `<tr class="click" data-q="${esc(r.q)}"><td>${esc(r.q)}</td><td class="num">${r.rows}</td><td>${[...r.splits].sort().join(" + ")}${r.splits.size > 1 ? ' <span class="status-badge"><span class="ic info">i</span></span>' : ""}</td></tr>`).join("")}</tbody></table></div>`;

  // graph sources
  const lin = new Map();
  for (const e of base) {
    const k = e.lineage || "—";
    if (!lin.has(k)) lin.set(k, { rows: 0, splits: new Set() });
    lin.get(k).rows++; lin.get(k).splits.add(e.split);
  }
  const ltable = `<div class="cov-section"><h2>Graph sources</h2><table class="plain"><thead><tr><th>Source</th><th>Split</th><th class="num">Rows</th></tr></thead><tbody>
    ${[...lin.entries()].sort((a, b) => b[1].rows - a[1].rows).map(([k, v]) => `<tr class="click" data-lineage="${esc(k)}"><td>${esc(k)}</td><td>${[...v.splits].sort().join(" + ")}${v.splits.size > 1 ? ' <span class="status-badge"><span class="ic warning">!</span>mixed</span>' : ""}</td><td class="num">${v.rows}</td></tr>`).join("")}</tbody></table></div>`;

  host.innerHTML = `<div class="cov-head"><h1>Coverage</h1>
      <label class="toggle"><input type="checkbox" id="cov-filtered"${S.coverageFiltered ? " checked" : ""}> Only examples matching current filters (${S.visible.length.toLocaleString()})</label></div>
    ${tiles}<div class="cov-grid"><div>${heat}</div><div>${impl}${qtable}${ltable}</div></div>`;
}

// ------------------------------------------------------------------ changes view
async function renderChanges() {
  const host = $("#changes-view");
  try {
    const { changes } = await api("/api/changes");
    host.innerHTML = `<div class="cov-head"><h1>Changes</h1><span class="muted">${plural(changes.length, "changed example")} · saved in the workspace journal, written out on export</span>
      <span style="flex:1"></span><button class="btn primary" id="changes-export">Export new version</button></div>
      ${changes.length ? `<div class="cov-section"><table class="plain"><thead><tr><th>When</th><th>Change</th><th>Stage</th><th>Split</th><th>Question</th><th>Fields</th><th></th></tr></thead><tbody>
      ${changes.map((c) => `<tr class="click" data-open="${esc(c.id)}"><td class="muted">${c.updated_at ? esc(new Date(c.updated_at).toLocaleString()) : ""}</td>
        <td>${c.deleted ? '<span class="chip kind-deleted">deleted</span>' : `<span class="chip kind-${esc(c.kind)}">${esc(c.kind)}</span>`}</td>
        <td>${stageChip(c.schema)}</td><td>${esc(c.split)}</td><td>${esc(c.question)}</td><td class="muted">${esc(c.changed.join(", "))}</td>
        <td><button class="btn small" data-undo="${esc(c.id)}">${c.kind === "new" || c.kind === "clone" ? "Discard" : "Revert"}</button></td></tr>`).join("")}
      </tbody></table></div>` : '<div class="cov-section muted">No changes yet. Edit, tag, review, clone or add examples in Browse.</div>'}`;
  } catch (err) { fail(err); }
}

// ------------------------------------------------------------------ graphs: picker shared by the builder and the graph dialog
// A conversation replays on one graph: a graph already in this dataset, a small
// graph from the pipeline's case library, or an upload (checked by the agent's
// own ingestion). Domains come from the catalog's domain profiles.
async function loadGraphs(force = false) {
  if (S.graphs && !force) return S.graphs;
  try { S.graphs = await api("/api/graphs"); } catch (err) { fail(err); S.graphs = { dataset: [], library: [] }; }
  return S.graphs;
}
function graphPickerHtml(sel = {}) {
  const g = S.graphs || { dataset: [], library: [] };
  const opt = (value, label, on) => `<option value="${esc(value)}"${on ? " selected" : ""}>${esc(label)}</option>`;
  const desc = (x) => `${x.name || x.id}${x.vertices != null ? ` · ${x.vertices} records · ${x.edges} links` : ""}${x.directed ? " · directed" : ""}`;
  return `<div class="graph-picker">
    <div class="form-grid gp-grid">
      <label>Domain<select data-gp="domain">${S.meta.catalog.domains.map((d) => opt(d.id, d.name, d.id === (sel.domain_id || "general"))).join("")}</select></label>
      <label class="gp-graph">Graph<select data-gp="graph"><option value="">${S.graphs ? "Choose a graph…" : "Loading graphs…"}</option>
        ${g.dataset.length ? `<optgroup label="In this dataset">${g.dataset.map((x) => opt(`own:${x.id}`, desc(x), sel.pick === `own:${x.id}`)).join("")}</optgroup>` : ""}
        ${g.library.length ? `<optgroup label="Case library: small graphs from pipeline cases">${g.library.map((x) => opt(`lib:${x.id}`, desc(x) + (x.attachments?.length ? ` · with ${x.attachments.join(", ")}` : ""), sel.pick === `lib:${x.id}`)).join("")}</optgroup>` : ""}
      </select></label>
    </div>
    <details class="gp-upload"><summary>Upload a graph…</summary>
      <div class="form-grid">
        <label>Name<input data-gp="up-name" placeholder="optional"></label>
        <label>File: a GraphMine .json graph, or a .csv / .tsv edge list<input type="file" data-gp="up-file" accept=".json,.csv,.tsv,.txt"></label>
        <label class="check"><input type="checkbox" data-gp="up-directed"> Links are directed</label>
      </div>
      <button type="button" class="btn small" data-gp-act="upload">Upload and use</button>
    </details>
  </div>`;
}
// The picked graph as an id in this dataset; a library graph is copied in first.
async function resolvePickedGraph(pick) {
  if (!pick) return null;
  if (pick.startsWith("own:")) return pick.slice(4);
  const r = await api("/api/graphs/use", { id: pick.slice(4) });
  await loadGraphs(true);
  return r.graph.id;
}
async function uploadPickedGraph(root) {
  const file = root.querySelector('[data-gp="up-file"]').files[0];
  if (!file) { toast("Choose a file to upload", true); return null; }
  try {
    const r = await api("/api/graphs/upload", {
      name: root.querySelector('[data-gp="up-name"]').value, filename: file.name, content: await file.text(),
      directed: root.querySelector('[data-gp="up-directed"]').checked,
    });
    await loadGraphs(true);
    toast(`Uploaded ${r.graph.name}: ${r.graph.vertices} records, ${r.graph.edges} links`);
    return `own:${r.graph.id}`;
  } catch (err) { fail(err); return null; }
}

let graphDialog = null;
async function openGraphDialog(group) {
  const sum = S.conversations[group] || {};
  graphDialog = { group, domain_id: sum.settings?.domain_id || "general", pick: sum.settings?.graph ? `own:${sum.settings.graph.id}` : "" };
  $("#graph-body").innerHTML = `<p class="muted" style="margin:0">The agent replays this conversation on the graph, with the domain's vocabulary. Changing either makes the model inputs out of date until the next build.</p>${graphPickerHtml(graphDialog)}`;
  $("#graph-dialog").showModal();
  await loadGraphs();
  $("#graph-body").innerHTML = `<p class="muted" style="margin:0">The agent replays this conversation on the graph, with the domain's vocabulary. Changing either makes the model inputs out of date until the next build.</p>${graphPickerHtml(graphDialog)}`;
}
async function submitGraphDialog(ev) {
  ev.preventDefault();
  const root = $("#graph-body");
  graphDialog.domain_id = root.querySelector('[data-gp="domain"]').value;
  graphDialog.pick = root.querySelector('[data-gp="graph"]').value;
  if (!graphDialog.pick) return toast("Choose a graph", true);
  try {
    const graph_id = await resolvePickedGraph(graphDialog.pick);
    const r = await api("/api/conversation/settings", { group: graphDialog.group, domain_id: graphDialog.domain_id, graph_id });
    applyConversations({ [graphDialog.group]: r.summary });
    $("#graph-dialog").close();
    refreshAll();
    renderDetail();
    buildConversation(graphDialog.group);
  } catch (err) { fail(err); }
}

// ------------------------------------------------------------------ templates
// A real output to start from: this dataset first, then the others (a dataset
// made in the studio has nothing of its own to copy at first).
async function findTemplate(schema, want, op) {
  const live = S.examples.filter((e) => !e.deleted && e.schema === schema && e.kind !== "new");
  const fits = (e) => (want === "ask" ? asksForInfo(e.output) : want === "supported" ? e.output?.supported === true
    : want === "ready" ? e.output?.status === "ready" : true);
  const ex = live.find((e) => fits(e) && (!op || e.tags.operation_id === op)) || live.find(fits);
  if (ex) return { output: ex.output, source: ex.id };
  return api("/api/template", { schema, want, operation: op || null });
}
const WANT_FOR = { askRoute: "ask", route: "supported", plan: "ready" };
async function loadNextTemplate() {
  const ed = S.editing;
  const c = S.convs.get(ed.key);
  try {
    const t = await findTemplate(ed.schema, ed.schema === "RouteDecision" ? "supported" : ed.schema === "PlanDraft" ? "ready" : "any", c.tagged.tags.operation_id);
    $("#next-editor").value = ed.text = JSON.stringify(t.output, null, 2);
    $("#next-editor").dispatchEvent(new Event("input"));
    toast(`Template copied from ${t.source}`);
  } catch { toast(`No dataset has a ${STAGE_LABEL[ed.schema]} example to copy from`, true); }
}

// ------------------------------------------------------------------ add conversation
// The builder lays a conversation out in chat order; a Qwen output left empty is
// skipped. Text the agent derives (the clarification question, the analyst's
// request, GraphMine's replies) is not typed: with a graph, building the
// conversation fills it in from the agent itself. Opened from a conversation, it
// offers only the steps that conversation is missing, plus follow-ups.
let B = null;
const BSCHEMA = { askRoute: "RouteDecision", route: "RouteDecision", plan: "PlanDraft", answer: "GroundedNarrative", check: "TurnDecision" };
const FU_ID = /^fu(\d+)-(\w+)$/;
const bSchema = (id) => BSCHEMA[id.match(FU_ID)?.[2] || id];
const bGet = (id) => { const m = id.match(FU_ID); return (m ? B.followups[+m[1]]?.[m[2]] : B[id]) ?? ""; };
const bSet = (id, v) => { const m = id.match(FU_ID); if (m) B.followups[+m[1]][m[2]] = v; else B[id] = v; };
const bTurn = (role, text, status = null) => ({ role, text, status, payload: null });
const newFollowup = () => ({ msg: "", check: "", route: "", plan: "", answer: "" });
const engineOn = () => !!S.meta?.engine?.available;

function openAdd(c = null) {
  if (S.editing && !confirm("Discard unsaved edits?")) return;
  S.editing = null;
  const live = c ? convSteps(c).filter((e) => !e.deleted) : [];
  const main = live.filter((e) => e._section === "main");
  const reply = main.find((e) => e._phase === 1);
  const priorReply = live.find((e) => e._section === "followup" && e.turns.length)?.turns.filter((t) => t.role === "assistant").pop();
  const sum = c ? S.conversations[c.key] : null;
  B = {
    conv: c?.key || null,
    question: c ? c.question : "",
    // After a clarification the reply is what the rest of the conversation answers.
    mainQ: reply ? userMessage(reply) : c?.question || "",
    ctx: reply ? reply.turns : [],
    split: c ? c.split : "train",
    tags: { problem_id: "", operation_id: "", backend: "", ...(c ? c.tagged.tags : {}) },
    // A graph is chosen here for a new conversation, or for one that has none yet.
    graph: c && (sum?.settings || sum?.case) ? null : { domain_id: "general", pick: "" },
    clarify: false, askRoute: "", reply: "",
    route: "", plan: "", answer: "",
    earlierReply: priorReply?.text || "",
    followups: [],
    show: { route: !main.some((e) => e.schema === "RouteDecision"), plan: !main.some((e) => e.schema === "PlanDraft"),
      answer: !live.some((e) => e.schema === "GroundedNarrative") },
    issues: {},
    preview: null,
  };
  if (c && !B.show.route && !B.show.plan && !B.show.answer) B.followups.push(newFollowup());
  $("#add-title").textContent = c ? "Add to this conversation" : "Add conversation";
  renderBuilder();
  $("#add-dialog").showModal();
  $(c ? "#add-body textarea" : '[data-btext="question"]')?.focus();
  if (B.graph && engineOn()) loadGraphs().then(() => { if (B && $("#add-dialog").open) renderBuilder(); });
}

function renderBuilder() {
  const conv = !!B.conv;
  const text = (id, who, title, placeholder, rows = 2) => `<div class="cb-step"><div class="avatar ${who === "U" ? "user" : "assistant"}">${who}</div>
    <div class="cb-body"><div class="cb-title">${esc(title)}</div>
      <textarea rows="${rows}" data-btext="${id}" placeholder="${esc(placeholder)}">${esc(bGet(id))}</textarea></div></div>`;
  const json = (id, title = "", hint = "", extra = "") => `<div class="cb-step"><div class="avatar assistant">Q</div>
    <div class="cb-body"><div class="cb-title">${stageChip(bSchema(id))}${title ? `<span class="muted">${esc(title)}</span>` : ""}<span class="spacer"></span>
        ${extra}<button type="button" class="link-btn" data-btpl="${id}">Load template</button></div>
      ${hint ? `<div class="cb-hint">${esc(hint)}</div>` : ""}
      <textarea class="mono" rows="5" spellcheck="false" data-bjson="${id}" placeholder="Expected Qwen output (JSON). Leave empty to skip this step.">${esc(bGet(id))}</textarea>
      <div data-bissues="${id}">${issuesHtml(B.issues[id])}</div></div></div>`;
  const tagSelect = (key, label, html) => `<label>${label}<select data-btag="${key}">${html}</select></label>`;
  const parts = [`<div class="callout">Fill in the steps in the order the chat happens; a Qwen step left empty is skipped.
    ${engineOn() ? "With a graph, the studio replays the conversation through the GraphMine agent: each step gets the model input production would send, text the agent derives is filled in, and once GraphMine has run, the analyst answer is checked against the computed facts. You can also add just the first steps now and the rest later, one step at a time."
      : "The GraphMine agent is not available here, so steps written now have no model input and export to <code>needs-context.jsonl</code>."}</div>`];
  if (conv) {
    parts.push(`<div class="cb-context"><span class="chip split ${esc(B.split)}">${esc(B.split)}</span>
      ${B.tags.operation_id ? `<span class="tag-pill">${esc(B.tags.operation_id)}</span>` : ""}<span class="muted">New steps use this conversation's split and tags.</span></div>`);
  } else {
    parts.push(`<div class="form-grid">
      ${tagSelect("problem_id", "Problem", problemOptions(B.tags.problem_id, "").replace("Auto: (none)", "(none)"))}
      ${tagSelect("operation_id", "Operation", operationOptions(B.tags.operation_id, "", B.tags.problem_id).replace("Auto: (none)", "(none)"))}
      ${tagSelect("backend", "Implementation", backendOptions(B.tags.backend, "", B.tags.operation_id).replace("Auto: (none)", "(auto)"))}
      <label>Split<select id="b-split">${["train", "validation"].map((s) => `<option${s === B.split ? " selected" : ""}>${s}</option>`).join("")}</select></label></div>`);
  }
  if (B.graph && engineOn()) parts.push(`<div class="cb-section"><div class="cb-title"><b>Graph and domain</b><span class="muted">the data the agent replays the conversation on</span></div>${graphPickerHtml(B.graph)}</div>`);
  const t = [];
  if (conv) {
    t.push(`<div class="cb-step"><div class="avatar user">U</div><div class="cb-body"><div class="cb-title">User · question</div>
      <div class="cb-quote">${esc(B.question)}</div>${B.mainQ !== B.question ? `<div class="cb-title">User · reply to the clarification question</div><div class="cb-quote">${esc(B.mainQ)}</div>` : ""}</div></div>`);
  } else {
    t.push(text("question", "U", "User · question", "Plain-English question", 3));
    t.push(`<label class="check cb-toggle"><input type="checkbox" id="b-clarify"${B.clarify ? " checked" : ""}> Qwen asks for clarification first</label>`);
    if (B.clarify) {
      t.push(json("askRoute", "asks for more information", "supported: false, with the open question in ambiguity or missing_information."));
      let shown = "";
      try { shown = B.askRoute.trim() ? derivedClarification(JSON.parse(B.askRoute)) : ""; } catch { shown = ""; }
      t.push(`<div class="cb-step"><div class="avatar assistant">G</div><div class="cb-body"><div class="cb-title">GraphMine · clarification question shown to the user <span class="muted">(derived from the Understanding output above)</span></div>
        <div class="cb-quote">${shown ? esc(shown) : '<span class="muted">Appears once the Understanding output asks something.</span>'}</div></div></div>`);
      t.push(text("reply", "U", "User · reply to the clarification question", "The clarified request"));
    }
  }
  const canPreview = !conv && engineOn() && B.graph?.pick && !B.clarify;
  if (B.show.route) {
    t.push(json("route", "", "", canPreview ? '<button type="button" class="link-btn" data-bact="preview">Show model input</button>' : ""));
    if (B.preview) t.push(`<details class="ns-input cb-preview" open><summary>Understanding · model input the agent sends for this question</summary><div class="json-tree">${jsonTree(JSON.parse(B.preview.at(-1).content))}</div></details>`);
  }
  if (B.show.plan) t.push(json("plan"));
  if (B.show.answer) {
    t.push(`<div class="run-divider"><span>⚙ GraphMine runs the plan; the analyst gets the computed result and the objective from Understanding</span></div>`);
    t.push(json("answer", "", engineOn() ? "Easiest after GraphMine has run: the conversation then shows the facts to cite. Leave empty to add it later." : "Leave empty to add it later."));
  }
  t.push(`<div class="thread-section"><div class="ts-title">Follow-up messages</div>
    <div class="ts-desc">Optional. Each one is an alternative next message after the first answer: the follow-up check decides whether to explain, analyze again or clarify.</div></div>`);
  if (B.followups.length) t.push(text("earlierReply", "G", "GraphMine · reply the user saw before the follow-ups", B.graph?.pick || (conv && S.conversations[B.conv]?.replayable) ? "Optional: building the conversation replaces it with the agent's real reply" : "e.g. Found 4 matching groups of entities."));
  B.followups.forEach((_, i) => {
    t.push(`<div class="branch"><div class="cb-title"><b>Follow-up ${i + 1}</b><span class="spacer"></span>
        <button type="button" class="link-btn" data-bfu-del="${i}">Remove</button></div>
      ${text(`fu${i}-msg`, "U", "User · follow-up message", "e.g. Explain what this result means")}
      ${json(`fu${i}-check`)}
      ${json(`fu${i}-route`, "optional", "When the check says analyze (or clarify), the planner runs again: Understanding, then Planning.")}
      ${json(`fu${i}-plan`, "optional")}
      ${json(`fu${i}-answer`, "optional")}</div>`);
  });
  t.push(`<button type="button" class="btn small cb-add-fu" data-bact="add-fu">+ Add follow-up message</button>`);
  parts.push(`<div class="cb-thread">${t.join("")}</div>`);
  $("#add-body").innerHTML = parts.join("");
  renderAddSummary();
}

// The rows this builder would create, in chat order, plus anything blocking the save.
function builderSteps() {
  const problems = [];
  const steps = [];
  const filled = [];
  const tags = Object.fromEntries(Object.entries(B.tags).filter(([, v]) => v));
  const parse = (id) => {
    const raw = bGet(id).trim();
    if (!raw) return undefined;
    filled.push(id);
    try { return JSON.parse(raw); } catch { problems.push(`${STAGE_LABEL[bSchema(id)]}: the output is not valid JSON.`); return undefined; }
  };
  const planner = (schema, message, turns, output) => ({ adapter: "planner", schema, split: B.split, tags, turns, output,
    prompt_fields: [{ path: "message", label: "User question", value: message }] });
  const analyst = (question, request, turns, output) => ({ adapter: "analyst", schema: "GroundedNarrative", split: B.split, tags, turns, output,
    prompt_fields: [{ path: "answer.question", label: "Original user question", value: question }, { path: "user_message", label: "Request to the analyst", value: request }] });
  let mainQ = B.mainQ;
  let ctx = B.ctx;
  if (!B.conv) {
    mainQ = B.question.trim();
    if (!mainQ) problems.push("Enter the user question.");
    if (B.clarify) {
      const ask = parse("askRoute");
      if (ask !== undefined) {
        steps.push(planner("RouteDecision", mainQ, [], ask));
        if (!asksForInfo(ask)) problems.push("The first Understanding must ask for more information (ambiguity or missing_information).");
      }
      if (!B.reply.trim()) problems.push("Write the user's reply to the clarification question.");
      ctx = [bTurn("user", mainQ), bTurn("assistant", derivedClarification(ask), "needs_information")];
      mainQ = B.reply.trim();
    }
  }
  for (const id of ["route", "plan"]) {
    const output = B.show[id] ? parse(id) : undefined;
    if (output !== undefined) steps.push(planner(bSchema(id), mainQ, ctx, output));
  }
  const answer = B.show.answer ? parse("answer") : undefined;
  if (answer !== undefined) steps.push(analyst(mainQ, mainQ, [], answer));
  // "answered" marks the reply as following a finished answer until a build supplies the real one.
  const replayed = !!(B.graph?.pick || (B.conv && S.conversations[B.conv]?.replayable));
  const prior = B.earlierReply.trim() || (replayed ? "(GraphMine's reply: filled in when the conversation is built)" : "");
  const fuTurns = [...ctx, bTurn("user", mainQ), bTurn("assistant", prior, "answered")];
  B.followups.forEach((f, i) => {
    const outs = ["check", "route", "plan", "answer"].map((k) => [k, parse(`fu${i}-${k}`)]).filter(([, v]) => v !== undefined);
    if (!outs.length) return;
    if (!f.msg.trim()) problems.push(`Follow-up ${i + 1}: enter the user's message.`);
    if (!prior) problems.push("Enter GraphMine's reply the user saw before the follow-ups (or choose a graph so the build fills it in).");
    for (const [k, output] of outs) {
      steps.push(k === "answer" ? analyst(mainQ, f.msg.trim(), fuTurns, output)
        : planner({ check: "TurnDecision", route: "RouteDecision", plan: "PlanDraft" }[k], f.msg.trim(), fuTurns, output));
    }
  });
  const invalid = filled.filter((id) => (B.issues[id] || []).some((i) => i.level === "error")).length;
  return { steps, problems: [...new Set(problems)], invalid };
}

function renderAddSummary() {
  const r = builderSteps();
  const names = r.steps.map((s) => STAGE_LABEL[s.schema]);
  $("#add-summary").textContent = !r.steps.length ? "No Qwen outputs yet"
    : `${plural(r.steps.length, "step")}: ${names.join(" → ")}`;
  $("#add-submit").textContent = B.conv ? `Add ${plural(r.steps.length, "step")}` : "Add conversation";
}

const bValidators = new Map();
function bValidate(id) {
  if (!bValidators.has(id)) bValidators.set(id, debounce(() => validateBuilderField(id), 300));
  bValidators.get(id)();
}
async function validateBuilderField(id) {
  if (!B) return;
  const raw = bGet(id).trim();
  let issues = [];
  if (raw) {
    let output;
    try { output = JSON.parse(raw); } catch (err) { issues = [{ level: "error", message: "Invalid JSON: " + err.message }]; }
    if (!issues.length) {
      try {
        const r = await api("/api/validate", { schema: bSchema(id), output, prompts: [{ value: B.question || B.mainQ || "x" }], tags: B.tags });
        issues = r.issues.filter((i) => i.field !== "context" && i.field !== "prompts");
      } catch (err) { fail(err); return; }
    }
  }
  if (!B) return;
  B.issues[id] = issues;
  const host = $(`[data-bissues="${id}"]`);
  if (host) host.innerHTML = issuesHtml(issues);
  if (id === "askRoute" && B.clarify) renderBuilder();
  else renderAddSummary();
}

async function builderTemplate(id) {
  const schema = bSchema(id);
  try {
    const t = await findTemplate(schema, WANT_FOR[id.replace(FU_ID, "$2")] || "any", B.tags.operation_id);
    if (!B) return;
    bSet(id, JSON.stringify(t.output, null, 2));
    const area = $(`[data-bjson="${id}"]`);
    if (area) area.value = bGet(id);
    bValidate(id);
    renderAddSummary();
    toast(`Template copied from ${t.source}`);
  } catch { toast(`No dataset has a ${STAGE_LABEL[schema]} example to copy from`, true); }
}

async function previewUnderstanding() {
  const q = B.question.trim();
  if (!q) return toast("Enter the question first", true);
  try {
    const graph_id = await resolvePickedGraph(B.graph.pick);
    B.graph.pick = `own:${graph_id}`;
    const r = await api("/api/preview-understanding", { question: q, domain_id: B.graph.domain_id, graph_id });
    if (!r.messages) return toast((r.events || [])[0]?.message || "The agent did not ask for Understanding", true);
    B.preview = r.messages;
    renderBuilder();
  } catch (err) { fail(err); }
}

function removeFollowup(i) {
  B.followups.splice(i, 1);
  const moved = {};
  for (const [k, v] of Object.entries(B.issues)) {
    const m = k.match(FU_ID);
    if (!m || +m[1] < i) moved[k] = v;
    else if (+m[1] > i) moved[`fu${+m[1] - 1}-${m[2]}`] = v;
  }
  B.issues = moved;
  renderBuilder();
}

async function submitAdd(ev) {
  ev.preventDefault();
  const r = builderSteps();
  if (r.problems.length) return toast(r.problems[0], true);
  if (!r.steps.length) return toast("Fill in at least one Qwen output", true);
  if (r.invalid && !confirm(`${plural(r.invalid, "step")} ${r.invalid === 1 ? "does" : "do"} not pass validation. Add anyway?`)) return;
  try {
    const graph_id = B.graph?.pick ? await resolvePickedGraph(B.graph.pick) : null;
    const res = await api("/api/create-conversation", { group: B.conv, steps: r.steps });
    for (const ex of res.examples) applyExample(ex);
    applyIssues(res.issues);
    applyConversations(res.conversations);
    if (graph_id) {
      const s = await api("/api/conversation/settings", { group: res.group, domain_id: B.graph.domain_id, graph_id });
      applyConversations({ [res.group]: s.summary });
    }
    $("#add-dialog").close();
    if (!B.conv) { S.facetSel = {}; S.query = ""; $("#search").value = ""; }
    B = null;
    refreshAll();
    if (S.mode === "conv") selectConv(res.group, { stepId: res.examples[0].id, scroll: true, reveal: true });
    else select(res.examples[0].id, { scroll: true });
    toast(`${plural(res.examples.length, "step")} added${graph_id ? "; building the model inputs…" : ""}`);
    autoBuild(res.group);
  } catch (err) { fail(err); }
}

// ------------------------------------------------------------------ dataset settings (datasets made in the studio)
function openDatasetSettings() {
  const d = S.dataset;
  if (d?.layout !== "studio") return;
  $("#ds-name").value = d.name || "";
  $("#ds-description").value = d.description || "";
  $("#ds-location").textContent = `Folder: ${S.meta.data_root}/${d.path}`;
  $("#dataset-settings-dialog").showModal();
}
async function saveDatasetSettings(ev) {
  ev.preventDefault();
  try {
    const r = await api("/api/dataset/update", { key: S.dataset.key, name: $("#ds-name").value, description: $("#ds-description").value });
    S.datasets = r.datasets;
    S.dataset = r.dataset;
    $("#dataset-select").innerHTML = datasetOptions(S.datasets);
    $("#dataset-select").value = S.dataset.key;
    $("#dataset-settings-dialog").close();
    renderStatus();
    toast("Dataset updated");
  } catch (err) { fail(err); }
}
async function deleteDataset() {
  const d = S.dataset;
  if (!confirm(`Delete "${d.name}"? Its folder moves to studio-datasets/.deleted/, so it can be restored by moving it back.`)) return;
  try {
    const r = await api("/api/dataset/delete", { key: d.key });
    $("#dataset-settings-dialog").close();
    S.datasets = r.datasets;
    $("#dataset-select").innerHTML = datasetOptions(S.datasets);
    resetForDataset();
    if (r.current) await loadExamples(); else showNoDataset();
    toast(`Deleted. Moved to ${r.moved_to}`);
  } catch (err) { fail(err); }
}

// ------------------------------------------------------------------ export dialog
function openExport() {
  const live = S.examples.filter((e) => !e.deleted);
  const c = (f) => live.filter(f).length;
  const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "").replace(/^(\d{8})(\d{4})$/, "$1-$2");
  $("#export-name").value = `studio-${stamp}`;
  $("#export-result").innerHTML = "";
  // A step written here becomes a training row once its conversation's build is current.
  const replayed = (e) => e.kind === "new" && S.conversations[e.group]?.fresh && S.conversations[e.group]?.captured?.includes(e.id);
  const written = c((e) => e.kind === "new");
  $("#export-summary").innerHTML = `${plural(new Set(live.map((e) => e.group)).size, "conversation")}, ${plural(live.length, "step")} (each step is its own row) · ${c((e) => e.kind === "edited")} edited · ${c((e) => e.kind === "annotated")} annotated only · ${c((e) => e.kind === "clone")} duplicated
    · ${written} written here: ${c(replayed)} with current model input (training rows), ${written - c(replayed)} without (needs-context.jsonl)
    · ${S.examples.filter((e) => e.deleted).length} deleted · ${c((e) => e.review === "approved")} approved · ${c((e) => e.review === "rejected")} rejected
    ${c((e) => e._issue === "error") ? `<br><span class="status-badge"><span class="ic critical">✕</span>${c((e) => e._issue === "error")} examples have validation errors and would be exported as they are.</span>` : ""}`;
  $("#export-dialog").showModal();
}
async function submitExport(ev) {
  ev.preventDefault();
  const btn = $("#export-submit");
  btn.disabled = true;
  try {
    const r = await api("/api/export", { name: $("#export-name").value, exclude_rejected: $("#export-exclude-rejected").checked, approved_only: $("#export-approved-only").checked });
    const files = Object.entries(r.counts).filter(([k]) => k.startsWith("sft/")).map(([k, v]) => `${k}: ${v}`);
    if (r.counts.needs_context) files.push(`needs-context.jsonl: ${r.counts.needs_context} (written here, no current model input)`);
    for (const [k, label] of [["skipped_rejected", "rejected, left out"], ["skipped_not_approved", "not approved, left out"], ["skipped_deleted", "deleted"]]) {
      if (r.counts[k]) files.push(`${r.counts[k]} ${label}`);
    }
    $("#export-result").innerHTML = `<div class="callout"><b>Exported.</b><br><code>${esc(r.path)}</code><br>${esc(files.join(" · ") || "Nothing to write")}
      ${r.warning_count ? `<br><span class="status-badge"><span class="ic warning">!</span>${r.warning_count} warning(s); see manifest.json</span>` : ""}</div>`;
    toast("Export written");
  } catch (err) { fail(err); } finally { btn.disabled = false; }
}

// ------------------------------------------------------------------ misc
function refreshLabelOptions() {
  const labels = [...new Set(S.examples.flatMap((e) => e.labels))].sort();
  $("#label-options").innerHTML = labels.map((l) => `<option value="${esc(l)}">`).join("");
}
function fillBulkSelects() {
  $("#bulk-problem").innerHTML = '<option value="">Problem…</option>' + problemOptions("", "").replace(/<option value="">[^<]*<\/option>/, "") + '<option value="__clear__">↺ Reset to auto</option>';
  $("#bulk-operation").innerHTML = '<option value="">Operation…</option>' + [...S.operations.keys()].sort().map((o) => `<option value="${esc(o)}">${esc(o)}</option>`).join("") + '<option value="__clear__">↺ Reset to auto</option>';
  $("#bulk-backend").innerHTML = '<option value="">Implementation…</option>' + [...S.operations.values()].sort((a, b) => a.id.localeCompare(b.id))
    .map((o) => `<optgroup label="${esc(o.id)}">${o.backends.map((b) => `<option value="${esc(b.id)}">${esc(b.name)}</option>`).join("")}</optgroup>`).join("") + '<option value="__clear__">↺ Reset to auto</option>';
}
function setView(v) {
  if (S.editing && v !== "browse") { if (!confirm("Discard unsaved edits?")) return; S.editing = null; }
  S.view = v;
  $$(".views button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  $("#browse-view").hidden = v !== "browse";
  $("#coverage-view").hidden = v !== "coverage";
  $("#changes-view").hidden = v !== "changes";
  if (v === "coverage") renderCoverage();
  if (v === "changes") renderChanges();
}
function applyTheme(t) {
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
}
function toggleTheme() {
  const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = cur === "dark" ? "light" : "dark";
  applyTheme(next);
  store.set("theme", next);
}
function clearFilters() {
  S.facetSel = {};
  S.facetFilter = {};
  S.query = "";
  $("#search").value = "";
  refreshAll();
}
async function copyText(text, msg) {
  try { await navigator.clipboard.writeText(text); toast(msg); } catch { toast("Clipboard unavailable", true); }
}

// ------------------------------------------------------------------ events
function bind() {
  $("#search").addEventListener("input", debounce((ev) => { S.query = ev.target.value; S.rendered = 0; refreshAll(); }, 120));
  $("#dataset-select").addEventListener("change", async (ev) => {
    if (ev.target.value === NEW_DATASET) { ev.target.value = S.dataset?.key || ""; openNewDataset(); return; }
    if (S.editing && !confirm("Discard unsaved edits?")) { ev.target.value = S.dataset?.key || ""; return; }
    try {
      $("#status-strip").innerHTML = "<span>Indexing dataset…</span>";
      await api("/api/open", { key: ev.target.value });
      resetForDataset();
      await loadExamples();
    } catch (err) { fail(err); }
  });
  $("#dataset-form").addEventListener("submit", (ev) => { if (ev.submitter?.value === "default") submitNewDataset(ev); });
  document.addEventListener("click", (ev) => {
    if (ev.target.closest("[data-empty-add]")) openAdd();
    if (ev.target.closest("[data-new-dataset]")) openNewDataset();
  });
  $$(".views button").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
  $("#add-btn").addEventListener("click", () => openAdd());
  $("#export-btn").addEventListener("click", openExport);
  $("#theme-btn").addEventListener("click", toggleTheme);
  $("#help-btn").addEventListener("click", () => $("#help-dialog").showModal());
  $("#clear-filters").addEventListener("click", clearFilters);
  $("#facets-toggle").addEventListener("click", () => $("#facets").classList.toggle("open"));
  $$("#mode-seg button").forEach((b) => {
    b.classList.toggle("on", b.dataset.mode === S.mode);
    b.addEventListener("click", () => setMode(b.dataset.mode));
  });
  $("#deleted-toggle").checked = S.showDeleted;
  $("#sort-select").value = S.sort;
  $("#deleted-toggle").addEventListener("change", (ev) => {
    S.showDeleted = ev.target.checked;
    store.set("showDeleted", S.showDeleted);
    refreshAll();
    if (S.mode === "conv") { syncDrafts(); renderDetail(); }
  });
  $("#sort-select").addEventListener("change", (ev) => { S.sort = ev.target.value; store.set("sort", S.sort); S.rendered = 0; refreshAll(); });
  $("#select-all").addEventListener("change", (ev) => {
    selectableIds().forEach((id) => (ev.target.checked ? S.selected.add(id) : S.selected.delete(id)));
    renderList(true);
  });

  // facets
  $("#facet-groups").addEventListener("change", (ev) => {
    const cb = ev.target.closest("input[data-facet]");
    if (!cb) return;
    const set = S.facetSel[cb.dataset.facet] || (S.facetSel[cb.dataset.facet] = new Set());
    cb.checked ? set.add(cb.value) : set.delete(cb.value);
    S.rendered = 0;
    refreshAll();
  });
  $("#facet-groups").addEventListener("input", debounce((ev) => {
    const inp = ev.target.closest("[data-ffilter]");
    if (!inp) return;
    S.facetFilter[inp.dataset.ffilter] = inp.value;
    renderFacets();
  }, 120));
  $("#facet-groups").addEventListener("click", (ev) => {
    const more = ev.target.closest("[data-more]");
    if (more) { S.facetShowAll[more.dataset.more] = !S.facetShowAll[more.dataset.more]; renderFacets(); }
  });

  // list
  $("#list").addEventListener("click", (ev) => {
    if (ev.target.id === "empty-clear") return clearFilters();
    const cb = ev.target.closest("input[data-sel]");
    if (cb) {
      cb.checked ? S.selected.add(cb.dataset.sel) : S.selected.delete(cb.dataset.sel);
      renderBulkbar();
      syncSelectAll();
      return;
    }
    const ccb = ev.target.closest("input[data-csel]");
    if (ccb) {
      convIds(ccb.dataset.csel).forEach((id) => (ccb.checked ? S.selected.add(id) : S.selected.delete(id)));
      renderBulkbar();
      syncSelectAll();
      return;
    }
    const crow = ev.target.closest(".row[data-conv]");
    if (crow) { selectConv(crow.dataset.conv); return; }
    const row = ev.target.closest(".row");
    if (row) select(row.dataset.id);
  });

  // bulk
  const bulkSel = (id, fn) => $(id).addEventListener("change", async (ev) => {
    const v = ev.target.value;
    if (!v) return;
    ev.target.value = "";
    await fn(v === "__clear__" ? null : v);
  });
  bulkSel("#bulk-problem", (v) => bulk({ tags: { problem_id: v } }, v ? `Problem → ${problemName(v)}` : "Problem tag reset"));
  bulkSel("#bulk-operation", (v) => bulk({ tags: { operation_id: v } }, v ? `Operation → ${v}` : "Operation tag reset"));
  bulkSel("#bulk-backend", (v) => bulk({ tags: { backend: v } }, v ? `Implementation → ${v}` : "Implementation tag reset"));
  bulkSel("#bulk-review", (v) => bulk({ review: v || "unreviewed" }, `Review → ${REVIEW[v || "unreviewed"].label}`));
  bulkSel("#bulk-split", (v) => bulk({ split: v }, `Moved to ${v}`));
  $("#bulk-label").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && ev.target.value.trim()) { bulk({ labels_add: [ev.target.value.trim()] }, `Label "${ev.target.value.trim()}" added`); ev.target.value = ""; }
  });
  $("#bulk-delete").addEventListener("click", () => { if (confirm(`Delete ${S.selected.size} example(s)? They stay restorable until export.`)) bulk({ deleted: true }, "Deleted"); });
  $("#bulk-restore").addEventListener("click", () => bulk({ deleted: false }, "Restored"));
  $("#bulk-clear").addEventListener("click", () => { S.selected.clear(); renderList(true); });

  // detail
  $("#detail").addEventListener("click", async (ev) => {
    const t = ev.target;
    const tab = t.closest("[data-tab]");
    if (tab) { S.tab = tab.dataset.tab; renderDetail(); return; }
    const go = t.closest("[data-goto]");
    if (go) { select(go.dataset.goto, { scroll: true, rowView: S.rowView }); return; }
    const om = t.closest("[data-omode]");
    if (om) { S.outputMode = om.dataset.omode; store.set("outputMode", S.outputMode); syncDrafts(); renderDetail(); return; }
    // conversation view: steps, per-step actions, conversation-wide review and labels
    const stepEl = t.closest("[data-step]");
    if (stepEl) focusStep(stepEl.dataset.step);
    const srev = t.closest("[data-sreview]");
    if (srev && stepEl) { update(stepEl.dataset.step, { review: srev.dataset.sreview }, `Step review → ${REVIEW[srev.dataset.sreview].label}`); return; }
    const sact = t.closest("[data-sact]");
    if (sact) {
      const id = sact.dataset.for || stepEl?.dataset.step;
      const se = S.byId.get(id);
      if (!se) return;
      switch (sact.dataset.sact) {
        case "edit": startEdit("output", id); break;
        case "edit-prompt": focusStep(id); startEdit("prompts", id); break;
        case "copy": copyText(JSON.stringify(se.output, null, 2), "Output JSON copied"); break;
        case "restore": update(id, { deleted: false }, "Step restored"); break;
        case "delete": update(id, { deleted: true }, "Step deleted (restorable until export)"); break;
        case "discard": if (confirm("Discard this step? It was written here, so this cannot be undone.")) revert([id], "Step discarded"); break;
        case "details":
          if (S.editing && S.editing.id !== id) { if (!confirm("Discard unsaved edits?")) return; S.editing = null; }
          S.currentId = id;
          S.rowView = true;
          S.tab = "conversation";
          renderDetail();
          $("#detail").scrollTop = 0;
          break;
      }
      return;
    }
    const crv = t.closest("[data-creview]");
    if (crv) { bulk({ review: crv.dataset.creview }, `Review → ${REVIEW[crv.dataset.creview].label}`, convLiveIds()); return; }
    const cul = t.closest("[data-cunlabel]");
    if (cul) { bulk({ labels_remove: [cul.dataset.cunlabel] }, `Label "${cul.dataset.cunlabel}" removed`, convLiveIds()); return; }
    const rv = t.closest("[data-review]");
    if (rv) { update(S.currentId, { review: rv.dataset.review }, `Review → ${REVIEW[rv.dataset.review].label}`); return; }
    const ul = t.closest("[data-unlabel]");
    if (ul) { const e = current(); update(e.id, { labels: e.labels.filter((l) => l !== ul.dataset.unlabel) }); return; }
    const act = t.closest("[data-act]")?.dataset.act;
    const e = current();
    if (!act || !e) return;
    switch (act) {
      case "back": document.body.classList.remove("detail-open"); break;
      case "prev": S.mode === "conv" && S.rowView ? moveStep(-1) : move(-1); break;
      case "next": S.mode === "conv" && S.rowView ? moveStep(1) : move(1); break;
      case "to-conv": backToConv(); break;
      case "open-conv": setMode("conv"); break;
      case "edit-convq": startEdit("convq"); break;
      case "save-convq": saveConvQuestion().catch(() => {}); break;
      case "copy-conv": copyText(S.convKey, "Conversation ID copied"); break;
      case "add-to-conv": openAdd(currentConv()); break;
      case "build": buildConversation(S.convKey); break;
      case "run": buildConversation(S.convKey, { run: true }); break;
      case "choose-graph": openGraphDialog(S.convKey); break;
      case "edit-ctx": startEdit("ctx", S.currentId, S.ctxTexts[+t.closest("[data-ctx]").dataset.ctx]); break;
      case "write-next": {
        const c = currentConv();
        if (S.editing && !confirm("Discard unsaved edits?")) break;
        S.editing = { kind: "next", key: c.key, schema: NEXT_SCHEMA[c.progress], text: "", ...(c.progress === "waiting_reply" ? { reply: "" } : {}) };
        renderDetail();
        $("#next-step")?.scrollIntoView({ block: "center" });
        $(c.progress === "waiting_reply" ? "#next-reply" : "#next-editor")?.focus();
        break;
      }
      case "next-template": loadNextTemplate(); break;
      case "save-next": saveNextStep(); break;
      case "conv-discard": {
        const ids = convLiveIds();
        if (confirm(`Discard all ${plural(ids.length, "step")} of this conversation? They were written here, so this cannot be undone.`)) revert(ids, "Conversation discarded");
        break;
      }
      case "conv-delete": {
        const ids = convLiveIds();
        if (confirm(`Delete all ${plural(ids.length, "step")} of this conversation? They stay restorable until export.`)) bulk({ deleted: true }, "Conversation deleted", ids);
        break;
      }
      case "conv-restore": bulk({ deleted: false }, "Conversation restored", currentConv().steps.map((x) => x.id)); break;
      case "conv-reset-tags": bulk({ tags: { problem_id: null, operation_id: null, backend: null } }, "Tags reset to auto", convLiveIds()); break;
      case "duplicate": duplicateConversation(e.group); break;
      case "delete": update(e.id, { deleted: true }, "Deleted (restorable until export)"); break;
      case "restore": update(e.id, { deleted: false }, "Restored"); break;
      case "revert": if (confirm("Revert all edits to this example?")) revert([e.id], "Reverted to original"); break;
      case "discard": if (confirm("Discard this added example?")) revert([e.id], "Discarded"); break;
      case "copy-id": copyText(e.id, "ID copied"); break;
      case "copy-output": copyText(JSON.stringify(e.output, null, 2), "Output JSON copied"); break;
      case "reset-tags": update(e.id, { tags: { problem_id: null, operation_id: null, backend: null } }, "Tags reset to auto"); break;
      case "edit-output": startEdit("output"); break;
      case "edit-prompts": startEdit("prompts"); break;
      case "cancel-edit": cancelEdit(); break;
      case "save-output": saveOutput().catch(() => {}); break;
      case "save-prompts": savePrompts().catch(() => {}); break;
      case "save-ctx": saveConvText(S.editing.old, $("#ctx-editor").value).catch(() => {}); break;
      case "format-json": {
        const ta = $("#output-editor");
        try { ta.value = JSON.stringify(JSON.parse(ta.value), null, 2); ta.dispatchEvent(new Event("input")); } catch { toast("Cannot format invalid JSON", true); }
        break;
      }
    }
  });
  $("#detail").addEventListener("change", async (ev) => {
    const csel = ev.target.closest("[data-ctag]");
    if (csel) {
      // Same cascade as a single row, applied to every step of the conversation.
      const key = csel.dataset.ctag;
      const tags = { [key]: csel.value || null };
      const pool = convLiveIds().map((id) => S.byId.get(id));
      if (key === "problem_id" && csel.value) {
        const ops = opsOfProblem(csel.value);
        if (ops.length === 1 && pool.some((x) => x.tags.operation_id !== ops[0])) { tags.operation_id = ops[0]; tags.backend = null; }
        if (!ops.length) { tags.operation_id = null; tags.backend = null; }
      }
      if (key === "operation_id") tags.backend = null;
      await bulk({ tags }, "Tags saved", pool.map((x) => x.id));
      return;
    }
    const sel = ev.target.closest("[data-tag]");
    if (!sel) return;
    const key = sel.dataset.tag;
    const tags = { [key]: sel.value || null };
    if (key === "problem_id" && sel.value) {
      const ops = opsOfProblem(sel.value);
      const e = current();
      if (ops.length === 1 && e.tags.operation_id !== ops[0]) { tags.operation_id = ops[0]; tags.backend = null; }
      if (!ops.length) { tags.operation_id = null; tags.backend = null; }
    }
    if (key === "operation_id") tags.backend = null;
    await update(S.currentId, { tags }, "Tags saved");
  });
  $("#detail").addEventListener("keydown", (ev) => {
    if (ev.target.id === "label-input" && ev.key === "Enter" && ev.target.value.trim()) {
      const e = current();
      update(e.id, { labels: [...e.labels, ev.target.value.trim()] }, "Label added");
    }
    if (ev.target.id === "clabel-input" && ev.key === "Enter" && ev.target.value.trim()) {
      const label = ev.target.value.trim();
      bulk({ labels_add: [label] }, `Label "${label}" added`, convLiveIds());
    }
  });
  $("#detail").addEventListener("focusout", (ev) => {
    if (ev.target.id === "notes-input") {
      const e = current();
      if (e && ev.target.value !== e.notes) update(e.id, { notes: ev.target.value }, "Notes saved");
    }
  });

  // coverage & changes clicks
  $("#coverage-view").addEventListener("click", (ev) => {
    if (ev.target.id === "cov-filtered") { S.coverageFiltered = ev.target.checked; renderCoverage(); return; }
    const cell = ev.target.closest("[data-heat]");
    const impl = ev.target.closest("[data-impl]");
    const q = ev.target.closest("[data-q]");
    const lin = ev.target.closest("[data-lineage]");
    if (cell) {
      const [p, s] = cell.dataset.heat.split("|");
      S.facetSel = { problem: new Set([p]), schema: new Set([s]) };
    } else if (impl) {
      const [op, b] = impl.dataset.impl.split("|");
      S.facetSel = { operation: new Set([op]), backend: new Set([b]) };
    } else if (q) {
      S.facetSel = {};
      S.query = `"${q.dataset.q}"`;
      $("#search").value = S.query;
    } else if (lin) {
      S.facetSel = { lineage: new Set([lin.dataset.lineage === "—" ? NONE : lin.dataset.lineage]) };
    } else return;
    hideTip();
    S.rendered = 0;
    setView("browse");
    refreshAll();
  });
  $("#coverage-view").addEventListener("mousemove", (ev) => {
    const cell = ev.target.closest("[data-heat]");
    if (!cell) return hideTip();
    const [p, s] = cell.dataset.heat.split("|");
    const rows = S.examples.filter((e) => !e.deleted && (e.tags.problem_id || NONE) === p && e.schema === s && (!S.coverageFiltered || S.visibleSet.has(e.id)));
    const tr = rows.filter((e) => e.split === "train").length;
    showTip(ev, `<div>${esc(p === NONE ? "(untagged)" : problemName(p))}</div><div class="muted">${esc(STAGE_LABEL[s])} · ${esc(STAGE_HELP[s])}</div>
      <div><b>${rows.length}</b> example${rows.length === 1 ? "" : "s"} · ${tr} train · ${rows.length - tr} validation</div>`);
  });
  $("#coverage-view").addEventListener("mouseleave", hideTip);
  $("#changes-view").addEventListener("click", (ev) => {
    if (ev.target.id === "changes-export") return openExport();
    const undo = ev.target.closest("[data-undo]");
    if (undo) { ev.stopPropagation(); revert([undo.dataset.undo], "Change undone").then(renderChanges); return; }
    const open = ev.target.closest("[data-open]");
    if (open && S.byId.has(open.dataset.open)) {
      setView("browse");
      S.showDeleted = true;
      $("#deleted-toggle").checked = true;
      refreshAll();
      select(open.dataset.open, { scroll: true });
    }
  });

  // dialogs
  $("#add-body").addEventListener("input", (ev) => {
    const id = ev.target.dataset.btext || ev.target.dataset.bjson;
    if (!id || !B) return;
    bSet(id, ev.target.value);
    if (ev.target.dataset.bjson) bValidate(id);
    renderAddSummary();
  });
  $("#add-body").addEventListener("change", (ev) => {
    const t = ev.target;
    if (!B) return;
    if (t.id === "b-clarify") { B.clarify = t.checked; B.preview = null; renderBuilder(); }
    else if (t.id === "b-split") B.split = t.value;
    else if (t.dataset.gp === "graph") { B.graph.pick = t.value; B.preview = null; renderBuilder(); }
    else if (t.dataset.gp === "domain") { B.graph.domain_id = t.value; B.preview = null; }
    else if (t.dataset.btag) {
      B.tags[t.dataset.btag] = t.value;
      if (t.dataset.btag === "problem_id") { const ops = opsOfProblem(t.value); B.tags.operation_id = ops.length === 1 ? ops[0] : ""; }
      if (t.dataset.btag !== "backend") B.tags.backend = "";
      renderBuilder();
    }
  });
  $("#add-body").addEventListener("click", (ev) => {
    if (!B) return;
    const tpl = ev.target.closest("[data-btpl]");
    if (tpl) { builderTemplate(tpl.dataset.btpl); return; }
    const del = ev.target.closest("[data-bfu-del]");
    if (del) { removeFollowup(+del.dataset.bfuDel); return; }
    if (ev.target.closest('[data-bact="preview"]')) { previewUnderstanding(); return; }
    if (ev.target.closest('[data-gp-act="upload"]')) {
      uploadPickedGraph($("#add-body")).then((pick) => { if (pick && B) { B.graph.pick = pick; B.preview = null; renderBuilder(); } });
      return;
    }
    if (ev.target.closest('[data-bact="add-fu"]')) {
      B.followups.push(newFollowup());
      renderBuilder();
      $(`[data-btext="fu${B.followups.length - 1}-msg"]`)?.focus();
    }
  });
  $("#add-form").addEventListener("submit", (ev) => { if (ev.submitter?.value === "default") submitAdd(ev); });
  $("#graph-form").addEventListener("submit", (ev) => { if (ev.submitter?.value === "default") submitGraphDialog(ev); });
  $("#graph-body").addEventListener("click", (ev) => {
    if (!ev.target.closest('[data-gp-act="upload"]') || !graphDialog) return;
    uploadPickedGraph($("#graph-body")).then((pick) => {
      if (!pick) return;
      graphDialog.pick = pick;
      graphDialog.domain_id = $('#graph-body [data-gp="domain"]').value;
      $("#graph-body").innerHTML = graphPickerHtml(graphDialog);
    });
  });
  $("#dataset-settings-btn").addEventListener("click", openDatasetSettings);
  $("#dataset-settings-form").addEventListener("submit", (ev) => { if (ev.submitter?.value === "default") saveDatasetSettings(ev); });
  $("#ds-delete").addEventListener("click", deleteDataset);
  $("#export-form").addEventListener("submit", (ev) => { if (ev.submitter?.value === "default") submitExport(ev); });

  // keyboard
  document.addEventListener("keydown", (ev) => {
    const tag = ev.target.tagName;
    const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || ev.target.isContentEditable;
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") {
      if (S.editing) {
        ev.preventDefault();
        ({ output: saveOutput, prompts: savePrompts, convq: saveConvQuestion, ctx: () => saveConvText(S.editing.old, $("#ctx-editor").value),
          next: saveNextStep })[S.editing.kind]().catch(() => {});
      }
      return;
    }
    if (ev.key === "Escape") {
      if ($("dialog[open]")) return;
      if (S.editing) { cancelEdit(); return; }
      if (typing) { ev.target.blur(); return; }
      if (S.mode === "conv" && S.rowView && S.view === "browse") { backToConv(); return; }
      $("#facets").classList.remove("open");
      return;
    }
    if (typing || ev.ctrlKey || ev.metaKey || ev.altKey || $("dialog[open]")) return;
    const e = current();
    switch (ev.key) {
      case "/": ev.preventDefault(); $("#search").focus(); $("#search").select(); break;
      case "j": case "ArrowDown": if (S.view === "browse") { ev.preventDefault(); move(1); } break;
      case "k": case "ArrowUp": if (S.view === "browse") { ev.preventDefault(); move(-1); } break;
      case "[": if (S.view === "browse") { ev.preventDefault(); moveStep(-1); } break;
      case "]": if (S.view === "browse") { ev.preventDefault(); moveStep(1); } break;
      case "x":
        if (S.mode === "conv" && S.convKey) {
          const ids = convIds(S.convKey);
          const all = ids.every((id) => S.selected.has(id));
          ids.forEach((id) => (all ? S.selected.delete(id) : S.selected.add(id)));
          renderList(true);
        } else if (e) { S.selected.has(e.id) ? S.selected.delete(e.id) : S.selected.add(e.id); renderList(true); }
        break;
      case "e": if (e) { ev.preventDefault(); startEdit("output"); } break;
      case "q": if (e) { ev.preventDefault(); startEdit(S.mode === "conv" && !S.rowView ? "convq" : "prompts"); } break;
      case "c": if (e) duplicateConversation(e.group); break;
      case "n": ev.preventDefault(); openAdd(); break;
      case "1": case "2": case "3": case "4": if (e) update(e.id, { review: REVIEW_ORDER[+ev.key - 1] }, `Review → ${REVIEW[REVIEW_ORDER[+ev.key - 1]].label}`); break;
      case "Delete": if (e) update(e.id, e.deleted ? { deleted: false } : { deleted: true }, e.deleted ? "Restored" : "Deleted (restorable until export)"); break;
      case "?": $("#help-dialog").showModal(); break;
      case "g": setView(S.view === "coverage" ? "browse" : "coverage"); break;
    }
  });
  window.addEventListener("beforeunload", (ev) => { if (S.editing) { ev.preventDefault(); ev.returnValue = ""; } });
}

// ------------------------------------------------------------------ boot
// Display names and groups come from dataset-names.json; the path stays in the tooltip.
function datasetOptions(list) {
  const option = (d) => `<option value="${esc(d.key)}" title="${esc([d.description, d.path].filter(Boolean).join("\n"))}">${esc(d.name || d.path)} · ${d.rows.toLocaleString()} rows</option>`;
  const groups = new Map();
  for (const d of list) {
    if (!groups.has(d.group || "")) groups.set(d.group || "", []);
    groups.get(d.group || "").push(d);
  }
  return [...groups].map(([label, items]) => (label
    ? `<optgroup label="${esc(label)}">${items.map(option).join("")}</optgroup>` : items.map(option).join(""))).join("")
    + `<option value="${NEW_DATASET}">＋ New empty dataset…</option>`;
}
const NEW_DATASET = "__new_dataset__";

function openNewDataset() {
  $("#dataset-form").reset();
  $("#dataset-location").textContent = `${S.meta?.data_root || "<data root>"}/studio-datasets/`;
  $("#dataset-dialog").showModal();
  $("#dataset-name").focus();
}
async function submitNewDataset(ev) {
  ev.preventDefault();
  const name = $("#dataset-name").value.trim();
  if (!name) return toast("Give the dataset a name", true);
  if (S.editing && !confirm("Discard unsaved edits?")) return;
  try {
    const r = await api("/api/new-dataset", { name, description: $("#dataset-description").value });
    $("#dataset-dialog").close();
    S.datasets = r.datasets;
    $("#dataset-select").innerHTML = datasetOptions(S.datasets);
    resetForDataset();
    await loadExamples();
    toast(`Created "${r.dataset.name}". Add conversations with ＋ Add.`);
  } catch (err) { fail(err); }
}
// Selection, filters and caches belong to one dataset.
function resetForDataset() {
  S.currentId = null; S.convKey = null; S.rowView = false;
  S.selected.clear(); S.facetSel = {}; S.facetFilter = {}; S.editing = null; S.contextCache.clear();
  S.query = ""; $("#search").value = "";
}

async function loadExamples() {
  const d = await api("/api/examples");
  S.dataset = d.dataset;
  S.examples = d.examples.map(prepare);
  S.byId = new Map(S.examples.map((e) => [e.id, e]));
  S.conversations = d.conversations || {};
  S.convContext = new Map();
  S.graphs = null;
  // Which stages this dataset has at all decides what "complete" means for it.
  S.stagesPresent = new Set(S.examples.filter((e) => !e.deleted).map((e) => e.schema));
  $("#dataset-select").value = d.dataset.key;
  $("#dataset-settings-btn").hidden = d.dataset.layout !== "studio";
  refreshAll();
  const hash = decodeURIComponent(location.hash.slice(1));
  const convHash = hash.startsWith("c=") ? hash.slice(2) : null;
  if (convHash && S.mode === "conv" && S.convs.has(convHash)) selectConv(convHash, { scroll: true });
  else if (convHash && S.convs.has(convHash)) select(S.convs.get(convHash).steps[0].id, { scroll: true });
  else if (hash && S.byId.has(hash)) select(hash, { scroll: true });
  else renderDetail();
}

async function init() {
  applyTheme(store.get("theme", null));
  bind();
  try {
    const [ds, meta] = await Promise.all([api("/api/datasets"), api("/api/meta")]);
    S.datasets = ds.datasets;
    S.meta = meta;
    for (const p of meta.catalog.problems) S.problems.set(p.id, p);
    for (const o of meta.catalog.operations) S.operations.set(o.id, o);
    $("#dataset-select").innerHTML = datasetOptions(ds.datasets);
    fillBulkSelects();
    if (ds.current) await loadExamples(); else showNoDataset();
  } catch (err) {
    fail(err);
    $("#status-strip").textContent = "Could not load: " + err.message;
  }
}
// A studio can start with no dataset at all; it offers to create one.
function showNoDataset() {
  S.dataset = null;
  S.examples = [];
  S.byId = new Map();
  $("#dataset-settings-btn").hidden = true;
  $("#status-strip").innerHTML = "<span>No dataset is open.</span>";
  $("#list").innerHTML = '<div class="empty-list">There are no datasets yet.<br><button class="btn primary small" data-new-dataset>＋ New empty dataset</button></div>';
  $("#detail").innerHTML = '<div class="empty-detail"><p>Create a dataset to start writing conversations.</p><p><button class="btn primary" data-new-dataset>＋ New empty dataset</button></p></div>';
}
window.DatasetStudio = { state: S };  // handy for debugging in the console
init();
