#include "learning.hpp"

namespace graphmine::runtime {
json::object graph_condensation(const Graph& graph, const json::object& args, const std::string&,
                                int, Work& work) {
  using namespace family_util;
  using namespace learning;
  using namespace numeric;
  fields(args,
         {"synthetic_vertex_budget", "feature_key", "label_key", "split_key", "method", "seed",
          "method_parameters"},
         {"synthetic_vertex_budget", "method"});
  choice(args, "method", "gradient_matching_linear_sgc_v1", {"gradient_matching_linear_sgc_v1"});
  require(!graph.directed(), "Graph condensation requires undirected input");
  for (const auto& edge : graph.canonical().edges) {
    require(edge.source != edge.target, "Graph condensation rejects self-loops");
    require(edge.weight.value_or(1) >= 0, "Condensation weights must be nonnegative");
  }
  const auto budget = natural(args, "synthetic_vertex_budget", 1, 1);
  auto key = [&](const char* name, const char* fallback) {
    const auto result = args.contains(name) ? string(args.at(name), name) : std::string(fallback);
    require(!result.empty(), std::string(name) + " must not be empty");
    return result;
  };
  const auto feature_key = key("feature_key", "features"), label_key = key("label_key", "label"),
             split_key = key("split_key", "split");
  require(feature_key != label_key && feature_key != split_key && label_key != split_key,
          "Feature, label and split keys must be distinct");
  const auto options = args.contains("method_parameters")
                           ? object(args.at("method_parameters"), "method_parameters")
                           : json::object{};
  fields(options,
         {"optimizer", "epochs", "learning_rate", "l2", "tolerance", "layers", "parallel_edges",
          "downstream_epochs", "downstream_learning_rate", "downstream_l2", "evaluation_seeds"});
  choice(options, "parallel_edges", "sum", {"sum"});
  const auto layers = natural(options, "layers", 1, 1);
  Dataset original;
  std::vector<json::value> feature_values;
  std::vector<std::size_t> train;
  std::set<ExternalId> class_set;
  std::size_t held_out = 0;
  for (const auto& vertex : graph.canonical().vertices) {
    const auto record = vertex_record_json(vertex, work);
    const auto *features = record_field(record, "attributes." + feature_key),
               *label = record_field(record, "attributes." + label_key),
               *split_value = record_field(record, "attributes." + split_key);
    require(features && split_value, "Every condensation vertex needs features and a split");
    const auto name = string(*split_value, "split");
    require(name == "train" || name == "validation" || name == "test" || name == "inference",
            "Unknown condensation split");
    original.ids.push_back(vertex.id);
    original.splits.push_back(name);
    original.targets.push_back(label ? *label : json::value(nullptr));
    feature_values.push_back(*features);
    if (name == "train") {
      require(label, "Every training vertex needs a class label");
      class_set.insert(external_id(*label));
      train.push_back(original.ids.size() - 1);
    } else if ((name == "validation" || name == "test") && label && !label->is_null())
      ++held_out;
  }
  require(!train.empty() && budget <= train.size(),
          "Synthetic budget must not exceed the positive training vertex count");
  require(held_out > 0,
          "This condensation profile requires held-out labeled validation or test vertices for "
          "utility evaluation");
  std::vector<ExternalId> classes(class_set.begin(), class_set.end());
  const auto k = classes.size();
  require(budget >= k,
          "This gradient-matching profile needs at least one synthetic vertex per training class");
  std::map<ExternalId, std::size_t> class_index;
  for (std::size_t i = 0; i < k; ++i) class_index[classes[i]] = i;
  original.features = feature_rows(feature_values, work);
  const auto d = original.features.cols, n = original.features.rows;
  // Weighted transductive SGC representation. Parallel weights sum; one unit
  // self message is added after rejecting original loops.
  const auto normalized = edges(graph, true, work);
  std::vector<std::vector<std::pair<VertexIndex, double>>> neighbors(n);
  std::vector<long double> degrees(n, 1);
  for (const auto& edge : normalized)
    if (edge.weight > 0) {
      const auto weight = finite(edge.weight.convert_to<long double>());
      require(weight > 0, "Positive condensation weight underflowed");
      neighbors[edge.u].emplace_back(edge.v, weight);
      neighbors[edge.v].emplace_back(edge.u, weight);
      degrees[edge.u] += weight;
      degrees[edge.v] += weight;
    }
  for (std::size_t layer = 0; layer < layers; ++layer) {
    Matrix next(n, d, work);
    for (std::size_t v = 0; v < n; ++v)
      for (std::size_t c = 0; c < d; ++c) {
        long double value = original.features(v, c) / degrees[v];
        for (const auto& [u, weight] : neighbors[v]) {
          work.tick();
          value += weight / degrees[v] * original.features(u, c);
        }
        next(v, c) = finite(value);
      }
    original.features = std::move(next);
  }
  std::vector<std::size_t> counts(k, 0), allocation(k, 1), labels;
  for (const auto v : train) ++counts[class_index.at(external_id(original.targets[v]))];
  for (std::size_t allocated = k; allocated < budget; ++allocated) {
    std::size_t best = 0;
    long double difference = -std::numeric_limits<long double>::infinity();
    for (std::size_t c = 0; c < k; ++c) {
      const auto deficit =
          static_cast<long double>(counts[c]) * budget / train.size() - allocation[c];
      if (deficit > difference) {
        difference = deficit;
        best = c;
      }
    }
    ++allocation[best];
  }
  for (std::size_t c = 0; c < k; ++c)
    for (std::size_t i = 0; i < allocation[c]; ++i) labels.push_back(c);
  Matrix target(d + 1, k, work), initial(budget, d, work);
  const auto raw_seed = args.contains("seed") ? args.at("seed") : json::value(0);
  require(raw_seed.is_int64() || raw_seed.is_uint64(), "seed must be an integer");
  NativeRandom random(json::object{{"random_seed", raw_seed}});
  for (const auto v : train) {
    const auto label = class_index.at(external_id(original.targets[v]));
    for (std::size_t c = 0; c <= d; ++c)
      for (std::size_t cls = 0; cls < k; ++cls) {
        work.tick();
        target(c, cls) +=
            (c == d ? 1 : original.features(v, c)) * (1.0 / k - (cls == label)) / train.size();
      }
  }
  for (std::size_t s = 0; s < budget; ++s)
    for (std::size_t c = 0; c < d; ++c) {
      long double mean = 0;
      for (const auto v : train)
        if (class_index.at(external_id(original.targets[v])) == labels[s])
          mean += original.features(v, c);
      initial(s, c) = finite(mean / counts[labels[s]] + random_initial(random));
    }
  const auto configuration = training(options);
  auto gradient_at_zero = [&](const std::vector<double>& parameters) {
    Matrix gradient(d + 1, k, work);
    for (std::size_t s = 0; s < budget; ++s)
      for (std::size_t c = 0; c <= d; ++c)
        for (std::size_t cls = 0; cls < k; ++cls) {
          work.tick();
          gradient(c, cls) +=
              (c == d ? 1 : parameters[s + budget * c]) * (1.0 / k - (cls == labels[s])) / budget;
        }
    return gradient;
  };
  Objective objective = [&](const auto& parameters, auto& gradient) {
    const auto candidate = gradient_at_zero(parameters);
    long double loss = 0;
    for (std::size_t c = 0; c <= d; ++c)
      for (std::size_t cls = 0; cls < k; ++cls) {
        const long double difference = static_cast<long double>(candidate(c, cls)) - target(c, cls);
        loss += difference * difference / 2;
        if (c < d)
          for (std::size_t s = 0; s < budget; ++s) {
            work.tick();
            gradient[s + budget * c] +=
                finite(difference * (1.0 / k - (cls == labels[s])) / budget);
          }
      }
    for (std::size_t i = 0; i < parameters.size(); ++i) {
      loss += configuration.l2 * static_cast<long double>(parameters[i]) * parameters[i] / 2;
      gradient[i] += configuration.l2 * parameters[i];
    }
    return finite(loss);
  };
  const auto fit = minimize(initial.values, configuration, objective, work);
  initial.values = fit.parameters;
  json::array synthetic_vertices;
  std::vector<ExternalId> synthetic_ids;
  const auto& source_hash = work.input_fingerprint;
  std::set<ExternalId> existing(original.ids.begin(), original.ids.end());
  for (std::size_t s = 0; s < budget; ++s) {
    std::string id = "synthetic:" + source_hash + ":" + std::to_string(s);
    while (existing.count(ExternalId(id))) id = "synthetic:" + id;
    synthetic_ids.emplace_back(id);
    existing.insert(synthetic_ids.back());
    json::array values;
    for (std::size_t c = 0; c < d; ++c) values.push_back(initial(s, c));
    synthetic_vertices.push_back(json::object{
        {"id", id},
        {"attributes",
         {{feature_key, values}, {label_key, id_json(classes[labels[s]])}, {split_key, "train"}}}});
  }
  json::object synthetic_graph{
      {"graph",
       {{"id", "condensed:" + source_hash},
        {"directed", false},
        {"allows_self_loops", false},
        {"allows_parallel_edges", false},
        {"attributes",
         {{"adjacency_policy", "fixed edgeless graph; model adds one unit self message"},
          {"identity_policy", "new synthetic identities; no quotient mapping"}}}}},
      {"vertices", synthetic_vertices},
      {"edges", json::array{}}};
  const auto raw_evaluation_seeds = options.contains("evaluation_seeds")
                                        ? options.at("evaluation_seeds")
                                        : json::value(json::array{raw_seed});
  require(raw_evaluation_seeds.is_array() && !raw_evaluation_seeds.as_array().empty(),
          "evaluation_seeds must be a nonempty integer array");
  json::object downstream{
      {"epochs", natural(options, "downstream_epochs", 200, 1)},
      {"learning_rate", options.contains("downstream_learning_rate")
                            ? options.at("downstream_learning_rate")
                            : json::value(1)},
      {"l2", options.contains("downstream_l2") ? options.at("downstream_l2") : json::value(0.001)},
      {"standardize", false},
      {"prediction_split", "all"}};
  json::array runs;
  std::map<std::string, std::vector<double>> utility;
  std::set<std::uint64_t> seen_evaluation_seeds;
  for (const auto& seed : raw_evaluation_seeds.as_array()) {
    require(seen_evaluation_seeds.insert(uint(seed, "evaluation seed")).second,
            "Evaluation seeds must be distinct");
    downstream["random_seed"] = seed;
    auto baseline = supervised(original, "classification", downstream, work);
    Dataset condensed;
    condensed.ids = synthetic_ids;
    condensed.splits.assign(budget, "train");
    for (std::size_t s = 0; s < budget; ++s)
      condensed.targets.push_back(id_json(classes[labels[s]]));
    condensed.ids.insert(condensed.ids.end(), original.ids.begin(), original.ids.end());
    condensed.features = Matrix(budget + n, d, work);
    for (std::size_t s = 0; s < budget; ++s)
      for (std::size_t c = 0; c < d; ++c) condensed.features(s, c) = initial(s, c);
    for (std::size_t v = 0; v < n; ++v) {
      for (std::size_t c = 0; c < d; ++c)
        condensed.features(budget + v, c) = original.features(v, c);
      condensed.splits.push_back(original.splits[v] == "train" ? "inference" : original.splits[v]);
      condensed.targets.push_back(original.splits[v] == "train" ? json::value(nullptr)
                                                                : original.targets[v]);
    }
    auto synthetic = supervised(std::move(condensed), "classification", downstream, work);
    for (const auto* split_name : {"validation", "test"})
      for (const auto* kind : {"baseline", "condensed"}) {
        const auto& result = std::string(kind) == "baseline" ? baseline : synthetic;
        const auto& accuracy =
            result.at("metrics").as_object().at(split_name).as_object().at("accuracy");
        if (!accuracy.is_null())
          utility[std::string(kind) + "_" + split_name].push_back(accuracy.as_double());
      }
    runs.push_back(json::object{{"seed", seed}, {"baseline", baseline}, {"condensed", synthetic}});
  }
  json::object aggregate;
  for (const auto& [name, values] : utility) {
    long double mean = 0, variance = 0;
    for (double value : values) mean += value;
    mean /= values.size();
    for (double value : values) variance += (value - mean) * (value - mean);
    aggregate[name] = {{"accuracy_mean", finite(mean)},
                       {"accuracy_population_std", finite(std::sqrt(variance / values.size()))},
                       {"run_count", values.size()}};
  }
  auto training_metadata =
      summary(fit, configuration,
              "half squared Frobenius difference between full-batch softmax gradients at zero "
              "readout parameters, including intercept, plus l2/2 synthetic feature norm");
  training_metadata["method"] = "gradient_matching_linear_sgc_v1";
  training_metadata["seed"] = random.seed;
  training_metadata["layers"] = layers;
  training_metadata["synthetic_vertex_budget"] = budget;
  training_metadata["training_vertex_count"] = train.size();
  training_metadata["target_gradient"] = matrix(target);
  training_metadata["synthetic_gradient"] = matrix(gradient_at_zero(fit.parameters));
  training_metadata["adjacency_policy"] =
      "fixed edgeless synthetic adjacency; learned features represent weighted SGC training "
      "features";
  training_metadata["original_propagation"] =
      "row-normalized sum of nonnegative parallel weights plus a unit self message";
  training_metadata["synthetic_label_policy"] =
      "at least one vertex per training class, then largest deficit against training class "
      "proportions; typed class ordering resolves ties";
  training_metadata["fit_split"] = "training labels only";
  training_metadata["transductive_access"] =
      "unlabeled features and topology from every original vertex";
  training_metadata["preprocessing"] = "none";
  training_metadata["downstream_model"] = downstream;
  work.output(budget * (d + 1) + 2 * (d + 1) * k + fit.history.size() +
              raw_evaluation_seeds.as_array().size() * (2 * n + budget) * (d + 1 + k));
  auto parameters = args;
  parameters["feature_key"] = feature_key;
  parameters["label_key"] = label_key;
  parameters["split_key"] = split_key;
  parameters["seed"] = raw_seed;
  parameters["method_parameters"] = options;
  return output(parameters,
                {{"synthetic_graph", synthetic_graph},
                 {"training_metadata", training_metadata},
                 {"utility_metrics",
                  {{"runs", runs},
                   {"aggregate", aggregate},
                   {"variance_ddof", 0},
                   {"evaluation_protocol",
                    "same linear softmax readout, optimizer budget and seed for full training set "
                    "versus synthetic training set; metrics on original held-out labels"}}}},
                {{"graph", result_port("graph", synthetic_graph)}}, true, "learned_estimate");
}
}  // namespace graphmine::runtime
