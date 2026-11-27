"use strict";
// Shared by preview and recorded workflow revisions. Never consult the active file.
window.GraphMineSemanticDetails = ({node, W, source, versionId}) => {
  const card = node("section", {class: "semantic-card", "aria-label": "Model usage and provenance"});
  card.append(node("h3", {}, "Model usage"));
  card.classList.toggle("semantic-plain", !source.simulation && !source.model_dependent_input);
  const metrics = node("dl", {class: "semantic-metrics"});
  const line = (label, value) => { const pair = node("div"); pair.append(node("dt", {}, label), node("dd", {}, String(value ?? "Not recorded"))); metrics.append(pair); };
  const settings = source.settings || {}, usage = source.usage || {};
  card.append(node("p", {class: "semantic-notice"}, source.simulation
    ? "This input includes simulated model judgments. Mock answers do not establish real classifications."
    : source.model_dependent_input ? "A model helped select or derive this input. Calculation quality does not establish the accuracy of those judgments."
      : "Structural refinement of a saved snapshot. This run made no model judgments."));
  line("Model", settings.model || "No model steps");
  line("Engine calls observed", usage.calls ?? "Not reported");
  line(settings.query_wide_call_limit_supported ? "Total HTTP request limit" : "Limit per expression (not query total)", settings.request_limit ?? settings.llm_max_calls);
  line("Selected inputs (not completed judgments)", usage.llm_rows ?? "Not reported");
  if (usage.completed_rows != null) line("Completed answer evaluations", usage.completed_rows);
  if (usage.stored_hits != null) line("Retained answers reused", usage.stored_hits);
  line("Cached inputs (includes retained)", usage.cache_hits ?? "Not reported");
  line("Provider HTTP requests", settings.http_requests);
  line("Independently retained answers", settings.answers_retained);
  line("Output rows", source.row_count);
  line("Duration", source.duration_ms == null ? null : `${(source.duration_ms / 1000).toFixed(2)} seconds`);
  line("Completed", source.fetched_at);
  card.append(metrics);
  const details = node("details"); details.append(node("summary", {}, "Refinement provenance"));
  details.append(node("pre", {tabindex: "0"}, W.stringify({version_id: versionId ?? null, base_version_id: source.base_version_id ?? null,
    base_sha256: source.base_sha256 ?? null, query: source.query ?? null, parameters: source.parameters ?? null,
    projection: source.projection ?? null, directed: source.directed ?? null,
    weight_property: source.weight_property ?? null, steps: source.steps ?? null, engine: source.engine ?? null,
    settings, usage, completion_state: source.completion_state ?? null, parent: source.parent ? {
      version_id: source.parent.version_id ?? null, sha256: source.parent.sha256 ?? null,
      query: source.parent.source?.query ?? null, parameters: source.parent.source?.parameters ?? null,
    } : null}, true)));
  card.append(details, node("p", {class: "source-hint"}, "Call estimates and per-row judgment inspection are unavailable. Cache policy and reuse counts above describe this recorded run."));
  if (source.base_version_id && source.query) {
    const rerun = node("button", {type: "button", class: "secondary"}, "Run again without saved answers");
    rerun.onclick = () => document.dispatchEvent(new CustomEvent("graphmine:refine-snapshot", {detail: {baseId: source.base_version_id, recorded: source}}));
    card.append(rerun, node("p", {class: "source-hint"}, "Opens the recorded query on its original snapshot for review. Running creates another version using current access and limits."));
  }
  return card;
};

window.GraphMineSemanticTemplates = schema => {
  const ident = value => "`" + value.replaceAll("`", "``") + "`";
  const literal = value => "'" + value.replaceAll("\\", "\\\\").replaceAll("'", "\\'") + "'";
  const property = schema.vertex_properties.find(p => p.source_property === "text" && p.type === "STRING") || schema.vertex_properties.find(p => p.type === "STRING");
  const input = property ? `n.${ident(property.name)}` : "graph_id(n)";
  const condition = schema.labels.length ? `\nWHERE has_label(n, ${literal(schema.labels[0])})` : "";
  const rows = `MATCH (n:Vertex)${condition}`;
  // Prompt placeholders accept variables, not quoted properties or arbitrary functions.
  const modelRows = `${rows}\nWITH n, ${input} AS value`;
  const templates = [
    ["plain", "Plain snapshot read", `${rows}\nRETURN n`],
    ["extract", "Mock extraction · llm", `${modelRows}\nRETURN n, llm('mock', 'Describe {{value}} {answer STRING}') AS answer`],
    ["filter", "Mock filter · llm", `${modelRows}\nWHERE llm('mock', 'Keep this item? {{value}} {keep BOOLEAN}')\nRETURN n`],
    ["score", "Mock ranking · llm_score", `${modelRows}\nRETURN n, llm_score('mock', 'Rate {{value}}', 0, 5) AS score\nORDER BY score DESC`],
    ["aggregate", "Mock group summary · llm_agg", `${rows}\nRETURN labels_of(n) AS labels, llm_agg(${input}, 'mock', 'Summarize {answer STRING}') AS answer`],
    ["sg_agg", "Mock subgraph summary · llm_sg_agg", "MATCH (n:Vertex)\nRETURN llm_sg_agg(n, 'mock', 'Summarize {answer STRING}') AS answer"],
  ];
  if (schema.relationships.length) {
    const rel = ident(schema.relationships[0].table);
    templates.push(
      ["subgraph", "Mock subgraph input", `MATCH p=(a:Vertex)-[:${rel}]->(b:Vertex)\nWITH subgraph(collect(p)) AS g\nRETURN llm('mock', 'Describe {{g}} {answer STRING}') AS answer`],
      ["path", "Mock path summary · llm_path_agg", `MATCH p=(a:Vertex)-[:${rel}]->(b:Vertex)\nRETURN llm_path_agg(p, 'mock', 'Summarize {answer STRING}') AS answer`],
      ["path_filter", "Mock path-step condition", `MATCH p=(a:Vertex)-[:${rel}* 1..2 (e, n | WHERE llm('mock', 'Keep this step from {{start_node(e)}} to {{end_node(e)}}? {keep BOOLEAN}'))]->(b:Vertex)\nRETURN p`],
      ["previous", "Mock consecutive path steps", `MATCH p=(a:Vertex)-[:${rel}* 2..3 (e, n | WHERE llm('mock', 'Continue from {{start_node(previous(e))}} to {{end_node(e)}}? {keep BOOLEAN}'))]->(b:Vertex)\nRETURN p`],
      ["state", "Mock carried path state", `MATCH p=(a:Vertex)-[:${rel}* 1..2 (e, n | STATE s = llm('mock', 'Update {{s}} for {{n}} {state STRING}') INITIAL 'start' WHERE s <> 'stop')]->(b:Vertex)\nRETURN p, s`],
    );
  }
  return templates;
};
