#include "numeric.hpp"
#include "pattern_match.hpp"

namespace graphmine::runtime {
namespace {
using namespace family_util;
struct AnomalyPopulation {
  std::vector<ExternalId> ids;
  std::vector<json::object> records;
  std::vector<std::set<VertexIndex>> subsets;
  std::map<ExternalId, std::size_t> indices;
};
AnomalyPopulation population(const Graph& graph, const std::string& target,
                             const json::value& subgraphs, Work& work) {
  AnomalyPopulation result;
  if (target != "subgraph") {
    require(subgraphs.is_null(), "subgraphs applies only to subgraph anomalies");
    if (target == "vertex")
      for (const auto& row : graph.canonical().vertices)
        result.records.push_back(vertex_record_json(row, work));
    else
      for (const auto& row : graph.canonical().edges)
        result.records.push_back(edge_record_json(row, work));
  } else {
    require(subgraphs.is_array(), "Subgraph anomalies need a subgraphs array");
    for (const auto& raw : subgraphs.as_array()) {
      const auto row = object(raw, "subgraph");
      fields(row, {"id", "vertices", "attributes"}, {"id", "vertices"});
      if (row.contains("attributes"))
        require(row.at("attributes").is_object(), "Subgraph attributes must be an object");
      const auto selected = vertices(graph, row.at("vertices"), "subgraph vertices");
      result.subsets.emplace_back(selected.begin(), selected.end());
      result.records.push_back(row);
    }
  }
  for (const auto& row : result.records) {
    const auto id = external_id(row.at("id"));
    require(result.indices.emplace(id, result.ids.size()).second,
            "Anomaly entity IDs must be unique");
    result.ids.push_back(id);
  }
  return result;
}
std::vector<std::size_t> selected_entities(const AnomalyPopulation& population,
                                           const json::value& value) {
  std::vector<std::size_t> result;
  if (value.is_null()) {
    result.resize(population.ids.size());
    std::iota(result.begin(), result.end(), 0);
    return result;
  }
  require(value.is_array(), "Entity selection must be an array");
  std::set<ExternalId> seen;
  for (const auto& raw : value.as_array()) {
    const auto id = external_id(raw);
    const auto found = population.indices.find(id);
    require(found != population.indices.end() && seen.insert(id).second,
            "Entity selection must contain distinct known IDs");
    result.push_back(found->second);
  }
  return result;
}
struct Definition {
  std::string name, measure, field;
};
std::vector<Definition> definitions(const json::value& raw, const std::string& target,
                                    bool directed) {
  require(raw.is_array() && !raw.as_array().empty(),
          "feature_definitions must be a nonempty array");
  std::set<std::string> names;
  const std::map<std::string, std::set<std::string>> supported{
      {"vertex",
       {"degree", "in_degree", "out_degree", "strength", "in_strength", "out_strength",
        "triangle_count", "ego_edge_count", "event_count", "in_event_count", "out_event_count",
        "numeric_attribute"}},
      {"edge",
       {"edge_weight", "source_degree", "target_degree", "common_neighbors", "numeric_attribute"}},
      {"subgraph", {"vertex_count", "edge_count", "density", "weight_sum", "numeric_attribute"}}};
  std::vector<Definition> result;
  for (const auto& value : raw.as_array()) {
    const auto row = object(value, "feature definition");
    fields(row, {"name", "measure", "field"}, {"name", "measure"});
    Definition d{string(row.at("name"), "name"), string(row.at("measure"), "measure"), ""};
    require(!d.name.empty() && names.insert(d.name).second,
            "Feature names must be nonempty and unique");
    require(supported.at(target).count(d.measure), "Unsupported anomaly feature measure");
    require(directed || (d.measure.rfind("in_", 0) != 0 && d.measure.rfind("out_", 0) != 0),
            "In/out features require directed input");
    require(!directed || (d.measure != "triangle_count" && d.measure != "ego_edge_count" &&
                          d.measure != "common_neighbors"),
            "Triangle, ego and common-neighbor features require undirected input");
    if (d.measure == "numeric_attribute") {
      require(row.contains("field"), "Numeric attribute needs field");
      d.field = string(row.at("field"), "field");
      require(!d.field.empty() && d.field.front() != '.' && d.field.back() != '.' &&
                  d.field.find("..") == std::string::npos,
              "Invalid attribute field path");
    } else
      require(!row.contains("field"), "field applies only to numeric_attribute");
    result.push_back(d);
  }
  return result;
}
numeric::Matrix anomaly_features(const Graph& graph, const std::string& target,
                                 const AnomalyPopulation& population,
                                 const std::vector<std::size_t>& selected,
                                 const std::vector<Definition>& definitions, Work& work) {
  using namespace numeric;
  const auto n = graph.vertex_count();
  const auto simple = edges(graph, false, work, false, true),
             weighted = edges(graph, true, work, false, true);
  const auto adj = adjacency(graph, work);
  std::vector<Exact> degree(n, 0), in_degree(n, 0), out_degree(n, 0), strength(n, 0),
      in_strength(n, 0), out_strength(n, 0), events(n, 0), in_events(n, 0), out_events(n, 0);
  for (const auto& edge : simple) {
    ++degree[edge.u];
    ++degree[edge.v];
    ++out_degree[edge.u];
    ++in_degree[edge.v];
  }
  for (const auto& edge : weighted) {
    strength[edge.u] += edge.weight;
    strength[edge.v] += edge.weight;
    out_strength[edge.u] += edge.weight;
    in_strength[edge.v] += edge.weight;
  }
  for (const auto& edge : graph.canonical().edges) {
    const auto u = graph.dense_index(edge.source), v = graph.dense_index(edge.target);
    ++events[u];
    if (u != v) ++events[v];
    ++out_events[u];
    ++in_events[v];
  }
  Matrix result(selected.size(), definitions.size(), work);
  for (std::size_t i = 0; i < selected.size(); ++i)
    for (std::size_t j = 0; j < definitions.size(); ++j) {
      work.tick();
      const auto entity = selected[i];
      const auto& record = population.records[entity];
      const auto& definition = definitions[j];
      const auto& measure = definition.measure;
      Exact value = 0;
      if (measure == "numeric_attribute") {
        const auto* attribute = record_field(record, "attributes." + definition.field);
        require(attribute, "Entity is missing a numeric feature field");
        result(i, j) = float64(*attribute, "feature");
        continue;
      }
      if (target == "vertex") {
        const auto v = graph.dense_index(population.ids[entity]);
        if (measure == "degree")
          value = degree[v];
        else if (measure == "in_degree")
          value = in_degree[v];
        else if (measure == "out_degree")
          value = out_degree[v];
        else if (measure == "strength")
          value = strength[v];
        else if (measure == "in_strength")
          value = in_strength[v];
        else if (measure == "out_strength")
          value = out_strength[v];
        else if (measure == "event_count")
          value = events[v];
        else if (measure == "in_event_count")
          value = in_events[v];
        else if (measure == "out_event_count")
          value = out_events[v];
        else if (measure == "triangle_count") {
          for (std::size_t a = 0; a < adj[v].size(); ++a)
            for (std::size_t b = a + 1; b < adj[v].size(); ++b) {
              work.tick();
              if (adjacent(adj, adj[v][a], adj[v][b])) ++value;
            }
        } else {
          std::set<VertexIndex> members(adj[v].begin(), adj[v].end());
          members.insert(v);
          for (const auto& edge : simple) {
            work.tick();
            if (edge.u != edge.v && members.count(edge.u) && members.count(edge.v)) ++value;
          }
        }
      } else if (target == "edge") {
        const auto u = graph.dense_index(external_id(record.at("source"))),
                   v = graph.dense_index(external_id(record.at("target")));
        if (measure == "edge_weight") {
          result(i, j) =
              record.contains("weight") ? float64(record.at("weight"), "edge weight") : 1;
          continue;
        }
        if (measure == "source_degree")
          value = degree[u];
        else if (measure == "target_degree")
          value = degree[v];
        else
          for (const auto neighbor : adj[u]) {
            work.tick();
            if (neighbor != u && neighbor != v && adjacent(adj, v, neighbor)) ++value;
          }
      } else {
        const auto& members = population.subsets[entity];
        if (measure == "vertex_count")
          value = members.size();
        else if (measure == "density") {
          if (members.size() > 1) {
            for (const auto& edge : simple) {
              work.tick();
              if (edge.u != edge.v && members.count(edge.u) && members.count(edge.v)) ++value;
            }
            value *= graph.directed() ? 1 : 2;
            value /= Exact(members.size()) * (members.size() - 1);
          }
        } else
          for (const auto& edge : graph.canonical().edges) {
            work.tick();
            if (members.count(graph.dense_index(edge.source)) &&
                members.count(graph.dense_index(edge.target)))
              value += measure == "edge_count" ? Exact(1) : Exact(edge.weight.value_or(1));
          }
      }
      result(i, j) = finite(value.convert_to<long double>());
      if (denominator(value) == 1)
        require(Exact(result(i, j)) == value, "Integer anomaly feature loses float64 precision");
    }
  return result;
}
}  // namespace
json::object graph_anomalies(const Graph& graph, const json::object& args, const std::string&, int,
                             Work& work) {
  using namespace family_util;
  using namespace numeric;
  fields(args,
         {"anomaly_target", "feature_definitions", "normality_reference", "scoring_definition",
          "candidate_entities", "subgraphs", "top_k"},
         {"anomaly_target", "feature_definitions", "normality_reference", "scoring_definition",
          "top_k"});
  const auto target = choice(args, "anomaly_target", "vertex", {"vertex", "edge", "subgraph"});
  const auto features = definitions(args.at("feature_definitions"), target, graph.directed());
  const auto dimension = features.size(), k = natural(args, "top_k", 1, 1);
  const auto subgraphs = args.contains("subgraphs") ? args.at("subgraphs") : json::value(nullptr),
             candidates = args.contains("candidate_entities") ? args.at("candidate_entities")
                                                              : json::value(nullptr);
  const auto entities = population(graph, target, subgraphs, work);
  const auto selected = selected_entities(entities, candidates);
  const auto scoring = object(args.at("scoring_definition"), "scoring_definition"),
             reference = object(args.at("normality_reference"), "normality_reference");
  fields(scoring, {"method", "feature_weights", "minimum_scale"}, {"method"});
  const auto method = choice(scoring, "method", "standardized_l2",
                             {"standardized_l1", "standardized_l2", "max_abs_z"}),
             kind = choice(reference, "kind", "population", {"population", "statistics"});
  require(reference.contains("kind"), "normality_reference needs kind");
  auto vector = [&](const json::value& raw, const char* name) {
    require(raw.is_array() && raw.as_array().size() == dimension,
            std::string(name) + " must match the feature dimension");
    std::vector<double> result;
    for (const auto& value : raw.as_array()) result.push_back(float64(value, name));
    return result;
  };
  const auto weights = scoring.contains("feature_weights")
                           ? vector(scoring.at("feature_weights"), "feature_weights")
                           : std::vector<double>(dimension, 1);
  const auto floor =
      scoring.contains("minimum_scale") ? float64(scoring.at("minimum_scale"), "minimum_scale") : 0;
  require(
      floor >= 0 && std::all_of(weights.begin(), weights.end(), [](double w) { return w >= 0; }),
      "Feature weights and minimum_scale must be nonnegative");
  std::vector<double> location(dimension), scale(dimension), origin(dimension),
      mean_delta(dimension, 0);
  bool has_reference = true;
  json::value reference_count = nullptr, reference_hash = nullptr;
  if (kind == "statistics") {
    fields(reference, {"kind", "location", "scale"}, {"kind", "location", "scale"});
    location = origin = vector(reference.at("location"), "location");
    scale = vector(reference.at("scale"), "scale");
    require(std::all_of(scale.begin(), scale.end(), [](double s) { return s >= 0; }),
            "Reference scale must be nonnegative");
  } else {
    fields(reference, {"kind", "graph", "entities", "subgraphs"}, {"kind"});
    std::optional<Graph> external;
    if (reference.contains("graph")) external.emplace(parse_graph(reference.at("graph")));
    const auto& source = external ? *external : graph;
    require(source.directed() == graph.directed(), "Reference and candidate direction must match");
    const auto population_data =
        population(source, target,
                   reference.contains("subgraphs") ? reference.at("subgraphs")
                   : external                      ? json::value(nullptr)
                                                   : subgraphs,
                   work);
    const auto reference_ids =
        selected_entities(population_data, reference.contains("entities") ? reference.at("entities")
                                                                          : json::value(nullptr));
    reference_count = reference_ids.size();
    reference_hash = external ? input_fingerprint(reference.at("graph")) : work.input_fingerprint;
    require(!reference_ids.empty() || selected.empty(),
            "Reference population must not be empty when candidates exist");
    has_reference = !reference_ids.empty();
    if (has_reference) {
      const auto values =
          anomaly_features(source, target, population_data, reference_ids, features, work);
      for (std::size_t c = 0; c < dimension; ++c) {
        origin[c] = values(0, c);
        long double sum = 0;
        for (std::size_t r = 0; r < values.rows; ++r) {
          work.tick();
          sum += static_cast<long double>(values(r, c)) - origin[c];
        }
        mean_delta[c] = finite(sum / values.rows);
        location[c] = finite(static_cast<long double>(origin[c]) + mean_delta[c]);
        long double variance = 0;
        for (std::size_t r = 0; r < values.rows; ++r) {
          const auto delta = (static_cast<long double>(values(r, c)) - origin[c]) - mean_delta[c];
          variance += delta * delta;
        }
        scale[c] = finite(std::sqrt(variance / values.rows));
      }
    }
  }
  const auto values = anomaly_features(graph, target, entities, selected, features, work);
  Matrix contributions(values.rows, dimension, work);
  std::vector<double> scores(values.rows, 0);
  for (std::size_t r = 0; r < values.rows; ++r) {
    long double score = 0;
    for (std::size_t c = 0; c < dimension; ++c) {
      work.tick();
      if (!weights[c] || !has_reference) continue;
      const long double delta =
          (static_cast<long double>(values(r, c)) - origin[c]) - mean_delta[c];
      const auto denominator = std::max(scale[c], floor);
      require(denominator > 0 || delta == 0,
              "Active feature differs from a zero-variance reference; declare minimum_scale");
      const auto z = denominator > 0 ? delta / denominator : 0;
      contributions(r, c) =
          finite(weights[c] * (method == "standardized_l2" ? z * z : std::abs(z)));
      score = method == "max_abs_z" ? std::max(score, static_cast<long double>(contributions(r, c)))
                                    : score + contributions(r, c);
    }
    scores[r] = finite(method == "standardized_l2" ? std::sqrt(score) : score);
  }
  std::vector<std::size_t> order(selected.size());
  std::iota(order.begin(), order.end(), 0);
  std::sort(order.begin(), order.end(), [&](auto a, auto b) {
    return scores[a] == scores[b] ? entities.ids[selected[a]] < entities.ids[selected[b]]
                                  : scores[a] > scores[b];
  });
  if (order.size() > k) order.resize(k);
  json::array rows;
  for (const auto i : order) {
    json::object feature_values, feature_contributions;
    for (std::size_t c = 0; c < dimension; ++c) {
      feature_values[features[c].name] = values(i, c);
      feature_contributions[features[c].name] = contributions(i, c);
    }
    rows.push_back(json::object{{"entity", id_json(entities.ids[selected[i]])},
                                {"anomaly_target", target},
                                {"rank", rows.size() + 1},
                                {"score", scores[i]},
                                {"feature_values", feature_values},
                                {"feature_contributions", feature_contributions}});
  }
  auto as_json = [](const std::vector<double>& values) {
    json::array output;
    for (double value : values) output.push_back(value);
    return output;
  };
  json::object stats{
      {"location", has_reference ? json::value(as_json(location)) : json::value(nullptr)},
      {"scale", has_reference ? json::value(as_json(scale)) : json::value(nullptr)},
      {"ddof", 0},
      {"centering_origin", has_reference ? json::value(as_json(origin)) : json::value(nullptr)},
      {"mean_delta", has_reference ? json::value(as_json(mean_delta)) : json::value(nullptr)}};
  work.output(rows.size() * (1 + 2 * dimension) + 4 * dimension);
  auto ranking = result_port("entity_ranking", rows, rows.size() == selected.size());
  ranking["scope"] = "top_k_of_scored_population";
  auto parameters = args;
  parameters["candidate_entities"] = candidates;
  parameters["subgraphs"] = subgraphs;
  auto result = output(parameters,
                       {{"ranked_anomalies", rows},
                        {"scored_entity_count", selected.size()},
                        {"complete", true},
                        {"reference_statistics", stats}},
                       {{"ranking", ranking}}, true, "numerical");
  result["diagnostics"] =
      json::object{{"reference_kind", kind},
                   {"reference_population_count", reference_count},
                   {"reference_graph_fingerprint", reference_hash},
                   {"minimum_scale", floor},
                   {"score_interpretation", "deviation_from_declared_reference_not_ground_truth"},
                   {"edge_identity", "original_event_instances"},
                   {"structural_degree", "parallel_collapsed_self_loop_counts_twice"},
                   {"event_count", "incident_event_instances_self_loop_counts_once"}};
  return result;
}
}  // namespace graphmine::runtime
